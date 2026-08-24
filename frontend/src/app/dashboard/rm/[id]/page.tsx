"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Save, Download, RefreshCw, ChevronDown, ChevronRight, Plus, Trash2,
  ArrowUp, ArrowDown, Loader2, ArrowLeft, FileCheck, Lock,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Aviso, BOTAO_CTA, BOTAO_SEC, Bloco, ESTILO_CTA, ESTILO_SEC, Selo } from "@/components/ui/superficies";
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
  // Evento ATUAL do Histórico de Comunicações (TransfereGov mandatárias)
  evento_atual?: string;
  evento_data?: string;
  evento_situacao?: string;
  evento_consideracoes?: string;
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
  /** O veredito do servidor sobre ESTE RM (alcance "somente os que ele criou").
   *  Ausente = a API nao respondeu isso, e a tela fica como era. */
  pode_editar?: boolean | null;
}

const ITEM_FIELDS: Array<[keyof Item, string, "text" | "number" | "date" | "textarea"]> = [
  ["tipo", "Tipo", "text"],
  ["numero", "Número", "text"],
  ["objeto", "Objeto", "textarea"],
  ["parlamentar", "Parlamentar", "text"],
  ["valor_global", "Valor Global (R$)", "number"],
  ["valor_repasse", "Valor Repasse (R$)", "number"],
  ["valor_contrapartida", "Valor Contrapartida (R$)", "number"],
  ["banco", "Banco", "text"],
  ["agencia", "Agência", "text"],
  ["conta", "Conta", "text"],
  ["saldo_bancario", "Saldo Bancário (R$)", "number"],
  ["dt_saldo", "Data do Saldo", "date"],
  ["dt_fim_vigencia", "Final da Vigência", "date"],
  ["situacao_contratacao", "Situação de Contratação", "text"],
  ["situacao_atual", "Situação Atual", "textarea"],
  // Evento ATUAL do Histórico de Comunicações (TransfereGov)
  ["evento_atual", "Evento Atual", "text"],
  ["evento_data", "Data do Evento", "text"],
  ["evento_situacao", "Situação do Evento", "text"],
  ["evento_consideracoes", "Considerações", "textarea"],
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
    if (!confirm("Substituir TODO o conteúdo pelos dados atuais do banco?")) return;
    setRepopulating(true);
    try {
      await api.post(`/rm/${rid}/auto-popular`);
      await load();
    } catch (e) { console.error(e); } finally { setRepopulating(false); }
  };

  const [menuRel, setMenuRel] = useState(false);

  const exportar = (tipo: "completo" | "resumido", formato: "pdf" = "pdf") => {
    setMenuRel(false);
    const token = localStorage.getItem("pactha_token");
    const url = `${api.defaults.baseURL}/rm/${rid}/pdf?tipo=${tipo}&formato=${formato}`;
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        // Só PDF: o totalizado (o único que saía em .xlsx) foi descontinuado.
        window.open(URL.createObjectURL(blob), "_blank");
      });
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
    return <div className="flex h-64 items-center justify-center"><Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-faint)" }} /></div>;
  }

  /* EDICAO REMOVIDA (decisao do dono, 16/08/2026): o RM e um relatorio GERADO
     do banco, nao editado a mao. Esta tela agora e so CONSULTA + EXPORTACAO;
     para atualizar, gera-se de novo na lista (o "Gerar" repopula do banco).
     Forcando `podeEditar=false` reaproveitamos o modo somente-leitura que ja
     existia (Salvar/Finalizar/Re-popular desligados) — nada persiste daqui. */
  const podeEditar = false;

  return (
    <div className="space-y-4">
      {/* Topbar */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm"
            onClick={() => router.push(`/dashboard/rm?municipio_id=${municipioId || rm.municipio_id}`)}>
            <ArrowLeft className="size-4" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-base-content">
              RM {(rm.data_referencia || "").slice(0, 4)} - {rm.municipio_nome}/{rm.uf}
            </h1>
            <div className="mt-1 flex items-center gap-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
              {/* Rascunho e o estado que pede acao; finalizado e o normal, e
                  por isso fica cinza. */}
              <Selo tom={rm.status === "finalizado" ? "neutro" : "atencao"}>{rm.status}</Selo>
              <span>{rm.cidade_emissao}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={repopular} disabled={repopulating || !podeEditar}>
            {repopulating ? <Loader2 className="size-4 animate-spin mr-1" /> : <RefreshCw className="size-4 mr-1" />}
            Re-popular do DB
          </Button>
          {/* "Finalizar" fica junto: ele muda `status`, que só chega ao banco
              pelo mesmo PUT do Salvar. Deixá-lo aceso ofereceria uma alteração
              que não tem como ser gravada. */}
          <Button
            variant="outline"
            disabled={!podeEditar}
            onClick={() => setRm({ ...rm, status: rm.status === "finalizado" ? "rascunho" : "finalizado" })}
          >
            <FileCheck className="size-4 mr-1" /> {rm.status === "finalizado" ? "Reabrir" : "Finalizar"}
          </Button>
          <button type="button" onClick={salvar} disabled={saving || !podeEditar} className={BOTAO_CTA} style={ESTILO_CTA}>
            {saving ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />}
            Salvar
          </button>
          <div className="relative">
            {/* Era verde solido ao lado de um botao violeta solido: dois botoes
                de cores diferentes disputando a mesma linha. So um comanda. */}
            <button type="button" onClick={() => setMenuRel((v) => !v)} className={BOTAO_SEC} style={ESTILO_SEC}>
              <Download className="size-4" /> Relatório <ChevronDown className="size-4" />
            </button>
            {menuRel && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuRel(false)} />
                <div className="absolute right-0 z-20 mt-1 w-60 overflow-hidden py-1 text-[12px]"
                     style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)",
                              borderRadius: "var(--bi-radius-sm)", boxShadow: "var(--bi-shadow)" }}>
                  <button className="w-full text-left px-3 py-2 hover:bg-base-200" onClick={() => exportar("completo")}>
                    <span className="font-medium">Completo</span>
                    <span className="block text-xs text-base-content/60">Detalhado (PDF)</span>
                  </button>
                  <button className="w-full text-left px-3 py-2 hover:bg-base-200" onClick={() => exportar("resumido")}>
                    <span className="font-medium">Resumido</span>
                    <span className="block text-xs text-base-content/60">Só pendências, layout limpo (PDF)</span>
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {!podeEditar && (
        /* Antes do formulário, e não depois: quem chega aqui por um link ou
           pelo botão "Abrir" da lista precisa ler isto ANTES de começar a
           digitar. Atenção, e não crítico — não há nada errado, é o alcance
           configurado para esta conta. */
        <Aviso
          tom="atencao"
          icon={Lock}
          titulo="O RM é gerado do banco — esta tela é só consulta e exportação."
          className=""
        >
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O conteúdo vem automaticamente dos dados do município; não se edita à
            mão. Para atualizar com os dados mais recentes, use <b>Gerar</b> na
            lista de RMs (ele repopula este exercício). Consultar e exportar
            continuam valendo aqui.
          </p>
        </Aviso>
      )}

      {/* Metadata edit */}
      <Bloco className="grid grid-cols-1 gap-3 p-3 md:grid-cols-3">
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">Título</label>
          <Input value={rm.titulo || ""} onChange={(e) => setRm({ ...rm, titulo: e.target.value })} />
        </div>
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">Ano de referência</label>
          <select className="bi-field h-9 w-full p-2 text-sm"
                  value={(rm.data_referencia || "").slice(0, 4)}
                  onChange={(e) => setRm({ ...rm, data_referencia: `${e.target.value}-01-01` })}>
            {(() => { const a = new Date().getFullYear(); return [a + 1, a, a - 1, a - 2, a - 3]; })().map((y) => (
              <option key={y} value={String(y)}>{y}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">Cidade de emissão</label>
          <Input value={rm.cidade_emissao} onChange={(e) => setRm({ ...rm, cidade_emissao: e.target.value })} />
        </div>
      </Bloco>

      {/* Conteudo hierarquico */}
      <div className="space-y-3">
        {rm.conteudo.partes.map((parte, pi) => {
          const popen = openPartes.has(pi);
          return (
            <Bloco key={pi} className="overflow-hidden">
              <div className="flex items-center gap-2 border-b p-2"
                   style={{ background: "var(--bi-surface-2)", borderColor: "var(--bi-line)" }}>
                <button onClick={() => toggle(openPartes as Set<string | number>, pi, (s) => setOpenPartes(s as Set<number>))}>
                  {popen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                </button>
                <Input className="flex-1 font-bold" value={parte.titulo}
                  onChange={(e) => update((c) => { c.partes[pi].titulo = e.target.value; return c; })} />
                <button onClick={() => movParte(pi, -1)} className="text-base-content/60 hover:text-base-content/70"><ArrowUp className="size-4" /></button>
                <button onClick={() => movParte(pi, 1)} className="text-base-content/60 hover:text-base-content/70"><ArrowDown className="size-4" /></button>
                <button onClick={() => delParte(pi)} className="rounded p-1 transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-crit-ink)" }}><Trash2 className="size-4" /></button>
              </div>
              {popen && (
                <div className="p-3 space-y-2">
                  {parte.secoes.map((secao, si) => {
                    const skey = `${pi}-${si}`;
                    const sopen = openSecoes.has(skey);
                    return (
                      <div key={si} className="border rounded">
                        <div className="flex items-center gap-2 border-b p-2"
                             style={{ background: "var(--bi-bg)", borderColor: "var(--bi-line)" }}>
                          <button onClick={() => toggle(openSecoes, skey, (s) => setOpenSecoes(s as Set<string>))}>
                            {sopen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </button>
                          <Input className="flex-1 font-semibold text-sm" value={secao.titulo}
                            onChange={(e) => update((c) => { c.partes[pi].secoes[si].titulo = e.target.value; return c; })} />
                          <button onClick={() => movSecao(pi, si, -1)} className="text-base-content/60"><ArrowUp className="size-4" /></button>
                          <button onClick={() => movSecao(pi, si, 1)} className="text-base-content/60"><ArrowDown className="size-4" /></button>
                          <button onClick={() => delSecao(pi, si)} className="rounded p-1 transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-crit-ink)" }}><Trash2 className="size-4" /></button>
                        </div>
                        {sopen && (
                          <div className="p-2 space-y-2">
                            {secao.grupos.map((grupo, gi) => {
                              const gkey = `${pi}-${si}-${gi}`;
                              const gopen = openGrupos.has(gkey);
                              return (
                                <div key={gi} className="border rounded">
                                  <div className="flex items-center gap-2 border-b p-2"
                                       style={{ background: "var(--bi-surface-2)", borderColor: "var(--bi-line)" }}>
                                    <button onClick={() => toggle(openGrupos, gkey, (s) => setOpenGrupos(s as Set<string>))}>
                                      {gopen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                                    </button>
                                    <span style={{ color: "var(--bi-faint)" }}>●</span>
                                    <Input className="flex-1 font-medium text-sm" value={grupo.orgao}
                                      onChange={(e) => update((c) => { c.partes[pi].secoes[si].grupos[gi].orgao = e.target.value; return c; })} />
                                    <span className="text-xs text-base-content/60">{grupo.itens.length} itens</span>
                                    <button onClick={() => movGrupo(pi, si, gi, -1)} className="text-base-content/60"><ArrowUp className="size-4" /></button>
                                    <button onClick={() => movGrupo(pi, si, gi, 1)} className="text-base-content/60"><ArrowDown className="size-4" /></button>
                                    <button onClick={() => delGrupo(pi, si, gi)} className="rounded p-1 transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-crit-ink)" }}><Trash2 className="size-4" /></button>
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
                                              <button onClick={() => delItem(pi, si, gi, ii)} className="rounded p-1 transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-crit-ink)" }}><Trash2 className="size-3.5" /></button>
                                            </div>
                                            {iopen && (
                                              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 p-3 pt-1">
                                                {/* Detalhamento da Situação de Contratação (JSONB) */}
                                                <div className="md:col-span-2">
                                                  <label className="text-[11px] text-base-content/70 mb-0.5 block">
                                                    Detalhamento da Situação <span className="text-base-content/40">(uma linha por campo: <code>Chave: Valor</code>)</span>
                                                  </label>
                                                  <textarea
                                                    className="bi-field min-h-[60px] w-full px-2 py-1 font-mono text-[12px]"
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
                                                        className="bi-field min-h-[60px] w-full px-2 py-1 text-[12px]"
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
                                        className="flex w-full items-center justify-center gap-1 rounded-lg py-1.5 text-[11px] transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-muted)" }}>
                                        <Plus className="size-3.5" /> Adicionar item
                                      </button>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                            <button onClick={() => addGrupo(pi, si)}
                              className="flex w-full items-center justify-center gap-1 rounded-lg py-1.5 text-[11px] transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-muted)" }}>
                              <Plus className="size-3.5" /> Adicionar grupo (Órgão)
                            </button>
                          </div>
                        )}
                      </div>
                    );
                  })}
                  <button onClick={() => addSecao(pi)}
                    className="flex w-full items-center justify-center gap-1 rounded-lg py-1.5 text-[12px] transition-colors bi-hover"
                    style={{ background: "var(--bi-surface-2)", border: "1px dashed var(--bi-line-strong)", color: "var(--bi-muted)" }}>
                    <Plus className="size-4" /> Adicionar seção
                  </button>
                </div>
              )}
            </Bloco>
          );
        })}
        <button onClick={addParte}
          className="flex w-full items-center justify-center gap-2 rounded-xl py-2 text-[12px] font-semibold transition-colors bi-hover" style={{ background: "var(--bi-surface)", border: "1px dashed var(--bi-line-strong)", color: "var(--bi-muted)" }}>
          <Plus className="size-4" /> Adicionar PARTE
        </button>
      </div>
    </div>
  );
}
