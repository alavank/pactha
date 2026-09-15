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
from services.coleta import FRASE_CREDENCIAL, classificar_credencial, frescor_coleta
from services.audit import registrar
# Trava de permissao em MODO AVISO. `ensure_dono` responde a pergunta que
# `ensure_tela` nao responde: "este id e de um municipio que a pessoa enxerga?".
from services import authz
from services.registro_rotas import exige, declarado
from services.bi import anos_list
# ⚠️ O RECORTE DESTA TELA MORA NO SERVICE, e a tela e os tres exports usam a
# MESMA funcao. Ver o cabecalho de `services/convenios_filtro.py` para o
# historico: cada copia deste predicado ja custou um documento errado.
from services import convenios_filtro as filtro
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
# ⚠️ A REGRA DE FONTE MUDOU DE CASA, e o alias abaixo existe só para os dois
# call sites deste arquivo. Ela mora em `services/convenios_filtro.py` junto com
# os outros sete filtros, porque o export precisa da MESMA regra e um service
# não pode importar de um router (routers -> services -> models).
#
# O motivo original de ela existir continua valendo: `convenios_estadual` guarda
# TRÊS origens — SIGCON-MG, GCONV-ES e FNS (propostas de saúde, que NÃO são
# convênio e têm tela própria) — e a regra estava copiada em quatro lugares
# deste arquivo, duplicação que "deixou o export PDF de fora e contar propostas
# de saúde como convênio".
_cond_fonte = filtro.cond_fonte


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
        # ULTIMA ALTERACAO (capturada por _scrape_alteracoes). `situacao` sozinha e
        # generica ("Em vigor") e nao diz em que pe o convenio esta — a tela mostrava
        # so isso. Estes campos deixam o cartao exibir a situacao REAL, como o RM ja faz.
        alteracao_situacao=(raw.get("ultima_alteracao_situacao") or None),
        alteracao_tipo=(raw.get("ultima_alteracao_tipo") or None),
        alteracao_data=(raw.get("ultima_alteracao_data") or None),
        alteracao_titulo=(raw.get("ultima_alteracao_titulo") or None),
        # PRESTACAO DE CONTAS: o estagio em que a prestacao esta, o processo SEI e
        # as datas. Fica ao lado do selo de alteracao porque responde a outra
        # pergunta — a alteracao e sobre o CONVENIO, esta e sobre a ENTREGA.
        prestacao_contas_status=(raw.get("prestacao_contas_status") or None),
        prestacao_contas_data=(raw.get("prestacao_contas_data") or None),
        prestacao_contas_status_data=(raw.get("prestacao_contas_status_data") or None),
        prestacao_contas_sei=(raw.get("prestacao_contas_sei") or None),
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

    # ⚠️ O RECORTE VEM DO SERVICE, e a tela e os tres exports usam A MESMA
    # funcao. Isto aqui eram ~100 linhas de montagem de filtro, e a copia delas
    # no export PDF (a quinta da familia) e o que fazia o documento sair com a
    # base inteira enquanto a tela mostrava o recorte pedido.
    # `tests/test_convenios_filtro.py` compara as assinaturas dos dois lados,
    # para que um parametro novo nao possa nascer so num deles.
    _conds, _ = filtro.condicoes(
        municipio_id=municipio_id, ano=ano, anos=anos,
        situacao=situacao, situacoes=situacoes,
        fonte=fonte, fontes=fontes,
        vigencia=vigencia, vigencias=vigencias,
        pagamento=pagamento, pagamentos=pagamentos,
        vig_fim_de=vig_fim_de, vig_fim_ate=vig_fim_ate,
        search=search,
    )
    for _c in _conds:
        q = q.where(_c)
        q_count = q_count.where(_c)
    total = (await db.execute(q_count)).scalar() or 0

    # ⚠️ ORDENA POR data-ou-ano, e nao so pela data. O coletor do SIGCON gravava
    # `date(ano, 1, 1)` em `dt_publicacao` quando nao conseguia abrir o detalhe —
    # um SUBSTITUTO para esta ordenacao funcionar, guardado na mesma coluna da
    # data de verdade e impresso no modal como "Data Publicação" (15 dos 28
    # convenios de Araujos, medido em 30/08/2026). O substituto saiu; para a
    # ordenacao nao regredir, o proprio SQL faz a queda para 1o de janeiro do
    # `ano` — no lugar onde ela e um criterio de ordem, e nao um fato exibido.
    # ⚠️ A ORDEM TAMBEM MORA NO SERVICE. O export precisa repetir exatamente
    # esta, senao as MESMAS linhas saem embaralhadas em relacao a tela: o
    # `_sort_key` abaixo empata muito (todo NULL na mesma chave) e o `sort` do
    # Python e estavel, entao os empates preservam a ordem de chegada — que e
    # esta. Um export que rode so o WHERE entrega os empates na ordem arbitraria
    # do Postgres.
    q = q.order_by(filtro.ordem())
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
        # asyncpg exige LISTA Python p/ ANY(array), nao string '{...}'.
        rows = (await db.execute(text("""
            SELECT municipio_id, nr_indicacao, beneficiario, tipo_atendimento, nome_responsavel
            FROM emendas_estaduais
            WHERE municipio_id = ANY(CAST(:muns AS INT[]))
              AND nr_indicacao = ANY(CAST(:inds AS TEXT[]))
        """), {"muns": muns, "inds": inds})).all()
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

    # ESTADO DA CREDENCIAL: "nenhum dado" tem tres causas e a tela dizia uma so.
    #
    # ⚠️ DUAS CONSULTAS SEPARADAS, e nao um JOIN. `scraper_municipio_coleta` pode
    # nao existir num tenant novo (Santa Maria/RS foi o primeiro banco criado do
    # zero e expos exatamente esse tipo de schema herdado); juntando as duas, a
    # tabela fragil derrubaria tambem a contagem de credenciais, que e a que
    # sustenta a mensagem principal.
    #
    # ⚠️ `await db.rollback()` nos DOIS except. Sem ele a transacao fica invalida
    # e a LISTAGEM INTEIRA passa a devolver 500 — trocar "tela sem aviso" por
    # "tela quebrada" seria o unico jeito de piorar isto.
    credencial = "ok"
    if municipio_id:
        _n = 0
        try:
            # ⚠️ `municipio_id = :m` e nao "ou escopo de instancia": o coletor do
            # SIGCON faz INNER JOIN em `municipios`, entao credencial sem
            # municipio NUNCA e usada — conta-la diria "cadastrada" sobre um
            # municipio que jamais sera coletado. (E onde o precedente do
            # InvestSUS NAO se copia: la a credencial de instancia vale.)
            # ⚠️ `length(senha_hash) > 0`: o coletor so aceita quando o decrypt
            # devolve algo. Nao decifrar aqui e deliberado — com COFRE_KEY errada
            # o decrypt volta vazio em silencio e a tela afirmaria "cadastrada"
            # enquanto o coletor nao ve nada. O comprimento e o proxy honesto.
            _r = await db.execute(text(
                "SELECT count(*) FROM cofre_senhas "
                "WHERE municipio_id = :m "
                "  AND (sistema ILIKE 'SIGCON%' OR automation_key = 'sigcon') "
                "  AND senha_hash IS NOT NULL AND length(senha_hash) > 0"),
                {"m": municipio_id})
            _n = int((_r.scalar() or 0))
        except Exception:
            await db.rollback()
            _n = -1                      # desconhecido: nao acusa nem absolve
        if _n >= 0:
            _tent, _login, _coletou = 0, False, True
            try:
                _r = await db.execute(text(
                    "SELECT coalesce(tentativas, 0), coalesce(ultimo_erro, '') "
                    "FROM scraper_municipio_coleta "
                    "WHERE fonte = 'sigcon' AND municipio_id = :m"), {"m": municipio_id})
                _row = _r.first()
                # Sem linha no rodizio = a primeira coleta ainda nao rodou. E o
                # QUARTO estado: quem acabou de cadastrar a senha via "Nenhum
                # dado encontrado" e concluia que ela nao funcionou.
                _coletou = _row is not None
                if _row:
                    _tent = int(_row[0] or 0)
                    # ⚠️ ERRO DE LOGIN, e nao "falhou". Timeout, portal fora do ar
                    # e erro de parsing NAO sao culpa da senha; acusar a
                    # credencial por uma queda do portal manda o cliente trocar
                    # uma senha que esta certa.
                    _e = (_row[1] or "").lower()
                    _login = any(t in _e for t in ("login", "senha", "credencial",
                                                   "autentic", "usuario"))
            except Exception:
                await db.rollback()
            credencial = classificar_credencial(_n, _tent, _login, houve_coleta=_coletou)

    pages = math.ceil(total / per_page) if total > 0 else 1
    return ConvenioListResponse(items=items, total=total, page=page, per_page=per_page,
                                pages=pages, coleta_em=coleta_em, coleta_falhas=coleta_falhas,
                                credencial=credencial,
                                credencial_aviso=FRASE_CREDENCIAL.get(credencial, ""))


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


