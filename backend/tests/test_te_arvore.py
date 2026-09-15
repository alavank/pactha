"""A ÁRVORE DO PLANO da Transferência Especial pela API oficial (14/09/2026).

As respostas em `fixtures/te_especiais_arvore.json` são REAIS: capturadas de
`api-publica.transferegov.gestao.gov.br/especiais` em 14/09/2026, passando pelo
próprio `arvore_do_plano`. Dois planos:

  67457 — Nova Palma/RS: árvore completa (2 empenhos pagos, extrato de 11
          lançamentos, relatório de gestão final com 8 documentos de liquidação).
  91573 — o plano da MINUTA: R$ 205.066,16 pagos e R$ 192.933,84 ainda em
          minuta de DH. É o mesmo plano que `test_te_pagamentos.py` usa com o
          payload da SPA de 24/08 — e é isso que permite provar a paridade.
"""
import asyncio
import copy
import inspect
import json
import os

from ingestion import transferegov_te as te
from ingestion.transferegov_te import (
    _doc_normalizado, _pub_filhos, arvore_do_plano, divergencia_de_paridade,
    pagamentos_da_arvore, pagamentos_do_plano, status_da_rodada,
)
from services.rm_builder import _ano_pagamento_ops_obs, _desembolso_ops_obs

from tests.test_te_pagamentos import _Cli as _CliSpa

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "te_especiais_arvore.json")
with open(_FIXTURE, encoding="utf-8") as _f:
    _CAPTURA = json.load(_f)
PLANO_67457 = _CAPTURA["planos"]["67457"]
PLANO_91573 = _CAPTURA["planos"]["91573"]


def _chave(url: str, params: dict | None) -> str:
    caminho = url.rsplit("/especiais/", 1)[-1]
    p = {k: v for k, v in (params or {}).items() if k not in ("pagina", "tamanho_da_pagina")}
    return caminho + "?" + "&".join(f"{k}={p[k]}" for k in sorted(p))


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


class _Replay:
    """Dublê do httpx.AsyncClient: responde com a CAPTURA REAL, por caminho +
    parâmetros. Consulta que não foi capturada volta 404 — o teste que esquecer
    uma consulta falha em vez de passar vazio."""

    def __init__(self, respostas=None, falhar=(), trocar=None):
        self.respostas = copy.deepcopy(respostas or _CAPTURA["respostas"])
        self.falhar = set(falhar)          # chaves que respondem 500
        self.trocar = trocar or {}         # chave -> envelope substituto
        self.chamadas: list[str] = []

    async def get(self, url, params=None, timeout=None, headers=None):
        k = _chave(str(url), params)
        self.chamadas.append(k)
        if k in self.falhar:
            return _Resp(None, 500)
        if k in self.trocar:
            return _Resp(self.trocar[k])
        if k in self.respostas:
            return _Resp(self.respostas[k])
        return _Resp(None, 404)


def _progs(cli):
    return asyncio.run(te._programas(cli))


def _arvore(plano, cli=None):
    cli = cli or _Replay()
    return asyncio.run(arvore_do_plano(cli, copy.deepcopy(plano), _progs(cli)))


def _sem_retentativa(monkeypatch):
    # A retentativa espera 2s de verdade; nos testes de falha isso é só atraso.
    monkeypatch.setattr(te, "_PUB_RETRY_S", 0)


# ---------------------------------------------------------------------------
# A árvore inteira, com o dado que o PACTHA nunca teve
# ---------------------------------------------------------------------------
def test_a_arvore_do_67457_vem_inteira():
    a = _arvore(PLANO_67457)
    assert a is not None
    assert a["programa"]["id_programa"] == PLANO_67457["id_programa"]
    assert len(a["planos_trabalho"]) == 1
    pt = a["planos_trabalho"][0]
    assert pt["data_fim_execucao_plano_trabalho"] == "2027-01-01"      # a vigência
    assert len(pt["analises"]) == 3 and all("historico" in x for x in pt["analises"])
    assert len(pt["historico"]) == 7
    assert len(a["executores"]) == 1
    assert len(a["executores"][0]["metas"]) == 3
    assert len(a["executores"][0]["finalidades"]) == 2
    assert len(a["empenhos"]) == 2
    assert all(len(e["documentos_habeis"]) == 1 for e in a["empenhos"])
    assert a["devolucoes"] == [] and len(a["historico"]) == 2


