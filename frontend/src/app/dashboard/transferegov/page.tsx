"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Search, Eye, X, Loader2, Eraser, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import RelacionadosButton from "@/components/RelacionadosModal";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatCurrency } from "@/lib/utils";

interface Plano {
  id: number;
  codigo: string;
  programa_codigo: string;
  programa_id: number;
  situacao_plano_acao: string;
  situacao_plano_trabalho: string;
  beneficiario_nome: string;
  beneficiario_cnpj: string;
  uf: string;
  politicas_publicas: string;
  emenda_codigo: string;
  valor_custeio: number;
  valor_investimento: number;
  valor_total: number;
  objeto_descricao?: string;
  motivo_impedimento?: string;
}

interface BuscarResp {
  items: Plano[];
  total: number;
  municipio: { id: number; nome: string; uf: string };
  cache_age_seconds: number;
}

interface DetalhePlano {
  plano?: {
    id: number;
    codigo?: string;
    codigoSufixo?: number;
    ano?: number;
    modalidade?: string;
    situacao?: string;
    motivoImpedimento?: string;
    programaF?: string;
    valorCusteio?: number;
    valorInvestimento?: number;
    valorTotal?: number;
    objeto?: string;
    objetoDetalhe?: string;
    emailCamara?: string;
    beneficiario?: {
      cnpj?: string; nome?: string; uf?: string; ibge?: number;
      idh?: number; enteId?: number; email?: string;
    };
    emendaParlamentar?: {
      codigoEmendaFormatado?: string;
      nomeParlamentar?: string;
      codigoParlamentar?: string;
      ano?: number;
      valorCusteio?: number;
      valorInvestimento?: number;
    };
    listaPO?: unknown[];
    listaAPP?: unknown[];
  };
  resumo?: {
    nrMesesExecucao?: number;
    valorTotalCusteio?: number;
    valorTotalInvestimento?: number;
    valorTotalExecutado?: number;
    valorTotalPendente?: number;
    valorTotalCusteioExecutado?: number;
    valorTotalInvestimentoExecutado?: number;
  };
}

const SITUACOES_PA = ["TODAS", "CIENTE", "EM_ANALISE", "IMPEDIDO", "EM_ELABORACAO", "CONCLUIDA"];

