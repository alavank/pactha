// TELEMETRIA — a GRAMÁTICA que transforma um evento cru numa frase que o gestor
// lê: "Maria abriu o detalhe de «Convênio 812/2024» em Convênios Estaduais".
//
// Vive FORA do coletor (lib/uso.ts) de propósito: o coletor grava o mínimo e
// roda a cada clique; a tradução roda só na tela de Telemetria, e pode mudar
// sem regravar nada — um evento antigo passa a ler melhor no dia em que a
// frase melhora aqui.
//
// ⚠️ Rótulo de tela e de escrita são LITERAIS mantidos à mão, e não derivados
// do menu: o menu muda por permissão e por UF, e uma frase de telemetria sobre
// ontem não pode mudar porque o menu de hoje é outro.

export interface EventoUsoLido {
  id?: number;
  ocorrido_em: string;
  tela: string;
  rota: string | null;
  acao: string;
  alvo: string | null;
  ms: number | null;
  municipio: string | null;
  detalhe?: Record<string, unknown> | null;
  user_email: string;
  usuario_nome: string | null;
  sid: string;
}

/** O nome da tela por rota. Ordem importa: o mais específico primeiro. */
const TELAS: Array<[RegExp, string]> = [
  [/^\/dashboard\/?$/, "Painel de Indicadores"],
  [/^\/dashboard\/transferegov-geral/, "TransfereGov · Em execução"],
  [/^\/dashboard\/transferegov-pac/, "TransfereGov · PAC"],
  [/^\/dashboard\/transferegov-voluntarias/, "TransfereGov · Voluntárias"],
  [/^\/dashboard\/transferegov-rejeitadas/, "TransfereGov · Rejeitadas"],
  [/^\/dashboard\/transferegov-encerradas/, "TransfereGov · Encerradas"],
  [/^\/dashboard\/transferegov-cnpj/, "TransfereGov · CNPJ"],
  [/^\/dashboard\/transferegov/, "TransfereGov · Especiais"],
  [/^\/dashboard\/convenios/, "Convênios Estaduais"],
  // Antes de `emendas`, que a pegaria pelo prefixo. As rotas antigas ficam: o
  // histórico de uso anterior a 17/09/2026 ainda as cita.
  [/^\/dashboard\/emendas-parlamentares/, "Emendas parlamentares"],
  [/^\/dashboard\/emendas-rs/, "Emendas Estaduais RS"],
  [/^\/dashboard\/emendas/, "Emendas Estaduais"],
  [/^\/dashboard\/repasses/, "Repasses Estaduais"],
  [/^\/dashboard\/cofinanciamento/, "Cofinanciamento da Saúde"],
  [/^\/dashboard\/agendamentos/, "Agendamentos"],
  [/^\/dashboard\/consulta-popular/, "Consulta Popular"],
  [/^\/dashboard\/programas-rs/, "Programas do Estado"],
  [/^\/dashboard\/funrigs/, "Plano Rio Grande"],
  [/^\/dashboard\/tce-rs/, "TCE-RS"],
  [/^\/dashboard\/tce-pr/, "TCE-PR"],
  [/^\/dashboard\/cgu-convenios/, "Defesa Civil e outros repasses (CGU)"],
  [/^\/dashboard\/cgu-transferencias/, "Recursos recebidos por pasta"],
  [/^\/dashboard\/parlamentares/, "Parlamentares"],
  [/^\/dashboard\/fns/, "Fundo Nacional de Saúde"],
  [/^\/dashboard\/sismob/, "Obras da Saúde (SISMOB)"],
  [/^\/dashboard\/investsus/, "InvestSUS"],
  [/^\/dashboard\/acordofes/, "Acordo FES"],
  [/^\/dashboard\/simec/, "SIMEC - PAR"],
  [/^\/dashboard\/pdde/, "PDDE — dinheiro nas escolas"],
  [/^\/dashboard\/fnas/, "Assistência social — FNAS"],
  [/^\/dashboard\/feas/, "Assistência social — Estado (FEAS)"],
  [/^\/dashboard\/cauc/, "Regularidade"],
  [/^\/dashboard\/rm\/(\d+)/, "Relatório de Monitoramento nº $1"],
  [/^\/dashboard\/rm/, "Relatórios de Monitoramento"],
  [/^\/dashboard\/ai/, "IA PACTHA"],
  [/^\/dashboard\/paineis/, "Painéis Municipais"],
  [/^\/dashboard\/dou/, "Diário Oficial"],
  [/^\/dashboard\/documentos\/editor/, "Editor de Documentos"],
  [/^\/dashboard\/documentos/, "Geração de Documentos"],
  [/^\/dashboard\/gestao/, "Gestão Interna"],
  // Módulo removido em 05/09/2026; o rótulo fica porque a telemetria de uso
  // guarda navegação ANTIGA, e sem ele a linha aparece como caminho cru.
  [/^\/dashboard\/telegram/, "Telegram"],
  [/^\/dashboard\/(configuracoes\/)?usuarios/, "Configurações · Usuários"],
  [/^\/dashboard\/(configuracoes\/)?cofre/, "Configurações · Cofre de Senhas"],
  [/^\/dashboard\/(configuracoes\/)?sessoes/, "Configurações · Sessões gov.br"],
  [/^\/dashboard\/(configuracoes\/)?auditoria/, "Configurações · Auditoria"],
  [/^\/dashboard\/(configuracoes\/)?telemetria/, "Configurações · Telemetria"],
  [/^\/dashboard\/(configuracoes\/)?frescor/, "Configurações · Status dos Dados"],
  [/^\/dashboard\/(configuracoes\/)?service-tokens/, "Configurações · Service Tokens"],
  [/^\/dashboard\/(configuracoes\/)?parametros/, "Configurações · Parâmetros"],
  [/^\/dashboard\/configuracoes/, "Configurações"],
  [/^\/login/, "Login"],
];

