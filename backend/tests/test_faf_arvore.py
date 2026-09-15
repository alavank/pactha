"""A ÁRVORE DO PLANO do Fundo a Fundo, as CONTAS e os BENEFICIÁRIOS (15/09/2026).

As respostas em `fixtures/faf_arvore.json` são REAIS: capturadas de
`api-publica.transferegov.gestao.gov.br/fundoafundo` em 15/09/2026, passando pelo
próprio `arvore_do_plano` + `conta_completa`. Os alvos:

  22557 — Nova Palma/RS (MinC, Aldir Blanc): meta M1, 7 registros de histórico,
          conta BB 2352-11650 com saldo de R$ 4.683,01 e 7 pagamentos por TED.
  6811 e 6954 — Goiânia/GO (SINE): os DOIS usam as contas 1126-8216 e 1126-8217.
  545   — Goiânia/GO: conta "0086-0", plano sem conta aberta.
  7523  — Palmas/TO: OB emitida em lote com subtransações, OB cancelada e a
          devolução ao Tesouro por GRU.

E os beneficiários de programa de Goiânia e Palmas, com os entes do ESTADO
sediados na capital.
"""
import copy
import inspect
import json
import os

from ingestion import faf_planos as fp
from ingestion.faf_planos import (
    _filhos, arvore_do_plano, classifica_lancamento, cnpjs_do_municipio,
    conta_aberta, conta_completa, ente_municipal, fatora, grava_beneficiarios_do_municipio,
    linha_beneficiario, linha_programa, resumo_da_conta, resumo_do_plano, saldo_da_conta,
)

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "faf_arvore.json")
with open(_FIXTURE, encoding="utf-8") as _f:
    _CAPTURA = json.load(_f)
R = _CAPTURA["respostas"]


def _plano(pid):
    return copy.deepcopy(_CAPTURA["alvos"][str(pid)]["plano"])


def _chave(url: str, params: dict | None) -> str:
    caminho = url.rsplit("/fundoafundo/", 1)[-1]
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

    def __init__(self, falhar=(), trocar=None):
        self.respostas = copy.deepcopy(R)
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
    monkeypatch.setattr(fp, "RETRY_S", 0)
    monkeypatch.setattr(fp, "PAUSA_S", 0)


def _tudo(pid, cli=None):
    """Árvore + contas + resumo, como a fase 2 faz."""
    cli = cli or _Replay()
    arv = arvore_do_plano(cli, _plano(pid))
    contas = {c["id_agencia_conta"]: conta_completa(cli, c) for c in arv["contas"]}
    arv["_resumo"] = resumo_do_plano(arv, {k: (v or {}).get("resumo") or {}
                                           for k, v in contas.items()})
    return arv, contas


# ---------------------------------------------------------------------------
# A árvore inteira
# ---------------------------------------------------------------------------
def test_a_arvore_da_22557_vem_inteira():
    a = arvore_do_plano(_Replay(), _plano(22557))
    assert a is not None
    assert a["metas"][0]["numero_meta_plano_acao"] == "M1"
    assert a["metas"][0]["acoes"][0]["numero_acao_meta_plano_acao"] == "A1.1"
    assert a["destinacao"][0]["codigo_natureza_despesa_destinacao_recursos_plano_acao"] == 300000
    assert len(a["historico"]) == 7
    assert a["historico"][0]["data_historico_plano_acao"] == "2025-04-22"
    assert all(an["responsaveis"] for an in a["analises"])          # quem analisou
    assert a["termos_adesao"][0]["numero_processo_termo_adesao"] == "01400.022831/2024-78"
    assert len(a["termos_adesao"][0]["historico"]) == 3
    assert a["contas"][0]["id_agencia_conta"] == "2352-11650"
    assert a["relatorios"] == [] and a["empenhos"] == []            # respondido e vazio


def test_o_relatorio_traz_o_percentual_fisico_por_acao_e_o_parecer():
    """⭐ A análise de resultado: quanto de cada ação da meta foi executado,
    e o parecer do ministério sobre a prestação de contas, com o analista."""
    a = arvore_do_plano(_Replay(), _plano(7523))
    rel = a["relatorios"][0]
    assert rel["acoes"][0]["percentual_execucao_fisica_acao_relatorio_gestao_acao"] == 100.0
    ids_acoes_meta = {ac["id_acao_meta_plano_acao"] for m in a["metas"] for ac in m["acoes"]}
    assert rel["acoes"][0]["id_acao_meta_plano_acao"] in ids_acoes_meta   # casa com a meta
    assert rel["analises"] and rel["analises"][0]["responsaveis"]


