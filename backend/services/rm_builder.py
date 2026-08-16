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
from services.nome_parlamentar import e_parlamentar_real

logger = logging.getLogger("rm_builder")

_VOL_LIKE = "%enviado para an%lise%"
_REJ_LIKE = "%rejeitad%"

# Secoes federais (mesmo rotulo em qualquer Parte)
_SEC_FED = "INSTRUMENTOS DE REPASSE FEDERAIS"
_SEC_FED_REJ = "INSTRUMENTOS FEDERAIS REJEITADOS / INDEFERIDOS"
_SEC_EST = "INSTRUMENTOS DE REPASSE ESTADUAIS"

# ---------------------------------------------------------------------------
# RM COMPLETO (todos os anos) — padrao "Freitas completo" (ver referencia)
# ---------------------------------------------------------------------------
# O RM COMPLETO e um documento estruturalmente DIFERENTE do anual: 4 Partes
# classificadas por ESTAGIO/SITUACAO do instrumento (e ano do pagamento), NAO
# por esfera. Todo o comportamento novo fica atras de `completo=True` em
# montar_conteudo — o RM anual (completo=False) nao muda em nada.
#
#   PARTE 1 — pendencia FEDERAL/Brasilia (empenho, desembolso, aceite)
#   PARTE 2 — acao do MUNICIPIO (licitacao/projeto/clausula) + PAGOS no ano corrente
#   PARTE 3 — pagamentos de ANOS ANTERIORES / prestacao de contas
#   PARTE 4 — Propostas Voluntarias (SO cadastros do ano corrente, validade 1 ano)
#
# Os rotulos de secao mudam por Parte (a referencia usa plural no topo e singular
# na Parte 3; o estadual muda de nome entre a Parte 2 e a Parte 3).
_SEC_FED_PLURAL = "INSTRUMENTOS DE REPASSE FEDERAIS"          # Partes 1, 2, 4
_SEC_FED_SINGULAR = "INSTRUMENTOS DE REPASSE FEDERAL"        # Parte 3
_SEC_EST_P2 = "INFORMAÇÕES DE REPASSE ESTADUAIS"             # Parte 2
_SEC_EST_P3_RES = "Resoluções e Transferências Especiais Estaduais"  # Parte 3
_SEC_EST_P3_CONV = "Convênios Estaduais"                     # Parte 3


def _titulos_partes_completo(ano_ref: int) -> dict:
    """Titulos EXATOS das 4 Partes do RM completo (padrao da referencia).

    O ano corrente entra no texto da Parte 4 (validade 1 ano) — por isso e
    parametrizado pelo ano de emissao, nao fixo em 2026."""
    return {
        1: "Parte 1 - demandas em Brasília (Pendências de empenho, desembolso e aceite)",
        2: "Parte 2 - Demandas do Município",
        3: "Parte 3 – Prestações de contas em análise/aprovadas - pagamentos realizados de anos anteriores",
        4: (f"Parte 4 – Propostas Voluntárias - OBS: As propostas voluntárias referem-se "
            f"apenas a cadastros realizados no ano de {ano_ref} tendo validade de 1 ano "
            f"podendo serem empenhadas e pagas até 31 de dezembro mas não possuem garantia."),
    }


# Palavras que denunciam que a pendencia esta com o MUNICIPIO (nao em Brasilia):
# licitacao a fazer, projeto/termo de referencia em analise, clausula suspensiva,
# medicao a inserir. Quando presentes, o instrumento (mesmo federal) vai p/ Parte 2.
_PEND_MUNICIPAL_KW = (
    "licita", "projeto de engenharia", "projeto basico", "projeto básico",
    "termo de refer", "cláusula suspensiva", "clausula suspensiva",
    "aguardando inser", "inserir medi", "medição", "medicao",
    "aguardando o munic", "pendência do munic", "pendencia do munic",
    "contrapartida",
)


def _pend_municipal(*textos: str | None) -> bool:
    s = " ".join((t or "").lower() for t in textos)
    return any(k in s for k in _PEND_MUNICIPAL_KW)


