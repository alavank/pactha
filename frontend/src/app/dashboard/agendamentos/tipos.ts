/* AGENDAMENTOS — os tipos e as contas que as quatro superfícies compartilham.
 *
 * Calendário, kanban, lista e card lateral desenham a MESMA linha de jeitos
 * diferentes. Tudo o que os quatro precisam calcular igual mora aqui: se cada
 * um tivesse a própria conversão de hora ou o próprio "é hoje", o primeiro a
 * divergir mostraria um compromisso num dia e os outros três noutro.
 *
 * ⚠️ DATA PURA NÃO É INSTANTE. `new Date("2026-09-15")` é meia-noite UTC e, no
 * Brasil, volta dia 14. Toda data aqui trabalha com os componentes Y-M-D em
 * texto e nunca com fuso — o mesmo cuidado que a coluna DATE do banco tomou.
 */
import type { CSSProperties } from "react";

export interface Compromisso {
  id: number;
  municipio_id: number;
  municipio: string;
  uf: string;
  demanda: string;
  /** `YYYY-MM-DD` */
  data: string | null;
  /** `HH:MM` */
  hora_inicio: string | null;
  tem_periodo: boolean;
  hora_fim: string | null;
  data_solicitacao: string | null;
  solicitante: string;
  /** Só dígitos: `51999998888`. A máscara é da tela. */
  contato_whatsapp: string | null;
  cor: string;
  coluna_id: number;
  coluna: string;
  anexos: { nome: string; mime: string; tamanho?: number }[];
  criado_por: number | null;
  criado_por_nome: string | null;
  anotacoes_qtd: number;
  /** Só no detalhe (`GET /agendamentos/{id}`). */
  anotacoes?: Anotacao[];
}

export interface Anotacao {
  id: number;
  autor_id: number | null;
  autor: string | null;
  texto: string;
  criado_em: string | null;
}

export interface Coluna {
  id: number;
  nome: string;
  ordem: number;
  fixa: boolean;
  chave: string | null;
}

export interface CorPaleta {
  hex: string;
  nome: string;
}

export type Vista = "calendario" | "kanban" | "lista";
export type ModoCalendario = "mensal" | "semanal" | "diaria";

export const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
  "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
export const MESES_CURTO = ["jan", "fev", "mar", "abr", "mai", "jun", "jul",
  "ago", "set", "out", "nov", "dez"];
/** ⚠️ A SEMANA COMEÇA NA SEGUNDA, como a grade do calendário e como o
 *  `_janela` do relatório. Trocar por domingo desalinharia o arquivo da tela. */
export const SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];
export const SEMANA_LONGA = ["segunda-feira", "terça-feira", "quarta-feira",
  "quinta-feira", "sexta-feira", "sábado", "domingo"];

/* ------------------------------------------------------------------ datas -- */

