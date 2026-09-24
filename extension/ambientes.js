// AMBIENTES — a lista de tenants e o envio da MESMA captura para todos.
//
// ⭐ POR QUE ISTO EXISTE. A extensão guardava UM `pactha_api` e UM
// `pactha_token`. Como cada tenant tem banco e Cofre próprios e não há
// propagação entre eles, capturar a sessão gov.br significava reconfigurar a
// extensão e recapturar CINCO vezes — um ritual que ninguém completa.
//
// Em 02/09/2026 isso cobrou a conta: a sessão caiu, o dono recapturou uma vez, e
// o resultado foi 1 de 5 conectados. Freitas reconectou; trust e montesião
// ficaram em `needs_recapture`; santamaria e novapalma apareceram com "sem
// sessao govbr no Cofre" — NUNCA tinham sido capturados. O novapalma estava no
// ar desde 01/09.
//
// ⚠️ E O MODO DE FALHA ERA SILENCIOSO, que é o que torna isto urgente: capturar
// num ambiente e esquecer os outros não dá erro em lugar nenhum. As coletas
// atrás de login simplesmente param, e o produto leva semanas para reclamar —
// uma sessão já ficou morta 41% de um mês sem nada acusar.
//
// Decisão do dono (02/09/2026): "não faz sentido uma captura para cada um, tem
// que ser uma só".

/* ⚠️ `municipio_id: 0` É O PONTO MAIS IMPORTANTE DESTE ARQUIVO.
 *
 * O ID de município é LOCAL de cada tenant: o `6` do freitas é uma cidade e o
 * `6` do trust é outra. Mandar o mesmo número para os cinco amarraria a sessão
 * a uma cidade diferente em cada banco — e ninguém veria, porque o POST
 * responde 200 do mesmo jeito.
 *
 * O backend trata `None`/`0` como ESCOPO DE INSTÂNCIA (ver
 * `routers/session_capture.py`), e é o escopo correto: a sessão gov.br é do
 * operador, não de um município, e o próprio backend diz que ela "serve
 * cross-mun". Por isso a captura multi-ambiente NUNCA manda id de município. */
const AMBIENTE_ESCOPO_INSTANCIA = 0;

// Os SETE tenants em produção (22/09/2026). O `token` nasce vazio: ele é
// PRÓPRIO de cada ambiente (os service tokens vivem no banco de cada um) e é
// colado pela tela de configuração.
//
// ⚠️ Toda URL aqui precisa casar com `host_permissions` no manifest.json —
// fora dele o Chrome bloqueia o fetch ANTES de sair (MV3) e a captura falha sem
// nunca chegar ao servidor. `https://*.sslip.io/*` cobre os sete.
//
// ⚠️⚠️ CLIENTE NOVO ENTRA AQUI, NO MESMO PR QUE O COLOCA NO DEPLOY. O `bgk`
// entrou no `TENANTS` do build-backend.yml em 08/09/2026 e ficou DE FORA desta
// lista — resultado medido em 09/09: `extensao-captura` com último uso em cinco
// tenants e "nenhum token emitido" no sexto, com o `transferegov_lote` do bgk
// registrando 216 leituras atrás do login sem retorno desde que ele nasceu.
// Cliente pagante sem a fonte federal mais rica, e sem erro em lugar nenhum.
//
// `tests/test_extensao_conhece_os_tenants.py` agora cruza esta lista com o
// `TENANTS` do workflow de deploy e reprova o PR quando as duas divergem. Se
// você chegou aqui por causa daquele teste vermelho: é ele fazendo o trabalho,
// acrescente a linha e siga.
const AMBIENTES_CONHECIDOS = [
  { nome: "Freitas", api: "https://pactha-api-54-232-208-118.sslip.io/api" },
  { nome: "Trust", api: "https://pactha-trust-api-54-232-208-118.sslip.io/api" },
  { nome: "Monte Sião - MG", api: "https://pactha-montesiao-mg-api-54-232-208-118.sslip.io/api" },
  { nome: "Santa Maria - RS", api: "https://pactha-santamaria-rs-api-54-232-208-118.sslip.io/api" },
  { nome: "Nova Palma - RS", api: "https://pactha-novapalma-rs-api-54-232-208-118.sslip.io/api" },
  { nome: "BGK - RS", api: "https://pactha-bgk-rs-api-54-232-208-118.sslip.io/api" },
  { nome: "Juranda - PR", api: "https://pactha-juranda-pr-api-54-232-208-118.sslip.io/api" },
];

