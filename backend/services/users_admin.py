"""
Helpers de gestão de usuários do tenant reaproveitáveis pelo canal de control
(Console Alavank). O Console conhece município por `ibge_code` (chave estável),
nunca pelo PK local — por isso a tradução ibge<->municipio_id acontece aqui.
"""
import secrets
import string
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ALPHABET = string.ascii_letters + string.digits + "!@#$%&*"
# prefeito/viewer = perfis SOMENTE-LEITURA (Painel Executivo). O guard read-only
# em services/auth.py barra qualquer escrita fora dos endpoints do proprio Painel.
ROLES = ("admin", "analyst", "user", "prefeito", "viewer")


def gen_senha(n: int = 14) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(n))


async def set_user_telas(db: AsyncSession, user_id: int, telas) -> None:
    await db.execute(text("DELETE FROM user_telas WHERE user_id = :u"), {"u": user_id})
    for t in (telas or []):
        t = str(t).strip()
        if t:
            await db.execute(
                text("INSERT INTO user_telas (user_id, tela) VALUES (:u, :t) ON CONFLICT DO NOTHING"),
                {"u": user_id, "t": t})


async def set_user_municipios_by_ibge(db: AsyncSession, user_id: int, ibge_codes) -> list:
    """Substitui o escopo de municípios do usuário. Resolve ibge->municipio_id;
    ibge não encontrado é ignorado (retornado como 'unmatched')."""
    unmatched = []
    await db.execute(text("DELETE FROM user_municipios WHERE user_id = :u"), {"u": user_id})
    for ibge in (ibge_codes or []):
        row = (await db.execute(
            text("SELECT id FROM municipios WHERE ibge_code = :i"), {"i": str(ibge)})).first()
        if not row:
            unmatched.append(str(ibge))
            continue
        await db.execute(
            text("INSERT INTO user_municipios (user_id, municipio_id) VALUES (:u, :m) ON CONFLICT DO NOTHING"),
            {"u": user_id, "m": row[0]})
    return unmatched


async def get_user_ibges(db: AsyncSession, user_id: int) -> list:
    rows = (await db.execute(text(
        "SELECT m.ibge_code FROM user_municipios um "
        "JOIN municipios m ON m.id = um.municipio_id WHERE um.user_id = :u"), {"u": user_id})).fetchall()
    return sorted(r[0] for r in rows)


async def get_user_telas(db: AsyncSession, user_id: int) -> list:
    rows = (await db.execute(text("SELECT tela FROM user_telas WHERE user_id = :u"), {"u": user_id})).fetchall()
    return sorted(r[0] for r in rows)
