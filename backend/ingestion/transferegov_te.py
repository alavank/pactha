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
    fatia = _BUDGET_S / len(ufs)
    saidas = []
    for u in ufs:
        saidas.append(await run_uf(u, budget_s=fatia))
    return saidas


if __name__ == "__main__":
    asyncio.run(run())