def test_o_saldo_vem_do_campo_aninhado_e_nao_do_nome_do_openapi():
    """O openapi publica `saldo_final_conta_plano_acao_dado_bancario`; o que
    chega é `saldo_final_dado_bancario.saldo_final_gestao_financeira`."""
    conta = R["planos-acao-dados-bancarios?id_plano_acao=22557"]["data"][0]
    assert "saldo_final_conta_plano_acao_dado_bancario" not in conta
    assert saldo_da_conta(conta) == 4683.01
    # o dia em que a fonte alinhar com o proprio Swagger, nada zera
    assert saldo_da_conta({"saldo_final_conta_plano_acao_dado_bancario": 10.5}) == 10.5
    assert saldo_da_conta({"saldo_final_dado_bancario": None}) is None


# ---------------------------------------------------------------------------
# A conta: extrato, quem recebeu, e o que NÃO é pagamento
# ---------------------------------------------------------------------------
def test_nova_palma_pagou_os_sete_beneficiarios_por_ted():
    """R$ 55.543,38 entraram por OB em 04/03/2026 e saíram em 7 pagamentos
    identificados (associações culturais e pessoas) — o que só se via logado."""
    _, contas = _tudo(22557)
    r = contas["2352-11650"]["resumo"]
    assert r["recebido_ob"] == 55543.38
    assert r["pago_a_beneficiarios"] == 55543.38 and r["n_beneficiarios"] == 7
    assert r["nao_classificado"] == 0.0 and r["n_nao_classificado"] == 0
    assert r["devolvido_uniao"] == 0.0
    assert r["ultimo_lancamento"] == "2026-08-31"


def test_credito_menos_debito_da_zero_por_isso_o_saldo_e_o_da_fonte():
    """⚠️ O dinheiro vai para a aplicação automática: na conta corrente, crédito
    menos débito dá zero. O saldo verdadeiro (R$ 4.683,01) é o que a fonte informa."""
    lancs = R["gestao-financeira-lancamentos?id_agencia_conta=2352-11650"]["data"]
    cred = sum(l["valor_lancamento_gestao_financeira"] for l in lancs
               if l["tipo_operacao_gestao_financeira"] == "C")
    deb = sum(l["valor_lancamento_gestao_financeira"] for l in lancs
              if l["tipo_operacao_gestao_financeira"] == "D")
    assert round(cred - deb, 2) == 0.0
    arv, _ = _tudo(22557)
    assert arv["_resumo"]["saldo_em_conta"] == 4683.01


def test_palmas_ob_em_lote_estorno_e_devolucao_ao_tesouro():
    """7523 (Palmas): a OB emitida em lote detalha cada beneficiário nas
    subtransações; a OB cancelada VOLTA (estorno); e a GRU para o Ministério da
    Fazenda é DEVOLUÇÃO À UNIÃO, não pagamento a beneficiário."""
    _, contas = _tudo(7523)
    r = contas["3615-6319"]["resumo"]
    assert r["recebido_ob"] == 2471591.42
    assert r["estornos"] == 71632.08
    assert r["devolvido_uniao"] == 26730.5
    # só subtransação "Pago": a "Cancelado" (a OB que voltou) e a "Outros" ficam
    # fora — 4 empresas de transporte, R$ 1.744.355,46
    assert r["pago_a_beneficiarios"] == 1744355.46 and r["n_beneficiarios"] == 4
    lancs = contas["3615-6319"]["lancamentos"]
    assert sum(len(l.get("subtransacoes") or []) for l in lancs) >= 6


def test_so_pede_subtransacao_de_lancamento_que_tem():
    cli = _Replay()
    conta = R["planos-acao-dados-bancarios?id_plano_acao=7523"]["data"][0]
    ext = conta_completa(cli, conta)
    com = [l for l in ext["lancamentos"]
           if (l.get("quantidade_subtransacoes_lancamento_gestao_financeira") or 0) > 0]
    pedidas = [c for c in cli.chamadas if c.startswith("gestao-financeira-subtransacoes")]
    assert len(pedidas) == len(com) == 4


