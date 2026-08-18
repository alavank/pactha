"""Relatórios de Monitoramento em formatos alternativos ao Completo:

- TOTALIZADO: grade consolidada (1 linha por instrumento) nas colunas do modelo
  MOEMA — Concedente, Parlamentar, Ano, Objeto, Proposta/Convênio, Vl. Global,
  Vl. Repasse, Vl. Contrapartida, Situação Atual. Sai em Excel (.xlsx) e PDF.

Ambos consomem o MESMO `conteudo` JSONB do RM (partes → secoes → grupos →
itens), então batem 1:1 com o Relatório Completo — muda só a apresentação.
"""
import io
import re
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

# Colunas do totalizado (rótulo, chave do item, largura PDF em cm, largura Excel)
_COLS = [
    ("CONCEDENTE", "_concedente", 2.9, 26),
    ("PARLAMENTAR", "parlamentar", 2.7, 24),
    ("ANO", "_ano", 1.0, 7),
    ("OBJETO", "objeto", 5.4, 46),
    ("PROPOSTA/\nCONVÊNIO", "numero", 3.0, 22),
    ("VL. GLOBAL", "valor_global", 2.1, 15),
    ("VL. REPASSE", "valor_repasse", 2.1, 15),
    ("VL. CONTRAP.", "valor_contrapartida", 2.0, 15),
    ("SITUAÇÃO ATUAL", "situacao_atual", 4.5, 46),
]


def _ano_de(numero: str) -> str:
    """Ano a partir do número. PEGADINHA: a regex ingênua pegava '1920' do MEIO
    de '63000784419202600 - 2026'. Prioriza o ano após separador (/ ou -) no
    FINAL; senão o ÚLTIMO ano plausível (<= atual+2)."""
    s = str(numero or "")
    m = re.search(r"[/\-]\s*((?:19|20)\d{2})\s*$", s)  # ano após separador, no fim
    if m:
        return m.group(1)
    lim = date.today().year + 2
    cands = [int(x) for x in re.findall(r"(?:19|20)\d{2}", s)]
    plaus = [y for y in cands if 2000 <= y <= lim]
    return str(plaus[-1]) if plaus else ""


def _linhas(conteudo: dict):
    """Achata o conteudo do RM em (secao_titulo, [itens]) preservando a ordem
    das partes/seções. Cada item ganha _concedente (órgão do grupo) e _ano."""
    out = []
    for parte in conteudo.get("partes", []):
        p_tit = (parte.get("titulo") or "").strip()
        itens_parte = []
        for secao in parte.get("secoes", []):
            for grupo in secao.get("grupos", []):
                orgao = (grupo.get("orgao") or "").strip()
                for it in grupo.get("itens", []):
                    row = dict(it)
                    row["_concedente"] = orgao
                    row["_ano"] = _ano_de(it.get("numero"))
                    itens_parte.append(row)
        if itens_parte:
            out.append((p_tit, itens_parte))
    return out