def _destino_completo(esfera: str, fonte: str, status: str, ano_item: int | None,
                      ano_pgto: int | None, ano_ref: int, pend_municipal: bool,
                      pre_empenho_novo: bool, tem_convenio: bool) -> tuple[int, str, str]:
    """(parte, secao, sufixo_orgao) do RM COMPLETO, por ESTAGIO/SITUACAO.

    - status: rotulo de _fed_status (paga/empenhada/vigente/ativa; 'dead' ja foi
      cortado na retencao).
    - ano_pgto: ano do PAGAMENTO quando conhecido (SIMEC dt_pgto, FNS ultimo
      pagamento, TE concluida, c.ano no estadual). None quando a fonte nao diz.
    - pre_empenho_novo: proposta voluntaria/FNS cadastrada no ano corrente e ainda
      pre-empenho -> Parte 4.
    - tem_convenio: estadual com numero de convenio (nr_instrumento) -> "Convenios
      Estaduais"; senao (indicacao/resolucao/TE) -> "Resolucoes e T.E.".

    O sufixo_orgao ("- Pagos {ano}") so e usado nos federais PAGOS no ano corrente
    (bloco "REPASSES DE {ano}:" da Parte 2), como na referencia."""
    fed = (esfera == "federal")
    # Janela de "pago recente": federal so o ANO CORRENTE (bloco "REPASSES DE
    # {ano}"); estadual 2 anos (a referencia poe estaduais pagos 2025-2026 na Parte 2).
    pago_corrente = (ano_pgto == ano_ref) if fed else (ano_pgto is not None and ano_pgto >= ano_ref - 1)

    if pre_empenho_novo:
        return 4, _SEC_FED_PLURAL, ""

    if status == "paga":
        if pago_corrente:
            if fed:
                return 2, f"REPASSES DE {ano_ref}:", f" - Pagos {ano_ref}"
            return 2, _SEC_EST_P2, ""
        # anos anteriores -> Parte 3
        if fed:
            return 3, _SEC_FED_SINGULAR, ""
        return 3, (_SEC_EST_P3_CONV if tem_convenio else _SEC_EST_P3_RES), ""

    # Nao pago (empenhada / ativa / vigente)
    if fed:
        # Empenhado ou aprovado: se a bola esta com o municipio -> Parte 2; senao
        # a pendencia e federal (aguarda empenho/desembolso/aceite) -> Parte 1.
        return (2, _SEC_FED_PLURAL, "") if pend_municipal else (1, _SEC_FED_PLURAL, "")
    # Estadual em ciclo corrente (nao pago) aparece na Parte 2.
    return 2, _SEC_EST_P2, ""


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
    if any(x in s for x in ("rejeitad", "indeferid", "anulad", "rescind", "cancelad", "legado")):
        return "dead"
    if ("presta" in s and "conta" in s) or "conclu" in s or "encerr" in s or s == "pago" or "pagamento" in s or "finaliz" in s:
        return "paga"
    if "execu" in s or "empenhad" in s:
        return "empenhada"
    # Instrumento ATIVO (assinado / em vigor) — avançou -> permanece em qualquer
    # ano (convênio em curso), mesmo sem empenho ainda.
    if "vigor" in s or "assinad" in s:
        return "vigente"
    return "ativa"


def _fed_empenhada(situacao: str | None) -> bool:
    """True quando o instrumento foi, no mínimo, empenhado (inclui pago/prestação)."""
    return _fed_status(situacao) in ("empenhada", "paga")


