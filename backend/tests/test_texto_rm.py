"""Padronizacao de maiusculas do RM — services/texto_rm.

Texto que vai assinado ao prefeito: cada teste aqui e uma promessa de que a
funcao NAO estraga alguma coisa que ja estava certa. Os quatro exemplos reais
dos prints do dono estao todos cobertos, com o resultado exato esperado.
"""
from services.texto_rm import (
    frase, nome_proprio, normalizar_item, proprios_do_municipio,
)


class _Mun:
    def __init__(self, nome):
        self.nome = nome


ARAUJOS = proprios_do_municipio(_Mun("Araújos"))


# --------------------------------------------------------------------------
# Os quatro exemplos reais dos prints
# --------------------------------------------------------------------------
def test_objeto_em_caixa_alta_vira_so_primeira_letra_maiuscula():
    origem = ("EXECUÇÃO DE OBRAS OU SERVIÇOS DE ENGENHARIA EM "
              "ESTRADAS VICINAIS NO MUNICÍPIO DE ARAÚJOS/MG")
    assert frase(origem, ARAUJOS) == (
        "Execução de obras ou serviços de engenharia em "
        "estradas vicinais no município de Araújos/MG")


def test_banco_conhecido_sai_na_grafia_canonica_com_acento():
    # O portal grava sem acento; a grafia certa vem da tabela _EXCECOES, escrita
    # a mao — nao de adivinhacao de acento.
    assert nome_proprio("CAIXA ECONOMICA FEDERAL") == "Caixa Econômica Federal"


def test_nome_de_pessoa_em_caixa_alta_vira_capitalizado():
    assert nome_proprio("JUNIO AMARAL") == "Junio Amaral"


def test_programa_em_caixa_mista_nao_muda_um_byte():
    origem = "SNEAELIS (Emenda Parlamentar Individual - RP6 - Convênio)"
    assert nome_proprio(origem) == origem
    assert frase(origem) == origem


def test_programa_em_caixa_alta_preserva_sigla_e_codigo():
    assert nome_proprio("SNEAELIS (EMENDA PARLAMENTAR INDIVIDUAL - RP6 - CONVENIO)") == \
        "SNEAELIS (Emenda Parlamentar Individual - RP6 - Convenio)"


def test_bloco_da_saude_no_tipo_da_proposta_do_fns_fica_sigla():
    """O `coTipoProposta` do FNS vem em caixa alta ("INCREMENTO MAC"); o modelo
    da planilha do cliente escreve "Incremento MAC" (24/09/2026)."""
    assert frase("INCREMENTO MAC") == "Incremento MAC"
    assert frase("INCREMENTO PAP") == "Incremento PAP"
    assert frase("CUSTEIO PAP") == "Custeio PAP"
    # Garantia 3 continua: minúscula não é promovida.
    assert frase("incremento mac") == "Incremento mac"


# --------------------------------------------------------------------------
# As tres garantias
# --------------------------------------------------------------------------
def test_caixa_mista_volta_intacta():
    for s in ("Termo de Referência — Em Análise",
              "2026NE000320 — R$ 280.000,00 — Enviado (09/03/2026)",
              "A obra encontra-se em execução, com 02 medições atestadas."):
        assert frase(s) == s
        assert nome_proprio(s) == s


def test_nunca_inventa_acento():
    # "JUNIO" sem acento na fonte continua sem acento (nao vira "Júnio").
    assert nome_proprio("JUNIO AMARAL") == "Junio Amaral"
    assert frase("CONSTRUCAO DE PRACA") == "Construcao de praca"


def test_sigla_em_minuscula_nao_e_promovida():
    # "mg" de miligrama nao pode virar a UF.
    assert frase("aquisicao de medicamento 500 mg") == "Aquisicao de medicamento 500 mg"


# --------------------------------------------------------------------------
# Protecoes token a token
# --------------------------------------------------------------------------
def test_numero_e_codigo_nunca_mudam():
    assert frase("CONVENIO 993503/2026 CONTA 1060-0 EMPENHO 2026NE000320") == \
        "Convenio 993503/2026 conta 1060-0 empenho 2026NE000320"


def test_palavra_sem_vogal_e_tratada_como_sigla():
    # Nao esta na lista e mesmo assim sobrevive: palavra portuguesa tem vogal.
    assert frase("REPASSE VIA PSDB") == "Repasse via PSDB"


def test_algarismo_romano_curto_sobrevive():
    assert frase("CONSTRUCAO DA ETAPA II DA UBS") == "Construcao da etapa II da UBS"


def test_palavra_longa_de_letras_romanas_nao_e_confundida():
    # "CIVIL" e C-I-V-I-L, todas letras romanas: o limite de 4 caracteres do
    # regex e o que impede "construcao CIVIL".
    assert frase("OBRAS DE CONSTRUCAO CIVIL") == "Obras de construcao civil"


