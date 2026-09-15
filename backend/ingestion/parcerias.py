"""GESTAO DE PARCERIAS do Transferegov.br -> tabela `parcerias_propostas`.

⭐ A FONTE ONDE A EMENDA DE SAUDE PASSOU A VIVER. O modulo de Parcerias foi
publicado no Comunicado no 23/2026 do MGI e **nao substitui o SICONV** — os
convenios discricionarios continuam nos dumps CSV que `transferegov_opendata.py`
le. Ele e onde as transferencias sao processadas de 2024 em diante: dos 176
programas publicados, **144 sao Transferencias Fundo a Fundo da Saude** (medido
em 06/09/2026). Era o unico instrumento federal que a plataforma nao enxergava.

A cadeia, conferida com dado real (Nova Palma, proposta 75376):

    /proposta?cd_ibge_recebedor=4313102 ..... 11 propostas, R$ 2,18 mi
      └─ ds_objeto "AQUISICAO DE EQUIPAMENTO PARA UNIDADE BASICA DE SAUDE"
      └─ /parceria?id_proposta=75376 ........ o instrumento celebrado
      └─ /distribuicao-recurso-proposta ..... emenda 2026.2023.0002,
                                             PAULO PAIM, Individual, GND4,
                                             R$ 299.999

⚠️ O FILTRO TERRITORIAL E DE PRIMEIRA CLASSE, ao contrario do
`/projeto-investimento` do Obras.gov: `cd_ibge_recebedor` filtra no servidor (11
de 89.400 para Nova Palma). Nao ha casamento por CNPJ nem por nome — e portanto
nao ha a classe de erro que o `obrasgov.py` descreve no cabecalho inteiro.

⚠️ QUEM RECEBE RARAMENTE E A PREFEITURA. As 11 propostas de Nova Palma sao TODAS
do FUNDO MUNICIPAL DA SAUDE, com CNPJ proprio (12240183000100, diferente do
88488358000156 da prefeitura). Um coletor que entrasse por `municipios.cnpj` —
como o da Transferencia Especial faz, e com razao la — nao acharia nenhuma.

⭐ A API INTEIRA, desde 15/09/2026. Tres fases numa rodada:

  1. LISTAGEM -> `parcerias_propostas` (proposta + parceria + emenda), como antes.
  1b. EMENDAS INDICADAS -> `parcerias_emendas_indicadas`: o que o parlamentar ja
     destinou ao municipio, exista proposta ou nao (`/beneficiario_emenda_
     parlamentar`, uma consulta por UF da carteira por rodada).
  2. ARVORE DA PROPOSTA -> `parcerias_propostas.detalhe`: metas/etapas/itens,
     cronograma, parecer, indicadores e, por parceria, a CONTA (saldo corrente e
     investimento, classificacao de ingresso), extrato, OPP (quem recebeu da
     conta), empenhos e DH -> OP/OB. Fila pelos mais velhos, com orcamento.

⚠️ A EXECUCAO FINANCEIRA FICOU DE FORA EM 07/09 POR UM CUSTO QUE NAO SE
CONFIRMOU. A conta de entao — "o `/extrato-bancario` tem 1.275.217 registros e
nunca podera ser varrido" — valia para a base NACIONAL. Por conta
(`id_parceria_conta`) o extrato de uma parceria de Nova Palma tem 2 linhas. A
arvore inteira mediu 12,8 requisicoes por proposta a 0,19 s (Nova Serrana, 37
propostas em 91 s, 14/09/2026), sem um bloqueio.

⚠️ ARMADILHAS DESTA API (medidas em 14-15/09/2026):
  - filtro de TEXTO e "contem": `nm_municipio=SANTA MARIA` traz SANTA MARIA DO
    HERVAL; `nr_cnpj_beneficiario_emenda=1` devolve a base inteira. E e sensivel
    a ACENTO ("MONTE SIAO" -> 0, "Monte Sião" -> 12). Por isso as emendas
    indicadas entram pela UF (enum validado: "ZZ" -> 422) e o municipio casa na
    memoria por nome normalizado dos dois lados.
  - valor "0" em filtro de texto e tratado como SEM filtro — prova de filtro com
    valor impossivel NAO-zero.
  - listas ANINHADAS: `meta-proposta.etapas_proposta`, `parceria-conta.
    classificacoes_ingresso`, `item-proposta.classificacao_despesa`,
    `beneficiario_emenda_parlamentar.indicacoes_beneficiario`.
  - o extrato COME o zero a esquerda do CNPJ ("530493000171" e o FNS).
  - `in_situacao_parceria` diz "Aprovada" em parceria ja PAGA (OP "Paga", com
    OB): pago se deriva da ordem bancaria, nunca da situacao.

Rodar:  python -u ingestion/parcerias.py
        python -u ingestion/parcerias.py --dry     (varre e mostra, sem gravar)
        PARCERIAS_TETO_TAREFA_S=3150 ...  (o teto da tarefa inteira)
"""
from __future__ import annotations
import json
import logging
import os
import re
import sys
import time
import unicodedata

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ingestion.transferegov_te import status_da_rodada  # noqa: E402

log = logging.getLogger("parcerias")

# ⚠️ `api-publica`, e nao `api`. Mesma pegadinha do Obras.gov.br e do modulo de
# Especiais: o host sem o prefixo e o que bloqueia.
BASE = os.getenv("PARCERIAS_BASE",
                 "https://api-publica.transferegov.gestao.gov.br/parcerias")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Transferegov)",
      "Accept": "application/json"}
