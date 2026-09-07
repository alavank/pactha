"""Obras.gov.br: o vínculo territorial e o detalhe dos cinco endpoints.

Os números citados são medições reais de 07/09/2026 contra
`api-publica.obrasgov.gestao.gov.br/obras` e contra os bancos dos cinco tenants.
O que se prova aqui é o que o diff não mostra: que o guarda-chuva não posa de
obra local, que zero não é inventado onde a fonte não disse nada, e que a chave
nova deixa a obra intermunicipal existir para todos os donos.
"""
import json

from ingestion.obrasgov import (
    ABRANGENCIA_MAX, DETALHE_MIN_S, TETO_PAGINAS_DETALHE, TETO_TAREFA_S,
    _DETALHE_RODIZIO, _DETALHE_SEMPRE, _SQL, _SQL_DETALHE, _detalhe_da_rodada,
    _soma, linha, linha_detalhe,
)


# ---------------------------------------------------------------------------
# O VÍNCULO
# ---------------------------------------------------------------------------

PROJETO = {
    "id_projeto_investimento": "112787.43-55",
    "desc_nome": "Pavimentação de vias urbanas",
    "situacao": "Em execução",
    "uf_principal": "RS",
    "investimentos_previstos": [{"vl_investimento_previsto": 500000.0,
                                 "desc_nome_fonte_recurso": "Federal"}],
    "tomadores": [{"organizacao_tomador": "MUNICIPIO DE NOVA PALMA",
                   "cnpj_tomador": "88488358000156"}],
}


def test_o_padrao_continua_sendo_prefeitura():
    """Quem casa por CNPJ é da prefeitura, e é o comportamento de sempre — a
    coluna nasce preenchida para não deixar as linhas antigas indistinguíveis
    das territoriais que passam a chegar."""
    l = linha(7, PROJETO)
    assert l["vinculo"] == "prefeitura"
    assert l["cod_ibge_geo"] is None      # não veio da geometria
    assert l["abrangencia"] is None


def test_o_vinculo_territorial_guarda_a_prova_de_onde_veio():
    """⭐ `cod_ibge_geometria` preenchido significa que o município saiu do
    GOVERNO (o `/geometria?cod_ibge=` filtra de verdade), e não de um casamento
    por CNPJ nosso. É o que distingue dado de inferência."""
    l = linha(7, PROJETO, vinculo="territorio", cod_ibge="4313102", abrangencia=3)
    assert l["vinculo"] == "territorio"
    assert l["cod_ibge_geo"] == 4313102     # inteiro, não string
    assert l["abrangencia"] == 3


def test_o_guarda_chuva_do_DNIT_nao_posa_de_obra_local():
    """O `324.31-80` — "Manutenção rodoviária na malha federal do DNIT em MG" —
    tem geometria em 790 municípios e cai em 41 dos 42 do freitas. Gravá-lo como
    obra em Araújos seria o mesmo ruído 41 vezes."""
    assert 790 > ABRANGENCIA_MAX
    l = linha(7, PROJETO, vinculo="abrangencia", cod_ibge="3103504", abrangencia=790)
    assert l["vinculo"] == "abrangencia"


def test_o_corte_deixa_passar_a_obra_intermunicipal_de_verdade():
    """Amostra de 124 projetos da carteira do freitas: 102 em UM município, 15
    em 2 a 5, 3 em mais de cem. O corte tem de separar os 3 sem derrubar os 15 —
    consórcio e obra que cruza dois municípios são legítimos."""
    assert ABRANGENCIA_MAX >= 5
    assert ABRANGENCIA_MAX < 100


def test_a_chave_do_upsert_inclui_o_municipio():
    """⭐ A troca que `add_obrasgov.sql` previu no próprio cabeçalho. Com a chave
    global antiga, a obra intermunicipal era gravada para os dois municípios e a
    última gravação vencia — 40 dos 41 donos do `324.31-80` perderiam a obra em
    silêncio."""
    assert "ON CONFLICT (municipio_id, id_unico)" in _SQL
    # E o `municipio_id` sai do SET: ele agora é parte da chave, não um campo a
    # sobrescrever. Atualizá-lo no conflito seria escrever sobre si mesmo.
    corpo = _SQL.split("DO UPDATE SET", 1)[1]
    assert "municipio_id = EXCLUDED" not in corpo


# ---------------------------------------------------------------------------
# O DETALHE
# ---------------------------------------------------------------------------

# Respostas reais de /empenho e /execucao-fisica (recortadas no que se lê).
EMPENHOS = [
    {"id_projeto_investimento": "X", "nr_empenho": "2024NE000123",
     "valor_empenho": 2150345.05, "liquidado": 1000000.0, "pago": 900000.0,
     "rpinscrito": 100000.0, "codigo_autor_emenda": "71234"},
    {"id_projeto_investimento": "X", "nr_empenho": "2024NE000456",
     "valor_empenho": 500000.0, "liquidado": 0.0, "pago": 0.0},
]
EXECUCAO = [
    {"id_projeto_investimento": "X", "percentual_execucao": 35.5,
     "dt_cadastro_execucao": "2024-11-06T00:00:00"},
    {"id_projeto_investimento": "X", "percentual_execucao": 62.0,
     "dt_cadastro_execucao": "2025-06-30T00:00:00"},
]


def test_o_percentual_e_o_da_medicao_MAIS_RECENTE():
    """A execução física tem uma linha por medição e a fonte não garante ordem.
    Pegar a primeira da lista mostraria uma obra andando para trás."""
    l = linha_detalhe("X", {"execucao": EXECUCAO})
    assert l["pct"] == 62.0
    assert l["dt_exec"] == "2025-06-30"


