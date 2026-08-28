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

# `python ingestion/x.py` poe a PASTA DO SCRIPT no sys.path, nao o cwd —
# sem isto o `import services` abaixo falha em silencio.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

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

    # CAGEC irregular — 1 push AGREGADO, nomeando o que trava.
    # Faltava por completo: o município podia estar impedido de assinar convênio
    # estadual e o prefeito não recebia nada.
    # UMA LINHA POR ENTIDADE: Prefeitura, Fundo Municipal de Saúde e FMAS têm
    # cadastros separados no CAGEC. `fetchone()` aqui pegaria uma qualquer e o
    # prefeito receberia (ou deixaria de receber) o alerta errado.
    # ⚠️ O NOME DO CADASTRO SAI DA `fonte` DA LINHA (CAGEC-MG ou CHE-RS), e a
    # consequencia tambem: o push do prefeito gaucho dizia "Irregular no CAGEC".
    # O `ref` NAO muda com o rotulo — e a chave de idempotencia, e troca-la
    # re-dispararia todo alerta ja enviado.
    try:
        from services.cadastro_estadual import sigla_da_fonte, trava_da_uf, uf_da_fonte
        cur.execute(
            "SELECT COALESCE(pendencias, 0), regular, situacao, itens, nome, tipo, "
            "COALESCE(principal, false), cnpj, fonte "
            "FROM cagec_situacao WHERE municipio_id = %s "
            "ORDER BY principal DESC, tipo NULLS LAST", (mid,))
        for pend, regular, situacao, itens, nome, tipo, principal, cnpj, fonte in cur.fetchall():
            if regular is not False:
                continue
            sigla = sigla_da_fonte(fonte)
            nomes = [i.get("label") for i in (itens or [])
                     if isinstance(i, dict) and i.get("tipo") == "pendente"]
            detalhe = "; ".join(n for n in nomes[:2] if n) or f"{pend} pendência(s)"
            quem = "Município" if principal else (tipo or nome or "Entidade")
            trava = (trava_da_uf(uf_da_fonte(fonte)).capitalize() + "."
                     if principal else
                     f"Trava os convênios estaduais desta entidade — a prefeitura "
                     f"estar regular não resolve.")
            out.append(("cauc_vencendo", f"cagec:{cnpj}:{situacao}:{pend}",
                        f"Regularidade estadual ({sigla})",
                        f"{quem} {situacao or 'irregular'} no {sigla} — {detalhe[:100]}. {trava}"))
    except Exception as e:
        _log(f"ERRO ao montar alerta do cadastro estadual: {type(e).__name__}: {e}")
        cur.connection.rollback()

    # DOCUMENTAÇÃO VENCENDO — avisa ANTES de travar, que é o ponto.
    # A regra vem de services.bi_abas para a notificação e a tela nunca
    # discordarem sobre o mesmo prazo — e porque a parte difícil dela (separar
    # PRAZO de cadência de atualização do extrato) não pode existir em dois
    # lugares. Um push por obrigação e por FAIXA: o `ref` carrega a faixa, então
    # o gestor é cutucado em 30, de novo em 15 e de novo em 7 dias, e nunca duas
    # vezes na mesma faixa (a idempotência é por `ref`).
    try:
        from services.bi_abas import prazos_dos_itens
        from services.cadastro_estadual import sigla_da_fonte
        for tabela, esfera in (("cagec_situacao", "CAGEC"), ("cauc_situacao", "CAUC")):
            # fetchall: o CAGEC tem uma linha por ENTIDADE (prefeitura, fundo
            # de saude, FMAS). fetchone() perderia os prazos dos fundos.
            # `fonte` so existe no cadastro estadual — e o que da o nome certo
            # ao push ("CHE" no RS). O `ref` continua com `esfera` (a chave de
            # idempotencia nao acompanha o rotulo).
            fonte_col = "fonte" if esfera == "CAGEC" else "NULL"
            cur.execute(f"SELECT itens, data_pesquisa, {fonte_col} FROM {tabela} "
                        f"WHERE municipio_id = %s", (mid,))
            prazos = []
            for r in cur.fetchall():
                rotulo = sigla_da_fonte(r[2]) if esfera == "CAGEC" else esfera
                prazos += [{**p, "rotulo": rotulo}
                           for p in prazos_dos_itens(r[0], r[1], esfera, dias=30)]
            for p in prazos:
                faixa = next((f for f in (7, 15, 30) if p["dias_restantes"] <= f), None)
                if faixa is None:
                    continue
                quando = ("vence hoje" if p["dias_restantes"] == 0
                          else f"vence em {p['dias_restantes']} dia(s)")
                out.append((
                    "cauc_vencendo",                        # mesma preferência de regularidade
                    f"doc:{esfera}:{p['codigo']}:{faixa}",  # 1 push por faixa
                    f"Documento vencendo ({p['rotulo']})",
                    f"{(p['label'] or p['codigo'])[:90]} {quando}. "
                    f"Renove antes para não travar convênio."))
    except Exception as e:
        # Log alto: se a regra de prazo parar de carregar, o alerta some sem
        # ninguem notar — que e o pior modo de falha possivel aqui.
        _log(f"ERRO ao montar alertas de vencimento: {type(e).__name__}: {e}")
        cur.connection.rollback()

    # OBRAS DA SAUDE (SISMOB) — prazo de norma, obra parada e recurso a devolver.
    # As regras vem de services/sismob_regras.py, a MESMA que a tela usa, para a
    # notificacao e o painel nunca discordarem sobre a mesma obra.
    #
    # Duas decisoes de ruido, ambas deliberadas:
    #  - "sem_atualizacao" vai AGREGADO por municipio. Individual, uma carteira
    #    de 18 municipios viraria enxurrada e o gestor desligaria a preferencia
    #    inteira — perdendo junto os alertas caros de prazo e de recurso parado.
    #  - `push_permitido` corta pendencia cadastral antiga (>12 meses). Acordar
    #    o prefeito as 7h por causa de 2015 ensina que notificacao do PACTHA e
    #    ruido, e ai a de prazo vencido tambem passa a ser ignorada.
    try:
        from services.sismob_regras import classificar, push_permitido
        cur.execute("""
            SELECT proposta_id, estabelecimento, programa, co_situacao_obra,
                   dt_primeira_parcela, dt_conclusao_final, dt_inicio_funcionamento,
                   nu_cnes, co_cnes, possui_etapa_funcionamento, repasse_total,
                   ultima_atividade_em, dt_mudanca_situacao, vl_percentual_executado
            FROM sismob_obras
            WHERE municipio_id = %s AND ausente_desde IS NULL
        """, (mid,))
        cols = [d[0] for d in cur.description]
        paradas = []
        for linha in cur.fetchall():
            o = dict(zip(cols, linha))
            nome = (o.get("estabelecimento") or o.get("programa") or "Obra da saúde")[:70]
            for g in classificar(o)["regras"]:
                if not push_permitido(g, o):
                    continue
                if g["regra"] == "sem_atualizacao":
                    paradas.append((o, g))       # agregado depois
                    continue
                # `fase` entra no ref: no etapa90 o pre-aviso e o vencimento
                # sao a MESMA regra, e sem separar os dois o UNIQUE da tabela
                # fazia o pre-aviso silenciar o alerta de prazo vencido. As
                # outras regras nao tem fase e caem no "x", que preserva o ref
                # que ja usavam.
                out.append(("obra_prazo",
                            f"sismob:{g['regra']}:{g.get('fase', 'x')}:{o['proposta_id']}",
                            "Obra da saúde (SISMOB)",
                            f"{nome}: {g['titulo']}. {g['acao']}"))
        if paradas:
            pior = max(paradas, key=lambda x: x[1].get("dias") or 0)
            nome = (pior[0].get("estabelecimento") or "obra")[:50]
            # O `ref` carrega a CONTAGEM e a pior obra: reenvia quando o numero
            # muda ou quando outra obra passa a ser a mais parada, e fica quieto
            # quando nada mudou.
            out.append(("obra_prazo",
                        f"sismob:sematualizar:{len(paradas)}:{pior[0]['proposta_id']}",
                        "Obras da saúde paradas",
                        f"{len(paradas)} obra(s) sem atualização no SISMOB há mais de 60 dias. "
                        f"A pior é {nome} ({pior[1]['titulo'].lower()}). "
                        f"A norma exige atualização a cada 60 dias."))
    except Exception as e:
        # Log alto: se a regra parar de carregar, o alerta some sem ninguem ver.
        _log(f"ERRO ao montar alertas do SISMOB: {type(e).__name__}: {e}")
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
    cur.execute("SELECT user_id, cauc_vencendo, nova_emenda, prazo_prestacao, mudanca_status, "
                "       vigencia_60d, COALESCE(obra_prazo, true) FROM painel_preferencias")
    m = {}
    for r in cur.fetchall():
        m[r[0]] = {"cauc_vencendo": r[1], "nova_emenda": r[2], "prazo_prestacao": r[3],
                   "mudanca_status": r[4], "vigencia_60d": r[5], "obra_prazo": r[6]}
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
