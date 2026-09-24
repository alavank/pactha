"""A EXECUÇÃO da Transferência Especial (Emenda Pix) — UMA leitura só (24/09/2026).

Pedido da Laiza (Nova Serrana/MG), no PDF de Parlamentares: "na situação dessa
transferência especial não tá falando se ela já foi paga, já foi empenhada, ou tá
aguardando pagamento, ela só tá na situação como CIENTE".

⚠️ CIENTE NÃO É ESTÁGIO DO DINHEIRO. `transferegov_te.situacao` é a situação do
PLANO DE AÇÃO, e só tem dois valores na base nacional (24/09/2026: 52.956 CIENTE e
4.871 IMPEDIDO). CIENTE = o município deu ciência, fechou o plano de trabalho e o
plano está ativo; o plano 91573 tem OB desde 22/06/2026 e continua CIENTE. O
dinheiro mora em outras duas colunas, que a tela e o PDF de Parlamentares não liam:

  - `pagamentos` (JSONB, formato `ops_obs`): documentos hábeis -> OP -> OB, gravado
    por `ingestion/transferegov_te.py::pagamentos_da_arvore`;
  - `detalhe->'empenhos'`: os empenhos da árvore oficial (`arvore_do_plano`).

⭐ UMA FONTE SÓ. O RM, a tela Parlamentares e o PDF de Parlamentares leem a
execução por AQUI: o RM pelo `texto_rm_te` (o mesmo texto que sempre escreveu), a
tela e o PDF pelo rótulo. O parser do dinheiro é o `_desembolso_ops_obs` do RM —
nenhuma segunda leitura de `pagamentos`.

⚠️ NULO NÃO É ZERO. `pagamentos` NULO = "ainda não consultado" (add_te_pagamentos.sql)
e vira «Execução não consultada», nunca «Sem empenho» nem R$ 0,00. E «Sem empenho»
só sai quando os EMPENHOS foram lidos (`detalhe` gravado): a SPA, fonte antiga dos
pagamentos, só lista documento hábil, e empenho sem documento hábil é invisível a
ela.

⚠️ MINUTA NÃO É DINHEIRO — nem de documento hábil (vai para `pendentes` no
coletor), nem de EMPENHO: a minuta de empenho vem com `numero_empenho` nulo e o
valor CHEIO (4.963 na base em 24/09/2026, uma de R$ 1.043.317). Somá-la inventaria
empenho.

⚠️ «PAGO» = ORDEM BANCÁRIA EMITIDA para a conta do município (a mesma regra do RM
e do coletor). A API pública não traz a data de crédito (`dtPagamento` vem sempre
nulo); a data do último pagamento é a de emissão da OB mais recente.

Função PURA e TOTAL: nunca levanta. Quem chama (`routers/parlamentares.py::
detalhe_core`) está dentro de um `try/except` que, se estourasse, apagaria a
seção inteira da Transferência Especial da tela, do PDF e do Consolidado.
"""
from __future__ import annotations

import unicodedata

# O parser do dinheiro é o do RM, importado e não copiado: a regra de "o que é
# desembolsado" existe num lugar só. ⚠️ O rm_builder importa ESTE módulo só
# DENTRO da função que monta o RM, para não fechar um ciclo de import.
from services.rm_builder import _desembolso_ops_obs, _fmt_brl, _jsonb

# Os estados, na ORDEM em que são decididos (ver `execucao_te`).
ROTULOS: dict[str, str] = {
    "pago": "Pago",
    "pago_parte": "Pago em parte",
    "empenhado": "Empenhado, aguardando pagamento",
    "sem_empenho": "Sem empenho",
    # Pagamentos lidos (nenhum documento hábil), empenhos NÃO lidos: o que se
    # sabe é que não houve pagamento — não que não haja empenho.
    "sem_pagamento": "Sem pagamento",
    "nao_consultada": "Execução não consultada",
}

# Situação de empenho que NÃO é empenho: minuta (a única vista na base nacional
# em 24/09/2026, além de "Enviado") e, por cautela, cancelado/anulado — contar
# um desses como empenhado seria afirmar dinheiro reservado que não está.
_NAO_E_EMPENHO = ("minuta", "cancel", "anulad")


def _sem_acento(s) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(s or ""))
                   if not unicodedata.combining(c)).casefold()


def _num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def empenho_real(emp) -> bool:
    """Empenho de verdade: tem NÚMERO e a situação não é minuta/cancelamento."""
    if not isinstance(emp, dict):
        return False
    if not str(emp.get("numero_empenho") or "").strip():
        return False
    sit = _sem_acento(emp.get("descricao_situacao_empenho"))
    return not any(t in sit for t in _NAO_E_EMPENHO)


