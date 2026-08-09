"""Frescor de coleta por municipio (scraper_municipio_coleta) para os selos
"Atualizado em" das telas. Ponto unico da regra de honestidade: pos-#159 o
carimbo `ultima_coleta_em` acontece TAMBEM no erro (anti-starvation do
rodizio), entao so datamos quando tentativas=0 — com falhas, o timestamp seria
a hora do ultimo ERRO e a tela deve avisar em vez de mentir a hora."""
from typing import Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def frescor_coleta(db: AsyncSession, municipio_id: int,
                         fontes: Sequence[str]) -> Tuple[Optional[str], int]:
    """(coleta_em_iso | None, falhas_consecutivas) do municipio.

    `fontes` em ordem de preferencia — a primeira com linha vence. Permite
    'sigcon_emendas' com fallback 'sigcon' enquanto o carimbo por dataset ainda
    nao existe nas linhas antigas. Best-effort: tabela ausente (tenant novo)
    devolve (None, 0) e o selo simplesmente nao aparece.
    """
    for fonte in fontes:
        try:
            r = await db.execute(text(
                "SELECT ultima_coleta_em, coalesce(tentativas, 0) "
                "FROM scraper_municipio_coleta "
                "WHERE fonte = :f AND municipio_id = :m"),
                {"f": fonte, "m": municipio_id})
            row = r.first()
        except Exception:
            await db.rollback()
            return None, 0
        if row:
            falhas = int(row[1] or 0)
            em = row[0].isoformat() if (row[0] is not None and falhas == 0) else None
            return em, falhas
    return None, 0
