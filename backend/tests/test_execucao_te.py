"""A EXECUÇÃO da Transferência Especial — uma leitura só (24/09/2026).

Pedido da Laiza (Nova Serrana/MG), no PDF de Parlamentares: "não tá falando se ela
já foi paga, já foi empenhada, ou tá aguardando pagamento, ela só tá na situação
como CIENTE". CIENTE é a situação do PLANO (cadastro), e o dinheiro mora em
`pagamentos` e `detalhe->'empenhos'`.

Os dois planos de verdade vêm da CAPTURA REAL da API oficial
(`fixtures/te_especiais_arvore.json`, via os helpers de `test_te_arvore.py`),
passando pelo MESMO `pagamentos_da_arvore` que grava a coluna em produção:

  91573 — R$ 205.066,16 pagos (OB de 22/06/2026) e R$ 192.933,84 em MINUTA de DH;
  67457 — dois empenhos (60 mil + 140 mil), 100% pagos em 25/06/2024.

O que se prova: cada um dos seis estados, que NULO nunca vira «Sem empenho» nem
R$ 0, que minuta (de empenho ou de DH) não é dinheiro, e que o texto do RM
continuou byte a byte o mesmo depois de passar a sair daqui.
"""
import json
import re
from pathlib import Path

import pytest

from ingestion.transferegov_te import pagamentos_da_arvore
from services.execucao_te import (ROTULOS, empenho_real, execucao_te, frase_execucao_te,
                                  frase_relatorio_gestao, situacao_e_execucao, texto_rm_te)
from tests.test_te_arvore import PLANO_67457, PLANO_91573, _arvore

RAIZ = Path(__file__).resolve().parent.parent


def _gravado(plano, valor_total):
    """O que o coletor grava nas duas colunas: (pagamentos, detalhe->'empenhos')."""
    arv = _arvore(plano)
    return pagamentos_da_arvore(arv, valor_total), arv["empenhos"]


# ---------------------------------------------------------------------------
# Os dois planos reais
# ---------------------------------------------------------------------------
def test_91573_pago_em_parte_com_a_minuta_de_DH_fora_do_pago():
    pg, emps = _gravado(PLANO_91573, 398000.0)
    ex = execucao_te(pg, emps, True)
    assert ex["estado"] == "pago_parte"
    assert ex["rotulo"] == "Pago em parte"
    assert ex["consultada"] is True
    assert ex["valor_empenhado"] == 398000.0
    assert ex["valor_pago"] == 205066.16          # a minuta de R$ 192.933,84 NÃO conta
    assert ex["valor_a_pagar"] == 192933.84
    assert ex["dt_ultimo_pagamento"] == "22/06/2026"


def test_67457_pago_com_os_dois_empenhos_somados():
    pg, emps = _gravado(PLANO_67457, 200000.0)
    ex = execucao_te(pg, emps, True)
    assert ex["estado"] == "pago"
    assert ex["rotulo"] == "Pago"
    assert ex["valor_empenhado"] == 200000.0      # 60.000 + 140.000
    assert ex["valor_pago"] == 200000.0
    assert ex["dt_ultimo_pagamento"] == "25/06/2024"


# ---------------------------------------------------------------------------
# NULO não é zero
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pagamentos", [None, {}, "null", ""])
def test_pagamentos_nulo_e_execucao_nao_consultada_e_nunca_R_0(pagamentos):
    """Mesmo com empenhos lidos: sem `pagamentos`, não se afirma nada do dinheiro."""
    _pg, emps = _gravado(PLANO_91573, 398000.0)
    ex = execucao_te(pagamentos, emps, True)
    assert ex["estado"] == "nao_consultada"
    assert ex["rotulo"] == "Execução não consultada"
    assert ex["consultada"] is False
    assert ex["valor_pago"] is None and ex["valor_empenhado"] is None
    assert ex["valor_a_pagar"] is None and ex["dt_ultimo_pagamento"] is None