def test_particula_de_nome_fica_minuscula():
    assert nome_proprio("JOSE DA SILVA E SOUZA") == "Jose da Silva e Souza"


def test_particula_na_primeira_posicao_fica_maiuscula():
    assert nome_proprio("DA SILVA JUNIOR") == "Da Silva Junior"


def test_inicial_solta_continua_maiuscula():
    assert nome_proprio("J. AMARAL") == "J. Amaral"


def test_nome_do_municipio_e_restaurado_com_a_grafia_da_base():
    assert frase("REFORMA EM ARAUJOS", ARAUJOS) == "Reforma em Araújos"


def test_municipio_de_nome_composto_protege_as_duas_palavras():
    ms = proprios_do_municipio(_Mun("Monte Sião"))
    assert frase("OBRA NO MUNICIPIO DE MONTE SIAO", ms) == \
        "Obra no municipio de Monte Sião"


def test_municipio_ausente_nao_quebra():
    assert proprios_do_municipio(None) == {}
    assert proprios_do_municipio(_Mun("")) == {}


# --------------------------------------------------------------------------
# Forma do texto
# --------------------------------------------------------------------------
def test_texto_todo_minusculo_ganha_so_a_inicial():
    assert frase("aquisicao de veiculo para a saude") == \
        "Aquisicao de veiculo para a saude"


def test_segunda_frase_recomeca_com_maiuscula():
    # ⚠️ NÃO usar aqui "· PENDENTE DE DESEMBOLSO": aquele segmento é MARCADOR do
    # relatório e passa intacto de propósito (ver os testes de `_MARCAS` no fim
    # do arquivo). Este teste é sobre o `·` recomeçar a frase.
    assert frase("EM EXECUCAO · AGUARDANDO PARECER") == \
        "Em execucao · Aguardando parecer"
    assert frase("OBRA CONCLUIDA. FALTA A VISTORIA") == \
        "Obra concluida. Falta a vistoria"


def test_espacos_e_pontuacao_sao_preservados_byte_a_byte():
    assert frase("OBRAS   DE  ENGENHARIA...") == "Obras   de  engenharia..."


def test_e_idempotente():
    # Aplicar duas vezes tem de dar o mesmo resultado: a saida da 1a passada e
    # caixa mista, e a guarda a devolve intacta. Sem isto, Auto-popular repetido
    # degradaria o texto a cada rodada.
    for s in ("EXECUCAO DE OBRAS EM ARAUJOS/MG", "JUNIO AMARAL",
              "SNEAELIS (EMENDA - RP6)", "aquisicao de veiculo", "MG"):
        um = frase(s, ARAUJOS)
        assert frase(um, ARAUJOS) == um
        um_n = nome_proprio(s, ARAUJOS)
        assert nome_proprio(um_n, ARAUJOS) == um_n


def test_vazio_e_none_nao_quebram():
    assert frase(None) == ""
    assert frase("") == ""
    assert nome_proprio(None) == ""


# --------------------------------------------------------------------------
# Aplicacao ao item do RM
# --------------------------------------------------------------------------
def test_normalizar_item_nao_toca_campo_de_identificacao_nem_de_classificacao():
    item = {
        "objeto": "REFORMA DA UBS CENTRAL",
        "numero": "993503/2026",
        "situacao_base": "EM EXECUCAO",
        "nes": "2026NE000320 — R$ 280.000,00",
        "agencia": "1060-0",
        "conta": "00012345-6",
        "tipo": "PNAE",
        "empenhado": "Sim",
        "fonte": "voluntaria",
    }
    normalizar_item(item)
    assert item["objeto"] == "Reforma da UBS central"
    assert item["numero"] == "993503/2026"
    assert item["situacao_base"] == "EM EXECUCAO"   # e o campo que CLASSIFICA
    assert item["nes"] == "2026NE000320 — R$ 280.000,00"
    assert item["agencia"] == "1060-0"
    assert item["conta"] == "00012345-6"
    assert item["tipo"] == "PNAE"
    assert item["empenhado"] == "Sim"
    assert item["fonte"] == "voluntaria"


def test_normalizar_item_ignora_valor_que_nao_e_texto():
    item = {"objeto": None, "parlamentar": "", "banco": 33,
            "desembolsos": [{"numero_ob": "2026OB800123"}], "valor_global": 1.5}
    normalizar_item(item)
    assert item["objeto"] is None
    assert item["parlamentar"] == ""
    assert item["banco"] == 33
    assert item["desembolsos"] == [{"numero_ob": "2026OB800123"}]
    assert item["valor_global"] == 1.5


