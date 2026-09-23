"""
Sessao gov.br — o que se sabe sobre a VIDA dela, em funcoes puras.

⭐ POR QUE EXISTE (23/09/2026). A sessao caiu de novo nos seis tenants um dia depois
das guardas do PR #529 entrarem, e o `audit_log` mostrou que ninguem gravou por cima:
ela morreu SOZINHA, ~24h depois do login (21/09 09:42 -> 22/09 ~09:30 BRT). Ou seja,
a vida da sessao e a do proprio SSO do gov.br, e "nao cair mais" passa a ser: alguem
loga de novo ANTES de vencer, e o login novo se propaga sozinho (candidata ->
promovida). Este modulo da a hora do login e a hora prevista do vencimento para o
vigia (Telegram), a rota `/api/session-capture/saude` (selo da extensao) e o resumo.

⚠️ O TETO DE 24h E PADRAO MEDIDO, NAO CONTRATO. O gov.br nao publica a duracao da
sessao; duas mortes seguidas bateram em ~24h (12->13/09 ficou em ~35h, quando a
extensao ainda capturava a cada navegacao e pode ter estendido). Por isso o texto
diz "pelo padrao medido" e o aviso sai com folga (3h antes). A sonda hourly
`govbr_sso_roundtrip` (ver `govbr_renew.sso_roundtrip`) e o que vai calibrar isto.

Compartilhado pelo router (async) e pelo vigia (sync, sem Playwright/crypto): so
stdlib aqui.
"""
import re
from datetime import datetime, timedelta, timezone

# Vida observada do SSO gov.br a partir do login (horas) e com quanta antecedencia
# avisar. 21h = 3h de folga: tempo de uma pessoa ver o Telegram e logar.
VIDA_SSO_H = 24.0
AVISO_VENCIMENTO_H = 21.0

# "Viva" = a ultima medicao de `govbr_sso` e success e tem menos de SESSAO_VIVA_MIN.
# 180 = tres renews horarios perdidos: o worker parado ha 3h nao prova vida, e a
# guarda do endpoint de captura (sessao viva -> candidata) tem de se abrir sozinha
# quando ninguem mede. Mesma regua para o vigia e para a rota de saude.
SESSAO_VIVA_MIN = 180


def sessao_esta_viva(status, idade_min) -> bool:
    if (status or "").lower() != "success" or idade_min is None:
        return False
    return 0 <= float(idade_min) <= SESSAO_VIVA_MIN

_RE_CAPTURADO = re.compile(r"\[SESSION\] capturado em (\S+)")