def test_conta_zero_e_plano_sem_conta_e_nao_vai_a_fonte():
    """"0086-0": a fonte lista a linha com saldo nulo; não há extrato a pedir."""
    assert conta_aberta("0086-0") is False and conta_aberta("3615-0") is False
    assert conta_aberta("2352-11650") is True and conta_aberta("") is False
    cli = _Replay()
    arv, contas = _tudo(545, cli)
    assert contas["0086-0"] == {"cabecalho": None, "lancamentos": None, "resumo": None}
    assert not any(c.startswith("gestao-financeira") for c in cli.chamadas)
    assert arv["_resumo"]["saldo_em_conta"] is None
    assert arv["_resumo"]["n_contas"] == 1 and arv["_resumo"]["n_contas_abertas"] == 0


def test_lancamento_de_outro_banco_nao_entra_no_extrato():
    """`id_agencia_conta` não tem o banco: o filtro em memória separa."""
    k = "gestao-financeira-lancamentos?id_agencia_conta=2352-11650"
    dados = copy.deepcopy(R[k]["data"])
    dados[0]["codigo_banco_gestao_financeira"] = "104"
    cli = _Replay(trocar={k: _envelope(dados)})
    conta = R["planos-acao-dados-bancarios?id_plano_acao=22557"]["data"][0]
    assert conta_completa(cli, conta)["resumo"]["n_lancamentos"] == len(dados) - 1


def test_os_campos_da_conta_sobem_para_o_cabecalho_sem_perda():
    cli = _Replay()
    conta = R["planos-acao-dados-bancarios?id_plano_acao=22557"]["data"][0]
    ext = conta_completa(cli, conta)
    cab = ext["cabecalho"]
    assert cab["cnpj_ente_solicitante_gestao_financeira"] == "88488358000156"
    assert cab["id_agencia_conta"] == "2352-11650"
    assert all("id_agencia_conta" not in l for l in ext["lancamentos"])
    # sem perda: cabeçalho + lançamento remontam o original
    orig = R["gestao-financeira-lancamentos?id_agencia_conta=2352-11650"]["data"]
    assert [{**cab, **l} for l in ext["lancamentos"]] == orig


def test_fatora_deixa_no_item_o_campo_que_varia():
    cab, itens = fatora([{"a": 1, "b": 1}, {"a": 1, "b": 2}, {"a": 1}], ("a", "b"))
    assert cab == {"a": 1}
    assert itens == [{"b": 1}, {"b": 2}, {}]
    assert fatora([], ("a",)) == ({}, [])


def test_o_acento_comido_do_extrato_nao_escapa_da_regra():
    """"Emisso de Ordem Bancria" e "Resgate Automtico" (medidos) caem na mesma
    categoria da grafia certa."""
    def c(desc, tipo):
        return classifica_lancamento({"descricao_gestao_financeira": desc,
                                      "tipo_operacao_gestao_financeira": tipo})
    assert c("Emisso de Ordem Bancria", "D") == c("Emissão de Ordem Bancária", "D") == "saida"
    assert c("Resgate Automtico", "C") == c("Resgate Automático", "C") == "interno"
    assert c("Aplicao em BB Fix", "D") == "interno"
    assert c("Transferido para Poupana", "D") == "interno"
    assert c("Ordem Bancria", "C") == "recebido_ob"
    assert c("ORDEM BANC CANCELADA", "C") == "estorno"
    assert c("TED Devolvida", "C") == "estorno"
    assert c("Pix Recebido", "C") == "outro_credito"
    assert c("Impostos", "D") == "saida"
    # os dois que a carga real de Santa Maria (15/09/2026) mostrou não classificados
    assert c("Depsito Online", "C") == c("Depósito Online", "C") == "outro_credito"
    assert c("Devolução Cheque Depositado", "D") == "saida"


def test_descricao_desconhecida_e_contada_e_nao_some():
    r = resumo_da_conta([
        {"descricao_gestao_financeira": "Estorno de Tarifa Especial XPTO",
         "tipo_operacao_gestao_financeira": "C", "valor_lancamento_gestao_financeira": 9.9},
        {"descricao_gestao_financeira": "Coisa Nova do Banco",
         "tipo_operacao_gestao_financeira": "D", "valor_lancamento_gestao_financeira": 1.0},
    ])
    assert r["n_nao_classificado"] == 1 and r["nao_classificado"] == 1.0
    assert r["descricoes_nao_classificadas"] == ["Coisa Nova do Banco"]
    assert r["estornos"] == 9.9