/** A lista salva, já migrada do formato antigo.
 *
 * ⚠️ A MIGRAÇÃO NÃO PODE PERDER O TOKEN QUE JÁ FUNCIONAVA. Quem já usa a
 * extensão tem `pactha_api` + `pactha_token` gravados; se a lista nova nascesse
 * vazia, a pessoa abriria o popup e descobriria que a extensão "esqueceu" a
 * configuração — e provavelmente reconfiguraria só um ambiente, que é
 * exatamente o problema que este arquivo veio resolver.
 */
const _norm = (u) => (u || "").replace(/\/+$/, "");

/** Tokens pré-configurados, se o arquivo local existir.
 *
 * ⚠️ `tokens.local.js` NÃO VAI PARA O REPOSITÓRIO (está no .gitignore): ele
 * carrega segredo. É gravado na instalação, por quem emitiu os tokens, para que
 * o operador não tenha de colar nada. A extensão funciona sem ele — os campos
 * simplesmente nascem vazios e a tela pede a colagem, como antes. */
function _tokensLocais() {
  try {
    const g = typeof self !== "undefined" ? self : window;
    return (g && g.PACTHA_TOKENS_LOCAIS) || {};
  } catch (_e) {
    return {};
  }
}

async function lerAmbientes() {
  const dados = await new Promise((res) =>
    chrome.storage.local.get(["pactha_ambientes", "pactha_api", "pactha_token"], res));

  const locais = _tokensLocais();
  const salvos = Array.isArray(dados.pactha_ambientes) ? dados.pactha_ambientes : [];
  const porApi = new Map(salvos.map((a) => [_norm(a.api), a]));

  // ⚠️ RECONCILIA A CADA LEITURA, e não só na primeira vez.
  //
  // Havia aqui um `return dados.pactha_ambientes` que encerrava a função quando
  // a lista salva existia. O efeito: acrescentar um tenant novo a
  // `AMBIENTES_CONHECIDOS` NÃO surtia efeito nenhum em quem já tinha usado a
  // extensão — nem recarregando, porque a lista antiga continuava no storage
  // para sempre. O sexto cliente nasceria fora da captura exatamente como
  // santamaria e novapalma nasceram, e de novo sem erro em lugar nenhum.
  const apiAntiga = _norm(dados.pactha_api);
  const tokenAntigo = dados.pactha_token || "";

  const lista = AMBIENTES_CONHECIDOS.map((conhecido) => {
    const salvo = porApi.get(_norm(conhecido.api));
    // Precedência: o que o operador salvou > o arquivo local > a migração do
    // formato antigo. O que ele digitou na tela nunca é sobrescrito por default.
    const token = (salvo && salvo.token)
      || locais[_norm(conhecido.api)]
      || (apiAntiga && _norm(conhecido.api) === apiAntiga ? tokenAntigo : "")
      || "";
    return {
      ...conhecido,
      token,
      ativo: salvo && salvo.ativo === false ? false : true,
    };
  });

  // Ambientes que o operador acrescentou à mão continuam na lista.
  salvos.forEach((s) => {
    if (!AMBIENTES_CONHECIDOS.some((c) => _norm(c.api) === _norm(s.api))) lista.push(s);
  });
  // API antiga que não é nenhuma das conhecidas (ambiente próprio, teste): não
  // se perde — entra como uma entrada a mais. O segundo teste evita duplicar a
  // entrada que o laço de `salvos` acima já trouxe de volta.
  if (apiAntiga
      && !AMBIENTES_CONHECIDOS.some((a) => _norm(a.api) === apiAntiga)
      && !lista.some((a) => _norm(a.api) === apiAntiga)) {
    lista.push({ nome: "Configurado antes", api: dados.pactha_api, token: tokenAntigo, ativo: true });
  }
  await salvarAmbientes(lista);
  return lista;
}

async function salvarAmbientes(lista) {
  return new Promise((res) => chrome.storage.local.set({ pactha_ambientes: lista }, res));
}

/** Manda o MESMO payload para todos os ambientes com token configurado.
 *
 * Devolve uma linha por ambiente: `{ nome, ok, detalhe }`.
 *
 * ⚠️ NUNCA DEVOLVE UM "OK" ÚNICO, e essa é a regra central. O defeito que este
 * arquivo conserta é justamente o sucesso parcial invisível: três ambientes
 * gravando e dois falhando tem de aparecer como três e dois, nomeados. Um
 * resumo agregado ("enviado!") reproduziria o problema com outra roupa.
 *
 * ⚠️ AMBIENTE SEM TOKEN NÃO É ERRO DE REDE — é configuração faltando, e a
 * mensagem diz isso. Tratar os dois como "falhou" mandaria a pessoa investigar
 * conectividade quando o que falta é colar uma chave.
 */
