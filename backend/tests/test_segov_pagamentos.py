"""Pagamentos dos convenios estaduais pelo CSV aberto da SEGOV (15/09/2026).

Pedido do dono: "vi que ja apareceu os dados bancarios la nos convenios
Estaduais, falta agora as informacoes de pagamentos". A fonte que o RM tinha
para isso (Transparencia MG, Joomla) da 403 na VPS; o CSV da SEGOV responde.

⚠️ OS CABECALHOS DAS FIXTURES SAO OS REAIS de dados.mg.gov.br (datapackage.json
do dataset `portal_convenios_saida`, lido em 15/09/2026), nao inventados: o
`pagamento{ano}` tem 17 colunas com `valor_pago_financeiro`; o `pagamentorp{ano}`
tem 17 com `valor_pago_processado`/`valor_pago_nao_processado` e SEM empenhado.
"""
import json
import os
import re
from datetime import date

import pytest

from ingestion import status_coleta as st
from ingestion.segov_pagamentos import (_SQL_UPSERT, _money, agregar_por_chave, casar,
                                        chave_siafi, indice_convenios, ler_csv,
                                        linha_para_empenho, resolver_recursos)
from services.rm_builder import _complemento_segov, _segov_campos, _segov_resumo

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATION = os.path.join(RAIZ, "migrations", "add_segov_convenios_empenhos.sql")

_CAB_PG = ("contratoconvenio_saida;numero_empenho;data_registro_doc_empenho;razao_social_credor;"
           "cnpj_cpf_credor_formatado;unidade_orcamentaria_codigo;unidade_orcamentaria_sigla;"
           "unidade_orcamentaria_nome;elemento_despesa_codigo;elemento_despesa_descricao;"
           "item_despesa_codigo;item_despesa_descricao;fonte_recurso_codigo;fonte_recurso_descricao;"
           "valor_despesa_empenhada;valor_despesa_liquidada;valor_pago_financeiro")
_CAB_RP = ("contratoconvenio_saida;numero_empenho;data_registro_doc_empenho;razao_social_credor;"
           "cnpj_cpf_credor_formatado;unidade_orcamentaria_sigla;unidade_orcamentaria_codigo;"
           "unidade_orcamentaria_nome;elemento_despesa_codigo;elemento_despesa_descricao;"
           "item_despesa_codigo;item_despesa_descricao;fonte_recurso_codigo;fonte_recurso_descricao;"
           "valor_despesa_liquidada;valor_pago_processado;valor_pago_nao_processado")


def _csv(cab: str, linhas: list[str]) -> bytes:
    """Como o Estado publica: UTF-8 COM BOM e ';'."""
    return ("﻿" + cab + "\n" + "\n".join(linhas) + "\n").encode("utf-8")


PG = _csv(_CAB_PG, [
    # a linha real do cabecalho lido em 15/09 (credor OS, nao e prefeitura)
    "9301439;268;2026-06-24 00:00:00;ASSOCIACAO CENTRO DE EDUCACAO;02.663.026/0001-45;1261;SEE;"
    "SECRETARIA DE ESTADO DE EDUCACAO;85;CONTRATO DE GESTAO;1;CONTRATO DE GESTAO;10;"
    "RECURSOS ORDINARIOS;5209543,86;5209543,86;5209543,86",
    # convenio NOSSO: empenhado, nada pago ainda
    "9492993;310;2026-03-05 00:00:00;PM ARAUJOS;18.301.010/0001-22;1261;SEE;"
    "SECRETARIA DE ESTADO DE EDUCACAO;41;CONTRIBUICOES;1;CONTRIBUICOES;10;"
    "RECURSOS ORDINARIOS;519171,00;0,0;0,0",
    # sem numero de empenho: nao ha o que gravar
    "9492993;;2026-03-05 00:00:00;PM ARAUJOS;18.301.010/0001-22;1261;SEE;SEE;41;C;1;C;10;R;1,0;0,0;0,0",
])
RP = _csv(_CAB_RP, [
    "9492993;178;2025-11-06 00:00:00;PM ARAUJOS;18.301.010/0001-22;SEE;1261;"
    "SECRETARIA DE ESTADO DE EDUCACAO;41;CONTRIBUICOES;1;CONTRIBUICOES;71;FUNDO;"
    "259585,50;259585,50;0,0",
])


