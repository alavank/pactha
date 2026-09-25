"""
Resumo diario da coleta de todos os tenants, numa mensagem so no Telegram.

⭐ POR QUE ISTO NAO RODA NO WORKER

O watchdog (`backend/ingestion/watchdog_coleta.py`) ja vigia a coleta e ja fala no
Telegram — mas de DENTRO do worker. Ele nao consegue relatar a propria morte: se o
container cair ou a Scheduled Task nao disparar, ele nao roda, nao alerta, e **o
silencio fica identico a saude**. Foi essa a forma dos 6 dias de regularidade
estadual parada sem ninguem notar (CONTINUAR.md §1.18).

Por isso este script roda no **GitHub Actions**, que e a unica coisa que o projeto
ja usa e que nao mora na mesma VPS. Ele inverte a pergunta: em vez de esperar o
alerta chegar, vai buscar. E quando NADA responde, isso vira a noticia mais alta
do relatorio — "nao falei com NENHUMA das APIs" e um alarme que ninguem daria hoje.

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
import re
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
    "fns_saldo": "portalfns.saude.gov.br/downloads (REPASSE-FAF-COM-POPULACAO-<ANO>, anual)",
    "emendas_mg": "dados.mg.gov.br portal_emendas_estaduais (CSV de indicacoes da SEGOV)",
    "ses_mg_resolucoes": "pagamentoderesolucoes.saude.mg.gov.br (formulario por municipio e ano)",
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
    # ⚠️ MEDICAO EXPERIMENTAL (23/09/2026): a premissa da sonda — o IdP re-deriva
    # sessao sem o cookie do SP — ainda nao foi vista dando success em producao.
    # Texto neutro de proposito: a acao recomendada (Sair + login) derruba os
    # servidores na hora, e nao pode sair de uma medicao que ainda nao se provou.
    "govbr_sso_roundtrip": ("sonda experimental do SSO (sem cookie do SP) — nao agir so por ela; "
                            "conferir govbr_sso e o aviso de vencimento"),
    "govbr_sso": "login gov.br expirou — no Chrome, extensao do PACTHA > \"Captura completa (abre as 4 portas)\"",
    "obrasgov": "api-publica.obrasgov.gestao.gov.br (o outro host devolve 429)",
    "transferegov_opendata": "dados abertos do TransfereGov (siconv_*.zip)",
    "siconv_licitacao": "dump publico siconv_licitacao.zip (nao depende de login)",
    "transferegov_voluntarias": "APIs novas do TransfereGov",
    "transferegov_pac": "APIs novas do TransfereGov",
    "siconfi": "SICONFI/Tesouro (contas entregues + CAPAG)",
    "tce_rs": "dados.tce.rs.gov.br (403 para IP de datacenter — precisa do oficio)",
    "tce_rs_portal": "portal.tce.rs.gov.br (mesmo bloqueio de borda do outro host)",
    "tce_pr": "pit.tce.pr.gov.br (zip anual do SIM-AM, lido por HTTP Range)",
    "dou_federal": "in.gov.br (busca publica do DOU + pagina de cada ato)",
    "cgu_convenios": "Portal da Transparencia/CGU (planilha de convenios, download-de-dados)",
    "convenios_pr": "transparencia.download.pr.gov.br (CONVENIOS-{ANO}.zip, o SIT aberto)",
    "convenios_to": "convenio.to.gov.br/PesquisaExterna (TRANSFERE.TO, VisualizarConvenio por id)",
    "regularidade_pr": "certidões públicas da SEFA-PR (www4.pr.gov.br) e do TCE-PR (Liberatória)",
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


# Trios `nome:api_uuid:worker_uuid` do build-backend.yml — a lista que o deploy
# usa de verdade, versionada no repo.
_TRIO_CI = re.compile(r"^\s+([a-z0-9-]+):([a-z0-9]{20,}):([a-z0-9]{20,})\s*$")

CAMINHO_CI = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", ".github", "workflows", "build-backend.yml")


def tenants_do_ci(caminho: str = CAMINHO_CI) -> list:
    """Os tenants que o deploy realmente atualiza, lidos do workflow do CI.

    Nao chama rede de proposito: a lista precisa existir mesmo quando a VPS
    inteira esta fora — que e justamente o dia em que este relatorio importa."""
    try:
        with open(caminho, encoding="utf-8") as fh:
            return [m.group(1) for m in
                    (_TRIO_CI.match(ln) for ln in fh) if m]
    except OSError:
        return []


def tenants_ausentes(slugs: list, nomes_ci: list) -> list:
    """Quem o CI deploya e este relatorio nao olha.

    ⚠️ O DEFEITO QUE ISTO PEGA E REAL, NAO HIPOTETICO. A lista de tenants mora
    num secret do repo, e secret nao acompanha merge: o `bgk` entrou na `main` em
    08/09/2026, um dia depois deste script ser escrito "para os cinco". Sem esta
    conferencia, um tenant novo fica invisivel exatamente do jeito mais caro —
    silencio que se parece com saude, que e o defeito que este vigia existe para
    matar.

    O CI usa nome curto (`santamaria`) e a API usa o INSTANCE_SLUG
    (`santamaria-rs`); por isso o casamento e por prefixo, e nao por igualdade.
    Falta de conferencia nunca vira alarme: lista vazia devolve vazio."""
    if not nomes_ci:
        return []
    return [nome for nome in nomes_ci
            if not any(s == nome or s.startswith(f"{nome}-") for s in slugs)]


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
        elif e.code == 409:
            detalhe += " (slug do secret nao e o desta API — duas URLs trocadas?)"
        # ⚠️ RESPOSTA HTTP NAO E SILENCIO. Quem respondeu 401 esta VIVO: o
        # problema e credencial, e mandar o dono olhar a VPS por causa disso e
        # mandar no lugar errado no dia em que ele tem pressa.
        return {"slug": slug, "ok": False, "erro": detalhe,
                "recusa": e.code in (401, 403, 409)}
    except Exception as e:
        return {"slug": slug, "ok": False, "erro": f"{type(e).__name__}: {str(e)[:120]}"}


def _linha_tenant(r: dict) -> str:
    if not r["ok"]:
        # "nao respondeu" para quem respondeu 401 e mentira, e mentira num alarme
        # manda procurar no lugar errado.
        verbo = "API recusou o token" if r.get("recusa") else "API nao respondeu"
        return f"{ICONE['erro']} {r['slug']:<14} {verbo} — {r['erro']}"

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


def _horas(v, padrao: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return padrao


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
        status = f.get("status")
        # ⭐ O PARCIAL ENTROU AQUI EM 09/09/2026, E E A NOTICIA MAIS UTIL DO
        # RELATORIO. A rota ja devolvia o `error_message` de TODA fonte e o
        # resumo so imprimia o das que davam `erro`. Resultado: ele dizia
        # "transferegov_lote: fonte parada" sem NUNCA contar o motivo, que
        # estava gravado no banco desde sempre — "sessao gov.br fria: 153/153
        # leituras atras do login sem retorno". Custou uma manha de investigacao
        # na mao para descobrir o que a propria mensagem ja sabia.
        parcial = status in ("parcial", "partial")
        # `govbr_candidata` e um EVENTO, nao uma coleta periodica: a recusa de uma
        # captura fica como "ultimo estado" ate a proxima promocao, que pode levar
        # semanas. Recusa de hoje e noticia (o Chrome esta mandando jar sem login);
        # a de oito dias atras viraria item fixo nos seis tenants, todo dia.
        if (f.get("source") == "govbr_candidata" and parcial
                and _horas(f.get("horas_desde")) > _horas(d.get("janela_horas"), 24.0)):
            continue
        if parcial or status in ("erro", "error", "failed", "falha"):
            porque = " ".join((f.get("error_message") or "").split())
            # Parcial NAO e erro: ele trouxe dado. Icone e verbo diferentes para
            # nao inflar o tamanho do problema — foi assim que quatro avisos de
            # ruido viraram "catastrofe" na leitura de quem recebe.
            icone = ICONE["atencao"] if parcial else ICONE["erro"]
            cabeca = "rodou PARCIAL ha" if parcial else "erro ha"
            linha = (f"{icone} {slug} · {f['source']}\n"
                     f"   {cabeca} {f.get('horas_desde', '?')}h"
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


def montar_mensagem(resultados: list, agora=None, ausentes=None) -> str:
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
        # O alarme mais alto que este relatorio sabe dar — e por isso mesmo ele
        # precisa acertar o ENDERECO. Medido em 09/09/2026 com o secret ainda
        # vazio: as seis APIs responderam 401 e a versao anterior anunciou
        # "suspeita de VPS fora do ar". Mandar olhar o servidor quando o que
        # esta errado e a credencial custa a manha inteira.
        recusas = [r for r in fora if r.get("recusa")]
        mudos = len(fora) - len(recusas)
        if not mudos:
            linhas += ["", f"{ICONE['erro']} As {len(fora)} APIs responderam e RECUSARAM o "
                           "token — problema de credencial, nao de VPS: o secret "
                           "PACTHA_RESUMO_TENANTS esta desatualizado ou o "
                           "CONTROL_TOKEN_BOOTSTRAP foi rotacionado."]
        elif recusas:
            linhas += ["", f"{ICONE['erro']} NENHUM dos {len(fora)} tenants deu dados: "
                           f"{len(recusas)} recusaram o token e {mudos} nao responderam — "
                           "sao duas causas diferentes, olhe as duas."]
        else:
            linhas += ["", f"{ICONE['erro']} NENHUMA das {len(fora)} APIs respondeu — "
                           "suspeita de VPS fora do ar, nao de coleta."]

    if ausentes:
        # Ponto cego, nao detalhe: tenant fora do secret nao aparece nem como
        # erro — ele some do relatorio inteiro, e o relatorio continua verde.
        verbo = "esta" if len(ausentes) == 1 else "estao"
        linhas += ["", f"{ICONE['atencao']} {', '.join(ausentes)} {verbo} no deploy "
                       "do CI e fora deste resumo — falta por no secret "
                       "PACTHA_RESUMO_TENANTS."]

    # (slug, linha): o slug é o que permite cortar com justiça lá embaixo.
    itens = [(r["slug"], d) for r in resultados for d in _detalhes(r)]
    detalhes = [d for _, d in itens]
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
    total = len(itens)
    while itens:
        # ⚠️ CORTA DO TENANT COM MAIS ITENS, e nao do fim da lista. Medido no
        # primeiro envio real (09/09/2026): 14 itens nao couberam, e como a lista
        # e montada tenant a tenant, o corte cego comeu novapalma e bgk INTEIROS
        # enquanto o freitas ficou com doze linhas. Quem tem mais problema
        # calava quem tem menos — e o cliente pequeno some do relatorio todo dia.
        maior = max({s for s, _ in itens},
                    key=lambda s: sum(1 for x, _ in itens if x == s))
        for i in range(len(itens) - 1, -1, -1):
            if itens[i][0] == maior:
                itens.pop(i)
                break
        aviso = f"\n\n(… e mais {total - len(itens)} itens que nao couberam)"
        texto = "\n".join(cabecalho + [d for _, d in itens]) + aviso
        if len(texto) <= LIMITE_TELEGRAM:
            return texto

    # Nem o cabecalho coube (todos os tenants com mensagens de erro enormes). Corta duro:
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
    tenants = _tenants()
    resultados = [coletar(t, janela) for t in tenants]
    ausentes = tenants_ausentes([str(t.get("slug") or "") for t in tenants],
                                tenants_do_ci())
    if ausentes:
        print(f"[resumo] deployados e fora do secret: {', '.join(ausentes)}")
    texto = montar_mensagem(resultados, ausentes=ausentes)
    print(texto)
    if (os.getenv("RESUMO_DRY_RUN") or "").strip() == "1":
        # ⚠️ No dry run o LOG leva a lista INTEIRA. O corte de 4.096 e do Telegram,
        # e quem roda o dry run esta conferindo producao: em 21/09/2026 a pergunta
        # era "a recaptura pegou nos seis?" e, com "22 itens que nao couberam", a
        # lista visivel nao respondia pelo tenant cortado — consulta truncada nao e
        # evidencia de que o item NAO existe.
        if "itens que nao couberam" in texto:
            print("\n[resumo] lista COMPLETA (so no log; o Telegram corta em 4096):")
            for r in resultados:
                for d in _detalhes(r):
                    print(d)
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
