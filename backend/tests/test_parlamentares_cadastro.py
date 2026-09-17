"""Cadastro de parlamentares: o nome da emenda vira partido, UF, cargo e foto.

⚠️ O QUE ESTE ARQUIVO IMPEDE:
- partido ERRADO ao lado de um nome (dois "Bebeto" na mesma legislatura, um PSB-BA
  e outro PP-RJ): a tela afirma o que mostra, entao na duvida nao casa;
- a ordem das paginas decidir o partido (o da legislatura mais recente vale);
- a grafia antiga do nome se perder quando a Camara renomeia o deputado
  ("Reinhold Stephanes Junior" -> "Stephanes Junior": 1.400 emendas, 17/09/2026);
- apostrofo e espaco separarem a mesma pessoa ("CHICO D ANGELO" x "Chico D'Angelo").

Medido em 17/09/2026 com as APIs reais: 99,05% das emendas federais individuais
do `siconv_emenda.zip` casam com o cadastro.

Rodar: python -m pytest backend/tests/test_parlamentares_cadastro.py -q
"""
import re
from pathlib import Path

import pytest

from ingestion import parlamentares_cadastro as C
from services.nome_parlamentar import chave_nome, escolhe_cadastro

RAIZ = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------- chave_nome ---

@pytest.mark.parametrize("fonte,casa", [
    ("CHICO D ANGELO", "Chico D'Angelo"),
    ("JOSE PRIANTE", "José Priante"),
    ("  paulo   teixeira ", "PAULO TEIXEIRA"),
])
def test_chave_nome_ignora_acento_apostrofo_e_espaco(fonte, casa):
    assert chave_nome(fonte) == chave_nome(casa)


def test_chave_nome_vazia():
    assert chave_nome(None) == "" and chave_nome("") == ""


# --------------------------------------------------------------- leitores ---

def test_de_camara():
    r = C.de_camara({"id": 204379, "nome": "Acácio Favacho", "siglaPartido": "MDB",
                     "siglaUf": "AP", "urlFoto": "https://x/204379.jpg"}, 57)
    assert r["casa"] == "camara" and r["id_externo"] == "204379"
    assert r["partido"] == "MDB" and r["uf"] == "AP" and r["cargo"] == "Deputado(a) Federal"
    assert r["nomes_norm"] == {"ACACIOFAVACHO"} and r["legislaturas"] == {57}


def test_camara_tira_o_asterisco_do_partido_extinto():
    r = C.de_camara({"id": 1, "nome": "Márcio Reinaldo Moreira", "siglaPartido": "PP**"}, 54)
    assert r["partido"] == "PP"


def test_de_senado_pega_a_UF_do_mandato_e_o_nome_civil():
    item = {"IdentificacaoParlamentar": {"CodigoParlamentar": "5740",
                                         "NomeParlamentar": "Fabio Garcia",
                                         "NomeCompletoParlamentar": "Fabio Paulino Garcia"},
            "Mandatos": {"Mandato": {"UfParlamentar": "MT"}}}   # dict, e nao lista
    r = C.de_senado(item, 57)
    assert r["uf"] == "MT" and r["cargo"] == "Senador(a)"
    assert r["nomes_norm"] == {"FABIOGARCIA", "FABIOPAULINOGARCIA"}
    assert r["foto_url"].endswith("senador5740.jpg")
    assert r["partido"] is None, "a lista por legislatura nao traz partido"


def test_de_almg():
    r = C.de_almg({"id": 12193, "nome": "Adalclever Lopes", "partido": "PV"}, 57)
    assert r["uf"] == "MG" and r["cargo"] == "Deputado(a) Estadual" and r["partido"] == "PV"


@pytest.mark.parametrize("ruim", [{}, {"id": 1}, {"nome": "X"}])
def test_item_sem_id_ou_nome_e_descartado(ruim):
    assert C.de_camara(ruim, 57) is None
    assert C.de_almg(ruim, 57) is None


# ----------------------------------------------------------------- mescla ---

def test_mescla_usa_o_partido_da_legislatura_mais_recente_em_qualquer_ordem():
    nova = C.de_camara({"id": 1, "nome": "Stephanes Junior", "siglaPartido": "PL",
                        "siglaUf": "PR"}, 56)
    velha = C.de_camara({"id": 1, "nome": "Reinhold Stephanes Junior",
                         "siglaPartido": "PMDB", "siglaUf": "PR"}, 54)
    for ordem in ([nova, velha], [velha, nova]):
        r = C.mescla(ordem)[("camara", "1")]
        assert r["partido"] == "PL", "a ordem das paginas decidiu o partido"
        assert r["legislaturas"] == {54, 56}
        assert r["nomes_norm"] == {"STEPHANESJUNIOR", "REINHOLDSTEPHANESJUNIOR"}, (
            "a grafia antiga se perdeu — a emenda antiga fica sem partido")


