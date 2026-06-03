"use client";

import React, { useState, useEffect, useCallback } from "react";
import { X, Plus, Trash2, Loader2, Paperclip, Download, FileText, Edit2 } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Anexo {
  nome: string;
  mime: string;
  dados_b64?: string; // omitido na lista, presente no item
  tamanho?: number;
}

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
  anexos: Anexo[];
  created_at?: string;
  updated_at?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  fonte: string; // sigcon | voluntaria | plano_acao | fns | simec | emenda | rm
  fonteRef: string;
  municipioId: number;
  numeroReferencia?: string;
  onChanged?: () => void;
}

function fmtData(d?: string | null) {
  if (!d) return "-";
  try { return new Date(d).toLocaleDateString("pt-BR"); } catch { return d; }
}
function fmtBytes(n?: number) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export default function AnotacaoModal({
  open, onClose, fonte, fonteRef, municipioId, numeroReferencia, onChanged,
}: Props) {
  const [items, setItems] = useState<Anotacao[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<Anotacao | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [statusOpcoes, setStatusOpcoes] = useState<string[]>([]);

  // Form state
  const [statusInt, setStatusInt] = useState("");
  const [statusCustom, setStatusCustom] = useState("");
  const [protocolo, setProtocolo] = useState("");
  const [dataProt, setDataProt] = useState("");
  const [obs, setObs] = useState("");
  const [anexos, setAnexos] = useState<Anexo[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    if (!open) return;
    setLoading(true);
    try {
      const r = await api.get<{ items: Anotacao[] }>("/gestao/anotacoes/item", {
        params: { fonte, fonte_ref: fonteRef },
      });
      setItems(r.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [open, fonte, fonteRef]);

  useEffect(() => { if (open) carregar(); }, [open, carregar]);

  useEffect(() => {
    if (statusOpcoes.length || !open) return;
    api.get<{ opcoes: string[] }>("/gestao/status-opcoes")
      .then((r) => setStatusOpcoes(r.data.opcoes)).catch(() => {});
  }, [open, statusOpcoes.length]);

  const resetForm = () => {
    setStatusInt(""); setStatusCustom(""); setProtocolo("");
    setDataProt(""); setObs(""); setAnexos([]); setEditing(null); setErr(null);
  };

  const startEdit = (a: Anotacao) => {
    setEditing(a);
    setStatusInt(a.status_interno || "");
    setStatusCustom(a.status_custom || "");
    setProtocolo(a.protocolo || "");
    setDataProt(a.data_protocolo || "");
    setObs(a.observacoes || "");
    setAnexos(a.anexos || []);
    setFormOpen(true);
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    files.forEach((f) => {
      if (f.size > 1_500_000) {
        setErr(`Arquivo "${f.name}" excede 1.5MB (limite por anexo).`);
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // data:mime/type;base64,XXXX
        const b64 = result.split(",")[1] || "";
        setAnexos((prev) => [...prev, {
          nome: f.name, mime: f.type || "application/octet-stream",
          dados_b64: b64, tamanho: f.size,
        }]);
      };
      reader.readAsDataURL(f);
    });
    e.target.value = "";
  };

  const salvar = async () => {
    setErr(null);
    if (statusInt === "Outro" && !statusCustom.trim()) {
      setErr("Status 'Outro' exige preenchimento do campo livre."); return;
    }
    setSaving(true);
    try {
      const payload = {
        municipio_id: municipioId,
        fonte, fonte_ref: fonteRef, numero_referencia: numeroReferencia,
        status_interno: statusInt || null,
        status_custom: statusInt === "Outro" ? statusCustom : null,
        protocolo: protocolo || null,
        data_protocolo: dataProt || null,
        observacoes: obs || null,
        anexos,
      };
      if (editing) {
        await api.put(`/gestao/anotacoes/${editing.id}`, payload);
      } else {
        await api.post("/gestao/anotacoes", payload);
      }
      resetForm();
      setFormOpen(false);
      await carregar();
      onChanged?.();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErr(err.response?.data?.detail || "Falha ao salvar.");
    } finally { setSaving(false); }
  };

  const remover = async (id: number) => {
    if (!confirm("Remover esta anotação?")) return;
    try {
      await api.delete(`/gestao/anotacoes/${id}`);
      await carregar();
      onChanged?.();
    } catch (e) { console.error(e); }
  };

  const baixarAnexo = (anotId: number, idx: number, nome: string) => {
    const token = localStorage.getItem("pacta_token");
    fetch(`${api.defaults.baseURL}/gestao/anotacoes/${anotId}/anexo/${idx}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url; a.download = nome;
        a.click();
        URL.revokeObjectURL(url);
      });
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-2xl w-full max-w-3xl mt-8 mb-8" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 rounded-t-lg flex items-center justify-between border-b">
          <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <Edit2 className="size-5 text-violet-600" /> Gestão Interna
            {numeroReferencia && <span className="text-sm font-normal text-slate-500">({numeroReferencia})</span>}
          </h3>
          <button onClick={onClose}><X className="size-5 text-gray-500 hover:text-gray-700" /></button>
        </div>

        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          {/* Lista de anotacoes existentes */}
          {loading ? (
            <div className="text-center py-6"><Loader2 className="size-6 animate-spin mx-auto text-violet-600" /></div>
          ) : items.length === 0 ? (
            <div className="p-4 text-center text-sm text-slate-500 bg-slate-50 rounded">Nenhuma anotação ainda.</div>
          ) : (
            <div className="space-y-2">
              {items.map((a) => (
                <div key={a.id} className="border rounded-lg p-3 bg-slate-50/40">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        {a.status_interno && (
                          <span className="inline-block bg-violet-100 text-violet-800 px-2 py-0.5 rounded text-[11px] font-semibold">
                            {a.status_interno === "Outro" ? a.status_custom : a.status_interno}
                          </span>
                        )}
                        {a.protocolo && (
                          <span className="text-[11px] text-slate-600">
                            Protocolo: <code className="bg-slate-100 px-1 rounded font-mono">{a.protocolo}</code>
                          </span>
                        )}
                        {a.data_protocolo && (
                          <span className="text-[11px] text-slate-600">📅 {fmtData(a.data_protocolo)}</span>
                        )}
                      </div>
                      {a.observacoes && (
                        <p className="text-sm text-slate-700 whitespace-pre-wrap mt-1">{a.observacoes}</p>
                      )}
                      {a.anexos && a.anexos.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {a.anexos.map((ax, i) => (
                            <button
                              key={i}
                              onClick={() => baixarAnexo(a.id, i, ax.nome)}
                              className="inline-flex items-center gap-1 text-[11px] bg-white border rounded px-2 py-0.5 hover:bg-blue-50 hover:border-blue-300"
                              title={`${ax.nome} · ${fmtBytes(ax.tamanho)}`}
                            >
                              <Paperclip className="size-3" /> {ax.nome}
                              <Download className="size-3 text-blue-600" />
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="text-[10px] text-slate-400 mt-1.5">
                        Atualizado {fmtData(a.updated_at)}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1">
                      <button onClick={() => startEdit(a)} className="text-blue-600 hover:bg-blue-50 rounded p-1" title="Editar">
                        <Edit2 className="size-4" />
                      </button>
                      <button onClick={() => remover(a.id)} className="text-red-600 hover:bg-red-50 rounded p-1" title="Remover">
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Form */}
          {!formOpen ? (
            <Button onClick={() => { resetForm(); setFormOpen(true); }} variant="outline" className="w-full">
              <Plus className="size-4 mr-1" /> Nova anotação
            </Button>
          ) : (
            <div className="border-2 border-dashed border-violet-300 rounded-lg p-3 space-y-3 bg-violet-50/30">
              <h4 className="text-sm font-semibold text-violet-900">
                {editing ? "Editar anotação" : "Nova anotação"}
              </h4>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="md:col-span-2">
                  <label className="text-xs text-slate-600 mb-1 block">Status</label>
                  <select
                    value={statusInt}
                    onChange={(e) => setStatusInt(e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm bg-white"
                  >
                    <option value="">(selecione)</option>
                    {statusOpcoes.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                {statusInt === "Outro" && (
                  <div className="md:col-span-2">
                    <label className="text-xs text-slate-600 mb-1 block">Descreva o status</label>
                    <Input value={statusCustom} onChange={(e) => setStatusCustom(e.target.value)} placeholder="Texto livre do status" />
                  </div>
                )}
                <div>
                  <label className="text-xs text-slate-600 mb-1 block">Protocolo</label>
                  <Input value={protocolo} onChange={(e) => setProtocolo(e.target.value)} placeholder="Nº protocolo / SEI" />
                </div>
                <div>
                  <label className="text-xs text-slate-600 mb-1 block">Data</label>
                  <Input type="date" value={dataProt} onChange={(e) => setDataProt(e.target.value)} />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs text-slate-600 mb-1 block">Observações</label>
                  <textarea
                    value={obs} onChange={(e) => setObs(e.target.value)}
                    className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm min-h-[80px]"
                    placeholder="Detalhes, contexto, próximos passos..."
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs text-slate-600 mb-1 block">Anexos (PDF/imagem, máx 1.5MB cada)</label>
                  <input type="file" accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
                         multiple onChange={handleFile}
                         className="text-xs" />
                  {anexos.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {anexos.map((a, i) => (
                        <div key={i} className="inline-flex items-center gap-1 text-[11px] bg-white border rounded px-2 py-0.5">
                          <FileText className="size-3" /> {a.nome} {a.tamanho && `(${fmtBytes(a.tamanho)})`}
                          <button onClick={() => setAnexos(anexos.filter((_, j) => j !== i))} className="text-red-600 hover:bg-red-50 ml-1">
                            <X className="size-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {err && <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded px-2 py-1.5">{err}</div>}

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => { resetForm(); setFormOpen(false); }} disabled={saving}>
                  Cancelar
                </Button>
                <Button onClick={salvar} disabled={saving} className="bg-violet-600 hover:bg-violet-700">
                  {saving ? <Loader2 className="size-4 animate-spin mr-1" /> : null}
                  {editing ? "Salvar alterações" : "Criar anotação"}
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
