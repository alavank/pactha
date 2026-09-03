"""
Portal da Transparencia federal (CGU) — SCAFFOLD, esperando a chave.

⚠️ ESTE COLETOR NAO RODA HOJE, E ISSO E DE PROPOSITO. Ele so acorda quando a env
`PORTAL_TRANSPARENCIA_API_KEY` estiver preenchida; sem ela, sai na hora gravando
`ingestion_log` com `success` e a nota "sem chave" — o mesmo desenho do
`fpe_rs.py` e do SIGCON sem credencial, para o watchdog nao acusar fonte parada
que ninguem ligou.

A CHAVE E DE PESSOA FISICA, e isso e uma decisao, nao um detalhe tecnico. Ela
sai de `portaldatransparencia.gov.br/api-de-dados/cadastrar-email` com conta
gov.br Prata ou Ouro, e fica vinculada ao CPF de quem cadastrou. Num produto com
cinco tenants isso e um passivo: a chave de uma pessoa passa a responder pelas
consultas de todas as prefeituras. Por isso ela nao e pedida ao cliente — quem
decide se e quando ligar e o dono do PACTHA.

⭐ O QUE ESTA API TEM QUE O TRANSFEREGOV NAO DA. A auditoria de 29/08/2026
concluiu "derivado do SICONV com menos colunas — ignorar como fonte", e isso e
VERDADE para `/convenios`: o dump do TransfereGov que ja coletamos e mais rico.
Mas o Swagger (lido em 02/09/2026) mostra duas coisas que nao existem la:

  1. **`/emendas/documentos/{codigo}`** — os documentos de execucao de UMA
     emenda (empenho, liquidacao, pagamento), a partir do codigo que o
     TransfereGov ja nos da. E o elo entre "a emenda foi indicada" e "o dinheiro
     saiu", pelo lado da CGU.

  2. **Programas sociais POR MUNICIPIO** (`bolsa-familia-por-municipio`,
     `novo-bolsa-familia-por-municipio`, `bpc-por-municipio`,
     `auxilio-brasil-por-municipio`, `seguro-defeso`, `safra`, `peti`), todos com
     `codigoIbge` + `mesAno`. Nao e convenio, e retrato social do municipio — o
     que o gestor usa para justificar pleito. Nenhum deles existe no produto.

⚠️ E O QUE ELA **NAO** TEM: filtro por municipio em `/emendas`. Os parametros
sao `codigoEmenda`, `numeroEmenda`, `nomeAutor`, `tipoEmenda`, `ano`,
`codigoFuncao`, `codigoSubfuncao` — nenhum territorial. Varrer o Brasil inteiro
para achar as emendas de Nova Palma seria caro e desnecessario: o caminho e
partir dos codigos de emenda que o TransfereGov ja trouxe para a carteira.

CONTRATO DA API, conferido no Swagger (`/v3/api-docs`, 167 KB):
    cabecalho `chave-api-dados: <chave>`
    paginacao por `pagina` (comeca em 1); pagina vazia = fim
    401 sem chave (medido)

Quando a chave existir:
    PORTAL_TRANSPARENCIA_API_KEY=... python -u ingestion/portal_transparencia.py
"""
import json
import logging
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("portal_transparencia")

BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
UA = {"User-Agent": "Mozilla/5.0 (PACTHA/1.0 Portal da Transparencia/CGU)",
      "Accept": "application/json"}
TIMEOUT = 60

# A CGU limita por minuto e a janela e mais apertada fora do horario comercial
# (a propria documentacao publica avisa). 700ms entre chamadas fica folgado
# dentro de qualquer das faixas.
PAUSA_S = float(os.getenv("PORTAL_TRANSPARENCIA_PAUSA_S", "0.7") or "0.7")


def chave() -> str:
    return (os.getenv("PORTAL_TRANSPARENCIA_API_KEY") or "").strip()


def habilitado() -> bool:
    return bool(chave())


def _cabecalhos() -> dict:
    return {**UA, "chave-api-dados": chave()}


def paginar(client: httpx.Client, caminho: str, params: dict,
            teto_paginas: int = 50) -> list[dict]:
    """Percorre `pagina=1..N` ate a fonte devolver lista vazia.

    ⚠️ O TETO EXISTE E E REGISTRADO. Sem ele, uma mudanca de contrato que passe
    a repetir a primeira pagina viraria laco infinito contra um orgao publico.
    Quando o teto e atingido, o log DIZ — coleta truncada em silencio e pior que
    coleta que falha."""
    out: list[dict] = []
    for pagina in range(1, teto_paginas + 1):
        r = client.get(f"{BASE}{caminho}", params={**params, "pagina": pagina},
                       headers=_cabecalhos(), timeout=TIMEOUT)
        if r.status_code == 401:
            raise PermissionError(
                "chave-api-dados recusada (401). A chave e vinculada ao CPF de "
                "quem a cadastrou e pode ter sido revogada.")
        r.raise_for_status()
        lote = r.json() or []
        if not isinstance(lote, list) or not lote:
            return out
        out.extend(lote)
        time.sleep(PAUSA_S)
    log.warning("%s: teto de %d paginas atingido — resultado TRUNCADO",
                caminho, teto_paginas)
    return out


