"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { FileSignature, Plus, Pencil, Trash2, FileText, FileType, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface Doc {
  id: number;
  municipio_id: number | null;
  tipo: string;
  titulo: string;
  status: string;
  updated_at: string;
}
interface TipoDoc { tipo: string; titulo: string; descricao: string; }

function fmt(iso?: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "-" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export default function DocumentosPage() {
  const sp = useSearchParams();
  const router = useRouter();
  const municipioId = sp.get("municipio_id");

  const [docs, setDocs] = useState<Doc[]>([]);
  const [tipos, setTipos] = useState<TipoDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [baixando, setBaixando] = useState<string>("");

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const params = municipioId ? { municipio_id: municipioId } : {};
      const [d, t] = await Promise.all([
        api.get<{ items: Doc[] }>("/documentos", { params }),
        api.get<{ items: TipoDoc[] }>("/documentos/schemas"),
      ]);
      setDocs(d.data.items ?? []);
      setTipos(t.data.items ?? []);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { carregar(); }, [carregar]);

  const novo = (tipo: string) => {
    const qs = new URLSearchParams({ tipo });
    if (municipioId) qs.set("municipio_id", municipioId);
    router.push(`/dashboard/documentos/editor?${qs.toString()}`);
  };
  const editar = (id: number) => {
    const qs = new URLSearchParams({ id: String(id) });
    if (municipioId) qs.set("municipio_id", municipioId);
    router.push(`/dashboard/documentos/editor?${qs.toString()}`);
  };
  const excluir = async (id: number) => {
    if (!confirm("Excluir este documento? Esta ação não pode ser desfeita.")) return;
    try { await api.delete(`/documentos/${id}`); setDocs((p) => p.filter((d) => d.id !== id)); }
    catch (e) { console.error(e); alert("Falha ao excluir."); }
  };
  const exportar = async (id: number, formato: "pdf" | "docx", titulo: string) => {
    setBaixando(`${id}-${formato}`);
    try {
      const r = await api.get(`/documentos/${id}/export`, { params: { formato }, responseType: "blob" });
      const ext = formato === "docx" ? "docx" : "pdf";
      const mime = formato === "docx"
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : "application/pdf";
      const url = window.URL.createObjectURL(new Blob([r.data], { type: mime }));
      const a = document.createElement("a");
      a.href = url; a.download = `${(titulo || "documento").replace(/[^\w\-]+/g, "_")}.${ext}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); alert("Falha ao exportar."); } finally { setBaixando(""); }
  };

  return (
    <div className="space-y-5">
      <div className="border-b border-slate-200 pb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
            <span>Início</span><span>›</span><span className="text-slate-700">Geração de Documentos</span>
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight flex items-center gap-2">
            <FileSignature className="size-6 text-blue-700" /> Geração de Documentos
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Preencha, salve e exporte documentos (DOCX/PDF) com edição e exclusão.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {tipos.map((t) => (
            <Button key={t.tipo} onClick={() => novo(t.tipo)} className="bg-blue-600 hover:bg-blue-700">
              <Plus className="size-4 mr-1" /> Novo {t.titulo}
            </Button>
          ))}
        </div>
      </div>

      <div className="bg-white border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm">
          <strong>{docs.length}</strong> documento(s){municipioId ? " neste município" : ""}
        </div>
        {loading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-16 animate-pulse bg-gray-100 rounded" />)}
          </div>
        ) : docs.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            Nenhum documento criado ainda. Clique em <strong>Novo</strong> acima para começar.
          </div>
        ) : (
          <div className="divide-y">
            {docs.map((d) => (
              <div key={d.id} className="flex flex-wrap items-center justify-between gap-3 p-3 hover:bg-slate-50">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-slate-900 truncate">{d.titulo || "(sem título)"}</span>
                    <span className="inline-flex items-center rounded border border-blue-200 bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-blue-700">
                      {tipos.find((t) => t.tipo === d.tipo)?.titulo || d.tipo}
                    </span>
                    {d.status && d.status !== "rascunho" && (
                      <span className="text-[10px] uppercase text-green-700">{d.status}</span>
                    )}
                  </div>
                  <div className="text-xs text-slate-500">Atualizado: {fmt(d.updated_at)}</div>
                </div>
                <div className="flex items-center gap-1.5">
                  <Button variant="outline" size="sm" onClick={() => editar(d.id)}>
                    <Pencil className="size-3.5 mr-1" /> Editar
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => exportar(d.id, "pdf", d.titulo)}
                          disabled={baixando === `${d.id}-pdf`} title="Exportar PDF">
                    {baixando === `${d.id}-pdf` ? <Loader2 className="size-3.5 animate-spin mr-1" /> : <FileText className="size-3.5 mr-1" />} PDF
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => exportar(d.id, "docx", d.titulo)}
                          disabled={baixando === `${d.id}-docx`} title="Exportar DOCX">
                    {baixando === `${d.id}-docx` ? <Loader2 className="size-3.5 animate-spin mr-1" /> : <FileType className="size-3.5 mr-1" />} DOCX
                  </Button>
                  <Button variant="ghost" size="sm" className="text-red-600 hover:bg-red-50 hover:text-red-700"
                          onClick={() => excluir(d.id)} title="Excluir">
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