def test_transferencia_para_o_proprio_ente_e_aplicacao_nao_sao_beneficiario():
    base = {"tipo_operacao_gestao_financeira": "D", "tipo_favorecido_gestao_financeira": 2,
            "valor_lancamento_gestao_financeira": 100.0,
            "cnpj_ente_solicitante_gestao_financeira": "88488358000156"}
    r = resumo_da_conta([
        {**base, "descricao_gestao_financeira": "Transferência enviada",
         "doc_favorecido_gestao_financeira_mask": "88488358000156"},
        {**base, "descricao_gestao_financeira": "BB-APLIC C.PRZ-APL.AUT",
         "doc_favorecido_gestao_financeira_mask": "00000000000191"},
    ])
    assert r["pago_a_beneficiarios"] == 0.0 and r["n_beneficiarios"] == 0
    assert r["saidas"] == 100.0 and r["movimento_interno"] == 100.0


# ---------------------------------------------------------------------------
# ⚠️ A CONTA DIVIDIDA — 6811 e 6954 usam as mesmas duas contas
# ---------------------------------------------------------------------------
def test_os_dois_planos_de_goiania_usam_as_mesmas_contas():
    c1 = {c["id_agencia_conta"] for c in arvore_do_plano(_Replay(), _plano(6811))["contas"]}
    c2 = {c["id_agencia_conta"] for c in arvore_do_plano(_Replay(), _plano(6954))["contas"]}
    assert c1 == c2 == {"1126-8216", "1126-8217"}


class _Cur:
    def __init__(self):
        self.sqls: list[tuple[str, object]] = []
        self._fila = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sqls.append((s, params))
        if s.startswith("SELECT p.id, p.municipio_id"):
            self._fila = [(1, 7, "6811", _plano(6811)), (2, 7, "6954", _plano(6954))]

    def fetchall(self):
        f, self._fila = self._fila, []
        return f


class _Conn:
    def commit(self):
        pass

    def rollback(self):
        pass


def test_a_conta_dividida_sai_uma_vez_por_rodada_e_leva_os_dois_planos():
    """⚠️ Buscar o extrato por plano repetiria 1126-8216 cinco vezes em Goiânia —
    e somar o saldo por plano DOBRARIA o dinheiro. A conta sai UMA vez; o
    segundo plano só se soma a `planos`."""
    cli, cur = _Replay(), _Cur()
    det = fp.run_detalhe(cli, _Conn(), cur, budget_s=600)
    assert det["atualizados"] == 2 and det["falhas"] == 0 and det["contas"] == 2
    assert cli.chamadas.count("gestao-financeira-lancamentos?id_agencia_conta=1126-8216") == 1
    ins = [p for s, p in cur.sqls if s.startswith("INSERT INTO faf_contas")]
    assert sorted(p["idc"] for p in ins) == ["1126-8216", "1126-8217"]
    assert all(p["plano"] == "6811" for p in ins)
    so = [p for s, p in cur.sqls if s.startswith("UPDATE faf_contas SET planos = (SELECT")]
    assert sorted(p[2] for p in so) == ["1126-8216", "1126-8217"]
    assert all(p[0] == "6954" for p in so)
    # e o relatorio da arvore vai para a coluna que o router e o MCP ja leem
    upd = [p for s, p in cur.sqls if s.startswith("UPDATE faf_planos_acao SET detalhe")]
    assert len(upd) == 2 and json.loads(upd[0][1])[0]["id_relatorio_gestao"] == 1258


def test_o_saldo_do_plano_e_o_das_contas_dele():
    arv, _ = _tudo(6811)
    assert arv["_resumo"]["saldo_em_conta"] == round(1733911.76 + 476442.82, 2)


# ---------------------------------------------------------------------------
# ⚠️ TUDO OU NADA, e o teto nas consultas filhas
# ---------------------------------------------------------------------------
def test_uma_consulta_sem_resposta_anula_a_arvore(monkeypatch):
    _sem_esperas(monkeypatch)
    cli = _Replay(falhar={"planos-acao-analises-responsaveis?id_analise_plano_acao=31864"})
    assert arvore_do_plano(cli, _plano(22557)) is None


