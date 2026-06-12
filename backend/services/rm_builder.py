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


def _is_prestacao_contas(situacao: str | None, dt_fim: date | None, situacao_atual: str = "") -> bool:
    """Retorna True quando o item deve cair em PARTE 3 (prestacao de contas /
    pagamento ja realizado / vigencia ja vencida)."""
    s = (situacao or "").lower() + " " + (situacao_atual or "").lower()
    if "presta" in s and "conta" in s:
        return True
    if dt_fim and dt_fim < date.today():
        return True
    return False


def _classifica_parte(esfera: str, situacao: str | None, dt_fim: date | None, situacao_atual: str = "") -> int:
    """Decide a PARTE baseado em FONTE/ESFERA:
      - federal  → PARTE 1 (DEMANDAS EM BRASILIA)
      - estadual → PARTE 2 (DEMANDAS DO MUNICIPIO)
      - prestacao_contas (qualquer fonte com status de prestacao ou vencido) → PARTE 3
    """
    if _is_prestacao_contas(situacao, dt_fim, situacao_atual):
        return 3
    return 1 if esfera == "federal" else 2


async def montar_conteudo(db: AsyncSession, municipio_id: int) -> dict:
    """Monta o conteudo JSONB de um RM a partir dos dados do banco."""
    # Estrutura: {partes: [{ordem, titulo, secoes: [{ordem, titulo, grupos:
    #   [{ordem, orgao, itens: [...]}]}]}]}
    # Build incrementally then convert.
    partes_data = {
        1: {"titulo": "PARTE 1 - DEMANDAS EM BRASÍLIA (Instrumentos Federais)", "secoes": {}},
        2: {"titulo": "PARTE 2 - DEMANDAS DO MUNICÍPIO (Instrumentos Estaduais)", "secoes": {}},
        3: {"titulo": "PARTE 3 - PRESTAÇÕES DE CONTAS / PAGAMENTOS DE ANOS ANTERIORES", "secoes": {}},
    }

    def add_item(parte_n: int, secao: str, orgao: str, item: dict):
        p = partes_data[parte_n]
        if secao not in p["secoes"]:
            p["secoes"][secao] = {}
        if orgao not in p["secoes"][secao]:
            p["secoes"][secao][orgao] = []
        p["secoes"][secao][orgao].append(item)

    # === Convenios estaduais E FNS (mesma tabela, diferenciados por c.fonte) ===
    # SIGCON-MG => estadual => PARTE 2 / INSTRUMENTOS ESTADUAIS
    # FNS (Min Saude) => federal => PARTE 1 / INSTRUMENTOS FEDERAIS
    rs = await db.execute(
        select(ConvenioEstadual).where(ConvenioEstadual.municipio_id == municipio_id)
    )
    for c in rs.scalars().all():
        raw = c.raw_data if isinstance(c.raw_data, dict) else {}
        fonte_db = (c.fonte or "").upper()
        is_fns = "FNS" in fonte_db or "MS" in fonte_db
        nr_proposta = raw.get("nr_proposta") or c.nr_plano_trabalho
        nr_instr = raw.get("nr_instrumento") or (c.nr_sigcon if c.nr_sigcon and "/" in c.nr_sigcon else None)
        identificador = nr_instr or nr_proposta or c.nr_sigcon or ""
        tipo_label = "Convênio" if nr_instr else ("Proposta SUS" if is_fns else "Proposta")
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final
        if is_fns:
            esfera = "federal"
            secao = "INSTRUMENTOS DE REPASSE FEDERAIS"
            orgao = (c.orgao_concedente or "Ministério da Saúde — FNS").strip()
            fonte_label = "fns"
        else:
            esfera = "estadual"
            secao = "INSTRUMENTOS DE REPASSE ESTADUAIS"
            orgao = (c.orgao_concedente or "Outros - SIGCON").strip() + " - SIGCON"
            fonte_label = "sigcon"
        parte = _classifica_parte(esfera, c.situacao, dt_fim)
        # SIGCON-MG armazena o parlamentar como 'responsaveis' no raw_data
        # (deputado estadual/federal autor da indicacao). FNS pode ter
        # 'nuEmenda' ou 'noAutor' do parlamentar autor da emenda.
        _parl = (
            raw.get("parlamentar") or raw.get("responsaveis")
            or raw.get("indicacao") or raw.get("nome_responsavel")
            or raw.get("autor_emenda") or raw.get("noAutor")
            or raw.get("noParlamentar") or ""
        )
        if isinstance(_parl, list):
            _parl = ", ".join(str(x) for x in _parl if x)
        elif not isinstance(_parl, str):
            _parl = str(_parl) if _parl else ""
        _parl = _parl.replace("�", "").replace("  ", " ").strip()
        add_item(parte, secao, orgao, {
            "tipo": tipo_label,
            "numero": identificador,
            "objeto": c.objeto or "",
            "parlamentar": _parl,
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
            "fonte": fonte_label,
            "fonte_ref": str(c.id),
        })

    # === TransfereGov Voluntarias (SICONV) ===
    vol = await db.execute(text("""
        SELECT id, numero_proposta, codigo_instrumento, situacao, orgao, objeto,
               dt_fim_vigencia, valor_global, valor_repasse, valor_contrapartida,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar, situacao_contratacao_detalhe,
               detalhe->>'Empenhado'
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
        # TransfereGov/SICONV => federal => PARTE 1 (ou PARTE 3 se prestacao)
        parte = _classifica_parte("federal", sit, dt_fim)
        orgao = (row[4] or "Outros - Federal").strip()
        # Campos SEPARADOS (sem duplicar): situacao do ciclo, contratacao,
        # detalhe da clausula (motivo/data) e empenho — cada um no seu campo.
        situacao_contr = row[10]
        clausula_dt = row[11]
        clausula_motivo = row[12]
        empenhado_raw = (row[15] or "").strip().lower()
        empenhado = {"sim": "Sim", "não": "Não", "nao": "Não"}.get(empenhado_raw, "")
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
            "situacao_atual": sit,  # status do ciclo (ex.: "Em execução") — sem narrativa
            "empenhado": empenhado,
            "situacao_contratacao": situacao_contr or "",
            "clausula_motivo": clausula_motivo or "",
            "clausula_dt": _iso(clausula_dt) if clausula_dt else "",
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
        # Emendas SIGCON => estadual => PARTE 2
        parte = _classifica_parte("estadual", sit, None)
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
    # Ordem das secoes dentro de cada Parte: FEDERAIS primeiro, ESTADUAIS depois,
    # outras secoes (se houver) preservam ordem de insercao no fim.
    SECAO_PRIORIDADE = [
        "INSTRUMENTOS DE REPASSE FEDERAIS",
        "INSTRUMENTOS DE REPASSE ESTADUAIS",
    ]

    def _ordena_secoes(secoes_dict):
        nomes = list(secoes_dict.keys())
        ordenados = [s for s in SECAO_PRIORIDADE if s in secoes_dict]
        # outras secoes nao previstas — vao depois, preservando ordem original
        ordenados += [s for s in nomes if s not in SECAO_PRIORIDADE]
        return [(n, secoes_dict[n]) for n in ordenados]

    out_partes = []
    for n in sorted(partes_data.keys()):
        p = partes_data[n]
        secoes_out = []
        for s_idx, (s_titulo, grupos) in enumerate(_ordena_secoes(p["secoes"]), start=1):
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
