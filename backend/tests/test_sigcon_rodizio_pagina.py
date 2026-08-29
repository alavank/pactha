"""Rodízio de PÁGINA no laço de detalhe do SIGCON.

MEDIDO EM PRODUÇÃO (29/08/2026, Araújos, log da coleta):

    Pag 1 (Página 1 de 2): 25 linhas
    Pag 2 (Página 2 de 2): 3 linhas
    Total parsed: 28 convenios para ARAUJOS
    Detalhe: 7 links cmdLink na tabela      <- só os da PÁGINA 1
    Detalhes capturados: 4

A LISTAGEM pagina; o laço de DETALHE não paginava. E `_estabelecer_grid`, chamado
entre cada registro, faz `goto` + "Pesquisar" — o que devolve a grade para a
página 1. Resultado: toda rodada lia os MESMOS primeiros links, e os outros 24
convênios de Araújos nunca ganhariam prestação de contas, última alteração nem
indicação. Não era questão de esperar mais rodadas: era permanente.
"""
import asyncio

import pytest

from ingestion.sigcon_scraper import _ir_para_pagina, _scrape_detalhes


class _BotaoFake:
    """Um botão do paginador. `count()` = 'está habilitado?' — é assim que o
    código de produção decide se pode clicar."""
    def __init__(self, page, tipo):
        self._p, self._tipo = page, tipo

    async def count(self):
        if self._tipo == "next":
            return 1 if self._p.pag < self._p.total else 0
        return 1 if self._p.pag > 1 else 0          # 'primeira'

    async def click(self, timeout=None):
        self._p.pag = self._p.pag + 1 if self._tipo == "next" else 1
        self._p.cliques += 1


class _LocFake:
    def __init__(self, page, n=0, tipo="next"):
        self._p, self._n, self._tipo = page, n, tipo

    @property
    def first(self):
        return _BotaoFake(self._p, self._tipo)

    async def count(self):
        return self._n


class _PageFake:
    """`page` do Playwright reduzida ao que o laço usa.

    ⚠️ NASCE NA ÚLTIMA PÁGINA, e isso é o ponto. A primeira versão deste fake
    fazia `self.pag = 1` — a premissa da IMPLEMENTAÇÃO, não a sequência real de
    chamada. `_scrape_municipio` pagina até o 'próxima' sumir e entrega a grade
    na última página; com `pag = 1` os testes passavam verdes e o rodízio era um
    no-op em produção. Trocar esta única linha derrubava dois testes."""
    def __init__(self, total=2, links_por_pagina=None, com_paginador=True):
        self.total, self.cliques = total, 0
        self.pag = total                            # <- estado REAL de entrada
        self.com_paginador = com_paginador
        self.links = links_por_pagina or {1: 7, 2: 3}

    def locator(self, sel):
        if "paginator-first" in sel:
            if not self.com_paginador:
                return _LocFake(self, n=0, tipo="first")
            # sem `:not(...)` a consulta mede EXISTÊNCIA; com, mede HABILITADO
            n = (1 if self.pag > 1 else 0) if ":not(" in sel else 1
            return _LocFake(self, n=n, tipo="first")
        if "paginator-next" in sel:
            return _LocFake(self, n=1 if self.pag < self.total else 0, tipo="next")
        if "dtTblExibeListaPlanosDeTrabalho_data" in sel:
            return _LocFake(self, n=25 if self.pag == 1 else 3)
        return _LocFake(self, n=self.links.get(self.pag, 0))

    async def wait_for_timeout(self, ms):
        pass


def _corre(coro):
    return asyncio.run(coro)


# ------------------------------------------------------- o avanço de página --
def test_avanca_ate_a_pagina_pedida():
    """Custo = 1 clique de 'primeira' (a grade chega na ÚLTIMA página) + (N-1) de
    'próxima'. O paginador do PrimeFaces é um postback por clique."""
    p = _PageFake(total=4)                      # entra na página 4
    assert _corre(_ir_para_pagina(p, 3)) == 3
    assert p.cliques == 3, "1 para voltar ao início + 2 para chegar na 3"


