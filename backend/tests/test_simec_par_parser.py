"""SIMEC PAR (`ingestion/simec_par.py`) — o relatório REAL de Monte Sião/MG.

A fixture é a página inteira baixada em 25/09/2026. Com o `html.parser`,
a tabela da ALIMENTAÇÃO ESCOLAR (PNAE) saía desmontada: 1 linha sem OB, que o
upsert descarta — a merenda escolar sumia de todos os tenants, sem erro. O
teste prende o parser ao que a página de verdade contém.
"""
import pathlib
from collections import Counter
from datetime import date

from ingestion import simec_par as sp

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "simec_par_monte_siao_2026-09-25.html"


def _libs():
    # a página se declara windows-1252 e traz um 0x81 solto (o navegador tolera)
    html = FIXTURE.read_bytes().decode("windows-1252", errors="replace")
    return sp.parse_relatorio(html)["liberacoes"]


def test_pnae_inteiro_e_gravavel():
    libs = _libs()
    por_programa = Counter(li["programa"] for li in libs)
    assert por_programa["ALIMENTAÇÃO ESCOLAR"] == 40
    assert por_programa["PNATE"] == 3 and por_programa["QUOTA"] == 2
    # o upsert só grava linha com data e OB: nenhuma pode ficar de fora
    assert all(li.get("dt_pgto") and li.get("ob") for li in libs)


def test_pnae_de_agosto_bate_com_a_cgu():
    """Agosto/2026: R$ 33.765,50 no arquivo de Transferências da CGU."""
    total = sum(li["valor"] for li in _libs()
                if li["programa"] == "ALIMENTAÇÃO ESCOLAR"
                and date(2026, 8, 1) <= li["dt_pgto"] <= date(2026, 8, 31))
    assert round(total, 2) == 33765.50
