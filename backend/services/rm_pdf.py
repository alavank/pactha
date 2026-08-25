"""Gerador de PDF do RM seguindo o padrao Freitas.

Estrutura visual (replica do PDF de exemplo):
  - Margem padrao, rodape fixo em todas as paginas (endereco Freitas)
  - Cabecalho: titulo + cidade/data
  - Por PARTE: titulo grande centralizado/destacado
  - Por SECAO: subtitulo (caps)
  - Por GRUPO: bullet '●' + nome do orgao (negrito)
  - Por ITEM: identificador (negrito) + bullets '➢' com cada campo
"""
from __future__ import annotations
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from config import get_settings
# Nome legivel das consultas para a linha de escopo. Modulo de DADO puro (nao
# importa banco, nem reportlab): nao cria ciclo com este arquivo.
from services.rm_fontes import rotulo_longo
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether,
)

# Altura do logo no cabecalho. A largura e o dobro apenas como CAIXA maxima — o
# `preserveAspectRatio` encaixa a imagem dentro dela sem deformar.
# MEDIDAS DA REFERÊNCIA, em CENTÍMETROS e em CONSTANTE — lidas por DOIS
# renderizadores (o PDF daqui e o Word de services/rm_docx). Cravar o número em
# cada um faz "o logo está pequeno" ser corrigido só no PDF, e o Word sair com
# outro tamanho — sem erro e sem teste que compare os dois documentos.
_LOGO_ALT_CM = 1.8
_LOGO_ALT = _LOGO_ALT_CM * cm
# Margens medidas no .docx do padrão Freitas (sectPr/pgMar): topo, base, esq, dir.
# ASSIMÉTRICAS de propósito — a margem superior larga é o espaço do cabeçalho, e
# a direita é menor que a esquerda (documento pensado para encadernação).
_MARGENS_CM = (4.5, 3.0, 2.0, 1.5)
_CAB_DIST_CM = 1.6      # distância da borda ao cabeçalho
_ROD_DIST_CM = 0.8      # distância da borda ao rodapé

# GLIFOS DA HIERARQUIA VISUAL (docstring do modulo). Ficam em constante porque
# valem para TODO renderizador do RM. Repetir o caractere solto em cada um e o
# caminho para o Word sair com bullet diferente do PDF sem ninguem notar.
_GLIFO_GRUPO = "●"
_GLIFO_CAMPO = "➢"

# Texto do relatorio sem conteudo. Constante porque os dois renderizadores
# imprimem exatamente a mesma frase (em italico), e nao ha teste que pegue a
# divergencia.
_TXT_VAZIO = ("Relatório sem conteúdo. Use o botão 'Auto-popular' "
              "para puxar os dados atuais do banco.")


def _fmt_dt(d: Any) -> str:
    if not d:
        return ""
    try:
        if isinstance(d, str):
            d = datetime.fromisoformat(d[:10]).date()
        if isinstance(d, date):
            return d.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        pass
    return str(d)


def _fmt_money(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    s = f"{v:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


def _meses_pt(n: int) -> str:
    return [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ][n - 1]


def _data_extenso(d: Any) -> str:
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d[:10]).date()
        except ValueError:
            return d
    if isinstance(d, date):
        return f"{d.day:02d} de {_meses_pt(d.month)} de {d.year}"
    return str(d)


