// PACTA Captura de Sessao - popup logic
const DEFAULT_API = "https://pacta-api-production-9c11.up.railway.app/api";

const $ = (id) => document.getElementById(id);

async function getConfig() {
  return new Promise((res) => {
    chrome.storage.local.get(["pacta_api", "pacta_token"], (data) => {
      res({
        api: data.pacta_api || DEFAULT_API,
        token: data.pacta_token || "",
      });
    });
  });
}

async function saveConfig(api, token) {
  return new Promise((res) => {
    chrome.storage.local.set({ pacta_api: api, pacta_token: token }, res);
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
  try {
    const u = new URL(url);
    return u.hostname;
  } catch (e) {
    return null;
  }
}

// Pega o "registrable domain" (ex: gov.br para www.gov.br ou consultafns.saude.gov.br)
function getRegistrableDomain(host) {
  // Lista simples para .gov.br - pega os ultimos 2 niveis
  // Para *.gov.br pega "gov.br"
  // Para *.saude.gov.br pega "saude.gov.br" (subdominio relevante)
  // Vamos pegar o dominio + um nivel (ex: "saude.gov.br")
  const parts = host.split(".");
  if (parts.length <= 2) return host;
  // Para gov.br, pegar os ultimos 3 niveis (saude.gov.br, mds.gov.br) ou 2 (gov.br)
  if (parts.slice(-2).join(".") === "gov.br") {
    return parts.slice(-3).join(".");
  }
  return parts.slice(-2).join(".");
}

async function getAllCookiesForDomain(host) {
  // chrome.cookies.getAll com domain= pega TODOS (incluindo httpOnly).
  // Pega cookies para o host exato e todos os parentes
  return new Promise((res) => {
    const allCookies = [];
    const seen = new Set();

    // Lista de dominios a buscar: exato, .host, dominio raiz, .dominio raiz
    const root = getRegistrableDomain(host);
    const domains = [host, "." + host, root, "." + root, "gov.br", ".gov.br"];

    let pending = domains.length;
    for (const d of domains) {
      chrome.cookies.getAll({ domain: d }, (cookies) => {
        if (cookies) {
          for (const c of cookies) {
            const key = `${c.domain}|${c.name}|${c.path}`;
            if (!seen.has(key)) {
              seen.add(key);
              allCookies.push(c);
            }
          }
        }
        pending--;
        if (pending === 0) res(allCookies);
      });
    }
  });
}

function formatCookieHeader(cookies) {
  // Formato Cookie: name=value; name2=value2
  return cookies.map((c) => `${c.name}=${c.value}`).join("; ");
}

async function capture() {
  const cfg = await getConfig();
  if (!cfg.token) {
    showStatus("Configure o token PACTA primeiro", "error");
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
    showStatus("Nenhum cookie encontrado neste dominio", "error");
    return;
  }

  const cookieHeader = formatCookieHeader(cookies);
  const httpOnlyCount = cookies.filter((c) => c.httpOnly).length;

  showStatus(
    `Capturando ${cookies.length} cookies (${httpOnlyCount} httpOnly) e enviando...`,
    "info"
  );

  // Monta payload com metadados uteis (cookies estruturados + header simples)
  const payload = {
    automation_key: $("automation-key").value,
    municipio_id: parseInt($("municipio-id").value, 10),
    cookie: cookieHeader,
    cookies_full: cookies.map((c) => ({
      name: c.name,
      value: c.value,
      domain: c.domain,
      path: c.path,
      httpOnly: c.httpOnly,
      secure: c.secure,
      sameSite: c.sameSite,
      expirationDate: c.expirationDate,
    })),
    url_atual: tab.url,
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
    if (res.status === 401) {
      showStatus("Token PACTA invalido/expirado. Reconfigure.", "error");
      return;
    }
    if (!res.ok) {
      const txt = await res.text();
      showStatus(`Erro ${res.status}: ${txt.slice(0, 100)}`, "error");
      return;
    }
    const data = await res.json();
    showStatus(
      `OK! ${cookies.length} cookies enviados (${httpOnlyCount} httpOnly). ID=${data.id}`,
      "success"
    );
  } catch (e) {
    showStatus(`Erro de rede: ${e.message}`, "error");
  }
}

async function init() {
  const cfg = await getConfig();
  const tab = await getCurrentTab();
  const host = getDomainFromUrl(tab.url);

  $("domain-info").innerHTML = host
    ? `<strong>Dominio atual:</strong> ${host}`
    : "Nenhum dominio detectado";

  // Auto-detect automation_key baseado no dominio
  if (host) {
    if (host.includes("consultafns")) $("automation-key").value = "fns";
    else if (host.includes("simec")) $("automation-key").value = "simec";
    else if (host.includes("sismob")) $("automation-key").value = "sismob";
    else if (host.includes("estruturasuas")) $("automation-key").value = "suas";
    else if (host.includes("investsus")) $("automation-key").value = "investsus";
    else if (host.includes("gov.br")) $("automation-key").value = "govbr";
  }

  $("btn-capture").addEventListener("click", capture);
  $("btn-config").addEventListener("click", () => {
    $("main").classList.add("hidden");
    $("config").classList.remove("hidden");
    $("cfg-api-url").value = cfg.api;
    $("cfg-token").value = cfg.token;
  });
  $("btn-save-config").addEventListener("click", async () => {
    const api = $("cfg-api-url").value.trim();
    const token = $("cfg-token").value.trim();
    if (!api || !token) {
      alert("Preencha API URL e Token");
      return;
    }
    await saveConfig(api, token);
    $("config").classList.add("hidden");
    $("main").classList.remove("hidden");
    showStatus("Configuracao salva", "success");
  });
  $("btn-cancel-config").addEventListener("click", () => {
    $("config").classList.add("hidden");
    $("main").classList.remove("hidden");
  });
  $("open-pacta").addEventListener("click", () => {
    chrome.tabs.create({ url: "https://pacta-production.up.railway.app/dashboard" });
  });

  if (!cfg.token) {
    showStatus("Clique em 'Configurar token PACTA' antes de capturar", "info");
  }
}

init();
