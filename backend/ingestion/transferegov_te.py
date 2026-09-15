"""Coletor da TRANSFERENCIA ESPECIAL / EMENDA PIX (federal) -> tabela transferegov_te.

⭐ A API PUBLICA OFICIAL INTEIRA, desde 14/09/2026 (`api-publica.transferegov.
gestao.gov.br/especiais`, Comunicado no 23/2026 do MGI). Tres fases numa rodada:

  1. LISTAGEM (planos de acao) -> `run_municipios`, 2 requisicoes por municipio.
  2. ARVORE DO PLANO -> `run_detalhe`: os outros 21 recursos da API, pendurados
     no plano (plano de trabalho, pareceres, metas, empenhos, DH -> OP/OB, conta,
     extrato, relatorios de gestao, QUEM RECEBEU, devolucoes, historicos). Os
     PAGAMENTOS saem daqui, no MESMO formato que o RM ja le.
  3. RESERVA NA SPA -> `run_reserva_spa`: SO o que a oficial nao publica — o CPF
     completo do ordenador/gestor e o HISTORICO DE EVENTOS da ordem de pagamento,
     que a tela mostra. Uma requisicao por OP nova, nunca de novo pela mesma.

A API interna da SPA (`especiais.transferegov.sistema.gov.br/.../api/public`)
tem quota por IP e ja deixou a VPS bloqueada por >6h (INFRA.md §5). Ela saiu da
listagem em 06/09 e dos pagamentos em 14/09; o caminho antigo de pagamentos
continua no codigo como reserva completa, ligada por `TE_PGTO_FONTE=spa`.

⭐ POR QUE A LISTAGEM MUDOU DE FONTE. A da SPA cobra caro por um dado que a
oficial da de graca:

    ate 05/09/2026 (SPA)                  desde aqui (API oficial)
    ------------------------------------  ------------------------------------
    36 paginas de 5 MB por UF             2 requisicoes por MUNICIPIO
    403 apos ~10 paginas; IP da VPS       nenhum bloqueio observado
      punido por >6h (INFRA.md §5)
    25 de 42 rodadas parciais em 30 dias  —
    municipio casado por SUBSTRING DE     municipio casado por CNPJ
      NOME (628 de 890 linhas com CNPJ      (`municipios.cnpj` -> id_beneficiario)
      divergente no tenant trust)
    "Amplia??o De Sistema..."             "Ampliação De Sistema..."
      (mojibake na propria fonte)

⚠️ OS IDs SAO OS MESMOS NAS DUAS APIs — conferido campo a campo em 06/09/2026 na
cadeia inteira: plano 3200 == 3200, empenho 62311 == 62311, documento habil 76255
== 76255, OP/OB 53038 == 53038. E por isso que a troca de fonte NAO duplica linha
(a PK e `plano_acao_id`) e que a fase de pagamentos, que entra pelo id do plano,
continua funcionando sem uma linha de mudanca.

⚠️ O VOCABULARIO DA SITUACAO DO PLANO DE TRABALHO NAO E O MESMO — ver
`_SITUACAO_PT_PARA_CODIGO`. A oficial manda rotulo legivel ("Aprovado"), a SPA
mandava codigo ("APROVADO"), e o RM le por SUBSTRING. Normalizamos para o codigo.

O RM (services/rm_builder) e a tela (routers/transferegov.buscar) leem esta tabela.

Rodar:  python -m ingestion.transferegov_te
        TE_MUNICIPIO=123 python -m ingestion.transferegov_te   (um municipio so)
        TE_TETO_TAREFA_S=3150 ...   (o teto da tarefa inteira; ver `_TETO_TAREFA_S`)
"""
from __future__ import annotations
import os
import re
import json
import time
import asyncio
import logging
import unicodedata

import httpx
import psycopg2

logger = logging.getLogger("transferegov_te")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Cabecalhos da API interna da SPA — usados SO pelos endpoints de pagamento
# (`_API_DH` / `_API_OPOB`, mais abaixo). A listagem dela saiu deste coletor.
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
    "Referer": "https://especiais.transferegov.sistema.gov.br/transferencia-especial/plano-acao/consulta",
}

# ---------------------------------------------------------------------------
# API PUBLICA OFICIAL (Comunicado no 23/2026 do MGI) — a LISTAGEM vem daqui
# ---------------------------------------------------------------------------
# ⚠️ `api-publica`, e nao `api`. Mesma pegadinha do Obras.gov.br: o host sem o
# prefixo e o que bloqueia (ver `ingestion/obrasgov.py`).
_API_PUB = os.getenv("TE_API_PUBLICA",
                     "https://api-publica.transferegov.gestao.gov.br/especiais")
# Envelope de todo endpoint: {data, total_pages, total_items, page_number, page_size}.
# `pagina` e 1-based e `tamanho_da_pagina` tem teto 200 (201 -> HTTP 422).
_PUB_PAGE_SIZE = 200
_PUB_DELAY = float(os.getenv("TE_PUB_DELAY", "0.3") or "0.3")
_PUB_RETRY_S = float(os.getenv("TE_PUB_RETRY_S", "2") or "2")

# ⭐ O VOCABULARIO DA SITUACAO DO PLANO DE TRABALHO MUDOU COM A FONTE, e traduzir
# nao e preciosismo: e o que impede o RM de perder plano em silencio.
#
# `services/rm_builder` decide o ESTAGIO do item procurando SUBSTRING no texto:
#
#     sit_efetivo = sit_trab if any(x in sit_trab.lower()
#                    for x in ("empenh", "pag", "conclu", "finaliz", "execu"))
#                   else sit
#
# O rotulo novo "Legado ADPF 854 STF / NT - TCU" nao contem nenhuma delas, onde o
# codigo antigo "CONCLUIDO_NT_TCU" continha "conclu". Gravar o rotulo cru faria o
# plano cair para a situacao do PLANO DE ACAO (quase sempre "CIENTE" = ativa), e
# `_fed_retem` DESCARTA ativa de ano anterior ao do relatorio: o plano sumiria do
# RM sem erro nenhum em log. E o mesmo tipo de falha muda que o proprio
# rm_builder documenta no comentario do `row[8]`.
#
# O rm_builder tambem faz `sit_trab.replace("_", " ")` antes de exibir, ou seja,
# ele ja espera o codigo. Traduzimos aqui, no unico lugar que conhece as duas
# fontes, e nada mais no produto precisa saber que a origem mudou.
#
# Mapa conferido PAR A PAR em 06/09/2026 — 19 planos, mesmo `id_plano_acao` nas
# duas APIs, 19/19 batendo. Nao e deducao de nome parecido.
_SITUACAO_PT_PARA_CODIGO = {
    "legado adpf 854 stf / nt - tcu": "CONCLUIDO_NT_TCU",
    "aprovado": "APROVADO",
    "reprovado": "REPROVADO",
    "enviado para analise": "ENVIADO_PARA_ANALISE",
    "em complementacao": "EM_COMPLEMENTACAO",
    "em elaboracao": "EM_ELABORACAO",
}


def _situacao_pt_normalizada(rotulo: str | None) -> str | None:
    """Rotulo da API oficial -> codigo que o RM e a tela ja entendem.

    ⚠️ DESCONHECIDO NAO VIRA VAZIO. Situacao nova que o MGI crie amanha cai no
    `else` e sai como SCREAMING_SNAKE do proprio rotulo ("Em Diligencia" ->
    "EM_DILIGENCIA"): o RM continua tendo o que exibir e o que classificar, e o
    valor aparece no banco pedindo uma linha nova no mapa. Devolver None ou ""
    esconderia a novidade — e o campo simplesmente sumiria da tela.
    """
    if not rotulo:
        return None
    chave = _norm(rotulo).lower()
    mapeado = _SITUACAO_PT_PARA_CODIGO.get(chave)
    if mapeado:
        return mapeado
    return "_".join(_norm(rotulo).split()).replace("/", "_").strip("_") or None

# ---------------------------------------------------------------------------
# PAGAMENTOS PELA SPA — RESERVA desde 14/09/2026
# ---------------------------------------------------------------------------
# ⚠️ O CAMINHO PRINCIPAL AGORA E `pagamentos_da_arvore` (API oficial, mesmo
# formato). O que segue continua servindo a dois usos: `_API_OPOB` alimenta a
# fase 3 (`run_reserva_spa`, CPF e historico da OP), e `pagamentos_do_plano`/
# `run_pagamentos` voltam a ser o caminho inteiro com `TE_PGTO_FONTE=spa`.
#
# Endpoints PUBLICOS da MESMA base, descobertos no bundle da SPA de especiais
# (main.js: getPublicUrlDocumentoHabil / getPublicUrlOpob; chunk 527 = tela
# dados-orcamentarios, chunk 32 = tela detalhar-ordem-pagamento):
#
#   GET /public/documentos-habeis/plano-acao/resumido/{planoAcaoId}
#     -> [{id, numeroEmpenho, nuInternoDh, nuDh, vlDh, descricaoSituacao,
#          opObId, txOp}]  — e a grade "Lista de Documentos Habeis", coluna a coluna.
#   GET /public/opob/{opObId}
#     -> {txOp, txOb, situacao, dtEmissaoOb, dtPagamento, dtAssinaturaOrdDesp,
#         dtAssinaturaGestFin, txCpfOrdenadorDespesa, txCpfGestorFinanceiro,
#         historico:[{dhRegistro, txCpfResponsavel, situacao}]}
#
# ⚠️ NAO USE /public/opob/plano-acao/{id}. Ele existe e responde 200 com a lista
# de OPs do plano, mas com `historico` VAZIO e `situacao` NULA — medido no plano
# 91573. O historico de eventos de pagamento so vem no detalhe por opObId.
#
# ⚠️ CUSTO MEDIDO (23/08/2026, 590 requisicoes SEQUENCIAIS, ZERO 403): ~0,22s no
# endpoint de DH e ~0,32s no de OPOB. O rate-limit brutal desta API e da
# /plano-acao/listagem (paginas de 5 MB), NAO destes lookups por id. Sao 1 + N
# requisicoes por plano (N = DHs com OP; medido: 0 DH em 30% dos planos, 1 em
# 64%, maximo 3). No maior tenant (~60 planos na carteira) da ~120 requisicoes,
# ~100s por rodada diaria — sem navegador, sem concorrencia, uma conexao so.
#
# ⚠️ 403 NAO SIGNIFICA A MESMA COISA NOS DOIS: o de DH devolve `[]` com HTTP 200
# para plano inexistente, enquanto /opob/{id} devolve **403** (nao 404) para
# opObId inexistente. Ler esse 403 como rate-limit poria o coletor em backoff
# por causa de um id que simplesmente nao existe.
_API_DH = ("https://especiais.transferegov.sistema.gov.br/"
           "maisbrasil-transferencia-especial-backend/api/public/documentos-habeis"
           "/plano-acao/resumido/{pid}")
