"""Regras de obra do SISMOB — prazo de norma e estagnacao.

SEM I/O, de proposito. Usadas pela tela (async/SQLAlchemy), pela aba do Painel e
pelo cron de push (psycopg2 sincrono). Se cada um implementasse a sua, um dia a
notificacao e a tela passariam a discordar sobre a mesma obra e o gestor nao
saberia em qual acreditar. Mesmo padrao de `prazos_dos_itens` em bi_abas.py.

Cada regra devolve, alem do diagnostico, a NORMA e a ACAO em texto. Um alerta
que diz "vencido" sem dizer o dispositivo nem o que fazer nao sobrevive a
primeira conversa com a Secretaria de Saude.

Prazos e sua origem estao em services/sismob_catalogo.py.
"""
from __future__ import annotations

from datetime import date

from services.sismob_catalogo import (
    NORMA, PRAZO_ATUALIZACAO_DIAS, PRAZO_FUNCIONAMENTO_DIAS,
    PRAZO_INICIO_EXECUCAO_DIAS, MARCO_EXECUCAO_PCT, situacao_terminal,
)

# Situacoes em que a obra ainda esta viva o bastante para cobrar prazo.
_EM_ANDAMENTO = (0, 1, 2, 5, 6)
_CANCELADAS = (7, 8)
_CONCLUIDA = 3


def _dias(de: date | None, ate: date) -> int | None:
    return (ate - de).days if de else None


def por_extenso(dias: int) -> str:
    """"3 anos e 9 meses" em vez de "1368 dias".

    Numero grande de dias vira ruido: o gestor le "1368" e nao sente. Anos e
    meses ele sente."""
    if dias < 45:
        return f"{dias} dia{'s' if dias != 1 else ''}"
    if dias < 365:
        m = round(dias / 30)
        return f"{m} {'meses' if m != 1 else 'mês'}"
    anos, resto = divmod(dias, 365)
    meses = round(resto / 30)
    txt = f"{anos} ano{'s' if anos != 1 else ''}"
    return f"{txt} e {meses} {'meses' if meses != 1 else 'mês'}" if meses else txt


