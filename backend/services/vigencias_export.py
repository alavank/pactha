"""Vigências a vencer em ARQUIVO — PDF e Excel a partir do MESMO recorte.

O QUE ISTO É. O botão «Vigências ≤120d» do Painel de Indicadores mostra os
instrumentos com vigência encerrando no prazo. Este módulo transforma AQUELA
MESMA lista em documento, em dois formatos, com um totalizador por município.

⚠️ UM NORMALIZADOR, DOIS RENDERIZADORES — a mesma disciplina do `rm_pdf.roteiro_rm`.
`normalizar()` decide o que é cada linha e quanto soma cada município; o PDF e o
Excel só desenham. Nenhum dos dois calcula nada: se um dia o totalizador mudar de
critério, ele muda num lugar e os dois formatos acompanham. A alternativa — cada
renderizador somando por conta — é como as duas cópias de `exportar` do RM
divergiram (ver frontend/src/lib/rmExport.ts).

⚠️ O EXCEL GRAVA NÚMERO E DATA NATIVOS, não texto. `gerar_totalizado_xlsx`
(services/rm_export.py) escreve "R$ 1.234,56" como string porque lá o Excel é uma
folha de leitura; aqui o pedido é um TOTALIZADOR, e quem recebe vai somar,
ordenar e filtrar. Uma coluna de valores em texto responde SOMA = 0 sem avisar —
o defeito mais silencioso que uma planilha pode ter.
"""
import io
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

# Cores do resto do produto (routers/export_pdf.py) — um PDF novo que estreia
# outra paleta parece de outro sistema.
_AZUL = colors.HexColor("#1e40af")
_GRADE = colors.HexColor("#cbd5e1")
_ZEBRA = colors.HexColor("#f1f5f9")
_TINTA_FRACA = colors.HexColor("#64748b")

# Faixas de urgência — as MESMAS do modal (frontend/.../VigenciasModal.tsx::tomDias),
# para o papel não classificar diferente da tela que o gerou.
_CRITICO_ATE = 30
_ATENCAO_ATE = 60
_PDF_CRITICO = colors.HexColor("#FEE2E2")
_PDF_ATENCAO = colors.HexColor("#FEF3C7")
_XL_CRITICO = "FEE2E2"
_XL_ATENCAO = "FEF3C7"

# Sem município identificado. É o MESMO literal que a tela usa quando não sabe de
# quem é o instrumento — trocar por "Sem município" aqui faria o PDF e a tela
# nomearem a mesma linha de dois jeitos.
_SEM_MUNICIPIO = "—"


def _moeda(v) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"R$ {n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data(d) -> str:
    if isinstance(d, (date, datetime)):
        return d.strftime("%d/%m/%Y")
    return str(d or "—")


def _texto(v, limite: int = 0) -> str:
    s = str(v if v is not None else "").replace("\n", " ").strip()
    if limite and len(s) > limite:
        s = s[:limite].rstrip() + "…"
    return s or "—"


def _esfera_rotulo(e) -> str:
    """`esfera` é chave técnica ('estadual', 'voluntaria'). O documento sai para
    fora da plataforma, então imprime o nome que o gestor usa."""
    return {"estadual": "Estadual", "voluntaria": "Federal"}.get(
        str(e or "").strip().casefold(), _texto(e))


def _numero(a) -> str:
    """O identificador que a pessoa reconhece: o nº do CONVÊNIO / instrumento.

    ⚠️ Quando ele não existe, a queda sai ROTULADA (23/09/2026). O relatório da
    Freitas mostrava 9342516 no "Nº" de Martinho Campos — o SIAFI — e a cliente
    leu, com razão, como se fosse o número do convênio. Estadual sem número de
    convênio sai "SIAFI 9342516"; federal sem instrumento sai "Proposta 012345/2024"."""
    conv = str(getattr(a, "nr_convenio", None) or "").strip()
    sig = str(getattr(a, "nr_sigcon", None) or "").strip()
    siafi = str(getattr(a, "nr_siafi", None) or "").strip()
    if str(getattr(a, "esfera", "") or "").strip().casefold() == "estadual":
        if conv:
            return conv
        resto = siafi or sig
        return f"SIAFI {resto}" if resto else "—"
    if conv and conv != sig:
        return conv
    if sig:
        return f"Proposta {sig}"
    return _texto(conv)