def test_quem_recebeu_o_dinheiro_do_municipio():
    """O documento de liquidação do relatório de gestão: nome, CNPJ, valor e
    data de cada pagamento que o município fez com a emenda. A pergunta que o
    TCU e a imprensa fazem sobre emenda Pix, e que o PACTHA não respondia."""
    a = _arvore(PLANO_67457)
    rel = a["relatorios_gestao_novos"]
    assert len(rel) == 1 and rel[0]["tipo_relatorio_gestao_novo"] == "Final"
    dls = rel[0]["documentos_liquidacao"]
    assert len(dls) == 8
    assert {d["tx_nome_recebedor_relatorio_gestao_dl"] for d in dls} >= {
        "COMERCIAL DE COMBUSTIVEIS CASSOL LTDA"}
    # ⚠️ o nome do campo é o da RESPOSTA, que diverge do filtro do openapi
    assert "tx_identificacao_recebedor_mascarado_relatorio_gestao_dl" in dls[0]


def test_a_conta_saldo_e_extrato():
    a = _arvore(PLANO_67457)
    c = a["conta"]
    assert c["id_agencia_conta"] == "2127-575858087"
    assert c["saldo"]["saldo_final_gestao_financeira"] == 57226.11
    assert c["saldo"]["data_saldo_conta"] == "2025-04-30"
    assert len(c["lancamentos"]) == 11


def test_o_cnpj_do_extrato_volta_com_os_zeros_que_a_fonte_come():
    """A fonte manda `'394460055477.0'` para o CNPJ 00.394.460/0554-77 do
    Ministério da Fazenda: float em texto, sem os zeros à esquerda."""
    a = _arvore(PLANO_67457)
    creditos = [l for l in a["conta"]["lancamentos"]
                if l["descricao_gestao_financeira"] == "CRED TED"]
    assert creditos and all(l["doc_depositante_gestao_financeira"] == "00394460055477"
                            for l in creditos)
    fav = {l["doc_favorecido_gestao_financeira"] for l in a["conta"]["lancamentos"]}
    assert "88488358000156" in fav and "88488358000156.0" not in fav


def test_normalizacao_do_documento():
    assert _doc_normalizado("394460055477.0", 2) == "00394460055477"
    assert _doc_normalizado("12345678901.0", 1) == "12345678901"
    assert _doc_normalizado("123456789.0", 1) == "00123456789"
    # mascarado pela própria fonte: volta como veio
    assert _doc_normalizado("***47295***", 1) == "***47295***"
    assert _doc_normalizado("***", 0) == "***"
    assert _doc_normalizado(None, None) is None
    assert _doc_normalizado("", 2) is None


# ---------------------------------------------------------------------------
# Consultas que só acontecem quando há o que perguntar
# ---------------------------------------------------------------------------
def test_orgao_pendente_so_e_consultado_com_o_indicador_sim():
    cli = _Replay()
    _arvore(PLANO_67457, cli)          # indicador "Não" na captura
    assert not any(c.startswith("orgaos-analises-pendentes") for c in cli.chamadas)

    pt_sim = copy.deepcopy(_CAPTURA["respostas"]["planos-trabalho-especiais?id_plano_acao=67457"])
    pt_sim["data"][0]["ind_orgao_analises_pendentes"] = "Sim"
    vazio = {"data": [], "total_pages": 0, "total_items": 0, "page_number": 1, "page_size": 200}
    cli = _Replay(trocar={"planos-trabalho-especiais?id_plano_acao=67457": pt_sim,
                          "orgaos-analises-pendentes-especiais?id_plano_trabalho=950": vazio})
    a = _arvore(PLANO_67457, cli)
    assert "orgaos-analises-pendentes-especiais?id_plano_trabalho=950" in cli.chamadas
    assert a["planos_trabalho"][0]["orgaos_pendentes"] == []


def test_subtransacao_so_com_quantidade():
    cli = _Replay()
    _arvore(PLANO_67457, cli)          # quantidade nula nos 11 lançamentos
    assert not any(c.startswith("gestao-financeira-subtransacoes") for c in cli.chamadas)


def test_plano_sem_conta_nao_pergunta_pela_conta():
    cli = _Replay()
    a = _arvore({**PLANO_67457, "id_agencia_conta": None}, cli)
    assert a["conta"] == {"id_agencia_conta": None, "saldo": None, "lancamentos": []}
    assert not any("gestao-financeira" in c for c in cli.chamadas)


def test_parametro_nulo_nao_vai_para_a_rede():
    """`?id_dh=` vazio é filtro que a fonte ignora — ou seja, o Brasil."""
    cli = _Replay()
    assert asyncio.run(_pub_filhos(cli, "ordens-pagamentos-ordens-bancarias-especiais",
                                   {"id_dh": None})) == []
    assert cli.chamadas == []


