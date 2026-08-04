"""
Cofre de Senhas — armazenamento criptografado (AES-GCM).

Politicas:
- Listing nao expoe senha em claro (mascara) e exige a tela `cofre` + o municipio.
- Endpoint dedicado /reveal exige o papel `admin` + registra auditoria.
- CRUD (POST/PUT/DELETE) restrito ao papel `admin`.

⚠️ O docstring anterior anunciava "admin/gestor" nas tres linhas, e `gestor`
NUNCA existiu: nao esta em `services/users_admin.py::ROLES`, nao e aceito por
`routers/users.py::create_user` e nao ha uma linha em `users.role` com esse
valor. Era ramo morto, e ramo morto em regra de permissao e pior que ausencia —
lido de fora, o arquivo prometia um papel intermediario ("o gestor da prefeitura
mexe no Cofre") que o codigo nunca cumpriu; o Cofre sempre foi admin-only na
pratica. O nome saiu para o que esta escrito aqui ser o que roda.

Este e um gate por PAPEL, e ele fica de fora do incremento que fez `role` deixar
de conceder ESCOPO: papel deixou de valer para o que voce ENXERGA, e continua
valendo para o que voce FAZ ate o Incremento 5 (permissao por acao) trocar as
duas coisas de lugar com uma tela que explique a mudanca. O Cofre guarda a
credencial gov.br do cliente — se e para ele mudar de dono, que mude de proposito
e nao de raspao.

PERMISSAO POR ACAO (`exige`, ver services/registro_rotas.py)
------------------------------------------------------------
Cada rota declara agora o que exige, e o gate por papel acima CONTINUA no corpo:
sao duas travas somando, nao uma trocando a outra — enquanto `AUTHZ_MODO=aviso`
a declaracao so registra, e retirar `_require_role` "porque agora ha permissao"
abriria o CRUD do Cofre para todo mundo na mesma hora.

`cofre.revelar` e uma caixinha SEPARADA de `cofre.ver`, e e a linha mais
importante deste arquivo: ver que a credencial existe (sistema, usuario, senha
mascarada) nao e ver a credencial. Quem tiver so `cofre.ver` lista; quem revela
precisa da segunda caixinha, e a revelacao continua virando linha na trilha.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import logging

from database import get_db
from models.cofre import CofreSenha
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services import crypto
from services.audit import log_event
from services.registro_rotas import exige

router = APIRouter(prefix="/api/cofre", tags=["cofre"])
logger = logging.getLogger("cofre.audit")

# So `admin`. `gestor` saiu daqui: era um papel que o sistema nunca soube criar
# — ver o cabecalho do arquivo. Nenhum acesso muda com a remocao (nenhum usuario
# jamais casou com essa string); some so a promessa falsa.
ALLOWED_ROLES_WRITE = {"admin"}
ALLOWED_ROLES_REVEAL = {"admin"}


def _require_role(user: User, allowed: set[str]):
    if (user.role or "").lower() not in allowed:
        raise HTTPException(status_code=403, detail="Acao restrita a administradores")


class CofreCreate(BaseModel):
    municipio_id: int
    sistema: str
    url: Optional[str] = None
    usuario: Optional[str] = None
    senha: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None
    automation_key: Optional[str] = None  # ex: "fns", "simec", "sismob", "suas"


class CofreUpdate(BaseModel):
    sistema: Optional[str] = None
    url: Optional[str] = None
    usuario: Optional[str] = None
    senha: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None
    automation_key: Optional[str] = None


class CofreResponse(BaseModel):
    id: int
    municipio_id: int
    sistema: str
    url: Optional[str] = None
    usuario: Optional[str] = None
    senha_mascarada: Optional[str] = None
    observacao: Optional[str] = None
    categoria: Optional[str] = None
    automation_key: Optional[str] = None

    class Config:
        from_attributes = True


def _mask_smart(senha_clear: str) -> str:
    """Mascara inteligente: se for JSON de cookies (sessao capturada),
    mostra placeholder semantico ao inves de tentar mascarar JSON."""
    if not senha_clear:
        return ""
    s = senha_clear.strip()
    if s.startswith("{") and '"cookies"' in s:
        try:
            import json as _json
            obj = _json.loads(s)
            if obj.get("format") == "cookies_full":
                n = len(obj.get("cookies", []))
                return f"[Sessao capturada · {n} cookies]"
        except Exception:
            pass
    return crypto.mask(senha_clear)


def _to_response(item: CofreSenha) -> CofreResponse:
    senha_clear = crypto.decrypt(item.senha_encrypted) if item.senha_encrypted else ""
    return CofreResponse(
        id=item.id,
        municipio_id=item.municipio_id,
        sistema=item.sistema,
        url=item.url,
        usuario=item.usuario,
        senha_mascarada=_mask_smart(senha_clear),
        observacao=item.observacao,
        categoria=item.categoria,
        automation_key=item.automation_key,
    )


@router.get("", response_model=list[CofreResponse],
            dependencies=[exige("cofre.ver")])
async def list_senhas(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ensure_municipio_access(user, municipio_id)
    ensure_tela(user, "cofre")
    q = select(CofreSenha)
    if municipio_id:
        q = q.where(CofreSenha.municipio_id == municipio_id)
    q = q.order_by(CofreSenha.categoria, CofreSenha.sistema)
    result = await db.execute(q)
    items = result.scalars().all()
    return [_to_response(i) for i in items]


@router.get("/{item_id}/reveal", dependencies=[exige("cofre.revelar")])
async def reveal_senha(
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Retorna a senha em claro. Restrito ao papel `admin` + auditoria."""
    _require_role(user, ALLOWED_ROLES_REVEAL)
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")
    await log_event(
        db, action="cofre.reveal", user=user, request=request,
        target_type="cofre_senha", target_id=item.id,
        details={"sistema": item.sistema, "municipio_id": item.municipio_id},
    )
    return {"senha": crypto.decrypt(item.senha_encrypted) if item.senha_encrypted else ""}


