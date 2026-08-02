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

/** Carrega a contagem de uma LISTA inteira numa requisição só.
 *
 *  O caminho individual (`GET /anotacoes/item`) devolve as anotações COM OS
 *  ANEXOS EM BASE64 — para exibir um número. Numa tela de 20 linhas eram 20
 *  requisições, cada uma podendo trazer megabytes de arquivo; e o cache de
 *  módulo só ajudava a partir da SEGUNDA visita.
 *
 *  Quem renderiza uma lista chama isto uma vez, logo depois de receber os
 *  dados. Aí todo botão já nasce com o número no cache e nenhum vai à rede.
 *  Item sem anotação não volta na resposta — vira 0, e fica no cache como 0
 *  para não ser buscado de novo. */
export async function precarregarContagens(fonte: string, refs: string[]) {
  const faltando = refs.filter((r) => r && !cache.has(`${fonte}:${r}`));
  if (!faltando.length) return;
  try {
    const r = await api.post<Record<string, number>>("/gestao/anotacoes/contagens", {
      fonte, refs: faltando,
    });
    for (const ref of faltando) cache.set(`${fonte}:${ref}`, r.data[ref] ?? 0);
    // Avisa os botões já montados: eles leem o cache no próximo render.
    ouvintes.forEach((f) => f());
  } catch { /* silent: o botão cai no caminho individual */ }
}

/** Os botões já montados quando o lote chega. Sem isto, quem renderizou antes
 *  da resposta ficaria com 0 até um novo render. */
const ouvintes = new Set<() => void>();

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
    // Reage ao lote (`precarregarContagens`) chegando depois deste render.
    const aviso = () => setCount(cache.get(`${fonte}:${fonteRef}`) ?? 0);
    ouvintes.add(aviso);
    return () => { ouvintes.delete(aviso); };
  }, [fonte, fonteRef]);

  useEffect(() => {
    // Caminho individual: só quando o lote não cobriu este item. A espera dá
    // tempo de o `precarregarContagens` da tela responder antes — sem ela,
    // toda linha dispararia a requisição cara antes de o lote voltar.
    if (cache.has(`${fonte}:${fonteRef}`)) return;
    const t = setTimeout(() => {
      if (!cache.has(`${fonte}:${fonteRef}`)) refreshCount();
    }, 600);
    return () => clearTimeout(t);
  }, [fonte, fonteRef, refreshCount]);

  const cls = size === "sm" ? "size-6 text-[10px]" : "size-7 text-xs";
  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(true); }}
        className={`relative inline-flex ${cls} items-center justify-center rounded ${count > 0 ? "bg-info/15 hover:bg-info/25 text-info" : "bg-base-200 hover:bg-base-300 text-base-content/60"}`}
        title={count > 0 ? `${count} anotação(ões) interna(s)` : "Adicionar anotação interna"}
      >
        <Edit2 className="size-3.5" />
        {count > 0 && (
          <span className="absolute -top-1 -right-1 bg-info text-info-content rounded-full size-3.5 text-[8px] font-bold flex items-center justify-center">
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
