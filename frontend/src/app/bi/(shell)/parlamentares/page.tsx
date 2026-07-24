"use client";
import { useEffect, useMemo, useState } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LabelList,
} from "recharts";
import { Users, Zap } from "lucide-react";
import { useBiScope } from "@/contexts/BiScopeContext";
import { getParlamentares, RankingItem } from "@/lib/bi";
import { Card, SectionHead, EmptyState, Pill } from "@/components/bi/ui";
import { CHART_COLORS } from "@/components/bi/charts";
import { formatCurrencyShort, formatCurrency, formatInt } from "@/lib/bi-format";

export default function BiParlamentaresPage() {
  const { scope, municipioId, isConsolidado, ano } = useBiScope();
  const [items, setItems] = useState<RankingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [live, setLive] = useState(false);

  useEffect(() => {
    if (!scope) return;
    let cancel = false;
    setLoading(true);
    getParlamentares(municipioId, ano, live)
      .then((d) => {
        if (!cancel) {
          setItems(d.items || []);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [scope, municipioId, isConsolidado, ano, live]);

  const filtered = useMemo(() => {
    const qn = q.trim().toLowerCase();
    const list = qn
      ? items.filter((i) => i.nome_display.toLowerCase().includes(qn))
      : items;
    return list;
  }, [items, q]);

  const chartData = useMemo(
    () =>
      filtered.slice(0, 12).map((p) => ({
        nome: p.nome_display.length > 22 ? p.nome_display.slice(0, 21) + "…" : p.nome_display,
        valor: p.valor_total,
      })),
    [filtered]
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input input-bordered input-sm w-full max-w-xs"
          placeholder="Buscar parlamentar…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {!isConsolidado && municipioId != null && (
          <button
            onClick={() => setLive((v) => !v)}
            className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
              live
                ? "border-primary bg-primary/10 text-primary"
                : "border-base-300 text-base-content/60 hover:bg-base-200"
            }`}
            title="Inclui as emendas federais (RP9/Pix) ao vivo — mais lento"
          >
            <Zap className="size-3.5" /> Emendas federais ao vivo
          </button>
        )}
      </div>

      <Card>
        <SectionHead icon={Users} title={`Ranking de recursos destinados${live ? " (com RP9 ao vivo)" : ""}`} />
        {loading ? (
          <div className="h-72 animate-pulse rounded-xl bg-base-200" />
        ) : chartData.length ? (
          <div className="h-[360px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 48, top: 4, bottom: 4 }}>
                <XAxis type="number" hide />
                <YAxis
                  type="category"
                  dataKey="nome"
                  width={150}
                  tick={{ fontSize: 12, fill: "var(--color-base-content)" }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  cursor={{ fill: "var(--color-base-200)" }}
                  contentStyle={{
                    background: "var(--color-base-100)",
                    border: "1px solid var(--color-base-300)",
                    borderRadius: 12,
                    fontSize: 12,
                  }}
                  formatter={(v) => [formatCurrency(Number(v)), "Valor"]}
                />
                <Bar dataKey="valor" radius={[0, 6, 6, 0]}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                  ))}
                  <LabelList
                    dataKey="valor"
                    position="right"
                    formatter={(v) => formatCurrencyShort(Number(v))}
                    style={{ fontSize: 11, fill: "var(--color-base-content)", fontWeight: 600 }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <EmptyState>Nenhum parlamentar no período/escopo.</EmptyState>
        )}
      </Card>

      <Card>
        <SectionHead icon={Users} title="Detalhamento" />
        {filtered.length ? (
          <div className="overflow-x-auto">
            <table className="table table-sm">
              <thead>
                <tr className="text-base-content/50">
                  <th>Parlamentar</th>
                  <th className="text-right">Valor</th>
                  <th className="text-right">Lançamentos</th>
                  {isConsolidado && <th>Municípios</th>}
                  <th>Fontes</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, 50).map((p) => (
                  <tr key={p.nome_normalizado}>
                    <td className="font-medium">{p.nome_display}</td>
                    <td className="text-right tabular-nums">{formatCurrency(p.valor_total)}</td>
                    <td className="text-right tabular-nums">{formatInt(p.total_lancamentos)}</td>
                    {isConsolidado && (
                      <td className="text-xs text-base-content/60">{p.municipios.length}</td>
                    )}
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(p.por_fonte)
                          .filter(([, n]) => n > 0)
                          .map(([f, n]) => (
                            <Pill key={f} tone="neutral">
                              {f}: {n}
                            </Pill>
                          ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>Sem resultados.</EmptyState>
        )}
      </Card>
    </div>
  );
}
