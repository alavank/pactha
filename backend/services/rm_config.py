"""Configuracao do RM que o DONO edita pela tela: o RODAPE e o E-MAIL.

PRECEDENCIA — tres camadas, da mais especifica para a mais geral. Vale IGUAL para
os dois campos:

  1. a coluna DA LINHA em `rm_relatorios` (`rodape`, `email`) — o que foi
     carimbado NAQUELE relatorio. E o que o PDF/Word imprime, e continua sendo:
     relatorio ja emitido nao troca de rodape (nem de e-mail) sozinho porque
     alguem editou o padrao depois.
  2. `configuracoes['rm.rodape']` / `configuracoes['rm.email']` — o PADRAO
     editavel pela tela. E o valor que o `POST /api/rm` carimba em (1) toda vez
     que um RM e gerado.
  3. `RM_RODAPE` / `RM_EMAIL` (backend/config.py) — a env por tenant, que segue
     valendo enquanto NINGUEM tiver salvo nada pela tela.

⚠️ A ORDEM 2-ANTES-DE-3 E O PONTO DO PEDIDO. O contrario faria o campo digitavel
nao servir para nada justamente nos tenants que hoje definem a env — que sao os
unicos que hoje imprimem alguma coisa.

⚠️ VAZIO NAO E "NAO CONFIGURADO". Linha com valor '' e uma DECISAO: o dono apagou
o campo e quer a pagina sem ele. Por isso o teste e "a linha existe?"
(`is not None`) e nunca "o texto e verdadeiro" — com o teste ingenuo, apagar o
rodape faria a env ressuscitar no proximo relatorio, e a pessoa apagaria de novo
sem entender por que volta.

⚠️ UMA IMPLEMENTACAO, DOIS CAMPOS. As funcoes recebem a CHAVE; nao ha um bloco
`rodape` e uma copia dele para `email`. O modulo nasceu so com rodape e o e-mail
entrou em 08/2026 — duplicar teria criado dois lugares para a regra do vazio, e
e exatamente esse tipo de copia que faz um dos dois ficar para tras na proxima
mudanca. As funcoes com nome antigo (`rodape_env`, `rodape_salvo`, ...) seguem
existindo como atalhos porque `routers/rm.py` e os testes as chamam pelo nome.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings

CHAVE_RODAPE = "rm.rodape"
CHAVE_EMAIL = "rm.email"

# chave da tabela `configuracoes` -> nome do atributo em Settings.
# ⚠️ E TAMBEM A ALLOWLIST: `_env_de` levanta para chave fora daqui, entao um
# `campo` vindo do corpo de um request nunca vira `getattr(settings, <qualquer
# coisa>)`. Sem isto, "campo" seria uma leitura arbitraria de configuracao.
_ENV_DA_CHAVE = {
    CHAVE_RODAPE: "RM_RODAPE",
    CHAVE_EMAIL: "RM_EMAIL",
}


def _env_de(chave: str) -> str:
    try:
        return getattr(get_settings(), _ENV_DA_CHAVE[chave]) or ""
    except KeyError:
        raise ValueError(f"chave de configuracao do RM desconhecida: {chave!r}")


async def salvo(db: AsyncSession, chave: str) -> str | None:
    """O padrao gravado pela tela, ou None quando a linha nunca foi criada.

    None e '' sao coisas DIFERENTES aqui — ver o cabecalho do modulo."""
    _env_de(chave)          # valida a chave antes de tocar no banco
    row = (await db.execute(
        text("SELECT valor FROM configuracoes WHERE chave = :c"),
        {"c": chave},
    )).first()
    return row[0] if row else None


async def padrao(db: AsyncSession, chave: str) -> str:
    """O valor que um RM NOVO recebe: o salvo (se houver linha) ou a env."""
    s = await salvo(db, chave)
    return s if s is not None else _env_de(chave)


async def gravar(db: AsyncSession, chave: str, valor: str, usuario_id) -> None:
    """UPSERT do padrao. SEM `commit` — quem chama e dono da transacao (e e ele
    que precisa da linha gravada antes de registrar a trilha)."""
    _env_de(chave)
    await db.execute(text("""
        INSERT INTO configuracoes (chave, valor, atualizado_por)
        VALUES (:c, :v, :u)
        ON CONFLICT (chave) DO UPDATE SET
            valor          = EXCLUDED.valor,
            atualizado_em  = NOW(),
            atualizado_por = EXCLUDED.atualizado_por
    """), {"c": chave, "v": valor, "u": usuario_id})


# --------------------------------------------------------------- atalhos ------
# Nomes que `routers/rm.py` e os testes ja usam. Mantidos para a mudanca do
# e-mail nao arrastar renomeacao por todo o repo.
def rodape_env() -> str:
    return _env_de(CHAVE_RODAPE)


def email_env() -> str:
    return _env_de(CHAVE_EMAIL)


async def rodape_salvo(db: AsyncSession) -> str | None:
    return await salvo(db, CHAVE_RODAPE)


async def email_salvo(db: AsyncSession) -> str | None:
    return await salvo(db, CHAVE_EMAIL)


async def rodape_padrao(db: AsyncSession) -> str:
    return await padrao(db, CHAVE_RODAPE)


async def email_padrao(db: AsyncSession) -> str:
    return await padrao(db, CHAVE_EMAIL)


async def gravar_rodape(db: AsyncSession, valor: str, usuario_id) -> None:
    await gravar(db, CHAVE_RODAPE, valor, usuario_id)


async def gravar_email(db: AsyncSession, valor: str, usuario_id) -> None:
    await gravar(db, CHAVE_EMAIL, valor, usuario_id)
