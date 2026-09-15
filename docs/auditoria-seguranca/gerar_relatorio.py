# -*- coding: utf-8 -*-
"""Gera o Relatório de Auditoria de Segurança — PACTHA em PDF a partir de dados/achados.json.

Uso (dentro do venv isolado docs/auditoria-seguranca/.venv):
    .venv/Scripts/python gerar_relatorio.py            # gera relatorio-auditoria-seguranca.pdf
    .venv/Scripts/python gerar_relatorio.py --rasterizar  # também salva PNG de cada página em dados/paginas/

O arquivo de dados NÃO contém valores de segredo — só máscaras e fingerprints sha256 truncados.
Dependências: reportlab, matplotlib (e pymupdf para --rasterizar).
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)
from xml.sax.saxutils import escape as _xml_escape

HERE = Path(__file__).parent
DADOS = HERE / "dados" / "achados.json"
GRAF = HERE / "dados" / "graficos"
PDF = HERE / "relatorio-auditoria-seguranca.pdf"
TITULO = "Relatório de Auditoria de Segurança — PACTHA"

# Paleta prescrita pelo escopo da auditoria (status: sempre acompanhada de rótulo textual)
COR = {"critica": "#B91C1C", "alta": "#EA580C", "media": "#D97706", "baixa": "#2563EB", "informativa": "#6B7280", "forte": "#059669"}
ROTULO = {"critica": "Crítica", "alta": "Alta", "media": "Média", "baixa": "Baixa", "informativa": "Informativa"}
ORDEM_SEV = ["critica", "alta", "media", "baixa", "informativa"]
CATEGORIAS = [
    ("1", "1 — Banco sem tranca (isolamento entre clientes e usuários)"),
    ("2", "2 — Permissão definida no navegador"),
    ("3", "3 — IDOR"),
    ("4", "4 — Chaves expostas e defaults"),
    ("5", "5 — Inputs sem tratamento (XSS / templates)"),
    ("6", "6 — Injeção no backend Python"),
    ("inst", "Instâncias implantadas (Coolify)"),
]
CAT_CURTA = {"1": "1 Banco", "2": "2 Permissão", "3": "3 IDOR", "4": "4 Chaves", "5": "5 XSS", "6": "6 Injeção", "inst": "Instâncias"}
CINZA = colors.HexColor("#374151"); CINZA_CLARO = colors.HexColor("#F3F4F6"); LINHA = colors.HexColor("#D1D5DB"); AZUL_ESC = colors.HexColor("#111827")


def cat_grupo(c: str) -> str:
    return "inst" if c == "inst" else c[0]


# ------------------------------------------------------------------ fontes (DejaVu do matplotlib: Unicode completo)
def registrar_fontes():
    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont("DV", str(base / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DV-B", str(base / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DV-I", str(base / "DejaVuSans-Oblique.ttf")))
    pdfmetrics.registerFont(TTFont("DV-M", str(base / "DejaVuSansMono.ttf")))
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")
    for f in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
        font_manager.fontManager.addfont(str(base / f))
    plt.rcParams["font.family"] = "DejaVu Sans"


registrar_fontes()
S = {
    "titulo": ParagraphStyle("titulo", fontName="DV-B", fontSize=24, leading=30, textColor=AZUL_ESC, spaceAfter=10),
    "capa_sub": ParagraphStyle("capa_sub", fontName="DV", fontSize=12, leading=17, textColor=CINZA),
    "h1": ParagraphStyle("h1", fontName="DV-B", fontSize=16, leading=20, textColor=AZUL_ESC, spaceBefore=14, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="DV-B", fontSize=12.5, leading=16, textColor=AZUL_ESC, spaceBefore=10, spaceAfter=5),
    "h3": ParagraphStyle("h3", fontName="DV-B", fontSize=10.5, leading=14, textColor=CINZA, spaceBefore=6, spaceAfter=3),
    "corpo": ParagraphStyle("corpo", fontName="DV", fontSize=9.2, leading=13, textColor=CINZA, spaceAfter=4),
    "peq": ParagraphStyle("peq", fontName="DV", fontSize=7.6, leading=10, textColor=CINZA),
    "peq_b": ParagraphStyle("peq_b", fontName="DV-B", fontSize=7.6, leading=10, textColor=CINZA),
    "cel": ParagraphStyle("cel", fontName="DV", fontSize=7.4, leading=9.6, textColor=CINZA),
    "cel_b": ParagraphStyle("cel_b", fontName="DV-B", fontSize=7.4, leading=9.6, textColor=AZUL_ESC),
    "cel_mono": ParagraphStyle("cel_mono", fontName="DV-M", fontSize=6.6, leading=8.6, textColor=CINZA),
    "chip": ParagraphStyle("chip", fontName="DV-B", fontSize=6.4, leading=8.5, textColor=colors.white, alignment=TA_CENTER),
    "mono": ParagraphStyle("mono", fontName="DV-M", fontSize=7.2, leading=9.6, textColor=AZUL_ESC, backColor=CINZA_CLARO, borderPadding=(4, 6, 4, 6), leftIndent=0, spaceBefore=4, spaceAfter=8),
    "bullet": ParagraphStyle("bullet", fontName="DV", fontSize=9, leading=12.5, textColor=CINZA, leftIndent=12, bulletIndent=2, spaceAfter=2),
    "th": ParagraphStyle("th", fontName="DV-B", fontSize=7.6, leading=10, textColor=colors.white),
    "capa_meta": ParagraphStyle("capa_meta", fontName="DV", fontSize=9.5, leading=14, textColor=CINZA),
}


def esc(t) -> str:
    return _xml_escape(str(t if t is not None else ""))


def P(texto, estilo="corpo"):
    return Paragraph(esc(texto), S[estilo])


def P_rich(texto_xml, estilo="corpo"):
    return Paragraph(texto_xml, S[estilo])


def chip(sev: str):
    """Chip colorido de severidade (tabela de 1 célula com fundo; o rótulo textual garante leitura sem cor)."""
    t = Table([[Paragraph(ROTULO.get(sev, sev).upper(), S["chip"])]], colWidths=[2.25 * cm], rowHeights=[0.42 * cm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COR.get(sev, "#6B7280"))),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return t


def celula_status(cel: dict):
    """Célula da matriz por instância: verde/vermelho/âmbar com texto."""
    st = (cel or {}).get("status", "ok")
    fundo = {"ok": "#D1FAE5", "falha": "#FEE2E2", "atencao": "#FEF3C7", "na": "#F3F4F6"}[st]
    marca = {"ok": "✓ ", "falha": "✗ ", "atencao": "! ", "na": ""}[st]
    p = Paragraph(esc(marca + (cel or {}).get("texto", "")), S["cel"])
    return p, colors.HexColor(fundo)


def tabela(dados, larguras, cabecalho=True, zebra=True, extra=None):
    t = Table(dados, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    estilo = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.4, LINHA),
              ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if cabecalho:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), AZUL_ESC)]
    if zebra:
        for i in range(1 if cabecalho else 0, len(dados)):
            if i % 2 == 0:
                estilo.append(("BACKGROUND", (0, i), (-1, i), CINZA_CLARO))
    if extra:
        estilo += extra
    t.setStyle(TableStyle(estilo))
    return t


# ------------------------------------------------------------------ gráficos (matplotlib)
def graficos(d):
    GRAF.mkdir(parents=True, exist_ok=True)
    ach = d["achados"]
    cont = {s: sum(1 for a in ach if a["severidade"] == s) for s in ORDEM_SEV}
    # rosca por severidade — rótulo textual + contagem em cada fatia (cor nunca é o único código)
    fig, ax = plt.subplots(figsize=(4.6, 3.6), dpi=200)
    vals = [cont[s] for s in ORDEM_SEV if cont[s] > 0]
    labs = [f"{ROTULO[s]} ({cont[s]})" for s in ORDEM_SEV if cont[s] > 0]
    cors = [COR[s] for s in ORDEM_SEV if cont[s] > 0]
    if sum(vals) == 0:
        vals, labs, cors = [1], ["Nenhum achado"], ["#E5E7EB"]
    wedges, _ = ax.pie(vals, colors=cors, startangle=90, counterclock=False,
                       wedgeprops=dict(width=0.38, edgecolor="white", linewidth=2))
    ax.text(0, 0.06, str(len(ach)), ha="center", va="center", fontsize=22, fontweight="bold", color="#111827")
    ax.text(0, -0.2, "achados", ha="center", va="center", fontsize=9, color="#6B7280")
    ax.legend(wedges, labs, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=8)
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(GRAF / "rosca_severidade.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)

    # barras empilhadas por categoria (uma cor por severidade; rótulo do total no topo; legenda sempre presente)
    grupos = [g for g, _ in CATEGORIAS]
    fig, ax = plt.subplots(figsize=(6.4, 3.4), dpi=200)
    base = [0] * len(grupos)
    for s in ORDEM_SEV:
        v = [sum(1 for a in ach if a["severidade"] == s and cat_grupo(a["categoria"]) == g) for g in grupos]
        ax.bar([CAT_CURTA[g] for g in grupos], v, bottom=base, color=COR[s], label=ROTULO[s], width=0.62, edgecolor="white", linewidth=1.2)
        base = [b + x for b, x in zip(base, v)]
    for i, tot in enumerate(base):
        if tot:
            ax.text(i, tot + 0.15, str(tot), ha="center", va="bottom", fontsize=8, color="#374151")
    ax.set_ylabel("achados", fontsize=8, color="#6B7280")
    ax.tick_params(axis="x", labelsize=7.5, colors="#374151")
    ax.tick_params(axis="y", labelsize=7.5, colors="#6B7280")
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#D1D5DB")
    ax.yaxis.grid(True, color="#E5E7EB", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_ylim(0, max(base + [1]) * 1.18)
    from matplotlib.ticker import MaxNLocator
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.legend(frameon=False, fontsize=7.5, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.14))
    fig.tight_layout()
    fig.savefig(GRAF / "barras_categoria.png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return cont


# ------------------------------------------------------------------ cabeçalho / rodapé
def _cabecalho_rodape(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFont("DV", 7.5)
    canvas.setFillColor(colors.HexColor("#6B7280"))
    canvas.drawString(2 * cm, h - 1.3 * cm, TITULO)
    canvas.drawRightString(w - 2 * cm, h - 1.3 * cm, doc.meta_data)
    canvas.setStrokeColor(LINHA)
    canvas.line(2 * cm, h - 1.5 * cm, w - 2 * cm, h - 1.5 * cm)
    canvas.line(2 * cm, 1.5 * cm, w - 2 * cm, 1.5 * cm)
    canvas.drawString(2 * cm, 1.1 * cm, "Alavank · uso interno — segredos mascarados (fingerprint sha256 truncado)")
    canvas.drawRightString(w - 2 * cm, 1.1 * cm, f"Página {doc.page}")
    canvas.restoreState()


def _capa(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(AZUL_ESC)
    canvas.rect(0, h - 5.2 * cm, w, 5.2 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("DV-B", 11)
    canvas.drawString(2 * cm, h - 3.1 * cm, "PACTHA · Alavank")
    canvas.setFont("DV", 8.5)
    canvas.drawString(2 * cm, h - 3.8 * cm, "Auditoria estática de código + configuração das instâncias (Coolify, somente leitura)")
    canvas.restoreState()


# ------------------------------------------------------------------ montagem
def montar(d):
    meta = d["meta"]
    cont = graficos(d)
    ach = d["achados"]
    doc = BaseDocTemplate(str(PDF), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                          title=TITULO, author="Alavank — auditoria de segurança", subject=f"commit {meta['commit'][:12]}")
    doc.meta_data = f"{meta['data']} · commit {meta['commit'][:12]}"
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="capa", frames=[frame], onPage=_capa),
                          PageTemplate(id="normal", frames=[frame], onPage=_cabecalho_rodape)])
    L = []
    W = doc.width

    # ---- a) capa
    L += [Spacer(1, 4.6 * cm), Paragraph(esc(TITULO), S["titulo"]),
          Paragraph(esc(f"Data: {meta['data']}"), S["capa_sub"]),
          Paragraph(esc(f"Commit auditado: {meta['commit']} (branch {meta['branch']})"), S["capa_sub"]), Spacer(1, 0.5 * cm),
          Paragraph("Escopo auditado", S["h2"]),
          P_rich(f"<b>Pastas:</b> {esc(', '.join(meta['escopo_pastas']))}", "capa_meta"),
          P_rich(f"<b>Ignoradas (exceto na busca por segredos):</b> {esc(', '.join(meta['ignoradas']))}", "capa_meta"),
          P_rich(f"<b>Instâncias / environments no Coolify (projeto <i>pactha</i>):</b> {esc(', '.join(meta['instancias']))}", "capa_meta"),
          P_rich(f"<b>Coolify:</b> {esc(meta['coolify'])}", "capa_meta"), Spacer(1, 0.4 * cm),
          Paragraph("Nota metodológica", S["h2"])]
    for par in meta["nota_metodologica"]:
        L.append(P(par, "capa_meta"))
    L += [Spacer(1, 0.3 * cm), P_rich("<b>Ferramentas:</b> " + esc(meta["ferramentas"]), "capa_meta"),
          P_rich("<b>Fora do escopo desta rodada:</b> " + esc(meta["fora_de_escopo"]), "capa_meta")]
    from reportlab.platypus import NextPageTemplate
    L += [NextPageTemplate("normal"), PageBreak()]

    # ---- b) resumo executivo
    L.append(Paragraph("1. Resumo executivo", S["h1"]))
    for par in d["resumo_executivo"]:
        L.append(P(par))
    cab = [Paragraph("Severidade", S["th"]), Paragraph("Achados", S["th"]), Paragraph("Leitura", S["th"])]
    linhas = [cab]
    leitura = {"critica": "corrigir antes de qualquer outra coisa; atravessa silos ou expõe dado sem login",
               "alta": "explorável por usuário autenticado do mesmo silo ou segredo real exposto",
               "media": "depende de configuração/pré-condição; hardening prioritário",
               "baixa": "hardening e resíduos sem impacto demonstrado",
               "informativa": "decisão de design a validar, drift e itens de verificação manual"}
    for s in ORDEM_SEV:
        linhas.append([chip(s), Paragraph(str(cont[s]), S["cel_b"]), Paragraph(esc(leitura[s]), S["cel"])])
    linhas.append([Paragraph("Pontos fortes verificados", S["cel_b"]), Paragraph(str(len(d["pontos_fortes"])), S["cel_b"]),
                   Paragraph("controles confirmados com evidência (seção 2)", S["cel"])])
    L.append(tabela(linhas, [2.7 * cm, 1.8 * cm, W - 4.5 * cm]))
    L.append(Spacer(1, 0.3 * cm))
    img1 = Image(str(GRAF / "rosca_severidade.png"), width=7.6 * cm, height=5.6 * cm, kind="proportional")
    img2 = Image(str(GRAF / "barras_categoria.png"), width=9.4 * cm, height=5.0 * cm, kind="proportional")
    L.append(Table([[img1, img2]], colWidths=[7.8 * cm, W - 7.8 * cm], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])))
    L.append(P("Figura 1 — achados por severidade (rosca) e por categoria, empilhados por severidade (barras). Cada fatia/segmento traz o rótulo e a contagem; a cor é reforço, não o único código.", "peq"))

    # ---- c) pontos fortes e fracos
    L.append(Paragraph("2. Pontos fortes (o que está protegido, com evidência)", S["h1"]))
    linhas = [[Paragraph("Área", S["th"]), Paragraph("Controle verificado", S["th"]), Paragraph("Evidência", S["th"])]]
    for pf in d["pontos_fortes"]:
        linhas.append([Paragraph(esc(pf["categoria"]), S["cel_b"]), Paragraph(esc(pf["descricao"]), S["cel"]), Paragraph(esc(pf["evidencia"]), S["cel_mono"])])
    L.append(tabela(linhas, [2.4 * cm, 8.2 * cm, W - 10.6 * cm], extra=[("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#ECFDF5"))]))
    L.append(Paragraph("3. Pontos fracos (os riscos centrais)", S["h1"]))
    for pfr in d["pontos_fracos"]:
        L.append(Paragraph(esc(pfr), S["bullet"], bulletText="•"))

    # ---- d) achados detalhados por categoria
    L.append(PageBreak())
    L.append(Paragraph("4. Achados detalhados por categoria", S["h1"]))
    L.append(P("Severidade | Arquivo:linha (ou instância:resource:variável) | Descrição. Segredos aparecem mascarados (prefixo…sufixo, tamanho, sha256 truncado). Condições de explorabilidade e instâncias afetadas constam em cada linha; a íntegra (trecho, recomendação, critérios de aceite) está nas issues da seção 8."))
    for g, nome in CATEGORIAS:
        itens = [a for a in ach if cat_grupo(a["categoria"]) == g]
        itens.sort(key=lambda a: ORDEM_SEV.index(a["severidade"]))
        L.append(Paragraph(esc(nome), S["h2"]))
        if not itens:
            texto = d.get("categorias_sem_achado", {}).get(g, "Nenhum achado nesta categoria.")
            L.append(P(texto))
            continue
        linhas = [[Paragraph("Sev.", S["th"]), Paragraph("ID", S["th"]), Paragraph("Arquivo:linha / instância:resource:variável", S["th"]), Paragraph("Descrição", S["th"])]]
        for a in itens:
            desc = f"<b>{esc(a['titulo'])}</b><br/>{esc(a['descricao'])}"
            if a.get("condicoes"):
                desc += f"<br/><i>Condições:</i> {esc(a['condicoes'])}"
            desc += f"<br/><i>Instâncias afetadas:</i> {esc(a['instancias_afetadas'])}"
            if a.get("issue"):
                desc += f" · <i>Issue {esc(a['issue'])}</i>"
            linhas.append([chip(a["severidade"]), Paragraph(esc(a["id"]), S["cel_b"]), Paragraph(esc(a["local"]), S["cel_mono"]), Paragraph(desc, S["cel"])])
        L.append(tabela(linhas, [2.55 * cm, 1.1 * cm, 4.2 * cm, W - 7.85 * cm]))

    # ---- matriz por instância
    L.append(PageBreak())
    L.append(Paragraph("5. Matriz por instância (seção 2 — clientes no Coolify)", S["h1"]))
    for par in d["matriz_instancias"]["nota"]:
        L.append(P(par))
    cols = ["cliente", "resources", "banco_proprio", "segredos_unicos", "db_exposta", "dominio_tls", "cors_cookie", "commit"]
    titulos = ["Cliente", "Resources", "Banco próprio", "Segredos únicos", "DB exposta", "Domínio + TLS", "CORS / cookie", "Commit"]
    linhas = [[Paragraph(t, S["th"]) for t in titulos]]
    estilo_extra = []
    for r_i, linha in enumerate(d["matriz_instancias"]["linhas"], start=1):
        cels = [Paragraph(esc(linha["cliente"]), S["cel_b"])]
        for c_i, c in enumerate(cols[1:], start=1):
            p, fundo = celula_status(linha[c])
            cels.append(p)
            estilo_extra.append(("BACKGROUND", (c_i, r_i), (c_i, r_i), fundo))
        linhas.append(cels)
    larg = [1.8 * cm, 2.3 * cm, 2.1 * cm, 2.4 * cm, 1.7 * cm, 2.2 * cm, 2.1 * cm, W - 14.6 * cm]
    L.append(tabela(linhas, larg, zebra=False, extra=estilo_extra))
    L.append(P("Legenda: ✓ verde = conforme · ✗ vermelho = não conforme (há achado) · ! âmbar = atenção/parcial. Detalhes na categoria “Instâncias” da seção 4.", "peq"))
    if d["matriz_instancias"].get("observacoes"):
        L.append(Paragraph("Observações por instância", S["h3"]))
        for o in d["matriz_instancias"]["observacoes"]:
            L.append(Paragraph(esc(o), S["bullet"], bulletText="•"))

    # ---- e) recomendações priorizadas
    L.append(Paragraph("6. Recomendações priorizadas", S["h1"]))
    L.append(P("“Código” = a correção vale para todos os silos no próximo deploy (um merge na main deploya os quatro clientes). “Instância” = ajuste feito no Coolify, resource a resource (rotação de segredo, env, porta, backup)."))
    linhas = [[Paragraph("Prior.", S["th"]), Paragraph("Recomendação", S["th"]), Paragraph("Onde", S["th"]), Paragraph("Instâncias", S["th"]), Paragraph("Achados", S["th"])]]
    for r in d["recomendacoes"]:
        linhas.append([Paragraph(esc(r["prioridade"]), S["cel_b"]), Paragraph(f"<b>{esc(r['titulo'])}</b><br/>{esc(r['detalhe'])}", S["cel"]),
                       Paragraph(esc(r["tipo"]), S["cel"]), Paragraph(esc(r["instancias"]), S["cel"]), Paragraph(esc(", ".join(r["achados"])), S["cel_mono"])])
    L.append(tabela(linhas, [1.2 * cm, 8.6 * cm, 1.8 * cm, 2.9 * cm, W - 14.5 * cm]))

    # ---- cobertura
    L.append(Paragraph("7. Cobertura da auditoria (o que foi verificado)", S["h1"]))
    for par in d["cobertura"]["texto"]:
        L.append(P(par))
    if d["cobertura"].get("routers"):
        L.append(Paragraph("Routers do backend — handlers avaliados um a um", S["h3"]))
        linhas = [[Paragraph("Router", S["th"]), Paragraph("Handlers", S["th"]), Paragraph("Situação", S["th"])]]
        for r in d["cobertura"]["routers"]:
            linhas.append([Paragraph(esc(r["arquivo"]), S["cel_mono"]), Paragraph(str(r["handlers"]), S["cel"]), Paragraph(esc(r["situacao"]), S["cel"])])
        L.append(tabela(linhas, [4.6 * cm, 2.0 * cm, W - 6.6 * cm]))
    if d["cobertura"].get("verificacoes_corretas"):
        L.append(Paragraph("Verificado e correto (lista completa)", S["h3"]))
        for v in d["cobertura"]["verificacoes_corretas"]:
            L.append(Paragraph(esc(v), S["bullet"], bulletText="•"))
    if d["cobertura"].get("nao_verificado"):
        L.append(Paragraph("Ficou sem verificar / limitações", S["h3"]))
        for v in d["cobertura"]["nao_verificado"]:
            L.append(Paragraph(esc(v), S["bullet"], bulletText="•"))

    # ---- f) issues para o GitHub
    L.append(PageBreak())
    L.append(Paragraph("8. ISSUES PARA O GITHUB", S["h1"]))
    L.append(P("Texto completo de cada issue em Markdown, pronto para copiar e colar (não foram criadas issues — só o texto). Achados triviais do mesmo tema estão agrupados numa issue única."))
    for iss in d["issues"]:
        bloco = [Paragraph(esc(f"--- ISSUE {iss['n']} ---"), S["h3"])]
        md = iss["markdown"]
        html = esc(md).replace("\n", "<br/>")
        # preserva indentação de listas/código
        html = html.replace("<br/>  ", "<br/>&nbsp;&nbsp;").replace("<br/>    ", "<br/>&nbsp;&nbsp;&nbsp;&nbsp;")
        bloco.append(Paragraph(html, S["mono"]))
        bloco.append(Paragraph(esc(f"--- FIM ISSUE {iss['n']} ---"), S["h3"]))
        L.append(KeepTogether(bloco[:1]))
        L += bloco[1:]
    doc.build(L)


def rasterizar():
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    out = HERE / "dados" / "paginas"
    out.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open(str(PDF))
    for i, pg in enumerate(pdf, start=1):
        pg.get_pixmap(dpi=80).save(str(out / f"pagina-{i:02d}.png"))
    print(f"{len(pdf)} páginas rasterizadas em {out}")


if __name__ == "__main__":
    d = json.load(open(DADOS, encoding="utf-8"))
    montar(d)
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    n = len(fitz.open(str(PDF)))
    print(f"PDF gerado: {PDF} ({n} páginas, {PDF.stat().st_size // 1024} KB)")
    if "--rasterizar" in sys.argv:
        rasterizar()
