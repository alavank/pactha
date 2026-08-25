"""TransfereGov - Plano de Acao (Transferencia Especial Federal).

Fonte: https://especiais.transferegov.sistema.gov.br/transferencia-especial/plano-acao/consulta
API publica REST descoberta via reverse-eng do main.js:
  GET /maisbrasil-transferencia-especial-backend/api/public/plano-acao/listagem?uf=MG
  GET /maisbrasil-transferencia-especial-backend/api/public/plano-acao/{id}
  GET /maisbrasil-transferencia-especial-backend/api/public/relatorio-gestao/plano-acao/{id}

A listagem retorna TUDO de MG (~8800 items, 5MB) em uma chamada -- a API nao
suporta filtro server-side por municipio/CNPJ. Cacheamos em memoria por 1h e
filtramos local.
"""
import os
import asyncio
import time
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from database import get_db
from models import Municipio
from models.user import User
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
import httpx
import unicodedata
from services import authz
from services.registro_rotas import exige

router = APIRouter(prefix="/api/transferegov", tags=["transferegov"])

API_BASE = "https://especiais.transferegov.sistema.gov.br/maisbrasil-transferencia-especial-backend/api"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/131 Safari/537.36",
    "Referer": "https://especiais.transferegov.sistema.gov.br/transferencia-especial/plano-acao/consulta",
}

# Cache em memoria: {(uf): (timestamp, lista_planos)}
_CACHE: dict = {}
_CACHE_TTL = 3600  # 1h

import logging as _logging
logger = _logging.getLogger("transferegov")

# pageSize confiavel em TODA a faixa de paginas. O gateway aceita ate 300, mas em
# 300 a 2a pagina cai em 403 deterministico; 200 e estavel de ponta a ponta
# (>=400 -> 403 sempre). Concorrencia dispara rate-limit — a coleta e SEQUENCIAL.
_PAGE_SIZE = 200


def _norm(s: str) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper()) if not unicodedata.combining(c)).strip()


def _dias_restantes(dt_str: Optional[str]) -> Optional[int]:
    """Calcula dias entre hoje e a data de fim de vigencia (dd/mm/yyyy)."""
    if not dt_str:
        return None
    from datetime import date, datetime as _dt
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            d = _dt.strptime(dt_str.strip()[:10], fmt).date()
            return (d - date.today()).days
        except (ValueError, AttributeError):
            continue
    return None


async def _fetch_listagem(uf: Optional[str]) -> list[dict]:
    """Lista de planos de acao (com cache 1h). uf vazio/None => NACIONAL (todos
    os estados: ~58k itens). A API nao filtra por CNPJ no servidor -> filtramos local."""
    key = (uf or "BR").upper()
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    # A API mudou os nomes dos params: era `page`/`size` (agora devolve 403 — foi o
    # que quebrou a coleta), e virou `pageNumber` (1-based) / `pageSize` (teto 300;
    # >=400 -> 403). Ela e publica com os params certos — NAO precisa de sessao.
    # Pagina ate juntar `total`. SEM raise: em erro devolve o que tiver (ou []),
    # entao a tela Especiais e o RM ficam vazios em vez de estourar 500.
    # ORCAMENTO de tempo: a API RATE-LIMITA (bloqueia depois de ~10 paginas
    # seguidas, mesmo com delay; concorrencia piora). Coletar MG inteiro (~44
    # paginas) ao vivo levaria minutos — inviavel numa request web. Entao paginamos
    # SEQUENCIALMENTE por ate _BUDGET s e cacheamos o que vier (parcial e melhor que
    # nada e nao estoura 500). Cobertura COMPLETA e trabalho de coletor em segundo
    # plano (persistir numa tabela) — pendencia registrada.
    _BUDGET = float(os.getenv("TE_FETCH_BUDGET_S", "15") or "15")
    t0 = time.time()
    items: list[dict] = []
    completo = False
    try:
        async with httpx.AsyncClient(timeout=45, verify=False) as cli:
            page = 1
            while page <= 500 and (time.time() - t0) < _BUDGET:
                params: dict = {"pageNumber": page, "pageSize": _PAGE_SIZE}
                if uf:
                    params["uf"] = uf  # omitir uf => nacional
                data = None
                for tent in range(3):
                    r = await cli.get(f"{API_BASE}/public/plano-acao/listagem",
                                      params=params, headers=HEADERS)
                    if r.status_code == 200:
                        data = r.json()
                        break
                    await asyncio.sleep(0.8 * (tent + 1))
                if data is None:
                    logger.warning(f"especiais listagem {key} p{page}: 403 apos retries (rate-limit)")
                    break
                lote = data.get("listaPlanosAcao") or []
                items.extend(lote)
                total = int(data.get("total") or 0)
                if len(lote) < _PAGE_SIZE or (total and len(items) >= total):
                    completo = True
                    break
                page += 1
                await asyncio.sleep(0.25)
    except Exception as ex:
        logger.warning(f"especiais listagem {key}: {str(ex)[:120]} — TE indisponivel")
    # Cacheia o que veio (parcial inclusive) p/ nao repaginar a cada request.
    if items:
        _CACHE[key] = (now, items)
    if not completo:
        logger.warning(f"especiais listagem {key}: parcial {len(items)} itens (rate-limit / budget {_BUDGET}s)")
    return items


