"""A terceira porta do radar: BENEFICIARIO ESPECIFICO (17/09/2026).

O programa ja nomeia quem pode propor. A janela vem em DT_PROG_*_BENEF_ESP e os
nomeados em `siconv_programa_proponentes.zip`, com o CNPJ em
`siconv_proponentes.zip`. Medido em 17/09/2026: Nova Palma nomeada em 4 programas
abertos, Santa Maria em 13, Monte Siao em 3 — e o radar nao mostrava nenhum.

⚠️ O QUE ESTE ARQUIVO IMPEDE:
- a porta abrir para quem NAO esta na lista (porta que nao abre);
- casar municipio por NOME ("MUNICIPIO DE SANTA MARIA" pega Santa Maria do Herval);
- uma lista ilegivel apagar a lista boa da rodada anterior, sumindo com a porta
  de todo municipio por uma falha de download.

Rodar: python -m pytest backend/tests/test_radar_beneficiario.py -q
"""
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")

from ingestion import programas_captacao as P  # noqa: E402

HOJE = date(2026, 9, 17)
RAIZ = Path(__file__).resolve().parent.parent


def _linha(**kw):
    base = {
        "ID_PROGRAMA": "58001", "COD_PROGRAMA": "5600020260001",
        "NOME_PROGRAMA": "Novo PAC - Abastecimento de Água - FIN",
        "SIT_PROGRAMA": "DISPONIBILIZADO",
        "NATUREZA_JURIDICA_PROGRAMA": "Administração Pública Municipal",
        "UF_PROGRAMA": "RS",
        "DT_PROG_INI_RECEB_PROP": "", "DT_PROG_FIM_RECEB_PROP": "",
        "DT_PROG_INI_EMENDA_PAR": "", "DT_PROG_FIM_EMENDA_PAR": "",
        "DT_PROG_INI_BENEF_ESP": "01/09/2026", "DT_PROG_FIM_BENEF_ESP": "30/10/2026",
    }
    base.update(kw)
    return base


# ----------------------------------------------------------------- coleta ---

def test_programa_so_de_beneficiario_entra_com_as_datas():
    d = P.agrupa([_linha()], HOJE)["58001"]
    assert d["dt_ini_benef"] == date(2026, 9, 1)
    assert d["dt_fim_benef"] == date(2026, 10, 30)
    assert d["dt_fim_receb"] is None


def test_beneficiario_que_ainda_nao_abriu_nao_entra():
    """A janela tem dois lados tambem na porta nova."""
    assert not P.agrupa([_linha(DT_PROG_INI_BENEF_ESP="01/11/2026",
                                DT_PROG_FIM_BENEF_ESP="30/11/2026")], HOJE)


def test_linhas_por_UF_sem_recebimento_nao_derrubam_a_rodada():
    """⚠️ `dt_fim_receb` None em duas linhas do mesmo programa: a comparacao de
    prazo entre UFs nao pode levantar TypeError."""
    d = P.agrupa([_linha(UF_PROGRAMA="RS"), _linha(UF_PROGRAMA="MG")], HOJE)
    assert d["58001"]["ufs"] == {"RS", "MG"}


@pytest.mark.parametrize("bruto,esperado", [
    ("87612826000190", "87612826000190"),
    ("1179647000195", "01179647000195"),     # zero a esquerda perdido
    ("***47295***", None),                   # pessoa fisica mascarada
    ("", None),
    (None, None),
])
def test_cnpj_de(bruto, esperado):
    assert P.cnpj_de(bruto) == esperado


def test_listas_casam_por_id_e_devolvem_cnpj():
    lista = [{"ID_PROGRAMA": "1", "ID_PROPONENTE": "10"},
             {"ID_PROGRAMA": "1", "ID_PROPONENTE": "11"},
             {"ID_PROGRAMA": "2", "ID_PROPONENTE": "10"},
             {"ID_PROGRAMA": "999", "ID_PROPONENTE": "12"}]   # programa fechado
    proponentes = [{"ID_PROPONENTE": "10", "IDENTIF_PROPONENTE": "87612826000190"},
                   {"ID_PROPONENTE": "11", "IDENTIF_PROPONENTE": "***47295***"},
                   {"ID_PROPONENTE": "12", "IDENTIF_PROPONENTE": "11111111000111"}]
    r = P.listas_de_proponentes({"1", "2", "3"}, iter(lista), iter(proponentes))
    assert r == {"1": ["87612826000190"], "2": ["87612826000190"]}
    assert "3" not in r, "programa sem lista virou lista vazia (= ninguem pode)"


def test_cabecalho_mudado_devolve_None():
    r = P.listas_de_proponentes({"1"}, iter([{"ID_PROGRAMA": "1", "PROPONENTE": "10"}]), iter([]))
    assert r is None


