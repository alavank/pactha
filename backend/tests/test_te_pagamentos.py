"""PAGAMENTOS da Transferência Especial (Emenda Pix).

Os payloads abaixo são as RESPOSTAS REAIS da API pública, capturadas do plano
91573 em 24/08/2026 — não são invenção. O que se prova aqui é a única coisa que
o olho não pega lendo: que a MINUTA não vira dinheiro, que o formato gravado é o
MESMO do `ops_obs` das voluntárias, e que "não medido" não vira "não há pagamento".
"""
import asyncio

from ingestion.transferegov_te import (
    _chave_data, _dh_br, _dt_br, _num, _teto_listagem_s, pagamentos_do_plano,
)
from services.rm_builder import (
    _ano_pagamento_ops_obs, _desembolso_ops_obs, _fed_retem, _fed_status,
)

# Resposta real de /public/documentos-habeis/plano-acao/resumido/91573
DH_91573 = [
    {"descricaoSituacao": "Enviado", "id": 76255, "nuDh": "2026TF005459",
     "nuInternoDh": "2026MDH00005691", "numeroEmpenho": "2026NE005806",
     "opObId": 53038, "txOp": "2026OP004179", "vlDh": 205066.16},
    {"descricaoSituacao": "Minuta de DH", "id": 79670, "nuDh": None,
     "nuInternoDh": "2026MDH00009147", "numeroEmpenho": "2026NE005806",
     "opObId": 0, "txOp": None, "vlDh": 192933.84},
]
# Resposta real de /public/opob/53038 (recortada no que o coletor lê)
OPOB_53038 = {
    "txOp": "2026OP004179", "txOb": "2026OB004192",
    "situacao": "OB Enviada à instituição bancária para pagamento",
    "dtEmissaoOp": "2026-06-19", "dtEmissaoOb": "2026-06-22", "dtPagamento": None,
    "dtAssinaturaOrdDesp": "2026-06-19", "dtAssinaturaGestFin": "2026-06-19",
    "txCpfOrdenadorDespesa": "***.272.701-**", "txCpfGestorFinanceiro": "***.272.701-**",
    "historico": [
        {"cdEvento": 5, "dhRegistro": "2026-06-22T08:56:37.75667", "txCpfResponsavel": "sistema",
         "situacao": "OB Enviada à instituição bancária para pagamento"},
        {"cdEvento": 3, "dhRegistro": "2026-06-19T21:56:30.1", "txCpfResponsavel": "***272701**",
         "situacao": "Aguardando assinaturas do ordenador de despesas e/ou gestor financeiro"},
        {"cdEvento": 1, "dhRegistro": "2026-06-19T21:17:38.5", "txCpfResponsavel": "***272701**",
         "situacao": "Aguardando Envio para o SIAFI"},
    ],
}


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class _Cli:
    """Dublê do httpx.AsyncClient: devolve por PREFIXO de URL e conta chamadas."""

    def __init__(self, dh=None, opob=None, status_opob=200):
        self.dh = DH_91573 if dh is None else dh
        self.opob = OPOB_53038 if opob is None else opob
        self.status_opob = status_opob
        self.urls = []

    async def get(self, url, headers=None):
        self.urls.append(url)
        if "/documentos-habeis/" in url:
            return _Resp(self.dh)
        return _Resp(self.opob, self.status_opob)


def _colhe(cli, total=398000.0, pid=91573):
    return asyncio.run(pagamentos_do_plano(cli, pid, total))


# ---------------------------------------------------------------------------
# ⚠️ MINUTA NÃO É DINHEIRO
# ---------------------------------------------------------------------------
def test_a_minuta_NAO_conta_como_desembolsado():
    """No 91573 são R$ 205.066,16 emitidos e R$ 192.933,84 ainda em MINUTA.
    Somar a minuta mostraria o plano 100% pago e o mandaria para a Parte 3 sem
    que um centavo tivesse saído."""
    pg = _colhe(_Cli())
    assert pg["valor_desembolsado"] == 205066.16
    assert pg["valor_a_desembolsar"] == 192933.84
    assert pg["pago_integral"] is False
    assert len(pg["obs"]) == 1 and len(pg["pendentes"]) == 1
    assert pg["pendentes"][0]["situacao_dh"] == "Minuta de DH"


