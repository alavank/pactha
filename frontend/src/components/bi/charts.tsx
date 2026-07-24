"use client";
// Graficos do BI — SVG/CSS leves, sem lib. Portados de painel/src/components/charts.tsx
// com os tokens do app (daisyUI) em vez do tema CreditLynx do painel/ standalone.
// Escala NORMAL (rem), nada de vw gigante.
import { formatCurrencyShort } from "@/lib/bi-format";
import { initials, type Tone } from "./ui";

const TONE_VAR: Record<"ok" | "warn" | "crit", string> = {
  ok: "var(--color-success)",
  warn: "var(--color-warning)",
  crit: "var(--color-error)",
};

// Cores categoricas (tokens de grafico do app, tematizados claro/escuro).
export const CHART_COLORS = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

// Gauge semicircular. pct 0..1; tone define a cor do preenchimento.
export function Gauge({
  pct,
  tone = "ok",
  size = 160,
}: {
  pct: number;
  tone?: "ok" | "warn" | "crit";
  size?: number;
}) {
  const p = Math.max(0, Math.min(1, pct || 0));
  const ARC = "M12 112 A98 98 0 0 1 208 112";
  return (
    <svg viewBox="0 0 220 122" width="100%" style={{ maxHeight: size, display: "block" }} aria-hidden="true">
      <path d={ARC} fill="none" stroke="var(--color-base-300)" strokeWidth={16} strokeLinecap="round" />
      <path
        d={ARC}
        fill="none"
        stroke={TONE_VAR[tone]}
        strokeWidth={16}
        strokeLinecap="round"
        pathLength={100}
        strokeDasharray={`${p * 100} 100`}
      />
    </svg>
  );
}

// Barra segmentada estilo CAUC: `total` segmentos, `bad` em vermelho (pendencias).
export function SegBar({ total, bad }: { total: number; bad: number }) {
  const n = Math.max(0, Math.min(Math.round(total || 0), 30));
  const badN = Math.max(0, Math.min(Math.round(bad || 0), n));
  return (
    <div className="flex gap-[3px]" role="img" aria-label={`${n - badN} em dia, ${badN} pendências`}>
      {Array.from({ length: n }).map((_, i) => (
        <span
          key={i}
          className="h-5 flex-1 rounded"
          style={{ background: i >= n - badN ? "var(--color-error)" : "var(--color-success)" }}
        />
      ))}
    </div>
  );
}

// Barra empilhada de composicao por fonte + legenda. So mostra segmentos > 0.
export function FonteStack({ segments }: { segments: { label: string; value: number; color: string }[] }) {
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((s, x) => s + x.value, 0) || 1;
  if (!shown.length) return null;
  return (
    <>
      <div className="mt-1 flex h-3 gap-[2px] overflow-hidden rounded-md">
        {shown.map((s, i) => (
          <span
            key={i}
            className="h-full rounded-[3px]"
            style={{ flexGrow: s.value / total, flexBasis: 0, background: s.color }}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2">
        {shown.map((s, i) => (
          <span key={i} className="flex items-center gap-[7px] text-xs text-base-content/60">
            <span className="size-[9px] rounded-[3px]" style={{ background: s.color }} />
            {s.label} <b className="font-semibold tabular-nums text-base-content">{formatCurrencyShort(s.value)}</b>
          </span>
        ))}
      </div>
    </>
  );
}

// Ranking horizontal (parlamentares). Barra proporcional ao maior valor.
export function RankingBars({ items }: { items: { nome: string; valor: number; sub?: string }[] }) {
  if (!items.length) return null;
  const max = Math.max(...items.map((i) => i.valor), 1);
  return (
    <div className="flex flex-col gap-3.5">
      {items.map((it, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto] items-center gap-x-2.5 gap-y-1">
          <div className="flex min-w-0 items-center gap-2.5">
            <span
              className="grid size-[30px] shrink-0 place-items-center rounded-[9px] text-[11px] font-bold text-white"
              style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
            >
              {initials(it.nome)}
            </span>
            <div className="min-w-0">
              <div className="truncate text-[13.5px] font-semibold text-base-content">{it.nome}</div>
              {it.sub && <div className="text-[11px] text-base-content/50">{it.sub}</div>}
            </div>
          </div>
          <span className="text-[13.5px] font-bold tabular-nums text-base-content">{formatCurrencyShort(it.valor)}</span>
          <div className="col-span-2 h-2 overflow-hidden rounded-[5px] bg-base-300">
            <div
              className="h-full rounded-[5px]"
              style={{
                width: `${(it.valor / max) * 100}%`,
                background: "linear-gradient(90deg, var(--color-primary), var(--color-brand-400))",
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

// Mini-barras (recharts nao necessario aqui) — distribuicao simples horizontal.
export function StatBars({ items, tone = "primary" }: { items: { label: string; value: number }[]; tone?: Tone }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  const color =
    tone === "ok" ? "var(--color-success)" : tone === "crit" ? "var(--color-error)" : "var(--color-primary)";
  return (
    <div className="flex flex-col gap-2">
      {items.map((it, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 text-xs">
          <div className="truncate text-base-content/70">{it.label}</div>
          <div className="font-semibold tabular-nums text-base-content">{it.value}</div>
          <div className="col-span-2 h-1.5 overflow-hidden rounded bg-base-300">
            <div className="h-full rounded" style={{ width: `${(it.value / max) * 100}%`, background: color }} />
          </div>
        </div>
      ))}
    </div>
  );
}