_API_OPOB = ("https://especiais.transferegov.sistema.gov.br/"
             "maisbrasil-transferencia-especial-backend/api/public/opob/{oid}")
_PGTO_ON = (os.getenv("TE_PAGAMENTOS", "1") or "1").strip() == "1"
# De onde saem os PAGAMENTOS: `oficial` (padrao desde 14/09/2026, da arvore do
# plano) ou `spa` (o caminho antigo, `run_pagamentos`, mantido como reserva
# completa para o dia em que a API oficial falhar).
_PGTO_FONTE = (os.getenv("TE_PGTO_FONTE", "oficial") or "oficial").strip().lower()
_PGTO_DELAY = float(os.getenv("TE_PGTO_DELAY", "0.5") or "0.5")
_PGTO_BUDGET_S = float(os.getenv("TE_PGTO_BUDGET_S", "300") or "300")
_PGTO_MAX_AGE_DAYS = int(os.getenv("TE_PGTO_MAX_AGE_DAYS", "3") or "3")
# ⚠️ TETO DA TAREFA INTEIRA, e nao de uma fase dela. A Scheduled Task mata o
# processo em `timeout -k 30 N` (ver a docstring de `run`), e estourar isso
# degola a rodada no meio e perde o log final — que e onde o resultado aparece.
# Por isso `run()` CRONOMETRA cada fase e passa o RESTO a seguinte, nunca o
# orcamento cheio.
#
# ⚠️ O DEFAULT CONTINUA 1450, casado com o `timeout -k 30 1600` que as tasks
# tinham ate 14/09/2026. Quem sobe o kill da task sobe ESTE teto no MESMO
# comando (`TE_TETO_TAREFA_S=3150 ... timeout -k 30 3300`): assim o codigo nunca
# pede mais tempo do que a task que o roda concede, seja qual for a ordem em
# que deploy e mudanca no Coolify acontecem.
_TETO_TAREFA_S = float(os.getenv("TE_TETO_TAREFA_S", "1450") or "1450")
# Teto da LISTAGEM. Ela leva ~140s no maior tenant (Freitas, 405 planos, medido
# em 14/09/2026); 900 e folga para fonte lenta, nao previsao.
_BUDGET_S = float(os.getenv("TE_BUDGET_S", "900") or "900")
# Fatia minima reservada a ARVORE antes da listagem comecar, e a fatia da
# reserva na SPA (fase 3) — ver `run`.
_DET_MIN_S = float(os.getenv("TE_DET_MIN_S", "300") or "300")
_SPA_BUDGET_S = float(os.getenv("TE_SPA_BUDGET_S", "120") or "120")
# Plano cuja arvore foi colhida ha menos disto nao volta a fila. 20h, e nao 24:
# a task diaria nao pode achar "fresco" o plano que ela mesma colheu ontem uns
# minutos mais tarde.
_DET_MAX_AGE_H = float(os.getenv("TE_DET_MAX_AGE_H", "20") or "20")


def _norm(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper())
                   if not unicodedata.combining(c)).strip()


def _sync_url() -> str:
    u = os.getenv("DATABASE_URL_SYNC", "") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    return u.replace("&channel_binding=require", "").replace("?channel_binding=require", "")


def _log_ingestao(status: str, n: int, erro: str | None = None) -> None:
    """Registra a rodada em `ingestion_log` (source 'transferegov_te').

    Conexao PROPRIA, e engolindo excecao: este coletor commita pagina a pagina e
    a conexao do run pode ja ter morrido quando chegamos aqui. Falhar ao gravar
    o log nao pode desfazer coleta que deu certo. Mesmo padrao do sismob_obras.
    """
    try:
        cn = psycopg2.connect(_sync_url())
        cur = cn.cursor()
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, error_message, finished_at) "
            "VALUES ('transferegov_te', %s, %s, %s, NOW())",
            (status, n, (erro[:500] if erro else None)),
        )
        cn.commit(); cur.close(); cn.close()
    except Exception as e:
        logger.warning(f"ingestion_log falhou: {str(e)[:120]}")


def _casa_municipio(ben_norm: str, pares: list[tuple[str, int]]) -> int | None:
    """Beneficiario CONTEM o nome do municipio (ex.: 'MUNICIPIO DE NOVA SERRANA').

    ⚠️ REGRA DEFEITUOSA, MANTIDA POR UM SO CHAMADOR: 'SERRANA' casa dentro de
    'NOVA SERRANA', e foi assim que 628 de 890 linhas do tenant trust acabaram
    com o CNPJ de um municipio e o `municipio_id` de outro. A LISTAGEM nao usa
    mais isto — ela entra por CNPJ (`_beneficiario_do_cnpj`).

    Quem ainda chama e `routers/control.py::control_te_lote`, a coleta assistida
    por IP externo: ela recebe planos JA no formato da SPA, sem id de
    beneficiario resolvido, e nao tem por onde entrar a nao ser pelo nome. Se
    aquele endpoint for aposentado — a razao de existir dele era o bloqueio de
    IP, que a API oficial nao tem — esta funcao vai junto.
    """
    for nome_norm, mid in pares:
        if nome_norm and (nome_norm in ben_norm or ben_norm.endswith(nome_norm)):
            return mid
    return None


async def _pub_pagina(cli: httpx.AsyncClient, caminho: str, params: dict,
                      pagina: int = 1) -> dict | None:
    """UMA pagina da API publica oficial. None se a fonte nao respondeu 200.

    ⚠️ SEM BACKOFF DE RATE-LIMIT, e de proposito. Esta API nao pune martelada
    (10 requisicoes seguidas, todas 200, medido em 06/09/2026) — o backoff de
    `_fetch_page` existe para a API da SPA, que e outra coisa. Inventar espera
    aqui so faria a rodada demorar.

    ⚠️ HTTP 500 EM FILTRO VALIDO EXISTE E E DA FONTE: o modulo `/fundoafundo`
    devolve 500 para um filtro documentado (`codigo_ibge_..._recebedor`). Nao vi
    isso em `/especiais`, mas por isso o erro aqui e LOGADO com a URL e o
    parametro — se aparecer, o log diz qual filtro derrubou.

    ⚠️ UMA RETENTATIVA, e so para erro de rede ou 5xx — nao e backoff de
    rate-limit (429 nao repete). Em 13/09/2026 a Freitas perdeu um municipio
    inteiro por uma falha transitoria; com a arvore do plano sao ~20 consultas
    por plano, e sem isto um soluco da fonte jogaria fora o plano todo.
    """
    p = {**params, "pagina": pagina, "tamanho_da_pagina": _PUB_PAGE_SIZE}
    r = None
    for tentativa in (1, 2):
        try:
            r = await cli.get(f"{_API_PUB}/{caminho}", params=p, timeout=60)
        except Exception as e:
            logger.warning(f"  API oficial {caminho} (tentativa {tentativa}): {str(e)[:100]}")
            r = None
        if r is not None and r.status_code < 500:
            break
        if tentativa == 1:
            await asyncio.sleep(_PUB_RETRY_S)
    if r is None:
        return None
    if r.status_code != 200:
        logger.warning(f"  API oficial {caminho} {p}: HTTP {r.status_code}")
        return None
    try:
        return r.json()
    except ValueError:
        logger.warning(f"  API oficial {caminho}: resposta nao e JSON")
        return None


async def _pub_todos(cli: httpx.AsyncClient, caminho: str, params: dict,
                     teto_itens: int | None = None,
                     exigir_completo: bool = False) -> list[dict] | None:
    """Todas as paginas de uma consulta. None quando a PRIMEIRA pagina falhou.

    `exigir_completo`: None tambem quando uma pagina DO MEIO falhar. A listagem
    aceita o que veio (o upsert e por plano, e o resto entra amanha); a arvore do
    plano nao pode — um extrato com a segunda pagina faltando seria gravado como
    se fosse o extrato inteiro.

    A distincao importa: lista vazia e "a fonte respondeu e nao ha nada" (estado
    legitimo — municipio sem emenda especial), enquanto None e "nao consegui
    perguntar". Quem chama usa isso para nao gravar silencio como ausencia.

    ⚠️ `teto_itens` E A GUARDA CONTRA FILTRO IGNORADO. A fonte ignora EM
    SILENCIO todo parametro que nao reconhece: medido em 07/09/2026, um
    `?parametro_inexistente=x` devolve HTTP 200 com a base nacional inteira,
    identico a nao filtrar. Os filtros usados aqui funcionam hoje (conferidos
    com valor impossivel, que devolve 0 e nao tudo), mas o Obras.gov ja
    renomeou TODOS os campos numa troca de host: se acontecer aqui, sem esta
    guarda a rodada gravaria 57.827 planos do Brasil como sendo do municipio.
    Acima do teto devolvemos None, que quem chama ja trata como "nao consegui
    perguntar" — e nao como ausencia.
    """
    d = await _pub_pagina(cli, caminho, params, 1)
    if d is None:
        return None
    if teto_itens is not None:
        total_itens = int(d.get("total_items") or 0)
        if total_itens > teto_itens:
            logger.error(f"  {caminho} {params}: {total_itens} itens para um teto "
                         f"de {teto_itens} — o filtro nao foi aplicado. NAO "
                         f"gravando: seria carga nacional.")
            return None
    itens = list(d.get("data") or [])
    total_paginas = int(d.get("total_pages") or 1)
    for pag in range(2, total_paginas + 1):
        await asyncio.sleep(_PUB_DELAY)
        d = await _pub_pagina(cli, caminho, params, pag)
        if d is None:
            logger.warning(f"  {caminho}: parou na pagina {pag}/{total_paginas}")
            if exigir_completo:
                return None
            break
        itens.extend(d.get("data") or [])
    return itens


async def _beneficiario_do_cnpj(cli: httpx.AsyncClient, cnpj: str) -> dict | None:
    """CNPJ do municipio -> registro de beneficiario da API oficial (ou None).

    ⭐ ESTA E A TROCA QUE JUSTIFICA A FASE INTEIRA. O caminho antigo casava o
    plano ao municipio por SUBSTRING DE NOME ('MUNICIPIO DE NOVA SERRANA' contem
    'SERRANA'), e a contaminacao ja estava medida: 628 de 890 linhas com CNPJ
    divergente num tenant. Aqui a chave e o CNPJ, e o `id_beneficiario` que ele
    devolve e o que filtra os planos — nao ha como um plano de outro municipio
    entrar.

    ⚠️ CNPJ E UNICO POR BENEFICIARIO na fonte: 200 beneficiarios do RS, 200 CNPJs
    distintos, zero vazios (medido em 06/09/2026). Se um dia deixar de ser, o
    `total_items > 1` aparece no log em vez de escolher um em silencio.
    """
    so_digitos = "".join(c for c in (cnpj or "") if c.isdigit())
    if len(so_digitos) != 14:
        return None
    itens = await _pub_todos(cli, "beneficiarios-especiais",
                             {"cnpj_beneficiario": so_digitos},
                             teto_itens=50)
    if not itens:
        return None
    if len(itens) > 1:
        logger.warning(f"  CNPJ {so_digitos}: {len(itens)} beneficiarios na fonte "
                       f"(esperado 1) — usando o primeiro, ids "
                       f"{[i.get('id_beneficiario') for i in itens]}")
    return itens[0]