# ------------------------------------------------------- escolhe_cadastro ---

def _c(casa, ide, uf, partido, legs, cargo="Deputado(a) Federal", foto=None):
    return {"casa": casa, "id_externo": ide, "uf": uf, "partido": partido,
            "legislaturas": legs, "cargo": cargo, "foto_url": foto}


def test_um_candidato_so():
    c = _c("camara", "1", "SP", "PT", [57])
    assert escolhe_cadastro([c]) is c


def test_sem_candidato():
    assert escolhe_cadastro([]) is None


def test_deputado_que_virou_senador_vale_o_mandato_mais_recente():
    dep = _c("camara", "1", "AL", "MDB", [54])
    sen = _c("senado", "2", "AL", "MDB", [57], cargo="Senador(a)")
    assert escolhe_cadastro([dep, sen]) is sen


def test_mesma_pessoa_nas_duas_casas_junta_os_cargos():
    """Reginete Bispo: suplente no Senado (56-57) e deputada (57), PT-RS."""
    dep = _c("camara", "221378", "RS", "PT", [57], foto="https://camara/foto.jpg")
    sen = _c("senado", "6018", "RS", "PT", [56, 57], cargo="Senador(a)")
    r = escolhe_cadastro([dep, sen])
    assert r["partido"] == "PT" and r["uf"] == "RS"
    assert r["cargo"] == "Deputado(a) Federal e Senador(a)"
    assert r["foto_url"] == "https://camara/foto.jpg"


def test_homonimos_na_mesma_legislatura_nao_casam():
    """⚠️ "Bebeto" PP-RJ (deputado, 57) e "Bebeto" PSB-BA (senador, 56-57)."""
    rj = _c("camara", "220612", "RJ", "PP", [57])
    ba = _c("senado", "5554", "BA", "PSB", [56, 57], cargo="Senador(a)")
    assert escolhe_cadastro([rj, ba]) is None


# -------------------------------------------------------------- migration ---

def _sql():
    return (RAIZ / "migrations" / "add_parlamentares_cadastro.sql").read_text(encoding="utf-8")


def test_migration_registrada():
    from services.startup import MIGRATION_FILES
    assert "add_parlamentares_cadastro.sql" in MIGRATION_FILES
    assert MIGRATION_FILES[-1] == "add_auditoria_imutavel.sql"


def test_migration_e_sql_valido():
    pglast = pytest.importorskip("pglast")
    assert pglast.parse_sql(_sql())


def test_tabela_nova_nao_reusa_nome_derrubado():
    """`drop_lean_tables.sql` derruba `emendas`, `emendas_camara` e
    `dados_eleitorais` — reusar um desses nomes apagaria o cadastro."""
    drop = (RAIZ / "migrations" / "drop_lean_tables.sql").read_text(encoding="utf-8")
    derrubadas = set(re.findall(r"DROP TABLE IF EXISTS (\w+)", drop))
    for tabela in ("parlamentares_cadastro", "parlamentares_apelidos"):
        assert tabela not in derrubadas


def test_apelidos_estao_em_chave_nome():
    """A chave do apelido tem de sair de `chave_nome`, senao nunca casa."""
    pares = re.findall(r"\('([^']+)',\s+'([^']+)'", _sql())
    assert len(pares) >= 7
    for fonte, alvo in pares:
        assert fonte == chave_nome(fonte) and alvo == chave_nome(alvo), (fonte, alvo)


def test_upsert_nao_apaga_partido_nem_grafia():
    sql = C._SQL
    assert "COALESCE(EXCLUDED.partido, parlamentares_cadastro.partido)" in sql
    assert "parlamentares_cadastro.nomes_norm || EXCLUDED.nomes_norm" in sql
    assert "DELETE" not in sql.upper()


# ------------------------------------------------------------------ fiacao ---

def test_entra_no_cron_e_no_vigia():
    cron = (RAIZ / "ingestion" / "run_dadosabertos_cron.py").read_text(encoding="utf-8")
    assert '"ingestion.parlamentares_cadastro"' in cron
    from ingestion.watchdog_coleta import FRESCOR_HORAS_NACIONAL
    assert FRESCOR_HORAS_NACIONAL.get(C.FONTE) == 30
