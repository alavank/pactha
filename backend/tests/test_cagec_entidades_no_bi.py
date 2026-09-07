"""O dashboard não pode discordar da tela do menu sobre a MESMA regularidade.

No cadastro estadual cada entidade do município tem cadastro próprio e trava
**apenas o seu** convênio: prefeitura regular não libera o convênio da saúde se o
Fundo Municipal de Saúde estiver irregular.

Em 07/09/2026, o mesmo município (Arapuá/MG) era descrito de três jeitos na mesma
sessão, porque `_cagec_bloco` chamava `fetch_cagec_situacao` e DESCARTAVA
`entidades` e `pendencias_outras_entidades`:

    Visão Geral (medidor)      "Impedido de receber transferências"
                               (`routers/bi.py::_semaforo_cagec` sempre contou entidades)
    aba Documentação           "Em dia · 0 pendências"   <- só a prefeitura
    tela Regularidade (menu)   "Regular" + "outras entidades somam 4 pendências"

Estes testes travam as duas metades da correção: o repasse por município e os
agregados da carteira. São de contrato de payload — nao dependem de banco.

Rodar:
    python -m pytest backend/tests/test_cagec_entidades_no_bi.py -v
"""
import asyncio

import pytest

from services import bi_abas


# Arapuá/MG, com os números reais da coleta de 07/09/2026: a prefeitura Regular
# e o Fundo Municipal de Saúde Irregular com 4 pendências.
SITUACAO = {
    "tem_dados": True,
    "nome": "MUNICIPIO DE ARAPUA",
    "uf": "MG",
    "regular": True,
    "situacao": "Regular",
    "validade": "2026-09-14",
    "itens": [{"codigo": "RFB-PGFN", "tipo": "regular"}],
    "pendencias": 0,
    "data_pesquisa": "2026-09-07",
    "atualizado_em": "2026-09-07T18:07:00+00:00",
    "crc_em": "2026-09-07",
    "crc_erro": None,
    "detalhe_do_crc": True,
    "entidades": [
        {"nome": "MUNICIPIO DE ARAPUA", "principal": True, "regular": True,
         "situacao": "Regular", "pendencias": 0, "tipo": "Município"},
        {"nome": "FUNDO MUNICIPAL DE SAUDE", "principal": False, "regular": False,
         "situacao": "Irregular", "pendencias": 4, "tipo": "Fundo Municipal de Saúde"},
    ],
    "pendencias_outras_entidades": 4,
}


@pytest.fixture
def bloco(monkeypatch):
    """`_cagec_bloco` sem banco: as três dependências de I/O viram constantes."""
    async def _escopo(_db, ids):
        return list(ids), [], ["MG"]

    async def _mais_antiga(_db, _tabela, _ids):
        return "2026-09-07T18:07:00+00:00"

    async def _fetch(_db, _mid):
        return SITUACAO

    monkeypatch.setattr(bi_abas, "_escopo_do_cadastro_estadual", _escopo)
    monkeypatch.setattr(bi_abas, "_coleta_mais_antiga", _mais_antiga)
    # O import de `fetch_cagec_situacao` acontece DENTRO da função, então o
    # patch tem de ser no módulo de origem.
    import routers.cagec as rc
    monkeypatch.setattr(rc, "fetch_cagec_situacao", _fetch)
    return lambda ids: asyncio.run(bi_abas._cagec_bloco(None, ids))


def test_entidades_chegam_ao_dashboard(bloco):
    """Sem estes dois campos a aba não tem como mostrar o fundo travado."""
    m = bloco([1])["por_municipio"][0]
    assert m["pendencias_outras_entidades"] == 4
    assert [e["nome"] for e in m["entidades"]] == [
        "MUNICIPIO DE ARAPUA", "FUNDO MUNICIPAL DE SAUDE"]


def test_campos_do_topo_continuam_sendo_os_da_principal(bloco):
    """O contrato antigo não muda: quem só quer 'a' situação lê a prefeitura."""
    m = bloco([1])["por_municipio"][0]
    assert m["regular"] is True
    assert m["pendencias"] == 0


def test_agregados_contam_todas_as_entidades(bloco):
    """A carteira tem de somar o que o medidor da Visão Geral soma.

    Antes: `regulares=1` e `pendencias_total=0` para um município com o fundo de
    saúde irregular — enquanto o medidor logo acima dizia que havia município
    impedido."""
    d = bloco([1])
    assert d["pendencias_total"] == 4
    assert d["regulares"] == 0


def test_municipio_sem_entidade_irregular_continua_regular(bloco, monkeypatch):
    """A trava não pode virar alarme falso: só entidade IRREGULAR desconta."""
    limpo = {**SITUACAO,
             "entidades": [SITUACAO["entidades"][0]],
             "pendencias_outras_entidades": 0}

    async def _fetch(_db, _mid):
        return limpo

    import routers.cagec as rc
    monkeypatch.setattr(rc, "fetch_cagec_situacao", _fetch)
    d = bloco([1])
    assert d["regulares"] == 1
    assert d["pendencias_total"] == 0
