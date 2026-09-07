"""Fundo a Fundo do Transferegov.br — o plano de ação por trás do repasse.

Payloads reais de `api-publica.transferegov.gestao.gov.br/fundoafundo`,
capturados em 07/09/2026 do plano 1617 de Nova Palma. O que se prova aqui é o que
o diff não mostra: que o caminho de entrada contorna um filtro quebrado da
própria fonte, que a decomposição do valor sobrevive, e que uma rodada que não
conseguiu buscar os relatórios não apaga os que já estavam gravados.
"""
import json

from ingestion.faf_planos import _SQL, linha

# GET /fundoafundo/planos-acao?cnpj_ente_recebedor_plano_acao=88488358000156
PLANO = {
    "id_plano_acao": 1617, "codigo_plano_acao": "30882120200002-001617",
    "id_programa": 8,
    "data_inicio_vigencia_plano_acao": "2020-08-10",
    "data_fim_vigencia_plano_acao": "2020-12-31",
    "diagnostico_plano_acao": "Para recebimento dos recursos previstos na Lei 14017/2020",
    "objetivos_plano_acao": "Receber os recursos da Lei Aldir Blanc 14.017/2020",
    "situacao_plano_acao": "AUTORIZADO",
    "valor_repasse_emenda_plano_acao": 0.0,
    "valor_repasse_especifico_plano_acao": 60765.92,
    "valor_repasse_voluntario_plano_acao": 0.0,
    "valor_total_repasse_plano_acao": 60765.92,
    "valor_recursos_proprios_plano_acao": 0.0,
    "valor_rendimentos_aplicacao_plano_acao": 0.0,
    "valor_total_plano_acao": 60765.92,
    "valor_total_investimento_plano_acao": 0.0,
    "valor_total_custeio_plano_acao": 60765.92,
    "valor_saldo_disponivel_plano_acao": 0.0,
    "sigla_orgao_repassador_plano_acao": "MinC",
    "nome_orgao_repassador_plano_acao": "Ministério da Cultura",
    "nome_fundo_repassador_plano_acao": "FUNDO NACIONAL DA CULTURA",
    "cnpj_ente_recebedor_plano_acao": "88488358000156",
    "nome_ente_recebedor_plano_acao": "MUNICIPIO DE NOVA PALMA",
    "codigo_ibge_municipio_ente_recebedor_plano_acao": 4313102,
    "tipo_unidade_recebedora_plano_acao": "ENTE",
}
RELATORIOS = [{
    "id_relatorio_gestao": "1", "tipo_relatorio_gestao": "FINAL",
    "situacao_relatorio_gestao": "ENVIADO_ANALISE",
    "valor_executado_relatorio_gestao": 60765.92,
    "valor_pendente_relatorio_gestao": 0.0,
    "declaracao_conformidade_relatorio_gestao": True,
    "id_plano_acao": "1617",
}]


def test_a_decomposicao_do_valor_e_o_que_esta_fonte_acrescenta():
    """⭐ O `fns_repasse_faf` já conta quanto ENTROU por bloco. Só aqui se sabe
    de onde veio: emenda, repasse específico, voluntário, recursos próprios e
    rendimentos são campos separados na fonte."""
    l = linha(42, PLANO, RELATORIOS)
    assert l["vl_total"] == 60765.92
    assert l["vl_especifico"] == 60765.92
    assert l["vl_emenda"] == 0.0        # este plano não veio de emenda
    assert l["vl_custeio"] == 60765.92
    assert l["vl_investimento"] == 0.0
    assert l["vl_saldo"] == 0.0


def test_nao_e_so_saude():
    """O nome "fundo a fundo" sugere SUS, mas o módulo cobre todo repasse
    fundo a fundo: os quatro planos de Nova Palma são do Ministério da Cultura
    (Lei Aldir Blanc), com o Fundo Nacional da Cultura como repassador. Um
    coletor que filtrasse por saúde perderia os quatro."""
    l = linha(42, PLANO, RELATORIOS)
    assert l["sigla_orgao"] == "MinC"
    assert "CULTURA" in l["fundo"]


