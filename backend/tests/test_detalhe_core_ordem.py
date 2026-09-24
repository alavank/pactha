"""`detalhe_core` lê as linhas por ÍNDICE — e aqui a linha é montada NA ORDEM
DO SELECT (24/09/2026).

Achado (c) da revisão do 97e4903: o teste de lá conferia TEXTO ("te.pagamentos"
vem depois de "COALESCE(te.valor_investimento, 0)"), não COMPORTAMENTO. Trocar
`te.pagamentos` e `te.detalhe->'empenhos'` de lugar no SELECT passava por ele, e
em produção o plano pago em parte viraria «Execução não consultada» em silêncio.

Aqui o banco falso lê o SQL que `detalhe_core` realmente manda, separa a lista do
SELECT (nível 0, fora de parênteses e aspas) e devolve cada linha com os valores
POSTOS NA POSIÇÃO DA EXPRESSÃO. Se o SELECT mudar de ordem e o `r[N]` do laço
não, o valor errado cai no lugar errado e as asserções abaixo reprovam.

O plano de ação é o 91573 da CAPTURA REAL da API (`fixtures/te_especiais_arvore.
json`), gravado pelo MESMO `pagamentos_da_arvore` da produção: R$ 205.066,16
pagos em 22/06/2026 e o resto em minuta — "Pago em parte".
"""
import asyncio
import re

import pytest

from ingestion.transferegov_te import pagamentos_da_arvore
import routers.parlamentares as P
from tests.test_te_arvore import PLANO_91573, _arvore


def _select(sql: str) -> tuple[list[str], str]:
    """(expressões do SELECT de nível 0, normalizadas e sem `AS apelido`;
    tabela do FROM de nível 0)."""
    s = str(sql)
    j = re.search(r"\bSELECT\b", s, re.I).end()
    exprs, cur, prof, aspas, tabela = [], "", 0, False, None
    while j < len(s):
        ch = s[j]
        if aspas:
            aspas = ch != "'"
        elif ch == "'":
            aspas = True
        elif ch == "(":
            prof += 1
        elif ch == ")":
            prof -= 1
        elif prof == 0 and ch == ",":
            exprs.append(cur)
            cur, j = "", j + 1
            continue
        elif prof == 0 and s[j - 1].isspace() and re.match(r"FROM\b", s[j:j + 5], re.I):
            exprs.append(cur)
            tabela = re.match(r"FROM\s+(\w+)", s[j:], re.I).group(1)
            break
        cur += ch
        j += 1
    return ([re.sub(r"\s+AS\s+\w+$", "", " ".join(e.split()), flags=re.I) for e in exprs],
            tabela)


class _Res:
    def __init__(self, linhas):
        self._l = linhas

    def fetchall(self):
        return self._l


class _DbNaOrdemDoSelect:
    """`valores[consulta]` = {expressão: valor}. Chave começando com "~" casa por
    TRECHO (para as subconsultas longas). Toda chave tem de casar com uma
    expressão do SELECT — senão o teste estaria conferindo nada."""

    def __init__(self, valores: dict):
        self.valores = valores
        self.usadas: set = set()

    @staticmethod
    def _consulta(exprs, tabela):
        if tabela == "convenios_estadual":
            return "fns" if any("linhaPropostas" in e for e in exprs) else "sigcon"
        return {"transferegov_propostas": "vol", "emendas_estaduais": "emendas",
                "transferegov_te": "te", "transferegov_pac": "pac",
                "emendas_federais_carteira": "ef"}[tabela]

    async def execute(self, sql, params=None):
        exprs, tabela = _select(sql)
        nome = self._consulta(exprs, tabela)
        vals = self.valores.get(nome)
        if vals is None:
            return _Res([])
        linha = []
        for e in exprs:
            casou = [k for k in vals if k == e or (k.startswith("~") and k[1:] in e)]
            assert len(casou) <= 1, f"{nome}: {e!r} casou {casou}"
            linha.append(vals[casou[0]] if casou else None)
            self.usadas.update((nome, k) for k in casou)
        return _Res([tuple(linha)])

    def todas_usadas(self):
        return {(n, k) for n, v in self.valores.items() for k in v} - self.usadas