def test_os_programas_vem_numa_consulta_so():
    cli = _Replay()
    progs = _progs(cli)
    assert len(progs) == 15
    assert cli.chamadas == ["programas-especiais?"]


# ---------------------------------------------------------------------------
# ⚠️ TUDO OU NADA
# ---------------------------------------------------------------------------
def test_uma_consulta_sem_resposta_anula_a_arvore(monkeypatch):
    """Extrato faltando seria lido pela tela como "a conta não teve movimento"."""
    _sem_retentativa(monkeypatch)
    cli = _Replay(falhar={"gestao-financeira-lancamentos-especiais?id_agencia_conta=2127-575858087"})
    assert _arvore(PLANO_67457, cli) is None


def test_pagina_do_meio_faltando_tambem_anula(monkeypatch):
    _sem_retentativa(monkeypatch)
    k = "planos-acao-historico-especiais?id_plano_acao=67457"
    duas_paginas = {**_CAPTURA["respostas"][k], "total_pages": 2}

    class _SegundaPaginaCai(_Replay):
        async def get(self, url, params=None, timeout=None, headers=None):
            if _chave(str(url), params) == k and (params or {}).get("pagina") == 2:
                return _Resp(None, 500)
            return await super().get(url, params=params, timeout=timeout)

    assert _arvore(PLANO_67457, _SegundaPaginaCai(trocar={k: duas_paginas})) is None


def test_filho_com_carga_nacional_anula_a_arvore():
    """Filtro que a fonte deixou de reconhecer: 730.455 lançamentos — a base do
    Brasil inteiro — gravados como o extrato de UM plano."""
    k = "gestao-financeira-lancamentos-especiais?id_agencia_conta=2127-575858087"
    nacional = {"data": [{"x": 1}], "total_pages": 3653, "total_items": 730455,
                "page_number": 1, "page_size": 200}
    cli = _Replay(trocar={k: nacional})
    assert _arvore(PLANO_67457, cli) is None
    assert sum(1 for c in cli.chamadas if c == k) == 1       # não varreu as páginas


def test_toda_consulta_da_arvore_passa_pelo_teto():
    """A árvore só pode perguntar por `lista`/`_pub_filhos`. Um `_pub_todos`
    direto ali seria consulta por id do pai SEM teto — o caminho pelo qual a
    carga nacional entraria."""
    fonte = inspect.getsource(arvore_do_plano)
    assert "_pub_todos(" not in fonte
    assert "_pub_filhos(" in fonte
    assert "teto_itens=_TETO_FILHOS" in inspect.getsource(_pub_filhos)


def test_a_retentativa_salva_um_soluco_da_fonte(monkeypatch):
    _sem_retentativa(monkeypatch)
    k = "devolucao-especiais?id_plano_acao=67457"

    class _SolucaUmaVez(_Replay):
        ja_falhou = False

        async def get(self, url, params=None, timeout=None, headers=None):
            if _chave(str(url), params) == k and not self.ja_falhou:
                self.ja_falhou = True
                self.chamadas.append(k)
                return _Resp(None, 503)
            return await super().get(url, params=params, timeout=timeout)

    cli = _SolucaUmaVez()
    assert _arvore(PLANO_67457, cli) is not None
    assert cli.chamadas.count(k) == 2


# ---------------------------------------------------------------------------
# ⭐ OS PAGAMENTOS SAEM DA ÁRVORE — no formato que o RM já lê
# ---------------------------------------------------------------------------
def _pg(plano, anterior=None):
    total = (plano.get("valor_custeio_plano_acao") or 0) + (plano.get("valor_investimento_plano_acao") or 0)
    return pagamentos_da_arvore(_arvore(plano), total, anterior)


def test_a_minuta_continua_nao_sendo_dinheiro():
    pg = _pg(PLANO_91573)
    assert pg["valor_desembolsado"] == 205066.16
    assert pg["valor_a_desembolsar"] == 192933.84
    assert pg["pago_integral"] is False
    assert len(pg["obs"]) == 1 and len(pg["pendentes"]) == 1
    assert pg["pendentes"][0]["situacao_dh"] == "Minuta de DH"


def test_o_valor_e_o_do_documento_e_nunca_o_rateio():
    """Na minuta do 91573 `valor_rateio_dh` é 205.066,16 — o valor do OUTRO
    documento, o pago. Ler o rateio poria R$ 205 mil na minuta."""
    dhs = _CAPTURA["respostas"]["documentos-habeis-especiais?id_empenho=62311"]["data"]
    minuta = next(d for d in dhs if not d["numero_documento_habil"])
    assert minuta["valor_rateio_dh"] == 205066.16                 # a armadilha
    assert _pg(PLANO_91573)["pendentes"][0]["valor"] == 192933.84


