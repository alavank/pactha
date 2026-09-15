"""Voluntárias: a ÁRVORE da proposta pelos dumps de Discricionárias (15/09/2026).

A fixture é REAL: `tests/fixtures/tg_arvore_dumps.json` tem as linhas dos zips de
15/09/2026 para quatro propostas de Nova Palma/RS, mais duas linhas de OUTRA
cidade por arquivo (ruído que o coletor tem de ignorar) e os cabeçalhos
completos dos 52 arquivos lidos.

  1531858  convênio 901671: 2 aditivos, prorrogação de 208 dias, tributos,
           3 fornecedores, prestação de contas aprovada
  1665797  obra com medição, execução física 100% e o elo com o Obras.gov
  1056241  pago > desembolsado: a diferença é a contrapartida
  824122   proposta sem convênio
"""
import json
from pathlib import Path

import pytest

from ingestion import transferegov_arvore as ta

BACKEND = Path(__file__).resolve().parents[1]
FIX = json.loads((BACKEND / "tests" / "fixtures" / "tg_arvore_dumps.json").read_text(encoding="utf-8"))
NOVA_PALMA = "4313102"
MID = 4


def _ler(falhar=(), vazio=()):
    def ler(nome):
        if nome in falhar:
            raise ta.FalhaArquivo(f"{nome}: cabecalho sem ['X'] — a fonte renomeou coluna?")
        if nome in vazio:
            return
        for linha in FIX.get(nome, []):
            yield dict(linha)
    return ler


def _propostas():
    return {p["ID_PROPOSTA"]: (MID, p["IDENTIF_PROPONENTE"]) for p in FIX["_propostas"]}


def _coleta(**kw):
    return ta.coleta(_propostas(), {NOVA_PALMA: MID}, ler=_ler(**kw))


# ---------------------------------------------------------------------------
# A guarda do cabeçalho
# ---------------------------------------------------------------------------
def test_toda_coluna_lida_pelo_nome_existe_no_cabecalho_real():
    """O risco do dump não é filtro ignorado; é RENOMEAR coluna. Cada coluna que
    o coletor lê pelo nome tem de estar no cabeçalho de 15/09/2026."""
    cab = FIX["_cabecalhos"]
    assert set(ta.ARQUIVOS) == set(cab)
    faltando = {n: [c for c in cols if c not in cab[n]] for n, cols in ta.ARQUIVOS.items()}
    assert not {n: f for n, f in faltando.items() if f}


def test_toda_chave_da_arvore_diz_de_que_arquivo_depende():
    """Sem isto, arquivo que falha não tiraria a chave da gravação e a árvore
    ficaria com lista vazia afirmando 'não há'."""
    arv = _coleta().arvores["1531858"]
    fora = {"convenio", "_resumo", "_mantidas"}
    assert set(arv) - fora == set(ta.DEPENDE)
    lidos = {a for arqs in ta.DEPENDE.values() for a in arqs}
    assert lidos <= set(ta.ARQUIVOS)


def test_ler_pula_o_arquivo_quando_o_cabecalho_perde_coluna(monkeypatch):
    def abrir(nome):
        return ["NR_CONVENIO", "OUTRA"], iter([{"NR_CONVENIO": "1", "OUTRA": "x"}])
    monkeypatch.setattr(ta, "_abrir", abrir)
    with pytest.raises(ta.FalhaArquivo, match="renomeou"):
        list(ta._ler("siconv_termo_aditivo"))


def test_ler_compacta_campo_vazio(monkeypatch):
    monkeypatch.setattr(ta, "_abrir", lambda nome: (
        ["ID_PROPOSTA", "A", "B"], iter([{"ID_PROPOSTA": "1", "A": "", "B": "x"}])))
    assert list(ta._ler("siconv_consorcios")) == [{"ID_PROPOSTA": "1", "B": "x"}]


