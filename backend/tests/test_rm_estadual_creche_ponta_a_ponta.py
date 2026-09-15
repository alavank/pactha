"""`montar_conteudo` de ponta a ponta, com banco FALSO — os tres pontos do dono
(15/09/2026) medidos por ENTRADA -> SAIDA, e nao por texto-fonte.

  1. estadual com empenhos da SEGOV: NEs, valor empenhado, "Empenhado: Sim" e
     "Pendente de desembolso" (ha empenho, nada pago, Joomla sem resposta);
  2. "Cadastramento" fora; "CONVENIO CADASTRADO" (instrumento celebrado do
     CKAN) dentro;
  3. a creche 932836/2021: o pago do SIMEC na PROPRIA linha (casado pelo nº do
     processo), o "a desembolsar" do SICONV zerado, o termo NAO repetido — e,
     no recorte "pagas", o termo VOLTA a sair sozinho (a regressao que a
     revisao adversarial pegou: marcar "ja exibido" antes do add_item).

O banco falso roteia cada `db.execute` pela SUBSTRING do SQL (mesmo desenho do
FakeDb de test_gate_consultas.py); o que nao tem rota devolve vazio. `ops_obs`
e `ops_obs_aberto` vazios => `ops_obs_preferido` devolve (None, None) e o
SICONV nao mede desembolso — exatamente o caso da creche em producao.
"""
import asyncio
from datetime import date
from types import SimpleNamespace

from services.rm_builder import montar_conteudo


class _Res:
    """Resultado permissivo: .all()/.fetchall()/.scalars().all()/.scalar_one_or_none()."""

    def __init__(self, rows=None, obj=None):
        self._rows = list(rows or [])
        self._obj = obj

    def all(self):
        return self._rows

    def fetchall(self):
        return self._rows

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._obj

    def scalar(self):
        return self._obj

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchone(self):
        return self.first()

    def __iter__(self):
        return iter(self._rows)


class FakeDb:
    def __init__(self, rotas):
        self.rotas = rotas          # [(substring do SQL, _Res)] — a PRIMEIRA que casar
        self.consultas: list = []

    async def execute(self, stmt, params=None):
        s = str(stmt)
        self.consultas.append(s)
        for sub, res in self.rotas:
            if sub in s:
                return res
        return _Res()


def _conv(id_, nr_sigcon, situacao, ano=2026, valor=0.0, instrumento=True, siafi=None):
    return SimpleNamespace(
        id=id_, municipio_id=1, fonte="SIGCON-MG", situacao=situacao, ano=ano,
        nr_sigcon=nr_sigcon, nr_siafi=siafi, nr_plano_trabalho=None,
        raw_data={"nr_instrumento": nr_sigcon} if instrumento else {},
        dt_vigencia_atual=date(2028, 6, 7), dt_vigencia_final=date(2028, 6, 7),
        orgao_concedente="SEE", objeto="Aquisição de micro-ônibus",
        valor_total=valor, valor_concedente=valor, valor_contrapartida=0.0,
        banco="Banco do Brasil", agencia="3829-6", conta_corrente="18098-X",
        saldo_bancario=None, dt_saldo=None, qt_alteracoes=0,
    )


def _voluntaria_creche():
    """A 059522/2021 -> instrumento 932836, programa SIMEC/PAR4, Termo de
    Compromisso, sem OB no SICONV. 36 colunas, por INDICE (ver o SELECT):
    row[33]/row[34] sao as licitacoes do dump (PR 4), row[35] o processo."""
    r = [None] * 36
    r[0] = 18
    r[1] = "059522/2021"
    r[2] = "932836"
    r[3] = "Proposta/Plano de Trabalho Aprovados"
    r[4] = "26298 - Fundo Nacional de Desenvolvimento da Educacao"
    r[5] = "019-Construir escola ou creche"
    r[6] = "31/12/2099"          # vigencia viva: o teste nao pode envelhecer
    r[7], r[8], r[9] = 3823677.33, 3819853.65, 3823.68
    r[18], r[19], r[20] = "Banco do Brasil S.A.", "3829-6", "155853"
    r[24] = "Programa SIMEC/PAR4"
    r[28] = "Termo de Compromisso"
    r[35] = "23400.002301/2021-01"
    return r


# (processo, nr_documento, tipo_documento, tipo_objeto, dt_vigencia, valor_termo,
#  valor_empenhado, valor_pago, saldo_bancario, prestacao_contas)
_TC_CRECHE = ("23400.002301/2021-01", "202141430-1", "TC - Municípios", "Obra",
              date(2024, 12, 30), 3157096.83, 1875147.32, 572978.05, 0.0, None)