def _styles():
    """⚠️ ENTRELINHA 1,5 EM TODO O DOCUMENTO — `leading = 1,5 × fontSize`.

    É a medida da referência: no .docx do padrão Freitas os parágrafos do corpo
    trazem `w:spacing w:line="360"` com `lineRule` automático, e 360/240 = 1,5
    linhas. Vale para o título, para o corpo e para os títulos de parte/seção
    (medido parágrafo a parágrafo no XML). O documento fica mais longo do que
    estava — é o efeito esperado, não regressão."""
    base = getSampleStyleSheet()
    s = {}
    s["titulo_principal"] = ParagraphStyle(
        "TituloPrincipal", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=13, alignment=TA_CENTER, spaceAfter=4, leading=19.5,
    )
    # LOCAL E DATA À DIREITA — é assim na referência ("Brasília/DF, 29 de Julho de
    # 2026", `align=right` logo abaixo do título centralizado). Estava centralizada.
    s["data_local"] = ParagraphStyle(
        "DataLocal", parent=base["Normal"], fontName="Helvetica",
        fontSize=11, alignment=TA_RIGHT, spaceAfter=14, leading=16.5,
    )
    s["parte_titulo"] = ParagraphStyle(
        "ParteTitulo", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=12, alignment=TA_CENTER, spaceBefore=14, spaceAfter=10,
        leading=18.0, textColor=colors.HexColor("#1e40af"),
    )
    s["secao_titulo"] = ParagraphStyle(
        "SecaoTitulo", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, alignment=TA_CENTER, spaceBefore=10, spaceAfter=8,
        leading=16.5, textColor=colors.HexColor("#111827"),
    )
    s["grupo_titulo"] = ParagraphStyle(
        "GrupoTitulo", parent=base["Normal"], fontName="Helvetica-Bold",
        # ⭐ spaceBefore=26 (era 10): o `●` abre um TÓPICO NOVO — outro órgão,
        # outro programa — e vinha com quase o mesmo respiro que separa um campo
        # do outro dentro do mesmo instrumento. Numa página cheia, "Transferência
        # Especial (Emenda Pix)" colava na caixa de desembolso do convênio
        # anterior e lia-se como continuação dele. Pedido do dono, com o print.
        #
        # O número é maior que o `spaceBefore=14` do `item_id` DE PROPÓSITO: a
        # hierarquia tem de aparecer no espaço em branco antes de aparecer na
        # fonte. Tópico > instrumento > campo, e o respiro segue a mesma ordem.
        fontSize=10.5, spaceBefore=26, spaceAfter=4, leftIndent=4, leading=15.75,)
    s["item_id"] = ParagraphStyle(
        "ItemId", parent=base["Normal"], fontName="Helvetica-Bold",
        # spaceBefore=14 (era 4): o identificador do instrumento estava colado no
        # nome do órgão logo acima, e um não se lia como filho do outro. Pedido do
        # dono, com o print do "22000 - Ministério da Agricultura" seguido de
        # "Convênio: 993503/2026" sem respiro nenhum.
        #
        # ⭐ leftIndent=28 (era 14): "Plano de Ação: …", "Processo: …",
        # "Convênio: …" agora começam na MESMA coluna das tags `➢` logo abaixo.
        # 28 e não 18 porque o glifo `➢` NÃO é bullet do reportlab — ele é o
        # primeiro caractere do texto (ver `_flow_campo`), então a borda esquerda
        # visível daquelas linhas é o `leftIndent` delas, 28. `bulletIndent=18`
        # no `item_campo` é decoração inerte; alinhar por ele deixaria o
        # identificador 10pt à esquerda das tags — quase alinhado, que é pior de
        # olhar do que claramente desalinhado.
        fontSize=10, spaceBefore=14, spaceAfter=2, leftIndent=28, leading=15.0,)
    s["item_campo"] = ParagraphStyle(
        "ItemCampo", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, bulletIndent=18, spaceAfter=1,
        leading=14.25, alignment=TA_JUSTIFY,
    )
    s["rodape"] = ParagraphStyle(
        "Rodape", parent=base["Normal"], fontName="Helvetica",
        fontSize=8, alignment=TA_CENTER, textColor=colors.HexColor("#475569"),
    )
    # DESTAQUE da Cláusula Suspensiva / Liminar Judicial (caixa âmbar)
    s["clausula"] = ParagraphStyle(
        "Clausula", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, rightIndent=10, spaceBefore=3, spaceAfter=3,
        leading=14.25, backColor=colors.HexColor("#FEF3C7"),
        borderColor=colors.HexColor("#D97706"), borderWidth=1, borderPadding=5,
        textColor=colors.HexColor("#7c2d12"),
    )
    # INFORMATIVO (caixa cinza): licitacoes em dia, evento do historico, ultima
    # alteracao. ⚠️ Estas NAO sao alerta — usavam o mesmo ambar da clausula
    # suspensiva, e um convenio saudavel com 5 licitacoes "Concluído" virava um
    # bloco de alerta de 6 linhas. O ambar fica reservado ao que pede acao
    # (clausula/liminar e licitacao ZERO em contratacao Normal).
    s["informativo"] = ParagraphStyle(
        "Informativo", parent=base["Normal"], fontName="Helvetica",
        fontSize=9.5, leftIndent=28, rightIndent=10, spaceBefore=3, spaceAfter=3,
        leading=14.25, backColor=colors.HexColor("#F1F5F9"),
        borderColor=colors.HexColor("#CBD5E1"), borderWidth=1, borderPadding=5,
        textColor=colors.HexColor("#334155"),
    )
    return s


_ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _logo_path() -> str | None:
    """Caminho do logo do cabecalho, ou None.

    Aceita o MESMO valor que o frontend ja usa em NEXT_PUBLIC_CLIENT_LOGO — por
    isso fica so com o NOME do arquivo: "/freitas-logo.jpeg" e "freitas-logo.jpeg"
    dao no mesmo, e o dono pode copiar a env de um app para o outro sem editar.
    Caminho absoluto tambem vale (monta um volume e aponta).

    Arquivo ausente devolve None e o cabecalho sai sem logo — nunca levanta
    excecao: um logo faltando nao pode impedir a emissao do relatorio."""
    try:
        nome = (get_settings().RM_LOGO or "").strip()
    except Exception:
        return None
    if not nome:
        return None
    # ⚠️ A ORDEM IMPORTA. O valor tipico e "/freitas-logo.jpeg", copiado do
    # NEXT_PUBLIC_CLIENT_LOGO — que em Linux e um caminho ABSOLUTO e nao existe na
    # raiz do container. Por isso: tenta o caminho literal (serve para quem monta
    # um volume) e, NAO existindo, cai para o nome do arquivo em backend/assets/.
    # Sem esse fallback, justamente o valor que o dono ia copiar nao acharia nada.
    p = Path(nome)
    if p.is_absolute() and p.is_file():
        return str(p)
    alt = _ASSETS / p.name
    return str(alt) if alt.is_file() else None


