"""CONSOLIDADO — a carteira inteira lado a lado (18/09/2026).

⚠️ O QUE ESTE ARQUIVO IMPEDE:
- o escopo "sem município" virar o TENANT INTEIRO (as funções de agregação não
  têm gate; lista vazia nelas seria "sem filtro");
- usuário restrito ver município que não é dele;
- a soma por município divergir do cartão (campo de valor errado por fonte);
- a Emenda Pix voltar a ficar de fora do ranking do Painel/BI;
- `/parlamentares/{nome:path}` engolir `/exportar`.

Rodar: python -m pytest backend/tests/test_consolidado.py -q
"""
import asyncio
import io
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from routers import consolidado as C
from routers import parlamentares as P

RAIZ = Path(__file__).resolve().parent.parent


def _det():
    return {
        "sigcon": [{"municipio_id": 1, "municipio_nome": "Araújos", "valor_total": 100.0,
                    "numero": "123", "objeto": "Ponte", "situacao": "Vigente", "ano": 2024}],
        "voluntarias": [{"municipio_id": 2, "municipio_nome": "Bom Despacho",
                         "valor_global": 500.0, "valor_repasse": 450.0,
                         "numero_proposta": "1/2025", "objeto": "Pavimentação"}],
        "emendas": [{"municipio_id": 1, "municipio_nome": "Araújos", "valor_indicacao": 50.0,
                     "nr_indicacao": "9", "beneficiario": "APAE", "status_indicacao": "Paga"}],
        "plano_acao": [{"municipio_id": 2, "municipio_nome": "Bom Despacho",
                        "valor_total": 1000.0, "codigo": "09032025-1", "situacao": "Ciente"}],
        "pac": [], "fns": [],
        "emendas_federais": [{"municipio_id": 1, "municipio_nome": "Araújos",
                              "valor_total": 10.0, "codigo_emenda": "20254567", "ano": 2025}],
    }


# ------------------------------------------------------------------ puras ---

def test_por_municipio_soma_o_campo_que_o_cartao_soma():
    """⚠️ Voluntária soma `valor_global` (não `valor_repasse`), emenda estadual
    soma `valor_indicacao`: os mesmos de `detalhe_core.valor_total`."""
    muns = C.por_municipio(_det())
    assert [m["municipio_nome"] for m in muns] == ["Bom Despacho", "Araújos"], "maior valor primeiro"
    bd, ar = muns
    assert bd["valor"] == 1500.0 and bd["lancamentos"] == 2
    assert bd["por_fonte"]["voluntarias"] == {"valor": 500.0, "lancamentos": 1}
    assert ar["valor"] == 160.0
    assert set(ar["por_fonte"]) == {"sigcon", "emendas", "emendas_federais"}


def test_a_soma_por_municipio_fecha_com_o_total_do_detalhe():
    det = _det()
    total = (sum(x["valor_total"] for x in det["sigcon"])
             + sum(x["valor_global"] for x in det["voluntarias"])
             + sum(x["valor_indicacao"] for x in det["emendas"])
             + sum(x["valor_total"] for x in det["plano_acao"])
             + sum(x["valor_total"] for x in det["emendas_federais"]))
    assert sum(m["valor"] for m in C.por_municipio(det)) == total


def test_as_fontes_do_consolidado_sao_as_do_detalhe():
    """Fonte nova no `detalhe_core` sem entrar em FONTES sumiria da soma daqui."""
    fonte = (RAIZ / "routers" / "parlamentares.py").read_text(encoding="utf-8")
    ret = fonte[fonte.index('        "nome_consulta": nome_param,'):]
    chaves = set(re.findall(r'^\s+"(\w+)": (?:sigcon|voluntarias|emendas|plano_acao|pac_list|fns_list|ef_list),',
                            ret, re.M))
    assert chaves == {f for f, _c, _r in C.FONTES}, chaves


def test_lancamentos_levam_o_municipio_e_o_valor_certo():
    ls = C.lancamentos(_det())
    assert len(ls) == 5
    v = next(x for x in ls if x["fonte"].startswith("Voluntárias"))
    assert v["valor"] == 500.0 and v["municipio_id"] == 2 and v["numero"] == "1/2025"
    e = next(x for x in ls if x["fonte"] == "Emendas estaduais")
    assert e["objeto"] == "APAE" and e["situacao"] == "Paga"


