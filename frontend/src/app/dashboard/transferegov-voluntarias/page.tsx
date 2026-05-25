"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Search, Eraser, Loader2, ExternalLink, Eye, X } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import RelacionadosButton from "@/components/RelacionadosModal";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

interface Proposta {
  numero_proposta: string;
  situacao: string;
  orgao: string;
  proponente: string;
  possui_parecer: string;
  identificacao: string;
  codigo_instrumento?: string;
  modalidade?: string;
  situacao_siafi?: string;
  numero_processo?: string;
  objeto?: string;
  programa?: string;
  dt_inicio_vigencia?: string;
  dt_fim_vigencia?: string;
  dt_proposta?: string;
  dt_assinatura?: string;
  atualizado_em?: string;
}

interface Resp { items: Proposta[]; total: number; atualizado_em?: string; }

interface Detalhe extends Proposta {
  detalhe?: Record<string, string | string[]>;
}

const PORTAL_BASE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest";

function fmtData(iso?: string): string {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return "-"; }
}
function badgeColor(sit: string): string {
  const s = (sit || "").toLowerCase();
  if (s.includes("execu")) return "bg-blue-100 text-blue-800";
  if (s.includes("aprovad") || s.includes("assinado")) return "bg-green-100 text-green-800";
  if (s.includes("rejeitad") || s.includes("impedimento")) return "bg-red-100 text-red-800";
  if (s.includes("nlise") || s.includes("análise")) return "bg-amber-100 text-amber-800";
  return "bg-gray-100 text-gray-700";
}

