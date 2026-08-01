"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Search, Eraser, Loader2, ExternalLink, Eye, X } from "lucide-react";
import api from "@/lib/api";
import { MultiSelect } from "@/components/ui/multi-select";
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
  processo_execucao_qtd?: number | null;
  historico_comunicacoes?: Record<string, string>[];
  documentos_quadro_resumo?: Record<string, string>[];
  historico_atualizado_em?: string | null;
}

interface Resp { items: Proposta[]; total: number; atualizado_em?: string; }

function diasBadge(d?: number | null): { txt: string; cls: string } {
  if (d === null || d === undefined) return { txt: "-", cls: "bg-base-200 text-base-content/60" };
  if (d < 0) return { txt: `${Math.abs(d)}d`, cls: "bg-error/15 text-error" };
  if (d <= 60) return { txt: `${d}d`, cls: "bg-warning/15 text-warning" };
  if (d <= 180) return { txt: `${d}d`, cls: "bg-warning/15 text-warning" };
  return { txt: `${d}d`, cls: "bg-success/15 text-success" };
}

interface OpsObs {
  valor_total_repasse?: number | null;
  valor_desembolsado?: number | null;
  valor_a_desembolsar?: number | null;
  data_ultimo_desembolso?: string | null;
  obs?: Array<{
    numero_interno?: string; numero_ns?: string; numero_op?: string; numero_ob?: string;
    ug_emitente?: string; gestao_emitente?: string; valor?: number | null;
    valor_acerto?: number | null; situacao?: string; data_emissao_ob?: string;
  }>;
}
interface ObraSubmeta {
  numero?: string; descricao?: string; situacao?: string;
  regime_execucao?: string; valor?: number | null; valor_realizado?: number | null;
}
interface ObraArt {
  tipo?: string; numero?: string; dt_emissao?: string; responsavel_tecnico?: string;
}
interface ObraLote {
  tipo?: string; numero?: string; id_contrato?: number | null;
  apto_iniciar?: boolean; atrasado?: boolean | null; paralisado?: boolean | null;
  dias_sem_medicao?: number | null;
  submetas?: ObraSubmeta[];
  contrato?: {
    numero?: string; cnpj?: string; empresa?: string; objeto?: string;
    valor?: number | null; dt_assinatura?: string; dt_inicio_vigencia?: string; dt_fim_vigencia?: string;
  } | null;
  arts?: ObraArt[];
}
interface Obras {
  situacao_paralisacao?: string | null;
  valor_total_submetas?: number | null;
  valor_total_realizado?: number | null;
  objeto?: string | null;
  lotes?: ObraLote[];
}

