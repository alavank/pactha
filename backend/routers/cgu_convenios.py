"""Defesa Civil e outros repasses (CGU) — o dinheiro federal fora do TransfereGov.

Lê o que `ingestion/cgu_convenios.py` grava da planilha de convênios do Portal da
Transparência. Uma tela (`cgu_convenios`), duas rotas sob `cgu_convenios.ver`:
- `""` — os instrumentos do município, separados em grupos pela pergunta da tela;
- `/ordens-bancarias` — as OBs de UM instrumento, pedidas ao abrir o cartão (Santa
  Maria tem 2.065; mandá-las todas na lista pesaria a tela à toa).

⚠️ OS TOTAIS SÃO SÓ DA PREFEITURA (`municipal`). Hospital, APAE e a UFSM ficam
na resposta, no grupo próprio, e fora das contas — regra do dono.

⚠️ "SÓ NA CGU" É `no_transferegov IS FALSE`. NULO é "não deu para conferir" (o dump
do TransfereGov falhou na rodada) e NÃO entra no grupo: dizer que o TransfereGov
não tem, sem ter olhado, seria a afirmação errada mais cara da tela.

⚠️ "Ainda não coletado" ≠ "o município não tem repasse fora do TransfereGov":
sem linha em `cgu_convenios_carga`, `coletado: false`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/cgu-convenios", tags=["cgu-convenios"])


def _f(v):
    return float(v) if v is not None else None


def _d(v):
    return v.isoformat() if v else None


def _arquivo_iso(a: str | None) -> str | None:
    """"20260911" -> "2026-09-11" (a data da planilha, não a da coleta)."""
    return f"{a[:4]}-{a[4:6]}-{a[6:8]}" if a and len(a) == 8 else None


@router.get("", dependencies=[exige("cgu_convenios.ver")])
async def listar(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Os instrumentos da CGU do município, em grupos."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cgu_convenios")
    existe = (await db.execute(text("SELECT 1 FROM municipios WHERE id = :m"),
                               {"m": municipio_id})).scalar()
    if existe is None:
        raise HTTPException(404, "Município não encontrado")
    carga = (await db.execute(text("""
        SELECT arquivo, carregado_em, siafi_municipio FROM cgu_convenios_carga
         WHERE municipio_id = :m
    """), {"m": municipio_id})).first()
    if carga is None:
        return {"coletado": False}

    linhas = (await db.execute(text("""
        SELECT c.numero, c.numero_original, c.numero_processo, c.situacao, c.objeto,
               c.orgao_superior, c.orgao_concedente, c.ug_concedente,
               c.convenente_doc, c.convenente_nome, c.tipo_convenente, c.municipal,
               c.tipo_instrumento, c.valor, c.valor_liberado, c.valor_contrapartida,
               c.data_publicacao, c.data_inicio_vigencia, c.data_final_vigencia,
               c.data_ultima_liberacao, c.valor_ultima_liberacao, c.no_transferegov,
               c.data_final_vigencia >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date
                   AS vigente,
               (SELECT count(*) FROM cgu_convenios_ob o
                 WHERE o.municipio_id = c.municipio_id AND o.numero = c.numero) AS n_ob
          FROM cgu_convenios c
         WHERE c.municipio_id = :m
         ORDER BY c.data_final_vigencia DESC NULLS LAST, c.valor DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    itens = []
    for r in linhas:
        valor, liberado = _f(r["valor"]), _f(r["valor_liberado"])
        so_cgu = r["no_transferegov"] is False
        vigente = bool(r["vigente"])
        if not r["municipal"]:
            grupo = "outros_convenentes"
        elif vigente and so_cgu:
            grupo = "vigentes_so_cgu"
        elif vigente:
            grupo = "vigentes_no_transferegov"
        else:
            grupo = "encerrados"
        itens.append({
            "numero": r["numero"], "numero_original": r["numero_original"],
            "numero_processo": r["numero_processo"], "situacao": r["situacao"],
            "objeto": r["objeto"], "orgao_superior": r["orgao_superior"],
            "orgao_concedente": r["orgao_concedente"], "ug_concedente": r["ug_concedente"],
            "convenente_nome": r["convenente_nome"],
            "tipo_convenente": r["tipo_convenente"], "municipal": r["municipal"],
            "tipo_instrumento": r["tipo_instrumento"], "valor": valor,
            "valor_liberado": liberado,
            "a_liberar": (max(valor - liberado, 0.0)
                          if valor is not None and liberado is not None else None),
            "valor_contrapartida": _f(r["valor_contrapartida"]),
            "data_publicacao": _d(r["data_publicacao"]),
            "data_inicio_vigencia": _d(r["data_inicio_vigencia"]),
            "data_final_vigencia": _d(r["data_final_vigencia"]),
            "data_ultima_liberacao": _d(r["data_ultima_liberacao"]),
            "valor_ultima_liberacao": _f(r["valor_ultima_liberacao"]),
            "no_transferegov": r["no_transferegov"], "vigente": vigente,
            "n_ob": r["n_ob"], "grupo": grupo,
        })

    so = [i for i in itens if i["grupo"] == "vigentes_so_cgu"]
    return {
        "coletado": True,
        "arquivo": _arquivo_iso(carga[0]),
        "carregado_em": _d(carga[1]),
        # A marca "só na CGU" ficou sem conferir em alguma linha? A tela avisa.
        "sem_conferencia": sum(1 for i in itens if i["no_transferegov"] is None),
        "resumo": {
            "vigentes_so_cgu": len(so),
            "valor": sum(i["valor"] or 0 for i in so),
            "liberado": sum(i["valor_liberado"] or 0 for i in so),
            "a_liberar": sum(i["a_liberar"] or 0 for i in so),
        },
        "itens": itens,
    }


@router.get("/ordens-bancarias", dependencies=[exige("cgu_convenios.ver")])
async def ordens_bancarias(
    municipio_id: int = Query(...),
    numero: str = Query(..., max_length=40),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """As ordens bancárias de um instrumento, da mais recente para a mais antiga."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "cgu_convenios")
    linhas = (await db.execute(text("""
        SELECT ordem_bancaria, data_emissao, valor FROM cgu_convenios_ob
         WHERE municipio_id = :m AND numero = :n
         ORDER BY data_emissao DESC NULLS LAST, ordem_bancaria
    """), {"m": municipio_id, "n": numero})).fetchall()
    return {"numero": numero,
            "itens": [{"ordem_bancaria": r[0], "data_emissao": _d(r[1]),
                       "valor": _f(r[2])} for r in linhas]}