def _on_page(canvas, doc, rodape_txt: str, email_txt: str = ""):
    canvas.saveState()
    # CABECALHO: logo a ESQUERDA, em TODAS as paginas — a regra da referencia
    # (o .docx nao marca `titlePg`, entao o cabecalho padrao vale desde a 1a
    # pagina). Fica na faixa reservada pela margem superior de 4,5 cm, a 1,6 cm do
    # topo, alinhado a margem esquerda. `preserveAspectRatio` para nao deformar
    # logos de proporcoes diferentes (o da Freitas e quase quadrado, 512x487; os
    # brasoes de Monte Siao e Santa Maria nao sao).
    _logo = _logo_path()
    if _logo:
        try:
            canvas.drawImage(_logo, 2 * cm, A4[1] - 1.6 * cm - _LOGO_ALT,
                             width=_LOGO_ALT * 2, height=_LOGO_ALT,
                             preserveAspectRatio=True, anchor="sw", mask="auto")
        except Exception:
            pass          # logo ilegivel nunca derruba a emissao
    # ⭐ E-MAIL A DIREITA, na MESMA faixa do logo (pedido do dono). O logo ocupa
    # de 2cm ate 2cm+_LOGO_ALT*2 na esquerda; aqui e a borda direita, alinhado
    # pela direita para o texto crescer para dentro e nunca invadir a margem.
    #
    # A altura e o MEIO do logo, e nao o topo dele: alinhado pelo topo, um e-mail
    # de uma linha ficava pendurado ao lado de uma marca de 1,8cm e lia-se como
    # legenda solta. `A4[1] - 1.6cm - _LOGO_ALT/2` poe os dois no mesmo eixo
    # optico, e o `- 3` compensa a linha de base da fonte (o `drawRightString`
    # posiciona a BASE do texto, nao o centro).
    #
    # ⚠️ Sai em TODAS as paginas, como o logo — e pelo mesmo motivo: o .docx de
    # referencia nao marca `titlePg`, entao o cabecalho padrao vale desde a
    # primeira. Um contato que aparece so na capa some quando alguem imprime ou
    # encaminha uma pagina do meio.
    if email_txt:
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#334155"))
        canvas.drawRightString(A4[0] - 2 * cm,
                               A4[1] - 1.6 * cm - _LOGO_ALT / 2 - 3,
                               email_txt)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawCentredString(A4[0] / 2, 0.8 * cm, rodape_txt)
    canvas.drawRightString(A4[0] - 1.5 * cm, 0.8 * cm, str(doc.page))
    canvas.restoreState()


