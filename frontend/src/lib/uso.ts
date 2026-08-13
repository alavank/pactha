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

export interface EventoUso {
  tela: string;
  /** Rota crua. Guardada ALEM da tela porque `hrefToTela` funde as sete rotas
   *  transferegov* numa chave so — e a diferenca entre Voluntarias, PAC e
   *  Rejeitadas e exatamente a pergunta "o que acessam mais". */
  rota?: string;
  acao: "ver" | "detalhe" | "filtrar" | "buscar" | "exportar"
      | "gerar" | "perguntar" | "acionar" | "sair";
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

export function iniciarSessao() {
  if (!disponivel() || sid) return;
  sid = "1";   // marcador local de "ja montei os ouvintes"; o sid real e do servidor
  const toque = () => { ultimaAtividade = Date.now(); };
  // `passive` e gravando num ref de modulo, nunca em estado: sao eventos de
  // altissima frequencia e um setState aqui re-renderizaria o app inteiro.
  window.addEventListener("click", toque, { passive: true });
  window.addEventListener("keydown", toque, { passive: true });
  window.addEventListener("scroll", toque, { passive: true });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") void enviar("escondeu");
  });
  // `pagehide` e nao `beforeunload`: o segundo nao dispara em navegador de
  // celular e bloqueia o cache de volta/avancar.
  window.addEventListener("pagehide", () => { void enviar("saiu", "aba_fechada"); });
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

export function encerrarSessao() {
  void enviar("logout", "logout");
}

export function guardarPresenca(lista: Presente[], agoraIso: string) {
  presentes = lista;
  const t = Date.parse(agoraIso);
  if (!Number.isNaN(t)) desvioRelogioMs = t - Date.now();
  ouvintes.forEach((f) => f());
}
