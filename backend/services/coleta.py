"""Frescor de coleta por municipio (scraper_municipio_coleta) para os selos
"Atualizado em" das telas. Ponto unico da regra de honestidade: pos-#159 o
carimbo `ultima_coleta_em` acontece TAMBEM no erro (anti-starvation do
rodizio), entao so datamos quando tentativas=0 — com falhas, o timestamp seria
a hora do ultimo ERRO e a tela deve avisar em vez de mentir a hora."""
import os
from typing import Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def frescor_coleta(db: AsyncSession, municipio_id: int,
                         fontes: Sequence[str]) -> Tuple[Optional[str], int]:
    """(coleta_em_iso | None, falhas_consecutivas) do municipio.

    `fontes` em ordem de preferencia — a primeira com linha vence. Permite
    'sigcon_emendas' com fallback 'sigcon' enquanto o carimbo por dataset ainda
    nao existe nas linhas antigas. Best-effort: tabela ausente (tenant novo)
    devolve (None, 0) e o selo simplesmente nao aparece.
    """
    for fonte in fontes:
        try:
            r = await db.execute(text(
                "SELECT ultima_coleta_em, coalesce(tentativas, 0) "
                "FROM scraper_municipio_coleta "
                "WHERE fonte = :f AND municipio_id = :m"),
                {"f": fonte, "m": municipio_id})
            row = r.first()
        except Exception:
            await db.rollback()
            return None, 0
        if row:
            falhas = int(row[1] or 0)
            em = row[0].isoformat() if (row[0] is not None and falhas == 0) else None
            return em, falhas
    return None, 0


# ---------------------------------------------------------------------------
# ESTADO DA CREDENCIAL — porque "nenhum dado" tem TRES causas e a tela dizia uma
#
# A tela de Convenios Estaduais imprime o mesmo literal "Nenhum dado encontrado."
# quando (a) nao ha credencial do SIGCON no Cofre para aquele municipio, (b) ha
# credencial e ela foi recusada, e (c) a coleta rodou e o municipio realmente nao
# tem convenio. O cliente le sempre como (c) — e (a) e (b) sao pendencias
# ACIONAVEIS que ficavam invisiveis.
#
# ⚠️ Sem credencial o coletor NUNCA TOCA o municipio: `_marca_coleta` so escreve
# com o `municipio_id` que veio da credencial, entao nao existe linha em
# `scraper_municipio_coleta` e o `frescor_coleta` acima devolve (None, 0). O
# estado (a) e MUDO por construcao — nao ha carimbo para o selo mostrar.
#
# O padrao copiado e o do InvestSUS (`routers/investsus.py`), que ja devolve o
# estado da credencial e manda o usuario para Configuracoes -> Cofre de Senhas.
# ---------------------------------------------------------------------------

def _teto_login() -> int:
    """Quantas recusas seguidas tiram o municipio da fila do coletor.

    Mesma env e mesmo default do coletor. ⚠️ A env e do WORKER e a API pode nao
    te-la: no pior caso a tela diz "recusada" onde o coletor ja diz "fora da
    fila". Muda a PALAVRA, nunca se o aviso aparece."""
    try:
        return max(1, int(os.getenv("SIGCON_MAX_TENTATIVAS_LOGIN", "3") or 3))
    except ValueError:
        return 3


def classificar_credencial(n_credenciais: int, tentativas: int,
                           erro_de_login: bool, teto: Optional[int] = None,
                           houve_coleta: bool = True) -> str:
    """'sem_credencial' | 'recusada' | 'fora_da_fila' | 'sem_coleta' | 'ok'.

    ⚠️ SAO QUATRO ESTADOS DE PROBLEMA, e nao tres. O quarto — credencial
    cadastrada e a PRIMEIRA COLETA ainda nao rodou — era indistinguivel tanto do
    "sem credencial" quanto do "coletou e nao ha". Sem ele, quem acabou de
    cadastrar a senha ve "Nenhum dado encontrado" e conclui que a senha nao
    funcionou, quando so falta a proxima rodada do rodizio.

    ⚠️ `erro_de_login`, e nao "falhou". Timeout de rede, portal fora do ar e erro
    de parsing NAO sao culpa da senha — e o coletor ja faz essa distincao. Acusar
    a credencial por uma queda do portal manda o cliente trocar uma senha que
    esta certa, que e pior do que nao avisar nada.

    ⚠️ Funcao PURA de proposito: nao ha Postgres de teste neste repo, e a regra e
    o que precisa de teste. A consulta fica no chamador."""
    if n_credenciais <= 0:
        return "sem_credencial"
    if erro_de_login and tentativas > 0:
        return "fora_da_fila" if tentativas >= (teto or _teto_login()) else "recusada"
    if not houve_coleta:
        return "sem_coleta"
    return "ok"