def _campos_do_item(item: dict) -> list[tuple[str, str]]:
    """Retorna lista [(label, valor), ...] de campos nao vazios do item."""
    out = []
    def add(label, val):
        if val not in (None, "", 0) or (label == "Valor de contrapartida" and val == 0):
            out.append((label, val))

    if item.get("objeto"):
        out.append(("Objeto", item["objeto"]))
    # PROGRAMA logo abaixo do Objeto (pedido do dono): o objeto diz O QUE é, o
    # programa diz DE ONDE vem o dinheiro (ex.: "PRONE"). Hoje só as voluntárias
    # preenchem esta chave; nas demais fontes ela nem existe no item e a linha não
    # é impressa — por isso não usa o helper `add`, que trata 0 como vazio.
    if item.get("programa"):
        out.append(("Programa", item["programa"]))
    # ORIGEM NO NOVO PAC. O item do PAC correspondente deixa de sair separado
    # (rm_builder pula os que já apareceram como voluntária) — a informação de
    # que o recurso veio do PAC não se perde, migra para cá.
    if item.get("pac_origem"):
        out.append(("Origem — Novo PAC", item["pac_origem"]))
    if item.get("parlamentar"):
        out.append(("Parlamentar responsável pela indicação", item["parlamentar"]))
    add("Valor global", _fmt_money(item.get("valor_global")))
    add("Valor de repasse", _fmt_money(item.get("valor_repasse")))
    if item.get("valor_contrapartida") is not None:
        out.append(("Valor de contrapartida", _fmt_money(item.get("valor_contrapartida"))))
    if item.get("dt_fim_vigencia"):
        out.append(("Final da Vigência", _fmt_dt(item["dt_fim_vigencia"])))
    if item.get("banco"):
        out.append(("Banco", item["banco"]))
    if item.get("agencia"):
        out.append(("Agência", item["agencia"]))
    if item.get("conta"):
        out.append(("Conta", item["conta"]))
    if item.get("saldo_bancario") is not None:
        saldo_txt = _fmt_money(item["saldo_bancario"])
        if item.get("dt_saldo"):
            saldo_txt += f" atualizado em {_fmt_dt(item['dt_saldo'])}"
        out.append(("Saldo Bancário", saldo_txt))
    # Situação atual (status do ciclo, ex.: "Em execução")
    if item.get("situacao_atual"):
        out.append(("Situação atual", item["situacao_atual"]))
    # Empenhado — nas VOLUNTÁRIAS do TransfereGov é "Sim"/"Não"/CALADO, derivado
    # em rm_builder._empenhado_rotulo. Nas demais fontes (FNS, SIGCON) ainda é o
    # ternário Sim/Não de sempre; `_campos_do_item` é compartilhado.
    # ⚠️ VAZIO É DE PROPÓSITO, NÃO É BUG. Na voluntária, "sem NE coletada" não
    # prova "não empenhado", e o flag detalhe->>'Empenhado' do portal erra nos
    # dois sentidos. Quando não há prova, a linha SOME. Não repor um "Não"
    # default aqui — o lugar de mudar a regra é o rm_builder.
    if item.get("empenhado"):
        out.append(("Empenhado", item["empenhado"]))
    # Situação do NEs — o documento, logo abaixo do Sim/Não que é inferência.
    # Só sai quando há nota de empenho REAL coletada: linha ausente não afirma
    # que não há empenho, porque proposta não consultada cai no mesmo vazio.
    if item.get("nes"):
        out.append(("Situação do NEs", item["nes"]))
    # VALOR EMPENHADO — o número que sustenta o "PENDENTE DE EMPENHO" que já sai
    # dentro da Situação atual.
    #
    # ⚠️ `is not None`, e NÃO o helper `add` nem um `if` simples: 0,0 aqui é
    # RESPOSTA ("a listagem foi consultada e não há empenho") e o `add` acima
    # trata 0 como vazio, o que apagaria justamente o caso que o dono pediu para
    # ver. Ausente (None) = nunca consultado -> a linha não sai, porque o
    # relatório não afirma o que ninguém mediu.
    #
    # ⚠️ LINHA PRÓPRIA, e não pendurada em `_clausula_destaque`: aquela aborta
    # com `if not _tem_clausula(item): return None`, e Termo de Compromisso sem
    # empenho tipicamente NÃO tem cláusula suspensiva — o texto nunca sairia, e
    # sairia calado (é o mesmo motivo de `_obra_destaque`).
    if item.get("valor_empenhado") is not None:
        _ve = _fmt_money(item["valor_empenhado"])
        if item.get("pendente_empenho"):
            _ve += " — PENDENTE DE EMPENHO (Termo de Compromisso sem nota de empenho)"
        out.append(("Valor empenhado", _ve))
    # Situação de Contratação "Normal" aparece como linha simples; Cláusula
    # Suspensiva / Liminar Judicial vão para a CAIXA DE DESTAQUE (_clausula_destaque),
    # então NÃO entram aqui.
    sc = (item.get("situacao_contratacao") or "")
    if sc and not _tem_clausula(item):
        out.append(("Situação de Contratação", sc))
    return out


def _tem_clausula(item: dict) -> bool:
    """True quando o item tem Cláusula Suspensiva / Liminar Judicial (merece destaque)."""
    sc = (item.get("situacao_contratacao") or "").lower()
    return ("clausula" in sc or "cláusula" in sc or "suspensiv" in sc or "liminar" in sc
            or bool(item.get("clausula_motivo")) or bool(item.get("clausula_dt")))


def _clausula_destaque(item: dict) -> str | None:
    """Texto (markup) da caixa de destaque da cláusula, ou None se não houver."""
    if not _tem_clausula(item):
        return None
    sc = item.get("situacao_contratacao") or "Cláusula Suspensiva"
    partes = [f"⚠ <b>Situação de Contratação:</b> {_escape(sc)}"]
    # Situacao do CONTRATO no TransfereGov (ex.: "Cláusula Suspensiva"), que vinha
    # so no JSONB do portal e nao era exibida.
    if item.get("situacao_contrato"):
        partes.append(f"<b>Situação atual do contrato:</b> {_escape(item['situacao_contrato'])}")
    if item.get("clausula_motivo"):
        partes.append(f"<b>Motivo:</b> {_escape(item['clausula_motivo'])}")
    # O motivo diz QUAL documento trava (ex.: "Termo de Referência"); esta linha
    # diz em que PÉ ele está no portal (ex.: "Em Análise"). Sem ela o relatório
    # apontava a pendência sem saber se o município já havia entregado o documento.
    if item.get("projeto_basico"):
        partes.append("<b>Projeto Básico/Termo de Referência:</b> "
                      + _escape(item["projeto_basico"]))
    if item.get("clausula_dt"):
        partes.append(f"<b>Data prevista para resolução:</b> {_escape(_fmt_dt(item['clausula_dt']))}")
    return "<br/>".join(partes)