/** Componentes Y-M-D -> `YYYY-MM-DD`, sem passar por instante. */
export function iso(ano: number, mes0: number, dia: number): string {
  return `${ano}-${String(mes0 + 1).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
}

/** O dia de HOJE em `YYYY-MM-DD`, no relógio de quem está olhando.
 *  `toISOString()` daria o dia em UTC — às 21h de Brasília, o de amanhã. */
export function hojeISO(): string {
  const d = new Date();
  return iso(d.getFullYear(), d.getMonth(), d.getDate());
}

/** `YYYY-MM-DD` -> `[ano, mes0, dia]`. */
export function partes(dia: string): [number, number, number] {
  const [a, m, d] = dia.slice(0, 10).split("-").map(Number);
  return [a, (m || 1) - 1, d || 1];
}

/** `YYYY-MM-DD` -> `dd/mm` ou `dd/mm/aaaa`. */
export function diaBR(dia: string | null, comAno = false): string {
  if (!dia) return "—";
  const [a, m, d] = String(dia).slice(0, 10).split("-");
  if (!a || !m || !d) return "—";
  return comAno ? `${d}/${m}/${a}` : `${d}/${m}`;
}

/** `YYYY-MM-DD` -> "quinta-feira, 15 de setembro de 2026". */
export function porExtenso(dia: string): string {
  const [a, m0, d] = partes(dia);
  return `${SEMANA_LONGA[diaDaSemana(dia)]}, ${d} de ${MESES[m0]} de ${a}`;
}

/** 0 = segunda … 6 = domingo.
 *  ⚠️ `getDay()` do JavaScript é 0 no DOMINGO; a grade começa na segunda, daí
 *  o `(d + 6) % 7`. É a mesma correção que o `weekday()` do Python já faz
 *  sozinho no `_janela` do relatório — por isso os dois batem. */
export function diaDaSemana(dia: string): number {
  const [a, m0, d] = partes(dia);
  return (new Date(a, m0, d).getDay() + 6) % 7;
}

/** Anda `n` dias a partir de um `YYYY-MM-DD`, sem fuso no caminho. */
export function somaDias(dia: string, n: number): string {
  const [a, m0, d] = partes(dia);
  const x = new Date(a, m0, d + n);
  return iso(x.getFullYear(), x.getMonth(), x.getDate());
}

/** A segunda-feira da semana de `dia`. */
export function segundaDaSemana(dia: string): string {
  return somaDias(dia, -diaDaSemana(dia));
}

/** Os sete dias da semana de `dia`, de segunda a domingo. */
export function semanaDe(dia: string): string[] {
  const base = segundaDaSemana(dia);
  return Array.from({ length: 7 }, (_, i) => somaDias(base, i));
}

/** Quantos dias separam `a` de `b` (b - a). Só componentes Y-M-D, sem fuso. */
export function diasEntre(a: string, b: string): number {
  const [a1, m1, d1] = partes(a);
  const [a2, m2, d2] = partes(b);
  return Math.round(
    (new Date(a2, m2, d2).getTime() - new Date(a1, m1, d1).getTime()) / 86_400_000);
}

/** O primeiro e o último dia do mês de `dia`. */
export function limitesDoMes(dia: string): [string, string] {
  const [a, m0] = partes(dia);
  return [iso(a, m0, 1), iso(a, m0, new Date(a, m0 + 1, 0).getDate())];
}

/* ------------------------------------------------------------------ horas -- */

/** `HH:MM` -> minutos desde a meia-noite. Ilegível vira 0. */
export function minutos(hora: string | null): number {
  if (!hora) return 0;
  const [h, m] = String(hora).slice(0, 5).split(":").map(Number);
  return (h || 0) * 60 + (m || 0);
}

/** `09:00` ou `09:00 – 11:30`. O travessão é o mesmo do PDF. */
export function horarioDe(c: Compromisso): string {
  const i = c.hora_inicio || "—";
  return c.tem_periodo && c.hora_fim ? `${i} – ${c.hora_fim}` : i;
}

/** Duração em minutos para desenhar o bloco na semana/dia.
 *  ⚠️ PISO DE 30 MINUTOS mesmo com período: um compromisso de 10 minutos viraria
 *  uma faixa de 8px, alta demais para o texto e baixa demais para clicar. Sem
 *  período o piso é o tamanho do chip compacto, que é a regra do documento. */
export const MIN_BLOCO = 30;
export function duracaoDe(c: Compromisso): number {
  if (!c.tem_periodo || !c.hora_fim) return MIN_BLOCO;
  return Math.max(MIN_BLOCO, minutos(c.hora_fim) - minutos(c.hora_inicio));
}

/* -------------------------------------------------------------- sobreposição */

export interface Faixa { col: number; cols: number }

/** Reparte os compromissos de UM dia em colunas lado a lado.
 *
 * ⭐ É O QUE FAZ DOIS COMPROMISSOS NO MESMO HORÁRIO SEREM DOIS, e não um em
 * cima do outro. Sem isto, o bloco desenhado depois cobre o anterior — e o
 * compromisso some da tela sem sumir do banco, que é a pior forma de errar numa
 * agenda.
 *
 * O algoritmo é o dos calendários de mercado: ordena por início, junta em
 * AGLOMERADOS (tudo que se encosta, direta ou indiretamente) e, dentro de cada
 * aglomerado, encaixa cada bloco na primeira coluna livre. A largura de todos
 * do aglomerado é a mesma — senão dois blocos vizinhos teriam larguras
 * diferentes e o olho leria isso como hierarquia.
 */
export function repartirEmColunas(doDia: Compromisso[]): Map<number, Faixa> {
  const mapa = new Map<number, Faixa>();
  const ordenados = [...doDia].sort(
    (a, b) => minutos(a.hora_inicio) - minutos(b.hora_inicio) || a.id - b.id);

  let aglomerado: Compromisso[] = [];
  let fimDoAglomerado = -1;

  const fechar = () => {
    if (!aglomerado.length) return;
    const colunas: number[] = [];          // fim (em minutos) de cada coluna
    const posicao = new Map<number, number>();
    for (const c of aglomerado) {
      const ini = minutos(c.hora_inicio);
      let alvo = colunas.findIndex((fim) => fim <= ini);
      if (alvo === -1) { alvo = colunas.length; colunas.push(0); }
      colunas[alvo] = ini + duracaoDe(c);
      posicao.set(c.id, alvo);
    }
    for (const c of aglomerado) {
      mapa.set(c.id, { col: posicao.get(c.id) || 0, cols: colunas.length });
    }
    aglomerado = [];
    fimDoAglomerado = -1;
  };

  for (const c of ordenados) {
    const ini = minutos(c.hora_inicio);
    if (aglomerado.length && ini >= fimDoAglomerado) fechar();
    aglomerado.push(c);
    fimDoAglomerado = Math.max(fimDoAglomerado, ini + duracaoDe(c));
  }
  fechar();
  return mapa;
}

/* ------------------------------------------------------------------ texto -- */

/** Busca sem acento e sem caixa — o MESMO recorte que o backend faz em SQL
 *  (`translate(lower(...))` em `routers/agendamentos._filtros`). Aqui ela serve
 *  só para o filtro instantâneo do card lateral e das abas enquanto a
 *  requisição não volta; quem manda é sempre o servidor. */
export function semAcento(s: string): string {
  return String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

/** `51999998888` -> `(51) 99999-8888`. */
export function telefoneBR(digitos: string | null): string {
  const d = String(digitos || "").replace(/\D/g, "");
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return d;
}

/** A máscara enquanto se digita. Corta no 11º dígito: o formulário não pode
 *  aceitar o que a API recusa (`_so_digitos` devolve 422 fora de 10/11). */
export function mascaraTelefone(bruto: string): string {
  const d = String(bruto || "").replace(/\D/g, "").slice(0, 11);
  if (d.length <= 2) return d.length ? `(${d}` : "";
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
}

/** "Bom dia" / "Boa tarde" / "Boa noite", pelo relógio de quem está olhando.
 *  Os cortes são os do documento: até 11h59, 12h–17h59, 18h em diante. */
export function saudacao(agora = new Date()): string {
  const h = agora.getHours();
  if (h < 12) return "Bom dia";
  if (h < 18) return "Boa tarde";
  return "Boa noite";
}

/** O primeiro nome, para a saudação. "Maria Silva Souza" -> "Maria". */
export function primeiroNome(nome?: string | null): string {
  return String(nome || "").trim().split(/\s+/)[0] || "";
}

/** A cor como variável CSS para as peças de `.ag-*` em globals.css. */
export function estiloDaCor(cor: string): CSSProperties {
  return { "--ag-cor": cor } as CSSProperties;
}
