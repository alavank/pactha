"""
Autenticacao JWT (pyjwt) + bcrypt.
Suporta access + refresh tokens com JTI para revogacao.

Cookies httpOnly:
- access_token (TTL curto, ex: 60min)
- refresh_token (TTL maior, ex: 30 dias)
"""
import logging
import os
import uuid
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt as pyjwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from models.user import User
from database import get_db
from config import get_settings
# Roteador das negativas de tela/municipio. Import no topo e seguro: authz nao
# importa este modulo em tempo de import (so dentro de `ensure_dono`).
from services import authz

settings = get_settings()
security = HTTPBearer(auto_error=False)

_logger_auth = logging.getLogger("auth")

REFRESH_TTL_DAYS = int(os.getenv("REFRESH_TTL_DAYS", "30"))
COOKIE_NAME_ACCESS = "pactha_access"
COOKIE_NAME_REFRESH = "pactha_refresh"
COOKIE_NAME_CSRF = "pactha_csrf"

# ⚠️⚠️ A TRAVA «SOMENTE LEITURA» DA CONTA FOI REMOVIDA em 05/09/2026, por decisao
# do dono, e vale registrar a frase dele porque ela e o desenho novo:
#
#     "essa opçao somente leitura tb pode tirar isso, pq era para o prefeito,
#      nao precisa, prefiro dar permissao de visualizaçao separada pra cada menu
#      ou modulo dai eu permito so visualizar sem editar nada"
#
# O que ela fazia — barrar TODO metodo mutavel da conta inteira, fora de uma
# allowlist de prefixos do Painel — agora se faz DESMARCANDO as caixinhas de
# escrita de cada tela, que e mais fino: dava para ter "so leitura" no Cofre e
# escrita na Gestao Interna, o que a trava de conta nunca permitiu.
#
# ⚠️ E SO FICOU VERDADE NO MESMO DEPLOY, quando `AUTHZ_MODO` deixou de ser
# `aviso`: enquanto o modo era de aviso, quem impedia a escrita era exatamente
# esta trava, e as caixinhas so registravam na trilha. Tirar uma sem ligar a
# outra teria aberto a escrita para todo mundo. Ver `services/authz.py::modo`.
#
# ⚠️ A COLUNA `users.somente_leitura` CONTINUA NO BANCO, sem leitor. Mesma
# receita do Telegram e dos modelos de permissao: dropar coluna em cinco bancos
# de producao para ganhar nada e risco sem premio.

# ⭐ O QUIOSQUE E OUTRA HISTORIA, e por isso este bloco SOBREVIVEU a remocao
# acima. `viewer` nao e rotulo de pessoa: e a credencial SINTETICA do link
# publico de TV, criada em tempo de execucao por `routers/bi.py::_ensure_kiosk_user`
# com INSERT direto em `users`. Ela circula em WhatsApp e vale 365 dias.
#
# O guard principal do quiosque e o `ehQuiosque` + `KIOSK_GET_PERMITIDOS` mais
# abaixo, que le a coluna `kiosk` e recusa qualquer coisa que nao seja um GET de
# uma lista exata. Este conjunto e o SEGUNDO cinto, para a conta antiga cuja
# coluna `kiosk` ficou false: sem ele, um `viewer` legado passaria a escrever no
# dia em que a trava de conta saiu.
PAPEIS_SINTETICOS_SEM_ESCRITA = {"viewer"}

