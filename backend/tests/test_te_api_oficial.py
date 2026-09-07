"""LISTAGEM da Transferência Especial pela API PÚBLICA OFICIAL do MGI.

Os payloads abaixo são RESPOSTAS REAIS de
`api-publica.transferegov.gestao.gov.br/especiais`, capturadas em 06/09/2026 —
não são invenção. O que se prova aqui é o que o olho não pega lendo o diff da
troca de fonte:

  * que a situação do plano de trabalho é TRADUZIDA, e que sem essa tradução o
    RM perderia o plano em silêncio;
  * que `valor_total` e `programa_codigo`, que a fonte nova não entrega prontos,
    são derivados de um jeito que bate com o que a fonte antiga mandava;
  * que o município entra por CNPJ e não sobra caminho por nome.
"""
import json

from ingestion.transferegov_te import (
    _SITUACAO_PT_PARA_CODIGO, _situacao_pt_normalizada, plano_novo_para_linha,
)

# GET /especiais/beneficiarios-especiais?cnpj_beneficiario=88488358000156
BENEFICIARIO_NOVA_PALMA = {
    "id_beneficiario": 9970, "uf_beneficiario": "RS",
    "nome_beneficiario": "NOVA PALMA", "cnpj_beneficiario": "88488358000156",
    "id_ente": 3133,
}

# GET /especiais/planos-acao-especiais?id_beneficiario=9970 (um dos três)
PLANO_67457 = {
    "id_plano_acao": 67457, "codigo_plano_acao": "09032024-2-067457",
    "ano_plano_acao": 2024, "modalidade_plano_acao": "Especial",
    "situacao_plano_acao": "CIENTE",
    "nome_parlamentar_emenda_plano_acao": "Heitor Schuch",
    "codigo_emenda_parlamentar_formatado_plano_acao": "202432980001-Heitor Schuch",
    "categoria_despesa_plano_acao": "INVESTIMENTO",
    "codigo_descricao_areas_politicas_publicas_plano_acao":
        "27-Desporto e Lazer / 812-Desporto Comunitário , 15-Urbanismo / 451-Infraestrutura Urbana",
    "motivo_impedimento_plano_acao": None,
    "valor_custeio_plano_acao": 60000.0, "valor_investimento_plano_acao": 140000.0,
    "id_beneficiario": 9970, "id_objeto": None, "nome_objeto": None,
    "detalhamento_objeto": None, "id_programa": 21,
}

# GET /especiais/planos-acao-especiais?id_plano_acao=3200 — o mesmo plano que a
# API da SPA devolvia com planoAcaoId=3200, para provar que o id não muda.
PLANO_3200 = {
    "id_plano_acao": 3200, "codigo_plano_acao": "0903-003200",
    "situacao_plano_acao": "CIENTE",
    "nome_parlamentar_emenda_plano_acao": "Alceu Moreira",
    "codigo_emenda_parlamentar_formatado_plano_acao": "202028580011-Alceu Moreira",
    "codigo_descricao_areas_politicas_publicas_plano_acao":
        "15-Urbanismo / 451-Infraestrutura Urbana",
    "valor_custeio_plano_acao": 0.0, "valor_investimento_plano_acao": 70000.0,
    "id_beneficiario": 3749, "nome_objeto": None, "detalhamento_objeto": None,
    "id_programa": 3,
}
BENEFICIARIO_TAPEJARA = {
    "id_beneficiario": 3749, "uf_beneficiario": "RS",
    "nome_beneficiario": "MUNICIPIO DE TAPEJARA",
    "cnpj_beneficiario": "87615449000142", "id_ente": 4740,
}


# ---------------------------------------------------------------------------
# O VOCABULÁRIO DA SITUAÇÃO DO PLANO DE TRABALHO
# ---------------------------------------------------------------------------

def test_o_mapa_cobre_as_seis_situacoes_medidas_na_fonte():
    """As seis que apareceram em 800 planos da fonte antiga e nos 200 primeiros
    planos de trabalho da nova, conferidas par a par pelo mesmo id."""
    assert set(_SITUACAO_PT_PARA_CODIGO.values()) == {
        "CONCLUIDO_NT_TCU", "APROVADO", "REPROVADO",
        "ENVIADO_PARA_ANALISE", "EM_COMPLEMENTACAO", "EM_ELABORACAO",
    }