async function enviarParaTodos(payload, lista) {
  const alvos = (lista || []).filter((a) => a.ativo !== false);
  if (!alvos.length) return [];

  // ⚠️ O `municipio_id` do payload é IGNORADO de propósito — ver o comentário
  // de `AMBIENTE_ESCOPO_INSTANCIA` no topo. Sobrescrever aqui, e não no
  // chamador, garante que nenhuma tela futura consiga reintroduzir o id local.
  const corpo = JSON.stringify({ ...payload, municipio_id: AMBIENTE_ESCOPO_INSTANCIA });

  return Promise.all(alvos.map(async (amb) => {
    if (!amb.token) {
      return { nome: amb.nome, ok: false, detalhe: "sem token configurado" };
    }
    // Token longevo (service token) vai como X-Service-Token — não expira em
    // 60min como o JWT. Aceita os dois prefixos: os antigos usavam `pacta_`
    // (sem H) e cairiam no caminho do Bearer, resultando em 401.
    const ehServiceToken = amb.token.startsWith("pactha_") || amb.token.startsWith("pacta_");
    const auth = ehServiceToken
      ? { "X-Service-Token": amb.token }
      : { Authorization: `Bearer ${amb.token}` };
    try {
      const r = await fetch(`${amb.api}/session-capture`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...auth },
        body: corpo,
      });
      if (r.status === 401) {
        const motivo = await _motivoDoServidor(r);
        return { nome: amb.nome, ok: false, detalhe: "token inválido" + (motivo ? ` (${motivo})` : "") };
      }
      if (!r.ok) return { nome: amb.nome, ok: false, detalhe: `HTTP ${r.status}` };
      const d = await r.json().catch(() => ({}));
      // "candidata": o servidor está com a sessão VIVA e não a trocou às cegas;
      // o worker testa este jar e só o promove se autenticar.
      if (d.status === "candidata") {
        return { nome: amb.nome, ok: true, detalhe: "sessão viva preservada (captura em teste)" };
      }
      return { nome: amb.nome, ok: true, detalhe: d.id ? `id=${d.id}` : "gravado" };
    } catch (e) {
      // ⚠️ "Failed to fetch" aqui quase sempre é host_permissions, e não rede:
      // o Chrome bloqueia o fetch antes de sair e a mensagem não diz isso.
      const msg = String(e && e.message || e);
      return {
        nome: amb.nome, ok: false,
        detalhe: /failed to fetch/i.test(msg)
          ? "bloqueado (confira host_permissions no manifest)"
          : msg.slice(0, 60),
      };
    }
  }));
}

/**
 * AS QUATRO PORTAS DA CAPTURA COMPLETA. Cada uma é uma sessão SEPARADA no
 * TransfereGov (SP SAML próprio): logar só na primeira deixa as outras três
 * fora do jar, e o servidor não as revive sozinho.
 *
 * ⚠️ SÃO AS MESMAS URLs de `backend/ingestion/govbr_renew.py` (ENTRY,
 * PRIVATE_ENTRY, EXEC_ENTRY, PRESTACAO_ENTRY) — o servidor mantém viva a sessão
 * que NASCEU aqui. `tests/test_sessao_govbr_guardas.py` cruza as duas listas.
 */
const PORTAS_GOVBR = [
  { nome: "1. Login (faça o login gov.br aqui)",
    url: "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do" },
  { nome: "2. Mandatárias /private/",
    url: "https://mandatarias.transferegov.sistema.gov.br/projeto-basico/private/index.jsf" },
  { nome: "3. Execução (licitações)",
    url: "https://discricionarias.transferegov.sistema.gov.br/voluntarias/execucao/ListarLicitacoes/ListarLicitacoes.do?destino=ListarLicitacoes" },
  { nome: "4. Prestação (notas de empenho)",
    url: "https://discricionarias.transferegov.sistema.gov.br/voluntarias/prestacao/_proposta/empenho/listarEmpenhosNovoSiafi.jsf?destino=ManterEmpenhoNovoSiafi" },
];