export function nomeDaTela(rota: string | null | undefined, tela?: string): string {
  const r = rota || "";
  for (const [re, nome] of TELAS) {
    const m = re.exec(r);
    if (m) return nome.replace("$1", m[1] || "");
  }
  return tela ? tela.charAt(0).toUpperCase() + tela.slice(1) : (r || "o sistema");
}

/** As chaves de filtro que o gestor reconhece. Fora daqui, `chave_x` vira
 *  "chave x". */
const PARAMS: Record<string, string> = {
  ano: "ano", anos: "anos", situacao: "situação", situacoes: "situação",
  vigencia: "vigência", fontes: "fonte", fonte: "fonte", tipo: "tipo", tipos: "tipo",
  orgao: "órgão", orgaos: "órgão", esfera: "esfera", status: "status",
  categoria: "categoria", uf: "UF", dias: "período (dias)", programa: "programa",
  modalidade: "modalidade", parlamentar: "parlamentar", estagio: "estágio",
  periodo: "período", inicio: "de", fim: "até", ordem: "ordem", order: "ordem",
  sort: "ordem", aba: "aba", q: "busca", busca: "busca", termo: "busca",
  texto: "busca", palavra: "busca", pesquisa: "busca", cnpj: "CNPJ",
  proposta: "proposta", numero: "número", secretaria: "secretaria",
  responsavel: "responsável", sid: "sessão", user_id: "pessoa",
};

export function descreverParams(params: unknown): string {
  if (!params || typeof params !== "object") return "";
  return Object.entries(params as Record<string, unknown>)
    .map(([k, v]) => `${PARAMS[k] || k.replace(/_/g, " ")}: ${String(v)}`)
    .join(" · ");
}

/** O que uma ESCRITA na API significa, em português. Ordem: específico antes
 *  do genérico. `$1` recebe o id do caminho quando houver. */
