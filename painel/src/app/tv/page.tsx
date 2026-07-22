"use client";
import { useEffect, useState } from "react";
import { ShieldCheck, HeartPulse, Users, FileClock, AlertTriangle, CheckCircle2, Sparkles, Clock } from "lucide-react";
import { getMunicipios, getVisao, getAlertas, getNarrativa, type Visao, type Alertas } from "@/lib/painel";
import { DEMO_VISAO, DEMO_ALERTAS, DOCUMENTACOES, ehParlamentarValido } from "@/lib/demo";
import { formatCurrencyShort, formatInt, diasLabel } from "@/lib/format";
import { initials } from "@/components/ui";
import { usePeriod, ANOS, labelAno } from "@/lib/period";
import { resumoExecutivo, destaqueSaude, limparNarrativa } from "@/lib/narrative";

// Wallboard 4K (kiosk) — denso e interativo (o PC ligado na TV opera os filtros).
export default function Tv() {
  const { ano, setAno, ready } = usePeriod();
  const [v, setV] = useState<Visao | null>(null);
  const [al, setAl] = useState<Alertas | null>(null);
  const [fF, setFF] = useState(true);
  const [fE, setFE] = useState(true);
  const [narrativa, setNarrativa] = useState<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    // Token de quiosque via ?kiosk=<token> (a TV liga sem login).
    try {
      const k = new URLSearchParams(window.location.search).get("kiosk");
      if (k) {
        localStorage.setItem("pactha_token", k);
        window.history.replaceState({}, "", "/tv");
      }
    } catch {}
    let alive = true;
    setNarrativa(null);
    const load = async () => {
      try {
        const m = await getMunicipios();
        const mid = m[0]?.id ?? 1;
        const [vi, aa] = await Promise.all([getVisao(mid, ano ?? undefined), getAlertas(mid, ano ?? undefined)]);
        if (alive) { setV(vi); setAl(aa); }
        getNarrativa(mid, ano ?? undefined)
          .then((n) => { if (alive && n.disponivel && n.texto) setNarrativa(n.texto); })
          .catch(() => {});
      } catch {
        if (alive) { setV((p) => p ?? DEMO_VISAO); setAl((p) => p ?? DEMO_ALERTAS); }
      }
    };
    load();
    const iv = setInterval(load, 5 * 60 * 1000);
    return () => { alive = false; clearInterval(iv); };
  }, [ready, ano]);

  if (!v) return <div className="min-h-dvh grid place-items-center bg-page text-ink-3">Carregando…</div>;

  const k = v.kpis;
  const mun = k.municipio;
  const total = (fE ? k.valor_total_estadual : 0) + (fF ? k.valor_total_federal : 0);
  const regular = !!v.semaforo.regular;
  const top = (v.top_parlamentares || []).filter((p) => ehParlamentarValido(p.nome_normalizado, mun.nome)).slice(0, 6);
  const maxV = Math.max(...top.map((t) => t.valor_total), 1);
  const AV = ["#2f6b3a", "#57a6e6", "#b98ce0", "#f2b34a", "#68cf56", "#f0785b"];
  const prestacoes = (al?.prestacao || []).slice(0, 6);
  const stackSeg = [
    fF && k.valor_total_federal > 0 ? { label: "Federal", value: k.valor_total_federal, color: "var(--c-blue)" } : null,
    fE && k.valor_total_estadual > 0 ? { label: "Estadual", value: k.valor_total_estadual, color: "var(--c-green)" } : null,
  ].filter(Boolean) as { label: string; value: number; color: string }[];
  const stackTotal = stackSeg.reduce((s, x) => s + x.value, 0) || 1;

  return (
    <div className="min-h-dvh bg-page text-ink flex flex-col" style={{ padding: "1.8vw" }}>
      <div className="flex items-center justify-between" style={{ marginBottom: "1.4vw" }}>
        <div className="flex items-center" style={{ gap: "1vw" }}>
          <span className="grid place-items-center text-white font-display font-extrabold shrink-0" style={{ width: "3.4vw", height: "3.4vw", borderRadius: "0.9vw", fontSize: "1.4vw", background: "linear-gradient(150deg,#2f6b3a,#4f9e57)" }}>
            {mun.nome.slice(0, 2).toUpperCase()}
          </span>
          <div>
            <h1 className="font-display font-extrabold tracking-tight" style={{ fontSize: "2.4vw", lineHeight: 1 }}>{mun.nome} · Panorama de Recursos</h1>
            <div className="text-ink-2" style={{ fontSize: "1.05vw", marginTop: "0.3vw" }}>Prefeitura Municipal · {labelAno(ano)}</div>
          </div>
        </div>
        <div className="flex items-center" style={{ gap: "0.8vw" }}>
          <FonteToggle label="Federal" on={fF} onClick={() => setFF((x) => !x)} color="var(--c-blue)" />
          <FonteToggle label="Estadual" on={fE} onClick={() => setFE((x) => !x)} color="var(--c-green)" />
          <div className="flex bg-surface border border-line rounded-full" style={{ padding: "0.3vw", gap: "0.2vw" }}>
            {ANOS.map((a) => (
              <button key={String(a)} onClick={() => setAno(a)} className="font-semibold rounded-full transition-colors" style={{ fontSize: "1vw", padding: "0.5vw 1vw", background: ano === a ? "var(--cta)" : "transparent", color: ano === a ? "var(--cta-ink)" : "var(--ink-2)" }}>
                {a == null ? "Todos" : a}
              </button>
            ))}
          </div>
          <span className="inline-flex items-center bg-surface border border-line rounded-full font-bold text-ink-2" style={{ fontSize: "0.95vw", gap: "0.5vw", padding: "0.6vw 1vw" }}>
            <span className="rounded-full bg-crit" style={{ width: "0.6vw", height: "0.6vw" }} /> AO VIVO
          </span>
        </div>
      </div>

      <div className="flex-1" style={{ display: "grid", gridTemplateColumns: "repeat(12,1fr)", gridTemplateRows: "1.05fr 0.95fr", gap: "1.2vw", minHeight: 0 }}>
        {/* HERO */}
        <TvCard style={{ gridColumn: "1 / span 5", gridRow: "1" }}>
          <CardLabel>Total captado · {labelAno(ano)}</CardLabel>
          <div className="font-display font-extrabold tracking-tight tnum" style={{ fontSize: "4.6vw", lineHeight: 1, marginTop: "0.4vw" }}>{formatCurrencyShort(total)}</div>
          <div className="text-ink-3" style={{ fontSize: "1.1vw", marginTop: "0.6vw" }}>{formatInt(k.total_voluntarias)} propostas federais · {formatInt(k.total_convenios_estadual)} convênios estaduais</div>
          <div className="flex overflow-hidden" style={{ height: "1.1vw", borderRadius: "0.5vw", gap: "0.15vw", marginTop: "auto" }}>
            {stackSeg.map((s, i) => <span key={i} style={{ flexGrow: s.value / stackTotal, flexBasis: 0, background: s.color, borderRadius: "0.3vw" }} />)}
          </div>
          <div className="flex" style={{ gap: "1.4vw", marginTop: "0.8vw" }}>
            {stackSeg.map((s, i) => (
              <span key={i} className="flex items-center text-ink-2" style={{ gap: "0.5vw", fontSize: "1vw" }}>
                <span style={{ width: "0.8vw", height: "0.8vw", borderRadius: "0.2vw", background: s.color }} /> {s.label} <b className="text-ink tnum">{formatCurrencyShort(s.value)}</b>
              </span>
            ))}
          </div>
        </TvCard>

        {/* CAUC + DOCS + SAUDE */}
        <TvCard style={{ gridColumn: "6 / span 4", gridRow: "1" }}>
          <div className="flex items-center justify-between">
            <CardLabel><ShieldCheck style={{ width: "1.2vw", height: "1.2vw", display: "inline", verticalAlign: "-0.2vw" }} /> Documentação</CardLabel>
            <span className="inline-flex items-center font-bold rounded-full" style={{ fontSize: "0.95vw", gap: "0.4vw", padding: "0.4vw 0.9vw", background: regular ? "var(--ok-soft)" : "var(--crit-soft)", color: regular ? "var(--ok)" : "var(--crit)" }}>
              {regular ? "CAUC em dia" : `${v.semaforo.pendencias} pend.`}
            </span>
          </div>
          <div className="flex flex-wrap" style={{ gap: "0.5vw", marginTop: "0.8vw" }}>
            {DOCUMENTACOES.map((d) => (
              <span key={d.key} className="inline-flex items-center font-semibold rounded-full border" style={{ fontSize: "0.85vw", gap: "0.4vw", padding: "0.35vw 0.8vw", borderColor: "var(--line)", background: d.ativo ? "var(--ok-soft)" : "var(--surface-2)", color: d.ativo ? "var(--ok)" : "var(--ink-3)" }}>
                {d.ativo ? <CheckCircle2 style={{ width: "0.9vw", height: "0.9vw" }} /> : <Clock style={{ width: "0.9vw", height: "0.9vw" }} />} {d.nome}
              </span>
            ))}
          </div>
          {v.saude && v.saude.divida_atual > 0 && (
            <div style={{ marginTop: "auto" }}>
              <div className="flex items-center" style={{ gap: "0.5vw", fontSize: "1vw" }}><HeartPulse style={{ width: "1.1vw", height: "1.1vw", color: "var(--c-coral)" }} /> <span className="text-ink-2">Saúde · Acordo FES — Estado deve</span></div>
              <div className="font-display font-extrabold tracking-tight tnum text-crit" style={{ fontSize: "2.2vw", marginTop: "0.2vw" }}>{formatCurrencyShort(v.saude.divida_atual)}</div>
              <div className="overflow-hidden bg-surface-3" style={{ height: "0.7vw", borderRadius: "0.4vw", marginTop: "0.4vw" }}>
                <div className="bg-ok" style={{ height: "100%", borderRadius: "0.4vw", width: `${Math.min(100, (v.saude.pago / (v.saude.inicial || 1)) * 100)}%` }} />
              </div>
              <div className="text-ink-3" style={{ fontSize: "0.85vw", marginTop: "0.3vw" }}>pago {formatCurrencyShort(v.saude.pago)} de {formatCurrencyShort(v.saude.inicial)}</div>
            </div>
          )}
        </TvCard>

        {/* RANKING (tall) */}
        <TvCard style={{ gridColumn: "10 / span 3", gridRow: "1 / span 2" }}>
          <CardLabel><Users style={{ width: "1.2vw", height: "1.2vw", display: "inline", verticalAlign: "-0.2vw" }} /> Quem mandou verba</CardLabel>
          <div className="flex-1 flex flex-col justify-center" style={{ gap: "1.1vw", marginTop: "0.6vw" }}>
            {top.map((t, i) => (
              <div key={i}>
                <div className="flex items-center" style={{ gap: "0.7vw" }}>
                  <span className="grid place-items-center text-white font-display font-bold shrink-0" style={{ width: "2.3vw", height: "2.3vw", borderRadius: "0.6vw", fontSize: "0.95vw", background: AV[i % AV.length] }}>{initials(t.nome_display)}</span>
                  <div className="min-w-0 flex-1">
                    <div className="font-display font-bold truncate" style={{ fontSize: "1.15vw" }}>{t.nome_display}</div>
                    <div className="text-ink-3" style={{ fontSize: "0.8vw" }}>{formatInt(t.total_lancamentos)} lançamentos</div>
                  </div>
                  <div className="font-display font-extrabold tnum" style={{ fontSize: "1.15vw" }}>{formatCurrencyShort(t.valor_total)}</div>
                </div>
                <div className="bg-surface-3 overflow-hidden" style={{ height: "0.55vw", borderRadius: "0.3vw", marginTop: "0.35vw" }}>
                  <div style={{ height: "100%", width: `${(t.valor_total / maxV) * 100}%`, borderRadius: "0.3vw", background: "linear-gradient(90deg,var(--accent-strong),var(--accent))" }} />
                </div>
              </div>
            ))}
          </div>
        </TvCard>

        {/* RESUMO */}
        <TvCard accent style={{ gridColumn: "1 / span 4", gridRow: "2" }}>
          <div className="inline-flex items-center font-bold uppercase rounded-full" style={{ fontSize: "0.85vw", letterSpacing: "0.05em", gap: "0.5vw", padding: "0.4vw 0.9vw", background: "var(--accent-soft)", color: "var(--accent-ink)", alignSelf: "flex-start" }}>
            <Sparkles style={{ width: "0.9vw", height: "0.9vw" }} /> Resumo do prefeito
          </div>
          <p style={{ fontSize: "1.25vw", lineHeight: 1.5, marginTop: "0.8vw" }}>{narrativa ? limparNarrativa(narrativa) : resumoExecutivo(v, ano)}</p>
          {destaqueSaude(v) && <p className="text-ink-2" style={{ fontSize: "1.05vw", lineHeight: 1.45, marginTop: "0.6vw" }}>{destaqueSaude(v)}</p>}
        </TvCard>

        {/* PRAZOS */}
        <TvCard style={{ gridColumn: "5 / span 5", gridRow: "2" }}>
          <div className="flex items-center justify-between">
            <CardLabel><FileClock style={{ width: "1.2vw", height: "1.2vw", display: "inline", verticalAlign: "-0.2vw" }} /> Prazos que exigem ação</CardLabel>
            <span className="inline-flex items-center font-bold rounded-full" style={{ fontSize: "0.95vw", gap: "0.4vw", padding: "0.4vw 0.9vw", background: "var(--crit-soft)", color: "var(--crit)" }}>
              <AlertTriangle style={{ width: "0.95vw", height: "0.95vw" }} /> {formatInt(k.alertas_prestacao_contas)} prestações vencidas
            </span>
          </div>
          <div className="text-ink-3" style={{ fontSize: "0.95vw", marginTop: "0.4vw" }}>Convênios federais que precisam de prestação de contas para liberar novos recursos:</div>
          <div className="flex-1 flex flex-col justify-center" style={{ gap: "0.5vw", marginTop: "0.4vw" }}>
            {prestacoes.map((it, i) => (
              <div key={i} className="flex items-center bg-surface-2" style={{ gap: "0.8vw", borderRadius: "0.6vw", padding: "0.7vw 1vw" }}>
                <span className="grid place-items-center shrink-0" style={{ width: "2vw", height: "2vw", borderRadius: "0.5vw", background: "var(--crit-soft)", color: "var(--crit)" }}><AlertTriangle style={{ width: "1vw", height: "1vw" }} /></span>
                <div className="min-w-0 flex-1">
                  <div className="font-semibold truncate" style={{ fontSize: "1.05vw" }}>{it.objeto}</div>
                  <div className="text-ink-3 truncate" style={{ fontSize: "0.82vw" }}>{it.orgao_concedente}</div>
                </div>
                <div className="font-bold text-crit tnum shrink-0" style={{ fontSize: "1vw" }}>{diasLabel(it.dias_restantes)}</div>
              </div>
            ))}
          </div>
        </TvCard>
      </div>
    </div>
  );
}

