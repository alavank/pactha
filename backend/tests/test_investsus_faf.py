"""O agregado do fundo a fundo servido pela tela do InvestSUS (`routers/investsus._faf`).

O coletor tem os testes dele em `test_fns_faf.py`. Aqui esta o outro lado: a
soma que a tela mostra. Foi ela que fez o dado virar consequencia — a auditoria
de 31/08 achou 13 colunas coletadas que nenhuma tela lia, e a licao ficou:
coluna cheia que ninguem soma nao muda nada.

⚠️ O ERRO QUE ESTE ARQUIVO EXISTE PARA IMPEDIR E CONTAR DINHEIRO DUAS VEZES.
`grupo_codigo = 0` nao e um grupo: e a linha de TOTAL do bloco, gravada quando o
portal nao detalhou os grupos. Num bloco que tenha as duas formas — o total solto
E os grupos reais — somar tudo dobra o valor daquele bloco, e o numero errado sai
grande, isto e, do lado que ninguem estranha.

⚠️ E `None` NAO E ZERO. Municipio nunca coletado devolve None (a tela diz "ainda
nao coletamos"); um dia que devolvesse `{"total": 0}` faria a tela afirmar que o
municipio nao recebeu dinheiro de saude — falso, e sobre a fonte mais pesada da
pasta.

Rodar: python -m pytest backend/tests/test_investsus_faf.py -q
"""
import asyncio
from datetime import datetime, timezone

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

from routers.investsus import _faf  # noqa: E402

AGORA = datetime(2026, 9, 2, 3, 15, tzinfo=timezone.utc)


class _Resultado:
    def __init__(self, linhas):
        self._l = linhas

    def all(self):
        return self._l

    def first(self):
        return self._l[0] if self._l else None


class _DB:
    """Devolve os anos na 1a consulta e as linhas na 2a — a ordem de `_faf`."""

    def __init__(self, anos, linhas):
        self._respostas = [_Resultado([(a,) for a in anos]), _Resultado(linhas)]
        self.params = []

    async def execute(self, _sql, params=None):
        self.params.append(params)
        return self._respostas.pop(0) if self._respostas else _Resultado([])


def _linha(bcod, bnome, gcod, gnome, tot, desc=0, liq=None):
    return (bcod, bnome, gcod, gnome, tot, desc, tot if liq is None else liq, AGORA)


def _rodar(anos, linhas, ano=None):
    return asyncio.run(_faf(_DB(anos, linhas), 1, ano))


def test_sem_coleta_devolve_None():
    """⚠️ None, e nao dicionario zerado. A tela distingue os dois."""
    assert _rodar([], []) is None


def test_soma_por_bloco_e_total_do_ano():
    d = _rodar([2026], [
        _linha(10, "Manutenção", 12, "ATENÇÃO PRIMÁRIA", 3447463.86),
        _linha(10, "Manutenção", 35, "ASSISTÊNCIA FARMACÊUTICA", 137963.20),
        _linha(20, "Estruturação", 40, "INVESTIMENTO", 1000.00),
    ])
    assert d["ano"] == 2026
    assert len(d["blocos"]) == 2
    manutencao = d["blocos"][0]
    assert manutencao["codigo"] == 10
    assert round(manutencao["total"], 2) == 3585427.06
    assert round(d["total"], 2) == 3586427.06


def test_bloco_sem_detalhe_usa_o_total_solto():
    """`grupo_codigo = 0` sozinho E o valor do bloco."""
    d = _rodar([2026], [_linha(10, "Manutenção", 0, "Manutenção", 4059475.09, 12980)])
    assert d["blocos"][0]["total"] == 4059475.09
    assert d["blocos"][0]["desconto"] == 12980
    assert d["blocos"][0]["grupos"] == []
    assert d["total"] == 4059475.09


