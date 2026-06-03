"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Edit2, Loader2, Eraser, Paperclip } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import AnotacaoModal from "@/components/AnotacaoModal";

interface Anotacao {
  id: number;
  municipio_id: number;
  fonte: string;
  fonte_ref: string;
  numero_referencia?: string;
  status_interno?: string | null;
  status_custom?: string | null;
  protocolo?: string | null;
  data_protocolo?: string | null;
  observacoes?: string | null;
  anexos: Array<{ nome: string; mime: string; tamanho?: number }>;
  updated_at?: string;
}

const FONTE_LABEL: Record<string, string> = {
  sigcon: "SIGCON (Estadual)",
  voluntaria: "Voluntária (SICONV)",
  plano_acao: "Plano de Ação (TG Especial)",
  fns: "FNS",
  simec: "SIMEC",
  emenda: "Emenda Estadual",
  rm: "Item de RM",
};
const FONTE_COLOR: Record<string, string> = {
  sigcon: "bg-blue-100 text-blue-800",
  voluntaria: "bg-cyan-100 text-cyan-800",
  plano_acao: "bg-amber-100 text-amber-800",
  fns: "bg-emerald-100 text-emerald-800",
  simec: "bg-teal-100 text-teal-800",
  emenda: "bg-purple-100 text-purple-800",
  rm: "bg-slate-100 text-slate-800",
};

function fmtData(d?: string | null) {
  if (!d) return "-";
  try { return new Date(d).toLocaleDateString("pt-BR"); } catch { return d; }
}

export default function GestaoPage() {
  const sp = useSearchParams();
  const municipioId = sp.get("municipio_id");

  const [items, setItems] = useState<Anotacao[]>([]);
  const [loading, setLoading] = useState(false);
  const [filtroFonte, setFiltroFonte] = useState<string>("");
  const [filtroStatus, setFiltroStatus] = useState<string>("");
  const [statusOpcoes, setStatusOpcoes] = useState<string[]>([]);
  const [openItem, setOpenItem] = useState<Anotacao | null>(null);

  const carregar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { municipio_id: municipioId };
      if (filtroFonte) params.fonte = filtroFonte;
      if (filtroStatus) params.status = filtroStatus;
      const r = await api.get<{ items: Anotacao[] }>("/gestao/anotacoes", { params });
      setItems(r.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId, filtroFonte, filtroStatus]);

  useEffect(() => { carregar(); }, [carregar]);

  useEffect(() => {
    api.get<{ opcoes: string[] }>("/gestao/status-opcoes")
      .then((r) => setStatusOpcoes(r.data.opcoes)).catch(() => {});
  }, []);

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-violet-800 flex items-center gap-2">
          <Edit2 className="size-6" /> Gestão Interna
        </h1>
        <p className="text-sm text-slate-500">
          Anotações paralelas aos dados oficiais. Marque status próprio (ex: &quot;prestação enviada
          fisicamente&quot;), protocolos, datas, observações e anexe PDFs/imagens sem alterar
          os dados brutos do scraper.
        </p>
      </div>

      <div className="bg-white border rounded p-3 flex flex-wrap items-end gap-3">
        <div>
          <label className="text-xs text-slate-600 mb-1 block">Fonte</label>
          <select
            value={filtroFonte} onChange={(e) => setFiltroFonte(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm bg-white"
          >
            <option value="">Todas</option>
            {Object.entries(FONTE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-600 mb-1 block">Status</label>
          <select
            value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1.5 text-sm bg-white"
          >
            <option value="">Todos</option>
            {statusOpcoes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <Button variant="outline" onClick={() => { setFiltroFonte(""); setFiltroStatus(""); }}>
          <Eraser className="size-4 mr-1" /> Limpar
        </Button>
      </div>

      <div className="bg-white border rounded">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm">
          <strong>{items.length}</strong> anotação(ões)
        </div>
        {loading ? (
          <div className="p-8 text-center"><Loader2 className="size-6 animate-spin mx-auto text-violet-600" /></div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            Nenhuma anotação ainda. Use o ícone <Edit2 className="inline size-4 text-violet-600" /> nas telas
            de Convênios, Voluntárias ou outras para criar anotações.
          </div>
        ) : (
          <ul className="divide-y">
            {items.map((a) => (
              <li key={a.id}
                  onClick={() => setOpenItem(a)}
                  className="px-3 py-3 hover:bg-slate-50 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${FONTE_COLOR[a.fonte] || "bg-slate-100"}`}>
                        {FONTE_LABEL[a.fonte] || a.fonte}
                      </span>
                      <span className="text-sm font-mono text-slate-700">
                        {a.numero_referencia || a.fonte_ref}
                      </span>
                      {a.status_interno && (
                        <span className="inline-block bg-violet-100 text-violet-800 px-2 py-0.5 rounded text-[11px] font-semibold">
                          {a.status_interno === "Outro" ? a.status_custom : a.status_interno}
                        </span>
                      )}
                      {a.protocolo && (
                        <span className="text-[11px] text-slate-600">
                          Protocolo <code className="bg-slate-100 px-1 rounded font-mono">{a.protocolo}</code>
                        </span>
                      )}
                      {a.data_protocolo && (
                        <span className="text-[11px] text-slate-600">📅 {fmtData(a.data_protocolo)}</span>
                      )}
                      {a.anexos && a.anexos.length > 0 && (
                        <span className="text-[11px] text-slate-500 inline-flex items-center gap-0.5">
                          <Paperclip className="size-3" /> {a.anexos.length}
                        </span>
                      )}
                    </div>
                    {a.observacoes && (
                      <p className="text-sm text-slate-700 line-clamp-2">{a.observacoes}</p>
                    )}
                    <div className="text-[10px] text-slate-400 mt-1">
                      Atualizado {fmtData(a.updated_at)}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {openItem && (
        <AnotacaoModal
          open={!!openItem}
          onClose={() => { setOpenItem(null); carregar(); }}
          fonte={openItem.fonte}
          fonteRef={openItem.fonte_ref}
          municipioId={openItem.municipio_id}
          numeroReferencia={openItem.numero_referencia || openItem.fonte_ref}
          onChanged={carregar}
        />
      )}
    </div>
  );
}
