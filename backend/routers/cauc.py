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
    "1": "Regularidade fiscal e adimplência com a União",
    "2": "Prestação de contas de recursos federais recebidos",
    "3": "Informações fiscais e contábeis, transparência e Siafic",
    "4": "Competência tributária e regularidade previdenciária",
    "5": "Aplicações mínimas e limites (educação, saúde, Fundeb, PPP, crédito)",
}

# Rotulos das exigencias do extrato do CAUC.
#
# ⚠️ FONTE OBRIGATORIA — nao escreva de cabeca. Estes rotulos sao transcricao do
# PDF oficial "Metadados CAUC Municipios", do MESMO dataset CKAN que a ingestao
# ja baixa (`ingestion/cauc_ingest.py`, dataset `cauc` do Tesouro Transparente):
#   package_show?id=cauc -> resource format=PDF, name="Metadados CAUC Municípios"
# Conferido em 2026-07-30 contra o PDF e, de forma independente, contra o CRC do
# CAGEC-MG, que cita nominalmente os itens 3.1.2, 3.2, 3.3, 3.4, 3.5, 4.1, 5.1 e 5.2.
#
# POR QUE O AVISO: a versao anterior desta tabela tinha a MAIORIA dos rotulos
# trocada — 3.3 aparecia como "Cadastro da Divida Publica" (e CDP e o 3.5), 4.1
# como "Aplicacao minima em Educacao" (e competencia tributaria; educacao e o
# 5.1), 5.2 como "Transparencia LC 131" (e aplicacao minima em saude). A tela
# dizia ao prefeito que faltava uma coisa quando faltava outra. Provavel causa:
# a numeracao do extrato mudou e a tabela ficou para tras. Ao mexer aqui,
# reconfira contra o PDF — nao contra memoria nem contra FAQ de terceiros.
LABELS = {
    "1.1": "Tributos, contribuições previdenciárias federais e Dívida Ativa da União",
    "1.2": "Pagamento de precatórios judiciais",
    "1.3": "Contribuições para o FGTS",
    "1.4": "Adimplência em empréstimos e financiamentos concedidos pela União",
    "1.5": "Regularidade perante o Poder Público Federal",
    "2.1.1": "Prestação de contas de recursos federais — SIAFI/Transferências",
    "2.1.2": "Prestação de contas de recursos federais — Transferegov",
    "3.1.1": "RGF — publicação do Relatório de Gestão Fiscal",
    "3.1.2": "RGF — encaminhamento ao Siconfi",
    "3.2.1": "RREO — publicação do Relatório Resumido de Execução Orçamentária",
    "3.2.2": "RREO — encaminhamento ao Siconfi",
    "3.2.3": "RREO — encaminhamento do Anexo 8 ao Siope",
    "3.2.4": "RREO — encaminhamento do Anexo 12 ao Siops",
    "3.3": "Encaminhamento das contas anuais",
    "3.4.1": "Matriz de Saldos Contábeis — encaminhamento mensal",
    "3.4.2": "Matriz de Saldos Contábeis — encaminhamento de encerramento",
    "3.5": "Cadastro da Dívida Pública (CDP)",
    "3.6": "Transparência da execução orçamentária e financeira em meio eletrônico",
    "3.7": "Adoção de Sistema Integrado de Administração Financeira e Controle (Siafic)",
    "4.1": "Exercício da plena competência tributária",
    "4.2": "Regularidade previdenciária",
    "5.1": "Aplicação mínima de recursos em Educação",
    "5.2": "Aplicação mínima de recursos em Saúde",
    "5.3": "Limite de despesas com Parcerias Público-Privadas (PPP)",
    "5.4": "Limite de operações de crédito, inclusive por antecipação de receita",
    "5.5": "Fundeb — aplicação mínima em profissionais da educação básica",
    "5.6": "Fundeb — complementação da União aplicada em despesas de capital",
    "5.7": "Fundeb — 50% da complementação VAAT na educação infantil",
}


def _classifica(valor: str) -> tuple[str, str]:
    """(tipo, status legivel) a partir do valor bruto do CSV do CAUC.

    Os significados sao os do proprio PDF de metadados, e um deles e traicoeiro:
    **"Desabilitado" NAO quer dizer "nao exigido"**. O texto oficial e "a
    informacao do item nao esta disponivel na data da consulta. Essa situacao e
    valida para TODOS os entes" — ou seja, e indisponibilidade da FONTE, nao
    dispensa do municipio. Dizer "nao exigido" na tela fazia o gestor riscar da
    lista uma exigencia que continua valendo."""
    v = (valor or "").strip()
    if v == "!":
        # Oficial: "nao foi possivel ao CAUC obter a informacao de comprovacao
        # de cumprimento do requisito fiscal". Sem comprovacao, trava — mas o
        # rotulo diz o que de fato aconteceu em vez de acusar o municipio.
        return ("pendente", "Sem comprovação no CAUC")
    if v.lower() == "desabilitado":
        return ("na", "Indisponível na consulta (para todos os entes)")
    if v == "":
        return ("na", "Sem informação")
    return ("regular", f"Regular até {v}")


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
