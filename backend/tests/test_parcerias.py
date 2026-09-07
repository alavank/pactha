"""Gestão de Parcerias do Transferegov.br — a fonte onde a emenda de saúde vive.

Os payloads são respostas REAIS de
`api-publica.transferegov.gestao.gov.br/parcerias`, capturadas em 07/09/2026 da
proposta 75376 de Nova Palma. O que se prova aqui é o que o diff não mostra: que
a proposta sem instrumento e sem emenda continua sendo gravada, que o valor sai
do campo certo entre os dois que a fonte oferece, e que a chave já nasce com o
município.
"""
import json

from ingestion.parcerias import _SQL, linha

# GET /parcerias/proposta?cd_ibge_recebedor=4313102
PROPOSTA = {
    "id_proposta": 75376, "id_programa": 121,
    "cnpj_ente_recebedor": "12240183000100",
    "nm_ente_recebedor": "FUNDO MUNICIPAL DA SAUDE",
    "nm_natureza_juridica": "Fundo Público da Administração Direta Municipal",
    "cd_ibge_recebedor": 4313102, "nm_municipio_recebedor": "NOVA PALMA",
    "sg_uf_recebedor": "RS",
    "ds_objeto": "AQUISIÇÃO DE EQUIPAMENTO E MATERIAL PERMANENTE PARA UNIDADE BÁSICA DE SAÚDE",
    "ds_problema_proposta": "Barreiras ao acesso oportuno e resolutivo à Atenção Primária",
    "ds_resultado_esperado_proposta": "Adequar a infraestrutura das Unidades Básicas de Saúde",
    "ds_publico_alvo_proposta": "N/A",
    "situacao_proposta": "Aprovada",
    "nr_vlr_total": None,                     # ⚠️ vem NULO na fonte
    "vl_total_planejamento_gastos": 299999.0,  # e o valor está aqui
    "ano_proposta": 2026, "mes_proposta": 5, "dt_proposta": "2026-05-13",
}
# GET /parcerias/parceria?id_proposta=75376
PARCERIA = {
    "id_parceria": 75161, "cd_parceria": 202600030157,
    "nu_externo": "12240183000126003", "id_proposta": 75376,
    "in_situacao_parceria": "Aprovada", "tp_origem": "Sistema Externo",
    "dh_assinatura": None,
}
# GET /parcerias/distribuicao-recurso-proposta?id_proposta=75376
EMENDA = {
    "id_distribuicao_recurso_proposta": 86929, "id_proposta": 75376,
    "id_beneficiario_emenda_parlamentar": 92001,
    "in_tipo_distribuicao": "Emenda", "in_tipo_gnd": "GND4",
    "nr_emenda_proposta": "2026.2023.0002",
    "nm_parlamentar_proposta": "PAULO PAIM",
    "in_tipo_emenda_parlamentar_proposta": "Individual",
    "valor_emenda": 299999.0,
}


def test_a_cadeia_completa_vira_uma_linha():
    """⭐ O QUE ESTA FONTE ENTREGA E QUE NÃO EXISTIA NO PRODUTO: a emenda de
    saúde com o parlamentar nomeado, ligada ao objeto e ao instrumento."""
    l = linha(42, PROPOSTA, PARCERIA, EMENDA)
    assert l["id_proposta"] == 75376
    assert l["mid"] == 42        # o nome do placeholder do SQL
    assert l["objeto"].startswith("AQUISIÇÃO DE EQUIPAMENTO")
    assert l["id_parceria"] == 75161
    assert l["nr_emenda"] == "2026.2023.0002"
    assert l["parlamentar"] == "PAULO PAIM"
    assert l["tipo_emenda"] == "Individual"
    assert l["vl_emenda"] == 299999.0


