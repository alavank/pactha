"""Voluntárias: o que não é da prefeitura sai das somas (15/09/2026).

O coletor entra por `COD_MUNIC_IBGE`, e isso traz tudo o que está SEDIADO na
cidade. Medido nos dumps de Discricionárias em 15/09/2026: em Goiânia 75% do
valor é do ESTADO DE GOIÁS (1.897 propostas, R$ 8,2 bi), em Palmas 82% é do
Tocantins, em Santa Maria 33% é de entidades da sociedade civil.

Decisão do dono: mostrar marcado e FORA das somas, como em Parcerias. O que se
prova aqui: a regra com as naturezas REAIS da fonte, o coletor gravando a
coluna, a lista marcando e contando, e — a guarda que importa — que toda
consulta que soma `transferegov_propostas` carrega o filtro.
"""
import ast
import asyncio
from pathlib import Path

import pytest

from services.natureza import SQL_SO_PREFEITURA, e_municipal, municipal_ou_nulo

BACKEND = Path(__file__).resolve().parents[1]

# As cinco naturezas que `siconv_proposta.zip` traz para Goiânia, Palmas,
# Santa Maria, Nova Palma e Monte Sião (dump de 15/09/2026), mais as duas de
# Parcerias.
NATUREZAS = {
    "Administração Pública Municipal": True,
    "Administração Pública Estadual ou do Distrito Federal": False,
    "Organização da Sociedade Civil": False,
    "Consórcio Público": False,
    "Empresa pública/Sociedade de economia mista": False,
    "Fundo Público da Administração Direta Municipal": True,   # Parcerias
    "Município": True,                                          # Parcerias
    "Fundo Público da Administração Direta Estadual ou do Distrito Federal": False,
}


@pytest.mark.parametrize("natureza,esperado", NATUREZAS.items())
def test_a_regra_com_as_naturezas_reais(natureza, esperado):
    assert e_municipal(natureza) is esperado
    assert municipal_ou_nulo(natureza) is esperado


def test_ausencia_conta_como_prefeitura_e_vira_nulo_na_coluna():
    """Zerar os cartões porque a fonte parou de mandar a natureza seria pior que
    uma proposta a mais na conta. Na coluna, NULO: `IS NOT FALSE` a conta."""
    for vazio in (None, "", "   "):
        assert e_municipal(vazio) is True
        assert municipal_ou_nulo(vazio) is None
    assert SQL_SO_PREFEITURA == "municipal IS NOT FALSE"


def test_consorcio_nao_e_a_prefeitura():
    """É ente próprio, de vários municípios: fica marcado, como a OSC."""
    assert e_municipal("Consórcio Público") is False


def test_parcerias_usa_a_mesma_regra():
    from routers import parcerias
    assert parcerias._municipal is e_municipal


# ---------------------------------------------------------------------------
# O coletor grava a natureza e a regra
# ---------------------------------------------------------------------------
def _linha_proposta(id_prop, nr, natureza, ibge="5208707"):
    return {"ID_PROPOSTA": id_prop, "NR_PROPOSTA": nr, "COD_MUNIC_IBGE": ibge,
            "SIT_PROPOSTA": "Proposta/Plano de Trabalho Aprovados",
            "NATUREZA_JURIDICA": natureza, "NM_PROPONENTE": "X", "OBJETO_PROPOSTA": "Y",
            "VL_GLOBAL_PROP": "100,00"}


def test_o_coletor_grava_natureza_e_municipal(monkeypatch):
    from ingestion import transferegov_opendata as od
    linhas = {
        "siconv_proposta.zip": [
            _linha_proposta("1", "000001/2025", "Administração Pública Municipal"),
            _linha_proposta("2", "000002/2025", "Administração Pública Estadual ou do Distrito Federal"),
            _linha_proposta("3", "000003/2025", "Organização da Sociedade Civil"),
            _linha_proposta("4", "000004/2025", ""),
        ],
    }
    monkeypatch.setattr(od, "_linhas", lambda nome: iter(linhas.get(nome, [])))
    props = od._coleta([{"id": 7, "nome": "Goiânia", "ibge": "5208707"}])[7]
    por_num = {p["numero_proposta"]: p for p in props}
    assert por_num["000001/2025"]["municipal"] is True
    assert por_num["000002/2025"]["municipal"] is False
    assert por_num["000002/2025"]["natureza_juridica"].startswith("Administração Pública Estadual")
    assert por_num["000003/2025"]["municipal"] is False
    assert por_num["000004/2025"]["municipal"] is None      # a fonte não disse


# ---------------------------------------------------------------------------
# ⚠️ A GUARDA: toda consulta que lê a tabela carrega o filtro, ou diz por quê não
# ---------------------------------------------------------------------------
# (arquivo, função) -> por que NÃO filtra. Leitor novo que não esteja aqui e não
# filtre faz o teste falhar: é a decisão que precisa ser tomada, não esquecida.
NAO_SOMAM = {
    ("routers/control.py", "*"): "Central: conta o banco inteiro, é operação",
    ("routers/freshness.py", "*"): "frescor da fonte: quando e quanto chegou",
    ("routers/transferegov.py", "carregar_voluntaria"): "UMA proposta, pelo número",
    ("routers/emendas_parlamentares.py", "_fontes_federais"): "lista TODAS marcadas "
        "com `municipal`, e `emendas_unificadas.totais` soma só as da prefeitura "
        "(guardado em test_emendas_parlamentares.py)",
    ("routers/transferegov.py", "voluntarias_arvore_lista"): "UMA proposta, pelo número "
        "(pagamentos/licitações/liquidações paginados)",
    ("routers/transferegov.py", "listar_pac"): "elo PAC→voluntária, por número; não soma",
    ("main.py", "*"): "status de ingestão",
}
LEITORES = ["routers", "services", "mcp_app.py", "main.py"]
FILTROS = ("municipal IS NOT FALSE", "SQL_SO_PREFEITURA", "municipal IS FALSE")