def _siafi(a) -> str:
    """O SIAFI (MG) ao lado do número do convênio — quando é outro número. É o que
    a contabilidade do Estado usa; vazio quando já está no próprio "Nº"."""
    siafi = str(getattr(a, "nr_siafi", None) or "").strip()
    if not siafi or siafi in _numero(a):
        return ""
    return siafi


def _alteracao(a) -> str:
    """A alteração de prazo do SIGCON como o portal mostra: "TERMO ADITIVO —
    <etapa> (<data>)". Vazio quando não foi lida — NUNCA "sem alteração"."""
    partes = [str(getattr(a, k, None) or "").strip()
              for k in ("alteracao_tipo", "alteracao_situacao")]
    txt = " — ".join(p for p in partes if p)
    data = str(getattr(a, "alteracao_data", None) or "").strip()
    if txt and data:
        txt += f" ({data})"
    return txt


def normalizar(alertas: list, municipios: list[str] | None = None) -> dict:
    """O RECORTE E AS CONTAS, sem uma linha de formato.

    Devolve {"linhas": [...], "totais": [...], "geral": {...}}:
      - `linhas`  1 por instrumento, na ordem em que chegaram (o chamador já
                  ordenou como a tela ordena);
      - `totais`  1 por município, do maior número de instrumentos para o menor —
                  a mesma ordem das bolhas do modal;
      - `geral`   a soma de tudo, para o PDF não somar de novo no rodapé.

    `municipios` recorta por NOME. É o que a tela filtra (o MultiSelect do modal
    trabalha com nomes), e o nome vem do próprio backend — `municipio_nome` é
    preenchido em `_nomes_municipios`. Lista vazia ou None = todos.

    ⚠️ `valor_total` PODE SER None, e None não é zero: instrumento sem valor
    coletado não vira R$ 0,00 no totalizador — ele fica fora da soma e é contado
    em `sem_valor`. Somar como zero produziria um total que parece completo e não
    é, que é pior do que um total menor acompanhado da ressalva."""
    alvo = set(municipios or [])
    linhas, por_mun = [], {}
    for a in alertas:
        nome = _texto(getattr(a, "municipio_nome", None))
        if nome == "—":
            nome = _SEM_MUNICIPIO
        if alvo and nome not in alvo:
            continue
        dias = getattr(a, "dias_restantes", None)
        valor = getattr(a, "valor_total", None)
        linhas.append({
            "municipio": nome,
            "dias": dias,
            "esfera": _esfera_rotulo(getattr(a, "esfera", None)),
            "numero": _numero(a),
            "siafi": _siafi(a),
            "alteracao": _alteracao(a),
            "orgao": _texto(getattr(a, "orgao_concedente", None)),
            "objeto": _texto(getattr(a, "objeto", None)),
            "situacao": _texto(getattr(a, "situacao", None)),
            "dt_fim": getattr(a, "dt_fim_vigencia", None),
            "valor": valor,
        })
        # `valor` nasce None: município sem nenhum valor coletado não é "R$ 0,00".
        t = por_mun.setdefault(nome, {"municipio": nome, "qtd": 0, "menor": None,
                                      "valor": None, "sem_valor": 0,
                                      "criticos": 0, "atencao": 0})
        t["qtd"] += 1
        if isinstance(dias, int):
            t["menor"] = dias if t["menor"] is None else min(t["menor"], dias)
            if dias <= _CRITICO_ATE:
                t["criticos"] += 1
            elif dias <= _ATENCAO_ATE:
                t["atencao"] += 1
        if valor is None:
            t["sem_valor"] += 1
        else:
            t["valor"] = (t["valor"] or 0.0) + float(valor)

    totais = sorted(por_mun.values(), key=lambda x: (-x["qtd"], x["municipio"]))
    geral = {
        "qtd": len(linhas),
        "municipios": len(totais),
        "valor": (sum(t["valor"] for t in totais if t["valor"] is not None)
                  if any(t["valor"] is not None for t in totais) else None),
        "sem_valor": sum(t["sem_valor"] for t in totais),
        "criticos": sum(t["criticos"] for t in totais),
        "atencao": sum(t["atencao"] for t in totais),
    }
    return {"linhas": linhas, "totais": totais, "geral": geral}


