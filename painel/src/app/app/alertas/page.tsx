"use client";
import { useEffect, useState } from "react";
import { AlertTriangle, Clock, CheckCircle2, FileClock } from "lucide-react";
import { Card, cn } from "@/components/ui";
import { PageTitle, Loading } from "@/components/controls";
import { PeriodSelector } from "@/components/PeriodSelector";
import { formatCurrencyShort, formatInt, diasLabel, diasSeveridade } from "@/lib/format";
import { getMunicipios, getVisao, getAlertas, type Alertas, type AlertaVigencia, type MunicipioSummary } from "@/lib/painel";
import { DEMO_VISAO, DEMO_ALERTAS } from "@/lib/demo";
import { usePeriod, useJanelaDias, JANELAS } from "@/lib/period";

type Row = AlertaVigencia & { kind: "prestacao" | "vigencia" };

export default function AlertasPage() {
  const { ano, ready } = usePeriod();
  const { dias, setDias } = useJanelaDias(120);
  const [al, setAl] = useState<Alertas | null>(null);
  const [kpi, setKpi] = useState<MunicipioSummary | null>(null);
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    (async () => {
      try {
        const muns = await getMunicipios();
        const mid = muns[0]?.id ?? 1;
        const [a, v] = await Promise.all([getAlertas(mid, ano ?? undefined), getVisao(mid, ano ?? undefined)]);
        if (alive) { setAl(a); setKpi(v.kpis); setDemo(false); }
      } catch {
        if (alive) { setAl(DEMO_ALERTAS); setKpi(DEMO_VISAO.kpis); setDemo(true); }
      }
    })();
    return () => { alive = false; };
  }, [ready, ano]);

  if (!al || !kpi) return <Loading />;

  const vigenciaFiltrada = al.vigencia.filter((x) => x.dias_restantes <= dias);
  const rows: Row[] = [
    ...al.prestacao.map((x) => ({ ...x, kind: "prestacao" as const })),
    ...vigenciaFiltrada.map((x) => ({ ...x, kind: "vigencia" as const })),
  ];

  return (
    <>
      <PageTitle title="Alertas" subtitle="Prazos e pendências que exigem ação" />
      <PeriodSelector className="mb-2" />
      <div className="flex items-center gap-1.5 mb-3.5 overflow-x-auto no-scrollbar -mx-4 px-4">
        <span className="text-[12px] text-ink-3 shrink-0 mr-0.5">Vence em:</span>
        {JANELAS.map((j) => (
          <button
            key={j.d}
            onClick={() => setDias(j.d)}
            className={cn("px-3 py-1.5 rounded-full text-[12px] font-semibold border whitespace-nowrap shrink-0", dias === j.d ? "bg-surface-2 border-line text-ink" : "bg-surface border-line text-ink-3")}
          >
            {j.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2.5 mb-3.5">
        <MiniStat tone={kpi.alertas_prestacao_contas > 0 ? "crit" : "ok"} icon={<FileClock size={15} />} value={formatInt(kpi.alertas_prestacao_contas)} label="Prestação vencida" />
        <MiniStat tone={vigenciaFiltrada.length > 0 ? "warn" : "ok"} icon={<Clock size={15} />} value={formatInt(vigenciaFiltrada.length)} label={`Vencendo (≤${dias}d)`} />
      </div>

      {rows.length === 0 ? (
        <Card>
          <div className="text-center py-6 text-ink-3">
            <CheckCircle2 className="mx-auto mb-2 text-ok" size={28} />
            Nenhum alerta na janela selecionada.
          </div>
        </Card>
      ) : (
        <div className="flex flex-col gap-2.5">
          {rows.map((it, i) => (
            <AlertItem key={i} it={it} />
          ))}
        </div>
      )}
    </>
  );
}

function MiniStat({ tone, icon, value, label }: { tone: "ok" | "warn" | "crit"; icon: React.ReactNode; value: string; label: string }) {
  const c = tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-ok";
  const bg = tone === "crit" ? "bg-crit-soft" : tone === "warn" ? "bg-warn-soft" : "bg-ok-soft";
  return (
    <div className="bg-surface border border-line rounded-2xl shadow-card-sm p-3.5">
      <span className={cn("w-7 h-7 rounded-lg grid place-items-center", bg, c)}>{icon}</span>
      <div className={cn("font-display font-extrabold text-[22px] tnum mt-2", c)}>{value}</div>
      <div className="text-[11.5px] text-ink-3">{label}</div>
    </div>
  );
}

function AlertItem({ it }: { it: Row }) {
  const sev = it.kind === "prestacao" ? "crit" : diasSeveridade(it.dias_restantes);
  const bg = sev === "crit" ? "bg-crit-soft text-crit" : sev === "warn" ? "bg-warn-soft text-warn" : "bg-ok-soft text-ok";
  const Icon = sev === "crit" ? AlertTriangle : Clock;
  return (
    <Card className="!p-3.5">
      <div className="grid grid-cols-[auto_1fr_auto] gap-3 items-start">
        <span className={cn("w-9 h-9 rounded-xl grid place-items-center shrink-0", bg)}>
          <Icon size={16} />
        </span>
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold leading-snug line-clamp-2">{it.objeto || it.orgao_concedente || "Convênio"}</div>
          <div className="text-[12px] text-ink-3 mt-0.5">
            {it.esfera === "voluntaria" ? "Federal" : "Estadual"} · {it.nr_convenio || it.nr_sigcon || "—"}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className={cn("text-[12.5px] font-bold", sev === "crit" ? "text-crit" : sev === "warn" ? "text-warn" : "text-ink")}>{diasLabel(it.dias_restantes)}</div>
          {it.valor_total ? <div className="text-[11px] text-ink-3 tnum mt-0.5">{formatCurrencyShort(it.valor_total)}</div> : null}
        </div>
      </div>
    </Card>
  );
}