def _obra_destaque(item: dict) -> str | None:
    """Caixa da OBRA: a frase de situação pronta, vinda do builder.

    ⚠️ FUNÇÃO PRÓPRIA, DE PROPÓSITO. A tentação é pendurar isto junto do Projeto
    Básico, dentro de `_clausula_destaque` — mas aquela função começa com
    `if not _tem_clausula(item): return None`. Obra em execução tipicamente NÃO
    tem cláusula suspensiva, então o texto nunca sairia, e sairia calado.

    Informativo (caixa cinza), não alerta: obra andando não pede ação. A
    pendência de ART/RRT vem no mesmo texto e é o próprio conteúdo que avisa."""
    txt = (item.get("obra") or "").strip()
    return f"<b>Obra:</b> {_escape(txt)}" if txt else None


def _desembolso_destaque(item: dict) -> str | None:
    """Caixa do DESEMBOLSO (OPs/OBs): o valor desembolsado e CADA lancamento
    (data · valor · nº da OB). Quando nada saiu e a licitacao ja foi aceita, o
    proprio `situacao_atual` ja diz PENDENTE DE DESEMBOLSO — aqui detalhamos.
    None quando o instrumento nao tem OPs/OBs coletadas."""
    vd = item.get("valor_desembolsado")
    va = item.get("valor_a_desembolsar")
    lanc = item.get("desembolsos") or []
    # ⚠️ `is None` NÃO BASTA. O coletor grava 0.0 (não None) quando a Listagem de
    # Repasses existe e está zerada — e 0.0 passava por esta guarda, fazendo o
    # relatório abrir uma caixa de desembolso "R$ 0,00" em voluntária que nunca
    # teve repasse. Só há o que dizer quando há LANÇAMENTO ou algum valor
    # diferente de zero (a desembolsar > 0 continua valendo: é repasse previsto
    # e ainda não pago, que é informação de verdade).
    if not lanc and not (vd or 0) and not (va or 0):
        return None
    partes = []
    cab = []
    if vd is not None:
        cab.append("<b>Desembolsado:</b> " + _escape(_fmt_money_br(vd)))
    if va:
        cab.append("<b>A desembolsar:</b> " + _escape(_fmt_money_br(va)))
    if cab:
        partes.append(" · ".join(cab))
    for l in lanc[:12]:
        if not isinstance(l, dict):
            continue
        linha = "• " + _escape(l.get("data") or "—")
        if l.get("valor") is not None:
            linha += " · " + _escape(_fmt_money_br(l.get("valor")))
        if l.get("numero_ob"):
            linha += " · OB " + _escape(str(l["numero_ob"]))
        if l.get("situacao"):
            linha += " · " + _escape(str(l["situacao"]))
        partes.append(linha)
    if len(lanc) > 12:
        partes.append(f"<i>(+{len(lanc) - 12} lançamento(s))</i>")
    return "<br/>".join(partes) if partes else None


def _fmt_money_br(v) -> str:
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return ""


def _evento_destaque(item: dict) -> str | None:
    """Caixa do EVENTO ATUAL (Histórico de Comunicações do TransfereGov): onde o
    instrumento está de fato na análise, com a SITUAÇÃO e as CONSIDERAÇÕES do
    concedente. None quando não há histórico capturado."""
    ev = (item.get("evento_atual") or "").strip()
    sit = (item.get("evento_situacao") or "").strip()
    cons = (item.get("evento_consideracoes") or "").strip()
    if not (ev or sit or cons):
        return None
    dt = (item.get("evento_data") or "").strip()
    cab = "<b>Evento atual:</b> " + _escape(ev or "-")
    if dt:
        cab += f" ({_escape(dt)})"
    partes = [cab]
    if sit:
        partes.append(f"<b>Situação:</b> {_escape(sit)}")
    if cons:
        partes.append(f"<b>Considerações:</b> {_escape(cons)}")
    return "<br/>".join(partes)


def _alteracao_destaque(item: dict) -> str | None:
    """Caixa da ULTIMA ALTERACAO do convenio ESTADUAL (SIGCON): onde o instrumento
    esta de fato (ex.: "ANALISE - CHECKLIST DE TERMO ADITIVO"), com tipo, titulo e
    data. E o equivalente estadual do _evento_destaque dos federais. None quando o
    scraper ainda nao capturou a alteracao daquele convenio."""
    sit = (item.get("alteracao_situacao") or "").strip()
    tipo = (item.get("alteracao_tipo") or "").strip()
    data = (item.get("alteracao_data") or "").strip()
    nr = (item.get("alteracao_nr_controle") or "").strip()
    tit0 = (item.get("alteracao_titulo") or "").strip()
    # Captura PARCIAL tambem vale: sem a situacao, o tipo/data/titulo ja informam.
    if not (sit or tipo or data or nr or tit0):
        return None
    partes = ["<b>Última alteração:</b> " + _escape(sit or tipo or "(sem situação informada)")]
    cab = " · ".join(x for x in (
        # nao repete o tipo quando ele ja virou o cabecalho (captura sem situacao)
        _escape(tipo) if (tipo and sit) else "",
        ("nº " + _escape(nr)) if nr else "",
        _escape(data) if data else "",
    ) if x)
    if cab:
        partes.append(cab)
    if tit0:
        partes.append("<b>Título:</b> " + _escape(tit0))
    return "<br/>".join(partes)


