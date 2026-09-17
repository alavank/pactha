"""Emendas parlamentares numa tela só (17/09/2026) — o que só a lógica garante.

O repo não tem Postgres de teste; o que se prova aqui é a parte que decide
NÚMERO: a mesma emenda vinda de quatro tabelas vira UMA linha, o que casa não
soma duas vezes, o que não casa não some, e o total só conta a prefeitura.

Rodar:
    python -m pytest backend/tests/test_emendas_parlamentares.py -v
"""
import asyncio

import pytest

from services.emendas_unificadas import codigo_de, filtrar, totais, unificar_federais


def _carteira(codigo="202432980001", **kw):
    base = {"codigo_emenda": codigo, "ano": 2024, "autor": "Heitor Schuch",
            "tipo": "INDIVIDUAL", "impositiva": True, "valor_indicado": 500_000.0,
            "beneficiario_prefeitura": True, "beneficiario_nome": "MUNICIPIO",
            "propostas": [], "execucao_consultada": False, "grupo": "nao_consultada"}
    base.update(kw)
    return base


@pytest.mark.parametrize("texto,esperado", [
    ("202432980001", "202432980001"),                    # carteira
    ("202432980001-Heitor Schuch", "202432980001"),      # transferegov_te
    ("2024.3298.0001", "202432980001"),                  # Parcerias
    ("202432980001-Deputado 2º Mandato", "202432980001"),  # dígito no nome não entra
    ("2024.3298", None), ("", None), (None, None),
])
def test_codigo_de_reduz_os_tres_formatos(texto, esperado):
    assert codigo_de(texto) == esperado


def test_te_com_o_mesmo_codigo_vira_instrumento_e_nao_linha():
    """⚠️ O defeito caro: somar o plano Pix ao indicado da mesma emenda."""
    linhas = unificar_federais(
        [_carteira()],
        [{"plano_acao_id": 77, "emenda": "202432980001-Heitor Schuch",
          "parlamentar": "Heitor Schuch", "valor_total": 500_000.0, "situacao": "Ciente"}],
        [], [], [])
    assert len(linhas) == 1
    assert linhas[0]["instrumentos"][0]["origem"] == "te"
    assert linhas[0]["origens"] == ["federal", "te"]
    assert totais(linhas)["valor_prefeitura"] == 500_000.0


def test_o_que_nao_casa_vira_linha_propria():
    """Perder a emenda Pix que a carteira não viu é o erro oposto, e pior."""
    linhas = unificar_federais(
        [_carteira()],
        [{"plano_acao_id": 88, "emenda": "202511110002-Outro", "parlamentar": "Outro",
          "valor_total": 100_000.0}],
        [], [], [])
    assert {l["origem"] for l in linhas} == {"federal", "te"}
    te = next(l for l in linhas if l["origem"] == "te")
    assert te["codigo_emenda"] == "202511110002" and te["ano"] == 2025
    assert totais(linhas)["valor_prefeitura"] == 600_000.0


def test_parcerias_casa_pelo_codigo_com_pontos():
    linhas = unificar_federais(
        [_carteira()], [],
        [{"id_proposta": 5, "numero_emenda": "2024.3298.0001", "valor_emenda": 500_000.0,
          "municipal": True}],
        [], [])
    assert len(linhas) == 1 and linhas[0]["instrumentos"][0]["origem"] == "parcerias"


def test_indicacao_com_proposta_nao_entra_duas_vezes():
    linhas = unificar_federais(
        [], [],
        [{"id_proposta": 5, "numero_emenda": "2025.1234.0001", "valor_emenda": 300_000.0,
          "parlamentar": "Fulano", "municipal": True}],
        [{"numero_emenda": "2025.1234.0001", "valor_total": 300_000.0, "municipal": True},
         {"numero_emenda": "2025.1234.0002", "valor_total": 50_000.0, "municipal": True}],
        [])
    assert sorted(l["origem"] for l in linhas) == ["indicacao", "parcerias"]
    assert totais(linhas)["valor_prefeitura"] == 350_000.0