def plano_novo_para_linha(plano: dict, ben: dict, situacao_pt: str | None,
                          mid: int | None) -> dict | None:
    """Traduz UM plano da API PUBLICA OFICIAL para as colunas de transferegov_te.

    Funcao PURA e testavel: recebe o plano, o beneficiario ja resolvido e a
    situacao do plano de trabalho ja normalizada, e devolve exatamente as
    colunas que `UPSERT_SQL_NOMEADO` grava — as MESMAS que o caminho antigo
    gravava, para o RM e a tela nao notarem a troca de fonte.

    ⚠️ TRES CAMPOS SAO DERIVADOS, e cada derivacao foi conferida contra a fonte
    antiga antes de entrar aqui:

    `valor_total` — a API oficial NAO tem o campo; ela manda custeio e
      investimento separados. A soma bate com o `valorTotal` da SPA em 800 de
      800 planos conferidos (06/09/2026).

    `programa_codigo` — `/programas-especiais` tem `codigo_programa`, mas ele
      PERDE O ZERO A ESQUERDA ('903' onde a SPA mandava '0903'), porque a fonte
      trata como numero. O `codigo_plano_acao` carrega o codigo do programa
      intacto antes do ultimo hifen ('0903-003200' -> '0903';
      '09032024-2-069722' -> '09032024-2'): 800 de 800 conferindo, e sem gastar
      uma requisicao por programa.

    `parlamentar` — o caminho antigo partia o codigo da emenda no primeiro '-'.
      A API oficial tem `nome_parlamentar_emenda_plano_acao` DIRETO; usamos ele
      e caimos no split so se vier vazio.
    """
    pid = plano.get("id_plano_acao")
    if pid is None:
        return None
    codigo = plano.get("codigo_plano_acao") or ""
    emenda = plano.get("codigo_emenda_parlamentar_formatado_plano_acao") or ""
    custeio = float(plano.get("valor_custeio_plano_acao") or 0)
    investimento = float(plano.get("valor_investimento_plano_acao") or 0)
    parlamentar = (plano.get("nome_parlamentar_emenda_plano_acao") or "").strip()
    if not parlamentar and "-" in emenda:
        parlamentar = emenda.split("-", 1)[1].strip()
    return {
        "plano_acao_id": int(pid),
        "municipio_id": mid,
        "uf": ben.get("uf_beneficiario"),
        "codigo": codigo or None,
        "emenda": emenda or None,
        "parlamentar": parlamentar or None,
        # `nome_objeto` e o titulo ('Pavimentação') e `detalhamento_objeto` o
        # texto livre; a SPA mandava os dois juntos e com mojibake. Preferimos o
        # detalhamento quando ele acrescenta algo.
        "objeto": (plano.get("detalhamento_objeto")
                   or plano.get("nome_objeto")
                   or plano.get("codigo_descricao_areas_politicas_publicas_plano_acao")),
        "situacao": plano.get("situacao_plano_acao"),
        "situacao_trabalho": situacao_pt,
        "valor_total": round(custeio + investimento, 2),
        "valor_investimento": investimento,
        "valor_custeio": custeio,
        "beneficiario_nome": ben.get("nome_beneficiario"),
        "beneficiario_cnpj": ben.get("cnpj_beneficiario"),
        "programa_codigo": (codigo.rsplit("-", 1)[0] if "-" in codigo else None),
        # ⚠️ RAW DA FONTE NOVA, e nao uma traducao para o formato antigo. Quem le
        # `raw_data` (routers/transferegov.buscar) foi ajustado no mesmo commit
        # para as chaves novas. Gravar camelCase sintetico aqui criaria uma
        # traducao dupla que ninguem mais conseguiria justificar depois.
        "raw_data": json.dumps({**plano,
                                "_beneficiario": ben,
                                "_situacao_plano_trabalho": situacao_pt},
                               ensure_ascii=False),
    }


def plano_para_linha(it: dict, mid: int | None) -> dict | None:
    """Traduz UM plano da API 'especiais' (SPA) para as colunas de transferegov_te.

    ⚠️ CAMINHO DA COLETA ASSISTIDA, e nao mais o do cron. A listagem diaria vem
    da API publica oficial por `plano_novo_para_linha` (acima). Esta funcao
    continua viva porque `routers/control.py::control_te_lote` recebe planos no
    formato da SPA de um IP externo — e continua sendo o mesmo upsert.

    Funcao PURA e importavel de fora: o mapeamento de campos vive num lugar so,
    usado pelo coletor (psycopg2, abaixo) e pela coleta assistida do
    control-plane (`routers/control.py::control_te_lote`, SQLAlchemy). Se um
    campo mudar de nome na API, muda AQUI e os dois caminhos acompanham.
    """
    pid = it.get("planoAcaoId")
    if pid is None:
        return None
    emenda = it.get("codigoEmendaFormatado") or ""
    return {
        "plano_acao_id": int(pid),
        "municipio_id": mid,
        "uf": it.get("uf"),
        "codigo": it.get("planoAcaoCodigo"),
        "emenda": it.get("codigoEmendaFormatado"),
        # parlamentar = parte apos o '-' do codigo da emenda (ex.: '...-DIMAS FABIANO')
        "parlamentar": emenda.split("-", 1)[1].strip() if "-" in emenda else None,
        "objeto": it.get("objetoDescricao") or it.get("politicasPublicas"),
        "situacao": it.get("planoAcaoSituacao"),
        "situacao_trabalho": it.get("planoTrabalhoSituacao"),
        "valor_total": float(it.get("valorTotal") or 0),
        "valor_investimento": float(it.get("valorInvestimento") or 0),
        "valor_custeio": float(it.get("valorCusteio") or 0),
        "beneficiario_nome": it.get("beneficiarioNome"),
        "beneficiario_cnpj": it.get("beneficiarioCnpj"),
        "programa_codigo": it.get("programaCodigo"),
        "raw_data": json.dumps(it, ensure_ascii=False),
    }


# A clausula compartilhada dos dois caminhos de escrita (coletor e control):
# um so texto SQL, com placeholders nomeados; quem chama escolhe o driver.
UPSERT_SQL_NOMEADO = """INSERT INTO transferegov_te
     (plano_acao_id, municipio_id, uf, codigo, emenda, parlamentar, objeto,
      situacao, situacao_trabalho, valor_total, valor_investimento, valor_custeio,
      beneficiario_nome, beneficiario_cnpj, programa_codigo, raw_data, updated_at)
   VALUES (:plano_acao_id, :municipio_id, :uf, :codigo, :emenda, :parlamentar,
           :objeto, :situacao, :situacao_trabalho, :valor_total,
           :valor_investimento, :valor_custeio, :beneficiario_nome,
           :beneficiario_cnpj, :programa_codigo, CAST(:raw_data AS jsonb), NOW())
   ON CONFLICT (plano_acao_id) DO UPDATE SET
     municipio_id=EXCLUDED.municipio_id, uf=EXCLUDED.uf, codigo=EXCLUDED.codigo,
     emenda=EXCLUDED.emenda, parlamentar=EXCLUDED.parlamentar, objeto=EXCLUDED.objeto,
     situacao=EXCLUDED.situacao, situacao_trabalho=EXCLUDED.situacao_trabalho,
     valor_total=EXCLUDED.valor_total, valor_investimento=EXCLUDED.valor_investimento,
     valor_custeio=EXCLUDED.valor_custeio, beneficiario_nome=EXCLUDED.beneficiario_nome,
     beneficiario_cnpj=EXCLUDED.beneficiario_cnpj, programa_codigo=EXCLUDED.programa_codigo,
     raw_data=EXCLUDED.raw_data, updated_at=NOW()"""


def _grava_linha(cur, linha: dict) -> None:
    """Executa o upsert compartilhado com uma linha JA traduzida (psycopg2).

    Os dois tradutores (`plano_novo_para_linha`, da API oficial, e
    `plano_para_linha`, da SPA) desembocam aqui: um SQL so, um ON CONFLICT so.
    """
    # psycopg2 usa %(nome)s; o texto nomeado usa :nome. Regex de UMA passada —
    # replace por nome corromperia prefixos (":situacao" dentro de
    # ":situacao_trabalho").
    import re as _re
    sql = UPSERT_SQL_NOMEADO.replace("CAST(:raw_data AS jsonb)", "%(raw_data)s")
    sql = _re.sub(r":(\w+)", r"%(\1)s", sql)
    cur.execute(sql, linha)


def _upsert(cur, it: dict, mid: int | None):
    linha = plano_para_linha(it, mid)
    if linha is None:
        return
    _grava_linha(cur, linha)


def _municipios_da_carteira(cur) -> list[dict]:
    """Municipios ATIVOS do tenant: id, nome, uf e CNPJ.

    O CNPJ vem de `municipios.cnpj`, que o `ingestion/siconfi.py` preenche
    sozinho a partir do cadastro do Tesouro — a docstring de la ja dizia, desde
    antes desta migracao, que "a Transferencia Especial casa por CNPJ".

    ⚠️ `WHERE active`, e a falta dele custou caro na primeira rodada em producao
    (07/09/2026, freitas): dos 60 municipios, 18 estao INATIVOS — e sao
    exatamente os 18 sem CNPJ, porque o `siconfi` tambem filtra por `active` e
    nunca os visitou. Sem esta clausula o coletor: (1) gastava requisicao com
    municipio que o cliente nao acompanha mais, (2) gravava linha para ele, e
    (3) pior, caia no fallback por nome em todos os 18 — e cada queda baixa a
    lista de beneficiarios da UF INTEIRA. Dezoito varreduras de Minas Gerais
    para preencher municipio que ninguem le.

    E o padrao do repo, nao invencao: `obrasgov`, `portal_transparencia`,
    `che_rs`, `cofin_ses_go`, `consulta_popular_rs` e `cagec_scraper` todos
    filtram `active`.
    """
    cur.execute("SELECT id, nome, upper(coalesce(uf, '')), "
                "       coalesce(regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g'), '') "
                "  FROM municipios WHERE active ORDER BY nome")
    return [{"id": r[0], "nome": r[1], "uf": r[2], "cnpj": r[3]}
            for r in cur.fetchall()]