/** A URL final é a tela de login do gov.br? (o fetch SEGUE o redirect e a tela
 *  de login responde 200 — `r.ok` sozinho dizia "sessão viva" com ela morta.) */
function pareceLogin(url) {
  const u = String(url || "").toLowerCase();
  return u.includes("sso.acesso.gov.br") || u.includes("/idp/") || u.includes("acesso.gov.br/login");
}

/* ⭐ SAI DO "ACESSO LIVRE" (medido em 24/09/2026 no Chrome do dono). No modo
   visitante a porta 1 NÃO redireciona para o login: responde 200 com a página de
   visitante ("Transferegov - Consultar Proposta - Acesso Livre"), então o roteiro
   abria as 4 portas, nunca aparecia tela de login, e a captura final era barrada
   (corretamente) sem a pessoa saber o que fazer. O link "Sair do Acesso Livre" da
   própria página é este endereço; ele cai em idp.transferegov…/idp/ ("Login do
   Transferegov"), onde o certo é «Entrar com gov.br» — o link «Acesso livre» logo
   abaixo (www.gov.br/transferegov/…/acesso-livre) devolve ao modo visitante. */
const LLO_URL = "https://discricionarias.transferegov.sistema.gov.br/voluntarias?LLO=true";

/** O TÍTULO da aba diz "Acesso Livre"? (o roteiro lê `tab.title`, permissão "tabs"). */
function tituloEhAcessoLivre(titulo) {
  return /acesso livre/i.test(String(titulo || ""));
}

/** O HTML é a página de VISITANTE? Só marcadores PRECISOS, medidos em 24/09/2026:
 *  o `<title>` com "Acesso Livre", ou o `<span class="exit">` cujo texto começa por
 *  "Sair do Acesso Livre" (dentro de `<div id="info">`).
 *
 *  ⚠️ A FRASE SOLTA NÃO CONTA. A versão 2.4.4 barrava com "sair do acesso livre" em
 *  QUALQUER lugar do HTML cru — e página logada pode ter texto escondido (já
 *  aconteceu com "Acesso Restrito" e `SAMLRequest`, ver `corpoEhLogin`). Página
 *  logada tomada por visitante = a captura boa barrada para sempre, em silêncio, e
 *  o roteiro mandando a aba para o LLO. Por isso comentário, `<script>`, `<style>`
 *  e `<template>` saem ANTES de procurar. (Como é a página LOGADA não foi medido;
 *  hipótese: o título sem "Acesso Livre" e o span.exit dizendo só "Sair".) */
function corpoEhAcessoLivre(html) {
  const t = String(html || "")
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<(script|style|template)\b[\s\S]*?<\/\1\s*>/gi, " ");
  const titulo = /<title\b[^>]*>([\s\S]*?)<\/title\s*>/i.exec(t);
  if (titulo && /acesso\s+livre/i.test(titulo[1])) return true;
  return /<span\b[^>]*\bclass\s*=\s*["'](?:[^"']*\s)?exit(?:\s[^"']*)?["'][^>]*>\s*Sair\s+do\s+Acesso\s+Livre/i.test(t);
}

/** O CORPO é a página de "HTTP Post Binding" do SAML (ou a tela de login)?
 *
 * ⚠️ A URL SOZINHA NÃO BASTA. O TransfereGov deslogado nem sempre redireciona:
 * ele pode responder 200 NA PRÓPRIA URL com um formulário que o JavaScript
 * auto-envia para o idp. `fetch` não roda JS, então `r.url` continua sendo a do
 * TransfereGov e `pareceLogin(r.url)` diz "logado". (É o mesmo muro de 3469
 * bytes que o backend conhece — `transferegov._eh_muro_saml`.) */
