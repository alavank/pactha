"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Search, Eraser, Loader2, ExternalLink, Eye, X } from "lucide-react";
import api from "@/lib/api";
import MultiSelect from "@/components/MultiSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  dias_restantes?: number | null;
  atualizado_em?: string;
  situacao_contratacao?: string | null;
  clausula_suspensiva_dt_prevista?: string | null;
  clausula_suspensiva_motivo?: string | null;
  parlamentar?: string | null;
  valor_global?: number | null;
  valor_repasse?: number | null;
  valor_contrapartida?: number | null;
  situacao_contratacao_detalhe?: Record<string, string | null> | null;
}

interface Resp { items: Proposta[]; total: number; atualizado_em?: string; }

function diasBadge(d?: number | null): { txt: string; cls: string } {
  if (d === null || d === undefined) return { txt: "-", cls: "bg-gray-100 text-gray-500" };
  if (d < 0) return { txt: `${Math.abs(d)}d`, cls: "bg-red-100 text-red-700" };
  if (d <= 60) return { txt: `${d}d`, cls: "bg-amber-100 text-amber-700" };
  if (d <= 180) return { txt: `${d}d`, cls: "bg-yellow-50 text-yellow-700" };
  return { txt: `${d}d`, cls: "bg-green-100 text-green-700" };
}

interface Detalhe extends Proposta {
  detalhe?: Record<string, string | string[]>;
}

const PORTAL_BASE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest";

const VIGENCIA_LABELS: Record<string, string> = {
  vence60: "Vence em 60 dias",
  vence120: "Vence em 120 dias",
  prestacao: "Prestacao de Contas (+90d vencido)",
};

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

