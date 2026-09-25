"""SIOPS, SIOPE e os instrumentos de planejamento do SUS — as REGRAS, sem I/O.

Vive em `services/` e não no router pelo mesmo motivo de `cauc_catalogo.py`: a
imagem do worker não tem `/app/routers`, e o cron de push
(`ingestion/run_painel_alertas_cron.py`) usa `entrega_cobre_validade_do_cauc`
através de `bi_abas.prazos_dos_itens`. A tela, o painel e o push leem a MESMA
regra — se cada um calculasse o seu prazo, um dia eles discordariam sobre o mesmo
bimestre (regra do dono: o mesmo dado dá a mesma conta em toda tela).

O QUE O CAUC NÃO DIZ E ISTO DIZ:

  * 3.2.3 (Anexo 8 do RREO ao SIOPE) e 3.2.4 (Anexo 12 ao SIOPS): o CAUC dá "!"
    ou uma validade. Aqui: QUAL bimestre falta, até quando, e se o município já
    entregou e o Tesouro ainda não atualizou.
  * 5.1 (mínimo em educação) e 5.2 (mínimo em saúde): o percentual aplicado.

⚠️ O PERCENTUAL DO BIMESTRE É ACUMULADO NO ANO E PARCIAL. O mínimo (15% da
receita própria em ASPS, LC 141 art. 7º; 25% em MDE, CF art. 212) se apura no
exercício — o 6º bimestre. Pintar de vermelho um 1º bimestre com 13% seria
acusar o município de descumprir uma regra que ainda não pode ser descumprida.
Vermelho só no ano fechado; no bimestre, no máximo "atenção".

Prazos (lei, não fonte):
  * SIOPS e SIOPE: 30 dias após o fim do bimestre (o do RREO, LC 101 art. 52).
  * RDQA: até o fim de maio (1º), setembro (2º) e fevereiro do ano seguinte (3º)
    — LC 141 art. 36 §5º.
  * RAG: até 30 de março do ano seguinte (LC 141 art. 36 §1º).
  * PAS e Plano de Saúde: sem prazo nesta regra (o calendário deles é o do PPA e
    da LDO do próprio ente); a tela mostra só a situação.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Optional

SISTEMAS = ("SIOPS", "SIOPE")

# Código de período da API do SIOPS e da lista legada, por bimestre. MEDIDO em
# 24/09/2026 (o formulário de siops.datasus.gov.br/consmuntransm.php lista
# "12 = 1º Bimestre, 14 = 2º, 1 = 3º, 18 = 4º"; 20 e 2 conferidos com Monte Sião
# 2025, cuja receita acumulada cresce 25,8 → 49,0 → 80,8 → 110,8 → 135,8 → 167,7
# milhões nessa ordem). O 3º e o 6º têm os códigos do 1º e 2º SEMESTRE.
PERIODO_SIOPS = {1: 12, 2: 14, 3: 1, 4: 18, 5: 20, 6: 2}

MINIMO = {"SIOPS": 15.0, "SIOPE": 25.0}

INDICADOR = {
    "SIOPS": "% da receita própria aplicada em ações e serviços públicos de saúde (ASPS)",
    "SIOPE": "% das receitas de impostos e transferências aplicado em manutenção e "
             "desenvolvimento do ensino (MDE)",
}

NOME = {"SIOPS": "SIOPS — saúde", "SIOPE": "SIOPE — educação"}

# Item do CAUC que cobra o ENVIO, e o que cobra o MÍNIMO.
CAUC_ENVIO = {"3.2.4": "SIOPS", "3.2.3": "SIOPE"}
CAUC_MINIMO = {"5.2": "SIOPS", "5.1": "SIOPE"}


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------
def fim_bimestre(ano: int, bimestre: int) -> date:
    """Último dia do bimestre (28/02 ou 29/02, 30/04, 30/06, 31/08, 31/10, 31/12)."""
    mes = bimestre * 2
    if mes == 12:
        return date(ano, 12, 31)
    return date(ano, mes + 1, 1) - timedelta(days=1)


def prazo_bimestre(ano: int, bimestre: int) -> date:
    """30 dias após o fim do bimestre: 30/03, 30/05, 30/07, 30/09, 30/11 e 30/01."""
    return fim_bimestre(ano, bimestre) + timedelta(days=30)


def rotulo_bimestre(ano: int, bimestre: int) -> str:
    return f"{bimestre}º bimestre/{ano}"


def bimestres_encerrados(hoje: date, anos_atras: int = 1) -> list[tuple[int, int]]:
    """Os bimestres já encerrados, do ano corrente e dos `anos_atras` anteriores,
    do mais antigo para o mais novo. Bimestre em curso não entra: não há o que
    entregar antes de ele acabar."""
    out = []
    for ano in range(hoje.year - anos_atras, hoje.year + 1):
        for b in range(1, 7):
            if fim_bimestre(ano, b) < hoje:
                out.append((ano, b))
    return out


def bimestre_do_prazo(d: date) -> tuple[int, int]:
    """O bimestre que VENCE numa data de validade do CAUC: o mais recente já
    encerrado antes dela. Validade 30/09/2026 → 4º/2026 (acabou em 31/08);
    30/01/2027 → 6º/2026."""
    ano, b = d.year, 6
    while fim_bimestre(ano, b) >= d:
        b -= 1
        if b == 0:
            ano, b = ano - 1, 6
    return ano, b


def entrega_cobre_validade_do_cauc(codigo: str, validade: date,
                                   entregues: Optional[dict]) -> bool:
    """⭐ O ALARME FALSO. O CAUC diz "3.2.4 válido até 30/09" e o PACTHA avisava
    "vence em 6 dias" — com o 4º bimestre JÁ homologado no SIOPS desde 23/09
    (Nova Palma/RS, medido em 24/09/2026). O Tesouro atualiza o item depois; até
    lá a validade antiga continua no extrato, e o aviso manda o gestor correr
    atrás de uma entrega que ele já fez.

    `entregues`: {sistema: {(ano, bimestre), ...}} só com o que a fonte PROVOU
    entregue. Item sem sistema (tudo que não é 3.2.3/3.2.4) → False: a regra de
    prazo segue como sempre."""
    sistema = CAUC_ENVIO.get(codigo)
    if not sistema or not entregues or not validade:
        return False
    return bimestre_do_prazo(validade) in (entregues.get(sistema) or set())


def entregues_por_municipio(linhas) -> dict[int, dict[str, set]]:
    """{municipio_id: {sistema: {(ano, bimestre)}}} a partir de linhas
    (municipio_id, sistema, ano, bimestre) — o formato que
    `entrega_cobre_validade_do_cauc` recebe."""
    out: dict[int, dict[str, set]] = {}
    for mid, sistema, ano, bim in linhas:
        out.setdefault(mid, {}).setdefault(sistema, set()).add((int(ano), int(bim)))
    return out


# A mesma consulta para a tela (async, `:ids`) e para o cron (psycopg2, `%s`).
SQL_ENTREGUES = ("SELECT municipio_id, sistema, ano, bimestre FROM saude_educacao_bimestre "
                 "WHERE entregue AND municipio_id = ANY({ids})")


def situacao_bimestre(entregue: Optional[bool], data_entrega: Optional[date],
                      prazo: date, hoje: date) -> str:
    """'entregue' | 'entregue_atrasado' | 'no_prazo' | 'atrasado' | 'sem_informacao'.

    `entregue is None` = a fonte não respondeu por aquele bimestre (sem linha).
    NUNCA vira 'atrasado': não saber não é o município estar em falta."""
    if entregue is None:
        return "sem_informacao"
    if entregue:
        if data_entrega and data_entrega > prazo:
            return "entregue_atrasado"
        return "entregue"
    return "no_prazo" if hoje <= prazo else "atrasado"


def tom_percentual(pct: Optional[float], minimo: float, bimestre: int) -> Optional[str]:
    """Cor do percentual: vermelho SÓ no ano fechado (6º bimestre); no bimestre
    parcial, abaixo do mínimo é 'atencao' — nunca 'critico'."""
    if pct is None:
        return None
    if pct >= minimo:
        return "ok"
    return "critico" if bimestre == 6 else "atencao"


# ---------------------------------------------------------------------------
# Instrumentos de planejamento do SUS (DigiSUS Gestor)
# ---------------------------------------------------------------------------
INSTRUMENTOS = {
    "PLANO": "Plano de Saúde",
    "PAS": "Programação Anual de Saúde",
    "RDQA1": "1º RDQA",
    "RDQA2": "2º RDQA",
    "RDQA3": "3º RDQA",
    "RAG": "Relatório Anual de Gestão",
}
ORDEM_INSTRUMENTOS = ("PLANO", "PAS", "RDQA1", "RDQA2", "RDQA3", "RAG")

# Palavras literais da fonte, medidas nos arquivos de MG, RS e PR em 24/09/2026.
# "Avaliado" é o fim do RDQA (o conselho avalia); "Aprovado" é o fim de Plano,
# PAS e RAG (o conselho aprova).
_CONCLUIDO = {"aprovado", "aprovado com ressalvas", "avaliado"}
_CONSELHO = {"em análise no conselho de saúde", "em analise no conselho de saude"}
_PENDENTE = {"não iniciado", "nao iniciado", "em elaboração", "em elaboracao",
             "retornado para ajustes"}
_REPROVADO = {"não aprovado", "nao aprovado"}


def classe_situacao(situacao: Optional[str]) -> str:
    """'concluido' | 'conselho' | 'pendente' | 'reprovado' | 'desconhecido'.

    'conselho' NÃO é pendência da prefeitura: ela fez a parte dela e o documento
    espera o Conselho Municipal de Saúde. Separar os dois muda a quem se cobra.
    Palavra nova da fonte cai em 'desconhecido' — mostrada literal, sem cor."""
    s = " ".join((situacao or "").strip().lower().split())
    if s in _CONCLUIDO:
        return "concluido"
    if s in _CONSELHO:
        return "conselho"
    if s in _PENDENTE:
        return "pendente"
    if s in _REPROVADO:
        return "reprovado"
    return "desconhecido"


def prazo_instrumento(instrumento: str, ano: int) -> Optional[date]:
    if instrumento == "RDQA1":
        return date(ano, 5, 31)
    if instrumento == "RDQA2":
        return date(ano, 9, 30)
    if instrumento == "RDQA3":
        return date(ano + 1, 3, 1) - timedelta(days=1)     # fim de fevereiro
    if instrumento == "RAG":
        return date(ano + 1, 3, 30)
    return None


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


def _f(v) -> Optional[float]:
    return float(v) if v is not None else None


def _fmt_data(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.2f}".replace(".", ",") + "%" if v is not None else "—"


# ---------------------------------------------------------------------------
# O payload da tela
# ---------------------------------------------------------------------------
def montar_sistema(sistema: str, linhas: Iterable[dict], hoje: date) -> dict:
    """Um sistema (SIOPS ou SIOPE) do município: os bimestres encerrados do ano
    corrente e do anterior, com situação e prazo, mais os resumos que a tela e a
    nota ao lado do item do CAUC usam.

    `linhas`: dicts com ano, bimestre, entregue, data_entrega, pct_aplicado,
    numerador, denominador, recibo, indicadores."""
    por_bim = {(int(l["ano"]), int(l["bimestre"])): l for l in linhas}
    minimo = MINIMO[sistema]
    esperados = bimestres_encerrados(hoje)
    chaves = sorted(set(esperados) | set(por_bim), reverse=True)

    bims = []
    for ano, b in chaves:
        l = por_bim.get((ano, b))
        prazo = prazo_bimestre(ano, b)
        entregue = l["entregue"] if l else None
        data = l.get("data_entrega") if l else None
        pct = _f(l.get("pct_aplicado")) if l else None
        bims.append({
            "ano": ano, "bimestre": b, "rotulo": rotulo_bimestre(ano, b),
            "prazo": _iso(prazo),
            "entregue": entregue,
            "data_entrega": _iso(data),
            "situacao": situacao_bimestre(entregue, data, prazo, hoje),
            "pct": pct,
            "numerador": _f(l.get("numerador")) if l else None,
            "denominador": _f(l.get("denominador")) if l else None,
            "recibo": (l.get("recibo") if l else None),
            # 6º bimestre = o ano fechado; os demais são parciais.
            "parcial": b != 6,
            "tom_pct": tom_percentual(pct, minimo, b),
        })

    atrasados = [x for x in bims if x["situacao"] == "atrasado"]
    abertos = [x for x in bims if x["situacao"] in ("atrasado", "no_prazo")]
    entregues = [x for x in bims if x["entregue"]]
    # O próximo a entregar é o MAIS ANTIGO em aberto: é ele que o CAUC cobra.
    proximo = abertos[-1] if abertos else None
    ultimo = entregues[0] if entregues else None
    ultimo_pct = next((x for x in bims if x["entregue"] and x["pct"] is not None), None)
    ano_fechado = next((x for x in bims if x["bimestre"] == 6 and x["entregue"]
                        and x["pct"] is not None), None)
    return {
        "sistema": sistema,
        "nome": NOME[sistema],
        "indicador": INDICADOR[sistema],
        "minimo": minimo,
        "item_envio": next(k for k, v in CAUC_ENVIO.items() if v == sistema),
        "item_minimo": next(k for k, v in CAUC_MINIMO.items() if v == sistema),
        "bimestres": bims,
        "atrasados": [x["rotulo"] for x in atrasados],
        "proximo": proximo,
        "ultimo_entregue": ultimo,
        "ultimo_pct": ultimo_pct,
        "ano_fechado": ano_fechado,
        "sem_informacao": sum(1 for x in bims if x["situacao"] == "sem_informacao"),
    }


def nota_envio(s: dict, validade_cauc: Optional[date] = None) -> Optional[dict]:
    """A frase ao lado do item 3.2.3/3.2.4 do CAUC. {texto, tom}."""
    if not s["bimestres"]:
        return None
    partes, tom = [], None
    if s["atrasados"]:
        mais_antigo = s["proximo"]
        partes.append(
            f"Falta entregar ao {s['sistema']}: {', '.join(reversed(s['atrasados']))} "
            f"(o prazo do {mais_antigo['rotulo']} venceu em "
            f"{_fmt_data(date.fromisoformat(mais_antigo['prazo']))}).")
        tom = "critico"
    elif s["ultimo_entregue"]:
        u = s["ultimo_entregue"]
        quando = (f" em {_fmt_data(date.fromisoformat(u['data_entrega']))}"
                  if u["data_entrega"] else "")
        verbo = "homologado" if s["sistema"] == "SIOPS" else "declarado"
        partes.append(f"Último bimestre {verbo} no {s['sistema']}: {u['rotulo']}{quando}.")
        # O alarme falso, dito na tela: o bimestre que esta validade cobra já
        # foi entregue, e é o Tesouro que ainda não processou.
        if validade_cauc:
            ano, b = bimestre_do_prazo(validade_cauc)
            if any(x["ano"] == ano and x["bimestre"] == b and x["entregue"]
                   for x in s["bimestres"]):
                partes.append(f"A validade de {_fmt_data(validade_cauc)} no CAUC é do "
                              f"{rotulo_bimestre(ano, b)}, que já foi entregue — "
                              f"o extrato renova quando o Tesouro processar.")
                tom = "ok"
        if s["proximo"] and s["proximo"]["situacao"] == "no_prazo":
            p = s["proximo"]
            partes.append(f"Próximo: {p['rotulo']}, até "
                          f"{_fmt_data(date.fromisoformat(p['prazo']))}.")
    if s["sem_informacao"] and not partes:
        partes.append(f"A fonte ({s['sistema']}) ainda não respondeu por este município.")
    return {"texto": " ".join(partes), "tom": tom} if partes else None


def nota_minimo(s: dict) -> Optional[dict]:
    """A frase ao lado do item 5.1/5.2: o percentual, dito como PARCIAL."""
    partes, tom = [], None
    u = s["ultimo_pct"]
    if u and u["parcial"]:
        partes.append(f"Aplicado até o {u['rotulo']}: {_fmt_pct(u['pct'])} "
                      f"(parcial — o mínimo de {s['minimo']:.0f}% se apura no ano).")
    a = s["ano_fechado"]
    if a:
        partes.append(f"Ano {a['ano']} fechado: {_fmt_pct(a['pct'])}.")
        if a["tom_pct"] == "critico":
            tom = "critico"
    return {"texto": " ".join(partes), "tom": tom} if partes else None


def montar_instrumentos(linhas: Iterable[dict], hoje: date) -> list[dict]:
    """Uma linha por instrumento × ano, do mais novo para o mais antigo, sem ano
    futuro (a fonte lista 2027-2029 como "Não Iniciado" — é calendário, não
    pendência)."""
    out = []
    for l in linhas:
        ano = int(l["ano"])
        instr = l["instrumento"]
        if ano > hoje.year:
            continue
        classe = classe_situacao(l.get("situacao"))
        prazo = prazo_instrumento(instr, ano)
        vencido = bool(prazo and prazo < hoje and classe == "pendente")
        out.append({
            "instrumento": instr,
            "rotulo": INSTRUMENTOS.get(instr, instr),
            "ano": ano,
            "periodo": l.get("periodo"),
            "situacao": l.get("situacao"),
            "classe": classe,
            "prazo": _iso(prazo),
            "vencido": vencido,
        })
    ordem = {k: i for i, k in enumerate(ORDEM_INSTRUMENTOS)}
    out.sort(key=lambda x: (-x["ano"], ordem.get(x["instrumento"], 99)))
    return out


def montar(bimestres: Iterable[dict], instrumentos: Iterable[dict], hoje: date,
           validades_cauc: Optional[dict] = None) -> dict:
    """O payload inteiro de `/api/saude-educacao`.

    `validades_cauc`: {codigo: date} dos itens 3.2.3/3.2.4 que o extrato do CAUC
    trouxe com data — é o que permite a nota dizer "essa validade já foi
    cumprida"."""
    bimestres = list(bimestres)
    instrumentos = list(instrumentos)
    validades_cauc = validades_cauc or {}
    sistemas = {}
    notas = {}
    for sis in SISTEMAS:
        linhas = [b for b in bimestres if b["sistema"] == sis]
        s = montar_sistema(sis, linhas, hoje)
        sistemas[sis] = s
        n = nota_envio(s, validades_cauc.get(s["item_envio"]))
        if n:
            notas[s["item_envio"]] = n
        n = nota_minimo(s)
        if n:
            notas[s["item_minimo"]] = n
    instr = montar_instrumentos(instrumentos, hoje)
    return {
        "tem_dados": bool(bimestres or instrumentos),
        "sistemas": sistemas,
        "notas_cauc": notas,
        "instrumentos": instr,
        "instrumentos_vencidos": sum(1 for i in instr if i["vencido"]),
        "alerta": any(s["atrasados"] for s in sistemas.values())
                  or any(i["vencido"] or i["classe"] == "reprovado" for i in instr),
    }