# SEMENTE das contas DONAS do sistema (Alavank), nao "mais um admin do cliente".
# Mandam em Sessoes, Tokens de Servico, e sao as unicas que podem alterar umas as
# outras.
#
# Fica AQUI, num lugar so, porque a lista ja existia copiada em routers/users.py
# e routers/service_tokens.py — duas copias de uma regra de permissao divergem
# em silencio, e o que se perde e o acesso do dono.
#
# E lista, e nao um e-mail unico, para nao haver ponto unico de falha: perdida a
# conta, ninguem consegue reseta-la nem alcancar aquelas telas.
# Duas contas NOMINAIS + a de BOOTSTRAP.
#
# `admin@pactha.com.br` saiu em 02/08/2026. O nome dizia "mais um admin" quando
# era a chave da plataforma, e por estar aqui qualquer admin do cliente que
# recriasse aquele e-mail na tela de Usuarios ganhava super poder — o e-mail era
# adivinhavel justamente por ser generico.
#
# `super-admin@alavank.com.br` e semeado por `setup_db.py` em TODO tenant novo e
# existe para um cliente recem-criado nao nascer sem acesso a Sessoes e Service
# Tokens, antes de as contas nominais existirem la. Senha aleatoria por tenant e
# troca obrigatoria no primeiro acesso.
#
# ⚠️ `setup_db.py::seed_data` REPETE estas para semear o tenant novo (roda fora
# do app, nao da para importar daqui). Mexeu aqui, mexa la.
#
# ⚠️ ESTA LISTA DEIXOU DE SER A AUTORIDADE. A autoridade e a coluna
# `users.super_admin`, semeada destes quatro e-mails pela migration deste
# incremento — trocar quem manda virou um UPDATE, e nao mais um deploy. A lista
# fica como SEMENTE e como REFORCO em `is_super_admin`: se a migration nao rodou
# (ou rodou errado), a Alavank nao pode perder a porta de entrada do proprio
# produto — e neste sistema quem tem a chave e quem consegue devolver o acesso
# aos outros.
SUPER_ADMIN_EMAILS = {
    "super-admin@alavank.com.br",
    "alavank.tecnologia@gmail.com",
    "matheus@alavank.com.br",
    "tiagomiller@alavank.com.br",
}


def is_super_admin(user) -> bool:
    """Conta DONA da plataforma (Alavank).

    Le a COLUNA primeiro — e ela que permite promover/despromover um dono sem
    deploy. A allowlist de e-mails segue valendo como reforco: banco sem a
    coluna (migracao pendente, tenant recem-criado, objeto de teste) nao pode
    trancar a Alavank fora. `getattr` com default porque este modulo tambem e
    chamado com objetos que nao sao o modelo completo.

    A soma e deliberadamente OU e nao E: as duas fontes so ampliam, nunca
    cortam. Nao ha caminho em que um erro de dado tire o acesso do dono.
    """
    if bool(getattr(user, "super_admin", False)):
        return True
    return (getattr(user, "email", "") or "").strip().lower() in SUPER_ADMIN_EMAILS


def eh_credencial_sintetica(user) -> bool:
    """Conta que NAO e pessoa e por isso nunca escreve — hoje so o quiosque.

    ⚠️ NAO E a antiga `eh_somente_leitura`. Aquela lia a coluna
    `users.somente_leitura` e valia para PESSOAS (o prefeito); esta olha so o
    papel sintetico do link publico de TV. A trava por pessoa saiu em 05/09/2026
    — ver o bloco no topo do modulo — e foi substituida pelas caixinhas de
    escrita de cada tela."""
    return (getattr(user, "role", "") or "") in PAPEIS_SINTETICOS_SEM_ESCRITA

# ---------------------------------------------------------------------------
# QUIOSQUE — o que o link PUBLICO de TV pode alcancar
# ---------------------------------------------------------------------------
# O token vem de `GET /bi/tela-pub/{slug}`, que e PUBLICO: o slug de 12 chars e o
# unico segredo, e o link existe para circular (WhatsApp, TV de gabinete). Ele e
# um usuario `viewer` REAL, entao passava por `get_current_user` como qualquer
# um — e o guard de somente-leitura acima barra ESCRITA, nao LEITURA. Com 55 dos
# 171 endpoints sem checagem alguma, o link lia anotacao da Gestao Interna com
# anexo, RM, documentos e o status da sessao gov.br do cliente inteiro.
#
# A lista abaixo foi MEDIDA: e o conjunto exato que `/tela`, `/t/<slug>` e
# `/m/<slug>` chamam, varrendo o grafo de imports das tres paginas. Nao e
# prefixo — e IGUALDADE. Com `startswith`, liberar `/api/bi/parlamentares/
# detalhe` abriria `/api/bi/parlamentares` de brinde, e o prefixo `/api/bi`
# abriria `/api/bi/narrativa`, que chama a Anthropic (link vazado = conta paga).
#
# FICARAM DE FORA de proposito, conferido caller a caller no frontend:
#   /api/bi/narrativa, /timeline, /semaforo, /parlamentares (sem /detalhe),
#   /api/bi/preferencias, /vapid-public-key, /tela-links  -> ninguem chama
#   /api/auth/me            -> so `/tela` chama, e la ha sessao real; alem disso
#                              devolve o NOME do gestor dono do link
#   /api/session-capture/*  -> vaza `observacao` do Cofre, sem escopo de municipio
KIOSK_GET_PERMITIDOS = frozenset({
    "/api/municipios",              # exato: main.py usa redirect_slashes=False
    "/api/bi/overview",
    "/api/bi/alertas",
    "/api/bi/insights",
    "/api/bi/parlamentares/detalhe",
    "/api/bi/transferegov",
    "/api/bi/estaduais",
    "/api/bi/documentos",           # atende as abas CAUC e CAGEC
    "/api/bi/sismob",
    "/api/bi/fns",
    "/api/bi/tela-filtros",         # so `/tela`, para os links legados ?kiosk=
})


