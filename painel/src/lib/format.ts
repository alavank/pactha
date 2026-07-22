// Formatação em pt-BR para o Painel do prefeito. Linguagem de valores grandes,
// compacta ("R$ 6,4 mi") para caber em card/TV, e completa para detalhe.

/** R$ compacto: 6.400.000 -> "R$ 6,4 mi"; 480.000 -> "R$ 480 mil". */
export function formatCurrencyShort(v: number | null | undefined): string {
  const n = Number(v || 0);
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `R$ ${trim(n / 1_000_000)} mi`;
  if (abs >= 1_000) return `R$ ${trim(n / 1_000)} mil`;
  return `R$ ${trim(n)}`;
}

/** R$ completo com centavos: "R$ 6.400.000,00". */
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

/** Datas ISO / dd/mm/yyyy -> "12 fev 2026". Aceita null. */
export function formatDate(v: string | null | undefined): string {
  if (!v) return "—";
  const d = parseDate(v);
  if (!d) return String(v);
  return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "short", year: "numeric" }).format(d);
}

/** Rótulo de dias restantes: 45 -> "vence em 45 dias"; -112 -> "vencido há 112 dias". */
export function diasLabel(dias: number | null | undefined): string {
  const d = Number(dias ?? 0);
  if (d < 0) return `vencido há ${Math.abs(d)} dias`;
  if (d === 0) return "vence hoje";
  return `vence em ${d} dias`;
}

/** Severidade por dias restantes (para cor/badge). */
export function diasSeveridade(dias: number | null | undefined): "crit" | "warn" | "ok" {
  const d = Number(dias ?? 0);
  if (d < 0) return "crit";
  if (d <= 60) return "warn";
  return "ok";
}

function trim(n: number): string {
  // 1 casa decimal, sem ".0" desnecessário, com vírgula pt-BR.
  const r = Math.round(n * 10) / 10;
  return (Number.isInteger(r) ? String(r) : r.toFixed(1)).replace(".", ",");
}

function parseDate(v: string): Date | null {
  const s = String(v).trim();
  const iso = /^\d{4}-\d{2}-\d{2}/.exec(s);
  if (iso) {
    const d = new Date(s);
    return isNaN(+d) ? null : d;
  }
  const br = /^(\d{2})\/(\d{2})\/(\d{4})/.exec(s);
  if (br) return new Date(+br[3], +br[2] - 1, +br[1]);
  return null;
}
