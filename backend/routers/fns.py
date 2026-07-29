"""Proxy autenticado pra busca em tempo real no consultafns.saude.gov.br.

API descoberta via inspect:
- GET /recursos/proposta/consultar?ano=YYYY&coEsfera=&coMunicipioIbge=XXXXXX&sgUf=MG&count=20&page=1
- GET /recursos/anos
- GET /recursos/ufs
- GET /recursos/municipios/uf/{uf}

Autenticacao via cookies de sessao captura via bookmarklet (cofre_senhas
sistema='Sessao FNS').
"""
import asyncio
import json
import logging
import os
from typing import Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_tela
from models.user import User
from services.crypto import decrypt

router = APIRouter(prefix="/api/fns", tags=["fns"])
logger = logging.getLogger("fns")

FNS_BASE = "https://consultafns.saude.gov.br"

# Codigos IBGE FNS dos municipios PACTHA (6 digitos, sem digito verificador)
FNS_CODE_OVERRIDE = {
    "ARAUJOS": "310390",
    "NOVA SERRANA": "314520",
    "BOM DESPACHO": "310740",
    "SAO TIAGO": "316500",
    "TOLEDO": "316910",
    "PIRACEMA": "315060",
}


async def _ensure_fns_municipio(current, municipio: str, db: AsyncSession) -> None:
    """Non-admin so consulta FNS de municipio no seu escopo (casa por nome ou IBGE)."""
    ensure_tela(current, "fns")
    allowed = getattr(current, "allowed_municipio_ids", None)
    if allowed is None:  # admin -> todos
        return
    if not allowed:
        raise HTTPException(403, "Voce nao tem municipios atribuidos")
    rows = await db.execute(
        text("SELECT nome, ibge_code FROM municipios WHERE id = ANY(:ids)"),
        {"ids": list(allowed)},
    )
    alvo = (municipio or "").strip().upper()
    for nome, ibge in rows.fetchall():
        n = (nome or "").strip().upper()
        ib = (ibge or "").strip()
        if alvo in (n, ib, ib[:6]) or FNS_CODE_OVERRIDE.get(n) == alvo:
            return
    raise HTTPException(403, "Voce nao tem acesso a este municipio")


async def _get_cookies(db: AsyncSession) -> dict:
    """Cookies da sessao FNS — OPCIONAIS. A API do ConsultaFNS
    (consultafns.saude.gov.br/recursos/...) e PUBLICA: funciona sem login.
    Se houver uma sessao valida no cofre, usa (belt-and-suspenders); senao {}."""
    try:
        r = await db.execute(text("SELECT senha_hash FROM cofre_senhas WHERE sistema = 'Sessao FNS' LIMIT 1"))
        row = r.first()
        if not row:
            return {}
        data = json.loads(decrypt(row[0]) or "{}")
        cookies = data.get("cookies", [])
        return {c["name"]: c["value"] for c in cookies if "name" in c}
    except Exception:
        return {}


