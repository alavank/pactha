"""Export PDF: Convenios SIGCON-MG, Emendas Estaduais, Diario Oficial MG."""
import re
import html
import unicodedata
from io import BytesIO
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Body, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, or_
from database import get_db
from models import ConvenioEstadual, Municipio
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.audit import registrar
from services.bi import anos_list

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
                                KeepTogether, PageBreak)
from services import authz
from services.registro_rotas import exige, declarado
# O recorte da tela de Convênios e a montagem de linha dos três formatos.
from services import convenios_filtro as filtro
from services import convenios_export as cexp

router = APIRouter(prefix="/api/export-pdf", tags=["export-pdf"])


# ---------------------------------------------------------------------------
# Trilha de EXPORTACAO
#
# Este router inteiro produz arquivo que sai da plataforma — e, para a LGPD, o
# evento mais importante de rastrear, porque e o unico momento em que o dado
# deixa de estar sob controle do sistema. Todos os eventos ficam sob o prefixo
# `export.`: um filtro so ("action comeca com export.") lista tudo que ja saiu,
# venha do RM, dos Documentos, de um anexo ou daqui.
#
# ⚠️ `export.*` NAO e acao critica: `services/audit.py::ACOES_CRITICAS` promove
# apenas `control.sso.mint` e os `*.reveal`. Aqui a porta e `registrar` (melhor
# esforco) DE PROPOSITO — o PDF e leitura do que o usuario ja tem na tela, e
# bloquear o download porque o INSERT da trilha falhou nao impede exfiltracao
# nenhuma (ele fotografa a tela): so quebra o trabalho de quem nao fez nada de
# errado. Falha de gravacao aparece no log da aplicacao (`logger.exception`),
# nao em silencio.
#
# Ainda assim a chamada fica sempre ANTES do `return`, e isso importa por dois
# motivos que nao dependem de ser critica: depois do `return` ela simplesmente
# nao roda, e e daqui que sai a decisao se um dia o dono quiser fail-closed —
# bastaria trocar por `registrar_critico`, sem mexer na ordem. Quem precisa de
# fail-closed hoje chama a porta critica pelo nome, como faz a exportacao da
# PROPRIA trilha (routers/auditoria.py).
# ---------------------------------------------------------------------------
async def _registrar_export(
    db: AsyncSession, *, request: Request, current: User, tipo: str,
    municipio_id=None, filtros: dict | None = None, registros: int | None = None,
    arquivo: str | None = None,
):
    """Um registro por arquivo gerado.

    `filtros` guarda o RECORTE (parlamentar, vigencia, busca...): sem ele o
    registro diria apenas "exportou convenios", quando o que importa e "exportou
    os convenios do deputado X com vigencia vencendo". Valores vazios sao
    descartados para o modal nao virar uma lista de nulos."""
    await registrar(
        db, action=f"export.{tipo}", user=current, request=request,
        target_type="export", target_id=tipo, alvo_nome=arquivo,
        municipio_id=municipio_id,
        details={
            "formato": "pdf",
            "registros": registros,
            "arquivo": arquivo,
            "filtros": {k: v for k, v in (filtros or {}).items() if v not in (None, "", [])} or None,
        },
    )


# ---------------------------------------------------------------------------
# PORTA DE TELA
#
# Este router e uma SEGUNDA PORTA para dado que ja tem dono: cada PDF daqui e o
# conteudo de uma tela do sistema, so que em arquivo. Ate agora eles checavam o
# MUNICIPIO e mais nada — entao tirar a tela "SIGCON (Estaduais)" de alguem na
# tela de Usuarios nao impedia o relatorio de convenios sair inteiro por
# `/api/export-pdf/convenios`. Permissao que vale numa porta e nao vale na outra
# nao e permissao: e a aparencia de uma.
#
# O par (endpoint -> tela) e o MESMO do router que serve a tela, nunca uma chave
# nova. Quem ja podia VER e quem podia BAIXAR sao a mesma pessoa; inventar aqui
# uma chave propria criaria uma permissao que nenhum administrador concedeu e
# tiraria o PDF de quem sempre o teve. Por isso `/voluntarias` e `/plano-acao`
# pedem "transferegov" (as duas telas moram em routers/transferegov.py) e nao
# chaves com o nome da rota.
#
# ⚠️ HOJE ISTO NAO BARRA NINGUEM. Com AUTHZ_MODO=aviso (o default) `ensure_tela`
# apenas registra na trilha "eu teria negado isto, para este usuario, neste
# endpoint" e deixa passar — ver `services/authz.py`. O comportamento de todos
# os endpoints abaixo continua identico ao de ontem, inclusive o arquivo gerado.
# Quem fecha a porta e `AUTHZ_MODO=bloqueio`, depois da semana de observacao em
# que o dono corrige a permissao de quem precisa.
#
# A ordem e `ensure_municipio_access` e so depois `ensure_tela`, igual ao resto
# do repo (convenios.py, emendas_estaduais.py, transferegov.py): assim, no dia
# do bloqueio, a mensagem que sai daqui e a mesma que a tela ja devolvia aquele
# mesmo usuario — e nao duas explicacoes diferentes para o mesmo impedimento.
#
# ⭐ E A PERMISSAO DECLARADA E `<recurso>.exportar`, NAO `.ver` — o que NAO
# contradiz o paragrafo acima. A TELA continua sendo a mesma do router que serve
# a pagina (nenhuma chave de tela nova); o que muda e o VERBO, e "Exportar" e uma
# caixinha que ja existe no catalogo, separada de "Ver", justamente porque baixar
# nao e ler: o arquivo sai da plataforma e deixa de estar sob controle dela — o
# mesmo motivo pelo qual todo endpoint daqui grava linha na trilha. Quem hoje
# baixa e nao tiver a caixinha "Exportar" marcada aparece na trilha durante a
# semana de observacao, que e exatamente para isso que o modo aviso existe.
# ---------------------------------------------------------------------------


def _br(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if isinstance(v, (date, datetime)):
        return v.strftime("%d/%m/%Y")
    return str(v)


def _build_pdf(title: str, subtitle: str, headers: list, rows: list, landscape_mode: bool = True) -> BytesIO:
    buf = BytesIO()
    page = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(buf, pagesize=page,
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"],
                                 fontSize=14, textColor=colors.HexColor("#1e40af"),
                                 spaceAfter=4)
    sub_style = ParagraphStyle("Sub", parent=styles["Normal"],
                               fontSize=9, textColor=colors.HexColor("#475569"),
                               spaceAfter=8)
    story = [Paragraph(title, title_style), Paragraph(subtitle, sub_style), Spacer(1, 4)]

    # Wrap header + rows
    data = [headers] + rows
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | Total: {len(rows)} registros | PACTHA - Plataforma de Acompanhamento",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#64748b"), alignment=2)))
    doc.build(story)
    buf.seek(0)
    return buf


# ⚠️ O MESMO TETO DA TELA (`PER_PAGE = 2000` em app/dashboard/convenios/page.tsx:37,
# que carrega tudo numa página só). Um teto MAIOR aqui reproduziria a assinatura
# exata do defeito histórico — 2.000 na tela e 3.500 no arquivo — e seria
# indistinguível dele para quem lê. Passando disso, o documento diz que foi
# truncado, em vez de fingir completude.
MAX_EXPORT_CONVENIOS = 2000


