"""Correções da auditoria de coleta (11/09/2026).

Dois tipos, deliberadamente misturados (o prompt pede AMBOS):

- COMPORTAMENTO (§8/§10/§14) — entrada → execução → efeito, sem `assert
  "success" in file`. As funções puras de `status_coleta` recebem contadores e
  devolvem status; `siconv_federal_ingest.ingest()` e `backfill_parlamentar()`
  rodam contra um Postgres FALSO (sem banco, sem rede) e a gente inspeciona
  commit/rollback e a linha gravada em ingestion_log. `watchdog._fontes_paradas`
  roda contra um cursor falso e a gente lê os achados.
- ESTRUTURAL (§13) — regressão de FIAÇÃO: o coletor CHAMA a função pura (senão o
  teste de comportamento acima seria de código morto) e o status é PARÂMETRO do
  INSERT, não literal cravado. Guarda contra alguém recravar 'success'.

Infra (C-1 403-por-IP, C-3 Scheduled Task, A-3 heartbeat rollout, comando real
do cron) NÃO está aqui — depende de produção, e está em
docs/PRODUCAO_POS_AUDITORIA.md.
"""
import os
import types

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/d")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("BI_MODULE", "1")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fonte(rel):
    return open(os.path.join(RAIZ, rel), encoding="utf-8").read()


# ═══════════════════ COMPORTAMENTO — status_coleta (§14) ════════════════════
# Entrada real → saída real. NÃO derivado do texto do coletor: a regra vive aqui
# e é exercida pelos mesmos contadores que o coletor passa.

def test_status_simec_par_decide_por_falha_de_fetch_nao_por_contagem():
    from ingestion import status_coleta as st
    # 0 liberações SEM falha é legítimo (tenant de 1 município) → success
    assert st.simec_par(5, 0) == ("success", None)
    assert st.simec_par(1, 0) == ("success", None)
    assert st.simec_par(0, 0) == ("success", None)
    # alguns municípios sem resposta → partial; TODOS → error (Cloudflare/layout)
    assert st.simec_par(5, 2)[0] == "partial"
    assert st.simec_par(5, 5)[0] == "error"


def test_status_cauc_lista_nacional_1_para_1():
    from ingestion import status_coleta as st
    assert st.cauc(60, 60) == ("success", None)
    assert st.cauc(0, 0) == ("success", None)     # tenant sem esperado
    assert st.cauc(58, 60)[0] == "partial"        # sumiram do CSV
    assert st.cauc(0, 60)[0] == "error"           # nacional casou zero


def test_status_acordofes_planilha_vazia_vs_vinculo():
    from ingestion import status_coleta as st
    assert st.acordofes(1368, 40) == ("success", None)
    assert st.acordofes(1368, 0)[0] == "partial"  # credores ok, vínculo por nome falhou
    assert st.acordofes(0, 0)[0] == "error"       # planilha vazia/ilegível


def test_status_sigcon_ckan_so_enriquece():
    from ingestion import status_coleta as st
    assert st.sigcon_ckan(100, 90, True) == ("success", None)
    assert st.sigcon_ckan(0, 0, True) == ("success", None)   # nada nosso p/ enriquecer
    assert st.sigcon_ckan(100, 0, True)[0] == "partial"      # nada casou o dump
    assert st.sigcon_ckan(100, 90, False)[0] == "partial"    # ft_convenio não baixou


def test_status_siconv_federal_zero_e_queda_abrupta():
    from ingestion import status_coleta as st
    assert st.siconv_federal(1_000_000, 999_000) == ("success", None)
    assert st.siconv_federal(1000, 0) == ("success", None)   # 1ª carga (antes=0)
    assert st.siconv_federal(0, 1_000_000)[0] == "error"     # recarga vazia
    assert st.siconv_federal(100, 1_000_000)[0] == "partial" # queda >50%


def test_status_por_falhas_generica():
    from ingestion import status_coleta as st
    assert st.por_falhas(70, 0, "x") == ("success", None)
    assert st.por_falhas(70, 30, "x")[0] == "partial"


# ═══════════════════ COMPORTAMENTO — M-2 _money ═════════════════════════════

