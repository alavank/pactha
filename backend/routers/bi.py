"""Painel de Indicadores - BI — modulo NATIVO (mesmo app/login/banco).

Superficie executiva READ-ONLY com escopo AUTOMATICO por usuario:
  - municipio/consorcio (1 no user_municipios) -> so o proprio;
  - assessoria/parceiro (N) -> seletor + CONSOLIDADO (visao geral da carteira).

Gate: resolve_scope (services/bi.py) — ensure_municipio_access no modo unico,
allowed_municipio_ids no consolidado. Reusa os nucleos de calculo (bi_kpis,
cauc, parlamentares, convenios, status_changes) — para 1 municipio o resultado
bate byte-a-byte com /api/painel/*.

Namespace SEPARADO de /api/painel/* (que segue vivo ate o corte). Montado so
quando BI_MODULE=true (main.py) — flag OFF => 404, zero mudanca de comportamento.
"""
from __future__ import annotations
import os
import json
import hashlib
import secrets
import asyncio
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from services.ia_texto import modelo_texto, params_raciocinio, max_tokens_texto
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from services.audit import registrar
from services.auth import (
    get_current_user, hash_password, create_kiosk_token, ensure_tela, ehQuiosque,
    is_super_admin,
)
from services.bi import (
    resolve_scope, scope_signature, bi_kpis, bi_cauc_rollup, bi_saude_rollup,
    anos_list, anos_signature,
)
from services.bi_abas import (
    bi_estaduais, bi_transferegov, bi_parlamentares_detalhe, bi_documentos, bi_execucao,
    bi_sismob,
    documentos_vencendo,
)
from services.registro_rotas import exige
from models.user import User
from routers.cauc import fetch_cauc_situacao
from routers.parlamentares import aggregate_parlamentares
from routers.convenios import query_alertas_vigencia, query_prestacao_contas
from routers.status_changes import listar_core
from services import authz

router = APIRouter(prefix="/api/bi", tags=["bi"])

# Sentinela de "carteira toda" usada pelo frontend (BiScopeContext). O backend
# guarda o escopo do Modo Tela como texto porque quem o interpreta e a tela;
# aqui ele so precisa ir e voltar sem ser reinterpretado.
CONSOLIDADO = "__all__"


# --------------------------------------------------------------------------
# Gate de TELA do Painel — o que faltava
# --------------------------------------------------------------------------
def _gate_bi(current: User) -> None:
    """Exige a tela `bi` para ler o Painel.

    Ate aqui NENHUM endpoint de /api/bi/* checava tela: o unico gate era o
    escopo de MUNICIPIO (`resolve_scope`). Quem tivesse qualquer municipio lia o
    Painel inteiro — valores captados, ranking de parlamentares, prestacoes de
    contas vencidas, obras da saude, regularidade CAUC/CAGEC — sem ter a
    permissao que existe exatamente para isso. Permissao de municipio responde
    "de QUEM e o dado"; nao responde "esta pessoa pode ver o PAINEL".

    ⚠️⚠️ EM MODO BLOQUEIO ISTO ALCANCA A HOME DO SISTEMA. Com `BI_MODULE`
    ligado, `/dashboard` E o Painel (`frontend/src/app/dashboard/page.tsx`) —
    nao existem mais duas telas para o mesmo publico. E a equivalencia so vale
    numa direcao: `allowedTelasOf` (frontend/src/lib/telas.ts) faz `bi` implicar
    `dashboard`, mas quem tem so `dashboard` NAO ganha `bi`. Entao, na semana de
    observacao, todo usuario que hoje abre a home sem a tela `bi` vira linha
    `authz.negaria` — e isso e o censo que o dono precisa: antes de ligar
    `AUTHZ_MODO=bloqueio` ele tem de conceder `bi` a quem realmente deve abrir o
    Painel, senao a home morre para essa gente na segunda de manha.
    Deliberadamente NAO ha migration concedendo `bi` em massa a quem tem
    `dashboard`: o backfill apagaria justamente o achado que a semana existe
    para produzir.

    ⚠️ QUIOSQUE PASSA SEM TELA, E DE PROPOSITO. A TV do gabinete e o celular do
    gestor entram por um usuario `viewer` SINTETICO (`users.kiosk = true`),
    criado por `_ensure_kiosk_user` — nao por um administrador. Ele ja e barrado
    por uma regra MAIS ESTREITA que a tela: `KIOSK_GET_PERMITIDOS`, em
    `services/auth.py`, e uma allowlist por IGUALDADE de caminho aplicada dentro
    do proprio `get_current_user`; a conta de quiosque so alcanca os poucos GET
    que a TV realmente faz, e mais nada (nem `/narrativa`, que gasta API paga).
    Exigir tela dele nao acrescentaria seguranca nenhuma e criaria dependencia
    fragil: a linha em `user_telas` do quiosque e sintetica, e no dia em que ela
    faltar — conta emitida por outro caminho, limpeza de permissoes, restore
    parcial — o modo bloqueio apaga a TV do gabinete EM SILENCIO, porque o
    slideshow engole o erro no `.catch()` e a tela so para de atualizar.
    """
    if ehQuiosque(current):
        return
    authz.exigir_tela(current, "bi")


# ⚠️ A DECLARACAO DE PERMISSAO E O QUIOSQUE — leia antes de trocar a chave abaixo.
#
# Todo GET de leitura deste arquivo declara `exige("bi.ver")`. Isso SOMA a
# `_gate_bi` (tela) em vez de substitui-lo: a tela responde "esta pessoa tem o
# Painel", a permissao responde "pode LER" — e nenhum gate existente sai daqui.
#
# A conta de quiosque sobrevive, e nao por acidente: ela nao tem linha nenhuma em
# `user_permissoes`, mas `services/permissoes.py::PERMISSOES_QUIOSQUE` a resolve
# como exatamente {"bi.ver"} — o conjunto foi escrito para este dia. Por isso a
# chave declarada aqui tem de continuar sendo `bi.ver`: qualquer outra (`bi.tela`,
# `bi.exportar`) apagaria a TV do gabinete no dia do `AUTHZ_MODO=bloqueio`, EM
# SILENCIO, porque o slideshow engole o erro no `.catch()`. Trocar a chave de um
# endpoint exige trocar aquele frozenset junto.
#
# O que a TV alcanca continua limitado pela regra MAIS ESTREITA, que e anterior a
# esta: `KIOSK_GET_PERMITIDOS` (services/auth.py) so libera os poucos GET listados
# la — `bi.ver` nao abre `/narrativa` para o link publico.


def _periodo(ano: Optional[int], anos: Optional[list[int]]) -> Optional[list[int]]:
    """Periodo efetivo da requisicao. `ano` (legado, 1 valor) e `anos` (mandato
    inteiro) se somam — o frontend novo manda so `anos`."""
    return anos_list((anos or []) + ([ano] if ano else []))


# --------------------------------------------------------------------------
# Cache TTL em memoria do overview (por-worker). Chave = escopo+ano+live.
# Um wallboard polando a cada 30-60s quase nao toca o banco. Stale <= TTL.
# --------------------------------------------------------------------------
_OVERVIEW_TTL = 45  # segundos
_OVERVIEW_CACHE: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str) -> Optional[dict]:
    hit = _OVERVIEW_CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _OVERVIEW_TTL:
        return hit[1]
    return None


def _cache_put(key: str, payload: dict) -> None:
    now = time.monotonic()
    _OVERVIEW_CACHE[key] = (now, payload)
    # poda simples p/ nao crescer sem limite (escopos distintos sao poucos)
    if len(_OVERVIEW_CACHE) > 256:
        for k, (ts, _) in list(_OVERVIEW_CACHE.items()):
            if now - ts >= _OVERVIEW_TTL:
                _OVERVIEW_CACHE.pop(k, None)


# Single-flight: requests concorrentes p/ a MESMA chave fria compartilham UMA
# computacao (colapsa o "stampede" no cold start / virada de TTL).
_INFLIGHT: dict[str, "asyncio.Future"] = {}


async def _semaforo_cagec(db: AsyncSession, ids: list[int]) -> dict:
    """Resumo da regularidade ESTADUAL para o medidor da Visao Geral.

    Conta ENTIDADES, nao municipios: prefeitura, Fundo Municipal de Saude e FMAS
    tem cadastro proprio no CAGEC e cada um trava o seu convenio. Um municipio
    com a prefeitura regular e o fundo de saude irregular NAO esta "em dia"."""
    if not ids:
        return {"tem_dados": False}
    # A COBERTURA DA FONTE vem SEMPRE, mesmo sem dado coletado: e o que permite
    # a Visao Geral (e a TV, que recebe este MESMO payload) distinguir "MG
    # aguardando coleta" de "estado que a fonte nao cobre" — onde escrever
    # "Impedido de receber transferencias" era veredito falso na tela do gestor.
    from services.bi_abas import UF_DA_FONTE
    ufs_escopo = [u or "" for u in (await db.execute(text(
        "SELECT upper(coalesce(uf, '')) FROM municipios WHERE id = ANY(:ids)"
    ), {"ids": ids})).scalars().all()]
    cobertura = {
        "municipios_na_fonte": sum(1 for u in ufs_escopo if u == UF_DA_FONTE),
        "ufs_sem_fonte": sorted({u for u in ufs_escopo if u and u != UF_DA_FONTE}),
    }
    linhas = (await db.execute(text("""
        SELECT municipio_id, COALESCE(principal, false), regular, situacao, nome, tipo,
               itens
        FROM cagec_situacao WHERE municipio_id = ANY(:ids)
        ORDER BY principal DESC, tipo NULLS LAST
    """), {"ids": ids})).fetchall()
    if not linhas:
        return {"tem_dados": False, **cobertura}
    irregulares = [l for l in linhas if l[2] is False]

    # AS OBRIGACOES, e nao so as entidades. O medidor da Visao Geral precisa de
    # uma PROPORCAO; contando entidade, um municipio com um cadastro so tem
    # apenas 0% ou 100% — o arco nunca fica no meio e o painel parece quebrado.
    # As ~24 obrigacoes do CRC dao a medida real de "quanto falta destravar".
    #
    # `itens` vem do CRC (o PDF), nao da consulta publica: quando o Estado
    # recusa emitir, a lista chega vazia. Nesse caso NAO inventamos denominador
    # — devolvemos None e o painel cai no modo sem percentual, que e honesto.
    obrig_total = 0
    obrig_ok = 0
    for l in linhas:
        for it in (l[6] if isinstance(l[6], list) else []):
            if not isinstance(it, dict):
                continue
            # "na" nao existe no CAGEC hoje, mas se passar a existir ele sai da
            # conta pela mesma razao do CAUC: obrigacao desativada nao e meta.
            if it.get("tipo") == "na":
                continue
            obrig_total += 1
            if it.get("tipo") == "regular":
                obrig_ok += 1

    return {
        **cobertura,
        "tem_dados": True,
        "entidades": len(linhas),
        "regulares": sum(1 for l in linhas if l[2] is True),
        "irregulares": len(irregulares),
        "obrigacoes_total": obrig_total or None,
        "obrigacoes_ok": obrig_ok if obrig_total else None,
        "municipios_com_irregularidade": len({l[0] for l in irregulares}),
        # Com uma entidade so, mostra a situacao que o PROPRIO portal escreveu
        # ("Irregular") em vez de um numero sem contexto.
        "situacao": (linhas[0][3] if len(linhas) == 1 else None),
        "quem": [{"nome": l[4], "tipo": l[5], "principal": bool(l[1]),
                  "situacao": l[3]} for l in irregulares][:5],
    }