def _consultas():
    arquivos = []
    for alvo in LEITORES:
        p = BACKEND / alvo
        arquivos += sorted(p.glob("*.py")) if p.is_dir() else [p]
    for arq in arquivos:
        fonte = arq.read_text(encoding="utf-8")
        if "FROM transferegov_propostas" not in fonte:
            continue
        rel = arq.relative_to(BACKEND).as_posix()
        arvore = ast.parse(fonte)
        fns = [n for n in ast.walk(arvore) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        linhas = fonte.splitlines()
        for i, linha in enumerate(linhas, 1):
            if "FROM transferegov_propostas" not in linha or linha.lstrip().startswith("#"):
                continue
            donos = [n for n in fns if n.lineno <= i <= n.end_lineno]
            dono = min(donos, key=lambda n: n.end_lineno - n.lineno) if donos else None
            corpo = "\n".join(linhas[dono.lineno - 1:dono.end_lineno]) if dono else fonte
            yield rel, (dono.name if dono else "<modulo>"), i, corpo


def test_toda_consulta_que_soma_filtra_so_a_prefeitura():
    faltando = []
    vistas = 0
    for rel, fn, linha, corpo in _consultas():
        vistas += 1
        if (rel, fn) in NAO_SOMAM or (rel, "*") in NAO_SOMAM:
            continue
        if not any(f in corpo for f in FILTROS):
            faltando.append(f"{rel}:{linha} ({fn})")
    assert vistas >= 15, "a varredura não achou as consultas — o teste não está olhando nada"
    assert not faltando, (
        "consulta de transferegov_propostas sem o filtro da prefeitura "
        "(`municipal IS NOT FALSE`) nem justificativa em NAO_SOMAM:\n  "
        + "\n  ".join(faltando))


# ---------------------------------------------------------------------------
# A lista marca e conta
# ---------------------------------------------------------------------------
class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def fetchall(self):
        return self._l


class _Db:
    def __init__(self, linhas):
        self.linhas = linhas
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params))
        return _Res(self.linhas)


class _Usuario:
    id = 1
    email = "a@b.c"
    name = "A"
    allowed_telas = None
    allowed_municipio_ids = None
    role = "admin"
    super_admin = True


def _linha(num, natureza, municipal):
    base = [num, "Em execução", "Órgão", "Proponente", None, "1", "900001", "Convênio",
            None, None, "Objeto", "Programa", "01/01/2025", "31/12/2030", None, None,
            None, "Normal", None, None, None, None, 1]
    return tuple(base + [natureza, municipal, None])     # None: sem árvore colhida


def _lista(db, **kw):
    from routers import transferegov as tg
    args = dict(categoria="geral", municipio_id=1, situacao=None, orgao=None,
                instrumento=None, proposta=None, proponente=None, cnpj=None, search=None,
                parlamentar=None, situacao_contratacao=None, vigencia=None, vig_fim_de=None,
                vig_fim_ate=None, recebedor=None, db=db, current=_Usuario())
    args.update(kw)
    return asyncio.run(tg.voluntarias(**args))


def test_a_lista_traz_tudo_marcado_e_conta_o_que_nao_e_da_prefeitura(monkeypatch):
    from routers import transferegov as tg
    monkeypatch.setattr(tg, "ensure_municipio_access", lambda *a, **k: None)
    monkeypatch.setattr(tg, "_guarda_categoria", lambda *a, **k: "transferegov_geral")
    db = _Db([_linha("000001/2025", "Administração Pública Municipal", True),
              _linha("000002/2025", "Administração Pública Estadual ou do Distrito Federal", False),
              _linha("000003/2025", None, None)])
    r = _lista(db)
    assert [i["municipal"] for i in r["items"]] == [True, False, True]
    assert r["fora_da_prefeitura"] == 1
    assert r["items"][1]["natureza_juridica"].startswith("Administração Pública Estadual")


@pytest.mark.parametrize("recebedor,trecho", [("prefeitura", "municipal IS NOT FALSE"),
                                              ("outros", "municipal IS FALSE")])
def test_o_filtro_de_recebedor_vai_para_o_sql(monkeypatch, recebedor, trecho):
    from routers import transferegov as tg
    monkeypatch.setattr(tg, "ensure_municipio_access", lambda *a, **k: None)
    monkeypatch.setattr(tg, "_guarda_categoria", lambda *a, **k: "transferegov_geral")
    db = _Db([])
    _lista(db, recebedor=recebedor)
    assert trecho in db.sql[0][0]


def test_o_pdf_repassa_o_filtro_de_recebedor():
    fonte = (BACKEND / "routers" / "export_pdf.py").read_text(encoding="utf-8")
    assert "recebedor=recebedor" in fonte


def test_a_migration_e_valida_e_esta_na_lista():
    import pglast
    from services.startup import MIGRATION_FILES
    sql = (BACKEND / "migrations" / "add_tg_natureza.sql").read_text(encoding="utf-8")
    pglast.parse_sql(sql)
    assert "ADD COLUMN IF NOT EXISTS natureza_juridica" in sql
    assert "ADD COLUMN IF NOT EXISTS municipal" in sql
    assert "add_tg_natureza.sql" in MIGRATION_FILES
    assert MIGRATION_FILES.index("add_tg_natureza.sql") < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
