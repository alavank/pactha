"use client";

import React, { useState } from "react";
import { Link2, X, Loader2 } from "lucide-react";
import api from "@/lib/api";

export interface RelacionadosParams {
  municipio_id?: string | number;
  municipio_nome?: string; // alternativa (FNS usa nome)
  fonte: string; // convenios | plano-acao | emendas | fns | voluntarias
  proposta?: string;
  plano?: string;
  instrumento?: string;
  siafi?: string;
  processo?: string;
  parlamentar?: string;
  objeto?: string;
}

interface Match {
  titulo: string;
  subtitulo: string;
  valor?: number | null;
  chave_match: string;
  score: number;
}
interface Grupo { fonte: string; tela: string; matches: Match[]; }
interface Resp { origem: Record<string, unknown>; grupos: Grupo[]; total: number; }

function fmtMoeda(v?: number | null): string {
  if (v === null || v === undefined) return "";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/** Botao-icone que abre modal de lancamentos relacionados em outras fontes. */
export default function RelacionadosButton({ params, label }: { params: RelacionadosParams; label?: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<Resp | null>(null);

  const abrir = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen(true);
    setLoading(true);
    setData(null);
    try {
      const qs: Record<string, string> = { fonte: params.fonte };
      if (params.municipio_id) qs.municipio_id = String(params.municipio_id);
      if (params.municipio_nome) qs.municipio_nome = String(params.municipio_nome);
      for (const k of ["proposta", "plano", "instrumento", "siafi", "processo", "parlamentar", "objeto"] as const) {
        const v = params[k];
        if (v) qs[k] = String(v);
      }
      const r = await api.get<Resp>("/relacionados", { params: qs });
      setData(r.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <button
        onClick={abrir}
        title="Lançamentos relacionados em outras fontes"
        className="inline-flex items-center justify-center gap-1 rounded bg-indigo-500 hover:bg-indigo-600 text-white px-1.5 h-6 text-[10px]"
      >
        <Link2 className="size-3" />
        {label}
      </button>

      {open && (
        <div className="fixed inset-0 z-[70] bg-black/50 flex items-start justify-center p-4 overflow-y-auto"
             onClick={() => setOpen(false)}>
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-3xl mt-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-indigo-50 px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-indigo-900 flex items-center gap-2">
                <Link2 className="size-4" /> Lançamentos Relacionados
              </h3>
              <button onClick={() => setOpen(false)}><X className="size-5 text-gray-500 hover:text-gray-700" /></button>
            </div>
            <div className="p-4 max-h-[70vh] overflow-y-auto">
              {loading ? (
                <div className="text-center py-10"><Loader2 className="size-7 animate-spin mx-auto text-indigo-600" /></div>
              ) : !data || data.total === 0 ? (
                <p className="text-sm text-slate-500 italic text-center py-8">
                  Nenhum lançamento relacionado encontrado em outras fontes
                  (cruzando proposta, plano, instrumento, SIAFI, processo, parlamentar e objeto).
                </p>
              ) : (
                <div className="space-y-4">
                  {data.grupos.map((g, gi) => (
                    <div key={gi}>
                      <h4 className="text-xs font-semibold text-indigo-700 uppercase tracking-wide border-b border-indigo-200 pb-1 mb-2">
                        {g.fonte} <span className="text-slate-400 font-normal">({g.matches.length})</span>
                      </h4>
                      <div className="space-y-1.5">
                        {g.matches.map((m, mi) => (
                          <div key={mi} className="border rounded p-2 hover:bg-slate-50">
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className="text-sm text-slate-800 truncate">{m.titulo || "(sem objeto)"}</div>
                                <div className="text-[11px] text-slate-500 truncate">{m.subtitulo}</div>
                              </div>
                              {m.valor != null && (
                                <div className="text-xs font-mono text-green-700 whitespace-nowrap">{fmtMoeda(m.valor)}</div>
                              )}
                            </div>
                            <span className="inline-block mt-1 text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">
                              {m.chave_match}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