# ------------------------------------------------------------ o package_show --
def test_resolve_so_os_csvs_de_pagamento_pelo_NOME_e_ordena_por_ano():
    """Os UUIDs de recurso nao sao fixados: o dataset e republicado toda semana.
    Entram 'Pagamentos AAAA' e 'Restos a Pagar AAAA'; convenios_saida.csv e o
    datapackage ficam de fora."""
    pacote = {"success": True, "result": {"resources": [
        {"name": "Convênios de Saída", "url": "https://x/convenios_saida.csv"},
        {"name": "Pagamentos 2026", "url": "https://x/pagamento2026.csv"},
        {"name": "Restos a Pagar 2025", "url": "https://x/pagamentorp2025.csv"},
        {"name": "Pagamentos 2025", "url": "https://x/pagamento2025.csv"},
        {"name": "datapackage.json", "url": "https://x/datapackage.json"},
        {"name": "Pagamentos 2024", "url": ""},   # sem url nao entra
    ]}}
    assert resolver_recursos(pacote) == [
        ("pg", 2025, "https://x/pagamento2025.csv"),
        ("rp", 2025, "https://x/pagamentorp2025.csv"),
        ("pg", 2026, "https://x/pagamento2026.csv"),
    ]
    assert resolver_recursos({}) == []


# ----------------------------------------------------------------- o parser --
def test_o_BOM_nao_engole_a_primeira_coluna():
    """⚠️ A mesma armadilha do backfill do CKAN: BOM colado em
    'contratoconvenio_saida' faz todo .get() devolver None e a juncao sai
    VAZIA sem erro."""
    linhas = list(ler_csv(PG))
    assert linhas[0]["contratoconvenio_saida"] == "9301439"
    assert linhas[0]["valor_pago_financeiro"] == "5209543,86"


def test_linha_do_pagamento_vira_empenho_com_os_tres_valores():
    e = linha_para_empenho(list(ler_csv(PG))[1], "pg", 2026)
    assert e["nr_siafi"] == "9492993" and e["numero_empenho"] == "310"
    assert e["ano_arquivo"] == 2026 and e["tipo"] == "pg"
    assert str(e["dt_empenho"]) == "2026-03-05"
    assert e["credor_nome"] == "PM ARAUJOS" and e["uo_sigla"] == "SEE"
    assert e["vr_empenhado"] == 519171.0
    assert e["vr_liquidado"] == 0.0 and e["vr_pago"] == 0.0, "'0,0' e ZERO medido, nao None"


def test_restos_a_pagar_soma_o_pago_e_NAO_inventa_empenhado():
    """O RP nao traz a coluna de empenhado: gravar 0 diria 'nao houve empenho'
    sobre um resto a pagar, que e empenho por definicao."""
    e = linha_para_empenho(list(ler_csv(RP))[0], "rp", 2026)
    assert e["vr_empenhado"] is None
    assert e["vr_liquidado"] == 259585.5
    assert e["vr_pago"] == 259585.5   # processado + nao processado


def test_sem_numero_de_empenho_nao_ha_o_que_gravar():
    assert linha_para_empenho(list(ler_csv(PG))[2], "pg", 2026) is None


def test_money_segue_o_contrato_de_virgula_decimal():
    assert _money("5209543,86") == 5209543.86 and _money("0,0") == 0.0
    assert _money("1.234,56") == 1234.56 and _money("1000") == 1000.0
    assert _money("1.000") is None, "ambiguo (mil, ou 1,000?) -> nao medido, nunca mil vezes menor"
    assert _money("") is None and _money(None) is None and _money("abc") is None


