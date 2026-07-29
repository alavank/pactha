"use client";
// Kit visual do Painel de Indicadores (BI) — traduz design-tela/ em componentes.
//
// Regras que vieram da referencia e valem para tudo aqui:
//   - cartao com raio grande, borda de 1px quase invisivel, ZERO peso extra;
//   - titulo de secao = quadradinho arredondado com icone + texto pequeno;
//   - o numero e a estrela: grande, tabular, apertado; o rotulo fica discreto;
//   - paleta de grafico pastel (coral/ambar/menta/azul/violeta), nunca a cor
//     da marca do sistema — o BI destoa de proposito;
//   - nada de sombra dura nem gradiente de fundo em cartao de dado.
//
// Tudo depende das variaveis --bi-* definidas em globals.css (`.bi-skin`).
import React from "react";
import { cn } from "@/lib/utils";

export const BI_CORES = ["var(--bi-c1)", "var(--bi-c2)", "var(--bi-c3)", "var(--bi-c4)", "var(--bi-c5)"];

export type Tom = "neutro" | "ok" | "warn" | "crit" | "accent";

const TOM_COR: Record<Tom, string> = {
  neutro: "var(--bi-muted)",
  ok: "var(--bi-ok)",
  warn: "var(--bi-warn)",
  crit: "var(--bi-crit)",
  accent: "var(--bi-accent)",
};

// --------------------------------------------------------------------------
// Estrutura
// --------------------------------------------------------------------------

export function Painel({
  children,
  className,
  padding = true,
}: {
  children: React.ReactNode;
  className?: string;
  padding?: boolean;
}) {
  return (
    <div className={cn("bi-card flex min-h-0 flex-col", padding && "p-4", className)}>
      {children}
    </div>
  );
}

export function PainelHead({
  icon: Icon,
  titulo,
  sub,
  right,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  titulo: string;
  sub?: string;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-center gap-2.5", className)}>
      {Icon && (
        <span
          className="grid size-8 shrink-0 place-items-center rounded-xl"
          style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}
        >
          <Icon className="size-4" />
        </span>
      )}
      <div className="min-w-0">
        <div className="bi-title truncate text-[15px] leading-tight">{titulo}</div>
        {sub && (
          <div className="truncate text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {sub}
          </div>
        )}
      </div>
      {right && <div className="ml-auto flex shrink-0 items-center gap-1.5">{right}</div>}
    </div>
  );
}

/** Cabecalho de pagina: sobrenome pequeno + titulo grande (ver referencia). */
export function PageHead({
  eyebrow,
  titulo,
  right,
}: {
  eyebrow?: string;
  titulo: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end gap-x-4 gap-y-3">
      <div className="min-w-0">
        {eyebrow && (
          <div className="text-[12px]" style={{ color: "var(--bi-muted)" }}>
            {eyebrow}
          </div>
        )}
        <h1 className="bi-title text-[26px] leading-tight sm:text-[30px]">{titulo}</h1>
      </div>
      {right && <div className="ml-auto flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------
// Atomos
// --------------------------------------------------------------------------

export function Chip({
  children,
  tom = "neutro",
  className,
}: {
  children: React.ReactNode;
  tom?: Tom;
  className?: string;
}) {
  const cor = TOM_COR[tom];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold",
        className
      )}
      style={{ color: cor, background: `color-mix(in srgb, ${cor} 14%, transparent)` }}
    >
      {children}
    </span>
  );
}

export function BotaoIcone({
  children,
  onClick,
  title,
  ativo,
  disabled,
  className,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  title?: string;
  ativo?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className={cn(
        "grid size-8 place-items-center rounded-xl transition-colors disabled:opacity-40",
        className
      )}
      style={{
        background: ativo ? "var(--bi-accent-soft)" : "var(--bi-surface-2)",
        border: "1px solid var(--bi-line)",
        color: ativo ? "var(--bi-accent)" : "var(--bi-muted)",
      }}
    >
      {children}
    </button>
  );
}

