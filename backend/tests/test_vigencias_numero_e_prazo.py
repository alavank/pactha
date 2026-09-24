"""Relatório de vigências da Freitas (23/09/2026): o número do convênio estadual, a
alteração de prazo do SIGCON e o recorte/valor das federais.

O que estes testes seguram, com os casos que a cliente mandou:
  - Martinho Campos mostrava 9342516 (o SIAFI) no "Nº"; o número do convênio é
    1481002318/2022 (dado aberto do Estado, "Número Convênio SIGCON");
  - a prorrogação em andamento aparece como o SIGCON a mostra, sem classificar;
  - proposta federal em análise não é instrumento vencendo, e a federal tem valor.

Rodar:
    python -m pytest backend/tests/test_vigencias_numero_e_prazo.py -v
"""
import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from routers import convenios as cv
from services.fases_voluntaria import INSTRUMENTO_VIGENTE_SQL


def _conv(**kw):
    base = dict(id=1, fonte="SIGCON", nr_sigcon="9342516", nr_siafi="9342516", raw_data={},
                municipio_id=7, objeto="Cobertura de Quadra Poliesportiva", orgao_concedente="SEDESE",
                dt_vigencia_atual=date.today() + timedelta(days=42), valor_total=346338.80,
                situacao="Em vigor")
    base.update(kw)
    return SimpleNamespace(**base)


# ------------------------------------------------------------ o número ------
def test_numero_vem_da_grade_logada_do_SIGCON():
    assert cv.nr_convenio_estadual(_conv(raw_data={"nr_instrumento": "1481002318/2022"})) == "1481002318/2022"


def test_numero_vem_do_dado_aberto_quando_a_grade_nao_trouxe():
    c = _conv(raw_data={"nr_instrumento": "", "sigcon": "1481002318/2022"})
    assert cv.nr_convenio_estadual(c) == "1481002318/2022"


def test_o_SIAFI_e_o_plano_NUNCA_viram_numero_do_convenio():
    assert cv.nr_convenio_estadual(_conv()) is None, "9342516 é o SIAFI"
    assert cv.nr_convenio_estadual(_conv(nr_sigcon="002294/2022")) is None, "6/ano é o plano"
    assert cv.nr_convenio_estadual(_conv(nr_sigcon="1481002318/2022")) == "1481002318/2022"
    assert cv.nr_convenio_estadual(_conv(raw_data={"sigcon": "lixo"})) is None


def test_ES_usa_o_numero_publicado_e_FNS_nunca():
    es = _conv(fonte="GCONV-ES", nr_sigcon="GCONV-ES-123", raw_data={"numOriginal": "004/2026"})
    assert cv.nr_convenio_estadual(es) == "004/2026"
    fns = _conv(fonte="FNS", nr_sigcon="FNS-316500-2017-X-N/A-9001", raw_data={"nr_instrumento": "x/2020"})
    assert cv.nr_convenio_estadual(fns) is None


# --------------------------------------------------- a alteração de prazo ----
def test_a_alteracao_de_PRAZO_mais_recente_vence_uma_alteracao_simples_posterior():
    raw = {"alteracoes": [
        {"tipo": "PRORROGAÇÃO DE OFÍCIO", "situacao": "PUBLICADA", "data": "13/12/2023"},
        {"tipo": "TERMO ADITIVO", "situacao": "ASSINATURA DO CONCEDENTE", "data": "02/09/2026"},
        {"tipo": "ALTERAÇÃO SIMPLES", "situacao": "CONCLUÍDA", "data": "10/09/2026"},
    ], "ultima_alteracao_tipo": "ALTERAÇÃO SIMPLES"}
    assert cv.alteracao_de_prazo(raw) == {"tipo": "TERMO ADITIVO",
                                          "situacao": "ASSINATURA DO CONCEDENTE", "data": "02/09/2026"}


def test_sem_lista_usa_a_ultima_e_sem_nada_nao_afirma_nada():
    assert cv.alteracao_de_prazo({"ultima_alteracao_tipo": "TERMO ADITIVO",
                                  "ultima_alteracao_situacao": "CADASTRAMENTO DA ALTERAÇÃO",
                                  "ultima_alteracao_data": "01/09/2026"})["situacao"] == "CADASTRAMENTO DA ALTERAÇÃO"
    assert cv.alteracao_de_prazo({}) == {} and cv.alteracao_de_prazo(None) == {}


# ------------------------------------------------ a consulta dos alertas ----
class _Scalars:
    def __init__(self, xs):
        self._xs = xs

    def all(self):
        return self._xs


class _Res:
    def __init__(self, xs=None, rows=None):
        self._xs, self._rows = xs or [], rows or []

    def scalars(self):
        return _Scalars(self._xs)

    def fetchall(self):
        return self._rows

    def mappings(self):
        return self

    def all(self):
        return []


class _Db:
    def __init__(self, estaduais, federais):
        self.estaduais, self.federais, self.sqls = estaduais, federais, []

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.sqls.append(s)
        if "transferegov_propostas" in s:
            return _Res(rows=self.federais)
        if "convenios_estadual" in s:
            return _Res(xs=self.estaduais)
        return _Res()


def test_alertas__estadual_com_numero_SIAFI_e_alteracao__federal_so_instrumento_e_com_valor():
    fim = (date.today() + timedelta(days=30)).strftime("%d/%m/%Y")
    est = _conv(raw_data={"nr_instrumento": "1481002318/2022", "alteracoes": [
        {"tipo": "TERMO ADITIVO", "situacao": "ASSINATURA DO CONCEDENTE", "data": "02/09/2026"}]})
    fed = [("012345/2024", "941314", "Pavimentação", "MINISTÉRIO", "Em execução", fim, 7, "250000.00")]
    db = _Db([est], fed)
    alertas = asyncio.run(cv.query_alertas_vigencia(db, municipio_ids=[7], dias=120))
    e = next(a for a in alertas if a.esfera == "estadual")
    assert e.nr_convenio == "1481002318/2022" and e.nr_siafi == "9342516"
    assert e.alteracao_tipo == "TERMO ADITIVO" and e.alteracao_situacao == "ASSINATURA DO CONCEDENTE"
    f = next(a for a in alertas if a.esfera == "voluntaria")
    assert f.valor_total == 250000.0, "a federal saía SEMPRE sem valor"
    sql_fed = next(s for s in db.sqls if "transferegov_propostas" in s)
    assert INSTRUMENTO_VIGENTE_SQL in sql_fed, "proposta em análise não é instrumento vencendo"
    assert "valor_global" in sql_fed


def test_o_que_vence_HOJE_vai_para_o_TOPO_do_arquivo():
    """`0 or 9999` = 9999 em Python: o instrumento de 0 dias ia para o fim da lista
    "menor prazo primeiro" do arquivo exportado."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "routers" / "export_pdf.py").read_text(encoding="utf-8")
    trecho = src[src.index("alertas = sorted(alertas, key=lambda a:"):][:260]
    assert "is not None" in trecho and ' or 9999' not in trecho