def test_o_rotulo_do_legado_vira_o_codigo_que_o_RM_entende():
    """⭐ O CASO QUE JUSTIFICA O MAPA INTEIRO.

    `rm_builder` decide o estágio procurando substring: "conclu" está em
    "CONCLUIDO_NT_TCU" e NÃO está em "Legado ADPF 854 STF / NT - TCU". Gravar o
    rótulo cru faria o plano cair para a situação do plano de AÇÃO (quase sempre
    "CIENTE" = ativa), e `_fed_retem` descarta ativa de ano anterior: o plano
    sumiria do relatório sem erro nenhum em log.

    É a situação mais comum na base — 650 de 800 planos da amostra.
    """
    assert _situacao_pt_normalizada("Legado ADPF 854 STF / NT - TCU") == "CONCLUIDO_NT_TCU"
    assert "conclu" in _situacao_pt_normalizada("Legado ADPF 854 STF / NT - TCU").lower()
    assert "conclu" not in "Legado ADPF 854 STF / NT - TCU".lower()


def test_os_rotulos_com_acento_casam_pelo_texto_normalizado():
    """A fonte manda "Em Complementação" e "Enviado para Análise"; a chave do
    mapa é sem acento, então o casamento não pode depender da acentuação."""
    assert _situacao_pt_normalizada("Em Complementação") == "EM_COMPLEMENTACAO"
    assert _situacao_pt_normalizada("Enviado para Análise") == "ENVIADO_PARA_ANALISE"
    assert _situacao_pt_normalizada("Em Elaboração") == "EM_ELABORACAO"
    assert _situacao_pt_normalizada("Aprovado") == "APROVADO"
    assert _situacao_pt_normalizada("Reprovado") == "REPROVADO"


def test_situacao_desconhecida_NAO_some_da_tela():
    """Situação que o MGI criar amanhã tem de chegar ao banco de alguma forma:
    devolver None ou "" faria o campo sumir da tela e ninguém descobriria que a
    fonte ganhou um estado novo."""
    assert _situacao_pt_normalizada("Em Diligência") == "EM_DILIGENCIA"


def test_sem_plano_de_trabalho_continua_sendo_NULO():
    """11 de 800 planos da fonte antiga não tinham plano de trabalho. Isso é
    ausência, não um valor a inventar."""
    assert _situacao_pt_normalizada(None) is None
    assert _situacao_pt_normalizada("") is None


# ---------------------------------------------------------------------------
# OS CAMPOS DERIVADOS
# ---------------------------------------------------------------------------

def test_valor_total_e_a_soma_porque_a_fonte_nova_nao_manda_o_campo():
    """A API oficial só tem custeio e investimento. A soma bateu com o
    `valorTotal` da fonte antiga em 800 de 800 planos conferidos."""
    linha = plano_novo_para_linha(PLANO_67457, BENEFICIARIO_NOVA_PALMA, "APROVADO", 42)
    assert linha["valor_custeio"] == 60000.0
    assert linha["valor_investimento"] == 140000.0
    assert linha["valor_total"] == 200000.0


def test_programa_codigo_sai_do_codigo_do_plano_e_nao_da_fonte():
    """⚠️ `/programas-especiais.codigo_programa` PERDE O ZERO À ESQUERDA — devolve
    '903' onde a fonte antiga mandava '0903', porque trata o código como número.
    O código do plano carrega o do programa intacto antes do último hífen, e
    ainda economiza uma requisição por programa."""
    tapejara = plano_novo_para_linha(PLANO_3200, BENEFICIARIO_TAPEJARA, None, 7)
    assert tapejara["programa_codigo"] == "0903"          # e não "903"

    nova_palma = plano_novo_para_linha(PLANO_67457, BENEFICIARIO_NOVA_PALMA, None, 42)
    assert nova_palma["programa_codigo"] == "09032024-2"  # o sufixo faz parte


def test_o_parlamentar_vem_do_campo_proprio_e_nao_de_um_split():
    """A fonte antiga só tinha o código da emenda, e o nome saía de partir no
    primeiro '-'. A oficial tem o nome em campo próprio — que é o que vale
    quando o nome do parlamentar contém hífen."""
    linha = plano_novo_para_linha(PLANO_67457, BENEFICIARIO_NOVA_PALMA, None, 42)
    assert linha["parlamentar"] == "Heitor Schuch"


def test_sem_o_campo_proprio_ainda_cai_no_split_do_codigo_da_emenda():
    plano = {**PLANO_67457, "nome_parlamentar_emenda_plano_acao": None}
    linha = plano_novo_para_linha(plano, BENEFICIARIO_NOVA_PALMA, None, 42)
    assert linha["parlamentar"] == "Heitor Schuch"