/** Grupo de pilulas segmentadas (TransUnion | Equifax | Experian na referencia). */
export function SegTabs<T extends string>({
  value,
  onChange,
  options,
  size = "md",
}: {
  value: T;
  onChange: (v: T) => void;
  options: Array<{ value: T; label: string }>;
  size?: "sm" | "md";
}) {
  return (
    <div
      className="inline-flex flex-wrap items-center gap-1 rounded-full p-1"
      style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}
    >
      {options.map((o) => {
        const ativo = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={cn(
              "rounded-full font-medium transition-colors",
              size === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3 py-1.5 text-xs"
            )}
            style={{
              background: ativo ? "var(--bi-surface)" : "transparent",
              color: ativo ? "var(--bi-text)" : "var(--bi-muted)",
              border: ativo ? "1px solid var(--bi-line)" : "1px solid transparent",
              fontWeight: ativo ? 700 : 500,
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export function Vazio({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="grid flex-1 place-items-center px-3 py-6 text-center text-[12px]"
      style={{ color: "var(--bi-faint)" }}
    >
      {children}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("animate-pulse rounded-2xl", className)}
      style={{ background: "var(--bi-surface-2)" }}
    />
  );
}

// --------------------------------------------------------------------------
// KPI
// --------------------------------------------------------------------------

export function Metric({
  label,
  valor,
  sub,
  icon: Icon,
  tom = "neutro",
  grande,
}: {
  label: string;
  valor: React.ReactNode;
  sub?: React.ReactNode;
  icon?: React.ComponentType<{ className?: string }>;
  tom?: Tom;
  grande?: boolean;
}) {
  const cor = TOM_COR[tom];
  return (
    <div className="bi-card flex flex-col justify-between gap-2 p-3.5">
      <div className="flex items-center gap-2">
        {Icon && (
          <span
            className="grid size-7 shrink-0 place-items-center rounded-lg"
            style={{ background: `color-mix(in srgb, ${cor} 14%, transparent)`, color: cor }}
          >
            <Icon className="size-3.5" />
          </span>
        )}
        <span className="truncate text-[11px] font-medium" style={{ color: "var(--bi-muted)" }}>
          {label}
        </span>
      </div>
      <div>
        <div
          className={cn("bi-num leading-none", grande ? "text-[30px]" : "text-[22px]")}
          style={{ color: tom === "neutro" ? "var(--bi-text)" : cor }}
        >
          {valor}
        </div>
        {sub && (
          <div className="mt-1 truncate text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {sub}
          </div>
        )}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Graficos (SVG na mao — leves, sem lib, e batem com a referencia)
// --------------------------------------------------------------------------

/** Medidor em arco com gradiente (o "850 Excellent" da referencia). */
export function Gauge({
  pct,
  centro,
  legenda,
  tom = "ok",
  size = 168,
}: {
  pct: number;
  centro: React.ReactNode;
  legenda?: string;
  tom?: Tom;
  size?: number;
}) {
  const p = Math.max(0, Math.min(1, pct || 0));
  const r = 54;
  const circ = Math.PI * r; // meia volta
  const id = React.useId();
  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 140 82" width={size} height={size * 0.586} role="img" aria-label={legenda}>
        <defs>
          <linearGradient id={`g-${id}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--bi-c1)" />
            <stop offset="45%" stopColor="var(--bi-c2)" />
            <stop offset="100%" stopColor="var(--bi-c3)" />
          </linearGradient>
        </defs>
        <path
          d={`M 16 70 A ${r} ${r} 0 0 1 124 70`}
          fill="none"
          stroke="var(--bi-line)"
          strokeWidth="13"
          strokeLinecap="round"
        />
        <path
          d={`M 16 70 A ${r} ${r} 0 0 1 124 70`}
          fill="none"
          stroke={`url(#g-${id})`}
          strokeWidth="13"
          strokeLinecap="round"
          strokeDasharray={`${circ * p} ${circ}`}
          style={{ transition: "stroke-dasharray .6s ease" }}
        />
      </svg>
      <div className="-mt-6 text-center">
        <div className="bi-num text-[26px] leading-none" style={{ color: TOM_COR[tom] }}>
          {centro}
        </div>
        {legenda && (
          <div className="mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {legenda}
          </div>
        )}
      </div>
    </div>
  );
}

/** Barra de "bolinhas" coloridas (Credit Utilization da referencia). */
export function DotMeter({
  label,
  pct,
  direita,
  dots = 26,
}: {
  label: string;
  pct: number;
  direita?: React.ReactNode;
  dots?: number;
}) {
  const p = Math.max(0, Math.min(1, pct || 0));
  const cheios = Math.round(dots * p);
  return (
    <div className="py-1.5">
      <div className="mb-1 flex items-baseline gap-2">
        <span className="truncate text-[12px]" style={{ color: "var(--bi-muted)" }}>
          {label}
        </span>
        <span className="bi-num ml-auto text-[12px]" style={{ color: "var(--bi-text)" }}>
          {direita ?? `${Math.round(p * 100)}%`}
        </span>
      </div>
      <div className="flex items-center gap-[3px]">
        <span className="size-1.5 shrink-0 rounded-full" style={{ background: "var(--bi-text)" }} />
        {Array.from({ length: dots }).map((_, i) => (
          <span
            key={i}
            className="h-1.5 flex-1 rounded-full"
            style={{
              background:
                i < cheios ? BI_CORES[i % BI_CORES.length] : "var(--bi-line)",
              opacity: i < cheios ? 1 : 0.7,
            }}
          />
        ))}
      </div>
    </div>
  );
}

/** Barras verticais finas com gradiente (o grafico do "My Balance"). */
export function GradientBars({
  items,
  altura = 120,
}: {
  items: Array<{ label: string; valor: number }>;
  altura?: number;
}) {
  const max = Math.max(1, ...items.map((i) => i.valor));
  const id = React.useId();
  if (!items.length) return <Vazio>Sem série no período.</Vazio>;
  return (
    <div>
      <svg
        viewBox={`0 0 ${Math.max(items.length * 10, 40)} 100`}
        preserveAspectRatio="none"
        style={{ width: "100%", height: altura }}
        role="img"
      >
        <defs>
          <linearGradient id={`b-${id}`} x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor="var(--bi-c1)" />
            <stop offset="50%" stopColor="var(--bi-c2)" />
            <stop offset="100%" stopColor="var(--bi-c3)" />
          </linearGradient>
        </defs>
        {items.map((it, i) => {
          const h = Math.max(2, (it.valor / max) * 92);
          return (
            <rect
              key={i}
              x={i * 10 + 3.2}
              y={100 - h}
              width={3.6}
              height={h}
              rx={1.8}
              fill={`url(#b-${id})`}
            />
          );
        })}
      </svg>
      <div className="mt-1 flex justify-between text-[10px]" style={{ color: "var(--bi-faint)" }}>
        {items.map((it, i) => (
          <span key={i} className="flex-1 text-center">
            {it.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** Barra empilhada horizontal + legenda (composicao de fontes). */
export function StackBar({
  segments,
}: {
  segments: Array<{ label: string; valor: number; cor?: string }>;
}) {
  const total = segments.reduce((s, x) => s + Math.max(0, x.valor || 0), 0);
  return (
    <div>
      <div
        className="flex h-2.5 w-full overflow-hidden rounded-full"
        style={{ background: "var(--bi-line)" }}
      >
        {segments.map((s, i) => (
          <div
            key={i}
            style={{
              width: total ? `${(Math.max(0, s.valor) / total) * 100}%` : "0%",
              background: s.cor || BI_CORES[i % BI_CORES.length],
            }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5 text-[11px]">
            <span
              className="size-2 rounded-full"
              style={{ background: s.cor || BI_CORES[i % BI_CORES.length] }}
            />
            <span style={{ color: "var(--bi-muted)" }}>{s.label}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** Ranking horizontal: nome, valor e barra proporcional. */
export function RankBars({
  items,
  formatar,
}: {
  items: Array<{ nome: string; valor: number; sub?: string }>;
  formatar: (v: number) => string;
}) {
  const max = Math.max(1, ...items.map((i) => i.valor));
  if (!items.length) return <Vazio>Nada no período selecionado.</Vazio>;
  return (
    <ul className="flex flex-col gap-2.5">
      {items.map((it, i) => (
        <li key={`${it.nome}-${i}`}>
          <div className="mb-1 flex items-baseline gap-2">
            <span className="truncate text-[12px] font-medium">{it.nome}</span>
            <span className="bi-num ml-auto shrink-0 text-[12px]">{formatar(it.valor)}</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--bi-line)" }}>
            <div
              className="h-full rounded-full"
              style={{
                width: `${(it.valor / max) * 100}%`,
                background: BI_CORES[i % BI_CORES.length],
                transition: "width .5s ease",
              }}
            />
          </div>
          {it.sub && (
            <div className="mt-0.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
              {it.sub}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Lista compacta chave→valor com barra de fundo (rollups por situacao/orgao). */
export function ListaRollup({
  items,
  formatar,
  max: maxItens = 6,
}: {
  items: Array<{ label: string; qtd: number; valor: number }>;
  formatar: (v: number) => string;
  max?: number;
}) {
  const vis = items.slice(0, maxItens);
  const max = Math.max(1, ...vis.map((i) => i.valor));
  if (!vis.length) return <Vazio>Sem dados.</Vazio>;
  return (
    <ul className="flex flex-col gap-1.5">
      {vis.map((it, i) => (
        <li key={it.label} className="relative overflow-hidden rounded-lg px-2 py-1.5">
          <span
            className="absolute inset-y-0 left-0 rounded-lg"
            style={{
              width: `${(it.valor / max) * 100}%`,
              background: BI_CORES[i % BI_CORES.length],
              opacity: 0.14,
            }}
          />
          <span className="relative flex items-baseline gap-2">
            <span className="truncate text-[12px]">{it.label}</span>
            <span className="ml-auto shrink-0 text-[10px]" style={{ color: "var(--bi-faint)" }}>
              {it.qtd}
            </span>
            <span className="bi-num shrink-0 text-[12px]">{formatar(it.valor)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