def _valores():
    arv = _arvore(PLANO_91573)
    fins = [f for ex in arv["executores"] for f in ex["finalidades"]]
    return {
        "te": {
            "te.plano_acao_id": 91573, "te.municipio_id": 2, "m.nome": "Araújos",
            "te.codigo": "09032026-091573", "te.emenda": "202627620003-LUIS TIBÉ",
            "te.parlamentar": "LUIS TIBÉ", "te.objeto": "Pavimentação Urbana",
            "te.situacao": "CIENTE",
            "COALESCE(te.valor_total, 0)": 398000.0,
            "COALESCE(te.valor_custeio, 0)": 0.0,
            "COALESCE(te.valor_investimento, 0)": 398000.0,
            "te.pagamentos": pagamentos_da_arvore(arv, 398000.0),
            "te.detalhe->'empenhos'": arv["empenhos"],
            "(te.detalhe IS NOT NULL)": True,
            "te.pagamentos_atualizado_em": None,
            "te.programa_codigo": "09032026",
            "~nome_orgao_programa": arv["programa"]["nome_orgao_programa"],
            "~relatorios_gestao_novos": [],
            "~jsonb_array_length(te.detalhe->'relatorios_gestao')": 0,
            "~objeto_executor": [ex["objeto_executor"] for ex in arv["executores"]],
            "~cd_area_politica_publica_tipo_pt": [f["cd_area_politica_publica_tipo_pt"] for f in fins],
            "~finalidades[*].cd_area_politica_publica_pt'": [f["cd_area_politica_publica_pt"] for f in fins],
            "~codigo_descricao_areas": PLANO_91573["codigo_descricao_areas_politicas_publicas_plano_acao"],
        },
        "vol": {
            "v.id": 1, "v.municipio_id": 2, "~FROM municipios": "Araújos",
            "v.numero_proposta": "034595/2025", "v.codigo_instrumento": "981397",
            "v.objeto": "PAVIMENTACAO", "v.situacao": "Em execução",
            "v.valor_global": 350000.0, "v.valor_repasse": 350000.0,
            "v.parlamentar": "LUIS TIBE", "v.orgao": "MINISTERIO DAS CIDADES",
            "v.ops_obs_aberto": {"valor_desembolsado": 100000.0,
                                 "valor_a_desembolsar": 250000.0,
                                 "data_ultimo_desembolso": "10/03/2026", "obs": []},
            # A RASPAGEM com números DIFERENTES do dump (achado 8 da revisão do
            # 248361f): sem ela, trocar `ops_obs_aberto` e `ops_obs` de lugar no
            # SELECT passava — `ops_obs_preferido(None, dump)` devolve o dump.
            "v.ops_obs": {"valor_desembolsado": 350000.0, "valor_a_desembolsar": 0.0,
                          "data_ultimo_desembolso": "01/02/2026", "obs": []},
            "v.detalhe": {"Número da Proposta Novo PAC - Seleção": "56000004633/2025"},
        },
        "emendas": {
            "e.id": 3, "e.municipio_id": 2, "e.nr_indicacao": "2024/123", "e.ano": 2024,
            "e.valor_indicacao": 500000.0, "e.nome_responsavel": "LUIS TIBE",
            "e.valor_empenhado": 500000.0, "e.valor_pago": 100000.0,
            "e.grupo_despesa": "Investimento",
        },
        "sigcon": {
            "c.id": 4, "c.municipio_id": 2, "c.nr_sigcon": "1301234",
            "c.valor_total": 500000.0, "c.orgao_concedente": "SEINFRA",
            "c.raw_data->>'nr_indicacao'": "2024/123",
            "c.raw_data->'indicacoes'": [{"nr_indicacao": "2024/124"}],
        },
        "fns": {
            "c.id": 5, "c.municipio_id": 2, "c.ano": 2025,
            "c.raw_data->'linhaPropostas'": [{
                "nuProposta": "36000679587202500", "vlProposta": 450000.0,
                "vlPago": 450000.0, "vlPagar": 0.0, "data_pagamento": "18/11/2025",
                "parlamentares": [{"noApelidoPolitico": "LUIS TIBÉ"}]}],
            "c.raw_data->>'coTipoProposta'": "INCREMENTO MAC",
            "c.raw_data->>'dsTipoRecurso'": "MAC",
        },
        "pac": {"id": 6, "municipio_id": 2, "numero_proposta": "56000004633/2025",
                "situacao": "Selecionada", "valor_total": 900000.0,
                "emenda_parlamentar": "LUIS TIBE", "programa_codigo": "5600020250001"},
        "ef": {"ef.id": 7, "ef.municipio_id": 2, "ef.codigo_emenda": "202627620009",
               "COALESCE(ef.valor_repasse_emenda, 0)": 10.0, "ef.orgao_siafi": "36000"},
    }


