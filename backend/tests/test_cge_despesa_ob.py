"""Data e nº da OB dos convenios estaduais pelos dumps da CGE (Fase 2, 15/09/2026).

Fixtures com os CABECALHOS REAIS de dados.mg.gov.br (lidos em 15/09/2026):
ft_despesa_2026 (24 colunas), dm_empenho_desp_2026, dm_tempo_diario,
dm_tipo_documento, ft_restos_pagar_2026 (21 colunas) e dm_empenho_resto_2026.
Os numeros sao os de Pequi: NE 881 de 05/03/2026, id_empenho 15264190, OB 1939
de 25/03/2026 R$ 938.793,55 — a mesma linha que o coletor Joomla mediu
(transparencia_mg.py:351).
"""
import gzip
import json
import os
from datetime import date

from ingestion import status_coleta as st
from ingestion.cge_despesa_ob import (_SQL_UPSERT, SIT_OB, SIT_OB_ESTORNO, anos_alvo,
                                      extrair_obs, ids_por_regex, indexar_empenhos, ler_tempo,
                                      ler_tipos, montar_bloco, resolver, url_recurso, _RE_OP,
                                      _RE_RP)
from ingestion.transparencia_mg import pagamento_confirmado
from services.rm_builder import _desembolso_ops_obs, _mg_pagamentos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gz(cab: str, linhas: list[str]) -> bytes:
    return gzip.compress(("﻿" + cab + "\n" + "\n".join(linhas) + "\n").encode("utf-8"))


TIPOS = _gz("id_tipo_documento;cd_tipo_documento;nome", [
    "1;0;EMPENHO", "498;5;OP PAGA", "532;6;OP PENDENTE", "525;51;OP PAGA SEM DOCUMENTO DE ORIGEM",
    "576;52;OP PENDENTE SEM DOCUMENTO DE ORIGEM", "544;78;OP PAGAMENTO DOCUMENTO FOLHA",
    "510;3;LIQUIDACAO - BRUTO", "488;19;PAGAMENTO RESTO A PAGAR NAO PROCESSADO",
    "561;20;PAGAMENTO RESTO A PAGAR PROCESSADO", "505;50;PAGAMENTO PENDENTE DE RPP",
    "516;49;PAGAMENTO PENDENTE DE RPNP",
])
TEMPO = _gz("id_tempo;data_iso;dia;mes;ano;data_formatada", [
    "49077;20260305;5;3;2026;2026-03-05", "49097;20260325;25;3;2026;2026-03-25",
    "49468;20260423;23;4;2026;2026-04-23",
])
DM = _gz("id_empenho;ano_exercicio;nr_empenho;dt_empenho;unidade_executora;tipo_empenho;vr_empenho;cd_uni_prog_gasto;uni_prog_gasto", [
    "15263502;2026;881;2026-03-05;1260037 - SEE - SRE/TEOFILO OTONI;ORDINARIO;44.13;;",
    "15264190;2026;881;2026-03-05;1260460 - SUP.DE REDE FISICA;ORDINARIO;938793.55;;",
    "15270000;2026;900;2026-03-10;1260460 - SUP.DE REDE FISICA;ORDINARIO;100.00;;",
    "15270001;2026;900;2026-03-10;1260037 - SEE - SRE/TEOFILO OTONI;ORDINARIO;100.00;;",
])
FT_CAB = ("id_tempo;id_categ_econ;id_grupo;id_elemento;id_item;id_fonte;id_modalidade_aplic;id_funcao;"
          "id_subfuncao;id_programa;id_acao;id_procedencia;id_unidade_orc;id_favorecido;id_empenho;"
          "id_tipo_documento;tp_operacao;cd_documento;cd_evento;dt_anomes;ano_particao;vr_empenhado;"
          "vr_liquidado;vr_pago")


def _ft(id_tempo, id_emp, tipo, op, doc, vp, vl="0.00", ve="0.00"):
    return f"{id_tempo};1;1;1;1;1;1;1;1;1;1;1;4744;1207020;{id_emp};{tipo};{op};{doc};701001;202603;2026;{ve};{vl};{vp}"


