"use client";
import { useEffect, useState } from "react";
import { CalendarClock, FileWarning } from "lucide-react";
import { useBiScope } from "@/contexts/BiScopeContext";
import { getAlertas, Alertas, AlertaVigencia } from "@/lib/bi";
import { Card, SectionHead, EmptyState, Pill, type Tone } from "@/components/bi/ui";
import { formatCurrency, formatDate, diasSeveridade, diasLabel } from "@/lib/bi-format";

function esferaTone(esfera: string): Tone {
  return esfera === "voluntaria" ? "ok" : "info";
}

function AlertaRow({ a }: { a: AlertaVigencia }) {
  const sev = diasSeveridade(a.dias_restantes);
  const tone: Tone = sev === "crit" ? "crit" : sev === "warn" ? "warn" : "ok";
  return (
    <li className="flex items-start gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium text-base-content">{a.objeto || a.nr_sigcon || "—"}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[11px] text-base-content/55">
          <Pill tone={esferaTone(a.esfera)}>{a.esfera === "voluntaria" ? "Federal" : "Estadual"}</Pill>
          {a.orgao_concedente && <span className="truncate">{a.orgao_concedente}</span>}
          {a.dt_fim_vigencia && <span>· {formatDate(a.dt_fim_vigencia)}</span>}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <Pill tone={tone}>{diasLabel(a.dias_restantes)}</Pill>
        {a.valor_total != null && (
          <div className="mt-1 text-[11px] tabular-nums text-base-content/60">{formatCurrency(a.valor_total)}</div>
        )}
      </div>
    </li>
  );
}

export default function BiAlertasPage() {
  const { scope, municipioId, isConsolidado, ano } = useBiScope();
  const [data, setData] = useState<Alertas | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!scope) return;
    let cancel = false;
    setLoading(true);
    getAlertas(municipioId, ano)
      .then((d) => {
        if (!cancel) {
          setData(d);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [scope, municipioId, isConsolidado, ano]);

  if (loading && !data) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="h-72 animate-pulse rounded-2xl border border-base-300 bg-base-100" />
        <div className="h-72 animate-pulse rounded-2xl border border-base-300 bg-base-100" />
      </div>
    );
  }

  const vig = data?.vigencia || [];
  const prest = data?.prestacao || [];

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <SectionHead
          icon={CalendarClock}
          title="Vigências vencendo (≤120 dias)"
          action={<Pill tone="warn">{vig.length}</Pill>}
        />
        {vig.length ? (
          <ul className="flex flex-col divide-y divide-base-200">
            {vig.slice(0, 60).map((a, i) => (
              <AlertaRow key={`${a.id}-${i}`} a={a} />
            ))}
          </ul>
        ) : (
          <EmptyState>Nenhuma vigência crítica no período.</EmptyState>
        )}
      </Card>

      <Card>
        <SectionHead
          icon={FileWarning}
          title="Prestação de contas vencida (+90 dias)"
          action={<Pill tone="crit">{prest.length}</Pill>}
        />
        {prest.length ? (
          <ul className="flex flex-col divide-y divide-base-200">
            {prest.slice(0, 60).map((a, i) => (
              <AlertaRow key={`${a.id}-${i}`} a={a} />
            ))}
          </ul>
        ) : (
          <EmptyState>Nenhuma prestação de contas vencida.</EmptyState>
        )}
      </Card>
    </div>
  );
}
