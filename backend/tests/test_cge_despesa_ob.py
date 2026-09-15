"""Data e nº da OB dos convenios estaduais pelos dumps da CGE (Fase 2, 15/09/2026).

Fixtures com os CABECALHOS REAIS de dados.mg.gov.br (lidos em 15/09/2026):
ft_despesa_2026 (24 colunas), dm_empenho_desp_2026, dm_tempo_diario,
dm_tipo_documento, dm_favorecido, ft_restos_pagar_2026 (21 colunas) e
dm_empenho_resto_2026. Os numeros sao os de Pequi: NE 881 de 05/03/2026,
id_empenho 15264190, OB 1939 de 25/03/2026 R$ 938.793,55 — a mesma linha que o
coletor Joomla mediu (transparencia_mg.py:351) — e o caso que a revisao
adversarial pegou: a NE 981 de 13/05/2026 de PM Catugi (R$ 801 mil) tinha UM
candidato por (nr, data), e era a NE 981 de uma pessoa fisica (R$ 35,70).
"""
import gzip
import json
import os
from datetime import date

from ingestion import status_coleta as st
from ingestion.cge_despesa_ob import (_RE_EMP, _RE_OP, _RE_RP, _SQL_UPSERT, SIT_OB, SIT_OB_ESTORNO,
                                      anos_alvo, candidatos, escolher, escolher_rp, ids_por_regex,
                                      indexar_empenhos, ler_favorecidos, ler_tempo, ler_tipos,
                                      montar_bloco, obs_do_bloco, origem_da_rp, url_recurso,
                                      varrer_ft)
from ingestion.transparencia_mg import montar_pagamentos, pagamento_confirmado
from services.rm_builder import _desembolso_ops_obs, _mg_pagamentos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gz(cab: str, linhas: list[str]) -> bytes:
    return gzip.compress(("﻿" + cab + "\n" + "\n".join(linhas) + "\n").encode("utf-8"))


TIPOS = _gz("id_tipo_documento;cd_tipo_documento;nome", [
    "1;0;EMPENHO", "558;1;REFORCO", "559;2;ANULACAO",
    "498;5;OP PAGA", "532;6;OP PENDENTE", "525;51;OP PAGA SEM DOCUMENTO DE ORIGEM",
    "576;52;OP PENDENTE SEM DOCUMENTO DE ORIGEM", "544;78;OP PAGAMENTO DOCUMENTO FOLHA",
    "510;3;LIQUIDACAO - BRUTO", "488;19;PAGAMENTO RESTO A PAGAR NAO PROCESSADO",
    "561;20;PAGAMENTO RESTO A PAGAR PROCESSADO", "505;50;PAGAMENTO PENDENTE DE RPP",
    "516;49;PAGAMENTO PENDENTE DE RPNP",
])
TEMPO = _gz("id_tempo;data_iso;dia;mes;ano;data_formatada", [
    "49077;20260305;5;3;2026;2026-03-05", "49097;20260325;25;3;2026;2026-03-25",
    "49468;20260423;23;4;2026;2026-04-23", "49500;20260513;13;5;2026;2026-05-13",
    "49501;20260514;14;5;2026;2026-05-14",
])
DM_CAB = "id_empenho;ano_exercicio;nr_empenho;dt_empenho;unidade_executora;tipo_empenho;vr_empenho;cd_uni_prog_gasto;uni_prog_gasto"
DM = _gz(DM_CAB, [
    "15263502;2026;881;2026-03-05;1260037 - SEE - SRE/TEOFILO OTONI;ORDINARIO;44.13;;",
    "15264190;2026;881;2026-03-05;1260460 - SUP.DE REDE FISICA;ORDINARIO;938793.55;;",
    "15270000;2026;900;2026-03-10;1260460 - SUP.DE REDE FISICA;ORDINARIO;100.00;;",
    "15270001;2026;900;2026-03-10;1260037 - SEE - SRE/TEOFILO OTONI;ORDINARIO;100.00;;",
    # a armadilha: UM candidato por (nr, data), e e de OUTRO favorecido
    "15406800;2026;981;2026-05-13;1260018 - SEE - SRE/JUIZ DE FORA;ORDINARIO;35.70;;",
    # empenho ESTIMADO com reforco: vr_empenho do dm (55.124,89) != SEGOV (110.249,79)
    "15300000;2026;500;2026-04-01;1260460 - SUP.DE REDE FISICA;ESTIMATIVO;55124.89;;",
])
FT_CAB = ("id_tempo;id_categ_econ;id_grupo;id_elemento;id_item;id_fonte;id_modalidade_aplic;id_funcao;"
          "id_subfuncao;id_programa;id_acao;id_procedencia;id_unidade_orc;id_favorecido;id_empenho;"
          "id_tipo_documento;tp_operacao;cd_documento;cd_evento;dt_anomes;ano_particao;vr_empenhado;"
          "vr_liquidado;vr_pago")


