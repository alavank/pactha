import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { Sparkles } from "lucide-react";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function initials(nome: string): string {
  const parts = (nome || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("bg-surface border border-line rounded-[22px] shadow-card p-4", className)}>
      {children}
    </div>
  );
}

export function SectionHead({
  icon,
  title,
  right,
}: {
  icon?: React.ReactNode;
  title: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2.5 mb-3">
      {icon && (
        <span className="w-[30px] h-[30px] rounded-[9px] bg-surface-2 grid place-items-center text-ink-2 shrink-0">
          {icon}
        </span>
      )}
      <h3 className="text-[14.5px] font-bold tracking-tight">{title}</h3>
      {right && <div className="ml-auto text-xs text-ink-3 flex items-center gap-1.5">{right}</div>}
    </div>
  );
}

type Tone = "ok" | "warn" | "crit" | "accent" | "muted";
const toneCls: Record<Tone, string> = {
  ok: "text-ok bg-ok-soft",
  warn: "text-warn bg-warn-soft",
  crit: "text-crit bg-crit-soft",
  accent: "text-accent-ink bg-accent-soft",
  muted: "text-ink-2 bg-surface-2",
};

export function Pill({
  tone = "muted",
  children,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-[5px] rounded-full",
        toneCls[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

export function AiCard({ children, tag = "Resumo do dia" }: { children: React.ReactNode; tag?: string }) {
  return (
    <div
      className="rounded-[22px] border border-line shadow-card p-4 relative overflow-hidden"
      style={{ background: "radial-gradient(140% 120% at 0% 0%, var(--accent-soft), transparent 55%), var(--surface)" }}
    >
      <span
        className="inline-flex items-center gap-[7px] text-[11px] font-bold uppercase tracking-wide px-2.5 py-[5px] rounded-full"
        style={{ color: "var(--accent-ink)", background: "var(--accent-soft)" }}
      >
        <Sparkles size={13} /> {tag}
      </span>
      <p className="mt-3 text-[14.5px] leading-relaxed text-ink">{children}</p>
    </div>
  );
}