def test_duas_linhas_da_mesma_NE_por_item_de_despesa_viram_UM_empenho_somado():
    """O CSV e por ITEM de despesa: uma NE com dois itens vem em duas linhas
    com a mesma identidade (SIAFI, NE, UO). Sem agregar, o upsert 'sobrescreve'
    ficava so com a ultima e a NE saia menor, calada, com status success."""
    csv_ = _csv(_CAB_PG, [
        "9492993;310;2026-03-05 00:00:00;PM ARAUJOS;18.301.010/0001-22;1261;SEE;SEE;44;"
        "INVESTIMENTOS;1;OBRAS;10;RO;300000,00;100000,00;100000,00",
        "9492993;310;2026-03-05 00:00:00;PM ARAUJOS;18.301.010/0001-22;1261;SEE;SEE;44;"
        "INVESTIMENTOS;2;INSTALACOES;10;RO;219171,00;0,0;0,0",
        "9492993;311;2026-03-06 00:00:00;PM ARAUJOS;18.301.010/0001-22;1261;SEE;SEE;44;"
        "INVESTIMENTOS;1;OBRAS;10;RO;1,00;0,0;0,0",
    ])
    ag = agregar_por_chave(linha_para_empenho(r, "pg", 2026) for r in ler_csv(csv_))
    assert [(e["numero_empenho"], e["vr_empenhado"], e["vr_liquidado"], e["vr_pago"]) for e in ag] == [
        ("310", 519171.0, 100000.0, 100000.0), ("311", 1.0, 0.0, 0.0)]
    assert len(json.loads(ag[0]["raw_data"])) == 2, "os dois itens ficam no raw_data"
    assert json.loads(ag[1]["raw_data"])["numero_empenho"] == "311"


# ---------------------------------------------------------------- a juncao --
def test_chave_siafi_tolera_zero_a_esquerda_e_espaco():
    assert chave_siafi(" 9492993 ") == "9492993"
    assert chave_siafi("09492993") == "9492993"
    assert chave_siafi(None) == ""


def test_so_o_convenio_NOSSO_entra_e_ja_vinculado():
    por_siafi = indice_convenios([(41, 1, "9492993"), (42, 1, "1111111")])
    emp = [linha_para_empenho(r, "pg", 2026) for r in ler_csv(PG)]
    casados = casar([e for e in emp if e], por_siafi)
    assert [e["nr_siafi"] for e in casados] == ["9492993"]
    assert casados[0]["convenio_id"] == 41 and casados[0]["municipio_id"] == 1


# ----------------------------------------------------------------- o upsert --
def test_os_valores_SOBRESCREVEM_e_nao_congelam():
    """Empenhado/liquidado/pago mudam toda semana. Um COALESCE congelaria a
    semana em que a linha nasceu (o erro do #328 no simec_termos)."""
    do_update = _SQL_UPSERT[_SQL_UPSERT.index("DO UPDATE SET"):]
    for c in ("vr_empenhado", "vr_liquidado", "vr_pago", "convenio_id"):
        assert re.search(rf"{c}\s*=\s*EXCLUDED\.{c}", do_update), f"{c} nao e atualizado"
    assert "COALESCE(segov_convenios_empenhos." not in do_update


def test_o_conflito_e_a_identidade_da_fonte_com_a_UO():
    assert "ON CONFLICT (nr_siafi, ano_arquivo, tipo, numero_empenho, COALESCE(uo_sigla, ''))" in _SQL_UPSERT


# -------------------------------------------------------------- a migration --
def test_a_migration_esta_no_boot_e_e_valida_para_o_postgres():
    from services.startup import MIGRATION_FILES
    assert "add_segov_convenios_empenhos.sql" in MIGRATION_FILES
    idx = MIGRATION_FILES.index("add_segov_convenios_empenhos.sql")
    assert idx < MIGRATION_FILES.index("add_auditoria_imutavel.sql")
    pglast = pytest.importorskip("pglast", reason="pglast ausente — checagem PULADA")
    pglast.parse_sql(open(MIGRATION, encoding="utf-8").read())


