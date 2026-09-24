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
