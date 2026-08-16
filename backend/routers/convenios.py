"""Convenios estaduais (SIGCON-MG).

Apos refactor lean, mantemos apenas a esfera estadual. Federal foi removida.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, and_, text
from datetime import date, timedelta
from typing import Optional
from database import get_db
from models import ConvenioEstadual, Municipio
from schemas.convenio import ConvenioResponse, ConvenioListResponse, ConvenioStats, AlertaVigencia
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from services.coleta import frescor_coleta
from services.audit import registrar
# Trava de permissao em MODO AVISO. `ensure_dono` responde a pergunta que
# `ensure_tela` nao responde: "este id e de um municipio que a pessoa enxerga?".
from services import authz
from services.registro_rotas import exige
from services.bi import anos_list
from models.user import User
import math
import os
import re
import unicodedata

router = APIRouter(prefix="/api/convenios", tags=["convenios"])


# --------------------------------------------------------------- sentinelas
# Sentinela do portal: o texto que ele escreve para dizer "este campo esta
# vazio". Comparacao por IGUALDADE EXATA do texto aparado, sem acento e em
# minusculas — NUNCA por substring: "Diretoria de Convenios e Doacoes" contem a
# palavra, e uma regra por substring engoliria diretoria real.
#
# O conjunto tem UM elemento de proposito. Varridos os 3 tenants, os unicos
# valores nao-diretoria de `setor` sao "Nao ha" (186 linhas) e "Processos
# Migrados" (20). "Processos Migrados" FICA DE FORA: as 20 linhas que o
# carregam tem, TODAS, fase_etapa_status = "ALTERAR - ALTERAR - Alterar",
# espalhadas por 4 situacoes — e fila real do fluxo, nao ausencia de dado.
# Tambem nao entram "-", "n/a", "nao informado": nenhum aparece em tenant
# nenhum, e cada entrada especulativa e uma chance de engolir dado real amanha.
_SENTINELA_VAZIO = {"nao ha"}


def _sem_sentinela(v):
    """Devolve None quando o texto e marcador de vazio do portal."""
    if not isinstance(v, str):
        return v or None
    s = v.strip()
    if not s:
        return None
    chave = "".join(c for c in unicodedata.normalize("NFKD", s.casefold())
                    if not unicodedata.combining(c))
    chave = " ".join(chave.split())
    return None if chave in _SENTINELA_VAZIO else s


def _sem_sentinela_composto(v):
    """'Fase-Etapa-Status' vem como partes unidas por hifen. So some quando
    TODAS as partes sao sentinela: "Nao ha - Nao ha - Nao ha" (117 linhas) e
    "- -" (29) saem; "ALTERAR - ALTERAR - Alterar" (20) e "CELEBRACAO -
    PROPOSTA - ANALISE - CHECKLIST DE CELEBRACAO" (12) ficam INTEIROS. Testar o
    texto todo apagaria uma fase real que tivesse uma parte vazia."""
    s = _sem_sentinela(v)
    if s is None:
        return None
    return None if all(_sem_sentinela(p) is None for p in s.split("-")) else s


def _proposta_vigencia(raw: dict):
    """Prazo PROPOSTO, normalizado para "<n> <unidade>".

    O SIGCON entrega o mesmo dado com dois rotulos e dois formatos, escolhidos
    pelo TIPO DE INSTRUMENTO: "Proposta de Vigencia" = "730 / dias"
    (Transferencia Especial, 32 linhas) e "Proposta de Dias de Vigencia" = "730"
    (Convenio, 91 linhas) — ver o mapa em ingestion/sigcon_scraper.py:385-386.
    Ler so o primeiro deixava 91 linhas com "-" tendo o numero gravado ao lado.

    A unidade NAO e constante: vem escrita no proprio dado, depois da barra. Por
    isso e ECOADA, nunca assumida — hardcodar " dias" transformaria um futuro
    "24 / meses" em "24 dias", numero errado na tela, pior que o "-" de hoje.
    O que nao e numero (o portal escreve "Nao ha") passa intacto."""
    v = raw.get("proposta_vigencia") or raw.get("proposta_dias_vigencia")
    if v is None:
        return None
    s = str(v).strip()
    if "/" in s:
        n, _, unidade = s.partition("/")
        n, unidade = n.strip(), unidade.strip()
        return f"{n} {unidade}" if n.isdigit() and unidade.isalpha() else (s or None)
    return f"{s} dias" if s.isdigit() else (s or None)


# ------------------------------------------------------------------- fonte
# A regra de FONTE mora AQUI, num lugar so. `convenios_estadual` guarda TRES
# origens: SIGCON-MG (convenio estadual de MG), GCONV-ES (o equivalente
# capixaba) e FNS (propostas de saude, que NAO sao convenio e tem tela propria).
# A regra estava copiada em quatro lugares deste arquivo, e foi essa duplicacao
# que deixou o export PDF de fora e contar propostas de saude como convenio.
_FNS_EXCL = or_(ConvenioEstadual.fonte.is_(None),
                ~ConvenioEstadual.fonte.ilike("%FNS%"))


def _cond_fonte(fonte: Optional[str], fontes: Optional[list[str]]):
    """Sem escolha = a regra padrao da tela (tudo menos FNS).

    'SIGCON' e 'SIGCON-MG' sao o MESMO pedido: o dropdown antigo mandava
    'SIGCON', o novo manda o valor do banco. Os dois casam com as duas grafias
    E com fonte NULA (linhas legadas de MG).

    Substitui o `_asked_fns`, que significava "o caller citou FNS" e desligava a
    exclusao para TODAS as fontes juntas — marcar tudo trazia conjunto errado."""
    if fontes:
        alvo: list[str] = []
        com_nulo = False
        for f in fontes:
            if f.upper() in ("SIGCON", "SIGCON-MG"):
                alvo.extend(["SIGCON-MG", "SIGCON"])
                com_nulo = True
            else:
                alvo.append(f)
        cond = ConvenioEstadual.fonte.in_(alvo)
        return or_(cond, ConvenioEstadual.fonte.is_(None)) if com_nulo else cond
    if fonte:
        cond = ConvenioEstadual.fonte == fonte
        return cond if "FNS" in fonte.upper() else and_(cond, _FNS_EXCL)
    return _FNS_EXCL


def estadual_to_response(c: ConvenioEstadual) -> ConvenioResponse:
    dias = None
    if c.dt_vigencia_atual:
        dias = (c.dt_vigencia_atual - date.today()).days
    elif c.dt_vigencia_final:
        dias = (c.dt_vigencia_final - date.today()).days
    # Dias restantes SEMPRE derivado da data que a tela exibe ao lado. O SIGCON
    # publica um contador proprio em raw_data.dias_restantes_str, mas ele e o
    # RETRATO DO DIA DA COLETA e sobrevive a rodadas que nao abrem o detalhe:
    # medido, 65 das 92 linhas que o tinham exibiam numero diferente do calculo,
    # e um convenio caia no filtro "vence em 120 dias" mostrando "121d". A mesma
    # coluna respondia por duas contas e discordava do Dashboard, do BI e dos
    # alertas, que sempre calcularam por data.
    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    nr_proposta = raw.get("nr_proposta")
    nr_instrumento = raw.get("nr_instrumento")
    nr_plano = c.nr_plano_trabalho
    # Heuristicas para CKAN bulk (raw_data costuma vir vazio):
    # - nr_instrumento SIGCON: 8-12 digits + "/" + 4-digit year (ex: "1481000677/2026")
    # - nr_proposta SIGCON:   6 digits + "/" + 4-digit year       (ex: "001030/2026")
    # - nr_plano_trabalho real eh um inteiro curto (5-7 digits sem barra)
    if not nr_instrumento and c.nr_sigcon and re.match(r"^\d{8,12}/\d{4}$", c.nr_sigcon):
        nr_instrumento = c.nr_sigcon
    if not nr_proposta and nr_plano and re.match(r"^\d{6}/\d{4}$", nr_plano):
        nr_proposta = nr_plano
        nr_plano = None
    if not nr_proposta:
        rps = raw.get("nr_plano_sigcon")
        if rps and re.match(r"^\d{6}/\d{4}$", rps):
            nr_proposta = rps
    return ConvenioResponse(
        id=c.id,
        esfera="estadual",
        nr_sigcon=c.nr_sigcon,
        municipio_id=c.municipio_id,
        orgao_concedente=c.orgao_concedente,
        objeto=c.objeto,
        situacao=c.situacao,
        valor_total=float(c.valor_total) if c.valor_total else None,
        valor_repasse=float(c.valor_concedente) if c.valor_concedente else None,
        valor_empenhado=float(c.valor_emenda_parlamentar) if c.valor_emenda_parlamentar else None,
        valor_desembolsado=float(c.valor_repassado) if c.valor_repassado else None,
        # `is not None` SO nesta linha do serializador da lista: `0` e falso em
        # Python e NULO saia igual a ZERO REAL, fazendo a lista discordar do
        # modal em 180 linhas. NAO estender as vizinhas (valor_total,
        # valor_repasse, valor_desembolsado): `valor_repasse` = 0 faria a base
        # do calculo de "Repassado %" virar falsy e a coluna sumiria de linhas
        # que hoje mostram porcentagem. Unico consumidor conferido: a celula
        # "Contrapartida" em dashboard/convenios/page.tsx.
        valor_contrapartida=float(c.valor_contrapartida) if c.valor_contrapartida is not None else None,
        dt_inicio=c.dt_vigencia_inicial,
        dt_fim_vigencia=c.dt_vigencia_atual or c.dt_vigencia_final,
        dias_restantes=dias,
        ano=c.ano,
        etapa_sigcon=c.etapa_sigcon,
        etapa_sigcon_nr=c.etapa_sigcon_nr,
        fonte=c.fonte,
        tipo_programa=c.tipo_programa,
        banco=c.banco,
        agencia=c.agencia,
        conta_corrente=c.conta_corrente,
        saldo_bancario=float(c.saldo_bancario) if c.saldo_bancario else None,
        dt_saldo=c.dt_saldo,
        nr_sei=c.nr_sei,
        dt_empenho=c.dt_empenho,
        dt_desembolso=c.dt_desembolso,
        nr_proposta=nr_proposta or None,
        nr_plano_trabalho=nr_plano,
        nr_instrumento=nr_instrumento or None,
        nr_siafi=c.nr_siafi,
    )


@router.get("/situacoes", dependencies=[exige("convenios.ver")])
async def list_situacoes(
    municipio_id: Optional[int] = None,
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None, description="Multi-select fonte — a MESMA da lista"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    q = select(ConvenioEstadual.situacao).distinct().where(ConvenioEstadual.situacao.is_not(None))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    # A MESMA regra da lista, e nao mais uma copia dela. Sem `fontes` continua
    # sendo "tudo menos FNS" — identico ao que estava aqui. COM `fontes`, passa a
    # acompanhar: antes o dropdown aplicava o anti-FNS SEMPRE, entao escolher
    # Fonte=FNS abria a caixa de situacoes VAZIA enquanto a tela mostrava as
    # linhas do FNS atras. O `.strip()` fica: a lista filtra `situacao.in_(...)`
    # sem aparar, e tirar daqui faria a selecao nao casar.
    q = q.where(_cond_fonte(fonte, fontes))
    r = await db.execute(q)
    return sorted({row[0].strip() for row in r.all() if row[0]})


@router.get("/anos", dependencies=[exige("convenios.ver")])
async def list_anos(
    municipio_id: Optional[int] = None,
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None, description="Multi-select fonte — a MESMA da lista"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    # Mesma regra da lista (ver /situacoes): sem escolha, FNS fica de fora; com
    # Fonte=FNS marcada, os anos do FNS aparecem em vez de o dropdown mentir.
    q = (select(ConvenioEstadual.ano).distinct()
         .where(ConvenioEstadual.ano.is_not(None))
         .where(_cond_fonte(fonte, fontes)))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    r = await db.execute(q)
    return sorted({int(row[0]) for row in r.all() if row[0]}, reverse=True)


@router.get("/fontes", dependencies=[exige("convenios.ver")])
async def list_fontes(
    municipio_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """AS FONTES QUE ESTE MUNICIPIO TEM DE VERDADE.

    A lista era chumbada no frontend em ["SIGCON","FNS"]. Num municipio do ES a
    unica opcao que devolvia linha era o FNS — que nao e convenio estadual — e
    os convenios do GConv-ES nao tinham opcao nenhuma (25 linhas no Trust, em
    Anchieta, Guarapari e Conceicao da Barra). E em 39 dos 65 municipios dos
    tres clientes a opcao "SIGCON-MG" oferecida devolvia ZERO.

    Derivar do dado, e nao chumbar "GCONV-ES" ao lado dos outros, e o que
    impede o defeito de se repetir quando entrar o coletor de GO ou TO."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    q = select(func.coalesce(ConvenioEstadual.fonte, "SIGCON-MG")).distinct()
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    vistas = {str(r[0]).strip() for r in (await db.execute(q)).all() if r[0]}
    if "SIGCON-MG" in vistas:   # 'SIGCON' e a mesma coisa: nao oferecer as duas
        vistas.discard("SIGCON")
    # FNS SEMPRE POR ULTIMO. `sorted` puro poria "FNS" no topo do dropdown em
    # TODO municipio, promovendo a unica origem que NAO e convenio estadual ao
    # primeiro lugar — o contrario do que esta correcao existe para fazer.
    return sorted(vistas, key=lambda f: (1 if "FNS" in f.upper() else 0, f))


