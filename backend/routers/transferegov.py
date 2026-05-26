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
from services.auth import get_current_user
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


async def _fetch_listagem(uf: str = "MG") -> list[dict]:
    """Busca lista completa de planos de acao de uma UF (com cache)."""
    now = time.time()
    cached = _CACHE.get(uf)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]
    async with httpx.AsyncClient(timeout=60, verify=False) as cli:
        r = await cli.get(f"{API_BASE}/public/plano-acao/listagem",
                          params={"uf": uf, "page": 0, "size": 99999},
                          headers=HEADERS)
        r.raise_for_status()
        data = r.json()
    items = data.get("listaPlanosAcao") or []
    _CACHE[uf] = (now, items)
    return items


@router.get("/buscar")
async def buscar(
    municipio_id: int = Query(..., description="ID do municipio PACTA"),
    situacao: Optional[str] = Query(None, description="CIENTE, EM_ANALISE, IMPEDIDO, etc"),
    programa: Optional[str] = Query(None, description="codigo do programa (ex: 09032022)"),
    parlamentar: Optional[str] = Query(None, description="texto livre - busca em codigoEmendaFormatado"),
    emenda: Optional[str] = Query(None, description="codigo da emenda formatado"),
    objeto: Optional[str] = Query(None, description="busca em politicasPublicas"),
    refresh: bool = Query(False, description="forca refresh do cache"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lista planos de acao filtrados pelo municipio + filtros opcionais.

    A API do TransfereGov nao oferece filtro server-side por municipio, entao
    baixa lista completa de MG (com cache 1h) e filtra por nome do municipio
    do PACTA + filtros adicionais.
    """
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
        if situacao and _norm(situacao) != _norm(it.get("planoAcaoSituacao") or ""):
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


@router.get("/voluntarias")
async def voluntarias(
    municipio_id: int = Query(...),
    situacao: Optional[str] = Query(None),
    orgao: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="busca em numero/proponente"),
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Lista propostas de Transferencias Voluntarias (SICONV) de um municipio.

    Dados coletados pelo scraper Playwright (acesso livre guest) em
    transferegov_propostas. Refresh via cron/ on-demand.
    """
    where = ["municipio_id = :mun"]
    params: dict = {"mun": municipio_id}
    if situacao:
        where.append("situacao ILIKE :sit"); params["sit"] = f"%{situacao}%"
    if orgao:
        where.append("orgao ILIKE :org"); params["org"] = f"%{orgao}%"
    if search:
        where.append("(numero_proposta ILIKE :s OR proponente ILIKE :s)"); params["s"] = f"%{search}%"
    sql = f"""
        SELECT numero_proposta, situacao, orgao, proponente, possui_parecer,
               identificacao, codigo_instrumento, modalidade, situacao_siafi,
               numero_processo, objeto, programa, dt_inicio_vigencia,
               dt_fim_vigencia, dt_proposta, dt_assinatura, updated_at
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
    } for row in r.fetchall()]

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
    _=Depends(get_current_user),
):
    """Detalhe completo de uma proposta (todos os campos capturados do portal)."""
    r = await db.execute(text("""
        SELECT numero_proposta, situacao, orgao, proponente, identificacao,
               codigo_instrumento, modalidade, situacao_siafi, numero_processo,
               objeto, programa, dt_inicio_vigencia, dt_fim_vigencia,
               dt_proposta, dt_assinatura, detalhe
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
