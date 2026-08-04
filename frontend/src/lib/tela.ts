"use client";
// Protocolo do MODO TELA — a janela do slideshow e o painel de indicadores
// conversam por BroadcastChannel (mesma origem, sem servidor no meio).
//
// Quem manda no relogio e a JANELA DA TELA: ela roda o timer e publica o estado
// (`state`) a cada ~500 ms. O painel de indicadores so ESCUTA e manda comandos
// (`cmd`). Assim nao ha dois cronometros disputando quem esta certo — e se a
// janela for fechada, o painel para de receber `state` e some com o controle.
//
// Os filtros seguem o caminho inverso: quem manda e o painel (`filtros`), a
// tela obedece. Filtrou no modulo -> a TV ja mostra filtrado.

export const TELA_CHANNEL = "pactha_modo_tela";
export const TELA_PATH = "/tela";

/** Mesmo valor de CONSOLIDADO no BiScopeContext, repetido aqui para a janela
 *  da tela nao precisar carregar o contexto do sistema so por causa disto. */
export const CONSOLIDADO_URL = "__all__";

/** Tempo que cada aba fica no ar antes de virar (padrao pedido: 60 s). */
export const DURACAO_PADRAO_MS = 60_000;

/** Sem `state` por este tempo, consideramos que a janela morreu. */
export const TELA_TIMEOUT_MS = 4_000;

export type AbaId =
  | "geral"
  | "parlamentares"
  | "transferegov"
  | "estaduais"
  | "documentos"
  | "fns"
  | "sismob";

export interface AbaDef {
  id: AbaId;
  label: string;
  /** Rotulo curto para a "orelha" da pasta quando o espaco aperta. */
  curto: string;
  descricao: string;
}

export const ABAS: AbaDef[] = [
  { id: "geral", label: "Visão Geral", curto: "Geral", descricao: "O essencial do período" },
  { id: "parlamentares", label: "Parlamentares", curto: "Parlam.", descricao: "Emendas por autor, destinação e finalidade" },
  { id: "transferegov", label: "TransfereGov", curto: "Federal", descricao: "Propostas e convênios federais" },
  { id: "estaduais", label: "Verbas Estaduais", curto: "Estadual", descricao: "Convênios e emendas estaduais" },
  // Rótulo neutro de propósito: "CAGEC" é o nome do cadastro de MINAS, e esta
  // aba é a mesma para clientes de qualquer estado (ver components/bi/abas.tsx).
  { id: "documentos", label: "CAUC e cadastro estadual", curto: "Documentos", descricao: "Documentação em dia ou pendente" },
  { id: "sismob", label: "Obras da Saúde", curto: "Obras",
    descricao: "Obras do Ministério da Saúde (SISMOB) — prazos e execução" },
  { id: "fns", label: "Fundo Nacional de Saúde", curto: "FNS", descricao: "Propostas do FNS no período" },
];

export function abaIndex(id: AbaId): number {
  const i = ABAS.findIndex((a) => a.id === id);
  return i < 0 ? 0 : i;
}

// ---- mensagens ----

export interface FiltrosTela {
  /** "__all__" (consolidado) ou o id do municipio como string. */
  scope: string;
  anos: number[];
}

/** Estado publicado pela janela da tela. */
export interface TelaState {
  type: "state";
  aba: AbaId;
  indice: number;
  total: number;
  /** ms restantes na aba atual. */
  restante: number;
  duracao: number;
  tocando: boolean;
  /** Epoch ms de quando o estado foi emitido (p/ interpolar no outro lado). */
  em: number;
}

export type TelaCmd =
  | { type: "cmd"; acao: "play" | "pause" | "toggle" | "next" | "prev" }
  | { type: "cmd"; acao: "goto"; aba: AbaId }
  | { type: "cmd"; acao: "duracao"; ms: number };

export type TelaMsg =
  | TelaState
  | TelaCmd
  | { type: "filtros"; filtros: FiltrosTela }
  | { type: "ola" } // tela abriu: peca os filtros atuais ao painel
  | { type: "tchau" }; // tela fechando

/** Canal do modo tela, ou null em SSR / navegador sem BroadcastChannel. */
export function abrirCanal(): BroadcastChannel | null {
  if (typeof window === "undefined" || typeof BroadcastChannel === "undefined") return null;
  try {
    return new BroadcastChannel(TELA_CHANNEL);
  } catch {
    return null;
  }
}

/** Monta a URL da janela da tela com os filtros embutidos (fallback do canal:
 *  se o BroadcastChannel nao existir, a tela ainda abre no escopo certo). */
export function urlDaTela(filtros: FiltrosTela, aba?: AbaId): string {
  const p = new URLSearchParams();
  if (filtros.scope) p.set("scope", filtros.scope);
  if (filtros.anos.length) p.set("anos", filtros.anos.join(","));
  if (aba) p.set("aba", aba);
  return `${TELA_PATH}?${p.toString()}`;
}

/** Abre (ou reaproveita) a janela da tela. Guardamos o nome fixo para nao
 *  espalhar dez janelas iguais quando o prefeito clica de novo. */
export function abrirJanelaDaTela(filtros: FiltrosTela): Window | null {
  if (typeof window === "undefined") return null;
  const w = window.open(urlDaTela(filtros), "pactha_modo_tela");
  w?.focus();
  return w;
}
