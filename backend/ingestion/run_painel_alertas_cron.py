"""Cron do Painel Executivo do prefeito.

Avalia regras de alerta por município e dispara PUSH WEB (VAPID) para as
inscrições do prefeito. Roda no Worker (Coolify Scheduled Task), ex.: a cada
30 min. Idempotente via painel_alertas_enviados (municipio, regra, ref) — cada
alerta é enviado uma única vez. Respeita painel_preferencias por usuário.

Envs necessárias: DATABASE_URL_SYNC (ou DATABASE_URL), VAPID_PRIVATE_KEY,
VAPID_PUBLIC_KEY, VAPID_SUBJECT. Sem as chaves VAPID, o cron sai sem enviar.
"""
import os
import json
import sys

MAX_ENVIOS = 30  # teto por execução (evita flood)


def _log(msg):
    print(f"[PAINEL_ALERTAS] {msg}", flush=True)


def _conn():
    import psycopg2
    url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not url:
        raise RuntimeError("DATABASE_URL_SYNC não configurada")
    return psycopg2.connect(url)


def _candidatos(cur, mid):
    """Lista de (regra, ref, titulo, corpo) para o município."""
    out = []

    # Convênios vencendo em até 60 dias — 1 push por convênio (costuma ser poucos)
    try:
        cur.execute(
            "SELECT nr_sigcon, objeto FROM convenios_estadual WHERE municipio_id = %s "
            "AND dt_vigencia_atual BETWEEN CURRENT_DATE AND CURRENT_DATE + 60",
            (mid,),
        )
        for nr, obj in cur.fetchall():
            out.append(("vigencia_60d", f"vig:{nr}", "Convênio vencendo",
                        ((obj or "Um convênio")[:90]) + " vence em até 60 dias."))
    except Exception:
        cur.connection.rollback()

    # Prestação de contas vencida (+90d) — 1 push AGREGADO (evita flood)
    try:
        cur.execute(
            "SELECT COUNT(*) FROM convenios_estadual WHERE municipio_id = %s "
            "AND dt_vigencia_atual < CURRENT_DATE - 90",
            (mid,),
        )
        n = cur.fetchone()[0] or 0
        if n > 0:
            out.append(("prazo_prestacao", f"pc-total:{n}", "Prestação de contas",
                        f"{n} convênio(s) com prestação de contas vencida — regularize para liberar novos recursos."))
    except Exception:
        cur.connection.rollback()

    # CAUC com pendência — 1 push AGREGADO por quantidade de pendências
    try:
        cur.execute(
            "SELECT COALESCE(pendencias, 0), regular FROM cauc_situacao WHERE municipio_id = %s",
            (mid,),
        )
        row = cur.fetchone()
        if row and not row[1] and (row[0] or 0) > 0:
            out.append(("cauc_vencendo", f"cauc:{row[0]}", "Documentação (CAUC)",
                        f"{row[0]} pendência(s) no CAUC podem travar novos repasses."))
    except Exception:
        cur.connection.rollback()

    # Mudanças de status recentes (48h) — 1 push por mudança
    try:
        cur.execute(
            "SELECT id, objeto, status_novo FROM status_changes WHERE municipio_id = %s "
            "AND changed_at >= NOW() - INTERVAL '2 days' "
            "AND length(trim(coalesce(objeto, ''))) > 3 LIMIT 10",
            (mid,),
        )
        for sid, obj, novo in cur.fetchall():
            out.append(("mudanca_status", f"sc:{sid}", "Mudança de status",
                        ((obj or "Um convênio")[:70]) + f" → {novo or 'novo status'}."))
    except Exception:
        cur.connection.rollback()

    # Novas emendas estaduais (48h) — 1 push por emenda
    try:
        cur.execute(
            "SELECT nr_indicacao, nome_responsavel FROM emendas_estaduais WHERE municipio_id = %s "
            "AND created_at >= NOW() - INTERVAL '2 days' LIMIT 10",
            (mid,),
        )
        for nr, resp in cur.fetchall():
            out.append(("nova_emenda", f"em:{nr}", "Nova emenda registrada",
                        f"Nova emenda ({resp or 'parlamentar'}) destinada ao município."))
    except Exception:
        cur.connection.rollback()

    return out


def _prefs(cur):
    """Mapa user_id -> dict de preferências (default tudo ligado)."""
    cur.execute("SELECT user_id, cauc_vencendo, nova_emenda, prazo_prestacao, mudanca_status, vigencia_60d FROM painel_preferencias")
    m = {}
    for r in cur.fetchall():
        m[r[0]] = {"cauc_vencendo": r[1], "nova_emenda": r[2], "prazo_prestacao": r[3],
                   "mudanca_status": r[4], "vigencia_60d": r[5]}
    return m


def main():
    priv = os.getenv("VAPID_PRIVATE_KEY")
    subject = os.getenv("VAPID_SUBJECT") or "mailto:contato@pactha.com.br"
    if not priv:
        _log("VAPID_PRIVATE_KEY ausente — nada a enviar.")
        return
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        _log("pywebpush não instalado — pulando.")
        return

    conn = _conn()
    cur = conn.cursor()
    prefs = _prefs(cur)

    # Municípios que têm inscrição ativa
    cur.execute("SELECT DISTINCT municipio_id FROM painel_push_subscriptions")
    muns = [r[0] for r in cur.fetchall()]
    enviados = 0

    for mid in muns:
        cur.execute("SELECT id, endpoint, p256dh, auth, user_id FROM painel_push_subscriptions WHERE municipio_id = %s", (mid,))
        subs = cur.fetchall()
        if not subs:
            continue
        for (regra, ref, titulo, corpo) in _candidatos(cur, mid):
            if enviados >= MAX_ENVIOS:
                break
            cur.execute(
                "SELECT 1 FROM painel_alertas_enviados WHERE municipio_id = %s AND regra = %s AND ref = %s",
                (mid, regra, ref),
            )
            if cur.fetchone():
                continue  # já enviado
            enviou_algum = False
            for (sid, endpoint, p256dh, auth, uid) in subs:
                pref = prefs.get(uid, {})
                if pref.get(regra, True) is False:
                    continue
                payload = json.dumps({"title": titulo, "body": corpo, "url": "/app/alertas", "tag": ref})
                try:
                    webpush(
                        subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}},
                        data=payload,
                        vapid_private_key=priv,
                        vapid_claims={"sub": subject},
                    )
                    enviou_algum = True
                    cur.execute("UPDATE painel_push_subscriptions SET last_ok_at = NOW() WHERE id = %s", (sid,))
                except WebPushException as e:
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    if status in (404, 410):
                        cur.execute("DELETE FROM painel_push_subscriptions WHERE id = %s", (sid,))
                        _log(f"inscrição {sid} removida (HTTP {status})")
                    else:
                        _log(f"falha push sub {sid}: {str(e)[:80]}")
                except Exception as e:
                    _log(f"erro push sub {sid}: {str(e)[:80]}")
            if enviou_algum:
                cur.execute(
                    "INSERT INTO painel_alertas_enviados (municipio_id, regra, ref) VALUES (%s, %s, %s) "
                    "ON CONFLICT (municipio_id, regra, ref) DO NOTHING",
                    (mid, regra, ref),
                )
                enviados += 1
        conn.commit()

    cur.close()
    conn.close()
    _log(f"OK — {enviados} alerta(s) despachado(s).")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _log(f"FALHOU: {e}")
        sys.exit(1)
