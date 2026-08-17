"""A REGRA do Decreto Estadual (RS) nº 56.939/2023 — monitoramento mensal de convênios.

⭐ POR QUE ISTO E O GANCHO COMERCIAL MAIS FORTE DO RIO GRANDE DO SUL. O decreto
obriga o municipio a atualizar o Sistema de Monitoramento de Convenios **ate o
dia 15 de cada mes**, informando status (licitando/contratando/executando),
percentual de execucao fisica e fotos. Tres meses consecutivos sem atualizar
implicam **suspensao das parcelas, indeferimento de pedido de prorrogacao e
impedimento de celebrar novos convenios**.

Ou seja: o prejuizo nao vem de fazer errado, vem de ESQUECER. E e exatamente o
tipo de esquecimento que um sistema evita — por isso o PACTHA alarma no **2º
mes**, antes do bloqueio, e nao no 3º, quando o dano ja aconteceu.

⚠️ FUNCAO PURA, SEM I/O — e nao e preferencia de estilo. Esta regra e consumida
por tres caminhos diferentes: a tela (`routers/monitoramento.py`, async), o push
ao prefeito (`run_painel_alertas_cron.py`, psycopg2 sincrono) e o Painel de
Indicadores. Se cada um implementasse a contagem por conta propria, um dia a tela
e a notificacao passariam a discordar sobre o mesmo prazo — que e a razao pela
qual `bi_abas.prazos_dos_itens` tambem mora isolada.

AS DUAS GUARDAS CONTRA FALSO ALARME, que valem mais que a regra em si:

1. ⭐ **O FALSO ALARME DE ESTREIA.** Enquanto nao houver credencial do Portal de
   Convenios e Parcerias (perfil PCPRS), `monitoramento_convenios` esta VAZIA — e
   uma contagem ingenua acusaria **100% dos convenios como atrasados**. O cliente
   abriria o sistema numa parede vermelha inteiramente falsa e, depois disso,
   ignoraria o alerta para sempre, inclusive quando fosse verdade. Municipio sem
   NENHUM registro devolve `nao_conectado`, nunca alarme e nunca verde — a mesma
   escolha do `add_cagec.sql` ("enquanto nao houver linha, `tem_dados: false`;
   nunca um verde, que seria lido como 'regularidade em dia'").

2. **A EXCECAO DE CALAMIDADE.** Municipio em calamidade tem **120 dias** em vez
   do dia 15 (Nota Tecnica SPGG, no rastro das enchentes de maio/2024). Entra
   como PARAMETRO — `prazo_dias` —, nunca como um `if uf == 'RS'` dentro do laco
   de alertas. Default e SEM excecao: silenciar alarme por omissao seria pior que
   o falso positivo que a guarda 1 evita.

⚠️ E o universo exclui convenio que ainda NAO esta em execucao. O dump da CAGE
traz instrumentos em fase anterior ("Liberado para Assembleia Legislativa"), que
nao estao sob a obrigacao mensal. Na duvida, EXCLUIR: falso negativo aqui custa
menos que falso positivo, pela mesma razao da guarda 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Vigencia do decreto. Competencia anterior a esta NAO e exigivel — cobrar
# fevereiro de 2023 de um convenio de 2019 seria inventar divida.
DECRETO_VIGENTE_DESDE = date(2023, 3, 1)
# O prazo do mes: ate o dia 15 o municipio ainda esta dentro do direito dele.
DIA_LIMITE = 15
# Excecao de calamidade (Nota Tecnica SPGG).
PRAZO_CALAMIDADE_DIAS = 120

# Situacoes que indicam convenio ENCERRADO — nao contam para a obrigacao mensal.
# Comparadas sem acento e em minusculas (`_norm`), porque o dump da CAGE mistura
# grafias ao longo dos anos.
#
# ⚠️⚠️ "LIBERADO PARA ASSEMBLEIA LEGISLATIVA" **NAO** ENTRA AQUI, e essa e a
# armadilha mais cara deste modulo. O nome sugere convenio que ainda nem foi
# celebrado, e a primeira versao desta regra o excluiu por isso — resultado: dos
# 108 convenios de Santa Maria, **ZERO** eram avaliados, e o alarme jamais
# tocaria. Um alerta que nunca dispara e pior que alerta nenhum, porque da a
# impressao de cobertura.
#
# Medido no dump da CAGE: ele so tem DUAS situacoes ("Liberado para Assembleia
# Legislativa", 69; "Assinado", 39), e os convenios com essa primeira situacao
# incluem um de R$ 10 milhoes **integralmente pago**, com vigencia ate 2030.
# Ou seja: o campo descreve uma etapa do TRAMITE que fica registrada, nao o
# estado da execucao. Quem responde pelo estado real e a VIGENCIA — e e por ela
# que `esta_em_execucao` decide.
FORA_DE_EXECUCAO = (
    "cancelado", "extinto", "rescindido", "encerrado", "arquivado",
    "nao aprovado", "indeferido",
)

NIVEIS = {0: "em_dia", 1: "atencao", 2: "alarme"}


def _norm(s: str | None) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower())
                   if unicodedata.category(c) != "Mn").strip()


def competencia(d: date) -> str:
    """'AAAA-MM' — a unidade da obrigacao. String e nao date de proposito: e
    chave de tabela, aparece na tela e vai no `ref` do alerta; um `date(1º do
    mes)` convidaria a comparacoes por dia que nao fazem sentido aqui."""
    return f"{d.year:04d}-{d.month:02d}"


def _meses_entre(inicio: date, fim: date) -> list[str]:
    """Competencias de `inicio` ate `fim`, inclusive nas duas pontas."""
    out, ano, mes = [], inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        out.append(f"{ano:04d}-{mes:02d}")
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return out


def esta_em_execucao(situacao: str | None, dt_inicio: date | None,
                     dt_fim: date | None, hoje: date) -> bool:
    """O convenio esta sob a obrigacao mensal AGORA?

    Tres condicoes, e a ordem importa para a legibilidade do resultado: rotulo
    que diz que nao esta em execucao vence qualquer data; depois, vigencia
    iniciada; por fim, vigencia nao encerrada. Sem `dt_inicio` nao da para
    afirmar que comecou — e nao afirmar e o certo (ver a doutrina do modulo)."""
    s = _norm(situacao)
    if any(x in s for x in FORA_DE_EXECUCAO):
        return False
    if dt_inicio is None or dt_inicio > hoje:
        return False
    if dt_fim is not None and dt_fim < hoje:
        return False
    return True


@dataclass
class Pendencia:
    """O resultado por convenio. `nivel` in ('em_dia','atencao','alarme')."""
    chave: str
    convenio_id: int | None
    rotulo: str
    atrasadas: list[str] = field(default_factory=list)
    nivel: str = "em_dia"
    regime: str = "padrao"          # 'padrao' | 'calamidade'
    prazo_do_mes: str = ""          # frase curta para a tela

    @property
    def meses_em_atraso(self) -> int:
        return len(self.atrasadas)


def competencias_exigidas(dt_inicio: date | None, dt_fim: date | None,
                          hoje: date, prazo_dias: int | None = None) -> list[str]:
    """De quais meses este convenio ja DEVERIA ter registro.

    ⚠️ O MES CORRENTE SO ENTRA DEPOIS DO PRAZO. Ate o dia 15 o municipio esta
    dentro do direito dele, e cobrar antes disso e o erro mais facil de cometer
    aqui — transformaria o sistema num alarme que toca todo dia 1º.

    `prazo_dias` (calamidade) troca a regra do dia 15 por "N dias apos o fim da
    competencia", que e como a Nota Tecnica da SPGG descreve a excecao."""
    if dt_inicio is None:
        return []
    inicio = max(dt_inicio, DECRETO_VIGENTE_DESDE)
    # Convenio encerrado nao acumula competencia depois do fim da vigencia.
    fim = min(hoje, dt_fim) if dt_fim else hoje
    if fim < inicio:
        return []
    # ⚠️ O VENCIMENTO E CALCULADO PARA CADA COMPETENCIA, nao so para a ultima.
    # Tratar so a ultima parece equivalente e nao e: no regime padrao, em 10/08
    # tanto agosto quanto JULHO ainda estao no prazo (julho vence em 15/08), e a
    # versao ingenua cobrava julho. No regime de calamidade a diferenca e ainda
    # maior — 120 dias cobrem varias competencias seguidas, e a excecao
    # simplesmente nao teria efeito nenhum. Os dois defeitos apareceram no
    # mesmo teste; e o tipo de erro que passa despercebido porque "quase" acerta.
    return [m for m in _meses_entre(inicio, fim)
            if hoje > _vencimento(int(m[:4]), int(m[5:]), prazo_dias)]


