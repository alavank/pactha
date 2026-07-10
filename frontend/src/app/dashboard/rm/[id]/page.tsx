"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Save, Download, RefreshCw, ChevronDown, ChevronRight, Plus, Trash2,
  ArrowUp, ArrowDown, Loader2, ArrowLeft, FileCheck,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useMunicipio } from "@/contexts/MunicipioContext";

interface Item {
  ordem?: number;
  tipo?: string;
  numero?: string;
  objeto?: string;
  parlamentar?: string;
  valor_global?: number | null;
  valor_repasse?: number | null;
  valor_contrapartida?: number | null;
  banco?: string;
  agencia?: string;
  conta?: string;
  saldo_bancario?: number | null;
  dt_saldo?: string | null;
  dt_fim_vigencia?: string | null;
  situacao_atual?: string;
  situacao_contratacao?: string;
  situacao_contratacao_detalhe?: Record<string, unknown> | null;
  fonte?: string;
  fonte_ref?: string;
}
interface Grupo { ordem?: number; orgao: string; itens: Item[]; }
interface Secao { ordem?: number; titulo: string; grupos: Grupo[]; }
interface Parte { ordem?: number; titulo: string; secoes: Secao[]; }
interface Conteudo { partes: Parte[]; }
interface Rm {
  id: number; municipio_id: number; municipio_nome?: string; uf?: string;
  data_referencia: string; cidade_emissao: string;
  titulo?: string; rodape: string; status: string;
  conteudo: Conteudo;
}

const ITEM_FIELDS: Array<[keyof Item, string, "text" | "number" | "date" | "textarea"]> = [
  ["tipo", "Tipo", "text"],
  ["numero", "Numero", "text"],
  ["objeto", "Objeto", "textarea"],
  ["parlamentar", "Parlamentar", "text"],
  ["valor_global", "Valor Global (R$)", "number"],
  ["valor_repasse", "Valor Repasse (R$)", "number"],
  ["valor_contrapartida", "Valor Contrapartida (R$)", "number"],
  ["banco", "Banco", "text"],
  ["agencia", "Agencia", "text"],
  ["conta", "Conta", "text"],
  ["saldo_bancario", "Saldo Bancario (R$)", "number"],
  ["dt_saldo", "Data do Saldo", "date"],
  ["dt_fim_vigencia", "Final da Vigencia", "date"],
  ["situacao_contratacao", "Situação de Contratação", "text"],
  ["situacao_atual", "Situacao Atual", "textarea"],
];

function formatSitDet(det: Record<string, unknown> | null | undefined): string {
  if (!det || typeof det !== "object") return "";
  const parts: string[] = [];
  for (const [k, v] of Object.entries(det)) {
    if (k.startsWith("_") || v == null || v === "") continue;
    if (typeof v === "string" || typeof v === "number") {
      parts.push(`${k}: ${v}`);
    }
  }
  const label = (det._label_botao as string) || "";
  return (label ? `(${label}) ` : "") + parts.join("\n");
}

function parseSitDet(txt: string): Record<string, unknown> {
  // Reverse of formatSitDet, melhor esforço: cada linha "K: V"
  const out: Record<string, unknown> = {};
  for (const line of (txt || "").split("\n")) {
    const m = line.match(/^\s*([^:]{1,80}):\s*(.+)$/);
    if (m) out[m[1].trim()] = m[2].trim();
  }
  return out;
}

function moveItem<T>(arr: T[], idx: number, delta: number): T[] {
  const ni = idx + delta;
  if (ni < 0 || ni >= arr.length) return arr;
  const copy = arr.slice();
  [copy[idx], copy[ni]] = [copy[ni], copy[idx]];
  return copy;
}

