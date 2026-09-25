"""Liberações do FNDE (`simec_par_liberacoes`) — QUEM recebeu e o que entra na
conta do município. A regra única: coletor, rota, IA e RM leem daqui.

Até 24/09/2026 a tabela só tinha o que o relatório do SIMEC mostra: o CNPJ da
PREFEITURA, no ano corrente. O coletor `ingestion/fnde_liberacoes.py` passou a ler
a consulta de liberações do FNDE (`pls/simad`), que lista TODA entidade do
município — e com isso chegam favorecidos que não são a prefeitura:

- a SECRETARIA de educação com CNPJ próprio (Monte Sião passou a receber o
  salário-educação nela a partir de 03/2026: R$ 1.168.706,81 até 09/2026 que o
  SIMEC não mostrava);
- as CAIXAS ESCOLARES / APM / CPM (o PDDE de cada escola) — ⚠️ podem ser de
  escola ESTADUAL (Nova Palma: "CIRCULO DE PAIS E MESTRES DA EE ..."), então
  ficam FORA do total do município, sempre visíveis à parte.

A CLASSIFICAÇÃO É A MESMA DAS TRANSFERÊNCIAS DA CGU (`services/transferencias_pasta.py`)
— "o mesmo dado dá a mesma conta em toda tela": o PDDE de uma caixa escolar é
`escola` lá e aqui, e o salário-educação da secretaria é `secretaria` lá e aqui.
O simad não publica a natureza jurídica do favorecido; a pergunta é feita como a
CGU faz com as linhas "Sem Informação" pagas pelo FNDE: o NOME decide o tipo
(fundo, escola, secretaria), o CNPJ decide a prefeitura. O vínculo com o
MUNICÍPIO nunca é por nome — a lista de entidades vem do simad pelo IBGE.

DECISÃO (24/09/2026): prefeitura + fundo + secretaria + órgão municipal ENTRAM no
total. O salário-educação (QUOTA municipal) é receita do município — a lei manda a
cota ao município, e a Secretaria é órgão dele; antes a tela somava só jan+fev de
Monte Sião porque o SIMEC não enxergava a Secretaria, e o total estava ERRADO.
Escola, entidade e outro ente ficam fora do total, sempre mostrados à parte.
"""
from __future__ import annotations

import re

from services.transferencias_pasta import DO_MUNICIPIO, ORGAO_FNDE, grupo_favorecido

# (chave, rótulo) — as MESMAS chaves de `transferencias_pasta.GRUPOS`.
TIPOS: tuple[tuple[str, str], ...] = (
    ("prefeitura", "Prefeitura"),
    ("secretaria", "Secretaria municipal"),
    ("fundo", "Fundo municipal"),
    ("orgao_municipal", "Outro órgão municipal"),
    ("escola", "Caixa escolar / APM / CPM"),
    ("entidade", "Entidade"),
    ("outro_ente", "Outro ente"),
)
ROTULO_TIPO = dict(TIPOS)

# Os tipos que SOMAM no total do município. Tuple ordenada para o SQL sair estável.
TIPOS_DO_MUNICIPIO: tuple[str, ...] = tuple(sorted(DO_MUNICIPIO))

# ⚠️ O filtro que TODO leitor que soma `simec_par_liberacoes` usa. Linha antiga
# (do SIMEC, antes da coluna existir) nasce `tipo_favorecido = 'prefeitura'` pelo
# DEFAULT da migration — exatamente o que ela era —, então a soma de antes não muda.
# `tests/test_fnde_liberacoes.py` falha se um leitor novo esquecer o filtro.
SQL_DO_MUNICIPIO = "tipo_favorecido IN (" + ", ".join(f"'{t}'" for t in TIPOS_DO_MUNICIPIO) + ")"

# A prefeitura com OUTRO CNPJ (ou tenant sem `municipios.cnpj` preenchido): o
# nome que o FNDE dá a ela é "PREF MUN DE X" / "PREFEITURA MUNICIPAL DE X" /
# "MUNICIPIO DE X". Só vale no início do nome — "CAIXA ESCOLAR ... MUNICIPIO"
# não é prefeitura (e a escola é perguntada antes, de qualquer forma).
_RX_PREFEITURA = re.compile(r"^\s*(PREF\b|PREFEITURA\b|MUNICIPIO DE\b|MUNIC\. DE\b|MUN DE\b)")


def _so_digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def tipo_favorecido(cnpj: str | None, nome: str | None, cnpj_prefeitura: str | None) -> str:
    """O tipo de UMA entidade da lista do simad, numa das chaves de `TIPOS`."""
    cnpj = _so_digitos(cnpj)
    pref = _so_digitos(cnpj_prefeitura)
    if pref and cnpj == pref:
        return "prefeitura"
    # "Sem Informação" + FNDE: é como a CGU publica as linhas sem natureza jurídica,
    # e é exatamente o que o simad dá — só o nome.
    g = grupo_favorecido(cnpj, nome, "Sem Informação", ORGAO_FNDE, pref or None)
    if g in ("orgao_municipal", "entidade", "outro_ente") and _RX_PREFEITURA.search((nome or "").upper()):
        # "PREF MUN DE MONTE SIAO" sem o CNPJ cadastrado: é a prefeitura.
        return "prefeitura"
    return g


def do_municipio(tipo: str | None) -> bool:
    """Entra no total do município? Linha sem tipo é linha antiga = prefeitura."""
    return (tipo or "prefeitura") in DO_MUNICIPIO
