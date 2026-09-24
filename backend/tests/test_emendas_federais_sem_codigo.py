"""«Execução consultada em 36 de 37» — a linha SEM Nº DA EMENDA (24/09/2026).

Pergunta da Laiza (Nova Serrana/MG): "é só um aviso ou ainda não está puxando
todos os dados?". O aviso "parcial" dizia duas coisas falsas:

1. "Onde a execução aparece como «—», o dado ainda não foi buscado" — a emenda
   «Sem registro na CGU» FOI buscada (agregados_em gravado, achou_agregado=false)
   e também mostra «—».
2. "ainda não" — a linha da carteira SEM `codigo_emenda` nunca entra na fila da
   CGU (`semear_fila` só pega código não nulo) nem casa no JOIN: a busca
   prometida nunca acontece, e o aviso não apagava nunca.

O que se prova: a linha sem código ganha grupo e motivo próprios e sai da conta
do "X de Y"; a frase não afirma mais o que é falso; e o resto não mudou.

Rodar:
    python -m pytest backend/tests/test_emendas_federais_sem_codigo.py -v
"""
import asyncio
from datetime import datetime

import pytest

import routers.emendas_federais as EF
from services.coleta import FRASE_EMENDAS_FEDERAIS, classificar_emendas_federais
from services.emendas_unificadas import totais, unificar_federais


def _c(**kw) -> str:
    base = {"chave_configurada": True, "houve_coleta": True, "tem_cnpj": True,
            "n_emendas": 10, "n_execucao_consultada": 10}
    base.update(kw)
    return classificar_emendas_federais(**base)


# ---------------------------------------------------------------------------
# A regra (função pura)
# ---------------------------------------------------------------------------
def test_36_de_37_com_uma_sem_codigo_e_ok():
    """O caso de Nova Serrana: tudo o que PODE ser consultado foi."""
    assert _c(n_emendas=37, n_execucao_consultada=36, n_sem_codigo=1) == "ok"


def test_falta_de_consulta_de_verdade_continua_parcial():
    assert _c(n_emendas=37, n_execucao_consultada=35, n_sem_codigo=1) == "parcial"


def test_so_linha_sem_codigo_nao_vira_sem_chave():
    """Nenhuma consulta possível não é "a execução não foi consultada neste
    ambiente" — não havia o que consultar."""
    assert _c(chave_configurada=False, n_emendas=1, n_execucao_consultada=0,
              n_sem_codigo=1) == "ok"
    # Com emenda consultável e nada consultado, `sem_chave` continua valendo.
    assert _c(chave_configurada=False, n_emendas=2, n_execucao_consultada=0,
              n_sem_codigo=1) == "sem_chave"


def test_o_default_mantem_a_regra_antiga():
    assert _c(n_emendas=37, n_execucao_consultada=36) == "parcial"


def test_a_frase_parcial_nao_afirma_mais_que_todo_traco_e_nao_buscado():
    frase = FRASE_EMENDAS_FEDERAIS["parcial"].format(consultadas=35, total=36)
    assert "35 de 36" in frase and "não é R$ 0" in frase
    assert "Onde a execução aparece como «—», o dado ainda não foi buscado" not in frase
    # Aponta o SELO de cada linha, que é o que distingue os dois «—».
    assert "«Execução não consultada»" in frase and "«Sem registro na CGU»" in frase


# ---------------------------------------------------------------------------
# A linha
# ---------------------------------------------------------------------------
def _e(codigo, consultada=False, **kw):
    base = {"codigo_emenda": codigo, "execucao_consultada": consultada, "encontrada": None,
            "valor_empenhado": None, "valor_pago": None, "valor_resto_pago": None,
            "valor_resto_inscrito": None, "valor_resto_cancelado": None,
            "impositiva": False}
    base.update(kw)
    return base


def test_linha_sem_codigo_tem_grupo_proprio_e_nao_promete_busca():
    r = EF.classificar(_e(None))
    assert r["grupo"] == "sem_codigo"
    assert "ainda" not in r["motivo"]
    assert "não é R$ 0" in r["motivo"]


