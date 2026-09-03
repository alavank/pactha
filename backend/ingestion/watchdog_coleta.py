"""Watchdog da saude da coleta -- torna VISIVEL o que hoje e silencioso.

MOTIVACAO (incidente de 2026-07-23): um scraper do TransfereGov ficou pendurado
por 4h49m sem que ninguem soubesse. O `ingestion_log` so grava DEPOIS que a
execucao termina (sempre com finished_at preenchido), entao uma execucao travada
nao aparece em lugar nenhum -- nem no log, nem no painel. E fontes que pararam de
atualizar (o SIGCON ficou 26h sem ingerir) tambem passavam despercebidas.

Este cron roda a cada ~30 min e detecta DUAS condicoes que hoje ninguem ve:

  1. SCRAPER TRAVADO: um processo `ingestion/*.py` ou um `chrome-headless-shell`
     vivo ha mais tempo que o teto (o reaper ja mata, mas aqui a gente ALERTA
     antes/alem disso -- defesa em profundidade).
  2. FONTE PARADA: uma fonte cujo ultimo `success` no ingestion_log e mais velho
     que o esperado para a frequencia dela (ex.: sigcon deveria rodar 4x/dia;
     se o ultimo sucesso tem >18h, algo travou).

Alerta vai para o Telegram (chat em WATCHDOG_CHAT_ID ou TELEGRAM_CHAT_ID) se
configurado; senao, so loga (o log ja e melhor que o nada de hoje). Nunca falha
o processo por causa do alerta.

Anti-spam: nao repete o mesmo alerta dentro de WATCHDOG_COOLDOWN_MIN (default
180 min) -- estado guardado na tabela watchdog_alertas.

Uso: python -m ingestion.watchdog_coleta
"""
import logging
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("watchdog_coleta")