def _subtitulo(dados: dict, dias: int, municipios: list[str] | None) -> str:
    g = dados["geral"]
    recorte = (f"{len(municipios)} município(s) selecionado(s)" if municipios
               else "todos os municípios da carteira")
    partes = [f"Prazo: até {dias} dias", recorte,
              f"{g['qtd']} instrumento(s) em {g['municipios']} município(s)"]
    if g["criticos"]:
        partes.append(f"{g['criticos']} vencendo em até {_CRITICO_ATE} dias")
    return " · ".join(partes)


# ------------------------------------------------------------------ PDF --------
_CEL = ParagraphStyle("vig_cel", fontName="Helvetica", fontSize=6.8, leading=8.4)
_CEL_CAB = ParagraphStyle("vig_cab", fontName="Helvetica-Bold", fontSize=6.8,
                          leading=8.4, textColor=colors.white)


def _p(txt, estilo=_CEL) -> Paragraph:
    s = (str(txt) if txt is not None else "")
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(s or "—", estilo)


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _duas_linhas(principal, secundaria="") -> Paragraph:
    """Célula com uma segunda linha menor e cinza (o SIAFI sob o nº do convênio, a
    alteração do SIGCON sob a situação). Escapa cada parte À MÃO: `_p` escaparia
    também o <br/>."""
    txt = _esc(principal) or "—"
    if secundaria:
        txt += f'<br/><font size="5.8" color="#64748b">{_esc(secundaria)}</font>'
    return Paragraph(txt, _CEL)


def _estilo_base(n_linhas: int) -> list:
    return [
        ("BACKGROUND", (0, 0), (-1, 0), _AZUL),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, _GRADE),
        ("ROWBACKGROUNDS", (0, 1), (-1, n_linhas), [colors.white, _ZEBRA]),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]