def _proc_exec_lista(item: dict) -> list:
    """A lista de licitações/processos do item, tolerando JSONB vindo como str
    (dependendo do driver) ou já parseado. Sempre devolve uma lista (vazia se n/a)."""
    lst = item.get("processo_execucao_lista")
    if isinstance(lst, str):
        try:
            lst = json.loads(lst)
        except (ValueError, TypeError):
            lst = None
    return lst if isinstance(lst, list) else []


def _processo_execucao_destaque(item: dict) -> str | None:
    """Destaque p/ convênio com contratação Normal e o Processo de Execução
    (Licitações): 0 = sem processo/licitação iniciado (flag de monitoramento);
    N = registros. Quando há a LISTA capturada, imprime CADA licitação com
    situação/modalidade/nº/data — não só a contagem. None quando não se aplica
    (não-Normal ou não capturado)."""
    qtd = item.get("processo_execucao_qtd")
    sc = (item.get("situacao_contratacao") or "").lower()
    if qtd is None or "normal" not in sc:
        return None
    if qtd == 0:
        return ("⚠ <b>Licitação:</b> nenhum registro "
                "(contratação Normal, sem licitação iniciada)")
    partes = [f"<b>Licitação:</b> {qtd} registro(s)"]
    # Detalhe por licitação — mesmo formato da tela (situação em negrito, depois
    # modalidade · nº · data · sistema · aceite). Só aparece quando o scraper
    # trouxe a lista; senão fica só a contagem (degrada suave).
    for pe in _proc_exec_lista(item):
        if not isinstance(pe, dict):
            continue
        extra = []
        if pe.get("modalidade"):
            extra.append(_escape(str(pe["modalidade"])))
        if pe.get("numero"):
            extra.append("nº " + _escape(str(pe["numero"])))
        if pe.get("data_publicacao"):
            extra.append(_escape(str(pe["data_publicacao"])))
        if pe.get("sistema_origem"):
            extra.append(_escape(str(pe["sistema_origem"])))
        if pe.get("aceite"):
            extra.append(_escape(str(pe["aceite"])))
        linha = "• <b>" + _escape(str(pe.get("situacao") or "—")) + "</b>"
        if extra:
            linha += " · " + " · ".join(extra)
        partes.append(linha)
    return "<br/>".join(partes)