def test_extrato_sem_resposta_nao_grava_o_plano(monkeypatch):
    _sem_esperas(monkeypatch)
    cli = _Replay(falhar={"gestao-financeira-lancamentos?id_agencia_conta=1126-8217"})
    cur = _Cur()
    det = fp.run_detalhe(cli, _Conn(), cur, budget_s=600)
    assert det["atualizados"] == 0 and det["falhas"] == 2
    assert not any(s.startswith(("INSERT INTO faf_contas", "UPDATE faf_planos_acao"))
                   for s, _ in cur.sqls)


def test_subtransacao_sem_resposta_anula_a_conta(monkeypatch):
    _sem_esperas(monkeypatch)
    k = "gestao-financeira-subtransacoes?id_lancamento_gestao_financeira=844187"
    conta = R["planos-acao-dados-bancarios?id_plano_acao=7523"]["data"][0]
    assert conta_completa(_Replay(falhar={k}), conta) is None


def test_pagina_do_meio_faltando_tambem_anula(monkeypatch):
    _sem_esperas(monkeypatch)
    k = "planos-acao-historico?id_plano_acao=22557"
    duas = {**R[k], "total_pages": 2}

    class _SegundaCai(_Replay):
        def get(self, url, params=None, headers=None, timeout=None):
            if _chave(str(url), params) == k and (params or {}).get("pagina") == 2:
                return _Resp(None, 500)
            return super().get(url, params=params)

    assert arvore_do_plano(_SegundaCai(trocar={k: duas}), _plano(22557)) is None


def test_filho_com_carga_nacional_anula_a_arvore():
    """⚠️ `relatorios-gestao-analises-responsaveis` com o nome de filtro errado
    devolve os 22.182 do Brasil (medido). O teto pega qualquer rota assim."""
    k = "planos-acao-historico?id_plano_acao=22557"
    cli = _Replay(trocar={k: _envelope([{"x": 1}], total=183910, paginas=920)})
    assert arvore_do_plano(cli, _plano(22557)) is None
    assert cli.chamadas.count(k) == 1


def test_extrato_com_carga_nacional_anula_a_conta():
    """1.149.632 lançamentos no Brasil para um teto de 20.000."""
    k = "gestao-financeira-lancamentos?id_agencia_conta=2352-11650"
    cli = _Replay(trocar={k: _envelope([{"x": 1}], total=1149632, paginas=5749)})
    conta = R["planos-acao-dados-bancarios?id_plano_acao=22557"]["data"][0]
    assert conta_completa(cli, conta) is None


def test_parametro_nulo_nao_vai_para_a_rede():
    cli = _Replay()
    assert _filhos(cli, "planos-acao-metas-acoes", {"id_meta_plano_acao": None}) == []
    assert _filhos(cli, "gestao-financeira-lancamentos", {"id_agencia_conta": ""}) == []
    assert cli.chamadas == []


def test_toda_consulta_da_arvore_passa_pelo_teto():
    for f in (arvore_do_plano, conta_completa):
        fonte = inspect.getsource(f)
        assert "buscar(" not in fonte and "_filhos(" in fonte, f.__name__
    assert "teto_itens=teto or TETO_FILHOS" in inspect.getsource(_filhos)
    assert "teto=TETO_LANCAMENTOS" in inspect.getsource(conta_completa)


def test_a_retentativa_salva_um_soluco(monkeypatch):
    _sem_esperas(monkeypatch)
    k = "planos-acao-destinacao-recursos?id_plano_acao=22557"

    class _Soluca(_Replay):
        ja = False

        def get(self, url, params=None, headers=None, timeout=None):
            if _chave(str(url), params) == k and not self.ja:
                self.ja = True
                self.chamadas.append(k)
                return _Resp(None, 503)
            return super().get(url, params=params)

    cli = _Soluca()
    assert arvore_do_plano(cli, _plano(22557)) is not None
    assert cli.chamadas.count(k) == 2