export default function TransfereGovVoluntariasPage() {
  const sp = useSearchParams();
  const municipioId = sp.get("municipio_id");

  const [items, setItems] = useState<Proposta[]>([]);
  const [total, setTotal] = useState(0);
  const [atualizadoEm, setAtualizadoEm] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [situacao, setSituacao] = useState("");

  const [detalhe, setDetalhe] = useState<Detalhe | null>(null);
  const [loadingDet, setLoadingDet] = useState(false);

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { municipio_id: municipioId };
      if (search.trim()) params.search = search.trim();
      if (situacao.trim()) params.situacao = situacao.trim();
      const r = await api.get<Resp>("/transferegov/voluntarias", { params });
      setItems(r.data.items); setTotal(r.data.total); setAtualizadoEm(r.data.atualizado_em);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId, search, situacao]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId]); // eslint-disable-line react-hooks/exhaustive-deps

  const abrirDetalhe = async (numero: string) => {
    setDetalhe(null); setLoadingDet(true);
    try {
      const r = await api.get<Detalhe>(`/transferegov/voluntarias/${encodeURIComponent(numero)}`,
        { params: { municipio_id: municipioId } });
      setDetalhe(r.data);
    } catch (e) { console.error(e); } finally { setLoadingDet(false); }
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">TransfereGov - Transferencias Voluntarias</h1>
          <p className="text-sm text-slate-500">
            Convenios e contratos de repasse (SICONV) - acesso livre
            {atualizadoEm && <span className="ml-2 text-xs">· Atualizado: {fmtData(atualizadoEm)}</span>}
          </p>
        </div>
        <a href={PORTAL_BASE} target="_blank" rel="noreferrer noopener"
           className="text-xs text-blue-700 hover:underline inline-flex items-center gap-1">
          <ExternalLink className="size-3" /> Portal oficial
        </a>
      </div>

      <div className="bg-white border rounded p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Buscar (nº / proponente)</label>
            <Input value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Ex: 048291/2025" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Situacao</label>
            <Input value={situacao} onChange={(e) => setSituacao(e.target.value)}
                   placeholder="Ex: Em execucao" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div className="flex items-end gap-2">
            <Button onClick={buscar} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
              {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />} Filtrar
            </Button>
            <Button variant="outline" onClick={() => { setSearch(""); setSituacao(""); setTimeout(buscar, 100); }}>
              <Eraser className="size-4 mr-1" /> Limpar
            </Button>
          </div>
        </div>
      </div>

      <div className="bg-white border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm"><strong>{total}</strong> propostas</div>
        {loading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-gray-100 rounded" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">Nenhuma proposta encontrada.</div>
        ) : (
          <Table className="text-xs table-fixed w-full">
            <TableHeader>
              <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold bg-blue-50">
                <TableHead className="w-[95px]">Código Instr.</TableHead>
                <TableHead className="w-[90px]">Nº Proposta</TableHead>
                <TableHead>Órgão</TableHead>
                <TableHead className="w-[200px]">Situação</TableHead>
                <TableHead className="w-[80px]">Início Vig.</TableHead>
                <TableHead className="w-[80px]">Fim Vig.</TableHead>
                <TableHead>Objeto</TableHead>
                <TableHead className="w-[50px] text-center">Ver</TableHead>
                <TableHead className="w-[40px] text-center">Rel.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((p, i) => (
                <TableRow key={i} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-blue-50 cursor-pointer"
                          onClick={() => abrirDetalhe(p.numero_proposta)}>
                  <TableCell className="font-mono">{p.codigo_instrumento || "-"}</TableCell>
                  <TableCell className="font-mono">{p.numero_proposta}</TableCell>
                  <TableCell className="truncate" title={p.orgao}>{p.orgao}</TableCell>
                  <TableCell>
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${badgeColor(p.situacao)}`}>
                      {p.situacao}
                    </span>
                  </TableCell>
                  <TableCell>{p.dt_inicio_vigencia || "-"}</TableCell>
                  <TableCell>{p.dt_fim_vigencia || "-"}</TableCell>
                  <TableCell className="truncate" title={p.objeto || ""}>{p.objeto || "-"}</TableCell>
                  <TableCell className="text-center">
                    <button onClick={(e) => { e.stopPropagation(); abrirDetalhe(p.numero_proposta); }}
                            className="inline-flex w-6 h-6 items-center justify-center rounded bg-blue-500 hover:bg-blue-600 text-white">
                      <Eye className="size-3" />
                    </button>
                  </TableCell>
                  <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                    <RelacionadosButton params={{
                      municipio_id: municipioId, fonte: "voluntarias",
                      proposta: p.numero_proposta, instrumento: p.codigo_instrumento,
                      processo: p.numero_processo, objeto: p.objeto,
                    }} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Modal detalhe */}
      {(detalhe !== null || loadingDet) && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto"
             onClick={() => setDetalhe(null)}>
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-5xl mt-4 mb-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-white px-5 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="text-xl font-light text-slate-900">
                Consultar Pré-Instrumento/Instrumento {detalhe?.codigo_instrumento || detalhe?.numero_proposta || ""}
              </h3>
              <button onClick={() => setDetalhe(null)}><X className="size-5 text-gray-500 hover:text-gray-700" /></button>
            </div>
            {loadingDet ? (
              <div className="text-center py-16"><Loader2 className="size-8 animate-spin mx-auto text-blue-600" /></div>
            ) : detalhe && (
              <div className="p-5 space-y-5 max-h-[75vh] overflow-y-auto">
                <Section title="Dados da Proposta">
                  <Grid>
                    <Field label="Modalidade" value={detalhe.modalidade} />
                    <Field label="Situação no SIAFI" value={detalhe.situacao_siafi} />
                    <Field label="Situação" value={detalhe.situacao} />
                    <Field label="Código do Instrumento" value={detalhe.codigo_instrumento} />
                    <Field label="Número da Proposta" value={detalhe.numero_proposta} />
                    <Field label="Número do Processo" value={detalhe.numero_processo} />
                    <Field label="Órgão" value={detalhe.orgao} />
                    <Field label="Programa" value={detalhe.programa} />
                  </Grid>
                </Section>

                <Section title="Vigência e Datas">
                  <Grid>
                    <Field label="Data da Proposta" value={detalhe.dt_proposta} />
                    <Field label="Data de Assinatura" value={detalhe.dt_assinatura} />
                    <Field label="Início de Vigência" value={detalhe.dt_inicio_vigencia} />
                    <Field label="Término de Vigência" value={detalhe.dt_fim_vigencia} />
                  </Grid>
                </Section>

                <Section title="Proponente">
                  <Grid cols={2}>
                    <Field label="Proponente" value={detalhe.proponente} />
                    <Field label="CNPJ" value={detalhe.identificacao} />
                  </Grid>
                </Section>

                <Section title="Objeto">
                  <p className="text-sm text-slate-800 bg-slate-50 border rounded p-3">{detalhe.objeto || "-"}</p>
                </Section>

                {detalhe.detalhe && Object.keys(detalhe.detalhe).length > 0 && (
                  <Section title="Justificativa e demais informações">
                    <div className="space-y-2">
                      {Object.entries(detalhe.detalhe)
                        .filter(([k]) => !k.startsWith("_") && !["Modalidade","Situação no SIAFI","Código do Instrumento","Número da Proposta","Número do Processo","Órgão","Objeto do Instrumento"].includes(k))
                        .map(([k, v]) => (
                          <div key={k} className="text-sm border-b border-slate-100 pb-1">
                            <span className="text-[11px] font-semibold text-slate-600">{k}: </span>
                            <span className="text-slate-800">{Array.isArray(v) ? v.join(" | ") : v}</span>
                          </div>
                        ))}
                    </div>
                  </Section>
                )}

                {Array.isArray(detalhe.detalhe?._documentos) && (detalhe.detalhe!._documentos as string[]).length > 0 && (
                  <Section title="Documentos Digitalizados">
                    <ul className="text-sm list-disc pl-5 space-y-1">
                      {(detalhe.detalhe!._documentos as string[]).map((d, i) => (
                        <li key={i} className="text-slate-700">{d}</li>
                      ))}
                    </ul>
                  </Section>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-slate-800 border-b border-blue-600 pb-1 mb-3">{title}</h4>
      {children}
    </div>
  );
}
function Grid({ children, cols = 4 }: { children: React.ReactNode; cols?: 2 | 3 | 4 }) {
  const cls = cols === 2 ? "md:grid-cols-2" : cols === 3 ? "md:grid-cols-3" : "md:grid-cols-4";
  return <div className={`grid grid-cols-1 ${cls} gap-3`}>{children}</div>;
}
function Field({ label, value }: { label: string; value?: string | null }) {
  const v = value === null || value === undefined || value === "" ? "-" : String(value);
  return (
    <div>
      <div className="text-[11px] text-slate-600 mb-0.5">{label}</div>
      <div className="border border-slate-300 rounded px-2 py-1.5 bg-slate-50 text-sm text-slate-900 break-words">{v}</div>
    </div>
  );
}