def _vazio(estado: str) -> dict:
    return {"estado": estado, "rotulo": ROTULOS[estado], "consultada": False,
            "valor_empenhado": None, "valor_pago": None, "valor_a_pagar": None,
            "dt_ultimo_pagamento": None, "tem_documento_habil": False}


def execucao_te(pagamentos, empenhos=None, detalhe_coletado: bool = False) -> dict:
    """A execução de UM plano de ação.

    `pagamentos`: a coluna `transferegov_te.pagamentos` (dict ou str, conforme o
    driver). `empenhos`: `detalhe->'empenhos'` (lista, str ou None).
    `detalhe_coletado`: `detalhe IS NOT NULL` — só com ele os empenhos contam
    como LIDOS.

    Devolve {estado, rotulo, consultada, valor_empenhado, valor_pago,
    valor_a_pagar, dt_ultimo_pagamento, tem_documento_habil}. Valor que não foi
    medido sai None, nunca 0.
    """
    try:
        pg = _jsonb(pagamentos)
        # Dict vazio é tratado como NULO — a mesma leitura do RM (`_medido`).
        if not isinstance(pg, dict) or not pg:
            return _vazio("nao_consultada")
        des = _desembolso_ops_obs(pg) or {}
        pago = _num(des.get("valor_desembolsado"))
        tem_dh = bool(pg.get("obs") or pg.get("pendentes"))

        valor_empenhado = None
        n_empenhos = 0
        emps = _jsonb(empenhos)
        if detalhe_coletado and isinstance(emps, list):
            reais = [e for e in emps if empenho_real(e)]
            n_empenhos = len(reais)
            valor_empenhado = round(sum(_num(e.get("valor_empenho")) or 0.0
                                        for e in reais), 2)

        if pg.get("pago_integral"):
            estado = "pago"
        elif (pago or 0) > 0:
            estado = "pago_parte"
        elif tem_dh or n_empenhos:
            # Documento hábil só existe pendurado num empenho: havendo DH (mesmo
            # minuta de DH), há empenho — e nada saiu.
            estado = "empenhado"
        elif detalhe_coletado and isinstance(emps, list):
            estado = "sem_empenho"
        else:
            estado = "sem_pagamento"

        return {
            "estado": estado,
            "rotulo": ROTULOS[estado],
            "consultada": True,
            "valor_empenhado": valor_empenhado,
            "valor_pago": pago,
            "valor_a_pagar": _num(des.get("valor_a_desembolsar")),
            "dt_ultimo_pagamento": des.get("dt_ultimo_desembolso") or None,
            "tem_documento_habil": tem_dh,
        }
    except Exception:
        # Lixo no JSONB não pode apagar a seção: sai como não consultada.
        return _vazio("nao_consultada")


def texto_rm_te(ex: dict) -> str:
    """O texto de desembolso que o RM acrescenta à situação da TE.

    ⚠️ BYTE A BYTE O TEXTO QUE O RM SEMPRE ESCREVEU (bloco TE de
    `services/rm_builder.py::montar_conteudo`): o RM fica gravado em
    `rm_relatorios.conteudo`, e mudar a frase mudaria só os relatórios novos.
    Sem medição, silêncio — nunca "Pendente de desembolso" sem ter medido."""
    if not ex or not ex.get("consultada"):
        return ""
    if ex.get("estado") == "pago":
        return f"Pago integralmente: {_fmt_brl(ex.get('valor_pago'))}"
    if ex.get("estado") == "pago_parte":
        return f"Desembolsado: {_fmt_brl(ex.get('valor_pago'))} · Pendente de desembolso"
    if ex.get("tem_documento_habil"):
        return "Pendente de desembolso"   # há empenho/DH e nada saiu
    return ""


