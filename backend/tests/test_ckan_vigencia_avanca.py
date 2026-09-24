"""O backfill do CKAN passa a AVANÇAR a vigência com a data oficial publicada
(23/09/2026) e a guardar o número do convênio do Estado.

Antes era COALESCE: só preenchia coluna vazia e nunca atualizava — a prorrogação
publicada ficava fora do relatório de vigências até o scraper logado reabrir o
detalhe. Relato da Freitas (Arapuá): "acredito que não está atualizado".

Rodar:
    python -m pytest backend/tests/test_ckan_vigencia_avanca.py -v
"""
import gzip
import re
from datetime import date

import pytest

from ingestion import sigcon_ckan_backfill as bf


def _gz(cab, linhas) -> bytes:
    txt = ";".join(cab) + "\n" + "".join(";".join(str(c) for c in l) + "\n" for l in linhas)
    return gzip.compress(b"\xef\xbb\xbf" + txt.encode("utf-8"))


CAB = ["id_convenio", "nome", "objetivo", "vr_contra_public", "dt_vigencia_inicial",
       "dt_vigencia_final", "dt_vigencia_atual", "dt_publicacao", "fl_versao",
       "nr_siafi", "nr_sigcon", "nr_plano_sigcon", "tp_instrumento"]


def _dump():
    return _gz(CAB, [
        # Martinho Campos (medido no dado aberto de 22/09/2026)
        ["68362", "COBERTURA DE QUADRA POLIESPORTIVA", "", "66338,80", "2024-06-28", "2024-06-28",
         "2026-11-04", "2022-06-30", "1", "9342516", "1481002318/2022", "002294/2022", "CONVENIO"],
        # um SIAFI que aponta para DOIS convênios (acontece até 2016)
        ["10", "A", "", "", "", "", "2026-12-01", "", "1", "5001064", "0821/2014", "", "CONVENIO"],
        ["11", "B", "", "", "", "", "2027-01-01", "", "1", "5001064", "5191000116/2016", "", "CONVENIO"],
    ])


def test_o_indice_guarda_o_numero_do_convenio_e_marca_o_SIAFI_ambiguo():
    by_siafi, by_sigcon, by_id = bf._index_dataset(_dump())
    assert by_siafi["9342516"]["sigcon"] == "1481002318/2022"
    assert by_siafi["9342516"]["ambiguo"] is False
    assert by_siafi["5001064"]["ambiguo"] is True, "SIAFI de dois convênios não pode escrever nada"
    assert by_siafi["9342516"]["vig_atual"] == date(2026, 11, 4)


def test_os_parametros__vigencia_so_avanca_e_ambiguo_nao_escreve():
    by_siafi, _, _ = bf._index_dataset(_dump())
    p = bf._params_enriquece(by_siafi["9342516"], None, 99)
    # (contra, vig_ini, vig_atual, ambiguo, vig_atual, vig_atual|fim, vig_fim, dt_pub, obj,
    #  repassado, repassado, sigcon, sigcon, cid)
    assert p[2] == date(2026, 11, 4) and p[3] is False and p[4] == date(2026, 11, 4)
    assert p[11] == p[12] == "1481002318/2022" and p[-1] == 99
    amb = bf._params_enriquece(by_siafi["5001064"], None, 5)
    assert amb[3] is True and amb[11] == "", "com SIAFI ambíguo o número não é gravado"


def test_o_UPDATE_e_SQL_valido__GREATEST_so_sem_ambiguidade__numero_em_chave_propria():
    pglast = pytest.importorskip("pglast")
    n = bf._SQL_ENRIQUECE.count("%s")
    assert n == len(bf._params_enriquece({"contra": None, "vig_ini": None, "vig_atual": None,
                                          "vig_fim": None, "sigcon": ""}, None, 1))
    i = iter(range(1, n + 1))
    pglast.parse_sql(re.sub(r"%s", lambda _m: f"${next(i)}", bf._SQL_ENRIQUECE))
    sql = " ".join(bf._SQL_ENRIQUECE.split())
    assert "GREATEST(dt_vigencia_atual" in sql, "a prorrogação publicada tem de AVANÇAR a data"
    assert "ELSE COALESCE(dt_vigencia_atual" in sql
    assert "jsonb_build_object('sigcon'" in sql and "raw_data->>'sigcon'" in sql
    assert "nr_instrumento" not in sql, "o número vai numa chave SÓ deste coletor"
