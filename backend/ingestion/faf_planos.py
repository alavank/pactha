"""FUNDO A FUNDO do Transferegov.br -> `faf_planos_acao`, `faf_contas`,
`faf_programas_beneficiarios` e `faf_programas`.

⭐ O OUTRO LADO DO ConsultaFNS. O `fns_faf.py` coleta o repasse consolidado por
bloco: **o dinheiro que entra**. Esta fonte traz o que o FNS nao publica — o
PLANO DE ACAO que justifica o repasse: diagnostico, objetivos, vigencia, e a
decomposicao do valor entre emenda, repasse especifico, voluntario, recursos
proprios e rendimentos. Uma nao substitui a outra.

E nao e so saude — e, na verdade, NAO E SAUDE: os 125 programas publicados
(15/09/2026) sao de SPPE, DIRPP, SENASP, MinC, FNDE e MCID. Em Nova Palma os
quatro planos sao do **Ministerio da Cultura** (Lei Aldir Blanc). O SUS continua
so no `fns_faf`.

⭐ A API INTEIRA, desde 15/09/2026. Duas fases numa rodada:

  1. LISTAGEM (por municipio): os BENEFICIARIOS de programa -> tabela propria
     (quanto cada programa destina ao municipio, com plano enviado ou nao), e os
     PLANOS -> `faf_planos_acao`, como antes. O catalogo de programas vem uma vez
     por rodada -> `faf_programas`.
  2. ARVORE DO PLANO -> `faf_planos_acao.detalhe`: metas -> acoes, destinacao,
     historico, parecer (-> analista), termo de adesao (-> historico), empenhos,
     relatorio de gestao (-> % fisico por acao, -> parecer -> analista), e as
     CONTAS -> `faf_contas`, com o extrato e, por lancamento, as subtransacoes
     (QUEM RECEBEU). Fila pelos mais velhos, com orcamento.

Tudo o que a fase 2 traz so aparecia no modulo Fundo a Fundo do Transferegov
para quem entrasse LOGADO como o ente.

⚠️ O FILTRO OBVIO ESTA QUEBRADO NA FONTE.
`/planos-acao?codigo_ibge_municipio_ente_recebedor_plano_acao=4313102` devolve
**HTTP 500** — o parametro esta no Swagger e nao funciona (medido em 06, 07 e
15/09/2026). O caminho que funciona tem dois passos:

    1. /programas-beneficiarios?codigo_ibge_..._beneficiario_programa=4313102
         -> 5 beneficiarios, cada um com `cnpj_beneficiario_programa`
    2. /planos-acao?cnpj_ente_recebedor_plano_acao=<cnpj>
         -> 4 planos, com os valores batendo com os beneficiarios

⚠️ E O CNPJ NAO PODE SER ADIVINHADO. Aqui o ente recebedor e a PREFEITURA
(88488358000156 em Nova Palma); no modulo de Parcerias as propostas do mesmo
municipio sao todas do FUNDO MUNICIPAL DA SAUDE (12240183000100). Assumir
qualquer um dos dois erraria em um dos modulos — e erraria calado, devolvendo
lista vazia como se o municipio nao tivesse nada. Por isso o passo 1 existe: a
fonte diz quem recebe.

⚠️ ARMADILHAS DESTA API (medidas em 15/09/2026):
  - filtro de CNPJ e "contem" (13 digitos trazem os 94 lancamentos de Nova
    Palma); `id_agencia_conta` e EXATO ("2352-1165" -> 0) e da 400 em formato
    invalido.
  - o saldo vem em `saldo_final_dado_bancario.saldo_final_gestao_financeira`,
    ANINHADO — nao no `saldo_final_conta_plano_acao_dado_bancario` do openapi.
  - A MESMA CONTA SERVE A VARIOS PLANOS (Goiania: 5 planos em 1126-8216). Por
    isso a conta tem tabela propria e e buscada uma vez por rodada.
  - o extrato vem com o ACENTO COMIDO em parte das linhas ("Emisso de Ordem
    Bancria"): a classificacao compara por prefixo sem acento.
  - conta "NNNN-0" e plano SEM conta aberta: nao ha extrato a pedir.

Custo medido: ~0,18 s por consulta. Os 15 planos de Goiania: 326 consultas em
57 s, mais 209 de subtransacoes. Nova Palma: ~15 por plano.

Rodar:  python -u ingestion/faf_planos.py
        python -u ingestion/faf_planos.py --dry
        FAF_TETO_TAREFA_S=3150 ...  (o teto da tarefa inteira)
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

log = logging.getLogger("faf_planos")

# ⚠️ `api-publica`, e nao `api` — a mesma pegadinha dos outros modulos.
BASE = os.getenv("FAF_BASE",
                 "https://api-publica.transferegov.gestao.gov.br/fundoafundo")
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 dados abertos Transferegov)",
      "Accept": "application/json"}
TIMEOUT = 60
TAMANHO_PAGINA = 200
PAUSA_S = float(os.getenv("FAF_PAUSA_S", "0.2") or "0.2")
TETO_PAGINAS = int(os.getenv("FAF_TETO_PAGINAS", "200") or "200")
BUDGET_S = float(os.getenv("FAF_BUDGET_S", "900") or "900")
MIN_INTERVAL_H = int(os.getenv("FAF_MIN_INTERVAL_H", "20") or "20")
# ⚠️ TETO DA TAREFA INTEIRA (listagem + arvore). O default fica casado com o
# `timeout -k 30 1200` que a task tinha em 15/09/2026: quem sobe o kill da task
# sobe ESTA env no MESMO comando, e o codigo nunca pede mais tempo do que a task
# concede. Mesmo contrato de `parcerias.TETO_TAREFA_S`.
TETO_TAREFA_S = float(os.getenv("FAF_TETO_TAREFA_S", "1140") or "1140")
# Fatia minima reservada a arvore antes da listagem comecar.
DET_MIN_S = float(os.getenv("FAF_DET_MIN_S", "300") or "300")
# Plano cuja arvore foi colhida ha menos disto nao volta a fila.
DET_MAX_AGE_H = float(os.getenv("FAF_DET_MAX_AGE_H", "20") or "20")
# ⚠️ TETO NA CONSULTA POR ID DO PAI. Filtro que a fonte deixe de reconhecer
# devolve a base NACIONAL (183.910 registros de historico, 79.434 acoes): sem
# teto, um renome do lado de la viraria a base inteira gravada num plano.
TETO_FILHOS = int(os.getenv("FAF_TETO_FILHOS", "5000") or "5000")
# Extrato por conta: a maior medida tem 811 lancamentos (Goiania, 15/09/2026). O
# teto barra os 1.149.632 do Brasil caso `id_agencia_conta` deixe de valer.
TETO_LANCAMENTOS = int(os.getenv("FAF_TETO_LANCAMENTOS", "20000") or "20000")
RETRY_S = float(os.getenv("FAF_RETRY_S", "2") or "2")


def _pagina(client: httpx.Client, caminho: str, params: dict, n: int) -> dict | None:
    """Uma pagina. `None` = a fonte nao respondeu 200 (e NAO "acabou").

    ⚠️ UMA RETENTATIVA, e so para erro de rede ou 5xx (429 nao repete). A arvore
    faz ~15 consultas por plano, e sem isto um soluco da fonte jogaria fora o
    plano inteiro. Mesmo desenho de `parcerias._pagina`."""
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
        # ⚠️ O 500 do `codigo_ibge_..._recebedor` mora aqui. O log traz o caminho
        # E os parametros para que um filtro novo que a fonte quebre apareca
        # nomeado, em vez de virar "coletou zero" sem explicacao.
        log.warning("  %s %s: HTTP %s", caminho, params, r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        return None


def buscar(client: httpx.Client, caminho: str, params: dict,
           teto_itens: int | None = None,
           exigir_completo: bool = False) -> list[dict] | None:
    """Todas as paginas. `None` quando a PRIMEIRA falhou; `[]` e ausencia real.

    `exigir_completo`: `None` tambem quando uma pagina DO MEIO falhar. A
    listagem de planos aceita o que veio; a arvore e os beneficiarios nao — um
    extrato com pagina faltando seria gravado como se fosse inteiro.

    ⚠️ `teto_itens` E A GUARDA CONTRA FILTRO IGNORADO, e ela existe porque
    a fonte ignora EM SILENCIO qualquer parametro que nao reconheca: medido em
    07/09/2026, `?parametro_que_nao_existe=xyz` devolve HTTP 200 com os 31.026
    beneficiarios do Brasil inteiro, exatamente como se nao houvesse filtro. Um
    erro de digitacao aqui, ou uma renomeacao do lado deles (o Obras.gov ja
    renomeou TODOS os campos numa troca de host), nao daria erro nenhum: daria
    uma carga nacional gravada como se fosse do municipio da vez.

    Por isso quem filtra por municipio passa o teto do que e plausivel, e um
    `total_items` acima dele devolve `None` — que quem chama ja trata como
    "nao consegui perguntar", e nao como ausencia.
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