def _ft(id_tempo, id_emp, tipo, op, doc, vp, vl="0.00", ve="0.00", fav="1207020"):
    return f"{id_tempo};1;1;1;1;1;1;1;1;1;1;1;4744;{fav};{id_emp};{tipo};{op};{doc};701001;202603;2026;{ve};{vl};{vp}"


FT = _gz(FT_CAB, [
    _ft(49077, 15264190, 1, 2, 881, "0.00", ve="938793.55"),          # o empenho em si
    _ft(49077, 15264190, 510, 2, 875, "0.00", vl="938793.55"),        # liquidacao: nao e OB
    _ft(49097, 15264190, 532, 2, 1939, "938793.55"),                   # a OB de Pequi
    _ft(49468, 15264190, 532, 1, 2000, "-100.00"),                     # um estorno
    _ft(49468, 15264190, 544, 2, 7, "5.00"),                           # folha: fica de fora
    _ft(49077, 15263502, 1, 2, 881, "0.00", ve="44.13", fav="1374490"),  # a outra NE 881 (SRE)
    _ft(49500, 15406800, 1, 2, 981, "0.00", ve="35.70", fav="1374490"),  # a NE 981 da pessoa fisica
    _ft(49501, 15406800, 532, 2, 1674, "35.70", fav="1374490"),
    _ft(49077, 15300000, 1, 2, 500, "0.00", ve="55124.89"),            # estimado + reforco = 110.249,79
    _ft(49097, 15300000, 558, 2, 600, "0.00", ve="55124.90"),
    _ft(49097, 15300000, 532, 2, 700, "55124.90"),
    _ft(49097, 99999999, 532, 2, 1, "1.00"),                           # de outro empenho
])
FAV = _gz("id_favorecido;tp_documento;nr_documento_anonimizado;nome_anonimizado", [
    "1207020;2;18313874000164;PM PEQUI",
    "1374490;1;***.456.789-**;VIVIANI F.",          # pessoa fisica, anonimizada
    "1482490;2;26218636000106;PM CATUGI",
])
RP_DM_CAB = "id_empenho;ano_exercicio;nr_empenho;dt_empenho;dt_original;unidade_executora;tipo_empenho;vr_empenho"
RP_DM = _gz(RP_DM_CAB, [
    "3090411;2026;178;2026-01-09;2017-11-06;1260057 - SUBSECR.DES.EDUC.BAS;INSCRICAO DE RESTO A PAGAR PROCESSADO;641301.79",
    "3090412;2026;178;2026-01-09;2017-11-06;1260018 - SEE - SRE/JUIZ DE FORA;INSCRICAO DE RESTO A PAGAR PROCESSADO;10.00",
])
RP_FT_CAB = ("id_tempo;id_categ_econ;id_grupo;id_elemento;id_item;id_fonte;id_modalidade_aplic;id_unidade_orc;"
             "id_favorecido;id_empenho;id_tipo_documento;ano_origem;cd_evento;tp_operacao;cd_documento;nr_ordem;"
             "dt_documento;ano_particao;vr_nao_processado;vr_processado;vr_pago")