function corpoEhLogin(texto) {
  const t = String(texto || "");
  /* ⚠️ ASSINATURA MEDIDA, não palavra solta. O muro (medido em 23/09/2026:
     3.469 bytes) é `<TITLE>HTTP Post Binding (Request)` + `<FORM METHOD="POST"
     ACTION="https://idp.transferegov.../idp/"` + `<INPUT NAME="SAMLRequest">`.
     A versão anterior barrava com QUALQUER "SAMLRequest"/"acesso restrito" no
     HTML cru — e uma página LOGADA pode ter os dois escondidos (o link "Sair" do
     SAML leva `SAMLRequest=` na URL; o menu tem "Acesso Restrito" oculto, que o
     innerText do servidor não vê mas o fetch daqui vê). Resultado: a captura
     boa barrada para sempre, em silêncio. */
  /* ⚠️ VISITANTE NÃO É LOGIN (23/09/2026, visto no Chrome do dono). O TransfereGov
     tem o modo "Acesso Livre": a página abre, e tem um botão "Sair do Acesso
     Livre" — o "Sair" que servia de prova de login. Tratado como logado, o jar de
     VISITANTE sairia para os servidores e, pela mesma régua no servidor, seria
     promovido por cima da sessão boa. Pelos marcadores precisos de
     `corpoEhAcessoLivre` (2.4.5), não pela frase solta no HTML cru. */
  if (corpoEhAcessoLivre(t)) return true;
  if (/<title>\s*HTTP Post Binding/i.test(t)) return true;
  const formIdp = /<form[^>]*action=["'][^"']*(\/idp\/|idp\.transferegov|sso\.acesso)[^"']*["']/i.test(t);
  const inputSaml = /<input[^>]*name=["']SAMLRequest["']/i.test(t);
  if (formIdp && inputSaml) return true;
  return /identifique-se no gov\.br|<title>[^<]*identifique-se/i.test(t);
}

/**
 * Veredito da sonda: true (logado) | false (deslogado) | null (não sei).
 *
 * Mesma régua do servidor (`govbr_renew._is_authenticated`): logado é PROVA
 * POSITIVA — a página tem o "Sair". Deslogado é a ASSINATURA do muro/tela de
 * login (`corpoEhLogin`). Sem nenhum dos dois (layout mudou, portal devolveu
 * erro) o veredito é `null`, e `null` NÃO barra captura: o servidor tem a guarda
 * dele (sessão viva → vira candidata), e travar aqui por dúvida impediria
 * justamente a recaptura.
 */
function vereditoLogin(url, corpo) {
  return estadoLogin(url, corpo).valor;
}

/** O veredito com o MOTIVO: `{ valor, motivo }`, motivo 'logado' | 'visitante' |
 *  'login' | 'nao_sei'. O motivo existe porque as duas recusas pedem ações
 *  diferentes: deslogado → fazer o login; visitante → SAIR do Acesso Livre antes
 *  (nesse modo o TransfereGov nunca pede login, e "faça o login" não diz onde). */
function estadoLogin(url, corpo) {
  if (pareceLogin(url)) return { valor: false, motivo: "login" };
  if (corpoEhAcessoLivre(corpo)) return { valor: false, motivo: "visitante" };
  if (corpoEhLogin(corpo)) return { valor: false, motivo: "login" };
  if (/\bsair\b/i.test(String(corpo || ""))) return { valor: true, motivo: "logado" };
  return { valor: null, motivo: "nao_sei" };
}

let _sondaCache = { em: 0, valor: null };

/**
 * O Chrome está LOGADO no TransfereGov? É o PORTEIRO de toda captura `govbr`:
 * navegação, cookie trocado, alarme e captura manual passam por aqui. Antes,
 * qualquer página do TransfereGov aberta deslogada ("Acesso Livre", a página de
 * auto-envio do SAML, o Chrome reaberto sem os cookies de sessão) mandava um jar
 * SEM login para os seis servidores.
 *
 * Sonda a porta 1 (a mesma URL que o servidor usa para medir o login). Só o
 * `true` fica guardado (5s — um login dispara vários gatilhos em sequência):
 * guardar o `false` descartaria a captura BOA que chega 2s depois da página de
 * auto-envio do SAML, no meio de um login.
 */
async function chromeEstadoLogin() {
  const agora = Date.now();
  if (_sondaCache.valor === true && agora - _sondaCache.em < 5000) return { valor: true, motivo: "logado" };
  let estado = { valor: null, motivo: "nao_sei" };
  try {
    const r = await fetch(PORTAS_GOVBR[0].url, { method: "GET", credentials: "include", cache: "no-store" });
    if (r.ok) estado = estadoLogin(r.url, await r.text());
  } catch (_) { estado = { valor: null, motivo: "nao_sei" }; }
  _sondaCache = { em: agora, valor: estado.valor };
  return estado;
}

/** Só o valor (true | false | null) — os chamadores antigos continuam valendo. */
async function chromeEstaLogado() {
  return (await chromeEstadoLogin()).valor;
}

/** O MOTIVO que o servidor deu para recusar (`{"detail": "..."}` do FastAPI), ou "".
 *  Sem ele o popup só dizia "HTTP 401" — e o Juranda ficou assim (23–24/09/2026)
 *  sem dizer se o token era errado, revogado ou expirado. */
async function _motivoDoServidor(r) {
  try {
    const d = await r.json();
    return d && typeof d.detail === "string" ? d.detail.slice(0, 120) : "";
  } catch (_) {
    return "";
  }
}

/**
 * Pergunta a CADA ambiente como está a sessão gov.br DO SERVIDOR.
 *
 * ⚠️ POR QUE ISTO EXISTE: "capturei" não é "o servidor está com a sessão viva".
 * O vigia avisa no Telegram desde 16/09/2026 e a sessão ficou morta mais quatro
 * dias mesmo assim — o aviso precisa chegar AQUI, no Chrome, que é onde se
 * resolve. Devolve um item por ambiente; nunca rejeita (mesma disciplina de
 * `enviarParaTodos`).
 */
async function consultarSaude(lista) {
  const alvos = (lista || []).filter((a) => a.ativo !== false && a.token);
  return Promise.all(alvos.map(async (amb) => {
    const ehServiceToken = amb.token.startsWith("pactha_") || amb.token.startsWith("pacta_");
    const auth = ehServiceToken
      ? { "X-Service-Token": amb.token }
      : { Authorization: `Bearer ${amb.token}` };
    try {
      const r = await fetch(`${amb.api}/session-capture/saude`, { headers: auth, cache: "no-store" });
      // 404 = servidor ainda sem esta rota (deploy antigo): não é "caiu".
      // O motivo do servidor vai junto ("HTTP 401 — Token inválido ou revogado"):
      // é ele que diz se o caso é colar outro token ou esperar o deploy.
      if (!r.ok) {
        const motivo = await _motivoDoServidor(r);
        return { nome: amb.nome, ok: false, status: r.status,
          detalhe: `HTTP ${r.status}` + (motivo ? ` — ${motivo}` : "") };
      }
      const d = await r.json().catch(() => ({}));
      return {
        nome: amb.nome, ok: true,
        login: d.login || "sem_medicao",
        precisa_recapturar: d.precisa_recapturar === true,
        modulos: d.modulos || "",
        candidata_pendente: d.candidata_pendente === true,
        medido_ha_min: d.login_medido_ha_min,
        // vencimento PREVISTO (padrão medido ~24h a partir do login) — o aviso
        // que chega ANTES de cair; servidor antigo não manda e fica null.
        login_em: d.login_em || null,
        login_ha_h: typeof d.login_ha_h === "number" ? d.login_ha_h : null,
        vence_previsto_em: d.vence_previsto_em || null,
        vence_em_h: typeof d.vence_em_h === "number" ? d.vence_em_h : null,
        vencendo: d.vencendo === true,
      };
    } catch (e) {
      return { nome: amb.nome, ok: false, detalhe: String(e && e.message || e).slice(0, 60) };
    }
  }));
}

/** Algum ambiente MEDIU que o login caiu? Falha de rede/404 não conta. */
function algumPrecisaRecapturar(itens) {
  return (itens || []).some((i) => i.ok && i.precisa_recapturar);
}

/** Algum servidor diz que o login VIVO está para vencer (janela de aviso)? */
function algumVencendo(itens) {
  return (itens || []).some((i) => i.ok && i.vencendo === true);
}

/** "login há 22h · vence ~09:27 (em 2,4h)" — hora local do Chrome; "" sem previsão.
 *  A HORA vem do servidor (`vence_previsto_em`), nunca de um 24h fixo aqui: o teto
 *  é padrão medido e vai ser recalibrado no servidor; duas contas divergiriam. */
function textoVencimento(i) {
  if (!i || i.vence_em_h == null || !i.vence_previsto_em) return "";
  const vence = new Date(Date.parse(i.vence_previsto_em));
  if (isNaN(vence.getTime())) return "";
  const hh = String(vence.getHours()).padStart(2, "0") + ":" + String(vence.getMinutes()).padStart(2, "0");
  const em = i.vence_em_h >= 0 ? `em ${i.vence_em_h.toFixed(1).replace(".", ",")}h` : "já passou do previsto";
  return `login há ${(i.login_ha_h || 0).toFixed(0)}h · vence ~${hh} (${em})`;
}

/** "3 de 5 ambientes" — o resumo que acompanha a lista, nunca a substitui. */
function resumoEnvio(resultados) {
  const ok = resultados.filter((r) => r.ok).length;
  return `${ok} de ${resultados.length} ambiente(s)`;
}
