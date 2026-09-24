"""O PDF de Parlamentares NO MODELO DA PLANILHA do cliente — gerado e lido de
volta (24/09/2026).

Pedido do dono: "na aba parlamentares eu gostaria que o pdf ficasse nesse
modelo" (`EmendasNikolasFerreiraBomDespacho.xlsx`). O endpoint roda INTEIRO, sem
Postgres: o banco falso só responde a leitura do município, `listar`/`detalhe`
são dublês, e o PDF é lido com pypdf — texto E cores do desenho.

As CORES esperadas foram medidas na planilha com openpyxl (fill de cada
célula), e não copiadas do código:
    título, cabeçalho e TOTAL GERAL ...... #1F4E78
    faixa de área ........................ #2E75B6
    linhas de dado ....................... #DCE6F1
    subtotal ............................. #BDD7EE
"""
import asyncio
import re
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

import routers.parlamentares as P
from routers import export_pdf
from tests.test_relatorio_parlamentares import FNS_MODELO, TE_MODELO

ADMIN = SimpleNamespace(id=1, name="Admin", allowed_telas=None, allowed_municipio_ids=None,
                        allowed_permissoes=None, role="super_admin")
BOM_DESPACHO = SimpleNamespace(id=7, nome="Bom Despacho", uf="MG")


class _Res:
    def __init__(self, v):
        self._v = v

    def scalar_one_or_none(self):
        return self._v


class _Db:
    def __init__(self, mun=BOM_DESPACHO):
        self.mun = mun

    async def execute(self, *a, **kw):
        return _Res(self.mun)


def _det(**kw):
    base = {"sigcon": [], "voluntarias": [], "emendas": [], "plano_acao": [], "pac": [],
            "fns": [], "emendas_federais": []}
    base.update(kw)
    return base


@pytest.fixture
def dubles(monkeypatch):
    """`dubles["detalhes"]`: nome -> detalhe. A lista de parlamentares sai dele."""
    reg = {"detalhes": {"NIKOLAS FERREIRA": _det(fns=[FNS_MODELO], plano_acao=[TE_MODELO])}}

    async def _listar(**kw):
        return {"items": [{"nome_display": n} for n in reg["detalhes"]]}

    async def _detalhe(**kw):
        return reg["detalhes"][kw["nome_normalizado"]]

    async def _nada(*a, **kw):
        pass

    monkeypatch.setattr(P, "listar", _listar)
    monkeypatch.setattr(P, "detalhe", _detalhe)
    monkeypatch.setattr(export_pdf, "_registrar_export", _nada)
    return reg


def _gera(mun=BOM_DESPACHO, **kw):
    args = {"request": None, "municipio_id": 7 if mun else None, "q": None, "ano": None,
            "anos": None, "tipo": "parlamentar", "db": _Db(mun), "current": ADMIN}
    args.update(kw)
    resp = asyncio.run(export_pdf.export_parlamentares_pdf(**args))

    async def _ler():
        return b"".join([c async for c in resp.body_iterator])

    pdf = PdfReader(BytesIO(asyncio.run(_ler())))
    return pdf, [" ".join((p.extract_text() or "").split()) for p in pdf.pages]


def _cores_de_preenchimento(pagina) -> set[str]:
    """As cores de PREENCHIMENTO (`r g b rg`) do desenho da folha, em #RRGGBB."""
    dados = pagina.get_contents().get_data().decode("latin-1")
    cores = set()
    for r, g, b in re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) rg", dados):
        cores.add("#%02X%02X%02X" % tuple(round(float(x) * 255) for x in (r, g, b)))
    return cores


def test_o_modelo_sai_no_papel(dubles):
    _pdf, texto = _gera()
    t = texto[0]
    assert "RECURSOS PAGOS BOM DESPACHO – EMENDAS INDICADAS POR NIKOLAS FERREIRA" in t
    # As colunas do modelo, na ordem (a busca anda: "RECURSO" também está no título).
    cab = ["MUNICÍPIO", "ANO", "RECURSO", "MINISTÉRIO DE ORIGEM", "VALOR GLOBAL (R$)",
           "PLANO DE AÇÃO / PROPOSTA", "SITUAÇÃO ATUAL"]
    pos = t.index("MUNICÍPIO")
    for c in cab:
        pos = t.index(c, pos)
    assert pos < t.index("SAÚDE")
    # Faixas, subtotais e total — com os valores do modelo.
    assert t.index("SAÚDE") < t.index("SUBTOTAL – SAÚDE 450.000,00") \
        < t.index("INFRAESTRUTURA") < t.index("SUBTOTAL – INFRAESTRUTURA 400.000,00") \
        < t.index("TOTAL GERAL – BOM DESPACHO 850.000,00")
    assert ("BOM DESPACHO 2025 Incremento MAC Ministério da Saúde 450.000,00 "
            "Proposta: 36000679587202500 Pagamento realizado em 18/11/2025.") in t
    assert "Plano de Ação: 09032024-070446" in t
    assert "Pagamento realizado em 13/12/2024." in t
    assert "(Transferência especial – Investimento)" in t


def test_as_cores_sao_as_da_planilha(dubles):
    pdf, _texto = _gera()
    cores = _cores_de_preenchimento(pdf.pages[0])
    assert {"#1F4E78", "#2E75B6", "#DCE6F1", "#BDD7EE"} <= cores


def test_a_folha_e_paisagem_A4(dubles):
    pdf, _texto = _gera()
    larg, alt = float(pdf.pages[0].mediabox.width), float(pdf.pages[0].mediabox.height)
    assert larg > alt and round(larg) == 842 and round(alt) == 595


