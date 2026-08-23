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


def _vol_pre_empenho(st: str, ano_prop: int | None, ano_ref: int,
                     parlamentar: str | None) -> bool:
    """True quando a proposta do TransfereGov e cadastro PRE-EMPENHO do ano de
    referencia E repasse 100% VOLUNTARIO — o unico caso que a Parte 4 aceita.

    REGRA DO DONO (auditoria da Parte 4): repasse 100% voluntario NAO tem nome de
    parlamentar atrelado. Proposta com autor de emenda (o caso concreto: Junior
    Amaral / Ministerio do Esporte) e EMENDA, nao voluntaria — cair na Parte 4
    dizia ao prefeito que aquele dinheiro era discricionario e "sem garantia",
    quando ele tem padrinho. Devolvendo False aqui, o item segue o caminho normal
    de qualquer federal nao pago em _destino_completo e sobe para a secao superior:
    Parte 1 (pendencia de empenho/desembolso/aceite em Brasilia) ou Parte 2 quando
    a bola esta com o municipio.

    NAO condicionar a estar empenhada: o status 'empenhada' JA nao chega aqui (a
    Parte 4 exige st == 'ativa'), entao a condicao composta seria letra morta e a
    emenda relatada continuaria exatamente onde esta.

    e_parlamentar_real e nao `bool(parlamentar)`: o campo carrega marcador de
    ausencia de portal ("Nao ha", "Nao informado"). Tratar texto de portal como
    autor de emenda expulsaria da Parte 4 proposta que e voluntaria de verdade —
    o mesmo defeito que ja custou um "parlamentar" de R$ 14,9 mi no SIGCON
    (services/nome_parlamentar.py)."""
    if st != "ativa" or ano_prop != ano_ref:
        return False
    return not e_parlamentar_real(parlamentar or "")


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
               completo: bool = False, anos_sel: set[int] | None = None) -> bool:
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

    completo=True: de ano ANTERIOR so permanece quem teve REPASSE EFETIVO
    (vl_pago > 0) — e esse o historico que alimenta a Parte 3. O rotulo
    'Empenhado' vindo do TEXTO do portal NAO basta: _fns_classifica promove esse
    texto por cima do rotulo do dinheiro, e havia proposta de 2014/2017 marcada
    'Empenhado' com repasse R$ 0. E a mesma doutrina que o calculo de `sit` em
    montar_conteudo ja seguia ("Empenho CONFIRMADO exige REPASSE EFETIVO").
    Pedido do dono: proposta antiga NUNCA empenhada sai do relatorio.

    ⚠️ `anos_sel` = a SELECAO de anos do relatorio (vazia/None = "todos os anos").
    O corte acima so vale no relatorio de TODOS OS ANOS. Havendo selecao, CADA ANO
    ESCOLHIDO VALE POR SI: quem selecionou [2023, 2024, 2025] pediu aqueles anos de
    proposito, e comparar tudo contra o MAIOR ano da selecao (o `ano_emissao`)
    derrubaria justamente 2023 e 2024 — o oposto do pedido. Por isso, com selecao,
    a pergunta passa a ser "o ano do item esta na selecao?", nao "e maior ou igual
    ao ano de referencia?". Regra do dono, decidida em 19/08/2026.

    Rejeitada/dead nunca entra no completo."""
    if sit_cls == "Rejeitada" or _fed_status(sit_cls) == "dead":
        return False if completo else (ano_prop is not None and ano_prop == ano_emissao)
    if completo:
        # `and vl_pago > 0`: empenho REAL, nao o rotulo. Nao derruba o que a
        # docstring promete manter — pagamento no ano de referencia e empenhada
        # com saldo a receber tem, os dois, vl_pago > 0.
        if _fed_status(sit_cls) in ("paga", "empenhada", "vigente") and vl_pago > 0:
            return True
        if anos_sel:
            return ano_prop is not None and ano_prop in anos_sel
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


def _fmt_brl(v) -> str:
    """R$ 1.234.567,89 (formato do relatorio)."""
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    except (TypeError, ValueError):
        return ""


def _jsonb(v):
    """JSONB que pode chegar como dict OU como str, dependendo do driver."""
    if isinstance(v, str):
        try:
            import json as _json
            return _json.loads(v)
        except (ValueError, TypeError):
            return None
    return v


def _det_clausula_txt(detalhe_contratacao) -> str:
    """Todo o texto do JSONB `situacao_contratacao_detalhe`, para a deteccao de
    pendencia municipal. E la que o portal poe "Motivo da Cláusula Suspensiva":
    "Termo de Referência" — a coluna dedicada costuma vir NULA."""
    d = _jsonb(detalhe_contratacao)
    if not isinstance(d, dict):
        return ""
    return " ".join(str(v) for v in d.values() if v)


def _desembolso_ops_obs(ops_obs) -> dict:
    """Situacao do DESEMBOLSO a partir de `ops_obs` (ja coletado).

    Devolve valor_desembolsado/valor_a_desembolsar e a lista de LANCAMENTOS
    (data + valor + nº da OB). O RM usa isto para dizer "PENDENTE DE DESEMBOLSO"
    quando a licitacao ja foi aceita e nada foi desembolsado, e para mostrar os
    lancamentos quando houve."""
    d = _jsonb(ops_obs)
    if not isinstance(d, dict):
        return {}
    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None
    lanc = []
    for ob in (d.get("obs") or []):
        if not isinstance(ob, dict):
            continue
        lanc.append({
            "data": (ob.get("data_emissao_ob") or "").strip(),
            "valor": _num(ob.get("valor")),
            "numero_ob": (ob.get("numero_ob") or "").strip(),
            "situacao": (ob.get("situacao") or "").strip(),
        })
    return {
        "valor_desembolsado": _num(d.get("valor_desembolsado")),
        "valor_a_desembolsar": _num(d.get("valor_a_desembolsar")),
        "dt_ultimo_desembolso": (d.get("data_ultimo_desembolso") or "") or None,
        "desembolsos": lanc,
    }


def _licitacao_aceita(processo_execucao) -> bool:
    """True quando alguma licitacao do instrumento esta ACEITA (coluna 'aceite'
    do Processo de Execucao). E o gatilho de "PENDENTE DE DESEMBOLSO"."""
    lst = _jsonb(processo_execucao)
    if not isinstance(lst, list):
        return False
    for it in lst:
        if not isinstance(it, dict):
            continue
        a = (it.get("aceite") or "").strip().casefold()
        # ⚠️ Substring "aceit" NAO serve: casa "Não Aceito", "Aguardando aceite" e
        # "Aceite Pendente" — todos o OPOSTO de aceito. So conta o aceite EFETIVO.
        if not a or "nao" in a.replace("ã", "a") or "pend" in a or "aguard" in a:
            continue
        if a.startswith("aceit"):
            return True
    return False


def _projeto_basico_resumo(projeto_basico) -> str:
    """"Termo de Referência — Em Análise": QUAL documento sustenta a clausula
    suspensiva e em que PE ele esta no portal. String vazia quando nao ha captura
    — o relatorio so imprime a linha quando ha o que dizer."""
    d = _jsonb(projeto_basico)
    if not isinstance(d, dict):
        return ""
    sit = (d.get("situacao") or "").strip()
    docs = d.get("documentos") if isinstance(d.get("documentos"), list) else []
    # ⚠️ O rotulo util e a DESCRICAO do anexo ("Termo de Referência"). O `tipo`
    # vem abreviado do portal ("Termo Referência") e o nome do arquivo e ruido
    # ("TERMO DE REFERÊNCIA - ARAÚJOS - ESPORTE.pdf") — nao servem para o RM.
    rotulo = ""
    for it in docs:
        if isinstance(it, dict) and (it.get("descricao") or it.get("tipo")):
            rotulo = (it.get("descricao") or it.get("tipo") or "").strip()
            break
    if rotulo and sit:
        return f"{rotulo} — {sit}"
    return sit or rotulo


def _programa_limpo(programa) -> str:
    """Nome do PROGRAMA da voluntaria, pronto para imprimir (ex.: "PRONE - ...").

    Duas fontes escrevem `transferegov_propostas.programa` e elas NAO tem o mesmo
    formato:
      - dado aberto (autoritativo, sobrescreve todo dia): NOME_PROGRAMA de
        siconv_programa.zip — so o nome, sem codigo.
      - navegador: a celula "Programa" da tela Dados da Proposta, capturada pelo
        varredor GENERICO de pares label|valor. Esse mesmo varredor ja colou lixo
        com TAB em `modalidade` — por isso cortamos no primeiro TAB/quebra, para o
        RM nao herdar o defeito.

    Tambem descarta o codigo do programa quando ele vem colado no comeco
    ("0036420250001 - PRONE ..."), SO quando o prefixo e TODO DIGITO: uma SIGLA
    ("PRONE - PROGRAMA NACIONAL...") e exatamente o que o dono quer ler e NAO pode
    ser cortada.

    Limpa na LEITURA, nao na ingestao: nao reprocessa milhares de linhas, nao muda
    o que as telas de proposta ja exibem e vale para dado antigo ja gravado."""
    import re as _re
    s = str(programa or "")
    s = _re.split(r"[\t\r\n]", s)[0]           # corta o lixo colado do portal
    s = _re.sub(r"\s+", " ", s).strip()
    s = _re.sub(r"^\d{3,}\s*[-–]\s*", "", s)   # tira SO codigo numerico
    return s.strip()


def _moeda_br(v) -> str:
    """R$ 280.000,00 — o formato do relatorio. Esta frase e montada aqui, no
    builder, e vai CONGELADA no JSONB do RM, entao nao pode depender do render."""
    try:
        s = f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _pct_br(p) -> str:
    """93,70% — duas casas, virgula decimal."""
    try:
        return f"{float(p):.2f}".replace(".", ",") + "%"
    except (TypeError, ValueError):
        return "-"


def _obra_pct(valor_total, valor_realizado) -> float | None:
    """Percentual de execucao da obra, DERIVADO — sem requisicao nenhuma.

    O portal mostra esse numero no "Resumo Fisico-Financeiro", mas os dois valores
    que o compoem ja vem no JSONB de obras (valorTotalSubmetas e
    valorTotalRealizado, ver ingestion/transferegov_http.py). Buscar a tela do
    resumo so para ler a divisao seria um GET a mais por instrumento num host de
    2 vCPU — e o resultado bate: 344.827,46 / 368.000,00 = 93,70%, digito a
    digito com o exemplo do dono.

    None quando nao da para dividir (total ausente ou zero)."""
    t, r = _money(valor_total), _money(valor_realizado)
    if t is None or r is None or t <= 0:
        return None
    return round(r * 100.0 / t, 2)


def _obra_resumo(obras, medicoes: int | None = None) -> str:
    """Frase de situacao da obra para o RM, no modelo que o dono especificou.

    DUAS SAIDAS, na ordem de precedencia:

    1. SEM ART/RRT cadastrada -> a obra nem pode ser medida, entao a pendencia e
       essa e nenhum numero de execucao importa:
       "Necessario cumprir a exigencia de cadastro da ART/RRT para possibilitar o
        lancamento da primeira medicao no sistema."
    2. COM execucao -> "A obra encontra-se em execucao, [com N medicoes
       atestadas, ]totalizando R$ X em valor executado, correspondente a Y% do
       valor total de R$ Z."

    ⚠️ `medicoes` E OPCIONAL PORQUE O DADO AINDA NAO E COLETADO. O exemplo do dono
    traz "com 02 medicoes atestadas", mas a contagem de medicoes atestadas nao
    esta em nenhum endpoint que o obras() ja consulta (contratoslotes, contratos,
    arts, situacaoParalisacao). Em vez de inventar o numero ou travar a frase
    inteira, a oracao some quando o valor e desconhecido — o resto e 100%
    derivado do que ja existe. Quando a coleta da medicao entrar, basta passar o
    parametro.

    String vazia quando nao ha obra ou nao ha o que dizer."""
    d = _jsonb(obras)
    if not isinstance(d, dict):
        return ""
    lotes = d.get("lotes") if isinstance(d.get("lotes"), list) else []
    tem_art = any((l or {}).get("arts") for l in lotes if isinstance(l, dict))
    if lotes and not tem_art:
        return ("Necessário cumprir a exigência de cadastro da ART/RRT para "
                "possibilitar o lançamento da primeira medição no sistema.")
    total, realizado = _money(d.get("valor_total_submetas")), _money(d.get("valor_total_realizado"))
    if not total or realizado is None:
        return ""
    med = ""
    if medicoes:
        # Substantivo e adjetivo trocam JUNTOS: montar por sufixo ("medição" +
        # "ões") produzia "mediçãoões". O dono escreveu com zero a esquerda.
        palavra = "medições atestadas" if medicoes != 1 else "medição atestada"
        med = f"com {medicoes:02d} {palavra}, "
    return (f"A obra encontra-se em execução, {med}totalizando "
            f"{_moeda_br(realizado)} em valor executado, correspondente a "
            f"{_pct_br(_obra_pct(total, realizado))} do valor total de {_moeda_br(total)}.")


def _nes_resumo(notas) -> str:
    """"Situacao do NEs" para o RM: uma entrada por nota de empenho REAL.

    Ex.: "2026NE000320 — R$ 280.000,00 — Enviado (09/03/2026)"

    ⚠️ IGNORA A MINUTA. A listagem do portal mistura o empenho com a MINUTA de
    empenho, que vem sem numero e com valor de R$ 1,00 — imprimir ou somar isso
    poria R$ 1,00 no relatorio como se fosse recurso. O coletor ja marca a linha
    (`minuta_apenas`) na leitura; aqui so se obedece a marca.

    ⚠️ VAZIO NAO SIGNIFICA "NAO HA EMPENHO". Proposta nunca consultada tem
    `notas_empenho` NULO e cai no mesmo vazio de quem foi consultado e nao tem
    NE. Por isso o RM apenas OMITE a linha — nunca escreve "sem empenho", que
    seria afirmar algo que nao foi medido."""
    lst = _jsonb(notas)
    if not isinstance(lst, list):
        return ""
    partes = []
    for n in lst:
        if not isinstance(n, dict) or n.get("minuta_apenas"):
            continue
        p = [str(n.get("numero") or "").strip()]
        if n.get("valor") is not None:
            p.append(_moeda_br(n["valor"]))
        if n.get("situacao"):
            sit = str(n["situacao"]).strip()
            dt = str(n.get("dt_emissao") or "").strip()
            p.append(f"{sit} ({dt})" if dt else sit)
        linha = " — ".join(x for x in p if x)
        if linha:
            partes.append(linha)
    return "; ".join(partes)


def _ano_pagamento_ops_obs(ops_obs) -> int | None:
    """ANO do ultimo desembolso da voluntaria, lido de `ops_obs`.

    Sem isto o `ano_pgto` das voluntarias era SEMPRE None, entao `pago_corrente`
    nunca era verdadeiro e NENHUMA voluntaria caia no bloco "REPASSES DE {ano}" da
    Parte 2 — toda voluntaria paga descia para a Parte 3 (anos anteriores), mesmo a
    paga NESTE ano. Formato (raspado do portal):
      {"data_ultimo_desembolso": "24/07/2026", "obs": [{"data_emissao_ob": "24/07/2026", ...}]}
    Usa a data do ultimo desembolso e, na falta dela, a MAIOR data de emissao de OB."""
    if isinstance(ops_obs, str):
        try:
            import json as _json
            ops_obs = _json.loads(ops_obs)
        except (ValueError, TypeError):
            return None
    if not isinstance(ops_obs, dict):
        return None
    anos = []
    y = _ano_de(ops_obs.get("data_ultimo_desembolso"))
    if y:
        anos.append(y)
    for ob in (ops_obs.get("obs") or []):
        if isinstance(ob, dict):
            y = _ano_de(ob.get("data_emissao_ob"))
            if y:
                anos.append(y)
    return max(anos) if anos else None


def _situacao_estadual(situacao: str | None, raw: dict) -> str:
    """SITUACAO exibida do instrumento ESTADUAL (SIGCON).

    O campo `situacao` do SIGCON e generico ("Em vigor", "Encerrado", "Cancelado") e
    NAO diz em que pe o convenio esta — era por isso que o relatorio saia mostrando
    so "EM VIGOR" nos estaduais. A situacao REAL do momento esta na ULTIMA ALTERACAO
    (ex.: "ANALISE - CHECKLIST DE TERMO ADITIVO", "CADASTRAMENTO DA ALTERACAO",
    "VIGENTE"), capturada por _scrape_alteracoes (raw_data.ultima_alteracao_*).

    Junta as duas quando ha alteracao e ela ACRESCENTA informacao; senao devolve so
    a situacao base (degrada suave — a maioria dos convenios ainda nao foi revisitada
    pelo rodizio do scraper)."""
    base = (situacao or "").strip()
    if not isinstance(raw, dict):
        return base
    alt = (raw.get("ultima_alteracao_situacao") or "").strip()
    if not alt:
        return base
    # Nao repete quando a alteracao diz a mesma coisa (ex.: base "Encerrado" x
    # alteracao "ENCERRADO"): o relatorio ficaria "Encerrado · ... : ENCERRADO".
    if not base or alt.casefold() == base.casefold():
        detalhe = alt
    else:
        detalhe = f"{base} · Última alteração: {alt}"
    tipo = (raw.get("ultima_alteracao_tipo") or "").strip()
    data = (raw.get("ultima_alteracao_data") or "").strip()
    sufixo = " ".join(x for x in (tipo, f"em {data}" if data else "") if x).strip()
    return f"{detalhe} ({sufixo})" if sufixo else detalhe


_ALT_CHAVES = ("ultima_alteracao_situacao", "ultima_alteracao_tipo", "ultima_alteracao_data",
               "ultima_alteracao_titulo", "ultima_alteracao_nr_controle")


def _alteracao_campos(raw: dict) -> dict:
    """Campos da ultima alteracao do convenio estadual, para a caixa de destaque do
    PDF (rm_pdf._alteracao_destaque). Vazio quando o scraper ainda nao capturou.

    Aceita captura PARCIAL: o scraper grava o que achou (celula vazia vira None), e
    exigir a `situacao` jogava fora tipo/data/titulo/nº ja capturados."""
    if not isinstance(raw, dict) or not any((raw.get(k) or "").strip() for k in _ALT_CHAVES):
        return {}
    return {
        "alteracao_situacao": (raw.get("ultima_alteracao_situacao") or "").strip(),
        "alteracao_tipo": (raw.get("ultima_alteracao_tipo") or "").strip(),
        "alteracao_data": (raw.get("ultima_alteracao_data") or "").strip(),
        "alteracao_titulo": (raw.get("ultima_alteracao_titulo") or "").strip(),
        "alteracao_nr_controle": (raw.get("ultima_alteracao_nr_controle") or "").strip(),
    }


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
                          completo: bool = False, anos: list[int] | None = None) -> dict:
    """Monta o conteudo JSONB de um RM a partir dos dados do banco.

    ano_emissao: ano-base da janela do relatório (year da data de referência).
    Mantém só propostas federais do ano de emissão (em análise/aprovação) + todas
    as empenhadas (qualquer ano). Default = ano atual.

    completo=False (RM ANUAL — legado): 3 Partes por esfera, recorte por ano_emissao.

    completo=True (padrao "Freitas"): 4 Partes por ESTAGIO/SITUACAO (ver
    _destino_completo), com os sub-blocos e rotulos da referencia.

    anos: SELECAO de anos do relatorio (novo modelo — o RM e UM so, com o escopo
    escolhido). None/vazio = TODOS os anos (o "completo"). Lista com anos = filtra
    os itens para esses anos (pelo ano do numero do instrumento). O filtro roda por
    cima da estrutura de 4 partes: 1 ano -> so ele; varios -> os anos juntos num
    unico relatorio; todos/vazio -> o completo."""
    if not ano_emissao:
        ano_emissao = date.today().year
    anos_filtro = set(a for a in (anos or []) if a)  # vazio => sem filtro (todos)
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

    def add_item(parte_n: int, secao: str, orgao: str, item: dict, ano: int | None = None):
        """Adiciona o item na arvore. `ano` e o ano que a FONTE ja calculou (c.ano,
        ano_prop, ano_te, ano do pagamento...) — carimbado como `ano_item`.

        ⚠️ O recorte por anos (_no_escopo) NAO pode re-derivar o ano do TEXTO do
        numero: ha fontes cujo numero nao carrega ano (SIMEC usa a OB, PAC/emendas
        usam so o sequencial), e elas cairiam fora de qualquer RM filtrado por ano,
        em silencio. Quando a fonte nao sabe o ano, cai no ano do numero e, se ainda
        assim nao houver, o item PERMANECE (melhor um item a mais do que sumir)."""
        p = partes_data[parte_n]
        if secao not in p["secoes"]:
            p["secoes"][secao] = {}
        if orgao not in p["secoes"][secao]:
            p["secoes"][secao][orgao] = []
        if ano and not item.get("ano_item"):
            item["ano_item"] = int(ano)
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
                    if not _fns_retem(c.ano, ano_emissao, ind, vlpago or 0, vlpagar or 0,
                                      sit_cls, completo, anos_filtro):
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
                    }, ano=c.ano)
            elif (c.ano is not None and c.ano >= ano_emissao) or (
                    completo and _fed_status(c.situacao) != "dead"
                    and ((anos_filtro and c.ano in anos_filtro)
                         or (not anos_filtro and (_money(raw.get("vlPago")) or 0) > 0))):
                # Fallback: bucket SEM as propostas individuais. Nao e so "coleta
                # antiga": _fetch_individuais devolve [] tambem em falha transitoria
                # (tipo vazio, HTTP != 200, excecao de rede) e a linha do `if
                # individuais:` acima manda lista vazia para ca. Sem as individuais
                # nao da pra saber se houve pagamento no ano, entao no anual so
                # entra se for do proprio ano de referência.
                # No completo segue a MESMA regra do _fns_retem: com selecao de
                # anos, o ano escolhido vale por si; sem selecao (todos os anos),
                # ano anterior so entra com REPASSE EFETIVO (vlPago do agregado,
                # guardado em raw_data) — a `situacao` gravada pelo scraper marca
                # "Empenhado" so por vlPagar > 0, que nao e empenho real.
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
                }, ano=c.ano)
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
            # SITUACAO do estadual: o campo `situacao` do SIGCON e generico ("Em vigor",
            # "Encerrado") e sozinho nao diz em que PE o convenio esta. A situacao REAL
            # esta na ULTIMA ALTERACAO (ex.: "ANALISE - CHECKLIST DE TERMO ADITIVO"),
            # capturada por _scrape_alteracoes em raw_data. Junta as duas — era o motivo
            # de o relatorio mostrar so "EM VIGOR" nos estaduais.
            "situacao_atual": _situacao_estadual(c.situacao, raw),
            # ⚠️ A situacao CRUA da fonte, ao lado da enriquecida. `situacao_atual`
            # passou a carregar a NARRATIVA da ultima alteracao, e quem CLASSIFICA
            # (rm_export._e_pendencia) nao pode ler narrativa: uma alteracao
            # "ENCERRADO"/"CONCLUIDA" num convenio ATIVO o faria sumir, calado, do
            # Resumido (o PDF das pendencias). Classificar sempre por esta.
            "situacao_base": (c.situacao or "").strip(),
            **_alteracao_campos(raw),
            "fonte": "sigcon",
            "fonte_ref": str(c.id),
        }, ano=ano_est)

    # === TransfereGov Voluntarias (SICONV) ===
    vol = await db.execute(text("""
        SELECT id, numero_proposta, codigo_instrumento, situacao, orgao, objeto,
               dt_fim_vigencia, valor_global, valor_repasse, valor_contrapartida,
               situacao_contratacao, clausula_suspensiva_dt_prevista,
               clausula_suspensiva_motivo, parlamentar, situacao_contratacao_detalhe,
               detalhe->>'Empenhado', processo_execucao_qtd, historico_comunicacoes,
               detalhe->>'Banco', detalhe->>'Agência', detalhe->>'Conta',
               processo_execucao,
               -- OPs/OBs: e daqui que sai o ANO DO PAGAMENTO da voluntaria (o
               -- bloco "REPASSES DE {ano}" da Parte 2 dependia dele e vinha
               -- sempre vazio de voluntaria, porque ninguem lia esta coluna).
               ops_obs,
               -- Situacao do Projeto Basico/Termo de Referencia: o documento que
               -- sustenta a clausula suspensiva, e em que pe ele esta no portal.
               projeto_basico,
               -- PROGRAMA do instrumento (ex.: "PRONE - ..."): o Objeto diz O QUE
               -- e; o programa diz DE ONDE vem o dinheiro. Pedido do dono.
               -- ULTIMA COLUNA DE PROPOSITO (row[24]). O laco abaixo le por INDICE;
               -- acrescentar no MEIO do SELECT desloca TODOS os row[N] seguintes em
               -- silencio — `objeto` passaria a ler dt_fim_vigencia, `parlamentar`
               -- viraria outra coisa (e com ela a decisao de Parte 4), os valores
               -- trocariam de lugar e os JSONB chegariam como tipo errado.
               -- Nada disso levanta excecao: sai relatorio errado, calado.
               programa,
               -- NEs (Notas de Empenho). ULTIMA coluna de proposito: inserir no
               -- MEIO deslocaria `programa` (row[24]) e o RM passaria a imprimir
               -- a lista de empenhos no lugar do nome do programa, calado.
               notas_empenho,
               -- OBRAS (medicao). O RM nunca leu esta coluna, apesar de o
               -- coletor grava-la desde sempre: e dai que sai o valor total, o
               -- realizado e o percentual da obra. ULTIMA coluna, como as duas
               -- acima — inserir no meio desloca `programa` e `notas_empenho`.
               obras
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
            # Parte 4 = voluntaria PURA (pre-empenho do ano corrente e SEM autor de
            # emenda). row[13] = coluna `parlamentar`, preenchida pelo dado aberto
            # (ingestion/transferegov_opendata.py e siconv_emenda_backfill.py) — nao
            # pelo scraper, que nao ve o autor da emenda na tela guest.
            pre_novo = _vol_pre_empenho(st, ano_prop, ano_emissao, row[13])
            # Pendencia municipal: situacao do ciclo + contratacao + motivo da clausula.
            # ⚠️ O motivo costuma vir SO no JSONB `situacao_contratacao_detalhe`
            # ("Motivo da Cláusula Suspensiva": "Termo de Referência") com a COLUNA
            # `clausula_suspensiva_motivo` NULA — lendo so a coluna, um convenio
            # parado esperando Termo de Referencia (acao do MUNICIPIO) era
            # classificado como pendencia de Brasilia. Le os dois.
            pend = _pend_municipal(sit, row[10], row[12], _det_clausula_txt(row[14]))
            # Contratacao Normal com ZERO licitacao registrada tambem e acao do
            # MUNICIPIO (falta ele licitar). `== 0` e nao `not row[16]`: None
            # significa "nao coletado" e jogaria toda proposta nao-raspada p/ ca.
            if row[16] == 0 and "normal" in (row[10] or "").casefold():
                pend = True
            # ano do PAGAMENTO (OPs/OBs) — alimenta o bloco "REPASSES DE {ano}".
            ano_pgto_vol = _ano_pagamento_ops_obs(row[22])
            parte, secao, suf = _destino_completo(
                "federal", "voluntaria", st, ano_prop, ano_pgto_vol, ano_emissao,
                pend, pre_novo, bool(row[2]))
            orgao = orgao + suf
        else:
            parte, secao = _federal_destino(sit)
        # Campos SEPARADOS (sem duplicar): situacao do ciclo, contratacao,
        # detalhe da clausula (motivo/data) e empenho — cada um no seu campo.
        situacao_contr = row[10]
        clausula_dt = row[11]
        # Motivo da clausula: a COLUNA costuma vir nula e o valor real fica no JSONB.
        _det_c = _jsonb(row[14]) if isinstance(_jsonb(row[14]), dict) else {}
        clausula_motivo = row[12] or _det_c.get("Motivo da Cláusula Suspensiva") or ""
        # SITUAÇÃO DO CONTRATO no TransfereGov (ex.: "Cláusula Suspensiva") — vinha
        # so no JSONB e nao aparecia no relatorio.
        sit_contrato = (_det_c.get("Situação Atual do Contrato") or "").strip()
        empenhado = "Sim" if _fed_empenhada(sit) else "Não"  # validado pelo status
        # DESEMBOLSO (OPs/OBs): "PENDENTE DE DESEMBOLSO" quando a licitacao ja foi
        # ACEITA e nada saiu; senao o valor desembolsado + os lancamentos.
        _des = _desembolso_ops_obs(row[22])
        _vd = _des.get("valor_desembolsado")
        _aceita = _licitacao_aceita(row[21])
        sit_exibida = sit
        if _aceita and (_vd or 0) == 0:
            sit_exibida = f"{sit} · PENDENTE DE DESEMBOLSO" if sit else "PENDENTE DE DESEMBOLSO"
        elif (_vd or 0) > 0:
            sit_exibida = f"{sit} · Desembolsado: {_fmt_brl(_vd)}" if sit else f"Desembolsado: {_fmt_brl(_vd)}"
        # O NUMERO do convenio com o ANO DA PROPOSTA ao lado ("981397 /2025"): o
        # numero do instrumento sozinho nao diz de que ano ele e.
        _num_exib = row[2] or row[1] or ""
        if row[2] and row[1] and "/" in str(row[1]):
            _num_exib = f"{row[2]} /{str(row[1]).split('/')[-1].strip()}"
        add_item(parte, secao, orgao, {
            "tipo": tipo_label,
            "numero": _num_exib,
            "objeto": row[5] or "",
            # PROGRAMA (row[24], ULTIMA coluna do SELECT). Fica ao lado do objeto no
            # dict e, no PDF, na linha logo abaixo dele (rm_pdf._campos_do_item).
            # Vazio quando a proposta nunca foi coberta pelo dado aberto nem pelo
            # enrich — ai a linha simplesmente nao sai.
            "programa": _programa_limpo(row[24]),
            # EXIBE pelo mesmo criterio que CLASSIFICA: e `e_parlamentar_real` que
            # decide se a proposta e emenda (e portanto sai da Parte 4) — se o texto
            # nao e nome, tambem nao pode ser impresso como pessoa. Sem isto o item
            # ficava na Parte 4 (correto) e ao lado imprimia "Não há" como
            # parlamentar — o defeito de R$ 14,9 mi de services/nome_parlamentar.py,
            # agora do lado do RM, que CONGELA o texto em rm_relatorios.conteudo.
            "parlamentar": (row[13] or "") if e_parlamentar_real(row[13] or "") else "",
            "valor_global": _money(row[7]),
            "valor_repasse": _money(row[8]),
            "valor_contrapartida": _money(row[9]),
            # Banco/agencia/conta ja estao no JSONB `detalhe` (raspados junto do
            # resto da pagina Dados da Proposta). Antes ficavam "" p/ TransfereGov —
            # a tela do RM tem os campos, mas nunca eram preenchidos deste lado.
            "banco": row[18] or "", "agencia": row[19] or "", "conta": row[20] or "",
            "saldo_bancario": None, "dt_saldo": None,
            "dt_fim_vigencia": _iso(dt_fim),
            "situacao_atual": sit_exibida,   # ciclo + desembolso (ver acima)
            "situacao_base": sit,            # CRUA, p/ quem CLASSIFICA (rm_export)
            "empenhado": empenhado,
            "situacao_contratacao": situacao_contr or "",
            # Situacao do CONTRATO no TransfereGov (do JSONB do portal).
            "situacao_contrato": sit_contrato,
            "clausula_motivo": clausula_motivo or "",
            "clausula_dt": _iso(clausula_dt) if clausula_dt else "",
            # DESEMBOLSO: valores + lancamentos (data/valor/OB) p/ o relatorio.
            **_des,
            # Processo de Execução (Licitações): só relevante p/ contratação Normal.
            # 0 = Normal SEM processo/licitação registrado (flag); N>0 = tem; None = n/c.
            "processo_execucao_qtd": row[16],
            # Lista das licitações/processos COM detalhe (situação, modalidade, nº,
            # data, aceite) — para o RM mostrar cada registro, não só a contagem.
            "processo_execucao_lista": row[21],
            # Projeto Básico/Termo de Referência: o `clausula_motivo` diz QUAL
            # documento trava; este diz a SITUAÇÃO dele ("Em Análise").
            "projeto_basico": _projeto_basico_resumo(row[23]),
            # "Situação do NEs" — troca a INFERÊNCIA pelo DOCUMENTO. O campo
            # `empenhado` (Sim/Não) vinha do status do ciclo e o próprio
            # _fed_status documenta que ele marcava "Aprovadas" como empenhadas
            # sem empenho real; aqui sai o número, o valor e a data da NE.
            "nes": _nes_resumo(row[25]),
            # Situação da obra: frase pronta, com o percentual DERIVADO
            # de valores que já estavam no banco e ninguém exibia.
            "obra": _obra_resumo(row[26]),
            # EVENTO ATUAL do Histórico de Comunicações (mandatárias): onde o
            # instrumento está de fato na análise, + situação e considerações.
            **_evento_atual(row[17]),
            "fonte": "voluntaria",
            "fonte_ref": row[1],
        }, ano=ano_prop)

    # === Transferencia Especial / Plano de Acao (Emenda Pix) — federal ===
    # Fonte PERSISTIDA: tabela transferegov_te, alimentada pelo coletor do worker
    # (ingestion/transferegov_te.py). A API "especiais" rate-limita e nao da p/ buscar
    # ao vivo numa request; por isso lemos a tabela. Vazio ate o coletor rodar.
    try:
        te = await db.execute(text("""
            SELECT plano_acao_id, codigo, emenda, parlamentar, objeto, situacao,
                   situacao_trabalho, valor_total
            FROM transferegov_te WHERE municipio_id = :m
        """), {"m": municipio_id})
        for row in te.fetchall():
            cod = row[1] or ""
            sit = row[5] or ""            # planoAcaoSituacao (CIENTE/IMPEDIDO/...)
            sit_trab = row[6] or ""       # planoTrabalhoSituacao (a FASE real)
            cod_em = row[2] or ""
            # A fase REAL do dinheiro esta no PLANO DE TRABALHO (EM_ANALISE/APROVADO/
            # EMPENHADO/CONCLUIDO/...). Uso ela p/ retencao+estagio quando indica avanco
            # (empenhado/pago/concluido/execucao); senao o plano de acao (CIENTE etc).
            _tl = sit_trab.lower()
            sit_efetivo = sit_trab if any(x in _tl for x in ("empenh", "pag", "conclu", "finaliz", "execu")) else sit
            sl = sit_efetivo.lower()
            # Situacao exibida: mostra o plano de acao + o plano de trabalho.
            sit_pt = sit_trab.replace("_", " ").strip()
            sit_te = sit.replace("_", " ").strip()
            if sit_pt and sit_te.lower() != sit_pt.lower():
                sit_te = f"{sit_te} · Plano de Trabalho: {sit_pt}"
            # Mesma regra de ano: concluida/empenhada fica (Parte 3/qualquer ano); ativa
            # so do ano de referencia ou posterior. Ano vem do codigo da emenda ou do plano.
            ano_te = _ano_de(cod_em, cod)
            if not _fed_retem(ano_te, ano_emissao, sit_efetivo, completo):
                continue
            parte_te = 3 if ("conclu" in sl or "pag" in sl or "finaliz" in sl) else 1
            parl = row[3] or (cod_em.split("-", 1)[1].strip() if "-" in cod_em else "")
            valor = _money(row[7])
            orgao_te = "Transferência Especial (Emenda Pix)"
            tipo_te = "Transferência Especial"
            secao_te = _SEC_FED
            if completo:
                st = _fed_status(sit_efetivo)
                parte_te, secao_te, suf = _destino_completo(
                    "federal", "transferencia_especial", st, ano_te,
                    ano_te if st == "paga" else None, ano_emissao,
                    False, False, False)
                orgao_te = orgao_te + suf
                tipo_te = "Plano de Ação"  # rotulo do numero na referencia (Fazenda/TE)
            add_item(parte_te, secao_te, orgao_te, {
                "tipo": tipo_te,
                "numero": cod,
                "objeto": row[4] or "",
                "parlamentar": parl,
                "valor_global": valor,
                "valor_repasse": valor,
                "valor_contrapartida": 0,
                "banco": "", "agencia": "", "conta": "",
                "saldo_bancario": None, "dt_saldo": None,
                "dt_fim_vigencia": None,
                "situacao_atual": sit_te,
                "fonte": "transferencia_especial",
                "fonte_ref": str(row[0] or ""),
            }, ano=ano_te)
    except Exception as ex:
        logger.warning(f"RM: TE indisponivel p/ {municipio_id}: {str(ex)[:120]}")

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
        }, ano=(r[9] or _ano_de(_iso(r[2]))))

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
        }, ano=r[2])

    # === SIMEC/PAR — TERMOS DE COMPROMISSO (o INSTRUMENTO do MEC) ===
    # As liberacoes (simec_par_liberacoes) sao os PAGAMENTOS; aqui entra o termo em
    # si — processo, tipo, vigencia e valor —, coletado de carregaTermos.php
    # (ingestion/simec_termos.py). Best-effort: tenant sem a tabela segue sem MEC.
    if completo:
        try:
            tc = await db.execute(text("""
                SELECT processo, nr_documento, tipo_documento, tipo_objeto,
                       dt_validacao, periodo_pagamento, vigencia_txt, dt_vigencia,
                       valor_termo
                FROM simec_termos WHERE municipio_id = :m
            """), {"m": municipio_id})
            for r in tc.fetchall():
                venceu = bool(r[7]) and r[7] < date.today()
                # Termo com vigencia vencida ou ja pago -> Parte 3 (anos anteriores /
                # prestacao); vigente -> pendencia em Brasilia (Parte 1).
                st = "paga" if venceu else "vigente"
                ano_tc = (r[4].year if r[4] else None) or _ano_de(r[0], r[1])
                ano_pg = r[7].year if (venceu and r[7]) else None
                parte_tc, secao_tc, suf = _destino_completo(
                    "federal", "simec_termo", st, ano_tc, ano_pg, ano_emissao,
                    False, False, False)
                add_item(parte_tc, secao_tc, ("Ministério da Educação — Termo de Compromisso" + suf), {
                    "tipo": "Processo",   # rotulo do numero na referencia (Educacao/SIMEC)
                    "numero": r[0] or r[1] or "",
                    "objeto": " · ".join(x for x in (r[2], r[3]) if x) or "",
                    "parlamentar": "",
                    "valor_global": _money(r[8]),
                    "valor_repasse": _money(r[8]),
                    "valor_contrapartida": 0,
                    "banco": "", "agencia": "", "conta": "",
                    "saldo_bancario": None, "dt_saldo": None,
                    "dt_fim_vigencia": _iso(r[7]),
                    "situacao_atual": (r[6] or "").strip() or ("Vigente" if not venceu else "Vigência encerrada"),
                    "situacao_base": "Vigente" if not venceu else "Encerrado",
                    # Nº do documento e período de pagamento ficam visíveis no objeto
                    # do item quando existem (o portal os traz separados).
                    "simec_documento": r[1] or "",
                    "simec_periodo_pagamento": r[5] or "",
                    "fonte": "simec_termo",
                    "fonte_ref": r[0] or r[1] or "",
                }, ano=ano_tc)
        except Exception as ex:
            logger.warning(f"RM: SIMEC termos indisponivel p/ {municipio_id}: {str(ex)[:120]}")

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
                # SO as SELECIONADAS entram no RM. As demais situacoes do PAC
                # (Habilitada, Enviada para Análise, Cadastrada, Não Habilitada...)
                # sao etapas do funil de selecao — nao sao recurso do municipio e
                # inflavam o relatorio. Ver contagem real: Selecionada e ~1/4 da base.
                # Comparacao canonica (sem acento, exata): "selecionad" como
                # substring casaria "Não Selecionada" — o oposto.
                import unicodedata as _ud
                _s = "".join(c for c in _ud.normalize("NFD", sit.strip())
                             if _ud.category(c) != "Mn").casefold()
                if _s not in ("selecionada", "selecionado"):
                    continue
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
                }, ano=ano_pac)
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

    def _ano_do_item(it):
        """Ano do item: o que a FONTE calculou (`ano_item`, carimbado no add_item) e,
        so na falta dele, o ano lido do numero. None quando nenhum dos dois sabe."""
        return it.get("ano_item") or _ano_de(it.get("numero"))

    def _no_escopo(it):
        # Filtro de SELECAO de anos. Vazio = todos (completo).
        # Item SEM ano conhecido PERMANECE: sumir calado de um relatorio e pior do
        # que aparecer a mais — e ha fontes cujo numero nao carrega ano (SIMEC/OB).
        if not anos_filtro:
            return True
        y = _ano_do_item(it)
        return True if y is None else (y in anos_filtro)

    def _ordena_itens(itens):
        # No completo (multi-ano) ordena por ANO desc + numero, como a referencia.
        # No anual mantem a ordem de insercao (comportamento historico).
        if not completo:
            return itens
        return sorted(itens, key=lambda it: (-(_ano_do_item(it) or 0), str(it.get("numero") or "")))

    out_partes = []
    for n in sorted(partes_data.keys()):
        p = partes_data[n]
        secoes_out = []
        for s_idx, (s_titulo, grupos) in enumerate(_ordena_secoes(p["secoes"]), start=1):
            grupos_out = []
            for g_idx, (orgao, itens) in enumerate(grupos.items(), start=1):
                itens_ord = _ordena_itens([it for it in itens if _no_escopo(it)])
                if not itens_ord:
                    continue  # grupo fica vazio apos o recorte de anos -> nao entra
                grupos_out.append({
                    "ordem": g_idx,
                    "orgao": orgao,
                    "itens": [{"ordem": i + 1, **it} for i, it in enumerate(itens_ord)],
                })
            if grupos_out:  # secao vazia apos o recorte de anos nao entra
                secoes_out.append({"ordem": s_idx, "titulo": s_titulo, "grupos": grupos_out})
        if secoes_out:
            out_partes.append({"ordem": n, "titulo": p["titulo"], "secoes": secoes_out})
    return {"partes": out_partes}