const ESCRITAS: Array<[RegExp, string]> = [
  [/^POST \/rm\/\d+\/(pdf|export)/, "exportou o PDF de um Relatório de Monitoramento"],
  [/^POST \/rm\/?$/, "gerou um Relatório de Monitoramento"],
  [/^(PUT|PATCH) \/rm\/(\d+)/, "alterou o Relatório de Monitoramento nº $1"],
  [/^DELETE \/rm\/(\d+)/, "excluiu o Relatório de Monitoramento nº $1"],
  [/^POST \/rm\/(\d+)/, "atualizou o Relatório de Monitoramento nº $1"],
  [/^POST \/gestao\/anotacoes/, "criou uma anotação na Gestão Interna"],
  [/^(PUT|PATCH) \/gestao\/anotacoes/, "alterou uma anotação na Gestão Interna"],
  [/^DELETE \/gestao\/anotacoes/, "excluiu uma anotação na Gestão Interna"],
  [/^POST \/gestao/, "gravou um registro na Gestão Interna"],
  [/^(PUT|PATCH) \/gestao/, "alterou um registro na Gestão Interna"],
  [/^DELETE \/gestao/, "excluiu um registro na Gestão Interna"],
  [/^POST \/documentos\/.*(pdf|gerar)/, "gerou um documento em PDF"],
  [/^POST \/documentos/, "gerou um documento"],
  [/^(PUT|PATCH) \/documentos/, "alterou um documento"],
  [/^DELETE \/documentos/, "excluiu um documento"],
  [/^POST \/cofre\/\d+\/revelar/, "revelou uma senha do Cofre"],
  [/^POST \/cofre/, "guardou uma senha no Cofre"],
  [/^(PUT|PATCH) \/cofre/, "alterou uma senha do Cofre"],
  [/^DELETE \/cofre/, "removeu uma senha do Cofre"],
  [/^POST \/(users|usuarios)\/?$/, "criou um usuário"],
  [/^(PUT|PATCH) \/(users|usuarios)\/\d+\/permiss/, "alterou permissões de um usuário"],
  [/^(PUT|PATCH) \/(users|usuarios)/, "alterou um usuário"],
  [/^DELETE \/(users|usuarios)/, "excluiu um usuário"],
  [/^\w+ \/permissoes/, "alterou permissões"],
  [/^\w+ \/modelos-permissao/, "alterou um modelo de permissão"],
  [/^POST \/ai/, "perguntou à IA PACTHA"],
  [/^POST \/convenios\/refresh|sigcon/, "pediu atualização no portal do Estado"],
  [/^POST \/bi\/tela-links/, "gerou um link público da TV"],
  [/^DELETE \/bi\/tela-links/, "revogou um link público da TV"],
  [/^\w+ \/bi\/tela-filtros/, "salvou os filtros do Modo Tela"],
  [/^\w+ \/(bi|painel)\/(push|preferencias)/, "alterou os avisos do painel"],
  [/^POST \/service-tokens/, "criou um service token"],
  [/^DELETE \/service-tokens/, "revogou um service token"],
  [/^POST \/auth\/change-password/, "trocou a própria senha"],
  [/^\w+ \/session-capture/, "capturou uma sessão gov.br"],
  [/^POST \/export-pdf/, "exportou um PDF"],
  [/^POST \/(scraper|coleta|control)/, "pediu uma coleta"],
  [/^POST \/telegram/, "vinculou o Telegram"],
  [/^\w+ \/parametros/, "alterou parâmetros do sistema"],
];

function humanizar(seg: string): string {
  return seg.replace(/[-_]/g, " ");
}

export function descreverEscrita(alvo: string | null): string {
  const a = alvo || "";
  for (const [re, frase] of ESCRITAS) {
    const m = re.exec(a);
    if (m) return frase.replace("$1", m[m.length - 1] || "");
  }
  const [metodo, caminho = ""] = a.split(" ");
  const recurso = humanizar(caminho.split("/").filter(Boolean)[0] || "dados");
  const verbo = metodo === "DELETE" ? "excluiu" : metodo === "POST" ? "gravou" : "alterou";
  return `${verbo} dados em ${recurso}`;
}

export interface Frase {
  /** O que a pessoa fez, sem o sujeito: "abriu o detalhe de «X»". */
  acao: string;
  /** Onde: "em Convênios Estaduais". Vazio quando a ação já nomeia a tela. */
  onde: string;
  /** Duração, quando o evento a tem (a permanência numa tela). */
  duracao?: string;
}