def test_o_texto_que_justifica_o_plano_sobrevive():
    """`diagnostico` e `objetivos` são o conteúdo que o RM pode citar, e o
    ConsultaFNS não publica nenhum dos dois."""
    l = linha(42, PLANO, RELATORIOS)
    assert "14017/2020" in l["diagnostico"]
    assert "Aldir Blanc" in l["objetivos"]


def test_a_prestacao_de_contas_vira_dado_estruturado():
    """⚠️ Preenche um buraco conhecido do modelo: `prestacao_contas` é DROPADA a
    cada boot (`drop_lean_tables.sql`), e hoje prestação de contas só existe como
    texto dentro de um campo de situação."""
    l = linha(42, PLANO, RELATORIOS)
    rel = json.loads(l["relatorios"])
    assert rel[0]["valor_executado_relatorio_gestao"] == 60765.92
    assert rel[0]["declaracao_conformidade_relatorio_gestao"] is True


def test_sem_relatorio_a_coluna_fica_NULA_e_nunca_vazia():
    """Lista vazia no banco seria indistinguível de "coletei e não há". Nulo diz
    "não medido" — e é o que permite o COALESCE do upsert funcionar."""
    assert linha(42, PLANO, None)["relatorios"] is None
    assert linha(42, PLANO, [])["relatorios"] is None


def test_a_rodada_sem_relatorio_NAO_apaga_o_que_ja_estava_gravado():
    """⭐ O COALESCE do upsert. A busca dos relatórios é a parte cara e a
    primeira a falhar quando a fonte está lenta; sem esta proteção, uma rodada
    ruim apagaria a prestação de contas de todos os planos — em silêncio, porque
    gravar NULL sobre dado não levanta erro."""
    assert "coalesce(EXCLUDED.relatorios_gestao" in _SQL


def test_os_ids_viram_texto():
    """`id_plano_acao` e `id_programa` chegam ora como int, ora como str na
    família de APIs (o módulo de Especiais manda int, este manda os dois).
    Normalizar para texto evita que a mesma linha entre duas vezes com chaves
    "1617" e 1617."""
    l = linha(42, PLANO, RELATORIOS)
    assert l["id_plano"] == "1617"
    assert isinstance(l["id_plano"], str)
    assert l["id_programa"] == "8"


def test_plano_sem_id_e_descartado():
    assert linha(42, {}, None) is None
    assert linha(42, {"id_plano_acao": ""}, None) is None


def test_a_chave_do_upsert_ja_nasce_com_o_municipio():
    assert "ON CONFLICT (municipio_id, id_plano_acao)" in _SQL


def test_a_linha_tem_exatamente_as_colunas_do_upsert():
    import re
    esperadas = set(re.findall(r"%\((\w+)\)s", _SQL))
    assert set(linha(42, PLANO, RELATORIOS)) == esperadas


def test_a_fonte_entrou_no_monitor_de_frescor():
    from routers.freshness import _SOURCES
    fontes = [s for s in _SOURCES if s[2] == "faf_planos"]
    assert len(fontes) == 1
    assert "faf_planos_acao" in fontes[0][1]


def test_o_caminho_de_entrada_contorna_o_filtro_quebrado_da_fonte():
    """⚠️ `/planos-acao?codigo_ibge_municipio_ente_recebedor_plano_acao=` está no
    Swagger e devolve **HTTP 500** — medido em 06 e 07/09/2026, dias diferentes.
    Por isso o coletor descobre os CNPJs por `/programas-beneficiarios` (cujo
    filtro por IBGE funciona) e só então busca os planos.

    E o CNPJ não pode ser adivinhado: aqui o ente é a PREFEITURA
    (88488358000156), enquanto no módulo de Parcerias as propostas do mesmo
    município são todas do FUNDO MUNICIPAL DA SAUDE (12240183000100)."""
    import inspect
    from ingestion.faf_planos import cnpjs_do_municipio
    fonte = inspect.getsource(cnpjs_do_municipio)
    assert "programas-beneficiarios" in fonte
    assert "cnpj_beneficiario_programa" in fonte
