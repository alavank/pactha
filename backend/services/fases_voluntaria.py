"""EM QUE FASE está cada proposta voluntária — uma regra só (19/09/2026).

As regras de SQL abaixo moravam em `routers/transferegov.py`, que monta as quatro
telas de propostas (Voluntárias, Em execução, Rejeitadas, Encerradas). Subiram
para cá porque o PAINEL passou a usá-las: o valor de voluntárias do Painel
somava a proposta em QUALQUER fase — o pedido que ninguém aprovou, o convênio
assinado e o rejeitado, num número só. Medido na Freitas (2026, 19/09): das 162
propostas da carteira, 19 em execução e 102 ainda "enviada para análise";
Conceição do Pará aparecia com R$ 45,3 mi que eram seis pedidos de asfalto em
análise. O dono: "pra quem bate o olho, é um valor cheio, independente da fase".

AS TRÊS FASES DO PAINEL (e do Consolidado):
    celebrada .. convênio assinado: em execução, prestação de contas, encerrado.
                 É o dinheiro de fato, e é o NÚMERO PRINCIPAL.
    analise .... o pipeline antes da celebração (enviada, em complementação,
                 aprovada e ainda não assinada). Aparece AO LADO, nunca somada.
    rejeitada .. rejeitada ou eliminada. Só a contagem; valor nenhum.

⚠️ A FASE É A MESMA DAS TELAS: `analise` = `VOLUNTARIA_SQL`, `rejeitada` =
`REJEITADA_SQL`, `celebrada` = o resto (as telas Em execução e Encerradas). Se o
Painel classificasse diferente, a soma dele não fecharia com as listas.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.natureza import SQL_SO_PREFEITURA

# Status que identifica uma proposta VOLUNTARIA (FREITAS). Alem do classico
# "Proposta/Plano de Trabalho enviado para Analise", a Freitas considera tambem
# voluntarias todas as propostas/planos no PIPELINE de analise/aprovacao/
# complementacao (antes da celebracao): "Aprovados", "em Analise", "em
# Complementacao", "complementado enviada para Analise", "Proposta Aprovada e
# Plano de Trabalho ...", etc. NAO inclui: Prestacao de Contas, Rejeitadas,
# "Em execucao" (convenio ja celebrado). O acento corrompido (U+FFFD) e tratado
# com curinga (an%lise).
VOLUNTARIA_LIKE = "%enviado para an%lise%"  # mantido p/ compat
VOLUNTARIA_SQL = (
    "(situacao ILIKE '%plano de trabalho%' "
    "AND (situacao ILIKE '%an%lise%' OR situacao ILIKE '%aprovad%' OR situacao ILIKE '%complementa%') "
    "AND situacao NOT ILIKE '%presta%' AND situacao NOT ILIKE '%rejeitad%' "
    "AND situacao NOT ILIKE '%eliminad%')"
)
# REJEITADAS: "Rejeitados", "Rejeitados por Impedimento tecnico" e — desde
# 19/09/2026 — "Eliminada em Analise Preliminar". Esta ultima nao tem a palavra
# "rejeitad" nem "plano de trabalho", e caia no ELSE: aparecia na tela «Em
# execucao» como convenio vivo (medido na Freitas, 1 proposta de 2026). A regra
# do Radar (`ingestion/programas_captacao.fase_da_proposta`) ja tratava
# "eliminad" como rejeicao.
REJEITADA_SQL = "(situacao ILIKE '%rejeitad%' OR situacao ILIKE '%eliminad%')"
# ENCERRADAS: instrumento finalizado. Inclui Anulado, Rescindido e Prestacao
# de Contas finalizada (Concluida/Aprovada/Aprovada com Ressalvas).
ENCERRADA_SQL = (
    "(situacao ILIKE '%anulad%' OR situacao ILIKE '%rescind%' OR "
    "(situacao ILIKE '%presta%' AND (situacao ILIKE '%conclu%' OR situacao ILIKE '%aprovad%')))"
)
# ⭐ VIVA = o CICLO DE VIDA ATIVO: tudo que NAO foi rejeitado nem encerrado.
# E o recorte da tela «Voluntarias» desde 08/2026 (pedido do dono).
#
# O QUE MUDOU E POR QUE. Antes «Voluntarias» era so o PIPELINE DE ANALISE
# (VOLUNTARIA_SQL) e parava exatamente onde a proposta vira instrumento: no dia
# em que o convenio era celebrado ele SUMIA da tela e reaparecia noutra, chamada
# «Geral». Quem acompanha uma proposta do inicio ao fim tinha de trocar de aba no
# meio do caminho — e, pior, o filtro de situacao da tela e montado a partir das
# LINHAS CARREGADAS (frontend/src/components/TransfereGovPropostas.tsx), entao a
# opcao "Em execucao" nunca podia aparecer ali: as linhas nao chegavam.
#
# ⚠️ NAO INCLUI rejeitadas nem encerradas, de proposito. As duas sao DESFECHO,
# nao trabalho em curso, e cada uma tem aba propria — traze-las para ca faria
# «Voluntarias» duplicar duas telas inteiras e contradizer o proprio nome.
#
# ⚠️ `situacao IS NULL` ENTRA. Linha sem situacao coletada nao e desfecho — e
# ausencia de informacao, e sumir com ela seria afirmar um encerramento que
# ninguem viu. E o mesmo criterio do ramo `geral`.
VIVA_SQL = f"(situacao IS NULL OR (NOT {REJEITADA_SQL} AND NOT {ENCERRADA_SQL}))"
# EM QUAL DAS QUATRO TELAS de propostas um instrumento aparece, como expressao SQL.
# Existe para o vinculo do /pac poder LINKAR para a tela certa usando AS MESMAS
# regras que o /voluntarias usa para montar cada categoria — se divergissem, o
# link do PAC levaria a uma tela onde o convenio nao esta, que e pior que nao
# linkar. A ordem repete a do handler `voluntarias`: voluntarias -> rejeitadas ->
# encerradas -> o que sobra. `situacao` NULA cai no ELSE ('geral'), igual ao
# ramo `situacao IS NULL` de la.
# ⚠️ `situacao` sem qualificador: so pode ser usado em consulta onde
# transferegov_propostas e a unica tabela com essa coluna.
CATEGORIA_SQL = (
    "CASE "
    f"WHEN {VOLUNTARIA_SQL} THEN 'voluntarias' "
    f"WHEN {REJEITADA_SQL} THEN 'rejeitadas' "
    f"WHEN {ENCERRADA_SQL} THEN 'encerradas' "
    "ELSE 'geral' END"
)
# A FASE do Painel: a categoria das telas, com Em execução + Encerradas juntas.
# `situacao` NULA segue o ELSE, como na tela «Em execução» que a mostra.
FASE_SQL = (
    "CASE "
    f"WHEN {VOLUNTARIA_SQL} THEN 'analise' "
    f"WHEN {REJEITADA_SQL} THEN 'rejeitada' "
    "ELSE 'celebrada' END"
)
FASES = ("celebrada", "analise", "rejeitada")


def _like(s: str, padrao: str) -> bool:
    """`ILIKE` do Postgres em Python: `%` é qualquer coisa, sem diferenciar caixa."""
    return re.fullmatch(".*".join(map(re.escape, padrao.split("%"))), s,
                        re.IGNORECASE | re.DOTALL) is not None


def fase_de(situacao: Optional[str]) -> str:
    """O `FASE_SQL` para quem já tem a linha na mão (as emendas unificadas trazem a
    situação da voluntária). ⚠️ Espelho exato do SQL acima — o teste
    `test_fases_voluntaria.py` passa as situações reais pelos dois."""
    if situacao is None:
        return "celebrada"
    s = situacao
    if (_like(s, "%plano de trabalho%")
            and (_like(s, "%an%lise%") or _like(s, "%aprovad%") or _like(s, "%complementa%"))
            and not _like(s, "%presta%") and not _like(s, "%rejeitad%")
            and not _like(s, "%eliminad%")):
        return "analise"
    if _like(s, "%rejeitad%") or _like(s, "%eliminad%"):
        return "rejeitada"
    return "celebrada"


def fases_vazias() -> dict:
    return {f: {"n": 0, "valor": 0.0} for f in FASES}


async def voluntarias_por_fase(db: AsyncSession, ids: list[int],
                               anos: Optional[list[int]] = None) -> tuple[dict, list]:
    """As voluntárias da PREFEITURA em `ids`, por fase, no período.

    Devolve `(fases, vigencias)`: `fases[f] = {"n", "valor"}` e `vigencias` =
    `dt_fim_vigencia` de cada proposta NÃO rejeitada, para os alertas de prazo
    (proposta rejeitada não tem convênio que vença)."""
    params: dict = {"ids": list(ids)}
    ano_sql = ""
    if anos:
        ano_sql = " AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)"
        params["anos_txt"] = [str(a) for a in anos]
    rows = (await db.execute(text(
        f"SELECT {FASE_SQL} AS fase, dt_fim_vigencia, "
        "COALESCE(valor_global, valor_repasse, 0) "
        # So a PREFEITURA entra na conta (15/09/2026) — ver `services/natureza.py`.
        "FROM transferegov_propostas WHERE municipio_id = ANY(:ids) AND "
        + SQL_SO_PREFEITURA + ano_sql
    ), params)).fetchall()
    fases = fases_vazias()
    vigencias = []
    for fase, dtf, val in rows:
        f = fases[fase]
        f["n"] += 1
        try:
            f["valor"] += float(val or 0)
        except (TypeError, ValueError):
            pass
        if fase != "rejeitada":
            vigencias.append(dtf)
    return fases, vigencias
