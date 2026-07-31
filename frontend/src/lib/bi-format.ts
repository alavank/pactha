// Formatacao pt-BR do Painel de Indicadores (BI). Valores compactos ("R$ 6,4 mi")
// p/ caber em card/TV, e inteiros/datas amigaveis. Portado de painel/src/lib/format.ts.

function trim(n: number): string {
  const r = Math.round(n * 10) / 10;
  return (Number.isInteger(r) ? String(r) : r.toFixed(1)).replace(".", ",");
}

/** R$ compacto: 6.400.000 -> "R$ 6,4 mi"; 480.000 -> "R$ 480 mil". */
export function formatCurrencyShort(v: number | null | undefined): string {
  const n = Number(v || 0);
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `R$ ${trim(n / 1_000_000)} mi`;
  if (abs >= 1_000) return `R$ ${trim(n / 1_000)} mil`;
  return `R$ ${trim(n)}`;
}

/** R$ completo: "R$ 6.400.000,00". */
export function formatCurrency(v: number | null | undefined): string {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
    maximumFractionDigits: 2,
  }).format(Number(v || 0));
}

/** Inteiro pt-BR: 1234 -> "1.234". */
export function formatInt(v: number | null | undefined): string {
  return new Intl.NumberFormat("pt-BR").format(Math.round(Number(v || 0)));
}

/** ISO / dd/mm/yyyy -> "12 fev 2026". */
export function formatDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = parseDate(v);
  if (!d) return String(v);
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(d);
}

/** Severidade por dias restantes (cor/badge): <0 crit, <=60 warn, resto ok. */
export function diasSeveridade(dias: number | null | undefined): "crit" | "warn" | "ok" {
  const d = Number(dias ?? 0);
  if (d < 0) return "crit";
  if (d <= 60) return "warn";
  return "ok";
}

export function diasLabel(dias: number | null | undefined): string {
  const d = Number(dias ?? 0);
  if (d < 0) return `vencido há ${Math.abs(d)} dias`;
  if (d === 0) return "vence hoje";
  return `vence em ${d} dias`;
}

function parseDate(v: string): Date | null {
  const s = String(v).trim();

  // Data PURA (YYYY-MM-DD) e uma data de CALENDARIO, nao um instante: monte no
  // fuso LOCAL. `new Date("2026-07-31")` e meia-noite UTC e, formatada em UTC-3,
  // volta um dia — o Painel, a TV, o link publico e o celular exibiam
  // "30 de jul. de 2026" para o extrato do CAUC pesquisado em 31/07, e TODA
  // validade saia um dia antes (24/09/2026 virava 23/09). A tela do modulo usa
  // outro caminho (`toLocaleDateString` com timeZone "UTC") e acertava: as duas
  // superficies do mesmo sistema mostravam datas diferentes para o mesmo campo.
  //
  // Nao resolva isso pondo `timeZone: "UTC"` no formatDate: conserta este ramo e
  // quebra o de baixo, porque `new Date(2026, 6, 31)` e meia-noite LOCAL e, num
  // fuso positivo, ja e o dia anterior em UTC.
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (iso) return new Date(+iso[1], +iso[2] - 1, +iso[3]);

  // Timestamp completo (com hora/offset) e um INSTANTE: parse normal, exibido no
  // fuso de quem le — que aqui e o comportamento desejado.
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) {
    const d = new Date(s);
    return isNaN(+d) ? null : d;
  }

  const br = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(s);
  if (br) return new Date(+br[3], +br[2] - 1, +br[1]);
  return null;
}
