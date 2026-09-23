"""DOU federal — os atos do Diário Oficial da União que citam o município.

Lê o que `ingestion/dou_federal.py` grava. Diferente dos `dou_*` estaduais
(busca em tempo real, texto livre), aqui é COLETA: toda noite o coletor busca
cada município da carteira e guarda só o ato que o cita com evidência forte.

Duas rotas, cada uma com o gate da tela que a mostra:
- `/atos` — a lista completa, na tela Diário Oficial (`dou.ver`);
- `/alertas` — só os atos de CAPTAÇÃO recentes, no Radar
  (`transferegov_radar.ver`). Quem vê o Radar e não o Diário vê o alerta; a
  lista inteira continua sendo da outra tela.

⚠️ `evidencia = 'cidade'` FICA DE FORA POR PADRÃO. É o nome colado à UF sem
"Município de" antes — em Santa Maria, 20 de 28 atos em 14 dias eram UFSM,
Exército e vara federal. `/atos?incluir_cidade=true` mostra; o Radar, nunca.

⚠️ "NENHUM ATO" SÓ É AFIRMAÇÃO DEPOIS DA COBERTURA. Sem linha em
`dou_cobertura`, o município ainda não teve a busca feita inteira, e a resposta
diz `coletado: false` — a tela não pode ler isso como "não saiu nada no DOU".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from ingestion.dou_federal import ATO, CATEGORIAS_CAPTACAO
from models.user import User
from services.auth import ensure_municipio_access, ensure_tela, get_current_user
from services.registro_rotas import exige

router = APIRouter(prefix="/api/dou-federal", tags=["dou-federal"])

CATEGORIAS = ("emergencia", "selecao", "habilitacao", "repasse", "prazo",
              "convenio", "licitacao", "outros")


def _d(v):
    return v.isoformat() if v else None


# ⚠️ `CAST(:dias AS integer)` em toda janela de data, e não `- :dias`: com o
# parâmetro sem tipo o Postgres resolve `date - $1` como `date - date` (que dá
# INTEIRO) e a comparação quebra com "operator does not exist: date >= integer".
# Pego contra um Postgres de verdade em 22/09/2026; teste de unidade não pega.


async def _cobertura(db: AsyncSession, municipio_id: int):
    existe = (await db.execute(text("SELECT 1 FROM municipios WHERE id = :m"),
                               {"m": municipio_id})).scalar()
    if existe is None:
        raise HTTPException(404, "Município não encontrado")
    return (await db.execute(text(
        "SELECT conferido_ate, atualizado_em FROM dou_cobertura WHERE municipio_id = :m"),
        {"m": municipio_id})).first()


def _item(r) -> dict:
    return {
        "id": r.id,
        "data_publicacao": _d(r.data_publicacao),
        "secao": r.secao,
        "edicao": r.edicao,
        "pagina": r.pagina,
        "tipo_ato": r.tipo_ato,
        "orgao": r.orgao,
        "titulo": r.titulo,
        "ementa": r.ementa,
        "categoria": r.categoria,
        "evidencia": r.evidencia,
        "trecho": r.trecho,
        "url": ATO + r.url_titulo,
    }


_SELECT = """
    SELECT a.id, a.url_titulo, a.secao, a.edicao, a.pagina, a.data_publicacao,
           a.tipo_ato, a.orgao, a.titulo, a.ementa, a.categoria,
           c.evidencia, c.trecho
      FROM dou_atos_municipio c
      JOIN dou_atos a ON a.id = c.ato_id