export default function TransfereGovPropostas({
  categoria,
  titulo,
  subtitulo,
}: {
  categoria: "geral" | "voluntarias" | "rejeitadas";
  titulo: string;
  subtitulo: string;
}) {
  const sp = useSearchParams();
  const municipioId = sp.get("municipio_id");
  const vigenciaParam = sp.get("vigencia");

  const [items, setItems] = useState<Proposta[]>([]);
  const [atualizadoEm, setAtualizadoEm] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [vigencia, setVigencia] = useState(vigenciaParam ?? "");

  const [detalhe, setDetalhe] = useState<Detalhe | null>(null);
  const [loadingDet, setLoadingDet] = useState(false);

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { municipio_id: municipioId, categoria };
      if (search.trim()) params.search = search.trim();
      if (vigencia) params.vigencia = vigencia;
      const r = await api.get<Resp>("/transferegov/voluntarias", { params });
      setItems(r.data.items); setAtualizadoEm(r.data.atualizado_em);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId, search, vigencia, categoria]);

  // Sincroniza filtro de vigencia com o parametro da URL (vindo dos KPIs)
  useEffect(() => { setVigencia(vigenciaParam ?? ""); }, [vigenciaParam]);

  // Busca ao montar e sempre que municipio/categoria/vigencia mudarem
  useEffect(() => { if (municipioId) buscar(); }, [municipioId, vigencia, categoria]); // eslint-disable-line react-hooks/exhaustive-deps

  // Opcoes do multi-select = situacoes distintas presentes nos dados carregados
  const situacaoOptions = useMemo(
    () => Array.from(new Set(items.map((i) => i.situacao).filter(Boolean))).sort(),
    [items]
  );

  // Filtro de situacao client-side (multi-select)
  const displayItems = useMemo(
    () => (situacoesSel.length ? items.filter((i) => situacoesSel.includes(i.situacao)) : items),
    [items, situacoesSel]
  );

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
          <h1 className="text-2xl font-bold text-gray-900">{titulo}</h1>
          <p className="text-sm text-slate-500">
            {subtitulo}
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
            <label className="text-xs text-slate-600 mb-1 block">Situacao (multi)</label>
            <MultiSelect
              options={situacaoOptions}
              selected={situacoesSel}
              onChange={setSituacoesSel}
              placeholder="Todas as situacoes"
              width="w-full"
            />
          </div>
          <div className="flex items-end gap-2">
            <Button onClick={buscar} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
              {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />} Filtrar
            </Button>
            <Button variant="outline" onClick={() => { setSearch(""); setSituacoesSel([]); setVigencia(""); setTimeout(buscar, 100); }}>
              <Eraser className="size-4 mr-1" /> Limpar
            </Button>
          </div>
        </div>
      </div>

      {/* Chip do filtro ativo de vigencia (vindo dos KPIs do dashboard) */}
      {vigencia && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500">Filtro ativo:</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-fuchsia-50 border border-fuchsia-200 px-2.5 py-0.5 text-xs font-medium text-fuchsia-700">
            {VIGENCIA_LABELS[vigencia] ?? vigencia}
            <button
              onClick={() => setVigencia("")}
              className="text-fuchsia-500 hover:text-fuchsia-800"
              aria-label="Limpar filtro"
            >
              ×
            </button>
          </span>
        </div>
      )}

      <div className="bg-white border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm"><strong>{displayItems.length}</strong> propostas</div>
        {loading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-gray-100 rounded" />)}
          </div>
        ) : displayItems.length === 0 ? (
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
                <TableHead className="w-[55px]">Dias</TableHead>
                <TableHead>Objeto</TableHead>
                <TableHead className="w-[50px] text-center">Ver</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayItems.map((p, i) => (
                <TableRow key={i} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-blue-50 cursor-pointer"
                          onClick={() => abrirDetalhe(p.numero_proposta)}>
                  <TableCell className="font-mono">{p.codigo_instrumento || "-"}</TableCell>
                  <TableCell className="font-mono">{p.numero_proposta}</TableCell>
                  <TableCell className="truncate" title={p.orgao}>{p.orgao}</TableCell>
                  <TableCell className="max-w-[200px]" title={p.situacao}>
                    <span className={`block truncate px-1.5 py-0.5 rounded text-[10px] ${badgeColor(p.situacao)}`}>
                      {p.situacao}
                    </span>
                  </TableCell>
                  <TableCell>{p.dt_inicio_vigencia || "-"}</TableCell>
                  <TableCell>{p.dt_fim_vigencia || "-"}</TableCell>
                  <TableCell>
                    {(() => { const b = diasBadge(p.dias_restantes); return (
                      <span className={`inline-block px-1.5 py-0.5 rounded-full text-[10px] font-medium ${b.cls}`}>{b.txt}</span>
                    ); })()}
                  </TableCell>
                  <TableCell className="truncate" title={p.objeto || ""}>{p.objeto || "-"}</TableCell>
                  <TableCell className="text-center">
                    <button onClick={(e) => { e.stopPropagation(); abrirDetalhe(p.numero_proposta); }}
                            className="inline-flex w-6 h-6 items-center justify-center rounded bg-blue-500 hover:bg-blue-600 text-white">
                      <Eye className="size-3" />
                    </button>
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

                {(detalhe.situacao_contratacao || detalhe.parlamentar || detalhe.situacao_contratacao_detalhe) && (
                  <Section title="Contratação e Indicação">
                    <Grid>
                      <Field label="Situação de Contratação Atual" value={detalhe.situacao_contratacao} />
                      <Field label="Parlamentar Responsável" value={detalhe.parlamentar} />
                    </Grid>
                    {detalhe.situacao_contratacao_detalhe && Object.keys(detalhe.situacao_contratacao_detalhe).filter(k => !k.startsWith("_")).length > 0 && (
                      <div className="mt-3 rounded border-l-4 border-amber-400 bg-amber-50 p-3">
                        <div className="text-xs font-semibold text-amber-900 mb-2">
                          Detalhe da Situação de Contratação
                          {detalhe.situacao_contratacao_detalhe._label_botao && (
                            <span className="ml-1 text-amber-700 font-normal">
                              ({String(detalhe.situacao_contratacao_detalhe._label_botao)})
                            </span>
                          )}
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          {Object.entries(detalhe.situacao_contratacao_detalhe)
                            .filter(([k]) => !k.startsWith("_"))
                            .map(([k, v]) => (
                              <Field key={k} label={k} value={v == null ? "-" : String(v)} />
                            ))}
                        </div>
                      </div>
                    )}
                  </Section>
                )}

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
                    <ul className="text-sm space-y-1.5">
                      {(detalhe.detalhe!._documentos as string[]).map((d, i) => {
                        const nome = d.replace(/\s*Baixar( Contrapartida)?\s*$/i, "").trim();
                        return (
                          <li key={i} className="flex items-start gap-2 text-slate-700">
                            <span className="text-indigo-500 mt-0.5">📄</span>
                            <span className="break-words">{nome}</span>
                          </li>
                        );
                      })}
                    </ul>
                    <a href={PORTAL_BASE} target="_blank" rel="noreferrer noopener"
                       className="inline-flex items-center gap-1 mt-3 text-xs text-white bg-blue-600 hover:bg-blue-700 rounded px-3 py-1.5">
                      <ExternalLink className="size-3" /> Baixar no portal (Acesso Livre)
                    </a>
                    <p className="text-[11px] text-slate-500 mt-1.5">
                      Os anexos do TransfereGov exigem sessão do portal. Clique acima, pesquise o município/proposta
                      e baixe os PDFs diretamente no Acesso Livre.
                    </p>
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
