"use client";

import React, { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, ChevronUp, CheckCircle2, Circle } from "lucide-react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  formatCurrency,
  formatDate,
  diasRestantesBadge,
  situacaoBadgeColor,
} from "@/lib/utils";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PrestacaoContas, PrestacaoDocumento } from "@/types";

const TOTAL_STEPS = 16;

function statusBadgeColor(status: string): string {
  const s = status.toLowerCase();
  if (s.includes("conclu") || s.includes("finaliz")) return "bg-green-100 text-green-700";
  if (s.includes("andamento") || s.includes("execu")) return "bg-blue-100 text-blue-700";
  if (s.includes("penden")) return "bg-yellow-100 text-yellow-700";
  if (s.includes("atras") || s.includes("irregular")) return "bg-red-100 text-red-700";
  return "bg-gray-100 text-gray-600";
}

function WorkflowTimeline({ etapaAtual }: { etapaAtual: number }) {
  return (
    <div className="flex items-center gap-0.5 py-2">
      {Array.from({ length: TOTAL_STEPS }).map((_, i) => {
        const step = i + 1;
        const isCompleted = step < etapaAtual;
        const isCurrent = step === etapaAtual;
        return (
          <div
            key={step}
            className="group relative flex-1"
            title={`Etapa ${step}`}
          >
            <div
              className={`h-2.5 rounded-sm transition-colors ${
                isCompleted
                  ? "bg-green-500"
                  : isCurrent
                  ? "bg-indigo-500"
                  : "bg-gray-200"
              }`}
            />
            <span className="absolute -top-5 left-1/2 -translate-x-1/2 hidden text-[10px] text-muted-foreground group-hover:block">
              {step}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function DocumentChecklist({
  documentos,
}: {
  documentos: PrestacaoDocumento[];
}) {
  if (!documentos || documentos.length === 0) {
    return (
      <p className="py-2 text-sm text-muted-foreground">
        Nenhum documento cadastrado.
      </p>
    );
  }

  return (
    <div className="space-y-2 py-2">
      {documentos.map((doc) => (
        <div
          key={doc.id}
          className="flex items-center gap-3 rounded-md border px-3 py-2"
        >
          <Checkbox checked={doc.enviado} disabled />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">{doc.documento_nome}</p>
            {doc.observacao && (
              <p className="truncate text-xs text-muted-foreground">
                {doc.observacao}
              </p>
            )}
          </div>
          {doc.dt_envio && (
            <span className="text-xs text-muted-foreground shrink-0">
              {new Date(doc.dt_envio).toLocaleDateString("pt-BR")}
            </span>
          )}
          {doc.enviado ? (
            <CheckCircle2 className="size-4 text-green-500 shrink-0" />
          ) : (
            <Circle className="size-4 text-gray-300 shrink-0" />
          )}
        </div>
      ))}
    </div>
  );
}

export default function PrestacaoPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [prestacoes, setPrestacoes] = useState<PrestacaoContas[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [anoFilter, setAnoFilter] = useState("todos");

  const anosDisponiveis = Array.from({ length: 20 }, (_, i) => 2026 - i);

  useEffect(() => {
    if (!municipioId) return;
    setLoading(true);
    const params: Record<string, string | number> = { municipio_id: municipioId };
    if (anoFilter !== "todos") params.ano = anoFilter;
    api
      .get<PrestacaoContas[]>("/prestacao", { params })
      .then((res) => setPrestacoes(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [municipioId, anoFilter]);

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar prestacao de contas.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Prestacao de Contas</h1>
        <Select value={anoFilter} onValueChange={(v) => setAnoFilter(v ?? "todos")}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Ano" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos Anos</SelectItem>
            {anosDisponiveis.map((a) => (
              <SelectItem key={a} value={String(a)}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      ) : prestacoes.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhum dado encontrado.
        </div>
      ) : (
        <div className="rounded-lg border bg-white overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <TableHead>Esfera</TableHead>
                <TableHead>Nr Convenio</TableHead>
                <TableHead className="max-w-[320px]">Objeto</TableHead>
                <TableHead>Orgao Concedente</TableHead>
                <TableHead className="text-right">Valor Total</TableHead>
                <TableHead>Vigencia</TableHead>
                <TableHead>Etapa</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {prestacoes.map((prest) => {
                const isExpanded = expandedId === prest.id;
                return (
                  <React.Fragment key={prest.id}>
                    <TableRow
                      className="cursor-pointer hover:bg-gray-50"
                      onClick={() =>
                        setExpandedId(isExpanded ? null : prest.id)
                      }
                    >
                      <TableCell>
                        {isExpanded ? (
                          <ChevronUp className="size-4 text-muted-foreground" />
                        ) : (
                          <ChevronDown className="size-4 text-muted-foreground" />
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="secondary"
                          className={`text-xs uppercase ${
                            prest.esfera === "federal"
                              ? "bg-blue-100 text-blue-700"
                              : "bg-indigo-100 text-indigo-700"
                          }`}
                        >
                          {prest.esfera || "-"}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">
                        {prest.nr_convenio || "-"}
                      </TableCell>
                      <TableCell className="max-w-[320px]">
                        <span className="line-clamp-2 text-sm">
                          {prest.objeto
                            ? prest.objeto.length > 100
                              ? prest.objeto.slice(0, 100) + "..."
                              : prest.objeto
                            : "-"}
                        </span>
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-sm">
                        {prest.orgao_concedente || "-"}
                      </TableCell>
                      <TableCell className="text-right">
                        {formatCurrency(prest.valor_total)}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col text-xs">
                          <span>{formatDate(prest.dt_fim_vigencia)}</span>
                          {prest.dias_restantes != null && (
                            <span
                              className={`inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs ${diasRestantesBadge(
                                prest.dias_restantes
                              )}`}
                            >
                              {prest.dias_restantes < 0
                                ? `${Math.abs(prest.dias_restantes)}d vencido`
                                : `${prest.dias_restantes}d restantes`}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-mono text-xs">
                            {prest.etapa_atual}/{TOTAL_STEPS}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {prest.etapa_nome || "-"}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusBadgeColor(
                            prest.status
                          )}`}
                        >
                          {prest.status}
                        </span>
                      </TableCell>
                    </TableRow>
                    {isExpanded && (
                      <TableRow>
                        <TableCell colSpan={9} className="bg-gray-50 p-4">
                          <div className="space-y-3">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                              {prest.objeto && (
                                <div>
                                  <strong className="text-muted-foreground">Objeto completo:</strong>
                                  <p className="mt-1">{prest.objeto}</p>
                                </div>
                              )}
                              <div className="space-y-1">
                                {prest.situacao && (
                                  <p>
                                    <strong className="text-muted-foreground">Situacao:</strong>{" "}
                                    <span
                                      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${situacaoBadgeColor(
                                        prest.situacao
                                      )}`}
                                    >
                                      {prest.situacao}
                                    </span>
                                  </p>
                                )}
                                {prest.ano && (
                                  <p>
                                    <strong className="text-muted-foreground">Ano:</strong> {prest.ano}
                                  </p>
                                )}
                                {prest.dt_inicio && (
                                  <p>
                                    <strong className="text-muted-foreground">Inicio:</strong>{" "}
                                    {formatDate(prest.dt_inicio)}
                                  </p>
                                )}
                              </div>
                            </div>
                            <div>
                              <h4 className="mb-2 text-sm font-semibold">
                                Workflow (16 etapas)
                              </h4>
                              <WorkflowTimeline etapaAtual={prest.etapa_atual} />
                            </div>
                            <div>
                              <h4 className="mb-2 text-sm font-semibold">
                                Checklist de Documentos
                              </h4>
                              <DocumentChecklist
                                documentos={prest.documentos || []}
                              />
                            </div>
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