# ---------------------------------------------------------------------------
# A execução POR EXTENSO — o PDF de Parlamentares no modelo da planilha
# (24/09/2026) e as telas que só mostravam "CIENTE"
# ---------------------------------------------------------------------------
def frase_execucao_te(ex: dict | None, valor_total=None) -> str:
    """A coluna SITUAÇÃO ATUAL do PDF de Parlamentares, para UM plano.

    O modelo do cliente (planilha de Bom Despacho, 24/09/2026) escreve frase, e
    não rótulo: "Pagamento realizado em 13/12/2024." Cada estado de
    `execucao_te` vira UMA frase, sem inventar o que não foi medido:

      pago           "Pagamento realizado em dd/mm/aaaa."
      pago_parte     "Pago em parte: R$ X de R$ Y; último pagamento em dd/mm/aaaa."
      empenhado      "Empenhado, aguardando pagamento."
      sem_empenho    "Sem empenho."
      sem_pagamento  "Sem pagamento."  (empenhos NÃO lidos: não se diz "sem empenho")
      nao_consultada "Execução não consultada."

    ⚠️ A data é a da EMISSÃO DA OB mais recente (a API pública não traz a de
    crédito — ver o topo deste módulo). Sem data, a frase diz só o que se sabe.
    ⚠️ "Execução não consultada" SÓ no estado `nao_consultada`: o PDF antigo tinha
    uma legenda «-» = "não consultado" que valia também para o «Últ. pagamento»
    de plano CONSULTADO sem OB — a frase por extenso acaba com essa ambiguidade.
    """
    ex = ex or {}
    estado = ex.get("estado") or "nao_consultada"
    dt = ex.get("dt_ultimo_pagamento")
    if estado == "pago":
        return f"Pagamento realizado em {dt}." if dt else "Pagamento realizado."
    if estado == "pago_parte":
        pago = _fmt_brl(ex.get("valor_pago"))
        total = _fmt_brl(valor_total) if _num(valor_total) else ""
        base = f"Pago em parte: {pago} de {total}" if total else f"Pago em parte: {pago}"
        return f"{base}; último pagamento em {dt}." if dt else f"{base}."
    if estado == "empenhado":
        return "Empenhado, aguardando pagamento."
    if estado == "sem_empenho":
        return "Sem empenho."
    if estado == "sem_pagamento":
        return "Sem pagamento."
    return "Execução não consultada."


def _data_br(s) -> str:
    """'2025-12-30' / '2025-12-30T08:19:19' -> '30/12/2025'. Outro formato volta
    como veio (a fonte já manda dd/mm/aaaa em alguns recursos)."""
    t = str(s or "").strip()
    if len(t) >= 10 and t[4] == "-" and t[7] == "-":
        return f"{t[8:10]}/{t[5:7]}/{t[:4]}"
    return t


def frase_relatorio_gestao(relatorios, n_antigos: int = 0,
                           detalhe_coletado: bool = False,
                           estado_execucao: str | None = None) -> str:
    """O estado do RELATÓRIO DE GESTÃO da TE, por extenso — ou "" quando não há
    o que afirmar.

    `relatorios`: a lista enxuta que `detalhe_core` monta de
    `detalhe->'relatorios_gestao_novos'` ({tipo, situacao, data, analises}, com
    `analises` = QUANTAS análises a fonte devolveu). Vale o de data mais recente.

    ⚠️ SÓ O QUE A FONTE DIZ. O modelo do cliente escreve "Aguardando análise do
    relatório de gestão."; a API oficial não tem esse estado — ela dá a situação
    do relatório (ex.: "Disponibilizado", medido no plano 67457 em 14/09/2026) e
    a lista de análises. A frase aqui junta as duas coisas sem concluir além
    delas: "Relatório de gestão final: Disponibilizado em 30/12/2025; nenhuma
    análise registrada."

    Sem relatório: só se afirma "Nenhum relatório de gestão registrado." quando a
    árvore FOI lida (`detalhe_coletado`), nenhuma das duas listas da fonte tem
    item (`n_antigos` = tamanho da lista antiga, `relatorios_gestao`) e o plano
    já recebeu dinheiro — antes do pagamento não há relatório a cobrar.
    """
    try:
        lst = _jsonb(relatorios)
        lst = [r for r in (lst or []) if isinstance(r, dict)] if isinstance(lst, list) else []
        if lst:
            r = max(lst, key=lambda x: str(x.get("data") or ""))
            tipo = str(r.get("tipo") or "").strip().lower()
            sit = str(r.get("situacao") or "").strip()
            data = _data_br(r.get("data"))
            txt = "Relatório de gestão" + (f" {tipo}" if tipo else "")
            txt += f": {sit}" if sit else ": registrado"
            txt += f" em {data}" if data else ""
            n = int(_num(r.get("analises")) or 0)
            txt += ("; nenhuma análise registrada." if n == 0
                    else f"; {n} análise(s) registrada(s).")
            return txt
        if (detalhe_coletado and not int(_num(n_antigos) or 0)
                and estado_execucao in ("pago", "pago_parte")):
            return "Nenhum relatório de gestão registrado."
    except Exception:
        pass
    return ""


def situacao_e_execucao(situacao_plano, rotulo_execucao) -> str:
    """"CIENTE · Pago em parte": a situação do PLANO com a EXECUÇÃO ao lado.

    Para quem só tinha espaço para UMA coluna de situação — o Consolidado
    (`routers/consolidado.py::lancamentos`, tela, planilha e PDF) e a aba
    Federais (`routers/emendas_parlamentares.py::_fontes_federais`). CIENTE
    sozinho era lido como estágio do dinheiro (pedido da Laiza, 24/09/2026).
    Sem rótulo, a situação volta como veio (e vice-versa)."""
    sit = str(situacao_plano or "").strip()
    rot = str(rotulo_execucao or "").strip()
    if sit and rot:
        return f"{sit} · {rot}"
    return sit or rot
