"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Search, Eraser, Loader2, ExternalLink, Eye, X } from "lucide-react";
import api from "@/lib/api";
import MultiSelect from "@/components/MultiSelect";
import AnotacaoButton from "@/components/AnotacaoButton";
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
  if (d === null || d === undefined) return { txt: "-", cls: "bg-base-200 text-base-content/60" };
  if (d < 0) return { txt: `${Math.abs(d)}d`, cls: "bg-error/15 text-error" };
  if (d <= 60) return { txt: `${d}d`, cls: "bg-warning/15 text-warning" };
  if (d <= 180) return { txt: `${d}d`, cls: "bg-warning/15 text-warning" };
  return { txt: `${d}d`, cls: "bg-success/15 text-success" };
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
  if (s.includes("execu")) return "bg-primary/10 text-primary";
  if (s.includes("aprovad") || s.includes("assinado")) return "bg-success/15 text-success";
  if (s.includes("rejeitad") || s.includes("impedimento")) return "bg-error/15 text-error";
  if (s.includes("nlise") || s.includes("análise")) return "bg-warning/15 text-warning";
  return "bg-base-200 text-base-content/70";
}

export default function TransfereGovPropostas({
  categoria,
  titulo,
  subtitulo,
}: {
  categoria: "geral" | "voluntarias" | "rejeitadas" | "encerradas";
  titulo: string;
  subtitulo: string;
}) {
  const sp = useSearchParams();
  const { municipioId } = useMunicipio();
  const vigenciaParam = sp.get("vigencia");

  const [items, setItems] = useState<Proposta[]>([]);
  const [atualizadoEm, setAtualizadoEm] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [vigencia, setVigencia] = useState(vigenciaParam ?? "");
  const [parlamentar, setParlamentar] = useState("");
  const [orgao, setOrgao] = useState("");
  const [sitContratacao, setSitContratacao] = useState("");
  const [vigFimDe, setVigFimDe] = useState("");
  const [vigFimAte, setVigFimAte] = useState("");
  const [baixandoPdf, setBaixandoPdf] = useState(false);

  const [detalhe, setDetalhe] = useState<Detalhe | null>(null);
  const [loadingDet, setLoadingDet] = useState(false);

  const buildParams = useCallback((): Record<string, string> => {
    const params: Record<string, string> = { municipio_id: municipioId || "", categoria };
    if (search.trim()) params.search = search.trim();
    if (vigencia) params.vigencia = vigencia;
    if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
    if (orgao.trim()) params.orgao = orgao.trim();
    if (sitContratacao) params.situacao_contratacao = sitContratacao;
    if (vigFimDe) params.vig_fim_de = vigFimDe;
    if (vigFimAte) params.vig_fim_ate = vigFimAte;
    return params;
  }, [municipioId, categoria, search, vigencia, parlamentar, orgao, sitContratacao, vigFimDe, vigFimAte]);

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const r = await api.get<Resp>("/transferegov/voluntarias", { params: buildParams() });
      setItems(r.data.items); setAtualizadoEm(r.data.atualizado_em);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId, buildParams]);

  const gerarPdf = useCallback(async () => {
    if (!municipioId) return;
    setBaixandoPdf(true);
    try {
      const r = await api.get("/export-pdf/voluntarias", { params: buildParams(), responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url; a.download = `relatorio-federais-${categoria}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); } finally { setBaixandoPdf(false); }
  }, [municipioId, categoria, buildParams]);

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
          <h1 className="text-2xl font-bold text-base-content">{titulo}</h1>
          <p className="text-sm text-base-content/60">
            {subtitulo}
            {atualizadoEm && <span className="ml-2 text-xs">· Atualizado: {fmtData(atualizadoEm)}</span>}
          </p>
        </div>
        <a href={PORTAL_BASE} target="_blank" rel="noreferrer noopener"
           className="text-xs text-primary hover:underline inline-flex items-center gap-1">
          <ExternalLink className="size-3" /> Portal oficial
        </a>
      </div>

      <div className="bg-base-100 border rounded p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Buscar (nº / proponente / CNPJ)</label>
            <Input value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Ex: 048291/2025 ou CNPJ" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Parlamentar</label>
            <Input value={parlamentar} onChange={(e) => setParlamentar(e.target.value)}
                   placeholder="Ex: Cleitinho" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Órgão</label>
            <Input value={orgao} onChange={(e) => setOrgao(e.target.value)}
                   placeholder="Ex: Ministério do Esporte" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Situação de Contratação</label>
            <select className="w-full border border-base-300 rounded-md p-2 text-sm h-9 bg-base-100 text-base-content"
                    value={sitContratacao} onChange={(e) => setSitContratacao(e.target.value)}>
              <option value="">Todas</option>
              <option value="Normal">Normal</option>
              <option value="Cláusula Suspensiva">Cláusula Suspensiva</option>
              <option value="Liminar Judicial">Liminar Judicial</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Vencimento (fim de vigência)</label>
            <select className="w-full border border-base-300 rounded-md p-2 text-sm h-9 bg-base-100 text-base-content"
                    value={vigencia} onChange={(e) => setVigencia(e.target.value)}>
              <option value="">Todos</option>
              <option value="vence30">Vence em 30 dias</option>
              <option value="vence60">Vence em 60 dias</option>
              <option value="vence90">Vence em 90 dias</option>
              <option value="vence120">Vence em 120 dias</option>
              <option value="prestacao">Prestação de Contas (vencido +90d)</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Situação (multi)</label>
            <MultiSelect
              options={situacaoOptions}
              selected={situacoesSel}
              onChange={setSituacoesSel}
              placeholder="Todas as situações"
              width="w-full"
            />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Fim de vigência (de)</label>
            <Input type="date" value={vigFimDe} onChange={(e) => setVigFimDe(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Fim de vigência (até)</label>
            <Input type="date" value={vigFimAte} onChange={(e) => setVigFimAte(e.target.value)} />
          </div>
          <div className="flex items-end gap-2 flex-wrap">
            <Button onClick={buscar} disabled={loading} className="bg-primary hover:bg-primary/90">
              {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />} Filtrar
            </Button>
            <Button variant="outline" onClick={() => {
              setSearch(""); setSituacoesSel([]); setVigencia("");
              setParlamentar(""); setOrgao(""); setSitContratacao(""); setVigFimDe(""); setVigFimAte("");
              setTimeout(buscar, 100);
            }}>
              <Eraser className="size-4 mr-1" /> Limpar
            </Button>
            <Button variant="outline" onClick={gerarPdf} disabled={baixandoPdf}
                    title="Gera um PDF só com os instrumentos filtrados">
              {baixandoPdf ? <Loader2 className="size-4 animate-spin mr-1" /> : null} 📄 Gerar PDF (filtrado)
            </Button>
          </div>
        </div>
      </div>

      {/* Chip do filtro ativo de vigencia (vindo dos KPIs do dashboard) */}
      {vigencia && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-base-content/60">Filtro ativo:</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-info/15 border border-info px-2.5 py-0.5 text-xs font-medium text-info">
            {VIGENCIA_LABELS[vigencia] ?? vigencia}
            <button
              onClick={() => setVigencia("")}
              className="text-info hover:text-info/80"
              aria-label="Limpar filtro"
            >
              ×
            </button>
          </span>
        </div>
      )}

      <div className="bg-base-100 border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-base-200 text-sm"><strong>{displayItems.length}</strong> propostas</div>
        {loading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-base-200 rounded" />)}
          </div>
        ) : displayItems.length === 0 ? (
          <div className="p-12 text-center text-base-content/60">Nenhuma proposta encontrada.</div>
        ) : (
          <Table className="text-xs table-fixed w-full">
            <TableHeader>
              <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold bg-primary/10">
                <TableHead className="w-[95px]">Código Instr.</TableHead>
                <TableHead className="w-[90px]">Nº Proposta</TableHead>
                <TableHead>Órgão</TableHead>
                <TableHead className="w-[130px]">Parlamentar</TableHead>
                <TableHead className="w-[200px]">Situação</TableHead>
                <TableHead className="w-[150px]">Sit. Contratação</TableHead>
                <TableHead className="w-[80px]">Início Vig.</TableHead>
                <TableHead className="w-[80px]">Fim Vig.</TableHead>
                <TableHead className="w-[55px]">Dias</TableHead>
                <TableHead>Objeto</TableHead>
                <TableHead className="w-[50px] text-center">Ver</TableHead>
                <TableHead className="w-[40px] text-center" title="Gestão Interna">📝</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayItems.map((p, i) => (
                <TableRow key={i} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-primary/10 cursor-pointer"
                          onClick={() => abrirDetalhe(p.numero_proposta)}>
                  <TableCell className="font-mono">{p.codigo_instrumento || "-"}</TableCell>
                  <TableCell className="font-mono">{p.numero_proposta}</TableCell>
                  <TableCell className="truncate" title={p.orgao}>{p.orgao}</TableCell>
                  <TableCell className="truncate" title={p.parlamentar || ""}>{p.parlamentar || "-"}</TableCell>
                  <TableCell className="max-w-[200px]" title={p.situacao}>
                    <span className={`block truncate px-1.5 py-0.5 rounded text-[10px] ${badgeColor(p.situacao)}`}>
                      {p.situacao}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-[150px]">
                    <div className="flex items-center gap-1">
                      <span className="truncate" title={p.situacao_contratacao || ""}>
                        {p.situacao_contratacao || "-"}
                      </span>
                      {((p.situacao_contratacao_detalhe && Object.keys(p.situacao_contratacao_detalhe).filter(k => !k.startsWith("_")).length > 0) || p.clausula_suspensiva_motivo || p.clausula_suspensiva_dt_prevista) && (
                        <button
                          onClick={(e) => { e.stopPropagation(); abrirDetalhe(p.numero_proposta); }}
                          className="shrink-0 inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-primary hover:bg-primary/90 text-white text-[9px] font-medium"
                          title="Ver detalhamento da situação de contratação"
                        >
                          Detalhar
                        </button>
                      )}
                    </div>
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
                            className="inline-flex w-6 h-6 items-center justify-center rounded bg-primary hover:bg-primary/90 text-white">
                      <Eye className="size-3" />
                    </button>
                  </TableCell>
                  <TableCell className="text-center" onClick={(e) => e.stopPropagation()}>
                    <AnotacaoButton
                      fonte="voluntaria"
                      fonteRef={p.numero_proposta}
                      municipioId={Number(municipioId)}
                      numero={p.codigo_instrumento || p.numero_proposta}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Modal detalhe */}
      {(detalhe !== null || loadingDet) && (
        <div className="fixed inset-0 z-50 bg-neutral/50 flex items-start justify-center p-4 overflow-y-auto"
             onClick={() => setDetalhe(null)}>
          <div className="bg-base-100 rounded-lg shadow-2xl w-full max-w-5xl mt-4 mb-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-base-100 px-5 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="text-xl font-light text-base-content">
                Consultar Pré-Instrumento/Instrumento {detalhe?.codigo_instrumento || detalhe?.numero_proposta || ""}
              </h3>
              <button onClick={() => setDetalhe(null)}><X className="size-5 text-base-content/60 hover:text-base-content/70" /></button>
            </div>
            {loadingDet ? (
              <div className="text-center py-16"><Loader2 className="size-8 animate-spin mx-auto text-primary" /></div>
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

                {(detalhe.situacao_contratacao || detalhe.parlamentar || detalhe.situacao_contratacao_detalhe || detalhe.clausula_suspensiva_motivo || detalhe.clausula_suspensiva_dt_prevista) && (
                  <Section title="Contratação e Indicação">
                    <Grid>
                      <Field label="Situação de Contratação Atual" value={detalhe.situacao_contratacao} />
                      <Field label="Parlamentar Responsável" value={detalhe.parlamentar} />
                    </Grid>
                    {detalhe.situacao_contratacao_detalhe && Object.keys(detalhe.situacao_contratacao_detalhe).filter(k => !k.startsWith("_")).length > 0 && (
                      <div className="mt-3 rounded border-l-4 border-warning bg-warning/15 p-3">
                        <div className="text-xs font-semibold text-warning mb-2">
                          Detalhe da Situação de Contratação
                          {detalhe.situacao_contratacao_detalhe._label_botao && (
                            <span className="ml-1 text-warning font-normal">
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
                    {(!detalhe.situacao_contratacao_detalhe || Object.keys(detalhe.situacao_contratacao_detalhe).filter(k => !k.startsWith("_")).length === 0) && (detalhe.clausula_suspensiva_motivo || detalhe.clausula_suspensiva_dt_prevista) && (
                      <div className="mt-3 rounded border-l-4 border-warning bg-warning/15 p-3">
                        <div className="text-xs font-semibold text-warning mb-2">Detalhe da Cláusula Suspensiva</div>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          <Field label="Motivo" value={detalhe.clausula_suspensiva_motivo || "-"} />
                          <Field label="Data Prevista" value={detalhe.clausula_suspensiva_dt_prevista || "-"} />
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
                  <p className="text-sm text-base-content bg-base-200 border rounded p-3">{detalhe.objeto || "-"}</p>
                </Section>

                {detalhe.detalhe && Object.keys(detalhe.detalhe).length > 0 && (
                  <Section title="Justificativa e demais informações">
                    <div className="space-y-2">
                      {Object.entries(detalhe.detalhe)
                        .filter(([k]) => !k.startsWith("_") && !["Modalidade","Situação no SIAFI","Código do Instrumento","Número da Proposta","Número do Processo","Órgão","Objeto do Instrumento"].includes(k))
                        .map(([k, v]) => (
                          <div key={k} className="text-sm border-b border-base-300 pb-1">
                            <span className="text-[11px] font-semibold text-base-content/70">{k}: </span>
                            <span className="text-base-content">{Array.isArray(v) ? v.join(" | ") : v}</span>
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
                          <li key={i} className="flex items-start gap-2 text-base-content/70">
                            <span className="text-info mt-0.5">📄</span>
                            <span className="break-words">{nome}</span>
                          </li>
                        );
                      })}
                    </ul>
                    <a href={PORTAL_BASE} target="_blank" rel="noreferrer noopener"
                       className="inline-flex items-center gap-1 mt-3 text-xs text-white bg-primary hover:bg-primary/90 rounded px-3 py-1.5">
                      <ExternalLink className="size-3" /> Baixar no portal (Acesso Livre)
                    </a>
                    <p className="text-[11px] text-base-content/60 mt-1.5">
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
      <h4 className="text-sm font-semibold text-base-content border-b border-primary pb-1 mb-3">{title}</h4>
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
      <div className="text-[11px] text-base-content/70 mb-0.5">{label}</div>
      <div className="border border-base-300 rounded px-2 py-1.5 bg-base-200 text-sm text-base-content break-words">{v}</div>
    </div>
  );
}
