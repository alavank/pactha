"""Partido, UF, cargo e foto de quem assinou a emenda — a LEITURA do cadastro.

O cadastro nasce em `ingestion/parlamentares_cadastro.py` (Câmara, Senado e
ALMG). Aqui só se responde "quem é este nome?", para as telas que mostram autor
de emenda. A regra de casamento mora em `services/nome_parlamentar.py`
(`chave_nome` e `escolhe_cadastro`); este módulo só busca os candidatos.

⚠️ UMA CONSULTA PARA A LISTA INTEIRA, e não uma por nome: a aba Federais de um
município grande tem centenas de autores, e N consultas numa abertura de tela é
o custo que o `aggregate_parlamentares` já pagou uma vez com fetch ao vivo.

⚠️ NOME QUE NÃO CASA VOLTA `None`, e a tela mostra o nome sem partido. Partido
errado ao lado de um nome é pior que partido nenhum — a tela o afirma.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.nome_parlamentar import chave_nome, e_pessoa, escolhe_cadastro

_CAMPOS = ("casa", "id_externo", "nome", "partido", "uf", "cargo", "foto_url",
           "legislaturas")


def publico(c: dict | None) -> dict | None:
    """O que sai no payload: sem `nomes_norm`, que é detalhe de casamento."""
    if not c:
        return None
    return {k: c.get(k) for k in _CAMPOS}


async def cadastros_por_nome(db: AsyncSession, nomes) -> dict[str, dict | None]:
    """`{nome como veio: cadastro ou None}` para cada nome de PESSOA.

    Colegiado (bancada, comissão, relator) e rótulo de ausência ficam de fora do
    dicionário: não são gente, não têm partido. Tabela ausente (tenant onde a
    migration não rodou) devolve tudo `None` em vez de derrubar a tela."""
    por_chave: dict[str, list[str]] = {}
    for nome in {(n or "").strip() for n in nomes or ()}:
        if not nome or not e_pessoa(nome):
            continue
        ch = chave_nome(nome)
        if ch:
            por_chave.setdefault(ch, []).append(nome)
    if not por_chave:
        return {}
    saida: dict[str, dict | None] = {n: None for ns in por_chave.values() for n in ns}
    try:
        apelidos = dict((await db.execute(text(
            "SELECT nome_norm_fonte, nome_norm_cadastro FROM parlamentares_apelidos "
            " WHERE nome_norm_fonte = ANY(:c)"), {"c": list(por_chave)})).fetchall())
        # A chave que vai ao cadastro: o apelido curado quando há, senão a própria.
        alvo = {ch: apelidos.get(ch, ch) for ch in por_chave}
        linhas = (await db.execute(text(
            "SELECT casa, id_externo, nome, partido, uf, cargo, foto_url, legislaturas,"
            "       nomes_norm "
            "  FROM parlamentares_cadastro WHERE nomes_norm && :c"),
            {"c": sorted(set(alvo.values()))})).mappings().all()
    except Exception:
        await db.rollback()
        return saida
    candidatos: dict[str, list[dict]] = {}
    for l in linhas:
        d = dict(l)
        for ch in d.get("nomes_norm") or ():
            candidatos.setdefault(ch, []).append(d)
    for ch, nomes_fonte in por_chave.items():
        escolhido = publico(escolhe_cadastro(candidatos.get(alvo[ch], [])))
        for n in nomes_fonte:
            saida[n] = escolhido
    return saida
