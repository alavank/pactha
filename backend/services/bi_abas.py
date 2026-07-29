"""Agregacoes por ABA do Painel de Indicadores (BI).

Cada funcao aqui devolve o payload COMPLETO de uma aba num unico round-trip —
o Modo Tela troca de aba a cada poucos segundos e nao pode disparar uma cascata
de requests a cada troca. Todas sao SET-AWARE (`= ANY(:ids)`), READ-ONLY e sem
gate de auth: quem gateia e o `resolve_scope` do router.

Periodo: `anos` e sempre uma LISTA (ou None = todos os anos). A fonte do ano
difere por tabela e esta comentada em cada query:
  convenios_estadual / emendas_estaduais / transferegov_pac(ano) -> coluna `ano`
  transferegov_propostas / transferegov_pac                      -> sufixo de `numero_proposta` ("xxx/AAAA")
"""
from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Situacoes que o gestor le como "dinheiro andando" (convenio vivo, executando).
EM_EXECUCAO_TOKENS = ("EXECU", "VIGENTE", "ANDAMENTO", "CELEBRAD", "ASSINAD")

# Teto de linhas devolvidas por lista detalhada (a TV nao rola; o modulo pagina).
LIMITE_ITENS = 60


def _money(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _norm(s: str) -> str:
    """Uppercase sem acento — chave de agrupamento de nome de parlamentar."""
    if not s:
        return ""
    s = s.replace("�", "").strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def _iso(d) -> Optional[str]:
    if not d:
        return None
    if isinstance(d, (date, datetime)):
        return d.isoformat()[:10]
    s = str(d).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return s or None


def _em_execucao(situacao: Optional[str]) -> bool:
    s = _norm(situacao or "")
    return any(t in s for t in EM_EXECUCAO_TOKENS)


def _rollup(rows: list[dict], chave: str, limite: int = 8) -> list[dict]:
    """Agrupa por `chave` -> [{label, qtd, valor}] ordenado por valor desc.
    Rotulo vazio vira 'Nao informado' (o gestor precisa ver que existe o buraco)."""
    acc: dict[str, dict] = defaultdict(lambda: {"label": "", "qtd": 0, "valor": 0.0})
    for r in rows:
        label = (r.get(chave) or "").strip() or "Não informado"
        e = acc[label]
        e["label"] = label
        e["qtd"] += 1
        e["valor"] += _money(r.get("valor"))
    out = sorted(acc.values(), key=lambda e: (-e["valor"], -e["qtd"]))
    return out[:limite]


def _por_ano(rows: list[dict]) -> list[dict]:
    acc: dict[int, dict] = defaultdict(lambda: {"ano": 0, "qtd": 0, "valor": 0.0})
    for r in rows:
        a = r.get("ano")
        if not a:
            continue
        e = acc[int(a)]
        e["ano"] = int(a)
        e["qtd"] += 1
        e["valor"] += _money(r.get("valor"))
    return sorted(acc.values(), key=lambda e: e["ano"])


def _filtro_ano_col(anos: Optional[list[int]], col: str = "ano") -> str:
    return f" AND {col} = ANY(:anos)" if anos else ""


def _filtro_ano_proposta(anos: Optional[list[int]], col: str = "numero_proposta") -> str:
    return f" AND split_part({col}, '/', 2) = ANY(:anos_txt)" if anos else ""


def _params(ids: list[int], anos: Optional[list[int]]) -> dict:
    p: dict = {"ids": ids}
    if anos:
        p["anos"] = anos
        p["anos_txt"] = [str(a) for a in anos]
    return p


# --------------------------------------------------------------------------
# Aba: Verbas Estaduais (SIGCON-MG + Emendas Estaduais)
# --------------------------------------------------------------------------

async def bi_estaduais(db: AsyncSession, ids: list[int], anos: Optional[list[int]] = None) -> dict:
    """Convenios SIGCON-MG (exclui as linhas FNS, que sao federais e moram na
    mesma tabela) + indicacoes de emenda estadual."""
    if not ids:
        return {"convenios": _vazio(), "emendas": _vazio(), "por_ano": []}
    p = _params(ids, anos)

    sql_conv = f"""
        SELECT c.id, c.municipio_id, m.nome, c.nr_sigcon, c.objeto, c.situacao,
               COALESCE(c.valor_total, c.valor_concedente, 0) AS valor,
               COALESCE(c.valor_repassado, 0) AS repassado,
               c.orgao_concedente, c.ano, c.dt_vigencia_atual, c.etapa_sigcon
        FROM convenios_estadual c LEFT JOIN municipios m ON m.id = c.municipio_id
        WHERE c.municipio_id = ANY(:ids)
          AND (c.fonte IS NULL OR c.fonte NOT ILIKE '%FNS%')
          {_filtro_ano_col(anos, 'c.ano')}
        ORDER BY valor DESC NULLS LAST
    """
    convenios = [{
        "id": r[0], "municipio_id": r[1], "municipio": r[2],
        "numero": r[3], "objeto": r[4], "situacao": r[5],
        "valor": _money(r[6]), "repassado": _money(r[7]),
        "orgao": r[8], "ano": r[9], "vigencia_ate": _iso(r[10]),
        "etapa": r[11],
    } for r in (await db.execute(text(sql_conv), p)).fetchall()]

    sql_em = f"""
        SELECT e.id, e.municipio_id, m.nome, e.nr_indicacao, e.nome_responsavel,
               e.beneficiario, e.tipo_atendimento, COALESCE(e.valor_indicacao, 0) AS valor,
               e.status_indicacao, e.uo_sigla, e.ano, e.grupo_despesa
        FROM emendas_estaduais e LEFT JOIN municipios m ON m.id = e.municipio_id
        WHERE e.municipio_id = ANY(:ids)
          {_filtro_ano_col(anos, 'e.ano')}
        ORDER BY valor DESC NULLS LAST
    """
    emendas = [{
        "id": r[0], "municipio_id": r[1], "municipio": r[2],
        "numero": r[3], "parlamentar": r[4],
        "destinacao": r[5], "finalidade": r[6],
        "valor": _money(r[7]), "situacao": r[8], "orgao": r[9],
        "ano": r[10], "grupo_despesa": r[11],
    } for r in (await db.execute(text(sql_em), p)).fetchall()]

    return {
        "convenios": {
            "total": len(convenios),
            "valor_total": sum(c["valor"] for c in convenios),
            "valor_repassado": sum(c["repassado"] for c in convenios),
            "em_execucao": sum(1 for c in convenios if _em_execucao(c["situacao"])),
            "por_situacao": _rollup(convenios, "situacao"),
            "por_orgao": _rollup(convenios, "orgao"),
            "itens": convenios[:LIMITE_ITENS],
        },
        "emendas": {
            "total": len(emendas),
            "valor_total": sum(e["valor"] for e in emendas),
            "por_situacao": _rollup(emendas, "situacao"),
            "por_orgao": _rollup(emendas, "orgao"),
            "itens": emendas[:LIMITE_ITENS],
        },
        "por_ano": _por_ano(convenios + emendas),
    }


def _vazio() -> dict:
    return {"total": 0, "valor_total": 0.0, "por_situacao": [], "por_orgao": [], "itens": []}


# --------------------------------------------------------------------------
# Aba: TransfereGov (voluntarias + PAC)
# --------------------------------------------------------------------------

async def bi_transferegov(db: AsyncSession, ids: list[int], anos: Optional[list[int]] = None) -> dict:
    if not ids:
        return {"voluntarias": _vazio(), "pac": _vazio(), "por_ano": [], "em_execucao": []}
    p = _params(ids, anos)

    sql_vol = f"""
        SELECT v.id, v.municipio_id, m.nome, v.numero_proposta, v.codigo_instrumento,
               v.objeto, v.situacao, COALESCE(v.valor_global, v.valor_repasse, 0) AS valor,
               COALESCE(v.valor_repasse, 0), v.orgao, v.parlamentar,
               v.dt_inicio_vigencia, v.dt_fim_vigencia, v.programa, v.situacao_contratacao
        FROM transferegov_propostas v LEFT JOIN municipios m ON m.id = v.municipio_id
        WHERE v.municipio_id = ANY(:ids)
          {_filtro_ano_proposta(anos, 'v.numero_proposta')}
        ORDER BY valor DESC NULLS LAST
    """
    voluntarias = []
    for r in (await db.execute(text(sql_vol), p)).fetchall():
        num = r[3] or ""
        ano_prop = num.split("/")[-1] if "/" in num else None
        voluntarias.append({
            "id": r[0], "municipio_id": r[1], "municipio": r[2],
            "numero": num, "instrumento": r[4], "objeto": r[5], "situacao": r[6],
            "valor": _money(r[7]), "repasse": _money(r[8]), "orgao": r[9],
            "parlamentar": r[10], "vigencia_de": _iso(r[11]), "vigencia_ate": _iso(r[12]),
            "programa": r[13], "situacao_contratacao": r[14],
            "ano": int(ano_prop) if (ano_prop or "").isdigit() else None,
        })

    sql_pac = f"""
        SELECT pc.id, pc.municipio_id, m.nome, pc.numero_proposta, pc.programa,
               pc.situacao, COALESCE(pc.valor_total, 0) AS valor,
               COALESCE(pc.valor_repasse, 0), pc.emenda_parlamentar, pc.objeto
        FROM transferegov_pac pc LEFT JOIN municipios m ON m.id = pc.municipio_id
        WHERE pc.municipio_id = ANY(:ids)
          {_filtro_ano_proposta(anos, 'pc.numero_proposta')}
        ORDER BY valor DESC NULLS LAST
    """
    pac = []
    try:
        for r in (await db.execute(text(sql_pac), p)).fetchall():
            num = r[3] or ""
            ano_prop = num.split("/")[-1] if "/" in num else None
            pac.append({
                "id": r[0], "municipio_id": r[1], "municipio": r[2],
                "numero": num, "programa": r[4], "situacao": r[5],
                "valor": _money(r[6]), "repasse": _money(r[7]),
                "parlamentar": r[8], "objeto": r[9],
                "ano": int(ano_prop) if (ano_prop or "").isdigit() else None,
            })
    except Exception:
        pac = []  # tabela ausente em base antiga -> aba degrada sem quebrar

    execucao = [v for v in voluntarias if _em_execucao(v["situacao"])]

    return {
        "voluntarias": {
            "total": len(voluntarias),
            "valor_total": sum(v["valor"] for v in voluntarias),
            "valor_repasse": sum(v["repasse"] for v in voluntarias),
            "em_execucao": len(execucao),
            "por_situacao": _rollup(voluntarias, "situacao"),
            "por_orgao": _rollup(voluntarias, "orgao"),
            "itens": voluntarias[:LIMITE_ITENS],
        },
        "pac": {
            "total": len(pac),
            "valor_total": sum(x["valor"] for x in pac),
            "por_situacao": _rollup(pac, "situacao"),
            "por_orgao": _rollup(pac, "programa"),
            "itens": pac[:LIMITE_ITENS],
        },
        "em_execucao": execucao[:LIMITE_ITENS],
        "por_ano": _por_ano(voluntarias + pac),
    }


# --------------------------------------------------------------------------
# Aba: Parlamentares — cada emenda com DESTINACAO e FINALIDADE
# --------------------------------------------------------------------------

async def bi_parlamentares_detalhe(
    db: AsyncSession,
    ids: list[int],
    anos: Optional[list[int]] = None,
    max_parlamentares: int = 24,
    max_lancamentos: int = 12,
) -> dict:
    """Ranking de parlamentares COM os lancamentos de cada um — o que o prefeito
    quer ver na TV: quem mandou, quanto, pra que (finalidade) e pra quem
    (destinacao/beneficiario). Uma unica varredura das 3 fontes que tem autor
    nominal no banco (SIGCON, voluntarias, emendas estaduais)."""
    if not ids:
        return {"itens": [], "total": 0, "valor_total": 0.0}
    p = _params(ids, anos)
    grupos: dict[str, dict] = defaultdict(lambda: {
        "nome": "", "nome_normalizado": "", "valor_total": 0.0,
        "total_lancamentos": 0, "municipios": set(), "por_fonte": defaultdict(int),
        "lancamentos": [],
    })

    def _add(nome_bruto: str, lanc: dict):
        for nm in str(nome_bruto or "").split(","):
            nm = nm.strip()
            if len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            g = grupos[key]
            g["nome_normalizado"] = key
            if not g["nome"] or len(nm) > len(g["nome"]):
                g["nome"] = nm
            g["valor_total"] += lanc["valor"]
            g["total_lancamentos"] += 1
            g["por_fonte"][lanc["fonte"]] += 1
            if lanc.get("municipio"):
                g["municipios"].add(lanc["municipio"])
            g["lancamentos"].append(lanc)

    # 1) Emendas estaduais — a fonte mais rica: beneficiario + tipo_atendimento
    sql_em = f"""
        SELECT e.nome_responsavel, e.nr_indicacao, e.beneficiario, e.tipo_atendimento,
               COALESCE(e.valor_indicacao, 0), e.status_indicacao, e.uo_sigla, e.ano,
               m.nome, e.grupo_despesa
        FROM emendas_estaduais e LEFT JOIN municipios m ON m.id = e.municipio_id
        WHERE e.municipio_id = ANY(:ids) AND e.nome_responsavel IS NOT NULL
          {_filtro_ano_col(anos, 'e.ano')}
    """
    for r in (await db.execute(text(sql_em), p)).fetchall():
        _add(r[0], {
            "fonte": "emenda_estadual", "numero": r[1],
            "destinacao": r[2], "finalidade": r[3] or r[9],
            "valor": _money(r[4]), "situacao": r[5], "orgao": r[6],
            "ano": r[7], "municipio": r[8],
        })

    # 2) SIGCON — autor em raw_data.responsaveis; finalidade = objeto do convenio
    sql_sig = f"""
        SELECT c.raw_data->>'responsaveis', c.nr_sigcon, c.objeto, c.situacao,
               COALESCE(c.valor_total, c.valor_concedente, 0), c.orgao_concedente,
               c.ano, m.nome, c.dt_vigencia_atual
        FROM convenios_estadual c LEFT JOIN municipios m ON m.id = c.municipio_id
        WHERE c.municipio_id = ANY(:ids)
          AND c.raw_data->>'responsaveis' IS NOT NULL
          AND (c.fonte IS NULL OR c.fonte NOT ILIKE '%FNS%')
          {_filtro_ano_col(anos, 'c.ano')}
    """
    for r in (await db.execute(text(sql_sig), p)).fetchall():
        _add(r[0], {
            "fonte": "sigcon", "numero": r[1],
            "destinacao": r[7], "finalidade": r[2],
            "valor": _money(r[4]), "situacao": r[3], "orgao": r[5],
            "ano": r[6], "municipio": r[7], "vigencia_ate": _iso(r[8]),
        })

    # 3) TransfereGov voluntarias — parlamentar nominal
    sql_vol = f"""
        SELECT v.parlamentar, v.numero_proposta, v.objeto, v.situacao,
               COALESCE(v.valor_global, v.valor_repasse, 0), v.orgao, m.nome,
               v.dt_fim_vigencia
        FROM transferegov_propostas v LEFT JOIN municipios m ON m.id = v.municipio_id
        WHERE v.municipio_id = ANY(:ids) AND v.parlamentar IS NOT NULL
          {_filtro_ano_proposta(anos, 'v.numero_proposta')}
    """
    for r in (await db.execute(text(sql_vol), p)).fetchall():
        num = r[1] or ""
        ano_prop = num.split("/")[-1] if "/" in num else ""
        _add(r[0], {
            "fonte": "voluntaria", "numero": num,
            "destinacao": r[6], "finalidade": r[2],
            "valor": _money(r[4]), "situacao": r[3], "orgao": r[5],
            "ano": int(ano_prop) if ano_prop.isdigit() else None,
            "municipio": r[6], "vigencia_ate": _iso(r[7]),
        })

    itens = []
    for g in grupos.values():
        g["lancamentos"].sort(key=lambda x: -x["valor"])
        itens.append({
            "nome": g["nome"],
            "nome_normalizado": g["nome_normalizado"],
            "valor_total": g["valor_total"],
            "total_lancamentos": g["total_lancamentos"],
            "municipios": sorted(g["municipios"]),
            "por_fonte": dict(g["por_fonte"]),
            "lancamentos": g["lancamentos"][:max_lancamentos],
            "lancamentos_ocultos": max(0, g["total_lancamentos"] - max_lancamentos),
        })
    itens.sort(key=lambda x: (-x["valor_total"], -x["total_lancamentos"]))

    return {
        "itens": itens[:max_parlamentares],
        "total": len(itens),
        "valor_total": sum(i["valor_total"] for i in itens),
        "anos": anos or [],
    }


# --------------------------------------------------------------------------
# Aba: Documentacao (CAUC federal + CAGEC estadual)
# --------------------------------------------------------------------------

async def bi_documentos(db: AsyncSession, ids: list[int]) -> dict:
    """Situacao das certidoes/cadastros. CAUC vem do banco (coletado); CAGEC
    ainda NAO e coletado por nenhum scraper — devolvemos `disponivel: false` em
    vez de inventar um verde que o gestor leria como 'esta tudo em dia'."""
    if not ids:
        return {"cauc": {"por_municipio": [], "total_municipios": 0}, "cagec": _cagec_indisponivel()}

    # Import local: services -> routers seria uma dependencia invertida no topo
    # do modulo. fetch_cauc_situacao ja rotula e agrupa cada exigencia (labels
    # legiveis), que e exatamente o que a aba precisa mostrar na TV.
    from routers.cauc import fetch_cauc_situacao

    por_municipio = []
    for mid in ids[:20]:  # detalhe item-a-item so p/ os primeiros; o resto vai no rollup
        s = await fetch_cauc_situacao(db, mid)
        if not s.get("tem_dados"):
            continue
        itens = s.get("itens") or []
        por_municipio.append({
            "municipio_id": mid,
            "nome": s.get("nome"),
            "regular": s.get("regular"),
            "pendencias": s.get("pendencias") or 0,
            "pendencias_codigos": s.get("pendencias_codigos") or [],
            "itens_pendentes": [i for i in itens if i["tipo"] == "pendente"],
            "itens_regulares": [i for i in itens if i["tipo"] == "regular"],
            # TODAS as exigencias, com `grupo` e `tipo` (regular/pendente/na).
            # A TV mostrava so um recorte dos regulares e nada dos "nao
            # exigidos": o gestor via 9 linhas de 15 sem nenhum sinal de que
            # faltava o resto. Cada item ja vem rotulado e agrupado por
            # fetch_cauc_situacao — aqui era so nao jogar fora.
            "itens": itens,
            "total_itens": len([i for i in itens if i["tipo"] != "na"]),
            "data_pesquisa": s.get("data_pesquisa"),
            "atualizado_em": s.get("atualizado_em"),
        })
    por_municipio.sort(key=lambda m: (m["regular"] is True, m["nome"] or ""))

    return {
        "cauc": {
            "por_municipio": por_municipio,
            "total_municipios": len(ids),
            "com_dados": len(por_municipio),
            "regulares": sum(1 for m in por_municipio if m["regular"]),
            "pendencias_total": sum(m["pendencias"] for m in por_municipio),
        },
        "cagec": _cagec_indisponivel(),
    }


def _cagec_indisponivel() -> dict:
    return {
        "disponivel": False,
        "motivo": "O CAGEC (cadastro de convenentes de MG) ainda nao e coletado "
                  "automaticamente pelo PACTHA. Consulte pelo portal SIGCON-MG.",
        "por_municipio": [],
    }


# --------------------------------------------------------------------------
# Aba: Geral — convenios EM EXECUCAO (o que esta rodando agora)
# --------------------------------------------------------------------------

async def bi_execucao(db: AsyncSession, ids: list[int], anos: Optional[list[int]] = None) -> dict:
    """Instrumentos vivos: situacao de execucao/vigente E vigencia ainda aberta."""
    if not ids:
        return {"itens": [], "total": 0, "valor_total": 0.0}
    p = _params(ids, anos)
    hoje = date.today()

    sql = f"""
        SELECT c.id, m.nome, c.nr_sigcon, c.objeto, c.situacao,
               COALESCE(c.valor_total, c.valor_concedente, 0),
               COALESCE(c.valor_repassado, 0), c.dt_vigencia_atual, c.orgao_concedente
        FROM convenios_estadual c LEFT JOIN municipios m ON m.id = c.municipio_id
        WHERE c.municipio_id = ANY(:ids)
          AND (c.fonte IS NULL OR c.fonte NOT ILIKE '%FNS%')
          AND c.dt_vigencia_atual >= :hoje
          {_filtro_ano_col(anos, 'c.ano')}
        ORDER BY COALESCE(c.valor_total, c.valor_concedente, 0) DESC NULLS LAST
    """
    p["hoje"] = hoje
    itens = []
    for r in (await db.execute(text(sql), p)).fetchall():
        valor = _money(r[5])
        repassado = _money(r[6])
        itens.append({
            "id": r[0], "municipio": r[1], "numero": r[2], "objeto": r[3],
            "situacao": r[4], "valor": valor, "repassado": repassado,
            "pct_repassado": round(repassado / valor * 100, 1) if valor else 0.0,
            "vigencia_ate": _iso(r[7]), "orgao": r[8],
            "dias_restantes": (r[7] - hoje).days if r[7] else None,
        })
    return {
        "itens": itens[:LIMITE_ITENS],
        "total": len(itens),
        "valor_total": sum(i["valor"] for i in itens),
        "valor_repassado": sum(i["repassado"] for i in itens),
    }
