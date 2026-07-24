"use client";
// Modo Gestao a Vista (TV/Kiosk). FORA do route group (shell) => SEM menus/chrome.
// 100% indicadores em tempo real, auto-refresh. Densidade/escala NORMAIS do sistema
// (nada de blocos gigantes). Liga via ?kiosk=<token> (grava em localStorage) OU com
// a sessao ja logada. Escopo = pactha_bi_scope (municipio) ou consolidado.
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Wallet, Landmark, Coins, CalendarClock, FileWarning, ShieldCheck, ShieldAlert, Users, HeartPulse,
} from "lucide-react";
import { getOverview, Overview, isRollup } from "@/lib/bi";
import { Gauge, FonteStack, RankingBars, StatBars } from "@/components/bi/charts";
import { MetricCard } from "@/components/bi/ui";
import { formatCurrencyShort, formatInt } from "@/lib/bi-format";

const REFRESH_MS = 45_000;

function TvInner() {
  const params = useSearchParams();
  const [ov, setOv] = useState<Overview | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [ready, setReady] = useState(false);
  const [scopeStr, setScopeStr] = useState<string | null>(null);
  const [fallback, setFallback] = useState(false); // apos 403 num municipio -> consolidado
  const [err, setErr] = useState(false);

  // Bootstrap: grava o token do quiosque e resolve o escopo (URL ?scope= tem
  // prioridade sobre o localStorage — o link do quiosque leva o escopo certo).
  useEffect(() => {
    const kiosk = params.get("kiosk");
    if (kiosk && typeof window !== "undefined") {
      localStorage.setItem("pactha_token", kiosk);
    }
    const sc =
      params.get("scope") ??
      (typeof window !== "undefined" ? localStorage.getItem("pactha_bi_scope") : null);
    setScopeStr(sc);
    setReady(true);
  }, [params]);

  const municipioId = useMemo(() => {
    if (fallback) return null;
    return scopeStr && scopeStr !== "all" && scopeStr !== "__all__" ? Number(scopeStr) : null;
  }, [scopeStr, fallback]);

  useEffect(() => {
    if (!ready) return;
    let cancel = false;
    const load = () => {
      getOverview(municipioId)
        .then((d) => {
          if (!cancel) {
            setOv(d);
            setUpdated(new Date());
            setErr(false);
          }
        })
        .catch(() => {
          if (cancel) return;
          // 403/erro num municipio especifico (escopo fora do token) -> cai p/
          // consolidado do que o token permite, em vez de travar em "Carregando".
          if (municipioId != null) setFallback(true);
          else setErr(true);
        });
    };
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [ready, municipioId]);

  if (!ov) {
    return (
      <div className="grid min-h-screen place-items-center bg-base-200 px-6 text-center text-base-content/50">
        {err ? (
          <div>
            <div className="text-lg font-semibold text-base-content">Não foi possível carregar os indicadores</div>
            <div className="mt-1 text-sm">Verifique o link/token de acesso desta tela.</div>
          </div>
        ) : (
          "Carregando indicadores…"
        )}
      </div>
    );
  }

  const k = ov.kpis;
  const total = (k.valor_total_estadual || 0) + (k.valor_total_federal || 0);
  const s = ov.semaforo;
  const escopo = ov.consolidado
    ? `Consolidado · ${ov.municipios_count} municípios`
    : (!isRollup(s) && s.nome) || "Município";

  const caucPct = isRollup(s) ? (s.total_municipios ? s.regulares / s.total_municipios : 0) : s.regular ? 1 : 0;
  const caucTone = caucPct >= 0.99 ? "ok" : caucPct >= 0.5 ? "warn" : "crit";

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-base-200 p-4">
      {/* Faixa superior */}
      <div className="mb-3 flex items-center gap-3">
        <span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-content font-bold">P</span>
        <div>
          <div className="text-lg font-bold leading-tight text-base-content">Painel de Indicadores</div>
          <div className="text-xs text-base-content/55">{escopo}</div>
        </div>
        <div className="ml-auto flex items-center gap-2 text-xs text-base-content/50">
          <span className="inline-block size-2 animate-pulse rounded-full bg-success" />
          Atualizado {updated ? updated.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" }) : "—"}
        </div>
      </div>

      {/* Grade principal — preenche a tela, densidade normal */}
      <div className="grid min-h-0 flex-1 grid-cols-12 gap-3">
        {/* Coluna esquerda */}
        <div className="col-span-8 flex min-h-0 flex-col gap-3">
          {/* KPIs */}
          <div className="grid grid-cols-4 gap-3">
            <MetricCard icon={Wallet} tone="primary" label="Total captado" value={formatCurrencyShort(total)} />
            <MetricCard icon={Landmark} tone="info" label="Estadual" value={formatCurrencyShort(k.valor_total_estadual)} sub={`${formatInt(k.total_convenios_estadual)} conv.`} />
            <MetricCard icon={Coins} tone="ok" label="Federal" value={formatCurrencyShort(k.valor_total_federal)} sub={`${formatInt(k.total_voluntarias)} prop.`} />
            <MetricCard icon={CalendarClock} tone="warn" label="Vigências ≤120d" value={formatInt(k.alertas_vigencia)} sub={`${formatInt(k.alertas_vigencia_60d)} em 60d`} />
          </div>

          {/* Composição */}
          <div className="rounded-2xl border border-base-300 bg-base-100 p-4">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-base-content">
              <Coins className="size-4 text-primary" /> Composição da captação
            </div>
            <div className="text-3xl font-bold tabular-nums text-base-content">{formatCurrencyShort(total)}</div>
            <FonteStack
              segments={[
                { label: "Estadual (SIGCON)", value: k.valor_total_estadual, color: "var(--chart-2)" },
                { label: "Federal (voluntárias)", value: k.valor_total_federal, color: "var(--chart-1)" },
              ]}
            />
          </div>

          {/* Ranking */}
          <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-base-300 bg-base-100 p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-base-content">
              <Users className="size-4 text-primary" /> Quem mais destinou recurso
            </div>
            <RankingBars
              items={ov.top_parlamentares.slice(0, 6).map((p) => ({
                nome: p.nome_display,
                valor: p.valor_total,
                sub: ov.consolidado && p.municipios.length > 1 ? `${p.municipios.length} municípios` : undefined,
              }))}
            />
          </div>
        </div>

        {/* Coluna direita */}
        <div className="col-span-4 flex min-h-0 flex-col gap-3">
          {/* CAUC */}
          <div className="rounded-2xl border border-base-300 bg-base-100 p-4">
            <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-base-content">
              {caucPct >= 0.99 ? <ShieldCheck className="size-4 text-success" /> : <ShieldAlert className="size-4 text-warning" />}
              Regularidade (CAUC)
            </div>
            <div className="mx-auto max-w-[200px]">
              <Gauge pct={caucPct} tone={caucTone} />
            </div>
            <div className="-mt-2 text-center">
              {isRollup(s) ? (
                <>
                  <div className="text-xl font-bold tabular-nums text-base-content">{s.regulares}/{s.total_municipios}</div>
                  <div className="text-xs text-base-content/60">municípios em dia</div>
                </>
              ) : (
                <div className="text-sm font-semibold text-base-content">
                  {s.regular ? "Em dia" : `${s.pendencias || 0} pendência(s)`}
                </div>
              )}
            </div>
          </div>

          {/* Prazos */}
          <div className="grid grid-cols-2 gap-3">
            <MetricCard icon={FileWarning} tone="crit" label="Prestação vencida" value={formatInt(k.alertas_prestacao_contas)} sub="+90 dias" />
            <MetricCard icon={CalendarClock} tone="warn" label="Vencendo 60d" value={formatInt(k.alertas_vigencia_60d)} />
          </div>

          {/* Saúde */}
          {ov.saude && (
            <div className="rounded-2xl border border-base-300 bg-base-100 p-4">
              <div className="mb-1 flex items-center gap-2 text-sm font-semibold text-base-content">
                <HeartPulse className="size-4 text-primary" /> Saúde (Acordo FES)
              </div>
              <div className="text-2xl font-bold tabular-nums text-base-content">{formatCurrencyShort(ov.saude.divida_atual)}</div>
              <div className="text-xs text-base-content/60">dívida atual do Fundo de Saúde</div>
            </div>
          )}

          {/* CAUC piores (consolidado) */}
          {isRollup(s) && s.por_municipio.some((m) => m.pendencias > 0) && (
            <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-base-300 bg-base-100 p-4">
              <div className="mb-2 text-sm font-semibold text-base-content">Pendências por município</div>
              <StatBars
                items={s.por_municipio.filter((m) => m.pendencias > 0).slice(0, 6).map((m) => ({ label: m.nome, value: m.pendencias }))}
                tone="crit"
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function BiTvPage() {
  return (
    <Suspense fallback={<div className="grid min-h-screen place-items-center bg-base-200">Carregando…</div>}>
      <TvInner />
    </Suspense>
  );
}