def _detalhe(valores=None):
    db = _DbNaOrdemDoSelect(valores or _valores())
    det = asyncio.run(P.detalhe_core(db, "LUIS TIBE", [2], None))
    assert db.todas_usadas() == set(), "chave do teste que não casou com o SELECT"
    return det


def test_plano_pago_em_parte_sai_pago_em_parte():
    (pa,) = _detalhe()["plano_acao"]
    assert pa["execucao"] == "Pago em parte"
    assert pa["valor_pago"] == 205066.16
    assert pa["dt_ultimo_pagamento"] == "22/06/2026"
    assert pa["valor_empenhado"] == 398000.0


def test_as_colunas_novas_da_te_caem_no_lugar():
    (pa,) = _detalhe()["plano_acao"]
    # O órgão do programa 25 na captura real — NÃO é o Ministério da Fazenda.
    assert pa["orgao_programa"] == "Ministério da Gestão e da Inovação em Serviços Públicos"
    assert pa["ano"] == 2026
    assert pa["funcoes"] == [[15, 451]]
    assert pa["objetos_executor"][0].startswith("Execução de obras de pavimentação")
    # A árvore foi lida, o plano já recebeu dinheiro e as duas listas de
    # relatório vieram vazias (é o que a captura real do 91573 tem): fato medido.
    assert pa["relatorio_gestao"] == "Nenhum relatório de gestão registrado."


def test_o_relatorio_de_gestao_cai_no_lugar():
    """Achado 9 da revisão do 248361f: com a lista nova VAZIA e a contagem antiga
    ZERO, trocar r[17] e r[18] dava a mesma frase ("Nenhum relatório...") e
    passava. Com o relatório real do plano 67457 (captura de 14/09/2026: Final,
    Disponibilizado, 30/12/2025, sem análise) e a lista antiga NÃO vazia, só a
    ordem certa dá a frase."""
    vals = _valores()
    vals["te"]["~relatorios_gestao_novos"] = [
        {"tipo": "Final", "situacao": "Disponibilizado", "data": "2025-12-30", "analises": 0}]
    vals["te"]["~jsonb_array_length(te.detalhe->'relatorios_gestao')"] = 2
    (pa,) = _detalhe(vals)["plano_acao"]
    assert pa["relatorio_gestao"] == ("Relatório de gestão final: Disponibilizado em "
                                      "30/12/2025; nenhuma análise registrada.")
    assert pa["relatorios_gestao"][0]["situacao"] == "Disponibilizado"


def test_a_contagem_da_lista_antiga_cai_no_lugar():
    """A lista nova vazia e a ANTIGA com 2 itens: há relatório (em formato que
    não se lê), então nada de "Nenhum relatório de gestão registrado". Ler a
    contagem da coluna errada (a lista nova, vazia = 0) afirmaria a ausência."""
    vals = _valores()
    vals["te"]["~jsonb_array_length(te.detalhe->'relatorios_gestao')"] = 2
    (pa,) = _detalhe(vals)["plano_acao"]
    assert pa["execucao_estado"] == "pago_parte"      # já recebeu dinheiro
    assert pa["relatorio_gestao"] == ""


def test_o_desembolso_do_dump_vence_a_raspagem():
    """`ops_obs_aberto` (dump) e `ops_obs` (raspagem) com números DIFERENTES:
    valem os do dump (`ops_obs_preferido`, a regra do RM). A troca das duas
    colunas no SELECT reprova aqui."""
    (v,) = _detalhe()["voluntarias"]
    assert (v["valor_desembolsado"], v["valor_a_desembolsar"], v["dt_ultimo_desembolso"]) == (
        100000.0, 250000.0, "10/03/2026")
    assert v["desembolso_consultado"] is True