def _fed_retem(ano_prop: int | None, ano_emissao: int, situacao: str | None,
               completo: bool = False) -> bool:
    """Regra de permanência no RM, por ANO DE REFERÊNCIA (ano_emissao):
      - empenhada/paga -> sempre permanece (avançou; convênio em curso em qualquer ano)
      - dead (rejeitada/indeferida/anulada) -> só permanece no SEU próprio ano de
        referência; NÃO carrega p/ os relatórios dos demais anos (as que não foram
        para frente naquele ano não entram nos outros)
      - ativa (pré-empenho) -> só permanece se for do ano de referência (ou posterior)

    completo=True (RM de TODOS os anos): a MESMA regra do anual, com uma diferença
    — 'dead' (rejeitada/anulada/indeferida) NUNCA entra (a referência não tem seção
    de rejeitados). Note que empenhada/paga/vigente já permanecem em qualquer ano no
    anual; o pré-empenho ('ativa') continua só do ano de referência ou posterior
    (a referência trata Parte 1/2 como ciclo corrente, não histórico).
    """
    st = _fed_status(situacao)
    if st in ("empenhada", "paga", "vigente"):
        return True
    if st == "dead":
        # anual: só no próprio ano; completo: nunca.
        return False if completo else (ano_prop is not None and ano_prop == ano_emissao)
    # ativa (pré-empenho): só do ano de referência ou posterior (anual e completo).
    return ano_prop is not None and ano_prop >= ano_emissao


def _fns_classifica(situacao_desc: str | None, sit_calc: str) -> str:
    """Rotulo de CLASSIFICACAO da proposta FNS, no vocabulario que _fed_status
    entende. Prefere a situacao REAL do portal (situacao_desc) e cai no rotulo
    derivado do dinheiro (Pago/Empenhado/Em analise) quando ela nao veio.

    DIVISAO DE TRABALHO: o TEXTO decide o que o dinheiro nao consegue dizer
    (rejeitada / bloqueada / cancelada — uma proposta morta tem os mesmos
    valores de uma em analise). Ja PAGO x PARCIAL quem decide e o DINHEIRO:
    o portal escreve 'Proposta Paga - 1ª parcela' em proposta que ainda tem
    parcela a receber, e 'Proposta em Analise de Pagamento' em proposta que
    NAO foi paga — casar por 'pag' no texto mandava as duas para a PARTE 3
    (prestacao de contas) indevidamente."""
    d = (situacao_desc or "").strip().lower()
    if not d:
        return sit_calc
    if any(x in d for x in ("rejeit", "bloquead", "cancelad", "indeferid", "arquivad", "anulad")):
        return "Rejeitada"
    if "empenhad" in d:
        return "Empenhado"
    return sit_calc


def _fns_retem(ano_prop: int | None, ano_emissao: int, ind: dict,
               vl_pago: float, vl_pagar: float, sit_cls: str,
               completo: bool = False) -> bool:
    """Regra de ano PROPRIA do FNS (nao usa _fed_retem, que e compartilhada com
    TransfereGov/SIGCON e mantem 'paga' para sempre).

    O FNS acumula proposta desde 2010 e quase toda antiga fica marcada como
    'Paga' — pela regra federal elas entravam em TODOS os relatorios seguintes,
    poluindo o RM do ano de referencia com centenas de itens mortos.

    Permanece no relatorio do ano de referencia quem:
      - e do proprio ano (ou posterior);
      - teve PAGAMENTO no ano de referencia (ainda que a proposta seja antiga);
      - foi empenhada e ainda tem SALDO A RECEBER (pago > 0 e a pagar > 0).
    Rejeitada/bloqueada so aparece no seu proprio ano.

    completo=True (todos os anos): pago/empenhado de QUALQUER ano permanece (é o
    histórico que alimenta a Parte 3); pré-empenho ('Em análise'/'Pendente') só do
    ano de referência ou posterior; Rejeitada/dead nunca entra."""
    if sit_cls == "Rejeitada" or _fed_status(sit_cls) == "dead":
        return False if completo else (ano_prop is not None and ano_prop == ano_emissao)
    if completo:
        if _fed_status(sit_cls) in ("paga", "empenhada", "vigente"):
            return True
        return ano_prop is not None and ano_prop >= ano_emissao
    if ano_prop is not None and ano_prop >= ano_emissao:
        return True
    try:
        if int(ind.get("ano_ultimo_pagamento") or 0) == ano_emissao:
            return True
    except (TypeError, ValueError):
        pass
    return vl_pago > 0 and vl_pagar > 0


