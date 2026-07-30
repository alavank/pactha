"""IA Assistant - Claude consulta o banco de dados PACTHA via tool use.

Endpoint:
  POST /api/ai/chat - recebe pergunta + municipio_id + historico, devolve resposta

Implementacao:
  - Claude Sonnet 5 com adaptive thinking (modelo/effort configuraveis por env)
  - Prompt caching no bloco estatico (tools + system base)
  - Tool use loop manual (Claude pede ferramenta -> backend executa SQL -> repete)
  - RAG estruturado: a "recuperacao" e feita por ferramentas que rodam SQL real
    no banco do PACTHA. Todo numero da resposta vem de uma linha do banco, nunca
    de conhecimento do modelo.

ISOLAMENTO POR CLIENTE/MUNICIPIO (critico):
  O escopo NAO e escolhido pelo modelo. Ele e resolvido no servidor a partir do
  usuario autenticado (`allowed_municipio_ids`) + o municipio selecionado na UI,
  e aplicado em `_aplicar_escopo()` no despacho de TODA ferramenta. Se o modelo
  pedir um municipio fora do escopo, o valor e substituido/descartado antes do
  SQL. Prompt nao e barreira de seguranca; este choke point e.

A chave da API fica em env var ANTHROPIC_API_KEY (secret do Coolify, nao no git).
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from typing import Any, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, func, or_ as _or
from database import get_db
from models import ConvenioEstadual, Municipio
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User

logger = logging.getLogger("ai")

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Padrao das Voluntarias / Rejeitadas (mesmo dos routers/transferegov.py)
_VOL_LIKE = "%enviado para an%lise%"
_REJ_LIKE = "%rejeitad%"

MODEL = os.getenv("PACTHA_AI_MODEL", "claude-opus-5")
# low | medium | high | xhigh | max — profundidade de raciocinio x latencia x custo.
# Decisao do dono do sistema: `max` em tudo, priorizando resultado sobre custo
# (o custo e repassado ao cliente). Medicoes que embasaram a conversa estao em
# docs/ia-benchmarks.md.
AI_EFFORT = os.getenv("PACTHA_AI_EFFORT", "max")
# ATENCAO: em effort `max` o orcamento de max_tokens cobre RACIOCINIO + texto.
# Medido na faixa do dashboard: com 500 o modelo estourou no meio da frase
# (stop_reason=max_tokens, JSON cortado). Teto alto nao custa nada enquanto nao
# e usado; resposta cortada custa a pergunta inteira de novo.
MAX_TOKENS = int(os.getenv("PACTHA_AI_MAX_TOKENS", "32000"))
_CLIENTE = None  # cliente Anthropic reaproveitado (ver _cliente_ia)

SYSTEM_PROMPT = """Voce eh o assistente IA da plataforma PACTHA, que monitora convenios,
emendas e transferencias federais e estaduais de municipios brasileiros. Voce ajuda
gestores e consultores a responderem perguntas e gerarem relatorios sobre lancamentos,
valores, vigencias, parlamentares e situacoes.

REGRA ZERO - ESCOPO (inviolavel):
- Voce so enxerga os dados do escopo declarado no bloco ESCOPO ATUAL desta conversa.
- NUNCA afirme, sugira ou especule nada sobre municipios fora desse escopo, nem sobre
  quantos municipios existem na plataforma. Voce nao tem essa informacao.
- Se perguntarem sobre municipio fora do escopo, responda que voce nao tem acesso aos
  dados dele nesta conta - sem inventar nomes, numeros ou hipoteses.

REGRAS DE OURO (anti-alucinacao):
1. SEMPRE use as ferramentas para obter dados. NUNCA invente numeros, datas, nomes,
   parlamentares, orgaos ou valores. Voce nao tem conhecimento proprio sobre este
   municipio: tudo o que voce sabe veio das ferramentas nesta conversa.
2. Nunca extrapole alem das linhas retornadas. Nao some, projete, estime ou complete
   dados que a ferramenta nao devolveu. Se precisar de um total que nao veio pronto,
   some apenas o que foi listado e diga que o total se refere aos registros listados.
3. Se a ferramenta nao retornar nada, a resposta correta e "nao ha registro de X na
   base do PACTHA para este municipio" - nunca preencha com suposicao, nem atribua o
   vazio a "problema de configuracao/carga" (voce nao tem como saber isso).
4. Diga de qual fonte veio cada bloco de numeros (SIGCON-MG, TransfereGov/SICONV,
   SIMEC PAR, Emendas Estaduais, FNS, Plano de Acao/RP9).
5. Se o resultado vier truncado por limite, avise que a lista foi limitada.
6. Se a pergunta for ampla, faca multiplas consultas com ferramentas diferentes antes
   de responder.
7. Nao responda com conhecimento geral do mundo (noticias, politica, legislacao) como
   se fosse dado do PACTHA. Se a pergunta nao puder ser respondida com os dados da
   plataforma, diga isso claramente.
8. Apresente resultados em portugues, em markdown (tabelas, listas).
9. Valores em R$ no formato brasileiro: R$ 1.234.567,89. Datas em dd/mm/yyyy.
10. Se nao tiver dado suficiente, diga exatamente o que falta em vez de inventar.

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
    chame `query_voluntarias` com `situacao_contratacao`. A resposta ja traz Empenhado
    (Sim/Nao) e, na clausula, o Motivo + Data prevista para resolucao. NUNCA use
    query_situacoes_sigcon para isso (aquilo e estadual e nao tem clausula suspensiva).
- **SIMEC PAR (MEC)**: liberacoes federais de PNAE, PNATE, QUOTA Salario-Educacao,
  PDDE. Tambem tem sintese do diagnostico do PAR por dimensao.
  Use `query_simec_liberacoes` ou `query_simec_dimensoes`.
- **Emendas Estaduais**: indicacoes parlamentares estaduais (SIGCON Pesquisar Emendas).
  Use `query_emendas_estaduais`.
- **FNS (Fundo Nacional de Saude / Ministerio da Saude)**: emendas e recursos
  federais de SAUDE do municipio. **SAO PROPOSTAS FNS — NUNCA chame de "convenio".**
  Sempre se refira a elas como "proposta(s) FNS". Use `query_fns`.
- **Transferencia Especial / Plano de Acao (RP9, "emenda Pix", Federal)**:
  transferencias especiais indicadas por EMENDA PARLAMENTAR INDIVIDUAL, pagas
  direto ao municipio (Ministerio da Fazenda). Cada Plano de Acao tem o codigo +
  AUTOR da emenda (o parlamentar), politica publica, situacao e valores
  (custeio/investimento). Use `query_plano_acao`. Fonte AO VIVO (API nacional),
  nao fica no banco. **CRITICO: a maioria das emendas de DEPUTADO/SENADOR FEDERAL
  chega por AQUI, e NAO nas Voluntarias SICONV.** Em qualquer pergunta sobre
  emendas de parlamentar federal, SEMPRE consulte esta fonte.

BUSCA POR PARLAMENTAR:
- "Qual parlamentar trouxe mais?", ranking, "quem mais destinou", comparacao entre
  parlamentares -> use `ranking_parlamentares`. Ele ja devolve os totais SOMADOS
  pelo banco. NUNCA monte ranking somando listas voce mesmo: e assim que sai
  numero errado.