@router.get("/buscar", dependencies=[exige("transferegov.ver")])
async def buscar(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    # Aceita VARIAS situacoes (?situacao=CIENTE&situacao=IMPEDIDO).
    situacao: Optional[list[str]] = Query(None, description="CIENTE, EM_ANALISE, IMPEDIDO, etc (aceita varias)"),
    programa: Optional[str] = Query(None, description="codigo do programa (ex: 09032022)"),
    parlamentar: Optional[str] = Query(None, description="texto livre - busca em codigoEmendaFormatado"),
    emenda: Optional[str] = Query(None, description="codigo da emenda formatado"),
    objeto: Optional[str] = Query(None, description="busca em politicasPublicas"),
    refresh: bool = Query(False, description="forca refresh do cache"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista planos de acao filtrados pelo municipio + filtros opcionais.

    A API do TransfereGov nao oferece filtro server-side por municipio, entao
    baixa lista completa de MG (com cache 1h) e filtra por nome do municipio
    do PACTHA + filtros adicionais.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov")
    mun = (await db.execute(select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")

    # Le da tabela PERSISTIDA (coletor do worker, ingestion/transferegov_te.py). Antes
    # buscava ao vivo, mas a API "especiais" rate-limita — agora e completo e rapido.
    # Fallback ao vivo (capado) so se a tabela estiver vazia (coletor ainda nao rodou).
    rows = (await db.execute(text(
        "SELECT raw_data FROM transferegov_te WHERE municipio_id = :m"
    ), {"m": municipio_id})).all()
    all_items = [r[0] for r in rows if r[0]]
    if not all_items:
        try:
            all_items = await _fetch_listagem(mun.uf)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"TransfereGov: {e}")

    mun_norm = _norm(mun.nome)
    # Match: nome do beneficiario contem nome do municipio (caso "MUNICIPIO DE ARAUJOS")
    # ou cnpj corresponde
    filtered = []
    for it in all_items:
        ben = _norm(it.get("beneficiarioNome") or "")
        # match exato no fim: "MUNICIPIO DE ARAUJOS" ou nome simples
        if not (mun_norm in ben or ben.endswith(mun_norm)):
            continue
        if situacao and _norm(it.get("planoAcaoSituacao") or "") not in {_norm(x) for x in situacao}:
            continue
        if programa and programa not in (it.get("programaCodigo") or ""):
            continue
        if parlamentar and _norm(parlamentar) not in _norm(it.get("codigoEmendaFormatado") or ""):
            continue
        if emenda and emenda not in (it.get("codigoEmendaFormatado") or ""):
            continue
        if objeto and _norm(objeto) not in _norm(it.get("politicasPublicas") or ""):
            continue
        filtered.append({
            "id": it.get("planoAcaoId"),
            "codigo": it.get("planoAcaoCodigo"),
            "programa_codigo": it.get("programaCodigo"),
            "programa_id": it.get("programaId"),
            "situacao_plano_acao": it.get("planoAcaoSituacao"),
            "situacao_plano_trabalho": it.get("planoTrabalhoSituacao"),
            "beneficiario_nome": it.get("beneficiarioNome"),
            "beneficiario_cnpj": it.get("beneficiarioCnpj"),
            "uf": it.get("uf"),
            "politicas_publicas": it.get("politicasPublicas"),
            "emenda_codigo": it.get("codigoEmendaFormatado"),
            "valor_custeio": float(it.get("valorCusteio") or 0),
            "valor_investimento": float(it.get("valorInvestimento") or 0),
            "valor_total": float(it.get("valorTotal") or 0),
            "objeto_descricao": it.get("objetoDescricao"),
            "motivo_impedimento": it.get("motivoImpedimento"),
            "dt_atualizacao_plano_acao": it.get("dataAtualizacaoPlanoAcao"),
            "dt_atualizacao_plano_trabalho": it.get("dataAtualizacaoPlanoTrabalho"),
        })

    return {
        "items": filtered,
        "total": len(filtered),
        "municipio": {"id": mun.id, "nome": mun.nome, "uf": mun.uf},
        "cache_age_seconds": int(time.time() - (_CACHE.get(mun.uf, (time.time(), []))[0])),
    }


def _digits(s) -> str:
    return "".join(c for c in (s or "") if c.isdigit())


def _padrao_like(termo: str) -> str:
    """Termo digitado -> padrao ILIKE que sobrevive ao acento PERDIDO da fonte.

    ⚠️ O portal TransfereGov serve U+FFFD no lugar da letra acentuada e o coletor
    APAGA esse caractere (ingestion/transferegov_voluntarias.py, `_clean`, por
    onde `proponente` passa). O banco guarda, entao, "MUNICPIO DE SO GONALO"
    onde o portal queria "MUNICÍPIO DE SÃO GONÇALO" — e `proponente ILIKE
    '%São%'` nunca casa. Nem `'%Sao%'`: a letra nao foi desacentuada, foi
    DELETADA.

    Nao e teoria. Este mesmo arquivo ja convive com isso em _VOLUNTARIA_LIKE
    ("%enviado para an%lise%") e o upsert do coletor se recusa a sobrescrever
    `objeto` quando o texto novo contem chr(65533). A busca era o unico lugar
    que ignorava a regra.

    A saida e a MESMA do _VOLUNTARIA_LIKE, generalizada: cada caractere
    nao-ASCII do termo vira `%`, que casa a letra presente ("São"), a letra sem
    acento ("Sao") e a letra ausente ("So").

    Escapa ANTES os curingas do LIKE (`\\`, `%`, `_`): sem isso um `_` digitado
    casa qualquer caractere e um `%` sozinho devolve a base inteira. O caractere
    de escape do LIKE no Postgres JA e a barra invertida por padrao — nao ha
    clausula ESCAPE de proposito, para nao depender de standard_conforming_strings.

    Devolve "" para termo vazio: quem chama TEM de pular o filtro nesse caso, e
    nunca mandar "%%" (que traria tudo e pareceria "o filtro nao funciona")."""
    t = (termo or "").strip()
    if not t:
        return ""
    saida = []
    for ch in t:
        if ch in ("\\", "%", "_"):
            saida.append("\\" + ch)
        elif ord(ch) > 127 or len(unicodedata.normalize("NFD", ch)) > 1:
            saida.append("%")
        else:
            saida.append(ch)
    return "%" + "".join(saida) + "%"


@router.get("/por-cnpj", dependencies=[exige("transferegov.ver")])
async def por_cnpj(
    cnpj: str = Query(..., description="CNPJ do proponente (com ou sem mascara)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Consulta TransfereGov por CNPJ (nao entra em relatorio). So o CNPJ, sem UF.
    - Especiais/Plano de Acao: API publica NACIONAL (cache 1h), filtra pelo CNPJ;
    - Voluntarias: do que ja foi coletado no banco (identificacao = CNPJ).
    Nao e escopado por municipio (e o proposito). Voluntarias respeita o escopo
    de municipios do usuario nao-admin.
    """
    ensure_tela(current, "transferegov")
    alvo = _digits(cnpj)
    if len(alvo) != 14:
        raise HTTPException(400, "Informe um CNPJ válido (14 dígitos)")

    # 1) Especiais / Plano de Acao (API publica NACIONAL, filtra por CNPJ)
    especiais = []
    try:
        for it in await _fetch_listagem(None):
            if _digits(it.get("beneficiarioCnpj")) == alvo:
                especiais.append({
                    "id": it.get("planoAcaoId"),
                    "codigo": it.get("planoAcaoCodigo"),
                    "programa_codigo": it.get("programaCodigo"),
                    "situacao": it.get("planoAcaoSituacao"),
                    "beneficiario_nome": it.get("beneficiarioNome"),
                    "beneficiario_cnpj": it.get("beneficiarioCnpj"),
                    "uf": it.get("uf"),
                    "politicas_publicas": it.get("politicasPublicas"),
                    "emenda_codigo": it.get("codigoEmendaFormatado"),
                    "valor_total": float(it.get("valorTotal") or 0),
                    "objeto_descricao": it.get("objetoDescricao"),
                })
    except httpx.HTTPError:
        pass  # API fora do ar -> retorna so o que der

    # 2) Voluntarias/Convenios: base SICONV federal (Brasil inteiro, dados
    #    abertos), por CNPJ. Dado publico -> nao escopado por municipio.
    #    ⚠️ ATRAS DA FLAG SICONV_MODULE (decisao do dono, 10/08/2026): o padrao
    #    do PACTHA e SEM a base SICONV — ela so existe onde o cliente pediu
    #    (hoje: freitas, unica com o coletor agendado). Nos demais tenants a
    #    tabela foi TRUNCADA: consultar e devolver [] deixaria a tela mostrar
    #    "0 convenios encontrados" como se fosse resultado de busca — e modulo
    #    ausente NAO e resultado vazio, e a diferenca entre "procurei e nao
    #    achei" e "nem procuro". A flag viaja no payload (`siconv_module`) e o
    #    frontend esconde a secao inteira; ligar = env SICONV_MODULE=1 SO na
    #    API do tenant — sem build-arg por cliente, sem CI.
    _siconv = os.getenv("SICONV_MODULE") == "1"
    voluntarias = []
    if _siconv:
        rows = (await db.execute(text("""
            SELECT nr_proposta, situacao, proponente, municipio, uf, ano, objeto,
                   vl_global, vl_repasse, nr_convenio, situacao_convenio,
                   vl_desembolsado, dt_assinatura, dt_fim_vigencia
            FROM siconv_federal
            WHERE cnpj = :c
            ORDER BY ano DESC NULLS LAST, id_proposta DESC
            LIMIT 800
        """), {"c": alvo})).fetchall()
        voluntarias = [{
            "numero_proposta": r[0], "situacao": r[1], "proponente": r[2],
            "municipio": r[3], "uf": r[4], "ano": r[5], "objeto": r[6],
            "valor_global": float(r[7]) if r[7] else None,
            "valor_repasse": float(r[8]) if r[8] else None,
            "nr_convenio": r[9], "situacao_convenio": r[10],
            "valor_desembolsado": float(r[11]) if r[11] else None,
            "dt_assinatura": r[12].isoformat() if r[12] else None,
            "dt_fim_vigencia": r[13].isoformat() if r[13] else None,
        } for r in rows]

    return {
        "cnpj": alvo,
        "siconv_module": _siconv,
        "especiais": especiais, "voluntarias": voluntarias,
        "total_especiais": len(especiais), "total_voluntarias": len(voluntarias),
    }


# Status que identifica uma proposta VOLUNTARIA (FREITAS). Alem do classico
# "Proposta/Plano de Trabalho enviado para Analise", a Freitas considera tambem
# voluntarias todas as propostas/planos no PIPELINE de analise/aprovacao/
# complementacao (antes da celebracao): "Aprovados", "em Analise", "em
# Complementacao", "complementado enviada para Analise", "Proposta Aprovada e
# Plano de Trabalho ...", etc. NAO inclui: Prestacao de Contas, Rejeitadas,
# "Em execucao" (convenio ja celebrado). O acento corrompido (U+FFFD) e tratado
# com curinga (an%lise).
_VOLUNTARIA_LIKE = "%enviado para an%lise%"  # mantido p/ compat
_VOLUNTARIA_SQL = (
    "(situacao ILIKE '%plano de trabalho%' "
    "AND (situacao ILIKE '%an%lise%' OR situacao ILIKE '%aprovad%' OR situacao ILIKE '%complementa%') "
    "AND situacao NOT ILIKE '%presta%' AND situacao NOT ILIKE '%rejeitad%')"
)
# REJEITADAS: qualquer status contendo "rejeitad" (Rejeitados / Rejeitados por
# Impedimento tecnico). Tratamos como categoria propria; nao entram na Geral.
_REJEITADA_LIKE = "%rejeitad%"
# ENCERRADAS: instrumento finalizado. Inclui Anulado, Rescindido e Prestacao
# de Contas finalizada (Concluida/Aprovada/Aprovada com Ressalvas).
# Usamos SQL composto pra excluir do Geral.
_ENCERRADA_SQL = (
    "(situacao ILIKE '%anulad%' OR situacao ILIKE '%rescind%' OR "
    "(situacao ILIKE '%presta%' AND (situacao ILIKE '%conclu%' OR situacao ILIKE '%aprovad%')))"
)
# ⭐ VIVA = o CICLO DE VIDA ATIVO: tudo que NAO foi rejeitado nem encerrado.
# E o recorte da tela «Voluntarias» desde 08/2026 (pedido do dono).
#
# O QUE MUDOU E POR QUE. Antes «Voluntarias» era so o PIPELINE DE ANALISE
# (_VOLUNTARIA_SQL) e parava exatamente onde a proposta vira instrumento: no dia
# em que o convenio era celebrado ele SUMIA da tela e reaparecia noutra, chamada
# «Geral». Quem acompanha uma proposta do inicio ao fim tinha de trocar de aba no
# meio do caminho — e, pior, o filtro de situacao da tela e montado a partir das
# LINHAS CARREGADAS (frontend/src/components/TransfereGovPropostas.tsx), entao a
# opcao "Em execucao" nunca podia aparecer ali: as linhas nao chegavam.
#
# ⚠️ NAO INCLUI rejeitadas nem encerradas, de proposito. As duas sao DESFECHO,
# nao trabalho em curso, e cada uma tem aba propria — traze-las para ca faria
# «Voluntarias» duplicar duas telas inteiras e contradizer o proprio nome.
#
# ⚠️ `situacao IS NULL` ENTRA. Linha sem situacao coletada nao e desfecho — e
# ausencia de informacao, e sumir com ela seria afirmar um encerramento que
# ninguem viu. E o mesmo criterio do ramo `geral`, logo abaixo.
_VIVA_SQL = (
    "(situacao IS NULL OR (situacao NOT ILIKE '%rejeitad%' "
    f"AND NOT {_ENCERRADA_SQL}))"
)
# EM QUAL DAS QUATRO TELAS de propostas um instrumento aparece, como expressao SQL.
# Existe para o vinculo do /pac poder LINKAR para a tela certa usando AS MESMAS
# regras que o /voluntarias usa para montar cada categoria — se divergissem, o
# link do PAC levaria a uma tela onde o convenio nao esta, que e pior que nao
# linkar. A ordem repete a do handler `voluntarias`: voluntarias -> rejeitadas ->
# encerradas -> o que sobra. `situacao` NULA cai no ELSE ('geral'), igual ao
# ramo `situacao IS NULL` de la.
# ⚠️ `situacao` sem qualificador: so pode ser usado em consulta onde
# transferegov_propostas e a unica tabela com essa coluna.
_CATEGORIA_SQL = (
    "CASE "
    f"WHEN {_VOLUNTARIA_SQL} THEN 'voluntarias' "
    "WHEN situacao ILIKE '%rejeitad%' THEN 'rejeitadas' "
    f"WHEN {_ENCERRADA_SQL} THEN 'encerradas' "
    "ELSE 'geral' END"
)


@router.get("/voluntarias", dependencies=[exige("transferegov.ver")])
async def voluntarias(
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    orgao: Optional[str] = Query(None),
    # BUSCA SEPARADA POR CAMPO. A caixa unica ("nº / proponente / CNPJ") era um OR
    # de tres colunas: nao dava para dizer QUAL numero se procurava, o numero do
    # CONVENIO nem era consultado, e qualquer digito no termo arrastava CNPJs
    # parecidos junto. Cada campo abaixo filtra a SUA coluna.
    instrumento: Optional[str] = Query(None, description="nº do convênio/instrumento (codigo_instrumento ou numero_processo)"),
    proposta: Optional[str] = Query(None, description="nº da proposta (ex.: 048291/2025)"),
    proponente: Optional[str] = Query(None, description="nome do proponente"),
    cnpj: Optional[str] = Query(None, description="CNPJ do proponente, com ou sem máscara"),
    # LEGADO: a caixa unica saiu da tela, mas URLs salvas ainda mandam `search`.
    # Continua valendo — e agora tambem olha o codigo_instrumento, que era o
    # numero que faltava.
    search: Optional[str] = Query(None, description="LEGADO: busca em nº proposta/instrumento/proponente/CNPJ"),
    parlamentar: Optional[str] = Query(None, description="filtra pelo parlamentar (ILIKE)"),
    # Aceitam VARIOS valores (?vigencia=vence30&vigencia=prestacao). Um valor
    # unico chega como lista de um, entao os links antigos dos KPIs do dashboard
    # continuam valendo sem mudanca.
    situacao_contratacao: Optional[list[str]] = Query(None, description="Normal | Clausula Suspensiva | Liminar Judicial (aceita varios)"),
    vigencia: Optional[list[str]] = Query(None, description="vence30 | vence60 | vence90 | vence120 | prestacao (aceita varios)"),
    vig_fim_de: Optional[str] = Query(None, description="fim de vigencia >= AAAA-MM-DD"),
    vig_fim_ate: Optional[str] = Query(None, description="fim de vigencia <= AAAA-MM-DD"),
    categoria: Optional[str] = Query(None, description="geral | voluntarias | rejeitadas | encerradas"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista propostas SICONV de um municipio, filtradas por categoria.

    Dados coletados pelo scraper Playwright (acesso livre guest) em
    transferegov_propostas. Categorias:
      - voluntarias: o CICLO DE VIDA ATIVO — pipeline de analise E instrumentos
              em execucao. Exclui apenas rejeitadas e encerradas. (Era so o
              pipeline de analise ate 08/2026; ver `_VIVA_SQL`.)
      - rejeitadas: status com "Rejeitad"
      - encerradas: Anulado / Rescindido / Prestacao de Contas Concluida/Aprovada
      - geral: a tela «Em execucao» — o que sobra depois de tirar o pipeline de
              analise, as rejeitadas e as encerradas.

    ⚠️ `voluntarias` e `geral` agora SE SOBREPOEM, e isso e intencional: sao
    perguntas diferentes sobre o mesmo dado ("o que esta em andamento?" e "o que
    ja foi celebrado?"). Nenhuma proposta some de aba nenhuma por causa disso.
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov")
    where = ["municipio_id = :mun"]
    params: dict = {"mun": municipio_id}
    if categoria == "voluntarias":
        # ⚠️ `_VIVA_SQL`, NAO `_VOLUNTARIA_SQL`. O segundo continua existindo e
        # continua sendo usado — pelo `_CATEGORIA_SQL` (que decide para qual aba
        # o link do PAC aponta) e pelo ramo `geral` logo abaixo, que precisa
        # EXCLUIR o pipeline de analise para nao mostrar proposta nao celebrada
        # numa tela chamada «Em execucao». Trocar os dois por `_VIVA_SQL` faria
        # as duas telas devolverem a mesma coisa.
        where.append(_VIVA_SQL)
    elif categoria == "rejeitadas":
        where.append("situacao ILIKE :rejpat"); params["rejpat"] = _REJEITADA_LIKE
    elif categoria == "encerradas":
        where.append(_ENCERRADA_SQL)
    elif categoria == "geral":
        # Geral = o que sobra: nem voluntaria (pipeline de analise), nem rejeitada,
        # nem encerrada/prestacao. Sobra basicamente "Em execucao" + legados.
        where.append(f"(situacao IS NULL OR (NOT {_VOLUNTARIA_SQL} AND situacao NOT ILIKE :rejpat AND NOT {_ENCERRADA_SQL}))")
        params["rejpat"] = _REJEITADA_LIKE
    if situacao:
        where.append("situacao ILIKE :sit"); params["sit"] = f"%{situacao}%"
    if orgao:
        where.append("orgao ILIKE :org"); params["org"] = f"%{orgao}%"
    if parlamentar:
        where.append("parlamentar ILIKE :parl"); params["parl"] = f"%{parlamentar}%"
    if situacao_contratacao:
        # OR entre as escolhidas: "Normal" OU "Liminar Judicial" etc.
        _conds = []
        for _i, _sc in enumerate(situacao_contratacao):
            _conds.append(f"situacao_contratacao ILIKE :sc{_i}")
            params[f"sc{_i}"] = f"%{_sc}%"
        where.append("(" + " OR ".join(_conds) + ")")
    # --- BUSCA POR CAMPO (cada um filtra a SUA coluna, e sao combinados com AND) ---
    if _padrao_like(instrumento or ""):
        # O numero do CONVENIO ("981397"). E o que a tela imprime na meta de cada
        # item ("· instr 981397") e o que titula o modal — e era a UNICA coluna que
        # a busca nao olhava. `numero_processo` entra junto porque e o outro numero
        # do mesmo instrumento, impresso no detalhe: um quinto campo so para ele
        # seria formulario a mais para a mesma pergunta.
        where.append("(codigo_instrumento ILIKE :inst OR numero_processo ILIKE :inst)")
        params["inst"] = _padrao_like(instrumento)
    if _padrao_like(proposta or ""):
        where.append("numero_proposta ILIKE :prop")
        params["prop"] = _padrao_like(proposta)
    if _padrao_like(proponente or ""):
        where.append("proponente ILIKE :propon")
        params["propon"] = _padrao_like(proponente)
    if cnpj:
        # SO OS DIGITOS, dos dois lados: o portal grava com mascara
        # ("18.243.220/0001-01") e o gestor cola dos dois jeitos. Termo sem digito
        # nenhum nao filtra — CNPJ e numero, e casar letra contra CNPJ so daria ruido.
        _c = _digits(cnpj)
        if _c:
            where.append(r"regexp_replace(coalesce(identificacao,''), '\D', '', 'g') LIKE :cnpj")
            params["cnpj"] = f"%{_c}%"
    if search:
        # LEGADO (a tela nao manda mais; links salvos ainda mandam). Duas
        # correcoes: ganhou codigo_instrumento e passou a usar o padrao tolerante
        # ao acento apagado.
        conds = ["numero_proposta ILIKE :s", "codigo_instrumento ILIKE :s",
                 "proponente ILIKE :s", "identificacao ILIKE :s"]
        params["s"] = _padrao_like(search) or f"%{search}%"
        _sd = _digits(search)
        # >= 8 digitos: so entao o termo parece pedaco de CNPJ. Antes QUALQUER
        # numero entrava aqui — buscar "2025" devolvia toda proposta cujo CNPJ
        # contivesse 2025, misturado com os acertos de verdade.
        if len(_sd) >= 8:
            conds.append(r"regexp_replace(coalesce(identificacao,''), '\D', '', 'g') LIKE :sd")
            params["sd"] = f"%{_sd}%"
        where.append("(" + " OR ".join(conds) + ")")
    sql = f"""
        SELECT numero_proposta, situacao, orgao, proponente, possui_parecer,
               identificacao, codigo_instrumento, modalidade, situacao_siafi,
               numero_processo, objeto, programa, dt_inicio_vigencia,
               dt_fim_vigencia, dt_proposta, dt_assinatura, updated_at,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar,
               situacao_contratacao_detalhe, processo_execucao_qtd
        FROM transferegov_propostas
        WHERE {' AND '.join(where)}
        ORDER BY numero_proposta DESC
    """
    r = await db.execute(text(sql), params)
    items = [{
        "numero_proposta": row[0], "situacao": row[1], "orgao": row[2],
        "proponente": row[3], "possui_parecer": row[4], "identificacao": row[5],
        "codigo_instrumento": row[6], "modalidade": row[7], "situacao_siafi": row[8],
        "numero_processo": row[9], "objeto": row[10], "programa": row[11],
        "dt_inicio_vigencia": row[12], "dt_fim_vigencia": row[13],
        "dt_proposta": row[14], "dt_assinatura": row[15],
        "dias_restantes": _dias_restantes(row[13]),
        "atualizado_em": row[16].isoformat() if row[16] else None,
        "situacao_contratacao": row[17],
        "clausula_suspensiva_dt_prevista": row[18].isoformat() if row[18] else None,
        "clausula_suspensiva_motivo": row[19],
        "parlamentar": row[20],
        "situacao_contratacao_detalhe": row[21],
        "processo_execucao_qtd": row[22],
    } for row in r.fetchall()]

    # Filtro de vigencia (presets: dias para vencer) — vindo dos KPIs ou do filtro
    if vigencia:
        _LIMITES = {"vence30": 30, "vence60": 60, "vence90": 90, "vence120": 120}
        # So os presets CONHECIDOS entram. Se nada reconhecido sobrar, nao
        # filtramos — mesma leniencia de antes, que deixava passar valor estranho
        # em vez de devolver lista vazia sem explicacao.
        _sel = [v for v in vigencia if v in _LIMITES or v == "prestacao"]
        if _sel:
            def _match_vig(d):
                if d is None:
                    return False
                for _v in _sel:
                    if _v == "prestacao":
                        if d < -90:
                            return True
                    elif 0 <= d <= _LIMITES[_v]:
                        return True
                return False
            items = [i for i in items if _match_vig(i["dias_restantes"])]

    # Filtro por intervalo de DATA de fim de vigencia (de / ate, ISO AAAA-MM-DD)
    if vig_fim_de or vig_fim_ate:
        from datetime import datetime as _dt2
        def _parse_fim(s):
            if not s:
                return None
            for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
                try:
                    return _dt2.strptime(str(s).strip()[:10], fmt).date()
                except (ValueError, TypeError):
                    continue
            return None
        de = _parse_fim(vig_fim_de)
        ate = _parse_fim(vig_fim_ate)
        def _match_range(it):
            d = _parse_fim(it.get("dt_fim_vigencia"))
            if d is None:
                return False
            if de and d < de:
                return False
            if ate and d > ate:
                return False
            return True
        items = [i for i in items if _match_range(i)]

    # Mesma ordenacao do SIGCON: vigentes por urgencia ASC, vencidos depois
    # (|dias| ASC), sem data por ultimo.
    def _sort_key(x):
        d = x["dias_restantes"]
        if d is None:
            return (2, 0)
        if d >= 0:
            return (0, d)
        return (1, -d)
    items.sort(key=_sort_key)

    last = None
    if items:
        last = max((i["atualizado_em"] for i in items if i["atualizado_em"]), default=None)
    return {"items": items, "total": len(items), "atualizado_em": last}


@router.get("/voluntarias/{numero_proposta:path}",
            dependencies=[exige("transferegov.ver")])
async def voluntarias_detalhe(
    numero_proposta: str,
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Detalhe completo de uma proposta (todos os campos capturados do portal)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov")
    r = await db.execute(text("""
        SELECT numero_proposta, situacao, orgao, proponente, identificacao,
               codigo_instrumento, modalidade, situacao_siafi, numero_processo,
               objeto, programa, dt_inicio_vigencia, dt_fim_vigencia,
               dt_proposta, dt_assinatura, detalhe,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar,
               valor_global, valor_repasse, valor_contrapartida,
               situacao_contratacao_detalhe, processo_execucao_qtd,
               historico_comunicacoes, documentos_quadro_resumo, historico_atualizado_em,
               ops_obs, obras, processo_execucao, valor_emenda,
               -- Situacao do Projeto Basico/Termo de Referencia. ULTIMA coluna de
               -- proposito: o dict abaixo le por INDICE, e inserir no meio
               -- deslocaria todos os row[N] seguintes em silencio.
               projeto_basico,
               -- NEs da aba Execucao Concedente. ULTIMA coluna, mesma razao do
               -- projeto_basico: o dict abaixo le por INDICE.
               notas_empenho
        FROM transferegov_propostas
        WHERE municipio_id = :mun AND numero_proposta = :num
    """), {"mun": municipio_id, "num": numero_proposta})
    row = r.first()
    if not row:
        raise HTTPException(404, "Proposta não encontrada")
    return {
        "numero_proposta": row[0], "situacao": row[1], "orgao": row[2],
        "proponente": row[3], "identificacao": row[4], "codigo_instrumento": row[5],
        "modalidade": row[6], "situacao_siafi": row[7], "numero_processo": row[8],
        "objeto": row[9], "programa": row[10], "dt_inicio_vigencia": row[11],
        "dt_fim_vigencia": row[12], "dt_proposta": row[13], "dt_assinatura": row[14],
        "detalhe": row[15] or {},
        "situacao_contratacao": row[16],
        "clausula_suspensiva_dt_prevista": row[17].isoformat() if row[17] else None,
        "clausula_suspensiva_motivo": row[18],
        "parlamentar": row[19],
        "valor_global": float(row[20]) if row[20] is not None else None,
        "valor_repasse": float(row[21]) if row[21] is not None else None,
        "valor_contrapartida": float(row[22]) if row[22] is not None else None,
        "situacao_contratacao_detalhe": row[23],
        "processo_execucao_qtd": row[24],
        "historico_comunicacoes": row[25] or [],
        "documentos_quadro_resumo": row[26] or [],
        "historico_atualizado_em": row[27].isoformat() if row[27] else None,
        "ops_obs": row[28] or None,
        "obras": row[29] or None,
        # lista de licitacoes COM situacao (Concluído / Em execução ...)
        "processo_execucao": row[30] or [],
        # valores da emenda: valor_emenda vem do CSV; voluntario e proponente
        # sao DERIVADOS (voluntario = repasse - emenda; proponente = contrapartida).
        "valor_emenda": float(row[31]) if row[31] is not None else None,
        "valor_voluntario": (float(row[21]) - float(row[31]))
            if (row[21] is not None and row[31] is not None) else None,
        "valor_proponente": float(row[22]) if row[22] is not None else None,
        # {situacao, documentos:[...]} — o documento que sustenta a clausula
        # suspensiva e em que pe ele esta no portal. None quando a sessao do SP
        # `execucao` estava fria na coleta (nunca {} — ver ingestion/transferegov_http).
        "projeto_basico": row[32] or None,
        # [{numero, minuta, valor, valor_siafi, situacao, dt_emissao, minuta_apenas}]
        # `minuta_apenas` marca a linha que NAO e dinheiro (minuta de R$ 1,00).
        "notas_empenho": row[33] or [],
    }


@router.get("/plano-acao/{plano_acao_id}",
            dependencies=[exige("transferegov.ver")])
async def detalhe(plano_acao_id: int,
                  db: AsyncSession = Depends(get_db),
                  current: User = Depends(get_current_user)):
    """Detalhe completo de um Plano de Acao + relatorio de gestao + extrato +
    PAGAMENTOS (documentos habeis -> OP/OB e o historico de eventos)."""
    # Antes bastava estar LOGADO. Cada chamada dispara TRES requisicoes de saida
    # ao TransfereGov com timeout de 30s cada: sem gate, uma conta sem nenhuma
    # tela usava a API como proxy de rede e prendia workers do servidor.
    #
    # So a TELA: `plano_acao_id` e identificador FEDERAL (nao ha coluna de
    # municipio nossa para casar com ele), e o dado vem da API PUBLICA do
    # TransfereGov — exigir municipio aqui pediria um parametro que o endpoint
    # nao tem e que a fonte nao devolve de forma confiavel.
    authz.exigir_tela(current, "transferegov")
    async with httpx.AsyncClient(timeout=30, verify=False) as cli:
        # Detalhe basico
        try:
            r_plano = await cli.get(f"{API_BASE}/public/plano-acao/{plano_acao_id}", headers=HEADERS)
            r_plano.raise_for_status()
            plano = r_plano.json()
        except httpx.HTTPError as e:
            raise HTTPException(502, f"TransfereGov plano: {e}")
        # Resumo (vem com dados de execucao)
        resumo = None
        try:
            r_res = await cli.get(f"{API_BASE}/public/relatorio-gestao/resumo/plano-acao/{plano_acao_id}", headers=HEADERS)
            if r_res.status_code == 200:
                resumo = r_res.json()
        except Exception:
            pass
        # Extrato bancario
        extrato = None
        try:
            r_ext = await cli.get(f"{API_BASE}/public/relatorio-gestao/extrato",
                                  params={"planoAcaoId": plano_acao_id}, headers=HEADERS)
            if r_ext.status_code == 200:
                extrato = r_ext.json()
        except Exception:
            pass
        # PAGAMENTOS: saem da COLUNA que o coletor ja preencheu
        # (ingestion/transferegov_te.run_pagamentos), NAO da API.
        #
        # Custo de rede ZERO no caminho comum, de proposito: este endpoint ja
        # dispara TRES requisicoes de saida por clique, e a lista de documentos
        # habeis mais o detalhe de cada OP acrescentariam 1+N — num host de 2
        # vCPU, e com a mesma fonte que ja puniu o IP da VPS por horas
        # (INFRA.md §5). A tela passa a mostrar EXATAMENTE o mesmo dado que o RM
        # congela, que e o que o dono quer comparar.
        #
        # None (e nao {}) quando o coletor ainda nao passou por este plano: a
        # tela distingue "nao coletado" de "nao ha pagamento" — a mesma
        # disciplina do RM.
        pagamentos = None
        try:
            pagamentos = (await db.execute(text(
                "SELECT pagamentos FROM transferegov_te WHERE plano_acao_id = :p"
            ), {"p": plano_acao_id})).scalar_one_or_none()
        except Exception as ex:
            logger.warning(f"pagamentos TE {plano_acao_id}: {str(ex)[:120]}")
        return {"plano": plano, "resumo": resumo, "extrato": extrato,
                "pagamentos": pagamentos}


# ============================================================================
# ADMIN: status da sessao gov.br + dispara scraper manualmente apos re-captura
# ============================================================================

# `sessoes.ver`, e nao `transferegov.ver`: pelo mesmo motivo que a tela exigida
# no corpo e `sessoes` e nao `transferegov` — o que sai daqui e o estado da
# credencial gov.br guardada no Cofre, nao dado de transferencia. A rota mora
# neste router so por vizinhanca de assunto.
@router.get("/admin/sessao-status", dependencies=[exige("sessoes.ver")])
async def sessao_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Retorna idade/validade REAL da sessao gov.br no Cofre.

    Decodifica o JWT 'user-id' das cookies (sessao parcerias.transferegov tem
    expiracao curta ~20min, refrescada com atividade). Retorna minutos
    restantes REAIS, nao so idade da captura."""
    # Antes bastava estar LOGADO — e isto le uma linha do COFRE: devolve a
    # `observacao` da credencial, o municipio dela e os claims do gov.br
    # (vinculo, nivel, expiracao). E o mesmo tipo de vazamento que fez
    # `/api/session-capture/*` ficar de fora da lista do quiosque em
    # services/auth.py.
    #
    # A tela e `sessoes`, e NAO `transferegov` (a do irmao /admin/run-scraper),
    # de proposito: quem le isto e a tela /dashboard/sessoes, que e operacional
    # da Alavank (gestao de credencial gov.br, §12) e por isso nem entra no
    # catalogo oferecido ao cliente (services/telas_catalog.py). Quem chega
    # nessa pagina ja tem `sessoes` — o guard de rota do front usa a mesma
    # chave —, entao a exigencia e invisivel para o uso legitimo e barra
    # exatamente quem chamaria a URL direto.
    #
    # Sem exigencia de municipio: a sessao SSO do gov.br serve varios
    # municipios (a propria busca aqui e "a mais recente, de qualquer um") e
    # amarra-la a um recorte mudaria a logica de negocio, nao acrescentaria gate.
    authz.exigir_tela(user, "sessoes")
    from datetime import datetime, timezone
    from services import crypto
    import base64
    import json as _json
    r = await db.execute(text("""
        SELECT id, municipio_id, updated_at, observacao, senha_hash
        FROM cofre_senhas
        WHERE automation_key='govbr' AND length(senha_hash) > 1000
        ORDER BY updated_at DESC LIMIT 1
    """))
    row = r.first()
    if not row:
        return {"has_session": False, "message": "Nenhuma sessao gov.br capturada"}
    age_h = (datetime.now(timezone.utc) - row[2]).total_seconds() / 3600
    base: dict = {
        "has_session": True,
        "id": row[0],
        "municipio_id": row[1],
        "updated_at": row[2].isoformat(),
        "age_hours": round(age_h, 2),
        "observacao": row[3],
    }
    # Decodifica o JWT 'user-id' (sem validar assinatura) pra ver exp real
    try:
        dec = crypto.decrypt(row[4]) or ""
        data = _json.loads(dec)
        cookies = data.get("cookies", [])
        uid_cookie = next((c for c in cookies if c.get("name") == "user-id"), None)
        if uid_cookie:
            token = uid_cookie.get("value", "")
            parts = token.split(".")
            if len(parts) >= 2:
                payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
                payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
                exp_ts = payload.get("exp")
                if exp_ts:
                    now_ts = datetime.now(timezone.utc).timestamp()
                    mins = (exp_ts - now_ts) / 60
                    base["user_id_exp_minutes"] = round(mins, 1)
                    base["expired"] = mins <= 0
                    base["expira_em"] = datetime.fromtimestamp(
                        exp_ts, tz=timezone.utc).isoformat()
                    base["vinculo"] = payload.get("vinculo")
                    base["nivel"] = payload.get("nivel")
                    return base
    except Exception as e:
        base["decode_error"] = str(e)[:100]
    # Fallback: usa idade da captura (sessao tipica ~20 min)
    base["expired"] = age_h > 0.33
    return base


@router.post("/admin/run-scraper",
             dependencies=[exige("transferegov.atualizar")])
async def run_scraper_manual(
    municipio_id: Optional[int] = Query(None, description="se None, roda todos"),
    user=Depends(get_current_user),
):
    """Dispara o scraper voluntarias manualmente (background). Util apos
    re-capturar a sessao gov.br via bookmarklet."""
    ensure_municipio_access(user, municipio_id)
    ensure_tela(user, "transferegov")
    import asyncio as _aio
    from ingestion.transferegov_voluntarias import run, run_one

    async def _bg():
        try:
            if municipio_id:
                await run_one(municipio_id)
            else:
                await run()
        except Exception as e:
            import logging
            logging.getLogger("scraper-manual").exception(f"erro: {e}")

    _aio.create_task(_bg())
    return {"ok": True, "scope": "single" if municipio_id else "all",
            "message": "Scraper iniciado em background. Acompanhe via logs."}


@router.get("/pac", dependencies=[exige("transferegov.ver")])
async def listar_pac(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    parlamentar: Optional[str] = Query(None, description="filtra pela emenda parlamentar (parcial)"),
    situacao: Optional[str] = Query(None, description="filtra a situacao (parcial)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Selecao PAC / Novo PAC do municipio (coletado do TransfereGov Acesso Livre,
    tabela transferegov_pac). Retorna a listagem por municipio."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov")
    where = ["municipio_id = :m"]
    params: dict = {"m": municipio_id}
    if parlamentar:
        where.append("emenda_parlamentar ILIKE :p"); params["p"] = f"%{parlamentar}%"
    if situacao:
        where.append("situacao ILIKE :s"); params["s"] = f"%{situacao}%"
    sql = f"""
        SELECT numero_proposta, programa, programa_codigo, proponente, cnpj, situacao,
               valor_repasse, valor_contrapartida, valor_total, emenda_parlamentar,
               qualificacao, objeto, justificativa, updated_at
        FROM transferegov_pac WHERE {' AND '.join(where)}
        ORDER BY numero_proposta DESC
    """
    rows = (await db.execute(text(sql), params)).fetchall()

    # === ELO INVERSO: PAC -> VOLUNTARIA/CONVENIO ============================
    # O RM ja resolve o sentido "de qual selecao do PAC esta voluntaria nasceu"
    # (services/rm_builder._pac_da_voluntaria, usado para nao imprimir o mesmo
    # recurso duas vezes). A TELA do PAC precisa do caminho contrario: dado um
    # item da selecao, QUAL instrumento nasceu dele.
    #
    # ⚠️ SEGUNDA CONSULTA, e nao coluna nova no SELECT acima: o dict logo abaixo le
    # por INDICE (r[0]..r[13]) e uma coluna no meio deslocaria tudo em silencio.
    #
    # ⚠️ A leitura do JSONB acontece no BANCO, e nao em Python: trazer a coluna
    # `detalhe` inteira de todas as propostas do municipio so para ler UMA chave
    # poria alguns MB no fio a cada abertura da tela, e o host e burstable de
    # 2 vCPU. Com o LATERAL sai UMA linha por proposta que TEM vinculo.
    #
    # ⚠️ O pre-filtro `p.detalhe::text ILIKE '%novo pac%'` NAO e redundante com o
    # `lower(kv.key) LIKE` de dentro: sem ele o LATERAL expande TODAS as chaves de
    # TODAS as propostas do municipio (dezenas por proposta) para so entao
    # descartar. Ele derruba o conjunto para as ~35 propostas que tem o campo,
    # ANTES da expansao. E o que torna isto viavel num host de 2 vCPU.
    #
    # ⚠️ `lower(kv.key) LIKE '%novo pac%'` e o equivalente SQL da busca tolerante de
    # `_pac_da_voluntaria` (que normaliza NFD e procura "novo pac"): o trecho
    # procurado nao tem acento nenhum, so o resto do rotulo tem. Se um dia o rotulo
    # do portal mudar, os DOIS lados precisam mudar juntos.
    vinc_sql = rf"""
        SELECT regexp_replace(kv.value, '\D', '', 'g') AS pac_digitos,
               p.numero_proposta, p.codigo_instrumento, p.situacao,
               p.dt_inicio_vigencia, p.dt_fim_vigencia, p.valor_repasse,
               {_CATEGORIA_SQL} AS categoria
        FROM transferegov_propostas p
        CROSS JOIN LATERAL jsonb_each_text(
            CASE WHEN jsonb_typeof(p.detalhe) = 'object' THEN p.detalhe ELSE '{{}}'::jsonb END
        ) AS kv
        WHERE p.municipio_id = :m
          AND p.detalhe::text ILIKE '%novo pac%'
          AND left(kv.key, 1) <> '_'
          AND lower(kv.key) LIKE '%novo pac%'
          AND regexp_replace(kv.value, '\D', '', 'g') <> ''
    """
    por_pac: dict[str, list[dict]] = {}
    try:
        for v in (await db.execute(text(vinc_sql), {"m": municipio_id})).fetchall():
            por_pac.setdefault(v[0], []).append({
                "numero_proposta": v[1],
                "codigo_instrumento": v[2],
                "situacao": v[3],
                "dt_inicio_vigencia": v[4],
                "dt_fim_vigencia": v[5],
                "valor_repasse": float(v[6]) if v[6] is not None else None,
                "dias_restantes": _dias_restantes(v[5]),
                # Em qual das quatro telas de propostas o instrumento esta —
                # calculado com AS MESMAS constantes do /voluntarias (_CATEGORIA_SQL).
                "categoria": v[7],
            })
    except Exception as ex:
        # Best-effort, igual ao bloco do PAC no rm_builder: tenant onde as
        # voluntarias nunca foram raspadas nao pode PERDER a listagem do PAC por
        # causa do vinculo. Sem vinculo a tela mostra o que sempre mostrou.
        logger.warning(f"PAC: vinculo com voluntarias indisponivel p/ {municipio_id}: {str(ex)[:120]}")

    def _f(v):
        return float(v) if v is not None else None
    items = [{
        "numero_proposta": r[0], "programa": r[1], "programa_codigo": r[2],
        "proponente": r[3], "cnpj": r[4], "situacao": r[5],
        "valor_repasse": _f(r[6]), "valor_contrapartida": _f(r[7]), "valor_total": _f(r[8]),
        "emenda_parlamentar": r[9], "qualificacao": r[10],
        "objeto": r[11], "justificativa": r[12],
        # LISTA, e nao um so: nada no portal impede duas propostas apontarem para a
        # mesma selecao, e escolher uma calada esconderia a outra. Vazia = nao ha
        # instrumento CONHECIDO — nao e o mesmo que "nao ha instrumento" (tenant
        # com as voluntarias nunca raspadas cai no mesmo vazio).
        "vinculos": por_pac.get(_digits(r[0]), []),
    } for r in rows]
    atualizado = max((r[13] for r in rows if r[13]), default=None)
    return {"items": items, "total": len(items),
            "atualizado": atualizado.isoformat() if atualizado else None}
