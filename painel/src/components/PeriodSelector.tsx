"use client";
import { usePeriod, ANOS } from "@/lib/period";
import { cn } from "./ui";

// Seletor de ano (segmented, rolável no mobile). Muda o período de todas as telas.
export function PeriodSelector({ className }: { className?: string }) {
  const { ano, setAno } = usePeriod();
  return (
    <div className={cn("flex gap-1.5 overflow-x-auto no-scrollbar -mx-4 px-4 py-0.5", className)}>
      {ANOS.map((a) => {
        const on = ano === a;
        return (
          <button
            key={String(a)}
            type="button"
            onClick={() => setAno(a)}
            aria-pressed={on}
            className={cn(
              "px-3.5 py-1.5 rounded-full text-[12.5px] font-semibold whitespace-nowrap border transition-colors shrink-0",
              on ? "bg-cta text-cta-ink border-transparent" : "bg-surface text-ink-2 border-line active:bg-surface-2"
            )}
          >
            {a == null ? "Todos" : a}
          </button>
        );
      })}
    </div>
  );
}
