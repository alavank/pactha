"""Builder do Relatorio de Monitoramento (RM).

Monta o conteudo JSONB inicial agregando o que ja temos no banco:
  - convenios_estaduais (SIGCON-MG)
  - transferegov_propostas (Voluntarias SICONV)
  - simec_par_liberacoes (MEC - PNAE/PNATE/QUOTA/etc)
  - emendas_estaduais (Indicacoes SIGCON Estaduais)

Estrutura gerada (3 partes seguindo o padrao Freitas):
  PARTE 1 - DEMANDAS EM BRASILIA (federais, ainda em analise/aprovacao)
  PARTE 2 - DEMANDAS DO MUNICIPIO (federais + estaduais, em execucao local)
  PARTE 3 - PAGAMENTOS ANTERIORES / PRESTACAO DE CONTAS (vencidos ou pagos)

O usuario depois reorganiza tudo manualmente (edicao completa por item).
"""
from __future__ import annotations
from datetime import date
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from models import ConvenioEstadual, Municipio


_VOL_LIKE = "%enviado para an%lise%"
_REJ_LIKE = "%rejeitad%"


def _money(x) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _iso(d) -> str | None:
    if not d:
        return None
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _classifica_parte(situacao: str | None, dt_fim: date | None, situacao_atual: str = "") -> int:
    """Heuristica: decide qual PARTE o item entra (1, 2 ou 3)."""
    s = (situacao or "").lower() + " " + (situacao_atual or "").lower()
    hoje = date.today()
    # PARTE 3: pagamento realizado + vencido OU prestacao de contas
    if "presta" in s and "conta" in s:
        return 3
    if dt_fim and dt_fim < hoje:
        return 3
    # PARTE 2: em execucao / aprovado / vigencia futura
    if any(k in s for k in ["execu", "aprovad", "assinad", "pagament", "celebrad"]):
        return 2
    # PARTE 1 (default): demandas em Brasilia (analise / pendente / proposta)
    return 1