def _digitos(v) -> str:
    return "".join(ch for ch in str(v or "") if ch.isdigit())


def _cnpj(v) -> str | None:
    """CNPJ com os 14 digitos. A familia de APIs ja mandou CNPJ como numero e
    perdeu o zero a esquerda (Parcerias, extrato): 12 ou 13 digitos completam."""
    d = _digitos(v)
    if len(d) in (12, 13):
        d = d.zfill(14)
    return d if len(d) == 14 else None


def beneficiarios_do_municipio(client: httpx.Client, ibge: str) -> list[dict] | None:
    """`/programas-beneficiarios` do municipio. `None` = nao consegui perguntar.

    ⚠️ E o passo que substitui o filtro quebrado. Ver o cabecalho do modulo: o
    `codigo_ibge_..._recebedor` de `/planos-acao` devolve 500, e adivinhar entre
    a prefeitura e o fundo municipal erraria em um dos dois modulos da familia.
    Desde 15/09 a resposta tambem e GRAVADA: e quanto cada programa destina ao
    municipio, com ou sem plano enviado."""
    # O teto de 500: Goiania, a maior medida, devolve 62 (com o Estado e as
    # secretarias estaduais sediados nela). Serve so para separar "filtrou" de
    # "devolveu o Brasil" — ver o docstring de `buscar`.
    return buscar(client, "programas-beneficiarios",
                  {"codigo_ibge_municipio_ente_beneficiario_programa": ibge},
                  teto_itens=500, exigir_completo=True)


def cnpjs_do_municipio(beneficiarios: list[dict]) -> list[str]:
    """CNPJs que recebem fundo a fundo neste municipio, ditos PELA FONTE
    (`cnpj_beneficiario_programa` de `/programas-beneficiarios`). Funcao PURA."""
    vistos, fora = set(), []
    for b in beneficiarios or []:
        c = _cnpj(b.get("cnpj_beneficiario_programa"))
        if c and c not in vistos:
            vistos.add(c)
            fora.append(c)
    return fora


# ⚠️ O CAMPO QUE SEPARA O MUNICIPIO DO ESTADO, e o defeito que ele conserta.
#
# O filtro `codigo_ibge_municipio_ente_beneficiario_programa` devolve todo ente
# SEDIADO naquele municipio — e a sede do governo estadual e a capital. Medido
# em 07/09/2026 no tenant trust: os planos do ESTADO DE GOIAS (R$ 470 mi), da
# SECRETARIA DE ESTADO DA SEGURANCA PUBLICA (R$ 265 mi) e da DIRETORIA-GERAL DE
# POLICIA PENAL estavam gravados como planos de GOIANIA, cujo proprio municipio
# tem R$ 73 mi. O mesmo em Palmas com o ESTADO DO TOCANTINS (R$ 164 mi). Dos
# R$ 1,42 bilhao da carteira, ~85% era dinheiro estadual creditado a capital.
#
# E nao ha o que aproveitar nesses planos: o IBGE ali e a SEDE do ente, nao onde
# o dinheiro e aplicado — um plano do Estado de Goias e executado no estado
# inteiro. Guardar seria inventar um vinculo municipal que a fonte nao afirma.
#
# `descricao_tipo_unidade_ente_plano_acao` tem exatamente dois valores em toda a
# base ("Ente Municipal" e "Ente Estadual/Distrital"), e e o que a fonte diz.
ESFERA_MUNICIPAL = "Ente Municipal"


def e_do_municipio(plano: dict) -> bool:
    """O plano e do MUNICIPIO, e nao do estado sediado nele?

    ⚠️ AUSENCIA NAO E EXCLUSAO. Campo nulo devolve True: a fonte pode parar de
    mandar a descricao, e nesse dia a alternativa seria a tela esvaziar em
    silencio — que e pior que um plano estadual a mais. O log conta os
    descartados para que a mudanca apareca.
    """
    v = plano.get("descricao_tipo_unidade_ente_plano_acao")
    if v in (None, ""):
        return True
    return str(v).strip() == ESFERA_MUNICIPAL


