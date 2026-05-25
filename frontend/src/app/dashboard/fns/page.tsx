"use client";

import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency } from "@/lib/utils";
import { Search, Loader2, Eraser, Printer, Eye, X } from "lucide-react";
import RelacionadosButton from "@/components/RelacionadosModal";

interface Item {
  tipo_proposta?: string;
  tipo_recurso?: string;
  nu_processo?: string;
  valor_proposta?: number;
  valor_pago?: number;
  valor_pagar?: number;
  constituido_processo?: boolean;
  parlamentares?: Array<{ nome?: string; partido?: string }>;
  pagamentos_count?: number;
}

interface Resp {
  items: Item[];
  total: number;
  totais?: { valor_proposta: number; valor_pago: number; valor_pagar: number };
  params?: Record<string, string | number>;
}

interface Mun { nome: string; cod_ibge: string }

interface Individual {
  nu_proposta: string;
  entidade: string;
  tipo_proposta?: string;
  tipo_recurso?: string;
  valor_proposta: number;
  valor_pago: number;
}

interface EtapaWorkflow {
  numero: number;
  descricao: string;
  completada: boolean;
  atual: boolean;
}

interface ParlamentarFNS {
  nome?: string;
  partido?: string;
  nu_emenda?: string;
  ano?: string;
  valor?: number;
}

interface PagamentoFNS {
  parcela?: string;
  data?: number;  // ms epoch
  valor?: number;
  valor_acumulado?: number;
  ordem_bancaria?: string;
  nu_processo?: string;
  localizacao?: string;
}

interface PropostaDetalhe {
  nu_proposta: string;
  uf: string;
  municipio: string;
  cnpj: string;
  entidade: string;
  tipo_proposta: string;
  valor_proposta: number;
  ano: string;
  tipo_recurso: string;
  esfera: string;
  nu_portaria?: string;
  nu_processo: string;
  situacao_descricao: string;
  situacao_data?: number;
  data_portaria?: number;
  vl_empenhado: number;
  vl_pago: number;
  vl_pagar: number;
  parlamentares: ParlamentarFNS[];
  pagamentos: PagamentoFNS[];
  constituido_processo: boolean;
  etapas: EtapaWorkflow[];
  etapa_atual?: number;
}

const TIPOS_EMENDA = [
  "TODOS",
  "PROGRAMA",
  "EMENDA INDIVIDUAL",
  "EMENDA BANCADA",
  "EMENDA COMISSAO",
  "EMENDA BANCADA OBRIGATORIA",
];

function recursoColor(s?: string): string {
  if (!s) return "bg-gray-100";
  const u = s.toUpperCase();
  if (u.includes("INDIVIDUAL")) return "bg-blue-100 text-blue-800 border-blue-300";
  if (u.includes("BANCADA OBRIGAT")) return "bg-purple-100 text-purple-800 border-purple-300";
  if (u.includes("BANCADA")) return "bg-purple-100 text-purple-700 border-purple-200";
  if (u.includes("COMISSAO") || u.includes("COMISSÃO")) return "bg-amber-100 text-amber-800 border-amber-300";
  if (u.includes("PROGRAMA")) return "bg-green-100 text-green-800 border-green-300";
  return "bg-gray-100 text-gray-700 border-gray-300";
}