async def montar_conteudo(db: AsyncSession, municipio_id: int) -> dict:
    """Monta o conteudo JSONB de um RM a partir dos dados do banco."""
    # Estrutura: {partes: [{ordem, titulo, secoes: [{ordem, titulo, grupos:
    #   [{ordem, orgao, itens: [...]}]}]}]}
    # Build incrementally then convert.
    partes_data = {
        1: {"titulo": "PARTE 1 - DEMANDAS EM BRASÍLIA", "secoes": {}},
        2: {"titulo": "PARTE 2 - DEMANDAS DO MUNICÍPIO", "secoes": {}},
        3: {"titulo": "PARTE 3 - PRESTAÇÕES DE CONTAS / PAGAMENTOS DE ANOS ANTERIORES", "secoes": {}},
    }

    def add_item(parte_n: int, secao: str, orgao: str, item: dict):
        p = partes_data[parte_n]
        if secao not in p["secoes"]:
            p["secoes"][secao] = {}
        if orgao not in p["secoes"][secao]:
            p["secoes"][secao][orgao] = []
        p["secoes"][secao][orgao].append(item)

    # === SIGCON Estaduais (convenios_estaduais) ===
    rs = await db.execute(
        select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )
    for c in rs.scalars().all():
        raw = c.raw_data if isinstance(c.raw_data, dict) else {}
        nr_proposta = raw.get("nr_proposta") or c.nr_plano_trabalho
        nr_instr = raw.get("nr_instrumento") or (c.nr_sigcon if c.nr_sigcon and "/" in c.nr_sigcon else None)
        identificador = nr_instr or nr_proposta or c.nr_sigcon or ""
        tipo_label = "Convênio" if nr_instr else "Proposta"
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        parte = _classifica_parte(c.situacao, dt_fim)
        orgao = (c.orgao_concedente or "Outros - SIGCON").strip() + " - SIGCON"
        add_item(parte, "INSTRUMENTOS DE REPASSE ESTADUAIS", orgao, {
            "tipo": tipo_label,
            "numero": identificador,
            "objeto": c.objeto or "",
            "parlamentar": raw.get("parlamentar") or raw.get("indicacao") or "",
            "valor_global": _money(c.valor_total),
            "valor_repasse": _money(c.valor_concedente),
            "valor_contrapartida": _money(c.valor_contrapartida),
            "banco": c.banco or "",
            "agencia": c.agencia or "",
            "conta": c.conta_corrente or "",
            "saldo_bancario": _money(c.saldo_bancario),
            "dt_saldo": _iso(c.dt_saldo),
            "dt_fim_vigencia": _iso(dt_fim),
            "situacao_atual": (c.situacao or "").strip(),
            "fonte": "sigcon",
            "fonte_ref": str(c.id),
        })

    # === TransfereGov Voluntarias (SICONV) ===
    vol = await db.execute(text("""
        SELECT id, numero_proposta, codigo_instrumento, situacao, orgao, objeto,
               dt_fim_vigencia, valor_global, valor_repasse, valor_contrapartida,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar
        FROM transferegov_propostas WHERE municipio_id = :m
    """), {"m": municipio_id})
    for row in vol.fetchall():
        sit = row[3] or ""
        # pula rejeitadas no rascunho inicial
        if "rejeitad" in sit.lower():
            continue
        dt_fim = None
        try:
            from datetime import datetime as _dt
            dt_fim = _dt.strptime(str(row[6])[:10], "%d/%m/%Y").date() if row[6] else None
        except (ValueError, TypeError):
            pass
        tipo_label = "Convênio" if row[2] else "Proposta"
        parte = _classifica_parte(sit, dt_fim)
        orgao = (row[4] or "Outros - Federal").strip()
        # Monta narrativa de Situação Atual incluindo situacao_contratacao + clausula
        situacao_contr = row[10]
        cl_dt = row[11]; cl_motivo = row[12]
        narrativa_parts = [sit] if sit else []
        if situacao_contr:
            narrativa_parts.append(f"Situação de Contratação: {situacao_contr}.")
        if cl_dt:
            narrativa_parts.append(f"Cláusula Suspensiva vence em {cl_dt.strftime('%d/%m/%Y')}.")
        if cl_motivo:
            narrativa_parts.append(f"Motivo: {cl_motivo}.")
        situacao_atual = " ".join(narrativa_parts)
        add_item(parte, "INSTRUMENTOS DE REPASSE FEDERAIS", orgao, {
            "tipo": tipo_label,
            "numero": row[2] or row[1],
            "objeto": row[5] or "",
            "parlamentar": row[13] or "",
            "valor_global": _money(row[7]),
            "valor_repasse": _money(row[8]),
            "valor_contrapartida": _money(row[9]),
            "banco": "", "agencia": "", "conta": "",
            "saldo_bancario": None, "dt_saldo": None,
            "dt_fim_vigencia": _iso(dt_fim),
            "situacao_atual": situacao_atual,
            "situacao_contratacao": situacao_contr or "",
            "clausula_suspensiva_dt_prevista": _iso(cl_dt),
            "clausula_suspensiva_motivo": cl_motivo or "",
            "fonte": "voluntaria",
            "fonte_ref": row[1],
        })

    # === SIMEC liberacoes (MEC) -> agrupado por programa, ja sao pagamentos => PARTE 3 ===
    lb = await db.execute(text("""
        SELECT programa, programa_full, dt_pgto, ob, valor, descricao, banco, agencia, conta, ano
        FROM simec_par_liberacoes WHERE municipio_id = :m
        ORDER BY dt_pgto DESC NULLS LAST
    """), {"m": municipio_id})
    for r in lb.fetchall():
        orgao = "Ministério da Educação"
        add_item(3, "INSTRUMENTOS DE REPASSE FEDERAIS", orgao, {
            "tipo": r[0] or "MEC",
            "numero": r[3] or "",
            "objeto": r[5] or r[1] or r[0],
            "parlamentar": "",
            "valor_global": _money(r[4]),
            "valor_repasse": _money(r[4]),
            "valor_contrapartida": 0,
            "banco": r[6] or "", "agencia": r[7] or "", "conta": r[8] or "",
            "saldo_bancario": None, "dt_saldo": None,
            "dt_fim_vigencia": None,
            "situacao_atual": f"Pagamento realizado em {_iso(r[2]) or '-'}.",
            "fonte": "simec",
            "fonte_ref": r[3] or "",
        })

    # === Emendas Estaduais (indicacoes SIGCON) -> normalmente Parte 1 (em analise) ===
    em = await db.execute(text("""
        SELECT id, nr_indicacao, ano, beneficiario, tipo_atendimento, uo_sigla,
               valor_indicacao, nome_responsavel, status_indicacao
        FROM emendas_estaduais WHERE municipio_id = :m
    """), {"m": municipio_id})
    for r in em.fetchall():
        sit = r[8] or ""
        parte = _classifica_parte(sit, None)
        orgao = (r[5] or "SIGCON Estadual") + " - Indicação"
        objeto = f"{r[3] or ''} {r[4] or ''}".strip()
        add_item(parte, "INSTRUMENTOS DE REPASSE ESTADUAIS", orgao, {
            "tipo": "Indicação",
            "numero": f"{r[1]}/{r[2]}" if r[2] else r[1],
            "objeto": objeto,
            "parlamentar": r[7] or "",
            "valor_global": _money(r[6]),
            "valor_repasse": _money(r[6]),
            "valor_contrapartida": 0,
            "banco": "", "agencia": "", "conta": "",
            "saldo_bancario": None, "dt_saldo": None,
            "dt_fim_vigencia": None,
            "situacao_atual": sit,
            "fonte": "emenda_estadual",
            "fonte_ref": str(r[0]),
        })

    # === Converte dict -> lista ordenada (formato final) ===
    out_partes = []
    for n in sorted(partes_data.keys()):
        p = partes_data[n]
        secoes_out = []
        for s_idx, (s_titulo, grupos) in enumerate(p["secoes"].items(), start=1):
            grupos_out = []
            for g_idx, (orgao, itens) in enumerate(grupos.items(), start=1):
                # ordena itens por ano descendente (extraindo do numero) + numero
                grupos_out.append({
                    "ordem": g_idx,
                    "orgao": orgao,
                    "itens": [{"ordem": i + 1, **it} for i, it in enumerate(itens)],
                })
            secoes_out.append({"ordem": s_idx, "titulo": s_titulo, "grupos": grupos_out})
        if secoes_out:
            out_partes.append({"ordem": n, "titulo": p["titulo"], "secoes": secoes_out})
    return {"partes": out_partes}