FT = _gz(FT_CAB, [
    _ft(49077, 15264190, 1, 2, 881, "0.00", ve="938793.55"),          # o empenho em si
    _ft(49077, 15264190, 510, 2, 875, "0.00", vl="938793.55"),        # liquidacao: nao e OB
    _ft(49097, 15264190, 532, 2, 1939, "938793.55"),                   # a OB de Pequi
    _ft(49468, 15264190, 532, 1, 2000, "-100.00"),                     # um estorno
    _ft(49468, 15264190, 544, 2, 7, "5.00"),                           # folha: fica de fora
    _ft(49097, 99999999, 532, 2, 1, "1.00"),                           # de outro empenho
])
RP_DM = _gz("id_empenho;ano_exercicio;nr_empenho;dt_empenho;dt_original;unidade_executora;tipo_empenho;vr_empenho", [
    "3090411;2026;178;2026-01-09;2017-11-06;1260057 - SUBSECR.DES.EDUC.BAS;INSCRICAO DE RESTO A PAGAR PROCESSADO;641301.79",
])
RP_FT_CAB = ("id_tempo;id_categ_econ;id_grupo;id_elemento;id_item;id_fonte;id_modalidade_aplic;id_unidade_orc;"
             "id_favorecido;id_empenho;id_tipo_documento;ano_origem;cd_evento;tp_operacao;cd_documento;nr_ordem;"
             "dt_documento;ano_particao;vr_nao_processado;vr_processado;vr_pago")
RP_FT = _gz(RP_FT_CAB, [
    "426;1;1;1;1;1;1;4744;1207020;3090411;561;2017;701004;2;195;1;2026-03-05;2026;0.00;247493.40;247493.40",
    "426;1;1;1;1;1;1;4744;1207020;3090411;536;2017;509002;2;5;1;2026-01-14;2026;0.00;0.00;0.00",
])


# --------------------------------------------------------------- pecas puras --
def test_recurso_e_achado_pelo_sufixo_da_url_e_nao_pelo_nome():
    pk = {"result": {"resources": [
        {"name": "Tipo Documento", "url": "https://x/r/a/download/dm_tipo_documento.csv.gz"},
        {"name": "Despesa 2026", "url": "https://x/r/b/download/ft_despesa_2026.csv.gz"}]}}
    assert url_recurso(pk, "/ft_despesa_2026.csv.gz").endswith("/b/download/ft_despesa_2026.csv.gz")
    assert url_recurso(pk, "/ft_despesa_2025.csv.gz") is None and url_recurso({}, "/x") is None


def test_so_OP_e_pagamento_de_RP_sao_ordem_de_pagamento():
    tipos = ler_tipos(TIPOS)
    assert ids_por_regex(tipos, _RE_OP) == {"498", "532", "525", "576"}, "folha e liquidacao ficam de fora"
    assert ids_por_regex(tipos, _RE_RP) == {"488", "561", "505", "516"}


def test_a_data_da_OB_vem_pela_chave_substituta_em_dd_mm_aaaa():
    assert ler_tempo(TEMPO)["49097"] == "25/03/2026"


def test_resolve_a_NE_por_numero_data_e_DESEMPATA_por_valor():
    """A NE 881 de 05/03 existe em DUAS unidades executoras da SEE (medido):
    o valor empenhado decide. E o que faz a juncao ser 95,5% 1:1 sem CNPJ."""
    idx = indexar_empenhos(DM)
    row, m = resolver(idx, "881", date(2026, 3, 5), 938793.55)
    assert m == "casado" and row["id_empenho"] == "15264190"
    assert resolver(idx, "881", date(2026, 3, 5), 1.0) == (None, "ambiguo"), "sem valor que decida, NAO escolhe"
    assert resolver(idx, "900", date(2026, 3, 10), 100.0) == (None, "ambiguo"), "mesmo valor nos dois: ambiguo"
    assert resolver(idx, "777", date(2026, 3, 5), 1.0) == (None, "nao_achou")


