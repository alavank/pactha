"""O RELATÓRIO DE COMPROMISSOS em PDF — Dia, Semana ou Mês.

Quem decide QUAIS linhas entram é o router (`routers/agendamentos._filtros`, a
mesma função que a tela usa); este módulo só DESENHA o que recebe.

⚠️ ESTE MÓDULO NÃO FILTRA E NÃO CALCULA NADA — a única coisa que ele deriva é o
AGRUPAMENTO POR DIA, que é formatação e não recorte. É a mesma disciplina do
`vigencias_export`: um recorte, um renderizador. Se o arquivo montasse a própria
consulta, ele divergiria da tela no primeiro ajuste do filtro — e a divergência
aparece como "o relatório veio com um compromisso a mais", sem nada para culpar.

⚠️ AS ANOTAÇÕES NÃO ENTRAM, e é decisão do dono. O relatório é a AGENDA — o que
está marcado, quando, para quem —, e circula fora da plataforma: vai por e-mail,
é impresso, fica em cima da mesa. O histórico de anotações é a conversa interna
da equipe sobre cada compromisso; ela se lê na tela, com a permissão do módulo.

⚠️ RETRATO, e não paisagem como os PDFs de convênios. Aqueles são tabelas de
números, com muitas colunas estreitas. Este é uma AGENDA: seis colunas curtas e
uma leitura de cima para baixo, dia após dia. Em paisagem sobraria papel branco à
direita e o olho teria de varrer o dobro da distância entre a hora e a demanda.

⚠️ A IDENTIDADE DO TENANT VEM DE ONDE JÁ VINHA. O logo é o mesmo `RM_LOGO` que o
Relatório de Monitoramento imprime, resolvido pela MESMA função (`rm_pdf`) — e
não por uma cópia dela. Duas resoluções de caminho de logo divergem no dia em que
alguém montar um volume: um relatório sai com a marca e o outro sem, e ninguém
descobre por quê. O mesmo vale para o `RM_RODAPE`, que é o endereço de quem
assina.
"""
from __future__ import annotations

import html
import io
from datetime import date, datetime

_AZUL = "1E40AF"
_CINZA = "475569"

_PERIODO_ROTULO = {"dia": "Dia", "semana": "Semana", "mes": "Mês"}
_DIA_SEMANA = ("segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo")
_MES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
        "agosto", "setembro", "outubro", "novembro", "dezembro")


def _dia(iso: str | None) -> date | None:
    """`YYYY-MM-DD` -> date. Devolve None em qualquer coisa ilegível.

    ⚠️ NÃO usa `datetime.fromisoformat` sobre um valor com hora: a coluna do
    banco é DATE justamente para não ter fuso, e reintroduzir um instante aqui
    traria de volta o problema de a data virar o dia anterior."""
    if not iso:
        return None
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _por_extenso(d: date) -> str:
    return f"{_DIA_SEMANA[d.weekday()]}, {d.day} de {_MES[d.month - 1]} de {d.year}"


def _horario(item: dict) -> str:
    """`09:00` ou `09:00 – 11:30`. O travessão é o mesmo da tela."""
    inicio = item.get("hora_inicio") or "—"
    if item.get("tem_periodo") and item.get("hora_fim"):
        return f"{inicio} – {item['hora_fim']}"
    return inicio


def _telefone(digitos: str | None) -> str:
    """`51999999999` -> `(51) 99999-9999`. A máscara é da APRESENTAÇÃO; o banco
    guarda dígito (ver `routers/agendamentos._so_digitos`)."""
    d = "".join(c for c in str(digitos or "") if c.isdigit())
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return d or "—"


def _esc(v) -> str:
    """Texto do usuário dentro de `Paragraph` do reportlab.

    ⚠️ O reportlab interpreta um subconjunto de HTML no `Paragraph`. Uma demanda
    que contenha `<` ou `&` — e demanda é campo livre — quebra a construção do
    PDF com um erro de parser, ou some da página. Escapar é obrigatório, e a
    quebra de linha do texto vira `<br/>` porque o `Paragraph` ignora `\\n`.
    """
    if v is None:
        return ""
    return html.escape(str(v)).replace("\n", "<br/>")


def _agrupar_por_dia(itens: list[dict]) -> list[tuple[date | None, list[dict]]]:
    """Preserva a ordem que o router entregou (data, hora, id).

    ⚠️ NÃO reordena. A consulta já vem `ORDER BY data, hora_inicio`; ordenar de
    novo aqui seria uma segunda regra de ordenação para manter em sincronia com
    a da tela — e a que ficasse para trás produziria um arquivo com os
    compromissos do dia em ordem diferente da agenda que a pessoa está vendo."""
    grupos: list[tuple[date | None, list[dict]]] = []
    for item in itens:
        d = _dia(item.get("data"))
        if grupos and grupos[-1][0] == d:
            grupos[-1][1].append(item)
        else:
            grupos.append((d, [item]))
    return grupos


