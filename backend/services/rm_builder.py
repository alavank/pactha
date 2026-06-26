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
import logging
from datetime import date
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from models import ConvenioEstadual, Municipio

logger = logging.getLogger("rm_builder")

_VOL_LIKE = "%enviado para an%lise%"
_REJ_LIKE = "%rejeitad%"

# Secoes federais (mesmo rotulo em qualquer Parte)
_SEC_FED = "INSTRUMENTOS DE REPASSE FEDERAIS"
_SEC_FED_REJ = "INSTRUMENTOS FEDERAIS REJEITADOS / INDEFERIDOS"
_SEC_EST = "INSTRUMENTOS DE REPASSE ESTADUAIS"


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


def _fed_status(situacao: str | None) -> str:
    """Status FEDERAL CONFIÁVEL (pelo estado do sistema, ignorando o flag
    detalhe->>'Empenhado' que é furado — havia propostas só "Aprovadas" marcadas
    como empenhadas sem empenho real):
      - 'dead'      -> rejeitada/indeferida/anulada/rescindida/legado (seção Rejeitados)
      - 'paga'      -> prestação de contas / paga / concluída -> PARTE 3
      - 'empenhada' -> empenhada, falta pagamento (Em execução / FNS Empenhado) -> PARTE 1
      - 'ativa'     -> pré-empenho (análise/aprovada/complementação/ciente/pendente)
    """
    s = (situacao or "").strip().lower()
    if any(x in s for x in ("rejeitad", "indeferid", "anulad", "rescind", "legado")):
        return "dead"
    if ("presta" in s and "conta" in s) or "conclu" in s or s == "pago" or "pagamento" in s or "finaliz" in s:
        return "paga"
    if "execu" in s or "empenhad" in s:
        return "empenhada"
    return "ativa"


def _fed_empenhada(situacao: str | None) -> bool:
    """True quando o instrumento foi, no mínimo, empenhado (inclui pago/prestação)."""
    return _fed_status(situacao) in ("empenhada", "paga")


def _fed_retem(ano_prop: int | None, ano_emissao: int, situacao: str | None) -> bool:
    """Regra de permanência no RM, por ANO DE EMISSÃO:
      - empenhada/paga -> sempre permanece (qualquer ano)
      - dead           -> permanece (vai p/ seção Rejeitados à parte)
      - ativa (pré-empenho) -> só permanece se for do ano de emissão (ou posterior)
    """
    st = _fed_status(situacao)
    if st in ("empenhada", "paga", "dead"):
        return True
    return ano_prop is not None and ano_prop >= ano_emissao


def _federal_destino(situacao: str | None) -> tuple[int, str]:
    """(parte, secao) para um instrumento federal a partir do status."""
    st = _fed_status(situacao)
    if st == "dead":
        return (1, _SEC_FED_REJ)
    if st == "paga":
        return (3, _SEC_FED)
    return (1, _SEC_FED)


def _ano_de(*vals) -> int | None:
    """Extrai um ano (YYYY) de 'NNNNNN/2025', '202541760003-...', int, etc."""
    import re as _re
    for v in vals:
        if v is None:
            continue
        if isinstance(v, int):
            if 2000 <= v <= 2100:
                return v
            continue
        m = _re.search(r"(20\d{2})", str(v))
        if m:
            return int(m.group(1))
    return None