def test_extrai_so_as_OBs_do_empenho_alvo_com_data_e_sinal():
    tipos = ler_tipos(TIPOS)
    obs = extrair_obs(FT, {"15264190"}, ids_por_regex(tipos, _RE_OP), ler_tempo(TEMPO))
    assert list(obs) == ["15264190"]
    o = obs["15264190"]
    assert [(x["numero"], x["data"], x["valor"]) for x in o] == [("1939", "25/03/2026", 938793.55),
                                                                  ("2000", "23/04/2026", -100.0)]
    assert o[0]["situacao"] == SIT_OB and o[1]["situacao"] == SIT_OB_ESTORNO
    assert o[0]["id_favorecido"] == "1207020"


def test_restos_a_pagar_resolvem_pela_data_ORIGINAL_e_a_OB_usa_dt_documento():
    idx = indexar_empenhos(RP_DM, "dt_original")
    row, m = resolver(idx, "178", date(2017, 11, 6), None)
    assert m == "casado" and row["id_empenho"] == "3090411"
    obs = extrair_obs(RP_FT, {"3090411"}, ids_por_regex(ler_tipos(TIPOS), _RE_RP), None)
    assert [(x["numero"], x["data"], x["valor"]) for x in obs["3090411"]] == [("195", "05/03/2026", 247493.4)]


# ------------------------------------------------------- o bloco e o RM --
def test_o_bloco_e_ops_obs_marcado_com_a_fonte_e_o_estorno_abate():
    b = montar_bloco([{"data": "23/04/2026", "numero": "2000", "situacao": SIT_OB_ESTORNO, "valor": -100.0},
                      {"data": "25/03/2026", "numero": "1939", "situacao": SIT_OB, "valor": 938793.55}])
    assert b["_fonte"] == "cge_despesa_ob"
    assert b["valor_desembolsado"] == 938693.55 and b["tem_situacao_desconhecida"] is False
    assert [o["numero_ob"] for o in b["obs"]] == ["1939", "2000"], "ordenado por data"


def test_o_vocabulario_de_confirmacao_reconhece_a_OB_emitida_e_nada_mais_mudou():
    assert pagamento_confirmado(SIT_OB) is True
    assert pagamento_confirmado(SIT_OB_ESTORNO) is True, "confirmado e negativo: abate o total"
    assert pagamento_confirmado("Acatada pelo banco") is True
    assert pagamento_confirmado("Devolvida pelo banco") is False
    assert pagamento_confirmado("Pendente de transmissão aos bancos") is None


def test_o_RM_le_o_bloco_como_desembolso_medido_com_data_e_OB():
    """`_mg_pagamentos` -> `_desembolso_ops_obs`: e o caminho que o item estadual
    e o export ja usam; nao ha parser novo."""
    b = montar_bloco([{"data": "25/03/2026", "numero": "1939", "situacao": SIT_OB, "valor": 938793.55}])
    mg = _mg_pagamentos([b])
    assert mg["_consultado"] is True and mg["_incerto"] is False
    assert mg["valor_desembolsado"] == 938793.55 and mg["data_ultimo_desembolso"] == "25/03/2026"
    des = _desembolso_ops_obs(mg)
    assert des["desembolsos"][0]["numero_ob"] == "1939" and des["desembolsos"][0]["data"] == "25/03/2026"
    assert SIT_OB in des["desembolsos"][0]["situacao"]


# --------------------------------------------------------------- o escopo --
def test_anos_alvo_janela_normal_e_backfill_na_primeira_rodada():
    nes = [{"tipo": "pg", "ano_arquivo": 2024, "dt_empenho": date(2024, 5, 1)},
           {"tipo": "pg", "ano_arquivo": 2026, "dt_empenho": date(2026, 3, 5)},
           {"tipo": "rp", "ano_arquivo": 2026, "dt_empenho": date(2017, 11, 6)}]
    hoje = date(2026, 9, 15)
    assert anos_alvo(nes, {2026}, hoje) == ({2026}, {2026}), "rodada normal: so a janela"
    assert anos_alvo(nes, set(), hoje) == ({2024, 2026, 2017}, {2026}), "primeira rodada: tudo, inclusive a NE de origem do RP"
    assert anos_alvo(nes, {2026}, hoje, backfill=True) == ({2024, 2026, 2017}, {2026})


