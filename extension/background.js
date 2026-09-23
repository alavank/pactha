// PACTHA Captura Automática — service worker
//
// 3 mecanismos automáticos:
//   1) AUTO-CAPTURA: ao navegar em domínios alvo (transferegov/gov.br/saúde),
//      coleta cookies (httpOnly inclusive) e POSTa pro PACTHA. Re-captura
//      automática quando a página é navegada/recarregada.
//   2) COOKIE LISTENER: dispara captura quando JSESSIONID/user-id/Session_Gov_Br_Prod
//      são criados/atualizados em domínios alvo (significa que user acabou de
//      logar ou renovou sessão).
//   3) KEEP-ALIVE (chrome.alarms): a cada 12 minutos, faz HEAD em uma URL leve
//      do servidor alvo pra evitar session timeout no JEE (~20-30min inatividade).

// Ambiente novo (Coolify). O dominio antigo (pactha.alavank.com.br) nao resolve
// mais. Cada tenant tem sua propria API — configure a URL no popup:
//   freitas -> https://pactha-api-54-232-208-118.sslip.io/api
//   trust   -> https://pactha-trust-54-232-208-118.sslip.io/api
// IMPORTANTE: qualquer dominio usado aqui precisa estar em host_permissions no
// manifest.json, senao o Chrome bloqueia o fetch antes de sair (MV3) e a captura
// falha sem nunca chegar no servidor.
// ⚠️ `importScripts` E NAO `import`: o service worker deste manifest e script
// CLASSICO (sem "type": "module"). Trocar para modulo exigiria mexer no
// manifest e no popup ao mesmo tempo, e um dos dois ficando para tras deixa a
// extensao carregando pela metade — sem erro visivel, so sem funcionar.
// ⚠️ `tokens.local.js` PRIMEIRO, e dentro de try/catch. Ele é opcional e NÃO
// está no repositório (carrega segredo): quem instala grava os tokens ali para
// que ninguém precise colar nada. `importScripts` LANÇA quando o arquivo não
// existe — sem o try, a instalação limpa (o caso do repo) mataria o service
// worker inteiro na primeira linha, e a extensão simplesmente não subiria.
try {
  importScripts("tokens.local.js");
} catch (_e) {
  /* instalação sem tokens pré-configurados: a tela pede a colagem, como antes */
}
importScripts("ambientes.js");

const DEFAULT_API = "https://pactha-api-54-232-208-118.sslip.io/api";

// Mapeamento host → automation_key + URL de keep-alive
const TARGETS = [
  {
    matches: (h) => h.endsWith(".transferegov.sistema.gov.br") || h === "transferegov.sistema.gov.br",
    key: "govbr",
    keepAliveUrl: "https://discricionarias.transferegov.sistema.gov.br/voluntarias/",
  },
  /* ⚠️ `gatilho: false` — ESTES DOIS NÃO DISPARAM MAIS CAPTURA (21/09/2026).
     `www.gov.br` é o portal de notícias e `sso.acesso.gov.br` é A PRÓPRIA TELA DE
     LOGIN: navegar neles deslogado mandava um jar SEM login para os seis Cofres,
     por cima da sessão viva do servidor. Os cookies deles continuam ENTRANDO no
     jar (`getAllCookiesForDomain` coleta "gov.br" inteiro); o que saiu foi só o
     gatilho. Depois do login o gov.br devolve para o TransfereGov, e é LÁ que a
     captura dispara — já com a sessão pronta. */
  {
    matches: (h) => h === "www.gov.br" || h === "gov.br" || h.endsWith(".gov.br") && h.includes("transferegov"),
    key: "govbr",
    keepAliveUrl: null,
    gatilho: false,
  },
  {
    matches: (h) => h === "sso.acesso.gov.br" || h.endsWith(".acesso.gov.br"),
    key: "govbr",
    keepAliveUrl: null,
    gatilho: false,
  },
  {
    matches: (h) => h === "consultafns.saude.gov.br",
    key: "fns",
    keepAliveUrl: "https://consultafns.saude.gov.br/",
  },
  {
    matches: (h) => h === "simec.mec.gov.br",
    key: "simec",
    keepAliveUrl: "https://simec.mec.gov.br/",
  },
  {
    matches: (h) => h === "sismobcidadao.saude.gov.br",
    key: "sismob",
    keepAliveUrl: null,
  },
  {
    matches: (h) => h === "estruturasuas.mds.gov.br",
    key: "suas",
    keepAliveUrl: null,
  },
];

