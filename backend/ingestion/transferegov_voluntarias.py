"""Scraper TransfereGov - Transferencias Voluntarias (SICONV/Discricionarias).

Fonte: portal voluntarias via ACESSO LIVRE (guest), sem login gov.br.
Ponto de entrada que estabelece sessao de visitante:
  /voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest

O fluxo passa por SAML auto-submit (forms com onload=submit), que SO funciona
em browser real -> por isso Playwright (igual SIGCON). httpx puro nao resolve
porque o IdP exige JS.

Para cada municipio PACTHA:
  1. Entra via guest
  2. Consulta Rapida: seleciona UF + Municipio (match por nome normalizado)
  3. Clica Consultar
  4. Extrai a grid (Numero, Situacao, Orgao, Proponente, Parecer, CNPJ)
  5. UPSERT em transferegov_propostas

Roda no service com Chromium (Dockerfile.scraper). Local: requer playwright install.
"""
import asyncio
import json
import logging
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tg_voluntarias")

ENTRY = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
         "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest")

# Entrada AUTENTICADA (sem Usr=guest): mesma tela de consulta, mas os detalhes
# resultantes sao a versao logada — com o botao "Detalhar Clausula Suspensiva/
# Liminar Judicial" e os campos gated (parlamentar). O guest NAO renderiza esse
# botao (TagFuncionalidade resultado='false'). Por isso, quando ha sessao viva,
# a LISTAGEM tambem precisa rodar autenticada (nao so o detalhe).
ENTRY_AUTH = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do"
              "?modulo=Principal&path=/MostraPrincipalConsultarProposta.do")


def _jwt_minutos_restantes(cookies: list[dict]) -> float:
    """Retorna minutos restantes do JWT user-id (parcerias.transferegov).
    Retorna -inf se nao houver user-id ou nao decodificar.
    Retorna 0 se ja expirou."""
    import base64
    import json as _json
    import time
    uid = next((c for c in cookies if c.get("name") == "user-id"), None)
    if not uid:
        return float("-inf")
    token = uid.get("value", "")
    parts = token.split(".")
    if len(parts) < 2:
        return float("-inf")
    try:
        pb = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(pb))
        exp = payload.get("exp")
        if exp:
            return (exp - time.time()) / 60
    except Exception:
        pass
    return float("-inf")


# Orcamento de capturas de Historico COMPARTILHADO pela execucao inteira (ver o
# uso em _scrape_municipio). Fica no modulo, e nao numa local, porque a funcao
# roda uma vez por municipio: como local, o teto valia por municipio e o total
# virava (n_municipios x teto).
_HIST_ORC: dict = {"restante": None}

# Subcoleta de paginacao detectada na ULTIMA visita de cada municipio
# (municipio_id -> (coletadas, total_oficial); ver o fim de _scrape_municipio).
# No modulo pelo mesmo motivo do _HIST_ORC: quem consome e o chamador
# (run_proximos grava 'parcial' no ingestion_log), sem mudar a assinatura dos
# 3 call sites de _scrape_municipio.
_PAGINACAO_INCOMPLETA: dict = {}

# Estado do ultimo _scrape_municipio: sinaliza se o loop de DETALHE foi CORTADO
# pelo orcamento (parcial) em vez de ter terminado. Complementar ao
# _PAGINACAO_INCOMPLETA acima: aquele marca listagem incompleta, este marca
# detalhe incompleto. Mesmo motivo p/ viver no modulo — `_scrape_municipio`
# devolve uma lista e mudar a assinatura quebraria os 3 call sites.
_SCRAPE_STATE: dict = {"parcial": False, "restantes": 0}

# TERCEIRO EIXO DO STATUS DA RODADA: a fatia atras do LOGIN gov.br.
#
# ⚠️ O status era montado a partir de DUAS dimensoes apenas — municipio falhou?
# paginacao veio curta? — e a terceira, "a fatia gated nao respondeu", nao tinha
# como virar 'parcial'. Consequencia MEDIDA (auditoria + verificacao,
# 29/08/2026): com a sessao gov.br morta, as notas de empenho, o projeto basico,
# a licitacao e o historico param de atualizar, os leitores devolvem None
# CORRETAMENTE, o COALESCE preserva o dado velho CORRETAMENTE — e a rodada e
# gravada como 'success'. O apagao fica invisivel para o monitor de frescor e
# para o watchdog, que leem justamente esta linha.
#
# Contador de MODULO no mesmo molde de `_PAGINACAO_INCOMPLETA` e `_SCRAPE_STATE`:
# nao muda assinatura de funcao nenhuma, que e o que torna isto barato.
_GATED: dict = {"tentadas": 0, "sem_retorno": 0}


def _gated_conta(tentou: bool, teve_retorno: bool) -> None:
    """Registra UMA leitura atras do login. `tentou=False` nao conta — tenant com
    TG_HTTP_ENRICH/TG_NES desligado tem de ficar em ZERO, e nao virar 'parcial'
    por nunca ter perguntado."""
    if not tentou:
        return
    _GATED["tentadas"] += 1
    if not teve_retorno:
        _GATED["sem_retorno"] += 1


def _gated_zera() -> None:
    _GATED["tentadas"] = 0
    _GATED["sem_retorno"] = 0


def _gated_frase() -> str | None:
    """A frase para o `error_message` da rodada, ou None quando nao ha o que
    dizer. METADE das leituras sem retorno e o limiar: uma ou outra falha e
    ruido do portal; metade e sessao fria.

    ⚠️ `tentadas` ZERO devolve None — nunca uma divisao solta. Sem esta guarda,
    um tenant que nao le a fatia gated nasceria 'parcial' para sempre."""
    t, s = _GATED["tentadas"], _GATED["sem_retorno"]
    if not t or s * 2 < t:
        return None
    return (f"sessao gov.br fria: {s}/{t} leituras atras do login sem retorno "
            f"(dado gated NAO atualizou nesta rodada)")


def _hist_orcamento() -> dict:
    """Contador de orcamento da EXECUCAO (lazy, a partir do env na 1a chamada)."""
    if _HIST_ORC["restante"] is None:
        try:
            _HIST_ORC["restante"] = max(0, int(os.getenv("TRANSFEREGOV_HISTORICO_MAX", "15") or "15"))
        except ValueError:
            _HIST_ORC["restante"] = 15
    return _HIST_ORC


def _propostas_sem_historico(municipio_id: int) -> set:
    """numero_proposta das que precisam de Historico de Comunicacoes: as que nunca
    tiveram OU cuja captura ja passou de TG_HISTORICO_MAX_AGE_DAYS.

    O `IS NULL` puro (comportamento ate 10/08/2026) converge a primeira passada e
    depois CONGELA: capturada uma vez, a proposta nunca mais e reprioritizada e o
    campo passa a ter envelhecimento ILIMITADO. Medido em 10/08: freitas 3.256 de
    4.846 capturadas, trust apenas 1.580 de 9.101 — e nenhuma delas voltaria a ser
    lida jamais.

    Com a janela, o conjunto vira um CICLO permanente em vez de uma passada unica.
    TG_HISTORICO_MAX_AGE_DAYS=0 mantem o comportamento antigo (so as nunca lidas),
    que e o default p/ nao mudar o custo da rodada sem decisao explicita."""
    try:
        _max_age = max(0, int(os.getenv("TG_HISTORICO_MAX_AGE_DAYS", "0") or "0"))
    except ValueError:
        _max_age = 0
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        if _max_age > 0:
            cur.execute(
                "SELECT numero_proposta FROM transferegov_propostas "
                "WHERE municipio_id=%s AND (historico_atualizado_em IS NULL "
                "   OR historico_atualizado_em < NOW() - make_interval(days => %s))",
                (municipio_id, _max_age)
            )
            out = {r[0] for r in cur.fetchall()}
            cur.close(); conn.close()
            return out
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas "
            "WHERE municipio_id=%s AND historico_atualizado_em IS NULL",
            (municipio_id,)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _propostas_ops_obs_frescas(municipio_id: int, max_age_days: int = 3) -> set:
    """numero_proposta cujo ops_obs/obras foi checado ha menos de max_age_days.
    Usado p/ PULAR a re-navegacao no cron: cada instrumento e navegado no portal
    (~caro); sem skip, TODOS os ~3161 re-navegam toda rodada. Com skip, so os
    novos/vencidos navegam. Se a coluna ainda nao existe (migration nao rodou),
    o except devolve set() vazio -> tudo navega (fallback seguro)."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas "
            "WHERE municipio_id=%s AND ops_obs_atualizado_em IS NOT NULL "
            "AND ops_obs_atualizado_em > NOW() - make_interval(days => %s)",
            (municipio_id, max_age_days)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _stamp_ops_obs(municipio_id: int, numero_proposta: str) -> None:
    """Carimba ops_obs_atualizado_em=NOW() (checagem feita, MESMO vazia) num UPDATE
    isolado — NAO no INSERT do _upsert — p/ a proposta sair do backlog de ops_obs.
    Marcar tb as vazias e o que evita re-navegar os ~2900 sem ops_obs toda rodada."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "UPDATE transferegov_propostas SET ops_obs_atualizado_em=NOW() "
            "WHERE municipio_id=%s AND numero_proposta=%s",
            (municipio_id, numero_proposta[:20])
        )
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass


def _propostas_detalhe_frescas(municipio_id: int, max_age_hours: int) -> dict:
    """{numero_proposta: situacao_gravada} das propostas cujo DETALHE foi lido ha
    menos de max_age_hours.

    Por que existe: o loop de detalhe re-lia TODAS as propostas em toda rodada
    (~2,5-3s cada). No trust sao 9.095 propostas = ~7h — nenhum teto de tempo faz
    isso caber numa janela de cron, e por isso o lote morria no SIGKILL sem nunca
    carimbar municipio (livelock observado em 09/08/2026: 10 rodadas, 0 carimbos).

    POR QUE EM HORAS, E NAO EM DIAS. A janela precisa ficar ABAIXO da cadencia com
    que o rodizio volta ao mesmo municipio, senao a visita vira no-op: ela pula
    todas as propostas (nao carimba detalhe_atualizado_em, por causa do COALESCE
    no _upsert) mas CARIMBA ultima_coleta_em e anda a fila — e a releitura real
    passa a acontecer so a cada DUAS cadencias.
    Medido em 10/08/2026: com TG_LOTE_MUNICIPIOS=4 a cadencia do freitas e 31h,
    maior que 24h, entao a janela de 1 dia nao atrapalhava. Subindo p/ 6
    municipios a cadencia cai p/ 20,7h — abaixo de 24h — e a cobertura CAIRIA de
    77% p/ 58%, pior que antes. Em dias so havia dois estados uteis e nenhum era o
    certo: 1 (colide com a cadencia) ou 0 (mata a retomada do [PARCIAL]).

    O chamador so pula quando a situacao da LISTAGEM (barata, vem toda rodada)
    continua IGUAL a gravada — qualquer mudanca invalida o skip e forca releitura.
    Devolve dict vazio se a coluna ainda nao existe (migration nao rodou) -> tudo
    e lido, que e o comportamento antigo (fallback seguro)."""
    if max_age_hours <= 0:
        return {}
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta, COALESCE(situacao,'') FROM transferegov_propostas "
            "WHERE municipio_id=%s AND detalhe_atualizado_em IS NOT NULL "
            "AND detalhe_atualizado_em > NOW() - make_interval(hours => %s)",
            (municipio_id, max_age_hours)
        )
        out = {r[0]: r[1] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return {}


def _sem_clausula_confirmado(sit_portal) -> bool:
    """True SO quando o portal afirmou, nesta rodada, "Normal" — o valor POSITIVO.

    ⚠️ POR QUE NAO E `not _RE_CLAUSULA.search(...)`. Esta funcao autoriza APAGAR
    dado (o JSONB da clausula). Com a regra pela NEGATIVA, qualquer valor
    inesperado no campo — ou a situacao do CICLO ("Em execução"), que e o fallback
    de `_sit` — viraria ordem de limpeza, e um bug de leitura zeraria a carteira
    inteira em silencio. A coluna `situacao_contratacao` tem tres valores no
    portal (Normal / Cláusula Suspensiva / Liminar Judicial, ver
    SIT_CONTRATACAO_OPCOES no frontend), entao exigir "normal" e a leitura segura:
    na duvida, PRESERVA.

    String vazia = "nao perguntei" (detalhe nao lido nesta rodada) -> False."""
    return (sit_portal or "").strip().casefold().startswith("normal")


def _propostas_com_clausula(municipio_id: int) -> set:
    """numero_proposta das que o BANCO ja sabe estarem em clausula suspensiva ou
    liminar — por QUALQUER uma das tres fontes que registram isso.

    POR QUE EXISTE. O gate da coleta olhava so `_sit` (a "Situação de Contratação
    Atual" lida da tela NAQUELA rodada), enquanto a EXIBICAO no RM
    (services/rm_pdf.py::_tem_clausula) ja considerava tres sinais. Coleta e
    exibicao divergiam, e o convenio 981397/2025 (Araujos) caiu na fresta:

      - a coluna `situacao_contratacao` e sobrescrita todo dia pelo CSV do dado
        aberto (transferegov_opendata.py) e hoje diz "Normal";
      - `clausula_suspensiva_motivo` e `..._dt_prevista` foram ZERADAS por
        siconv_convenio_backfill.py, que faz UPDATE sem COALESCE e grava None
        quando o CSV diz normal;
      - so o JSONB `situacao_contratacao_detalhe` ainda registra a clausula — e
        ele e protegido por COALESCE no _upsert, entao NUNCA e limpo.

    Resultado: o RM desenhava a caixa ambar ("Motivo: Termo de Referência") e
    ninguem ia buscar em que pe o documento estava, porque o gate lia justamente
    a fonte que havia virado "Normal".

    Este SELECT e o espelho SQL de `_tem_clausula`. Em qualquer falha (coluna
    ausente, banco fora) devolve set() vazio e o gate volta a depender so de
    `_sit` — o comportamento antigo, nunca pior que ele."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas WHERE municipio_id=%s AND ("
            "  situacao_contratacao ~* 'cl[áa]usula|suspensiv|liminar'"
            "  OR clausula_suspensiva_motivo IS NOT NULL"
            "  OR clausula_suspensiva_dt_prevista IS NOT NULL"
            "  OR situacao_contratacao_detalhe IS NOT NULL)",
            (municipio_id,)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _proximo_link(res: dict, cur: int) -> str | None:
    """Link da pagina cur+1: o numero dentro da janela ou, na borda, o [Prox]."""
    nxt = next((l["href"] for l in res.get("links", []) if l["num"] == cur + 1), None)
    return nxt or res.get("prox")


def _propostas_conhecidas(municipio_id: int) -> int:
    """Quantas propostas o banco ja tem deste municipio. Referencia da trava de
    completude quando o portal nao mostrou o total (banner ausente). 0 = sem
    referencia (municipio novo, ou erro de banco) — ai a trava nao julga."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute("SELECT count(*) FROM transferegov_propostas WHERE municipio_id=%s", (municipio_id,))
        n = cur.fetchone()[0]
        cur.close(); conn.close()
        return int(n or 0)
    except Exception:
        return 0


def _listagem_incompleta(listadas: int, oficial: int | None, conhecidas: int) -> tuple[int, str] | None:
    """(esperado, de onde veio a referencia) quando a listagem veio curta; None se ok.

    Com o total OFICIAL (o Z do banner): tolerancia de max(2, 2%) — `listadas` e
    deduplicada e filtrada, o Z conta itens brutos, e uma divergencia estavel de
    1-2 itens marcaria o municipio como subcoleta em toda visita (letal no tenant
    de 1 municipio: nunca mais gravaria 'success').

    Sem o oficial, contra as propostas que o BANCO ja conhece: abaixo de 90% e
    corte. Tolerancia larga de proposito — o banco tambem guarda proposta que o
    portal ja nao lista — e so a partir de 20 conhecidas: municipio pequeno ou
    novo nao tem referencia que preste, e a trava nao inventa uma."""
    if oficial:
        if oficial - listadas > max(2, int(oficial * 0.02)):
            return oficial, "total oficial do portal"
        return None
    if conhecidas >= 20 and listadas < conhecidas * 0.9:
        return conhecidas, "propostas ja conhecidas no banco — o portal nao mostrou o total"
    return None


def _propostas_ja_enriquecidas(municipio_id: int) -> set:
    """Retorna numero_proposta das que JA tem parlamentar OU sit_det.
    Permite priorizar as pendentes quando rodando com janela curta de auth."""
    try:
        import psycopg2
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT numero_proposta FROM transferegov_propostas "
            "WHERE municipio_id=%s AND (parlamentar IS NOT NULL OR situacao_contratacao_detalhe IS NOT NULL)",
            (municipio_id,)
        )
        out = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return out
    except Exception:
        return set()


def _load_session_cookies(automation_key: str) -> list[dict] | None:
    """Carrega cookies do Cofre p/ uma chave de automacao (best-effort).

    ESCOLHA DA SESSAO. Por padrao vence a mais RECENTE com corpo de sessao
    (>1000 bytes; entradas curtas sao senha, nao cookie). Isso e fragil: qualquer
    captura nova assume o lugar sem aviso, e uma captura da conta errada troca a
    identidade da coleta em silencio.

    Para fixar uma conta, defina GOVBR_COFRE_ID com o id da linha do cofre —
    ai a selecao passa a ser por id e nenhuma captura posterior a substitui.
    Se o id fixado sumir ou perder o corpo de sessao, cai no comportamento
    antigo e AVISA no log (melhor coletar com a sessao errada do que nao coletar,
    mas o aviso tem de aparecer)."""
    try:
        import psycopg2
        from services import crypto
        url = os.getenv("DATABASE_URL_SYNC", "")
        url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        _fixo = (os.getenv("GOVBR_COFRE_ID", "") or "").strip()
        row = None
        if _fixo.isdigit():
            cur.execute(
                "SELECT senha_hash FROM cofre_senhas "
                "WHERE id=%s AND automation_key=%s AND length(senha_hash) > 1000",
                (int(_fixo), automation_key),
            )
            row = cur.fetchone()
            if row:
                logger.info(f"  cofre[{automation_key}]: sessao FIXADA id={_fixo}")
            else:
                logger.warning(f"  cofre[{automation_key}]: GOVBR_COFRE_ID={_fixo} nao encontrado "
                               f"(ou sem corpo de sessao) — caindo p/ a mais recente")
        if row is None:
            cur.execute(
                "SELECT senha_hash FROM cofre_senhas "
                "WHERE automation_key=%s AND length(senha_hash) > 1000 "
                "ORDER BY updated_at DESC LIMIT 1",
                (automation_key,),
            )
            row = cur.fetchone()
        cur.close(); conn.close()
        if not row:
            return None
        dec = crypto.decrypt(row[0])
        if not dec or not dec.startswith("{"):
            return None
        data = json.loads(dec)
        out = []
        for c in data.get("cookies", []):
            n, v = c.get("name"), c.get("value")
            if not n or v is None:
                continue
            ck = {
                "name": n, "value": v, "path": c.get("path") or "/",
                "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly")),
            }
            if c.get("domain"):
                ck["domain"] = c["domain"]
            ss = c.get("sameSite")
            if ss:
                ck["sameSite"] = {"no_restriction": "None", "lax": "Lax", "strict": "Strict",
                                  "None": "None", "Lax": "Lax", "Strict": "Strict"}.get(ss, "Lax")
            exp = c.get("expirationDate")
            if exp:
                try:
                    ck["expires"] = float(exp)
                except (TypeError, ValueError):
                    pass
            out.append(ck)
        return out or None
    except Exception as e:
        logger.warning(f"_load_session_cookies({automation_key}): ignorando ({e})")
        return None


