"""Refresh das fontes de DADOS ABERTOS (nao precisam de login/scraping):
  - CAUC (regularidade fiscal federal - STN)
  - Acordo FES (divida da saude estadual SES-MG)
  - SISMOB (obras de saude do MS)
  - SIMEC PAR (MEC - liberacoes PNAE/PNATE/QUOTA/PDDE + dimensoes)

Os TERMOS de compromisso do SIMEC (ingestion/simec_termos.py) NAO rodam aqui:
tem Scheduled Task propria nos 4 workers (`simec-termos`, 06:10).

Sao ingestoes leves e idempotentes (TRUNCATE/UPSERT). Rodam via o cron
existente (run_sigcon_cron.py chama run_all()), entao NAO precisam de uma
Scheduled Task nova no Coolify. Precisam so de DATABASE_URL_SYNC.

Uso direto: DATABASE_URL_SYNC=... python ingestion/run_dadosabertos_cron.py
"""
import logging

log = logging.getLogger("run_dadosabertos_cron")


def run_all() -> None:
    for nome, mod in (("CAUC", "ingestion.cauc_ingest"),
                      ("Acordo FES", "ingestion.acordofes_ingest"),
                      # SISMOB: API publica do MS, sem login. Entra aqui em vez
                      # de virar Scheduled Task nova porque seriam 3 tarefas
                      # manuais no Coolify (um worker por tenant) para uma fonte
                      # que muda a cada ~60 dias. O proprio ingest() se
                      # auto-limita a 1x/dia (SISMOB_MIN_INTERVAL_H).
                      ("SISMOB", "ingestion.sismob_obras"),
                      # RADAR DE CAPTACAO: programas federais com prazo aberto.
                      # Perfil identico ao do SISMOB — dado aberto, sem login,
                      # idempotente e LEVE (um zip de 11 MB, ~20s, 17 linhas
                      # gravadas). Entra aqui em vez de virar Scheduled Task
                      # porque seriam CINCO tarefas manuais no Coolify, uma por
                      # worker, para um trabalho de vinte segundos.
                      # ⚠️ E vem DEPOIS do SISMOB de proposito: a lista roda em
                      # ordem e o `except` abaixo isola cada fonte, entao a
                      # ultima e a que menos atrapalha se algum dia engasgar.
                      ("Radar de captação", "ingestion.programas_captacao"),
                      # CADASTRO DE PARLAMENTARES (Camara, Senado, ALMG): mesmo
                      # perfil — aberto, idempotente, ~50 s, e o ingest() se
                      # auto-limita a 1x/dia (PARLAMENTARES_MIN_INTERVAL_H).
                      ("Cadastro de parlamentares", "ingestion.parlamentares_cadastro")):
        # ⚠️ SIMEC Termos NAO entra aqui — e a correcao do PR #259, que o pendurou
        # neste laco por premissa ERRADA ("nao tem Scheduled Task em nenhum
        # worker"). Tem: os QUATRO workers ja rodavam `simec-termos` as 06:10,
        # com lock PROPRIO (/tmp/simec_termos.lock) e timeout proprio (1700s).
        # Com os dois caminhos vivos a fonte coletava DUAS vezes por dia: o
        # run_all() rodava ~05:25 (o gate de 20h do ingest() ja tinha vencido
        # desde as 06:10 do dia anterior) e a task rodava de novo 45 min depois.
        # A task e o caminho melhor — nao desconta do orcamento do SIGCON.
        # `ingest()` continua existindo como porta de entrada alternativa (e como
        # gate por env), so nao e mais chamado daqui.
        try:
            m = __import__(mod, fromlist=["ingest"])
            n = m.ingest()
            log.info(f"[dados abertos] {nome}: {n} registros.")
        except Exception as e:  # nunca derruba o cron por causa de uma fonte
            log.warning(f"[dados abertos] {nome} falhou: {e}")
    # SIMEC PAR (MEC) — nacional, sem login. Entry e run() (nao ingest()).
    # Estava SEM cron -> ficava meses velho; agora entra no ciclo de 6h.
    try:
        from ingestion.simec_par import run as _simec_run
        _simec_run()
        log.info("[dados abertos] SIMEC PAR: ok")
    except Exception as e:
        log.warning(f"[dados abertos] SIMEC PAR falhou: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_all()