async def _beneficiario_por_nome(cli: httpx.AsyncClient, mun: dict,
                                 cache_uf: dict[str, list[dict]]) -> dict | None:
    """FALLBACK para municipio sem CNPJ cadastrado: acha o beneficiario na UF.

    ⚠️ AINDA E CASAMENTO POR NOME, com todos os defeitos que esta fase existe
    para matar — mas num universo MUITO menor e sem consequencia sobre o dado
    dos outros: a lista de beneficiarios de uma UF tem centenas de linhas (498
    no RS), nao milhares de planos, e o que se escolhe aqui e UM beneficiario,
    nao um plano. Sem CNPJ, a alternativa seria nao coletar o municipio.

    Exige nome EXATO (normalizado) ou 'MUNICIPIO DE <nome>' — nada de substring,
    que e o que fazia 'SERRANA' capturar 'NOVA SERRANA'.

    ⚠️ A LISTA DA UF E BAIXADA UMA VEZ SO POR RODADA (`cache_uf`). Sem isso, cada
    municipio sem CNPJ repetia a varredura inteira do estado: na primeira rodada
    em producao foram 18 quedas no fallback num tenant de Minas, ou seja, 18
    downloads da mesma lista. O `WHERE active` de `_municipios_da_carteira`
    resolveu a causa daquele caso, mas o fallback continua existindo para
    municipio ativo cujo CNPJ ainda nao foi preenchido — e ai o cache e o que
    impede o custo de voltar.
    """
    uf = mun["uf"]
    if not uf:
        return None
    if uf not in cache_uf:
        cache_uf[uf] = await _pub_todos(cli, "beneficiarios-especiais",
                                        {"uf_beneficiario": uf}) or []
        logger.info(f"  fallback por nome: {len(cache_uf[uf])} beneficiario(s) de {uf} "
                    f"em cache para esta rodada")
    alvo = _norm(mun["nome"])
    for b in cache_uf[uf]:
        nome = _norm(b.get("nome_beneficiario") or "")
        if nome == alvo or nome == f"MUNICIPIO DE {alvo}":
            return b
    return None


async def run_municipios(budget_s: float | None = None,
                         registrar: bool = True) -> dict:
    """LISTAGEM pela API publica oficial, municipio a municipio.

    `registrar=False`: devolve o status em `status`/`erro` em vez de gravar a
    linha do `ingestion_log`. E o que `run()` usa — ele grava UMA linha no fim,
    somando a arvore, porque uma segunda linha por dia mudaria o que a tela
    Status dos Dados le como "ultima coleta".

    Sem paginacao de UF inteira e sem casamento por nome: para cada municipio da
    carteira sao 2 requisicoes (beneficiario pelo CNPJ + planos pelo
    id_beneficiario) mais 1 por plano para a situacao do plano de trabalho, que
    e o unico campo do retrato antigo que nao vem junto com o plano.

    ⚠️ NAO E INCREMENTAL POR PAGINA, e nao precisa ser. A retomada por
    `start_page` existia porque a fonte antiga bloqueava no meio da varredura de
    um estado; aqui cada municipio custa poucos segundos e a rodada inteira cabe
    folgada no orcamento. Se o tempo acabar, o que ficou de fora entra na
    proxima — municipio inteiro, nunca pela metade.
    """
    budget = _BUDGET_S if budget_s is None else budget_s
    cn = psycopg2.connect(_sync_url())
    cn.autocommit = False
    cur = cn.cursor()
    municipios = _municipios_da_carteira(cur)
    so_um = (os.getenv("TE_MUNICIPIO") or "").strip()
    if so_um.isdigit():
        municipios = [m for m in municipios if m["id"] == int(so_um)]
    if not municipios:
        msg = "nenhum municipio na carteira deste tenant"
        logger.error(f"TE: {msg}")
        if registrar:
            _log_ingestao("error", 0, msg)
        cur.close(); cn.close()
        return {"municipios": 0, "gravados": 0, "completo": False,
                "status": "error", "erro": msg}

    t0 = time.time()
    gravados = com_plano = sem_cnpj = sem_beneficiario = falhas = 0
    atendidos = 0
    completo = True
    # Lista de beneficiarios por UF, baixada no maximo uma vez por rodada e so
    # se algum municipio cair no fallback por nome. Ver `_beneficiario_por_nome`.
    cache_uf: dict[str, list[dict]] = {}
    logger.info(f"TE: {len(municipios)} municipio(s) na carteira "
                f"(orcamento {budget:.0f}s) — fonte: API publica oficial")
    async with httpx.AsyncClient(timeout=60) as cli:
        for mun in municipios:
            if (time.time() - t0) >= budget:
                completo = False
                logger.warning(f"TE: orcamento estourado apos {atendidos} municipio(s); "
                               f"o resto entra na proxima rodada")
                break
            ben = None
            if len(mun["cnpj"]) == 14:
                ben = await _beneficiario_do_cnpj(cli, mun["cnpj"])
            else:
                sem_cnpj += 1
                logger.warning(f"  {mun['nome']}/{mun['uf']}: sem CNPJ em municipios.cnpj "
                               f"— caindo no casamento por nome (rode o siconfi)")
                ben = await _beneficiario_por_nome(cli, mun, cache_uf)
            atendidos += 1
            if not ben:
                # ⚠️ ESTADO LEGITIMO, e nao erro: municipio que nunca recebeu
                # emenda especial simplesmente nao esta na fonte. Contamos para
                # o log final poder distinguir "todos sem beneficiario" (que ai
                # sim cheira a defeito) de "alguns".
                sem_beneficiario += 1
                continue
            planos = await _pub_todos(cli, "planos-acao-especiais",
                                      {"id_beneficiario": ben.get("id_beneficiario")},
                                      teto_itens=2000)
            if planos is None:
                falhas += 1
                logger.warning(f"  {mun['nome']}/{mun['uf']}: fonte nao respondeu os planos")
                continue
            if planos:
                com_plano += 1
            for plano in planos:
                await asyncio.sleep(_PUB_DELAY)
                pts = await _pub_todos(cli, "planos-trabalho-especiais",
                                       {"id_plano_acao": plano.get("id_plano_acao")})
                # Lista vazia = plano sem plano de trabalho (11 de 800 na fonte
                # antiga tambem vinham sem). None = nao consegui perguntar; nos
                # dois casos a coluna fica NULA, como ficava antes.
                rotulo = (pts[0].get("situacao_plano_trabalho") if pts else None)
                linha = plano_novo_para_linha(
                    plano, ben, _situacao_pt_normalizada(rotulo), mun["id"])
                if linha is None:
                    continue
                _grava_linha(cur, linha)
                gravados += 1
            cn.commit()   # municipio a municipio: progresso persiste
            logger.info(f"  {mun['nome']}/{mun['uf']}: {len(planos)} plano(s) "
                        f"(beneficiario {ben.get('id_beneficiario')})")
    cur.close(); cn.close()
    dur = time.time() - t0
    logger.info(f"TE: FIM — {atendidos} municipio(s), {com_plano} com plano, "
                f"{gravados} plano(s) gravado(s), {sem_beneficiario} sem beneficiario, "
                f"{falhas} falha(s) em {dur:.0f}s")

    # ⭐ O QUE E ERRO AQUI MUDOU COM A FONTE. No caminho antigo, `casados`=0 podia
    # ser normal (pagina de MG sem plano do municipio). Aqui cada consulta ja
    # nasce filtrada pelo beneficiario do municipio: nao existe plano coletado
    # que nao seja da carteira, e `municipio_id` nunca e nulo. Entao o alarme
    # certo e outro — a fonte parar de responder, ou a carteira inteira ficar
    # sem beneficiario (que so acontece se o CNPJ estiver errado em todos).
    if falhas and not gravados:
        status, erro = "error", "a fonte nao respondeu a nenhum municipio"
    elif atendidos and sem_beneficiario == atendidos:
        status, erro = "error", (f"nenhum dos {atendidos} municipios tem beneficiario "
                                 f"na fonte — CNPJ errado ou fonte mudou")
    elif not completo or falhas:
        status, erro = "partial", (
            f"{falhas} municipio(s) sem resposta; retoma na proxima rodada"
            if falhas else "orcamento estourado; retoma na proxima rodada")
    else:
        status, erro = "success", None
    if registrar:
        _log_ingestao(status, gravados if status != "error" else 0, erro)
    return {"municipios": atendidos, "gravados": gravados, "com_plano": com_plano,
            "sem_cnpj": sem_cnpj, "sem_beneficiario": sem_beneficiario,
            "falhas": falhas, "completo": completo, "status": status, "erro": erro}


def _teto_listagem_s(budget: float, teto_tarefa: float, pgto: float) -> float:
    """Quanto tempo a LISTAGEM pode tomar, reservando a fatia dos pagamentos.

    ⚠️ FUNCAO, e nao uma conta solta dentro de `run()`. Ela nasceu de um defeito
    real (ver `run`) e e coberta por teste; enquanto a formula vivia inline, o
    teste tinha de RECOPIA-LA — e um teste que reimplementa o codigo nao percebe
    quando o codigo muda.
    """
    return max(60.0, min(budget, teto_tarefa - pgto))


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dt_br(s) -> str:
    """'2026-06-22' (ou '2026-06-22T08:56:37') -> '22/06/2026'. '' quando nao da.

    dd/mm/aaaa DE PROPOSITO: e o formato que o `ops_obs` das voluntarias grava, e
    o RM le as duas fontes com as MESMAS funcoes (services/rm_builder
    _desembolso_ops_obs e _ano_pagamento_ops_obs). Formato diferente aqui obrigaria
    um segundo parser no builder e as duas acabariam divergindo."""
    t = str(s or "")[:10]
    if len(t) == 10 and t[4] == "-" and t[7] == "-":
        return f"{t[8:10]}/{t[5:7]}/{t[0:4]}"
    return ""


def _dh_br(s) -> str:
    """'2026-06-22T08:56:37.75667' -> '22/06/2026 08:56' (evento do historico)."""
    t = str(s or "")
    d = _dt_br(t)
    return f"{d} {t[11:16]}".strip() if d else t[:16]


def _chave_data(d: str) -> str:
    """dd/mm/aaaa -> aaaammdd, p/ comparar datas como texto sem parsear."""
    p = str(d or "").split("/")
    return (p[2] + p[1] + p[0]) if len(p) == 3 else ""