# Idade maxima esperada do ultimo SUCCESS por fonte, em horas. Fontes fora deste
# mapa nao sao cobradas por frescor (so entram na deteccao de processo travado).
# Derivado das Scheduled Tasks reais + folga.
#
# ⚠️ O QUE E NACIONAL FICA AQUI; O QUE E DE UM ESTADO FICA EM
# `FRESCOR_HORAS_POR_UF`. O catalogo era global aos tenants e constante no
# codigo — entao um tenant sem municipio de MG era cobrado por `sigcon_scraper`,
# `cagec` e `acordofes`, fontes que ali NUNCA vao rodar. Hoje o unico motivo de
# isso nao gritar e o ramo "so cobra fonte que ja tem linha no log" logo abaixo;
# bastava alguem criar a task uma vez para o alarme virar eterno. O padrao certo
# ja existia ao lado, em routers/freshness.py (_SOURCES_POR_UF + _ufs_do_tenant)
# — este modulo so tinha ficado para tras.
FRESCOR_HORAS_NACIONAL = {
    "transferegov_opendata": 30,     # 1x/dia -> 24h + folga
    "transferegov_voluntarias": 30,
    "transferegov_pac": 30,
    "fns": 30,                       # 1x/dia
    "cauc": 12,
    "acordofes": 12,
    "simec_par": 12,
    # Termos de Compromisso do SIMEC/PAR (PR #258). MESMO caso do `sismob` logo
    # abaixo — e por isso o MESMO numero: entra pendurado no
    # run_dadosabertos_cron.run_all() (que o cron do sigcon chama 4x/dia), mas o
    # proprio ingest() se auto-limita a 1x/dia
    # (SIMEC_TERMOS_MIN_INTERVAL_H=20). A cadencia REAL, portanto, e diaria, e
    # 30h = um dia + folga. Nao confunda com o irmao 'simec_par' (12h): aquele
    # roda em toda janela do run_all.
    # NACIONAL: o run() varre todo municipio ATIVO com ibge_code e manda a UF
    # como PARAMETRO do POST (estuf), sem recorte de estado — entao o lugar e
    # aqui, nunca no mapa por UF.
    # ⚠️ ISTO SO VIGIA DE VERDADE PORQUE, no mesmo PR, o coletor passou a gravar
    # ingestion_log com source='simec_termos' e status de STATUS_SUCESSO.
    # Enquanto nao houvesse linha nenhuma, o ramo "so cobra fonte que ja tem
    # linha no log" (mais abaixo) deixaria a chave dormindo.
    "simec_termos": 30,              # 1x/dia (auto-throttle no proprio ingest)
    "siconv_convenio_backfill": 30,
    "sismob": 30,                    # 1x/dia (auto-throttle no proprio ingest)
    # ⚠️ CAGEC ENTRA COM O VOCABULARIO CORRIGIDO (ver STATUS_SUCESSO abaixo).
    # Ele nunca grava 'success' — grava 'ok'/'parcial'/'erro'. Enquanto o filtro
    # era `status = 'success'`, por-lo aqui faria o watchdog acusar
    # "nunca teve sucesso" para sempre, e por isso ele ficou de fora. Era a
    # unica fonte em cron sem vigilancia nenhuma: a Freitas passou nove dias com
    # o CAGEC falhando todo dia e nada apitou.
    # 4x/dia -> 6h entre rodadas; 30h = quase cinco janelas perdidas.
    # Lote horario do TransfereGov (PR #158): fonte PROPRIA no ingestion_log,
    # separada do run() diario — um nao pode esconder a falha do outro. Roda de
    # hora em hora; 6h = seis rodadas sem 'success' (perdidas OU 'parcial'
    # persistente), que ja e problema real e nao ruido.
    "transferegov_lote": 6,
    # FUNDO A FUNDO da saude (ConsultaFNS, publico). Scheduled Task propria, 1x
    # por dia -> 30h = um dia + folga, o mesmo numero das outras diarias.
    # ⚠️ NAO confundir com o irmao `fns` logo acima: aquele e a PROPOSTA
    # (convenios_estadual, fonte='FNS'), este e o repasse ORDINARIO por bloco.
    # Sao fontes diferentes, com coletores diferentes, e uma parada nao diz nada
    # sobre a outra.
    "fns_faf": 30,
    # RADAR DE CAPTACAO (siconv_programa.zip). Pendurado no
    # run_dadosabertos_cron.run_all(), que o cron do sigcon chama 4x/dia -> 6h
    # entre rodadas. 30h = quase cinco janelas perdidas, o mesmo criterio do
    # CAGEC. ⚠️ Ele grava 'error' quando a rodada volta VAZIA (zero programa
    # aberto no Brasil nao e resultado plausivel), entao um arquivo que mudou de
    # layout aparece aqui como fonte parada, e nao como sucesso silencioso.
    "programas_captacao": 30,
    # SICONFI/Tesouro (contas entregues + CAPAG). MESMO desenho do `sismob` e do
    # `simec_termos`: o proprio ingest() se auto-limita
    # (SICONFI_MIN_INTERVAL_H=20), entao a cadencia REAL e diaria e 30h = um dia
    # + folga. NACIONAL: varre todo municipio ativo com ibge_code, sem recorte
    # de estado — o lugar e aqui, nunca no mapa por UF.
    "siconfi": 30,
    # Obras.gov.br/CIPI. Cadencia REAL de 2 dias (auto-limite de 44h no proprio
    # ingest): a varredura e cara — uma pagina a cada 8s por causa do rate
    # limit — e o CIPI muda devagar. 54h = dois dias + folga.
    "obrasgov": 54,
    # ⚠️ `portal_transparencia` NAO ENTRA AQUI de proposito. Ele e um scaffold
    # inerte (sem PORTAL_TRANSPARENCIA_API_KEY nao coleta nada) e nao tem
    # Scheduled Task. Por-lo no catalogo faria o vigia cobrar frescor de uma
    # fonte que ninguem ligou — que e exatamente a armadilha do `SISMOB_ENABLED=0`
    # documentada no INFRA.md. Entra junto com a decisao de ligar.
}

