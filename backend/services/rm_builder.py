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
import re
from datetime import date, datetime
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from models import ConvenioEstadual, Municipio
from services.nome_parlamentar import e_parlamentar_real
from services.texto_rm import (
    frase, nome_proprio, normalizar_item, proprios_do_municipio,
    # ⚠️ `_sem_acento` e privado do modulo, mas e importado de proposito em vez de
    # copiado: `situacao` vem CRUA do portal, e comparar acento e o tipo de coisa
    # que duas implementacoes fazem diferente. Ver `_lic_em_elaboracao`.
    _sem_acento,
)
# Recorte por CONSULTA. Importado com apelido para nao se confundir com o
# `_no_escopo` local de `montar_conteudo`, que e o recorte por ANO — sao dois
# filtros diferentes, em momentos diferentes do mesmo laco.
from services.rm_fontes import no_escopo as fonte_no_escopo
from services.voluntarias_dump import ops_obs_preferido

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


def _lic_em_elaboracao(processo_execucao) -> bool:
    """Alguma licitacao do instrumento esta EM ELABORACAO?

    ⭐ Pedido do dono (26/08/2026): licitacao em elaboracao e acao do MUNICIPIO —
    quem elabora o edital e a prefeitura, nao Brasilia. Ate aqui o unico sinal de
    licitacao que empurrava para a Parte 2 era a CONTAGEM ZERO em contratacao
    Normal (o ramo logo abaixo do chamador); a LISTA de licitacoes nunca era
    consultada, e um edital em elaboracao ficava listado como pendencia federal.

    ⚠️ AUSENCIA NAO CLASSIFICA. `None` (nao coletado) e `[]` (coletado e nao ha)
    devolvem False — a mesma disciplina de `_sem_empenho` e `_empenhado_rotulo`.
    Classificar por ausencia poria cobranca falsa na mesa do prefeito, e o item
    ainda sumiria do RM Resumido, que so imprime a Parte 1.

    ⚠️ SUBSTRING SEM ACENTO, e nao igualdade: `situacao` e texto CRU do portal,
    sem enum, e ja se sabe que ele varia a grafia ("Em Elaboração", "EM
    ELABORACAO", com o acento corrompido em `?`). Comparar string inteira seria
    apostar numa grafia."""
    itens = _jsonb(processo_execucao)
    if not isinstance(itens, list):
        return False
    for it in itens:
        if not isinstance(it, dict):
            continue
        if "elabora" in _sem_acento(str(it.get("situacao") or "")).lower():
            return True
    return False


def _obra_sem_art(obras) -> bool:
    """A obra tem lotes LIDOS e nenhum deles tem ART/RRT cadastrada?

    ⭐ Pedido do dono (26/08/2026): cumprir a exigencia de ART/RRT e acao do
    MUNICIPIO. A frase ja existia em `_obra_resumo` — mas so alimentava o campo
    `obra` do item, que vira caixa cinza INFORMATIVA no PDF. Ou seja: a obra
    travada por falta de ART ficava na Parte 1 (Brasilia) com a pendencia do
    municipio escrita ao lado dela.

    ⚠️ Extraida de `_obra_resumo`, que passa a CHAMAR esta funcao. As duas nao
    podem divergir: o texto que o relatorio imprime e a classificacao que decide
    a Parte tem de sair da mesma condicao.

    ⚠️ `{}` (instrumento sem medicao — o portal responde 412) e `None` (nao
    consegui ler) devolvem False. So `lotes` NAO VAZIO autoriza afirmar.

    ⚠️ E TODO LOTE PRECISA TER TIDO A LEITURA RESPONDIDA. `arts` None significa
    que a chamada das ARTs nao respondeu naquele lote (portal fora, sessao
    expirada, 412); [] significa que respondeu e nao ha ART. Antes o coletor
    gravava [] nos DOIS casos, e esta funcao transformava a falha de leitura numa
    ACUSACAO ao municipio — "cumprir a exigencia de ART/RRT e demanda do
    MUNICIPIO" — num documento entregue ao prefeito, sem nada indicando que a
    leitura nao tinha acontecido.

    Basta UM lote nao lido para calar: com dois lotes, um lido e vazio e outro
    nao lido, afirmar "nao tem ART" seria apostar que o nao lido tambem esta
    vazio. ⚠️ Linha ANTIGA no banco tem [] das duas origens e e indistinguivel —
    ela so passa a valer quando a obra for recoletada."""
    d = _jsonb(obras)
    if not isinstance(d, dict):
        return False
    lotes = d.get("lotes") if isinstance(d.get("lotes"), list) else []
    if not lotes:
        return False
    if any(not isinstance((l or {}).get("arts"), list)
           for l in lotes if isinstance(l, dict)):
        return False
    return not any((l or {}).get("arts") for l in lotes if isinstance(l, dict))


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


def _iso_de_br(s) -> str | None:
    """'dd/mm/aaaa' -> 'aaaa-mm-dd'. A data de pagamento do FNS chega do coletor
    no formato brasileiro (o detalhe-pagamento devolve 'dataCriacaoSiafi' assim);
    o resto do RM guarda datas em ISO (dt_saldo, dt_fim_vigencia) e os
    formatadores (_fmt_dt/_fmt_data_curta) esperam ISO. Tolera valor ja-ISO e
    vazio sem quebrar."""
    s = str(s or "").strip()
    if not s:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else s


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


def _em_cadastramento(situacao) -> bool:
    """O convenio estadual esta em CADASTRAMENTO — o estagio do SIGCON em que a
    proposta ainda esta sendo registrada: sem analise, sem celebracao, sem
    dinheiro. NAO entra no RM, de nenhum ano, anual ou completo.

    ⭐ Decisao do dono (15/09/2026). O RM de Araujos imprimia "Seapa - SIGCON ·
    Convenio 002567/2026 · Valor global R$ 0,00 · Situacao atual: Cadastramento ·
    sem alteracoes registradas no SIGCON" — um cadastro vazio numa lista de
    instrumentos. A regra de ano (`_fed_retem`) so barrava pre-empenho de ANOS
    ANTERIORES; para ela Cadastramento e 'ativa', e do ano corrente ENTRA. E o
    comentario que dizia "convenio em Cadastramento nao tem numero nem vigencia
    -> segue fora" estava errado: o 002567/2026 tem numero, com "/", o que ainda
    o rotulava "Convenio".

    ⚠️ A PALAVRA INTEIRA, sem acento e sem caixa — e NAO a substring "cadastr".
    O backfill do CKAN insere convenio com a situacao VERBATIM do Estado,
    "CONVENIO CADASTRADO" (sigcon_ckan_backfill._situacao_por_convenio), que e
    instrumento CELEBRADO e com repasse; "cadastr" o derrubaria junto, calado.
    None/vazio devolve False: ausencia de situacao nao classifica.

    ⚠️ SO SOBRE A COLUNA CRUA `situacao`, nunca sobre a narrativa montada por
    `_situacao_estadual`: a ultima alteracao de um convenio VIGENTE pode ser
    "CADASTRAMENTO DA ALTERACAO" (termo aditivo em cadastro), e a regex casaria
    — derrubando um instrumento em vigor por causa do aditivo."""
    s = _sem_acento(str(situacao or "")).casefold()
    return re.search(r"\bcadastramento\b", s) is not None


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


def _data_fim(dt_fim) -> date | None:
    """Lê a data de fim de vigência. Aceita date/datetime/ISO/'dd/mm/aaaa'.
    Devolve None para vazio, lixo e formato desconhecido — a coluna do banco é
    `character varying`, então chega de tudo por ali."""
    if not dt_fim:
        return None
    if isinstance(dt_fim, datetime):
        return dt_fim.date()
    if isinstance(dt_fim, date):
        return dt_fim
    s = str(dt_fim).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _vigencia_vencida(dt_fim, hoje: date | None = None) -> bool:
    """A vigência já terminou?

    None ou ilegível devolve False — "não sei quando vence" NUNCA vira "venceu".
    O marcador que depende disto ACRESCENTA item ao relatório; supor vencimento
    encheria o documento de proposta que ninguém pode afirmar estar vencida."""
    d = _data_fim(dt_fim)
    return d is not None and d < (hoje or date.today())


def _vigencia_em_curso(dt_fim, hoje: date | None = None) -> bool:
    """A vigência foi LIDA e ainda não terminou.

    ⚠️ NÃO é `not _vigencia_vencida`, e a diferença tem teste. As duas devolvem
    False quando não há data legível, de propósito: as duas ACRESCENTAM item ao
    relatório, e o que não se sabe não vira afirmação em documento entregue ao
    cliente. A primeira versão daqui era `bool(dt_fim) and not vencida` e dava
    True para `'   '`, `'sem data'` e `'13/2024'` — texto não vazio que o parser
    não lê. Por isso a pergunta é feita à DATA LIDA, não ao campo bruto."""
    d = _data_fim(dt_fim)
    return d is not None and d >= (hoje or date.today())


def _fed_retem(ano_prop: int | None, ano_emissao: int, situacao: str | None,
               completo: bool = False, anos_sel: set | list | None = None,
               dt_fim=None, celebrado: bool = False,
               hoje: date | None = None) -> bool:
    """Regra de permanência no RM, por ANO DE REFERÊNCIA (ano_emissao):
      - empenhada/paga -> sempre permanece (avançou; convênio em curso em qualquer ano)
      - dead (rejeitada/indeferida/anulada) -> só permanece no SEU próprio ano de
        referência; NÃO carrega p/ os relatórios dos demais anos (as que não foram
        para frente naquele ano não entram nos outros)
      - ativa (pré-empenho) -> ver as DUAS regras abaixo

    completo=True (RM de TODOS os anos): a MESMA regra do anual, com uma diferença
    — 'dead' (rejeitada/anulada/indeferida) NUNCA entra (a referência não tem seção
    de rejeitados).

    ⚠️ `anos_sel` = a SELEÇÃO de anos do relatório (vazia/None = "todos os anos").
    HAVENDO SELEÇÃO, CADA ANO ESCOLHIDO VALE POR SI: quem marcou [2021, 2025] pediu
    os dois de propósito, e comparar contra o MAIOR ano da seleção (o `ano_emissao`,
    que o router calcula como `max(anos)`) derrubava justamente 2021 — o oposto do
    pedido. Este é o MESMO defeito já corrigido no `_fns_retem` em 19/08/2026; o
    conserto ficou só no FNS e o federal nunca o recebeu. Medido: com [2021, 2025],
    a proposta 932836/2021 sumia do relatório, calada.

    ⚠️ E EM "TODOS OS ANOS", pré-empenho ANTIGA só volta quando FOI PARA FRENTE:
    virou INSTRUMENTO (`celebrado`) e a VIGÊNCIA AINDA CORRE.

    ESTA REGRA JÁ ESTEVE INVERTIDA, e o erro foi meu. O #317 (29/08/2026) fez o
    contrário — "entra quando a vigência VENCEU" — para resgatar a 932836. Medido
    contra produção em 30/08/2026, com as linhas reais e esta mesma função:

        município      antiga   #317 (vencida)   celebrada+viva
        Araújos          18       59 (+41)         19 (+1)
        3 municípios     79      190 (+111)        80 (+1)

    Os +41/+111 são exatamente a reclamação do dono: proposta SEM instrumento,
    "enviada para análise" desde 2009/2015/2017, com a janela fechada há anos —
    "convênios/propostas que não foram para frente". E a 932836 NÃO estava entre
    eles: a vigência dela é 31/12/2026, ou seja, ela nunca venceu, e a regra
    escrita para resgatá-la não a resgatava. Os dois lados errados.

    O que a 932836 tem e as outras não é ter VIRADO INSTRUMENTO (nº 932836,
    proposta 059522/2021, vigência até 31/12/2026) e seguir viva. Isso é o mesmo
    "instrumento ativo -> permanece em qualquer ano" que `_fed_status` já
    reconhece pelas palavras "em vigor"/"assinado"; aqui ele é provado pelo
    NÚMERO e pela DATA, porque o portal manteve a situação textual em
    "Proposta/Plano de Trabalho Aprovados" mesmo depois de celebrar.

    ⚠️ E FICA DENTRO DO "TODOS OS ANOS", DEPOIS DO `anos_sel` — não junto do
    `vigente` lá em cima. Testada nas linhas de produção, a versão "junto do
    vigente" puxava instrumentos de 2026 (994997, 7AABMT, 7AABSA, 7AAFZT) para
    dentro de um relatório pedido só para 2025. Quem escolhe anos recebe os anos
    que escolheu.

    `hoje` existe só para o teste poder FIXAR a data. A vigência da 932836 é
    31/12/2026: um teste preso a `date.today()` passaria agora e quebraria
    sozinho em janeiro — o caso do dono deixaria de estar coberto exatamente
    quando ninguém estivesse olhando.
    """
    st = _fed_status(situacao)
    if st in ("empenhada", "paga", "vigente"):
        return True
    if st == "dead":
        # anual: só no próprio ano; completo: nunca.
        return False if completo else (ano_prop is not None and ano_prop == ano_emissao)
    # ativa (pré-empenho).
    if anos_sel:
        return ano_prop is not None and ano_prop in anos_sel
    if ano_prop is not None and ano_prop >= ano_emissao:
        return True
    return celebrado and _vigencia_em_curso(dt_fim, hoje)


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


