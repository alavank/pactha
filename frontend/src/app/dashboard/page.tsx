"use client";

import React, { useEffect, useState, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  FileText,
  DollarSign,
  AlertTriangle,
  ClipboardList,
  Bell,
  ArrowRight,
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

interface StatusChange {
  id: number;
  fonte: string;
  ref: string;
  orgao: string;
  objeto: string;
  status_anterior: string;
  status_novo: string;
  changed_at: string;
}

function EsferaTag({ tipo }: { tipo: "estadual" | "federal" | "ambos" }) {
  const styles: Record<string, string> = {
    estadual: "bg-blue-50 text-blue-700 border-blue-200",
    federal: "bg-cyan-50 text-cyan-700 border-cyan-200",
    ambos: "bg-slate-100 text-slate-600 border-slate-200",
  };
  const labels: Record<string, string> = {
    estadual: "Estadual",
    federal: "Federal",
    ambos: "Estadual + Federal",
  };
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${styles[tipo]}`}
    >
      {labels[tipo]}
    </span>
  );
}

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
  const router = useRouter();
  const municipioId = searchParams.get("municipio_id");

  // Navega para os lançamentos (Convênios SIGCON) com o filtro de vigência do KPI
  const goConvenios = (vigencia?: string) => {
    if (!municipioId) return;
    const qs = new URLSearchParams({ municipio_id: municipioId });
    if (vigencia) qs.set("vigencia", vigencia);
    router.push(`/dashboard/convenios?${qs.toString()}`);
  };
  const goVoluntarias = (vigencia?: string) => {
    if (!municipioId) return;
    const qs = new URLSearchParams({ municipio_id: municipioId });
    if (vigencia) qs.set("vigencia", vigencia);
    router.push(`/dashboard/transferegov-voluntarias?${qs.toString()}`);
  };

  const [summary, setSummary] = useState<MunicipioSummary | null>(null);
  const [alertas, setAlertas] = useState<AlertaVigencia[]>([]);
  const [prestacao, setPrestacao] = useState<AlertaVigencia[]>([]);
  const [stats, setStats] = useState<ConvenioStats | null>(null);
  const [mudancas, setMudancas] = useState<StatusChange[]>([]);
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
      api.get<AlertaVigencia[]>("/convenios/prestacao-contas", {
        params: { municipio_id: municipioId },
      }),
      api.get<{ items: StatusChange[] }>("/status-changes", {
        params: { municipio_id: municipioId, days: 30 },
      }),
    ])
      .then(([summaryRes, alertasRes, statsRes, prestacaoRes, mudancasRes]) => {
        setSummary(summaryRes.data);
        setAlertas(Array.isArray(alertasRes.data) ? alertasRes.data : []);
        setStats(statsRes.data);
        setPrestacao(Array.isArray(prestacaoRes.data) ? prestacaoRes.data : []);
        setMudancas(mudancasRes.data?.items ?? []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [municipioId]);

  const fonteBadge = (f: string): { label: string; cls: string } => {
    if (f === "fns") return { label: "FNS", cls: "bg-rose-50 text-rose-700 border-rose-200" };
    if (f === "voluntaria") return { label: "Federal", cls: "bg-cyan-50 text-cyan-700 border-cyan-200" };
    return { label: "Estadual (SIGCON)", cls: "bg-blue-50 text-blue-700 border-blue-200" };
  };
  const statusCor = (s: string): string => {
    const t = (s || "").toLowerCase();
    if (t.includes("aprovad") || t.includes("execu") || t.includes("vigor") || t.includes("conclu")) return "text-green-700";
    if (t.includes("rejeitad") || t.includes("anulad") || t.includes("cancelad") || t.includes("rescind") || t.includes("impedi")) return "text-red-700";
    if (t.includes("análise") || t.includes("an") || t.includes("complementa")) return "text-amber-700";
    return "text-slate-700";
  };

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
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Grupo 1: Totais e Valores */}
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
              Totais e Valores
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card
                onClick={() => goConvenios()}
                className="border-l-4 border-l-blue-700 hover:shadow-md transition-shadow cursor-pointer"
              >
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Total de Convenios (SIGCON)
                  </CardTitle>
                  <div className="size-9 rounded-md bg-blue-50 flex items-center justify-center">
                    <FileText className="size-4 text-blue-700" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-slate-900">
                    {summary?.total_convenios_estadual ?? 0}
                  </div>
                  <div className="mt-2"><EsferaTag tipo="estadual" /></div>
                </CardContent>
              </Card>

              <Card
                onClick={() => goVoluntarias()}
                className="border-l-4 border-l-cyan-700 hover:shadow-md transition-shadow cursor-pointer"
              >
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    TransfereGov Voluntarias
                  </CardTitle>
                  <div className="size-9 rounded-md bg-cyan-50 flex items-center justify-center">
                    <FileText className="size-4 text-cyan-700" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-slate-900">
                    {summary?.total_voluntarias ?? 0}
                  </div>
                  <div className="mt-2"><EsferaTag tipo="federal" /></div>
                </CardContent>
              </Card>

              <Card className="border-l-4 border-l-green-700 hover:shadow-md transition-shadow">
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Valor Estadual
                  </CardTitle>
                  <div className="size-9 rounded-md bg-green-50 flex items-center justify-center">
                    <DollarSign className="size-4 text-green-700" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-xl font-bold text-slate-900 break-words leading-tight">
                    {formatCurrency(summary?.valor_total_estadual ?? 0)}
                  </div>
                  <div className="mt-2"><EsferaTag tipo="estadual" /></div>
                </CardContent>
              </Card>

              <Card className="border-l-4 border-l-teal-600 hover:shadow-md transition-shadow">
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Valor Federal
                  </CardTitle>
                  <div className="size-9 rounded-md bg-teal-50 flex items-center justify-center">
                    <DollarSign className="size-4 text-teal-600" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-xl font-bold text-slate-900 break-words leading-tight">
                    {formatCurrency(summary?.valor_total_federal ?? 0)}
                  </div>
                  <div className="mt-2"><EsferaTag tipo="federal" /></div>
                </CardContent>
              </Card>
            </div>
          </div>

          {/* Grupo 2: Vencimentos e Prestacao de Contas */}
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">
              Vencimentos e Prestacao de Contas
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Card
                onClick={() => goConvenios("vence60")}
                className="border-l-4 border-l-red-600 hover:shadow-md transition-shadow cursor-pointer"
              >
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Vence em 60 dias
                  </CardTitle>
                  <div className="size-9 rounded-md bg-red-50 flex items-center justify-center">
                    <AlertTriangle className="size-4 text-red-600" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-red-700">
                    {summary?.alertas_vigencia_60d ?? 0}
                  </div>
                  <div className="mt-2"><EsferaTag tipo="ambos" /></div>
                </CardContent>
              </Card>

              <Card
                onClick={() => goConvenios("vence120")}
                className="border-l-4 border-l-amber-600 hover:shadow-md transition-shadow cursor-pointer"
              >
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Vence em 120 dias
                  </CardTitle>
                  <div className="size-9 rounded-md bg-amber-50 flex items-center justify-center">
                    <AlertTriangle className="size-4 text-amber-600" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-amber-700">
                    {summary?.alertas_vigencia ?? 0}
                  </div>
                  <div className="mt-2"><EsferaTag tipo="ambos" /></div>
                </CardContent>
              </Card>

              <Card
                onClick={() => goConvenios("prestacao")}
                className="border-l-4 border-l-purple-700 hover:shadow-md transition-shadow cursor-pointer"
              >
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Prest. Contas Estadual
                  </CardTitle>
                  <div className="size-9 rounded-md bg-purple-50 flex items-center justify-center">
                    <ClipboardList className="size-4 text-purple-700" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-purple-700">
                    {summary?.alertas_prestacao_contas_estadual ?? 0}
                  </div>
                  <div className="mt-2 flex items-center gap-1.5">
                    <EsferaTag tipo="estadual" />
                    <span className="text-[10px] text-slate-400">vencidos +90d</span>
                  </div>
                </CardContent>
              </Card>

              <Card
                onClick={() => goVoluntarias("prestacao")}
                className="border-l-4 border-l-fuchsia-700 hover:shadow-md transition-shadow cursor-pointer"
              >
                <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
                  <CardTitle className="text-[11px] font-semibold uppercase tracking-wider text-slate-600">
                    Prest. Contas Federal
                  </CardTitle>
                  <div className="size-9 rounded-md bg-fuchsia-50 flex items-center justify-center">
                    <ClipboardList className="size-4 text-fuchsia-700" />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="text-3xl font-bold text-fuchsia-700">
                    {summary?.alertas_prestacao_contas_federal ?? 0}
                  </div>
                  <div className="mt-2 flex items-center gap-1.5">
                    <EsferaTag tipo="federal" />
                    <span className="text-[10px] text-slate-400">vencidos +90d</span>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      )}

      {/* Mudanças de status detectadas nas atualizações diárias */}
      <Card className="border-l-4 border-l-indigo-600">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Bell className="size-5 text-indigo-600" />
            Mudanças de Status (últimos 30 dias)
            {mudancas.length > 0 && (
              <Badge variant="secondary" className="ml-1">{mudancas.length}</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded bg-gray-100" />
              ))}
            </div>
          ) : mudancas.length === 0 ? (
            <p className="py-4 text-center text-muted-foreground">
              Nenhuma mudança de status detectada nas últimas atualizações.
            </p>
          ) : (
            <div className="space-y-2">
              {mudancas.slice(0, 15).map((m) => {
                const fb = fonteBadge(m.fonte);
                return (
                  <div key={m.id} className="flex items-center justify-between rounded-lg border p-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{m.ref || "-"}</span>
                        <span className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${fb.cls}`}>
                          {fb.label}
                        </span>
                      </div>
                      <p className="truncate text-sm text-muted-foreground">
                        {m.objeto || m.orgao || "-"}
                      </p>
                      <div className="mt-1 flex items-center gap-2 text-xs flex-wrap">
                        <span className={`${statusCor(m.status_anterior)} line-through opacity-70`}>
                          {m.status_anterior || "—"}
                        </span>
                        <ArrowRight className="size-3 text-slate-400 shrink-0" />
                        <span className={`font-semibold ${statusCor(m.status_novo)}`}>
                          {m.status_novo || "—"}
                        </span>
                      </div>
                    </div>
                    <span className="text-xs text-muted-foreground ml-4 shrink-0">
                      {formatDate(m.changed_at)}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

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

      {/* Prestacao de Contas: convenios vencidos ha +90 dias */}
      {!loading && prestacao.length > 0 && (
        <Card className="border-l-4 border-l-purple-700">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardList className="size-5 text-purple-700" />
              Prestacao de Contas (vencidos ha +90 dias)
              <Badge variant="secondary" className="ml-1">{prestacao.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {prestacao.slice(0, 10).map((alerta, idx) => (
                <div
                  key={`${alerta.esfera}-${alerta.id}-${idx}`}
                  className="flex items-center justify-between rounded-lg border border-purple-100 bg-purple-50/40 p-3"
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
                    <span className="inline-flex items-center rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-800 whitespace-nowrap">
                      {alerta.dias_restantes != null
                        ? `${Math.abs(alerta.dias_restantes)}d vencido`
                        : "-"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

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