# O que a tela deve dizer em cada estado. Fica aqui, junto da regra, e nao
# espalhado no frontend: a mesma frase serve tela, PDF e qualquer consumidor
# futuro, e um estado novo obriga a escrever a frase dele.
FRASE_CREDENCIAL = {
    "sem_credencial": "Sem credencial do SIGCON cadastrada para este município — "
                      "cadastre em Configurações → Cofre de Senhas.",
    "recusada": "A credencial do SIGCON foi recusada na última tentativa. "
                "Confira a senha em Configurações → Cofre de Senhas.",
    "fora_da_fila": "A credencial do SIGCON foi recusada seguidas vezes e o "
                    "município saiu da fila de coleta. Atualize a senha em "
                    "Configurações → Cofre de Senhas.",
    # ⚠️ Este NAO manda mexer em nada — e o unico dos quatro em que a acao certa
    # e esperar. Mandar conferir a senha aqui faria o cliente trocar uma
    # credencial que ainda nem foi usada.
    "sem_coleta": "Credencial cadastrada, primeira coleta ainda não rodou. "
                  "O município entra na próxima rodada.",
    "ok": "",
}


# ---------------------------------------------------------------------------
# EMENDAS FEDERAIS — os cinco estados, e por que a ORDEM das perguntas e a regra
#
# "Nenhuma emenda na tela" tem cinco causas e quatro delas NAO sao "este
# municipio nao tem emenda". Responder a ultima primeiro e como a tela de
# Convenios passou meses acusando o cliente de nao ter convenio quando o que
# faltava era senha no Cofre — o defeito que a funcao acima existe para corrigir.
#
# ⚠️ E a fonte tem DUAS FASES: a CARTEIRA sai de um dump ABERTO e a EXECUCAO vem
# da CGU — desde 24/09/2026 pela PLANILHA ABERTA, em todo tenant (antes so pela
# API com chave, ligada em dois). "sem_chave" ficou sendo o estado de carteira
# sem execucao nenhuma (planilha desligada ou falhando): nao e "sem dado", e a
# tela precisa dizer exatamente isso.
# ---------------------------------------------------------------------------
def classificar_emendas_federais(chave_configurada: bool, houve_coleta: bool,
                                 tem_cnpj: bool, n_emendas: int,
                                 n_execucao_consultada: int,
                                 n_sem_codigo: int = 0) -> str:
    """'sem_cnpj' | 'sem_coleta' | 'sem_emendas' | 'sem_chave' | 'parcial' | 'ok'.

    ⚠️ `sem_cnpj` VEM PRIMEIRO porque e a unica causa ACIONAVEL e a unica em que
    o numero na tela seria falso por culpa nossa: a emenda e reconhecida pelo
    CNPJ do beneficiario, entao municipio sem CNPJ cadastrado nao acha NADA — e
    dizer "nao ha emenda" ali seria acusar a prefeitura de uma ausencia que e
    do nosso cadastro.

    ⚠️ `n_execucao_consultada` e contado por execucao CONSULTADA (na tela,
    `coalesce(agregados_em, consultado_em) IS NOT NULL` — planilha ou API), e NAO
    por `valor_empenhado > 0`. Emenda consultada cujo empenho e zero e um FATO da
    CGU; emenda nao consultada e ausencia NOSSA. Confundir as duas e a unica
    forma de esta tela mentir com numeros certos.

    ⚠️ `n_sem_codigo` (24/09/2026): linhas da carteira SEM nº da emenda na fonte.
    Elas nunca entram na fila da CGU (a fila e o JOIN sao pelo codigo), entao
    conta-las no denominador deixava o aviso "parcial" aceso PARA SEMPRE —
    prometendo uma busca que nunca vai acontecer. Saem da conta; a linha mostra
    o motivo dela (grupo `sem_codigo` em `routers/emendas_federais.py`).

    ⚠️ Funcao PURA de proposito, como a `classificar_credencial`: nao ha Postgres
    de teste neste repo, e a REGRA e o que precisa de teste. A consulta fica no
    chamador."""
    if not tem_cnpj:
        return "sem_cnpj"
    if not houve_coleta:
        return "sem_coleta"
    if n_emendas == 0:
        return "sem_emendas"
    consultaveis = n_emendas - (n_sem_codigo or 0)
    if not chave_configurada and consultaveis > 0:
        return "sem_chave"
    if n_execucao_consultada < consultaveis:
        return "parcial"
    return "ok"


