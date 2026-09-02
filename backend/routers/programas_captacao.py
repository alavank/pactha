"""Radar de captação — os programas federais com prazo ABERTO para propor.

A plataforma acompanha o que o município já tem. Esta é a única tela que olha
para frente: a porta que ainda está aberta e até quando.

⚠️ O RECORTE É POR UF DO MUNICÍPIO, e não por bairrismo. Dos 17 programas
abertos em 02/09/2026, 9 são regionais — "INFRA-ESTRUTURA BÁSICA SR(RS)" só
aceita município gaúcho. Mostrá-lo a um prefeito mineiro seria oferecer uma
porta que não abre, que é o defeito que a tela de Programas do RS já documenta.
Medido: MG vê 9 programas, RS vê 10.

⚠️ E A DATA É CONFERIDA AQUI TAMBÉM, não só na coleta. A tabela é fotografia do
dia em que o coletor rodou; entre uma rodada e outra um prazo vence. Confiar na
coleta deixaria a tela anunciando prazo morto — e prazo morto numa tela de
captação faz o município montar processo para nada.

⚠️ GATE `convenios.ver` + tela `convenios`: é o funil de onde nasce o convênio,
mesma razão da Consulta Popular e dos Programas do RS. Não cria concessão nova.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/programas-captacao", tags=["programas-captacao"])

# O que a PREFEITURA propõe direto. O consórcio é coletado (está no array
# `naturezas`) mas é outra pessoa jurídica: listá-lo junto, sem distinção,
# ofereceria ao prefeito um programa que ele não assina.
NATUREZA_PREFEITURA = "Administração Pública Municipal"


@router.get("", dependencies=[exige("convenios.ver")])
async def radar(
    municipio_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Programas abertos hoje para este município apresentar proposta."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "convenios")

    mun = (await db.execute(text(
        "SELECT nome, uf FROM municipios WHERE id = :m"), {"m": municipio_id})).first()
    if mun is None:
        raise HTTPException(404, "Município não encontrado")
    uf = (mun[1] or "").strip().upper()

    # ⚠️ SEM UF NÃO DÁ PARA RESPONDER, e o honesto é dizer isso. A alternativa
    # seria rodar a consulta assim mesmo: `'' = ANY(ufs)` nunca casa, a tela
    # receberia lista vazia e leria "não há programa aberto" — acusando o
    # TransfereGov de não ter oportunidade por causa de um cadastro nosso
    # incompleto. O `motivo` manda a pessoa para onde se conserta.
    if not uf:
        return {"municipio": {"nome": mun[0], "uf": ""}, "total": 0, "programas": [],
                "atualizado_em": None,
                "motivo": "Este município está sem UF cadastrada, e o recorte dos "
                          "programas é por estado. Cadastre a UF em Configurações "
                          "→ Municípios para o radar funcionar."}

    linhas = (await db.execute(text("""
        SELECT id_programa, nome, orgao, modalidade, dt_ini_receb, dt_fim_receb,
               dt_fim_emenda, acao_orcamentaria, subtipo, cod_programa,
               (dt_fim_receb - CURRENT_DATE)  AS dias,
               (dt_fim_emenda - CURRENT_DATE) AS dias_emenda,
               cardinality(ufs) AS qt_ufs, visto_em
          FROM programas_captacao
         WHERE ausente_desde IS NULL
           AND dt_fim_receb >= CURRENT_DATE
           AND :nat = ANY(naturezas)
           -- ⚠️ SEM `OR cardinality(ufs) = 0` DE PROPÓSITO. A tentação é tratar
           -- array vazio como "vale para todos"; medido no arquivo real, NENHUM
           -- programa municipal vem sem UF (os nacionais listam as 27). Então
           -- esse ramo só seria alcançado por defeito de coleta — e, alcançado,
           -- mostraria o programa a TODO município do país. Numa tela que manda
           -- o gestor abrir processo, o padrão seguro é não mostrar o que não
           -- se sabe a quem se destina.
           AND :uf = ANY(ufs)
         ORDER BY dt_fim_receb, nome
    """), {"uf": uf, "nat": NATUREZA_PREFEITURA})).all()

    # ⚠️ `qt_ufs >= 27` = nacional. O rótulo existe porque "aberto ao Brasil
    # inteiro" e "aberto só ao seu estado" pedem urgências diferentes do gestor:
    # o regional costuma ser o que ninguém mais do município está olhando.
    itens = [{
        "id_programa": r[0], "nome": r[1], "orgao": r[2], "modalidade": r[3],
        "dt_ini_receb": r[4].isoformat() if r[4] else None,
        "dt_fim_receb": r[5].isoformat() if r[5] else None,
        "dt_fim_emenda": r[6].isoformat() if r[6] else None,
        "acao_orcamentaria": r[7], "subtipo": r[8], "cod_programa": r[9],
        "dias": r[10], "dias_emenda": r[11],
        "abrangencia": "nacional" if (r[12] or 0) >= 27 else "regional",
    } for r in linhas]

    atualizado = max((r[13] for r in linhas if r[13]), default=None)
    return {
        "municipio": {"nome": mun[0], "uf": uf},
        "total": len(itens),
        "programas": itens,
        # ⚠️ SEM CARIMBO, A TELA NÃO PODE PROMETER FRESCOR. `None` acontece
        # quando a coleta nunca rodou neste tenant — e a tela precisa dizer isso
        # em vez de mostrar lista vazia, que se leria como "não há programa".
        "atualizado_em": atualizado.isoformat() if atualizado else None,
    }