export default function PropostasFNSPage() {
  const currentYear = new Date().getFullYear();

  const [municipios, setMunicipios] = useState<Mun[]>([]);
  const [anos, setAnos] = useState<string[]>([]);
  const [nrProposta, setNrProposta] = useState("");
  const [ano, setAno] = useState(String(currentYear));
  const [estado, setEstado] = useState("MG");
  const [municipio, setMunicipio] = useState("ARAUJOS");
  const [tipoEmenda, setTipoEmenda] = useState("TODOS");
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Modal de detalhamento (clique no botao olho)
  const [detalheItem, setDetalheItem] = useState<Item | null>(null);
  const [individuais, setIndividuais] = useState<Array<Individual> | null>(null);
  const [loadingIndiv, setLoadingIndiv] = useState(false);
  const [propostaDetalhe, setPropostaDetalhe] = useState<PropostaDetalhe | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);

  // Quando abre modal nivel 1, busca lista de propostas individuais
  useEffect(() => {
    if (!detalheItem || !data) {
      setIndividuais(null);
      return;
    }
    setLoadingIndiv(true);
    api.get<{items: Individual[]}>("/fns/listar-individuais", {
      params: {
        municipio: data.params?.municipio,
        ano: data.params?.ano,
        uf: data.params?.uf,
        tipo_proposta: detalheItem.tipo_proposta,
        tipo_recurso: detalheItem.tipo_recurso,
      }
    }).then((r) => setIndividuais(r.data.items || []))
      .catch(() => setIndividuais([]))
      .finally(() => setLoadingIndiv(false));
  }, [detalheItem, data]);

  const abrirDetalheProposta = async (nuProposta: string) => {
    setLoadingDetalhe(true);
    setPropostaDetalhe(null);
    try {
      const r = await api.get<PropostaDetalhe>(`/fns/proposta/${nuProposta}`);
      setPropostaDetalhe(r.data);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error).message;
      alert(`Falha: ${msg}`);
    } finally {
      setLoadingDetalhe(false);
    }
  };

  useEffect(() => {
    api.get<Mun[]>("/fns/municipios").then((r) => setMunicipios(r.data || [])).catch(() => {});
    api.get<string[]>("/fns/anos").then((r) => setAnos(r.data || [])).catch(() => {
      // Fallback se /anos falha
      const list = [];
      for (let y = currentYear; y >= 2019; y--) list.push(String(y));
      setAnos(list);
    });
  }, [currentYear]);

  const consultar = async () => {
    setError(null);
    setLoading(true);
    try {
      const params: Record<string, string | number> = {
        municipio,
        ano,
        uf: estado,
      };
      if (nrProposta) params.nr_proposta = nrProposta;
      if (tipoEmenda !== "TODOS") params.tipo_emenda = tipoEmenda;
      const res = await api.get<Resp>("/fns/buscar", { params });
      setData(res.data);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error).message;
      setError(`Falha na consulta: ${msg}`);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const limpar = () => {
    setNrProposta("");
    setTipoEmenda("TODOS");
    setData(null);
    setError(null);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-blue-800">Propostas FAF - FNS</h1>
        <p className="text-sm text-muted-foreground">Consulta em tempo real no Fundo Nacional de Saúde (consultafns.saude.gov.br)</p>
      </div>

      {/* Formulario */}
      <div className="bg-white border rounded-lg p-4 space-y-3 shadow-sm">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs font-medium text-gray-700">Nº da Proposta</label>
            <Input
              value={nrProposta}
              onChange={(e) => setNrProposta(e.target.value)}
              placeholder="(opcional)"
              onKeyDown={(e) => { if (e.key === "Enter") consultar(); }}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700">Ano</label>
            <Select value={ano} onValueChange={(v) => setAno(v ?? String(currentYear))}>
              <SelectTrigger><SelectValue placeholder="Ano" /></SelectTrigger>
              <SelectContent>
                {anos.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700"><span className="text-red-600">*</span> Estado</label>
            <Select value={estado} onValueChange={(v) => setEstado(v ?? "MG")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="MG">MINAS GERAIS</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700"><span className="text-red-600">*</span> Município</label>
            <Select value={municipio} onValueChange={(v) => setMunicipio(v ?? "ARAUJOS")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {municipios.map((m) => <SelectItem key={m.cod_ibge} value={m.nome}>{m.nome}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700">Tipo de Emenda</label>
            <Select value={tipoEmenda} onValueChange={(v) => setTipoEmenda(v ?? "TODOS")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {TIPOS_EMENDA.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t">
          <Button variant="outline" onClick={limpar}>
            <Eraser className="size-4 mr-1" /> Limpar
          </Button>
          <Button onClick={consultar} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
            {loading ? <Loader2 className="size-4 animate-spin mr-2" /> : <Search className="size-4 mr-2" />}
            Consultar
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>
      )}

      {/* Resultado */}
      {data && (
        <div className="space-y-3">
          <div className="bg-gray-50 border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <h2 className="font-semibold">Resultado da Consulta</h2>
              <Button variant="outline" size="sm" onClick={() => window.print()}>
                <Printer className="size-3 mr-1" /> Imprimir
              </Button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-sm">
              <div><span className="font-medium text-gray-600">Estado:</span> {data.params?.uf}</div>
              <div><span className="font-medium text-gray-600">Município:</span> {data.params?.municipio}</div>
              <div><span className="font-medium text-gray-600">Ano:</span> {data.params?.ano}</div>
              <div><span className="font-medium text-gray-600">Registros:</span> {data.total}</div>
            </div>
          </div>

          {/* Stats cards */}
          {data.totais && (
            <div className="grid grid-cols-3 gap-3">
              <StatCard label="Valor Proposta" value={formatCurrency(data.totais.valor_proposta)} />
              <StatCard label="Valor Pago" value={formatCurrency(data.totais.valor_pago)} className="text-green-700" />
              <StatCard label="A Pagar" value={formatCurrency(data.totais.valor_pagar)} className="text-amber-700" />
            </div>
          )}

          {data.items.length === 0 ? (
            <div className="text-center text-muted-foreground py-8 border rounded-lg bg-white">
              Nenhuma proposta encontrada para os filtros aplicados.
            </div>
          ) : (
            <div className="rounded-lg border bg-white overflow-hidden">
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="[&>th]:py-2 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold bg-blue-50">
                    <TableHead>Tipo de Proposta</TableHead>
                    <TableHead>Tipo de Recurso</TableHead>
                    <TableHead>Nº Processo</TableHead>
                    <TableHead className="text-right">Valor Proposta</TableHead>
                    <TableHead className="text-right">Valor Pago</TableHead>
                    <TableHead className="text-right">A Pagar</TableHead>
                    <TableHead>Parlamentares</TableHead>
                    <TableHead className="w-[60px] text-center">Ações</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((it, idx) => (
                    <TableRow key={idx} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-gray-50">
                      <TableCell className="font-medium">{it.tipo_proposta || "-"}</TableCell>
                      <TableCell>
                        <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium border ${recursoColor(it.tipo_recurso)}`}>
                          {it.tipo_recurso || "-"}
                        </span>
                      </TableCell>
                      <TableCell className="font-mono">{it.nu_processo || "-"}</TableCell>
                      <TableCell className="text-right font-mono">{formatCurrency(it.valor_proposta)}</TableCell>
                      <TableCell className="text-right font-mono text-green-700">{formatCurrency(it.valor_pago)}</TableCell>
                      <TableCell className="text-right font-mono text-amber-700">{formatCurrency(it.valor_pagar)}</TableCell>
                      <TableCell title={(it.parlamentares || []).map((p) => p.nome).join(", ")}>
                        {(it.parlamentares || []).length > 0
                          ? <span className="text-[10px]">{(it.parlamentares || []).slice(0, 2).map((p) => p.nome).join(", ")}{(it.parlamentares || []).length > 2 ? ` +${(it.parlamentares || []).length - 2}` : ""}</span>
                          : <span className="text-gray-400">-</span>}
                      </TableCell>
                      <TableCell className="text-center">
                        <button
                          onClick={() => setDetalheItem(it)}
                          className="inline-flex items-center justify-center w-7 h-7 rounded bg-blue-500 hover:bg-blue-600 text-white"
                          title="Ver detalhamento"
                        >
                          <Eye className="size-3.5" />
                        </button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}

      {/* Modal Detalhamento */}
      {detalheItem && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center p-4 overflow-y-auto" onClick={() => setDetalheItem(null)}>
          <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl mt-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-blue-50 px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-blue-900">Detalhamento por Tipo de Proposta e Tipo de Recurso</h3>
              <button onClick={() => setDetalheItem(null)} className="text-gray-500 hover:text-gray-700"><X className="size-5" /></button>
            </div>
            <div className="p-4 space-y-4">
              {/* Dados Entidade + Proposta */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-3 border-b pb-3 text-sm">
                <div><span className="font-medium text-gray-600">Estado:</span> {data?.params?.uf}</div>
                <div><span className="font-medium text-gray-600">Município:</span> {data?.params?.municipio}</div>
                <div><span className="font-medium text-gray-600">Ano:</span> {data?.params?.ano}</div>
                <div><span className="font-medium text-gray-600">Tipo Recurso:</span> <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium border ${recursoColor(detalheItem.tipo_recurso)}`}>{detalheItem.tipo_recurso}</span></div>
              </div>

              <div className="bg-gray-50 rounded p-3">
                <h4 className="font-semibold text-sm mb-2">Dados da Proposta Agrupada</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                  <Field label="Tipo de Proposta" value={detalheItem.tipo_proposta || "-"} />
                  <Field label="Tipo de Recurso" value={detalheItem.tipo_recurso || "-"} />
                  <Field label="Nº Processo" value={detalheItem.nu_processo || "-"} mono />
                  <Field label="Processo Constituído" value={detalheItem.constituido_processo ? "Sim" : "Não"} />
                  <Field label="Valor Proposta" value={formatCurrency(detalheItem.valor_proposta)} mono className="text-blue-700" />
                  <Field label="Valor Pago" value={formatCurrency(detalheItem.valor_pago)} mono className="text-green-700" />
                  <Field label="A Pagar" value={formatCurrency(detalheItem.valor_pagar)} mono className="text-amber-700" />
                  <Field label="Qtd. Pagamentos" value={String(detalheItem.pagamentos_count ?? 0)} mono />
                </div>
              </div>

              {/* Parlamentares */}
              {(detalheItem.parlamentares || []).length > 0 && (
                <div className="bg-gray-50 rounded p-3">
                  <h4 className="font-semibold text-sm mb-2">Parlamentares ({detalheItem.parlamentares?.length})</h4>
                  <div className="flex flex-wrap gap-2">
                    {(detalheItem.parlamentares || []).map((p, i) => (
                      <span key={i} className="inline-flex items-center rounded bg-purple-50 border border-purple-200 px-2 py-0.5 text-[11px] text-purple-800">
                        {p.nome}{p.partido ? ` (${p.partido})` : ""}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Propostas individuais (nivel 1 listagem) */}
              <div className="bg-white border rounded p-3">
                <h4 className="font-semibold text-sm mb-2">Propostas Individuais (Nº SIPA)</h4>
                {loadingIndiv ? (
                  <div className="text-center text-sm text-gray-500 py-3">Carregando...</div>
                ) : (individuais && individuais.length > 0) ? (
                  <Table className="text-xs">
                    <TableHeader>
                      <TableRow className="[&>th]:py-1 [&>th]:px-2 [&>th]:text-[10px] [&>th]:font-semibold bg-blue-50">
                        <TableHead>Nº da Proposta</TableHead>
                        <TableHead>Entidade</TableHead>
                        <TableHead className="text-right">Valor Proposta</TableHead>
                        <TableHead className="text-right">Valor Pago</TableHead>
                        <TableHead className="w-[60px] text-center">Ação</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {individuais.map((i, idx) => (
                        <TableRow key={idx} className="[&>td]:py-1 [&>td]:px-2 [&>td]:text-[11px] hover:bg-gray-50">
                          <TableCell className="font-mono">{i.nu_proposta}</TableCell>
                          <TableCell>{i.entidade}</TableCell>
                          <TableCell className="text-right font-mono">{formatCurrency(i.valor_proposta)}</TableCell>
                          <TableCell className="text-right font-mono text-green-700">{formatCurrency(i.valor_pago)}</TableCell>
                          <TableCell className="text-center">
                            <button
                              onClick={() => abrirDetalheProposta(i.nu_proposta)}
                              className="inline-flex items-center justify-center w-6 h-6 rounded bg-blue-500 hover:bg-blue-600 text-white"
                              title="Ver detalhes"
                            >
                              <Eye className="size-3" />
                            </button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <p className="text-xs text-gray-500 italic text-center py-3">
                    Nenhuma proposta individual encontrada para esse grupo no FNS.
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal NÍVEL 2: Detalhe Completo da Proposta Individual */}
      {(propostaDetalhe || loadingDetalhe) && (
        <div className="fixed inset-0 z-[60] bg-black/50 flex items-start justify-center p-4 overflow-y-auto" onClick={() => setPropostaDetalhe(null)}>
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-5xl mt-4" onClick={(e) => e.stopPropagation()}>
            <div className="bg-blue-100 px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-blue-900">Detalhe da Proposta {propostaDetalhe?.nu_proposta || ""}</h3>
              <button onClick={() => setPropostaDetalhe(null)} className="text-gray-500 hover:text-gray-700"><X className="size-5" /></button>
            </div>
            <div className="p-4 space-y-3">
              {loadingDetalhe && <div className="text-center py-12 text-gray-500">Carregando detalhes...</div>}

              {propostaDetalhe && (
                <>
                  {/* Dados da Entidade */}
                  <Section title="Dados da Entidade">
                    <Field label="Estado" value={propostaDetalhe.uf} />
                    <Field label="Município" value={propostaDetalhe.municipio} />
                    <Field label="Entidade" value={propostaDetalhe.entidade} />
                    <Field label="CNPJ" value={propostaDetalhe.cnpj} mono />
                  </Section>

                  {/* Dados da Proposta */}
                  <Section title="Dados da Proposta">
                    <Field label="Nº da Proposta" value={propostaDetalhe.nu_proposta} mono />
                    <Field label="Tipo de Proposta" value={propostaDetalhe.tipo_proposta} />
                    <Field label="Ano" value={propostaDetalhe.ano} />
                    <Field label="Valor da Proposta" value={formatCurrency(propostaDetalhe.valor_proposta)} mono className="text-blue-700" />
                    <Field label="Nº Portaria" value={propostaDetalhe.nu_portaria || "-"} mono />
                    <Field label="Data Portaria" value={propostaDetalhe.data_portaria ? new Date(propostaDetalhe.data_portaria).toLocaleDateString("pt-BR") : "-"} />
                    <Field label="Valor Total de Empenho" value={formatCurrency(propostaDetalhe.vl_empenhado)} mono />
                    <Field label="Valor a Pagar" value={formatCurrency(propostaDetalhe.vl_pagar)} mono className="text-amber-700" />
                  </Section>

                  {/* Dados da Situação */}
                  <Section title="Dados da Situação da Proposta">
                    <Field label="Situação Atual" value={propostaDetalhe.situacao_descricao} className="text-green-800 font-semibold" />
                    <Field label="Data da Última Atualização" value={propostaDetalhe.situacao_data ? new Date(propostaDetalhe.situacao_data).toLocaleDateString("pt-BR") : "-"} />
                  </Section>

                  {/* Principais etapas - workflow 12 dots */}
                  {propostaDetalhe.etapas && propostaDetalhe.etapas.length > 0 && (
                    <div className="bg-gray-50 rounded p-3">
                      <h4 className="font-semibold text-sm mb-3">Principais etapas da proposta</h4>
                      <div className="flex items-center justify-between overflow-x-auto">
                        {propostaDetalhe.etapas.map((et, i) => (
                          <React.Fragment key={i}>
                            <div className="flex flex-col items-center text-center min-w-[60px]" title={et.descricao}>
                              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white ${
                                et.completada ? "bg-blue-500" : "bg-gray-300"
                              } ${et.atual ? "ring-2 ring-blue-300" : ""}`}>
                                {et.numero}
                              </div>
                              <div className="text-[9px] text-gray-600 mt-1 max-w-[60px] leading-tight">{et.descricao}</div>
                            </div>
                            {i < propostaDetalhe.etapas.length - 1 && (
                              <div className={`h-1 flex-1 mx-0.5 ${et.completada && propostaDetalhe.etapas[i+1].completada ? "bg-blue-500" : "bg-gray-300"}`} />
                            )}
                          </React.Fragment>
                        ))}
                      </div>
                      {!propostaDetalhe.constituido_processo && (
                        <p className="text-xs text-amber-700 italic mt-3">Não foi constituído processo para essa proposta.</p>
                      )}
                    </div>
                  )}

                  {/* Dados do Parlamentar */}
                  {propostaDetalhe.parlamentares && propostaDetalhe.parlamentares.length > 0 && (
                    <div className="border rounded p-3 bg-white">
                      <h4 className="font-semibold text-sm text-blue-900 border-b pb-1 mb-2">Dados do Parlamentar</h4>
                      <Table className="text-xs">
                        <TableHeader>
                          <TableRow className="[&>th]:py-1 [&>th]:px-2 [&>th]:text-[10px] [&>th]:font-semibold bg-blue-50">
                            <TableHead>Partido</TableHead>
                            <TableHead>Nome Parlamentar</TableHead>
                            <TableHead>Nº da Emenda</TableHead>
                            <TableHead>Ano</TableHead>
                            <TableHead className="text-right">Valor da Emenda</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {propostaDetalhe.parlamentares.map((p, i) => (
                            <TableRow key={i} className="[&>td]:py-1 [&>td]:px-2 [&>td]:text-[11px]">
                              <TableCell className="font-mono">{p.partido || "-"}</TableCell>
                              <TableCell className="font-medium">{p.nome || "-"}</TableCell>
                              <TableCell className="font-mono">{p.nu_emenda || "-"}</TableCell>
                              <TableCell>{p.ano || "-"}</TableCell>
                              <TableCell className="text-right font-mono text-blue-700">{formatCurrency(p.valor)}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}

                  {/* Dados do Pagamento */}
                  {propostaDetalhe.pagamentos && propostaDetalhe.pagamentos.length > 0 && (
                    <div className="border rounded p-3 bg-white">
                      <h4 className="font-semibold text-sm text-blue-900 border-b pb-1 mb-2">Dados do Pagamento</h4>
                      <Table className="text-xs">
                        <TableHeader>
                          <TableRow className="[&>th]:py-1 [&>th]:px-2 [&>th]:text-[10px] [&>th]:font-semibold bg-blue-50">
                            <TableHead>Parcela</TableHead>
                            <TableHead>Data Pagamento</TableHead>
                            <TableHead className="text-right">Valor</TableHead>
                            <TableHead className="text-right">Acumulado</TableHead>
                            <TableHead>Ordem Bancária</TableHead>
                            <TableHead>Nº Processo Pgto</TableHead>
                            <TableHead>Localização</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {propostaDetalhe.pagamentos.map((pg, i) => (
                            <TableRow key={i} className="[&>td]:py-1 [&>td]:px-2 [&>td]:text-[11px]">
                              <TableCell>{pg.parcela || "-"}</TableCell>
                              <TableCell>{pg.data ? new Date(pg.data).toLocaleDateString("pt-BR") : "-"}</TableCell>
                              <TableCell className="text-right font-mono text-green-700">{formatCurrency(pg.valor)}</TableCell>
                              <TableCell className="text-right font-mono">{formatCurrency(pg.valor_acumulado)}</TableCell>
                              <TableCell className="font-mono">{pg.ordem_bancaria || "-"}</TableCell>
                              <TableCell className="font-mono">{pg.nu_processo || "-"}</TableCell>
                              <TableCell className="text-[10px]">{pg.localizacao || "-"}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  )}

                  <div className="flex justify-end items-center gap-2 pt-2 border-t">
                    <RelacionadosButton params={{
                      municipio_nome: municipio, fonte: "fns",
                      proposta: propostaDetalhe.nu_proposta, processo: propostaDetalhe.nu_processo,
                      parlamentar: (propostaDetalhe.parlamentares || []).map((p) => p.nome).join(" "),
                      objeto: propostaDetalhe.tipo_proposta,
                    }} label="Relacionados" />
                    <Button variant="outline" onClick={() => setPropostaDetalhe(null)}>Voltar</Button>
                    <Button onClick={() => window.print()} className="bg-blue-600 hover:bg-blue-700">
                      <Printer className="size-4 mr-1" /> Imprimir
                    </Button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border rounded p-3 bg-white">
      <h4 className="font-semibold text-sm text-blue-900 border-b pb-1 mb-2">{title}</h4>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{children}</div>
    </div>
  );
}

function Field({ label, value, mono, className = "" }: { label: string; value: string; mono?: boolean; className?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase font-semibold text-gray-500">{label}</div>
      <div className={`text-sm mt-0.5 ${mono ? "font-mono" : ""} ${className}`}>{value}</div>
    </div>
  );
}

function StatCard({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg border bg-white p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-lg font-bold mt-1 ${className}`}>{value}</div>
    </div>
  );
}