# Fontes que so existem para certas UFs. A chave e a UF do TENANT (ha municipio
# ativo daquele estado?), nao a do municipio selecionado — este vigia e do
# ambiente inteiro. Espelha routers/freshness.py::_SOURCES_POR_UF.
FRESCOR_HORAS_POR_UF = {
    "MG": {
        "sigcon_scraper": 18,        # roda 4x/dia -> 6h; 18h = 3 janelas perdidas
        "cagec": 30,                 # 4x/dia -> 6h; 30h = quase cinco janelas
        "acordofes": 12,
    },
    "ES": {"gconv_es": 30},
    "GO": {"transfvol_go": 30, "cofin_ses_go": 30, "tcm_go": 30},
    "RS": {
        "che_rs": 30,          # 3x/dia; 30h = cinco janelas perdidas
        "convenios_rs": 30,    # 1x/dia (a CAGE republica o dump esporadicamente)
        # ⚠️ 1x/dia e SO de segunda a sabado (o FPE fecha aos domingos e fora do
        # horario comercial). 54h cobre o fim de semana sem alarme falso: a
        # rodada de sabado 9h35 so tem a proxima na segunda 9h35, ~48h depois.
        "fpe_rs": 54,
        # semanal: 8 dias de folga (a fonte muda 1x/ano, apos a votacao)
        "consulta_popular_rs": 192,
        # TCE-RS/LicitaCon: o TCE republica os ZIPs por orgao com cadencia
        # semanal (o de Nova Palma foi atualizado em 31/08/2026, um domingo), e
        # a rodada e diaria com HTTP condicional — quase toda ela responde 304.
        # 30h porque o que se vigia e a RODADA, nao a mudanca da fonte: 304 e
        # sucesso e carimba o log igual.
        "tce_rs": 30,
    },
}


def _ufs_do_tenant(cur) -> set[str]:
    """UFs com municipio ATIVO. Mesma consulta de routers/freshness.py.

    ⚠️ FAIL-OPEN: erro devolve conjunto vazio, ou seja, so o catalogo nacional.
    Vigia com catalogo curto e melhor que vigia que nao roda — e o oposto do
    fail-closed que vale para as LEITURAS de deteccao."""
    try:
        cur.execute("SELECT DISTINCT upper(coalesce(uf, '')) FROM municipios "
                    "WHERE active")
        return {r[0] for r in cur.fetchall() if r[0]}
    except Exception:
        return set()


def frescor_esperado(cur) -> dict:
    """O catalogo que vale NESTE tenant: o nacional + o das UFs presentes."""
    esperado = dict(FRESCOR_HORAS_NACIONAL)
    for uf in _ufs_do_tenant(cur):
        esperado.update(FRESCOR_HORAS_POR_UF.get(uf, {}))
    return esperado

# Teto de idade (horas) da ultima coleta BOA por MUNICIPIO, por fonte do
# scraper_municipio_coleta. E o alerta que faltava: o frescor por FONTE acima
# fica verde com a fonte rodando, mesmo que municipios especificos passem dias
# sem dado (rodizio lento, portal recusando um convenente, etc.) — foi assim
# que a Freitas chegou a 21/40 municipios defasados sem nada apitar.
# sigcon 48h: meta e <24h, mas 48h evita flapping enquanto o fatiamento por
# rodada curta faz a fila baixar. transferegov 36h: ciclo real e <24h + folga.
# cagec 48h: 4 rodadas/dia cobrem a carteira em 1-2 passadas com o rodizio;
# 48h = o MESMO municipio perdeu duas janelas inteiras.
STALENESS_MUNICIPIO_H = {"sigcon": 48, "transferegov": 36, "cagec": 48}

# ⚠️ SUCESSO E SO SUCESSO. Cada coletor escreve a palavra na sua lingua:
# cauc/gconv_es/sismob/simec_par gravam 'success', o cagec_scraper grava 'ok'.
# Filtrar por 'success' literal — como estava — excluia o CAGEC inteiro, e por
# isso ele nunca pode ser vigiado. Nao vale "padronizar o coletor e pronto": o
# historico ja gravado continuaria em 'ok' e a fonte ficaria cega por mais 30h.
#
# ⚠️ E 'partial'/'parcial' FICAM DE FORA, de proposito. O 'parcial' do CAGEC foi
# inventado em 01/08/2026 exatamente para este painel NAO ficar verde: naquele
# dia o coletor gravou 'ok' sem o CRC, o frescor ficou verde e a tela do gestor
# perdeu 28 obrigacoes sem ninguem ver. Aceita-lo aqui como sucesso desfaria a
# correcao — e hoje, com o portal do Estado recusando emitir CRC, TODA rodada do
# CAGEC e 'parcial': a vigilancia nasceria desligada justo no estado degradado.
# Para as outras fontes isto tambem NAO afrouxa nada: na main o filtro ja era
# `status = 'success'`, logo o 'partial' delas nunca contou como sucesso.
STATUS_SUCESSO = ("success", "ok")