export default function RmEditorPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const rid = params.id;
  const { municipioId } = useMunicipio();

  const [rm, setRm] = useState<Rm | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [repopulating, setRepopulating] = useState(false);
  const [openPartes, setOpenPartes] = useState<Set<number>>(new Set([0]));
  const [openSecoes, setOpenSecoes] = useState<Set<string>>(new Set());
  const [openGrupos, setOpenGrupos] = useState<Set<string>>(new Set());
  const [openItens, setOpenItens] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<Rm>(`/rm/${rid}`);
      setRm(r.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [rid]);

  useEffect(() => { load(); }, [load]);

  const salvar = async () => {
    if (!rm) return;
    setSaving(true);
    try {
      await api.put(`/rm/${rid}`, {
        data_referencia: rm.data_referencia, cidade_emissao: rm.cidade_emissao,
        titulo: rm.titulo, rodape: rm.rodape, status: rm.status,
        conteudo: rm.conteudo,
      });
      alert("Salvo!");
    } catch (e) { console.error(e); alert("Erro ao salvar."); }
    finally { setSaving(false); }
  };

  const repopular = async () => {
    if (!confirm("Substituir TODO o conteudo pelos dados atuais do banco?")) return;
    setRepopulating(true);
    try {
      await api.post(`/rm/${rid}/auto-popular`);
      await load();
    } catch (e) { console.error(e); } finally { setRepopulating(false); }
  };

  const exportarPdf = () => {
    const token = localStorage.getItem("pactha_token");
    fetch(`${api.defaults.baseURL}/rm/${rid}/pdf`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => window.open(URL.createObjectURL(blob), "_blank"));
  };

  // Mutadores do conteudo (imutaveis)
  const update = (mut: (c: Conteudo) => Conteudo) => {
    if (!rm) return;
    setRm({ ...rm, conteudo: mut(structuredClone(rm.conteudo)) });
  };

  // PARTE
  const addParte = () => update((c) => ({
    partes: [...c.partes, { titulo: "NOVA PARTE", secoes: [] }],
  }));
  const delParte = (pi: number) => update((c) => ({ partes: c.partes.filter((_, i) => i !== pi) }));
  const movParte = (pi: number, d: number) => update((c) => ({ partes: moveItem(c.partes, pi, d) }));

  // SECAO
  const addSecao = (pi: number) => update((c) => {
    c.partes[pi].secoes.push({ titulo: "NOVA SEÇÃO", grupos: [] });
    return c;
  });
  const delSecao = (pi: number, si: number) => update((c) => {
    c.partes[pi].secoes.splice(si, 1); return c;
  });
  const movSecao = (pi: number, si: number, d: number) => update((c) => {
    c.partes[pi].secoes = moveItem(c.partes[pi].secoes, si, d); return c;
  });

  // GRUPO
  const addGrupo = (pi: number, si: number) => update((c) => {
    c.partes[pi].secoes[si].grupos.push({ orgao: "Novo Órgão", itens: [] });
    return c;
  });
  const delGrupo = (pi: number, si: number, gi: number) => update((c) => {
    c.partes[pi].secoes[si].grupos.splice(gi, 1); return c;
  });
  const movGrupo = (pi: number, si: number, gi: number, d: number) => update((c) => {
    c.partes[pi].secoes[si].grupos = moveItem(c.partes[pi].secoes[si].grupos, gi, d); return c;
  });

  // ITEM
  const addItem = (pi: number, si: number, gi: number) => update((c) => {
    c.partes[pi].secoes[si].grupos[gi].itens.push({
      tipo: "Proposta", numero: "", objeto: "", parlamentar: "",
      situacao_atual: "",
    });
    return c;
  });
  const delItem = (pi: number, si: number, gi: number, ii: number) => update((c) => {
    c.partes[pi].secoes[si].grupos[gi].itens.splice(ii, 1); return c;
  });
  const movItem = (pi: number, si: number, gi: number, ii: number, d: number) => update((c) => {
    c.partes[pi].secoes[si].grupos[gi].itens = moveItem(c.partes[pi].secoes[si].grupos[gi].itens, ii, d);
    return c;
  });

  const toggle = (set: Set<string | number>, k: string | number, setter: (s: Set<string | number>) => void) => {
    const ns = new Set(set);
    if (ns.has(k)) ns.delete(k); else ns.add(k);
    setter(ns);
  };

  if (loading || !rm) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="size-6 animate-spin text-primary" /></div>;
  }

  return (
    <div className="space-y-4">
      {/* Topbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b">
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm"
            onClick={() => router.push(`/dashboard/rm?municipio_id=${municipioId || rm.municipio_id}`)}>
            <ArrowLeft className="size-4" />
          </Button>
          <div>
            <h1 className="text-xl font-bold text-primary">
              RM {(rm.data_referencia || "").slice(0, 4)} - {rm.municipio_nome}/{rm.uf}
            </h1>
            <div className="text-xs text-base-content/60">
              <span className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${rm.status === "finalizado" ? "bg-success/15 text-success" : "bg-warning/15 text-warning"}`}>
                {rm.status}
              </span>
              {" "}-{" "}{rm.cidade_emissao}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={repopular} disabled={repopulating}>
            {repopulating ? <Loader2 className="size-4 animate-spin mr-1" /> : <RefreshCw className="size-4 mr-1" />}
            Re-popular do DB
          </Button>
          <Button variant="outline" onClick={() => setRm({ ...rm, status: rm.status === "finalizado" ? "rascunho" : "finalizado" })}>
            <FileCheck className="size-4 mr-1" /> {rm.status === "finalizado" ? "Reabrir" : "Finalizar"}
          </Button>
          <Button onClick={salvar} disabled={saving} className="bg-primary hover:bg-primary/90">
            {saving ? <Loader2 className="size-4 animate-spin mr-1" /> : <Save className="size-4 mr-1" />}
            Salvar
          </Button>
          <Button onClick={exportarPdf} className="bg-success hover:bg-success/90">
            <Download className="size-4 mr-1" /> PDF
          </Button>
        </div>
      </div>

      {/* Metadata edit */}
      <div className="bg-base-100 border rounded p-3 grid grid-cols-1 md:grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">Titulo</label>
          <Input value={rm.titulo || ""} onChange={(e) => setRm({ ...rm, titulo: e.target.value })} />
        </div>
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">Ano de referência</label>
          <select className="w-full border border-base-300 rounded-md p-2 text-sm h-9"
                  value={(rm.data_referencia || "").slice(0, 4)}
                  onChange={(e) => setRm({ ...rm, data_referencia: `${e.target.value}-01-01` })}>
            {(() => { const a = new Date().getFullYear(); return [a + 1, a, a - 1, a - 2, a - 3]; })().map((y) => (
              <option key={y} value={String(y)}>{y}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">Cidade de emissao</label>
          <Input value={rm.cidade_emissao} onChange={(e) => setRm({ ...rm, cidade_emissao: e.target.value })} />
        </div>
      </div>

      {/* Conteudo hierarquico */}
      <div className="space-y-3">
        {rm.conteudo.partes.map((parte, pi) => {
          const popen = openPartes.has(pi);
          return (
            <div key={pi} className="border rounded bg-base-100">
              <div className="flex items-center gap-2 p-2 bg-primary/10 border-b">
                <button onClick={() => toggle(openPartes as Set<string | number>, pi, (s) => setOpenPartes(s as Set<number>))}>
                  {popen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                </button>
                <Input className="flex-1 font-bold" value={parte.titulo}
                  onChange={(e) => update((c) => { c.partes[pi].titulo = e.target.value; return c; })} />
                <button onClick={() => movParte(pi, -1)} className="text-base-content/60 hover:text-base-content/70"><ArrowUp className="size-4" /></button>
                <button onClick={() => movParte(pi, 1)} className="text-base-content/60 hover:text-base-content/70"><ArrowDown className="size-4" /></button>
                <button onClick={() => delParte(pi)} className="text-error hover:text-error"><Trash2 className="size-4" /></button>
              </div>
              {popen && (
                <div className="p-3 space-y-2">
                  {parte.secoes.map((secao, si) => {
                    const skey = `${pi}-${si}`;
                    const sopen = openSecoes.has(skey);
                    return (
                      <div key={si} className="border rounded">
                        <div className="flex items-center gap-2 p-2 bg-base-200 border-b">
                          <button onClick={() => toggle(openSecoes, skey, (s) => setOpenSecoes(s as Set<string>))}>
                            {sopen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </button>
                          <Input className="flex-1 font-semibold text-sm" value={secao.titulo}
                            onChange={(e) => update((c) => { c.partes[pi].secoes[si].titulo = e.target.value; return c; })} />
                          <button onClick={() => movSecao(pi, si, -1)} className="text-base-content/60"><ArrowUp className="size-4" /></button>
                          <button onClick={() => movSecao(pi, si, 1)} className="text-base-content/60"><ArrowDown className="size-4" /></button>
                          <button onClick={() => delSecao(pi, si)} className="text-error"><Trash2 className="size-4" /></button>
                        </div>
                        {sopen && (
                          <div className="p-2 space-y-2">
                            {secao.grupos.map((grupo, gi) => {
                              const gkey = `${pi}-${si}-${gi}`;
                              const gopen = openGrupos.has(gkey);
                              return (
                                <div key={gi} className="border rounded">
                                  <div className="flex items-center gap-2 p-2 bg-warning/15 border-b">
                                    <button onClick={() => toggle(openGrupos, gkey, (s) => setOpenGrupos(s as Set<string>))}>
                                      {gopen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                                    </button>
                                    <span className="text-warning">●</span>
                                    <Input className="flex-1 font-medium text-sm" value={grupo.orgao}
                                      onChange={(e) => update((c) => { c.partes[pi].secoes[si].grupos[gi].orgao = e.target.value; return c; })} />
                                    <span className="text-xs text-base-content/60">{grupo.itens.length} itens</span>
                                    <button onClick={() => movGrupo(pi, si, gi, -1)} className="text-base-content/60"><ArrowUp className="size-4" /></button>
                                    <button onClick={() => movGrupo(pi, si, gi, 1)} className="text-base-content/60"><ArrowDown className="size-4" /></button>
                                    <button onClick={() => delGrupo(pi, si, gi)} className="text-error"><Trash2 className="size-4" /></button>
                                  </div>
                                  {gopen && (
                                    <div className="p-2 space-y-1.5">
                                      {grupo.itens.map((item, ii) => {
                                        const ikey = `${gkey}-${ii}`;
                                        const iopen = openItens.has(ikey);
                                        return (
                                          <div key={ii} className="border rounded bg-base-200/40">
                                            <div className="flex items-center gap-2 p-2">
                                              <button onClick={() => toggle(openItens, ikey, (s) => setOpenItens(s as Set<string>))}>
                                                {iopen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                                              </button>
                                              <span className="text-xs text-base-content/70 font-mono shrink-0">
                                                {item.tipo}: {item.numero || "(sem nº)"}
                                              </span>
                                              <span className="flex-1 text-xs text-base-content/70 truncate" title={item.objeto}>
                                                {item.objeto || ""}
                                              </span>
                                              <button onClick={() => movItem(pi, si, gi, ii, -1)} className="text-base-content/60"><ArrowUp className="size-3.5" /></button>
                                              <button onClick={() => movItem(pi, si, gi, ii, 1)} className="text-base-content/60"><ArrowDown className="size-3.5" /></button>
                                              <button onClick={() => delItem(pi, si, gi, ii)} className="text-error"><Trash2 className="size-3.5" /></button>
                                            </div>
                                            {iopen && (
                                              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 p-3 pt-1">
                                                {/* Detalhamento da Situação de Contratação (JSONB) */}
                                                <div className="md:col-span-2">
                                                  <label className="text-[11px] text-base-content/70 mb-0.5 block">
                                                    Detalhamento da Situação <span className="text-base-content/40">(uma linha por campo: <code>Chave: Valor</code>)</span>
                                                  </label>
                                                  <textarea
                                                    className="w-full rounded border border-base-300 px-2 py-1 text-sm min-h-[60px] font-mono"
                                                    value={formatSitDet(item.situacao_contratacao_detalhe)}
                                                    onChange={(e) => update((c) => {
                                                      const it = c.partes[pi].secoes[si].grupos[gi].itens[ii] as Item;
                                                      it.situacao_contratacao_detalhe = parseSitDet(e.target.value);
                                                      return c;
                                                    })}
                                                    placeholder="Ex: Data Prevista: 30/06/2026&#10;Motivo: Pendência de documentação"
                                                  />
                                                </div>
                                                {ITEM_FIELDS.map(([k, label, type]) => (
                                                  <div key={k} className={type === "textarea" ? "md:col-span-2" : ""}>
                                                    <label className="text-[11px] text-base-content/70 mb-0.5 block">{label}</label>
                                                    {type === "textarea" ? (
                                                      <textarea
                                                        className="w-full rounded border border-base-300 px-2 py-1 text-sm min-h-[60px]"
                                                        value={(item[k] as string) || ""}
                                                        onChange={(e) => update((c) => {
                                                          (c.partes[pi].secoes[si].grupos[gi].itens[ii] as Record<string, unknown>)[k] = e.target.value;
                                                          return c;
                                                        })}
                                                      />
                                                    ) : (
                                                      <Input type={type}
                                                        value={item[k] == null ? "" : String(item[k])}
                                                        onChange={(e) => update((c) => {
                                                          const v: string | number | null = type === "number"
                                                            ? (e.target.value === "" ? null : Number(e.target.value))
                                                            : e.target.value;
                                                          (c.partes[pi].secoes[si].grupos[gi].itens[ii] as Record<string, unknown>)[k] = v;
                                                          return c;
                                                        })}
                                                      />
                                                    )}
                                                  </div>
                                                ))}
                                                {item.fonte && (
                                                  <div className="md:col-span-2 text-[10px] text-base-content/40">
                                                    Origem: <code className="bg-base-200 px-1 rounded">{item.fonte}</code>
                                                    {item.fonte_ref && <span> (ref: {item.fonte_ref})</span>}
                                                  </div>
                                                )}
                                              </div>
                                            )}
                                          </div>
                                        );
                                      })}
                                      <button onClick={() => addItem(pi, si, gi)}
                                        className="w-full text-xs text-primary hover:bg-primary/10 rounded py-1.5 flex items-center justify-center gap-1">
                                        <Plus className="size-3.5" /> Adicionar item
                                      </button>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                            <button onClick={() => addGrupo(pi, si)}
                              className="w-full text-xs text-warning hover:bg-warning/15 rounded py-1.5 flex items-center justify-center gap-1">
                              <Plus className="size-3.5" /> Adicionar grupo (Órgão)
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <button onClick={() => addSecao(pi)}
                    className="w-full text-sm text-base-content/70 hover:bg-base-200 rounded py-1.5 flex items-center justify-center gap-1 border border-dashed">
                    <Plus className="size-4" /> Adicionar seção
                  </button>
                </div>
              )}
            </div>
          );
        })}
        <button onClick={addParte}
          className="w-full text-sm font-semibold text-primary hover:bg-primary/10 rounded py-2 flex items-center justify-center gap-2 border-2 border-dashed border-primary">
          <Plus className="size-4" /> Adicionar PARTE
        </button>
      </div>
    </div>
  );
}