def gerar_pdf(dados: dict, *, dias: int, municipios: list[str] | None,
              titulo_cliente: str = "") -> bytes:
    """Duas tabelas, nesta ordem: TOTALIZADOR por município e depois a LISTA.

    O totalizador vem primeiro de propósito — é a resposta à pergunta "onde está
    concentrado?", que é a mesma que a visão de bolhas do modal responde. Quem
    precisa do detalhe rola para a lista; quem precisa do número o tem na
    primeira página, sem procurar."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4),
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=10 * mm,
        title="Vigências a vencer", author="PACTHA",
    )
    st_titulo = ParagraphStyle("vig_tit", fontName="Helvetica-Bold", fontSize=14,
                               textColor=_AZUL, spaceAfter=3)
    st_sub = ParagraphStyle("vig_sub", fontName="Helvetica", fontSize=8.5,
                            textColor=colors.HexColor("#475569"), spaceAfter=9)
    st_sec = ParagraphStyle("vig_sec", fontName="Helvetica-Bold", fontSize=10,
                            textColor=_AZUL, spaceBefore=6, spaceAfter=4)
    st_nota = ParagraphStyle("vig_nota", fontName="Helvetica", fontSize=7,
                             textColor=_TINTA_FRACA, spaceBefore=3)

    cab = "Vigências a vencer"
    if titulo_cliente:
        cab += f" — {titulo_cliente}"
    story = [Paragraph(cab, st_titulo),
             Paragraph(_subtitulo(dados, dias, municipios), st_sub)]

    g = dados["geral"]
    if not dados["linhas"]:
        # Folha em branco lê-se como "não há nada vencendo". Quando o recorte é
        # que está vazio, o documento precisa dizer isso com todas as letras.
        story.append(Paragraph(
            f"Nenhum instrumento com vigência encerrando em até {dias} dias "
            "para o recorte selecionado.", st_sub))
        doc.build(story)
        return buf.getvalue()

    # --- Totalizador por município ------------------------------------------
    story.append(Paragraph("Totalizador por município", st_sec))
    cabs = ["Município", "Instrumentos", f"Vencem em até {_CRITICO_ATE} dias",
            f"Entre {_CRITICO_ATE + 1} e {_ATENCAO_ATE} dias", "Próximo vencimento",
            "Valor total (dos com valor)"]
    dados_tot = [[_p(c, _CEL_CAB) for c in cabs]]

    def _valor_txt(v, sem):
        if v is None:
            return f"sem valor coletado ({sem})" if sem else "—"
        return _moeda(v) + (f" ({sem} sem valor)" if sem else "")

    for t in dados["totais"]:
        valor_txt = _valor_txt(t["valor"], t["sem_valor"])
        dados_tot.append([
            _p(t["municipio"]), _p(t["qtd"]),
            _p(t["criticos"] or "—"), _p(t["atencao"] or "—"),
            _p(f"{t['menor']}d" if t["menor"] is not None else "—"),
            _p(valor_txt),
        ])
    geral_valor = _valor_txt(g["valor"], g["sem_valor"])
    dados_tot.append([_p("TOTAL", _CEL_CAB), _p(g["qtd"], _CEL_CAB),
                      _p(g["criticos"] or "—", _CEL_CAB), _p(g["atencao"] or "—", _CEL_CAB),
                      _p("", _CEL_CAB), _p(geral_valor, _CEL_CAB)])
    t_tot = Table(dados_tot, repeatRows=1, hAlign="LEFT",
                  colWidths=[60 * mm, 24 * mm, 18 * mm, 22 * mm, 24 * mm, 55 * mm])
    estilo = _estilo_base(len(dados["totais"]))
    estilo += [
        ("ALIGN", (1, 0), (4, -1), "CENTER"),
        ("ALIGN", (5, 1), (5, -1), "RIGHT"),
        # A linha do TOTAL repete a cor do cabeçalho: fecha a tabela visualmente
        # e impede que ela seja lida como "mais um município".
        ("BACKGROUND", (0, -1), (-1, -1), _AZUL),
    ]
    t_tot.setStyle(TableStyle(estilo))
    story.append(t_tot)
    if g["sem_valor"]:
        story.append(Paragraph(
            f"Atenção: {g['sem_valor']} instrumento(s) sem valor coletado na fonte não "
            "entram na soma — o total é do que tem valor conhecido, não do total "
            "de instrumentos. «Próximo vencimento» = dias até o instrumento que "
            "vence primeiro no município.", st_nota))

    # --- Lista ---------------------------------------------------------------
    story.append(Spacer(1, 10))
    story.append(Paragraph("Instrumentos", st_sec))
    cabs_l = ["Dias", "Município", "Esfera", "Nº", "Órgão", "Objeto",
              "Situação", "Fim da vigência", "Valor"]
    dados_lst = [[_p(c, _CEL_CAB) for c in cabs_l]]
    pinturas = []
    for i, ln in enumerate(dados["linhas"], start=1):
        d = ln["dias"]
        if isinstance(d, int):
            if d <= _CRITICO_ATE:
                pinturas.append(("BACKGROUND", (0, i), (0, i), _PDF_CRITICO))
            elif d <= _ATENCAO_ATE:
                pinturas.append(("BACKGROUND", (0, i), (0, i), _PDF_ATENCAO))
        dados_lst.append([
            _p(f"{d}d" if isinstance(d, int) else "—"),
            _p(ln["municipio"]), _p(ln["esfera"]),
            _duas_linhas(ln["numero"], f"SIAFI {ln['siafi']}" if ln["siafi"] else ""),
            _p(_texto(ln["orgao"], 40)), _p(_texto(ln["objeto"], 190)),
            _duas_linhas(_texto(ln["situacao"], 40),
                         f"SIGCON: {_texto(ln['alteracao'], 90)}" if ln["alteracao"] else ""),
            _p(_data(ln["dt_fim"])),
            _p(_moeda(ln["valor"])),
        ])
    t_lst = Table(dados_lst, repeatRows=1, hAlign="LEFT",
                  colWidths=[11 * mm, 30 * mm, 15 * mm, 26 * mm, 33 * mm,
                             78 * mm, 32 * mm, 21 * mm, 31 * mm])
    estilo_l = _estilo_base(len(dados["linhas"]))
    estilo_l += [("ALIGN", (0, 0), (0, -1), "CENTER"),
                 ("ALIGN", (8, 1), (8, -1), "RIGHT")]
    estilo_l += pinturas
    t_lst.setStyle(TableStyle(estilo_l))
    story.append(t_lst)

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · PACTHA — "
        "Plataforma de Acompanhamento. Os prazos são contados a partir da data de "
        "emissão deste documento.",
        ParagraphStyle("vig_rod", fontName="Helvetica", fontSize=7,
                       textColor=_TINTA_FRACA, alignment=2)))
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------- EXCEL --------
_FMT_MOEDA = 'R$ #,##0.00'
_FMT_DATA = "DD/MM/YYYY"


def gerar_xlsx(dados: dict, *, dias: int, municipios: list[str] | None,
               titulo_cliente: str = "") -> bytes:
    """Duas abas: «Totalizador» e «Lista».

    Duas abas e não dois blocos na mesma: uma planilha com dois cabeçalhos
    empilhados quebra o autofiltro e a tabela dinâmica — as duas coisas para as
    quais alguém pede Excel em vez de PDF."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    azul = PatternFill("solid", fgColor="1E40AF")
    critico = PatternFill("solid", fgColor=_XL_CRITICO)
    atencao = PatternFill("solid", fgColor=_XL_ATENCAO)
    cab_fonte = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
    negrito = Font(name="Calibri", bold=True, size=10)
    normal = Font(name="Calibri", size=10)
    centro = Alignment(horizontal="center", vertical="center", wrap_text=True)
    esq = Alignment(horizontal="left", vertical="top", wrap_text=True)
    fino = Side(style="thin", color="BFBFBF")
    borda = Border(left=fino, right=fino, top=fino, bottom=fino)

    def _cabecalho(ws, rotulos, larguras):
        # ⚠️ Uma largura por rótulo: o `zip` cortaria o último cabeçalho em silêncio.
        assert len(rotulos) == len(larguras), "um rótulo sem largura some da planilha"
        for i, (rot, larg) in enumerate(zip(rotulos, larguras), start=1):
            ws.column_dimensions[get_column_letter(i)].width = larg
            c = ws.cell(1, i, rot)
            c.fill = azul; c.font = cab_fonte; c.alignment = centro; c.border = borda
        # Altura da linha 1: sem ela o Excel não aumenta a linha para quebrar o
        # texto, e o botão do filtro cobre o fim do rótulo — os "cabeçalhos
        # cortados" que a Freitas mostrou (23/09/2026).
        ws.row_dimensions[1].height = 32
        ws.freeze_panes = "A2"

    def _filtro(ws, n_colunas, ultima_linha):
        # Autofiltro no intervalo dos DADOS (e só deles): na linha 1 sozinha o Excel
        # adivinha o intervalo, e pode pegar a linha TOTAL e movê-la ao ordenar.
        ws.auto_filter.ref = f"A1:{get_column_letter(n_colunas)}{max(ultima_linha, 1)}"

    # --- aba 1: totalizador ---------------------------------------------------
    ws = wb.active
    ws.title = "Totalizador"
    _cabecalho(ws, ["Município", "Instrumentos", f"Vencem em até {_CRITICO_ATE} dias",
                    f"Entre {_CRITICO_ATE + 1} e {_ATENCAO_ATE} dias",
                    "Próximo vencimento (dias)", "Valor total (dos com valor)",
                    "Qtd. sem valor coletado"],
               [34, 15, 20, 20, 22, 24, 20])
    r = 2
    for t in dados["totais"]:
        vals = [t["municipio"], t["qtd"], t["criticos"], t["atencao"],
                t["menor"], t["valor"], t["sem_valor"]]
        for i, v in enumerate(vals, start=1):
            c = ws.cell(r, i, v)
            c.font = normal; c.border = borda
            c.alignment = esq if i == 1 else centro
            if i == 6:
                c.number_format = _FMT_MOEDA
        if t["menor"] is not None:
            if t["menor"] <= _CRITICO_ATE:
                ws.cell(r, 5).fill = critico
            elif t["menor"] <= _ATENCAO_ATE:
                ws.cell(r, 5).fill = atencao
        r += 1
    _filtro(ws, 7, r - 1)
    g = dados["geral"]
    # ⚠️ O TOTAL é FÓRMULA, não número gravado. Quem recebe a planilha filtra e
    # apaga linha; um total constante continuaria exibindo o valor de antes, com
    # cara de certo. `SUM` sobre o intervalo acompanha o que sobrar.
    if dados["totais"]:
        # Sem nenhum valor coletado, o TOTAL do valor fica EM BRANCO: `SUM` de
        # células vazias dá 0 e a linha diria "R$ 0,00" — o mesmo engano das linhas.
        total_valor = f"=SUM(F2:F{r - 1})" if g["valor"] is not None else ""
        for i, v in enumerate(["TOTAL", f"=SUM(B2:B{r - 1})", f"=SUM(C2:C{r - 1})",
                               f"=SUM(D2:D{r - 1})", "", total_valor,
                               f"=SUM(G2:G{r - 1})"], start=1):
            c = ws.cell(r, i, v)
            c.font = negrito; c.border = borda
            c.alignment = esq if i == 1 else centro
            if i == 6:
                c.number_format = _FMT_MOEDA

    # --- aba 2: lista ---------------------------------------------------------
    ws2 = wb.create_sheet("Lista")
    _cabecalho(ws2, ["Dias restantes", "Município", "Esfera", "Nº do instrumento",
                     "SIAFI (MG)", "Órgão", "Objeto", "Situação",
                     "Alteração no SIGCON (termo aditivo / prorrogação)",
                     "Fim da vigência", "Valor"],
               [16, 30, 12, 24, 14, 30, 60, 30, 40, 18, 18])
    j = 1
    for j, ln in enumerate(dados["linhas"], start=2):
        vals = [ln["dias"], ln["municipio"], ln["esfera"], ln["numero"], ln["siafi"] or None,
                ln["orgao"], ln["objeto"], ln["situacao"], ln["alteracao"] or None,
                ln["dt_fim"], ln["valor"]]
        for i, v in enumerate(vals, start=1):
            c = ws2.cell(j, i, v)
            c.font = normal; c.border = borda
            c.alignment = centro if i in (1, 3, 5, 10) else esq
            if i == 10 and isinstance(v, (date, datetime)):
                c.number_format = _FMT_DATA
            if i == 11:
                c.number_format = _FMT_MOEDA
        d = ln["dias"]
        if isinstance(d, int):
            if d <= _CRITICO_ATE:
                ws2.cell(j, 1).fill = critico
            elif d <= _ATENCAO_ATE:
                ws2.cell(j, 1).fill = atencao
    _filtro(ws2, 11, j)

    # --- aba 3: o recorte -----------------------------------------------------
    # Uma planilha circula solta por e-mail. Sem esta aba, daqui a um mês ninguém
    # sabe se ela é da carteira inteira ou de três municípios, nem de que dia são
    # os prazos — e "45 dias" sem data de emissão não quer dizer nada.
    ws3 = wb.create_sheet("Recorte")
    ws3.column_dimensions["A"].width = 26
    ws3.column_dimensions["B"].width = 60
    linhas_meta = [
        ("Relatório", "Vigências a vencer"),
        ("Cliente", titulo_cliente or "—"),
        ("Prazo", f"instrumentos vencendo em até {dias} dias"),
        ("Municípios", ", ".join(municipios) if municipios
         else "todos os municípios da carteira"),
        ("Instrumentos", g["qtd"]),
        ("Municípios com vigência a vencer", g["municipios"]),
        ("Valor total (dos que têm valor)", g["valor"] if g["valor"] is not None
         else "sem valor coletado"),
        ("Sem valor coletado", g["sem_valor"]),
        ("Emitido em", datetime.now().strftime("%d/%m/%Y %H:%M")),
    ]
    for j, (rot, val) in enumerate(linhas_meta, start=1):
        a = ws3.cell(j, 1, rot); a.font = negrito; a.alignment = esq
        b = ws3.cell(j, 2, val); b.font = normal; b.alignment = esq
        if rot.startswith("Valor total") and isinstance(val, (int, float)):
            b.number_format = _FMT_MOEDA

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