# Acima desta idade (segundos) um processo de ingestao/Chromium e considerado
# travado. Alinhado ao teto dos crons (timeout -k 30 3000 = 50 min) + margem.
IDADE_TRAVADO_S = int(os.getenv("WATCHDOG_MAX_PROC_S", "3900") or "3900")


def _db_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "").replace("?channel_binding=require", ""))


def _instancia() -> str:
    return os.getenv("INSTANCE_SLUG") or os.getenv("HOSTNAME") or "pactha"


# --------------------------------------------------------------- deteccao ---

def _fontes_paradas(cur, esperado: dict | None = None) -> list[dict]:
    """Fontes cujo ultimo SUCCESS e mais velho que o limite da fonte.

    `esperado` e o catalogo ja recortado pelas UFs do tenant (frescor_esperado).
    O default existe so para chamada avulsa em teste/console."""
    if esperado is None:
        esperado = frescor_esperado(cur)
    cur.execute("""
        SELECT source, max(finished_at) AS ultimo
        FROM ingestion_log
        WHERE lower(coalesce(status, '')) = ANY(%s)
        GROUP BY source
    """, (list(STATUS_SUCESSO),))
    achados = []
    for source, ultimo in cur.fetchall():
        limite_h = esperado.get(source)
        if limite_h is None or ultimo is None:
            continue
        cur.execute("SELECT EXTRACT(EPOCH FROM (now() - %s)) / 3600.0", (ultimo,))
        idade_h = float(cur.fetchone()[0])
        if idade_h > limite_h:
            achados.append({
                "tipo": "fonte_parada",
                "chave": source,
                "detalhe": f"ultimo sucesso ha {idade_h:.1f}h (limite {limite_h}h)",
            })
    # Fontes ESPERADAS que ja REGISTRARAM alguma execucao mas nunca um sucesso.
    # Fonte sem NENHUMA linha fica de fora: task nao configurada neste tenant
    # (lote horario e por-tenant no Coolify; SISMOB pode estar desligado) nao
    # pode virar alarme eterno — e a mesma armadilha ja documentada no INFRA.md
    # (caso SISMOB_ENABLED=0), que este ramo reproduzia para toda fonte nova.
    cur.execute("SELECT DISTINCT source FROM ingestion_log")
    com_linha = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT source FROM ingestion_log "
                "WHERE lower(coalesce(status, '')) = ANY(%s)", (list(STATUS_SUCESSO),))
    com_sucesso = {r[0] for r in cur.fetchall()}
    for source in esperado:
        if source in com_linha and source not in com_sucesso:
            achados.append({
                "tipo": "fonte_parada",
                "chave": source,
                "detalhe": "nenhum sucesso registrado ainda",
            })
    return achados


