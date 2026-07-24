"""Tela Parlamentares — lista agregada cross-fonte com detalhe expansivel.

Agrega nomes de parlamentar (deputados/senadores) de 3 fontes:
  - convenios_estadual.raw_data->>'responsaveis' (SIGCON-MG, "EDUARDO AZEVEDO")
  - transferegov_propostas.parlamentar (SICONV federal)
  - emendas_estaduais.nome_responsavel

Normaliza o nome (uppercase + remove acentos) p/ chave de agrupamento,
mas exibe o melhor nome (maior frequencia + sem U+FFFD).

Endpoints:
  GET  /api/parlamentares                    lista agregada
  GET  /api/parlamentares/{nome_norm}        lancamentos detalhados desse parlamentar
"""
from __future__ import annotations
import unicodedata
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from database import get_db
from services.auth import get_current_user, ensure_municipio_access, ensure_tela
from models.user import User

router = APIRouter(prefix="/api/parlamentares", tags=["parlamentares"])


class _SkipPlanoAcao(Exception):
    """Sentinela p/ pular o fetch AO VIVO do RP9 quando incluir_plano_acao=False.
    Capturado pelo `except Exception` que ja envolve o bloco (degradacao silenciosa)."""


def _norm(s: str) -> str:
    """Normaliza p/ chave de agrupamento: uppercase + sem acentos + 1 espaco."""
    if not s:
        return ""
    s = s.replace("�", "").strip()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = " ".join(s.upper().split())
    return s


def _money(v) -> float:
    try: return float(v or 0)
    except (TypeError, ValueError): return 0.0


def _fns_label(mun_nome: str) -> str:
    """Rotulo do 'parlamentar' para lancamentos FNS: o Fundo Municipal de Saude
    do municipio. O autor da emenda de saude nao vem na base coletada, entao o
    FMS/municipio entra como proponente (mesma logica do PAC)."""
    return f"FUNDO MUNICIPAL DE SAÚDE — {mun_nome}"


