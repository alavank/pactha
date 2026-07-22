"""CAUC — regularidade fiscal FEDERAL do municipio (STN).

Mostra, por municipio, se ele esta apto a receber transferencias voluntarias
da Uniao: exigencias regulares (validade) vs pendencias ("!"). Dados de
`cauc_situacao` (ingestao `ingestion/cauc_ingest.py`, dados abertos do Tesouro).
"""
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User

router = APIRouter(prefix="/api/cauc", tags=["cauc"])

# Grupos das exigencias CAUC (pelo digito inicial do codigo).
GRUPOS = {
    "1": "Tributos, contribuicoes e Divida Ativa da Uniao",
    "2": "Financiamentos e garantias com a Uniao",
    "3": "Envio de informacoes fiscais e contabeis (SICONFI/SIOPE/SIOPS)",
    "4": "Aplicacao minima e FUNDEB (educacao e saude)",
    "5": "Transparencia, precatorios e demais exigencias",
}

# Rotulos das exigencias (STN/CAUC — descricao curta indicativa).
LABELS = {
    "1.1": "Tributos federais e Divida Ativa da Uniao (RFB/PGFN)",
    "1.2": "Contribuicoes previdenciarias federais (RFB)",
    "1.3": "FGTS (Caixa)",
    "1.4": "Financiamentos/garantias com a Uniao",
    "1.5": "Recolhimento de contribuicoes ao PASEP",
    "2.1.1": "Adimplencia em operacoes de credito (garantia da Uniao)",
    "2.1.2": "Adimplencia em contratos com a Uniao",
    "3.1.1": "RREO — Relatorio Resumido de Execucao Orcamentaria (SICONFI)",
    "3.1.2": "RGF — Relatorio de Gestao Fiscal (SICONFI)",
    "3.2.1": "DCA — Declaracao de Contas Anuais (SICONFI)",
    "3.2.2": "MSC — Matriz de Saldos Contabeis (SICONFI)",
    "3.2.3": "SIOPE — informacoes de educacao",
    "3.2.4": "SIOPS — informacoes de saude",
    "3.3": "Cadastro da Divida Publica (CDP)",
    "3.4.1": "Envio de dados ao SISTN/SADIPEM",
    "3.4.2": "Contratacao de operacoes de credito (limites)",
    "3.5": "Prestacao de contas de recursos federais",
    "3.6": "Cadastro atualizado no SICONV/TransfereGov",
    "3.7": "Regularidade previdenciaria (RPPS) — envio de dados",
    "4.1": "Aplicacao minima em Educacao (MDE)",
    "4.2": "Aplicacao minima em Saude",
    "5.1": "Certidao Negativa de Debitos Trabalhistas / demais",
    "5.2": "Transparencia (LC 131) — divulgacao em tempo real",
    "5.3": "Regularidade quanto a precatorios",
    "5.4": "CRP — Certificado de Regularidade Previdenciaria (RPPS)",
    "5.5": "FUNDEB — complementacao VAAT",
    "5.6": "FUNDEB — proporcao de aplicacao",
    "5.7": "FUNDEB — aplicacao minima",
}


def _classifica(valor: str) -> tuple[str, str]:
    """(tipo, status legivel) a partir do valor bruto do CSV do CAUC."""
    v = (valor or "").strip()
    if v == "!":
        return ("pendente", "Pendencia (impeditivo)")
    if v.lower() == "desabilitado" or v == "":
        return ("na", "Nao exigido")
    return ("regular", f"Regular ate {v}")


@router.get("")
async def situacao(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Situacao do municipio no CAUC (regularidade fiscal federal)."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cauc")
    return await fetch_cauc_situacao(db, municipio_id)


async def fetch_cauc_situacao(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta CAUC, SEM gate de auth. Reusado pelo endpoint /api/cauc
    (apos ensure_tela) e pelo Painel Executivo do prefeito (gated so por municipio)."""
    row = (await db.execute(text("""
        SELECT nome, uf, ibge, cod_siafi, populacao, data_pesquisa,
               itens, pendencias, pendencias_codigos, regular, atualizado_em
        FROM cauc_situacao WHERE municipio_id = :m
    """), {"m": municipio_id})).first()
    if not row:
        return {"tem_dados": False}

    itens_raw = row[6] if isinstance(row[6], dict) else {}
    itens = []
    for codigo, valor in itens_raw.items():
        tipo, status = _classifica(valor)
        itens.append({
            "codigo": codigo,
            "grupo": GRUPOS.get(codigo.split(".")[0], "Outras"),
            "label": LABELS.get(codigo, f"Exigencia {codigo}"),
            "valor": valor,
            "tipo": tipo,
            "status": status,
        })
    # ordena por codigo (numerico por segmento)
    def _key(it):
        return [int(x) if x.isdigit() else 0 for x in it["codigo"].split(".")]
    itens.sort(key=_key)

    return {
        "tem_dados": True,
        "nome": row[0], "uf": row[1], "ibge": row[2], "cod_siafi": row[3],
        "populacao": row[4],
        "data_pesquisa": row[5].isoformat() if row[5] else None,
        "regular": row[9],
        "pendencias": row[7],
        "pendencias_codigos": list(row[8] or []),
        "itens": itens,
        "atualizado_em": row[10].isoformat() if row[10] else None,
    }


@router.post("/refresh")
async def refresh(
    _: User = Depends(get_current_user),
):
    """Dispara a ingestao do CAUC manualmente (dados abertos do Tesouro)."""
    from ingestion.cauc_ingest import ingest
    import anyio
    n = await anyio.to_thread.run_sync(ingest)
    return {"ok": True, "municipios": n}
