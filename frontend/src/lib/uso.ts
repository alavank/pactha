// TELEMETRIA DE USO — o coletor do lado do navegador.
//
// ⚠️ NAO confunda com a trilha de auditoria. A trilha guarda ATO CONSEQUENTE
// (login, exportar, revelar senha, conceder permissao) e serve de prova; isto
// guarda NAVEGACAO e serve para entender o uso. Sao tabelas, telas e propositos
// separados — ver backend/routers/uso.py.
//
// Tres regras que valem para o arquivo inteiro:
//   1. TODA falha e no-op. Metrica nao pode quebrar nem atrasar o trabalho.
//   2. O relogio e do SERVIDOR. Daqui sai "ha quantos ms", nunca um horario.
//   3. Nada de texto que a pessoa digitou. Chave de filtro sim, conteudo nao.
//
// ⭐ A CAPTURA E GENERICA (pedido do dono, 28/08/2026: "fulano abriu x, filtrou
// isso, selecionou tal aba, gerou tal relatorio"). Em vez de instrumentar 48
// telas uma a uma — que e o caminho em que a tela nova nasce cega —, o coletor
// ouve TRES fontes que toda tela ja produz sem saber:
//   · o DOM: clique em botao, aba, opcao, item de lista (o rotulo visivel e o
//     alvo — e rotulo de botao e texto NOSSO, nunca texto digitado);
//   · as CONSULTAS a API: os parametros de um GET sao o filtro aplicado, em
//     qualquer tela, com ou sem filtro na URL;
//   · as ESCRITAS na API: um POST/PUT/DELETE que deu certo e "fez tal
//     alteracao" — a intencao vem do clique, o fato vem daqui.
// Quem quiser dizer algo melhor que o generico marca `data-uso="detalhe"` e
// `data-uso-alvo="..."` no elemento (ver components/ui/superficies.tsx).

/** ⚠️ CLIENTE HTTP PROPRIO, e esta e a decisao mais importante do arquivo.
 *
 *  NAO usar a instancia `api` de lib/api.ts, por tres razoes independentes:
 *
 *  1. O interceptor dela joga o usuario no /login: um 401 dispara `tryRefresh()`
 *     e, falhando, limpa o localStorage e navega. Um flush de fundo passaria a
 *     ser a primeira coisa a descobrir sessao morta — e ejetaria alguem do meio
 *     de um formulario da Gestao Interna por causa de uma metrica.
 *  2. Renovacao eterna: o interceptor renova o token no 401, entao uma aba
 *     esquecida na recepcao da prefeitura bateria a cada 45s e renovaria para
 *     sempre. O access token de 60 minutos — reduzido de propósito, de 480 —
 *     viraria sessao de 30 dias. A telemetria teria desfeito uma decisao de
 *     seguranca sem ninguem decidir isso.
 *  3. Corrida de refresh entre abas: o backend rotaciona e revoga o refresh
 *     antigo; N abas batendo na virada da hora geram N refreshes simultaneos, e
 *     a perdedora vai para o /login.
 *
 *  E `navigator.sendBeacon` esta PROIBIDO: o backend exige o cabecalho
 *  `X-CSRF-Token` em todo POST autenticado por cookie, e o beacon nao manda
 *  cabecalho — o flush de saida tomaria 403 em silencio, para sempre.
 *  `fetch(..., {keepalive:true})` manda cabecalho e sobrevive ao fechar da aba. */
const ENDPOINT = "/api/uso/lote";

const INTERVALO_MS = 45_000;
const TETO_FILA = 200;      // acima disso, descarta os MAIS ANTIGOS
const LOTE_MAX = 50;        // dispara o envio antes do tempo
const OCIOSO_APOS_MS = 5 * 60_000;
/** Rotulo de botao/aba: o que cabe numa linha da tela de Telemetria. */
const TEXTO_MAX = 80;
/** Dois cliques iguais em menos disto sao UM gesto (duplo clique, botao que
 *  re-renderiza e recebe o evento de novo). */
const DEDUPE_MS = 800;

export type AcaoUso =
  | "ver" | "detalhe" | "filtrar" | "buscar" | "exportar" | "gerar"
  | "perguntar" | "acionar" | "sair"
  | "aba" | "selecionar" | "alterar" | "trocar" | "abrir";