def _money(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return ""
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- EXCEL --------
def gerar_totalizado_xlsx(meta: dict, conteudo: dict, municipio_nome: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = "TOTALIZADO"

    azul = PatternFill("solid", fgColor="1E2A52")
    cinza = PatternFill("solid", fgColor="D9D9D9")
    branco_neg = Font(name="Arial", bold=True, color="FFFFFF", size=11)
    preto_neg = Font(name="Arial", bold=True, size=9)
    normal = Font(name="Arial", size=9)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    thin = Side(style="thin", color="999999")
    borda = Border(left=thin, right=thin, top=thin, bottom=thin)

    for i, (_, _, _, w) in enumerate(_COLS, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    ncols = len(_COLS)

    r = 1
    dref = meta.get("data_referencia")
    ref_txt = dref.strftime("%d/%m/%Y") if hasattr(dref, "strftime") else str(dref or "")
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
    cell = ws.cell(r, 1, f"{municipio_nome} — RELATÓRIO TOTALIZADO — {ref_txt}")
    cell.fill = azul; cell.font = branco_neg; cell.alignment = center
    ws.row_dimensions[r].height = 22
    r += 2

    def _cab(titulo):
        nonlocal r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        c = ws.cell(r, 1, titulo)
        c.fill = azul; c.font = branco_neg; c.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[r].height = 18
        r += 1
        for i, (rot, _, _, _) in enumerate(_COLS, start=1):
            c = ws.cell(r, i, rot)
            c.fill = cinza; c.font = preto_neg; c.alignment = center; c.border = borda
        r += 1

    for secao_tit, itens in _linhas(conteudo):
        _cab(secao_tit)
        for it in itens:
            for i, (_, key, _, _) in enumerate(_COLS, start=1):
                if key.startswith("valor"):
                    val = _money(it.get(key))
                else:
                    val = str(it.get(key) or "")
                c = ws.cell(r, i, val)
                c.font = normal
                c.alignment = center if key in ("_ano", "numero") else left
                c.border = borda
            r += 1
        r += 1  # linha em branco entre seções

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ PDF --------
def gerar_totalizado_pdf(meta: dict, conteudo: dict, municipio_nome: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=1 * cm, rightMargin=1 * cm,
                            topMargin=1 * cm, bottomMargin=1 * cm)
    cell = ParagraphStyle("tz_cell", fontName="Helvetica", fontSize=6.5, leading=8)
    head = ParagraphStyle("tz_head", fontName="Helvetica-Bold", fontSize=6.5,
                          leading=8, textColor=colors.white)
    titulo = ParagraphStyle("tz_tit", fontName="Helvetica-Bold", fontSize=12,
                            textColor=colors.HexColor("#1E2A52"), spaceAfter=8)
    sec = ParagraphStyle("tz_sec", fontName="Helvetica-Bold", fontSize=8,
                         textColor=colors.white)

    dref = meta.get("data_referencia")
    ref_txt = dref.strftime("%d/%m/%Y") if hasattr(dref, "strftime") else str(dref or "")
    story = [Paragraph(f"{municipio_nome} — Relatório Totalizado — {ref_txt}", titulo)]

    col_widths = [c * cm for _, _, c, _ in _COLS]
    header_cells = [Paragraph(rot.replace("\n", "<br/>"), head) for rot, _, _, _ in _COLS]

    for secao_tit, itens in _linhas(conteudo):
        dados = [[Paragraph(secao_tit, sec)] + [""] * (len(_COLS) - 1)]
        dados.append(header_cells)
        for it in itens:
            linha = []
            for _, key, _, _ in _COLS:
                v = _money(it.get(key)) if key.startswith("valor") else str(it.get(key) or "")
                linha.append(Paragraph(_esc(v), cell))
            dados.append(linha)
        tbl = Table(dados, colWidths=col_widths, repeatRows=2)
        tbl.setStyle(TableStyle([
            ("SPAN", (0, 0), (-1, 0)),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E2A52")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#1E2A52")),
            ("GRID", (0, 1), (-1, -1), 0.4, colors.HexColor("#9CA3AF")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 2), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 10))

    if not conteudo.get("partes"):
        story.append(Paragraph("<i>Relatório sem conteúdo. Use 'Auto-popular'.</i>", cell))
    doc.build(story)
    return buf.getvalue()


def _esc(s: str) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# -------------------------------------------------------------- RESUMIDO -------
# Pendência = demanda ativa. Critério: exclui a PARTE 3 (prestações de contas /
# pagos de anos anteriores) e itens cuja situação indique conclusão/pagamento.
# Mantém Brasília (federais) + Município (estaduais) — como no modelo Ibitiúra.
_CONCLUIDO_RE = re.compile(r"presta[çc][ãa]o de contas|conclu[íi]d|encerrad|pago|"
                           r"pagamento efetuado|finaliz", re.I)


def _e_pendencia(parte_titulo: str, item: dict) -> bool:
    """O item conta como PENDENCIA no Resumido (o PDF que lista o que falta).

    ⚠️ Classifica pela situacao CRUA da fonte (`situacao_base`), NAO pela exibida.
    `situacao_atual` passou a carregar a narrativa da ULTIMA ALTERACAO nos estaduais
    ("Em vigor · Última alteração: ENCERRADO (TERMO ADITIVO em ...)"), e essa
    narrativa fala da ALTERACAO, nao do convenio: lida como classificador, ela some
    com um convenio ATIVO cuja alteracao foi encerrada/concluida. `situacao_base` so
    existe nos estaduais; nas demais fontes o fallback e a propria `situacao_atual`
    (que la nao tem narrativa)."""
    if re.search(r"PRESTA|PAGAMENTOS DE ANOS", parte_titulo or "", re.I):
        return False
    sit = item.get("situacao_base") or item.get("situacao_atual") or ""
    if _CONCLUIDO_RE.search(sit):
        return False
    return True


def _resumido_money(v):
    txt = _money(v)
    return txt or "R$ 0,00"


def gerar_resumido_pdf(meta: dict, conteudo: dict, municipio_nome: str) -> bytes:
    """RM RESUMIDO = o COMPLETO recortado nas DEMANDAS EM BRASILIA (Parte 1).

    ⚠️ MUDANCA DE CONCEITO (pedido do dono): o resumido NAO e "o relatorio com
    menos informacao". Ele mostra exatamente o que o completo mostra — os mesmos
    campos, as mesmas caixas de destaque (clausula, licitacao, evento, alteracao,
    desembolso) — porem SO da Parte 1. Antes ele tinha layout e lista de campos
    proprios (`_campos_resumido`), entao cada campo novo do completo precisava ser
    duplicado aqui e, na pratica, ficava faltando.

    Implementacao: e um RECORTE + o renderizador do completo (`rm_pdf.gerar_pdf`),
    que ja e puro sobre o conteudo. Qualquer caixa nova do completo aparece aqui
    de graca. A Parte 1 e identificada por `ordem == 1` (carimbado pelo builder)
    com queda para o TITULO quando o conteudo e de um RM antigo."""
    from services.rm_pdf import gerar_pdf

    def _e_parte1(p: dict) -> bool:
        if p.get("ordem") == 1:
            return True
        t = (p.get("titulo") or "").casefold()
        return "parte 1" in t or "bras" in t   # "demandas em Brasília"

    partes1 = [p for p in (conteudo.get("partes") or []) if _e_parte1(p)]
    meta_rs = dict(meta or {})
    tit = (meta_rs.get("titulo") or f"RELATÓRIO DE MONITORAMENTO – {municipio_nome.upper()}")
    meta_rs["titulo"] = f"{tit} — DEMANDAS EM BRASÍLIA"
    return gerar_pdf(meta_rs, {"partes": partes1}, municipio_nome)


def _campos_resumido(it: dict):
    """Campos do item no Resumido — SEM caixas, evento ou grade de licitação."""
    out = []
    if it.get("objeto"):
        out.append(("Objeto", it["objeto"]))
    if it.get("parlamentar"):
        out.append(("Responsável pela indicação", it["parlamentar"]))
    out.append(("Valor global", _resumido_money(it.get("valor_global"))))
    out.append(("Valor de repasse", _resumido_money(it.get("valor_repasse"))))
    out.append(("Valor de contrapartida", _resumido_money(it.get("valor_contrapartida"))))
    if it.get("dt_fim_vigencia"):
        out.append(("Final da vigência", _fmt_data_curta(it["dt_fim_vigencia"])))
    for k, lbl in (("banco", "Banco"), ("agencia", "Agência"), ("conta", "Conta")):
        if it.get(k):
            out.append((lbl, it[k]))
    if it.get("saldo_bancario") is not None:
        out.append(("Saldo Bancário", _resumido_money(it["saldo_bancario"])))
    if it.get("situacao_atual"):
        out.append(("Situação atual", it["situacao_atual"]))
    return out


def _fmt_data_extenso(d) -> str:
    meses = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
             "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    if hasattr(d, "day"):
        return f"{d.day:02d} de {meses[d.month - 1]} de {d.year}"
    return str(d or "")


def _fmt_data_curta(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%d/%m/%Y")
    s = str(d or "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else s


def _rodape_resumido(canvas, doc, rodape_txt):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    if rodape_txt:
        canvas.drawCentredString(A4[0] / 2, 1.0 * cm, rodape_txt)
    canvas.drawRightString(A4[0] - 2 * cm, 1.0 * cm, str(doc.page))
    canvas.restoreState()
