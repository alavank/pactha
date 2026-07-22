// PACTHA Captura Automática — popup logic
// Ver nota em background.js: dominio novo (Coolify) e obrigatoriedade de
// host_permissions no manifest.json.
const DEFAULT_API = "https://pactha-api-54-232-208-118.sslip.io/api";

const $ = (id) => document.getElementById(id);

// Ver nota em background.js: config salva no dominio morto vence o DEFAULT_API,
// entao reescrevemos aqui tambem (o popup pode abrir antes do service worker).
const LEGACY_API_HOSTS = ["pactha.alavank.com.br"];

function migrarApiLegado(api) {
  if (api && LEGACY_API_HOSTS.some((h) => api.includes(h))) {
    chrome.storage.local.set({ pactha_api: DEFAULT_API });
    return DEFAULT_API;
  }
  return api;
}

async function getConfig() {
  return new Promise((res) => {
    chrome.storage.local.get(
      ["pactha_api", "pactha_token", "pactha_municipio_id", "pactha_auto_enabled", "pactha_last_capture"],
      (data) => res({
        api: migrarApiLegado(data.pactha_api || DEFAULT_API),
        token: data.pactha_token || "",
        municipio_id: data.pactha_municipio_id || "6",
        auto_enabled: data.pactha_auto_enabled !== false,
        last_capture: data.pactha_last_capture || null,
      })
    );
  });
}

async function saveConfig(api, token) {
  return new Promise((res) => {
    chrome.storage.local.set({ pactha_api: api, pactha_token: token }, res);
  });
}

function showStatus(msg, kind) {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + kind;
}

async function getCurrentTab() {
  return new Promise((res) => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => res(tabs[0]));
  });
}

function getDomainFromUrl(url) {
  try { return new URL(url).hostname; } catch (e) { return null; }
}

function getRegistrableDomain(host) {
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  if (parts.slice(-2).join(".") === "gov.br") return parts.slice(-3).join(".");
  return parts.slice(-2).join(".");
}

async function getAllCookiesForDomain(host) {
  const root = getRegistrableDomain(host);
  const domains = new Set([host, "." + host, root, "." + root, "gov.br", ".gov.br"]);
  if (host.endsWith(".transferegov.sistema.gov.br")) {
    [
      "discricionarias","mandatarias","fiscalizacao","transfere",
      "idp","parcerias","cadastro","especiais","fundos","ted",
    ].forEach((sub) => {
      domains.add(`${sub}.transferegov.sistema.gov.br`);
      domains.add(`.${sub}.transferegov.sistema.gov.br`);
    });
    domains.add(".transferegov.sistema.gov.br");
    domains.add("transferegov.sistema.gov.br");
  }
  const seen = new Set();
  const out = [];
  await Promise.all([...domains].map((d) =>
    new Promise((resolve) => {
      chrome.cookies.getAll({ domain: d }, (cookies) => {
        for (const c of cookies || []) {
          const key = `${c.domain}|${c.name}|${c.path}`;
          if (!seen.has(key)) { seen.add(key); out.push(c); }
        }
        resolve();
      });
    })
  ));
  return out;
}

async function captureManual() {
  const cfg = await getConfig();
  if (!cfg.token) {
    showStatus("Configure o token PACTHA primeiro", "error");
    return;
  }
  const tab = await getCurrentTab();
  const host = getDomainFromUrl(tab.url);
  if (!host) {
    showStatus("Aba atual sem URL valida", "error");
    return;
  }
  showStatus("Coletando cookies (incluindo httpOnly)...", "info");
  const cookies = await getAllCookiesForDomain(host);
  if (!cookies.length) {
    showStatus("Nenhum cookie encontrado", "error");
    return;
  }
  const httpOnly = cookies.filter((c) => c.httpOnly).length;
  showStatus(`Enviando ${cookies.length} cookies (${httpOnly} httpOnly)...`, "info");

  const payload = {
    automation_key: $("automation-key").value,
    municipio_id: parseInt($("municipio-id").value || "6", 10),
    cookie: cookies.map((c) => `${c.name}=${c.value}`).join("; "),
    cookies_full: cookies.map((c) => ({
      name: c.name, value: c.value, domain: c.domain, path: c.path,
      httpOnly: c.httpOnly, secure: c.secure, sameSite: c.sameSite,
      expirationDate: c.expirationDate,
    })),
    url_atual: tab.url,
    user_agent: navigator.userAgent,
    domain_capturado: host,
  };
  try {
    const isServiceToken = cfg.token.startsWith("pactha_");
    const authHeaders = isServiceToken
      ? { "X-Service-Token": cfg.token }
      : { Authorization: `Bearer ${cfg.token}` };
    const res = await fetch(`${cfg.api}/session-capture`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify(payload),
    });
    if (res.status === 401) { showStatus("Token PACTHA invalido. Reconfigure.", "error"); return; }
    if (!res.ok) { showStatus(`Erro ${res.status}`, "error"); return; }
    const data = await res.json();
    showStatus(
      `OK! ${cookies.length} cookies (${httpOnly} httpOnly) ${data.auto_scrape_started ? "+ scraper disparado" : ""}`,
      "success"
    );
  } catch (e) {
    showStatus(`Erro: ${e.message}`, "error");
  }
}

function fmtTimeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return `${s}s atrás`;
  if (s < 3600) return `${Math.floor(s/60)}min atrás`;
  return `${Math.floor(s/3600)}h atrás`;
}

async function refreshLastCapture() {
  const cfg = await getConfig();
  const el = $("last-capture-info");
  if (!cfg.last_capture) {
    el.textContent = "Aguardando primeira captura...";
    el.className = "info";
    return;
  }
  const lc = cfg.last_capture;
  if (lc.ok) {
    el.innerHTML = `✓ Última: <strong>${lc.host}</strong> · ${lc.n} cookies (${lc.httpOnly} httpOnly) · ${fmtTimeAgo(lc.at)}${lc.auto_scrape ? " · scraper disparado" : ""}`;
    el.className = "info";
  } else {
    el.innerHTML = `✗ Última falhou: ${lc.host} · ${lc.error} · ${fmtTimeAgo(lc.at)}`;
    el.className = "info";
  }
}

async function init() {
  const cfg = await getConfig();
  const tab = await getCurrentTab();
  const host = getDomainFromUrl(tab.url);

  // Estado do toggle auto
  $("toggle-auto").checked = cfg.auto_enabled;
  if (!cfg.auto_enabled) {
    $("auto-card").classList.add("off");
    $("auto-title").textContent = "Modo automático DESLIGADO";
  }

  $("domain-info").innerHTML = host
    ? `<strong>Domínio atual:</strong> ${host}`
    : "Nenhum domínio detectado";

  // Mostra para onde a captura vai de fato. Sem isso, uma config antiga salva
  // apontando para um host fora do host_permissions falha silenciosamente (o
  // Chrome bloqueia o fetch) e nao ha como diagnosticar pela interface.
  $("api-info").textContent = `API: ${cfg.api}${cfg.token ? "" : "  (sem token configurado)"}`;

  // Auto-detect select baseado no domínio
  if (host) {
    if (host.includes("consultafns")) $("automation-key").value = "fns";
    else if (host.includes("simec")) $("automation-key").value = "simec";
    else if (host.includes("sismob")) $("automation-key").value = "sismob";
    else if (host.includes("estruturasuas")) $("automation-key").value = "suas";
    else if (host.includes("investsus")) $("automation-key").value = "investsus";
    else if (host.includes("gov.br")) $("automation-key").value = "govbr";
  }

  $("municipio-id").value = cfg.municipio_id;

  // Eventos
  $("toggle-auto").addEventListener("change", async (e) => {
    await new Promise((r) => chrome.storage.local.set({ pactha_auto_enabled: e.target.checked }, r));
    if (e.target.checked) {
      $("auto-card").classList.remove("off");
      $("auto-title").textContent = "Modo automático ativo";
    } else {
      $("auto-card").classList.add("off");
      $("auto-title").textContent = "Modo automático DESLIGADO";
    }
  });

  $("municipio-id").addEventListener("change", async (e) => {
    await new Promise((r) => chrome.storage.local.set({ pactha_municipio_id: e.target.value }, r));
  });

  $("btn-capture").addEventListener("click", captureManual);

  $("btn-config").addEventListener("click", () => {
    $("main").classList.add("hidden");
    $("config").classList.remove("hidden");
    $("cfg-api-url").value = cfg.api;
    $("cfg-token").value = cfg.token;
  });
  $("btn-save-config").addEventListener("click", async () => {
    const api = $("cfg-api-url").value.trim();
    const token = $("cfg-token").value.trim();
    if (!api || !token) { alert("Preencha API URL e Token"); return; }
    await saveConfig(api, token);
    $("config").classList.add("hidden");
    $("main").classList.remove("hidden");
    showStatus("Configuração salva. Auto-captura ativa.", "success");
  });
  $("btn-cancel-config").addEventListener("click", () => {
    $("config").classList.add("hidden");
    $("main").classList.remove("hidden");
  });
  $("open-pacta").addEventListener("click", () => {
    // Deriva do API URL configurado em vez de fixar um dominio: cada tenant tem
    // o seu, e o antigo (pactha.alavank.com.br) nao resolve mais.
    let url = "https://pactha-54-232-208-118.sslip.io/dashboard";
    try {
      const u = new URL(cfg.api);
      url = `${u.origin.replace("-api-", "-")}/dashboard`;
    } catch (_) { /* usa o padrao acima */ }
    chrome.tabs.create({ url });
  });

  if (!cfg.token) {
    showStatus("Configure o token PACTHA antes de capturar", "info");
  }

  refreshLastCapture();
  // Atualiza relógio do "última captura" a cada segundo
  setInterval(refreshLastCapture, 2000);
}

init();
