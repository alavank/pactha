// PACTA Captura Automática — service worker
//
// 3 mecanismos automáticos:
//   1) AUTO-CAPTURA: ao navegar em domínios alvo (transferegov/gov.br/saúde),
//      coleta cookies (httpOnly inclusive) e POSTa pro PACTA. Re-captura
//      automática quando a página é navegada/recarregada.
//   2) COOKIE LISTENER: dispara captura quando JSESSIONID/user-id/Session_Gov_Br_Prod
//      são criados/atualizados em domínios alvo (significa que user acabou de
//      logar ou renovou sessão).
//   3) KEEP-ALIVE (chrome.alarms): a cada 12 minutos, faz HEAD em uma URL leve
//      do servidor alvo pra evitar session timeout no JEE (~20-30min inatividade).

const DEFAULT_API = "https://pacta-api-production-9c11.up.railway.app/api";

// Mapeamento host → automation_key + URL de keep-alive
const TARGETS = [
  {
    matches: (h) => h.endsWith(".transferegov.sistema.gov.br") || h === "transferegov.sistema.gov.br",
    key: "govbr",
    keepAliveUrl: "https://discricionarias.transferegov.sistema.gov.br/voluntarias/",
  },
  {
    matches: (h) => h === "www.gov.br" || h === "gov.br" || h.endsWith(".gov.br") && h.includes("transferegov"),
    key: "govbr",
    keepAliveUrl: null,
  },
  {
    matches: (h) => h === "sso.acesso.gov.br" || h.endsWith(".acesso.gov.br"),
    key: "govbr",
    keepAliveUrl: null,
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

async function getConfig() {
  const data = await chrome.storage.local.get(["pacta_api", "pacta_token", "pacta_municipio_id", "pacta_auto_enabled"]);
  return {
    api: data.pacta_api || DEFAULT_API,
    token: data.pacta_token || "",
    municipio_id: parseInt(data.pacta_municipio_id || "0", 10),
    auto_enabled: data.pacta_auto_enabled !== false, // default ON
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

async function capture(host, reason) {
  const cfg = await getConfig();
  if (!cfg.token) {
    console.log("[PACTA] sem token configurado, ignorando captura");
    return;
  }
  if (!cfg.auto_enabled) {
    console.log("[PACTA] auto-captura desabilitada");
    return;
  }

  const target = resolveTarget(host);
  if (!target) return;

  const now = Date.now();
  const dKey = `${target.key}:${host}`;
  if (lastCaptureAt.has(dKey) && now - lastCaptureAt.get(dKey) < DEBOUNCE_MS) {
    console.log(`[PACTA] debounce ativo p/ ${dKey}`);
    return;
  }
  lastCaptureAt.set(dKey, now);

  const cookies = await getAllCookiesForDomain(host);
  if (!cookies.length) {
    console.log(`[PACTA] nenhum cookie pra ${host}`);
    return;
  }
  const httpOnlyCount = cookies.filter((c) => c.httpOnly).length;
  console.log(`[PACTA] capturando ${cookies.length} cookies (${httpOnlyCount} httpOnly) de ${host} [${reason}]`);

  const payload = {
    automation_key: target.key,
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
    const res = await fetch(`${cfg.api}/session-capture`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${cfg.token}`,
      },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      const data = await res.json();
      console.log(`[PACTA] ✓ enviado: id=${data.id} auto_scrape=${data.auto_scrape_started}`);
      // Notifica popup via storage
      chrome.storage.local.set({
        pacta_last_capture: {
          host, reason, n: cookies.length, httpOnly: httpOnlyCount,
          ok: true, at: now, auto_scrape: !!data.auto_scrape_started,
        },
      });
    } else {
      const text = (await res.text()).slice(0, 200);
      console.warn(`[PACTA] ✗ ${res.status}: ${text}`);
      chrome.storage.local.set({
        pacta_last_capture: { host, reason, ok: false, error: `HTTP ${res.status}`, at: now },
      });
    }
  } catch (e) {
    console.error("[PACTA] erro de rede:", e);
    chrome.storage.local.set({
      pacta_last_capture: { host, reason, ok: false, error: e.message, at: now },
    });
  }
}

// 1) AUTO-CAPTURA ao navegar em domínios alvo
chrome.webNavigation.onCompleted.addListener(async (details) => {
  if (details.frameId !== 0) return; // só main frame
  try {
    const u = new URL(details.url);
    if (resolveTarget(u.hostname)) {
      // Pequeno delay pra cookies do response settlearem
      setTimeout(() => capture(u.hostname, "navigation"), 1500);
    }
  } catch (e) { /* ignore */ }
}, { url: [{ schemes: ["https"] }] });

// 2) COOKIE LISTENER — dispara quando cookies de sessão são criados/renovados
chrome.cookies.onChanged.addListener(async (changeInfo) => {
  if (changeInfo.removed) return;
  const c = changeInfo.cookie;
  if (!TRIGGER_COOKIE_NAMES.has(c.name)) return;
  const host = (c.domain || "").replace(/^\./, "");
  const target = resolveTarget(host);
  if (!target) return;
  // delay pra deixar o conjunto inteiro de cookies da resposta chegar
  setTimeout(() => capture(host, `cookie:${c.name}`), 2500);
});

// 3) KEEP-ALIVE periódico — chama URLs alvo pra manter sessão JEE viva
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("pacta_keep_alive", { periodInMinutes: 12 });
  console.log("[PACTA] keep-alive alarm criado (12min)");
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create("pacta_keep_alive", { periodInMinutes: 12 });
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== "pacta_keep_alive") return;
  const cfg = await getConfig();
  if (!cfg.token || !cfg.auto_enabled) return;
  // Para cada target com keepAliveUrl, faz GET (mantém JSESSIONID vivo no servidor)
  for (const t of TARGETS) {
    if (!t.keepAliveUrl) continue;
    try {
      const r = await fetch(t.keepAliveUrl, {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });
      console.log(`[PACTA] keep-alive ${t.keepAliveUrl} → HTTP ${r.status}`);
      // Após ping bem-sucedido, re-captura cookies (servidor pode ter rotacionado)
      if (r.ok) {
        try {
          const u = new URL(t.keepAliveUrl);
          setTimeout(() => capture(u.hostname, "keepalive"), 2000);
        } catch (e) { /* ignore */ }
      }
    } catch (e) {
      console.warn(`[PACTA] keep-alive falhou ${t.keepAliveUrl}: ${e.message}`);
    }
  }
});

console.log("[PACTA] service worker carregado");
