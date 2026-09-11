"""O select de municipios do TransfereGov so pode ser lido com a pagina pronta.

⚠️ O DEFEITO QUE ISTO IMPEDE: trocar a UF no formulario do Acesso Livre
RECARREGA A PAGINA (medido em 10/09/2026, sonda em modo guest: o select some
~0,3s depois da escolha e volta ~0,5s depois com as 855 opcoes de MG). O coletor
lia a lista apos um sleep fixo de 3,5s e, com o portal lento, caia no meio do
recarregamento. O mesmo defeito aparecia com duas caras no rodizio:

  - select ausente     -> "Cannot read properties of null (reading 'options')"
  - select pela metade -> "municipio nao encontrado no select (727 opcoes)"

Sao Tiago e Oliveira Fortes passaram dias "nao encontrados" estando na lista
com o nome certo. Estes testes simulam o recarregamento e fixam o criterio de
pronto: fora de 'loading', mais que o placeholder e contagem estavel.
"""
import asyncio

import pytest

from ingestion.transferegov_voluntarias import _JS_OPCOES_MUNICIPIO, _opcoes_municipio

MUN = {"id": 1, "nome": "Sao Tiago", "uf": "MG"}


def _lista(n: int) -> list[dict]:
    return [{"v": "", "t": ""}] + [{"v": str(i), "t": f"MUNICIPIO {i}"} for i in range(n - 1)]


class _NavegacaoNoMeio(Exception):
    """O que o Playwright levanta quando a pagina navega durante o evaluate."""


class _PaginaQueRecarrega:
    """Devolve, a cada evaluate, o proximo estado do roteiro (ou levanta)."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.leituras = 0
        self.esperas = 0

    async def evaluate(self, js):
        assert js == _JS_OPCOES_MUNICIPIO
        self.leituras += 1
        estado = self.roteiro.pop(0) if len(self.roteiro) > 1 else self.roteiro[0]
        if isinstance(estado, Exception):
            raise estado
        return estado

    async def wait_for_timeout(self, ms):
        self.esperas += 1


def _rodar(pagina, **kw):
    return asyncio.run(_opcoes_municipio(pagina, MUN, **kw))


def test_so_devolve_a_lista_depois_do_recarregamento():
    # pagina velha (select vazio) -> navegacao destroi o contexto -> documento
    # em 'loading' (o JS devolve null) -> lista completa, duas vezes seguidas
    completa = _lista(855)
    pagina = _PaginaQueRecarrega([[], _NavegacaoNoMeio("Execution context was destroyed"),
                                  None, completa, completa])
    assert _rodar(pagina) == completa
    assert pagina.leituras == 5


def test_lista_pela_metade_nao_e_aceita_sem_confirmar_a_contagem():
    # Se o portal entregar 390 e depois 855, a leitura de 390 nao pode sair
    # como resposta: foi exatamente assim que "nao encontrado (390 opcoes)"
    # nasceu.
    pagina = _PaginaQueRecarrega([_lista(390), _lista(855), _lista(855)])
    assert len(_rodar(pagina)) == 855


def test_so_o_placeholder_ainda_nao_e_lista():
    pagina = _PaginaQueRecarrega([_lista(1), _lista(1), _lista(248), _lista(248)])
    assert len(_rodar(pagina)) == 248


def test_mesma_uf_ja_escolhida_sem_navegacao_devolve_na_segunda_leitura():
    pagina = _PaginaQueRecarrega([_lista(855), _lista(855)])
    assert len(_rodar(pagina)) == 855
    assert pagina.leituras == 2


def test_portal_que_nunca_termina_levanta_em_vez_de_devolver_vazio():
    # Lista vazia aqui viraria "municipio nao encontrado", o diagnostico errado.
    pagina = _PaginaQueRecarrega([None])
    with pytest.raises(RuntimeError, match="nao estabilizou"):
        _rodar(pagina, timeout_s=0)


def test_o_js_recusa_ler_durante_o_parse():
    # A trava que impede a lista pela metade mora no JS; se alguem "simplificar"
    # tirando o readyState, a contagem estavel sozinha nao basta com parse lento.
    assert "readyState === 'loading'" in _JS_OPCOES_MUNICIPIO
    assert "select[name=municipioAcessoLivre]" in _JS_OPCOES_MUNICIPIO