def test_m2_money_ponto_decimal_nao_vira_milhar():
    from ingestion.siconv_emenda_backfill import _money
    assert _money("0") == 0.0
    assert _money("1000000") == 1000000.0
    assert _money("10.50") == 10.5          # ⚠️ o BUG: replace incondicional dava 1050
    assert _money("1234.56") == 1234.56     # ⚠️ o caso do relatório: dava 123456
    assert _money("10,50") == 10.5
    assert _money("1.000,50") == 1000.5     # ponto = milhar QUANDO há vírgula
    assert _money("1.234,56") == 1234.56
    assert _money("R$ 1.234,56") == 1234.56
    assert _money("") is None and _money(None) is None
    assert _money("lixo") is None


# ═══════════════════ Postgres FALSO (comum aos testes de fluxo) ═════════════

class _FakeCur:
    def __init__(self, count_inicial=0):
        self._count = count_inicial
        self.execucoes = []          # [(sql, params)]
        self._fetch = None
    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))
        if "SELECT count(*)" in sql:
            self._fetch = (self._count,)
    def fetchone(self):
        return self._fetch
    def close(self):
        pass


class _FakeConn:
    def __init__(self, count_inicial=0):
        self.cur = _FakeCur(count_inicial)
        self.commits = 0
        self.rollbacks = 0
    def cursor(self):
        return self.cur
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        pass


def _log_gravado(conn):
    """(sql, params) do ÚLTIMO INSERT em ingestion_log, ou None. O source vai
    cravado no SQL; o status é params[0]."""
    for sql, params in reversed(conn.cur.execucoes):
        if "ingestion_log" in sql:
            return sql, params
    return None


# ═══════════════ §8 — siconv_federal: TRUNCATE seguro (5 cenários) ══════════

# o CSV real traz várias colunas; o ingest() fatia NR_PROPOSTA ([:40]), então a
# linha falsa precisa ter ID_PROPOSTA e NR_PROPOSTA como a de produção.
_IDX_SICONV = {"ID_PROPOSTA": 0, "NR_PROPOSTA": 1}


def _linhas(*idps):
    return [(idp, f"P{idp}") for idp in idps]


def _prep_siconv(monkeypatch, rows, antes):
    """Roda ingest() sem banco nem rede. `rows` = linhas do CSV de proposta."""
    from ingestion import siconv_federal_ingest as mod
    conn = _FakeConn(count_inicial=antes)
    monkeypatch.setattr(mod, "_index_convenios", lambda: {})
    monkeypatch.setattr(mod, "_open_csv", lambda url: (iter(rows), dict(_IDX_SICONV)))
    monkeypatch.setattr(mod, "_sync_url", lambda: "fake://")
    monkeypatch.setattr(mod, "execute_values", lambda *a, **k: None)
    monkeypatch.setattr(mod, "psycopg2",
                        types.SimpleNamespace(connect=lambda *a, **k: conn))
    return mod, conn


def test_c3_cenario1_coleta_normal_commita_e_success(monkeypatch):
    mod, conn = _prep_siconv(monkeypatch, _linhas("10", "20"), antes=2)
    total = mod.ingest()
    assert total == 2
    assert conn.commits >= 1 and conn.rollbacks == 0
    assert _log_gravado(conn)[1][0] == "success"


def test_c3_cenario2_download_interrompido_nao_commita(monkeypatch):
    def _stream_que_cai():
        yield ("10", "P10")
        raise ConnectionError("stream do dump caiu no meio")
    mod, conn = _prep_siconv(monkeypatch, _stream_que_cai(), antes=500_000)
    with pytest.raises(ConnectionError):
        mod.ingest()
    # ⚠️ o essencial: NUNCA comitou. O TRUNCATE não-commitado é desfeito ao fechar
    # a conexão (MVCC) → os 500.000 registros anteriores permanecem visíveis.
    assert conn.commits == 0


def test_c3_cenario3_arquivo_vazio_faz_rollback_e_error(monkeypatch):
    mod, conn = _prep_siconv(monkeypatch, [], antes=1_000_000)
    total = mod.ingest()
    assert total == 0
    assert conn.rollbacks >= 1                    # zero-guard desfez o TRUNCATE
    assert _log_gravado(conn)[1][0] == "error"    # status honesto, não 'success'


