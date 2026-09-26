"""
FNAS — o dinheiro da ASSISTÊNCIA SOCIAL no fundo municipal: o saldo de cada conta
mês a mês, cada repasse (OB) do FNAS e as emendas com o parlamentar.

Fonte: o painel "Repasses Fundo a Fundo" do MDS (Qlik Sense), que abre sessão
ANÔNIMA pelo websocket do engine — o mesmo que o navegador usa:

    https://paineis.mds.gov.br/public/extensions/RFF/RFF.html   (a página)
    wss://paineis.mds.gov.br/public/app/<id do app>              (o engine)

Três dos quatro apps que a página abre (os ids estão em `RFF.js`):
    saldos   01c7b0a9-... "Painel Repasses Fundo a Fundo - Saldos"  (TB_SUAS, 13,2 mi linhas)
    repasses d210fa5c-... "Painel Repasses Fundo a Fundo"           (TB_PLANDEM, 7,4 mi, desde 2008)
    emendas  7ee60957-... "Painel RFF Emendas"                       (TB_PLANDEM, 24.667)

O que só esta fonte tem: o SALDO DA CONTA do fundo municipal, todo mês. A CGU
(`cgu_transferencias`) dá quanto o FNAS mandou no mês; o SUASWeb tem uma consulta
de saldo, mas com hCaptcha conferido no servidor. Monte Sião, 08/2026: R$ 890 mil
em 15 contas — R$ 207 mil numa conta que recebeu emenda em 2020 e 2021 e só
rendeu juros desde então.

AS ARMADILHAS, medidas em 26/09/2026:

1. **NÃO HÁ API NEM ARQUIVO: É O ENGINE DO QLIK.** A conversa é JSON-RPC no
   websocket: `OpenDoc` → `CreateSessionObject` (um hipercubo com as dimensões e
   as medidas) → `GetHyperCubeData` paginado (≤ 10.000 células por página). O
   filtro é uma SET EXPRESSION dentro de cada medida — nada de seleção na
   sessão, que é compartilhada pelo usuário anônimo.
   Diferente do InvestSUS (websocket 403 fora do navegador): aqui a VPS abre o
   websocket (101) sem cookie, medido pela sonda em 26/09/2026.

2. ⚠️ **FILTRO ERRADO NÃO DÁ ERRO, DÁ O BRASIL** (a mesma armadilha das APIs do
   TransfereGov): campo inexistente na set expression é ignorado e o cubo volta
   com todos os municípios. Toda linha é conferida contra os IBGEs pedidos; uma
   só de fora e a rodada é `error`, nada gravado. E há um teto de linhas por
   município.

3. ⚠️ **DIMENSÃO NULA SOME COM A LINHA.** Com `qNullSuppression` numa dimensão
   que vem vazia (DT_ENTREGA_RECURSO, DT_ENVIO_SIAFI, NU_GND em quase todo
   repasse), o cubo devolve ZERO linhas — medido: 0 com essas colunas, 5 sem
   elas. Só a primeira dimensão (a chave) suprime nulo; nas outras, nulo vem como
   "-" e vira None.

4. ⚠️ **ZEROS À ESQUERDA EM QUANTIDADE VARIÁVEL.** A mesma conta é
   "000000197475" nas OBs até 08/2026 e "0000197475" nas de 09/2026; no saldo é
   "197475". Conta e agência são gravadas SEM os zeros — é assim que o repasse
   casa com a conta que recebeu.

5. ⚠️ **O ANO FILTRA POR VALOR, NUNCA POR BUSCA.** `NU_ANO_SALDO={2026}` filtra;
   `NU_ANO_SALDO={">=2025"}` devolve ZERO linhas (sem erro) — a janela vai como
   lista explícita de anos (`{2025,2026,2027}`). E o mês é texto:
   `NU_MES_EXERCICIO={8}` não filtra, `{'08'}` sim. O coletor filtra só por ano.

6. **O APP "ÚLTIMOS 4 ANOS" CORTA O ANO MAIS VELHO.** Monte Sião 2022: R$ 42 mil
   nele, R$ 327 mil no app completo. Lê-se o COMPLETO (`repasses`), com o ano
   no filtro.

7. **UMA LINHA POR (CONTA, MÊS) NO SALDO** — medido em Monte Sião, Nova Palma e
   Santa Maria, 2026 inteiro. Mesmo assim o cubo leva `Count(VL_TOTAL)`: conta
   com duas linhas no mesmo mês seria somada, e o coletor avisa (nota) em vez
   de gravar dinheiro em dobro calado. O Count também impede que a conta
   ZERADA suma do cubo (`qSuppressZero` descarta linha com todas as medidas 0).

8. **O FUNDO ESTADUAL NÃO SE MISTURA** (medido em Porto Alegre e Santa Maria:
   só `CO_ESFERA_ADMINISTRATIVA = MUNICIPAL` sob o IBGE do município). O filtro
   de esfera vai assim mesmo, porque o custo é zero.

9. **A CHAVE DO REPASSE É `CO_PROCESSO_ENTIDADE`** (1.594.570 valores em
   1.594.570 linhas). No app de emendas ela se repete em 4 de 24.667 linhas
   (dois autores): a emenda é (processo, parlamentar).

10. **O PAINEL É RECARREGADO TODO DIA** (`DH_CARGA`: saldos 25/09 09:47, repasses
    25/09 07:30). O saldo mais novo em 26/09/2026 era o de 08/2026 — o mês de
    referência vem do dado, nunca da data de hoje.

A RODADA (uma por tenant, todos os municípios ativos num cubo por app):
- município sem carga completa (`fnas_carga.historico`): tudo, desde 2008/2011;
- os outros: saldo e repasses do ano passado para cá (a janela é TROCADA
  inteira numa transação: conta que sumiu do painel some daqui); emendas,
  inteiras (são poucas).
Janela vazia para um município que já tinha dado = `partial`, nada apagado.

Rodável por Scheduled Task ou à mão:
    python -u ingestion/fnas_suas.py            # coleta de verdade
    python -u ingestion/fnas_suas.py --dry      # lê e mostra, não grava
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

log = logging.getLogger("fnas_suas")

FONTE = "fnas_suas"
HOST = "paineis.mds.gov.br"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (PACTHA/1.0; dados abertos MDS)"
APPS = {
    "saldo": "01c7b0a9-2755-400e-acca-d6fb6f2d8af1",
    "repasse": "d210fa5c-8a40-4def-a6fa-8c30d3e4a05c",
    "emenda": "7ee60957-baa0-418c-a9d8-6ddc6ec69af9",
}
TIMEOUT_S = int(os.getenv("FNAS_TIMEOUT_S") or 180)
CELULAS_POR_PAGINA = 10000
# Armadilha 2: teto por município. Saldo: 185 meses x ~20 contas; repasse: ~60
# OBs/ano desde 2008; emenda: dezenas. Acima disso o filtro não filtrou.
TETO_POR_MUNICIPIO = {"saldo": 12000, "repasse": 6000, "emenda": 600}
BRT = timezone(timedelta(hours=-3))

# (campo do painel, chave no dict) — a PRIMEIRA é a que suprime nulo (armadilha 3).
DIM_SALDO = (
    ("CO_IBGE", "ibge"), ("ANO_MES_SALDO", "ano_mes"), ("NU_CGC_ENTIDADE", "cnpj"),
    ("DS_TIPO_ENTIDADE", "tipo_entidade"), ("CO_AGENCIA", "agencia"),
    ("NU_CONTA_CORRENTE", "conta"), ("TIPO_CONTA_BLOCO", "bloco"),
    ("DS_TIPO_CONTA", "tipo_conta"), ("ST_MONITORAMENTO_SALDO", "monitorado"),
)
MED_SALDO = (
    ("Sum", "VL_CONTA_CORRENTE", "vl_conta_corrente"), ("Sum", "VL_POUPANCA", "vl_poupanca"),
    ("Sum", "VL_FUNDOS", "vl_fundos"), ("Sum", "VL_CDB_RDB", "vl_cdb_rdb"),
    ("Sum", "VL_TOTAL", "vl_total"), ("Count", "VL_TOTAL", "n"),
)
DIM_REPASSE = (
    ("CO_PROCESSO_ENTIDADE", "processo_entidade"), ("CO_IBGE", "ibge"),
    ("NU_ANO_EXERCICIO", "ano"), ("NU_MES_EXERCICIO", "mes"), ("NU_CGC_ENTIDADE", "cnpj"),
    ("DS_TIPO_PROGRAMA", "bloco"), ("GRUPO2", "grupo"), ("DS_PISO_PAI", "piso"),
    ("NO_PROGRAMA_RESUMIDO", "programa"), ("DS_TIPO_EXECUCAO", "tipo_execucao"),
    ("NU_OB_SIAFI", "ob"), ("DT_CRIACAO_SIAFI", "dt_ob"), ("CO_AGENCIA", "agencia"),
    ("NU_CONTA_CORRENTE", "conta"), ("NU_PROCESSO", "processo"),
)
MED_REPASSE = (("Sum", "VL_LIQUIDO", "valor"), ("Count", "VL_LIQUIDO", "n"))
DIM_EMENDA = (
    ("CO_PROCESSO_ENTIDADE", "processo_entidade"), ("CO_IBGE", "ibge"),
    ("NO_PARLAMENTAR", "parlamentar"), ("SG_PARTIDO_POLITICO", "partido"),
    ("TIPO_EMENDA", "tipo_emenda"), ("DS_PROGRAMA_FUNDO", "programa"),
    ("NU_ANO_EXERCICIO", "ano"), ("NU_MES_EXERCICIO", "mes"), ("NU_OB_SIAFI", "ob"),
    ("DT_CRIACAO_SIAFI", "dt_ob"), ("CO_AGENCIA", "agencia"),
    ("NU_CONTA_CORRENTE", "conta"), ("NU_GND", "gnd"), ("NU_PROCESSO", "processo"),
)
MED_EMENDA = MED_REPASSE
CAMPO_ANO = {"saldo": "NU_ANO_SALDO", "repasse": "NU_ANO_EXERCICIO"}


class FiltroIgnorado(RuntimeError):
    """O cubo trouxe município que não foi pedido (armadilha 2)."""


# ---------------------------------------------------------------------------
# Células e linhas (puro)
# ---------------------------------------------------------------------------
def txt(cel: dict) -> str | None:
    """Texto da célula; nulo do Qlik ("-", qIsNull) vira None."""
    if cel.get("qIsNull"):
        return None
    s = (cel.get("qText") or "").strip()
    return None if s in ("", "-") else s


def num(cel: dict) -> Decimal:
    v = cel.get("qNum")
    if isinstance(v, (int, float)) and v == v:          # NaN != NaN
        return Decimal(str(round(v, 2)))
    s = (cel.get("qText") or "").strip().replace(",", "")
    try:
        return Decimal(s) if s not in ("", "-") else Decimal("0")
    except Exception:
        return Decimal("0")


def sem_zeros(v: str | None) -> str | None:
    """Armadilha 4: "000000197475" e "0000197475" são "197475"."""
    if not v:
        return None
    s = v.strip().lstrip("0")
    return s or "0"


def data_qlik(v: str | None) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def inteiro(v: str | None) -> int | None:
    s = re.sub(r"\D", "", v or "")
    return int(s) if s else None


def dh_carga(v: str | None) -> datetime | None:
    """`DH_CARGA` vem como "9/25/2026 9:47:56 AM" (hora do MDS)."""
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime((v or "").strip(), fmt)
        except ValueError:
            continue
    return None


def linha(row: list[dict], dims: tuple, meds: tuple) -> dict:
    d = {chave: txt(c) for (_campo, chave), c in zip(dims, row)}
    for (_f, _campo, chave), c in zip(meds, row[len(dims):]):
        d[chave] = num(c)
    return d


def reg_saldo(d: dict) -> dict | None:
    ano_mes = inteiro(d["ano_mes"])
    if not ano_mes or not d.get("conta"):
        return None
    return {
        "ibge": d["ibge"], "ano_mes": ano_mes,
        "cnpj": re.sub(r"\D", "", d.get("cnpj") or "").zfill(14),
        "tipo_entidade": d.get("tipo_entidade"),
        "agencia": sem_zeros(d.get("agencia")) or "", "conta": sem_zeros(d["conta"]),
        "bloco": d.get("bloco"), "tipo_conta": d.get("tipo_conta"),
        "monitorado": None if d.get("monitorado") is None else d["monitorado"].upper() == "S",
        "vl_conta_corrente": d["vl_conta_corrente"], "vl_poupanca": d["vl_poupanca"],
        "vl_fundos": d["vl_fundos"], "vl_cdb_rdb": d["vl_cdb_rdb"], "vl_total": d["vl_total"],
        "n": int(d["n"]),
    }


def reg_repasse(d: dict) -> dict | None:
    pe, ano = inteiro(d["processo_entidade"]), inteiro(d.get("ano"))
    if not pe or not ano:
        return None
    return {
        "ibge": d["ibge"], "processo_entidade": pe, "ano": ano, "mes": inteiro(d.get("mes")),
        "cnpj": re.sub(r"\D", "", d.get("cnpj") or "").zfill(14) if d.get("cnpj") else None,
        "bloco": d.get("bloco"), "grupo": d.get("grupo"), "piso": d.get("piso"),
        "programa": d.get("programa"), "tipo_execucao": d.get("tipo_execucao"),
        "ob": d.get("ob"), "dt_ob": data_qlik(d.get("dt_ob")),
        "agencia": sem_zeros(d.get("agencia")), "conta": sem_zeros(d.get("conta")),
        "processo": d.get("processo"), "valor": d["valor"],
    }


def reg_emenda(d: dict) -> dict | None:
    pe = inteiro(d["processo_entidade"])
    if not pe:
        return None
    return {
        "ibge": d["ibge"], "processo_entidade": pe,
        "parlamentar": d.get("parlamentar") or "(sem autor no painel)",
        "partido": d.get("partido"), "tipo_emenda": d.get("tipo_emenda"),
        "programa": d.get("programa"), "ano": inteiro(d.get("ano")), "mes": inteiro(d.get("mes")),
        "ob": d.get("ob"), "dt_ob": data_qlik(d.get("dt_ob")),
        "agencia": sem_zeros(d.get("agencia")), "conta": sem_zeros(d.get("conta")),
        "gnd": d.get("gnd"), "processo": d.get("processo"), "valor": d["valor"],
    }


REG = {"saldo": (DIM_SALDO, MED_SALDO, reg_saldo),
       "repasse": (DIM_REPASSE, MED_REPASSE, reg_repasse),
       "emenda": (DIM_EMENDA, MED_EMENDA, reg_emenda)}


def set_expr(ibges: list[str], campo_ano: str | None = None, ano_desde: int | None = None) -> str:
    """O filtro de cada medida. IBGE de 6 dígitos (é como o painel grava)."""
    partes = ["CO_IBGE={%s}" % ",".join(sorted(set(ibges))),
              "CO_ESFERA_ADMINISTRATIVA={'MUNICIPAL'}"]
    if campo_ano and ano_desde:
        # Armadilha 5: a busca `{">=2025"}` devolve ZERO linhas (o ano não é
        # número para a busca); a lista explícita de anos filtra.
        ate = max(ano_desde, datetime.now(BRT).year + 1)
        partes.append("%s={%s}" % (campo_ano, ",".join(str(a) for a in range(ano_desde, ate + 1))))
    return "{<" + ",".join(partes) + ">}"


def cubo_def(dims: tuple, meds: tuple, filtro: str) -> dict:
    return {
        "qInfo": {"qType": "pactha-fnas"},
        "qHyperCubeDef": {
            "qDimensions": [{"qDef": {"qFieldDefs": [campo]}, "qNullSuppression": i == 0}
                            for i, (campo, _k) in enumerate(dims)],
            "qMeasures": [{"qDef": {"qDef": f"{f}({filtro} {campo})"}} for f, campo, _k in meds],
            "qSuppressZero": True,
            "qSuppressMissing": True,
            "qInitialDataFetch": [],
        },
    }


def confere(regs: list[dict], ibges: set[str], app: str) -> dict[str, list[dict]]:
    """Separa por IBGE; município não pedido = filtro ignorado (armadilha 2)."""
    por: dict[str, list[dict]] = {i: [] for i in ibges}
    fora = {r["ibge"] for r in regs if r["ibge"] not in ibges}
    if fora:
        raise FiltroIgnorado(f"{app}: o painel devolveu {len(fora)} município(s) não "
                             f"pedido(s) (ex.: {sorted(fora)[:3]}) — o filtro foi ignorado")
    for r in regs:
        por[r["ibge"]].append(r)
    teto = TETO_POR_MUNICIPIO[app]
    for i, lst in por.items():
        if len(lst) > teto:
            raise FiltroIgnorado(f"{app}: {len(lst)} linhas para o IBGE {i} (teto {teto})")
    return por


# ---------------------------------------------------------------------------
# O engine (websocket)
# ---------------------------------------------------------------------------
class Engine:
    def __init__(self, app: str):
        self.app, self.appid, self.ws, self.i, self.h = app, APPS[app], None, 0, None

    def __enter__(self):
        from websockets.sync.client import connect
        self.ws = connect(f"wss://{HOST}/public/app/{self.appid}",
                          additional_headers={"Origin": f"https://{HOST}", "User-Agent": UA},
                          max_size=2 ** 27, open_timeout=60, close_timeout=10)
        self.ws.recv(timeout=TIMEOUT_S)                 # OnAuthenticationInformation
        self.h = self.rpc("OpenDoc", -1, [self.appid])["qReturn"]["qHandle"]
        return self

    def __exit__(self, *exc):
        try:
            self.ws.close()
        except Exception:
            pass

    def rpc(self, metodo: str, handle: int, params: list) -> dict:
        self.i += 1
        self.ws.send(json.dumps({"jsonrpc": "2.0", "id": self.i, "method": metodo,
                                 "handle": handle, "params": params}))
        fim = time.monotonic() + TIMEOUT_S
        while True:
            m = json.loads(self.ws.recv(timeout=max(1, fim - time.monotonic())))
            if m.get("id") == self.i:
                if "error" in m:
                    raise RuntimeError(f"Qlik {metodo}: {m['error']}")
                return m["result"]

    def matriz(self, defs: dict, ncol: int):
        """Todas as linhas do cubo, página a página."""
        o = self.rpc("CreateSessionObject", self.h, [defs])["qReturn"]["qHandle"]
        total = self.rpc("GetLayout", o, [])["qLayout"]["qHyperCube"]["qSize"]["qcy"]
        passo = max(1, CELULAS_POR_PAGINA // ncol)
        topo = 0
        while topo < total:
            r = self.rpc("GetHyperCubeData", o, ["/qHyperCubeDef", [
                {"qTop": topo, "qLeft": 0, "qWidth": ncol, "qHeight": min(passo, total - topo)}]])
            for row in r["qDataPages"][0]["qMatrix"]:
                yield row
            topo += passo
        # O objeto de sessão morre com o websocket (`__exit__`).

    def dh_carga(self) -> datetime | None:
        defs = {"qInfo": {"qType": "pactha-fnas"}, "qHyperCubeDef": {
            "qDimensions": [{"qDef": {"qFieldDefs": ["DH_CARGA"]}}],
            "qMeasures": [{"qDef": {"qDef": "Count(DH_CARGA)"}}], "qInitialDataFetch": []}}
        for row in self.matriz(defs, 2):
            return dh_carga(txt(row[0]))
        return None


def ler_app(app: str, ibges: list[str], ano_desde: int | None) -> tuple[list[dict], datetime | None]:
    dims, meds, reg = REG[app]
    filtro = set_expr(ibges, CAMPO_ANO.get(app), ano_desde)
    regs: list[dict] = []
    with Engine(app) as e:
        carga = e.dh_carga()
        for row in e.matriz(cubo_def(dims, meds, filtro), len(dims) + len(meds)):
            r = reg(linha(row, dims, meds))
            if r:
                regs.append(r)
    return regs, carga


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
@dataclass
class Alvo:
    id: int
    nome: str
    ibge6: str


@dataclass
class Rodada:
    gravadas: int = 0
    parcial: bool = False
    notas: list[str] = field(default_factory=list)


def _alvos(cur) -> list[Alvo]:
    cur.execute("SELECT id, nome, coalesce(ibge_code::text, '') FROM municipios "
                "WHERE active ORDER BY id")
    out = []
    for mid, nome, ibge in cur.fetchall():
        d = re.sub(r"\D", "", ibge)
        if len(d) >= 6:
            out.append(Alvo(mid, nome, d[:6]))
    return out


def _cargas(cur) -> dict[tuple[int, str], bool]:
    cur.execute("SELECT municipio_id, app, historico FROM fnas_carga")
    return {(m, a): h for m, a, h in cur.fetchall()}


TABELA = {"saldo": "fnas_saldo_conta", "repasse": "fnas_repasse", "emenda": "fnas_emenda"}
COLS = {
    "saldo": ("ano_mes", "cnpj", "tipo_entidade", "agencia", "conta", "bloco", "tipo_conta",
              "monitorado", "vl_conta_corrente", "vl_poupanca", "vl_fundos", "vl_cdb_rdb",
              "vl_total"),
    "repasse": ("processo_entidade", "ano", "mes", "cnpj", "bloco", "grupo", "piso", "programa",
                "tipo_execucao", "ob", "dt_ob", "agencia", "conta", "processo", "valor"),
    "emenda": ("processo_entidade", "parlamentar", "partido", "tipo_emenda", "programa", "ano",
               "mes", "ob", "dt_ob", "agencia", "conta", "gnd", "processo", "valor"),
}


def _apaga(cur, app: str, mid: int, ano_desde: int | None) -> None:
    if app == "saldo" and ano_desde:
        cur.execute("DELETE FROM fnas_saldo_conta WHERE municipio_id = %s AND ano_mes >= %s",
                    (mid, ano_desde * 100))
    elif app == "repasse" and ano_desde:
        cur.execute("DELETE FROM fnas_repasse WHERE municipio_id = %s AND ano >= %s",
                    (mid, ano_desde))
    else:
        cur.execute(f"DELETE FROM {TABELA[app]} WHERE municipio_id = %s", (mid,))


def _tinha(cur, app: str, mid: int) -> bool:
    cur.execute(f"SELECT 1 FROM {TABELA[app]} WHERE municipio_id = %s LIMIT 1", (mid,))
    return cur.fetchone() is not None


def grava(cur, app: str, a: Alvo, regs: list[dict], ano_desde: int | None,
          carga: datetime | None) -> tuple[int, str | None]:
    """Troca a janela (ou tudo) do município numa transação. (gravadas, recusa)."""
    import psycopg2.extras
    if not regs and app != "emenda":
        # Todo município tem fundo com conta e piso mensal: janela vazia não é
        # plausível. Nada apagado, e a carga não é registrada.
        return 0, f"{app}: nenhuma linha no painel{' desde ' + str(ano_desde) if ano_desde else ''}"
    if app == "saldo":
        dup = sum(1 for r in regs if r["n"] > 1)
        if dup:
            log.warning("%s: %d conta(s)-mês com mais de uma linha no painel", a.nome, dup)
    _apaga(cur, app, a.id, ano_desde)
    cols = COLS[app]
    sql = (f"INSERT INTO {TABELA[app]} (municipio_id, {', '.join(cols)}) VALUES %s "
           "ON CONFLICT DO NOTHING")
    psycopg2.extras.execute_values(cur, sql, [(a.id, *(r[c] for c in cols)) for r in regs],
                                   page_size=500)
    cur.execute("""
        INSERT INTO fnas_carga (municipio_id, app, historico, linhas, painel_em, lido_em)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (municipio_id, app) DO UPDATE SET
            historico = fnas_carga.historico OR EXCLUDED.historico,
            linhas = EXCLUDED.linhas, painel_em = EXCLUDED.painel_em, lido_em = NOW()
    """, (a.id, app, ano_desde is None, len(regs), carga))
    return len(regs), None


def _log_ingest(cur, conn, status: str, n: int, nota: str | None = None) -> None:
    try:
        cur.execute(
            "INSERT INTO ingestion_log (source, status, records_inserted, "
            "error_message, finished_at) VALUES (%s, %s, %s, %s, NOW())",
            (FONTE, status, n, nota))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])


def rodar_app(cur, conn, app: str, alvos: list[Alvo], cargas: dict, ano_desde: int,
              rod: Rodada, dry: bool) -> None:
    """Dois cubos no máximo: os municípios com histórico (janela) e os sem (tudo)."""
    novos = [a for a in alvos if not cargas.get((a.id, app))]
    velhos = [a for a in alvos if cargas.get((a.id, app))]
    grupos = [(velhos, None if app == "emenda" else ano_desde), (novos, None)]
    for grupo, desde in grupos:
        if not grupo:
            continue
        t = time.monotonic()
        regs, carga = ler_app(app, [a.ibge6 for a in grupo], desde)
        por = confere(regs, {a.ibge6 for a in grupo}, app)
        log.info("%s: %d linha(s) de %d município(s) (%s; painel de %s; %.1f s)", app,
                 len(regs), len(grupo), f"desde {desde}" if desde else "tudo", carga,
                 time.monotonic() - t)
        for a in grupo:
            lst = por.get(a.ibge6, [])
            if dry:
                if app == "saldo" and lst:
                    ult = max(r["ano_mes"] for r in lst)
                    tot = sum(r["vl_total"] for r in lst if r["ano_mes"] == ult)
                    log.info("   %s: %d linha(s); saldo em %d: R$ %s", a.nome, len(lst), ult, tot)
                else:
                    log.info("   %s: %d linha(s)", a.nome, len(lst))
                continue
            if not lst and app != "emenda" and desde and not _tinha(cur, app, a.id):
                # Janela vazia de quem nunca teve linha nenhuma: não é regressão.
                continue
            try:
                n, recusa = grava(cur, app, a, lst, desde, carga)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            if recusa:
                rod.parcial = True
                rod.notas.append(f"{a.nome}: {recusa}")
            rod.gravadas += n


def ingest(dry: bool = False) -> int:
    from ingestion._resilience import get_sync_db_url, neon_connect

    rod = Rodada()
    with neon_connect(get_sync_db_url()) as conn:
        cur = conn.cursor()
        try:
            alvos = _alvos(cur)
            if not alvos:
                if not dry:
                    _log_ingest(cur, conn, "success", 0, "nenhum município ativo")
                return 0
            cargas = _cargas(cur)
            ano_desde = datetime.now(BRT).year - 1
            for app in ("saldo", "repasse", "emenda"):
                rodar_app(cur, conn, app, alvos, cargas, ano_desde, rod, dry)
            if dry:
                return 0
            status = "partial" if rod.parcial else "success"
            nota = "; ".join(rod.notas)[:480] or f"{len(alvos)} município(s)"
            _log_ingest(cur, conn, status, rod.gravadas, nota)
            return rod.gravadas
        except Exception as e:
            conn.rollback()
            log.error("FNAS falhou: %s: %s", type(e).__name__, str(e)[:200])
            if not dry:
                _log_ingest(cur, conn, "error", rod.gravadas, f"{type(e).__name__}: {str(e)[:380]}")
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    ingest(dry="--dry" in sys.argv)
