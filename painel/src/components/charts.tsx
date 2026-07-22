import { formatCurrencyShort } from "@/lib/format";
import { initials } from "./ui";

// Gauge semicircular (SVG). pct 0..1. tone define a cor do preenchimento.
export function Gauge({ pct, tone = "ok" }: { pct: number; tone?: "ok" | "warn" | "crit" }) {
  const color = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)" : "var(--crit)";
  const p = Math.max(0, Math.min(1, pct || 0));
  const ARC = "M12 112 A98 98 0 0 1 208 112";
  return (
    <svg viewBox="0 0 220 122" width="100%" style={{ maxHeight: 180, display: "block" }} aria-hidden="true">
      <path d={ARC} fill="none" stroke="var(--surface-3)" strokeWidth={18} strokeLinecap="round" />
      <path
        d={ARC}
        fill="none"
        stroke={color}
        strokeWidth={18}
        strokeLinecap="round"
        pathLength={100}
        strokeDasharray={`${p * 100} 100`}
      />
    </svg>
  );
}

// Barra segmentada estilo CAUC: `total` segmentos, `bad` deles em coral (pendências).
export function SegBar({ total, bad }: { total: number; bad: number }) {
  const n = Math.max(0, Math.min(Math.round(total || 0), 30));
  const badN = Math.max(0, Math.min(Math.round(bad || 0), n));
  return (
    <div className="flex gap-[3px]" role="img" aria-label={`${n - badN} em dia, ${badN} pendências`}>
      {Array.from({ length: n }).map((_, i) => (
        <span
          key={i}
          className="h-6 flex-1 rounded"
          style={{ background: i >= n - badN ? "var(--crit)" : "var(--c-green)" }}
        />
      ))}
    </div>
  );
}

// Barra empilhada de composição por fonte + legenda. Só mostra segmentos > 0.
export function FonteStack({ segments }: { segments: { label: string; value: number; color: string }[] }) {
  const shown = segments.filter((s) => s.value > 0);
  const total = shown.reduce((s, x) => s + x.value, 0) || 1;
  if (!shown.length) return null;
  return (
    <>
      <div className="flex h-3 rounded-md overflow-hidden gap-[2px] mt-1">
        {shown.map((s, i) => (
          <span key={i} className="h-full rounded-[3px]" style={{ flexGrow: s.value / total, flexBasis: 0, background: s.color }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-2 mt-3">
        {shown.map((s, i) => (
          <span key={i} className="flex items-center gap-[7px] text-xs text-ink-2">
            <span className="w-[9px] h-[9px] rounded-[3px]" style={{ background: s.color }} />
            {s.label} <b className="text-ink font-semibold tnum">{formatCurrencyShort(s.value)}</b>
          </span>
        ))}
      </div>
    </>
  );
}

// Ranking horizontal (parlamentares). Barra proporcional ao maior valor.
const AV_COLORS = ["#2f6b3a", "#57a6e6", "#b98ce0", "#f2b34a", "#68cf56"];
export function RankingBars({ items }: { items: { nome: string; valor: number; sub?: string }[] }) {
  const max = Math.max(...items.map((i) => i.valor), 1);
  return (
    <div className="flex flex-col gap-3.5">
      {items.map((it, i) => (
        <div key={i} className="grid grid-cols-[1fr_auto] gap-x-2.5 gap-y-1 items-center">
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className="w-[30px] h-[30px] rounded-[9px] grid place-items-center text-white font-display font-bold text-[11px] shrink-0"
              style={{ background: AV_COLORS[i % AV_COLORS.length] }}
            >
              {initials(it.nome)}
            </span>
            <div className="min-w-0">
              <div className="text-[13.5px] font-semibold truncate">{it.nome}</div>
              {it.sub && <div className="text-[11px] text-ink-3">{it.sub}</div>}
            </div>
          </div>
          <span className="font-display font-bold text-[13.5px] tnum">{formatCurrencyShort(it.valor)}</span>
          <div className="col-span-2 h-2 rounded-[5px] bg-surface-3 overflow-hidden">
            <div
              className="h-full rounded-[5px]"
              style={{ width: `${(it.valor / max) * 100}%`, background: "linear-gradient(90deg,var(--accent-strong),var(--accent))" }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