def _mg_pagamentos(linhas) -> dict:
    """Funde os pagamentos dos VARIOS empenhos de um mesmo convenio estadual num
    unico bloco no formato `ops_obs` — o mesmo que `_desembolso_ops_obs` ja le.

    `linhas` = [pagamentos_jsonb, ...] de `transparencia_mg_empenhos` daquele
    convenio. Um convenio de MG costuma ter mais de um empenho (um por exercicio,
    por exemplo), e cada um traz suas proprias ordens de pagamento.

    ⚠️ SO O BLOCO `pagamentos` PROVA QUE HOUVE MEDICAO — nunca `detalhe_lido_em`.
    Esta funcao ja aceitou a coluna `detalhe_lido_em IS NOT NULL` como prova, e
    era um defeito GRAVE e PERMANENTE: o coletor carimba aquela coluna tambem
    quando a aba de Pagamento devolveu corpo vazio (o portal faz isso com cookie
    velho — "nao erro, nao 403: vazio"), deixando `pagamentos` NULO. Uma leitura
    que FALHOU virava "Pendente de desembolso" num convenio que podia ter
    recebido tudo — e o texto CONGELA em `rm_relatorios.conteudo`.
    NULO = NAO CONSULTADO. E a doutrina do `add_transparencia_mg_empenhos.sql` e
    das Notas de Empenho, e agora a coluna nem chega mais ate aqui.

    ⚠️ E `valor_desembolsado` conta SO O QUE A SITUACAO DA OP CONFIRMA. Somar
    toda linha da aba fazia uma OP "Devolvida pelo banco" virar dinheiro
    recebido — e, pior, APAGAR o "Pendente de desembolso", tirando da lista de
    cobranca justamente o convenio que nao recebeu.

    Devolve {} quando nao ha nada a dizer."""
    total = 0.0
    obs: list = []
    consultado = False
    incerto = False
    ops = 0
    ultima = ""
    for pagamentos in (linhas or []):
        d = _jsonb(pagamentos)
        if not isinstance(d, dict):
            continue
        # O bloco existe => o detalhe foi lido E a aba de Pagamento respondeu.
        consultado = True
        total += _num0(d.get("valor_desembolsado"))
        ops += int(_num0(d.get("qtd_ops")) or len(d.get("obs") or []))
        # ⚠️ Bloco ANTIGO (gravado antes de a situacao passar a ser lida) nao tem
        # `tem_situacao_desconhecida`. Reclassifica pelas proprias `obs`, senao
        # uma linha velha passaria por "tudo confirmado" — que e a afirmacao que
        # este conserto existe para impedir.
        if "tem_situacao_desconhecida" in d:
            incerto = incerto or bool(d.get("tem_situacao_desconhecida"))
        else:
            incerto = incerto or any(
                _pgto_confirmado(ob.get("situacao")) is None
                for ob in (d.get("obs") or []) if isinstance(ob, dict))
        for ob in (d.get("obs") or []):
            if isinstance(ob, dict):
                obs.append(ob)
        dt = (d.get("data_ultimo_desembolso") or "").strip()
        # Datas em dd/mm/aaaa: comparar como string daria 08/08 > 25/03. A chave
        # de ordem e (ano, mes, dia).
        if dt and _chave_data_br(dt) > _chave_data_br(ultima):
            ultima = dt
    if not consultado:
        return {}
    return {
        "valor_desembolsado": round(total, 2),
        "data_ultimo_desembolso": ultima or None,
        "obs": obs,
        "_consultado": True,
        # ⚠️ O TERCEIRO ESTADO. Ha OP cuja situacao este codigo nao sabe ler:
        # nao da para afirmar "pendente" (o dinheiro pode ter saido) nem
        # "desembolsado" (pode nao ter). O RM CALA — ver o call site.
        "_incerto": incerto and total == 0,
        "_qtd_ops": ops,
    }


