"""O recorte da tela de Convênios, num lugar só — filtro, ordem e rótulos.

⚠️ POR QUE ESTE MÓDULO EXISTE, e é a razão de ele ser um módulo e não mais uma
função dentro do router.

O predicado desta tela já foi copiado repetidamente, e cada cópia cobrou o
mesmo preço. `_cond_fonte` (antes em `routers/convenios.py:105`) nasceu para
matar QUATRO cópias da regra de fonte, e o comentário dela registra o estrago:
"foi essa duplicacao que deixou o export PDF de fora e contar propostas de saude
como convenio". O comentário de `routers/export_pdf.py:182` registra o resto —
Goiânia com 139 "convênios SIGCON-MG" que eram propostas federais de saúde num
estado que o SIGCON-MG nem cobre, Monte Sião com 81 na tela e 129 no PDF, e 22
municípios do Freitas com PDF inteiramente fabricado ao lado de uma tela
corretamente vazia. Aquele arquivo se descreve como "a QUINTA copia da mesma".

Em 03/09/2026 o dono relatou o defeito seguinte da mesma família: marcava
"apenas os convênios em vigor" e o PDF saía com tudo. A causa era mais simples
que as anteriores — o frontend mandava só `municipio_id` e a rota não aceitava
mais nada —, mas o conserto óbvio (repetir os oito filtros na rota de export)
seria a SEXTA cópia. Daí este módulo: a listagem e os três exports chamam
`condicoes()`, e `tests/test_convenios_filtro.py` compara as assinaturas para
que um parâmetro novo não possa nascer em um lado só.

⚠️ "EM VIGOR" É `situacoes`, NÃO `vigencias`. Vale escrever porque eu mesmo
errei isto ao diagnosticar. `VIGENCIA_OPCOES` na tela é
vence30/vence60/vence90/vence120/prestacao — não há "em vigor" ali. "Em vigor" é
VALOR da coluna `situacao`, escrito pelo coletor (`sigcon_scraper.py:66` mapeia
`VIGENTE -> "Em vigor"`). Quem conserta só a vigência não conserta a queixa.
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, func, or_

from models import ConvenioEstadual

# ------------------------------------------------------------------- fonte
# A regra de FONTE mora AQUI, num lugar so. `convenios_estadual` guarda TRES
# origens: SIGCON-MG (convenio estadual de MG), GCONV-ES (o equivalente
# capixaba) e FNS (propostas de saude, que NAO sao convenio e tem tela propria).
_FNS_EXCL = or_(ConvenioEstadual.fonte.is_(None),
                ~ConvenioEstadual.fonte.ilike("%FNS%"))


def cond_fonte(fonte: Optional[str], fontes: Optional[list[str]]):
    """Sem escolha = a regra padrao da tela (tudo menos FNS).

    'SIGCON' e 'SIGCON-MG' sao o MESMO pedido: o dropdown antigo mandava
    'SIGCON', o novo manda o valor do banco. Os dois casam com as duas grafias
    E com fonte NULA (linhas legadas de MG).

    ⚠️ OMITIR ESTE FILTRO NAO E "SEM RECORTE": sem escolha, ele devolve
    `_FNS_EXCL`, que e um conjunto ATIVO (tudo menos FNS). E o unico dos oito em
    que esquecer o parametro no export produziria um resultado diferente da tela
    na direcao oposta — arquivo sem FNS com a tela mostrando FNS."""
    if fontes:
        alvo: list[str] = []
        com_nulo = False
        for f in fontes:
            if f.upper() in ("SIGCON", "SIGCON-MG"):
                alvo.extend(["SIGCON-MG", "SIGCON"])
                com_nulo = True
            else:
                alvo.append(f)
        cond = ConvenioEstadual.fonte.in_(alvo)
        return or_(cond, ConvenioEstadual.fonte.is_(None)) if com_nulo else cond
    if fonte:
        cond = ConvenioEstadual.fonte == fonte
        return cond if "FNS" in fonte.upper() else and_(cond, _FNS_EXCL)
    return _FNS_EXCL


_ROTULO_VIGENCIA = {
    "vence30": "Vence em 30 dias",
    "vence60": "Vence em 60 dias",
    "vence90": "Vence em 90 dias",
    "vence120": "Vence em 120 dias",
    "prestacao": "Prestação de contas (vencida há +90 dias)",
}
_ROTULO_PAGAMENTO = {
    "pago": "Pago",
    "parcial": "Parcialmente pago",
    "nao_pago": "Não pago",
}


def ordem():
    """A ordem do SQL, a MESMA da tela.

    ⚠️ O export TEM de repetir esta ordem. `_sort_key` do router empata muito
    (todo NULL cai na mesma chave) e o `sort` do Python é estável, então os
    empates preservam a ordem de chegada — que é esta. Um export que rode só o
    WHERE entrega os empates na ordem arbitrária do Postgres, e as MESMAS linhas
    saem embaralhadas em relação à tela.

    ⚠️ Ordena por data-ou-ano. O coletor do SIGCON gravava `date(ano,1,1)` em
    `dt_publicacao` quando não conseguia abrir o detalhe; o substituto saiu, e o
    SQL passou a fazer a queda — no lugar onde ela é critério de ordem, e não
    fato exibido."""
    return func.coalesce(
        ConvenioEstadual.dt_publicacao,
        func.make_date(func.coalesce(ConvenioEstadual.ano, 1900), 1, 1),
    ).desc().nullslast()


def condicoes(
    *,
    municipio_id: Optional[int] = None,
    ano: Optional[int] = None,
    anos: Optional[list[int]] = None,
    situacao: Optional[str] = None,
    situacoes: Optional[list[str]] = None,
    fonte: Optional[str] = None,
    fontes: Optional[list[str]] = None,
    vigencia: Optional[str] = None,
    vigencias: Optional[list[str]] = None,
    pagamento: Optional[str] = None,
    pagamentos: Optional[list[str]] = None,
    vig_fim_de: Optional[date] = None,
    vig_fim_ate: Optional[date] = None,
    search: Optional[str] = None,
) -> tuple[list, list[str]]:
    """Devolve `(condicoes, recorte)` — as cláusulas e como descrevê-las.

    ⚠️ O `recorte` SAI DAQUI, e não da querystring, de propósito. `vigencias` e
    `pagamentos` são dicionários de regras: um valor fora do dicionário é
    descartado em silêncio, e se TODOS forem, o filtro some. O caminho é vivo —
    a tela lê `?vigencia=` da URL sem validar, vindo de link de KPI do painel.
    Descrever o pedido em vez do que foi aplicado faria um link velho com
    `?vigencia=vence45` gerar um documento que AFIRMA "Vence em 45 dias" sobre a
    base inteira. Um papel que mente por escrito é pior que o PDF mudo de hoje.
    """
    conds: list = []
    recorte: list[str] = []

    if municipio_id:
        conds.append(ConvenioEstadual.municipio_id == municipio_id)

    _anos = anos or ([ano] if ano else [])
    if _anos:
        conds.append(ConvenioEstadual.ano.in_(_anos))
        recorte.append("Ano: " + ", ".join(str(a) for a in sorted(_anos)))

    if situacoes:
        conds.append(ConvenioEstadual.situacao.in_(situacoes))
        recorte.append("Situação: " + ", ".join(situacoes))
    elif situacao:
        conds.append(ConvenioEstadual.situacao.ilike(f"%{situacao}%"))
        recorte.append(f"Situação contém: {situacao}")

    _pagamentos = pagamentos or ([pagamento] if pagamento else [])
    if _pagamentos:
        vr = ConvenioEstadual.valor_repassado
        vc = ConvenioEstadual.valor_concedente
        # UNIAO, nao intersecao: marcar "pago" e "parcial" tem que trazer os
        # dois grupos. Com AND o resultado seria sempre vazio, porque as
        # condicoes se excluem — filtro que devolve zero parece base sem dado.
        _regras = {
            "pago":     and_(vr.is_not(None), vr > 0, vc.is_not(None), vr >= vc),
            "parcial":  and_(vr.is_not(None), vr > 0, or_(vc.is_(None), vr < vc)),
            "nao_pago": or_(vr.is_(None), vr == 0),
        }
        usados = [p for p in _pagamentos if p in _regras]
        if usados:
            cs = [_regras[p] for p in usados]
            conds.append(cs[0] if len(cs) == 1 else or_(*cs))
            recorte.append("Pagamento: " + ", ".join(_ROTULO_PAGAMENTO[p] for p in usados))

    # Esta e a tela de CONVENIOS ESTADUAIS. `convenios_estadual` tambem guarda
    # PROPOSTAS do FNS (saude), que NAO sao convenio e tem tela propria — por
    # isso, sem escolha de fonte, elas ficam de fora.
    conds.append(cond_fonte(fonte, fontes))
    if fontes:
        recorte.append("Fonte: " + ", ".join(fontes))
    elif fonte:
        recorte.append(f"Fonte: {fonte}")

    _vigencias = vigencias or ([vigencia] if vigencia else [])
    if _vigencias:
        hoje = date.today()
        dv = ConvenioEstadual.dt_vigencia_atual
        # UNIAO pelo mesmo motivo do pagamento. "vence60" e SUBCONJUNTO de
        # "vence120": marcar os dois e igual a marcar so o 120, e isso e o
        # esperado — nao ha o que "somar" alem do maior.
        _regras = {
            "vence30":   and_(dv >= hoje, dv <= hoje + timedelta(days=30)),
            "vence60":   and_(dv >= hoje, dv <= hoje + timedelta(days=60)),
            "vence90":   and_(dv >= hoje, dv <= hoje + timedelta(days=90)),
            "vence120":  and_(dv >= hoje, dv <= hoje + timedelta(days=120)),
            "prestacao": dv < hoje - timedelta(days=90),
        }
        usados = [v for v in _vigencias if v in _regras]
        if usados:
            cs = [_regras[v] for v in usados]
            conds.append(cs[0] if len(cs) == 1 else or_(*cs))
            recorte.append("Vigência: " + ", ".join(_ROTULO_VIGENCIA[v] for v in usados))

    if vig_fim_de or vig_fim_ate:
        # `dt_vigencia_atual` e a data que a tela mostra e a que o alerta usa;
        # `dt_vigencia_final` e o fim FORMAL, que diverge quando houve aditivo.
        dv = func.coalesce(ConvenioEstadual.dt_vigencia_atual,
                           ConvenioEstadual.dt_vigencia_final)
        if vig_fim_de:
            conds.append(dv >= vig_fim_de)
        if vig_fim_ate:
            conds.append(dv <= vig_fim_ate)
        faixa = " a ".join(x.strftime("%d/%m/%Y") for x in (vig_fim_de, vig_fim_ate) if x)
        recorte.append(f"Fim de vigência: {faixa}")

    if search:
        term = f"%{search}%"
        conds.append(or_(
            ConvenioEstadual.objeto.ilike(term),
            # `objetivo` tambem: no dialeto do ES a descricao vive NESTA coluna e
            # `objeto` guarda o codigo do processo. No-op em MG (objetivo e NULO
            # em 869 de 869 linhas); no ES leva PAVIMENTA de 0 para 3.
            ConvenioEstadual.objetivo.ilike(term),
            ConvenioEstadual.nr_sigcon.ilike(term),
            ConvenioEstadual.nr_siafi.ilike(term),
            ConvenioEstadual.nr_plano_trabalho.ilike(term),
            ConvenioEstadual.raw_data["nr_proposta"].astext.ilike(term),
            ConvenioEstadual.raw_data["nr_instrumento"].astext.ilike(term),
            ConvenioEstadual.raw_data["nr_plano"].astext.ilike(term),
            ConvenioEstadual.raw_data["nr_plano_sigcon"].astext.ilike(term),
            # O numero publicado do ES vive em `numOriginal` (`nr_instrumento` e
            # NULO nas 25 de 25 linhas do GConv).
            ConvenioEstadual.raw_data["numOriginal"].astext.ilike(term),
        ))
        recorte.append(f"Busca: “{search}”")

    return conds, recorte