def ehQuiosque(user) -> bool:
    """Conta de quiosque? Le do USUARIO — ver migrations/add_users_kiosk.sql."""
    return bool(getattr(user, "kiosk", False))

# Blacklist em memoria (suficiente para single-instance; em multi-replica usar Redis)
_REVOKED_JTI: set[str] = set()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _encode(payload: dict, ttl_minutes: int) -> str:
    to_encode = payload.copy()
    now = datetime.now(timezone.utc)
    to_encode.update({
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=ttl_minutes)).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": "pactha-api",
    })
    return pyjwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(data: dict) -> str:
    payload = data.copy()
    if "sub" in payload:
        payload["sub"] = str(payload["sub"])
    payload["typ"] = "access"
    return _encode(payload, settings.JWT_EXPIRE_MINUTES)


def create_refresh_token(user_id: int, sid: str | None = None) -> str:
    """`sid` = identificador da SESSAO, que atravessa a renovacao do token.

    Ate aqui o sistema nao tinha sessao: tinha token de 60 minutos, e cada
    renovacao gerava um `jti` novo. `services/audit.py::_sessao` deriva a sessao
    de `sid or jti` e caia sempre no `jti` — entao a trilha FATIAVA um expediente
    de 4 horas em quatro sessoes sem relacao, e qualquer "tempo logado" tinha
    teto de 60 minutos: um numero plausivel e falso.

    O autor da trilha ja tinha deixado o gancho pronto: "se um dia o token passar
    a carregar `sid` atravessando o refresh, ele passa a mandar aqui sem mudar
    mais nada". E o que esta linha faz.

    Ausente (token velho ainda em circulacao) cai no `jti`, que e o
    comportamento de hoje — a virada e silenciosa e nao invalida ninguem."""
    corpo = {"sub": str(user_id), "typ": "refresh"}
    if sid:
        corpo["sid"] = sid
    return _encode(corpo, REFRESH_TTL_DAYS * 24 * 60)


def create_kiosk_token(user_id: int, dias: int = 365) -> str:
    """Access token de LONGA duracao para a TV (quiosque do Painel). typ='access'
    p/ o get_current_user aceitar sem mudanca; o usuario e um 'viewer' escopado ao
    municipio (read-only pelo guard). Revogacao = desativar o usuario viewer."""
    return _encode({"sub": str(user_id), "typ": "access", "role": "viewer", "kiosk": True}, dias * 24 * 60)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _sso_audience() -> str:
    """Identidade DESTA instancia, usada como 'aud' do token SSO. Amarra o token ao
    tenant que o emitiu: um token de A e rejeitado por B mesmo que (por erro de ops)
    dois tenants compartilhem o JWT_SECRET. Sempre nao-vazio p/ evitar aud ambiguo."""
    return settings.INSTANCE_SLUG or settings.FRONTEND_URL or "pactha-instance"


def create_sso_token(user_id: int) -> str:
    """Token de uso único e CURTO (2 min) p/ o SSO da Central: o aceitador o troca
    por uma sessao. typ='sso' impede reuso como access/refresh; aud amarra a instancia."""
    return _encode({"sub": str(user_id), "typ": "sso", "aud": _sso_audience()}, 2)


def decode_sso(token: str) -> dict:
    return _decode(token, "sso", audience=_sso_audience())


def revoke_jti(jti: str):
    _REVOKED_JTI.add(jti)


def is_revoked(jti: str) -> bool:
    return jti in _REVOKED_JTI


