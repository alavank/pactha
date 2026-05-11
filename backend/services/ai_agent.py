"""
PACTA IA - agente conversacional Claude com tool_use sobre os dados do banco.

Usuario faz pergunta em linguagem natural ("Quanto Bom Despacho recebeu em emendas
do Luis Tibe?", "Quais convenios estao vencendo?", etc.) e o Claude:
1. Decide qual tool chamar (query_emendas, query_convenios, etc.)
2. Recebe o resultado JSON
3. Sintetiza a resposta em PT-BR

Usa prompt caching no system para reduzir custo de chamadas frequentes.
"""
import os
import json
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# Definicao das ferramentas que o Claude pode invocar
TOOLS = [
    {
        "name": "query_emendas",
        "description": "Lista emendas parlamentares por municipio. Use quando o usuario perguntar sobre emendas, repasses, valores indicados por deputados, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer", "description": "ID do municipio (1=Araujos, 2=Nova Serrana, 3=Bom Despacho, 4=Sao Tiago, 5=Toledo, 6=Piracema)"},
                "parlamentar_nome": {"type": "string", "description": "Filtro opcional por nome (ex: 'Luis Tibe', 'Domingos Savio')"},
                "ano_inicio": {"type": "integer", "description": "Ano inicial (ex: 2022)"},
                "ano_fim": {"type": "integer", "description": "Ano final (ex: 2026)"},
                "limit": {"type": "integer", "default": 30}
            },
            "required": ["municipio_id"]
        }
    },
    {
        "name": "query_convenios",
        "description": "Lista convenios federais ou estaduais de um municipio. Use para perguntas sobre status, valores, vigencia de convenios.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "esfera": {"type": "string", "enum": ["federal", "estadual", "todos"], "default": "todos"},
                "situacao_filtro": {"type": "string", "description": "Filtro parcial em situacao (ex: 'vigor', 'concluido')"},
                "vigencia_dias_max": {"type": "integer", "description": "So convenios vencendo em N dias"},
                "limit": {"type": "integer", "default": 30}
            },
            "required": ["municipio_id"]
        }
    },
    {
        "name": "query_pendencias",
        "description": "Convenios pendentes: sem desembolso, vigencia proxima do fim, ou prestacao atrasada. Use para perguntas de risco/urgencia.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"}
            },
            "required": ["municipio_id"]
        }
    },
    {
        "name": "query_oportunidades",
        "description": "Programas federais abertos para inscricao (TransfereGov). Use para perguntas tipo 'que editais estao abertos', 'oportunidades de captacao'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "orgao_filtro": {"type": "string", "description": "Filtro por orgao (ex: 'saude', 'educacao')"},
                "limit": {"type": "integer", "default": 30}
            }
        }
    },
    {
        "name": "query_editais_pncp",
        "description": "Editais/licitacoes do PNCP no radar Freitas (Cultura, Esporte, Cidades, Saude, Educacao etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "area": {"type": "string", "description": "Area: Saude, Educacao, Esporte, Cultura, Obras"},
                "limit": {"type": "integer", "default": 20}
            }
        }
    },
    {
        "name": "query_sancoes",
        "description": "Consulta de sancoes (CEIS) por CNPJ. Use para due diligence de fornecedor.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cpf_cnpj": {"type": "string", "description": "CNPJ sem mascara"},
                "razao_social": {"type": "string", "description": "Filtro por nome parcial"}
            }
        }
    },
    {
        "name": "query_deputado_perfil",
        "description": "Perfil de um deputado: emendas indicadas + despesas CEAP + proposicoes. Use para perguntas sobre desempenho/relacionamento com um deputado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome_deputado": {"type": "string", "description": "Nome do deputado (parcial ok)"},
                "municipio_id": {"type": "integer", "description": "Se quiser focar emendas em um municipio"}
            },
            "required": ["nome_deputado"]
        }
    },
    {
        "name": "query_top_parlamentares_por_municipio",
        "description": "Top N parlamentares mais votados em um municipio com valor de emendas. Use para 'quais deputados mais votados aqui', 'planejamento de eleicao'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "municipio_id": {"type": "integer"},
                "limit": {"type": "integer", "default": 10}
            },
            "required": ["municipio_id"]
        }
    },
]