def _escape(s: str) -> str:
    """Escape p/ Paragraph: &, <, > viram entidades."""
    if not isinstance(s, str):
        s = str(s) if s is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def roteiro_rm(meta: dict, conteudo: dict, municipio_nome: str):
    """O RM inteiro como uma SEQUENCIA DE EVENTOS, sem uma linha de ReportLab.

    ⚠️ E A UNICA FONTE DE VERDADE DA APRESENTACAO DO RM: `gerar_pdf` (abaixo) e
    `services/rm_docx.gerar_docx_rm` sao dois CONSUMIDORES — nenhum dos dois
    decide o que aparece nem em que ordem, so COMO aquilo e desenhado. Caixa
    nova, campo novo ou mudanca de ordem entram AQUI e saem nos dois formatos de
    graca; escrever a mesma regra duas vezes e exatamente como o Word e o PDF
    passariam a divergir em silencio (nao ha teste que renderize nenhum dos dois).

    ⚠️ NAO e a fonte de verdade do CONTEUDO. O conteudo e montado por
    `services/rm_builder.montar_conteudo` e CONGELADO em `rm_relatorios.conteudo`
    (routers/rm.py) no momento em que o relatorio e gerado. Campo novo exige as
    tres coisas: o builder passar a produzi-lo, `_campos_do_item` passar a le-lo,
    e cada RM ja emitido ser reprocessado com Auto-popular — senao relatorio
    antigo e novo tem contratos de campo diferentes, sem erro nenhum.

    Eventos, na forma (tipo, dado):
      ("titulo",     str)               titulo principal — texto CRU, sem escape
      ("local_data", str)               linha cidade/data — CRU
      ("consultas",  str)               "Consultas incluídas: ..." — CRU; só sai
                                        quando HÁ recorte de consultas
      ("quebra",     None)              quebra de pagina; NAO vem antes da 1a parte
      ("parte",      str)               CRU
      ("secao",      str)               CRU
      ("grupo",      str)               nome do orgao, CRU e SEM o glifo `●`
      ("item",       str)               identificador do instrumento, CRU (ABRE o item)
      ("campo",      (label, valor))    ambos CRUS, sem escape e sem o glifo `➢`
      ("caixa",      (markup, estilo))  markup JA ESCAPADO, com <b>/<i>/<br/>;
                                        estilo = "clausula" (ambar) | "informativo" (cinza)
      ("fim_item",   None)              FECHA o item aberto
      ("vazio",      str)               frase do relatorio sem conteudo, CRU

    ⚠️ A ASSIMETRIA DE ESCAPE E PROPOSITAL e vem do codigo antigo: `campo` sai CRU
    (quem escapa e o renderizador) e `caixa` sai JA ESCAPADA (as funcoes
    `_*_destaque` escapam e embutem as tags). Reescapar uma caixa mostra `&lt;b&gt;`
    no documento; imprimir uma caixa como texto puro mostra `<b>` literal.
    """
    titulo = meta.get("titulo") or f"RELATÓRIO DE MONITORAMENTO – {municipio_nome.upper()}"
    yield ("titulo", titulo)
    cidade = meta.get("cidade_emissao") or ""   # ver nota em rm_export.py
    if meta.get("escopo") in ("completo", "parcial"):
        # RM por SELECAO de anos (padrao Freitas): nao ha um exercicio unico. Linha
        # local + data por extenso, como a referencia ("Brasília/DF, 29 de Julho de 2026").
        _de = _data_extenso(meta.get("data_referencia"))
        linha = f"{cidade}, {_de}".strip(", ") if _de else cidade
    else:
        # RM ANUAL: a linha local/data mostra o EXERCÍCIO (ano de emissão).
        _dr = str(meta.get("data_referencia") or "")
        _ano = _dr[:4] if len(_dr) >= 4 and _dr[:4].isdigit() else ""
        linha = f"{cidade} — Relatório referente ao exercício de {_ano}" if _ano else cidade
    yield ("local_data", linha)
    # CONSULTAS INCLUIDAS — so quando HA recorte. `rotulo_longo([])` devolve "",
    # entao o RM completo nao emite este evento e a pagina continua a de hoje.
    #
    # ⚠️ E EVENTO DO ROTEIRO, e nao um `append` no PDF: sem isto o .docx de um RM
    # FILTRADO sairia visualmente identico ao do completo. E o motivo de o roteiro
    # existir — regra de apresentacao mora aqui e sai nos dois formatos.
    #
    # ⚠️ Sem esta linha, quem recebe o documento IMPRESSO nao tem como saber que
    # aquele relatorio NAO cobre o municipio inteiro — e um relatorio de
    # monitoramento que parece completo e nao e vale menos que nenhum.
    _fontes_txt = rotulo_longo(meta.get("fontes") or [])
    if _fontes_txt:
        yield ("consultas", f"Consultas incluídas: {_fontes_txt}")

    for p_idx, parte in enumerate(conteudo.get("partes", [])):
        if p_idx > 0:
            yield ("quebra", None)
        yield ("parte", parte.get("titulo", ""))
        for secao in parte.get("secoes", []):
            yield ("secao", secao.get("titulo", ""))
            for grupo in secao.get("grupos", []):
                yield ("grupo", grupo.get("orgao", ""))
                for item in grupo.get("itens", []):
                    tipo = item.get("tipo", "")
                    numero = item.get("numero", "")
                    yield ("item", f"{tipo}: {numero}".strip(": ").strip())
                    for label, val in _campos_do_item(item):
                        yield ("campo", (label, val))
                    # ⚠️ A ORDEM DAS SEIS CAIXAS E CONTRATO: e nesta ordem que elas
                    # saem no PDF desde sempre e e nesta ordem que o dono confere o
                    # documento. Mexer aqui mexe nos dois formatos de uma vez — que
                    # e justamente a razao de existir desta funcao.
                    # Caixa de DESTAQUE p/ Cláusula Suspensiva / Liminar Judicial
                    destaque = _clausula_destaque(item)
                    if destaque:
                        yield ("caixa", (destaque, "clausula"))
                    # Licitacao: AMBAR so quando e alerta (contratacao Normal com
                    # ZERO licitacao). Com licitacoes registradas e informativo.
                    destaque_pe = _processo_execucao_destaque(item)
                    if destaque_pe:
                        _alerta_pe = item.get("processo_execucao_qtd") == 0
                        yield ("caixa", (destaque_pe, "clausula" if _alerta_pe else "informativo"))
                    destaque_ev = _evento_destaque(item)
                    if destaque_ev:
                        yield ("caixa", (destaque_ev, "informativo"))
                    # Estadual (SIGCON): a ultima alteracao e o "evento atual" dele.
                    destaque_alt = _alteracao_destaque(item)
                    if destaque_alt:
                        yield ("caixa", (destaque_alt, "informativo"))
                    # Desembolso (OPs/OBs): valor + lançamentos.
                    destaque_des = _desembolso_destaque(item)
                    if destaque_des:
                        yield ("caixa", (destaque_des, "informativo"))
                    # OBRA — bloco PRÓPRIO, e não dentro da caixa da cláusula.
                    # Pendurá-lo lá o faria passar por `_tem_clausula`, que aborta
                    # quando não há cláusula suspensiva: obra com 93,70% executado
                    # tipicamente NÃO tem cláusula, e o texto nunca sairia — calado.
                    destaque_obra = _obra_destaque(item)
                    if destaque_obra:
                        yield ("caixa", (destaque_obra, "informativo"))
                    yield ("fim_item", None)

    if not conteudo.get("partes"):
        yield ("vazio", _TXT_VAZIO)