def test_sem_empenho_so_com_os_empenhos_LIDOS():
    """Árvore lida, nenhum empenho, nenhum documento hábil: «Sem empenho»."""
    pg = pagamentos_da_arvore({"empenhos": []}, 500000.0)
    ex = execucao_te(pg, [], True)
    assert ex["estado"] == "sem_empenho"
    assert ex["rotulo"] == "Sem empenho"
    assert ex["valor_pago"] == 0.0 and ex["valor_empenhado"] == 0.0


@pytest.mark.parametrize("empenhos,coletado", [(None, False), ([], False), (None, True)])
def test_sem_os_empenhos_lidos_nunca_afirma_sem_empenho(empenhos, coletado):
    """⚠️ `pagamentos` gravado pela SPA (antes de 14/09) ou com `detalhe` NULO: a
    SPA só lista documento hábil, e empenho sem DH é invisível a ela. O que se
    sabe é «sem pagamento» — nunca «sem empenho»."""
    pg = pagamentos_da_arvore({"empenhos": []}, 500000.0)
    ex = execucao_te(pg, empenhos, coletado)
    assert ex["estado"] == "sem_pagamento"
    assert ex["rotulo"] == "Sem pagamento"
    assert ex["valor_empenhado"] is None


# ---------------------------------------------------------------------------
# Minuta não é dinheiro — nem de empenho, nem de documento hábil
# ---------------------------------------------------------------------------
MINUTA_DE_EMPENHO = {"numero_empenho": None, "valor_empenho": 1043317.0,
                     "situacao_empenho": 1,
                     "descricao_situacao_empenho": "Minuta de Empenho",
                     "documentos_habeis": []}


def test_so_minuta_de_empenho_e_sem_empenho_com_empenhado_zero():
    """4.963 minutas de empenho na base em 24/09/2026, com o valor CHEIO."""
    pg = pagamentos_da_arvore({"empenhos": [MINUTA_DE_EMPENHO]}, 1043317.0)
    ex = execucao_te(pg, [MINUTA_DE_EMPENHO], True)
    assert ex["estado"] == "sem_empenho"
    assert ex["valor_empenhado"] == 0.0


def test_empenho_enviado_sem_documento_habil_e_empenhado_aguardando_pagamento():
    emp = {"numero_empenho": "2026NE000123", "valor_empenho": 300000.0,
           "situacao_empenho": 4, "descricao_situacao_empenho": "Enviado",
           "documentos_habeis": []}
    pg = pagamentos_da_arvore({"empenhos": [emp]}, 300000.0)
    ex = execucao_te(pg, [emp, MINUTA_DE_EMPENHO], True)
    assert ex["estado"] == "empenhado"
    assert ex["rotulo"] == "Empenhado, aguardando pagamento"
    assert ex["valor_empenhado"] == 300000.0      # a minuta ao lado não soma
    assert ex["valor_pago"] == 0.0


def test_so_minuta_de_DH_e_empenhado_mesmo_sem_os_empenhos_lidos():
    """Documento hábil só existe pendurado num empenho: havendo DH (mesmo minuta)
    há empenho, e nada saiu. Vale para o `pagamentos` da SPA, sem `detalhe`."""
    arv = _arvore(PLANO_91573)
    for emp in arv["empenhos"]:
        for dh in emp.get("documentos_habeis") or []:
            dh["ordens"] = []                      # nenhuma OP/OB ainda
    pg = pagamentos_da_arvore(arv, 398000.0)
    assert pg["valor_desembolsado"] == 0.0 and pg["pendentes"]
    ex = execucao_te(pg, None, False)
    assert ex["estado"] == "empenhado"
    assert ex["valor_pago"] == 0.0


@pytest.mark.parametrize("emp,real", [
    ({"numero_empenho": "2026NE1", "descricao_situacao_empenho": "Enviado"}, True),
    ({"numero_empenho": None, "descricao_situacao_empenho": "Minuta de Empenho"}, False),
    ({"numero_empenho": "2026NE1", "descricao_situacao_empenho": "MINUTA"}, False),
    ({"numero_empenho": "2026NE1", "descricao_situacao_empenho": "Cancelado"}, False),
    ({"numero_empenho": "  ", "descricao_situacao_empenho": "Enviado"}, False),
    ("lixo", False), (None, False),
])
def test_empenho_real_exige_numero_e_nao_e_minuta(emp, real):
    assert empenho_real(emp) is real