async def montar_conteudo(db: AsyncSession, municipio_id: int, ano_emissao: int | None = None) -> dict:
    """Monta o conteudo JSONB de um RM a partir dos dados do banco.

    ano_emissao: ano-base da janela do relatório (year da data de referência).
    Mantém só propostas federais do ano de emissão (em análise/aprovação) + todas
    as empenhadas (qualquer ano). Default = ano atual."""
    if not ano_emissao:
        ano_emissao = date.today().year
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

    mun = (await db.execute(
        select(Municipio).where(Municipio.id == municipio_id)
    )).scalar_one_or_none()

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
        identificador = (nr_proposta or nr_instr or c.nr_sigcon or "") if is_fns else (nr_instr or nr_proposta or c.nr_sigcon or "")
        dt_fim = c.dt_vigencia_atual or c.dt_vigencia_final

        if is_fns:
            # FNS = PROPOSTAS do Min. Saude. O scraper guarda em raw_data o
            # tipo/recurso e a lista de propostas INDIVIDUAIS (Nº SIPA) em
            # linhaPropostas. Expandimos 1 item por proposta individual com o
            # NUMERO REAL (SIPA) + ano — em vez do agregado/chave sintetica.
            tipo = (raw.get("coTipoProposta") or c.tipo_programa or "").strip()
            recurso = (raw.get("dsTipoRecurso") or "").strip()
            objeto_fns = tipo.title() if tipo else (c.objeto or "").strip()
            recurso_label = recurso.title() if recurso else ""
            orgao = (c.orgao_concedente or "Ministério da Saúde — FNS").strip()
            individuais = raw.get("linhaPropostas") if isinstance(raw.get("linhaPropostas"), list) else []
            if individuais:
                for ind in individuais:
                    nuprop = str(ind.get("nuProposta") or "").strip()
                    if not nuprop:
                        continue
                    vlprop = _money(ind.get("vlProposta"))
                    vlpago = _money(ind.get("vlPago"))
                    vlpagar = _money(ind.get("vlPagar")) or 0
                    # Empenho CONFIRMADO exige REPASSE EFETIVO (vlPago>0). vlPagar>0
                    # com vlPago=0 é só o valor proposto "a pagar" — NÃO é empenho real
                    # (havia propostas 2014/2017 marcadas "Empenhado" com repasse R$0).
                    # Sem vlPago, cai em "Em análise" (pré-empenho) e segue a regra do ano.
                    sit = ("Pago" if (vlpago or 0) > 0 and vlpagar == 0
                           else "Empenhado" if (vlpago or 0) > 0
                           else "Em análise" if (vlprop or 0) > 0 else "Pendente")
                    parls = ind.get("parlamentares") or []
                    nomes = [(_p.get("noApelidoPolitico") or _p.get("noParlamentar") or _p.get("nome"))
                             for _p in parls if isinstance(_p, dict)]
                    nomes = [n for n in nomes if n]
                    resp = ", ".join(nomes) if nomes else recurso_label
                    # Regra do ano de emissão: empenhada/paga sempre; "em análise"
                    # só do ano de emissão. Empenho validado pelo valor (vlPagar/
                    # vlPago), não por flag.
                    if not _fed_retem(c.ano, ano_emissao, sit):
                        continue
                    parte, secao = _federal_destino(sit)
                    add_item(parte, secao, orgao, {
                        "tipo": "Proposta",
                        "numero": f"{nuprop} - {c.ano}" if c.ano else nuprop,
                        "objeto": objeto_fns,
                        "parlamentar": resp,
                        "valor_global": vlprop or vlpago,
                        "valor_repasse": vlpago,
                        "valor_contrapartida": 0,
                        "banco": "", "agencia": "", "conta": "",
                        "saldo_bancario": None, "dt_saldo": None,
                        "dt_fim_vigencia": None,
                        "situacao_atual": sit,
                        "empenhado": "Sim" if _fed_empenhada(sit) else "Não",
                        "fonte": "fns",
                        "fonte_ref": str(c.id),
                    })
            elif _fed_retem(c.ano, ano_emissao, c.situacao):
                # Fallback: bucket sem individuais (dados ainda nao re-coletados).
                parte, secao = _federal_destino(c.situacao)
                add_item(parte, secao, orgao, {
                    "tipo": "Proposta",
                    "numero": f"{objeto_fns} - {c.ano}" if c.ano else (objeto_fns or "Proposta FNS"),
                    "objeto": objeto_fns,
                    "parlamentar": recurso_label,
                    "valor_global": _money(c.valor_total),
                    "valor_repasse": _money(c.valor_concedente),
                    "valor_contrapartida": 0,
                    "banco": "", "agencia": "", "conta": "",
                    "saldo_bancario": None, "dt_saldo": None,
                    "dt_fim_vigencia": _iso(dt_fim),
                    "situacao_atual": (c.situacao or "").strip(),
                    "empenhado": "Sim" if _fed_empenhada(c.situacao) else "Não",
                    "fonte": "fns",
                    "fonte_ref": str(c.id),
                })
            continue

        # === SIGCON-MG (estadual) -> PARTE 2 ===
        secao = _SEC_EST
        orgao = (c.orgao_concedente or "Outros - SIGCON").strip() + " - SIGCON"
        parte = _classifica_parte("estadual", c.situacao, dt_fim)
        tipo_label = "Convênio" if nr_instr else "Proposta"
        # SIGCON-MG armazena o parlamentar como 'responsaveis' no raw_data.
        _parl = (
            raw.get("parlamentar") or raw.get("responsaveis")
            or raw.get("indicacao") or raw.get("nome_responsavel") or ""
        )
        if isinstance(_parl, list):
            _parl = ", ".join(str(x) for x in _parl if x)
        elif not isinstance(_parl, str):
            _parl = str(_parl) if _parl else ""
        _parl = _parl.replace("�", "").replace("  ", " ").strip()
        add_item(parte, secao, orgao, {
            "tipo": tipo_label,
            "numero": nr_instr or nr_proposta or c.nr_sigcon or "",
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
            "fonte": "sigcon",
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
        # Regra do ANO DE EMISSÃO: empenhada/paga (Em execução / Prestação) fica
        # sempre; "em análise/aprovada" só do ano de emissão; antigas não-avançadas
        # saem. Empenho validado pelo STATUS (não pelo flag detalhe->>'Empenhado',
        # que estava marcando "Aprovadas" como empenhadas sem empenho real).
        ano_prop = _ano_de(row[1], row[2])  # numero_proposta NNNNNN/AAAA / codigo
        if not _fed_retem(ano_prop, ano_emissao, sit):
            continue
        dt_fim = None
        try:
            from datetime import datetime as _dt
            dt_fim = _dt.strptime(str(row[6])[:10], "%d/%m/%Y").date() if row[6] else None
        except (ValueError, TypeError):
            pass
        tipo_label = "Convênio" if row[2] else "Proposta"
        parte, secao = _federal_destino(sit)
        orgao = (row[4] or "Outros - Federal").strip()
        # Campos SEPARADOS (sem duplicar): situacao do ciclo, contratacao,
        # detalhe da clausula (motivo/data) e empenho — cada um no seu campo.
        situacao_contr = row[10]
        clausula_dt = row[11]
        clausula_motivo = row[12]
        empenhado = "Sim" if _fed_empenhada(sit) else "Não"  # validado pelo status
        add_item(parte, secao, orgao, {
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

    # === Transferencia Especial / Plano de Acao (Emenda Pix) — federal, API ao vivo ===
    # NAO fica em tabela: vem da listagem publica (cache 1h). Best-effort: se a API
    # estiver fora, o RM e gerado sem TE (nao quebra).
    if mun is not None:
        try:
            from routers.transferegov import _fetch_listagem, _norm as _norm_tg
            planos = await _fetch_listagem(mun.uf)
            mn = _norm_tg(mun.nome)
            for it in planos:
                ben = _norm_tg(it.get("beneficiarioNome") or "")
                if not (mn in ben or ben.endswith(mn)):
                    continue
                sit = it.get("planoAcaoSituacao") or ""
                sl = sit.lower()
                cod_em = it.get("codigoEmendaFormatado") or ""
                # Mesma regra do ano de emissão: TE concluída fica (PARTE 3);
                # TE ativa (CIENTE/análise) só do ano de emissão; antiga não-
                # concluída sai. Ano vem do código da emenda (AAAA...) ou do plano.
                ano_te = _ano_de(cod_em, it.get("planoAcaoCodigo"))
                if not _fed_retem(ano_te, ano_emissao, sit):
                    continue
                # CONCLUIDA/paga -> PARTE 3; demais (CIENTE/EM_ANALISE/...) -> PARTE 1.
                parte_te = 3 if ("conclu" in sl or "pag" in sl or "finaliz" in sl) else 1
                parl = cod_em.split("-", 1)[1].strip() if "-" in cod_em else ""
                valor = _money(it.get("valorTotal"))
                add_item(parte_te, _SEC_FED, "Transferência Especial (Emenda Pix)", {
                    "tipo": "Transferência Especial",
                    "numero": it.get("planoAcaoCodigo") or "",
                    "objeto": it.get("objetoDescricao") or it.get("politicasPublicas") or "",
                    "parlamentar": parl,
                    "valor_global": valor,
                    "valor_repasse": valor,
                    "valor_contrapartida": 0,
                    "banco": "", "agencia": "", "conta": "",
                    "saldo_bancario": None, "dt_saldo": None,
                    "dt_fim_vigencia": None,
                    "situacao_atual": sit,
                    "fonte": "transferencia_especial",
                    "fonte_ref": str(it.get("planoAcaoId") or ""),
                })
        except Exception as ex:
            logger.warning(f"RM: TE/plano-acao indisponivel p/ {municipio_id}: {str(ex)[:120]}")

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
        _SEC_FED,
        _SEC_EST,
        _SEC_FED_REJ,
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