# ---------------------------------------------------------------------------
# A árvore com as linhas reais
# ---------------------------------------------------------------------------
def test_a_arvore_do_convenio_com_aditivo_e_prorrogacao():
    c = _coleta()
    assert not any(c.falhas.values())
    arv = c.arvores["1531858"]
    assert arv["convenio"]["NR_CONVENIO"] == "901671"
    r = arv["_resumo"]
    assert (r["vigencia_original"], r["vigencia_atual"]) == ("30/08/2022", "26/03/2024")
    assert (r["n_aditivos"], r["n_prorrogacoes"], r["dias_prorrogados"]) == (2, 1, 208)
    assert r["tributos"] == 3000.0
    assert (r["pago_fornecedores"], r["n_pagamentos"], r["n_fornecedores"]) == (377700.0, 4, 3)
    assert (r["n_licitacoes"], r["n_liquidacoes"]) == (3, 4)
    assert r["cumprimento_objeto"] == "INTEGRALMENTE"
    assert r["prestacao_contas_aprovada"] == "19/07/2024 15:21:27"
    assert r["contrapartida_devida"] == r["contrapartida_depositada"] == 187532.74
    assert r["situacao_atual"] == "PRESTACAO_CONTAS_CONCLUIDA"
    # Os netos vêm pendurados no pai.
    assert arv["emendas"][0]["NR_EMENDA"] == "32980006"
    assert len(arv["emendas"][0]["apoiadores"]) == 1
    assert len(arv["desembolsos"][0]["empenhos"]) == 1
    assert len(arv["metas"][0]["etapas"]) >= 1


def test_a_obra_e_o_elo_com_o_obrasgov():
    r = _coleta().arvores["1665797"]
    assert r["cipi"]["id_projeto_investimento"] == "7378.43-65"
    assert r["_resumo"]["id_projeto_investimento"] == "7378.43-65"
    assert r["_resumo"]["execucao_fisica_pct"] == 100.0
    assert r["_resumo"]["n_medicoes"] == 1
    assert len(r["obras"]["medicoes"][0]["valores"]) == 1
    assert r["_resumo"]["dias_prorrogados"] == 822


def test_pago_maior_que_desembolsado_e_a_contrapartida():
    """Não é erro: o convenente paga com o repasse E com a contrapartida."""
    r = _coleta().arvores["1056241"]["_resumo"]
    assert r["desembolsado"] == 97500.0
    assert r["pago_fornecedores"] == 112590.0
    assert r["pago_fornecedores"] == r["desembolsado"] + r["contrapartida_depositada"]


def test_proposta_sem_convenio_nao_afirma_empenho_nem_desembolso():
    c = _coleta()
    arv = c.arvores["824122"]
    assert arv["convenio"] is None
    assert arv["justificativas"]
    assert "824122" not in c.notas_empenho      # a coluna fica como estava
    assert "824122" not in c.ops_obs
    assert arv["_resumo"]["desembolsado"] is None


def test_o_ruido_de_outra_cidade_fica_de_fora():
    c = _coleta()
    ids = set(_propostas())
    for tabela in (c.licitacoes, c.pagamentos, c.liquidacoes):
        assert tabela and {li["id_proposta"] for li in tabela} <= ids
        assert {li["mid"] for li in tabela} == {MID}
    assert len(c.licitacoes) == 5 and len(c.pagamentos) == 17 and len(c.liquidacoes) == 17


def test_canceladas_por_ibge_com_a_regra_da_prefeitura():
    c = _coleta()
    assert [x["numero"] for x in c.canceladas] == ["031085/2013", "029805/2012"]
    assert all(x["municipal"] is True and x["mid"] == MID for x in c.canceladas)


def test_data_da_carga():
    assert _coleta().data_carga == "15/09/2026 06:34:05"


def test_data_da_carga_nao_passa_pela_guarda_de_zip_truncado(monkeypatch):
    """O arquivo tem ~150 bytes, e o `_baixa` recusa tudo abaixo de 1.000 como
    download truncado — o e2e de 15/09/2026 perdeu a data por isso."""
    import io
    import zipfile

    import httpx
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("data_carga_siconv.csv", "﻿data_carga\r\n15/09/2026 06:34:05\r\n")

    class _R:
        content = buf.getvalue()

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R())
    monkeypatch.setattr(ta.od, "_baixa", lambda nome: pytest.fail("usou o _baixa"))
    assert list(ta._ler("data_carga_siconv")) == [{"data_carga": "15/09/2026 06:34:05"}]
    d = ta._dt("15/09/2026 06:34:05")
    assert (d.year, d.month, d.day, d.hour) == (2026, 9, 15, 6)