def _decode(token: str, expected_typ: str = "access", audience: Optional[str] = None) -> dict:
    # aud so e exigido/validado p/ tokens SSO (audience != None). Access/refresh nao
    # carregam aud e sao decodificados sem audience -> pyjwt nao verifica esse claim.
    require = ["exp", "iat", "jti", "iss"] + (["aud"] if audience is not None else [])
    kwargs = dict(
        algorithms=[settings.JWT_ALGORITHM],
        issuer="pactha-api",
        options={"require": require},
    )
    if audience is not None:
        kwargs["audience"] = audience
    try:
        payload = pyjwt.decode(token, settings.JWT_SECRET, **kwargs)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido")

    if payload.get("typ") != expected_typ:
        raise HTTPException(status_code=401, detail="Tipo de token incorreto")
    if is_revoked(payload.get("jti", "")):
        raise HTTPException(status_code=401, detail="Token revogado")
    return payload


def decode_access(token: str) -> dict:
    return _decode(token, "access")


def decode_refresh(token: str) -> dict:
    return _decode(token, "refresh")


def set_auth_cookies(response, access_token: str, refresh_token: str, csrf: str):
    """Seta cookies httpOnly de auth. Em prod usar secure=True + SameSite=Lax."""
    secure = os.getenv("ENV", "").lower() == "production"
    response.set_cookie(
        COOKIE_NAME_ACCESS, access_token,
        httponly=True, secure=secure, samesite="lax",
        max_age=settings.JWT_EXPIRE_MINUTES * 60, path="/",
    )
    response.set_cookie(
        COOKIE_NAME_REFRESH, refresh_token,
        httponly=True, secure=secure, samesite="lax",
        max_age=REFRESH_TTL_DAYS * 24 * 60 * 60, path="/api/auth",
    )
    # CSRF token NAO httpOnly (frontend precisa ler e enviar no header X-CSRF-Token)
    response.set_cookie(
        COOKIE_NAME_CSRF, csrf,
        httponly=False, secure=secure, samesite="lax",
        max_age=settings.JWT_EXPIRE_MINUTES * 60, path="/",
    )