def test_a_pagina_1_TAMBEM_custa_a_normalizacao():
    """⚠️ Antes este teste se chamava "não custa clique nenhum" e passava — com
    um fake que nascia na página 1. Na vida real a grade chega na ÚLTIMA página,
    então até pedir a página 1 exige voltar. Sem isso o laço lia a última página
    LOGANDO "pagina 1"."""
    p = _PageFake(total=4)
    assert _corre(_ir_para_pagina(p, 1)) == 1
    assert p.cliques == 1, "o clique de 'primeira'"
    assert p.pag == 1, "e a grade FICA na página 1"


def test_municipio_de_pagina_unica_nao_clica_nada():
    """Sem paginador não há o que normalizar."""
    p = _PageFake(total=1, com_paginador=False)
    assert _corre(_ir_para_pagina(p, 1)) == 1
    assert p.cliques == 0


def test_pedir_pagina_alem_do_fim_devolve_ate_onde_deu():
    """⚠️ É assim que o rodízio sabe que deu a volta: pedir a 5 num município de
    2 páginas devolve 2, e quem chama trata."""
    p = _PageFake(total=2)
    assert _corre(_ir_para_pagina(p, 5)) == 2


# ---------------------------------------------------------- o laço de detalhe --
def test_o_laco_le_a_PAGINA_PEDIDA_e_nao_sempre_a_primeira():
    """⚠️ A regressão que este trabalho conserta. Sem isto, Araújos lia
    eternamente os 7 links da página 1 e os outros 21 convênios ficavam sem
    prestação de contas para sempre."""
    p = _PageFake(total=2, links_por_pagina={1: 7, 2: 3})
    _, lida = _corre(_scrape_detalhes(p, max_planos=0, pagina=2))
    assert lida == 2, "leu a página 2, não a 1"
    assert p.pag == 2
    assert p.cliques == 2, "1 para voltar ao início + 1 para ir à 2"


def test_devolve_TUPLA_e_o_dict_fica_limpo():
    """⚠️ A página lida vai numa TUPLA, não numa chave dentro do dict: `out` é
    indexado por número de proposta e `len(out)` é o que loga "Detalhes
    capturados: N". Uma chave de controle ali somaria +1 na contagem e ainda
    poderia ser servida como se fosse um convênio."""
    p = _PageFake(total=2)
    out, lida = _corre(_scrape_detalhes(p, max_planos=0, pagina=1))
    assert isinstance(out, dict) and isinstance(lida, int)
    assert not any(k.startswith("_") for k in out), "sem chave de controle no dict"


def test_pagina_inexistente_VOLTA_para_a_1_na_mesma_rodada():
    """Município com 2 páginas e o rodízio pedindo a 3: em vez de gastar a vez
    lendo o fim da grade, recomeça da 1 JÁ NESTA rodada."""
    p = _PageFake(total=2)

    async def _grid(pg, tries=3, pagina=1):
        pg.pag = 1
        return True

    import ingestion.sigcon_scraper as m
    orig, m._estabelecer_grid = m._estabelecer_grid, _grid
    try:
        _, lida = _corre(_scrape_detalhes(p, max_planos=0, pagina=3))
    finally:
        m._estabelecer_grid = orig
    assert lida == 1


# ------------------------------------------------------------- a rotação -----
@pytest.mark.parametrize("lida,esperado", [(1, 2), (2, 3), (3, 4)])
def test_a_proxima_pagina_e_a_seguinte_a_que_foi_LIDA(lida, esperado):
    """A conta que o chamador faz. Usa a página REALMENTE lida, não a pedida —
    senão um município de 2 páginas iria para 4, 5, 6… e nunca mais leria nada."""
    assert int(lida or 1) + 1 == esperado


def test_o_ciclo_se_fecha_sozinho_sem_saber_o_total():
    """Município de 2 páginas: 1 → 2 → (pede 3, lê 1) → 2 → … O rodízio nunca
    precisa saber quantas páginas existem, e um município que ganhar páginas
    novas entra no ciclo sem nenhuma migração."""
    total, pag, vistas = 2, 1, []
    for _ in range(6):
        lida = pag if pag <= total else 1     # o que `_scrape_detalhes` devolve
        vistas.append(lida)
        pag = lida + 1
    assert set(vistas) == {1, 2}, vistas
    assert vistas.count(1) >= 2 and vistas.count(2) >= 2, "as duas são revisitadas"