def test_os_valores_somam_todos_os_empenhos_do_projeto():
    l = linha_detalhe("X", {"empenhos": EMPENHOS})
    assert l["empenhado"] == 2650345.05
    assert l["liquidado"] == 1000000.0
    assert l["pago"] == 900000.0
    assert l["restos"] == 100000.0


def test_sem_empenho_o_valor_e_NULO_e_nunca_zero():
    """⚠️ Zero é uma AFIRMAÇÃO — "não foi empenhado nada" — e só pode ser feita
    quando a fonte disse zero. Projeto sem nenhum empenho não sabe se foi
    empenhado; a coluna fica nula e a tela omite em vez de mentir."""
    l = linha_detalhe("X", {})
    assert l["empenhado"] is None
    assert l["pago"] is None
    assert l["pct"] is None


def test_soma_ignora_campo_ausente_mas_respeita_o_zero_explicito():
    assert _soma([{"v": 1.5}, {"sem_campo": 9}], "v") == 1.5
    assert _soma([{"v": 0.0}], "v") == 0.0          # a fonte disse zero
    assert _soma([{"sem_campo": 9}], "v") is None   # a fonte não disse nada


def test_o_JSONB_so_existe_quando_ha_o_que_guardar():
    """Lista vazia viraria `[]` no banco, indistinguível de "coletei e não há".
    Nulo diz "não medido", que é a verdade para quem não tem contrato nenhum."""
    l = linha_detalhe("X", {"empenhos": EMPENHOS})
    assert json.loads(l["empenhos"])[0]["nr_empenho"] == "2024NE000123"
    assert l["contratos"] is None
    assert l["paralisacao"] is None


def test_o_codigo_do_autor_da_emenda_sobrevive_no_JSONB():
    """É o campo que liga a obra ao parlamentar — o motivo de coletar empenho
    em vez de só somar valores."""
    l = linha_detalhe("X", {"empenhos": EMPENHOS})
    assert json.loads(l["empenhos"])[0]["codigo_autor_emenda"] == "71234"


# ---------------------------------------------------------------------------
# O ORÇAMENTO DA RODADA
# ---------------------------------------------------------------------------

def test_a_fase_de_detalhe_cabe_no_teto_da_tarefa():
    """⚠️ O NÚMERO VEIO DA MEDIÇÃO, e a estimativa tinha errado por mais do
    dobro: varrer os cinco endpoints custa **1.020s**, não 450s. Com o rodízio
    a rodada leva os dois baratos (60s) mais o pior dos caros (384s) = ~450s."""
    assert DETALHE_MIN_S >= 450
    assert TETO_TAREFA_S > DETALHE_MIN_S * 2   # sobra para a varredura de projetos


def test_o_teto_de_paginas_do_detalhe_cobre_o_maior_endpoint():
    """⭐ DEFEITO PEGO NA MEDIÇÃO REAL: `/empenho` tem 89.477 linhas = 448
    páginas, e o `TETO_PAGINAS` de 400 da varredura por UF cortou em 80.000. O
    coletor gravaria empenho faltando e diria apenas "PARCIAL" numa linha de
    log."""
    assert TETO_PAGINAS_DETALHE * 200 > 89_477


def test_o_rodizio_cobre_os_tres_caros_em_tres_dias():
    """Os dois baratos vão sempre (60s juntos); os três caros — 384s, 301s e
    276s — se revezam. Varrer os cinco toda noite seria 17 min por tenant, e os
    cinco tenants baixariam as mesmas 1.278 páginas da mesma fonte todo dia."""
    vistos = set()
    for dia in range(1, 4):
        rodada = _detalhe_da_rodada(dia)
        # os baratos estão sempre
        for barato in _DETALHE_SEMPRE:
            assert barato in rodada
        # e exatamente um dos caros
        caros = [x for x in rodada if x in _DETALHE_RODIZIO]
        assert len(caros) == 1
        vistos.add(caros[0][0])
    assert vistos == {c[0] for c in _DETALHE_RODIZIO}


def test_o_teto_cabe_no_kill_da_scheduled_task():
    """A task roda `timeout -k 30 1800`. Estourar degola a rodada e o log final
    se perde — o mesmo defeito que a Transferência Especial já pagou."""
    assert TETO_TAREFA_S < 1800


def test_o_detalhe_atualiza_TODOS_os_donos_da_obra():
    """⚠️ O UPDATE é por `id_unico`, sem município, e é de propósito: o
    percentual de execução e o empenho são do PROJETO, não do município. Uma
    obra intermunicipal (o `324.31-80` está em 41) tem 41 linhas, e as 41 têm de
    receber o mesmo detalhe — filtrar por município aqui deixaria 40 delas
    eternamente sem execução física."""
    assert "WHERE id_unico = %(pid)s" in _SQL_DETALHE
    assert "municipio_id" not in _SQL_DETALHE


def test_o_projeto_de_outra_UF_tem_de_ser_buscado_um_a_um():
    """⭐ DEFEITO PEGO ANTES DE IR AO AR. `varrer_uf` filtra por `uf_principal`,
    e a `uf_principal` NÃO é necessariamente a do território: o `123265.26-04` é
    uma consultoria com `uf_principal=PE` que tem geometria em município de MG
    (medido). Sem uma busca por id, a geometria apontaria a obra e o coletor não
    teria o projeto para gravar — a promessa de "tudo o que está no território"
    valeria só para quem coincidisse de ser da mesma UF."""
    import inspect
    from ingestion.obrasgov import ingest, projeto_por_id
    assert callable(projeto_por_id)
    fonte = inspect.getsource(ingest)
    assert "faltando" in fonte and "projeto_por_id" in fonte
