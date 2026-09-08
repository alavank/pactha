"""
Sistema de Monitoramento de Convenios do RS (FPE) — Decreto Estadual 56.939/2023.

⚠️ ESTE COLETOR NASCE INERTE, E ISSO E O ENTREGAVEL DE HOJE. Sem a credencial do
Portal de Convenios e Parcerias (conta gov.br com perfil PCPRS) ele registra uma
rodada limpa dizendo que nao ha credencial — e NADA MAIS. A navegacao autenticada
esta marcada como pendente e falha alto quando alcancada, com a URL e o proximo
passo no erro; ver `_coletar_do_portal`.

Escrever a raspagem "no escuro", contra um portal que nao consigo abrir, produz
codigo que parece pronto e quebra no primeiro uso real — pior que ausencia,
porque ninguem revisita o que parece feito.

O QUE JA VALE HOJE, mesmo inerte:
  - a tela `/api/monitoramento` existe e diz "ainda nao conectado" (nunca um
    verde, nunca um alarme falso);
  - a regra do decreto esta escrita e TESTADA (`services/monitoramento_rs.py`,
    `tests/test_monitoramento_rs.py`), entao no dia em que a credencial entrar o
    alarme ja funciona;
  - o watchdog nao cobra a fonte, porque a rodada sai `success`.

⚠️ `success` E NAO `error` QUANDO FALTA CREDENCIAL — regra do dono, ja aplicada
no `sigcon_scraper._run()`: credencial ausente e NOTA, nunca alarme. Marcar
`error` faria o watchdog acusar "fonte parada" para sempre num tenant que
simplesmente ainda nao tem a senha, e o alerta verdadeiro se perderia no ruido.

ONDE FICA O QUE INTERESSA (medido em 16/08/2026):
  O portal institucional (`convenioseparcerias.rs.gov.br`) e vitrine: a unica
  "consulta publica" dele e sobre a INSTRUCAO NORMATIVA, nao sobre convenios. O
  modulo de monitoramento vive no FPE:

      https://portalfpe.sefaz.rs.gov.br/APL/PRFPEM27/ProgramasNet/
          FPE-MonitConvenio-Pesquisar_Out.aspx

  ASP.NET WebForms; responde 200 sem login, mas devolve erro de sessao. O sufixo
  `_Out` sugere acesso externo (o convenente), que e o perfil do cliente.

  ⚠️ E o FPE tem JANELA DE FUNCIONAMENTO: segunda a sabado, das 7h as 22h30. Fora
  disso os servicos respondem `500` com essa frase — medido no CADIN, que usa o
  mesmo backend. Um cron de madrugada falharia todo dia, e por isso a Scheduled
  Task deste coletor tem de ficar dentro da janela.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("fpe_rs")

FONTE = "FPE-RS"
UF = "RS"
# Como a credencial e reconhecida no Cofre. Espelha o criterio do
# `sigcon_scraper._list_credentials` (sistema ILIKE ... OR automation_key = ...).
SISTEMA = "PCPRS"
AUTOMATION_KEY = "pcprs"
PORTAL = ("https://portalfpe.sefaz.rs.gov.br/APL/PRFPEM27/ProgramasNet/"
          "FPE-MonitConvenio-Pesquisar_Out.aspx")


def _credenciais(cur) -> list[dict]:
    """Credenciais PCPRS por municipio do RS, ja decifradas.

    Mesmo formato do SIGCON: uma credencial POR MUNICIPIO, porque o usuario do
    portal so enxerga a entidade dele. Cofre vazio devolve lista vazia — e isso
    e um estado legitimo, nao um erro."""
    # ⚠️ A coluna chama `senha_hash` e NAO e hash: e a senha CIFRADA (AES-GCM
    # com a COFRE_KEY do tenant). Nome herdado; `decrypt` e o que se usa nela,
    # exatamente como faz o sigcon_scraper.
    from services.crypto import decrypt
    cur.execute("""
        SELECT cs.id, m.id, m.nome, cs.usuario, cs.senha_hash
          FROM cofre_senhas cs
          JOIN municipios m ON m.id = cs.municipio_id
         WHERE m.active AND upper(coalesce(m.uf,'')) = %s
           AND (cs.sistema ILIKE %s OR cs.automation_key = %s)
         ORDER BY m.nome
    """, (UF, f"{SISTEMA}%", AUTOMATION_KEY))
    saida = []
    for _id, mid, nome, usuario, senha in cur.fetchall():
        # ⚠️ COFRE_KEY errada decifra para "" EM SILENCIO (services/crypto.py).
        # Sem esta guarda, a credencial pareceria cadastrada e o login falharia
        # como se a senha estivesse errada — mandando o dono resetar a senha
        # certa no portal do Estado.
        clara = decrypt(senha) if senha else ""
        if not clara:
            log.warning("  %s: credencial cadastrada mas decifrou VAZIO — "
                        "confira a COFRE_KEY deste tenant antes de culpar o portal", nome)
            continue
        saida.append({"cofre_id": _id, "municipio_id": mid, "nome": nome,
                      "usuario": usuario, "senha": clara})
    return saida


def _coletar_do_portal(cred: dict) -> list[dict]:
    """PENDENTE — a navegacao autenticada no FPE.

    Nao esta implementada de proposito: sem uma credencial PCPRS real nao ha como
    abrir o portal, e raspagem escrita as cegas contra WebForms (ViewState,
    postback, grid paginada) nao e codigo — e chute com aparencia de codigo.

    O QUE FALTA, na ordem, quando a credencial chegar:
      1. login gov.br -> perfil PCPRS (o SSO e o mesmo do TransfereGov, entao
         `ingestion/renovar_sessao_govbr.py` e o ponto de partida, nao o zero);
      2. abrir o FPE-MonitConvenio-Pesquisar_Out.aspx e listar os convenios do
         convenente;
      3. de cada um, ler as competencias JA REGISTRADAS (mes, status de execucao,
         % fisico, se tem foto) — e so isso: o que o alarme precisa e a presenca
         do registro, nao o conteudo dele;
      4. upsert em `monitoramento_convenios` por (fonte, chave, competencia).

    Molde: `ingestion/sigcon_scraper.py` — credencial por municipio, rodizio com
    backoff, orcamento de tempo (`_sig_estourou`) e upsert incremental com
    SAVEPOINT."""
    raise NotImplementedError(
        f"navegacao no FPE ainda nao implementada — portal: {PORTAL} | "
        "credencial PCPRS disponivel, seguir o roteiro no docstring de "
        "_coletar_do_portal (molde: ingestion/sigcon_scraper.py)")


def _log_ingest(cur, conn, status: str, inseridos: int, nota: str | None = None):
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES ('fpe_rs', %s, %s, %s, NOW())",
            (status, inseridos, nota))
        conn.commit()
    except Exception as e:
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def ingest() -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            cur.execute("SELECT count(*) FROM municipios "
                        "WHERE active AND upper(coalesce(uf,'')) = %s", (UF,))
            if not cur.fetchone()[0]:
                # Tenant sem municipio gaucho: a fonte NAO SE APLICA. Mesmo
                # criterio do CAGEC fora de MG.
                log.info("nenhum municipio do RS neste tenant — FPE nao se aplica")
                _log_ingest(cur, conn, "success", 0, "fonte nao se aplica a este tenant")
                return 0

            creds = _credenciais(cur)
            if not creds:
                # ⭐ O CAMINHO DE HOJE. `success` com nota: credencial ausente e
                # nota, nunca alarme (regra do dono, ver cabecalho).
                log.info("sem credenciais PCPRS cadastradas — nada a coletar. "
                         "A tela de monitoramento continua dizendo 'ainda nao "
                         "conectado', que e a verdade.")
                _log_ingest(cur, conn, "success", 0, "sem credenciais PCPRS cadastradas")
                return 0

            log.info("FPE-RS: %d credencial(is) PCPRS", len(creds))
            gravados = 0
            for cred in creds:
                registros = _coletar_do_portal(cred)   # levanta enquanto pendente
                gravados += len(registros)
            _log_ingest(cur, conn, "success", gravados)
            return gravados
        except NotImplementedError as e:
            # Falha ALTA e legivel: a credencial chegou antes da navegacao. E o
            # unico caso em que este coletor grava `error` — porque aqui ha
            # trabalho NOSSO a fazer, e o watchdog deve mesmo cobrar.
            conn.rollback()
            log.error("FPE-RS: %s", e)
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        except Exception as e:
            conn.rollback()
            log.error("FPE-RS falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(cur, conn, "error", 0, str(e)[:400])
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest()
