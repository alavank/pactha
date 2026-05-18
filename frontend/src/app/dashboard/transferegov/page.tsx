"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Search, Eye, X, Loader2, Eraser, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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

  const [detalhe, setDetalhe] = useState<unknown | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);

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
    setLoadingDetalhe(true);
    try {
      const r = await api.get(`/transferegov/plano-acao/${id}`);
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
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Modal Detalhe */}
      {(detalhe !== null || loadingDetalhe) && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto"
             onClick={() => setDetalhe(null)}>
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-5xl mt-4 mb-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-blue-100 px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-blue-900">Dados do Plano de Acao</h3>
              <button onClick={() => setDetalhe(null)}><X className="size-5 text-gray-500 hover:text-gray-700" /></button>
            </div>
            <div className="p-4">
              {loadingDetalhe ? (
                <div className="text-center py-12"><Loader2 className="size-8 animate-spin mx-auto" /></div>
              ) : (
                <pre className="text-xs bg-slate-50 p-3 rounded overflow-x-auto max-h-[70vh]">
                  {JSON.stringify(detalhe, null, 2)}
                </pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
