"""PNAB 2027 / Sistema Nacional de Cultura: o coletor `ingestion/snc_cultura.py` e a
conta da aba Cultura da Regularidade (`services/cultura_pnab.py`), contra recortes
REAIS da página de adesão do SNC (26/09/2026) em `fixtures/snc_cultura/` — só o bloco
que o coletor lê, sem o dado pessoal que a página traz."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion import snc_cultura as s
from services.cultura_pnab import e_fundo_de_cultura, montar

FIX = Path(__file__).parent / "fixtures" / "snc_cultura"
PREF_MS = "22646525000131"


def _pag(ibge: int) -> dict:
    return s.ler_pagina((FIX / f"detalhar_{ibge}.html").read_text(encoding="utf-8"))


def test_monte_siao_sem_adesao_e_sem_fundo():
    d = _pag(3143401)
    assert d["situacao"] == "Nao possui adesão"
    assert d["data_publicacao"] is None
    assert len(d["componentes"]) == 5 and not any(c["registrado"] for c in d["componentes"])
    assert s.fundo_registrado(d["componentes"]) is False


def test_santa_maria_com_fundo_e_documento():
    d = _pag(4316907)
    assert d["situacao"] == "Publicado no DOU"
    assert d["data_publicacao"] == date(2017, 6, 16)
    fundo = next(c for c in d["componentes"] if "Fundo" in c["nome"])
    assert fundo["registrado"] and fundo["documento"].startswith("https://snc.cultura.gov.br/media/")
    assert s.fundo_registrado(d["componentes"]) is True
    # A ata do conselho não registrada convive com as leis registradas.
    ata = next(c for c in d["componentes"] if c["nome"].startswith("Ata"))
    assert ata["registrado"] is False and ata["documento"] is None


def test_nova_palma_fundo_na_lei_do_sistema():
    d = _pag(4313102)
    assert d["data_publicacao"] == date(2015, 12, 4)
    assert s.fundo_registrado(d["componentes"]) is True


def test_nenhum_dado_pessoal_sai_do_coletor():
    for i in (3143401, 4313102, 4316907):
        d = _pag(i)
        assert set(d) == {"situacao", "data_publicacao", "componentes"}
        assert "@" not in str(d)


def test_layout_mudado_e_recusado():
    with pytest.raises(s.PaginaRecusada):
        s.ler_pagina("<html><body>manutenção</body></html>")


@pytest.mark.parametrize("txt,esperado", [("16 de Junho de 2017", date(2017, 6, 16)),
                                          ("4 de Março de 2015", date(2015, 3, 4)),
                                          ("Sem data de publicação", None)])
def test_data_extenso(txt, esperado):
    assert s.data_extenso(txt) == esperado


# --- a conta da aba ----------------------------------------------------------
def _snc(fundo: bool):
    return {"situacao": "Publicado no DOU", "data_publicacao": date(2015, 12, 4),
            "componentes": [], "fundo_registrado": fundo, "lido_em": None}


def _p(doc, nome, v):
    return {"favorecido_doc": doc, "favorecido_nome": nome, "valor": Decimal(str(v))}


def test_pnab_no_fundo_de_cultura_e_ok_mesmo_sem_registro_no_snc():
    r = montar(snc=_snc(False), pnab=[_p("11111111000111", "FUNDO MUNICIPAL DE CULTURA DE X", 90000)],
               cnpj_prefeitura=PREF_MS)
    assert r["situacao"] == "ok" and r["recebe_no_fundo"] is True


def test_lei_registrada_mas_pnab_na_prefeitura_e_atencao():
    r = montar(snc=_snc(True), pnab=[_p(PREF_MS, "MUNICIPIO DE MONTE SIAO", 90000)],
               cnpj_prefeitura=PREF_MS)
    assert r["situacao"] == "atencao" and r["pnab_12m"] == 90000.0


def test_nada_a_vista_e_risco():
    r = montar(snc=_snc(False), pnab=[_p(PREF_MS, "MUNICIPIO DE MONTE SIAO", 90000)],
               cnpj_prefeitura=PREF_MS)
    assert r["situacao"] == "risco"


def test_snc_nao_lido_nunca_e_risco():
    r = montar(snc=None, pnab=[], cnpj_prefeitura=PREF_MS)
    assert r["situacao"] == "sem_dado" and r["fundo_registrado_snc"] is None


def test_prefeitura_com_cultura_no_nome_nao_e_fundo():
    """"SECRETARIA DE CULTURA" ou a prefeitura não contam como fundo."""
    assert e_fundo_de_cultura("FUNDO MUNICIPAL DE CULTURA") is True
    assert e_fundo_de_cultura("FUNDO MUN. DE CULTURA E TURISMO") is True
    assert e_fundo_de_cultura("SECRETARIA MUNICIPAL DE CULTURA") is False
    r = montar(snc=_snc(False), pnab=[_p(PREF_MS, "FUNDO MUNICIPAL DE CULTURA", 1)],
               cnpj_prefeitura=PREF_MS)
    assert r["recebe_no_fundo"] is False           # o CNPJ é o da prefeitura


def test_migration_registrada():
    from services.startup import MIGRATION_FILES
    assert MIGRATION_FILES.index("add_snc_cultura.sql") < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    sql = (Path(__file__).parents[1] / "migrations" / "add_snc_cultura.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS snc_cultura" in sql
    for c in ("situacao", "data_publicacao", "componentes", "fundo_registrado", "lido_em"):
        assert f"\n    {c} " in sql
