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
# `usuario` e a chave NOVA (a migration `add_role_vira_rotulo.sql` funde
# `analyst` e `user` nela). As duas antigas continuam aceitas porque o
# canal da Central e integracoes podem manda-las, e porque papel virou
# ROTULO: recusar um sinonimo do mesmo rotulo so quebraria chamada boa.
ROLES = ("admin", "usuario", "analyst", "user", "prefeito", "viewer")


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


# ---------------------------------------------------------------------------
# EXCLUSÃO DEFINITIVA — a receita numa fonte só, para os dois canais (o produto,
# em routers/users.py, e o Console, em routers/control.py) nunca divergirem.
#
# A lição do control.py:1012-1016 é literalmente esta: as duas tabelas do Painel
# (painel_preferencias/push_subscriptions) chegaram DEPOIS da rotina de exclusão
# do Console e ninguém veio somá-las aqui — resultado, excluir usuário que já
# abriu o Painel devolvia 409 e não havia como remover a conta pelo produto. Com
# a lista viva num lugar só, uma FK nova mexe em um arquivo, não em dois.
# ---------------------------------------------------------------------------

# FKs sem ON DELETE cuja LINHA não sobrevive sem o usuário (coluna é PK ou o
# conteúdo é descartável): a linha inteira sai.
_FK_APAGAR_LINHA = [
    ("painel_preferencias", "user_id"),        # preferência de alerta (user_id é PK)
    ("painel_push_subscriptions", "user_id"),  # inscrição de web-push
]
# FKs sem ON DELETE em coluna que aceita NULL: zera preservando a linha (o
# registro é PATRIMÔNIO do cliente — RM, documento, anotação, senha do cofre —
# e a autoria vira "usuário removido").
_FK_ZERAR = [
    ("cofre_senhas", "atualizado_por_id"),
    ("edital_acompanhamento", "user_id"),
    ("prestacao_contas", "responsavel_id"),
    ("prestacao_documentos", "responsavel_id"),
    # Colunas de autoria SEM FK (não bloqueiam, mas evita id órfão apontando
    # para conta inexistente):
    ("rm_relatorios", "criado_por"),
    ("documentos_gerados", "criado_por"),
    ("gestao_anotacoes", "criado_por"),
    ("service_tokens", "created_by_user_id"),
]
# ⚠️ audit_log NÃO entra em NENHUMA das listas, e a ausência é a decisão mais
# importante daqui. A FK audit_log.user_id -> users foi DERRUBADA de propósito
# (add_auditoria_imutavel.sql) e a tabela é append-only por gatilho: qualquer
# UPDATE/DELETE nela levanta exceção e derrubaria a exclusão inteira. A trilha
# não precisa de nada — user_id/user_email/usuario_nome são SNAPSHOT do instante
# do ato; user_id fica apontando para uma conta que não existe mais, e é assim
# que tem de ser. É o "deixar só o log" que o dono pediu.
# O resto (user_telas, user_municipios, user_permissoes, user_escopos, bi_*,
# ai_conversas, telegram_*) sai por ON DELETE CASCADE — não precisa de linha.


async def _coluna_existe(db: AsyncSession, table: str, col: str) -> bool:
    """Migrations podem ser parciais entre tenants — checa tabela E coluna antes
    de tocar, e só pula se faltar (sem abortar a transação)."""
    return (await db.execute(text(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
        "AND table_name=:t AND column_name=:c"), {"t": table, "c": col})).first() is not None


async def limpar_fks_do_usuario(db: AsyncSession, user_id: int) -> None:
    """Zera/apaga as FKs que bloqueariam o DELETE, preservando o patrimônio.
    NÃO commita — o chamador fecha a transação junto com o delete e a trilha."""
    for table, col in _FK_APAGAR_LINHA:
        if await _coluna_existe(db, table, col):
            await db.execute(text(f"DELETE FROM {table} WHERE {col} = :u"), {"u": user_id})
    for table, col in _FK_ZERAR:
        if await _coluna_existe(db, table, col):
            await db.execute(text(f"UPDATE {table} SET {col} = NULL WHERE {col} = :u"), {"u": user_id})
