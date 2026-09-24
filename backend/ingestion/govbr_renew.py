"""Auto-RECONEXAO da sessao gov.br/SICONV — SEM login, SEM reCAPTCHA.

Ideia: ha DUAS camadas de sessao:
  - SSO gov.br (acesso.gov.br)  -> cookies Govbrid/Session_Gov_Br_Prod/...
  - SICONV/JEE (discricionarias) -> JSESSIONID (derivado do SSO via SAML)

O keep-alive antigo (httpx) so resetava o JEE e NAO conseguia refazer o SAML
(precisa de JS). Aqui, num browser real (Playwright), navegamos a entrada do
discricionarias: isso dispara o SAML, que -> bate no SSO (mantendo o SSO QUENTE)
-> se o SSO ainda e valido, volta com nova assertion -> NOVO JSESSIONID JEE.
Ou seja, RE-DERIVAMOS a sessao a cada ciclo, sem login. Salvamos os cookies
frescos no Cofre. Enquanto o SSO viver, a conexao se mantem sozinha.

So quando o SSO expira de vez (teto duro do gov.br) e que cai em /idp/ e ai
retorna 'needs_recapture' — NAO tentamos login (tem reCAPTCHA, nao automatizamos).

Roda como cron (Dockerfile.scraper, Playwright) a cada ~10min.
Uso: COFRE_KEY=... DATABASE_URL_SYNC=... python ingestion/govbr_renew.py
"""
from __future__ import annotations
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from services import crypto

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("govbr_renew")

# Entrada autenticada do discricionarias — dispara o SAML (round-trip no SSO).
ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
         "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do")

# Entrada do /private/ das mandatarias (projeto-basico). E um SP gov.br SEPARADO:
# o SSO re-derivado nao o cobre, entao ele expira por INATIVIDADE se ninguem o
# consulta. A captura da extensao estabelece a sessao dele; para NAO precisar de
# re-captura, o keepalive abaixo navega esta pagina com frequencia (< timeout de
# idle do JEE, ~20-30min) e re-salva os cookies -> mantem o /private/ vivo
# "sempre consultando". Os cookies mandatarias entram no jar (filtro pega
# 'transferegov'). Se ja tiver caido no login, navegar aqui NAO revive (login tem
# reCAPTCHA) -> vira 'private_dead' e o monitor de frescor acusa.
PRIVATE_ENTRY = ("https://mandatarias.transferegov.sistema.gov.br/"
                 "projeto-basico/private/index.jsf")

# Modulo "Execucao Convenente > Processo de Execucao" (ListarLicitacoes). Assim
# como o /private/, e um SP SAML SEPARADO: a sessao dele expira por inatividade e
# o govbr-renew (que so reaquece o discricionarias) NAO a mantinha — por isso a
# situacao da licitacao (processo_execucao) parava de ser capturada horas apos a
# captura. Navegar esta URL no keepalive reseta o idle desse SP e re-salva os
# cookies -> mantem `TgHttpEnrich.processo_execucao_lista` funcionando. Se ja
# caiu no login (idp), navegar aqui NAO revive (precisa re-captura), igual ao
# /private/.
EXEC_ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/"
              "voluntarias/execucao/ListarLicitacoes/ListarLicitacoes.do?destino=ListarLicitacoes")

# Modulo "Execucao Concedente > Notas de Empenho". ⚠️ NAO E O MESMO SP DO
# `EXEC_ENTRY` ACIMA, ao contrario do que o comentario dele supunha: ele mora sob
# /voluntarias/PRESTACAO/ (e nao /execucao/) e tem idle PROPRIO.
#
# MEDIDO EM PRODUCAO (Freitas, 25/08/2026), e e o que separa os dois:
#   keepalive .......... execucao=vivo, de 10 em 10 minutos, sem falhar
#   projeto basico ..... 0 falhas   (mora em /execucao/ -> coberto)
#   notas de empenho ... 115 falhas (mora em /prestacao/ -> NUNCA tocado)
# Ou seja: a sessao que o keepalive mantinha viva nao era a que as NEs usam, e
# elas morriam por inatividade algumas horas depois de cada captura — com o log
# dizendo "sessao do SP fria?", que estava certo mas apontava para o SP errado.
#
# Navegar esta URL reseta o idle DESSE SP e re-salva os cookies. Se ja caiu no
# login (idp), navegar aqui NAO revive — precisa re-captura, igual aos outros.
PRESTACAO_ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/"
                   "voluntarias/prestacao/_proposta/empenho/"
                   "listarEmpenhosNovoSiafi.jsf?destino=ManterEmpenhoNovoSiafi")

# Subdominios p/ repovoar JSESSIONIDs frescos + manter o SSO quente.
SUBDOMINIOS = [
    ENTRY,
    "https://parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home",
    "https://cadastro.transferegov.sistema.gov.br/ep-cadastro-web/home",
    PRIVATE_ENTRY,
]


def _sync_url() -> str:
    return (os.getenv("DATABASE_URL_SYNC", "")
            .replace("&channel_binding=require", "")
            .replace("?channel_binding=require", ""))


def _load_govbr() -> tuple[int | None, list | None]:
    """(cofre_id, cookies) da sessao govbr mais recente com cookies."""
    cofre_id, cookies, _visto = _load_govbr_v()
    return cofre_id, cookies


