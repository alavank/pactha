"""O recebedor e a PREFEITURA? A regra unica, para as fontes que filtram por
municipio do RECEBEDOR — e recebedor nao e so a prefeitura.

⚠️ O FILTRO POR IBGE TRAZ O QUE ESTA SEDIADO NA CIDADE. Medido nos dumps de
Discricionarias e Legais em 15/09/2026:

    Goiania      75% do valor e do ESTADO DE GOIAS (1.897 propostas, R$ 8,2 bi)
    Palmas       82% e do Estado do Tocantins
    Santa Maria  33% e de entidades da sociedade civil (hospitais, abrigos)

E em Gestao de Parcerias (07/09/2026), 13,6% do valor do tenant trust era de
fundo estadual e de entidade privada.

DECISAO DO DONO (Parcerias em 07/09, Voluntarias em 15/09/2026): NADA E
DESCARTADO. A Santa Casa que recebeu emenda federal ESTA na cidade, e o gestor
quer saber. O que nao pode e entrar na conta como se fosse dinheiro da
prefeitura. Entao fica, marcado ("nao e da prefeitura"), e FORA dos totais,
alertas, painel, ranking de parlamentar e RM.

Os vocabularios sao fechados, e diferentes em cada fonte:
  Parcerias (`nm_natureza_juridica`): "Fundo Publico da Administracao Direta
    Municipal", "Municipio", "Associacao Privada", "Fundo Publico da Adm. Direta
    Estadual ou do DF", "Consorcio Publico", ...
  Discricionarias (`NATUREZA_JURIDICA` de `siconv_proposta`): "Administracao
    Publica Municipal", "Administracao Publica Estadual ou do Distrito Federal",
    "Organizacao da Sociedade Civil", "Consorcio Publico", "Empresa
    publica/Sociedade de economia mista".

⚠️ CONSORCIO PUBLICO NAO E A PREFEITURA. E um ente proprio, de varios
municipios: fica marcado, como a OSC.
"""
from __future__ import annotations

import unicodedata
from typing import Optional

# Prefixos, ja normalizados (minusculo, sem acento).
_MUNICIPAIS = (
    "fundo publico da administracao direta municipal",   # Parcerias
    "municipio",                                          # Parcerias
    "administracao publica municipal",                    # Discricionarias
)

# O filtro SQL de "so a prefeitura", para as tabelas que gravam a coluna
# `municipal` (hoje: `transferegov_propostas`). ⚠️ `IS NOT FALSE`, e nao
# `= TRUE`: NULO e "a fonte nao disse" e conta como municipal — ver
# `e_municipal`. Com `= TRUE`, toda linha anterior a coluna sumiria dos totais.
SQL_SO_PREFEITURA = "municipal IS NOT FALSE"


def _norm(texto: str) -> str:
    s = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def e_municipal(natureza: Optional[str]) -> bool:
    """A natureza juridica e da ADMINISTRACAO MUNICIPAL?

    ⚠️ AUSENCIA CONTA COMO MUNICIPAL. Se a fonte parar de mandar a natureza, a
    alternativa seria zerar os cartoes da tela em silencio — pior que uma
    proposta a mais na conta. A contagem de "nao e da prefeitura" na resposta
    deixa a mudanca visivel em vez de escondida."""
    if not natureza or not natureza.strip():
        return True
    t = _norm(natureza)
    return any(t.startswith(m) for m in _MUNICIPAIS)


def municipal_ou_nulo(natureza: Optional[str]) -> Optional[bool]:
    """O valor da coluna `municipal`: NULO quando a fonte nao disse a natureza
    (e o filtro `SQL_SO_PREFEITURA` a conta como municipal), senao a regra."""
    if not natureza or not natureza.strip():
        return None
    return e_municipal(natureza)