async def _resolve_cod(municipio: str, uf: str, db: AsyncSession) -> Optional[str]:
    """Nome do municipio -> codigo IBGE 6 digitos (FNS). Usa a tabela `municipios`
    do AMBIENTE (ibge_code sem o digito verificador). Fallbacks: override legado
    e a API de municipios do FNS. Funciona em qualquer ambiente/instalacao."""
    m = (municipio or "").strip()
    if m.isdigit():
        return m
    row = (await db.execute(
        text("SELECT ibge_code FROM municipios WHERE upper(nome) = upper(:m) LIMIT 1"),
        {"m": m})).first()
    if row and row[0]:
        return str(row[0])[:6]
    cod = FNS_CODE_OVERRIDE.get(m.upper())
    if cod:
        return cod
    try:
        cookies = await _get_cookies(db)
        with httpx.Client(cookies=cookies, timeout=15, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/municipios/uf/{uf}",
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            for mm in r.json().get("resultado", []):
                if (mm.get("noMunicipio", "") or "").upper().strip() == m.upper():
                    return mm.get("coMunicipioIbge")
    except Exception:
        pass
    return None


@router.get("/buscar")
async def buscar(
    municipio: str = Query(..., description="Nome do municipio (ex: ARAUJOS) ou codigo IBGE 6 digitos"),
    ano: int = Query(...),
    uf: str = Query("MG"),
    nr_proposta: Optional[str] = Query(None),
    tipo_emenda: Optional[str] = Query(None, description="TODOS, INDIVIDUAL, BANCADA, COMISSAO, BANCADA OBRIGATORIA"),
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Busca propostas FAF no FNS em tempo real."""
    await _ensure_fns_municipio(current, municipio, db)
    return await consultar_fns(db, municipio, ano, uf, nr_proposta, tipo_emenda, pagina, tamanho)


async def consultar_fns(
    db: AsyncSession,
    municipio: str,
    ano: int,
    uf: str = "MG",
    nr_proposta: Optional[str] = None,
    tipo_emenda: Optional[str] = None,
    pagina: int = 1,
    tamanho: int = 50,
) -> dict:
    """Nucleo da consulta FNS, SEM gate de auth. Reusado pelo endpoint /api/fns/buscar
    (apos _ensure_fns_municipio) e pelo Painel de Indicadores (gated por escopo em
    /api/bi/fns), que consulta VARIOS anos de uma vez."""
    # Resolve codigo IBGE FNS (tabela municipios do ambiente + fallbacks)
    cod = await _resolve_cod(municipio, uf, db)
    if not cod:
        raise HTTPException(404, f"Municipio '{municipio}' nao mapeado")

    cookies = await _get_cookies(db)
    params = {
        "ano": str(ano),
        "coEsfera": "",
        "coMunicipioIbge": cod,
        "count": str(tamanho),
        "page": str(pagina),
        "sgUf": uf,
    }
    if nr_proposta:
        params["nuProposta"] = nr_proposta
    # Filtro de emenda: o FNS usa o parametro `tpEmenda` com o valor exato do
    # portal (INDIVIDUAL, BANCADA, BANCADA OBRIGATÓRIA com acento, COMISSAO,
    # RELATOR). dsTipoRecurso NAO filtra (e ignorado pelo servidor).
    if tipo_emenda and tipo_emenda.upper() != "TODOS":
        params["tpEmenda"] = tipo_emenda

    # httpx.Client e SINCRONO: roda numa thread p/ nao travar o event loop
    # (o Painel de Indicadores dispara varios anos de uma vez).
    def _fetch() -> dict:
        with httpx.Client(cookies=cookies, timeout=30, verify=False) as cli:
            r = cli.get(
                f"{FNS_BASE}/recursos/proposta/consultar",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"{FNS_BASE}/",
                },
            )
            if r.status_code == 401 or "login" in r.text[:200].lower():
                raise HTTPException(401, "Sessao FNS expirada. Re-capture via bookmarklet.")
            r.raise_for_status()
            return r.json()

    try:
        data = await asyncio.to_thread(_fetch)
    except HTTPException as e:
        # NAO propagar 401 daqui: o interceptor do frontend trata 401 como sessao
        # do PACTHA expirada e desloga o usuario. Sessao do FNS != sessao do app.
        raise HTTPException(502, f"Falha FNS: {e.status_code}: {e.detail}")
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"FNS: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    resultado = data.get("resultado", {}) or {}
    items = resultado.get("itensPagina", []) or []
    normalized = []
    for it in items:
        normalized.append({
            "tipo_proposta": it.get("coTipoProposta"),
            "tipo_recurso": it.get("dsTipoRecurso"),
            "nu_processo": it.get("nuProcesso"),
            "valor_proposta": float(it.get("vlProposta") or 0),
            "valor_pago": float(it.get("vlPago") or 0),
            "valor_pagar": float(it.get("vlPagar") or 0),
            "constituido_processo": it.get("constituidoProcesso"),
            "parlamentares": it.get("parlamentares", []),
            "pagamentos_count": len(it.get("pagamentos", []) or []),
        })
    return {
        "items": normalized,
        "params": {"municipio": municipio, "cod_ibge": cod, "ano": ano, "uf": uf},
        "total": len(normalized),
        "totais": {
            "valor_proposta": sum(i["valor_proposta"] for i in normalized),
            "valor_pago": sum(i["valor_pago"] for i in normalized),
            "valor_pagar": sum(i["valor_pagar"] for i in normalized),
        },
    }


@router.get("/anos")
async def anos(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    """Anos disponiveis no FNS."""
    cookies = await _get_cookies(db)
    try:
        with httpx.Client(cookies=cookies, timeout=15, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/anos",
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            return [a.get("valor") for a in r.json().get("resultado", [])]
    except Exception as e:
        # Fallback: range
        from datetime import datetime
        return [str(y) for y in range(datetime.now().year, 2018, -1)]


@router.get("/municipios")
async def municipios_pacta(db: AsyncSession = Depends(get_db), _=Depends(get_current_user)):
    """Lista os municipios do AMBIENTE com codigo IBGE FNS
    (6 digitos = ibge_code sem o digito verificador) + UF, ordenados por nome."""
    rows = (await db.execute(text(
        "SELECT id, nome, ibge_code, uf FROM municipios WHERE active = true "
        "AND ibge_code IS NOT NULL ORDER BY nome"))).fetchall()
    return [{"id": i, "nome": n, "cod_ibge": str(ib)[:6], "uf": uf} for i, n, ib, uf in rows]


@router.get("/proposta/{nu_proposta}")
async def detalhe_proposta(
    nu_proposta: str,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Detalhe completo de uma proposta individual.

    Endpoint upstream:
      GET /recursos/proposta/obter-proposta?nuProposta=XXX
      GET /recursos/proposta/obter-proposta-etapa  (mapa de 12 etapas)
    """
    cookies = await _get_cookies(db)
    try:
        with httpx.Client(cookies=cookies, timeout=20, verify=False) as cli:
            # Detalhe principal
            r1 = cli.get(
                f"{FNS_BASE}/recursos/proposta/obter-proposta",
                params={"nuProposta": nu_proposta},
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                         "Referer": f"{FNS_BASE}/"},
            )
            r1.raise_for_status()
            d = r1.json().get("resultado", {}) or {}

            # Etapas
            # Sem nuProposta o portal devolve 400 e o mapa de etapas vinha vazio
            # (o erro era engolido pelo except) -> a trilha de 12 etapas nunca
            # aparecia no detalhe.
            r2 = cli.get(
                f"{FNS_BASE}/recursos/proposta/obter-proposta-etapa",
                params={"nuProposta": nu_proposta},
                headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                         "Referer": f"{FNS_BASE}/"},
            )
            etapas_map = r2.json().get("resultado", {}) if r2.status_code == 200 else {}
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, f"FNS: {e.response.text[:200]}")
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    # Determina workflow ativo (Contrato de Repasse, Outros Tipos, etc)
    # Por padrao, usa Contrato de Repasse (12 etapas)
    workflow_key = "Contrato de Repasse"
    etapas_list = etapas_map.get(workflow_key, []) or []
    sit_cod = (d.get("situacao") or {}).get("codigoSituacaoProjeto")
    current_etapa = None
    for et in etapas_list:
        if sit_cod and sit_cod in (et.get("situacoes") or []):
            current_etapa = et.get("etapa")
            break

    return {
        "nu_proposta": d.get("nuProposta"),
        "uf": d.get("sgUf"),
        "municipio": d.get("noMunicipio"),
        "cnpj": d.get("cnpjFormatado") or d.get("cnpj"),
        "entidade": d.get("noEntidade"),
        "tipo_proposta": d.get("coTipoProposta"),
        "valor_proposta": float(d.get("vlProposta") or 0),
        "ano": d.get("nuAnoProposta"),
        "tipo_recurso": d.get("dsTipoRecurso"),
        "esfera": d.get("coEsfera"),
        "nu_portaria": d.get("nuPortaria") or None,
        "nu_processo": d.get("nuProcesso"),
        "situacao_descricao": (d.get("situacao") or {}).get("descricaoSituacaoproposta"),
        "situacao_data": (d.get("situacao") or {}).get("dataSituacaoProjeto"),  # ms epoch
        "vl_empenhado": float(d.get("vlEmpenhado") or 0),
        "vl_pago": float(d.get("vlPago") or 0),
        "vl_pagar": float(d.get("vlPagar") or 0),
        # Normaliza parlamentares (campo upstream: noApelidoPolitico, sgPartido, vlIndObjeto, coEmendaPolitica, nuAnoExercicio)
        "parlamentares": [
            {
                "nome": p.get("noApelidoPolitico") or p.get("nome"),
                "partido": p.get("sgPartido") or p.get("partido") or "",
                "nu_emenda": p.get("coEmendaPolitica"),
                "ano": p.get("nuAnoExercicio"),
                "valor": float(p.get("vlIndObjeto") or 0),
            }
            for p in (d.get("parlamentares") or [])
        ],
        # Normaliza pagamentos (campo upstream: dtCriacaoSiafi (ms), nuParcela, localizacao, nuProcesso, nuOb, vlLiquido, vlAcumulado)
        "pagamentos": [
            {
                "parcela": pg.get("nuParcela"),
                "data": pg.get("dtCriacaoSiafi"),  # ms epoch
                "valor": float(pg.get("vlLiquido") or 0),
                "valor_acumulado": float(pg.get("vlAcumulado") or 0),
                "ordem_bancaria": pg.get("nuOb"),
                "nu_processo": pg.get("nuProcesso"),
                "localizacao": pg.get("localizacao"),
            }
            for pg in (d.get("pagamentos") or [])
        ],
        "data_portaria": d.get("dtPortaria"),  # ms epoch
        "constituido_processo": d.get("constituidoProcesso"),
        "situacao_ultima_analise": d.get("situacaoUltimaAnalise"),
        "ultimo_processo": d.get("ultimoProcesso"),
        "etapas": [
            {
                "numero": et.get("etapa"),
                "descricao": et.get("descricao"),
                "completada": (et.get("etapa") or 0) <= (current_etapa or 0),
                "atual": et.get("etapa") == current_etapa,
            }
            for et in etapas_list
        ],
        "etapa_atual": current_etapa,
    }