def test_c3_cenario4_arquivo_invalido_propaga_sem_commit(monkeypatch):
    # _open_csv que estoura (BOM/coluna faltando/zip corrompido) = arquivo inválido.
    from ingestion import siconv_federal_ingest as mod
    conn = _FakeConn(count_inicial=800_000)
    monkeypatch.setattr(mod, "_index_convenios", lambda: {})
    def _open_ruim(url):
        raise KeyError("ID_PROPOSTA ausente no header (layout mudou)")
    monkeypatch.setattr(mod, "_open_csv", _open_ruim)
    monkeypatch.setattr(mod, "_sync_url", lambda: "fake://")
    monkeypatch.setattr(mod, "psycopg2",
                        types.SimpleNamespace(connect=lambda *a, **k: conn))
    with pytest.raises(KeyError):
        mod.ingest()
    assert conn.commits == 0   # explode antes de tocar a base → nada é substituído


def test_c3_cenario5_execucao_repetida_e_idempotente(monkeypatch):
    mod, c1 = _prep_siconv(monkeypatch, _linhas("1", "2", "3"), antes=3)
    t1 = mod.ingest()
    mod, c2 = _prep_siconv(monkeypatch, _linhas("1", "2", "3"), antes=3)
    t2 = mod.ingest()
    assert t1 == t2 == 3   # TRUNCATE+reload → rodar de novo dá o mesmo, sem duplicar


# ═══════════════ §10 — backfill_parlamentar grava ingestion_log ═════════════
# O cron chama backfill_parlamentar() DIRETO (não main()); antes, o caminho mais
# comum (nenhuma proposta com id ainda) saía sem deixar linha, e o card de frescor
# listava a fonte sem escritor. Comportamento: a função grava mesmo nesse caminho.

def test_a4_backfill_parlamentar_grava_log_no_caminho_do_cron(monkeypatch):
    from ingestion import siconv_emenda_backfill as mod
    conn = _FakeConn()
    monkeypatch.setattr(mod, "_db", lambda: conn)
    monkeypatch.setattr(mod, "_nossas_propostas", lambda: {})  # nenhum id ainda
    n = mod.backfill_parlamentar()
    assert n == 0
    sql, params = _log_gravado(conn)
    assert "'siconv_emenda_backfill'" in sql   # source cravado no SQL
    assert params[0] == "success" and params[1] == 0


# ═══════════════ §6 — watchdog: fonte crítica órfã vira achado próprio ══════

class _FakeCurWD:
    """Cobre só as consultas de _fontes_paradas. `distinct` = fontes com linha."""
    def __init__(self, distinct):
        self._distinct = distinct
        self._rows = []
    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "GROUP BY source" in s:
            self._rows = []                                   # nenhum success
        elif "SELECT DISTINCT source FROM ingestion_log WHERE" in s:
            self._rows = []                                   # com_sucesso
        elif "SELECT DISTINCT source FROM ingestion_log" in s:
            self._rows = [(x,) for x in self._distinct]       # com_linha
        else:
            self._rows = []
    def fetchall(self):
        return self._rows
    def fetchone(self):
        return (0,)


def test_item6_watchdog_flag_fontes_criticas_orfas():
    from ingestion.watchdog_coleta import _fontes_paradas
    # as duas críticas NÃO estão entre as fontes com linha no log
    achados = _fontes_paradas(_FakeCurWD(distinct=["cauc", "fns"]), esperado={})
    orfas = {a["chave"] for a in achados if a["tipo"] == "fonte_nunca_executada"}
    # 15/09/2026: `transferegov_arvore` substituiu `siconv_empenho_aberto` (a
    # task `empenho-aberto` virou reserva; a árvore grava a mesma coluna).
    assert orfas == {"siconv_federal", "transferegov_arvore"}


def test_item6_watchdog_nao_alarma_quando_ja_rodaram():
    from ingestion.watchdog_coleta import _fontes_paradas
    cur = _FakeCurWD(distinct=["siconv_federal", "transferegov_arvore"])
    achados = _fontes_paradas(cur, esperado={})
    assert not any(a["tipo"] == "fonte_nunca_executada" for a in achados)


# ═══════════════════ ESTRUTURAL — fiação / regressão (§13) ══════════════════

