"use client";
import { useEffect, useState } from "react";
import {
  Bell, ShieldCheck, Landmark, Users, Clock, AlertTriangle,
  CheckCircle2, FileClock, Wallet, HeartPulse,
} from "lucide-react";
import { Card, SectionHead, Pill, AiCard, cn } from "@/components/ui";
import { FonteStack, RankingBars } from "@/components/charts";
import { ThemeToggle } from "@/components/ThemeToggle";
import { PeriodSelector } from "@/components/PeriodSelector";
import { formatCurrencyShort, formatInt } from "@/lib/format";
import { getMunicipios, getVisao, getNarrativa, type Visao } from "@/lib/painel";
import { DEMO_VISAO, ehParlamentarValido } from "@/lib/demo";
import { usePeriod, labelAno } from "@/lib/period";
import { resumoExecutivo, limparNarrativa } from "@/lib/narrative";

export default function Home() {
  const { ano, ready } = usePeriod();
  const [v, setV] = useState<Visao | null>(null);
  const [demo, setDemo] = useState(false);
  const [loading, setLoading] = useState(true);
  const [narrativa, setNarrativa] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    setLoading(true);
    setNarrativa(null);
    (async () => {
      try {
        const muns = await getMunicipios();
        const mid = muns[0]?.id ?? 1;
        const data = await getVisao(mid, ano ?? undefined);
        if (alive) { setV(data); setDemo(false); }
        getNarrativa(mid, ano ?? undefined)
          .then((n) => { if (alive && n.disponivel && n.texto) setNarrativa(n.texto); })
          .catch(() => {});
      } catch {
        if (alive) { setV(DEMO_VISAO); setDemo(true); }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [ready, ano]);

  if (!v) return <LoadingHome />;

  const k = v.kpis;
  const mun = k.municipio;
  const total = (k.valor_total_estadual || 0) + (k.valor_total_federal || 0);
  const regular = !!v.semaforo.regular;
  const pend = v.semaforo.pendencias || 0;
  const top = (v.top_parlamentares || [])
    .filter((p) => ehParlamentarValido(p.nome_normalizado, mun.nome))
    .slice(0, 3)
    .map((p) => ({ nome: p.nome_display, valor: p.valor_total, sub: `${p.total_lancamentos} lançamentos` }));

  return (
    <>
      <header className="flex items-center justify-between pt-2 pb-1">
        <div className="flex items-center gap-2.5">
          <span className="w-[38px] h-[38px] rounded-xl grid place-items-center text-white font-display font-extrabold text-[15px] shrink-0 shadow-card-sm" style={{ background: "linear-gradient(150deg,#2f6b3a,#4f9e57)" }}>
            {mun.nome.slice(0, 2).toUpperCase()}
          </span>
          <div>
            <div className="font-display font-bold text-[15px] leading-tight">{mun.nome}</div>
            <div className="text-[11.5px] text-ink-3">{mun.uf === "MG" ? "Minas Gerais" : mun.uf}</div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <button className="w-[38px] h-[38px] rounded-xl bg-surface border border-line grid place-items-center text-ink-2 relative" aria-label="Alertas">
            <Bell size={18} />
            {k.alertas_prestacao_contas > 0 && (
              <span className="absolute -top-1 -right-1 bg-crit text-white text-[9px] font-bold min-w-[15px] h-[15px] rounded-full grid place-items-center px-[3px]">!</span>
            )}
          </button>
        </div>
      </header>

      <div className="pt-1 pb-2">
        <div className="text-[13px] text-ink-2">👋 Bom dia, Prefeito</div>
        <h2 className="text-[26px] font-extrabold tracking-tight leading-none mt-0.5">Panorama</h2>
      </div>

      <PeriodSelector className="mb-3" />

      {demo && (
        <div className="mb-3 text-[11.5px] text-ink-3 bg-surface-2 border border-line rounded-full px-3 py-1.5 inline-flex items-center gap-2">
          <span className="w-[7px] h-[7px] rounded-full bg-accent" /> Dados de exemplo (Monte Sião) — sem sessão ativa
        </div>
      )}

      <div className={cn("flex flex-col gap-3.5 transition-opacity", loading && "opacity-50")}>
        <AiCard>{narrativa ? limparNarrativa(narrativa) : resumoExecutivo(v, ano)}</AiCard>

        <Card>
          <div className="text-[12.5px] text-ink-2">Total captado · {labelAno(ano)}</div>
          <div className="font-display font-extrabold text-[34px] tracking-tight leading-none mt-1.5 tnum">{formatCurrencyShort(total)}</div>
          <div className="text-[12px] text-ink-3 mt-2">
            {formatInt(k.total_voluntarias)} propostas federais · {formatInt(k.total_convenios_estadual)} convênios estaduais
          </div>
          <div className="mt-3">
            <FonteStack segments={[
              { label: "Federal", value: k.valor_total_federal, color: "var(--c-blue)" },
              { label: "Estadual", value: k.valor_total_estadual, color: "var(--c-green)" },
            ]} />
          </div>
        </Card>

        <Card>
          <SectionHead icon={<ShieldCheck size={16} />} title="Documentação (CAUC)" right={<>STN · hoje</>} />
          <div className="flex items-center justify-between">
            <div>
              <div className="font-display font-bold text-[18px]">{regular ? "Em dia" : `${pend} pendência${pend > 1 ? "s" : ""}`}</div>
              <div className="text-[12px] text-ink-3">{regular ? "Apto a receber transferências voluntárias" : "Pode travar novos repasses"}</div>
            </div>
            {regular ? <Pill tone="ok"><CheckCircle2 size={13} /> Regular</Pill> : <Pill tone="crit"><AlertTriangle size={13} /> Atenção</Pill>}
          </div>
        </Card>

        {v.saude && v.saude.divida_atual > 0 && (
          <Card>
            <SectionHead icon={<HeartPulse size={16} />} title="Saúde · Acordo FES" right={<>SES-MG</>} />
            <div className="flex items-end justify-between">
              <div>
                <div className="text-[12px] text-ink-2">Estado deve ao Fundo Municipal</div>
                <div className="font-display font-extrabold text-[24px] tracking-tight tnum mt-0.5 text-crit">{formatCurrencyShort(v.saude.divida_atual)}</div>
              </div>
              <div className="text-right text-[11.5px] text-ink-3">
                <div>pago {formatCurrencyShort(v.saude.pago)}</div>
                <div>de {formatCurrencyShort(v.saude.inicial)}</div>
              </div>
            </div>
            <div className="h-2 rounded-full bg-surface-3 overflow-hidden mt-2.5">
              <div className="h-full rounded-full bg-ok" style={{ width: `${Math.min(100, (v.saude.pago / (v.saude.inicial || 1)) * 100)}%` }} />
            </div>
          </Card>
        )}

        <div className="grid grid-cols-2 gap-2.5">
          <Tile color="var(--c-blue)" icon={<Wallet size={14} />} label="Voluntárias federais" value={formatInt(k.total_voluntarias)} sub="captação federal" />
          <Tile color="var(--c-green)" icon={<Landmark size={14} />} label="Convênios estaduais" value={formatInt(k.total_convenios_estadual)} sub="SIGCON-MG" />
          <Tile color="var(--c-amber)" icon={<Clock size={14} />} label="Vencem ≤ 60 dias" value={formatInt(k.alertas_vigencia_60d)} sub="atenção à vigência" tone={k.alertas_vigencia_60d > 0 ? "warn" : undefined} />
          <Tile color="var(--c-coral)" icon={<FileClock size={14} />} label="Prestação vencida" value={formatInt(k.alertas_prestacao_contas)} sub="+90 dias" tone={k.alertas_prestacao_contas > 0 ? "crit" : undefined} />
        </div>

        {top.length > 0 && (
          <Card>
            <SectionHead icon={<Users size={16} />} title="Quem mandou verba" right={<>{labelAno(ano)}</>} />
            <RankingBars items={top} />
          </Card>
        )}
      </div>
    </>
  );
}

function Tile({ color, icon, label, value, sub, tone }: { color: string; icon: React.ReactNode; label: string; value: string; sub?: string; tone?: "warn" | "crit" }) {
  return (
    <div className="bg-surface border border-line rounded-2xl shadow-card-sm p-3.5">
      <div className="flex items-center gap-2 text-[12px] text-ink-2">
        <span className="w-6 h-6 rounded-[7px] grid place-items-center text-white shrink-0" style={{ background: color }}>{icon}</span>
        {label}
      </div>
      <div className={cn("font-display font-extrabold text-[21px] tracking-tight mt-2 tnum", tone === "crit" && "text-crit", tone === "warn" && "text-warn")}>{value}</div>
      {sub && <div className="text-[11px] text-ink-3 mt-0.5">{sub}</div>}
    </div>
  );
}

function LoadingHome() {
  return (
    <div className="pt-16 flex flex-col items-center gap-3 text-ink-3">
      <div className="w-8 h-8 rounded-full border-2 border-line border-t-accent-strong animate-spin" />
      <div className="text-sm">Carregando panorama…</div>
    </div>
  );
}
