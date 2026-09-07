"""Coletor da TRANSFERENCIA ESPECIAL / EMENDA PIX (federal) -> tabela transferegov_te.

DUAS FONTES, DE PROPOSITO — e a divisao nao e arbitraria, ela segue onde cada
uma e melhor (medido em 06/09/2026):

  1. LISTAGEM (planos de acao) -> API PUBLICA OFICIAL, `api-publica.transferegov.
     gestao.gov.br/especiais`. Publicada no Comunicado no 23/2026 do MGI.
  2. PAGAMENTOS (documentos habeis -> OP/OB) -> continua na API interna da SPA
     (`especiais.transferegov.sistema.gov.br/.../api/public`), porque so ela tem
     o CPF do ordenador/gestor e o HISTORICO DE EVENTOS da ordem de pagamento.

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
"""
from __future__ import annotations
import os
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
# PAGAMENTOS: documentos habeis -> ordem de pagamento/bancaria + historico
# ---------------------------------------------------------------------------
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
_PGTO_DELAY = float(os.getenv("TE_PGTO_DELAY", "0.5") or "0.5")
_PGTO_BUDGET_S = float(os.getenv("TE_PGTO_BUDGET_S", "300") or "300")
_PGTO_MAX_AGE_DAYS = int(os.getenv("TE_PGTO_MAX_AGE_DAYS", "3") or "3")
# ⚠️ TETO DA TAREFA INTEIRA, e nao de uma fase dela. A Scheduled Task mata o
# processo em `timeout -k 30 1600` (ver a docstring de `run`), e a listagem
# sozinha ja pede `_BUDGET_S`=1500. Somar `_PGTO_BUDGET_S`=300 em cima daria
# 1800s: a fase de pagamentos seria degolada no meio e o log final — que e onde
# o resultado aparece — se perderia. Por isso `run()` CRONOMETRA a listagem e
# passa o RESTO aos pagamentos, nunca o orcamento cheio. 1450 deixa 150s de
# folga antes do kill, para o commit final e o log caberem.
_TETO_TAREFA_S = float(os.getenv("TE_TETO_TAREFA_S", "1450") or "1450")
_BUDGET_S = float(os.getenv("TE_BUDGET_S", "1500") or "1500")  # teto total (~25min)


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
    """
    p = {**params, "pagina": pagina, "tamanho_da_pagina": _PUB_PAGE_SIZE}
    try:
        r = await cli.get(f"{_API_PUB}/{caminho}", params=p, timeout=60)
    except Exception as e:
        logger.warning(f"  API oficial {caminho}: {str(e)[:100]}")
        return None
    if r.status_code != 200:
        logger.warning(f"  API oficial {caminho} {p}: HTTP {r.status_code}")
        return None
    try:
        return r.json()
    except ValueError:
        logger.warning(f"  API oficial {caminho}: resposta nao e JSON")
        return None


async def _pub_todos(cli: httpx.AsyncClient, caminho: str, params: dict) -> list[dict] | None:
    """Todas as paginas de uma consulta. None quando a PRIMEIRA pagina falhou.

    A distincao importa: lista vazia e "a fonte respondeu e nao ha nada" (estado
    legitimo — municipio sem emenda especial), enquanto None e "nao consegui
    perguntar". Quem chama usa isso para nao gravar silencio como ausencia.
    """
    d = await _pub_pagina(cli, caminho, params, 1)
    if d is None:
        return None
    itens = list(d.get("data") or [])
    total_paginas = int(d.get("total_pages") or 1)
    for pag in range(2, total_paginas + 1):
        await asyncio.sleep(_PUB_DELAY)
        d = await _pub_pagina(cli, caminho, params, pag)
        if d is None:
            logger.warning(f"  {caminho}: parou na pagina {pag}/{total_paginas}")
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
                             {"cnpj_beneficiario": so_digitos})
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
    """Municipios do tenant com o que a coleta precisa: id, nome, uf e CNPJ.

    O CNPJ vem de `municipios.cnpj`, que o `ingestion/siconfi.py` preenche
    sozinho a partir do cadastro do Tesouro — a docstring de la ja dizia, desde
    antes desta migracao, que "a Transferencia Especial casa por CNPJ".
    """
    cur.execute("SELECT id, nome, upper(coalesce(uf, '')), "
                "       coalesce(regexp_replace(coalesce(cnpj, ''), '\\D', '', 'g'), '') "
                "  FROM municipios ORDER BY nome")
    return [{"id": r[0], "nome": r[1], "uf": r[2], "cnpj": r[3]}
            for r in cur.fetchall()]


async def _beneficiario_por_nome(cli: httpx.AsyncClient, mun: dict) -> dict | None:
    """FALLBACK para municipio sem CNPJ cadastrado: acha o beneficiario na UF.

    ⚠️ AINDA E CASAMENTO POR NOME, com todos os defeitos que esta fase existe
    para matar — mas num universo MUITO menor e sem consequencia sobre o dado
    dos outros: a lista de beneficiarios de uma UF tem centenas de linhas (498
    no RS), nao milhares de planos, e o que se escolhe aqui e UM beneficiario,
    nao um plano. Sem CNPJ, a alternativa seria nao coletar o municipio.

    Exige nome EXATO (normalizado) ou 'MUNICIPIO DE <nome>' — nada de substring,
    que e o que fazia 'SERRANA' capturar 'NOVA SERRANA'.
    """
    if not mun["uf"]:
        return None
    itens = await _pub_todos(cli, "beneficiarios-especiais",
                             {"uf_beneficiario": mun["uf"]})
    if not itens:
        return None
    alvo = _norm(mun["nome"])
    for b in itens:
        nome = _norm(b.get("nome_beneficiario") or "")
        if nome == alvo or nome == f"MUNICIPIO DE {alvo}":
            return b
    return None


async def run_municipios(budget_s: float | None = None) -> dict:
    """LISTAGEM pela API publica oficial, municipio a municipio.

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
        _log_ingestao("error", 0, msg)
        cur.close(); cn.close()
        return {"municipios": 0, "gravados": 0, "completo": False, "erro": msg}

    t0 = time.time()
    gravados = com_plano = sem_cnpj = sem_beneficiario = falhas = 0
    atendidos = 0
    completo = True
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
                ben = await _beneficiario_por_nome(cli, mun)
            atendidos += 1
            if not ben:
                # ⚠️ ESTADO LEGITIMO, e nao erro: municipio que nunca recebeu
                # emenda especial simplesmente nao esta na fonte. Contamos para
                # o log final poder distinguir "todos sem beneficiario" (que ai
                # sim cheira a defeito) de "alguns".
                sem_beneficiario += 1
                continue
            planos = await _pub_todos(cli, "planos-acao-especiais",
                                      {"id_beneficiario": ben.get("id_beneficiario")})
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
        _log_ingestao("error", 0, "a fonte nao respondeu a nenhum municipio")
    elif atendidos and sem_beneficiario == atendidos:
        _log_ingestao("error", 0, f"nenhum dos {atendidos} municipios tem beneficiario "
                                  f"na fonte — CNPJ errado ou fonte mudou")
    elif not completo or falhas:
        _log_ingestao("partial", gravados,
                      f"{falhas} municipio(s) sem resposta; retoma na proxima rodada"
                      if falhas else "orcamento estourado; retoma na proxima rodada")
    else:
        _log_ingestao("success", gravados, None)
    return {"municipios": atendidos, "gravados": gravados, "com_plano": com_plano,
            "sem_cnpj": sem_cnpj, "sem_beneficiario": sem_beneficiario,
            "falhas": falhas, "completo": completo}


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


