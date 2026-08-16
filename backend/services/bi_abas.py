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
from services.nome_parlamentar import e_parlamentar_real

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


def _pct(v) -> Optional[float]:
    """Percentual PRESERVANDO None. Nao use `_money` aqui.

    `_money` e para DINHEIRO, onde ausente = zero e a leitura certa. Percentual
    ausente NAO e zero medido: a API do MS manda `vlPercentualExecutado` nulo
    quando a obra nunca informou medicao — 3 das 7 obras de Monte Siao em
    31/07/2026, incluindo as duas maiores da carteira (CAPS de R$ 2,5 mi e ESF
    de R$ 2,0 mi, ambas com repasse integral em junho). Zerar isso fazia a TV e
    o link publico exibirem "0%" com a barra apagada, e a faixa de IA escrever
    em prosa "0% de execucao" sobre obra que ninguem mediu — enquanto a tela do
    modulo, com o mesmo dado, mostrava "—". Ausencia de medicao virando medicao
    zero e o tipo de erro que so aparece na superficie lida de longe."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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
            # Mesma regra do ranking de Parlamentares (ver
            # services/nome_parlamentar.py): "Não há" e marcador de ausencia do
            # SIGCON, nao pessoa — e liderava o Painel do freitas.
            if not e_parlamentar_real(nm):
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

    valor_total = sum(i["valor_total"] for i in itens)

    # FAIXA COMPARATIVA para a TV: mandato atual contra o anterior, so o total.
    # Na parede do gabinete cabe UM numero e a variacao — a tabela comparativa
    # inteira mora na tela do sistema. Falha em silencio de proposito: se a
    # consulta do periodo anterior der errado, a aba continua funcionando sem a
    # faixa, em vez de derrubar o Painel por causa de um enfeite.
    comparativo = None
    try:
        hoje = date.today().year
        ini = hoje - ((((hoje - 2025) % 4) + 4) % 4)      # mandato de PREFEITO
        atual = [a for a in range(ini, ini + 4) if a <= hoje]
        anterior = list(range(ini - 4, ini))
        # So compara quando a aba esta mostrando o mandato atual (ou tudo): com
        # um recorte qualquer na tela, "mandato x mandato" seria outro numero
        # que nao o da tabela ao lado, e duas verdades na mesma tela e pior que
        # nenhuma.
        if not anos or set(anos) == set(atual):
            ant = await bi_parlamentares_detalhe(
                db, ids, anos=anterior, max_parlamentares=1, max_lancamentos=0)
            base = float(ant.get("valor_total") or 0.0)
            # `valor_total` so vale como "mandato atual" quando a aba ESTA
            # filtrada por ele. Com a aba em "todos os anos", reaproveita-lo
            # rotularia o total historico como se fosse o mandato — foi o que
            # este codigo fez na primeira versao, e o teste pegou: R$ 30,6 mi
            # de todos os anos aparecendo como "2025-2026".
            if anos:
                topo = valor_total
            else:
                atu = await bi_parlamentares_detalhe(
                    db, ids, anos=atual, max_parlamentares=1, max_lancamentos=0)
                topo = float(atu.get("valor_total") or 0.0)
            comparativo = {
                "rotulo_atual": f"{atual[0]}–{atual[-1]}" if len(atual) > 1 else str(atual[0]),
                "rotulo_anterior": f"{anterior[0]}–{anterior[-1]}",
                "valor_atual": topo,
                "valor_anterior": base,
                "delta": topo - base,
                "delta_pct": ((topo - base) / base * 100.0) if base > 0 else None,
                "anos_atual": len(atual),
                "anos_anterior": len(anterior),
            }
    except Exception:
        comparativo = None

    return {
        "itens": itens[:max_parlamentares],
        "total": len(itens),
        "valor_total": valor_total,
        "anos": anos or [],
        "comparativo": comparativo,
    }


# --------------------------------------------------------------------------
# Aba: Documentacao (CAUC federal + CAGEC estadual)
# --------------------------------------------------------------------------

# Ate quantos municipios recebem o detalhe item-a-item das exigencias.
#
# 60 e nao 20: a maior carteira viva hoje (Freitas) tem 41 municipios, e o corte
# antigo deixava 21 deles de fora — em silencio, e com as somas parecendo falar
# do total. O teto continua existindo porque cada municipio e uma consulta ao
# banco, e uma carteira de centenas viraria centenas de idas numa requisicao so;
# o que ele nao pode e ser invisivel (ver `detalhe_limitado` na resposta).
LIMITE_DETALHE_CAUC = 60


async def _coleta_mais_antiga(db: AsyncSession, tabela: str, ids: list[int]):
    """`min(atualizado_em)` sobre TODOS os ids do escopo, em uma query so.

    ⚠️ NAO DA PARA CALCULAR ISSO NA TELA. O `por_municipio` que vai no payload e
    CORTADO (`LIMITE_DETALHE_CAUC` no CAUC, os 20 primeiros de MG no CAGEC) e
    ainda pula quem nao tem linha na tabela. Um `min()` no frontend carimbaria
    "a coleta mais antiga entre os que couberam" — numa carteira de 41
    municipios, uma afirmacao falsa sobre a carteira, que e exatamente o defeito
    do cartao que esta mudanca veio corrigir, so que mais dificil de enxergar.

    Municipio sem NENHUMA linha nao entra no min() (nao ha o que datar); quem
    conta esses e `com_dados`/`municipios_no_escopo`, ja no payload."""
    if not ids:
        return None
    try:
        r = await db.execute(
            text(f"SELECT min(atualizado_em) FROM {tabela} WHERE municipio_id = ANY(:ids)"),
            {"ids": ids})
        v = r.scalar()
        return v.isoformat() if v else None
    except Exception:
        return None


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

    # ⚠️ O CORTE EXISTE, MAS AGORA ELE SE DECLARA.
    #
    # Era `ids[:20]` cru, e a resposta misturava dois conjuntos: `total_municipios`
    # contava TODOS os ids, enquanto `com_dados`, `regulares` e `pendencias_total`
    # olhavam so os 20 primeiros. Numa assessoria de 41 municipios a tela dizia
    # "18 de 41 regulares" sem nunca ter olhado 21 deles — numerador e denominador
    # falando de coisas diferentes, e o gestor lendo aquilo como cobertura.
    #
    # O limite continua porque cada municipio e uma consulta (`fetch_cauc_situacao`),
    # e uma carteira grande viraria 200 idas ao banco numa requisicao so. O que
    # muda e que ele sai na resposta: quem soma passa a saber sobre quantos somou.
    examinados = ids[:LIMITE_DETALHE_CAUC]
    por_municipio = []
    for mid in examinados:
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
            # ⭐ Sobre QUANTOS os numeros abaixo falam. Sem este campo a tela nao
            # tem como ser honesta: ela so ve o total e as somas.
            "examinados": len(examinados),
            "detalhe_limitado": len(ids) > len(examinados),
            "com_dados": len(por_municipio),
            "regulares": sum(1 for m in por_municipio if m["regular"]),
            "pendencias_total": sum(m["pendencias"] for m in por_municipio),
            # Carimbo honesto da carteira: o MAIS ANTIGO de todo o escopo, nao o
            # mais antigo entre os que couberam no corte de detalhe.
            "coleta_mais_antiga": await _coleta_mais_antiga(db, "cauc_situacao", ids),
        },
        "cagec": await _cagec_bloco(db, ids),
    }


# ⚠️ CADASTRO ESTADUAL NAO E EXCLUSIVIDADE DE MINAS — outros estados tem o seu.
# O que e nosso e a lista de fontes que este sistema sabe consultar.
#
# A diferenca nao e semantica. Dizer "nao se aplica" a um municipio de Goias
# afirma que ele NAO TEM cadastro estadual — e nos nao sabemos isso. O que
# sabemos e que nao coletamos o cadastro daquele estado. Uma frase fecha o
# assunto por engano; a outra descreve a nossa cobertura, que e o fato.
#
# ⚠️ CONJUNTO, e nao escalar. Era `UF_DA_FONTE = "MG"` ate 08/2026, quando o
# coletor do CHE gaucho (ingestion/che_rs.py) entrou. Com o escalar, a tela
# /dashboard/cauc mostraria o CHE de Santa Maria com dado real enquanto o Painel
# de Indicadores dizia, na MESMA sessao, que o cadastro estadual daquele estado
# nao e acompanhado — duas telas do mesmo sistema discordando sobre o mesmo fato.
#
# Espelha `UFS_ACOMPANHADAS` de frontend/src/lib/estadual.ts. As duas listas
# precisam andar juntas: entrar aqui e nao la (ou vice-versa) reintroduz
# exatamente a contradicao acima.
UFS_COM_CADASTRO_COLETADO: set[str] = {"MG", "RS"}

# ⚠️ OUTRA COISA, apesar do nome parecido: esta e a UF do coletor de CONVENIOS
# estaduais logado (SIGCON-MG), usada como denominador do medidor de coleta em
# routers/bi.py. Regularidade e convenio tem coberturas DIFERENTES — no RS
# coletamos o cadastro (CHE) mas nao ha coletor de convenio estadual logado, e
# no ES e o inverso. Fundir as duas faria o medidor do SIGCON contar municipio
# gaucho como "sem coleta ainda", prometendo uma coleta que nunca vira.
UF_DA_FONTE_SIGCON = "MG"
# ⚠️ A FRASE NAO CITA MINAS. Ela aparece na tela de um cliente do ES ou de GO, e
# ali Minas nao tem nada com o assunto: o ambiente e do municipio aberto, e nossa
# cobertura interna nao e problema do cliente. Diz o que vale para ELE — que a
# regularidade estadual dele ainda nao e acompanhada aqui — sem afirmar que o
# cadastro nao existe (existe: GO tem o SIGECON, o ES tem o Portal de Convenios).
MOTIVO_ESTADO_SEM_FONTE = (
    "O cadastro estadual de convenentes deste estado ainda não é acompanhado "
    "por este sistema."
)


def _cagec_indisponivel(motivo: str | None = None) -> dict:
    from routers.cagec import MOTIVO_SEM_COLETA
    return {"disponivel": False, "motivo": motivo or MOTIVO_SEM_COLETA,
            "por_municipio": [], "municipios_no_escopo": 0, "fora_de_mg": 0}


async def _escopo_do_cadastro_estadual(
    db: AsyncSession, ids: list[int]
) -> tuple[list[int], list[str]]:
    """Separa o escopo entre o que a fonte alcanca e o que ela nao alcanca.

    Devolve `(ids_cobertos, ufs_sem_fonte)` — e a segunda parte importa tanto
    quanto a primeira: e com ela que a tela nomeia os estados de fora em vez de
    dizer um "nao se aplica" que nao tem como saber."""
    if not ids:
        return [], []
    linhas = await db.execute(
        text("SELECT id, upper(coalesce(uf, '')) FROM municipios "
             "WHERE id = ANY(:ids)"),
        {"ids": ids})
    uf_por_id = {r[0]: r[1] for r in linhas.fetchall()}
    cobertos = [i for i in ids if uf_por_id.get(i) in UFS_COM_CADASTRO_COLETADO]
    fora = sorted({uf for i, uf in uf_por_id.items()
                   if uf and uf not in UFS_COM_CADASTRO_COLETADO and i in set(ids)})
    return cobertos, fora


async def _cagec_bloco(db: AsyncSession, ids: list[int]) -> dict:
    """CAGEC no mesmo formato do CAUC. Hoje NENHUM scraper alimenta a tabela
    (falta a credencial do SIGCON-MG), entao na pratica isto devolve
    `disponivel: false` — mas a consulta ja e real: no dia em que a coleta
    entrar, a tela preenche sozinha, sem mexer em frontend.

    Nunca inventar verde aqui: numa TV de gabinete, "sem dado" pintado de verde
    e lido como "a regularidade estadual esta em dia"."""
    from routers.cagec import fetch_cagec_situacao

    # ⭐ SO O QUE A FONTE ALCANCA. Antes varria os ids todos: numa carteira
    # multi-estado, consultava o portal mineiro para cidades de GO/TO/ES e a tela
    # carimbava "CAGEC — Minas Gerais" sobre elas.
    ids_mg, ufs_fora = await _escopo_do_cadastro_estadual(db, ids)
    fora = len(ids) - len(ids_mg)
    if not ids_mg:
        vazio = _cagec_indisponivel(MOTIVO_ESTADO_SEM_FONTE if fora else None)
        vazio["fora_de_mg"] = fora
        vazio["ufs_sem_fonte"] = ufs_fora
        return vazio

    por_municipio = []
    for mid in ids_mg[:20]:
        s = await fetch_cagec_situacao(db, mid)
        if not s.get("tem_dados"):
            continue
        por_municipio.append({
            "municipio_id": mid,
            "nome": s.get("nome"),
            "regular": s.get("regular"),
            "situacao": s.get("situacao"),
            "validade": s.get("validade"),
            "itens": s.get("itens") or [],
            "pendencias": s.get("pendencias") or 0,
            "data_pesquisa": s.get("data_pesquisa"),
            # ⚠️ QUANDO O ROBO RODOU, que NAO e `data_pesquisa`. No CAGEC o
            # `data_pesquisa` e `date.today()` do proprio scraper (DATE, sem
            # hora); no CAUC e a data do extrato do TESOURO, que pode ser de
            # ontem. Chamar os dois de "atualizado em" na tela juntava duas
            # coisas diferentes sob o mesmo rotulo. `atualizado_em` e
            # TIMESTAMPTZ e significa a mesma coisa nas duas esferas: a hora
            # da nossa coleta. E o unico campo que pode carimbar as duas.
            "atualizado_em": s.get("atualizado_em"),
            # Procedencia do detalhamento. Sem isto, o Painel e a TV repetem o
            # erro que a tela do modulo cometeu em 01/08/2026: exibir as duas
            # linhas de fallback como se fossem o cadastro inteiro, com o
            # contador afirmando "2 exigencias" na parede do gabinete.
            "crc_em": s.get("crc_em"),
            "crc_erro": s.get("crc_erro"),
            "detalhe_do_crc": bool(s.get("detalhe_do_crc")),
        })

    if not por_municipio:
        return _cagec_indisponivel()
    return {
        "disponivel": True,
        "motivo": "",
        "por_municipio": por_municipio,
        # ⭐ SOBRE QUANTOS o CAGEC fala. Numa carteira multi-estado ele cobre
        # so a parte mineira, e a tela precisa dizer isso — senao "3 em dia"
        # sobre 19 municipios e lido como a carteira inteira estar em dia.
        "municipios_no_escopo": len(ids_mg),
        "fora_de_mg": fora,
        # As UFs que ficaram de fora, NOMEADAS. E o que permite a tela dizer
        # "GO, TO" em vez de uma frase generica que o gestor nao sabe conferir.
        "ufs_sem_fonte": ufs_fora,
        "regulares": sum(1 for m in por_municipio if m["regular"]),
        "pendencias_total": sum(m["pendencias"] for m in por_municipio),
        # So os de MG: o CAGEC nao alcanca os outros, e incluir os demais faria
        # o carimbo ficar eternamente vazio numa carteira mista.
        "coleta_mais_antiga": await _coleta_mais_antiga(db, "cagec_situacao", ids_mg),
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


# --------------------------------------------------------------------------
# Documentacao vencendo — fonte UNICA para a tela e para o push
# --------------------------------------------------------------------------
# Antes nao existia alerta nenhum de VALIDADE de documento: o cron so olhava
# `cauc_situacao.pendencias > 0`, ou seja, so avisava DEPOIS de o municipio ja
# estar travado. E a preferencia de push ja se chamava `cauc_vencendo` — o nome
# prometia uma coisa que o codigo nao fazia.
#
# O dado para avisar ANTES sempre esteve la e nao era usado: cada obrigacao do
# CAGEC tem validade propria (vem do CRC) e cada item do CAUC traz a data no
# proprio valor. Aqui as duas esferas viram uma lista so, ordenada por urgencia,
# que alimenta a tela E o push — para os dois canais nunca discordarem.

# O CAUC escreve o ano com DOIS digitos ("30/09/26"); o CRC do CAGEC escreve com
# quatro ("30/09/2026"). Aceitar so um formato perderia metade dos alertas em
# silencio, que e o pior tipo de falha aqui.
_FORMATOS_DATA = ("%d/%m/%Y", "%d/%m/%y")


def _data_br(v) -> Optional[date]:
    if not v or not isinstance(v, str):
        return None
    v = v.strip()
    for f in _FORMATOS_DATA:
        try:
            return datetime.strptime(v, f).date()
        except ValueError:
            continue
    return None


# Janela minima para uma data ser tratada como PRAZO.
#
# Medido em producao (Monte Siao, extrato de 30/07/2026): 16 dos 25 itens do
# CAUC tem `validade == data_pesquisa`, e mais um tem +1 dia. Nao sao prazos —
# e como o CAUC reporta requisito verificado CONTINUAMENTE: a informacao vale
# "na data da consulta" e o proximo extrato traz a data do dia seguinte. Tratar
# isso como vencimento dispararia 17 alertas por dia, por municipio, para
# sempre — e alerta que grita todo dia e pior do que alerta nenhum, porque o
# gestor aprende a ignorar TODOS, inclusive o do FGTS que importa.
#
# Prazo de verdade tem janela: os outros 8 itens ficam entre +170 e +274 dias, e
# as certidoes do CAGEC entre 55 e 880 dias.
JANELA_MINIMA_DIAS = 3


def prazos_dos_itens(itens, data_pesquisa: Optional[date], esfera: str,
                     dias: int = 30, hoje: Optional[date] = None) -> list[dict]:
    """A REGRA, isolada e sem I/O — usada pela tela (async) e pelo cron de push
    (psycopg2 sincrono). Se as duas implementassem a regra por conta propria, um
    dia a tela e a notificacao passariam a discordar sobre o mesmo prazo.

    Aceita os dois formatos: CAGEC manda LISTA de dicts (cada um com `validade`),
    CAUC manda DICT {codigo: valor} em que o valor JA E a data."""
    hoje = hoje or date.today()
    from services.cauc_catalogo import LABELS, _classifica

    if isinstance(itens, dict):        # CAUC
        pares = [(cod, val, LABELS.get(cod, f"Exigência {cod}"),
                  _classifica(val)[0]) for cod, val in itens.items()]
    else:                              # CAGEC
        pares = [(i.get("codigo"), i.get("validade"), i.get("label"), i.get("tipo"))
                 for i in (itens or []) if isinstance(i, dict)]

    out = []
    for codigo, valor, label, tipo in pares:
        if tipo == "na":
            continue
        d = _data_br(valor)
        if not d:
            # "!" no CAUC nao tem data: e pendencia ja existente, nao prazo.
            continue
        # A janela vale SO PARA O CAUC, e a diferenca nao e detalhe.
        #
        # Em `cauc_situacao`, `data_pesquisa` e a "Data da Pesquisa" DO PROPRIO
        # EXTRATO, e os itens verificados continuamente trazem exatamente essa
        # data no lugar da validade (10 dos 28 em 31/07/2026). Sem a janela, eles
        # apareceriam como "vencendo hoje" TODO DIA.
        #
        # Em `cagec_situacao`, `data_pesquisa` e a data da NOSSA raspagem: nao tem
        # relacao com o documento. E no CRC validade vencida VIRA pendencia — as 3
        # de Monte Siao sao exatamente as 3 com validade anterior a pesquisa.
        # Aplicar a janela ali escondia toda obrigacao do CRC nos seus 3 ultimos
        # dias: com o item 3.4 (Matriz de Saldos) vencendo em 31/07/2026, o painel
        # afirmava "Nenhuma certidao vencendo nos proximos 30 dias".
        if (esfera or "").upper() == "CAUC" and data_pesquisa \
                and (d - data_pesquisa).days < JANELA_MINIMA_DIAS:
            continue                   # cadencia de atualizacao, nao vencimento
        restantes = (d - hoje).days
        if restantes < 0 or restantes > dias:
            continue                   # ja venceu (= pendencia) ou ainda longe
        out.append({"esfera": esfera, "codigo": codigo, "label": label,
                    "validade": d.isoformat(), "dias_restantes": restantes})
    return out


async def documentos_vencendo(db: AsyncSession, ids: list[int],
                              dias: int = 30) -> list[dict]:
    """Obrigacoes de regularidade que VAO vencer nos proximos `dias`.

    So o futuro, de proposito. O que ja venceu nao e "vencendo": e pendencia, e
    ja aparece como tal (chip vermelho na lista, contador nos cartoes, faixa da
    IA). Repetir aqui duplicaria o mesmo aviso em dois lugares com nomes
    diferentes."""
    if not ids:
        return []
    hoje = date.today()
    out: list[dict] = []

    for tabela, esfera in (("cagec_situacao", "CAGEC"), ("cauc_situacao", "CAUC")):
        # `entidade` so existe no CAGEC, que tem UMA LINHA POR ENTIDADE
        # (prefeitura, Fundo Municipal de Saude, FMAS — cada uma com cadastro
        # proprio, e cada uma travando so o SEU convenio). Esta funcao ja lia
        # todas as linhas, entao os prazos dos fundos ja entravam na lista — mas
        # saiam sem dono, dentro de um painel cujo resto fala so do municipio.
        # O gestor lia um prazo do Fundo como se fosse da Prefeitura.
        #
        # NAO filtrar por `principal` para "resolver": isso apagaria prazo real
        # do fundo, e trocar rotulo incompleto por omissao e regressao.
        # `cauc_situacao` nao tem essas colunas (uma linha por municipio), entao
        # o ramo do CAUC manda NULL e a tela nao rotula nada.
        extra = ("c.nome, COALESCE(c.principal, false)" if esfera == "CAGEC"
                 else "NULL::text, true")
        rows = (await db.execute(text(f"""
            SELECT c.municipio_id, COALESCE(m.nome, c.nome), c.itens, c.data_pesquisa,
                   {extra}
            FROM {tabela} c
            LEFT JOIN municipios m ON m.id = c.municipio_id
            WHERE c.municipio_id = ANY(:ids)
        """), {"ids": ids})).fetchall()
        for mid, nome, itens, pesquisa, ent_nome, principal in rows:
            for p in prazos_dos_itens(itens, pesquisa, esfera, dias, hoje):
                out.append({"municipio_id": mid, "municipio": nome,
                            # So quando NAO e a principal: repetir "Prefeitura"
                            # em toda linha e ruido que ninguem le.
                            "entidade": (None if principal else (ent_nome or None)),
                            **p})

    out.sort(key=lambda x: (x["dias_restantes"], x["esfera"], x["codigo"] or ""))
    return out


# --------------------------------------------------------------------------
# Aba: Obras da Saúde (SISMOB)
# --------------------------------------------------------------------------
async def bi_sismob(db: AsyncSession, ids: list[int], anos: Optional[list[int]] = None) -> dict:
    """Obras do SISMOB agregadas para o Painel.

    SET-AWARE e SEQUENCIAL: nada de `asyncio.gather` com sessoes proprias — o
    pool e pool_size=5/max_overflow=10 e abrir N sessoes por request derruba o
    app inteiro, inclusive /auth/login (ver o aviso em _compute_overview).

    A classificacao vem de `sismob_regras.classificar`, a MESMA que a tela e o
    push usam. Se a aba reclassificasse por conta, um dia a TV do gabinete e o
    celular do prefeito discordariam sobre a mesma obra.

    ESTA ABA NAO E FILTRADA POR PERIODO, e isso e deliberado (`anos` chega e e
    ignorado). `ano_referencia` e o ano em que a PROPOSTA foi feita, nao o ano
    em que a obra esta acontecendo. Filtrar por ele apagava exatamente o que a
    aba existe para mostrar: as duas obras paradas de Monte Siao sao propostas
    de 2020 que continuam "Em inicio de execucao" hoje, e a cancelada com
    repasse a devolver e de 2012. Com o periodo "Mandato atual" (2025-2026) —
    que era o que estava salvo em `bi_tela_filtros` — a aba dizia "0 com prazo
    vencido / R$ 0 parado / nenhuma obra precisa de acao" no mesmo minuto em
    que a tela do modulo mostrava 3 obras e R$ 249.648 parados. A TV do
    gabinete e o link publico exibiam a versao que mente.

    Obra em aberto e obrigacao do PRESENTE, independente do ano da proposta.
    Esta e uma aba de estado atual, como a de CAUC/CAGEC (que nem recebe
    `anos`). A tela avisa ao gestor que o filtro de periodo nao se aplica aqui,
    para que "nao filtra" nunca seja confundido com "filtro ignorado por bug".
    """
    if not ids:
        return {"total": 0, "totais": {}, "acao": [], "por_situacao": [],
                "por_programa": [], "execucao": [], "sem_filtro_periodo": True}
    from services.sismob_regras import classificar

    p: dict = {"ids": ids}

    rows = (await db.execute(text(f"""
        SELECT o.proposta_id, o.municipio_id, m.nome AS municipio,
               o.estabelecimento, o.programa, o.tipo_obra, o.tipo_recurso,
               o.co_situacao_obra, o.situacao, o.vl_percentual_executado,
               o.vl_proposta, o.repasse_total, o.dt_primeira_parcela,
               o.dt_conclusao_final, o.dt_inicio_funcionamento, o.nu_cnes, o.co_cnes,
               o.possui_etapa_funcionamento, o.ultima_atividade_em, o.dt_mudanca_situacao,
               -- A regra "repasse sem contrato" olha se ha empresa. Sem esta
               -- contagem, `classificar` recebia a obra SEM empresas e acusava as
               -- duas obras novas: a aba mostrava 5 obras em acao e a tela do
               -- modulo, 3, para o mesmo municipio. As regras ja eram as mesmas;
               -- o que divergia era a ENTRADA.
               (SELECT count(*) FROM sismob_obra_empresas e
                 WHERE e.proposta_id = o.proposta_id) AS n_empresas
        FROM sismob_obras o LEFT JOIN municipios m ON m.id = o.municipio_id
        WHERE o.municipio_id = ANY(:ids) AND o.ausente_desde IS NULL
        ORDER BY o.ultima_atividade_em NULLS FIRST
    """), p)).mappings().all()

    hoje = date.today()
    tot = {"obras": 0, "vivas": 0, "concluidas": 0, "canceladas": 0,
           "valor_proposta": 0.0, "repasse_total": 0.0, "repasse_parado": 0.0,
           "com_prazo_vencido": 0}
    acao, execucao = [], []
    por_situacao: dict[str, dict] = {}
    por_programa: dict[str, dict] = {}

    for r in rows:
        o = dict(r)
        # `classificar` so testa a verdade da lista; a contagem basta.
        o["empresas"] = [1] * int(o.pop("n_empresas", 0) or 0)
        diag = classificar(o, hoje)
        co = o["co_situacao_obra"]
        proposta = _money(o["vl_proposta"])
        repasse = _money(o["repasse_total"])

        tot["obras"] += 1
        tot["valor_proposta"] += proposta
        tot["repasse_total"] += repasse
        if co in (7, 8):
            tot["canceladas"] += 1
        elif co in (3, 4):
            tot["concluidas"] += 1
        else:
            tot["vivas"] += 1
        if any(g["regra"] == "sem_atualizacao" for g in diag["regras"]):
            tot["repasse_parado"] += repasse
        if any(g["regra"] == "etapa90" and (g.get("dias") or 0) > 0 for g in diag["regras"]):
            tot["com_prazo_vencido"] += 1

        for acc, chave in ((por_situacao, o["situacao"]), (por_programa, o["programa"])):
            k = (chave or "").strip() or "Não informado"
            e = acc.setdefault(k, {"label": k, "qtd": 0, "valor": 0.0})
            e["qtd"] += 1
            e["valor"] += proposta

        if diag["regras"]:
            acao.append({
                "proposta_id": o["proposta_id"], "municipio": o["municipio"],
                "estabelecimento": o["estabelecimento"], "programa": o["programa"],
                "situacao": o["situacao"], "percentual": _pct(o["vl_percentual_executado"]),
                "severidade": diag["severidade"],
                # UMA frase por obra na TV: o painel precisa ser lido de longe.
                # O detalhe completo fica na tela do modulo.
                "problema": diag["regras"][0]["titulo"],
                "problemas": len(diag["regras"]),
                "valor": proposta,
            })
        elif co in (0, 1, 2, 5, 6):
            execucao.append({
                "proposta_id": o["proposta_id"], "municipio": o["municipio"],
                "estabelecimento": o["estabelecimento"], "programa": o["programa"],
                "percentual": _pct(o["vl_percentual_executado"]), "valor": proposta,
            })

    ordem = {"critico": 0, "atencao": 1}
    acao.sort(key=lambda i: (ordem.get(i["severidade"], 9), -i["valor"]))
    return {
        "total": tot["obras"],
        "totais": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in tot.items()},
        "acao": acao[:LIMITE_ITENS],
        "execucao": execucao[:LIMITE_ITENS],
        "por_situacao": sorted(por_situacao.values(), key=lambda e: -e["valor"]),
        "por_programa": sorted(por_programa.values(), key=lambda e: -e["valor"]),
        # A tela usa isto para dizer, em uma linha, que o seletor de periodo do
        # Painel nao vale aqui. Sem o aviso, o gestor troca o periodo, nada
        # muda, e ele conclui que a aba travou.
        "sem_filtro_periodo": True,
    }