_TC_OUTRO = ("23400.005008/2013-88", "04227/2013", "PAC2 04227/2013", "PAC - Quadras",
             date(2015, 12, 31), 500000.0, 500000.0, 500000.0, 0.0, "Aprovada")


def _termos_13(tc):
    """A linha do bloco dos termos (13 colunas): dt_validacao/periodo/vigencia_txt no meio."""
    return (tc[0], tc[1], tc[2], tc[3], date(2021, 12, 30), "13/03/2024",
            "30/12/2024", tc[4], tc[5], tc[6], tc[7], tc[8], tc[9])


def _db(convenios, segov_rows=(), voluntarias=(), termos=(), mg_rows=()):
    return FakeDb([
        ("FROM municipios", _Res(obj=SimpleNamespace(id=1, nome="Araújos", uf="MG"))),
        # o Joomla da 403 na VPS; o que existe aqui e o bloco da CGE (Fase 2)
        ("FROM transparencia_mg_empenhos", _Res(rows=mg_rows)),
        ("FROM segov_convenios_empenhos", _Res(rows=segov_rows)),
        ("FROM convenios_estadual", _Res(rows=convenios)),
        ("FROM transferegov_propostas", _Res(rows=voluntarias)),
        # ⚠️ ordem: o bloco dos termos (13 colunas) tem `dt_validacao`; o mapa
        # por processo (10 colunas) nao. As duas consultas sao em simec_termos.
        ("dt_validacao", _Res(rows=[_termos_13(t) for t in termos])),
        ("FROM simec_termos", _Res(rows=list(termos))),
    ])


def _itens(conteudo):
    return [it for p in conteudo["partes"] for s in p["secoes"] for g in s["grupos"] for it in g["itens"]]


def _por_numero(conteudo, trecho):
    return [it for it in _itens(conteudo) if trecho in str(it.get("numero") or "")]


def _monta(db, **kw):
    return asyncio.run(montar_conteudo(db, 1, ano_emissao=2026, completo=True, **kw))


# ---------------------------------------------------------------- estadual --
def test_cadastramento_fica_fora_e_o_CONVENIO_CADASTRADO_do_ckan_fica_dentro():
    db = _db([
        _conv(1, "002567/2026", "Cadastramento"),                       # a tela do dono
        _conv(2, "1261002153/2026", "CONVENIO CADASTRADO", valor=519171.0),
        _conv(3, "1261009999/2026", "Em vigor", valor=100.0),
    ])
    c = _monta(db)
    assert not _por_numero(c, "002567/2026"), "Cadastramento entrou no RM"
    assert _por_numero(c, "1261002153/2026"), "instrumento celebrado do CKAN saiu junto"
    assert _por_numero(c, "1261009999/2026")


def test_estadual_com_empenho_da_segov_e_sem_joomla_mostra_NEs_e_pendente_de_desembolso():
    segov = [  # (convenio_id, numero_empenho, dt_empenho, vr_emp, vr_liq, vr_pago, tipo, ano, uo)
        (2, "310", date(2026, 3, 5), 519171.0, 0.0, 0.0, "pg", 2026, "SEE"),
    ]
    db = _db([_conv(2, "1261002153/2026", "Em vigor", valor=519171.0)], segov_rows=segov)
    it = _por_numero(_monta(db), "1261002153/2026")[0]
    assert it["nes"] == "NE 310/2026 — R$ 519.171,00 — empenhado em 05/03/2026 — pago R$ 0,00"
    assert it["valor_empenhado"] == 519171.0 and it["empenhado"] == "Sim"
    assert it["valor_desembolsado"] == 0.0
    assert it["situacao_atual"].endswith("Pendente de desembolso")
    assert "desembolsos" not in it, "o CSV nao tem data: nenhum lancamento fabricado"


