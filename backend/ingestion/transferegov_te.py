"""Coletor da TRANSFERENCIA ESPECIAL / EMENDA PIX (federal) -> tabela transferegov_te.

Por que um coletor em vez de buscar ao vivo: a API "especiais"
(especiais.transferegov.sistema.gov.br/.../public/plano-acao/listagem) RATE-LIMITA
forte — bloqueia (403) depois de ~10 paginas seguidas, e concorrencia piora. Coletar
MG inteiro (~8773 planos, ~44 paginas de 200) numa request web e inviavel. Aqui, no
worker (cron), paginamos DEVAGAR com backoff no 403 e fazemos upsert incremental; se
o gateway travar no meio, o progresso ja gravado fica e a proxima rodada continua.

O RM (services/rm_builder) e a tela (routers/transferegov.buscar) leem esta tabela.

Params ATUAIS da API (mudaram — o formato antigo page/size da 403): pageNumber
(1-based) / pageSize (teto 300; 200 e estavel) / uf. Ver memory te-emenda-pix-especiais.

Rodar:  python -m ingestion.transferegov_te            (MG, default)
        TE_UF=MG TE_PAGE_DELAY=2 python -m ingestion.transferegov_te
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

_API = ("https://especiais.transferegov.sistema.gov.br/"
        "maisbrasil-transferencia-especial-backend/api/public/plano-acao/listagem")
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
    "Referer": "https://especiais.transferegov.sistema.gov.br/transferencia-especial/plano-acao/consulta",
}
_PAGE_SIZE = 200                 # teto estavel (>=400 -> 403; 300 falha na 2a pagina)

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
_PAGE_DELAY = float(os.getenv("TE_PAGE_DELAY", "2") or "2")   # espaco entre paginas OK
_BACKOFFS = (8, 20, 45, 90)      # esperas ao tomar 403 (o rate-limit reseta com o tempo)
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


def _ufs_do_tenant(cur) -> list[str]:
    """As UFs que este tenant realmente acompanha, lidas da carteira.

    ⚠️ SUBSTITUI O DEFAULT "MG", que era um bug caro e mudo. Com `TE_UF` nao
    definido — que e o caso dos 4 tenants em producao — o coletor baixava Minas
    inteiro (~8773 planos, ~44 paginas) em TODO tenant. Medido em 17/08:

        freitas     MG=60                -> certo, por coincidencia
        montesiao   MG=1                 -> certo, por coincidencia
        trust       ES=3 GO=6 MG=8 TO=3  -> cobria 8 de 20 municipios
        santamaria  RS=1                 -> cobria ZERO

    No Santa Maria o `_municipios_uf(cur, "MG")` voltava vazio e nenhum
    beneficiario casava: 25 minutos de paginacao para gravar milhares de linhas
    de MG com municipio_id nulo. No Trust, 12 dos 20 municipios simplesmente
    nunca tiveram Transferencia Especial coletada. Sem erro em log nenhum —
    `gravados` alto, `casados` baixo ou zero, e a fonte sequer aparecia no
    Status dos Dados (ver `_log_ingestao`, que so passou a existir agora).

    Mesmo padrao de `routers/freshness._ufs_do_tenant`: quem manda e a carteira.
    `TE_UF` continua valendo como override manual (um estado especifico).
    """
    cur.execute("SELECT DISTINCT upper(uf) FROM municipios "
                "WHERE uf IS NOT NULL AND btrim(uf) <> '' ORDER BY 1")
    return [r[0] for r in cur.fetchall()]


def _municipios_uf(cur, uf: str) -> list[tuple[str, int]]:
    """(_norm(nome), id) dos municipios da UF — para casar o beneficiario ao PACTHA.
    Ordena pelo nome mais LONGO primeiro para 'Nova Serrana' vencer 'Serrana' etc."""
    cur.execute("SELECT id, nome FROM municipios WHERE uf = %s", (uf,))
    pares = [(_norm(nome), mid) for (mid, nome) in cur.fetchall() if nome]
    pares.sort(key=lambda x: len(x[0]), reverse=True)
    return pares


def _casa_municipio(ben_norm: str, pares: list[tuple[str, int]]) -> int | None:
    """Mesma regra do routers/transferegov.buscar: beneficiario CONTEM o nome do
    municipio (ex.: 'MUNICIPIO DE NOVA SERRANA')."""
    for nome_norm, mid in pares:
        if nome_norm and (nome_norm in ben_norm or ben_norm.endswith(nome_norm)):
            return mid
    return None


async def _fetch_page(cli: httpx.AsyncClient, uf: str, page: int) -> dict | None:
    """Uma pagina, com backoff no 403 (rate-limit). None se falhar de vez."""
    params = {"pageNumber": page, "pageSize": _PAGE_SIZE, "uf": uf}
    for espera in (0, *_BACKOFFS):
        if espera:
            await asyncio.sleep(espera)
        r = await cli.get(_API, params=params, headers=_HEADERS)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"  p{page}: HTTP {r.status_code} — aguardando {espera or _BACKOFFS[0]}s (rate-limit)")
    return None


def plano_para_linha(it: dict, mid: int | None) -> dict | None:
    """Traduz UM plano da API 'especiais' para as colunas de transferegov_te.

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