# ---------------------------------------------------------------------------
# O driver e o lixo
# ---------------------------------------------------------------------------
def test_jsonb_em_texto_le_igual_ao_dict():
    """asyncpg sem codec devolve JSONB como str; o resultado não pode mudar."""
    pg, emps = _gravado(PLANO_91573, 398000.0)
    assert execucao_te(json.dumps(pg), json.dumps(emps), True) == execucao_te(pg, emps, True)


@pytest.mark.parametrize("pagamentos,empenhos", [
    ("{nao e json", None),
    ({"valor_desembolsado": "abc", "obs": "x", "pendentes": 3}, ["lixo", None, 3]),
    ({"pago_integral": True, "valor_desembolsado": None}, {"nao": "lista"}),
    ([1, 2, 3], "[]"),
    (42, 42),
])
def test_lixo_nao_levanta_excecao(pagamentos, empenhos):
    """Exceção aqui cairia no `except Exception: pass` de `detalhe_core` e apagaria
    a seção inteira da Transferência Especial da tela, do PDF e do Consolidado."""
    ex = execucao_te(pagamentos, empenhos, True)
    assert ex["rotulo"] in ROTULOS.values()
    assert set(ex) == {"estado", "rotulo", "consultada", "valor_empenhado", "valor_pago",
                       "valor_a_pagar", "dt_ultimo_pagamento", "tem_documento_habil"}


# ---------------------------------------------------------------------------
# O RM continua escrevendo EXATAMENTE o que escrevia
# ---------------------------------------------------------------------------
def test_texto_do_RM_nos_quatro_casos():
    """As frases de sempre do bloco TE do RM, agora vindas de `texto_rm_te`. O RM
    fica gravado em `rm_relatorios.conteudo`: mudar uma vírgula aqui mudaria só os
    relatórios novos."""
    pg_pago, _ = _gravado(PLANO_67457, 200000.0)
    pg_parte, _ = _gravado(PLANO_91573, 398000.0)
    arv = _arvore(PLANO_91573)
    for emp in arv["empenhos"]:
        for dh in emp.get("documentos_habeis") or []:
            dh["ordens"] = []
    pg_so_dh = pagamentos_da_arvore(arv, 398000.0)
    pg_nada = pagamentos_da_arvore({"empenhos": []}, 500000.0)

    # O RM passa SÓ `pagamentos` (row[8]), sem os empenhos.
    assert texto_rm_te(execucao_te(pg_pago)) == "Pago integralmente: R$ 200.000,00"
    assert texto_rm_te(execucao_te(pg_parte)) == \
        "Desembolsado: R$ 205.066,16 · Pendente de desembolso"
    assert texto_rm_te(execucao_te(pg_so_dh)) == "Pendente de desembolso"
    assert texto_rm_te(execucao_te(pg_nada)) == ""
    assert texto_rm_te(execucao_te(None)) == ""
    assert texto_rm_te(execucao_te({})) == ""


def test_empenho_sem_DH_nao_muda_o_texto_do_RM():
    """O RM não lê `detalhe`; mesmo que um dia leia, empenho sem documento hábil
    não escreve "Pendente de desembolso" sem decisão do dono (ver CONTINUAR)."""
    emp = {"numero_empenho": "2026NE000123", "valor_empenho": 300000.0,
           "descricao_situacao_empenho": "Enviado", "documentos_habeis": []}
    pg = pagamentos_da_arvore({"empenhos": [emp]}, 300000.0)
    assert texto_rm_te(execucao_te(pg, [emp], True)) == ""


# ---------------------------------------------------------------------------
# Contrato: os três leitores passam por aqui
# ---------------------------------------------------------------------------
def _fonte(rel: str) -> str:
    return (RAIZ / rel).read_text(encoding="utf-8")


def test_o_RM_le_a_execucao_da_TE_por_este_modulo():
    fonte = _fonte("services/rm_builder.py")
    bloco = fonte[fonte.index("# === Transferencia Especial / Plano de Acao"):
                  fonte.index("# === SIMEC liberacoes")]
    assert "execucao_te(row[8])" in bloco
    assert "_txt_pg = texto_rm_te(_ex_te)" in bloco
    # Nenhuma segunda leitura de `pago_integral` no bloco.
    assert 'get("pago_integral")' not in bloco