- Se o usuario perguntar por um parlamentar especifico (deputado/senador), use
  `search_by_parlamentar` — retorna TUDO daquele nome em uma chamada:
  convenios SIGCON, propostas SICONV, emendas estaduais E Planos de Acao /
  Transferencia Especial (RP9). Cross-fonte.
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
- Quando o resultado eh longo, comece com um resumo de 2-3 linhas e depois detalhe.
- NUNCA escreva "TL;DR" nem "TLDR" — e jargao de chatbot e nao cabe aqui. Se for rotular o
  resumo, use "**Resumo:**" ou um heading "## Resumo". Evite tambem "Vamos la", "Claro!",
  "Espero ter ajudado" e afins: escreva como um relatorio tecnico para um gestor publico.
- Valores monetarios SEMPRE como `**R$ 1.234.567,89**` em negrito quando forem totais.

TAMANHO DA RESPOSTA (o usuario espera na tela — resposta gigante demora demais):
- SEMPRE de os agregados primeiro: quantidade total e valor total, calculados sobre TODAS as
  linhas que a ferramenta devolveu. O agregado nunca e cortado.
- Se a ferramenta devolveu MAIS DE 15 registros, NAO liste todos. Liste no maximo 10 — os mais
  relevantes para a pergunta (maior valor, ou vencimento mais proximo) — e feche com a linha:
  "Mostrando 10 de N. Peca 'lista completa' se quiser todos." Nunca omita em silencio.
