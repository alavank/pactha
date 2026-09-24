/* Testes da extensão de captura. Rode com:  node extension/testar.js
 * Opcionalmente contra a pasta INSTALADA:   node extension/testar.js "C:\\caminho\\extension"
 *
 * ⚠️ POR QUE ESTE ARQUIVO EXISTE. Os dois defeitos que ele trava eram INVISÍVEIS
 * por construção — nenhum dos dois gerava erro em lugar nenhum:
 *
 *   1. `background.js` só gravava o status `if (bons.length)`. Falha em TODOS os
 *      ambientes não gravava nada, então o popup seguia exibindo o cartão verde
 *      da última captura que funcionou. O `catch` que salvaria o caso era código
 *      inalcançável, porque `enviarParaTodos` nunca rejeita.
 *   2. `lerAmbientes()` devolvia a lista salva sem reconciliar com
 *      `AMBIENTES_CONHECIDOS`. Acrescentar um tenant novo ao código não surtia
 *      efeito nenhum em quem já usava a extensão — o sexto cliente nasceria fora
 *      da captura como santamaria e novapalma nasceram.
 *
 * Não há suíte de testes de frontend neste repo (ver CLAUDE.md); por isso um
 * script node avulso, sem dependência nenhuma.
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const DIR = process.argv[2] || __dirname;
const ler = (f) => fs.readFileSync(path.join(DIR, f), "utf8");
const TEM_TOKENS = fs.existsSync(path.join(DIR, "tokens.local.js"));

function montar(storageInicial) {
  const store = { ...storageInicial };
  const ctx = {
    console,
    chrome: {
      storage: {
        local: {
          get: (chaves, cb) => {
            const out = {};
            (Array.isArray(chaves) ? chaves : [chaves]).forEach((k) => {
              if (k in store) out[k] = store[k];
            });
            cb(out);
          },
          set: (obj, cb) => { Object.assign(store, obj); if (cb) cb(); },
        },
      },
    },
  };
  ctx.self = ctx;
  vm.createContext(ctx);
  if (TEM_TOKENS) vm.runInContext(ler("tokens.local.js"), ctx);
  /* ⚠️ `AMBIENTES_CONHECIDOS` é `const`, e `const` NÃO vira propriedade do
     contexto do vm — fica no escopo léxico do script. Sem a linha extra,
     `ctx.AMBIENTES_CONHECIDOS` é undefined e o teste do sexto tenant morre no
     arreio em vez de testar o produto. (`lerAmbientes` aparece porque declaração
     de FUNÇÃO vira global; `const` não.) */
  vm.runInContext(ler("ambientes.js") + "\n;self.__CONHECIDOS = AMBIENTES_CONHECIDOS;", ctx);
  return { ctx, store };
}

let falhas = 0;
const chk = (cond, msg) => {
  console.log(`  ${cond ? "ok  " : "FALHA"} ${msg}`);
  if (!cond) falhas++;
};

/* O CHROME FALSO: roda o background.js INTEIRO com abas, eventos, alarme, selo e
   storage simulados. `cenario(url, aba)` diz onde cada navegação vai parar:
   `{ url, titulo, carregando, semEvento, pendenteMs }`. `opcoes.sonda(url)` é o HTML
   que a sonda do porteiro recebe (default: página logada). */
function montarBg(cenario, inicial, opcoes) {
  const store = { pactha_ambientes: [{ nome: "A", api: "https://a.sslip.io/api", token: "pactha_st_a", ativo: true }],
    ...(inicial || {}) };
  const ouvintes = { nav: [], alarme: [], msg: [] };
  const abas = new Map();
  const posts = [];
  const alarmes = new Set();
  const navegacoes = [];                     // toda URL mandada a uma aba por tabs.update
  const removidos = [];                      // cookies apagados (chrome.cookies.remove)
  let sessaoDiscr = true;                    // o JSESSIONID do discricionarias existe
  const selo = { texto: "", titulo: "" };
  let proxId = 100;
  const ecoa = (v, cb) => { if (cb) cb(v); return Promise.resolve(v); };
  const nada = () => {};
  const navegar = (aba, url) => {
    const plano = cenario(url, aba) || {};
    const commit = () => {
      delete aba.pendingUrl;
      aba.url = plano.url || url;
      aba.title = plano.titulo != null ? plano.titulo : "Transferegov";
      (aba.visitas = aba.visitas || []).push(aba.url);
      if (!plano.carregando) aba.status = "complete";
      if (!plano.semEvento) ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: aba.url, frameId: 0 }));
    };
    const comecar = () => {
      aba.status = "loading";
      aba.pendingUrl = url;                  // como no Chrome: a URL velha fica até o commit
      setTimeout(commit, plano.pendenteMs || 1);
    };
    // `inicioMs`: a navegação pedida demora a APARECER na aba (sem pendingUrl, a
    // página velha "complete") — a janela em que um sinal velho parece a página nova.
    if (plano.inicioMs) setTimeout(comecar, plano.inicioMs); else comecar();
  };
  const chromeFalso = {
    storage: { local: {
      get: (k, cb) => { const o = {}; (Array.isArray(k) ? k : [k]).forEach((x) => { if (x in store) o[x] = store[x]; }); return ecoa(o, cb); },
      set: (o, cb) => { Object.assign(store, o); return ecoa(undefined, cb); },
      remove: (k, cb) => { (Array.isArray(k) ? k : [k]).forEach((x) => delete store[x]); return ecoa(undefined, cb); },
    }, onChanged: { addListener: nada } },
    tabs: {
      create: (o, cb) => { const aba = { id: proxId++, url: o.url, status: "complete" }; abas.set(aba.id, aba); if (cb) cb(aba); },
      get: (id) => abas.has(id) ? Promise.resolve({ ...abas.get(id) }) : Promise.reject(new Error("No tab with id")),
      update: (id, o) => {
        const aba = abas.get(id);
        if (aba && aba.recusa) { aba.recusa--; return Promise.reject(new Error("Tabs cannot be edited right now")); }
        if (o && o.url) navegacoes.push(o.url);
        if (aba && o.url) navegar(aba, o.url);
        return Promise.resolve(aba);
      },
    },
    alarms: { create: (n) => alarmes.add(n), clear: (n) => alarmes.delete(n),
      get: (n) => Promise.resolve(alarmes.has(n) ? { name: n } : undefined),
      onAlarm: { addListener: (f) => ouvintes.alarme.push(f) } },
    webNavigation: { onCompleted: { addListener: (f) => ouvintes.nav.push(f) } },
    cookies: { onChanged: { addListener: nada },
      getAll: (q, cb) => {
        if (q.domain === "idp.transferegov.sistema.gov.br") {
          return cb([{ name: "JSESSIONID", value: "i1", domain: "idp.transferegov.sistema.gov.br", path: "/", httpOnly: true }]);
        }
        if (q.domain === "consultafns.saude.gov.br") {     // o FNS do keepalive de 12 min
          return cb([{ name: "JSESSIONID", value: "f1", domain: "consultafns.saude.gov.br", path: "/", httpOnly: true }]);
        }
        // a sessão do discricionarias (a de VISITANTE, quando é o caso), que a saída apaga
        if (q.domain === "discricionarias.transferegov.sistema.gov.br" && q.name === "JSESSIONID") {
          return cb(sessaoDiscr ? [{ name: "JSESSIONID", value: "d1", storeId: "0", path: "/voluntarias",
            domain: "discricionarias.transferegov.sistema.gov.br" }] : []);
        }
        return cb([]);
      },
      remove: (d, cb) => {
        removidos.push(d);
        if (d.name === "JSESSIONID" && /^https:\/\/discricionarias\.transferegov\.sistema\.gov\.br\//.test(d.url)) {
          sessaoDiscr = false;
          if (opcoes && opcoes.aoApagarVisitante) opcoes.aoApagarVisitante();
        }
        if (cb) cb({ url: d.url, name: d.name, storeId: d.storeId });
      } },
    runtime: { onInstalled: { addListener: nada }, onStartup: { addListener: nada },
      onMessage: { addListener: (f) => ouvintes.msg.push(f) } },
    action: { setBadgeText: (o) => { selo.texto = o.text; }, setBadgeBackgroundColor: nada,
      setTitle: (o) => { selo.titulo = o.title; } },
  };
  const ctx = {
    console: { log: nada, warn: nada, error: nada },
    chrome: chromeFalso, navigator: { userAgent: "teste" }, URL, Date, JSON, Promise, Set, Map,
    setTimeout: (f) => setTimeout(f, 1),       // o tempo corre depressa aqui
    fetch: async (url, opt) => {
      if (opt && opt.method === "POST") { posts.push(JSON.parse(opt.body)); return { ok: true, status: 200, json: async () => ({ id: 1 }) }; }
      if (String(url).includes("/session-capture/saude")) return { ok: true, status: 200, json: async () => ({}) };
      // `sondaMs`: a sonda leva tempo de REDE de verdade (no Chrome ela é um fetch):
      // é o que deixa dois sinais passarem juntos pela conferência da página.
      if (opcoes && opcoes.sondaMs) await new Promise((r) => setTimeout(r, opcoes.sondaMs));
      const html = opcoes && opcoes.sonda ? opcoes.sonda(url) : "<a>Sair</a> Consultar Proposta";
      return { ok: true, status: 200, url, text: async () => html };
    },
  };
  ctx.self = ctx;
  ctx.importScripts = (f) => { if (f === "tokens.local.js") throw new Error("ausente"); vm.runInContext(ler(f), ctx); };
  vm.createContext(ctx);
  vm.runInContext(ler("background.js"), ctx);
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  return { ctx, store, abas, posts, alarmes, ouvintes, navegacoes, removidos, selo, esperar,
    clicar: () => ouvintes.msg.forEach((f) => f({ tipo: "captura_completa" }, {}, nada)),
    tick: async () => { for (const f of ouvintes.alarme) f({ name: "pactha_roteiro_tick" }); await esperar(80); } };
}
const PORTA = (n) => vm.runInContext(`PORTAS_GOVBR[${n}].url`, montarBg(() => ({})).ctx);
// Só as capturas DO ROTEIRO (o modo automático também captura a cada navegação).
const govbrPosts = (bg) => bg.posts.filter((p) => p.automation_key === "govbr"
  && /captura_completa/.test(String(p.url_atual || "")));