RP_FT = _gz(RP_FT_CAB, [
    "426;1;1;1;1;1;1;4744;1207020;3090411;561;2017;701004;2;195;1;2026-03-05;2026;0.00;247493.40;247493.40",
    "426;1;1;1;1;1;1;4744;1207020;3090411;536;2017;509002;2;5;1;2026-01-14;2026;0.00;0.00;0.00",
    "426;1;1;1;1;1;1;4744;1374490;3090412;561;2017;701004;2;9;1;2026-03-05;2026;0.00;10.00;10.00",
])
DM_2017 = _gz(DM_CAB, [
    "7000178;2017;178;2017-11-06;1260057 - SUBSECR.DES.EDUC.BAS;ORDINARIO;641301.79;;",
    "7000179;2017;178;2017-11-06;1260018 - SEE - SRE/JUIZ DE FORA;ORDINARIO;10.00;;",
])
PEQUI = "18.313.874/0001-64"
CATUGI = "26.218.636/0001-06"


def _tipos():
    t = ler_tipos(TIPOS)
    return t, ids_por_regex(t, _RE_OP), ids_por_regex(t, _RE_RP), ids_por_regex(t, _RE_EMP)


# --------------------------------------------------------------- pecas puras --
def test_recurso_e_achado_pelo_sufixo_da_url_e_nao_pelo_nome():
    pk = {"result": {"resources": [
        {"name": "Tipo Documento", "url": "https://x/r/a/download/dm_tipo_documento.csv.gz"},
        {"name": "Despesa 2026", "url": "https://x/r/b/download/ft_despesa_2026.csv.gz"}]}}
    assert url_recurso(pk, "/ft_despesa_2026.csv.gz").endswith("/b/download/ft_despesa_2026.csv.gz")
    assert url_recurso(pk, "/ft_despesa_2025.csv.gz") is None and url_recurso({}, "/x") is None


def test_so_OP_e_pagamento_de_RP_sao_ordem_de_pagamento():
    _, ids_op, ids_rp, ids_emp = _tipos()
    assert ids_op == {"498", "532", "525", "576"}, "folha e liquidacao ficam de fora"
    assert ids_rp == {"488", "561", "505", "516"}
    assert ids_emp == {"1", "558", "559"}


def test_a_data_da_OB_vem_pela_chave_substituta_em_dd_mm_aaaa():
    assert ler_tempo(TEMPO)["49097"] == "25/03/2026"


def test_a_varredura_do_ft_traz_favorecido_soma_e_OBs_so_dos_ids_alvo():
    _, ids_op, _, ids_emp = _tipos()
    info = varrer_ft(FT, {"15264190", "15300000"}, ids_op, ids_emp, ler_tempo(TEMPO))
    assert set(info) == {"15264190", "15300000"}
    p = info["15264190"]
    assert p["fav"] == "1207020" and p["soma"] == 938793.55
    assert [(x["numero"], x["data"], x["valor"]) for x in p["obs"]] == [("1939", "25/03/2026", 938793.55),
                                                                         ("2000", "23/04/2026", -100.0)]
    assert p["obs"][0]["situacao"] == SIT_OB and p["obs"][1]["situacao"] == SIT_OB_ESTORNO
    assert info["15300000"]["soma"] == 110249.79, "empenho + reforco"


def test_o_favorecido_decide__a_NE_981_da_pessoa_fisica_NAO_e_a_de_catugi():
    """⚠️ O caso da revisao: um candidato por (nr, data), valor diferente,
    favorecido diferente. Antes: 'casado' e a OB de R$ 35,70 no convenio de
    R$ 801 mil. Agora: 'favorecido_diverge'."""
    _, ids_op, _, ids_emp = _tipos()
    idx = indexar_empenhos(DM)
    info = varrer_ft(FT, {"15406800"}, ids_op, ids_emp, ler_tempo(TEMPO))
    fav = ler_favorecidos(FAV, {"1374490", "1207020"})
    c = candidatos(idx, "981", date(2026, 5, 13))
    assert len(c) == 1 and c[0][0] == "15406800"
    assert escolher(c, 801000.0, CATUGI, info, fav) == (None, "favorecido_diverge")


