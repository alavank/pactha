"use client";

/* TCE-PR — o que o município declarou ao Tribunal de Contas do Paraná.
 *
 * Dado COLETADO (não curadoria): `backend/ingestion/tce_pr.py` lê o arquivo aberto
 * do PIT (pit.tce.pr.gov.br), que traz tudo o que a prefeitura, a câmara e as
 * autarquias mandam ao SIM-AM.
 *
 * ⭐ A TELA ABRE PELA DESPESA POR FONTE, e não pela lista de convênios, porque é o
 * número que nenhuma outra tela do PACTHA tem: a prefeitura cria uma fonte de
 * recurso por convênio ("SECID Convênio 1748/2025 Pavimentação"), e a soma dos
 * empenhos dela diz quanto daquele dinheiro já foi empenhado, liquidado e pago.
 *
 * ⚠️ O DADO TEM ATRASO, e a tela diz de quanto: o município entrega ao SIM-AM mês
 * a mês e o Tribunal publica depois (Juranda, em 22/09/2026: entregue até junho).
 * É o prazo da norma, não falha de coleta.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Banknote, FileSignature, Gavel, HardHat, Loader2, ScrollText } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Abas, Aviso, Bloco, BlocoHead, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

type Categoria = "convenio" | "legal" | "propria";

interface Fonte {
  ano: number; entidade: number | null; codigo: string; fonte: string;
  plano?: string | null; empenhos: number; empenhado?: number | null;
  liquidado?: number | null; pago?: number | null; categoria: Categoria;
}
interface Convenio {
  id: number; ano: number; entidade: number | null; numero?: string | null;
  celebracao?: string | null; situacao?: string | null; esfera?: string | null;
  valor?: number | null; contrapartida?: number | null;
  vigencia_inicio?: string | null; vigencia_fim?: string | null;
  objeto?: string | null; fonte?: string | null;
}
interface Obra {
  id: number; ano: number; entidade: number | null; nome?: string | null;
  valor?: number | null; inicio?: string | null; prazo_dias?: number | null;
  situacao?: string | null; regime?: string | null; ultima_medicao?: string | null;
  locais?: Array<{ bem?: string | null; logradouro?: string | null }>;
}
interface Contrato {
  id: number; numero: string; entidade: number | null; objeto?: string | null;
  contratado?: string | null; valor?: number | null; valor_atual?: number | null;
  vigencia_ate?: string | null; aditivos: number;
}
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  coletado?: boolean;
  atualizado_em?: string | null;
  referencia?: string | null;
  ultimo_envio?: string | null;
  anos_coletados?: number[];
  entidades?: Array<{ id: number; nome?: string | null }>;
  despesa?: Fonte[];
  convenios?: Convenio[];
  obras?: { total: number; valor_total?: number | null; obras: Obra[] };
  licitacoes_por_ano?: Array<{ ano: number; entidade: number | null; total: number;
    valor_estimado?: number | null }>;
  contratos_vigentes?: Contrato[];
}

const money = (v?: number | null) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL",
                                                maximumFractionDigits: 0 });
const dia = (iso?: string | null) =>
  iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("pt-BR") : "—";

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
  "agosto", "setembro", "outubro", "novembro", "dezembro"];
/* "2026/06" -> "junho/2026". O SIM-AM usa o mês 13 para o encerramento do
   exercício: "2025/13" é o ano de 2025 fechado. */
const mesAno = (s?: string | null) => {
  const m = /^(\d{4})\/(\d{1,2})/.exec((s || "").trim());
  if (!m) return null;
  const n = Number(m[2]);
  if (n === 13) return `${m[1]} (exercício encerrado)`;
  return n >= 1 && n <= 12 ? `${MESES[n - 1]}/${m[1]}` : m[1];
};

/* "MUNICÍPIO DE JURANDA" / "CÂMARA MUNICIPAL DE JURANDA": o chip leva só o que
   distingue — a primeira palavra. */
