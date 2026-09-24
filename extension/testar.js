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

(async () => {
  console.log(`pasta: ${DIR}${TEM_TOKENS ? "  (com tokens.local.js)" : "  (sem tokens pré-configurados)"}`);

  console.log("\n1) lista base");
  {
    const { ctx } = montar({});
    const lista = await ctx.lerAmbientes();
    chk(lista.length >= 5, `${lista.length} ambientes (esperado >= 5)`);
    chk(lista.every((a) => /^https:\/\//.test(a.api)), "toda api é https");
    if (TEM_TOKENS) {
      chk(lista.every((a) => a.token && a.token.startsWith("pactha_st_")),
        "os cinco saem com service token — se falhar, a chave do mapa não bate com a api");
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
    const iPorteiro = bg.indexOf("await chromeEstaLogado()");
    const iDebounce = bg.indexOf("lastCaptureAt.set(dKey, now)");
    chk(iPorteiro > 0 && iPorteiro < iDebounce,
      "em capture(), o porteiro vem ANTES de marcar o debounce (senão a página SAML engole a captura boa)");
    chk(/tab\.status\s*!==\s*"complete"/.test(bg), "o roteiro só avança com a aba `complete`");
    chk(/if\s*\(!itens\.some\(\(i\)\s*=>\s*i\.ok\)\)\s*return/.test(bg),
      "sem nenhuma resposta de servidor o selo não muda");
    chk(/chromeEstaLogado\(\)\)\s*===\s*false/.test(ler("popup.js")), "a captura MANUAL passa pelo mesmo porteiro");
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
    chk(/if \(pareceLogin\(details\.url\)\) \{[\s\S]{0,900}\{ \.\.\.rot, em: Date\.now\(\) \}/.test(bg),
      "na tela de login o roteiro regrava `em` (login demorado não mata o roteiro no meio)");
  }

  console.log("\n9b) VISITANTE («Acesso Livre») não é login — nem com o botão «Sair» na página");
  {
    const { ctx } = montar({});
    const URL_TG = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/proposta/ConsultarProposta/ConsultarProposta.do";
    // Como o Chrome do dono estava em 23/09/2026 (título e botão da página real).
    const visitante = "<title>Transferegov - Consultar Proposta - Acesso Livre</title>"
      + "<a href='#'>Sair do Acesso Livre</a> Consultar Proposta";
    chk(ctx.vereditoLogin(URL_TG, visitante) === false, "página de visitante = deslogado (o jar não sai)");
    chk(ctx.vereditoLogin(URL_TG, "<a>Sair</a> Consultar Proposta") === true, "página logada continua logada");
  }

  console.log("\n11b) salvar os tokens TESTA cada um no servidor e acusa o incompleto");
  {
    const pj = ler("popup.js");
    chk(/a\.token\.length < 50/.test(pj), "token pactha_st_ curto (só o começo, da lista) é acusado como INCOMPLETO");
    chk(/btn-save-config[\s\S]{0,4000}consultarSaude\(lista\)/.test(pj), "ao salvar, cada token é testado no servidor dele");
    chk(/HTTP 40\[13\]/.test(pj), "401/403 viram «o servidor RECUSOU o token de: …»");
  }

  console.log("\n12) o ROTEIRO da captura completa, rodando de verdade num Chrome falso");
  {
    // ⚠️ Travou em produção em 23/09/2026 ("só fica abrindo e não captura"). Estes
    // cenários rodam o background.js inteiro com abas, eventos e alarme simulados.
    const montarBg = (cenario, inicial) => {
      const store = { pactha_ambientes: [{ nome: "A", api: "https://a.sslip.io/api", token: "pactha_st_a", ativo: true }],
        ...(inicial || {}) };
      const ouvintes = { nav: [], alarme: [], msg: [] };
      const abas = new Map();
      const posts = [];
      const alarmes = new Set();
      let proxId = 100;
      const ecoa = (v, cb) => { if (cb) cb(v); return Promise.resolve(v); };
      const nada = () => {};
      const navegar = (aba, url) => {
        const plano = cenario(url, aba) || {};
        aba.status = "loading";
        aba.pendingUrl = url;                    // como no Chrome: a URL velha fica até o commit
        const commit = () => {
          delete aba.pendingUrl;
          aba.url = plano.url || url;
          (aba.visitas = aba.visitas || []).push(aba.url);
          if (!plano.carregando) aba.status = "complete";
          if (!plano.semEvento) ouvintes.nav.forEach((f) => f({ tabId: aba.id, url: aba.url, frameId: 0 }));
        };
        setTimeout(commit, plano.pendenteMs || 1);
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
            if (aba && o.url) navegar(aba, o.url);
            return Promise.resolve(aba);
          },
        },
        alarms: { create: (n) => alarmes.add(n), clear: (n) => alarmes.delete(n),
          get: (n) => Promise.resolve(alarmes.has(n) ? { name: n } : undefined),
          onAlarm: { addListener: (f) => ouvintes.alarme.push(f) } },
        webNavigation: { onCompleted: { addListener: (f) => ouvintes.nav.push(f) } },
        cookies: { onChanged: { addListener: nada },
          getAll: (q, cb) => cb(q.domain === "idp.transferegov.sistema.gov.br"
            ? [{ name: "JSESSIONID", value: "i1", domain: "idp.transferegov.sistema.gov.br", path: "/", httpOnly: true }] : []) },
        runtime: { onInstalled: { addListener: nada }, onStartup: { addListener: nada },
          onMessage: { addListener: (f) => ouvintes.msg.push(f) } },
        action: { setBadgeText: nada, setBadgeBackgroundColor: nada, setTitle: nada },
      };
      const ctx = {
        console: { log: nada, warn: nada, error: nada },
        chrome: chromeFalso, navigator: { userAgent: "teste" }, URL, Date, JSON, Promise, Set, Map,
        setTimeout: (f) => setTimeout(f, 1),       // o tempo corre depressa aqui
        fetch: async (url, opt) => {
          if (opt && opt.method === "POST") { posts.push(JSON.parse(opt.body)); return { ok: true, status: 200, json: async () => ({ id: 1 }) }; }
          if (String(url).includes("/session-capture/saude")) return { ok: true, status: 200, json: async () => ({}) };
          return { ok: true, status: 200, url, text: async () => "<a>Sair</a> Consultar Proposta" };
        },
      };
      ctx.self = ctx;
      ctx.importScripts = (f) => { if (f === "tokens.local.js") throw new Error("ausente"); vm.runInContext(ler(f), ctx); };
      vm.createContext(ctx);
      vm.runInContext(ler("background.js"), ctx);
      const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
      return { ctx, store, abas, posts, alarmes, ouvintes, esperar,
        clicar: () => ouvintes.msg.forEach((f) => f({ tipo: "captura_completa" }, {}, nada)),
        tick: async () => { for (const f of ouvintes.alarme) f({ name: "pactha_roteiro_tick" }); await esperar(80); } };
    };
    const PORTA = (n) => vm.runInContext(`PORTAS_GOVBR[${n}].url`, montarBg(() => ({})).ctx);
    // Só as capturas DO ROTEIRO (o modo automático também captura a cada navegação).
    const govbrPosts = (bg) => bg.posts.filter((p) => p.automation_key === "govbr"
      && /captura_completa/.test(String(p.url_atual || "")));

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

  console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTUDO OK");
  process.exit(falhas ? 1 : 0);
})();