def _municipios_defasados(cur) -> list[dict]:
    """Municipios cuja ultima coleta BOA e mais velha que o teto da fonte.

    Pos-#159 o carimbo de `ultima_coleta_em` acontece TAMBEM no erro (para o
    rodizio nao sofrer starvation), entao o carimbo sozinho nao significa "dado
    novo". Dado bom = carimbo com tentativas=0 (a streak zera no 1o sucesso).
    Municipio em falha persistente (tentativas>0) e problema de credencial ou
    de portal: entra como NOTA agregada no texto do alerta, nunca como alarme
    proprio — credencial quebrada nao trava (nem polui) o jogo.

    Um alerta AGREGADO por fonte (chave = fonte), com contagem + piores casos,
    para o cooldown valer por fonte e nao virar spam por municipio.
    """
    achados = []
    # O MESMO teto do coletor (sigcon_scraper::_list_credentials). Se mudar la,
    # muda aqui — o watchdog e quem conta ao dono o que o coletor desistiu de
    # tentar, e as duas contas discordando fariam o aviso mentir.
    TETO_LOGIN = max(1, int(os.getenv("SIGCON_MAX_TENTATIVAS_LOGIN", "3") or "3"))
    for fonte, limite_h in STALENESS_MUNICIPIO_H.items():
        try:
            cur.execute("""
                SELECT m.nome,
                       EXTRACT(EPOCH FROM (now() - sc.ultima_coleta_em)) / 3600.0 AS idade_h,
                       coalesce(sc.tentativas, 0)
                FROM scraper_municipio_coleta sc
                JOIN municipios m ON m.id = sc.municipio_id
                -- so municipios ATIVOS: contrato encerrado mantem a linha do
                -- rodizio (historico), mas nao pode inflar a nota de 'falha
                -- persistente' nem virar defasado (visto 09/08: 9 ex-clientes
                -- da freitas contando como falha de credencial no log).
                WHERE sc.fonte = %s AND coalesce(m.active, true)
                ORDER BY sc.ultima_coleta_em ASC
            """, (fonte,))
            rows = cur.fetchall()
        except Exception as e:
            # Tabela do rodizio ausente (worker subiu antes da migration) nao
            # pode abortar o watchdog inteiro; rollback para nao envenenar a
            # transacao dos checks seguintes (_deve_alertar usa a mesma conexao).
            try:
                cur.connection.rollback()
            except Exception:
                pass
            logger.debug(f"  staleness {fonte} indisponivel: {e}")
            continue
        if not rows:
            continue  # fonte sem rastreio neste tenant (ex.: sem credencial SIGCON)
        defasados = []
        com_erro = 0
        for nome, idade, tent in rows:
            if tent > 0:
                com_erro += 1     # falha persistente = credencial/portal -> nota, nao alarme
            elif idade is None:
                defasados.append((nome, None))   # linha existe mas nunca coletou (legado pre-#159)
            elif idade > limite_h:
                defasados.append((nome, idade))
        if com_erro:
            logger.info(f"  {fonte}: {com_erro} municipio(s) em falha persistente "
                        f"(credencial/portal) — nota, nao alarme")
        # ⭐ CREDENCIAL RECUSADA E DESISTIDA — este SOBE de nota para ALERTA.
        #
        # A partir de 11/08/2026 o coletor PARA de tentar login depois de 3
        # recusas (ordem do dono: insistir arrisca bloqueio da conta no portal).
        # Parar e o certo — mas parar CALADO trocaria o risco de bloqueio pelo
        # risco de um municipio ficar meses sem coleta sem ninguem notar. Aqui
        # ele vira linha visivel, com o nome e o caminho de volta.
        try:
            cur.execute(
                "SELECT m.nome, coalesce(sc.tentativas,0) "
                "FROM scraper_municipio_coleta sc "
                "JOIN municipios m ON m.id = sc.municipio_id "
                "WHERE sc.fonte = %s AND coalesce(sc.tentativas,0) >= %s "
                "  AND coalesce(sc.ultimo_erro,'') ILIKE %s "
                "  AND coalesce(m.active, true) ORDER BY m.nome",
                (fonte, TETO_LOGIN, "%login%"))
            travados = cur.fetchall()
        except Exception:
            try:
                cur.connection.rollback()
            except Exception:
                pass
            travados = []
        if travados:
            nomes = ", ".join(f"{n} ({t}x)" for n, t in travados[:5])
            if len(travados) > 5:
                nomes += " ..."
            achados.append({
                "tipo": "credencial_recusada", "chave": fonte,
                "detalhe": (f"{len(travados)} municipio(s) com CREDENCIAL RECUSADA pelo portal — "
                            f"coleta SUSPENSA para nao arriscar bloqueio da conta: {nomes}. "
                            f"Corrigir a senha no Cofre religa automaticamente."),
            })
        if defasados:
            defasados.sort(key=lambda t: float("inf") if t[1] is None else t[1], reverse=True)
            piores = ", ".join(("%s (nunca)" % n if i is None else "%s (%.0fh)" % (n, i))
                               for n, i in defasados[:5])
            detalhe = f"{len(defasados)} municipio(s) sem coleta boa ha >{limite_h}h: {piores}"
            if len(defasados) > 5:
                detalhe += " ..."
            if com_erro:
                detalhe += f" | nota: {com_erro} municipio(s) em falha persistente (credencial?)"
            achados.append({"tipo": "municipio_defasado", "chave": fonte, "detalhe": detalhe})
    return achados


