"""CGU / convênios pela planilha (`ingestion/cgu_convenios.py`) — as armadilhas
medidas em 22/09/2026, com linhas no formato REAL da planilha de 11/09."""
import csv
import io
import zipfile

import pytest

from ingestion import cgu_convenios as c

NP = "88488358000156"          # prefeitura de Nova Palma/RS (SIAFI 8765)
SM = "88488366000100"          # prefeitura de Santa Maria/RS (SIAFI 8841)


def _linha(**k):
    base = {col: "" for col in c.COLUNAS}
    base.update({"UF": "RS", "TIPO ENTE CONVENENTE": "Municipal",
                 "TIPO CONVENENTE": "Administração Pública Municipal",
                 "SITUAÇÃO CONVÊNIO": "ADIMPLENTE", "TIPO INSTRUMENTO": "CONVENIO",
                 "VALOR CONVÊNIO": "100,00", "VALOR LIBERADO": "0,00",
                 "DATA FINAL VIGÊNCIA": "31/12/2027"})
    base.update(k)
    return base


PLANILHA = [
    # Nova Palma: a prefeitura e um hospital no mesmo código SIAFI
    _linha(**{"NÚMERO CONVÊNIO": "1ABDUP", "CÓDIGO SIAFI MUNICÍPIO": "8765",
              "CÓDIGO CONVENENTE": NP, "TIPO INSTRUMENTO": "TRANSFERENCIA LEGAL",
              "NOME ÓRGÃO CONCEDENTE": "Ministério da Integração e do Desenvolvimento Regional",
              "VALOR CONVÊNIO": "14.391.975,71", "VALOR LIBERADO": "0,00"}),
    _linha(**{"NÚMERO CONVÊNIO": "901671", "CÓDIGO SIAFI MUNICÍPIO": "8765",
              "CÓDIGO CONVENENTE": NP}),
    _linha(**{"NÚMERO CONVÊNIO": "700001", "CÓDIGO SIAFI MUNICÍPIO": "8765",
              "CÓDIGO CONVENENTE": "91026138000115",
              "TIPO CONVENENTE": "Entidades Sem Fins Lucrativos",
              "NOME CONVENENTE": "ASSOCIACAO HOSPITAL NOSSA SENHORA DA PIEDADE"}),
    # Santa Maria: 1 linha num código (8801), o resto no 8841 — com a UFSM e uma
    # pessoa física sob o mesmo código
    _linha(**{"NÚMERO CONVÊNIO": "500001", "CÓDIGO SIAFI MUNICÍPIO": "8801",
              "CÓDIGO CONVENENTE": SM}),
    _linha(**{"NÚMERO CONVÊNIO": "500002", "CÓDIGO SIAFI MUNICÍPIO": "8841",
              "CÓDIGO CONVENENTE": SM}),
    _linha(**{"NÚMERO CONVÊNIO": "500003", "CÓDIGO SIAFI MUNICÍPIO": "8841",
              "CÓDIGO CONVENENTE": SM}),
    _linha(**{"NÚMERO CONVÊNIO": "600001", "CÓDIGO SIAFI MUNICÍPIO": "8841",
              "CÓDIGO CONVENENTE": "153164", "TIPO CONVENENTE": "Agentes Intermediários",
              "NOME CONVENENTE": "UNIVERSIDADE FEDERAL DE SANTA MARIA"}),
    _linha(**{"NÚMERO CONVÊNIO": "600002", "CÓDIGO SIAFI MUNICÍPIO": "8841",
              "CÓDIGO CONVENENTE": "92040659820", "TIPO CONVENENTE": "Pessoa Física",
              "NOME CONVENENTE": "FULANO DE TAL"}),
    _linha(**{"NÚMERO CONVÊNIO": "600003", "CÓDIGO SIAFI MUNICÍPIO": "8841",
              "CÓDIGO CONVENENTE": "00814071000128", "TIPO CONVENENTE": "Administração Pública",
              "NOME CONVENENTE": "FUNDO MUNICIPAL DE SAUDE"}),
    # outro município qualquer (não entra)
    _linha(**{"NÚMERO CONVÊNIO": "104141", "UF": "SP", "CÓDIGO SIAFI MUNICÍPIO": "6689",
              "CÓDIGO CONVENENTE": "46522959000198"}),
]
ALVOS = {NP: {"id": 1, "nome": "Nova Palma", "arquivo": None, "extras": set()},
         SM: {"id": 2, "nome": "Santa Maria", "arquivo": None, "extras": set()}}


def test_codigo_siafi_sai_da_linha_da_prefeitura():
    """Armadilha 4: sem IBGE; o código é o das linhas em que a PREFEITURA assina,
    e o mais frequente vence (Santa Maria: 8841, e não o 8801 de uma linha só)."""
    cod = c.codigos_siafi(PLANILHA, ALVOS)
    assert cod == {NP: ("8765", "RS"), SM: ("8841", "RS")}