def test_a_minuta_nao_gera_requisicao_de_OP():
    # `opObId` 0 = não há ordem de pagamento a consultar. Gastar um GET nela
    # seria pagar rede por um id que a própria API rejeita com 403.
    cli = _Cli()
    _colhe(cli)
    assert sum(1 for u in cli.urls if "/opob/" in u) == 1


def test_documento_habil_SEM_ordem_bancaria_nao_e_pagamento():
    """DH com OP emitida mas ainda SEM OB: o dinheiro não saiu. Vai para
    `pendentes`, não para `obs`."""
    pg = _colhe(_Cli(opob={**OPOB_53038, "txOb": "", "dtEmissaoOb": None}))
    assert pg["valor_desembolsado"] == 0.0
    assert pg["obs"] == []
    assert len(pg["pendentes"]) == 2


# ---------------------------------------------------------------------------
# O formato é o MESMO do `ops_obs` das voluntárias
# ---------------------------------------------------------------------------
def test_o_RM_le_a_TE_com_as_MESMAS_funcoes_das_voluntarias():
    """É o desenho inteiro: mesmo formato = nenhum parser novo no builder, e
    `rm_pdf._desembolso_destaque` imprime a caixa da TE sem uma linha nova."""
    pg = _colhe(_Cli())
    d = _desembolso_ops_obs(pg)
    assert d["valor_desembolsado"] == 205066.16
    assert d["valor_a_desembolsar"] == 192933.84
    assert d["dt_ultimo_desembolso"] == "22/06/2026"
    assert len(d["desembolsos"]) == 1
    assert _ano_pagamento_ops_obs(pg) == 2026


def test_as_datas_saem_em_dd_mm_aaaa_como_o_ops_obs():
    assert _dt_br("2026-06-22") == "22/06/2026"
    assert _dt_br("2026-06-22T08:56:37.75667") == "22/06/2026"
    assert _dt_br(None) == "" and _dt_br("") == ""
    assert _dh_br("2026-06-22T08:56:37.75667") == "22/06/2026 08:56"


def test_a_ultima_OB_e_a_de_DATA_maior_e_nao_a_ultima_da_lista():
    # A API não garante ordem. `_chave_data` compara aaaammdd como texto.
    assert _chave_data("22/06/2026") > _chave_data("19/06/2026")
    assert _chave_data("01/01/2027") > _chave_data("31/12/2026")
    assert _chave_data("") == "" and _chave_data(None) == ""


# ---------------------------------------------------------------------------
# ⚠️ "NÃO MEDIDO" ≠ "NÃO HÁ PAGAMENTO"
# ---------------------------------------------------------------------------
def test_fonte_muda_devolve_None_para_a_coluna_ficar_NULA():
    """None = não medido. É o que impede o RM de escrever PENDENTE DE
    DESEMBOLSO sobre um plano que ninguém consultou — a disciplina de
    `_nes_resumo`."""
    class _Ruim(_Cli):
        async def get(self, url, headers=None):
            return _Resp(None, 500)
    assert _colhe(_Ruim()) is None


def test_plano_sem_documento_habil_e_MEDIDO_e_nao_None():
    """Diferente do caso acima: aqui a fonte respondeu, e a resposta é "não há".
    Tem de carimbar, senão os ~30% de planos sem DH voltam à fila todo dia."""
    pg = _colhe(_Cli(dh=[]))
    assert pg is not None
    assert pg["valor_desembolsado"] == 0.0
    assert pg["obs"] == [] and pg["pendentes"] == []


def test_o_403_do_opob_nao_derruba_a_coleta_do_plano():
    """⚠️ `/opob/{id}` devolve 403 (não 404) para id inexistente. Tratar como
    rate-limit poria o coletor em backoff por causa de um id que não existe."""
    pg = _colhe(_Cli(status_opob=403))
    assert pg is not None                    # o plano continua sendo gravado
    assert pg["valor_desembolsado"] == 0.0   # sem OB confirmada, nada é pago
    assert len(pg["pendentes"]) == 2


# ---------------------------------------------------------------------------
# O histórico de eventos de pagamento
# ---------------------------------------------------------------------------
def test_o_historico_de_eventos_chega_inteiro():
    pg = _colhe(_Cli())
    h = pg["obs"][0]["historico"]
    assert len(h) == 3
    assert h[0]["data"] == "22/06/2026 08:56"
    assert h[0]["responsavel"] == "sistema"
    assert "instituição bancária" in h[0]["situacao"]