async def execute_tool(name: str, args: dict, db: AsyncSession) -> Any:
    """Executa um tool e retorna JSON resultado."""

    if name == "query_emendas":
        mun = args["municipio_id"]
        parl = args.get("parlamentar_nome")
        ai = args.get("ano_inicio", 2022)
        af = args.get("ano_fim", 2026)
        limit = args.get("limit", 30)
        q = """
          SELECT p.nome, p.partido, e.ano, e.valor::float, e.esfera, e.tipo,
                 COALESCE(cf.objeto, ce.objeto)[1:120] as objeto,
                 COALESCE(cf.orgao_concedente, ce.orgao_concedente) as orgao
          FROM emendas e
          JOIN parlamentares p ON p.id = e.parlamentar_id
          LEFT JOIN convenios_federal cf ON cf.id = e.convenio_federal_id
          LEFT JOIN convenios_estadual ce ON ce.id = e.convenio_estadual_id
          WHERE e.municipio_id = :m
            AND COALESCE(e.ano, 0) BETWEEN :ai AND :af
        """
        params = {"m": mun, "ai": ai, "af": af}
        if parl:
            q += " AND upper(p.nome) LIKE :p"
            params["p"] = f"%{parl.upper()}%"
        q += " ORDER BY e.valor DESC NULLS LAST LIMIT :l"
        params["l"] = limit
        r = (await db.execute(text(q), params)).all()
        items = [dict(zip(["nome","partido","ano","valor","esfera","tipo","objeto","orgao"], row)) for row in r]
        total = sum(i["valor"] or 0 for i in items)
        return {"total_itens": len(items), "soma_valor": total, "itens": items}

    if name == "query_convenios":
        mun = args["municipio_id"]
        esfera = args.get("esfera", "todos")
        sit = args.get("situacao_filtro")
        vmax = args.get("vigencia_dias_max")
        limit = args.get("limit", 30)
        from datetime import date
        items = []
        if esfera in ("federal", "todos"):
            q = """SELECT 'federal' as esfera, nr_convenio, orgao_concedente, LEFT(objeto, 120) obj,
                          situacao, valor_repasse::float, dt_fim_vigencia, dt_empenho, dt_desembolso
                   FROM convenios_federal WHERE municipio_id = :m"""
            params = {"m": mun}
            if sit:
                q += " AND upper(situacao) LIKE :s"
                params["s"] = f"%{sit.upper()}%"
            if vmax is not None:
                q += " AND dt_fim_vigencia BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL ':v days'"
                params["v"] = str(vmax)
            q += " ORDER BY valor_repasse DESC NULLS LAST LIMIT :l"
            params["l"] = limit
            r = (await db.execute(text(q), params)).all()
            for row in r: items.append(dict(zip(
                ["esfera","nr","orgao","objeto","situacao","valor","dt_fim_vigencia","dt_empenho","dt_desembolso"],
                row)))
        if esfera in ("estadual", "todos"):
            q = """SELECT 'estadual' as esfera, nr_sigcon as nr, orgao_concedente,
                          LEFT(objeto, 120) obj, situacao, valor_concedente::float,
                          dt_vigencia_atual, NULL, NULL
                   FROM convenios_estadual WHERE municipio_id = :m"""
            params = {"m": mun}
            if sit:
                q += " AND upper(situacao) LIKE :s"
                params["s"] = f"%{sit.upper()}%"
            q += " ORDER BY valor_concedente DESC NULLS LAST LIMIT :l"
            params["l"] = limit
            r = (await db.execute(text(q), params)).all()
            for row in r: items.append(dict(zip(
                ["esfera","nr","orgao","objeto","situacao","valor","dt_fim_vigencia","dt_empenho","dt_desembolso"],
                row)))
        return {"total": len(items), "soma_valor": sum(i["valor"] or 0 for i in items), "itens": items[:limit]}

    if name == "query_pendencias":
        mun = args["municipio_id"]
        q = """
          SELECT cf.nr_convenio, cf.orgao_concedente, cf.valor_repasse::float, cf.dt_fim_vigencia,
                 cf.valor_empenhado::float, cf.valor_desembolsado::float, cf.situacao
          FROM convenios_federal cf
          WHERE cf.municipio_id = :m
            AND cf.dt_fim_vigencia IS NOT NULL
            AND cf.dt_fim_vigencia BETWEEN CURRENT_DATE - INTERVAL '30 days' AND CURRENT_DATE + INTERVAL '90 days'
          ORDER BY cf.dt_fim_vigencia ASC LIMIT 30
        """
        r = (await db.execute(text(q), {"m": mun})).all()
        return {"convenios_pendentes": [dict(zip(
            ["nr","orgao","valor_repasse","dt_fim_vigencia","valor_empenhado","valor_desembolsado","situacao"],
            row)) for row in r]}

    if name == "query_oportunidades":
        orgao = args.get("orgao_filtro")
        limit = args.get("limit", 30)
        q = """SELECT id_programa, nome_programa, orgao, situacao,
                      dt_inicio_inscricao, dt_fim_inscricao
               FROM programas_federais
               WHERE situacao ILIKE 'Disponi%' OR situacao ILIKE 'Aberto%' """
        params = {}
        if orgao:
            q += " AND upper(orgao) LIKE :o"
            params["o"] = f"%{orgao.upper()}%"
        q += " ORDER BY dt_fim_inscricao ASC LIMIT :l"
        params["l"] = limit
        r = (await db.execute(text(q), params)).all()
        return {"programas": [dict(zip(["id","nome","orgao","situacao","inicio","fim"], row)) for row in r]}

    if name == "query_editais_pncp":
        area = args.get("area")
        limit = args.get("limit", 20)
        q = "SELECT id, titulo, orgao, area, valor_total::float, dt_encerramento FROM editais WHERE status='aberto'"
        params = {}
        if area:
            q += " AND area = :a"
            params["a"] = area
        q += " ORDER BY dt_encerramento ASC NULLS LAST LIMIT :l"
        params["l"] = limit
        r = (await db.execute(text(q), params)).all()
        return {"editais": [dict(zip(["id","titulo","orgao","area","valor","encerramento"], row)) for row in r]}

    if name == "query_sancoes":
        cnpj = args.get("cpf_cnpj", "").replace(".","").replace("/","").replace("-","")
        razao = args.get("razao_social")
        if cnpj:
            r = (await db.execute(text("""
              SELECT cpf_cnpj, razao_social, tipo_sancao, dt_inicio_sancao, dt_fim_sancao, orgao_sancionador
              FROM sancoes_ceis WHERE cpf_cnpj = :c LIMIT 20"""), {"c": cnpj})).all()
        elif razao:
            r = (await db.execute(text("""
              SELECT cpf_cnpj, razao_social, tipo_sancao, dt_inicio_sancao, dt_fim_sancao, orgao_sancionador
              FROM sancoes_ceis WHERE upper(razao_social) LIKE :r LIMIT 20"""),
                  {"r": f"%{razao.upper()}%"})).all()
        else:
            return {"erro": "Informe cpf_cnpj ou razao_social"}
        return {"sancoes": [dict(zip(["cnpj","razao","sancao","inicio","fim","orgao"], row)) for row in r]}

    if name == "query_deputado_perfil":
        nome = args["nome_deputado"]
        # Achar parlamentar
        p = (await db.execute(text("""
          SELECT id, nome, partido, esfera FROM parlamentares
          WHERE upper(nome) LIKE :n ORDER BY length(nome) ASC LIMIT 1
        """), {"n": f"%{nome.upper()}%"})).first()
        if not p:
            return {"erro": f"Deputado '{nome}' nao encontrado"}
        pid = p[0]
        out = {"parlamentar": dict(zip(["id","nome","partido","esfera"], p))}
        # Emendas
        mun_filter = ""
        params = {"p": pid}
        if args.get("municipio_id"):
            mun_filter = " AND e.municipio_id = :m"
            params["m"] = args["municipio_id"]
        em = (await db.execute(text(f"""
          SELECT m.nome, e.ano, e.valor::float, e.tipo
          FROM emendas e LEFT JOIN municipios m ON m.id = e.municipio_id
          WHERE e.parlamentar_id = :p {mun_filter}
          ORDER BY e.valor DESC NULLS LAST LIMIT 30
        """), params)).all()
        out["emendas"] = [dict(zip(["municipio","ano","valor","tipo"], row)) for row in em]
        out["soma_emendas"] = sum(r[2] or 0 for r in em)
        # Despesas CEAP
        try:
            desp = (await db.execute(text("""
              SELECT ano, tipo_despesa, SUM(valor_liquido)::float as total
              FROM camara_despesas WHERE parlamentar_id = :p
              GROUP BY ano, tipo_despesa ORDER BY ano DESC, total DESC LIMIT 30
            """), {"p": pid})).all()
            out["despesas_ceap"] = [dict(zip(["ano","tipo","total"], row)) for row in desp]
        except Exception: out["despesas_ceap"] = []
        return out

    if name == "query_top_parlamentares_por_municipio":
        mun = args["municipio_id"]
        limit = args.get("limit", 10)
        r = (await db.execute(text("""
          SELECT p.nome, p.partido, p.esfera, de.votos, de.eleito,
                 COALESCE(SUM(e.valor) FILTER (WHERE e.municipio_id = :m), 0)::float as valor_em
          FROM dados_eleitorais de
          JOIN parlamentares p ON p.id = de.parlamentar_id
          LEFT JOIN emendas e ON e.parlamentar_id = p.id
          WHERE de.municipio_id = :m AND de.votos > 0
          GROUP BY p.nome, p.partido, p.esfera, de.votos, de.eleito
          ORDER BY de.votos DESC LIMIT :l
        """), {"m": mun, "l": limit})).all()
        return {"top": [dict(zip(["nome","partido","esfera","votos","eleito","valor_emendas"], row)) for row in r]}

    return {"erro": f"Tool '{name}' nao implementada"}