# --------------------------------------------------------------- o upsert --
def test_o_bloco_do_joomla_VENCE_e_o_nosso_e_recarregado():
    """So se sobrescreve `pagamentos` que e nosso (`_fonte`) ou nulo: o bloco do
    portal tem a situacao bancaria e nao pode ser apagado por recarga diaria."""
    up = _SQL_UPSERT[_SQL_UPSERT.index("DO UPDATE SET"):]
    assert "pagamentos->>'_fonte' = %(fonte)s" in up
    assert "THEN EXCLUDED.pagamentos ELSE transparencia_mg_empenhos.pagamentos END" in up
    assert "convenio_id    = COALESCE(transparencia_mg_empenhos.convenio_id, EXCLUDED.convenio_id)" in up
    assert "'segov_ne'" in _SQL_UPSERT and "'casado'" in _SQL_UPSERT
    assert "historico" not in up, "o historico e do Joomla; nunca se toca nele"


def test_status_honesto():
    assert st.cge_despesa_ob(6, 6, 30, 28) == ("success", None)
    assert st.cge_despesa_ob(6, 6, 0, 0) == ("success", None), "sem NE nossa: nada a resolver"
    assert st.cge_despesa_ob(0, 0, 30, 0)[0] == "error"
    assert st.cge_despesa_ob(0, 6, 30, 0)[0] == "error"
    s, m = st.cge_despesa_ob(6, 6, 30, 0)
    assert s == "partial" and "0 resolveram" in m
    assert st.cge_despesa_ob(5, 6, 30, 28)[0] == "partial"


# --------------------------------------------------------------- o ingest --
class _Cur:
    def __init__(self, count_mg=1, nes=None, ja=()):
        self.count_mg, self.nes, self.ja = count_mg, nes or [], list(ja)
        self.execucoes, self._fetch, self._rows = [], None, []

    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))
        if "SELECT count(*)" in sql:
            self._fetch = (self.count_mg,)
        elif "EXTRACT(EPOCH" in sql:
            self._fetch = (None,)
        elif "FROM segov_convenios_empenhos" in sql:
            self._rows = self.nes
        elif "DISTINCT ano_exercicio" in sql:
            self._rows = [(a,) for a in self.ja]

    def fetchone(self):
        return self._fetch

    def fetchall(self):
        return self._rows

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
    import ingestion.cge_despesa_ob as m
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://u:p@localhost/d")
    for k in ("CGE_OB_FORCE", "CGE_OB_ENABLED", "CGE_OB_BACKFILL"):
        monkeypatch.delenv(k, raising=False)
    conn = _Conn(cur)
    monkeypatch.setattr(m.psycopg2, "connect", lambda url: conn)
    despesa = {"result": {"resources": [
        {"url": "https://x/dm_tipo_documento.csv.gz"}, {"url": "https://x/dm_tempo_diario.csv.gz"},
        {"url": "https://x/dm_empenho_desp_2026.csv.gz"}, {"url": "https://x/ft_despesa_2026.csv.gz"},
        {"url": "https://x/dm_empenho_desp_2017.csv.gz"}, {"url": "https://x/ft_despesa_2017.csv.gz"}]}}
    restos = {"result": {"resources": [
        {"url": "https://x/dm_empenho_resto_2026.csv.gz"}, {"url": "https://x/ft_restos_pagar_2026.csv.gz"}]}}
    arquivos = {"dm_tipo_documento.csv.gz": TIPOS, "dm_tempo_diario.csv.gz": TEMPO,
                "dm_empenho_desp_2026.csv.gz": DM, "ft_despesa_2026.csv.gz": FT,
                "dm_empenho_desp_2017.csv.gz": _gz("id_empenho;ano_exercicio;nr_empenho;dt_empenho;unidade_executora;tipo_empenho;vr_empenho;cd_uni_prog_gasto;uni_prog_gasto",
                                                   ["7000178;2017;178;2017-11-06;1260057 - SUBSECR;ORDINARIO;641301.79;;"]),
                "ft_despesa_2017.csv.gz": _gz(FT_CAB, []),
                "dm_empenho_resto_2026.csv.gz": RP_DM, "ft_restos_pagar_2026.csv.gz": RP_FT}

    def _baixar(url):
        if url == m.PKG_DESPESA:
            return json.dumps(despesa).encode()
        if url == m.PKG_RESTOS:
            return json.dumps(restos).encode()
        return arquivos[url.rsplit("/", 1)[-1]]
    monkeypatch.setattr(m, "_baixar", _baixar)
    return m.ingest(), conn


