"use client";

/* REPASSES DO FUNDO ESTADUAL DE SAÚDE — RIO GRANDE DO SUL (SES-RS).
 *
 * A mesma pergunta da tela de Goiás ("o que o Estado repassa à saúde do
 * município"), com a fonte que o RS publica: o PAGAMENTO, mês a mês, com as
 * RETENÇÕES e os hospitais que recebem direto. Toda conta vem pronta do backend
 * (`routers/cofinanciamento.py::resumo_fes_rs`) — a tela só desenha.
 *
 * ⚠️ TRÊS DECISÕES DO DONO, e a ordem da tela segue elas:
 * 1. O total é o do FUNDO MUNICIPAL (o dinheiro da prefeitura).
 * 2. A RETENÇÃO do fundo vem em destaque: é dinheiro que não chegou (desconto
 *    CONASEMS, multa de auditoria, pagamento a maior) — e tem motivo e portaria.
 * 3. Hospitais e entidades sediados no município (ASSISTIR, MAC e SUS Gaúcho vão
 *    direto a eles) ficam num bloco RECOLHIDO, FORA do total — o mesmo critério
 *    de «Outros convenentes» na tela de Convênios.
 */

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Building2, CalendarRange, ChevronDown, HeartPulse, Loader2 } from "lucide-react";

