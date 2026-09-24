"""A emenda de saude (FNS) aparece sob o PARLAMENTAR AUTOR, nas duas telas.

⚠️ POR QUE EXISTE. Em 04/09/2026 o dono relatou: o parlamentar Igor Timo tinha
duas emendas em Nova Serrana (a Transferencia Especial "Pavimentacao" R$792k e a
emenda de saude "Incremento pap" R$400k), mas a aba Parlamentares mostrava so
uma. Medido em producao: a "Incremento pap" ESTAVA no banco e no RM, mas o autor
NAO estava em nenhum campo de nivel raiz do raw_data (noAutor/responsaveis/
parlamentar, todos vazios para FNS) — ele mora ANINHADO em
`raw_data.linhaPropostas[].parlamentares[]`. A tela de Parlamentares e a aba do
BI liam so o raiz (e o BI ainda EXCLUIA FNS de proposito), entao a emenda de
saude sumia por parlamentar. O RM ja descia ate o aninhamento — por isso o
relatorio mostrava e as telas nao.

A extracao virou UMA funcao (nome_parlamentar.emendas_saude_por_autor) que o
router de Parlamentares (usado tambem pelo Painel) e o BI chamam, para as tres
superficies nunca divergirem — mesma disciplina do resto de nome_parlamentar.py.
"""
import json

from services.nome_parlamentar import emendas_saude_por_autor, propostas_saude_por_autor


def test_extrai_o_parlamentar_aninhado():
    """O caso do Igor Timo: autor em linhaPropostas[].parlamentares[]."""
    props = [{"nuProposta": "1", "vlProposta": 400000.0,
              "parlamentares": [{"noApelidoPolitico": "Igor Timo"}]}]
    assert emendas_saude_por_autor(props) == [("Igor Timo", 400000.0)]


def test_precedencia_dos_campos_de_nome():
    """noApelidoPolitico > noParlamentar > nome — a MESMA do RM."""
    assert emendas_saude_por_autor(
        [{"vlProposta": 1000, "parlamentares": [
            {"noApelidoPolitico": "Apelido", "noParlamentar": "Formal", "nome": "Civil"}]}]
    ) == [("Apelido", 1000.0)]
    assert emendas_saude_por_autor(
        [{"vlProposta": 1000, "parlamentares": [{"noParlamentar": "Formal", "nome": "Civil"}]}]
    ) == [("Formal", 1000.0)]
    assert emendas_saude_por_autor(
        [{"vlProposta": 1000, "parlamentares": [{"nome": "Civil"}]}]
    ) == [("Civil", 1000.0)]


def test_proposta_sem_autor_vira_None_para_o_fundo():
    """Sem parlamentar real, o chamador cai no Fundo Municipal — o valor NUNCA
    se perde, que era o unico acerto do bloco antigo."""
    assert emendas_saude_por_autor(
        [{"vlProposta": 250000.0, "parlamentares": []}]) == [(None, 250000.0)]
    assert emendas_saude_por_autor(
        [{"vlProposta": 250000.0}]) == [(None, 250000.0)]  # sem a chave
    # "Não há" e marcador de ausencia do portal, nao pessoa -> cai no fundo.
    assert emendas_saude_por_autor(
        [{"vlProposta": 9, "parlamentares": [{"noApelidoPolitico": "Não há"}]}]) == [(None, 9.0)]


def test_varios_autores_rateiam_por_parlamentar():
    """Emenda com 2 autores conta para os 2 — a semantica de agregacao por autor
    (a mesma emenda aparece nos dois nomes, cada um com o valor da proposta)."""
    # ⚠️ Nomes com >= 3 chars de proposito: `e_parlamentar_real` tem piso de 3
    # (descarta inicial solta e lixo de parsing). Um fixture com "A"/"B" reprovaria
    # por esse piso, nao por defeito — foi o escorregao da primeira versao.
    r = emendas_saude_por_autor(
        [{"vlProposta": 100000.0, "parlamentares": [{"nome": "Ana Silva"}, {"nome": "Bruno Costa"}]}])
    assert ("Ana Silva", 100000.0) in r and ("Bruno Costa", 100000.0) in r and len(r) == 2


def test_string_json_e_lixo_nao_quebram():
    """A coluna chega como jsonb (lista) OU string, dependendo do driver; e uma
    linha FNS antiga pode nem ter `linhaPropostas`. Nenhum caso pode derrubar a
    agregacao — o defeito antigo era justamente uma excecao calada."""
    props = [{"vlProposta": 5, "parlamentares": [{"nome": "José Lima"}]}]
    assert emendas_saude_por_autor(json.dumps(props)) == [("José Lima", 5.0)]
    assert emendas_saude_por_autor(None) == []
    assert emendas_saude_por_autor("nao e json") == []
    assert emendas_saude_por_autor(42) == []
    # sem vlProposta -> valor 0.0, mas o autor entra (nome >= 3 chars).
    assert emendas_saude_por_autor([{"parlamentares": [{"nome": "Xico Rocha"}]}]) == [("Xico Rocha", 0.0)]


