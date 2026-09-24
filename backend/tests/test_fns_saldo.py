"""Saldo das contas do Fundo Municipal pelo arquivo anual do Portal FNS (24/09/2026).

Os arquivos sintéticos repetem os dois formatos medidos: CSV de 2020 (Latin-1,
separado por VÍRGULA, tudo entre aspas, vírgula decimal) e XLSX de 2025.
"""
import io
from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest

from ingestion import fns_saldo as fs

CAB = ["BLOCO", "GRUPO", "ESTRATÉGIA", "UF", "MUNICIPIO", "CO_MUNICIPIO_IBGE",
       "QT_POPULACAO", "NU_ANO_REFERENCIA_IBGE", "CNPJ", "ENTIDADE", "BANCO", "AGENCIA",
       "CONTA", "TP_REPASSE", "TP_REPASSE_ESTADO", "ST_FAF", "ST_HU",
       "DT_ULTIMA_LIBERACAO", "VL_BRUTO", "VL_LIQUIDO", "VL_SALDO_CONTA", "DT_SALDO_CONTA"]


def _linha(estrategia, conta="000000254630", liquido="1000,50", saldo="1844208,59",
           ibge="314340", tp="MUNICIPAL", cnpj="11875540000135"):
    return ["Manutenção", "VIGILÂNCIA EM SAÚDE", estrategia, "MG", "MONTE SIAO", ibge,
            "25107", "2025", cnpj, "FUNDO MUNICIPAL DE SAUDE", "001", "02791X", conta,
            tp, "N", "S", "N", "31/12/2025", liquido, liquido, saldo, "30/11/2025"]


def _csv(linhas) -> bytes:
    q = lambda v: '"' + str(v) + '"'  # noqa: E731
    texto = ",".join(q(c) for c in CAB) + "\r\n" + "\r\n".join(",".join(q(v) for v in ln) for ln in linhas)
    return texto.encode("latin-1")


def _xlsx(linhas) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([c.replace("É", "E") for c in CAB])    # o de 2025 vem sem acento
    for ln in linhas:
        r = list(ln)
        r[18] = r[19] = float(str(r[19]).replace(",", "."))
        r[20] = float(str(r[20]).replace(".", "").replace(",", "."))
        r[21] = datetime(2025, 11, 30)
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_arquivo_mais_recente_pelo_ano_do_nome():
    html = """
      <a href="https://portalfns.saude.gov.br/wp-content/uploads/2021/12/REPASSE-FAF-COM-POPULACAO-2020.csv">
      <a href="https://portalfns.saude.gov.br/wp-content/uploads/2022/01/REPASSE-FAF-COM-POPULACAO-2021-1.csv">
      <a href="https://portalfns.saude.gov.br/wp-content/uploads/2023/01/REPASSE-FAF-COM-POPULACAO-v4-2022.csv">
      <a href="https://portalfns.saude.gov.br/wp-content/uploads/2026/01/REPASSE-FAF-COM-POPULACAO-2025.xlsx">
      <a href="https://portalfns.saude.gov.br/wp-content/uploads/2020/06/RelatoriodeGestao2009FNS.pdf">"""
    ano, url = fs.arquivo_mais_recente(html)
    assert ano == 2025 and url.endswith("POPULACAO-2025.xlsx")
    assert fs.arquivo_mais_recente("<html>nada</html>") is None


@pytest.mark.parametrize("fabrica,url", [(_csv, "x/A-2020.csv"), (_xlsx, "x/A-2025.xlsx")])
def test_um_saldo_por_conta_e_o_repassado_somado(fabrica, url):
    """Armadilha 3: o arquivo repete o saldo em cada estratégia da mesma conta."""
    conteudo = fabrica([
        _linha("VIGILANCIA", liquido="1000,50"),
        _linha("ENDEMIAS", liquido="2000,25"),
        _linha("PISO ENFERMAGEM", conta="000000254657", liquido="10,00", saldo="9106,72"),
        _linha("OUTRO MUNICIPIO", ibge="999999"),
        _linha("FUNDO DO ESTADO", tp="ESTADUAL"),
    ])
    contas, n = fs.contas_por_municipio(fs.linhas_do_arquivo(conteudo, url), {"314340": 7})
    assert n == 5
    assert len(contas) == 2
    c = contas[(7, "11875540000135", "001", "02791X", "000000254630")]
    assert c["saldo"] == Decimal("1844208.59")          # UMA vez, não 2x
    assert c["repassado_ano"] == Decimal("3000.75")     # o repassado, sim, soma
    assert c["dt_saldo"] == date(2025, 11, 30)
    assert [e["estrategia"] for e in c["estrategias"]] == ["VIGILANCIA", "ENDEMIAS"]


def test_coluna_ausente_recusa_o_arquivo():
    texto = _csv([_linha("X")]).decode("latin-1").replace('"VL_SALDO_CONTA"', '"VL_SALDO"')
    with pytest.raises(ValueError, match="VL_SALDO_CONTA"):
        list(fs.linhas_do_arquivo(texto.encode("latin-1"), "x/A-2020.csv"))


def test_data_traco_e_vazia():
    assert fs._data("-") is None
    assert fs._data("30/11/2025") == date(2025, 11, 30)
    assert fs._data(datetime(2025, 11, 30)) == date(2025, 11, 30)


class _Cur:
    def __init__(self, contagem=0):
        self.sql, self.contagem = [], contagem

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return (self.contagem,)


def test_ja_carregado_exige_todos_os_municipios():
    assert fs.ja_carregado(_Cur(contagem=2), 2025, "u", [1, 2]) is True
    # Município novo no tenant = baixa de novo, mesmo com o arquivo igual.
    assert fs.ja_carregado(_Cur(contagem=1), 2025, "u", [1, 2]) is False


def test_grava_troca_o_ano_inteiro(monkeypatch):
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        lambda cur, sql, seq, page_size=100: [cur.execute(sql, p) for p in seq])
    contas, _ = fs.contas_por_municipio(
        fs.linhas_do_arquivo(_csv([_linha("A")]), "x/A-2020.csv"), {"314340": 7})
    cur = _Cur()
    fs.grava(cur, contas, 2025, "u", [7])
    assert cur.sql[0][0].startswith("DELETE FROM fns_saldo_conta WHERE ano = %s")
    assert cur.sql[0][1] == (2025, [7])
    ins = [p for s, p in cur.sql if s.startswith("INSERT")]
    assert len(ins) == 1 and ins[0]["ano"] == 2025 and ins[0]["saldo"] == Decimal("1844208.59")
