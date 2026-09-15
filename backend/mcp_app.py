"""Servidor MCP de LEITURA do PACTHA — para um assistente de IA (Claude, ChatGPT)
consultar os dados do município com o MESMO alcance do dono do token.

⚠️ SÓ LEITURA. Nenhuma ferramenta escreve, apaga ou dispara coleta. O contrato
inteiro é leitura — é o que permite entregar isto a um modelo externo.

⚠️ CADA FERRAMENTA COMEÇA POR `identidade_do_contexto(ctx)` (o choke point do
§2, em `services/mcp_auth.py`) e passa o município por `escopo_municipios` (o
filtro do §3). Nenhuma ferramenta lê o header nem monta filtro de município por
conta própria. `tests/test_mcp_ferramentas_escopadas.py` falha se uma esquecer.

⚠️ OS NÚMEROS SÃO OS DA TELA. Cada ferramenta REUSA a função que a própria
plataforma usa (`summary_core`, `aggregate_parlamentares`, `fetch_*`…). Um número
que divergir da tela é defeito, não melhoria; a descrição diz a base usada.

Transporte: SDK oficial `mcp` 2.x (Streamable HTTP). ⚠️ Em 2.x o `FastMCP` virou
`MCPServer` — todo exemplo online de `FastMCP` está errado para esta versão.
"""
from __future__ import annotations

import logging

from mcp.server.mcpserver import MCPServer
# ⚠️ Em mcp 2.x o Context injetável é este (mcp.server.mcpserver.context), NÃO o
# mcp.server.context — anotar com o errado faz o SDK tentar gerar JSON schema
# dele e quebrar. `find_context_parameter` injeta por `issubclass(_, Context)`.
from mcp.server.mcpserver.context import Context
from sqlalchemy import text

from starlette.responses import JSONResponse

from database import async_session
from services.mcp_auth import (
    identidade_do_contexto, escopo_municipios, MCPNaoAutenticado,
    verificar_token, definir_usuario, limpar_usuario)

log = logging.getLogger("mcp_app")

INSTRUCOES = (
    "Dados públicos de convênios, emendas, obras e regularidade fiscal dos "
    "municípios que a conta do token pode ver, na plataforma PACTHA. Tudo é "
    "somente leitura e já vem filtrado ao alcance do dono do token — você não "
    "escolhe o município fora dele. Comece por 'listar_municipios' para saber "
    "quais existem e seus ids; passe o 'municipio_id' às demais ferramentas. "
    "Valores em reais (BRL). Quando uma resposta disser 'nada para este filtro', "
    "é ausência de dado, não erro."
)

mcp_server = MCPServer(name="PACTHA", instructions=INSTRUCOES)


