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
    (e `vencendo` False) sem hora de login. `vencendo` = dentro da janela de aviso
    (>= AVISO_VENCIMENTO_H desde o login) e ainda antes do teto + 3h: depois disso
    a sessao ja caiu, e quem avisa e o alarme de sessao caida, nao este."""
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
        "vencendo": AVISO_VENCIMENTO_H <= ha_h < VIDA_SSO_H + 3.0,
    }


def _brt(dt: datetime) -> str:
    return dt.astimezone(timezone(timedelta(hours=-3))).strftime("%H:%M de %d/%m")


def texto_do_aviso(login_em: datetime, agora: datetime | None = None) -> str:
    """O aviso do vigia: diz a HORA, a ACAO e o porque de ser 'previsto'."""
    v = vencimento(login_em, agora)
    vence = datetime.fromisoformat(v["vence_previsto_em"])
    return (f"Login gov.br feito as {_brt(login_em)} (Brasilia), ha {v['login_ha_h']:.0f}h. "
            f"Pelo padrao medido (~{VIDA_SSO_H:.0f}h de vida) vence por volta das {_brt(vence)}.\n"
            "Antes disso: no Chrome, extensao do PACTHA > \"Captura completa (abre as 4 portas)\". "
            "Se o TransfereGov abrir SEM pedir login, clique em Sair e faca o login de novo — "
            "so um login novo renova o prazo; o servidor promove a captura nova sozinho.")
