import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number | null | undefined): string {
  if (value == null) return "R$ 0,00";
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(value);
}

export function formatDate(date: string | null | undefined): string {
  if (!date) return "-";
  const d = new Date(date + "T00:00:00");
  return d.toLocaleDateString("pt-BR");
}

export function diasRestantesColor(dias: number | null | undefined): string {
  if (dias == null) return "text-base-content/40";
  if (dias < 0) return "text-error font-bold";
  if (dias <= 30) return "text-error font-semibold";
  if (dias <= 120) return "text-warning font-medium";
  return "text-success";
}

export function diasRestantesBadge(dias: number | null | undefined): string {
  if (dias == null) return "bg-base-200 text-base-content/60";
  if (dias < 0) return "bg-error/15 text-error";
  if (dias <= 30) return "bg-error/15 text-error";
  if (dias <= 120) return "bg-warning/15 text-warning";
  return "bg-success/15 text-success";
}

export function situacaoBadgeColor(situacao: string | null | undefined): string {
  if (!situacao) return "bg-base-200 text-base-content/60";
  const s = situacao.toLowerCase();
  if (s.includes("execu")) return "bg-primary/10 text-primary";
  if (s.includes("presta")) return "bg-info/15 text-info";
  if (s.includes("conclu") || s.includes("finaliz") || s.includes("encerr")) return "bg-success/15 text-success";
  if (s.includes("cancel") || s.includes("anulad")) return "bg-error/15 text-error";
  if (s.includes("proposta") || s.includes("analise")) return "bg-warning/15 text-warning";
  return "bg-base-200 text-base-content/60";
}