SYSTEM_PROMPT = """Voce e PACTA IA, assistente especialista em monitoramento de convenios e
transferencias governamentais para a Freitas Consultoria. Voce tem acesso a dados de:
- Convenios federais (SICONV/TransfereGov) e estaduais (SIGCON-MG)
- Emendas parlamentares (federais + estaduais)
- Eleicoes 2022 (TSE)
- Programas federais abertos (oportunidades)
- Editais PNCP
- Sancoes CEIS
- Despesas CEAP de deputados

Voce atende 6 municipios MG (IDs): 1=Araujos, 2=Nova Serrana, 3=Bom Despacho,
4=Sao Tiago, 5=Toledo, 6=Piracema.

Regras:
- SEMPRE use tools para buscar dados reais antes de responder. Nunca invente numeros.
- Quando o usuario falar do "meu municipio" ou nao especificar, pergunte ou use o
  municipio do contexto (se vier na mensagem).
- Formate valores em R$ com 2 decimais (R$ 1.234,56).
- Para listas grandes, resuma e ofereca filtrar.
- Responda em portugues do Brasil, tom direto, sem firulas.
- Se uma pergunta exigir multiplas tools, faca em sequencia.

Quando der opiniao/analise, base nos dados. Se faltar dado, fale honestamente."""
