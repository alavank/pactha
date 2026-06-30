"use client";

import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";

interface MultiSelectProps {
  options: string[];
  selected: string[];
  onChange: (vals: string[]) => void;
  placeholder?: string;
  width?: string; // ex: "w-56"
}

/**
 * Filtro seletor multiplo (checkboxes em dropdown). Permite marcar uma, varias
 * ou nenhuma opcao. Usado nos filtros de situacao das telas.
 */
export default function MultiSelect({
  options,
  selected,
  onChange,
  placeholder = "Situacao",
  width = "w-56",
}: MultiSelectProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const toggle = (opt: string) => {
    if (selected.includes(opt)) onChange(selected.filter((s) => s !== opt));
    else onChange([...selected, opt]);
  };

  const label =
    selected.length === 0
      ? placeholder
      : selected.length === 1
      ? selected[0]
      : `${selected.length} selecionadas`;

  return (
    <div ref={ref} className={`relative ${width}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-8 w-full items-center justify-between gap-1.5 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none hover:bg-base-200"
      >
        <span className={`truncate text-left ${selected.length === 0 ? "text-muted-foreground" : ""}`}>
          {label}
        </span>
        <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 max-h-72 w-full min-w-56 overflow-y-auto rounded-lg border bg-base-100 p-1 shadow-md">
          {selected.length > 0 && (
            <button
              type="button"
              onClick={() => onChange([])}
              className="mb-1 w-full rounded px-2 py-1 text-left text-xs font-medium text-primary hover:bg-base-200"
            >
              Limpar selecao ({selected.length})
            </button>
          )}
          {options.length === 0 && (
            <div className="px-2 py-2 text-xs text-base-content/40">Nenhuma opcao</div>
          )}
          {options.map((opt) => {
            const checked = selected.includes(opt);
            return (
              <button
                key={opt}
                type="button"
                onClick={() => toggle(opt)}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-base-200"
              >
                <span
                  className={`flex size-4 shrink-0 items-center justify-center rounded border ${
                    checked ? "border-primary bg-primary text-white" : "border-base-300"
                  }`}
                >
                  {checked && <Check className="size-3" />}
                </span>
                <span className="truncate">{opt}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
