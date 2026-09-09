"""
Resumo diario da coleta dos cinco tenants, numa mensagem so no Telegram.

⭐ POR QUE ISTO NAO RODA NO WORKER

O watchdog (`backend/ingestion/watchdog_coleta.py`) ja vigia a coleta e ja fala no
Telegram — mas de DENTRO do worker. Ele nao consegue relatar a propria morte: se o
container cair ou a Scheduled Task nao disparar, ele nao roda, nao alerta, e **o
silencio fica identico a saude**. Foi essa a forma dos 6 dias de regularidade
estadual parada sem ninguem notar (CONTINUAR.md §1.18).

Por isso este script roda no **GitHub Actions**, que e a unica coisa que o projeto
ja usa e que nao mora na mesma VPS. Ele inverte a pergunta: em vez de esperar o
alerta chegar, vai buscar. E quando NADA responde, isso vira a noticia mais alta
do relatorio — "nao falei com 5 de 5 APIs" e um alarme que ninguem daria hoje.

Divisao de trabalho entre os dois, que e de proposito:
  - o watchdog do worker GRITA NA HORA (a cada 30 min, so quando acha problema);
  - este aqui RELATA UMA VEZ POR DIA, inclusive quando esta tudo bem — porque
    relatorio que so chega em dia ruim nao prova que o vigia esta vivo.

⚠️ SO STDLIB. Nada de `requests`: o workflow nao instala dependencia nenhuma, e a
unica coisa pior que um vigia mudo e um vigia que quebra no `pip install`.

Envs:
    PACTHA_RESUMO_TENANTS   JSON: [{"slug","api_url","control_token"}, ...]
    RESUMO_TELEGRAM_TOKEN   token do bot (o mesmo pactha_watchdog_bot serve)
    RESUMO_TELEGRAM_CHAT_ID destino
    RESUMO_JANELA_HORAS     opcional, default 24
    RESUMO_DRY_RUN          "1" imprime e nao envia (usado no teste manual do workflow)

Uso:
    python scripts/resumo_coleta.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

TIMEOUT = 25
LIMITE_TELEGRAM = 4096

# Fuso de Brasilia sem depender de tzdata no runner (o Actions roda em UTC).
BRT = timezone(timedelta(hours=-3))

# ⚠️ ONDE OLHAR quando a fonte falha. Este mapa e o que transforma o relatorio de
# "algo quebrou" em "va aqui" — foi o pedido literal do dono: *"detalhar quais
# deram erro, qual municipio, por que, pra eu ir na fonte e ver o que ta
# acontecendo"*. Fonte ausente daqui simplesmente nao ganha a linha do "->".
ONDE_OLHAR = {
    "sigcon": "portal SIGCON-MG (login por municipio; senha revogada = 'Esqueci minha senha')",
    "sigcon_scraper": "portal SIGCON-MG (login por municipio)",
    "sigcon_emendas": "portal SIGCON-MG > Emendas",
    "cagec": "cagec.mg.gov.br/convenente-web (consulta publica por CNPJ)",
    "cauc": "CAUC/Tesouro (consulta por CNPJ)",
    "acordofes": "Acordo FES-MG",
    "simec_par": "SIMEC/PAR (anti-bot: curl_cffi)",
    "sismob": "sismobcidadao.saude.gov.br/api/public/obras",
    "fns": "ConsultaFNS (sessao gov.br pela extensao)",
    # `private=CAIU, execucao=CAIU, prestacao=CAIU` foi o erro real mais comum
    # medido em 08/09/2026: 27 de 27 falhas de um tenant eram esta.
    "govbr_sessao": "sessao gov.br expirou — recapturar pela extensao do Chrome",
    "govbr_renew": "renovacao da sessao gov.br (extensao do Chrome)",
    "obrasgov": "api-publica.obrasgov.gestao.gov.br (o outro host devolve 429)",
    "transferegov_opendata": "dados abertos do TransfereGov (siconv_*.zip)",
    "transferegov_voluntarias": "APIs novas do TransfereGov",
    "transferegov_pac": "APIs novas do TransfereGov",
    "siconfi": "SICONFI/Tesouro (contas entregues + CAPAG)",
    "tce_rs": "dados.tce.rs.gov.br (403 para IP de datacenter — precisa do oficio)",
    "tce_rs_portal": "portal.tce.rs.gov.br (mesmo bloqueio de borda do outro host)",
    "che_rs": "CHE/RS",
    "convenios_rs": "CAGE/RS",
    "consulta_popular_rs": "Consulta Popular/RS",
}

ICONE = {"ok": "✅", "atencao": "⚠️", "erro": "\U0001F534",
         "credencial": "\U0001F511", "volume": "\U0001F4C9", "fonte": "\U0001F7E0"}


def _tenants() -> list:
    bruto = (os.getenv("PACTHA_RESUMO_TENANTS") or "").strip()
    if not bruto:
        raise SystemExit("PACTHA_RESUMO_TENANTS ausente")
    dados = json.loads(bruto)
    if not isinstance(dados, list) or not dados:
        raise SystemExit("PACTHA_RESUMO_TENANTS deve ser uma lista nao vazia")
    return dados


def coletar(tenant: dict, janela: int) -> dict:
    """Busca o resumo de UM tenant. Falha de rede vira dado, nao excecao.

    ⚠️ Erro aqui e a informacao mais importante do relatorio, nao um contratempo:
    API que nao responde e o unico jeito de este script perceber que a VPS caiu.
    Por isso ele e capturado e devolvido como conteudo."""
    slug = tenant.get("slug") or "?"
    base = (tenant.get("api_url") or "").rstrip("/")
    url = f"{base}/api/control/resumo-coleta?horas={janela}"
    req = urllib.request.Request(url, headers={
        "X-Control-Token": tenant.get("control_token") or "",
        # Anti-misrouting: a API recusa (409) se este slug nao for o dela. Protege
        # contra um dia alguem trocar duas URLs de lugar no secret e o relatorio
        # passar meses atribuindo os numeros de um cliente a outro.
        "X-Tenant-Slug": slug,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return {"slug": slug, "ok": True, "dados": json.loads(r.read().decode("utf-8"))}
    except urllib.error.HTTPError as e:
        detalhe = f"HTTP {e.code}"
        if e.code in (401, 403):
            detalhe += " (control token invalido, revogado ou sem escopo control:data:read)"
        elif e.code == 404:
            detalhe += " (rota /api/control/resumo-coleta ausente — tenant com codigo antigo)"
        return {"slug": slug, "ok": False, "erro": detalhe}
    except Exception as e:
        return {"slug": slug, "ok": False, "erro": f"{type(e).__name__}: {str(e)[:120]}"}


def _linha_tenant(r: dict) -> str:
    if not r["ok"]:
        return f"{ICONE['erro']} {r['slug']:<14} API nao respondeu — {r['erro']}"

    d = r["dados"]
    rodadas = {x["status"]: x["n"] for x in d.get("rodadas", [])}
    total = sum(rodadas.values())
    # Os tres dialetos de status convivem no mesmo banco (auditoria de 29/08):
    # success/ok, parcial/partial, erro/error/failed. A API ja normaliza para
    # minusculas; o agrupamento por familia acontece aqui.
    boas = rodadas.get("success", 0) + rodadas.get("ok", 0)
    parciais = rodadas.get("parcial", 0) + rodadas.get("partial", 0)
    ruins = sum(v for k, v in rodadas.items()
                if k in ("erro", "error", "failed", "falha"))

    partes = [f"{total} rodada" + ("s" if total != 1 else "")]
    if boas:
        partes.append(f"{boas} ok")
    if parciais:
        partes.append(f"{parciais} parcia" + ("is" if parciais != 1 else "l"))
    if ruins:
        partes.append(f"{ruins} com erro")

    achados = len(d.get("achados", [])) + len(d.get("volume", []))
    if total == 0:
        # ⚠️ Zero rodadas nao e "dia calmo": e worker parado. Este e exatamente o
        # caso que o watchdog de dentro nao consegue reportar.
        return f"{ICONE['erro']} {r['slug']:<14} NENHUMA rodada na janela — worker parado?"
    icone = ICONE["ok"] if (ruins == 0 and achados == 0) else ICONE["atencao"]
    return f"{icone} {r['slug']:<14} " + " · ".join(partes)


def _limpar_mensagem_watchdog(bruta: str) -> str:
    """Tira do alerta do watchdog o que o resumo ja diz de outro jeito.

    A mensagem vem no formato de la, em tres linhas:

        {icone} *PACTHA {slug}* — {titulo}
        `{chave}`
        {detalhe}

    Os marcadores `*` e a crase sao heranca do Markdown legado do Telegram (o
    proprio watchdog os remove antes de enviar), e o slug e a chave o resumo ja
    imprime no cabecalho do item. Repetir os tres transformaria cada achado em
    tres linhas de ruido — num relatorio que precisa caber em 4.096 caracteres.

    Degrada com elegancia: se o formato mudar e nao houver as tres linhas, o que
    volta e a mensagem inteira limpa, que e pior que o ideal e melhor que vazio.
    """
    limpa = bruta.replace("*", "").replace("`", "")
    linhas = [ln.strip() for ln in limpa.splitlines() if ln.strip()]
    if len(linhas) >= 3 and "—" in linhas[0]:
        titulo = linhas[0].split("—", 1)[1].strip()
        detalhe = " ".join(linhas[2:])
        return f"{titulo}: {detalhe}" if titulo else detalhe
    return " ".join(limpa.split())


def _detalhes(r: dict) -> list:
    """As linhas do 'o que olhar' de um tenant: o porque e o onde."""
    if not r["ok"]:
        return []
    out, d, slug = [], r["dados"], r["slug"]

    for a in d.get("achados", []):
        icone = ICONE["credencial"] if a.get("tipo") == "credencial_recusada" else ICONE["fonte"]
        corpo = _limpar_mensagem_watchdog(a.get("mensagem") or "")
        vezes = a.get("repeticoes") or 1
        # 7x em 24h e "persistente", 1x e "piscou" — a contagem muda o que fazer.
        sufixo = f" ({vezes}x em 24h)" if vezes > 1 else ""
        out.append(f"{icone} {slug} · {a.get('chave', '?')}{sufixo}\n   {corpo[:300]}")

    for f in d.get("fontes", []):
        if f.get("status") in ("erro", "error", "failed", "falha"):
            porque = " ".join((f.get("error_message") or "").split())
            linha = (f"{ICONE['erro']} {slug} · {f['source']}\n"
                     f"   erro ha {f.get('horas_desde', '?')}h"
                     + (f": {porque[:250]}" if porque else " (sem mensagem gravada)"))
            onde = ONDE_OLHAR.get(f["source"])
            if onde:
                linha += f"\n   -> {onde}"
            out.append(linha)

    for v in d.get("volume", []):
        # A lacuna E da auditoria: verde e vazio e indistinguivel de verde e cheio.
        linha = (f"{ICONE['volume']} {slug} · {v['source']}\n"
                 f"   ultima rodada trouxe {v['ultimo']} (mediana {v['mediana']} "
                 f"das {v['amostras']} anteriores) — rodou sem erro e veio quase vazia")
        onde = ONDE_OLHAR.get(v["source"])
        if onde:
            linha += f"\n   -> {onde}"
        out.append(linha)

    for e in d.get("erros", []):
        out.append(f"{ICONE['atencao']} {slug} · consulta incompleta\n   {e}")

    return out


def montar_mensagem(resultados: list, agora=None) -> str:
    """Monta a mensagem unica. Funcao PURA — e por isso que ela e testavel.

    ⚠️ Texto puro, sem `parse_mode`. Os nomes das fontes tem `_`
    (`transferegov_opendata`, `simec_par`) e no Markdown legado do Telegram um `_`
    solto abre italico que nunca fecha: a API responde 400 «can't parse entities»
    e o relatorio some justamente no dia em que ha o que relatar. Mesma licao do
    canal do watchdog."""
    agora = agora or datetime.now(BRT)
    linhas = [f"\U0001F4CB PACTHA — resumo da coleta · {agora.strftime('%d/%m %H:%M')}", ""]

    for r in resultados:
        linhas.append(_linha_tenant(r))

    fora = [r for r in resultados if not r["ok"]]
    if fora and len(fora) == len(resultados):
        # O alarme mais alto que este relatorio sabe dar.
        linhas += ["", f"{ICONE['erro']} NENHUMA das {len(fora)} APIs respondeu — "
                       "suspeita de VPS fora do ar, nao de coleta."]

    detalhes = [d for r in resultados for d in _detalhes(r)]
    if detalhes:
        linhas += ["", "—— o que olhar ——", ""]
        linhas += detalhes
    elif not fora:
        linhas += ["", "Nada a olhar: nenhuma fonte com erro, nenhum municipio "
                       "defasado, nenhuma queda de volume."]

    texto = "\n".join(linhas)
    if len(texto) <= LIMITE_TELEGRAM:
        return texto

    # ⚠️ CORTA POR ITEM, nunca no meio de um. Um dia ruim com 44 municipios passa
    # de 4.096 facil, e um corte cego deixaria meia linha — "Piracema · SIGCON
    # recu" nao e informacao, e ruido com cara de informacao. Some primeiro o
    # cabecalho (que diz de quando e o relatorio) e as linhas por tenant, que sao
    # o resumo; o que se sacrifica sao os detalhes, do fim para o comeco.
    cabecalho = linhas[:linhas.index("—— o que olhar ——") + 2]
    total = len(detalhes)
    while detalhes:
        detalhes.pop()
        aviso = f"\n\n(… e mais {total - len(detalhes)} itens que nao couberam)"
        texto = "\n".join(cabecalho + detalhes) + aviso
        if len(texto) <= LIMITE_TELEGRAM:
            return texto

    # Nem o cabecalho coube (5 tenants com mensagens de erro enormes). Corta duro:
    # melhor um resumo truncado que chega do que uma mensagem que a API recusa.
    return "\n".join(cabecalho[:-2])[:LIMITE_TELEGRAM - 40] + "\n\n(… truncado)"


def enviar(texto: str) -> bool:
    token = (os.getenv("RESUMO_TELEGRAM_TOKEN") or "").strip()
    chat_id = (os.getenv("RESUMO_TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat_id):
        print("[resumo] sem RESUMO_TELEGRAM_TOKEN/CHAT_ID — nao enviado")
        return False
    corpo = json.dumps({"chat_id": chat_id, "text": texto[:LIMITE_TELEGRAM],
                        "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data=corpo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            print(f"[resumo] telegram: HTTP {r.status}")
            return True
    except Exception as e:
        # ⚠️ O token vai NA URL e o urllib repete a URL na mensagem do erro.
        # Trocar ANTES de cortar — o corte sozinho nao protege, porque a URL
        # comeca pelo token (medido em 08/09/2026 no canal do watchdog).
        print(f"[resumo] falha no telegram: {type(e).__name__}: "
              f"{str(e).replace(token, '<token>')[:200]}")
        return False


def main() -> int:
    janela = int(os.getenv("RESUMO_JANELA_HORAS", "24") or "24")
    resultados = [coletar(t, janela) for t in _tenants()]
    texto = montar_mensagem(resultados)
    print(texto)
    if (os.getenv("RESUMO_DRY_RUN") or "").strip() == "1":
        print("[resumo] DRY RUN — nada enviado")
        return 0
    enviado = enviar(texto)
    # ⚠️ Sai 0 mesmo com tenant fora do ar: o run vermelho seria um SEGUNDO canal
    # de alarme, e um que so o dono ve se abrir o GitHub. O alarme e a mensagem.
    # Vermelho aqui fica reservado para "nao consegui nem falar no Telegram",
    # que e o unico caso em que o relatorio nao chegou a lugar nenhum.
    return 0 if enviado else 1


if __name__ == "__main__":
    sys.exit(main())
