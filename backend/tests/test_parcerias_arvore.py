"""A ÁRVORE DA PROPOSTA de Gestão de Parcerias e as EMENDAS INDICADAS (15/09/2026).

As respostas em `fixtures/parcerias_arvore.json` são REAIS: capturadas de
`api-publica.transferegov.gestao.gov.br/parcerias` em 15/09/2026, passando pelo
próprio `arvore_da_proposta`. Duas propostas:

  75376 — Nova Palma/RS, parceria 75161: R$ 299.999,00 pagos por OB em
          26/05/2026, parados na conta de INVESTIMENTO (R$ 301.614,37), com o
          ingresso ainda "Não Classificado". A parceria diz "Aprovada".
  26975 — Nova Serrana/MG, com documento hábil e ordem bancária.

E uma amostra real de `/beneficiario_emenda_parlamentar` de Nova Palma, Santa
Maria e Santa Maria do Herval — o caso do filtro "contém".
"""
import copy
import inspect
import json
import os

from ingestion import parcerias as pc
from ingestion.parcerias import (
    _chave_nome, _doc_cnpj, _filhos, arvore_da_proposta, emendas_da_uf,
    execucao_da_arvore, grava_emendas_do_municipio, linha, linha_emenda_indicada,
)

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "parcerias_arvore.json")
with open(_FIXTURE, encoding="utf-8") as _f:
    _CAPTURA = json.load(_f)
NP = _CAPTURA["alvos"]["75376"]
NS = _CAPTURA["alvos"]["26975"]


def _chave(url: str, params: dict | None) -> str:
    caminho = url.rsplit("/parcerias/", 1)[-1]
    p = {k: v for k, v in (params or {}).items() if k not in ("pagina", "tamanho_da_pagina")}
    return caminho + "?" + "&".join(f"{k}={p[k]}" for k in sorted(p))


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


def _envelope(data, total=None, paginas=1):
    return {"data": data, "total_items": len(data) if total is None else total,
            "total_pages": paginas, "page_number": 1, "page_size": 200}


class _Replay:
    """Dublê do httpx.Client: responde com a CAPTURA REAL por caminho +
    parâmetros. Consulta não capturada volta 404 — teste que esquecer uma
    consulta falha em vez de passar vazio."""

    def __init__(self, falhar=(), trocar=None, extra=None):
        self.respostas = copy.deepcopy(_CAPTURA["respostas"])
        self.respostas.update(extra or {})
        self.falhar = set(falhar)
        self.trocar = trocar or {}
        self.chamadas: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        k = _chave(str(url), params)
        self.chamadas.append(k)
        if k in self.falhar:
            return _Resp(None, 500)
        if k in self.trocar:
            return _Resp(self.trocar[k])
        if k in self.respostas:
            return _Resp(copy.deepcopy(self.respostas[k]))
        return _Resp(None, 404)


def _sem_esperas(monkeypatch):
    monkeypatch.setattr(pc, "RETRY_S", 0)
    monkeypatch.setattr(pc, "PAUSA_S", 0)


def _arvore(alvo, cli=None):
    cli = cli or _Replay()
    progs = pc.programas(cli)
    return arvore_da_proposta(cli, copy.deepcopy(alvo["proposta"]),
                              copy.deepcopy(alvo["parceria"]), progs)


# ---------------------------------------------------------------------------
# A árvore inteira
# ---------------------------------------------------------------------------
def test_a_arvore_da_75376_vem_inteira():
    a = _arvore(NP)
    assert a is not None
    assert a["programa"]["id_programa"] == NP["proposta"]["id_programa"]
    etapas = [e for m in a["metas"] for e in m["etapas_proposta"]]
    assert len(etapas) == 2 and all(e["itens"] for e in etapas)   # itens por etapa
    assert a["cronograma"][0]["vl_cronograma_desembolso"] == 299999.0
    assert "ds_parecer" in a["analises"][0]
    ex = a["execucao"]
    assert len(ex["contas"]) == 1 and len(ex["contas"][0]["extrato"]) == 2
    assert ex["contas"][0]["opp"] == []
    assert ex["empenhos"][0]["numero_nota_empenho_gerada"] == "2026NE478986"
    assert ex["documentos_habeis"][0]["ordens"][0]["nr_ordem_bancaria"] == "2026OB038114"


def test_o_dinheiro_parado_na_aplicacao_e_o_ingresso_nao_classificado():
    """O que a tela nunca mostrou: o repasse chegou em maio, está rendendo na
    conta de INVESTIMENTO, e o município ainda não classificou o ingresso."""
    r = _arvore(NP)["_resumo"]
    assert r["saldo_corrente"] == 0.0
    assert r["saldo_investimento"] == 301614.37
    assert r["saldo_total"] == 301614.37
    assert r["data_saldo"] == "2026-06-16"
    assert r["nao_classificado"] == 299999.0