def test_normalizar_item_usa_nome_proprio_no_parlamentar_e_frase_no_objeto():
    item = {"objeto": "AQUISICAO DE VEICULO", "parlamentar": "JUNIO AMARAL",
            "banco": "CAIXA ECONOMICA FEDERAL"}
    normalizar_item(item)
    assert item["objeto"] == "Aquisicao de veiculo"
    assert item["parlamentar"] == "Junio Amaral"
    assert item["banco"] == "Caixa Econômica Federal"


# --------------------------------------------------------------------------
# Marcadores do relatorio: PRESERVADOS COMO O BUILDER ESCREVEU
#
# ⚠️ Eles eram caixa alta e deixaram de ser (pedido do dono, 08/2026). O que
# `_MARCAS` garante NÃO é "caixa alta" — é "não mexa neste segmento, ele é meu".
# --------------------------------------------------------------------------
def test_os_avisos_do_relatorio_nao_sao_rebaixados():
    # A grafia de HOJE, que o rm_builder escreve.
    assert frase("Pendente de desembolso") == "Pendente de desembolso"
    assert frase("Pendente de empenho") == "Pendente de empenho"


def test_a_grafia_ANTIGA_do_marcador_tambem_e_preservada():
    """⚠️ COMPATIBILIDADE COM RM JÁ EMITIDO. O `conteudo` de um relatório antigo
    está congelado no JSONB com a forma em caixa alta; reimprimi-lo tem de sair
    como saiu. Funciona porque a comparação de `_MARCAS` é por `_chave` (sem
    acento, caixa alta) — a mesma entrada casa as duas grafias."""
    assert frase("PENDENTE DE DESEMBOLSO") == "PENDENTE DE DESEMBOLSO"
    assert frase("PENDENTE DE EMPENHO") == "PENDENTE DE EMPENHO"


def test_o_valor_do_plano_de_trabalho_tem_de_vir_normalizado_DA_ORIGEM():
    """⚠️ O TESTE QUE EXPLICA ONDE O CONSERTO TEVE DE FICAR.

    O portal manda `situacao_plano_trabalho` em caixa alta ("APROVADO"). Depois
    de composto, o segmento vira "Plano de Trabalho: APROVADO" — caixa MISTA — e
    a guarda do módulo o devolve intacto, de propósito (é ela que impede estragar
    texto já correto e o que o usuário editou à mão na tela).

    Ou seja: normalizado DEPOIS da composição, nunca seria. Por isso o
    `rm_builder` aplica `frase()` no valor ANTES de montar a frase."""
    assert frase("Plano de Trabalho: APROVADO") == "Plano de Trabalho: APROVADO"
    # E o valor sozinho — que é o que o builder passa por `frase()` — normaliza:
    assert frase("APROVADO") == "Aprovado"


def test_a_situacao_composta_padroniza_so_o_lado_da_fonte():
    assert frase("PLANO DE TRABALHO EM ANALISE · PENDENTE DE DESEMBOLSO") == \
        "Plano de trabalho em analise · PENDENTE DE DESEMBOLSO"
    assert frase("EM EXECUCAO · PENDENTE DE EMPENHO · PENDENTE DE DESEMBOLSO") == \
        "Em execucao · PENDENTE DE EMPENHO · PENDENTE DE DESEMBOLSO"


def test_a_situacao_ja_em_caixa_mista_segue_intacta():
    s = "Em execução · PENDENTE DE DESEMBOLSO"
    assert frase(s) == s


def test_desembolsado_com_valor_nao_e_marcador_e_segue_a_regra_normal():
    # Caixa mista: a guarda devolve intacto, como sempre.
    s = "Em execução · Desembolsado: R$ 280.000,00"
    assert frase(s) == s


def test_a_palavra_pendente_no_meio_de_uma_frase_continua_padronizada():
    # `_MARCAS` só vale para o SEGMENTO INTEIRO entre separadores.
    assert frase("OBRA PENDENTE DE VISTORIA") == "Obra pendente de vistoria"


def test_letra_solta_sem_ponto_nao_e_inicial():
    # O artigo e a conjunção não podem ser confundidos com inicial de nome.
    assert frase("FALTA A VISTORIA DA OBRA") == "Falta a vistoria da obra"
    assert nome_proprio("JOSE DA SILVA E SOUZA") == "Jose da Silva e Souza"


def test_letra_solta_COM_ponto_continua_sendo_inicial():
    assert nome_proprio("MARIA A. SILVA") == "Maria A. Silva"
    assert nome_proprio("J. AMARAL") == "J. Amaral"


def test_consoante_e_romano_soltos_sobrevivem_sem_precisar_do_ponto():
    # Consoante não tem vogal (regra 5); "I"/"V" são romanos (regra 6).
    assert frase("OBRA NO ANEXO B") == "Obra no anexo B"
    assert frase("REFORMA DA ETAPA I") == "Reforma da etapa I"
