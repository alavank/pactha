"""FERIADOS — nacionais e estaduais, CALCULADOS e não coletados.

⭐ ESTE É O ÚNICO "DADO EXTERNO" DO REPO QUE NÃO TEM COLETOR, e é de propósito. A
regra de feriado não muda sozinha: ela está em lei, e lei nova é mudança de
produto — entra aqui, com o número da lei escrito ao lado. Um scraper de feriado
teria tudo o que este repo evita (um site de terceiro no caminho, um selo de
frescor a manter, um watchdog a mais) para produzir uma tabela que cabe em cem
linhas e que qualquer erro do fornecedor transformaria em compromisso marcado no
dia em que a prefeitura está fechada.

⚠️ FERIADO E PONTO FACULTATIVO NÃO SÃO A MESMA COISA, e a diferença é a razão de
este módulo separar os dois. Carnaval, Quarta-feira de Cinzas e Corpus Christi
**não são feriados nacionais** — são pontos facultativos do calendário federal
(Portaria MGI 11.460/2025 para 2026: dez feriados e nove pontos facultativos). Já
a Sexta-feira Santa (Paixão de Cristo) É feriado. Marcar os três como feriado
seria mais útil e menos verdadeiro; a tela mostra os dois, com pesos diferentes.

⚠️ UF SÓ ENTRA AQUI COM A LEI CONFERIDA. Os agregadores de feriado da internet
erram: o primeiro consultado dava ao Espírito Santo "28/10 — Dia do Servidor
Público" como feriado estadual, quando o próprio TJES publica essa data como
PONTO FACULTATIVO e o feriado estadual capixaba é outro (Nossa Senhora da Penha,
móvel). Estado sem linha aqui mostra só os feriados nacionais — ausência é
honesta; feriado inventado manda alguém marcar visita num dia em que não há
ninguém para receber.

Mesma disciplina de `services/cadastro_estadual.py`: linha nova só com fonte.
"""
from __future__ import annotations

from datetime import date, timedelta

# ---------------------------------------------------------------------------
# A Páscoa, de onde saem todas as datas móveis
# ---------------------------------------------------------------------------


