"""Frescor de coleta por municipio (scraper_municipio_coleta) para os selos
"Atualizado em" das telas. Ponto unico da regra de honestidade: pos-#159 o
carimbo `ultima_coleta_em` acontece TAMBEM no erro (anti-starvation do
rodizio), entao so datamos quando tentativas=0 — com falhas, o timestamp seria
a hora do ultimo ERRO e a tela deve avisar em vez de mentir a hora."""
import os
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


# ---------------------------------------------------------------------------
# ESTADO DA CREDENCIAL — porque "nenhum dado" tem TRES causas e a tela dizia uma
#
# A tela de Convenios Estaduais imprime o mesmo literal "Nenhum dado encontrado."
# quando (a) nao ha credencial do SIGCON no Cofre para aquele municipio, (b) ha
# credencial e ela foi recusada, e (c) a coleta rodou e o municipio realmente nao
# tem convenio. O cliente le sempre como (c) — e (a) e (b) sao pendencias
# ACIONAVEIS que ficavam invisiveis.
#
# ⚠️ Sem credencial o coletor NUNCA TOCA o municipio: `_marca_coleta` so escreve
# com o `municipio_id` que veio da credencial, entao nao existe linha em
# `scraper_municipio_coleta` e o `frescor_coleta` acima devolve (None, 0). O
# estado (a) e MUDO por construcao — nao ha carimbo para o selo mostrar.
#
# O padrao copiado e o do InvestSUS (`routers/investsus.py`), que ja devolve o
# estado da credencial e manda o usuario para Configuracoes -> Cofre de Senhas.
# ---------------------------------------------------------------------------

def _teto_login() -> int:
    """Quantas recusas seguidas tiram o municipio da fila do coletor.

    Mesma env e mesmo default do coletor. ⚠️ A env e do WORKER e a API pode nao
    te-la: no pior caso a tela diz "recusada" onde o coletor ja diz "fora da
    fila". Muda a PALAVRA, nunca se o aviso aparece."""
    try:
        return max(1, int(os.getenv("SIGCON_MAX_TENTATIVAS_LOGIN", "3") or 3))
    except ValueError:
        return 3


def classificar_credencial(n_credenciais: int, tentativas: int,
                           erro_de_login: bool, teto: Optional[int] = None,
                           houve_coleta: bool = True) -> str:
    """'sem_credencial' | 'recusada' | 'fora_da_fila' | 'sem_coleta' | 'ok'.

    ⚠️ SAO QUATRO ESTADOS DE PROBLEMA, e nao tres. O quarto — credencial
    cadastrada e a PRIMEIRA COLETA ainda nao rodou — era indistinguivel tanto do
    "sem credencial" quanto do "coletou e nao ha". Sem ele, quem acabou de
    cadastrar a senha ve "Nenhum dado encontrado" e conclui que a senha nao
    funcionou, quando so falta a proxima rodada do rodizio.

    ⚠️ `erro_de_login`, e nao "falhou". Timeout de rede, portal fora do ar e erro
    de parsing NAO sao culpa da senha — e o coletor ja faz essa distincao. Acusar
    a credencial por uma queda do portal manda o cliente trocar uma senha que
    esta certa, que e pior do que nao avisar nada.

    ⚠️ Funcao PURA de proposito: nao ha Postgres de teste neste repo, e a regra e
    o que precisa de teste. A consulta fica no chamador."""
    if n_credenciais <= 0:
        return "sem_credencial"
    if erro_de_login and tentativas > 0:
        return "fora_da_fila" if tentativas >= (teto or _teto_login()) else "recusada"
    if not houve_coleta:
        return "sem_coleta"
    return "ok"


# O que a tela deve dizer em cada estado. Fica aqui, junto da regra, e nao
# espalhado no frontend: a mesma frase serve tela, PDF e qualquer consumidor
# futuro, e um estado novo obriga a escrever a frase dele.
FRASE_CREDENCIAL = {
    "sem_credencial": "Sem credencial do SIGCON cadastrada para este município — "
                      "cadastre em Configurações → Cofre de Senhas.",
    "recusada": "A credencial do SIGCON foi recusada na última tentativa. "
                "Confira a senha em Configurações → Cofre de Senhas.",
    "fora_da_fila": "A credencial do SIGCON foi recusada seguidas vezes e o "
                    "município saiu da fila de coleta. Atualize a senha em "
                    "Configurações → Cofre de Senhas.",
    # ⚠️ Este NAO manda mexer em nada — e o unico dos quatro em que a acao certa
    # e esperar. Mandar conferir a senha aqui faria o cliente trocar uma
    # credencial que ainda nem foi usada.
    "sem_coleta": "Credencial cadastrada, primeira coleta ainda não rodou. "
                  "O município entra na próxima rodada.",
    "ok": "",
}