def test_as_duas_telas_usam_a_MESMA_funcao():
    """⚠️ O requisito do dono: "outro na mesma regra". Router (que o Painel
    reusa) e BI chamam a mesma extracao — se um parar de chamar, volta a
    divergir do outro e do RM."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    for rel in ("routers/parlamentares.py", "services/bi_abas.py"):
        src = (raiz / rel).read_text(encoding="utf-8")
        assert "emendas_saude_por_autor" in src, f"{rel} deixou de usar a funcao compartilhada"


# ---------------------------------------------------------------------------
# DETALHE (drill-down): o card por PROPOSTA, sob o autor aninhado
# ---------------------------------------------------------------------------
# ⚠️ POR QUE EXISTE. Em 04/09/2026, ja com o #371 no ar, o dono relatou que a
# aba Parlamentares passou a CONTAR duas emendas do Igor Timo (o cabecalho e os
# chips), mas ao expandir o card da emenda de saude NAO aparecia. O agregado
# (bloco 6) descia no aninhamento; o `detalhe` casava so o rotulo do Fundo
# Municipal contra o nome buscado, entao um parlamentar real nunca batia. A
# terceira superficie do mesmo bug. `propostas_saude_por_autor` carrega os
# campos ricos (numero, situacao) que o card precisa e que a versao em tuplas
# nao tem; `emendas_saude_por_autor` passou a delegar nela, p/ a descida viver
# num lugar so.

def test_proposta_rica_traz_numero_situacao_e_valor():
    """O caso do detalhe: numero (nuProposta), situacao (situacao_desc), valor."""
    props = [{"nuProposta": "0932025", "vlProposta": 400000.0,
              "situacao_desc": "Em analise",
              "parlamentares": [{"noApelidoPolitico": "Igor Timo"}]}]
    assert propostas_saude_por_autor(props) == [
        {"autor": "Igor Timo", "valor": 400000.0, "numero": "0932025", "situacao": "Em analise"}]


def test_numero_cai_para_nuProcesso_quando_falta_nuProposta():
    r = propostas_saude_por_autor(
        [{"nuProcesso": "25000.111", "vlProposta": 10, "parlamentares": [{"nome": "Ana Silva"}]}])
    assert r == [{"autor": "Ana Silva", "valor": 10.0, "numero": "25000.111", "situacao": None}]


def test_proposta_rica_sem_autor_vira_None_para_o_fundo():
    """Mesma disciplina da versao em tuplas: sem parlamentar real, autor=None e
    o chamador cai no Fundo Municipal — o valor NUNCA se perde."""
    r = propostas_saude_por_autor([{"nuProposta": "1", "vlProposta": 250000.0, "parlamentares": []}])
    assert r == [{"autor": None, "valor": 250000.0, "numero": "1", "situacao": None}]


def test_varios_autores_rateiam_cada_um_com_a_proposta_inteira():
    # SEM `vlIndObjeto`: a reserva é o `vlProposta`. Com ele, cada autor leva a
    # SUA parte (ver os testes da revisão do PDF, no fim do arquivo).
    r = propostas_saude_por_autor(
        [{"nuProposta": "7", "vlProposta": 100000.0,
          "parlamentares": [{"nome": "Ana Silva"}, {"nome": "Bruno Costa"}]}])
    assert len(r) == 2
    assert {"autor": "Ana Silva", "valor": 100000.0, "numero": "7", "situacao": None} in r
    assert {"autor": "Bruno Costa", "valor": 100000.0, "numero": "7", "situacao": None} in r


def test_string_e_lixo_nao_quebram_a_versao_rica():
    props = [{"nuProposta": "9", "vlProposta": 5, "parlamentares": [{"nome": "José Lima"}]}]
    assert propostas_saude_por_autor(json.dumps(props)) == [
        {"autor": "José Lima", "valor": 5.0, "numero": "9", "situacao": None}]
    assert propostas_saude_por_autor(None) == []
    assert propostas_saude_por_autor("nao e json") == []
    assert propostas_saude_por_autor(42) == []


def test_tupla_e_a_projecao_exata_da_versao_rica():
    """⚠️ `emendas_saude_por_autor` DELEGA em `propostas_saude_por_autor`. Se as
    duas divergirem, o contador e o detalhe voltam a mostrar coisas diferentes —
    exatamente a "duas verdades" que este conjunto existe para impedir."""
    props = [
        {"nuProposta": "1", "vlProposta": 400000.0,
         "parlamentares": [{"noApelidoPolitico": "Igor Timo"}]},
        {"nuProposta": "2", "vlProposta": 250000.0, "parlamentares": []},
        {"nuProposta": "3", "vlProposta": 100000.0,
         "parlamentares": [{"nome": "Ana Silva"}, {"nome": "Bruno Costa"}]},
    ]
    ricas = propostas_saude_por_autor(props)
    assert emendas_saude_por_autor(props) == [(p["autor"], p["valor"]) for p in ricas]


def test_as_TRES_superficies_usam_o_modulo_compartilhado():
    """Agregado + BI pela versao em tuplas; o detalhe pela versao rica. As tres
    descem pelo mesmo modulo — se uma parar, volta a divergir das outras."""
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent
    router = (raiz / "routers/parlamentares.py").read_text(encoding="utf-8")
    bi = (raiz / "services/bi_abas.py").read_text(encoding="utf-8")
    assert "emendas_saude_por_autor" in router      # bloco 6 (agregado)
    assert "propostas_saude_por_autor" in router     # detalhe (drill-down)
    assert "emendas_saude_por_autor" in bi           # aba do BI


# ---------------------------------------------------------------------------
# A PARTE DO AUTOR, não a proposta inteira (24/09/2026, revisão do PDF)
# ---------------------------------------------------------------------------
# Achado 1 da revisão do 248361f: a proposta 36000679587202500 (R$ 450.000,
# paga) com o MESMO autor duas vezes em `parlamentares[]` (coEmendaPolitica
# 37080010 com vlIndObjeto 250.000 e 37080011 com 200.000) saía em DUAS linhas
# de R$ 450.000 — TOTAL R$ 900.000 no PDF.
def _parl(nome, emenda, parte):
    return {"noApelidoPolitico": nome, "coEmendaPolitica": emenda,
            "nuAnoExercicio": 2025, "vlIndObjeto": parte}


def test_mesmo_autor_duas_vezes_e_uma_entrada_com_a_soma_das_partes():
    props = [{"nuProposta": "36000679587202500", "vlProposta": 450000.0,
              "parlamentares": [_parl("NIKOLAS FERREIRA", "37080010", 250000.0),
                                _parl("NIKOLAS FERREIRA", "37080011", 200000.0)]}]
    assert propostas_saude_por_autor(props) == [
        {"autor": "NIKOLAS FERREIRA", "valor": 450000.0,
         "numero": "36000679587202500", "situacao": None}]
    # O agregado (cabeçalho) e o BI contam o mesmo — uma vez, R$ 450 mil.
    assert emendas_saude_por_autor(props) == [("NIKOLAS FERREIRA", 450000.0)]


def test_o_mesmo_autor_e_reconhecido_sem_caixa_e_sem_acento():
    props = [{"nuProposta": "1", "vlProposta": 450000.0,
              "parlamentares": [_parl("Luis Tibé", "1", 250000.0),
                                _parl("LUIS TIBE", "2", 200000.0)]}]
    assert emendas_saude_por_autor(props) == [("Luis Tibé", 450000.0)]


def test_dois_autores_cada_um_com_o_seu_vlIndObjeto():
    props = [{"nuProposta": "36000679587202500", "vlProposta": 450000.0,
              "parlamentares": [_parl("NIKOLAS FERREIRA", "37080010", 250000.0),
                                _parl("IGOR TIMO", "40200001", 200000.0)]}]
    assert emendas_saude_por_autor(props) == [("NIKOLAS FERREIRA", 250000.0),
                                              ("IGOR TIMO", 200000.0)]


def test_sem_vlIndObjeto_a_reserva_e_o_vlProposta_uma_vez_so():
    props = [{"nuProposta": "1", "vlProposta": 450000.0,
              "parlamentares": [{"noApelidoPolitico": "NIKOLAS FERREIRA"},
                                {"noApelidoPolitico": "NIKOLAS FERREIRA"}]}]
    assert emendas_saude_por_autor(props) == [("NIKOLAS FERREIRA", 450000.0)]


def test_a_parte_do_autor_nunca_passa_da_proposta():
    props = [{"nuProposta": "1", "vlProposta": 450000.0,
              "parlamentares": [_parl("NIKOLAS FERREIRA", "1", 300000.0),
                                _parl("NIKOLAS FERREIRA", "2", 300000.0)]}]
    assert emendas_saude_por_autor(props) == [("NIKOLAS FERREIRA", 450000.0)]


def test_com_pagamento_traz_o_valor_inteiro_da_proposta():
    """O pagamento é da PROPOSTA: quem escreve "pago em parte: X de Y" divide
    pelo `valor_proposta`, não pela parte do autor."""
    props = [{"nuProposta": "1", "vlProposta": 450000.0, "vlPago": 200000.0,
              "vlPagar": 250000.0,
              "parlamentares": [_parl("NIKOLAS FERREIRA", "1", 250000.0),
                                _parl("IGOR TIMO", "2", 200000.0)]}]
    r = propostas_saude_por_autor(props, com_pagamento=True)
    assert [(p["autor"], p["valor"], p["valor_proposta"]) for p in r] == [
        ("NIKOLAS FERREIRA", 250000.0, 450000.0), ("IGOR TIMO", 200000.0, 450000.0)]
