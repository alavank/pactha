"""O código do município NO FNDE — que em ~14% dos casos NÃO é o IBGE de 6 dígitos.

Medido em 25/09/2026 contra a lista oficial do próprio FNDE
(`/pddeinfo/pddeinfo/corp/get-municipio?sg_uf=UF`, a mesma que monta o formulário do
PDDE Info): o IBGE de 6 dígitos difere do `CO_MUNICIPIO_FNDE` em 120 de 853
municípios de MG, 118 de 497 do RS, 67 de 399 do PR, 50 de 139 do TO, 30 de 246 de
GO e 9 de 78 do ES — quase sempre município emancipado depois de 1990 (Tocos do
Moji/MG: IBGE 316905, FNDE 317850).

⚠️ E o IBGE de um pode ser o FNDE de OUTRO: Xangri-lá/RS tem IBGE 432380, que no
FNDE é BARRA DO GUARITA. Pedir pelo IBGE traria os dados do vizinho — o PDDE Info
confere o nome na planilha e recusa; o `pls/simad` só conferia o código e aceitaria.

O FNDE não publica a tabela IBGE↔FNDE; a única ponte pública é o nome DENTRO DA UF
(igualdade exata depois de normalizar acento, apóstrofo e "DE/DO/DA" — "OLHOS
D'ÁGUA" × "OLHOS DAGUA", "BARÃO DE MONTE ALTO" × "BARÃO DO MONTE ALTO"). Por isso o
código achado pelo nome não vale sozinho: o `fnde_liberacoes` exige que a lista de
entidades traga a PRÓPRIA prefeitura (raiz do CNPJ de `municipios.cnpj`), e o
`pdde_info` confere o município que a planilha diz ser dela.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

import httpx

URL_MUNICIPIOS = "https://www.fnde.gov.br/pddeinfo/pddeinfo/corp/get-municipio"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131 Safari/537.36",
      "X-Requested-With": "XMLHttpRequest"}
# Município que o FNDE ainda chama por OUTRO nome (medido em 25/09/2026, os dois
# únicos entre os 2.212 de MG/RS/PR/TO/GO/ES que o nome não resolve): IBGE -> FNDE.
APELIDOS = {
    "3165206": "316520",   # São Tomé das Letras/MG  = "SAO THOME DAS LETRAS"
    "1708254": "172250",   # Tabocão/TO              = "FORTALEZA DO TABOCAO" (nome antigo)
}
_PARTICULAS = {"DE", "DO", "DA", "DOS", "DAS"}   # "D" de "d'Água" fica: o FNDE escreve DAGUA


def chave_nome(nome) -> str:
    """Só as letras das palavras que contam: sem acento, sem apóstrofo/hífen/espaço
    e sem as partículas DE/DO/DA/DOS/DAS."""
    s = "".join(c for c in unicodedata.normalize("NFD", str(nome or "").upper())
                if unicodedata.category(c) != "Mn")
    return "".join(w for w in re.split(r"[^A-Z]+", s) if w and w not in _PARTICULAS)


def resolver(lista: dict[str, str], ibge: str, nome: str) -> tuple[Optional[str], str]:
    """(código FNDE, como foi achado: 'ibge' | 'nome') ou (None, motivo).

    `lista` = {CO_MUNICIPIO_FNDE: NO_MUNICIPIO} da UF do município."""
    i7 = re.sub(r"\D", "", str(ibge or ""))
    i6 = i7[:6]
    if APELIDOS.get(i7) in lista:
        return APELIDOS[i7], "apelido"
    alvo = chave_nome(nome)
    if i6 and i6 in lista and chave_nome(lista[i6]) == alvo:
        return i6, "ibge"
    candidatos = sorted(c for c, n in lista.items() if chave_nome(n) == alvo)
    if len(candidatos) == 1:
        return candidatos[0], "nome"
    if not candidatos:
        return None, f"{nome}: nenhum município com esse nome na lista do FNDE da UF"
    return None, f"{nome}: {len(candidatos)} municípios com esse nome na lista do FNDE"


class CodigosFNDE:
    """A lista do FNDE por UF, baixada UMA vez por rodada (MG: 853 linhas, 1 GET)."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self._por_uf: dict[str, dict[str, str]] = {}

    def lista(self, uf: str) -> dict[str, str]:
        uf = (uf or "").upper()
        if uf not in self._por_uf:
            r = self.client.get(URL_MUNICIPIOS, params={"sg_uf": uf}, headers=UA, timeout=60)
            r.raise_for_status()
            dados = r.json()
            itens = dados if isinstance(dados, list) else (dados.get("data") or [])
            lst = {str(x["CO_MUNICIPIO_FNDE"]).strip(): str(x["NO_MUNICIPIO"]).strip()
                   for x in itens if x.get("CO_MUNICIPIO_FNDE") and x.get("SG_UF", uf) == uf}
            if not lst:
                raise ValueError(f"lista de municípios do FNDE vazia para {uf}")
            self._por_uf[uf] = lst
        return self._por_uf[uf]

    def codigo(self, uf: str, ibge: str, nome: str) -> tuple[Optional[str], str]:
        return resolver(self.lista(uf), ibge, nome)