const curto = (nome?: string | null) => {
  const n = (nome || "").trim();
  if (/^MUNIC[IÍ]PIO/i.test(n)) return "Prefeitura";
  if (/^C[AÂ]MARA/i.test(n)) return "Câmara";
  return n.split(" - ")[0].slice(0, 28);
};

const pct = (parte?: number | null, todo?: number | null) =>
  parte != null && todo ? Math.max(0, Math.min(100, (parte / todo) * 100)) : null;

function BarraExecucao({ empenhado, liquidado, pago }: {
  empenhado?: number | null; liquidado?: number | null; pago?: number | null;
}) {
  const pl = pct(liquidado, empenhado);
  const pp = pct(pago, empenhado);
  if (pl == null) return null;
  return (
    <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full"
         style={{ background: "var(--bi-surface-2)" }}
         title={`liquidado ${pl.toFixed(0)}% · pago ${(pp ?? 0).toFixed(0)}% do empenhado`}>
      <div className="relative h-full" style={{ width: `${pl}%`,
        background: "color-mix(in oklab, var(--bi-accent) 45%, transparent)" }}>
        <div className="absolute inset-y-0 left-0"
             style={{ width: `${pl ? ((pp ?? 0) / pl) * 100 : 0}%`,
                      background: "var(--bi-accent)" }} />
      </div>
    </div>
  );
}