def test_linha_com_codigo_nao_consultada_continua_nao_consultada():
    assert EF.classificar(_e("202641760002"))["grupo"] == "nao_consultada"
    assert EF.classificar(_e("202641760002", True, encontrada=False))["grupo"] == "nao_encontrada"


def test_o_cartao_nao_conta_a_sem_codigo_como_ainda_nao_consultada():
    carteira = [
        {"codigo_emenda": None, "ano": 2025, "autor": "Fulano", "valor_indicado": 1.0,
         "beneficiario_prefeitura": True, "execucao_consultada": False,
         "grupo": "sem_codigo", "propostas": []},
        {"codigo_emenda": "202641760002", "ano": 2025, "autor": "Fulano",
         "valor_indicado": 1.0, "beneficiario_prefeitura": True,
         "execucao_consultada": False, "grupo": "nao_consultada", "propostas": []},
    ]
    t = totais(unificar_federais(carteira, [], [], [], []))
    assert t["nao_consultadas_n"] == 1


# ---------------------------------------------------------------------------
# O router inteiro, com um banco falso: o "X de Y" e o selo
# ---------------------------------------------------------------------------
def _linha(codigo, consultada=True):
    x = [None] * 27
    x[0], x[1], x[2] = codigo, None, 2025
    x[3], x[4], x[5] = "Nikolas Ferreira", "INDIVIDUAL", True
    x[7], x[8], x[9], x[10] = "18301036000164", "MUNICIPIO DE NOVA SERRANA", True, True
    x[11], x[12] = 100000.0, []
    if consultada:
        x[13] = x[15] = 100000.0
        x[22], x[23] = datetime(2026, 9, 24, 3, 45), True
    x[24], x[26] = 0, 0
    return tuple(x)


class _R:
    def __init__(self, primeira=None, linhas=(), escalar=None):
        self._p, self._l, self._s = primeira, list(linhas), escalar

    def first(self):
        return self._p

    def fetchall(self):
        return self._l

    def scalar(self):
        return self._s


class _Db:
    def __init__(self, linhas):
        self.linhas = linhas

    async def execute(self, sql, params=None):
        s = str(sql)
        if "FROM municipios" in s:
            return _R(primeira=("Nova Serrana", "18301036000164"))
        if "emendas_federais_carteira" in s:
            return _R(linhas=self.linhas)
        if "ingestion_log" in s:
            return _R(escalar=1)
        raise AssertionError(f"consulta inesperada: {s[:80]}")

    async def rollback(self):
        pass


@pytest.fixture
def sem_frescor(monkeypatch):
    async def _f(*a, **kw):
        return None, 0
    monkeypatch.setattr(EF, "frescor_coleta", _f)


def test_nova_serrana_36_de_37_sem_aviso_e_com_o_selo_dizendo_por_que(sem_frescor):
    linhas = [_linha(f"2025417600{i:02d}") for i in range(36)] + [_linha(None, False)]
    d = asyncio.run(EF.buscar(_Db(linhas), 2))
    assert d["estado"] == "ok" and d["aviso"] == ""
    assert d["execucao"] == {"consultadas": 36, "total": 37, "sem_codigo": 1}
    assert d["totais"]["nao_consultadas_n"] == 0 and d["totais"]["sem_codigo_n"] == 1
    assert [e["grupo"] for e in d["items"] if not e["codigo_emenda"]] == ["sem_codigo"]


def test_falta_de_verdade_segue_avisando_com_o_denominador_consultavel(sem_frescor):
    linhas = ([_linha(f"2025417600{i:02d}") for i in range(35)]
              + [_linha("202541760099", False), _linha(None, False)])
    d = asyncio.run(EF.buscar(_Db(linhas), 2))
    assert d["estado"] == "parcial"
    assert "35 de 36 emendas" in d["aviso"]
    assert d["totais"]["nao_consultadas_n"] == 1