async def pagamentos_do_plano(cli: httpx.AsyncClient, plano_acao_id: int,
                              valor_total) -> dict | None:
    """Pagamentos de UM plano de acao, no MESMO formato do `ops_obs` das voluntarias.

    REGRA DO QUE CONTA COMO DESEMBOLSADO: documento habil com Ordem de Pagamento
    (opObId > 0) cuja OPOB ja tem ORDEM BANCARIA (`txOb` preenchido).

    ⚠️ MINUTA NAO E DINHEIRO — o mesmo cuidado que `_nes_resumo` ja teve de tomar
    no RM. A grade da tela mistura o DH emitido ("Enviado", com `nuDh`) com a
    MINUTA de DH ("Minuta de DH", `nuDh` nulo e `opObId` 0). No plano 91573 sao
    R$ 205.066,16 emitidos e R$ 192.933,84 ainda em minuta: somar a minuta como
    pago inventaria repasse e mandaria o item para a Parte 3 sem que um centavo
    tivesse saido. A minuta vai para `pendentes` e o valor dela fica no a-desembolsar.

    ⚠️ `dtPagamento` VEM SEMPRE NULO nesta API publica (medido em 90 OPs de 4
    faixas de ano). Quem marca a saida do dinheiro e `txOb`/`dtEmissaoOb`.

    None quando a fonte nao respondeu — e NULO no banco significa "nao medido",
    que e o que impede o RM de escrever PENDENTE DE DESEMBOLSO sem ter medido.
    """
    try:
        r = await cli.get(_API_DH.format(pid=plano_acao_id), headers=_HEADERS)
    except Exception as e:
        logger.warning(f"  pgto {plano_acao_id}: DH {str(e)[:80]}")
        return None
    if r.status_code != 200:
        logger.warning(f"  pgto {plano_acao_id}: DH HTTP {r.status_code}")
        return None
    try:
        lista = r.json() or []
    except ValueError:
        return None
    if not isinstance(lista, list):
        return None

    pagos: list[dict] = []
    pendentes: list[dict] = []
    datas: list[str] = []
    total_pago = 0.0
    for dh in lista:
        if not isinstance(dh, dict):
            continue
        vl = _num(dh.get("vlDh"))
        base = {
            "dh_id": dh.get("id"),
            "numero_dh": (dh.get("nuDh") or ""),
            "minuta": (dh.get("nuInternoDh") or ""),
            "numero_empenho": (dh.get("numeroEmpenho") or ""),
            "valor": vl,
            "situacao_dh": (dh.get("descricaoSituacao") or ""),
        }
        oid = dh.get("opObId") or 0
        if not oid:
            pendentes.append(base)      # minuta: nao ha OP, nao ha o que consultar
            continue
        await asyncio.sleep(_PGTO_DELAY)
        op: dict = {}
        try:
            ro = await cli.get(_API_OPOB.format(oid=int(oid)), headers=_HEADERS)
            # ⚠️ 403 AQUI NAO E RATE-LIMIT: esta rota devolve 403 (nao 404) para
            # opObId inexistente. Como o id veio da propria lista de DH isso
            # praticamente nao acontece; se acontecer, o certo e seguir em
            # frente, nunca entrar em backoff.
            if ro.status_code == 200 and isinstance(ro.json(), dict):
                op = ro.json()
        except Exception as e:
            logger.warning(f"  pgto {plano_acao_id}: OPOB {oid} {str(e)[:80]}")
        ob = (op.get("txOb") or "").strip()
        data_ob = _dt_br(op.get("dtEmissaoOb"))
        item = {
            **base,
            "opob_id": int(oid),
            "numero_op": (dh.get("txOp") or op.get("txOp") or "").strip(),
            "numero_ob": ob,
            "data_emissao_ob": data_ob,
            "data_emissao_op": _dt_br(op.get("dtEmissaoOp")),
            "situacao": (op.get("situacao") or "").strip(),
            "ordenador_despesa": (op.get("txCpfOrdenadorDespesa") or "").strip(),
            "gestor_financeiro": (op.get("txCpfGestorFinanceiro") or "").strip(),
            "dt_assinatura_ordenador": _dt_br(op.get("dtAssinaturaOrdDesp")),
            "dt_assinatura_gestor": _dt_br(op.get("dtAssinaturaGestFin")),
            # HISTORICO DE EVENTOS DE PAGAMENTO: a tabela da tela
            # detalhar-ordem-pagamento (Data | Responsavel | Situacao).
            "historico": [
                {"data": _dh_br(h.get("dhRegistro")),
                 "responsavel": (h.get("txCpfResponsavel") or "").strip(),
                 "situacao": (h.get("situacao") or "").strip()}
                for h in (op.get("historico") or []) if isinstance(h, dict)
            ],
        }
        if ob:
            total_pago += vl or 0.0
            if data_ob:
                datas.append(data_ob)
            pagos.append(item)
        else:
            pendentes.append(item)

    total = _num(valor_total)
    a_desembolsar = None if total is None else round(total - total_pago, 2)
    return {
        "valor_total": total,
        # AS CHAVES SAO AS DO `ops_obs` DE PROPOSITO — ver _dt_br acima.
        "valor_desembolsado": round(total_pago, 2),
        "valor_a_desembolsar": a_desembolsar,
        # Ultima OB pela DATA e nao pela ordem da lista: a API nao garante ordem.
        "data_ultimo_desembolso": max(datas, key=_chave_data) if datas else None,
        # 1 centavo de tolerancia: o rateio entre documentos habeis fecha em centavos.
        "pago_integral": bool(total and a_desembolsar is not None and a_desembolsar <= 0.01),
        "obs": pagos,
        "pendentes": pendentes,
    }


# ⚠️ UPDATE PROPRIO, e NAO o `UPSERT_SQL_NOMEADO`. Aquele INSERT ... ON CONFLICT
# usa `EXCLUDED.<coluna>` SEM COALESCE e e compartilhado com a coleta assistida
# do control-plane (routers/control.py::control_te_lote). Se `pagamentos`
# entrasse nele, cada passada da listagem — que nao conhece pagamento nenhum —
# APAGARIA a coluna em silencio, todo dia, nos dois caminhos de escrita.
_UPDATE_PGTO = """UPDATE transferegov_te
   SET pagamentos = %(pg)s::jsonb, pagamentos_atualizado_em = NOW()
 WHERE plano_acao_id = %(pid)s"""


async def run_pagamentos(budget_s: float | None = None) -> dict:
    """Preenche `transferegov_te.pagamentos` dos planos DA CARTEIRA.

    SO os planos com `municipio_id` — sao os unicos que o RM e a tela enxergam
    (`WHERE municipio_id = :m` nos dois). Enriquecer o resto seria pagar
    requisicao por dado que ninguem le: exatamente o desperdicio que
    `_ufs_do_tenant` acabou de matar do outro lado deste arquivo.

    Incremental por `pagamentos_atualizado_em`, como o `ops_obs_atualizado_em`
    das voluntarias: quem foi checado ha menos de TE_PGTO_MAX_AGE_DAYS nao volta
    a fila — inclusive quem voltou VAZIO, senao os ~30% de planos sem documento
    habil consumiriam a rodada inteira todo dia.

    NAO grava em `ingestion_log`: a fonte 'transferegov_te' ja registra a rodada
    da listagem, e uma segunda linha por dia mudaria o que a tela Status dos
    Dados le como "ultima coleta" e como `records_inserted`. O que houve aqui
    sai no log da aplicacao e no retorno desta funcao.
    """
    budget = _PGTO_BUDGET_S if budget_s is None else budget_s
    cn = psycopg2.connect(_sync_url())
    cn.autocommit = False
    cur = cn.cursor()
    cur.execute(
        "SELECT plano_acao_id, valor_total FROM transferegov_te "
        "WHERE municipio_id IS NOT NULL "
        "  AND (pagamentos_atualizado_em IS NULL "
        "       OR pagamentos_atualizado_em < NOW() - make_interval(days => %s)) "
        "ORDER BY pagamentos_atualizado_em NULLS FIRST, plano_acao_id",
        (_PGTO_MAX_AGE_DAYS,))
    fila = cur.fetchall()
    if not fila:
        logger.info("TE pagamentos: nada vencido nesta rodada")
        cur.close(); cn.close()
        return {"consultados": 0, "com_documento": 0, "pagos_integral": 0, "completo": True}
    logger.info(f"TE pagamentos: {len(fila)} plano(s) na fila (orcamento {budget:.0f}s)")
    t0 = time.time()
    consultados = com = integrais = 0
    completo = True
    async with httpx.AsyncClient(timeout=45, verify=False) as cli:
        for pid, vtotal in fila:
            if (time.time() - t0) >= budget:
                completo = False
                logger.warning(f"TE pagamentos: orcamento estourado apos {consultados} "
                               f"plano(s); a fila retoma na proxima rodada")
                break
            pg = await pagamentos_do_plano(cli, int(pid), vtotal)
            consultados += 1
            if pg is None:
                # Fonte muda: NAO carimba. O plano volta amanha e a coluna
                # continua NULA — "nao medido", que e o que impede o RM de
                # afirmar pendencia sem medida.
                continue
            if pg.get("obs") or pg.get("pendentes"):
                com += 1
            if pg.get("pago_integral"):
                integrais += 1
            cur.execute(_UPDATE_PGTO,
                        {"pg": json.dumps(pg, ensure_ascii=False), "pid": int(pid)})
            cn.commit()   # plano a plano: progresso persiste se travar depois
            await asyncio.sleep(_PGTO_DELAY)
    cur.close(); cn.close()
    logger.info(f"TE pagamentos: {consultados} consultado(s), {com} com documento "
                f"habil, {integrais} pago(s) 100% em {time.time()-t0:.0f}s")
    return {"consultados": consultados, "com_documento": com,
            "pagos_integral": integrais, "completo": completo}


# ---------------------------------------------------------------------------
# ⭐ A ARVORE DO PLANO — os outros 21 recursos da API oficial (14/09/2026)
# ---------------------------------------------------------------------------
# Tudo pendurado no plano por ID DO PAI. Cada filtro abaixo foi PROVADO em
# 14/09/2026 com valor impossivel (id 0 -> 0 itens) contra a base nacional:
#
#   plano ─┬─ planos-trabalho ─┬─ planos-trabalho-analises ── ...-analise-historico
#          │                   ├─ planos-trabalho-historico
#          │                   └─ orgaos-analises-pendentes (so com indicador "Sim")
#          ├─ executores ─┬─ meta
#          │              └─ finalidade
#          ├─ empenhos ── documentos-habeis ── ordens-pagamentos-ordens-bancarias
#          ├─ (id_agencia_conta) ─┬─ saldo-conta-gestao-financeira
#          │                      └─ gestao-financeira-lancamentos ── subtransacoes
#          ├─ relatorios-gestao
#          ├─ relatorios-gestao-novos ─┬─ ...-documento-liquidacao  (QUEM RECEBEU)
#          │                           └─ relatorios-gestao-analise
#          ├─ devolucao
#          ├─ planos-acao-historico
#          └─ (id_programa) programas-especiais   (15 no Brasil: 1 consulta/rodada)
#
# ⚠️ OS NOMES DE CAMPO SAO OS DA RESPOSTA, E NAO OS DO OPENAPI. Eles divergem
# em pelo menos dois recursos, medido em 14/09/2026: o filtro e
# `tx_identificacao_recebedor_relatorio_gestao_dl`, o campo que volta e
# `tx_identificacao_recebedor_mascarado_relatorio_gestao_dl`; idem
# `tx_cpf_responsavel_mascarado_devolucao`. A arvore guarda a resposta CRUA —
# quem le (a tela) le pelo nome que a fonte manda.
#
# ⚠️ TETO TAMBEM NA CONSULTA POR ID DO PAI, ao contrario da listagem. Filtro que
# a fonte deixe de reconhecer devolve a base NACIONAL: 730.455 lancamentos,
# 461.219 eventos de historico de plano de trabalho (medido em 14/09/2026). Sem
# teto, um renome do lado de la viraria uma varredura de 3.653 paginas gravada
# como o extrato de UM plano. 5.000 e folga: o maior filho medido tem dezenas.
_TETO_FILHOS = int(os.getenv("TE_TETO_FILHOS", "5000") or "5000")


