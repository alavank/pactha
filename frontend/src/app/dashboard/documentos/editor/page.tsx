"use client";

import React, { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, Save, Plus, Trash2, FileText, FileType, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Input } from "@/components/ui/input";
import {
  BOTAO_ACAO, BOTAO_CTA, BOTAO_SEC, Bloco, BlocoHead, ESTILO_CTA, ESTILO_SEC,
} from "@/components/ui/superficies";

type Campo = {
  key: string; label: string; tipo: string;
  ajuda?: string; exemplo?: string; opcoes?: string[];
};
type Secao = { titulo: string; tipo?: string; key?: string; item_label?: string; ajuda?: string; campos: Campo[] };
type Schema = { tipo: string; titulo: string; descricao?: string; secoes: Secao[] };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Dados = Record<string, any>;

// A mesma aparencia de campo do resto do sistema (`.bi-field` em globals.css):
// tres desenhos de campo conviviam no produto, um deles sumindo dentro do modal.
const inputCls = "bi-field w-full p-2 text-sm";

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
      <label className="block text-[12px] font-semibold" style={{ color: "var(--bi-text)" }}>{campo.label}</label>
      {campo.ajuda && <p className="mt-0.5 mb-1.5 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>{campo.ajuda}</p>}
      <CampoInput campo={campo} value={value} onChange={onChange} />
    </div>
  );
}

function EditorInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const { municipioId } = useMunicipio();
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

  if (loading) return <div className="flex h-64 items-center justify-center"><Loader2 className="size-7 animate-spin" style={{ color: "var(--bi-faint)" }} /></div>;
  if (!schema) return <div className="p-8 text-center text-[12px]" style={{ color: "var(--bi-faint)" }}>Tipo de documento não encontrado.</div>;

  return (
    <div className="mx-auto max-w-4xl space-y-4 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div>
          <button type="button" onClick={voltar}
                  className="mb-1.5 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors bi-hover"
                  style={ESTILO_SEC}>
            <ArrowLeft className="size-3" /> Voltar
          </button>
          <h1 className="text-2xl font-bold text-base-content">{schema.titulo}</h1>
          {schema.descricao && <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>{schema.descricao}</p>}
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={() => salvar()} disabled={salvando} className={BOTAO_CTA} style={ESTILO_CTA}>
            {salvando ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Salvar
          </button>
          <button type="button" onClick={() => exportar("pdf")} disabled={!!baixando} className={BOTAO_SEC} style={ESTILO_SEC}>
            {baixando === "pdf" ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />} PDF
          </button>
          <button type="button" onClick={() => exportar("docx")} disabled={!!baixando} className={BOTAO_SEC} style={ESTILO_SEC}>
            {baixando === "docx" ? <Loader2 className="size-4 animate-spin" /> : <FileType className="size-4" />} DOCX
          </button>
        </div>
      </div>

      {schema.secoes.map((secao) => (
        <Bloco key={secao.titulo} className="p-4">
          <BlocoHead titulo={secao.titulo} sub={secao.tipo === "lista" ? undefined : `${secao.campos.length} campo(s)`} />
          {secao.tipo === "lista" ? (
            <ListaSecao secao={secao} itens={(dados[secao.key!] as Dados[]) || []}
                        onItemChange={(idx, k, v) => setItemCampo(secao.key!, idx, k, v)}
                        onAdd={() => addItem(secao.key!)} onRemove={(idx) => removeItem(secao.key!, idx)} />
          ) : (
            secao.campos.map((c) => (
              <CampoBlock key={c.key} campo={c} value={dados[c.key]} onChange={(v) => setCampo(c.key, v)} />
            ))
          )}
        </Bloco>
      ))}

      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>As alterações são salvas ao clicar em <strong>Salvar</strong>. Exportar salva automaticamente antes de gerar o arquivo.</p>
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
      {secao.ajuda && <p className="-mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>{secao.ajuda}</p>}
      {itens.length === 0 && <p className="text-[12px] italic" style={{ color: "var(--bi-faint)" }}>Nenhum {(secao.item_label || "item").toLowerCase()} cadastrado.</p>}
      {itens.map((item, idx) => (
        <Bloco key={idx} plano className="p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[12px] font-semibold" style={{ color: "var(--bi-muted)" }}>{secao.item_label || "Item"} {idx + 1}</span>
            <button type="button" onClick={() => onRemove(idx)} className={BOTAO_ACAO}
                    style={{ ...ESTILO_SEC, color: "var(--bi-crit-ink)" }}>
              <Trash2 className="size-3.5" /> Remover
            </button>
          </div>
          {secao.campos.map((c) => (
            <CampoBlock key={c.key} campo={c} value={item[c.key]} onChange={(v) => onItemChange(idx, c.key, v)} />
          ))}
        </Bloco>
      ))}
      <button type="button" onClick={onAdd} className={BOTAO_SEC} style={ESTILO_SEC}>
        <Plus className="size-4" /> Adicionar {secao.item_label || "item"}
      </button>
    </div>
  );
}

export default function EditorPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="size-7 animate-spin" style={{ color: "var(--bi-faint)" }} /></div>}>
      <EditorInner />
    </Suspense>
  );
}
