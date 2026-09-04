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

from services.nome_parlamentar import emendas_saude_por_autor


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