def test_favorecido_igual_aceita_mesmo_com_valor_diferente__empenho_estimado():
    _, ids_op, _, ids_emp = _tipos()
    idx = indexar_empenhos(DM)
    info = varrer_ft(FT, {"15300000"}, ids_op, ids_emp, ler_tempo(TEMPO))
    fav = ler_favorecidos(FAV, {"1207020"})
    c, m = escolher(candidatos(idx, "500", date(2026, 4, 1)), 110249.79, PEQUI, info, fav)
    assert m == "casado" and c[0] == "15300000"
    # e sem o favorecido (linha sem dm_favorecido), a SOMA do ft decide
    c, m = escolher(candidatos(idx, "500", date(2026, 4, 1)), 110249.79, PEQUI, info, {})
    assert m == "casado" and c[0] == "15300000"


def test_desempate_entre_candidatos_por_favorecido_e_valor__ambiguo_nao_escolhe():
    _, ids_op, _, ids_emp = _tipos()
    idx = indexar_empenhos(DM)
    info = varrer_ft(FT, {"15263502", "15264190", "15270000", "15270001"}, ids_op, ids_emp, ler_tempo(TEMPO))
    fav = ler_favorecidos(FAV, {"1207020", "1374490"})
    c, m = escolher(candidatos(idx, "881", date(2026, 3, 5)), 938793.55, PEQUI, info, fav)
    assert m == "casado" and c[0] == "15264190"
    # mesmo valor nos dois, favorecido desconhecido (sem linha no ft): ambiguo
    assert escolher(candidatos(idx, "900", date(2026, 3, 10)), 100.0, PEQUI, {}, {}) == (None, "ambiguo")
    assert escolher(candidatos(idx, "777", date(2026, 3, 5)), 1.0, PEQUI, info, fav) == (None, "nao_achou")
    # favorecido desconhecido e valor diferente: nao aceita
    assert escolher(candidatos(idx, "981", date(2026, 5, 13)), 801000.0, CATUGI, {}, {}) == (None, "nao_casou")


def test_restos_a_pagar_resolvem_pelo_favorecido_e_a_origem_pela_unidade_executora():
    _, _, ids_rp, _ = _tipos()
    idx_rp = indexar_empenhos(RP_DM, "dt_original")
    cands = candidatos(idx_rp, "178", date(2017, 11, 6))
    assert len(cands) == 2, "dois RP com o mesmo (nr, dt_original) em UEs diferentes"
    info_rp = varrer_ft(RP_FT, {c[0] for c in cands}, ids_rp, set(), None)
    fav = ler_favorecidos(FAV, {"1207020", "1374490"})
    c, m = escolher_rp(cands, PEQUI, info_rp, fav)
    assert m == "casado" and c[0] == "3090411" and c[2].startswith("1260057")
    assert [(x["numero"], x["data"], x["valor"]) for x in info_rp["3090411"]["obs"]] == [("195", "05/03/2026", 247493.4)]
    # a NE de origem: (nr, dt_original) tem dois candidatos em 2017; a UE fecha
    o, m2 = origem_da_rp(candidatos(indexar_empenhos(DM_2017), "178", date(2017, 11, 6)), c[2])
    assert m2 == "casado" and o[0] == "7000178"
    assert origem_da_rp([], "x") == (None, "nao_achou")


# ------------------------------------------------------- o bloco e o RM --
def test_o_bloco_e_ops_obs_marcado_com_a_fonte_o_estorno_abate_e_nao_repete_OB():
    obs = [{"data": "23/04/2026", "numero": "2000", "situacao": SIT_OB_ESTORNO, "valor": -100.0},
           {"data": "25/03/2026", "numero": "1939", "situacao": SIT_OB, "valor": 938793.55}]
    b = montar_bloco(obs + obs[1:])   # a OB 1939 repetida (bloco antigo + varredura nova)
    assert b["_fonte"] == "cge_despesa_ob"
    assert b["valor_desembolsado"] == 938693.55 and b["tem_situacao_desconhecida"] is False
    assert [o["numero_ob"] for o in b["obs"]] == ["1939", "2000"], "ordenado por data, sem repetir"
    assert obs_do_bloco(json.dumps(b)) == [{"data": "25/03/2026", "numero": "1939", "situacao": SIT_OB, "valor": 938793.55},
                                           {"data": "23/04/2026", "numero": "2000", "situacao": SIT_OB_ESTORNO, "valor": -100.0}]


