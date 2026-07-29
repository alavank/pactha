"use client";
// Filtros do Painel de Indicadores: escopo (município / consolidado) e PERÍODO
// MULTI-ANO. O prefeito filtra o mandato (ex.: 2021 a 2024), não um ano solto —
// por isso os anos são pastilhas que ligam e desligam, e não um <select>.
//
// Estes filtros valem para o módulo E para o Modo Tela: quem abre a janela
// manda o filtro junto, e toda mudança é empurrada pelo BroadcastChannel.
import { useMemo, useRef, useState, useEffect } from "react";
import { Check, ChevronDown, CalendarRange } from "lucide-react";
import { Municipio } from "@/lib/bi";
import { useBiScope, CONSOLIDADO } from "@/contexts/BiScopeContext";
import { cn } from "@/lib/utils";

/** Anos oferecidos: do corrente para trás (cobre com folga um mandato). */
export function anosDisponiveis(qtd = 8): number[] {
  const y = new Date().getFullYear();
  return Array.from({ length: qtd }, (_, i) => y - i);
}

/** Rótulo curto do período para cabeçalhos ("2021–2024", "2025", "Todos"). */
export function rotuloPeriodo(anos: number[]): string {
  if (!anos.length) return "Todos os anos";
  if (anos.length === 1) return String(anos[0]);
  const min = anos[0];
  const max = anos[anos.length - 1];
  const contiguo = anos.length === max - min + 1;
  return contiguo ? `${min}–${max}` : anos.join(", ");
}

export function EscopoSelect({
  municipios,
  podeConsolidado,
}: {
  municipios: Municipio[];
  podeConsolidado: boolean;
}) {
  const { scope, setScope } = useBiScope();

  if (municipios.length <= 1 && !podeConsolidado) {
    const m = municipios[0];
    return (
      <span
        className="inline-flex items-center rounded-full px-3 py-1.5 text-xs font-semibold"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
      >
        {m ? `${m.nome} — ${m.uf}` : "—"}
      </span>
    );
  }

  return (
    <select
      value={scope}
      onChange={(e) => setScope(e.target.value)}
      aria-label="Escopo do painel"
      className="rounded-full px-3 py-1.5 text-xs font-medium outline-none"
      style={{
        background: "var(--bi-surface)",
        border: "1px solid var(--bi-line)",
        color: "var(--bi-text)",
      }}
    >
      {podeConsolidado && <option value={CONSOLIDADO}>Consolidado (todos)</option>}
      {municipios.map((m) => (
        <option key={m.id} value={String(m.id)}>
          {m.nome} — {m.uf}
        </option>
      ))}
    </select>
  );
}

export function PeriodoMultiSelect({ anos: opcoes = anosDisponiveis() }: { anos?: number[] }) {
  const { anos, setAnos, alternarAno } = useBiScope();
  const [aberto, setAberto] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setAberto(false);
    };
    document.addEventListener("mousedown", fora);
    return () => document.removeEventListener("mousedown", fora);
  }, [aberto]);

  const rotulo = useMemo(() => rotuloPeriodo(anos), [anos]);
  const mandato = useMemo(() => {
    // Atalho do mandato vigente (2025–2028 para a gestão eleita em 2024).
    const y = new Date().getFullYear();
    const inicio = y - ((y - 2025) % 4 + 4) % 4;
    return [inicio, inicio + 1, inicio + 2, inicio + 3].filter((a) => a <= y);
  }, []);

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        aria-haspopup="dialog"
        className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium"
        style={{
          background: "var(--bi-surface)",
          border: "1px solid var(--bi-line)",
          color: "var(--bi-text)",
        }}
      >
        <CalendarRange className="size-3.5" style={{ color: "var(--bi-muted)" }} />
        {rotulo}
        <ChevronDown className={cn("size-3.5 transition-transform", aberto && "rotate-180")} />
      </button>

      {aberto && (
        <div
          className="absolute right-0 z-40 mt-1.5 w-[16.5rem] rounded-2xl p-3"
          style={{
            background: "var(--bi-surface)",
            border: "1px solid var(--bi-line)",
            boxShadow: "var(--bi-shadow)",
          }}
          role="dialog"
          aria-label="Selecionar período"
        >
          <div className="mb-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Selecione um ou mais anos
          </div>
          <div className="grid grid-cols-4 gap-1.5">
            {opcoes.map((a) => {
              const on = anos.includes(a);
              return (
                <button
                  key={a}
                  type="button"
                  onClick={() => alternarAno(a)}
                  className="rounded-xl py-1.5 text-[12px] font-semibold transition-colors"
                  style={{
                    background: on ? "var(--bi-accent-soft)" : "var(--bi-surface-2)",
                    border: `1px solid ${on ? "var(--bi-accent)" : "var(--bi-line)"}`,
                    color: on ? "var(--bi-accent)" : "var(--bi-muted)",
                  }}
                  aria-pressed={on}
                >
                  {a}
                </button>
              );
            })}
          </div>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            <AtalhoPeriodo label="Mandato atual" onClick={() => setAnos(mandato)} />
            <AtalhoPeriodo label="Este ano" onClick={() => setAnos([new Date().getFullYear()])} />
            <AtalhoPeriodo
              label="Todos"
              onClick={() => setAnos([])}
              ativo={anos.length === 0}
            />
          </div>
          {anos.length > 0 && (
            <div className="mt-2 flex items-center gap-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              <Check className="size-3" /> {anos.length} ano(s) no filtro
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AtalhoPeriodo({
  label,
  onClick,
  ativo,
}: {
  label: string;
  onClick: () => void;
  ativo?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-full px-2.5 py-1 text-[11px] font-medium"
      style={{
        background: ativo ? "var(--bi-accent-soft)" : "var(--bi-surface-2)",
        border: "1px solid var(--bi-line)",
        color: ativo ? "var(--bi-accent)" : "var(--bi-muted)",
      }}
    >
      {label}
    </button>
  );
}
