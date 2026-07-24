"use client";
// Kit de UI do Painel de Indicadores (BI). Estetica "CreditLynx executivo"
// (cards arredondados suaves, KPI tiles, pills de status) MAS na densidade/escala
// NORMAL do Pactha — nada de blocos gigantes. Usa os tokens do app (daisyUI
// pactha/pactha-dark), sem importar o tema do painel/ standalone.
import { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type Tone = "ok" | "warn" | "crit" | "info" | "primary" | "neutral";

const TONE_TEXT: Record<Tone, string> = {
  ok: "text-success",
  warn: "text-warning",
  crit: "text-error",
  info: "text-info",
  primary: "text-primary",
  neutral: "text-base-content/60",
};
const TONE_SOFT: Record<Tone, string> = {
  ok: "bg-success/12 text-success",
  warn: "bg-warning/12 text-warning",
  crit: "bg-error/12 text-error",
  info: "bg-info/12 text-info",
  primary: "bg-primary/10 text-primary",
  neutral: "bg-base-200 text-base-content/60",
};

export function initials(name: string): string {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-2xl border border-base-300 bg-base-100 p-4 shadow-theme-xs", className)}>
      {children}
    </div>
  );
}

export function SectionHead({
  icon: Icon,
  title,
  action,
}: {
  icon?: LucideIcon;
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        {Icon && (
          <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-4" />
          </span>
        )}
        <h3 className="text-sm font-semibold text-base-content">{title}</h3>
      </div>
      {action}
    </div>
  );
}

// KPI tile: icone -> valor -> rotulo -> rodape opcional. Densidade normal.
export function MetricCard({
  icon: Icon,
  label,
  value,
  sub,
  tone = "primary",
  onClick,
}: {
  icon?: LucideIcon;
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        "rounded-2xl border border-base-300 bg-base-100 p-4 shadow-theme-xs transition-all",
        onClick && "cursor-pointer hover:-translate-y-0.5 hover:shadow-theme-md"
      )}
    >
      <div className="flex items-start justify-between gap-2">
        {Icon && (
          <span className={cn("grid size-9 place-items-center rounded-xl", TONE_SOFT[tone])}>
            <Icon className="size-[18px]" />
          </span>
        )}
        {sub != null && <div className="text-right text-[11px] text-base-content/50">{sub}</div>}
      </div>
      <div className="mt-3 text-2xl font-bold leading-none tabular-nums text-base-content">{value}</div>
      <div className="mt-1 text-xs font-medium text-base-content/60">{label}</div>
    </div>
  );
}

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold", TONE_SOFT[tone])}>
      {children}
    </span>
  );
}

export function ToneText({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={TONE_TEXT[tone]}>{children}</span>;
}

// Card de IA (narrativa) — faixa de destaque com "sparkle".
export function AiCard({ children, loading }: { children: ReactNode; loading?: boolean }) {
  return (
    <div className="rounded-2xl border border-primary/20 bg-primary/[0.06] p-4">
      <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold text-primary">
        <span aria-hidden>✦</span> Leitura executiva
      </div>
      <div className={cn("text-sm leading-relaxed text-base-content/80", loading && "animate-pulse")}>
        {children}
      </div>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="grid place-items-center rounded-2xl border border-dashed border-base-300 bg-base-100 p-8 text-center text-sm text-base-content/50">
      {children}
    </div>
  );
}