# ⭐ DOIS CAMINHOS DE PERMISSAO, e por isso `declarado` no lugar de `exige`:
# `exige()` cobra TODAS as chaves que recebe ("e", nao "ou"), e aqui a regra e
# "ou". Quem decide e o corpo, logo abaixo.
#
# O motivo do "ou": o botao «Vigencias <=120d» do Painel de Indicadores le DESTE
# endpoint, e o dono pediu para liberar SO o monitoramento de vencimento a certas
# pessoas — sem entregar o modulo inteiro de Convenios Estaduais.
@router.get("/alertas", response_model=list[AlertaVigencia],
            dependencies=[declarado("convenios.ver", "vigencias.ver")])
async def alertas_vigencia(
    municipio_id: Optional[int] = None,
    dias: int = Query(120, ge=1),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Multi-select de ano"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # ⚠️ SO quando o pedido NOMEIA um municipio. Sem `municipio_id` o pedido
    # significa "a minha carteira inteira", e quem resolve isso com o recorte
    # certo e o bloco de `permitidos` trinta linhas abaixo — que existe
    # EXATAMENTE para este caso e, ate aqui, era codigo morto.
    #
    # A guarda chamada com None negava ANTES de qualquer checagem de
    # permissao: ela levanta 403 ("Selecione um municipio permitido") para
    # TODO MUNDO que nao seja super-admin, e nega nos DOIS modos de
    # AUTHZ_MODO (ver services/auth.py). Como o botao «Vigencias <=120d» do
    # Painel de Indicadores pede sem municipio (components/bi/VigenciasModal.tsx),
    # ele so funcionava para o super-admin — que e justamente quem testa.
    #
    # MEDIDO NO FREITAS (24/08/2026), no log do freitas-api:
    #   GET /api/convenios/alertas?dias=120 -> 403 Forbidden, em serie
    #   GET /api/bi/alertas?municipio_id=8  -> 200 OK
    # E o modal traduz 403 em «voce nao tem acesso», entao conceder
    # `vigencias.ver` nao mudava NADA na tela e o administrador jurava que a
    # caixinha nova nao pegava. O 403 nunca vinha da permissao.
    #
    # ⚠️ Isto NAO alarga acesso: sem municipio o alcance continua sendo o do
    # `permitidos` abaixo (carteira do usuario; vazia devolve []), e o gate de
    # permissao logo em seguida continua valendo igual.
    if municipio_id is not None:
        ensure_municipio_access(current, municipio_id)
    # ⚠️ A ORDEM IMPORTA, e ela e o que garante "nada muda para quem ja
    # funciona hoje": quem NAO tem a caixinha nova cai exatamente nas duas
    # travas de antes, na mesma sequencia e com as mesmas mensagens. A caixinha
    # `vigencias.ver` so ACRESCENTA um caminho — nunca tira um.
    #
    # `authz.pode` (e nao `authz.exigir`) porque a pergunta aqui e "existe outro
    # caminho?", nao "barre agora": `exigir` respeita o AUTHZ_MODO e em `aviso`
    # deixaria passar registrando um falso negado.
    #
    # ⚠️ E `ensure_tela` fica DENTRO do mesmo `if`: ela nega nos dois modos
    # (ver services/auth.py), entao deixa-la de fora barraria justamente a
    # pessoa que recebeu a caixinha nova e nao tem a tela de Convenios — que e
    # o caso inteiro para o qual esta permissao existe.
    if not authz.pode(current, "vigencias.ver"):
        authz.exigir(current, "convenios.ver")
        ensure_tela(current, "convenios")
    # ⚠️ SEM `municipio_id`, o nucleo devolve TODOS os municipios do tenant. Isso
    # e o esperado para o super-admin (allowed_municipio_ids=None), mas para quem
    # tem carteira restrita seria vazamento: veria vigencia de municipio que nao
    # pode abrir. Aqui o pedido "todos" passa a significar "todos OS MEUS".
    permitidos = getattr(current, "allowed_municipio_ids", None)
    mids = None
    if municipio_id is None and permitidos is not None:
        mids = list(permitidos)
        if not mids:
            return []          # carteira vazia: nao ha o que listar
    # O nucleo ja normaliza com `anos_list()`, que aceita int OU lista — aqui
    # so falta a assinatura do FastAPI deixar a lista chegar.
    alertas = await query_alertas_vigencia(db, municipio_id, dias, anos or ano,
                                           municipio_ids=mids)
    # Nome do municipio junto (a tela agrupa/filtra por ele e nao deve ter de
    # cruzar com outra chamada).
    ids = {a.municipio_id for a in alertas if a.municipio_id}
    if ids:
        nomes = dict((await db.execute(
            select(Municipio.id, Municipio.nome).where(Municipio.id.in_(ids))
        )).all())
        for a in alertas:
            a.municipio_nome = nomes.get(a.municipio_id)
    return alertas


async def _nomes_municipios(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    municipio_ids: Optional[list[int]] = None,
) -> dict:
    """{municipio_id: nome} dos municipios no escopo da consulta.

    POR QUE EXISTE. O schema AlertaVigencia declara `municipio_nome` e a tela
    (frontend/src/components/bi/VigenciasModal.tsx) tenta usa-lo ANTES de cruzar
    por id — o comentario de la ate diz "a API passou a mandar municipio_nome
    junto". So que NINGUEM preenchia: o campo vinha sempre None e a tela caia no
    cruzamento por id, que depende de a lista de municipios ter sido carregada no
    navegador. Para quem nao tem essa lista, TODA bolha virava "—" e o filtro
    nascia vazio — o modal de Vigencias aparecia EM BRANCO. Relatado em producao.

    Vale para os alertas de vigencia E os de prestacao de contas: os dois usam o
    mesmo schema e tinham o mesmo buraco.

    Uma consulta por chamada, so do escopo pedido. Falha devolve {} e a tela volta
    ao cruzamento por id — o comportamento antigo, nunca pior."""
    try:
        if municipio_id:
            r = await db.execute(text("SELECT id, nome FROM municipios WHERE id = :m"),
                                 {"m": municipio_id})
        elif municipio_ids:
            r = await db.execute(text("SELECT id, nome FROM municipios WHERE id = ANY(:mids)"),
                                 {"mids": list(municipio_ids)})
        else:
            r = await db.execute(text("SELECT id, nome FROM municipios"))
        return {row[0]: row[1] for row in r.fetchall()}
    except Exception:
        return {}


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

    _nomes = await _nomes_municipios(db, municipio_id, municipio_ids)

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
            municipio_id=c.municipio_id,
            municipio_nome=_nomes.get(c.municipio_id),
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy)
    #
    # ⚠️ SEM PORTAO. Aqui havia um `if municipio_id or municipio_ids:` e ele
    # apagava as voluntarias INTEIRAS para o super-admin: `allowed_municipio_ids`
    # e None para ele (services/auth.py), o handler deixa `mids = None`, e os dois
    # parametros nulos davam falso no portao. O bloco dos ESTADUAIS, logo acima,
    # nunca teve esse portao — sem municipio ele consulta o tenant inteiro. Dai a
    # assimetria que o dono relatou: o modal de Vigencias do super-admin mostrava
    # so estaduais, enquanto o de um usuario comum (carteira = lista nao vazia)
    # mostrava os dois. "Sem recorte" significa TODOS, e nao NENHUM.
    from datetime import datetime as _dt
    if municipio_id:
        _mun_sql = "municipio_id = :m"; _vp = {"m": municipio_id}
    elif municipio_ids:
        _mun_sql = "municipio_id = ANY(:mids)"; _vp = {"mids": list(municipio_ids)}
    else:
        _mun_sql = "TRUE"; _vp = {}
    _vsql = "AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""
    if _anos:
        _vp["anos_txt"] = [str(a) for a in _anos]
    # ⚠️ So a PREFEITURA vira alerta (15/09/2026). O filtro por IBGE traz o que
    # esta sediado na cidade: o convenio do Estado de Goias vencendo nao e
    # prazo da prefeitura de Goiania. Ver `services/natureza.py`.
    vol = await db.execute(text(f"""
        SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia,
               municipio_id
        FROM transferegov_propostas
        WHERE {_mun_sql} AND municipal IS NOT FALSE {_vsql}
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
            municipio_id=(row[6] if len(row) > 6 else municipio_id),
            municipio_nome=_nomes.get(row[6] if len(row) > 6 else municipio_id),
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
    # Mesmo buraco da vigencia: o alerta de prestacao usa o MESMO schema e
    # tambem chegava sem o nome do municipio.
    _nomes = await _nomes_municipios(db, municipio_id, municipio_ids)

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
            municipio_id=c.municipio_id,
            municipio_nome=_nomes.get(c.municipio_id),
            objeto=c.objeto, orgao_concedente=c.orgao_concedente,
            dt_fim_vigencia=c.dt_vigencia_atual, dias_restantes=dias_rest,
            valor_total=float(c.valor_total) if c.valor_total else None,
            situacao=c.situacao,
        ))

    # TransfereGov Voluntarias (dt_fim_vigencia eh string dd/mm/yyyy)
    #
    # ⚠️ SEM PORTAO. Aqui havia um `if municipio_id or municipio_ids:` e ele
    # apagava as voluntarias INTEIRAS para o super-admin: `allowed_municipio_ids`
    # e None para ele (services/auth.py), o handler deixa `mids = None`, e os dois
    # parametros nulos davam falso no portao. O bloco dos ESTADUAIS, logo acima,
    # nunca teve esse portao — sem municipio ele consulta o tenant inteiro. Dai a
    # assimetria que o dono relatou: o modal de Vigencias do super-admin mostrava
    # so estaduais, enquanto o de um usuario comum (carteira = lista nao vazia)
    # mostrava os dois. "Sem recorte" significa TODOS, e nao NENHUM.
    from datetime import datetime as _dt
    if municipio_id:
        _mun_sql = "municipio_id = :m"; _vp = {"m": municipio_id}
    elif municipio_ids:
        _mun_sql = "municipio_id = ANY(:mids)"; _vp = {"mids": list(municipio_ids)}
    else:
        _mun_sql = "TRUE"; _vp = {}
    _vsql = "AND split_part(numero_proposta, '/', 2) = ANY(:anos_txt)" if _anos else ""
    if _anos:
        _vp["anos_txt"] = [str(a) for a in _anos]
    vol = await db.execute(text(f"""
        SELECT numero_proposta, codigo_instrumento, objeto, orgao, situacao, dt_fim_vigencia,
               municipio_id
        FROM transferegov_propostas
        WHERE {_mun_sql} AND municipal IS NOT FALSE {_vsql}
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
            municipio_id=(row[6] if len(row) > 6 else municipio_id),
            municipio_nome=_nomes.get(row[6] if len(row) > 6 else municipio_id),
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
        # PRESTACAO DE CONTAS — o campo VOLTOU, agora com fonte.
        #
        # Ele existiu, saia `raw.get("prestacao_contas") or raw.get("presta_contas")`
        # e foi REMOVIDO porque as duas chaves tinham zero ocorrencia no raw_data
        # de qualquer fonte dos tres tenants (varridas as 72 chaves do SIGCON e as
        # 46 do GCONV-ES): rendia "-" em 894 de 894 linhas, num campo de largura
        # dupla e justamente o que o gestor mais procura quando um convenio vence.
        # Aquele comentario terminava assim: "o derivado so sabe que o PRAZO
        # venceu, nao se a prestacao foi entregue".
        #
        # E essa a lacuna que o pedido de 27/08/2026 fecha. As chaves agora
        # EXISTEM porque ha coletor: `_scrape_prestacao_contas` abre a secao
        # 'PRESTAÇÃO DE CONTAS' do detalhe e le status, SEI e as duas datas.
        # ⚠️ Isto NAO substitui `dias_restantes_label` ("VENCIDO +90 DIAS -
        # PRESTACAO DE CONTAS"): aquilo e o PRAZO derivado da vigencia, isto e a
        # ENTREGA declarada pelo Estado. Um convenio pode ter os dois — vencido ha
        # 200 dias E com prestacao final ja apresentada — e e a diferenca entre os
        # dois que diz se ha algo a cobrar do municipio.
        "prestacao_contas_status": raw.get("prestacao_contas_status"),
        "prestacao_contas_data": raw.get("prestacao_contas_data"),
        "prestacao_contas_status_data": raw.get("prestacao_contas_status_data"),
        "prestacao_contas_sei": raw.get("prestacao_contas_sei"),
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
