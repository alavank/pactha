"""RELATÓRIOS DO CONSOLIDADO — PR 3 da série (19/09/2026).

Três relatórios da carteira, todos quebrados por município:
  - RECURSOS POR MUNICÍPIO: estaduais, voluntárias federais e emendas federais,
    lado a lado, no período escolhido;
  - MATRIZ PARLAMENTAR × MUNICÍPIO: quem mandou quanto para cada cliente;
  - as planilhas da REGULARIDADE e do RADAR da carteira.

⚠️ RECURSOS NÃO TEM COLUNA DE TOTAL, de propósito. As fontes se sobrepõem: a
voluntária que nasceu de emenda está nas voluntárias E nas emendas federais
(`emendas_unificadas` casa as duas pelo código). Somar as colunas contaria o
mesmo dinheiro duas vezes — e o total de um cliente seria o número errado.
Medido na Freitas (2026, 19/09): 24 de 42 municípios têm voluntária nas duas
colunas, R$ 16,7 mi. `voluntarias_n` diz quantas, para a tela avisar.

O que SOMA é cada coluna na VERTICAL (a carteira inteira, pedido do dono em
19/09/2026): município é disjunto, então a soma dos estaduais da carteira é
exata. Somar ATRAVESSANDO as colunas continua proibido.

⚠️ MESMA CONTA DAS TELAS: estaduais e voluntárias saem de `services/bi.bi_kpis`
(o Painel de cada município), emendas de `_fontes_federais` + `emendas_unificadas`
(a aba Federais), a matriz de `aggregate_parlamentares` (a tela Parlamentares),
que desde este PR devolve `por_municipio` numa varredura só.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

MOEDA = '"R$" #,##0.00'


def voluntarias_nas_emendas(linhas: list[dict]) -> int:
    """Quantas propostas voluntárias da Prefeitura também estão na coluna de
    emendas — como linha própria ou casada a uma emenda da carteira."""
    n = 0
    for l in linhas:
        if not l["municipal"]:
            continue
        n += (l["origem"] == "voluntaria") + sum(
            1 for i in l["instrumentos"] if i["origem"] == "voluntaria")
    return n


async def recursos_por_municipio(db: AsyncSession, ids: list[int],
                                 anos: Optional[list[int]]) -> list[dict]:
    from routers.emendas_parlamentares import _fontes_federais
    from services.bi import bi_kpis
    from services.consolidado_painel import _municipios
    from services.emendas_unificadas import filtrar, totais, unificar_federais

    linhas = []
    for m in await _municipios(db, ids):
        mid = m["municipio_id"]
        k = await bi_kpis(db, [mid], anos)
        f = await _fontes_federais(db, mid)
        todas = unificar_federais((f["carteira"] or {}).get("items") or [], f["te"],
                                  f["parcerias"], f["indicadas"], f["voluntarias"])
        filtradas = filtrar(todas, anos=anos)
        t = totais(filtradas)
        linhas.append({
            "municipio_id": mid, "nome": m["nome"], "uf": m["uf"],
            "estaduais": {"n": k["total_convenios_estadual"], "valor": k["valor_total_estadual"]},
            "voluntarias": {"n": k["total_voluntarias"], "valor": k["valor_total_federal"]},
            # `n` conta TODAS as emendas e `valor` só o da Prefeitura — os dois
            # cartões da aba Federais ("Emendas" e "À Prefeitura"). O `fora_*` é
            # o sub do segundo cartão: sem ele, "23 · R$ 12,1 mi" esconde que uma
            # das 23 é do hospital e não está nos 12,1.
            "emendas": {"n": t["emendas"], "valor": t["valor_prefeitura"],
                        "fora_n": t["fora_prefeitura_n"],
                        "fora_valor": t["fora_prefeitura_valor"],
                        "sem_pagamento": t["parado_n"],
                        "com_execucao": t["com_execucao_n"],
                        "voluntarias_n": voluntarias_nas_emendas(filtradas),
                        "estado": (f["carteira"] or {}).get("estado")},
        })
    return linhas


async def matriz_parlamentares(db: AsyncSession, ids: list[int], anos: Optional[list[int]],
                               limite: int = 200) -> dict:
    """Parlamentares (linhas) × municípios (colunas), numa agregação só."""
    from routers.parlamentares import aggregate_parlamentares
    from services.consolidado_painel import _municipios

    muns = await _municipios(db, ids)
    agg = await aggregate_parlamentares(db, municipio_ids=ids, ano=anos, tipo="parlamentar")
    itens = sorted(agg["items"], key=lambda i: -i["valor_total"])[:limite]
    return {"municipios": [m["nome"] for m in muns],
            "parlamentares": [{"nome": i["nome_display"], "total": i["valor_total"],
                               "por_municipio": i.get("por_municipio") or {}} for i in itens],
            "truncado": len(agg["items"]) > limite, "total_parlamentares": len(agg["items"])}


# --------------------------------------------------------------- planilhas ---

def _wb(titulo: str, subtitulo: str):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.append([titulo])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append([f"{subtitulo} · gerado em {datetime.now():%d/%m/%Y %H:%M} · PACTHA"])
    ws.append([])
    return wb, ws


def _cabecalho(ws, colunas: list[str]) -> None:
    from openpyxl.styles import Font
    ws.append(colunas)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)


def _moeda(ws, colunas: list[int], desde: int) -> None:
    for col in colunas:
        for row in ws.iter_rows(min_row=desde, min_col=col, max_col=col):
            for c in row:
                c.number_format = MOEDA


def _salvar(wb) -> BytesIO:
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def xlsx_recursos(linhas: list[dict], periodo: str) -> BytesIO:
    wb, ws = _wb("Recursos por município da carteira",
                 f"{periodo} · {len(linhas)} municípios · sem coluna de total: as fontes se "
                 f"sobrepõem (voluntária que nasceu de emenda aparece nas duas)")
    ws.title = "Recursos por município"
    _cabecalho(ws, ["Município", "UF", "Convênios estaduais", "Valor estadual",
                    "Voluntárias federais (todas as fases)", "Valor voluntárias",
                    "Emendas federais", "Valor das emendas (prefeitura)",
                    "Emendas a entidades (fora do valor)",
                    "Emendas com execução no Portal", "Empenhadas sem pagamento",
                    "Voluntárias também nas emendas"])
    ini = ws.max_row + 1
    for l in linhas:
        e = l["emendas"]
        ws.append([l["nome"], l["uf"], l["estaduais"]["n"], l["estaduais"]["valor"],
                   l["voluntarias"]["n"], l["voluntarias"]["valor"], e["n"], e["valor"],
                   e.get("fora_n", 0), e.get("com_execucao", 0), e["sem_pagamento"],
                   e.get("voluntarias_n", 0)])
    fim = ws.max_row
    if linhas:
        # A soma de CADA COLUNA (a carteira inteira). Nunca uma soma entre colunas.
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter
        ws.append(["Soma da carteira", None] + [
            f"=SUM({get_column_letter(c)}{ini}:{get_column_letter(c)}{fim})"
            for c in range(3, 13)])
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
    _moeda(ws, [4, 6, 8], ini)
    for col, w in zip("ABCDEFGHIJKL", (30, 5, 12, 18, 14, 18, 12, 22, 14, 14, 14, 14)):
        ws.column_dimensions[col].width = w
    return _salvar(wb)


def xlsx_matriz(m: dict, periodo: str) -> BytesIO:
    from openpyxl.utils import get_column_letter
    wb, ws = _wb("Parlamentares × municípios da carteira",
                 f"{periodo} · {len(m['parlamentares'])} parlamentar(es)"
                 + (f" de {m['total_parlamentares']} (os de maior valor)" if m["truncado"] else ""))
    ws.title = "Matriz"
    muns = m["municipios"]
    _cabecalho(ws, ["Parlamentar", "Total na carteira"] + muns)
    ini = ws.max_row + 1
    for p in m["parlamentares"]:
        ws.append([p["nome"], p["total"]] + [p["por_municipio"].get(n) or None for n in muns])
    _moeda(ws, list(range(2, len(muns) + 3)), ini)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 18
    for i in range(3, len(muns) + 3):
        ws.column_dimensions[get_column_letter(i)].width = 16
    ws.freeze_panes = ws.cell(row=ini, column=3)
    return _salvar(wb)


def xlsx_regularidade(p: dict) -> BytesIO:
    """A regularidade da carteira: situação por município e documentos vencendo."""
    wb, ws = _wb("Regularidade da carteira", f"{p['municipios_na_carteira']} municípios")
    ws.title = "Situação"
    _cabecalho(ws, ["Município", "UF", "CAUC", "Pendências CAUC", "Estadual",
                    "Pendências estadual", "Documentos vencendo (30d)", "Próximo em (dias)"])
    for l in p["municipios"]:
        c, e = l.get("cauc"), l.get("estadual") or {}
        est = ("sem fonte no estado" if e.get("cobertura") == "sem_fonte"
               else "sem coleta" if e.get("regular") is None
               else "em dia" if e.get("regular") else "irregular")
        ws.append([l["nome"], l["uf"],
                   "sem coleta" if not c or c.get("regular") is None
                   else ("em dia" if c["regular"] else "irregular"),
                   (c or {}).get("pendencias"), est, e.get("pendencias"),
                   l["documentos"]["n"], l["documentos"]["proximo_dias"]])
    ws.column_dimensions["A"].width = 30
    wd = wb.create_sheet("Vencendo em 30 dias")
    _cabecalho(wd, ["Município", "Entidade", "Cadastro", "Documento", "Validade", "Dias"])
    for d in p["documentos"]:
        wd.append([d["municipio"], d.get("entidade"), d["esfera"], d["label"],
                   d["validade"], d["dias_restantes"]])
    wd.column_dimensions["A"].width = 30
    wd.column_dimensions["D"].width = 60
    return _salvar(wb)


def xlsx_radar(p: dict) -> BytesIO:
    """O Radar da carteira: por município e os programas com nomeação/indicação."""
    wb, ws = _wb("Radar da carteira", f"{p['municipios_na_carteira']} municípios")
    ws.title = "Por município"
    _cabecalho(ws, ["Município", "UF", "Programas abertos", "Nomeado", "Com emenda indicada",
                    "Prazo mais próximo (dias)"])
    for l in p["municipios"]:
        r = l.get("radar") or {}
        ws.append([l["nome"], l["uf"], r.get("abertos"), r.get("nomeado"), r.get("indicado"),
                   r.get("proximo_dias")])
    ws.column_dimensions["A"].width = 30
    wr = wb.create_sheet("Programas")
    _cabecalho(wr, ["Município", "Programa", "Município nomeado", "Fecha em (dias)",
                    "Emenda indicada por", "A pedido de", "Valor indicado"])
    for x in p["programas"]:
        for i in (x["indicacoes"] or [{}]):
            wr.append([x["municipio"], x["programa"], "sim" if x["beneficiario"] else "",
                       x["dias"], i.get("parlamentar"), i.get("solicitante"), i.get("valor")])
    _moeda(wr, [7], 2)
    wr.column_dimensions["A"].width = 30
    wr.column_dimensions["B"].width = 70
    return _salvar(wb)
