"""Compara as envs sanitizadas (fingerprints) entre as instâncias do projeto `pactha`.

Entrada: coolify-auditoria-sanitizada.json (gerado por coletar_coolify.mjs; sem valores de segredo).
Saída:  dados/coolify-comparacao-envs.json e dados/coolify-comparacao-envs.md

Nunca lê nem grava valores de segredo — só fingerprints sha256 truncados, comprimentos e máscaras.
Uso: python comparar_envs_coolify.py [default1 default2 ...]  (defaults do código para testar por fingerprint)
"""
import json, re, sys, hashlib
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
d = json.load(open(HERE / "coolify-auditoria-sanitizada.json", encoding="utf-8"))

SENSIVEL = re.compile(r"(SECRET|TOKEN|PASSWORD|PASSWD|PASS$|API_KEY|PRIVATE_KEY|CREDENTIAL|COFRE|DATABASE_URL|DB_URL|AUTH_SECRET|SIGNING|ENCRYPTION|CERTIFICATE|SMTP_PASS|VAPID)", re.I)

apps = [a for a in d["applications"] if a["project_name"] == "pactha"]
dbs = {x["environment_name"]: x for x in d["databases"] if x["project_name"] == "pactha"}


def papel(nome):
    return nome.rsplit("-", 1)[-1]  # api | frontend | worker


# dedupe envs por key — prefere a entrada não-preview
inst = {}
for a in apps:
    env = {}
    for e in a["envs"]:
        k = e["key"]
        if k in env and env[k]["is_preview"] and not e["is_preview"]:
            env[k] = e
        elif k not in env:
            env[k] = e
    inst[a["name"]] = {"env": a["environment_name"], "papel": papel(a["name"]), "envs": env, "app": a}

# 1) DATABASE_URL -> host do db do mesmo environment
banco = []
for nome, i in inst.items():
    for k in ("DATABASE_URL", "DATABASE_URL_SYNC"):
        e = i["envs"].get(k)
        if not e:
            continue
        hosts = [u.get("host") for u in e.get("url", [])]
        db = dbs.get(i["env"])
        db_host = None
        if db and db.get("urls", {}).get("internal_db_url"):
            db_host = db["urls"]["internal_db_url"][0]["host"]
        banco.append({
            "instancia": nome, "environment": i["env"], "variavel": k, "hosts": hosts,
            "db_do_environment": db["name"] if db else None, "host_esperado": db_host,
            "ok": bool(hosts) and all(h == db_host for h in hosts),
            "senha_fp": [u.get("password") for u in e.get("url", [])],
        })

# 2) fingerprints iguais entre environments diferentes
por_chave = defaultdict(lambda: defaultdict(list))
for nome, i in inst.items():
    for k, e in i["envs"].items():
        if e["fingerprint"] is None:
            continue
        por_chave[k][e["fingerprint"]].append(nome)

compartilhados = []
for k, fps in sorted(por_chave.items()):
    for fp, insts in fps.items():
        envs_distintos = sorted({inst[n]["env"] for n in insts})
        if len(envs_distintos) > 1:
            compartilhados.append({
                "variavel": k, "fingerprint": fp, "instancias": sorted(insts),
                "environments": envs_distintos, "sensivel": bool(SENSIVEL.search(k)),
                "length": inst[insts[0]]["envs"][k]["length"],
                "masked": inst[insts[0]]["envs"][k]["masked"],
            })

# 3) consistência intra-tenant (api x worker x frontend)
intra = []
for env in sorted({i["env"] for i in inst.values()}):
    membros = {i["papel"]: i for n, i in inst.items() if i["env"] == env}
    for k in ("COFRE_KEY", "JWT_SECRET", "DATABASE_URL", "CONTROL_TOKEN_BOOTSTRAP", "ANTHROPIC_API_KEY", "ADMIN_PASSWORD"):
        fps = {p: m["envs"][k]["fingerprint"] for p, m in membros.items() if k in m["envs"]}
        intra.append({"environment": env, "variavel": k, "fingerprint_por_papel": fps,
                      "igual_entre_papeis": len(set(fps.values())) <= 1})

# 4) valores fracos conhecidos (compara fingerprint com sha256 de candidatos)
candidatos = ["", "changeme", "change-me", "secret", "postgres", "password", "admin", "123456", "pactha",
              "dev-secret", "dev-secret-change-me", "dev-secret-key", "supersecret", "your-secret-key",
              "CHANGE_ME", "changeme123", "pactha123", "admin123", "senha123", "true", "false"]
extra = sys.argv[1:]
cand_fp = {hashlib.sha256(c.encode()).hexdigest()[:12]: c for c in candidatos + extra}
fracos = []
for nome, i in inst.items():
    for k, e in i["envs"].items():
        if not SENSIVEL.search(k):
            continue
        if e["fingerprint"] in cand_fp:
            fracos.append({"instancia": nome, "variavel": k, "valor_candidato": cand_fp[e["fingerprint"]], "length": e["length"], "motivo": "igual a default/placeholder"})
        elif e["length"] < 16 and k not in ("DATABASE_URL", "DATABASE_URL_SYNC"):
            fracos.append({"instancia": nome, "variavel": k, "valor_candidato": None, "length": e["length"], "motivo": "curto (<16 chars)"})

# 5) matriz de fingerprints por instância
chaves = sorted({k for i in inst.values() for k in i["envs"]})
matriz = {k: {n: (i["envs"][k]["fingerprint"] if k in i["envs"] else None) for n, i in inst.items()} for k in chaves}

