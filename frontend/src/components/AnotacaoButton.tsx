"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Edit2 } from "lucide-react";
import api from "@/lib/api";
import AnotacaoModal from "./AnotacaoModal";

interface Props {
  fonte: string;
  fonteRef: string;
  municipioId: number;
  numero?: string;
  size?: "sm" | "md";
}

// Cache global simples de contagem (key = fonte:ref) — preenchido pelo modal
const cache = new Map<string, number>();

export default function AnotacaoButton({ fonte, fonteRef, municipioId, numero, size = "sm" }: Props) {
  const [open, setOpen] = useState(false);
  const [count, setCount] = useState<number>(() => cache.get(`${fonte}:${fonteRef}`) ?? 0);

  const refreshCount = useCallback(async () => {
    try {
      const r = await api.get<{ total: number }>("/gestao/anotacoes/item", {
        params: { fonte, fonte_ref: fonteRef },
      });
      setCount(r.data.total);
      cache.set(`${fonte}:${fonteRef}`, r.data.total);
    } catch { /* silent */ }
  }, [fonte, fonteRef]);

  useEffect(() => {
    // só busca count se não houver no cache (evita N+1 ao renderizar muitas linhas)
    if (!cache.has(`${fonte}:${fonteRef}`)) {
      // delay leve para evitar storm — mas não é critico
      const t = setTimeout(refreshCount, 50);
      return () => clearTimeout(t);
    }
  }, [fonte, fonteRef, refreshCount]);

  const cls = size === "sm" ? "size-6 text-[10px]" : "size-7 text-xs";
  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className={`relative inline-flex ${cls} items-center justify-center rounded ${count > 0 ? "bg-violet-100 hover:bg-violet-200 text-violet-700" : "bg-slate-100 hover:bg-slate-200 text-slate-500"}`}
        title={count > 0 ? `${count} anotação(ões) interna(s)` : "Adicionar anotação interna"}
      >
        <Edit2 className="size-3.5" />
        {count > 0 && (
          <span className="absolute -top-1 -right-1 bg-violet-600 text-white rounded-full size-3.5 text-[8px] font-bold flex items-center justify-center">
            {count > 9 ? "9+" : count}
          </span>
        )}
      </button>
      <AnotacaoModal
        open={open}
        onClose={() => setOpen(false)}
        fonte={fonte} fonteRef={fonteRef} municipioId={municipioId} numeroReferencia={numero}
        onChanged={refreshCount}
      />
    </>
  );
}