"""


@router.get("/atos", dependencies=[exige("dou.ver")])
async def atos(
    municipio_id: int = Query(...),
    categoria: str | None = Query(None),
    incluir_cidade: bool = Query(False),
    texto: str | None = Query(None, max_length=120),
    dias: int = Query(90, ge=1, le=730),
    pagina: int = Query(1, ge=1),
    tamanho: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Atos do DOU que citam o município, do mais novo para o mais antigo."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "dou")
    if categoria and categoria not in CATEGORIAS:
        raise HTTPException(400, f"categoria desconhecida: {categoria}")
    cob = await _cobertura(db, municipio_id)

    filtros = ["c.municipio_id = :m",
               "a.data_publicacao >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date - CAST(:dias AS integer)"]
    p: dict = {"m": municipio_id, "dias": dias}
    if not incluir_cidade:
        filtros.append("c.evidencia <> 'cidade'")
    if texto and texto.strip():
        filtros.append("(a.titulo ILIKE :t OR a.ementa ILIKE :t OR a.orgao ILIKE :t "
                       "OR c.trecho ILIKE :t)")
        p["t"] = f"%{texto.strip()}%"
    # A contagem por categoria ignora o filtro de categoria de propósito: é ela
    # que desenha os chips, e um chip não pode sumir por estar selecionado outro.
    onde_base = " AND ".join(filtros)
    contagem = (await db.execute(text(f"""
        SELECT a.categoria, count(*) FROM dou_atos_municipio c
          JOIN dou_atos a ON a.id = c.ato_id WHERE {onde_base} GROUP BY 1
    """), p)).fetchall()
    cidade = (await db.execute(text("""
        SELECT count(*) FROM dou_atos_municipio c JOIN dou_atos a ON a.id = c.ato_id
         WHERE c.municipio_id = :m AND c.evidencia = 'cidade'
           AND a.data_publicacao >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date - CAST(:dias AS integer)
    """), {"m": municipio_id, "dias": dias})).scalar()

    if categoria:
        filtros.append("a.categoria = :cat")
        p["cat"] = categoria
    onde = " AND ".join(filtros)
    total = (await db.execute(text(f"""
        SELECT count(*) FROM dou_atos_municipio c JOIN dou_atos a ON a.id = c.ato_id
         WHERE {onde}"""), p)).scalar()
    linhas = (await db.execute(text(
        _SELECT + f" WHERE {onde} ORDER BY a.data_publicacao DESC, a.id DESC "
                  "LIMIT :lim OFFSET :off"),
        {**p, "lim": tamanho, "off": (pagina - 1) * tamanho})).fetchall()

    return {
        "coletado": cob is not None,
        "conferido_ate": _d(cob[0]) if cob else None,
        "atualizado_em": _d(cob[1]) if cob else None,
        "total": total,
        "pagina": pagina,
        "total_paginas": max(1, -(-total // tamanho)),
        "por_categoria": {r[0]: r[1] for r in contagem},
        "mencoes_cidade": cidade,
        "categorias_captacao": list(CATEGORIAS_CAPTACAO),
        "itens": [_item(r) for r in linhas],
    }


@router.get("/alertas", dependencies=[exige("transferegov_radar.ver")])
async def alertas(
    municipio_id: int = Query(...),
    dias: int = Query(30, ge=1, le=180),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Atos de captação (repasse, habilitação, seleção, emergência) recentes —
    o gatilho que sai no DOU antes de aparecer em qualquer sistema."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "transferegov_radar")
    cob = await _cobertura(db, municipio_id)
    linhas = (await db.execute(text(_SELECT + """
         WHERE c.municipio_id = :m
           AND c.evidencia <> 'cidade'
           AND a.categoria = ANY(:cats)
           AND a.data_publicacao >= (NOW() AT TIME ZONE 'America/Sao_Paulo')::date - CAST(:dias AS integer)
         ORDER BY a.data_publicacao DESC, a.id DESC
         LIMIT 50
    """), {"m": municipio_id, "cats": list(CATEGORIAS_CAPTACAO), "dias": dias})).fetchall()
    return {
        "coletado": cob is not None,
        "conferido_ate": _d(cob[0]) if cob else None,
        "dias": dias,
        "itens": [_item(r) for r in linhas],
    }
