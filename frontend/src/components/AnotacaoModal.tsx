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
    const token = localStorage.getItem("pactha_token");
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
    <div className="fixed inset-0 z-50 bg-neutral/50 flex items-start justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-base-100 rounded-lg shadow-2xl w-full max-w-3xl mt-8 mb-8" onClick={(e) => e.stopPropagation()}>
        <div className="px-5 py-3 rounded-t-lg flex items-center justify-between border-b">
          <h3 className="text-lg font-semibold text-base-content flex items-center gap-2">
            <Edit2 className="size-5 text-info" /> Gestão Interna
            {numeroReferencia && <span className="text-sm font-normal text-base-content/60">({numeroReferencia})</span>}
          </h3>
          <button onClick={onClose}><X className="size-5 text-base-content/60 hover:text-base-content/70" /></button>
        </div>

        <div className="p-5 space-y-4 max-h-[75vh] overflow-y-auto">
          {/* Lista de anotacoes existentes */}
          {loading ? (
            <div className="text-center py-6"><Loader2 className="size-6 animate-spin mx-auto text-info" /></div>
          ) : items.length === 0 ? (
            <div className="p-4 text-center text-sm text-base-content/60 bg-base-200 rounded">Nenhuma anotação ainda.</div>
          ) : (
            <div className="space-y-2">
              {items.map((a) => (
                <div key={a.id} className="border rounded-lg p-3 bg-base-200/40">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1">
                        {a.status_interno && (
                          <span className="inline-block bg-info/15 text-info px-2 py-0.5 rounded text-[11px] font-semibold">
                            {a.status_interno === "Outro" ? a.status_custom : a.status_interno}
                          </span>
                        )}
                        {a.protocolo && (
                          <span className="text-[11px] text-base-content/70">
                            Protocolo: <code className="bg-base-200 px-1 rounded font-mono">{a.protocolo}</code>
                          </span>
                        )}
                        {a.data_protocolo && (
                          <span className="text-[11px] text-base-content/70">📅 {fmtData(a.data_protocolo)}</span>
                        )}
                      </div>
                      {a.observacoes && (
                        <p className="text-sm text-base-content/70 whitespace-pre-wrap mt-1">{a.observacoes}</p>
                      )}
                      {a.anexos && a.anexos.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {a.anexos.map((ax, i) => (
                            <button
                              key={i}
                              onClick={() => baixarAnexo(a.id, i, ax.nome)}
                              className="inline-flex items-center gap-1 text-[11px] bg-base-100 border rounded px-2 py-0.5 hover:bg-primary/10 hover:border-primary"
                              title={`${ax.nome} · ${fmtBytes(ax.tamanho)}`}
                            >
                              <Paperclip className="size-3" /> {ax.nome}
                              <Download className="size-3 text-primary" />
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="text-[10px] text-base-content/40 mt-1.5">
                        Atualizado {fmtData(a.updated_at)}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1">
                      <button onClick={() => startEdit(a)} className="text-primary hover:bg-primary/10 rounded p-1" title="Editar">
                        <Edit2 className="size-4" />
                      </button>
                      <button onClick={() => remover(a.id)} className="text-error hover:bg-error/10 rounded p-1" title="Remover">
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
            <div className="border-2 border-dashed border-info rounded-lg p-3 space-y-3 bg-info/15">
              <h4 className="text-sm font-semibold text-info">
                {editing ? "Editar anotação" : "Nova anotação"}
              </h4>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="md:col-span-2">
                  <label className="text-xs text-base-content/70 mb-1 block">Status</label>
                  <select
                    value={statusInt}
                    onChange={(e) => setStatusInt(e.target.value)}
                    className="w-full rounded border border-base-300 px-2 py-1.5 text-sm bg-base-100 text-base-content"
                  >
                    <option value="">(selecione)</option>
                    {statusOpcoes.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                {statusInt === "Outro" && (
                  <div className="md:col-span-2">
                    <label className="text-xs text-base-content/70 mb-1 block">Descreva o status</label>
                    <Input value={statusCustom} onChange={(e) => setStatusCustom(e.target.value)} placeholder="Texto livre do status" />
                  </div>
                )}
                <div>
                  <label className="text-xs text-base-content/70 mb-1 block">Protocolo</label>
                  <Input value={protocolo} onChange={(e) => setProtocolo(e.target.value)} placeholder="Nº protocolo / SEI" />
                </div>
                <div>
                  <label className="text-xs text-base-content/70 mb-1 block">Data</label>
                  <Input type="date" value={dataProt} onChange={(e) => setDataProt(e.target.value)} />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs text-base-content/70 mb-1 block">Observações</label>
                  <textarea
                    value={obs} onChange={(e) => setObs(e.target.value)}
                    className="w-full rounded border border-base-300 px-2 py-1.5 text-sm min-h-[80px] bg-base-100 text-base-content"
                    placeholder="Detalhes, contexto, próximos passos..."
                  />
                </div>
                <div className="md:col-span-2">
                  <label className="text-xs text-base-content/70 mb-1 block">Anexos (PDF/imagem, máx 1.5MB cada)</label>
                  <input type="file" accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
                         multiple onChange={handleFile}
                         className="text-xs" />
                  {anexos.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {anexos.map((a, i) => (
                        <div key={i} className="inline-flex items-center gap-1 text-[11px] bg-base-100 border rounded px-2 py-0.5">
                          <FileText className="size-3" /> {a.nome} {a.tamanho && `(${fmtBytes(a.tamanho)})`}
                          <button onClick={() => setAnexos(anexos.filter((_, j) => j !== i))} className="text-error hover:bg-error/10 ml-1">
                            <X className="size-3" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {err && <div className="text-xs text-error bg-error/15 border border-error rounded px-2 py-1.5">{err}</div>}

              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => { resetForm(); setFormOpen(false); }} disabled={saving}>
                  Cancelar
                </Button>
                <Button onClick={salvar} disabled={saving} className="bg-info hover:bg-info/90">
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