@router.get("", response_model=ConvenioListResponse,
            dependencies=[exige("convenios.ver")])
async def list_convenios(
    municipio_id: Optional[int] = None,
    # Os plurais convivem com os singulares de proposito: e o mesmo padrao de
    # `situacoes`/`situacao` e de routers/parlamentares.py. Link antigo, KPI do
    # dashboard e integracao que ainda mandam o singular continuam funcionando.
    ano: Optional[int] = None,
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    situacao: Optional[str] = None,
    situacoes: Optional[list[str]] = Query(None, description="Multi-select de situacao (match exato)"),
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = Query(None, description="Multi-select fonte"),
    vigencia: Optional[str] = Query(None, description="vence60 | vence120 | prestacao"),
    vigencias: Optional[list[str]] = Query(None, description="Multi-select de vigencia (uniao)"),
    pagamento: Optional[str] = Query(None, description="pago | parcial | nao_pago (via valor_repassado)"),
    pagamentos: Optional[list[str]] = Query(None, description="Multi-select de pagamento (uniao)"),
    # PERIODO LIVRE. Filtra pelo FIM DA VIGENCIA — decisao do dono, e a mesma
    # semantica ja usada em routers/transferegov.py (`vig_fim_de`/`vig_fim_ate`),
    # porque e a pergunta que a equipe faz de verdade: "o que vence entre marco
    # e outubro". Um lado so e valido ("a partir de marco").
    vig_fim_de: Optional[date] = Query(None, description="Fim de vigencia >= esta data"),
    vig_fim_ate: Optional[date] = Query(None, description="Fim de vigencia <= esta data"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    # Teto igual ao das Emendas Estaduais (le=2000). A tela do SIGCON agrupa
    # por ano num cartao por exercicio, e com teto de 100 o cartao contava so
    # o que cabia na pagina — "12 convenio(s) nesta pagina" ao lado de uma
    # tela vizinha que mostra o ano inteiro. Sao dois menus colados.
    per_page: int = Query(20, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    q = select(ConvenioEstadual)
    q_count = select(func.count()).select_from(ConvenioEstadual)

    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
        q_count = q_count.where(ConvenioEstadual.municipio_id == municipio_id)
    _anos = anos or ([ano] if ano else [])
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
        q_count = q_count.where(ConvenioEstadual.ano.in_(_anos))
    if situacoes:
        q = q.where(ConvenioEstadual.situacao.in_(situacoes))
        q_count = q_count.where(ConvenioEstadual.situacao.in_(situacoes))
    elif situacao:
        q = q.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
        q_count = q_count.where(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
    _pagamentos = pagamentos or ([pagamento] if pagamento else [])
    if _pagamentos:
        vr = ConvenioEstadual.valor_repassado
        vc = ConvenioEstadual.valor_concedente
        # UNIAO, nao intersecao: marcar "pago" e "parcial" tem que trazer os
        # dois grupos. Com AND o resultado seria sempre vazio, porque as
        # condicoes se excluem — filtro que devolve zero parece base sem dado.
        _regras = {
            "pago":     and_(vr.is_not(None), vr > 0, vc.is_not(None), vr >= vc),
            "parcial":  and_(vr.is_not(None), vr > 0, or_(vc.is_(None), vr < vc)),
            "nao_pago": or_(vr.is_(None), vr == 0),
        }
        conds = [_regras[p] for p in _pagamentos if p in _regras]
        if conds:
            pcond = conds[0] if len(conds) == 1 else or_(*conds)
            q = q.where(pcond)
            q_count = q_count.where(pcond)
    # Esta e a tela de CONVENIOS ESTADUAIS. `convenios_estadual` tambem guarda
    # PROPOSTAS do FNS (saude), que NAO sao convenio e tem tela propria — por
    # isso, sem escolha de fonte, elas ficam de fora.
    #
    # O bloco anterior tinha uma variavel `_asked_fns` que significava "o caller
    # citou FNS" e, quando verdadeira, desligava a exclusao para TODAS as fontes
    # juntas — entao "Marcar tudo" no filtro devolvia um conjunto que nao era
    # nem o padrao nem a uniao pedida. Agora a regra e uma so, em `_cond_fonte`.
    _cf = _cond_fonte(fonte, fontes)
    q = q.where(_cf)
    q_count = q_count.where(_cf)
    _vigencias = vigencias or ([vigencia] if vigencia else [])
    if _vigencias:
        hoje = date.today()
        dv = ConvenioEstadual.dt_vigencia_atual
        # UNIAO pelo mesmo motivo do pagamento. Note que "vence60" e um
        # SUBCONJUNTO de "vence120": marcar os dois e igual a marcar so o 120,
        # e isso e o esperado — nao ha o que "somar" alem do maior.
        _regras = {
            "vence30":   and_(dv >= hoje, dv <= hoje + timedelta(days=30)),
            "vence60":   and_(dv >= hoje, dv <= hoje + timedelta(days=60)),
            "vence90":   and_(dv >= hoje, dv <= hoje + timedelta(days=90)),
            "vence120":  and_(dv >= hoje, dv <= hoje + timedelta(days=120)),
            "prestacao": dv < hoje - timedelta(days=90),
        }
        conds = [_regras[v] for v in _vigencias if v in _regras]
        if conds:
            vcond = conds[0] if len(conds) == 1 else or_(*conds)
            q = q.where(vcond)
            q_count = q_count.where(vcond)
    if vig_fim_de or vig_fim_ate:
        # `dt_vigencia_atual` e a data que a tela mostra e a que o alerta usa;
        # `dt_vigencia_final` e o fim FORMAL, que diverge quando houve aditivo.
        # Filtrar pela primeira mantem o filtro coerente com a coluna "Fim da
        # Vigencia" — filtro que discorda da tela destroi a confianca no numero.
        dv = func.coalesce(ConvenioEstadual.dt_vigencia_atual,
                           ConvenioEstadual.dt_vigencia_final)
        if vig_fim_de:
            q = q.where(dv >= vig_fim_de)
            q_count = q_count.where(dv >= vig_fim_de)
        if vig_fim_ate:
            q = q.where(dv <= vig_fim_ate)
            q_count = q_count.where(dv <= vig_fim_ate)
    if search:
        term = f"%{search}%"
        search_filter = or_(
            ConvenioEstadual.objeto.ilike(term),
            # `objetivo` tambem: no dialeto do ES a descricao vive NESTA coluna e
            # `objeto` guarda o codigo do processo. Sem isto, buscar "praca" ou
            # "ambulancia" no Trust devolve ZERO com o convenio na tela ao lado.
            # No-op em MG (objetivo e NULO em 869 de 869 linhas); no ES leva
            # PAVIMENTA de 0 para 3 resultados e PRACA de 0 para 5.
            ConvenioEstadual.objetivo.ilike(term),
            ConvenioEstadual.nr_sigcon.ilike(term),
            ConvenioEstadual.nr_siafi.ilike(term),
            ConvenioEstadual.nr_plano_trabalho.ilike(term),
            ConvenioEstadual.raw_data["nr_proposta"].astext.ilike(term),
            ConvenioEstadual.raw_data["nr_instrumento"].astext.ilike(term),
            ConvenioEstadual.raw_data["nr_plano"].astext.ilike(term),
            ConvenioEstadual.raw_data["nr_plano_sigcon"].astext.ilike(term),
            # O numero publicado do ES vive em `numOriginal` (`nr_instrumento` e
            # NULO nas 25 de 25 linhas do GConv). Sem esta linha o modal passa a
            # exibir "004/2026" e a busca por "004/2026" devolve ZERO com o
            # convenio na lista atras — o mesmo defeito que a busca por
            # `objetivo` fechou no PR anterior. E mais um ramo de OR: so pode
            # aumentar o resultado, e a chave nao existe em nenhuma linha
            # SIGCON-MG nem FNS.
            ConvenioEstadual.raw_data["numOriginal"].astext.ilike(term),
        )
        q = q.where(search_filter)
        q_count = q_count.where(search_filter)

    total = (await db.execute(q_count)).scalar() or 0

    q = q.order_by(ConvenioEstadual.dt_publicacao.desc().nullslast())
    q = q.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(q)
    convs = result.scalars().all()

    # EMENDA vinculada (direcao reversa de #3): o convenio mostra que TEM emenda.
    # O numero da indicacao vem de _scrape_indicacoes (raw_data->>'nr_indicacao' e a
    # lista raw_data->'indicacoes'). Uma consulta EM LOTE casa (municipio, indicacao)
    # -> emenda; vazio ate o scraper popular. Custo: 1 query por pagina.
    def _inds_do(c) -> set[str]:
        raw = c.raw_data if isinstance(c.raw_data, dict) else {}
        out: set[str] = set()
        s = (raw.get("nr_indicacao") or "").strip()
        if s:
            out.add(s)
        lst = raw.get("indicacoes")
        if isinstance(lst, list):
            for it in lst:
                if isinstance(it, dict):
                    v = (it.get("nr_indicacao") or "").strip()
                    if v:
                        out.add(v)
        return out

    pares = {(c.municipio_id, ind) for c in convs for ind in _inds_do(c)}
    emap: dict = {}
    if pares:
        muns = sorted({m for m, _ in pares})
        inds = sorted({i for _, i in pares})
        muns_lit = "{" + ",".join(str(m) for m in muns) + "}"
        inds_lit = "{" + ",".join('"' + i.replace('"', '') + '"' for i in inds) + "}"
        rows = (await db.execute(text("""
            SELECT municipio_id, nr_indicacao, beneficiario, tipo_atendimento, nome_responsavel
            FROM emendas_estaduais
            WHERE municipio_id = ANY(CAST(:muns AS INT[]))
              AND nr_indicacao = ANY(CAST(:inds AS TEXT[]))
        """), {"muns": muns_lit, "inds": inds_lit})).all()
        for r in rows:
            obj = f"{r[2] or ''} {r[3] or ''}".strip() or (r[4] or "")
            emap[(r[0], r[1])] = (r[1], obj)

    items = []
    for c in convs:
        resp = estadual_to_response(c)
        if emap:
            for ind in _inds_do(c):
                e = emap.get((c.municipio_id, ind))
                if e:
                    resp.emenda_nr, resp.emenda_objeto = e
                    break
        items.append(resp)

    # Sort: vigentes ASC primeiro, vencidos depois (|dias| ASC = mais recentes primeiro), NULL ao final
    def _sort_key(x):
        d = x.dias_restantes
        if d is None:
            return (2, 0)
        if d >= 0:
            return (0, d)
        return (1, -d)
    items.sort(key=_sort_key)

    # Frescor da coleta SIGCON deste municipio, para o selo "Atualizado em" da
    # tela (regra de honestidade centralizada em services/coleta.py).
    coleta_em, coleta_falhas = (await frescor_coleta(db, municipio_id, ("sigcon",))
                                if municipio_id else (None, 0))

    pages = math.ceil(total / per_page) if total > 0 else 1
    return ConvenioListResponse(items=items, total=total, page=page, per_page=per_page,
                                pages=pages, coleta_em=coleta_em, coleta_falhas=coleta_falhas)


@router.get("/stats", response_model=ConvenioStats,
            dependencies=[exige("convenios.ver")])
async def convenio_stats(
    municipio_id: Optional[int] = None,
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    _anos = anos or ([ano] if ano else [])
    stats = ConvenioStats()
    # FNS (saude) mora na mesma tabela mas nao e convenio estadual — fora dos KPIs.
    _sem_fns = or_(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%"))

    q = select(
        func.count().label("cnt"),
        func.coalesce(func.sum(ConvenioEstadual.valor_total), 0).label("total"),
    ).where(_sem_fns)
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
    row = (await db.execute(q)).one()
    stats.total_convenios = row.cnt
    stats.valor_total = float(row.total)
    stats.por_esfera["estadual"] = row.cnt

    q = (select(ConvenioEstadual.situacao, func.count())
         .where(_sem_fns).group_by(ConvenioEstadual.situacao))
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
    for sit, cnt in (await db.execute(q)).all():
        if sit:
            stats.por_situacao[sit] = cnt

    return stats


@router.get("/alertas", response_model=list[AlertaVigencia],
            dependencies=[exige("convenios.ver")])
async def alertas_vigencia(
    municipio_id: Optional[int] = None,
    dias: int = Query(120, ge=1),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    # O nucleo ja normaliza com `anos_list()`, que aceita int OU lista — aqui
    # so falta a assinatura do FastAPI deixar a lista chegar.
    return await query_alertas_vigencia(db, municipio_id, dias, anos or ano)


async def query_alertas_vigencia(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    dias: int = 120,
    ano: Optional[int] = None,
    municipio_ids: Optional[list[int]] = None,
) -> list:
    """Nucleo dos alertas de vigencia (<= `dias`), SEM gate de auth. Reusado pelo
    endpoint /api/convenios/alertas e pelo Painel Executivo.

    `municipio_ids` (lista) = escopo CONSOLIDADO (`= ANY(:mids)`), usado quando
    `municipio_id` (unico) e None. Ambos None = todos (comportamento original).

    `ano` aceita int (legado) ou lista de anos — ver services.bi.anos_list."""
    _anos = anos_list(ano)
    limite = date.today() + timedelta(days=dias)
    alertas = []

    q = select(ConvenioEstadual).where(
        ConvenioEstadual.dt_vigencia_atual <= limite,
        ConvenioEstadual.dt_vigencia_atual >= date.today(),
    )
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    elif municipio_ids:
        q = q.where(ConvenioEstadual.municipio_id.in_(list(municipio_ids)))
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
    q = q.order_by(ConvenioEstadual.dt_vigencia_atual.asc())
    for c in (await db.execute(q)).scalars().all():
        dias_rest = (c.dt_vigencia_atual - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="estadual", nr_sigcon=c.nr_sigcon,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy)
    if municipio_id or municipio_ids:
        from datetime import datetime as _dt
        if municipio_id:
            _mun_sql = "municipio_id = :m"; _vp = {"m": municipio_id}
        else:
            _mun_sql = "municipio_id = ANY(:mids)"; _vp = {"mids": list(municipio_ids)}
        _vsql = "AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""
        if _anos:
            _vp["anos_txt"] = [str(a) for a in _anos]
        vol = await db.execute(text(f"""
            SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia
            FROM transferegov_propostas WHERE {_mun_sql} {_vsql}
        """), _vp)
        for row in vol.fetchall():
            dtf = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dtf = _dt.strptime(str(row[5]).strip()[:10], fmt).date(); break
                except (ValueError, AttributeError, TypeError):
                    continue
            if not dtf or not (date.today() <= dtf <= limite):
                continue
            alertas.append(AlertaVigencia(
                id=0, esfera="voluntaria", nr_convenio=row[1] or row[0],
                nr_sigcon=row[0], objeto=row[2], orgao_concedente=row[3],
                dt_fim_vigencia=dtf, dias_restantes=(dtf - date.today()).days,
                valor_total=None, situacao=row[4],
            ))

    alertas.sort(key=lambda x: x.dias_restantes)
    return alertas


@router.get("/prestacao-contas", response_model=list[AlertaVigencia],
            dependencies=[exige("convenios.ver")])
async def alertas_prestacao_contas(
    municipio_id: Optional[int] = None,
    dias: int = Query(90, ge=1, description="Dias minimos apos o vencimento"),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Convenios vencidos ha mais de `dias` (default 90) -> prestacao de contas obrigatoria."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")
    return await query_prestacao_contas(db, municipio_id, dias, anos or ano)


async def query_prestacao_contas(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    dias: int = 90,
    ano: Optional[int] = None,
    municipio_ids: Optional[list[int]] = None,
) -> list:
    """Nucleo da prestacao de contas vencida (+`dias`), SEM gate de auth. Reusado
    pelo endpoint /api/convenios/prestacao-contas e pelo Painel Executivo.

    `municipio_ids` (lista) = escopo CONSOLIDADO (`= ANY(:mids)`), usado quando
    `municipio_id` (unico) e None. Ambos None = todos (comportamento original).

    `ano` aceita int (legado) ou lista de anos — ver services.bi.anos_list."""
    _anos = anos_list(ano)
    corte = date.today() - timedelta(days=dias)
    alertas = []

    q = select(ConvenioEstadual).where(ConvenioEstadual.dt_vigencia_atual < corte)
    if municipio_id:
        q = q.where(ConvenioEstadual.municipio_id == municipio_id)
    elif municipio_ids:
        q = q.where(ConvenioEstadual.municipio_id.in_(list(municipio_ids)))
    if _anos:
        q = q.where(ConvenioEstadual.ano.in_(_anos))
    q = q.order_by(ConvenioEstadual.dt_vigencia_atual.desc())
    for c in (await db.execute(q)).scalars().all():
        dias_rest = (c.dt_vigencia_atual - date.today()).days
        alertas.append(AlertaVigencia(
            id=c.id, esfera="estadual", nr_sigcon=c.nr_sigcon,
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy)
    if municipio_id or municipio_ids:
        from datetime import datetime as _dt
        if municipio_id:
            _mun_sql = "municipio_id = :m"; _vp = {"m": municipio_id}
        else:
            _mun_sql = "municipio_id = ANY(:mids)"; _vp = {"mids": list(municipio_ids)}
        _vsql = "AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""
        if _anos:
            _vp["anos_txt"] = [str(a) for a in _anos]
        vol = await db.execute(text(f"""
            SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia
            FROM transferegov_propostas WHERE {_mun_sql} {_vsql}
        """), _vp)
        for row in vol.fetchall():
            dtf = None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dtf = _dt.strptime(str(row[5]).strip()[:10], fmt).date(); break
                except (ValueError, AttributeError, TypeError):
                    continue
            if not dtf or dtf >= corte:
                continue
            alertas.append(AlertaVigencia(
                id=0, esfera="voluntaria", nr_convenio=row[1] or row[0],
                nr_sigcon=row[0], objeto=row[2], orgao_concedente=row[3],
                dt_fim_vigencia=dtf, dias_restantes=(dtf - date.today()).days,
                valor_total=None, situacao=row[4],
            ))

    # Mais recentemente vencidos primeiro (|dias| menor primeiro)
    alertas.sort(key=lambda x: -x.dias_restantes)
    return alertas


# Workflow SIGCON-MG (etapas oficiais do portal Pesquisa Unificada)
SIGCON_WORKFLOW = [
    "CADASTRAMENTO",
    "PREENCHIMENTO DE CHECKLIST",
    "VALIDACAO DA PROPOSTA PELO RESPONSAVEL LEGAL",
    "ANALISE - CHECKLIST DE CELEBRACAO",
    "RECEBIDO PELO ORGAO / ANALISE TECNICA / ADEQUACAO",
    "ANALISE JURIDICA",
    "AGUARDANDO ENVIO PARA SEGOV",
    "SEGOV ANALISE",
    "PLANO AUTORIZADO",
    "ANEXACAO DO INSTRUMENTO",
    "PROCESSO DE ASSINATURA - CONVENENTE/OSC",
    "PROCESSO DE ASSINATURA - CONCEDENTE/OEEP",
    "PROCESSO DE PUBLICACAO",
    "INSTRUMENTO CADASTRADO / VIGENTE",
    "INSTRUMENTO ENCERRADO",
]


def _norm_workflow(s: str) -> str:
    if not s: return ""
    import unicodedata as u
    return "".join(c for c in u.normalize("NFKD", s.upper()) if not u.combining(c)).strip()


def _build_workflow_state(situacao: str | None) -> dict | None:
    sit_norm = _norm_workflow(situacao or "")
    aliases = {
        "EM VIGOR": "INSTRUMENTO CADASTRADO / VIGENTE",
        "VIGENTE": "INSTRUMENTO CADASTRADO / VIGENTE",
        "ENCERRADO": "INSTRUMENTO ENCERRADO",
        "CADASTRAMENTO": "CADASTRAMENTO",
        "PREENCHIMENTO CHECKLIST": "PREENCHIMENTO DE CHECKLIST",
        "ANALISE CELEBRACAO": "ANALISE - CHECKLIST DE CELEBRACAO",
        "ANALISE TECNICA": "RECEBIDO PELO ORGAO / ANALISE TECNICA / ADEQUACAO",
        "PLANO AUTORIZADO": "PLANO AUTORIZADO",
        "PROPOSTA/PLANO DE TRABALHO ENVIADO PARA ANALISE": "PREENCHIMENTO DE CHECKLIST",
        "PROPOSTA/PLANO DE TRABALHO REJEITADOS": "ANALISE - CHECKLIST DE CELEBRACAO",
        # Etapa que EXISTE na régua e faltava no mapa: 8 convênios paravam em
        # "0 de 15" estando numa etapa real do fluxo.
        "ADEQUACAO": "RECEBIDO PELO ORGAO / ANALISE TECNICA / ADEQUACAO",
    }
    target = aliases.get(sit_norm, sit_norm)
    cur_idx = -1
    for i, step in enumerate(SIGCON_WORKFLOW):
        if _norm_workflow(step) == target:
            cur_idx = i
            break
    # ⚠️ SITUACAO QUE NAO E ETAPA -> SEM TRILHA, e nao trilha zerada.
    #
    # Antes, `cur_idx = -1` devolvia as 15 etapas todas apagadas, e o modal
    # escrevia "0 de 15 etapa(s) concluída(s)". Isso e uma AFIRMACAO — diz que o
    # processo nao andou — e ela era falsa em 3.149 linhas de FNS (proposta
    # "Paga" abrindo com zero etapas) e em 234 convenios CANCELADOS do SIGCON,
    # que obviamente andaram antes de serem cancelados.
    #
    # Devolver None faz o front esconder a secao inteira sozinho, que e a
    # leitura honesta: nao sabemos a etapa, entao nao desenhamos regua nenhuma.
    #
    # NAO mapear CANCELADO para um indice: cancelamento nao e etapa do fluxo, e
    # encaixa-lo faria o sistema afirmar um progresso que tambem nao existe.
    if cur_idx < 0:
        return None
    return {
        "current_index": cur_idx,
        "current_label": situacao,
        "steps": [
            {"label": s, "completed": cur_idx >= i, "current": cur_idx == i}
            for i, s in enumerate(SIGCON_WORKFLOW)
        ],
    }


@router.get("/estadual/{conv_id}", dependencies=[exige("convenios.ver")])
async def get_convenio_estadual_detail(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Detalhes ricos de um convenio estadual: campos + workflow SIGCON + raw_data util."""
    # Este endpoint nao checava NADA alem de estar logado, enquanto a LISTA que
    # leva ate ele (`GET /api/convenios`) sempre checou as duas coisas. Quem
    # soubesse o id — e id e um inteiro sequencial — lia o convenio inteiro de
    # qualquer municipio do tenant: objeto, valores, dados bancarios (banco,
    # agencia, conta) e o `raw_data` cru do SIGCON.
    #
    # SAO DOIS GATES e o segundo nao e repeticao do primeiro. `ensure_tela` diz
    # que a pessoa pode mexer com SIGCON; `ensure_dono` diz que ESTE convenio
    # pertence a um municipio que ela enxerga. Sem o segundo, quem tem a tela
    # tem a tela do tenant INTEIRO — e "detalhe por id" e justamente onde isso
    # aparece, porque a listagem filtra por municipio e o detalhe nao filtrava
    # nada.
    authz.exigir_tela(current, "convenios")
    # Custa um SELECT de uma coluna so. Registro inexistente devolve None e NAO
    # vira 403: quem responde por "nao achei" continua sendo o 404 abaixo.
    await authz.ensure_dono(db, "convenios_estadual", "id", conv_id, current)
    q = select(ConvenioEstadual).where(ConvenioEstadual.id == conv_id)
    c = (await db.execute(q)).scalar_one_or_none()
    if not c:
        from fastapi import HTTPException
        raise HTTPException(404, "Convênio não encontrado")

    raw = c.raw_data if isinstance(c.raw_data, dict) else {}
    nr_proposta = raw.get("nr_proposta")
    nr_instrumento = raw.get("nr_instrumento")
    if not nr_instrumento and c.nr_sigcon and re.match(r"^\d{8,12}/\d{4}$", c.nr_sigcon):
        nr_instrumento = c.nr_sigcon
    # DIALETO DO ES. O GConv-ES nao tem `nr_instrumento` no raw_data e o
    # `nr_sigcon` e uma chave sintetica nossa ("GCONV-ES-<cod>"), sem barra —
    # entao os CINCO numeros da secao Identificacao saiam "-" e o titulo do
    # modal era um travessao solitario nas 25 de 25 linhas do Trust.
    # O numero publicado vem em `numOriginal` ("004/2026"), presente em 25 de
    # 25. Texto livre na origem: 6 vem como "TERMO DE CONVENIO 066/2025" — e o
    # que o portal publica, e exibir verbatim e honesto (a celula trunca com
    # tooltip). NAO serve como chave: 23 valores distintos em 25 linhas.
    if not nr_instrumento and (c.fonte or "").upper().startswith("GCONV"):
        nr_instrumento = str(raw.get("numOriginal") or "").strip() or None
    # Nº Convenio Publicado = numero do INSTRUMENTO (formato XXXXXXXXXX/YYYY).
    # Quando o registro veio do scraper, nr_sigcon eh o SIAFI numerico -> nao usar.
    #
    # E NUNCA o do FNS: la o `nr_sigcon` e uma CHAVE SINTETICA NOSSA
    # ("FNS-316500-2017-AMBULANC-PROGRA-N/A-900194d2") — o `nuProcesso` vem
    # "N/A" e entrega justamente a barra que este teste procura. Medido: 3.194
    # linhas (freitas 1.719, trust 1.427, montesiao 48) exibiam essa string com
    # rotulo de numero oficial de convenio, e como titulo do modal.
    #
    # A regra e "TUDO MENOS FNS", a mesma polaridade de `_FNS_EXCL`, e NAO uma
    # lista de permissao por fonte: numero publicado nao e conceito do SIGCON, e
    # do convenio — quando entrar o coletor de GO/TO o fallback continua valendo
    # sozinho, em vez de nascer desligado em silencio. Preserva as 375 linhas
    # SIGCON que dependem dele (fonte NULA entra: "" nao contem "FNS").
    _e_fns = "FNS" in (c.fonte or "").upper()
    nr_conv_pub = nr_instrumento or (
        c.nr_sigcon if not _e_fns and c.nr_sigcon and "/" in c.nr_sigcon else None)

    dias_vig = None
    if c.dt_vigencia_inicial and (c.dt_vigencia_atual or c.dt_vigencia_final):
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        dias_vig = (dt_fim - c.dt_vigencia_inicial).days

    dias_rest = None
    dias_rest_label = None
    if c.dt_vigencia_atual or c.dt_vigencia_final:
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        dias_rest = (dt_fim - date.today()).days
    # (a chamada a `_dias_restantes_sigcon` saiu daqui junto com o helper: o
    #  numero passa a vir da mesma data que a celula ao lado exibe)
    if dias_rest is not None:
        if dias_rest < -90:
            dias_rest_label = "VENCIDO +90 DIAS - PRESTACAO DE CONTAS"
        elif dias_rest < 0:
            dias_rest_label = "VENCIDO"

    # "Municipio" pela CHAVE ESTRANGEIRA, e nao pelo texto solto do portal.
    # Mesma resolucao que o BI ja faz (services/bi_abas.py, LEFT JOIN municipios)
    # — a tela de Convenios era a unica fora do padrao. Medido: `municipio_id`
    # preenchido em 100% das linhas dos 3 tenants e ZERO FK orfa, entao isto
    # nunca fica pior que o raw.
    #
    # SEM FALLBACK PARA O RAW, de proposito e por tres motivos medidos:
    #  1. no ES a chave `municipio` NAO EXISTE (25 de 25 linhas do Trust
    #     mostravam "-"), e a equivalente `nomeMunicipio` vale literalmente
    #     "SEM MUNICIPIO INFORMADO" — trocaria "-" honesto por afirmacao falsa;
    #  2. no SIGCON o texto vem em caixa alta sem acento ("CORREGO DANTA" contra
    #     "Corrego Danta" no resto do sistema) e a fonte e inconsistente consigo
    #     mesma ("CONCEICAO DO PARA" 42x contra "CONCEIÇAO DO PARA" 18x, o MESMO
    #     municipio);
    #  3. em 2 linhas do freitas o raw CONTRADIZ o municipio pelo qual a tela
    #     filtrou (id 45670 raw="PEQUI" com FK=Bom Despacho; id 26479
    #     raw="PERDIGAO" com FK=Nova Serrana) — o gestor filtrava uma cidade e
    #     lia o nome de outra dentro do modal.
    municipio_nome = None
    if c.municipio_id:
        municipio_nome = (await db.execute(
            select(Municipio.nome).where(Municipio.id == c.municipio_id)
        )).scalar_one_or_none()

    return {
        "id": c.id,
        "esfera": "estadual",
        "nr_convenio_publicado": nr_conv_pub,
        "nr_siafi": c.nr_siafi,
        "nr_proposta": nr_proposta,
        "nr_plano_trabalho": c.nr_plano_trabalho,
        "nr_instrumento": nr_instrumento,
        "status": c.situacao,
        "dt_assinatura": c.dt_assinatura,
        "dt_publicacao": c.dt_publicacao,
        "dias_vigencia_atual": dias_vig,
        "vigencia_inicial": c.dt_vigencia_inicial,
        "vigencia_atual": c.dt_vigencia_atual or c.dt_vigencia_final,
        "dias_restantes": dias_rest,
        "dias_restantes_label": dias_rest_label,
        "titulo": c.objeto,
        "objetivo": c.objetivo,
        # "prestacao_contas" REMOVIDO: as DUAS chaves tem zero ocorrencia no
        # raw_data de qualquer fonte dos tres tenants (varridas as 72 chaves do
        # SIGCON e as 46 do GCONV-ES). Era uma cadeia de dois elos mortos que
        # rendia "-" em 894 de 894 linhas visiveis, num campo de largura dupla e
        # justamente o que o gestor mais procura quando um convenio vence.
        # O sinal que o sistema REALMENTE tem ja aparece na celula vizinha:
        # "Dias Restantes" exibe o rotulo oficial VENCIDO +90 DIAS - PRESTACAO DE
        # CONTAS em 282 linhas. Nao re-derivar aqui: duplicaria a celula ao lado
        # com risco de divergirem, e o derivado so sabe que o PRAZO venceu, nao
        # se a prestacao foi entregue.
        "concedente_orgao": c.orgao_concedente,
        "convenente_nome": c.convenente_nome or raw.get("convenente"),
        "municipio_nome": municipio_nome,
        # "tipo_convenente" REMOVIDO — o campo era um palpite disfarçado de dado.
        #
        # A expressão era
        #     raw.get("tipo_beneficiario") or raw.get("tipo_convenente") or "ADMINISTRACAO MUNICIPAL"
        # com o elo do meio SEM NENHUMA ocorrência em qualquer linha de qualquer
        # tenant (código morto). Na prática: o que a fonte disse, ou o literal.
        #
        # Medido antes de remover: a fonte informa em 75 linhas de 4.093 (freitas
        # 71, montesiao 4, trust ZERO). Nas outras 4.018 o sistema escrevia
        # "Administração Municipal" por conta própria — inclusive onde o
        # convenente é "FMS DE ANCHIETA", um Fundo Municipal de Saúde com CNPJ
        # próprio, que administração municipal não é.
        #
        # E não valia nem como aproximação útil: nas 75 vezes em que a fonte
        # falou, ela disse "ADMINISTRAÇÃO MUNICIPAL" em 75 — ou seja, o campo
        # NUNCA distinguiu nada. Era redundante quando acertava e enganoso
        # quando errava, logo abaixo de "Convenente / OSC", que já mostra
        # "PREFEITURA MUNICIPAL DE GUARAPARI" ou "FMS DE ANCHIETA" — onde a
        # natureza da entidade está escrita, e correta.
        #
        # A COLETA CONTINUA: `ingestion/sigcon_scraper.py:379` segue gravando
        # "Tipo de Beneficiario" em `raw_data.tipo_beneficiario`. Se um dia o
        # campo voltar à tela, volta com o dado real e sem inventar o resto.
        # `if x else None` colapsava ZERO em "sem dado": Decimal(0) e falso em
        # Python. Medido (fonte <> FNS): concedente = 0 em 265 linhas,
        # contrapartida = 0 em 180, total = 0 em 263. Zero informado pela fonte
        # e DADO — e o que separa "o municipio nao poe contrapartida" de "nao
        # sabemos quanto e". Sem isto o front nao consegue parar de inventar
        # "R$ 0,00" sem apagar zero legitimo junto.
        #
        # ⚠️ NAO estender ao serializador da LISTA (o `estadual_to_response` no
        # topo do arquivo): la `valor_repasse` = 0 faria a base virar falsy no
        # calculo de "Repassado %" e a coluna sumiria de linhas que hoje mostram
        # porcentagem.
        "valor_concedente": float(c.valor_concedente) if c.valor_concedente is not None else None,
        "valor_contrapartida": float(c.valor_contrapartida) if c.valor_contrapartida is not None else None,
        "valor_total": float(c.valor_total) if c.valor_total is not None else None,
        # Os `or raw.get(...)` que havia nestas linhas apontavam para chaves com
        # ZERO ocorrencia em 4.093 linhas dos tres tenants (varridas as 72
        # chaves do SIGCON-MG, as 46 do GCONV-ES e as 11 do FNS): "responsavel",
        # "prop_vigencia", "vr_dotacao_compl", "fase_etapa" e "dt_criacao".
        # Elo morto nao e inofensivo: ele PROMETE uma cobertura que nao existe.
        # Foi lendo `proposta_vigencia or prop_vigencia` como "isso ja tem
        # fallback" que o campo real do portal (`proposta_dias_vigencia`, 91
        # linhas) passou despercebido por meses. Nenhum coletor grava as cinco.
        "responsaveis": raw.get("responsaveis"),
        "proposta_vigencia": _proposta_vigencia(raw),
        "valor_dotacao_complementar": raw.get("valor_dotacao_complementar"),
        # A sentinela vira None e o `or c.situacao` — FORA do normalizador, de
        # proposito, porque situacao legitima nunca pode ser anulada — devolve a
        # situacao; ai o guarda que JA EXISTE no modal (`fase_etapa_status !==
        # status`) esconde o bloco sozinho, sem tocar no frontend. Some
        # "Nao ha - Nao ha - Nao ha" (117 linhas) e "- -" (29); ficam inteiros
        # "ALTERAR - ALTERAR - Alterar" (20) e "CELEBRACAO - PROPOSTA -
        # ANALISE - CHECKLIST DE CELEBRACAO" (12).
        "fase_etapa_status": _sem_sentinela_composto(raw.get("fase_etapa_status")) or c.situacao,
        # 181 linhas traziam literalmente "Nao ha" num campo de largura dupla.
        # "Processos Migrados" (20) NAO entra na lista de sentinelas: e fila
        # real do fluxo do portal — ver o comentario de `_SENTINELA_VAZIO`.
        "setor": _sem_sentinela(raw.get("setor")),
        "data_criacao": raw.get("data_criacao"),
        # "Qt. Alteracoes" so e NUMERO quando alguem de fato contou. Tres
        # origens de "0" conviviam na coluna e so uma era zero de verdade: o
        # scraper leu "Quantidade de Alteracoes Concluidas: 0" (81 linhas, zero
        # LEGITIMO, continua "0"); a linha veio do CKAN ou do GCONV-ES, que nao
        # coletam o campo, e a coluna tem DEFAULT 0 (78 linhas); ou o scraper
        # nao abriu o detalhe e a coluna e NULL (703 linhas), que o frontend
        # transformava em 0 com `?? 0`. Somadas, 781 das 899 linhas visiveis
        # afirmavam "0 alteracoes" sem evidencia — inclusive o convenio do
        # Trust com R$ 11,65 mi em aditivos que a propria tela mostra.
        #
        # A EVIDENCIA e `raw_data.qt_alteracoes_str`, que so o scraper grava e
        # so quando o portal informou: existe em 118 linhas e bate com a coluna
        # em 118/118. O `hasattr` que estava aqui era ruido — num objeto do ORM
        # e sempre True.
        #
        # ⚠️ O `> 0` nao e redundancia, e trava: hoje nao muda nenhuma linha,
        # mas as duas pontas PODEM dessincronizar (o scraper grava a chave mesmo
        # com valor vazio, e o upsert preserva a coluna antiga com COALESCE).
        # Sem ele, um convenio com 7 alteracoes REAIS viraria "-" calado.
        # `raw.get(k, "")` e nao `raw.get(k) or ""`: o `or` e falsy para o
        # numero JSON 0 e mataria o zero legitimo se a ingestao mudar de tipo.
        "qt_alteracoes": (
            c.qt_alteracoes
            if (str(raw.get("qt_alteracoes_str", "")).strip().isdigit()
                or (c.qt_alteracoes or 0) > 0)
            else None
        ),
        "ano": c.ano,
        "tp_instrumento": c.tp_instrumento or raw.get("tipo"),
        "fonte": c.fonte,
        # A régua de 15 etapas é do SIGCON-MG e só dela. Aplicá-la a outra fonte
        # inventa histórico: um convênio "Vigente" do Espírito Santo abria com
        # "14 de 15 etapas concluídas" e visto verde em "AGUARDANDO ENVIO PARA
        # SEGOV" e "SEGOV ANALISE" — SEGOV é órgão de MINAS. Eram 25 de 25 do
        # Trust. O alias VIGENTE casava por acidente com a situação que a
        # ingestão do ES deriva das datas (gconv_es.py:81).
        #
        # `fonte` NULA conta como SIGCON: é o que a própria lista faz em
        # :116,133,229, e são linhas legadas legítimas de MG.
        "workflow": (_build_workflow_state(c.situacao)
                     if (c.fonte or "SIGCON-MG").upper().startswith("SIGCON") else None),
        # `raw_data` NÃO volta mais. Cada abertura de modal mandava ao navegador
        # o registro cru inteiro do portal — até 13,7 KB, com domicílio bancário
        # e CNPJ nas linhas do ES — e o componente nunca leu esse campo. Era
        # exatamente o tipo de vazamento que o comentário de :588-599 diz querer
        # evitar. `raw` segue em uso acima, nos campos derivados.
    }


@router.post("/refresh-sigcon", dependencies=[exige("convenios.atualizar")])
async def refresh_sigcon(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Enfileira execucao on-demand do scraper SIGCON-MG (sem depender de plataforma).

    Insere um job 'pending' na tabela `scraper_jobs`. O Worker (Scheduled Task
    no Coolify) roda `ingestion/run_queue_sigcon.py` a cada ~2min, consome o job
    (FOR UPDATE SKIP LOCKED) e executa `run_sigcon_cron.py`. Dedup: nao enfileira
    se ja houver um job 'pending'/'running'.

    Leva ~1-2min ate o resultado aparecer no banco. Frontend deve fazer polling
    em /municipios/{id}/summary apos o trigger.
    """
    # Coleta pesada disparada por quem quiser: o botao vive na tela do SIGCON,
    # mas o endpoint aceitava qualquer sessao autenticada. Uma coleta muda
    # situacao e valores de dezenas de convenios de uma vez e ocupa o worker.
    #
    # SO A TELA, sem municipio, e isso e deliberado: o job enfileirado nao tem
    # recorte de municipio nenhum (`INSERT INTO scraper_jobs (tipo, status)`) —
    # ele recoleta o tenant inteiro. Inventar um `municipio_id` aqui para poder
    # checa-lo seria mudar a logica do endpoint, e nao acrescentar gate.
    authz.exigir_tela(current, "convenios")
    row = (await db.execute(text(
        "INSERT INTO scraper_jobs (tipo, status) "
        "SELECT 'sigcon', 'pending' "
        "WHERE NOT EXISTS ("
        " SELECT 1 FROM scraper_jobs WHERE tipo = 'sigcon' AND status IN ('pending', 'running')"
        ") RETURNING id"
    ))).first()
    await db.commit()
    # Disparar coletor muda o dado que a prefeitura ve: uma coleta pode alterar
    # situacao e valores de dezenas de convenios de uma vez. O pedido fica
    # registrado inclusive quando ele NAO enfileira (dedup) — a pergunta que
    # aparece depois e "quem mandou atualizar antes do numero mudar", e um pedido
    # recusado por ja haver fila tambem responde isso.
    await registrar(
        db, action="coletor.disparo", user=current, request=request,
        target_type="scraper", target_id="sigcon", alvo_nome="SIGCON-MG",
        details={"fonte": "sigcon", "origem": "tela do usuário",
                 "enfileirado": row is not None,
                 "job_id": row[0] if row else None},
    )
    if row is None:
        return {
            "status": "already_queued",
            "message": "Uma atualização do SIGCON já está na fila ou em execução.",
        }
    return {
        "status": "triggered",
        "message": "Scraper SIGCON enfileirado. Os dados serão atualizados em 1-2 minutos.",
        "job_id": row[0],
    }