def test_nao_pagos_quando_algo_nao_foi_pago(dubles):
    dubles["detalhes"]["NIKOLAS FERREIRA"] = _det(
        fns=[FNS_MODELO],
        plano_acao=[dict(TE_MODELO, execucao_estado="empenhado", valor_pago=0.0)])
    _pdf, texto = _gera()
    assert "RECURSOS PARA BOM DESPACHO – EMENDAS INDICADAS POR NIKOLAS FERREIRA" in texto[0]
    assert "RECURSOS PAGOS BOM DESPACHO" not in texto[0]
    assert "Empenhado, aguardando pagamento." in texto[0]


def test_um_parlamentar_por_folha(dubles):
    dubles["detalhes"]["FULANO DE TAL"] = _det(fns=[dict(FNS_MODELO, vl_pagar=10.0)])
    pdf, texto = _gera()
    assert len(pdf.pages) == 2
    assert "EMENDAS INDICADAS POR NIKOLAS FERREIRA" in texto[0]
    assert "FULANO DE TAL" not in texto[0]
    assert "RECURSOS PARA BOM DESPACHO – EMENDAS INDICADAS POR FULANO DE TAL" in texto[1]
    assert "parlamentar 2 de 2" in texto[1]


def test_fora_do_total_nao_entra_no_total_geral(dubles):
    carteira = {"municipio_id": 7, "municipio_nome": "Bom Despacho",
                "codigo_emenda": "202537080010", "ano": 2025, "orgao_siafi": "36000",
                "beneficiario_nome": "FUNDO MUNICIPAL DE SAUDE", "valor_total": 300000.0}
    dubles["detalhes"]["NIKOLAS FERREIRA"]["emendas_federais"] = [carteira]
    _pdf, texto = _gera()
    t = " ".join(texto)
    assert "TOTAL GERAL – BOM DESPACHO 850.000,00" in t        # o mesmo de antes
    assert "FORA DO TOTAL – EMENDAS FEDERAIS SEM INSTRUMENTO IDENTIFICADO" in t
    assert "SOMA – FORA DO TOTAL GERAL 300.000,00" in t
    assert t.index("TOTAL GERAL – BOM DESPACHO") < t.index("FORA DO TOTAL")
    # Com linha fora do total, o título não afirma "pagos".
    assert "RECURSOS PARA BOM DESPACHO" in t
    # Achado 4 da revisão do 248361f: a nota dizia que o FNS "não traz" o nº da
    # emenda — traz (`coEmendaPolitica`/`nuAnoExercicio`). O verdadeiro é que
    # nada foi casado por ele nesta base.
    assert "não trazem esse número" not in t
    assert "não foram casadas pelo número da emenda nesta base" in t


def test_toda_secao_fora_do_total_tem_a_sua_nota():
    """As chaves de `_NOTA_FORA` são os `GRUPOS_FORA` reescritos à mão: uma que
    diverge (o grupo ganhou "EM CADASTRAMENTO" no nome) apaga a nota calada."""
    from services.relatorio_parlamentares import GRUPOS_FORA
    assert set(export_pdf._NOTA_FORA) == set(GRUPOS_FORA)


def test_convenio_em_cadastramento_sai_fora_do_total_com_a_nota(dubles):
    conv = {"id": 11, "municipio_id": 7, "municipio_nome": "Bom Despacho",
            "numero": "002567/2026", "objeto": "AQUISICAO DE TRATOR",
            "situacao": "Cadastramento", "valor_total": 0.0, "orgao": "SEAPA",
            "ano": 2026, "indicacoes": [], "fonte": "sigcon"}
    dubles["detalhes"]["NIKOLAS FERREIRA"]["sigcon"] = [conv]
    _pdf, texto = _gera()
    t = " ".join(texto)
    assert "TOTAL GERAL – BOM DESPACHO 850.000,00" in t        # o mesmo de antes
    assert ("FORA DO TOTAL – PROPOSTAS NÃO SELECIONADAS, EM CADASTRAMENTO, "
            "CANCELADAS OU IMPEDIDAS") in t
    assert "convênios estaduais ainda em cadastramento" in t


def test_tabela_longa_repete_o_cabecalho_e_a_cidade_em_toda_folha(dubles):
    muitos = [dict(TE_MODELO, id=i, codigo=f"09032024-{i:06d}") for i in range(40)]
    dubles["detalhes"]["NIKOLAS FERREIRA"] = _det(plano_acao=muitos)
    pdf, texto = _gera()
    assert len(pdf.pages) >= 2
    for i, t in enumerate(texto, 1):
        assert "BOM DESPACHO/MG" in t, f"folha {i} sem a cidade no rodapé"
        assert "MUNICÍPIO" in t and "SITUAÇÃO ATUAL" in t, f"folha {i} sem o cabeçalho"
    assert "TOTAL GERAL – BOM DESPACHO 16.000.000,00" in texto[-1]


def test_texto_enorme_nao_estoura_a_folha(dubles):
    """Uma célula mais alta que a folha é LayoutError (500). O texto é cortado."""
    enorme = dict(TE_MODELO, objetos_executor=["Obra " * 3000])
    dubles["detalhes"]["NIKOLAS FERREIRA"] = _det(plano_acao=[enorme])
    pdf, texto = _gera()
    assert "…" in texto[0]


def test_sem_parlamentar(dubles):
    dubles["detalhes"].clear()
    _pdf, texto = _gera()
    assert "Nenhum parlamentar para o filtro atual." in texto[0]
    assert "RECURSOS PARA BOM DESPACHO" in texto[0]


def test_parlamentar_sem_lancamento_nao_quebra(dubles):
    dubles["detalhes"]["NIKOLAS FERREIRA"] = {}
    _pdf, texto = _gera()
    assert "Sem lançamentos detalhados para o filtro atual." in texto[0]