@router.get("/convenios", dependencies=[exige("convenios.exportar")])
async def export_convenios_pdf(
    request: Request,
    municipio_id: int = Query(...),
    # ⚠️ OS MESMOS FILTROS DA TELA, COM OS MESMOS NOMES E OS MESMOS TIPOS.
    #
    # Esta rota aceitava SÓ `municipio_id`, e por isso o documento saía com a
    # base inteira mesmo com "Em vigor" marcado — o dono relatou em 03/09/2026.
    # Não era filtro perdido no caminho: ele nunca era enviado, e a rota não
    # saberia o que fazer com ele. Vale o aviso que já está em
    # `export_voluntarias_pdf`, logo abaixo: parâmetro não declarado é
    # simplesmente IGNORADO pelo FastAPI, sem erro nenhum.
    #
    # ⚠️ OS TIPOS IMPORTAM. `anos` é list[int] (a coluna é INT) e as datas são
    # `date`; declarar como str manda bind de texto para o asyncpg e o resultado
    # é 500 seco ou comparação diferente, sem nada na tela. E toda lista precisa
    # de `Query(...)` explícito, senão o FastAPI a interpreta como corpo e o GET
    # vira 422. `tests/test_convenios_filtro.py` compara esta assinatura com a de
    # `list_convenios`, campo a campo, para que a divergência não volte.
    ano: Optional[int] = None,
    anos: Optional[list[int]] = Query(None),
    situacao: Optional[str] = None,
    situacoes: Optional[list[str]] = Query(None),
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None),
    vigencia: Optional[str] = Query(None),
    vigencias: Optional[list[str]] = Query(None),
    pagamento: Optional[str] = Query(None),
    pagamentos: Optional[list[str]] = Query(None),
    vig_fim_de: Optional[date] = Query(None),
    vig_fim_ate: Optional[date] = Query(None),
    search: Optional[str] = None,
    formato: str = Query("pdf", pattern="^(pdf|docx|xlsx)$"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    authz.exigir_tela(current, "convenios")
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")

    # ⚠️ O RECORTE VEM DO SERVICE — a MESMA função que a tela usa.
    #
    # Aqui morava a QUINTA cópia do predicado, e o comentário dela pedia
    # exatamente isto: "Unificar num helper e o conserto de raiz; esta copia
    # estanca hoje". O histórico que aquelas cópias produziram: Goiânia com 139
    # "convênios SIGCON-MG" que eram propostas federais de saúde, num estado que
    # o SIGCON-MG nem cobre; Monte Sião com 81 na tela e 129 no PDF; e 22
    # municípios do Freitas com PDF inteiramente fabricado ao lado de uma tela
    # corretamente vazia.
    conds, recorte = filtro.condicoes(
        municipio_id=municipio_id, ano=ano, anos=anos,
        situacao=situacao, situacoes=situacoes,
        fonte=fonte, fontes=fontes,
        vigencia=vigencia, vigencias=vigencias,
        pagamento=pagamento, pagamentos=pagamentos,
        vig_fim_de=vig_fim_de, vig_fim_ate=vig_fim_ate,
        search=search,
    )
    q = select(ConvenioEstadual)
    for c in conds:
        q = q.where(c)
    # ⚠️ A MESMA ORDEM da tela, e `+1` para saber se truncou sem uma segunda
    # consulta de contagem.
    q = q.order_by(filtro.ordem()).limit(MAX_EXPORT_CONVENIOS + 1)
    convs = list((await db.execute(q)).scalars().all())
    truncado = len(convs) > MAX_EXPORT_CONVENIOS
    if truncado:
        convs = convs[:MAX_EXPORT_CONVENIOS]
    # PAGAMENTO (ultimo desembolso) + EMPENHO por convenio — as MESMAS fontes do
    # RM para o estadual: `transparencia_mg_empenhos` (Portal da Transparencia de
    # MG, com data/OB) e, para a DATA DO EMPENHO onde o Joomla nao tem o convenio,
    # `segov_convenios_empenhos` (dado aberto da SEGOV, 15/09/2026). Reusa as
    # funcoes do rm_builder para nao duplicar a regra (uma consulta so p/ o
    # municipio, nao N+1). `pagamentos` prova a medicao; `dt_empenho` (a mais
    # recente) e a data de empenho. Tabela ausente ou tenant nao-MG => mapa vazio
    # e as colunas saem "-".
    mg_por_conv: dict[int, dict] = {}
    try:
        from services.rm_builder import _mg_pagamentos, _desembolso_ops_obs
        _pgs: dict[int, list] = {}
        _emp: dict[int, object] = {}
        for _cid, _pg, _dte in (await db.execute(text(
            "SELECT convenio_id, pagamentos, dt_empenho FROM transparencia_mg_empenhos "
            "WHERE municipio_id = :mid AND convenio_id IS NOT NULL"
        ), {"mid": municipio_id})).all():
            if _pg is not None:
                _pgs.setdefault(_cid, []).append(_pg)
            if _dte and (_cid not in _emp or _dte > _emp[_cid]):
                _emp[_cid] = _dte
        # DATA DO EMPENHO pela SEGOV onde o Joomla nao tem o convenio. Em
        # producao o Joomla da 403 na VPS e `_emp` sai vazio, enquanto o RM ja
        # imprime "NE 310/2026 — empenhado em 05/03/2026" da SEGOV — os dois
        # papeis do mesmo dia divergiam ("Data de empenho: -" aqui). SO a data
        # do empenho: o CSV nao tem data de pagamento, e `dt_pagamento` segue
        # "-" com honestidade. Try proprio: tenant sem a tabela segue.
        try:
            for _cid, _dte in (await db.execute(text(
                "SELECT convenio_id, max(dt_empenho) FROM segov_convenios_empenhos "
                "WHERE municipio_id = :mid AND convenio_id IS NOT NULL GROUP BY convenio_id"
            ), {"mid": municipio_id})).all():
                if _dte and _cid not in _emp:
                    _emp[_cid] = _dte
        except Exception:
            pass
        for _cid in set(_pgs) | set(_emp):
            _des = _desembolso_ops_obs(_mg_pagamentos(_pgs.get(_cid))) if _pgs.get(_cid) else {}
            # dt_ultimo_desembolso vem em dd/mm/aaaa (string) — vira date p/ o
            # arquivo formatar igual às outras datas.
            _dtp = _des.get("dt_ultimo_desembolso")
            _dtp_date = None
            if _dtp:
                try:
                    _dtp_date = datetime.strptime(str(_dtp)[:10], "%d/%m/%Y").date()
                except ValueError:
                    _dtp_date = None
            mg_por_conv[_cid] = {"dt_pagamento": _dtp_date, "dt_empenho": _emp.get(_cid)}
    except Exception as e:
        # Nunca derruba o export por causa da coluna nova: sem os dados de MG, as
        # duas colunas simplesmente saem vazias (mesma disciplina do resto).
        mg_por_conv = {}

    # ⚠️ UMA SÓ MONTAGEM DE LINHA para os três formatos (`convenios_export`).
    # Se o PDF montasse a linha aqui e o Excel montasse a dele lá, o gestor que
    # exportasse nos dois encontraria conteúdos diferentes — e a divergência
    # nasceria exatamente como a do filtro nasceu.
    linhas = [cexp.linha_de(c, mg=mg_por_conv.get(c.id)) for c in convs]
    rows = [[
        (l["fonte"])[:8],
        l["proposta"][:14] or "-",
        l["plano"][:10] or "-",
        l["instrumento"][:14] or "-",
        l["orgao"][:15],
        Paragraph(l["objeto"][:120], ParagraphStyle("o", fontSize=7)),
        l["situacao"][:18],
        _br(l["repasse"]),
        _br(l["assinatura"]),
        _br(l["vigencia"]),
        # Dias p/ fim da vigencia — mesma formatacao do Excel/Word (cexp), p/ os
        # tres formatos mostrarem o mesmo valor.
        cexp.dias_vigencia_txt(l["dias_vigencia"]),
        _br(l["dt_pagamento"]),
        _br(l["dt_empenho"]),
    ] for l in linhas]
    # O titulo nao pode mais cravar "SIGCON-MG": o produto e vendido em MG, ES,
    # GO e TO, e emitir "Convenios SIGCON-MG — Goiania/GO" e afirmar que o dado
    # veio de um sistema que nao atende aquele estado. Espelha o mapa que o
    # frontend ja usa (lib/estadual.ts::FONTE_CONVENIOS_ESTADUAIS).
    _fonte_uf = {"MG": "SIGCON-MG", "ES": "GConv · SEGER"}.get((mun.uf or "").upper())
    _titulo = (f"Convênios Estaduais ({_fonte_uf}) - {mun.nome}/{mun.uf}" if _fonte_uf
               else f"Convênios Estaduais - {mun.nome}/{mun.uf}")
    # Vazio ganha frase, nao tabela so com cabecalho: 38 municipios caem neste
    # caso, e uma folha em branco le-se como "o municipio nao tem convenio",
    # que e diferente de "a fonte estadual deste estado ainda nao esta ligada".
    # ⚠️ VAZIO FILTRADO ≠ VAZIO SEM DADO. Antes só havia duas frases possíveis;
    # agora o documento pode sair vazio porque o FILTRO não casou nada, e dizer
    # "nenhum convênio coletado para este município" nesse caso seria acusar a
    # coleta por uma escolha de quem exportou.
    if convs:
        _sub = f"{len(convs)} convênio(s) estadual(is)"
    elif recorte:
        _sub = "nenhum convênio atende aos filtros aplicados"
    elif _fonte_uf:
        _sub = "nenhum convênio estadual coletado para este município"
    else:
        _sub = "a fonte estadual deste estado ainda não está integrada ao PACTHA"
    if recorte:
        _sub += " · " + "; ".join(recorte)
    if truncado:
        _sub += (f" · ⚠️ o filtro tem mais de {MAX_EXPORT_CONVENIOS} registros; "
                 f"este documento traz os {len(convs)} primeiros")

    agora = datetime.now()
    base_nome = f"convenios_{mun.nome.replace(' ', '_')}"
    if formato == "xlsx":
        conteudo = cexp.gerar_xlsx(
            linhas, titulo=_titulo, recorte=recorte, emitido_em=agora,
            truncado_em=MAX_EXPORT_CONVENIOS if truncado else None)
        nome_arq = f"{base_nome}.xlsx"
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        corpo = BytesIO(conteudo)
    elif formato == "docx":
        conteudo = cexp.gerar_docx(
            linhas, titulo=_titulo, subtitulo=_sub, recorte=recorte, emitido_em=agora,
            truncado_em=MAX_EXPORT_CONVENIOS if truncado else None)
        nome_arq = f"{base_nome}.docx"
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        corpo = BytesIO(conteudo)
    else:
        corpo = _build_pdf(
            _titulo,
            _sub,
            ["Fonte", "Proposta", "Plano", "Instrumento", "Órgão", "Objeto", "Situação", "Repasse", "Assinatura", "Vigência", "Dias p/ fim vig.", "Data pgto", "Data empenho"],
            rows,
        )
        nome_arq = f"{base_nome}.pdf"
        mime = "application/pdf"

    # ⚠️ A TRILHA REGISTRA O RECORTE, e não só o município. Um export auditado
    # como "convenios · Monte Sião" não permite reconstruir o que saiu no papel:
    # a mesma linha de auditoria descreveria a base inteira e um único convênio.
    await _registrar_export(db, request=request, current=current, tipo="convenios",
                            municipio_id=municipio_id, registros=len(convs),
                            arquivo=nome_arq,
                            filtros={"municipio": f"{mun.nome}/{mun.uf}",
                                     "formato": formato,
                                     "recorte": recorte or ["(sem filtro)"],
                                     "truncado": truncado})
    return StreamingResponse(corpo, media_type=mime,
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"})


# ⭐ A CATEGORIA SUBIU PARA O CAMINHO, pelo mesmo motivo da rota de listagem em
# `routers/transferegov.py`: as quatro telas de FEDERAIS que dividem este export
# viraram quatro permissoes, e categoria em QUERY nao gateia nada — quem tivesse
# so «Rejeitadas» pediria `?categoria=geral` e levaria o PDF da outra tela.
_TELA_POR_CATEGORIA_EXPORT: dict[str, str] = {
    "geral": "transferegov_geral",
    "voluntarias": "transferegov_voluntarias",
    "rejeitadas": "transferegov_rejeitadas",
    "encerradas": "transferegov_encerradas",
}
_CATEGORIA_EXPORT_PERMISSOES: tuple = tuple(
    f"{t}.exportar" for t in _TELA_POR_CATEGORIA_EXPORT.values())


@router.get("/federais/{categoria}",
            dependencies=[declarado(*_CATEGORIA_EXPORT_PERMISSOES)])
async def export_voluntarias_pdf(
    request: Request,
    categoria: str,
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    orgao: Optional[str] = Query(None),
    # Os mesmos campos separados da tela (routers/transferegov.py). Sem isto o
    # "Gerar PDF (filtrado)" sairia com um recorte DIFERENTE do que está na tela —
    # o pior defeito possível num relatório, porque nada avisa: parâmetro não
    # declarado é simplesmente IGNORADO pelo FastAPI.
    instrumento: Optional[str] = Query(None),
    proposta: Optional[str] = Query(None),
    proponente: Optional[str] = Query(None),
    cnpj: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    parlamentar: Optional[str] = Query(None),
    situacao_contratacao: Optional[str] = Query(None),
    vigencia: Optional[str] = Query(None),
    vig_fim_de: Optional[str] = Query(None),
    vig_fim_ate: Optional[str] = Query(None),
    # Quem recebe (15/09/2026): prefeitura | outros. Declarado pelo mesmo motivo
    # do aviso acima — sem ele o PDF ignoraria o filtro da tela calado.
    recebedor: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF dos instrumentos FEDERAIS (TransfereGov) com os MESMOS filtros da tela —
    relatorio personalizado da selecao (parlamentar, vigencia, situacao, etc.)."""
    ensure_municipio_access(current, municipio_id)
    # A tela e A DA CATEGORIA PEDIDA, lida do caminho. O `_voluntarias` reusado
    # abaixo tambem chama `ensure_tela`, mas com o `current` que RECEBE — e ele
    # recebe `_=None`, nao o usuario. A unica checagem que realmente corre neste
    # caminho e esta.
    _tela_export = _TELA_POR_CATEGORIA_EXPORT.get((categoria or "").strip().lower())
    if not _tela_export:
        raise HTTPException(404, "Categoria desconhecida")
    authz.exigir(current, f"{_tela_export}.exportar")
    authz.exigir_tela(current, _tela_export)
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")
    # Reusa a mesma logica de filtro do endpoint da tela
    from routers.transferegov import voluntarias as _voluntarias
    res = await _voluntarias(
        municipio_id=municipio_id, situacao=situacao, orgao=orgao, search=search,
        instrumento=instrumento, proposta=proposta, proponente=proponente, cnpj=cnpj,
        parlamentar=parlamentar, situacao_contratacao=situacao_contratacao,
        vigencia=vigencia, vig_fim_de=vig_fim_de, vig_fim_ate=vig_fim_ate,
        recebedor=recebedor,
        # ⚠️ `current=current` E NAO `_=None` — o botao "Gerar PDF" desta tela
        # ficou QUEBRADO por semanas por causa disto. O parametro do handler
        # reusado foi renomeado de `_` para `current` no trabalho de RBAC (as
        # 182 rotas declarando permissao) e este arquivo ficou para tras:
        # `TypeError: voluntarias() got an unexpected keyword argument '_'` ->
        # 500 seco. Como o frontend engolia o erro no catch, o gestor clicava e
        # NADA acontecia — sem PDF e sem aviso.
        # Passar o usuario de verdade tambem fecha o buraco que o comentario no
        # topo deste arquivo confessava: o `exigir_tela` interno rodava contra
        # None.
        categoria=categoria, db=db, current=current,
    )
    items = res.get("items", [])
    rows = []
    for it in items:
        rows.append([
            (it.get("codigo_instrumento") or it.get("numero_proposta") or "-")[:14],
            (it.get("orgao") or "")[:16],
            Paragraph((it.get("objeto") or "")[:110], ParagraphStyle("o", fontSize=7)),
            (it.get("parlamentar") or "-")[:18],
            (it.get("situacao") or "")[:16],
            (it.get("situacao_contratacao") or "-")[:14],
            it.get("dt_inicio_vigencia") or "-",
            it.get("dt_fim_vigencia") or "-",
            str(it["dias_restantes"]) if it.get("dias_restantes") is not None else "-",
        ])
    # Subtitulo com os filtros ativos (deixa claro o recorte do relatorio)
    _f = []
    if parlamentar: _f.append(f"parlamentar: {parlamentar}")
    if orgao: _f.append(f"órgão: {orgao}")
    if situacao_contratacao: _f.append(f"sit.contratacao: {situacao_contratacao}")
    _VIG = {"vence30": "vence 30d", "vence60": "vence 60d", "vence90": "vence 90d",
            "vence120": "vence 120d", "prestacao": "prestação de contas"}
    if vigencia: _f.append(_VIG.get(vigencia, vigencia))
    if vig_fim_de: _f.append(f"fim vig. de {vig_fim_de}")
    if vig_fim_ate: _f.append(f"fim vig. até {vig_fim_ate}")
    if instrumento: _f.append(f"instrumento: {instrumento}")
    if proposta: _f.append(f"proposta: {proposta}")
    if proponente: _f.append(f"proponente: {proponente}")
    if cnpj: _f.append(f"CNPJ: {cnpj}")
    if search: _f.append(f"busca: {search}")
    filtros = " | ".join(_f) if _f else "sem filtros (todos)"
    pdf = _build_pdf(
        f"Instrumentos Federais (TransfereGov) - {mun.nome}/{mun.uf}",
        f"Categoria: {categoria or 'geral'} · Filtros: {filtros} · {len(rows)} instrumento(s)",
        ["Instrumento", "Órgão", "Objeto", "Parlamentar", "Situação", "Sit.Contr.", "Início Vig.", "Fim Vig.", "Dias"],
        rows,
    )
    nome_arq = f"federais_{mun.nome.replace(' ','_')}.pdf"
    await _registrar_export(
        db, request=request, current=current, tipo="voluntarias",
        municipio_id=municipio_id, registros=len(rows), arquivo=nome_arq,
        filtros={"municipio": f"{mun.nome}/{mun.uf}", "categoria": categoria,
                 "situacao": situacao, "orgao": orgao, "busca": search,
                 "parlamentar": parlamentar, "situacao_contratacao": situacao_contratacao,
                 "vigencia": vigencia, "vig_fim_de": vig_fim_de, "vig_fim_ate": vig_fim_ate},
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"})


@router.get("/vigencias",
            dependencies=[declarado("vigencias.exportar", "convenios.exportar")])
async def export_vigencias(
    request: Request,
    dias: int = Query(120, ge=1, le=3650),
    # O MultiSelect do modal trabalha com NOMES, e o nome vem do proprio backend
    # (`_nomes_municipios` preenche `municipio_nome`). Filtrar por nome aqui e o
    # que garante que o arquivo traga EXATAMENTE as linhas da tela; mandar ids
    # deixaria de fora o instrumento sem municipio_id, que a tela mostra.
    municipios: list[str] = Query(default=[]),
    ordem: str = Query("asc", pattern="^(asc|desc)$"),
    formato: str = Query("pdf", pattern="^(pdf|xlsx)$"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """«Vigências a vencer» em arquivo — PDF ou Excel, com totalizador por município.

    ⭐ DOIS CAMINHOS DE PERMISSAO, espelhando a LEITURA. O endpoint que serve o
    modal (`/api/convenios/alertas`) aceita `convenios.ver` OU `vigencias.ver`,
    porque o dono pediu para liberar o monitoramento de vencimento sem entregar o
    modulo de Convenios Estaduais. Se aqui a regra fosse so `convenios.exportar`,
    quem recebeu a caixinha nova veria o botao e levaria 403 — permissao que
    aparece na tela e nao funciona e pior do que botao ausente. Por isso
    `declarado` (que so MARCA) e o "ou" resolvido no corpo, igual la.

    ⚠️ A LISTA VEM DO ENDPOINT DA TELA, nao de uma consulta nova. `alertas_vigencia`
    ja resolve o alcance do usuario (carteira restrita, super-admin, `[]` para
    carteira vazia) e ja preenche `municipio_nome`. Recopiar essa logica aqui
    criaria a chance de o arquivo mostrar municipio que a tela nao mostra — o
    defeito que este router ja teve em `/convenios`, quando o PDF contava as
    propostas do FNS que a tela corretamente escondia."""
    if not authz.pode(current, "vigencias.exportar"):
        authz.exigir(current, "convenios.exportar")

    from routers.convenios import alertas_vigencia

    # ⚠️ `ano=None, anos=None` EXPLICITOS. `alertas_vigencia` e um endpoint do
    # FastAPI e o default de `anos` e um objeto `Query(None)`, nao None — quem
    # resolve esse default e o framework, e esta chamada e direta. Omitir faz o
    # `anos_list()` la dentro receber o proprio `Query`. E a mesma pegadinha
    # documentada em `/parlamentares`, algumas linhas acima.
    alertas = await alertas_vigencia(municipio_id=None, dias=dias, ano=None,
                                     anos=None, db=db, current=current)
    # A MESMA ordenacao da tela (o modal ordena por dias, nos dois sentidos).
    # `dias_restantes` e obrigatorio no schema, mas o `9999` fica como rede: uma
    # linha sem prazo iria para o fim em vez de estourar a comparacao.
    # ⚠️ `is None`, e não `or`: 0 dias (vence HOJE) é falso em Python e ia para o FIM
    # da lista "menor prazo primeiro" — o mais urgente escondido no fundo.
    alertas = sorted(alertas, key=lambda a: (getattr(a, "dias_restantes", None)
                                             if getattr(a, "dias_restantes", None) is not None
                                             else 9999),
                     reverse=(ordem == "desc"))

    from services import vigencias_export as vx
    dados = vx.normalizar(alertas, municipios)

    # Nome do cliente no cabecalho: quando o recorte e de UM municipio, ele nomeia
    # o documento; com varios, quem nomeia e o tenant. Sem isto o arquivo sai da
    # plataforma sem dizer de quem e.
    nomes = [t["municipio"] for t in dados["totais"]]
    titulo_cliente = nomes[0] if len(nomes) == 1 else ""

    hoje = date.today().strftime("%Y-%m-%d")
    if formato == "xlsx":
        conteudo = vx.gerar_xlsx(dados, dias=dias, municipios=municipios,
                                 titulo_cliente=titulo_cliente)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        nome_arq = f"vigencias_{dias}d_{hoje}.xlsx"
    else:
        conteudo = vx.gerar_pdf(dados, dias=dias, municipios=municipios,
                                titulo_cliente=titulo_cliente)
        mime = "application/pdf"
        nome_arq = f"vigencias_{dias}d_{hoje}.pdf"

    await _registrar_export(
        db, request=request, current=current, tipo="vigencias",
        # Sem `municipio_id`: o recorte pode ser de varios municipios de uma vez.
        # Quais foram fica em `filtros`, que e o campo feito para isso.
        registros=dados["geral"]["qtd"], arquivo=nome_arq,
        filtros={"dias": dias, "formato": formato, "ordem": ordem,
                 "municipios": sorted(municipios) or "todos os do alcance",
                 "municipios_no_arquivo": dados["geral"]["municipios"]},
    )
    return StreamingResponse(
        BytesIO(conteudo), media_type=mime,
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"})


def _parse_emenda(cod: str):
    """codigoEmendaFormatado "202341760002-Vilson da Fetaemg" -> (codigo, parlamentar)."""
    if not cod:
        return ("", "")
    if "-" in cod:
        c, n = cod.split("-", 1)
        return (c.strip(), n.strip())
    return (cod.strip(), "")


@router.get("/plano-acao",
            dependencies=[exige("transferegov_especiais.exportar")])
async def export_plano_acao_pdf(
    request: Request,
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    programa: Optional[str] = Query(None),
    parlamentar: Optional[str] = Query(None),
    emenda: Optional[str] = Query(None),
    objeto: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF dos Planos de Acao (Transferencia Especial / Pix Parlamentar) com os
    MESMOS filtros da tela Especiais."""
    ensure_municipio_access(current, municipio_id)
    # ⭐ «Especiais» virou TELA PROPRIA em 05/09/2026 (`transferegov_especiais`),
    # como as outras sete do grupo FEDERAIS. Ate aqui a tela concedida era
    # "transferegov", uma chave so para as oito.
    authz.exigir_tela(current, "transferegov_especiais")
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")
    from routers.transferegov import buscar as _buscar
    res = await _buscar(
        municipio_id=municipio_id,
        situacao=(situacao if situacao and situacao != "TODAS" else None),
        programa=programa, parlamentar=parlamentar, emenda=emenda, objeto=objeto,
        # Mesmo motivo do export de voluntarias: `_` virou `current` no handler
        # reusado, e este PDF dava 500 desde entao.
        refresh=False, db=db, current=current,
    )
    items = res.get("items", [])
    rows = []
    for it in items:
        cod, parl = _parse_emenda(it.get("emenda_codigo") or "")
        benef = f"{it.get('beneficiario_cnpj') or ''} - {it.get('beneficiario_nome') or ''}".strip(" -")
        # Dados bancários da emenda Pix (banco / agência / conta), vindos do plano
        # de ação (`buscar` já os expõe do raw_data). Uma célula só, legível.
        _bco = " · ".join(x for x in (
            it.get("banco"),
            f"Ag {it['agencia']}" if it.get("agencia") else "",
            f"CC {it['conta']}" if it.get("conta") else "",
        ) if x) or "-"
        rows.append([
            (it.get("codigo") or "")[:16],
            cod[:14] or "-",
            Paragraph((parl or "-")[:50], ParagraphStyle("p", fontSize=7)),
            Paragraph(benef[:70], ParagraphStyle("b", fontSize=7)),
            _br(it.get("valor_total")),
            (it.get("situacao_plano_acao") or "")[:14],
            (it.get("situacao_plano_trabalho") or "-")[:22],
            Paragraph(_bco[:60], ParagraphStyle("bco", fontSize=7)),
        ])
    _f = []
    if situacao and situacao != "TODAS": _f.append(f"situação: {situacao}")
    if programa: _f.append(f"programa: {programa}")
    if parlamentar: _f.append(f"parlamentar/emenda: {parlamentar}")
    if emenda: _f.append(f"emenda: {emenda}")
    if objeto: _f.append(f"objeto: {objeto}")
    filtros = " | ".join(_f) if _f else "sem filtros (todos)"
    pdf = _build_pdf(
        f"Planos de Ação - Transferência Especial - {mun.nome}/{mun.uf}",
        f"Filtros: {filtros} · {len(rows)} plano(s)",
        ["Código", "Emenda", "Parlamentar", "Beneficiário", "Valor", "Sit. P. Ação", "Sit. P. Trabalho", "Dados bancários"],
        rows,
    )
    nome_arq = f"plano_acao_{mun.nome.replace(' ','_')}.pdf"
    await _registrar_export(
        db, request=request, current=current, tipo="plano_acao",
        municipio_id=municipio_id, registros=len(rows), arquivo=nome_arq,
        filtros={"municipio": f"{mun.nome}/{mun.uf}", "situacao": situacao,
                 "programa": programa, "parlamentar": parlamentar,
                 "emenda": emenda, "objeto": objeto},
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"})


@router.get("/emendas", dependencies=[exige("emendas.exportar")])
async def export_emendas_pdf(
    request: Request,
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    authz.exigir_tela(current, "emendas")
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")
    r = await db.execute(text("""
        SELECT nr_indicacao, nome_responsavel, tipo_indicacao,
               uo_sigla, valor_indicacao, status_indicacao, ano
        FROM emendas_estaduais WHERE municipio_id = :mun
        ORDER BY ano DESC NULLS LAST, valor_indicacao DESC NULLS LAST
    """), {"mun": municipio_id})
    items = r.fetchall()
    rows = [[
        (r[0] or "")[:14],
        Paragraph((r[1] or "")[:80], ParagraphStyle("n", fontSize=7)),
        (r[2] or "")[:18],
        (r[3] or "")[:12],
        _br(float(r[4]) if r[4] else 0),
        (r[5] or "")[:14],
        str(r[6] or "-"),
    ] for r in items]
    pdf = _build_pdf(
        f"Emendas Estaduais (SIGCON-MG) - {mun.nome}/{mun.uf}",
        f"{len(items)} indicações parlamentares estaduais",
        ["Nº Indicação", "Responsável", "Tipo", "UO", "Valor", "Status", "Ano"],
        rows,
    )
    nome_arq = f"emendas_{mun.nome.replace(' ','_')}.pdf"
    await _registrar_export(db, request=request, current=current, tipo="emendas",
                            municipio_id=municipio_id, registros=len(items),
                            arquivo=nome_arq,
                            filtros={"municipio": f"{mun.nome}/{mun.uf}"})
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"})


@router.get("/dou", dependencies=[exige("dou.exportar")])
async def export_dou_pdf(
    request: Request,
    municipio_id: int = Query(...),
    edicoes: list[str] = Query(...),
    titulos: list[str] = Query(default=[]),
    # `db` entrou so por causa da trilha: este endpoint nao consulta o banco
    # (o DOU e real-time e vem pronto do frontend), mas exportacao sem registro
    # e o unico caso que o dono nao aceita.
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """DOU eh real-time. Frontend envia os titulos/edicoes ja filtrados via query."""
    ensure_municipio_access(current, municipio_id)
    # `routers/dou_mg.py` ainda nao checa tela nenhuma, entao esta e a PRIMEIRA
    # trava da chave "dou" no sistema. Ela fica de pe sozinha: quem so tem o link
    # da exportacao nao passa a poder baixar o Diario porque a tela vizinha esta
    # aberta — o buraco de la vira linha na trilha quando alguem o fechar.
    authz.exigir_tela(current, "dou")
    rows = []
    for i, (titulo, edicao) in enumerate(zip(titulos, edicoes)):
        rows.append([
            str(i+1),
            Paragraph(titulo[:200], ParagraphStyle("t", fontSize=7)),
            edicao,
        ])
    pdf = _build_pdf(
        f"Diário Oficial MG - Município {municipio_id}",
        f"{len(rows)} publicações encontradas",
        ["#", "Título", "Edição/Data"],
        rows,
        landscape_mode=False,
    )
    nome_arq = f"dou_{municipio_id}.pdf"
    await _registrar_export(
        db, request=request, current=current, tipo="dou",
        municipio_id=municipio_id, registros=len(rows), arquivo=nome_arq,
        # As edicoes definem o periodo coberto; os titulos, nao — sao o conteudo
        # e podem ser centenas de linhas de texto dentro do JSONB.
        filtros={"edicoes": sorted(set(edicoes))[:50]},
    )
    return StreamingResponse(pdf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={nome_arq}"})


# ---------------------------------------------------------------------------
# Parlamentares — NO MODELO DA PLANILHA DO CLIENTE (24/09/2026)
# ---------------------------------------------------------------------------
# Pedido do dono: "na aba parlamentares eu gostaria que o pdf ficasse nesse
# modelo" — `EmendasNikolasFerreiraBomDespacho.xlsx`, aba "Emendas por
# categoria", MEDIDA com openpyxl: paisagem, ajustada à página, bordas finas;
# título mesclado 16pt negrito branco sobre #1F4E78; cabeçalho 12pt negrito
# branco sobre #1F4E78; faixa de área 13pt negrito branco sobre #2E75B6; linhas
# 12pt sobre #DCE6F1 (município em negrito); subtotal negrito sobre #BDD7EE;
# linha em branco entre áreas; TOTAL GERAL branco sobre #1F4E78. Larguras
# relativas A..G = 22, 8, 46, 24, 20, 33, 48.
#
# ⚠️ AS FONTES DA TABELA SAEM A 3/4 DO MODELO (12 -> 9, 13 -> 10): a planilha é
# "ajustada à página" — 201 caracteres de largura impressos em 277 mm saem
# encolhidos nessa proporção. O TÍTULO fica nos 16pt do modelo: é nele que está
# a CIDADE, e o pedido anterior da Laiza foi "a cidade grande, para identificar
# impressa".
#
# A LÓGICA (linhas, áreas, fora do total, "PAGOS") mora em
# `services/relatorio_parlamentares.py`; aqui só se desenha.
_M_AZUL_ESCURO = colors.HexColor("#1F4E78")
_M_AZUL_FAIXA = colors.HexColor("#2E75B6")
_M_AZUL_LINHA = colors.HexColor("#DCE6F1")
_M_AZUL_SUBTOTAL = colors.HexColor("#BDD7EE")
# Fora do total: CINZA, de propósito diferente do azul do modelo — é o que o
# olho usa para não somar essas linhas.
_M_CINZA_FAIXA = colors.HexColor("#595959")
_M_CINZA_LINHA = colors.HexColor("#EDEDED")
_M_CINZA_SOMA = colors.HexColor("#D9D9D9")
_M_BORDA = colors.HexColor("#404040")
# 277 mm úteis (A4 paisagem, margens de 10 mm), na proporção das colunas A..G.
_M_LARGURAS = [w * 277 / 201 * mm for w in (22, 8, 46, 24, 20, 33, 48)]
_M_CABECALHO = ("MUNICÍPIO", "ANO", "RECURSO", "MINISTÉRIO DE ORIGEM",
                "VALOR GLOBAL (R$)", "PLANO DE AÇÃO / PROPOSTA", "SITUAÇÃO ATUAL")

_MS_TIT = ParagraphStyle("m_tit", fontName="Helvetica-Bold", fontSize=16, leading=19,
                         textColor=colors.white, alignment=1)
_MS_FILTRO = ParagraphStyle("m_filtro", fontName="Helvetica", fontSize=8, leading=10,
                            textColor=colors.HexColor("#475569"), spaceBefore=3, spaceAfter=5)
_MS_CAB = ParagraphStyle("m_cab", fontName="Helvetica-Bold", fontSize=9, leading=11,
                         textColor=colors.white, alignment=1)
_MS_FAIXA = ParagraphStyle("m_faixa", fontName="Helvetica-Bold", fontSize=10, leading=12,
                           textColor=colors.white, alignment=0)
_MS_MUN = ParagraphStyle("m_mun", fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=1)
_MS_C = ParagraphStyle("m_c", fontName="Helvetica", fontSize=9, leading=11, alignment=1)
_MS_L = ParagraphStyle("m_l", fontName="Helvetica", fontSize=9, leading=11, alignment=0)
_MS_R = ParagraphStyle("m_r", fontName="Helvetica", fontSize=9, leading=11, alignment=2)
_MS_SUB = ParagraphStyle("m_sub", fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=2)
_MS_TOT = ParagraphStyle("m_tot", fontName="Helvetica-Bold", fontSize=10, leading=12,
                         textColor=colors.white, alignment=2)
_MS_NOTA = ParagraphStyle("m_nota", fontName="Helvetica", fontSize=7.5, leading=9.5,
                          textColor=colors.HexColor("#334155"), spaceBefore=4)

# ⚠️ As chaves são os `GRUPOS_FORA` de `services/relatorio_parlamentares.py`,
# ESCRITOS de novo aqui (o import de lá é local, dentro das funções): chave que
# diverge apaga a nota em silêncio — `test_parlamentares_pdf_modelo` confere.
_NOTA_FORA = {
    # ⚠️ Sem dizer que o FNS "não traz o número da emenda": traz
    # (`coEmendaPolitica`/`nuAnoExercicio` em `parlamentares[]`). O que é verdade
    # é que nada aqui foi casado por ele — o formato nunca foi medido.
    "EMENDAS FEDERAIS SEM INSTRUMENTO IDENTIFICADO": (
        "<b>Fora do total — emendas federais sem instrumento identificado:</b> "
        "indicações da carteira da CGU que não foram casadas pelo número da emenda "
        "nesta base com um instrumento (transferência especial ou convênio). Podem "
        "ser o mesmo dinheiro de uma linha acima — uma proposta de saúde do FNS ou "
        "uma seleção do Novo PAC; por isso não entram no total geral."),
    "PROPOSTAS NÃO SELECIONADAS, EM CADASTRAMENTO, CANCELADAS OU IMPEDIDAS": (
        "<b>Fora do total — propostas não selecionadas, em cadastramento, canceladas "
        "ou impedidas:</b> seleções do Novo PAC não selecionadas, convênios estaduais "
        "ainda em cadastramento, planos impedidos e instrumentos ou propostas "
        "encerrados sem recurso (rejeitados, cancelados, rescindidos, arquivados, "
        "bloqueados e afins). Aparecem para conferência, mas não são recurso do "
        "município."),
}
_NOTA_COMO_LER = (
    "<b>Como ler.</b> Cada parlamentar começa numa folha. A <b>situação atual</b> diz "
    "o que foi medido: «Pagamento realizado» é ordem bancária emitida (transferência "
    "especial), repasse do FNS sem saldo a pagar, desembolso integral do convênio ou "
    "pagamento na planilha da SEGOV (emenda estadual); o que não foi consultado é dito "
    "por extenso e nunca vira R$ 0. O título só diz <b>RECURSOS PAGOS</b> quando todas "
    "as linhas do total foram pagas e não há nada fora dele. <b>Áreas</b>: pela função "
    "orçamentária do plano (transferência especial) ou pelo ministério/secretaria de "
    "origem; esporte só de investimento (obra) conta como infraestrutura; na dúvida, "
    "OUTROS. Um instrumento que executa uma emenda aparece uma vez só — a emenda não "
    "se repete ao lado dele.")


def _esc(s, limite: int = 0) -> str:
    """Texto para Paragraph: markup escapado (um "<" ou "&" derrubava o PDF) e,
    com `limite`, cortado — uma célula mais alta que a folha é LayoutError."""
    t = " ".join(str(s if s is not None else "").split())
    if limite and len(t) > limite:
        t = t[:limite].rstrip() + "…"
    return html.escape(t, quote=False)


def _barra_titulo(titulo: str) -> Table:
    t = Table([[Paragraph(_esc(titulo), _MS_TIT)]], colWidths=[sum(_M_LARGURAS)])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _M_AZUL_ESCURO),
        ("BOX", (0, 0), (-1, -1), 0.4, _M_BORDA),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _celulas_modelo(l: dict) -> list:
    from services.relatorio_parlamentares import fmt_valor
    refs = "<br/>".join(_esc(r, 80) for r in l.get("referencias") or []) or "—"
    return [
        Paragraph(_esc(l["municipio"], 60), _MS_MUN),
        Paragraph(str(l["ano"]) if l.get("ano") else "—", _MS_C),
        Paragraph(_esc(l["recurso"], 600), _MS_L),
        Paragraph(_esc(l["ministerio"], 120), _MS_C),
        Paragraph(fmt_valor(l["valor"]), _MS_R),
        Paragraph(refs, _MS_C),
        Paragraph(_esc(l["situacao"], 500), _MS_L),
    ]


def _linha_soma(rotulo: str, valor, estilo) -> list:
    from services.relatorio_parlamentares import fmt_valor
    return [Paragraph(_esc(rotulo), estilo), "", "", "", Paragraph(fmt_valor(valor), estilo), "", ""]


def _estilo_modelo(tipos: list[str]) -> list:
    cmds: list = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    fundo = {"cab": _M_AZUL_ESCURO, "faixa": _M_AZUL_FAIXA, "dado": _M_AZUL_LINHA,
             "subtotal": _M_AZUL_SUBTOTAL, "total": _M_AZUL_ESCURO,
             "faixa_fora": _M_CINZA_FAIXA, "fora": _M_CINZA_LINHA, "soma_fora": _M_CINZA_SOMA}
    for i, k in enumerate(tipos):
        if k == "branco":
            continue          # a linha em branco do modelo: sem borda, sem fundo
        cmds.append(("GRID", (0, i), (-1, i), 0.4, _M_BORDA))
        cmds.append(("BACKGROUND", (0, i), (-1, i), fundo[k]))
        if k in ("faixa", "faixa_fora"):
            cmds.append(("SPAN", (0, i), (-1, i)))
        elif k in ("subtotal", "total", "soma_fora"):
            cmds.append(("SPAN", (0, i), (3, i)))     # A:D mesclado, como no modelo
    return cmds


def _bloco_modelo(bloco: dict, cidade: str, filtros_txt: str) -> list:
    """Os flowables de UM parlamentar: barra do título, a linha de filtros e a
    tabela (cabeçalho repetido a cada folha)."""
    fl: list = [_barra_titulo(bloco["titulo"]), Paragraph(_esc(filtros_txt), _MS_FILTRO)]
    if not bloco["areas"] and not bloco["fora"]:
        fl.append(Paragraph("Sem lançamentos detalhados para o filtro atual.", _MS_NOTA))
        return fl
    dados: list = [[Paragraph(h, _MS_CAB) for h in _M_CABECALHO]]
    tipos = ["cab"]

    def _add(linha, tipo):
        dados.append(linha)
        tipos.append(tipo)

    for a in bloco["areas"]:
        if len(tipos) > 1:
            _add([""] * 7, "branco")
        _add([Paragraph(_esc(a["area"]), _MS_FAIXA)] + [""] * 6, "faixa")
        for l in a["linhas"]:
            _add(_celulas_modelo(l), "dado")
        _add(_linha_soma(f"SUBTOTAL – {a['area']}", a["subtotal"], _MS_SUB), "subtotal")
    if bloco["total"] is not None:
        _add([""] * 7, "branco")
        _add(_linha_soma(f"TOTAL GERAL – {cidade}", bloco["total"], _MS_TOT), "total")
    for g in bloco["fora"]:
        _add([""] * 7, "branco")
        _add([Paragraph(_esc(f"FORA DO TOTAL – {g['grupo']}"), _MS_FAIXA)] + [""] * 6,
             "faixa_fora")
        for l in g["linhas"]:
            _add(_celulas_modelo(l), "fora")
        _add(_linha_soma("SOMA – FORA DO TOTAL GERAL", g["soma"], _MS_SUB), "soma_fora")
    t = Table(dados, repeatRows=1, colWidths=_M_LARGURAS, hAlign="CENTER",
              rowHeights=[4 * mm if k == "branco" else None for k in tipos])
    t.setStyle(TableStyle(_estilo_modelo(tipos)))
    fl.append(t)
    if bloco["total"] is None:
        fl.append(Paragraph("Nenhum instrumento deste parlamentar entra no total geral.",
                            _MS_NOTA))
    for g in bloco["fora"]:
        if g["grupo"] in _NOTA_FORA:
            fl.append(Paragraph(_NOTA_FORA[g["grupo"]], _MS_NOTA))
    return fl


def _slug_arquivo(s: str) -> str:
    """Pedaço de NOME DE ARQUIVO em ASCII puro: sem acento, e o que não for letra
    ou dígito vira `_`. O `Content-Disposition` daqui não usa `filename*=UTF-8''`,
    e o Starlette codifica o cabeçalho em latin-1 — uma busca com caractere fora
    dele (o `isalnum` deixava passar) dava 500 na hora de devolver o PDF."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def _rodape_cidade(cidade: str, emitido: str):
    """Rodapé desenhado em TODA folha — o mesmo gesto de `services/rm_pdf.py::
    _on_page`. A cidade do título só está na primeira folha de cada
    parlamentar; impressa, a folha de continuação voltaria a não dizer de qual
    cidade era, que é exatamente o pedido (Laiza, Nova Serrana/MG, 24/09/2026)."""
    def _desenha(canvas, doc):
        canvas.saveState()
        largura = doc.pagesize[0]
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(colors.HexColor("#0f172a"))
        canvas.drawString(doc.leftMargin, 5 * mm, cidade)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawRightString(largura - doc.rightMargin, 5 * mm,
                               f"Relatório de Parlamentares · pág. {doc.page} · "
                               f"gerado em {emitido} · PACTHA")
        canvas.restoreState()
    return _desenha


@router.get("/parlamentares", dependencies=[exige("parlamentares.exportar")])
async def export_parlamentares_pdf(
    request: Request,
    municipio_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    ano: Optional[int] = Query(None),
    # ⚠️ `anos` e `tipo` SÃO OS DA TELA (24/09/2026). A aba sempre mandou `anos`
    # (com o ano corrente marcado por padrão) e a rota só declarava `ano`: o
    # FastAPI IGNORA parâmetro não declarado, sem erro, e o PDF saía "todos os
    # anos" com a década inteira enquanto a tela mostrava 2026. E sem `tipo` o
    # `listar` recebia o objeto `Query("parlamentar")` na chamada direta, o
    # filtro de tipo não casava, e o PDF misturava os "outros" (Fundo
    # Municipal, Município de X) que a tela esconde por padrão.
    anos: Optional[list[int]] = Query(None),
    tipo: str = Query("parlamentar", pattern="^(parlamentar|outro|todos)$"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF da tela Parlamentares NO MODELO DA PLANILHA DO CLIENTE (24/09/2026):
    um bloco por parlamentar, cada um numa folha, com o título "RECURSOS
    (PAGOS|PARA) <CIDADE> – EMENDAS INDICADAS POR <NOME>", as faixas por área,
    subtotal, TOTAL GERAL e, à parte, o que fica FORA do total. Respeita a busca
    `q`, os anos, o tipo e o filtro de município. Regras em
    `services/relatorio_parlamentares.py`."""
    # Unico endpoint do router que ja checava a tela — nada a acrescentar aqui.
    # A ordem invertida (tela antes de municipio) fica como esta pelo mesmo
    # motivo de `/ai-relatorio`: `municipio_id` e opcional, e um nao-admin que
    # peca sem municipio ja leva hoje o 403 "Selecione um municipio permitido".
    ensure_tela(current, "parlamentares")
    # Sem município, 403 a quem não é super-admin — de propósito: a carteira do
    # cliente sai pelo CONSOLIDADO, com permissão própria
    # (`/api/consolidado/parlamentares/{nome}/exportar`).
    ensure_municipio_access(current, municipio_id)

    # ⭐ O NOME DA CIDADE, e não o ID (pedido da Laiza, 24/09/2026): o subtítulo
    # dizia "município: 2" — o id interno —, e impressa a folha não dizia de
    # qual cidade era. ⚠️ DEPOIS das duas portas: a leitura do banco não pode
    # acontecer antes de a permissão ser conferida (a `BancoSentinela` de
    # tests/test_export_pdf_gate.py prova "passou da porta" no 1º execute).
    mun = None
    if municipio_id:
        mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
        if not mun:
            raise HTTPException(404, "Município não encontrado")
    _uf = ((mun.uf or "").strip().upper() if mun else "")
    # `Nova Serrana/MG` no subtítulo e na trilha; sem UF (a coluna é anulável
    # desde uf_sem_default_mg), só o nome — nunca "/None".
    rotulo_mun = (f"{mun.nome}/{_uf}" if _uf else mun.nome) if mun else "Todos os municípios"
    # No TÍTULO de cada bloco, como no modelo ("RECURSOS PAGOS BOM DESPACHO"): o
    # nome em maiúsculas, sem UF — a UF vai no rodapé de toda folha.
    cidade_titulo = mun.nome.upper() if mun else "TODOS OS MUNICÍPIOS"

    # Normalização contra a CHAMADA DIRETA (os testes chamam esta função sem o
    # FastAPI no meio, e aí o default é o objeto `Query`, não o valor).
    _anos = anos_list((anos if isinstance(anos, list) else [])
                      + ([ano] if isinstance(ano, int) and ano else []))
    _tipo = tipo if isinstance(tipo, str) else "parlamentar"

    from routers.parlamentares import (listar as _listar, detalhe as _detalhe,
                                       _rotulo_periodo)
    # ⚠️ `ano`/`anos` SEMPRE EXPLICITOS. `listar`/`detalhe` sao endpoints do
    # FastAPI e o default do parametro e um objeto `Query(None)`, nao `None` —
    # quem resolve esse default e o framework, e aqui a chamada e DIRETA (funcao
    # a funcao). Omitir o argumento faz o `anos or []` de la devolver o proprio
    # `Query`, e a soma seguinte estoura com `TypeError: unsupported operand
    # type(s) for +: 'Query' and 'list'` — 500 em TODA exportacao de
    # parlamentares. O mesmo vale para `tipo`: omitido, chega `Query(...)`.
    lista = await _listar(municipio_id=municipio_id, q=q, ano=None, anos=_anos,
                          tipo=_tipo, db=db, current=current)
    items = lista.get("items", [])

    from services.relatorio_parlamentares import montar_bloco

    # A linha pequena de FILTROS abaixo do título de cada bloco. O texto é
    # escapado na hora de virar Paragraph (`_esc`): um "<" ou "&" na busca
    # derrubava o PDF com 500 (e há município com apóstrofo, como Olhos-d'Água).
    emitido = datetime.now().strftime('%d/%m/%Y %H:%M')
    filtros = []
    if q:
        filtros.append(f"busca: \"{q}\"")
    if _anos:
        filtros.append(f"{'ano' if len(_anos) == 1 else 'anos'}: {_rotulo_periodo(_anos)}")
    else:
        filtros.append("todos os anos")
    if _tipo == "outro":
        filtros.append("só outros proponentes (fundos, municípios)")
    elif _tipo == "todos":
        filtros.append("parlamentares e outros proponentes")
    filtros.append(f"município: {rotulo_mun}")

    story: list = []
    for n, p in enumerate(items, 1):
        try:
            det = await _detalhe(nome_normalizado=p["nome_display"],
                                 municipio_id=municipio_id, ano=None, anos=_anos,
                                 db=db, current=current)  # `ano`/`anos`: ver acima
        except HTTPException:
            det = {}
        bloco = montar_bloco(p["nome_display"], det, cidade_titulo)
        if n > 1:
            story.append(PageBreak())      # um parlamentar por folha, como o modelo
        story += _bloco_modelo(
            bloco, cidade_titulo,
            " · ".join(filtros) + f" · parlamentar {n} de {len(items)} · gerado em {emitido}")

    if not items:
        story += [
            _barra_titulo(f"RECURSOS PARA {cidade_titulo} – EMENDAS INDICADAS POR PARLAMENTARES"),
            Paragraph(_esc(" · ".join(filtros) + f" · gerado em {emitido}"), _MS_FILTRO),
            Paragraph("Nenhum parlamentar para o filtro atual.", _MS_NOTA),
        ]
    else:
        # Uma vez, no fim — repetida sob cada parlamentar viraria ruído.
        story.append(Spacer(1, 6))
        story.append(Paragraph(_NOTA_COMO_LER, _MS_NOTA))

    buf = BytesIO()
    # `title`: é o que aparece na aba do visualizador — a tela abre o PDF como
    # blob (`window.open`), e o nome do arquivo do Content-Disposition se perde.
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm,
                            title=f"Relatório de Parlamentares — {rotulo_mun}",
                            author="PACTHA")
    _rodape = _rodape_cidade(rotulo_mun.upper(), emitido)
    doc.build(story, onFirstPage=_rodape, onLaterPages=_rodape)
    buf.seek(0)
    fn = "parlamentares_" + (_slug_arquivo(mun.nome) if mun else "todos_os_municipios")
    if q:
        fn += "_" + _slug_arquivo(q)[:20]
    if _anos:
        fn += f"_{_anos[0]}" if len(_anos) == 1 else f"_{_anos[0]}-{_anos[-1]}"
    fn = fn.rstrip("_")
    await _registrar_export(
        db, request=request, current=current, tipo="parlamentares",
        municipio_id=municipio_id, registros=len(items), arquivo=f"{fn}.pdf",
        # Sem municipio a exportacao e da carteira INTEIRA — a marca fica
        # explicita para nao passar por relatorio de uma prefeitura so.
        filtros={"busca": q, "anos": _anos, "tipo": _tipo, "municipio": rotulo_mun,
                 "escopo": "municipio" if municipio_id else "todos os municipios"},
    )
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={fn}.pdf"})


# ---------------------------------------------------------------------------
# IA PACTHA — exporta uma resposta da IA (markdown) em PDF
# ---------------------------------------------------------------------------
def _md_inline(t: str) -> str:
    """Markdown inline -> markup do reportlab Paragraph (<b>, <i>, code)."""
    t = html.escape(t or "", quote=False)
    t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"__([^_]+)__", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\*\w])\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", t)
    return t


def _md_to_flowables(md: str, styles) -> list:
    """Converte markdown (headings, listas, tabelas, negrito) em flowables."""
    body = ParagraphStyle("mdbody", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=4)
    h1 = ParagraphStyle("mdh1", parent=styles["Heading1"], fontSize=14, textColor=colors.HexColor("#1e40af"), spaceBefore=8, spaceAfter=4)
    h2 = ParagraphStyle("mdh2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#1e40af"), spaceBefore=6, spaceAfter=3)
    h3 = ParagraphStyle("mdh3", parent=styles["Heading3"], fontSize=11, textColor=colors.HexColor("#334155"), spaceBefore=4, spaceAfter=2)
    cell = ParagraphStyle("mdcell", parent=styles["Normal"], fontSize=8, leading=10)

    out = []
    lines = (md or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        # Tabela markdown (linha com | e proxima com ---)
        if "|" in s and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:\-|]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            def _cells(row):
                row = row.strip().strip("|")
                return [c.strip() for c in row.split("|")]
            header = _cells(s)
            data = [[Paragraph(_md_inline(c), cell) for c in header]]
            i += 2
            while i < len(lines) and "|" in lines[i]:
                data.append([Paragraph(_md_inline(c), cell) for c in _cells(lines[i])])
                i += 1
            t = Table(data, repeatRows=1, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e40af")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            out.append(t)
            out.append(Spacer(1, 6))
            continue
        if not s:
            out.append(Spacer(1, 4))
        elif s.startswith("### "):
            out.append(Paragraph(_md_inline(s[4:]), h3))
        elif s.startswith("## "):
            out.append(Paragraph(_md_inline(s[3:]), h2))
        elif s.startswith("# "):
            out.append(Paragraph(_md_inline(s[2:]), h1))
        elif re.match(r"^([-*+])\s+", s):
            out.append(Paragraph("• " + _md_inline(re.sub(r"^([-*+])\s+", "", s)), body, bulletText=None))
        elif re.match(r"^\d+\.\s+", s):
            out.append(Paragraph(_md_inline(s), body))
        elif re.match(r"^[-=]{3,}$", s):
            out.append(Spacer(1, 4))
        else:
            out.append(Paragraph(_md_inline(s), body))
        i += 1
    return out


# Nome legivel da fonte a partir do nome tecnico da ferramenta, para a secao de
# procedencia. O que nao estiver aqui nao aparece — melhor omitir do que
# imprimir "query_xyz" num documento institucional.
_FONTE_DA_TOOL = {
    "municipio_summary": "Resumo consolidado do município (base PACTHA)",
    "query_convenios_sigcon": "SIGCON-MG — convênios estaduais",
    "query_situacoes_sigcon": "SIGCON-MG — situações dos convênios",
    "query_voluntarias": "TransfereGov / SICONV — propostas federais",
    "search_by_parlamentar": "Busca por parlamentar (todas as fontes)",
    "query_simec_liberacoes": "SIMEC PAR — liberações do MEC",
    "query_simec_dimensoes": "SIMEC PAR — diagnóstico por dimensão",
    "query_emendas_estaduais": "SIGCON-MG — emendas estaduais",
    "query_fns": "FNS — Fundo Nacional de Saúde",
    "query_plano_acao": "Transferências Especiais (RP9) — Ministério da Fazenda",
    "list_municipios": None,  # ruido: nao entra no relatorio
}


@router.post("/ai-relatorio", dependencies=[exige("ai.exportar")])
async def export_ai_relatorio(
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Relatorio em PDF de UM resultado da IA.

    Diferente do /ai antigo (que imprimia "Solicitacao: <pergunta>" seguida da
    resposta e parecia transcricao de conversa): aqui sai um documento —
    cabecalho institucional com municipio e data de emissao, o conteudo como
    corpo, e uma secao de PROCEDENCIA com as fontes que a IA realmente
    consultou. Body: {assunto, conteudo, municipio_id?, tools?: [nomes]}."""
    # Aqui a tela vem ANTES do municipio, ao contrario do resto do router, e nao
    # e descuido: `municipio_id` e OPCIONAL neste corpo, e chamar
    # `authz.exigir_municipio(current, None)` para um nao-admin levanta 403
    # ("Selecione um municipio permitido") nos DOIS modos — o que quebraria hoje
    # todo relatorio de IA pedido sem municipio. Entao a checagem de municipio
    # continua exatamente onde estava (so quando ha `mid`), e a de tela, que em
    # modo aviso nunca levanta, entra no topo.
    authz.exigir_tela(current, "ai")
    conteudo = (payload.get("conteudo") or "").strip()
    if not conteudo:
        raise HTTPException(400, "conteudo vazio")
    assunto = (payload.get("assunto") or "Relatório").strip().replace("\n", " ")[:160]

    municipio_txt = ""
    mid = payload.get("municipio_id")
    if mid:
        ensure_municipio_access(current, mid)
        row = (await db.execute(
            text("SELECT nome, uf FROM municipios WHERE id = :i"), {"i": int(mid)})).first()
        if row:
            municipio_txt = f"{row[0]}/{row[1]}"

    fontes: list[str] = []
    for t in (payload.get("tools") or []):
        nome = _FONTE_DA_TOOL.get(str(t))
        if nome and nome not in fontes:
            fontes.append(nome)

    styles = getSampleStyleSheet()
    st_rotulo = ParagraphStyle("Rotulo", parent=styles["Normal"], fontSize=7.5,
                               textColor=colors.HexColor("#64748b"), spaceAfter=1,
                               alignment=1)
    st_titulo = ParagraphStyle("TituloRel", parent=styles["Heading1"], fontSize=16,
                               textColor=colors.HexColor("#0f172a"), spaceAfter=2,
                               alignment=1, leading=19)
    st_sub = ParagraphStyle("SubRel", parent=styles["Normal"], fontSize=9,
                            textColor=colors.HexColor("#475569"), alignment=1,
                            spaceAfter=10)
    st_sec = ParagraphStyle("SecRel", parent=styles["Heading3"], fontSize=10,
                            textColor=colors.HexColor("#1e40af"), spaceBefore=10,
                            spaceAfter=3)
    st_fonte = ParagraphStyle("FonteRel", parent=styles["Normal"], fontSize=8.5,
                              textColor=colors.HexColor("#334155"), leftIndent=8,
                              spaceAfter=1)
    st_rodape = ParagraphStyle("RodapeRel", parent=styles["Normal"], fontSize=7,
                               textColor=colors.HexColor("#94a3b8"), alignment=1)

    emitido = datetime.now().strftime("%d/%m/%Y as %H:%M")
    linha_sub = " · ".join(x for x in [
        municipio_txt, f"Emitido em {emitido}",
        html.escape(getattr(current, "name", "") or ""),
    ] if x)
    story = [
        Paragraph("RELATÓRIO GERADO PELA PLATAFORMA PACTHA", st_rotulo),
        Paragraph(html.escape(assunto), st_titulo),
        Paragraph(linha_sub, st_sub),
        Table([[""]], colWidths=[180 * mm], rowHeights=[0.6],
              style=TableStyle([("BACKGROUND", (0, 0), (-1, -1),
                                 colors.HexColor("#1e40af"))])),
        Spacer(1, 8),
    ]
    story.extend(_md_to_flowables(conteudo, styles))

    if fontes:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Procedência dos dados", st_sec))
        for f in fontes:
            story.append(Paragraph("• " + html.escape(f), st_fonte))

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Documento gerado automaticamente a partir dos dados da plataforma PACTHA na data de "
        "emissão. Os valores refletem a última coleta de cada fonte oficial.", st_rodape))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=12 * mm,
                            title=assunto, author="PACTHA")
    doc.build(story)
    buf.seek(0)
    nome_arq = re.sub(r"[^A-Za-z0-9]+", "-", assunto).strip("-").lower()[:60] or "relatorio"
    await _registrar_export(
        db, request=request, current=current, tipo="ia_relatorio",
        municipio_id=int(mid) if mid else None,
        arquivo=f"relatorio-{nome_arq}.pdf",
        # O texto da IA NAO vai para a trilha: e o corpo do relatorio inteiro, e
        # copia-lo aqui duplicaria o documento numa tabela que nao se apaga. Ficam
        # o assunto (rotulo) e as FONTES que a IA consultou — que e o que responde
        # "de onde veio o numero que este PDF afirma".
        filtros={"assunto": assunto, "municipio": municipio_txt, "fontes": fontes,
                 "tamanho_caracteres": len(conteudo)},
    )
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=relatorio-{nome_arq}.pdf"})


@router.post("/ai", dependencies=[exige("ai.exportar")])
async def export_ai_pdf(
    request: Request,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),   # so para a trilha (ver /dou)
    current: User = Depends(get_current_user),
):
    """Exporta uma resposta da IA PACTHA (markdown) em PDF. Body: {titulo?, pergunta?, conteudo}."""
    # Endpoint LEGADO (o frontend hoje chama `/ai-relatorio`) e o unico deste
    # router que nao checava NADA alem de estar logado: sem municipio, porque nao
    # sabe de qual municipio a conversa tratava, e sem tela. Rota esquecida que
    # continua registrada e um caminho aberto — a mesma chave da tela de IA vale
    # aqui.
    authz.exigir_tela(current, "ai")
    conteudo = (payload.get("conteudo") or "").strip()
    if not conteudo:
        raise HTTPException(400, "conteudo vazio")
    titulo = (payload.get("titulo") or "Relatório - IA PACTHA").strip()[:120]
    pergunta = (payload.get("pergunta") or "").strip()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=15,
                                 textColor=colors.HexColor("#1e40af"), spaceAfter=2)
    q_style = ParagraphStyle("Q", parent=styles["Normal"], fontSize=9,
                             textColor=colors.HexColor("#475569"), spaceAfter=2,
                             leftIndent=6, borderPadding=4)
    story = [Paragraph(html.escape(titulo), title_style)]
    if pergunta:
        story.append(Paragraph("<b>Solicitação:</b> " + _md_inline(pergunta), q_style))
    story.append(Spacer(1, 6))
    story.extend(_md_to_flowables(conteudo, styles))
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        f"Gerado pela IA PACTHA em {datetime.now().strftime('%d/%m/%Y %H:%M')} · "
        "confira os dados na plataforma antes de usar.",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#94a3b8"), alignment=1)))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=12*mm)
    doc.build(story)
    buf.seek(0)
    await _registrar_export(
        db, request=request, current=current, tipo="ia",
        arquivo="ia-pactha.pdf",
        # A PERGUNTA entra (e curta e identifica o recorte pedido); a resposta,
        # nao (documento inteiro). Sem municipio_id: este endpoint legado nao
        # sabe de qual municipio a conversa tratava.
        filtros={"titulo": titulo, "pergunta": pergunta[:500] or None,
                 "tamanho_caracteres": len(conteudo)},
    )
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ia-pactha.pdf"})
