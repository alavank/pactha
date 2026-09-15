"""A tela de Fundo a Fundo com a árvore do plano e as contas (15/09/2026).

O que se prova: o detalhe sai INTEIRO do banco, cobra a tela e o município da
linha e traz as contas do plano; a execução do município soma POR CONTA (a mesma
conta serve a vários planos); e os beneficiários de programa marcam os que ainda
não têm plano e se a janela para enviar ainda está aberta.
"""
import asyncio
from datetime import date

import pytest
from fastapi import HTTPException

from routers import faf_planos as rf
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
        self.params = []
        self.rollbacks = 0

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.consultas.append(s)
        self.params.append(params)
        for trecho in self.explode:
            if trecho in s:
                raise RuntimeError(f"relation {trecho} does not exist")
        for trecho, linhas in self.respostas.items():
            if trecho in s:
                return _Res(linhas)
        return _Res([])

    async def rollback(self):
        self.rollbacks += 1


_LINHA = (1, {"id_plano_acao": 22557, "id_programa": 343},
          {"_resumo": {"saldo_em_conta": 4683.01}, "metas": []}, None, None, "343")
_CONTA = {"id_agencia_conta": "2352-11650", "codigo_banco": "001", "nome_banco": "Banco do Brasil",
          "agencia": "2352", "dv_agencia": "3", "conta": "11650", "dv_conta": "5",
          "situacao": "Conta Ativa", "data_abertura": date(2025, 4, 29), "programa_agil": "MINC",
          "saldo_final": 4683.01, "planos": ["22557"], "cabecalho": {}, "lancamentos": [],
          "resumo": {"pago_a_beneficiarios": 55543.38}, "n_lancamentos": 14,
          "ultimo_lancamento": date(2026, 8, 31), "atualizado_em": None}


def _det(db, usuario, pid=22557):
    return asyncio.run(rf.detalhe_plano(id_plano_acao=pid, db=db, current=usuario))


def test_o_detalhe_sai_do_banco_com_as_contas_e_o_programa():
    db = _Db({"FROM faf_planos_acao": [_LINHA], "FROM faf_contas": [_CONTA],
              "FROM faf_programas": [({"nome_programa": "MINC_PNAB"}, [{"codigo_programa_agil": "343"}])]})
    r = _det(db, Usuario(telas={"faf_planos"}, municipios={1}))
    assert set(r) == {"plano", "detalhe", "contas", "programa", "detalhe_atualizado_em",
                      "atualizado_em", "fonte_atualizada_em", "url_fonte"}
    assert r["detalhe"]["_resumo"]["saldo_em_conta"] == 4683.01
    assert r["contas"][0]["saldo_final"] == 4683.01
    assert r["contas"][0]["ultimo_lancamento"] == "2026-08-31"
    assert r["programa"]["gestao_agil"][0]["codigo_programa_agil"] == "343"
    assert r["url_fonte"].endswith("id_plano_acao=22557")
    # a conta vem pelo plano (`= ANY(planos)`) e dentro do município da linha
    i = next(n for n, s in enumerate(db.consultas) if "FROM faf_contas" in s)
    assert "ANY(planos)" in db.consultas[i] and db.params[i] == {"m": 1, "p": "22557"}


def test_plano_de_outro_municipio_e_negado():
    """`id_plano_acao` é id federal: quem só vê o município 5 não abre o do 1."""
    with pytest.raises(HTTPException) as e:
        _det(_Db({"FROM faf_planos_acao": [_LINHA]}), Usuario(telas={"faf_planos"}, municipios={5}))
    assert e.value.status_code == 403


def test_sem_a_tela_nega_antes_do_banco():
    db = _Db({"FROM faf_planos_acao": [_LINHA]})
    with pytest.raises(HTTPException) as e:
        _det(db, Usuario(telas=set(), municipios={1}))
    assert e.value.status_code == 403 and db.consultas == []


def test_plano_fora_da_base_e_404():
    with pytest.raises(HTTPException) as e:
        _det(_Db(), Usuario(telas={"faf_planos"}, municipios={1}))
    assert e.value.status_code == 404


def test_sem_as_tabelas_novas_o_detalhe_segue():
    db = _Db({"FROM faf_planos_acao": [_LINHA]}, explode=("faf_contas", "faf_programas"))
    r = _det(db, Usuario(telas={"faf_planos"}, municipios={1}))
    assert r["contas"] == [] and r["programa"] is None and r["detalhe"] is not None


# ---------------------------------------------------------------------------
# A listagem: execução POR CONTA
# ---------------------------------------------------------------------------
def _plano_lista(pid, **kw):
    base = {"id_plano_acao": pid, "codigo_plano_acao": "c", "id_programa": "8",
            "situacao": "AUTORIZADO", "data_inicio_vigencia": None, "data_fim_vigencia": None,
            "diagnostico": None, "objetivos": "x", "valor_total": 100.0,
            "valor_repasse_emenda": 0.0, "valor_repasse_especifico": 100.0,
            "valor_repasse_voluntario": 0.0, "valor_recursos_proprios": 0.0,
            "valor_rendimentos": 0.0, "valor_custeio": 100.0, "valor_investimento": 0.0,
            "valor_saldo_disponivel": 0.0, "orgao_repassador": "Ministério da Cultura",
            "sigla_orgao_repassador": "MinC", "fundo_repassador": "FNC",
            "nome_ente_recebedor": "MUNICIPIO", "cnpj_ente_recebedor": "1",
            "tipo_unidade_recebedora": "ENTE", "relatorios_gestao": None,
            "resumo": None, "detalhe_coletado": False, "atualizado_em": None}
    base.update(kw)
    return base