def test_a_migration_e_idempotente_e_solta_o_convenio_apagado():
    """`fix_duplicatas_chave_natural.sql` faz DELETE em convenios_estadual a
    cada boot — sem ON DELETE SET NULL essa migration passaria a falhar."""
    sql = open(MIGRATION, encoding="utf-8").read()
    corpo = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "CREATE TABLE IF NOT EXISTS segov_convenios_empenhos" in corpo
    assert "REFERENCES convenios_estadual(id) ON DELETE SET NULL" in corpo
    assert "DROP" not in corpo.upper()
    for c in ("vr_empenhado", "vr_liquidado", "vr_pago"):
        linha = next(l for l in corpo.splitlines() if l.strip().startswith(c))
        assert "DEFAULT" not in linha.upper(), f"{c} com DEFAULT diria 'zero' sobre o que nao veio"


# ------------------------------------------------------------- o status --
def test_status_honesto_da_carga():
    assert st.segov_pagamentos(10, 10, 50, 40) == ("success", None)
    assert st.segov_pagamentos(10, 10, 0, 0) == ("success", None), "tenant sem SIAFI: nada a casar"
    s, m = st.segov_pagamentos(0, 0, 50, 0)
    assert s == "error" and "package_show" in m
    s, m = st.segov_pagamentos(0, 10, 50, 0)
    assert s == "error" and "WAF" in m
    s, m = st.segov_pagamentos(10, 10, 50, 0)
    assert s == "partial" and "0 casaram" in m
    s, m = st.segov_pagamentos(8, 10, 50, 40)
    assert s == "partial" and "2 de 10" in m


# ------------------------------------------------------------- o RM le --
_L = [  # (numero_empenho, dt_empenho, vr_empenhado, vr_liquidado, vr_pago, tipo, ano_arquivo, uo)
    ("310", date(2026, 3, 5), 519171.0, 0.0, 0.0, "pg", 2026, "SEE"),
    # restos a pagar de 2026 de uma NE REGISTRADA em 2025 (como a fixture RP)
    ("178", date(2025, 11, 6), None, 259585.5, 259585.5, "rp", 2026, "SEE"),
]


def test_resumo_vazio_e_NAO_CONSULTADO():
    assert _segov_resumo([]) == {} and _segov_resumo(None) == {}
    assert _segov_campos({}, False) == {}


def test_resumo_soma_e_monta_a_linha_das_NEs_sem_fabricar_lancamento():
    """O CSV nao tem data de pagamento: o bloco NAO cria `desembolsos` (a caixa
    do PDF imprimiria a data do EMPENHO como se fosse a do pagamento)."""
    r = _segov_resumo(_L)
    assert r["valor_empenhado"] == 519171.0
    assert r["valor_pago"] == 259585.5
    assert "NE 310/2026 — R$ 519.171,00 — empenhado em 05/03/2026 — pago R$ 0,00" in r["nes"]
    # o ano e o DA NOTA (data do registro), nao o do arquivo; o exercicio do RP
    # vai entre parenteses ao lado do pago
    assert ("NE 178/2025 — empenhado em 06/11/2025 — pago R$ 259.585,50 "
            "(R$ 259.585,50 em restos a pagar 2026)") in r["nes"]
    assert "desembolsos" not in r


def test_a_mesma_NE_em_pagamento_e_restos_a_pagar_e_UMA_linha_com_o_ano_da_nota():
    """Medido no CSV vivo de 15/09/2026: 99 das 160 linhas do rp2026 sao NEs de
    2025 que tambem estao no pg2025. Uma linha por ARQUIVO mostrava "NE 634/2025
    ... pago R$ 0,00; NE 634/2026 (restos a pagar) ... pago R$ 99.932,16" — duas
    notas de dois anos onde ha uma. As somas nao mudam."""
    r = _segov_resumo([
        ("634", date(2025, 11, 6), 99932.16, 0.0, 0.0, "pg", 2025, "SEE"),
        ("634", date(2025, 11, 6), None, 99932.16, 99932.16, "rp", 2026, "SEE"),
    ])
    assert r["nes"] == ("NE 634/2025 — R$ 99.932,16 — empenhado em 06/11/2025 — "
                        "pago R$ 99.932,16 (R$ 99.932,16 em restos a pagar 2026)")
    assert r["valor_empenhado"] == 99932.16 and r["valor_pago"] == 99932.16


