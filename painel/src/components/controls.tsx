import { cn } from "./ui";

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="pt-3 pb-4">
      <h1 className="text-[24px] font-extrabold tracking-tight leading-none">{title}</h1>
      {subtitle && <div className="text-[13px] text-ink-2 mt-1">{subtitle}</div>}
    </div>
  );
}

export function Switch({ checked, onChange }: { checked: boolean; onChange: () => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onChange}
      className={cn("w-[46px] h-[27px] rounded-full p-[3px] transition-colors shrink-0", checked ? "bg-accent-strong" : "bg-surface-3")}
    >
      <span className={cn("block w-[21px] h-[21px] rounded-full bg-white shadow-sm transition-transform", checked && "translate-x-[19px]")} />
    </button>
  );
}

export function Loading() {
  return (
    <div className="pt-20 flex flex-col items-center gap-3 text-ink-3">
      <div className="w-8 h-8 rounded-full border-2 border-line border-t-accent-strong animate-spin" />
      <div className="text-sm">Carregando…</div>
    </div>
  );
}