def test_voluntaria_casa_pelo_id_da_proposta_da_carteira():
    linhas = unificar_federais(
        [_carteira(propostas=["123456"])], [], [], [],
        [{"numero_proposta": "048291/2024", "id_proposta_siconv": 123456,
          "valor_emenda": 500_000.0, "municipal": True},
         {"numero_proposta": "000001/2023", "id_proposta_siconv": 999,
          "parlamentar": "Beltrano, Sicrano", "valor_emenda": 10_000.0, "municipal": True}])
    fed = next(l for l in linhas if l["origem"] == "federal")
    assert [i["id"] for i in fed["instrumentos"]] == ["048291/2024"]
    solta = next(l for l in linhas if l["origem"] == "voluntaria")
    assert solta["ano"] == 2023 and solta["autores"] == ["Beltrano", "Sicrano"]


def test_total_so_soma_a_prefeitura_e_nunca_a_execucao_cgu():
    """A execução CGU é da emenda INTEIRA, nacional: somada, deu R$ 4 bi em Nova
    Palma. E o hospital da cidade aparece, marcado, fora da conta."""
    linhas = unificar_federais(
        [_carteira(execucao_consultada=True, valor_empenhado=30_000_000.0,
                   valor_pago=30_000_000.0, grupo="paga"),
         _carteira(codigo="202432980002", valor_indicado=80_000.0,
                   beneficiario_prefeitura=False, beneficiario_nome="HOSPITAL")],
        [], [], [], [])
    t = totais(linhas)
    assert t["valor_prefeitura"] == 500_000.0
    assert t["fora_prefeitura_n"] == 1 and t["fora_prefeitura_valor"] == 80_000.0
    assert t["com_pagamento_n"] == 1 and t["nao_consultadas_n"] == 1
    assert "30000000" not in repr({k: v for k, v in t.items() if k != "por_origem"})


def test_mesmo_codigo_em_dois_beneficiarios_nao_repete_a_chave():
    linhas = unificar_federais(
        [_carteira(), _carteira(beneficiario_prefeitura=False, valor_indicado=1.0)],
        [], [], [], [])
    assert len({l["chave"] for l in linhas}) == 2
    assert {l["id"] for l in linhas} == {"202432980001"}


def test_colegiado_e_marcado():
    linhas = unificar_federais([_carteira(tipo="BANCADA", autor="BANCADA DO RS")],
                               [], [], [], [])
    assert linhas[0]["colegiado"] is True


def test_colegiado_sem_tipo_e_marcado_pelo_nome():
    """A voluntária não traz `tipo`: medido na Freitas, "BANCADA DE MINAS GERAIS"
    e "COM. CULTURA" saíam como pessoa sem partido."""
    linhas = unificar_federais([], [], [], [], [
        {"numero_proposta": "1/2024", "parlamentar": "BANCADA DE MINAS GERAIS",
         "valor_emenda": 1.0, "municipal": True},
        {"numero_proposta": "2/2024", "parlamentar": "COM. CULTURA",
         "valor_emenda": 1.0, "municipal": True},
        {"numero_proposta": "3/2024", "parlamentar": "Domingos Savio",
         "valor_emenda": 1.0, "municipal": True}])
    por_id = {l["id"]: l["colegiado"] for l in linhas}
    assert por_id == {"1/2024": True, "2/2024": True, "3/2024": False}


def test_orgao_no_lugar_do_autor_nao_vira_parlamentar():
    """No SIGCON o responsável às vezes é a Secretaria de Estado."""
    from routers.emendas_parlamentares import _autor
    a = _autor("SECRETARIA DE ESTADO DE EDUCAÇÃO", {"SECRETARIA DE ESTADO DE EDUCAÇÃO": {"partido": "X"}})
    assert a == {"nome": "SECRETARIA DE ESTADO DE EDUCAÇÃO", "pessoa": False, "cadastro": None}
    assert _autor("Diego Andrade", {"Diego Andrade": {"partido": "PSD"}})["pessoa"] is True


def test_filtros_antes_dos_totais():
    linhas = unificar_federais(
        [_carteira(), _carteira(codigo="202311110001", ano=2023, autor="Outra",
                                valor_indicado=1_000.0)], [], [], [], [])
    so_2023 = filtrar(linhas, anos=[2023])
    assert totais(so_2023)["valor_prefeitura"] == 1_000.0
    assert len(filtrar(linhas, autor="heitor")) == 1
    assert filtrar(linhas, origem="te") == []


