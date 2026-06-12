"""IA Assistant - Claude consulta o banco de dados PACTA via tool use.

Endpoint:
  POST /api/ai/chat - recebe pergunta + municipio_id + historico, devolve resposta

Implementacao:
  - Claude Opus 4.8 com adaptive thinking
  - Prompt caching no system + tools
  - Tool use loop manual (Claude pede ferramenta -> backend executa SQL -> repete)
  - Ferramentas cobrem todas as fontes: SIGCON, Voluntarias/Geral/Rejeitadas,
    SIMEC PAR, Emendas Estaduais, summary do municipio

A chave da API fica em env var ANTHROPIC_API_KEY (Railway secret, nao no git).
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func
from database import get_db
from models import ConvenioEstadual, Municipio
from services.auth import get_current_user

logger = logging.getLogger("ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Padrao das Voluntarias / Rejeitadas (mesmo dos routers/transferegov.py)
_VOL_LIKE = "%enviado para an%lise%"
_REJ_LIKE = "%rejeitad%"

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """Voce eh o assistente IA da PACTA, plataforma da Freitas Consultoria que monitora
convenios federais e estaduais de 6 municipios de Minas Gerais. Voce ajuda os
consultores e gestores municipais a responderem perguntas e gerarem relatorios
sobre os lancamentos, valores, vigencias, parlamentares e situacoes.

REGRAS DE OURO:
1. SEMPRE use as ferramentas disponiveis para obter dados. NUNCA invente numeros, datas, nomes ou valores.
2. Se a pergunta for ampla, faca multiplas consultas com ferramentas diferentes.
3. Apresente resultados em portugues, formatados em markdown quando ajudar (tabelas, listas).
4. Valores em R$ no formato brasileiro: R$ 1.234.567,89.
5. Datas em dd/mm/yyyy.
6. Se nao tiver dado suficiente, diga claramente o que falta em vez de inventar.

FONTES DE DADOS:
- **SIGCON-MG (Estadual)**: convenios celebrados com Estado de MG via SEINFRA, SEGOV,
  SES, SEE, SEAPA, SEDESE, etc. Tem nº de instrumento (XXXXXXXXXX/YYYY), SIAFI,
  proposta, plano de trabalho. Use `query_convenios_sigcon`.
- **TransfereGov Voluntarias (SICONV, Federal)**: propostas/convenios federais.
  Tres categorias por status:
    * `voluntarias`: status "Proposta/Plano de Trabalho enviado para Analise"
    * `rejeitadas`: status com "Rejeitad"
    * `geral`: o restante (Em execucao, Aprovados, Prestacao de Contas, etc.)
  Use `query_voluntarias`.
  * **Situacao de Contratacao** (Normal / Clausula Suspensiva / Liminar Judicial) e um
    campo FEDERAL das Voluntarias. Para "quais estao em clausula suspensiva/liminar",
    chame `query_voluntarias` com `situacao_contratacao` e SEM `municipio_id` (busca
    os 6 de uma vez, 1 chamada so). A resposta ja traz Empenhado (Sim/Nao) e, na
    clausula, o Motivo + Data prevista para resolucao. NUNCA use query_situacoes_sigcon
    para isso (aquilo e estadual e nao tem clausula suspensiva).
- **SIMEC PAR (MEC)**: liberacoes federais de PNAE, PNATE, QUOTA Salario-Educacao,
  PDDE. Tambem tem sintese do diagnostico do PAR por dimensao.
  Use `query_simec_liberacoes` ou `query_simec_dimensoes`.
- **Emendas Estaduais**: indicacoes parlamentares estaduais (SIGCON Pesquisar Emendas).
  Use `query_emendas_estaduais`.

BUSCA POR PARLAMENTAR:
- Se o usuario perguntar por um parlamentar especifico (deputado/senador), use
  `search_by_parlamentar` — retorna TUDO daquele nome em uma chamada:
  convenios SIGCON, propostas SICONV, indicacoes/emendas. Cross-fonte.
- Se for um filtro DENTRO de uma fonte, use o parametro `parlamentar` da tool
  especifica (query_convenios_sigcon, query_voluntarias, query_emendas_estaduais).

ESTRUTURA TEMPORAL:
- "Vence em 60d" = convenios com fim de vigencia nos proximos 60 dias.
- "Vence em 120d" = idem para 120 dias.
- "Prestacao de Contas" = convenios vencidos ha mais de 90 dias (precisam prestar contas).