def _load_govbr_v() -> tuple[int | None, list | None, object]:
    """(cofre_id, cookies, updated_at). O `updated_at` e a VERSAO lida: quem
    grava de volta passa esse valor a `_save_cookies`, que so grava se a linha
    continuar nessa versao. Sem isso, uma rodada que leu o jar velho as 10:00:00
    gravava as 10:00:20 por cima de uma RECAPTURA feita as 10:00:10 — a captura
    nova era engolida em silencio (`updated_at` tem onupdate no modelo, entao a
    captura pela API sempre muda a versao)."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        # ⚠️ `municipio_id IS NULL` SEPARA A SESSAO DA CREDENCIAL, e sem isso o
        # renovador le a linha errada. A sessao gov.br e do OPERADOR e vale
        # cross-mun, entao a extensao a grava em escopo de instancia; uma linha
        # COM municipio e a credencial daquela prefeitura (CPF + senha).
        #
        # Em 02/09 isso apareceu em producao no freitas: a extensao antiga
        # mandava `municipio_id`, e a captura — que casa por
        # (automation_key, municipio_id) — gravou o blob de sessao POR CIMA da
        # senha da credencial do IBGE 3103900. Aquela linha passou a satisfazer
        # `length(senha_hash) > 1000` e, como o keepalive re-salva nela a cada
        # ciclo, o `updated_at` dela ficava sempre a frente: a captura nova era
        # gravada e IGNORADA. O sintoma so apareceria na proxima recuperacao —
        # recapturar e continuar sem sessao, sem erro em lugar nenhum.
        cur.execute("SELECT id, senha_hash, updated_at FROM cofre_senhas "
                    "WHERE automation_key='govbr' AND length(senha_hash) > 1000 "
                    "AND municipio_id IS NULL "
                    "ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return None, None, None
        dec = crypto.decrypt(row[1])
        if not dec or not dec.startswith("{"):
            return None, None, None
        return row[0], json.loads(dec).get("cookies", []), row[2]
    except Exception as e:
        log.warning(f"_load_govbr: {e}")
        return None, None, None


def _to_pw_cookies(cookies: list) -> list:
    out = []
    for c in cookies:
        n, v = c.get("name"), c.get("value")
        if not n or v is None:
            continue
        ck = {"name": n, "value": v, "path": c.get("path") or "/",
              "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly"))}
        dom = c.get("domain")
        if dom:
            ck["domain"] = dom
        ss = c.get("sameSite")
        if ss:
            ck["sameSite"] = {"no_restriction": "None", "lax": "Lax", "strict": "Strict",
                              "None": "None", "Lax": "Lax", "Strict": "Strict"}.get(ss, "Lax")
        exp = c.get("expirationDate") or c.get("expires")
        if exp and float(exp) > 0:
            try:
                ck["expires"] = float(exp)
            except (TypeError, ValueError):
                pass
        out.append(ck)
    return out


def _from_pw_cookies(cookies: list) -> list:
    """Converte cookies do Playwright p/ o formato de storage do Cofre."""
    out = []
    for c in cookies:
        out.append({
            "name": c.get("name"), "value": c.get("value"),
            "domain": c.get("domain"), "path": c.get("path") or "/",
            "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly")),
            "sameSite": c.get("sameSite"),
            "expirationDate": c.get("expires") if c.get("expires", -1) and c.get("expires", -1) > 0 else None,
        })
    return out


SOURCE_SESSAO = "govbr_sessao"
# MUDA-OU-VENCE. O keepalive roda de 10 em 10 minutos = 144 linhas por dia. O
# painel de ingestao mostra as ~80 linhas mais recentes; 144/dia apagariam o
# historico de TODAS as outras fontes. Grava so quando o estado MUDA ou quando a
# ultima linha ja venceu — em regime saudavel, ~24 linhas/dia.
HEARTBEAT_MIN = int(os.getenv("GOVBR_LOG_HEARTBEAT_MIN", "50") or "50")


def _status_sessao(private_ok: bool, exec_ok: bool, prest_ok: bool) -> tuple:
    """(status, vivos, frase) no vocabulario que o frescor JA entende.

    ⚠️ 'success' | 'parcial' | 'erro', e nao 'alive'/'vivo'. Inventar vocabulario
    aqui obrigaria a mexer no `freshness` e no `watchdog` — o custo de um nome
    bonito seria dois lugares a mais para errar.

    ⚠️ OS TRES SPs CONTAM SEPARADO. Foi exatamente por `execucao` e `prestacao`
    aparecerem como um so que as NEs morriam em silencio com o keepalive
    dizendo "execucao=vivo"."""
    vivos = sum((bool(private_ok), bool(exec_ok), bool(prest_ok)))
    frase = (f"private={'vivo' if private_ok else 'CAIU'}, "
             f"execucao={'vivo' if exec_ok else 'CAIU'}, "
             f"prestacao={'vivo' if prest_ok else 'CAIU'}")
    if vivos == 3:
        return "success", vivos, frase
    if vivos == 0:
        return "erro", vivos, frase
    return "parcial", vivos, frase


def _grava_estado(source: str, status: str, n: int, erro: str | None) -> None:
    """Uma linha em `ingestion_log`, no regime MUDA-OU-VENCE (ver HEARTBEAT_MIN).

    ⚠️ POR QUE ISTO PRECISOU EXISTIR: a saude da sessao so vivia no LOG DO
    CONTAINER, que e efemero. "Ha quantas horas a sessao esta viva ou morta" era
    uma pergunta sem resposta possivel no banco — e a auditoria mediu a sessao
    morta 297,5h de 720h (41%) sem que nada no produto dissesse isso.

    ⚠️ `cofre_senhas.updated_at` NAO serve de sinal de saude: ate 21/09/2026 o
    keepalive re-salvava os cookies mesmo com tudo caido no idp, e o carimbo
    subia com a sessao morta. Hoje ele so grava com prova de vida
    (`tem_prova_de_vida`), mas o carimbo continua sendo a VERSAO do jar
    (`_load_govbr_v`/`_save_cookies`), nao um atestado — a saude mora aqui.

    Best-effort de verdade: qualquer falha aqui e engolida. Este e um registro de
    OBSERVACAO — derrubar o keepalive ou a renovacao por causa dele seria trocar a
    coleta pela contabilidade da coleta."""
    try:
        conn = psycopg2.connect(_sync_url())
        with conn, conn.cursor() as cur:
            cur.execute(
                "SELECT status, finished_at FROM ingestion_log "
                "WHERE source = %s ORDER BY id DESC LIMIT 1", (source,))
            ult = cur.fetchone()
            if ult and ult[0] == status and ult[1] is not None:
                cur.execute("SELECT EXTRACT(epoch FROM (now() - %s)) / 60", (ult[1],))
                if (cur.fetchone()[0] or 0) < HEARTBEAT_MIN:
                    conn.close()
                    return          # mesmo estado e ainda dentro da janela
            cur.execute(
                "INSERT INTO ingestion_log (source, status, records_inserted, "
                "error_message, started_at, finished_at) "
                "VALUES (%s, %s, %s, %s, NOW(), NOW())",
                (source, status, n, erro if status != "success" else None))
        conn.close()
    except Exception as e:
        log.info(f"registro de {source} nao gravado ({str(e)[:70]}) — coleta segue")


def _registra_sessao(private_ok: bool, exec_ok: bool, prest_ok: bool) -> None:
    """Saude dos tres SPs que o keepalive navega (`govbr_sessao`)."""
    status, vivos, frase = _status_sessao(private_ok, exec_ok, prest_ok)
    _grava_estado(SOURCE_SESSAO, status, vivos, frase)


# O LOGIN gov.br em si (SSO), e nao os SPs de cima. ⚠️ Sao sinais DIFERENTES, e
# foi confundi-los que deixou os seis tenants 2 dias sem sessao sem ninguem saber
# (14-17/09/2026): o `govbr_sessao` mede o /private/ das mandatarias, que vive
# caido MESMO com o SSO bom (medido na Freitas de 06 a 12/09: CAIU em 100% das
# rodadas), entao ninguem podia alarmar por ele. Quem sabe que o login expirou e
# o renew() — e ate aqui ele so dizia isso no log efemero do container.
# Quem le esta fonte: watchdog_coleta._sessao_govbr_caida (o nome e repetido la
# de proposito, para o vigia nao importar Playwright/crypto; teste garante).
SOURCE_SSO = "govbr_sso"
FRASE_SSO_EXPIROU = "SSO gov.br expirou — recapturar pela extensao do Chrome"
FRASE_SEM_SESSAO = "nenhuma sessao gov.br no Cofre"


def _registra_sso(resultado: str) -> None:
    """'reconnected' vira success; o resto vira erro com a frase que diz o que fazer.

    `no_session` tem frase PROPRIA: tenant que nunca capturou sessao nao e sessao
    caida, e o vigia nao pode cobrar recaptura de quem nunca capturou."""
    if resultado == "inconclusivo":
        # ⚠️ FALHA DE REDE NAO E VEREDITO. Esta fonte LIGA e DESLIGA a guarda do
        # endpoint de captura (`session_capture.sessao_esta_viva`): gravar "SSO
        # expirou" por causa de um timeout reabriria a porta para o jar deslogado
        # e acenderia o alarme de recaptura a toa. Sem medicao, nao se grava nada.
        return
    if resultado == "reconnected":
        _grava_estado(SOURCE_SSO, "success", 1, None)
    elif resultado == "no_session":
        _grava_estado(SOURCE_SSO, "erro", 0, FRASE_SEM_SESSAO)
    else:
        _grava_estado(SOURCE_SSO, "erro", 0, FRASE_SSO_EXPIROU)


# A RODADA do renew, separada do veredito do login. `inconclusivo` nao escreve em
# `govbr_sso` (ver `_registra_sso`) — e sem ISTO ele seria mudo: se o portal mudar
# o layout (sumir o "Sair"), toda rodada passa a ser inconclusiva e nada diria
# isso em lugar nenhum. 'partial' enquanto a ultima rodada nao soube julgar; volta
# a 'success' sozinho na primeira que souber. Nao liga nem desliga guarda nenhuma.
SOURCE_RODADA = "govbr_renew"


def _registra_rodada(resultado: str) -> None:
    if resultado == "inconclusivo":
        _grava_estado(SOURCE_RODADA, "partial", 0,
                      "rodada inconclusiva: o portal nao devolveu pagina reconhecivel (nem logado, "
                      "nem tela de login) — se persistir por horas, o layout do TransfereGov mudou")
    else:
        _grava_estado(SOURCE_RODADA, "success", 1, None)


# A SONDA DO SSO — a pergunta que o renew de hora em hora NAO fazia.
#
# ⭐ POR QUE (23/09/2026): a sessao caiu ~24h depois do login SEM nenhuma captura
# por cima (audit_log dos seis). O keepalive mantem o JSESSIONID do SP vivo de 10
# em 10 min, entao o renew navega a entrada JA autenticado e NUNCA passa pelo
# IdP/SSO — mede o SP, nao o login. Quando o SSO do gov.br morre, ninguem ve ate o
# SP tambem morrer. Esta sonda navega a entrada SEM os cookies do SP (so IdP +
# gov.br): forca o SAML e responde "o IdP/SSO ainda re-deriva sessao?". Fonte
# `govbr_sso_roundtrip`: success = re-derivou; erro = caiu no login (o SSO ja
# morreu, o SP e um zumbi que vai cair); partial = pagina irreconhecivel.
# ⚠️ SO MEDE. O contexto e descartado; o jar em uso nao e tocado. Se um dia a
# vida do SSO se mostrar por OCIOSIDADE (e nao teto), esta rodada tambem a renova.
SOURCE_SSO_RT = "govbr_sso_roundtrip"
_SP_HOSTS = ("discricionarias.", "mandatarias.", "fiscalizacao.", "transfere.", "parcerias.",
             "cadastro.", "especiais.", "fundos.", "ted.")


def cookies_para_roundtrip(cookies: list) -> list:
    """O jar SEM os cookies dos SPs (JSESSIONID de discricionarias, mandatarias...):
    ficam os do IdP (`idp.transferegov...`), do gov.br (`sso.acesso.gov.br`, `.gov.br`)
    e os do dominio-pai `transferegov.sistema.gov.br`. Sem sessao no SP, a entrada
    obriga o SAML — que e o que se quer medir."""
    out = []
    for c in cookies or []:
        dom = (c.get("domain") or "").lstrip(".").lower()
        if any(dom.startswith(h) for h in _SP_HOSTS):
            continue
        out.append(c)
    return out


def sonda_ligada() -> bool:
    """Kill-switch sem deploy: GOVBR_SONDA_SSO=0 no env do worker desliga a sonda.
    Ela cria, a cada hora, uma sessao a mais do SP para o mesmo CPF (descartada).
    Que o SP aceite varias sessoes do mesmo usuario e FATO ja medido em producao —
    os sete tenants re-derivam cada um o seu JSESSIONID do mesmo login e convivem
    — mas se um dia o portal mudar isso, desliga-se aqui."""
    return (os.getenv("GOVBR_SONDA_SSO", "1") or "1").strip() not in ("0", "false", "no")


def _sp_jsessionid(cookies: list) -> str | None:
    for c in cookies or []:
        if c.get("name") == "JSESSIONID" and "discricionarias" in (c.get("domain") or ""):
            return c.get("value")
    return None


async def sso_roundtrip(br, cookies: list) -> tuple[str, str]:
    """('logado' | 'login' | 'nao_sei', detalhe). CONTEXTO proprio no navegador que o
    renew ja abriu (jar isolado), fechado no fim — nao um segundo Chromium: o host
    tem 2 vCPU e dois navegadores ao mesmo tempo ja colidiram antes.

    ⚠️ ESPERA ADAPTATIVA, nao 8s fixos: a sonda e a unica rodada que SEMPRE faz o
    salto SAML inteiro (SP -> idp -> talvez gov.br -> SP). Julgar com a URL ainda
    em `/idp/` ou em `sso.acesso` EM TRANSITO daria 'login' falso — e um falso
    'erro' aqui calibra o teto errado. Poll de 2s ate 24s; para ao autenticar ou
    quando a URL fica parada por 6s (pagina final, seja ela qual for)."""
    jar = cookies_para_roundtrip(cookies)
    ctx = await br.new_context(ignore_https_errors=True,
                               user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                                          "Chrome/131.0.0.0 Safari/537.36")
    try:
        n = await _add_cookies_tolerante(ctx, jar)
        if n == 0:
            # Navegador anonimo nao mede o SSO: cairia no login e diria "venceu".
            return "nao_sei", "nenhum cookie de IdP/SSO no jar — sonda sem o que medir"
        page = await ctx.new_page()
        resp = None
        try:
            resp = await page.goto(ENTRY, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            return "nao_sei", f"navegacao nao completou ({str(e)[:60]})"
        v, body, parada, passos = "nao_sei", "", 0, 0
        url_ant = None
        for passos in range(1, 13):
            await page.wait_for_timeout(2000)
            try:
                body = await page.evaluate("() => document.body.innerText")
            except Exception:
                body = ""
            v = veredito_login(page.url, body, getattr(resp, "status", None))
            if v == "logado":
                break
            parada = parada + 1 if page.url == url_ant else 0
            url_ant = page.url
            if parada >= 3:
                break
        if v == "login" and not _eh_tela_de_login("", body):
            # 'login' so com PROVA NO CORPO (Identifique-se / Acesso restrito). URL em
            # idp/sso sem marcador no corpo = SAML em transito ou pagina de erro do
            # IdP (o `http_status` so cobre a 1a resposta) — nao e veredito.
            v = "nao_sei"
        host = ""
        try:
            from urllib.parse import urlparse
            host = urlparse(page.url or "").hostname or ""
        except Exception:
            pass
        # Prova de que a sonda abriu uma sessao PROPRIA no SP (e nao reusou a em uso).
        sp_novo = "?"
        try:
            sp = _sp_jsessionid(await ctx.cookies())
            sp_novo = "sim" if (sp and sp != _sp_jsessionid(cookies)) else "nao"
        except Exception:
            pass
        return v, (f"{n} cookie(s) de IdP/SSO; terminou em {host or '?'} apos {passos * 2}s; "
                   f"SP proprio={sp_novo}")
    finally:
        try:
            await ctx.close()
        except Exception:
            pass


def _registra_roundtrip(veredito: str, detalhe: str) -> None:
    if veredito == "logado":
        _grava_estado(SOURCE_SSO_RT, "success", 1, None)
    elif veredito == "login":
        _grava_estado(SOURCE_SSO_RT, "erro", 0,
                      f"IdP/SSO gov.br NAO re-deriva sessao sem o cookie do SP ({detalhe}) — o login "
                      "ja venceu no gov.br; o SP so esta vivo pelo keepalive e vai cair")
    else:
        _grava_estado(SOURCE_SSO_RT, "partial", 0, f"sonda inconclusiva ({detalhe})")


# A identidade da sessao SSO ("login novo ou a mesma sessao?") mora no modulo
# puro, porque o endpoint de captura tambem precisa dela (captura direta).
from services.sessao_govbr import comparar_sessao_sso, mesma_sessao_sso  # noqa: E402,F401


def _copia_observacao(de_id: int, para_id: int) -> None:
    """Na promocao, a hora do LOGIN passa a ser a da candidata: e da `observacao`
    ("[SESSION] capturado em ...") que o vigia e a rota de saude tiram a hora do
    login para prever o vencimento. Sem isto a promocao trocava o jar e deixava a
    hora do login antigo — e o aviso de vencimento sairia na hora errada."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        with conn, conn.cursor() as cur:
            cur.execute("UPDATE cofre_senhas SET observacao = (SELECT observacao FROM cofre_senhas "
                        "WHERE id=%s) WHERE id=%s AND (SELECT observacao FROM cofre_senhas WHERE id=%s) "
                        "LIKE '[SESSION] capturado em %%'", (de_id, para_id, de_id))
        conn.close()
    except Exception as e:
        log.info(f"candidata: observacao nao copiada ({str(e)[:70]})")