def test_detalhe_core_le_a_execucao_pelo_mesmo_helper_e_com_as_colunas_no_fim():
    fonte = _fonte("routers/parlamentares.py")
    assert "from services.execucao_te import execucao_te" in fonte
    sql = fonte.split('sql_pa = f"""', 1)[1].split('"""', 1)[0]
    # As colunas novas vêm DEPOIS das 11 antigas: o laço lê por índice.
    assert sql.index("COALESCE(te.valor_investimento, 0)") < sql.index("te.pagamentos,")
    assert "te.detalhe->'empenhos'" in sql and "(te.detalhe IS NOT NULL)" in sql
    assert "execucao_te(r[11], r[12], bool(r[13]))" in fonte


def test_o_SELECT_do_plano_de_acao_e_SQL_valido():
    """Erro de SQL aqui não levanta: cai no `except Exception: pass` e a seção
    some calada. Gramática real do Postgres (pglast), sem banco."""
    pglast = pytest.importorskip("pglast")
    fonte = _fonte("routers/parlamentares.py")
    sql = fonte.split('sql_pa = f"""', 1)[1].split('"""', 1)[0]
    sql = sql.replace("{mun_te_d}{ano_te_d}",
                      " AND te.municipio_id = ANY(:muns)"
                      " AND substr(te.programa_codigo, 5, 4) = ANY(:anos_txt_te)")
    n = iter(range(1, 50))
    sql = re.sub(r":(\w+)", lambda _m: f"${next(n)}", sql)
    pglast.parse_sql(sql)


def test_o_PDF_escreve_a_execucao_por_esta_frase():
    """O PDF no modelo da planilha (24/09/2026) escreve a SITUAÇÃO ATUAL da TE
    por `frase_execucao_te` — nenhuma segunda leitura do dinheiro no relatório."""
    fonte = _fonte("services/relatorio_parlamentares.py")
    assert "from services.execucao_te import frase_execucao_te" in fonte
    assert "frase_execucao_te(ex, x.get(\"valor_total\"))" in fonte


# ---------------------------------------------------------------------------
# A execução POR EXTENSO (PDF no modelo da planilha) — cada estado, uma frase
# ---------------------------------------------------------------------------
def test_frase_dos_dois_planos_reais():
    """As frases do modelo do cliente ("Pagamento realizado em 13/12/2024."),
    com as datas e valores que a CAPTURA REAL dá — não os do código."""
    pg_pago, emps_pago = _gravado(PLANO_67457, 200000.0)
    pg_parte, emps_parte = _gravado(PLANO_91573, 398000.0)
    assert frase_execucao_te(execucao_te(pg_pago, emps_pago, True), 200000.0) == \
        "Pagamento realizado em 25/06/2024."
    assert frase_execucao_te(execucao_te(pg_parte, emps_parte, True), 398000.0) == \
        "Pago em parte: R$ 205.066,16 de R$ 398.000,00; último pagamento em 22/06/2026."


@pytest.mark.parametrize("estado,frase_esperada", [
    ("empenhado", "Empenhado, aguardando pagamento."),
    ("sem_empenho", "Sem empenho."),
    ("sem_pagamento", "Sem pagamento."),
    ("nao_consultada", "Execução não consultada."),
])
def test_frase_de_cada_estado_sem_dinheiro(estado, frase_esperada):
    assert frase_execucao_te({"estado": estado}, 100.0) == frase_esperada


def test_frase_dos_estados_produzidos_pelo_helper():
    """Os mesmos estados, agora saindo de `execucao_te` (e não escritos à mão)."""
    emp = {"numero_empenho": "2026NE000123", "valor_empenho": 300000.0,
           "descricao_situacao_empenho": "Enviado", "documentos_habeis": []}
    pg_emp = pagamentos_da_arvore({"empenhos": [emp]}, 300000.0)
    pg_nada = pagamentos_da_arvore({"empenhos": []}, 500000.0)
    assert frase_execucao_te(execucao_te(pg_emp, [emp], True)) == "Empenhado, aguardando pagamento."
    assert frase_execucao_te(execucao_te(pg_nada, [], True)) == "Sem empenho."
    assert frase_execucao_te(execucao_te(pg_nada, None, False)) == "Sem pagamento."
    assert frase_execucao_te(execucao_te(None)) == "Execução não consultada."