FORMATO DA RESPOSTA (importante para a UI renderizar bem):
- Use **markdown** SEMPRE: headings (## Titulo), listas (- item), negrito (**chave**).
- Para dados tabulares, use TABELAS markdown reais:
  | Coluna A | Coluna B |
  | --- | --- |
  | valor | valor |
  (Sempre com o separador `---` na segunda linha.)
- Quando o resultado tiver MULTIPLAS fontes, divida em SECOES com `##` ou `###`.
- Quando o resultado eh longo, comece com um resumo TL;DR de 2-3 linhas, depois detalhe.
- Valores monetarios SEMPRE como `**R$ 1.234.567,89**` em negrito quando forem totais."""


# --------------------------------------------------------------------------
# Tool definitions (JSON schemas)
# --------------------------------------------------------------------------
TOOLS = [
    {
        "name": "list_municipios",
        "description": "Lista os 6 municipios atendidos pela PACTA com ID e nome (use o ID nas outras ferramentas).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "municipio_summary",
        "description": "Resumo consolidado do municipio: contagem de convenios SIGCON, total de Voluntarias, valor total estadual e federal, alertas de vigencia (60d, 120d) e prestacao de contas (vencidos +90d) ja separados estadual/federal.",
        "input_schema": {
            "type": "object",
            "properties": {"municipio_id": {"type": "integer", "description": "ID do municipio (use list_municipios para descobrir)"}},
            "required": ["municipio_id"],
        },
    },
    {
        "name": "query_convenios_sigcon",
        "description": "Busca convenios estaduais SIGCON-MG do municipio. Filtros opcionais: situacoes (lista), ano de assinatura, busca textual (n° instrumento/proposta/plano/SIAFI/objeto), parlamentar (nome do deputado responsavel/indicador), vigencia (vence em 60d, 120d, ou prestacao de contas +90d vencido).",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "situacoes": {"type": "array", "items": {"type": "string"}, "description": "Lista de situacoes exatas (ex: ['INSTRUMENTO CADASTRADO / VIGENTE', 'PRESTACAO DE CONTAS APROVADA']). Veja query_situacoes_sigcon para a lista disponivel."},
                "ano": {"type": "integer", "description": "Ano de assinatura"},
                "search": {"type": "string", "description": "Busca em n° instrumento, proposta, plano, SIAFI ou objeto"},
                "parlamentar": {"type": "string", "description": "Nome do parlamentar/responsavel (busca parcial em raw_data->responsaveis). Ex: 'EDUARDO AZEVEDO', 'AVELAR'"},
                "vigencia": {"type": "string", "enum": ["vence60", "vence120", "prestacao"], "description": "Filtro de vigencia"},
                "limit": {"type": "integer", "description": "Max resultados (default 30, max 100)"},
            },
            "required": ["municipio_id"],
        },
    },
    {
        "name": "query_situacoes_sigcon",
        "description": "Lista as situacoes distintas dos convenios SIGCON do municipio (ex: 'INSTRUMENTO CADASTRADO / VIGENTE', 'PRESTACAO DE CONTAS APROVADA') com contagem. Util antes de filtrar por situacoes em query_convenios_sigcon.",
        "input_schema": {
            "type": "object",
            "properties": {"municipio_id": {"type": "integer"}},
            "required": ["municipio_id"],
        },
    },
    {
        "name": "query_voluntarias",
        "description": "Busca propostas/convenios SICONV (FEDERAL) das Voluntarias. municipio_id e OPCIONAL — sem ele busca nos 6 municipios de uma vez (ideal p/ 'quais em clausula suspensiva'). Categorias: geral (em execucao/aprovados/prestacao), voluntarias (enviado p/ analise), rejeitadas. Retorna orgao, situacao, valores, vigencia, parlamentar, Empenhado (Sim/Nao) e, quando aplicavel, Situacao de Contratacao + Motivo/Data da Clausula Suspensiva. Use situacao_contratacao p/ filtrar 'Clausula Suspensiva' ou 'Liminar Judicial' (isso e FEDERAL — NAO use query_situacoes_sigcon).",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer", "description": "Opcional. Sem ele, busca nos 6 municipios."},
                "categoria": {"type": "string", "enum": ["geral", "voluntarias", "rejeitadas"], "description": "Categoria (omite para todas)"},
                "situacao_contratacao": {"type": "string", "description": "Filtra a situacao de contratacao (ex: 'Clausula Suspensiva', 'Liminar Judicial', 'Normal'). Busca parcial."},
                "search": {"type": "string", "description": "Busca em n° proposta ou proponente"},
                "parlamentar": {"type": "string", "description": "Nome do parlamentar autor da indicacao (busca parcial)"},
                "limit": {"type": "integer", "description": "Max resultados (default 50, max 200)"},
            },
            "required": [],
        },
    },
    {
        "name": "search_by_parlamentar",
        "description": "Busca UNIFICADA por nome de parlamentar em TODAS as fontes: convenios SIGCON-MG (estaduais, campo responsaveis), propostas SICONV (federais, campo parlamentar), emendas estaduais (nome_responsavel). Use quando o usuario pede 'tudo do deputado X' ou 'convenios indicados por Y'. Retorna agrupado por fonte.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome ou parte do nome do parlamentar (ex: 'AVELAR', 'EDUARDO AZEVEDO'). Match case-insensitive parcial."},
                "municipio_id": {"type": "integer", "description": "Opcional: filtra um municipio. Sem isso, busca nos 6 municipios."},
                "limit": {"type": "integer", "description": "Max resultados por fonte (default 50)"},
            },
            "required": ["nome"],
        },
    },
    {
        "name": "query_simec_liberacoes",
        "description": "Liberacoes de recursos federais MEC para o municipio (PNAE Alimentacao Escolar, PNATE Transporte, QUOTA Salario-Educacao, PDDE). Cada linha tem data, valor, programa, OB, banco/conta.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "ano": {"type": "integer", "description": "Filtra por ano do pagamento"},
                "programa": {"type": "string", "description": "Sigla do programa (PNATE, QUOTA, PDDE, ALIMENTACAO)"},
            },
            "required": ["municipio_id"],
        },
    },
    {
        "name": "query_simec_dimensoes",
        "description": "Sintese do PAR (Plano de Acoes Articuladas) por dimensao do municipio. 4 dimensoes: Gestao Educacional, Formacao de Professores, Praticas Pedagogicas, Infraestrutura Fisica. Cada uma com contagem de indicadores por pontuacao (4=bom, 3=adequado, 2=a melhorar, 1=critico).",
        "input_schema": {
            "type": "object",
            "properties": {"municipio_id": {"type": "integer"}},
            "required": ["municipio_id"],
        },
    },
    {
        "name": "query_emendas_estaduais",
        "description": "Indicacoes/emendas estaduais SIGCON do municipio. Inclui n° indicacao, parlamentar, beneficiario, tipo de atendimento, valor, status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "parlamentar": {"type": "string", "description": "Filtra por nome do parlamentar (busca parcial)"},
                "ano": {"type": "integer"},
                "limit": {"type": "integer", "description": "Max resultados (default 30)"},
            },
            "required": ["municipio_id"],
        },
    },
]


# --------------------------------------------------------------------------
# Helpers de formatacao
# --------------------------------------------------------------------------
def _fmt_money(v) -> str:
    if v is None:
        return "-"
    try:
        v = float(v)
        s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"R$ {s}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_dt(d) -> str:
    if not d:
        return "-"
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    return str(d)


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------
async def _tool_list_municipios(db: AsyncSession, _input: dict) -> str:
    r = await db.execute(text("SELECT id, nome, uf FROM municipios WHERE active = true ORDER BY nome"))
    rows = r.fetchall()
    return "Municipios atendidos:\n" + "\n".join(f"- id={row[0]}  {row[1]}/{row[2]}" for row in rows)


async def _tool_municipio_summary(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    # Reusa a logica do router /municipios/{id}/summary
    from datetime import datetime, timedelta
    mun = (await db.execute(select(Municipio).where(Municipio.id == mun_id))).scalar_one_or_none()
    if not mun:
        return f"Erro: municipio_id={mun_id} nao encontrado."
    est_count = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
                                  .where(ConvenioEstadual.municipio_id == mun_id))).scalar()
    est_valor = (await db.execute(select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
                                  .where(ConvenioEstadual.municipio_id == mun_id))).scalar()
    hoje = date.today()
    l120 = hoje + timedelta(days=120); l60 = hoje + timedelta(days=60); v90 = hoje - timedelta(days=90)
    a120 = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == mun_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= l120)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje))).scalar()
    a60 = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == mun_id)
        .where(ConvenioEstadual.dt_vigencia_atual <= l60)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje))).scalar()
    prest = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == mun_id)
        .where(ConvenioEstadual.dt_vigencia_atual < v90))).scalar()
    # Voluntarias
    vol = await db.execute(text("""
        SELECT dt_fim_vigencia, COALESCE(valor_global, valor_repasse, 0), situacao
        FROM transferegov_propostas WHERE municipio_id = :m
    """), {"m": mun_id})
    vol_rows = vol.fetchall()
    total_vol = len(vol_rows); vol_valor = 0.0; vol_120 = vol_60 = vol_prest = 0
    n_voluntarias = n_rejeitadas = n_geral = 0
    for dtf, val, sit in vol_rows:
        try: vol_valor += float(val or 0)
        except (TypeError, ValueError): pass
        sit_l = (sit or "").lower()
        if "rejeitad" in sit_l:
            n_rejeitadas += 1
        elif "enviado para an" in sit_l and ("lise" in sit_l or "alise" in sit_l):
            n_voluntarias += 1
        else:
            n_geral += 1
        d = None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try: d = datetime.strptime(str(dtf).strip()[:10], fmt).date(); break
            except (ValueError, AttributeError, TypeError): continue
        if d:
            if hoje <= d <= l120:
                vol_120 += 1
                if d <= l60: vol_60 += 1
            elif d < v90:
                vol_prest += 1
    return (
        f"=== {mun.nome}/{mun.uf} (id={mun.id}) ===\n"
        f"ESTADUAL (SIGCON):\n"
        f"  Total convenios: {est_count}\n"
        f"  Valor total: {_fmt_money(float(est_valor or 0))}\n"
        f"  Vencendo em 60d: {a60}\n"
        f"  Vencendo em 120d: {a120}\n"
        f"  Vencidos +90d (prestacao de contas): {prest}\n"
        f"FEDERAL (SICONV - TransfereGov Voluntarias):\n"
        f"  Total propostas: {total_vol}\n"
        f"    - Voluntarias (enviado p/ analise): {n_voluntarias}\n"
        f"    - Geral (em execucao/aprovado/etc): {n_geral}\n"
        f"    - Rejeitadas: {n_rejeitadas}\n"
        f"  Valor total: {_fmt_money(vol_valor)}\n"
        f"  Vencendo em 60d: {vol_60}\n"
        f"  Vencendo em 120d: {vol_120}\n"
        f"  Vencidos +90d (prestacao de contas): {vol_prest}\n"
    )


async def _tool_query_situacoes_sigcon(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    r = await db.execute(
        select(ConvenioEstadual.situacao, func.count())
        .where(ConvenioEstadual.municipio_id == mun_id)
        .where(ConvenioEstadual.situacao.is_not(None))
        .group_by(ConvenioEstadual.situacao)
        .order_by(func.count().desc())
    )
    rows = r.all()
    if not rows:
        return f"Nenhuma situacao encontrada para municipio_id={mun_id}."
    return "Situacoes do SIGCON (municipio_id={}):\n".format(mun_id) + "\n".join(
        f"  {c:>3}x  {s}" for s, c in rows
    )


async def _tool_query_convenios_sigcon(db: AsyncSession, inp: dict) -> str:
    from datetime import timedelta
    mun_id = int(inp["municipio_id"])
    q = select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == mun_id)
    if inp.get("ano"):
        q = q.where(ConvenioEstadual.ano == int(inp["ano"]))
    if inp.get("situacoes"):
        q = q.where(ConvenioEstadual.situacao.in_(inp["situacoes"]))
    if inp.get("search"):
        from sqlalchemy import or_
        term = f"%{inp['search']}%"
        q = q.where(or_(
            ConvenioEstadual.objeto.ilike(term),
            ConvenioEstadual.nr_sigcon.ilike(term),
            ConvenioEstadual.nr_siafi.ilike(term),
            ConvenioEstadual.nr_plano_trabalho.ilike(term),
        ))
    if inp.get("parlamentar"):
        # raw_data->>'responsaveis' tem o parlamentar (SIGCON-MG)
        q = q.where(text("raw_data->>'responsaveis' ILIKE :parl"))
        q = q.params(parl=f"%{inp['parlamentar']}%")
    if inp.get("vigencia"):
        from sqlalchemy import and_
        hoje = date.today()
        v = inp["vigencia"]
        if v == "vence60":
            q = q.where(and_(ConvenioEstadual.dt_vigencia_atual >= hoje,
                             ConvenioEstadual.dt_vigencia_atual <= hoje + timedelta(days=60)))
        elif v == "vence120":
            q = q.where(and_(ConvenioEstadual.dt_vigencia_atual >= hoje,
                             ConvenioEstadual.dt_vigencia_atual <= hoje + timedelta(days=120)))
        elif v == "prestacao":
            q = q.where(ConvenioEstadual.dt_vigencia_atual < hoje - timedelta(days=90))
    limit = min(int(inp.get("limit", 30)), 100)
    q = q.order_by(ConvenioEstadual.dt_publicacao.desc().nullslast()).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return "Nenhum convenio encontrado com os filtros informados."
    out = [f"{len(rows)} convenio(s) SIGCON encontrado(s):"]
    for c in rows:
        raw = c.raw_data if isinstance(c.raw_data, dict) else {}
        instr = raw.get("nr_instrumento") or (c.nr_sigcon if c.nr_sigcon and "/" in c.nr_sigcon else None)
        parl = raw.get("responsaveis") or raw.get("parlamentar") or raw.get("indicacao")
        if isinstance(parl, list):
            parl = ", ".join(str(x) for x in parl if x)
        if isinstance(parl, str):
            parl = parl.replace("�", "").strip()
        out.append(
            f"- {instr or c.nr_sigcon or '(sem nº)'}\n"
            f"  Orgao: {c.orgao_concedente or '-'}\n"
            f"  Objeto: {(c.objeto or '')[:180]}\n"
            f"  Situacao: {c.situacao or '-'} | Ano: {c.ano or '-'}\n"
            f"  Parlamentar: {parl or '-'}\n"
            f"  Valor total: {_fmt_money(c.valor_total)} | Repasse: {_fmt_money(c.valor_concedente)}\n"
            f"  Vigencia: {_fmt_dt(c.dt_vigencia_inicial)} -> {_fmt_dt(c.dt_vigencia_atual or c.dt_vigencia_final)}\n"
            f"  SIAFI: {c.nr_siafi or '-'} | Conta: {c.conta_corrente or '-'}"
        )
    return "\n".join(out)


async def _tool_query_voluntarias(db: AsyncSession, inp: dict) -> str:
    where: list[str] = []
    params: dict = {}
    mun_id = inp.get("municipio_id")
    if mun_id:
        where.append("v.municipio_id = :m"); params["m"] = int(mun_id)
    categoria = inp.get("categoria")
    if categoria == "voluntarias":
        where.append("v.situacao ILIKE :vp"); params["vp"] = _VOL_LIKE
    elif categoria == "rejeitadas":
        where.append("v.situacao ILIKE :rp"); params["rp"] = _REJ_LIKE
    elif categoria == "geral":
        where.append("(v.situacao IS NULL OR (v.situacao NOT ILIKE :vp AND v.situacao NOT ILIKE :rp))")
        params["vp"] = _VOL_LIKE; params["rp"] = _REJ_LIKE
    if inp.get("search"):
        where.append("(v.numero_proposta ILIKE :s OR v.proponente ILIKE :s)"); params["s"] = f"%{inp['search']}%"
    if inp.get("parlamentar"):
        where.append("v.parlamentar ILIKE :parl"); params["parl"] = f"%{inp['parlamentar']}%"
    if inp.get("situacao_contratacao"):
        where.append("v.situacao_contratacao ILIKE :sc"); params["sc"] = f"%{inp['situacao_contratacao']}%"
    limit = min(int(inp.get("limit", 50)), 200)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT v.numero_proposta, v.situacao, v.orgao, v.objeto, v.dt_fim_vigencia,
               v.valor_global, v.valor_repasse, v.valor_contrapartida, v.codigo_instrumento,
               v.parlamentar, v.situacao_contratacao, v.clausula_suspensiva_motivo,
               v.clausula_suspensiva_dt_prevista, v.detalhe->>'Empenhado',
               (SELECT nome FROM municipios WHERE id = v.municipio_id) AS mun
        FROM transferegov_propostas v{where_sql}
        ORDER BY v.municipio_id, v.numero_proposta DESC LIMIT {limit}
    """
    r = await db.execute(text(sql), params)
    rows = r.fetchall()
    escopo = f"municipio_id={mun_id}" if mun_id else "TODOS os 6 municipios"
    if not rows:
        return f"Nenhuma proposta SICONV encontrada ({escopo}, categoria={categoria or 'todas'})."
    out = [f"{len(rows)} proposta(s) SICONV ({escopo}, categoria={categoria or 'todas'}):"]
    for row in rows:
        empenhado = (row[13] or "").strip()
        empenhado = {"sim": "Sim", "não": "Não", "nao": "Não"}.get(empenhado.lower(), empenhado)
        extra = []
        if not mun_id and row[14]:
            extra.append(f"Municipio: {row[14]}")
        if row[9]:
            extra.append(f"Parlamentar: {row[9]}")
        if empenhado:
            extra.append(f"Empenhado: {empenhado}")
        if row[10]:
            extra.append(f"Sit. Contratacao: {row[10]}")
        extra_txt = ("\n  " + " | ".join(extra)) if extra else ""
        # Detalhe da clausula suspensiva (motivo + data prevista), quando houver
        clausula_txt = ""
        if row[11] or row[12]:
            partes = []
            if row[12]:
                partes.append(f"Data prevista p/ resolucao: {_fmt_dt(row[12])}")
            if row[11]:
                partes.append(f"Motivo: {row[11]}")
            clausula_txt = "\n  Clausula Suspensiva -> " + " | ".join(partes)
        out.append(
            f"- N° proposta: {row[0]}{' / Instrumento ' + row[8] if row[8] else ''}\n"
            f"  Orgao: {row[2]}\n"
            f"  Situacao: {row[1]}{extra_txt}{clausula_txt}\n"
            f"  Objeto: {(row[3] or '')[:180]}\n"
            f"  Valores: global {_fmt_money(row[5])} / repasse {_fmt_money(row[6])} / contrap {_fmt_money(row[7])}\n"
            f"  Fim vigencia: {row[4] or '-'}"
        )
    return "\n".join(out)


async def _tool_search_by_parlamentar(db: AsyncSession, inp: dict) -> str:
    """Busca cross-fonte por nome de parlamentar:
       - convenios_estadual.raw_data->>'responsaveis' (SIGCON-MG)
       - transferegov_propostas.parlamentar (SICONV federal)
       - emendas_estaduais.nome_responsavel
       Agrupa por fonte + municipio."""
    nome = (inp.get("nome") or "").strip()
    if not nome or len(nome) < 3:
        return "Erro: informe nome com ao menos 3 caracteres."
    limit_per_source = min(int(inp.get("limit", 50)), 200)
    mun_filter = inp.get("municipio_id")
    out: list[str] = [f"## Busca por parlamentar: \"{nome}\""]
    # 1) Convenios SIGCON estaduais
    sql = """
        SELECT c.id, c.municipio_id, m.nome, c.nr_sigcon, c.objeto, c.situacao,
               c.valor_total, c.raw_data->>'responsaveis' AS responsaveis,
               c.dt_vigencia_atual, c.ano
        FROM convenios_estadual c LEFT JOIN municipios m ON m.id = c.municipio_id
        WHERE c.raw_data->>'responsaveis' ILIKE :n
    """
    params: dict = {"n": f"%{nome}%"}
    if mun_filter:
        sql += " AND c.municipio_id = :mun"
        params["mun"] = int(mun_filter)
    sql += f" ORDER BY c.ano DESC NULLS LAST, c.dt_publicacao DESC NULLS LAST LIMIT {limit_per_source}"
    rows = (await db.execute(text(sql), params)).fetchall()
    out.append(f"\n### SIGCON-MG (estaduais): {len(rows)} resultado(s)")
    for r in rows:
        out.append(
            f"- **{r[3] or '(sem nº)'}** ({r[9] or '-'}) — {r[2]}/{r[1]}\n"
            f"  Responsavel: {r[7]}\n"
            f"  Objeto: {(r[4] or '')[:140]}\n"
            f"  Situacao: {r[5] or '-'} | Valor: {_fmt_money(r[6])} | Vig: {_fmt_dt(r[8])}"
        )

    # 2) Voluntarias SICONV federais
    sql2 = """
        SELECT id, municipio_id, (SELECT nome FROM municipios WHERE id=v.municipio_id) AS mun,
               numero_proposta, codigo_instrumento, objeto, situacao,
               valor_global, parlamentar, situacao_contratacao
        FROM transferegov_propostas v
        WHERE parlamentar ILIKE :n
    """
    params2: dict = {"n": f"%{nome}%"}
    if mun_filter:
        sql2 += " AND municipio_id = :mun"
        params2["mun"] = int(mun_filter)
    sql2 += f" ORDER BY numero_proposta DESC LIMIT {limit_per_source}"
    rows = (await db.execute(text(sql2), params2)).fetchall()
    out.append(f"\n### TransfereGov / SICONV (federais): {len(rows)} resultado(s)")
    for r in rows:
        out.append(
            f"- **{r[4] or r[3]}** — {r[2]}/{r[1]}\n"
            f"  Parlamentar: {r[8]}\n"
            f"  Objeto: {(r[5] or '')[:140]}\n"
            f"  Situacao: {r[6] or '-'} | Sit. Contr.: {r[9] or '-'} | Valor: {_fmt_money(r[7])}"
        )

    # 3) Emendas estaduais (indicacoes SIGCON)
    sql3 = """
        SELECT e.id, e.municipio_id, (SELECT nome FROM municipios WHERE id=e.municipio_id) AS mun,
               e.nr_indicacao, e.ano, e.beneficiario, e.tipo_atendimento,
               e.valor_indicacao, e.nome_responsavel, e.status_indicacao
        FROM emendas_estaduais e
        WHERE e.nome_responsavel ILIKE :n
    """
    params3: dict = {"n": f"%{nome}%"}
    if mun_filter:
        sql3 += " AND e.municipio_id = :mun"
        params3["mun"] = int(mun_filter)
    sql3 += f" ORDER BY e.ano DESC NULLS LAST LIMIT {limit_per_source}"
    rows = (await db.execute(text(sql3), params3)).fetchall()
    out.append(f"\n### Emendas Estaduais (indicacoes): {len(rows)} resultado(s)")
    for r in rows:
        out.append(
            f"- **Indicacao {r[3]}/{r[4] or '?'}** — {r[2]}/{r[1]}\n"
            f"  Responsavel: {r[8]}\n"
            f"  Beneficiario: {r[5] or '-'} | Tipo: {r[6] or '-'}\n"
            f"  Valor: {_fmt_money(r[7])} | Status: {r[9] or '-'}"
        )

    return "\n".join(out)


async def _tool_query_simec_liberacoes(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    where = ["municipio_id = :m"]
    params: dict = {"m": mun_id}
    if inp.get("ano"):
        where.append("ano = :a"); params["a"] = int(inp["ano"])
    if inp.get("programa"):
        where.append("programa ILIKE :p"); params["p"] = f"%{inp['programa']}%"
    sql = f"""
        SELECT programa, dt_pgto, valor, descricao, banco, agencia, conta, ano
        FROM simec_par_liberacoes WHERE {' AND '.join(where)}
        ORDER BY dt_pgto DESC NULLS LAST LIMIT 200
    """
    rows = (await db.execute(text(sql), params)).fetchall()
    if not rows:
        return f"Nenhuma liberacao SIMEC encontrada."
    total = sum(float(r[2] or 0) for r in rows)
    out = [f"{len(rows)} liberacao(oes) SIMEC, total: {_fmt_money(total)}"]
    # Sumario por programa
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0.0])
    for r in rows:
        agg[r[0] or "?"][0] += 1
        agg[r[0] or "?"][1] += float(r[2] or 0)
    out.append("Por programa:")
    for p, (n, v) in sorted(agg.items(), key=lambda x: -x[1][1]):
        out.append(f"  {p}: {n} pagamento(s), {_fmt_money(v)}")
    out.append("Linhas (mais recentes primeiro, ate 50):")
    for r in rows[:50]:
        out.append(
            f"- {_fmt_dt(r[1])} | {r[0]:<10} | {_fmt_money(r[2])} | {(r[3] or '')[:60]} | {r[4] or ''} ag {r[5] or ''} c/c {r[6] or ''}"
        )
    return "\n".join(out)