def test_fiacao_coletores_chamam_status_coleta():
    """O coletor USA a função pura E o status é PARÂMETRO do INSERT (não cravado).
    Se isso quebrar, os testes de comportamento de status_coleta viram inúteis."""
    casos = [
        ("ingestion/simec_par.py", "_st.simec_par(", "'simec_par',%s"),
        ("ingestion/cauc_ingest.py", "_st.cauc(", "'cauc',%s"),
        ("ingestion/acordofes_ingest.py", "_st.acordofes(", "'acordofes',%s"),
        ("ingestion/sigcon_ckan_backfill.py", "_st.sigcon_ckan(", "'sigcon_ckan_backfill',%s"),
        ("ingestion/siconv_federal_ingest.py", "_st.siconv_federal(", "'siconv_federal',%s"),
        ("ingestion/consulta_popular_rs.py", "_st.por_falhas(", None),
        ("ingestion/cofin_ses_go.py", "_st.por_falhas(", None),
    ]
    for rel, chamada, insert in casos:
        src = _fonte(rel)
        assert chamada in src, f"{rel} não chama {chamada}"
        if insert:
            assert insert in src, f"{rel}: status deveria ser %s no INSERT"


def test_fiacao_import_status_coleta_nos_dois_estilos():
    """pytest importa como pacote (`from ingestion import ...`), o script roda
    solto (`import status_coleta`). Os dois estilos têm de existir."""
    for rel in ("ingestion/simec_par.py", "ingestion/siconv_federal_ingest.py",
                "ingestion/cofin_ses_go.py"):
        src = _fonte(rel)
        assert "from ingestion import status_coleta as _st" in src
        assert "import status_coleta as _st" in src   # o fallback do except


def test_m1_update_clausula_usa_coalesce():
    src = _fonte("ingestion/siconv_convenio_backfill.py")
    assert "COALESCE(%s, situacao_contratacao)" in src
    assert "COALESCE(%s, clausula_suspensiva_motivo)" in src
    assert "COALESCE(%s, clausula_suspensiva_dt_prevista)" in src


def test_m2_backfill_tem_uma_so_definicao_de_money():
    """A cópia aninhada (replace incondicional) foi removida; sobra a do módulo."""
    assert _fonte("ingestion/siconv_emenda_backfill.py").count("def _money(") == 1


def test_m4_cofin_ses_go_isola_municipio_com_savepoint():
    src = _fonte("ingestion/cofin_ses_go.py")
    assert "SAVEPOINT cofin_mun" in src and "ROLLBACK TO SAVEPOINT cofin_mun" in src


def test_c1_transparencia_mg_grava_ingestion_log():
    """403-por-IP (memória transparencia-mg-403-vps) precisa virar linha, não
    silêncio: sem escritor, a fonte que sempre falha some do frescor."""
    src = _fonte("ingestion/transparencia_mg.py")
    assert "def _log_ingest(" in src and "'transparencia_mg'" in src


def test_c2_tce_rs_403_e_error_nao_partial():
    """§12: 403 é FALHA DE ACESSO. O ramo `if bloqueado:` loga 'error'; 'partial'
    só pode aparecer no ramo normal (else), nunca no bloqueio."""
    for rel in ("ingestion/tce_rs.py", "ingestion/tce_rs_portal.py"):
        src = _fonte(rel)
        i = src.index("if bloqueado:")
        ramo = src[i:src.index("else:", i)]        # só o corpo do if
        assert '"error"' in ramo, f"{rel}: bloqueio deveria logar error"
        assert '"partial"' not in ramo, f"{rel}: 403 não pode ser partial"


def test_m6_emendas_estaduais_nao_comita_vazio():
    src = _fonte("ingestion/emendas_estaduais.py")
    assert "if extracted == 0:" in src and "conn.rollback()" in src
    assert "'emendas_estaduais', 'success'" in src   # caminho normal mantido


def test_item6_watchdog_criticas_no_codigo():
    """Regressão do conjunto crítico: se alguém tirar uma das duas do watchdog,
    a órfã volta a sumir no silêncio."""
    src = _fonte("ingestion/watchdog_coleta.py")
    assert "fonte_nunca_executada" in src
    assert "siconv_federal" in src and '"transferegov_arvore"}' in src