def test_o_valor_sai_do_campo_PREENCHIDO_entre_os_dois():
    """⚠️ A fonte tem dois campos de valor e o preenchido varia: `nr_vlr_total`
    veio NULO em todas as propostas medidas, e o número está em
    `vl_total_planejamento_gastos`. Ler só o primeiro deixaria a tela com uma
    carteira de R$ 0,00 — e sem erro nenhum em log."""
    l = linha(42, PROPOSTA, PARCERIA, EMENDA)
    assert l["valor"] == 299999.0

    # E quando a fonte inverte, o outro campo vale.
    invertida = {**PROPOSTA, "vl_total_planejamento_gastos": None,
                 "nr_vlr_total": 12345.0}
    assert linha(42, invertida, None, None)["valor"] == 12345.0


def test_proposta_sem_instrumento_e_sem_emenda_continua_sendo_gravada():
    """Proposta em elaboração não tem parceria celebrada, e proposta de programa
    voluntário não tem emenda. Os dois são estado legítimo: descartar a linha
    perderia o objeto e o valor, que já valem a tela."""
    l = linha(42, PROPOSTA, None, None)
    assert l is not None
    assert l["id_parceria"] is None
    assert l["nr_emenda"] is None
    assert l["objeto"]           # o que interessa continua lá
    assert l["valor"] == 299999.0


def test_o_recebedor_e_o_FUNDO_e_nao_a_prefeitura():
    """⭐ POR QUE ESTA FONTE NÃO PODE ENTRAR POR CNPJ. As 11 propostas de Nova
    Palma são todas do FUNDO MUNICIPAL DA SAUDE (12240183000100), diferente do
    CNPJ da prefeitura (88488358000156). Um coletor que casasse por
    `municipios.cnpj` — como o da Transferência Especial faz, e com razão lá —
    não acharia nenhuma. O vínculo vem do `cd_ibge_recebedor` da fonte."""
    l = linha(42, PROPOSTA, PARCERIA, EMENDA)
    assert l["cnpj"] == "12240183000100"
    assert l["cnpj"] != "88488358000156"
    assert "FUNDO" in l["ente"]


def test_o_codigo_da_parceria_vira_texto():
    """`cd_parceria` chega como inteiro de 12 dígitos (202600030157). Gravar como
    número convidaria a soma e a formatação com separador de milhar — é um
    código, não uma quantidade."""
    l = linha(42, PROPOSTA, PARCERIA, EMENDA)
    assert l["cd_parceria"] == "202600030157"
    assert isinstance(l["cd_parceria"], str)


def test_a_chave_do_upsert_ja_nasce_com_o_municipio():
    """⚠️ `add_obrasgov.sql` deixou a chave global e teve de trocá-la depois:
    numa carteira de assessoria o mesmo instrumento pode pertencer a mais de um
    município, e a última gravação apagava as outras. Aqui já nasce certo."""
    assert "ON CONFLICT (municipio_id, id_proposta)" in _SQL


def test_a_linha_tem_exatamente_as_colunas_do_upsert():
    """Uma chave a mais ou a menos só apareceria como erro de bind em produção."""
    import re
    esperadas = set(re.findall(r"%\((\w+)\)s", _SQL))
    assert set(linha(42, PROPOSTA, PARCERIA, EMENDA)) == esperadas


def test_proposta_sem_id_e_descartada_sem_quebrar_a_rodada():
    assert linha(42, {}, None, None) is None


def test_o_raw_guarda_os_tres_pedacos_da_cadeia():
    """A proposta, o instrumento e a emenda vêm de três consultas diferentes; o
    raw guarda os três para o que não virou coluna continuar recuperável."""
    l = linha(42, PROPOSTA, PARCERIA, EMENDA)
    raw = json.loads(l["raw"])
    assert raw["id_proposta"] == 75376
    assert raw["_parceria"]["id_parceria"] == 75161
    assert raw["_emenda"]["nm_parlamentar_proposta"] == "PAULO PAIM"


def test_a_fonte_entrou_no_monitor_de_frescor():
    """⚠️ REGRA DO REPO, escrita em `routers/freshness.py`: fonte que coleta sem
    aparecer no monitor pode parar por meses sem ninguém ver — foi assim que
    `siconv_federal` ficou zerado em dois tenants."""
    from routers.freshness import _SOURCES
    fontes = [s for s in _SOURCES if s[2] == "parcerias"]
    assert len(fontes) == 1
    assert "parcerias_propostas" in fontes[0][1]
