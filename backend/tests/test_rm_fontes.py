"""Filtro de CONSULTAS (fontes) do RM — catalogo, normalizacao e recorte.

O teste que mais importa e o PRIMEIRO: ele le o CODIGO-FONTE do builder e cobra
que a chave do catalogo seja LITERALMENTE a string que o item carrega em
`fonte`. E o unico ponto que impede o defeito de telas_catalog.py x lib/telas.ts
de se repetir aqui — so que la divergir deixava a tela feia, e aqui deixa o
filtro SEM EFEITO, calado.

Tudo aqui roda sem banco: `montar_conteudo` e async e varre cinco tabelas, entao
o que da para provar em teste unitario e (a) a coerencia catalogo x builder por
leitura de fonte e (b) as funcoes puras de rm_fontes.
"""
import inspect
import re

from services import rm_builder
from services.rm_fontes import (
    FONTES_RM, CHAVES, catalogo, normalizar, no_escopo, rotulo_longo, slug,
)


def _carimbos_do_builder(fonte_txt: str) -> list[str]:
    """Todo valor literal de `"fonte": "..."` no texto dado."""
    return re.findall(r'"fonte":\s*"([a-z_]+)"', fonte_txt)


def test_o_catalogo_tem_exatamente_as_fontes_QUE_O_BUILDER_CARIMBA():
    """⭐ O contrato do incremento. Chave que existe so no catalogo vira uma caixa
    de selecao que nao filtra nada; fonte que existe so no builder some do
    relatorio de quem marcar qualquer consulta."""
    assert set(_carimbos_do_builder(inspect.getsource(rm_builder))) == set(CHAVES)


def test_toda_chamada_de_add_item_carimba_uma_fonte():
    src = inspect.getsource(rm_builder.montar_conteudo)
    chamadas = re.findall(r"^\s+add_item\(", src, re.M)
    carimbos = _carimbos_do_builder(src)
    assert len(chamadas) == len(carimbos), (
        "ha `add_item` sem `fonte`: esse item entra no RM e NENHUM filtro o alcanca")
    assert set(carimbos) == set(CHAVES)


def test_as_DUAS_insercoes_do_fns_respondem_a_mesma_chave():
    """O FNS entra por DOIS `add_item` (propostas individuais e o bucket agregado
    de fallback), mutuamente exclusivos por linha. Marcar "FNS" tem de alcancar os
    dois — pegar so um entrega o relatorio pela metade, calado."""
    src = inspect.getsource(rm_builder.montar_conteudo)
    assert len(re.findall(r'"fonte":\s*"fns"', src)) == 2


def test_o_filtro_mora_no_add_item_ponto_unico():
    src = inspect.getsource(rm_builder.montar_conteudo)
    corpo = src.split("def add_item(")[1].split("mun = (await db.execute(")[0]
    assert "fonte_no_escopo(" in corpo, (
        "o recorte por consulta saiu do ponto unico — com 9 insercoes e 8 fontes, "
        "filtro espalhado por laco esquece uma")


def test_a_dedupe_do_PAC_so_conta_voluntaria_que_ENTRA_no_relatorio():
    """⭐ A ARMADILHA DESTE INCREMENTO. `_pac_ja_exibidos` e preenchido no laco das
    VOLUNTARIAS, fora e antes do `add_item`, e consumido la embaixo no bloco do
    PAC. Com "Novo PAC" marcado e "TransfereGov" nao, o laco das voluntarias
    CONTINUA rodando: sem esta condicao ele alimenta a deduplicacao com propostas
    que NAO estao no documento, e o item do PAC e suprimido por uma voluntaria
    invisivel — o recurso some das DUAS fontes ao mesmo tempo."""
    src = inspect.getsource(rm_builder.montar_conteudo)
    assert 'fonte_no_escopo(fontes_filtro, "voluntaria")' in src


def test_selecao_vazia_e_TODAS_marcadas_sao_o_mesmo_relatorio():
    assert normalizar(None) == []
    assert normalizar([]) == []
    assert normalizar(list(CHAVES)) == []


def test_normalizar_ordena_porque_a_identidade_e_um_indice_sobre_ARRAY():
    # Para o Postgres {'fns','pac'} e {'pac','fns'} sao chaves DIFERENTES: sem a
    # ordenacao, o mesmo pedido com as caixas clicadas noutra ordem criaria um
    # SEGUNDO relatorio identico ao primeiro.
    assert normalizar(["pac", "fns"]) == normalizar(["fns", "pac"]) == ["fns", "pac"]
    assert normalizar(["fns", "fns"]) == ["fns"]


def test_chave_desconhecida_e_descartada_e_nao_derruba_a_geracao():
    assert normalizar(["fns", "sigconv", ""]) == ["fns"]
    # Sobrou vazio -> vira o completo, que e o padrao seguro.
    assert normalizar(["nada disso"]) == []


def test_no_escopo_vazio_deixa_TUDO_passar():
    """E o que garante que o RM completo continua exatamente o de hoje."""
    for chave in CHAVES:
        assert no_escopo([], chave) is True
        assert no_escopo(None, chave) is True


def test_no_escopo_compara_a_chave_EXATA():
    assert no_escopo(["simec"], "simec") is True
    # "simec" (liberacoes) e "simec_termo" (o instrumento) sao consultas
    # DIFERENTES com prefixo comum: startswith/substring fundiria as duas.
    assert no_escopo(["simec"], "simec_termo") is False
    assert no_escopo(["simec_termo"], "simec") is False
    assert no_escopo(["fns"], "") is False


def test_rotulo_e_slug_do_COMPLETO_sao_vazios():
    """E o que mantem titulo, nome de arquivo e pagina do RM completo iguais aos
    de hoje — os tres decidem por string vazia."""
    assert rotulo_longo([]) == ""
    assert slug([]) == ""
    assert rotulo_longo(["fns", "pac"]) == "FNS, Novo PAC"
    assert slug(["fns", "pac"]) == "fns-pac"


def test_o_catalogo_devolvido_e_copia():
    c = catalogo()
    c[0]["rotulo"] = "estragado"
    assert FONTES_RM[0]["rotulo"] != "estragado"


def test_todo_item_do_catalogo_tem_os_tres_campos_que_a_tela_desenha():
    for f in FONTES_RM:
        assert set(f) == {"chave", "rotulo", "curto"}
        assert f["rotulo"].strip() and f["curto"].strip()
    assert len(set(CHAVES)) == len(CHAVES)