// Cookies que indicam "sessão recém-renovada" — disparam captura imediata
const TRIGGER_COOKIE_NAMES = new Set([
  "JSESSIONID",
  "user-id",
  "Session_Gov_Br_Prod",
  "Govbrid",
  "XSRF-TOKEN",
]);

// Debounce: evita capturas redundantes em sequência
const lastCaptureAt = new Map();
const DEBOUNCE_MS = 30 * 1000; // 30s entre capturas do mesmo domínio

function resolveTarget(host) {
  for (const t of TARGETS) {
    if (t.matches(host)) return t;
  }
  return null;
}

function getRegistrableDomain(host) {
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  if (parts.slice(-2).join(".") === "gov.br") {
    return parts.slice(-3).join(".");
  }
  return parts.slice(-2).join(".");
}

// Dominios que sairam do ar. Uma config salva neles vence o DEFAULT_API (que so
// vale quando nao ha nada gravado), entao trocar a constante nao basta: quem ja
// usava a extensao continuaria apontando para o endereco morto. Reescrevemos.
const LEGACY_API_HOSTS = ["pactha.alavank.com.br"];

function migrarApiLegado(api) {
  if (api && LEGACY_API_HOSTS.some((h) => api.includes(h))) {
    console.log(`[PACTHA] API URL antiga (${api}) migrada para ${DEFAULT_API}`);
    return DEFAULT_API;
  }
  return api;
}

async function getConfig() {
  const data = await chrome.storage.local.get(["pactha_api", "pactha_token", "pactha_municipio_id", "pactha_auto_enabled"]);
  const apiMigrada = migrarApiLegado(data.pactha_api || DEFAULT_API);
  if (data.pactha_api && apiMigrada !== data.pactha_api) {
    await chrome.storage.local.set({ pactha_api: apiMigrada });
  }
  return {
    api: apiMigrada,
    token: data.pactha_token || "",
    municipio_id: parseInt(data.pactha_municipio_id || "0", 10),
    auto_enabled: data.pactha_auto_enabled !== false, // default ON
  };
}

async function getAllCookiesForDomain(host) {
  // Coleta cookies dos vários níveis do host (host, .host, root, .root, .gov.br)
  const root = getRegistrableDomain(host);
  const candidates = new Set([host, "." + host, root, "." + root, "gov.br", ".gov.br"]);
  // Também coleta dos subdomínios IRMÃOS do transferegov (todos compartilham SSO)
  if (host.endsWith(".transferegov.sistema.gov.br")) {
    [
      "discricionarias", "mandatarias", "fiscalizacao", "transfere",
      "idp", "parcerias", "cadastro", "especiais", "fundos", "ted",
    ].forEach((sub) => {
      candidates.add(`${sub}.transferegov.sistema.gov.br`);
      candidates.add(`.${sub}.transferegov.sistema.gov.br`);
    });
    candidates.add(".transferegov.sistema.gov.br");
    candidates.add("transferegov.sistema.gov.br");
  }
  const seen = new Set();
  const out = [];
  await Promise.all([...candidates].map((d) =>
    new Promise((resolve) => {
      chrome.cookies.getAll({ domain: d }, (cookies) => {
        for (const c of cookies || []) {
          const key = `${c.domain}|${c.name}|${c.path}`;
          if (!seen.has(key)) {
            seen.add(key);
            out.push(c);
          }
        }
        resolve();
      });
    })
  ));
  return out;
}

