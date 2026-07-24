"use client";
import { useEffect, useState } from "react";
import {
  Wallet, Landmark, Coins, FileWarning, CalendarClock,
  ShieldCheck, ShieldAlert, Users, History, HeartPulse, TrendingUp,
} from "lucide-react";
import { useBiScope } from "@/contexts/BiScopeContext";
import { getOverview, getNarrativa, Overview, isRollup } from "@/lib/bi";
import { Card, SectionHead, MetricCard, AiCard, Pill, EmptyState } from "@/components/bi/ui";
import { Gauge, SegBar, FonteStack, RankingBars, StatBars } from "@/components/bi/charts";
import { formatCurrencyShort, formatInt, formatDate } from "@/lib/bi-format";

export default function BiOverviewPage() {
  const { scope, municipioId, isConsolidado, ano } = useBiScope();
  const [ov, setOv] = useState<Overview | null>(null);
  const [narr, setNarr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!scope) return; // escopo ainda nao resolvido pelo shell
    let cancel = false;
    setLoading(true);
    setErr(null);
    getOverview(municipioId, ano)
      .then((d) => {
        if (!cancel) {
          setOv(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancel) {
          setErr("Não foi possível carregar os indicadores.");
          setLoading(false);
        }
      });
    setNarr(null);
    getNarrativa(municipioId, ano)
      .then((n) => {
        if (!cancel) setNarr(n.disponivel ? n.texto : null);
      })
      .catch(() => {});
    return () => {
      cancel = true;
    };
  }, [scope, municipioId, isConsolidado, ano]);

  if (loading && !ov) return <OverviewSkeleton />;
  if (err) return <EmptyState>{err}</EmptyState>;
  if (!ov) return <EmptyState>Selecione um escopo para ver os indicadores.</EmptyState>;

  const k = ov.kpis;
  const totalCaptado = (k.valor_total_estadual || 0) + (k.valor_total_federal || 0);
  const escopoLabel = ov.consolidado
    ? `${ov.municipios_count} município(s)`
    : "município selecionado";

  return (
    <div className="flex flex-col gap-5">
      {/* Narrativa executiva (IA) */}
      {narr && <AiCard>{narr}</AiCard>}

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <MetricCard
          icon={Wallet}
          tone="primary"
          label="Total captado"
          value={formatCurrencyShort(totalCaptado)}
          sub={escopoLabel}
        />
        <MetricCard
          icon={Landmark}
          tone="info"
          label="Estadual (SIGCON)"
          value={formatCurrencyShort(k.valor_total_estadual)}
          sub={`${formatInt(k.total_convenios_estadual)} convênios`}
        />
        <MetricCard
          icon={Coins}
          tone="ok"
          label="Federal (voluntárias)"
          value={formatCurrencyShort(k.valor_total_federal)}
          sub={`${formatInt(k.total_voluntarias)} propostas`}
        />
        <MetricCard
          icon={CalendarClock}
          tone="warn"
          label="Vigências ≤120d"
          value={formatInt(k.alertas_vigencia)}
          sub={`${formatInt(k.alertas_vigencia_60d)} em 60 dias`}
        />
        <MetricCard
          icon={FileWarning}
          tone="crit"
          label="Prestação vencida"
          value={formatInt(k.alertas_prestacao_contas)}
          sub="+90 dias"
        />
      </div>

      {/* Composição + regularidade + saúde */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <SectionHead icon={TrendingUp} title="Composição da captação" />
          <div className="mb-2 text-2xl font-bold tabular-nums text-base-content">
            {formatCurrencyShort(totalCaptado)}
          </div>
          <FonteStack
            segments={[
              { label: "Estadual", value: k.valor_total_estadual, color: "var(--chart-2)" },
              { label: "Federal", value: k.valor_total_federal, color: "var(--chart-1)" },
            ]}
          />
        </Card>

        <CaucCard ov={ov} />

        {ov.saude ? (
          <Card>
            <SectionHead icon={HeartPulse} title="Saúde (Acordo FES)" />
            <div className="text-2xl font-bold tabular-nums text-base-content">
              {formatCurrencyShort(ov.saude.divida_atual)}
            </div>
            <div className="mt-1 text-xs text-base-content/60">dívida atual do Fundo de Saúde</div>
            <FonteStack
              segments={[
                { label: "Pago", value: ov.saude.pago, color: "var(--chart-1)" },
                { label: "Em aberto", value: ov.saude.divida_atual, color: "var(--chart-4)" },
              ]}
            />
          </Card>
        ) : (
          <Card>
            <SectionHead icon={HeartPulse} title="Saúde (Acordo FES)" />
            <EmptyState>Sem dívida registrada no Acordo FES.</EmptyState>
          </Card>
        )}
      </div>

      {/* Parlamentares + movimentações */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <SectionHead icon={Users} title="Quem mais destinou recurso" />
          {ov.top_parlamentares.length ? (
            <RankingBars
              items={ov.top_parlamentares.slice(0, 6).map((p) => ({
                nome: p.nome_display,
                valor: p.valor_total,
                sub: ov.consolidado && p.municipios.length > 1 ? `${p.municipios.length} municípios` : undefined,
              }))}
            />
          ) : (
            <EmptyState>Sem parlamentares no período.</EmptyState>
          )}
        </Card>

        <Card>
          <SectionHead icon={History} title="Movimentações recentes" />
          {ov.ultimas_mudancas.length ? (
            <ul className="flex flex-col divide-y divide-base-200">
              {ov.ultimas_mudancas.slice(0, 8).map((m) => (
                <li key={m.id} className="py-2">
                  <div className="truncate text-[13px] font-medium text-base-content">
                    {m.objeto || m.ref || "—"}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-base-content/55">
                    <span className="truncate">
                      {m.status_anterior ? `${m.status_anterior} → ` : ""}
                      <b className="font-semibold text-base-content/75">{m.status_novo || "—"}</b>
                    </span>
                    <span className="ml-auto shrink-0">{formatDate(m.changed_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>Nenhuma mudança recente.</EmptyState>
          )}
        </Card>
      </div>
    </div>
  );
}

function CaucCard({ ov }: { ov: Overview }) {
  const s = ov.semaforo;
  if (isRollup(s)) {
    const pct = s.total_municipios ? s.regulares / s.total_municipios : 0;
    const tone = pct >= 0.99 ? "ok" : pct >= 0.5 ? "warn" : "crit";
    const piores = s.por_municipio.filter((m) => m.pendencias > 0).slice(0, 5);
    return (
      <Card>
        <SectionHead icon={pct >= 0.99 ? ShieldCheck : ShieldAlert} title="Regularidade (CAUC)" />
        <div className="mx-auto max-w-[220px]">
          <Gauge pct={pct} tone={tone} />
        </div>
        <div className="-mt-2 text-center">
          <div className="text-lg font-bold tabular-nums text-base-content">
            {s.regulares}/{s.total_municipios}
          </div>
          <div className="text-xs text-base-content/60">municípios em dia</div>
        </div>
        {piores.length > 0 && (
          <div className="mt-3">
            <StatBars items={piores.map((m) => ({ label: m.nome, value: m.pendencias }))} tone="crit" />
          </div>
        )}
      </Card>
    );
  }
  // municipio unico
  const itens = s.itens?.length || 0;
  const pend = s.pendencias || 0;
  return (
    <Card>
      <SectionHead icon={s.regular ? ShieldCheck : ShieldAlert} title="Regularidade (CAUC)" />
      {s.tem_dados ? (
        <>
          <div className="mb-2 flex items-center gap-2">
            {s.regular ? (
              <Pill tone="ok">Em dia</Pill>
            ) : (
              <Pill tone="crit">{pend} pendência(s)</Pill>
            )}
          </div>
          {itens > 0 && <SegBar total={itens} bad={pend} />}
          <div className="mt-2 text-xs text-base-content/60">
            {itens > 0 ? `${itens - pend} de ${itens} exigências regulares` : "Sem itens detalhados"}
          </div>
        </>
      ) : (
        <EmptyState>Sem dados de CAUC.</EmptyState>
      )}
    </Card>
  );
}

function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-28 animate-pulse rounded-2xl border border-base-300 bg-base-100" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-52 animate-pulse rounded-2xl border border-base-300 bg-base-100" />
        ))}
      </div>
    </div>
  );
}