def clear_auth_cookies(response):
    for name in (COOKIE_NAME_ACCESS, COOKIE_NAME_REFRESH, COOKIE_NAME_CSRF):
        response.delete_cookie(name, path="/")
        response.delete_cookie(name, path="/api/auth")


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Aceita tanto Bearer header quanto cookie httpOnly."""
    token = None
    if credentials:
        token = credentials.credentials
    if not token:
        token = request.cookies.get(COOKIE_NAME_ACCESS)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")

    payload = decode_access(token)
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Token inválido")

    # CSRF check para mutating methods se vier por cookie (nao por Bearer)
    if not credentials and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        csrf_cookie = request.cookies.get(COOKIE_NAME_CSRF)
        csrf_header = request.headers.get("X-CSRF-Token")
        # Permitir bypass se Authorization header presente
        if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
            raise HTTPException(status_code=403, detail="CSRF token inválido")

    user_id = int(user_id_str)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    await load_user_scopes(db, user)

    # Contexto para o modo aviso do authz. Vem DEPOIS de `load_user_scopes`
    # porque a linha da trilha registra "o que ele TEM" — antes disso os
    # escopos ainda nao estao anexados ao user e a trilha diria que todo mundo
    # nao tem nada. `definir_contexto` nunca levanta.
    authz.definir_contexto(request, user)

    # ⚠️ A TRAVA DE CONTA «somente leitura» SAIU em 05/09/2026 (ver o topo do
    # modulo). O que barra escrita agora e a caixinha de cada tela, cobrada por
    # `exige()` em cada rota — e ela so passou a barrar de verdade no mesmo
    # deploy, quando `AUTHZ_MODO` deixou de ser `aviso`.
    #
    # O que sobrou aqui e a credencial SINTETICA: o `viewer` do link publico de
    # TV nunca escreve, e sem allowlist nenhuma. O quiosque nao tem "escrita
    # legitima" — o bloco logo abaixo ja o limita a uma lista exata de GETs, e
    # este e o segundo cinto para a conta legada cuja coluna `kiosk` ficou false.
    if (eh_credencial_sintetica(user)
            and request.method in ("POST", "PUT", "PATCH", "DELETE")):
        raise HTTPException(
            status_code=403,
            detail="Este link só alcança o Painel de Indicadores")

    # QUIOSQUE: so as leituras que a TV e o celular realmente fazem.
    #
    # 403 e NAO 401, de proposito. O interceptor do front (`lib/api.ts`) reage a
    # 401 tentando refresh e, se falhar, faz `window.location.href = "/login"` —
    # ou seja, um 401 aqui transformaria o painel do gabinete numa tela de login
    # a cada volta do slideshow. Com 403 a aba apenas nao carrega, e todos os
    # consumidores ja engolem o erro.
    if ehQuiosque(user):
        if request.method != "GET" or request.url.path not in KIOSK_GET_PERMITIDOS:
            raise HTTPException(
                status_code=403,
                detail="Este link só alcança o Painel de Indicadores",
            )

    return user


# ---------------------------------------------------------------------------
# ⭐⭐ COMPATIBILIDADE DAS TELAS RENOMEADAS — a rede que NAO depende de migration
# ---------------------------------------------------------------------------
# Em 05/09/2026 duas chaves de tela viraram dezoito: `transferegov` -> as 8
# telas do grupo FEDERAIS, `convenios` -> as 10 do grupo ESTADUAIS (das quais 8
# eram novas). `add_permissoes_por_tela.sql` traduz as linhas de `user_telas` e
# `user_permissoes` de todo mundo.
#
# ⚠️ MAS UMA MIGRATION QUE FALHA NAO DERRUBA O BOOT — ela loga e o processo
# segue (`services/startup.py`, o `except` que so trata "already exists"). Com
# `AUTHZ_MODO=bloqueio` ligado no MESMO deploy, o desfecho de uma falha ali
# seria: API no ar, ninguem traduzido, e todo usuario perdendo os dois maiores
# grupos do menu — em cinco prefeituras, em silencio.
#
# E `AUTHZ_MODO=aviso` NAO SALVARIA: `ensure_tela` e da familia antiga e nega
# nos DOIS modos. A valvula de escape que existe para as caixinhas nao existe
# para as telas.
#
# Entao a compatibilidade mora AQUI, no codigo, e nao no dado: quem tem a chave
# antiga tem as novas, tenha a migration rodado ou nao. Custa um `if` por
# requisicao e torna o deploy reversivel por rollback de imagem, que e a unica
# reversao que sempre funciona.
#
# ⚠️ ISTO NAO SUBSTITUI A MIGRATION, e nem torna a coisa permanente: a migration
# grava as chaves NOVAS, que sao as que a tela de Usuarios desenha e edita. Sem
# ela o administrador veria as telas novas desmarcadas para quem, na pratica,
# tem acesso — e desmarcar o que ja esta desmarcado nao tira nada. Este mapa e a
# rede de seguranca do intervalo entre o deploy e a migration ter rodado,
# e sai quando os cinco bancos estiverem confirmados.
TELAS_RENOMEADAS: dict = {
    "transferegov": (
        "transferegov_radar", "transferegov_geral", "transferegov_especiais",
        "transferegov_pac", "transferegov_voluntarias",
        "transferegov_rejeitadas", "transferegov_encerradas",
        "transferegov_cnpj",
    ),
    # `convenios` CONTINUA sendo tela (a de Convenios Estaduais). O que ela ganha
    # sao as oito que estavam escondidas dentro dela.
    "convenios": (
        "repasses", "cofinanciamento", "monitoramento", "consulta_popular",
        "programas_rs", "funrigs", "emendas_rs", "tce_rs",
    ),
    # A aba Telemetria usava a chave `auditoria` — a de outra coisa.
    "auditoria": ("telemetria",),
}


# ⭐ AS ABAS DE ADMINISTRACAO QUE O PAPEL `admin` ABRIA ATE 05/09/2026.
#
# ⚠️⚠️ ESTA REDE NASCEU DE UM DEFEITO REAL, MEDIDO EM PRODUCAO. Usuarios, Status
# dos Dados e Parametros eram governadas pelo PAPEL: nao havia linha em
# `user_telas` para elas, e `_require_admin` (o antigo) abria pelo `role`.
# Quando elas viraram TELAS, quem devia gravar a linha era a parte 2 de
# `add_permissoes_por_tela.sql` — e essa migration NAO RODOU no deploy.
#
# Resultado medido no freitas: todo `role='admin'` que nao e super-admin ficou
# com a aba Usuarios VISIVEL (o frontend a mostra por papel, ver
# `lib/configuracoes.ts::abasVisiveis`) e a tela devolvendo 403. Ou seja: a
# unica tela que conserta permissao era a que ninguem conseguia abrir. E o
# `AUTHZ_MODO=aviso` nao salvaria, porque `ensure_tela` nega nos dois modos.
#
# Entao a compatibilidade mora AQUI, como a das telas renomeadas: o papel volta
# a abrir estas tres enquanto a linha nao existir no banco.
#
# ⚠️ NAO E AFROUXAMENTO — e a restauracao exata do que valia na vespera. O papel
# `admin` abria estas tres telas desde sempre; o incremento pretendia trocar o
# papel pela linha, e a troca so vale quando a linha existir. As DEMAIS telas
# continuam exigindo concessao: um admin sem `cofre` nao ganha o Cofre por aqui.
#
# ⚠️ ELA SAI quando os cinco bancos confirmarem a migration — junto com
# `TELAS_RENOMEADAS`, pelo mesmo motivo e no mesmo commit.
TELAS_DE_ADMINISTRACAO: frozenset = frozenset({"usuarios", "frescor", "parametros"})


def expandir_telas_legadas(telas: set, papel: str = "") -> set:
    """As telas da pessoa, mais as que as chaves antigas passaram a significar.

    Idempotente: rodar sobre um conjunto ja traduzido nao muda nada."""
    saida = set(telas)
    for antiga, novas in TELAS_RENOMEADAS.items():
        if antiga in saida:
            saida.update(novas)
    if (papel or "").strip().lower() == "admin":
        saida |= TELAS_DE_ADMINISTRACAO
    return saida


async def load_user_scopes(db: AsyncSession, user: User) -> None:
    """Anexa ao user os escopos de acesso: municipios + telas + PERMISSOES.

    Super-admin (Alavank) -> None nos tres, que os `ensure_*` leem como "sem
    limite". TODO o resto — INCLUSIVE quem esta marcado `admin` — passa a valer
    exatamente o que houver em `user_telas`/`user_municipios`; conjunto vazio e
    "nao pode nada", nao "pode tudo".

    ⭐ FOI AQUI QUE `role` DEIXOU DE CONCEDER. Antes, `role == "admin"` zerava os
    dois limites: nao era "coordenador do cliente", era ausencia total de limite
    — e como o cadastro nascia com `role="admin"` por default, um POST sem o
    campo criava um deus. Pela regra do dono, papel e ROTULO de organizacao
    interna do cliente; o que vale e a permissao dada a cada usuario
    INDIVIDUALMENTE, porque nao da para supor que todos os analistas de uma
    prefeitura devam enxergar a mesma coisa.

    O super-admin fica de fora da regra de proposito: a Alavank e dona da
    plataforma e precisa de porta de entrada. Sem essa excecao, um tenant cujo
    cadastro de telas ficasse vazio trancaria o suporte para fora do proprio
    produto — e ninguem sobraria para devolver o acesso.

    ⚠️ A migration deste incremento concede a TODO `role='admin'` ativo o
    catalogo INTEIRO de telas e TODOS os municipios ativos, na mesma transacao e
    ANTES desta linha passar a valer. Sem esse backfill os admins do cliente —
    que nunca precisaram de linha em `user_telas` — perderiam o sistema inteiro
    no deploy. Mexer nesta funcao sem conferir aquela migration derruba o cliente.
    """
    if is_super_admin(user):
        user.allowed_municipio_ids = None
        user.allowed_telas = None
        # None aqui NAO e o que concede: quem decide e `super_admin=True` na
        # funcao pura (services/permissoes.py::permissoes_efetivas), que nem
        # olha para este campo. Fica None so para o objeto ficar coerente com os
        # outros dois — e porque a convencao inversa ("None = tudo") foi
        # exatamente a que criou o deus por default no Incremento 4.
        user.allowed_permissoes = None
        # ⚠️ DICIONARIO VAZIO, e nao None: aqui a convencao "None = sem limite"
        # nao existe, porque o alcance nao e um limite que se remove — e um
        # MODIFICADOR cujo default (`todos`) ja e a ausencia de restricao.
        # Super-admin passa por cima por `is_super_admin` em
        # `authz.escopo_de`, nao por um valor sentinela que alguem possa
        # reproduzir sem querer noutro caminho.
        user.allowed_escopos = {}
        return
    mrows = await db.execute(
        text("SELECT municipio_id FROM user_municipios WHERE user_id = :u"), {"u": user.id})
    user.allowed_municipio_ids = {r[0] for r in mrows.fetchall()}
    trows = await db.execute(
        text("SELECT tela FROM user_telas WHERE user_id = :u"), {"u": user.id})
    user.allowed_telas = expandir_telas_legadas(
        {r[0] for r in trows.fetchall()}, getattr(user, "role", "") or "")
    user.allowed_permissoes = await _carregar_permissoes(db, user.id)
    user.allowed_escopos = await _carregar_escopos(db, user.id)


async def _carregar_escopos(db: AsyncSession, user_id: int) -> dict:
    """O ALCANCE por modulo deste usuario (Incremento 6): `{recurso: escopo}`.

    Recurso ausente do dicionario = `todos` — o valor que nao restringe ninguem.

    ⚠️ POR QUE A FALHA AQUI VIRA VAZIO E ISSO **NAO** CONTRADIZ O FAIL-CLOSED DE
    `_carregar_permissoes`, que fica logo acima e falha na direcao oposta:

      * la, vazio = "nenhuma permissao concedida". Aqui, vazio = "nenhuma
        RESTRICAO configurada". As duas coisas sao a mesma frase — **o estado do
        banco antes de alguem configurar qualquer coisa** — e as duas devolvem o
        comportamento que o tenant ja tinha. Acontece que num caso isso fecha e
        no outro abre, porque uma tabela concede e a outra restringe.

      * o contrario seria destrutivo e desproporcional: uma tabela ausente
        (migration nao rodou, banco em manutencao) trancaria TODA a prefeitura
        em "so os que ele criou" de uma vez, sem ninguem ter pedido, e o suporte
        veria "sumiu o botao de editar" sem relacao aparente com a causa. O
        alcance e opt-in, deliberado, um usuario por vez; ele nao pode nascer de
        um erro de I/O.

    ⚠️ CUSTO DECLARADO: mais UM SELECT por requisicao autenticada (o quarto desta
    funcao). E uma busca por prefixo da chave primaria devolvendo no maximo tres
    linhas, mas ela acontece em TODA requisicao — inclusive nas de quem nunca foi
    restringido. Junta-la a consulta de `user_permissoes` economizaria uma ida ao
    banco e custaria a distincao acima: as duas falham em direcoes opostas de
    proposito, e numa consulta so nao haveria como falhar diferente.

    O CRITICO no log e o que faz o problema aparecer, e o SAVEPOINT
    (`begin_nested`) e pelo mesmo motivo da funcao acima: sem ele um erro aqui
    aborta a transacao inteira e a proxima consulta do endpoint quebra com um
    erro sem relacao aparente.
    """
    try:
        async with db.begin_nested():
            linhas = await db.execute(
                text("SELECT recurso, escopo FROM user_escopos WHERE user_id = :u"),
                {"u": user_id})
        return {r[0]: r[1] for r in linhas.fetchall()}
    except Exception:
        _logger_auth.critical(
            "Nao consegui ler user_escopos do usuario %s — seguindo com alcance "
            "'todos' em todos os modulos (o comportamento anterior ao "
            "Incremento 6). Se a migration add_escopo_por_modulo.sql nao rodou, "
            "e isso.", user_id, exc_info=True)
        return {}


async def _carregar_permissoes(db: AsyncSession, user_id: int) -> set:
    """As linhas de `user_permissoes` deste usuario (Incremento 5).

    ⚠️ AS DUAS DECISOES DESTA FUNCAO, e as duas sao sobre o dia em que ela
    falhar:

    1. SAVEPOINT (`begin_nested`). Sem ele, um erro aqui — tabela ausente porque
       a migration nao rodou — ABORTA a transacao inteira no Postgres, e a
       proxima consulta do endpoint quebra com um erro sem relacao aparente.
       Mesma razao de `services/authz.py::ensure_dono`.

    2. FALHA VIRA CONJUNTO VAZIO, e nao excecao. Levantar aqui derrubaria TODA
       requisicao autenticada do sistema (esta funcao roda em `get_current_user`)
       — a API inteira de uma prefeitura fora do ar porque uma tabela nova nao
       existe. Vazio e fail-closed e, com `AUTHZ_MODO=aviso` (o default), nao
       tira nada de ninguem: a trava so fala. O CRITICO no log e o que faz o
       problema aparecer.

       ⚠️ O que NAO pode acontecer aqui e devolver `None`: None e "sem limite"
       no vocabulario deste arquivo, e um erro de banco viraria acesso total.
    """
    try:
        async with db.begin_nested():
            linhas = await db.execute(
                text("SELECT permissao FROM user_permissoes WHERE user_id = :u"),
                {"u": user_id})
        return {r[0] for r in linhas.fetchall()}
    except Exception:
        _logger_auth.critical(
            "Nao consegui ler user_permissoes do usuario %s — seguindo com ZERO "
            "permissao (fail-closed). Se a migration add_permissoes_por_acao.sql "
            "nao rodou, e isso.", user_id, exc_info=True)
        return set()


def ensure_municipio_access(user: User, municipio_id) -> None:
    """Barra acesso a municipio fora do escopo do usuario.
    `allowed_municipio_ids=None` (hoje so o super-admin — ver `load_user_scopes`;
    antes deste incremento, qualquer `role='admin'`) sempre passa. Todo o resto
    precisa informar um municipio_id que esteja no seu conjunto atribuido.

    ⚠️ ESTA FUNCAO NEGA SEMPRE, NOS DOIS MODOS — nao passa pelo modo aviso de
    `services/authz.py`. Ela ja era chamada em dezenas de lugares ANTES do
    Incremento 2, e cada um deles e uma trava que ja vale hoje; roteá-la pelo
    modo aviso faria essas negativas ANTIGAS pararem de negar durante a semana
    de observacao, alargando o acesso justamente no incremento que existe para
    fecha-lo. Ver o docstring do authz para o porque.

    Gate NOVO usa `authz.exigir_municipio`, que respeita o modo. E la, no gate
    novo, que pedido MALFORMADO tambem continua levantando nos dois modos:
    municipio AUSENTE e municipio NAO-NUMERICO nao sao permissao que falta —
    sao pedido malformado. Nenhuma correcao de cadastro faz um pedido sem
    municipio virar valido, entao observa-los nao ensina nada; e deixa-los
    passar trocaria um 403 honesto por um 500 (o None desce ate a consulta) ou
    por uma consulta sem filtro devolvendo o tenant inteiro."""
    allowed = getattr(user, "allowed_municipio_ids", None)
    if allowed is None:
        return
    if municipio_id is None:
        raise HTTPException(status_code=403, detail="Selecione um municipio permitido")
    try:
        mid = int(municipio_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=403, detail="Municipio invalido")
    if mid not in allowed:
        # NEGA SEMPRE — ver a nota em `ensure_tela`. Gate NOVO usa
        # `authz.exigir_municipio`, que respeita o modo.
        raise HTTPException(status_code=403, detail="Voce nao tem acesso a este municipio")


def ensure_tela(user: User, tela: str) -> None:
    """403 se o usuario nao tem acesso a tela/modulo.

    `allowed_telas=None` passa — e desde este incremento isso e SO o super-admin
    (ver `load_user_scopes`). Quem esta marcado `admin` agora vale pelas linhas
    de `user_telas`, como todo mundo.

    ⚠️ ESTA FUNCAO NEGA SEMPRE, NOS DOIS MODOS — e nao passa pelo modo aviso
    de `services/authz.py`. Ela ja era chamada em ~128 pontos ANTES do
    Incremento 2, e cada um deles e uma trava que ja vale hoje. Roteá-la pelo
    modo aviso faria essas 128 negativas ANTIGAS pararem de negar durante a
    semana de observacao: o sistema ficaria MAIS ABERTO justamente no
    incremento que existe para fecha-lo.

    Gate NOVO usa `authz.exigir_tela`, que respeita o modo. A distincao e
    explicita no CHAMADOR de proposito: em tempo de execucao nao ha como
    saber se uma chamada e velha ou nova.
    """
    allowed = getattr(user, "allowed_telas", None)
    if allowed is None:
        return
    if tela not in allowed:
        raise HTTPException(status_code=403, detail="Voce nao tem acesso a esta tela")