function moeda(v?: number | null): string {
  if (v === null || v === undefined) return "-";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

interface Detalhe extends Proposta {
  detalhe?: Record<string, string | string[]>;
  ops_obs?: OpsObs | null;
  obras?: Obras | null;
}

const PORTAL_BASE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest";

// Estava incompleto (faltavam vence30 e vence90), e o chip do filtro vindo dos
// KPIs mostrava o codigo cru ("vence30") em vez do rotulo.
const VIGENCIA_LABELS: Record<string, string> = {
  vence30: "Vence em 30 dias",
  vence60: "Vence em 60 dias",
  vence90: "Vence em 90 dias",
  vence120: "Vence em 120 dias",
  prestacao: "Prestação de contas (vencido +90d)",
};

/** Ordem que o gestor espera ver no dropdown (do mais curto ao mais longo). */
const VIGENCIA_OPCOES = ["vence30", "vence60", "vence90", "vence120", "prestacao"];

/** Valores da coluna `situacao_contratacao` no TransfereGov. */
const SIT_CONTRATACAO_OPCOES = ["Normal", "Cláusula Suspensiva", "Liminar Judicial"];

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
  const [vigenciaSel, setVigenciaSel] = useState<string[]>(vigenciaParam ? [vigenciaParam] : []);
  const [parlamentar, setParlamentar] = useState("");
  const [orgao, setOrgao] = useState("");
  const [sitContratacaoSel, setSitContratacaoSel] = useState<string[]>([]);
  const [vigFimDe, setVigFimDe] = useState("");
  const [vigFimAte, setVigFimAte] = useState("");
  const [baixandoPdf, setBaixandoPdf] = useState(false);

  const [detalhe, setDetalhe] = useState<Detalhe | null>(null);
  // Aba ativa do modal de detalhe (evita rolagem gigante com 50+ eventos)
  const [aba, setAba] = useState<"dados" | "opsobs" | "obras" | "historico" | "docs">("dados");
  const [loadingDet, setLoadingDet] = useState(false);

  const buildParams = useCallback((): Record<string, string | string[]> => {
    // string[] p/ os filtros multi: o axios serializa como chave repetida
    // (?vigencia=a&vigencia=b), que e o formato que o FastAPI le em list[str].
    const params: Record<string, string | string[]> = { municipio_id: municipioId || "", categoria };
    if (search.trim()) params.search = search.trim();
    if (vigenciaSel.length) params.vigencia = vigenciaSel;
    if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
    if (orgao.trim()) params.orgao = orgao.trim();
    if (sitContratacaoSel.length) params.situacao_contratacao = sitContratacaoSel;
    if (vigFimDe) params.vig_fim_de = vigFimDe;
    if (vigFimAte) params.vig_fim_ate = vigFimAte;
    return params;
  }, [municipioId, categoria, search, vigenciaSel, parlamentar, orgao, sitContratacaoSel, vigFimDe, vigFimAte]);

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
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setVigenciaSel(vigenciaParam ? [vigenciaParam] : []); }, [vigenciaParam]);

  // Busca ao montar e sempre que municipio/categoria/vigencia mudarem
  useEffect(() => { if (municipioId) buscar(); }, [municipioId, vigenciaSel, categoria]); // eslint-disable-line react-hooks/exhaustive-deps

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
    setDetalhe(null); setLoadingDet(true); setAba("dados");
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
            <label className="text-xs text-base-content/70 mb-1 block">
              Situação de Contratação <span className="text-base-content/40">(uma, algumas ou todas)</span>
            </label>
            <MultiSelect
              opcoes={SIT_CONTRATACAO_OPCOES}
              valor={sitContratacaoSel}
              onChange={setSitContratacaoSel}
              placeholder="Todas"
              rotuloTodos="Todas"
              ariaLabel="Situação de contratação"
            />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">
              Vencimento (fim de vigência) <span className="text-base-content/40">(um ou vários)</span>
            </label>
            <MultiSelect
              opcoes={VIGENCIA_OPCOES}
              valor={vigenciaSel}
              onChange={setVigenciaSel}
              rotulos={VIGENCIA_LABELS}
              placeholder="Todos"
              rotuloTodos="Todos"
              ariaLabel="Vencimento"
            />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Situação (multi)</label>
            <MultiSelect
              opcoes={situacaoOptions}
              valor={situacoesSel}
              onChange={setSituacoesSel}
              placeholder="Todas as situações"
              rotuloTodos="Todas"
              ariaLabel="Situação da proposta"
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
              setSearch(""); setSituacoesSel([]); setVigenciaSel([]);
              setParlamentar(""); setOrgao(""); setSitContratacaoSel([]); setVigFimDe(""); setVigFimAte("");
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

      {/* Chips dos filtros de vencimento ativos (podem vir dos KPIs do
          dashboard ou do proprio dropdown, e agora podem ser varios). */}
      {vigenciaSel.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-base-content/60">Filtro ativo:</span>
          {vigenciaSel.map((v) => (
            <span key={v} className="inline-flex items-center gap-1.5 rounded-full bg-info/15 border border-info px-2.5 py-0.5 text-xs font-medium text-info">
              {VIGENCIA_LABELS[v] ?? v}
              <button
                onClick={() => setVigenciaSel((atual) => atual.filter((x) => x !== v))}
                className="text-info hover:text-info/80"
                aria-label={`Remover filtro ${VIGENCIA_LABELS[v] ?? v}`}
              >
                ×
              </button>
            </span>
          ))}
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
                      {p.processo_execucao_qtd === 0 && (p.situacao_contratacao || "").toLowerCase().includes("normal") && (
                        <button
                          onClick={(e) => { e.stopPropagation(); abrirDetalhe(p.numero_proposta); }}
                          className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded bg-error/15 text-error text-[9px] font-semibold"
                          title="Contratação Normal sem processo de execução/licitação registrado (Execução Convenente)"
                        >
                          ⚠ sem processo
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
            ) : detalhe && (() => {
              const nHist = (detalhe.historico_comunicacoes || []).length;
              const nDocs = (detalhe.documentos_quadro_resumo || []).length;
              const nLotes = (detalhe.obras?.lotes || []).length;
              const temOpsObs = !!(detalhe.ops_obs && (detalhe.ops_obs.valor_total_repasse != null || (detalhe.ops_obs.obs || []).length));
              const abas: [typeof aba, string, boolean][] = [
                ["dados", "Dados", true],
                ["opsobs", "OPs/OBs", temOpsObs],
                ["obras", `Obras${nLotes ? ` (${nLotes})` : ""}`, nLotes > 0],
                ["historico", `Histórico${nHist ? ` (${nHist})` : ""}`, nHist > 0],
                ["docs", `Documentos${nDocs ? ` (${nDocs})` : ""}`, nDocs > 0],
              ];
              const ativa = abas.find((a) => a[0] === aba)?.[2] ? aba : "dados";
              return (
              <div className="max-h-[75vh] overflow-y-auto">
                <div className="flex gap-1 px-5 border-b border-base-300 sticky top-0 bg-base-100 z-10">
                  {abas.map(([k, label, on]) => (
                    <button key={k} onClick={() => on && setAba(k)} disabled={!on}
                      className={`px-3 py-2 text-sm font-medium -mb-px border-b-2 transition-colors ${
                        ativa === k
                          ? "border-primary text-primary"
                          : on
                            ? "border-transparent text-base-content/60 hover:text-base-content"
                            : "border-transparent text-base-content/25 cursor-not-allowed"}`}>
                      {label}
                    </button>
                  ))}
                </div>
                <div className="p-5 space-y-5">
                {ativa === "dados" && (<>
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
                    {/* Processo de Execução (Licitações) — só p/ contratação Normal.
                        0 = convênio Normal sem processo iniciado (flag, igual à cláusula). */}
                    {detalhe.processo_execucao_qtd != null && (detalhe.situacao_contratacao || "").toLowerCase().includes("normal") && (
                      detalhe.processo_execucao_qtd === 0 ? (
                        <div className="mt-3 rounded border-l-4 border-error bg-error/15 p-3">
                          <div className="text-xs font-semibold text-error">⚠ Processo de Execução: NENHUM registro</div>
                          <div className="text-xs text-base-content/70 mt-1">
                            Contratação Normal, mas sem licitação/processo de execução registrado no TransfereGov
                            (Execução Convenente → Processo de Execução).
                          </div>
                        </div>
                      ) : (
                        <div className="mt-3 rounded border-l-4 border-success bg-success/15 p-3">
                          <div className="text-xs font-semibold text-success">
                            Processo de Execução: {detalhe.processo_execucao_qtd} registro(s)
                          </div>
                        </div>
                      )
                    )}
                  </Section>
                )}
                </>)}

                {/* OPs/OBs — Execução Concedente → Listagem de Repasses */}
                {ativa === "opsobs" && detalhe.ops_obs && (
                  <Section title="OPs/OBs — Repasses e Desembolsos">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                      <div className="rounded border border-base-300 bg-base-100 p-3">
                        <div className="text-[11px] text-base-content/50">Valor Total de Repasse</div>
                        <div className="font-semibold text-base-content">{moeda(detalhe.ops_obs.valor_total_repasse)}</div>
                      </div>
                      <div className="rounded border border-base-300 bg-success/5 p-3">
                        <div className="text-[11px] text-base-content/50">Valor Desembolsado</div>
                        <div className="font-semibold text-success">{moeda(detalhe.ops_obs.valor_desembolsado)}</div>
                      </div>
                      <div className="rounded border border-base-300 bg-warning/5 p-3">
                        <div className="text-[11px] text-base-content/50">Valor a Desembolsar</div>
                        <div className="font-semibold text-warning">{moeda(detalhe.ops_obs.valor_a_desembolsar)}</div>
                      </div>
                      <div className="rounded border border-base-300 bg-base-100 p-3">
                        <div className="text-[11px] text-base-content/50">Último Desembolso</div>
                        <div className="font-semibold text-base-content">{detalhe.ops_obs.data_ultimo_desembolso || "-"}</div>
                      </div>
                    </div>
                    {(detalhe.ops_obs.obs || []).length > 0 && (
                      <div className="overflow-x-auto">
                        <div className="text-xs font-semibold text-base-content/60 mb-1">Ordens Bancárias (GERCOMP)</div>
                        <table className="w-full text-[11px] border-collapse">
                          <thead>
                            <tr className="text-left text-base-content/60">
                              <th className="py-1 pr-3 font-medium">Nº NS</th>
                              <th className="py-1 pr-3 font-medium">Nº OP</th>
                              <th className="py-1 pr-3 font-medium">Nº OB</th>
                              <th className="py-1 pr-3 font-medium">Valor</th>
                              <th className="py-1 pr-3 font-medium">Situação</th>
                              <th className="py-1 pr-3 font-medium">Emissão OB</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(detalhe.ops_obs.obs || []).map((o, i) => (
                              <tr key={i} className="border-t border-base-200">
                                <td className="py-1 pr-3 font-mono">{o.numero_ns || "-"}</td>
                                <td className="py-1 pr-3 font-mono">{o.numero_op || "-"}</td>
                                <td className="py-1 pr-3 font-mono">{o.numero_ob || "-"}</td>
                                <td className="py-1 pr-3">{moeda(o.valor)}</td>
                                <td className="py-1 pr-3">{o.situacao || "-"}</td>
                                <td className="py-1 pr-3 whitespace-nowrap">{o.data_emissao_ob || "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </Section>
                )}

                {/* OBRAS — Acompanhamento de Obras (medição) */}
                {ativa === "obras" && detalhe.obras && (detalhe.obras.lotes || []).length > 0 && (
                  <Section title="Acompanhamento de Obras">
                    <div className="flex flex-wrap gap-4 mb-3 text-xs">
                      <span><span className="text-base-content/50">Valor total das submetas: </span>
                        <span className="font-semibold">{moeda(detalhe.obras.valor_total_submetas)}</span></span>
                      {detalhe.obras.situacao_paralisacao && (
                        <span><span className="text-base-content/50">Paralisação: </span>
                          <span className="font-medium">{detalhe.obras.situacao_paralisacao}</span></span>
                      )}
                    </div>
                    <div className="space-y-4">
                      {(detalhe.obras.lotes || []).map((lote, li) => (
                        <div key={li} className="rounded border border-base-300 bg-base-100 p-3">
                          <div className="flex flex-wrap items-center gap-2 mb-2">
                            <span className="rounded bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                              {lote.tipo === "C" ? "CTEF" : "Lote"} {lote.numero}
                            </span>
                            {lote.dias_sem_medicao != null && (
                              <span className="text-[11px] text-base-content/50">{lote.dias_sem_medicao} dias sem medição</span>
                            )}
                            {lote.paralisado && <span className="rounded-full bg-error/15 px-2 py-0.5 text-[11px] text-error">Paralisado</span>}
                          </div>
                          <div className="overflow-x-auto">
                            <table className="w-full text-[11px] border-collapse">
                              <thead>
                                <tr className="text-left text-base-content/60">
                                  <th className="py-1 pr-3 font-medium">Submeta</th>
                                  <th className="py-1 pr-3 font-medium">Descrição</th>
                                  <th className="py-1 pr-3 font-medium">Valor</th>
                                  <th className="py-1 pr-3 font-medium">Situação</th>
                                  <th className="py-1 pr-3 font-medium">Regime</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(lote.submetas || []).map((s, si) => (
                                  <tr key={si} className="border-t border-base-200 align-top">
                                    <td className="py-1 pr-3 font-mono">{s.numero || "-"}</td>
                                    <td className="py-1 pr-3">{s.descricao || "-"}</td>
                                    <td className="py-1 pr-3 whitespace-nowrap">{moeda(s.valor)}</td>
                                    <td className="py-1 pr-3">{s.situacao || "-"}</td>
                                    <td className="py-1 pr-3">{s.regime_execucao || "-"}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                          {lote.contrato && (
                            <div className="mt-2 rounded bg-base-200/50 p-2 text-[11px]">
                              <div className="font-semibold text-base-content/70 mb-1">Contrato {lote.contrato.numero} — Detalhar</div>
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4 gap-y-0.5">
                                <span><span className="text-base-content/50">Empresa: </span>{lote.contrato.empresa || "-"}</span>
                                <span><span className="text-base-content/50">CNPJ: </span>{lote.contrato.cnpj || "-"}</span>
                                <span><span className="text-base-content/50">Valor: </span>{moeda(lote.contrato.valor)}</span>
                                <span><span className="text-base-content/50">Vigência: </span>{lote.contrato.dt_inicio_vigencia || "?"} a {lote.contrato.dt_fim_vigencia || "?"}</span>
                              </div>
                              {lote.contrato.objeto && (
                                <div className="mt-1"><span className="text-base-content/50">Objeto: </span>{lote.contrato.objeto}</div>
                              )}
                              <div className="mt-2 font-semibold text-base-content/70">ART/RRT</div>
                              {(lote.arts || []).length > 0 ? (
                                <table className="w-full text-[11px] border-collapse mt-1">
                                  <thead><tr className="text-left text-base-content/50">
                                    <th className="py-0.5 pr-3 font-medium">Tipo</th>
                                    <th className="py-0.5 pr-3 font-medium">ART/RRT</th>
                                    <th className="py-0.5 pr-3 font-medium">Emissão</th>
                                    <th className="py-0.5 pr-3 font-medium">Responsável Técnico</th>
                                  </tr></thead>
                                  <tbody>
                                    {(lote.arts || []).map((a, ai) => (
                                      <tr key={ai} className="border-t border-base-200">
                                        <td className="py-0.5 pr-3">{a.tipo || "-"}</td>
                                        <td className="py-0.5 pr-3 font-mono">{a.numero || "-"}</td>
                                        <td className="py-0.5 pr-3">{a.dt_emissao || "-"}</td>
                                        <td className="py-0.5 pr-3">{a.responsavel_tecnico || "-"}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              ) : (
                                <div className="text-base-content/50 italic">Nenhum item incluído</div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </Section>
                )}

                {/* Histórico de Comunicações (TransfereGov mandatárias) — SITUAÇÃO e
                    CONSIDERAÇÕES em destaque: é o andamento real da análise. */}
                {ativa === "historico" && detalhe.historico_comunicacoes && detalhe.historico_comunicacoes.length > 0 && (
                  <Section title={`Histórico de Comunicações (${detalhe.historico_comunicacoes.length})`}>
                    <div className="space-y-2 p-2">
                      {detalhe.historico_comunicacoes.map((h, i) => {
                        const pick = (re: RegExp) => {
                          const k = Object.keys(h).find((kk) => re.test(kk));
                          return k ? (h[k] || "") : "";
                        };
                        const data = pick(/data|hora/i);
                        const evento = pick(/evento/i);
                        const resp = pick(/respons/i);
                        const sit = pick(/situa/i);
                        const cons = pick(/considera/i);
                        return (
                          <div key={i} className="rounded border border-base-300 bg-base-100 p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-[11px] text-base-content/50">{data}</span>
                              <span className="font-medium text-base-content">{evento}</span>
                              {sit && (
                                <span className="ml-auto rounded-full bg-info/15 px-2 py-0.5 text-[11px] font-semibold text-info">
                                  {sit}
                                </span>
                              )}
                            </div>
                            {resp && <div className="mt-0.5 text-[11px] text-base-content/50">{resp}</div>}
                            {cons && (
                              <div className="mt-2 rounded border-l-4 border-warning bg-warning/10 p-2 text-xs text-base-content/80">
                                <span className="font-semibold text-warning">Considerações: </span>
                                {cons}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </Section>
                )}

                {/* Documentos do Quadro Resumo (Termos de Notificação etc.) */}
                {ativa === "docs" && detalhe.documentos_quadro_resumo && detalhe.documentos_quadro_resumo.length > 0 && (
                  <Section title={`Documentos / Termos de Notificação (${detalhe.documentos_quadro_resumo.length})`}>
                    <div className="space-y-1 p-2">
                      {detalhe.documentos_quadro_resumo.map((d, i) => {
                        const vals = Object.entries(d).filter(([, v]) => v && !/^\s*$/.test(v));
                        return (
                          <div key={i} className="rounded border border-base-300 bg-base-100 px-3 py-2 text-xs">
                            {vals.map(([k, v]) => (
                              <span key={k} className="mr-3 inline-block">
                                <span className="text-base-content/50">{k}: </span>
                                <span className="text-base-content/80">{v}</span>
                              </span>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  </Section>
                )}

                {ativa === "dados" && (<>
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
                </>)}
                </div>
              </div>
              );
            })()}
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
