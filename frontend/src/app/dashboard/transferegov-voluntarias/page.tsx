"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Search, Eraser, Loader2, ExternalLink } from "lucide-react";
import api from "@/lib/api";
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
  atualizado_em?: string;
}

interface Resp {
  items: Proposta[];
  total: number;
  atualizado_em?: string;
}

const PORTAL_BASE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest";

function fmtData(iso?: string): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch { return "-"; }
}

function badgeColor(sit: string): string {
  const s = sit.toLowerCase();
  if (s.includes("execu")) return "bg-blue-100 text-blue-800";
  if (s.includes("aprovad")) return "bg-green-100 text-green-800";
  if (s.includes("rejeitad") || s.includes("impedimento")) return "bg-red-100 text-red-800";
  if (s.includes("anlise") || s.includes("análise")) return "bg-amber-100 text-amber-800";
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

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string> = { municipio_id: municipioId };
      if (search.trim()) params.search = search.trim();
      if (situacao.trim()) params.situacao = situacao.trim();
      const r = await api.get<Resp>("/transferegov/voluntarias", { params });
      setItems(r.data.items);
      setTotal(r.data.total);
      setAtualizadoEm(r.data.atualizado_em);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [municipioId, search, situacao]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">
      Selecione um municipio.
    </div>;
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
          <ExternalLink className="size-3" /> Abrir portal oficial
        </a>
      </div>

      {/* Filtros */}
      <div className="bg-white border rounded p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Buscar (nº proposta / proponente)</label>
            <Input value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Ex: 048291/2025"
                   onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Situacao</label>
            <Input value={situacao} onChange={(e) => setSituacao(e.target.value)}
                   placeholder="Ex: Em execucao, Aprovada"
                   onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div className="flex items-end gap-2">
            <Button onClick={buscar} disabled={loading} className="bg-blue-600 hover:bg-blue-700">
              {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />}
              Filtrar
            </Button>
            <Button variant="outline" onClick={() => { setSearch(""); setSituacao(""); setTimeout(buscar, 100); }}>
              <Eraser className="size-4 mr-1" /> Limpar
            </Button>
          </div>
        </div>
      </div>

      {/* Grid */}
      <div className="bg-white border rounded overflow-hidden">
        <div className="px-3 py-2 border-b bg-slate-50 text-sm">
          <strong>{total}</strong> propostas
        </div>
        {loading ? (
          <div className="p-3 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-gray-100 rounded" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="p-12 text-center text-slate-500">
            Nenhuma proposta encontrada para este municipio.
          </div>
        ) : (
          <Table className="text-xs table-fixed w-full">
            <TableHeader>
              <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold bg-blue-50">
                <TableHead className="w-[110px]">Nº Proposta</TableHead>
                <TableHead className="w-[230px]">Situacao</TableHead>
                <TableHead>Orgao</TableHead>
                <TableHead className="w-[180px]">Proponente</TableHead>
                <TableHead className="w-[70px] text-center">Parecer</TableHead>
                <TableHead className="w-[130px]">CNPJ</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((p, i) => (
                <TableRow key={i} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-blue-50">
                  <TableCell className="font-mono">{p.numero_proposta}</TableCell>
                  <TableCell>
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] ${badgeColor(p.situacao)}`}>
                      {p.situacao}
                    </span>
                  </TableCell>
                  <TableCell className="truncate" title={p.orgao}>{p.orgao}</TableCell>
                  <TableCell className="truncate" title={p.proponente}>{p.proponente}</TableCell>
                  <TableCell className="text-center">
                    <span className={p.possui_parecer === "Sim" ? "text-green-700" : "text-gray-400"}>
                      {p.possui_parecer}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[10px]">{p.identificacao}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