def documentos_da_emenda(client: httpx.Client, codigo: str) -> list[dict]:
    """Empenho, liquidacao e pagamento de UMA emenda.

    O `codigo` vem da nossa propria base (o TransfereGov ja o traz para a
    carteira) — esta API nao tem filtro territorial em `/emendas`."""
    return paginar(client, f"/emendas/documentos/{codigo}", {})


def convenios_do_municipio(client: httpx.Client, ibge: str,
                           data_inicial: str, data_final: str) -> list[dict]:
    """⚠️ REDUNDANTE COM O TRANSFEREGOV, e esta aqui so como conferencia
    amostral. O dump do SICONV que ja coletamos tem mais colunas; usar isto como
    fonte primaria seria trocar um dado rico por um resumo."""
    return paginar(client, "/convenios", {
        "codigoIBGE": ibge, "dataInicial": data_inicial, "dataFinal": data_final})


# Programas sociais por municipio: `codigoIbge` + `mesAno` (formato AAAAMM).
# Nao sao convenio — sao o retrato social que sustenta o pleito.
PROGRAMAS_SOCIAIS = {
    "novo_bolsa_familia": "/novo-bolsa-familia-por-municipio",
    "bpc": "/bpc-por-municipio",
    "auxilio_brasil": "/auxilio-brasil-por-municipio",
    "seguro_defeso": "/seguro-defeso-por-municipio",
    "safra": "/safra-por-municipio",
    "peti": "/peti-por-municipio",
}


def programa_social(client: httpx.Client, chave_programa: str, ibge: str,
                    mes_ano: str) -> list[dict]:
    caminho = PROGRAMAS_SOCIAIS[chave_programa]
    return paginar(client, caminho, {"codigoIbge": ibge, "mesAno": mes_ano})


def _log_ingest(cur, conn, status: str, n: int, erro: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) "
            "VALUES ('portal_transparencia', %s, %s, %s, NOW())",
            (status, n, erro))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


NOTA_SEM_CHAVE = (
    "sem PORTAL_TRANSPARENCIA_API_KEY — coletor inerte por decisao. A chave sai "
    "de portaldatransparencia.gov.br/api-de-dados/cadastrar-email com conta "
    "gov.br Prata/Ouro e fica vinculada ao CPF de quem a cadastrou.")


def ingest(dry: bool = False) -> int:
    """Hoje so registra o estado. A gravacao entra junto com a decisao de ligar.

    ⚠️ SAI COMO `success`, NAO como erro: fonte que ninguem ligou nao e fonte
    quebrada, e marca-la assim faria o watchdog alarmar para sempre sobre uma
    escolha deliberada. Mesmo desenho do `fpe_rs.py`."""
    from ingestion._resilience import get_sync_db_url, neon_connect

    if not habilitado():
        log.info("Portal da Transparencia: %s", NOTA_SEM_CHAVE)
        if not dry:
            with neon_connect(get_sync_db_url()) as conn:
                cur = conn.cursor()
                try:
                    _log_ingest(cur, conn, "success", 0, NOTA_SEM_CHAVE)
                finally:
                    cur.close()
        return 0

    # ⚠️ A CHAVE EXISTE, MAS A GRAVACAO AINDA NAO FOI DECIDIDA. Preencher a env
    # nao pode, sozinho, comecar a escrever tabela nova em cinco bancos: o que
    # entra (execucao de emenda? programas sociais? os dois?) e uma decisao de
    # produto, nao um efeito colateral de configuracao. Ate la, o coletor
    # CONFERE que a chave funciona e diz isso — util e inofensivo.
    with httpx.Client(follow_redirects=True) as client:
        try:
            r = client.get(f"{BASE}/despesas/tipo-transferencia",
                           headers=_cabecalhos(), timeout=TIMEOUT)
            ok = r.status_code == 200
        except Exception as e:
            log.warning("Portal da Transparencia: %s: %s", type(e).__name__, str(e)[:120])
            ok = False
    nota = ("chave valida — falta decidir o que gravar (execucao de emenda por "
            "codigo, programas sociais por municipio, ou ambos)"
            if ok else "chave presente mas recusada pela API")
    log.info("Portal da Transparencia: %s", nota)
    if not dry:
        with neon_connect(get_sync_db_url()) as conn:
            cur = conn.cursor()
            try:
                _log_ingest(cur, conn, "success" if ok else "partial", 0, nota)
            finally:
                cur.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
