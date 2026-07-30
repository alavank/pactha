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


async def _fetch_listagem(uf: Optional[str] = "MG") -> list[dict]:
    """Lista de planos de acao (com cache 1h). uf vazio/None => NACIONAL (todos
    os estados: ~58k itens). A API nao filtra por CNPJ no servidor -> filtramos local."""
    key = (uf or "BR").upper()
    now = time.time()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    params: dict = {"page": 0, "size": 99999}
    if uf:
        params["uf"] = uf  # omitir uf => nacional
    async with httpx.AsyncClient(timeout=120, verify=False) as cli:
        r = await cli.get(f"{API_BASE}/public/plano-acao/listagem",
                          params=params, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
    items = data.get("listaPlanosAcao") or []
    _CACHE[key] = (now, items)
    return items


@router.get("/buscar")
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
        raise HTTPException(404, "Municipio nao encontrado")

    if refresh:
        _CACHE.pop(mun.uf, None)

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


@router.get("/por-cnpj")
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
        raise HTTPException(400, "Informe um CNPJ valido (14 digitos)")

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

    # 2) Voluntarias/Convenios: base SICONV federal (Brasil inteiro, dados abertos),
    #    por CNPJ. Dado publico -> nao escopado por municipio.
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


@router.get("/voluntarias")
async def voluntarias(
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    orgao: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="busca em numero/proponente"),
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
      - voluntarias: status "Proposta/Plano de Trabalho enviado para Analise"
      - rejeitadas: status com "Rejeitad"
      - encerradas: Anulado / Rescindido / Prestacao de Contas Concluida/Aprovada
      - geral: o restante (Em execucao, Aprovados em curso, em analise, etc.)
              -- exclui voluntarias, rejeitadas E encerradas
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov")
    where = ["municipio_id = :mun"]
    params: dict = {"mun": municipio_id}
    if categoria == "voluntarias":
        where.append(_VOLUNTARIA_SQL)
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
    if search:
        # Busca por numero / proponente (nome) / CNPJ (identificacao). Aceita CNPJ
        # com ou sem mascara: compara tambem so os digitos.
        conds = ["numero_proposta ILIKE :s", "proponente ILIKE :s", "identificacao ILIKE :s"]
        params["s"] = f"%{search}%"
        _sd = _digits(search)
        if _sd:
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


@router.get("/voluntarias/{numero_proposta:path}")
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
               historico_comunicacoes, documentos_quadro_resumo, historico_atualizado_em
        FROM transferegov_propostas
        WHERE municipio_id = :mun AND numero_proposta = :num
    """), {"mun": municipio_id, "num": numero_proposta})
    row = r.first()
    if not row:
        raise HTTPException(404, "Proposta nao encontrada")
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
    }


@router.get("/plano-acao/{plano_acao_id}")
async def detalhe(plano_acao_id: int, _=Depends(get_current_user)):
    """Detalhe completo de um Plano de Acao + relatorio de gestao + extrato."""
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
        return {"plano": plano, "resumo": resumo, "extrato": extrato}


# ============================================================================
# ADMIN: status da sessao gov.br + dispara scraper manualmente apos re-captura
# ============================================================================

@router.get("/admin/sessao-status")
async def sessao_status(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Retorna idade/validade REAL da sessao gov.br no Cofre.

    Decodifica o JWT 'user-id' das cookies (sessao parcerias.transferegov tem
    expiracao curta ~20min, refrescada com atividade). Retorna minutos
    restantes REAIS, nao so idade da captura."""
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


@router.post("/admin/run-scraper")
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


@router.get("/pac")
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
    def _f(v):
        return float(v) if v is not None else None
    items = [{
        "numero_proposta": r[0], "programa": r[1], "programa_codigo": r[2],
        "proponente": r[3], "cnpj": r[4], "situacao": r[5],
        "valor_repasse": _f(r[6]), "valor_contrapartida": _f(r[7]), "valor_total": _f(r[8]),
        "emenda_parlamentar": r[9], "qualificacao": r[10],
        "objeto": r[11], "justificativa": r[12],
    } for r in rows]
    atualizado = max((r[13] for r in rows if r[13]), default=None)
    return {"items": items, "total": len(items),
            "atualizado": atualizado.isoformat() if atualizado else None}
