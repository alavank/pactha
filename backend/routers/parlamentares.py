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
    by_norm: dict[str, dict] = defaultdict(lambda: {
        "nome_normalizado": "",
        "nome_display": "",
        "nome_variants": set(),
        "total_lancamentos": 0,
        "valor_total": 0.0,
        "municipios": set(),
        "por_fonte": {"sigcon": 0, "voluntaria": 0, "emenda": 0, "plano_acao": 0},
    })

    where_extra = ""
    params: dict = {}
    if municipio_id:
        where_extra = " AND municipio_id = :mun"
        params["mun"] = municipio_id

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
        from routers.transferegov import _fetch_listagem
        muns_sql = "SELECT id, nome, uf FROM municipios WHERE active = true"
        mparams: dict = {}
        if municipio_id:
            muns_sql += " AND id = :mid"; mparams["mid"] = municipio_id
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

    if not (sigcon or voluntarias or emendas or plano_acao):
        raise HTTPException(404, f"Nenhum lancamento encontrado para '{nome_param}'")

    return {
        "nome_consulta": nome_param,
        "sigcon": sigcon,
        "voluntarias": voluntarias,
        "emendas": emendas,
        "plano_acao": plano_acao,
        "total_sigcon": len(sigcon),
        "total_voluntarias": len(voluntarias),
        "total_emendas": len(emendas),
        "total_plano_acao": len(plano_acao),
        "total_geral": len(sigcon) + len(voluntarias) + len(emendas) + len(plano_acao),
        "valor_total": (
            sum(x["valor_total"] for x in sigcon)
            + sum(x["valor_global"] for x in voluntarias)
            + sum(x["valor_indicacao"] for x in emendas)
            + sum(x["valor_total"] for x in plano_acao)
        ),
    }
