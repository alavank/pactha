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

/** Data em pt-BR, ou "-" quando não há data legível.
 *
 *  ⚠️ Esta função ESCREVIA "Invalid Date" na tela, em inglês. O `+ "T00:00:00"`
 *  só funciona sobre ISO: quando o valor vem `dd/mm/aaaa` — que é como o SIGCON
 *  entrega `data_criacao` — o resultado é `"16/04/2018T00:00:00"`, o `Date`
 *  nasce inválido e `toLocaleDateString` devolve a STRING "Invalid Date", que
 *  segue direto para a célula. Medido: o campo "Data Criação" do modal de
 *  Convênios não mostrava uma data válida em NENHUMA das três bases.
 *
 *  Duas correções, e a segunda é a que importa: aceitar `dd/mm/aaaa` (com hora
 *  opcional, que é o formato do ES) e, principalmente, o guard de `isNaN` —
 *  sem ele, QUALQUER string não-ISO que chegue aqui vira "Invalid Date" na
 *  cara do cliente. São ~40 usos em 11 arquivos; a mudança é estritamente
 *  melhoria, porque ISO continua idêntico e nada pode depender de receber
 *  "Invalid Date". */
export function formatDate(date: string | null | undefined): string {
  if (!date) return "-";
  const s = String(date).trim();
  const br = s.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
  const iso = br ? `${br[3]}-${br[2]}-${br[1]}` : s.slice(0, 10);
  const d = new Date(iso + "T00:00:00");
  return isNaN(d.getTime()) ? "-" : d.toLocaleDateString("pt-BR");
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