def test_so_o_nao_consultado_diz_nao_consultada():
    """Achado (a) da revisão do 97e4903: nenhum texto diz "não consultado" do que
    foi consultado — nem do plano pago sem data, nem do consultado sem OB."""
    for estado in ("pago", "pago_parte", "empenhado", "sem_empenho", "sem_pagamento"):
        assert "consultad" not in frase_execucao_te({"estado": estado}, 1.0)
    # Pago sem data: diz o que se sabe, sem inventar data nem "não consultado".
    assert frase_execucao_te({"estado": "pago"}) == "Pagamento realizado."


def _relatorios_enxutos(arv: dict) -> list[dict]:
    """O que o SELECT de `detalhe_core` monta de `detalhe->'relatorios_gestao_novos'`
    (tipo, situação, data e QUANTAS análises) — aqui a partir da árvore REAL."""
    return [{"tipo": r.get("tipo_relatorio_gestao_novo"),
             "situacao": r.get("situacao_relatorio_gestao_novo"),
             "data": r.get("data_relatorio_gestao_novo"),
             "analises": len(r.get("analises") or [])}
            for r in arv.get("relatorios_gestao_novos") or []]


def test_relatorio_de_gestao_do_67457_real():
    """O 67457 tem relatório de gestão FINAL "Disponibilizado" em 30/12/2025 e
    nenhuma análise na captura. A frase diz exatamente isso — e não "aguardando
    análise", que a fonte não afirma."""
    arv = _arvore(PLANO_67457)
    txt = frase_relatorio_gestao(_relatorios_enxutos(arv), len(arv["relatorios_gestao"]),
                                 True, "pago")
    assert txt == ("Relatório de gestão final: Disponibilizado em 30/12/2025; "
                   "nenhuma análise registrada.")


def test_relatorio_de_gestao_so_afirma_ausencia_com_a_arvore_lida_e_dinheiro_pago():
    assert frase_relatorio_gestao([], 0, True, "pago") == "Nenhum relatório de gestão registrado."
    assert frase_relatorio_gestao([], 0, False, "pago") == ""        # árvore não lida
    assert frase_relatorio_gestao([], 0, True, "empenhado") == ""    # nada pago ainda
    assert frase_relatorio_gestao([], 1, True, "pago") == ""         # há na lista antiga
    assert frase_relatorio_gestao("lixo", "x", True, "pago") == "Nenhum relatório de gestão registrado."
    assert frase_relatorio_gestao([{"tipo": "Parcial", "situacao": "Em análise",
                                    "data": "2026-01-02", "analises": 2}]) == \
        "Relatório de gestão parcial: Em análise em 02/01/2026; 2 análise(s) registrada(s)."


def test_situacao_do_plano_com_a_execucao_ao_lado():
    """Consolidado e aba Federais: "CIENTE · Pago em parte" (achado (b))."""
    assert situacao_e_execucao("CIENTE", "Pago em parte") == "CIENTE · Pago em parte"
    assert situacao_e_execucao("CIENTE", None) == "CIENTE"
    assert situacao_e_execucao(None, "Pago") == "Pago"
    assert situacao_e_execucao("", "") == ""


def test_a_tela_mostra_o_mesmo_rotulo():
    fonte = (RAIZ.parent / "frontend" / "src" / "components" / "emendas"
             / "AbaParlamentares.tsx").read_text(encoding="utf-8")
    assert "{pa.execucao}" in fonte
    assert "brlOuTraco(pa.valor_pago)" in fonte


def test_cada_estado_tem_rotulo_e_nao_ha_rotulo_orfao():
    assert set(ROTULOS) == {"pago", "pago_parte", "empenhado", "sem_empenho",
                            "sem_pagamento", "nao_consultada"}
    # O rótulo do não medido não pode soar como fato sobre o dinheiro.
    assert "não consultada" in ROTULOS["nao_consultada"]