async def _tool_query_simec_dimensoes(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    r = await db.execute(text("""
        SELECT dimensao, score_4, score_3, score_2, score_1, score_na
        FROM simec_par_dimensoes WHERE municipio_id = :m ORDER BY dimensao
    """), {"m": mun_id})
    rows = r.fetchall()
    if not rows:
        return "Nenhuma dimensao do PAR encontrada (talvez o scraper SIMEC ainda nao rodou)."
    out = ["Sintese do PAR (Plano de Acoes Articuladas):"]
    for row in rows:
        total = sum(int(x or 0) for x in row[1:])
        out.append(
            f"- {row[0]}\n"
            f"  Total indicadores: {total} | Score 4 (bom): {row[1]} | 3 (adequado): {row[2]} | "
            f"2 (a melhorar): {row[3]} | 1 (critico): {row[4]} | N/A: {row[5]}"
        )
    return "\n".join(out)


async def _tool_query_emendas_estaduais(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    where = ["municipio_id = :m"]
    params: dict = {"m": mun_id}
    if inp.get("parlamentar"):
        where.append("nome_responsavel ILIKE :p"); params["p"] = f"%{inp['parlamentar']}%"
    if inp.get("ano"):
        where.append("ano = :a"); params["a"] = int(inp["ano"])
    limit = min(int(inp.get("limit", 30)), 100)
    sql = f"""
        SELECT nr_indicacao, ano, nome_responsavel, beneficiario, tipo_atendimento,
               uo_sigla, valor_indicacao, status_indicacao
        FROM emendas_estaduais WHERE {' AND '.join(where)}
        ORDER BY ano DESC NULLS LAST, nr_indicacao DESC LIMIT {limit}
    """
    rows = (await db.execute(text(sql), params)).fetchall()
    if not rows:
        return "Nenhuma emenda estadual encontrada."
    out = [f"{len(rows)} emenda(s) estadual(is):"]
    for r in rows:
        out.append(
            f"- N° {r[0]}/{r[1]} | Parlamentar: {r[2]}\n"
            f"  Beneficiario: {r[3] or '-'} | Tipo: {r[4] or '-'} | Orgao: {r[5] or '-'}\n"
            f"  Valor: {_fmt_money(r[6])} | Status: {r[7] or '-'}"
        )
    return "\n".join(out)


# Dispatcher
TOOL_FUNCS = {
    "list_municipios": _tool_list_municipios,
    "municipio_summary": _tool_municipio_summary,
    "query_convenios_sigcon": _tool_query_convenios_sigcon,
    "query_situacoes_sigcon": _tool_query_situacoes_sigcon,
    "query_voluntarias": _tool_query_voluntarias,
    "query_simec_liberacoes": _tool_query_simec_liberacoes,
    "query_simec_dimensoes": _tool_query_simec_dimensoes,
    "query_emendas_estaduais": _tool_query_emendas_estaduais,
    "search_by_parlamentar": _tool_search_by_parlamentar,
}


# --------------------------------------------------------------------------
# Endpoint
# --------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    municipio_id: Optional[int] = None
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict[str, Any]]  # logs das ferramentas executadas
    usage: dict[str, Any]


@router.get("/_ping")
async def ping(_=Depends(get_current_user)):
    """Diagnostico: chama Claude com prompt minimo (sem tools, sem DB)."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "anthropic nao instalada")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY ausente")
    client = anthropic.AsyncAnthropic(api_key=api_key)
    try:
        r = await client.messages.create(
            model=MODEL, max_tokens=80,
            messages=[{"role": "user", "content": "Diga 'pong' em uma palavra."}],
        )
        text = next((b.text for b in r.content if b.type == "text"), "")
        return {"ok": True, "model": MODEL, "reply": text,
                "usage": {"in": r.usage.input_tokens, "out": r.usage.output_tokens}}
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Anthropic {e.status_code}: {str(e.message)[:300]}")
    except Exception as e:
        logger.exception("Ping IA falhou")
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}")


async def _run_ai_chat(
    db: AsyncSession,
    message: str,
    history: list,
    municipio_id: int | None = None,
    user_name: str | None = None,
) -> dict:
    """Roda chat com a IA. Reusavel — usado por /chat e pelo bot Telegram.
    Retorna {reply, tool_calls, usage}."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "Biblioteca anthropic nao instalada no servidor.")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY nao configurada no servidor.")

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key)
    except Exception as e:
        logger.exception("Falha criando cliente Anthropic")
        raise HTTPException(503, f"Falha criando cliente IA: {type(e).__name__}: {str(e)[:200]}")

    # Constroi mensagens
    messages: list[dict[str, Any]] = []
    for h in history or []:
        # Aceita objeto ChatMessage (com .role/.content) ou dict {"role","content"}
        role = getattr(h, "role", None) or (h.get("role") if isinstance(h, dict) else None)
        content = getattr(h, "content", None) or (h.get("content") if isinstance(h, dict) else None)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    user_msg = message
    contexto_parts = []
    if municipio_id:
        contexto_parts.append(f"municipio_id={municipio_id}")
    if user_name:
        contexto_parts.append(f"usuario={user_name}")
    if contexto_parts:
        user_msg = f"[contexto: {', '.join(contexto_parts)}]\n\n{user_msg}"
    messages.append({"role": "user", "content": user_msg})

    return await _execute_loop(client, db, messages)