# ---------------------------------------------------------------------------
# Formatação — TEXTO legível (§4), não JSON cru
# ---------------------------------------------------------------------------
def _reais(v) -> str:
    """Float → 'R$ 1.234.567,89' (convenção pt-BR), sem depender de locale."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + s


def _num(n) -> str:
    try:
        return f"{int(n or 0):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


async def _um_municipio(user, municipio_id):
    """Interpreta `escopo_municipios` (§3) para as ferramentas de UM município.

    Devolve `(id, None)` quando há exatamente um alvo legítimo, ou
    `(None, mensagem)` explicando por quê não — sempre passando pela ÚNICA função
    de escopo, nunca decidindo aqui.
    """
    ids = escopo_municipios(user, municipio_id)
    if ids == []:
        # Pedido fora do escopo OU escopo vazio. Não revela qual — apenas "nada".
        return None, ("Nenhum município para este filtro: ou está fora do seu "
                      "acesso, ou você não tem municípios atribuídos.")
    if ids is None:
        return None, ("Sua conta enxerga todos os municípios — informe um "
                      "'municipio_id' (use 'listar_municipios' para ver os ids).")
    if len(ids) == 1:
        return ids[0], None
    return None, (f"Sua conta enxerga {len(ids)} municípios — informe um "
                  f"'municipio_id' (use 'listar_municipios' para ver os ids).")


async def _nome_municipio(db, municipio_id) -> str:
    row = (await db.execute(
        text("SELECT nome, uf FROM municipios WHERE id = :m"),
        {"m": municipio_id})).first()
    if not row:
        return f"município {municipio_id}"
    return f"{row[0]}/{row[1]}" if row[1] else str(row[0])


TETO_LISTA = 30  # cap de itens em qualquer listagem (§4)


# ---------------------------------------------------------------------------
# FERRAMENTAS
# ---------------------------------------------------------------------------
@mcp_server.tool(
    name="listar_municipios",
    description=(
        "Lista os municípios que a conta do token pode ver, com o id de cada um. "
        "Use PRIMEIRO: o 'municipio_id' que ela devolve é o que as outras "
        "ferramentas pedem. Não recebe parâmetros. Não cobre municípios fora do "
        "seu acesso (eles simplesmente não aparecem)."),
)
async def listar_municipios(ctx: Context) -> str:
    user = await identidade_do_contexto(ctx)
    ids = escopo_municipios(user, None)  # None = super-admin (todos); [] = nenhum
    async with async_session() as db:
        if ids is None:
            rows = (await db.execute(text(
                "SELECT id, nome, uf FROM municipios WHERE active "
                "ORDER BY nome"))).fetchall()
            alcance = "todos os municípios (conta sem restrição)"
        elif not ids:
            return ("Sua conta não tem nenhum município atribuído — não há o que "
                    "listar. Fale com o administrador para receber acesso.")
        else:
            rows = (await db.execute(text(
                "SELECT id, nome, uf FROM municipios WHERE active AND id = ANY(:ids) "
                "ORDER BY nome"), {"ids": ids})).fetchall()
            alcance = f"{len(rows)} município(s) no seu acesso"
    if not rows:
        return "Nenhum município ativo para o seu acesso."
    linhas = [f"Municípios que você pode consultar — {alcance}:", ""]
    for r in rows[:TETO_LISTA]:
        uf = f"/{r[2]}" if r[2] else ""
        linhas.append(f"  • id {r[0]} — {r[1]}{uf}")
    if len(rows) > TETO_LISTA:
        linhas.append(f"  … e mais {len(rows) - TETO_LISTA} (total {len(rows)}).")
    return "\n".join(linhas)


@mcp_server.tool(
    name="visao_municipio",
    description=(
        "Visão geral de um município: total e valor de convênios ESTADUAIS "
        "(SIGCON-MG / convênios estaduais, exclui saúde FNS), valor de convênios "
        "FEDERAIS (TransfereGov voluntárias), e contagem de prazos de vigência e "
        "de prestação de contas próximos ou vencidos. Valores em reais. Números "
        "idênticos aos do Painel do município (reusa a mesma função "
        "'summary_core'). Requer 'municipio_id' quando você vê mais de um."),
)
async def visao_municipio(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    from routers.municipios import summary_core
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        s = await summary_core(db, mid)
    return "\n".join([
        f"Visão de {nome}:",
        "",
        f"  Convênios estaduais: {_num(s.total_convenios_estadual)} "
        f"({_reais(s.valor_total_estadual)})",
        f"  Convênios federais (voluntárias): {_num(s.total_voluntarias)} "
        f"({_reais(s.valor_total_federal)})",
        f"  Vigências vencendo em até 120 dias: {_num(s.alertas_vigencia)} "
        f"(em até 60 dias: {_num(s.alertas_vigencia_60d)})",
        f"  Prestação de contas vencida (+90 dias): "
        f"{_num(s.alertas_prestacao_contas)} "
        f"(estadual {_num(s.alertas_prestacao_contas_estadual)}, "
        f"federal {_num(s.alertas_prestacao_contas_federal)})",
    ])


@mcp_server.tool(
    name="emendas_parlamentares",
    description=(
        "Ranking de quem destinou recurso a um município, somando TODAS as "
        "fontes (convênios estaduais SIGCON, propostas federais, emendas "
        "estaduais e federais, planos de ação/RP9): por autor, o nº de "
        "lançamentos e o valor total. Reusa a agregação da tela Parlamentares "
        "('aggregate_parlamentares'). Só pessoas por padrão (fundos e prefeitura "
        "entram como 'outro' e ficam de fora). Requer 'municipio_id' quando você "
        "vê mais de um. Valores em reais."),
)
async def emendas_parlamentares(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    from routers.parlamentares import aggregate_parlamentares
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        res = await aggregate_parlamentares(db, municipio_id=mid, tipo="parlamentar")
    itens = res.get("items", [])
    if not itens:
        return f"Nada para este filtro: nenhum parlamentar com recurso em {nome}."
    linhas = [f"Parlamentares que destinaram recurso a {nome} "
              f"({len(itens)} no total), maiores primeiro:", ""]
    for e in itens[:TETO_LISTA]:
        fontes = ", ".join(f"{k}:{v}" for k, v in (e.get("por_fonte") or {}).items() if v)
        linhas.append(
            f"  • {e.get('nome_display')} — {_num(e.get('total_lancamentos'))} "
            f"lançamento(s), {_reais(e.get('valor_total'))}"
            + (f"  [{fontes}]" if fontes else ""))
    if len(itens) > TETO_LISTA:
        linhas.append(f"  … e mais {len(itens) - TETO_LISTA}.")
    return "\n".join(linhas)


@mcp_server.tool(
    name="regularidade",
    description=(
        "Regularidade fiscal de um município: as exigências do CAUC (o que trava "
        "ou libera convênio federal — cada item vem com sua situação: Comprovado, "
        "A Comprovar, Desativado) e a nota CAPAG do Tesouro (capacidade de "
        "pagamento: decide se o município pode tomar crédito com garantia da "
        "União; A e B são boas, C e D restringem). Reusa 'fetch_cauc_situacao' e "
        "'fetch_siconfi'. Não é parecer jurídico. Requer 'municipio_id' quando "
        "você vê mais de um."),
)
async def regularidade(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    from collections import Counter
    from routers.cauc import fetch_cauc_situacao
    from routers.siconfi import fetch_siconfi
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        cauc = await fetch_cauc_situacao(db, mid)
        sic = await fetch_siconfi(db, mid)
    linhas = [f"Regularidade fiscal de {nome}:", ""]
    itens = (cauc or {}).get("itens") or []
    if not itens:
        linhas.append("  CAUC: sem dados coletados para este município.")
    else:
        c = Counter((i.get("situacao") or "?") for i in itens)
        linhas.append(f"  CAUC — {len(itens)} exigência(s): "
                      + ", ".join(f"{v} {k}" for k, v in c.most_common()))
    capag = (sic or {}).get("capag")
    if capag and capag.get("nota"):
        sig = capag.get("significado")
        linhas.append(f"  CAPAG (capacidade de pagamento): nota {capag['nota']}"
                      + (f" — {sig}" if sig else ""))
    else:
        linhas.append("  CAPAG: sem nota publicada no Tesouro.")
    return "\n".join(linhas)


@mcp_server.tool(
    name="obras",
    description=(
        "Obras de um município: SISMOB (obras de saúde financiadas pelo "
        "Ministério da Saúde) e obras federais (Obras.gov/CIPI) — contagem por "
        "situação e valores, em reais. Reusa 'fetch_sismob_obras' e "
        "'fetch_obras_federais'. Contagem zero é estado legítimo (município sem "
        "obra cadastrada), não erro. Requer 'municipio_id' quando você vê mais de "
        "um."),
)
async def obras(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    from routers.sismob import fetch_sismob_obras
    from routers.obrasgov import fetch_obras_federais
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        sm = await fetch_sismob_obras(db, mid)
        og = await fetch_obras_federais(db, mid)
    linhas = [f"Obras de {nome}:", ""]
    if not sm.get("tem_dados"):
        linhas.append("  SISMOB (saúde): sem obra coletada.")
    else:
        t = sm.get("totais") or {}
        linhas.append(
            f"  SISMOB (saúde): {_num(t.get('obras'))} obra(s) — em andamento "
            f"{_num(t.get('vivas'))}, concluídas {_num(t.get('concluidas'))}, "
            f"canceladas {_num(t.get('canceladas'))}; repasse "
            f"{_reais(t.get('repasse_total'))}")
    if not og.get("tem_dados"):
        linhas.append("  Federais (Obras.gov): sem obra coletada.")
    else:
        t = og.get("totais") or {}
        linhas.append(f"  Federais (Obras.gov): {_num(t.get('obras'))} obra(s), "
                      f"valor {_reais(t.get('valor'))}")
    return "\n".join(linhas)


@mcp_server.tool(
    name="fundo_a_fundo",
    description=(
        "Repasses fundo a fundo (planos de ação do Transferegov, saúde e outras "
        "áreas) de um município: nº de planos, valor total, saldo disponível, "
        "custeio × investimento, a decomposição por ORIGEM do recurso (emenda, "
        "repasse específico, voluntário, recursos próprios) e o que as CONTAS "
        "dos planos mostram (saldo, pago a beneficiários, devolvido). Reusa "
        "'fetch_faf_planos'. É o lado dos PLANOS de ação — o repasse consolidado "
        "do FNS por bloco não está aqui. Valores em reais. Requer 'municipio_id' "
        "quando você vê mais de um."),
)
async def fundo_a_fundo(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    from routers.faf_planos import fetch_faf_planos
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        f = await fetch_faf_planos(db, mid)
    if not f.get("tem_dados"):
        return f"Nada para este filtro: {nome} sem planos de fundo a fundo coletados."
    linhas = [
        f"Fundo a fundo (planos de ação) de {nome}:",
        "",
        f"  {_num(f.get('total'))} plano(s) — valor total "
        f"{_reais(f.get('valor_total'))}, saldo disponível "
        f"{_reais(f.get('valor_saldo'))}",
        f"  Custeio {_reais(f.get('valor_custeio'))} · "
        f"Investimento {_reais(f.get('valor_investimento'))}",
    ]
    por = [o for o in (f.get("por_origem") or []) if o.get("valor")]
    if por:
        linhas.append("  Por origem do recurso:")
        for o in por:
            linhas.append(f"    - {o.get('rotulo') or o.get('chave')}: "
                          f"{_reais(o.get('valor'))}")
    # A conta do plano (saldo informado pela fonte, pagamentos identificados no
    # extrato) — somada POR CONTA, porque a mesma conta serve a varios planos.
    ex = f.get("execucao") or {}
    if ex.get("n_contas"):
        linhas.append(
            f"  Nas contas ({_num(ex.get('n_contas'))}): saldo "
            f"{_reais(ex.get('saldo_em_conta'))}, pago a beneficiários "
            f"{_reais(ex.get('pago_a_beneficiarios'))}, devolvido à União "
            f"{_reais(ex.get('devolvido_uniao'))}")
    return "\n".join(linhas)


@mcp_server.tool(
    name="convenios_estaduais",
    description=(
        "Convênios ESTADUAIS de um município (SIGCON-MG e congêneres — NÃO inclui "
        "saúde FNS): total, valor somado e a quebra por situação. Mesma agregação "
        "da tela de Convênios (espelha 'convenio_stats': exclui FNS, conta e soma "
        "'valor_total', agrupa por situação). Valores em reais. Requer "
        "'municipio_id' quando você vê mais de um."),
)
async def convenios_estaduais(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    # ⚠️ O MESMO filtro do convenio_stats: FNS mora na mesma tabela mas não é
    # convênio estadual (fica fora dos KPIs). Só leitura, município vem por bind.
    _sem_fns = "(fonte IS NULL OR fonte NOT ILIKE '%FNS%')"
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        tot = (await db.execute(text(
            f"SELECT count(*), COALESCE(SUM(valor_total), 0) FROM convenios_estadual "
            f"WHERE {_sem_fns} AND municipio_id = :m"), {"m": mid})).first()
        rows = (await db.execute(text(
            f"SELECT COALESCE(situacao, '(sem situação)'), count(*) "
            f"FROM convenios_estadual WHERE {_sem_fns} AND municipio_id = :m "
            f"GROUP BY situacao ORDER BY count(*) DESC"), {"m": mid})).fetchall()
    n = tot[0] if tot else 0
    if not n:
        return f"Nada para este filtro: {nome} sem convênios estaduais."
    linhas = [f"Convênios estaduais de {nome}: {_num(n)} — {_reais(tot[1])}",
              "", "  Por situação:"]
    for sit, c in rows[:TETO_LISTA]:
        linhas.append(f"    - {sit}: {_num(c)}")
    if len(rows) > TETO_LISTA:
        linhas.append(f"    … e mais {len(rows) - TETO_LISTA} situação(ões).")
    return "\n".join(linhas)


@mcp_server.tool(
    name="convenios_federais",
    description=(
        "Convênios/propostas FEDERAIS (TransfereGov voluntárias) de um município, "
        "pela MESMA categorização das telas: Voluntárias/Em execução, Rejeitadas, "
        "Encerradas, Geral — total, valor e contagem por categoria. Reusa a regra "
        "'_CATEGORIA_SQL' do módulo transferegov (a mesma que decide cada aba). "
        "Valores em reais. Requer 'municipio_id' quando você vê mais de um."),
)
async def convenios_federais(ctx: Context, municipio_id: int | None = None) -> str:
    user = await identidade_do_contexto(ctx)
    mid, erro = await _um_municipio(user, municipio_id)
    if erro:
        return erro
    # `_CATEGORIA_SQL` é uma CASE só sobre `situacao` (constante do código, sem
    # entrada do usuário) — a mesma expressão que a tela usa para escolher a aba.
    from routers.transferegov import _CATEGORIA_SQL
    async with async_session() as db:
        nome = await _nome_municipio(db, mid)
        rows = (await db.execute(text(
            f"SELECT {_CATEGORIA_SQL} AS cat, count(*), "
            "COALESCE(SUM(COALESCE(valor_global, valor_repasse, 0)), 0) "
            # So a PREFEITURA (15/09/2026) — ver `services/natureza.py`.
            "FROM transferegov_propostas WHERE municipio_id = :m AND "
            "municipal IS NOT FALSE GROUP BY cat"),
            {"m": mid})).fetchall()
    if not rows:
        return f"Nada para este filtro: {nome} sem propostas federais."
    rot = {"voluntarias": "Voluntárias/Em execução", "rejeitadas": "Rejeitadas",
           "encerradas": "Encerradas", "geral": "Geral"}
    total = sum(r[1] for r in rows)
    valor = sum(float(r[2] or 0) for r in rows)
    linhas = [f"Convênios federais (voluntárias) de {nome}: {_num(total)} — "
              f"{_reais(valor)}", "", "  Por categoria:"]
    for cat, c, v in sorted(rows, key=lambda r: -r[1]):
        linhas.append(f"    - {rot.get(cat, cat)}: {_num(c)} ({_reais(v)})")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Transporte: Starlette app (Streamable HTTP), montado em /api/mcp pelo main.py.
# stateless_http=True: cada chamada é um POST independente que carrega o próprio
# Bearer, então a verificação roda a cada chamada e a revogação é imediata.
# ---------------------------------------------------------------------------
mcp_starlette = mcp_server.streamable_http_app(
    streamable_http_path="/", stateless_http=True)


class _AuthMCP:
    """Gate HTTP do /api/mcp: sem 'Authorization: Bearer <token válido>' → 401,
    ANTES de qualquer protocolo MCP (§7: 'no token → 401'). O 401 é idêntico para
    token ausente, desconhecido, revogado ou de dono inativo — não revela qual.

    Guarda o dono verificado no contextvar (uma verificação por chamada); o choke
    point `identidade_do_contexto` lê de lá. Só age em HTTP; lifespan e outros
    escopos passam direto para o app interno (cujo lifespan o main.py roda).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        raw = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        user = None
        if raw:
            async with async_session() as db:
                user = await verificar_token(db, raw)
        if user is None:
            resp = JSONResponse(
                {"error": "unauthorized",
                 "detail": "Envie 'Authorization: Bearer <token do PACTHA>' válido."},
                status_code=401, headers={"WWW-Authenticate": "Bearer"})
            return await resp(scope, receive, send)
        tok = definir_usuario(user)
        try:
            await self.app(scope, receive, send)
        finally:
            limpar_usuario(tok)


# É ISTO que o main.py monta em /api/mcp. O lifespan roda sobre `mcp_starlette`
# (o app interno), que é quem tem o gerenciador de sessão do transporte.
mcp_asgi = _AuthMCP(mcp_starlette)