async def _compute_overview(db: AsyncSession, ids: list[int], cons: bool, single: bool,
                            ano: Optional[list[int]], live: bool) -> dict:
    """Monta o payload do overview SEQUENCIALMENTE na sessao do request. NAO usar
    asyncio.gather com sessoes proprias aqui: abrir N AsyncSession por request
    esgota o pool compartilhado (pool_size+overflow=15) e derruba TODO o app,
    inclusive /auth/login. As queries sao indexadas/set-based e o cache TTL torna
    o miss raro — sequencial e barato e seguro."""
    kpis = await bi_kpis(db, ids, ano)
    semaforo = await fetch_cauc_situacao(db, ids[0]) if single else await bi_cauc_rollup(db, ids)
    # SEMAFORO ESTADUAL. O medidor da Visao Geral so olhava o CAUC e escrevia
    # "Em dia - sem pendencias" para um municipio IRREGULAR no CAGEC. E o sinal
    # mais visivel do painel; dizer "em dia" com convenio estadual travado e o
    # pior erro que ele pode cometer. Regular na Uniao nao e regular em Minas.
    semaforo_cagec = await _semaforo_cagec(db, ids)
    saude = await bi_saude_rollup(db, ids)
    if single:
        ranking = await aggregate_parlamentares(db, municipio_id=ids[0], ano=ano, incluir_plano_acao=live)
    else:
        ranking = await aggregate_parlamentares(db, municipio_ids=ids, ano=ano, incluir_plano_acao=live)
    mudancas = await listar_core(db, ids, 30, 8)
    execucao = await bi_execucao(db, ids, ano)
    return {
        "consolidado": cons,
        "municipios_count": len(ids),
        "municipio_ids": ids,
        "ano": ano[0] if (ano and len(ano) == 1) else None,
        "anos": ano or [],
        "kpis": kpis,
        "execucao": execucao,
        "semaforo": semaforo,
        "semaforo_cagec": semaforo_cagec,
        "saude": saude,
        "top_parlamentares": ranking["items"][:8],
        "ultimas_mudancas": mudancas.get("items", []),
        "ttl": _OVERVIEW_TTL,
    }


# --------------------------------------------------------------------------
# Overview (payload unico do dashboard e da TV) — 1 round-trip
# --------------------------------------------------------------------------