def test_pago_vem_da_ordem_bancaria_e_nao_da_situacao_da_parceria():
    """⚠️ A parceria diz "Aprovada" — e o dinheiro já saiu (OP "Paga", OB em
    26/05/2026). Ler a situação esconderia o pagamento."""
    assert NP["parceria"]["in_situacao_parceria"] == "Aprovada"
    r = _arvore(NP)["_resumo"]
    assert r["pago"] == 299999.0 and r["n_ordens_bancarias"] == 1
    assert r["data_ultima_ob"] == "2026-05-26"
    assert r["empenhado"] == 299999.0


def test_a_segunda_proposta_real_tambem_fecha():
    r = _arvore(NS)["_resumo"]
    assert r["pago"] == 200000.0 and r["data_ultima_ob"] == "2025-10-07"
    assert r["saldo_investimento"] == 11972.28


def test_o_cnpj_do_extrato_volta_com_os_zeros():
    """A fonte manda '530493000171' para o FNS (00.530.493/0001-71)."""
    lanc = _arvore(NP)["execucao"]["contas"][0]["extrato"]
    credito = next(l for l in lanc if l["in_transacao"] == "Crédito")
    assert credito["nu_identificacao_depositante_extrato_bancario"] == "00530493000171"


def test_normalizacao_do_documento():
    assert _doc_cnpj("530493000171") == "00530493000171"
    assert _doc_cnpj("1224018300010") == "01224018300010"
    assert _doc_cnpj("12240183000100") == "12240183000100"
    # curto demais para saber se é CPF ou CNPJ: fica cru
    assert _doc_cnpj("191") == "191"
    assert _doc_cnpj(None) is None and _doc_cnpj("") is None
    assert _doc_cnpj("***47295***") == "***47295***"


# ---------------------------------------------------------------------------
# Proposta sem parceria, e o resumo
# ---------------------------------------------------------------------------
def test_proposta_sem_parceria_tem_arvore_so_do_plano():
    cli = _Replay()
    a = arvore_da_proposta(cli, copy.deepcopy(NP["proposta"]), None, {})
    assert a is not None and a["execucao"] is None and a["_resumo"] is None
    assert not any(c.startswith(("parceria-conta", "empenho-parceria", "documento-habil"))
                   for c in cli.chamadas)


def test_op_cancelada_ou_sem_ob_nao_e_pagamento():
    arv = {"execucao": {"empenhos": [], "contas": [], "documentos_habeis": [
        {"ordens": [{"nr_ordem_bancaria": "2026OB1", "in_situacao_op": "Cancelada",
                     "vl_ordem_pagamento": 100.0, "dt_emissao_ordem_bancaria": "2026-01-01"},
                    {"nr_ordem_bancaria": "", "in_situacao_op": "Aguardando",
                     "vl_ordem_pagamento": 50.0},
                    {"nr_ordem_bancaria": "2026OB2", "in_situacao_op": "Paga",
                     "vl_ordem_pagamento": 30.0, "dt_emissao_ordem_bancaria": "2026-02-01T00:00:00"}]}]}}
    r = execucao_da_arvore(arv)
    assert r["pago"] == 30.0 and r["n_ordens_bancarias"] == 1
    assert r["data_ultima_ob"] == "2026-02-01"
    assert r["saldo_total"] is None       # sem conta: "não medido", não zero


def test_opp_efetivado_e_pagamento_a_terceiros():
    arv = {"execucao": {"empenhos": [], "documentos_habeis": [], "contas": [
        {"vl_saldo_conta_corrente": 10.0, "dt_referencia_saldo_conta_corrente": "2026-06-01",
         "opp": [{"vl_opp": 878.07, "vl_efetivado": None},
                 {"vl_opp": 500.0, "vl_efetivado": 500.0}]}]}}
    assert execucao_da_arvore(arv)["pago_a_terceiros"] == 500.0


# ---------------------------------------------------------------------------
# ⚠️ TUDO OU NADA, e o teto nas consultas filhas
# ---------------------------------------------------------------------------
def test_uma_consulta_sem_resposta_anula_a_arvore(monkeypatch):
    _sem_esperas(monkeypatch)
    cli = _Replay(falhar={"extrato-bancario?id_parceria_conta=82470"})
    assert _arvore(NP, cli) is None