TIMEOUT = 60
# Envelope de todo endpoint: {data, total_pages, total_items, page_number,
# page_size}. `pagina` e 1-based e `tamanho_da_pagina` tem teto 200 (201 -> 422).
TAMANHO_PAGINA = 200
PAUSA_S = float(os.getenv("PARCERIAS_PAUSA_S", "0.2") or "0.2")
TETO_PAGINAS = int(os.getenv("PARCERIAS_TETO_PAGINAS", "400") or "400")
# Orcamento da rodada. Medido: o nucleo custa ~420 s no freitas (547 propostas)
# e ~530 s no trust (706). O teto deixa folga para a fonte estar lenta sem que a
# rodada seja degolada no meio — ela retoma pelo que ficou.
BUDGET_S = float(os.getenv("PARCERIAS_BUDGET_S", "1200") or "1200")
MIN_INTERVAL_H = int(os.getenv("PARCERIAS_MIN_INTERVAL_H", "20") or "20")
# ⚠️ TETO DA TAREFA INTEIRA (listagem + emendas indicadas + arvore). O default
# fica casado com o `timeout -k 30 1500` que a task tinha em 15/09/2026: quem sobe
# o kill da task sobe ESTA env no MESMO comando, e o codigo nunca pede mais tempo
# do que a task concede. Mesmo contrato de `transferegov_te._TETO_TAREFA_S`.
TETO_TAREFA_S = float(os.getenv("PARCERIAS_TETO_TAREFA_S", "1400") or "1400")
# Fatia minima reservada a arvore antes da listagem comecar.
DET_MIN_S = float(os.getenv("PARCERIAS_DET_MIN_S", "300") or "300")
# Proposta cuja arvore foi colhida ha menos disto nao volta a fila.
DET_MAX_AGE_H = float(os.getenv("PARCERIAS_DET_MAX_AGE_H", "20") or "20")
# ⚠️ TETO NA CONSULTA POR ID DO PAI — ao contrario do que este modulo fazia ate
# 15/09/2026. Filtro que a fonte deixe de reconhecer devolve a base NACIONAL
# (1.301.416 lancamentos de extrato, 427.977 itens): sem teto, um renome do lado
# de la viraria milhares de paginas gravadas como a arvore de UMA proposta.
TETO_FILHOS = int(os.getenv("PARCERIAS_TETO_FILHOS", "5000") or "5000")
# Emendas indicadas por UF: a maior medida e SP, com 10.823 (15/09/2026). O teto
# barra a base nacional (78.072) caso o filtro de UF deixe de valer.
TETO_EMENDAS_UF = int(os.getenv("PARCERIAS_TETO_EMENDAS_UF", "20000") or "20000")
RETRY_S = float(os.getenv("PARCERIAS_RETRY_S", "2") or "2")