export interface EventoUso {
  tela: string;
  /** Rota crua. Guardada ALEM da tela porque `hrefToTela` funde as sete rotas
   *  transferegov* numa chave so — e a diferenca entre Voluntarias, PAC e
   *  Rejeitadas e exatamente a pergunta "o que acessam mais". */
  rota?: string;
  acao: AcaoUso;
  alvo?: string;
  ms?: number;
  municipio_id?: number | null;
  detalhe?: Record<string, unknown>;
}

interface NaFila extends EventoUso { em: number }

// ⚠️ ESCOPO DE MODULO, nunca useState nem context: o layout do dashboard
// remonta a arvore inteira com `key={escopo}` a cada troca de municipio, e uma
// fila em estado do React perderia tudo justamente no gesto mais interessante
// de medir.
let fila: NaFila[] = [];
let sid = "";
let ligado = true;
let falhas = 0;
let ultimaAtividade = Date.now();
let temporizador: ReturnType<typeof setInterval> | null = null;
/** Os ouvintes de DOM sao montados UMA vez por vida da pagina. `iniciarSessao`
 *  roda de novo a cada login (sair e entrar e navegacao do Next, nao recarga),
 *  e montar de novo faria cada clique virar dois eventos. */
let ouvintesMontados = false;
/** Tomou 401: o access token venceu e ninguem renovou ainda (o refresh e do
 *  cliente `api`, no proximo gesto real). Pausa ate a pessoa mexer de novo —
 *  em vez de contar como falha e DESLIGAR a telemetria pelo resto da aba, que
 *  era o que acontecia com quem deixava a tela parada por uma hora. */
let pausadoPor401 = false;
let ultimoClique: { chave: string; em: number } = { chave: "", em: 0 };
/** Ultimos parametros vistos por caminho de API: so a MUDANCA de filtro vira
 *  evento — a mesma consulta repetida (poll, F5) nao. */
const ultimaConsulta = new Map<string, string>();

/** Quem esta online, como o servidor respondeu no ultimo flush. A presenca
 *  pega carona na resposta do lote: zero requisicao nova. */
export interface Presente { nome: string; email: string; desde: string | null; tela: string | null }
let presentes: Presente[] = [];
/** Diferenca entre o relogio do servidor e o desta maquina. Um desktop de
 *  prefeitura com a hora 3h adiantada exibiria "online ha -3h" e o widget
 *  perderia a credibilidade na primeira conferencia. */
let desvioRelogioMs = 0;
const ouvintes = new Set<() => void>();

export function assinarPresenca(f: () => void) {
  ouvintes.add(f);
  return () => { ouvintes.delete(f); };
}
export function presencaAtual() {
  return { presentes, desvioRelogioMs };
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|;\s*)pactha_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

/** TV e celular publico nao coletam NADA.
 *
 *  E a maior economia do desenho: a tela de quiosque consulta sozinha a cada
 *  10 segundos, 24 horas por dia. Sem esta saida, uma TV de parede geraria mais
 *  eventos que todo o time humano do cliente — e o ranking de "quem mais usa o
 *  sistema" responderia "a televisao da recepcao, 720 horas logada". */
function ehQuiosque(): boolean {
  if (typeof window === "undefined") return true;
  const p = window.location.pathname;
  return p.startsWith("/t/") || p.startsWith("/m/") || p === "/tela";
}

function disponivel(): boolean {
  return (
    typeof window !== "undefined" &&
    ligado &&
    !ehQuiosque() &&
    process.env.NEXT_PUBLIC_TELEMETRIA !== "0"
  );
}

export function registrar(e: EventoUso) {
  if (!disponivel()) return;
  fila.push({ ...e, em: Date.now() });
  if (fila.length > TETO_FILA) fila = fila.slice(-TETO_FILA);
  if (fila.length >= LOTE_MAX) void enviar("cheio");
}

/** Ativo = houve clique, tecla ou rolagem nos ultimos 5 minutos E a aba esta
 *  visivel. Aba escondida NUNCA conta como ativa: o notebook aberto no PACTHA
 *  durante uma reuniao nao e uso do sistema. */
function estaAtivo(): boolean {
  if (typeof document !== "undefined" && document.visibilityState !== "visible") return false;
  return Date.now() - ultimaAtividade < OCIOSO_APOS_MS;
}

