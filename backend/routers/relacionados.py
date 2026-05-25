"""Correlacao cross-fonte: dado um lancamento, encontra registros relacionados
em outras telas (Convenios SIGCON, Plano de Acao, Emendas, FNS, Voluntarias).

Chaves de match:
- numero (proposta/plano/instrumento/siafi/processo): comparacao por digitos normalizados
- parlamentar: nome normalizado (sem acento, upper), match por conteudo
- objeto: similaridade fuzzy (difflib) >= 0.6
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user

router = APIRouter(prefix="/api/relacionados", tags=["relacionados"])


def _digits(s: Optional[str]) -> str:
    return re.sub(r"\D", "", s or "")


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    return "".join(c for c in unicodedata.normalize("NFKD", s.upper()) if not unicodedata.combining(c)).strip()


def _fuzzy(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _num_match(origem_nums: set[str], cand_nums: list[Optional[str]]) -> Optional[str]:
    """Retorna o numero que casou (>= 5 digitos para evitar falso positivo)."""
    for cn in cand_nums:
        d = _digits(cn)
        if len(d) >= 5 and d in origem_nums:
            return cn
    return None


@router.get("")
async def relacionados(
    municipio_id: int = Query(...),
    fonte: str = Query(..., description="fonte de origem (convenios|plano-acao|emendas|fns|voluntarias)"),
    proposta: Optional[str] = None,
    plano: Optional[str] = None,
    instrumento: Optional[str] = None,
    siafi: Optional[str] = None,
    processo: Optional[str] = None,
    parlamentar: Optional[str] = None,
    objeto: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    # Conjunto de numeros da origem (somente digitos, >=5)
    origem_nums = set()
    for n in (proposta, plano, instrumento, siafi, processo):
        d = _digits(n)
        if len(d) >= 5:
            origem_nums.add(d)
    parl_norm = _norm(parlamentar)
    obj = objeto or ""

    grupos = []

    def add_match(cand_nums, cand_parl, cand_obj):
        """Avalia um candidato; retorna (chave, score) ou None."""
        # 1) numero
        nm = _num_match(origem_nums, cand_nums)
        if nm:
            return (f"Nº {nm}", 1.0)
        # 2) parlamentar
        if parl_norm and cand_parl:
            cp = _norm(cand_parl)
            if parl_norm and (parl_norm in cp or cp in parl_norm) and len(parl_norm) >= 4:
                return (f"Parlamentar: {cand_parl}", 0.9)
        # 3) objeto fuzzy
        if obj and cand_obj:
            r = _fuzzy(obj, cand_obj)
            if r >= 0.6:
                return (f"Objeto similar ({int(r*100)}%)", round(r, 2))
        return None

    # --- Convenios SIGCON ---
    if fonte != "convenios":
        r = await db.execute(text("""
            SELECT id, nr_sigcon, nr_siafi, nr_plano_trabalho, situacao, objeto,
                   valor_concedente, raw_data->>'nr_proposta' AS rp,
                   raw_data->>'nr_instrumento' AS ri
            FROM convenios_estadual WHERE municipio_id = :m
        """), {"m": municipio_id})
        ms = []
        for row in r.fetchall():
            m = add_match([row[1], row[2], row[3], row[7], row[8]], None, row[5])
            if m:
                ms.append({"titulo": (row[5] or "")[:80], "subtitulo": f"SIGCON {row[1] or ''} · {row[4] or ''}",
                           "valor": float(row[6]) if row[6] else None, "chave_match": m[0], "score": m[1]})
        if ms:
            grupos.append({"fonte": "Convênios (SIGCON-MG)", "tela": "convenios", "matches": sorted(ms, key=lambda x: -x["score"])[:10]})

    # --- TransfereGov Voluntarias ---
    if fonte != "voluntarias":
        r = await db.execute(text("""
            SELECT numero_proposta, codigo_instrumento, numero_processo, situacao,
                   objeto, orgao, proponente
            FROM transferegov_propostas WHERE municipio_id = :m
        """), {"m": municipio_id})
        ms = []
        for row in r.fetchall():
            m = add_match([row[0], row[1], row[2]], None, row[4])
            if m:
                ms.append({"titulo": (row[4] or "")[:80], "subtitulo": f"Vol. {row[0]} · {row[3] or ''} · {(row[5] or '')[:30]}",
                           "valor": None, "chave_match": m[0], "score": m[1]})
        if ms:
            grupos.append({"fonte": "TransfereGov Voluntárias", "tela": "transferegov-voluntarias", "matches": sorted(ms, key=lambda x: -x["score"])[:10]})

    # --- Emendas Estaduais ---
    if fonte != "emendas":
        r = await db.execute(text("""
            SELECT nr_indicacao, nome_responsavel, valor_indicacao, status_indicacao,
                   beneficiario, tipo_atendimento, ano
            FROM emendas_estaduais WHERE municipio_id = :m
        """), {"m": municipio_id})
        ms = []
        for row in r.fetchall():
            obj_cand = f"{row[4] or ''} {row[5] or ''}"
            m = add_match([row[0]], row[1], obj_cand)
            if m:
                ms.append({"titulo": (row[5] or row[4] or "")[:80],
                           "subtitulo": f"Emenda {row[0] or ''} · {row[1] or ''} · {row[3] or ''}",
                           "valor": float(row[2]) if row[2] else None, "chave_match": m[0], "score": m[1]})
        if ms:
            grupos.append({"fonte": "Emendas Estaduais", "tela": "emendas", "matches": sorted(ms, key=lambda x: -x["score"])[:10]})

    total = sum(len(g["matches"]) for g in grupos)
    return {
        "origem": {"fonte": fonte, "proposta": proposta, "plano": plano,
                   "instrumento": instrumento, "siafi": siafi, "processo": processo,
                   "parlamentar": parlamentar, "objeto": (obj or "")[:100]},
        "grupos": grupos,
        "total": total,
    }