def pascoa(ano: int) -> date:
    """Domingo de Páscoa no calendário gregoriano (algoritmo de Meeus/Butcher).

    ⚠️ ARITMÉTICA PURA, SEM TABELA. Uma tabela de Páscoas ano a ano precisaria
    ser estendida à mão, e o dia em que alguém esquecesse seria o dia em que o
    Carnaval sumiria do calendário — sem erro, só sem marca."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741
    m = (a + 11 * h + 22 * l) // 451
    mes, dia = divmod(h + l - 7 * m + 114, 31)
    return date(ano, mes, dia + 1)


# ---------------------------------------------------------------------------
# Nacionais
# ---------------------------------------------------------------------------
# Os DEZ feriados nacionais. Leis 662/1949 e 10.607/2002 (os cívicos),
# 6.802/1980 (Aparecida) e 14.759/2023 (Consciência Negra, que virou nacional e
# por isso NÃO aparece mais como estadual de AL/AP/AM/MT/RJ).
NACIONAIS_FIXOS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Consciência Negra"),
    (12, 25, "Natal"),
)

# Móveis, em dias de deslocamento a partir do domingo de Páscoa.
# ⚠️ SÓ A SEXTA-FEIRA SANTA É FERIADO. As outras três são ponto facultativo no
# calendário federal — ver a nota do topo.
NACIONAIS_MOVEIS: tuple[tuple[int, str], ...] = (
    (-2, "Sexta-feira Santa"),
)
FACULTATIVOS_MOVEIS: tuple[tuple[int, str], ...] = (
    (-48, "Carnaval (segunda-feira)"),
    (-47, "Carnaval"),
    (-46, "Quarta-feira de Cinzas (até as 14h)"),
    (60, "Corpus Christi"),
)
FACULTATIVOS_FIXOS: tuple[tuple[int, int, str], ...] = (
    (10, 28, "Dia do Servidor Público"),
)


# ---------------------------------------------------------------------------
# Estaduais
# ---------------------------------------------------------------------------
# ⚠️ CADA LINHA CITA A LEI, e a citação não é enfeite: é o que permite conferir
# sem repetir a pesquisa. Só entram UFs verificadas — ver a nota do topo.
#
# `dia` é `(mes, dia)` para data fixa, ou um inteiro de deslocamento a partir da
# Páscoa para data móvel.
ESTADUAIS: dict[str, tuple[dict, ...]] = {
    # ⚠️ MG NÃO ACRESCENTA DIA NENHUM. A Data Magna mineira é 21 de abril, que já
    # é o feriado nacional de Tiradentes (Lei 10.607/2002) — a linha existe para
    # o rótulo do dia dizer as duas coisas, não para marcar um dia a mais.
    "MG": ({"dia": (4, 21), "nome": "Data Magna de Minas Gerais",
            "lei": "Constituição Estadual de MG", "coincide_nacional": True},),
    # Lei estadual 11.010/2019: a Data Magna capixaba é Nossa Senhora da Penha,
    # padroeira do estado — a segunda-feira OITO DIAS depois da Páscoa.
    # ⚠️ NÃO é 28/10: essa data é o Dia do Servidor Público, ponto facultativo.
    "ES": ({"dia": 8, "nome": "Nossa Senhora da Penha",
            "lei": "Lei estadual 11.010/2019"},),
    # Art. 346 da Lei estadual 10.460/1988 — o feriado do lançamento da pedra
    # fundamental de Goiânia vale no ESTADO inteiro, não só na capital.
    "GO": ({"dia": (10, 24), "nome": "Pedra Fundamental de Goiânia",
            "lei": "Lei estadual 10.460/1988, art. 346"},),
    "RS": ({"dia": (9, 20), "nome": "Revolução Farroupilha",
            "lei": "Lei estadual 4.850/1964"},),
    # O DF entra porque a assessoria que assina os relatórios é de Brasília
    # (`RM_CIDADE`) — mas só marca se houver município do DF na carteira.
    # 21/04 coincide com Tiradentes, como em MG.
    "DF": ({"dia": (4, 21), "nome": "Fundação de Brasília",
            "lei": "Lei orgânica do DF", "coincide_nacional": True},
           {"dia": (11, 30), "nome": "Dia do Evangélico",
            "lei": "Lei distrital 963/1995"}),
}

UFS_COM_FERIADO_ESTADUAL: frozenset[str] = frozenset(ESTADUAIS)

TIPO_NACIONAL = "nacional"
TIPO_ESTADUAL = "estadual"
TIPO_FACULTATIVO = "facultativo"


def _entrada(quando: date, nome: str, tipo: str, uf: str | None = None,
             lei: str | None = None) -> dict:
    return {"data": quando.isoformat(), "nome": nome, "tipo": tipo,
            "uf": uf, "lei": lei}


def do_ano(ano: int, ufs: set[str] | None = None) -> list[dict]:
    """Os feriados e pontos facultativos do ano, para as UFs pedidas.

    `ufs` vazio ou None = só os nacionais. A tela manda as UFs dos municípios
    que o tenant alcança, então um cliente de Nova Palma nunca vê o Dia do
    Evangélico do DF marcado na agenda dele.

    ⚠️ A MESMA DATA PODE APARECER DUAS VEZES, e é assim que tem de ser: 21 de
    abril é Tiradentes (nacional) E Data Magna de Minas. Quem desenha decide se
    junta os rótulos; quem calcula não pode escolher um dos dois e esconder o
    outro.
    """
    p = pascoa(ano)
    itens = [_entrada(date(ano, m, d), nome, TIPO_NACIONAL)
             for m, d, nome in NACIONAIS_FIXOS]
    itens += [_entrada(p + timedelta(days=off), nome, TIPO_NACIONAL)
              for off, nome in NACIONAIS_MOVEIS]
    itens += [_entrada(p + timedelta(days=off), nome, TIPO_FACULTATIVO)
              for off, nome in FACULTATIVOS_MOVEIS]
    itens += [_entrada(date(ano, m, d), nome, TIPO_FACULTATIVO)
              for m, d, nome in FACULTATIVOS_FIXOS]

    for uf in sorted({(u or "").strip().upper() for u in (ufs or set())}):
        for regra in ESTADUAIS.get(uf, ()):
            dia = regra["dia"]
            quando = (p + timedelta(days=dia) if isinstance(dia, int)
                      else date(ano, dia[0], dia[1]))
            itens.append(_entrada(quando, regra["nome"], TIPO_ESTADUAL, uf,
                                  regra.get("lei")))

    itens.sort(key=lambda x: (x["data"], x["tipo"], x["nome"]))
    return itens