def _fmt(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _money(v) -> str:
    """R$ 1.234.567,89.

    Formata SO o numero. Aplicar o swap de ponto/virgula sobre a frase inteira
    troca a pontuacao do texto tambem — vira "cancelada em 14/01/2019, O recurso
    precisa" com virgula no lugar do ponto final."""
    return f"R$ {float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def classificar(o: dict, hoje: date | None = None) -> dict:
    """Diagnostico de UMA obra.

    Devolve {"severidade": "critico"|"atencao"|"ok"|"encerrada", "regras": [...]}
    onde cada regra tem regra/titulo/detalhe/norma/acao/dias."""
    hoje = hoje or date.today()
    co = o.get("co_situacao_obra")
    try:
        co = int(co) if co is not None else None
    except (TypeError, ValueError):
        co = None

    regras: list[dict] = []

    # ---- R1: etapa de inicio de execucao estourou os 90 dias ----------------
    # A etapa COMECA COM O REPASSE (nao com a portaria nem com a ordem de
    # servico) e se encerra ao informar 30% de execucao.
    if co == 1 and o.get("dt_primeira_parcela"):
        venc = _dias(o["dt_primeira_parcela"], hoje)
        atraso = venc - PRAZO_INICIO_EXECUCAO_DIAS
        if atraso > 0:
            regras.append({
                "regra": "etapa90",
                "titulo": "Etapa de início de execução vencida",
                "detalhe": (f"Repasse em {_fmt(o['dt_primeira_parcela'])}. A etapa deveria "
                            f"ter sido encerrada em até {PRAZO_INICIO_EXECUCAO_DIAS} dias, "
                            f"informando {MARCO_EXECUCAO_PCT}% de execução. "
                            f"Vencida há {por_extenso(atraso)}."),
                "norma": NORMA,
                "acao": "Informar o percentual de execução no SISMOB e encerrar a etapa.",
                "dias": atraso, "severidade": "critico",
            })
        elif atraso > -31:
            falta = -atraso
            regras.append({
                "regra": "etapa90",
                "titulo": f"Etapa de início de execução vence em {falta} dia(s)",
                "detalhe": (f"Repasse em {_fmt(o['dt_primeira_parcela'])}. Prazo de "
                            f"{PRAZO_INICIO_EXECUCAO_DIAS} dias para informar "
                            f"{MARCO_EXECUCAO_PCT}% de execução."),
                "norma": NORMA,
                "acao": "Informar o percentual de execução antes do prazo.",
                "dias": -falta, "severidade": "atencao",
            })

    # ---- R2: sem atualizacao ha mais de 60 dias -----------------------------
    # `ultima_atividade_em` e GREATEST(foto, mudanca de situacao, mudanca de %).
    # NUNCA usar `dt_atualizacao_fonte`: ela vale a mesma data para obra
    # abandonada ha anos e para obra que se moveu semana passada.
    if co in _EM_ANDAMENTO and o.get("ultima_atividade_em"):
        parado = _dias(o["ultima_atividade_em"], hoje)
        if parado > PRAZO_ATUALIZACAO_DIAS:
            regras.append({
                "regra": "sem_atualizacao",
                "titulo": f"Sem atualização há {por_extenso(parado)}",
                "detalhe": (f"Última atividade registrada em "
                            f"{_fmt(o['ultima_atividade_em'])}."),
                "norma": f"Atualização obrigatória a cada {PRAZO_ATUALIZACAO_DIAS} dias",
                "acao": "Subir fotos e atualizar o percentual de execução no SISMOB.",
                "dias": parado,
                # Duas palavras diferentes porque sao dois problemas diferentes:
                # atrasada volta com uma visita do fiscal; parada ha anos e outra
                # conversa.
                "severidade": "critico" if parado > 180 else "atencao",
            })

    # ---- R3: concluida que nunca entrou em funcionamento --------------------
    # A 4a etapa vem DEPOIS da conclusao — por isso "Concluída" nao e terminal.
    if (co == _CONCLUIDA and o.get("dt_conclusao_final")
            and not o.get("dt_inicio_funcionamento") and not o.get("nu_cnes")):
        atraso = _dias(o["dt_conclusao_final"], hoje) - PRAZO_FUNCIONAMENTO_DIAS
        if atraso > 0:
            regras.append({
                "regra": "sem_funcionamento",
                "titulo": "Obra concluída sem entrada em funcionamento",
                "detalhe": (f"Concluída em {_fmt(o['dt_conclusao_final'])}, sem registro "
                            f"no CNES nem data de início de funcionamento. "
                            f"Pendente há {por_extenso(atraso)}."),
                "norma": f"{NORMA} — 4ª etapa: {PRAZO_FUNCIONAMENTO_DIAS} dias, com registro no CNES",
                "acao": "Registrar o estabelecimento no CNES e informar o início de funcionamento.",
                "dias": atraso,
                # Pendencia antiga NAO vira push (ver push_permitido): acordar o
                # prefeito as 7h por causa de 2015 ensina que a notificacao do
                # PACTHA e ruido — e ai a de prazo vencido tambem e ignorada.
                "severidade": "atencao",
            })

    # ---- R5: repasse na conta sem contrato registrado -----------------------
    # Flag de TELA, nao push: nao dispara nenhuma vez no tenant vivo, e ligar
    # push nunca exercitado em producao e o pior tipo de codigo.
    if (o.get("repasse_total") or 0) > 0 and co in (0, 1, 2) and not o.get("empresas"):
        regras.append({
            "regra": "sem_contrato",
            "titulo": "Repasse recebido sem contrato registrado",
            "detalhe": (f"{_money(o['repasse_total'])} repassados e nenhuma "
                        f"empresa contratada consta no SISMOB."),
            "norma": NORMA,
            "acao": "Registrar o contrato e a ordem de serviço no SISMOB.",
            "dias": None, "severidade": "atencao",
        })

    # ---- R6: cancelada com dinheiro recebido --------------------------------
    if co in _CANCELADAS and (o.get("repasse_total") or 0) > 0:
        v = float(o["repasse_total"])
        desde = o.get("dt_primeira_parcela")
        quando = f" desde {_fmt(desde)}" if desde else ""
        regras.append({
            "regra": "cancelada_com_repasse",
            "titulo": "Obra cancelada com recurso recebido",
            "detalhe": (f"{_money(v)} repassados{quando}, e a obra foi cancelada"
                        f"{' em ' + _fmt(o['dt_mudanca_situacao']) if o.get('dt_mudanca_situacao') else ''}. "
                        f"O recurso precisa ser devolvido ou reprogramado."),
            "norma": NORMA,
            "acao": "Providenciar a devolução ou a reprogramação do recurso junto ao FNS.",
            "dias": _dias(desde, hoje) if desde else None,
            "severidade": "critico",
        })

    if regras:
        sev = "critico" if any(r["severidade"] == "critico" for r in regras) else "atencao"
    elif situacao_terminal(co):
        sev = "encerrada"
    else:
        sev = "ok"
    return {"severidade": sev, "regras": regras}


# Regras que PODEM virar notificacao push. `sem_contrato` fica de fora por
# decisao (ver R5).
_PUSH = {"etapa90", "sem_atualizacao", "sem_funcionamento", "cancelada_com_repasse"}


def push_permitido(regra: dict, o: dict, hoje: date | None = None) -> bool:
    """Se esta regra desta obra merece ir para o celular do gestor.

    O corte de 12 meses em `sem_funcionamento` existe porque uma pendencia
    cadastral de 2015 no push destroi a credibilidade de TODAS as outras."""
    if regra["regra"] not in _PUSH:
        return False
    if regra["regra"] == "sem_funcionamento":
        return (regra.get("dias") or 0) <= 365
    return True