import api from "@/lib/api";
import { Aviso, Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import { formatCurrency, formatDate } from "@/lib/utils";

interface Programa {
  projeto: string; pago: number; retido: number; fontes: string[];
  subprojetos: { subprojeto: string; pago: number }[];
}
interface Retencao {
  data: string | null; mes: number; projeto: string | null; subprojeto: string | null;
  motivo: string | null; tipo: string | null; valor: number; competencia: string | null;
  historico: string | null;
}
interface Entidade {
  credor: string; cod_credor: string; pago: number; retido: number;
  retido_por_tipo: Record<string, number>;
  programas: { projeto: string; pago: number }[];
}
interface Resp {
  tem_dados: boolean;
  fonte: string;
  anos: number[];
  ano: number | null;
  pago_ate?: string | null;
  fundo?: {
    credor: string | null; total_pago: number; total_retido: number;
    programas: Programa[]; retencoes: Retencao[];
    retido_por_motivo: { motivo: string; tipo: string | null; valor: number; n: number }[];
  };
  meses?: { mes: number; pago: number; retido: number; entidades: number }[];
  entidades?: { total_pago: number; total_retido: number; itens: Entidade[] };
}

const MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const TIPO: Record<string, string> = {
  desconto: "desconto", tributo: "tributo do prestador", judicial: "bloqueio judicial",
  consignado: "consignado", outra: "outra retenção",
};

export function FesRs({ municipioId, titulo, fonte }: {
  municipioId: string; titulo: string; fonte: string;
}) {
  const [ano, setAno] = useState<number | null>(null);
  const [data, setData] = useState<Resp | null>(null);
  const [carimbo, setCarimbo] = useState("");
  const [loading, setLoading] = useState(false);
  const [abertoProg, setAbertoProg] = useState<string | null>(null);
  const [abertoEnt, setAbertoEnt] = useState(false);

  const carregar = useCallback(() => {
    const meu = `${municipioId}|${ano ?? ""}`;
    setLoading(true);
    api.get<Resp>("/cofinanciamento/fes-rs", { params: { municipio_id: municipioId, ano: ano ?? undefined } })
      .then((r) => { setData(r.data); setCarimbo(meu); })
      .catch(() => { setData(null); setCarimbo(meu); })
      .finally(() => setLoading(false));
  }, [municipioId, ano]);

  useEffect(() => {
    let vivo = true;
    Promise.resolve().then(() => { if (vivo) carregar(); });
    return () => { vivo = false; };
  }, [carregar]);

  const doMun = carimbo === `${municipioId}|${ano ?? ""}`;
  const d = doMun ? data : null;
  if (loading && !doMun) {
    return <div className="flex justify-center py-14"><Loader2 className="size-6 animate-spin" /></div>;
  }
  if (!d?.tem_dados || !d.fundo || !d.entidades) {
    return (
      <div className="space-y-4">
        <div>
          <TituloTela>{titulo}</TituloTela>
          <p className="text-sm text-muted-foreground">{fonte}</p>
        </div>
        <Vazio>Nenhum pagamento do Fundo Estadual de Saúde coletado para este município ainda.</Vazio>
      </div>
    );
  }

  const f = d.fundo;
  const ent = d.entidades;
  const meses = d.meses || [];
  const maxMes = Math.max(1, ...meses.map((m) => m.pago));
  const descontos = f.retido_por_motivo;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <TituloTela>{titulo}</TituloTela>
          <p className="text-sm text-muted-foreground">
            {fonte}{d.pago_ate ? ` · pagamentos até ${formatDate(d.pago_ate)}` : ""}
          </p>
        </div>
        {d.anos.length > 1 && (
          <select className="select select-bordered select-sm" aria-label="Ano"
                  value={d.ano ?? ""} onChange={(e) => setAno(Number(e.target.value))}>
            {d.anos.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Numero icon={HeartPulse} rotulo={`Pago ao Fundo Municipal em ${d.ano}`} tom="acento"
                valor={formatCurrency(f.total_pago)}
                sub={`${f.programas.length} programa(s)${f.credor ? ` · ${f.credor}` : ""}`} />
        <Numero icon={AlertTriangle} rotulo="Retido do Fundo Municipal"
                tom={f.total_retido > 0 ? "critico" : "neutro"}
                valor={formatCurrency(f.total_retido)}
                sub={f.total_retido > 0 ? `${f.retencoes.length} retenção(ões) — dinheiro que não chegou`
                                        : "nenhuma retenção no ano"} />
        <Numero icon={Building2} rotulo="Hospitais e entidades no município"
                valor={formatCurrency(ent.total_pago)}
                sub="pago direto a eles — fora do total da prefeitura" />
      </div>

      {f.total_retido > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={AlertTriangle} titulo="Retenções no repasse ao Fundo Municipal"
                     sub="Descontados pelo Estado antes do pagamento — o motivo e a portaria vêm da própria SES" />
          <Aviso tom="critico" className="mb-2" titulo={
            <>{formatCurrency(f.total_retido)} retidos em {d.ano}:{" "}
              {descontos.map((m) => `${m.motivo} (${formatCurrency(m.valor)})`).join("; ")}</>
          } />
          <Lista>
            {f.retencoes.map((r, i) => (
              <ItemLinha key={i}
                titulo={<span className="flex flex-wrap items-center gap-x-2">
                  <span>{r.motivo || "Retenção sem motivo informado"}</span>
                  {r.tipo && <Selo tom="critico">{TIPO[r.tipo] || r.tipo}</Selo>}
                </span>}
                valor={formatCurrency(r.valor)}
                meta={<>
                  {r.data && <span>{formatDate(r.data)}</span>}
                  {r.projeto && <span>· {r.projeto}</span>}
                  {r.competencia && <span>· competência {r.competencia}</span>}
                </>}
              >
                {r.historico && (
                  <p className="mt-1 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                    {r.historico}
                  </p>
                )}
              </ItemLinha>
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={HeartPulse} titulo="Por programa — Fundo Municipal de Saúde"
                   sub="Soma do ano, do maior para o menor. Toque para ver os subprojetos." />
        <Lista>
          {f.programas.map((p) => (
            <ItemLinha key={p.projeto}
              onClick={() => setAbertoProg(abertoProg === p.projeto ? null : p.projeto)}
              expandido={abertoProg === p.projeto}
              titulo={<span className="flex flex-wrap items-center gap-x-2">
                <span>{p.projeto}</span>
                {p.fontes.includes("FEDERAL") && <Selo>recurso federal via Estado</Selo>}
                {p.retido > 0 && <Selo tom="critico">retido {formatCurrency(p.retido)}</Selo>}
              </span>}
              valor={formatCurrency(p.pago)}
            >
              {abertoProg === p.projeto && (
                <Campos cols={1} campos={p.subprojetos.map((s) => ({
                  rotulo: s.subprojeto, valor: formatCurrency(s.pago),
                }))} />
              )}
            </ItemLinha>
          ))}
        </Lista>
      </Bloco>

      {meses.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={CalendarRange} titulo="Mês a mês — pago ao Fundo Municipal"
                     sub="Pelo mês do pagamento (a competência de cada parcela está no detalhe)" />
          {/* Uma série só: barra na cor de acento, valor em texto ao lado — a
              própria lista é a tabela. A retenção do mês vai em texto crítico. */}
          <ul className="flex flex-col gap-1">
            {meses.map((m) => (
              <li key={m.mes} className="grid grid-cols-[2.5rem_1fr_auto] items-center gap-2 text-[12px]"
                  title={`${MES[m.mes - 1]}/${d.ano}: ${formatCurrency(m.pago)} ao fundo`
                    + (m.retido ? `, ${formatCurrency(m.retido)} retido` : "")
                    + ` · ${formatCurrency(m.entidades)} a hospitais e entidades`}>
                <span style={{ color: "var(--bi-muted)" }}>{MES[m.mes - 1]}</span>
                <span className="h-2.5 rounded-sm" style={{ background: "var(--bi-surface-2)" }}>
                  <span className="block h-full rounded-sm"
                        style={{ width: `${Math.max(0, (m.pago / maxMes) * 100)}%`, background: "var(--bi-accent)" }} />
                </span>
                <span className="bi-num text-right">
                  {formatCurrency(m.pago)}
                  {m.retido > 0 && (
                    <span className="ml-1.5" style={{ color: "var(--bi-crit-ink)" }}>
                      −{formatCurrency(m.retido)}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Bloco>
      )}

      {ent.itens.length > 0 && (
        <Bloco className="p-3">
          <button type="button" className="w-full text-left" onClick={() => setAbertoEnt(!abertoEnt)}
                  aria-expanded={abertoEnt}>
            <BlocoHead
              icon={Building2}
              titulo={`Hospitais e entidades no município · ${ent.itens.length} · ${formatCurrency(ent.total_pago)}`}
              sub="ASSISTIR, MAC e SUS Gaúcho vão direto ao prestador — não é a prefeitura e fica fora do total desta tela"
              right={<ChevronDown className={`size-4 transition-transform ${abertoEnt ? "rotate-180" : ""}`} />}
            />
          </button>
          {abertoEnt && (
            <Lista>
              {ent.itens.map((e) => (
                <ItemLinha key={e.cod_credor}
                  titulo={<span className="flex flex-wrap items-center gap-x-2">
                    <span>{e.credor}</span>
                    <Selo>não é a prefeitura</Selo>
                  </span>}
                  valor={formatCurrency(e.pago)}
                  meta={e.retido > 0 ? <span>
                    retido {formatCurrency(e.retido)} (
                    {Object.entries(e.retido_por_tipo)
                      .map(([t, v]) => `${TIPO[t] || t} ${formatCurrency(v)}`).join("; ")})
                  </span> : undefined}
                >
                  <Campos cols={1} campos={e.programas.slice(0, 8).map((p) => ({
                    rotulo: p.projeto, valor: formatCurrency(p.pago),
                  }))} />
                </ItemLinha>
              ))}
            </Lista>
          )}
        </Bloco>
      )}
    </div>
  );
}
