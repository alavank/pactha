"""RELATÓRIOS DO CONSOLIDADO — PR 3 (19/09/2026).

⚠️ O QUE ESTE ARQUIVO IMPEDE:
- o valor por município da matriz divergir do total do parlamentar (os sete
  blocos do agregado somam num lugar só, `_soma`);
- a planilha de recursos ganhar uma coluna de TOTAL (as fontes se sobrepõem:
  somar contaria o mesmo dinheiro duas vezes);
- exportação sem a caixinha "Exportar" ou sem registro na trilha.

Rodar: python -m pytest backend/tests/test_consolidado_relatorios.py -q
"""
import io
import re
from collections import defaultdict
from pathlib import Path

import pytest

from routers import parlamentares as P
from services import consolidado_relatorios as R

RAIZ = Path(__file__).resolve().parent.parent
openpyxl = pytest.importorskip("openpyxl")


def _entry():
    return {"valor_total": 0.0, "municipios": set(), "por_municipio": defaultdict(float)}


def test_soma_fecha_o_total_com_o_por_municipio():
    e = _entry()
    P._soma(e, 100.0, "Araújos")
    P._soma(e, "50.5", "Bom Despacho")  # NUMERIC do banco pode chegar como texto
    P._soma(e, 25.0, "Araújos")
    P._soma(e, 10.0, None)  # sem município: conta no total, não na matriz
    assert e["valor_total"] == 185.5
    assert dict(e["por_municipio"]) == {"Araújos": 125.0, "Bom Despacho": 50.5}
    assert e["municipios"] == {"Araújos", "Bom Despacho"}


def test_os_sete_blocos_do_agregado_somam_por_soma():
    fonte = (RAIZ / "routers" / "parlamentares.py").read_text(encoding="utf-8")
    corpo = fonte[fonte.index("async def aggregate_parlamentares"):fonte.index("# Resolve nome_display")]
    assert corpo.count("_soma(entry,") == 7
    assert 'entry["valor_total"] +=' not in corpo, "soma fora do `_soma`: a matriz deixaria de fechar"


def _linha(nome, est=(1, 100.0), vol=(2, 200.0), em=(3, 300.0, 1)):
    return {"municipio_id": 1, "nome": nome, "uf": "MG",
            "estaduais": {"n": est[0], "valor": est[1]},
            "voluntarias": {"n": vol[0], "valor": vol[1]},
            "emendas": {"n": em[0], "valor": em[1], "sem_pagamento": em[2], "estado": "ok"}}


def test_planilha_de_recursos_nao_tem_total():
    wb = openpyxl.load_workbook(io.BytesIO(R.xlsx_recursos([_linha("Araújos")], "2025").getvalue()))
    ws = wb.active
    cab = [c.value for c in ws[4]]
    assert not any("total" in str(c).lower() for c in cab if c), cab
    assert [c.value for c in ws[5]][:4] == ["Araújos", "MG", 1, 100.0]
    assert "sem coluna de total" in ws["A2"].value


def test_matriz_uma_coluna_por_municipio():
    m = {"municipios": ["Araújos", "Bom Despacho"], "truncado": False, "total_parlamentares": 1,
         "parlamentares": [{"nome": "Reginaldo Lopes", "total": 1250000.0,
                            "por_municipio": {"Araújos": 1000000.0, "Bom Despacho": 250000.0}}]}
    ws = openpyxl.load_workbook(io.BytesIO(R.xlsx_matriz(m, "todos os anos").getvalue())).active
    assert [c.value for c in ws[4]] == ["Parlamentar", "Total na carteira", "Araújos", "Bom Despacho"]
    assert [c.value for c in ws[5]] == ["Reginaldo Lopes", 1250000.0, 1000000.0, 250000.0]
    assert ws.freeze_panes == "C5"


def test_planilha_do_painel_tem_uma_aba_por_bloco():
    p = {"municipios_na_carteira": 1,
         "municipios": [{"nome": "Araújos", "uf": "MG", "cauc": {"regular": False, "pendencias": 2},
                         "estadual": {"cobertura": "sem_fonte", "regular": None},
                         "vencimentos": {"n": 1, "proximo_dias": 5},
                         "documentos": {"n": 0, "proximo_dias": None},
                         "emendas": {"sem_pagamento": 1}, "radar": {"abertos": 3, "nomeado": 1, "indicado": 0}}],
         "vencimentos": [{"municipio": "Araújos", "esfera": "estadual", "numero": "1", "objeto": "x",
                          "orgao": "y", "fim": "2026-10-01", "dias": 5}],
         "documentos": [],
         "radar": [{"municipio": "Araújos", "programa": "P", "beneficiario": True, "dias": 9,
                    "indicacoes": [{"parlamentar": "Fulano", "valor": 10.0}]}]}
    wb = openpyxl.load_workbook(io.BytesIO(R.xlsx_painel(p).getvalue()))
    assert wb.sheetnames == ["Município a município", "Vencimentos (90 dias)",
                             "Documentos (30 dias)", "Radar"]
    linha = [c.value for c in wb["Município a município"][5]]
    assert linha[:5] == ["Araújos", "MG", "irregular", 2, "sem fonte no estado"]


def test_toda_exportacao_cobra_exportar_e_grava_na_trilha():
    fonte = (RAIZ / "routers" / "consolidado.py").read_text(encoding="utf-8")
    for bloco in fonte.split("@router.get(")[1:]:
        cab = bloco.split("\n")[0]
        if "exportar" in cab:
            assert 'exige("consolidado.exportar")' in cab, cab
            assert "registrar(" in bloco or "_arquivo(" in bloco, cab
    assert re.search(r"async def _arquivo.*?await registrar\(", fonte, re.S)