# O destino de cada captura CANDIDATA, no banco e nao so no log do container: a
# promocao troca o jar inteiro da sessao em uso, e "a sessao morreu depois de uma
# promocao?" precisa ter resposta. 'partial' (e nao 'erro') na recusa: a sessao
# em uso esta BEM — o recado e "o Chrome do dono esta mandando jar sem login".
SOURCE_CANDIDATA = "govbr_candidata"


def _registra_candidata(veredito: str, motivo: str | None) -> None:
    if veredito == "promovida":
        _grava_estado(SOURCE_CANDIDATA, "success", 1, None)
    else:
        _grava_estado(SOURCE_CANDIDATA, "partial", 0,
                      f"captura candidata RECUSADA: {motivo or 'nao autenticou'}")


def _save_cookies(cofre_id: int, cookies_pw: list, visto_em=None) -> bool:
    """Sobrescreve os cookies da sessao govbr no Cofre (mesma linha id).

    `visto_em` = o `updated_at` que esta rodada LEU (`_load_govbr_v`). Com ele,
    so grava se a linha continua nessa versao; se alguem gravou no meio (a
    RECAPTURA do dono, tipicamente), devolve False e o jar desta rodada e
    descartado — ele nasceu do jar velho e nao pode engolir o novo. Sem
    `visto_em` (promocao de candidata) grava incondicional."""
    payload = {
        "format": "cookies_full",
        "cookies": _from_pw_cookies(cookies_pw),
        "url": "https://discricionarias.transferegov.sistema.gov.br/voluntarias/",
        "domain": "discricionarias.transferegov.sistema.gov.br",
    }
    enc = crypto.encrypt(json.dumps(payload))
    conn = psycopg2.connect(_sync_url(), connect_timeout=10)
    cur = conn.cursor()
    if visto_em is None:
        cur.execute("UPDATE cofre_senhas SET senha_hash=%s, updated_at=NOW() WHERE id=%s",
                    (enc, cofre_id))
    else:
        cur.execute("UPDATE cofre_senhas SET senha_hash=%s, updated_at=NOW() "
                    "WHERE id=%s AND updated_at=%s", (enc, cofre_id, visto_em))
    gravou = (cur.rowcount or 0) > 0
    conn.commit(); cur.close(); conn.close()
    if not gravou:
        log.info("jar desta rodada DESCARTADO: a linha do Cofre mudou no meio "
                 "(captura nova?) — a versao mais nova fica")
    return gravou