# ----------------------------------------------------------------- escopo ---

def test_usuario_restrito_ve_so_os_seus_municipios():
    user = SimpleNamespace(allowed_municipio_ids={5, 3}, role="usuario")
    ids = asyncio.run(P.escopo_de_municipios(None, user, None))
    assert ids == [3, 5]


def test_usuario_sem_municipio_leva_403_e_nao_o_tenant():
    from fastapi import HTTPException
    user = SimpleNamespace(allowed_municipio_ids=set(), role="usuario")
    with pytest.raises(HTTPException) as e:
        asyncio.run(P.escopo_de_municipios(None, user, None))
    assert e.value.status_code == 403


def test_detalhe_core_recusa_escopo_vazio():
    """⚠️ Lista vazia seria "sem filtro" — o tenant inteiro."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        asyncio.run(P.detalhe_core(None, "fulano", [], None))
    assert e.value.status_code == 403


def test_parlamentares_continua_sem_todos_para_quem_nao_e_super_admin():
    """⚠️ A carteira do cliente é do CONSOLIDADO, com permissão própria. Se as
    rotas da tela Parlamentares aceitassem "sem município" para todo mundo, quem
    só tem `parlamentares.ver` teria a visão da carteira sem `consolidado.ver`.
    E o escopo vem como lista explícita (`escopo_de_municipios`), nunca None."""
    fonte = (RAIZ / "routers" / "parlamentares.py").read_text(encoding="utf-8")
    for funcao in ("async def listar", "async def comparar", "async def detalhe("):
        corpo = fonte[fonte.index(funcao):]
        corpo = corpo[:corpo.index("\n@router") if "\n@router" in corpo else len(corpo)]
        gate = corpo.index("ensure_municipio_access(current, municipio_id)")
        assert gate < corpo.index("escopo_de_municipios(db, current, municipio_id)"), funcao


def test_o_consolidado_resolve_escopo_em_toda_rota():
    fonte = (RAIZ / "routers" / "consolidado.py").read_text(encoding="utf-8")
    # O escopo é o do usuário; nenhuma rota aceita município como parâmetro.
    assert not re.search(r"^\s+municipio_id\s*:", fonte, re.M)
    for bloco in fonte.split("@router.get(")[1:]:
        assert 'exige("consolidado.' in bloco.split("\n")[0]
        assert "await _escopo(db, current)" in bloco


def test_exportar_e_declarada_antes_do_path_generico():
    caminhos = [r.path for r in C.router.routes]
    assert caminhos.index("/api/consolidado/parlamentares/{nome:path}/exportar") < caminhos.index(
        "/api/consolidado/parlamentares/{nome:path}")


# ------------------------------------------------------------ Emenda Pix ---

def test_a_emenda_pix_entra_em_toda_tela():
    """⚠️ Até 18/09/2026 o Painel, o BI e o /comparar passavam
    `incluir_plano_acao=False` e o ranking deles deixava a Emenda Pix de fora."""
    import inspect
    assert "incluir_plano_acao" not in inspect.signature(P.aggregate_parlamentares).parameters
    for arq in ("routers/bi.py", "routers/painel.py", "routers/parlamentares.py",
                "routers/consolidado.py"):
        codigo = "\n".join(l for l in (RAIZ / arq).read_text(encoding="utf-8").splitlines()
                           if not l.strip().startswith("#"))
        assert "incluir_plano_acao=" not in codigo, arq


# --------------------------------------------------------------- arquivos ---

def test_a_planilha_tem_as_duas_abas():
    openpyxl = pytest.importorskip("openpyxl")
    det = _det()
    buf = C._xlsx("Fulano", "todos os anos", 44, C.por_municipio(det), C.lancamentos(det))
    wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()))
    assert wb.sheetnames == ["Por município", "Lançamentos"]
    ws = wb["Por município"]
    assert ws["A5"].value == "Bom Despacho" and ws["B5"].value == 1500.0
    assert "2 de 44 municípios" in ws["A2"].value
    assert wb["Lançamentos"].max_row == 6


def test_o_pdf_sai():
    pytest.importorskip("reportlab")
    det = _det()
    buf = C._pdf("Fulano <&>", "2025", 44, C.por_municipio(det), C.lancamentos(det))
    assert buf.getvalue()[:4] == b"%PDF"