# ---------------------------------------------------------------------------
# O resumo do plano
# ---------------------------------------------------------------------------
def test_o_resumo_da_22557():
    r = _tudo(22557)[0]["_resumo"]
    assert r["meta_principal"].startswith("Executar a Política Nacional Aldir Blanc")
    assert r["situacao_atual"] == "AUTORIZADO" and r["data_situacao"] == "2026-06-08"
    assert r["enviado_em"] == "2025-04-22"
    assert r["termo"] == {"situacao": "ASSINADO", "assinado_em": "2025-04-29"}
    assert r["relatorio"] is None and r["n_relatorios"] == 0
    assert r["pago_a_beneficiarios"] == 55543.38


def test_o_resumo_traz_o_ultimo_relatorio_com_o_percentual_fisico():
    r = _tudo(7523)[0]["_resumo"]
    assert r["relatorio"]["tipo"] == "FINAL"
    assert r["relatorio"]["situacao"] == "ENVIADO_ANALISE"
    assert r["relatorio"]["pct_fisico_medio"] == 100.0


# ---------------------------------------------------------------------------
# BENEFICIÁRIOS DE PROGRAMA — sem o estado sediado na capital
# ---------------------------------------------------------------------------
def _benefs(ibge):
    return copy.deepcopy(R[f"programas-beneficiarios?codigo_ibge_municipio_ente_beneficiario_programa={ibge}"]["data"])


def test_goiania_fica_so_com_o_municipio():
    """⚠️ Os beneficiários não têm campo de esfera. A consulta de Goiânia traz o
    ESTADO DE GOIAS, duas SECRETARIAS DE ESTADO e a DIRETORIA-GERAL DE POLICIA
    PENAL (estadual, sem "estado" no nome) — nenhum entra."""
    bs = _benefs(5208707)
    fica = [b for b in bs if ente_municipal(b, {"01612092000123"})]
    assert {b["cnpj_beneficiario_programa"] for b in fica} == {"01612092000123"}
    assert len(fica) == 16 and len(bs) == 62


def test_palmas_leva_a_filial_do_municipio_e_deixa_o_tocantins():
    bs = _benefs(1721000)
    fica = {b["cnpj_beneficiario_programa"] for b in bs if ente_municipal(b, {"24851511000185"})}
    assert fica == {"24851511000185", "24851511002200"}


def test_sem_plano_o_nome_decide():
    assert ente_municipal({"nome_ente_beneficiario_programa": "MUNICIPIO DE NOVA PALMA"}, set())
    assert ente_municipal({"nome_ente_beneficiario_programa": "Fundo Municipal de Cultura"}, set())
    assert not ente_municipal({"nome_ente_beneficiario_programa": "ESTADO DE GOIAS"}, set())
    assert not ente_municipal({"nome_ente_beneficiario_programa":
                               "SECRETARIA DE ESTADO DE ASSUNTOS MUNICIPAIS"}, set())


def test_os_cnpjs_saem_dos_beneficiarios_e_voltam_com_zero():
    assert cnpjs_do_municipio(_benefs(4313102)) == ["88488358000156"]
    assert cnpjs_do_municipio([{"cnpj_beneficiario_programa": "1612092000123"}]) == ["01612092000123"]
    assert cnpjs_do_municipio([{"cnpj_beneficiario_programa": None}]) == []


def test_linha_do_beneficiario():
    b = _benefs(4313102)[0]
    l = linha_beneficiario(7, b)
    assert l["mid"] == 7 and l["bid"] == b["id_beneficiario_programa"]
    assert l["cnpj"] == "88488358000156" and l["tipo"] == "ESPECIFICO"
    assert l["valor"] == b["valor_beneficiario_programa"]
    assert linha_beneficiario(7, {}) is None


class _CurFalso:
    def __init__(self):
        self.sqls = []

    def execute(self, sql, params=None):
        self.sqls.append((" ".join(sql.split())[:60], params))


def test_a_troca_do_conjunto_apaga_so_o_que_saiu_da_fonte():
    cur = _CurFalso()
    assert grava_beneficiarios_do_municipio(cur, 7, _benefs(4313102)) == 5
    sql, params = cur.sqls[0]
    assert sql.startswith("DELETE FROM faf_programas_beneficiarios WHERE municipio_id")
    assert params[0] == 7 and len(params[1]) == 5
    assert sum(1 for s, _ in cur.sqls if s.startswith("INSERT")) == 5