def test_estadual_com_OB_da_cge_mostra_data_e_numero_e_complementa_o_atraso_do_dump():
    """Fase 2: o bloco da CGE em transparencia_mg_empenhos da a data e o nº da OB;
    o marcador vira "Desembolsado". E quando a SEGOV (mais fresca) diz pago
    mais que as OBs publicadas, a diferenca entra como linha propria."""
    from ingestion.cge_despesa_ob import SIT_OB, montar_bloco
    bloco = montar_bloco([{"data": "14/05/2026", "numero": "1674", "situacao": SIT_OB, "valor": 35.7}])
    segov = [(2, "981", date(2026, 5, 10), 801000.0, 801000.0, 801000.0, "pg", 2026, "SEE")]
    db = _db([_conv(2, "1261002153/2026", "Em vigor", valor=801000.0)],
             segov_rows=segov, mg_rows=[(2, bloco)])
    it = _por_numero(_monta(db), "1261002153/2026")[0]
    assert it["situacao_atual"].endswith("Desembolsado: R$ 801.000,00")
    assert it["valor_desembolsado"] == 801000.0
    assert it["desembolsos"][0]["numero_ob"] == "1674" and it["desembolsos"][0]["data"] == "14/05/2026"
    assert it["desembolsos"][1]["situacao"] == "pago segundo a SEGOV — OB sem nº/data no dump da CGE"
    assert it["desembolsos"][1]["valor"] == 800964.3
    # a SEGOV continua dando NEs e valor empenhado; o total pago dela NAO
    # sobrescreve o da CGE por baixo dos panos (so pela linha rotulada)
    assert it["valor_empenhado"] == 801000.0 and "NE 981/2026" in it["nes"]


def test_estadual_com_OB_da_cge_igual_a_segov_nao_ganha_linha_extra():
    from ingestion.cge_despesa_ob import SIT_OB, montar_bloco
    bloco = montar_bloco([{"data": "25/03/2026", "numero": "1939", "situacao": SIT_OB, "valor": 938793.55}])
    segov = [(2, "881", date(2026, 3, 5), 938793.55, 938793.55, 938793.55, "pg", 2026, "SEE")]
    db = _db([_conv(2, "1261002849/2025", "Em vigor", valor=938793.55)],
             segov_rows=segov, mg_rows=[(2, bloco)])
    it = _por_numero(_monta(db), "1261002849/2025")[0]
    assert it["situacao_atual"].endswith("Desembolsado: R$ 938.793,55")
    assert len(it["desembolsos"]) == 1 and it["desembolsos"][0]["numero_ob"] == "1939"


def test_estadual_sem_linha_na_segov_cala():
    it = _por_numero(_monta(_db([_conv(3, "1261009999/2026", "Em vigor", valor=100.0)])),
                     "1261009999/2026")[0]
    assert "nes" not in it and "empenhado" not in it and "valor_desembolsado" not in it
    assert "Pendente" not in it["situacao_atual"]


# ------------------------------------------------------------------ creche --
def test_o_pago_do_simec_sai_na_linha_da_creche_e_o_termo_nao_repete():
    db = _db([], voluntarias=[_voluntaria_creche()], termos=[_TC_CRECHE, _TC_OUTRO])
    c = _monta(db)
    creche = _por_numero(c, "932836")[0]
    assert "pago R$ 572.978,05" in creche["simec_pagamento"]
    assert "empenhado no SIMEC R$ 1.875.147,32" in creche["simec_pagamento"]
    assert creche["valor_desembolsado"] == 572978.05
    assert creche.get("valor_a_desembolsar") is None
    assert creche["situacao_atual"].endswith("Desembolsado: R$ 572.978,05")
    assert "Pendente de empenho" not in creche["situacao_atual"]
    termos = [it for it in _itens(c) if it.get("fonte") == "simec_termo"]
    assert [t["numero"] for t in termos] == ["23400.005008/2013-88"], \
        "o termo da creche repetiu (ou o outro sumiu)"


def test_sem_processo_igual_nao_junta_e_o_termo_sai_separado():
    v = _voluntaria_creche()
    v[35] = "23400.999999/2021-00"
    c = _monta(_db([], voluntarias=[v], termos=[_TC_CRECHE]))
    creche = _por_numero(c, "932836")[0]
    assert "simec_pagamento" not in creche and not creche.get("valor_desembolsado")
    assert [it["numero"] for it in _itens(c) if it.get("fonte") == "simec_termo"] == ["23400.002301/2021-01"]


def test_no_recorte_PAGAS_o_termo_pago_volta_a_sair_sozinho():
    """A regressao que a revisao pegou: a creche nao e paga no SICONV e o recorte
    'pagas' a descarta; o termo (vigencia vencida => pago) tem de sair — antes
    ele era pulado porque o processo ja estava em `_simec_ja_exibidos`."""
    db = _db([], voluntarias=[_voluntaria_creche()], termos=[_TC_CRECHE])
    c = _monta(db, estagio="pagas")
    assert not _por_numero(c, "932836"), "a voluntaria nao paga entrou no recorte 'pagas'"
    termos = [it for it in _itens(c) if it.get("fonte") == "simec_termo"]
    assert len(termos) == 1 and termos[0]["valor_desembolsado"] == 572978.05