def _processos_travados() -> list[dict]:
    """Processos de ingestao / Chromium vivos ha mais que IDADE_TRAVADO_S.

    Le a arvore de processos do PROPRIO container (o watchdog roda como um
    `docker exec` no worker, entao ve os processos dos scrapers). Best-effort:
    se ps/pgrep faltarem, retorna vazio sem quebrar."""
    achados = []
    try:
        # etimes = segundos de vida; args = linha de comando
        out = subprocess.run(
            ["ps", "-eo", "etimes,args"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception as e:
        logger.debug(f"  ps indisponivel: {e}")
        return achados

    for linha in out.splitlines()[1:]:
        linha = linha.strip()
        if not linha:
            continue
        parte = linha.split(None, 1)
        if len(parte) != 2:
            continue
        try:
            idade = int(parte[0])
        except ValueError:
            continue
        cmd = parte[1]
        eh_ingestao = "ingestion/" in cmd or "ingestion." in cmd
        eh_chrome = "chrome-headless-shell" in cmd or "ms-playwright" in cmd
        if (eh_ingestao or eh_chrome) and idade > IDADE_TRAVADO_S:
            achados.append({
                "tipo": "processo_travado",
                "chave": cmd[:60],
                "detalhe": f"vivo ha {idade // 60} min (teto {IDADE_TRAVADO_S // 60} min)",
            })
    return achados


# --------------------------------------------------------------- anti-spam --

def _garante_tabela(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS watchdog_alertas (
            tipo         VARCHAR(30)  NOT NULL,
            chave        VARCHAR(120) NOT NULL,
            ultimo_envio TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tipo, chave)
        )
    """)


def _deve_alertar(cur, tipo: str, chave: str, cooldown_min: int) -> bool:
    """True se este alerta nao foi enviado dentro do cooldown. Registra o envio."""
    cur.execute(
        "SELECT EXTRACT(EPOCH FROM (now() - ultimo_envio)) / 60.0 "
        "FROM watchdog_alertas WHERE tipo = %s AND chave = %s",
        (tipo, chave))
    row = cur.fetchone()
    if row is not None and float(row[0]) < cooldown_min:
        return False
    cur.execute(
        "INSERT INTO watchdog_alertas (tipo, chave, ultimo_envio) VALUES (%s, %s, now()) "
        "ON CONFLICT (tipo, chave) DO UPDATE SET ultimo_envio = now()",
        (tipo, chave))
    return True


# --------------------------------------------------------------- envio ------

def _alerta(mensagem: str, cur=None, tipo: str = "", chave: str = "") -> None:
    """Entrega o alerta em TODOS os canais disponiveis. Sempre loga.

    ⚠️ ATE 11/08/2026 ESTA FUNCAO PODIA NAO ENTREGAR NADA. O Telegram foi
    desligado por decisao do dono (09/08) e o WhatsApp ainda nao existe: o
    watchdog detectava, montava a frase certa e terminava com "(Telegram nao
    configurado -- alerta so no log)". Um vigia que grita para uma sala vazia e
    pior que nenhum, porque ele passa a sensacao de que alguem esta olhando.

    Ordem dos canais, do que sempre funciona ao que depende de configuracao:
      1. LOG — sempre.
      2. BANCO (`watchdog_historico`) — vira a aba Status dos Dados. Nao depende
         de credencial nenhuma: o operador abre o sistema e ve. E o canal que
         resolve HOJE.
      3. WEBHOOK (`WATCHDOG_WEBHOOK_URL`) — um POST JSON generico. Serve para
         WhatsApp oficial, Slack, Discord, n8n, Zapier: e so preencher a env, do
         nosso lado nao muda nada.
      4. TELEGRAM — continua funcionando se um dia religarem as duas envs.
    Cada canal e best-effort e isolado: falhar num nao pode impedir os outros
    (o alerta ja e a noticia ruim; nao pode virar duas)."""
    logger.warning(f"ALERTA: {mensagem}")

    # 2. Banco — o canal que nao depende de ninguem.
    if cur is not None:
        try:
            cur.execute(
                "INSERT INTO watchdog_historico (tipo, chave, mensagem) VALUES (%s,%s,%s)",
                (tipo or "alerta", chave or "-", mensagem[:2000]))
            cur.connection.commit()
        except Exception as e:
            try:
                cur.connection.rollback()
            except Exception:
                pass
            logger.warning(f"  historico do alerta nao gravado: {str(e)[:120]}")

    # 3. Webhook generico.
    url = (os.getenv("WATCHDOG_WEBHOOK_URL") or "").strip()
    if url:
        try:
            import json as _json
            import urllib.request
            corpo = _json.dumps({"texto": mensagem, "tipo": tipo, "chave": chave,
                                 "instancia": _instancia()}).encode("utf-8")
            req = urllib.request.Request(
                url, data=corpo, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                logger.info(f"  webhook: HTTP {r.status}")
        except Exception as e:
            logger.warning(f"  falha no webhook: {str(e)[:120]}")

    # 4. Telegram (legado, so se religarem).
    chat = (os.getenv("WATCHDOG_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not chat or not token:
        return
    try:
        import asyncio
        from services.telegram import send_message
        asyncio.run(send_message(chat, mensagem))
    except Exception as e:
        logger.warning(f"  falha ao enviar Telegram: {e}")


def main() -> None:
    import psycopg2
    url = _db_url()
    if not url:
        logger.error("DATABASE_URL_SYNC ausente")
        return
    cooldown = int(os.getenv("WATCHDOG_COOLDOWN_MIN", "180") or "180")
    inst = _instancia()

    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        _garante_tabela(cur)
        conn.commit()

        # O catalogo e resolvido UMA vez por rodada, contra as UFs deste tenant:
        # cobrar frescor de fonte que nao existe aqui e como cobrar coleta de um
        # estado onde nao temos cliente.
        esperado = frescor_esperado(cur)
        logger.info("frescor esperado neste tenant: %s",
                    ", ".join(sorted(esperado)) or "(nenhuma fonte)")
        achados = (_fontes_paradas(cur, esperado) + _municipios_defasados(cur)
                   + _processos_travados())
        if not achados:
            logger.info("coleta saudavel: nenhuma fonte parada, nenhum municipio defasado, nenhum processo travado")
            return

        _ICONES = {"processo_travado": "\U0001F534", "fonte_parada": "\U0001F7E0",
                   "municipio_defasado": "\U0001F7E1",
                   # Chave: e acao de PESSOA (trocar a senha), nao de maquina.
                   "credencial_recusada": "\U0001F511"}
        _TITULOS = {"processo_travado": "processo travado", "fonte_parada": "fonte parada",
                    "municipio_defasado": "municipios defasados",
                    "credencial_recusada": "credencial recusada — coleta suspensa"}
        enviados = 0
        for a in achados:
            if _deve_alertar(cur, a["tipo"], a["chave"], cooldown):
                conn.commit()
                icone = _ICONES.get(a["tipo"], "\U0001F7E0")
                titulo = _TITULOS.get(a["tipo"], a["tipo"])
                _alerta(f"{icone} *PACTHA {inst}* — {titulo}\n`{a['chave']}`\n{a['detalhe']}",
                        cur=cur, tipo=a["tipo"], chave=a["chave"])
                enviados += 1
            else:
                logger.info(f"  (em cooldown, nao reenviado): {a['tipo']} {a['chave']}")
        logger.info(f"watchdog: {len(achados)} achado(s), {enviados} alerta(s) enviado(s)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
