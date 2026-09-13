#!/usr/bin/env python3
"""Agenda da coleta noturna — TODO municipio de TODO cliente, TODO dia, entre 19h e 7h.

REGRA DO DONO (13/09/2026), literal: *"nao existe cliente grande e cliente pequeno,
TODOS os municipios devem ser atualizados todos os dias para que esteja pronto de
manha para as equipes trabalharem [...] todos os clientes devem rodar coleta a partir
das 19h ate as 7h da manha do outro dia, TODOS [...] isso e regra, daqui a pouco eu
pego mais 20 clientes novos e tera que ser assim tb"*.

O que motivou: a BGK rodava o lote do TransfereGov 1x/dia com 1 municipio por rodada
(ciclo de 10 dias — Bento Goncalves ficou 5 dias sem detalhe) e o SIGCON da Freitas
visitava 1-3 municipios por noite (ciclo de ~10 dias). Nenhum dos dois era limite da
maquina: era agenda.

ESTE ARQUIVO E A FONTE DA AGENDA DAS TASKS DE RODIZIO. As demais tasks continuam como
estao no Coolify (fonte de verdade de tudo o que nao esta aqui), mas TODAS passam pela
auditoria da janela.

    python scripts/agenda_noturna.py                 # audita a agenda REAL do Coolify
    python scripts/agenda_noturna.py --plano         # audita a agenda que o PLANO produziria
    python scripts/agenda_noturna.py --carga         # + capacidade: cabe todo municipio todo dia?
    python scripts/agenda_noturna.py --aplicar       # grava o PLANO no Coolify e audita de novo

⚠️ `--aplicar` PODE DISPARAR TASKS NA HORA: o Coolify roda na mesma hora a task cujo cron
NOVO tem ocorrencia mais recente que a ultima execucao (medido em 13/09/2026: dois lotes
do TransfereGov de ~24 min e uma base diaria rodaram 1 min depois). Aplique fora da
janela noturna e com nada pesado rodando.

Precisa de COOLIFY_TOKEN no ambiente (no Windows do dono ela mora na env de USUARIO:
`[Environment]::GetEnvironmentVariable('COOLIFY_TOKEN','User')`).

CLIENTE NOVO: (1) crie as tasks dele no Coolify como nos outros; (2) acrescente o bloco
dele em PLANO usando um slot que a auditoria lista como LIVRE no portal do TransfereGov;
(3) `--carga` para ver se o numero de rodadas cobre a carteira; (4) `--aplicar`.
Quando os slots livres acabarem, a regra NAO deixa de valer — o que muda e o desenho
(ver "Quando nao couber" no INFRA.md §5).

TUDO EM UTC. Brasilia = UTC-3. A janela 19h-07h BRT e 22:00-10:00 UTC.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

COOLIFY = "http://54.232.208.118:8000/api/v1"
WORKFLOW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".github",
                        "workflows", "build-backend.yml")

# --- A janela ---------------------------------------------------------------
JANELA_INICIO_MIN = 22 * 60          # 22:00 UTC = 19h BRT
JANELA_FIM_MIN = 10 * 60             # 10:00 UTC = 07h BRT (dia seguinte)
# O Coolify reinicia perto das 00:00 UTC e marca como falha o que estiver rodando
# (INFRA.md §5). Nenhuma coleta pode ATRAVESSAR este instante.
REINICIO_COOLIFY_MIN = 0

# Tasks que NAO sao coleta: sessao, vigia, fila on-demand, motor de alertas.
INFRA = {"watchdog", "govbr-renew", "private-keepalive", "queue-sigcon", "painel-alertas"}

# Excecoes a janela — cada uma com o motivo. So entra aqui o que a FONTE impoe.
EXCECOES = {
    "cauc-manha": "o Tesouro so publica o extrato do dia entre 07h e 09h20 BRT; a task "
                  "insiste de hora em hora ate a data virar (HTTP, ~2 s). A coleta noturna "
                  "pega o arquivo mais novo que existe as 7h, que e o de ontem.",
}

# --- Travas -----------------------------------------------------------------
# Ate 13/09/2026 sigcon, transferegov(-lote) e cagec dividiam /tmp/scraper.lock por
# worker — heranca do t3.large de 2 vCPU, onde dois Chromium derrubavam o host. Com
# 8 vCPU (medido: seis workers em coleta = load 3,97) a trava unica virou o gargalo:
# a Freitas precisaria de ~12h de trava para SIGCON + TransfereGov + CAGEC em fila.
# Agora cada PORTAL tem a sua; o que continua serializado e o mesmo portal.
TRAVA_TG = "/tmp/transferegov.lock"
TRAVA_SIGCON = "/tmp/sigcon.lock"
TRAVA_CAGEC = "/tmp/cagec.lock"

SUFIXO = "2>&1; rc=$?; if [ $rc = 99 ]; then rc=0; fi; exit $rc"

# Lote do TransfereGov: orcamento de 24 min numa grade de slots de 30 min. O prazo e
# ABSOLUTO dentro do municipio (para no meio do detalhe e grava), entao o estouro e a
# listagem de um municipio: +5 min de kill externo sobram. TG_LOTE_MUNICIPIOS=99 = "o
# que couber": quem limita e o orcamento, e o rodizio (ultima_coleta_em NULLS FIRST)
# retoma na rodada seguinte de onde parou. TG_HTTP_DETALHE=1 le o detalhe sem navegar
# (~0,7 s contra ~3 s por proposta) e cai no navegador sozinho se o HTTP falhar.
TG_ORCAMENTO_S = 1440
TG_KILL_S = TG_ORCAMENTO_S + 300
# Quantos lotes de clientes DIFERENTES podem estar no portal ao mesmo tempo. O limite
# e do PORTAL (todos os tenants saem do mesmo IP), nao da maquina — diretriz do dono em
# 13/09/2026: "a maquina agora e mais possante [...] nao tem muito problema rodar coisas
# em paralelo, a gente vai testando, se ver que ta estourando a gente baixa". Quando os
# slots livres acabarem, suba para 2, acompanhe uma noite (403, timeout, `detalhe
# parcial` no watchdog) e so entao pense em 3.
TG_FAIXAS = 1
CMD_LOTE = (f"TG_OPENDATA=0 TG_SKIP_ENRICH=0 TG_HTTP_DETALHE=1 TG_BUDGET_S={TG_ORCAMENTO_S} "
            f"TG_LOTE_MUNICIPIOS=99 flock -n -E 99 {TRAVA_TG} timeout -k 30 {TG_KILL_S} "
            f"python -u ingestion/transferegov_voluntarias.py lote {SUFIXO}")
TIMEOUT_LOTE = 2820

# SIGCON: a task `sigcon` (run_sigcon_cron) roda dados abertos + backfill CKAN + scraper
# — UMA vez por noite. As rodadas extras chamam o scraper DIRETO (`sigcon_scraper.py`)
# para nao repetir CAUC/FES/SIMEC-PAR a cada hora: o SIMEC tem protecao anti-robo e
# bater nele 10x por noite e pedir bloqueio. Orcamento 45 min, kill 50, reaper em 60.
SIGCON_ORCAMENTO_S = 2700
CMD_SIGCON_FREITAS = (f"SIGCON_INDICACOES=1 SIGCON_CONCURRENCY=1 SIGCON_LOTE_MUNICIPIOS=5 "
                      f"SIGCON_BUDGET_SECONDS={SIGCON_ORCAMENTO_S} flock -n -E 99 {TRAVA_SIGCON} "
                      f"timeout -k 30 3000 python -u ingestion/run_sigcon_cron.py {SUFIXO}")
CMD_SIGCON_RODIZIO = (f"SIGCON_INDICACOES=1 SIGCON_CONCURRENCY=1 SIGCON_LOTE_MUNICIPIOS=5 "
                      f"SIGCON_BUDGET_SECONDS={SIGCON_ORCAMENTO_S} flock -n -E 99 {TRAVA_SIGCON} "
                      f"timeout -k 30 3000 python -u ingestion/sigcon_scraper.py {SUFIXO}")

# CAGEC: o portal NAO emite o CRC de madrugada (medido 07/09: 03h15 BRT falha em toda
# entidade, 14h58 e 20h08 BRT emitem). Por isso ele abre a janela, as 19h. Sem
# orcamento interno: ~50 s por municipio, lote 22 = ~18 min, kill em 35.
CMD_CAGEC_FREITAS = (f"CAGEC_LOTE_MUNICIPIOS=22 flock -n -E 99 {TRAVA_CAGEC} "
                     f"timeout -k 30 2100 python -u ingestion/cagec_scraper.py {SUFIXO}")


def troca_trava(de: str, para: str):
    """Transformacao do comando ATUAL: so troca a trava, o resto fica como esta."""
    return lambda cmd: cmd.replace(de, para)


TG_BASE = troca_trava("/tmp/scraper.lock", TRAVA_TG)
SIGCON_TRAVA = troca_trava("/tmp/scraper.lock", TRAVA_SIGCON)
FILA_SIGCON = troca_trava("/tmp/q.lock", TRAVA_SIGCON)
CAGEC_TRAVA = troca_trava("/tmp/scraper.lock", TRAVA_CAGEC)

# --- O PLANO ----------------------------------------------------------------
# task -> {frequency, command (str = substitui | funcao = transforma o atual), timeout}
# `criar: True` = a task nao existe e deve ser criada.
#
# ⭐ GRADE DO PORTAL DO TRANSFEREGOV (lote), um cliente por vez — todos saem do mesmo
# IP. Slots de 30 min: 22:00 22:30 23:00 | 00:05 00:35 ... 09:05 09:35.
#   22:00 santamaria · 22:30 montesiao · 23:00 novapalma
#   :05 → trust  (00-04, 06-09 = 9 rodadas)      :35 → freitas (00-03, 05 = 5)
#   :35 → bgk    (04, 06-08 = 4)                  LIVRES: 05:05 · 09:35
# O `transferegov` (base diaria) de cada cliente fica FORA dos slots do proprio lote
# (mesma trava); ele pode cruzar com o lote de OUTRO cliente, como sempre cruzou.
PLANO: dict[str, dict[str, dict]] = {
    "freitas": {
        "transferegov-lote": {"frequency": "35 0-3,5 * * *", "command": CMD_LOTE, "timeout": TIMEOUT_LOTE},
        "transferegov":      {"frequency": "10 4 * * *", "command": TG_BASE, "timeout": 3120},
        "sigcon":            {"frequency": "5 5 * * *", "command": CMD_SIGCON_FREITAS, "timeout": 3120},
        "sigcon-rodizio":    {"frequency": "5 0-4,6-9,22 * * *", "command": CMD_SIGCON_RODIZIO,
                              "timeout": 3120, "criar": True},
        "queue-sigcon":      {"command": FILA_SIGCON},
        "cagec":             {"frequency": "0 22,23 * * *", "command": CMD_CAGEC_FREITAS, "timeout": 3420},
        "transparencia-mg":  {"frequency": "20 1,7 * * *"},
    },
    "trust": {
        "transferegov-lote": {"frequency": "5 0-4,6-9 * * *", "command": CMD_LOTE, "timeout": TIMEOUT_LOTE},
        "transferegov":      {"command": TG_BASE, "timeout": 3120},
        "sigcon":            {"command": SIGCON_TRAVA},
        "queue-sigcon":      {"command": FILA_SIGCON},
        "cagec":             {"frequency": "30 22 * * *", "command": CAGEC_TRAVA},
    },
    "montesiao": {
        "transferegov-lote": {"frequency": "30 22 * * *", "command": CMD_LOTE, "timeout": TIMEOUT_LOTE},
        "transferegov":      {"command": TG_BASE},
        "sigcon":            {"command": SIGCON_TRAVA},
        "queue-sigcon":      {"command": FILA_SIGCON},
        "cagec":             {"frequency": "45 22 * * *", "command": CAGEC_TRAVA},
        "faf-planos":        {"frequency": "5 8 * * *"},
    },
    "santamaria": {
        "transferegov-lote": {"frequency": "0 22 * * *", "command": CMD_LOTE, "timeout": TIMEOUT_LOTE},
        "transferegov":      {"command": TG_BASE},
        "faf-planos":        {"frequency": "15 8 * * *"},
        # FPE atende seg-sab 7h-22h30 BRT; CADIN idem ate 22h30. 19h BRT cabe nos dois.
        "fpe-rs":            {"frequency": "14 22 * * 1-6"},
        "cadin-rs":          {"frequency": "10 22 * * *"},
    },
    "novapalma": {
        "transferegov-lote": {"frequency": "0 23 * * *", "command": CMD_LOTE, "timeout": TIMEOUT_LOTE},
        "transferegov":      {"command": TG_BASE},
        "faf-planos":        {"frequency": "45 8 * * *"},
        "fpe-rs":            {"frequency": "44 22 * * 1-6"},
        "cadin-rs":          {"frequency": "40 22 * * *"},
    },
    "bgk": {
        "transferegov-lote": {"frequency": "35 4,6-8 * * *", "command": CMD_LOTE, "timeout": TIMEOUT_LOTE},
        # 06:00 e nao 06:32: com kill em 30 min, 06:05 encostava no slot 06:35 do lote.
        "transferegov":      {"frequency": "0 6 * * *", "command": TG_BASE},
        "faf-planos":        {"frequency": "55 8 * * *"},
        "fpe-rs":            {"frequency": "51 22 * * 1-6"},
        "cadin-rs":          {"frequency": "47 22 * * *"},
    },
}

# Custo medido, usado so por --carga (13/09/2026):
#   TransfereGov detalhe por HTTP ~0,7 s/proposta, +50% com TG_NES/TG_OPS_OBS ligados,
#   + ~40 s de listagem por municipio. SIGCON: 15-22 min por municipio (Bom Despacho
#   sozinho = 22 min; a rodada de 20 min da Freitas fechava 1 municipio).
#   CAGEC: ~50 s por municipio.
TG_S_POR_PROPOSTA = 1.05
TG_S_POR_MUNICIPIO = 40
SIGCON_S_POR_MUNICIPIO = 18 * 60
CAGEC_S_POR_MUNICIPIO = 50


# --- Coolify ----------------------------------------------------------------
def _token() -> str:
    t = os.getenv("COOLIFY_TOKEN", "").strip().strip('"\'').strip("<>").strip()
    if not t:
        sys.exit("defina COOLIFY_TOKEN no ambiente")
    return t


def _req(metodo: str, url: str, token: str, corpo: dict | None = None, cab: dict | None = None):
    h = {"Accept": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if cab:
        h.update(cab)
    dados = None
    if corpo is not None:
        dados = json.dumps(corpo).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=dados, headers=h, method=metodo)
    with urllib.request.urlopen(r, timeout=180) as resp:
        txt = resp.read().decode()
        return json.loads(txt) if txt else None


def tenants() -> dict[str, tuple[str, str]]:
    """nome -> (uuid da api, uuid do worker), lido do workflow que deploya os seis."""
    out = {}
    with open(WORKFLOW, encoding="utf-8") as f:
        for linha in f:
            m = re.match(r"^\s+([a-z0-9-]+):([a-z0-9]{20,}):([a-z0-9]{20,})\s*$", linha)
            if m:
                out[m.group(1)] = (m.group(2), m.group(3))
    return out


def tasks_reais(token: str, worker: str) -> list[dict]:
    return _req("GET", f"{COOLIFY}/applications/{worker}/scheduled-tasks", token) or []


# --- Cron -------------------------------------------------------------------
def _campo(expr: str, lo: int, hi: int) -> list[int]:
    vals: set[int] = set()
    for parte in expr.split(","):
        passo = 1
        if "/" in parte:
            parte, p = parte.split("/")
            passo = int(p)
        if parte == "*":
            a, b = lo, hi
        elif "-" in parte:
            a, b = (int(x) for x in parte.split("-"))
        else:
            a = b = int(parte)
        vals.update(range(a, b + 1, passo))
    return sorted(vals)


def disparos(freq: str) -> list[int]:
    """Minutos do dia (UTC) em que a task dispara. Dia do mes/semana nao entram:
    a pergunta aqui e SE o horario cabe na janela, nao em que dia."""
    mi, ho, *_ = freq.split()
    return [h * 60 + m for h in _campo(ho, 0, 23) for m in _campo(mi, 0, 59)]


def duracao_max_min(cmd: str) -> float:
    """O pior caso e o kill externo (`timeout -k 30 N`). Sem ele, 10 min."""
    m = re.search(r"timeout\s+-k\s+(\d+)\s+(\d+)", cmd or "")
    return (int(m.group(2)) + int(m.group(1))) / 60 if m else 10.0


def trava(cmd: str) -> str | None:
    m = re.search(r"flock\s+(?:-\S+\s+)*(/tmp/\S+\.lock)", cmd or "")
    return m.group(1) if m else None


def na_janela(ini: int, fim: float) -> bool:
    """[ini, fim] inteiro dentro de 22:00-10:00 UTC (fim pode passar de 1440)."""
    if ini >= JANELA_INICIO_MIN:
        return fim <= 1440 + JANELA_FIM_MIN
    return ini < JANELA_FIM_MIN and fim <= JANELA_FIM_MIN


def _hm(x: float) -> str:
    x = int(x) % 1440
    return f"{x // 60:02d}:{x % 60:02d}"


def _intervalos(t: dict) -> list[tuple[int, float]]:
    d = duracao_max_min(t["command"])
    return [(i, i + d) for i in disparos(t["frequency"])]


def _cruza(a: tuple[int, float], b: tuple[int, float]) -> bool:
    # em minutos do dia, considerando a volta da meia-noite
    for desl in (-1440, 0, 1440):
        if a[0] < b[1] + desl and b[0] + desl < a[1]:
            return True
    return False


# --- Plano -> estado desejado -------------------------------------------------
def aplica_plano(reais: dict[str, list[dict]]) -> tuple[dict[str, list[dict]], list[tuple]]:
    """Estado que o PLANO produz a partir do real + lista de mudancas (tenant, task, campos)."""
    novo = {t: [dict(x) for x in lst] for t, lst in reais.items()}
    mudancas = []
    for tenant, tasks in PLANO.items():
        if tenant not in novo:
            continue
        por_nome = {t["name"]: t for t in novo[tenant]}
        for nome, alvo in tasks.items():
            atual = por_nome.get(nome)
            if atual is None:
                if not alvo.get("criar"):
                    mudancas.append((tenant, nome, {"_erro": "task nao existe e o plano nao manda criar"}))
                    continue
                atual = {"name": nome, "frequency": "", "command": "", "timeout": 0,
                         "enabled": True, "uuid": None}
                novo[tenant].append(atual)
            campos = {}
            if "frequency" in alvo and atual["frequency"] != alvo["frequency"]:
                campos["frequency"] = alvo["frequency"]
            if "command" in alvo:
                c = alvo["command"](atual["command"]) if callable(alvo["command"]) else alvo["command"]
                if c != atual["command"]:
                    campos["command"] = c
            if "timeout" in alvo and int(atual.get("timeout") or 0) != alvo["timeout"]:
                campos["timeout"] = alvo["timeout"]
            if campos:
                atual.update(campos)
                mudancas.append((tenant, nome, dict(campos, _uuid=atual.get("uuid"))))
    return novo, mudancas


# --- Auditoria ----------------------------------------------------------------
def auditar(estado: dict[str, list[dict]]) -> int:
    problemas = 0

    print("\n== 1. Janela 19h-07h BRT (22:00-10:00 UTC), sem atravessar 00:00 UTC")
    for tenant, lst in estado.items():
        for t in sorted(lst, key=lambda x: x["name"]):
            if not t.get("enabled", True) or t["name"] in INFRA:
                continue
            fora = []
            for ini, fim in _intervalos(t):
                if not na_janela(ini, fim):
                    fora.append(f"{_hm(ini)}-{_hm(fim)}")
                elif fim > REINICIO_COOLIFY_MIN + 1440 > ini:
                    fora.append(f"{_hm(ini)}-{_hm(fim)} atravessa 00:00")
            if fora:
                if t["name"] in EXCECOES:
                    print(f"   excecao  {tenant:10} {t['name']:20} {t['frequency']:18} — {EXCECOES[t['name']][:70]}...")
                else:
                    problemas += 1
                    print(f"   FORA     {tenant:10} {t['name']:20} {t['frequency']:18} {', '.join(fora[:4])}")

    print("\n== 2. Mesma trava no mesmo worker (a segunda PULA a vez, sem log)")
    for tenant, lst in estado.items():
        por_trava: dict[str, list[dict]] = {}
        for t in lst:
            if t.get("enabled", True) and t["name"] not in INFRA and trava(t["command"]):
                por_trava.setdefault(trava(t["command"]), []).append(t)
        for tv, grupo in por_trava.items():
            for i, a in enumerate(grupo):
                for b in grupo[i + 1:]:
                    for ia in _intervalos(a):
                        hit = next((ib for ib in _intervalos(b) if _cruza(ia, ib)), None)
                        if hit:
                            problemas += 1
                            print(f"   CHOQUE   {tenant:10} {tv}: {a['name']} {_hm(ia[0])} x {b['name']} {_hm(hit[0])}")
                            break

    print(f"\n== 3. Portal do TransfereGov: ate {TG_FAIXAS} lote(s) ao mesmo tempo, entre TODOS os clientes")
    lotes = [(tenant, iv) for tenant, lst in estado.items() for t in lst
             if t["name"] == "transferegov-lote" and t.get("enabled", True) for iv in _intervalos(t)]
    lotes.sort(key=lambda x: (x[1][0] - JANELA_INICIO_MIN) % 1440)
    for ta, ia in lotes:
        juntos = sorted({tb for tb, ib in lotes if tb != ta and _cruza(ia, ib)})
        if len(juntos) + 1 > TG_FAIXAS:
            problemas += 1
            print(f"   CHOQUE   {ta} {_hm(ia[0])} divide o portal com {', '.join(juntos)} (limite {TG_FAIXAS})")
    print("   grade: " + " · ".join(f"{_hm(iv[0])} {t}" for t, iv in lotes))
    grade = [22 * 60, 22 * 60 + 30, 23 * 60] + [h * 60 + m for h in range(10) for m in (5, 35)]
    livres = []
    for g in grade:
        ocupadas = sum(1 for _, iv in lotes if _cruza((g, g + 29), iv))
        livres += [_hm(g)] * max(0, TG_FAIXAS - ocupadas)
    print(f"   slots LIVRES para cliente novo: {', '.join(livres) or 'NENHUM — suba TG_FAIXAS (ver INFRA.md §5)'}")

    return problemas


def auditar_limites(token: str) -> int:
    """Worker com teto de memoria/CPU no Coolify. Decisao do dono (13/09/2026): SEM
    limite. O teto de 2 GB / 1,2 CPU era da era de 2 vCPU e estrangula o paralelismo
    da coleta noturna sem erro nenhum na tela (so rodada que nao fecha, ou OOM)."""
    print("\n== 5. Workers sem teto de memoria/CPU (regra de 13/09/2026)")
    problemas = 0
    for tenant, (_api, wrk) in tenants().items():
        a = _req("GET", f"{COOLIFY}/applications/{wrk}", token) or {}
        tetos = {k: a.get(k) for k in ("limits_memory", "limits_cpus")
                 if str(a.get(k) or "0").strip() not in ("0", "")}
        if tetos:
            problemas += 1
            print(f"   TETO     {tenant:10} {tetos} — zerar e dar restart no worker")
    if not problemas:
        print("   todos sem teto")
    return problemas


# --- Capacidade -----------------------------------------------------------------
def carga(token: str, estado: dict[str, list[dict]]) -> None:
    print("\n== 4. Capacidade da noite: cabe todo municipio todo dia?")
    for tenant, (api, _wrk) in tenants().items():
        try:
            envs = _req("GET", f"{COOLIFY}/applications/{api}/envs", token) or []
            ctrl = next((e.get("real_value") or e.get("value") for e in envs
                         if e.get("key") == "CONTROL_TOKEN_BOOTSTRAP"), None)
            app = _req("GET", f"{COOLIFY}/applications/{api}", token)
            base = next(u for u in (app.get("fqdn") or "").split(",") if u.startswith("https")).rstrip("/")
            cob = _req("GET", f"{base}/api/control/cobertura", "", cab={"X-Control-Token": ctrl})
        except Exception as e:  # noqa: BLE001 — relatorio, nunca derruba
            print(f"   {tenant:10} sem leitura da cobertura: {str(e)[:80]}")
            continue
        ativos = [m for m in cob["municipios"] if m["ativo"]]
        props = sum((m["fontes"].get("TransfereGov (voluntárias)") or {}).get("n", 0) for m in ativos)
        lst = {t["name"]: t for t in estado.get(tenant, [])}
        n_lote = len(disparos(lst["transferegov-lote"]["frequency"])) if "transferegov-lote" in lst else 0
        precisa = props * TG_S_POR_PROPOSTA + len(ativos) * TG_S_POR_MUNICIPIO
        tem = n_lote * TG_ORCAMENTO_S
        marca = "ok " if tem >= precisa * 1.15 else "FALTA"
        print(f"   {tenant:10} TransfereGov {marca} {len(ativos):3} mun · {props:5} propostas · "
              f"precisa ~{precisa / 60:4.0f} min · {n_lote} rodadas = {tem / 60:4.0f} min")
        mg = [m for m in ativos if m["uf"] == "MG"]
        if mg:
            cred = [m for m in mg if "sigcon" in m["coletas"]
                    and "pausado" not in (m["coletas"]["sigcon"].get("erro") or "")]
            n_sig = sum(len(disparos(lst[n]["frequency"])) for n in ("sigcon", "sigcon-rodizio") if n in lst)
            p_sig = len(cred) * SIGCON_S_POR_MUNICIPIO
            t_sig = n_sig * min(SIGCON_ORCAMENTO_S, 2700)
            print(f"   {'':10} SIGCON       {'ok ' if t_sig >= p_sig else 'FALTA'} {len(cred):3} com senha · "
                  f"precisa ~{p_sig / 60:4.0f} min · {n_sig} rodadas = {t_sig / 60:4.0f} min")
            cmd = lst.get("cagec", {}).get("command", "")
            m_l = re.search(r"CAGEC_LOTE_MUNICIPIOS=(\d+)", cmd)
            lote = int(m_l.group(1)) if m_l else 11
            n_cg = len(disparos(lst["cagec"]["frequency"])) if "cagec" in lst else 0
            print(f"   {'':10} CAGEC        {'ok ' if n_cg * lote >= len(mg) else 'FALTA'} {len(mg):3} de MG · "
                  f"{n_cg} rodadas x lote {lote} = {n_cg * lote}")


# --- Aplicar ----------------------------------------------------------------------
def aplicar(token: str, mudancas: list[tuple]) -> None:
    ts = tenants()
    for tenant, nome, campos in mudancas:
        if "_erro" in campos:
            print(f"   PULADO {tenant} {nome}: {campos['_erro']}")
            continue
        wrk = ts[tenant][1]
        uuid = campos.pop("_uuid", None)
        try:
            if uuid:
                _req("PATCH", f"{COOLIFY}/applications/{wrk}/scheduled-tasks/{uuid}", token, campos)
                print(f"   ok     {tenant:10} {nome:20} {', '.join(campos)}")
            else:
                corpo = {"name": nome, "frequency": campos["frequency"], "command": campos["command"],
                         "timeout": campos.get("timeout", 3120)}
                _req("POST", f"{COOLIFY}/applications/{wrk}/scheduled-tasks", token, corpo)
                print(f"   criada {tenant:10} {nome:20} {campos['frequency']}")
        except urllib.error.HTTPError as e:
            print(f"   ERRO   {tenant:10} {nome:20} HTTP {e.code}: {e.read().decode()[:200]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plano", action="store_true", help="audita o estado que o PLANO produziria")
    ap.add_argument("--carga", action="store_true", help="inclui a conta de capacidade por cliente")
    ap.add_argument("--aplicar", action="store_true", help="grava o PLANO no Coolify")
    a = ap.parse_args()

    token = _token()
    reais = {t: tasks_reais(token, wrk) for t, (_api, wrk) in tenants().items()}
    novo, mudancas = aplica_plano(reais)

    if a.plano or a.aplicar:
        print(f"== Mudancas do plano: {len(mudancas)}")
        for tenant, nome, campos in mudancas:
            resumo = {k: (v if k != "command" else "(comando novo)") for k, v in campos.items() if k != "_uuid"}
            print(f"   {tenant:10} {nome:20} {resumo}")
    if a.aplicar:
        print("\n== Gravando no Coolify")
        aplicar(token, mudancas)
        reais = {t: tasks_reais(token, wrk) for t, (_api, wrk) in tenants().items()}
        _, resto = aplica_plano(reais)
        print(f"\n== Conferencia: {len(resto)} diferenca(s) entre o Coolify e o plano")
        for tenant, nome, campos in resto:
            print(f"   {tenant:10} {nome:20} {list(k for k in campos if k != '_uuid')}")
        estado = reais
    else:
        estado = novo if a.plano else reais

    n = auditar(estado) + auditar_limites(token)
    print(f"\n== {'OK' if not n else f'{n} PROBLEMA(S)'}")
    if a.carga:
        carga(token, estado)
    return 1 if n else 0


if __name__ == "__main__":
    sys.exit(main())