class _FonteMuda(Exception):
    """Uma consulta da arvore ficou sem resposta — a arvore inteira nao vale."""


async def _pub_filhos(cli: httpx.AsyncClient, caminho: str,
                      params: dict) -> list[dict] | None:
    """Consulta por ID DO PAI: com teto (`_TETO_FILHOS`) e sem aceitar pagina
    faltando.

    ⚠️ PARAMETRO NULO = NAO HA O QUE PERGUNTAR: devolve [] SEM tocar a rede.
    `?id_empenho=` vazio e filtro que a fonte ignora — ou seja, o Brasil.
    """
    if any(v is None or v == "" for v in params.values()):
        return []
    return await _pub_todos(cli, caminho, params, teto_itens=_TETO_FILHOS,
                            exigir_completo=True)


def _doc_normalizado(valor, tipo) -> str | None:
    """Documento do favorecido/depositante do extrato -> so digitos, com zeros.

    ⚠️ A FONTE MANDA CNPJ COMO TEXTO DE FLOAT: `'394460055477.0'` e o CNPJ
    00.394.460/0554-77 do Ministerio da Fazenda, com o ".0" do float e SEM os
    dois zeros a esquerda. Na amostra de 14/09/2026, 209 de 264 documentos de
    pessoa juridica tinham 12 ou 13 digitos. Sem isto o CNPJ nao casa com nada.

    `tipo` 2 = pessoa juridica (14 digitos), 1 = pessoa fisica (11). O que nao e
    numero (`'***47295***'`, o CPF que a propria fonte mascara, ou `'***'`)
    volta como veio — mascara e da fonte, e nao nos cabe desfazer.
    """
    if valor is None:
        return None
    s = str(valor).strip()
    m = re.fullmatch(r"(\d+)(?:\.0+)?", s)
    if not m:
        return s or None
    digitos = m.group(1)
    t = _num(tipo)
    if t == 2:
        return digitos.zfill(14)
    if t == 1:
        return digitos.zfill(11)
    return digitos


async def _programas(cli: httpx.AsyncClient) -> dict[int, dict]:
    """`programas-especiais` INTEIRO, uma vez por rodada: sao 15 no Brasil
    (14/09/2026), entao uma consulta substitui uma por plano. {} se a fonte nao
    respondeu — o programa e acessorio e nao derruba a arvore de ninguem."""
    itens = await _pub_todos(cli, "programas-especiais", {}, teto_itens=500,
                             exigir_completo=True)
    return {int(p["id_programa"]): p for p in (itens or [])
            if p.get("id_programa") is not None}


async def arvore_do_plano(cli: httpx.AsyncClient, plano: dict,
                          programas: dict[int, dict] | None = None) -> dict | None:
    """Os 21 recursos da API oficial pendurados em UM plano de acao.

    ⚠️ TUDO OU NADA: se qualquer consulta ficar sem resposta, devolve None e
    quem chama NAO GRAVA — o detalhe anterior fica, e o carimbo nao anda (o
    plano volta primeiro na proxima rodada). Uma arvore com o extrato faltando
    seria lida pela tela como "a conta nao teve movimento".

    Tres consultas so acontecem quando ha o que perguntar, e isso e exato, nao
    economia de palpite: `orgaos-analises-pendentes` so com o indicador "Sim"
    no plano de trabalho (a base nacional dessa rota tinha ZERO linhas em
    14/09/2026); subtransacoes so com `quantidade_subtransacoes` > 0; a conta so
    com `id_agencia_conta`.
    """
    pid = plano.get("id_plano_acao")
    if pid is None:
        return None

    async def lista(caminho: str, **params) -> list[dict]:
        itens = await _pub_filhos(cli, caminho, params)
        if itens is None:
            raise _FonteMuda(f"{caminho} {params}")
        return itens

    try:
        planos_trabalho = await lista("planos-trabalho-especiais", id_plano_acao=pid)
        for pt in planos_trabalho:
            ptid = pt.get("id_plano_trabalho")
            analises = await lista("planos-trabalho-analises-especiais",
                                   id_plano_trabalho=ptid)
            for a in analises:
                a["historico"] = await lista(
                    "plano-trabalho-analise-historico-especiais",
                    id_plano_trabalho_analise_pt=a.get("id_plano_trabalho_analise_pt"))
            pt["analises"] = analises
            pt["historico"] = await lista("planos-trabalho-historico",
                                          id_plano_trabalho=ptid)
            pt["orgaos_pendentes"] = (
                await lista("orgaos-analises-pendentes-especiais", id_plano_trabalho=ptid)
                if _norm(pt.get("ind_orgao_analises_pendentes") or "") == "SIM" else [])

        executores = await lista("executores-especiais", id_plano_acao=pid)
        for ex in executores:
            eid = ex.get("id_executor")
            ex["metas"] = await lista("meta-especiais", id_executor=eid)
            ex["finalidades"] = await lista("finalidade-especiais", id_executor=eid)

        empenhos = await lista("empenhos-especiais", id_plano_acao=pid)
        for emp in empenhos:
            dhs = await lista("documentos-habeis-especiais", id_empenho=emp.get("id_empenho"))
            for dh in dhs:
                dh["ordens"] = await lista("ordens-pagamentos-ordens-bancarias-especiais",
                                           id_dh=dh.get("id_dh"))
            emp["documentos_habeis"] = dhs

        id_conta = plano.get("id_agencia_conta")
        conta = {"id_agencia_conta": id_conta, "saldo": None, "lancamentos": []}
        if id_conta:
            saldos = await lista("saldo-conta-gestao-financeira-especiais",
                                 id_agencia_conta=id_conta)
            # PK da fonte e a conta, entao vem 0 ou 1; se um dia vier mais de um,
            # vale o de data mais recente — nunca o primeiro da lista por acaso.
            conta["saldo"] = max(saldos, key=lambda s: str(s.get("data_saldo_conta") or ""),
                                 default=None)
            lancamentos = await lista("gestao-financeira-lancamentos-especiais",
                                      id_agencia_conta=id_conta)
            for lc in lancamentos:
                for campo, tipo in (("doc_favorecido_gestao_financeira",
                                     "tipo_favorecido_gestao_financeira"),
                                    ("doc_depositante_gestao_financeira",
                                     "tipo_depositante_gestao_financeira")):
                    lc[campo] = _doc_normalizado(lc.get(campo), lc.get(tipo))
                qtd = _num(lc.get("quantidade_subtransacoes_lancamento_gestao_financeira")) or 0
                lc["subtransacoes"] = (
                    await lista("gestao-financeira-subtransacoes-especiais",
                                id_lancamento_gestao_financeira=lc.get(
                                    "id_lancamento_gestao_financeira"))
                    if qtd > 0 else [])
            conta["lancamentos"] = lancamentos

        relatorios = await lista("relatorios-gestao-especiais", id_plano_acao=pid)
        relatorios_novos = await lista("relatorios-gestao-novos-especiais", id_plano_acao=pid)
        for rel in relatorios_novos:
            rid = rel.get("id_relatorio_gestao_novo")
            rel["documentos_liquidacao"] = await lista(
                "relatorios-gestao-documento-liquidacao-especiais",
                id_relatorio_gestao_novo=rid)
            rel["analises"] = await lista("relatorios-gestao-analise-especiais",
                                          id_relatorio_gestao_novo=rid)

        devolucoes = await lista("devolucao-especiais", id_plano_acao=pid)
        historico = await lista("planos-acao-historico-especiais", id_plano_acao=pid)
    except _FonteMuda as e:
        logger.warning(f"  arvore {pid}: sem resposta em {str(e)[:160]} — nada gravado")
        return None

    id_prog = plano.get("id_programa")
    return {
        "programa": (programas or {}).get(int(id_prog)) if id_prog is not None else None,
        "planos_trabalho": planos_trabalho,
        "executores": executores,
        "empenhos": empenhos,
        "conta": conta,
        "relatorios_gestao": relatorios,
        "relatorios_gestao_novos": relatorios_novos,
        "devolucoes": devolucoes,
        "historico": historico,
    }


# Os tres campos da ordem de pagamento que SO a SPA publica (a oficial nao tem
# CPF de ordenador/gestor nem evento de OP — varredura por conceito do modelo de
# dados, 09/09/2026). Vem da fase 3 (`run_reserva_spa`) e sao HERDADOS rodada a
# rodada, para a SPA ser consultada uma vez por OP, e nao todo dia.
_CAMPOS_SPA = ("ordenador_despesa", "gestor_financeiro", "historico")


def _ordem_que_vale(ordens: list[dict]) -> dict:
    """Entre as OP/OB de um documento habil, a que representa o pagamento.

    Medido em 14/09/2026: 0 de 1.600 DHs da amostra tinham mais de uma OP. Se
    um dia vierem duas (OP cancelada e reemitida), vale a que tem ORDEM
    BANCARIA, e entre elas a de emissao mais recente — o DH e pago uma vez so,
    e somar as duas inventaria dinheiro."""
    return max(ordens, key=lambda o: (bool((o.get("numero_ordem_bancaria") or "").strip()),
                                      str(o.get("data_emissao_ob") or ""),
                                      str(o.get("data_emissao_op") or "")))


def _ja_conferido_na_spa(item: dict | None) -> bool:
    """O item anterior ja passou pela SPA? Os itens gravados pelo caminho
    antigo (antes de 14/09/2026) nao tem a marca, mas tem o CPF preenchido."""
    if not item:
        return False
    return bool(item.get("spa_conferido") or item.get("ordenador_despesa")
                or item.get("gestor_financeiro") or item.get("historico"))


