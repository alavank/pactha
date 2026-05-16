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
import { Search, Loader2, Eraser, Printer } from "lucide-react";

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
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      )}
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
