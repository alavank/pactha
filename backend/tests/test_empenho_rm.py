"""EMPENHO no RM: quando o relatório pode dizer "Sim", quando tem de CALAR e
quando pode afirmar "PENDENTE DE EMPENHO".

É dinheiro público num documento assinado. Cada teste aqui existe para impedir
uma AFIRMAÇÃO sem medição — nos dois sentidos: nem "Não" onde não se consultou,
nem "Sim" a partir de um flag que o próprio repositório documenta como furado.
"""
from services.rm_builder import (
    _e_termo_compromisso, _empenhado_rotulo, _empenho_valor, _sem_empenho,
    _situacao_com_marcas, _tem_ne_real,
)

NE_REAL = [{"numero": "2026NE000320", "valor": 280000.0, "situacao": "Enviado"}]
SO_MINUTA = [{"numero": "", "valor": 1.0, "situacao": "Minuta de Empenho",
              "minuta_apenas": True}]


# ---------------------------------------------------------------------------
# _tem_ne_real / _empenhado_rotulo
# ---------------------------------------------------------------------------
def test_ne_real_manda_em_tudo():
    assert _tem_ne_real(NE_REAL) is True
    assert _empenhado_rotulo(NE_REAL, "Plano de Trabalho em Análise") == "Sim"


def test_minuta_nao_e_empenho():
    # A listagem do portal mistura o empenho com a MINUTA (sem número, R$ 1,00).
    assert _tem_ne_real(SO_MINUTA) is False
    assert _empenhado_rotulo(SO_MINUTA, "Aprovada") == ""


def test_o_caso_994997_deixa_de_sair_como_Nao():
    # Convênio assinado com NE emitida saía "Empenhado: Não", porque _fed_status
    # classifica "Em Vigor"/"Assinado" como 'vigente' e não 'empenhada'.
    assert _empenhado_rotulo(NE_REAL, "Em Vigor") == "Sim"


def test_status_do_ciclo_ainda_prova_Sim_sem_NE():
    assert _empenhado_rotulo(None, "Em execução") == "Sim"


def test_sem_prova_nenhuma_o_relatorio_CALA():
    # ⚠️ "" e não "Não": a ausência de NE não prova ausência de empenho (tenant
    # com TG_NES desligado nunca consulta). rm_pdf omite a linha nesse caso.
    assert _empenhado_rotulo(None, "Aprovada") == ""
    assert _empenhado_rotulo([], "Plano de Trabalho em Análise") == ""


def test_lista_vinda_como_texto_json_e_lida():
    assert _empenhado_rotulo('[{"numero": "2026NE000320"}]', "Aprovada") == "Sim"


# ---------------------------------------------------------------------------
# _empenho_valor: None e 0.0 são coisas DIFERENTES
# ---------------------------------------------------------------------------
def test_nunca_consultado_devolve_None_e_consultado_vazio_devolve_zero():
    assert _empenho_valor(None) is None       # coluna nula: ninguém mediu
    assert _empenho_valor([]) == 0.0          # medido: não há empenho
    assert _empenho_valor(SO_MINUTA) == 0.0   # a minuta de R$ 1,00 não soma


def test_soma_so_as_notas_reais():
    notas = NE_REAL + SO_MINUTA + [{"numero": "2026NE000321", "valor": 20000.0}]
    assert _empenho_valor(notas) == 300000.0


def test_NE_real_sem_valor_lido_nao_quebra_a_soma():
    assert _empenho_valor([{"numero": "2026NE000320", "valor": None}]) == 0.0


# ---------------------------------------------------------------------------
# _sem_empenho: só afirma o que foi medido
# ---------------------------------------------------------------------------
def test_sem_empenho_exige_medicao():
    assert _sem_empenho(None) is False        # nunca consultado -> não afirma
    assert _sem_empenho([]) is True           # consultado e vazio
    assert _sem_empenho(SO_MINUTA) is True    # só minuta é "sem empenho"
    assert _sem_empenho(NE_REAL) is False


def test_sem_empenho_conta_NOTA_e_nao_valor():
    # NE real com a célula de valor vazia no portal: há empenho emitido, e
    # decidir por `_empenho_valor() == 0` marcaria isto como pendente.
    assert _sem_empenho([{"numero": "2026NE000320", "valor": None}]) is False


# ---------------------------------------------------------------------------
# _e_termo_compromisso
# ---------------------------------------------------------------------------
def test_termo_de_compromisso_e_reconhecido_com_e_sem_acento():
    assert _e_termo_compromisso("Termo de Compromisso") is True
    assert _e_termo_compromisso("TERMO DE COMPROMISSO") is True
    assert _e_termo_compromisso("termo de compromisso") is True


def test_lixo_com_TAB_colado_pelo_varredor_do_portal_nao_atrapalha():
    # O scraper grava a célula crua da tela: "Termo de Compromisso\tEnviada
    # para mandataria?\tNao\t..." — ~950 linhas assim já foram documentadas.
    assert _e_termo_compromisso(
        "Termo de Compromisso\tEnviada para mandataria?\tNao") is True


def test_outros_Termo_de_NAO_casam():
    # startswith e não `in`: são modalidades DIFERENTES.
    for m in ("Termo de Execução Descentralizada", "Termo de Fomento",
              "Termo de Colaboração", "Convênio", "Contrato de Repasse", "", None):
        assert _e_termo_compromisso(m) is False


# ---------------------------------------------------------------------------
# _situacao_com_marcas — NÃO-REGRESSÃO do texto que já saía
#
# ⚠️ OS MARCADORES SAÍRAM DO CAIXA ALTA em 08/2026 (pedido do dono: «APROVADO e
# PENDENTE DE DESEMBOLSO ainda está em caixa alta»). A ideia original era
# «gritar na página»; na prática o caixa alta virou ruído no meio de um texto
# todo em sentence case.
#
# O conjunto `texto_rm._MARCAS` continua protegendo os dois — a comparação lá é
# por `_chave`, que remove acento e sobe a caixa, então a MESMA entrada casa as
# duas grafias. Isso mantém o RM ANTIGO intacto: o `conteudo` já emitido guarda
# a forma em caixa alta e reimprimi-lo continua saindo como saiu.
# ---------------------------------------------------------------------------
def test_sem_o_marcador_novo_a_string_sai_identica_a_de_antes():
    assert _situacao_com_marcas("Em execução", False, True, 0) == \
        "Em execução · Pendente de desembolso"
    assert _situacao_com_marcas("Em execução", False, False, 280000.0) == \
        "Em execução · Desembolsado: R$ 280.000,00"
    assert _situacao_com_marcas("", False, True, 0) == "Pendente de desembolso"
    assert _situacao_com_marcas("Aprovada", False, False, 0) == "Aprovada"
    assert _situacao_com_marcas("", False, False, None) == ""


def test_o_empenho_vem_ANTES_do_desembolso():
    # A ordem é a da esteira do dinheiro: não se desembolsa o que não foi
    # empenhado.
    assert _situacao_com_marcas("Em execução", True, True, 0) == \
        "Em execução · Pendente de empenho · Pendente de desembolso"


def test_pendente_de_empenho_sozinho():
    assert _situacao_com_marcas("Assinado", True, False, 0) == \
        "Assinado · Pendente de empenho"