/* O ACESSO LIVRE como medido no Chrome do dono em 24/09/2026 (título, o span.exit
   do <div id="info"> e o link do LLO são os literais medidos; o resto é enchimento). */
const HTML_VISITANTE = '<html><head><title>Transferegov - Consultar Proposta - Acesso Livre</title></head><body>'
  + '<div id="info"><a href="/voluntarias?LLO=true"><span class="exit">Sair do Acesso Livre '
  + '<input type="button" class="bt_exit" value=""></span></a></div><h1>Consultar Proposta</h1></body></html>';
/* A página LOGADA NÃO foi medida: hipótese (título sem "Acesso Livre", span.exit só
   "Sair"). O "Acesso Livre" solto no menu é o que o keepalive do servidor anotou
   ("aparece no header MESMO logado"). */
const HTML_LOGADA = '<html><head><title>Transferegov - Consultar Proposta</title></head><body>'
  + '<div id="info"><a href="/voluntarias/Logout.do"><span class="exit">Sair <input type="button" class="bt_exit" value="">'
  + '</span></a></div><ul class="menu"><li><a href="https://www.gov.br/transferegov/pt-br/sistemas/acesso-livre">Acesso Livre</a></li></ul>'
  + '<h1>Consultar Proposta</h1></body></html>';
const MURO_REAL = '<HTML><HEAD><TITLE>HTTP Post Binding (Request)</TITLE></HEAD><BODY Onload="document.forms[0].submit()">'
  + '<FORM METHOD="POST" ACTION="https://idp.transferegov.sistema.gov.br/idp/"><INPUT TYPE="HIDDEN" NAME="SAMLRequest" VALUE="..."/>'
  + '<NOSCRIPT><P>JavaScript is disabled.</P><INPUT TYPE="SUBMIT" VALUE="CONTINUE" /></NOSCRIPT></FORM></BODY></HTML>';
const URL_VISITANTE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/proposta/ConsultarProposta/ConsultarProposta.do";
const URL_IDP = "https://idp.transferegov.sistema.gov.br/idp/";
const URL_IDP_COM_CONTEXTO = "https://idp.transferegov.sistema.gov.br/idp/profile/SAML2/POST/SSO?execution=e1s1";
const TIT_LIVRE = "Transferegov - Consultar Proposta - Acesso Livre";
const TIT_LOGIN = "Login do Transferegov";
const TIT_LOGADA = "Transferegov - Consultar Proposta";

