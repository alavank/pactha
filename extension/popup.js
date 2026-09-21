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

/* `saveConfig` FOI REMOVIDA. Ela gravava o par `pactha_api`/`pactha_token`, que
 * a lista de ambientes substituiu, e ficou sem nenhum chamador — funcao morta
 * que ainda escrevia a chave da qual o resto do codigo dependia por engano.
 * `lerAmbientes()` continua LENDO `pactha_token` uma unica vez, para migrar o
 * token de quem ja usava a versao antiga; ver `ambientes.js`. */

/** Desenha um campo de token por AMBIENTE.
 *
 * ⚠️ UM TOKEN POR AMBIENTE, e nao um so: os service tokens vivem no banco de
 * cada tenant, entao nao existe chave que sirva para os cinco. Era isso que
 * tornava a configuracao um ritual de cinco passos — a lista nao remove o
 * trabalho de colar cinco chaves, mas o transforma em UMA tela, feita uma vez,
 * em vez de cinco reconfiguracoes toda vez que a sessao cai.
 */
async function desenharAmbientes() {
  const lista = await lerAmbientes();
  const box = $("cfg-ambientes");
  if (!box) return;
  box.innerHTML = "";
  lista.forEach((amb, i) => {
    const linha = document.createElement("div");
    linha.className = "amb-linha";
    const rot = document.createElement("label");
    rot.textContent = amb.nome;
    const inp = document.createElement("input");
    inp.type = "password";
    inp.placeholder = "pactha_st_…";
    inp.value = amb.token || "";
    inp.dataset.idx = String(i);
    inp.className = "amb-token";
    // O ambiente sem token fica marcado: e a diferenca entre "nao configurei"
    // e "configurei e falhou", e as duas pedem acoes diferentes.
    if (!amb.token) rot.textContent += "  (sem token)";
    linha.appendChild(rot);
    linha.appendChild(inp);
    box.appendChild(linha);
  });
}