def test_lista_que_nao_cita_nenhum_programa_aberto_devolve_None():
    """Com 100+ programas abertos, zero listas e arquivo truncado."""
    r = P.listas_de_proponentes({"1", "2"}, iter([{"ID_PROGRAMA": "9", "ID_PROPONENTE": "10"}]),
                                iter([{"ID_PROPONENTE": "10", "IDENTIF_PROPONENTE": "87612826000190"}]))
    assert r is None


def test_cadastro_sem_nenhum_cnpj_dos_listados_devolve_None():
    r = P.listas_de_proponentes({"1"}, iter([{"ID_PROGRAMA": "1", "ID_PROPONENTE": "10"}]),
                                iter([{"ID_PROPONENTE": "77", "IDENTIF_PROPONENTE": "87612826000190"}]))
    assert r is None


# -------------------------------------------------------------------- run ---

class _Cursor:
    def __init__(self):
        self.execs = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.execs.append((sql, params))

    def fetchone(self):
        return (0,)

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self._c = cur

    def cursor(self):
        return self._c

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _rodar(monkeypatch, lista, proponentes):
    cur = _Cursor()

    def linhas(nome):
        return iter({P.ARQUIVO: [_linha()], P.ARQUIVO_LISTA: lista,
                     P.ARQUIVO_PROPONENTES: proponentes}[nome])

    monkeypatch.setattr(P, "_linhas", linhas)
    monkeypatch.setattr(P.psycopg2, "connect", lambda _d: _Conn(cur))
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://x/y")
    P.run()
    upsert = next(p for s, p in cur.execs if "INSERT INTO programas_captacao" in s)
    log = next(p for s, p in cur.execs if "ingestion_log" in s)
    return upsert, log


def test_run_grava_a_lista_e_sai_success(monkeypatch):
    upsert, log = _rodar(monkeypatch,
                         [{"ID_PROGRAMA": "58001", "ID_PROPONENTE": "5382"}],
                         [{"ID_PROPONENTE": "5382", "IDENTIF_PROPONENTE": "87612826000190"}])
    assert upsert[-2] == ["87612826000190"]
    assert upsert[-1] is True, "lista legivel tem de sobrescrever a anterior"
    assert log[1] == "success"


def test_run_com_lista_ilegivel_preserva_a_anterior_e_sai_partial(monkeypatch):
    """⚠️ O CASO QUE APAGARIA A PORTA DE TODO MUNICIPIO."""
    upsert, log = _rodar(monkeypatch, [{"COLUNA_NOVA": "x"}], [])
    assert upsert[-1] is False, "lista ilegivel sobrescreveu a lista boa da rodada anterior"
    assert log[1] == "partial"
    assert "proponentes" in (log[3] or "")


def test_o_upsert_so_troca_a_lista_quando_ela_foi_lida():
    import pglast
    sql = P._SQL.replace("%s", "NULL")
    assert pglast.parse_sql(sql)
    assert "ELSE programas_captacao.proponentes_cnpj" in P._SQL


# ------------------------------------------------------------------- rota ---

def test_a_porta_de_beneficiario_exige_o_CNPJ_na_lista():
    """⚠️ Sem o `ANY(proponentes_cnpj)` DENTRO de `porta_benef`, o programa que
    nomeia 229 municipios apareceria para os 5.570."""
    rota = (RAIZ / "routers" / "programas_captacao.py").read_text(encoding="utf-8")
    cte = rota[rota.index("_CTE_ABERTOS = "):rota.index("_FILTRO_ABERTOS = ")]
    trecho = cte[cte.index("COALESCE(p.dt_fim_benef"):cte.index("AS porta_benef")]
    assert ":cnpj = ANY(p.proponentes_cnpj)" in trecho
    assert "(porta_receb OR porta_emenda OR porta_benef)" in rota


def test_a_chave_do_municipio_e_o_CNPJ_e_nunca_o_nome():
    rota = (RAIZ / "routers" / "programas_captacao.py").read_text(encoding="utf-8")
    assert "NM_PROPONENTE" not in rota
    # Listagem, contagem e ficha montam a mesma CTE, e as tres tem de mandar o
    # CNPJ normalizado — senao o selo "nomeado" diverge entre lista e ficha.
    for funcao in ("async def radar", "async def contagem", "async def ficha"):
        corpo = rota[rota.index(funcao):]
        corpo = corpo[:corpo.find("\n@router", 1) if "\n@router" in corpo[1:] else len(corpo)]
        assert "_CTE_ABERTOS" in corpo and '"cnpj": cnpj' in corpo, funcao


def test_a_tela_mostra_o_municipio_nomeado():
    tela = (RAIZ.parent / "frontend" / "src" / "app" / "dashboard"
            / "transferegov-radar" / "page.tsx").read_text(encoding="utf-8")
    assert "município nomeado" in tela
    assert "cnpj_cadastrado === false" in tela, (
        "sem o aviso, municipio sem CNPJ le 'nenhum programa nomeia' como fato")