def login_em_da_observacao(observacao) -> datetime | None:
    """Hora do login = hora da captura gravada na `observacao` da linha `govbr`
    do Cofre ("[SESSION] capturado em <iso> | ..."). A captura acontece segundos
    depois do login (fim do roteiro da extensao), e e a unica marca do login que o
    servidor tem — `updated_at` e a versao do JAR (o keepalive a renova a cada 10
    min), nao a hora do login. Devolve None se nao houver marca."""
    m = _RE_CAPTURADO.search(str(observacao or ""))
    if not m:
        return None
    bruto = m.group(1).rstrip("|,;")
    try:
        dt = datetime.fromisoformat(bruto.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def vencimento(login_em: datetime | None, agora: datetime | None = None) -> dict:
    """{login_em, login_ha_h, vence_previsto_em, vence_em_h, vencendo} — tudo None
    (e `vencendo` False) sem hora de login. `vencendo` = ja passou da janela de
    aviso (>= AVISO_VENCIMENTO_H desde o login), SEM teto superior: 24h e padrao
    medido, e uma sessao que dure mais nao pode apagar o aviso e voltar a "tudo
    certo" com o vencimento ja passado. Quem contem o spam e o cooldown do vigia;
    quem apaga o aviso e o login NOVO (a hora muda) ou a morte (`viva` cai)."""
    if login_em is None:
        return {"login_em": None, "login_ha_h": None, "vence_previsto_em": None,
                "vence_em_h": None, "vencendo": False}
    agora = agora or datetime.now(timezone.utc)
    ha_h = (agora - login_em).total_seconds() / 3600.0
    vence = login_em + timedelta(hours=VIDA_SSO_H)
    return {
        "login_em": login_em.isoformat(),
        "login_ha_h": round(ha_h, 1),
        "vence_previsto_em": vence.isoformat(),
        "vence_em_h": round(VIDA_SSO_H - ha_h, 1),
        "vencendo": ha_h >= AVISO_VENCIMENTO_H,
    }


# ---------------------------------------------------------------------------
# IDENTIDADE DA SESSAO SSO — "esta captura e um LOGIN NOVO ou a mesma sessao?"
# ---------------------------------------------------------------------------
# ⚠️ MEDIDO EM PRODUCAO (23/09/2026, `cookies_meta` do jar real, sem valores): o
# login de 23/09 11:27 NAO trouxe `Session_Gov_Br_Prod` nem `INGRESSCOOKIE`. Do
# gov.br vieram so `Govbrid` e `GovbrUid_*` — PERSISTENTES, validos ate 2027, e o
# `Govbrid` vence em 15/06/2027: nao foi reemitido no login, e identificador do
# APARELHO. Comparar esses dava "mesma sessao" para sempre (a hora do login nunca
# mudava, o aviso nunca apagava). O que e da SESSAO sao os cookies httpOnly SEM
# validade: o `JSESSIONID` do IdP (`idp.transferegov...`) e, se vier, o
# `Session_Gov_Br_Prod` do gov.br. Afinidade de balanceador nao e identidade.
COOKIE_SESSAO_SSO = "Session_Gov_Br_Prod"
_NAO_IDENTIDADE = {"INGRESSCOOKIE"}


def _dominio_sso(dom: str) -> bool:
    return dom == "gov.br" or dom.endswith("acesso.gov.br")


def _persistente(expira) -> bool:
    try:
        return bool(expira) and float(expira) > 0
    except (TypeError, ValueError):
        return False


def _cookies_sso(cookies) -> dict:
    """{(dominio, nome): valor} dos cookies que identificam a SESSAO de login:
    httpOnly, SEM data de validade (cookie de sessao do navegador), no gov.br ou o
    JSESSIONID do IdP. Aceita os dois formatos que circulam: dict (Cofre, extensao)
    e objeto com atributos (pydantic)."""
    out = {}
    for c in cookies or []:
        g = c.get if isinstance(c, dict) else (lambda k, _c=c: getattr(_c, k, None))
        dom = (g("domain") or "").lstrip(".").lower()
        nome = g("name")
        if not g("httpOnly") or nome in _NAO_IDENTIDADE:
            continue
        if _persistente(g("expirationDate") or g("expires")):
            continue                      # Govbrid/GovbrUid: aparelho, nao sessao
        if _dominio_sso(dom) or (dom.startswith("idp.") and nome == "JSESSIONID"):
            out[(dom, nome)] = g("value")
    return out


def comparar_sessao_sso(candidata, em_uso) -> tuple[bool, list]:
    """(mesma_sessao, nomes que diferem — SEM valor, para calibrar pelo log).

    ⭐ POR QUE (revisao de 23/09): a promocao copiava a hora da captura como hora
    do LOGIN em toda candidata; com o Chrome aberto a extensao recaptura a cada
    navegacao/alarme, e o relogio do vencimento andava para a frente a cada ciclo
    — o aviso nunca sairia. So login NOVO troca os cookies de sessao (IdP/gov.br).

    Regra: compara os cookies de identidade que os DOIS lados tem; algum diferente =
    login novo, todos iguais = mesma sessao. Nada em comum: nao ha como saber, e
    vale 'login novo' — o comportamento antigo, nunca pior."""
    a, b = _cookies_sso(candidata), _cookies_sso(em_uso)
    comuns = set(a) & set(b)
    if not comuns:
        return False, sorted({n for (_d, n) in a})
    difere = sorted({n for (d, n) in comuns if a[(d, n)] != b[(d, n)]})
    return (not difere), difere


def mesma_sessao_sso(candidata, em_uso) -> bool:
    return comparar_sessao_sso(candidata, em_uso)[0]


def observacao_preservando_login(obs_nova: str, obs_atual) -> str:
    """Recaptura da MESMA sessao: a observacao nova, mas com a hora do LOGIN antiga
    no lugar da hora desta captura (o vigia le a hora do login dali)."""
    antigo = login_em_da_observacao(obs_atual)
    if antigo is None:
        return obs_nova
    novo = login_em_da_observacao(obs_nova)
    agora = novo.isoformat() if novo else "?"
    return _RE_CAPTURADO.sub(f"[SESSION] capturado em {antigo.isoformat()}", obs_nova, count=1) \
        + f" | recapturado em {agora} (mesma sessao gov.br)"


def _brt(dt: datetime) -> str:
    return dt.astimezone(timezone(timedelta(hours=-3))).strftime("%H:%M de %d/%m")


def texto_do_aviso(login_em: datetime, agora: datetime | None = None) -> str:
    """O aviso do vigia: diz a HORA, a ACAO e o porque de ser 'previsto'."""
    v = vencimento(login_em, agora)
    vence = datetime.fromisoformat(v["vence_previsto_em"])
    quando = (f"vence por volta das {_brt(vence)}" if v["vence_em_h"] >= 0
              else f"ja passou do previsto ({_brt(vence)}) e ainda esta vivo")
    return (f"Login gov.br feito as {_brt(login_em)} (Brasilia), ha {v['login_ha_h']:.0f}h. "
            f"Pelo padrao medido (~{VIDA_SSO_H:.0f}h de vida) {quando}.\n"
            "Como renovar (nesta ordem): 1) no TransfereGov, clique em Sair — so um login NOVO "
            "renova o prazo; 2) na extensao do PACTHA, \"Captura completa (abre as 4 portas)\": "
            "ela para na tela de login, espera voce logar e passa pelas 4 portas sozinha. "
            "Se o gov.br entrar SEM pedir senha, a sessao dele continuou: saia tambem em "
            "sso.acesso.gov.br e repita. "
            "O Sair derruba a sessao dos servidores na hora; ela volta quando o keepalive "
            "promover a captura nova (ate ~10 min).")