def pagamentos_da_arvore(arvore: dict, valor_total,
                         anterior: dict | None = None) -> dict:
    """Os PAGAMENTOS de um plano a partir da arvore oficial — no MESMO formato
    que `pagamentos_do_plano` (SPA) sempre gravou, chave por chave.

    O formato e o contrato: o RM le com `_desembolso_ops_obs` e
    `_ano_pagamento_ops_obs`, a tela desenha a grade de documentos habeis e o
    PDF imprime a caixa de desembolso. Mudar a FONTE nao pode mudar nada disso.

    REGRA DO QUE CONTA COMO DESEMBOLSADO (a mesma da SPA): documento habil com
    ORDEM BANCARIA emitida (`numero_ordem_bancaria` preenchido).

    ⚠️ MINUTA NAO E DINHEIRO, e a oficial a marca igual a SPA: no plano 91573 a
    minuta tem `numero_documento_habil` nulo, situacao 1 "Minuta de DH" e
    nenhuma OP. Vai para `pendentes`, e o valor dela fica no a-desembolsar.

    ⚠️ O VALOR E `valor_dh`, NUNCA `valor_rateio_dh`. Na minuta do 91573 o
    rateio e 205.066,16 — o valor do OUTRO documento, o que foi pago. Somar o
    rateio mostraria o plano 100% desembolsado sem a minuta ter virado dinheiro.

    `anterior` e o `pagamentos` que estava gravado: dele se herdam, por
    `opob_id` (os ids sao os mesmos nas duas APIs), os tres campos que so a SPA
    publica. Item sem herança sai com `spa_pendente` e a fase 3 completa.
    Herda SO se a OB nao mudou: OP que acabou de ganhar ordem bancaria tem
    historico novo, e o antigo pararia no "aguardando assinatura".
    """
    herdado: dict[int, dict] = {}
    if isinstance(anterior, dict):
        for it in list(anterior.get("obs") or []) + list(anterior.get("pendentes") or []):
            if isinstance(it, dict) and it.get("opob_id"):
                try:
                    herdado[int(it["opob_id"])] = it
                except (TypeError, ValueError):
                    pass

    pagos: list[dict] = []
    pendentes: list[dict] = []
    datas: list[str] = []
    total_pago = 0.0
    for emp in arvore.get("empenhos") or []:
        for dh in emp.get("documentos_habeis") or []:
            vl = _num(dh.get("valor_dh"))
            base = {
                "dh_id": dh.get("id_dh"),
                "numero_dh": (dh.get("numero_documento_habil") or ""),
                "minuta": (dh.get("id_minuta_documento_habil") or ""),
                "numero_empenho": (emp.get("numero_empenho") or ""),
                "valor": vl,
                "situacao_dh": (dh.get("descricao_situacao_dh") or ""),
            }
            ordens = [o for o in (dh.get("ordens") or []) if isinstance(o, dict)]
            if not ordens:
                pendentes.append(base)      # minuta ou DH ainda sem OP
                continue
            op = _ordem_que_vale(ordens)
            oid = _num(op.get("id_op_ob"))
            oid = int(oid) if oid else None
            ob = (op.get("numero_ordem_bancaria") or "").strip()
            data_ob = _dt_br(op.get("data_emissao_ob"))
            item = {
                **base,
                "opob_id": oid,
                "numero_op": (op.get("numero_ordem_pagamento") or "").strip(),
                "numero_ob": ob,
                "data_emissao_ob": data_ob,
                "data_emissao_op": _dt_br(op.get("data_emissao_op")),
                "situacao": (op.get("descricao_situacao_op") or "").strip(),
                "ordenador_despesa": "",
                "gestor_financeiro": "",
                "dt_assinatura_ordenador": _dt_br(op.get("data_assinatura_ordenador_despesa_ob")),
                "dt_assinatura_gestor": _dt_br(op.get("data_assinatura_gestor_financeiro_ob")),
                "historico": [],
            }
            h = herdado.get(oid) if oid else None
            if _ja_conferido_na_spa(h) and (h.get("numero_ob") or "").strip() == ob:
                for campo in _CAMPOS_SPA:
                    if h.get(campo):
                        item[campo] = h[campo]
                item["spa_conferido"] = True
            elif oid:
                item["spa_pendente"] = True
            if ob:
                total_pago += vl or 0.0
                if data_ob:
                    datas.append(data_ob)
                pagos.append(item)
            else:
                pendentes.append(item)

    total = _num(valor_total)
    a_desembolsar = None if total is None else round(total - total_pago, 2)
    return {
        "valor_total": total,
        "valor_desembolsado": round(total_pago, 2),
        "valor_a_desembolsar": a_desembolsar,
        "data_ultimo_desembolso": max(datas, key=_chave_data) if datas else None,
        "pago_integral": bool(total and a_desembolsar is not None and a_desembolsar <= 0.01),
        "obs": pagos,
        "pendentes": pendentes,
        # Quem produziu este JSON. E o que separa, na paridade, a primeira troca
        # de fonte (anterior da SPA) de uma mudanca real de uma rodada a outra.
        "fonte": "api_oficial",
    }


def divergencia_de_paridade(novo: dict, anterior: dict | None) -> str | None:
    """Na TROCA de fonte, o que mudou no que o RM le. None = bateu.

    So compara quando o anterior veio da SPA (sem `fonte`). Depois da primeira
    rodada oficial, diferenca entre rodadas e dinheiro novo, nao divergencia —
    e logar isso como paridade seria alarme falso todo dia.

    ⚠️ DIVERGENCIA NAO E NECESSARIAMENTE DEFEITO: a oficial e atualizada 1x/dia
    (`/data-atualizacao`), a SPA e em tempo real. OB emitida hoje aparece na SPA
    hoje e na oficial amanha. Cada linha do log se explica olhando as datas.
    """
    if not isinstance(anterior, dict) or anterior.get("fonte") == "api_oficial":
        return None
    difs = []
    a = _num(anterior.get("valor_desembolsado")) or 0.0
    n = _num(novo.get("valor_desembolsado")) or 0.0
    if abs(a - n) > 0.01:
        difs.append(f"desembolsado {a:.2f} (SPA) -> {n:.2f} (oficial)")
    if bool(anterior.get("pago_integral")) != bool(novo.get("pago_integral")):
        difs.append(f"pago_integral {bool(anterior.get('pago_integral'))} -> "
                    f"{bool(novo.get('pago_integral'))}")
    return "; ".join(difs) or None


# ⚠️ UPDATE PROPRIO, pelo mesmo motivo do `_UPDATE_PGTO`: o `UPSERT_SQL_NOMEADO`
# e compartilhado com a coleta assistida e nao conhece `detalhe` — se entrasse
# nele, cada passada da listagem APAGARIA a arvore.
_UPDATE_DETALHE = """UPDATE transferegov_te
   SET detalhe = %(det)s::jsonb, detalhe_atualizado_em = NOW()
 WHERE plano_acao_id = %(pid)s"""
_UPDATE_DETALHE_E_PGTO = """UPDATE transferegov_te
   SET detalhe = %(det)s::jsonb, detalhe_atualizado_em = NOW(),
       pagamentos = %(pg)s::jsonb, pagamentos_atualizado_em = NOW()
 WHERE plano_acao_id = %(pid)s"""


async def _data_da_fonte(cli: httpx.AsyncClient) -> str | None:
    """`/data-atualizacao`: quando a PROPRIA fonte foi atualizada.

    E outra coisa que a hora da nossa coleta, e ate aqui o Frescor so tinha a
    segunda: coletar as 3h nao significa que a fonte mudou as 3h — e fonte que
    parou de se atualizar continuava parecendo em dia. Medido em 14/09/2026:
    `{"data_ultima_atualizacao": "2026-09-14T00:00:00"}` — carga diaria."""
    try:
        r = await cli.get(f"{_API_PUB}/data-atualizacao", timeout=30)
        if r.status_code == 200:
            return (r.json() or {}).get("data_ultima_atualizacao")
    except Exception as e:
        logger.warning(f"  /data-atualizacao: {str(e)[:100]}")
    return None


def _grava_data_da_fonte(data: str | None) -> None:
    """Grava em `fonte_atualizacao` (conexao propria, excecao engolida: a tabela
    pode ainda nao existir no boot que antecede a migration, e isso nao pode
    custar a coleta)."""
    if not data:
        return
    try:
        cn = psycopg2.connect(_sync_url())
        cur = cn.cursor()
        cur.execute(
            "INSERT INTO fonte_atualizacao (fonte, data_fonte, consultado_em) "
            "VALUES ('transferegov_especiais', %s, NOW()) "
            "ON CONFLICT (fonte) DO UPDATE SET data_fonte = EXCLUDED.data_fonte, "
            "consultado_em = NOW()", (data,))
        cn.commit(); cur.close(); cn.close()
    except Exception as e:
        logger.warning(f"fonte_atualizacao falhou: {str(e)[:120]}")


async def run_detalhe(budget_s: float, fonte_atualizada_em: str | None = None) -> dict:
    """FASE 2: a arvore de cada plano da carteira, os mais velhos primeiro.

    Fila `ORDER BY detalhe_atualizado_em NULLS FIRST`: o que nao coube no
    orcamento de hoje e o primeiro de amanha — nenhum plano fica esquecido no
    fim de uma lista ordenada por nome. So planos com `municipio_id`, os unicos
    que tela e RM enxergam.

    Com `TE_PGTO_FONTE=oficial` (padrao), grava tambem os PAGAMENTOS, derivados
    da mesma arvore — nenhuma requisicao a mais.
    """
    cn = psycopg2.connect(_sync_url())
    cn.autocommit = False
    cur = cn.cursor()
    so_um = (os.getenv("TE_MUNICIPIO") or "").strip()
    cur.execute(
        "SELECT plano_acao_id, valor_total, raw_data, pagamentos FROM transferegov_te "
        "WHERE municipio_id IS NOT NULL "
        + ("AND municipio_id = %(m)s " if so_um.isdigit() else "")
        + "AND (detalhe_atualizado_em IS NULL "
          "     OR detalhe_atualizado_em < NOW() - make_interval(secs => %(s)s)) "
          "ORDER BY detalhe_atualizado_em NULLS FIRST, plano_acao_id",
        {"m": int(so_um) if so_um.isdigit() else None, "s": _DET_MAX_AGE_H * 3600})
    fila = cur.fetchall()
    grava_pgto = _PGTO_ON and _PGTO_FONTE != "spa"
    t0 = time.time()
    feitos = falhas = com_pgto = divergentes = 0
    if not fila:
        logger.info("TE arvore: nada vencido nesta rodada")
        cur.close(); cn.close()
        return {"fila": 0, "atualizados": 0, "falhas": 0, "restantes": 0,
                "paridade_divergente": 0}
    logger.info(f"TE arvore: {len(fila)} plano(s) na fila (orcamento {budget_s:.0f}s)")
    processados = 0
    async with httpx.AsyncClient(timeout=60) as cli:
        programas = await _programas(cli)
        for pid, vtotal, raw, anterior in fila:
            if (time.time() - t0) >= budget_s:
                logger.warning(f"TE arvore: orcamento estourado apos {processados} "
                               f"plano(s); {len(fila) - processados} entram primeiro "
                               f"na proxima rodada")
                break
            processados += 1
            raw = raw if isinstance(raw, dict) else (json.loads(raw) if raw else {})
            # Linha antiga ainda no formato da SPA nao tem os ids que penduram a
            # conta e o programa: a arvore sai sem eles ate a listagem regrava-la.
            plano = raw if raw.get("id_plano_acao") is not None else {"id_plano_acao": pid}
            arv = await arvore_do_plano(cli, plano, programas)
            if arv is None:
                falhas += 1
                continue
            arv["_fonte_atualizada_em"] = fonte_atualizada_em
            params = {"det": json.dumps(arv, ensure_ascii=False), "pid": int(pid)}
            if grava_pgto:
                ant = anterior if isinstance(anterior, dict) else (
                    json.loads(anterior) if anterior else None)
                pg = pagamentos_da_arvore(arv, vtotal, ant)
                dif = divergencia_de_paridade(pg, ant)
                if dif:
                    divergentes += 1
                    logger.warning(f"  paridade plano={pid}: {dif}")
                if pg["obs"] or pg["pendentes"]:
                    com_pgto += 1
                params["pg"] = json.dumps(pg, ensure_ascii=False)
                cur.execute(_UPDATE_DETALHE_E_PGTO, params)
            else:
                cur.execute(_UPDATE_DETALHE, params)
            cn.commit()   # plano a plano: progresso persiste se a tarefa cair
            feitos += 1
    cur.close(); cn.close()
    restantes = len(fila) - processados
    logger.info(f"TE arvore: FIM — {feitos} de {len(fila)} plano(s) atualizado(s), "
                f"{falhas} sem resposta, {restantes} para a proxima rodada, "
                f"{com_pgto} com documento habil, {divergentes} divergencia(s) de "
                f"paridade em {time.time() - t0:.0f}s")
    return {"fila": len(fila), "atualizados": feitos, "falhas": falhas,
            "restantes": restantes, "com_documento": com_pgto,
            "paridade_divergente": divergentes}


