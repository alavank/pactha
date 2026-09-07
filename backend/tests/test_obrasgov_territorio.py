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
# ⚠️⚠️ ESTE PAYLOAD ESTAVA ERRADO, E POR ISSO O TESTE PASSAVA COM O BUG.
# A primeira versão escreveu `percentual_execucao` — o nome que o COLETOR usava,
# não o que a fonte manda. O campo real é `percentual_execucao_FISICA`, e o
# resultado foi `percentual_execucao` NULO em 538 de 538 obras do freitas por
# três dias, sem erro em log nenhum: `.get()` de chave inexistente devolve None,
# indistinguível de "a fonte não mediu esta obra".
#
# A lição: payload de teste se captura da FONTE, não se deduz do código que se
# quer testar. Estes são de uma resposta real de 07/09/2026.
EXECUCAO = [
    {"id_projeto_investimento": "X", "percentual_execucao_fisica": 35.5,
     "dt_cadastro_execucao": "2024-11-06T00:00:00"},
    {"id_projeto_investimento": "X", "percentual_execucao_fisica": 62.0,
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


def test_5xx_transitorio_nao_derruba_a_rodada_inteira():
    """⭐ DEFEITO MEDIDO EM PRODUÇÃO, DUAS VEZES, no montesião:

        06/09 03:18  500 Internal Server Error  na página 63 de MG
        07/09 02:48  502 Bad Gateway            na página 12 de MG

    Nos dois casos a rodada registrou `error` com ZERO gravados — a varredura
    inteira perdida por um soluço de uma página, porque `raise_for_status()`
    levantava e a exceção subia até o `except` do `ingest`.

    5xx é transitório por definição e merece o mesmo backoff que o 429. O que
    continua levantando é 4xx: 404 ou 422 significam que NÓS pedimos errado, e
    insistir não conserta.

    ⚠️ A fase de detalhe multiplicou a exposição: a rodada passou de ~75s para
    ~8-10 min e de dezenas para mais de mil páginas."""
    from ingestion.obrasgov import _STATUS_RETENTAVEIS
    for transitorio in (429, 500, 502, 503, 504):
        assert transitorio in _STATUS_RETENTAVEIS
    for nosso_erro in (400, 404, 422):
        assert nosso_erro not in _STATUS_RETENTAVEIS


def test_os_dois_caminhos_de_requisicao_usam_o_mesmo_retry():
    """A varredura por UF e a fase de detalhe/geometria entravam por funções
    diferentes, e só uma tinha backoff. Um retry que protege metade do coletor
    não protege o coletor."""
    import inspect
    from ingestion.obrasgov import _pagina_de, pagina
    assert "_get_com_retry" in inspect.getsource(pagina)
    assert "_get_com_retry" in inspect.getsource(_pagina_de)


# ---------------------------------------------------------------------------
# ⚠️ O GUARDA-CHUVA ERA 96% DO VALOR DA TELA (07/09/2026).
#
# O coletor já marcava `abrangencia` desde o #408 — o que faltava era a leitura
# respeitar a marca. Medido no freitas:
#
#     abrangencia    56 obras   R$ 15.894.300.865   ← 96% do valor
#     prefeitura    421 obras   R$    606.809.018
#     territorio     61 obras   R$     91.560.948
#
# É o MESMO projeto repetido: "Manutenção rodoviária na malha federal do DNIT em
# MG" (R$ 383,3 mi, 790 municípios) cai em 41 das 42 cidades da carteira, e cada
# uma somava os R$ 383 mi inteiros como se fossem obra da cidade.
# ---------------------------------------------------------------------------

from routers.obrasgov import conta_no_total


def test_o_guarda_chuva_fica_fora_da_conta_do_municipio():
    assert conta_no_total("abrangencia") is False


def test_a_obra_no_territorio_CONTA():
    """⚠️ Ela é uma obra só, naquele lugar, e quem diz é o Governo
    (`/geometria?cod_ibge=`). O dono ser a UFSM ou o DNIT não a torna menos real
    para quem mora na cidade — a tela diz de quem é pelo selo."""
    assert conta_no_total("territorio") is True


def test_a_obra_da_prefeitura_conta():
    assert conta_no_total("prefeitura") is True


def test_vinculo_ausente_conta_como_prefeitura():
    """Linha gravada antes do #408 tem `vinculo` nulo, e sumir dos totais num
    deploy seria a tela encolher sem explicação."""
    assert conta_no_total(None) is True
    assert conta_no_total("") is True


def test_a_resposta_diz_quanto_ficou_de_fora():
    """Silêncio aqui faria a contagem não bater para quem conferisse contra o
    portal — a tela precisa poder dizer «56 programas, não somados»."""
    import inspect
    from routers.obrasgov import fetch_obras_federais
    fonte = inspect.getsource(fetch_obras_federais)
    assert '"guarda_chuva"' in fonte


def test_a_tela_usa_a_mesma_regra_do_router():
    """⚠️ A tela recalcula os totais dos cartões a partir das listas filtradas
    (de propósito — cartão dizendo 360 com 12 obras na lista faz o gestor
    desconfiar do resto). Então a regra do servidor não basta: se o filtro do
    cliente não excluir o guarda-chuva, os R$ 15,89 bi voltam pelos cartões."""
    from pathlib import Path
    tela = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "app"
            / "dashboard" / "obrasgov" / "page.tsx").read_text(encoding="utf-8")
    assert 'o.vinculo !== "abrangencia"' in tela
    assert "Programas que passam pelo município" in tela


# ---------------------------------------------------------------------------
# ⚠️ OS NOMES DOS CAMPOS DA FONTE, TRAVADOS (07/09/2026).
#
# `.get("nome_errado")` devolve `None` sem reclamar, e `None` nesta base
# significa "a fonte não informou" — então um erro de digitação vira um campo
# permanentemente vazio que ninguém percebe. Foi o que aconteceu com
# `percentual_execucao` vs `percentual_execucao_fisica`.
#
# Esta lista é o contrato observado na resposta real. Se a fonte renomear (o
# Obras.gov já renomeou TODOS os campos numa troca de host), o teste não pega
# sozinho — mas quem mexer no coletor tem aqui, escrito, o nome que a fonte usa.
# ---------------------------------------------------------------------------

CAMPOS_DA_FONTE = {
    "execucao-fisica": {"id_projeto_investimento", "id_execucao_fisica",
                        "percentual_execucao_fisica", "dt_inicial_execucao",
                        "dt_final_execucao", "dt_cadastro_execucao",
                        "dt_atualizacao_execucao"},
    "empenho": {"valor_empenho", "liquidado", "pago", "rpinscrito"},
}


def test_os_nomes_dos_campos_lidos_existem_na_fonte():
    """O coletor só pode ler chave que a fonte manda."""
    import inspect
    from ingestion import obrasgov
    fonte = inspect.getsource(obrasgov.linha_detalhe)
    for campo in ("percentual_execucao_fisica", "dt_cadastro_execucao",
                  "valor_empenho", "liquidado", "pago", "rpinscrito"):
        assert campo in fonte, f"{campo} sumiu de linha_detalhe"
    # ⚠️ E o nome ERRADO não pode voltar. `percentual_execucao` é prefixo do
    # certo, então a checagem é por delimitador.
    assert '"percentual_execucao")' not in fonte, (
        "voltou o nome sem o sufixo _fisica — o campo ficaria NULO em tudo")


def test_a_medicao_mais_recente_usa_o_campo_certo():
    """Prova de ponta a ponta com o payload real: 62,0% e não None."""
    from ingestion.obrasgov import linha_detalhe
    l = linha_detalhe("X", {"execucao": EXECUCAO})
    assert l["pct"] == 62.0, "o percentual voltou a sair NULO"


def test_payload_com_o_nome_ANTIGO_nao_preenche():
    """⚠️ O contrário do teste acima, e é ele que documenta o defeito: se a
    fonte mandasse o nome antigo, a coluna ficaria nula — e era exatamente esse
    o estado em produção."""
    from ingestion.obrasgov import linha_detalhe
    antigo = [{"percentual_execucao": 62.0, "dt_cadastro_execucao": "2025-06-30"}]
    assert linha_detalhe("X", {"execucao": antigo})["pct"] is None