def test_as_colunas_novas_das_outras_fontes_caem_no_lugar():
    det = _detalhe()
    (v,) = det["voluntarias"]
    assert v["valor_desembolsado"] == 100000.0 and v["valor_a_desembolsar"] == 250000.0
    assert v["dt_ultimo_desembolso"] == "10/03/2026"
    assert v["pac_origem"] == "56000004633/2025"
    (e,) = det["emendas"]
    assert (e["valor_empenhado"], e["valor_pago"]) == (500000.0, 100000.0)
    assert e["grupo_despesa"] == "Investimento"
    (c,) = det["sigcon"]
    assert c["indicacoes"] == ["2024/123", "2024/124"] and c["orgao"] == "SEINFRA"
    (f,) = det["fns"]
    assert (f["tipo_proposta"], f["tipo_recurso"]) == ("INCREMENTO MAC", "MAC")
    assert (f["vl_pago"], f["vl_pagar"], f["data_pagamento"]) == (450000.0, 0.0, "18/11/2025")
    (p,) = det["pac"]
    assert p["programa_codigo"] == "5600020250001"
    (ef,) = det["emendas_federais"]
    assert ef["orgao_siafi"] == "36000"


def test_o_parser_do_teste_separa_o_select_de_verdade():
    """O dublê só prova alguma coisa se ler o SELECT direito."""
    exprs, tab = _select("SELECT a, COALESCE(b, 0), (SELECT x FROM y WHERE z=1) AS n, "
                         "f(c, 'd,e') FROM t WHERE 1=1")
    assert exprs == ["a", "COALESCE(b, 0)", "(SELECT x FROM y WHERE z=1)", "f(c, 'd,e')"]
    assert tab == "t"


def test_voluntaria_com_bloco_vazio_nao_conta_como_consultada():
    """`ops_obs` `{}` (ou sem o desembolsado) é NULO: o PDF não pode escrever
    "Nenhum pagamento registrado" de uma proposta que ninguém mediu."""
    for bloco in ({}, {"obs": []}):
        vals = _valores()
        vals["vol"]["v.ops_obs_aberto"] = bloco
        vals["vol"]["v.ops_obs"] = None       # e nenhuma raspagem por trás
        (v,) = _detalhe(vals)["voluntarias"]
        assert v["desembolso_consultado"] is False and v["valor_desembolsado"] is None


def test_indicacao_nula_nao_vira_zero():
    """NULO na planilha da SEGOV continua None — nunca "R$ 0 pago"."""
    vals = _valores()
    vals["emendas"]["e.valor_pago"] = None
    vals["emendas"]["e.valor_empenhado"] = None
    (e,) = _detalhe(vals)["emendas"]
    assert e["valor_pago"] is None and e["valor_empenhado"] is None


# ---------------------------------------------------------------------------
# FNS: UMA linha por (município, proposta), com a PARTE do autor
# ---------------------------------------------------------------------------
# Achado 1 da revisão do 248361f: a proposta 36000679587202500 (R$ 450.000,
# paga) com o mesmo autor duas vezes virava duas linhas de R$ 450.000 — TOTAL
# R$ 900.000 e "RECURSOS PAGOS" no PDF.
def _parl(nome, emenda, parte=None):
    p = {"noApelidoPolitico": nome, "coEmendaPolitica": emenda, "nuAnoExercicio": 2025}
    if parte is not None:
        p["vlIndObjeto"] = parte
    return p


def _fns_450(parlamentares):
    return [{"nuProposta": "36000679587202500", "vlProposta": 450000.0,
             "vlPago": 450000.0, "vlPagar": 0.0, "data_pagamento": "18/11/2025",
             "parlamentares": parlamentares}]


def _com_fns(parlamentares):
    vals = _valores()
    vals["fns"]["c.raw_data->'linhaPropostas'"] = _fns_450(parlamentares)
    return vals


