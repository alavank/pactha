"""Configuracao do RM que o DONO edita pela tela. Hoje: o RODAPE.

PRECEDENCIA DO RODAPE — tres camadas, da mais especifica para a mais geral:

  1. `rm_relatorios.rodape` DA LINHA — o que foi carimbado NAQUELE relatorio.
     E o que o PDF imprime (routers/rm.py -> rm_pdf._on_page), e continua sendo.
     Nada aqui muda isso: relatorio ja emitido nao troca de rodape sozinho
     porque alguem editou o padrao depois.
  2. `configuracoes['rm.rodape']` — o PADRAO editavel pela tela. E o valor que
     o `POST /api/rm` carimba em (1) toda vez que um RM e gerado.
  3. `RM_RODAPE` (backend/config.py) — a env por tenant, que segue valendo
     enquanto NINGUEM tiver salvo nada pela tela.

⚠️ A ORDEM 2-ANTES-DE-3 E O PONTO DO PEDIDO. O contrario faria o campo digitavel
nao servir para nada justamente nos tenants que hoje definem RM_RODAPE — que sao
os unicos que hoje imprimem rodape.

⚠️ VAZIO NAO E "NAO CONFIGURADO". Linha com valor '' e uma DECISAO: o dono
apagou o rodape e quer pagina sem rodape. Por isso o teste e "a linha existe?"
(`is not None`) e nunca "o texto e verdadeiro" — com o teste ingenuo, apagar o
rodape faria a env ressuscitar no proximo relatorio, e a pessoa apagaria de novo
sem entender por que volta.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings

CHAVE_RODAPE = "rm.rodape"


def rodape_env() -> str:
    return get_settings().RM_RODAPE or ""


async def rodape_salvo(db: AsyncSession) -> str | None:
    """O padrao gravado pela tela, ou None quando a linha nunca foi criada.

    None e '' sao coisas DIFERENTES aqui — ver o cabecalho do modulo."""
    row = (await db.execute(
        text("SELECT valor FROM configuracoes WHERE chave = :c"),
        {"c": CHAVE_RODAPE},
    )).first()
    return row[0] if row else None


async def rodape_padrao(db: AsyncSession) -> str:
    """O rodape que um RM NOVO recebe: o salvo (se houver linha) ou a env."""
    salvo = await rodape_salvo(db)
    return salvo if salvo is not None else rodape_env()


async def gravar_rodape(db: AsyncSession, valor: str, usuario_id) -> None:
    """UPSERT do padrao. SEM `commit` — quem chama e dono da transacao (e e ele
    que precisa da linha gravada antes de registrar a trilha)."""
    await db.execute(text("""
        INSERT INTO configuracoes (chave, valor, atualizado_por)
        VALUES (:c, :v, :u)
        ON CONFLICT (chave) DO UPDATE SET
            valor          = EXCLUDED.valor,
            atualizado_em  = NOW(),
            atualizado_por = EXCLUDED.atualizado_por
    """), {"c": CHAVE_RODAPE, "v": valor, "u": usuario_id})
