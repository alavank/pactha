// PERÍODO — a definição única de "mandato", "ano" e "intervalo" do PACTHA.
//
// Por que existe: a fórmula do mandato estava copiada LITERALMENTE em três
// arquivos (parlamentares, components/bi/Filtros e app/m/[slug]), e os
// seletores de ano divergiam entre nove telas — umas com chips de mandato,
// outras multi sem chips, outras de escolha única, e uma com <select> nativo.
// O gestor percebe: "o filtro de uma tela não é igual ao da outra".
//
// ⚠️ MANDATO AQUI É SEMPRE MANDATO DE PREFEITO. Decisão do dono, registrada
// porque é contraintuitiva na tela de Parlamentares: ali os dados são de
// emendas de deputados e senadores, cujos ciclos são OUTROS (deputado 4 anos
// começando em 2023, senador 8). Mesmo lá, "Mandato atual" significa o mandato
// do prefeito — é o recorte que o cliente usa para prestar contas.
//
// Ciclo: 2025–2028, 2021–2024, 2017–2020… Ancorado em 2025 e andando de 4 em 4,
// então continua correto em 2029 sem ninguém tocar no código.

/** Atalho do topo do dropdown. Estruturalmente igual ao `AtalhoMulti` do
 *  MultiSelect, declarado aqui de propósito: se este módulo importasse de lá,
 *  o MultiSelect não poderia reexportar nada daqui sem ciclo. */
export interface AtalhoPeriodo {
  label: string;
  valores: string[];
}

/** Primeiro ano do mandato de prefeito que contém `ano`. */
export function inicioDoMandato(ano: number = new Date().getFullYear()): number {
  return ano - ((((ano - 2025) % 4) + 4) % 4);
}

/** Os 4 anos do mandato que contém `ano`.
 *  `ateHoje` corta os anos que ainda não aconteceram: oferecer 2027 e 2028 num
 *  filtro de dados de 2026 é oferecer resultado vazio garantido. */
export function anosDoMandato(
  ano: number = new Date().getFullYear(),
  ateHoje = true,
): number[] {
  const i = inicioDoMandato(ano);
  const anos = [i, i + 1, i + 2, i + 3];
  return ateHoje ? anos.filter((a) => a <= new Date().getFullYear()) : anos;
}

/** Rótulo do mandato para texto ("2025–2028"). Sempre os 4 anos, mesmo os
 *  futuros: aqui é o NOME do período, não a lista de anos com dado. */
export function rotuloMandato(ano: number = new Date().getFullYear()): string {
  const i = inicioDoMandato(ano);
  return `${i}–${i + 3}`;
}

/** Anos oferecidos no seletor, do mais recente para o mais antigo.
 *  Começa em 2016 porque não há dado coletado antes disso em fonte nenhuma. */
export function anosOpcoes(desde = 2016): string[] {
  const y = new Date().getFullYear();
  return Array.from({ length: y - desde + 1 }, (_, i) => String(y - i));
}

/** Os três atalhos do topo do dropdown.
 *  Sem atalho "Todos": a linha de ações do MultiSelect já tem esse botão, e o
 *  mesmo rótulo duas vezes na mesma caixa só faz o usuário hesitar. */
export function atalhosAnos(): AtalhoPeriodo[] {
  const y = new Date().getFullYear();
  const i = inicioDoMandato(y);
  return [
    { label: "Mandato atual", valores: anosDoMandato(y).map(String) },
    { label: "Este ano", valores: [String(y)] },
    {
      label: "Mandato anterior",
      valores: [i - 4, i - 3, i - 2, i - 1].map(String),
    },
  ];
}

/** Resumo curto para o gatilho do dropdown.
 *  Anos contíguos viram intervalo ("2021–2024") em vez de lista; quatro anos
 *  soltos separados por vírgula é ruído numa barra de filtros. */
export function resumoAnos(v: string[]): string {
  if (!v.length) return "";
  const n = v.map(Number).filter((x) => !Number.isNaN(x)).sort((a, b) => a - b);
  if (!n.length) return v.join(", ");
  if (n.length === 1) return String(n[0]);
  const contiguo = n.every((a, i) => i === 0 || a === n[i - 1] + 1);
  if (contiguo) {
    // Comparar com os 4 anos cheios NÃO serve para o mandato em curso: o atalho
    // "Mandato atual" só oferece os anos que já aconteceram (em 2026 são dois),
    // então quem clicava no botão via "2025–2026" na caixa em vez do nome que
    // acabou de clicar. Compara-se com as DUAS formas — a cheia, para mandato
    // encerrado, e a cortada em hoje, para o que está correndo.
    const cheio = anosDoMandato(n[0], false);
    const ateHoje = anosDoMandato(n[0], true);
    const casa = (m: number[]) => n.length === m.length && n[0] === m[0];
    if (casa(cheio) || casa(ateHoje)) {
      if (inicioDoMandato() === n[0]) return "Mandato atual";
      if (inicioDoMandato() - 4 === n[0]) return "Mandato anterior";
      return rotuloMandato(n[0]);
    }
    return `${n[0]}–${n[n.length - 1]}`;
  }
  return n.length <= 3 ? n.join(", ") : `${n.length} anos`;
}

// ---------------------------------------------------------------------------
// Intervalo de datas
// ---------------------------------------------------------------------------

/** Período livre por data. Vazio nos dois lados = sem filtro de intervalo. */
export interface Intervalo {
  de?: string;   // ISO "2025-03-23"
  ate?: string;  // ISO "2025-10-11"
}

export function intervaloVazio(i?: Intervalo): boolean {
  return !i || (!i.de && !i.ate);
}

/** Texto do intervalo em pt-BR, para o gatilho e para o chip de filtro ativo.
 *  Um lado só é válido e comum ("tudo que vence a partir de março"). */
export function rotuloIntervalo(i?: Intervalo): string {
  if (intervaloVazio(i)) return "";
  const br = (iso?: string) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
  };
  if (i!.de && i!.ate) return `${br(i!.de)} a ${br(i!.ate)}`;
  if (i!.de) return `a partir de ${br(i!.de)}`;
  return `até ${br(i!.ate)}`;
}

/** `de` depois de `ate` devolve lista vazia sem erro, o que parece "nenhum
 *  resultado" quando na verdade é o filtro invertido. Melhor avisar. */
export function intervaloInvalido(i?: Intervalo): boolean {
  return !!(i?.de && i?.ate && i.de > i.ate);
}