def test_plano_pago_inteiro_vai_para_a_parte_3():
    pg = _pg(PLANO_67457)
    assert pg["valor_desembolsado"] == 200000.0
    assert pg["pago_integral"] is True
    assert {o["numero_ob"] for o in pg["obs"]} == {"2024OB000437", "2024OB000419"}
    assert pg["data_ultimo_desembolso"] == "25/06/2024"


def test_PARIDADE_com_a_SPA_no_mesmo_plano():
    """⭐ O teste que autoriza a troca. O 91573 pela SPA (payload de 24/08) e
    pela oficial (14/09): o RM tem de ler EXATAMENTE a mesma coisa."""
    spa = asyncio.run(pagamentos_do_plano(_CliSpa(), 91573, 398000.0))
    ofi = _pg(PLANO_91573)
    for chave in ("valor_total", "valor_desembolsado", "valor_a_desembolsar",
                  "data_ultimo_desembolso", "pago_integral"):
        assert ofi[chave] == spa[chave], chave
    assert _desembolso_ops_obs(ofi) == _desembolso_ops_obs(spa)
    assert _ano_pagamento_ops_obs(ofi) == _ano_pagamento_ops_obs(spa)
    for campo in ("dh_id", "numero_dh", "minuta", "numero_empenho", "valor",
                  "opob_id", "numero_op", "numero_ob", "data_emissao_ob"):
        assert ofi["obs"][0][campo] == spa["obs"][0][campo], campo
    assert divergencia_de_paridade(ofi, spa) is None


def test_as_chaves_sao_as_mesmas_do_caminho_da_SPA():
    """Quem lê `pagamentos` (RM, tela, PDF) não pode notar a troca de fonte."""
    spa = asyncio.run(pagamentos_do_plano(_CliSpa(), 91573, 398000.0))
    ofi = _pg(PLANO_91573)
    assert set(ofi) - {"fonte"} == set(spa)
    assert set(ofi["obs"][0]) - {"spa_pendente", "spa_conferido"} == set(spa["obs"][0])


def test_cpf_e_historico_sao_herdados_da_rodada_anterior():
    """A oficial não publica CPF de ordenador/gestor nem evento de OP. O que a
    SPA já deu não é perguntado de novo."""
    spa = asyncio.run(pagamentos_do_plano(_CliSpa(), 91573, 398000.0))
    ofi = _pg(PLANO_91573, anterior=spa)
    o = ofi["obs"][0]
    assert o["ordenador_despesa"] == "***.272.701-**"
    assert len(o["historico"]) == 3
    assert o.get("spa_conferido") is True and "spa_pendente" not in o


def test_sem_heranca_a_OP_fica_pendente_para_a_reserva_na_SPA():
    o = _pg(PLANO_91573)["obs"][0]
    assert o["spa_pendente"] is True and o["ordenador_despesa"] == ""


def test_OP_que_ganhou_ordem_bancaria_perde_a_heranca():
    """O histórico herdado pararia em "aguardando assinatura" para sempre."""
    spa = asyncio.run(pagamentos_do_plano(_CliSpa(), 91573, 398000.0))
    spa["obs"][0]["numero_ob"] = ""          # na rodada anterior ainda sem OB
    o = _pg(PLANO_91573, anterior=spa)["obs"][0]
    assert o.get("spa_pendente") is True


def test_divergencia_de_paridade_so_na_troca_de_fonte():
    novo = {"valor_desembolsado": 100.0, "pago_integral": False, "fonte": "api_oficial"}
    spa = {"valor_desembolsado": 250.0, "pago_integral": True}
    assert "desembolsado 250.00 (SPA) -> 100.00 (oficial)" in divergencia_de_paridade(novo, spa)
    assert divergencia_de_paridade(novo, {**spa, "fonte": "api_oficial"}) is None
    assert divergencia_de_paridade(novo, None) is None
    assert divergencia_de_paridade(novo, {"valor_desembolsado": 100.004,
                                          "pago_integral": False}) is None