export async function enviar(motivo: string, encerrar?: "logout" | "aba_fechada") {
  if (!disponivel()) return;
  // Em pausa por token vencido: segura a fila ate a pessoa mexer de novo. A
  // despedida (logout/aba fechada) tenta mesmo assim — e a ultima chance.
  if (pausadoPor401 && !encerrar) return;
  const lote = fila;
  fila = [];
  const agora = Date.now();
  const corpo = {
    // `sid` NAO vai daqui: o servidor le do token, pelo mesmo caminho que a
    // trilha usa. Sessao que o navegador escolhe nao serve de agrupamento.
    sessao: {
      ativo: estaAtivo(),
      tela: typeof window !== "undefined" ? telaDaRota(window.location.pathname) : null,
      encerrar: encerrar ?? null,
    },
    eventos: lote.map((e) => ({
      ha_ms: Math.max(0, agora - e.em),
      tela: e.tela, rota: e.rota ?? null, acao: e.acao,
      alvo: e.alvo ?? null, ms: e.ms ?? null,
      municipio_id: e.municipio_id ?? null, detalhe: e.detalhe ?? null,
    })),
  };
  try {
    const r = await fetch(ENDPOINT, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf() },
      body: JSON.stringify(corpo),
    });
    if (r.status === 401) {
      // Token vencido, nao defeito: devolve os eventos a fila (limitada) e
      // espera o proximo gesto — o cliente `api` renova o cookie na proxima
      // chamada real, e o lote seguinte entra com tudo.
      pausadoPor401 = true;
      fila = [...lote, ...fila].slice(-TETO_FILA);
      return;
    }
    if (!r.ok) throw new Error(String(r.status));
    falhas = 0;
    // O backend responde 204 no lote; a presenca vem de uma leitura propria,
    // disparada so por quem tem permissao (ver PresencaChip).
  } catch {
    // Desliga sozinho depois de 3 falhas seguidas: se o endpoint nao existe
    // (frontend novo contra API velha — o CI tem filtro de paths e isso
    // ACONTECE), nao adianta insistir a cada 45s pelo resto da sessao.
    falhas += 1;
    if (falhas >= 3) ligado = false;
    void motivo;
  }
}

/** A chave de tela a partir do caminho. Espelha `hrefToTela` de lib/telas.ts —
 *  duplicado de proposito para este arquivo nao importar o catalogo inteiro num
 *  caminho que roda a cada 45 segundos. */
export function telaDaRota(pathname: string): string {
  const seg = pathname.replace(/^\/dashboard\/?/, "").split("/")[0] || "dashboard";
  return seg.startsWith("transferegov") ? "transferegov" : seg;
}

// ---------------------------------------------------------------------------
// A CAPTURA GENERICA
// ---------------------------------------------------------------------------

/** O municipio aberto, do mesmo lugar em que o MunicipioContext o guarda. Lido
 *  aqui e nao recebido por props porque este arquivo nao vive na arvore do
 *  React. */
function municipioAtual(): number | null {
  try {
    const v = localStorage.getItem("pactha_last_municipio_id");
    const n = v ? Number(v) : NaN;
    return Number.isFinite(n) ? n : null;
  } catch { return null; }
}

function limparTexto(s: string | null | undefined): string {
  return (s || "").replace(/\s+/g, " ").trim().slice(0, TEXTO_MAX);
}

/** O rotulo VISIVEL de um elemento — o que a pessoa leu antes de clicar.
 *  Texto de botao e copy nossa, nunca conteudo digitado. */
function textoDe(el: Element): string {
  const explicito = (el as HTMLElement).dataset?.usoAlvo;
  if (explicito) return limparTexto(explicito);
  const titulo = el.querySelector<HTMLElement>("[data-uso-titulo]");
  if (titulo) return limparTexto(titulo.textContent);
  return limparTexto(el.textContent)
    || limparTexto(el.getAttribute("aria-label"))
    || limparTexto(el.getAttribute("title"));
}

/** O nome de um CAMPO de formulario (select, caixa): o <label> dele, ou o
 *  aria-label. Sem nome, o evento nao diz nada e e descartado. */
function rotuloDoCampo(el: HTMLElement): string {
  const aria = el.getAttribute("aria-label");
  if (aria) return limparTexto(aria);
  const id = el.getAttribute("id");
  if (id) {
    const lab = document.querySelector<HTMLElement>(`label[for="${CSS.escape(id)}"]`);
    if (lab) return limparTexto(lab.textContent);
  }
  const envolto = el.closest("label");
  if (envolto) return limparTexto(envolto.textContent);
  return "";
}