async def run_reserva_spa(budget_s: float) -> dict:
    """FASE 3: CPF do ordenador/gestor e historico de eventos — SO da SPA.

    Uma requisicao por OP marcada `spa_pendente` pela fase 2, e nunca de novo
    pela mesma OP (a marca vira `spa_conferido`). Na primeira rodada oficial
    quase nada cai aqui: os itens herdam os campos do `pagamentos` que o
    caminho antigo gravou.

    ⚠️ PARA NA PRIMEIRA RECUSA. E a mesma API cuja quota ja puniu a VPS por >6h,
    e requisicao REJEITADA renova a pena (INFRA.md §5). 403/429/5xx encerra a
    fase ate amanha — insistir e o que transforma um soluco em bloqueio.
    O dado principal ja esta gravado; faltar CPF por um dia e o custo aceito.
    """
    cn = psycopg2.connect(_sync_url())
    cn.autocommit = False
    cur = cn.cursor()
    alvo = json.dumps([{"spa_pendente": True}])
    cur.execute(
        "SELECT plano_acao_id, pagamentos FROM transferegov_te "
        "WHERE municipio_id IS NOT NULL AND pagamentos IS NOT NULL "
        "  AND (pagamentos->'obs' @> %(a)s::jsonb OR pagamentos->'pendentes' @> %(a)s::jsonb) "
        "ORDER BY plano_acao_id", {"a": alvo})
    fila = cur.fetchall()
    t0 = time.time()
    consultadas = completadas = 0
    recusada = False
    if fila:
        logger.info(f"TE reserva SPA: {len(fila)} plano(s) com OP sem CPF/historico "
                    f"(orcamento {budget_s:.0f}s)")
    async with httpx.AsyncClient(timeout=45, verify=False) as cli:
        for pid, pg in fila:
            if recusada or (time.time() - t0) >= budget_s:
                break
            pg = pg if isinstance(pg, dict) else json.loads(pg)
            mudou = False
            for item in list(pg.get("obs") or []) + list(pg.get("pendentes") or []):
                if not (isinstance(item, dict) and item.get("spa_pendente") and item.get("opob_id")):
                    continue
                if (time.time() - t0) >= budget_s:
                    break
                consultadas += 1
                try:
                    ro = await cli.get(_API_OPOB.format(oid=int(item["opob_id"])),
                                       headers=_HEADERS)
                except Exception as e:
                    logger.warning(f"  reserva SPA opob {item['opob_id']}: {str(e)[:80]}")
                    recusada = True
                    break
                if ro.status_code != 200:
                    logger.warning(f"  reserva SPA opob {item['opob_id']}: HTTP "
                                   f"{ro.status_code} — fase encerrada ate a proxima rodada")
                    recusada = True
                    break
                try:
                    op = ro.json()
                except ValueError:
                    op = None
                if not isinstance(op, dict):
                    continue
                item["ordenador_despesa"] = (op.get("txCpfOrdenadorDespesa") or "").strip()
                item["gestor_financeiro"] = (op.get("txCpfGestorFinanceiro") or "").strip()
                item["historico"] = [
                    {"data": _dh_br(h.get("dhRegistro")),
                     "responsavel": (h.get("txCpfResponsavel") or "").strip(),
                     "situacao": (h.get("situacao") or "").strip()}
                    for h in (op.get("historico") or []) if isinstance(h, dict)
                ]
                item.pop("spa_pendente", None)
                item["spa_conferido"] = True
                mudou = True
                completadas += 1
                await asyncio.sleep(_PGTO_DELAY)
            if mudou:
                cur.execute("UPDATE transferegov_te SET pagamentos = %(pg)s::jsonb "
                            "WHERE plano_acao_id = %(pid)s",
                            {"pg": json.dumps(pg, ensure_ascii=False), "pid": int(pid)})
                cn.commit()
    cur.close(); cn.close()
    if fila:
        logger.info(f"TE reserva SPA: {completadas} de {consultadas} OP(s) completada(s) "
                    f"em {time.time() - t0:.0f}s" + (" — parou na recusa da SPA" if recusada else ""))
    return {"planos": len(fila), "consultadas": consultadas,
            "completadas": completadas, "recusada": recusada}


def status_da_rodada(lst: dict, det: dict | None) -> tuple[str, int, str | None]:
    """A UMA linha do `ingestion_log` da rodada, somando listagem e arvore.

    A listagem manda (erro dela e erro da rodada). Com a listagem em dia, a
    arvore rebaixa para `partial` quando planos ficaram sem resposta da fonte
    ou de fora do orcamento — e diz quantos. A reserva na SPA NAO entra: faltar
    CPF de ordenador por um dia nao e coleta degradada, e a SPA recusando nao
    pode pintar de amarelo uma fonte que respondeu inteira.
    """
    status = lst.get("status") or "error"
    erro = lst.get("erro")
    n = int(lst.get("gravados") or 0)
    if status == "success" and det:
        if det.get("erro"):
            status, erro = "partial", f"arvore do plano falhou: {det['erro']}"
        elif det.get("falhas"):
            status, erro = "partial", (f"arvore: {det['falhas']} plano(s) sem resposta "
                                       f"da fonte; retomam na proxima rodada")
        elif det.get("restantes"):
            status, erro = "partial", (f"arvore: {det['restantes']} plano(s) nao "
                                       f"couberam no orcamento; entram primeiro na "
                                       f"proxima rodada")
    return status, (0 if status == "error" else n), erro


async def run() -> list[dict]:
    """Uma rodada completa: LISTAGEM + ARVORE (API oficial) + RESERVA NA SPA.

    ⚠️ AS FATIAS SAO RESERVADAS ANTES, e nao o que sobrar depois. Medido em
    producao (Freitas, 24/08, com a fonte ANTIGA): a listagem consumia o
    orcamento inteiro enquanto houvesse atraso, e sem reserva a fase seguinte
    NUNCA rodava — o log dizia "sem tempo" para sempre e a coluna ficava NULA
    sem ninguem ver erro. Hoje a listagem leva ~140s, mas a reserva fica: custa
    nada quando sobra tempo e e o que garante a arvore numa rodada lenta.

    Tudo na MESMA tarefa, de proposito: o Coolify nao tem endpoint de execucao
    e o comando trava por volta de 255 caracteres.

    Exceptions das fases 2 e 3 sao ENGOLIDAS: a listagem ja commitou municipio a
    municipio e nao pode ser desfeita por falha de fase posterior.
    """
    _t0 = time.time()
    async with httpx.AsyncClient(timeout=30) as cli:
        fonte_data = await _data_da_fonte(cli)
    _grava_data_da_fonte(fonte_data)
    logger.info(f"TE: fonte atualizada em {fonte_data or '(nao informado)'}")

    fatia_final = _SPA_BUDGET_S if _PGTO_FONTE != "spa" else _PGTO_BUDGET_S
    fatia_final = fatia_final if _PGTO_ON else 0.0
    teto_listagem = _teto_listagem_s(_BUDGET_S, _TETO_TAREFA_S, _DET_MIN_S + fatia_final)
    logger.info(f"TE: teto da tarefa {_TETO_TAREFA_S:.0f}s — listagem ate "
                f"{teto_listagem:.0f}s, {fatia_final:.0f}s reservados a fase final")
    lst = await run_municipios(budget_s=teto_listagem, registrar=False)
    saidas = [lst]

    det = None
    resto = _TETO_TAREFA_S - (time.time() - _t0) - fatia_final
    if resto < 30:
        logger.warning(f"TE arvore: sem tempo nesta rodada (sobraram {resto:.0f}s)")
        det = {"erro": "sem tempo nesta rodada; a fila inteira fica para a proxima"}
    else:
        try:
            det = await run_detalhe(budget_s=resto, fonte_atualizada_em=fonte_data)
        except Exception as e:
            logger.warning(f"TE arvore falhou: {str(e)[:150]}")
            det = {"erro": str(e)[:150]}
    saidas.append(det)

    status, n, erro = status_da_rodada(lst, det)
    _log_ingestao(status, n, erro)

    if _PGTO_ON:
        resto = _TETO_TAREFA_S - (time.time() - _t0)
        if resto < 30:
            logger.warning(f"TE fase final: sem tempo nesta rodada (sobraram {resto:.0f}s)")
        else:
            try:
                if _PGTO_FONTE == "spa":
                    saidas.append(await run_pagamentos(budget_s=min(_PGTO_BUDGET_S, resto)))
                else:
                    saidas.append(await run_reserva_spa(budget_s=min(_SPA_BUDGET_S, resto)))
            except Exception as e:
                logger.warning(f"TE fase final falhou: {str(e)[:150]}")
    return saidas


if __name__ == "__main__":
    asyncio.run(run())