def _federal_destino(situacao: str | None) -> tuple[int, str]:
    """(parte, secao) para um instrumento federal a partir do status."""
    st = _fed_status(situacao)
    if st == "dead":
        return (1, _SEC_FED_REJ)
    if st == "paga":
        return (3, _SEC_FED)
    return (1, _SEC_FED)


def _ano_de(*vals) -> int | None:
    """Extrai o ANO (YYYY) de 'NNNNNN/2025', '202541760003-...', int, etc.

    PEGADINHA: a regex ingênua (20\\d{2}) pegava '2097' de '042097/2015' (o
    miolo do número, antes do ano real após a barra) -> ano futuro absurdo que
    driblava o filtro do RM. Agora: 1) prioriza o ano APÓS a barra (formato
    proposta 'NNNNNN/AAAA'); 2) senão, o 1º AAAA PLAUSÍVEL (<= ano atual+2),
    descartando anos impossíveis vindos do meio do número."""
    import re as _re
    from datetime import date as _date
    lim = _date.today().year + 2
    for v in vals:
        if v is None:
            continue
        if isinstance(v, int):
            if 2000 <= v <= 2100:
                return v
            continue
        s = str(v)
        m = _re.search(r"/\s*((?:19|20)\d{2})\b", s)  # ano após a barra tem prioridade
        if m:
            return int(m.group(1))
        for mm in _re.finditer(r"(?:19|20)\d{2}", s):  # senão, 1º ano plausível
            y = int(mm.group(0))
            if 2000 <= y <= lim:
                return y
    return None


def _evento_atual(historico) -> dict:
    """EVENTO ATUAL do Histórico de Comunicações (TransfereGov mandatárias):
    onde o instrumento está de fato na análise, com SITUAÇÃO e CONSIDERAÇÕES.
    As chaves vêm do próprio portal (Data/Hora, Evento, Responsável,
    Considerações, Situação) — por isso casamos por regex, não por chave fixa.
    O portal lista do mais novo p/ o mais antigo; ainda assim escolhemos pelo
    maior Data/Hora quando parseável."""
    if not isinstance(historico, list) or not historico:
        return {}
    import re as _re
    from datetime import datetime as _dtp

    def _pick(d, pat):
        if not isinstance(d, dict):
            return ""
        for k, v in d.items():
            if _re.search(pat, str(k), _re.I):
                return v.strip() if isinstance(v, str) else (v or "")
        return ""

    def _ts(d):
        s = str(_pick(d, r"data|hora")).strip()
        for f in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                return _dtp.strptime(s, f)
            except (ValueError, TypeError):
                continue
        return None

    validos = [h for h in historico if isinstance(h, dict)]
    if not validos:
        return {}
    datados = [(h, _ts(h)) for h in validos]
    datados = [(h, t) for h, t in datados if t]
    atual = max(datados, key=lambda x: x[1])[0] if datados else validos[0]
    return {
        "evento_data": _pick(atual, r"data|hora"),
        "evento_atual": _pick(atual, r"evento"),
        "evento_situacao": _pick(atual, r"situa"),
        "evento_consideracoes": _pick(atual, r"considera"),
        "evento_responsavel": _pick(atual, r"respons"),
        "historico_qtd": len(validos),
    }