(async () => {
  console.log(`pasta: ${DIR}${TEM_TOKENS ? "  (com tokens.local.js)" : "  (sem tokens pré-configurados)"}`);

  console.log("\n1) lista base");
  {
    const { ctx } = montar({});
    const lista = await ctx.lerAmbientes();
    chk(lista.length >= 5, `${lista.length} ambientes (esperado >= 5)`);
    chk(lista.every((a) => /^https:\/\//.test(a.api)), "toda api é https");
    if (TEM_TOKENS) {
      // Só os NOMES dos que ficaram sem token do arquivo (nunca o valor): um tenant
      // novo cujo token foi colado no popup (Juranda, 23/09/2026) aparece aqui.
      const semArquivo = lista.filter((a) => !(a.token && a.token.startsWith("pactha_st_"))).map((a) => a.nome);
      chk(!semArquivo.length, "todos saem com service token do tokens.local.js"
        + (semArquivo.length ? ` — SEM: ${semArquivo.join(", ")} (token só no popup, ou a chave do mapa não bate com a api)` : ""));
    }
  }

  console.log("\n2) migração do formato antigo não perde o token que já funcionava");
  {
    const { ctx } = montar({
      pactha_api: "https://pactha-api-54-232-208-118.sslip.io/api",
      pactha_token: "pactha_st_TOKEN_ANTIGO_QUE_NAO_PODE_SUMIR_0001",
    });
    const lista = await ctx.lerAmbientes();
    const fr = lista.find((a) => /pactha-api-/.test(a.api));
    chk(!!fr && !!fr.token, "o ambiente da api antiga sai com token");
    if (!TEM_TOKENS) {
      chk(fr.token === "pactha_st_TOKEN_ANTIGO_QUE_NAO_PODE_SUMIR_0001",
        "sem arquivo local, o token migrado é exatamente o antigo");
    }
  }

  console.log("\n3) tenant novo aparece mesmo com lista antiga salva");
  {
    const { ctx } = montar({
      pactha_ambientes: [{
        nome: "Freitas",
        api: "https://pactha-api-54-232-208-118.sslip.io/api",
        token: "pactha_st_SALVO_PELO_OPERADOR_0002",
        ativo: true,
      }],
    });
    ctx.__CONHECIDOS.push({ nome: "Sexto - XX", api: "https://pactha-sexto.sslip.io/api" });
    const lista = await ctx.lerAmbientes();
    chk(lista.some((a) => a.nome === "Sexto - XX"),
      "o sexto ambiente aparece (era o defeito: não aparecia nunca)");
    const fr = lista.find((a) => a.nome === "Freitas");
    chk(fr && fr.token === "pactha_st_SALVO_PELO_OPERADOR_0002",
      "o que o operador salvou tem precedência sobre o arquivo local");
    const dups = lista.filter((a, i) => lista.findIndex((b) => b.api === a.api) !== i);
    chk(dups.length === 0, "sem entradas duplicadas");
  }

  console.log("\n4) ambiente desativado pelo operador continua desativado");
  {
    const { ctx } = montar({
      pactha_ambientes: [{
        nome: "Trust",
        api: "https://pactha-trust-api-54-232-208-118.sslip.io/api",
        token: "x", ativo: false,
      }],
    });
    const lista = await ctx.lerAmbientes();
    const t = lista.find((a) => /trust/.test(a.api));
    chk(t && t.ativo === false, "a escolha de desativar sobrevive à reconciliação");
  }

  console.log("\n5) o status é gravado MESMO quando nenhum ambiente aceita");
  {
    /* Lê o fonte porque o `if` removido era o defeito: um teste que só chama a
       função não distingue "gravou 0 de 5" de "não gravou nada". */
    const bg = ler("background.js");
    chk(!/if\s*\(\s*bons\.length\s*\)\s*\{[\s\S]{0,80}chrome\.storage\.local\.set/.test(bg),
      "não há mais portão `if (bons.length)` em volta do set de status");
    chk(/ambientes_ok:\s*bons\.length/.test(bg), "o status carrega quantos deram certo");
  }

  console.log("\n6) o popup não desenha ✓ para uma captura que não gravou em lugar nenhum");
  {
    const pj = ler("popup.js");
    chk(/ambientes_total\s*&&\s*!\s*lc\.ambientes_ok/.test(pj),
      "há ramo explícito para zero ambientes gravados");
    chk(!/`✓ Última: <strong>/.test(pj) || /falhas\.length\s*\?\s*"⚠"\s*:\s*"✓"/.test(pj),
      "o ✓ só aparece quando não houve falha");
  }

  console.log("\n7) a tela de LOGIN não conta como sessão viva, e o selo só acende com medição");
  {
    const { ctx } = montar({});
    chk(ctx.pareceLogin("https://sso.acesso.gov.br/login?client_id=x") === true, "sso.acesso é login");
    chk(ctx.pareceLogin("https://idp.transferegov.sistema.gov.br/idp/profile/SAML2") === true, "/idp/ é login");
    chk(ctx.pareceLogin("https://discricionarias.transferegov.sistema.gov.br/voluntarias/") === false,
      "o TransfereGov autenticado não é login");
    chk(ctx.algumPrecisaRecapturar([{ ok: true, precisa_recapturar: true }]) === true, "medição de queda acende");
    chk(ctx.algumPrecisaRecapturar([{ ok: false, detalhe: "HTTP 404" }, { ok: true, precisa_recapturar: false }]) === false,
      "falha de rede / servidor sem a rota NÃO acende o selo");
    chk(vm.runInContext("PORTAS_GOVBR.length", ctx) === 4, "a captura completa tem as 4 portas");
  }

  console.log("\n8) a saúde é consultada em CADA ambiente com token, e nunca rejeita");
  {
    const { ctx } = montar({
      pactha_ambientes: [
        { nome: "A", api: "https://a.sslip.io/api", token: "pactha_st_a", ativo: true },
        { nome: "B", api: "https://b.sslip.io/api", token: "pactha_st_b", ativo: true },
        { nome: "SemToken", api: "https://c.sslip.io/api", token: "", ativo: true },
      ],
    });
    const chamadas = [];
    ctx.fetch = async (url, opt) => {
      chamadas.push([url, opt && opt.headers]);
      if (url.startsWith("https://b.")) throw new Error("Failed to fetch");
      return { ok: true, status: 200, json: async () => ({ login: "caiu", precisa_recapturar: true, modulos: "private=CAIU" }) };
    };
    const itens = await ctx.consultarSaude([
      { nome: "A", api: "https://a.sslip.io/api", token: "pactha_st_a", ativo: true },
      { nome: "B", api: "https://b.sslip.io/api", token: "pactha_st_b", ativo: true },
      { nome: "SemToken", api: "https://c.sslip.io/api", token: "", ativo: true },
    ]);
    chk(itens.length === 2, "ambiente sem token não é consultado");
    chk(chamadas[0][0] === "https://a.sslip.io/api/session-capture/saude", "rota /session-capture/saude");
    chk(chamadas[0][1]["X-Service-Token"] === "pactha_st_a", "vai com o service token do ambiente");
    chk(itens[0].ok && itens[0].precisa_recapturar === true, "queda medida chega nomeada");
    chk(itens[1].ok === false, "erro de rede vira item com ok=false, não exceção");
  }

  console.log("\n9) o PORTEIRO: Chrome deslogado não manda jar — nem quando a URL parece boa");
  {
    const { ctx } = montar({});
    const URL_TG = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do";
    // O caso que a URL não pega: 200 NA MESMA URL com o form SAML de auto-envio.
    const muro = '<html><body onload="document.forms[0].submit()"><form method="post" '
      + 'action="https://idp.x/idp/profile/SAML2/POST/SSO"><input type="hidden" name="SAMLRequest" value="abc"/></form>';
    chk(ctx.vereditoLogin(URL_TG, muro) === false, "página SAML de auto-envio na URL do TransfereGov = deslogado");
    chk(ctx.vereditoLogin("https://sso.acesso.gov.br/login", "<html>") === false, "tela de login = deslogado");
    chk(ctx.vereditoLogin(URL_TG, "<a href='/logout'>Sair</a> Consultar Proposta") === true, "página com «Sair» = logado");
    chk(ctx.vereditoLogin(URL_TG, "<html>erro 500</html>") === null, "sem prova para nenhum lado = não sei (null)");
    // O muro REAL, medido em 23/09/2026 (3.469 bytes; só o valor do SAMLRequest foi cortado).
    const muroReal = '<HTML><HEAD><TITLE>HTTP Post Binding (Request)</TITLE></HEAD><BODY Onload="document.forms[0].submit()">'
      + '<FORM METHOD="POST" ACTION="https://idp.transferegov.sistema.gov.br/idp/"><INPUT TYPE="HIDDEN" NAME="SAMLRequest" VALUE="..."/>'
      + '<NOSCRIPT><P>JavaScript is disabled.</P><INPUT TYPE="SUBMIT" VALUE="CONTINUE" /></NOSCRIPT></FORM></BODY></HTML>';
    chk(ctx.vereditoLogin(URL_TG, muroReal) === false, "o muro REAL (maiúsculas, TITLE + FORM p/ idp + INPUT SAMLRequest) = deslogado");
    // ⚠️ Página LOGADA com as palavras do muro ESCONDIDAS no HTML cru: o link
    // "Sair" do SAML leva `SAMLRequest=` na URL e o menu tem "Acesso Restrito"
    // oculto. A versão anterior barrava isto — e a captura boa nunca saía.
    const logadaComPalavras = '<html><body><ul style="display:none"><li>Acesso Restrito</li></ul>'
      + '<a href="/idp/profile/SAML2/Redirect/SLO?SAMLRequest=abc&RelayState=x">Sair</a>'
      + '<script>var RelayState = "SAMLRequest";</script><h1>Consultar Proposta</h1></body></html>';
    chk(ctx.vereditoLogin(URL_TG, logadaComPalavras) === true,
      "página LOGADA com «SAMLRequest»/«Acesso Restrito» escondidos no HTML = logado (era barrada)");

    let corpo = muro;
    let sondas = 0;
    ctx.fetch = async (url) => { sondas++; return { ok: true, status: 200, url, text: async () => corpo }; };
    chk((await ctx.chromeEstaLogado()) === false, "sonda com muro SAML → false");
    corpo = "<a>Sair</a>";
    chk((await ctx.chromeEstaLogado()) === true, "o `false` NÃO fica em cache: a captura boa, 2s depois, passa");
    const antes = sondas;
    await ctx.chromeEstaLogado();
    chk(sondas === antes, "o `true` fica em cache (5s): um login dispara vários gatilhos");
    const { ctx: ctx2 } = montar({});
    ctx2.fetch = async () => { throw new Error("Failed to fetch"); };
    chk((await ctx2.chromeEstaLogado()) === null, "falha de rede = null (não barra a recaptura)");

    const bg = ler("background.js");
    const iPorteiro = bg.indexOf("await chromeEstadoLogin()");
    const iDebounce = bg.indexOf("lastCaptureAt.set(dKey, now)");
    chk(iPorteiro > 0 && iPorteiro < iDebounce,
      "em capture(), o porteiro vem ANTES de marcar o debounce (senão a página SAML engole a captura boa)");
    chk(/tab\.status\s*!==\s*"complete"/.test(bg), "o roteiro só avança com a aba `complete`");
    chk(/if\s*\(!itens\.some\(\(i\)\s*=>\s*i\.ok\)\)\s*return/.test(bg),
      "sem nenhuma resposta de servidor o selo não muda");
    chk(/await chromeEstadoLogin\(\);\s*if \(estado\.valor === false\)/.test(ler("popup.js")),
      "a captura MANUAL passa pelo mesmo porteiro");
    chk(/if\s*\(!cfg\.auto_enabled\s*&&\s*!forcar\)/.test(bg),
      "o toggle do modo AUTOMÁTICO não barra o fim da «Captura completa» (era no-op silencioso)");
    chk(!/if\s*\(!cfg\.auto_enabled\)\s*\{\s*console\.log\("\[PACTHA\] auto-captura/.test(bg),
      "não sobrou o portão antigo, que ignorava `forcar`");
  }

  console.log("\n10) o aviso ANTES de vencer: selo ⏰ só com servidor dizendo «vencendo», e «!» tem precedência");
  {
    const { ctx } = montar({});
    ctx.fetch = async () => ({ ok: true, status: 200, json: async () => ({
      login: "vivo", precisa_recapturar: false, login_em: "2026-09-23T14:27:18+00:00",
      login_ha_h: 21.6, vence_previsto_em: "2026-09-24T14:27:18+00:00", vence_em_h: 2.4, vencendo: true }) });
    const [i] = await ctx.consultarSaude([{ nome: "A", api: "https://a.sslip.io/api", token: "pactha_st_a", ativo: true }]);
    chk(i.vencendo === true && i.vence_em_h === 2.4 && i.login_em && i.vence_previsto_em, "os campos de vencimento chegam da rota /saude");
    chk(ctx.algumVencendo([i]) === true, "vencendo acende");
    chk(ctx.algumVencendo([{ ok: false, vencendo: true }]) === false, "sem resposta do servidor não acende");
    chk(/login há 22h · vence ~\d\d:\d\d \(em 2,4h\)/.test(ctx.textoVencimento(i)), "texto: «login há 22h · vence ~HH:MM (em 2,4h)»");
    const esperado = new Date(Date.parse("2026-09-24T14:27:18+00:00"));
    const hhmm = String(esperado.getHours()).padStart(2, "0") + ":" + String(esperado.getMinutes()).padStart(2, "0");
    chk(ctx.textoVencimento(i).includes("vence ~" + hhmm), "a HORA vem do servidor (vence_previsto_em), não de 24h fixas no Chrome");
    chk(ctx.textoVencimento({ ...i, vence_previsto_em: null }) === "", "sem vence_previsto_em não inventa hora");
    chk(ctx.textoVencimento({ ok: true, login: "vivo" }) === "", "servidor antigo (sem campos) não inventa hora");
    chk(/já passou do previsto/.test(ctx.textoVencimento({ ...i, vence_em_h: -2 })), "passou do previsto e ainda vivo: diz isso, não apaga");
    const bg = ler("background.js");
    chk(/caiu \? "!" : \(vencendo \? "⏰" : ""\)/.test(bg), "selo: «!» (caiu) tem precedência sobre «⏰» (vencendo)");
    chk(/\.vencendo/.test(ler("popup.html")) && /algumVencendo\(itens\)/.test(ler("popup.js")), "o popup pinta o cartão de vencendo");
  }

  console.log("\n11) o roteiro espera o login sem prazo curto: os 20 min recomeçam na tela de login");
  {
    const bg = ler("background.js");
    // Cada CARREGAMENTO da tela de login renova o prazo; o alarme de 30s não (revisão de
    // 24/09/2026: renovar no alarme fazia os 20 min nunca vencerem). Comportamento na seção 15.
    chk(/if \(pareceLogin\(details\.url\)\) \{[\s\S]{0,1200}origem === "alarme" \? \{\} : \{ em: Date\.now\(\) \}/.test(bg),
      "na tela de login cada carregamento regrava `em` (login demorado não mata o roteiro no meio)");
  }

  console.log("\n9b) VISITANTE («Acesso Livre») não é login — nem com o botão «Sair» na página");
  {
    const { ctx } = montar({});
    const URL_TG = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/proposta/ConsultarProposta/ConsultarProposta.do";
    // Como o Chrome do dono estava (título e o link do botão, medidos em 24/09/2026 — o
    // `href='#'` da versão de 23/09 era palpite; o link real é o do LLO).
    const visitante = "<title>Transferegov - Consultar Proposta - Acesso Livre</title>"
      + "<a href='/voluntarias?LLO=true'>Sair do Acesso Livre</a> Consultar Proposta";
    chk(ctx.vereditoLogin(URL_TG, visitante) === false, "página de visitante = deslogado (o jar não sai)");
    chk(ctx.vereditoLogin(URL_TG, "<a>Sair</a> Consultar Proposta") === true, "página logada continua logada");
  }

  console.log("\n11b) salvar os tokens TESTA cada um no servidor e acusa o incompleto");
  {
    const pj = ler("popup.js");
    chk(/a\.token\.length < 50/.test(pj), "token pactha_st_ curto (só o começo, da lista) é acusado como INCOMPLETO");
    chk(/btn-save-config[\s\S]{0,4000}consultarSaude\(lista\)/.test(pj), "ao salvar, cada token é testado no servidor dele");
    chk(/HTTP 40\[13\]/.test(pj), "401/403 viram «o servidor RECUSOU o token de: …»");
    // 24/09/2026: o Juranda colou o token de LOGIN DA WEB (JWT, vence em 60 min) — o
    // teste de salvar passava e, uma hora depois, "JWT inválido ou expirado".
    const m = /const deLoginWeb = (lista\.filter\([\s\S]*?\)\s*\.map\(\(a\) => a\.nome\));/.exec(pj);
    const deLoginWeb = m ? vm.runInNewContext(m[1], {
      lista: [{ nome: "Web", token: "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.x" },
              { nome: "Servico", token: "pactha_st_" + "x".repeat(54) },
              { nome: "Legado", token: "pacta_st_" + "y".repeat(54) },
              { nome: "Vazio", token: "" }] }) : null;
    chk(JSON.stringify(deLoginWeb) === JSON.stringify(["Web"]),
      "token que não começa com «pactha_» é acusado como LOGIN DA WEB (e só ele)");
    chk(/Token de LOGIN DA WEB em: [\s\S]{0,200}vence em 1 hora[\s\S]{0,200}SERVICE TOKEN \(começa com «pactha_st_»\)/.test(pj),
      "a mensagem diz que vence em 1 hora e aponta o SERVICE TOKEN (pactha_st_)");
  }

  console.log("\n12) o ROTEIRO da captura completa, rodando de verdade num Chrome falso");
  {
    // ⚠️ Travou em produção em 23/09/2026 ("só fica abrindo e não captura"). Estes
    // cenários rodam o background.js inteiro com abas, eventos e alarme simulados
    // (`montarBg`, no topo deste arquivo).

    // (a) caminho feliz: passa pelas 4 portas e captura
    {
      const bg = montarBg(() => ({}));
      bg.clicar(); await bg.esperar(400);
      chk(!bg.store.pactha_roteiro, "(a) roteiro terminou");
      chk(govbrPosts(bg).length >= 1, "(a) a captura foi enviada ao ambiente");
      chk(!bg.alarmes.has("pactha_roteiro_tick"), "(a) o alarme do roteiro foi desligado no fim");
    }
    // (b) o evento da porta 2 se PERDE: o alarme destrava
    {
      const bg = montarBg((url) => url === PORTA(1) ? { semEvento: true } : {});
      bg.clicar(); await bg.esperar(200);
      chk(bg.store.pactha_roteiro && bg.store.pactha_roteiro.passo === 1, "(b) parado na porta 2 sem o evento (era o travamento)");
      chk(bg.alarmes.has("pactha_roteiro_tick"), "(b) o alarme do roteiro está ligado");
      await bg.tick(); await bg.esperar(300);
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(b) o alarme fez o roteiro andar até a captura");
    }
    // (c) a aba da porta 3 nunca sai de "carregando": ~20s na mesma URL = assentada
    {
      const bg = montarBg((url) => url === PORTA(2) ? { carregando: true } : {});
      bg.clicar(); await bg.esperar(500);
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(c) recurso que nunca termina de carregar não trava mais");
    }
    // (d) cai na tela de login: ESPERA a pessoa, e segue depois do login
    {
      let logado = false;
      const bg = montarBg((url) => (url === PORTA(0) && !logado) ? { url: "https://sso.acesso.gov.br/login?client_id=x" } : {});
      bg.clicar(); await bg.esperar(200);
      chk(bg.store.pactha_roteiro && /passando pelo login/.test(bg.store.pactha_roteiro.fase), "(d) diz que está no login (e que é para logar se pedir)");
      chk(govbrPosts(bg).length === 0, "(d) nada enviado antes do login");
      logado = true;
      const aba = [...bg.abas.values()][0];
      aba.url = PORTA(0); aba.status = "complete";
      bg.ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: PORTA(0), frameId: 0 }));
      await bg.esperar(400);
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(d) depois do login o roteiro seguiu sozinho");
    }
    // (e) a aba foi fechada no meio: o alarme encerra em vez de ficar pendurado
    {
      const bg = montarBg((url) => url === PORTA(1) ? { semEvento: true } : {});
      bg.clicar(); await bg.esperar(200);
      bg.abas.clear();
      await bg.tick();
      chk(!bg.store.pactha_roteiro && !bg.alarmes.has("pactha_roteiro_tick"), "(e) aba fechada encerra o roteiro e o alarme");
      chk(govbrPosts(bg).length === 0, "(e) a captura do roteiro não sai");
    }
    // (g) porta LENTA (navegação pendente por muito tempo): não é pulada nem cortada
    {
      const bg = montarBg((url) => url === PORTA(1) ? { pendenteMs: 400 } : {});
      bg.clicar(); await bg.esperar(150);
      await bg.tick(); await bg.tick();          // o alarme cai no meio da navegação pendente
      await bg.esperar(700);
      const aba = [...bg.abas.values()][0];
      chk(JSON.stringify(aba.visitas) === JSON.stringify([PORTA(0), PORTA(1), PORTA(2), PORTA(3)]),
        "(g) porta lenta: as 4 portas, em ordem, nenhuma pulada");
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(g) e a captura saiu no fim");
    }
    // (h) recurso que nunca termina E evento perdido: o alarme resolve sozinho
    {
      const bg = montarBg((url) => url === PORTA(2) ? { carregando: true, semEvento: true } : {});
      bg.clicar(); await bg.esperar(200);
      chk(bg.store.pactha_roteiro && bg.store.pactha_roteiro.passo === 2, "(h) parado na porta 3");
      await bg.tick(); await bg.esperar(400);
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(h) o alarme destravou");
    }
    // (i) a aba recusa navegar uma vez: o passo volta e o alarme refaz
    {
      const bg = montarBg(() => ({}));
      bg.clicar(); await bg.esperar(20);
      const aba = [...bg.abas.values()][0];
      aba.recusa = 1;                            // a próxima tabs.update falha
      await bg.esperar(200);
      await bg.tick(); await bg.esperar(400);
      chk(JSON.stringify(aba.visitas) === JSON.stringify([PORTA(0), PORTA(1), PORTA(2), PORTA(3)]),
        "(i) navegação recusada não pula porta");
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(i) e a captura saiu");
    }
    // (j) roteiro ÓRFÃO de antes (2.4.1, sem alarme): o service worker rearma e limpa
    {
      const bg = montarBg(() => ({}), { pactha_roteiro: { tabId: 999, passo: 1, em: Date.now() } });
      await bg.esperar(30);
      chk(bg.alarmes.has("pactha_roteiro_tick"), "(j) ao subir, o alarme do roteiro que sobrou é rearmado");
      await bg.tick();
      chk(!bg.store.pactha_roteiro, "(j) e o roteiro órfão (aba 999 não existe) é encerrado");
    }
    // (k) o Chrome está DESLOGADO no fim: o popup fica sabendo que nada foi enviado
    {
      const bg = montarBg(() => ({}));
      bg.ctx.fetch = async (url, opt) => {
        if (opt && opt.method === "POST") { bg.posts.push(JSON.parse(opt.body)); return { ok: true, status: 200, json: async () => ({}) }; }
        if (String(url).includes("/session-capture/saude")) return { ok: true, status: 200, json: async () => ({}) };
        return { ok: true, status: 200, url, text: async () => '<TITLE>HTTP Post Binding (Request)</TITLE><FORM ACTION="https://idp.transferegov.sistema.gov.br/idp/"><INPUT NAME="SAMLRequest" VALUE="x"/></FORM>' };
      };
      bg.clicar(); await bg.esperar(400);
      chk(govbrPosts(bg).length === 0, "(k) Chrome deslogado: nada enviado");
      chk(bg.store.pactha_roteiro_fim && /não está logado/.test(bg.store.pactha_roteiro_fim.barrado || ""),
        "(k) e o motivo fica para o popup (não mais «enviando…» por 10 min)");
    }
    // (f) o estado existe ANTES de a aba navegar (a corrida que perdia o 1º evento)
    {
      const bg = montarBg(() => ({}));
      let viuEstado = null;
      const updateOriginal = bg.ctx.chrome.tabs.update;
      bg.ctx.chrome.tabs.update = (id, o) => { viuEstado = !!bg.store.pactha_roteiro; updateOriginal(id, o); };
      bg.clicar(); await bg.esperar(50);
      chk(viuEstado === true, "(f) o roteiro é gravado antes de a aba ir para a porta 1");
    }
  }

  console.log("\n13) ACESSO LIVRE (visitante): só marcadores PRECISOS — página logada nunca é visitante");
  {
    // (c) do pedido de 24/09/2026. Página logada tomada por visitante = a captura boa
    // barrada para sempre, em silêncio, e o roteiro mandando a aba para o LLO.
    const { ctx } = montar({});
    const URL_TG = URL_VISITANTE;
    chk(ctx.corpoEhAcessoLivre(HTML_VISITANTE) === true, "o HTML medido de visitante = Acesso Livre");
    chk(ctx.corpoEhAcessoLivre('<div id="info"><span class="exit">Sair do Acesso Livre <input type="button" class="bt_exit" value=""></span></div>') === true,
      "só o span.exit «Sair do Acesso Livre» (sem título) também é");
    // O TÍTULO NÃO DECIDE (revisão de 24/09/2026): a página logada não foi medida, e o
    // keepalive do servidor, calibrado com sessão real, viu "Acesso Livre" no cabeçalho LOGADO.
    chk(ctx.corpoEhAcessoLivre("<title>Transferegov - Consultar Proposta - Acesso Livre</title>") === false,
      "só o <title> com «Acesso Livre» NÃO é visitante (não decide sozinho)");
    chk(ctx.corpoEhAcessoLivre(HTML_LOGADA) === false,
      "página logada simulada (título sem «Acesso Livre», span.exit «Sair», «Acesso Livre» no menu) NÃO é");
    const LOGADA_TITULO_LIVRE = HTML_LOGADA.replace("<title>Transferegov - Consultar Proposta</title>",
      "<title>Transferegov - Consultar Proposta - Acesso Livre</title>");
    chk(ctx.corpoEhAcessoLivre(LOGADA_TITULO_LIVRE) === false
      && ctx.estadoLogin(URL_TG, LOGADA_TITULO_LIVRE).motivo === "logado",
      "página LOGADA com «Acesso Livre» no <title> (o pior caso não medido) = LOGADA");
    chk(ctx.corpoEhAcessoLivre('<span class="exit">Sair do&nbsp;Acesso&#160;Livre <input class="bt_exit"></span>') === true,
      "span.exit com &nbsp;/&#160; entre as palavras continua visitante");
    chk(ctx.corpoEhAcessoLivre('<a href="/voluntarias?LLO=true"><b>Sair do Acesso Livre</b></a>') === true,
      "o link do LLO com o texto «Sair do Acesso Livre» (sem o span) também é visitante");
    chk(ctx.corpoEhAcessoLivre("<a href='#'>Sair do Acesso Livre</a>") === false
      && ctx.corpoEhAcessoLivre('<a href="/voluntarias?LLO=true">voltar</a>') === false,
      "só o texto (sem o LLO) ou só o LLO (sem o texto) NÃO bastam");
    chk(ctx.tituloEhAcessoLivre("Transferegov - Consultar Proposta - Acesso Livre") === true,
      "título com espaço não separável (U+00A0) continua disparando a pergunta");
    const armadilha = "https://www.gov.br/transferegov/pt-br/sistemas/acesso-livre";
    chk(ctx.ehPaginaDoAcessoLivre(armadilha) === true && ctx.ehPaginaDoAcessoLivre(armadilha + "/") === true,
      "ehPaginaDoAcessoLivre: o link-armadilha medido da tela de login");
    chk(ctx.ehPaginaDoAcessoLivre("https://www.gov.br/transferegov/pt-br") === false
      && ctx.ehPaginaDoAcessoLivre(URL_VISITANTE) === false
      && ctx.ehPaginaDoAcessoLivre("https://sso.acesso.gov.br/login") === false
      && ctx.ehPaginaDoAcessoLivre("https://discricionarias.transferegov.sistema.gov.br/acesso-livre") === false
      && ctx.ehPaginaDoAcessoLivre("lixo") === false,
      "ehPaginaDoAcessoLivre: outras páginas do gov.br, do TransfereGov e do login NÃO são");
    const escondidas = {
      "num <script>": '<script>var rotulo = \'<span class="exit">Sair do Acesso Livre</span>\';</script>',
      "num comentário": '<!-- <span class="exit">Sair do Acesso Livre <input class="bt_exit"></span> -->',
      "num div oculto (frase solta)": '<div style="display:none">Sair do Acesso Livre</div>',
      "num <template>": '<template><title>Consultar - Acesso Livre</title></template>',
      "num botão com outra classe": '<span class="bt_exit">Sair do Acesso Livre</span>',
    };
    Object.entries(escondidas).forEach(([onde, trecho]) => {
      const html = HTML_LOGADA.replace("</body>", trecho + "</body>");
      chk(ctx.corpoEhAcessoLivre(html) === false && ctx.vereditoLogin(URL_TG, html) === true,
        `página logada com «Sair do Acesso Livre» escondido ${onde} = LOGADA (não visitante)`);
    });
    chk(ctx.corpoEhLogin(MURO_REAL) === true && ctx.corpoEhAcessoLivre(MURO_REAL) === false,
      "o muro SAML continua reconhecido (e não é visitante)");
    chk(JSON.stringify(ctx.estadoLogin(URL_TG, HTML_VISITANTE)) === JSON.stringify({ valor: false, motivo: "visitante" }),
      "estadoLogin: visitante");
    chk(ctx.estadoLogin(URL_TG, MURO_REAL).motivo === "login", "estadoLogin: muro = login");
    chk(ctx.estadoLogin(URL_TG, HTML_LOGADA).motivo === "logado", "estadoLogin: logada = logado");
    chk(ctx.estadoLogin(URL_TG, "<html>erro 500</html>").motivo === "nao_sei", "estadoLogin: sem prova = nao_sei");
    chk(ctx.tituloEhAcessoLivre(TIT_LIVRE) === true && ctx.tituloEhAcessoLivre(TIT_LOGIN) === false
      && ctx.tituloEhAcessoLivre(TIT_LOGADA) === false, "tituloEhAcessoLivre: só o título de visitante");
    chk(ctx.estadoLogin(URL_TG, "<title>X - Acesso Livre</title><a>Sair</a>").motivo === "logado",
      "estadoLogin: título de visitante SEM o span.exit não é visitante");
    chk(vm.runInContext("LLO_URL", ctx) === "https://discricionarias.transferegov.sistema.gov.br/voluntarias?LLO=true",
      "LLO_URL é o «Sair do Acesso Livre» medido");

    let corpo = HTML_VISITANTE;
    ctx.fetch = async (url) => ({ ok: true, status: 200, url, text: async () => corpo });
    chk(JSON.stringify(await ctx.chromeEstadoLogin()) === JSON.stringify({ valor: false, motivo: "visitante" }),
      "chromeEstadoLogin: sonda de visitante → {false, visitante}");
    chk((await ctx.chromeEstaLogado()) === false, "chromeEstaLogado continua existindo (delega) e diz false");
    corpo = MURO_REAL;
    chk((await ctx.chromeEstadoLogin()).motivo === "login", "chromeEstadoLogin: muro → login");
    corpo = HTML_LOGADA;
    chk(JSON.stringify(await ctx.chromeEstadoLogin()) === JSON.stringify({ valor: true, motivo: "logado" }),
      "chromeEstadoLogin: logada → {true, logado}");
    const { ctx: ctx2 } = montar({});
    ctx2.fetch = async () => { throw new Error("Failed to fetch"); };
    chk(JSON.stringify(await ctx2.chromeEstadoLogin()) === JSON.stringify({ valor: null, motivo: "nao_sei" }),
      "chromeEstadoLogin: rede fora → {null, nao_sei} (não barra a recaptura)");
  }

  console.log("\n14) o 401 diz o MOTIVO do servidor e a AÇÃO (o Juranda ficou em «HTTP 401» mudo)");
  {
    // (f) do pedido de 24/09/2026.
    const { ctx } = montar({});
    const amb = [{ nome: "Juranda - PR", api: "https://j.sslip.io/api", token: "pactha_st_x", ativo: true }];
    ctx.fetch = async () => ({ ok: false, status: 401, json: async () => ({ detail: "Token inválido ou revogado" }) });
    const [i] = await ctx.consultarSaude(amb);
    chk(i.ok === false && i.status === 401 && i.detalhe === "HTTP 401 — Token inválido ou revogado",
      "consultarSaude: 401 com {detail} → «HTTP 401 — Token inválido ou revogado»");
    ctx.fetch = async () => ({ ok: false, status: 404, json: async () => { throw new Error("not json"); } });
    chk((await ctx.consultarSaude(amb))[0].detalhe === "HTTP 404", "sem corpo JSON: só o código (servidor sem a rota)");
    ctx.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ msg: "x" }] }) });
    chk((await ctx.consultarSaude(amb))[0].detalhe === "HTTP 422", "detail que não é texto não vira «[object Object]»");
    ctx.fetch = async () => ({ ok: false, status: 401, json: async () => ({ detail: "Service token expirado" }) });
    const [e] = await ctx.enviarParaTodos({ automation_key: "govbr" }, amb);
    chk(e.ok === false && e.detalhe === "token inválido (Service token expirado)", "a captura recusada também diz o motivo");

    // A LINHA do popup: a função de verdade, tirada do popup.js (o resto dele precisa do DOM).
    const pj = ler("popup.js");
    const ini = pj.indexOf("function textoDoItem(");
    vm.runInContext(pj.slice(ini, pj.indexOf("\n}\n", ini) + 2), ctx);
    const linha = ctx.textoDoItem(i);
    chk(/RECUSOU o token \(Token inválido ou revogado\)/.test(linha), "popup: a linha do 401 mostra o motivo do servidor");
    chk(/gere um novo token em Configurações › Service Tokens no PACTHA desse cliente e cole em «Configurar token PACTHA»/.test(linha),
      "popup: e a ação (novo token, colar em «Configurar token PACTHA»)");
    chk(/RECUSOU o token/.test(ctx.textoDoItem({ nome: "X", ok: false, detalhe: "HTTP 401" })),
      "popup: item antigo guardado no storage (sem `status`) também é reconhecido");
    chk(/sem resposta \(HTTP 503\)/.test(ctx.textoDoItem({ nome: "X", ok: false, status: 503, detalhe: "HTTP 503" })),
      "popup: outro erro continua «sem resposta»");
  }

  console.log("\n15) ACESSO LIVRE no ROTEIRO e no modo automático, rodando no Chrome falso");
  {
    // ⛔ O "Sair do Acesso Livre" (LLO) é o LOGOUT de tudo, inclusive do gov.br (medido em
    // 24/09/2026): NENHUM cenário pode navegar para ele. A saída é apagar o JSESSIONID do
    // discricionarias (a sessão de visitante) e reabrir a porta 1.
    const LLO = vm.runInContext("LLO_URL", montarBg(() => ({})).ctx);
    const sondaPor = (estado) => () => (estado() === "visitante" ? HTML_VISITANTE
      : (estado() === "logado" ? HTML_LOGADA : MURO_REAL));
    const apagouVisitante = (bg) => bg.removidos.filter((d) => d.name === "JSESSIONID"
      && /^https:\/\/discricionarias\.transferegov\.sistema\.gov\.br\/voluntarias/.test(d.url)).length;

    // (a) porta 1 no Acesso Livre → apaga a sessão de visitante → porta 1 → tela de login
    //     (espera) → logado → portas 2..4 → captura final ENVIADA
    {
      let estado = "visitante";
      const bg = montarBg((url) => {
        if (url === PORTA(0) && estado === "visitante") return { url: URL_VISITANTE, titulo: TIT_LIVRE };
        if (url === PORTA(0) && estado === "deslogado") return { url: URL_IDP_COM_CONTEXTO, titulo: TIT_LOGIN };
        return { titulo: TIT_LOGADA };
      }, { pactha_visitante: { quando: new Date().toISOString() } },   // o automático já tinha visto o visitante
      { sonda: sondaPor(() => estado), aoApagarVisitante: () => { estado = "deslogado"; } });
      bg.clicar(); await bg.esperar(300);
      const aba = [...bg.abas.values()][0];
      const rot = bg.store.pactha_roteiro;
      chk(JSON.stringify(aba.visitas) === JSON.stringify([URL_VISITANTE, URL_IDP_COM_CONTEXTO]),
        "(a) visitante → sessão de visitante apagada → porta 1 → tela de login COM contexto");
      chk(apagouVisitante(bg) === 1 && bg.removidos.length === 1,
        "(a) apagou SÓ o JSESSIONID do discricionarias, uma vez");
      chk(!bg.navegacoes.includes(LLO), "(a) NUNCA foi ao «Sair do Acesso Livre» (o logout de tudo)");
      chk(rot && rot.passo === 0 && rot.saidasDoLivre === 1,
        "(a) o roteiro voltou ao passo 0 com 1 saída do Acesso Livre contada");
      chk(rot && /«Entrar com gov\.br»/.test(rot.fase) && /NÃO em «Acesso livre»/.test(rot.fase),
        "(a) espera o login dizendo «Entrar com gov.br», NÃO «Acesso livre»");
      chk(govbrPosts(bg).length === 0, "(a) nada enviado antes do login");
      // a PESSOA faz o login; o gov.br devolve à porta 1 logada
      estado = "logado";
      aba.url = PORTA(0); aba.title = TIT_LOGADA; aba.status = "complete"; aba.visitas.push(PORTA(0));
      bg.ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: PORTA(0), frameId: 0 }));
      await bg.esperar(500);
      chk(JSON.stringify(aba.visitas.slice(-4)) === JSON.stringify([PORTA(0), PORTA(1), PORTA(2), PORTA(3)]),
        "(a) depois do login: as 4 portas, em ordem");
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "(a) e a captura final foi ENVIADA");
      chk(bg.store.pactha_roteiro_fim && !bg.store.pactha_roteiro_fim.barrado, "(a) sem motivo de barrado no fim");
      chk(!bg.store.pactha_visitante, "(a) a sonda logada limpa o aviso de visitante");
      const lc = bg.store.pactha_last_capture;
      chk(lc && lc.automation_key === "govbr" && lc.sonda === "logado",
        "(a) a última captura grava QUAL sistema e o que a sonda disse");
    }

    // (b) continua no Acesso Livre mesmo depois de apagar (a pessoa volta ao visitante):
    //     3 saídas e encerra com o motivo, sem enviar, em vez de rodar em círculo
    {
      const bg = montarBg((url) => {
        if (url === PORTA(0)) return { url: URL_VISITANTE, titulo: TIT_LIVRE };
        return { titulo: TIT_LOGADA };
      }, null, { sonda: () => HTML_VISITANTE });
      bg.clicar(); await bg.esperar(700);
      const fim = bg.store.pactha_roteiro_fim;
      chk(!bg.store.pactha_roteiro, "(b) o roteiro encerrou");
      chk(bg.navegacoes.filter((u) => u === PORTA(0)).length === 4 && !bg.navegacoes.includes(LLO),
        "(b) saiu do Acesso Livre 3 vezes (porta 1 reaberta 3×), e não uma 4ª — e nunca pelo LLO");
      chk(fim && fim.visitante === true && /voltou ao Acesso Livre/.test(fim.barrado || "")
        && /«Entrar com gov\.br»/.test(fim.barrado || ""), "(b) o motivo fica para o popup: voltou ao Acesso Livre; «Entrar com gov.br»");
      // medido em 24/09/2026: o visitante voltou MESMO com «Entrar com gov.br» (a conta do Chrome)
      chk(/conta gov\.br deste Chrome/.test(fim.barrado || "") && /conta gov\.br cadastrada no TransfereGov/.test(fim.barrado || "")
        && /servidores sem sessão/.test(fim.barrado || ""),
        "(b) e o caso da CONTA: sair de tudo só com os servidores sem sessão, e entrar com a conta cadastrada");
      chk(govbrPosts(bg).length === 0 && !bg.posts.some((p) => p.automation_key === "govbr"), "(b) nada enviado");
      chk(!bg.alarmes.has("pactha_roteiro_tick"), "(b) o alarme do roteiro foi desligado");
      chk(bg.selo.texto === "!" && /ACESSO LIVRE/.test(bg.selo.titulo), "(b) selo «!» dizendo Acesso Livre");
    }

    // (e) evento + alarme JUNTOS na página de visitante, e um evento ATRASADO dela: sai UMA vez só
    {
      let estado = "visitante";
      const bg = montarBg((url) => {
        if (url === PORTA(0) && estado === "visitante") return { url: URL_VISITANTE, titulo: TIT_LIVRE, semEvento: true };
        if (url === PORTA(0)) return { url: URL_IDP_COM_CONTEXTO, titulo: TIT_LOGIN, pendenteMs: 60 };
        return { titulo: TIT_LOGADA };
      }, null, { sonda: sondaPor(() => estado), sondaMs: 15, aoApagarVisitante: () => { estado = "deslogado"; } });
      bg.clicar(); await bg.esperar(60);
      const aba = [...bg.abas.values()][0];
      chk(aba.url === URL_VISITANTE && bg.navegacoes.length === 1, "(e) parado na página de visitante, sem evento");
      bg.ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: aba.url, frameId: 0 }));      // o evento…
      for (const f of bg.ouvintes.alarme) f({ name: "pactha_roteiro_tick" });               // …e o alarme, juntos
      await bg.esperar(30);
      bg.ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: URL_VISITANTE, frameId: 0 })); // …e um atrasado
      await bg.esperar(300);
      chk(apagouVisitante(bg) === 1, "(e) a sessão de visitante foi apagada UMA vez só");
      chk(bg.navegacoes.filter((u) => u === PORTA(0)).length === 2, "(e) e a porta 1 reaberta uma vez só");
      const rot = bg.store.pactha_roteiro;
      chk(rot && rot.saidasDoLivre === 1 && rot.passo === 0, "(e) uma saída contada; ainda na porta 1 (esperando o login)");
    }

    // (e2) a navegação à porta 1 demora a APARECER na aba (a página de visitante segue
    //      "complete", sem pendingUrl) e o alarme cai nessa janela: é a página DEIXADA, não
    //      a porta 1 assentada — avançar ali pularia o login da porta 1
    {
      let estado = "visitante";
      const bg = montarBg((url) => {
        if (url === PORTA(0) && estado === "visitante") return { url: URL_VISITANTE, titulo: TIT_LIVRE };
        if (url === PORTA(0)) return { url: URL_IDP_COM_CONTEXTO, titulo: TIT_LOGIN, inicioMs: 40 };
        return { titulo: TIT_LOGADA };
      }, null, { sonda: sondaPor(() => estado), aoApagarVisitante: () => { estado = "deslogado"; } });
      bg.clicar();
      for (let k = 0; k < 100 && apagouVisitante(bg) === 0; k++) await bg.esperar(2);
      const aba = [...bg.abas.values()][0];
      chk(apagouVisitante(bg) === 1 && aba.url === URL_VISITANTE && !aba.pendingUrl,
        "(e2) a sessão de visitante foi apagada e a aba ainda mostra a página de visitante");
      await bg.tick();
      await bg.esperar(300);
      chk(!bg.navegacoes.includes(PORTA(1)), "(e2) o sinal velho NÃO avançou para a porta 2");
      chk(JSON.stringify(aba.visitas) === JSON.stringify([URL_VISITANTE, URL_IDP_COM_CONTEXTO])
        && bg.store.pactha_roteiro && bg.store.pactha_roteiro.saidasDoLivre === 1,
        "(e2) a porta 1 abriu a tela de login, com uma saída só");
    }

    // (d1) a captura FINAL barrada por visitante: o motivo de visitante fica para o popup
    {
      // títulos sem «Acesso Livre» (o roteiro passa), mas a sonda da porta 1 é de visitante
      const bg = montarBg(() => ({ titulo: TIT_LOGADA }), null, { sonda: () => HTML_VISITANTE });
      bg.clicar(); await bg.esperar(400);
      const fim = bg.store.pactha_roteiro_fim;
      chk(govbrPosts(bg).length === 0, "(d) captura final de visitante: nada enviado");
      chk(fim && fim.visitante === true && /Acesso Livre \(visitante\)/.test(fim.barrado || ""),
        "(d) o motivo gravado é o de VISITANTE (não «não está logado»)");
      chk(!!bg.store.pactha_visitante && bg.selo.texto === "!", "(d) e o Chrome fica marcado como visitante, com o «!»");
    }

    // (d2) a captura AUTOMÁTICA barrada por visitante: não navega nem apaga nada, grava e acende o «!»
    {
      let sonda = HTML_VISITANTE;
      const bg = montarBg(() => ({}), null, { sonda: () => sonda });
      bg.ouvintes.nav.forEach((f) => f({ tabId: 7, url: URL_VISITANTE, frameId: 0 }));
      await bg.esperar(100);
      const v = bg.store.pactha_visitante;
      chk(v && !isNaN(Date.parse(v.quando)), "(d) automática: grava pactha_visitante {quando}");
      chk(bg.navegacoes.length === 0 && bg.abas.size === 0 && bg.removidos.length === 0,
        "(d) automática: não navega, não abre aba e não apaga cookie nenhum");
      chk(!bg.posts.some((p) => p.automation_key === "govbr"), "(d) automática: nada enviado");
      chk(bg.selo.texto === "!" && /ACESSO LIVRE/.test(bg.selo.titulo), "(d) automática: selo «!» com o título do Acesso Livre");
      await bg.ctx.atualizarSaude({ forcar: true });
      chk(bg.selo.texto === "!", "(d) a consulta periódica de saúde (servidores vivos) não apaga o «!» do visitante");
      // uma captura do FNS (o keepalive de 12 min, sem porteiro) CHEGA aos servidores —
      // e não diz nada da sessão gov.br: o aviso de visitante fica
      await bg.ctx.capture("consultafns.saude.gov.br", "keepalive");
      await bg.esperar(50);
      const lc = bg.store.pactha_last_capture;
      chk(lc && lc.automation_key === "fns" && lc.ambientes_ok > 0 && !!bg.store.pactha_visitante && bg.selo.texto === "!",
        "(d) captura do FNS chegou, mas NÃO apaga o aviso de visitante");
      // a pessoa sai do Acesso Livre e entra: a próxima captura sai e limpa o aviso
      sonda = HTML_LOGADA;
      bg.ouvintes.nav.forEach((f) => f({ tabId: 7, url: PORTA(0), frameId: 0 }));
      await bg.esperar(150);
      chk(bg.posts.some((p) => p.automation_key === "govbr"), "(d) logado: a captura automática sai");
      chk(!bg.store.pactha_visitante && bg.selo.texto === "", "(d) e limpa pactha_visitante (o «!» apaga)");
    }

    // o roteiro NÃO apaga a sessão de uma aba logada: título com «Acesso Livre» mas a sonda diz logado
    {
      const bg = montarBg((url) => url === PORTA(0) ? { titulo: TIT_LIVRE } : { titulo: TIT_LOGADA }, null,
        { sonda: () => HTML_LOGADA });
      bg.clicar(); await bg.esperar(400);
      chk(bg.removidos.length === 0 && !bg.navegacoes.includes(LLO),
        "título de Acesso Livre com a sonda LOGADA: nenhum cookie apagado");
      chk(!bg.store.pactha_roteiro && govbrPosts(bg).length >= 1, "e o roteiro segue até a captura");
    }

    // o PIOR CASO não medido: a página LOGADA tem «Acesso Livre» no título (a aba e a sonda);
    // só o span.exit decide, então a sessão logada fica e a captura sai
    {
      const LOGADA_TITULO_LIVRE = HTML_LOGADA.replace("<title>Transferegov - Consultar Proposta</title>",
        "<title>Transferegov - Consultar Proposta - Acesso Livre</title>");
      const bg = montarBg(() => ({ titulo: TIT_LIVRE }), null, { sonda: () => LOGADA_TITULO_LIVRE });
      bg.clicar(); await bg.esperar(400);
      chk(bg.removidos.length === 0 && !bg.store.pactha_roteiro && govbrPosts(bg).length >= 1,
        "página logada com «Acesso Livre» no título: nada apagado, e a captura sai");
    }

    // título de visitante com a sonda SEM resposta: nem sai do Acesso Livre nem avança;
    // quando a sonda volta (visitante), o alarme leva à saída
    {
      let sondaFora = true;
      let estado = "visitante";
      const bg = montarBg((url) => {
        if (url === PORTA(0) && estado === "visitante") return { url: URL_VISITANTE, titulo: TIT_LIVRE };
        if (url === PORTA(0)) return { url: URL_IDP_COM_CONTEXTO, titulo: TIT_LOGIN };
        return { titulo: TIT_LOGADA };
      }, null, { sonda: () => (sondaFora ? "<html>erro 502</html>" : sondaPor(() => estado)()),
        aoApagarVisitante: () => { estado = "deslogado"; } });
      bg.clicar(); await bg.esperar(300);
      await bg.tick(); await bg.esperar(100);
      chk(bg.removidos.length === 0 && bg.navegacoes.length === 1 && bg.store.pactha_roteiro
        && bg.store.pactha_roteiro.passo === 0, "sonda sem resposta: não apaga nada e não avança de porta");
      sondaFora = false;
      await bg.tick(); await bg.esperar(300);
      chk(apagouVisitante(bg) === 1, "a sonda voltou: o alarme leva à saída do visitante");
    }

    // a ARMADILHA: na tela de login a pessoa clica «Acesso livre» (vai a www.gov.br); o roteiro
    // volta à porta 1 contando uma saída, e a 4ª vez encerra com o motivo
    {
      const ARMADILHA = "https://www.gov.br/transferegov/pt-br/sistemas/acesso-livre";
      const bg = montarBg((url) => {
        if (url === PORTA(0)) return { url: URL_IDP_COM_CONTEXTO, titulo: TIT_LOGIN };
        return { titulo: TIT_LOGADA };
      }, null, { sonda: () => MURO_REAL });
      bg.clicar(); await bg.esperar(200);
      const aba = [...bg.abas.values()][0];
      const clicaArmadilha = async () => {
        aba.url = ARMADILHA; aba.title = "Acesso livre — Transferegov"; aba.status = "complete";
        bg.ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: ARMADILHA, frameId: 0 }));
        await bg.esperar(150);
      };
      await clicaArmadilha();
      const rot = bg.store.pactha_roteiro;
      chk(bg.navegacoes.filter((u) => u === PORTA(0)).length === 2 && rot && rot.saidasDoLivre === 1
        && rot.passo === 0 && /você clicou em «Acesso livre»/.test(rot.fase),
        "armadilha: volta à porta 1, conta uma saída e diz o que aconteceu");
      chk(aba.url === URL_IDP_COM_CONTEXTO, "armadilha: e a aba está de novo na tela de login");
      // o onCompleted ATRASADO da página da armadilha, com a aba já na tela de login
      bg.ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: ARMADILHA, frameId: 0 }));
      await bg.tick(); await bg.esperar(150);
      chk(bg.store.pactha_roteiro && bg.store.pactha_roteiro.saidasDoLivre === 1
        && bg.navegacoes.filter((u) => u === PORTA(0)).length === 2,
        "armadilha: o evento atrasado dela NÃO conta uma segunda saída");
      await clicaArmadilha(); await clicaArmadilha();
      chk(bg.store.pactha_roteiro && bg.store.pactha_roteiro.saidasDoLivre === 3, "armadilha: 3 saídas contadas");
      await clicaArmadilha();
      const fim = bg.store.pactha_roteiro_fim;
      chk(!bg.store.pactha_roteiro && fim && fim.visitante === true && /«Entrar com gov\.br»/.test(fim.barrado || ""),
        "armadilha pela 4ª vez: encerra com o motivo (em vez de «tempo esgotado» 20 min depois)");
      chk(bg.navegacoes.filter((u) => u === PORTA(0)).length === 4 && govbrPosts(bg).length === 0,
        "armadilha: nenhuma 5ª navegação e nada enviado");
    }

    // a sonda dizendo DESLOGADO (muro/login) apaga o aviso de visitante: não é mais visitante
    {
      const bg = montarBg(() => ({}), { pactha_visitante: { quando: new Date().toISOString() } },
        { sonda: () => MURO_REAL });
      bg.ouvintes.nav.forEach((f) => f({ tabId: 7, url: PORTA(0), frameId: 0 }));
      await bg.esperar(150);
      chk(!bg.store.pactha_visitante && !bg.posts.some((p) => p.automation_key === "govbr"),
        "sonda deslogada: pactha_visitante apagado, e nada enviado");
    }

    // na tela de login, o ALARME não renova o prazo (só carregamento renova): parado 21 min, vence
    {
      const bg = montarBg((url) => (url === PORTA(0) ? { url: URL_IDP_COM_CONTEXTO, titulo: TIT_LOGIN } : {}),
        null, { sonda: () => MURO_REAL });
      bg.clicar(); await bg.esperar(200);
      const rot = bg.store.pactha_roteiro;
      const emAntes = rot.em;
      await bg.tick();
      chk(bg.store.pactha_roteiro && bg.store.pactha_roteiro.em === emAntes, "o alarme na tela de login NÃO renova `em`");
      bg.store.pactha_roteiro = { ...bg.store.pactha_roteiro, em: Date.now() - 21 * 60 * 1000 };
      await bg.tick();
      chk(!bg.store.pactha_roteiro && bg.store.pactha_roteiro_fim && bg.store.pactha_roteiro_fim.venceu === true,
        "21 min sem carregar nada na tela de login: o roteiro vence (antes só o teto de 60 min valia)");
    }
  }

  console.log("\n16) a faixa na PÁGINA (aviso_pagina.js): avisa sem mexer em nada");
  {
    const rodarAviso = ({ titulo, texto, roteiro, semBody, storageQuebrado, exit }) => {
      const porId = {};
      const mk = (tag) => ({
        tag, id: "", style: {}, attrs: {}, filhos: [], ouvintes: {}, textContent: "",
        setAttribute(k, v) { this.attrs[k] = v; },
        appendChild(c) { this.filhos.push(c); if (c.id) porId[c.id] = c; return c; },
        addEventListener(ev, f) { this.ouvintes[ev] = f; },
        remove() { if (this.id) delete porId[this.id]; this.removido = true; },
      });
      const body = semBody ? null : mk("body");
      if (body) body.innerText = texto || "";
      const store = roteiro ? { pactha_roteiro: roteiro } : {};
      const ctx = {
        Date, String,
        document: { title: titulo || "", readyState: "complete", body, documentElement: mk("html"),
          getElementById: (id) => porId[id] || null, createElement: mk, addEventListener() {},
          // o botão de saída do cabeçalho (`<span class="exit">`), como medido
          querySelector: (sel) => (sel === "span.exit" && exit != null ? { textContent: exit } : null) },
        chrome: { storage: { local: { get: (k, cb) => {
          if (storageQuebrado) throw new Error("Extension context invalidated.");
          const o = {}; k.forEach((x) => { if (x in store) o[x] = store[x]; }); cb(o);
        } } } },
      };
      vm.createContext(ctx);
      let erro = null;
      try { vm.runInContext(ler("aviso_pagina.js"), ctx); } catch (e) { erro = e; }
      const faixa = porId["pactha-aviso-faixa"] || null;
      return { faixa, erro, texto: faixa ? faixa.filhos[0].textContent : "" };
    };
    const ativo = { tabId: 1, passo: 0, em: Date.now(), inicio: Date.now() };
    const EXIT_LIVRE = "Sair do Acesso Livre ";
    let r = rodarAviso({ titulo: TIT_LIVRE, texto: "Sair do Acesso Livre", exit: EXIT_LIVRE });
    chk(r.faixa && /Acesso Livre \(visitante\)/.test(r.texto) && /«Captura completa»/.test(r.texto) && /«Sair do Acesso Livre»/.test(r.texto),
      "página de Acesso Livre: faixa de visitante (Captura completa / Sair do Acesso Livre)");
    r = rodarAviso({ titulo: TIT_LIVRE, texto: "Sair Consultar Proposta Acesso Livre", exit: "Sair " });
    chk(!r.faixa, "título com «Acesso Livre» mas o botão diz só «Sair» (logada): NENHUMA faixa");
    r = rodarAviso({ titulo: TIT_LIVRE, texto: "Sair do Acesso Livre", exit: EXIT_LIVRE, roteiro: ativo });
    chk(r.faixa && /está tirando este Chrome do Acesso Livre/.test(r.texto) && /aguarde/.test(r.texto)
      && !/clique em «Sair do Acesso Livre»/.test(r.texto),
      "Acesso Livre com a Captura completa em curso: «aguarde» (não manda sair à mão)");
    chk(!/«Sair do Acesso Livre» e entre/.test(ler("aviso_pagina.js")) && /Evite «Sair do Acesso Livre»/.test(ler("aviso_pagina.js")),
      "a faixa NÃO manda clicar em «Sair do Acesso Livre» (é o logout do gov.br) — manda evitar");
    r = rodarAviso({ titulo: TIT_LOGIN, texto: "Entrar com gov.br  Acesso livre", roteiro: ativo });
    chk(r.faixa && /clique em «Entrar com gov\.br»/.test(r.texto) && /Não use «Acesso livre»/.test(r.texto),
      "tela de login com o roteiro ativo: «clique em Entrar com gov.br; não use Acesso livre»");
    chk(r.faixa && r.faixa.style.cssText.includes("position:fixed") && /z-index:\s*2147483647/.test(r.faixa.style.cssText),
      "a faixa é fixa no topo, por cima de tudo");
    r = rodarAviso({ titulo: "Transferegov", texto: "Entrar com gov.br", roteiro: ativo });
    chk(!!r.faixa, "tela de login reconhecida também pelo texto «Entrar com gov.br»");
    r = rodarAviso({ titulo: TIT_LOGIN, texto: "Entrar com gov.br" });
    chk(!r.faixa, "tela de login SEM roteiro: nenhuma faixa (seria ruído em todo login)");
    r = rodarAviso({ titulo: TIT_LOGIN, texto: "Entrar com gov.br", roteiro: { ...ativo, em: Date.now() - 30 * 60 * 1000 } });
    chk(!r.faixa, "roteiro vencido que sobrou no storage não acende a faixa");
    r = rodarAviso({ titulo: TIT_LOGADA, texto: "Sair  Consultar Proposta", roteiro: ativo });
    chk(!r.faixa, "página logada: nenhuma faixa");
    r = rodarAviso({ titulo: TIT_LIVRE, exit: EXIT_LIVRE });
    r.faixa.filhos[1].ouvintes.click();
    chk(r.faixa.removido === true, "o × fecha a faixa");
    r = rodarAviso({ titulo: TIT_LIVRE, semBody: true, exit: EXIT_LIVRE });
    chk(!r.erro, "página sem <body>: não quebra");
    r = rodarAviso({ titulo: TIT_LOGIN, texto: "Entrar com gov.br", storageQuebrado: true });
    chk(!r.erro && !r.faixa, "extensão recarregada (storage lança): não quebra a página");
    const src = ler("aviso_pagina.js");
    chk(!/\.submit\(|\.click\(|fetch\(|XMLHttpRequest|sendMessage|\.value\s*=|querySelectorAll|\.forms\b|cookie|input\b/i.test(src)
      && (src.match(/querySelector\(/g) || []).length === 1 && /querySelector\("span\.exit"\)/.test(src),
      "o script não clica, não preenche, não lê formulário/cookie e não envia nada (só lê o span.exit)");
  }

  console.log("\n17) manifest, popup e textos da 2.4.5");
  {
    const man = JSON.parse(ler("manifest.json"));
    chk(man.version === "2.4.5", "versão 2.4.5");
    const cs = (man.content_scripts || [])[0] || {};
    chk((cs.js || []).includes("aviso_pagina.js")
      && (cs.matches || []).includes("https://idp.transferegov.sistema.gov.br/*")
      && (cs.matches || []).includes("https://*.transferegov.sistema.gov.br/*"),
      "content_scripts: aviso_pagina.js no idp e em *.transferegov");
    chk(!(man.permissions || []).includes("scripting"), "sem a permissão «scripting»");
    const pj = ler("popup.js");
    const ph = ler("popup.html");
    chk(/fim\.barrado && fim\.visitante/.test(pj), "popup: roteiro barrado por visitante tem mensagem própria");
    const m = /const PASSO_A_PASSO_LIVRE = ([\s\S]*?");\s*\n/.exec(pj);
    const passo = m ? vm.runInNewContext(m[1]) : "";
    chk(/«Captura completa»/.test(passo) && /«Entrar com gov\.br» \(NUNCA em «Acesso livre»\)/.test(passo),
      "popup: o passo a passo diz «Captura completa» e «Entrar com gov.br», nunca «Acesso livre»");
    chk(/voltar como visitante/.test(passo) && /conta cadastrada/.test(passo),
      "popup: e o que fazer se, mesmo com gov.br, voltar como visitante (a conta)");
    chk(/pactha_visitante/.test(pj) && /AVISO_LIVRE_VALE_MS = 6 \* 60 \* 60 \* 1000/.test(pj) && /recente && !rot/.test(pj),
      "popup: aviso de Acesso Livre com pactha_visitante < 6h e sem roteiro ativo");
    chk(/id="aviso-livre"/.test(ph), "popup.html: o lugar do aviso de Acesso Livre");
    chk(/clique em <strong>«Entrar com gov\.br»<\/strong>,\s*nunca em «Acesso livre»/.test(ph),
      "popup.html: a ajuda perto do botão diz «Entrar com gov.br», nunca «Acesso livre»");
    chk(/mud\.pactha_roteiro \|\|/.test(pj) && /setInterval\(\(\) => \{ refreshLastCapture\(\); mostrarRoteiro\(\); \}, 2000\)/.test(pj),
      "popup: o «Abrindo as 4 portas…» é trocado pelo andamento (ouvinte do storage + relógio de 2s)");
  }

  console.log("\n18) o POPUP de verdade: mostrarRoteiro diz o que fazer em cada estado");
  {
    // A função REAL, tirada do popup.js com as constantes do topo (o resto precisa do DOM).
    // Revisão de 24/09/2026: 3 mutações nas mensagens passavam com TUDO OK.
    const pj = ler("popup.js");
    const consts = pj.slice(pj.indexOf("const $ = "), pj.indexOf("// Ver nota em background.js: config salva"));
    const iniM = pj.indexOf("async function mostrarRoteiro(");
    const fonteM = pj.slice(iniM, pj.indexOf("\n}\n", iniM) + 3);
    const rodarPopup = async (store) => {
      const aviso = { id: "aviso-livre", textContent: "", classes: new Set(["hidden"]) };
      aviso.classList = { toggle: (c, on) => { if (on) aviso.classes.add(c); else aviso.classes.delete(c); } };
      let status = null;
      const ctx = {
        Date, String, Math, JSON, Promise, PORTAS_GOVBR: [1, 2, 3, 4],
        document: { getElementById: (id) => (id === "aviso-livre" ? aviso : null) },
        chrome: { storage: { local: { get: (k, cb) => { const o = {}; k.forEach((x) => { if (x in store) o[x] = store[x]; }); cb(o); } } } },
        showStatus: (msg, kind) => { status = { msg, kind }; },
      };
      vm.createContext(ctx);
      vm.runInContext(consts + "\n" + fonteM, ctx);
      await ctx.mostrarRoteiro();
      return { status, aviso, visivel: !aviso.classes.has("hidden") };
    };
    const agora = new Date().toISOString();
    const depois = new Date(Date.now() + 2000).toISOString();
    const rotAtivo = { tabId: 1, passo: 0, em: Date.now(), inicio: Date.now(), fase: "passando pelo login" };
    let p = await rodarPopup({ pactha_visitante: { quando: agora } });
    chk(p.visivel && /ACESSO LIVRE/.test(p.aviso.textContent) && /«Entrar com gov\.br»/.test(p.aviso.textContent),
      "visitante recente e sem roteiro: o aviso de Acesso Livre aparece, com «Entrar com gov.br»");
    p = await rodarPopup({ pactha_visitante: { quando: agora }, pactha_roteiro: rotAtivo });
    chk(!p.visivel && /porta 1 de 4/.test(p.status.msg), "com o roteiro em curso: o aviso some e o andamento aparece");
    p = await rodarPopup({ pactha_visitante: { quando: new Date(Date.now() - 7 * 3600 * 1000).toISOString() } });
    chk(!p.visivel, "visitante de mais de 6h: sem aviso");
    const fimLivre = { quando: agora, barrado: "o TransfereGov deste Chrome está no Acesso Livre (visitante)", visitante: true };
    p = await rodarPopup({ pactha_roteiro_fim: fimLivre });
    chk(p.status.kind === "error" && /«Entrar com gov\.br»/.test(p.status.msg) && /«Captura completa»/.test(p.status.msg)
      && !/Faça o login no TransfereGov/.test(p.status.msg),
      "roteiro barrado por VISITANTE: passo a passo do Acesso Livre (e não «faça o login»)");
    p = await rodarPopup({ pactha_roteiro_fim: { quando: agora, barrado: "o Chrome não está logado no TransfereGov" } });
    chk(p.status.kind === "error" && /Faça o login no TransfereGov/.test(p.status.msg), "roteiro barrado por DESLOGADO: «faça o login»");
    const enviou = { quando: depois, reason: "navigation", host: "discricionarias.transferegov.sistema.gov.br",
      automation_key: "govbr", sonda: "logado", ambientes_ok: 7, ambientes_total: 7, falhas: [] };
    p = await rodarPopup({ pactha_roteiro_fim: fimLivre, pactha_last_capture: enviou });
    chk(p.status.kind === "success" && /Captura enviada: 7 de 7/.test(p.status.msg) && !/Nada foi enviado/.test(p.status.msg),
      "barrado, mas uma captura do TransfereGov LOGADA chegou depois: mostra o envio, não a recusa velha");
    p = await rodarPopup({ pactha_roteiro_fim: { quando: agora, venceu: true }, pactha_last_capture: enviou });
    chk(p.status.kind === "success", "tempo esgotado, mas uma captura logada chegou depois: mostra o envio");
    p = await rodarPopup({ pactha_roteiro_fim: fimLivre,
      pactha_last_capture: { ...enviou, ambientes_ok: 0, falhas: ["A: HTTP 500"] } });
    chk(/Nada foi enviado/.test(p.status.msg), "captura depois que não chegou a NENHUM servidor não apaga a recusa");
    // a revisão de 24/09/2026: o keepalive de 12 min captura FNS/SIMEC (sem porteiro) e isso
    // CHEGA aos servidores — não pode virar "Captura enviada" verde sobre o TransfereGov barrado
    for (const [k, host] of [["fns", "consultafns.saude.gov.br"], ["simec", "simec.mec.gov.br"]]) {
      p = await rodarPopup({ pactha_roteiro_fim: fimLivre,
        pactha_last_capture: { ...enviou, automation_key: k, host, reason: "keepalive", sonda: null } });
      chk(/Nada foi enviado/.test(p.status.msg) && p.status.kind === "error",
        `captura do ${k.toUpperCase()} depois não troca a recusa do TransfereGov por «enviada»`);
    }
    p = await rodarPopup({ pactha_roteiro_fim: fimLivre, pactha_last_capture: { ...enviou, sonda: "nao_sei" } });
    chk(/Nada foi enviado/.test(p.status.msg), "captura govbr com a sonda SEM resposta não prova login: a recusa fica");
    p = await rodarPopup({ pactha_roteiro_fim: fimLivre,
      pactha_last_capture: { quando: depois, host: "discricionarias.transferegov.sistema.gov.br", ambientes_ok: 7, ambientes_total: 7 } });
    chk(/Nada foi enviado/.test(p.status.msg), "captura antiga no storage (sem automation_key) não conta como prova");
    chk(/estado\.motivo === "visitante"\s*\?\s*`Este Chrome está no ACESSO LIVRE/.test(pj),
      "captura manual: visitante tem mensagem própria");
  }

  console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTUDO OK");
  process.exit(falhas ? 1 : 0);
})();
