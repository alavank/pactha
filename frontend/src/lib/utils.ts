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
  if (dias == null) return "text-gray-400";
  if (dias < 0) return "text-red-600 font-bold";
  if (dias <= 30) return "text-red-500 font-semibold";
  if (dias <= 120) return "text-orange-500 font-medium";
  return "text-green-600";
}

export function diasRestantesBadge(dias: number | null | undefined): string {
  if (dias == null) return "bg-gray-100 text-gray-600";
  if (dias < 0) return "bg-red-100 text-red-800";
  if (dias <= 30) return "bg-red-100 text-red-700";
  if (dias <= 120) return "bg-orange-100 text-orange-700";
  return "bg-green-100 text-green-700";
}

export function situacaoBadgeColor(situacao: string | null | undefined): string {
  if (!situacao) return "bg-gray-100 text-gray-600";
  const s = situacao.toLowerCase();
  if (s.includes("execu")) return "bg-blue-100 text-blue-700";
  if (s.includes("presta")) return "bg-purple-100 text-purple-700";
  if (s.includes("conclu") || s.includes("finaliz") || s.includes("encerr")) return "bg-green-100 text-green-700";
  if (s.includes("cancel") || s.includes("anulad")) return "bg-red-100 text-red-700";
  if (s.includes("proposta") || s.includes("analise")) return "bg-yellow-100 text-yellow-700";
  return "bg-gray-100 text-gray-600";
}
