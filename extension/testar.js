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

  console.log(falhas ? `\n${falhas} FALHA(S)` : "\nTUDO OK");
  process.exit(falhas ? 1 : 0);
})();