def tem_prova_de_vida(entry_ok: bool, private_ok: bool, exec_ok: bool, prest_ok: bool) -> bool:
    """O keepalive PODE regravar o jar? So com prova de vida: a entrada do
    discricionarias autenticou OU ao menos um SP respondeu sem cair no login.

    Ate 21/09/2026 o jar era regravado SEMPRE — inclusive com as quatro
    navegacoes na tela de login, quando o que o navegador tem na mao e o jar DA
    TELA DE LOGIN. Numa oscilacao do portal isso trocava a sessao boa pela
    anonima. Com tudo caido nao ha nada no navegador que valha mais que o Cofre."""
    return bool(entry_ok or private_ok or exec_ok or prest_ok)


async def _add_cookies_tolerante(ctx, cookies: list) -> int:
    """Carrega o jar no contexto e devolve QUANTOS cookies entraram.

    ⚠️ `add_cookies` e ATOMICO: um cookie malformado (sameSite estranho, dominio
    vazio) derruba o lote inteiro, o navegador sobe ANONIMO, cai na tela de
    login — e o keepalive antigo gravava esse jar anonimo por cima da sessao
    boa. Aqui o lote que falha e refeito cookie a cookie, pulando so o ruim.
    Zero carregados = nao ha o que testar: quem chama aborta SEM gravar."""
    pw = _to_pw_cookies(cookies)
    if not pw:
        return 0
    try:
        await ctx.add_cookies(pw)
        return len(pw)
    except Exception as e:
        log.warning(f"add_cookies em lote falhou ({str(e)[:80]}) — tentando um a um")
    n = 0
    for c in pw:
        try:
            await ctx.add_cookies([c])
            n += 1
        except Exception:
            pass
    log.info(f"add_cookies um a um: {n} de {len(pw)} carregados")
    return n


