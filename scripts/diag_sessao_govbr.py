"""
Diagnostico SOMENTE-LEITURA da sessao gov.br em todos os tenants — a linha do tempo
que o resumo nao mostra: quando a sessao foi gravada, por quem (captura da
extensao, promocao de candidata, keepalive), e o que o `audit_log` registrou.

⭐ POR QUE EXISTE. Em 23/09/2026 a sessao caiu de novo nos seis tenants, um dia
depois das guardas do PR #529 entrarem. A pergunta que separa as causas ("houve
`session.update` antes da morte, ou so `session.candidata`?") so tem resposta no
`audit_log` — e o banco so existe na rede Docker. Este script roda no GitHub
Actions (o mesmo canal do `resumo_coleta.py`, com o mesmo secret) e imprime a
resposta no log do run. Nao envia nada, nao grava nada.

⚠️ SO STDLIB, como o resumo. ⚠️ Nunca imprime cookie, token ou senha: os campos
sao os do `/api/control/audit` (acao, alvo, tamanho do jar, via) e do
`/api/control/session/status` (idade, `exp` do JWT, `observacao`).

Envs:
    PACTHA_RESUMO_TENANTS   JSON: [{"slug","api_url","control_token"}, ...]
    DIAG_AUDIT_LIMIT        opcional, default 80 (teto da rota: 200)
"""
import json
import os
import urllib.error
import urllib.request

TIMEOUT = 25


def _get(tenant: dict, caminho: str):
    base = (tenant.get("api_url") or "").rstrip("/")
    req = urllib.request.Request(base + caminho, headers={
        "X-Control-Token": tenant.get("control_token") or "",
        "X-Tenant-Slug": tenant.get("slug") or "",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_erro": f"HTTP {e.code}"}
    except Exception as e:  # rede: vira dado, nao excecao
        return {"_erro": str(e)[:80]}


CAMPOS_SESSAO = ("has_session", "updated_at", "age_hours", "exp_minutes", "expired",
                 "expira_em", "decode_error", "message", "_erro")


def linhas_do_tenant(tenant: dict, limite: int) -> list:
    slug = tenant.get("slug") or "?"
    out = [f"\n===== {slug}"]
    st = _get(tenant, "/api/control/session/status")
    out.append("sessao em uso: " + json.dumps({k: st.get(k) for k in CAMPOS_SESSAO if k in st},
                                              ensure_ascii=False))
    out.append("observacao:    " + " ".join(str(st.get("observacao") or "").split())[:500])
    # nome/dominio/vencimento de cada cookie (sem valor): e daqui que sai o teto medido
    for c in st.get("cookies_meta") or []:
        out.append(f"  cookie {str(c.get('name'))[:28]:<28} {str(c.get('domain'))[:40]:<40} "
                   f"httpOnly={'s' if c.get('httpOnly') else 'n'} expira_em={c.get('expira_em') or '(sessao)'}")

    ev = _get(tenant, f"/api/control/audit?action=session.&limit={limite}")
    if isinstance(ev, dict):
        out.append(f"audit: {ev.get('_erro') or ev.get('error') or ev}")
    else:
        out.append(f"audit (session.*, {len(ev)} evento(s), do mais novo ao mais velho):")
        for a in ev:
            d = a.get("details") or {}
            out.append(f"  {a.get('created_at')}  {a.get('action'):<22} alvo={a.get('target_id')} "
                       f"via={d.get('auth_via')} jar={d.get('cookie_size')} "
                       f"key={d.get('automation_key')} mun={d.get('municipio_id')}")

    ing = _get(tenant, "/api/control/ingestion")
    if isinstance(ing, dict) and not ing.get("_erro"):
        ult = ing.get("ultimo_por_fonte") or {}
        for src in sorted(k for k in ult if k.startswith("govbr")):
            out.append(f"ultimo {src:<16} {ult[src].get('status'):<8} {ult[src].get('finished_at')}")
        hist = [r for r in (ing.get("log") or []) if str(r.get("source", "")).startswith("govbr")]
        if hist:
            out.append(f"historico govbr_* nas ultimas {len(ing.get('log') or [])} linhas do ingestion_log:")
            for r in hist:
                out.append(f"  {r.get('finished_at')}  {r.get('source'):<16} {r.get('status')}")
    else:
        out.append(f"ingestion: {ing.get('_erro') if isinstance(ing, dict) else ing}")
    return out


def main() -> int:
    bruto = (os.getenv("PACTHA_RESUMO_TENANTS") or "").strip()
    if not bruto:
        raise SystemExit("PACTHA_RESUMO_TENANTS ausente")
    limite = max(1, min(int(os.getenv("DIAG_AUDIT_LIMIT", "80") or "80"), 200))
    print("[diag] sessao gov.br — linha do tempo por tenant (horarios em UTC, como a API devolve)")
    for t in json.loads(bruto):
        print("\n".join(linhas_do_tenant(t, limite)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