export default function TcePrPage() {
  const { municipioId } = useMunicipio();
  // A resposta guarda de QUAL município ela é: "carregando" é derivado (resposta
  // de outro município = ainda não chegou), sem setState síncrono no efeito.
  const [resp, setResp] = useState<{ mid: string; d: Resp | null } | null>(null);
  const [entidade, setEntidade] = useState<number | null>(null);
  const [ano, setAno] = useState<string>("");
  const [verOutras, setVerOutras] = useState<Categoria | null>(null);

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    const mid = String(municipioId);
    api.get("/pr/tce", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setResp({ mid, d: r.data }); })
      .catch(() => { if (vivo) setResp({ mid, d: null }); });
    return () => { vivo = false; };
  }, [municipioId]);
  const d = resp?.mid === String(municipioId) ? resp.d : null;
  const loading = !!municipioId && resp?.mid !== String(municipioId);

  const entidades = d?.entidades || [];
  // O filtro só existe com mais de uma entidade, e só vale se a entidade estiver
  // nos dados na tela (trocar de município não pode deixar um filtro órfão).
  const temFiltro = entidades.length > 1;
  const filtro = temFiltro && entidades.some((e) => e.id === entidade) ? entidade : null;
  const daEntidade = useCallback(
    <T extends { entidade: number | null }>(xs: T[] | undefined) =>
      (xs || []).filter((x) => filtro == null || x.entidade === filtro),
    [filtro],
  );

  const anosDespesa = useMemo(
    () => [...new Set((d?.despesa || []).map((f) => f.ano))].sort((a, b) => b - a),
    [d?.despesa],
  );
  const anoAtivo = anosDespesa.includes(Number(ano)) ? Number(ano) : anosDespesa[0];
  const fontesDoAno = useMemo(
    () => daEntidade(d?.despesa).filter((f) => f.ano === anoAtivo),
    [d?.despesa, daEntidade, anoAtivo],
  );
  const porCategoria = (c: Categoria) => fontesDoAno.filter((f) => f.categoria === c);
  const somaDe = (fs: Fonte[], k: "empenhado" | "liquidado" | "pago") =>
    fs.reduce((s, f) => s + (f[k] ?? 0), 0);
  const conv = porCategoria("convenio");

  const convenios = daEntidade(d?.convenios);
  const obras = daEntidade(d?.obras?.obras);
  const vigentes = daEntidade(d?.contratos_vigentes);
  const licPorAno = useMemo(() => {
    const m = new Map<number, { ano: number; total: number; valor: number | null }>();
    for (const l of daEntidade(d?.licitacoes_por_ano)) {
      const a = m.get(l.ano) || { ano: l.ano, total: 0, valor: null };
      a.total += l.total;
      if (l.valor_estimado != null) a.valor = (a.valor ?? 0) + l.valor_estimado;
      m.set(l.ano, a);
    }
    return [...m.values()].sort((a, b) => b.ano - a.ano);
  }, [d?.licitacoes_por_ano, daEntidade]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;
  if (!d.coletado) {
    /* ⚠️ Ainda não coletado NÃO é "o município não tem nada no TCE". */
    return (
      <div className="space-y-4">
        <TituloTela>TCE-PR</TituloTela>
        <Vazio>
          Os dados do SIM-AM deste município ainda não foram coletados. A primeira
          coleta roda na janela noturna; até lá, não conclua que não há convênios
          nem contratos.
        </Vazio>
      </div>
    );
  }

  const envio = mesAno(d.ultimo_envio);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <TituloTela>TCE-PR</TituloTela>
          <p className="text-sm text-muted-foreground">
            O que o município declarou ao Tribunal de Contas do Paraná (SIM-AM):
            convênios, obras, contratos e quanto de cada convênio já foi gasto.
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {envio && <Selo>{`dados até ${envio}`}</Selo>}
          {d.atualizado_em && <Selo>{`coletado em ${dia(d.atualizado_em)}`}</Selo>}
        </div>
      </div>

      {temFiltro && (
        <div className="flex flex-wrap items-center gap-1.5">
          {[{ id: null as number | null, nome: "Todas as entidades" }, ...entidades].map((e) => {
            const ativo = e.id === filtro;
            return (
              <button key={e.id ?? "todas"} type="button" onClick={() => setEntidade(e.id)}
                      className="rounded-full border px-2.5 py-1 text-[11px] transition-colors"
                      style={{
                        borderColor: ativo ? "var(--bi-accent-ink)" : "var(--bi-line)",
                        color: ativo ? "var(--bi-accent-ink)" : "var(--bi-muted)",
                        fontWeight: ativo ? 600 : 400,
                      }}
                      title={e.nome || undefined}>
                {e.id == null ? e.nome : curto(e.nome)}
              </button>
            );
          })}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Numero icon={Banknote} tom="acento"
                rotulo={`Convênios e emendas — empenhado em ${anoAtivo ?? "—"}`}
                valor={money(somaDe(conv, "empenhado"))}
                sub={`${money(somaDe(conv, "pago"))} pago · ${conv.length} fonte(s)`} />
        <Numero icon={ScrollText} rotulo="Convênios registrados no TCE"
                valor={convenios.length}
                sub={`${d.anos_coletados?.length ?? 0} exercício(s) lidos`} />
        <Numero icon={HardHat} rotulo="Obras declaradas"
                valor={d.obras?.total ?? 0} sub={money(d.obras?.valor_total)} />
        <Numero icon={FileSignature} rotulo="Contratos vigentes" valor={vigentes.length}
                sub="com os aditivos de prazo" />
      </div>

      {/* ------------- Despesa por fonte: o dinheiro do convênio saindo -------------
          ⭐ É o bloco que só esta fonte tem. Cada fonte de recurso que a
          prefeitura cria para um convênio vira uma linha com empenhado,
          liquidado e pago. */}
      <Bloco className="p-3">
        <BlocoHead
          icon={Banknote}
          titulo="Convênios e emendas: quanto já foi gasto"
          sub="soma das notas de empenho por fonte de recurso, como o município informou ao SIM-AM"
          right={anosDespesa.length > 1 ? (
            <Abas valor={String(anoAtivo)} onChange={setAno}
                  opcoes={anosDespesa.map((a) => ({ valor: String(a), label: String(a) }))} />
          ) : undefined}
        />
        {conv.length ? (
          <Lista>
            {conv.map((f) => (
              <li key={`${f.entidade}-${f.codigo}-${f.fonte}`} className="py-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                    <span className="tabular-nums" style={{ color: "var(--bi-faint)" }}>
                      {f.codigo}{" "}
                    </span>
                    {f.fonte}
                  </span>
                  <span className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                    {money(f.pago)} pago · {money(f.liquidado)} liquidado ·{" "}
                    <b style={{ color: "var(--bi-text)" }}>{money(f.empenhado)}</b> empenhado
                  </span>
                </div>
                <BarraExecucao empenhado={f.empenhado} liquidado={f.liquidado} pago={f.pago} />
                {f.plano && (
                  <div className="mt-0.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {f.plano} · {f.empenhos} empenho(s)
                  </div>
                )}
              </li>
            ))}
          </Lista>
        ) : (
          <p className="px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Nenhuma fonte de convênio ou emenda com empenho em {anoAtivo}.
          </p>
        )}

        {/* As outras duas categorias ficam fechadas: são dinheiro do município
            ou repasse automático, sem instrumento a acompanhar — mas a conta
            inteira precisa poder ser vista, senão o total não fecha. */}
        <div className="mt-3 flex flex-wrap gap-2">
          {(["legal", "propria"] as const).map((c) => {
            const fs = porCategoria(c);
            if (!fs.length) return null;
            const rotulo = c === "legal" ? "Fundo a fundo e transferências legais"
                                         : "Recursos próprios e vinculados";
            return (
              <button key={c} type="button"
                      onClick={() => setVerOutras(verOutras === c ? null : c)}
                      className="rounded-full border px-2.5 py-1 text-[11px]"
                      style={{ borderColor: "var(--bi-line)",
                               color: verOutras === c ? "var(--bi-accent-ink)" : "var(--bi-muted)" }}>
                {verOutras === c ? "ocultar" : "ver"} {rotulo.toLowerCase()} ·{" "}
                {money(somaDe(fs, "empenhado"))}
              </button>
            );
          })}
        </div>
        {verOutras && (
          <Lista>
            {porCategoria(verOutras).map((f) => (
              <li key={`${f.entidade}-${f.codigo}-${f.fonte}`}
                  className="flex flex-wrap items-baseline justify-between gap-x-3 py-1">
                <span className="text-[11px]" style={{ color: "var(--bi-text)" }}>{f.fonte}</span>
                <span className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                  {money(f.pago)} pago de {money(f.empenhado)}
                </span>
              </li>
            ))}
          </Lista>
        )}
      </Bloco>

      {/* ------------------- Convênios registrados no TCE-PR ------------------- */}
      <Bloco className="p-3">
        <BlocoHead icon={ScrollText} titulo="Convênios registrados no TCE-PR"
                   sub="os que a própria entidade cadastrou no SIM-AM, de todos os exercícios" />
        {convenios.length ? (
          <Lista>
            {convenios.map((c) => (
              <li key={c.id} className="py-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                    Convênio {c.numero || c.id}
                    {c.esfera && <span className="ml-2"><Selo>{c.esfera}</Selo></span>}
                    {c.situacao && (
                      <span className="ml-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                        {c.situacao}
                      </span>
                    )}
                  </span>
                  <span className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                    {money(c.valor)}
                    {c.contrapartida ? ` + ${money(c.contrapartida)} contrapartida` : ""}
                  </span>
                </div>
                {c.objeto && (
                  <div className="text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                    {c.objeto.slice(0, 180)}
                  </div>
                )}
                <div className="mt-0.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  celebrado em {dia(c.celebracao)} · vigência até {dia(c.vigencia_fim)}
                  {c.fonte ? ` · ${c.fonte}` : ""}
                </div>
              </li>
            ))}
          </Lista>
        ) : (
          <p className="px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Nenhum convênio cadastrado pela entidade no SIM-AM.
          </p>
        )}
        {/* ⚠️ A situação é a do arquivo daquele ano, e os arquivos antigos são
            congelados pelo Tribunal. Sem este aviso, "Em Andamento" num convênio
            de 2017 seria lido como pendência de hoje. */}
        <Aviso tom="atencao" titulo="A situação é a do exercício em que o convênio foi registrado">
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O TCE-PR não reabre os arquivos de exercícios antigos. Um convênio de anos
            anteriores pode aparecer &quot;Em Andamento&quot; mesmo já encerrado — a
            execução de verdade está na despesa por fonte, acima.
          </p>
        </Aviso>
      </Bloco>

      {/* ------------------------------ Obras ------------------------------ */}
      {!!obras.length && (
        <Bloco className="p-3">
          <BlocoHead icon={HardHat} titulo="Obras declaradas ao TCE-PR"
                     sub={`as ${obras.length} mais recentes de ${d.obras?.total ?? 0}`} />
          <Lista>
            {obras.map((o) => (
              <li key={o.id} className="py-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                    {o.nome || `Obra ${o.id}`}
                  </span>
                  <span className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                    {money(o.valor)}
                  </span>
                </div>
                <div className="mt-0.5 flex flex-wrap gap-x-4 text-[11px]"
                     style={{ color: "var(--bi-muted)" }}>
                  <span>{o.ano}</span>
                  {o.situacao && <span>{o.situacao}</span>}
                  {o.inicio && <span>início {dia(o.inicio)}</span>}
                  {o.prazo_dias != null && <span>prazo {o.prazo_dias} dias</span>}
                  {o.ultima_medicao && <span>última medição {dia(o.ultima_medicao)}</span>}
                </div>
                {!!o.locais?.length && (
                  <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {o.locais.map((l) => [l.bem, l.logradouro].filter(Boolean).join(" — "))
                      .filter(Boolean).slice(0, 3).join(" · ")}
                  </div>
                )}
              </li>
            ))}
          </Lista>
        </Bloco>
      )}

      {/* ------------------------- Contratos vigentes ------------------------- */}
      {!!vigentes.length && (
        <Bloco className="p-3">
          <BlocoHead icon={FileSignature} titulo="Contratos vigentes — os próximos a vencer"
                     sub="o fim já considera os aditivos de prazo; rescindidos ficam de fora" />
          <Lista>
            {vigentes.slice(0, 20).map((c) => (
              <li key={c.id} className="py-1">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                    Contrato {c.numero}
                    {c.aditivos > 0 && (
                      <span className="ml-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                        {c.aditivos} aditivo(s)
                      </span>
                    )}
                  </span>
                  <span className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                    {money(c.valor)} · até {dia(c.vigencia_ate)}
                  </span>
                </div>
                {c.valor_atual != null && c.valor != null && c.valor_atual !== c.valor && (
                  <div className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                    com aditivos: {money(c.valor_atual)}
                  </div>
                )}
                {c.contratado && (
                  <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{c.contratado}</div>
                )}
                {c.objeto && (
                  <div className="text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                    {c.objeto.slice(0, 140)}
                  </div>
                )}
              </li>
            ))}
          </Lista>
        </Bloco>
      )}

      {/* --------------------------- Licitações --------------------------- */}
      {!!licPorAno.length && (
        <Bloco className="p-3">
          <BlocoHead icon={Gavel} titulo="Licitações por ano"
                     sub="valor ESTIMADO do edital; o homologado sai por item e não é somado aqui" />
          <Lista>
            {licPorAno.map((a) => (
              <li key={a.ano} className="flex flex-wrap items-baseline justify-between gap-x-3 py-1">
                <span className="text-[12px] tabular-nums" style={{ color: "var(--bi-text)" }}>
                  {a.ano} · {a.total} processo(s)
                </span>
                <span className="text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                  {money(a.valor)} estimado
                </span>
              </li>
            ))}
          </Lista>
        </Bloco>
      )}

      <p className="px-1 text-[10px] leading-relaxed" style={{ color: "var(--bi-faint)" }}>
        Fonte: Portal Informação para Todos (pit.tce.pr.gov.br), arquivos anuais do
        SIM-AM{d.referencia ? `, gerados em ${mesAno(d.referencia)}` : ""}. O município
        entrega ao Tribunal mês a mês e o arquivo é publicado depois — por isso os
        dados do ano corrente vão só até o último mês entregue.
      </p>
    </div>
  );
}