# 6) NEXT_PUBLIC_* / origens / proxy
INTERESSE = ("API_PROXY_TARGET", "FRONTEND_URL", "CORS_ORIGIN_REGEX", "COOKIE_DOMAIN", "SESSION_DOMAIN", "CONTROL_PLANE_ALLOWED_IPS", "ENV", "AUTHZ_MODO", "AUTHZ_REGISTRO", "INSTANCE_SLUG")
publicas = {}
for n, i in inst.items():
    publicas[n] = {}
    for k, e in i["envs"].items():
        if k.startswith("NEXT_PUBLIC_") or k in INTERESSE:
            publicas[n][k] = e.get("url") or e.get("safe_value") or e.get("masked")

# 7) scheduled tasks
tasks = {n: [{"name": t["name"], "frequency": t["frequency"], "enabled": t["enabled"], "timeout": t["timeout"], "command": t["command"]} for t in i["app"]["scheduled_tasks"]] for n, i in inst.items()}

out = {
    "schema": "pactha-coolify-comparacao-envs-v1",
    "fonte": {"collected_at_utc": d.get("collected_at_utc"), "coolify_version": d.get("version")},
    "instancias": {n: {"environment": i["env"], "papel": i["papel"], "n_envs": len(i["envs"]), "fqdn": i["app"]["fqdn"],
                       "image": f'{i["app"]["docker_registry_image_name"]}:{i["app"]["docker_registry_image_tag"]}',
                       "build_pack": i["app"]["build_pack"], "git_branch": i["app"]["git_branch"], "redirect": i["app"]["redirect"],
                       "ports_exposes": i["app"]["ports_exposes"], "ports_mappings": i["app"]["ports_mappings"]}
                   for n, i in inst.items()},
    "bancos": banco,
    "compartilhados_entre_environments": compartilhados,
    "intra_tenant": intra,
    "valores_fracos": fracos,
    "matriz_fingerprints": matriz,
    "publicas_e_origens": publicas,
    "scheduled_tasks": tasks,
    "databases": {k: {"name": v["name"], "is_public": v["is_public"], "public_port": v["public_port"], "image": v["image"],
                      "user": v["postgres_user"], "db": v["postgres_db"], "backup": v["backup_enabled"],
                      "host": v["urls"]["internal_db_url"][0]["host"]} for k, v in dbs.items()},
    "environments_do_projeto": [e["name"] for p in d["project_details"] if p["name"] == "pactha" for e in p["environments"]],
}
(HERE / "dados").mkdir(exist_ok=True)
json.dump(out, open(HERE / "dados" / "coolify-comparacao-envs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

L = ["# Comparação de envs entre instâncias (fingerprints)\n"]
L.append("## Banco por instância\n\n| instância | env | variável | host(s) na URL | db do environment | host esperado | OK |\n|---|---|---|---|---|---|---|")
for b in banco:
    L.append(f"| {b['instancia']} | {b['environment']} | {b['variavel']} | {', '.join(map(str, b['hosts']))} | {b['db_do_environment']} | {b['host_esperado']} | {'OK' if b['ok'] else 'FALHA'} |")
L.append("\n## Valores idênticos em mais de um environment\n\n| variável | sensível | fingerprint | len | instâncias |\n|---|---|---|---|---|")
for c in compartilhados:
    L.append(f"| {c['variavel']} | {'SIM' if c['sensivel'] else 'não'} | {c['fingerprint']} | {c['length']} | {', '.join(c['instancias'])} |")
L.append("\n## Intra-tenant (api × worker × frontend)\n\n| env | variável | fp por papel | igual |\n|---|---|---|---|")
for x in intra:
    L.append(f"| {x['environment']} | {x['variavel']} | {x['fingerprint_por_papel']} | {'sim' if x['igual_entre_papeis'] else 'NÃO'} |")
L.append("\n## Valores fracos / candidatos a default\n")
for f in fracos:
    L.append(f"- {f}")
L.append("\n## NEXT_PUBLIC_* / origens / proxy / flags\n")
for n, p in publicas.items():
    L.append(f"### {n}")
    for k, v in p.items():
        L.append(f"- `{k}`: {v}")
L.append("\n## Scheduled tasks\n")
for n, ts in tasks.items():
    if not ts:
        continue
    L.append(f"### {n} ({len(ts)} tasks)")
    for t in ts:
        L.append(f"- **{t['name']}** `{t['frequency']}` enabled={t['enabled']} timeout={t['timeout']}\n  `{t['command']}`")
L.append("\n## Matriz de fingerprints por instância\n")
cols = list(inst.keys())
L.append("| chave | " + " | ".join(cols) + " |\n|---|" + "---|" * len(cols))
for k in chaves:
    L.append(f"| {k} | " + " | ".join((matriz[k][c] or "—") for c in cols) + " |")
open(HERE / "dados" / "coolify-comparacao-envs.md", "w", encoding="utf-8").write("\n".join(L) + "\n")

print("instancias:", len(inst), "| bancos:", len(banco), "| compartilhados:", len(compartilhados), "| fracos:", len(fracos))
for b in banco:
    print(" DB", b["instancia"], b["variavel"], "OK" if b["ok"] else "!!", b["hosts"], "->", b["host_esperado"])
for c in compartilhados:
    print(" SHARED", c["variavel"], "sens=" + str(c["sensivel"]), c["fingerprint"], c["instancias"])
for x in intra:
    if not x["igual_entre_papeis"]:
        print(" INTRA-DIFF", x)
for f in fracos:
    print(" WEAK", f)