# ---------------------------------------------------------------------------
# O formato que o RM já lê
# ---------------------------------------------------------------------------
def test_ops_obs_aberto_tem_o_formato_do_raspado():
    from services.rm_builder import _ano_pagamento_ops_obs, _desembolso_ops_obs
    ops = _coleta().ops_obs["1531858"]
    d = _desembolso_ops_obs(ops)
    assert d["valor_desembolsado"] == 213220.28
    assert d["valor_a_desembolsar"] == 25529.72
    assert d["dt_ultimo_desembolso"] == "27/12/2022"
    assert d["desembolsos"][0]["numero_ob"] == "2022OB800444"
    assert _ano_pagamento_ops_obs(ops) == 2022


def test_faixa_sem_desembolso_nao_e_contagem_de_dias():
    """Dicionário oficial: 'Indicador de dias sem desembolso. Domínio: 90, 180 e
    365'. Gravar como 'dias' mentiria; calcular aqui faria a árvore mudar todo
    dia sem a fonte mudar."""
    ops = _coleta().ops_obs["1531858"]
    assert ops["faixa_sem_desembolso"] == 365
    assert "qtd_dias_sem_desembolso" not in ops
    assert "dias_sem_desembolso" not in _coleta().arvores["1531858"]["_resumo"]


def test_notas_de_empenho_no_formato_do_rm():
    ne = _coleta().notas_empenho["1531858"]
    # A fonte publica duas NEs desse convênio com VALOR_EMPENHO 0: ficam fora,
    # como no `siconv_empenho_aberto` (o RM não conta minuta).
    assert ne == [{"numero": "2020NE803201", "valor": 25529.72, "situacao": "Enviado",
                   "dt_emissao": "23/06/2020", "minuta_apenas": False}]


# ---------------------------------------------------------------------------
# Falha parcial: o que falhou fica como estava, e é dito
# ---------------------------------------------------------------------------
def test_arquivo_que_falha_mantem_so_a_sua_chave():
    c = _coleta(falhar={"siconv_termo_aditivo"})
    assert c.chaves_mantidas == {"aditivos"}
    arv = c.arvores["1531858"]
    assert "aditivos" not in arv and arv["_mantidas"] == ["aditivos"]
    assert arv["_resumo"]["n_aditivos"] is None          # não medido, e não zero
    assert arv["_resumo"]["n_prorrogacoes"] == 1         # o resto segue
    status, n, erro = ta.status_da_coleta(c, {"arvore": {"total": 4}})
    assert status == "partial" and n == 4
    assert "siconv_termo_aditivo" in erro and "aditivos" in erro


def test_sem_o_convenio_nada_por_nr_convenio_e_trocado():
    """⚠️ Sem `siconv_convenio` o conjunto de NR_CONVENIO fica vazio: ler
    licitação e pagamento 'daria certo' com zero linhas e a troca APAGARIA as
    tabelas."""
    c = _coleta(falhar={"siconv_convenio"})
    assert c.falhas["licitacoes"] and c.falhas["pagamentos"]
    assert not c.licitacoes and not c.pagamentos
    assert not c.notas_empenho and not c.ops_obs
    assert not c.falhas["liquidacoes"] and c.liquidacoes    # entra por ID_PROPOSTA


def test_arquivo_vazio_e_falha_e_nao_zero():
    c = _coleta(vazio={"siconv_pagamento"})
    assert c.falhas["pagamentos"] and "sem nenhuma linha" in c.falhas["pagamentos"][0]
    assert c.arvores["1531858"]["_resumo"]["n_pagamentos"] is None


def test_status_sem_falha_e_success_e_sem_nada_e_error():
    c = _coleta()
    assert ta.status_da_coleta(c, {"arvore": {"total": 4}}) == ("success", 4, None)
    ruim = _coleta(falhar=set(ta.ARQUIVOS))
    status, n, erro = ta.status_da_coleta(ruim, {})
    assert status == "error" and n == 0 and erro.startswith("nada trocado")


# ---------------------------------------------------------------------------
# A gravação: só o que mudou, e seção que falhou nunca apaga
# ---------------------------------------------------------------------------
class _Cur:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.conn.sql.append(sql)
        self._um = [self.conn.contagem]

    def fetchone(self):
        return self._um

    def close(self):
        pass


