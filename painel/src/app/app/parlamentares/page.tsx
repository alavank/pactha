"use client";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui";
import { PageTitle, Loading } from "@/components/controls";
import { PeriodSelector } from "@/components/PeriodSelector";
import { RankingBars } from "@/components/charts";
import { formatCurrencyShort } from "@/lib/format";
import { getMunicipios, getRanking, type RankingItem } from "@/lib/painel";
import { DEMO_VISAO, ehParlamentarValido } from "@/lib/demo";
import { usePeriod, labelAno } from "@/lib/period";

export default function ParlamentaresPage() {
  const { ano, ready } = usePeriod();
  const [items, setItems] = useState<RankingItem[] | null>(null);
  const [muniNome, setMuniNome] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const muns = await getMunicipios();
        const mid = muns[0]?.id ?? 1;
        if (alive) setMuniNome(muns[0]?.nome ?? "");
        const r = await getRanking(mid, ano ?? undefined);
        if (alive) setItems(r.items);
      } catch {
        if (alive) { setItems(DEMO_VISAO.top_parlamentares); setMuniNome(DEMO_VISAO.kpis.municipio.nome); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [ready, ano]);

  if (!items) return <Loading />;

  const valid = items.filter((p) => ehParlamentarValido(p.nome_normalizado, muniNome));
  const totalValor = valid.reduce((s, p) => s + p.valor_total, 0);

  return (
    <>
      <PageTitle title="Parlamentares" subtitle="Quem destinou recurso ao município" />
      <PeriodSelector className="mb-3" />
      <div className={loading ? "opacity-50 transition-opacity" : "transition-opacity"}>
        <Card className="mb-3.5">
          <div className="text-[12.5px] text-ink-2">Total atribuído a parlamentares · {labelAno(ano)}</div>
          <div className="font-display font-extrabold text-[28px] tracking-tight tnum mt-1">{formatCurrencyShort(totalValor)}</div>
          <div className="text-[12px] text-ink-3 mt-1">{valid.length} parlamentares com recurso destinado</div>
        </Card>
        {valid.length > 0 ? (
          <Card>
            <RankingBars items={valid.slice(0, 12).map((p) => ({ nome: p.nome_display, valor: p.valor_total, sub: fonteSub(p) }))} />
          </Card>
        ) : (
          <Card>
            <div className="text-center py-6 text-ink-3 text-[13px]">Nenhum parlamentar com recurso registrado no período.</div>
          </Card>
        )}
      </div>
    </>
  );
}

function fonteSub(p: RankingItem): string {
  const f = p.por_fonte;
  const parts: string[] = [];
  if (f.plano_acao) parts.push(`${f.plano_acao} transf. especial`);
  if (f.voluntaria) parts.push(`${f.voluntaria} voluntária(s)`);
  if (f.emenda) parts.push(`${f.emenda} emenda(s)`);
  if (f.sigcon) parts.push(`${f.sigcon} SIGCON`);
  return parts.join(" · ") || `${p.total_lancamentos} lançamentos`;
}
