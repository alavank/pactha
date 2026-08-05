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
  HardHat, AlertCircle, AlertTriangle, Ban, CheckCircle2,
} from "lucide-react";
import {
  AbaDocumentos, AbaEstaduais, AbaFns, AbaParlamentares, AbaSismob, AbaTransfereGov,
  Alertas, CaucItemDetalhe, Lancamento, Overview, isRollup,
} from "@/lib/bi";
import { CADASTRO_ESTADUAL, NOME_UF, tituloEstadual } from "@/lib/estadual";
import { formatCurrencyShort, formatInt, formatDate, diasLabel } from "@/lib/bi-format";
import {
  BI_CORES, Chip, DotMeter, Gauge, ListaRollup, Metric, Painel, PainelHead,
  RankBars, StackBar, Vazio,
} from "./kit";

const FONTE_LABEL: Record<string, string> = {
  emenda_estadual: "Emenda estadual",
  sigcon: "Convênio estadual",
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
  /* O MEDIDOR MEDE EXIGENCIAS, NAO UM SIM/NAO.
   *
   *  Antes: `s.regular ? 1 : 0`. Para um municipio unico — que e o caso de
   *  todo cliente deste produto — o arco so podia estar CHEIO ou VAZIO, nunca
   *  no meio. E vazio, num arco com ponta arredondada, vira uma bolinha solta
   *  que parece defeito de renderizacao. O medidor foi desenhado para
   *  proporcao (e o "850 Excellent" da referencia) e estava recebendo booleano.
   *
   *  Agora a proporcao e real: quantas exigencias estao comprovadas de quantas
   *  sao exigiveis. O gestor passa a ler "faltam 4 de 12", que e a pergunta
   *  que ele faz, em vez de "irregular", que ele ja sabia.
   *
   *  DESATIVADAS FICAM DE FORA do denominador, por decisao do dono: o CAUC nao
   *  consegue consultar aquelas exigencias para ENTE NENHUM — nao e falha do
   *  municipio e nao e meta que ele possa atingir. Continuam visiveis na lista
   *  do modulo, so nao contam. Se entrassem, nenhum municipio chegaria a 100%
   *  e o medidor mediria uma limitacao da ferramenta federal. */
  const caucItens = isRollup(s) ? [] : (s.itens ?? []);
  const caucExig = caucItens.filter((i) => i.tipo !== "na");
  const caucOk = caucExig.filter((i) => i.tipo === "regular").length;
  const caucPct = isRollup(s)
    ? (s.total_municipios ? s.regulares / s.total_municipios : 0)
    : caucExig.length ? caucOk / caucExig.length
    : s.regular ? 1 : 0;   // sem detalhe de itens, cai no que se sabe
  const caucTom = caucPct >= 0.99 ? "ok" : caucPct >= 0.5 ? "warn" : "crit";

  const vig = alertas?.vigencia ?? [];
  const prest = alertas?.prestacao ?? [];
  const docs = alertas?.documentos ?? [];
  const cg = ov.semaforo_cagec;
  const cagecCrit = !!cg?.tem_dados && (cg.irregulares || 0) > 0;
  /* CAGEC pela mesma regra. `obrigacoes_total` vem do CRC (o PDF); quando o
   *  Estado recusa emiti-lo nao ha denominador, e ai o medidor mostra a
   *  situacao em palavra em vez de inventar uma fracao. */
  const cgTotal = cg?.obrigacoes_total ?? 0;
  const cgOk = cg?.obrigacoes_ok ?? 0;
  const cgPct = cgTotal ? cgOk / cgTotal : (cg?.entidades ? (cg.regulares || 0) / cg.entidades : 0);
  /* FORA DA FONTE ≠ SEM COLETA. Município de estado que a fonte não cobre
     não está "aguardando coleta": a esfera estadual não é acompanhada, e
     tratá-la como pendência escrevia "Impedido de receber transferências"
     para cidade 100% regular no CAUC — veredito falso na tela do gestor. */
  const ufsForaDaFonte = cg?.ufs_sem_fonte ?? [];
  const estadualNaoSeAplica =
    !cg?.tem_dados && (cg?.municipios_na_fonte ?? 1) === 0 && ufsForaDaFonte.length > 0;
  const cgTom = !cg?.tem_dados ? (estadualNaoSeAplica ? "ok" : "warn")
    : cgPct >= 0.99 ? "ok" : cgPct >= 0.5 ? "warn" : "crit";


  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className={grid(tv, "grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5", "grid grid-cols-5 gap-3")}>
        <Metric icon={Wallet} tom="accent" label="Total captado" valor={formatCurrencyShort(total)} grande={tv}
          sub={ov.consolidado ? `${ov.municipios_count} municípios` : undefined} />
        <Metric icon={Landmark} label="Estadual" valor={formatCurrencyShort(k.valor_total_estadual)}
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

        {/* AS DUAS ESFERAS NO MESMO CARD, COM O MESMO PESO.
            Este medidor era só do CAUC e escrevia "Em dia · sem pendências"
            para um município IRREGULAR no CAGEC — é o sinal mais visível do
            painel, e dizer "em dia" com convênio estadual travado é o pior erro
            que ele pode cometer. Regular na União não é regular em Minas: são
            esferas independentes, e a estadual ainda trava o PAGAMENTO de
            convênio já assinado.

            O CAGEC entrava como uma tarja fina embaixo de um medidor gigante —
            duas coisas que travam igual, com pesos visuais opostos. Agora são
            dois medidores do mesmo tamanho, cada um com a sua fração real. */}
        <Painel>
          <PainelHead
            icon={caucPct >= 0.99 && !cagecCrit ? ShieldCheck : ShieldAlert}
            titulo="Regularidade"
            sub="aptidão para receber transferências"
          />
          <div className="flex min-h-0 flex-1 flex-col items-center gap-2">
            {/* A DIRECAO SEGUE O FORMATO DO CARTAO, e isso foi MEDIDO.
                No modulo e no celular o cartao e ALTO e estreito: empilhado,
                cada arco fica com 300x206 e 230x158. No Modo Tela e no link
                publico o cartao e BAIXO e largo (grade `h-screen`, linhas de
                altura limitada): ali empilhar espremia cada arco para 121x83 e
                99x68 — ilegivel numa parede de gabinete —, e com altura fixa em
                pixels o segundo era CORTADO ao meio. Lado a lado nos mesmos
                cartoes: 260x174 e 259x144, ou seja 2,1x e 2,6x maior.

                `items-stretch` na linha nao e detalhe: com `items-center` o
                filho nao estica, o `h-full` do SVG fica sem altura de
                referencia, ele cai no proprio teto e VAZA por cima da faixa.
                Foi o que a medicao pegou.

                `min-h-0` e o que permite encolher: sem ele o flex respeita o
                tamanho do conteudo e volta a transbordar. */}
            <div className={`flex min-h-0 w-full flex-1 justify-center gap-2 ${
              tv ? "flex-row items-stretch" : "flex-col items-center"
            }`}>
              <Gauge
                pct={caucPct}
                tom={caucTom}
                max={tv ? 260 : 300}
                centro={isRollup(s)
                  ? `${s.regulares}/${s.total_municipios}`
                  : caucExig.length ? `${caucOk}/${caucExig.length}` : (s.regular ? "Em dia" : "—")}
                legenda={isRollup(s) ? "municípios em dia" : "CAUC · União"}
              />
              <Gauge
                pct={cgPct}
                tom={cgTom}
                max={tv ? 260 : 300}
                centro={!cg?.tem_dados ? "—"
                  : cgTotal ? `${cgOk}/${cgTotal}`
                  : (cg.situacao || `${cg.regulares}/${cg.entidades}`)}
                legenda={!estadualNaoSeAplica ? "CAGEC · Minas"
                  : ufsForaDaFonte.length === 1
                    ? `${CADASTRO_ESTADUAL[ufsForaDaFonte[0]]?.sigla
                        || CADASTRO_ESTADUAL[ufsForaDaFonte[0]]?.curto
                        || "Cadastro estadual"} · ${ufsForaDaFonte[0]}`
                    : "Cadastro estadual"}
              />
            </div>

            {/* O RESUMO EM PALAVRA, que é o que o gestor lê primeiro. Vermelho
                só quando há impedimento — se o normal também for colorido, a
                cor deixa de avisar. */}
            <div
              className="w-full shrink-0 rounded-lg px-3 py-2"
              style={{
                background: `color-mix(in oklab, var(--bi-${
                  !cg?.tem_dados && caucPct >= 0.99
                    ? (estadualNaoSeAplica ? "ok" : "warn")
                  : caucPct < 0.99 || cagecCrit ? "crit" : "ok"
                }) 12%, transparent)`,
              }}
            >
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span
                  className="text-[11px] font-semibold"
                  style={{
                    color: `var(--bi-${
                      !cg?.tem_dados && caucPct >= 0.99
                        ? (estadualNaoSeAplica ? "ok-ink" : "warn-ink")
                      : caucPct < 0.99 || cagecCrit ? "crit-ink" : "ok-ink"
                    })`,
                  }}
                >
                  {isRollup(s)
                    ? (caucPct < 0.99 || cagecCrit
                        ? "Há município impedido de receber transferência"
                        : estadualNaoSeAplica
                          ? "Todos os municípios aptos na União"
                          : "Todos os municípios aptos")
                    : caucPct < 0.99 || cagecCrit
                      ? "Impedido de receber transferências"
                      : cg?.tem_dados
                        ? "Apto a receber transferências"
                        : estadualNaoSeAplica
                          ? "Apto a receber transferências da União"
                          : "União em dia · estadual sem coleta"}
                </span>
              </div>
              <div className="mt-0.5 text-[10px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                {!isRollup(s) && caucExig.length > 0 && caucExig.length - caucOk > 0 && (
                  <>União: {caucExig.length - caucOk} exigência(s) a comprovar. </>
                )}
                {!cg?.tem_dados
                  ? (estadualNaoSeAplica
                      ? `${ufsForaDaFonte.map((u) => NOME_UF[u] || u).join(", ")}: `
                        + "regularidade estadual ainda não acompanhada por este sistema."
                      : "Minas: regularidade estadual ainda não coletada.")
                  : cagecCrit
                    ? `Minas: ${cg.quem?.[0]?.nome ? `${cg.quem[0].nome.slice(0, 34)} — ` : ""}`
                      + "impede convênio estadual e liberação de parcela."
                    : cgTotal && cgTotal - cgOk > 0
                      ? `Minas: ${cgTotal - cgOk} obrigação(ões) pendente(s).`
                      : `Minas: ${cg.entidades} cadastro(s) em situação regular.`}
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

      {/* FAIXA COMPARATIVA — mandato de prefeito atual contra o anterior.
          Uma linha, o número e a variação: é o que se lê de longe. O detalhe
          por parlamentar fica na tela do sistema. */}
      {d.comparativo && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg px-3 py-2"
          style={{ background: "color-mix(in oklab, var(--bi-accent) 10%, transparent)" }}>
          <span className={tv ? "text-[13px]" : "text-[11px]"} style={{ color: "var(--bi-faint)" }}>
            {d.comparativo.rotulo_anterior}
          </span>
          <span className={`bi-num font-semibold ${tv ? "text-[15px]" : "text-[13px]"}`}>
            {formatCurrencyShort(d.comparativo.valor_anterior)}
          </span>
          <span style={{ color: "var(--bi-faint)" }}>→</span>
          <span className={tv ? "text-[13px]" : "text-[11px]"} style={{ color: "var(--bi-faint)" }}>
            {d.comparativo.rotulo_atual}
          </span>
          <span className={`bi-num font-bold ${tv ? "text-[15px]" : "text-[13px]"}`}>
            {formatCurrencyShort(d.comparativo.valor_atual)}
          </span>
          {(() => {
            const c = d.comparativo!;
            const sobe = c.delta > 0;
            const zero = Math.abs(c.delta) < 0.005;
            const cor = zero ? "var(--bi-faint)" : sobe ? "var(--bi-ok)" : "var(--bi-crit)";
            return (
              <span className={`font-bold ${tv ? "text-[14px]" : "text-[12px]"}`} style={{ color: cor }}>
                {zero ? "— sem variação"
                  : c.delta_pct == null ? (sobe ? "▲ novo" : "▼ sem verba")
                  : `${sobe ? "▲ +" : "▼ −"}${Math.abs(c.delta_pct).toFixed(0)}%`}
              </span>
            );
          })()}
          {/* O mandato em curso tem menos anos que o encerrado. Sem dizer isso,
              a queda aparente e so aritmetica de calendario. */}
          {d.comparativo.anos_atual !== d.comparativo.anos_anterior && (
            <span className={tv ? "text-[11px]" : "text-[10px]"} style={{ color: "var(--bi-warn)" }}>
              {d.comparativo.anos_atual} ano(s) corridos contra {d.comparativo.anos_anterior}
            </span>
          )}
        </div>
      )}

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
        <Metric icon={Landmark} tom="accent" label="Convênios Estaduais" valor={formatInt(c.total)} grande={tv} />
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