# --------------------------------------------------------------------------
# O TETO. Paginar custa: `_estabelecer_grid` roda entre CADA registro e
# re-avança (página-1) cliques de ~2s. Conta feita: 25 registros na página 10
# = 432s SÓ de paginação. O orçamento impede o estouro, mas a rodada passaria
# a paginar em vez de ler detalhe — cobertura CAI.
# --------------------------------------------------------------------------
from ingestion.sigcon_scraper import _DET_MAX_PAG                     # noqa: E402


def test_o_rodizio_tem_teto_e_volta_para_a_1():
    """4 páginas × 25 linhas = 100, exatamente o `SIGCON_MAX_PLANOS` que já
    limita quantos detalhes uma credencial abre. Os dois tetos concordam."""
    assert _DET_MAX_PAG == 4
    prox = lambda lida: 1 if (lida + 1) > _DET_MAX_PAG else lida + 1
    assert [prox(n) for n in (1, 2, 3, 4)] == [2, 3, 4, 1]


def test_o_custo_de_paginar_e_limitado_pelo_teto():
    """A conta que justifica o teto — em segundos de paginação por município."""
    custo = lambda regs, pag: (regs - 1) * (pag - 1) * 2.0
    assert custo(25, _DET_MAX_PAG) <= 150, "no teto, cabe na fatia de ~240s"
    assert custo(25, 10) > 400, "sem teto, a paginação comeria a rodada"


def test_o_avanco_para_quando_o_orcamento_acaba():
    """⚠️ Paginar também custa. Sem o corte, um município no fim do rodízio
    gastaria o resto da janela clicando 'próxima' sem ler detalhe nenhum."""
    import ingestion.sigcon_scraper as m
    p = _PageFake(total=8)
    orig = m._sig_estourou
    m._sig_estourou = lambda: True
    try:
        assert _corre(_ir_para_pagina(p, 6)) == 1
        # A NORMALIZACAO acontece mesmo sem orcamento — é 1 clique, e sem ela
        # `alcancada` mentiria sobre em que página a grade está. O que o
        # orçamento corta é o AVANÇO, que é o que cresce com N.
        assert p.cliques == 1, "só o 'primeira'; nenhum avanço"
        assert p.pag == 1
    finally:
        m._sig_estourou = orig


# --------------------------------------------------------------------------
# A REGRESSÃO QUE A REVISÃO ADVERSARIAL ACHOU (29/08/2026).
#
# A 1ª versão de `_ir_para_pagina` começava com `atual = 1`, assumindo grade na
# primeira página. `_scrape_municipio` pagina até o 'próxima' SUMIR — termina na
# ÚLTIMA — e `_scrape_one` passa a MESMA `page` adiante sem reset. Resultado:
# 'próxima' já desabilitado → ZERO cliques → devolvia 1 → o ramo "página não
# existe" disparava → relia a página 1. O rodízio virava um no-op que só cobrava
# tempo, e a coluna travava em 2 para sempre.
#
# Os testes passavam porque o fake nascia em `pag = 1`.
# --------------------------------------------------------------------------
def test_grade_entrando_na_ULTIMA_pagina_ainda_alcanca_a_pedida():
    """O cenário exato do defeito: município de 2 páginas, grade entra na 2,
    rodízio pede a 2. Sem a normalização isto devolvia 1."""
    p = _PageFake(total=2)
    assert p.pag == 2, "o fake tem de entrar na última página"
    assert _corre(_ir_para_pagina(p, 2)) == 2


def test_o_ciclo_visita_TODAS_as_paginas_entrando_pela_ultima():
    """⚠️ A prova de cobertura, feita com as funções REAIS e a grade entrando na
    última página a cada rodada. Com o defeito, a lista saía [1, 1, 1, 1, 1, 1] e
    os convênios das outras páginas nunca eram lidos."""
    vistas, prox = [], 1
    for _ in range(6):
        p = _PageFake(total=3)              # nova rodada: grade na última
        lida = _corre(_ir_para_pagina(p, prox))
        if lida < prox:                     # deu a volta
            lida = _corre(_ir_para_pagina(p, 1))
        vistas.append(lida)
        prox = 1 if lida + 1 > _DET_MAX_PAG else lida + 1
    assert set(vistas) == {1, 2, 3}, vistas
