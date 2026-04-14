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

  const chartData = stats?.por_situacao
    ? Object.entries(stats.por_situacao).map(([name, value]) => ({
        name: name.length > 20 ? name.slice(0, 20) + "..." : name,
        quantidade: value,
      }))
    : [];

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>

      {/* Summary cards */}
      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Total Convenios
              </CardTitle>
              <FileText className="size-4 text-indigo-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {(summary?.total_convenios_federal ?? 0) +
                  (summary?.total_convenios_estadual ?? 0)}
              </div>
              <p className="text-xs text-muted-foreground">
                {summary?.total_convenios_federal ?? 0} federal /{" "}
                {summary?.total_convenios_estadual ?? 0} estadual
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Valor Total
              </CardTitle>
              <DollarSign className="size-4 text-green-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {formatCurrency(
                  (summary?.valor_total_federal ?? 0) +
                    (summary?.valor_total_estadual ?? 0)
                )}
              </div>
              <p className="text-xs text-muted-foreground">
                Federal: {formatCurrency(summary?.valor_total_federal)} | Estadual:{" "}
                {formatCurrency(summary?.valor_total_estadual)}
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Alertas de Vigencia
              </CardTitle>
              <AlertTriangle className="size-4 text-orange-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-orange-600">
                {summary?.alertas_vigencia ?? 0}
              </div>
              <p className="text-xs text-muted-foreground">
                Convenios com vigencia proxima
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Editais Acompanhados
              </CardTitle>
              <Search className="size-4 text-blue-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {summary?.editais_acompanhados ?? 0}
              </div>
              <p className="text-xs text-muted-foreground">
                Editais em acompanhamento
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
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="name"
                  tick={{ fontSize: 12 }}
                  interval={0}
                  angle={-30}
                  textAnchor="end"
                  height={80}
                />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="quantidade" fill="#4f46e5" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