function TvCard({ children, style, accent }: { children: React.ReactNode; style?: React.CSSProperties; accent?: boolean }) {
  return (
    <div
      className="bg-surface border border-line shadow-card flex flex-col overflow-hidden"
      style={{ borderRadius: "1.2vw", padding: "1.6vw", ...(accent ? { background: "radial-gradient(120% 100% at 0% 0%, var(--accent-soft), transparent 55%), var(--surface)" } : {}), ...style }}
    >
      {children}
    </div>
  );
}
function CardLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-ink-2 font-semibold" style={{ fontSize: "1.2vw" }}>{children}</div>;
}
function FonteToggle({ label, on, onClick, color }: { label: string; on: boolean; onClick: () => void; color: string }) {
  return (
    <button onClick={onClick} className="inline-flex items-center font-semibold rounded-full border transition-colors" style={{ fontSize: "1vw", gap: "0.5vw", padding: "0.55vw 1vw", borderColor: on ? "transparent" : "var(--line)", background: on ? "var(--surface-2)" : "var(--surface)", color: on ? "var(--ink)" : "var(--ink-3)", opacity: on ? 1 : 0.6 }}>
      <span style={{ width: "0.8vw", height: "0.8vw", borderRadius: "50%", background: on ? color : "var(--ink-3)" }} /> {label}
    </button>
  );
}