def _num0(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _pgto_confirmado(situacao):
    """A situacao da OP diz que o dinheiro saiu? True/False/None (nao sei).

    ⚠️ IMPORTADA do coletor, e nao recopiada aqui. O vocabulario e da FONTE, e
    este repo ja mostrou o que acontece quando a mesma regra vive em dois
    arquivos: as duas copias divergem e ninguem percebe. Import LOCAL para o
    service nao carregar o modulo de ingestao no boot da API."""
    from ingestion.transparencia_mg import pagamento_confirmado
    return pagamento_confirmado(situacao)


def _chave_data_br(v) -> str:
    """'25/03/2026' -> '20260325', para ORDENAR datas brasileiras. String vazia
    para o que nao casa — assim ela perde de qualquer data real."""
    import re as _re
    m = _re.search(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return (m.group(3) + m.group(2) + m.group(1)) if m else ""


def _so_digitos(v) -> str:
    """So os digitos de um numero de processo, para JUNTAR dois lados que
    escrevem a mesma coisa com pontuacao propria ('23400.002301/2021-01' no
    SIMEC; o dado aberto do TransfereGov traz a dele). Vazio para None."""
    return re.sub(r"\D", "", str(v or ""))


def _segov_resumo(linhas) -> dict:
    """Funde os empenhos do Estado (CSV da SEGOV, `segov_convenios_empenhos`)
    de UM convenio estadual num bloco que o item do RM consome.

    `linhas` = [(numero_empenho, dt_empenho, vr_empenhado, vr_liquidado, vr_pago,
                 tipo, ano_arquivo, uo_sigla), ...]

    Devolve {} quando nao ha linha — e {} e "NAO CONSULTADO", nunca "nao houve
    empenho": o CSV e do Estado inteiro e a linha so entra quando casou por SIAFI.

    ⚠️ SO O QUANTO. O CSV nao tem data de pagamento nem OB, entao este bloco NAO
    fabrica `desembolsos` (lancamentos com data): `valor_pago` vira numero e a
    caixa do PDF imprime so "Desembolsado: R$ X". A data que existe — a do
    REGISTRO DO EMPENHO — vai na linha das NEs, com o rotulo certo.

    ⚠️ UMA NE E UMA LINHA, e o ano e o DA NOTA. A mesma NE aparece em DOIS
    arquivos da SEGOV — pagamento{ano} no exercicio em que foi empenhada e
    pagamentorp{ano+1} quando o pago vira restos a pagar (medido em 15/09/2026:
    99 das 160 linhas do rp2026 sao NEs de 2025 que tambem estao no pg2025).
    Uma linha por arquivo rotulava a NE 634/2025 como "NE 634/2025 ... pago
    R$ 0,00; NE 634/2026 (restos a pagar) ... pago R$ 99.932,16" — duas notas
    de dois anos onde ha uma. Aqui as linhas de uma mesma (numero, UO, ano da
    nota) se FUNDEM, o ano sai de `dt_empenho` (o do arquivo so na falta), e o
    exercicio do RP fica entre parenteses ao lado do pago. As SOMAS nao mudam.

    `valor_empenhado` fica None quando NENHUMA linha trouxe empenhado (so restos
    a pagar, que nao tem a coluna): None e "nao medido" e o PDF omite a linha,
    em vez de imprimir R$ 0,00 sobre um RP que e empenho por definicao."""
    emp = liq = pago = 0.0
    tem_emp = False
    notas: dict = {}   # (numero, uo, ano da nota) -> acumulador, na ordem de chegada
    n = 0
    for l in (linhas or []):
        try:
            numero, dt, vr_e, vr_l, vr_p, tipo, ano, uo = (list(l) + [None] * 8)[:8]
        except TypeError:
            continue
        n += 1
        if vr_e is not None:
            emp += _num0(vr_e)
            tem_emp = True
        liq += _num0(vr_l)
        pago += _num0(vr_p)
        ano_nota = dt.year if hasattr(dt, "year") else ano
        k = (str(numero or "").strip(), str(uo or "").strip(), ano_nota)
        a = notas.setdefault(k, {"emp": None, "pago": None, "dt": None, "rp": []})
        if vr_e is not None:
            a["emp"] = _num0(a["emp"]) + _num0(vr_e)
        if vr_p is not None:
            a["pago"] = _num0(a["pago"]) + _num0(vr_p)
        if a["dt"] is None and dt:
            a["dt"] = dt
        if tipo == "rp":
            a["rp"].append((ano, _num0(vr_p)))
    if not n:
        return {}
    nes: list[str] = []
    for (numero, _uo, ano_nota), a in notas.items():
        partes = [f"NE {numero}/{ano_nota}" if ano_nota else f"NE {numero}"]
        if a["emp"] is not None:
            partes.append(_moeda_br(a["emp"]))
        dt = a["dt"]
        dts = dt.strftime("%d/%m/%Y") if hasattr(dt, "strftime") else str(dt or "").strip()
        if dts:
            partes.append(f"empenhado em {dts}")
        if a["pago"] is not None:
            txt = f"pago {_moeda_br(a['pago'])}"
            rp = [(ano_rp, v) for ano_rp, v in a["rp"] if v]
            if rp:
                txt += " (" + ", ".join(f"{_moeda_br(v)} em restos a pagar {ano_rp}"
                                        for ano_rp, v in rp) + ")"
            partes.append(txt)
        nes.append(" — ".join(partes))
    return {
        "valor_empenhado": round(emp, 2) if tem_emp else None,
        "valor_liquidado": round(liq, 2),
        "valor_pago": round(pago, 2),
        "nes": "; ".join(nes),
        "_qtd": n,
    }


def _segov_campos(sg: dict, mg_consultado: bool) -> dict:
    """Chaves do item estadual vindas da SEGOV. Vazio sem dado.

    `valor_desembolsado` SO quando o Joomla (Transparencia MG) NAO respondeu: la
    ha data/OB/situacao por ordem e a caixa de desembolso ja e desenhada por
    eles; sobrescrever o total pelo CSV misturaria duas medicoes no mesmo item.
    `valor_empenhado`/`nes`/`empenhado` vem sempre daqui — o Joomla nao os grava
    no convenio.

    `empenhado` so afirma "Sim": a ausencia de linha no CSV nao prova "Nao"
    (mesma disciplina de rm_pdf, que OMITE a linha em vez de negar)."""
    if not sg:
        return {}
    out: dict = {}
    if sg.get("nes"):
        out["nes"] = sg["nes"]
    if sg.get("valor_empenhado") is not None:
        out["valor_empenhado"] = sg["valor_empenhado"]
        if sg["valor_empenhado"] > 0:
            out["empenhado"] = "Sim"
    else:
        out["valor_empenhado"] = None
    if not mg_consultado:
        out["valor_desembolsado"] = sg.get("valor_pago")
    return out


def _simec_termos_mapa(linhas) -> dict:
    """{digitos do processo: termo} a partir das linhas de `simec_termos`
    (processo, nr_documento, tipo_documento, tipo_objeto, dt_vigencia, valor_termo,
     valor_empenhado, valor_pago, saldo_bancario, prestacao_contas).

    Termo sem processo nao entra (nao ha como casa-lo). Processo REPETIDO (o
    portal lista o mesmo TC de novo no bloco de aditivos) fica com a linha de
    MAIOR pago — a leitura mais recente do mesmo instrumento."""
    out: dict = {}
    for l in (linhas or []):
        try:
            (processo, nr_doc, tipo_doc, tipo_obj, dt_vig, v_termo,
             v_emp, v_pago, saldo, pc) = (list(l) + [None] * 10)[:10]
        except TypeError:
            continue
        k = _so_digitos(processo)
        if not k:
            continue
        tc = {
            "processo": str(processo or "").strip(),
            "nr_documento": str(nr_doc or "").strip(),
            "tipo_documento": tipo_doc or "",
            "tipo_objeto": tipo_obj or "",
            "dt_vigencia": dt_vig,
            "valor_termo": v_termo,
            "valor_empenhado": v_emp,
            "valor_pago": v_pago,
            "saldo_bancario": saldo,
            "prestacao_contas": str(pc or "").strip(),
        }
        if k not in out or _num0(v_pago) > _num0(out[k].get("valor_pago")):
            out[k] = tc
    return out


def _simec_na_linha(tc, vd_siconv) -> dict:
    """O pago do SIMEC/PAR na PROPRIA linha da voluntaria (a creche 932836/2021).

    Pedido do dono (15/09/2026): "da creche ainda falta o valor que ja foi pago,
    esta no SIMEC" — e ele quer ve-lo na linha da creche, nao so no item
    separado do Termo de Compromisso. A creche vem do SICONV com Desembolsado
    R$ 0,00 porque o FNDE paga o PAR pelo SIMEC, nao por OB do SICONV.

    A JUNCAO E PELO Nº DO PROCESSO (SEI), digitos apenas: o TransfereGov guarda
    `numero_processo` (do dado aberto diario, NR_PROCESSO — "numero interno do
    processo", pelo dicionario do SICONV) e o SIMEC guarda `processo`. No SIMEC
    a creche e 23400.002301/2021-01 (medido: simec_termos id 6); que o SICONV
    grave o MESMO numero na 059522/2021 e HIPOTESE ate a primeira conferencia
    em producao — o repo nao tem esse valor. Sem processo igual NAO se junta:
    casar por municipio+objeto e hipotese pior, e "juntar por hipotese vincula
    pagamento ao convenio errado, que e pior do que nao vincular"
    (add_transparencia_mg_empenhos.sql). O builder LOGA quando ha termo com
    processo e nenhuma voluntaria casou — o falso negativo nao pode ser mudo.

    Devolve {} sem termo. Com termo:
      - `simec_pagamento`: a frase (empenhado NO SIMEC/pago/saldo + TC + processo)
        — "no SIMEC" no rotulo porque a mesma linha ja imprime o "Valor
        empenhado" das NEs do SICONV, e os dois numeros DIFEREM (R$ 819 mil x
        R$ 1,87 mi na creche): sem a origem, o leitor ve contradicao;
      - `valor_desembolsado`: o pago do SIMEC, SO quando o SICONV nao mediu
        desembolso (None ou 0) e o SIMEC tem pago > 0. Onde a OB do SICONV
        existe, ela e a medicao e fica. E, no mesmo gesto, `valor_a_desembolsar`
        vira None — ver o comentario no corpo."""
    if not tc:
        return {}
    pago = _money(tc.get("valor_pago"))
    emp = _money(tc.get("valor_empenhado"))
    saldo = _money(tc.get("saldo_bancario"))
    partes = []
    if emp is not None:
        partes.append(f"empenhado no SIMEC {_moeda_br(emp)}")
    if pago is not None:
        partes.append(f"pago {_moeda_br(pago)}")
    if saldo is not None:
        partes.append(f"saldo bancário {_moeda_br(saldo)}")
    ref = []
    if tc.get("nr_documento"):
        ref.append(f"TC {tc['nr_documento']}")
    if tc.get("processo"):
        ref.append(f"processo {tc['processo']}")
    frase = " · ".join(partes)
    if ref:
        frase = (frase + " — " if frase else "") + ", ".join(ref)
    if tc.get("prestacao_contas"):
        frase += f" · prestação de contas: {tc['prestacao_contas']}"
    out = {"simec_pagamento": frase}
    if (pago or 0) > 0 and not (vd_siconv or 0):
        out["valor_desembolsado"] = pago
        # ⚠️ E ZERA o "a desembolsar" do SICONV no mesmo gesto. Sem isto a caixa
        # do PDF imprimia "Desembolsado: R$ 572.978,05 · A desembolsar:
        # R$ 3.819.853,65" — o pago do SIMEC ao lado do saldo do SICONV, somando
        # mais que o valor global do instrumento, num documento que CONGELA em
        # rm_relatorios.conteudo. Duas medicoes nao dividem a mesma caixa (a
        # mesma regra de _segov_campos no estadual). Nao se recalcula a partir
        # do valor do termo: seria uma terceira fonte na mesma linha.
        out["valor_a_desembolsar"] = None
    return out


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


def _projeto_basico_resumo(projeto_basico, situacao_csv=None) -> str:
    """"Termo de Referência — Em Análise": QUAL documento sustenta a clausula
    suspensiva e em que PE ele esta no portal. String vazia quando nao ha captura
    — o relatorio so imprime a linha quando ha o que dizer.

    ⚠️ `situacao_csv` E O PLANO B, e na pratica ele e quem responde. O JSONB rico
    vem da tela LOGADA e exige o SP `execucao` quente; a auditoria mediu esse SP
    frio 519 vezes, com a sessao morta 298 de 720 horas em 30 dias. O CSV publico
    traz so a situacao ("Em Analise"), sem o rotulo do documento — mas responder
    "Em Analise" e melhor que a linha sumir, que e o que o dono relatou em
    03/09/2026 sobre o convenio 981397/2025.

    A precedencia e a rica primeiro: quando as duas existem, o rotulo do
    documento ("Termo de Referência — Em Análise") vale mais que a situacao seca.
    """
    d = _jsonb(projeto_basico)
    if not isinstance(d, dict):
        return (situacao_csv or "").strip()
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
    return sit or rotulo or (situacao_csv or "").strip()


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

    `medicoes` continua OPCIONAL, mas agora tem de onde vir: o coletor passou a
    ler /contratos/{id}/medicoes e a contar as ATESTADAS por lote. Quando o
    parametro nao vier, a funcao SOMA o que estiver nos lotes; se nem isso
    existir (proposta coletada antes desta versao), a oracao some — em vez de
    inventar o numero ou travar a frase inteira.

    String vazia quando nao ha obra ou nao ha o que dizer."""
    d = _jsonb(obras)
    if not isinstance(d, dict):
        return ""
    lotes = d.get("lotes") if isinstance(d.get("lotes"), list) else []
    if medicoes is None:
        _soma = sum((l or {}).get("medicoes_atestadas") or 0
                    for l in lotes if isinstance(l, dict))
        medicoes = _soma or None
    # ⚠️ A MESMA condicao que decide a PARTE (`_obra_sem_art`), e nao uma copia:
    # o texto que o relatorio imprime e a classificacao que manda o item para a
    # Parte 2 tem de sair do mesmo lugar. Duas copias divergiriam calado — a
    # frase diria "falta ART" e o item continuaria listado como pendencia de
    # Brasilia, que e exatamente o defeito que o dono relatou.
    if _obra_sem_art(obras):
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


def _pac_da_voluntaria(detalhe) -> str:
    """Numero da proposta do Novo PAC que ORIGINOU esta voluntaria, ou "".

    O portal mostra "Número da Proposta Novo PAC - Seleção: 56000004633/2025" na
    aba Dados da Proposta, e o varredor generico de pares label:valor do coletor
    ja guarda isso no JSONB `detalhe` — mas NINGUEM lia. Sem esse elo, o mesmo
    recurso aparecia DUAS vezes no RM: uma como voluntaria, outra como item do
    Novo PAC.

    ⚠️ BUSCA TOLERANTE, e nao pela chave exata. O rotulo tem acento, hifen e
    espacos ("Número da Proposta Novo PAC - Seleção") e passa por _clean antes de
    virar chave; casar a string inteira e apostar na grafia. Aqui basta a chave
    conter "novo pac", normalizada sem acento — o que sobrevive a variacao de
    pontuacao e de caixa."""
    d = _jsonb(detalhe)
    if not isinstance(d, dict):
        return ""
    import unicodedata as _ud

    def _norm(s):
        return "".join(c for c in _ud.normalize("NFD", str(s or ""))
                       if _ud.category(c) != "Mn").lower()

    for k, v in d.items():
        if str(k).startswith("_"):
            continue
        if "novo pac" in _norm(k):
            val = str(v or "").strip()
            if val:
                return val
    return ""


def _mesma_proposta(a, b) -> bool:
    """True quando dois numeros de proposta sao o MESMO, ignorando pontuacao.

    O numero aparece como "56000004633/2025" na tela da voluntaria e pode chegar
    com espaco ou formatacao diferente na tabela do PAC. Comparar cru deixaria
    passar duplicata por causa de um espaco."""
    def _so_digitos(x):
        return "".join(c for c in str(x or "") if c.isdigit())
    da, db = _so_digitos(a), _so_digitos(b)
    return bool(da) and da == db


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


def _tem_ne_real(notas) -> bool:
    """True quando ha pelo menos UMA nota de empenho de verdade em `notas_empenho`.

    ⚠️ MINUTA NAO E EMPENHO. A listagem do portal mistura o empenho com a MINUTA
    (sem numero, R$ 1,00, situacao "Minuta de Empenho"); o coletor ja marca a
    linha com `minuta_apenas` na leitura (ingestion/transferegov_http.py
    ::_le_notas_empenho) e aqui so se obedece a marca — mesma disciplina do
    _nes_resumo. Sem isto, proposta que so tem minuta apareceria EMPENHADA.

    O `numero` e conferido alem da marca de proposito (redundante hoje, porque o
    leitor ja poe minuta_apenas=True quando falta numero): defende de linha
    gravada por versao mais frouxa do coletor."""
    lst = _jsonb(notas)
    if not isinstance(lst, list):
        return False
    return any(isinstance(n, dict) and not n.get("minuta_apenas")
               and str(n.get("numero") or "").strip()
               for n in lst)


def _empenhado_rotulo(notas, situacao, agregado=None) -> str:
    """"Sim" ou "" (CALADO) para a linha "Empenhado" do RM da voluntaria.

    ORDEM DE PROVA, da mais forte para a mais fraca:
      1. NE REAL coletada (`notas_empenho`) -> "Sim". E o DOCUMENTO: numero de
         empenho emitido no SIAFI. Manda em tudo.
      2. status do ciclo empenhada/paga (Em execucao / Pago / Prestacao de
         Contas) -> "Sim". Nao se executa convenio sem empenho.
      3. nada disso -> "" (CALADO; rm_pdf omite a linha).

    ⚠️ POR QUE O "NAO" SUMIU, e por que nao pode voltar como default: a ausencia
    de NE NAO PROVA ausencia de empenho. Ate a correcao do upsert, o `[]`
    ("consultei e nao ha") virava NULL no banco e ficava identico a "nunca
    consultei"; e o tenant com TG_NES desligado nunca consulta. Escrever "Nao"
    seria afirmar o que nao foi medido — exatamente o que _nes_resumo se recusa
    a fazer. Ate aqui o ternario nunca calava: convenio assinado com NE emitida
    saia "Empenhado: Nao", porque _fed_status classifica "Em Vigor"/"Assinado"
    como 'vigente', nao 'empenhada'. Esse era o caso 994997 reportado pelo dono.

    ⚠️ O flag `detalhe->>'Empenhado'` do portal ficou DE FORA de proposito. Ele
    erra nos DOIS sentidos: o falso positivo esta documentado em _fed_status e
    em migrations/add_voluntarias_notas_empenho.sql (propostas so "Aprovadas"
    marcadas como empenhadas sem empenho real), e o falso negativo foi o 994997.
    Aceita-lo como prova de "Sim" trocaria um falso negativo por um falso
    POSITIVO em relatorio de dinheiro publico — e nao resolveria o 994997, que e
    justamente o caso em que o flag mente para menos. Quem responde e o
    DOCUMENTO (regra 1) ou o CICLO (regra 2).

    Para poder dizer "Nao" com verdade faltaria um carimbo proprio
    (notas_empenho_atualizado_em, no molde de ops_obs_atualizado_em)."""
    if _tem_ne_real(notas):
        return "Sim"
    # ⚠️ REGRA 1.5 (31/08/2026): VL_EMPENHADO_CONV > 0, o agregado MONETARIO que
    # o dado aberto publica. Entra ACIMA do ciclo porque e medicao do portal, e
    # nao inferencia de status — mas ABAIXO da NE, que traz o documento.
    #
    # NAO confundir com o flag `detalhe->>'Empenhado'` do paragrafo anterior:
    # aquele e um sim/nao que erra nos dois sentidos; este e um VALOR, e valor
    # maior que zero so existe se houve empenho. Zero continua calando — pode ser
    # convenio sem empenho ou coluna nunca coletada, e os dois chegam iguais.
    if (_money(agregado) or 0) > 0:
        return "Sim"
    if _fed_empenhada(situacao):
        return "Sim"
    return ""


def _empenho_valor(notas) -> float | None:
    """VALOR EMPENHADO medido, somando SO as notas de empenho REAIS.

    None = a listagem de NEs NUNCA FOI CONSULTADA (coluna `notas_empenho` nula).
    0.0  = foi consultada e nao ha empenho nenhum.

    A diferenca entre os dois e o inteiro sentido desta funcao: `None` e `0`
    chegam iguais em qualquer `or`/`if not`, e e exatamente essa confusao que
    faria o relatorio escrever "pendente de empenho" em proposta que ninguem
    mediu — o oposto da promessa de _nes_resumo.

    ⚠️ IGNORA A MINUTA pela marca que o coletor ja poe na leitura."""
    lst = _jsonb(notas)
    if not isinstance(lst, list):
        return None
    total = 0.0
    for n in lst:
        if not isinstance(n, dict) or n.get("minuta_apenas"):
            continue
        total += _money(n.get("valor")) or 0.0
    return total


def _empenho_total(notas, agregado) -> float | None:
    """VALOR EMPENHADO com as DUAS fontes, na ordem de quem mediu melhor.

    1. A listagem de NEs (`notas_empenho`) e o DOCUMENTO — nota a nota, da aba
       logada. Manda sempre que existe, inclusive quando some zero: ali `0.0`
       quer dizer "consultei e nao ha", que e informacao.
    2. `valor_empenhado` (VL_EMPENHADO_CONV, do dado aberto) entra SO quando a
       listagem nunca foi consultada.

    ⚠️ POR QUE ISTO EXISTE: medido em 31/08/2026 no tenant freitas, 2.741 das
    3.199 propostas tem `notas_empenho` NULA — a aba logada nunca foi lida
    naquele instrumento. Ate aqui o RM calava nas 2.741, mesmo com o portal
    publicando o agregado. O 932836 (creche de Araujos) e um deles: R$ 819.375,12
    empenhados no arquivo publico, e o relatorio nao dizia nada.

    ⚠️ E POR QUE O AGREGADO NAO PASSA NA FRENTE: ele e um numero so, sem nota,
    sem data e sem situacao. Quando ha listagem, ela responde melhor a mesma
    pergunta — e quando as duas discordam, a que tem documento por tras vale
    mais. Isto NAO e o flag `detalhe->>'Empenhado'`, que fica de fora por errar
    nos dois sentidos (ver `_empenhado_rotulo`); e o valor monetario que o
    proprio portal publica."""
    medido = _empenho_valor(notas)
    return medido if medido is not None else _money(agregado)


def _sem_empenho(notas) -> bool:
    """True SO quando a listagem de NEs FOI consultada e nao tem NENHUMA nota
    real (nenhuma linha, ou so minuta).

    NUNCA devolve True por ausencia de coleta. E a mesma promessa que
    `_nes_resumo` ja faz ("vazio nao significa 'nao ha empenho'"), so que ali ela
    servia para OMITIR uma linha e aqui precisa sustentar uma AFIRMACAO impressa
    no documento. Coluna nula — proposta nunca raspada, ou tenant com TG_NES
    desligado — devolve False, e o relatorio simplesmente nao diz nada.

    Conta NOTA, e nao valor: ha NE real cuja celula de valor vem vazia no portal
    (`valor` None). Decidir por `_empenho_valor() == 0` marcaria como pendente
    justamente a proposta que tem empenho emitido e valor nao lido."""
    lst = _jsonb(notas)
    if not isinstance(lst, list):
        return False
    return not any(isinstance(n, dict) and not n.get("minuta_apenas") for n in lst)


def _e_termo_compromisso(modalidade) -> bool:
    """True quando a MODALIDADE do instrumento e Termo de Compromisso.

    Duas fontes escrevem `transferegov_propostas.modalidade` e elas nao tem o
    mesmo formato. O dado aberto grava o rotulo limpo ("Termo de Compromisso");
    o scraper grava a celula crua da tela pelo varredor generico label|valor — o
    MESMO varredor que ja colou lixo com TAB nesta coluna ("Contrato de
    Repasse\tEnviada para mandataria?\tNao\t..."). Por isso corta no primeiro
    TAB/quebra antes de comparar, como `_programa_limpo` ja faz.

    `startswith` e nao `in`: "Termo de Execucao Descentralizada", "Termo de
    Fomento" e "Termo de Colaboracao" tambem comecam com "Termo de" e sao
    modalidades DIFERENTES — so o prefixo completo casa."""
    import re as _re
    import unicodedata as _ud
    s = _re.split(r"[\t\r\n]", str(modalidade or ""))[0]
    s = "".join(c for c in _ud.normalize("NFD", s) if _ud.category(c) != "Mn")
    return _re.sub(r"\s+", " ", s).strip().casefold().startswith("termo de compromisso")


def _situacao_com_marcas(situacao, pendente_empenho: bool,
                         pode_desembolsar: bool, valor_desembolsado) -> str:
    """A `situacao_atual` exibida: a situacao do ciclo mais os marcadores de
    ESTAGIO DO DINHEIRO, na ordem em que o dinheiro anda — EMPENHO antes de
    DESEMBOLSO (nao se desembolsa o que nao foi empenhado).

    ⚠️ `pode_desembolsar` chamava-se `licitacao_aceita` e nao e mais so isso: e
    "o processo CHEGOU no ponto em que o dinheiro deveria sair". Na voluntaria
    isso e a licitacao aceita; no estadual de MG e "ha empenho no portal e os
    pagamentos dele ja foram consultados". Os DOIS passam por aqui de proposito —
    o pedido era que o estadual entrasse "no mesmo status como o transferegov", e
    duplicar a composicao e o jeito conhecido, neste repo, de as duas divergirem.

    Funcao PURA e separada de proposito: este texto vai CONGELADO no JSONB do RM
    (rm_relatorios.conteudo), entao o teste precisa poder fixar a string exata
    sem tocar no banco.

    ⚠️ NAO-REGRESSAO: com `pendente_empenho=False` a saida e caractere a
    caractere a de antes. O marcador novo apenas ACRESCENTA."""
    sit = situacao or ""
    marcas: list[str] = []
    if pendente_empenho:
        marcas.append("Pendente de empenho")
    vd = valor_desembolsado or 0
    if pode_desembolsar and vd == 0:
        marcas.append("Pendente de desembolso")
    elif vd > 0:
        marcas.append(f"Desembolsado: {_fmt_brl(valor_desembolsado)}")
    if not marcas:
        return sit
    return " · ".join(([sit] if sit else []) + marcas)


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


def _situacao_estadual(situacao: str | None, raw: dict,
                       qt_alteracoes: int | None = None) -> str:
    """SITUACAO exibida do instrumento ESTADUAL (SIGCON).

    O campo `situacao` do SIGCON e generico ("Em vigor", "Encerrado", "Cancelado") e
    NAO diz em que pe o convenio esta — era por isso que o relatorio saia mostrando
    so "EM VIGOR" nos estaduais. A situacao REAL do momento esta na ULTIMA ALTERACAO
    (ex.: "ANALISE - CHECKLIST DE TERMO ADITIVO", "CADASTRAMENTO DA ALTERACAO",
    "VIGENTE"), capturada por _scrape_alteracoes (raw_data.ultima_alteracao_*).

    Junta as duas quando ha alteracao e ela ACRESCENTA informacao; senao devolve so
    a situacao base (degrada suave — a maioria dos convenios ainda nao foi revisitada
    pelo rodizio do scraper).

    Quando NAO ha detalhe de ultima alteracao capturado, `qt_alteracoes` (a coluna
    "Quantidade de Alteracoes Concluidas" da LISTAGEM/CKAN, capturada para TODOS)
    separa dois casos que confundir engana o leitor — a dúvida real "cadê o detalhe
    da situacao atual?":
      - qt_alteracoes == 0: o SIGCON nao registra alteracao. E DEFINITIVO; dizemos
        "sem alteracoes registradas" para nao restar duvida do porque de sair so
        "Em vigor".
      - qt_alteracoes > 0: o contador afirma alteracao(oes). Declaramos so o CONTADOR
        ("N alteracao(oes) registrada(s) no SIGCON") — NAO "detalhe em coleta". Medido
        na producao (Freitas, Desterro): dos 9 convenios com qt>0, 8 tinham alteracao
        real (capturada) e 1 abriu o accordion VAZIO. Ou seja, o contador (listagem)
        e o detalhe (tela autenticada) DIVERGEM: para varios pendentes nao ha o que
        raspar — prometer "em coleta" seria falso. Afirmar so o contador e sempre
        verdade, venha o detalhe depois ou nunca.
    Sem `qt_alteracoes` (chamador antigo/teste), degrada para a situacao base como
    antes."""
    base = (situacao or "").strip()
    if not isinstance(raw, dict):
        return base
    alt = (raw.get("ultima_alteracao_situacao") or "").strip()
    if not alt:
        if base and qt_alteracoes == 0:
            return f"{base} · sem alterações registradas no SIGCON"
        if base and isinstance(qt_alteracoes, int) and qt_alteracoes > 0:
            rotulo = ("alteração registrada" if qt_alteracoes == 1
                      else "alterações registradas")
            return f"{base} · {qt_alteracoes} {rotulo} no SIGCON"
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


_PC_CHAVES = ("prestacao_contas_status", "prestacao_contas_data",
              "prestacao_contas_status_data", "prestacao_contas_sei")


def _prestacao_contas_campos(raw: dict) -> dict:
    """PRESTACAO DE CONTAS do convenio estadual (secao propria do detalhe SIGCON),
    para a caixa do PDF (rm_pdf._prestacao_contas_destaque).

    ⚠️ E COISA DIFERENTE do rotulo "VENCIDO +90 DIAS - PRESTACAO DE CONTAS" que o
    relatorio ja mostra em `dias_restantes_label`. Aquele e o PRAZO, derivado da
    vigencia — ele so sabe que a data passou. Este e a ENTREGA, declarada pelo
    Estado. Um convenio pode ter os dois ao mesmo tempo, e e a diferenca entre eles
    que diz se ainda ha algo a cobrar do municipio.

    Aceita captura PARCIAL, como `_alteracao_campos`: exigir o status jogaria fora
    SEI e datas ja capturados."""
    if not isinstance(raw, dict) or not any((raw.get(k) or "").strip() for k in _PC_CHAVES):
        return {}
    return {k: (raw.get(k) or "").strip() for k in _PC_CHAVES}


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
                          completo: bool = False, anos: list[int] | None = None,
                          fontes: list[str] | None = None,
                          estagio: str | None = None) -> dict:
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
    unico relatorio; todos/vazio -> o completo.

    fontes: SELECAO de CONSULTAS do relatorio (services/rm_fontes.CHAVES). Cada
    string e, literalmente, o que a fonte carimba em `item["fonte"]` aqui neste
    arquivo. None/vazio = TODAS as consultas = o completo de hoje, sem nenhuma
    diferenca de conteudo. O recorte roda no PONTO UNICO `add_item`, entao ele
    cobre as NOVE insercoes (as duas do FNS inclusive) e preserva os efeitos
    colaterais dos lacos — ver a nota em `_pac_ja_exibidos`."""
    if not ano_emissao:
        ano_emissao = date.today().year
    anos_filtro = set(a for a in (anos or []) if a)  # vazio => sem filtro (todos)
    # Vazio => sem filtro (todas as consultas). `frozenset` porque este valor e
    # so lido, por item, ate o fim da montagem.
    fontes_filtro = frozenset(f for f in (fontes or []) if f)
    # RECORTE POR ESTAGIO: "" / None = TODAS (o completo). Ver `add_item`.
    # ⚠️ Valor desconhecido tambem vira "todas", e nao filtro vazio: um typo
    # no parametro devolveria um relatorio EM BRANCO, e um RM vazio se le
    # como "o municipio nao tem nada" — o pior erro que este documento pode
    # cometer. Melhor entregar o completo do que uma folha que mente.
    estagio_filtro = (estagio or "").strip().lower()
    if estagio_filtro not in ("pagas", "pendentes"):
        estagio_filtro = ""
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

    # Nome do MUNICIPIO do relatorio, para a padronizacao de maiusculas nao
    # rebaixar o unico nome proprio que o RM sabe qual e ("...NO MUNICIPIO DE
    # ARAUJOS/MG" -> "...no municipio de Araújos/MG", com o acento vindo da
    # tabela `municipios` — nao adivinhado).
    #
    # Declarado AQUI e preenchido logo abaixo, quando `mun` e lido. `add_item` e
    # closure e so resolve o nome na CHAMADA (a primeira e depois da leitura de
    # `mun`), mas um dicionario vazio ja nesta linha garante que uma reordenacao
    # futura do corpo da funcao nao vire NameError em producao.
    _proprios: dict[str, str] = {}

    def add_item(parte_n: int, secao: str, orgao: str, item: dict, ano: int | None = None,
                 pago: bool | None = None):
        """Adiciona o item na arvore. `ano` e o ano que a FONTE ja calculou (c.ano,
        ano_prop, ano_te, ano do pagamento...) — carimbado como `ano_item`.

        ⚠️ O recorte por anos (_no_escopo) NAO pode re-derivar o ano do TEXTO do
        numero: ha fontes cujo numero nao carrega ano (SIMEC usa a OB, PAC/emendas
        usam so o sequencial), e elas cairiam fora de qualquer RM filtrado por ano,
        em silencio. Quando a fonte nao sabe o ano, cai no ano do numero e, se ainda
        assim nao houver, o item PERMANECE (melhor um item a mais do que sumir).

        ⚠️ RECORTE POR CONSULTA — PONTO UNICO. Fica AQUI, e nao com um `continue`
        no topo de cada laco, por tres motivos medidos:
          1. sao NOVE insercoes e OITO fontes; o FNS entra por DUAS chamadas
             (propostas individuais e o bucket agregado de fallback), e um filtro
             por laco que pegasse so uma delas entregaria o RM pela metade, calado;
          2. `continue` no topo do laco muda os EFEITOS COLATERAIS dele — o mais
             perigoso e `_pac_ja_exibidos`, ver a nota la embaixo;
          3. fonte nova nasce filtravel de graca, do mesmo jeito que ja nasce
             padronizada pela normalizacao logo abaixo.
        Selecao vazia deixa tudo passar, entao o RM completo sai identico ao de
        hoje."""
        if not fonte_no_escopo(fontes_filtro, str(item.get("fonte") or "")):
            return False
        # ⭐ RECORTE POR ESTAGIO (pagas / pendentes / todas) — pedido do dono,
        # 26/08/2026. Fica AQUI pelos MESMOS tres motivos do recorte por consulta
        # logo acima: sao onze insercoes e oito fontes, um `continue` no topo de
        # cada laco mudaria os efeitos colaterais (`_pac_ja_exibidos`), e fonte
        # nova nasce filtravel de graca.
        #
        # ⚠️ `pago is None` PASSA SEMPRE. E a mesma disciplina do `ano_item` desta
        # funcao ("quando a fonte nao sabe o ano, o item PERMANECE"): a fonte que
        # ainda nao informa o estagio nao pode sumir de um recorte, calada. Some
        # so quem a fonte AFIRMOU ser o oposto do pedido.
        #
        # ⚠️ NAO da para inferir "pago" da PARTE. Federal pago no ano corrente vai
        # para a secao "REPASSES DE {ano}" da Parte 2, o que seria detectavel —
        # mas ESTADUAL pago no mesmo periodo cai na Parte 2 com o MESMO nome de
        # secao do nao pago (`_destino_completo`, ramo `status == "paga"`). Ler a
        # estrutura em vez do status classificaria estadual pago como pendente.
        # ⚠️ `pop`, e nao `get`: a marca é de TRANSPORTE — ela existe para viajar
        # do bloco da fonte até aqui e some antes de o item entrar no JSONB. Sem o
        # `pop`, `_pago` seria congelado em `rm_relatorios.conteudo`, apareceria
        # na tela de edição do RM e o usuário teria de olhar para um campo
        # interno que não sabe o que é.
        _pago = item.pop("_pago", pago)
        if estagio_filtro and _pago is not None:
            if estagio_filtro == "pagas" and not _pago:
                return False
            if estagio_filtro == "pendentes" and _pago:
                return False
        # PADRONIZACAO DE MAIUSCULAS — PONTO UNICO (services/texto_rm).
        #
        # Todas as fontes (SIGCON, FNS individuais, FNS fallback, voluntarias,
        # TE, SIMEC liberacoes, SIMEC termos, emendas estaduais, PAC) inserem
        # item por aqui, entao a regra vive num lugar so e fonte nova nasce
        # padronizada. Repetir a chamada em cada `add_item(...)` seria a receita
        # de esquecer a nona.
        #
        # ⚠️ RODA NO BUILDER, e nao no render do PDF, DE PROPOSITO: o resultado
        # CONGELA em rm_relatorios.conteudo e o usuario o revisa e corrige na
        # tela antes de emitir. No render, a correcao manual dele seria
        # reprocessada a cada download e ele nao teria como vencer a funcao.
        #
        # ⚠️ LISTA BRANCA de campos (texto_rm._CAMPOS_FRASE / _CAMPOS_NOME):
        # `numero`, `situacao_base`, `nes`, `agencia`, `conta`, `tipo` e os
        # valores NAO sao tocados. Ver o comentario la antes de acrescentar chave.
        #
        # `orgao` e a CHAVE do grupo: normalizar aqui tambem funde dois orgaos
        # que so diferiam na caixa — efeito desejado, e o unico lugar onde a
        # padronizacao muda a ESTRUTURA e nao so o texto.
        orgao = nome_proprio(orgao, _proprios)
        normalizar_item(item, _proprios)
        p = partes_data[parte_n]
        if secao not in p["secoes"]:
            p["secoes"][secao] = {}
        if orgao not in p["secoes"][secao]:
            p["secoes"][secao][orgao] = []
        if ano and not item.get("ano_item"):
            item["ano_item"] = int(ano)
        p["secoes"][secao][orgao].append(item)
        # Devolve se o item ENTROU. E o que permite marcar "ja exibido" so do
        # que saiu de fato: um conjunto `_*_ja_exibidos` alimentado ANTES do
        # recorte por estagio suprimia o item irmao (o termo do SIMEC) de um RM
        # "pagas" em que a voluntaria nem tinha entrado — o pago sumia dos dois.
        return True

    mun = (await db.execute(
        select(Municipio).where(Municipio.id == municipio_id)
    )).scalar_one_or_none()

    # Preenche o dicionario declarado antes de `add_item`: as palavras do nome do
    # municipio, com a grafia CANONICA da tabela `municipios`. E dai que sai a
    # unica restauracao de acento que o modulo faz sem adivinhar — "ARAUJOS"
    # volta "Araújos" acentuado porque o banco tem a grafia, nao porque alguem
    # supos. `mun` None devolve {} e a padronizacao segue sem esse nome.
    _proprios = proprios_do_municipio(mun)

    # === Convenios estaduais E FNS (mesma tabela, diferenciados por c.fonte) ===
    # SIGCON-MG => estadual => PARTE 2 / INSTRUMENTOS ESTADUAIS
    # FNS (Min Saude) => federal => PARTE 1 / INSTRUMENTOS FEDERAIS
    # PAGAMENTOS DO ESTADO (Portal da Transparencia de MG), por convenio.
    #
    # Pedido do dono (26/08/2026): "pegue tb a informacao do pagamento data e
    # situacao da ordem de pagamento, aquele que nao tiver empenho, exibir no
    # relatorio como 'pendente de desembolso', entrando no mesmo status como o
    # transferegov".
    #
    # ⚠️ LEITURA ADOTADA: o marcador sai quando HA EMPENHO no portal e NENHUM
    # pagamento saiu dele. E a unica leitura em que "pendente de DESEMBOLSO"
    # significa alguma coisa — sem empenho o que falta e o EMPENHO, e para isso o
    # relatorio ja tem marcador proprio. E e a mesma regra da voluntaria: o
    # processo chegou no ponto em que o dinheiro deveria sair e ele nao saiu.
    #
    # Uma consulta so para o municipio inteiro (nao uma por convenio): o laco
    # abaixo roda por convenio e um SELECT la dentro seria N+1 numa tela que ja e
    # a mais pesada do sistema.
    # ⚠️ `pagamentos IS NOT NULL` no WHERE, e `detalhe_lido_em` NAO entra aqui.
    # A coluna `detalhe_lido_em` e carimbada mesmo quando a aba de Pagamento
    # devolveu corpo vazio — usa-la como prova de medicao transformava uma
    # leitura FALHA em "Pendente de desembolso" permanente. So o bloco prova.
    _mg: dict = {}
    for _cid, _pg in (await db.execute(text("""
        SELECT convenio_id, pagamentos
          FROM transparencia_mg_empenhos
         WHERE municipio_id = :mid AND convenio_id IS NOT NULL
           AND pagamentos IS NOT NULL
    """), {"mid": municipio_id})).all():
        _mg.setdefault(_cid, []).append(_pg)
    # EMPENHOS DO ESTADO pelo DADO ABERTO da SEGOV (segov_convenios_empenhos):
    # o QUANTO empenhado/liquidado/pago por NE, chaveado por SIAFI. E o plano B
    # do Joomla acima, que da 403 na VPS — em producao e o que efetivamente
    # responde. Uma consulta por municipio, pela mesma razao do `_mg`.
    # Best-effort: tenant cujo boot ainda nao rodou a migration segue sem.
    _segov: dict = {}
    try:
        for _r in (await db.execute(text("""
            SELECT convenio_id, numero_empenho, dt_empenho, vr_empenhado,
                   vr_liquidado, vr_pago, tipo, ano_arquivo, uo_sigla
              FROM segov_convenios_empenhos
             WHERE municipio_id = :mid AND convenio_id IS NOT NULL
             ORDER BY ano_arquivo, tipo, numero_empenho
        """), {"mid": municipio_id})).all():
            _segov.setdefault(_r[0], []).append(tuple(_r[1:]))
    except Exception as ex:
        logger.warning(f"RM: segov_convenios_empenhos indisponivel p/ {municipio_id}: {str(ex)[:120]}")

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
            # ⚠️ SEM `str.title()`. Ele e a versao errada exatamente do que esta
            # sendo consertado: quebra sigla ("SNEAELIS" -> "Sneaelis", "FNS" ->
            # "Fns") e sobe particula ("CUSTEIO DE OBRAS" -> "Custeio De Obras").
            # Pior: ele deixa o texto em caixa MISTA, e a padronizacao de
            # `add_item` so age em texto TODO alto ou TODO baixo — mantido aqui,
            # o `.title()` blindaria o proprio defeito contra a correcao, calado.
            # A padronizacao e feita JA NESTA LINHA (e nao so em add_item) porque
            # `objeto_fns` tambem vira o `numero` no ramo de fallback abaixo, e
            # `numero` nunca e reescrito.
            objeto_fns = frase(tipo, _proprios) if tipo else (c.objeto or "").strip()
            recurso_label = nome_proprio(recurso, _proprios) if recurso else ""
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
                        # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
                        # poder existir. `add_item` consome e REMOVE a chave — ela nunca
                        # chega ao JSONB do relatório.
                        "_pago": st == "paga",
                        "tipo": "Proposta",
                        "numero": f"{nuprop} - {c.ano}" if c.ano else nuprop,
                        "objeto": objeto_fns,
                        "parlamentar": resp,
                        "valor_global": vlprop or vlpago,
                        "valor_repasse": vlpago,
                        "valor_contrapartida": 0,
                        # Domicilio bancario da OB (banco/agencia/CONTA) e DATA do
                        # pagamento, coletados por proposta do detalhe-pagamento do
                        # FNS (run_fns_local._detalhe_pagamento). O `conta` ja e
                        # renderizado hoje (so vinha vazio no FNS); `dt_pagamento` e
                        # o campo novo. Vazio/None quando a proposta ainda nao foi
                        # paga ou nao foi re-coletada — nao vira "sem conta".
                        "banco": (ind.get("codigo_banco") or ""),
                        "agencia": (ind.get("codigo_agencia") or ""),
                        "conta": (ind.get("conta_corrente") or ""),
                        "saldo_bancario": None, "dt_saldo": None,
                        "dt_pagamento": _iso_de_br(ind.get("data_pagamento")),
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
                    # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
                    # poder existir. `add_item` consome e REMOVE a chave — ela nunca
                    # chega ao JSONB do relatório.
                    "_pago": st == "paga",
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
        # ⭐ CADASTRAMENTO NAO ENTRA — em nenhum relatorio, de nenhum ano (dono,
        # 15/09/2026). E o estagio em que a proposta ainda esta sendo registrada
        # no SIGCON: sem instrumento de verdade, sem valor, sem alteracao. A
        # regra de ano logo abaixo so barrava pre-empenho de anos ANTERIORES; o
        # cadastramento do ano corrente (002567/2026, R$ 0,00) passava e saia
        # impresso como "Convenio". ANTES do `_fed_retem` de proposito: e um
        # corte de ESTAGIO, nao de ano. Ver _em_cadastramento.
        if _em_cadastramento(c.situacao):
            continue
        # Mesma regra de ANO do federal: as que NAO foram para frente
        # (analise celebracao / cancelada) de anos anteriores NAO entram no
        # relatorio do ano de referencia; avancadas (em execucao / em vigor /
        # empenhada) e concluidas (encerrada / prestacao) permanecem.
        ano_est = c.ano or _ano_de(nr_instr, nr_proposta, c.nr_sigcon)
        # `celebrado` + `dt_fim` vem ANTES do filtro: em "todos os anos", o que
        # resgata pre-empenho antiga e ter VIRADO INSTRUMENTO e a vigencia ainda
        # correr. `nr_instr` e o mesmo numero que decide `tipo_label` logo abaixo
        # ("Convenio" x "Proposta") — quem la ja e Proposta, aqui ja e barrado.
        # ⚠️ "Convenio em Cadastramento nao tem numero nem vigencia -> segue fora"
        # ERA FALSO (o 002567/2026 tem numero com "/"): e o corte explicito acima,
        # e nao esta regra, que o barra.
        if not _fed_retem(ano_est, ano_emissao, c.situacao, completo,
                          anos_sel=anos_filtro, celebrado=bool(nr_instr),
                          dt_fim=(c.dt_vigencia_atual or c.dt_vigencia_final)):
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
        # Pagamentos do Estado para ESTE convenio (varios empenhos -> um bloco).
        _mg_pg = _mg_pagamentos(_mg.get(c.id))
        # Passa pelo MESMO leitor da voluntaria: e ele que vira os campos que a
        # caixa de desembolso do PDF/Word ja sabe desenhar (data, nº da OB e a
        # SITUACAO da ordem de pagamento — a parte "data e situacao da ordem de
        # pagamento" do pedido). `{}` quando nao ha nada consultado, e ai a caixa
        # nao aparece.
        _mg_des = _desembolso_ops_obs(_mg_pg) if _mg_pg else {}
        # SEGOV (dado aberto) para ESTE convenio. ESTAGIO DO DINHEIRO: o Joomla
        # (OB a OB) quando respondeu; senao a SEGOV (o total por NE), em que
        # "pode desembolsar" = ha empenho no CSV. Sem nenhum dos dois, cala.
        _sg = _segov_resumo(_segov.get(c.id))
        if _mg_pg.get("_consultado"):
            _pode_est = not _mg_pg.get("_incerto")
            _vd_est = _mg_pg.get("valor_desembolsado")
        elif _sg:
            _pode_est = (_sg.get("valor_empenhado") or 0) > 0
            _vd_est = _sg.get("valor_pago")
        else:
            _pode_est, _vd_est = False, None
        add_item(parte, secao, orgao, {
            # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
            # poder existir. `add_item` consome e REMOVE a chave — ela nunca
            # chega ao JSONB do relatório.
            "_pago": st == "paga",
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
            # SITUACAO + o ESTAGIO DO DINHEIRO medido no Portal da Transparencia
            # de MG. `_situacao_com_marcas` e a MESMA funcao da voluntaria: era
            # isso o "entrando no mesmo status como o transferegov".
            # `pendente_empenho=False` aqui — este coletor mede PAGAMENTO, e
            # afirmar "pendente de empenho" a partir da AUSENCIA de linha no
            # portal confundiria "o Estado nao empenhou" com "o rodizio ainda nao
            # passou neste municipio".
            # ⚠️ `_incerto` DESLIGA o marcador. Ha OP na aba de Pagamento cuja
            # situacao este codigo nao sabe ler: dizer "Pendente de desembolso"
            # pode ser falso (o dinheiro talvez tenha saido) e dizer
            # "Desembolsado" tambem. Entao o relatorio nao afirma nenhum dos
            # dois — a caixa abaixo mostra as OPs com a situacao literal, e quem
            # le decide. Calar no desconhecido e o unico jeito de o marcador
            # continuar valendo alguma coisa quando ele APARECE.
            "situacao_atual": _situacao_com_marcas(
                _situacao_estadual(c.situacao, raw, c.qt_alteracoes), False,
                _pode_est, _vd_est),
            # ⚠️ A situacao CRUA da fonte, ao lado da enriquecida. `situacao_atual`
            # passou a carregar a NARRATIVA da ultima alteracao, e quem CLASSIFICA
            # (rm_export._e_pendencia) nao pode ler narrativa: uma alteracao
            # "ENCERRADO"/"CONCLUIDA" num convenio ATIVO o faria sumir, calado, do
            # Resumido (o PDF das pendencias). Classificar sempre por esta.
            "situacao_base": (c.situacao or "").strip(),
            **_alteracao_campos(raw),
            **_prestacao_contas_campos(raw),
            # ⚠️ DEPOIS de `valor_repasse`/`valor_contrapartida` de proposito: as
            # chaves aqui (`valor_desembolsado`, `desembolsos`, ...) nao colidem
            # com nenhuma acima, mas a ordem torna visivel que este bloco e o
            # ULTIMO a falar sobre dinheiro no item.
            **_mg_des,
            # SEGOV (dado aberto): NEs, valor empenhado, "Empenhado: Sim" e — so
            # quando o Joomla nao respondeu — o total pago em `valor_desembolsado`.
            # DEPOIS de `**_mg_des` de proposito: ver _segov_campos.
            **_segov_campos(_sg, bool(_mg_pg.get("_consultado"))),
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
               obras,
               -- O `detalhe` INTEIRO. As linhas acima extraem chaves pontuais
               -- (->>'Empenhado', ->>'Banco'), mas o numero da proposta do Novo
               -- PAC tem rotulo com acento, hifen e espacos — casar a chave exata
               -- em SQL seria apostar na grafia. Vem inteiro e a busca tolerante
               -- acha (_pac_da_voluntaria).
               detalhe,
               -- MODALIDADE do instrumento ("Convênio", "Contrato de Repasse",
               -- "Termo de Compromisso"...). O RM nunca leu esta coluna; ela
               -- entra para o marcador "PENDENTE DE EMPENHO", que o dono pediu
               -- SO para o Termo de Compromisso (ver _e_termo_compromisso).
               -- ULTIMA COLUNA (row[28]), a quinta consecutiva pendurada no fim
               -- pela mesma razao das quatro acima: o laco le por INDICE, e
               -- inserir no MEIO deslocaria em silencio `detalhe` (row[27]),
               -- `obras` (row[26]), `notas_empenho` (row[25]) e `programa`
               -- (row[24]). Nada disso levanta excecao: sai relatorio errado,
               -- calado.
               -- ⚠️ `detalhe->>'Empenhado'` (row[15]) segue no SELECT e segue
               -- SEM USO, de proposito: remove-lo deslocaria row[16]..row[28].
               modalidade,
               -- VALOR EMPENHADO agregado do dado aberto (VL_EMPENHADO_CONV),
               -- lido desde o #333. Sem esta linha a coluna existia no banco e
               -- NINGUEM a consumia: o RM calculava o empenho so pela listagem
               -- de NEs da aba logada, que e NULA em 2.741 das 3.199 propostas
               -- do tenant. ULTIMA COLUNA (row[29]), a sexta consecutiva
               -- pendurada no fim pela mesma razao das cinco acima.
               valor_empenhado,
               -- SITUACAO DO TERMO DE REFERENCIA vinda do CSV PUBLICO.
               --
               -- `projeto_basico` (row[23]) e o JSONB da tela LOGADA e vem nulo na
               -- pratica: exige o SP `execucao` da sessao gov.br quente, medido
               -- frio 519 vezes no log e com a sessao morta 298 de 720 horas em 30
               -- dias. Enquanto isso este campo chega no `siconv_proposta.zip`
               -- desde 31/08 e estava preenchido em 2.799 de 3.200 propostas do
               -- freitas — sem ninguem ler.
               --
               -- ULTIMA COLUNA (row[30]), a setima consecutiva pendurada no fim
               -- pela mesma razao das seis acima: o laco le por INDICE, e inserir
               -- no MEIO desloca tudo em silencio.
               situacao_projeto_basico,
               -- NOTAS DE EMPENHO DO DADO ABERTO (siconv_empenho.zip), FALLBACK
               -- da listagem rica do scraper. ⚠️ NUNCA substitui `notas_empenho`
               -- (row[25]): o `_ne_efetiva` abaixo usa a rica quando existe e cai
               -- para esta so quando a rica e nula — o requisito "nao perder
               -- informacao". OITAVA coluna (row[31]).
               notas_empenho_aberto,
               -- DESEMBOLSO DO DUMP (siconv_desembolso.zip, 15/09/2026), no
               -- MESMO formato do `ops_obs` raspado (row[22]). Manda sobre ele
               -- — ver `services/voluntarias_dump.ops_obs_preferido`. NONA e
               -- ULTIMA coluna (row[32]), pela mesma razao das oito acima.
               ops_obs_aberto,
               -- Nº DO PROCESSO (SEI), do dado aberto diario (NR_PROCESSO). E a
               -- chave que casa a voluntaria com o Termo de Compromisso do
               -- SIMEC/PAR (`simec_termos.processo`) — a creche 932836/2021 e o
               -- caso. ULTIMA coluna (row[33]), pela mesma razao das nove acima.
               numero_processo
        FROM transferegov_propostas WHERE municipio_id = :m
        -- ⚠️ SO A PREFEITURA entra no RM (15/09/2026). O filtro por IBGE traz o
        -- que esta sediado na cidade — o convenio do Estado de Goias nao e
        -- instrumento da prefeitura de Goiania. Ver `services/natureza.py`.
          AND municipal IS NOT FALSE
    """), {"m": municipio_id})
    # PACs que JA aparecem como voluntaria. O mesmo recurso saia DUAS vezes no
    # relatorio: uma como voluntaria (que e o instrumento de verdade, com valores
    # e vigencia) e outra como item do Novo PAC (que e so a etapa da selecao).
    # Preenchido aqui e consumido no bloco do PAC, mais abaixo — a ordem importa.
    _pac_ja_exibidos: set[str] = set()
    # TERMOS DE COMPROMISSO do SIMEC/PAR deste municipio, por Nº DO PROCESSO
    # (digitos). Quem casar com uma voluntaria pelo `numero_processo` (row[33])
    # tem o pago do SIMEC impresso NA LINHA DA VOLUNTARIA (ver _simec_na_linha)
    # e NAO sai de novo como item separado la embaixo — mesma disciplina do
    # `_pac_ja_exibidos`, inclusive a de so contar como exibido o que pode
    # entrar neste relatorio. Best-effort: sem a tabela, segue sem juncao.
    _simec_tc: dict = {}
    try:
        _simec_tc = _simec_termos_mapa((await db.execute(text("""
            SELECT processo, nr_documento, tipo_documento, tipo_objeto, dt_vigencia,
                   valor_termo, valor_empenhado, valor_pago, saldo_bancario,
                   prestacao_contas
              FROM simec_termos WHERE municipio_id = :m
        """), {"m": municipio_id})).all())
    except Exception as ex:
        logger.warning(f"RM: simec_termos (juncao por processo) indisponivel p/ "
                       f"{municipio_id}: {str(ex)[:120]}")
    _simec_ja_exibidos: set[str] = set()
    for row in vol.fetchall():
        sit = row[3] or ""
        # O DESEMBOLSO: o do dump (row[32]) quando existe, com NS/OP/situacao da
        # raspagem (row[22]) onde o numero da OB bate. E o MESMO bloco que a
        # aba OPs/OBs do modal mostra (`routers/transferegov.voluntarias_detalhe`).
        # Consequencia: "Desembolsado: R$ ..." e o ano do pagamento (bloco
        # "REPASSES DE {ano}") passam a sair tambem nos convenios que a
        # raspagem nunca leu — antes o relatorio calava neles.
        _ops_vol = ops_obs_preferido(row[32], row[22])[0]
        # De qual selecao do Novo PAC esta voluntaria nasceu (vazio se nenhuma).
        _pac_origem_atual = _pac_da_voluntaria(row[27])
        # ⚠️⚠️ SO CONTA COMO "JA EXIBIDO" SE A VOLUNTARIA PUDER MESMO ENTRAR NESTE
        # RELATORIO. Este conjunto e preenchido AQUI, no laco das VOLUNTARIAS,
        # fora e antes do `add_item` — e e consumido la embaixo, no bloco do PAC,
        # para o mesmo recurso nao sair duas vezes.
        #
        # Com o filtro de consultas ligado SEM "voluntaria" (ex.: o usuario marcou
        # so "Novo PAC"), este laco CONTINUA rodando inteiro — ele nao para, so
        # deixa de inserir itens. Sem esta condicao, ele alimentaria a deduplicacao
        # com propostas que NAO estao no documento, e o item do Novo PAC seria
        # suprimido por uma voluntaria invisivel: o recurso sumiria das DUAS
        # fontes ao mesmo tempo, sem excecao e sem rastro.
        #
        # Sem filtro (todas as consultas) `fonte_no_escopo` devolve True sempre e o
        # comportamento e exatamente o de hoje.
        if _pac_origem_atual and fonte_no_escopo(fontes_filtro, "voluntaria"):
            _pac_ja_exibidos.add(_pac_origem_atual)
        # Regra do ANO DE EMISSÃO: empenhada/paga (Em execução / Prestação) fica
        # sempre; "em análise/aprovada" só do ano de emissão; antigas não-avançadas
        # saem. Empenho validado pelo STATUS (não pelo flag detalhe->>'Empenhado',
        # que estava marcando "Aprovadas" como empenhadas sem empenho real).
        ano_prop = _ano_de(row[1], row[2])  # numero_proposta NNNNNN/AAAA / codigo
        # row[2] = codigo_instrumento, row[6] = dt_fim_vigencia. Os dois juntos
        # sao o que resgata pre-empenho ANTIGA no relatorio de todos os anos:
        # virou instrumento E a vigencia ainda corre. E o caso da 932836/2021
        # (proposta 059522/2021, instrumento 932836, vigencia ate 31/12/2026),
        # que o portal ainda mostra como "Proposta/Plano de Trabalho Aprovados".
        # `row[2]` e o MESMO campo que decide `tipo_label` tres linhas abaixo.
        if not _fed_retem(ano_prop, ano_emissao, sit, completo,
                          anos_sel=anos_filtro, dt_fim=row[6],
                          celebrado=bool(row[2])):
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
            # ⭐ LICITAÇÃO EM ELABORAÇÃO e OBRA SEM ART/RRT — os dois são ação do
            # MUNICÍPIO (pedido do dono, 26/08/2026). Até aqui o item ficava na
            # Parte 1, listado como pendência de Brasília, e no caso da ART com a
            # frase da pendência municipal escrita ao lado, numa caixa cinza.
            #
            # ⚠️ As duas funções só afirmam com DADO LIDO — `None` e vazio
            # devolvem False. Classificar por ausência poria cobrança falsa na
            # mesa do prefeito e ainda tiraria o item do RM Resumido, que só
            # imprime a Parte 1.
            #
            # ⚠️ COBERTURA IRREGULAR, e vale saber: `processo_execucao` (row[21])
            # só é gravado com detalhe lido E contratação Normal E `_hx` vivo; e
            # `obras` (row[26]) depende de `TG_OPS_OBS=1`, que hoje está ligado em
            # freitas/montesiao/santamaria mas NÃO no trust. Onde o dado não
            # chega, a classificação sai idêntica à de hoje — não piora, mas
            # também não entrega.
            if _lic_em_elaboracao(row[21]) or _obra_sem_art(row[26]):
                pend = True
            # ano do PAGAMENTO (OPs/OBs) — alimenta o bloco "REPASSES DE {ano}".
            ano_pgto_vol = _ano_pagamento_ops_obs(_ops_vol)
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
        # ⚠️ A LISTAGEM DE NEs EFETIVA: a RICA do scraper (row[25]) quando existe,
        # e a do DADO ABERTO (row[31], siconv_empenho) SO como fallback quando a
        # rica e nula. Este e o ponto unico que garante "nao perder informacao":
        # a fonte logada, que tem detalhe que a API nao tem, sempre vence; a API
        # so preenche o vazio (2.742 de 3.200 propostas sem listagem, porque a
        # sessao gov.br fica fria). As duas colunas tem o MESMO formato, entao as
        # quatro funcoes abaixo leem qualquer uma sem traducao.
        _ne = row[25] if row[25] is not None else row[31]
        # EMPENHADO: o DOCUMENTO na frente da inferencia. `_ne` = listagem de NEs
        # (NE real manda), `sit` = status do ciclo. Devolve "" quando nao ha
        # prova nenhuma — e rm_pdf OMITE a linha nesse caso, em vez de afirmar
        # "Não" sem ter medido.
        # ⚠️ `detalhe->>'Empenhado'` (row[15]) NAO entra: e o flag furado do
        # portal, que erra nos dois sentidos. Ver _empenhado_rotulo.
        empenhado = _empenhado_rotulo(_ne, sit, row[29])
        # EMPENHO (NEs): "PENDENTE DE EMPENHO" — o simetrico do PENDENTE DE
        # DESEMBOLSO logo abaixo, um degrau antes na esteira do dinheiro.
        #
        # ⚠️ AS DUAS CONDICOES, e nenhuma e enfeite:
        #   `_e_termo_compromisso(row[28])` — o dono pediu para o TERMO DE
        #       COMPROMISSO. Convenio e Contrato de Repasse seguem exatamente
        #       como estao hoje.
        #   `_sem_empenho(row[25])` — so afirma quando a listagem de NEs FOI
        #       CONSULTADA e voltou sem nenhuma nota real. Coluna NULA (proposta
        #       nao raspada, ou tenant com TG_NES desligado) devolve False e o
        #       relatorio CALA.
        #   ⚠️ E A TERCEIRA, nova: o agregado do dado aberto (row[29]) NAO pode
        #       estar dizendo que HA empenho. Quando a listagem volta vazia mas o
        #       portal publica VL_EMPENHADO_CONV > 0, as duas fontes discordam —
        #       e diante da discordancia o relatorio CALA, em vez de imprimir
        #       "PENDENTE DE EMPENHO" na mesa do prefeito sobre um instrumento
        #       que o proprio governo diz ter empenho.
        # `_ne` (rica ou fallback aberto): quando o dado aberto ja mostra a NE, o
        # relatorio deixa de marcar "PENDENTE DE EMPENHO" indevidamente — antes
        # calava por falta de dado; agora cala porque SABE que ha empenho.
        # O TERMO DO SIMEC/PAR casado pelo nº do processo (row[33]) — resolvido
        # ANTES de qualquer marcador de empenho: se o SIMEC diz que ha empenho,
        # nao se imprime "Pendente de empenho" ao lado dele.
        _tc = _simec_tc.get(_so_digitos(row[33])) if row[33] else None
        _tc_empenhado = bool(_tc and (_money(_tc.get("valor_empenhado")) or 0) > 0)
        _pend_empenho = (_e_termo_compromisso(row[28]) and _sem_empenho(_ne)
                         and not (_money(row[29]) or 0) and not _tc_empenhado)
        if _pend_empenho:
            # Nao imprimir "Empenhado: Sim" ao lado de "PENDENTE DE EMPENHO" no
            # MESMO item: o Sim vem do ciclo e aqui existe MEDICAO dizendo que
            # nao ha NE. Onde ha documento, o documento vence a inferencia — e
            # SO nesse caso.
            empenhado = "Não"
        # DESEMBOLSO (OPs/OBs): "PENDENTE DE DESEMBOLSO" quando a licitacao ja foi
        # ACEITA e nada saiu; senao o valor desembolsado + os lancamentos.
        _des = _desembolso_ops_obs(_ops_vol)
        _vd = _des.get("valor_desembolsado")
        _aceita = _licitacao_aceita(row[21])
        # O PAGO DO SIMEC/PAR NA LINHA (a creche). Onde o SICONV nao mediu
        # desembolso, o pago do SIMEC vira o `valor_desembolsado` e o marcador
        # "Desembolsado: R$ ..." — senao a creche paga pelo FNDE seguia impressa
        # como "R$ 0,00". E com empenho no SIMEC o dinheiro ja deveria estar
        # saindo: entra no `pode_desembolsar`, como a licitacao aceita entra na
        # voluntaria. O "ja exibido" e marcado DEPOIS do add_item, la embaixo.
        _tc_campos = _simec_na_linha(_tc, _vd)
        if "valor_desembolsado" in _tc_campos:
            _vd = _tc_campos["valor_desembolsado"]
        _pode_vol = _aceita or _tc_empenhado
        # Composicao em funcao PURA (ver _situacao_com_marcas): com
        # `_pend_empenho` falso a string sai identica a de antes.
        sit_exibida = _situacao_com_marcas(sit, _pend_empenho, _pode_vol, _vd)
        # O NUMERO do convenio com o ANO DA PROPOSTA ao lado ("981397 /2025"): o
        # numero do instrumento sozinho nao diz de que ano ele e.
        _num_exib = row[2] or row[1] or ""
        if row[2] and row[1] and "/" in str(row[1]):
            _num_exib = f"{row[2]} /{str(row[1]).split('/')[-1].strip()}"
        _entrou = add_item(parte, secao, orgao, {
            # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
            # poder existir. `add_item` consome e REMOVE a chave — ela nunca
            # chega ao JSONB do relatório.
            "_pago": st == "paga",
            "tipo": tipo_label,
            "numero": _num_exib,
            # ⚠️ FALLBACK quando o objeto vem NULL. Proposta recem-enviada ("enviado
            # para Analise") ainda nao tem objeto no portal (medido: 034595/2026,
            # Araujos, objeto NULL). Sem isto o render do PDF OMITE a linha de Objeto
            # (rm_pdf: so imprime se truthy) e o item aparece "sem informacao" — so o
            # numero, num item da Parte 4. Com o texto, a linha sai e a ausencia fica
            # HONESTA (a proposta e real: tem situacao e valor), em vez de um branco.
            "objeto": row[5] or "(objeto ainda não informado pelo portal)",
            # PROGRAMA (row[24], ULTIMA coluna do SELECT). Fica ao lado do objeto no
            # dict e, no PDF, na linha logo abaixo dele (rm_pdf._campos_do_item).
            # Vazio quando a proposta nunca foi coberta pelo dado aberto nem pelo
            # enrich — ai a linha simplesmente nao sai.
            "programa": _programa_limpo(row[24]),
            # ORIGEM NO NOVO PAC. Quando a voluntaria nasceu de uma selecao do
            # PAC, o portal registra o numero na aba Dados — e e esse elo que
            # evita o item duplicado logo abaixo.
            "pac_origem": _pac_origem_atual,
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
            # O pago do SIMEC/PAR (creche): `simec_pagamento` e, so onde o
            # SICONV nao mediu, o `valor_desembolsado`. DEPOIS de `**_des` de
            # proposito: e ele quem vence quando as duas chaves existem.
            **_tc_campos,
            # Processo de Execução (Licitações): só relevante p/ contratação Normal.
            # 0 = Normal SEM processo/licitação registrado (flag); N>0 = tem; None = n/c.
            "processo_execucao_qtd": row[16],
            # Lista das licitações/processos COM detalhe (situação, modalidade, nº,
            # data, aceite) — para o RM mostrar cada registro, não só a contagem.
            "processo_execucao_lista": row[21],
            # Projeto Básico/Termo de Referência: o `clausula_motivo` diz QUAL
            # documento trava; este diz a SITUAÇÃO dele ("Em Análise").
            # row[30] e o plano B do CSV publico — ver o docstring da funcao.
            "projeto_basico": _projeto_basico_resumo(row[23], row[30]),
            # "Situação do NEs" — troca a INFERÊNCIA pelo DOCUMENTO. O campo
            # `empenhado` (Sim/Não) vinha do status do ciclo e o próprio
            # _fed_status documenta que ele marcava "Aprovadas" como empenhadas
            # sem empenho real; aqui sai o número, o valor e a data da NE.
            # ⚠️ `_ne` (rica do scraper, ou fallback do dado aberto) — a listagem
            # de NEs completa. A rica sempre vence; o dado aberto so preenche o
            # vazio. Ver o `_ne = row[25] if ... else row[31]` acima.
            "nes": _nes_resumo(_ne),
            # VALOR EMPENHADO medido (soma das NEs REAIS, sem a minuta de R$ 1,00).
            # `None` = a listagem nunca foi consultada, e aí o PDF não imprime a
            # linha. `0.0` NÃO é vazio: é resposta medida ("consultei e não há").
            "valor_empenhado": _empenho_total(_ne, row[29]),
            # Termo de Compromisso MEDIDO e sem nenhuma NE real. Já aparece dentro
            # de `situacao_atual`; fica também como CAMPO próprio para o PDF poder
            # destacar e para quem classifica (rm_export) não precisar reler texto.
            "pendente_empenho": _pend_empenho,
            # Situação da obra: frase pronta, com o percentual DERIVADO
            # de valores que já estavam no banco e ninguém exibia.
            "obra": _obra_resumo(row[26]),
            # EVENTO ATUAL do Histórico de Comunicações (mandatárias): onde o
            # instrumento está de fato na análise, + situação e considerações.
            **_evento_atual(row[17]),
            "fonte": "voluntaria",
            "fonte_ref": row[1],
        }, ano=ano_prop)
        # ⚠️ SO DEPOIS DE O ITEM ENTRAR. `add_item` devolve False no recorte
        # por consulta e por ESTAGIO; marcar antes suprimia o termo do SIMEC de
        # um RM "pagas" em que a creche (nao paga no SICONV) nem tinha entrado —
        # o pago do FNDE sumia dos DOIS itens. O recorte de ANO (`_no_escopo`,
        # no fim) e antecipado aqui pelo mesmo criterio dele: sem ano, entra.
        if (_entrou and _tc and (not anos_filtro or ano_prop is None
                                 or ano_prop in anos_filtro)):
            _simec_ja_exibidos.add(_so_digitos(row[33]))
    # O falso negativo da juncao nao pode ser mudo: ha termo do SIMEC com
    # processo neste municipio e nenhuma voluntaria casou e entrou. O primeiro
    # suspeito e `numero_processo` vazio ou diferente no dado aberto.
    if _simec_tc and not _simec_ja_exibidos:
        logger.info(f"RM {municipio_id}: {len(_simec_tc)} termo(s) do SIMEC com processo e "
                    f"nenhuma voluntaria casou por numero_processo (e entrou no relatorio)")

    # === Transferencia Especial / Plano de Acao (Emenda Pix) — federal ===
    # Fonte PERSISTIDA: tabela transferegov_te, alimentada pelo coletor do worker
    # (ingestion/transferegov_te.py). A API "especiais" rate-limita e nao da p/ buscar
    # ao vivo numa request; por isso lemos a tabela. Vazio ate o coletor rodar.
    try:
        te = await db.execute(text("""
            SELECT plano_acao_id, codigo, emenda, parlamentar, objeto, situacao,
                   situacao_trabalho, valor_total,
                   -- PAGAMENTOS (documentos habeis -> OP/OB + historico de
                   -- eventos), gravados por ingestion/transferegov_te.py no
                   -- MESMO formato do `ops_obs` das voluntarias — por isso o
                   -- laco abaixo reusa _desembolso_ops_obs e
                   -- _ano_pagamento_ops_obs sem uma linha de parsing nova.
                   -- ULTIMA COLUNA DE PROPOSITO (row[8]): o laco le por INDICE e
                   -- inserir no MEIO deslocaria todos os row[N] seguintes em
                   -- silencio — `objeto` passaria a ler `situacao`, o valor
                   -- trocaria de lugar. Nada disso levanta excecao: sai
                   -- relatorio errado, calado.
                   pagamentos
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
            # DESEMBOLSO da TE. O coletor grava `pagamentos` (row[8]) com as MESMAS
            # chaves do `ops_obs` das voluntarias, entao as duas fontes passam pelas
            # MESMAS funcoes — nenhum parser novo, e nada para divergir depois.
            _des_te = _desembolso_ops_obs(row[8])
            _pg_te = _jsonb(row[8]) if isinstance(_jsonb(row[8]), dict) else {}
            _medido = bool(_pg_te)                       # NULO = nunca consultado
            _pago_100 = bool(_pg_te.get("pago_integral"))
            _vd_te = _des_te.get("valor_desembolsado")
            # ⭐ O DINHEIRO QUE JA SAIU PROMOVE O ESTAGIO — e nao o texto do portal.
            # Sem isto, plano com Ordem Bancaria emitida mas `planoAcaoSituacao`
            # ainda "CIENTE" (o caso NORMAL: o plano 91573 tem OB de 22/06/2026 e
            # segue CIENTE) vira 'ativa' em _fed_status, e o _fed_retem logo abaixo
            # o DESCARTA de todo RM de ano posterior — some do relatorio calado,
            # justamente o plano que ja foi pago. Mesma doutrina de _fns_retem
            # ("Empenho CONFIRMADO exige REPASSE EFETIVO").
            # A frase usa o vocabulario que _fed_status entende ("pagamento" -> 'paga')
            # e fica SEPARADA de `sit_te`, que e o texto exibido.
            _sit_classifica = "Pagamento integral realizado" if _pago_100 else sit_efetivo
            sl = _sit_classifica.lower()
            # Situacao exibida: mostra o plano de acao + o plano de trabalho.
            # ⚠️ `frase(...)` AQUI, e nao la no renderizador. O portal manda este
            # campo em caixa alta ("APROVADO"), e depois de composto ele vira
            # UM segmento de caixa MISTA ("Plano de Trabalho: APROVADO") — que a
            # guarda do `texto_rm` protege de proposito, para nao estragar texto
            # ja correto nem o que o usuario editou a mao. Ou seja: normalizado
            # depois da composicao, nunca seria. Tem de ser antes.
            sit_pt = frase(sit_trab.replace("_", " ").strip())
            sit_te = sit.replace("_", " ").strip()
            if sit_pt and sit_te.lower() != sit_pt.lower():
                sit_te = f"{sit_te} · Plano de Trabalho: {sit_pt}"
            # REGRA DO DONO, na SITUACAO ATUAL: se falta desembolsar, o item grita
            # PENDENTE DE DESEMBOLSO; se saiu 100%, diz que foi pago. Mesmo texto e
            # mesma ordem das voluntarias (bloco `sit_exibida`, acima), p/ o
            # relatorio nao ter dois dialetos para a mesma coisa.
            # ⚠️ So com `_medido`: `pagamentos` NULO e "nunca consultado", NAO "nao
            # ha pagamento" — a disciplina de _nes_resumo, que OMITE a linha em vez
            # de afirmar o que nao mediu.
            if _medido and _pago_100:
                _txt_pg = f"Pago integralmente: {_fmt_brl(_vd_te)}"
            elif _medido and (_vd_te or 0) > 0:
                _txt_pg = f"Desembolsado: {_fmt_brl(_vd_te)} · Pendente de desembolso"
            elif _medido and (_pg_te.get("obs") or _pg_te.get("pendentes")):
                _txt_pg = "Pendente de desembolso"   # ha empenho/DH e nada saiu
            else:
                _txt_pg = ""
            if _txt_pg:
                sit_te = f"{sit_te} · {_txt_pg}" if sit_te else _txt_pg
            # Mesma regra de ano: concluida/empenhada fica (Parte 3/qualquer ano); ativa
            # so do ano de referencia ou posterior. Ano vem do codigo da emenda ou do plano.
            ano_te = _ano_de(cod_em, cod)
            if not _fed_retem(ano_te, ano_emissao, _sit_classifica, completo,
                              anos_sel=anos_filtro):
                continue
            parte_te = 3 if ("conclu" in sl or "pag" in sl or "finaliz" in sl) else 1
            parl = row[3] or (cod_em.split("-", 1)[1].strip() if "-" in cod_em else "")
            valor = _money(row[7])
            orgao_te = "Transferência Especial (Emenda Pix)"
            tipo_te = "Transferência Especial"
            secao_te = _SEC_FED
            if completo:
                st = _fed_status(_sit_classifica)
                parte_te, secao_te, suf = _destino_completo(
                    "federal", "transferencia_especial", st, ano_te,
                    # ano do PAGAMENTO agora tem fonte: a data da OB. Antes so
                    # existia o ano do proprio plano.
                    _ano_pagamento_ops_obs(row[8]) or (ano_te if st == "paga" else None),
                    ano_emissao, False, False, False)
                # ⭐ REGRA DO DONO: TE paga 100% vai para a PARTE 3 — e nao para o
                # bloco "REPASSES DE {ano}" da Parte 2, onde _destino_completo poe
                # o federal pago no ano corrente. A excecao mora AQUI, e nao dentro
                # de _destino_completo, porque aquela funcao e compartilhada com
                # voluntaria/SIMEC/FNS/estadual: mexer la mudaria a Parte de todas
                # as fontes de uma vez.
                if _pago_100:
                    parte_te, secao_te, suf = 3, _SEC_FED_SINGULAR, ""
                orgao_te = orgao_te + suf
                tipo_te = "Plano de Ação"  # rotulo do numero na referencia (Fazenda/TE)
            add_item(parte_te, secao_te, orgao_te, {
                # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
                # poder existir. `add_item` consome e REMOVE a chave — ela nunca
                # chega ao JSONB do relatório.
                "_pago": st == "paga",
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
                # DESEMBOLSO: as MESMAS 4 chaves das voluntarias
                # (valor_desembolsado / valor_a_desembolsar / dt_ultimo_desembolso /
                # desembolsos). Com elas, rm_pdf._desembolso_destaque ja imprime a
                # caixa da TE sem UMA LINHA nova no renderizador. Vazio quando
                # `pagamentos` e NULO — _desembolso_ops_obs devolve {} e o ** nao
                # derrama chave nenhuma, entao a caixa simplesmente nao sai.
                **_des_te,
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
            # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
            # poder existir. `add_item` consome e REMOVE a chave — ela nunca
            # chega ao JSONB do relatório.
            "_pago": True,
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
            # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
            # poder existir. `add_item` consome e REMOVE a chave — ela nunca
            # chega ao JSONB do relatório.
            "_pago": st == "paga",
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
            # ⚠️ FALLBACK: `status_indicacao` do SIGCON vem vazio com frequencia
            # (raspado de uma celula que costuma estar em branco). Sem isto o item
            # "Indicação" sai SEM a linha de Situação atual — o "estadual sem
            # situação" reclamado. O texto e honesto: nao inventa um estagio, so
            # diz que a fonte nao informou. (A CLASSIFICACAO por parte usa `st`
            # acima, derivado do `sit` cru — este fallback e so de EXIBICAO.)
            "situacao_atual": sit or "Situação não informada pelo SIGCON",
            "fonte": "emenda_estadual",
            "fonte_ref": str(r[0]),
        }, ano=r[2])

    # === SIMEC/PAR — TERMOS DE COMPROMISSO (o INSTRUMENTO do MEC) ===
    # As liberacoes (simec_par_liberacoes) sao os PAGAMENTOS; aqui entra o termo em
    # si — processo, tipo, vigencia e valor —, coletado de carregaTermos.php
    # (ingestion/simec_termos.py). Best-effort: tenant sem a tabela segue sem MEC.
    #
    # ⚠️ Termo que JA SAIU NA LINHA DA VOLUNTARIA (casado pelo nº do processo,
    # `_simec_ja_exibidos`) NAO sai de novo aqui — seria o mesmo dinheiro duas
    # vezes na mesma pagina. O conjunto so recebe processo de voluntaria que
    # ENTROU (ver o `_entrou` la em cima), senao o recorte "pagas" perderia o
    # termo pago de uma creche que ele proprio descartou.
    #
    # ⚠️ `completo` E SEMPRE TRUE EM PRODUCAO: os dois chamadores (routers/rm.py,
    # criar e auto-popular) passam completo=True, e o "anual" da tela e a
    # SELECAO de anos (`anos=[2026]`) sobre este mesmo modelo. Um instrumento
    # de 2021 — a creche 932836/2021 — entra no "Todos os anos" e em qualquer
    # selecao que inclua 2021; numa selecao so de 2026 ele nao entra, como
    # nenhum outro instrumento de 2021 (`_fed_retem` + `_no_escopo`). Isso e
    # o recorte por ano do RM, nao este bloco.
    if completo:
        try:
            tc = await db.execute(text("""
                SELECT processo, nr_documento, tipo_documento, tipo_objeto,
                       dt_validacao, periodo_pagamento, vigencia_txt, dt_vigencia,
                       valor_termo,
                       -- ⚠️ AS QUATRO NOVAS VAO NO FIM. Este resultado e lido por
                       -- INDICE (r[0]..r[8]); coluna inserida no meio desloca
                       -- tudo em silencio.
                       valor_empenhado, valor_pago, saldo_bancario, prestacao_contas
                FROM simec_termos WHERE municipio_id = :m
            """), {"m": municipio_id})
            for r in tc.fetchall():
                if _so_digitos(r[0]) and _so_digitos(r[0]) in _simec_ja_exibidos:
                    continue
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
                    # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
                    # poder existir. `add_item` consome e REMOVE a chave — ela nunca
                    # chega ao JSONB do relatório.
                    "_pago": st == "paga",
                    "tipo": "Processo",   # rotulo do numero na referencia (Educacao/SIMEC)
                    "numero": r[0] or r[1] or "",
                    "objeto": " · ".join(x for x in (r[2], r[3]) if x) or "",
                    "parlamentar": "",
                    "valor_global": _money(r[8]),
                    "valor_repasse": _money(r[8]),
                    "valor_contrapartida": 0,
                    "banco": "", "agencia": "", "conta": "",
                    # ⚠️ ERAM TRES ZEROS FIXOS ate 31/08/2026 — nao porque o SIMEC
                    # nao publicasse, mas porque `_COLS` do coletor parava no
                    # "Valor do Termo". A pagina traz Valor Empenhado, Pagamento
                    # Efetivado e Saldo Bancario ao lado dele. Era por isso que a
                    # creche de Araujos (TC 202141430-1: R$ 1.875.147,32
                    # empenhados e R$ 572.978,05 pagos) aparecia no relatorio
                    # como se nada tivesse andado.
                    "saldo_bancario": _money(r[11]) if r[11] is not None else None,
                    "dt_saldo": None,
                    "valor_empenhado": _money(r[9]) if r[9] is not None else None,
                    # `valor_desembolsado` e a chave GENERICA que a caixa de
                    # desembolso do PDF ja le (rm_pdf._desembolso_destaque); o
                    # termo do MEC passa a preenche-la com o pagamento efetivado.
                    "valor_desembolsado": _money(r[10]) if r[10] is not None else None,
                    "prestacao_contas_status": (r[12] or "").strip(),
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
                # ⚠️ NAO REPETIR O QUE JA SAIU COMO VOLUNTARIA. Quando a selecao
                # do PAC vira instrumento, o mesmo recurso aparecia DUAS vezes no
                # relatorio: como voluntaria (o instrumento de verdade, com
                # valores, vigencia e execucao) e como item do PAC (que e so a
                # etapa da selecao). O elo e o "Número da Proposta Novo PAC" que
                # a propria voluntaria carrega no detalhe. A voluntaria vence: ela
                # diz mais. A origem no PAC nao se perde — vai impressa NELA.
                if any(_mesma_proposta(r[0], p) for p in _pac_ja_exibidos):
                    continue
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
                # ⭐ NOVO PAC É DEMANDA DO MUNICÍPIO (pedido do dono, 26/08/2026).
                # São DUAS metades, e uma sem a outra não entrega:
                #
                #  `pre_empenho_novo=False` — a Parte 4 se chama, literalmente,
                #  "Propostas Voluntárias … cadastros realizados no ano de {ano} …
                #  não possuem garantia". Uma seleção do PAC não é proposta
                #  voluntária, e `_destino_completo` devolve a Parte 4 ANTES de
                #  olhar a pendência: sem zerar isto, o PAC do ano corrente
                #  continuaria caindo lá e o pedido não teria efeito nenhum
                #  justamente nas seleções mais novas.
                #
                #  `pend_municipal=True` — leva o não pago para a Parte 2 em vez
                #  da 1. O PAGO segue o caminho de sempre (Parte 2 no ano
                #  corrente, Parte 3 nos anteriores): o pedido é sobre onde a
                #  bola está, e em seleção paga não há bola com ninguém.
                parte_pac, secao_pac, suf = _destino_completo(
                    "federal", "pac", st, ano_pac, None, ano_emissao,
                    True, False, False)
                add_item(parte_pac, secao_pac, ("Novo PAC" + suf), {
                    # ⭐ Marca o ESTÁGIO na origem, para o recorte pagas/pendentes
                    # poder existir. `add_item` consome e REMOVE a chave — ela nunca
                    # chega ao JSONB do relatório.
                    "_pago": st == "paga",
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
