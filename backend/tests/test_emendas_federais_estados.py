"""
Os cinco estados da tela de Emendas Federais — e a ORDEM das perguntas.

⚠️ POR QUE ISTO É TESTE, E DE UMA FUNÇÃO PURA. "Nenhuma emenda na tela" tem
cinco causas, e **quatro delas não são «este município não tem emenda»**.
Responder a última primeiro é exatamente o defeito que a tela de Convênios teve
por meses: ela acusava o cliente de não ter convênio quando o que faltava era
senha no Cofre (ver o cabeçalho de `services/coleta.py`).

A regra é a ordem, a ordem cabe numa função sem banco, e o repo não tem Postgres
de teste — então a regra é o que se testa e a consulta fica no chamador. Mesmo
desenho de `classificar_credencial`.

Rodar:
    python -m pytest backend/tests/test_emendas_federais_estados.py -v
"""
import pytest

from services.coleta import (FRASE_EMENDAS_FEDERAIS,
                             classificar_emendas_federais)


def _c(**kw) -> str:
    base = {"chave_configurada": True, "houve_coleta": True, "tem_cnpj": True,
            "n_emendas": 10, "n_execucao_consultada": 10}
    base.update(kw)
    return classificar_emendas_federais(**base)


def test_sem_cnpj_vem_primeiro_porque_e_a_unica_causa_acionavel():
    """⚠️ A emenda é reconhecida pelo CNPJ do beneficiário. Município sem CNPJ
    cadastrado não acha NADA — e dizer «não há emenda» ali seria acusar a
    prefeitura de uma ausência que é do NOSSO cadastro.

    Vem antes de tudo, inclusive de «sem coleta»: é a única das cinco que o
    operador pode corrigir hoje."""
    assert _c(tem_cnpj=False) == "sem_cnpj"
    # E vence mesmo quando tudo o mais também está faltando.
    assert _c(tem_cnpj=False, houve_coleta=False, n_emendas=0,
              chave_configurada=False) == "sem_cnpj"


def test_sem_coleta_e_o_unico_em_que_a_acao_certa_e_esperar():
    """Mandar conferir configuração aqui faria alguém mexer numa fonte que ainda
    nem rodou — o mesmo motivo pelo qual o `sem_coleta` da credencial do SIGCON
    não manda mexer em nada."""
    assert _c(houve_coleta=False, n_emendas=0) == "sem_coleta"
    assert "próxima rodada" in FRASE_EMENDAS_FEDERAIS["sem_coleta"]
    # ⚠️ Não pode mandar conferir chave nem cadastro.
    frase = FRASE_EMENDAS_FEDERAIS["sem_coleta"].lower()
    assert "chave" not in frase and "cadastr" not in frase


def test_sem_emendas_e_a_unica_afirmacao_sobre_o_municipio_e_declara_o_metodo():
    """É a única das cinco que afirma algo sobre o MUNICÍPIO, e por isso é a
    única que precisa dizer COMO procurou: a busca é por CNPJ do beneficiário, e
    emenda a uma entidade cujo CNPJ não está cadastrado não aparece.

    Sem essa ressalva, um CNPJ faltando vira «o município não tem emenda» — e é
    justamente por CNPJ que a emenda ao hospital ou à APAE chega (medido: 8
    emendas ao Hospital N. S. da Piedade em Nova Palma)."""
    assert _c(n_emendas=0, n_execucao_consultada=0) == "sem_emendas"
    assert "CNPJ do beneficiário" in FRASE_EMENDAS_FEDERAIS["sem_emendas"]


def test_sem_chave_nao_manda_o_cliente_fazer_nada():
    """⚠️ A chave é de pessoa física, vinculada ao CPF de quem a cadastrou, e
    quem decide ligá-la é o dono do PACTHA. Mandar «procure o suporte» empurraria
    o cliente para uma fila por uma decisão já tomada.

    O que a frase PRECISA fazer é impedir a leitura errada: «empenhado R$ 0» não
    é «nada foi empenhado», é «ninguém perguntou»."""
    assert _c(chave_configurada=False, n_execucao_consultada=0) == "sem_chave"
    frase = FRASE_EMENDAS_FEDERAIS["sem_chave"]
    assert "não é R$ 0" in frase
    assert "carteira abaixo está completa" in frase


def test_a_carteira_vem_antes_da_chave_na_ordem():
    """⚠️ SUTIL E IMPORTANTE: sem chave MAS sem emenda nenhuma, o que o gestor
    precisa saber é que não há emenda — dizer «falta a chave» ali sugeriria que
    existe dado escondido atrás dela. A carteira não depende da chave."""
    assert _c(chave_configurada=False, n_emendas=0,
              n_execucao_consultada=0) == "sem_emendas"


def test_parcial_impede_a_leitura_de_que_zero_e_nao_pago():
    """A frase mais importante das cinco: sem ela, oito emendas sem consulta
    parecem oito emendas sem pagamento — e o gestor cobra um parlamentar por um
    empenho que talvez exista."""
    assert _c(n_emendas=10, n_execucao_consultada=7) == "parcial"
    frase = FRASE_EMENDAS_FEDERAIS["parcial"].format(consultadas=7, total=10)
    assert "7 de 10" in frase
    assert "não é R$ 0" in frase


def test_ok_e_vazio_como_o_ok_da_credencial():
    """Repetir «está tudo bem» acima de uma tela cheia é ruído que treina o
    gestor a não ler os avisos desta faixa. O selo de frescor já leva a data."""
    assert _c() == "ok"
    assert FRASE_EMENDAS_FEDERAIS["ok"] == ""


@pytest.mark.parametrize("estado", ["sem_cnpj", "sem_coleta", "sem_emendas",
                                    "sem_chave", "parcial", "ok"])
def test_todo_estado_tem_frase_escrita(estado):
    """⚠️ Estado novo OBRIGA a escrever a frase dele — é o motivo de o dicionário
    morar junto da regra, e não espalhado no frontend."""
    assert estado in FRASE_EMENDAS_FEDERAIS


def test_a_execucao_e_contada_por_consulta_e_nunca_por_valor():
    """⚠️ `n_execucao_consultada` vem de `consultado_em IS NOT NULL`, e NÃO de
    `valor_empenhado > 0`. Emenda consultada cujo empenho é zero é um FATO da
    CGU; emenda não consultada é ausência NOSSA.

    Aqui isso aparece como: 10 emendas todas consultadas dão `ok` mesmo que
    nenhuma tenha valor — a função não olha valor nenhum, e não pode olhar."""
    assert _c(n_emendas=10, n_execucao_consultada=10) == "ok"
    assert _c(n_emendas=10, n_execucao_consultada=0) == "parcial"