def test_total_solto_e_grupos_juntos_nao_contam_duas_vezes():
    """⚠️ O TESTE PRINCIPAL DESTE ARQUIVO.

    Se o portal devolver, no mesmo bloco, o total consolidado (grupo 0) E os
    grupos detalhados, vale o detalhamento — o total solto e a MESMA grana,
    escrita de outro jeito. Somar os dois publicaria o dobro.
    """
    d = _rodar([2026], [
        _linha(10, "Manutenção", 0, "Manutenção", 4059475.09, 12980),
        _linha(10, "Manutenção", 12, "ATENÇÃO PRIMÁRIA", 3447463.86),
        _linha(10, "Manutenção", 35, "ASSISTÊNCIA FARMACÊUTICA", 137963.20),
    ])
    assert len(d["blocos"]) == 1
    assert round(d["blocos"][0]["total"], 2) == 3585427.06   # e nao 7644902,15
    assert round(d["total"], 2) == 3585427.06
    assert [g["codigo"] for g in d["blocos"][0]["grupos"]] == [12, 35]


def test_blocos_e_grupos_saem_do_maior_para_o_menor():
    """A tela nao ordena; quem ordena e daqui. Dinheiro grande em cima."""
    d = _rodar([2026], [
        _linha(10, "Pequeno", 1, "a", 10.0),
        _linha(20, "Grande", 2, "b", 100.0),
        _linha(20, "Grande", 3, "c", 900.0),
    ])
    assert [b["codigo"] for b in d["blocos"]] == [20, 10]
    assert [g["codigo"] for g in d["blocos"][0]["grupos"]] == [3, 2]


def test_valor_nulo_no_banco_nao_estoura_a_soma():
    """NULL na coluna de dinheiro entra como 0 na SOMA — mas so na soma.

    A distincao NULL/zero vive na tabela e no coletor; aqui, somar None
    levantaria TypeError e derrubaria a tela inteira por causa de uma celula.
    """
    d = _rodar([2026], [
        (10, "B", 12, "g", None, None, None, AGORA),
        (10, "B", 13, "h", 5.0, 0, 5.0, AGORA),
    ])
    assert d["total"] == 5.0
    assert d["blocos"][0]["grupos"][1]["total"] == 0.0


def test_ano_pedido_e_respeitado_e_ano_invalido_cai_no_mais_recente():
    """O seletor da tela manda `ano`; um ano sem dado nao pode dar tela vazia."""
    d = _rodar([2026, 2025], [_linha(10, "B", 12, "g", 1.0)], ano=2025)
    assert d["ano"] == 2025
    assert d["anos"] == [2026, 2025]
    # 2019 nunca foi coletado -> cai no mais recente, e nao devolve nada vazio.
    assert _rodar([2026, 2025], [_linha(10, "B", 12, "g", 1.0)], ano=2019)["ano"] == 2026


def test_consulta_e_filtrada_pelo_municipio_pedido():
    """⚠️ Vazamento entre municipios seria o pior defeito possivel aqui.

    A tela e multi-municipio no freitas (41 na carteira). Se o filtro sumisse da
    consulta, um usuario veria o dinheiro de saude de outra prefeitura.
    """
    db = _DB([2026], [_linha(10, "B", 12, "g", 1.0)])
    asyncio.run(_faf(db, 77, 2026))
    assert all(p.get("m") == 77 for p in db.params)


def test_carimbo_de_coleta_vai_para_a_tela():
    d = _rodar([2026], [_linha(10, "B", 12, "g", 1.0)])
    assert d["atualizado_em"].startswith("2026-09-02")


def test_carimbo_sai_tambem_de_bloco_sem_detalhamento():
    """⚠️ DINHEIRO NA TELA SEM DATA AO LADO era o defeito.

    O carimbo subia apenas no ramo dos grupos reais. Um municipio cujos blocos
    viessem todos sem detalhamento — caminho previsto e tratado no resto do
    codigo — exibia valor de verdade e `atualizado_em = null`, e a tela nao sabia
    dizer de quando aquele numero era. A data e da LINHA, qualquer linha.
    """
    d = _rodar([2026], [_linha(10, "Manutenção", 0, "Manutenção", 4059475.09, 12980)])
    assert d["total"] == 4059475.09
    assert d["atualizado_em"] is not None
    assert d["atualizado_em"].startswith("2026-09-02")