/** O verbo de um botao pelo que esta escrito nele. Generico de proposito: o
 *  FATO ("gerou um relatorio") vem da escrita na API; aqui e a intencao. */
function acaoDoBotao(texto: string): AcaoUso {
  const t = texto.toLowerCase();
  if (/exportar|pdf|excel|csv|baixar|download|imprimir/.test(t)) return "exportar";
  if (/\bgerar|emitir/.test(t)) return "gerar";
  if (/pesquisar|buscar|filtrar|aplicar filtro|limpar filtro/.test(t)) return "filtrar";
  if (/perguntar/.test(t)) return "perguntar";
  return "acionar";
}

function contextoDaTela() {
  const rota = window.location.pathname;
  return { tela: telaDaRota(rota), rota, municipio_id: municipioAtual() };
}

function aoClicar(ev: MouseEvent) {
  try {
    const origem = ev.target;
    if (!(origem instanceof Element)) return;
    // Campo de texto, area de edicao e o que a tela marcou como privado: fora.
    if (origem.closest("[data-uso-ignorar], input, textarea, select, [contenteditable='true']")) return;
    const el = origem.closest<HTMLElement>(
      "[data-uso], [role='tab'], [role='option'], [role='menuitem'], button, a[href], summary, [role='button']",
    );
    if (!el) return;

    const texto = textoDe(el);
    const explicito = el.dataset.uso as AcaoUso | undefined;
    const papel = el.getAttribute("role");
    let acao: AcaoUso;
    let detalhe: Record<string, unknown> = { tipo: papel || el.tagName.toLowerCase() };

    if (explicito) {
      acao = explicito;
    } else if (papel === "tab") {
      acao = "aba";
    } else if (papel === "option") {
      // Opcao de um MultiSelect: o grupo diz de que filtro e ("Anos", "Situacao").
      const grupo = el.closest<HTMLElement>("[data-uso-grupo]")?.dataset.usoGrupo;
      acao = "filtrar";
      detalhe = { ...detalhe, grupo: grupo || undefined,
                  marcado: el.getAttribute("aria-selected") !== "true" };
    } else if (el.tagName === "A") {
      const href = (el as HTMLAnchorElement).href;
      let externo = false;
      try { externo = !!href && new URL(href).origin !== window.location.origin; } catch { /* href invalido */ }
      // Link interno vira `ver` pela mudanca de rota; registrar aqui dobraria.
      if (!externo) return;
      acao = "abrir";
      try { detalhe = { ...detalhe, site: new URL(href).host }; } catch { /* ignora */ }
    } else if (el.tagName === "SUMMARY") {
      acao = "detalhe";
    } else {
      // Botao dentro de um MultiSelect ("Todos", "Marcar tudo", atalho): filtro.
      const grupo = el.closest<HTMLElement>("[data-uso-grupo]")?.dataset.usoGrupo;
      if (grupo) {
        acao = "filtrar";
        detalhe = { ...detalhe, grupo };
      } else {
        acao = acaoDoBotao(texto);
      }
    }
    // Botao so com icone e sem aria-label: nao ha o que contar. E "Sair" tem
    // o proprio registro (o fim da sessao, com motivo).
    if (!texto || /^sair( do sistema)?$/i.test(texto)) return;

    const chave = `${acao}|${texto}`;
    const agora = Date.now();
    if (ultimoClique.chave === chave && agora - ultimoClique.em < DEDUPE_MS) return;
    ultimoClique = { chave, em: agora };

    registrar({ ...contextoDaTela(), acao, alvo: texto, detalhe });
  } catch { /* metrica nunca quebra a tela */ }
}

function aoMudar(ev: Event) {
  try {
    const el = ev.target;
    if (!(el instanceof HTMLElement) || el.closest("[data-uso-ignorar]")) return;
    if (el instanceof HTMLSelectElement) {
      const nome = rotuloDoCampo(el);
      if (!nome) return;
      const opcao = el.selectedOptions[0];
      registrar({ ...contextoDaTela(), acao: "filtrar", alvo: nome,
                  detalhe: { tipo: "select", valor: limparTexto(opcao?.text).slice(0, 60) } });
    } else if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) {
      const nome = rotuloDoCampo(el);
      if (!nome) return;
      registrar({ ...contextoDaTela(), acao: "selecionar", alvo: nome,
                  detalhe: { tipo: el.type, marcado: el.checked } });
    }
    // Campo de texto: NADA. Regra 3.
  } catch { /* idem */ }
}

