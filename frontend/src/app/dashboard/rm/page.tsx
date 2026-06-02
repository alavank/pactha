"use client";

import React, { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { FileText, Plus, Trash2, Eye, Download, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface RmListItem {
  id: number;
  municipio_id: number;
  municipio_nome?: string;
  data_referencia: string;
  cidade_emissao: string;
  titulo?: string;
  status: string;
  updated_at?: string;
}

export default function RmListPage() {
  const sp = useSearchParams();
  const router = useRouter();
  const municipioId = sp.get("municipio_id");

  const [items, setItems] = useState<RmListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [criando, setCriando] = useState(false);
  const [novaData, setNovaData] = useState<string>(() => new Date().toISOString().slice(0, 10));

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const r = await api.get<{ items: RmListItem[] }>("/rm", {
        params: { municipio_id: municipioId },
      });
      setItems(r.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId, buscar]);

  const criar = async () => {
    if (!municipioId) return;
    setCriando(true);
    try {
      const r = await api.post<{ id: number }>("/rm", {
        municipio_id: Number(municipioId),
        data_referencia: novaData,
        cidade_emissao: "Brasília/DF",
        auto_popular: true,
      });
      router.push(`/dashboard/rm/${r.data.id}?municipio_id=${municipioId}`);
    } catch (e) {
      console.error(e); alert("Erro ao criar RM.");
    } finally { setCriando(false); }
  };

  const remover = async (id: number) => {
    if (!confirm("Remover este RM?")) return;
    try {
      await api.delete(`/rm/${id}`);
      buscar();
    } catch (e) { console.error(e); }
  };

  const exportarPdf = (id: number) => {
    const url = `${api.defaults.baseURL}/rm/${id}/pdf`;
    const token = localStorage.getItem("pacta_token");
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => window.open(URL.createObjectURL(blob), "_blank"));
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-blue-800 flex items-center gap-2">
          <FileText className="size-6" /> Relatorio de Monitoramento (RM)
        </h1>
        <p className="text-sm text-slate-500">
          Gestao dos RMs do municipio - padrao Freitas (criar, editar, exportar PDF).
        </p>
      </div>

      {/* Form de novo RM */}
      <div className="bg-white border rounded p-4">
        <h2 className="text-sm font-semibold mb-1">Novo RM</h2>
        <p className="text-xs text-slate-500 mb-3">
          O conteúdo será preenchido automaticamente com os dados atuais do banco (SIGCON, Voluntárias, SIMEC, Emendas).
          Você edita livremente depois.
        </p>
        <div className="flex flex-wrap gap-3 items-end">
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Data de referencia</label>
            <Input type="date" value={novaData} onChange={(e) => setNovaData(e.target.value)} />
          </div>
          <Button onClick={criar} disabled={criando} className="bg-blue-600 hover:bg-blue-700">
            {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <Plus className="size-4 mr-1" />}
            Criar RM
          </Button>
        </div>
      </div>

      {/* Lista */}
      <div className="bg-white border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm"><strong>{items.length}</strong> RM(s) cadastrado(s)</div>
        {loading ? (
          <div className="p-8 text-center"><Loader2 className="size-6 animate-spin mx-auto text-blue-600" /></div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">Nenhum RM ainda. Crie o primeiro acima.</div>
        ) : (
          <ul className="divide-y">
            {items.map((rm) => (
              <li key={rm.id} className="flex items-center justify-between gap-3 px-3 py-2.5 hover:bg-slate-50">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-slate-900">
                    {rm.titulo || `RM - ${rm.municipio_nome || ""} - ${rm.data_referencia}`}
                  </div>
                  <div className="text-xs text-slate-500">
                    Data ref.: {rm.data_referencia} ·
                    <span className={`ml-1.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${rm.status === "finalizado" ? "bg-green-100 text-green-800" : "bg-amber-100 text-amber-800"}`}>
                      {rm.status}
                    </span>
                    {rm.updated_at && <span className="ml-2">atualizado {new Date(rm.updated_at).toLocaleString("pt-BR")}</span>}
                  </div>
                </div>
                <div className="flex items-center gap-1.5">
                  <Link
                    href={`/dashboard/rm/${rm.id}?municipio_id=${municipioId}`}
                    className="inline-flex items-center gap-1 rounded bg-blue-50 hover:bg-blue-100 px-2.5 py-1 text-xs text-blue-700"
                  >
                    <Eye className="size-3.5" /> Abrir
                  </Link>
                  <button onClick={() => exportarPdf(rm.id)}
                    className="inline-flex items-center gap-1 rounded bg-emerald-50 hover:bg-emerald-100 px-2.5 py-1 text-xs text-emerald-700">
                    <Download className="size-3.5" /> PDF
                  </button>
                  <button onClick={() => remover(rm.id)}
                    className="inline-flex items-center gap-1 rounded bg-red-50 hover:bg-red-100 px-2.5 py-1 text-xs text-red-700">
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
