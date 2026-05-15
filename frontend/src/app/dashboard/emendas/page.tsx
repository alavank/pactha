"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronLeft, ChevronRight, Search as SearchIcon } from "lucide-react";
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

interface Emenda {
  id: number;
  municipio_id: number;
  nr_indicacao?: string;
  nome_responsavel?: string;
  tipo_indicacao?: string;
  uo_codigo?: string;
  uo_sigla?: string;
  cnpj_beneficiario?: string;
  beneficiario?: string;
  grupo_despesa?: string;
  tipo_atendimento?: string;
  valor_indicacao?: number;
  status_indicacao?: string;
  ano?: number;
}

const PER_PAGE = 25;

function statusColor(s?: string): string {
  if (!s) return "bg-gray-100 text-gray-700";
  const u = s.toUpperCase();
  if (u.includes("APROVAD")) return "bg-green-100 text-green-800 border-green-300";
  if (u.includes("REJEIT") || u.includes("CANCEL")) return "bg-red-100 text-red-800 border-red-300";
  if (u.includes("ANALIS") || u.includes("AGUARD")) return "bg-yellow-100 text-yellow-800 border-yellow-300";
  return "bg-blue-100 text-blue-800 border-blue-300";
}

export default function EmendasEstaduaisPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [data, setData] = useState<{ items: Emenda[]; total: number; pages: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [ano, setAno] = useState("todos");
  const [responsavel, setResponsavel] = useState("");
  const [tipo, setTipo] = useState("todos");
  const [stats, setStats] = useState<{ total: number; valor_total: number; responsaveis: number; aprovadas: number } | null>(null);
  const [anos, setAnos] = useState<number[]>([]);

  useEffect(() => {
    if (!municipioId) return;
    api.get<number[]>("/emendas-estaduais/anos", { params: { municipio_id: municipioId } })
      .then((r) => setAnos(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, [municipioId]);

  useEffect(() => { setPage(1); }, [ano, responsavel, tipo]);

  const fetchData = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    const params: Record<string, string | number> = {
      municipio_id: municipioId,
      page,
      per_page: PER_PAGE,
    };
    if (ano !== "todos") params.ano = ano;
    if (responsavel) params.responsavel = responsavel;
    if (tipo !== "todos") params.tipo = tipo;
    api.get<{ items: Emenda[]; total: number; pages: number }>("/emendas-estaduais", { params })
      .then((r) => setData(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));

    api.get("/emendas-estaduais/stats", { params: { municipio_id: municipioId, ...(ano !== "todos" ? { ano } : {}) } })
      .then((r) => setStats(r.data as never))
      .catch(() => {});
  }, [municipioId, page, ano, responsavel, tipo]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  const items = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-gray-900">Emendas Parlamentares Estaduais</h1>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-4 gap-3">
          <StatCard label="Total Indicações" value={stats.total.toLocaleString("pt-BR")} />
          <StatCard label="Valor Total Indicado" value={formatCurrency(stats.valor_total)} />
          <StatCard label="Parlamentares" value={stats.responsaveis.toString()} />
          <StatCard label="Aprovadas" value={stats.aprovadas.toLocaleString("pt-BR")} />
        </div>
      )}

      {/* Filtros */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={ano} onValueChange={(v) => setAno(v ?? "todos")}>
          <SelectTrigger className="w-32"><SelectValue placeholder="Ano" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos Anos</SelectItem>
            {anos.map((a) => <SelectItem key={a} value={String(a)}>{a}</SelectItem>)}
          </SelectContent>
        </Select>

        <Select value={tipo} onValueChange={(v) => setTipo(v ?? "todos")}>
          <SelectTrigger className="w-56"><SelectValue placeholder="Tipo" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos Tipos</SelectItem>
            <SelectItem value="Transferência Especial">Transferência Especial</SelectItem>
            <SelectItem value="Aplicação Direta">Aplicação Direta</SelectItem>
            <SelectItem value="Convênio">Convênio</SelectItem>
          </SelectContent>
        </Select>

        <div className="relative flex-1 min-w-[200px]">
          <SearchIcon className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por responsável (parlamentar)..."
            value={responsavel}
            onChange={(e) => setResponsavel(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Tabela */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded bg-gray-100" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhuma emenda encontrada. Rode o scraper SIGCON-MG (Emendas/Pesquisar Por Convenente) para popular.
        </div>
      ) : (
        <>
          <div className="rounded-lg border bg-white overflow-hidden">
            <Table className="text-xs">
              <TableHeader>
                <TableRow className="[&>th]:py-2 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold [&>th]:whitespace-nowrap">
                  <TableHead className="w-[80px]">Nº Indicação</TableHead>
                  <TableHead>Responsável</TableHead>
                  <TableHead className="w-[150px]">Tipo</TableHead>
                  <TableHead className="w-[60px]">UO</TableHead>
                  <TableHead className="w-[80px]">Sigla UO</TableHead>
                  <TableHead className="w-[140px]">CNPJ Beneficiário</TableHead>
                  <TableHead>Beneficiário</TableHead>
                  <TableHead>Grupo Despesa</TableHead>
                  <TableHead>Tipo Atend./Aplicação</TableHead>
                  <TableHead className="w-[110px] text-right">Valor</TableHead>
                  <TableHead className="w-[100px]">Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((em) => (
                  <TableRow key={em.id} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-gray-50">
                    <TableCell className="font-mono">{em.nr_indicacao || "-"}</TableCell>
                    <TableCell className="font-medium">{em.nome_responsavel || "-"}</TableCell>
                    <TableCell title={em.tipo_indicacao || ""}>
                      <span className="text-[10px] truncate block max-w-[150px]">{em.tipo_indicacao || "-"}</span>
                    </TableCell>
                    <TableCell className="font-mono">{em.uo_codigo || "-"}</TableCell>
                    <TableCell className="font-mono">{em.uo_sigla || "-"}</TableCell>
                    <TableCell className="font-mono text-[10px]">{em.cnpj_beneficiario || "-"}</TableCell>
                    <TableCell title={em.beneficiario || ""}>
                      <span className="truncate block max-w-[200px]">{em.beneficiario || "-"}</span>
                    </TableCell>
                    <TableCell title={em.grupo_despesa || ""}>
                      <span className="truncate block max-w-[150px] text-[10px]">{em.grupo_despesa || "-"}</span>
                    </TableCell>
                    <TableCell title={em.tipo_atendimento || ""}>
                      <span className="truncate block max-w-[180px] text-[10px]">{em.tipo_atendimento || "-"}</span>
                    </TableCell>
                    <TableCell className="text-right font-mono">{formatCurrency(em.valor_indicacao)}</TableCell>
                    <TableCell>
                      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium border ${statusColor(em.status_indicacao)}`}>
                        {em.status_indicacao || "-"}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">Página {page} de {totalPages} ({data?.total ?? 0} registros)</p>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                <ChevronLeft className="size-4" /> Anterior
              </Button>
              <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Próximo <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-white p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-bold mt-1">{value}</div>
    </div>
  );
}