@router.get("")
async def listar(
    municipio_id: Optional[int] = Query(None, description="Filtra um municipio (None=todos)"),
    q: Optional[str] = Query(None, description="Busca parcial no nome"),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Lista agregada de parlamentares, com totais cross-fonte.

    Retorna:
      [{
        nome_normalizado: "EDUARDO AZEVEDO",
        nome_display: "EDUARDO AZEVEDO",       # melhor representacao
        total_lancamentos: 12,
        valor_total: 1234567.89,
        municipios: ["Araujos", "Bom Despacho"],
        por_fonte: {sigcon: 8, voluntaria: 2, emenda: 2},
      }, ...]
    """
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parlamentares")
    return await aggregate_parlamentares(db, municipio_id=municipio_id, q=q, ano=ano)


async def aggregate_parlamentares(
    db: AsyncSession,
    municipio_id: Optional[int] = None,
    q: Optional[str] = None,
    ano: Optional[int] = None,
    incluir_plano_acao: bool = True,
    municipio_ids: Optional[list[int]] = None,
) -> dict:
    """Nucleo da agregacao cross-fonte de parlamentares, SEM gate de auth.

    Reusado pelo endpoint /api/parlamentares (apos ensure_tela) e pelo Painel
    Executivo do prefeito (gated so por municipio). incluir_plano_acao=False pula
    o fetch AO VIVO do RP9 federal (mais rapido, p/ telas snappy).

    `municipio_ids` (lista) = escopo CONSOLIDADO da assessoria: agrega sobre esse
    CONJUNTO (`= ANY(:muns)`). Ignorado quando `municipio_id` (unico) e informado;
    ausentes ambos = todos (comportamento original preservado)."""
    by_norm: dict[str, dict] = defaultdict(lambda: {
        "nome_normalizado": "",
        "nome_display": "",
        "nome_variants": set(),
        "total_lancamentos": 0,
        "valor_total": 0.0,
        "municipios": set(),
        "por_fonte": {"sigcon": 0, "voluntaria": 0, "emenda": 0, "plano_acao": 0, "pac": 0, "fns": 0},
    })

    where_extra = ""
    params: dict = {}
    if municipio_id:
        where_extra = " AND municipio_id = :mun"
        params["mun"] = municipio_id
    elif municipio_ids:
        where_extra = " AND municipio_id = ANY(:muns)"
        params["muns"] = list(municipio_ids)

    # Filtro de ano — a fonte do ano difere por tabela:
    #   convenios_estadual/emendas_estaduais -> coluna `ano`
    #   transferegov_propostas -> derivado do sufixo do numero_proposta ("xxx/AAAA")
    ano_sig = ano_vol = ano_em = ""
    if ano:
        ano_sig = " AND ano = :ano"
        ano_em = " AND ano = :ano"
        ano_vol = " AND split_part(numero_proposta, '/', 2) = :ano_txt"
        params["ano"] = ano
        params["ano_txt"] = str(ano)

    # 1) convenios_estadual: SIGCON (responsaveis) E FNS (noAutor/noParlamentar)
    # Federal FNS pode ter campos noAutor, noParlamentar, dsAutor — variações
    # diferentes entre cadastros antigos e emendas individuais.
    sql_sigcon = f"""
        SELECT
            COALESCE(
                raw_data->>'responsaveis',
                raw_data->>'noAutor',
                raw_data->>'noParlamentar',
                raw_data->>'dsAutor',
                raw_data->>'parlamentar',
                ''
            ) AS nome,
            municipio_id,
            (SELECT nome FROM municipios WHERE id=convenios_estadual.municipio_id) AS mun_nome,
            COALESCE(valor_total, valor_concedente, 0) AS valor,
            COALESCE(fonte, '') AS fonte_db
        FROM convenios_estadual
        WHERE (
            raw_data->>'responsaveis' IS NOT NULL
            OR raw_data->>'noAutor' IS NOT NULL
            OR raw_data->>'noParlamentar' IS NOT NULL
            OR raw_data->>'dsAutor' IS NOT NULL
            OR raw_data->>'parlamentar' IS NOT NULL
        )
        {where_extra}{ano_sig}
    """
    for row in (await db.execute(text(sql_sigcon), params)).fetchall():
        for nm in str(row[0] or "").split(","):
            nm = nm.strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            # classifica por fonte: FNS é federal, SIGCON-MG é estadual
            fonte_db = (row[4] or "").upper()
            if "FNS" in fonte_db or "MS" in fonte_db:
                entry["por_fonte"]["voluntaria"] += 1  # contagem federal usa esse bucket
            else:
                entry["por_fonte"]["sigcon"] += 1

    # 2) TransfereGov Voluntarias (parlamentar)
    sql_vol = f"""
        SELECT
            parlamentar AS nome,
            municipio_id,
            (SELECT nome FROM municipios WHERE id=transferegov_propostas.municipio_id) AS mun_nome,
            COALESCE(valor_global, valor_repasse, 0) AS valor
        FROM transferegov_propostas
        WHERE parlamentar IS NOT NULL
        AND LENGTH(TRIM(parlamentar)) >= 3
        {where_extra}{ano_vol}
    """
    for row in (await db.execute(text(sql_vol), params)).fetchall():
        for nm in str(row[0] or "").split(","):
            nm = nm.strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            entry["por_fonte"]["voluntaria"] += 1

    # 3) Emendas Estaduais (nome_responsavel)
    sql_em = f"""
        SELECT
            nome_responsavel AS nome,
            municipio_id,
            (SELECT nome FROM municipios WHERE id=emendas_estaduais.municipio_id) AS mun_nome,
            COALESCE(valor_indicacao, 0) AS valor
        FROM emendas_estaduais
        WHERE nome_responsavel IS NOT NULL
        AND LENGTH(TRIM(nome_responsavel)) >= 3
        {where_extra}{ano_em}
    """
    for row in (await db.execute(text(sql_em), params)).fetchall():
        for nm in str(row[0] or "").split(","):
            nm = nm.strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            entry["por_fonte"]["emenda"] += 1

    # 4) Transferencia Especial / Plano de Acao (RP9, "emenda Pix") — AO VIVO.
    # Fonte federal que NAO fica no banco (API nacional, cache 1h no router
    # transferegov). E por onde chega a maioria das emendas de deputado FEDERAL.
    # O autor vem embutido em codigoEmendaFormatado ('<codigo>-<Nome>').
    # Degrada em silencio se a API cair — nao pode derrubar a tela.
    try:
        if not incluir_plano_acao:
            raise _SkipPlanoAcao()
        from routers.transferegov import _fetch_listagem
        muns_sql = "SELECT id, nome, uf FROM municipios WHERE active = true"
        mparams: dict = {}
        if municipio_id:
            muns_sql += " AND id = :mid"; mparams["mid"] = municipio_id
        elif municipio_ids:
            muns_sql += " AND id = ANY(:mids)"; mparams["mids"] = list(municipio_ids)
        muns = (await db.execute(text(muns_sql), mparams)).fetchall()
        listagens: dict[str, list] = {}
        for m in muns:
            if m.uf not in listagens:
                try:
                    listagens[m.uf] = await _fetch_listagem(m.uf)
                except Exception:
                    listagens[m.uf] = []
        for m in muns:
            mn = _norm(m.nome)
            for it in listagens.get(m.uf, []):
                ben = _norm(it.get("beneficiarioNome") or "")
                if not (mn in ben or ben.endswith(mn)):
                    continue
                if ano:
                    pc = str(it.get("programaCodigo") or "")
                    if (pc[4:8] if len(pc) >= 8 else "") != str(ano):
                        continue
                _, _, autor = (it.get("codigoEmendaFormatado") or "").partition("-")
                autor = autor.strip()
                if not autor or len(autor) < 3:
                    continue  # sem emenda nominal (institucional) -> fora do ranking
                key = _norm(autor)
                if not key:
                    continue
                entry = by_norm[key]
                entry["nome_variants"].add(autor)
                entry["total_lancamentos"] += 1
                entry["valor_total"] += _money(it.get("valorTotal"))
                entry["municipios"].add(m.nome)
                entry["por_fonte"]["plano_acao"] += 1
    except Exception:
        pass

    # 5) Selecao PAC / Novo PAC — o PROPONENTE entra como "parlamentar" (ou a
    #    emenda parlamentar quando houver). Fonte: transferegov_pac.
    ano_pac = " AND split_part(numero_proposta, '/', 2) = :ano_txt" if ano else ""
    sql_pac = f"""
        SELECT COALESCE(NULLIF(TRIM(emenda_parlamentar), ''), proponente) AS nome,
               municipio_id,
               (SELECT nome FROM municipios WHERE id=transferegov_pac.municipio_id) AS mun_nome,
               COALESCE(valor_total, 0) AS valor
        FROM transferegov_pac
        WHERE COALESCE(NULLIF(TRIM(emenda_parlamentar), ''), proponente) IS NOT NULL
        {where_extra}{ano_pac}
    """
    try:
        for row in (await db.execute(text(sql_pac), params)).fetchall():
            nm = (row[0] or "").strip()
            if not nm or len(nm) < 3:
                continue
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[3])
            if row[2]:
                entry["municipios"].add(row[2])
            entry["por_fonte"]["pac"] += 1
    except Exception:
        pass

    # 6) FNS (Fundo Municipal de Saude) — o autor da emenda de saude NAO vem na
    #    base coletada (0 parlamentar em todas as propostas), entao o FMS do
    #    municipio entra como "parlamentar" (mesma logica do PAC). Fonte:
    #    convenios_estadual com fonte ILIKE 'FNS' (nao capturado pela fonte #1,
    #    que exige parlamentar top-level no raw_data — sempre nulo no FNS).
    sql_fns = f"""
        SELECT (SELECT nome FROM municipios WHERE id=convenios_estadual.municipio_id) AS mun_nome,
               COALESCE(valor_total, valor_concedente, 0) AS valor
        FROM convenios_estadual
        WHERE fonte ILIKE '%FNS%'
        {where_extra}{ano_sig}
    """
    try:
        for row in (await db.execute(text(sql_fns), params)).fetchall():
            mun_nome = row[0]
            if not mun_nome:
                continue
            nm = _fns_label(mun_nome)
            key = _norm(nm)
            if not key:
                continue
            entry = by_norm[key]
            entry["nome_variants"].add(nm)
            entry["total_lancamentos"] += 1
            entry["valor_total"] += _money(row[1])
            entry["municipios"].add(mun_nome)
            entry["por_fonte"]["fns"] += 1
    except Exception:
        pass

    # Resolve nome_display: prefere a variante mais comum sem U+FFFD
    out = []
    for key, entry in by_norm.items():
        variants = list(entry["nome_variants"])
        # ordena: 1) sem U+FFFD primeiro, 2) mais "completo" (mais espacos)
        variants.sort(key=lambda v: (
            "�" in v,
            -len(v.split()),
            -len(v),
        ))
        entry["nome_normalizado"] = key
        entry["nome_display"] = (variants[0] if variants else key).replace("�", "").strip()
        del entry["nome_variants"]
        entry["municipios"] = sorted(entry["municipios"])
        out.append(entry)

    # Filtro de busca textual
    if q:
        q_norm = _norm(q)
        out = [e for e in out if q_norm in e["nome_normalizado"]]

    # Ordena por total descendente
    out.sort(key=lambda e: (-e["total_lancamentos"], -e["valor_total"]))

    return {"items": out, "total": len(out)}


@router.get("/{nome_normalizado:path}")
async def detalhe(
    nome_normalizado: str,
    municipio_id: Optional[int] = Query(None),
    ano: Optional[int] = Query(None, description="Filtra por ano (None=todos)"),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Retorna todos os lancamentos (convenios/propostas/emendas) desse parlamentar."""
    ensure_municipio_access(current, municipio_id)
    ensure_tela(current, "parlamentares")
    # Aceita tanto chave normalizada quanto nome livre
    nome_param = nome_normalizado.replace("+", " ")
    # Busca por ILIKE em cada fonte com o nome original (case-insensitive)
    where_extra = ""
    params: dict = {"n": f"%{nome_param}%"}
    if municipio_id:
        where_extra_sigcon = " AND c.municipio_id = :mun"
        where_extra_vol = " AND v.municipio_id = :mun"
        where_extra_em = " AND e.municipio_id = :mun"
        params["mun"] = municipio_id
    else:
        where_extra_sigcon = where_extra_vol = where_extra_em = ""
    # Filtro de ano (fonte do ano difere por tabela — ver endpoint listar)
    if ano:
        where_extra_sigcon += " AND c.ano = :ano"
        where_extra_vol += " AND split_part(v.numero_proposta, '/', 2) = :ano_txt"
        where_extra_em += " AND e.ano = :ano"
        params["ano"] = ano
        params["ano_txt"] = str(ano)

    # SIGCON
    sql1 = f"""
        SELECT c.id, c.municipio_id, m.nome AS mun_nome,
               c.nr_sigcon, c.objeto, c.situacao,
               c.valor_total, c.valor_concedente,
               c.raw_data->>'responsaveis' AS responsaveis,
               c.dt_vigencia_inicial, c.dt_vigencia_atual, c.dt_vigencia_final,
               c.ano, c.orgao_concedente
        FROM convenios_estadual c LEFT JOIN municipios m ON m.id = c.municipio_id
        WHERE c.raw_data->>'responsaveis' ILIKE :n
        {where_extra_sigcon}
        ORDER BY c.ano DESC NULLS LAST, c.dt_publicacao DESC NULLS LAST
    """
    sigcon = [{
        "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
        "numero": r[3], "objeto": r[4], "situacao": r[5],
        "valor_total": _money(r[6]), "valor_repasse": _money(r[7]),
        "responsaveis": r[8],
        "dt_vigencia_inicial": str(r[9]) if r[9] else None,
        "dt_vigencia_atual": str(r[10]) if r[10] else None,
        "dt_vigencia_final": str(r[11]) if r[11] else None,
        "ano": r[12], "orgao": r[13],
        "fonte": "sigcon",
    } for r in (await db.execute(text(sql1), params)).fetchall()]

    # Voluntarias
    sql2 = f"""
        SELECT v.id, v.municipio_id,
               (SELECT nome FROM municipios WHERE id=v.municipio_id) AS mun_nome,
               v.numero_proposta, v.codigo_instrumento, v.objeto, v.situacao,
               v.valor_global, v.valor_repasse, v.parlamentar,
               v.dt_inicio_vigencia, v.dt_fim_vigencia, v.orgao,
               v.situacao_contratacao, v.situacao_contratacao_detalhe
        FROM transferegov_propostas v
        WHERE v.parlamentar ILIKE :n
        {where_extra_vol}
        ORDER BY v.numero_proposta DESC
    """
    voluntarias = [{
        "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
        "numero_proposta": r[3], "codigo_instrumento": r[4],
        "objeto": r[5], "situacao": r[6],
        "valor_global": _money(r[7]), "valor_repasse": _money(r[8]),
        "parlamentar": r[9],
        "dt_inicio_vigencia": r[10], "dt_fim_vigencia": r[11],
        "orgao": r[12],
        "situacao_contratacao": r[13],
        "situacao_contratacao_detalhe": r[14] if isinstance(r[14], dict) else None,
        "fonte": "voluntaria",
    } for r in (await db.execute(text(sql2), params)).fetchall()]

    # Emendas
    sql3 = f"""
        SELECT e.id, e.municipio_id,
               (SELECT nome FROM municipios WHERE id=e.municipio_id) AS mun_nome,
               e.nr_indicacao, e.ano, e.beneficiario, e.tipo_atendimento,
               e.valor_indicacao, e.nome_responsavel, e.status_indicacao,
               e.uo_sigla
        FROM emendas_estaduais e
        WHERE e.nome_responsavel ILIKE :n
        {where_extra_em}
        ORDER BY e.ano DESC NULLS LAST
    """
    emendas = [{
        "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
        "nr_indicacao": r[3], "ano": r[4],
        "beneficiario": r[5], "tipo_atendimento": r[6],
        "valor_indicacao": _money(r[7]),
        "nome_responsavel": r[8], "status_indicacao": r[9],
        "uo_sigla": r[10],
        "fonte": "emenda",
    } for r in (await db.execute(text(sql3), params)).fetchall()]

    # Plano de Acao / Transferencia Especial (RP9) — AO VIVO (mesma fonte da tela
    # TransfereGov). Autor vem em codigoEmendaFormatado ('<codigo>-<Nome>').
    plano_acao: list = []
    try:
        from routers.transferegov import _fetch_listagem
        alvo = _norm(nome_param)
        muns_sql = "SELECT id, nome, uf FROM municipios WHERE active = true"
        mp: dict = {}
        if municipio_id:
            muns_sql += " AND id = :mun"; mp["mun"] = municipio_id
        muns = (await db.execute(text(muns_sql), mp)).fetchall()
        listagens: dict[str, list] = {}
        for m in muns:
            if m.uf not in listagens:
                try:
                    listagens[m.uf] = await _fetch_listagem(m.uf)
                except Exception:
                    listagens[m.uf] = []
        for m in muns:
            mn = _norm(m.nome)
            for it in listagens.get(m.uf, []):
                ben = _norm(it.get("beneficiarioNome") or "")
                if not (mn in ben or ben.endswith(mn)):
                    continue
                code, _, autor = (it.get("codigoEmendaFormatado") or "").partition("-")
                if not autor or alvo not in _norm(autor):
                    continue
                if ano:
                    pc = str(it.get("programaCodigo") or "")
                    if (pc[4:8] if len(pc) >= 8 else "") != str(ano):
                        continue
                plano_acao.append({
                    "id": it.get("planoAcaoId"),
                    "municipio_id": m.id, "municipio_nome": m.nome,
                    "codigo": it.get("planoAcaoCodigo"),
                    "emenda": code.strip(),
                    "parlamentar": autor.strip(),
                    "objeto": it.get("objetoDescricao") or it.get("politicasPublicas"),
                    "situacao": it.get("planoAcaoSituacao"),
                    "valor_total": _money(it.get("valorTotal")),
                    "valor_custeio": _money(it.get("valorCusteio")),
                    "valor_investimento": _money(it.get("valorInvestimento")),
                    "fonte": "plano_acao",
                })
    except Exception:
        pass
    plano_acao.sort(key=lambda x: x["valor_total"], reverse=True)

    # Selecao PAC / Novo PAC — proponente (ou emenda) como parlamentar
    pac_list: list = []
    try:
        pac_sql = """
            SELECT id, municipio_id,
                   (SELECT nome FROM municipios WHERE id=transferegov_pac.municipio_id) AS mun,
                   numero_proposta, programa, situacao, valor_total,
                   emenda_parlamentar, proponente, objeto
            FROM transferegov_pac
            WHERE COALESCE(NULLIF(TRIM(emenda_parlamentar), ''), proponente) ILIKE :n
        """
        pac_params: dict = {"n": f"%{nome_param}%"}
        if municipio_id:
            pac_sql += " AND municipio_id = :mun"; pac_params["mun"] = municipio_id
        if ano:
            pac_sql += " AND split_part(numero_proposta, '/', 2) = :ano_txt"; pac_params["ano_txt"] = str(ano)
        pac_sql += " ORDER BY valor_total DESC NULLS LAST"
        for r in (await db.execute(text(pac_sql), pac_params)).fetchall():
            pac_list.append({
                "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
                "numero_proposta": r[3], "programa": r[4], "situacao": r[5],
                "valor_total": _money(r[6]), "emenda_parlamentar": r[7],
                "proponente": r[8], "objeto": r[9], "fonte": "pac",
            })
    except Exception:
        pass

    # FNS — Fundo Municipal de Saude do municipio como "parlamentar" (mesma
    # logica do PAC; o autor da emenda de saude nao vem na base). Casa por
    # comparacao normalizada do rotulo FMS (evita problema de acento no ILIKE).
    fns_list: list = []
    try:
        alvo = _norm(nome_param)
        fns_sql = """
            SELECT c.id, c.municipio_id,
                   (SELECT nome FROM municipios WHERE id=c.municipio_id) AS mun,
                   c.nr_sigcon, c.nr_proposta, c.objeto, c.situacao,
                   COALESCE(c.valor_total, c.valor_concedente, 0) AS valor,
                   c.orgao_concedente, c.ano,
                   c.dt_vigencia_inicial, c.dt_vigencia_final
            FROM convenios_estadual c
            WHERE c.fonte ILIKE '%FNS%'
        """
        fns_params: dict = {}
        if municipio_id:
            fns_sql += " AND c.municipio_id = :mun"; fns_params["mun"] = municipio_id
        if ano:
            fns_sql += " AND c.ano = :ano"; fns_params["ano"] = ano
        fns_sql += " ORDER BY valor DESC NULLS LAST"
        for r in (await db.execute(text(fns_sql), fns_params)).fetchall():
            mun_nome = r[2] or ""
            label_key = _norm(_fns_label(mun_nome))
            if alvo and alvo not in label_key and label_key not in alvo:
                continue
            fns_list.append({
                "id": r[0], "municipio_id": r[1], "municipio_nome": r[2],
                "numero": r[3] or r[4], "objeto": r[5], "situacao": r[6],
                "valor_total": _money(r[7]), "orgao": r[8], "ano": r[9],
                "dt_vigencia_inicial": str(r[10]) if r[10] else None,
                "dt_vigencia_final": str(r[11]) if r[11] else None,
                "proponente": _fns_label(mun_nome), "fonte": "fns",
            })
    except Exception:
        pass

    if not (sigcon or voluntarias or emendas or plano_acao or pac_list or fns_list):
        raise HTTPException(404, f"Nenhum lancamento encontrado para '{nome_param}'")

    return {
        "nome_consulta": nome_param,
        "sigcon": sigcon,
        "voluntarias": voluntarias,
        "emendas": emendas,
        "plano_acao": plano_acao,
        "pac": pac_list,
        "fns": fns_list,
        "total_sigcon": len(sigcon),
        "total_voluntarias": len(voluntarias),
        "total_emendas": len(emendas),
        "total_plano_acao": len(plano_acao),
        "total_pac": len(pac_list),
        "total_fns": len(fns_list),
        "total_geral": len(sigcon) + len(voluntarias) + len(emendas) + len(plano_acao) + len(pac_list) + len(fns_list),
        "valor_total": (
            sum(x["valor_total"] for x in sigcon)
            + sum(x["valor_global"] for x in voluntarias)
            + sum(x["valor_indicacao"] for x in emendas)
            + sum(x["valor_total"] for x in plano_acao)
            + sum(x["valor_total"] for x in pac_list)
            + sum(x["valor_total"] for x in fns_list)
        ),
    }