async function capture(host, reason, opts) {
  const forcar = !!(opts && opts.forcar);   // a captura FINAL do roteiro fura o debounce
  const cfg = await getConfig();
  /* ⚠️ O PORTEIRO OLHA A LISTA, e a versao anterior desta funcao NAO olhava —
     era o defeito mais grave desta mudanca, achado em revisao antes de subir.
     Ele barrava por `cfg.token`, o `pactha_token` UNICO, que depois da migracao
     multi-ambiente NINGUEM MAIS ESCREVE (o campo saiu da tela e `saveConfig`
     ficou sem chamador). Em perfil novo ele e "" para sempre, entao este
     `return` matava TODA a auto-captura — enquanto o popup exibia
     "Captura em 5 de 5 ambiente(s)" e a captura MANUAL funcionava.
     Era o mesmo modo de falha silencioso que esta mudanca existe para
     eliminar, agora com a interface afirmando o contrario. */
  const ambientes = await lerAmbientes();
  if (!ambientes.some((a) => a.token && a.ativo !== false)) {
    console.log("[PACTHA] nenhum ambiente com token, ignorando captura");
    return;
  }
  // ⚠️ `forcar` (o fim da "Captura completa") é AÇÃO DA PESSOA, como a captura
  // manual: o toggle do modo AUTOMÁTICO não pode barrá-la. Barrando, o botão que o
  // alerta manda usar virava no-op silencioso com o toggle desligado — as 4 portas
  // abriam, o roteiro "terminava" e nenhum POST saía.
  if (!cfg.auto_enabled && !forcar) {
    console.log("[PACTHA] auto-captura desabilitada");
    return;
  }

  const target = resolveTarget(host);
  if (!target) return;

  const now = Date.now();
  const dKey = `${target.key}:${host}`;
  if (!forcar && lastCaptureAt.has(dKey) && now - lastCaptureAt.get(dKey) < DEBOUNCE_MS) {
    console.log(`[PACTHA] debounce ativo p/ ${dKey}`);
    return;
  }
  /* ⭐ O PORTEIRO DO LOGIN: jar `govbr` só sai com o Chrome LOGADO (ver
     `chromeEstaLogado` em ambientes.js). `null` = a sonda não soube dizer, e aí
     a captura SEGUE — o servidor tem a guarda dele.
     ⚠️ ANTES de marcar o debounce: durante um login, a página de auto-envio do
     SAML dispara esta função ainda deslogada — se ela marcasse o debounce, a
     captura BOA, dois segundos depois, seria descartada por 30s. */
  if (target.key === "govbr") {
    const logado = await chromeEstaLogado();
    if (logado === false) {
      console.log(`[PACTHA] Chrome sem login gov.br — nada enviado [${reason}@${host}]`);
      return;
    }
  }
  lastCaptureAt.set(dKey, now);

  const cookies = await getAllCookiesForDomain(host);
  if (!cookies.length) {
    console.log(`[PACTHA] nenhum cookie pra ${host}`);
    return;
  }
  const httpOnlyCount = cookies.filter((c) => c.httpOnly).length;
  console.log(`[PACTHA] capturando ${cookies.length} cookies (${httpOnlyCount} httpOnly) de ${host} [${reason}]`);

  const payload = {
    automation_key: target.key,
    // ⚠️ IGNORADO por `enviarParaTodos`, que sobrescreve com escopo de
    // instancia. Fica aqui so para o payload continuar completo se alguem
    // reaproveitar este objeto — ver a nota em `ambientes.js`.
    municipio_id: cfg.municipio_id || 1,
    cookie: cookies.map((c) => `${c.name}=${c.value}`).join("; "),
    cookies_full: cookies.map((c) => ({
      name: c.name, value: c.value, domain: c.domain, path: c.path,
      httpOnly: c.httpOnly, secure: c.secure, sameSite: c.sameSite,
      expirationDate: c.expirationDate,
    })),
    url_atual: `auto:${reason}@${host}`,
    user_agent: navigator.userAgent,
    domain_capturado: host,
  };

  try {
    // ⚠️ MANDA PARA TODOS OS AMBIENTES, e nao so para o configurado. Ver o
    // cabecalho de `ambientes.js`: cada tenant tem Cofre proprio e capturar num
    // deles deixava os outros com o cookie velho, sem erro nenhum.
    const lista = await lerAmbientes();
    const resultados = await enviarParaTodos(payload, lista);
    const bons = resultados.filter((r) => r.ok);
    const ruins = resultados.filter((r) => !r.ok);
    console.log(`[PACTHA] auto: ${resumoEnvio(resultados)}`
      + (ruins.length ? ` | falharam: ${ruins.map((r) => `${r.nome} (${r.detalhe})`).join(", ")}` : ""));
    // ⚠️ GRAVA SEMPRE, INCLUSIVE 0 DE 5 — e este `if` que nao existe mais era um
    // defeito FATAL. Havia aqui um `if (bons.length)`: falha TOTAL nao gravava
    // nada, entao o popup seguia exibindo o cartao verde da ultima captura que
    // deu certo, de ontem. E o `catch` de baixo nao salvava: `enviarParaTodos`
    // trata cada alvo no seu proprio try e NUNCA rejeita, logo aquele ramo era
    // inalcancavel para este caso.
    //
    // O detalhe que torna isso grave: com UM token por ambiente a falha realista
    // era PARCIAL (1 de 5), e parcial era gravado. Quanto mais a configuracao
    // converge — mesma origem para todos os tokens, tudo emitido de uma vez — mais
    // a falha realista vira 0 de 5, que era exatamente o unico caso cego. A
    // instrumentacao precisa ser mais confiavel conforme o resto melhora, nao menos.
    chrome.storage.local.set({
      pactha_last_capture: {
        quando: new Date().toISOString(),
        cookies: cookies.length,
        httpOnly: httpOnlyCount,
        host,
        reason,
        ambientes_ok: bons.length,
        ambientes_total: resultados.length,
        // ⚠️ Os que falharam vao NOMEADOS para o popup. Guardar so a
        // contagem faria "4 de 5" virar um numero sem acao possivel.
        falhas: ruins.map((r) => `${r.nome}: ${r.detalhe}`),
      },
    });
    // O servidor mede a sessão nova no próximo keepalive (até ~10 min); o selo
    // é reconferido já e de novo no próximo alarme.
    atualizarSaude({ forcar: true });
  } catch (e) {
    console.error("[PACTHA] erro de rede:", e);
    chrome.storage.local.set({
      pactha_last_capture: { host, reason, ok: false, error: e.message, at: now },
    });
  }
}