def test_municipio_sem_beneficiario_na_fonte_zera_o_conjunto():
    cur = _CurFalso()
    assert grava_beneficiarios_do_municipio(cur, 7, []) == 0
    assert len(cur.sqls) == 1
    sql, params = cur.sqls[0]
    assert sql.startswith("DELETE FROM faf_programas_beneficiarios WHERE municipio_id")
    assert params == (7,)


def test_beneficiarios_so_trocam_com_os_planos_todos_respondidos():
    """A raiz de CNPJ municipal sai dos planos: com um CNPJ sem resposta, o
    conjunto ficaria incompleto e apagaria beneficiário legítimo."""
    fonte = inspect.getsource(fp.ingest)
    assert "if planos_ok:" in fonte
    assert "grava_beneficiarios_do_municipio" in fonte.split("if planos_ok:")[1].split("else:")[0]


# ---------------------------------------------------------------------------
# O catálogo de programas
# ---------------------------------------------------------------------------
def test_catalogo_junta_o_programa_da_gestao_agil():
    cli = _Replay(trocar={
        "programas?": R["programas?id_programa=8"],
        "programas-gestao-agil?": R["programas-gestao-agil?id_programa=8"],
    })
    progs = fp.catalogo_de_programas(cli)
    assert len(progs) == 1 and progs[0]["gestao_agil"][0]["codigo_programa_agil"] == "71"
    l = linha_programa(progs[0])
    assert l["idp"] == 8 and l["sigla_orgao"] == "MinC"
    assert json.loads(l["gestao_agil"])[0]["nome_programa_agil"] == "SECULT-A BLANC-MUN"
    assert "gestao_agil" not in json.loads(l["raw"])


def test_catalogo_sem_resposta_e_None(monkeypatch):
    _sem_esperas(monkeypatch)
    cli = _Replay(falhar={"programas-gestao-agil?"},
                  trocar={"programas?": R["programas?id_programa=8"]})
    assert fp.catalogo_de_programas(cli) is None


# ---------------------------------------------------------------------------
# A migration e o teto da tarefa
# ---------------------------------------------------------------------------
def test_a_migration_e_valida_idempotente_e_depois_da_tabela():
    import pglast

    from services.startup import MIGRATION_FILES
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sql = open(os.path.join(raiz, "migrations", "add_faf_detalhe.sql"),
               encoding="utf-8").read()
    pglast.parse_sql(sql)
    assert "ADD COLUMN IF NOT EXISTS detalhe " in sql
    for t in ("faf_contas", "faf_programas_beneficiarios", "faf_programas"):
        assert f"CREATE TABLE IF NOT EXISTS {t}" in sql
    assert MIGRATION_FILES.index("add_faf_detalhe.sql") > \
        MIGRATION_FILES.index("add_faf_planos_acao.sql")
    assert MIGRATION_FILES.index("add_faf_detalhe.sql") < \
        MIGRATION_FILES.index("add_auditoria_imutavel.sql")


def test_as_colunas_das_linhas_batem_com_os_upserts():
    import re
    conta = R["planos-acao-dados-bancarios?id_plano_acao=22557"]["data"][0]
    ext = conta_completa(_Replay(), conta)
    pares = [
        (fp._SQL_CONTA, fp.linha_conta(7, "22557", conta, ext)),
        (fp._SQL_BENEF, linha_beneficiario(7, _benefs(4313102)[0])),
        (fp._SQL_PROGRAMA, linha_programa(R["programas?id_programa=8"]["data"][0])),
    ]
    for sql, linha in pares:
        assert set(re.findall(r"%\((\w+)\)s", sql)) == set(linha), sql[:40]


def test_o_teto_da_tarefa_cabe_no_kill_da_task():
    """Default casado com o `timeout -k 30 1200` da task em 15/09/2026."""
    assert fp.TETO_TAREFA_S + 60 <= 1200
    assert max(60.0, min(fp.BUDGET_S, fp.TETO_TAREFA_S - fp.DET_MIN_S)) + fp.DET_MIN_S \
        <= fp.TETO_TAREFA_S


def test_a_data_da_fonte_vai_para_a_chave_do_fundo_a_fundo():
    assert "'transferegov_fundoafundo'" in inspect.getsource(fp._grava_data_da_fonte)
