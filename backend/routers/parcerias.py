"""Gestão de Parcerias — a emenda de saúde do município, por parlamentar.

Le a tabela `parcerias_propostas`, alimentada por `ingestion/parcerias.py` a
partir de `api-publica.transferegov.gestao.gov.br/parcerias`. O modulo processa
as transferencias de 2024 em diante — 144 dos 176 programas publicados sao
Fundo a Fundo da Saude —, e ate 07/09/2026 era o unico instrumento federal que a
plataforma nao enxergava.

⭐ A LEITURA QUE ESTA TELA EXISTE PARA DAR e a de PARLAMENTAR: quanto cada um
destinou ao municipio, em quantas propostas, e em que pe cada uma esta. Medido
no tenant trust: Comissao da Saude com 84 propostas e R$ 67,7 milhoes; Bancada
de Goias com R$ 69 mi. Nenhum desses numeros existia no produto.

⚠️ NAO CONFUNDIR COM A TELA DE VOLUNTARIAS. Aquela mostra os convenios
discricionarios do SICONV, que continuam vindo dos dumps CSV. Esta e outro
modulo, com outro ciclo (proposta -> parceria) e outro tipo de instrumento. As
duas coexistem de proposito.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Municipio
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/parcerias", tags=["parcerias"])

# A fonte publica o instrumento; o link deixa qualquer numero desta tela
# conferivel por quem duvidar dele.
URL_FONTE = ("https://api-publica.transferegov.gestao.gov.br/parcerias/"
             "proposta?id_proposta=")

MOTIVO_SEM_COLETA = (
    "A coleta da Gestão de Parcerias ainda não rodou para este município. "
    "Ela é diária e cobre as transferências de 2024 em diante."
)


def _f(v) -> Optional[float]:
    """`None` continua `None`. ⚠️ Proposta sem valor declarado não é proposta de
    R$ 0,00 — zero na tela seria uma afirmação que a fonte não faz."""
    return float(v) if v is not None else None


def _d(v) -> Optional[str]:
    return v.isoformat() if v is not None else None


async def fetch_parcerias(db: AsyncSession, municipio_id: int) -> dict:
    """Nucleo da consulta, SEM gate de auth — mesmo desenho de
    `fetch_obras_federais`, para o Painel de Indicadores poder reusar depois sem
    duplicar a agregacao."""
    linhas = (await db.execute(text("""
        SELECT id_proposta, objeto, situacao, valor_total, ano_proposta,
               data_proposta, nome_ente_recebedor, cnpj_ente_recebedor,
               natureza_juridica, id_parceria, codigo_parceria,
               situacao_parceria, data_assinatura, numero_emenda, parlamentar,
               tipo_emenda, valor_emenda, resultado_esperado, atualizado_em
          FROM parcerias_propostas
         WHERE municipio_id = :m
         ORDER BY ano_proposta DESC NULLS LAST, valor_total DESC NULLS LAST
    """), {"m": municipio_id})).mappings().all()

    if not linhas:
        return {"tem_dados": False, "motivo": MOTIVO_SEM_COLETA}

    itens = []
    # ⚠️ AGREGADOS EM PYTHON, e não em SQL com GROUP BY: a tela precisa da lista
    # E dos dois resumos na mesma resposta, e uma segunda consulta ao banco para
    # somar o que já está em memória seria trabalho pago duas vezes.
    por_parlamentar: dict[str, dict] = {}
    por_situacao: dict[str, int] = {}
    total = total_emenda = 0.0
    for p in linhas:
        valor = _f(p["valor_total"])
        vl_emenda = _f(p["valor_emenda"])
        total += valor or 0
        total_emenda += vl_emenda or 0
        itens.append({
            "id_proposta": p["id_proposta"],
            "objeto": p["objeto"],
            "situacao": p["situacao"],
            "valor": valor,
            "ano": p["ano_proposta"],
            "data_proposta": _d(p["data_proposta"]),
            "ente_recebedor": p["nome_ente_recebedor"],
            "cnpj_recebedor": p["cnpj_ente_recebedor"],
            "natureza_juridica": p["natureza_juridica"],
            # Nulo enquanto a proposta não virou instrumento — estado legítimo e
            # frequente, e a tela mostra "não celebrada" em vez de esconder.
            "id_parceria": p["id_parceria"],
            "codigo_parceria": p["codigo_parceria"],
            "situacao_parceria": p["situacao_parceria"],
            "data_assinatura": _d(p["data_assinatura"]),
            "numero_emenda": p["numero_emenda"],
            "parlamentar": p["parlamentar"],
            "tipo_emenda": p["tipo_emenda"],
            "valor_emenda": vl_emenda,
            "resultado_esperado": p["resultado_esperado"],
            "url_fonte": URL_FONTE + str(p["id_proposta"]),
        })
        if p["parlamentar"]:
            e = por_parlamentar.setdefault(
                p["parlamentar"], {"parlamentar": p["parlamentar"],
                                   "propostas": 0, "valor": 0.0,
                                   "tipo": p["tipo_emenda"]})
            e["propostas"] += 1
            e["valor"] += vl_emenda or 0
        sit = p["situacao"] or "Sem situação"
        por_situacao[sit] = por_situacao.get(sit, 0) + 1

    return {
        "tem_dados": True,
        "itens": itens,
        "total": len(itens),
        "valor_total": round(total, 2),
        "valor_emenda": round(total_emenda, 2),
        # ⭐ O RANKING É O PRODUTO DESTA TELA. Ordenado por valor, que é a
        # pergunta que o gestor faz — "quem trouxe mais para a cidade".
        "por_parlamentar": sorted(por_parlamentar.values(),
                                  key=lambda e: -e["valor"]),
        "por_situacao": sorted(
            [{"situacao": k, "qtd": v} for k, v in por_situacao.items()],
            key=lambda e: -e["qtd"]),
        "atualizado_em": max((p["atualizado_em"] for p in linhas
                              if p["atualizado_em"]), default=None),
    }


@router.get("", dependencies=[exige("parcerias.ver")])
async def listar(
    municipio_id: int = Query(..., description="ID do municipio PACTHA"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Propostas do módulo de Gestão de Parcerias, com o ranking por parlamentar."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parcerias")
    mun = (await db.execute(
        select(Municipio).where(Municipio.id == municipio_id))).scalar_one_or_none()
    if not mun:
        raise HTTPException(404, "Município não encontrado")
    dados = await fetch_parcerias(db, municipio_id)
    dados["municipio"] = {"id": mun.id, "nome": mun.nome, "uf": mun.uf}
    return dados