// 1) AUTO-CAPTURA ao navegar em domínios alvo
chrome.webNavigation.onCompleted.addListener(async (details) => {
  if (details.frameId !== 0) return; // só main frame
  try {
    const u = new URL(details.url);
    const alvo = resolveTarget(u.hostname);
    if (alvo && alvo.gatilho !== false) {
      // Pequeno delay pra cookies do response settlearem
      setTimeout(() => capture(u.hostname, "navigation"), 1500);
    }
  } catch (e) { /* ignore */ }
}, { url: [{ schemes: ["https"] }] });

/* ROTEIRO DA CAPTURA COMPLETA — o botão do popup. Abre as QUATRO portas
   (`PORTAS_GOVBR`, em ambientes.js) na MESMA aba, uma depois da outra, e no fim
   faz UMA captura forçada com o jar inteiro.

   ⚠️ NÃO AUTOMATIZA LOGIN. Se a porta cair na tela do gov.br, o roteiro PARA e
   espera: quem loga é a pessoa (reCAPTCHA). Quando o gov.br devolve para o
   TransfereGov, a navegação completa de novo e o roteiro segue sozinho.

   ⚠️ O ESTADO MORA NO STORAGE, não numa variável: o service worker do MV3 morre
   com ~30s de ócio, e o login leva minutos. Vence em 20 min para não sequestrar
   uma aba esquecida. */
const ROTEIRO_TTL_MS = 20 * 60 * 1000;

function iniciarCapturaCompleta() {
  chrome.tabs.create({ url: PORTAS_GOVBR[0].url }, (tab) => {
    chrome.storage.local.set({ pactha_roteiro: { tabId: tab.id, passo: 0, em: Date.now() } });
  });
}