def test_pagina_do_meio_faltando_tambem_anula(monkeypatch):
    _sem_esperas(monkeypatch)
    k = "item-proposta?id_etapa_proposta=130526"
    duas = {**_CAPTURA["respostas"][k], "total_pages": 2}

    class _SegundaCai(_Replay):
        def get(self, url, params=None, headers=None, timeout=None):
            if _chave(str(url), params) == k and (params or {}).get("pagina") == 2:
                return _Resp(None, 500)
            return super().get(url, params=params)

    assert _arvore(NP, _SegundaCai(trocar={k: duas})) is None


def test_filho_com_carga_nacional_anula_a_arvore():
    """1.301.416 lançamentos de extrato no Brasil: gravados como o extrato de
    UMA proposta se o filtro `id_parceria_conta` deixasse de valer."""
    k = "extrato-bancario?id_parceria_conta=82470"
    cli = _Replay(trocar={k: _envelope([{"x": 1}], total=1301416, paginas=6508)})
    assert _arvore(NP, cli) is None
    assert cli.chamadas.count(k) == 1


def test_parametro_nulo_nao_vai_para_a_rede():
    cli = _Replay()
    assert _filhos(cli, "ordem-pagamento", {"id_documento_habil": None}) == []
    assert cli.chamadas == []


def test_toda_consulta_da_arvore_passa_pelo_teto():
    fonte = inspect.getsource(arvore_da_proposta)
    assert "buscar(" not in fonte and "_filhos(" in fonte
    assert "teto_itens=TETO_FILHOS" in inspect.getsource(_filhos)


def test_a_retentativa_salva_um_soluco(monkeypatch):
    _sem_esperas(monkeypatch)
    k = "cronograma-desembolso?id_proposta=75376"

    class _Soluca(_Replay):
        ja = False

        def get(self, url, params=None, headers=None, timeout=None):
            if _chave(str(url), params) == k and not self.ja:
                self.ja = True
                self.chamadas.append(k)
                return _Resp(None, 503)
            return super().get(url, params=params)

    cli = _Soluca()
    assert _arvore(NP, cli) is not None
    assert cli.chamadas.count(k) == 2


# ---------------------------------------------------------------------------
# EMENDAS INDICADAS — por UF, casando o município por igualdade
# ---------------------------------------------------------------------------
def _cli_uf(registros, total=None):
    return _Replay(extra={"beneficiario_emenda_parlamentar?sg_uf_beneficiario_emenda=RS":
                          _envelope(registros, total=total)})


def test_santa_maria_nao_leva_as_emendas_de_santa_maria_do_herval():
    """⚠️ O filtro da fonte é "contém": `SANTA MARIA` traz SANTA MARIA DO
    HERVAL (9 de 42 na amostra real). Aqui o município casa por IGUALDADE."""
    amostra = _CAPTURA["emendas_rs_amostra"]
    idx = emendas_da_uf(_cli_uf(amostra), "RS")
    sm = idx["SANTA MARIA"]
    assert sm and all(r["nm_municipio_beneficiario_emenda"] == "SANTA MARIA" for r in sm)
    assert idx["SANTA MARIA DO HERVAL"]
    assert len(idx["NOVA PALMA"]) == 11
    total = sum(len(v) for v in idx.values())
    assert total == len(amostra)


def test_o_nome_casa_com_ou_sem_acento():
    """A fonte é sensível a acento ("MONTE SIAO" -> 0, "Monte Sião" -> 12): por
    isso a comparação é entre os dois lados normalizados."""
    assert _chave_nome("Monte Sião") == _chave_nome("MONTE SIÃO") == "MONTE SIAO"
    assert _chave_nome("Sant'Ana do Livramento") == _chave_nome("SANT ANA DO LIVRAMENTO")
    assert _chave_nome("SANTA MARIA") != _chave_nome("SANTA MARIA DO HERVAL")


def test_registro_de_outra_uf_nao_entra():
    amostra = copy.deepcopy(_CAPTURA["emendas_rs_amostra"][:2])
    amostra[0]["sg_uf_beneficiario_emenda"] = "SC"
    idx = emendas_da_uf(_cli_uf(amostra), "RS")
    assert sum(len(v) for v in idx.values()) == 1


def test_emendas_da_uf_com_carga_nacional_nao_grava():
    """78.072 no Brasil para um teto de 20.000: a UF foi ignorada."""
    assert emendas_da_uf(_cli_uf([{"x": 1}], total=78072), "RS") is None


def test_emendas_da_uf_sem_resposta_e_None(monkeypatch):
    _sem_esperas(monkeypatch)
    cli = _Replay(falhar={"beneficiario_emenda_parlamentar?sg_uf_beneficiario_emenda=RS"})
    assert emendas_da_uf(cli, "RS") is None


