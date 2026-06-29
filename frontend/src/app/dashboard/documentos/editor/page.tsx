"use client";

import React, { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, Save, Plus, Trash2, FileText, FileType, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Campo = {
  key: string; label: string; tipo: string;
  ajuda?: string; exemplo?: string; opcoes?: string[];
};
type Secao = { titulo: string; tipo?: string; key?: string; item_label?: string; ajuda?: string; campos: Campo[] };
type Schema = { tipo: string; titulo: string; descricao?: string; secoes: Secao[] };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Dados = Record<string, any>;

const inputCls = "w-full border border-base-300 rounded-md p-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20";

function CampoInput({ campo, value, onChange }: { campo: Campo; value: unknown; onChange: (v: string) => void }) {
  const v = (value as string) ?? "";
  if (campo.tipo === "textarea") {
    return <textarea rows={4} className={inputCls} value={v} placeholder={campo.exemplo ? `Ex.: ${campo.exemplo}` : ""}
                     onChange={(e) => onChange(e.target.value)} />;
  }
  if (campo.tipo === "select") {
    return (
      <select className={inputCls + " h-9"} value={v} onChange={(e) => onChange(e.target.value)}>
        <option value="">Selecione...</option>
        {(campo.opcoes || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  if (campo.tipo === "date") {
    return <Input type="date" value={v} onChange={(e) => onChange(e.target.value)} />;
  }
  return <Input value={v} placeholder={campo.exemplo ? `Ex.: ${campo.exemplo}` : (campo.tipo === "currency" ? "R$ 0,00" : "")}
                onChange={(e) => onChange(e.target.value)} />;
}

function CampoBlock({ campo, value, onChange }: { campo: Campo; value: unknown; onChange: (v: string) => void }) {
  return (
    <div className="mb-4">
      <label className="block text-sm font-semibold text-base-content">{campo.label}</label>
      {campo.ajuda && <p className="text-xs text-base-content/60 mt-0.5 mb-1.5 leading-snug">{campo.ajuda}</p>}
      <CampoInput campo={campo} value={value} onChange={onChange} />
    </div>
  );
}

function EditorInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const municipioId = sp.get("municipio_id");
  const tipoParam = sp.get("tipo");
  const idParam = sp.get("id");

  const [schema, setSchema] = useState<Schema | null>(null);
  const [dados, setDados] = useState<Dados>({});
  const [docId, setDocId] = useState<number | null>(idParam ? Number(idParam) : null);
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [baixando, setBaixando] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        let tipo = tipoParam;
        if (idParam) {
          const r = await api.get<{ tipo: string; dados: Dados }>(`/documentos/${idParam}`);
          tipo = r.data.tipo;
          setDados(r.data.dados || {});
        }
        if (tipo) {
          const s = await api.get<Schema>(`/documentos/schema/${tipo}`);
          setSchema(s.data);
        }
      } catch (e) { console.error(e); } finally { setLoading(false); }
    })();
  }, [tipoParam, idParam]);

  const setCampo = useCallback((key: string, val: string) => {
    setDados((d) => ({ ...d, [key]: val })); setDirty(true);
  }, []);
  const setItemCampo = (secKey: string, idx: number, key: string, val: string) => {
    setDados((d) => {
      const arr = Array.isArray(d[secKey]) ? [...d[secKey]] : [];
      arr[idx] = { ...(arr[idx] || {}), [key]: val };
      return { ...d, [secKey]: arr };
    });
    setDirty(true);
  };
  const addItem = (secKey: string) => {
    setDados((d) => ({ ...d, [secKey]: [...(Array.isArray(d[secKey]) ? d[secKey] : []), {}] }));
    setDirty(true);
  };
  const removeItem = (secKey: string, idx: number) => {
    setDados((d) => ({ ...d, [secKey]: (d[secKey] as Dados[]).filter((_, i) => i !== idx) }));
    setDirty(true);
  };

  const salvar = useCallback(async (): Promise<number | null> => {
    if (!schema) return null;
    setSalvando(true);
    try {
      const titulo = (dados.convenio_proposta as string) || schema.titulo;
      if (docId) {
        await api.put(`/documentos/${docId}`, { titulo, dados });
        setDirty(false);
        return docId;
      }
      const r = await api.post<{ id: number }>("/documentos", {
        municipio_id: municipioId ? Number(municipioId) : null,
        tipo: schema.tipo, titulo, dados,
      });
      setDocId(r.data.id); setDirty(false);
      // reflete o id na URL (próximos saves viram PUT)
      const qs = new URLSearchParams({ id: String(r.data.id) });
      if (municipioId) qs.set("municipio_id", municipioId);
      router.replace(`/dashboard/documentos/editor?${qs.toString()}`);
      return r.data.id;
    } catch (e) { console.error(e); alert("Falha ao salvar."); return null; }
    finally { setSalvando(false); }
  }, [schema, dados, docId, municipioId, router]);

  const exportar = async (formato: "pdf" | "docx") => {
    let id = docId;
    if (!id || dirty) { id = await salvar(); }   // garante salvo antes de exportar
    if (!id) return;
    setBaixando(formato);
    try {
      const r = await api.get(`/documentos/${id}/export`, { params: { formato }, responseType: "blob" });
      const mime = formato === "docx"
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : "application/pdf";
      const nome = ((dados.convenio_proposta as string) || schema?.titulo || "documento").replace(/[^\w\-]+/g, "_");
      const url = window.URL.createObjectURL(new Blob([r.data], { type: mime }));
      const a = document.createElement("a");
      a.href = url; a.download = `${nome}.${formato}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); alert("Falha ao exportar."); } finally { setBaixando(""); }
  };

  const voltar = () => {
    const qs = municipioId ? `?municipio_id=${municipioId}` : "";
    router.push(`/dashboard/documentos${qs}`);
  };

  if (loading) return <div className="flex h-64 items-center justify-center"><Loader2 className="size-7 animate-spin text-primary" /></div>;
  if (!schema) return <div className="p-8 text-center text-base-content/60">Tipo de documento não encontrado.</div>;

  return (
    <div className="space-y-5 max-w-4xl mx-auto pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div>
          <button onClick={voltar} className="text-xs text-primary hover:underline inline-flex items-center gap-1 mb-1">
            <ArrowLeft className="size-3" /> Voltar
          </button>
          <h1 className="text-xl font-bold text-base-content">{schema.titulo}</h1>
          {schema.descricao && <p className="text-sm text-base-content/60">{schema.descricao}</p>}
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={() => salvar()} disabled={salvando} className="bg-primary hover:bg-primary/90">
            {salvando ? <Loader2 className="size-4 animate-spin mr-1" /> : <Save className="size-4 mr-1" />} Salvar
          </Button>
          <Button variant="outline" onClick={() => exportar("pdf")} disabled={!!baixando}>
            {baixando === "pdf" ? <Loader2 className="size-4 animate-spin mr-1" /> : <FileText className="size-4 mr-1" />} PDF
          </Button>
          <Button variant="outline" onClick={() => exportar("docx")} disabled={!!baixando}>
            {baixando === "docx" ? <Loader2 className="size-4 animate-spin mr-1" /> : <FileType className="size-4 mr-1" />} DOCX
          </Button>
        </div>
      </div>

      {schema.secoes.map((secao) => (
        <div key={secao.titulo} className="bg-base-100 border rounded-lg p-4">
          <h2 className="text-sm font-bold uppercase tracking-wide text-primary border-b border-primary/10 pb-1.5 mb-3">
            {secao.titulo}
          </h2>
          {secao.tipo === "lista" ? (
            <ListaSecao secao={secao} itens={(dados[secao.key!] as Dados[]) || []}
                        onItemChange={(idx, k, v) => setItemCampo(secao.key!, idx, k, v)}
                        onAdd={() => addItem(secao.key!)} onRemove={(idx) => removeItem(secao.key!, idx)} />
          ) : (
            secao.campos.map((c) => (
              <CampoBlock key={c.key} campo={c} value={dados[c.key]} onChange={(v) => setCampo(c.key, v)} />
            ))
          )}
        </div>
      ))}

      <p className="text-xs text-base-content/40">As alterações são salvas ao clicar em <strong>Salvar</strong>. Exportar salva automaticamente antes de gerar o arquivo.</p>
    </div>
  );
}

function ListaSecao({ secao, itens, onItemChange, onAdd, onRemove }: {
  secao: Secao; itens: Dados[];
  onItemChange: (idx: number, key: string, val: string) => void;
  onAdd: () => void; onRemove: (idx: number) => void;
}) {
  return (
    <div className="space-y-4">
      {secao.ajuda && <p className="text-xs text-base-content/60 -mt-1">{secao.ajuda}</p>}
      {itens.length === 0 && <p className="text-sm text-base-content/40 italic">Nenhum {(secao.item_label || "item").toLowerCase()} cadastrado.</p>}
      {itens.map((item, idx) => (
        <div key={idx} className="border border-base-300 rounded-md p-3 bg-base-200/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-semibold text-base-content/70">{secao.item_label || "Item"} {idx + 1}</span>
            <Button variant="ghost" size="sm" className="text-error hover:bg-error/10 hover:text-error"
                    onClick={() => onRemove(idx)}>
              <Trash2 className="size-3.5 mr-1" /> Remover
            </Button>
          </div>
          {secao.campos.map((c) => (
            <CampoBlock key={c.key} campo={c} value={item[c.key]} onChange={(v) => onItemChange(idx, c.key, v)} />
          ))}
        </div>
      ))}
      <Button variant="outline" onClick={onAdd}>
        <Plus className="size-4 mr-1" /> Adicionar {secao.item_label || "item"}
      </Button>
    </div>
  );
}

export default function EditorPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="size-7 animate-spin text-primary" /></div>}>
      <EditorInner />
    </Suspense>
  );
}