- Prefira quebrar por situacao/categoria com contagem e subtotal, em vez de repetir linha a linha.
- Se o usuario pedir explicitamente a lista completa, ai sim liste tudo.
- Nao repita na prosa o que ja esta na tabela."""


# --------------------------------------------------------------------------
# Tool definitions (JSON schemas)
# --------------------------------------------------------------------------
TOOLS = [
    {
        "name": "list_municipios",
        "description": "Lista os municipios do SEU ESCOPO com ID e nome (use o ID nas outras ferramentas). Esta e a unica lista de municipios que existe para voce - nao ha outros.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "municipio_summary",
        "description": "Resumo consolidado do municipio: contagem de convenios SIGCON, total de Voluntarias, valor total estadual e federal, alertas de vigencia (60d, 120d) e prestacao de contas (vencidos +90d) ja separados estadual/federal.",
        "input_schema": {
            "type": "object",
            "properties": {"municipio_id": {"type": "integer", "description": "ID do municipio do seu escopo (use list_municipios para descobrir)"}},
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
        "description": "Busca propostas/convenios SICONV (FEDERAL) das Voluntarias. municipio_id e OPCIONAL — sem ele busca em TODO O SEU ESCOPO de uma vez (ideal p/ 'quais em clausula suspensiva'). Categorias: geral (em execucao/aprovados/prestacao), voluntarias (enviado p/ analise), rejeitadas. Retorna orgao, situacao, valores, vigencia, parlamentar, Empenhado (Sim/Nao) e, quando aplicavel, Situacao de Contratacao + Motivo/Data da Clausula Suspensiva. Use situacao_contratacao p/ filtrar 'Clausula Suspensiva' ou 'Liminar Judicial' (isso e FEDERAL — NAO use query_situacoes_sigcon).",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer", "description": "Opcional. Sem ele, busca em todo o seu escopo."},
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
        "description": "Busca UNIFICADA por nome de parlamentar em TODAS as fontes: convenios SIGCON-MG (estaduais, campo responsaveis), propostas SICONV (federais, campo parlamentar), emendas estaduais (nome_responsavel). Use quando o usuario pede 'tudo do deputado X' ou 'convenios indicados por Y'. Retorna agrupado por fonte, sempre limitado ao seu escopo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome ou parte do nome do parlamentar (ex: 'AVELAR', 'EDUARDO AZEVEDO'). Match case-insensitive parcial."},
                "municipio_id": {"type": "integer", "description": "Opcional: filtra um municipio. Sem isso, busca em todo o seu escopo."},
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
    {
        "name": "query_fns",
        "description": "Busca PROPOSTAS do FNS (Fundo Nacional de Saude / Min. Saude) do municipio — emendas e recursos de saude. ATENCAO: sao PROPOSTAS FNS, NUNCA 'convenios'. Tem objeto, situacao (Empenhado/Pago/etc), valor, ano e parlamentar autor da emenda. Use para qualquer pergunta de saude/FNS.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "ano": {"type": "integer", "description": "Filtra por ano"},
                "situacao": {"type": "string", "description": "Filtra situacao (ex: 'Pago', 'Empenhado')"},
                "limit": {"type": "integer", "description": "default 50, max 200"},
            },
            "required": ["municipio_id"],
        },
    },
    {
        "name": "ranking_parlamentares",
        "description": "Ranking dos parlamentares por valor trazido ao municipio, JA SOMADO pelo banco, cruzando SICONV (federal), Emendas Estaduais e RP9/Transferencia Especial. USE SEMPRE que a pergunta for 'qual parlamentar trouxe mais', 'quem mais destinou', ranking ou comparacao entre parlamentares — NUNCA some as listas na mao para responder isso. Para detalhar UM parlamentar especifico, use search_by_parlamentar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "limit": {"type": "integer", "description": "Quantos mostrar (default 15, max 50)"},
            },
            "required": ["municipio_id"],
        },
    },
    {
        "name": "query_plano_acao",
        "description": "Planos de Acao / Transferencia Especial (RP9, 'emenda Pix', FEDERAL) do municipio — transferencias indicadas por emenda parlamentar individual, pagas direto ao municipio. Consulta AO VIVO a API nacional (nao esta no banco). Retorna, por plano: codigo, AUTOR da emenda (parlamentar), politica publica, situacao e valores (custeio/investimento/total). MUITAS emendas de deputado federal vem por aqui — use sempre que a pergunta envolver emenda de parlamentar federal. Filtro opcional por parlamentar/situacao.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "parlamentar": {"type": "string", "description": "Filtra pelo nome do autor da emenda (busca parcial). Ex: 'Luis Tibe', 'Tibe'"},
                "situacao": {"type": "string", "description": "Filtra a situacao do plano (ex: 'CIENTE', 'EM_ANALISE', 'IMPEDIDO')"},
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
# Escopo (isolamento por cliente/municipio) — imposto pelo SERVIDOR
# --------------------------------------------------------------------------
# Ferramentas que exigem um municipio especifico (nao sabem operar em lote).
_TOOLS_REQ_MUN = {
    "municipio_summary", "query_convenios_sigcon", "query_situacoes_sigcon",
    "query_simec_liberacoes", "query_simec_dimensoes", "query_emendas_estaduais",
    "query_fns", "query_plano_acao", "ranking_parlamentares",
}


async def resolver_escopo(db: AsyncSession, user, municipio_id=None) -> list[int]:
    """IDs de municipio que ESTA conversa pode enxergar.

    Regra: parte do que o usuario tem direito (`allowed_municipio_ids`; None = admin,
    todos os ativos) e, se a UI mandou um municipio, estreita para ele. O modelo nunca
    participa dessa decisao."""
    permitidos = getattr(user, "allowed_municipio_ids", None)
    if permitidos is None:
        rows = await db.execute(text("SELECT id FROM municipios WHERE active = true ORDER BY id"))
        escopo = [int(r[0]) for r in rows.fetchall()]
    else:
        escopo = sorted(int(x) for x in permitidos)
    if municipio_id is not None:
        try:
            mid = int(municipio_id)
        except (TypeError, ValueError):
            mid = None
        if mid is not None and mid in escopo:
            return [mid]
    return escopo


def _aplicar_escopo(nome_tool: str, inp: dict, escopo: list[int]) -> dict:
    """Reescreve o input da ferramenta para caber no escopo, ANTES de virar SQL.

    - municipio_id pedido pelo modelo so passa se estiver no escopo;
    - se o modelo omitir e o escopo tiver 1 municipio, injetamos ele;
    - `_escopo_ids` vai sempre junto, para as ferramentas que rodam em lote."""
    limpo = dict(inp or {})
    pedido = limpo.get("municipio_id")
    if pedido is not None:
        try:
            pedido = int(pedido)
        except (TypeError, ValueError):
            pedido = None
    if pedido is not None and pedido in escopo:
        limpo["municipio_id"] = pedido
    elif len(escopo) == 1:
        limpo["municipio_id"] = escopo[0]
    else:
        limpo.pop("municipio_id", None)
    limpo["_escopo_ids"] = list(escopo)
    return limpo


async def _resumo_por_situacao(db: AsyncSession, tabela: str, where: list[str],
                               params: dict, col_valor: str, col_situacao: str) -> str:
    """Agregado calculado NO BANCO, sobre TODAS as linhas que casam com o filtro
    (nao so as que couberam no LIMIT).

    Existe porque o modelo erra contagem: pedindo a lista completa de 48
    propostas FNS ele respondeu "Pago 27 / Empenhado 19" quando o banco diz
    "Pago 33 / Empenhado 13". Somar e contar e trabalho de SQL — o modelo so
    deve citar. Entregamos pronto para ele nao ter o que calcular."""
    filtro = " AND ".join(where)
    sql = (f"SELECT {col_situacao}, count(*), COALESCE(SUM({col_valor}), 0) "
           f"FROM {tabela} WHERE {filtro} GROUP BY {col_situacao} ORDER BY 2 DESC")
    linhas = (await db.execute(text(sql), params)).fetchall()
    if not linhas:
        return "Nenhum registro."
    n = sum(int(r[1]) for r in linhas)
    v = sum(float(r[2] or 0) for r in linhas)
    partes = [f"{(r[0] or 'sem situacao')}: {int(r[1])} ({_fmt_money(float(r[2] or 0))})"
              for r in linhas]
    return (
        "RESUMO CALCULADO NO BANCO — use EXATAMENTE estes numeros e NUNCA conte a lista a mao:\n"
        f"  Total: {n} registro(s) | {_fmt_money(v)}\n"
        f"  Por situacao: {' | '.join(partes)}"
    )


def _ids_do_escopo(inp: dict) -> list[int]:
    """Escopo efetivo de uma ferramenta em lote. Nunca devolve lista vazia sem querer:
    lista vazia significa 'nenhum municipio permitido' e a query nao retorna nada."""
    return [int(x) for x in (inp.get("_escopo_ids") or [])]


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------
async def _tool_list_municipios(db: AsyncSession, inp: dict) -> str:
    ids = _ids_do_escopo(inp)
    if not ids:
        return "Nenhum municipio disponivel no seu escopo."
    r = await db.execute(
        text("SELECT id, nome, uf FROM municipios WHERE active = true AND id = ANY(:ids) ORDER BY nome"),
        {"ids": ids},
    )
    rows = r.fetchall()
    if not rows:
        return "Nenhum municipio disponivel no seu escopo."
    return (
        f"Municipios do seu escopo ({len(rows)}) — esta e a lista completa, nao existem outros:\n"
        + "\n".join(f"- id={row[0]}  {row[1]}/{row[2]}" for row in rows)
    )


async def _tool_municipio_summary(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    # Reusa a logica do router /municipios/{id}/summary
    from datetime import datetime, timedelta
    mun = (await db.execute(select(Municipio).where(Municipio.id == mun_id))).scalar_one_or_none()
    if not mun:
        return f"Erro: municipio_id={mun_id} nao encontrado."
    # SIGCON estadual NAO inclui registros do FNS (saude) — eles moram na mesma
    # tabela mas sao PROPOSTAS FNS, contadas em bloco proprio mais abaixo.
    # Sem este filtro o resumo rotulava proposta FNS como "convenio estadual".
    _nao_fns = _or(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%"))
    est_count = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
                                  .where(ConvenioEstadual.municipio_id == mun_id)
                                  .where(_nao_fns))).scalar()
    est_valor = (await db.execute(select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
                                  .where(ConvenioEstadual.municipio_id == mun_id)
                                  .where(_nao_fns))).scalar()
    fns_count = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
                                  .where(ConvenioEstadual.municipio_id == mun_id)
                                  .where(ConvenioEstadual.fonte.ilike("%FNS%")))).scalar()
    fns_valor = (await db.execute(select(func.coalesce(func.sum(ConvenioEstadual.valor_total), 0))
                                  .where(ConvenioEstadual.municipio_id == mun_id)
                                  .where(ConvenioEstadual.fonte.ilike("%FNS%")))).scalar()
    hoje = date.today()
    l120 = hoje + timedelta(days=120); l60 = hoje + timedelta(days=60); v90 = hoje - timedelta(days=90)
    a120 = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == mun_id).where(_nao_fns)
        .where(ConvenioEstadual.dt_vigencia_atual <= l120)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje))).scalar()
    a60 = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == mun_id).where(_nao_fns)
        .where(ConvenioEstadual.dt_vigencia_atual <= l60)
        .where(ConvenioEstadual.dt_vigencia_atual >= hoje))).scalar()
    prest = (await db.execute(select(func.count()).select_from(ConvenioEstadual)
        .where(ConvenioEstadual.municipio_id == mun_id).where(_nao_fns)
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
        f"FNS (Fundo Nacional de Saude) — PROPOSTAS, nunca chamar de convenio:\n"
        f"  Total propostas FNS: {fns_count}\n"
        f"  Valor total: {_fmt_money(float(fns_valor or 0))}\n"
    )


async def _tool_query_situacoes_sigcon(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    r = await db.execute(
        select(ConvenioEstadual.situacao, func.count())
        .where(ConvenioEstadual.municipio_id == mun_id)
        # Mesmo filtro do query_convenios_sigcon: FNS nao e SIGCON estadual.
        .where(_or(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%")))
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
    # convenios_estadual tambem guarda PROPOSTAS do FNS (fonte=FNS). Aqui e a
    # ferramenta de CONVENIOS SIGCON estaduais -> exclui FNS (sao propostas federais).
    q = q.where(_or(ConvenioEstadual.fonte.is_(None), ~ConvenioEstadual.fonte.ilike("%FNS%")))
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
    else:
        # Sem municipio especifico: varre o escopo permitido — nunca a base inteira.
        where.append("v.municipio_id = ANY(:esc)"); params["esc"] = _ids_do_escopo(inp)
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
    escopo = f"municipio_id={mun_id}" if mun_id else f"escopo municipio_id in {_ids_do_escopo(inp)}"
    if not rows:
        return f"Nenhuma proposta SICONV encontrada ({escopo}, categoria={categoria or 'todas'})."
    resumo = await _resumo_por_situacao(
        db, "transferegov_propostas v", where, params,
        "COALESCE(v.valor_global, v.valor_repasse, 0)", "v.situacao")
    out = [f"SICONV ({escopo}, categoria={categoria or 'todas'})", resumo,
           f"Listando {len(rows)} registro(s):"]
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
          AND (c.fonte IS NULL OR c.fonte NOT ILIKE '%FNS%')
    """
    params: dict = {"n": f"%{nome}%"}
    if mun_filter:
        sql += " AND c.municipio_id = :mun"
        params["mun"] = int(mun_filter)
    else:
        sql += " AND c.municipio_id = ANY(:esc)"
        params["esc"] = _ids_do_escopo(inp)
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
    else:
        sql2 += " AND municipio_id = ANY(:esc)"
        params2["esc"] = _ids_do_escopo(inp)
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
    else:
        sql3 += " AND e.municipio_id = ANY(:esc)"
        params3["esc"] = _ids_do_escopo(inp)
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

    # 4) Planos de Acao / Transferencia Especial (RP9) — AO VIVO, por municipio
    from routers.transferegov import _norm as _tgnorm
    nome_norm = _tgnorm(nome)
    muns_sql = "SELECT id, nome, uf FROM municipios WHERE active = true"
    params_m: dict = {}
    if mun_filter:
        muns_sql += " AND id = :mid"
        params_m["mid"] = int(mun_filter)
    else:
        muns_sql += " AND id = ANY(:esc)"
        params_m["esc"] = _ids_do_escopo(inp)
    muns = (await db.execute(text(muns_sql), params_m)).fetchall()
    pa_rows: list = []
    pa_erro = None
    for m in muns:
        try:
            for p in await _planos_acao_municipio(m):
                if p["autor"] and nome_norm in _tgnorm(p["autor"]):
                    pa_rows.append((m, p))
        except Exception as e:  # fonte ao vivo pode cair; nao derruba as outras
            pa_erro = f"{type(e).__name__}: {str(e)[:80]}"
    if pa_erro and not pa_rows:
        out.append(f"\n### Transferencia Especial / Plano de Acao (RP9): fonte ao vivo indisponivel ({pa_erro})")
    else:
        pa_rows.sort(key=lambda t: t[1]["vtot"], reverse=True)
        out.append(f"\n### Transferencia Especial / Plano de Acao (RP9): {len(pa_rows)} resultado(s)")
        for m, p in pa_rows[:limit_per_source]:
            obj = (p["objeto"] or p["politicas"] or "-")[:140]
            out.append(
                f"- **Plano {p['codigo']}** (emenda {p['emenda'] or '-'}) — {m.nome}/{m.id}\n"
                f"  Parlamentar: {p['autor'] or '-'}\n"
                f"  Objeto/Politica: {obj}\n"
                f"  Situacao: {p['situacao'] or '-'} | Valor: {_fmt_money(p['vtot'])}"
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


async def _tool_query_fns(db: AsyncSession, inp: dict) -> str:
    """Propostas FNS (saude) do municipio — armazenadas em convenios_estadual
    com fonte=FNS. Sao PROPOSTAS, nao convenios."""
    mun_id = int(inp["municipio_id"])
    where = ["municipio_id = :m", "fonte ILIKE '%FNS%'"]
    params: dict = {"m": mun_id}
    if inp.get("ano"):
        where.append("ano = :a"); params["a"] = int(inp["ano"])
    if inp.get("situacao"):
        where.append("situacao ILIKE :s"); params["s"] = f"%{inp['situacao']}%"
    limit = min(int(inp.get("limit", 50)), 200)
    sql = f"""
        SELECT nr_sigcon, objeto, situacao, valor_concedente, ano, orgao_concedente,
               raw_data->>'nu_proposta', raw_data->>'noAutor',
               raw_data->>'parlamentar', raw_data->>'nome_responsavel'
        FROM convenios_estadual WHERE {' AND '.join(where)}
        ORDER BY ano DESC NULLS LAST, valor_concedente DESC NULLS LAST LIMIT {limit}
    """
    rows = (await db.execute(text(sql), params)).fetchall()
    if not rows:
        return "Nenhuma proposta FNS encontrada para este municipio."
    resumo = await _resumo_por_situacao(
        db, "convenios_estadual", where, params, "valor_concedente", "situacao")
    out = [resumo, f"Listando {len(rows)} registro(s):"]
    for r in rows:
        parl = r[7] or r[8] or r[9] or ""
        nprop = r[6] or r[0]
        linha = (
            f"- Proposta FNS {nprop}\n"
            f"  Orgao: {r[5] or 'MS - FNS'} | Ano: {r[4] or '-'}\n"
            f"  Objeto: {(r[1] or '')[:160]}\n"
            f"  Situacao: {r[2] or '-'} | Valor: {_fmt_money(r[3])}"
        )
        if parl:
            linha += f" | Parlamentar: {parl}"
        out.append(linha)
    return "\n".join(out)


def _parse_emenda_autor(codigo_emenda_formatado: str) -> tuple[str, str]:
    """`codigoEmendaFormatado` vem como '<codigo>-<Nome do Parlamentar>'
    (ex: '202141760007-Vilson da Fetaemg'). Retorna (codigo, nome_autor)."""
    s = (codigo_emenda_formatado or "").strip()
    code, sep, autor = s.partition("-")
    return code.strip(), autor.strip()


async def _tool_ranking_parlamentares(db: AsyncSession, inp: dict) -> str:
    """Ranking de parlamentares por valor, JA SOMADO, cruzando as fontes.

    Existe porque o modelo erra somando lista longa a mao: perguntado "qual
    parlamentar trouxe mais recurso", leu as linhas cruas e respondeu que o
    maior era Lincoln Portela — quando o banco diz Julio Delgado com
    R$ 2.270.550,72 so no SICONV contra R$ 592.600,00 de Lincoln Portela.
    Errou nas 3 repeticoes. Somar e trabalho de SQL."""
    mun_id = int(inp["municipio_id"])
    limite = min(int(inp.get("limit", 15)), 50)
    totais: dict[str, dict] = {}

    import unicodedata

    def _chave(nome: str) -> str:
        """Nome sem acento e em caixa alta, so para AGRUPAR.

        O SICONV grava "JULIO DELGADO" e a API do RP9 devolve "Julio Delgado"
        com acento: sem normalizar, o MESMO deputado vira duas linhas e o
        ranking sai errado (aconteceu no primeiro teste desta ferramenta)."""
        n = unicodedata.normalize("NFKD", nome or "")
        return "".join(c for c in n if not unicodedata.combining(c)).upper().strip()

    def _acc(nome: str, fonte: str, valor: float, qtd: int = 1):
        nome = (nome or "").strip()
        if not nome:
            return
        alvo = totais.setdefault(_chave(nome), {"siconv": 0.0, "estaduais": 0.0,
                                                "rp9": 0.0, "qtd": 0, "rotulo": nome})
        alvo[fonte] += float(valor or 0)
        alvo["qtd"] += qtd

    rows = (await db.execute(text(
        "SELECT parlamentar, count(*), COALESCE(SUM(COALESCE(valor_global, valor_repasse, 0)), 0) "
        "FROM transferegov_propostas "
        "WHERE municipio_id = :m AND parlamentar IS NOT NULL AND parlamentar <> '' "
        "GROUP BY parlamentar"), {"m": mun_id})).fetchall()
    for r in rows:
        _acc(r[0], "siconv", r[2], int(r[1]))

    rows = (await db.execute(text(
        "SELECT nome_responsavel, count(*), COALESCE(SUM(valor_indicacao), 0) "
        "FROM emendas_estaduais "
        "WHERE municipio_id = :m AND nome_responsavel IS NOT NULL AND nome_responsavel <> '' "
        "GROUP BY nome_responsavel"), {"m": mun_id})).fetchall()
    for r in rows:
        _acc(r[0], "estaduais", r[2], int(r[1]))

    mun = (await db.execute(select(Municipio).where(Municipio.id == mun_id))).scalar_one_or_none()
    rp9_aviso = ""
    if mun:
        try:
            for p in await _planos_acao_municipio(mun):
                _acc(p.get("autor") or "", "rp9", p.get("vtot") or 0)
        except Exception as e:  # fonte AO VIVO: nao pode derrubar o ranking
            rp9_aviso = (f"\nATENCAO: a fonte RP9 falhou agora ({str(e)[:70]}); "
                         "o ranking abaixo NAO inclui Transferencia Especial — avise o usuario.")

    if not totais:
        return "Nenhum parlamentar identificado nas fontes deste municipio."

    ordenado = sorted(totais.items(),
                      key=lambda kv: kv[1]["siconv"] + kv[1]["estaduais"] + kv[1]["rp9"],
                      reverse=True)
    out = ["RANKING DE PARLAMENTARES — TOTAIS JA SOMADOS PELO BANCO.",
           "Use exatamente estes valores e NAO refaca a soma." + rp9_aviso,
           f"{len(ordenado)} parlamentar(es) identificado(s); mostrando ate {limite}.",
           "Fontes somadas: SICONV (federal), Emendas Estaduais (SIGCON), RP9/Transf. Especial.",
           "Obs.: proposta com varios autores no mesmo campo vira um nome composto — o dado",
           "nao diz como ratear entre eles, entao nao rateie."]
    for nome, v in ordenado[:limite]:
        tot = v["siconv"] + v["estaduais"] + v["rp9"]
        partes = []
        if v["siconv"]:
            partes.append(f"SICONV {_fmt_money(v['siconv'])}")
        if v["estaduais"]:
            partes.append(f"Emendas estaduais {_fmt_money(v['estaduais'])}")
        if v["rp9"]:
            partes.append(f"RP9 {_fmt_money(v['rp9'])}")
        out.append(f"- {v.get('rotulo') or nome}: TOTAL {_fmt_money(tot)}  ({' | '.join(partes)})")
    return "\n".join(out)


async def _planos_acao_municipio(mun) -> list[dict]:
    """Busca AO VIVO os Planos de Acao (Transferencia Especial/RP9) do municipio
    na API nacional (reusa o fetch com cache do router transferegov). Filtra por
    nome do municipio e ja extrai o parlamentar autor do codigo da emenda."""
    from routers.transferegov import _fetch_listagem, _norm as _tgnorm
    items = await _fetch_listagem(mun.uf)
    mn = _tgnorm(mun.nome)
    out = []
    for it in items:
        ben = _tgnorm(it.get("beneficiarioNome") or "")
        if not (mn in ben or ben.endswith(mn)):
            continue
        code, autor = _parse_emenda_autor(it.get("codigoEmendaFormatado") or "")
        out.append({
            "codigo": it.get("planoAcaoCodigo"),
            "autor": autor,
            "emenda": code,
            "situacao": it.get("planoAcaoSituacao") or "",
            "pt": it.get("planoTrabalhoSituacao") or "",
            "politicas": it.get("politicasPublicas") or "",
            "objeto": it.get("objetoDescricao") or "",
            "vcust": float(it.get("valorCusteio") or 0),
            "vinv": float(it.get("valorInvestimento") or 0),
            "vtot": float(it.get("valorTotal") or 0),
        })
    return out


async def _tool_query_plano_acao(db: AsyncSession, inp: dict) -> str:
    mun_id = int(inp["municipio_id"])
    mun = (await db.execute(select(Municipio).where(Municipio.id == mun_id))).scalar_one_or_none()
    if not mun:
        return f"Erro: municipio_id={mun_id} nao encontrado."
    try:
        planos = await _planos_acao_municipio(mun)
    except Exception as e:
        return (f"Erro ao consultar a API de Transferencia Especial (Plano de Acao): "
                f"{type(e).__name__}: {str(e)[:150]}. A fonte e ao vivo; tente de novo em instantes.")
    from routers.transferegov import _norm as _tgnorm
    parl = _tgnorm(inp.get("parlamentar") or "")
    situ = _tgnorm(inp.get("situacao") or "")
    rows = [
        p for p in planos
        if (not parl or parl in _tgnorm(p["autor"]))
        and (not situ or situ in _tgnorm(p["situacao"]))
    ]
    if not rows:
        extra = f" para parlamentar '{inp.get('parlamentar')}'" if inp.get("parlamentar") else ""
        return (f"Nenhum Plano de Acao (Transferencia Especial/RP9){extra} encontrado para "
                f"{mun.nome}. (Foram vistos {len(planos)} plano(s) no total do municipio.)")
    rows.sort(key=lambda r: r["vtot"], reverse=True)
    total = sum(r["vtot"] for r in rows)
    out = [f"{len(rows)} Plano(s) de Acao — Transferencia Especial (RP9/emenda Pix) de "
           f"{mun.nome}/{mun.uf}, total {_fmt_money(total)}:"]
    for r in rows:
        obj = (r["objeto"] or r["politicas"] or "-")[:180]
        autor = r["autor"] or "(sem emenda nominal / institucional)"
        pt = f" | Plano de Trabalho: {r['pt']}" if r["pt"] else ""
        out.append(
            f"- Plano {r['codigo']} | Emenda {r['emenda'] or '-'}\n"
            f"  Parlamentar: {autor}\n"
            f"  Objeto/Politica: {obj}\n"
            f"  Situacao: {r['situacao'] or '-'}{pt}\n"
            f"  Valores: total {_fmt_money(r['vtot'])} "
            f"(custeio {_fmt_money(r['vcust'])} / investimento {_fmt_money(r['vinv'])})"
        )
    return "\n".join(out)


# Dispatcher
# Rotulos exibidos ao usuario enquanto a ferramenta roda. Escritos por nos a
# partir do nome da tool que REALMENTE vai executar — nunca progresso inventado.
_ROTULO_TOOL = {
    "list_municipios": "Conferindo os municipios do escopo",
    "municipio_summary": "Levantando o resumo do municipio",
    "query_convenios_sigcon": "Consultando convenios estaduais (SIGCON-MG)",
    "query_situacoes_sigcon": "Verificando as situacoes dos convenios estaduais",
    "query_voluntarias": "Consultando propostas federais (TransfereGov/SICONV)",
    "search_by_parlamentar": "Buscando o parlamentar em todas as fontes",
    "query_simec_liberacoes": "Consultando liberacoes do MEC (SIMEC PAR)",
    "query_simec_dimensoes": "Consultando o diagnostico do PAR",
    "query_emendas_estaduais": "Consultando emendas estaduais",
    "query_fns": "Consultando propostas do FNS (saude)",
    "query_plano_acao": "Consultando Transferencias Especiais (RP9)",
    "ranking_parlamentares": "Montando o ranking de parlamentares",
}

TOOL_FUNCS = {
    "list_municipios": _tool_list_municipios,
    "municipio_summary": _tool_municipio_summary,
    "query_convenios_sigcon": _tool_query_convenios_sigcon,
    "query_situacoes_sigcon": _tool_query_situacoes_sigcon,
    "query_voluntarias": _tool_query_voluntarias,
    "query_simec_liberacoes": _tool_query_simec_liberacoes,
    "query_simec_dimensoes": _tool_query_simec_dimensoes,
    "query_emendas_estaduais": _tool_query_emendas_estaduais,
    "query_fns": _tool_query_fns,
    "query_plano_acao": _tool_query_plano_acao,
    "search_by_parlamentar": _tool_search_by_parlamentar,
    "ranking_parlamentares": _tool_ranking_parlamentares,
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
    # Conversa a continuar. E so uma sugestao do cliente: o servidor confere a
    # posse e, se o id nao for do usuario, abre uma conversa nova.
    conversa_id: Optional[int] = None


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


async def _escopo_por_user_id(db: AsyncSession, user_id) -> list[int]:
    """Escopo de um usuario a partir do id (usado pelo bot do Telegram, que nao
    passa pelo Depends de autenticacao HTTP). Mesma regra do load_user_scopes."""
    row = (await db.execute(text("SELECT role FROM users WHERE id = :u"), {"u": user_id})).first()
    if row and row[0] == "admin":
        rows = await db.execute(text("SELECT id FROM municipios WHERE active = true ORDER BY id"))
        return [int(r[0]) for r in rows.fetchall()]
    rows = await db.execute(
        text("SELECT municipio_id FROM user_municipios WHERE user_id = :u ORDER BY municipio_id"),
        {"u": user_id})
    return [int(r[0]) for r in rows.fetchall()]


async def _rotulos_escopo(db: AsyncSession, escopo: list[int]) -> str:
    """Texto 'Monte Siao/MG (id=1)' para o bloco ESCOPO ATUAL do system prompt."""
    if not escopo:
        return "(nenhum municipio — voce nao pode responder nada com dados)"
    rows = (await db.execute(
        text("SELECT id, nome, uf FROM municipios WHERE id = ANY(:ids) ORDER BY nome"),
        {"ids": escopo})).fetchall()
    if not rows:
        return "(nenhum municipio — voce nao pode responder nada com dados)"
    return "; ".join(f"{r[1]}/{r[2]} (id={r[0]})" for r in rows)


async def _run_ai_chat(
    db: AsyncSession,
    message: str,
    history: list,
    municipio_id: int | None = None,
    user_name: str | None = None,
    escopo: list[int] | None = None,
    user_id: int | None = None,
) -> dict:
    """Roda chat com a IA. Reusavel — usado por /chat e pelo bot Telegram.
    Retorna {reply, tool_calls, usage}.

    `escopo` e a lista de municipio_id que ESTA conversa pode ver. Quem chama
    DEVE fornece-la (ou `user_id`, para derivarmos). Sem nenhum dos dois nao ha
    como garantir isolamento, entao a chamada e recusada."""
    client = _cliente_ia()

    # Escopo: nunca deduzido do que o modelo pede.
    if escopo is None:
        if user_id is not None:
            escopo = await _escopo_por_user_id(db, user_id)
            if municipio_id is not None and int(municipio_id) in escopo:
                escopo = [int(municipio_id)]
        else:
            raise HTTPException(500, "Escopo da IA nao resolvido (chamada sem escopo/user_id).")
    escopo = [int(x) for x in escopo]

    # Constroi mensagens
    messages: list[dict[str, Any]] = []
    for h in history or []:
        # Aceita objeto ChatMessage (com .role/.content) ou dict {"role","content"}
        role = getattr(h, "role", None) or (h.get("role") if isinstance(h, dict) else None)
        content = getattr(h, "content", None) or (h.get("content") if isinstance(h, dict) else None)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    user_msg = message
    if user_name:
        user_msg = f"[usuario={user_name}]\n\n{user_msg}"
    messages.append({"role": "user", "content": user_msg})

    escopo_txt = await _rotulos_escopo(db, escopo)
    return await _execute_loop(client, db, messages, escopo, escopo_txt)


def _cliente_ia():
    """Cliente Anthropic reaproveitado entre requisicoes.

    Antes era criado a cada pergunta, e cada criacao refaz handshake TLS com a
    API — latencia pura, sem nada em troca. O SDK e async-safe e mantem pool de
    conexoes, entao um por processo e o certo."""
    global _CLIENTE
    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "Biblioteca anthropic nao instalada no servidor.")
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY nao configurada no servidor.")
    if _CLIENTE is None or getattr(_CLIENTE, "_pactha_key", None) != api_key:
        _CLIENTE = anthropic.AsyncAnthropic(api_key=api_key)
        _CLIENTE._pactha_key = api_key  # rotacionar a env recria o cliente
    return _CLIENTE


def _marcar_cache_no_fim(messages: list) -> None:
    """Move o breakpoint de cache para o fim do historico (janela deslizante).

    O cache da Anthropic e casamento de PREFIXO: o breakpoint diz ate onde
    guardar. Marcando sempre o ultimo bloco, cada passo do loop reaproveita tudo
    o que ja foi processado antes (prompt fixo + ferramentas ja executadas) e so
    paga preco cheio pelo pedaco novo.

    Tiramos a marca anterior porque a API aceita no maximo 4 breakpoints por
    requisicao e o loop pode dar ate 8 voltas. Remover nao invalida nada: os
    BYTES do prefixo continuam iguais, muda so onde o corte e declarado."""
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            for bloco in c:
                if isinstance(bloco, dict):
                    bloco.pop("cache_control", None)
    if not messages:
        return
    ultimo = messages[-1]
    c = ultimo.get("content")
    if isinstance(c, str):
        # Normaliza para lista para poder carimbar o bloco.
        ultimo["content"] = [{"type": "text", "text": c,
                              "cache_control": {"type": "ephemeral"}}]
    elif isinstance(c, list) and c and isinstance(c[-1], dict):
        c[-1]["cache_control"] = {"type": "ephemeral"}


async def _loop_eventos(client, db, messages, escopo: list[int], escopo_txt: str,
                        streaming: bool = False):
    """Loop de chamadas IA + tool_use ate end_turn, preso ao `escopo`.

    Gerador de eventos — UMA implementacao para os dois endpoints:
      ("etapa", {...})  ferramenta que vai rodar (so no modo streaming)
      ("texto", {...})  pedaco de texto recem-gerado (so no modo streaming)
      ("fim",   {...})  reply + tool_calls + usage

    O /chat normal consome isto e devolve o dict de sempre; o /chat/stream
    repassa como SSE. Ter uma implementacao so importa porque e aqui que mora
    o choke point de escopo: duplicar o loop seria duplicar a barreira."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(503, "anthropic nao instalada")

    # Bloco 1 = estatico (tools + regras): e o que fica em cache entre requests.
    # Bloco 2 = escopo desta conversa; fica DEPOIS do breakpoint para nao
    # invalidar o cache quando o municipio muda.
    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": (
                f"ESCOPO ATUAL desta conversa: {escopo_txt}.\n"
                "Voce so tem dados destes municipios. As ferramentas ja estao presas a esse "
                "escopo pelo servidor: pedir outro municipio nao funciona e nao deve ser tentado. "
                "Nao mencione, compare nem especule sobre nenhum municipio fora desta lista, "
                "e nunca diga quantos municipios a plataforma atende."
            ),
        },
    ]

    tool_calls_log: list[dict[str, Any]] = []
    total_in = total_out = cache_read = cache_create = 0
    max_iter = 8

    import asyncio as _asyncio

    for iteration in range(max_iter):
        # Cache tambem do HISTORICO, nao so do prompt fixo. Sem isto, cada passo
        # do loop reenvia os resultados de ferramenta ja processados pagando
        # preco cheio de novo — e sao eles que pesam numa pergunta que cruza
        # varias fontes (medi uma que custou US$ 0,40, quase tudo entrada).
        _marcar_cache_no_fim(messages)
        # Retry com backoff p/ erros transitorios de sobrecarga (529 Overloaded,
        # 503, 500, 429). A API da Anthropic devolve 529 quando esta saturada —
        # antes isso virava 502 na cara do usuario. Agora tentamos ate 3x.
        response = None
        last_err = None
        kwargs = dict(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": AI_EFFORT},
            system=system,
            tools=TOOLS,
            messages=messages,
        )
        for attempt in range(4):
            emitiu_texto = False
            try:
                if streaming:
                    # Mesma requisicao, mesmos tokens — muda so a entrega.
                    async with client.messages.stream(**kwargs) as fluxo:
                        async for ev in fluxo:
                            if (ev.type == "content_block_delta"
                                    and getattr(ev.delta, "type", "") == "text_delta"):
                                emitiu_texto = True
                                yield ("texto", {"t": ev.delta.text})
                        response = await fluxo.get_final_message()
                else:
                    response = await client.messages.create(**kwargs)
                break
            except anthropic.APIStatusError as e:
                last_err = e
                # Nao repete se ja mostramos texto na tela: o retry reescreveria
                # a resposta do zero e o usuario veria o texto duplicado.
                if (e.status_code in (429, 500, 503, 529) and attempt < 3
                        and not emitiu_texto):
                    logger.warning(f"Anthropic {e.status_code} (sobrecarga) — retry {attempt+1}/3")
                    await _asyncio.sleep(1.5 * (2 ** attempt))  # 1.5s, 3s, 6s
                    continue
                logger.error(f"Anthropic API error: {e.status_code} - {e.message}")
                raise HTTPException(502, f"Erro Anthropic ({e.status_code}): {e.message[:200]}")
            except Exception as e:
                logger.exception("Erro na chamada Anthropic")
                raise HTTPException(500, f"Erro IA: {str(e)[:200]}")
        if response is None:
            sc = getattr(last_err, "status_code", "?")
            raise HTTPException(503, f"IA temporariamente sobrecarregada ({sc}). Tente de novo em instantes.")

        u = response.usage
        total_in += u.input_tokens
        total_out += u.output_tokens
        cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        cache_create += getattr(u, "cache_creation_input_tokens", 0) or 0

        if response.stop_reason == "end_turn":
            # Resposta final
            reply = "".join(b.text for b in response.content if b.type == "text")
            yield ("fim", {
                "reply": reply,
                "tool_calls": tool_calls_log,
                "usage": {
                    "input_tokens": total_in, "output_tokens": total_out,
                    "cache_read": cache_read, "cache_create": cache_create,
                    "iterations": iteration + 1,
                },
            })
            return

        if response.stop_reason != "tool_use":
            # max_tokens, refusal, etc.
            text_out = "".join(b.text for b in response.content if b.type == "text")
            yield ("fim", {
                "reply": text_out or f"(IA parou: {response.stop_reason})",
                "tool_calls": tool_calls_log,
                "usage": {"input_tokens": total_in, "output_tokens": total_out,
                          "cache_read": cache_read, "cache_create": cache_create,
                          "stop_reason": response.stop_reason},
            })
            return

        # Tool use: executa cada ferramenta e devolve resultado
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tname = block.name
                tinput = block.input or {}
                fn = TOOL_FUNCS.get(tname)
                # CHOKE POINT DE ISOLAMENTO: o input do modelo so vira SQL depois
                # de ser reescrito para caber no escopo do usuario autenticado.
                tinput_seguro = _aplicar_escopo(tname, tinput, escopo)
                if streaming:
                    # Rotulo escrito por NOS a partir do nome da ferramenta que
                    # de fato vai rodar — nao passa pelo modelo, nao custa token,
                    # e nunca anuncia uma consulta que nao aconteceu.
                    yield ("etapa", {"tool": tname,
                                     "rotulo": _ROTULO_TOOL.get(tname, "Consultando a base")})
                if fn is None:
                    result = f"Erro: ferramenta '{tname}' desconhecida."
                elif tname in _TOOLS_REQ_MUN and tinput_seguro.get("municipio_id") is None:
                    result = (
                        "Erro: informe um municipio_id do seu escopo. "
                        f"Permitidos: {escopo}."
                    )
                else:
                    try:
                        result = await fn(db, tinput_seguro)
                    except Exception as e:
                        logger.exception(f"Erro executando tool {tname}")
                        # Sem este rollback a transacao fica ABORTADA e TODA
                        # ferramenta seguinte falha em cascata — e o modelo,
                        # vendo consulta vazia, responde "nao ha registro" com
                        # 200 OK. Ou seja: vira dado errado silencioso, que e
                        # pior que um erro visivel. (main.py:139 ja fazia isso.)
                        try:
                            await db.rollback()
                        except Exception:
                            logger.exception("Falha no rollback apos erro de tool")
                        result = f"Erro executando ferramenta: {str(e)[:200]}"
                # Log mostra o input JA sanitizado (e o que de fato rodou).
                log_input = {k: v for k, v in tinput_seguro.items() if k != "_escopo_ids"}
                tool_calls_log.append({"tool": tname, "input": log_input, "output_preview": result[:200]})
                # Cap de seguranca. Cortar em silencio e perigoso: o cabecalho do
                # resultado ja anunciou "N registros" e o corte some com parte
                # deles, entao o modelo somaria em cima de uma lista incompleta
                # achando que esta completa. Avisamos explicitamente.
                if len(result) > 30000:
                    conteudo = (
                        result[:30000]
                        + "\n\n[ATENCAO: resultado truncado pelo servidor. A lista acima esta"
                          " INCOMPLETA — nao some nem conte em cima dela. Use os totais que a"
                          " propria ferramenta informou no cabecalho, e diga ao usuario que a"
                          " listagem foi cortada e que ele pode refinar o filtro.]"
                    )
                else:
                    conteudo = result
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": conteudo,
                })
        messages.append({"role": "user", "content": tool_results})

    # Estourou o limite de iteracoes. Antes isto virava 500 e jogava fora TODO o
    # trabalho ja feito (varias consultas pagas). Melhor devolver o que temos e
    # dizer a verdade ao usuario.
    logger.warning("Loop de IA atingiu %d iteracoes sem resposta final", max_iter)
    yield ("fim", {
        "reply": ("Consultei varias fontes, mas nao consegui fechar a resposta dentro do "
                  "limite de passos. Tente uma pergunta mais especifica (por exemplo, "
                  "restringindo a uma fonte ou a um ano). As consultas que fiz estao "
                  "listadas abaixo."),
        "tool_calls": tool_calls_log,
        "usage": {"input_tokens": total_in, "output_tokens": total_out,
                  "cache_read": cache_read, "cache_create": cache_create,
                  "iterations": max_iter, "stop_reason": "max_iteracoes"},
    })


async def _execute_loop(client, db, messages, escopo: list[int], escopo_txt: str) -> dict:
    """Modo nao-streaming (/chat e bot do Telegram): consome o gerador e
    devolve o dict de sempre.

    Por baixo usa streaming=True DE PROPOSITO. Com max_tokens alto — necessario
    em effort `max`, onde o orcamento cobre raciocinio + texto — o SDK RECUSA a
    chamada nao-streaming ("Streaming is required for operations that may take
    longer than 10 minutes"). Streamar por dentro e descartar os pedacos mantem
    a assinatura e a saida identicas as de antes."""
    final: dict = {}
    async for tipo, dado in _loop_eventos(client, db, messages, escopo, escopo_txt,
                                          streaming=True):
        if tipo == "fim":
            final = dado
    if not final:
        raise HTTPException(500, "IA nao produziu resposta.")
    return final


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Chat com a IA. Pode usar ferramentas para consultar o DB."""
    ensure_municipio_access(current, body.municipio_id)
    ensure_tela(current, "ai")
    escopo = await resolver_escopo(db, current, body.municipio_id)
    if not escopo:
        raise HTTPException(403, "Sua conta nao tem municipio atribuido.")
    result = await _run_ai_chat(
        db=db,
        message=body.message,
        history=body.history,
        municipio_id=body.municipio_id,
        escopo=escopo,
    )
    return ChatResponse(
        reply=result["reply"],
        tool_calls=result.get("tool_calls", []),
        usage=result.get("usage", {}),
    )


# --------------------------------------------------------------------------
# Historico de conversas — por usuario, retencao de 30 dias
# --------------------------------------------------------------------------
RETENCAO_DIAS = 30
_ultimo_expurgo: dict[str, Any] = {"em": None}


async def _expurgar_antigas(db: AsyncSession, forcar: bool = False) -> int:
    """Apaga DEFINITIVAMENTE conversas com mais de RETENCAO_DIAS.

    Roda no boot e tambem de forma preguicosa quando alguem abre o painel — a
    tela promete "apagadas apos 30 dias", entao a promessa nao pode depender de
    a API ter reiniciado. Throttle de 1h por processo p/ nao repetir o DELETE a
    cada clique."""
    from datetime import datetime, timedelta, timezone
    agora = datetime.now(timezone.utc)
    if not forcar:
        ant = _ultimo_expurgo.get("em")
        if ant and (agora - ant) < timedelta(hours=1):
            return 0
    _ultimo_expurgo["em"] = agora
    r = await db.execute(text(
        "DELETE FROM ai_conversas "
        "WHERE criado_em < NOW() - make_interval(days => :d) RETURNING id"
    ), {"d": RETENCAO_DIAS})
    n = len(r.fetchall())
    await db.commit()
    if n:
        logger.info("Expurgo do historico da IA: %d conversa(s) com mais de %d dias",
                    n, RETENCAO_DIAS)
    return n


async def _salvar_mensagem(db: AsyncSession, conversa_id: int, role: str,
                           conteudo: str, tool_calls=None) -> None:
    await db.execute(text(
        "INSERT INTO ai_mensagens (conversa_id, role, conteudo, tool_calls) "
        "VALUES (:c, :r, :t, CAST(:tc AS JSONB))"
    ), {"c": conversa_id, "r": role, "t": conteudo,
        "tc": json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None})
    await db.execute(text(
        "UPDATE ai_conversas SET atualizado_em = NOW() WHERE id = :c"), {"c": conversa_id})
    await db.commit()


async def _abrir_conversa(db: AsyncSession, user_id: int, conversa_id: Optional[int],
                          municipio_id: Optional[int], primeira_pergunta: str) -> int:
    """Id da conversa a usar. Se veio um id, CONFIRMA que e do usuario — id de
    outra pessoa e tratado como inexistente (abre uma nova), nunca como acesso
    concedido."""
    if conversa_id:
        dono = (await db.execute(text(
            "SELECT id FROM ai_conversas WHERE id = :i AND user_id = :u"),
            {"i": conversa_id, "u": user_id})).first()
        if dono:
            return int(dono[0])
    titulo = (primeira_pergunta or "Nova conversa").strip().replace("\n", " ")[:90]
    novo = (await db.execute(text(
        "INSERT INTO ai_conversas (user_id, municipio_id, titulo) "
        "VALUES (:u, :m, :t) RETURNING id"),
        {"u": user_id, "m": municipio_id, "t": titulo})).first()
    await db.commit()
    return int(novo[0])


@router.get("/conversas")
async def listar_conversas(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Conversas DO USUARIO LOGADO. Nao existe rota que devolva a de outro."""
    ensure_tela(current, "ai")
    await _expurgar_antigas(db)
    rows = (await db.execute(text(
        "SELECT id, titulo, atualizado_em, criado_em FROM ai_conversas "
        "WHERE user_id = :u ORDER BY atualizado_em DESC LIMIT 100"
    ), {"u": current.id})).fetchall()
    return {
        "retencao_dias": RETENCAO_DIAS,
        "conversas": [
            {"id": r[0], "titulo": r[1],
             "atualizado_em": r[2].isoformat() if r[2] else None,
             "criado_em": r[3].isoformat() if r[3] else None}
            for r in rows
        ],
    }


@router.get("/conversas/{conversa_id}")
async def abrir_conversa(
    conversa_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_tela(current, "ai")
    dono = (await db.execute(text(
        "SELECT id FROM ai_conversas WHERE id = :i AND user_id = :u"),
        {"i": conversa_id, "u": current.id})).first()
    if not dono:
        # 404 e nao 403 de proposito: quem nao e dono nem descobre que existe.
        raise HTTPException(404, "Conversa nao encontrada.")
    rows = (await db.execute(text(
        "SELECT role, conteudo, tool_calls FROM ai_mensagens "
        "WHERE conversa_id = :c ORDER BY id"), {"c": conversa_id})).fetchall()
    return {"id": conversa_id, "mensagens": [
        {"role": r[0], "content": r[1], "tool_calls": r[2]} for r in rows]}


@router.delete("/conversas/{conversa_id}")
async def apagar_conversa(
    conversa_id: int,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    ensure_tela(current, "ai")
    r = await db.execute(text(
        "DELETE FROM ai_conversas WHERE id = :i AND user_id = :u RETURNING id"),
        {"i": conversa_id, "u": current.id})
    if not r.first():
        raise HTTPException(404, "Conversa nao encontrada.")
    await db.commit()
    return {"ok": True}


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Mesma coisa do /chat, entregue como SSE enquanto e gerada.

    Custo identico ao /chat: mesma requisicao, mesmos tokens. Muda so a entrega.
    Efeito colateral util: como os bytes fluem sem parar, o timeout de
    inatividade do proxy do Next deixa de ser um risco."""
    ensure_municipio_access(current, body.municipio_id)
    ensure_tela(current, "ai")
    escopo = await resolver_escopo(db, current, body.municipio_id)
    if not escopo:
        raise HTTPException(403, "Sua conta nao tem municipio atribuido.")

    client = _cliente_ia()

    messages: list[dict[str, Any]] = []
    for h in body.history or []:
        role = getattr(h, "role", None)
        content = getattr(h, "content", None)
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": body.message})
    escopo_txt = await _rotulos_escopo(db, escopo)

    # Historico: a conversa e sempre do usuario do token. `conversa_id` vindo do
    # cliente e apenas uma sugestao — _abrir_conversa confere a posse.
    conversa_id = await _abrir_conversa(
        db, current.id, body.conversa_id, body.municipio_id, body.message)
    await _salvar_mensagem(db, conversa_id, "user", body.message)

    def _sse(evento: str, dado: dict) -> str:
        # json.dumps e obrigatorio: `data:` do SSE nao aceita quebra de linha
        # crua, e a resposta e markdown cheio de \n.
        return f"event: {evento}\ndata: {json.dumps(dado, ensure_ascii=False)}\n\n"

    async def gerar():
        try:
            async for tipo, dado in _loop_eventos(client, db, messages, escopo,
                                                  escopo_txt, streaming=True):
                if tipo == "fim":
                    dado = {**dado, "conversa_id": conversa_id}
                    try:
                        await _salvar_mensagem(db, conversa_id, "assistant",
                                               dado.get("reply", ""),
                                               dado.get("tool_calls"))
                    except Exception:
                        # Nao derruba a resposta ja gerada por causa do historico.
                        logger.exception("Falha salvando mensagem no historico")
                yield _sse(tipo, dado)
        except HTTPException as e:
            yield _sse("erro", {"detail": str(e.detail)})
        except asyncio.CancelledError:
            # Usuario fechou a aba: paramos de gerar (e de pagar) na hora.
            logger.info("Streaming da IA cancelado pelo cliente")
            raise
        except Exception as e:
            logger.exception("Erro no streaming da IA")
            yield _sse("erro", {"detail": f"Erro interno ({type(e).__name__})."})

    return StreamingResponse(
        gerar(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # impede bufferizacao em proxies estilo nginx
            "Connection": "keep-alive",
        },
    )