def _pagina(client: httpx.Client, caminho: str, params: dict, n: int) -> dict | None:
    """Uma pagina. `None` = a fonte nao respondeu 200 (e NAO "acabou").

    ⚠️ UMA RETENTATIVA, e so para erro de rede ou 5xx (429 nao repete). Com a
    arvore sao ~13 consultas por proposta, e sem isto um soluco da fonte jogaria
    fora a proposta inteira. Mesmo desenho de `transferegov_te._pub_pagina`."""
    p = {**params, "pagina": n, "tamanho_da_pagina": TAMANHO_PAGINA}
    r = None
    for tentativa in (1, 2):
        try:
            r = client.get(f"{BASE}/{caminho}", params=p, headers=UA, timeout=TIMEOUT)
        except Exception as e:
            log.warning("  %s %s (tentativa %d): %s", caminho, params, tentativa, str(e)[:90])
            r = None
        if r is not None and r.status_code < 500:
            break
        if tentativa == 1:
            time.sleep(RETRY_S)
    if r is None:
        return None
    if r.status_code != 200:
        # ⚠️ HTTP 500 EM FILTRO DOCUMENTADO EXISTE NESTA FAMILIA DE APIs: o
        # modulo `/fundoafundo` devolve 500 para `codigo_ibge_..._recebedor`,
        # que o proprio Swagger publica (medido 06/09/2026). Por isso o log traz
        # o caminho E os parametros — se aparecer aqui, ele diz qual filtro caiu.
        log.warning("  %s %s: HTTP %s", caminho, params, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        log.warning("  %s: resposta nao e JSON", caminho)
        return None


def buscar(client: httpx.Client, caminho: str, params: dict,
           teto_itens: int | None = None,
           exigir_completo: bool = False) -> list[dict] | None:
    """Todas as paginas de uma consulta. `None` quando a PRIMEIRA falhou.

    `exigir_completo`: `None` tambem quando uma pagina DO MEIO falhar. A listagem
    aceita o que veio; a arvore e as emendas indicadas nao — um extrato ou uma
    lista de indicacoes com pagina faltando seria gravado como se fosse inteiro.

    A distincao importa: `[]` e "a fonte respondeu e nao ha nada" (municipio sem
    proposta, proposta que nao virou parceria — estados legitimos e comuns),
    enquanto `None` e "nao consegui perguntar". Quem chama usa isso para nao
    gravar silencio como ausencia.

    ⚠️ `teto_itens` E A GUARDA CONTRA FILTRO IGNORADO. A fonte ignora EM
    SILENCIO todo parametro que nao reconhece: medido em 07/09/2026,
    `?cd_ibge_recebedorX=4313102` devolve HTTP 200 com as 89.400 propostas do
    Brasil, identico a nao filtrar. Um erro de digitacao, ou uma renomeacao do
    lado deles (o Obras.gov renomeou TODOS os campos numa troca de host), nao
    daria erro: daria a base nacional gravada como sendo do municipio da vez.
    Acima do teto devolvemos `None`, que ja e tratado como "nao consegui
    perguntar" — e nao como ausencia.
    """
    d = _pagina(client, caminho, params, 1)
    if d is None:
        return None
    if teto_itens is not None:
        total_itens = int(d.get("total_items") or 0)
        if total_itens > teto_itens:
            log.error("  %s %s: %d itens para um teto de %d — o filtro nao "
                      "foi aplicado. NAO gravando: seria carga nacional.",
                      caminho, params, total_itens, teto_itens)
            return None
    itens = list(d.get("data") or [])
    total = min(int(d.get("total_pages") or 1), TETO_PAGINAS)
    for n in range(2, total + 1):
        time.sleep(PAUSA_S)
        d = _pagina(client, caminho, params, n)
        if d is None:
            log.warning("  %s: parou na pagina %d/%d", caminho, n, total)
            if exigir_completo:
                return None
            break
        itens.extend(d.get("data") or [])
    return itens


def _num(v):
    return v if isinstance(v, (int, float)) else None


def _data(v):
    s = str(v or "").strip()
    return s[:10] if s else None


def linha(municipio_id: int, prop: dict, parceria: dict | None,
          emenda: dict | None) -> dict | None:
    """Traduz UMA proposta (mais o instrumento e a emenda) para as colunas.

    Funcao PURA e testavel: recebe os tres pedacos ja buscados e devolve
    exatamente o que o UPSERT grava.

    ⚠️ `parceria` e `emenda` sao OPCIONAIS de propósito. Proposta em elaboracao
    nao tem instrumento celebrado, e proposta de programa voluntario nao tem
    emenda — os dois sao estado legitimo, e gravar a linha sem eles e melhor do
    que descarta-la: o objeto e o valor ja valem a tela.
    """
    pid = prop.get("id_proposta")
    if pid is None:
        return None
    parceria = parceria or {}
    emenda = emenda or {}
    return {
        "mid": municipio_id,
        "id_proposta": int(pid),
        "id_programa": prop.get("id_programa"),
        "cnpj": (prop.get("cnpj_ente_recebedor") or "")[:14] or None,
        "ente": prop.get("nm_ente_recebedor"),
        "natureza": prop.get("nm_natureza_juridica"),
        "objeto": prop.get("ds_objeto"),
        "problema": prop.get("ds_problema_proposta"),
        "resultado": prop.get("ds_resultado_esperado_proposta"),
        "publico": prop.get("ds_publico_alvo_proposta"),
        "situacao": prop.get("situacao_proposta"),
        # A fonte tem DOIS campos de valor e o preenchido varia: `nr_vlr_total`
        # vem nulo nas propostas que medimos e `vl_total_planejamento_gastos`
        # traz o numero. Tenta os dois, nessa ordem de confianca.
        "valor": _num(prop.get("vl_total_planejamento_gastos")
                      if prop.get("vl_total_planejamento_gastos") is not None
                      else prop.get("nr_vlr_total")),
        "ano": prop.get("ano_proposta"),
        "dt_proposta": _data(prop.get("dt_proposta")),
        "id_parceria": parceria.get("id_parceria"),
        "cd_parceria": (str(parceria["cd_parceria"])
                        if parceria.get("cd_parceria") is not None else None),
        "sit_parceria": parceria.get("in_situacao_parceria"),
        "dt_assinatura": _data(parceria.get("dh_assinatura")),
        "nr_emenda": emenda.get("nr_emenda_proposta"),
        "parlamentar": emenda.get("nm_parlamentar_proposta"),
        "tipo_emenda": emenda.get("in_tipo_emenda_parlamentar_proposta"),
        "vl_emenda": _num(emenda.get("valor_emenda")),
        # O numero da proposta no sistema de ORIGEM — para a saude, o
        # `nuProposta` do FNS. E a chave do cruzamento com as propostas FNS.
        "nu_externo": (str(parceria["nu_externo"]).strip() or None
                       if parceria.get("nu_externo") is not None else None),
        "raw": json.dumps({**prop, "_parceria": parceria, "_emenda": emenda},
                          ensure_ascii=False),
    }


_SQL = """
INSERT INTO parcerias_propostas (
    municipio_id, id_proposta, id_programa, cnpj_ente_recebedor,
    nome_ente_recebedor, natureza_juridica, objeto, problema,
    resultado_esperado, publico_alvo, situacao, valor_total, ano_proposta,
    data_proposta, id_parceria, codigo_parceria, situacao_parceria,
    data_assinatura, numero_emenda, parlamentar, tipo_emenda, valor_emenda,
    nu_externo, raw_data, atualizado_em)
VALUES (%(mid)s, %(id_proposta)s, %(id_programa)s, %(cnpj)s, %(ente)s,
        %(natureza)s, %(objeto)s, %(problema)s, %(resultado)s, %(publico)s,
        %(situacao)s, %(valor)s, %(ano)s, %(dt_proposta)s, %(id_parceria)s,
        %(cd_parceria)s, %(sit_parceria)s, %(dt_assinatura)s, %(nr_emenda)s,
        %(parlamentar)s, %(tipo_emenda)s, %(vl_emenda)s, %(nu_externo)s,
        %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, id_proposta) DO UPDATE SET
    id_programa = EXCLUDED.id_programa,
    cnpj_ente_recebedor = EXCLUDED.cnpj_ente_recebedor,
    nome_ente_recebedor = EXCLUDED.nome_ente_recebedor,
    natureza_juridica = EXCLUDED.natureza_juridica,
    objeto = EXCLUDED.objeto, problema = EXCLUDED.problema,
    resultado_esperado = EXCLUDED.resultado_esperado,
    publico_alvo = EXCLUDED.publico_alvo, situacao = EXCLUDED.situacao,
    valor_total = EXCLUDED.valor_total, ano_proposta = EXCLUDED.ano_proposta,
    data_proposta = EXCLUDED.data_proposta,
    -- ⚠️ COALESCE no instrumento e na emenda (15/09/2026). Em 14/09/2026, as
    -- 06:00 UTC, a fonte respondeu HTTP 200 com a lista de emendas VAZIA para
    -- todas as propostas (recarga do dia), e este upsert apagou parlamentar e
    -- emenda de 547 propostas no freitas e 326 no bgk — a tela ficou um dia
    -- sem ranking por parlamentar, sem erro nenhum em log. Emenda retirada de
    -- uma proposta ja celebrada nao e caso real; vazio da fonte e.
    id_parceria = COALESCE(EXCLUDED.id_parceria, parcerias_propostas.id_parceria),
    codigo_parceria = COALESCE(EXCLUDED.codigo_parceria, parcerias_propostas.codigo_parceria),
    situacao_parceria = COALESCE(EXCLUDED.situacao_parceria, parcerias_propostas.situacao_parceria),
    data_assinatura = COALESCE(EXCLUDED.data_assinatura, parcerias_propostas.data_assinatura),
    numero_emenda = COALESCE(EXCLUDED.numero_emenda, parcerias_propostas.numero_emenda),
    parlamentar = COALESCE(EXCLUDED.parlamentar, parcerias_propostas.parlamentar),
    tipo_emenda = COALESCE(EXCLUDED.tipo_emenda, parcerias_propostas.tipo_emenda),
    valor_emenda = COALESCE(EXCLUDED.valor_emenda, parcerias_propostas.valor_emenda),
    nu_externo = COALESCE(EXCLUDED.nu_externo, parcerias_propostas.nu_externo),
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _municipios(cur) -> list[dict]:
    """Municipios ATIVOS com IBGE — a chave desta fonte.

    ⚠️ `WHERE active`, pelo mesmo motivo que a Transferencia Especial teve de
    aprender em producao (07/09/2026): sem ele, o coletor gasta requisicao com
    municipio que o cliente nao acompanha mais. No freitas sao 18 dos 60.
    """
    cur.execute("""
        SELECT id, nome, coalesce(ibge_code, ''), upper(coalesce(uf, ''))
          FROM municipios
         WHERE active AND length(coalesce(ibge_code, '')) = 7
         ORDER BY nome
    """)
    return [{"id": r[0], "nome": r[1], "ibge": r[2], "uf": r[3]} for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# FASE 1b — EMENDAS INDICADAS AO MUNICIPIO (15/09/2026)
# ---------------------------------------------------------------------------
def _chave_nome(nome) -> str:
    """Nome de municipio comparavel: sem acento, maiusculo, so letras e digitos.

    ⚠️ E O QUE PERMITE ENTRAR POR NOME SEM REPETIR O ERRO DO OBRAS.GOV. O filtro
    da fonte e "contem" (SANTA MARIA traz SANTA MARIA DO HERVAL) e sensivel a
    acento (MONTE SIAO -> 0). Aqui a comparacao e de IGUALDADE, entre os dois
    lados normalizados, dentro da mesma UF — e nome de municipio e unico dentro
    da UF, entao igualdade exata identifica o municipio como o IBGE."""
    s = unicodedata.normalize("NFKD", str(nome or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", s).split())


def emendas_da_uf(client: httpx.Client, uf: str) -> dict[str, list[dict]] | None:
    """`/beneficiario_emenda_parlamentar` da UF INTEIRA, indexado por municipio.

    Uma consulta por UF por rodada (MG: 9.737 registros, 49 paginas, ~40 s) em vez
    de uma por municipio pelo nome — que so acharia o municipio com a grafia exata
    da fonte, acento incluido. `None` = nao consegui perguntar (nada e apagado)."""
    itens = buscar(client, "beneficiario_emenda_parlamentar",
                   {"sg_uf_beneficiario_emenda": uf},
                   teto_itens=TETO_EMENDAS_UF, exigir_completo=True)
    if itens is None:
        return None
    por_mun: dict[str, list[dict]] = {}
    for it in itens:
        if str(it.get("sg_uf_beneficiario_emenda") or "").upper() != uf:
            continue   # a fonte filtrou errado: nao entra
        por_mun.setdefault(_chave_nome(it.get("nm_municipio_beneficiario_emenda")), []).append(it)
    return por_mun


def linha_emenda_indicada(municipio_id: int, reg: dict) -> dict | None:
    """UM registro de `/beneficiario_emenda_parlamentar` -> colunas. Funcao PURA."""
    rid = reg.get("id_beneficiario_emenda_parlamentar_programa")
    if rid is None:
        return None
    ano = reg.get("aa_emenda")
    return {
        "mid": municipio_id,
        "rid": int(rid),
        "id_programa": reg.get("id_programa"),
        "cnpj": (str(reg.get("nr_cnpj_beneficiario_emenda") or "")[:14] or None),
        "nome": reg.get("nm_beneficiario_emenda"),
        "natureza": reg.get("nm_natureza_juridica_beneficiario_emenda"),
        "ano": int(ano) if isinstance(ano, (int, float)) else None,
        "nr_emenda": reg.get("nr_emenda"),
        "parlamentar": reg.get("nm_parlamentar"),
        "tipo": reg.get("in_tipo_emenda_parlamentar"),
        "gnd3": _num(reg.get("vl_gnd3")),
        "gnd4": _num(reg.get("vl_gnd4")),
        "total": _num(reg.get("vl_total_emenda")),
        "indicacoes": json.dumps(reg.get("indicacoes_beneficiario") or [], ensure_ascii=False),
        "raw": json.dumps(reg, ensure_ascii=False),
    }


_SQL_EMENDA = """
INSERT INTO parcerias_emendas_indicadas (
    municipio_id, id_beneficiario_emenda, id_programa, cnpj_beneficiario,
    nome_beneficiario, natureza_juridica, ano_emenda, numero_emenda, parlamentar,
    tipo_emenda, valor_gnd3, valor_gnd4, valor_total, indicacoes, raw_data,
    atualizado_em)
VALUES (%(mid)s, %(rid)s, %(id_programa)s, %(cnpj)s, %(nome)s, %(natureza)s,
        %(ano)s, %(nr_emenda)s, %(parlamentar)s, %(tipo)s, %(gnd3)s, %(gnd4)s,
        %(total)s, %(indicacoes)s::jsonb, %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, id_beneficiario_emenda) DO UPDATE SET
    id_programa = EXCLUDED.id_programa, cnpj_beneficiario = EXCLUDED.cnpj_beneficiario,
    nome_beneficiario = EXCLUDED.nome_beneficiario,
    natureza_juridica = EXCLUDED.natureza_juridica, ano_emenda = EXCLUDED.ano_emenda,
    numero_emenda = EXCLUDED.numero_emenda, parlamentar = EXCLUDED.parlamentar,
    tipo_emenda = EXCLUDED.tipo_emenda, valor_gnd3 = EXCLUDED.valor_gnd3,
    valor_gnd4 = EXCLUDED.valor_gnd4, valor_total = EXCLUDED.valor_total,
    indicacoes = EXCLUDED.indicacoes, raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def grava_emendas_do_municipio(cur, municipio_id: int, registros: list[dict]) -> int:
    """TROCA o conjunto do municipio: o que a fonte deixou de listar sai daqui.

    So e chamada com a consulta da UF COMPLETA — consulta falhada nunca apaga.
    Quem chama commita (a troca e atomica com o resto do municipio)."""
    linhas = [l for l in (linha_emenda_indicada(municipio_id, r) for r in registros) if l]
    ids = [l["rid"] for l in linhas]
    if ids:
        cur.execute("DELETE FROM parcerias_emendas_indicadas "
                    "WHERE municipio_id = %s AND NOT (id_beneficiario_emenda = ANY(%s))",
                    (municipio_id, ids))
    else:
        cur.execute("DELETE FROM parcerias_emendas_indicadas WHERE municipio_id = %s",
                    (municipio_id,))
    for l in linhas:
        cur.execute(_SQL_EMENDA, l)
    return len(linhas)


# ---------------------------------------------------------------------------
# FASE 2 — A ARVORE DA PROPOSTA (15/09/2026)
# ---------------------------------------------------------------------------
# Tudo pendurado na proposta e na parceria por ID DO PAI. Cada filtro abaixo foi
# PROVADO com valor impossivel (id 0 -> 0 itens) contra a base nacional:
#
#   proposta ─┬─ meta-proposta (etapas ANINHADAS) ── item-proposta (por etapa)
#             ├─ cronograma-desembolso
#             ├─ analise-proposta (texto do parecer)
#             ├─ proposta-resultado-indicador
#             └─ parceria ─┬─ parceria-conta (classificacao de ingresso ANINHADA)
#                          │     ├─ extrato-bancario (por id_parceria_conta)
#                          │     └─ opp (por id_conta_gf: pagamentos a terceiros)
#                          ├─ empenho-parceria
#                          └─ documento-habil ── ordem-pagamento (a OB)
#
# `/programa` (176 no Brasil) vem inteiro, uma vez por rodada.
class _FonteMuda(Exception):
    """Uma consulta da arvore ficou sem resposta — a arvore inteira nao vale."""


def _filhos(client: httpx.Client, caminho: str, params: dict) -> list[dict] | None:
    """Consulta por ID DO PAI: com teto e sem aceitar pagina faltando.

    ⚠️ PARAMETRO NULO = NAO HA O QUE PERGUNTAR: devolve [] SEM tocar a rede —
    filtro vazio e filtro que a fonte ignora, ou seja, o Brasil."""
    if any(v is None or v == "" for v in params.values()):
        return []
    return buscar(client, caminho, params, teto_itens=TETO_FILHOS, exigir_completo=True)


def _doc_cnpj(valor) -> str | None:
    """CNPJ do extrato com os zeros que a fonte come ('530493000171' e o FNS,
    00.530.493/0001-71). So completa 12 ou 13 digitos — ai nao ha duvida de que e
    CNPJ. Com 11 ou menos fica cru (CPF e CNPJ curto se confundem); o documento
    completo do depositante esta na classificacao de ingresso da conta."""
    if valor is None:
        return None
    s = str(valor).strip()
    m = re.fullmatch(r"(\d+)(?:\.0+)?", s)
    if not m:
        return s or None
    d = m.group(1)
    return d.zfill(14) if len(d) in (12, 13) else d


def programas(client: httpx.Client) -> dict[int, dict]:
    """`/programa` inteiro (176 no Brasil). {} se a fonte nao respondeu: o
    programa e acessorio e nao derruba a arvore de ninguem."""
    itens = buscar(client, "programa", {}, teto_itens=2000, exigir_completo=True)
    return {int(p["id_programa"]): p for p in (itens or []) if p.get("id_programa") is not None}


def arvore_da_proposta(client: httpx.Client, prop: dict, parceria: dict | None,
                       progs: dict[int, dict] | None = None) -> dict | None:
    """As rotas da API penduradas em UMA proposta (e na parceria dela).

    ⚠️ TUDO OU NADA: qualquer consulta sem resposta devolve None, e quem chama
    NAO GRAVA — o detalhe anterior fica e o carimbo nao anda. Uma arvore com o
    extrato faltando seria lida como "a conta nao teve movimento".

    `parceria` vem do `raw_data` da listagem (a mesma rodada ja a buscou): nao
    ha requisicao repetida. Proposta sem parceria celebrada tem arvore so do
    plano (metas, cronograma, parecer), e `execucao` nula — estado legitimo.
    """
    pid = prop.get("id_proposta")
    if pid is None:
        return None

    def lista(caminho: str, **params) -> list[dict]:
        itens = _filhos(client, caminho, params)
        if itens is None:
            raise _FonteMuda(f"{caminho} {params}")
        return itens

    try:
        metas = lista("meta-proposta", id_proposta=pid)
        for meta in metas:
            for etapa in meta.get("etapas_proposta") or []:
                etapa["itens"] = lista("item-proposta",
                                       id_etapa_proposta=etapa.get("id_etapa_proposta"))
        cronograma = lista("cronograma-desembolso", id_proposta=pid)
        analises = lista("analise-proposta", id_proposta=pid)
        indicadores = lista("proposta-resultado-indicador", id_proposta=pid)
        execucao = None
        id_par = (parceria or {}).get("id_parceria")
        if id_par is not None:
            contas = lista("parceria-conta", id_parceria=id_par)
            for conta in contas:
                extrato = lista("extrato-bancario",
                                id_parceria_conta=conta.get("id_parceria_conta"))
                for lanc in extrato:
                    for campo in ("nu_identificacao_depositante_extrato_bancario",
                                  "nu_identificacao_beneficiario"):
                        lanc[campo] = _doc_cnpj(lanc.get(campo))
                conta["extrato"] = extrato
                conta["opp"] = lista("opp", id_conta_gf=conta.get("id_conta_gf"))
            empenhos = lista("empenho-parceria", id_parceria=id_par)
            dhs = lista("documento-habil", id_parceria=id_par)
            for dh in dhs:
                dh["ordens"] = lista("ordem-pagamento",
                                     id_documento_habil=dh.get("id_documento_habil"))
            execucao = {"contas": contas, "empenhos": empenhos, "documentos_habeis": dhs}
    except _FonteMuda as e:
        log.warning("  arvore %s: sem resposta em %s — nada gravado", pid, str(e)[:160])
        return None

    id_prog = prop.get("id_programa")
    arv = {
        "programa": (progs or {}).get(int(id_prog)) if id_prog is not None else None,
        "metas": metas,
        "cronograma": cronograma,
        "analises": analises,
        "indicadores": indicadores,
        "execucao": execucao,
    }
    arv["_resumo"] = execucao_da_arvore(arv)
    return arv


def _d10(v) -> str | None:
    s = str(v or "").strip()
    return s[:10] if len(s) >= 10 else None


def _cancelada(situacao) -> bool:
    return "cancel" in str(situacao or "").lower()


def execucao_da_arvore(arv: dict) -> dict | None:
    """O que aconteceu com o dinheiro, em numeros — o que a listagem mostra.

    `None` quando nao ha parceria celebrada (nao ha execucao a resumir).

    REGRA DO PAGO (a mesma de Especiais): ordem de pagamento com ORDEM BANCARIA
    emitida (`nr_ordem_bancaria`) e nao cancelada. ⚠️ NUNCA pela situacao da
    parceria: medido na 75161 de Nova Palma, `in_situacao_parceria` "Aprovada"
    com a OP "Paga" e OB 2026OB038114 emitida em 26/05/2026.

    SALDO = conta corrente + conta de INVESTIMENTO. O dinheiro parado costuma
    estar na aplicacao: na 75161, R$ 0,00 em corrente e R$ 301.614,37 aplicados.
    """
    ex = arv.get("execucao")
    if not ex:
        return None
    empenhado = 0.0
    for e in ex.get("empenhos") or []:
        if not _cancelada(e.get("in_situacao_siafi")):
            empenhado += _num(e.get("valor_empenho")) or 0.0
    pago = 0.0
    datas_ob: list[str] = []
    n_ob = 0
    for dh in ex.get("documentos_habeis") or []:
        for op in dh.get("ordens") or []:
            if (op.get("nr_ordem_bancaria") or "").strip() and not _cancelada(op.get("in_situacao_op")):
                pago += _num(op.get("vl_ordem_pagamento")) or 0.0
                n_ob += 1
                d = _d10(op.get("dt_emissao_ordem_bancaria"))
                if d:
                    datas_ob.append(d)
    corrente = investimento = nao_classificado = terceiros = 0.0
    datas_saldo: list[str] = []
    tem_saldo = False
    for c in ex.get("contas") or []:
        for campo_v, campo_d in (("vl_saldo_conta_corrente", "dt_referencia_saldo_conta_corrente"),
                                 ("vl_saldo_conta_investimento", "dt_referencia_saldo_conta_investimento")):
            v = _num(c.get(campo_v))
            if v is not None:
                tem_saldo = True
                if campo_v.endswith("corrente"):
                    corrente += v
                else:
                    investimento += v
                d = _d10(c.get(campo_d))
                if d:
                    datas_saldo.append(d)
        for ci in c.get("classificacoes_ingresso") or []:
            nao_classificado += _num(ci.get("vl_nao_classificado")) or 0.0
        for o in c.get("opp") or []:
            terceiros += _num(o.get("vl_efetivado")) or 0.0
    return {
        "empenhado": round(empenhado, 2),
        "pago": round(pago, 2),
        "n_ordens_bancarias": n_ob,
        "data_ultima_ob": max(datas_ob) if datas_ob else None,
        "saldo_corrente": round(corrente, 2) if tem_saldo else None,
        "saldo_investimento": round(investimento, 2) if tem_saldo else None,
        "saldo_total": round(corrente + investimento, 2) if tem_saldo else None,
        "data_saldo": max(datas_saldo) if datas_saldo else None,
        "nao_classificado": round(nao_classificado, 2),
        "pago_a_terceiros": round(terceiros, 2),
        "n_contas": len(ex.get("contas") or []),
    }


def _data_da_fonte(client: httpx.Client) -> str | None:
    """`/data-atualizacao`: quando a PROPRIA fonte se atualizou (outra coisa que a
    hora da nossa coleta). Medido: carga diaria, `2026-09-14T00:00:00`."""
    try:
        r = client.get(f"{BASE}/data-atualizacao", headers=UA, timeout=30)
        if r.status_code == 200:
            return (r.json() or {}).get("data_ultima_atualizacao")
    except Exception as e:
        log.warning("  /data-atualizacao: %s", str(e)[:100])
    return None


def _grava_data_da_fonte(cur, conn, data: str | None) -> None:
    """Grava em `fonte_atualizacao` (chave `transferegov_parcerias`). Excecao
    engolida: a tabela nasce numa migration, e isso nao pode custar a coleta."""
    if not data:
        return
    try:
        cur.execute(
            "INSERT INTO fonte_atualizacao (fonte, data_fonte, consultado_em) "
            "VALUES ('transferegov_parcerias', %s, NOW()) "
            "ON CONFLICT (fonte) DO UPDATE SET data_fonte = EXCLUDED.data_fonte, "
            "consultado_em = NOW()", (data,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("fonte_atualizacao falhou: %s", str(e)[:120])


def run_detalhe(client: httpx.Client, conn, cur, budget_s: float) -> dict:
    """FASE 2: a arvore de cada proposta da carteira, as mais velhas primeiro.

    Fila `ORDER BY detalhe_atualizado_em NULLS FIRST`: o que nao coube hoje e o
    primeiro de amanha — nenhuma proposta fica esquecida no fim de uma lista
    ordenada por nome. So municipios ATIVOS."""
    cur.execute(
        "SELECT p.id, p.id_proposta, p.raw_data FROM parcerias_propostas p "
        "  JOIN municipios m ON m.id = p.municipio_id AND m.active "
        " WHERE p.detalhe_atualizado_em IS NULL "
        "    OR p.detalhe_atualizado_em < NOW() - make_interval(secs => %s) "
        " ORDER BY p.detalhe_atualizado_em NULLS FIRST, p.id",
        (DET_MAX_AGE_H * 3600,))
    fila = cur.fetchall()
    if not fila:
        log.info("Parcerias arvore: nada vencido nesta rodada")
        return {"fila": 0, "atualizados": 0, "falhas": 0, "restantes": 0}
    log.info("Parcerias arvore: %d proposta(s) na fila (orcamento %.0fs)", len(fila), budget_s)
    t0 = time.time()
    progs = programas(client)
    feitos = falhas = processados = com_execucao = 0
    for pk, _pid, raw in fila:
        if (time.time() - t0) >= budget_s:
            log.warning("Parcerias arvore: orcamento estourado apos %d proposta(s); "
                        "%d entram primeiro na proxima rodada", processados,
                        len(fila) - processados)
            break
        processados += 1
        raw = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        arv = arvore_da_proposta(client, raw, raw.get("_parceria") or None, progs)
        if arv is None:
            falhas += 1
            continue
        if arv.get("execucao"):
            com_execucao += 1
        cur.execute("UPDATE parcerias_propostas SET detalhe = %s::jsonb, "
                    "detalhe_atualizado_em = NOW() WHERE id = %s",
                    (json.dumps(arv, ensure_ascii=False), pk))
        conn.commit()   # proposta a proposta: progresso persiste se a tarefa cair
        feitos += 1
    restantes = len(fila) - processados
    log.info("Parcerias arvore: FIM — %d de %d proposta(s) atualizada(s), %d sem "
             "resposta, %d para a proxima rodada, %d com execucao financeira em %.0fs",
             feitos, len(fila), falhas, restantes, com_execucao, time.time() - t0)
    return {"fila": len(fila), "atualizados": feitos, "falhas": falhas,
            "restantes": restantes, "com_execucao": com_execucao}


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('parcerias', %s, %s, %s, NOW())",
            (status, n, (erro[:500] if erro else None)))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest(dry: bool = False) -> int:
    from datetime import datetime

    from ingestion._resilience import get_sync_db_url, neon_connect

    t0 = time.time()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            if not dry and os.getenv("PARCERIAS_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'parcerias' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "PARCERIAS_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            municipios = _municipios(cur)
            if not municipios:
                msg = "nenhum municipio ativo com IBGE na carteira"
                log.warning(msg)
                if not dry:
                    _log_ingest(cur, conn, "success", 0, msg)
                return 0

            gravados = com_proposta = com_emenda = falhas = 0
            atendidos = 0
            emendas_gravadas = emendas_falhas = 0
            completo = True
            det = None
            # A fatia da arvore e RESERVADA antes, e nao o que sobrar — mesma
            # licao de `transferegov_te.run` (sem reserva, a fase seguinte nunca
            # roda numa rodada lenta).
            teto_listagem = max(60.0, min(BUDGET_S, TETO_TAREFA_S - DET_MIN_S))
            log.info("Parcerias: %d municipio(s) na carteira — teto da tarefa %.0fs, "
                     "listagem ate %.0fs", len(municipios), TETO_TAREFA_S, teto_listagem)
            with httpx.Client(follow_redirects=True) as client:
                fonte_data = _data_da_fonte(client)
                log.info("Parcerias: fonte atualizada em %s", fonte_data or "(nao informado)")
                if not dry:
                    _grava_data_da_fonte(cur, conn, fonte_data)
                # Emendas indicadas por UF: baixadas no maximo UMA vez por rodada,
                # na primeira vez que um municipio daquela UF aparece.
                emendas_uf: dict[str, dict | None] = {}
                for m in municipios:
                    if (time.time() - t0) >= teto_listagem:
                        completo = False
                        log.warning("orcamento estourado apos %d municipio(s); "
                                    "o resto entra na proxima rodada", atendidos)
                        break
                    # FASE 1b — as emendas indicadas ao municipio. Independe da
                    # listagem: municipio sem proposta pode ter emenda indicada,
                    # e e justamente esse o caso que a tela precisa mostrar.
                    if m["uf"]:
                        if m["uf"] not in emendas_uf:
                            emendas_uf[m["uf"]] = emendas_da_uf(client, m["uf"])
                        idx = emendas_uf[m["uf"]]
                        if idx is None:
                            emendas_falhas += 1
                        elif not dry:
                            emendas_gravadas += grava_emendas_do_municipio(
                                cur, m["id"], idx.get(_chave_nome(m["nome"]), []))
                            conn.commit()
                    # Teto de 5.000 contra a base nacional de 89.400: o
                    # maior municipio medido tem 84 propostas, e nem uma
                    # capital chegaria a milhares. Ver `buscar`.
                    propostas = buscar(client, "proposta",
                                       {"cd_ibge_recebedor": m["ibge"]},
                                       teto_itens=5000)
                    atendidos += 1
                    if propostas is None:
                        falhas += 1
                        continue
                    if not propostas:
                        continue
                    com_proposta += 1
                    for prop in propostas:
                        pid = prop.get("id_proposta")
                        # Instrumento e emenda: o que as COLUNAS precisam. O
                        # resto da proposta (plano, conta, extrato, pagamentos)
                        # vem na fase 2, que reusa esta `parceria` do raw_data.
                        time.sleep(PAUSA_S)
                        parcerias = buscar(client, "parceria", {"id_proposta": pid})
                        time.sleep(PAUSA_S)
                        emendas = buscar(client, "distribuicao-recurso-proposta",
                                         {"id_proposta": pid})
                        l = linha(m["id"], prop,
                                  (parcerias or [None])[0] if parcerias else None,
                                  (emendas or [None])[0] if emendas else None)
                        if l is None:
                            continue
                        if l["nr_emenda"]:
                            com_emenda += 1
                        if dry:
                            continue
                        cur.execute(_SQL, l)
                        gravados += 1
                    conn.commit()   # municipio a municipio: progresso persiste
                    log.info("  %s: %d proposta(s)", m["nome"], len(propostas))

                if dry:
                    log.info("DRY: %d municipio(s), %d com proposta", atendidos, com_proposta)
                    return 0
                log.info("=== Parcerias: %d proposta(s) gravada(s), %d com emenda, "
                         "%d municipio(s) com proposta, %d falha(s); %d emenda(s) "
                         "indicada(s), %d municipio(s) sem emendas por UF sem "
                         "resposta em %.0fs ===",
                         gravados, com_emenda, com_proposta, falhas, emendas_gravadas,
                         emendas_falhas, time.time() - t0)

                # FASE 2 — a arvore, com o que sobrou do teto da tarefa.
                resto = TETO_TAREFA_S - (time.time() - t0)
                if resto < 30:
                    log.warning("Parcerias arvore: sem tempo nesta rodada (sobraram %.0fs)", resto)
                    det = {"erro": "sem tempo nesta rodada; a fila inteira fica para a proxima"}
                else:
                    try:
                        det = run_detalhe(client, conn, cur, budget_s=resto)
                    except Exception as e:
                        conn.rollback()
                        log.warning("Parcerias arvore falhou: %s", str(e)[:150])
                        det = {"erro": str(e)[:150]}

            # ⚠️ O ALARME CERTO NAO E "zero gravados". Municipio sem parceria e
            # estado legitimo e comum — a fonte so tem instrumento de 2024 em
            # diante. O que denuncia defeito e a fonte nao responder a ninguem.
            if falhas and not gravados:
                lst = {"status": "error", "gravados": 0,
                       "erro": "a fonte nao respondeu a nenhum municipio"}
            elif falhas or not completo:
                lst = {"status": "partial", "gravados": gravados,
                       "erro": (f"{falhas} municipio(s) sem resposta" if falhas
                                else "orcamento estourado; retoma na proxima rodada")}
            elif emendas_falhas:
                lst = {"status": "partial", "gravados": gravados,
                       "erro": f"emendas indicadas: {emendas_falhas} municipio(s) sem "
                               f"resposta da fonte; retomam na proxima rodada"}
            elif gravados >= 20 and not com_emenda:
                # ⚠️ A ASSINATURA DE 14/09/2026: HTTP 200, zero erro, e NENHUMA
                # das propostas com emenda — em carteira onde 94% tem. Nao e
                # estado plausivel; e a fonte no meio da recarga. O COALESCE do
                # upsert preserva o que ja estava gravado; isto faz a rodada
                # aparecer amarela no Frescor em vez de verde.
                lst = {"status": "partial", "gravados": gravados,
                       "erro": f"a fonte devolveu {gravados} proposta(s) e nenhuma "
                               f"emenda — provavel recarga da fonte; emendas ja "
                               f"gravadas foram preservadas"}
            else:
                lst = {"status": "success", "gravados": gravados, "erro": None}
            # UMA linha no ingestion_log, somando listagem e arvore — a mesma regra
            # de `transferegov_te` (uma segunda linha mudaria a "ultima coleta").
            status, n, erro = status_da_rodada(lst, det)
            _log_ingest(cur, conn, status, n, erro)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("Parcerias falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    # Sem isto o log da rodada vira lixo: sao ~1.100 requisicoes no maior tenant
    # e o httpx loga cada uma em INFO. Mesmo tratamento de `obrasgov` e `sismob`.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
