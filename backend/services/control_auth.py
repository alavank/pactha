"""
Autenticacao do CONTROL-PLANE (Console Alavank). Terceiro tipo de principal,
distinto do JWT de usuario e do service token de scraper — separado em 3 eixos
(header + kind + namespace de scope) para que o vazamento de um nao escale ao outro:

  | Eixo         | JWT usuario     | Service token scraper | Control token (aqui)  |
  | Header       | Cookie/Bearer   | X-Service-Token       | X-Control-Token       |
  | kind         | -               | 'scraper'             | 'control'             |
  | Scopes       | telas/municipios| secret:*, session:*   | control:*             |

Reusa a tabela service_tokens (hash SHA-256, revoke/rotate, last_used) e o
hash_token/require_scope de service_auth.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import Header, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.service_token import ServiceToken
from database import get_db
from services.service_auth import hash_token, require_scope
from services.net import client_ip, normalizar_ip


class ControlPrincipal:
    """Objeto com .scopes — compativel com require_scope(principal, scope)."""
    def __init__(self, token_id: int, name: str, scopes: list):
        self.token_id = token_id
        self.name = name
        self.scopes = scopes


async def get_control_principal(
    request: Request,
    x_control_token: Optional[str] = Header(None, alias="X-Control-Token"),
    x_tenant_slug: Optional[str] = Header(None, alias="X-Tenant-Slug"),
    db: AsyncSession = Depends(get_db),
) -> ControlPrincipal:
    if not x_control_token or len(x_control_token) < 32:
        raise HTTPException(status_code=401, detail="X-Control-Token obrigatorio")

    th = hash_token(x_control_token)
    tok = (await db.execute(
        select(ServiceToken).where(ServiceToken.token_hash == th))).scalar_one_or_none()
    if not tok or not tok.active:
        raise HTTPException(status_code=401, detail="Control token invalido ou revogado")
    if tok.expires_at and tok.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Control token expirado")
    # kind: um control token apresentado como scraper (ou vice-versa) e rejeitado
    if (getattr(tok, "kind", "scraper") or "scraper") != "control":
        raise HTTPException(status_code=401, detail="Nao e um control token")

    # services/net.py conta o X-Forwarded-For de TRAS para FRENTE. A versao antiga
    # daqui pegava o primeiro item da lista — o pedaco que o proprio cliente
    # escreve — o que deixava a allowlist abaixo ser preenchida pelo atacante.
    ip_cliente = client_ip(request)

    # IP allowlist opcional (Console tem egress fixo).
    allowed = os.getenv("CONTROL_PLANE_ALLOWED_IPS", "").strip()
    if allowed:
        # Normaliza os dois lados: sem isto um IPv6 escrito na env em forma longa
        # (2001:0db8::1) nunca casaria com o mesmo IPv6 vindo do proxy. Entrada da
        # env que nao for IP fica como texto — nao casa com nada e so nega.
        permitidos = {normalizar_ip(i) or i.strip()
                      for i in allowed.split(",") if i.strip()}
        # ip_cliente None = origem indeterminada: nega (fail-closed).
        if not ip_cliente or ip_cliente not in permitidos:
            raise HTTPException(status_code=403, detail="IP nao autorizado para control-plane")

    # Anti-misrouting: nao aceitar mutacao destinada a OUTRO tenant
    slug = os.getenv("INSTANCE_SLUG", "")
    if x_tenant_slug and slug and x_tenant_slug != slug:
        raise HTTPException(status_code=409, detail="Tenant slug divergente")

    # Em producao, exige HTTPS (credencial nao trafega em claro). Fail-closed: o
    # Traefik SEMPRE seta x-forwarded-proto=https; ausencia => bloqueia.
    if os.getenv("ENV", "").lower() == "production":
        proto = request.headers.get("x-forwarded-proto", "").lower()
        if proto != "https":
            raise HTTPException(status_code=400, detail="Control-plane exige HTTPS")

    tok.last_used_at = datetime.now(timezone.utc)
    if ip_cliente:
        tok.last_used_ip = ip_cliente
    await db.commit()
    return ControlPrincipal(tok.id, tok.name, tok.scopes or [])


def require_control_scope(scope: str):
    """Factory de dependency: exige o scope no control token."""
    async def dep(p: ControlPrincipal = Depends(get_control_principal)) -> ControlPrincipal:
        require_scope(p, scope)   # reusa a logica de wildcard de service_auth
        return p
    return dep