def _conta(idc, saldo, planos, **resumo):
    return {"id_agencia_conta": idc, "saldo_final": saldo, "planos": planos,
            "resumo": resumo, "n_lancamentos": 1, "ultimo_lancamento": None,
            "situacao": "Conta Ativa"}


def test_a_execucao_soma_por_conta_e_nao_por_plano():
    """⚠️ Em Goiânia cinco planos usam a mesma conta. Somar o saldo do resumo de
    cada plano dobraria o dinheiro; aqui a conta 1126-8216 conta UMA vez."""
    planos = [_plano_lista("6811", detalhe_coletado=True, resumo={"saldo_em_conta": 2210354.58}),
              _plano_lista("6954", detalhe_coletado=True, resumo={"saldo_em_conta": 2210354.58}),
              _plano_lista("545")]
    contas = [_conta("1126-8216", 1733911.76, ["6811", "6954"], pago_a_beneficiarios=33459.6,
                     n_beneficiarios=3),
              _conta("1126-8217", 476442.82, ["6811", "6954"], pago_a_beneficiarios=6036.9,
                     n_beneficiarios=1, devolvido_uniao=10.0),
              _conta("0086-0", None, ["545"])]
    d = asyncio.run(rf.fetch_faf_planos(
        _Db({"FROM faf_planos_acao": planos, "FROM faf_contas": contas}), 1))
    ex = d["execucao"]
    assert ex["saldo_em_conta"] == round(1733911.76 + 476442.82, 2)
    assert ex["n_contas"] == 3 and ex["contas_com_saldo"] == 2 and ex["contas_divididas"] == 2
    assert ex["pago_a_beneficiarios"] == round(33459.6 + 6036.9, 2)
    assert ex["devolvido_uniao"] == 10.0
    assert ex["medidos"] == 2
    i6811 = next(i for i in d["itens"] if i["id_plano_acao"] == "6811")
    assert {c["id_agencia_conta"]: c["n_planos"] for c in i6811["contas"]} == \
        {"1126-8216": 2, "1126-8217": 2}
    assert i6811["detalhe_coletado"] is True and i6811["resumo"]["saldo_em_conta"] == 2210354.58


def test_sem_a_tabela_de_contas_a_listagem_segue():
    db = _Db({"FROM faf_planos_acao": [_plano_lista("1")]}, explode=("faf_contas",))
    d = asyncio.run(rf.fetch_faf_planos(db, 1))
    assert d["tem_dados"] and d["execucao"]["n_contas"] == 0 and db.rollbacks == 1


# ---------------------------------------------------------------------------
# Beneficiários de programa: sem plano, e a janela
# ---------------------------------------------------------------------------
def _benef(id_programa, tipo="ESPECIFICO", **kw):
    base = {"id_programa": id_programa, "cnpj_beneficiario": "88488358000156",
            "nome_beneficiario": "MUNICIPIO DE NOVA PALMA", "tipo_beneficiario": tipo,
            "valor": 1000.0, "numero_emenda": None, "parlamentar": None,
            "programa": "P", "ano": 2026, "sigla_orgao": "SENASP", "nome_orgao": "x",
            "situacao": "DISPONIBILIZADO",
            "janela_especificos_ini": None, "janela_especificos_fim": None,
            "janela_emendas_ini": None, "janela_emendas_fim": None,
            "janela_voluntarios_ini": None, "janela_voluntarios_fim": None}
    base.update(kw)
    return base


def test_beneficiario_sem_plano_com_a_janela_aberta():
    linhas = [
        _benef(8),                                            # já tem plano
        _benef(90, janela_especificos_ini=date(2026, 7, 20),
               janela_especificos_fim=date(2026, 9, 30)),     # sem plano, janela aberta
        _benef(91, janela_especificos_ini=date(2026, 7, 20),
               janela_especificos_fim=date(2026, 9, 11)),     # sem plano, janela fechada
        _benef(92, tipo="EMENDA_PARLAMENTAR", numero_emenda="202013310016",
               janela_emendas_ini=date(2026, 9, 1), janela_emendas_fim=date(2026, 12, 31),
               janela_especificos_ini=date(2020, 1, 1), janela_especificos_fim=date(2020, 2, 1)),
    ]
    r = asyncio.run(rf.fetch_faf_beneficiarios(
        _Db({"FROM faf_programas_beneficiarios": linhas}), 1, {"8"}, hoje=date(2026, 9, 15)))
    assert [b["tem_plano"] for b in r] == [True, False, False, False]
    assert [b["janela_aberta"] for b in r] == [False, True, False, True]
    # a janela vale pelo TIPO do beneficiário: emenda usa a de emendas
    assert r[3]["janela_fim"] == "2026-12-31"


def test_sem_a_tabela_de_beneficiarios_a_tela_segue_inteira():
    db = _Db(explode=("faf_programas_beneficiarios",))
    assert asyncio.run(rf.fetch_faf_beneficiarios(db, 1, set())) == []
    assert db.rollbacks == 1
