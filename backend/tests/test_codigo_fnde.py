"""O código do município NO FNDE (`services/codigo_fnde.py`) — medido em 25/09/2026.

A lista abaixo é um RECORTE REAL de `/pddeinfo/pddeinfo/corp/get-municipio` (RS e
MG). O caso que dá nome ao módulo: o IBGE de Xangri-lá (432380) é, no FNDE, o
código de BARRA DO GUARITA — pedir pelo IBGE traria os dados do vizinho.
"""
import asyncio  # noqa: F401  (padrão do repo: testes síncronos)

import httpx
import pytest

from ingestion import fnde_liberacoes as fl
from services.codigo_fnde import CodigosFNDE, chave_nome, resolver

RS = {"432380": "BARRA DO GUARITA", "433350": "XANGRI-LA", "431690": "SANTA MARIA",
      "431695": "SANTA MARIA DO HERVAL", "431710": "SANTANA DO LIVRAMENTO"}
MG = {"314340": "MONTE SIAO", "317850": "TOCOS DO MOJI", "314545": "OLHOS-DAGUA",
      "310550": "BARAO DE MONTE ALTO"}


@pytest.mark.parametrize("lista,ibge,nome,esperado", [
    (MG, "3143401", "Monte Sião", ("314340", "ibge")),           # o caso comum
    (MG, "3169059", "Tocos do Moji", ("317850", "nome")),         # IBGE 316905 não existe no FNDE
    (RS, "4323804", "Xangri-lá", ("433350", "nome")),             # ⚠️ 432380 é Barra do Guarita
    (RS, "4316907", "Santa Maria", ("431690", "ibge")),           # não vira Santa Maria do Herval
    (RS, "4317103", "Sant'Ana do Livramento", ("431710", "ibge")),
    (MG, "3145455", "Olhos-d'Água", ("314545", "ibge")),
    (MG, "3105509", "Barão do Monte Alto", ("310550", "ibge")),  # DO × DE
])
def test_resolver(lista, ibge, nome, esperado):
    assert resolver(lista, ibge, nome) == esperado


def test_nome_antigo_no_fnde_vai_pelo_apelido_do_ibge():
    assert resolver({"316520": "SAO THOME DAS LETRAS"}, "3165206", "São Tomé das Letras") ==         ("316520", "apelido")
    assert resolver({"172250": "FORTALEZA DO TABOCAO"}, "1708254", "Tabocão") == ("172250", "apelido")


def test_sem_candidato_ou_ambiguo_nao_chuta():
    cod, motivo = resolver(MG, "3199999", "Município Que Não Existe")
    assert cod is None and "nenhum" in motivo
    cod, motivo = resolver({"1": "PALMAS", "2": "PALMAS"}, "1799999", "Palmas")
    assert cod is None and "2 municípios" in motivo


def test_chave_nome_ignora_acento_apostrofo_e_particulas():
    assert chave_nome("Olhos-d'Água") == chave_nome("OLHOS-DAGUA") == "OLHOSDAGUA"
    assert chave_nome("Barão do Monte Alto") == chave_nome("BARAO DE MONTE ALTO")
    assert chave_nome("Santa Maria") != chave_nome("Santa Maria do Herval")


def test_lista_baixada_uma_vez_por_uf():
    pedidos = []

    def responde(req):
        pedidos.append(dict(req.url.params))
        return httpx.Response(200, json=[{"CO_MUNICIPIO_FNDE": c, "NO_MUNICIPIO": n, "SG_UF": "RS"}
                                         for c, n in RS.items()])
    with httpx.Client(transport=httpx.MockTransport(responde)) as c:
        cod = CodigosFNDE(c)
        assert cod.codigo("RS", "4323804", "Xangri-lá") == ("433350", "nome")
        assert cod.codigo("RS", "4316907", "Santa Maria") == ("431690", "ibge")
    assert pedidos == [{"sg_uf": "RS"}]


# ------------------------------------------ fnde_liberacoes usa o código ---
class _Simad:
    fora = False
    falhas_seguidas = 0

    def __init__(self):
        self.pedidos = []

    def lista(self, ano, uf, codigo):
        self.pedidos.append(codigo)
        return "<html>Não foram encontrados dados</html>"


def test_simad_pede_pelo_codigo_fnde_e_nao_pelo_ibge():
    s = _Simad()
    fl.coleta_ano(s, {"ibge": "4323804", "uf": "RS", "codigo_fnde": "433350"}, 2026)
    assert s.pedidos == ["433350"]


def test_simad_sem_codigo_resolvido_nao_chuta_o_ibge():
    s = _Simad()
    with pytest.raises(fl.FalhaSimad, match="indisponível"):
        fl.coleta_ano(s, {"ibge": "4323804", "uf": "RS", "codigo_fnde": None,
                          "motivo_codigo": "lista de municípios do FNDE indisponível"}, 2026)
    assert s.pedidos == []


# Página REAL da entidade 52576764000123 (Secretaria de Educação de Giruá/RS), 2026:
# a lista da madrugada de 25/09 a citava; a página veio só com o cabeçalho.
CASCA = """<html><head><title>LIBERAÇÕES - CONSULTAS GERAIS</title></head><body>
<center><font>Fundo Nacional de<br>Desenvolvimento da Educação</font>
<font> :: LIBERAÇÕES - CONSULTAS GERAIS :: </font></center></body></html>"""


def test_pagina_so_com_cabecalho_e_casca_e_nao_layout_novo():
    p = fl.parse_entidade(CASCA)
    assert p["estado"] == "casca" and "FNDE listou" in p["motivo"]
    # erro do Oracle continua sendo página inválida
    assert fl.parse_entidade("<html>CONSULTAS GERAIS ORA-06502</html>")["estado"] == "invalido"