def _vencimento(ano: int, mes: int, prazo_dias: int | None) -> date:
    """Ate quando o municipio pode registrar a competencia `ano-mes`.

    Padrao: dia 15 do mes SEGUINTE (o decreto fala do dia 15 de cada mes, e o
    que se registra em setembro e a execucao de agosto). Calamidade: N dias
    corridos apos o fim da competencia, como descreve a Nota Tecnica da SPGG."""
    prox = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    if prazo_dias:
        from datetime import timedelta
        return prox + timedelta(days=prazo_dias - 1)
    return date(prox.year, prox.month, DIA_LIMITE)


def avaliar(convenios: list[dict], registros: set[tuple[str, str]],
            hoje: date | None = None,
            calamidade_ate: date | None = None,
            tem_algum_registro: bool = True) -> dict:
    """A REGRA. Sem I/O: quem consulta o banco e o chamador.

    `convenios`   [{chave, convenio_id, rotulo, situacao, dt_inicio, dt_fim}]
    `registros`   {(chave, 'AAAA-MM')} — o que JA foi registrado no portal
    `calamidade_ate`  ate quando vale a excecao de 120 dias (None = sem excecao)
    `tem_algum_registro`  o municipio ja teve ALGUMA linha de monitoramento?

    Devolve {estado, nivel, pendencias[], resumo}. `estado` in
    ('nao_conectado', 'avaliado')."""
    hoje = hoje or date.today()

    # ⭐ GUARDA 1 — o falso alarme de estreia. Ver o cabecalho do modulo.
    if not tem_algum_registro:
        return {
            "estado": "nao_conectado",
            "nivel": "desconhecido",
            "pendencias": [],
            "resumo": ("O Sistema de Monitoramento de Convênios ainda não está "
                       "conectado. Assim que a credencial do Portal de Convênios "
                       "e Parcerias (perfil PCPRS) for cadastrada, os prazos do "
                       "Decreto 56.939/2023 passam a ser acompanhados aqui."),
        }

    em_calamidade = bool(calamidade_ate and hoje <= calamidade_ate)
    prazo_dias = PRAZO_CALAMIDADE_DIAS if em_calamidade else None

    pendencias: list[Pendencia] = []
    for c in convenios:
        if not esta_em_execucao(c.get("situacao"), c.get("dt_inicio"),
                                c.get("dt_fim"), hoje):
            continue
        exigidas = competencias_exigidas(c.get("dt_inicio"), c.get("dt_fim"),
                                         hoje, prazo_dias)
        chave = c["chave"]
        atrasadas = [m for m in exigidas if (chave, m) not in registros]
        p = Pendencia(
            chave=chave,
            convenio_id=c.get("convenio_id"),
            rotulo=c.get("rotulo") or chave,
            atrasadas=atrasadas,
            nivel=NIVEIS.get(min(len(atrasadas), 2), "alarme"),
            regime="calamidade" if em_calamidade else "padrao",
            prazo_do_mes=(f"prazo excepcional de {PRAZO_CALAMIDADE_DIAS} dias "
                          f"(calamidade até {calamidade_ate:%d/%m/%Y})"
                          if em_calamidade else "até o dia 15 de cada mês"),
        )
        pendencias.append(p)

    pior = max((p.meses_em_atraso for p in pendencias), default=0)
    nivel = NIVEIS.get(min(pior, 2), "alarme")
    return {
        "estado": "avaliado",
        "nivel": nivel,
        "pendencias": [p for p in pendencias if p.atrasadas],
        "em_dia": sum(1 for p in pendencias if not p.atrasadas),
        "avaliados": len(pendencias),
        "regime": "calamidade" if em_calamidade else "padrao",
        "resumo": _frase(nivel, pior, len([p for p in pendencias if p.atrasadas])),
    }


def _frase(nivel: str, pior: int, quantos: int) -> str:
    """⚠️ NUNCA AFIRMAR QUE O BLOQUEIO JA ACONTECEU. Nós vemos a AUSENCIA de
    registro, nao a decisao do Estado — o convenente pode ter sido notificado,
    ter prazo em curso ou ter regularizado por outra via. A frase descreve o que
    a norma PREVE, no futuro do preterito. Mesma disciplina do
    `add_contas_irregulares.sql`: indicio, nunca documento."""
    if nivel == "em_dia":
        return "Monitoramento em dia em todos os convênios em execução."
    if nivel == "atencao":
        return (f"{quantos} convênio(s) com 1 mês sem registro no Sistema de "
                "Monitoramento. Regularizar antes do próximo dia 15.")
    return (f"{quantos} convênio(s) com {pior} meses sem registro. Ao 3º mês "
            "consecutivo, a norma prevê suspensão das parcelas, indeferimento "
            "de pedido de prorrogação e impedimento de celebrar novos convênios "
            "(Decreto 56.939/2023).")
