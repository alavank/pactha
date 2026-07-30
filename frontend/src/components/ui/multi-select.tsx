"use client";
// Dropdown de selecao MULTIPLA.
//
// Nasceu do filtro de anos do FNS: 29 chips de ano ocupavam tres linhas do
// formulario e empurravam o resto da tela para baixo. Um dropdown ocupa uma
// linha e continua permitindo marcar um, alguns ou todos.
//
// E O UNICO multi-select do app. Havia um segundo (components/MultiSelect.tsx,
// usado em Convenios/SIMEC/TransfereGov) com o mesmo proposito e visual
// diferente — dois componentes para a mesma coisa divergem, e o usuario percebe
// que "o filtro de uma tela nao e igual ao da outra". Aquele foi removido e as
// telas migraram para ca.
//
// Convencao: lista VAZIA = "todos". E o mesmo que o backend ja entende (sem
// filtro), e evita o estado sem saida de "nenhum marcado, nenhum resultado".
import * as React from "react";
import { Check, ChevronDown } from "lucide-react";

/** Atalho de seleção (ex.: "Mandato atual", "Todos"). */
export interface AtalhoMulti {
  label: string;
  /** Valores que o atalho aplica. Lista vazia = limpar (= todos). */
  valores: string[];
}

export function MultiSelect({
  opcoes,
  valor,
  onChange,
  rotuloTodos = "Todos",
  formatarResumo,
  placeholder,
  className = "",
  ariaLabel,
  atalhos,
  rotulos,
}: {
  opcoes: string[];
  valor: string[];
  onChange: (v: string[]) => void;
  /** Texto quando nada esta marcado (= todos). */
  rotuloTodos?: string;
  /** Resumo custom (ex.: "2021–2024" para anos contiguos). */
  formatarResumo?: (v: string[]) => string;
  placeholder?: string;
  className?: string;
  ariaLabel?: string;
  /** Atalhos no topo do painel (ex.: "Mandato atual", "Este ano"). */
  atalhos?: AtalhoMulti[];
  /** Rótulo legível por valor, quando o valor é um código ("vence30" -> "Vence em 30 dias"). */
  rotulos?: Record<string, string>;
}) {
  const [aberto, setAberto] = React.useState(false);
  const boxRef = React.useRef<HTMLDivElement | null>(null);

  // Fecha ao clicar fora ou no Esc. Sem isto o painel fica aberto por cima do
  // resultado da consulta, que e justamente o que se quer olhar depois.
  React.useEffect(() => {
    if (!aberto) return;
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setAberto(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setAberto(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [aberto]);

  const alternar = (o: string) => {
    onChange(valor.includes(o) ? valor.filter((x) => x !== o) : [...valor, o]);
  };

  const nome = (v: string) => rotulos?.[v] ?? v;
  const resumo = !valor.length
    ? (placeholder ?? rotuloTodos)
    : formatarResumo
      ? formatarResumo(valor)
      : valor.length === 1
        ? nome(valor[0])
        : `${valor.length} selecionados`;

  return (
    <div ref={boxRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={aberto}
        aria-label={ariaLabel}
        className="mt-1 flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-base-300 bg-base-100 px-3 text-sm text-base-content transition-colors hover:bg-base-200"
      >
        <span className="truncate">{resumo}</span>
        <ChevronDown className={`size-4 shrink-0 opacity-60 transition-transform ${aberto ? "rotate-180" : ""}`} />
      </button>

      {aberto && (
        <div
          role="listbox"
          aria-multiselectable
          className="absolute z-50 mt-1 max-h-72 w-full min-w-[13rem] overflow-y-auto rounded-lg border border-base-300 bg-base-100 p-1 shadow-lg"
        >
          <div className="flex gap-1 border-b border-base-300 px-1 pb-1">
            <button
              type="button"
              onClick={() => onChange([])}
              className="flex-1 rounded px-2 py-1 text-xs font-medium text-base-content/70 hover:bg-base-200"
            >
              {rotuloTodos}
            </button>
            <button
              type="button"
              onClick={() => onChange([...opcoes])}
              className="flex-1 rounded px-2 py-1 text-xs font-medium text-base-content/70 hover:bg-base-200"
            >
              Marcar tudo
            </button>
          </div>

          {/* Atalhos: um clique para o recorte que o gestor pede sempre
              ("o mandato", "este ano"). Sem eles, marcar 4 anos é 4 cliques. */}
          {!!atalhos?.length && (
            <div className="flex flex-wrap gap-1 border-b border-base-300 px-1 py-1.5">
              {atalhos.map((a) => (
                <button
                  key={a.label}
                  type="button"
                  onClick={() => onChange([...a.valores])}
                  className="rounded-full border border-base-300 px-2 py-0.5 text-[11px] font-medium text-base-content/70 hover:bg-base-200"
                >
                  {a.label}
                </button>
              ))}
            </div>
          )}
          {opcoes.map((o) => {
            const on = valor.includes(o);
            return (
              <button
                key={o}
                type="button"
                role="option"
                aria-selected={on}
                onClick={() => alternar(o)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-base-200"
              >
                <span
                  className={`grid size-4 shrink-0 place-items-center rounded border ${
                    on ? "border-primary bg-primary text-primary-content" : "border-base-300"
                  }`}
                >
                  {on && <Check className="size-3" />}
                </span>
                <span className="truncate">{nome(o)}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** "2021, 2022, 2023, 2024" vira "2021–2024"; sequencias quebradas viram lista. */
export function resumoAnos(v: string[]): string {
  const ns = [...v].map(Number).filter(Boolean).sort((a, b) => a - b);
  if (!ns.length) return "";
  if (ns.length === 1) return String(ns[0]);
  const contiguo = ns.every((n, i) => i === 0 || n === ns[i - 1] + 1);
  if (contiguo) return `${ns[0]}–${ns[ns.length - 1]}`;
  return ns.length <= 3 ? ns.join(", ") : `${ns.length} anos`;
}