export function dur(seg: number | null | undefined): string {
  if (!seg || seg < 1) return "—";
  if (seg < 60) return `${Math.round(seg)}s`;
  const m = Math.floor(seg / 60);
  if (m < 60) return `${m}min`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}min`;
}

const aspas = (s: string | null | undefined) => (s ? `«${s}»` : "");

/** A frase, sem o nome da pessoa (quem monta a linha põe o sujeito). */
export function fraseDoEvento(e: EventoUsoLido): Frase {
  const tela = nomeDaTela(e.rota, e.tela);
  const em = `em ${tela}`;
  const d = (e.detalhe || {}) as Record<string, unknown>;
  const tipo = String(d.tipo || "");
  switch (e.acao) {
    case "ver":
      return { acao: `abriu ${tela}`, onde: "" };
    case "sair":
      return { acao: `ficou ${dur(e.ms ? e.ms / 1000 : 0)} em ${tela}`, onde: "" };
    case "detalhe":
      return { acao: `abriu o detalhe de ${aspas(e.alvo) || "um item"}`, onde: em };
    case "aba":
      return { acao: `abriu a aba ${aspas(e.alvo)}`, onde: em };
    case "trocar":
      return { acao: `trocou para o município ${aspas(e.alvo)}`, onde: "" };
    case "abrir":
      return { acao: `abriu o site ${d.site ? String(d.site) : aspas(e.alvo)}`, onde: em };
    case "selecionar":
      return { acao: `${d.marcado === false ? "desmarcou" : "marcou"} ${aspas(e.alvo)}`, onde: em };
    case "filtrar": {
      if (tipo === "consulta") return { acao: `filtrou ${tela}: ${descreverParams(d.params)}`, onde: "" };
      if (tipo === "select") return { acao: `filtrou ${aspas(e.alvo)}: ${String(d.valor ?? "")}`, onde: em };
      if (tipo === "option" || d.grupo) {
        const grupo = d.grupo ? String(d.grupo) : "filtro";
        const verbo = d.marcado === false ? "desmarcou" : "marcou";
        return { acao: `${verbo} ${aspas(e.alvo)} no filtro ${aspas(grupo)}`, onde: em };
      }
      return { acao: `clicou em ${aspas(e.alvo) || "filtrar"}`, onde: em };
    }
    case "buscar":
      return { acao: `buscou ${aspas(e.alvo)}`, onde: em };
    case "exportar":
      return tipo === "escrita"
        ? { acao: descreverEscrita(e.alvo), onde: em }
        : { acao: `exportou ${aspas(e.alvo) || "um arquivo"}`, onde: em };
    case "gerar":
      return tipo === "escrita"
        ? { acao: descreverEscrita(e.alvo), onde: em }
        : { acao: `clicou em ${aspas(e.alvo) || "gerar"}`, onde: em };
    case "perguntar":
      return { acao: tipo === "escrita" ? "perguntou à IA PACTHA" : `clicou em ${aspas(e.alvo)}`, onde: em };
    case "alterar":
      return { acao: descreverEscrita(e.alvo), onde: em };
    case "acionar":
      return { acao: `clicou em ${aspas(e.alvo) || "um botão"}`, onde: em };
    default:
      return { acao: `usou ${aspas(e.alvo) || "o sistema"}`, onde: em };
  }
}

/** O rótulo curto do tipo de evento, para o selo e o filtro. */
export const TIPO_EVENTO: Record<string, string> = {
  ver: "navegação", sair: "permanência", detalhe: "detalhe", aba: "aba",
  filtrar: "filtro", selecionar: "seleção", buscar: "busca", exportar: "exportação",
  gerar: "geração", perguntar: "IA", alterar: "alteração", acionar: "clique",
  trocar: "município", abrir: "link externo", outro: "outro",
};

/** Como a sessão terminou — a frase que o dono pediu: "clicou em Sair" ou
 *  "fechou o navegador e o sistema encerrou depois de um tempo". */
export function fimDaSessao(situacao: string): { texto: string; tom: "ok" | "neutro" | "atencao" } {
  switch (situacao) {
    case "ativa": return { texto: "em uso agora", tom: "ok" };
    case "logout": return { texto: "saiu pelo botão Sair", tom: "neutro" };
    case "navegador_fechado": return { texto: "fechou o navegador — sessão encerrada", tom: "neutro" };
    case "aba_fechada": return { texto: "fechou a aba há pouco", tom: "neutro" };
    case "expirou": return { texto: "parou de responder — sessão expirou", tom: "atencao" };
    default: return { texto: situacao || "encerrada", tom: "neutro" };
  }
}

/** "Chrome · Windows" a partir do user-agent — o suficiente para saber se foi
 *  o computador da prefeitura ou o celular. */
export function dispositivo(ua: string | null | undefined): string {
  const s = ua || "";
  if (!s) return "—";
  const nav =
    /Edg\//.test(s) ? "Edge" :
    /OPR\//.test(s) ? "Opera" :
    /Chrome\//.test(s) ? "Chrome" :
    /Firefox\//.test(s) ? "Firefox" :
    /Safari\//.test(s) ? "Safari" : "navegador";
  const so =
    /Windows/.test(s) ? "Windows" :
    /Android/.test(s) ? "Android" :
    /iPhone|iPad/.test(s) ? "iOS" :
    /Mac OS/.test(s) ? "macOS" :
    /Linux/.test(s) ? "Linux" : "";
  const movel = /Mobile|Android|iPhone/.test(s) ? " · celular" : "";
  return `${nav}${so ? ` · ${so}` : ""}${movel}`;
}

/** "Hoje", "Ontem" ou a data por extenso — o cabeçalho de cada dia. */
export function nomeDoDia(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  const dia = new Date(d); dia.setHours(0, 0, 0, 0);
  const diff = Math.round((hoje.getTime() - dia.getTime()) / 86_400_000);
  const extenso = d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
  if (diff === 0) return `Hoje · ${extenso}`;
  if (diff === 1) return `Ontem · ${extenso}`;
  return extenso.charAt(0).toUpperCase() + extenso.slice(1);
}

export function chaveDoDia(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function horaCurta(iso: string | null | undefined): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }); }
  catch { return iso; }
}

/** COM SEGUNDOS, de propósito. Sem eles, seis eventos do mesmo minuto apareciam
 *  todos como "22:29" e a lista parecia desordenada — a ordem estava certa, o
 *  carimbo é que escondia a diferença. */
export function horaCompleta(iso: string | null | undefined): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" }); }
  catch { return iso; }
}