def test_fns_mesmo_autor_duas_vezes_e_uma_linha_de_450_mil():
    from services.relatorio_parlamentares import montar_bloco
    det = _detalhe(_com_fns([_parl("LUIS TIBÉ", "37080010", 250000.0),
                             _parl("LUIS TIBÉ", "37080011", 200000.0)]))
    (f,) = det["fns"]
    assert f["numero"] == "36000679587202500"
    assert f["valor_total"] == 450000.0 and f["valor_proposta"] == 450000.0
    b = montar_bloco("Luis Tibé", {"fns": det["fns"]}, "ARAÚJOS")
    assert b["total"] == 450000.0
    assert [len(a["linhas"]) for a in b["areas"]] == [1]
    # Pago de verdade (R$ 450 mil de R$ 450 mil): aqui "PAGOS" é fato.
    assert b["titulo"].startswith("RECURSOS PAGOS ARAÚJOS")


def test_fns_dois_autores_cada_bloco_com_a_sua_parte():
    vals = _com_fns([_parl("LUIS TIBÉ", "37080010", 250000.0),
                     _parl("NIKOLAS FERREIRA", "40200001", 200000.0)])
    (f,) = _detalhe(vals)["fns"]
    assert f["valor_total"] == 250000.0 and f["proponente"] == "LUIS TIBÉ"
    det = asyncio.run(P.detalhe_core(_DbNaOrdemDoSelect(vals), "NIKOLAS FERREIRA", [2], None))
    (f,) = det["fns"]
    assert f["valor_total"] == 200000.0 and f["proponente"] == "NIKOLAS FERREIRA"


class _DbFnsEmDuasLinhas(_DbNaOrdemDoSelect):
    """A MESMA proposta em duas linhas do FNS (o coletor grava por tipo/recurso)."""

    async def execute(self, sql, params=None):
        res = await super().execute(sql, params)
        exprs, tabela = _select(sql)
        if self._consulta(exprs, tabela) == "fns":
            return _Res(res.fetchall() * 2)
        return res


def test_fns_a_mesma_proposta_em_duas_linhas_nao_soma_duas_vezes():
    db = _DbFnsEmDuasLinhas(_valores())
    det = asyncio.run(P.detalhe_core(db, "LUIS TIBE", [2], None))
    (f,) = det["fns"]
    assert f["valor_total"] == 450000.0


def test_fns_em_duas_linhas_com_DOIS_autores_conta_a_parte_uma_vez_so():
    """Revisão de 24/09/2026: com um autor só, a parte = vlProposta e o teto
    escondia a soma dobrada — o `vistos` do detalhe_core podia sumir e nada
    reprovava. Com dois autores a parte (250 mil) é menor que a proposta."""
    vals = _com_fns([_parl("LUIS TIBÉ", "37080010", 250000.0),
                     _parl("NIKOLAS FERREIRA", "40200001", 200000.0)])
    det = asyncio.run(P.detalhe_core(_DbFnsEmDuasLinhas(vals), "LUIS TIBE", [2], None))
    (f,) = det["fns"]
    assert f["valor_total"] == 250000.0
    assert f["proponente"] == "LUIS TIBÉ"


def test_fns_vlIndObjeto_ZERO_conta_como_ausente():
    """A leitura da tela do FNS (`routers/fns.py`, com `or`): parte 0 não é parte.
    Contada, a proposta paga de 450 mil saía "RECURSOS PAGOS … TOTAL 0,00"."""
    det = _detalhe(_com_fns([_parl("LUIS TIBÉ", "37080010", 0.0)]))
    (f,) = det["fns"]
    assert f["valor_total"] == 450000.0


@pytest.mark.parametrize("parte_a,parte_b,esperado", [
    (250000.0, 200000.0, 450000.0),     # as duas partes que casaram a busca
    (None, None, 450000.0),             # sem vlIndObjeto: 450+450, teto na proposta
])
def test_fns_dois_autores_que_casam_a_busca_somam_ate_a_proposta(parte_a, parte_b, esperado):
    vals = _com_fns([_parl("LUIS TIBÉ", "37080010", parte_a),
                     _parl("LUIS SOUZA", "40200001", parte_b)])
    det = asyncio.run(P.detalhe_core(_DbNaOrdemDoSelect(vals), "LUIS", [2], None))
    (f,) = det["fns"]
    assert f["valor_total"] == esperado
    assert f["proponente"] == "LUIS TIBÉ, LUIS SOUZA"