class _Conn:
    def __init__(self, contagem=0):
        self.sql = []
        self.contagem = contagem
        self.commits = 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_grava_pula_arvore_e_tabelas_quando_o_convenio_falha(monkeypatch):
    chamadas = []
    monkeypatch.setattr(ta, "_troca_tabela",
                        lambda conn, secao, linhas, mids, **kw: chamadas.append(secao) or {})
    c = _coleta(falhar={"siconv_convenio"})
    g = ta.grava(_Conn(), c, _propostas())
    assert "arvore" not in g
    assert chamadas == ["liquidacoes", "canceladas"]


def test_troca_recusa_apagar_quando_nada_casou_e_a_tabela_tem_linhas():
    with pytest.raises(ta.FalhaArquivo, match="nada apagado"):
        ta._troca_tabela(_Conn(contagem=12), "pagamentos", [], [MID])
    with pytest.raises(ta.FalhaArquivo, match="nada apagado"):
        ta._troca_tabela(_Conn(contagem=12), "pagamentos", [], [MID], casadas=0)


# ---------------------------------------------------------------------------
# Opção B (decisão do dono, 15/09/2026): o que não é da prefeitura guarda só o
# RESUMO — as contas, e não as linhas.
# ---------------------------------------------------------------------------
def test_o_que_nao_e_da_prefeitura_guarda_so_o_resumo():
    cheia = _coleta()
    so = ta.coleta(_propostas(), {NOVA_PALMA: MID}, ler=_ler(), so_resumo={"1531858"})
    # As linhas dela saem das três tabelas...
    for tabela in ("licitacoes", "pagamentos", "liquidacoes"):
        assert not [x for x in getattr(so, tabela) if x["id_proposta"] == "1531858"]
        assert [x for x in getattr(cheia, tabela) if x["id_proposta"] == "1531858"]
    # ...e as das outras ficam iguais.
    assert len(so.pagamentos) == len(cheia.pagamentos) - 4
    # O RESUMO é o mesmo, número a número — sai dos agregados, não das linhas.
    r_so, r_cheia = so.arvores["1531858"]["_resumo"], cheia.arvores["1531858"]["_resumo"]
    assert r_so.pop("so_resumo") is True and r_cheia.pop("so_resumo") is False
    assert r_so == r_cheia
    # A árvore pequena continua: vigência, aditivos, empenhos, desembolsos.
    assert so.arvores["1531858"]["aditivos"] and so.ops_obs["1531858"]


def test_so_resumo_nao_apaga_como_se_nada_tivesse_casado(monkeypatch):
    """Tudo o que casou pode ser de quem não é prefeitura: aí não há linha a
    guardar, e a guarda de "nada casou" NÃO pode travar a limpeza das linhas
    velhas (as de antes da opção B)."""
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_values", lambda *a, **k: [])
    trocas = {}
    monkeypatch.setattr(ta, "_troca_tabela",
                        lambda conn, secao, linhas, mids, casadas=None: trocas.setdefault(
                            secao, (len(linhas), casadas)) and {} or {})
    todas = set(_propostas())
    c = ta.coleta(_propostas(), {NOVA_PALMA: MID}, ler=_ler(), so_resumo=todas)
    g = ta.grava(_Conn(), c, _propostas())
    assert trocas["pagamentos"] == (0, 17) and trocas["licitacoes"] == (0, 5)
    assert g["pagamentos"]["so_resumo"] == 17


def test_o_sql_so_reescreve_o_que_mudou():
    import pglast
    sql = ta._SQL_ARVORE.replace("%s", "(1, '1', '{}'::jsonb, NULL::jsonb, NULL::jsonb)")
    pglast.parse_sql(sql)
    assert "IS DISTINCT FROM" in ta._SQL_ARVORE
    assert "COALESCE(p.arvore, '{}'::jsonb) || v.arv" in ta._SQL_ARVORE


def test_a_migration_e_valida_e_esta_na_lista():
    import pglast
    from services.startup import MIGRATION_FILES
    sql = (BACKEND / "migrations" / "add_tg_arvore.sql").read_text(encoding="utf-8")
    pglast.parse_sql(sql)
    for tabela, chave, _ in ta._TABELAS.values():
        assert f"CREATE TABLE IF NOT EXISTS {tabela}" in sql
        assert f"ON {tabela} (municipio_id, {chave})" in sql     # o ON CONFLICT precisa
    assert MIGRATION_FILES.index("add_tg_natureza.sql") < MIGRATION_FILES.index("add_tg_arvore.sql")
    assert MIGRATION_FILES.index("add_tg_arvore.sql") < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
