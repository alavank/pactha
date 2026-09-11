"""Autor divergente na CGU: barrar A EMENDA, e não a noite inteira.

⚠️ O QUE ACONTECEU (11/09/2026, freitas e trust): a amostra de 20 códigos deu
"autor bate em 19, diverge em 1", e o veto antigo abortou a fase de execução
do tenant inteiro. Pior: a fila põe primeiro quem nunca foi consultado e o
aborto não consultava ninguém — a MESMA amostra voltaria na noite seguinte, e o
veto se renovaria sozinho, para sempre.

E a comparação que decidia era só `upper()` + "um contém o outro": "JOSÉ" contra
"JOSE" já contava como outro deputado.

O pior desfecho — gravar o número plausível da emenda de OUTRO deputado — segue
barrado, agora por emenda: a divergente é conferida pelo plano B (o código que a
própria CGU devolve para ano + número) e, se ainda divergir, é pulada e anotada.
"""
import inspect

import ingestion.portal_transparencia as pt
from ingestion.portal_transparencia import (Orcamento, _confere_autor, _norm_autor,
                                            estrategia_pela_amostra, mesmo_autor)


# --- a comparação de nomes ---------------------------------------------------

def test_acento_caixa_e_pontuacao_nao_fazem_outro_deputado():
    assert mesmo_autor("JOSÉ ROCHA", ["Jose Rocha"]) is True
    assert mesmo_autor("MARIA DO ROSÁRIO", ["MARIA DO ROSARIO"]) is True
    assert mesmo_autor("PAULO PIMENTA", ["PAULO  PIMENTA."]) is True


def test_titulo_na_frente_do_nome_nao_faz_outro_deputado():
    assert mesmo_autor("DEP. HEITOR SCHUCH", ["HEITOR SCHUCH"]) is True
    assert mesmo_autor("HEITOR SCHUCH", ["Deputado Heitor Schuch"]) is True
    assert _norm_autor("Sen. Fulano de Tal") == "FULANO DE TAL"


def test_nome_curto_contido_no_longo_continua_valendo():
    # A regra de antes ("um contém o outro") segue — agora por palavra inteira.
    assert mesmo_autor("BANCADA DO RIO GRANDE DO SUL", ["BANCADA DO RIO GRANDE DO SUL"]) is True
    assert mesmo_autor("ALCEU MOREIRA", ["ALCEU MOREIRA DA SILVA"]) is True


def test_pedaco_de_palavra_nao_casa():
    # O substring cru de antes deixava "ANA" casar com "JULIANA".
    assert mesmo_autor("ANA", ["JULIANA"]) is False
    assert mesmo_autor("PAULO PIMENTA", ["PAULO PIMENTAL"]) is False


def test_pessoas_diferentes_continuam_diferentes():
    assert mesmo_autor("HEITOR SCHUCH", ["PAULO PIMENTA"]) is False


def test_sem_nome_de_um_lado_nao_e_divergencia():
    # Não há o que comparar: não é prova de erro (e o comportamento de antes).
    assert mesmo_autor(None, ["PAULO PIMENTA"]) is None
    assert mesmo_autor("PAULO PIMENTA", [None, ""]) is None


# --- a amostra escolhe a estratégia, e não para mais a rodada ----------------

def _v(achou, diverge, taxa=1.0):
    return {"testados": 20, "achou": achou, "taxa": taxa,
            "autor_bate": achou - diverge, "autor_diverge": diverge}


def test_uma_divergencia_em_vinte_segue_derivando():
    # Exatamente o caso de 11/09: a rodada NÃO para e NÃO muda de estratégia.
    assert estrategia_pela_amostra(_v(20, 1)) == "codigo"


def test_divergencia_em_massa_passa_a_rodada_ao_plano_b():
    assert estrategia_pela_amostra(_v(20, 10)) == "ano_numero"


def test_taxa_baixa_continua_mandando_ao_plano_b():
    assert estrategia_pela_amostra(_v(3, 0, taxa=0.15)) == "ano_numero"