# ---------------------------------------------------------------------------
# Cadastro: partido ao lado do nome
# ---------------------------------------------------------------------------

class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def fetchall(self):
        return self._l

    def mappings(self):
        return self

    def all(self):
        return self._l


class _DB:
    """Responde às duas consultas de `cadastros_por_nome`, pela tabela citada."""

    def __init__(self, apelidos, cadastro):
        self.apelidos, self.cadastro, self.params = apelidos, cadastro, []

    async def execute(self, sql, params=None):
        self.params.append(params)
        if "parlamentares_apelidos" in str(sql):
            return _Res(self.apelidos)
        return _Res(self.cadastro)

    async def rollback(self):
        pass


def _cad(nome, chaves, partido, uf, leg=(57,), casa="camara", ident="1"):
    return {"casa": casa, "id_externo": ident, "nome": nome, "partido": partido, "uf": uf,
            "cargo": "Deputado(a) Federal", "foto_url": None, "legislaturas": list(leg),
            "nomes_norm": list(chaves)}


def test_cadastro_casa_usa_apelido_e_ignora_colegiado():
    from services.cadastro_parlamentar import cadastros_por_nome
    db = _DB([("MICHELMIGUELELIASTEMERLULIA", "MICHELTEMER")],
             [_cad("Michel Temer", ["MICHELTEMER"], "MDB", "SP"),
              _cad("Heitor Schuch", ["HEITORSCHUCH"], "PSB", "RS", ident="2")])
    r = asyncio.run(cadastros_por_nome(db, [
        "MICHEL MIGUEL ELIAS TEMER LULIA", "Heitor Schuch", "BANCADA DO RS", "Não há"]))
    assert r["MICHEL MIGUEL ELIAS TEMER LULIA"]["partido"] == "MDB"
    assert r["Heitor Schuch"]["uf"] == "RS"
    assert "BANCADA DO RS" not in r and "Não há" not in r
    assert "nomes_norm" not in r["Heitor Schuch"]


def test_homonimo_de_pessoas_diferentes_fica_sem_partido():
    from services.cadastro_parlamentar import cadastros_por_nome
    db = _DB([], [_cad("Bebeto", ["BEBETO"], "PSB", "BA", ident="1"),
                  _cad("Bebeto", ["BEBETO"], "PP", "RJ", ident="2")])
    assert asyncio.run(cadastros_por_nome(db, ["Bebeto"])) == {"Bebeto": None}


def test_tabela_ausente_nao_derruba_a_tela():
    from services.cadastro_parlamentar import cadastros_por_nome

    class _Quebra(_DB):
        async def execute(self, sql, params=None):
            raise RuntimeError("relation does not exist")

    assert asyncio.run(cadastros_por_nome(_Quebra([], []), ["Heitor Schuch"])) == {
        "Heitor Schuch": None}


# ---------------------------------------------------------------------------
# Permissão: cada aba cobra a chave que já existia
# ---------------------------------------------------------------------------

def test_telas_estaduais_existem_no_catalogo():
    from routers.emendas_parlamentares import TELA_ESTADUAL_POR_UF
    from services.permissoes import CATALOGO
    chaves = set(CATALOGO)
    for tela in TELA_ESTADUAL_POR_UF.values():
        assert f"{tela}.ver" in chaves


def test_rotas_registradas_com_as_chaves_antigas():
    """Nenhuma chave `emendas_parlamentares.*`: a decisão do dono foi não criar
    tela nova, para ninguém ganhar nem perder acesso."""
    from services.permissoes import CATALOGO
    assert not any(c.startswith("emendas_parlamentares") for c in CATALOGO)
    from routers.emendas_parlamentares import router
    caminhos = {r.path for r in router.routes}
    for p in ("/api/emendas-parlamentares/federais", "/api/emendas-parlamentares/estaduais",
              "/api/emendas-parlamentares/parlamentares",
              "/api/emendas-parlamentares/emenda/{origem}/{ident:path}"):
        assert p in caminhos