/** Chaves que carregam TEXTO DIGITADO: o valor vira "…" — fica registrado que
 *  houve busca, nunca o que foi buscado. */
const CHAVES_DE_TEXTO = /^(q|busca|termo|texto|palavra|search|query|pesquisa|nome|razao|objeto)$/i;
/** Chaves que sao mecanica de paginacao/escopo, nao escolha do usuario.
 *  `live` e `aba` sao do Painel de Indicadores: `live=false` e o cache do
 *  overview, e a aba ja entra pelo clique nela (role=tab) — como parametro
 *  virava "filtrou Painel: aba: geral" a cada abertura. */
const CHAVES_IGNORADAS = new Set([
  "municipio_id", "page", "per_page", "page_size", "limit", "offset", "skip",
  "_t", "ts", "live", "aba", "scope",
]);

function paramsRelevantes(params: unknown): Record<string, string> | null {
  if (!params || typeof params !== "object") return null;
  const out: Record<string, string> = {};
  let n = 0;
  for (const [k, v] of Object.entries(params as Record<string, unknown>)) {
    if (CHAVES_IGNORADAS.has(k) || v == null || v === "" || (Array.isArray(v) && v.length === 0)) continue;
    if (n >= 8) break;
    const texto = Array.isArray(v) ? v.map(String).join(", ") : String(v);
    out[k] = CHAVES_DE_TEXTO.test(k) ? "…" : texto.slice(0, 60);
    n += 1;
  }
  return n ? out : null;
}

/** Caminho da API sem host, sem `/api` e sem query — o que se le na tela. */
function caminhoDaApi(url: string): string {
  let c = url;
  try { c = new URL(url, window.location.origin).pathname; } catch { /* relativo */ }
  return c.replace(/^\/api(?=\/)/, "").split("?")[0];
}

/** O verbo de uma ESCRITA, pelo caminho. O fato consequente e o mesmo em toda
 *  tela: "gerou" (relatorio, documento), "perguntou" (IA), "exportou" ou, no
 *  resto, "alterou" — e a tela de Telemetria traduz o caminho em portugues. */
function acaoDaEscrita(metodo: string, caminho: string): AcaoUso {
  if (/^\/ai(\/|$)/.test(caminho)) return "perguntar";
  if (/pdf|export|exportar|download/.test(caminho)) return "exportar";
  if (metodo === "POST" && /^\/(rm|documentos)(\/|$)/.test(caminho)) return "gerar";
  return "alterar";
}

/** Chamado pelo cliente `api` (lib/api.ts) em toda resposta que deu certo.
 *
 *  GET com parametros = FILTRO aplicado (so quando os parametros MUDAM para
 *  aquele caminho — poll e recarga nao contam). POST/PUT/PATCH/DELETE = a
 *  pessoa GRAVOU algo, e este e o unico sinal confiavel de "fez tal alteracao":
 *  o clique diz a intencao, a resposta 2xx diz que aconteceu. */
export function observarResposta(metodo: string | undefined, url: string | undefined,
                                 params: unknown, status: number) {
  try {
    if (!disponivel() || !metodo || !url) return;
    const caminho = caminhoDaApi(url);
    // A propria telemetria, a sessao, o que o layout busca a cada abertura e
    // o que o Painel grava SOZINHO (os filtros da TV, salvos 600ms depois de
    // qualquer render): mecanica do sistema, nao gesto de ninguem.
    if (/^\/(uso|auth|municipios|users\/me|bi\/tela-filtros|bi\/tela-pub)(\/|$)/.test(caminho)) return;
    const m = metodo.toUpperCase();
    if (m === "GET") {
      const p = paramsRelevantes(params);
      if (!p) return;
      const chave = JSON.stringify(p);
      if (ultimaConsulta.get(caminho) === chave) return;
      ultimaConsulta.set(caminho, chave);
      registrar({ ...contextoDaTela(), acao: "filtrar", alvo: caminho,
                  detalhe: { tipo: "consulta", params: p } });
      return;
    }
    if (!["POST", "PUT", "PATCH", "DELETE"].includes(m)) return;
    registrar({ ...contextoDaTela(), acao: acaoDaEscrita(m, caminho),
                alvo: `${m} ${caminho}`, detalhe: { tipo: "escrita", status } });
  } catch { /* idem */ }
}

