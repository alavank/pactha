"use client";

import React, { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import {
  FileText,
  DollarSign,
  AlertTriangle,
  Search,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  formatCurrency,
  formatDate,
  diasRestantesBadge,
} from "@/lib/utils";
import type { MunicipioSummary, AlertaVigencia, ConvenioStats } from "@/types";

function SkeletonCard() {
  return (
    <Card>
      <CardHeader>
        <div className="h-4 w-24 animate-pulse rounded bg-gray-200" />
      </CardHeader>
      <CardContent>
        <div className="h-8 w-32 animate-pulse rounded bg-gray-200" />
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [summary, setSummary] = useState<MunicipioSummary | null>(null);
  const [alertas, setAlertas] = useState<AlertaVigencia[]>([]);
  const [stats, setStats] = useState<ConvenioStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!municipioId) return;
    setLoading(true);

    Promise.all([
      api.get<MunicipioSummary>(`/municipios/${municipioId}/summary`),
      api.get<AlertaVigencia[]>("/convenios/alertas", {
        params: { municipio_id: municipioId },
      }),
      api.get<ConvenioStats>("/convenios/stats", {
        params: { municipio_id: municipioId },
      }),
    ])
      .then(([summaryRes, alertasRes, statsRes]) => {
        setSummary(summaryRes.data);
        setAlertas(Array.isArray(alertasRes.data) ? alertasRes.data : []);
        setStats(statsRes.data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [municipioId]);

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar o dashboard.
      </div>
    );
  }

  // Smart abbreviation that distinguishes similar prefixes (e.g., "Prestacao de Contas Aprovada" vs "Concluida")
  const abbreviateLabel = (full: string): string => {
    if (full.length <= 22) return full;
    // Take first word + last meaningful word
    const words = full.split(/\s+/);
    if (words.length <= 2) return full.slice(0, 20) + "...";
    // Use first word + last word (skip common middle words)
    const skipWords = new Set(["de", "do", "da", "dos", "das", "e"]);
    const significantWords = words.filter(w => !skipWords.has(w.toLowerCase()));
    if (significantWords.length >= 2) {
      const last = significantWords[significantWords.length - 1];
      return `${significantWords[0]}... ${last}`;
    }
    return full.slice(0, 20) + "...";
  };

  const chartData = stats?.por_situacao
    ? Object.entries(stats.por_situacao)
        .sort((a, b) => b[1] - a[1])
        .map(([name, value]) => ({
          name: abbreviateLabel(name),
          fullName: name,
          quantidade: value,
        }))
    : [];

  // Color palette for different situacao
  const getBarColor = (sit: string) => {
    const s = sit.toLowerCase();
    if (s.includes("aprovada")) return "#16a34a";
    if (s.includes("concluida") || s.includes("concluído")) return "#059669";
    if (s.includes("recurso")) return "#0ea5e9";
    if (s.includes("vigor") || s.includes("execu")) return "#2563eb";
    if (s.includes("anulado")) return "#dc2626";
    if (s.includes("cancelado")) return "#ef4444";
    if (s.includes("rescindido")) return "#f97316";
    if (s.includes("proposta")) return "#a855f7";
    return "#64748b";
  };

  return (
    <div className="space-y-6">
      {/* Cabecalho institucional */}
      <div className="border-b border-slate-200 pb-4">
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
          <span>Inicio</span>
          <span>›</span>
          <span className="text-slate-700">Painel de Monitoramento</span>
        </div>
        <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
          Painel de Monitoramento
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Visao consolidada de convenios, emendas e indicadores do municipio
        </p>
      </div>

      {/* Summary cards - estilo prefeitura */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card className="border-l-4 border-l-blue-700 hover:shadow-md transition-shadow">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                Total de Convenios
              </CardTitle>
              <div className="size-9 rounded-md bg-blue-50 flex items-center justify-center">
                <FileText className="size-4 text-blue-700" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-slate-900">
                {(summary?.total_convenios_federal ?? 0) +
                  (summary?.total_convenios_estadual ?? 0)}
              </div>
              <div className="flex gap-3 mt-2 text-xs">
                <span className="text-slate-600">
                  <strong className="text-blue-700">{summary?.total_convenios_federal ?? 0}</strong> federal
                </span>
                <span className="text-slate-600">
                  <strong className="text-blue-700">{summary?.total_convenios_estadual ?? 0}</strong> estadual
                </span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-green-700 hover:shadow-md transition-shadow">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                Valor Total
              </CardTitle>
              <div className="size-9 rounded-md bg-green-50 flex items-center justify-center">
                <DollarSign className="size-4 text-green-700" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-slate-900">
                {formatCurrency(
                  (summary?.valor_total_federal ?? 0) +
                    (summary?.valor_total_estadual ?? 0)
                )}
              </div>
              <p className="text-xs text-slate-500 mt-2 leading-relaxed">
                Fed: {formatCurrency(summary?.valor_total_federal)}
                <br />
                Est: {formatCurrency(summary?.valor_total_estadual)}
              </p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-amber-600 hover:shadow-md transition-shadow">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                Alertas de Vigencia
              </CardTitle>
              <div className="size-9 rounded-md bg-amber-50 flex items-center justify-center">
                <AlertTriangle className="size-4 text-amber-600" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-amber-700">
                {summary?.alertas_vigencia ?? 0}
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Vencendo nos proximos 120 dias
              </p>
            </CardContent>
          </Card>

          <Card className="border-l-4 border-l-cyan-700 hover:shadow-md transition-shadow">
            <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
              <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                Editais Acompanhados
              </CardTitle>
              <div className="size-9 rounded-md bg-cyan-50 flex items-center justify-center">
                <Search className="size-4 text-cyan-700" />
              </div>
            </CardHeader>
            <CardContent>
              <div className="text-3xl font-bold text-slate-900">
                {summary?.editais_acompanhados ?? 0}
              </div>
              <p className="text-xs text-slate-500 mt-2">
                Em monitoramento ativo
              </p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Alerts section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <AlertTriangle className="size-5 text-orange-500" />
            Alertas de Vigencia
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-gray-100" />
              ))}
            </div>
          ) : alertas.length === 0 ? (
            <p className="py-4 text-center text-muted-foreground">
              Nenhum alerta de vigencia encontrado.
            </p>
          ) : (
            <div className="space-y-2">
              {alertas.slice(0, 10).map((alerta) => (
                <div
                  key={alerta.id}
                  className="flex items-center justify-between rounded-lg border p-3"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm">
                        {alerta.nr_convenio || alerta.nr_sigcon || "-"}
                      </span>
                      <Badge className="text-xs uppercase" variant="secondary">
                        {alerta.esfera}
                      </Badge>
                    </div>
                    <p className="truncate text-sm text-muted-foreground">
                      {alerta.objeto || alerta.orgao_concedente || "-"}
                    </p>
                  </div>
                  <div className="flex items-center gap-3 ml-4">
                    <span className="text-sm text-muted-foreground">
                      {formatDate(alerta.dt_fim_vigencia)}
                    </span>
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${diasRestantesBadge(
                        alerta.dias_restantes
                      )}`}
                    >
                      {alerta.dias_restantes != null
                        ? alerta.dias_restantes < 0
                          ? `${Math.abs(alerta.dias_restantes)}d vencido`
                          : `${alerta.dias_restantes}d restantes`
                        : "-"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Chart */}
      <Card>
        <CardHeader>
          <CardTitle>Convenios por Situacao</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="h-64 animate-pulse rounded bg-gray-100" />
          ) : chartData.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              Nenhum dado encontrado.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={340}>
              <BarChart data={chartData} margin={{ top: 10, right: 20, bottom: 80, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 11, fill: "#475569" }}
                  interval={0}
                  angle={-30}
                  textAnchor="end"
                  height={100}
                />
                <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#475569" }} />
                <Tooltip
                  formatter={(value, _name, props) => [`${value} convenios`, props.payload.fullName]}
                  contentStyle={{ borderRadius: 8, border: "1px solid #cbd5e1" }}
                />
                <Bar dataKey="quantidade" radius={[6, 6, 0, 0]}>
                  {chartData.map((entry, idx) => (
                    <Cell key={idx} fill={getBarColor(entry.fullName)} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
