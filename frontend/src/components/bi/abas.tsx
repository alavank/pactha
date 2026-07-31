"use client";
// As SEIS abas do Painel de Indicadores. Cada uma e um componente puro que
// recebe os dados prontos — o MESMO componente e usado no modulo (dentro do
// sistema) e na janela do Modo Tela. So muda a densidade, via `tv`:
//
//   tv=false -> modulo: fonte menor, mais linhas, rolagem.
//   tv=true  -> tela:   fonte maior, menos linhas, sem rolagem (ninguem rola
//               uma TV pendurada na parede).
//
// Nao ha fetch aqui: quem busca e `useAba` (abaixo), para que o slideshow possa
// pre-carregar a proxima aba antes de virar.
import React from "react";
import {
  Wallet, Landmark, Coins, CalendarClock, FileWarning, ShieldCheck, ShieldAlert,
  Users, HeartPulse, Activity, FileCheck2, Stethoscope, Building2, TrendingUp, Info,
  HardHat,
} from "lucide-react";
import {
  AbaDocumentos, AbaEstaduais, AbaFns, AbaParlamentares, AbaSismob, AbaTransfereGov,
  Alertas, CaucItemDetalhe, Lancamento, Overview, isRollup,
} from "@/lib/bi";
import { formatCurrencyShort, formatInt, formatDate, diasLabel } from "@/lib/bi-format";
import {
  BI_CORES, Chip, DotMeter, Gauge, ListaRollup, Metric, Painel, PainelHead,
  RankBars, StackBar, Vazio,
} from "./kit";

const FONTE_LABEL: Record<string, string> = {
  emenda_estadual: "Emenda estadual",
  sigcon: "Convênio SIGCON",
  voluntaria: "Proposta federal",
};

export interface AbaProps {
  tv?: boolean;
}

function grid(tv: boolean | undefined, base: string, tvClass: string) {
  return tv ? tvClass : base;
}

// ==========================================================================
// Geral
// ==========================================================================