def _upsert(cur, it: dict, mid: int | None):
    linha = plano_para_linha(it, mid)
    if linha is None:
        return
    # psycopg2 usa %(nome)s; o texto nomeado usa :nome. Regex de UMA passada —
    # replace por nome corromperia prefixos (":situacao" dentro de
    # ":situacao_trabalho").
    import re as _re
    sql = UPSERT_SQL_NOMEADO.replace("CAST(:raw_data AS jsonb)", "%(raw_data)s")
    sql = _re.sub(r":(\w+)", r"%(\1)s", sql)
    cur.execute(sql, linha)


async def run_uf(uf: str, budget_s: float | None = None) -> dict:
    uf = uf.upper()
    budget = _BUDGET_S if budget_s is None else budget_s
    cn = psycopg2.connect(_sync_url())
    cn.autocommit = False
    cur = cn.cursor()
    pares = _municipios_uf(cur, uf)
    # ⚠️ FALHA ALTO EM VEZ DE BAIXAR UM ESTADO INTEIRO PARA O LIXO. Sem municipio
    # da UF na carteira, nenhum beneficiario casaria: seriam ~25min de paginacao
    # para gravar milhares de linhas com municipio_id nulo, que os leitores
    # (routers/transferegov e rm_builder, ambos `WHERE municipio_id = :m`) nunca
    # enxergam. Era exatamente o que acontecia no Trust e no Santa Maria.
    if not pares:
        msg = f"nenhum municipio de {uf} na carteira deste tenant"
        logger.error(f"TE {uf}: {msg} — nao vou baixar o estado inteiro")
        _log_ingestao("error", 0, msg)
        cur.close(); cn.close()
        return {"uf": uf, "gravados": 0, "casados": 0, "completo": False,
                "total_api": None, "erro": msg}
    # RETOMA de onde parou: a API tem QUOTA por IP (bloqueia depois de ~N paginas
    # numa janela), entao um run so nao pega tudo. Comeca na pagina apos as ja
    # gravadas (1 pagina de sobreposicao; upsert e idempotente por planoAcaoId) —
    # cada run diario AVANCA a cobertura ate completar. Se ja cobriu tudo, o loop
    # fecha logo (tail < pageSize). Reset periodico p/ refrescar: TE_RESET_PAGE=1.
    cur.execute("SELECT count(*) FROM transferegov_te WHERE uf = %s", (uf,))
    have = cur.fetchone()[0]
    reset = (os.getenv("TE_RESET_PAGE", "0") or "0").strip() == "1"
    start_page = 1 if reset else max(1, have // _PAGE_SIZE)
    logger.info(f"TE {uf}: {len(pares)} municipios | ja tem {have} linhas -> comeca pagina {start_page}")
    t0 = time.time()
    total_api = None
    gravados = 0
    casados = 0
    completo = False
    async with httpx.AsyncClient(timeout=60, verify=False) as cli:
        page = start_page
        while page <= 1000 and (time.time() - t0) < budget:
            data = await _fetch_page(cli, uf, page)
            if data is None:
                logger.warning(f"TE {uf}: parando na pagina {page} (403 persistente); retoma na proxima rodada")
                break
            lote = data.get("listaPlanosAcao") or []
            total_api = int(data.get("total") or 0)
            for it in lote:
                mid = _casa_municipio(_norm(it.get("beneficiarioNome") or ""), pares)
                if mid is not None:
                    casados += 1
                _upsert(cur, it, mid)
                gravados += 1
            cn.commit()   # grava a pagina (progresso persiste mesmo se travar depois)
            logger.info(f"TE {uf}: pagina {page} ({len(lote)} itens) | gravados={gravados}/{total_api} casados={casados}")
            if len(lote) < _PAGE_SIZE or (total_api and gravados >= total_api):
                completo = True
                break
            page += 1
            await asyncio.sleep(_PAGE_DELAY)
    cur.close(); cn.close()
    logger.info(f"TE {uf}: FIM — gravados={gravados} casados={casados} completo={completo} em {time.time()-t0:.0f}s")
    # ⭐ O QUE CONTA AQUI E `casados`, NAO `gravados` — mas SO no contexto certo.
    # A primeira versao destas regras gritava 'error' em dois casos normais, e
    # alarme que grita no dia a dia e alarme que se aprende a ignorar:
    #
    #   1. VARREDURA JA COMPLETA. A retomada comeca em start_page = have//200;
    #      com a tabela cheia, a pagina final volta vazia -> gravados=0 com
    #      completo=True. Isso e "nada novo hoje", nao falha — e acontecia TODO
    #      DIA no montesiao (varredura MG completa) apos o cron diario.
    #   2. RETOMADA SEM PLANO DA CARTEIRA. Num tenant de UM municipio, a maioria
    #      das ~44 paginas de MG nao contem plano dele: casados=0 numa pagina
    #      retomada e o esperado. O retrato do bug da UF ('gravados' alto com
    #      'casados' zero) so e diagnostico quando a varredura foi INTEIRA
    #      (start_page=1 e completo) — ai sim zero casamentos = UF errada.
    if gravados == 0 and completo:
        _log_ingestao("success", 0, f"{uf}: varredura completa — sem novidade nesta rodada")
    elif gravados == 0:
        _log_ingestao("error", 0, f"{uf}: nenhuma pagina coletada (rate-limit ou fonte fora)")
    elif casados == 0 and start_page == 1 and completo:
        _log_ingestao("error", 0, f"{uf}: {gravados} planos baixados e NENHUM casou com municipio da carteira")
    else:
        _log_ingestao("success" if completo else "partial", casados,
                      None if completo else f"{uf}: cobertura parcial, retoma na proxima rodada")
    return {"uf": uf, "gravados": gravados, "casados": casados, "completo": completo, "total_api": total_api}


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


async def run(uf: str | None = None) -> list[dict]:
    """Roda as UFs da carteira deste tenant (ou a de `TE_UF`/`uf`, se informada).

    ⚠️ O ORCAMENTO E DIVIDIDO entre as UFs, nao multiplicado por elas: a
    Scheduled Task mata o processo em `timeout -k 30 1600`, e dar `_BUDGET_S`
    cheio a cada UF faria a segunda ser degolada no meio da pagina — perdendo o
    log final, que e onde `casados` aparece. Como a retomada e por pagina
    (`start_page` vem do count ja gravado), cortar o tempo so adia cobertura;
    nunca perde progresso. No Trust, que tem 4 UFs, sao ~375s por UF e a
    cobertura completa leva algumas rodadas diarias — que e exatamente como o
    coletor ja foi desenhado para se comportar contra o rate-limit da fonte.
    """
    forcado = (uf or os.getenv("TE_UF") or "").strip().upper()
    if forcado:
        return [await run_uf(forcado)]

    cn = psycopg2.connect(_sync_url())
    cur = cn.cursor()
    try:
        ufs = _ufs_do_tenant(cur)
    finally:
        cur.close(); cn.close()

    if not ufs:
        logger.warning("TE: nenhum municipio com UF na carteira — nada a coletar")
        return []

    logger.info(f"TE: carteira deste tenant -> {', '.join(ufs)}")
    _t0 = time.time()
    # ⚠️ A FATIA DOS PAGAMENTOS E RESERVADA ANTES, e nao o que sobrar depois.
    #
    # Medido em producao (Freitas, 24/08): a LISTAGEM e incremental e retoma por
    # pagina, entao ela consome o orcamento INTEIRO todo dia enquanto houver
    # atraso a recuperar — e `_BUDGET_S` (1500) sozinho ja passa de
    # `_TETO_TAREFA_S` (1450). Sem esta reserva, `resto` nasce NEGATIVO e os
    # pagamentos NUNCA rodam: o log diria "sem tempo nesta rodada" para sempre,
    # e a coluna `pagamentos` ficaria eternamente NULA sem ninguem ver erro.
    #
    # A listagem e quem pode esperar: ela nao perde progresso (retoma da pagina
    # gravada) e a fonte a limita de qualquer jeito. Os pagamentos sao 1+N GETs
    # baratos por plano e sao o dado que o RM precisa para dizer PENDENTE DE
    # DESEMBOLSO — deixa-los para "se sobrar" e deixa-los de fora.
    _teto_listagem = _BUDGET_S
    if _PGTO_ON:
        _teto_listagem = max(60.0, min(_BUDGET_S, _TETO_TAREFA_S - _PGTO_BUDGET_S))
        if _teto_listagem < _BUDGET_S:
            logger.info(f"TE: listagem limitada a {_teto_listagem:.0f}s para reservar "
                        f"{_PGTO_BUDGET_S:.0f}s aos pagamentos (teto da tarefa "
                        f"{_TETO_TAREFA_S:.0f}s)")
    fatia = _teto_listagem / len(ufs)
    saidas = []
    for u in ufs:
        saidas.append(await run_uf(u, budget_s=fatia))
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