async def montar_conteudo(db: AsyncSession, municipio_id: int, ano_emissao: int | None = None,
                          completo: bool = False) -> dict:
    """Monta o conteudo JSONB de um RM a partir dos dados do banco.

    ano_emissao: ano-base da janela do relatório (year da data de referência).
    Mantém só propostas federais do ano de emissão (em análise/aprovação) + todas
    as empenhadas (qualquer ano). Default = ano atual.

    completo=False (DEFAULT — RM ANUAL): comportamento historico, intacto. 3 Partes
    classificadas por esfera, recorte por ano_emissao.

    completo=True (RM COMPLETO — TODOS OS ANOS, padrao "Freitas completo"): 4 Partes
    classificadas por ESTAGIO/SITUACAO (ver _destino_completo), sem recorte de ano,
    com os sub-blocos e rotulos da referencia. Ativado pelo endpoint quando
    escopo='completo'. Nenhum caminho do anual e tocado quando completo=False."""
    if not ano_emissao:
        ano_emissao = date.today().year
    # Estrutura: {partes: [{ordem, titulo, secoes: [{ordem, titulo, grupos:
    #   [{ordem, orgao, itens: [...]}]}]}]}
    # Build incrementally then convert.
    if completo:
        _tit = _titulos_partes_completo(ano_emissao)
        partes_data = {n: {"titulo": _tit[n], "secoes": {}} for n in (1, 2, 3, 4)}
    else:
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
                    # Regra de ano PROPRIA do FNS: do ano de referência, ou que
                    # se moveu nele (pagamento no ano / saldo a receber). Sem
                    # isso o RM de 2026 vinha com proposta "Paga" de 2010.
                    sit_cls = _fns_classifica(ind.get("situacao_desc"), sit)
                    if not _fns_retem(c.ano, ano_emissao, ind, vlpago or 0, vlpagar or 0, sit_cls, completo):
                        continue
                    orgao_fns = orgao
                    if completo:
                        st = _fed_status(sit_cls)
                        try:
                            ano_pg = int(ind.get("ano_ultimo_pagamento") or 0) or None
                        except (TypeError, ValueError):
                            ano_pg = None
                        pre_novo = st == "ativa" and c.ano == ano_emissao
                        parte, secao, suf = _destino_completo(
                            "federal", "fns", st, c.ano, ano_pg, ano_emissao,
                            _pend_municipal(ind.get("situacao_desc"), sit), pre_novo, False)
                        orgao_fns = orgao + suf
                    else:
                        parte, secao = _federal_destino(sit_cls)
                    add_item(parte, secao, orgao_fns, {
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
                        # Situacao REAL do portal FNS (ex.: "EM ANALISE PELA AREA
                        # FINALISTICA"), capturada por proposta no scraper. Fallback
                        # p/ o rotulo computado (Pago/Empenhado/Em analise) quando
                        # ainda nao re-coletado.
                        "situacao_atual": (ind.get("situacao_desc") or sit),
                        "empenhado": "Sim" if _fed_empenhada(sit_cls) else "Não",
                        "fonte": "fns",
                        "fonte_ref": str(c.id),
                    })
            elif (c.ano is not None and c.ano >= ano_emissao) or (completo and _fed_status(c.situacao) != "dead"):
                # Fallback: bucket sem individuais (coleta antiga/incompleta). Sem
                # as propostas individuais nao da pra saber se houve pagamento no
                # ano — entao no anual so entra se for do proprio ano de referência.
                # No completo entra qualquer ano (menos dead).
                orgao_fb = orgao
                if completo:
                    st = _fed_status(c.situacao)
                    pre_novo = st == "ativa" and c.ano == ano_emissao
                    parte, secao, suf = _destino_completo(
                        "federal", "fns", st, c.ano, None, ano_emissao,
                        _pend_municipal(c.situacao), pre_novo, False)
                    orgao_fb = orgao + suf
                else:
                    parte, secao = _federal_destino(c.situacao)
                add_item(parte, secao, orgao_fb, {
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
        # Mesma regra de ANO do federal: as que NAO foram para frente
        # (cadastramento / analise celebracao / cancelada) de anos anteriores NAO
        # entram no relatorio do ano de referencia; avancadas (em execucao / em
        # vigor / empenhada) e concluidas (encerrada / prestacao) permanecem.
        ano_est = c.ano or _ano_de(nr_instr, nr_proposta, c.nr_sigcon)
        if not _fed_retem(ano_est, ano_emissao, c.situacao, completo):
            continue
        orgao = (c.orgao_concedente or "Outros - SIGCON").strip() + " - SIGCON"
        tipo_label = "Convênio" if nr_instr else "Proposta"
        if completo:
            st = _fed_status(c.situacao)
            parte, secao, _suf = _destino_completo(
                "estadual", "sigcon", st, ano_est, ano_est, ano_emissao,
                _pend_municipal(c.situacao), False, bool(nr_instr))
        else:
            secao = _SEC_EST
            parte = _classifica_parte("estadual", c.situacao, dt_fim)
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
        # "Não há" nao e parlamentar — e o texto que o SIGCON escreve quando nao
        # ha responsavel. Sem isto o relatorio mensal atribui convenio a um
        # parlamentar inexistente, e o RM CONGELA o resultado em
        # rm_relatorios.conteudo: documento entregue com nome errado nao se
        # corrige depois. Regra unica em services/nome_parlamentar.py.
        if not e_parlamentar_real(_parl):
            _parl = ""
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
               detalhe->>'Empenhado', processo_execucao_qtd, historico_comunicacoes,
               detalhe->>'Banco', detalhe->>'Agência', detalhe->>'Conta'
        FROM transferegov_propostas WHERE municipio_id = :m
    """), {"m": municipio_id})
    for row in vol.fetchall():
        sit = row[3] or ""
        # Regra do ANO DE EMISSÃO: empenhada/paga (Em execução / Prestação) fica
        # sempre; "em análise/aprovada" só do ano de emissão; antigas não-avançadas
        # saem. Empenho validado pelo STATUS (não pelo flag detalhe->>'Empenhado',
        # que estava marcando "Aprovadas" como empenhadas sem empenho real).
        ano_prop = _ano_de(row[1], row[2])  # numero_proposta NNNNNN/AAAA / codigo
        if not _fed_retem(ano_prop, ano_emissao, sit, completo):
            continue
        dt_fim = None
        try:
            from datetime import datetime as _dt
            dt_fim = _dt.strptime(str(row[6])[:10], "%d/%m/%Y").date() if row[6] else None
        except (ValueError, TypeError):
            pass
        tipo_label = "Convênio" if row[2] else "Proposta"
        orgao = (row[4] or "Outros - Federal").strip()
        if completo:
            st = _fed_status(sit)
            # Voluntaria pre-empenho cadastrada no ano corrente -> Parte 4.
            pre_novo = st == "ativa" and ano_prop == ano_emissao
            # Pendencia municipal: situacao do ciclo + contratacao + motivo da clausula.
            pend = _pend_municipal(sit, row[10], row[12])
            parte, secao, suf = _destino_completo(
                "federal", "voluntaria", st, ano_prop, None, ano_emissao,
                pend, pre_novo, bool(row[2]))
            orgao = orgao + suf
        else:
            parte, secao = _federal_destino(sit)
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
            # Banco/agencia/conta ja estao no JSONB `detalhe` (raspados junto do
            # resto da pagina Dados da Proposta). Antes ficavam "" p/ TransfereGov —
            # a tela do RM tem os campos, mas nunca eram preenchidos deste lado.
            "banco": row[18] or "", "agencia": row[19] or "", "conta": row[20] or "",
            "saldo_bancario": None, "dt_saldo": None,
            "dt_fim_vigencia": _iso(dt_fim),
            "situacao_atual": sit,  # status do ciclo (ex.: "Em execução") — sem narrativa
            "empenhado": empenhado,
            "situacao_contratacao": situacao_contr or "",
            "clausula_motivo": clausula_motivo or "",
            "clausula_dt": _iso(clausula_dt) if clausula_dt else "",
            # Processo de Execução (Licitações): só relevante p/ contratação Normal.
            # 0 = Normal SEM processo/licitação registrado (flag); N>0 = tem; None = n/c.
            "processo_execucao_qtd": row[16],
            # EVENTO ATUAL do Histórico de Comunicações (mandatárias): onde o
            # instrumento está de fato na análise, + situação e considerações.
            **_evento_atual(row[17]),
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
                # Situacao exibida: Plano de Acao (CIENTE/...) + Plano de Trabalho
                # (a fase real: EM_ANALISE, APROVADO, CONCLUIDO..., EMPENHADO...).
                # So "ciente" (plano de acao) e pouco informativo p/ o relatorio.
                _hz = lambda s: (s or "").replace("_", " ").strip()
                sit_pt = _hz(it.get("planoTrabalhoSituacao"))
                sit_te = _hz(sit)
                if sit_pt and _hz(sit).lower() != sit_pt.lower():
                    sit_te = f"{_hz(sit)} · Plano de Trabalho: {sit_pt}"
                cod_em = it.get("codigoEmendaFormatado") or ""
                # Mesma regra do ano de emissão: TE concluída fica (PARTE 3);
                # TE ativa (CIENTE/análise) só do ano de emissão; antiga não-
                # concluída sai. Ano vem do código da emenda (AAAA...) ou do plano.
                ano_te = _ano_de(cod_em, it.get("planoAcaoCodigo"))
                if not _fed_retem(ano_te, ano_emissao, sit, completo):
                    continue
                # CONCLUIDA/paga -> PARTE 3; demais (CIENTE/EM_ANALISE/...) -> PARTE 1.
                parte_te = 3 if ("conclu" in sl or "pag" in sl or "finaliz" in sl) else 1
                parl = cod_em.split("-", 1)[1].strip() if "-" in cod_em else ""
                valor = _money(it.get("valorTotal"))
                orgao_te = "Transferência Especial (Emenda Pix)"
                tipo_te = "Transferência Especial"
                secao_te = _SEC_FED
                if completo:
                    st = _fed_status(sit)
                    parte_te, secao_te, suf = _destino_completo(
                        "federal", "transferencia_especial", st, ano_te,
                        ano_te if st == "paga" else None, ano_emissao,
                        False, False, False)
                    orgao_te = orgao_te + suf
                    tipo_te = "Plano de Ação"  # rotulo do numero na referencia (Fazenda/TE)
                add_item(parte_te, secao_te, orgao_te, {
                    "tipo": tipo_te,
                    "numero": it.get("planoAcaoCodigo") or "",
                    "objeto": it.get("objetoDescricao") or it.get("politicasPublicas") or "",
                    "parlamentar": parl,
                    "valor_global": valor,
                    "valor_repasse": valor,
                    "valor_contrapartida": 0,
                    "banco": "", "agencia": "", "conta": "",
                    "saldo_bancario": None, "dt_saldo": None,
                    "dt_fim_vigencia": None,
                    "situacao_atual": sit_te,
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
        parte_mec, secao_mec, tipo_mec = 3, "INSTRUMENTOS DE REPASSE FEDERAIS", (r[0] or "MEC")
        if completo:
            # SIMEC = pagamentos: ano do pagamento (dt_pgto/ano) manda p/ Parte 2
            # ("REPASSES DE {ano}") se for do ano corrente, senao Parte 3.
            ano_pg = r[9] or _ano_de(_iso(r[2]))
            parte_mec, secao_mec, suf = _destino_completo(
                "federal", "simec", "paga", ano_pg, ano_pg, ano_emissao, False, False, False)
            orgao = orgao + suf
            tipo_mec = "Processo"  # rotulo do numero na referencia (Educacao-SIMEC)
        add_item(parte_mec, secao_mec, orgao, {
            "tipo": tipo_mec,
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
        orgao = (r[5] or "SIGCON Estadual") + " - Indicação"
        objeto = f"{r[3] or ''} {r[4] or ''}".strip()
        if completo:
            st = _fed_status(sit)
            if st == "dead":
                continue  # rejeitada/anulada nao entra no completo
            # Indicacao estadual = "Resolucoes e T.E." (nao e convenio) -> tem_convenio=False.
            parte, secao_em, _suf = _destino_completo(
                "estadual", "emenda_estadual", st, r[2], r[2], ano_emissao,
                _pend_municipal(sit), False, False)
        else:
            # Emendas SIGCON => estadual => PARTE 2
            parte = _classifica_parte("estadual", sit, None)
            secao_em = "INSTRUMENTOS DE REPASSE ESTADUAIS"
        add_item(parte, secao_em, orgao, {
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

    # === Novo PAC / Selecao PAC / Doacao (TransfereGov) — federal, SO no completo ===
    # A referencia lista itens 'Novo PAC'/'Doacao Selecao Novo PAC'/'(DOACAO)' cujo
    # "parlamentar" e na verdade o PROGRAMA. Fonte: tabela transferegov_pac.
    # Best-effort: se a tabela nao existir no tenant, o completo sai sem PAC.
    if completo:
        try:
            pac = await db.execute(text("""
                SELECT numero_proposta, programa, situacao, valor_repasse,
                       valor_contrapartida, valor_total, emenda_parlamentar, objeto
                FROM transferegov_pac WHERE municipio_id = :m
            """), {"m": municipio_id})
            for r in pac.fetchall():
                sit = r[2] or ""
                st = _fed_status(sit)
                if st == "dead":
                    continue
                ano_pac = _ano_de(r[0])
                prog = (r[1] or "").strip()
                is_doacao = "doa" in (prog + " " + sit).lower()
                # Parlamentar = emenda quando ha; senao o PROGRAMA (Novo PAC / Doacao).
                parl = (r[6] or "").strip() or prog or "Novo PAC"
                num = r[0] or ""
                if ano_pac:
                    num = f"{num} - {ano_pac}"
                if is_doacao:
                    num = f"{num} (DOAÇÃO)"
                pre_novo = st == "ativa" and ano_pac == ano_emissao
                parte_pac, secao_pac, suf = _destino_completo(
                    "federal", "pac", st, ano_pac, None, ano_emissao,
                    _pend_municipal(sit), pre_novo, False)
                add_item(parte_pac, secao_pac, ("Novo PAC" + suf), {
                    "tipo": "Proposta",
                    "numero": num,
                    "objeto": r[7] or prog or "",
                    "parlamentar": parl,
                    "valor_global": _money(r[5]),
                    "valor_repasse": _money(r[3]),
                    "valor_contrapartida": _money(r[4]),
                    "banco": "", "agencia": "", "conta": "",
                    "saldo_bancario": None, "dt_saldo": None,
                    "dt_fim_vigencia": None,
                    "situacao_atual": sit,
                    "fonte": "pac",
                    "fonte_ref": r[0],
                })
        except Exception as ex:
            logger.warning(f"RM completo: PAC indisponivel p/ {municipio_id}: {str(ex)[:120]}")

    # === Converte dict -> lista ordenada (formato final) ===
    # Ordem das secoes dentro de cada Parte: FEDERAIS primeiro, ESTADUAIS depois,
    # outras secoes (se houver) preservam ordem de insercao no fim.
    if completo:
        # Ordem da referencia: dentro da Parte 2 -> FEDERAIS (pendencia municipal),
        # depois REPASSES DE {ano} (pagos), depois estadual; na Parte 3 -> FEDERAL,
        # depois estadual (Resolucoes/T.E., depois Convenios).
        SECAO_PRIORIDADE = [
            _SEC_FED_PLURAL,
            f"REPASSES DE {ano_emissao}:",
            _SEC_FED_SINGULAR,
            _SEC_EST_P2,
            _SEC_EST_P3_RES,
            _SEC_EST_P3_CONV,
        ]
    else:
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

    def _ordena_itens(itens):
        # No completo (multi-ano) ordena por ANO desc + numero, como a referencia.
        # No anual mantem a ordem de insercao (comportamento historico).
        if not completo:
            return itens
        return sorted(itens, key=lambda it: (-(_ano_de(it.get("numero")) or 0), str(it.get("numero") or "")))

    out_partes = []
    for n in sorted(partes_data.keys()):
        p = partes_data[n]
        secoes_out = []
        for s_idx, (s_titulo, grupos) in enumerate(_ordena_secoes(p["secoes"]), start=1):
            grupos_out = []
            for g_idx, (orgao, itens) in enumerate(grupos.items(), start=1):
                itens_ord = _ordena_itens(itens)
                grupos_out.append({
                    "ordem": g_idx,
                    "orgao": orgao,
                    "itens": [{"ordem": i + 1, **it} for i, it in enumerate(itens_ord)],
                })
            secoes_out.append({"ordem": s_idx, "titulo": s_titulo, "grupos": grupos_out})
        if secoes_out:
            out_partes.append({"ordem": n, "titulo": p["titulo"], "secoes": secoes_out})
    return {"partes": out_partes}