def gerar_pdf(meta: dict, conteudo: dict, municipio_nome: str) -> bytes:
    """Gera bytes do PDF.

    Args:
        meta: {data_referencia, cidade_emissao, titulo (opt), rodape,
               escopo ('completo'|'parcial'|'anual' — troca o cabecalho),
               fontes (lista de consultas; vazio = todas, e ai nao sai linha
               nenhuma a mais e o documento e identico ao de hoje)}
        conteudo: {partes: [{ordem, titulo, secoes: [{ordem, titulo, grupos:
                  [{ordem, orgao, itens: [...]}]}]}]}
        municipio_nome: para o titulo

    ⚠️ NAO decide conteudo nem ordem: e um CONSUMIDOR de `roteiro_rm`. Tudo o que
    este corpo faz e traduzir cada evento para ReportLab. Regra nova vai no
    roteiro, senao ela sai no PDF e nao sai no Word.
    """
    buf = io.BytesIO()
    rodape_txt = meta.get("rodape", "")
    # ⚠️ `meta.get("email") or ""` e nao `meta.get("email", "")`: o carimbo da
    # linha e NULL em todo relatorio gerado ANTES de o campo existir, e o
    # default do `get` so vale quando a chave esta AUSENTE — com a chave
    # presente valendo None, `drawRightString` escreveria "None" no cabecalho.
    email_txt = meta.get("email") or ""
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=_MARGENS_CM[2] * cm, rightMargin=_MARGENS_CM[3] * cm,
        topMargin=_MARGENS_CM[0] * cm, bottomMargin=_MARGENS_CM[1] * cm,
        title=f"RM - {municipio_nome}",
    )
    s = _styles()
    story = []
    bloco: list = []          # o item em construcao, despejado no ("fim_item")

    for evento, dado in roteiro_rm(meta, conteudo, municipio_nome):
        if evento == "titulo":
            story.append(Paragraph(_escape(dado), s["titulo_principal"]))
        elif evento == "local_data":
            story.append(Paragraph(_escape(dado), s["data_local"]))
        elif evento == "consultas":
            # Mesmo estilo da linha de cima, para as duas ficarem no mesmo bloco
            # de cabecalho.
            story.append(Paragraph(_escape(dado), s["data_local"]))
        elif evento == "quebra":
            story.append(PageBreak())
        elif evento == "parte":
            story.append(Paragraph(_escape(dado), s["parte_titulo"]))
        elif evento == "secao":
            story.append(Paragraph(_escape(dado), s["secao_titulo"]))
        elif evento == "grupo":
            story.append(Paragraph(f"{_GLIFO_GRUPO} {_escape(dado)}", s["grupo_titulo"]))
        elif evento == "item":
            bloco = [Paragraph(_escape(dado), s["item_id"])]
        elif evento == "campo":
            label, val = dado
            bloco.append(Paragraph(
                f"{_GLIFO_CAMPO} <b>{_escape(label)}:</b> {_escape(str(val))}",
                s["item_campo"],
            ))
        elif evento == "caixa":
            markup, estilo = dado
            bloco.append(Spacer(1, 2))
            bloco.append(Paragraph(markup, s[estilo]))
        elif evento == "fim_item":
            bloco.append(Spacer(1, 4))
            # ⚠️ KeepTogether SÓ NO CABEÇALHO DO ITEM, não no bloco todo.
            #
            # Embrulhar o item inteiro fazia o ReportLab empurrar TUDO para a
            # página seguinte quando não coubesse — e sobrava meia página em
            # branco. O efeito ficou visível depois que a entrelinha 1,5 e a
            # margem de topo de 4,5 cm (padrão Freitas) engordaram cada bloco:
            # o que antes cabia, passou a não caber.
            #
            # Mantendo junto só o identificador e os dois primeiros campos, o
            # item nunca fica órfão do próprio título, mas pode QUEBRAR entre
            # páginas em vez de deixar buraco.
            story.append(KeepTogether(bloco[:3]))
            story.extend(bloco[3:])
            bloco = []
        elif evento == "vazio":
            story.append(Paragraph(f"<i>{_escape(dado)}</i>", s["item_campo"]))

    doc.build(
        story,
        onFirstPage=lambda c, d: _on_page(c, d, rodape_txt, email_txt),
        onLaterPages=lambda c, d: _on_page(c, d, rodape_txt, email_txt),
    )
    return buf.getvalue()
