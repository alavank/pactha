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

// Mapeia secretarias estaduais MG e ministerios federais para sigla curta
const SIGLAS: Record<string, string> = {
  "SECRETARIA DE ESTADO DE SAUDE": "SES",
  "SECRETARIA DE ESTADO DE GOVERNO": "SEGOV",
  "SECRETARIA DE ESTADO DE EDUCACAO": "SEE",
  "SECRETARIA DE ESTADO DE DESENVOLVIMENTO ECONOMICO": "SEDE",
  "SECRETARIA DE ESTADO DE DESENVOLVIMENTO SOCIAL": "SEDESE",
  "SECRETARIA DE ESTADO DE INFRAESTRUTURA": "SEINFRA",
  "SECRETARIA DE ESTADO DE AGRICULTURA": "SEAPA",
  "SECRETARIA DE ESTADO DE CULTURA": "SECULT",
  "SECRETARIA DE ESTADO DE ESPORTES": "SEESP",
  "SECRETARIA DE ESTADO DE TURISMO": "SETUR",
  "SECRETARIA DE ESTADO DE MEIO AMBIENTE": "SEMAD",
  "SECRETARIA DE ESTADO DE PLANEJAMENTO": "SEPLAG",
  "MINISTERIO DA SAUDE": "Min. Saude",
  "MINISTERIO DA FAZENDA": "Min. Fazenda",
  "MINISTERIO DA EDUCACAO": "Min. Educacao",
  "MINISTERIO DO ESPORTE": "Min. Esporte",
  "MINISTERIO DA INTEGRACAO": "MI",
  "MINISTERIO DA INTEGRA": "MI",
  "MINISTERIO DO DESENVOLVIMENTO": "MDS",
  "MINISTERIO DA AGRICULTURA": "Min. Agricultura",
  "MINISTERIO DAS CIDADES": "Min. Cidades",
};

// Codigos numericos SIAFI dos orgaos federais (TransfereGov usa esses)
// Ref: https://www.planejamento.gov.br/transferegov - cod orgao superior
const ORGAO_FED_CODIGOS: Record<string, { sigla: string; nome: string }> = {
  "20000": { sigla: "PR",          nome: "Presidência da República" },
  "22000": { sigla: "MAPA",        nome: "Min. Agricultura, Pecuária e Abastecimento" },
  "24000": { sigla: "MCTI",        nome: "Min. Ciência, Tecnologia e Inovação" },
  "25000": { sigla: "MF",          nome: "Min. Fazenda" },
  "26000": { sigla: "MEC",         nome: "Min. Educação" },
  "30000": { sigla: "MJ",          nome: "Min. Justiça e Segurança Pública" },
  "33000": { sigla: "MPS",         nome: "Min. Previdência Social" },
  "35000": { sigla: "MRE",         nome: "Min. Relações Exteriores" },
  "36000": { sigla: "Min. Saúde",  nome: "Min. Saúde" },
  "38000": { sigla: "MTb",         nome: "Min. Trabalho e Emprego" },
  "39000": { sigla: "MT",          nome: "Min. Transportes" },
  "41000": { sigla: "MinC",        nome: "Min. Cultura" },
  "42000": { sigla: "MinC",        nome: "Min. Cultura" },
  "44000": { sigla: "MMA",         nome: "Min. Meio Ambiente" },
  "49000": { sigla: "MDA",         nome: "Min. Desenvolvimento Agrário" },
  "51000": { sigla: "Min. Esporte", nome: "Min. Esporte" },
  "52000": { sigla: "MD",          nome: "Min. Defesa" },
  "53000": { sigla: "MIDR",        nome: "Min. Integração e Desenvolvimento Regional" },
  "54000": { sigla: "MTur",        nome: "Min. Turismo" },
  "55000": { sigla: "MDS",         nome: "Min. Desenvolvimento Social" },
  "56000": { sigla: "MCID",        nome: "Min. Cidades" },
  "58000": { sigla: "MPO",         nome: "Min. Planejamento e Orçamento" },
};

function siglaOrgao(o?: string | null): string {
  if (!o) return "-";
  const trimmed = o.trim();
  // Codigo numerico federal (ex: "22000")
  if (/^\d{4,6}$/.test(trimmed) && ORGAO_FED_CODIGOS[trimmed]) {
    return ORGAO_FED_CODIGOS[trimmed].sigla;
  }
  const up = trimmed.toUpperCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  for (const [k, sig] of Object.entries(SIGLAS)) {
    if (up.startsWith(k)) return sig;
  }
  return trimmed.length > 18 ? trimmed.slice(0, 18) + "..." : trimmed;
}