def test_o_estorno_por_ultimo_nao_vira_data_do_ultimo_desembolso():
    b = montar_pagamentos([{"data": "29/06/2026", "numero": "2021", "situacao": SIT_OB, "valor": 453098.31},
                           {"data": "30/06/2026", "numero": "2021", "situacao": SIT_OB_ESTORNO, "valor": -453098.31}])
    assert b["valor_desembolsado"] == 0.0 and b["data_ultimo_desembolso"] == "29/06/2026"


def test_o_vocabulario_de_confirmacao_reconhece_a_OB_emitida_e_nada_mais_mudou():
    assert pagamento_confirmado(SIT_OB) is True
    assert pagamento_confirmado(SIT_OB_ESTORNO) is True, "confirmado e negativo: abate o total"
    assert pagamento_confirmado("Acatada pelo banco") is True
    assert pagamento_confirmado("Devolvida pelo banco") is False
    assert pagamento_confirmado("Pendente de transmissão aos bancos") is None
    assert len(SIT_OB) <= 50, "cabe numa linha da caixa do PDF (12 OBs = 12 linhas)"


def test_o_RM_le_o_bloco_como_desembolso_medido_com_data_e_OB():
    b = montar_bloco([{"data": "25/03/2026", "numero": "1939", "situacao": SIT_OB, "valor": 938793.55}])
    mg = _mg_pagamentos([b])
    assert mg["_consultado"] is True and mg["_incerto"] is False
    assert mg["valor_desembolsado"] == 938793.55 and mg["data_ultimo_desembolso"] == "25/03/2026"
    des = _desembolso_ops_obs(mg)
    assert des["desembolsos"][0]["numero_ob"] == "1939" and des["desembolsos"][0]["data"] == "25/03/2026"


# --------------------------------------------------------------- o escopo --
def test_anos_alvo__janela_no_ft_mas_a_origem_do_RP_sempre_na_dimensao():
    nes = [{"tipo": "pg", "ano_arquivo": 2024, "dt_empenho": date(2024, 5, 1)},
           {"tipo": "pg", "ano_arquivo": 2026, "dt_empenho": date(2026, 3, 5)},
           {"tipo": "rp", "ano_arquivo": 2026, "dt_empenho": date(2017, 11, 6)},
           {"tipo": "rp", "ano_arquivo": 2023, "dt_empenho": date(2021, 1, 1)}]
    hoje = date(2026, 9, 15)
    assert anos_alvo(nes, True, hoje) == ({2026}, {2026}, {2026, 2017}), \
        "rodada normal: ft e RP so na janela; a NE de ORIGEM do RP de 2017 entra na dimensao"
    assert anos_alvo(nes, False, hoje) == ({2024, 2026}, {2026, 2023}, {2024, 2026, 2017, 2021})
    assert anos_alvo(nes, True, hoje, backfill=True) == ({2024, 2026}, {2026, 2023}, {2024, 2026, 2017, 2021})


# --------------------------------------------------------------- o upsert --
def test_o_bloco_do_joomla_VENCE_e_o_carimbo_de_leitura_nao_e_tocado():
    up = _SQL_UPSERT[_SQL_UPSERT.index("DO UPDATE SET"):]
    assert "pagamentos->>'_fonte' = %(fonte)s" in up
    assert "THEN EXCLUDED.pagamentos ELSE transparencia_mg_empenhos.pagamentos END" in up
    assert "convenio_id    = COALESCE(transparencia_mg_empenhos.convenio_id, EXCLUDED.convenio_id)" in up
    assert "detalhe_lido_em   = transparencia_mg_empenhos.detalhe_lido_em" in up, \
        "linha do Joomla ainda nao lida tem de continuar na fila dele"
    assert "'segov_ne'" in _SQL_UPSERT and "'casado'" in _SQL_UPSERT
    assert "historico" not in up, "o historico e do Joomla; nunca se toca nele"