def test_empenhado_so_afirma_SIM_e_o_desembolsado_so_sem_o_joomla():
    r = _segov_resumo(_L)
    c = _segov_campos(r, mg_consultado=False)
    assert c["empenhado"] == "Sim" and c["valor_empenhado"] == 519171.0
    assert c["valor_desembolsado"] == 259585.5
    # O Joomla respondeu: a caixa de desembolso e dele (OB a OB); a SEGOV
    # continua dando NEs e valor empenhado, que ele nao grava.
    c2 = _segov_campos(r, mg_consultado=True)
    assert "valor_desembolsado" not in c2 and c2["nes"] == c["nes"]
    # so RP (sem empenhado medido) nao afirma "Sim"
    c3 = _segov_campos(_segov_resumo(_L[1:]), False)
    assert "empenhado" not in c3 and c3["valor_empenhado"] is None


# ------------------------------------------------------------- o ingest --
class _Cur:
    """psycopg2 falso, roteado por substring do SQL (o bastante para ingest())."""
    def __init__(self, count_mg=1, nossos=None, falhar_ne=None):
        self.count_mg, self.nossos, self.falhar_ne = count_mg, nossos or [], falhar_ne
        self.execucoes = []
        self._fetch = None

    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))
        if "SELECT count(*)" in sql:
            self._fetch = (self.count_mg,)
        elif "EXTRACT(EPOCH" in sql:
            self._fetch = (None,)          # nunca rodou: nao ha o que pular
        elif ("INSERT INTO segov_convenios_empenhos" in sql and self.falhar_ne
              and params.get("numero_empenho") == self.falhar_ne):
            raise RuntimeError("boom")

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return self.nossos

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur, self.commits, self.rollbacks = cur, 0, 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def _roda(monkeypatch, cur):
    import ingestion.segov_pagamentos as sp
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://u:p@localhost/d")
    monkeypatch.delenv("SEGOV_FORCE", raising=False)
    monkeypatch.delenv("SEGOV_ENABLED", raising=False)
    conn = _Conn(cur)
    monkeypatch.setattr(sp.psycopg2, "connect", lambda url: conn)
    pacote = {"result": {"resources": [{"name": "Pagamentos 2026", "url": "https://x/pg"},
                                       {"name": "Restos a Pagar 2026", "url": "https://x/rp"}]}}

    def _baixar(url):
        if url == sp.PACKAGE_URL:
            return json.dumps(pacote).encode()
        if url.endswith("/pg"):
            return PG
        if url.endswith("/rp"):
            return RP
        raise RuntimeError("url inesperada " + url)
    monkeypatch.setattr(sp, "_baixar", _baixar)
    return sp.ingest(), conn


def _log(conn):
    """(source, status, records, erro) do INSERT em ingestion_log, ou None."""
    for sql, params in reversed(conn.cur.execucoes):
        if "ingestion_log" in sql:
            return params
    return None


def test_ingest_grava_so_o_que_casou_e_loga_success(monkeypatch):
    cur = _Cur(count_mg=1, nossos=[(41, 1, "9492993")])
    n, conn = _roda(monkeypatch, cur)
    ups = [p for s, p in cur.execucoes if "INSERT INTO segov_convenios_empenhos" in s]
    assert n == 2
    assert [(p["tipo"], p["numero_empenho"], p["convenio_id"], p["municipio_id"]) for p in ups] == [
        ("pg", "310", 41, 1), ("rp", "178", 41, 1)]
    assert all(p["nr_siafi"] == "9492993" for p in ups), "o 9301439 (nao e nosso) nao entra"
    assert _log(conn) == ("segov_pagamentos", "success", 2, None)
    assert conn.commits >= 3   # um por arquivo + o do log