@router.get("/overview", dependencies=[exige("bi.ver")])
async def overview(
    municipio_id: Optional[int] = Query(None, description="1 municipio; ausente = consolidado do escopo"),
    ano: Optional[int] = Query(None, description="Filtra KPIs por ano (None=todos)"),
    anos: Optional[list[int]] = Query(None, description="Varios anos (mandato); soma-se a `ano`"),
    live: bool = Query(False, description="Inclui o RP9 federal AO VIVO (lento; nao usar no polling da TV)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # ANTES do resolve_scope: em modo aviso a ordem e indiferente (nada levanta),
    # mas em bloqueio a primeira negativa e a que vira resposta — e "voce nao tem
    # acesso a esta tela" diz ao gestor o que corrigir, enquanto "voce nao tem
    # municipios no escopo" o manda procurar no lugar errado.
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    single = (not cons) and len(ids) == 1
    ano = _periodo(ano, anos)

    cache_key = f"{scope_signature(ids, cons)}|a={anos_signature(ano)}|l={int(live)}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # single-flight (get/create sem await entre eles = atomico no loop async)
    inflight = _INFLIGHT.get(cache_key)
    if inflight is not None:
        return await inflight
    fut = asyncio.get_event_loop().create_future()
    _INFLIGHT[cache_key] = fut
    try:
        payload = await _compute_overview(db, ids, cons, single, ano, live)
        _cache_put(cache_key, payload)
        if not fut.done():
            fut.set_result(payload)
        return payload
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        _INFLIGHT.pop(cache_key, None)


# --------------------------------------------------------------------------
# Wrappers finos (drilldowns) — usam a sessao do request (sequenciais, sem gather)
# --------------------------------------------------------------------------

@router.get("/semaforo", dependencies=[exige("bi.ver")])
async def semaforo(
    municipio_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    if (not cons) and len(ids) == 1:
        return await fetch_cauc_situacao(db, ids[0])
    return await bi_cauc_rollup(db, ids)


@router.get("/parlamentares", dependencies=[exige("bi.ver")])
async def parlamentares(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    live: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    if (not cons) and len(ids) == 1:
        return await aggregate_parlamentares(db, municipio_id=ids[0], ano=periodo, incluir_plano_acao=live)
    return await aggregate_parlamentares(db, municipio_ids=ids, ano=periodo, incluir_plano_acao=live)


@router.get("/alertas", dependencies=[exige("bi.ver")])
async def alertas(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    if (not cons) and len(ids) == 1:
        vig = await query_alertas_vigencia(db, ids[0], 120, periodo)
        prest = await query_prestacao_contas(db, ids[0], 90, periodo)
    else:
        vig = await query_alertas_vigencia(db, None, 120, periodo, municipio_ids=ids)
        prest = await query_prestacao_contas(db, None, 90, periodo, municipio_ids=ids)
    execucao = await bi_execucao(db, ids, periodo)
    # Documentacao vencendo NAO respeita o filtro de periodo: validade de
    # certidao nao tem nada a ver com o ano do convenio que o gestor esta
    # olhando. Filtrar por periodo aqui esconderia um FGTS vencido so porque a
    # tela esta em 2025.
    docs = await documentos_vencendo(db, ids, 30)
    return {
        "vigencia": [a.model_dump() for a in vig],
        "prestacao": [a.model_dump() for a in prest],
        "execucao": execucao,
        "documentos": docs,
    }


# --------------------------------------------------------------------------
# Abas do painel — 1 request = 1 aba inteira (a TV troca de aba a cada ~15s e
# nao pode disparar uma cascata). Cada uma tem o mesmo cache TTL do overview.
# --------------------------------------------------------------------------

async def _aba_cacheada(key: str, fn):
    """Cache TTL + single-flight compartilhados por todas as abas."""
    cached = _cache_get(key)
    if cached is not None:
        return cached
    inflight = _INFLIGHT.get(key)
    if inflight is not None:
        return await inflight
    fut = asyncio.get_event_loop().create_future()
    _INFLIGHT[key] = fut
    try:
        payload = await fn()
        _cache_put(key, payload)
        if not fut.done():
            fut.set_result(payload)
        return payload
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        _INFLIGHT.pop(key, None)


@router.get("/estaduais", dependencies=[exige("bi.ver")])
async def aba_estaduais(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Verbas Estaduais': convenios SIGCON-MG + emendas estaduais."""
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    key = f"est|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    return await _aba_cacheada(key, lambda: bi_estaduais(db, ids, periodo))


@router.get("/transferegov", dependencies=[exige("bi.ver")])
async def aba_transferegov(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'TransfereGov': voluntarias + Novo PAC + o que esta em execucao."""
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    key = f"tg|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    return await _aba_cacheada(key, lambda: bi_transferegov(db, ids, periodo))


@router.get("/parlamentares/detalhe", dependencies=[exige("bi.ver")])
async def aba_parlamentares_detalhe(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Parlamentares': cada parlamentar com as emendas que mandou —
    destinacao (pra quem) e finalidade (pra que), que e o detalhe que o
    prefeito cobra na tela."""
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)
    key = f"parld|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    return await _aba_cacheada(key, lambda: bi_parlamentares_detalhe(db, ids, periodo))


@router.get("/sismob", dependencies=[exige("bi.ver")])
async def aba_sismob(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Obras da saude (SISMOB) da aba do Painel.

    `ano`/`anos` continuam aceitos porque o Painel os envia em toda aba, mas a
    resposta NAO depende deles: obra em aberto e obrigacao do presente, e o ano
    da proposta nao diz em que ano o problema existe (ver bi_sismob). Por isso a
    chave de cache tambem nao leva `a=` — se levasse, cada periodo clicado
    criaria uma entrada nova com resultado identico.
    """
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    key = f"sismob|{scope_signature(ids, cons)}"
    return await _aba_cacheada(key, lambda: bi_sismob(db, ids, None))


@router.get("/documentos", dependencies=[exige("bi.ver")])
async def aba_documentos(
    municipio_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Documentacao': CAUC (federal, coletado) e CAGEC (estadual, ainda
    nao integrado — devolve disponivel=false em vez de fingir que esta em dia)."""
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    key = f"doc|{scope_signature(ids, cons)}"
    return await _aba_cacheada(key, lambda: bi_documentos(db, ids))


# --------------------------------------------------------------------------
# Aba FNS — consulta AO VIVO no portal do Fundo Nacional de Saude, ja resolvida
# no backend p/ VARIOS anos. Cache proprio (TTL maior): o portal e lento e a
# TV volta nesta aba a cada rodada do slideshow.
# --------------------------------------------------------------------------

_FNS_TTL = 900  # 15 min
_FNS_CACHE: dict[str, tuple[float, dict]] = {}


def _ano_corrente() -> int:
    from datetime import date as _date
    return _date.today().year


@router.get("/fns", dependencies=[exige("bi.ver")])
async def aba_fns(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Aba 'Fundo Nacional de Saude'. SEM filtro de ano, abre no ano corrente
    ja consultado (o gestor nao deveria ter que clicar em 'consultar' para ver
    o ano em que esta). Aceita varios anos."""
    # Esta aba consulta o portal do FNS AO VIVO, um municipio-ano por vez: sem
    # gate, quem nao tem o Painel dispara trabalho externo pesado em nome do
    # cliente.
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos) or [_ano_corrente()]

    key = f"fns|{scope_signature(ids, cons)}|a={anos_signature(periodo)}"
    hit = _FNS_CACHE.get(key)
    if hit and (time.monotonic() - hit[0]) < _FNS_TTL:
        return hit[1]

    from routers.fns import consultar_fns

    muns = (await db.execute(text(
        "SELECT id, nome, uf FROM municipios WHERE id = ANY(:ids) ORDER BY nome"
    ), {"ids": ids})).fetchall()

    por_ano: dict[int, dict] = {a: {"ano": a, "total": 0, "valor_proposta": 0.0,
                                    "valor_pago": 0.0, "valor_pagar": 0.0} for a in periodo}
    itens: list[dict] = []
    erros: list[str] = []
    for m in muns:
        if not m.uf:
            # Era `m.uf or "MG"`: municipio sem UF era consultado como se fosse
            # mineiro e o vazio parecia resposta. Sem UF nao ha consulta certa.
            erros.append(f"{m.nome}: sem UF no cadastro — consulta FNS nao feita")
            continue
        for a in periodo:
            try:
                res = await consultar_fns(db, m.nome, a, m.uf, tamanho=200)
            except Exception as e:
                erros.append(f"{m.nome}/{a}: {str(getattr(e, 'detail', e))[:120]}")
                continue
            agg = por_ano[a]
            t = res.get("totais") or {}
            agg["total"] += res.get("total") or 0
            agg["valor_proposta"] += float(t.get("valor_proposta") or 0)
            agg["valor_pago"] += float(t.get("valor_pago") or 0)
            agg["valor_pagar"] += float(t.get("valor_pagar") or 0)
            for it in res.get("items") or []:
                itens.append({**it, "ano": a, "municipio": m.nome})

    itens.sort(key=lambda i: -(i.get("valor_proposta") or 0))
    payload = {
        "anos": periodo,
        "por_ano": [por_ano[a] for a in periodo],
        "itens": itens[:80],
        "total": len(itens),
        "totais": {
            "valor_proposta": sum(v["valor_proposta"] for v in por_ano.values()),
            "valor_pago": sum(v["valor_pago"] for v in por_ano.values()),
            "valor_pagar": sum(v["valor_pagar"] for v in por_ano.values()),
        },
        "disponivel": bool(itens) or not erros,
        "erros": erros[:5],
        "ttl": _FNS_TTL,
    }
    _FNS_CACHE[key] = (time.monotonic(), payload)
    if len(_FNS_CACHE) > 64:
        now = time.monotonic()
        for k, (ts, _) in list(_FNS_CACHE.items()):
            if now - ts >= _FNS_TTL:
                _FNS_CACHE.pop(k, None)
    return payload


@router.get("/timeline", dependencies=[exige("bi.ver")])
async def timeline(
    municipio_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    _gate_bi(current)
    ids, _cons = await resolve_scope(db, current, municipio_id)
    return await listar_core(db, ids, days, limit)


# --------------------------------------------------------------------------
# Narrativa (IA/Haiku) com cache por input_hash — self-contained (nao depende
# de painel.py, que sera removido no corte). Degrada sem ANTHROPIC_API_KEY.
# --------------------------------------------------------------------------

def _money_br(v) -> str:
    v = float(v or 0)
    if abs(v) >= 1_000_000:
        return ("R$ %.1f mi" % (v / 1_000_000)).replace(".", ",")
    if abs(v) >= 1_000:
        return "R$ %.0f mil" % (v / 1_000)
    return "R$ %.0f" % v


async def _gerar_narrativa(dados: dict, kind: str, api_key: str) -> str:
    """Uma chamada Haiku (sem tools/thinking) que traduz os numeros em 2-4 frases
    de linguagem leiga para o gestor. NAO reusa o tool-loop pesado do ai.py."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    total = (dados["estadual"] or 0) + (dados["federal"] or 0)
    top_txt = "; ".join(f'{t["n"]} ({_money_br(t["v"])})' for t in dados["top"]) or "sem registro"
    ano_txt = str(dados["ano"]) if dados["ano"] else "todos os anos"
    cauc_txt = "em dia, sem pendencias" if dados["cauc_regular"] else f'{dados["cauc_pend"]} pendencia(s)'
    system = (
        "Voce explica dados de captacao de recursos publicos para um GESTOR leigo, em "
        "portugues do Brasil. Linguagem simples e direta, tom institucional, positivo mas "
        "honesto. Sem jargao tecnico. Responda em 2 a 4 frases curtas. Nao invente numeros "
        "alem dos fornecidos."
    )
    prompt = (
        f"Carteira: {dados['municipio']}. Periodo: {ano_txt}.\n"
        f"Total captado: {_money_br(total)} (estadual {_money_br(dados['estadual'])}, "
        f"federal {_money_br(dados['federal'])}).\n"
        f"{dados['voluntarias']} propostas federais; {dados['convenios_est']} convenios estaduais.\n"
        f"CAUC (documentacao federal): {cauc_txt}.\n"
        f"Prestacoes de contas vencidas: {dados['prestacao']}. Convenios vencendo: {dados['vigencia']}.\n"
        f"Parlamentares que mais destinaram recurso: {top_txt}.\n\n"
        "Escreva um resumo executivo destacando o impacto (quanto entrou, quem ajudou) e os "
        "pontos de atencao (documentacao, prazos). Escreva em portugues do Brasil com "
        "ACENTUACAO CORRETA — o texto vai direto para a tela do gestor."
    )
    resp = await client.messages.create(
        model=modelo_texto(),
        max_tokens=max_tokens_texto(),
        # Sonnet 5 liga raciocinio adaptativo quando `thinking` e OMITIDO (o
        # Haiku nao ligava). Numa frase curta de painel isso so somaria latencia
        # e tokens, entao desligamos de proposito e usamos effort baixo: aqui o
        # modelo apenas REDIGE — os numeros ja vem calculados do backend.
        # Haiku 4.5 NAO aceita `effort` nem `thinking` (400 "does not support the
        # effort parameter"). Como o modelo e trocavel por env, os parametros so
        # vao quando o modelo os suporta — senao trocar para Haiku (mais barato)
        # derrubaria a faixa do dashboard.
        **params_raciocinio(),
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("refusal")
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


@router.get("/narrativa", dependencies=[exige("bi.ver")])
async def narrativa(
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    kind: str = Query("resumo"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Resumo executivo em linguagem leiga (IA/Haiku) com cache por input_hash.
    Sem ANTHROPIC_API_KEY -> disponivel=false e o frontend usa texto por template."""
    # Chama a Anthropic quando o cache erra: sem gate, quem nao tem o Painel
    # gasta a conta paga do cliente (e por isso `/narrativa` tambem ficou FORA
    # da allowlist de quiosque).
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    single = (not cons) and len(ids) == 1
    periodo = _periodo(ano, anos)
    ano = periodo[0] if (periodo and len(periodo) == 1) else None

    kpis = await bi_kpis(db, ids, periodo)
    cauc = await bi_cauc_rollup(db, ids)
    if single:
        ranking = await aggregate_parlamentares(db, municipio_id=ids[0], ano=periodo, incluir_plano_acao=False)
        mrow = (await db.execute(text("SELECT nome FROM municipios WHERE id = :m"), {"m": ids[0]})).first()
        nome = mrow[0] if mrow else f"Municipio {ids[0]}"
        cauc_regular = cauc["por_municipio"][0]["regular"] if cauc["por_municipio"] else None
        mid_key = ids[0]
    else:
        ranking = await aggregate_parlamentares(db, municipio_ids=ids, ano=periodo, incluir_plano_acao=False)
        nome = f"{len(ids)} municipios da carteira"
        cauc_regular = (cauc["com_dados"] > 0 and cauc["com_pendencia"] == 0)
        mid_key = 0
    cauc_pend = cauc["pendencias_total"]

    top = [
        {"n": t["nome_display"], "v": t["valor_total"]}
        for t in ranking["items"]
        if "MUNICIPIO" not in (t.get("nome_normalizado") or "") and "PREFEITURA" not in (t.get("nome_normalizado") or "")
    ][:3]
    dados = {
        "municipio": nome,
        "ano": ano,
        "anos": periodo or [],
        "estadual": kpis["valor_total_estadual"],
        "federal": kpis["valor_total_federal"],
        "voluntarias": kpis["total_voluntarias"],
        "convenios_est": kpis["total_convenios_estadual"],
        "prestacao": kpis["alertas_prestacao_contas"],
        "vigencia": kpis["alertas_vigencia"],
        "cauc_regular": cauc_regular,
        "cauc_pend": cauc_pend,
        "top": top,
    }
    input_hash = hashlib.sha256(
        json.dumps(dados, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    ano_key = ano or 0
    # single: compartilha o cache com o painel (mesmos numeros -> mesmo input_hash).
    # consolidado: mid_key=0 seria UMA linha p/ TODAS as carteiras (admin + cada
    # assessoria) -> thrash. Isola por assinatura do escopo na chave `kind`.
    #
    # MULTI-ANO: a coluna `ano` da tabela so guarda 1 valor, entao um periodo de
    # varios anos vai com ano_key=0 e o periodo entra no `kind` — senao 2021-2024
    # e 2022-2025 dividiriam a MESMA linha e ficariam se sobrescrevendo.
    periodo_key = "" if (not periodo or len(periodo) == 1) else f":p{anos_signature(periodo)}"
    if single:
        kind_key = f"{kind}{periodo_key}"
    else:
        sig = hashlib.sha256(scope_signature(ids, cons).encode("utf-8")).hexdigest()[:16]
        kind_key = f"bi:{sig}:{kind}{periodo_key}"

    row = (await db.execute(text(
        "SELECT texto, input_hash, gerado_em FROM painel_narrativa_cache "
        "WHERE municipio_id = :m AND ano = :a AND kind = :k"
    ), {"m": mid_key, "a": ano_key, "k": kind_key})).first()
    if row and row[1] == input_hash and row[0]:
        return {"texto": row[0], "kind": kind, "cache": True, "disponivel": True,
                "gerado_em": row[2].isoformat() if row[2] else None}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"texto": None, "kind": kind, "cache": False, "disponivel": False}
    try:
        texto = await _gerar_narrativa(dados, kind, api_key)
    except Exception as e:
        return {"texto": None, "kind": kind, "cache": False, "disponivel": False, "erro": str(e)[:80]}

    await db.execute(text(
        "INSERT INTO painel_narrativa_cache (municipio_id, ano, kind, texto, input_hash, gerado_em) "
        "VALUES (:m, :a, :k, :t, :h, NOW()) "
        "ON CONFLICT (municipio_id, ano, kind) DO UPDATE SET texto = :t, input_hash = :h, gerado_em = NOW()"
    ), {"m": mid_key, "a": ano_key, "k": kind_key, "t": texto, "h": input_hash})
    await db.commit()
    return {"texto": texto, "kind": kind, "cache": False, "disponivel": True}


# --------------------------------------------------------------------------
# Insights por ABA (IA) — LISTA de mensagens curtas p/ o cabecalho do Modo Tela
# rodar em slideshow. Uma aba costuma ter mais de uma coisa importante pra dizer.
# Sem ANTHROPIC_API_KEY cai num texto por template (a faixa nunca fica vazia).
# --------------------------------------------------------------------------

ABAS_INSIGHT = ("geral", "parlamentares", "transferegov", "estaduais",
                "documentos", "fns", "sismob")


async def _fatos_da_aba(db: AsyncSession, ids: list[int], cons: bool, aba: str,
                        periodo: Optional[list[int]]) -> tuple[dict, list[str]]:
    """(fatos p/ a IA, mensagens de fallback por template). Os fatos sao poucos
    e ja resumidos — a IA nao recebe a base inteira."""
    periodo_txt = ", ".join(str(a) for a in periodo) if periodo else "todos os anos"
    if aba == "parlamentares":
        d = await bi_parlamentares_detalhe(db, ids, periodo)
        top = d["itens"][:3]
        fatos = {
            "aba": "parlamentares", "periodo": periodo_txt,
            "total_parlamentares": d["total"], "valor_total": d["valor_total"],
            "top": [{"nome": t["nome"], "valor": t["valor_total"],
                     "emendas": t["total_lancamentos"]} for t in top],
        }
        tpl = [f"{d['total']} parlamentares destinaram {_money_br(d['valor_total'])} ao município em {periodo_txt}."]
        if top:
            tpl.append(f"Maior destinação: {top[0]['nome']} — {_money_br(top[0]['valor_total'])} "
                       f"em {top[0]['total_lancamentos']} lançamento(s).")
        return fatos, tpl

    if aba == "transferegov":
        d = await bi_transferegov(db, ids, periodo)
        v = d["voluntarias"]
        fatos = {"aba": "transferegov", "periodo": periodo_txt,
                 "propostas": v["total"], "valor": v["valor_total"],
                 "em_execucao": v.get("em_execucao", 0),
                 "situacoes": v["por_situacao"][:4], "pac": d["pac"]["total"]}
        tpl = [f"{v['total']} propostas federais somando {_money_br(v['valor_total'])} ({periodo_txt})."]
        if v.get("em_execucao"):
            tpl.append(f"{v['em_execucao']} instrumento(s) em execução neste momento.")
        return fatos, tpl

    if aba == "estaduais":
        d = await bi_estaduais(db, ids, periodo)
        c, e = d["convenios"], d["emendas"]
        fatos = {"aba": "estaduais", "periodo": periodo_txt,
                 "convenios": c["total"], "valor_convenios": c["valor_total"],
                 "repassado": c.get("valor_repassado", 0),
                 "emendas": e["total"], "valor_emendas": e["valor_total"],
                 "orgaos": c["por_orgao"][:3]}
        tpl = [f"{c['total']} convênios estaduais somando {_money_br(c['valor_total'])} ({periodo_txt})."]
        if e["total"]:
            tpl.append(f"{e['total']} indicações de emenda estadual, {_money_br(e['valor_total'])}.")
        return fatos, tpl

    if aba == "documentos":
        # AS DUAS ESFERAS NOS FATOS. Com só o CAUC aqui, a faixa da aba dizia
        # "Nenhuma pendência de documentos registrada" para um município
        # IRREGULAR no CAGEC — ou seja, tranquilizava o gestor sobre um convênio
        # estadual travado. Fato faltando não gera silêncio, gera afirmação falsa.
        d = await bi_documentos(db, ids)
        c, g = d["cauc"], d.get("cagec") or {}
        g_muns = g.get("por_municipio") or []
        g_irregulares = [m for m in g_muns if m.get("regular") is False]
        g_pend_total = sum(m.get("pendencias") or 0 for m in g_muns)
        fatos = {
            "aba": "documentos",
            "cauc": {
                "regulares": c["regulares"], "municipios": c["total_municipios"],
                "pendencias": c["pendencias_total"],
                "pendentes": [{"nome": m["nome"],
                               "itens": [i["label"] for i in m["itens_pendentes"][:3]]}
                              for m in c["por_municipio"] if m["pendencias"]][:3],
            },
            "cagec": {
                "coletado": bool(g_muns),
                "irregulares": len(g_irregulares),
                "pendencias": g_pend_total,
                "pendentes": [{"nome": m.get("nome"),
                               "situacao": m.get("situacao"),
                               "itens": [f"{i['label']} (venceu em {i['valor']})"
                                         if i.get("valor") else i["label"]
                                         for i in (m.get("itens") or [])
                                         if i.get("tipo") == "pendente"][:3]}
                              for m in g_irregulares][:3],
            },
        }
        if c["pendencias_total"]:
            tpl = [f"{c['pendencias_total']} pendência(s) no CAUC bloqueiam novas transferências voluntárias."]
        else:
            tpl = ["Documentação federal (CAUC) em dia — município apto a receber transferências voluntárias."]
        if not g_muns:
            tpl.append("CAGEC (regularidade estadual de MG) ainda não coletado para este escopo.")
        elif g_irregulares:
            # A consequência é diferente da do CAUC e precisa ser dita: no CAGEC
            # a irregularidade trava também o PAGAMENTO de convênio já assinado.
            tpl.append(f"{len(g_irregulares)} município(s) IRREGULAR(es) no CAGEC "
                       f"({g_pend_total} pendência(s)) — impede assinar convênio estadual "
                       f"e a liberação de parcela de convênio em execução.")
        else:
            tpl.append("CAGEC (regularidade estadual de MG) em dia.")
        return fatos, tpl

    if aba == "sismob":
        # Fatos das obras. Sem este ramo, /bi/insights?aba=sismob devolveria 400
        # e a aba ficaria sendo a unica sem faixa de IA — em silencio, porque o
        # ticker engole o erro no .catch().
        # `periodo` NAO entra: a aba e de estado atual (ver bi_sismob). Quando
        # entrava, com "Mandato atual" selecionado a faixa afirmava "2 obras da
        # saude em andamento, sem paralisacao registrada" enquanto 3 obras
        # precisavam de acao — a IA repetindo, com a autoridade dela, o erro do
        # filtro.
        d = await bi_sismob(db, ids, None)
        t = d["totais"]
        fatos = {
            "aba": "sismob", "obras": t.get("obras", 0), "vivas": t.get("vivas", 0),
            "concluidas": t.get("concluidas", 0), "canceladas": t.get("canceladas", 0),
            "valor_proposta": t.get("valor_proposta", 0),
            "repassado": t.get("repasse_total", 0),
            "repasse_parado": t.get("repasse_parado", 0),
            "com_prazo_vencido": t.get("com_prazo_vencido", 0),
            "precisam_acao": [{"obra": i.get("estabelecimento"), "municipio": i.get("municipio"),
                               "problema": i.get("problema"), "percentual": i.get("percentual")}
                              for i in d.get("acao", [])[:3]],
        }
        if t.get("repasse_parado"):
            tpl = [f"{_money_br(t['repasse_parado'])} repassados em obras da saúde sem "
                   f"atualização há mais de 60 dias — a norma exige atualização a cada 60 dias."]
        elif t.get("obras"):
            tpl = [f"{t.get('vivas', 0)} obra(s) da saúde em andamento, sem paralisação registrada."]
        else:
            tpl = ["Nenhuma obra do SISMOB registrada para este escopo."]
        if t.get("com_prazo_vencido"):
            tpl.append(f"{t['com_prazo_vencido']} obra(s) com a etapa de início de execução "
                       f"vencida (prazo de 90 dias após o repasse).")
        return fatos, tpl

    if aba == "fns":
        # Antes isto devolvia SO {aba, periodo} — sem nenhum numero. Sem fato, a
        # IA escrevia "nenhum repasse registrado" na tela do gestor, o que e
        # FALSO: Monte Siao tem 48 propostas FNS somando R$ 26,3 mi. Os fatos
        # agora vem do BANCO (mesma fonte que a IA do chat usa) e nao da API ao
        # vivo do painel — faixa de dashboard nao pode depender de servico externo.
        _w = ["municipio_id = ANY(:ids)", "fonte ILIKE '%FNS%'"]
        _p: dict = {"ids": ids}
        if periodo:
            _w.append("ano = ANY(:anos)")
            _p["anos"] = periodo
        _linhas = (await db.execute(text(
            "SELECT situacao, count(*), COALESCE(SUM(valor_total), 0) "
            "FROM convenios_estadual WHERE " + " AND ".join(_w) +
            " GROUP BY situacao ORDER BY 2 DESC"), _p)).fetchall()
        _total = sum(int(r[1]) for r in _linhas)
        _valor = float(sum(float(r[2] or 0) for r in _linhas))
        fatos = {
            "aba": "fns", "periodo": periodo_txt,
            "propostas": _total, "valor_total": _valor,
            "situacoes": [{"label": r[0] or "sem situação", "qtd": int(r[1]),
                           "valor": float(r[2] or 0)} for r in _linhas],
        }
        tpl = [f"FNS: {_total} proposta(s) de saúde somando {_money_br(_valor)}."
               if _total else f"FNS: nenhuma proposta registrada em {periodo_txt}."]
        return fatos, tpl

    # geral
    kpis = await bi_kpis(db, ids, periodo)
    cauc = await bi_cauc_rollup(db, ids)
    exe = await bi_execucao(db, ids, periodo)
    fatos = {
        "aba": "geral", "periodo": periodo_txt,
        "estadual": kpis["valor_total_estadual"], "federal": kpis["valor_total_federal"],
        "vigencia_120d": kpis["alertas_vigencia"], "vigencia_60d": kpis["alertas_vigencia_60d"],
        "prestacao_vencida": kpis["alertas_prestacao_contas"],
        "cauc_pendencias": cauc["pendencias_total"],
        "em_execucao": exe["total"], "valor_em_execucao": exe["valor_total"],
    }
    total = (kpis["valor_total_estadual"] or 0) + (kpis["valor_total_federal"] or 0)
    tpl = [f"Total captado no período ({periodo_txt}): {_money_br(total)}."]
    if kpis["alertas_vigencia_60d"]:
        tpl.append(f"{kpis['alertas_vigencia_60d']} convênio(s) vencem nos próximos 60 dias.")
    if kpis["alertas_prestacao_contas"]:
        tpl.append(f"{kpis['alertas_prestacao_contas']} prestação(ões) de contas em atraso.")
    return fatos, tpl


async def _gerar_insights(fatos: dict, api_key: str) -> list[str]:
    """2 a 4 frases INDEPENDENTES (uma por item) — o cabecalho da TV mostra uma
    de cada vez. Cada frase precisa fazer sentido sozinha."""
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    system = (
        "Voce escreve avisos curtos para um PAINEL DE TV lido por um prefeito. "
        "Portugues do Brasil, linguagem simples, tom institucional e direto. "
        "Cada aviso e uma frase UNICA de no maximo 140 caracteres, faz sentido "
        "sozinho (a TV mostra um de cada vez) e traz um numero ou um nome concreto. "
        "Priorize o que exige acao (prazo, pendencia) antes do que e so resultado. "
        "Escreva em portugues do Brasil com ACENTUACAO CORRETA (atencao->atenção, "
        "convenio->convênio, prestacoes->prestações). O texto vai direto para a tela. "
        "Nao invente numeros. Nao invente ROTULOS: use apenas as descricoes que "
        "aparecem nos dados e nunca atribua um valor a uma area, tema, programa, "
        "orgao ou pessoa que nao esteja explicito ali (ex.: nao escreva 'para "
        "educacao' ou 'para saude' se o dado nao disser a que se refere; nesse "
        "caso diga apenas 'em repasses federais'). "
        "Responda APENAS um array JSON de 2 a 4 strings."
    )
    resp = await client.messages.create(
        model=modelo_texto(),
        max_tokens=max_tokens_texto(),
        # Sonnet 5 liga raciocinio adaptativo quando `thinking` e OMITIDO (o
        # Haiku nao ligava). Numa frase curta de painel isso so somaria latencia
        # e tokens, entao desligamos de proposito e usamos effort baixo: aqui o
        # modelo apenas REDIGE — os numeros ja vem calculados do backend.
        # Haiku 4.5 NAO aceita `effort` nem `thinking` (400 "does not support the
        # effort parameter"). Como o modelo e trocavel por env, os parametros so
        # vao quando o modelo os suporta — senao trocar para Haiku (mais barato)
        # derrubaria a faixa do dashboard.
        **params_raciocinio(),
        system=system,
        messages=[{"role": "user", "content": json.dumps(fatos, ensure_ascii=False)}],
    )
    if getattr(resp, "stop_reason", None) == "refusal":
        raise RuntimeError("refusal")
    txt = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
    ini, fim = txt.find("["), txt.rfind("]")
    if ini >= 0 and fim > ini:
        msgs = json.loads(txt[ini:fim + 1])
    else:  # modelo respondeu em linhas soltas
        msgs = [ln.strip(" -•\t") for ln in txt.splitlines() if len(ln.strip()) > 15]
    return [str(m).strip() for m in msgs if str(m).strip()][:4]


@router.get("/insights", dependencies=[exige("bi.ver")])
async def insights(
    aba: str = Query("geral"),
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None),
    anos: Optional[list[int]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Mensagens curtas da IA sobre a aba aberta (slideshow do cabecalho)."""
    if aba not in ABAS_INSIGHT:
        raise HTTPException(status_code=400, detail=f"aba inválida: {aba}")
    # Depois do 400 de proposito: `aba` invalida e pedido malformado, nao
    # permissao que falta, e a lista de abas ja e publica no frontend — trocar a
    # ordem mudaria a resposta de hoje sem esconder nada de ninguem.
    _gate_bi(current)
    ids, cons = await resolve_scope(db, current, municipio_id)
    periodo = _periodo(ano, anos)

    fatos, template = await _fatos_da_aba(db, ids, cons, aba, periodo)
    input_hash = hashlib.sha256(
        json.dumps(fatos, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()

    # A PK da tabela guarda 1 `ano`; um periodo com varios anos entra no `kind`
    # (senao 2021-2024 e 2022-2025 brigariam pela mesma linha).
    sig = hashlib.sha256(scope_signature(ids, cons).encode("utf-8")).hexdigest()[:16]
    periodo_key = "" if (not periodo or len(periodo) == 1) else f":p{anos_signature(periodo)}"
    kind_key = f"bi:ins:{sig}:{aba}{periodo_key}"
    mid_key = ids[0] if ((not cons) and len(ids) == 1) else 0
    ano_key = (periodo[0] if periodo and len(periodo) == 1 else 0)

    row = (await db.execute(text(
        "SELECT texto, input_hash FROM painel_narrativa_cache "
        "WHERE municipio_id = :m AND ano = :a AND kind = :k"
    ), {"m": mid_key, "a": ano_key, "k": kind_key})).first()
    if row and row[1] == input_hash and row[0]:
        try:
            return {"aba": aba, "mensagens": json.loads(row[0]), "cache": True, "disponivel": True}
        except (ValueError, TypeError):
            pass

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"aba": aba, "mensagens": template, "cache": False, "disponivel": False, "fonte": "template"}
    try:
        msgs = await _gerar_insights(fatos, api_key)
    except Exception as e:
        return {"aba": aba, "mensagens": template, "cache": False, "disponivel": False,
                "fonte": "template", "erro": str(e)[:80]}
    if not msgs:
        return {"aba": aba, "mensagens": template, "cache": False, "disponivel": False, "fonte": "template"}

    await db.execute(text(
        "INSERT INTO painel_narrativa_cache (municipio_id, ano, kind, texto, input_hash, gerado_em) "
        "VALUES (:m, :a, :k, :t, :h, NOW()) "
        "ON CONFLICT (municipio_id, ano, kind) DO UPDATE SET texto = :t, input_hash = :h, gerado_em = NOW()"
    ), {"m": mid_key, "a": ano_key, "k": kind_key,
        "t": json.dumps(msgs, ensure_ascii=False), "h": input_hash})
    await db.commit()
    return {"aba": aba, "mensagens": msgs, "cache": False, "disponivel": True, "fonte": "ia"}


# --------------------------------------------------------------------------
# MODO TELA — filtro POR USUARIO e link publico curto.
#
# Regra do produto: cada gestor e um ambiente. O que o secretario de Saude
# filtra vale para a TV DELE e para o link publico DELE; ninguem altera o que o
# outro ve. Por isso o filtro e chaveado por `user_id` e o link guarda o dono.
#
# O link publico nao leva mais o JWT na URL. Antes iam ~300 chars impossiveis de
# ditar, e revogar exigia desativar o usuario de quiosque — que era
# COMPARTILHADO entre todo mundo, entao derrubava a TV dos outros junto. Agora a
# URL leva um slug de 12 chars, o token mora no banco e cada link morre sozinho.
# --------------------------------------------------------------------------

class FiltroTelaIn(BaseModel):
    scope: str = CONSOLIDADO
    anos: list[int] = []
    aba: Optional[str] = None


class TelaLinkIn(BaseModel):
    # PARA QUEM o link foi gerado. E o que torna a revogacao possivel: sem nome,
    # a lista vira um punhado de slugs de 12 caracteres e ninguem lembra qual
    # entregar de volta quando a pessoa sai, ou qual matar quando o prazo passa.
    nome: Optional[str] = None
    # 'tela' = TV de parede (segue o filtro do dono em tempo real)
    # 'mobile' = app de celular (filtro PROPRIO no aparelho)
    kind: str = "tela"
    # ESCOPO em que o link foi gerado. Município concreto -> o link FIXA nele
    # (cada um dos 50 links da assessoria mostra a sua cidade, e a prévia do
    # WhatsApp cita a certa). CONSOLIDADO/vazio -> segue o dono, como antes.
    escopo: Optional[str] = None
    # COMO expira: "dias" (a partir de hoje), "data" (dia marcado) ou "nunca".
    expira: str = "dias"
    dias: int = 365
    # Dia em que o acesso morre, quando `expira == "data"`. Vale ate o FIM
    # daquele dia — quem escolhe "10 de agosto" quer o dia 10 inteiro.
    data_expiracao: Optional[date] = None


# Teto do proprio JWT de quiosque. "Nao expira" e uma decisao de OPERACAO (o
# dono nao quer prazo), nao uma promessa de eternidade: o token embutido no link
# e assinado com validade, e assinar por tempo infinito seria pior. Dez anos e
# mais que o mandato que este produto atende.
_DIAS_MAX_LINK = 3650


def _prazo_do_link(body: TelaLinkIn) -> tuple[Optional[datetime], int]:
    """(quando o link morre, quantos dias o token vale).

    `expira_em = None` e o que o resolvedor publico ja entende como "sem prazo"
    (`tela-pub` so compara a data quando ela existe). O TTL do token continua
    limitado ao teto — se um dia alguem precisar de mais, renova o link, que e
    justamente a hora de reconferir se aquela pessoa ainda deve ter acesso."""
    modo = (body.expira or "dias").lower()
    if modo == "nunca":
        return None, _DIAS_MAX_LINK
    if modo == "data":
        if not body.data_expiracao:
            raise HTTPException(status_code=400, detail="Informe a data de expiração")
        # Fim do dia escolhido, em UTC. Sem isto, "expira em 10/08" mataria o
        # link a meia-noite do dia 9 para quem esta em Brasilia.
        fim = datetime.combine(body.data_expiracao, dt_time.max, tzinfo=timezone.utc)
        if fim <= datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="A data de expiração já passou")
        dias = max(1, min((fim - datetime.now(timezone.utc)).days + 1, _DIAS_MAX_LINK))
        return fim, dias
    # `int(body.dias or 365)` seria o idioma natural aqui — e estava errado:
    # com `dias = 0` (campo zerado na tela), `0 or 365` vira 365, e um campo
    # limpo por engano viraria UM ANO de acesso anonimo. Num prazo de permissao
    # o erro tem de cair para o lado curto, nunca para o longo.
    dias = 365 if body.dias is None else int(body.dias)
    dias = max(1, min(dias, _DIAS_MAX_LINK))
    return datetime.now(timezone.utc) + timedelta(days=dias), dias


def _caminho_link(slug: str, kind: str) -> str:
    """Rota da superficie. Curta nas duas porque o link e ditado/colado a mao."""
    return f"/m/{slug}" if kind == "mobile" else f"/t/{slug}"


def _ref_link(slug: str) -> str:
    """Identificador do link para a TRILHA DE AUDITORIA — nunca o slug.

    O slug E A CREDENCIAL: `/api/bi/tela-pub/{slug}` e publico, nao pede login e
    devolve o token de quiosque para quem souber os 12 caracteres (ver
    `resolver_tela_link`, que diz isso com todas as letras). A trilha e lida por
    qualquer um com a tela de Auditoria e sai do sistema em PDF/Excel — gravar o
    slug ali entregaria o painel do municipio a quem so deveria poder AUDITAR
    quem o publicou, e ainda por cima num arquivo que circula por e-mail.
    `services/audit.py` ja se recusa a guardar o caminho preenchido desta rota
    (`_rota` guarda so o molde) exatamente por isto; entrar pelo `target_id`
    reabriria a mesma porta pelos fundos.

    O hash resolve o unico uso legitimo do valor: amarrar a criacao a revogacao
    do MESMO link. Nao volta a ser slug (SHA-256) e nao serve de credencial."""
    return hashlib.sha256(slug.encode("utf-8")).hexdigest()[:16]


def _anos_csv(anos: list[int]) -> str:
    """Normaliza pelo MESMO filtro do anos_list (1990<n<2100) para nao gravar
    lixo que depois volta como periodo valido."""
    return ",".join(str(a) for a in (anos_list(anos) or []))


def _csv_anos(csv: Optional[str]) -> list[int]:
    return anos_list(csv or "") or []


async def _ensure_kiosk_user(db: AsyncSession, owner: User, slug: str) -> int:
    """Usuario 'viewer' sintetico por LINK (antes era um por municipio,
    compartilhado entre todos os gestores). Um por link e o que torna a
    revogacao real: desativar este usuario mata o token daquele link e so dele
    — os outros links do mesmo dono seguem no ar.

    Espelha os municipios do dono: a TV nunca enxerga mais que quem a publicou."""
    email = f"kiosk-u{owner.id}-{slug}@painel.local"
    urow = (await db.execute(text("SELECT id FROM users WHERE email = :e"), {"e": email})).first()
    # `kiosk` e `somente_leitura` gravados AQUI, e não deixados para o backfill do
    # próximo boot.
    #
    # `users.kiosk` é o que `get_current_user` lê para aplicar `KIOSK_GET_PERMITIDOS`
    # — a allowlist por igualdade de caminho que fecha o link público no Painel
    # (PR #112). Ela era preenchida SÓ por `add_users_kiosk.sql`, que roda no
    # boot: um link publicado às 10h ficava com `kiosk = FALSE` até o próximo
    # restart e, nesse meio-tempo, alcançava todos os GET do sistema com o token
    # de 365 dias que circula em WhatsApp. `somente_leitura` tem a mesma história
    # a partir deste incremento (a semente da flag também é de boot).
    #
    # Nenhum dos dois pode depender de reinício: a conta é criada em RUNTIME, e o
    # que a barra tem de nascer com ela. As migrations continuam existindo como
    # rede para as contas antigas.
    if urow:
        uid = urow[0]
        await db.execute(text(
            "UPDATE users SET active = true, role = 'viewer', kiosk = true, "
            "somente_leitura = true WHERE id = :u"
        ), {"u": uid})
    else:
        ph = hash_password(secrets.token_urlsafe(24))
        r = (await db.execute(text(
            "INSERT INTO users (email, name, password_hash, role, active, "
            "must_change_password, kiosk, somente_leitura) "
            "VALUES (:e, :n, :p, 'viewer', true, false, true, true) RETURNING id"
        ), {"e": email, "n": f"Quiosque de {owner.name or owner.email}", "p": ph})).first()
        uid = r[0]
    # concede a tela BI (consistencia; os endpoints /api/bi/* gateiam por municipio)
    await db.execute(text(
        "INSERT INTO user_telas (user_id, tela) VALUES (:u, 'bi') ON CONFLICT DO NOTHING"
    ), {"u": uid})
    # Espelha o escopo do dono a cada emissao.
    #
    # ⚠️ Aqui estava `owner.role == "admin"`, com o comentario "admin = carteira
    # ativa inteira". Isso valia enquanto `role == "admin"` zerava os limites em
    # `load_user_scopes` — o admin de fato enxergava todos os municipios ativos.
    # Depois que o papel virou ROTULO, deixou de valer: um admin cujo escopo foi
    # reduzido a dois municipios continuaria emitindo um link PUBLICO de TV com
    # a carteira inteira do cliente, e esse link circula em WhatsApp. Era a
    # propria promessa do docstring acima ("a TV nunca enxerga mais que quem a
    # publicou") sendo quebrada pela porta de tras, num caminho sem 403 nenhum
    # para avisar.
    #
    # `is_super_admin` e nao `role`: para a Alavank o ramo de baixo devolveria
    # ZERO municipio (o dono da plataforma nao tem linha em `user_municipios`,
    # por definicao — `load_user_scopes` sai antes de consultar), e a TV nasceria
    # vazia. Para todo o resto, incluindo o admin do cliente, o espelho e a lista
    # real da pessoa.
    await db.execute(text("DELETE FROM user_municipios WHERE user_id = :u"), {"u": uid})
    if is_super_admin(owner):
        await db.execute(text(
            "INSERT INTO user_municipios (user_id, municipio_id) "
            "SELECT :u, id FROM municipios WHERE active = true ON CONFLICT DO NOTHING"
        ), {"u": uid})
    else:
        await db.execute(text(
            "INSERT INTO user_municipios (user_id, municipio_id) "
            "SELECT :u, municipio_id FROM user_municipios WHERE user_id = :o ON CONFLICT DO NOTHING"
        ), {"u": uid, "o": owner.id})
    return uid


# /tela-filtros e /tela-links (menos o POST) NAO declaram permissao: sao
# auto-escopadas por `user_id`/`owner_id` e estao em ROTAS_LIVRES, com motivo, em
# services/registro_rotas.py. No GET abaixo isso tambem e a armadilha do
# quiosque: o caminho esta em `KIOSK_GET_PERMITIDOS` e a conta de TV so tem
# `bi.ver` — declarar `bi.tela` aqui mataria os links legados `?kiosk=`.
@router.get("/tela-filtros")
async def get_tela_filtros(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Filtro corrente do PROPRIO usuario. A janela do Modo Tela le daqui quando
    esta noutro navegador/aparelho, onde o BroadcastChannel nao alcanca.

    SEM `_gate_bi`, de proposito: auto-escopado por `user_id` — le e escreve so
    a PROPRIA linha, e para quem nao tem o Painel o retorno e o default vazio.
    Alem disso este caminho esta em `KIOSK_GET_PERMITIDOS` (os links legados
    `?kiosk=` dependem dele) e o Painel chama o PUT a cada mudanca de filtro,
    para TODO usuario — exigir `bi_tela` aqui encheria a semana de observacao de
    linhas sobre um fato que nao e o buraco que estamos fechando."""
    row = (await db.execute(text(
        "SELECT scope, anos, aba FROM bi_tela_filtros WHERE user_id = :u"
    ), {"u": current.id})).first()
    if not row:
        # `existe: false` importa: sem ele a tela aberta por um link antigo
        # (?kiosk=<jwt>&scope=...) leria este default e jogaria fora o filtro que
        # veio na URL, regredindo o link que ja estava colado numa TV.
        return {"existe": False, "scope": CONSOLIDADO, "anos": [], "aba": None}
    return {"existe": True, "scope": row[0], "anos": _csv_anos(row[1]), "aba": row[2]}


@router.put("/tela-filtros")
async def put_tela_filtros(
    body: FiltroTelaIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Publica o filtro do usuario. O painel chama isto a cada mudanca de periodo
    ou de municipio — e o que faz a TV e o link publico virarem junto."""
    await db.execute(text(
        "INSERT INTO bi_tela_filtros (user_id, scope, anos, aba, updated_at) "
        "VALUES (:u, :s, :a, :b, NOW()) "
        "ON CONFLICT (user_id) DO UPDATE SET scope = :s, anos = :a, aba = :b, updated_at = NOW()"
    ), {"u": current.id, "s": (body.scope or CONSOLIDADO)[:40],
        "a": _anos_csv(body.anos), "b": (body.aba or None)})
    await db.commit()
    return {"ok": True}


def _link_para_api(slug, nome, criado_em, expira_em, revogado, ultimo_acesso,
                   kind, *, dias=None, cidade=None) -> dict:
    """⭐ A FORMA DO LINK, NUM LUGAR SO — e a razao e um defeito de verdade.

    Criar e listar montavam o dicionario cada um por conta propria, e as duas
    formas divergiram: o POST devolvia so `{slug, caminho, kind, dias}`, entao o
    link recem-criado entrava na lista da tela sem nome e sem prazo, e so
    aparecia inteiro depois de fechar e reabrir o modal. Com uma funcao so, um
    campo novo nasce nas duas respostas ou em nenhuma.

    `dias` sai apenas na criacao: e o prazo PEDIDO, util para a tela confirmar o
    que acabou de acontecer. Na listagem, o que vale e `expira_em` — o pedido de
    ontem nao diz quanto falta hoje."""
    ficha = {
        "slug": slug,
        "caminho": _caminho_link(slug, kind or "tela"),
        "kind": kind or "tela",
        "nome": nome,
        "criado_em": criado_em.isoformat() if criado_em else None,
        "expira_em": expira_em.isoformat() if expira_em else None,
        "revogado": bool(revogado),
        "ultimo_acesso": ultimo_acesso.isoformat() if ultimo_acesso else None,
        # A cidade em que o link foi FIXADO (None = segue o dono/consolidado).
        # A lista mostra "Cidade · Modo" e a prévia do WhatsApp cita a cidade.
        "cidade": cidade,
    }
    if dias is not None:
        ficha["dias"] = dias
    return ficha


@router.post("/tela-links", dependencies=[exige("bi.link")])
async def criar_tela_link(
    body: TelaLinkIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Gera um link publico CURTO para a TV. Permissao propria (`bi_link`): quem
    pode ver o Modo Tela nao necessariamente pode publicar dado para fora.

    NAO leva `_gate_bi`: `bi_link` ja e a permissao mais forte do Painel — quem
    a tem publica o painel para fora da prefeitura, e ela nunca foi concedida em
    massa (ver `migrations/add_bi_tela.sql`). Somar `bi` aqui seria duplicar
    gate no mesmo endpoint."""
    ensure_tela(current, "bi_link")
    kind = "mobile" if (body.kind or "tela").lower() == "mobile" else "tela"
    # Expiracao calculada em Python de proposito: `make_interval(days => :d)`
    # mistura a notacao de argumento nomeado do Postgres com o bind do
    # SQLAlchemy, e nao ha ganho nenhum em arriscar isso no driver.
    expira, dias = _prazo_do_link(body)
    slug = secrets.token_urlsafe(9)[:12]  # 12 chars, ~72 bits: curto e nao chutavel
    uid = await _ensure_kiosk_user(db, current, slug)
    token = create_kiosk_token(uid, dias)
    nome_do_link = body.nome or None
    # FIXA O MUNICÍPIO se o escopo é uma cidade concreta E o dono a enxerga
    # (não deixar fixar um município fora do próprio escopo — o link é público).
    # Consolidado/ausente -> NULL, e o resolver segue o filtro do dono.
    pin_mid = None
    esc = (body.escopo or "").strip()
    if esc and esc != CONSOLIDADO and esc.isdigit():
        ok = (await db.execute(text(
            "SELECT 1 FROM municipios m WHERE m.id = :mid AND m.active"
            " AND (:sup OR EXISTS (SELECT 1 FROM user_municipios um"
            "                      WHERE um.user_id = :o AND um.municipio_id = m.id))"
        ), {"mid": int(esc), "o": current.id, "sup": is_super_admin(current)})).first()
        if ok:
            pin_mid = int(esc)
    cidade_do_link = None
    if pin_mid is not None:
        cidade_do_link = (await db.execute(text(
            "SELECT nome FROM municipios WHERE id = :m"), {"m": pin_mid})).scalar()
    # `RETURNING criado_em` em vez de carimbar a hora em Python: quem manda no
    # relogio e o banco (a coluna tem DEFAULT NOW()), e uma hora vinda daqui
    # divergiria da que a listagem mostra no proximo carregamento.
    criado_em = (await db.execute(text(
        "INSERT INTO bi_tela_links (slug, owner_id, kiosk_user_id, municipio_id, token, nome, expira_em, kind) "
        "VALUES (:s, :o, :k, :mid, :t, :n, :e, :kind) RETURNING criado_em"
    ), {"s": slug, "o": current.id, "k": uid, "mid": pin_mid, "t": token,
        "n": nome_do_link, "e": expira, "kind": kind})).scalar()
    await db.commit()
    # Publicar link de TV cria acesso ANONIMO e duradouro ao painel: quem tiver a
    # URL ve o dado sem login, por ate `dias`. E o evento de permissao mais forte
    # que um gestor consegue disparar sozinho — e ate agora nao deixava rastro
    # nenhum. NEM O SLUG NEM O CAMINHO entram: os dois SAO a credencial (ver
    # `_ref_link`). O que amarra criacao e revogacao do mesmo link e a
    # `referencia` (hash); quem o link libera esta no `kiosk_user_id`, e o nome
    # que o gestor deu identifica o link para uma pessoa.
    await registrar(
        db, action="bi.tela_link.create", user=current, request=request,
        target_type="bi_tela_link", target_id=_ref_link(slug),
        alvo_nome=(body.nome or f"link de {kind}"),
        details={"referencia": _ref_link(slug), "kind": kind, "nome": body.nome,
                 "dias": dias, "expira_em": expira.isoformat() if expira else None,
                 "sem_prazo": expira is None,
                 "kiosk_user_id": uid,
                 "efeito": "acesso público sem login ao painel enquanto o link viver"},
    )
    # ⚠️ A RESPOSTA DO POST TEM DE SER O LINK INTEIRO, e nao so o slug.
    # Devolvia `{slug, caminho, kind, dias}`, e a tela — que insere o item
    # devolvido direto na lista, sem recarregar — mostrava o link recem-criado
    # como "Sem destinatario" e "Sem prazo". Nao era erro de gravacao: o banco
    # estava certo o tempo todo, e bastava fechar e reabrir o modal para o nome e
    # a validade aparecerem. Um defeito que se conserta sozinho ao recarregar e
    # dos piores, porque quem ve conclui que o sistema perdeu o que digitou.
    return _link_para_api(slug, nome_do_link, criado_em, expira, False, None, kind,
                          dias=dias, cidade=cidade_do_link)


@router.get("/tela-links")
async def listar_tela_links(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Links do PROPRIO usuario — ninguem lista nem revoga link alheio.

    SEM `_gate_bi`: auto-escopado por `owner_id` na propria consulta. Quem nao
    tem o Painel nao tem link, e a resposta e uma lista vazia."""
    # Revogado NAO aparece: o link esta morto (404 e token desativado) e nao ha
    # nada a fazer com ele. Antes ficava na lista para sempre, sem marca alguma —
    # ao recarregar o modal, um link que o gestor acabou de apagar reaparecia, e o
    # botao de copiar entregava uma URL que nao abre.
    rows = (await db.execute(text(
        "SELECT l.slug, l.nome, l.criado_em, l.expira_em, l.revogado, "
        "       l.ultimo_acesso, l.kind, m.nome AS cidade "
        "FROM bi_tela_links l "
        "LEFT JOIN municipios m ON m.id = l.municipio_id "
        "WHERE l.owner_id = :u AND NOT l.revogado "
        "ORDER BY l.criado_em DESC LIMIT 50"
    ), {"u": current.id})).fetchall()
    return [_link_para_api(r[0], r[1], r[2], r[3], r[4], r[5], r[6], cidade=r[7])
            for r in rows]


@router.delete("/tela-links/{slug}")
async def revogar_tela_link(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Revoga o link. So o dono revoga o proprio.

    Marcar `revogado` sozinho nao bastaria: quem ja tivesse extraido o token do
    localStorage da TV continuaria batendo na API por mais 365 dias. Como o
    usuario de quiosque e por LINK, desativa-lo mata o token daquele link — e
    so dele.

    SEM `_gate_bi`: auto-escopado por `owner_id` no proprio UPDATE. E revogar e
    a acao que NUNCA se deve negar — travar o corte de um acesso publico por
    falta de permissao deixaria o link vivo, que e exatamente o contrario do que
    qualquer gate quer."""
    row = (await db.execute(text(
        "UPDATE bi_tela_links SET revogado = TRUE WHERE slug = :s AND owner_id = :u "
        "RETURNING kiosk_user_id"
    ), {"s": slug, "u": current.id})).first()
    if not row:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Link não encontrado")
    await db.execute(text("UPDATE users SET active = false WHERE id = :k"), {"k": row[0]})
    await db.commit()
    # Mesma `referencia` da criacao (hash do slug): e por ela que o auditor liga
    # "publicou" a "revogou" sem que a trilha guarde o endereco que ainda estava
    # colado numa TV. O slug segue fora daqui — revogado hoje nao apaga o que a
    # trilha guardaria por 5 anos, e ha registros de links AINDA VIVOS na mesma
    # tabela.
    await registrar(
        db, action="bi.tela_link.revoke", user=current, request=request,
        target_type="bi_tela_link", target_id=_ref_link(slug),
        alvo_nome=f"link de painel ({_ref_link(slug)[:8]})",
        details={"referencia": _ref_link(slug), "kiosk_user_id": row[0],
                 "efeito": "link e token de quiosque desativados"},
    )
    return {"ok": True}


@router.get("/tela-pub/{slug}")
async def resolver_tela_link(slug: str, db: AsyncSession = Depends(get_db)):
    """PUBLICO — o slug e o segredo. A TV chama isto ao abrir e a cada poll:
    devolve o token de quiosque e o FILTRO VIGENTE DO DONO. E por aqui que
    "mudou o periodo no sistema" vira "mudou na TV" mesmo noutro aparelho, onde
    o BroadcastChannel nunca chegaria.

    Sem `_gate_bi` porque nao ha usuario para gatear: a rota nao depende de
    `get_current_user`. Quem limita o alcance do que ela entrega e o proprio
    prazo do link, a marca de revogado e, do outro lado, a allowlist de
    quiosque em `services/auth.py`."""
    row = (await db.execute(text(
        "SELECT l.token, l.owner_id, l.municipio_id, l.revogado, l.expira_em, "
        "       f.scope, f.anos, f.aba, l.kind "
        "FROM bi_tela_links l "
        "LEFT JOIN bi_tela_filtros f ON f.user_id = l.owner_id "
        "WHERE l.slug = :s"
    ), {"s": slug})).first()
    if not row or row[3]:
        raise HTTPException(status_code=404, detail="Link inválido ou revogado")
    if row[4] is not None and row[4] < datetime.now(timezone.utc):
        raise HTTPException(status_code=404, detail="Link expirado")
    # Throttle proposital: a TV chama isto a cada 10s, o dia inteiro. Gravar a
    # cada chamada seriam ~8.600 escritas/dia por televisao, so para mexer num
    # carimbo que ninguem le com essa precisao. De 5 em 5 minutos basta.
    await db.execute(text(
        "UPDATE bi_tela_links SET ultimo_acesso = NOW() WHERE slug = :s "
        "AND (ultimo_acesso IS NULL OR ultimo_acesso < NOW() - INTERVAL '5 minutes')"
    ), {"s": slug})
    await db.commit()
    # municipio_id preenchido = link fixado num municipio; NULL = segue o dono.
    # O NULL e o caso da assessoria: trocou de municipio no sistema, a TV vai
    # junto. Quem barra excesso e o resolve_scope dos endpoints de dado, que so
    # aceita municipio dentro do escopo do usuario de quiosque.
    scope = str(row[2]) if row[2] is not None else (row[5] or CONSOLIDADO)
    return {
        "token": row[0],
        "scope": scope,
        "anos": _csv_anos(row[6]),
        "aba": row[7],
        # 'mobile' usa isto como SEMENTE e depois manda em si; 'tela' segue o
        # dono a cada poll. Quem decide e a superficie, nao o servidor.
        "kind": row[8] or "tela",
    }


@router.get("/tela-pub/{slug}/meta")
async def meta_tela_link(slug: str, db: AsyncSession = Depends(get_db)):
    """SO O TITULO para a previa de compartilhamento — o WhatsApp le a Open Graph
    no HTML (server-side), sem rodar JS. Publico como a resolucao, mas revela
    MENOS: cidade + modo, nunca o token e sem tocar no quiosque. Link revogado ou
    expirado devolve titulo NEUTRO (a pagina em si 404a) — sem previa enganosa.

    O slug ja e a credencial: quem o tem ve o painel inteiro, entao expor cidade
    e modo aqui e estritamente menos do que ele ja alcanca — e e o que o dono
    PEDE para organizar dezenas de links num grupo de WhatsApp."""
    row = (await db.execute(text(
        "SELECT l.kind, l.revogado, l.expira_em, m.nome AS cidade_fix, f.scope "
        "FROM bi_tela_links l "
        "LEFT JOIN municipios m ON m.id = l.municipio_id "
        "LEFT JOIN bi_tela_filtros f ON f.user_id = l.owner_id "
        "WHERE l.slug = :s"
    ), {"s": slug})).first()
    modo = "Mobile" if (row and row[0] == "mobile") else "Dashboard"
    neutro = {"cidade": None, "modo": modo, "titulo": "Painel de Indicadores PACTHA"}
    if not row or row[1] or (row[2] is not None and row[2] < datetime.now(timezone.utc)):
        return neutro
    cidade = row[3]  # cidade FIXADA no link
    if not cidade:
        # Legado NULL (ou consolidado): se o filtro do dono e um unico municipio,
        # usa o nome dele; senao, "Consolidado".
        sc = row[4]
        if sc and sc != CONSOLIDADO and str(sc).isdigit():
            cidade = (await db.execute(text("SELECT nome FROM municipios WHERE id = :m"),
                                       {"m": int(sc)})).scalar()
        cidade = cidade or "Consolidado"
    return {"cidade": cidade, "modo": modo,
            "titulo": f"Painel de Indicadores PACTHA - {cidade} - {modo}"}


# --------------------------------------------------------------------------
# Push web + preferencias (perfil executivo). Escritas permitidas ao readonly
# via READONLY_WRITE_ALLOW (services/auth.py). Reusa as tabelas painel_*.
# --------------------------------------------------------------------------

class PushSubIn(BaseModel):
    municipio_id: int
    endpoint: str
    p256dh: str
    auth: str
    ua: Optional[str] = None


class PrefsIn(BaseModel):
    cauc_vencendo: bool = True
    obra_prazo: bool = True
    nova_emenda: bool = True
    prazo_prestacao: bool = True
    mudanca_status: bool = True
    vigencia_60d: bool = True


@router.get("/vapid-public-key")
async def vapid_public_key(current: User = Depends(get_current_user)):
    # A chave VAPID publica nao e segredo (ela vai para o navegador de qualquer
    # assinante), mas so serve para assinar o push DO PAINEL — que e gateado
    # logo abaixo. Sem o gate aqui este seria o unico endpoint do arquivo sem
    # checagem alguma, e a proxima pessoa a ler o arquivo teria de descobrir
    # sozinha se foi esquecimento ou decisao.
    _gate_bi(current)
    return {"key": os.getenv("VAPID_PUBLIC_KEY") or ""}


@router.post("/push/subscribe")
async def push_subscribe(
    body: PushSubIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # Assinar push do Painel e assinar o Painel: sem a tela, nao ha o que
    # notificar. O escopo de municipio (abaixo) ja existia e continua valendo.
    _gate_bi(current)
    # valida que o municipio esta no escopo do usuario
    _ids, _cons = await resolve_scope(db, current, body.municipio_id)
    await db.execute(text(
        "INSERT INTO painel_push_subscriptions (user_id, municipio_id, endpoint, p256dh, auth, ua) "
        "VALUES (:u, :m, :e, :p, :a, :ua) "
        "ON CONFLICT (endpoint) DO UPDATE SET p256dh = :p, auth = :a, ua = :ua, "
        "municipio_id = :m, user_id = :u, last_ok_at = NULL"
    ), {"u": current.id, "m": body.municipio_id, "e": body.endpoint,
        "p": body.p256dh, "a": body.auth, "ua": body.ua})
    await db.commit()
    return {"ok": True}


@router.delete("/push/subscribe")
async def push_unsubscribe(
    endpoint: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # SEM `_gate_bi`: auto-escopado por `user_id`, e cancelar a propria
    # inscricao e o par de "revogar" — negar isso deixaria um aparelho recebendo
    # notificacao do Painel sem conseguir desligar.
    await db.execute(text(
        "DELETE FROM painel_push_subscriptions WHERE endpoint = :e AND user_id = :u"
    ), {"e": endpoint, "u": current.id})
    await db.commit()
    return {"ok": True}


@router.get("/preferencias")
async def get_preferencias(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    # GET e PUT de /preferencias ficam SEM `_gate_bi`: auto-escopados por
    # `user_id` (a propria linha), guardam so liga/desliga de notificacao e nao
    # revelam nem alteram dado de municipio nenhum.
    row = (await db.execute(text(
        "SELECT cauc_vencendo, nova_emenda, prazo_prestacao, mudanca_status, vigencia_60d, "
        "       COALESCE(obra_prazo, true) "
        "FROM painel_preferencias WHERE user_id = :u"
    ), {"u": current.id})).first()
    if not row:
        return {"cauc_vencendo": True, "obra_prazo": True, "nova_emenda": True, "prazo_prestacao": True,
                "mudanca_status": True, "vigencia_60d": True}
    return {"cauc_vencendo": row[0], "obra_prazo": row[5], "nova_emenda": row[1], "prazo_prestacao": row[2],
            "mudanca_status": row[3], "vigencia_60d": row[4]}


@router.put("/preferencias")
async def put_preferencias(
    body: PrefsIn,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    await db.execute(text(
        "INSERT INTO painel_preferencias (user_id, cauc_vencendo, obra_prazo, nova_emenda, prazo_prestacao, "
        "mudanca_status, vigencia_60d, updated_at) VALUES (:u, :a, :f, :b, :c, :d, :e, NOW()) "
        "ON CONFLICT (user_id) DO UPDATE SET cauc_vencendo = :a, obra_prazo = :f, nova_emenda = :b, "
        "prazo_prestacao = :c, mudanca_status = :d, vigencia_60d = :e, updated_at = NOW()"
    ), {"u": current.id, "a": body.cauc_vencendo, "f": body.obra_prazo, "b": body.nova_emenda,
        "c": body.prazo_prestacao, "d": body.mudanca_status, "e": body.vigencia_60d})
    await db.commit()
    return {"ok": True}