def _norm(texto) -> str:
    """Maiusculo, sem acento, so letras/digitos separados por um espaco."""
    s = unicodedata.normalize("NFKD", str(texto or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", s).split())


_MARCA_ESTADO = re.compile(r"\bESTADO\b|\bGOVERNO DO\b|\bDISTRITO FEDERAL\b")
_MARCA_MUNICIPIO = re.compile(r"MUNICIP|PREFEITURA")


def ente_municipal(benef: dict, cnpjs_municipais: set[str]) -> bool:
    """O beneficiario de programa e o MUNICIPIO (ou orgao dele), e nao o estado?

    ⚠️ Os beneficiarios NAO tem campo de esfera — os planos tem. Medido em
    15/09/2026: a consulta por IBGE de Goiania traz o ESTADO DE GOIAS, a
    SECRETARIA DE ESTADO DA SEGURANCA PUBLICA, a SECRETARIA DE ESTADO DA
    RETOMADA e a DIRETORIA-GERAL DE POLICIA PENAL, alem do MUNICIPIO DE GOIANIA.
    A ordem da decisao:

      1. mesma RAIZ de CNPJ (8 digitos) de um plano que a fonte afirma "Ente
         Municipal" nesta rodada -> municipal (pega a filial 24851511002200 de
         Palmas e o fundo municipal de nome sem "municipal");
      2. nome com ESTADO / GOVERNO DO / DISTRITO FEDERAL -> estadual;
      3. nome com MUNICIP / PREFEITURA -> municipal;
      4. o resto fica fora, e e contado no log.

    Funcao PURA."""
    c = _cnpj(benef.get("cnpj_beneficiario_programa"))
    if c and c[:8] in {x[:8] for x in cnpjs_municipais}:
        return True
    nome = _norm(benef.get("nome_ente_beneficiario_programa")
                 or benef.get("nome_beneficiario_programa"))
    if _MARCA_ESTADO.search(nome):
        return False
    return bool(_MARCA_MUNICIPIO.search(nome))


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _data(v):
    s = str(v or "").strip()
    return s[:10] if s else None


def linha(municipio_id: int, plano: dict, relatorios: list[dict] | None) -> dict | None:
    """Traduz UM plano de acao para as colunas. Funcao PURA e testavel.

    Desde 15/09 a listagem passa `relatorios=None`: os relatorios vem da arvore
    (fase 2), que os grava na coluna. O COALESCE do upsert os preserva."""
    pid = plano.get("id_plano_acao")
    if pid in (None, ""):
        return None
    return {
        "mid": municipio_id,
        "id_plano": str(pid),
        "codigo": plano.get("codigo_plano_acao"),
        "id_programa": (str(plano["id_programa"])
                        if plano.get("id_programa") is not None else None),
        "situacao": plano.get("situacao_plano_acao"),
        "dt_ini": _data(plano.get("data_inicio_vigencia_plano_acao")),
        "dt_fim": _data(plano.get("data_fim_vigencia_plano_acao")),
        "diagnostico": plano.get("diagnostico_plano_acao"),
        "objetivos": plano.get("objetivos_plano_acao"),
        "vl_total": _num(plano.get("valor_total_plano_acao")),
        "vl_emenda": _num(plano.get("valor_repasse_emenda_plano_acao")),
        "vl_especifico": _num(plano.get("valor_repasse_especifico_plano_acao")),
        "vl_voluntario": _num(plano.get("valor_repasse_voluntario_plano_acao")),
        "vl_proprios": _num(plano.get("valor_recursos_proprios_plano_acao")),
        "vl_rendimentos": _num(plano.get("valor_rendimentos_aplicacao_plano_acao")),
        "vl_custeio": _num(plano.get("valor_total_custeio_plano_acao")),
        "vl_investimento": _num(plano.get("valor_total_investimento_plano_acao")),
        "vl_saldo": _num(plano.get("valor_saldo_disponivel_plano_acao")),
        "orgao": plano.get("nome_orgao_repassador_plano_acao"),
        "sigla_orgao": plano.get("sigla_orgao_repassador_plano_acao"),
        "fundo": plano.get("nome_fundo_repassador_plano_acao"),
        "cnpj_ente": (plano.get("cnpj_ente_recebedor_plano_acao") or "")[:14] or None,
        "nome_ente": plano.get("nome_ente_recebedor_plano_acao"),
        "tipo_unidade": plano.get("tipo_unidade_recebedora_plano_acao"),
        # Gravada apesar do filtro: quem abrir o banco tem de poder conferir que
        # so ha municipal aqui, sem reler o coletor.
        "esfera": plano.get("descricao_tipo_unidade_ente_plano_acao"),
        # ⚠️ NULO quando nao ha relatorio, e nunca `[]`: lista vazia no banco
        # seria indistinguivel de "coletei e nao ha", e a diferenca entre "nao
        # medido" e "nao existe" e a mesma disciplina do resto do repo.
        "relatorios": (json.dumps(relatorios, ensure_ascii=False)
                       if relatorios else None),
        "raw": json.dumps(plano, ensure_ascii=False),
    }


_SQL = """
INSERT INTO faf_planos_acao (
    municipio_id, id_plano_acao, codigo_plano_acao, id_programa, situacao,
    data_inicio_vigencia, data_fim_vigencia, diagnostico, objetivos,
    valor_total, valor_repasse_emenda, valor_repasse_especifico,
    valor_repasse_voluntario, valor_recursos_proprios, valor_rendimentos,
    valor_custeio, valor_investimento, valor_saldo_disponivel,
    orgao_repassador, sigla_orgao_repassador, fundo_repassador,
    cnpj_ente_recebedor, nome_ente_recebedor, tipo_unidade_recebedora,
    esfera_ente, relatorios_gestao, raw_data, atualizado_em)
VALUES (%(mid)s, %(id_plano)s, %(codigo)s, %(id_programa)s, %(situacao)s,
        %(dt_ini)s, %(dt_fim)s, %(diagnostico)s, %(objetivos)s, %(vl_total)s,
        %(vl_emenda)s, %(vl_especifico)s, %(vl_voluntario)s, %(vl_proprios)s,
        %(vl_rendimentos)s, %(vl_custeio)s, %(vl_investimento)s, %(vl_saldo)s,
        %(orgao)s, %(sigla_orgao)s, %(fundo)s, %(cnpj_ente)s, %(nome_ente)s,
        %(tipo_unidade)s, %(esfera)s, %(relatorios)s::jsonb, %(raw)s::jsonb,
        NOW())
ON CONFLICT (municipio_id, id_plano_acao) DO UPDATE SET
    codigo_plano_acao = EXCLUDED.codigo_plano_acao,
    id_programa = EXCLUDED.id_programa, situacao = EXCLUDED.situacao,
    data_inicio_vigencia = EXCLUDED.data_inicio_vigencia,
    data_fim_vigencia = EXCLUDED.data_fim_vigencia,
    diagnostico = EXCLUDED.diagnostico, objetivos = EXCLUDED.objetivos,
    valor_total = EXCLUDED.valor_total,
    valor_repasse_emenda = EXCLUDED.valor_repasse_emenda,
    valor_repasse_especifico = EXCLUDED.valor_repasse_especifico,
    valor_repasse_voluntario = EXCLUDED.valor_repasse_voluntario,
    valor_recursos_proprios = EXCLUDED.valor_recursos_proprios,
    valor_rendimentos = EXCLUDED.valor_rendimentos,
    valor_custeio = EXCLUDED.valor_custeio,
    valor_investimento = EXCLUDED.valor_investimento,
    valor_saldo_disponivel = EXCLUDED.valor_saldo_disponivel,
    orgao_repassador = EXCLUDED.orgao_repassador,
    sigla_orgao_repassador = EXCLUDED.sigla_orgao_repassador,
    fundo_repassador = EXCLUDED.fundo_repassador,
    cnpj_ente_recebedor = EXCLUDED.cnpj_ente_recebedor,
    nome_ente_recebedor = EXCLUDED.nome_ente_recebedor,
    tipo_unidade_recebedora = EXCLUDED.tipo_unidade_recebedora,
    esfera_ente = EXCLUDED.esfera_ente,
    -- ⚠️ COALESCE no relatorio: a listagem nao busca mais relatorio (a arvore
    -- busca) e passa NULO — que NAO pode apagar o que a arvore gravou.
    relatorios_gestao = coalesce(EXCLUDED.relatorios_gestao,
                                 faf_planos_acao.relatorios_gestao),
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def _municipios(cur) -> list[dict]:
    """Municipios ATIVOS com IBGE — `WHERE active` pelo motivo que a
    Transferencia Especial aprendeu em producao (07/09/2026)."""
    cur.execute("""
        SELECT id, nome, coalesce(ibge_code, '')
          FROM municipios
         WHERE active AND length(coalesce(ibge_code, '')) = 7
         ORDER BY nome
    """)
    return [{"id": r[0], "nome": r[1], "ibge": r[2]} for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# FASE 1b — BENEFICIARIOS DE PROGRAMA E CATALOGO (15/09/2026)
# ---------------------------------------------------------------------------
def linha_beneficiario(municipio_id: int, b: dict) -> dict | None:
    """UM registro de `/programas-beneficiarios` -> colunas. Funcao PURA."""
    bid = b.get("id_beneficiario_programa")
    if bid is None:
        return None
    idp = b.get("id_programa")
    return {
        "mid": municipio_id,
        "bid": int(bid),
        "id_programa": int(idp) if isinstance(idp, (int, float)) else None,
        "cnpj": _cnpj(b.get("cnpj_beneficiario_programa")),
        "nome": b.get("nome_beneficiario_programa"),
        "nome_ente": b.get("nome_ente_beneficiario_programa"),
        "tipo": b.get("tipo_beneficiario_programa"),
        "valor": _num(b.get("valor_beneficiario_programa")),
        "nr_emenda": b.get("numero_emenda_beneficiario_programa"),
        "parlamentar": b.get("nome_parlamentar_beneficiario_programa"),
        "raw": json.dumps(b, ensure_ascii=False),
    }


_SQL_BENEF = """
INSERT INTO faf_programas_beneficiarios (
    municipio_id, id_beneficiario_programa, id_programa, cnpj_beneficiario,
    nome_beneficiario, nome_ente, tipo_beneficiario, valor, numero_emenda,
    parlamentar, raw_data, atualizado_em)
VALUES (%(mid)s, %(bid)s, %(id_programa)s, %(cnpj)s, %(nome)s, %(nome_ente)s,
        %(tipo)s, %(valor)s, %(nr_emenda)s, %(parlamentar)s, %(raw)s::jsonb, NOW())
ON CONFLICT (municipio_id, id_beneficiario_programa) DO UPDATE SET
    id_programa = EXCLUDED.id_programa, cnpj_beneficiario = EXCLUDED.cnpj_beneficiario,
    nome_beneficiario = EXCLUDED.nome_beneficiario, nome_ente = EXCLUDED.nome_ente,
    tipo_beneficiario = EXCLUDED.tipo_beneficiario, valor = EXCLUDED.valor,
    numero_emenda = EXCLUDED.numero_emenda, parlamentar = EXCLUDED.parlamentar,
    raw_data = EXCLUDED.raw_data, atualizado_em = NOW()
"""


def grava_beneficiarios_do_municipio(cur, municipio_id: int, registros: list[dict]) -> int:
    """TROCA o conjunto do municipio: o que a fonte deixou de listar sai daqui.

    So e chamada com a consulta COMPLETA (e com os planos do municipio todos
    respondidos: a raiz de CNPJ municipal sai deles) — consulta falhada nunca
    apaga. Quem chama commita. Mesmo desenho de
    `parcerias.grava_emendas_do_municipio`."""
    linhas = [l for l in (linha_beneficiario(municipio_id, r) for r in registros) if l]
    ids = [l["bid"] for l in linhas]
    if ids:
        cur.execute("DELETE FROM faf_programas_beneficiarios "
                    "WHERE municipio_id = %s AND NOT (id_beneficiario_programa = ANY(%s))",
                    (municipio_id, ids))
    else:
        cur.execute("DELETE FROM faf_programas_beneficiarios WHERE municipio_id = %s",
                    (municipio_id,))
    for l in linhas:
        cur.execute(_SQL_BENEF, l)
    return len(linhas)


def catalogo_de_programas(client: httpx.Client) -> list[dict] | None:
    """`/programas` (125 no Brasil) com o programa da Gestao Agil (a conta BB,
    185) aninhado em `gestao_agil`. `None` = a fonte nao respondeu."""
    progs = buscar(client, "programas", {}, teto_itens=2000, exigir_completo=True)
    ageis = buscar(client, "programas-gestao-agil", {}, teto_itens=2000, exigir_completo=True)
    if progs is None or ageis is None:
        return None
    por_prog: dict[str, list[dict]] = {}
    for a in ageis:
        por_prog.setdefault(str(a.get("id_programa")), []).append(a)
    for p in progs:
        p["gestao_agil"] = por_prog.get(str(p.get("id_programa")), [])
    return progs


def linha_programa(p: dict) -> dict | None:
    """UM programa do catalogo -> colunas. Funcao PURA."""
    idp = p.get("id_programa")
    if idp is None:
        return None
    ano = p.get("ano_programa")
    raw = {k: v for k, v in p.items() if k != "gestao_agil"}
    return {
        "idp": int(idp),
        "ano": int(ano) if isinstance(ano, (int, float)) else None,
        "codigo": (str(p["codigo_programa"]) if p.get("codigo_programa") is not None else None),
        "nome": p.get("nome_programa"),
        "modalidade": p.get("modalidade_programa"),
        "situacao": p.get("situacao_programa"),
        "sigla_orgao": p.get("sigla_orgao_superior_programa"),
        "nome_orgao": p.get("nome_orgao_superior_programa"),
        "nome_fundo": p.get("nome_fundo_programa"),
        "valor_global": _num(p.get("valor_global_programa")),
        "esp_ini": _data(p.get("data_inicio_recebimento_planos_acao_beneficiarios_especificos")),
        "esp_fim": _data(p.get("data_fim_recebimento_planos_acao_beneficiarios_especificos")),
        "eme_ini": _data(p.get("data_inicio_recebimento_planos_acao_beneficiarios_emendas")),
        "eme_fim": _data(p.get("data_fim_recebimento_planos_acao_beneficiarios_emendas")),
        "vol_ini": _data(p.get("data_inicio_recebimento_planos_acao_beneficiarios_voluntarios")),
        "vol_fim": _data(p.get("data_fim_recebimento_planos_acao_beneficiarios_voluntarios")),
        "gestao_agil": json.dumps(p.get("gestao_agil") or [], ensure_ascii=False),
        "raw": json.dumps(raw, ensure_ascii=False),
    }


_SQL_PROGRAMA = """
INSERT INTO faf_programas (
    id_programa, ano, codigo, nome, modalidade, situacao, sigla_orgao, nome_orgao,
    nome_fundo, valor_global, janela_especificos_ini, janela_especificos_fim,
    janela_emendas_ini, janela_emendas_fim, janela_voluntarios_ini,
    janela_voluntarios_fim, gestao_agil, raw_data, atualizado_em)
VALUES (%(idp)s, %(ano)s, %(codigo)s, %(nome)s, %(modalidade)s, %(situacao)s,
        %(sigla_orgao)s, %(nome_orgao)s, %(nome_fundo)s, %(valor_global)s,
        %(esp_ini)s, %(esp_fim)s, %(eme_ini)s, %(eme_fim)s, %(vol_ini)s, %(vol_fim)s,
        %(gestao_agil)s::jsonb, %(raw)s::jsonb, NOW())
ON CONFLICT (id_programa) DO UPDATE SET
    ano = EXCLUDED.ano, codigo = EXCLUDED.codigo, nome = EXCLUDED.nome,
    modalidade = EXCLUDED.modalidade, situacao = EXCLUDED.situacao,
    sigla_orgao = EXCLUDED.sigla_orgao, nome_orgao = EXCLUDED.nome_orgao,
    nome_fundo = EXCLUDED.nome_fundo, valor_global = EXCLUDED.valor_global,
    janela_especificos_ini = EXCLUDED.janela_especificos_ini,
    janela_especificos_fim = EXCLUDED.janela_especificos_fim,
    janela_emendas_ini = EXCLUDED.janela_emendas_ini,
    janela_emendas_fim = EXCLUDED.janela_emendas_fim,
    janela_voluntarios_ini = EXCLUDED.janela_voluntarios_ini,
    janela_voluntarios_fim = EXCLUDED.janela_voluntarios_fim,
    gestao_agil = EXCLUDED.gestao_agil, raw_data = EXCLUDED.raw_data,
    atualizado_em = NOW()
"""


# ---------------------------------------------------------------------------
# FASE 2 — A ARVORE DO PLANO (15/09/2026)
# ---------------------------------------------------------------------------
# Tudo pendurado no plano por ID DO PAI. Cada filtro abaixo foi PROVADO com
# valor impossivel nao-zero (987654321 -> 0 itens) contra a base nacional:
#
#   plano ─┬─ planos-acao-metas ── planos-acao-metas-acoes (id_meta_plano_acao)
#          ├─ planos-acao-destinacao-recursos
#          ├─ planos-acao-historico
#          ├─ planos-acao-analises ── -responsaveis (id_analise_plano_acao)
#          ├─ termos-adesao ── termos-adesao-historico (id_termo_adesao)
#          ├─ empenhos
#          ├─ relatorios-gestao ─┬─ relatorios-gestao-acoes (% fisico por acao)
#          │                     └─ relatorios-gestao-analises
#          │                          └─ -responsaveis (id_relatorio_gestao_analise)
#          └─ planos-acao-dados-bancarios (a CONTA, com o saldo)
#                └─ gestao-financeira-lancamentos (id_agencia_conta, EXATO)
#                      └─ gestao-financeira-subtransacoes (id_lancamento_...)
#
# ⚠️ `relatorios-gestao-analises-responsaveis` so filtra por
# `id_relatorio_gestao_analise`: com `id_analise_relatorio_gestao` (o nome que
# pareceria natural) devolve os 22.182 do Brasil. O teto pega.
class _FonteMuda(Exception):
    """Uma consulta da arvore ficou sem resposta — a arvore inteira nao vale."""


def _filhos(client: httpx.Client, caminho: str, params: dict,
            teto: int | None = None) -> list[dict] | None:
    """Consulta por ID DO PAI: com teto e sem aceitar pagina faltando.

    ⚠️ PARAMETRO NULO = NAO HA O QUE PERGUNTAR: devolve [] SEM tocar a rede —
    filtro vazio e filtro que a fonte ignora, ou seja, o Brasil."""
    if any(v is None or v == "" for v in params.values()):
        return []
    return buscar(client, caminho, params, teto_itens=teto or TETO_FILHOS,
                  exigir_completo=True)


def arvore_do_plano(client: httpx.Client, plano: dict) -> dict | None:
    """As rotas da API penduradas em UM plano. As CONTAS vem so como a fonte as
    lista em `dados-bancarios` (com o saldo); o extrato e buscado por
    `conta_completa`, uma vez por conta por rodada.

    ⚠️ TUDO OU NADA: qualquer consulta sem resposta devolve None, e quem chama
    NAO GRAVA — o detalhe anterior fica e o carimbo nao anda. Uma arvore com o
    parecer faltando seria lida como "o ministerio nao se manifestou".
    """
    pid = plano.get("id_plano_acao")
    if pid in (None, ""):
        return None

    def lista(caminho: str, **params) -> list[dict]:
        itens = _filhos(client, caminho, params)
        if itens is None:
            raise _FonteMuda(f"{caminho} {params}")
        return itens

    try:
        metas = lista("planos-acao-metas", id_plano_acao=pid)
        for meta in metas:
            meta["acoes"] = lista("planos-acao-metas-acoes",
                                  id_meta_plano_acao=meta.get("id_meta_plano_acao"))
        destinacao = lista("planos-acao-destinacao-recursos", id_plano_acao=pid)
        historico = lista("planos-acao-historico", id_plano_acao=pid)
        analises = lista("planos-acao-analises", id_plano_acao=pid)
        for a in analises:
            a["responsaveis"] = lista("planos-acao-analises-responsaveis",
                                      id_analise_plano_acao=a.get("id_analise_plano_acao"))
        termos = lista("termos-adesao", id_plano_acao=pid)
        for t in termos:
            t["historico"] = lista("termos-adesao-historico",
                                   id_termo_adesao=t.get("id_termo_adesao"))
        empenhos = lista("empenhos", id_plano_acao=pid)
        relatorios = lista("relatorios-gestao", id_plano_acao=pid)
        for r in relatorios:
            rid = r.get("id_relatorio_gestao")
            r["acoes"] = lista("relatorios-gestao-acoes", id_relatorio_gestao=rid)
            r["analises"] = lista("relatorios-gestao-analises", id_relatorio_gestao=rid)
            for a in r["analises"]:
                a["responsaveis"] = lista(
                    "relatorios-gestao-analises-responsaveis",
                    id_relatorio_gestao_analise=a.get("id_relatorio_gestao_analise"))
        contas = lista("planos-acao-dados-bancarios", id_plano_acao=pid)
    except _FonteMuda as e:
        log.warning("  arvore %s: sem resposta em %s — nada gravado", pid, str(e)[:160])
        return None

    return {
        "metas": metas,
        "destinacao": destinacao,
        "historico": historico,
        "analises": analises,
        "termos_adesao": termos,
        "empenhos": empenhos,
        "relatorios": relatorios,
        "contas": contas,
    }


# --- A CONTA -----------------------------------------------------------------
_QTD_SUB = "quantidade_subtransacoes_lancamento_gestao_financeira"

# Campos do lancamento que sao da CONTA (iguais em todo lancamento dela). Sobem
# para `faf_contas.cabecalho` — SO se forem iguais em todos (ver `fatora`).
CAMPOS_DA_CONTA = (
    "origem_solicitacao_gestao_financeira",
    "descricao_origem_solicitacao_gestao_financeira",
    "cnpj_ente_solicitante_gestao_financeira",
    "nome_ente_solicitante_gestao_financeira",
    "nome_personalizado_ente_solicitante_gestao_financeira",
    "codigo_programa_agil_ente_solicitante_gestao_financeira",
    "codigo_banco_gestao_financeira",
    "codigo_agencia_gestao_financeira",
    "dv_agencia_gestao_financeira",
    "codigo_conta_gestao_financeira",
    "dv_conta_gestao_financeira",
    "id_agencia_conta",
)


def conta_aberta(id_agencia_conta) -> bool:
    """⚠️ "0086-0" e "3615-0" (Goiania, Porto Velho): plano sem conta aberta. A
    fonte lista a linha em `dados-bancarios` com saldo nulo, e nao ha extrato a
    pedir. So a parte da CONTA toda zero conta como "sem conta" — formato
    estranho segue para a fonte, e um 400 ali aparece no log como falha."""
    s = str(id_agencia_conta or "").strip()
    if not s:
        return False
    conta = s.rsplit("-", 1)[-1]
    return not (conta.isdigit() and int(conta) == 0)


def saldo_da_conta(conta: dict) -> float | None:
    """⚠️ O saldo vem ANINHADO em `saldo_final_dado_bancario` (medido); o openapi
    publica `saldo_final_conta_plano_acao_dado_bancario`, que nao chega. Os dois
    sao lidos — o dia em que a fonte alinhar com o proprio Swagger nao zera nada."""
    aninhado = conta.get("saldo_final_dado_bancario")
    if isinstance(aninhado, dict):
        v = _num(aninhado.get("saldo_final_gestao_financeira"))
        if v is not None:
            return v
    v = conta.get("saldo_final_conta_plano_acao_dado_bancario")
    if isinstance(v, dict):
        return _num(v.get("saldo_final_gestao_financeira"))
    return _num(v)


def _banco(v) -> str:
    return str(v or "").strip().lstrip("0")


def fatora(itens: list[dict], campos) -> tuple[dict, list[dict]]:
    """Sobe para um cabecalho os campos IGUAIS em todos os itens, sem perda:
    campo que varia (ou falta em algum item) fica em cada item. Funcao PURA."""
    cab: dict = {}
    if itens:
        for c in campos:
            if all(c in i for i in itens):
                vals = {json.dumps(i[c], sort_keys=True, ensure_ascii=False) for i in itens}
                if len(vals) == 1:
                    cab[c] = itens[0][c]
    return cab, [{k: v for k, v in i.items() if k not in cab} for i in itens]


def conta_completa(client: httpx.Client, conta: dict) -> dict | None:
    """O extrato inteiro de UMA conta, com as subtransacoes (quem recebeu).

    `None` = alguma consulta sem resposta (tudo ou nada, como a arvore).

    ⚠️ `id_agencia_conta` ("2352-11650") NAO tem o banco. Toda conta medida e do
    BB (Gestao Agil), mas o filtro de banco em memoria custa nada e impede que
    uma agencia-conta igual em outro banco entre no extrato errado."""
    idc = conta.get("id_agencia_conta")
    if not conta_aberta(idc):
        return {"cabecalho": None, "lancamentos": None, "resumo": None}
    lancs = _filhos(client, "gestao-financeira-lancamentos", {"id_agencia_conta": idc},
                    teto=TETO_LANCAMENTOS)
    if lancs is None:
        return None
    banco = _banco(conta.get("codigo_banco_plano_acao_dado_bancario"))
    if banco:
        lancs = [l for l in lancs
                 if not _banco(l.get("codigo_banco_gestao_financeira"))
                 or _banco(l.get("codigo_banco_gestao_financeira")) == banco]
    for l in lancs:
        if (_num(l.get(_QTD_SUB)) or 0) > 0:
            subs = _filhos(client, "gestao-financeira-subtransacoes",
                           {"id_lancamento_gestao_financeira":
                            l.get("id_lancamento_gestao_financeira")})
            if subs is None:
                return None
            l["subtransacoes"] = subs
    cab, lancs = fatora(lancs, CAMPOS_DA_CONTA)
    return {"cabecalho": cab, "lancamentos": lancs, "resumo": resumo_da_conta(lancs, cab)}


# --- O RESUMO DA CONTA ---------------------------------------------------------
# Vocabulario do extrato do BB, medido em 15/09/2026 em Goiania, Palmas e Nova
# Palma (2.300 lancamentos). ⚠️ Parte das linhas vem com o ACENTO COMIDO
# ("Emisso de Ordem Bancria", "Resgate Automtico", "Aplicao em BB Fix"): por isso
# as regras sao PREFIXOS sem acento, que casam as duas grafias.
_INTERNO = re.compile(r"\bAPLI|\bRESGATE|\bPOUPAN|\bBB FIX")
_ESTORNO = re.compile(r"\bCANCEL|\bDEVOLV|\bESTORN")
_OB = re.compile(r"\bORDEM BANC")
# "Depsito Online" (Santa Maria, 0126-89855) e o acento comido de "Deposito".
_CREDITO_CONHECIDO = re.compile(
    r"\bTRANSF|\bTED\b|\bPIX\b|\bDEPO?SITO|\bDEP\b|\bMOVIMENTO DO DIA|\bDOC\b")
# "Devolucao Cheque Depositado" (Santa Maria, 0126-96288): o cheque creditado que
# voltou sai como debito.
_DEBITO_CONHECIDO = re.compile(
    r"\bORDEM BANC|\bEMISS|\bTED\b|\bTRANSF|\bPAGTO|\bPAGAMENTO|\bPIX\b|\bIMPOSTO|"
    r"\bTARIFA|\bDOC\b|\bBOLETO|\bDEBITO|\bTRIBUTO|\bCHEQUE")
_DOC_BB = "00000000000191"
# ⚠️ GRU: o debito com favorecido "MINISTERIO DA FAZENDA" (raiz 00394460, a do
# Tesouro) e DEVOLUCAO A UNIAO, nao pagamento a beneficiario. Medido em Palmas
# (conta 3615-6319, 09/06/2026): "Pagto via Auto-Atendimento BB" de R$ 26.730,50
# para 00394460040950 — o saldo que sobrou voltando.
_RAIZ_TESOURO = "00394460"


def classifica_lancamento(l: dict) -> str:
    """recebido_ob | estorno | interno | outro_credito | saida | nao_classificado.

    - interno: aplicacao, resgate, poupanca — o dinheiro muda de gaveta, nao sai.
      E por isso que credito menos debito da ZERO na conta corrente.
    - estorno: OB cancelada, TED devolvida — dinheiro que VOLTOU.
    - recebido_ob: credito por ordem bancaria (o repasse da Uniao).
    - saida: debito que deixou a conta (OB emitida, TED, transferencia,
      pagamento, imposto).
    - nao_classificado: descricao que nenhuma regra reconhece — CONTADA, para que
      vocabulario novo do banco apareca em vez de sumir das somas.
    Funcao PURA."""
    d = _norm(l.get("descricao_gestao_financeira"))
    tipo = str(l.get("tipo_operacao_gestao_financeira") or "").upper()
    if _INTERNO.search(d):
        return "interno"
    if tipo == "C":
        if _ESTORNO.search(d):
            return "estorno"
        if _OB.search(d):
            return "recebido_ob"
        if _CREDITO_CONHECIDO.search(d):
            return "outro_credito"
        return "nao_classificado"
    if tipo == "D":
        return "saida" if _DEBITO_CONHECIDO.search(d) else "nao_classificado"
    return "nao_classificado"


def _pago(sub: dict) -> bool:
    return _norm(sub.get("descricao_situacao_pagamento_subtransacao_gestao_financeira")) == "PAGO"


def resumo_da_conta(lancs: list[dict], cab: dict | None = None) -> dict:
    """O que aconteceu com o dinheiro da conta, em numeros. Funcao PURA.

    ⚠️ O SALDO NAO SAI DAQUI: e o `saldo_final` que a fonte informa (ver
    `saldo_da_conta`). Credito menos debito da zero na conta corrente, porque o
    dinheiro fica na aplicacao automatica.

    PAGO A BENEFICIARIOS = subtransacoes "Pago" (a OB emitida em lote, com cada
    beneficiario: nome, CPF mascarado, valor, categoria) + debito que saiu com o
    favorecido IDENTIFICADO (TED/transferencia com CPF ou CNPJ) e sem
    subtransacao — o que nao for o proprio ente nem o banco (a aplicacao
    automatica sai com o CNPJ do BB).

    DEVOLVIDO A UNIAO = saida para o Tesouro (GRU, raiz 00394460): continua em
    `saidas`, mas nao e beneficiario.
    """
    cab = cab or {}
    somas = {k: 0.0 for k in ("recebido_ob", "estorno", "interno", "outro_credito",
                              "saida", "nao_classificado")}
    n_nao_classificado = 0
    desc_nao_classificadas: list[str] = []
    pago = devolvido = 0.0
    beneficiarios: set[str] = set()
    datas: list[str] = []
    for l in lancs or []:
        v = _num(l.get("valor_lancamento_gestao_financeira")) or 0.0
        cat = classifica_lancamento(l)
        somas[cat] += v
        if cat == "nao_classificado":
            n_nao_classificado += 1
            d = str(l.get("descricao_gestao_financeira") or "")
            if d and d not in desc_nao_classificadas and len(desc_nao_classificadas) < 10:
                desc_nao_classificadas.append(d)
        d10 = _data(l.get("data_lancamento_gestao_financeira"))
        if d10:
            datas.append(d10)
        subs = l.get("subtransacoes") or []
        for s in subs:
            if _pago(s):
                pago += _num(s.get("valor_subtransacao_gestao_financeira")) or 0.0
                beneficiarios.add(f"{s.get('doc_beneficiario_subtransacao_gestao_financeira_mask')}|"
                                  f"{_norm(s.get('nome_beneficiario_subtransacao_gestao_financeira'))}")
        if cat == "saida" and not subs:
            doc = _digitos(l.get("doc_favorecido_gestao_financeira_mask"))
            ente = _digitos(l.get("cnpj_ente_solicitante_gestao_financeira")
                            or cab.get("cnpj_ente_solicitante_gestao_financeira"))
            tipo_fav = str(l.get("tipo_favorecido_gestao_financeira") or "")
            if tipo_fav == "2" and doc.startswith(_RAIZ_TESOURO):
                devolvido += v
            elif tipo_fav in ("1", "2") and doc and doc != ente and doc != _DOC_BB:
                pago += v
                beneficiarios.add(f"{l.get('doc_favorecido_gestao_financeira_mask')}|"
                                  f"{_norm(l.get('nome_favorecido_gestao_financeira'))}")
    return {
        "n_lancamentos": len(lancs or []),
        "primeiro_lancamento": min(datas) if datas else None,
        "ultimo_lancamento": max(datas) if datas else None,
        "recebido_ob": round(somas["recebido_ob"], 2),
        "estornos": round(somas["estorno"], 2),
        "outros_creditos": round(somas["outro_credito"], 2),
        "saidas": round(somas["saida"], 2),
        "movimento_interno": round(somas["interno"], 2),
        "pago_a_beneficiarios": round(pago, 2),
        "n_beneficiarios": len(beneficiarios),
        "devolvido_uniao": round(devolvido, 2),
        "nao_classificado": round(somas["nao_classificado"], 2),
        "n_nao_classificado": n_nao_classificado,
        "descricoes_nao_classificadas": desc_nao_classificadas,
    }


# --- O RESUMO DO PLANO ---------------------------------------------------------
def _ultimo(itens: list[dict], *campos_ordem: str) -> dict | None:
    if not itens:
        return None
    return max(itens, key=lambda i: tuple(str(i.get(c) or "") for c in campos_ordem))


def _cancelado(situacao) -> bool:
    return "CANCEL" in _norm(situacao)


def resumo_do_plano(arv: dict, contas: dict[str, dict] | None = None) -> dict:
    """O que a listagem mostra do plano. `contas` = {id_agencia_conta: resumo da
    conta} (o extrato vem de `faf_contas`, nao da arvore). Funcao PURA.

    ⚠️ SALDO DO PLANO = saldo das contas QUE ELE USA. Conta dividida com outro
    plano aparece inteira nos dois (e a verdade da conta; quem a divide esta em
    `faf_contas.planos`): somar o saldo do MUNICIPIO e por conta, em
    `faf_contas`, nunca por plano."""
    contas = contas or {}
    saldo = 0.0
    tem_saldo = False
    abertas = 0
    pago = recebido = devolvido = 0.0
    for c in arv.get("contas") or []:
        if conta_aberta(c.get("id_agencia_conta")):
            abertas += 1
        s = saldo_da_conta(c)
        if s is not None:
            tem_saldo = True
            saldo += s
        rc = contas.get(str(c.get("id_agencia_conta"))) or {}
        pago += rc.get("pago_a_beneficiarios") or 0.0
        recebido += rc.get("recebido_ob") or 0.0
        devolvido += rc.get("devolvido_uniao") or 0.0
    hist =_ultimo(arv.get("historico") or [], "data_historico_plano_acao",
                   "id_historico_plano_acao")
    rel = _ultimo(arv.get("relatorios") or [], "data_e_hora_relatorio_gestao",
                  "id_relatorio_gestao")
    pct = None
    if rel and rel.get("acoes"):
        vals = [_num(a.get("percentual_execucao_fisica_acao_relatorio_gestao_acao"))
                for a in rel["acoes"]]
        vals = [v for v in vals if v is not None]
        pct = round(sum(vals) / len(vals), 1) if vals else None
    analise = _ultimo(arv.get("analises") or [], "data_analise_plano_acao",
                      "id_analise_plano_acao")
    termo = _ultimo(arv.get("termos_adesao") or [], "data_assinatura_termo_adesao",
                    "id_termo_adesao")
    empenhado = sum(_num(e.get("valor_empenho")) or 0.0
                    for e in arv.get("empenhos") or []
                    if not _cancelado(e.get("descricao_situacao_empenho")))
    metas = arv.get("metas") or []
    return {
        "n_metas": len(metas),
        "n_acoes": sum(len(m.get("acoes") or []) for m in metas),
        "meta_principal": (metas[0].get("nome_meta_plano_acao") if metas else None),
        "situacao_atual": hist.get("situacao_historico_plano_acao") if hist else None,
        "data_situacao": _data(hist.get("data_historico_plano_acao")) if hist else None,
        "enviado_em": min((_data(h.get("data_historico_plano_acao"))
                           for h in arv.get("historico") or []
                           if h.get("data_historico_plano_acao")), default=None),
        "ultima_analise": ({"tipo": analise.get("tipo_analise_plano_acao"),
                            "resultado": analise.get("tipo_resultado_analise_plano_acao"),
                            "data": _data(analise.get("data_analise_plano_acao"))}
                           if analise else None),
        "termo": ({"situacao": termo.get("situacao_termo_adesao"),
                   "assinado_em": _data(termo.get("data_assinatura_termo_adesao"))}
                  if termo else None),
        "relatorio": ({"tipo": rel.get("tipo_relatorio_gestao"),
                       "situacao": rel.get("situacao_relatorio_gestao"),
                       "data": _data(rel.get("data_relatorio_gestao")),
                       "valor_executado": _num(rel.get("valor_executado_relatorio_gestao")),
                       "valor_pendente": _num(rel.get("valor_pendente_relatorio_gestao")),
                       "pct_fisico_medio": pct}
                      if rel else None),
        "n_relatorios": len(arv.get("relatorios") or []),
        "empenhado": round(empenhado, 2),
        "n_contas": len(arv.get("contas") or []),
        "n_contas_abertas": abertas,
        "saldo_em_conta": round(saldo, 2) if tem_saldo else None,
        "recebido_ob": round(recebido, 2),
        "pago_a_beneficiarios": round(pago, 2),
        "devolvido_uniao": round(devolvido, 2),
    }


def _data_da_fonte(client: httpx.Client) -> str | None:
    """`/data-atualizacao`: quando a PROPRIA fonte se atualizou (outra coisa que a
    hora da nossa coleta). Medido: `2026-09-14T06:02:13`."""
    try:
        r = client.get(f"{BASE}/data-atualizacao", headers=UA, timeout=30)
        if r.status_code == 200:
            return (r.json() or {}).get("data_ultima_atualizacao")
    except Exception as e:
        log.warning("  /data-atualizacao: %s", str(e)[:100])
    return None


def _grava_data_da_fonte(cur, conn, data: str | None) -> None:
    """Grava em `fonte_atualizacao` (chave `transferegov_fundoafundo`). Excecao
    engolida: a tabela nasce numa migration, e isso nao pode custar a coleta."""
    if not data:
        return
    try:
        cur.execute(
            "INSERT INTO fonte_atualizacao (fonte, data_fonte, consultado_em) "
            "VALUES ('transferegov_fundoafundo', %s, NOW()) "
            "ON CONFLICT (fonte) DO UPDATE SET data_fonte = EXCLUDED.data_fonte, "
            "consultado_em = NOW()", (data,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("fonte_atualizacao falhou: %s", str(e)[:120])


_SQL_CONTA = """
INSERT INTO faf_contas (
    municipio_id, id_agencia_conta, codigo_banco, nome_banco, agencia, dv_agencia,
    conta, dv_conta, situacao, data_abertura, programa_agil, saldo_final, planos,
    cabecalho, lancamentos, resumo, n_lancamentos, ultimo_lancamento, atualizado_em)
VALUES (%(mid)s, %(idc)s, %(banco)s, %(nome_banco)s, %(agencia)s, %(dv_agencia)s,
        %(conta)s, %(dv_conta)s, %(situacao)s, %(abertura)s, %(programa_agil)s,
        %(saldo)s, ARRAY[%(plano)s]::text[], %(cabecalho)s::jsonb,
        %(lancamentos)s::jsonb, %(resumo)s::jsonb, %(n)s, %(ultimo)s, NOW())
ON CONFLICT (municipio_id, id_agencia_conta) DO UPDATE SET
    codigo_banco = EXCLUDED.codigo_banco, nome_banco = EXCLUDED.nome_banco,
    agencia = EXCLUDED.agencia, dv_agencia = EXCLUDED.dv_agencia,
    conta = EXCLUDED.conta, dv_conta = EXCLUDED.dv_conta,
    situacao = EXCLUDED.situacao, data_abertura = EXCLUDED.data_abertura,
    programa_agil = EXCLUDED.programa_agil, saldo_final = EXCLUDED.saldo_final,
    planos = (SELECT array_agg(DISTINCT x ORDER BY x)
                FROM unnest(faf_contas.planos || EXCLUDED.planos) AS x),
    cabecalho = EXCLUDED.cabecalho, lancamentos = EXCLUDED.lancamentos,
    resumo = EXCLUDED.resumo, n_lancamentos = EXCLUDED.n_lancamentos,
    ultimo_lancamento = EXCLUDED.ultimo_lancamento, atualizado_em = NOW()
"""

# Conta ja atualizada NESTA rodada por outro plano: so soma o plano.
_SQL_CONTA_SO_PLANO = """
UPDATE faf_contas
   SET planos = (SELECT array_agg(DISTINCT x ORDER BY x) FROM unnest(planos || ARRAY[%s]::text[]) AS x)
 WHERE municipio_id = %s AND id_agencia_conta = %s
"""


def linha_conta(municipio_id: int, id_plano: str, conta: dict, extrato: dict) -> dict:
    """Conta de `dados-bancarios` + extrato de `conta_completa` -> colunas."""
    lancs = extrato.get("lancamentos")
    res = extrato.get("resumo")
    return {
        "mid": municipio_id,
        "idc": str(conta.get("id_agencia_conta")),
        "banco": conta.get("codigo_banco_plano_acao_dado_bancario"),
        "nome_banco": conta.get("nome_banco_plano_acao_dado_bancario"),
        "agencia": conta.get("numero_agencia_plano_acao_dado_bancario"),
        "dv_agencia": conta.get("dv_agencia_plano_acao_dado_bancario"),
        "conta": conta.get("numero_conta_plano_acao_dado_bancario"),
        "dv_conta": conta.get("dv_conta_plano_acao_dado_bancario"),
        "situacao": conta.get("situacao_conta_plano_acao_dado_bancario"),
        "abertura": _data(conta.get("data_abertura_conta_plano_acao_dado_bancario")),
        "programa_agil": conta.get("nome_programa_agil_conta_plano_acao_dado_bancario"),
        "saldo": saldo_da_conta(conta),
        "plano": str(id_plano),
        "cabecalho": json.dumps(extrato.get("cabecalho"), ensure_ascii=False)
        if extrato.get("cabecalho") is not None else None,
        "lancamentos": json.dumps(lancs, ensure_ascii=False) if lancs is not None else None,
        "resumo": json.dumps(res, ensure_ascii=False) if res is not None else None,
        "n": len(lancs) if lancs is not None else None,
        "ultimo": (res or {}).get("ultimo_lancamento"),
    }


def run_detalhe(client: httpx.Client, conn, cur, budget_s: float) -> dict:
    """FASE 2: a arvore de cada plano da carteira, os mais velhos primeiro.

    Fila `ORDER BY detalhe_atualizado_em NULLS FIRST`: o que nao coube hoje e o
    primeiro de amanha. So municipios ATIVOS.

    ⚠️ CONTA DIVIDIDA E BUSCADA UMA VEZ POR RODADA (`feitas`): em Goiania cinco
    planos usam as mesmas duas contas, e o extrato de 1126-8216 sairia cinco vezes.
    """
    cur.execute(
        "SELECT p.id, p.municipio_id, p.id_plano_acao, p.raw_data FROM faf_planos_acao p "
        "  JOIN municipios m ON m.id = p.municipio_id AND m.active "
        " WHERE p.detalhe_atualizado_em IS NULL "
        "    OR p.detalhe_atualizado_em < NOW() - make_interval(secs => %s) "
        " ORDER BY p.detalhe_atualizado_em NULLS FIRST, p.id",
        (DET_MAX_AGE_H * 3600,))
    fila = cur.fetchall()
    if not fila:
        log.info("FaF arvore: nada vencido nesta rodada")
        return {"fila": 0, "atualizados": 0, "falhas": 0, "restantes": 0}
    log.info("FaF arvore: %d plano(s) na fila (orcamento %.0fs)", len(fila), budget_s)
    t0 = time.time()
    # (municipio_id, id_agencia_conta) -> resumo, das contas ja buscadas agora
    feitas: dict[tuple[int, str], dict | None] = {}
    feitos = falhas = processados = contas_buscadas = 0
    for pk, mid, id_plano, raw in fila:
        if (time.time() - t0) >= budget_s:
            log.warning("FaF arvore: orcamento estourado apos %d plano(s); "
                        "%d entram primeiro na proxima rodada", processados,
                        len(fila) - processados)
            break
        processados += 1
        raw = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
        arv = arvore_do_plano(client, {**raw, "id_plano_acao": raw.get("id_plano_acao", id_plano)})
        if arv is None:
            falhas += 1
            continue
        # As contas do plano: extrato das que ainda nao sairam nesta rodada.
        novas: list[dict] = []
        so_plano: list[str] = []
        resumos: dict[str, dict] = {}
        falhou = False
        for c in arv["contas"]:
            idc = str(c.get("id_agencia_conta") or "")
            if not idc:
                continue
            if (mid, idc) in feitas:
                so_plano.append(idc)
                resumos[idc] = feitas[(mid, idc)] or {}
                continue
            ext = conta_completa(client, c)
            if ext is None:
                log.warning("  arvore %s: extrato da conta %s sem resposta — nada gravado",
                            id_plano, idc)
                falhou = True
                break
            contas_buscadas += 1
            novas.append(linha_conta(mid, str(id_plano), c, ext))
            resumos[idc] = ext.get("resumo") or {}
        if falhou:
            falhas += 1
            continue
        for l in novas:
            cur.execute(_SQL_CONTA, l)
        for idc in so_plano:
            cur.execute(_SQL_CONTA_SO_PLANO, (str(id_plano), mid, idc))
        # Conta que o plano deixou de usar perde a referencia a ele.
        cur.execute("UPDATE faf_contas SET planos = array_remove(planos, %s) "
                    "WHERE municipio_id = %s AND %s = ANY(planos) "
                    "AND NOT (id_agencia_conta = ANY(%s))",
                    (str(id_plano), mid, str(id_plano),
                     [str(c.get("id_agencia_conta")) for c in arv["contas"]]))
        arv["_resumo"] = resumo_do_plano(arv, resumos)
        cur.execute("UPDATE faf_planos_acao SET detalhe = %s::jsonb, "
                    "detalhe_atualizado_em = NOW(), relatorios_gestao = %s::jsonb "
                    "WHERE id = %s",
                    (json.dumps(arv, ensure_ascii=False),
                     json.dumps(arv["relatorios"], ensure_ascii=False) if arv["relatorios"] else None,
                     pk))
        conn.commit()   # plano a plano: progresso persiste se a tarefa cair
        for l in novas:
            feitas[(mid, l["idc"])] = json.loads(l["resumo"]) if l["resumo"] else None
        feitos += 1
    restantes = len(fila) - processados
    log.info("FaF arvore: FIM — %d de %d plano(s) atualizado(s), %d sem resposta, "
             "%d para a proxima rodada, %d conta(s) com extrato em %.0fs",
             feitos, len(fila), falhas, restantes, contas_buscadas, time.time() - t0)
    return {"fila": len(fila), "atualizados": feitos, "falhas": falhas,
            "restantes": restantes, "contas": contas_buscadas}


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('faf_planos', %s, %s, %s, NOW())",
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
            if not dry and os.getenv("FAF_FORCE") != "1":
                cur.execute("SELECT max(finished_at) FROM ingestion_log "
                            "WHERE source = 'faf_planos' AND status IN ('success','ok')")
                ultimo = (cur.fetchone() or [None])[0]
                if ultimo:
                    horas = (datetime.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600
                    if horas < MIN_INTERVAL_H:
                        log.info("ultima coleta ha %.1fh (< %dh) — pulando. "
                                 "FAF_FORCE=1 forca.", horas, MIN_INTERVAL_H)
                        return 0

            municipios = _municipios(cur)
            if not municipios:
                msg = "nenhum municipio ativo com IBGE na carteira"
                log.warning(msg)
                if not dry:
                    _log_ingest(cur, conn, "success", 0, msg)
                return 0

            gravados = com_plano = com_emenda = falhas = atendidos = 0
            de_estado = benef_gravados = benef_estaduais = benef_pulados = 0
            completo = True
            catalogo_ok = True
            det = None
            # A fatia da arvore e RESERVADA antes, e nao o que sobrar — mesma
            # licao de `transferegov_te.run` (sem reserva, a fase seguinte nunca
            # roda numa rodada lenta).
            teto_listagem = max(60.0, min(BUDGET_S, TETO_TAREFA_S - DET_MIN_S))
            log.info("FaF: %d municipio(s) na carteira — teto da tarefa %.0fs, "
                     "listagem ate %.0fs", len(municipios), TETO_TAREFA_S, teto_listagem)
            with httpx.Client(follow_redirects=True) as client:
                fonte_data = _data_da_fonte(client)
                log.info("FaF: fonte atualizada em %s", fonte_data or "(nao informado)")
                if not dry:
                    _grava_data_da_fonte(cur, conn, fonte_data)
                # Catalogo nacional: 2 consultas por rodada.
                progs = catalogo_de_programas(client)
                if progs is None:
                    catalogo_ok = False
                    log.warning("FaF: catalogo de programas sem resposta — fica o de ontem")
                elif not dry:
                    for p in progs:
                        lp = linha_programa(p)
                        if lp:
                            cur.execute(_SQL_PROGRAMA, lp)
                    conn.commit()
                    log.info("FaF: %d programa(s) no catalogo", len(progs))

                for m in municipios:
                    if (time.time() - t0) >= teto_listagem:
                        completo = False
                        log.warning("orcamento estourado apos %d municipio(s)", atendidos)
                        break
                    atendidos += 1
                    benefs = beneficiarios_do_municipio(client, m["ibge"])
                    if benefs is None:
                        falhas += 1
                        continue
                    cnpjs = cnpjs_do_municipio(benefs)
                    planos: list[dict] = []
                    planos_ok = True
                    for cnpj in cnpjs:
                        time.sleep(PAUSA_S)
                        # Mesma guarda, mesmo motivo: Nova Palma tem 4 planos
                        # e a base nacional tem 25.971. Ver `buscar`.
                        achados = buscar(client, "planos-acao",
                                         {"cnpj_ente_recebedor_plano_acao": cnpj},
                                         teto_itens=2000)
                        if achados is None:
                            falhas += 1
                            planos_ok = False
                            continue
                        # ⚠️ O filtro de CNPJ e "contem": so fica o CNPJ igual.
                        planos.extend(p for p in achados
                                      if _cnpj(p.get("cnpj_ente_recebedor_plano_acao")) == cnpj)
                    # ⚠️ AQUI SAI O DINHEIRO DO ESTADO. Ver `e_do_municipio`: o
                    # filtro por IBGE entrega tambem o governo estadual, cuja
                    # sede e a capital, e somar isso ao municipio ja produziu
                    # R$ 470 mi do ESTADO DE GOIAS creditados a Goiania.
                    antes = len(planos)
                    planos = [p for p in planos if e_do_municipio(p)]
                    if antes != len(planos):
                        de_estado += antes - len(planos)
                        log.info("  %s: %d plano(s) de ente ESTADUAL descartado(s)",
                                 m["nome"], antes - len(planos))
                    # BENEFICIARIOS: so com os planos todos respondidos, porque a
                    # raiz de CNPJ municipal que decide `ente_municipal` sai deles.
                    if planos_ok:
                        cnpjs_mun = {c for c in (_cnpj(p.get("cnpj_ente_recebedor_plano_acao"))
                                                 for p in planos) if c}
                        do_mun = [b for b in benefs if ente_municipal(b, cnpjs_mun)]
                        benef_estaduais += len(benefs) - len(do_mun)
                        if not dry:
                            benef_gravados += grava_beneficiarios_do_municipio(cur, m["id"], do_mun)
                    else:
                        benef_pulados += 1
                    if planos:
                        com_plano += 1
                    for plano in planos:
                        l = linha(m["id"], plano, None)
                        if l is None:
                            continue
                        if (l["vl_emenda"] or 0) > 0:
                            com_emenda += 1
                        if dry:
                            continue
                        cur.execute(_SQL, l)
                        gravados += 1
                    conn.commit()   # municipio a municipio: progresso persiste
                    log.info("  %s: %d plano(s) de acao (%d CNPJ)",
                             m["nome"], len(planos), len(cnpjs))

                if dry:
                    log.info("DRY: %d municipio(s), %d com plano", atendidos, com_plano)
                    return 0
                log.info("=== FaF: %d plano(s) gravado(s), %d com repasse de emenda, "
                         "%d municipio(s) com plano, %d de ente estadual descartado(s), "
                         "%d falha(s); %d beneficiario(s) de programa (%d estadual(is) "
                         "fora) em %.0fs ===",
                         gravados, com_emenda, com_plano, de_estado, falhas,
                         benef_gravados, benef_estaduais, time.time() - t0)

                # FASE 2 — a arvore, com o que sobrou do teto da tarefa.
                resto = TETO_TAREFA_S - (time.time() - t0)
                if resto < 30:
                    log.warning("FaF arvore: sem tempo nesta rodada (sobraram %.0fs)", resto)
                    det = {"erro": "sem tempo nesta rodada; a fila inteira fica para a proxima"}
                else:
                    try:
                        det = run_detalhe(client, conn, cur, budget_s=resto)
                    except Exception as e:
                        conn.rollback()
                        log.warning("FaF arvore falhou: %s", str(e)[:150])
                        det = {"erro": str(e)[:150]}

            # Municipio sem plano fundo a fundo e estado legitimo. O que denuncia
            # defeito e a fonte nao responder a ninguem — ou o filtro por CNPJ
            # comecar a devolver 500 como o de IBGE ja devolve.
            if falhas and not gravados:
                lst = {"status": "error", "gravados": 0,
                       "erro": "a fonte nao respondeu a nenhum municipio"}
            elif falhas or not completo:
                lst = {"status": "partial", "gravados": gravados,
                       "erro": (f"{falhas} consulta(s) sem resposta" if falhas
                                else "orcamento estourado; retoma na proxima rodada")}
            elif not catalogo_ok:
                lst = {"status": "partial", "gravados": gravados,
                       "erro": "catalogo de programas sem resposta; fica o da rodada anterior"}
            elif gravados >= 20 and not benef_gravados:
                # Todo municipio medido tem ao menos um beneficiario municipal (e
                # dele saem os proprios planos): planos gravados sem nenhum
                # beneficiario e a fonte no meio de uma recarga.
                lst = {"status": "partial", "gravados": gravados,
                       "erro": f"{gravados} plano(s) e nenhum beneficiario de programa "
                               f"— provavel recarga da fonte"}
            else:
                lst = {"status": "success", "gravados": gravados, "erro": None}
            # UMA linha no ingestion_log, somando listagem e arvore — a mesma regra
            # de `transferegov_te` (uma segunda linha mudaria a "ultima coleta").
            status, n, erro = status_da_rodada(lst, det)
            _log_ingest(cur, conn, status, n, erro)
            return gravados
        except Exception as e:
            conn.rollback()
            log.error("FaF falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest(dry="--dry" in sys.argv)