def gerar_pdf(itens: list[dict], *, periodo: str, de: date, ate: date,
              usuario: str = "", entidade: str | None = None) -> bytes:
    """A agenda do recorte, agrupada por dia.

    `entidade` só vem preenchida no tenant de UM município (a prefeitura): ali
    ele é a identidade do documento. Numa assessoria fica em branco de propósito
    — quem nomeia cada linha é a coluna «Município», e escrever o nome de um
    cliente no cabeçalho de um relatório que traz vários seria pior que não
    escrever nenhum.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    # Município só vira coluna quando há mais de um no recorte — com um só, o
    # nome se repetiria em toda linha sem distinguir nada, comendo a largura que
    # a demanda precisa.
    com_municipio = len({i.get("municipio_id") for i in itens}) > 1 or not entidade

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm,
        # Margem superior larga: é a faixa do cabeçalho com o logo do tenant,
        # desenhado a cada página pelo `_rodape_e_marca` abaixo.
        topMargin=26 * mm, bottomMargin=16 * mm,
        title="Agenda de compromissos", author="PACTHA",
    )
    estilos = getSampleStyleSheet()
    t_titulo = ParagraphStyle("T", parent=estilos["Heading1"], fontSize=14,
                              textColor=colors.HexColor(f"#{_AZUL}"), spaceAfter=2)
    t_sub = ParagraphStyle("S", parent=estilos["Normal"], fontSize=9,
                           textColor=colors.HexColor(f"#{_CINZA}"), spaceAfter=2)
    t_dia = ParagraphStyle("D", parent=estilos["Normal"], fontSize=10,
                           textColor=colors.HexColor(f"#{_AZUL}"),
                           spaceBefore=6, spaceAfter=3, leading=13)
    t_cel = ParagraphStyle("C", parent=estilos["Normal"], fontSize=8, leading=10)
    t_cab = ParagraphStyle("H", parent=estilos["Normal"], fontSize=8, leading=10,
                           textColor=colors.white)

    historia = [Paragraph("Agenda de compromissos", t_titulo)]
    if entidade:
        historia.append(Paragraph(_esc(entidade), t_sub))
    rotulo = _PERIODO_ROTULO.get(periodo, periodo)
    if de == ate:
        recorte = f"{rotulo}: {_por_extenso(de)}"
    else:
        recorte = f"{rotulo}: de {de:%d/%m/%Y} a {ate:%d/%m/%Y}"
    # ⚠️ O SUBTÍTULO DIZ O RECORTE, QUEM EMITIU E QUANDO. Um relatório sem isso
    # vira uma lista sem contexto assim que sai do navegador — e quem recebe não
    # tem como saber se está vendo o dia, a semana ou o mês, nem de quando é.
    emissao = f"Emitido em {datetime.now():%d/%m/%Y às %H:%M}"
    if usuario:
        emissao += f" por {_esc(usuario)}"
    historia.append(Paragraph(
        f"{recorte}. {len(itens)} compromisso(s). {emissao}.", t_sub))
    historia.append(Spacer(1, 4))

    if not itens:
        historia.append(Paragraph(
            "Nenhum compromisso no período selecionado.", t_sub))

    cabecalho = ["Horário", "Demanda"]
    larguras = [24 * mm, 54 * mm]
    if com_municipio:
        cabecalho.append("Município")
        larguras.append(28 * mm)
    cabecalho += ["Solicitante", "Contato", "Situação"]
    larguras += [30 * mm, 28 * mm, 18 * mm]
    # A tabela ocupa a largura útil (A4 210 − 28 de margem = 182 mm).
    sobra = 182 - sum(l / mm for l in larguras)
    larguras[1] += sobra * mm

    for d, doDia in _agrupar_por_dia(itens):
        linhas = [[Paragraph(f"<b>{c}</b>", t_cab) for c in cabecalho]]
        for item in doDia:
            celulas = [Paragraph(_horario(item), t_cel),
                       Paragraph(_esc(item.get("demanda")), t_cel)]
            if com_municipio:
                celulas.append(Paragraph(_esc(item.get("municipio")), t_cel))
            celulas += [
                Paragraph(_esc(item.get("solicitante")) or "—", t_cel),
                Paragraph(_telefone(item.get("contato_whatsapp")), t_cel),
                Paragraph(_esc(item.get("coluna")), t_cel),
            ]
            linhas.append(celulas)
        tabela = Table(linhas, colWidths=larguras, repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{_AZUL}")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BFBFBF")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        # ⭐ A COR DO COMPROMISSO ACOMPANHA O ARQUIVO. É a mesma cor que
        # identifica aquele compromisso nas três abas e no card lateral; sem ela
        # o relatório seria a única superfície do módulo em que a pessoa não
        # reconhece o que já sabe de cor. Vai como faixa fina na coluna do
        # horário — não como fundo da linha, que competiria com o texto.
        for i, item in enumerate(doDia, start=1):
            cor = str(item.get("cor") or "").strip()
            if cor.startswith("#") and len(cor) == 7:
                estilo.append(("LINEBEFORE", (0, i), (0, i), 2.5,
                               colors.HexColor(cor)))
        tabela.setStyle(TableStyle(estilo))
        titulo_dia = Paragraph(
            f"<b>{_por_extenso(d) if d else 'Sem data'}</b>", t_dia)
        # `KeepTogether` só do título com a PRIMEIRA linha faria a tabela inteira
        # saltar de página quando ela é longa. Aqui o par é título + tabela, e o
        # `repeatRows=1` cuida do cabeçalho nas páginas seguintes.
        historia.append(KeepTogether([titulo_dia, tabela]))

    doc.build(historia, onFirstPage=_rodape_e_marca, onLaterPages=_rodape_e_marca,
              canvasmaker=_canvas_numerado())
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Cabeçalho (marca do tenant) e rodapé (endereço + paginação)
# ---------------------------------------------------------------------------

def _logo_do_tenant() -> str | None:
    """O MESMO logo do Relatório de Monitoramento, pela MESMA função.

    ⚠️ IMPORTA EM VEZ DE COPIAR, e o nome privado é de propósito: `rm_pdf` é
    quem define como o valor de `RM_LOGO` vira caminho de arquivo (literal,
    depois `backend/assets/`), e duplicar essa regra aqui faria os dois
    relatórios do mesmo tenant divergirem no dia em que alguém montasse um
    volume. Falha de import ou de leitura devolve None e o documento sai sem
    marca — um logo faltando nunca pode impedir a emissão."""
    try:
        from services.rm_pdf import _logo_path
        return _logo_path()
    except Exception:
        return None


def _rodape_do_tenant() -> str:
    """O endereço de quem assina, como no RM. Vazio = rodapé sem endereço."""
    try:
        from config import get_settings
        return (get_settings().RM_RODAPE or "").strip()
    except Exception:
        return ""


def _rodape_e_marca(canvas, doc) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm

    canvas.saveState()
    logo = _logo_do_tenant()
    if logo:
        try:
            canvas.drawImage(logo, 14 * mm, A4[1] - 22 * mm,
                             width=44 * mm, height=14 * mm,
                             preserveAspectRatio=True, anchor="sw", mask="auto")
        except Exception:
            pass          # logo ilegível nunca derruba a emissão
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor(f"#{_CINZA}"))
    canvas.drawRightString(A4[0] - 14 * mm, A4[1] - 14 * mm,
                           "PACTHA · Agenda de compromissos")
    rodape = _rodape_do_tenant()
    if rodape:
        canvas.drawCentredString(A4[0] / 2, 10 * mm, rodape[:160])
    canvas.restoreState()


def _canvas_numerado():
    """«Página N de M» — e o M exige duas passagens.

    ⚠️ O TOTAL SÓ EXISTE NO FIM. Um `canvas.getPageNumber()` desenhado durante a
    construção sabe em que página está e não sabe quantas serão; escrever só
    "Página 3" num documento que circula impresso deixa quem recebe sem saber se
    a folha 3 é a última. Por isso as páginas são guardadas e só desenhadas no
    `save()`, quando o total já é conhecido — é o padrão do reportlab para isso.

    ⚠️ A CLASSE NASCE DENTRO DA FUNÇÃO porque o import do reportlab é preguiçoso
    neste módulo inteiro (ver `gerar_pdf`): declarar `class X(canvas.Canvas)` no
    corpo do arquivo puxaria a biblioteca no import do módulo, e este arquivo é
    importado pelo router — que responde muita requisição que não gera PDF
    nenhum.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as _canvas

    class Numerado(_canvas.Canvas):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._paginas = []

        def showPage(self):
            self._paginas.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._paginas)
            for estado in self._paginas:
                self.__dict__.update(estado)
                self.setFont("Helvetica", 7.5)
                self.setFillColor(colors.HexColor(f"#{_CINZA}"))
                self.drawRightString(A4[0] - 14 * mm, 10 * mm,
                                     f"Página {self._pageNumber} de {total}")
                super().showPage()
            super().save()

    return Numerado