/** Uma exigência por linha, no MESMO desenho do extrato oficial:
 *  código · Item Legal · **Situação** · **Validade**.
 *
 *  GRADE de largura fixa, não flex. Com flex, o rótulo que quebrava em duas
 *  linhas empurrava as colunas da direita, e no CAGEC o código (que varia de
 *  "CNPJ" a "AUTORIZ-ELETRONICA") deslocava o início de cada rótulo — a lista
 *  saía desalinhada e difícil de varrer com o olho. Na grade o texto quebra
 *  DENTRO da célula e as vizinhas não se mexem.
 *
 *  O CAGEC não tem coluna de código: aqueles identificadores são NOSSOS (o CRC
 *  não os imprime) e os únicos informativos — os oito "Item 3.1.2 -…" — já vêm
 *  escritos no próprio rótulo. Mostrá-los era duplicar e desalinhar. */
/** Obrigacao "Vigente" cujo prazo ja passou. Ver o uso em ListaExigencias. */
function venceuEm(validade?: string | null): boolean {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((validade || "").trim());
  if (!m) return false;
  const h = new Date();
  return new Date(+m[3], +m[2] - 1, +m[1]) < new Date(h.getFullYear(), h.getMonth(), h.getDate());
}

function ListaExigencias({
  itens, tv, esfera = "cauc",
}: { itens: CaucItemDetalhe[]; tv?: boolean; esfera?: "cauc" | "cagec" }) {
  const cols = esfera === "cauc"
    ? (tv ? "grid-cols-[3rem_minmax(0,1fr)_7.5rem_5.5rem]" : "grid-cols-[2.6rem_minmax(0,1fr)_6.5rem_5rem]")
    : (tv ? "grid-cols-[minmax(0,1fr)_7.5rem_5.5rem]" : "grid-cols-[minmax(0,1fr)_6.5rem_5rem]");
  return (
    <div className="flex flex-col">
      {/* Cabeçalho de coluna: o extrato tem, e sem ele "31/07/2026" solto na
          direita não diz se é validade ou data de consulta. */}
      {/* `px-2` no cabecalho E nas linhas: e o respiro que faz a faixa colorida
          da linha em alerta virar um CARTAO, em vez de uma tarja que vai de
          margem a margem e termina em corte seco. Sem ele o realce encosta na
          borda do painel e parece vazamento. */}
      {/* `border-x border-transparent` só para o cabeçalho alinhar com a
          borda de 1px que cada linha ganhou. */}
      <div className={`grid ${cols} items-end gap-x-2 border-x border-b border-x-transparent px-2 pb-1 text-[9px] uppercase tracking-wide`}
        style={{ borderBottomColor: "var(--bi-line-strong)", color: "var(--bi-faint)" }}>
        {esfera === "cauc" && <span>Item</span>}
        <span>Item legal</span>
        <span>Situação</span>
        <span className="text-right">Validade</span>
      </div>
      {/* VÃO PEQUENO em vez de divisória compartilhada.
          Com `divide-y` a linha fica ENTRE as células e o fundo colorido da
          linha em alerta passa por cima dela: quatro "A Comprovar" seguidos
          viravam UM BLOCO vermelho só, e o arredondamento que eu tinha
          acabado de pôr era invisível porque não havia espaço para ele
          aparecer. Dois pixels bastam — a lista continua densa (são 28
          exigências) e cada linha volta a ter contorno próprio. */}
      {/* `mt-1` porque `gap` só vale ENTRE irmãos: sem ele a primeira linha
          encostava na régua do cabeçalho enquanto todas as outras tinham
          respiro. 4px e não 2px de propósito — a quebra cabeçalho/lista é
          maior que a de item para item. */}
      <div className="mt-1 flex flex-col gap-0.5">
        {itens.map((i) => {
          const pendente = i.tipo === "pendente";
          const na = i.tipo === "na";
          // "Vigente" com prazo no passado: so aparece em lista PRESERVADA (o
          // CRC e de semanas atras e o portal nao emite outro). Verde aqui e o
          // pior erro possivel numa TV de gabinete — o gestor confia numa
          // certidao vencida. So no CAGEC: no CAUC a validade e reemitida todo
          // dia e a de ontem e rotina, nao pendencia.
          const vencido = esfera === "cagec" && i.tipo === "regular" && venceuEm(i.validade);
          const cor = pendente ? "var(--bi-crit)"
            : vencido ? "var(--bi-warn)"
            : na ? "var(--bi-faint)" : "var(--bi-ok)";
          return (
            <div
              key={i.codigo}
              className={`grid ${cols} items-start gap-x-2 rounded-lg border px-2 py-[5px]`}
              /* A MESMA bordinha do item de lista do sistema (`bi-card-flat`).
                 A linha em alerta leva a borda no tom dela, senão o vermelho
                 encostaria no vermelho de novo. */
              style={pendente
                ? { background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
                    borderColor: "color-mix(in oklab, var(--bi-crit) 26%, transparent)" }
                : vencido
                ? { background: "color-mix(in oklab, var(--bi-warn) 12%, transparent)",
                    borderColor: "color-mix(in oklab, var(--bi-warn) 26%, transparent)" }
                : { borderColor: "var(--bi-line)" }}
            >
              {esfera === "cauc" && (
                <span className="bi-num text-[10px] leading-[1.45]" style={{ color: "var(--bi-faint)" }}>
                  {i.codigo}
                </span>
              )}
              {/* O texto QUEBRA em vez de ser cortado. Truncar deixava linhas
                  como "Certidão de Débitos Relativos a Créditos …", que não
                  dizem QUAL certidão é — o dado necessário para agir. */}
              <span
                className={`min-w-0 leading-[1.45] ${tv ? "text-[13px]" : "text-[12px]"} ${pendente ? "font-semibold" : ""}`}
                style={na ? { color: "var(--bi-faint)" } : pendente ? { color: "var(--bi-crit)" } : undefined}
              >
                {i.label}
              </span>

              {/* SITUAÇÃO — a palavra do documento, com o símbolo da esfera.
                  Alinhada à esquerda da célula de propósito: os ícones formam
                  uma coluna vertical, e é ela que o olho percorre na TV. */}
              <span
                className={`flex items-center gap-1 leading-[1.45] ${tv ? "text-[11px]" : "text-[10px]"} ${pendente ? "font-bold" : ""}`}
                style={{ color: cor }}
                title={i.nota || undefined}
              >
                {pendente
                  ? (esfera === "cagec"
                      ? <AlertTriangle className="size-3 shrink-0" />
                      : <AlertCircle className="size-3 shrink-0" />)
                  : vencido
                    ? <CalendarClock className="size-3 shrink-0" />
                    : na
                      ? <Ban className="size-3 shrink-0" />
                      : <CheckCircle2 className="size-3 shrink-0" />}
                {/* O documento dizia "Vigente" quando foi lido; hoje o prazo
                    passou. Repetir a palavra do extrato seria transcrever com
                    fidelidade uma informacao que deixou de ser verdadeira. */}
                <span className="truncate">
                  {vencido ? "Prazo vencido" : (i.status || (pendente ? "Pendente" : "—"))}
                </span>
              </span>

              {/* VALIDADE — coluna própria e SEMPRE presente, como no extrato.
                  "—" quando a fonte não dá data (todo "A Comprovar" e todo
                  "Desativado"): ausência de data é informação, não buraco. */}
              <span
                className={`bi-num text-right leading-[1.45] ${tv ? "text-[11px]" : "text-[10px]"}`}
                style={{ color: pendente ? "var(--bi-crit)"
                  : vencido ? "var(--bi-warn)" : "var(--bi-faint)" }}
              >
                {i.validade || (/^\d{2}\/\d{2}\/\d{2,4}$/.test(i.valor || "") ? i.valor : "—")}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function AbaDocumentosView({
  d, tv, esfera,
}: AbaProps & { d: AbaDocumentos; esfera?: "cauc" | "cagec" }) {
  const c = d.cauc;
  const pct = c.com_dados ? c.regulares / c.com_dados : 0;

  /* ⚠️ CARTEIRA NÃO TEM "PRIMEIRO". Este bloco lia `por_municipio[0]` para o
     detalhe item-a-item do CAUC e para o CAGEC inteiro. Num município único
     está certo — há um só. No CONSOLIDADO de uma assessoria, `[0]` é uma cidade
     ARBITRÁRIA, e pior: `bi_abas.py` ordena colocando os irregulares primeiro,
     então a tela mostrava as certidões da PIOR cidade da carteira, sem dizer
     qual, sob o título da carteira. O gestor lia aquilo como o retrato de todos
     os clientes dele.

     Com N municípios a tela passa a mostrar o que ela de fato sabe: a lista por
     município. O detalhe de exigência continua existindo — no escopo de um
     município, que é onde ele significa alguma coisa. */
  const carteira = (c.total_municipios ?? 1) > 1;
  const primeiro = carteira ? undefined : c.por_municipio[0];

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
  // Mesma regra do CAUC acima: no consolidado não existe "o" CAGEC.
  const cagec = carteira ? undefined : d.cagec.por_municipio[0];
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
  // DOIS estados diferentes, e a tela precisa distinguir os dois:
  //  crcAusente — a lista NÃO é o certificado, são as 2 linhas da consulta
  //               pública. Nada abaixo pode ser contado nem chamado de "em dia".
  //  crcVelho   — a lista é um certificado de verdade, só que antigo, porque o
  //               portal parou de emitir. Vale mostrar, com a data na cara.
  // Gatear pelo erro apenas (como estava) deixaria a tela MUDA nas linhas
  // gravadas antes da coluna existir, que é o estado de Monte Sião agora.
  /* ⚠️ O QUE É DE MINAS É A FONTE, NÃO O CONCEITO. Cadastro estadual de
     convenentes existe em outros estados; o que este sistema sabe consultar é o
     portal do CAGEC-MG. A tela carimbava "CAGEC — Minas Gerais" sobre cidades de
     Goiás e Tocantins, e dizer "não se aplica" seria trocar um erro por outro:
     afirmaria que a cidade não tem cadastro estadual, o que não sabemos.
     O que sabemos — e o que a tela diz — é até onde a NOSSA coleta vai.
     `ufs_sem_fonte` vem do servidor, que conhece a UF de cada município. */
  const ufsSemFonte = d.cagec.ufs_sem_fonte ?? [];
  const semFonteNoEscopo = (d.cagec.municipios_no_escopo ?? 0) === 0
    && (d.cagec.fora_de_mg ?? 0) > 0;
  const cagecParcial = (d.cagec.fora_de_mg ?? 0) > 0
    && (d.cagec.municipios_no_escopo ?? 0) > 0;

  const crcAusente = !!cagec && cagec.detalhe_do_crc === false;
  const crcVelho = !!cagec && cagec.detalhe_do_crc !== false && !!cagec.crc_erro;

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
        <Metric icon={ShieldAlert}
          tom={semFonteNoEscopo ? "neutro" : cagec ? (cagecIrregular ? "crit" : "ok") : "warn"}
          /* ⚠️ "CAGEC" É NOME DE MINAS, não do produto. Pesquisado: é o
             Cadastro Geral de Convenentes do Estado de MG (Decreto
             44.293/2006); Goiás tem o SIGECON, o Espírito Santo o Portal de
             Convênios da SEGER. Fora de Minas o rótulo é o genérico, com a UF
             do próprio ambiente — e nada de "Minas Gerais" na tela de um
             cliente do ES, que não tem por que ler sobre outro estado. */
          /* Uma UF de fora: nomeia o sistema dela ("SIGECON — Goiás").
             Várias: só as siglas, que é o que cabe num cartão. */
          label={semFonteNoEscopo
            ? (ufsSemFonte.length === 1
                ? tituloEstadual(ufsSemFonte[0])
                : `Cadastro estadual — ${ufsSemFonte.join(", ")}`)
            : "CAGEC — Minas Gerais"}
          valor={semFonteNoEscopo ? "Não acompanhado"
            : !cagec ? "Sem coleta"
            : cagecIrregular ? (cagec.situacao || "Irregular") : "Em dia"}
          sub={semFonteNoEscopo ? "ainda não acompanhado aqui"
            : cagecParcial ? `só os ${d.cagec.municipios_no_escopo} de MG`
            : "convênios estaduais"}
          grande={tv} />
        {/* Com o CRC indisponivel nao existe denominador: as pendencias do
            CAGEC sao desconhecidas, e somar as 2 linhas do fallback anunciaria
            "de 27 exigencias" quando o cadastro estadual tem ~28 sozinho. */}
        {/* Na carteira o que existe é a SOMA das pendências dos municípios;
            "de N exigências" não tem sentido, porque cada município tem o seu
            conjunto. Num município só, segue o detalhe de sempre. */}
        <Metric icon={FileCheck2} tom={carteira
            ? (c.pendencias_total ? "crit" : "ok")
            : ((primeiro?.itens_pendentes.length || 0) + pendCagec ? "crit" : "ok")}
          label={carteira ? "Pendências na carteira"
            : crcAusente ? "Pendências no CAUC" : "Pendências (as duas)"}
          valor={formatInt(carteira
            ? c.pendencias_total
            : (primeiro?.itens_pendentes.length || 0) + (crcAusente ? 0 : pendCagec))}
          sub={carteira
            ? `${formatInt(c.com_dados - c.regulares)} município(s) com pendência`
            : crcAusente
              ? `de ${primeiro?.total_itens ?? 0} · CAGEC não conferido`
              : `de ${(primeiro?.total_itens ?? 0) + (cagec?.itens?.length ?? 0)} exigências`}
          grande={tv} />
        <Metric icon={CalendarClock}
          label={carteira ? "Municípios conferidos" : "Última consulta"}
          valor={carteira
            ? `${formatInt(c.com_dados)} de ${formatInt(c.total_municipios)}`
            : primeiro?.data_pesquisa ? formatDate(primeiro.data_pesquisa) : "—"}
          /* ⚠️ O corte do detalhe DECLARADO. `bi_abas.py` só examina os
             primeiros municípios da carteira; sem esta linha, "18 de 41" seria
             lido como "23 estão irregulares" quando 21 nunca foram olhados. */
          sub={carteira && c.detalhe_limitado
            ? `conferência limitada aos ${formatInt(c.examinados ?? 0)} primeiros`
            : undefined}
          grande={tv} />
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
              contagem={carteira
                ? `${formatInt(c.regulares)} em dia de ${formatInt(c.com_dados)} conferidos`
                : blocos.length
                ? `${blocos.reduce((n, [, it]) => n + it.length, 0)} exigências · ${
                    (primeiro?.itens ?? []).filter((x) => x.tipo === "na").length
                  } desativadas na origem`
                : undefined}
            />
            {carteira ? (
              /* ⭐ A CARTEIRA, UMA LINHA POR MUNICÍPIO. Aqui estava o detalhe
                 item-a-item de UMA cidade, sem rótulo — e como a ordenação do
                 servidor põe os irregulares primeiro, era a PIOR cidade posando
                 de retrato da carteira. */
              <Painel>
                {c.por_municipio.length ? (
                  <ul className="flex flex-col gap-1">
                    {c.por_municipio.map((m) => (
                      <li
                        key={m.municipio_id}
                        className="flex items-baseline gap-2 rounded-lg px-2 py-1.5"
                        style={{ background: "var(--bi-surface-2)" }}
                      >
                        <span className="truncate text-[12px]">
                          {m.nome || `Município ${m.municipio_id}`}
                        </span>
                        <span className="ml-auto shrink-0 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                          {m.data_pesquisa ? formatDate(m.data_pesquisa) : "sem data"}
                        </span>
                        <Chip tom={m.regular ? "ok" : "crit"}>
                          {m.regular ? "Em dia" : `${formatInt(m.pendencias)} pend.`}
                        </Chip>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <Vazio>Sem dados de CAUC coletados na carteira.</Vazio>
                )}
              </Painel>
            ) : blocos.length ? (
              <div className={soUmaEsfera && tv ? "bi-colunas-2" : ""}>
                {blocos.map(([grupo, itens]) => (
                  <Painel key={grupo} className="mb-3 break-inside-avoid">
                    {/* Titulo = o LITERAL do extrato ("III - Obrigacoes de
                        Transparencia"), para casar na conferencia. A glosa vem
                        no subtitulo, para quem nao vive o documento. */}
                    <PainelHead icon={ShieldCheck} titulo={grupo}
                      sub={`${itens.length} exigência(s)${
                        itens[0]?.grupo_glossa ? ` · ${itens[0].grupo_glossa}` : ""}`} />
                    <ListaExigencias itens={itens} tv={tv} esfera="cauc" />
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
              titulo={semFonteNoEscopo
                ? (ufsSemFonte.length === 1
                    ? tituloEstadual(ufsSemFonte[0])
                    : `Cadastro estadual — ${ufsSemFonte.join(", ")}`)
                : "CAGEC — Minas Gerais"}
              sub={semFonteNoEscopo
                ? "regularidade estadual · ainda não acompanhada por este sistema"
                : cagecParcial
                ? `Cadastro Geral de Convenentes · cobre ${d.cagec.municipios_no_escopo} de ${(d.cagec.municipios_no_escopo ?? 0) + (d.cagec.fora_de_mg ?? 0)} municípios (os de MG)`
                : "Cadastro Geral de Convenentes · exigências estaduais"}
              /* "27 exigencias" nao existe em documento nenhum: o CRC tem 24
                 documentos, e as outras 3 linhas (CADIN-MG, SIAFI-MG, mandato)
                 vem do CABECALHO do certificado. Separar por procedencia. */
              contagem={semFonteNoEscopo
                ? "fonte não disponível"
                : crcAusente
                /* Sem o CRC, "2 linhas · 2 documentos do CRC" e uma contagem
                   FALSA numa parede de gabinete: o cadastro tem ~28 obrigacoes
                   e nos lemos duas. Contagem que nao sabe nao conta. */
                ? "detalhamento indisponível"
                : crcVelho
                ? `documentos de ${formatDate(cagec.crc_em)}`
                : cagec?.itens?.length
                ? `${cagec.itens.length} linhas · ${
                    cagec.itens.filter((x) => !["CADIN-MG", "SIAFI-MG", "MANDATO"].includes(x.codigo || "")).length
                  } documentos do CRC`
                : "aguardando coleta"}
            />
            {/* Falha do PORTAL do Estado — nao nossa e nao do municipio. Mas
                quem le a tela precisa saber que a lista abaixo esta incompleta,
                senao um CAGEC de duas linhas passa por cadastro em dia. */}
            {(crcAusente || crcVelho) && (
              <div
                className="mb-3 flex items-start gap-2 rounded-lg px-3 py-2"
                style={{ background: "color-mix(in oklab, var(--bi-warn) 15%, transparent)" }}
              >
                <Info className="mt-[1px] size-4 shrink-0" style={{ color: "var(--bi-warn)" }} />
                <p className="text-[11px] leading-snug" style={{ color: "var(--bi-warn)" }}>
                  {crcAusente ? (
                    <>
                      <strong>Documentos não conferidos.</strong> O certificado (CRC),
                      de onde saem os documentos e suas validades, não pôde ser lido.
                      Abaixo, apenas o que a consulta pública mostra — não é a lista
                      de exigências.
                    </>
                  ) : (
                    <>
                      <strong>Leitura de {formatDate(cagec.crc_em)}.</strong> O portal do
                      CAGEC não emitiu certificado novo, então a lista abaixo pode estar
                      desatualizada.
                    </>
                  )}
                  {" "}A situação do cadastro continua atualizada.
                </p>
              </div>
            )}
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
                    <ListaExigencias itens={itens} tv={tv} esfera="cagec" />
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