export default function TransfereGovPage() {
  const sp = useSearchParams();
  const municipioId = sp.get("municipio_id");

  const [items, setItems] = useState<Plano[]>([]);
  const [loading, setLoading] = useState(false);
  const [cacheAge, setCacheAge] = useState(0);
  const [total, setTotal] = useState(0);

  const [situacao, setSituacao] = useState("TODAS");
  const [programa, setPrograma] = useState("");
  const [parlamentar, setParlamentar] = useState("");
  const [emenda, setEmenda] = useState("");
  const [objeto, setObjeto] = useState("");

  const [detalhe, setDetalhe] = useState<DetalhePlano | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);
  const [tab, setTab] = useState<"basicos" | "orcamento" | "execucao">("basicos");

  const buscar = useCallback(async (refresh = false) => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string | boolean> = { municipio_id: municipioId };
      if (situacao !== "TODAS") params.situacao = situacao;
      if (programa.trim()) params.programa = programa.trim();
      if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
      if (emenda.trim()) params.emenda = emenda.trim();
      if (objeto.trim()) params.objeto = objeto.trim();
      if (refresh) params.refresh = true;
      const r = await api.get<BuscarResp>("/transferegov/buscar", { params });
      setItems(r.data.items);
      setTotal(r.data.total);
      setCacheAge(r.data.cache_age_seconds);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [municipioId, situacao, programa, parlamentar, emenda, objeto]);

  useEffect(() => {
    if (municipioId) buscar(false);
  }, [municipioId]); // eslint-disable-line react-hooks/exhaustive-deps

  const limpar = () => {
    setSituacao("TODAS"); setPrograma(""); setParlamentar(""); setEmenda(""); setObjeto("");
    setItems([]); setTotal(0);
  };

  const abrirDetalhe = async (id: number) => {
    setDetalhe(null);
    setTab("basicos");
    setLoadingDetalhe(true);
    try {
      const r = await api.get<DetalhePlano>(`/transferegov/plano-acao/${id}`);
      setDetalhe(r.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingDetalhe(false);
    }
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">
      Selecione um municipio.
    </div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Plano de Acao - TransfereGov</h1>
          <p className="text-sm text-slate-500">Transferencia Especial Federal (Pix Parlamentar)</p>
        </div>
        <div className="text-xs text-slate-500">
          {cacheAge > 0 && `Cache: ${Math.floor(cacheAge / 60)}min`}
        </div>
      </div>

      {/* Filtros */}
      <div className="bg-white border rounded p-4">
        <h2 className="text-sm font-semibold text-slate-700 mb-3">Pesquisa - Escolha um ou Mais Criterios</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Situacao do Plano de Acao</label>
            <Select value={situacao} onValueChange={(v) => setSituacao(v ?? "TODAS")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {SITUACOES_PA.map(s => <SelectItem key={s} value={s}>{s.replace("_", " ")}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Programa (codigo)</label>
            <Input value={programa} onChange={(e) => setPrograma(e.target.value)} placeholder="Ex: 09032022" />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Parlamentar (nome)</label>
            <Input value={parlamentar} onChange={(e) => setParlamentar(e.target.value)} placeholder="Ex: LUIS TIBE" />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Emenda Parlamentar (codigo)</label>
            <Input value={emenda} onChange={(e) => setEmenda(e.target.value)} placeholder="Ex: 202241760007" />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Objeto/Politica Publica</label>
            <Input value={objeto} onChange={(e) => setObjeto(e.target.value)} placeholder="Ex: Urbanismo, Saude" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-3">
          <Button variant="outline" onClick={limpar}><Eraser className="size-4 mr-1" /> Limpar</Button>
          <Button variant="outline" onClick={() => buscar(true)} disabled={loading} title="Refresh cache do TransfereGov">
            <RefreshCw className="size-4 mr-1" /> Atualizar
          </Button>
          <Button onClick={() => buscar(false)} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
            {loading ? <Loader2 className="size-4 mr-1 animate-spin" /> : <Search className="size-4 mr-1" />}
            Filtrar
          </Button>
        </div>
      </div>

      {/* Grid */}
      <div className="bg-white border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm">
          Lista de Planos de Acao - <strong>{total}</strong> registros
        </div>
        {loading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-gray-100 rounded" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            Nenhum plano encontrado. Use os filtros acima e clique em <strong>Filtrar</strong>.
          </div>
        ) : (
          <Table className="text-xs table-fixed w-full">
            <TableHeader>
              <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold bg-blue-50">
                <TableHead className="w-[120px]">Codigo</TableHead>
                <TableHead className="w-[180px]">Emenda Parlamentar</TableHead>
                <TableHead className="w-[40px]">UF</TableHead>
                <TableHead>Beneficiario</TableHead>
                <TableHead className="w-[110px] text-right">Valor</TableHead>
                <TableHead className="w-[100px]">Sit. P. Acao</TableHead>
                <TableHead className="w-[160px]">Sit. P. Trabalho</TableHead>
                <TableHead className="w-[60px] text-center">Acoes</TableHead>
                <TableHead className="w-[40px] text-center">Rel.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((p) => (
                <TableRow key={p.id} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-blue-50">
                  <TableCell className="font-mono">{p.codigo}</TableCell>
                  <TableCell className="truncate" title={p.emenda_codigo}>{p.emenda_codigo}</TableCell>
                  <TableCell className="text-center">{p.uf}</TableCell>
                  <TableCell className="truncate" title={`${p.beneficiario_cnpj} - ${p.beneficiario_nome}`}>
                    {p.beneficiario_cnpj} - {p.beneficiario_nome}
                  </TableCell>
                  <TableCell className="text-right font-mono text-blue-700">{formatCurrency(p.valor_total)}</TableCell>
                  <TableCell>
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${
                      p.situacao_plano_acao === "CIENTE" ? "bg-green-100 text-green-800" :
                      p.situacao_plano_acao === "IMPEDIDO" ? "bg-red-100 text-red-800" :
                      "bg-gray-100 text-gray-800"
                    }`}>{p.situacao_plano_acao}</span>
                  </TableCell>
                  <TableCell className="text-[10px] truncate" title={p.situacao_plano_trabalho}>
                    {p.situacao_plano_trabalho}
                  </TableCell>
                  <TableCell className="text-center">
                    <button onClick={() => abrirDetalhe(p.id)}
                            className="inline-flex w-6 h-6 items-center justify-center rounded bg-blue-500 hover:bg-blue-600 text-white" title="Detalhar">
                      <Eye className="size-3" />
                    </button>
                  </TableCell>
                  <TableCell className="text-center">
                    <RelacionadosButton params={{
                      municipio_id: municipioId, fonte: "plano-acao",
                      proposta: p.codigo, parlamentar: p.emenda_codigo,
                      objeto: p.politicas_publicas,
                    }} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Modal Detalhe - replica layout TransfereGov oficial */}
      {(detalhe !== null || loadingDetalhe) && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto"
             onClick={() => setDetalhe(null)}>
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-6xl mt-4 mb-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-white px-5 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="text-xl font-light text-slate-900">Dados do Plano de Ação</h3>
              <button onClick={() => setDetalhe(null)}><X className="size-5 text-gray-500 hover:text-gray-700" /></button>
            </div>
            {loadingDetalhe ? (
              <div className="text-center py-16"><Loader2 className="size-8 animate-spin mx-auto text-blue-600" /></div>
            ) : detalhe?.plano && (
              <>
                {/* Header cinza */}
                <div className="bg-slate-100 px-5 py-3 grid grid-cols-3 gap-4 text-sm border-b">
                  <div>
                    <span className="font-semibold">Plano de Ação:</span>{" "}
                    {detalhe.plano.programaF}-{String(detalhe.plano.codigoSufixo || "").padStart(6,"0")} / {detalhe.plano.ano}
                  </div>
                  <div><span className="font-semibold">Programa:</span> {detalhe.plano.programaF}</div>
                  <div><span className="font-semibold">Situação:</span> {detalhe.plano.situacao}</div>
                  <div className="col-span-2">
                    <span className="font-semibold">Beneficiário:</span> {detalhe.plano.beneficiario?.cnpj} - {detalhe.plano.beneficiario?.nome} ({detalhe.plano.beneficiario?.uf})
                  </div>
                  <div><span className="font-semibold">Emenda Parlamentar:</span> {detalhe.plano.emendaParlamentar?.codigoEmendaFormatado}</div>
                </div>

                {/* Tabs */}
                <div className="border-b flex gap-1 px-5">
                  {[
                    {k:"basicos", l:"Dados Básicos"},
                    {k:"orcamento", l:"Dados Orçamentários"},
                    {k:"execucao", l:"Execução / Relatório"},
                  ].map((t) => (
                    <button
                      key={t.k}
                      onClick={() => setTab(t.k as "basicos"|"orcamento"|"execucao")}
                      className={`px-4 py-2.5 text-sm border-b-2 ${tab === t.k ? "border-blue-600 text-blue-700 font-semibold" : "border-transparent text-slate-600 hover:text-slate-900"}`}
                    >
                      {t.l}
                    </button>
                  ))}
                </div>

                <div className="p-5 space-y-6 max-h-[70vh] overflow-y-auto">
                  {tab === "basicos" && (
                    <>
                      <Section title="Dados do Beneficiário">
                        <Grid>
                          <Field label="Beneficiário (Obrigatório)" value={`${detalhe.plano.beneficiario?.cnpj} - ${detalhe.plano.beneficiario?.nome}`} />
                          <Field label="UF (Obrigatório)" value={detalhe.plano.beneficiario?.uf} />
                          <Field label="Código IBGE" value={detalhe.plano.beneficiario?.ibge} />
                          <Field label="IDH" value={detalhe.plano.beneficiario?.idh} />
                          <Field label="E-mail Câmara" value={detalhe.plano.emailCamara || "-"} />
                        </Grid>
                      </Section>
                      <Section title="Dados da Emenda Parlamentar">
                        <Grid>
                          <Field label="Emenda Parlamentar (Obrigatório)" value={detalhe.plano.emendaParlamentar?.codigoEmendaFormatado} />
                          <Field label="Parlamentar" value={detalhe.plano.emendaParlamentar?.nomeParlamentar} />
                          <Field label="Código Parlamentar" value={detalhe.plano.emendaParlamentar?.codigoParlamentar} />
                          <Field label="Ano" value={detalhe.plano.emendaParlamentar?.ano} />
                          <Field label="Valor de Custeio (Obrigatório)" value={formatCurrency(detalhe.plano.valorCusteio)} />
                          <Field label="Valor de Investimento (Obrigatório)" value={formatCurrency(detalhe.plano.valorInvestimento)} />
                        </Grid>
                      </Section>
                      <Section title="Dados Complementares do Plano">
                        <Grid cols={2}>
                          <Field label="Modalidade" value={detalhe.plano.modalidade} />
                          <Field label="Objeto" value={detalhe.plano.objeto || detalhe.plano.objetoDetalhe || "-"} />
                          <Field label="Motivo Impedimento" value={detalhe.plano.motivoImpedimento || "-"} />
                          <Field label="Anexos" value={(detalhe.plano.listaAPP?.length || 0).toString()} />
                        </Grid>
                      </Section>
                    </>
                  )}
                  {tab === "orcamento" && (
                    <Section title="Orçamento do Plano">
                      <Grid>
                        <Field label="Valor de Custeio" value={formatCurrency(detalhe.plano.valorCusteio)} />
                        <Field label="Valor de Investimento" value={formatCurrency(detalhe.plano.valorInvestimento)} />
                        <Field label="Valor Total" value={formatCurrency(detalhe.plano.valorTotal)} />
                      </Grid>
                      {detalhe.plano.emendaParlamentar && (
                        <div className="mt-4">
                          <h5 className="text-xs font-semibold text-slate-700 mb-2">Da Emenda Parlamentar</h5>
                          <Grid>
                            <Field label="Custeio na Emenda" value={formatCurrency(detalhe.plano.emendaParlamentar.valorCusteio)} />
                            <Field label="Investimento na Emenda" value={formatCurrency(detalhe.plano.emendaParlamentar.valorInvestimento)} />
                          </Grid>
                        </div>
                      )}
                    </Section>
                  )}
                  {tab === "execucao" && (
                    detalhe.resumo ? (
                      <Section title="Relatório de Gestão">
                        <Grid>
                          <Field label="Meses em Execução" value={detalhe.resumo.nrMesesExecucao} />
                          <Field label="Custeio Previsto" value={formatCurrency(detalhe.resumo.valorTotalCusteio)} />
                          <Field label="Investimento Previsto" value={formatCurrency(detalhe.resumo.valorTotalInvestimento)} />
                          <Field label="Custeio Executado" value={formatCurrency(detalhe.resumo.valorTotalCusteioExecutado)} />
                          <Field label="Investimento Executado" value={formatCurrency(detalhe.resumo.valorTotalInvestimentoExecutado)} />
                          <Field label="Total Executado" value={formatCurrency(detalhe.resumo.valorTotalExecutado)} highlight="green" />
                          <Field label="Total Pendente" value={formatCurrency(detalhe.resumo.valorTotalPendente)} highlight="amber" />
                        </Grid>
                      </Section>
                    ) : (
                      <p className="text-sm text-slate-500 italic">Sem relatório de gestão registrado para este plano.</p>
                    )
                  )}
                </div>
              </>
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
      <h4 className="text-sm font-semibold text-slate-800 border-b border-blue-600 pb-1 mb-3">
        {title}
      </h4>
      <div>{children}</div>
    </div>
  );
}

function Grid({ children, cols = 4 }: { children: React.ReactNode; cols?: 2 | 3 | 4 }) {
  const cls = cols === 2 ? "md:grid-cols-2" : cols === 3 ? "md:grid-cols-3" : "md:grid-cols-4";
  return <div className={`grid grid-cols-1 ${cls} gap-3`}>{children}</div>;
}

function Field({
  label, value, highlight,
}: {
  label: string;
  value?: string | number | null;
  highlight?: "green" | "amber" | "red";
}) {
  const valStr = value === null || value === undefined || value === "" ? "-" : String(value);
  const color =
    highlight === "green" ? "text-green-700" :
    highlight === "amber" ? "text-amber-700" :
    highlight === "red" ? "text-red-700" : "text-slate-900";
  return (
    <div>
      <div className="text-[11px] text-slate-600 mb-0.5">{label}</div>
      <div className={`border border-slate-300 rounded px-2 py-1.5 bg-slate-50 text-sm ${color}`}>
        {valStr}
      </div>
    </div>
  );
}