# ---------------------------------------------------------------------------
# O status da rodada — UMA linha no ingestion_log
# ---------------------------------------------------------------------------
def test_status_da_rodada():
    ok = {"status": "success", "gravados": 405, "erro": None}
    assert status_da_rodada(ok, {"falhas": 0, "restantes": 0}) == ("success", 405, None)
    st, n, erro = status_da_rodada(ok, {"falhas": 3, "restantes": 0})
    assert st == "partial" and n == 405 and "3 plano(s) sem resposta" in erro
    st, _, erro = status_da_rodada(ok, {"falhas": 0, "restantes": 40})
    assert st == "partial" and "40 plano(s)" in erro
    st, _, erro = status_da_rodada(ok, {"erro": "boom"})
    assert st == "partial" and "boom" in erro
    # erro da listagem manda, e não conta registro
    assert status_da_rodada({"status": "error", "gravados": 7, "erro": "x"},
                            {"falhas": 0}) == ("error", 0, "x")


# ---------------------------------------------------------------------------
# O orçamento cabe no kill da Scheduled Task — com o teto velho e o novo
# ---------------------------------------------------------------------------
def test_as_fatias_cabem_no_kill_da_task():
    """O default continua casado com o `timeout -k 30 1600` que as tasks tinham
    até 14/09/2026; quem sobe o kill sobe `TE_TETO_TAREFA_S` no MESMO comando.
    Nos dois casos, listagem + reserva cabem no teto, e o teto deixa folga para
    o commit e o log antes do kill."""
    assert te._TETO_TAREFA_S == 1450.0
    reserva = te._DET_MIN_S + te._SPA_BUDGET_S
    for teto, kill in ((1450.0, 1600.0), (3150.0, 3300.0)):
        listagem = te._teto_listagem_s(te._BUDGET_S, teto, reserva)
        assert listagem + reserva <= teto
        assert teto + 120 <= kill


# ---------------------------------------------------------------------------
# A migration
# ---------------------------------------------------------------------------
def test_a_migration_e_valida_idempotente_e_registrada_depois_da_tabela():
    from pathlib import Path

    import pglast

    from services.startup import MIGRATION_FILES
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "add_te_detalhe.sql").read_text(encoding="utf-8")
    pglast.parse_sql(sql)
    assert "ADD COLUMN IF NOT EXISTS detalhe " in sql
    assert "CREATE TABLE IF NOT EXISTS fonte_atualizacao" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_te_detalhe_fila" in sql
    assert MIGRATION_FILES.index("add_te_detalhe.sql") > \
        MIGRATION_FILES.index("add_transferegov_te.sql")
    assert MIGRATION_FILES.index("add_te_detalhe.sql") < \
        MIGRATION_FILES.index("add_auditoria_imutavel.sql")


# ---------------------------------------------------------------------------
# Fase 3 — a reserva na SPA para na primeira recusa
# ---------------------------------------------------------------------------
class _CurFalso:
    def __init__(self, linhas):
        self.linhas = linhas
        self.updates = []

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith("UPDATE"):
            self.updates.append(json.loads(params["pg"]))

    def fetchall(self):
        return self.linhas

    def close(self):
        pass


class _CnFalsa:
    def __init__(self, cur):
        self.cur = cur
        self.autocommit = True

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def close(self):
        pass


def _reserva(monkeypatch, linhas, cli):
    cur = _CurFalso(linhas)
    monkeypatch.setattr(te.psycopg2, "connect", lambda *_a, **_k: _CnFalsa(cur))
    monkeypatch.setattr(te.httpx, "AsyncClient", lambda *a, **k: cli)
    monkeypatch.setattr(te, "_PGTO_DELAY", 0)
    return asyncio.run(te.run_reserva_spa(budget_s=60)), cur


class _CliCtx(_CliSpa):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def test_a_reserva_completa_a_OP_pendente(monkeypatch):
    pg = _pg(PLANO_91573)
    r, cur = _reserva(monkeypatch, [(91573, pg)], _CliCtx())
    assert r["completadas"] == 1 and not r["recusada"]
    o = cur.updates[0]["obs"][0]
    assert o["ordenador_despesa"] == "***.272.701-**" and len(o["historico"]) == 3
    assert o["spa_conferido"] is True and "spa_pendente" not in o


def test_a_reserva_para_na_primeira_recusa(monkeypatch):
    """Requisição REJEITADA renova a pena da quota por IP (INFRA.md §5)."""
    pg1, pg2 = _pg(PLANO_91573), _pg(PLANO_91573)
    cli = _CliCtx(status_opob=403)
    r, cur = _reserva(monkeypatch, [(1, pg1), (2, pg2)], cli)
    assert r["recusada"] is True and r["consultadas"] == 1
    assert cur.updates == []
    assert sum(1 for u in cli.urls if "/opob/" in u) == 1