def test_o_veto_que_abortava_a_rodada_nao_existe_mais():
    src = inspect.getsource(pt.execucao)
    assert 'rel["veto"]' not in src, "voltou o veto que abortava a fase 2 inteira"
    assert "_confere_autor(" in src, "a conferência por emenda saiu do laço"
    ingest = inspect.getsource(pt.ingest)
    assert 'ex["autor_divergente"]' in ingest and '"partial"' in ingest, (
        "emenda pulada é execução faltando: a rodada tem de sair `partial`")


# --- a conferência por emenda ------------------------------------------------

class _PlanoB:
    """Dublê de `agregado_por_ano_numero`: registra a chamada e devolve o roteiro."""

    def __init__(self, devolve):
        self.devolve = devolve
        self.chamadas = []

    def __call__(self, client, ano, numero, orcamento=None):
        self.chamadas.append((ano, numero))
        return self.devolve


def _orc():
    return Orcamento(300, 80)


def test_autor_que_bate_segue_como_veio(monkeypatch):
    b = _PlanoB([])
    monkeypatch.setattr(pt, "agregado_por_ano_numero", b)
    itens = [{"nomeAutor": "HEITOR SCHUCH", "codigoEmenda": "202532980004"}]
    assert _confere_autor(None, "202532980004", 2025, itens, False,
                          "Heitor Schuch", "codigo", _orc()) == (itens, False, None)
    assert b.chamadas == [], "não pode gastar requisição com emenda que bateu"


def test_divergente_resolvida_pelo_plano_b_usa_o_codigo_oficial(monkeypatch):
    oficial = [{"nomeAutor": "HEITOR SCHUCH", "codigoEmenda": "202432980004"}]
    b = _PlanoB(oficial)
    monkeypatch.setattr(pt, "agregado_por_ano_numero", b)
    errado = [{"nomeAutor": "OUTRO DEPUTADO", "codigoEmenda": "202532980004"}]
    itens, confirmado, div = _confere_autor(None, "202532980004", 2025, errado, False,
                                            "HEITOR SCHUCH", "codigo", _orc())
    assert (itens, confirmado, div) == (oficial, True, None)
    assert b.chamadas == [(2025, "32980004")]


def test_divergente_mesmo_no_plano_b_e_pulada_e_anotada(monkeypatch):
    monkeypatch.setattr(pt, "agregado_por_ano_numero",
                        _PlanoB([{"nomeAutor": "OUTRO DEPUTADO"}]))
    itens, confirmado, div = _confere_autor(
        None, "202532980004", 2025, [{"nomeAutor": "OUTRO DEPUTADO"}], False,
        "HEITOR SCHUCH", "codigo", _orc())
    assert itens == [] and confirmado is False
    assert div == {"codigo": "202532980004", "dump": "HEITOR SCHUCH",
                   "cgu": "OUTRO DEPUTADO"}


def test_na_estrategia_plano_b_nao_ha_segunda_consulta(monkeypatch):
    # O item já veio do plano B: perguntar de novo devolveria o mesmo.
    b = _PlanoB([{"nomeAutor": "HEITOR SCHUCH"}])
    monkeypatch.setattr(pt, "agregado_por_ano_numero", b)
    itens, _, div = _confere_autor(None, "202532980004", 2025,
                                   [{"nomeAutor": "OUTRO DEPUTADO"}], True,
                                   "HEITOR SCHUCH", "ano_numero", _orc())
    assert itens == [] and div["codigo"] == "202532980004"
    assert b.chamadas == []


def test_documentos_sao_buscados_pelo_codigo_oficial():
    """Com o plano B o código oficial pode diferir do derivado; a linha do tempo
    pelo DERIVADO traria os pagamentos da emenda de outro deputado."""
    src = inspect.getsource(pt.execucao)
    assert "documentos_da_emenda(client, cod_cgu, orc)" in src
    assert "linha_documento(cod_cgu, b)" in src
    assert "marcas.append((verdadeiro, True, len(docs), None))" in src, (
        "sem a marca sob o código renomeado, o carimbo da fila se perde")