async function avancarRoteiro(details) {
  const { pactha_roteiro: rot } = await chrome.storage.local.get(["pactha_roteiro"]);
  if (!rot || details.tabId !== rot.tabId) return;
  if (Date.now() - rot.em > ROTEIRO_TTL_MS) {
    await chrome.storage.local.remove("pactha_roteiro");
    console.warn("[PACTHA] roteiro da captura completa venceu (20 min sem avançar) — clique de novo");
    return;
  }
  if (pareceLogin(details.url)) {
    // Esperando a PESSOA logar (reCAPTCHA, 2FA, telefone). O prazo de 20 min conta
    // do ÚLTIMO carregamento da tela de login, não do clique — senão um login
    // demorado fazia o roteiro morrer calado no meio, sem abrir as portas 2–4.
    await chrome.storage.local.set({ pactha_roteiro: { ...rot, em: Date.now() } });
    return;
  }
  let host = "";
  try { host = new URL(details.url).hostname; } catch (_) { return; }
  // Só conta página do TransfereGov — e o `idp.` dele é o SAML EM TRÂNSITO
  // (form auto-post): avançar ali abortaria o login daquela porta no meio.
  if (!host.endsWith("transferegov.sistema.gov.br") || host.startsWith("idp.")) return;
  /* ⚠️ SÓ AVANÇA SE A PÁGINA ASSENTOU. O SAML encadeia navegações; trocar a URL
     da aba no meio da cadeia mata a sessão da porta que estava nascendo. Espera
     3s e confere que a aba continua NA MESMA URL e que ninguém avançou antes. */
  const semFragmento = (u) => String(u || "").split("#")[0];
  const conferir = async (tentativa) => {
    try {
      const tab = await chrome.tabs.get(rot.tabId);
      if (!tab || semFragmento(tab.url) !== semFragmento(details.url)) return;  // navegou: o próximo evento decide
      /* ⚠️ `status`, e não só a URL: a página de auto-envio do SAML pode ter A
         MESMA URL da página final. Enquanto o POST ao idp está pendente a aba
         fica "loading" — avançar aí mataria a sessão da porta que estava
         nascendo. Reconfere de 2 em 2s, até ~20s. */
      if (tab.status !== "complete") {
        if (tentativa < 10) setTimeout(() => conferir(tentativa + 1), 2000);
        return;
      }
      const { pactha_roteiro: atual } = await chrome.storage.local.get(["pactha_roteiro"]);
      if (!atual || atual.passo !== rot.passo || atual.tabId !== rot.tabId) return;
      const proximo = rot.passo + 1;
      if (proximo < PORTAS_GOVBR.length) {
        await chrome.storage.local.set({ pactha_roteiro: { ...rot, passo: proximo } });
        chrome.tabs.update(rot.tabId, { url: PORTAS_GOVBR[proximo].url });
      } else {
        await chrome.storage.local.remove("pactha_roteiro");
        capture(host, "captura_completa", { forcar: true });
        // De novo em 12s: a sessão da ÚLTIMA porta pode terminar de nascer depois
        // do primeiro envio, e o debounce engoliria a captura natural dela.
        setTimeout(() => capture(host, "captura_completa_2", { forcar: true }), 12000);
      }
    } catch (e) {
      console.warn("[PACTHA] roteiro (avanço): " + (e && e.message || e));
    }
  };
  setTimeout(() => conferir(0), 3000);
}

chrome.webNavigation.onCompleted.addListener((details) => {
  if (details.frameId !== 0) return;
  avancarRoteiro(details).catch((e) => console.warn("[PACTHA] roteiro: " + (e && e.message || e)));
}, { url: [{ schemes: ["https"] }] });

chrome.runtime.onMessage.addListener((msg, _sender, responder) => {
  if (msg && msg.tipo === "captura_completa") {
    iniciarCapturaCompleta();
    responder({ ok: true });
  }
  return false;
});

// 2) COOKIE LISTENER — dispara quando cookies de sessão são criados/renovados
chrome.cookies.onChanged.addListener(async (changeInfo) => {
  if (changeInfo.removed) return;
  const c = changeInfo.cookie;
  if (!TRIGGER_COOKIE_NAMES.has(c.name)) return;
  const host = (c.domain || "").replace(/^\./, "");
  const target = resolveTarget(host);
  if (!target || target.gatilho === false) return;
  // delay pra deixar o conjunto inteiro de cookies da resposta chegar
  setTimeout(() => capture(host, `cookie:${c.name}`), 2500);
});

