"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Download, Search as SearchIcon, ChevronLeft, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
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
import {
  formatCurrency,
  formatDate,
  diasRestantesBadge,
  situacaoBadgeColor,
} from "@/lib/utils";
import type { Convenio, ConvenioList } from "@/types";

const PER_PAGE = 20;

export default function ConveniosPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [data, setData] = useState<ConvenioList | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [esfera, setEsfera] = useState("todos");
  const [situacao, setSituacao] = useState("todos");
  const [ano, setAno] = useState("todos");
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [situacoes, setSituacoes] = useState<string[]>([]);
  const [anos, setAnos] = useState<number[]>([]);

  // Load distinct situacoes and anos for this municipio
  useEffect(() => {
    if (!municipioId) return;
    api
      .get<string[]>("/convenios/situacoes", { params: { municipio_id: municipioId } })
      .then((res) => setSituacoes(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});
    api
      .get<number[]>("/convenios/anos", { params: { municipio_id: municipioId } })
      .then((res) => setAnos(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});
  }, [municipioId]);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  // Reset page on filter change
  useEffect(() => {
    setPage(1);
  }, [esfera, situacao, ano, debouncedSearch]);

  const fetchData = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);

    const params: Record<string, string | number> = {
      municipio_id: municipioId,
      page,
      per_page: PER_PAGE,
    };
    if (esfera !== "todos") params.esfera = esfera;
    if (situacao !== "todos") params.situacao = situacao;
    if (ano !== "todos") params.ano = ano;
    if (debouncedSearch) params.search = debouncedSearch;

    api
      .get<ConvenioList>("/convenios", { params })
      .then((res) => setData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [municipioId, page, esfera, situacao, ano, debouncedSearch]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleExport = (format: "xlsx" | "pdf" = "xlsx") => {
    if (!municipioId) return;
    const token = localStorage.getItem("pacta_token");
    const url = `${api.defaults.baseURL}/export/convenios?municipio_id=${municipioId}&format=${format}`;
    // Open with auth via fetch
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob);
        window.open(blobUrl, "_blank");
      });
  };

  const handleExportPendencias = () => {
    if (!municipioId) return;
    const token = localStorage.getItem("pacta_token");
    const url = `${api.defaults.baseURL}/export/pendencias?municipio_id=${municipioId}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = "pendencias_pacta.xlsx";
        a.click();
      });
  };

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar convenios.
      </div>
    );
  }

  const items = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Convenios</h1>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleExportPendencias}>
            <Download className="mr-2 size-4" />
            Pendencias
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleExport("pdf")}>
            <Download className="mr-2 size-4" />
            PDF
          </Button>
          <Button variant="outline" size="sm" onClick={() => handleExport("xlsx")}>
            <Download className="mr-2 size-4" />
            Excel
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={esfera} onValueChange={(v) => setEsfera(v ?? "todos")}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Esfera" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos</SelectItem>
            <SelectItem value="federal">Federal</SelectItem>
            <SelectItem value="estadual">Estadual</SelectItem>
          </SelectContent>
        </Select>

        <Select value={situacao} onValueChange={(v) => setSituacao(v ?? "todos")}>
          <SelectTrigger className="w-56">
            <SelectValue placeholder="Situacao" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todas Situacoes</SelectItem>
            {situacoes.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={ano} onValueChange={(v) => setAno(v ?? "todos")}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Ano" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos Anos</SelectItem>
            {anos.map((a) => (
              <SelectItem key={a} value={String(a)}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="relative flex-1 min-w-[200px]">
          <SearchIcon className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por numero, orgao ou objeto..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhum dado encontrado.
        </div>
      ) : (
        <>
          <div className="rounded-lg border bg-white">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Nr Convenio</TableHead>
                  <TableHead>Orgao</TableHead>
                  <TableHead className="max-w-[300px]">Objeto</TableHead>
                  <TableHead>Situacao</TableHead>
                  <TableHead className="text-right">Valor Total</TableHead>
                  <TableHead>Vigencia</TableHead>
                  <TableHead>Dias Restantes</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((conv: Convenio) => (
                  <TableRow key={conv.id}>
                    <TableCell className="font-medium">
                      {conv.nr_convenio || conv.nr_sigcon || "-"}
                    </TableCell>
                    <TableCell className="max-w-[150px] truncate">
                      {conv.orgao_concedente || "-"}
                    </TableCell>
                    <TableCell className="max-w-[300px]">
                      <span className="line-clamp-2 text-sm">
                        {conv.objeto
                          ? conv.objeto.length > 80
                            ? conv.objeto.slice(0, 80) + "..."
                            : conv.objeto
                          : "-"}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${situacaoBadgeColor(
                          conv.situacao
                        )}`}
                      >
                        {conv.situacao || "-"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right">
                      {formatCurrency(conv.valor_total)}
                    </TableCell>
                    <TableCell>{formatDate(conv.dt_fim_vigencia)}</TableCell>
                    <TableCell>
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${diasRestantesBadge(
                          conv.dias_restantes
                        )}`}
                      >
                        {conv.dias_restantes != null
                          ? conv.dias_restantes < 0
                            ? `${Math.abs(conv.dias_restantes)}d vencido`
                            : `${conv.dias_restantes}d`
                          : "-"}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Pagina {page} de {totalPages} ({data?.total ?? 0} registros)
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft className="size-4" />
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Proximo
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