function montarOuvintes() {
  if (ouvintesMontados) return;
  ouvintesMontados = true;
  const toque = () => { ultimaAtividade = Date.now(); pausadoPor401 = false; };
  // `passive` e gravando num ref de modulo, nunca em estado: sao eventos de
  // altissima frequencia e um setState aqui re-renderizaria o app inteiro.
  window.addEventListener("click", toque, { passive: true });
  window.addEventListener("keydown", toque, { passive: true });
  window.addEventListener("scroll", toque, { passive: true });
  // Fase de CAPTURA: chega antes de qualquer `stopPropagation` da tela, e antes
  // de o React desmontar o botao que abriu um modal.
  document.addEventListener("click", aoClicar, { capture: true, passive: true });
  document.addEventListener("change", aoMudar, { capture: true, passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void enviar("escondeu");
  });
  // `pagehide` e nao `beforeunload`: o segundo nao dispara em navegador de
  // celular e bloqueia o cache de volta/avancar.
  window.addEventListener("pagehide", () => { void enviar("saiu", "aba_fechada"); });
}

export function iniciarSessao() {
  if (!disponivel() || sid) return;
  sid = "1";   // marcador local de "ja iniciei"; o sid real e do servidor
  montarOuvintes();
  if (temporizador) clearInterval(temporizador);
  temporizador = setInterval(() => { void enviar("intervalo"); }, INTERVALO_MS);

  // ⭐ PRIMEIRO ENVIO IMEDIATO, e nao no fim do primeiro ciclo.
  //
  // Sem isto, a sessao so NASCIA no servidor apos 45 segundos — entao quem
  // estava olhando o painel de presenca via o colega aparecer quase um minuto
  // depois de ele ter entrado, e a tela parecia atrasada quando na verdade nao
  // havia o que mostrar ainda. O gargalo do "tempo real" era este, e nao o
  // intervalo de consulta do painel: encurtar a consulta nao adiantava nada.
  //
  // 1,5s e nao zero DE PROPOSITO: da tempo de o primeiro evento de navegacao
  // (o `ver` da tela inicial, que o UsoProvider emite no efeito seguinte) entrar
  // no MESMO lote. Uma requisicao em vez de duas, e a sessao ja nasce sabendo
  // onde a pessoa esta — em vez de aparecer com a tela em branco por 45s.
  setTimeout(() => { void enviar("inicio"); }, 1500);
}

/** Fecha a sessao AGORA — chamada pelo botao "Sair do sistema".
 *
 *  Devolve promessa porque quem chama precisa ESPERAR: logo depois disto o
 *  cookie de autenticacao e apagado, e um envio atrasado tomaria 401. Sem o
 *  await, a sessao ficava aberta no painel ate expirar por silencio (~2min) e o
 *  evento `sessao.encerrada` — que leva a duracao para a trilha — nao era
 *  gravado. E o mesmo defeito da entrada, do outro lado: demorava a aparecer
 *  quem entrou, e demorava a sumir quem saiu.
 *
 *  Nunca rejeita: `enviar` ja trata a propria falha, e metrica nao pode impedir
 *  alguem de sair do sistema. */
export async function encerrarSessao(): Promise<void> {
  await enviar("logout", "logout");
  // ⚠️ ZERA O ESTADO DO MODULO. Sair e entrar de novo NAO recarrega a pagina —
  // e uma navegacao do Next, e tudo aqui e escopo de modulo, entao sobrevive.
  // Sem esta limpeza, `iniciarSessao` sairia cedo no login seguinte (o guard
  // `if (sid) return`) e a proxima pessoa a usar a mesma maquina herdaria o
  // temporizador da anterior. Os ouvintes de DOM ficam (sao os mesmos para
  // qualquer pessoa); so o relogio de atividade e a fila zeram.
  sid = "";
  fila = [];
  ligado = true;   // reabre o disjuntor: sessao nova merece tentativa limpa
  falhas = 0;
  pausadoPor401 = false;
  ultimaConsulta.clear();
  if (temporizador) { clearInterval(temporizador); temporizador = null; }
}

export function guardarPresenca(lista: Presente[], agoraIso: string) {
  presentes = lista;
  const t = Date.parse(agoraIso);
  if (!Number.isNaN(t)) desvioRelogioMs = t - Date.now();
  ouvintes.forEach((f) => f());
}