def test_ingest_zero_casados_e_partial__e_tenant_sem_MG_nem_baixa(monkeypatch):
    n, conn = _roda(monkeypatch, _Cur(count_mg=1, nossos=[(41, 1, "1111111")]))
    assert n == 0 and _log(conn)[1] == "partial" and "0 casaram" in _log(conn)[3]
    n2, conn2 = _roda(monkeypatch, _Cur(count_mg=0))
    assert n2 == 0 and _log(conn2) is None
    assert not [s for s, _ in conn2.cur.execucoes if "INSERT" in s]


def test_linha_que_falha_no_upsert_volta_ao_savepoint_e_a_rodada_vira_partial(monkeypatch):
    cur = _Cur(count_mg=1, nossos=[(41, 1, "9492993")], falhar_ne="178")
    n, conn = _roda(monkeypatch, cur)
    sqls = [s for s, _ in cur.execucoes]
    assert n == 1 and "ROLLBACK TO SAVEPOINT sp_seg" in sqls
    assert _log(conn)[1] == "partial" and "1 linha(s) nao gravadas" in _log(conn)[3]


def test_o_atraso_do_dump_da_cge_entra_como_linha_propria_e_nao_troca_o_total():
    """Medido: 22 de 4.888 NEs em que a SEGOV (do dia) diz pago mais que as OBs
    do dump da CGE (de 2-5 dias antes). A diferenca vira uma linha rotulada,
    sem data nem OB, e o total sobe junto — cabecalho, lista e marcador ficam
    consistentes. Quando a OB chegar, a diferenca e zero e a linha some."""
    sg = {"valor_pago": 801000.0}
    mg = {"_consultado": True, "_incerto": False, "valor_desembolsado": 35.7}
    des = {"valor_desembolsado": 35.7,
           "desembolsos": [{"data": "14/05/2026", "valor": 35.7, "numero_ob": "1674", "situacao": "OB emitida"}]}
    c = _complemento_segov(sg, mg, des)
    assert c["valor_desembolsado"] == 801000.0
    assert len(c["desembolsos"]) == 2 and c["desembolsos"][0]["numero_ob"] == "1674"
    extra = c["desembolsos"][1]
    assert extra["valor"] == 800964.3 and extra["data"] == "" and extra["numero_ob"] == ""
    assert extra["situacao"] == "pago segundo a SEGOV — OB sem nº/data no dump da CGE", \
        "o rotulo descreve o fato, nao a causa (atraso OU NE nao resolvida)"
    # iguais, CGE mais fresca (estorno) ou sem SEGOV: nada a complementar
    assert _complemento_segov({"valor_pago": 35.7}, mg, des) == {}
    assert _complemento_segov({"valor_pago": 10.0}, mg, des) == {}
    assert _complemento_segov({}, mg, des) == {} and _complemento_segov(None, mg, des) == {}
    # CGE/Joomla incerto ou nao consultado: o RM cala, como sempre
    assert _complemento_segov(sg, {"_consultado": True, "_incerto": True, "valor_desembolsado": 0}, des) == {}
    assert _complemento_segov(sg, {}, des) == {}


def test_o_cron_do_sigcon_chama_a_carga_depois_do_backfill():
    """Nos DOIS pipelines (cron e fila on-demand), logo apos o backfill do CKAN,
    que e quem promove o nr_siafi usado na juncao."""
    for nome in ("run_sigcon_cron.py", "run_queue_sigcon.py"):
        src = open(os.path.join(RAIZ, "ingestion", nome), encoding="utf-8").read()
        i_bf = src.index("sigcon_ckan_backfill import backfill")
        i_sg = src.index("segov_pagamentos import ingest")
        assert i_bf < i_sg, f"{nome}: a carga da SEGOV precisa vir DEPOIS do backfill"