def test_linha_da_emenda_indicada():
    reg = next(r for r in _CAPTURA["emendas_rs_amostra"]
               if r["nm_municipio_beneficiario_emenda"] == "NOVA PALMA")
    l = linha_emenda_indicada(7, reg)
    assert l["mid"] == 7 and l["rid"] == reg["id_beneficiario_emenda_parlamentar_programa"]
    assert l["cnpj"] == "12240183000100" and l["nr_emenda"] == reg["nr_emenda"]
    assert json.loads(l["indicacoes"]) == (reg.get("indicacoes_beneficiario") or [])
    assert linha_emenda_indicada(7, {}) is None


class _CurFalso:
    def __init__(self):
        self.sqls = []

    def execute(self, sql, params=None):
        self.sqls.append((" ".join(sql.split())[:60], params))


def test_a_troca_do_conjunto_apaga_so_o_que_saiu_da_fonte():
    regs = [r for r in _CAPTURA["emendas_rs_amostra"]
            if r["nm_municipio_beneficiario_emenda"] == "NOVA PALMA"]
    cur = _CurFalso()
    assert grava_emendas_do_municipio(cur, 7, regs) == 11
    sql, params = cur.sqls[0]
    assert sql.startswith("DELETE FROM parcerias_emendas_indicadas WHERE municipio_id")
    assert params[0] == 7 and len(params[1]) == 11
    assert sum(1 for s, _ in cur.sqls if s.startswith("INSERT")) == 11


def test_municipio_sem_emenda_na_fonte_zera_o_conjunto():
    cur = _CurFalso()
    assert grava_emendas_do_municipio(cur, 7, []) == 0
    assert len(cur.sqls) == 1
    sql, params = cur.sqls[0]
    assert sql.startswith("DELETE FROM parcerias_emendas_indicadas WHERE municipio_id")
    assert params == (7,)


# ---------------------------------------------------------------------------
# A listagem ganha o `nu_externo` — a chave do FNS
# ---------------------------------------------------------------------------
def test_vazio_da_fonte_nao_apaga_emenda_nem_instrumento_ja_gravados():
    """⚠️ 14/09/2026, 06:00 UTC: HTTP 200 com a lista de emendas VAZIA para
    todas as propostas, e o upsert apagou parlamentar e emenda de 547 propostas
    no freitas e 326 no bgk. Agora o que ja se sabe so e trocado por valor."""
    sql = " ".join(pc._SQL.split())
    for col in ("id_parceria", "codigo_parceria", "situacao_parceria", "data_assinatura",
                "numero_emenda", "parlamentar", "tipo_emenda", "valor_emenda", "nu_externo"):
        assert f"{col} = COALESCE(EXCLUDED.{col}, parcerias_propostas.{col})" in sql, col


def test_rodada_sem_nenhuma_emenda_fica_amarela():
    fonte = inspect.getsource(pc.ingest)
    assert "gravados >= 20 and not com_emenda" in fonte
    assert "provavel recarga da fonte" in fonte


def test_o_nu_externo_e_o_numero_da_proposta_no_FNS():
    l = linha(7, NP["proposta"], NP["parceria"], None)
    assert l["nu_externo"] == "12240183000126003"
    assert "%(nu_externo)s" in pc._SQL
    assert "nu_externo = COALESCE(EXCLUDED.nu_externo" in pc._SQL


# ---------------------------------------------------------------------------
# A migration
# ---------------------------------------------------------------------------
def test_a_migration_e_valida_idempotente_e_depois_da_tabela():
    import pglast

    from services.startup import MIGRATION_FILES
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sql = open(os.path.join(raiz, "migrations", "add_parcerias_detalhe.sql"),
               encoding="utf-8").read()
    pglast.parse_sql(sql)
    assert "ADD COLUMN IF NOT EXISTS detalhe " in sql
    assert "ADD COLUMN IF NOT EXISTS nu_externo" in sql
    assert "CREATE TABLE IF NOT EXISTS parcerias_emendas_indicadas" in sql
    assert MIGRATION_FILES.index("add_parcerias_detalhe.sql") > \
        MIGRATION_FILES.index("add_parcerias.sql")
    assert MIGRATION_FILES.index("add_parcerias_detalhe.sql") < \
        MIGRATION_FILES.index("add_auditoria_imutavel.sql")


def test_o_teto_da_tarefa_cabe_no_kill_da_task():
    """Default casado com o `timeout -k 30 1500` da task em 15/09/2026."""
    assert pc.TETO_TAREFA_S + 60 <= 1500
    assert max(60.0, min(pc.BUDGET_S, pc.TETO_TAREFA_S - pc.DET_MIN_S)) + pc.DET_MIN_S \
        <= pc.TETO_TAREFA_S