// 3) KEEP-ALIVE periódico — chama URLs alvo pra manter sessão JEE viva
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("pactha_keep_alive", { periodInMinutes: 12 });
  console.log("[PACTHA] keep-alive alarm criado (12min)");
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("pactha_keep_alive", { periodInMinutes: 12 });
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "pactha_keep_alive") return;
  const cfg = await getConfig();
  /* ⚠️ O KEEP-ALIVE NAO PRECISA DE TOKEN DO PACTHA. Ele faz GET numa URL do
     GOVERNO para o JSESSIONID nao expirar por ociosidade — nada disso passa
     pela nossa API. Barrar por token era acoplamento sem motivo, e depois da
     migracao virou barreira permanente: `cfg.token` nunca mais e preenchido, e
     a sessao passaria a morrer por ociosidade num perfil novo mesmo com os
     cinco ambientes configurados. Fica so o `auto_enabled`, que e a escolha
     explicita do usuario. */
  if (!cfg.auto_enabled) return;
  // Para cada target com keepAliveUrl, faz GET (mantém JSESSIONID vivo no servidor)
  for (const t of TARGETS) {
    if (!t.keepAliveUrl) continue;
    try {
      const r = await fetch(t.keepAliveUrl, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });
      console.log(`[PACTHA] keep-alive ${t.keepAliveUrl} → HTTP ${r.status} (${r.url})`);
      // Após ping bem-sucedido, re-captura cookies (servidor pode ter rotacionado).
      // ⚠️ `r.ok` SOZINHO MENTIA: o fetch segue o redirect, e a TELA DE LOGIN do
      // gov.br responde 200. Com o Chrome deslogado isto mandava, de 12 em 12
      // minutos, um jar sem login por cima da sessão viva dos seis servidores.
      if (r.ok && !pareceLogin(r.url)) {
        try {
          const u = new URL(t.keepAliveUrl);
          setTimeout(() => capture(u.hostname, "keepalive"), 2000);
        } catch (e) { /* ignore */ }
      } else if (r.ok) {
        console.log("[PACTHA] keep-alive caiu na tela de login — Chrome sem sessão, nada enviado");
      }
    } catch (e) {
      console.warn(`[PACTHA] keep-alive falhou ${t.keepAliveUrl}: ${e.message}`);
    }
  }
  await atualizarSaude({ forcar: true });
});

/* SAÚDE DA SESSÃO DO SERVIDOR → selo no ícone. Roda junto do alarme (12 min),
   ao subir o service worker e depois de cada captura. Vermelho "!" só quando
   algum ambiente MEDIU que o login caiu; falha de rede ou servidor ainda sem a
   rota não pinta nada (alarme que toca à toa deixa de ser lido). */
async function atualizarSaude(opts) {
  try {
    /* O service worker renasce a cada evento (qualquer cookie, qualquer aba): sem
       este freio, a chamada do topo do arquivo faria 6 GETs toda vez. Alarme e
       captura passam `forcar`. */
    if (!(opts && opts.forcar)) {
      const { pactha_saude: ult } = await chrome.storage.local.get(["pactha_saude"]);
      if (ult && ult.quando && Date.now() - Date.parse(ult.quando) < 5 * 60 * 1000) return;
    }
    const itens = await consultarSaude(await lerAmbientes());
    await new Promise((r) => chrome.storage.local.set(
      { pactha_saude: { quando: new Date().toISOString(), itens } }, r));
    // Sem NENHUMA resposta (offline, deploy no meio) não se sabe nada: o selo fica
    // como estava — apagar o "!" aqui seria afirmar que a sessão voltou.
    if (!itens.some((i) => i.ok)) return;
    const caiu = algumPrecisaRecapturar(itens);
    // ⏰ = ainda vivo, mas dentro da janela de aviso (padrão medido ~24h): logar
    // de novo AGORA evita a noite de coleta sem login. "!" (caiu) tem precedência.
    const vencendo = !caiu && algumVencendo(itens);
    if (chrome.action && chrome.action.setBadgeText) {
      chrome.action.setBadgeText({ text: caiu ? "!" : (vencendo ? "⏰" : "") });
      if ((caiu || vencendo) && chrome.action.setBadgeBackgroundColor) {
        chrome.action.setBadgeBackgroundColor({ color: caiu ? "#c53030" : "#dd6b20" });
      }
      chrome.action.setTitle({
        title: caiu
          ? "PACTHA — a sessão gov.br do servidor CAIU. Clique para recapturar."
          : (vencendo
            ? "PACTHA — a sessão gov.br vence em breve. Clique e faça o login de novo."
            : "PACTHA - Captura Automática"),
      });
    }
  } catch (e) {
    console.warn("[PACTHA] saúde da sessão: " + (e && e.message || e));
  }
}
atualizarSaude();

console.log("[PACTHA] service worker carregado");