@router.post("", response_model=CofreResponse,
             dependencies=[exige("cofre.criar")])
async def create_senha(
    data: CofreCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(user, ALLOWED_ROLES_WRITE)
    item = CofreSenha(
        municipio_id=data.municipio_id,
        sistema=data.sistema,
        url=data.url,
        usuario=data.usuario,
        senha_encrypted=crypto.encrypt(data.senha) if data.senha else None,
        observacao=data.observacao,
        categoria=data.categoria,
        automation_key=data.automation_key,
        atualizado_por_id=user.id,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    await log_event(
        db, action="cofre.create", user=user, request=request,
        target_type="cofre_senha", target_id=item.id,
        details={"sistema": item.sistema, "municipio_id": item.municipio_id},
    )
    return _to_response(item)


@router.put("/{item_id}", response_model=CofreResponse,
            dependencies=[exige("cofre.editar")])
async def update_senha(
    item_id: int,
    data: CofreUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(user, ALLOWED_ROLES_WRITE)
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")

    fields = data.model_dump(exclude_unset=True)
    senha_changed = "senha" in fields
    if senha_changed:
        senha = fields.pop("senha")
        item.senha_encrypted = crypto.encrypt(senha) if senha else None
    for k, v in fields.items():
        setattr(item, k, v)
    item.atualizado_por_id = user.id

    await db.commit()
    await db.refresh(item)
    await log_event(
        db, action="cofre.update", user=user, request=request,
        target_type="cofre_senha", target_id=item.id,
        details={"sistema": item.sistema, "senha_changed": senha_changed},
    )
    return _to_response(item)


@router.delete("/{item_id}", dependencies=[exige("cofre.excluir")])
async def delete_senha(
    item_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_role(user, ALLOWED_ROLES_WRITE)
    item = await db.get(CofreSenha, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Senha nao encontrada")
    sistema = item.sistema
    await db.delete(item)
    await db.commit()
    await log_event(
        db, action="cofre.delete", user=user, request=request,
        target_type="cofre_senha", target_id=item_id,
        details={"sistema": sistema},
    )
    return {"status": "deleted"}