def _load_govbr_cookies() -> list[dict] | None:
    """Carrega cookies das DUAS sessoes (govbr + siconv_legado) consolidadas.
    govbr = cookies de parcerias.transferegov + SSO gov.br
    siconv_legado = cookies de discricionarias.transferegov (JSESSIONID p/
                    acessar Cláusula Suspensiva e demais campos gated do SICONV antigo)
    Retorna lista consolidada (deduplicada por nome+dominio)."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for key in ("govbr", "siconv_legado"):
        cks = _load_session_cookies(key)
        if not cks:
            continue
        for c in cks:
            sig = (c.get("name", ""), c.get("domain", ""))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(c)
        logger.info(f"  cofre[{key}]: {len(cks)} cookies carregados")
    return out or None


def _norm(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper()) if not unicodedata.combining(c)).strip()


def _clean(s):
    """Remove o caractere de substituicao U+FFFD que o portal TransfereGov as
    vezes serve no lugar de acentos (corrompido na origem, irrecuperavel)."""
    if not isinstance(s, str):
        return s
    return s.replace("�", "").replace("  ", " ").strip()


_INCOERENTES = {"n": 0}


def _log_incoerente(num, glob, repasse, contrap) -> None:
    """Conta e loga o trio recusado. ⚠️ O SILENCIO E QUE DEIXOU ISTO VIVER: o
    deslocamento roda desde que `grab_money` nasceu e so apareceu quando uma
    auditoria externa comparou com o portal. Recusar calado seria trocar um
    defeito silencioso por outro."""
    _INCOERENTES["n"] += 1
    if _INCOERENTES["n"] <= 10:      # nao inunda o log de uma rodada grande
        logger.warning(
            f"  [valores] proposta {num}: trio incoerente, NAO gravado "
            f"(global={glob} repasse={repasse} contrap={contrap}) — "
            f"o CSV de dados abertos continua valendo")


def _primeiro_campo(valor):
    """So o primeiro campo do que o extrator devolveu, cortando no TAB/quebra.

    O leitor de detalhe achata a linha da tabela e as vezes traz o par
    rotulo/valor SEGUINTE colado por TAB: "Contrato de Repasse\\tEnviada para
    mandatária?\\tNÃ£o". Medido em 27 de 83 propostas de Araujos.

    None e '' passam intactos — a funcao nao inventa valor, so apara."""
    if valor is None:
        return None
    return re.split(r"[\t\r\n]", str(valor))[0].strip() or None


_RE_DATA_BR = re.compile(r"\d{2}/\d{2}/\d{4}")


def _data_br(valor):
    """A PRIMEIRA data dd/mm/aaaa do que o extrator devolveu, ou None.

    Mesmo defeito do `_primeiro_campo`, nas colunas de data: a celula vem as
    vezes com o par rotulo/valor seguinte colado por TAB ("06/07/2026\\tData
    Assinatura\\t01/07/2026"). Nos bancos antigos a coluna nao tem limite e o
    texto inteiro entrava na coluna de DATA; nos criados pelo `setup_db`
    (VARCHAR(20)) nao cabe. Foi o que derrubou `fix_transferegov_datas_texto.sql`
    em Santa Maria a cada boot, de 17/08 a 15/09/2026.

    Texto sem data nenhuma vira None — e None faz o COALESCE do upsert
    PRESERVAR o que ja esta na coluna, em vez de gravar lixo nela."""
    if valor is None:
        return None
    m = _RE_DATA_BR.search(str(valor))
    return m.group(0) if m else None


def valores_coerentes(glob, repasse, contrap, tol: float = 0.02) -> bool:
    """O trio de valores fecha a conta? global == repasse + contrapartida.

    ⚠️ E A UNICA TRAVA que separa dinheiro medido de dinheiro DESLOCADO.
    MEDIDO EM PRODUCAO (29/08/2026, auditoria externa + bancada): `grab_money`
    (transferegov_http.py) procura o proximo "R$" DEPOIS do rotulo, e o portal
    imprime o valor ANTES dele. Com os tres campos em sequencia, cada rotulo
    colhe o valor do SEGUINTE:

        valor_global      <- o REPASSE          (3.819.853,65)
        valor_repasse     <- a CONTRAPARTIDA    (3.823,68)
        valor_contrapartida <- nada

    O caso real da creche de Araujos, e a aritmetica que o nomeia:
        3.823.677,33 - 3.819.853,65 = 3.823,68   (exato)
    O numero que aparecia como "repasse" ERA a contrapartida. Nao era troca de
    campo (o que a auditoria externa afirmou) nem truncamento de milhar (a
    primeira hipotese desta sessao): era DESLOCAMENTO de um campo. As duas
    correcoes erradas — "des-inverter as colunas" e "fazer a regex olhar para
    tras" — quebrariam o layout que hoje sai CERTO, porque o portal serve os dois
    formatos.

    Por isso a trava e sobre o RESULTADO, nao sobre o layout: um trio deslocado
    NUNCA fecha a soma, qualquer que seja a forma da pagina. E o mesmo principio
    que `_pc_forma` usa no SIGCON — validar a FORMA do que se leu em vez de
    perseguir cada jeito novo de o portal errar.

    None conta como ZERO so na CONTRAPARTIDA (convenio sem contrapartida e
    normal). Faltando global ou repasse, nao ha o que conferir -> False, e o
    chamador nao grava: o CSV de dados abertos e a fonte AUTORITATIVA declarada
    para estes tres campos (`transferegov_opendata._SOBRESCREVE`)."""
    if glob is None or repasse is None:
        return False
    try:
        return abs(float(glob) - (float(repasse) + float(contrap or 0))) <= tol
    except (TypeError, ValueError):
        return False


def _money(s):
    """Converte 'R$ 1.234.567,89' (pt-BR) em float. Retorna None se vazio/invalido."""
    if not s:
        return None
    import re as _re
    cleaned = _re.sub(r"[^\d,.-]", "", str(s))      # remove 'R$', espacos, etc
    cleaned = cleaned.replace(".", "").replace(",", ".")  # milhar . -> nada; decimal , -> .
    try:
        v = float(cleaned)
        return v if v != 0 else None
    except ValueError:
        return None


def _municipios_pacta() -> list[dict]:
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SELECT id, nome, uf FROM municipios WHERE active = true ORDER BY nome")
    out = [{"id": r[0], "nome": r[1], "uf": r[2]} for r in cur.fetchall()]
    cur.close(); conn.close()
    return out


async def _goto_with_retry(page, url: str, max_retries: int = 3, base_delay: float = 0.5,
                           timeout: int = 30000) -> bool:
    """goto() com backoff exponencial. True=sucesso, False=falhou.
    Nao retenta 404/403 (erro permanente). Recupera de 'connection closed',
    'ERR_NAME_NOT_RESOLVED' e timeouts transitorios."""
    import random
    for attempt in range(max_retries):
        try:
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return True
        except Exception as e:
            es = str(e).lower()
            if "404" in es or "403" in es or "not found" in es:
                return False
            if attempt < max_retries - 1:
                await asyncio.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.4))
            else:
                logger.warning(f"    goto {url[:55]} falhou {max_retries}x: {str(e)[:60]}")
                return False
    return False


# Le as opcoes do select de municipio SO com o documento fora de 'loading': ler
# durante o parse devolve a lista pela metade (ver _scrape_municipio).
_JS_OPCOES_MUNICIPIO = """() => {
    if (document.readyState === 'loading') return null;
    const s = document.querySelector('select[name=municipioAcessoLivre]');
    return s ? [...s.options].map(o => ({v: o.value, t: o.text})) : null;
}"""


async def _opcoes_municipio(page, mun: dict, timeout_s: float = 30.0,
                            passo_ms: int = 500) -> list[dict]:
    """Opcoes do select de municipio DEPOIS que a troca de UF terminou de recarregar.

    Pronto = documento fora de 'loading', select presente com mais que o
    placeholder, e a MESMA contagem em duas leituras seguidas. Erro de avaliacao
    (contexto destruido pela navegacao que a troca de UF dispara) e so "ainda
    nao": tenta de novo.

    Estourou o prazo: LEVANTA. Devolver a lista vazia ou pela metade aqui viraria
    "municipio nao encontrado no select", que e o diagnostico errado que este
    helper existe para matar."""
    fim = time.monotonic() + timeout_s
    anterior: list[dict] | None = None
    while True:
        try:
            atual = await page.evaluate(_JS_OPCOES_MUNICIPIO)
        except Exception:
            atual = None
        if atual and len(atual) > 1:
            if anterior is not None and len(atual) == len(anterior):
                return atual
            anterior = atual
        else:
            anterior = None
        if time.monotonic() >= fim:
            raise RuntimeError(f"select de municipios de {mun.get('uf')} nao estabilizou "
                               f"em {timeout_s:.0f}s (portal lento ou fora do ar)")
        await page.wait_for_timeout(passo_ms)


async def _scrape_municipio(page, mun: dict, _retry: int = 0, is_auth: bool = False,
                            page_auth=None, deadline: float | None = None) -> list[dict]:
    """Consulta por UF + Municipio, retorna lista de propostas COM detalhe.

    deadline  = instante (time.monotonic) em que o loop de DETALHE deve parar.
                None = sem corte. Sem isso, o orcamento do lote so era avaliado
                ENTRE municipios: um municipio grande atravessava a janela
                inteira e morria no SIGKILL externo, sem carimbar nada.

    page      = pagina GUEST (sem cookies) p/ listagem+detalhe via Acesso Livre.
                A listagem SO funciona em guest: com cookies de sessao, o
                ForwardAction redireciona p/ a consulta do convenente (sem o
                form ufAcessoLivre) e a listagem falha.
    page_auth = pagina AUTENTICADA (com cookies gov.br) p/ abrir o INSTRUMENTO
                e capturar o detalhe da Clausula Suspensiva (motivo + data).
                None = sem sessao -> captura so o status, sem motivo/data.
    is_auth   = mantido por compat; nao altera mais a entrada (sempre guest).
    """
    entry = ENTRY  # listagem SEMPRE via Acesso Livre (guest)
    await page.goto(entry, timeout=60000, wait_until="domcontentloaded")
    await page.wait_for_timeout(6000 + _retry * 4000)  # SAML auto-submits (mais tempo no retry)

    # Seleciona UF (com retry se a sessao SAML nao estabeleceu)
    try:
        await page.wait_for_selector("select[name=ufAcessoLivre]", timeout=12000)
        await page.select_option("select[name=ufAcessoLivre]", mun["uf"], timeout=10000)
    except Exception:
        if _retry < 2:
            logger.warning(f"  {mun['nome']}: select UF ausente, retry {_retry+1}")
            return await _scrape_municipio(page, mun, _retry + 1, is_auth=is_auth,
                                           page_auth=page_auth, deadline=deadline)
        logger.warning(f"  {mun['nome']}: select UF nao encontrado apos retries (sessao falhou)")
        # Levanta em vez de devolver []: lista vazia aqui virava "sucesso com
        # zero propostas" no chamador — carimbava coleta boa, zerava tentativas
        # e o municipio quebrado sumia de todos os radares novos.
        raise RuntimeError("portal/sessao indisponivel (select UF ausente apos retries)")
    # ⚠️ TROCAR A UF RECARREGA A PAGINA INTEIRA — nao e AJAX, como este trecho
    # supunha. Medido em 10/09/2026 numa sonda em modo guest: o select de
    # municipios SOME ~0,3s depois da escolha (contexto destruido pela
    # navegacao) e volta ~0,5s depois com as 855 opcoes de MG. O sleep fixo de
    # 3,5s que havia aqui caia, com o portal lento, no MEIO do recarregamento, e
    # os dois erros que o rodizio acumulava eram o mesmo defeito:
    #   - select ainda ausente    -> "Cannot read properties of null (reading
    #     'options')" (Papagaios, Passa Tempo, Santo Antonio do Monte, Pequi,
    #     Pirenopolis, Tocantins);
    #   - select a meio do parse  -> "nao encontrado no select (727 opcoes)" e
    #     "(390 opcoes)". Sao Tiago e Oliveira Fortes ESTAO na lista, com o nome
    #     certo: a lista e que ainda nao tinha terminado de ser desenhada.
    muns = await _opcoes_municipio(page, mun)
    alvo = [m for m in muns if _norm(m["t"]) == _norm(mun["nome"])]
    if not alvo:
        logger.warning(f"  {mun['nome']}: nao encontrado no select "
                       f"({len(muns)} municipios de {mun['uf']}, lista completa)")
        # Mesmo raciocinio do raise acima: municipio ausente do dropdown e erro
        # (nome divergente/portal), nao "zero propostas". Com a lista lida
        # completa, este erro passa a significar nome divergente DE VERDADE.
        raise RuntimeError(f"municipio nao encontrado no select do portal "
                           f"({len(muns)} opcoes de {mun['uf']}, lista completa)")
    await page.select_option("select[name=municipioAcessoLivre]", alvo[0]["v"])
    await page.wait_for_timeout(1500)

    # Clica Consultar (consulta rapida)
    await page.evaluate("""() => {
        const btns = [...document.querySelectorAll('input[type=button],button,input[type=submit],a')];
        const c = btns.find(b => (b.value||b.innerText||'').trim().toLowerCase()==='consultar');
        if (c) c.click();
    }""")
    await page.wait_for_timeout(9000)
    # Aguarda o banner de paginacao (.pagelinks) renderizar. Sem isso, as vezes
    # a 1a leitura pega a grid (20 linhas) ANTES dos controles de paginacao ->
    # o loop nao acha "proxima"/total e para na pagina 1 (subestima o total).
    try:
        await page.wait_for_selector(".pagelinks", timeout=15000)
        await page.wait_for_timeout(1200)
    except Exception:
        pass

    # Extrai a grid (maior tabela) + links de paginacao displaytag (d-XXXX-p=N).
    # A consulta rapida mostra 20 itens/pagina -> precisamos visitar TODAS as paginas.
    grid_js = r"""() => {
        const tables=[...document.querySelectorAll('table')];
        let best=null,max=0;
        for(const t of tables){const r=t.querySelectorAll('tr');if(r.length>max){max=r.length;best=t;}}
        let rows=[];
        if(best){
            rows=[...best.querySelectorAll('tr')].slice(1).map(tr=>{
                const tds=[...tr.querySelectorAll('td')].map(c=>c.innerText.trim());
                const a=tr.querySelector('td a');
                return {cols: tds, href: a ? a.href : null};
            }).filter(r=>r.cols.length>=6);
        }
        const denude = s => (s||'').normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
        const links=[];
        let prox=null;
        document.querySelectorAll('a').forEach(a=>{
            const raw=(a.innerText||'').trim();
            const href=a.href||'';
            // links NUMERICOS da janela: tem -p= E -g= (ex ...-p=3&-g=3)
            if(/^\d+$/.test(raw) && /-p=\d+/.test(href)) links.push({num: parseInt(raw,10), href});
            // link "Prox" (proxima janela): so tem -g= (SEM -p=). Desliza a janela.
            const t=denude(raw);
            if((t.indexOf('prox')===0 || t==='>' || t==='>>' || t.indexOf('seguinte')>=0 || t.indexOf('next')>=0)
               && /-g=\d+/.test(href)) prox=href;
        });
        // info "Pagina X de Y (Z item(s))" p/ validar avanco e saber a ultima pagina
        let info=null;
        document.querySelectorAll('.pagelinks').forEach(b=>{
            const mm=denude(b.innerText).match(/pagina\s+(\d+)\s+de\s+(\d+)\s*\((\d+)/);
            if(mm) info={cur:+mm[1], total:+mm[2], items:+mm[3]};
        });
        return {rows, links, prox, info};
    }"""

    all_rows = []
    res = await page.evaluate(grid_js)
    # ⚠️ SEM O BANNER NAO HA TOTAL, E SEM TOTAL A PARADA E SILENCIOSA. O banner
    # "Pagina X de Y (Z item(s))" e o UNICO lugar de onde sai o total: sem ele o
    # loop anda pelos links ate a primeira pagina que chegar sem link e para
    # achando que era a ultima — e a trava de completude la embaixo, que compara
    # com o Z, fica cega. Medido em 13/09/2026 com o portal lento (varias coletas
    # simultaneas): Palmas saiu com 100 de 2.121, Goiania com 2.460 de 3.472, os
    # dois como `success`, sem aviso nenhum. A mesma listagem, sozinha minutos
    # depois, veio inteira (107 paginas) da VPS e de fora dela — nao era bloqueio
    # de IP, era a pagina 1 lida antes do displaytag desenhar a paginacao.
    for _ in range(4):
        if res.get("info") or not res.get("rows"):
            break
        await page.wait_for_timeout(4000)
        res = await page.evaluate(grid_js)
    if res.get("rows") and not res.get("info"):
        logger.warning(f"  {mun['nome']}: pagina 1 sem o banner de paginacao — total desconhecido, "
                       f"a completude sera conferida contra as propostas ja conhecidas")
    all_rows.extend(res["rows"])

    # Paginacao SEM TETO. O displaytag mostra so uma JANELA fixa de numeros
    # (ex 1-10) e NAO desliza clicando nos numeros. Para ir alem, ha o link
    # "[Prox]" (proxima janela), que usa APENAS -g=<pag> (SEM -p=) e recarrega
    # a grid deslizando a janela (10 -> 11..16). Estrategia:
    #   - dentro da janela: navega pelo link NUMERICO de cur+1 (tem -p= & -g=);
    #   - na borda da janela: usa o link "[Prox]" (so -g=).
    # Valida o avanco pelo banner "Pagina X de Y" e re-tenta se a grid vier
    # vazia (carga incompleta). Para na ultima pagina (cur == total).
    def _key(r):
        return _clean(r["cols"][0]) if r.get("cols") else ""
    seen_keys = {_key(r) for r in res["rows"] if _key(r)}
    total = (res.get("info") or {}).get("total")
    itens_oficial = (res.get("info") or {}).get("items")
    cur = 1
    paginas = 1
    tried = set()
    while (total is None or cur < total) and paginas < 2000:
        nxt = _proximo_link(res, cur)
        if not nxt and (total is None or cur < total):
            # Sem link para a proxima NAO prova que acabou: a grid chega antes da
            # barra de paginacao quando o portal esta lento. Rele a pagina atual
            # e, a partir da 2a (que veio por GET), recarrega antes de desistir.
            # A pagina 1 e resultado de POST (Consultar) — recarregar reenviaria.
            for _t in range(3):
                await page.wait_for_timeout(2500 + _t * 2000)
                if _t == 2 and cur > 1:
                    try:
                        await page.reload(timeout=40000, wait_until="domcontentloaded")
                        await page.wait_for_timeout(3000)
                    except Exception:
                        pass
                res = await page.evaluate(grid_js)
                total = total or (res.get("info") or {}).get("total")
                nxt = _proximo_link(res, cur)
                if nxt:
                    break
        if not nxt or nxt in tried:
            if total is not None and cur < total:
                logger.warning(f"  {mun['nome']}: paginacao INTERROMPIDA na pagina {cur} de {total} "
                               f"(sem link para a {cur + 1} depois de reler)")
            break  # ultima pagina (nem cur+1 numerico nem [Prox])
        tried.add(nxt)
        # navega com retry: as vezes a grid vem vazia/incompleta (recarrega)
        loaded = False
        for attempt in range(3):
            try:
                await page.goto(nxt, timeout=40000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning(f"  {mun['nome']}: goto pagina {cur + 1} falhou: {str(e)[:70]}")
                await page.wait_for_timeout(1500)
                continue
            await page.wait_for_timeout(2500 + attempt * 1500)
            res = await page.evaluate(grid_js)
            info = res.get("info") or {}
            # ok se veio linha(s) E a pagina reportada avancou p/ cur+1. Pagina SEM
            # banner so passa se o total nunca foi conhecido: com total conhecido,
            # grid sem banner e pagina desenhada pela metade — e e dela que sai o
            # "sem link para a proxima" que encerrava a listagem em silencio.
            if res["rows"] and ((info and info.get("cur") == cur + 1) or (not info and total is None)):
                loaded = True
                break
        if not loaded:
            logger.warning(f"  {mun['nome']}: pagina {cur + 1} nao carregou (grid vazia/errada), parando em {len(all_rows)} linhas")
            break
        novos = 0
        for r in res["rows"]:
            k = _key(r)
            if k and k not in seen_keys:
                seen_keys.add(k); novos += 1
        all_rows.extend(res["rows"])
        itens_oficial = (res.get("info") or {}).get("items") or itens_oficial
        total = total or (res.get("info") or {}).get("total")
        cur += 1
        paginas += 1
        if novos == 0:
            break  # nada novo -> fim (evita loop se algo repetir)

    propostas = []
    seen_num = set()
    for row in all_rows:
        num = _clean(row["cols"][0])
        if not num or num in seen_num:
            continue
        seen_num.add(num)
        propostas.append({
            "numero_proposta": num,
            "situacao": _clean(row["cols"][1]),
            "orgao": _clean(row["cols"][2]),
            "proponente": _clean(row["cols"][3]),
            "possui_parecer": _clean(row["cols"][4]),
            "identificacao": _clean(row["cols"][5]),
            "_detalhe_url": row["href"],
        })
    logger.info(f"  {mun['nome']}: {paginas} pagina(s) -> {len(propostas)} propostas")

    # Valida completude contra o total oficial do banner do displaytag
    # ("Pagina X de Y (Z item(s))"). O Z sempre foi capturado e jogado fora:
    # paginacao que parava no meio (grid vazia, 'novos==0', janela quebrada)
    # saia como coleta normal — subcoleta SILENCIOSA com cara de sucesso, o
    # unico vetor real de "dado incompleto sem falha de job" do pipeline.
    # Registra no modulo p/ o chamador marcar a rodada como 'parcial'
    # (mesmo motivo do _HIST_ORC: nao muda a assinatura dos 3 call sites).
    # TOLERANCIA de max(2, 2%): `propostas` e DEDUPLICADA e filtrada (linha sem
    # numero/colunas cai fora), o Z conta itens brutos — uma divergencia
    # estavel de 1-2 itens marcaria o municipio como subcoleta em TODA visita
    # (letal no tenant de 1 municipio: nunca mais gravaria 'success').
    # Sem o Z (banner ausente), a referencia passa a ser o que o BANCO ja conhece
    # deste municipio — senao a trava fica cega exatamente no caso que a cegou em
    # 13/09 (ver o comentario do banner, la em cima).
    _conhecidas = 0 if itens_oficial else _propostas_conhecidas(mun["id"])
    _inc = _listagem_incompleta(len(propostas), itens_oficial, _conhecidas)
    if _inc:
        _esperado, _ref = _inc
        logger.warning(f"  {mun['nome']}: PAGINACAO INCOMPLETA — {len(propostas)} de "
                       f"{_esperado} proposta(s) ({_ref})")
        _PAGINACAO_INCOMPLETA[mun["id"]] = (len(propostas), _esperado)
    else:
        _PAGINACAO_INCOMPLETA.pop(mun["id"], None)

    # Modo rapido (re-run "carregar todos"): pula o enrich por-proposta (lento,
    # ~2.5s cada). As linhas-base (numero, situacao, orgao, proponente, parecer,
    # CNPJ) sao gravadas mesmo assim; o detalhe (valores/objeto/parlamentar) e
    # preenchido depois pelo cron diario. O detalhe ja existente e preservado
    # (upsert usa COALESCE). Mantemos id_proposta_siconv pois vem so da URL.
    if os.getenv("TG_SKIP_ENRICH") == "1":
        for prop in propostas:
            _u = prop.pop("_detalhe_url", None)
            _idp = _id_proposta_from_url(_u) if _u else None
            if _idp:
                prop["id_proposta_siconv"] = _idp
        logger.info(f"  {mun['nome']}: enrich pulado (TG_SKIP_ENRICH=1) — {len(propostas)} propostas base")
        return propostas

    # Enriquece cada proposta com o detalhe (Dados da Proposta).
    # Listagem e detalhe rodam na MESMA page (mesma sessao). Quando is_auth,
    # os links de detalhe sao logados → renderizam o botao Detalhar Clausula
    # Suspensiva + campos gated (parlamentar).
    # OTIMIZACAO: quando auth, prioriza propostas SEM enrich (janela curta).
    detail_page = page
    # Orçamento de capturas de Histórico por execução. Cada captura navega a área
    # /private/ das mandatárias (~12s); sem teto, as 3152 propostas do Freitas
    # dariam ~10h por rodada — inviável no host de 2 vCPU compartilhado. Com teto
    # + priorização das que ainda não têm histórico, cada rodada avança um naco e
    # o conjunto converge em poucos dias. 0 desliga a captura.
    # ⚠️ O orcamento e POR EXECUCAO (é o que este comentario sempre disse), e nao
    # por municipio. Ele vivia como variavel LOCAL desta funcao — que roda 1x por
    # municipio —, entao o freitas fazia 41 x 15 = 615 capturas do /private/ por
    # rodada (~12s cada = ~2h), e nao 15. Era a maior fonte isolada de estouro da
    # janela do cron. Agora o contador e compartilhado pela execucao inteira.
    _orc = _hist_orcamento()
    _hist_budget = _orc["restante"]
    if page_auth is not None:
        try:
            _ja_enriquecidos = _propostas_ja_enriquecidas(mun["id"])
            _sem_hist = _propostas_sem_historico(mun["id"])
            # Ordena por (sem enrich, sem histórico): as duas pendências vêm primeiro.
            propostas.sort(key=lambda p: (
                0 if p["numero_proposta"] not in _ja_enriquecidos else 1,
                0 if p["numero_proposta"] in _sem_hist else 1,
            ))
            n_pend = sum(1 for p in propostas if p["numero_proposta"] not in _ja_enriquecidos)
            n_hist = sum(1 for p in propostas if p["numero_proposta"] in _sem_hist)
            logger.info(f"  {mun['nome']}: {n_pend} propostas SEM enrich serao priorizadas | "
                        f"{n_hist} sem historico (orcamento desta rodada: {_hist_budget})")
        except Exception:
            pass
    # Skip incremental de ops_obs/obras: precomputa quais propostas ja foram
    # checadas recentemente (nao re-navegar). E GUEST, entao independe de page_auth.
    _ops_obs_on = (os.getenv("TG_OPS_OBS", "0") or "0").strip() == "1"
    try:
        _ops_obs_max_age = max(0, int(os.getenv("TG_OPS_OBS_MAX_AGE_DAYS", "3") or "3"))
    except ValueError:
        _ops_obs_max_age = 3
    _ops_obs_frescas = _propostas_ops_obs_frescas(mun["id"], _ops_obs_max_age) if _ops_obs_on else set()
    # ENRICH POR HTTP (TG_HTTP_ENRICH=1): mesmos dados sem Chromium — ~4s por
    # instrumento em vez de ~22s (validado campo-a-campo contra o browser). O
    # cliente e STATEFUL (contexto do convenio no servidor) -> um por municipio,
    # usado sequencialmente. Falha ao criar = segue no browser (fallback).
    _hx = None
    if (os.getenv("TG_HTTP_ENRICH", "0") or "0").strip() == "1":
        try:
            from ingestion.transferegov_http import TgHttpEnrich
            _hx = TgHttpEnrich(_load_govbr_cookies())
            logger.info(f"  {mun['nome']}: enrich via HTTP (sem browser)")
        except Exception as e:
            logger.warning(f"  {mun['nome']}: HTTP enrich indisponivel ({str(e)[:60]}) — usando browser")
            _hx = None
    # SKIP INCREMENTAL DO DETALHE — janela de 1 DIA, deliberadamente.
    #
    # O objetivo NAO e ler menos: e nao ler a MESMA proposta duas vezes no mesmo
    # dia. O lote roda 12x/dia; sem isso, cada proposta era renavegada 12 vezes
    # por dia (~3s cada) e nenhuma rodada terminava — o trust ficou 09/08 inteiro
    # com 10 rodadas e ZERO municipios carimbados (livelock).
    #
    # Com 1 dia, TUDO continua sendo relido todo dia. O que some e so o
    # desperdicio. Os campos em massa (situacao, valores, datas, vigencia,
    # assinatura, SIAFI, processo, programa, parlamentar, clausula) ja sao
    # atualizados DIARIAMENTE pela camada de dados abertos (CSV, sem navegador,
    # cron `transferegov`) — o navegador so acrescenta a fatia atras do login
    # (historico_comunicacoes, documentos_quadro_resumo, situacao_detalhe).
    #
    # Alem da idade, qualquer mudanca de `situacao` na LISTAGEM (barata, vem toda
    # rodada) invalida o skip na hora. TG_DETALHE_MAX_AGE_H=0 desliga tudo.
    #
    # A janela e em HORAS e o default e 18h: ela PRECISA ficar abaixo da cadencia
    # com que o rodizio volta ao mesmo municipio (ver _propostas_detalhe_frescas),
    # e a cadencia alvo com 6 municipios/rodada e ~20,7h. TG_DETALHE_MAX_AGE_DAYS
    # ainda e aceito (x24) so p/ rollback sem deploy.
    try:
        _dias = os.getenv("TG_DETALHE_MAX_AGE_DAYS")
        if _dias is not None and _dias.strip() != "":
            _det_max_age = max(0, int(_dias)) * 24
        else:
            _det_max_age = max(0, int(os.getenv("TG_DETALHE_MAX_AGE_H", "18") or "18"))
    except ValueError:
        _det_max_age = 18
    _det_frescas = _propostas_detalhe_frescas(mun["id"], _det_max_age)
    # O que o BANCO ja sabe sobre clausula/liminar, para o gate do Projeto Basico
    # nao depender so da leitura volatil da tela. INCONDICIONAL de proposito: o
    # bloco de pre-consultas logo acima so roda com `page_auth`, e esta captura
    # funciona tambem no caminho guest.
    _com_clausula = _propostas_com_clausula(mun["id"])
    _tot = len(propostas)
    _enr = 0
    _pulados = 0
    _SCRAPE_STATE["parcial"] = False
    _SCRAPE_STATE["restantes"] = 0
    for _i, prop in enumerate(propostas, 1):
        # Corte por orcamento: para limpo e devolve o que ja foi lido, em vez de
        # ser morto no meio pelo `timeout` externo (que perdia o carimbo do
        # municipio e reiniciava tudo na rodada seguinte).
        if deadline is not None and time.monotonic() >= deadline:
            _SCRAPE_STATE["parcial"] = True
            _SCRAPE_STATE["restantes"] = _tot - _i + 1
            logger.info(f"  {mun['nome']}: orcamento esgotado no detalhe "
                        f"{_i}/{_tot} — {_SCRAPE_STATE['restantes']} ficam p/ a proxima "
                        f"(o skip incremental retoma daqui)")
            break
        if _i % 10 == 0:
            logger.info(f"    {mun['nome']}: detalhe {_i}/{_tot} "
                        f"(enriquecidos: {_enr}, pulados: {_pulados})")
        url = prop.pop("_detalhe_url", None)
        if not url:
            continue
        # Detalhe fresco E situacao inalterada -> nao renavega. Guarda o
        # id_proposta_siconv (vem so da URL) antes de sair.
        _sit_grav = _det_frescas.get(prop["numero_proposta"])
        if _sit_grav is not None and _sit_grav == (prop.get("situacao") or ""):
            _idp_skip = _id_proposta_from_url(url)
            if _idp_skip:
                prop["id_proposta_siconv"] = _idp_skip
            _pulados += 1
            continue
        # Guarda o idProposta (da URL) -> casa com o open data siconv_emenda p/
        # backfill do parlamentar sem precisar do arquivo nacional de 199 MB.
        _idp = _id_proposta_from_url(url)
        if _idp:
            prop["id_proposta_siconv"] = _idp
        try:
            # DETALHE POR HTTP (TG_HTTP_DETALHE=1): o mesmo conteudo sem navegar
            # o Chromium — ~0,7s em vez de ~3s. E o que torna a releitura DIARIA
            # de todas as propostas possivel neste host: o trust (9.095 x 3s =
            # 7,6h/dia) nao cabe em janela nenhuma por browser, e por HTTP cai
            # p/ ~1,8h/dia. Sai pelo mesmo caminho do browser (o GET tambem seta
            # o contexto Struts). None/erro = cai no browser, sem perder rodada.
            det = None
            _via_http = False
            if _hx is not None and _idp and (os.getenv("TG_HTTP_DETALHE", "0") or "0").strip() == "1":
                try:
                    det = _hx.detalhe(str(_idp))
                    _via_http = det is not None
                except Exception as e:
                    logger.warning(f"    detalhe HTTP {prop['numero_proposta']}: {str(e)[:60]} — browser")
                    det = None
            if not _via_http:
                if not await _goto_with_retry(detail_page, url):
                    continue
                await detail_page.wait_for_timeout(700)  # perf: Struts server-rendered (HTML pronto no domcontentloaded)
                det = await _extrai_detalhe(detail_page)
            # Marca que o detalhe FOI lido nesta rodada -> _upsert carimba
            # detalhe_atualizado_em, e a proxima rodada pula esta proposta
            # enquanto a situacao da listagem nao mudar.
            prop["_detalhe_lido"] = True
            # Tenta capturar parlamentar (best-effort via texto livre na tela).
            # So no caminho browser: o parlamentar vem tambem do open data
            # (siconv_emenda) + backfill, entao a via HTTP nao perde o campo.
            if not _via_http:
                try:
                    parl = await _extrai_parlamentar(detail_page)
                    if parl:
                        det["_parlamentar"] = parl
                except Exception:
                    pass
            det.pop("_situacao_det_url", None)
            det.pop("_situacao_det_label", None)
            # Limpa U+FFFD de chaves e valores
            prop["detalhe"] = {
                _clean(k): (_clean(v) if isinstance(v, str)
                            else [_clean(x) for x in v] if isinstance(v, list) else v)
                for k, v in (det or {}).items()
            }
            # Detalhe da Clausula Suspensiva / Liminar Judicial (motivo + data
            # prevista). So existe quando a Situacao de Contratacao e clausula/
            # liminar E ha sessao autenticada com acesso ao instrumento. O botao
            # NAO fica na pagina da proposta — fica no INSTRUMENTO. Por isso
            # navegamos proposta->instrumento->Detalhar na page_auth (cookies).
            _sit = (prop["detalhe"].get("Situação de Contratação Atual")
                    or prop.get("situacao") or "")
            # ⚠️ "CONFERIDO, E NAO TEM MAIS" — o UNICO caso em que se pode APAGAR o
            # JSONB da clausula. A condicao e deliberadamente estreita:
            #
            #  - exige o campo do PORTAL lido NESTA rodada. NAO vale o fallback
            #    `prop.get("situacao")` da linha acima: aquilo e a situacao do
            #    CICLO ("Em execução"), que nunca casa com clausula e faria a
            #    limpeza disparar para a carteira INTEIRA;
            #  - exige valor NAO-VAZIO. Detalhe nao lido (TG_SKIP_ENRICH=1, skip
            #    incremental, falha de rede) chega aqui com "" e NAO limpa nada —
            #    "nao perguntei" continua preservando, que e o proposito do
            #    COALESCE no _upsert.
            #
            # Sem isto o JSONB era eterno: o CSV diario devolve "Normal" e zera as
            # colunas dedicadas (siconv_convenio_backfill, UPDATE sem COALESCE),
            # mas o JSONB — a unica fonte que o RM le — ficava congelado, e a caixa
            # ambar do relatorio apontava pendencia ja resolvida para sempre.
            if _sem_clausula_confirmado(prop["detalhe"].get("Situação de Contratação Atual")):
                prop["_clausula_conferida_sem"] = True
            # ⚠️ A NAVEGACAO STRUTS DA CLAUSULA SUSPENSIVA SAIU EM 09/09/2026.
            #
            # Aqui rodava `_extrai_clausula_via_instrumento(page_auth, _idp)`:
            # tres navegacoes Playwright por proposta (setar contexto -> abrir o
            # instrumento -> submit Struts `DetalharClausulaSuspensiva`), possivel
            # so com sessao gov.br viva. O resultado ia para o JSONB
            # `situacao_contratacao_detalhe`.
            #
            # MEDIDO no tenant freitas em 09/09/2026, depois que o coletor de
            # dado aberto passou a ler as quatro colunas de clausula do
            # `siconv_convenio.zip` (PR #464):
            #
            #   | propostas com detalhe de clausula | Struts 21 | dump 605 |
            #   | das 21 do Struts, cobertas pelo dump          | 21 de 21 |
            #   | casos que SO o Struts sabia                   | 0        |
            #   | data prevista batendo                         | 18 de 18 |
            #   | data de RETIRADA (clausula resolvida)         | so o dump|
            #
            # O JSONB tinha QUATRO chaves — Instrumento, Situacao Atual do
            # Contrato, Motivo e Data prevista — e todas as quatro tem coluna
            # equivalente no dump. O motivo diverge no VOCABULARIO, nao no
            # conteudo: a tela legada diz "Projeto Basico" e "Licenca Ambiental
            # Previa" onde o dump ja usa "Projeto de Engenharia" e "Licenciamento
            # Ambiental Previo".
            #
            # Ou seja: esta navegacao entregava 3,5% do que um CSV ja baixado
            # entrega sozinho, e cobrava por isso uma sessao gov.br viva — a
            # mesma que, ao morrer, parou a coleta gated dos SEIS tenants por
            # 169h sem alarme nenhum, porque um Chrome foi fechado.
            #
            # ⚠️ O JSONB NAO FOI APAGADO e continua sendo lido por rm_builder,
            # routers/transferegov, routers/parlamentares e pela tela do RM. Ele
            # simplesmente para de RECEBER dado novo: o que ja esta la segue
            # servindo de historico, e o dado novo chega pelas colunas, que o
            # `_pend_municipal` do RM ja consulta junto com o JSONB.
            # Processo de Execução (Licitações) — SÓ p/ contratação "Normal".
            # Convênio Normal em execução SEM licitação/processo registrado =
            # município parado (flag de monitoramento, destacado igual à cláusula).
            # Funciona em GUEST (detail_page já está no detalhe = contexto setado).
            if _idp and "normal" in _sit.lower():
                try:
                    if _hx:
                        # lista COM situacao por licitacao (URL direta server-rendered)
                        _lst = await asyncio.to_thread(_hx.processo_execucao_lista, _idp)
                        # 3o eixo do status: None = a fatia atras do login nao respondeu.
                        _gated_conta(True, _lst is not None)
                        if _lst is not None:
                            prop["processo_execucao_qtd"] = len(_lst)
                            prop["processo_execucao"] = _lst
                    else:
                        _qtd = await _conta_processo_execucao(detail_page)
                        if _qtd is not None:
                            prop["processo_execucao_qtd"] = _qtd
                except Exception as e:
                    logger.warning(f"    proc.exec {prop['numero_proposta']}: {str(e)[:80]}")
            # Projeto Básico/Termo de Referência — o espelho da regra acima, do
            # outro lado: para o convênio em CLÁUSULA SUSPENSIVA, o que o dono
            # quer saber é em que pé está o documento que a suspende (Termo de
            # Referência "Em Análise"). Até aqui o motivo da cláusula só dizia
            # QUAL documento falta; a situação dele não existia em lugar nenhum.
            # ⚠️ Depende da MESMA sessão do Processo de Execução (SP SAML
            # `execucao`): sem ela o portal devolve a página SAML e isto vira
            # None — nunca 0, nunca vazio. Só o caminho HTTP tem; quem chega aqui
            # sem _hx segue sem o campo e o COALESCE do upsert preserva o que já
            # havia. Perder o SP derruba a Licitação junto, e em silêncio.
            # ⚠️ O GATE OLHA DUAS FONTES, e nao so `_sit`. A leitura da tela e
            # volatil: o CSV diario do dado aberto sobrescreve
            # `situacao_contratacao` para "Normal" e o portal passa a responder o
            # mesmo, enquanto o JSONB da clausula (que o RM imprime) continua la,
            # congelado pelo COALESCE. Foi assim que o 981397/2025 ficou com a
            # caixa ambar no relatorio e SEM o status do Termo de Referencia.
            # `_com_clausula` e o espelho de rm_pdf._tem_clausula — coleta e
            # exibicao passam a usar o mesmo criterio.
            if _idp and _hx and (_RE_CLAUSULA.search(_sit)
                                 or prop["numero_proposta"] in _com_clausula):
                try:
                    _pb = await asyncio.to_thread(_hx.projeto_basico, _idp)
                    _gated_conta(True, _pb is not None)
                    if _pb is not None:
                        prop["projeto_basico"] = _pb
                    else:
                        # Distingue "nao perguntei" de "perguntei e nao veio". Sem
                        # esta linha, o SP `execucao` frio some sem deixar rastro —
                        # o retorno None nunca apaga (COALESCE), mas tambem nunca
                        # preenche, e a falha fica invisivel.
                        logger.info(f"    proj.basico {prop['numero_proposta']}: "
                                    "sem retorno (sessao do SP `execucao` fria?)")
                except Exception as e:
                    logger.warning(f"    proj.basico {prop['numero_proposta']}: {str(e)[:80]}")
            # NEs (Notas de Empenho, Execução Concedente). Ligado por TG_NES=1.
            #
            # ⚠️ O PORTÃO É O CÓDIGO DO INSTRUMENTO, e ele vem do DETALHE — não de
            # `prop`. `prop.get("codigo_instrumento")` NÃO EXISTE neste ponto: a
            # chave só nasce dentro do _upsert, derivada de `det`. Usá-la aqui
            # faria a coleta rodar em ZERO, sem erro e sem log.
            #
            # Só instrumento CELEBRADO tem nota de empenho, então o código é o
            # recorte natural — e é ele que segura o custo: sem o portão, seria um
            # GET a mais em TODA proposta, saindo do mesmo TG_BUDGET_S.
            if (_idp and _hx and prop["detalhe"].get("Código do Instrumento")
                    and (os.getenv("TG_NES", "0") or "0").strip() == "1"):
                try:
                    _ne = await asyncio.to_thread(_hx.notas_empenho, _idp)
                    _gated_conta(True, _ne is not None)
                    # ⚠️ ESTE BLOCO JA AFIRMOU O CONTRARIO, com carimbo de
                    # "medido", e a versao antiga mandava quem investigasse atras
                    # de ViewState. NAO ERA ISSO. O que existia era um defeito de
                    # PARSER (o cabecalho da grade nao esta na 1a linha) somado a
                    # o caminho do browser pedir a tela sem o contexto do
                    # instrumento. A explicacao inteira, com o que foi de fato
                    # demonstrado e o que nao foi, esta na docstring de
                    # `_extrai_notas_empenho`.
                    #
                    # A tentativa HTTP fica ANTES pelo custo: ~0,7s contra ~3s do
                    # browser. NAO afirmo aqui qual dos dois "resolve" — isso
                    # depende do que o portal devolver, e e justamente o tipo de
                    # afirmacao que envelheceu mal da ultima vez. O log de cada
                    # caminho diz o que aconteceu em cada rodada.
                    if _ne is None:
                        _ne = await _extrai_notas_empenho(page_auth, _idp)
                    if _ne is not None:
                        prop["notas_empenho"] = _ne
                    else:
                        logger.info(f"    NEs {prop['numero_proposta']}: sem retorno "
                                    "por HTTP nem pelo browser")
                except Exception as e:
                    logger.warning(f"    NEs {prop['numero_proposta']}: {str(e)[:80]}")
            # OPs/OBs (repasses/desembolsos) e OBRAS (acompanhamento/medicao).
            # Ambas GUEST (nao exigem sessao gov.br), mas cada uma navega o portal
            # por instrumento (~alguns s) — pesado no host burstable. Por isso a
            # coleta e ligada por env TG_OPS_OBS=1, hoje so no siao-worker
            # (ativado so p/ SIAO; os demais tenants nao gastam CPU com isto).
            #
            # ⚠️ SO INSTRUMENTO CELEBRADO — mesmo portão das NEs, logo acima, e
            # pela mesma razão. "Listagem de Repasses" e "Acompanhamento de
            # Obras" são telas de EXECUÇÃO: proposta que nunca virou convênio não
            # tem repasse nem obra, e o portal responde 200 com o resumo zerado
            # (ou, quando o contexto Struts não trocou, com o do instrumento
            # ANTERIOR). Era assim que voluntária sem desembolso ganhava aba
            # "OPs/OBs" na tela e caixa "Desembolsado: R$ 0,00" no RM.
            # De quebra corta ~2 GET por proposta não celebrada, do mesmo
            # TG_BUDGET_S, num host de 2 vCPU.
            # ⚠️ Lê `prop["detalhe"]`, NUNCA `prop["codigo_instrumento"]` — essa
            # chave só nasce dentro do _upsert e o portão rodaria em ZERO.
            if (_idp and _ops_obs_on
                    and prop["detalhe"].get("Código do Instrumento")
                    and prop["numero_proposta"] not in _ops_obs_frescas):
                try:
                    _oo = (await asyncio.to_thread(_hx.ops_obs, _idp)) if _hx \
                        else (await _extrai_ops_obs(detail_page))
                    if _oo is not None:
                        prop["ops_obs"] = _oo
                except Exception as e:
                    logger.warning(f"    ops_obs {prop['numero_proposta']}: {str(e)[:80]}")
                try:
                    _ob = (await asyncio.to_thread(_hx.obras, _idp)) if _hx \
                        else (await _extrai_obras(detail_page, _idp))
                    if _ob is not None:
                        prop["obras"] = _ob
                except Exception as e:
                    logger.warning(f"    obras {prop['numero_proposta']}: {str(e)[:80]}")
                # Carimba a checagem (mesmo vazia) -> sai do backlog, nao re-navega toda rodada.
                _stamp_ops_obs(mun["id"], prop["numero_proposta"])
            elif (_idp and _ops_obs_on
                    and not prop["detalhe"].get("Código do Instrumento")):
                # Log obrigatório: sem isto, "instrumento celebrado que perdeu a
                # chave para de coletar" seria indistinguível de "não celebrado".
                logger.info(f"    ops_obs/obras {prop['numero_proposta']}: "
                            "sem Código do Instrumento — não celebrada, pulando")
            # Historico de Comunicacoes + Termos de Notificacao (Projeto Basico /
            # mandatarias). SO com sessao gov.br viva (area /private/).
            if page_auth is not None and _idp and _orc["restante"] > 0:
                try:
                    # Debita o orçamento na TENTATIVA, não no sucesso: o custo de
                    # tempo já foi pago mesmo quando a página não devolve dados.
                    # Debita no contador da EXECUCAO (compartilhado entre municipios).
                    _orc["restante"] -= 1
                    _hc = (await asyncio.to_thread(_hx.historico, _idp)) if _hx \
                        else (await _captura_historico_comunicacoes(page_auth, _idp))
                    if _hc:
                        prop["historico_comunicacoes"] = _hc.get("historico") or []
                        prop["documentos_quadro_resumo"] = _hc.get("documentos") or []
                    if _hc is not None:
                        # Sessao viva e pagina /private/ consultada, MESMO sem eventos:
                        # marca como checada p/ sair do backlog e nao re-consumir o
                        # orcamento toda rodada (senao as propostas vazias represam os
                        # slots e o historico nunca converge). _hc None = sessao
                        # morta/erro de navegacao -> continua pendente p/ nova tentativa.
                        prop["_historico_checado"] = True
                except Exception as e:
                    logger.warning(f"    historico {prop['numero_proposta']}: {str(e)[:80]}")
            if det.get("_parlamentar") or prop["detalhe"].get("_situacao_detalhe"):
                _enr += 1
        except Exception as e:
            logger.warning(f"    detalhe {prop['numero_proposta']}: {str(e)[:80]}")
        # Persiste ESTA proposta ja — nao espera o fim do municipio. Assim o
        # progresso parcial sobrevive a um restart do container no meio da coleta:
        # municipios grandes fecham em pedacos, em vez de reiniciar do zero toda vez.
        try:
            _upsert(mun["id"], [prop])
        except Exception as e:
            logger.warning(f"    upsert incremental {prop['numero_proposta']}: {str(e)[:80]}")
    if _hx is not None:
        _hx.close()
    logger.info(f"  {mun['nome']}: enrich concluido — {_enr}/{_tot} propostas enriquecidas")
    return propostas


async def _extrai_situacao_detalhe(page) -> dict:
    """Pagina de detalhe da Situacao de Contratacao Atual (qualquer tipo).
    Captura todos os pares label:valor de forma generica, ignorando linhas
    de cabecalho/rodape e celulas vazias. Funciona para Clausula Suspensiva,
    Liminar Judicial, Pendencia etc."""
    return await page.evaluate("""() => {
        const out = {};
        document.querySelectorAll('tr').forEach(tr => {
            const tds = [...tr.querySelectorAll('td,th')].map(c => c.innerText.trim());
            if (tds.length === 2) {
                const k = tds[0]; const v = tds[1];
                if (k && v && k.length < 80 && v.length < 600 && !out[k]) out[k] = v;
            } else if (tds.length === 4) {
                for (const i of [0, 2]) {
                    const k = tds[i]; const v = tds[i + 1];
                    if (k && v && k.length < 80 && v.length < 600 && !out[k]) out[k] = v;
                }
            }
        });
        return out;
    }""")


_RE_CLAUSULA = re.compile(r"cl[áa]usula|suspensiv|liminar", re.I)

def _id_proposta_from_url(url: str) -> str | None:
    """Extrai idProposta=NNN da URL de detalhe (guest) p/ navegar o instrumento."""
    if not url:
        return None
    m = re.search(r"[?&]idProposta=(\d+)", url)
    return m.group(1) if m else None


def _dt_now():
    """Timestamp UTC (marca quando o historico foi capturado)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


async def _captura_historico_comunicacoes(page_auth, id_proposta: str) -> dict | None:
    """Captura o Historico numa PAGINA FRESCA do mesmo contexto autenticado.

    A page_auth compartilhada/longeva (reusada em navegacoes guest + Clausula do
    discricionarias) NAO estabelecia a sessao mandatarias /private/ no batch e
    todo _captura devolvia None em silencio (historico travava em 64/3160). Uma
    pagina NOVA no mesmo contexto (mesmos cookies, identica a sonda validada ao
    vivo: retorna eventos de forma confiavel) resolve. Fecha a pagina ao fim;
    fallback = usa a propria page_auth. Ver [[freitas-paridade-piloto]]."""
    try:
        pg = await page_auth.context.new_page()
    except Exception:
        return await _captura_historico_impl(page_auth, id_proposta)
    try:
        return await _captura_historico_impl(pg, id_proposta)
    finally:
        try:
            await pg.close()
        except Exception:
            pass


async def _captura_historico_impl(page_auth, id_proposta: str) -> dict | None:
    """Histórico de Comunicações + Documentos do Quadro Resumo (tela "Documentos
    Orçamentários" / Projeto Básico do TransfereGov **mandatárias**).

    Traz o andamento REAL da análise — eventos com SITUAÇÃO e CONSIDERAÇÕES do
    concedente (ex.: "Emitido Laudo de Análise", "Aceite realizado", parecer) —
    e os Termos de Notificação enviados.

    EXIGE sessão gov.br: a área e /private/ (guest cai no login). Retorna
    {'historico': [...], 'documentos': [...]} com eventos, {} se a página abriu
    autenticada porém SEM eventos (checada), ou None se a sessão caiu no login /
    a navegação falhou (não checada -> continua pendente p/ nova tentativa)."""
    url = ("https://mandatarias.transferegov.sistema.gov.br/projeto-basico/private/"
           f"index.jsf?idProposta={id_proposta}")
    if not await _goto_with_retry(page_auth, url, timeout=45000):
        return None
    await page_auth.wait_for_timeout(4000)
    cur_url = (page_auth.url or "")
    if "idp.transferegov" in cur_url or "sso.acesso.gov.br" in cur_url:
        return None  # sessao gov.br ausente/expirada -> caiu no login
    # PEGADINHA: a tela abre noutra aba e o Historico NAO esta no DOM inicial —
    # ele vive sob a aba "Quadro Resumo" (JSF/AJAX). Confirmado ao vivo: sem o
    # clique temHistorico=false/1 tabela; com o clique, true/4 tabelas.
    for _sel in ("a:has-text('Quadro Resumo')", "span:has-text('Quadro Resumo')",
                 "td:has-text('Quadro Resumo')", "li:has-text('Quadro Resumo')"):
        try:
            _tab = page_auth.locator(_sel).first
            if await _tab.count() > 0:
                await _tab.click(timeout=8000)
                await page_auth.wait_for_timeout(3500)
                break
        except Exception:
            continue
    try:
        data = await page_auth.evaluate("""() => {
            const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
            // Identifica a tabela pela ASSINATURA DO CABECALHO (robusto): buscar
            // pelo titulo nao funciona — "Historico de Comunicacoes" nao e um
            // elemento de texto puro no DOM (confirmado ao vivo).
            const tabelas = [...document.querySelectorAll('table')].map(t => {
                const rows = [...t.querySelectorAll('tr')];
                const heads = rows[0]
                    ? [...rows[0].querySelectorAll('th,td')].map(c => norm(c.textContent))
                    : [];
                return { t, rows, heads, chave: heads.join('|').toLowerCase() };
            });
            const acha = (...res) => {
                for (const x of tabelas) {
                    if (x.rows.length < 2) continue;
                    if (res.every(re => re.test(x.chave))) return x;
                }
                return null;
            };
            // ⚠️ COLUNA DE BOTAO NAO E DADO. A grade do portal tem uma coluna
            // "Ações" cujas celulas sao botoes do PrimeFaces, e `textContent`
            // devolve o ONCLICK inteiro como se fosse texto:
            //   Baixar arquivoPrimeFaces.cw("CommandButton","widget_tabView…
            // Isso era gravado no JSONB e a tela imprimia, campo a campo, num
            // modal que o gestor abre para LER o parecer. Relatado com print
            // (Arapuá/MG, 26/08/2026).
            //
            // Duas defesas, e a segunda e a que importa: o NOME da coluna pode
            // mudar (ou vir vazio), mas a assinatura do PrimeFaces no valor nao
            // engana. Vale para o historico tambem — os dois usam este `ler`.
            const ehAcao = (cab, val) =>
                /^\\s*a[çc][ãaõo](o|es)\\s*$/i.test(cab || '') ||
                /PrimeFaces\\.|CommandButton|widget_/.test(val || '');
            const ler = (x) => {
                if (!x) return [];
                const out = [];
                for (const r of x.rows.slice(1)) {
                    const cells = [...r.querySelectorAll('td')].map(c => norm(c.textContent));
                    if (!cells.length || cells.every(c => !c)) continue;
                    const o = {};
                    cells.forEach((c, i) => {
                        const cab = x.heads[i] || ('col' + i);
                        if (ehAcao(cab, c)) return;
                        o[cab] = c;
                    });
                    // Linha que so tinha botao nao vira registro vazio.
                    if (Object.keys(o).length) out.push(o);
                }
                return out;
            };
            // Historico: Data/Hora + Evento + Situacao + Consideracoes.
            // (exigir situacao+consideracoes exclui a tabela de "Sistema Externo",
            //  que tambem tem Data/Hora+Evento mas traz Resultado/Mensagem)
            const hist = acha(/data.?\\/?\\s?hora/, /evento/, /situa/, /considera/)
                      || acha(/data.?\\/?\\s?hora/, /evento/, /situa/);
            // Documentos do Quadro Resumo: Descricao + Tipo + Data de Envio
            const docs = acha(/descri/, /tipo/, /data de envio/);
            return { historico: ler(hist), documentos: ler(docs) };
        }""")
    except Exception:
        return None
    if not data:
        return None
    if not (data.get("historico") or data.get("documentos")):
        return {}  # pagina viva e consultada, porem SEM eventos -> checada (nao None)
    return data


async def _le_listagem_licitacoes(page) -> int | None:
    """N licitacoes na tela de Processo de Execucao, ou None se INDETERMINADO.

    None nao e "nenhuma": e "nao consegui ler". Quem chama nao deve gravar 0
    nesse caso — 0 vira o alerta de "contratacao Normal sem processo de
    execucao", e um 0 errado mente para o usuario."""
    try:
        return await page.evaluate("""() => {
            const body = document.body.innerText || '';
            // 1) TABELA de licitacoes pelo cabecalho — sinal PRIMARIO (antes vinha
            //    por ultimo; o /Nenhum registro/ largo abaixo disparava antes e
            //    zerava convenios com licitacao Concluida — o falso 0).
            for (const t of document.querySelectorAll('table')) {
                const rows = [...t.querySelectorAll('tr')];
                if (!rows.length) continue;
                const heads = [...rows[0].querySelectorAll('th,td')]
                    .map(c => (c.innerText || '').trim().toLowerCase()).join('|');
                if (heads.includes('processo de execu') &&
                    (heads.includes('data da public') || heads.includes('situa'))) {
                    return rows.slice(1).filter(r =>
                        [...r.querySelectorAll('td')].some(c => (c.innerText || '').trim())).length;
                }
            }
            // 2) marcador "(N item(s))"
            const m = body.match(/\\((\\d+)\\s*ite/i);
            if (m) return parseInt(m[1], 10);
            // 3) vazio ESTRITO (a frase completa, nao o largo)
            if (/Nenhum registro foi encontrado/i.test(body)) return 0;
            return null;   // indeterminado
        }""")
    except Exception:
        return None


async def _conta_processo_execucao(page) -> int | None:
    """Conta licitações/processos de execução do instrumento (Execução Convenente
    -> Processo de Execução). FUNCIONA EM GUEST (Acesso Livre) — confirmado ao vivo.

    Pré-condição: `page` já está na tela de DETALHE da proposta (o
    ResultadoDaConsultaDePropostaDetalharProposta.do já setou o contexto do
    convênio). Navega para destino=ListarLicitacoes e lê a listagem.

    Retorna: 0 (Nenhum registro — convênio Normal sem processo iniciado, flag),
    N (nº de registros), ou None se não conseguiu navegar/ler."""
    lic_url = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/"
               "ForwardAction.do?modulo=proposta&path=/SelecionarConvenio/"
               "SelecionarConvenio.do?destino=ListarLicitacoes")
    if not await _goto_with_retry(page, lic_url, timeout=40000):
        return None
    await page.wait_for_timeout(800)
    if not await page.locator("text=/Listagem de Licita|Processo de Execu/i").count():
        return None  # nao chegou na tela certa
    # A tela JA VEM POPULADA. Le daqui ANTES de qualquer submit.
    #
    # Antes o codigo clicava "Consultar" primeiro, na crenca de que a listagem so
    # populava apos o filtro. E o contrario: o submit DESTROI o resultado (volta
    # uma tela curta, sem a tabela) e a proposta virava 0 licitacoes em silencio.
    # Reproduzido no instrumento 993503 (proposta 011147/2026): a tela traz a
    # licitacao 102026, o submit a some, e gravavamos 0 — o alerta "sem processo
    # de execucao" ficava mentindo para o usuario.
    _lido = await _le_listagem_licitacoes(page)
    if _lido is not None:
        return _lido
    # Indeterminado: ai sim tenta o submit do filtro (fallback).
    try:
        btn = page.locator("input[value='Consultar'], button:has-text('Consultar')").first
        if await btn.count() > 0:
            await btn.click(timeout=8000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            await page.wait_for_timeout(300)  # perf: cushion apos networkidle
    except Exception:
        pass
    try:
        return await page.evaluate("""() => {
            const body = document.body.innerText || '';
            if (/Nenhum registro foi encontrado/i.test(body)) return 0;
            // displaytag: "Página X de Y (N item(s))"
            const m = body.match(/\\((\\d+)\\s*ite/i);
            if (m) return parseInt(m[1], 10);
            // linhas da tabela de resultados (exclui cabecalho)
            const t = document.querySelector('table.dataTable, table.listagem, table#listagem');
            if (t) { const r = t.querySelectorAll('tbody tr'); if (r.length) return r.length; }
            return null; // indeterminado -> NAO assume 0 (evita falso flag)
        }""")
    except Exception:
        return None


def _num_br(s):
    """'R$ 2.800.000,00' -> 2800000.0 ; None se não numérico."""
    if s is None:
        return None
    t = re.sub(r"[^\d,.-]", "", str(s)).replace(".", "").replace(",", ".")
    try:
        return float(t) if t not in ("", "-", ".") else None
    except ValueError:
        return None


async def _extrai_notas_empenho(page_auth, id_proposta: str) -> list | None:
    """NEs pelo BROWSER — a segunda tentativa, quando o HTTP não traz a grade.

    ⚠️ A EXPLICAÇÃO ANTERIOR DESTA DOCSTRING ESTAVA ERRADA, e vale registrar por
    quê. Ela afirmava que `listarEmpenhosNovoSiafi.jsf` "renderiza a tabela por
    POST com ViewState" e que o GET só devolve casca. Isso NUNCA foi demonstrado:
    nasceu de uma linha de diagnóstico que imprimia "1 tabela(s)" quando o número
    era, na verdade, "1 tabela COM TEXTO NA PRIMEIRA LINHA" — e uma grade
    RichFaces cuja linha 0 é um espaçador vazio não entrava naquela conta.

    O que está demonstrado (bancada, 25/08/2026):
      - o parser HTTP procurava o cabeçalho SÓ na primeira linha da tabela, e num
        `rich:dataTable` ele costuma estar na SEGUNDA. Com o cabeçalho na 2ª
        linha, o parser antigo devolve "não achei" para um HTML que CONTÉM a
        grade. Isso foi corrigido em `_le_notas_empenho`;
      - esta função navegava DIRETO para a `.jsf` sem estabelecer o contexto do
        instrumento — o `id_proposta` entrava e não era usado. O contexto vive na
        sessão do servidor e quem o estabelece é um GET no detalhe da proposta
        (`_seta_contexto`, do lado HTTP), que mora no cookie jar do httpx e NÃO
        alcança a página do Chromium. Ou seja: o browser pedia a tela de empenhos
        sem convênio selecionado, e recebia exatamente a casca que se via.

    Por isso agora ela faz as duas etapas, na ordem: detalhe (contexto) → grade.

    Devolve list (pode ser []) ou None. None = não consegui ler — e NUNCA apaga,

    Devolve list (pode ser []) ou None. None = não consegui ler — e NUNCA apaga,
    porque o `_upsert` é COALESCE. `[]` = a tela abriu e não há empenho.
    """
    # ⚠️ TODA SAÍDA `None` FALA. Escrever este caminho mudo foi repetir, no mesmo
    # dia, o defeito que o #286 tinha acabado de corrigir no caminho HTTP ("a
    # sexta saída era muda"): sabia-se que o browser desistia, não em que ponto.
    _lg = f"    NEs {id_proposta}"
    if page_auth is None:
        logger.info(f"{_lg}: sem página autenticada (lote sem browser) — nada olhado")
        return None

    _BASE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias"
    # ETAPA 1 — CONTEXTO. Sem isto o portal serve a tela de empenhos SEM convênio
    # selecionado, e é dessa casca que saiu a hipótese errada do "POST com
    # ViewState". É o equivalente, no browser, do `_seta_contexto` do lado HTTP —
    # que não serve aqui porque vive no cookie jar do httpx, não no Chromium.
    _det = (f"{_BASE}/ConsultarProposta/"
            f"ResultadoDaConsultaDePropostaDetalharProposta.do?idProposta={id_proposta}&")
    if not await _goto_with_retry(page_auth, _det, timeout=40000):
        logger.info(f"{_lg}: contexto — o detalhe da proposta não abriu")
        return None
    await page_auth.wait_for_timeout(900)
    _txt_det = (await page_auth.evaluate("() => document.body.innerText || ''")) or ""
    # ⚠️ 200 NÃO BASTA, pelo mesmo motivo documentado em `_seta_contexto`: o portal
    # serve o Principal.do com "Proposta não encontrada" também com 200, e aí o
    # contexto do instrumento ANTERIOR continua de pé — as NEs sairiam do convênio
    # errado, caladas. Pior que não coletar.
    if re.search(r"Proposta n.{0,2}o encontrada", _txt_det, re.I):
        logger.info(f"{_lg}: contexto — caiu em 'Proposta não encontrada'")
        return None

    # ETAPA 2 — a grade, agora com o instrumento selecionado na sessão.
    url = (f"{_BASE}/prestacao/_proposta/empenho/listarEmpenhosNovoSiafi.jsf"
           "?destino=ManterEmpenhoNovoSiafi")
    if not await _goto_with_retry(page_auth, url, timeout=40000):
        logger.info(f"{_lg}: a tela de empenhos não abriu")
        return None
    u = (page_auth.url or "").lower()
    if "idp.transferegov" in u or "sso.acesso" in u:
        logger.info(f"{_lg}: redirecionou para o login (sessão morta) — {u[:70]}")
        return None
    # ESPERA ANCORADA NA GRADE, e não um `wait_for_timeout` fixo. 1,2s era a menor
    # espera do arquivo para a tela mais pesada. ⚠️ Sem `networkidle`: esta tela
    # tem o contador de sessão do JSF, que faz XHR periódico e nunca deixa a rede
    # ficar ociosa — o wait não fecharia nunca.
    try:
        await page_auth.wait_for_selector("[id*='dtEmpenhos']", timeout=12000)
    except Exception:
        pass          # pode ser a tela vazia legítima; quem decide é o JS abaixo
    # A grade agora existe (o JSF renderizou). Sem ela, não afirmar nada.
    r_js = await page_auth.evaluate("""() => {
        const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
        const vazioDecl = /Nenhum registro foi encontrado/i.test(document.body.innerText || '');
        // ⭐ A GRADE PELO ID PRIMEIRO, varredura por texto so como queda — mesmo
        // critério do parser HTTP, e o mesmo id que o `wait_for_selector` espera.
        // `dtEmpenhos` é o único sinal que uma tabela de MOLDURA nunca tem.
        const tabelas = [...document.querySelectorAll("table[id*='dtEmpenhos' i]"),
                         ...document.querySelectorAll('table')];
        for (const t of tabelas) {
            // Linhas DIRETAS: `querySelectorAll('tr')` desce em tabela aninhada e
            // mistura as linhas da grade com as de um layout interno.
            const trs = [...t.querySelectorAll(':scope > thead > tr'),
                         ...t.querySelectorAll(':scope > tbody > tr'),
                         ...t.querySelectorAll(':scope > tr')];
            if (trs.length < 1) continue;
            // ⚠️ O CABEÇALHO PODE ESTAR NA 2ª LINHA — num rich:dataTable a linha 0
            // costuma ser um espaçador. Ler só trs[0] era o mesmo ponto cego do
            // parser HTTP, e descartava a grade inteira em silêncio.
            let iCab = -1, heads = [];
            for (let i = 0; i < Math.min(trs.length, 4); i++) {
                // ⚠️ `:scope >` — CÉLULAS DIRETAS, e este era o defeito. Com
                // descendentes (o que estava aqui), a linha da MOLDURA recebe as
                // próprias células MAIS todas as th/td da grade de dentro:
                // `h.length` passa de 10 e a guarda das 3 colunas NUNCA dispara.
                // O parser Python usa `./th|./td` desde sempre — os dois liam a
                // MESMA página de jeitos diferentes, e o browser é quem roda.
                const h = [...trs[i].querySelectorAll(':scope > th, :scope > td')].map(x => norm(x.innerText).toLowerCase());
                // `h.length >= 3` pelo mesmo motivo do parser HTTP: a tabela de
                // LAYOUT que envolve a grade tem UMA célula cujo texto achatado
                // contém a grade inteira — logo casa "empenho" e "situa" — e o
                // laço pararia nela, com zero linhas de dado.
                if (h.length < 3) continue;
                // Célula que contém tabela não é cabeçalho, seja qual for a
                // largura — mata a moldura por construção (espelha o Python).
                if (trs[i].querySelector(':scope > th table, :scope > td table')) continue;
                const k = h.join('|');
                if (/empenho/.test(k) && /situa/.test(k)) { iCab = i; heads = h; break; }
            }
            if (iCab < 0) continue;
            const col = f => { for (let i = 0; i < heads.length; i++) if (heads[i].includes(f)) return i; return null; };
            const iSiafi = col('siafi');
            let iVal = null;
            for (let i = 0; i < heads.length; i++) if (heads[i].includes('valor') && i !== iSiafi) { iVal = i; break; }
            const idx = {num: col('mero do empenho'), min: col('minuta'),
                         val: iVal, siafi: iSiafi, sit: col('situa'), dt: col('emiss')};
            const out = [];
            for (const tr of trs.slice(iCab + 1)) {
                // Mesma razão: uma célula que contenha uma tabelinha de botão
                // (`<td><table>Detalhar</table>2026NE000320</td>`) acrescentaria
                // células fantasma e deslocaria TODAS as colunas seguintes — o
                // valor de um empenho iria para o campo do número.
                const c = [...tr.querySelectorAll(':scope > td')].map(x => norm(x.innerText));
                if (!c.some(x => x)) continue;
                const g = i => (i !== null && i < c.length && c[i]) ? c[i] : null;
                out.push({numero: g(idx.num), minuta: g(idx.min), valor: g(idx.val),
                          valor_siafi: g(idx.siafi), situacao: g(idx.sit), dt_emissao: g(idx.dt)});
            }
            // ⚠️ `vazio_declarado` VAI JUNTO mesmo com a grade casada. Quem
            // decide se `[]` pode ser gravado é o Python, no portão logo depois
            // da chamada. Devolver `[]` daqui como resposta pronta era APAGAR
            // os empenhos: o `_upsert` é COALESCE e `[]` sobrescreve.
            return {linhas: out, cab_na_linha: iCab, vazio_declarado: vazioDecl};
        }
        // Não achou a grade: devolve o que VIU, para o log não ficar mudo.
        return {
            linhas: vazioDecl ? [] : null,
            vazio_declarado: vazioDecl,
            tabelas: tabelas.length,
            tem_dt: tabelas.some(t => /dtEmpenhos/i.test(t.id || '')),
            bytes: document.documentElement.outerHTML.length,
            saml: /Post Binding|SAMLResponse/i.test(document.documentElement.outerHTML),
            assinaturas: tabelas.slice(0, 5).map(t => (t.id || '?').slice(-26) + '::' +
                [...t.querySelectorAll(':scope > thead > tr, :scope > tbody > tr, :scope > tr')]
                    .slice(0, 3)
                    .map(tr => [...tr.querySelectorAll(':scope > th, :scope > td')].map(x => norm(x.innerText)).join('|').slice(0, 40))
                    .join('/')),
        };
    }""")
    r_js = r_js or {}
    linhas = r_js.get("linhas")
    if linhas is None:
        if r_js.get("saml"):
            logger.info(f"{_lg}: muro SAML na página ({r_js.get('bytes')} bytes) — "
                        "o SP `prestacao` está frio")
        else:
            logger.info(
                f"{_lg}: a grade não estava na página — {r_js.get('bytes')} bytes, "
                f"tabelas={r_js.get('tabelas')}, dtEmpenhos_no_dom={r_js.get('tem_dt')}, "
                f"assinaturas={(r_js.get('assinaturas') or [])[:3]}")
        return None
    # ⚠️⚠️ O PORTÃO QUE IMPEDE ESTE CAMINHO DE APAGAR. `[]` grava `'[]'` e o
    # COALESCE do `_upsert` sobrescreve os empenhos que já estavam lá; só `None`
    # preserva. E a interação era pior que o caso isolado: o browser SÓ roda
    # quando o HTTP devolveu `None` — inclusive quando esse `None` veio da guarda
    # gêmea do lado HTTP ("grade vazia sem confirmação"). Ou seja, o primeiro
    # leitor se recusava a apagar e o segundo apagava em seguida, no mesmo
    # instrumento e na mesma rodada.
    #
    # O portão fica AQUI, e não no JS, porque o filtro logo abaixo também pode
    # zerar `out` a partir de uma lista NÃO vazia (linha sem número e sem minuta).
    # Uma guarda só no JS não fecharia essa segunda porta.
    if not linhas and not r_js.get("vazio_declarado"):
        logger.info(f"{_lg}: a grade veio VAZIA e a página não diz 'Nenhum "
                    "registro foi encontrado' — indeterminado, não vou apagar")
        return None
    out = []
    for r in linhas:
        numero, minuta = r.get("numero"), r.get("minuta")
        if not numero and not minuta:
            continue
        sit = r.get("situacao")
        out.append({
            "numero": numero, "minuta": minuta,
            # `_num_br` roda em Python: o evaluate devolve só as strings da tela,
            # como em `_extrai_ops_obs`.
            "valor": _num_br(r.get("valor")), "valor_siafi": _num_br(r.get("valor_siafi")),
            "situacao": sit, "dt_emissao": r.get("dt_emissao"),
            # ⚠️ MINUTA NÃO É EMPENHO — a mesma marca que o leitor HTTP põe. A
            # listagem mistura o empenho com a minuta (sem número, R$ 1,00,
            # situação "Minuta de Empenho"), e somá-la põe R$ 1,00 no relatório
            # como se fosse recurso.
            "minuta_apenas": (not numero) or ("minuta" in (sit or "").casefold()),
        })
    # A SEGUNDA PORTA do mesmo portão: o filtro acima pode zerar `out` a partir de
    # uma lista NÃO vazia (linhas sem número e sem minuta — o rodapé "Voltar",
    # por exemplo). Chegar aqui com `out` vazio depois de ter lido linhas é sinal
    # de que a tabela era a errada, e afirmar `[]` apagaria os empenhos.
    if not out and not r_js.get("vazio_declarado"):
        logger.info(f"{_lg}: li {len(linhas)} linha(s) e nenhuma tinha número ou "
                    "minuta — tabela errada, não vou apagar")
        return None
    logger.info(f"{_lg}: {len(out)} linha(s) pelo browser "
                f"(cabeçalho na linha {r_js.get('cab_na_linha')})")
    return out


async def _extrai_ops_obs(page) -> dict | None:
    """OPs/OBs (Execução Concedente -> OPs/OBs -> Listagem de Repasses). GUEST.

    Pré-condição: `page` está no DETALHE da proposta (contexto do convênio setado).
    Lê o resumo (Valor Total de Repasse / Desembolsado / A Desembolsar / Data do
    último desembolso) e, clicando em 'OPs / OBs GERCOMP Efetuadas', as ordens
    bancárias (NS/OP/OB, valor, situação, data). Retorna dict ou None (sem
    contexto / sessão caiu). {} quando o convênio não tem repasses."""
    rep_url = ("https://discricionarias.transferegov.sistema.gov.br/voluntarias/"
               "ForwardAction.do?modulo=proposta&path=/SelecionarConvenio/"
               "SelecionarConvenio.do?destino=ListarRepasses")
    if not await _goto_with_retry(page, rep_url, timeout=40000):
        return None
    await page.wait_for_timeout(800)
    if "idp.transferegov" in (page.url or ""):
        return None
    if not await page.locator("text=/Listagem de Repasses/i").count():
        return None
    resumo = await page.evaluate("""() => {
        for (const t of document.querySelectorAll('table')) {
            if (/Valor Total de Repasse/i.test(t.innerText || '')) {
                const trs = [...t.querySelectorAll('tr')];
                for (const tr of trs) {
                    const c = [...tr.querySelectorAll('td')].map(x => x.innerText.trim());
                    if (c.length >= 4 && /R\\$/.test(c[0])) return c.slice(0, 4);
                }
            }
        }
        return null;
    }""")
    # _num_br roda em Python (page.evaluate devolve só as strings da tabela)
    out = {}
    if resumo:
        out = {
            "valor_total_repasse": _num_br(resumo[0]),
            "valor_desembolsado": _num_br(resumo[1]),
            "valor_a_desembolsar": _num_br(resumo[2]),
            "data_ultimo_desembolso": (resumo[3] or "").strip() or None,
            "obs": [],
        }
    # GERCOMP -> ordens bancárias detalhadas
    try:
        g = page.locator("input[value*='GERCOMP' i], a:has-text('GERCOMP')").first
        if await g.count():
            await g.click(timeout=8000)
            await page.wait_for_timeout(1200)
            det = await page.evaluate("""() => {
                const res = {resumo: {}, obs: []};
                for (const t of document.querySelectorAll('table')) {
                    const txt = t.innerText || '';
                    if (/Valor Previsto/i.test(txt) && /Valor Desembolsado/i.test(txt) && t.querySelectorAll('tr').length <= 4) {
                        for (const tr of t.querySelectorAll('tr')) {
                            const c = [...tr.querySelectorAll('td')].map(x => x.innerText.trim());
                            if (c.length === 2) res.resumo[c[0]] = c[1];
                        }
                    }
                    if (/N[úu]mero da OB/i.test(txt)) {
                        const rows = [...t.querySelectorAll('tr')];
                        for (const tr of rows) {
                            const c = [...tr.querySelectorAll('td')].map(x => x.innerText.trim());
                            if (c.length >= 10 && /\\dOB\\d|OB\\d/i.test(c[3] || '')) {
                                res.obs.push(c);
                            }
                        }
                    }
                }
                return res;
            }""")
            r = det.get("resumo") or {}
            if not out:
                out = {"obs": []}
            out.setdefault("valor_total_repasse", _num_br(r.get("Valor Previsto")))
            if out.get("valor_desembolsado") is None:
                out["valor_desembolsado"] = _num_br(r.get("Valor Desembolsado"))
            if out.get("valor_a_desembolsar") is None:
                out["valor_a_desembolsar"] = _num_br(r.get("Valor a Desembolsar"))
            for c in det.get("obs") or []:
                out["obs"].append({
                    "numero_interno": c[0], "numero_ns": c[1], "numero_op": c[2],
                    "numero_ob": c[3], "ug_emitente": c[4], "gestao_emitente": c[5],
                    "valor": _num_br(c[6]), "valor_acerto": _num_br(c[7]),
                    "situacao": c[8], "data_emissao_ob": c[9],
                })
    except Exception:
        pass
    # ⚠️ ZERO NAO E DADO — mesmo corte do caminho HTTP. Este e o caminho PADRAO
    # (TG_HTTP_ENRICH tem default "0"), entao sem ele a correcao valeria so p/
    # metade dos tenants. {} = "consultei e nao ha": o _upsert nao grava e o
    # COALESCE preserva.
    try:
        from ingestion.transferegov_http import _ops_obs_vazio
        if _ops_obs_vazio(out):
            return {}
    except Exception:
        pass
    return out or {}


async def _extrai_obras(page, id_proposta: str) -> dict | None:
    """OBRAS (Acompanhamento de Obras / medicao). Guest — a sessão Acesso Livre
    da discricionarias vale no medicao. Usa a API JSON /medicao-backend/...:
      - propostas/{id}/contratoslotes  -> lotes/CTEF + submetas
      - proposta/{id}/situacaoParalisacao
      - contratos/{idc}                -> dados do contrato + empresa
      - contratos/{idc}/arts/          -> ART/RRT
    Retorna dict com lotes (ou {} sem obras) ou None se não autenticou."""
    med = "https://medicao.transferegov.sistema.gov.br"
    base = f"{med}/medicao/acompanhamento/proposta/{id_proposta}"
    # A API do medicao exige o TOKEN que o SPA injeta (fetch cru dá 403 "sem
    # perfil"). Então NÃO chamamos a API direto: deixamos o próprio SPA chamar e
    # capturamos as respostas JSON via listener. A sessão Acesso Livre da
    # discricionarias autentica o SPA.
    capt: dict = {}

    async def _on_resp(resp):
        u = resp.url
        if "/medicao-backend/" not in u or "integrations" in u:
            return
        try:
            if "json" in (resp.headers.get("content-type") or ""):
                capt[u.split("/medicao-backend")[-1]] = await resp.json()
        except Exception:
            pass

    page.on("response", _on_resp)
    try:
        try:
            await page.goto(base, timeout=55000, wait_until="networkidle")
        except Exception:
            await page.goto(base, timeout=55000, wait_until="domcontentloaded")
        # perf: poll curto ate o /contratoslotes cair no listener, em vez de sleep
        # cego de 4s — apos networkidle o XHR ja costuma ter chegado (sai em <1s).
        for _ in range(20):
            if any("contratoslotes" in k for k in capt):
                break
            await page.wait_for_timeout(200)
        if "idp.transferegov" in (page.url or ""):
            return None  # sessão Acesso Livre não autenticou o medicao

        def _find(sufixo):
            for k, v in capt.items():
                if k.endswith(sufixo) or sufixo in k:
                    return v
            return None

        cl = _find(f"/propostas/{id_proposta}/contratoslotes")
        if not isinstance(cl, dict):
            return None
        data = cl.get("data") or {}

        # ART/RRT: navega a tela artrrt de cada contrato p/ o SPA disparar /arts/
        for cont in (data.get("contratosLotes") or []):
            if cont.get("tipo") == "C" and cont.get("id"):
                art_url = f"{base}/contrato/{cont['id']}/config/artrrt/listar"
                try:
                    await page.goto(art_url, timeout=45000, wait_until="networkidle")
                    await page.wait_for_timeout(1000)  # perf: cushion apos networkidle
                except Exception:
                    pass
    finally:
        page.remove_listener("response", _on_resp)

    par = capt.get(f"/proposta/{id_proposta}/situacaoParalisacao")
    par_desc = ((par or {}).get("data") or {}).get("descricao") if isinstance(par, dict) else None

    lotes = []
    for cont in (data.get("contratosLotes") or []):
        idc = cont.get("id")
        lote = {
            "tipo": cont.get("tipo"), "numero": cont.get("numero"),
            "id_contrato": idc, "apto_iniciar": cont.get("aptoIniciar"),
            "atrasado": cont.get("atrasado"), "paralisado": cont.get("paralisado"),
            "dias_sem_medicao": cont.get("qtdeDiasSemMedicao"),
            "submetas": [{
                "numero": s.get("numero"), "descricao": s.get("descricao"),
                "situacao": s.get("situacao"), "regime_execucao": s.get("regimeExecucao"),
                "valor": s.get("valorSubmeta"), "valor_realizado": s.get("valorRealizadoAcumulado"),
            } for s in (cont.get("submetas") or [])],
            # ⚠️ None = NAO LI; [] so quando a captura RESPONDEU e nao havia
            # ART. Ver o gemeo em transferegov_http.py — os DOIS leitores
            # gravavam [] nos dois casos, e o RM transformava a falha de
            # leitura numa ACUSACAO ao municipio.
            "contrato": None, "arts": None,
        }
        if cont.get("tipo") == "C" and idc:
            cd = capt.get(f"/contratos/{idc}")
            cdd = (cd or {}).get("data") if isinstance(cd, dict) else None
            if cdd:
                emp = None
                fid = cdd.get("fornecedorId")
                if fid:
                    ed = capt.get(f"/empresas/{fid}")
                    emp = ((ed or {}).get("data") or {}).get("razaoSocial") if isinstance(ed, dict) else None
                # O medicao devolve valorContrato como decimal US ("2562000.00"),
                # NÃO no formato BR — float() direto (nada de _num_br aqui).
                vc = cdd.get("valorContrato")
                try:
                    vc = float(vc) if vc not in (None, "") else None
                except (TypeError, ValueError):
                    vc = None
                lote["contrato"] = {
                    "numero": cdd.get("numeroContrato"), "cnpj": cdd.get("cnpj"),
                    "empresa": emp or cdd.get("nomeConvenente"),
                    "objeto": cdd.get("nomeObjetoContratoFornecimento"),
                    "valor": vc,
                    "dt_assinatura": cdd.get("dtAssinatura"),
                    "dt_inicio_vigencia": cdd.get("dtInicioVigencia"),
                    "dt_fim_vigencia": cdd.get("dtFimVigencia"),
                }
            ar = capt.get(f"/contratos/{idc}/arts/") or capt.get(f"/contratos/{idc}/arts")
            # SO promove para lista quando a captura respondeu (dict). Sem
            # resposta, `arts` fica None e o relatorio CALA em vez de acusar.
            if isinstance(ar, dict):
                lote["arts"] = [{
                    "tipo": a.get("tipo"), "numero": a.get("numeroArt") or a.get("numero"),
                    "dt_emissao": a.get("dtEmissao"),
                    "responsavel_tecnico": a.get("nomeResponsavelTecnico") or a.get("responsavelTecnico"),
                    "submetas": a.get("submetas"),
                } for a in (ar.get("data") or [])]
        lotes.append(lote)

    if not lotes:
        return {}
    ti = data.get("tipoInstrumento") or {}
    return {
        "situacao_paralisacao": par_desc,
        "valor_total_submetas": data.get("valorTotalSubmetas"),
        "valor_total_realizado": data.get("valorTotalRealizado"),
        "objeto": ti.get("nomeObjetoContratoRepasse"),
        "lotes": lotes,
    }


async def _extrai_parlamentar(page) -> str | None:
    """Tenta extrair parlamentar/autor da indicacao. Combina abordagens:
      1) Procura em <tr> com 2 ou 4 celulas (label-valor)
      2) Procura em texto livre por varios padroes
      3) Tenta seguir botao 'Histórico de Indicações' / 'Indicações Parlamentares'
         na pagina de detalhe, se aparecer (best-effort, ignora se nao houver)."""
    parl = await page.evaluate("""() => {
        const LABELS = [
            'Autor da Emenda', 'Parlamentar', 'Nome do Autor', 'Indica',
            'Nome do Parlamentar', 'Autor', 'Indicado por',
            'Parlamentar Indicador', 'Beneficiario da Emenda',
        ];
        const cleanVal = (v) => {
            v = (v || '').replace(/\\s+/g, ' ').trim();
            if (!v) return null;
            if (v.length < 5 || v.length > 200) return null;
            // descarta sentinelas e valores nao-nome
            if (/^(numero|data|valor|tipo|sim|n[ãa]o|n[/.]\\s*a|\\-+|0+)$/i.test(v)) return null;
            // descarta datas (DD/MM/YYYY) e numeros puros
            if (/^\\d{1,2}\\/\\d{1,2}\\/\\d{2,4}$/.test(v)) return null;
            if (/^[\\d.,\\s]+$/.test(v)) return null;
            // descarta funcional programatica e codigos longos sem espaco
            if (/^\\d{6,}/.test(v)) return null;
            // exige PELO MENOS 2 palavras com letras (nomes proprios tem nome+sobrenome)
            const palavras = v.split(/\\s+/).filter(w => /[A-Za-zÀ-ú]{2,}/.test(w));
            if (palavras.length < 2) return null;
            // exige pelo menos uma letra maiuscula (nome proprio)
            if (!/[A-ZÀ-Ú]/.test(v)) return null;
            return v;
        };

        // 1) Tabelas label:valor
        const trs = [...document.querySelectorAll('tr')];
        for (const tr of trs) {
            const tds = [...tr.querySelectorAll('td,th')].map(c => c.innerText.trim());
            if (tds.length === 2 && LABELS.some(l => tds[0].toLowerCase().includes(l.toLowerCase()))) {
                const v = cleanVal(tds[1]);
                if (v) return v;
            } else if (tds.length === 4) {
                for (const i of [0, 2]) {
                    if (LABELS.some(l => tds[i].toLowerCase().includes(l.toLowerCase()))) {
                        const v = cleanVal(tds[i+1]);
                        if (v) return v;
                    }
                }
            }
        }

        // 2) Texto livre (regex)
        const txt = document.body.innerText;
        const patterns = [
            /Autor\\s+da\\s+Emenda\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Parlamentar(?:\\s+Indicador)?\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Nome\\s+do\\s+(?:Autor|Parlamentar)\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Indica[çc][ãa]o\\s+Parlamentar\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Indicado\\s+por\\s*[:\\n]\\s*([^\\n]{3,120})/i,
            /Benefici[áa]rio\\s+da\\s+Emenda\\s*[:\\n]\\s*([^\\n]{3,120})/i,
        ];
        for (const re of patterns) {
            const m = txt.match(re);
            if (m) {
                const v = cleanVal(m[1]);
                if (v) return v;
            }
        }
        return null;
    }""")
    if parl:
        return parl
    # Fallback: tenta clicar em "Histórico de Indicações" / "Emendas"
    try:
        link = page.locator(
            "xpath=//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'indica')] | "
            "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'emenda')]"
        ).first
        if await link.count() > 0:
            href = await link.get_attribute("href")
            if href and "javascript" not in href.lower():
                cur = page.url
                await page.goto(href, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2500)
                p2 = await page.evaluate("""() => {
                    const trs=[...document.querySelectorAll('tr')];
                    for (const tr of trs) {
                        const tds=[...tr.querySelectorAll('td,th')].map(c=>c.innerText.trim());
                        // procura linha que comece com nome de parlamentar
                        for (const t of tds) {
                            const m = t.match(/(?:Deputad[oa]|Senador[a]?|Vereador[a]?|Dr\\.|Dra\\.)\\s+([A-Z][A-ZÀ-Úa-zà-ú\\s'.-]{4,80})/i);
                            if (m) return m[0].trim();
                        }
                    }
                    return null;
                }""")
                await page.goto(cur, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                if p2:
                    return p2
    except Exception:
        pass
    return None


async def _extrai_detalhe(page) -> dict:
    """Captura todos os pares label:valor + campos do topo da tela Dados da Proposta."""
    return await page.evaluate("""() => {
        const out = {};
        // Espelho de `transferegov_http._parece_rotulo` — ver o comentario longo
        // la. Resumo: este laco varre TODAS as linhas de 2 ou 4 celulas da pagina
        // sem saber de que tabela vieram, entao ano do cronograma e nome de
        // arquivo da grade de documentos viravam CHAVE DE TOPO do detalhe (224
        // chaves-lixo nas 83 propostas de Araujos). A regra e sobre a FORMA do
        // rotulo: tem letra, nao e so numero, nao e nome de arquivo.
        const pareceRotulo = (k) => {
            const s = (k || '').trim();
            if (!s) return false;
            if (/^[\\d\\s.,/:%-]+$/.test(s)) return false;
            if (/\\.(pdf|docx?|xlsx?|jpe?g|png|zip|p7s|txt|csv)\\s*$/i.test(s)) return false;
            return /[A-Za-zÀ-ÿ]/.test(s);
        };
        const setKV = (k, v) => {
            if (k && k.length < 70 && v && !out[k] && pareceRotulo(k)) out[k] = v.slice(0, 600);
        };
        // Pares label|valor: linhas com 2 OU 4 celulas (label|valor|label|valor)
        document.querySelectorAll('tr').forEach(tr => {
            const tds = [...tr.querySelectorAll('td,th')];
            if (tds.length === 2) {
                setKV(tds[0].innerText.trim(), tds[1].innerText.trim());
            } else if (tds.length === 4) {
                setKV(tds[0].innerText.trim(), tds[1].innerText.trim());
                setKV(tds[2].innerText.trim(), tds[3].innerText.trim());
            }
        });
        // Campos do topo (Modalidade, Situacao SIAFI, Codigo Instrumento, etc) - layout em divs/spans
        const txt = document.body.innerText;
        const grab = (label) => {
            const re = new RegExp(label + '\\\\s*[:\\\\n]\\\\s*([^\\\\n]{1,120})', 'i');
            const m = txt.match(re);
            return m ? m[1].trim() : null;
        };
        for (const lbl of ['Modalidade','Situação no SIAFI','Código do Instrumento',
                           'Número da Proposta','Número do Processo','Situação de Contratação Atual']) {
            const v = grab(lbl);
            if (v && !out[lbl]) out[lbl] = v;
        }
        // Valores monetarios (Valor Global/Repasse/Contrapartida) - podem estar em
        // tabelas financeiras com layout variado; busca o proximo R$ apos o rotulo.
        const grabMoney = (label) => {
            const re = new RegExp(label + '[\\\\s\\\\S]{0,40}?(R\\\\$\\\\s*[\\\\d.]+,\\\\d{2})', 'i');
            const m = txt.match(re);
            return m ? m[1].trim() : null;
        };
        const moneyLabels = {
            'Valor Global': ['Valor Global do Instrumento','Valor Global'],
            'Valor de Repasse': ['Valor de Repasse da União','Valor de Repasse','Valor do Repasse'],
            'Valor de Contrapartida': ['Valor da Contrapartida','Valor de Contrapartida','Valor Contrapartida'],
        };
        for (const [outKey, variants] of Object.entries(moneyLabels)) {
            for (const lbl of variants) {
                const v = grabMoney(lbl);
                if (v) { out[outKey] = v; break; }
            }
        }
        // Botao "Detalhar Clausula Suspensiva/Liminar Judicial".
        // Busca na PAGINA INTEIRA (nao so numa linha especifica) qualquer
        // anchor/button cujo onclick/href/texto aponte para o detalhe da
        // CLAUSULA SUSPENSIVA (ou liminar judicial). Ignora "Detalhar" generico
        // de habilitacao etc. Extrai a URL do onclick (location.href='...').
        try {
            const extractUrl = (el) => {
                let url = el.href || '';
                if (!url || url.toLowerCase().startsWith('javascript')) {
                    const oc = el.getAttribute('onclick') || '';
                    // location.href='...'  ou  window.location='...'
                    const m = oc.match(/(?:location\\.href|window\\.location)\\s*=\\s*['"]([^'"]+)['"]/i)
                            || oc.match(/['"]([^'"]*Detalhar[^'"]*)['"]/i);
                    if (m) {
                        url = m[1];
                        if (!url.startsWith('http')) {
                            url = (url.startsWith('/') ? location.origin : location.origin + '/voluntarias/execucao/') + url.replace(/^\\//, '');
                        }
                    }
                }
                return url;
            };
            const isClausula = (s) => /clausula|cláusula|suspensiva|liminar/i.test(s || '');
            const cands = [...document.querySelectorAll('a, input[type="button"], button')];
            let chosen = null;
            // 1) prioridade: onclick/href aponta p/ DetalharClausulaSuspensiva
            for (const el of cands) {
                const oc = (el.getAttribute('onclick') || '') + ' ' + (el.href || '');
                if (/detalharclausulasuspensiva|clausulasuspensiva|liminarjudicial/i.test(oc)) { chosen = el; break; }
            }
            // 2) fallback: texto "Detalhar ... Clausula/Suspensiva/Liminar"
            if (!chosen) {
                for (const el of cands) {
                    const t = (el.value || el.innerText || '').trim();
                    if (/detalhar/i.test(t) && isClausula(t)) { chosen = el; break; }
                }
            }
            // 3) fallback final: dentro de uma linha que mencione contratacao + clausula
            if (!chosen) {
                const row = [...document.querySelectorAll('tr')].find(tr =>
                    isClausula(tr.innerText) && /detalhar/i.test(tr.innerText));
                if (row) chosen = row.querySelector('a, input[type="button"], button');
            }
            if (chosen) {
                const url = extractUrl(chosen);
                const label = (chosen.value || chosen.innerText || '').trim();
                if (url && /detalhar|clausula|suspensiva|liminar/i.test(url + label)) {
                    out['_situacao_det_url'] = url;
                    if (label) out['_situacao_det_label'] = label.slice(0, 80);
                }
            }
        } catch (e) { /* ignore */ }
        // Documentos digitalizados (nomes dos PDFs)
        const docs = [];
        document.querySelectorAll('a').forEach(a => {
            const t = (a.innerText||'').trim();
            if (t.toLowerCase().includes('baixar') && a.closest('tr')) {
                const row = a.closest('tr').innerText.replace(/\\s+/g,' ').trim();
                if (row.includes('.pdf') || row.toLowerCase().includes('.pdf')) docs.push(row.slice(0,160));
            }
        });
        if (docs.length) out['_documentos'] = docs;
        // Situacao macro (campo destacado)
        const sitM = txt.match(/Situação\\s*\\n\\s*([^\\n]+)/);
        if (sitM) out['_situacao_macro'] = sitM[1].trim().slice(0,100);
        return out;
    }""")


def _upsert(mun_id: int, propostas: list[dict]):
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "")
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    conn = psycopg2.connect(url); cur = conn.cursor()
    ins = 0
    for p in propostas:
        if not p.get("numero_proposta"):
            continue
        det = p.get("detalhe") or {}
        def g(*keys):
            for k in keys:
                if det.get(k):
                    return str(det[k])
            return None
        codigo_instr = g("Código do Instrumento")
        # ⚠️ CORTA NO PRIMEIRO TAB/QUEBRA. O extrator devolve a celula do rotulo
        # MAIS o par rotulo/valor seguinte da mesma linha da tabela, colados por
        # TAB. Medido em Araujos (30/08/2026): 27 de 83 propostas gravaram coisas
        # como "Contrato de Repasse\tEnviada para mandatária?\tNÃ£o", e 21 delas
        # ainda carregavam o acento duplamente codificado do pedaco extra.
        #
        # O `rm_builder._e_termo_compromisso` ja se defendia cortando no TAB
        # (rm_builder.py:1042) — a defesa existia no CONSUMIDOR e faltava na
        # origem, entao a sujeira seguia na coluna esperando o proximo leitor que
        # nao soubesse dela. Cortar aqui e um `split`, e o dado aberto (que e
        # autoritativo para este campo) continua corrigindo o resto.
        modalidade = _primeiro_campo(g("Modalidade"))
        situacao_siafi = g("Situação no SIAFI")
        num_processo = g("Número do Processo")
        objeto = g("Objeto do Instrumento")
        programa = g("Programa", "Nome do Programa")
        # Só a data: a célula pode trazer o campo seguinte colado (ver `_data_br`).
        dt_ini_vig = _data_br(g("Data Início de Vigência"))
        dt_fim_vig = _data_br(g("Data Término de Vigência Atual", "Data Término de Vigência"))
        dt_prop = _data_br(g("Data da Proposta"))
        dt_assin = _data_br(g("Data Assinatura"))
        valor_global = _money(g("Valor Global", "Valor Global do Instrumento"))
        valor_repasse = _money(g("Valor de Repasse", "Valor de Repasse da União", "Valor do Repasse"))
        valor_contrap = _money(g("Valor de Contrapartida", "Valor da Contrapartida"))
        # ⚠️ A TRAVA DE COERENCIA. Ponto UNICO de escrita dos tres valores — os
        # dois leitores (HTTP e navegador) desaguam aqui, entao uma guarda so
        # cobre os dois. Trio que nao fecha a soma NAO E GRAVADO, e os TRES viram
        # None de uma vez: gravar so o que "parece bom" deixaria um valor
        # deslocado ao lado de um correto, que e pior de detectar.
        #
        # None faz o COALESCE do upsert PRESERVAR o que ja esta na coluna — e o
        # que esta la vem do CSV de dados abertos, a fonte autoritativa declarada
        # para estes campos. Sem isto, o lote de 2 em 2 horas RE-CORROMPIA o que
        # o dump oficial tinha acabado de consertar: o COALESCE so protege contra
        # NULL, e valor errado nao-nulo vence valor bom.
        if not valores_coerentes(valor_global, valor_repasse, valor_contrap):
            if valor_global is not None or valor_repasse is not None:
                _log_incoerente(p.get("numero_proposta"), valor_global,
                                valor_repasse, valor_contrap)
            valor_global = valor_repasse = valor_contrap = None
            # ⚠️ E O MESMO DINHEIRO SAI DO `detalhe`, NAO SO DAS COLUNAS.
            #
            # A trava acima nasceu protegendo as tres COLUNAS, e nisso ela
            # funciona. Mas o `det` seguia sendo gravado inteiro, com os valores
            # deslocados dentro dele. Medido em Araujos (30/08/2026): 83 de 83
            # propostas tinham o trio trocado no JSONB — "Valor Global" com o
            # repasse, "Valor de Repasse" com a contrapartida — e 61 tinham sido
            # regravadas naquele mesmo dia. Nao era passivo antigo: era o mesmo
            # numero errado sendo reescrito a cada rodada, ao lado de uma coluna
            # certa, esperando alguem ler o blob em vez da coluna.
            #
            # Apagar em vez de corrigir e deliberado. O `detalhe` e o que a
            # PAGINA disse; consertar o valor aqui inventaria uma leitura que
            # nunca houve. Quem precisa do numero tem as colunas ao lado, que vem
            # do CSV oficial. O marcador deixa o silencio auditavel — sem ele,
            # "nao tem valor no detalhe" seria indistinguivel de "nunca li".
            _sujos = [k for k in ("Valor Global", "Valor de Repasse",
                                  "Valor de Contrapartida") if k in det]
            if _sujos:
                for k in _sujos:
                    det.pop(k, None)
                det["_valores_descartados"] = _sujos
        situacao_contr = g("Situação de Contratação Atual")
        parlamentar = g("_parlamentar")
        # Detalhe generico da situacao de contratacao (qualquer tipo)
        sd = det.get("_situacao_detalhe") if isinstance(det.get("_situacao_detalhe"), dict) else {}
        sit_det_json = sd if sd else None
        # Deriva campos especificos de Clausula Suspensiva quando aplicavel
        cl_dt = None
        cl_motivo = None
        if sd:
            import re as _re
            from datetime import datetime as _dt
            for k, v in sd.items():
                if not isinstance(v, str):
                    continue
                kl = k.lower()
                if ("data" in kl and "prevista" in kl) or ("prazo" in kl):
                    m = _re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", v.strip())
                    if m:
                        try:
                            cl_dt = _dt(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
                        except (ValueError, TypeError):
                            pass
                elif "motivo" in kl:
                    cl_motivo = v.strip() or None
        cur.execute("""
            INSERT INTO transferegov_propostas
                (municipio_id, numero_proposta, situacao, orgao, proponente,
                 possui_parecer, identificacao, codigo_instrumento, modalidade,
                 situacao_siafi, numero_processo, objeto, programa,
                 dt_inicio_vigencia, dt_fim_vigencia, dt_proposta, dt_assinatura,
                 valor_global, valor_repasse, valor_contrapartida,
                 situacao_contratacao, clausula_suspensiva_dt_prevista,
                 clausula_suspensiva_motivo, parlamentar, situacao_contratacao_detalhe,
                 id_proposta_siconv, processo_execucao_qtd, processo_execucao,
                 projeto_basico, notas_empenho,
                 historico_comunicacoes, documentos_quadro_resumo, historico_atualizado_em,
                 ops_obs, obras, detalhe_atualizado_em,
                 detalhe, raw_data, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s::jsonb,NOW())
            ON CONFLICT (municipio_id, numero_proposta) DO UPDATE SET
                situacao=EXCLUDED.situacao, orgao=EXCLUDED.orgao,
                proponente=EXCLUDED.proponente, possui_parecer=EXCLUDED.possui_parecer,
                identificacao=EXCLUDED.identificacao,
                -- Os 10 campos abaixo vem do DETALHE (g(...) no topo desta funcao),
                -- que so existe quando o enrich roda. O cron diario roda com
                -- TG_SKIP_ENRICH=1 e chega aqui com detalhe VAZIO — com atribuicao
                -- direta isso GRAVAVA NULL e APAGAVA o que o enrich tinha capturado.
                -- Observado ao vivo: o siao perdeu os 41 codigo_instrumento (e
                -- modalidade/siafi/processo/programa) na rodada das 18:00; sobreviveram
                -- so as colunas que ja usavam COALESCE (valores, proc_execucao).
                -- COALESCE aqui = "nao apaga o que ja sabemos quando a fonte nao veio".
                codigo_instrumento=COALESCE(EXCLUDED.codigo_instrumento, transferegov_propostas.codigo_instrumento),
                modalidade=COALESCE(EXCLUDED.modalidade, transferegov_propostas.modalidade),
                situacao_siafi=COALESCE(EXCLUDED.situacao_siafi, transferegov_propostas.situacao_siafi),
                numero_processo=COALESCE(EXCLUDED.numero_processo, transferegov_propostas.numero_processo),
                objeto=CASE WHEN EXCLUDED.objeto IS NULL
                              OR position(chr(65533) in EXCLUDED.objeto) > 0
                            THEN transferegov_propostas.objeto ELSE EXCLUDED.objeto END,
                programa=COALESCE(EXCLUDED.programa, transferegov_propostas.programa),
                dt_inicio_vigencia=COALESCE(EXCLUDED.dt_inicio_vigencia, transferegov_propostas.dt_inicio_vigencia),
                dt_fim_vigencia=COALESCE(EXCLUDED.dt_fim_vigencia, transferegov_propostas.dt_fim_vigencia),
                dt_proposta=COALESCE(EXCLUDED.dt_proposta, transferegov_propostas.dt_proposta),
                dt_assinatura=COALESCE(EXCLUDED.dt_assinatura, transferegov_propostas.dt_assinatura),
                -- ⚠️ A COLUNA VEM PRIMEIRO: o scraper so PREENCHE O VAZIO, nunca
                -- sobrescreve. Isto e a consequencia de uma frase que ja estava
                -- escrita no `valores_coerentes` e que o codigo nao obedecia: "o
                -- CSV de dados abertos e a fonte AUTORITATIVA declarada para
                -- estes tres campos".
                --
                -- Com o EXCLUDED na frente, a trava de coerencia so parava o
                -- trio que NAO FECHA. Um deslocamento que por acaso FECHA
                -- atravessava e sobrescrevia o valor certo do CSV. Caso medido
                -- (30/08/2026, 053238/2015 de Araujos): portal
                -- 150.000/100.000/50.000, tela 100.000/50.000/50.000 — e
                -- 50.000 + 50.000 = 100.000, entao a trava aprovou. Pior: o cron
                -- das 06:50 regravava o valor certo do CSV e o lote de 2 em 2
                -- horas regravava o errado de volta, duas vezes por dia.
                --
                -- E a mesma inversao do #328 (vigencia), na direcao contraria:
                -- la a TELA e a fonte da verdade, aqui e o CSV. O criterio nao e
                -- "quem roda por ultimo", e quem a fonte declara como dono.
                --
                -- Proposta NOVA, que o CSV ainda nao cobre, continua nascendo com
                -- o valor da tela: a coluna esta vazia e o COALESCE cai nele.
                valor_global=COALESCE(transferegov_propostas.valor_global, EXCLUDED.valor_global),
                valor_repasse=COALESCE(transferegov_propostas.valor_repasse, EXCLUDED.valor_repasse),
                valor_contrapartida=COALESCE(transferegov_propostas.valor_contrapartida, EXCLUDED.valor_contrapartida),
                situacao_contratacao=COALESCE(EXCLUDED.situacao_contratacao, transferegov_propostas.situacao_contratacao),
                clausula_suspensiva_dt_prevista=COALESCE(EXCLUDED.clausula_suspensiva_dt_prevista, transferegov_propostas.clausula_suspensiva_dt_prevista),
                clausula_suspensiva_motivo=COALESCE(EXCLUDED.clausula_suspensiva_motivo, transferegov_propostas.clausula_suspensiva_motivo),
                parlamentar=COALESCE(EXCLUDED.parlamentar, transferegov_propostas.parlamentar),
                situacao_contratacao_detalhe=COALESCE(EXCLUDED.situacao_contratacao_detalhe, transferegov_propostas.situacao_contratacao_detalhe),
                id_proposta_siconv=COALESCE(EXCLUDED.id_proposta_siconv, transferegov_propostas.id_proposta_siconv),
                processo_execucao_qtd=COALESCE(EXCLUDED.processo_execucao_qtd, transferegov_propostas.processo_execucao_qtd),
                processo_execucao=COALESCE(EXCLUDED.processo_execucao, transferegov_propostas.processo_execucao),
                projeto_basico=COALESCE(EXCLUDED.projeto_basico, transferegov_propostas.projeto_basico),
                notas_empenho=COALESCE(EXCLUDED.notas_empenho, transferegov_propostas.notas_empenho),
                historico_comunicacoes=COALESCE(EXCLUDED.historico_comunicacoes, transferegov_propostas.historico_comunicacoes),
                documentos_quadro_resumo=COALESCE(EXCLUDED.documentos_quadro_resumo, transferegov_propostas.documentos_quadro_resumo),
                historico_atualizado_em=COALESCE(EXCLUDED.historico_atualizado_em, transferegov_propostas.historico_atualizado_em),
                ops_obs=COALESCE(EXCLUDED.ops_obs, transferegov_propostas.ops_obs),
                obras=COALESCE(EXCLUDED.obras, transferegov_propostas.obras),
                -- So avanca quando o detalhe foi REALMENTE lido nesta rodada
                -- (_detalhe_lido). Rodada com TG_SKIP_ENRICH=1 chega aqui com
                -- NULL e o COALESCE preserva o carimbo antigo — senao o skip se
                -- auto-invalidaria a cada cron diario.
                detalhe_atualizado_em=COALESCE(EXCLUDED.detalhe_atualizado_em, transferegov_propostas.detalhe_atualizado_em),
                detalhe=COALESCE(EXCLUDED.detalhe, transferegov_propostas.detalhe),
                raw_data=EXCLUDED.raw_data, updated_at=NOW()
        """, (mun_id, p["numero_proposta"][:20], p["situacao"][:300], p["orgao"][:300],
              p["proponente"][:300], p["possui_parecer"][:10], p["identificacao"][:30],
              (codigo_instr or "")[:30] or None, (modalidade or "")[:100] or None,
              (situacao_siafi or "")[:200] or None, (num_processo or "")[:50] or None,
              objeto, (programa or "")[:300] or None,
              (dt_ini_vig or "")[:20] or None, (dt_fim_vig or "")[:20] or None,
              (dt_prop or "")[:20] or None, (dt_assin or "")[:20] or None,
              valor_global, valor_repasse, valor_contrap,
              (situacao_contr or "")[:100] or None, cl_dt, cl_motivo,
              (parlamentar or "")[:200] or None,
              json.dumps(sit_det_json, ensure_ascii=False) if sit_det_json else None,
              (p.get("id_proposta_siconv") or None),
              p.get("processo_execucao_qtd"),
              # ⚠️ `is not None` tambem aqui. Lista VAZIA e resposta medida ("o
              # portal respondeu: nenhuma licitacao"), nao ausencia. Sintoma
              # concreto em Araujos: 054685/2025 com processo_execucao_qtd = 0 e
              # processo_execucao = NULL. O `_qtd` ao lado salvava a informacao,
              # entao nao se perdia — mas duas colunas discordando sobre o mesmo
              # fato e exatamente o tipo de contradicao que a auditoria caca.
              # Seguro: `prop["processo_execucao"]` so e atribuido dentro de
              # `if _lst is not None` (linha ~999), nunca pre-semeado.
              (json.dumps(p["processo_execucao"], ensure_ascii=False)
               if p.get("processo_execucao") is not None else None),
              # ⚠️ `is not None`, e nao truthy — a mesma correcao que
              # `notas_empenho` recebeu logo abaixo, e que faltava aqui.
              # `projeto_basico` e o UNICO dos quatro campos com esta guarda que
              # nao tem uma coluna vizinha para salvar o "consultei e nao ha":
              # `processo_execucao` tem o `_qtd` ao lado, `historico_comunicacoes`
              # e `documentos_quadro_resumo` tem o `historico_atualizado_em`.
              # Aqui, dict vazio virava NULL, o COALESCE preservava o anterior, e
              # "esta proposta nao tem projeto basico" ficava indistinguivel de
              # "nunca olhei o projeto basico dela".
              (json.dumps(p["projeto_basico"], ensure_ascii=False)
               if p.get("projeto_basico") is not None else None),
              # ⚠️ `is not None`, NÃO truthy. `[]` é RESPOSTA MEDIDA ("consultei
              # a listagem de empenhos e não há NE"), não ausência. Com a guarda
              # antiga a lista vazia era falsy, virava NULL e o COALESCE do
              # ON CONFLICT preservava o valor anterior — a coluna só podia ser
              # NULA ou lista não-vazia, e "sem empenho" era indistinguível de
              # "nunca consultado". Seguro porque `notas_empenho` nunca é
              # pré-semeada em `prop`: só nasce quando o leitor devolve != None.
              (json.dumps(p["notas_empenho"], ensure_ascii=False)
               if p.get("notas_empenho") is not None else None),
              (json.dumps(p["historico_comunicacoes"], ensure_ascii=False)
               if p.get("historico_comunicacoes") else None),
              (json.dumps(p["documentos_quadro_resumo"], ensure_ascii=False)
               if p.get("documentos_quadro_resumo") else None),
              (_dt_now() if (p.get("historico_comunicacoes") or p.get("documentos_quadro_resumo")
                             or p.get("_historico_checado")) else None),
              (json.dumps(p["ops_obs"], ensure_ascii=False) if p.get("ops_obs") else None),
              (json.dumps(p["obras"], ensure_ascii=False) if p.get("obras") else None),
              (_dt_now() if p.get("_detalhe_lido") else None),
              (json.dumps(det, ensure_ascii=False) if det else None), json.dumps(p, ensure_ascii=False)))
        ins += 1

    # CLAUSULA RESOLVIDA -> APAGA o JSONB. E a contrapartida do COALESCE logo
    # acima: ele existe para "nao perguntei" nao apagar dado bom, mas sem uma
    # saida o campo virava ETERNO — convenio que saiu da clausula suspensiva
    # continuava com a caixa ambar no RM para sempre, porque o relatorio le este
    # JSONB e nenhuma das fontes que se atualizam consegue toca-lo.
    #
    # So entra aqui quem foi CONFERIDO nesta rodada (ver
    # `_clausula_conferida_sem` no laco de coleta): o portal disse, com o campo
    # lido de verdade, que a Situacao de Contratacao nao e mais clausula/liminar.
    # UPDATE separado, e nao um CASE no UPSERT de 38 colunas, porque a operacao e
    # DESTRUTIVA e merece ficar legivel e isolada.
    _resolvidas = [p["numero_proposta"][:20] for p in propostas
                   if p.get("_clausula_conferida_sem")]
    if _resolvidas:
        cur.execute(
            "UPDATE transferegov_propostas SET situacao_contratacao_detalhe = NULL "
            "WHERE municipio_id = %s AND numero_proposta = ANY(%s) "
            "  AND situacao_contratacao_detalhe IS NOT NULL",
            (mun_id, _resolvidas),
        )
        if cur.rowcount:
            # Logado sempre: apagar dado em silencio e o tipo de coisa que ninguem
            # descobre ate precisar dele.
            logger.info(f"  clausula resolvida em {cur.rowcount} proposta(s) — "
                        "JSONB de detalhe da clausula limpo (portal diz nao-clausula)")
    conn.commit(); cur.close(); conn.close()
    return ins


async def run():
    from playwright.async_api import async_playwright
    municipios = _municipios_pacta()
    logger.info(f"=== TransfereGov Voluntarias: {len(municipios)} municipios ===")

    # CAMADA BASE por DADOS ABERTOS primeiro (HTTP, sem navegador). Preenche a
    # tabela inteira -- valores, situacao, datas, parlamentar, programa -- a
    # partir dos CSVs oficiais. So DEPOIS o navegador entra para a fatia que so
    # existe atras do login (historico de comunicacoes, quadro resumo, processo
    # de execucao). Assim, se o Chromium travar/falhar, a base ja esta completa e
    # atualizada -- em vez do cenario antigo, em que uma falha do navegador
    # deixava TUDO desatualizado. Isolado: um erro aqui nao impede o resto.
    # TG_OPENDATA=0 desliga (volta ao comportamento so-navegador).
    if (os.getenv("TG_OPENDATA", "1") or "1").strip() not in ("0", "false", "no"):
        try:
            from ingestion.transferegov_opendata import run as _open_run
            _open_run()
            # ⚠️ ORDEM IMPORTA. Estes backfills (baratos, HTTP, carteira inteira)
            # ficavam DEPOIS do loop de browser — e o timeout do cron mata dentro
            # do loop, entao no freitas e no trust eles NUNCA rodavam: clausula
            # suspensiva e parlamentar paravam de atualizar em silencio. Rodando
            # aqui, junto do open data de que dependem (id_proposta_siconv), eles
            # entregam a carteira inteira todo dia, independente de o browser
            # terminar. Ver tambem o PAC e o ingestion_log, movidos pelo mesmo motivo.
            try:
                from ingestion import siconv_emenda_backfill as _bf
                npb = _bf.backfill_parlamentar(use_cache=False)
                logger.info(f"  backfill parlamentar: {npb} linha(s) atualizadas")
            except Exception as e:
                logger.warning(f"  backfill parlamentar falhou: {str(e)[:160]}")
            try:
                from ingestion import siconv_convenio_backfill as _cb
                ncl = _cb.backfill(use_cache=False)
                logger.info(f"  backfill clausula/contratacao: {ncl} linha(s) atualizadas")
            except Exception as e:
                logger.warning(f"  backfill clausula falhou: {str(e)[:160]}")
            # LICITACOES pelo dado aberto — o mesmo campo que a tela LOGADA
            # preenchia, sem depender de sessao gov.br (que ficou 7 dias morta em
            # 09/2026 sem ninguem ver). Fica aqui, junto dos irmaos, pelo mesmo
            # motivo deles: roda mesmo quando o navegador nao termina.
            try:
                from ingestion import siconv_licitacao as _lic
                nlic = _lic.coletar(use_cache=False)
                logger.info(f"  licitacoes (dado aberto): {nlic} linha(s) atualizadas")
            except Exception as e:
                logger.warning(f"  licitacoes (dado aberto) falhou: {str(e)[:160]}")
        except Exception as e:
            logger.warning(f"  camada de dados abertos falhou (segue p/ navegador): {e}")

    total = 0
    _ok_diario = 0
    _falhas_diario: list = []
    _subs_diario: list = []
    _gated_zera()          # contador de MODULO: zera a cada rodada
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx_guest = None
        ctx_auth = None
        try:
            # Contexto GUEST (sem cookies): listagem via Acesso Livre
            ctx_guest = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
            page_guest = await ctx_guest.new_page()
            # A Cláusula Suspensiva vem do OPEN DATA (siconv_convenio_backfill), então
            # por um tempo este run() rodou GUEST-ONLY, com a sessão desligada. Só que
            # o Histórico de Comunicações (add. em 20/07) EXIGE a área /private/: sem
            # sessão ele nunca era capturado pelo cron — apenas por run_one() manual.
            # Com a extensão de captura + govbr_renew (re-deriva via SAML a cada 15min,
            # sem reCAPTCHA), a sessão se mantém sozinha e a coleta pode ser automática.
            # Degrada com segurança: sem sessão válida, cai em guest exatamente como antes.
            # TRANSFEREGOV_AUTH=0 volta ao comportamento guest-only.
            _auth_on = (os.getenv("TRANSFEREGOV_AUTH", "1") or "1").strip() not in ("0", "false", "no")
            govbr_cks = _load_govbr_cookies() if _auth_on else None
            page_auth = None
            if govbr_cks:
                # Carrega cookies originais (com expiration) para checar validade.
                # Auth do scraper usa principalmente JSESSIONID de discricionarias
                # (capturado quando user faz bookmarklet em /voluntarias/...).
                # user-id JWT do parcerias eh OPCIONAL (so usado pra extracoes
                # adicionais no parcerias). Pula auth APENAS se NAO tiver
                # JSESSIONID de discricionarias E o user-id estiver expirado.
                try:
                    import psycopg2 as _pg
                    _u = os.getenv("DATABASE_URL_SYNC","").replace("&channel_binding=require","").replace("?channel_binding=require","")
                    _c = _pg.connect(_u); _cur = _c.cursor()
                    _cur.execute("SELECT senha_hash FROM cofre_senhas WHERE automation_key IN ('govbr','siconv_legado') "
                                 "AND length(senha_hash) > 1000 ORDER BY updated_at DESC")
                    _all = _cur.fetchall(); _cur.close(); _c.close()
                    from services import crypto as _crypto
                    has_discric_session = False
                    best_jwt_mins = float("-inf")
                    for _row in _all:
                        _data = json.loads(_crypto.decrypt(_row[0]))
                        cks = _data.get("cookies", [])
                        if any('discricionarias' in (c.get('domain','') or '') and c.get('name')=='JSESSIONID' for c in cks):
                            has_discric_session = True
                        jm = _jwt_minutos_restantes(cks)
                        if jm > best_jwt_mins: best_jwt_mins = jm
                    logger.info(f"  auth status: JSESSIONID-discric={has_discric_session} | user-id JWT={best_jwt_mins:+.1f}min")
                    if not has_discric_session and best_jwt_mins <= 1:
                        logger.warning("  sem JSESSIONID e JWT expirado — pulando auth, indo direto guest")
                        govbr_cks = None
                except Exception as e:
                    logger.warning(f"  nao validou sessao: {e}")
            if govbr_cks:
                try:
                    ctx_auth = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
                    await ctx_auth.add_cookies(govbr_cks)
                    page_auth = await ctx_auth.new_page()
                    logger.info(f"  contexto AUTH criado com {len(govbr_cks)} cookies SSO")
                except Exception as e:
                    logger.warning(f"  falha ao criar contexto AUTH: {e}")
                    page_auth = None
            else:
                logger.info("  sem sessao gov.br valida, detalhes em guest")
            for mun in municipios:
                try:
                    # Listagem SEMPRE guest (Acesso Livre). Com sessao viva, o
                    # detalhe da Clausula Suspensiva (motivo+data) e capturado via
                    # page_auth navegando o instrumento. Sem sessao: so o status.
                    props = await _scrape_municipio(page_guest, mun, page_auth=page_auth)
                    n = _upsert(mun["id"], props)
                    logger.info(f"  {mun['nome']}: {len(props)} propostas -> {n} upsert")
                    total += n
                    _ok_diario += 1
                    if mun["id"] in _PAGINACAO_INCOMPLETA:
                        _cd, _ed = _PAGINACAO_INCOMPLETA[mun["id"]]
                        _subs_diario.append(f"{mun['nome']} ({_cd}/{_ed})")
                except Exception as e:
                    logger.error(f"  {mun['nome']}: ERRO {str(e)[:200]}")
                    _falhas_diario.append(mun["nome"])
        finally:
            # Fecha SEMPRE, inclusive em excecao/cancelamento: e este caminho que,
            # sem o finally, deixava Chromium orfao vivo consumindo CPU para sempre.
            for _ctx in (ctx_auth, ctx_guest):
                if _ctx is not None:
                    try:
                        await _ctx.close()
                    except Exception:
                        pass
            try:
                await browser.close()
            except Exception:
                pass
    logger.info(f"=== Finalizado: {total} propostas ===")
    # (backfills de parlamentar e clausula/contratacao rodam ANTES do loop de
    #  browser — ver o bloco logo apos o open data. Ficavam aqui e nunca eram
    #  alcancados quando o timeout matava dentro do loop.)
    # Log de ingestao — mesma regra honesta do lote e do sigcon: uma rodada
    # diaria em que TODO municipio falhou (ou veio subcoletado) nao pode pintar
    # 'success' no monitor de frescor, que le exatamente esta fonte.
    try:
        import psycopg2
        _gated_d = _gated_frase()
        if _ok_diario == 0 and _falhas_diario:
            _st_d = "erro"
        elif _falhas_diario or _subs_diario or _gated_d:
            # ⚠️ NUNCA rebaixa 'erro' para 'parcial': o eixo gated so ACRESCENTA
            # motivo, e o ramo do erro vem antes de proposito.
            _st_d = "parcial"
        else:
            _st_d = "success"
        _partes_d = []
        if _gated_d:
            _partes_d.append(_gated_d)
        if _falhas_diario:
            _partes_d.append(f"{len(_falhas_diario)} municipio(s) com erro: {', '.join(_falhas_diario[:5])}")
        if _subs_diario:
            _partes_d.append(f"paginacao incompleta: {', '.join(_subs_diario[:5])}")
        url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute("INSERT INTO ingestion_log (source, status, records_processed, records_inserted, error_message, finished_at) "
                    "VALUES ('transferegov_voluntarias',%s,%s,%s,%s,NOW())",
                    (_st_d, _ok_diario + len(_falhas_diario), total, "; ".join(_partes_d) or None))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass
    # Selecao PAC / Novo PAC — roda logo apos as voluntarias (usa o CNPJ da
    # prefeitura que as voluntarias acabaram de gravar em transferegov_propostas).
    # Best-effort (browser proprio); nao derruba o cron das voluntarias.
    try:
        from ingestion.transferegov_pac import run as _pac_run
        await _pac_run()
    except Exception as e:
        logger.warning(f"  PAC (apos voluntarias) falhou: {str(e)[:160]}")


FONTE_COLETA = "transferegov"


def _proximos_municipios(n: int) -> list[dict]:
    """Os N municipios mais desatualizados (rodizio), como o sigcon ja faz.

    Ordena por `ultima_coleta_em NULLS FIRST` em scraper_municipio_coleta — quem
    esta parado ha mais tempo (ou nunca coletado) vem primeiro. Se a tabela nao
    existir, degrada para a ordem alfabetica de sempre."""
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
    try:
        conn = psycopg2.connect(url); cur = conn.cursor()
        cur.execute(
            "SELECT m.id, m.nome, m.uf FROM municipios m "
            "LEFT JOIN scraper_municipio_coleta sc "
            "       ON sc.municipio_id = m.id AND sc.fonte = %s "
            "WHERE m.active = true "
            "ORDER BY sc.ultima_coleta_em ASC NULLS FIRST, m.nome "
            "LIMIT %s", (FONTE_COLETA, n))
        out = [{"id": r[0], "nome": r[1], "uf": r[2]} for r in cur.fetchall()]
        cur.close(); conn.close()
        return out
    except Exception as e:
        logger.warning(f"  rodizio indisponivel ({str(e)[:70]}) — ordem alfabetica")
        return _municipios_pacta()[:n]


def _marca_coleta(municipio_id: int, ok: bool, erro: str | None = None) -> None:
    """Carimba a passagem pelo municipio. SEMPRE — inclusive em erro/corte.

    Diferenca DELIBERADA do sigcon (que so carimba no sucesso): com NULLS FIRST,
    carimbar so no sucesso faz um municipio problematico (ou grande demais p/ a
    janela) ocupar o primeiro lugar da fila em TODA rodada, para sempre, e os
    demais nunca serem alcancados. Carimbando sempre, a fila e um round-robin
    honesto; o erro fica registrado em ultimo_erro para diagnostico."""
    import psycopg2
    try:
        conn = psycopg2.connect(os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", ""))
        cur = conn.cursor()
        # tentativas do INSERT tambem respeita `ok` (0 no sucesso, 1 no erro):
        # gravar 1 fixo marcava a 1a coleta BOA de um municipio novo como
        # 'falha consecutiva' ate a 2a rodada. E o ultimo_erro_em do INSERT
        # agora e expressao SQL — antes ia a STRING "NOW()" como parametro de
        # timestamptz, que o Postgres rejeita (o except engolia e o municipio
        # novo com erro ficava sem linha nenhuma no rodizio).
        cur.execute(
            "INSERT INTO scraper_municipio_coleta (fonte, municipio_id, ultima_coleta_em, ultimo_erro_em, ultimo_erro, tentativas) "
            "VALUES (%s,%s,NOW(), CASE WHEN %s THEN NULL ELSE NOW() END, %s, CASE WHEN %s THEN 0 ELSE 1 END) "
            "ON CONFLICT (fonte, municipio_id) DO UPDATE SET "
            "  ultima_coleta_em = NOW(), "
            "  ultimo_erro_em = CASE WHEN %s THEN scraper_municipio_coleta.ultimo_erro_em ELSE NOW() END, "
            "  ultimo_erro    = CASE WHEN %s THEN scraper_municipio_coleta.ultimo_erro ELSE %s END, "
            "  tentativas     = CASE WHEN %s THEN 0 ELSE scraper_municipio_coleta.tentativas + 1 END",
            (FONTE_COLETA, municipio_id, ok, (erro or "")[:400] if not ok else None, ok,
             ok, ok, (erro or "")[:400], ok))
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass  # contabilidade do rodizio nunca derruba a coleta


async def run_proximos(n: int | None = None, deadline_s: int | None = None):
    """LOTE PEQUENO E FREQUENTE — o padrao que funciona na mao, virado cron.

    Por que existe: `run()` processa TODOS os municipios numa execucao so e nao
    cabe na janela do cron (freitas 41 mun / trust 19 mun grandes) — morria no
    timeout, sempre. Rodando na mao sempre funcionou porque eu chamava
    `run_one(id)` municipio a municipio, com TG_OPENDATA=0, varias vezes. Esta
    funcao e exatamente isso, automatizado: pega os N mais desatualizados
    (rodizio), respeita um DEADLINE de relogio e sai limpo. Como o cron roda de
    hora em hora, a carteira inteira e coberta todo dia, em pedacos que sempre
    cabem — em vez de uma rodada grande que nunca termina.

    NAO faz open data nem backfills: quem faz e o cron `transferegov` (base),
    1x/dia. Repetir aqui seria baixar 200MB de novo por nada (era o que o cron
    de enrich fazia)."""
    from playwright.async_api import async_playwright
    try:
        n = n if n is not None else max(1, int(os.getenv("TG_LOTE_MUNICIPIOS", "3") or "3"))
    except ValueError:
        n = 3
    try:
        deadline_s = deadline_s if deadline_s is not None else max(60, int(os.getenv("TG_BUDGET_S", "1500") or "1500"))
    except ValueError:
        deadline_s = 1500
    muns = _proximos_municipios(n)
    if not muns:
        logger.info("=== nenhum municipio a coletar ==="); return
    logger.info(f"=== TransfereGov LOTE: {len(muns)} municipio(s) | budget {deadline_s}s | "
                f"{', '.join(m['nome'] for m in muns)} ===")
    _t0 = time.monotonic()
    total = 0
    ok_n = 0
    falhas_mun: list = []
    subcoletas: list = []
    _gated_zera()          # contador de MODULO: zera a cada rodada
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
                                          args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        try:
            ctx_guest = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
            page_guest = await ctx_guest.new_page()
            page_auth = None
            govbr_cks = _load_govbr_cookies() if (os.getenv("TRANSFEREGOV_AUTH", "1") or "1").strip() not in ("0", "false", "no") else None
            if govbr_cks:
                try:
                    ctx_auth = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
                    await ctx_auth.add_cookies(govbr_cks)
                    page_auth = await ctx_auth.new_page()
                    logger.info(f"  contexto AUTH criado com {len(govbr_cks)} cookies SSO")
                except Exception as e:
                    logger.warning(f"  falha ao criar contexto AUTH: {str(e)[:80]}")
            for mun in muns:
                gasto = time.monotonic() - _t0
                if gasto > deadline_s:
                    logger.info(f"  orcamento esgotado ({gasto:.0f}s) — {mun['nome']} fica p/ a proxima rodada")
                    break
                try:
                    # Deadline ABSOLUTO da execucao: o municipio para no meio do
                    # loop de detalhe em vez de ser morto pelo `timeout` externo.
                    props = await _scrape_municipio(page_guest, mun, page_auth=page_auth,
                                                    deadline=_t0 + deadline_s)
                    n_up = _upsert(mun["id"], props)
                    total += n_up
                    _parc = _SCRAPE_STATE.get("parcial")
                    logger.info(f"  {mun['nome']}: {len(props)} propostas -> {n_up} upsert "
                                f"({time.monotonic()-_t0:.0f}s acumulados)"
                                f"{' [PARCIAL]' if _parc else ''}")
                    _pag = _PAGINACAO_INCOMPLETA.get(mun["id"])
                    if _parc:
                        # Parcial NAO e sucesso: registra p/ diagnostico e deixa o
                        # backoff agir. O carimbo de ultima_coleta_em acontece de
                        # todo jeito (ver _marca_coleta), entao a fila anda e os
                        # outros municipios nao passam fome. Na proxima passagem o
                        # skip incremental pula o que ja foi lido e retoma o resto.
                        # Por isso tb NAO conta em ok_n: a passagem nao fechou.
                        _marca_coleta(mun["id"], ok=False,
                                      erro=f"parcial: orcamento esgotado, "
                                           f"{_SCRAPE_STATE.get('restantes', 0)} propostas restantes")
                    elif _pag:
                        # Listagem curta tambem NAO e sucesso. Ate 13/09/2026 este
                        # caso carimbava ok=True: Palmas "fechou" com 100 de 2.121
                        # propostas e sumiu do radar — o relatorio a mostrava verde.
                        _marca_coleta(mun["id"], ok=False,
                                      erro=f"paginacao incompleta: {_pag[0]} de {_pag[1]} propostas listadas")
                    else:
                        _marca_coleta(mun["id"], ok=True)
                        ok_n += 1
                    # Subcoleta de paginacao e ortogonal ao corte de detalhe:
                    # vale registrar nos dois casos.
                    if mun["id"] in _PAGINACAO_INCOMPLETA:
                        _col, _esp = _PAGINACAO_INCOMPLETA[mun["id"]]
                        subcoletas.append(f"{mun['nome']} ({_col}/{_esp})")
                except Exception as e:
                    logger.error(f"  {mun['nome']}: ERRO {str(e)[:200]}")
                    _marca_coleta(mun["id"], ok=False, erro=str(e))
                    falhas_mun.append(mun["nome"])
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    logger.info(f"=== LOTE concluido: {total} propostas em {time.monotonic()-_t0:.0f}s ===")

    # Log de ingestao do LOTE, com fonte PROPRIA ('transferegov_lote'): o lote
    # horario nao gravava ingestion_log nenhum e podia falhar por dias sem o
    # watchdog ver (ele so vigiava o 'transferegov_voluntarias' do run diario).
    # Vocabulario do freshness/watchdog: 'parcial' = rodou mas degradado
    # (municipio com erro ou paginacao incompleta); 'erro' = nenhum municipio
    # saiu. Watchdog tolera 6h sem success — um 'parcial' isolado nao alarma,
    # seis seguidos sim.
    try:
        import psycopg2
        _u = os.getenv("DATABASE_URL_SYNC", "").replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        _gated_l = _gated_frase()
        if ok_n == 0 and falhas_mun:
            _st = "erro"
        elif falhas_mun or subcoletas or _gated_l:
            _st = "parcial"
        else:
            _st = "success"
        _partes = []
        if _gated_l:
            _partes.append(_gated_l)
        if falhas_mun:
            _partes.append(f"{len(falhas_mun)} municipio(s) com erro: {', '.join(falhas_mun[:5])}")
        if subcoletas:
            _partes.append(f"paginacao incompleta: {', '.join(subcoletas[:5])}")
        _cn = psycopg2.connect(_u); _cu = _cn.cursor()
        _cu.execute(
            "INSERT INTO ingestion_log (source, status, records_processed, "
            "records_inserted, error_message, finished_at) "
            "VALUES ('transferegov_lote', %s, %s, %s, %s, NOW())",
            (_st, ok_n + len(falhas_mun), total, "; ".join(_partes) or None),
        )
        _cn.commit(); _cu.close(); _cn.close()
    except Exception as e:
        logger.warning(f"  ingestion_log do lote falhou: {str(e)[:120]}")


async def run_one(municipio_id: int):
    """Versao test: roda so para um municipio (debug)."""
    from playwright.async_api import async_playwright
    muns = [m for m in _municipios_pacta() if m["id"] == municipio_id]
    if not muns:
        logger.error(f"municipio_id={municipio_id} nao encontrado")
        return
    mun = muns[0]
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--ignore-certificate-errors", "--no-sandbox", "--disable-dev-shm-usage"])
        ctx_guest = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
        page_guest = await ctx_guest.new_page()
        govbr_cks = _load_govbr_cookies()
        page_auth = None
        # Auth eh por JSESSIONID de discricionarias (capturado via bookmarklet
        # em /voluntarias/...) OU user-id JWT do parcerias. Pula auth APENAS
        # se nenhum estiver valido.
        if govbr_cks:
            try:
                import psycopg2 as _pg
                _u = os.getenv("DATABASE_URL_SYNC","").replace("&channel_binding=require","").replace("?channel_binding=require","")
                _c = _pg.connect(_u); _cur = _c.cursor()
                _cur.execute("SELECT senha_hash FROM cofre_senhas WHERE automation_key IN ('govbr','siconv_legado') "
                             "AND length(senha_hash) > 1000 ORDER BY updated_at DESC")
                _all = _cur.fetchall(); _cur.close(); _c.close()
                from services import crypto as _crypto
                has_discric_session = False
                best_jwt_mins = float("-inf")
                for _row in _all:
                    _data = json.loads(_crypto.decrypt(_row[0]))
                    cks = _data.get("cookies", [])
                    if any('discricionarias' in (c.get('domain','') or '') and c.get('name')=='JSESSIONID' for c in cks):
                        has_discric_session = True
                    jm = _jwt_minutos_restantes(cks)
                    if jm > best_jwt_mins: best_jwt_mins = jm
                logger.info(f"  auth: JSESSIONID-discric={has_discric_session} | user-id JWT={best_jwt_mins:+.1f}min")
                if not has_discric_session and best_jwt_mins <= 1:
                    logger.warning("  sem JSESSIONID e JWT expirado — pulando auth")
                    govbr_cks = None
            except Exception as e:
                logger.warning(f"  nao validou sessao: {e}")
        if govbr_cks:
            ctx_auth = await browser.new_context(ignore_https_errors=True, user_agent="Mozilla/5.0 Chrome/131")
            await ctx_auth.add_cookies(govbr_cks)
            page_auth = await ctx_auth.new_page()
            logger.info(f"  contexto AUTH criado com {len(govbr_cks)} cookies SSO")
        try:
            props = await _scrape_municipio(page_guest, mun, page_auth=page_auth)
            n = _upsert(mun["id"], props)
            logger.info(f"{mun['nome']}: {len(props)} propostas -> {n} upsert")
            com_parl = sum(1 for p in props if (p.get("detalhe") or {}).get("_parlamentar"))
            com_sit_det = sum(1 for p in props if (p.get("detalhe") or {}).get("_situacao_detalhe"))
            logger.info(f"  ENRICH: parlamentar={com_parl} sit_det={com_sit_det}")
        finally:
            await browser.close()


if __name__ == "__main__":
    import sys
    _arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if _arg.isdigit():
        asyncio.run(run_one(int(_arg)))          # um municipio (debug/manual)
    elif _arg.startswith("lote"):
        # `lote` ou `lote:N` — rodizio, N municipios, com deadline (TG_BUDGET_S).
        _n = None
        if ":" in _arg:
            try:
                _n = int(_arg.split(":", 1)[1])
            except ValueError:
                _n = None
        asyncio.run(run_proximos(_n))
    else:
        asyncio.run(run())                        # rodada completa (cron base)