def test_o_ordenador_e_o_gestor_financeiro_vem_junto():
    o = _colhe(_Cli())["obs"][0]
    assert o["ordenador_despesa"] == "***.272.701-**"
    assert o["dt_assinatura_ordenador"] == "19/06/2026"
    assert o["numero_empenho"] == "2026NE005806"
    assert o["numero_op"] == "2026OP004179"


# ---------------------------------------------------------------------------
# ⭐ O BURACO SILENCIOSO que o pagamento fecha
# ---------------------------------------------------------------------------
def test_plano_PAGO_deixa_de_sumir_do_RM_de_ano_posterior():
    """O 91573 tem OB emitida em 22/06/2026 e `planoAcaoSituacao` ainda CIENTE —
    que é o caso NORMAL, não a exceção. `_fed_status("CIENTE")` devolve 'ativa',
    e `_fed_retem` só mantém 'ativa' quando o ano do plano >= o ano do RM.
    Resultado: num RM de 2027 um plano JÁ PAGO era descartado, calado."""
    assert _fed_retem(2026, 2027, "CIENTE", True) is False          # o defeito
    assert _fed_retem(2026, 2027, "Pagamento integral realizado", True) is True


def test_a_frase_de_classificacao_usa_o_vocabulario_que_o_fed_status_entende():
    # Se a frase mudar e deixar de conter "pag", o plano pago volta a ser 'ativa'
    # e o teste acima cai junto — é a trava dos dois.
    assert _fed_status("Pagamento integral realizado") == "paga"


def test_pago_integral_tolera_um_centavo():
    """O rateio entre documentos hábeis fecha em centavos; exigir zero exato
    deixaria plano pago de fora da Parte 3 por R$ 0,01."""
    pg = _colhe(_Cli(dh=[{**DH_91573[0], "vlDh": 397999.99}]), total=398000.0)
    assert pg["valor_a_desembolsar"] == 0.01
    assert pg["pago_integral"] is True


def test_num_nao_quebra_com_lixo():
    assert _num("12,5") is None and _num(None) is None and _num("12.5") == 12.5


# ---------------------------------------------------------------------------
# ⚠️ O ORÇAMENTO — achado na PRIMEIRA rodada real (Freitas, 24/08/2026)
# ---------------------------------------------------------------------------
# ⚠️ IMPORTADA do coletor, e não recopiada. Enquanto esta conta vivia duplicada
# aqui, o teste passaria mesmo que `run()` mudasse a fórmula — que é exatamente
# o caso que ele existe para pegar.
_teto_listagem = _teto_listagem_s


def test_a_listagem_nao_pode_engolir_o_orcamento_dos_pagamentos():
    """Com os defaults de 24/08/2026 (listagem 1500s, teto de tarefa 1450s), o
    cálculo "pagamentos ficam com o que sobrar" dava −50s: eles NUNCA rodariam,
    e o log diria "sem tempo nesta rodada" para sempre, com a coluna
    `pagamentos` eternamente NULA e ninguém vendo erro nenhum.

    A listagem é quem pode esperar — ela retoma da página gravada e a fonte a
    limita de qualquer jeito. Os pagamentos são 1+N GETs baratos e são o dado
    que sustenta o PENDENTE DE DESEMBOLSO do RM."""
    BUDGET, TETO, PGTO = 1500.0, 1450.0, 300.0
    assert TETO - BUDGET < 0                       # o defeito, explicitado
    reservado = TETO - _teto_listagem(BUDGET, TETO, PGTO)
    assert reservado == PGTO                       # a correção
    assert _teto_listagem(BUDGET, TETO, PGTO) + PGTO <= TETO


def test_o_total_cabe_no_kill_da_scheduled_task():
    """A task roda `timeout -k 30 1600`. Estourar isso degola a rodada no meio e
    o log final — que é onde o resultado aparece — se perde."""
    BUDGET, TETO, PGTO, KILL = 1500.0, 1450.0, 300.0, 1600.0
    assert _teto_listagem(BUDGET, TETO, PGTO) + PGTO < KILL


def test_orcamento_apertado_ainda_deixa_a_listagem_andar():
    """Piso de 60s: um `TE_PGTO_BUDGET_S` grande demais não pode zerar a
    listagem — sem ela não há plano novo para consultar pagamento nenhum."""
    assert _teto_listagem(1500.0, 400.0, 900.0) == 60.0