def _upserts(cur):
    return [p for s, p in cur.execucoes if "INSERT INTO transparencia_mg_empenhos" in s]


def _log(conn):
    for sql, params in reversed(conn.cur.execucoes):
        if "ingestion_log" in sql:
            return params
    return None


# (id, municipio_id, convenio_id, nr_siafi, ano_arquivo, tipo, numero_empenho, dt_empenho, vr_empenhado, vr_liquidado, credor_doc)
_NE_PG = (1, 7, 41, "9492993", 2026, "pg", "881", date(2026, 3, 5), 938793.55, 938793.55, "18.313.874/0001-64")
_NE_RP = (2, 7, 42, "9041311", 2026, "rp", "178", date(2017, 11, 6), None, 0.0, "18.715.466/0001-39")


def test_ingest_grava_a_OB_de_pequi_no_id_do_portal_e_loga_success(monkeypatch):
    cur = _Cur(nes=[_NE_PG])
    n, conn = _roda(monkeypatch, cur)
    ups = _upserts(cur)
    assert n == 1 and len(ups) == 1
    u = ups[0]
    assert u["id_empenho"] == 15264190 and u["convenio_id"] == 41 and u["municipio_id"] == 7
    assert u["cnpj_favorecido"] == "18313874000164" and u["convenio_ref"] == "9492993"
    assert u["nr_empenho"] == "881" and u["ano_exercicio"] == 2026 and u["vr_empenho"] == 938793.55
    bloco = json.loads(u["pagamentos"])
    assert bloco["_fonte"] == "cge_despesa_ob" and bloco["valor_desembolsado"] == 938693.55
    assert [o["numero_ob"] for o in bloco["obs"]] == ["1939", "2000"]
    assert u["vr_pago"] == 938693.55
    assert _log(conn) == ("cge_despesa_ob", "success", 1, None)


def test_restos_a_pagar_pendura_a_OB_na_NE_de_origem_de_2017(monkeypatch):
    """Primeira rodada (tabela sem bloco nosso): a NE de origem do RP e
    resolvida no dm_empenho_desp_2017 e a OB 195 fica no id do `despesa`."""
    cur = _Cur(nes=[_NE_RP])
    n, conn = _roda(monkeypatch, cur)
    ups = _upserts(cur)
    assert n == 1 and ups[0]["id_empenho"] == 7000178 and ups[0]["convenio_id"] == 42
    bloco = json.loads(ups[0]["pagamentos"])
    assert [(o["numero_ob"], o["data_emissao_ob"], o["valor"]) for o in bloco["obs"]] == [("195", "05/03/2026", 247493.4)]


def test_sem_NE_da_segov_nao_baixa_dump_grande_e_loga_success(monkeypatch):
    n, conn = _roda(monkeypatch, _Cur(nes=[]))
    assert n == 0 and not _upserts(conn.cur)
    baixados = [s for s, _ in conn.cur.execucoes]
    assert _log(conn)[1] == "success"


def test_tenant_sem_MG_sai_antes(monkeypatch):
    n, conn = _roda(monkeypatch, _Cur(count_mg=0, nes=[_NE_PG]))
    assert n == 0 and _log(conn) is None


def test_NE_que_nao_resolve_vira_partial(monkeypatch):
    ne = (1, 7, 41, "9492993", 2026, "pg", "881", date(2026, 3, 5), 1.0, 1.0, "18.313.874/0001-64")  # valor nao desempata
    n, conn = _roda(monkeypatch, _Cur(nes=[ne]))
    assert n == 0 and _log(conn)[1] == "partial" and "0 resolveram" in _log(conn)[3]


def test_o_cron_chama_a_cge_DEPOIS_da_segov():
    for nome in ("run_sigcon_cron.py", "run_queue_sigcon.py"):
        src = open(os.path.join(RAIZ, "ingestion", nome), encoding="utf-8").read()
        assert src.index("segov_pagamentos import ingest") < src.index("cge_despesa_ob import ingest"), nome