def test_status_honesto():
    assert st.cge_despesa_ob(6, 6, 30, 28) == ("success", None)
    assert st.cge_despesa_ob(6, 6, 0, 0) == ("success", None), "sem NE nossa: nada a resolver"
    assert st.cge_despesa_ob(6, 6, 30, 28, 10, 9) == ("success", None), "RP ambiguo nao e partial"
    assert st.cge_despesa_ob(0, 0, 30, 0)[0] == "error"
    assert st.cge_despesa_ob(0, 6, 30, 0)[0] == "error"
    s, m = st.cge_despesa_ob(5, 6, 30, 28)
    assert s == "partial" and "ausentes/falharam" in m
    s, m = st.cge_despesa_ob(6, 6, 30, 0)
    assert s == "partial" and "0 resolveram" in m
    assert st.cge_despesa_ob(6, 6, 30, 28, 10, 0)[0] == "partial"


# --------------------------------------------------------------- o ingest --
class _Cur:
    def __init__(self, count_mg=1, nes=None, ja_rodou=False, blocos=None):
        self.count_mg, self.nes, self.ja_rodou = count_mg, nes or [], ja_rodou
        self.blocos = blocos or {}            # id_empenho -> bloco ja gravado (nosso)
        self.execucoes, self._fetch, self._rows = [], None, []

    def execute(self, sql, params=None):
        self.execucoes.append((sql, params))
        if "SELECT count(*) FROM municipios" in sql:
            self._fetch = (self.count_mg,)
        elif "SELECT count(*) FROM ingestion_log" in sql:
            self._fetch = (1 if self.ja_rodou else 0,)
        elif "EXTRACT(EPOCH" in sql:
            self._fetch = (None,)
        elif "FROM segov_convenios_empenhos" in sql:
            self._rows = self.nes
        elif "SELECT id_empenho, pagamentos FROM transparencia_mg_empenhos" in sql:
            self._rows = [(i, json.dumps(b)) for i, b in self.blocos.items() if i in params[0]]

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


ARQUIVOS = {"dm_tipo_documento.csv.gz": TIPOS, "dm_tempo_diario.csv.gz": TEMPO,
            "dm_favorecido.csv.gz": FAV,
            "dm_empenho_desp_2026.csv.gz": DM, "ft_despesa_2026.csv.gz": FT,
            "dm_empenho_desp_2017.csv.gz": DM_2017, "ft_despesa_2017.csv.gz": _gz(FT_CAB, []),
            "dm_empenho_resto_2026.csv.gz": RP_DM, "ft_restos_pagar_2026.csv.gz": RP_FT}


def _roda(monkeypatch, cur, sem=()):
    """Roda ingest() com downloads falsos; `sem` = sufixos de recurso a omitir do CKAN."""
    import ingestion.cge_despesa_ob as m
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://u:p@localhost/d")
    for k in ("CGE_OB_FORCE", "CGE_OB_ENABLED", "CGE_OB_BACKFILL"):
        monkeypatch.delenv(k, raising=False)
    conn = _Conn(cur)
    monkeypatch.setattr(m.psycopg2, "connect", lambda url: conn)
    nomes = [n for n in ARQUIVOS if not any(n.endswith(s.lstrip("/")) for s in sem)]
    despesa = {"result": {"resources": [{"url": f"https://x/{n}"} for n in nomes if "resto" not in n]}}
    restos = {"result": {"resources": [{"url": f"https://x/{n}"} for n in nomes if "resto" in n]}}
    baixados = []

    def _baixar(url):
        if url == m.PKG_DESPESA:
            return json.dumps(despesa).encode()
        if url == m.PKG_RESTOS:
            return json.dumps(restos).encode()
        nome = url.rsplit("/", 1)[-1]
        baixados.append(nome)
        return ARQUIVOS[nome]
    monkeypatch.setattr(m, "_baixar", _baixar)
    return m.ingest(), conn, baixados


def _upserts(cur):
    return [p for s, p in cur.execucoes if "INSERT INTO transparencia_mg_empenhos" in s]