FRASE_EMENDAS_FEDERAIS = {
    # (a) SEM CNPJ. A unica das cinco que pede acao de quem opera, e ela diz
    # qual. Sem isto a tela vazia seria lida como "o municipio nao tem emenda".
    "sem_cnpj":
        "Este município ainda não tem CNPJ cadastrado, e é por ele que a emenda "
        "federal é reconhecida. Rode a coleta do SICONFI (que preenche o CNPJ a "
        "partir do cadastro de entes do Tesouro) ou cadastre-o no município.",

    # (b) PRIMEIRA COLETA AINDA NAO RODOU. ⚠️ Este NAO manda mexer em nada — e o
    # unico dos cinco em que a acao certa e ESPERAR. Mandar conferir
    # configuracao aqui faria alguem mexer numa fonte que ainda nem rodou.
    "sem_coleta":
        "A coleta ainda não rodou para este município. Ela é automática, roda de "
        "madrugada e reconhece o município pelo CNPJ — não depende de senha. "
        "O município entra na próxima rodada.",

    # (c) COLETOU E NAO HA. A unica das cinco que e uma AFIRMACAO sobre o
    # municipio, e por isso ela vem com o metodo declarado: a busca e por CNPJ do
    # beneficiario, e a tela lista ao lado quais CNPJ foram consultados. Sem essa
    # ressalva, um CNPJ faltando no cadastro vira "o municipio nao tem emenda" —
    # e e justamente por CNPJ que a emenda ao hospital ou a APAE chega.
    "sem_emendas":
        "A coleta rodou e não encontrou emenda parlamentar federal para os CNPJ "
        "deste município. A busca é por CNPJ do beneficiário: emenda destinada a "
        "uma entidade cujo CNPJ não está cadastrado aqui não aparece nesta tela.",

    # (d) CARTEIRA SIM, EXECUCAO NAO. ⚠️ Nao manda o cliente fazer nada, porque
    # nao ha nada que ele possa fazer: a chave e de pessoa fisica, vinculada ao
    # CPF de quem a cadastrou, e quem decide liga-la e o dono do PACTHA. O que a
    # frase PRECISA fazer e impedir a leitura errada — "empenhado R$ 0" nao e
    # "nada foi empenhado", e sim "ninguem perguntou".
    "sem_chave":
        "A execução destas emendas (empenhado, liquidado, pago) vem do Portal da "
        "Transparência da CGU e ainda não foi consultada neste ambiente — ela é "
        "lida de madrugada, da planilha que a CGU publica todo dia. A carteira "
        "abaixo está completa; o que falta é o andamento de cada uma, e onde ele "
        "aparece como «—» o dado não foi buscado, não é R$ 0.",

    # (e) EXECUCAO PARCIAL. A frase mais importante das cinco: sem ela, oito
    # emendas sem consulta parecem oito emendas sem pagamento, e o gestor cobra
    # um parlamentar por um empenho que talvez exista. O {consultadas}/{total} e
    # formatado pelo router (total = as que TEM numero de emenda).
    # ⚠️ ATE 24/09/2026 dizia "onde a execucao aparece como «—», o dado ainda
    # nao foi buscado" — FALSO para a «Sem registro na CGU», que FOI buscada e
    # tambem mostra «—». A frase agora aponta o selo da linha, nao o traco.
    "parcial":
        "Carteira coletada; a execução foi consultada em {consultadas} de "
        "{total} emendas. As marcadas «Execução não consultada» ainda não foram "
        "buscadas no Portal da Transparência — o «—» delas não é R$ 0. As "
        "marcadas «Sem registro na CGU» foram procuradas, e a CGU não publica "
        "execução para elas.",

    # (f) TUDO CERTO: vazio, como o 'ok' de FRASE_CREDENCIAL. O selo de frescor
    # ja carrega a data, e repetir "esta tudo bem" acima de uma tela cheia e
    # ruido que treina o gestor a nao ler os avisos desta faixa.
    "ok": "",
}
