"""PDDE Info (FNDE): saldo das contas das escolas, situação da PC e suspensões
(25/09/2026).

As fixtures em `fixtures/pdde_info/` são as planilhas REAIS que o PDDE Info
devolveu em 24-25/09/2026 (bytes intactos) e o formulário do saldo recortado no
`<form>` de filtro:
  - saldo 08/2026 de Monte Sião (314340), Nova Palma (431310) e Aimorés (310110 —
    a caixa escolar que atende escola municipal E estadual);
  - o saldo de 09/2026 de Monte Sião, pedido antes de o mês sair (200, zero linha);
  - a PC de 2025 de Monte Sião, todas as redes e só a municipal (esferaAdm=2);
  - as suspensões de Santa Maria 2026 (92), Nova Palma 2026 (2) e Monte Sião 2025 (0).
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from ingestion import pdde_info as P
from services.pdde import montar

FIX = Path(__file__).parent / "fixtures" / "pdde_info"
PREF_MONTE_SIAO = "22646525000131"
RENATO_FRANCO_BUENO = "19696954000109"     # UEx de escola ESTADUAL em Monte Sião


def _b(nome: str) -> bytes:
    return (FIX / nome).read_bytes()


def _saldo(nome: str, uf: str, mes: date) -> dict:
    p = P.ler_planilha(_b(nome), "saldo")
    P.confere(p, uf, mes=mes)
    return P.contas_do_saldo(p.linhas)


def _como_no_banco(contas: dict) -> list[dict]:
    """As contas no formato em que a rota as lê de `pdde_saldo`."""
    return [{"cnpj": c["cnpj"], "razao_social": c["razao_social"], "banco": c["banco"],
             "agencia": c["agencia"], "conta": c["conta"], "programa": c["programa"],
             "redes": c["redes"], "saldo_conta": c["valores"][0],
             "saldo_fundos": c["valores"][1], "saldo_poupanca": c["valores"][2],
             "saldo_rdb_cdb": c["valores"][3]} for c in contas.values()]


def _pc_monte_siao_2025() -> list[dict]:
    todas = P.ler_planilha(_b("pc_314340_2025_todas.xlsx"), "prestacao")
    mun = P.ler_planilha(_b("pc_314340_2025_municipal.xlsx"), "prestacao")
    P.confere(todas, "MG", ano=2025)
    P.confere(mun, "MG", ano=2025)
    return P.linhas_da_prestacao(todas.linhas, mun.linhas)


# ---------------------------------------------------------------------------
# O formulário
# ---------------------------------------------------------------------------
def test_meses_saem_do_seletor_do_formulario():
    html = _b("form_saldo_recorte.html").decode("latin-1")    # a página é ISO-8859-1
    meses = P.meses_publicados(html)
    assert meses[0] == date(2026, 8, 1)          # em 24/09/2026 o mais novo era 08/2026
    assert meses[-1] == date(2002, 3, 1)
    assert meses == sorted(meses, reverse=True) and len(meses) == len(set(meses))


def test_programas_sao_o_seletor_mais_o_padrao_do_servidor():
    """Armadilha 2: programa vazio = 5 programas; o seletor tem 19."""
    cods = P.programas_do_formulario(_b("form_saldo_recorte.html").decode("latin-1"))
    assert len(cods) == 20
    assert set(P.PROGRAMAS_PADRAO) <= set(cods)
    assert {"Z9", "A8", "T1"} <= set(cods)       # educação integral, ensino médio...
    # Sem formulário, sobra o padrão — nunca a lista vazia (que o servidor lê
    # como "só os cinco").
    assert P.programas_do_formulario("") == sorted(P.PROGRAMAS_PADRAO)


# ---------------------------------------------------------------------------
# Saldo
# ---------------------------------------------------------------------------
def test_saldo_de_monte_siao_lido_inteiro():
    contas = _saldo("saldo_314340_082026.xlsx", "MG", date(2026, 8, 1))
    assert len(contas) == 46
    assert len({k[0] for k in contas}) == 16                  # 16 CNPJs
    total = sum(sum(c["valores"]) for c in contas.values())
    assert total == Decimal("406301.99")
    rfb = [c for c in contas.values() if c["cnpj"] == RENATO_FRANCO_BUENO]
    # O exemplo do relatório: R$ 62.167,73 em fundos — numa conta de escola ESTADUAL.
    assert any(c["valores"][1] == Decimal("62167.73") for c in rfb)
    assert all(c["redes"] == ["estadual"] for c in rfb)
    pref = [c for c in contas.values() if c["cnpj"] == PREF_MONTE_SIAO]
    assert pref and pref[0]["redes"] == ["municipal"]


def test_exportacao_traz_o_total_que_a_listagem_pagina():
    """Armadilha 1: a listagem mostra 10 por página; o Excel traz todas."""
    resumo = _b("listagem_saldo_314340_paginacao.html").decode("latin-1")
    total_listagem = int(re.search(r"de (\d+) itens", resumo).group(1))
    p = P.ler_planilha(_b("saldo_314340_082026.xlsx"), "saldo")
    assert total_listagem == 46 == len(p.linhas)


def test_programa_fora_do_padrao_so_vem_pedindo():
    """Nova Palma com a lista explícita: 2 contas de Educação Integral, que o
    padrão do servidor (5 programas) deixaria de fora."""
    contas = _saldo("saldo_431310_082026.xlsx", "RS", date(2026, 8, 1))
    progs = [c["programa"] for c in contas.values()]
    assert len(contas) == 23
    assert progs.count("PDDE-EDUCAÇÃO INTEGRAL") == 2


def test_mesma_conta_em_duas_redes_e_uma_conta_so():
    """Armadilha 4 (Aimorés): 76 linhas, 72 contas — 4 contas da mesma caixa
    escolar vêm duas vezes, MUNICIPAL e ESTADUAL, com o mesmo saldo."""
    p = P.ler_planilha(_b("saldo_310110_082026.xlsx"), "saldo")
    contas = P.contas_do_saldo(p.linhas)
    assert (len(p.linhas), len(contas)) == (76, 72)
    duplas = [c for c in contas.values() if len(c["redes"]) == 2]
    assert len(duplas) == 4
    assert {c["cnpj"] for c in duplas} == {"19616705000166"}
    soma_linhas = sum(sum(P._dec(x[k]) for k in ("saldo conta", "saldo fundos",
                                                  "saldo poupanca", "saldo rdb/cdb"))
                      for x in p.linhas)
    soma_contas = sum(sum(c["valores"]) for c in contas.values())
    assert soma_linhas - soma_contas == sum(sum(c["valores"]) for c in duplas)


def test_mesma_conta_com_dois_saldos_e_recusada():
    p = P.ler_planilha(_b("saldo_310110_082026.xlsx"), "saldo")
    linhas = [dict(x) for x in p.linhas]
    dupla = [i for i, x in enumerate(linhas) if x["cnpj"] == "19616705000166"
             and x["conta"] == "0000262498"]
    linhas[dupla[1]]["saldo fundos"] = "1,00"
    with pytest.raises(P.PlanilhaRecusada, match="dois saldos"):
        P.contas_do_saldo(linhas)


def test_mes_nao_publicado_vem_vazio_e_nao_apaga():
    """Armadilha 3: 09/2026 pedido em 24/09 — 200, cabeçalho certo, zero linha."""
    p = P.ler_planilha(_b("saldo_314340_092026_nao_publicado.xlsx"), "saldo")
    assert P.confere(p, "MG", mes=date(2026, 9, 1)) == "MONTE SIAO"
    assert p.linhas == []
    cur = BancoFalso().cursor()
    n, recusa = P.grava(cur, 1, P.Pedido("saldo", date(2026, 9, 1), True), [])
    assert n == 0 and "nada apagado" in recusa
    assert cur.sqls == []                         # nem DELETE, nem carga


def test_planilha_de_outro_municipio_mes_ou_uf_e_recusada():
    p = P.ler_planilha(_b("saldo_314340_082026.xlsx"), "saldo")
    with pytest.raises(P.PlanilhaRecusada, match="UF RS"):
        P.confere(p, "RS", mes=date(2026, 8, 1))
    with pytest.raises(P.PlanilhaRecusada, match="mês do cabeçalho"):
        P.confere(p, "MG", mes=date(2026, 7, 1))
    linhas = [dict(x) for x in p.linhas]
    linhas[3]["municipio"] = "MONTE SANTO DE MINAS"
    with pytest.raises(P.PlanilhaRecusada, match="outro município"):
        P.confere(P.Planilha(p.meta, linhas), "MG", mes=date(2026, 8, 1))


def test_resposta_que_nao_e_planilha_e_falha_e_nao_zero():
    """Armadilhas 7 e 8: os textos que a fonte devolveu no lugar do .xlsx."""
    for corpo in ("Um ou mais municípios não pertencem às UFs selecionadas.".encode(),
                  b"Erro ao gerar arquivo Excel: SQLSTATE[HY000]: General error: 1722 "
                  b"OCIStmtExecute: ORA-01722: invalid number", b""):
        with pytest.raises(P.PlanilhaRecusada, match="não devolveu planilha"):
            P.ler_planilha(corpo, "saldo")


def test_coluna_que_falta_e_recusa_com_o_nome():
    """Armadilha 9: a planilha de saldo lida como a de suspensão não tem
    "Programa", "Destinação"... — recusa dizendo quais."""
    with pytest.raises(P.PlanilhaRecusada, match="Destinação"):
        P.ler_planilha(_b("saldo_314340_082026.xlsx"), "suspensao")


# ---------------------------------------------------------------------------
# Prestação de contas e suspensão
# ---------------------------------------------------------------------------
def test_pc_marca_a_rede_municipal_pela_segunda_consulta():
    pc = _pc_monte_siao_2025()
    assert len(pc) == 29
    assert sum(x["municipal"] for x in pc) == 26
    fora = {x["escola_nome"] for x in pc if not x["municipal"]}
    assert fora == {"APAE ESC AMIZADE", "EE PROVEDOR THEOFILO TAVARES PAES"}
    assert all(x["uex_situacao"] == "Adimplente" and x["uex_suspensa"] is False for x in pc)
    assert sum(x["valor_previsto"] for x in pc) == Decimal("172084.00")
    # A escola estadual é executada pela Secretaria de Estado, e a UEx dela é a
    # caixa escolar dos R$ 62 mil.
    ee = next(x for x in pc if x["escola_nome"] == "EE PROVEDOR THEOFILO TAVARES PAES")
    assert ee["uex_cnpj"] == RENATO_FRANCO_BUENO and ee["eex_cnpj"] == "18715599000105"


def test_pc_municipal_fora_da_completa_e_recusada():
    todas = P.ler_planilha(_b("pc_314340_2025_todas.xlsx"), "prestacao")
    mun = P.ler_planilha(_b("pc_314340_2025_municipal.xlsx"), "prestacao")
    # A 1ª linha é a APAE (particular); a 2ª é escola municipal.
    assert todas.linhas[1]["nome da escola"] == "C MUN EDUC INF ELVIRA C BERNARDI"
    sem_uma = todas.linhas[:1] + todas.linhas[2:]
    with pytest.raises(P.PlanilhaRecusada, match="fora da PC completa"):
        P.linhas_da_prestacao(sem_uma, mun.linhas)


def test_suspensoes_de_santa_maria_2026():
    p = P.ler_planilha(_b("susp_431690_2026.xlsx"), "suspensao")
    P.confere(p, "RS", ano=2026)
    s = P.linhas_da_suspensao(p.linhas)
    assert len(s) == 92
    assert sum(x["rede"] == "municipal" for x in s) == 17
    assert sum(x["tipo"] == "UEX sem dirigente ativo (UEX)" for x in s) == 48
    assert len({x["escola_inep"] for x in s if x["rede"] == "municipal"}) == 8
    # "Escola sem UEX" vem sem CNPJ — é justamente o motivo.
    assert all(x["uex_cnpj"] is None for x in s if x["tipo"] == "Escola sem UEX (escola)")


def test_suspensoes_de_nova_palma_sao_de_escola_estadual():
    """As duas de Nova Palma em 2026 são da rede ESTADUAL: ficam fora da conta
    municipal da tela, mas aparecem (outras redes)."""
    p = P.ler_planilha(_b("susp_431310_2026.xlsx"), "suspensao")
    P.confere(p, "RS", ano=2026)
    s = P.linhas_da_suspensao(p.linhas)
    assert [(x["rede"], x["tipo"]) for x in s] == [("estadual", "UEX sem dirigente ativo (UEX)")] * 2
    r = montar(cnpj_prefeitura="88488358000156", rede="municipal", mes_ref=None, saldo=[],
               saldo_antigo=None, prestacao=[], suspensao=s, recebido=None)
    assert r["totais"]["escolas_suspensas"] == 0 and r["outras_redes"]["suspensas"] == 1


def test_suspensao_zero_e_resposta_e_e_gravada():
    """Armadilha 10: Monte Sião 2025 não tem suspensão — a planilha veio com o
    cabeçalho e o município, e a carga registra 0 (≠ "não coletado")."""
    p = P.ler_planilha(_b("susp_314340_2025.xlsx"), "suspensao")
    P.confere(p, "MG", ano=2025)
    assert p.linhas == []
    db = BancoFalso()
    n, recusa = P.grava(db.cursor(), 7, P.Pedido("suspensao", date(2025, 1, 1), False), [])
    assert (n, recusa) == (0, None)
    assert db.carga[(7, "suspensao", date(2025, 1, 1))] == 0


# ---------------------------------------------------------------------------
# A fila de cada município
# ---------------------------------------------------------------------------
MESES = [date(2026, m, 1) for m in range(8, 0, -1)] + [date(2025, m, 1) for m in range(12, 0, -1)]


def test_primeira_noite_diario_e_depois_a_fila():
    hoje = date(2026, 9, 25)
    ped = P.pedidos(hoje, MESES, {})
    diario = [(p.relatorio, p.referencia) for p in ped if p.diario]
    fila = [(p.relatorio, p.referencia) for p in ped if not p.diario]
    assert diario == [("suspensao", date(2026, 1, 1)), ("prestacao", date(2026, 1, 1)),
                      ("saldo", date(2026, 8, 1))]
    assert fila == [("suspensao", date(2025, 1, 1)), ("prestacao", date(2025, 1, 1)),
                    ("saldo", date(2026, 7, 1)), ("saldo", date(2026, 6, 1))]


def test_noite_seguinte_so_o_que_muda_e_o_proximo_pedaco_da_carga():
    hoje = date(2026, 9, 26)
    ontem = datetime(2026, 9, 25, 5, 10)
    cargas = {("suspensao", date(2026, 1, 1)): ontem, ("prestacao", date(2026, 1, 1)): ontem,
              ("saldo", date(2026, 8, 1)): ontem, ("suspensao", date(2025, 1, 1)): ontem,
              ("prestacao", date(2025, 1, 1)): ontem, ("saldo", date(2026, 7, 1)): ontem,
              ("saldo", date(2026, 6, 1)): ontem}
    ped = [(p.relatorio, p.referencia, p.diario) for p in P.pedidos(hoje, MESES, cargas)]
    # O ano corrente é relido TODA noite (todo município, todo dia); o saldo do mês
    # mais novo e o ano anterior, não.
    assert ped == [("suspensao", date(2026, 1, 1), True), ("prestacao", date(2026, 1, 1), True),
                   ("saldo", date(2026, 5, 1), False), ("saldo", date(2026, 4, 1), False)]
    # Uma semana depois o mês mais novo e o ano anterior voltam.
    semana = [(p.relatorio, p.referencia) for p in
              P.pedidos(hoje + timedelta(days=6), MESES, cargas)]
    assert ("saldo", date(2026, 8, 1)) in semana and ("prestacao", date(2025, 1, 1)) in semana


def test_janela_do_historico_do_saldo():
    cargas = {("saldo", m): date(2026, 9, 25) for m in MESES[:12]}
    ped = P.pedidos(date(2026, 9, 25), MESES, cargas)
    assert not [p for p in ped if p.relatorio == "saldo"]      # 12 meses = janela cheia


# ---------------------------------------------------------------------------
# Idempotência: a mesma planilha duas vezes dá o mesmo banco
# ---------------------------------------------------------------------------
class BancoFalso:
    """O bastante de Postgres para `grava`: DELETE por (município, referência),
    INSERT em lote e o upsert de `pdde_carga`."""

    def __init__(self):
        self.tabelas = {"pdde_saldo": [], "pdde_prestacao": [], "pdde_suspensao": []}
        self.carga: dict = {}

    def cursor(self):
        return _Cursor(self)


class _Cursor:
    def __init__(self, db):
        self.db = db
        self.sqls: list[str] = []

    def execute(self, sql, params=()):
        self.sqls.append(sql)
        m = re.search(r"DELETE FROM (\w+) WHERE municipio_id = %s AND (\w+) = %s", sql)
        if m:
            col = 1 if m.group(2) in ("mes", "ano") else None
            self.db.tabelas[m.group(1)] = [r for r in self.db.tabelas[m.group(1)]
                                           if (r[0], r[col]) != tuple(params)]
            return
        if "INSERT INTO pdde_carga" in sql:
            mid, rel, ref, linhas = params
            self.db.carga[(mid, rel, ref)] = linhas
            return
        raise AssertionError(f"SQL inesperado: {sql}")


@pytest.fixture
def lote_falso(monkeypatch):
    import psycopg2.extras

    def execute_values(cur, sql, linhas, **_):
        tabela = re.search(r"INSERT INTO (\w+)", sql).group(1)
        cur.db.tabelas[tabela].extend(tuple(x) for x in linhas)
    monkeypatch.setattr(psycopg2.extras, "execute_values", execute_values)


def test_gravar_a_mesma_planilha_duas_vezes_da_o_mesmo_banco(lote_falso):
    db = BancoFalso()
    contas = list(_saldo("saldo_314340_082026.xlsx", "MG", date(2026, 8, 1)).values())
    pc = _pc_monte_siao_2025()
    susp = P.linhas_da_suspensao(P.ler_planilha(_b("susp_431690_2026.xlsx"), "suspensao").linhas)
    pedidos = [(P.Pedido("saldo", date(2026, 8, 1), True), contas),
               (P.Pedido("prestacao", date(2025, 1, 1), False), pc),
               (P.Pedido("suspensao", date(2026, 1, 1), True), susp)]
    for p, regs in pedidos:
        assert P.grava(db.cursor(), 1, p, regs) == (len(regs), None)
    uma = {k: sorted(v, key=repr) for k, v in db.tabelas.items()}
    for p, regs in pedidos:
        P.grava(db.cursor(), 1, p, regs)
    assert {k: sorted(v, key=repr) for k, v in db.tabelas.items()} == uma
    assert (len(uma["pdde_saldo"]), len(uma["pdde_prestacao"]), len(uma["pdde_suspensao"])) \
        == (46, 29, 92)
    assert db.carga == {(1, "saldo", date(2026, 8, 1)): 46,
                        (1, "prestacao", date(2025, 1, 1)): 29,
                        (1, "suspensao", date(2026, 1, 1)): 92}


def test_outro_mes_e_outro_municipio_nao_sao_tocados(lote_falso):
    db = BancoFalso()
    contas = list(_saldo("saldo_314340_082026.xlsx", "MG", date(2026, 8, 1)).values())
    P.grava(db.cursor(), 1, P.Pedido("saldo", date(2026, 8, 1), True), contas)
    P.grava(db.cursor(), 1, P.Pedido("saldo", date(2026, 7, 1), False), contas[:3])
    P.grava(db.cursor(), 2, P.Pedido("saldo", date(2026, 8, 1), True), contas[:5])
    # Relê 08/2026 do município 1 com menos contas: só aquele (município, mês) muda.
    P.grava(db.cursor(), 1, P.Pedido("saldo", date(2026, 8, 1), True), contas[:10])
    por = {}
    for r in db.tabelas["pdde_saldo"]:
        por[(r[0], r[1])] = por.get((r[0], r[1]), 0) + 1
    assert por == {(1, date(2026, 8, 1)): 10, (1, date(2026, 7, 1)): 3,
                   (2, date(2026, 8, 1)): 5}


# ---------------------------------------------------------------------------
# A conta da tela (services/pdde.py)
# ---------------------------------------------------------------------------
def _monte_siao(rede: str, recebido=None, suspensao=()):
    contas = _saldo("saldo_314340_082026.xlsx", "MG", date(2026, 8, 1))
    return montar(cnpj_prefeitura=PREF_MONTE_SIAO, rede=rede, mes_ref=date(2026, 8, 1),
                  saldo=_como_no_banco(contas), saldo_antigo=None,
                  prestacao=_pc_monte_siao_2025(), suspensao=list(suspensao),
                  recebido=recebido)


def test_rede_municipal_deixa_a_escola_estadual_fora_da_conta():
    r = _monte_siao("municipal")
    cnpjs = {e["cnpj"] for e in r["entidades"]}
    assert RENATO_FRANCO_BUENO not in cnpjs and "41774639000101" not in cnpjs   # APAE
    assert PREF_MONTE_SIAO in cnpjs
    # A conta da tela = as linhas MUNICIPAIS da planilha, somadas de outro jeito.
    p = P.ler_planilha(_b("saldo_314340_082026.xlsx"), "saldo")
    esperado = sum(sum(P._dec(x[k]) for k in ("saldo conta", "saldo fundos", "saldo poupanca",
                                                "saldo rdb/cdb"))
                   for x in p.linhas if "MUNICIPAL" in P.sem_acento(x["rede de ensino"]).upper())
    assert Decimal(str(r["totais"]["saldo"])) == esperado == Decimal("140395.03")
    assert r["outras_redes"] == {"saldo": 265906.96, "entidades": 2, "suspensas": 0}
    todas = _monte_siao("todas")
    assert todas["totais"]["saldo"] == 406301.99 and todas["outras_redes"] is None


def test_parado_e_saldo_acima_do_previsto_do_ano():
    r = _monte_siao("municipal")
    lazaro = next(e for e in r["entidades"] if e["nome"] == "CAIXA ESCOLAR LAZARO CANDIDO DE SOUZA")
    assert (lazaro["saldo"], lazaro["previsto_ano"], lazaro["parado"]) == (35916.36, 10081.0, True)
    pref = next(e for e in r["entidades"] if e["prefeitura"])
    # A prefeitura não executa escola sem UEx em Monte Sião: sem previsto, o
    # "parado" fica em aberto — nunca "não está parado".
    assert pref["previsto_ano"] is None and pref["parado"] is None
    assert r["totais"]["entidades_paradas"] == 3
    assert r["totais"]["saldo_parado"] == 76799.16
    assert r["prefeitura_eex"] == {"situacoes": ["Adimplente"], "suspensa": False, "escolas": 13}


def test_suspensas_vem_primeiro_e_contam_escolas():
    susp = [{"rede": "municipal", "programa": "PDDE", "destinacao": "PDDE Básico - 1ª Parcela",
             "escola_inep": "31319252", "escola_nome": "C MUN EDUC INF ELVIRA C BERNARDI",
             "uex_cnpj": "34330971000111", "uex_nome": "CAIXA ESCOLAR ELVIRA",
             "tipo": "UEX sem dirigente ativo (UEX)"},
            {"rede": "municipal", "programa": "PDDE", "destinacao": "PDDE Básico - 1ª Parcela",
             "escola_inep": "99999999", "escola_nome": "EMEI SEM UEX", "uex_cnpj": None,
             "uex_nome": None, "tipo": "Escola sem UEX (escola)"},
            {"rede": "estadual", "programa": "PDDE", "destinacao": "PDDE Básico - 1ª Parcela",
             "escola_inep": "31055816", "escola_nome": "EE PROVEDOR THEOFILO TAVARES PAES",
             "uex_cnpj": RENATO_FRANCO_BUENO, "uex_nome": "CAIXA ESCOLAR RENATO FRANCO BUENO",
             "tipo": "Inadimplente (UEX)"}]
    r = _monte_siao("municipal", suspensao=susp)
    assert r["entidades"][0]["cnpj"] == "34330971000111" and r["entidades"][0]["suspensa"]
    assert r["totais"]["escolas_suspensas"] == 2          # a estadual fica fora
    assert [s["escola_nome"] for s in r["sem_executora"]] == ["EMEI SEM UEX"]
    assert r["outras_redes"]["suspensas"] == 1
    assert _monte_siao("todas", suspensao=susp)["totais"]["escolas_suspensas"] == 3


def test_pdde_pago_vem_das_liberacoes_do_fnde_pelo_cnpj_e_ausencia_nao_e_zero():
    """O PDDE liberado no ano (simad, `simec_par_liberacoes`) — o mesmo dado do
    bloco das escolas na tela do SIMEC —, casado pelo CNPJ da executora."""
    assert _monte_siao("municipal")["totais"]["recebido_ano"] is None     # ano não lido
    nada = _monte_siao("municipal", recebido={})
    assert nada["totais"]["recebido_ano"] is None and nada["totais"]["entidades_com_liberacao"] == 0
    r = _monte_siao("municipal", recebido={"08086062000170": Decimal("10081.00"),
                                           RENATO_FRANCO_BUENO: Decimal("19342.00")})
    lazaro = next(e for e in r["entidades"] if e["cnpj"] == "08086062000170")
    assert lazaro["recebido_ano"] == 10081.0
    assert r["totais"]["recebido_ano"] == 10081.0         # a estadual não entra na conta
    assert next(e for e in r["entidades"] if e["prefeitura"])["recebido_ano"] is None
