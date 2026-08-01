"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  FileText,
  DollarSign,
  AlertTriangle,
  ClipboardList,
  Bell,
  ArrowRight,
  BarChart3,
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
  LabelList,
} from "recharts";
import api from "@/lib/api";
import { MultiSelect } from "@/components/ui/multi-select";
import { anosOpcoes, atalhosAnos, resumoAnos } from "@/lib/periodo";
import { Badge } from "@/components/ui/badge";
import {
  formatCurrency,
  formatDate,
  diasRestantesBadge,
} from "@/lib/utils";
import type { MunicipioSummary, AlertaVigencia, ConvenioStats } from "@/types";
import { BiScopeProvider } from "@/contexts/BiScopeContext";
import { PainelIndicadores } from "@/components/bi/PainelIndicadores";

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
    estadual: "bg-primary/10 text-primary border-primary/30",
    federal: "bg-info/15 text-info border-info/30",
    ambos: "bg-base-200 text-base-content/70 border-base-300",
  };
  const labels: Record<string, string> = {
    estadual: "Estadual",
    federal: "Federal",
    ambos: "Est + Fed",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${styles[tipo]}`}
    >
      {labels[tipo]}
    </span>
  );
}

// Card de metrica padronizado: icone (caixa arredondada) -> nome -> valor ->
// esfera (Estadual/Federal) embaixo. Layout vertical uniforme em todos os KPIs.
function MetricCard({
  icon: Icon,
  iconBg,
  iconText,
  label,
  value,
  valueClass = "text-2xl text-base-content",
  right,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  iconBg: string;
  iconText: string;
  label: string;
  value: React.ReactNode;
  valueClass?: string;
  right?: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`flex flex-col rounded-2xl border border-base-300 bg-base-100 p-5 transition-all ${
        onClick ? "cursor-pointer hover:-translate-y-0.5 hover:shadow-lg hover:shadow-base-300/40" : ""
      }`}
    >
      <div className={`flex size-11 items-center justify-center rounded-xl ${iconBg}`}>
        <Icon className={`size-5 ${iconText}`} />
      </div>
      <p className="mt-4 text-xs font-medium text-base-content/50">{label}</p>
      <h4 className={`mt-1.5 font-bold leading-tight break-words ${valueClass}`}>{value}</h4>
      {right && <div className="mt-3">{right}</div>}
    </div>
  );
}

// Painel de secao (lista/grafico) no estilo TailAdmin.
function Section({
  title,
  icon: Icon,
  iconClass = "text-primary",
  count,
  children,
}: {
  title: string;
  icon?: React.ComponentType<{ className?: string }>;
  iconClass?: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-base-300 bg-base-100">
      <div className="flex items-center gap-2 border-b border-base-300 px-5 py-4">
        {Icon && <Icon className={`size-5 ${iconClass}`} />}
        <h3 className="text-base font-semibold text-base-content">{title}</h3>
        {count != null && count > 0 && (
          <span className="ml-1 rounded-full bg-base-200 px-2 py-0.5 text-xs font-semibold text-base-content/70">
            {count}
          </span>
        )}
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

/** Rótulo do eixo do gráfico, quebrando em até duas linhas.
 *
 *  O recharts não quebra texto de tick sozinho: ou cabe, ou vaza por cima do
 *  gráfico. Por isso existia um abreviador que cortava em 22 caracteres e
 *  transformava "Prestação de contas enviada para análise" em
 *  "Prestação... análise" — numa TV de gabinete, ilegível.
 *
 *  Duas linhas de ~26 caracteres cobrem todas as situações do SIGCON. O que
 *  ainda não couber ganha reticências, mas isso passou a ser exceção em vez
 *  de regra, e o nome inteiro continua no tooltip. */
function TickQuebrado({ x, y, payload }: {
  x?: number; y?: number; payload?: { value?: string };
}) {
  const texto = String(payload?.value ?? "");
  const MAX = 26;
  const linhas: string[] = [];
  let atual = "";
  for (const palavra of texto.split(/\s+/)) {
    if (!atual) atual = palavra;
    else if ((atual + " " + palavra).length <= MAX) atual += " " + palavra;
    else { linhas.push(atual); atual = palavra; }
    if (linhas.length === 2) break;
  }
  if (atual && linhas.length < 2) linhas.push(atual);
  // Sobrou texto? Marca na última linha, em vez de sumir em silêncio.
  const usado = linhas.join(" ").length;
  if (usado < texto.replace(/\s+/g, " ").length) {
    linhas[linhas.length - 1] = linhas[linhas.length - 1].slice(0, MAX - 1) + "…";
  }
  const dy = linhas.length > 1 ? -4 : 4;
  return (
    <text x={x} y={y} textAnchor="end" fill="var(--bi-faint)" fontSize={11}>
      {linhas.map((l, i) => (
        <tspan key={i} x={x} dy={i === 0 ? dy : 13}>{l}</tspan>
      ))}
    </text>
  );
}

function MetricSkeleton() {
  return (
    <div className="rounded-2xl border border-base-300 bg-base-100 p-5">
      <div className="size-11 animate-pulse rounded-xl bg-base-300" />
      <div className="mt-4 h-3 w-24 animate-pulse rounded bg-base-200" />
      <div className="mt-3 h-7 w-20 animate-pulse rounded bg-base-300" />
    </div>
  );
}

// Com o modulo BI ligado, /dashboard E o Painel de Indicadores — nao existem
// mais dois menus (Dashboard + Painel de Indicadores) para o mesmo publico.
// Sem a flag, segue o dashboard operacional de sempre (freitas/trust).
const BI_ON = process.env.NEXT_PUBLIC_BI_MODULE === "1";

export default function DashboardPage() {
  if (BI_ON) {
    return (
      <BiScopeProvider>
        <PainelIndicadores />
      </BiScopeProvider>
    );
  }
  return <DashboardOperacional />;
}

function DashboardOperacional() {
  const router = useRouter();
  const { municipioId } = useMunicipio();
  // Era um <select> NATIVO de um ano so — o unico do app fora do padrao, e o
  // que fica na tela que o prefeito abre primeiro.
  const [anosSel, setAnosSel] = useState<string[]>([]);

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
    const anoP = anosSel.length ? { anos: anosSel } : {};

    Promise.all([
      api.get<MunicipioSummary>(`/municipios/${municipioId}/summary`, { params: { ...anoP } }),
      api.get<AlertaVigencia[]>("/convenios/alertas", { params: { municipio_id: municipioId, ...anoP } }),
      api.get<ConvenioStats>("/convenios/stats", { params: { municipio_id: municipioId, ...anoP } }),
      api.get<AlertaVigencia[]>("/convenios/prestacao-contas", { params: { municipio_id: municipioId, ...anoP } }),
      api.get<{ items: StatusChange[] }>("/status-changes", { params: { municipio_id: municipioId, days: 30 } }),
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
  }, [municipioId, anosSel]);

  const fonteBadge = (f: string): { label: string; cls: string } => {
    if (f === "fns") return { label: "FNS", cls: "bg-error/15 text-error border-error/30" };
    if (f === "voluntaria") return { label: "Federal", cls: "bg-info/15 text-info border-info/30" };
    return { label: "Estadual", cls: "bg-primary/10 text-primary border-primary/30" };
  };
  const fmtDataHora = (iso?: string): string => {
    if (!iso) return "-";
    const d = new Date(iso);
    return isNaN(d.getTime()) ? "-" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  };
  const statusCor = (s: string): string => {
    const t = (s || "").toLowerCase();
    if (t.includes("aprovad") || t.includes("execu") || t.includes("vigor") || t.includes("conclu")) return "text-success";
    if (t.includes("rejeitad") || t.includes("anulad") || t.includes("cancelad") || t.includes("rescind") || t.includes("impedi")) return "text-error";
    if (t.includes("análise") || t.includes("an") || t.includes("complementa")) return "text-warning";
    return "text-base-content/70";
  };

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar o dashboard.
      </div>
    );
  }

  // O rotulo do grafico NAO e mais abreviado. `abbreviateLabel` cortava em 22
  // caracteres e produzia coisas como "Prestacao... analise" — o gestor lia o
  // grafico na TV e nao sabia qual situacao era qual. O nome inteiro cabe
  // quebrando em duas linhas num eixo mais largo (ver TickQuebrado).
  const chartData = stats?.por_situacao
    ? Object.entries(stats.por_situacao)
        .sort((a, b) => b[1] - a[1])
        .map(([name, value]) => ({ name, fullName: name, quantidade: value }))
    : [];

  /** Cor da barra por situacao.
   *
   *  Eram sete hexadecimais CRAVADOS da paleta antiga ("Base", violeta) — nao
   *  seguiam o tema, entao no escuro continuavam os mesmos sete tons pensados
   *  para fundo branco. Agora saem dos tokens da identidade, que trocam de
   *  valor junto com o tema.
   *
   *  Grafico e o unico lugar do sistema onde varias cores convivem de
   *  proposito: aqui a cor E o dado, nao enfeite. Por isso usa a serie
   *  `--bi-c1..c5` do Painel, que foi calibrada para isso. */
  const getBarColor = (sit: string) => {
    const s = sit.toLowerCase();
    if (s.includes("pago")) return "var(--bi-ok)";
    if (s.includes("aprovad") || s.includes("conclu")) return "var(--bi-c3)";
    if (s.includes("vigor") || s.includes("execu")) return "var(--bi-c4)";
    if (s.includes("empenhad")) return "var(--bi-accent)";
    if (s.includes("anulad") || s.includes("cancelad") || s.includes("rescind") || s.includes("rejeitad") || s.includes("impedi"))
      return "var(--bi-crit)";
    if (s.includes("analise") || s.includes("análise") || s.includes("pendente") || s.includes("cadastr") ||
        s.includes("checklist") || s.includes("processo") || s.includes("adequa") || s.includes("jur") || s.includes("autorizad"))
      return "var(--bi-c2)";
    if (s.includes("encerrad")) return "var(--bi-faint)";
    return "var(--bi-line-strong)";
  };

  const secLabel = "text-xs font-semibold uppercase tracking-wider text-base-content/50 mb-3";
  const rowCls = "flex items-center justify-between rounded-xl border border-base-300 p-3 transition-colors hover:bg-base-200/60";

  return (
    <div className="space-y-6">
      {/* Cabecalho */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 flex items-center gap-1.5 text-xs text-base-content/50">
            <span>Início</span>
            <span>›</span>
            <span className="text-base-content/70">Painel de Monitoramento</span>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-base-content">Painel de Monitoramento</h1>
          <p className="mt-1 text-sm text-base-content/60">
            Visão consolidada de convênios, emendas e indicadores do município
          </p>
        </div>
        {/* Filtro de ano — os KPIs, o gráfico e os alertas respeitam a seleção.
            Mesmo componente e mesmos atalhos do resto do sistema: "Mandato
            atual" aqui é o mandato do PREFEITO (ver @/lib/periodo). */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-medium text-base-content/60">Anos</label>
          <MultiSelect
            opcoes={anosOpcoes(2010)}
            valor={anosSel}
            onChange={setAnosSel}
            atalhos={atalhosAnos()}
            formatarResumo={resumoAnos}
            placeholder="Todos"
            rotuloTodos="Todos"
            ariaLabel="Anos do painel"
            className="w-44"
          />
        </div>
      </div>

      {/* KPIs */}
      {loading ? (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <MetricSkeleton key={i} />)}
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => <MetricSkeleton key={i} />)}
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Totais e Valores */}
          <div>
            <h2 className={secLabel}>Totais e Valores</h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                icon={FileText} iconBg="bg-primary/10" iconText="text-primary"
                label="Total de Convênios (SIGCON)"
                value={summary?.total_convenios_estadual ?? 0}
                valueClass="text-3xl text-base-content"
                right={<EsferaTag tipo="estadual" />}
                onClick={() => goConvenios()}
              />
              <MetricCard
                icon={FileText} iconBg="bg-info/15" iconText="text-info"
                label="TransfereGov Voluntárias"
                value={summary?.total_voluntarias ?? 0}
                valueClass="text-3xl text-base-content"
                right={<EsferaTag tipo="federal" />}
                onClick={() => goVoluntarias()}
              />
              <MetricCard
                icon={DollarSign} iconBg="bg-success/15" iconText="text-success"
                label="Valor Estadual"
                value={formatCurrency(summary?.valor_total_estadual ?? 0)}
                valueClass="text-lg text-base-content"
                right={<EsferaTag tipo="estadual" />}
              />
              <MetricCard
                icon={DollarSign} iconBg="bg-success/15" iconText="text-success"
                label="Valor Federal"
                value={formatCurrency(summary?.valor_total_federal ?? 0)}
                valueClass="text-lg text-base-content"
                right={<EsferaTag tipo="federal" />}
              />
            </div>
          </div>

          {/* Vencimentos e Prestacao */}
          <div>
            <h2 className={secLabel}>Vencimentos e Prestação de Contas</h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                icon={AlertTriangle} iconBg="bg-error/15" iconText="text-error"
                label="Vence em 60 dias"
                value={summary?.alertas_vigencia_60d ?? 0}
                valueClass="text-3xl text-error"
                right={<EsferaTag tipo="ambos" />}
                onClick={() => goConvenios("vence60")}
              />
              <MetricCard
                icon={AlertTriangle} iconBg="bg-warning/15" iconText="text-warning"
                label="Vence em 120 dias"
                value={summary?.alertas_vigencia ?? 0}
                valueClass="text-3xl text-warning"
                right={<EsferaTag tipo="ambos" />}
                onClick={() => goConvenios("vence120")}
              />
              <MetricCard
                icon={ClipboardList} iconBg="bg-info/15" iconText="text-info"
                label="Prest. Contas Estadual"
                value={summary?.alertas_prestacao_contas_estadual ?? 0}
                valueClass="text-3xl text-info"
                right={<EsferaTag tipo="estadual" />}
                onClick={() => goConvenios("prestacao")}
              />
              <MetricCard
                icon={ClipboardList} iconBg="bg-info/15" iconText="text-info"
                label="Prest. Contas Federal"
                value={summary?.alertas_prestacao_contas_federal ?? 0}
                valueClass="text-3xl text-info"
                right={<EsferaTag tipo="federal" />}
                onClick={() => goVoluntarias("prestacao")}
              />
            </div>
          </div>
        </div>
      )}

      {/* Mudanças de Status */}
      <Section title="Mudanças de Status (últimos 30 dias)" icon={Bell} count={mudancas.length}>
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-14 animate-pulse rounded-xl bg-base-200" />)}
          </div>
        ) : mudancas.length === 0 ? (
          <p className="py-6 text-center text-sm text-base-content/50">
            Nenhuma mudança de status detectada nas últimas atualizações.
          </p>
        ) : (
          <div className="space-y-2">
            {mudancas.slice(0, 15).map((m) => {
              const fb = fonteBadge(m.fonte);
              return (
                <div key={m.id} className={rowCls}>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-base-content">{m.ref || "-"}</span>
                      <span className={`inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide ${fb.cls}`}>
                        {fb.label}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-sm leading-snug text-base-content/60">{m.objeto || m.orgao || "-"}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <span className={`${statusCor(m.status_anterior)} line-through opacity-70`}>{m.status_anterior || "—"}</span>
                      <ArrowRight className="size-3 shrink-0 text-base-content/40" />
                      <span className={`font-semibold ${statusCor(m.status_novo)}`}>{m.status_novo || "—"}</span>
                    </div>
                  </div>
                  <span className="ml-4 shrink-0 text-xs text-base-content/50">{fmtDataHora(m.changed_at)}</span>
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* Alertas de Vigencia */}
      <Section title="Alertas de Vigência" icon={AlertTriangle} iconClass="text-warning">
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-base-200" />)}
          </div>
        ) : alertas.length === 0 ? (
          <p className="py-6 text-center text-sm text-base-content/50">Nenhum alerta de vigência encontrado.</p>
        ) : (
          <div className="space-y-2">
            {alertas.slice(0, 10).map((alerta) => (
              <div key={alerta.id} className={rowCls}>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-base-content">{alerta.nr_convenio || alerta.nr_sigcon || "-"}</span>
                    <Badge className="text-xs uppercase" variant="secondary">{alerta.esfera}</Badge>
                  </div>
                  <p className="line-clamp-2 text-sm leading-snug text-base-content/60">{alerta.objeto || alerta.orgao_concedente || "-"}</p>
                </div>
                <div className="ml-4 flex items-center gap-3">
                  <span className="text-sm text-base-content/60">{formatDate(alerta.dt_fim_vigencia)}</span>
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${diasRestantesBadge(alerta.dias_restantes)}`}>
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
      </Section>

      {/* Prestacao de Contas vencidos +90d */}
      {!loading && prestacao.length > 0 && (
        <Section title="Prestação de Contas (vencidos há +90 dias)" icon={ClipboardList} iconClass="text-info" count={prestacao.length}>
          <div className="space-y-2">
            {prestacao.slice(0, 10).map((alerta, idx) => (
              <div key={`${alerta.esfera}-${alerta.id}-${idx}`} className="flex items-center justify-between rounded-xl border border-info/40 bg-info/10 p-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-base-content">{alerta.nr_convenio || alerta.nr_sigcon || "-"}</span>
                    <Badge className="text-xs uppercase" variant="secondary">{alerta.esfera}</Badge>
                  </div>
                  <p className="line-clamp-2 text-sm leading-snug text-base-content/60">{alerta.objeto || alerta.orgao_concedente || "-"}</p>
                </div>
                <div className="ml-4 flex items-center gap-3">
                  <span className="text-sm text-base-content/60">{formatDate(alerta.dt_fim_vigencia)}</span>
                  <span className="inline-flex items-center whitespace-nowrap rounded-full bg-info/15 px-2.5 py-0.5 text-xs font-medium text-info">
                    {alerta.dias_restantes != null ? `${Math.abs(alerta.dias_restantes)}d vencido` : "-"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Grafico */}
      <Section title="Convênios por Situação" icon={BarChart3}>
        {loading ? (
          <div className="h-64 animate-pulse rounded-xl bg-base-200" />
        ) : chartData.length === 0 ? (
          <p className="py-8 text-center text-sm text-base-content/50">Nenhum dado encontrado.</p>
        ) : (
          /* 46px por barra em vez de 38: a linha do eixo agora pode ter duas
             linhas de texto. O cartao cresce um pouco e passa a ser legivel. */
          <ResponsiveContainer width="100%" height={Math.max(260, chartData.length * 46)}>
            <BarChart data={chartData} layout="vertical" margin={{ top: 4, right: 44, bottom: 4, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--bi-line)" horizontal={false} />
              <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: "var(--bi-faint)" }} />
              <YAxis
                type="category"
                dataKey="name"
                width={230}
                interval={0}
                tick={<TickQuebrado />}
              />
              <Tooltip
                formatter={(value, _name, props) => [`${value} convênios`, props.payload.fullName]}
                contentStyle={{ borderRadius: 12, border: "1px solid var(--bi-line)" }}
                cursor={{ fill: "color-mix(in oklab, var(--bi-accent) 8%, transparent)" }}
              />
              <Bar dataKey="quantidade" radius={[0, 6, 6, 0]} barSize={18}>
                {chartData.map((entry, idx) => (
                  <Cell key={idx} fill={getBarColor(entry.fullName)} />
                ))}
                <LabelList dataKey="quantidade" position="right" style={{ fontSize: 11, fill: "var(--bi-faint)", fontWeight: 600 }} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </Section>
    </div>
  );
}
