"""Export PDF: Convenios SIGCON-MG, Emendas Estaduais, Diario Oficial MG."""
import re
import html
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

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
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
    alertas = sorted(alertas, key=lambda a: getattr(a, "dias_restantes", None) or 9999,
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
# Parlamentares — relatorio por parlamentar (respeita a busca da tela)
# ---------------------------------------------------------------------------
_CELL = ParagraphStyle("cell", fontSize=7, leading=8.5)


def _pc(txt, limit: int = 400):
    """Celula que quebra linha (Paragraph). '-' quando vazio."""
    s = "" if txt is None else str(txt)
    s = s.replace("\n", " ").strip()
    return Paragraph((s[:limit] or "-"), _CELL)


def _sec_table(headers: list, rows: list, col_widths_mm: list) -> Table:
    t = Table([headers] + rows, repeatRows=1, hAlign="LEFT",
              colWidths=[w * mm for w in col_widths_mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


@router.get("/parlamentares", dependencies=[exige("parlamentares.exportar")])
async def export_parlamentares_pdf(
    request: Request,
    municipio_id: Optional[int] = Query(None),
    q: Optional[str] = Query(None),
    ano: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """PDF da tela Parlamentares — uma secao por parlamentar (respeita a busca
    `q`, o ano e o filtro de municipio), com TODOS os lancamentos: SIGCON-MG
    (estadual), TransfereGov/SICONV (federal) e Emendas estaduais."""
    # Unico endpoint do router que ja checava a tela — nada a acrescentar aqui.
    # A ordem invertida (tela antes de municipio) fica como esta pelo mesmo
    # motivo de `/ai-relatorio`: `municipio_id` e opcional, e um nao-admin que
    # peca sem municipio ja leva hoje o 403 "Selecione um municipio permitido".
    ensure_tela(current, "parlamentares")
    # Sem município, 403 a quem não é super-admin — de propósito: a carteira do
    # cliente sai pelo CONSOLIDADO, com permissão própria
    # (`/api/consolidado/parlamentares/{nome}/exportar`).
    ensure_municipio_access(current, municipio_id)

    from routers.parlamentares import listar as _listar, detalhe as _detalhe
    # ⚠️ `anos=None` EXPLICITO. `listar`/`detalhe` sao endpoints do FastAPI e o
    # default do parametro e um objeto `Query(None)`, nao `None` — quem resolve
    # esse default e o framework, e aqui a chamada e DIRETA (funcao a funcao).
    # Omitir o argumento faz o `anos or []` de la devolver o proprio `Query`, e a
    # soma seguinte estoura com `TypeError: unsupported operand type(s) for +:
    # 'Query' and 'list'` — 500 em TODA exportacao de parlamentares, para quem
    # tem a tela inclusive. Ver `routers/parlamentares.py::listar` (linha do
    # `anos_list((anos or []) + ...)`).
    lista = await _listar(municipio_id=municipio_id, q=q, ano=ano, anos=None,
                          db=db, current=current)
    items = lista.get("items", [])

    styles = getSampleStyleSheet()
    name_style = ParagraphStyle("pname", parent=styles["Heading2"], fontSize=11,
                                textColor=colors.HexColor("#1e40af"),
                                spaceBefore=10, spaceAfter=1)
    meta_style = ParagraphStyle("pmeta", parent=styles["Normal"], fontSize=8,
                                textColor=colors.HexColor("#475569"), spaceAfter=3)
    sub_style = ParagraphStyle("psub", parent=styles["Normal"], fontSize=8.5,
                               fontName="Helvetica-Bold",
                               textColor=colors.HexColor("#0f766e"),
                               spaceBefore=4, spaceAfter=2)
    title_style = ParagraphStyle("Title", parent=styles["Heading1"], fontSize=15,
                                 textColor=colors.HexColor("#1e40af"), spaceAfter=2)
    subt_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9,
                                textColor=colors.HexColor("#475569"), spaceAfter=10)

    filtros = []
    if q:
        filtros.append(f"busca: \"{q}\"")
    filtros.append(f"ano: {ano}" if ano else "todos os anos")
    filtros.append(f"município: {municipio_id}" if municipio_id else "todos os municípios")
    story = [
        Paragraph("Relatório de Parlamentares", title_style),
        Paragraph(f"{len(items)} parlamentar(es) · {' · '.join(filtros)}", subt_style),
    ]

    for p in items:
        try:
            det = await _detalhe(nome_normalizado=p["nome_display"],
                                 municipio_id=municipio_id, ano=ano, anos=None,
                                 db=db, current=current)  # `anos=None`: ver acima
        except HTTPException:
            det = {"sigcon": [], "voluntarias": [], "emendas": [], "plano_acao": [], "pac": [], "fns": []}

        pf = p.get("por_fonte", {})
        muns = ", ".join(p.get("municipios", []))
        cab = [
            Paragraph(p["nome_display"], name_style),
            Paragraph(
                f"{p['total_lancamentos']} lançamento(s) · Total {_br(p['valor_total'])} · "
                f"SIGCON: {pf.get('sigcon', 0)} · TransfereGov: {pf.get('voluntaria', 0)} · "
                f"Emendas: {pf.get('emenda', 0)} · Transf. Especial: {pf.get('plano_acao', 0)} · "
                f"PAC: {pf.get('pac', 0)} · FNS: {pf.get('fns', 0)} · "
                f"Emendas federais: {pf.get('emenda_federal', 0)}"
                + (f" · Municípios: {muns}" if muns else ""),
                meta_style),
        ]
        story.append(KeepTogether(cab))

        sig = det.get("sigcon", [])
        if sig:
            rows = [[
                _pc(s.get("municipio_nome"), 30), _pc(s.get("numero"), 20),
                _pc(s.get("orgao"), 60), _pc(s.get("situacao"), 40),
                _pc(_br(s.get("valor_total"))),
                _pc(s.get("dt_vigencia_atual") or s.get("dt_vigencia_final")),
                _pc(s.get("objeto"), 500),
            ] for s in sig]
            story.append(Paragraph(f"SIGCON-MG (Estadual) — {len(sig)} convênio(s)", sub_style))
            story.append(_sec_table(
                ["Município", "Nº SIGCON", "Órgão", "Situação", "Valor Total", "Vigência", "Objeto"],
                rows, [24, 22, 34, 30, 26, 22, 119]))

        vol = det.get("voluntarias", [])
        if vol:
            rows = [[
                _pc(v.get("municipio_nome"), 30), _pc(v.get("numero_proposta"), 20),
                _pc(v.get("codigo_instrumento"), 20), _pc(v.get("orgao"), 40),
                _pc(v.get("situacao"), 40), _pc(v.get("situacao_contratacao"), 30),
                _pc(_br(v.get("valor_global"))),
                _pc(_br(v.get("dt_fim_vigencia")) if v.get("dt_fim_vigencia") else "-"),
                _pc(v.get("objeto"), 500),
            ] for v in vol]
            story.append(Paragraph(f"TransfereGov / SICONV (Federal) — {len(vol)} proposta(s)", sub_style))
            story.append(_sec_table(
                ["Município", "Nº Proposta", "Instrumento", "Órgão", "Situação", "Sit.Contr.", "Valor Global", "Fim Vig.", "Objeto"],
                rows, [22, 22, 22, 26, 26, 22, 26, 20, 91]))

        em = det.get("emendas", [])
        if em:
            rows = [[
                _pc(e.get("municipio_nome"), 30), _pc(e.get("nr_indicacao"), 20),
                _pc(e.get("ano")), _pc(e.get("uo_sigla"), 14),
                _pc(e.get("beneficiario"), 120), _pc(e.get("tipo_atendimento"), 60),
                _pc(_br(e.get("valor_indicacao"))), _pc(e.get("status_indicacao"), 40),
            ] for e in em]
            story.append(Paragraph(f"Emendas Estaduais — {len(em)} indicação(ões)", sub_style))
            story.append(_sec_table(
                ["Município", "Indicação", "Ano", "UO", "Beneficiário", "Tipo", "Valor", "Status"],
                rows, [24, 24, 12, 16, 70, 45, 26, 60]))

        pa = det.get("plano_acao", [])
        if pa:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("codigo"), 20),
                _pc(x.get("emenda"), 16), _pc(x.get("situacao"), 16),
                _pc(_br(x.get("valor_custeio"))), _pc(_br(x.get("valor_investimento"))),
                _pc(_br(x.get("valor_total"))), _pc(x.get("objeto"), 500),
            ] for x in pa]
            story.append(Paragraph(f"Transferência Especial / Plano de Ação (RP9) — {len(pa)} plano(s)", sub_style))
            story.append(_sec_table(
                ["Município", "Plano", "Emenda", "Situação", "Custeio", "Investim.", "Valor Total", "Objeto/Política"],
                rows, [24, 26, 26, 22, 26, 26, 26, 101]))

        pac = det.get("pac", [])
        if pac:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("numero_proposta"), 20),
                _pc(x.get("programa"), 120), _pc(x.get("situacao"), 40),
                _pc(_br(x.get("valor_total"))), _pc(x.get("emenda_parlamentar"), 40),
            ] for x in pac]
            story.append(Paragraph(f"Seleção PAC / Novo PAC — {len(pac)} proposta(s)", sub_style))
            story.append(_sec_table(
                ["Município", "Nº Proposta", "Programa", "Situação", "Valor Total", "Emenda"],
                rows, [26, 24, 90, 40, 28, 45]))

        fns = det.get("fns", [])
        if fns:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("numero"), 20),
                _pc(x.get("orgao"), 40), _pc(x.get("situacao"), 40),
                _pc(_br(x.get("valor_total"))), _pc(x.get("ano")),
                _pc(x.get("objeto"), 500),
            ] for x in fns]
            story.append(Paragraph(f"FNS — Fundo Nacional de Saúde (Federal) — {len(fns)} proposta(s)", sub_style))
            story.append(_sec_table(
                ["Município", "Nº Proposta", "Órgão", "Situação", "Valor Total", "Ano", "Objeto"],
                rows, [24, 24, 34, 34, 26, 14, 97]))

        # A sétima fonte. O cabeçalho do parlamentar já contava "Emendas federais"
        # (acima), mas o arquivo não tinha a seção: o total do cabeçalho passava
        # a soma das tabelas, e o parlamentar só com emenda federal saía "sem
        # lançamentos detalhados".
        ef = det.get("emendas_federais", [])
        if ef:
            rows = [[
                _pc(x.get("municipio_nome"), 30), _pc(x.get("codigo_emenda"), 20),
                _pc(x.get("ano")), _pc(x.get("beneficiario_nome"), 120),
                _pc(x.get("qualif_proponente"), 40), _pc(_br(x.get("valor_total"))),
            ] for x in ef]
            story.append(Paragraph(f"Emendas federais (carteira CGU) — {len(ef)} emenda(s)", sub_style))
            story.append(_sec_table(
                ["Município", "Emenda", "Ano", "Beneficiário", "Qualificação", "Valor"],
                rows, [26, 26, 12, 110, 60, 28]))

        if not (sig or vol or em or pa or pac or fns or ef):
            story.append(Paragraph("Sem lançamentos detalhados.", meta_style))
        story.append(Spacer(1, 6))

    if not items:
        story.append(Paragraph("Nenhum parlamentar para o filtro atual.", meta_style))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | PACTHA - Plataforma de Acompanhamento",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.HexColor("#64748b"), alignment=2)))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    doc.build(story)
    buf.seek(0)
    fn = "parlamentares"
    if q:
        fn += "_" + "".join(ch for ch in q if ch.isalnum())[:20]
    if ano:
        fn += f"_{ano}"
    await _registrar_export(
        db, request=request, current=current, tipo="parlamentares",
        municipio_id=municipio_id, registros=len(items), arquivo=f"{fn}.pdf",
        # Sem municipio a exportacao e da carteira INTEIRA — a marca fica
        # explicita para nao passar por relatorio de uma prefeitura so.
        filtros={"busca": q, "ano": ano,
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