# ---------------------------------------------------------------------------
# O QUE A TROCA DE FONTE NÃO PODE MUDAR
# ---------------------------------------------------------------------------

def test_a_chave_primaria_e_o_mesmo_id_das_duas_fontes():
    """⭐ Se os ids divergissem, o upsert por `plano_acao_id` criaria linha nova
    em vez de atualizar, e a tabela dobraria de tamanho na primeira rodada.
    Conferido na fonte: o plano que a SPA chamava de 3200 é o `id_plano_acao`
    3200 da API oficial, com o mesmo código e o mesmo valor."""
    linha = plano_novo_para_linha(PLANO_3200, BENEFICIARIO_TAPEJARA, None, 7)
    assert linha["plano_acao_id"] == 3200
    assert linha["codigo"] == "0903-003200"
    assert linha["valor_total"] == 70000.0


def test_o_municipio_vem_de_quem_chamou_e_nunca_do_nome_do_beneficiario():
    """O casamento por substring de nome era o defeito estrutural do coletor
    antigo (628 de 890 linhas com CNPJ divergente num tenant). Aqui o
    `municipio_id` é argumento: quem monta a linha já entrou pelo CNPJ."""
    linha = plano_novo_para_linha(PLANO_3200, BENEFICIARIO_TAPEJARA, None, 7)
    assert linha["municipio_id"] == 7
    assert linha["beneficiario_cnpj"] == "87615449000142"


def test_a_linha_tem_exatamente_as_colunas_do_upsert():
    """O upsert é compartilhado com a coleta assistida do control-plane. Uma
    chave a mais ou a menos aqui só apareceria como erro de bind em produção."""
    from ingestion.transferegov_te import UPSERT_SQL_NOMEADO
    import re
    esperadas = set(re.findall(r":(\w+)", UPSERT_SQL_NOMEADO))
    linha = plano_novo_para_linha(PLANO_67457, BENEFICIARIO_NOVA_PALMA, "APROVADO", 42)
    assert set(linha) == esperadas


def test_o_raw_data_guarda_a_fonte_nova_e_o_que_ela_nao_traz_junto():
    """`routers/transferegov.buscar` lê do raw os campos que não viraram coluna
    (`id_programa`, as áreas de política pública, o motivo do impedimento).
    Guardar o payload da fonte NOVA — e não uma tradução para o formato antigo —
    é o que evita uma tradução dupla que ninguém saberia justificar depois."""
    linha = plano_novo_para_linha(PLANO_67457, BENEFICIARIO_NOVA_PALMA, "APROVADO", 42)
    raw = json.loads(linha["raw_data"])
    assert raw["id_programa"] == 21
    assert raw["codigo_descricao_areas_politicas_publicas_plano_acao"].startswith("27-Desporto")
    assert raw["_beneficiario"]["cnpj_beneficiario"] == "88488358000156"
    assert raw["_situacao_plano_trabalho"] == "APROVADO"


def test_plano_sem_id_e_descartado_e_nao_quebra_a_rodada():
    assert plano_novo_para_linha({}, BENEFICIARIO_NOVA_PALMA, None, 42) is None


# ---------------------------------------------------------------------------
# A REGRESSÃO QUE IMPORTA: o RM tem de classificar igual
# ---------------------------------------------------------------------------

def test_o_RM_classifica_o_plano_traduzido_como_classificava_antes():
    """⭐ O TESTE DE PONTA A PONTA DA TROCA DE FONTE.

    Reproduz a decisão de estágio do `rm_builder` sobre uma linha montada a
    partir da API oficial, e prova que ela cai no MESMO ramo que caía com o dado
    da SPA — que é a única coisa que o cliente enxerga.
    """
    linha = plano_novo_para_linha(
        PLANO_3200, BENEFICIARIO_TAPEJARA,
        _situacao_pt_normalizada("Legado ADPF 854 STF / NT - TCU"), 7)

    # A mesma conta do rm_builder, sobre a linha que o coletor novo grava.
    sit = linha["situacao"] or ""
    sit_trab = linha["situacao_trabalho"] or ""
    avanco = ("empenh", "pag", "conclu", "finaliz", "execu")
    sit_efetivo = sit_trab if any(x in sit_trab.lower() for x in avanco) else sit

    assert sit_efetivo == "CONCLUIDO_NT_TCU"   # e NÃO "CIENTE"
    # E o texto exibido continua legível depois do replace que o RM faz.
    assert sit_trab.replace("_", " ") == "CONCLUIDO NT TCU"