async def _execute_loop(client, db, messages) -> dict:
    """Loop de chamadas IA + tool_use ate end_turn."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "anthropic nao instalada")

    # Cacheia o system prompt + tools (sao estaveis entre requests)
    system = [{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }]

    tool_calls_log: list[dict[str, Any]] = []
    total_in = total_out = cache_read = cache_create = 0
    max_iter = 8

    for iteration in range(max_iter):
        try:
            response = await client.messages.create(
                model=MODEL,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=system,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIStatusError as e:
            logger.error(f"Anthropic API error: {e.status_code} - {e.message}")
            raise HTTPException(502, f"Erro Anthropic ({e.status_code}): {e.message[:200]}")
        except Exception as e:
            logger.exception("Erro na chamada Anthropic")
            raise HTTPException(500, f"Erro IA: {str(e)[:200]}")

        u = response.usage
        total_in += u.input_tokens
        total_out += u.output_tokens
        cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        cache_create += getattr(u, "cache_creation_input_tokens", 0) or 0

        if response.stop_reason == "end_turn":
            # Resposta final
            reply = "".join(b.text for b in response.content if b.type == "text")
            return {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "usage": {
                    "input_tokens": total_in, "output_tokens": total_out,
                    "cache_read": cache_read, "cache_create": cache_create,
                    "iterations": iteration + 1,
                },
            }

        if response.stop_reason != "tool_use":
            # max_tokens, refusal, etc.
            text_out = "".join(b.text for b in response.content if b.type == "text")
            return {
                "reply": text_out or f"(IA parou: {response.stop_reason})",
                "tool_calls": tool_calls_log,
                "usage": {"input_tokens": total_in, "output_tokens": total_out,
                          "cache_read": cache_read, "cache_create": cache_create,
                          "stop_reason": response.stop_reason},
            }

        # Tool use: executa cada ferramenta e devolve resultado
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tname = block.name
                tinput = block.input or {}
                fn = TOOL_FUNCS.get(tname)
                if fn is None:
                    result = f"Erro: ferramenta '{tname}' desconhecida."
                else:
                    try:
                        result = await fn(db, tinput)
                    except Exception as e:
                        logger.exception(f"Erro executando tool {tname}")
                        result = f"Erro executando ferramenta: {str(e)[:200]}"
                tool_calls_log.append({"tool": tname, "input": tinput, "output_preview": result[:200]})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result[:30000],  # cap por seguranca
                })
        messages.append({"role": "user", "content": tool_results})

    raise HTTPException(500, "Loop de IA atingiu limite de iteracoes sem resposta final.")


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_user),
):
    """Chat com a IA. Pode usar ferramentas para consultar o DB."""
    result = await _run_ai_chat(
        db=db,
        message=body.message,
        history=body.history,
        municipio_id=body.municipio_id,
    )
    return ChatResponse(
        reply=result["reply"],
        tool_calls=result.get("tool_calls", []),
        usage=result.get("usage", {}),
    )