@router.get("/listar-individuais")
async def listar_individuais(
    municipio: str = Query(...),
    ano: int = Query(...),
    uf: str = Query("MG"),
    tipo_proposta: str = Query(..., description="Ex: EQUIPAMENTO, CUSTEIO MAC, INCREMENTO PAP"),
    tipo_recurso: str = Query(..., description="PROGRAMA / EMENDA INDIVIDUAL / etc"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista propostas individuais de um grupo (nivel 1 do detalhamento).

    Descoberto via portalCtrl.grid2() do FNS: quando o usuario clica no
    botao olho, o portal chama /recursos/proposta/consultar com OS MESMOS
    params da listagem MAS substitui `coTipoProposta/dsTipoRecurso` por
    `tpProposta/tpRecurso` (URL-encoded). Esses dois parametros
    "destravam" o agrupamento: a resposta vem com 1 item POR PROPOSTA
    individual (cada um com nuProposta), ao inves do agregado.
    """
    await _ensure_fns_municipio(current, municipio, db)
    cod = await _resolve_cod(municipio, uf, db) or municipio
    cookies = await _get_cookies(db)
    params = {
        "ano": str(ano), "coEsfera": "", "coMunicipioIbge": cod,
        "count": "200", "page": "1", "sgUf": uf,
        # Note: httpx faz urlencode automaticamente
        "tpProposta": tipo_proposta, "tpRecurso": tipo_recurso,
    }
    try:
        with httpx.Client(cookies=cookies, timeout=20, verify=False) as cli:
            r = cli.get(f"{FNS_BASE}/recursos/proposta/consultar", params=params,
                        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0",
                                 "Referer": f"{FNS_BASE}/"})
            r.raise_for_status()
            res = r.json().get("resultado", {}) or {}
    except Exception as e:
        raise HTTPException(502, f"Falha FNS: {e}")

    items = res.get("itensPagina", []) or []
    individuais = []
    for it in items:
        individuais.append({
            "tipo_proposta": it.get("coTipoProposta"),
            "tipo_recurso": it.get("dsTipoRecurso"),
            "nu_proposta": it.get("nuProposta"),
            "entidade": it.get("noEntidade") or "FUNDO MUNICIPAL DE SAUDE",
            "municipio": it.get("noMunicipio"),
            "nu_processo": it.get("nuProcesso"),
            "valor_proposta": float(it.get("vlProposta") or 0),
            "valor_pago": float(it.get("vlPago") or 0),
            "valor_pagar": float(it.get("vlPagar") or 0),
            "constituido_processo": it.get("constituidoProcesso"),
            "qtd_parlamentares": len(it.get("parlamentares") or []),
            "qtd_pagamentos": len(it.get("pagamentos") or []),
        })
    return {"items": individuais, "total": len(individuais),
            "grupo": {"tipo_proposta": tipo_proposta, "tipo_recurso": tipo_recurso,
                      "municipio": municipio, "ano": ano, "uf": uf}}