def test_selecao_por_municipio():
    linhas = c.selecionar(PLANILHA, ALVOS, c.codigos_siafi(PLANILHA, ALVOS))
    np_nums = sorted(x["NÚMERO CONVÊNIO"] for x in linhas[1])
    sm_nums = sorted(x["NÚMERO CONVÊNIO"] for x in linhas[2])
    assert np_nums == ["1ABDUP", "700001", "901671"]
    # a linha da prefeitura no OUTRO código (8801) entra; a pessoa física, não
    assert sm_nums == ["500001", "500002", "500003", "600001", "600003"]


def test_pessoa_fisica_nunca_entra():
    linhas = c.selecionar(PLANILHA, ALVOS, c.codigos_siafi(PLANILHA, ALVOS))
    assert not any(x["TIPO CONVENENTE"] == "Pessoa Física" for xs in linhas.values() for x in xs)


@pytest.mark.parametrize("doc,tipo,nome,esperado", [
    (SM, "Administração Pública Municipal", "MUNICIPIO DE SANTA MARIA", True),
    ("00814071000128", "Administração Pública", "FUNDO MUNICIPAL DE SAUDE", True),
    ("13474332000150", "Administração Pública", "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL", True),
    ("11111111000111", "Administração Pública Municipal", "CAMARA MUNICIPAL DE X", True),
    ("153164", "Agentes Intermediários", "UNIVERSIDADE FEDERAL DE SANTA MARIA", False),
    ("91026138000115", "Entidades Sem Fins Lucrativos", "ASSOCIACAO HOSPITAL", False),
    ("22222222000122", "Administração Pública", "SECRETARIA DE ESTADO DA SAUDE", False),
])
def test_e_municipal(doc, tipo, nome, esperado):
    """Armadilha 5: 'TIPO ENTE = Municipal' é ONDE FICA; quem é sai do tipo + CNPJ."""
    assert c.e_municipal(doc, tipo, nome, SM) is esperado


def test_linha_convenio_e_marca_do_transferegov():
    x = PLANILHA[0]
    sim = c.linha_convenio(x, 1, NP, "20260911", {"901671"})
    assert sim["no_transferegov"] is False           # 1ABDUP não está no TransfereGov
    assert str(sim["valor"]) == "14391975.71"
    assert sim["municipal"] is True
    assert sim["data_final_vigencia"].isoformat() == "2027-12-31"
    # sem o dump do TransfereGov: NULO ("não conferido"), nunca "não está lá"
    assert c.linha_convenio(x, 1, NP, "20260911", None)["no_transferegov"] is None
    assert c.linha_convenio(PLANILHA[1], 1, NP, "20260911", {"901671"})["no_transferegov"] is True


def test_data_do_arquivo_sai_da_pagina():
    """Armadilha 3: o arquivo NÃO é o de hoje (em 22/09 o mais novo era 11/09)."""
    html = ('<script>arquivos.push({"ano" : "2026", "mes" : "09", "dia" : "11", '
            '"origem" :  "Convenios"});</script>')
    assert c.data_do_arquivo(html) == "20260911"
    assert c.data_do_arquivo("<html>sem lista</html>") is None


def _zip(membros: dict[str, str]) -> zipfile.ZipFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, texto in membros.items():
            z.writestr(nome, texto.encode("latin-1"))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _csv(cols, linhas) -> str:
    s = io.StringIO()
    w = csv.writer(s, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(cols)
    for l in linhas:
        w.writerow([l.get(k, "") for k in cols])
    return s.getvalue()


def test_cabecalho_conferido():
    """Armadilha 8: coluna renomeada é erro com o nome, nunca 'zero instrumentos'."""
    z = _zip({"20260911_Convenios.csv": _csv(c.COLUNAS, PLANILHA[:1])})
    assert len(list(c.leitor(z, "_Convenios.csv", c.COLUNAS))) == 1
    renomeada = [col if col != "CÓDIGO CONVENENTE" else "CODIGO CONVENENTE" for col in c.COLUNAS]
    z = _zip({"20260911_Convenios.csv": _csv(renomeada, [])})
    with pytest.raises(c.CabecalhoMudou, match="CÓDIGO CONVENENTE"):
        c.leitor(z, "_Convenios.csv", c.COLUNAS)
    with pytest.raises(c.CabecalhoMudou):
        c.leitor(z, "_OrdensBancarias.csv", c.COLUNAS_OB)


def test_numeros_do_transferegov():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("siconv_convenio.csv",
                   "﻿NR_CONVENIO;ID_PROPOSTA\n901671;1\n;2\n7AAEUD;3\n".encode("utf-8"))
    buf.seek(0)
    assert c.numeros_transferegov(zipfile.ZipFile(buf)) == {"901671", "7AAEUD"}


def test_decimal_e_data_da_planilha():
    assert str(c._dec("2.054.267,71")) == "2054267.71"
    assert c._dec("") is None
    assert c._data("28/02/1999").isoformat() == "1999-02-28"
    assert c._data("") is None