def _log(conn):
    for sql, params in reversed(conn.cur.execucoes):
        if "ingestion_log" in sql and "INSERT" in sql:
            return params
    return None


# (id, municipio_id, convenio_id, nr_siafi, ano_arquivo, tipo, numero_empenho, dt_empenho, vr_empenhado, vr_liquidado, credor_doc)
NE_PEQUI = (1, 7, 41, "9492993", 2026, "pg", "881", date(2026, 3, 5), 938793.55, 938793.55, PEQUI)
NE_CATUGI = (3, 8, 43, "9501949", 2026, "pg", "981", date(2026, 5, 13), 801000.0, 801000.0, CATUGI)
RP_PEQUI = (2, 7, 42, "9041311", 2026, "rp", "178", date(2017, 11, 6), None, 0.0, PEQUI)


def test_ingest_grava_a_OB_de_pequi_no_id_do_portal_e_rejeita_a_NE_errada_de_catugi(monkeypatch):
    cur = _Cur(nes=[NE_PEQUI, NE_CATUGI])
    n, conn, _ = _roda(monkeypatch, cur)
    ups = _upserts(cur)
    assert n == 1 and [u["id_empenho"] for u in ups] == [15264190], "a NE 981 de outro favorecido NAO entra"
    u = ups[0]
    assert u["convenio_id"] == 41 and u["municipio_id"] == 7 and u["cnpj_favorecido"] == "18313874000164"
    assert u["convenio_ref"] == "9492993" and u["nr_empenho"] == "881" and u["ano_exercicio"] == 2026
    assert u["vr_empenho"] == 938793.55 and u["id_favorecido"] == "1207020"
    bloco = json.loads(u["pagamentos"])
    assert bloco["_fonte"] == "cge_despesa_ob" and bloco["valor_desembolsado"] == 938693.55
    assert [o["numero_ob"] for o in bloco["obs"]] == ["1939", "2000"] and u["vr_pago"] == 938693.55
    assert _log(conn) == ("cge_despesa_ob", "success", 1, None), "NE rejeitada por favorecido nao e falha da rodada"


def test_restos_a_pagar_pendura_a_OB_na_NE_de_origem_de_2017__rodada_NORMAL(monkeypatch):
    """A rodada de todo dia (ja_rodou=True): o ft de 2017 NAO e baixado, mas a
    dimensao de 2017 e — e a OB 195 vai para o id 7000178 do `despesa`. Era o
    RP que sumia depois da primeira rodada."""
    cur = _Cur(nes=[RP_PEQUI], ja_rodou=True)
    n, conn, baixados = _roda(monkeypatch, cur)
    ups = _upserts(cur)
    assert n == 1 and ups[0]["id_empenho"] == 7000178 and ups[0]["convenio_id"] == 42
    bloco = json.loads(ups[0]["pagamentos"])
    assert [(o["numero_ob"], o["data_emissao_ob"], o["valor"]) for o in bloco["obs"]] == [("195", "05/03/2026", 247493.4)]
    assert "dm_empenho_desp_2017.csv.gz" in baixados and "ft_despesa_2017.csv.gz" not in baixados
    assert _log(conn)[1] == "success"


def test_a_ordem_das_linhas_nao_muda_o_resultado__pg_e_rp_da_mesma_NE(monkeypatch):
    """A mesma NE em pg{ano} e rp{ano+1} resolve para o mesmo id do `despesa`:
    as OBs do exercicio E as do RP ficam no mesmo bloco, venha a linha rp antes
    ou depois no SELECT."""
    rp_881 = (5, 7, 41, "9492993", 2026, "rp", "881", date(2026, 3, 5), None, 0.0, PEQUI)
    rp_dm = _gz(RP_DM_CAB, ["3099999;2026;881;2026-01-09;2026-03-05;1260460 - SUP.DE REDE FISICA;INSCRICAO;1.00"])
    rp_ft = _gz(RP_FT_CAB, ["426;1;1;1;1;1;1;4744;1207020;3099999;561;2026;701004;2;300;1;2026-06-01;2026;0.00;1.00;1.00"])
    monkeypatch.setitem(ARQUIVOS, "dm_empenho_resto_2026.csv.gz", rp_dm)
    monkeypatch.setitem(ARQUIVOS, "ft_restos_pagar_2026.csv.gz", rp_ft)
    resultados = []
    for nes in ([NE_PEQUI, rp_881], [rp_881, NE_PEQUI]):
        cur = _Cur(nes=nes)
        _roda(monkeypatch, cur)
        ups = _upserts(cur)
        resultados.append((len(ups), ups[0]["id_empenho"], sorted(o["numero_ob"] for o in json.loads(ups[0]["pagamentos"])["obs"])))
    assert resultados[0] == resultados[1] == (1, 15264190, ["1939", "2000", "300"])