export function AbaGeral({ ov, alertas, tv }: AbaProps & { ov: Overview; alertas?: Alertas | null }) {
  const k = ov.kpis;
  const total = (k.valor_total_estadual || 0) + (k.valor_total_federal || 0);
  const s = ov.semaforo;
  const caucPct = isRollup(s)
    ? (s.total_municipios ? s.regulares / s.total_municipios : 0)
    : s.regular ? 1 : 0;
  const caucTom = caucPct >= 0.99 ? "ok" : caucPct >= 0.5 ? "warn" : "crit";
  const vig = alertas?.vigencia ?? [];
  const prest = alertas?.prestacao ?? [];
  const docs = alertas?.documentos ?? [];
  const cg = ov.semaforo_cagec;
  const cagecCrit = !!cg?.tem_dados && (cg.irregulares || 0) > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className={grid(tv, "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5", "grid grid-cols-5 gap-3")}>
        <Metric icon={Wallet} tom="accent" label="Total captado" valor={formatCurrencyShort(total)} grande={tv}
          sub={ov.consolidado ? `${ov.municipios_count} municípios` : undefined} />
        <Metric icon={Landmark} label="Estadual (SIGCON)" valor={formatCurrencyShort(k.valor_total_estadual)}
          sub={`${formatInt(k.total_convenios_estadual)} convênios`} grande={tv} />
        <Metric icon={Coins} label="Federal (voluntárias)" valor={formatCurrencyShort(k.valor_total_federal)}
          sub={`${formatInt(k.total_voluntarias)} propostas`} grande={tv} />
        <Metric icon={CalendarClock} tom="warn" label="Vigências ≤120d" valor={formatInt(k.alertas_vigencia)}
          sub={`${formatInt(k.alertas_vigencia_60d)} em 60 dias`} grande={tv} />
        <Metric icon={FileWarning} tom="crit" label="Prestação vencida" valor={formatInt(k.alertas_prestacao_contas)}
          sub="há mais de 90 dias" grande={tv} />
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3", "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel>
          <PainelHead icon={TrendingUp} titulo="Composição da captação" sub="de onde veio o recurso" />
          <div className="bi-num mb-3 text-[28px] leading-none">{formatCurrencyShort(total)}</div>
          <StackBar
            segments={[
              { label: "Estadual", valor: k.valor_total_estadual, cor: BI_CORES[3] },
              { label: "Federal", valor: k.valor_total_federal, cor: BI_CORES[2] },
            ]}
          />
          {ov.execucao?.total ? (
            <div className="mt-4">
              <DotMeter
                label="Convênios em execução (repasse recebido)"
                pct={ov.execucao.valor_total ? (ov.execucao.valor_repassado || 0) / ov.execucao.valor_total : 0}
                direita={`${formatCurrencyShort(ov.execucao.valor_repassado || 0)} de ${formatCurrencyShort(ov.execucao.valor_total)}`}
              />
            </div>
          ) : null}
        </Painel>

        {/* AS DUAS ESFERAS NO MESMO CARD.
            Este medidor era só do CAUC e escrevia "Em dia · sem pendências"
            para um município IRREGULAR no CAGEC — é o sinal mais visível do
            painel, e dizer "em dia" com convênio estadual travado é o pior erro
            que ele pode cometer. Regular na União não é regular em Minas: são
            esferas independentes, e a estadual ainda trava o PAGAMENTO de
            convênio já assinado. O medidor continua sendo o do CAUC (é o que
            tem percentual); o CAGEC entra como faixa de status logo abaixo,
            com o mesmo peso de cor. */}
        <Painel>
          <PainelHead
            icon={caucPct >= 0.99 && !cagecCrit ? ShieldCheck : ShieldAlert}
            titulo="Regularidade"
            sub="aptidão para receber transferências"
          />
          <div className="flex flex-1 flex-col items-center justify-center gap-3">
            <Gauge
              pct={caucPct}
              tom={caucTom}
              size={tv ? 176 : 148}
              centro={isRollup(s) ? `${s.regulares}/${s.total_municipios}` : s.regular ? "Em dia" : `${s.pendencias || 0}`}
              legenda={isRollup(s) ? "municípios em dia (CAUC)" : s.regular ? "CAUC · sem pendências" : "CAUC · pendência(s) impeditiva(s)"}
            />
            <div
              className="w-full rounded-lg px-3 py-2"
              style={{
                background: cg?.tem_dados
                  ? `color-mix(in oklab, var(--bi-${cagecCrit ? "crit" : "ok"}) 13%, transparent)`
                  : "color-mix(in oklab, var(--bi-warn) 11%, transparent)",
              }}
            >
              <div className="flex items-baseline gap-2">
                <span className="text-[11px] font-semibold"
                  style={{ color: `var(--bi-${!cg?.tem_dados ? "warn" : cagecCrit ? "crit" : "ok"})` }}>
                  CAGEC — Minas Gerais
                </span>
                <span className="bi-num ml-auto text-[12px] font-bold"
                  style={{ color: `var(--bi-${!cg?.tem_dados ? "warn" : cagecCrit ? "crit" : "ok"})` }}>
                  {!cg?.tem_dados ? "sem coleta"
                    : cagecCrit ? (cg.situacao || `${cg.irregulares} irregular(es)`)
                    : "Em dia"}
                </span>
              </div>
              <div className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                {!cg?.tem_dados
                  ? "regularidade estadual ainda não coletada"
                  : cagecCrit
                    ? `${cg.quem?.[0]?.nome ? `${cg.quem[0].nome.slice(0, 34)} — ` : ""}`
                      + "impede convênio estadual e liberação de parcela"
                    : `${cg.entidades} cadastro(s) do município em situação regular`}
              </div>
            </div>
          </div>
        </Painel>

        <Painel className="min-h-0">
          <PainelHead icon={Activity} titulo="Em execução agora" sub="instrumentos com vigência aberta" />
          {ov.execucao?.itens?.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
              {ov.execucao.itens.slice(0, tv ? 6 : 10).map((e) => (
                <li key={`${e.id}-${e.numero}`} className="bi-card-flat px-2.5 py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px] font-medium">{e.objeto || e.numero || "—"}</span>
                    <span className="bi-num ml-auto shrink-0 text-[12px]">{formatCurrencyShort(e.valor)}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    <span className="truncate">{e.orgao || "—"}</span>
                    <span className="ml-auto shrink-0">
                      {e.dias_restantes != null ? diasLabel(e.dias_restantes) : "—"}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhum instrumento com vigência aberta no período.</Vazio>
          )}
        </Painel>
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3", "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel className="min-h-0">
          <PainelHead icon={CalendarClock} titulo="Vencendo" sub="vigências nos próximos 120 dias"
            right={<Chip tom="warn">{vig.length}</Chip>} />
          {vig.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col divide-y overflow-y-auto pr-1"
              style={{ borderColor: "var(--bi-line)" }}>
              {vig.slice(0, tv ? 6 : 12).map((a, i) => (
                <li key={`${a.esfera}-${a.id}-${i}`} className="py-1.5">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px]">{a.objeto || a.nr_sigcon || a.nr_convenio || "—"}</span>
                    <Chip tom={a.dias_restantes <= 60 ? "crit" : "warn"} className="ml-auto shrink-0">
                      {diasLabel(a.dias_restantes)}
                    </Chip>
                  </div>
                  <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {a.orgao_concedente || "—"} · {formatDate(a.dt_fim_vigencia)}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhuma vigência vencendo nos próximos 120 dias.</Vazio>
          )}
        </Painel>

        <Painel className="min-h-0">
          <PainelHead icon={FileWarning} titulo="Prestação de contas" sub="vencidas há mais de 90 dias"
            right={<Chip tom="crit">{prest.length}</Chip>} />
          {prest.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col divide-y overflow-y-auto pr-1"
              style={{ borderColor: "var(--bi-line)" }}>
              {prest.slice(0, tv ? 6 : 12).map((a, i) => (
                <li key={`${a.esfera}-${a.id}-${i}`} className="py-1.5">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px]">{a.objeto || a.nr_sigcon || a.nr_convenio || "—"}</span>
                    <span className="bi-num ml-auto shrink-0 text-[12px]">
                      {a.valor_total ? formatCurrencyShort(a.valor_total) : "—"}
                    </span>
                  </div>
                  <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {a.orgao_concedente || "—"} · encerrou em {formatDate(a.dt_fim_vigencia)}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhuma prestação de contas em atraso.</Vazio>
          )}
        </Painel>

        {/* DOCUMENTAÇÃO VENCENDO — o alerta que faltava. Os dois painéis ao lado
            avisam sobre convênio; nenhum avisava que uma CERTIDÃO está para
            vencer, que é o que trava o convênio seguinte. Só prazos de verdade
            entram aqui: o backend descarta as datas que são apenas a cadência de
            atualização do extrato do CAUC (seriam 17 avisos por dia). */}
        <Painel className="min-h-0">
          <PainelHead icon={ShieldAlert} titulo="Documentação vencendo" sub="certidões nos próximos 30 dias"
            right={<Chip tom={docs.length ? "warn" : "ok"}>{docs.length}</Chip>} />
          {docs.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col divide-y overflow-y-auto pr-1"
              style={{ borderColor: "var(--bi-line)" }}>
              {docs.slice(0, tv ? 6 : 12).map((a, i) => (
                <li key={`${a.esfera}-${a.codigo}-${i}`} className="py-1.5">
                  <div className="flex items-start gap-2">
                    <span className="flex-1 text-[12px] leading-snug">{a.label || a.codigo}</span>
                    <Chip tom={a.dias_restantes <= 7 ? "crit" : "warn"} className="shrink-0">
                      {a.dias_restantes === 0 ? "hoje" : diasLabel(a.dias_restantes)}
                    </Chip>
                  </div>
                  <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {/* `entidade` so vem preenchida quando o prazo NAO e da
                        prefeitura. O CAGEC tem um cadastro por entidade e cada
                        um trava so o SEU convenio — sem este rotulo, o prazo do
                        Fundo Municipal de Saude era lido como se fosse da
                        Prefeitura, num painel cujo resto fala so do municipio. */}
                    {a.esfera}{a.entidade ? ` · ${a.entidade}` : ""} · vence em {formatDate(a.validade)}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhuma certidão vencendo nos próximos 30 dias.</Vazio>
          )}
        </Painel>
      </div>
    </div>
  );
}

// ==========================================================================
// Parlamentares — cada emenda com destinação e finalidade
// ==========================================================================

function LinhaLancamento({ l }: { l: Lancamento }) {
  return (
    <li className="bi-card-flat px-2.5 py-2">
      <div className="flex items-baseline gap-2">
        <span className="truncate text-[12px] font-medium">{l.finalidade || l.numero || "—"}</span>
        <span className="bi-num ml-auto shrink-0 text-[12px]">{formatCurrencyShort(l.valor)}</span>
      </div>
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
        <span className="rounded px-1" style={{ background: "var(--bi-line)" }}>
          {FONTE_LABEL[l.fonte] || l.fonte}
        </span>
        {l.destinacao && <span className="truncate">→ {l.destinacao}</span>}
        {l.orgao && <span className="truncate">· {l.orgao}</span>}
        {l.ano && <span>· {l.ano}</span>}
        {l.situacao && <span className="truncate">· {l.situacao}</span>}
      </div>
    </li>
  );
}

export function AbaParlamentaresView({ d, tv }: AbaProps & { d: AbaParlamentares }) {
  const top = d.itens.slice(0, tv ? 4 : 8);
  if (!d.itens.length) {
    return (
      <Painel className="flex-1">
        <PainelHead icon={Users} titulo="Parlamentares" />
        <Vazio>Nenhuma emenda de parlamentar no período selecionado.</Vazio>
      </Painel>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric icon={Users} tom="accent" label="Parlamentares" valor={formatInt(d.total)} grande={tv} />
        <Metric icon={Wallet} label="Valor destinado" valor={formatCurrencyShort(d.valor_total)} grande={tv} />
        <Metric icon={Coins} label="Lançamentos"
          valor={formatInt(d.itens.reduce((s, i) => s + i.total_lancamentos, 0))} grande={tv} />
        <Metric icon={TrendingUp} label="Maior destinação"
          valor={formatCurrencyShort(d.itens[0]?.valor_total || 0)}
          sub={d.itens[0]?.nome} grande={tv} />
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3", "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel className="min-h-0">
          <PainelHead icon={Users} titulo="Quem mais destinou" sub="no período selecionado" />
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
            <RankBars
              items={d.itens.slice(0, tv ? 7 : 12).map((p) => ({
                nome: p.nome,
                valor: p.valor_total,
                sub: `${p.total_lancamentos} lançamento(s)`,
              }))}
              formatar={formatCurrencyShort}
            />
          </div>
        </Painel>

        {/* lg: no celular a grade-mae tem UMA coluna, e um col-span-2 sem
            breakpoint criava a segunda trilha — a grade ficava mais larga que
            a tela e o app ganhava rolagem lateral. */}
        <div className="grid grid-cols-1 min-h-0 gap-3 sm:grid-cols-2 lg:col-span-2">
          {top.map((p) => (
            <Painel key={p.nome_normalizado} className="min-h-0">
              <PainelHead
                icon={Users}
                titulo={p.nome}
                sub={`${p.total_lancamentos} lançamento(s) · ${p.municipios.join(", ") || "—"}`}
                right={<span className="bi-num text-[13px]">{formatCurrencyShort(p.valor_total)}</span>}
              />
              <ul className="bi-scroll flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
                {p.lancamentos.slice(0, tv ? 4 : 8).map((l, i) => (
                  <LinhaLancamento key={`${l.fonte}-${l.numero}-${i}`} l={l} />
                ))}
              </ul>
              {p.lancamentos_ocultos > 0 && (
                <div className="mt-1.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  + {p.lancamentos_ocultos} lançamento(s) não exibido(s)
                </div>
              )}
            </Painel>
          ))}
        </div>
      </div>
    </div>
  );
}

// ==========================================================================
// TransfereGov
// ==========================================================================

export function AbaTransfereGovView({ d, tv }: AbaProps & { d: AbaTransfereGov }) {
  const v = d.voluntarias;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric icon={Coins} tom="accent" label="Propostas federais" valor={formatInt(v.total)} grande={tv} />
        <Metric icon={Wallet} label="Valor global" valor={formatCurrencyShort(v.valor_total)} grande={tv} />
        <Metric icon={Landmark} label="Repasse da União" valor={formatCurrencyShort(v.valor_repasse)} grande={tv} />
        <Metric icon={Activity} tom="ok" label="Em execução" valor={formatInt(v.em_execucao)}
          sub={d.pac.total ? `${formatInt(d.pac.total)} no Novo PAC` : undefined} grande={tv} />
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3", "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel className="min-h-0">
          <PainelHead icon={Activity} titulo="Por situação" />
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
            <ListaRollup items={v.por_situacao} formatar={formatCurrencyShort} max={tv ? 6 : 8} />
          </div>
        </Painel>
        <Painel className="min-h-0">
          <PainelHead icon={Building2} titulo="Por órgão concedente" />
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
            <ListaRollup items={v.por_orgao} formatar={formatCurrencyShort} max={tv ? 6 : 8} />
          </div>
        </Painel>
        <Painel className="min-h-0">
          <PainelHead icon={TrendingUp} titulo="Novo PAC" sub={`${formatInt(d.pac.total)} seleções`} />
          {d.pac.total ? (
            <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
              <ListaRollup items={d.pac.por_orgao} formatar={formatCurrencyShort} max={tv ? 6 : 8} />
            </div>
          ) : (
            <Vazio>Nenhuma seleção do Novo PAC no período.</Vazio>
          )}
        </Painel>
      </div>

      <Painel className="min-h-0 flex-1">
        <PainelHead icon={Coins} titulo="Maiores propostas" sub="valor global, do maior para o menor" />
        {v.itens.length ? (
          <ul className="bi-scroll flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
            {v.itens.slice(0, tv ? 7 : 20).map((it) => (
              <li key={it.id} className="bi-card-flat px-2.5 py-2">
                <div className="flex items-baseline gap-2">
                  <span className="truncate text-[12px] font-medium">{it.objeto || it.numero}</span>
                  <span className="bi-num ml-auto shrink-0 text-[12px]">{formatCurrencyShort(it.valor)}</span>
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  <span>{it.numero}</span>
                  {it.orgao && <span className="truncate">· {it.orgao}</span>}
                  {it.situacao && <span className="truncate">· {it.situacao}</span>}
                  {it.parlamentar && <span className="truncate">· emenda de {it.parlamentar}</span>}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <Vazio>Nenhuma proposta federal no período.</Vazio>
        )}
      </Painel>
    </div>
  );
}

// ==========================================================================
// Verbas estaduais
// ==========================================================================

export function AbaEstaduaisView({ d, tv }: AbaProps & { d: AbaEstaduais }) {
  const c = d.convenios;
  const e = d.emendas;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric icon={Landmark} tom="accent" label="Convênios SIGCON" valor={formatInt(c.total)} grande={tv} />
        <Metric icon={Wallet} label="Valor conveniado" valor={formatCurrencyShort(c.valor_total)} grande={tv} />
        <Metric icon={Coins} label="Já repassado" valor={formatCurrencyShort(c.valor_repassado)}
          sub={c.valor_total ? `${Math.round((c.valor_repassado / c.valor_total) * 100)}% do total` : undefined}
          grande={tv} />
        <Metric icon={FileCheck2} label="Emendas estaduais" valor={formatInt(e.total)}
          sub={formatCurrencyShort(e.valor_total)} grande={tv} />
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3", "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel className="min-h-0">
          <PainelHead icon={Activity} titulo="Convênios por situação" />
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
            <ListaRollup items={c.por_situacao} formatar={formatCurrencyShort} max={tv ? 6 : 8} />
          </div>
        </Painel>
        <Painel className="min-h-0">
          <PainelHead icon={Building2} titulo="Por órgão concedente" />
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
            <ListaRollup items={c.por_orgao} formatar={formatCurrencyShort} max={tv ? 6 : 8} />
          </div>
        </Painel>
        <Painel className="min-h-0">
          <PainelHead icon={FileCheck2} titulo="Emendas por situação" />
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto pr-1">
            <ListaRollup items={e.por_situacao} formatar={formatCurrencyShort} max={tv ? 6 : 8} />
          </div>
        </Painel>
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-2", "grid min-h-0 flex-1 grid-cols-2 gap-3")}>
        <Painel className="min-h-0">
          <PainelHead icon={Landmark} titulo="Maiores convênios" />
          {c.itens.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
              {c.itens.slice(0, tv ? 6 : 15).map((it) => (
                <li key={it.id} className="bi-card-flat px-2.5 py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px] font-medium">{it.objeto || it.numero}</span>
                    <span className="bi-num ml-auto shrink-0 text-[12px]">{formatCurrencyShort(it.valor)}</span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    <span>{it.numero}</span>
                    {it.orgao && <span className="truncate">· {it.orgao}</span>}
                    {it.situacao && <span className="truncate">· {it.situacao}</span>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhum convênio estadual no período.</Vazio>
          )}
        </Painel>

        <Painel className="min-h-0">
          <PainelHead icon={FileCheck2} titulo="Emendas estaduais" sub="destinação e finalidade" />
          {e.itens.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
              {e.itens.slice(0, tv ? 6 : 15).map((it) => (
                <li key={it.id} className="bi-card-flat px-2.5 py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px] font-medium">{it.finalidade || it.numero}</span>
                    <span className="bi-num ml-auto shrink-0 text-[12px]">{formatCurrencyShort(it.valor)}</span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {it.parlamentar && <span className="truncate">{it.parlamentar}</span>}
                    {it.destinacao && <span className="truncate">→ {it.destinacao}</span>}
                    {it.situacao && <span className="truncate">· {it.situacao}</span>}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhuma emenda estadual no período.</Vazio>
          )}
        </Painel>
      </div>
    </div>
  );
}

// ==========================================================================
// Documentação — CAUC e CAGEC
// ==========================================================================

/** Cabeçalho de ESFERA (União / Minas). É o que impede o CAUC e o CAGEC de
 *  virarem uma sopa de blocos quando os dois tiverem dado. */
function EsferaHead({
  titulo, sub, contagem,
}: { titulo: string; sub: string; contagem?: string }) {
  return (
    <div
      className="mb-2 flex flex-wrap items-baseline gap-x-2 border-b pb-1.5"
      style={{ borderColor: "var(--bi-line-strong)" }}
    >
      <span className="bi-title text-[15px]">{titulo}</span>
      <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>{sub}</span>
      {contagem && (
        <span className="bi-num ml-auto text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {contagem}
        </span>
      )}
    </div>
  );
}

/** Uma exigência por linha: código, rótulo e status. Serve CAUC e CAGEC — o
 *  payload das duas esferas tem o mesmo formato de propósito. */
function ListaExigencias({ itens, tv }: { itens: CaucItemDetalhe[]; tv?: boolean }) {
  return (
    <ul className="flex flex-col">
      {itens.map((i) => {
        const pendente = i.tipo === "pendente";
        return (
          // O texto QUEBRA em vez de ser cortado. Truncar deixava linhas como
          // "Certidão de Débitos Relativos a Créditos …", que não dizem QUAL
          // certidão é — exatamente o dado necessário para agir.
          <li
            key={i.codigo}
            className={`flex items-start gap-2 rounded py-[3px] ${pendente ? "-mx-1.5 px-1.5" : ""}`}
            style={pendente
              ? { background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)" }
              : undefined}
          >
            <span className="bi-num mt-[2px] shrink-0 text-[10px]" style={{ color: "var(--bi-faint)" }}>
              {i.codigo}
            </span>
            <span
              className={`flex-1 leading-snug ${tv ? "text-[13px]" : "text-[12px]"} ${pendente ? "font-semibold" : ""}`}
              style={i.tipo === "na" ? { color: "var(--bi-faint)" }
                : pendente ? { color: "var(--bi-crit)" } : undefined}
            >
              {i.label}
            </span>
            {/* Pendência vira CHIP: o status é o que o olho precisa achar de
                longe. Chip só no status, não em volta do título — envolver o
                texto todo comeria a largura que o título precisa para ser lido. */}
            {pendente ? (
              <span
                className="bi-num shrink-0 rounded px-1.5 py-[1px] text-[9px] font-bold tracking-wide"
                style={{ background: "var(--bi-crit)", color: "#fff" }}
              >
                {/* So anexa o valor quando ele for DATA. Nas 6 pendencias do
                    CAUC o `valor` e o marcador bruto do CSV do Tesouro, entao o
                    chip saia literalmente "PENDENTE · !" na TV e no celular. No
                    CAGEC o valor E a data em que venceu, e ela e util — mas
                    precisa do verbo, senao "PENDENTE · 29/07/2026" e lido como
                    prazo FUTURO quando e a data do vencimento. */}
                {/^\d{2}\/\d{2}\/\d{2,4}$/.test(i.valor || "")
                  ? `PENDENTE · venceu ${i.valor}`
                  : "PENDENTE"}
              </span>
            ) : (
              <span
                className="bi-num mt-[2px] shrink-0 text-[10px]"
                style={{ color: i.tipo === "regular" ? "var(--bi-ok)" : "var(--bi-faint)" }}
              >
                {i.tipo === "na" ? (i.status || "indisponível") : i.valor}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function AbaDocumentosView({
  d, tv, esfera,
}: AbaProps & { d: AbaDocumentos; esfera?: "cauc" | "cagec" }) {
  const c = d.cauc;
  const pct = c.com_dados ? c.regulares / c.com_dados : 0;
  const primeiro = c.por_municipio[0];

  // Agrupa por bloco, na ordem em que o CAUC numera (1.x, 2.x, 3.x) — a mesma
  // do módulo. `itens` traz TODAS as exigências; se a API for antiga e não
  // mandar, remonta com o que existe (sem as "não exigidas", que só vêm ali).
  const blocos = React.useMemo(() => {
    const todos =
      primeiro?.itens ??
      [...(primeiro?.itens_pendentes ?? []), ...(primeiro?.itens_regulares ?? [])];
    const porGrupo = new Map<string, typeof todos>();
    for (const i of todos) {
      const g = i.grupo || "Outras";
      if (!porGrupo.has(g)) porGrupo.set(g, []);
      porGrupo.get(g)!.push(i);
    }
    return [...porGrupo.entries()];
  }, [primeiro]);

  // CAGEC do mesmo município — agora coletado, e agrupado igual ao CAUC:
  // Credenciamento do Representante Legal, Habilitação Jurídica, Regularidade
  // Fiscal e Trabalhista, Responsabilidade e Transparência Fiscal, Adimplência
  // com o Estado. O scraper já preenche `grupo`; era a tela que jogava as 27
  // linhas num bloco só.
  const cagec = d.cagec.por_municipio[0];
  const blocosCagec = React.useMemo(() => {
    const porGrupo = new Map<string, CaucItemDetalhe[]>();
    for (const i of cagec?.itens ?? []) {
      const g = i.grupo || "Outras";
      if (!porGrupo.has(g)) porGrupo.set(g, []);
      porGrupo.get(g)!.push(i);
    }
    return [...porGrupo.entries()];
  }, [cagec]);

  const pendCagec = (cagec?.itens ?? []).filter((i) => i.tipo === "pendente").length;
  const cagecIrregular = !!cagec && cagec.regular === false;
  const soUmaEsfera = esfera === "cauc" || esfera === "cagec";

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {/* AS DUAS ESFERAS NOS CARTÕES. Antes os quatro cartões falavam só do
            CAUC: com o município IRREGULAR no CAGEC, o topo da tela dizia
            "Em dia" e "0 impeditivos" — tranquilizando o gestor sobre um
            convênio estadual que está travado. Regular na União não é regular
            em Minas, e o resumo tem que mostrar as duas. */}
        <Metric icon={ShieldCheck} tom={pct >= 0.99 ? "ok" : "crit"} label="CAUC — União"
          valor={pct >= 0.99 ? "Em dia" : `${formatInt(c.pendencias_total)} pendência(s)`}
          sub="transferências federais" grande={tv} />
        <Metric icon={ShieldAlert} tom={cagec ? (cagecIrregular ? "crit" : "ok") : "warn"}
          label="CAGEC — Minas Gerais"
          valor={!cagec ? "Sem coleta" : cagecIrregular ? (cagec.situacao || "Irregular") : "Em dia"}
          sub="convênios estaduais" grande={tv} />
        <Metric icon={FileCheck2} tom={(primeiro?.itens_pendentes.length || 0) + pendCagec ? "crit" : "ok"}
          label="Pendências (as duas)"
          valor={formatInt((primeiro?.itens_pendentes.length || 0) + pendCagec)}
          sub={`de ${(primeiro?.total_itens ?? 0) + (cagec?.itens?.length ?? 0)} exigências`} grande={tv} />
        <Metric icon={CalendarClock} label="Última consulta"
          valor={primeiro?.data_pesquisa ? formatDate(primeiro.data_pesquisa) : "—"} grande={tv} />
      </div>

      {/* DUAS ESFERAS, CADA UMA NA SUA SEÇÃO ROTULADA.
          Antes os blocos do CAUC e o do CAGEC corriam no MESMO fluxo de colunas:
          nada dizia onde acabava a União e começava o Estado, e no dia em que o
          CAGEC trouxer dados os blocos se embaralhariam. Cada esfera tem título,
          fonte e o seu próprio fluxo — a fronteira é visível mesmo de longe.
          CAUC ocupa 2/3 porque tem ~25 exigências em 5 blocos; o CAGEC, 1/3. */}
      <div className="bi-scroll min-h-0 flex-1 overflow-y-auto">
        {/* DUAS COLUNAS IGUAIS: União à esquerda, Minas à direita, cada uma com
            sua lista descendo. A divisão anterior era 3/1 e espremia o CAGEC em
            um quarto da largura — os nomes das exigências vinham cortados no
            meio ("Certidão de Débitos Relativos a Créditos …"), o contador
            escorregava para a linha de baixo e saía do alinhamento com o CAUC,
            e as 27 linhas ficavam num bloco só, sem as subdivisões que o CAUC
            tem. Metade da tela para cada esfera dá largura para o texto e deixa
            as duas colunas alinhadas. Custa rolagem — aceitável, inclusive na
            TV, porque ler pela metade não serve para nada. */}
        <div className={`grid grid-cols-1 gap-x-4 gap-y-3 ${soUmaEsfera ? "" : "lg:grid-cols-2"}`}>
          {esfera !== "cagec" && (
          <section className="min-w-0">
            <EsferaHead
              titulo="CAUC — União"
              sub="Tesouro Nacional · exigências federais"
              /* Conta o que esta NA TELA. `total_itens` exclui os `na`, entao
                 o cabecalho dizia "25 exigencias" sobre blocos que somam 28 —
                 e nenhum dos dois numeros batia com o extrato. */
              contagem={blocos.length
                ? `${blocos.reduce((n, [, it]) => n + it.length, 0)} exigências · ${
                    (primeiro?.itens ?? []).filter((x) => x.tipo === "na").length
                  } desativadas na origem`
                : undefined}
            />
            {blocos.length ? (
              <div className={soUmaEsfera && tv ? "bi-colunas-2" : ""}>
                {blocos.map(([grupo, itens]) => (
                  <Painel key={grupo} className="mb-3 break-inside-avoid">
                    <PainelHead icon={ShieldCheck} titulo={grupo} sub={`${itens.length} exigência(s)`} />
                    <ListaExigencias itens={itens} tv={tv} />
                  </Painel>
                ))}
              </div>
            ) : (
              <Painel><Vazio>Sem dados de CAUC coletados.</Vazio></Painel>
            )}
          </section>
          )}

          {esfera !== "cauc" && (
          <section className="min-w-0">
            <EsferaHead
              titulo="CAGEC — Minas Gerais"
              sub="Cadastro Geral de Convenentes · exigências estaduais"
              /* "27 exigencias" nao existe em documento nenhum: o CRC tem 24
                 documentos, e as outras 3 linhas (CADIN-MG, SIAFI-MG, mandato)
                 vem do CABECALHO do certificado. Separar por procedencia. */
              contagem={cagec?.itens?.length
                ? `${cagec.itens.length} linhas · ${
                    cagec.itens.filter((x) => !["CADIN-MG", "SIAFI-MG", "MANDATO"].includes(x.codigo || "")).length
                  } documentos do CRC`
                : "aguardando coleta"}
            />
            {/* Situação em destaque ANTES da lista: irregular no CAGEC trava
                convênio estadual e pagamento de parcela, e isso não pode ficar
                escondido no meio de 27 linhas. */}
            {cagecIrregular && (
              <div
                className="mb-3 flex items-start gap-2 rounded-lg px-3 py-2"
                style={{ background: "color-mix(in oklab, var(--bi-crit) 15%, transparent)" }}
              >
                <ShieldAlert className="mt-[1px] size-4 shrink-0" style={{ color: "var(--bi-crit)" }} />
                <p className="text-[11px] font-semibold leading-snug" style={{ color: "var(--bi-crit)" }}>
                  Situação {cagec?.situacao || "Irregular"} no CAGEC
                  {pendCagec ? ` · ${pendCagec} pendência(s)` : ""} — impede assinar convênio
                  estadual e liberação de parcela.
                </p>
              </div>
            )}
            {blocosCagec.length ? (
              <div className={soUmaEsfera && tv ? "bi-colunas-2" : ""}>
                {blocosCagec.map(([grupo, itens]) => (
                  <Painel key={grupo} className="mb-3 break-inside-avoid">
                    <PainelHead icon={ShieldCheck} titulo={grupo} sub={`${itens.length} exigência(s)`} />
                    <ListaExigencias itens={itens} tv={tv} />
                  </Painel>
                ))}
              </div>
            ) : (
              /* Fica explícito que NÃO está verde por estar em dia — é que
                 falta o dado. Verde aqui seria lido como "o Estado está em
                 dia", que é pior que a ausência. */
              <Painel className="mb-3">
                <div className="flex items-start gap-2">
                  <Info className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn)" }} />
                  <p className="text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                    {d.cagec.motivo}
                  </p>
                </div>
              </Painel>
            )}
          </section>
          )}
        </div>
      </div>
    </div>
  );
}

// ==========================================================================
// FNS
// ==========================================================================

export function AbaFnsView({ d, tv }: AbaProps & { d: AbaFns }) {
  const t = d.totais;
  const pctPago = t.valor_proposta ? t.valor_pago / t.valor_proposta : 0;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric icon={Stethoscope} tom="accent" label="Propostas no FNS" valor={formatInt(d.total)}
          sub={d.anos.join(", ")} grande={tv} />
        <Metric icon={Wallet} label="Valor das propostas" valor={formatCurrencyShort(t.valor_proposta)} grande={tv} />
        <Metric icon={HeartPulse} tom="ok" label="Já pago" valor={formatCurrencyShort(t.valor_pago)}
          sub={`${Math.round(pctPago * 100)}% do total`} grande={tv} />
        <Metric icon={CalendarClock} tom="warn" label="A pagar" valor={formatCurrencyShort(t.valor_pagar)} grande={tv} />
      </div>

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3", "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel>
          <PainelHead icon={CalendarClock} titulo="Por ano" />
          {d.por_ano.length ? (
            <div className="flex flex-col gap-1">
              {d.por_ano.map((a) => (
                <DotMeter
                  key={a.ano}
                  label={`${a.ano} · ${a.total} proposta(s)`}
                  pct={a.valor_proposta ? a.valor_pago / a.valor_proposta : 0}
                  direita={formatCurrencyShort(a.valor_proposta)}
                  dots={18}
                />
              ))}
            </div>
          ) : (
            <Vazio>Sem propostas no período.</Vazio>
          )}
        </Painel>

        {/* lg: ver comentario acima — col-span sem breakpoint estoura no celular */}
        <Painel className="min-h-0 lg:col-span-2">
          <PainelHead icon={Stethoscope} titulo="Propostas" sub="maior valor primeiro" />
          {d.itens.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto pr-1">
              {d.itens.slice(0, tv ? 8 : 24).map((it, i) => (
                <li key={`${it.nu_processo}-${i}`} className="bi-card-flat px-2.5 py-2">
                  <div className="flex items-baseline gap-2">
                    <span className="truncate text-[12px] font-medium">
                      {it.tipo_proposta || it.nu_processo || "Proposta"}
                    </span>
                    <span className="bi-num ml-auto shrink-0 text-[12px]">
                      {formatCurrencyShort(it.valor_proposta)}
                    </span>
                  </div>
                  <div className="mt-0.5 flex flex-wrap gap-x-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    <span>{it.ano}</span>
                    {it.tipo_recurso && <span className="truncate">· {it.tipo_recurso}</span>}
                    <span>· pago {formatCurrencyShort(it.valor_pago)}</span>
                    <span>· a pagar {formatCurrencyShort(it.valor_pagar)}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>
              {d.erros.length
                ? "Não foi possível consultar o Fundo Nacional de Saúde agora."
                : "Nenhuma proposta no FNS para os anos selecionados."}
            </Vazio>
          )}
        </Painel>
      </div>
    </div>
  );
}

// ==========================================================================
// Obras da Saúde (SISMOB)
// ==========================================================================

export function AbaSismobView({ d, tv }: AbaProps & { d: AbaSismob }) {
  const t = d.totais;
  const acao = d.acao ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric icon={HardHat} tom="accent" label="Obras em andamento"
          valor={formatInt(t.vivas)} sub={`${formatInt(t.obras)} no total`} grande={tv} />
        <Metric icon={Wallet} label="Já repassado"
          valor={formatCurrencyShort(t.repasse_total)}
          sub={`de ${formatCurrencyShort(t.valor_proposta)} aprovados`} grande={tv} />
        <Metric icon={FileWarning} tom={t.repasse_parado ? "crit" : "ok"} label="Parado"
          valor={formatCurrencyShort(t.repasse_parado)}
          sub={t.repasse_parado ? "sem atualização há +60 dias" : "nada parado"} grande={tv} />
        <Metric icon={CalendarClock} tom={t.com_prazo_vencido ? "warn" : "ok"}
          label="Prazo de etapa vencido" valor={formatInt(t.com_prazo_vencido)}
          sub="90 dias após o repasse" grande={tv} />
      </div>

      {/* O seletor de periodo do Painel continua na tela (ele vale para as
          outras abas), mas nao muda nada aqui. Dizer isso em uma linha evita
          as duas leituras erradas: "a aba travou" e, pior, "no periodo atual
          nao ha obra com problema" — uma obra proposta em 2012 que segue
          cancelada com dinheiro a devolver e problema de HOJE. */}
      {d.sem_filtro_periodo && !tv ? (
        <p className="text-xs opacity-60">
          Obras não são filtradas por período: uma obra proposta em anos
          anteriores e ainda em aberto continua sendo obrigação do presente.
        </p>
      ) : null}

      <div className={grid(tv, "grid grid-cols-1 min-h-0 gap-3 lg:grid-cols-3",
                              "grid min-h-0 flex-1 grid-cols-3 gap-3")}>
        <Painel className="min-h-0 lg:col-span-2">
          <PainelHead icon={FileWarning} titulo="Precisa de ação"
            sub="prazo de norma, obra parada ou recurso a devolver"
            right={<Chip tom={acao.length ? "crit" : "ok"}>{acao.length}</Chip>} />
          {acao.length ? (
            <ul className="bi-scroll flex min-h-0 flex-1 flex-col divide-y overflow-y-auto pr-1"
              style={{ borderColor: "var(--bi-line)" }}>
              {/* Na TV, no máximo 4 e UMA frase por obra: painel de parede é
                  lido de longe e ninguém rola. O detalhe fica no módulo. */}
              {acao.slice(0, tv ? 4 : 12).map((o) => (
                <li key={o.proposta_id} className="py-1.5">
                  <div className="flex items-start gap-2">
                    <span className={`flex-1 leading-snug ${tv ? "text-[13px]" : "text-[12px]"}`}>
                      {o.estabelecimento || o.programa || `Obra ${o.proposta_id}`}
                    </span>
                    <Chip tom={o.severidade === "critico" ? "crit" : "warn"} className="shrink-0">
                      {o.percentual != null ? `${o.percentual}%` : "—"}
                    </Chip>
                  </div>
                  <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {o.problema}
                    {(o.problemas || 0) > 1 ? ` · +${(o.problemas || 1) - 1}` : ""}
                    {o.municipio ? ` · ${o.municipio}` : ""}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <Vazio>Nenhuma obra com prazo vencido ou parada.</Vazio>
          )}
        </Painel>

        <Painel className="min-h-0">
          <PainelHead icon={Activity} titulo="Execução" sub="obras em andamento" />
          {d.execucao?.length ? (
            <div className="bi-scroll flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
              {d.execucao.slice(0, tv ? 5 : 10).map((o) => (
                // `percentual` null = a obra nunca informou medicao ao MS, e nao
                // "0% executado". A barra fica vazia nos dois casos (distinguir
                // exigiria um estado novo no DotMeter, que e compartilhado com
                // outras abas), mas o RÓTULO tem que dizer a verdade: as duas
                // maiores obras da carteira estao sem medicao, e "0%" numa TV de
                // gabinete e lido como obra parada.
                <DotMeter key={o.proposta_id}
                  label={(o.estabelecimento || o.programa || "Obra") as string}
                  pct={(o.percentual ?? 0) / 100}
                  direita={o.percentual != null ? `${o.percentual}%` : "sem medição"} />
              ))}
            </div>
          ) : (
            <Vazio>Nenhuma obra em execução.</Vazio>
          )}
        </Painel>
      </div>

      <Painel>
        <PainelHead icon={Stethoscope} titulo="Por programa" sub="valor aprovado" />
        <ListaRollup items={d.por_programa ?? []} formatar={formatCurrencyShort} />
      </Painel>
    </div>
  );
}