async function salvarTokensDaTela() {
  const lista = await lerAmbientes();
  document.querySelectorAll(".amb-token").forEach((inp) => {
    const i = parseInt(inp.dataset.idx, 10);
    if (lista[i]) lista[i].token = inp.value.trim();
  });
  await salvarAmbientes(lista);
  return lista;
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
  /* ⚠️ O PORTEIRO OLHA A LISTA, e não o `pactha_token` antigo. Depois da
     migração para multi-ambiente o token único fica VAZIO — quem continuasse
     barrando por ele recusaria a captura com "configure o token primeiro"
     mesmo com os cinco ambientes preenchidos, e a mensagem mandaria a pessoa
     configurar o que já estava configurado. */
  const ambientes = await lerAmbientes();
  const comToken = ambientes.filter((a) => a.token && a.ativo !== false);
  if (!comToken.length) {
    showStatus("Nenhum ambiente com token. Abra «Configurar ambientes».", "error");
    return;
  }
  const tab = await getCurrentTab();
  const host = getDomainFromUrl(tab.url);
  if (!host) {
    showStatus("Aba atual sem URL valida", "error");
    return;
  }
  // O mesmo PORTEIRO da captura automática (`chromeEstaLogado`, ambientes.js):
  // jar `govbr` deslogado não sai nem no clique manual — a mensagem diz o que fazer.
  if ($("automation-key").value === "govbr" && (await chromeEstaLogado()) === false) {
    showStatus("Este Chrome NÃO está logado no TransfereGov — nada foi enviado. "
      + "Use «Captura completa» (ela espera você logar).", "error");
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
    // ⚠️ TODOS OS AMBIENTES, e a lista de resultados aparece NOMEADA. O defeito
    // que isto conserta e o sucesso parcial invisivel — ver `ambientes.js`.
    const lista = await lerAmbientes();
    const resultados = await enviarParaTodos(payload, lista);
    if (!resultados.length) {
      showStatus("Nenhum ambiente configurado. Abra «Configurar ambientes».", "error");
      return;
    }
    const ruins = resultados.filter((r) => !r.ok);
    const linhas = resultados
      .map((r) => `${r.ok ? "OK" : "FALHOU"} ${r.nome}${r.ok ? "" : " — " + r.detalhe}`)
      .join("\n");
    showStatus(
      `${cookies.length} cookies (${httpOnly} httpOnly) para ${resumoEnvio(resultados)}\n${linhas}`,
      ruins.length ? (ruins.length === resultados.length ? "error" : "info") : "success"
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

  /* ⚠️ O FORMATO MUDOU E O LEITOR NAO TINHA ACOMPANHADO. A auto-captura passou
     a gravar `{quando, cookies, ambientes_ok, ambientes_total, falhas}` e esta
     funcao ainda lia `{at, n, ok}` — o card mostraria "undefined cookies" e
     "NaNs atras", e as `falhas` (que a mudanca grava DE PROPOSITO, nomeadas)
     nunca chegariam a tela. Dado gravado que ninguem le nao muda nada: e o
     mesmo defeito de "coluna cheia sem consumidor" que este projeto ja teve.
     Aceita os DOIS formatos porque o storage pode ter uma captura antiga
     gravada antes desta versao. */
  const quando = lc.quando ? Date.parse(lc.quando) : lc.at;
  const nCookies = lc.cookies != null ? lc.cookies : lc.n;
  const houveFalha = lc.ok === false;

  if (houveFalha) {
    el.innerHTML = `✗ Última falhou: ${lc.host} · ${lc.error || "erro"} · ${fmtTimeAgo(quando)}`;
    el.className = "info";
    return;
  }

  const falhas = Array.isArray(lc.falhas) ? lc.falhas : [];
  const alcance = lc.ambientes_total
    ? `${lc.ambientes_ok} de ${lc.ambientes_total} ambiente(s)`
    : "";

  /* ⚠️ ZERO AMBIENTES NÃO É "✓". Antes, uma captura que falhou nos CINCO
     desenhava o mesmo cartão de sucesso — o `✓` é escrito logo abaixo sem olhar
     `ambientes_ok`, e `lc.ok === false` só cobre o erro de rede, que nunca
     ocorre porque `enviarParaTodos` trata cada alvo no seu próprio try.
     Combinado com o `if (bons.length)` que havia no background (e que também
     saiu), a falha total era duplamente invisível: não gravava, e se gravasse
     desenhava verde. */
  if (lc.ambientes_total && !lc.ambientes_ok) {
    el.innerHTML =
      `✗ Última NÃO gravou em nenhum ambiente · ${lc.host} · ${fmtTimeAgo(quando)}`
      + (falhas.length ? `<br><span style="opacity:.85">${falhas.join(" · ")}</span>` : "");
    el.className = "info";
    return;
  }

  el.innerHTML =
    `${falhas.length ? "⚠" : "✓"} Última: <strong>${lc.host}</strong> · ${nCookies} cookies`
    + (lc.httpOnly != null ? ` (${lc.httpOnly} httpOnly)` : "")
    + (alcance ? ` · ${alcance}` : "")
    + ` · ${fmtTimeAgo(quando)}`
    // ⚠️ AS FALHAS APARECEM NOMEADAS. "4 de 5" sozinho e um numero sem acao:
    // quem le nao sabe QUAL refazer.
    + (falhas.length
      ? `<br><span style="opacity:.85">falhou em: ${falhas.join(" · ")}</span>`
      : "");
  el.className = "info";
}

/* A SAÚDE DA SESSÃO NOS SERVIDORES. Consulta ao abrir o popup (não espera o
   alarme de 12 min) e desenha uma linha por ambiente. ⚠️ `textContent`, nunca
   `innerHTML`: os textos vêm do servidor. */
function textoDoItem(i) {
  if (!i.ok) return `${i.nome}: sem resposta (${i.detalhe})`;
  if (i.precisa_recapturar) {
    return `${i.nome}: LOGIN CAIU${i.modulos ? " · " + i.modulos : ""} — recapturar`;
  }
  if (i.login === "vivo") {
    return `${i.nome}: vivo`
      + (i.medido_ha_min != null ? ` (medido há ${i.medido_ha_min} min)` : "")
      + (i.modulos && i.modulos.includes("CAIU") ? ` · ${i.modulos}` : "")
      + (i.candidata_pendente ? " · captura em teste" : "");
  }
  return `${i.nome}: ainda sem medição do servidor`;
}

async function desenharSaude() {
  const card = $("saude-card");
  const info = $("saude-info");
  if (!card || !info) return;
  let itens = [];
  try {
    itens = await consultarSaude(await lerAmbientes());
    chrome.storage.local.set({ pactha_saude: { quando: new Date().toISOString(), itens } });
  } catch (_) { /* fica com o que houver no storage */ }
  if (!itens.length) {
    const guardado = await new Promise((r) => chrome.storage.local.get(["pactha_saude"], (d) => r(d.pactha_saude)));
    itens = (guardado && guardado.itens) || [];
  }
  info.textContent = "";
  if (!itens.length) {
    info.textContent = "Nenhum ambiente com token para consultar.";
    return;
  }
  itens.forEach((i) => {
    const linha = document.createElement("div");
    linha.className = "linha";
    linha.textContent = textoDoItem(i);
    info.appendChild(linha);
  });
  const caiu = algumPrecisaRecapturar(itens);
  const respondeu = itens.filter((i) => i.ok);
  const todasVivas = respondeu.length > 0 && respondeu.every((i) => i.login === "vivo");
  card.classList.toggle("caiu", caiu);
  card.classList.toggle("viva", !caiu && todasVivas);
  $("saude-titulo").textContent = caiu
    ? "⚠ A sessão gov.br CAIU nos servidores — recapture"
    : (todasVivas ? "✓ Sessão gov.br viva nos servidores" : "Sessão gov.br nos servidores");
}

function desenharPortas() {
  const box = $("portas-lista");
  if (!box) return;
  box.textContent = "";
  PORTAS_GOVBR.forEach((p) => {
    const a = document.createElement("a");
    a.className = "porta-link";
    a.textContent = p.nome;
    a.addEventListener("click", () => chrome.tabs.create({ url: p.url }));
    box.appendChild(a);
  });
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
  /* ⚠️ MOSTRA QUANTOS AMBIENTES A CAPTURA ALCANÇA, e nomeia os que ficam de
     fora. A versão anterior exibia UMA API — o que, num mundo de cinco
     tenants, é a informação errada: dizia "API: freitas" e a pessoa concluía,
     corretamente para aquela tela e erradamente para o produto, que a captura
     estava resolvida. */
  const ambs = await lerAmbientes();
  const prontos = ambs.filter((a) => a.token && a.ativo !== false);
  const faltando = ambs.filter((a) => !a.token).map((a) => a.nome);
  /* ⚠️ "CONFIGURADOS", E NÃO "CAPTURA EM". Esta linha conta token PREENCHIDO,
     não token que funciona — ela não valida nada. A frase anterior era "Captura
     em 5 de 5 ambiente(s)", que com uma chave inválida afirmava exatamente o
     contrário do que estava acontecendo. Quem responde "funcionou?" é o cartão
     da última captura, logo abaixo; esta linha responde só "está preenchido?". */
  $("api-info").textContent =
    `${prontos.length} de ${ambs.length} ambiente(s) configurado(s)`
    + (faltando.length ? ` · sem token: ${faltando.join(", ")}` : "");

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

  // Captura completa: quem conduz é o service worker (o popup FECHA quando a aba
  // nova ganha o foco, e o roteiro morreria junto).
  $("btn-completa").addEventListener("click", () => {
    chrome.runtime.sendMessage({ tipo: "captura_completa" });
    showStatus("Abrindo as 4 portas na mesma aba. Se pedir login, faça — o roteiro "
               + "continua sozinho depois.", "info");
  });
  desenharPortas();
  desenharSaude();

  $("btn-config").addEventListener("click", async () => {
    $("main").classList.add("hidden");
    $("config").classList.remove("hidden");
    await desenharAmbientes();
  });
  $("btn-save-config").addEventListener("click", async () => {
    const lista = await salvarTokensDaTela();
    const semToken = lista.filter((a) => !a.token).map((a) => a.nome);
    $("config").classList.add("hidden");
    $("main").classList.remove("hidden");
    // ⚠️ `refreshLastCapture`, e nao `refresh` — esta funcao NAO EXISTE. A
    // chamada errada levantava ReferenceError DEPOIS de trocar as telas e
    // ANTES do aviso abaixo, entao o "SEM TOKEN ainda: …" que eu acrescentei
    // de proposito nunca chegava a aparecer.
    await refreshLastCapture();
    // ⚠️ AVISA QUEM FICOU DE FORA, na hora de salvar. Sem isto a pessoa fecha a
    // tela achando que configurou tudo, e so descobre o ambiente faltando na
    // proxima vez que a sessao cair — que foi exatamente o que aconteceu com o
    // santamaria e o novapalma.
    showStatus(
      semToken.length
        ? `Salvo. SEM TOKEN ainda: ${semToken.join(", ")} — a captura nao alcanca esses.`
        : "Salvo. Os cinco ambientes tem token.",
      semToken.length ? "info" : "success"
    );
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

  /* ⚠️ AVISA PELA LISTA, e nomeia quem falta. A versao anterior olhava o
     `pactha_token` unico e dizia "Configure o token PACTHA" — uma frase que
     contradizia o "Captura em 5 de 5" logo acima e apontava para um campo que
     nao existe mais na tela. */
  const semToken = (await lerAmbientes()).filter((a) => !a.token).map((a) => a.nome);
  if (semToken.length) {
    showStatus(`Sem token em: ${semToken.join(", ")} — a captura nao alcanca esses.`,
               "info");
  }

  refreshLastCapture();
  // Atualiza relógio do "última captura" a cada segundo
  setInterval(refreshLastCapture, 2000);
}

init();