def test_exercicio_nao_re_varrido_preserva_as_OBs_ja_gravadas(monkeypatch):
    """Rodada normal, RP de NE de 2017: o ft de 2017 nao e lido, entao as OBs do
    exercicio que a primeira rodada gravou vem do bloco existente e se juntam
    as de RP — em vez de o upsert sobrescrever com um bloco so de RP."""
    antigo = montar_bloco([{"data": "20/11/2017", "numero": "44", "situacao": SIT_OB, "valor": 641301.79}])
    cur = _Cur(nes=[RP_PEQUI], ja_rodou=True, blocos={7000178: antigo})
    n, conn, _ = _roda(monkeypatch, cur)
    bloco = json.loads(_upserts(cur)[0]["pagamentos"])
    assert [o["numero_ob"] for o in bloco["obs"]] == ["44", "195"]
    assert bloco["valor_desembolsado"] == 888795.19   # 641.301,79 + 247.493,40, arredondado no bloco


def test_sem_NE_da_segov_nao_baixa_dump_grande_e_loga_success(monkeypatch):
    n, conn, baixados = _roda(monkeypatch, _Cur(nes=[]))
    assert n == 0 and not _upserts(conn.cur)
    assert not [b for b in baixados if b.startswith("ft_") or b.startswith("dm_empenho")]
    assert _log(conn)[1] == "success"


def test_tenant_sem_MG_sai_antes(monkeypatch):
    n, conn, _ = _roda(monkeypatch, _Cur(count_mg=0, nes=[NE_PEQUI]))
    assert n == 0 and _log(conn) is None


def test_recurso_ausente_no_ckan_nao_vira_success(monkeypatch):
    n, conn, _ = _roda(monkeypatch, _Cur(nes=[NE_PEQUI]), sem=("/dm_tipo_documento.csv.gz",))
    assert n == 0 and _log(conn)[1] == "error"
    n2, conn2, _ = _roda(monkeypatch, _Cur(nes=[NE_PEQUI]), sem=("/dm_favorecido.csv.gz",))
    assert _log(conn2)[1] == "partial" and "ausentes" in _log(conn2)[3]


def test_NE_que_nao_resolve_vira_partial(monkeypatch):
    ne = (1, 7, 41, "9492993", 2026, "pg", "777", date(2026, 3, 5), 1.0, 1.0, PEQUI)  # nao existe no dm
    n, conn, _ = _roda(monkeypatch, _Cur(nes=[ne]))
    assert n == 0 and _log(conn)[1] == "partial" and "0 resolveram" in _log(conn)[3]


def test_excecao_no_meio_vira_error_no_log_e_nao_derruba_o_cron(monkeypatch):
    import ingestion.cge_despesa_ob as m
    monkeypatch.setattr(m, "varrer_ft", lambda *a, **k: (_ for _ in ()).throw(EOFError("gzip truncado")))
    n, conn, _ = _roda(monkeypatch, _Cur(nes=[NE_PEQUI]))
    assert n == 0 and conn.rollbacks >= 1
    assert _log(conn)[1] == "error" and "gzip truncado" in _log(conn)[3]


def test_o_cron_chama_a_cge_DEPOIS_da_segov():
    for nome in ("run_sigcon_cron.py", "run_queue_sigcon.py"):
        src = open(os.path.join(RAIZ, "ingestion", nome), encoding="utf-8").read()
        assert src.index("segov_pagamentos import ingest") < src.index("cge_despesa_ob import ingest"), nome
