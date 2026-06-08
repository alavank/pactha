"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  UserCircle2, Loader2, Search, ChevronDown, ChevronRight,
  Landmark, Building2, FileText, Eraser,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ParlamentarItem {
  nome_normalizado: string;
  nome_display: string;
  total_lancamentos: number;
  valor_total: number;
  municipios: string[];
  por_fonte: { sigcon: number; voluntaria: number; emenda: number };
}

interface DetalheSigcon {
  id: number;
  municipio_nome: string;
  numero: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_total: number;
  valor_repasse: number;
  responsaveis: string | null;
  dt_vigencia_atual: string | null;
  ano: number | null;
  orgao: string | null;
}

interface DetalheVoluntaria {
  id: number;
  municipio_nome: string;
  numero_proposta: string;
  codigo_instrumento: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_global: number;
  valor_repasse: number;
  parlamentar: string | null;
  dt_fim_vigencia: string | null;
  orgao: string | null;
  situacao_contratacao: string | null;
}

interface DetalheEmenda {
  id: number;
  municipio_nome: string;
  nr_indicacao: string;
  ano: number | null;
  beneficiario: string | null;
  tipo_atendimento: string | null;
  valor_indicacao: number;
  status_indicacao: string | null;
  uo_sigla: string | null;
}

interface ParlamentarDetalhe {
  nome_consulta: string;
  sigcon: DetalheSigcon[];
  voluntarias: DetalheVoluntaria[];
  emendas: DetalheEmenda[];
  total_sigcon: number;
  total_voluntarias: number;
  total_emendas: number;
  total_geral: number;
  valor_total: number;
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "-";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function ParlamentaresInner() {
  const sp = useSearchParams();
  const municipioId = sp.get("municipio_id");

  const [items, setItems] = useState<ParlamentarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [detailCache, setDetailCache] = useState<Record<string, ParlamentarDetalhe | "loading" | "error">>({});

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (municipioId) params.municipio_id = municipioId;
      if (search.trim()) params.q = search.trim();
      const r = await api.get<{ items: ParlamentarItem[] }>("/parlamentares", { params });
      setItems(r.data.items);
    } catch (e) {
      console.error("erro parlamentares", e);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [municipioId, search]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar();
  }, [carregar]);

  const toggle = async (item: ParlamentarItem) => {
    const k = item.nome_normalizado;
    const ns = new Set(expandedKeys);
    if (ns.has(k)) {
      ns.delete(k);
      setExpandedKeys(ns);
      return;
    }
    ns.add(k);
    setExpandedKeys(ns);
    if (detailCache[k]) return;
    setDetailCache((c) => ({ ...c, [k]: "loading" }));
    try {
      const params: Record<string, string> = {};
      if (municipioId) params.municipio_id = municipioId;
      // Backend faz ILIKE — usa o nome display original do registro
      const nome = encodeURIComponent(item.nome_display);
      const r = await api.get<ParlamentarDetalhe>(`/parlamentares/${nome}`, { params });
      setDetailCache((c) => ({ ...c, [k]: r.data }));
    } catch (e) {
      console.error("erro detalhe", e);
      setDetailCache((c) => ({ ...c, [k]: "error" }));
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <UserCircle2 className="size-6 text-violet-700" />
          Parlamentares
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Lista agregada dos parlamentares (deputados estaduais/federais e senadores)
          com lançamentos vinculados — convênios SIGCON-MG, propostas TransfereGov/SICONV
          e emendas estaduais. Clique para ver os lançamentos.
        </p>
      </div>

      {/* Filtro */}
      <div className="bg-white border rounded p-4 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-slate-600 mb-1 block">Buscar parlamentar</label>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Ex: Eduardo Azevedo"
            onKeyDown={(e) => { if (e.key === "Enter") carregar(); }}
          />
        </div>
        <Button onClick={carregar} className="bg-violet-600 hover:bg-violet-700">
          <Search className="size-4 mr-1" /> Buscar
        </Button>
        {(search || municipioId) && (
          <Button variant="outline" onClick={() => { setSearch(""); }}>
            <Eraser className="size-4 mr-1" /> Limpar
          </Button>
        )}
      </div>

      {/* Resumo */}
      <div className="text-xs text-slate-500">
        {loading ? "Carregando..." : (
          <>
            <strong>{items.length}</strong> parlamentares
            {municipioId && " no município selecionado"}
            {!municipioId && " (todos os municípios)"}
          </>
        )}
      </div>

      {/* Lista */}
      <div className="space-y-2">
        {loading && (
          <div className="flex justify-center py-12">
            <Loader2 className="size-8 animate-spin text-violet-600" />
          </div>
        )}
        {!loading && items.length === 0 && (
          <div className="bg-slate-50 border border-slate-200 rounded p-12 text-center text-slate-500">
            Nenhum parlamentar encontrado. Os parlamentares são extraídos automaticamente
            dos campos: SIGCON (responsáveis), TransfereGov (parlamentar) e emendas estaduais
            (nome_responsavel). Se a lista estiver vazia, é porque essas fontes ainda não foram
            populadas pelos scrapers.
          </div>
        )}
        {!loading && items.map((p) => {
          const expanded = expandedKeys.has(p.nome_normalizado);
          const detail = detailCache[p.nome_normalizado];
          return (
            <div key={p.nome_normalizado} className="bg-white border rounded">
              <button
                onClick={() => toggle(p)}
                className="w-full flex items-center gap-3 p-3 hover:bg-violet-50/40 transition text-left"
              >
                {expanded ? <ChevronDown className="size-4 text-violet-600 shrink-0" /> : <ChevronRight className="size-4 text-slate-400 shrink-0" />}
                <UserCircle2 className="size-8 text-violet-500 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-slate-900">{p.nome_display}</div>
                  <div className="text-xs text-slate-500 flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
                    <span>{p.total_lancamentos} lançamentos</span>
                    <span className="font-medium text-emerald-700">{fmtMoney(p.valor_total)}</span>
                    <span className="text-slate-400">·</span>
                    {p.por_fonte.sigcon > 0 && (
                      <span className="text-blue-700">SIGCON: {p.por_fonte.sigcon}</span>
                    )}
                    {p.por_fonte.voluntaria > 0 && (
                      <span className="text-emerald-700">TransfereGov: {p.por_fonte.voluntaria}</span>
                    )}
                    {p.por_fonte.emenda > 0 && (
                      <span className="text-amber-700">Emendas: {p.por_fonte.emenda}</span>
                    )}
                    {p.municipios.length > 0 && (
                      <>
                        <span className="text-slate-400">·</span>
                        <span>{p.municipios.join(", ")}</span>
                      </>
                    )}
                  </div>
                </div>
              </button>

              {expanded && (
                <div className="border-t bg-slate-50/50 p-4 space-y-4">
                  {detail === "loading" && (
                    <div className="flex justify-center py-6">
                      <Loader2 className="size-5 animate-spin text-violet-600" />
                    </div>
                  )}
                  {detail === "error" && (
                    <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-3">
                      Erro ao carregar lançamentos. Tente novamente.
                    </div>
                  )}
                  {detail && typeof detail === "object" && (
                    <>
                      {/* Resumo dentro do expand */}
                      <div className="text-xs text-slate-600 flex flex-wrap gap-4 pb-2 border-b border-slate-200">
                        <span><strong>{detail.total_geral}</strong> lançamentos totais</span>
                        <span className="text-emerald-700 font-semibold">{fmtMoney(detail.valor_total)}</span>
                      </div>

                      {/* SIGCON */}
                      {detail.sigcon.length > 0 && (
                        <Section
                          icon={<Building2 className="size-4 text-blue-600" />}
                          title={`SIGCON-MG (Estadual) — ${detail.sigcon.length} convênio(s)`}
                        >
                          <Table headers={["Município", "Nº SIGCON", "Órgão", "Situação", "Valor Total", "Vigência", "Objeto"]}>
                            {detail.sigcon.map((s) => (
                              <tr key={s.id} className="even:bg-white">
                                <Td>{s.municipio_nome}</Td>
                                <Td mono>{s.numero || "-"}</Td>
                                <Td className="text-xs">{s.orgao || "-"}</Td>
                                <Td className="text-xs">{s.situacao || "-"}</Td>
                                <Td>{fmtMoney(s.valor_total)}</Td>
                                <Td>{s.dt_vigencia_atual || "-"}</Td>
                                <Td className="text-xs max-w-[280px] truncate" title={s.objeto || ""}>
                                  {s.objeto || "-"}
                                </Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* Voluntarias */}
                      {detail.voluntarias.length > 0 && (
                        <Section
                          icon={<Landmark className="size-4 text-emerald-600" />}
                          title={`TransfereGov / SICONV (Federal) — ${detail.voluntarias.length} proposta(s)`}
                        >
                          <Table headers={["Município", "Nº Proposta", "Instrumento", "Órgão", "Situação", "Sit. Contrat.", "Valor Global", "Fim Vig.", "Objeto"]}>
                            {detail.voluntarias.map((v) => (
                              <tr key={v.id} className="even:bg-white">
                                <Td>{v.municipio_nome}</Td>
                                <Td mono>{v.numero_proposta}</Td>
                                <Td mono>{v.codigo_instrumento || "-"}</Td>
                                <Td className="text-xs">{v.orgao || "-"}</Td>
                                <Td className="text-xs">{v.situacao || "-"}</Td>
                                <Td className="text-xs">{v.situacao_contratacao || "-"}</Td>
                                <Td>{fmtMoney(v.valor_global)}</Td>
                                <Td>{v.dt_fim_vigencia || "-"}</Td>
                                <Td className="text-xs max-w-[280px] truncate" title={v.objeto || ""}>
                                  {v.objeto || "-"}
                                </Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* Emendas */}
                      {detail.emendas.length > 0 && (
                        <Section
                          icon={<FileText className="size-4 text-amber-600" />}
                          title={`Emendas Estaduais — ${detail.emendas.length} indicação(ões)`}
                        >
                          <Table headers={["Município", "Indicação", "Ano", "UO", "Beneficiário", "Tipo", "Valor", "Status"]}>
                            {detail.emendas.map((e) => (
                              <tr key={e.id} className="even:bg-white">
                                <Td>{e.municipio_nome}</Td>
                                <Td mono>{e.nr_indicacao}</Td>
                                <Td>{e.ano || "-"}</Td>
                                <Td>{e.uo_sigla || "-"}</Td>
                                <Td className="text-xs">{e.beneficiario || "-"}</Td>
                                <Td className="text-xs">{e.tipo_atendimento || "-"}</Td>
                                <Td>{fmtMoney(e.valor_indicacao)}</Td>
                                <Td className="text-xs">{e.status_indicacao || "-"}</Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {detail.total_geral === 0 && (
                        <div className="text-sm text-slate-500 italic text-center py-4">
                          Nenhum lançamento encontrado para este parlamentar.
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2 mb-2">
        {icon} {title}
      </h3>
      <div className="overflow-x-auto rounded border border-slate-200 bg-white">
        {children}
      </div>
    </div>
  );
}

function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <table className="min-w-full text-xs">
      <thead className="bg-slate-50 text-slate-700">
        <tr>
          {headers.map((h, i) => (
            <th key={i} className="text-left font-semibold px-3 py-1.5 border-b">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function Td({ children, mono, className, title }: { children: React.ReactNode; mono?: boolean; className?: string; title?: string }) {
  return (
    <td className={`px-3 py-1.5 border-b border-slate-100 ${mono ? "font-mono" : ""} ${className || ""}`} title={title}>
      {children}
    </td>
  );
}

export default function ParlamentaresPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="size-6 animate-spin text-violet-600" /></div>}>
      <ParlamentaresInner />
    </Suspense>
  );
}