# =====================================================================
# CANDIDATA — a captura que chegou com a sessao VIVA (ver session_capture.py)
# =====================================================================
CHAVE_CANDIDATA = "govbr_candidata"   # o mesmo nome de routers/session_capture.py
# Candidata que nao se consegue TESTAR (portal fora, pagina irreconhecivel) espera
# a proxima rodada — mas nao para sempre: depois disto e descartada com motivo
# proprio. Fila presa tambem e defeito, e um jar de 6h ja nao e "login novo".
CANDIDATA_MAX_H = 6


def _candidata_velha(versao) -> bool:
    from datetime import datetime, timedelta, timezone
    if not isinstance(versao, datetime):
        return False
    if versao.tzinfo is None:
        versao = versao.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - versao > timedelta(hours=CANDIDATA_MAX_H)


def _load_candidata() -> tuple[int | None, list | None, object]:
    """(id, cookies, updated_at) da captura candidata, ou (None, None, None). Sem
    piso de tamanho: um jar deslogado e pequeno, e e justamente ele que precisa
    ser lido para ser recusado e sair da fila. O `updated_at` e a VERSAO testada:
    o endpoint ATUALIZA esta mesma linha a cada captura, e apagar por id apagaria
    junto a captura nova que chegou durante o teste (ver `_encerra_candidata`)."""
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        cur = conn.cursor()
        cur.execute("SELECT id, senha_hash, updated_at FROM cofre_senhas WHERE automation_key=%s "
                    "AND municipio_id IS NULL ORDER BY updated_at DESC LIMIT 1",
                    (CHAVE_CANDIDATA,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return None, None, None
        try:
            dec = crypto.decrypt(row[1]) or ""
            cookies = json.loads(dec).get("cookies", []) if dec.startswith("{") else []
        except Exception:
            cookies = []
        return row[0], cookies, row[2]
    except Exception as e:
        log.warning(f"_load_candidata: {e}")
        return None, None, None


def _id_da_sessao_em_uso() -> int | None:
    """id da linha 'govbr' de instancia, SEM o piso de tamanho e SEM decifrar.
    ⚠️ LEVANTA em erro, de proposito: `_load_govbr_v` devolve None tanto para "nao
    existe" quanto para "nao consegui ler" (timeout, decrypt), e tratar o segundo
    como o primeiro fazia a promocao RENOMEAR a candidata para 'govbr' com a linha
    principal existindo — duas linhas 'govbr', e o POST de captura
    (`scalar_one_or_none`) passava a responder 500 para sempre."""
    conn = psycopg2.connect(_sync_url(), connect_timeout=10)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM cofre_senhas WHERE automation_key='govbr' "
                    "AND municipio_id IS NULL ORDER BY updated_at DESC LIMIT 1")
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        conn.close()


def _encerra_candidata(cand_id: int, veredito: str, principal_id: int | None,
                       versao=None) -> bool:
    """Apaga a candidata TESTADA e deixa o veredito na `observacao` da sessao em
    uso — o log do container e efemero, e "a captura de ontem foi recusada?"
    precisa ter resposta no banco. `updated_at` da principal NAO e tocado (e a
    versao do jar).

    `versao` = o `updated_at` da candidata que foi lida. Se a linha mudou durante
    o teste (chegou captura nova — a "Captura completa" do dono, tipicamente),
    NADA e apagado nem anotado: a nova fica para a proxima rodada. Devolve se
    apagou."""
    import re as _re
    from datetime import datetime, timezone
    try:
        conn = psycopg2.connect(_sync_url(), connect_timeout=10)
        with conn, conn.cursor() as cur:
            if versao is None:
                cur.execute("DELETE FROM cofre_senhas WHERE id=%s AND automation_key=%s",
                            (cand_id, CHAVE_CANDIDATA))
            else:
                cur.execute("DELETE FROM cofre_senhas WHERE id=%s AND automation_key=%s "
                            "AND updated_at=%s", (cand_id, CHAVE_CANDIDATA, versao))
            if (cur.rowcount or 0) == 0:
                log.info("candidata mudou durante o teste (captura nova) — fica para a proxima rodada")
                conn.close()
                return False
            if versao is not None:
                # DUPLICATAS MAIS ANTIGAS vao junto. O endpoint faz SELECT+INSERT sem
                # trava e a API sobe com 2 workers: dois POSTs simultaneos (a extensao
                # manda varios por login) criam DUAS linhas candidatas, e a mais velha
                # seria promovida DEPOIS, por cima do jar mais completo. ⚠️ Em DELETE
                # separado: o rowcount de cima tem de continuar significando "apaguei
                # a linha TESTADA". Captura que chegou durante o teste tem updated_at
                # maior e fica.
                cur.execute("DELETE FROM cofre_senhas WHERE automation_key=%s AND municipio_id IS NULL "
                            "AND id<>%s AND updated_at<=%s", (CHAVE_CANDIDATA, cand_id, versao))
            if principal_id:
                cur.execute("SELECT observacao FROM cofre_senhas WHERE id=%s", (principal_id,))
                row = cur.fetchone()
                base = _re.sub(r"\s*\|\| \[CANDIDATA\].*$", "", (row[0] if row else "") or "", flags=_re.S)
                quando = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                cur.execute("UPDATE cofre_senhas SET observacao=%s WHERE id=%s",
                            (f"{base} || [CANDIDATA] {veredito} em {quando}"[:2000], principal_id))
        conn.close()
        return True
    except Exception as e:
        log.info(f"candidata: veredito nao registrado ({str(e)[:70]})")
        return False


async def processa_candidata() -> str:
    """Testa a captura candidata e so a PROMOVE se ela autenticar.

    Retorna 'sem_candidata' | 'promovida' | 'recusada' | 'inconclusivo'.

    E a outra metade da guarda de `session_capture.py`: la a captura que chega
    com a sessao viva e guardada a parte; aqui ela e USADA — navega a entrada do
    discricionarias com o jar dela. Autenticou: e um login bom (em geral mais
    novo que o nosso) e vira a sessao em uso. Caiu na tela de login: era o
    Chrome do dono deslogado, e a sessao viva segue intocada.

    ⚠️ FALHA NAO E VEREDITO. Navegacao que nem completou, banco que nao
    respondeu, linha que mudou durante o teste: a candidata FICA para a proxima
    rodada. Recusar por timeout jogaria fora um login bom; promover sem saber se
    a linha principal existe criaria uma segunda linha 'govbr'."""
    cand_id, cookies, versao = _load_candidata()
    if cand_id is None:
        return "sem_candidata"
    try:
        principal_id = _id_da_sessao_em_uso()
    except Exception as e:
        log.warning(f"candidata: nao consegui ler a sessao em uso ({str(e)[:80]}) — proxima rodada")
        return "inconclusivo"
    # O jar em uso ORIGINAL (antes de qualquer gravacao desta rodada): e contra ele
    # que se decide se a candidata e login novo (`mesma_sessao_sso`).
    try:
        _, em_uso_cookies, _ = _load_govbr_v()
    except Exception:
        em_uso_cookies = None
    if not cookies:
        _encerra_candidata(cand_id, "recusada (jar vazio/ilegivel)", principal_id, versao)
        _registra_candidata("recusada", "jar vazio ou ilegivel")
        return "recusada"
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True,
                                     args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await br.new_context(ignore_https_errors=True,
                                   user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                                              "Chrome/131.0.0.0 Safari/537.36")
        if await _add_cookies_tolerante(ctx, cookies) == 0:
            await br.close()
            _encerra_candidata(cand_id, "recusada (nenhum cookie carregavel)", principal_id, versao)
            _registra_candidata("recusada", "nenhum cookie carregavel")
            return "recusada"
        page = await ctx.new_page()
        resp = None
        try:
            resp = await page.goto(ENTRY, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            log.warning(f"candidata: navegacao nao completou ({str(e)[:80]}) — fica para a proxima rodada")
            await br.close()
            return "inconclusivo"
        await page.wait_for_timeout(8000)  # SAML auto-submit
        body = ""
        try:
            body = await page.evaluate("() => document.body.innerText")
        except Exception:
            pass
        url_final = page.url or ""
        veredito = veredito_login(url_final, body, getattr(resp, "status", None))
        if veredito == "nao_sei":
            # Pagina de erro do portal, corpo vazio, SAML ainda em transito: NAO e
            # prova de jar deslogado. A candidata fica — ate envelhecer: fila presa
            # para sempre tambem e defeito.
            await br.close()
            if _candidata_velha(versao):
                if _encerra_candidata(cand_id, "descartada (nao foi possivel testar em "
                                      f"{CANDIDATA_MAX_H}h)", principal_id, versao):
                    _registra_candidata("recusada", f"nao foi possivel testar em {CANDIDATA_MAX_H}h "
                                                    "(portal fora do ar ou pagina irreconhecivel)")
                    return "recusada"
            log.warning(f"candidata: pagina irreconhecivel em {url_final[:60]} "
                        "(nem logado, nem tela de login) — fica para a proxima rodada")
            return "inconclusivo"
        if veredito == "login":
            await br.close()
            log.info(f"candidata RECUSADA: caiu em {url_final[:60]} — Chrome do dono sem login; "
                     "a sessao em uso NAO foi tocada")
            if _encerra_candidata(cand_id, "recusada (jar sem login gov.br; sessao em uso preservada)",
                                  principal_id, versao):
                _registra_candidata("recusada", "o Chrome mandou um jar SEM login gov.br; "
                                                "a sessao em uso foi preservada")
                return "recusada"
            return "inconclusivo"
        fresh = await ctx.cookies()
        relevant = [c for c in fresh if any(d in (c.get("domain") or "")
                    for d in ("transferegov", "sso.acesso.gov.br", "gov.br"))]
        await br.close()
    try:
        # ⚠️ GRAVA PRIMEIRO, apaga depois. O jar `relevant` AUTENTICOU agora — vale
        # como sessao em uso mesmo que a linha candidata tenha mudado no meio. Na
        # ordem inversa, uma falha de banco entre os dois passos jogava fora um
        # login bom. Se a candidata mudou durante o teste, o DELETE versionado nao
        # apaga nada e a captura nova e testada na proxima rodada.
        if principal_id:
            if not _save_cookies(principal_id, relevant):       # promocao: incondicional
                log.warning("candidata: a sessao em uso nao foi gravada — proxima rodada")
                return "inconclusivo"
            # A hora do LOGIN so muda com login NOVO (cookies do gov.br diferentes);
            # recaptura da mesma sessao promove o jar mas nao reinicia o relogio.
            _mesma, _difere = comparar_sessao_sso(cookies, em_uso_cookies)
            if _mesma:
                log.info("candidata: mesma sessao SSO — jar renovado, hora do login preservada")
            else:
                # nomes (sem valor) do que mudou: e o que calibra a regra em producao
                log.info(f"candidata: LOGIN NOVO (cookies do gov.br que mudaram: "
                         f"{', '.join(_difere) or 'sem cookie de sessao em comum'})")
                _copia_observacao(cand_id, principal_id)        # login novo: a hora e a NOVA
        else:
            # A consulta RESPONDEU e nao ha linha 'govbr': nasce a sessao em uso,
            # com o jar FRESCO desta navegacao.
            enc = crypto.encrypt(json.dumps({
                "format": "cookies_full", "cookies": _from_pw_cookies(relevant),
                "url": "https://discricionarias.transferegov.sistema.gov.br/voluntarias/",
                "domain": "discricionarias.transferegov.sistema.gov.br"}))
            conn = psycopg2.connect(_sync_url(), connect_timeout=10)
            with conn, conn.cursor() as cur:
                cur.execute("INSERT INTO cofre_senhas (municipio_id, sistema, usuario, senha_hash, "
                            "categoria, automation_key, observacao) VALUES (NULL, 'Sessao GOVBR', "
                            "'(cookie)', %s, 'Sessao', 'govbr', '[SESSION] promovida de candidata')",
                            (enc,))
            conn.close()
        _encerra_candidata(cand_id, "promovida (autenticou)", principal_id or None, versao)
        log.info(f"candidata PROMOVIDA ✓ — {len(relevant)} cookies viraram a sessao em uso")
        # Autenticou = o login esta VIVO, medido agora: liga a guarda do endpoint
        # sem esperar o renew horario.
        _registra_sso("reconnected")
        _registra_candidata("promovida", None)
        return "promovida"
    except Exception as e:
        log.error(f"candidata: falha ao promover ({str(e)[:100]})")
        return "inconclusivo"

def _eh_tela_de_login(url: str, body: str) -> bool:
    """Prova POSITIVA de que a pagina NAO e sessao logada.

    ⚠️ "Sair do Acesso Livre" (23/09/2026, visto no Chrome do dono): o modo
    visitante do TransfereGov abre a pagina da porta com um botao "Sair" — que
    `_is_authenticated` tomava por login. Uma captura de visitante chegando com a
    sessao viva virava candidata e era PROMOVIDA por cima da sessao boa."""
    u = (url or "").lower(); b = (body or "").lower()
    return ("/idp/" in u or "sso.acesso.gov.br" in u or "identifique-se" in b
            or "acesso restrito" in b or "sair do acesso livre" in b)


def _is_authenticated(url: str, body: str) -> bool:
    if _eh_tela_de_login(url, body):
        return False
    return "voluntarias" in (url or "").lower() and "sair" in (body or "").lower()


def veredito_login(url: str, body: str, http_status: int | None = None) -> str:
    """'logado' | 'login' | 'nao_sei' — TRES valores, e o terceiro e o que importa.

    ⚠️ "NAO AUTENTICOU" NAO E "CAIU NO LOGIN". `page.goto` nao levanta para HTTP
    502/503 nem para pagina de manutencao, e um `evaluate` que falha no meio do
    auto-submit do SAML deixa o corpo vazio: com o bool de antes tudo isso virava
    "SSO expirou — recapturar". E `govbr_sso=erro` DESLIGA a guarda do endpoint de
    captura: um portal fora do ar por minutos reabria a porta para o jar deslogado
    do Chrome gravar por cima da sessao viva (o vigia ja sabia: "uma so pode ser o
    portal fora do ar por minutos"). So ha veredito negativo com PROVA POSITIVA da
    tela de login; sem prova para nenhum lado, a rodada e inconclusiva e nao
    escreve nada."""
    if _is_authenticated(url, body):
        return "logado"
    if (http_status or 0) >= 500:
        return "nao_sei"
    return "login" if _eh_tela_de_login(url, body) else "nao_sei"


async def renew() -> str:
    """Retorna 'reconnected' | 'needs_recapture' | 'no_session' | 'inconclusivo'."""
    # Antes de tudo, a captura CANDIDATA (se houver): promovida, ja e ela que o
    # `_load_govbr_v` logo abaixo le. Nunca derruba o renew.
    try:
        _c = await processa_candidata()
        if _c != "sem_candidata":
            log.info(f"candidata: {_c}")
    except Exception as e:
        log.warning(f"candidata: {str(e)[:100]}")
    cofre_id, cookies, visto_em = _load_govbr_v()
    if not cookies:
        log.info("sem sessao govbr no Cofre — aguardando captura via extensao")
        return "no_session"
    log.info(f"cofre id={cofre_id} | {len(cookies)} cookies (re-derivando via SAML, sem login)")
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True,
                                     args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await br.new_context(ignore_https_errors=True,
                                   user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                                              "Chrome/131.0.0.0 Safari/537.36")
        await _add_cookies_tolerante(ctx, cookies)
        page = await ctx.new_page()
        resp = None
        try:
            resp = await page.goto(ENTRY, timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            # A pagina nem carregou: nao ha o que julgar. Antes isto seguia,
            # `_is_authenticated('about:blank', '')` dava False e um TIMEOUT virava
            # "SSO expirou — recapturar" no banco e no Telegram.
            log.warning(f"goto entry: {str(e)[:80]} — rodada INCONCLUSIVA (rede/portal), nada gravado")
            await br.close()
            return "inconclusivo"
        await page.wait_for_timeout(8000)  # SAML auto-submit
        body = ""
        try:
            body = await page.evaluate("() => document.body.innerText")
        except Exception:
            pass
        veredito = veredito_login(page.url, body, getattr(resp, "status", None))
        if veredito == "nao_sei":
            # Ver `veredito_login`: pagina de erro/corpo vazio nao e "SSO expirou".
            log.warning(f"pagina irreconhecivel em {(page.url or '')[:60]} (HTTP "
                        f"{getattr(resp, 'status', '?')}; nem logado, nem tela de login) — "
                        "rodada INCONCLUSIVA, nada gravado")
            await br.close()
            return "inconclusivo"
        if veredito == "login":
            log.warning(f"SSO expirou (caiu em {page.url[:60]}) — precisa RE-CAPTURA "
                        f"(login tem reCAPTCHA, nao automatizavel)")
            await br.close()
            return "needs_recapture"
        # A entrada autenticou — mas foi o SP (vivo pelo keepalive) ou o SSO? A
        # sonda responde, em navegador proprio e descartado. Nunca derruba o renew.
        if sonda_ligada():
            try:
                _rt, _det = await sso_roundtrip(br, cookies)
                _registra_roundtrip(_rt, _det)
                log.info(f"sonda SSO (sem cookie do SP): {_rt} — {_det}")
            except Exception as e:
                log.warning(f"sonda SSO: {str(e)[:100]}")
        # SSO vivo -> re-derivado. Repovoa JSESSIONIDs dos subdominios + mantem SSO quente.
        for sd in SUBDOMINIOS[1:]:
            try:
                await page.goto(sd, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
            except Exception:
                pass
        fresh = await ctx.cookies()
        relevant = [c for c in fresh if any(d in (c.get("domain") or "")
                    for d in ("transferegov", "sso.acesso.gov.br", "gov.br"))]
        await br.close()
        try:
            # `visto_em`: se o dono recapturou DURANTE esta rodada, o jar dele
            # fica — este nasceu do jar velho. O login esta vivo de todo jeito.
            if _save_cookies(cofre_id, relevant, visto_em):
                log.info(f"RECONECTADO ✓ — {len(relevant)} cookies frescos salvos no Cofre")
            else:
                log.info("RECONECTADO ✓ — jar NAO salvo (captura nova chegou no meio; ela fica)")
        except Exception as e:
            log.error(f"falha ao salvar cookies: {str(e)[:100]}")
            return "needs_recapture"
        return "reconnected"


async def keepalive() -> str:
    """Keep-alive LEVE do /private/ (mandatarias), pensado p/ rodar a cada ~10min.

    So navega o guest (mantem SSO quente) e o /private/ (reseta o idle do JEE),
    re-salvando os cookies. NAO faz o round-trip pesado do renew(). Enquanto rodar
    mais rapido que o timeout de inatividade do /private/, ele NUNCA cai -> sem
    re-captura. Retorna 'alive' | 'private_dead' | 'no_session'.
    """
    # A captura CANDIDATA primeiro: o keepalive roda de 10 em 10 minutos, entao e
    # aqui que um login novo do dono e promovido rapido. Nunca derruba a rodada.
    try:
        _c = await processa_candidata()
        if _c != "sem_candidata":
            log.info(f"keepalive candidata: {_c}")
    except Exception as e:
        log.warning(f"keepalive candidata: {str(e)[:100]}")
    cofre_id, cookies, visto_em = _load_govbr_v()
    if not cookies:
        log.info("keepalive: sem sessao no Cofre")
        return "no_session"
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        br = await p.chromium.launch(headless=True,
                                     args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await br.new_context(ignore_https_errors=True,
                                   user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                                              "Chrome/131.0.0.0 Safari/537.36")
        if await _add_cookies_tolerante(ctx, cookies) == 0:
            # Navegador ANONIMO nao mede nada e nao pode gravar nada: o jar que
            # sairia daqui e o da tela de login.
            await br.close()
            log.error("keepalive: nenhum cookie do Cofre carregou — rodada abortada SEM gravar")
            return "private_dead"
        page = await ctx.new_page()
        # 1) guest: mantem o SSO/discricionarias quente (barato)
        entry_ok = False
        try:
            await page.goto(ENTRY, timeout=45000, wait_until="domcontentloaded")
            # 4s bastam com o JSESSIONID quente; com round-trip no SSO o renew()
            # espera 8s pela MESMA pergunta — entao: 4s, olha, e so se ainda nao
            # autenticou espera os outros 4s.
            for _ in range(2):
                await page.wait_for_timeout(4000)
                try:
                    _body = await page.evaluate("() => document.body.innerText")
                except Exception:
                    _body = ""
                entry_ok = _is_authenticated(page.url, _body)
                if entry_ok:
                    break
        except Exception as e:
            log.warning(f"keepalive guest: {str(e)[:80]}")
        # 2) /private/: reseta o idle do JEE das mandatarias
        private_ok = False
        try:
            await page.goto(PRIVATE_ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)
            u = (page.url or "").lower()
            private_ok = "idp/" not in u and "sso.acesso" not in u
        except Exception as e:
            log.warning(f"keepalive private: {str(e)[:80]}")
        # 3) execucao (Processo de Execucao): reseta o idle do SP `execucao`,
        #    mantendo a captura da situacao da licitacao (processo_execucao) viva.
        exec_ok = False
        try:
            await page.goto(EXEC_ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            eu = (page.url or "").lower()
            exec_ok = "idp/" not in eu and "sso.acesso" not in eu
        except Exception as e:
            log.warning(f"keepalive execucao: {str(e)[:80]}")
        # 4) prestacao (Notas de Empenho): SP SEPARADO do de cima, com idle
        #    proprio — ver o comentario de PRESTACAO_ENTRY. Sem esta navegacao a
        #    coleta de NEs morria horas depois da captura enquanto o keepalive
        #    reportava `execucao=vivo`, o que fazia o sintoma parecer outra coisa.
        prest_ok = False
        try:
            await page.goto(PRESTACAO_ENTRY, timeout=45000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            pu = (page.url or "").lower()
            prest_ok = "idp/" not in pu and "sso.acesso" not in pu
        except Exception as e:
            log.warning(f"keepalive prestacao: {str(e)[:80]}")
        fresh = await ctx.cookies()
        relevant = [c for c in fresh if any(d in (c.get("domain") or "")
                    for d in ("transferegov", "sso.acesso.gov.br", "gov.br"))]
        await br.close()
    if not relevant:
        return "private_dead"
    # ⭐ SO GRAVA COM PROVA DE VIDA — ver `tem_prova_de_vida`. E com `visto_em`:
    # se o dono recapturou durante esta rodada, o jar dele fica.
    gravou = False
    if tem_prova_de_vida(entry_ok, private_ok, exec_ok, prest_ok):
        try:
            gravou = _save_cookies(cofre_id, relevant, visto_em)
        except Exception as e:
            log.error(f"keepalive save: {str(e)[:100]}")
    else:
        log.warning("keepalive: login e os tres SPs caidos — jar NAO regravado")
    # ⭐ O LOGIN PROVADO VIVO vira medicao de `govbr_sso` JA, e nao so no renew
    # horario. E essa fonte que liga a guarda do endpoint de captura: sem isto,
    # depois de uma RECAPTURA a guarda ficava desligada ate ~60 min, e nesse
    # intervalo qualquer jar deslogado do Chrome gravava direto por cima da
    # sessao recem-recuperada. ⚠️ So o POSITIVO: a espera daqui e curta para
    # veredito negativo — quem declara o login morto continua sendo o renew().
    if entry_ok:
        _registra_sso("reconnected")
    # ⚠️ `prestacao` sai no log SEPARADO de `execucao`, e nao somado a ele: sao
    # SPs diferentes, e foi exatamente por eles aparecerem como um so que as NEs
    # morriam em silencio com o keepalive dizendo "execucao=vivo".
    _sps = (f"execucao={'vivo' if exec_ok else 'CAIU'}, "
            f"prestacao={'vivo' if prest_ok else 'CAIU'}")
    _registra_sessao(private_ok, exec_ok, prest_ok)
    if private_ok:
        log.info(f"keepalive OK — /private/ vivo, {_sps}, "
                 f"{len(relevant)} cookies {'re-salvos' if gravou else 'NAO salvos'}")
        return "alive"
    log.warning(f"keepalive — /private/ CAIU (idp/login), {_sps}. "
                "Precisa re-captura pela extensao.")
    return "private_dead"


if __name__ == "__main__":
    import sys
    modo = sys.argv[1] if len(sys.argv) > 1 else "renew"
    if modo == "keepalive":
        print(asyncio.run(keepalive()))
    else:
        resultado = asyncio.run(renew())
        _registra_sso(resultado)
        _registra_rodada(resultado)
        print(resultado)