function nomeOrgaoFull(o?: string | null): string {
  if (!o) return "";
  const trimmed = o.trim();
  if (/^\d{4,6}$/.test(trimmed) && ORGAO_FED_CODIGOS[trimmed]) {
    const m = ORGAO_FED_CODIGOS[trimmed];
    return `${trimmed} - ${m.nome}`;
  }
  return trimmed;
}

function isTE(objeto?: string | null): boolean {
  return !!objeto && /TRANSFER[ÊE]NCIA\s+ESPECIAL/i.test(objeto);
}

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
    // Endpoint novo (frente F): pendencias com aba Resumo + highlight visual
    // (vermelho para vencidas, salmao para vigencia <=30 dias)
    downloadAuth(`/export-relatorios/pendencias-xlsx?municipio_id=${municipioId}`,
                 `Pendencias_${municipioId}.xlsx`);
  };

  // Helper para downloads autenticados (substitui o boilerplate fetch+blob+anchor)
  const downloadAuth = (path: string, filename: string) => {
    const token = localStorage.getItem("pacta_token");
    fetch(`${api.defaults.baseURL}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => r.blob())
      .then((blob) => {
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        a.download = filename;
        a.click();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      });
  };

  const handleRMWord = () => {
    if (!municipioId) return;
    downloadAuth(`/export-relatorios/rm-word?municipio_id=${municipioId}`,
                 `RM_${municipioId}.docx`);
  };

  const handleRMPdf = () => {
    if (!municipioId) return;
    downloadAuth(`/export-relatorios/rm-pdf?municipio_id=${municipioId}`,
                 `RM_${municipioId}.pdf`);
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
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-gray-900">Convenios</h1>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="default"
            size="sm"
            onClick={() => {
              if (!municipioId) return;
              const token = localStorage.getItem("pacta_token");
              fetch(`${api.defaults.baseURL}/relatorio-monitoramento?municipio_id=${municipioId}`, {
                headers: { Authorization: `Bearer ${token}` },
              })
                .then((r) => r.text())
                .then((html) => {
                  const blob = new Blob([html], { type: "text/html" });
                  const url = URL.createObjectURL(blob);
                  window.open(url, "_blank");
                });
            }}
            className="bg-indigo-600 hover:bg-indigo-700"
          >
            <Download className="mr-2 size-4" />
            Gerar Relatorio Mensal (RM)
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={() => {
              if (!municipioId) return;
              const token = localStorage.getItem("pacta_token");
              fetch(`${api.defaults.baseURL}/levantamento-parlamentar?municipio_id=${municipioId}`, {
                headers: { Authorization: `Bearer ${token}` },
              })
                .then((r) => r.text())
                .then((html) => {
                  const blob = new Blob([html], { type: "text/html" });
                  const url = URL.createObjectURL(blob);
                  window.open(url, "_blank");
                });
            }}
            className="bg-emerald-700 hover:bg-emerald-800"
          >
            <Download className="mr-2 size-4" />
            Levantamento por Parlamentar
          </Button>
          <Button variant="outline" size="sm" onClick={handleRMWord}>
            <Download className="mr-2 size-4" />
            RM Word
          </Button>
          <Button variant="outline" size="sm" onClick={handleRMPdf}>
            <Download className="mr-2 size-4" />
            RM PDF
          </Button>
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
            placeholder="Buscar por nº, proposta, plano, instrumento, SIAFI ou objeto..."
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
          <div className="rounded-lg border bg-white overflow-hidden">
            <Table className="text-xs table-fixed w-full">
              <TableHeader>
                <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] [&>th]:font-semibold [&>th]:whitespace-nowrap">
                  <TableHead className="w-[90px]">Nr</TableHead>
                  <TableHead className="w-[55px]">Fonte</TableHead>
                  <TableHead className="w-[75px]">Proposta</TableHead>
                  <TableHead className="w-[75px]">Plano</TableHead>
                  <TableHead className="w-[100px]">Instrumento</TableHead>
                  <TableHead className="w-[75px]">Orgao</TableHead>
                  <TableHead className="min-w-0">Objeto</TableHead>
                  <TableHead className="w-[105px]">Situacao</TableHead>
                  <TableHead className="w-[90px] text-right">Repasse</TableHead>
                  <TableHead className="w-[70px] text-right">Contrap.</TableHead>
                  <TableHead className="w-[70px]">Assinat.</TableHead>
                  <TableHead className="w-[70px]">Vigencia</TableHead>
                  <TableHead className="w-[50px]">Dias</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((conv: Convenio) => {
                  const objeto = conv.objeto || "";
                  const programa = conv.tipo_programa || conv.programa || "";
                  const orgao = conv.orgao_concedente || "";
                  const tipTitle = `${isTE(conv.objeto) ? "[TE] " : ""}${objeto}${programa ? "\n\nPrograma: " + programa : ""}`;
                  return (
                  <TableRow key={conv.id} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] hover:bg-gray-50">
                    <TableCell className="font-mono whitespace-nowrap truncate" title={`Nr: ${conv.nr_convenio || conv.nr_sigcon || "-"}${conv.nr_siafi ? "\nSIAFI: " + conv.nr_siafi : ""}`}>
                      {conv.nr_convenio || conv.nr_sigcon || "-"}
                    </TableCell>
                    <TableCell title={conv.fonte || ""}>
                      {conv.fonte && (
                        <span className="inline-flex items-center rounded bg-indigo-50 border border-indigo-200 px-1 py-0.5 text-[9px] font-mono text-indigo-700">
                          {conv.fonte
                            .replace("TransfereGov-Proposta","TG-P")
                            .replace("TransfereGov","TG")
                            .replace("PortalTransparencia","PT")
                            .replace("SIGCON-MG","SIGCON")
                            .replace("CODEVASF","CODE")}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-[10px] whitespace-nowrap truncate text-muted-foreground" title={conv.nr_proposta ? `Nº Proposta: ${conv.nr_proposta}` : "Sem nº de proposta"}>
                      {conv.nr_proposta || "-"}
                    </TableCell>
                    <TableCell className="font-mono text-[10px] whitespace-nowrap truncate text-muted-foreground" title={conv.nr_plano_trabalho ? `Nº Plano de Trabalho: ${conv.nr_plano_trabalho}` : "Sem nº de plano"}>
                      {conv.nr_plano_trabalho || "-"}
                    </TableCell>
                    <TableCell className="font-mono text-[10px] whitespace-nowrap truncate text-muted-foreground" title={conv.nr_instrumento ? `Nº Instrumento: ${conv.nr_instrumento}` : "Sem nº de instrumento"}>
                      {conv.nr_instrumento || "-"}
                    </TableCell>
                    <TableCell className="font-mono whitespace-nowrap truncate" title={nomeOrgaoFull(conv.orgao_concedente) || orgao}>
                      {siglaOrgao(conv.orgao_concedente)}
                    </TableCell>
                    <TableCell title={tipTitle}>
                      <div className="flex items-center gap-1 min-w-0">
                        {isTE(conv.objeto) && (
                          <span className="shrink-0 inline-flex items-center rounded bg-purple-50 border border-purple-200 px-1 text-[9px] font-mono text-purple-700">TE</span>
                        )}
                        <span className="truncate">{objeto || "-"}</span>
                      </div>
                    </TableCell>
                    <TableCell title={conv.situacao || ""}>
                      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium truncate max-w-full ${situacaoBadgeColor(conv.situacao)}`}>
                        {conv.situacao || "-"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right whitespace-nowrap" title={`Repasse: ${formatCurrency(conv.valor_repasse ?? conv.valor_total)}\nGlobal: ${formatCurrency(conv.valor_total)}`}>
                      {formatCurrency(conv.valor_repasse ?? conv.valor_total)}
                    </TableCell>
                    <TableCell className="text-right text-muted-foreground whitespace-nowrap" title={conv.valor_contrapartida ? `Contrapartida: ${formatCurrency(conv.valor_contrapartida)}` : "Sem contrapartida"}>
                      {conv.valor_contrapartida ? formatCurrency(conv.valor_contrapartida) : "-"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap" title={`Assinatura: ${formatDate(conv.dt_inicio)}`}>
                      {formatDate(conv.dt_inicio)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap" title={`Vigencia: ${formatDate(conv.dt_fim_vigencia)}`}>
                      {formatDate(conv.dt_fim_vigencia)}
                    </TableCell>
                    <TableCell title={conv.dias_restantes != null ? `${conv.dias_restantes} dias restantes` : ""}>
                      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium ${diasRestantesBadge(conv.dias_restantes)}`}>
                        {conv.dias_restantes != null
                          ? conv.dias_restantes < 0
                            ? `${Math.abs(conv.dias_restantes)}d`
                            : `${conv.dias_restantes}d`
                          : "-"}
                      </span>
                    </TableCell>
                  </TableRow>
                );
                })}
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