async def run() -> list[dict]:
    """Uma rodada completa: LISTAGEM (API oficial) + PAGAMENTOS (SPA).

    ⚠️ O ORCAMENTO DA LISTAGEM ENCOLHEU DE PROPOSITO, e isso e consequencia
    direta da troca de fonte. O caminho antigo precisava de ~1500s porque
    paginava estados inteiros contra uma API que bloqueava no meio; a oficial
    faz a carteira inteira em poucos segundos por municipio. O que sobra vai
    para os pagamentos, que sao a parte cara agora.
    """
    _t0 = time.time()
    # ⚠️ A FATIA DOS PAGAMENTOS CONTINUA SENDO RESERVADA ANTES, e nao o que
    # sobrar depois — a conta e a mesma de quando a listagem era o gargalo.
    #
    # Medido em producao (Freitas, 24/08, com a fonte ANTIGA): a listagem
    # consumia o orcamento inteiro todo dia enquanto houvesse atraso a
    # recuperar, e `_BUDGET_S` (1500) sozinho ja passava de `_TETO_TAREFA_S`
    # (1450). Sem a reserva, `resto` nascia NEGATIVO e os pagamentos NUNCA
    # rodavam: o log dizia "sem tempo nesta rodada" para sempre e a coluna
    # `pagamentos` ficava eternamente NULA sem ninguem ver erro.
    #
    # Com a API oficial a listagem deixou de ser o gargalo, mas a reserva FICA:
    # ela custa nada quando sobra tempo e continua sendo a unica coisa que
    # garante os pagamentos numa rodada em que a fonte esteja lenta.
    teto_listagem = _teto_listagem_s(_BUDGET_S, _TETO_TAREFA_S, _PGTO_BUDGET_S) \
        if _PGTO_ON else _BUDGET_S
    if teto_listagem < _BUDGET_S:
        logger.info(f"TE: listagem limitada a {teto_listagem:.0f}s para reservar "
                    f"{_PGTO_BUDGET_S:.0f}s aos pagamentos (teto da tarefa "
                    f"{_TETO_TAREFA_S:.0f}s)")
    saidas = [await run_municipios(budget_s=teto_listagem)]
    # PAGAMENTOS na MESMA rodada, de proposito: nao da para criar uma segunda
    # Scheduled Task barata no Coolify — a API dele nao tem endpoint de execucao
    # e o comando trava por volta de 255 caracteres.
    #
    # ⚠️ O ORCAMENTO E O QUE SOBROU, e nao `_PGTO_BUDGET_S` cheio. A listagem
    # acabou de consumir ate `_BUDGET_S` (1500s) e a Scheduled Task mata tudo em
    # 1600s: pedir mais 300 aqui seria pedir 1800 e ser degolado no meio, com o
    # log final perdido. Se nao sobrou tempo, a fila simplesmente espera a
    # proxima rodada — ela e incremental e nao perde progresso.
    #
    # Exception ENGOLIDA: a listagem ja commitou pagina a pagina e nao pode ser
    # derrubada por uma falha do enrich.
    if _PGTO_ON:
        resto = _TETO_TAREFA_S - (time.time() - _t0)
        if resto < 30:
            logger.warning(f"TE pagamentos: sem tempo nesta rodada "
                           f"(sobraram {resto:.0f}s); fica para a proxima")
        else:
            try:
                saidas.append(await run_pagamentos(budget_s=min(_PGTO_BUDGET_S, resto)))
            except Exception as e:
                logger.warning(f"TE pagamentos falhou: {str(e)[:150]}")
    return saidas


if __name__ == "__main__":
    asyncio.run(run())
