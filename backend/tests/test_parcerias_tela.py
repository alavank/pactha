"""A tela de Parcerias com a árvore da proposta (15/09/2026).

O que se prova: o detalhe sai INTEIRO do banco, cobra a tela e o município da
linha; a execução soma só a administração municipal e diz quanto da carteira
já foi medido; e as emendas indicadas marcam as que ainda não viraram proposta.
"""
import asyncio

import pytest
from fastapi import HTTPException

from routers import parcerias as rp
from services import authz


class Usuario:
    def __init__(self, telas=None, municipios=None):
        self.id = 7
        self.email = "servidor@novapalma.rs.gov.br"
        self.name = "Servidor"
        self.allowed_telas = telas
        self.allowed_municipio_ids = municipios


@pytest.fixture(autouse=True)
def _isolar(monkeypatch):
    authz.limpar_dedupe()
    authz.limpar_contexto()
    monkeypatch.setattr(authz, "_enviar", lambda _d: True)
    yield
    authz.limpar_dedupe()
    authz.limpar_contexto()


class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def first(self):
        return self._l[0] if self._l else None

    def scalar_one_or_none(self):
        return self._l[0][0] if self._l else None

    def mappings(self):
        return self

    def all(self):
        return self._l


class _Db:
    """Responde por trecho do SQL. `explode` simula tabela ausente."""

    def __init__(self, respostas=None, explode=()):
        self.respostas = respostas or {}
        self.explode = explode
        self.consultas = []
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.consultas.append(s)
        for trecho in self.explode:
            if trecho in s:
                raise RuntimeError(f"relation {trecho} does not exist")
        for trecho, linhas in self.respostas.items():
            if trecho in s:
                return _Res(linhas)
        return _Res([])

    async def rollback(self):
        self.rollbacks += 1


_LINHA = (1, {"id_proposta": 75376, "_parceria": {"id_parceria": 75161}},
          {"_resumo": {"pago": 299999.0}, "metas": []}, None, None)


def _det(db, usuario, pid=75376):
    return asyncio.run(rp.detalhe_proposta(id_proposta=pid, db=db, current=usuario))


def test_o_detalhe_sai_do_banco_com_as_chaves_da_tela():
    db = _Db({"FROM parcerias_propostas": [_LINHA]})
    r = _det(db, Usuario(telas={"parcerias"}, municipios={1}))
    assert set(r) == {"proposta", "detalhe", "detalhe_atualizado_em", "atualizado_em",
                      "fonte_atualizada_em", "url_fonte"}
    assert r["detalhe"]["_resumo"]["pago"] == 299999.0
    assert r["url_fonte"].endswith("id_proposta=75376")


def test_proposta_de_outro_municipio_e_negada():
    """`id_proposta` é id federal: quem só vê o município 5 não abre a do 1."""
    with pytest.raises(HTTPException) as e:
        _det(_Db({"FROM parcerias_propostas": [_LINHA]}),
             Usuario(telas={"parcerias"}, municipios={5}))
    assert e.value.status_code == 403


def test_sem_a_tela_nega_antes_do_banco():
    db = _Db({"FROM parcerias_propostas": [_LINHA]})
    with pytest.raises(HTTPException) as e:
        _det(db, Usuario(telas=set(), municipios={1}))
    assert e.value.status_code == 403 and db.consultas == []


def test_proposta_fora_da_base_e_404():
    with pytest.raises(HTTPException) as e:
        _det(_Db(), Usuario(telas={"parcerias"}, municipios={1}))
    assert e.value.status_code == 404


def _linha_lista(**kw):
    base = {"id_proposta": 1, "objeto": "x", "situacao": "Aprovada", "valor_total": 100.0,
            "ano_proposta": 2026, "data_proposta": None, "nome_ente_recebedor": "FMS",
            "cnpj_ente_recebedor": "1", "natureza_juridica": "Fundo Público da Administração Direta Municipal",
            "id_parceria": 9, "codigo_parceria": "c", "situacao_parceria": "Aprovada",
            "data_assinatura": None, "numero_emenda": "2026.2023.0002", "parlamentar": "PAULO PAIM",
            "tipo_emenda": "Individual", "valor_emenda": 100.0, "resultado_esperado": None,
            "atualizado_em": None, "resumo": None, "detalhe_coletado": False, "nu_externo": None}
    base.update(kw)
    return base


def test_a_execucao_soma_so_a_administracao_municipal_e_diz_quanto_foi_medido():
    linhas = [
        _linha_lista(id_proposta=1, detalhe_coletado=True,
                     resumo={"pago": 100.0, "saldo_total": 40.0, "nao_classificado": 100.0}),
        _linha_lista(id_proposta=2, detalhe_coletado=True, resumo=None),   # sem parceria
        _linha_lista(id_proposta=3),                                       # não colhida
        _linha_lista(id_proposta=4, detalhe_coletado=True,
                     natureza_juridica="Associação Privada",
                     resumo={"pago": 999.0, "saldo_total": 999.0, "nao_classificado": 9.0}),
    ]
    d = asyncio.run(rp.fetch_parcerias(_Db({"FROM parcerias_propostas": linhas}), 1))
    ex = d["execucao"]
    assert ex == {"medidas": 2, "pago": 100.0, "saldo": 40.0, "com_saldo": 1,
                  "nao_classificado": 100.0, "com_nao_classificado": 1}
    item = next(i for i in d["itens"] if i["id_proposta"] == 1)
    assert item["resumo"]["pago"] == 100.0 and item["detalhe_coletado"] is True


def test_emendas_indicadas_marcam_as_que_ainda_nao_viraram_proposta():
    linhas = [
        {"numero_emenda": "2026.2023.0002", "ano_emenda": 2026, "parlamentar": "PAULO PAIM",
         "tipo_emenda": "Individual", "valor_gnd3": None, "valor_gnd4": 299999.0,
         "valor_total": 299999.0, "nome_beneficiario": "FMS", "cnpj_beneficiario": "12240183000100",
         "natureza_juridica": "Fundo Público da Administração Direta Municipal",
         "indicacoes": [], "id_programa": 14},
        {"numero_emenda": "2025.2098.0002", "ano_emenda": 2025, "parlamentar": "AFONSO HAMM",
         "tipo_emenda": "Individual", "valor_gnd3": 100000.0, "valor_gnd4": None,
         "valor_total": 100000.0, "nome_beneficiario": "FMS", "cnpj_beneficiario": "12240183000100",
         "natureza_juridica": "Fundo Público da Administração Direta Municipal",
         "indicacoes": [{"nm_solicitante": "X"}], "id_programa": 14},
    ]
    r = asyncio.run(rp.fetch_emendas_indicadas(
        _Db({"FROM parcerias_emendas_indicadas": linhas}), 1, {"2026.2023.0002"}))
    assert [e["tem_proposta"] for e in r] == [True, False]
    assert r[1]["indicacoes"] == [{"nm_solicitante": "X"}] and r[1]["municipal"] is True


def test_sem_a_tabela_de_emendas_a_tela_segue_inteira():
    """A API sobe antes da migration: o bloco some, a tela não quebra."""
    db = _Db(explode=("parcerias_emendas_indicadas",))
    assert asyncio.run(rp.fetch_emendas_indicadas(db, 1, set())) == []
    assert db.rollbacks == 1
