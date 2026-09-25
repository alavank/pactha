"use client";

/* FUNDO A FUNDO ESTADUAL DA SAÚDE — MINAS GERAIS (24/09/2026).
 *
 * Cada ordem de pagamento da SES-MG ao Fundo Municipal, por Resolução SES
 * (`ingestion/ses_mg_resolucoes.py`). A conta — o que soma e o que fica à parte —
 * vem PRONTA de `GET /api/cofinanciamento/mg` (`services/ses_mg_fundo.py`); esta
 * tela não soma nada por conta própria.
 *
 * ⚠️ TRÊS NÚMEROS QUE NÃO SE SOMAM, e a tela diz por quê:
 *  · ORDINÁRIO — o repasse que sustenta a rede (APS, CBAF, farmácia...). É o total.
 *  · EMENDA por Resolução SES — já está em Emendas parlamentares › Estaduais (MG),
 *    pela indicação. Aqui só aparece o PAGAMENTO, ligado à indicação quando há
 *    chave (nº da Resolução + conta).
 *  · RESTOS A PAGAR — empenho de ano anterior pago agora; o de empenho que está no
 *    Acordo FES leva o selo, e não entra na dívida da tela do Acordo.
 */

import React, { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import {
  Abas, Aviso, Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { Gift, HeartPulse, History, Landmark, Loader2, Users } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";
import { TituloTela } from "@/components/TituloTela";

interface Pagamento {
  id_fonte: number;
  data: string | null;
  valor: number;
  resolucao: string | null;
  num_ob: string | null;
  num_empenho: string | null;
  ano_empenho: number | null;
  cod_upg: string | null;
  upg: string | null;
  atividade: string | null;
  banco: string | null;
  agencia: string | null;
  conta: string | null;
  cnpj_credor: string;
  razao_credor: string | null;
  indicacao?: {
    nr_indicacao: string; autor: string | null;
    valor_indicacao: number | null; valor_pago_segov: number | null;
  } | null;
  acordo_fes?: { divida_atual: number; resolucao: string | null } | null;
}
interface Programa {
  cod_upg: string | null; upg: string | null; atividade: string | null;
  total: number; n: number; ultimo_pagamento: string | null; pagamentos: Pagamento[];
}
interface BlocoAParte { total: number; n: number; pagamentos: Pagamento[]; ligadas?: number }
interface Resp {
  tem_dados: boolean;
  anos: number[];
  ano: number | null;
  coletado_em?: string | null;
  fonte_atualizada_em?: string | null;
  lido_orcamentario?: boolean;
  lido_restos?: boolean;
  ordinario?: { total: number; n: number; programas: Programa[] };
  emendas?: BlocoAParte;
  emendas_federais?: BlocoAParte;
  acordo_fes?: BlocoAParte;
  restos?: { total: number; n: number; total_acordo_fes: number; pagamentos: Pagamento[] };
  outros_credores?: { cnpj: string; razao_social: string | null; total: number; n: number }[];
}

const cnpjFmt = (c: string) =>
  /^\d{14}$/.test(c) ? c.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5") : c;

function linhaPagamento(p: Pagamento, extra?: React.ReactNode) {
  return (
    <ItemLinha
      key={p.id_fonte}
      titulo={<span>Res. {p.resolucao || "—"}{extra}</span>}
      valor={formatCurrency(p.valor)}
      meta={
        <>
          {formatDate(p.data)}
          {p.num_ob ? ` · OB ${p.num_ob}` : ""}
          {p.num_empenho ? ` · empenho ${p.num_empenho}${p.ano_empenho ? `/${p.ano_empenho}` : ""}` : ""}
          {p.conta ? ` · conta ${p.agencia || "?"} / ${p.conta}` : ""}
        </>
      }
    />
  );
}

export function FundoAFundoMG({ municipioId, titulo, fonte }: {
  municipioId: string | number; titulo: string; fonte: string;
}) {
  const [ano, setAno] = useState<number | null>(null);
  const [data, setData] = useState<Resp | null>(null);
  const [carimbo, setCarimbo] = useState("");
  const [loading, setLoading] = useState(false);
  const [aberto, setAberto] = useState<string | null>(null);

  const carregar = useCallback(() => {
    const meu = `${municipioId}:${ano ?? ""}`;
    setLoading(true);
    api.get<Resp>("/cofinanciamento/mg", { params: { municipio_id: municipioId, ...(ano ? { ano } : {}) } })
      .then((r) => { setData(r.data); setCarimbo(meu); })
      .catch(() => { setData(null); setCarimbo(meu); })
      .finally(() => setLoading(false));
  }, [municipioId, ano]);

  /* Microtask: o mesmo idioma da tela de Goiás (setState síncrono em effect). */
  useEffect(() => {
    let vivo = true;
    Promise.resolve().then(() => { if (vivo) carregar(); });
    return () => { vivo = false; };
  }, [carregar]);

  const doMun = carimbo === `${municipioId}:${ano ?? ""}`;
  const d = doMun ? data : null;

  if (loading && !doMun) {
    return <div className="flex justify-center py-14"><Loader2 className="size-6 animate-spin" /></div>;
  }
  if (!d?.tem_dados || !d.ordinario) {
    return (
      <Vazio>
        Nenhum pagamento da SES-MG coletado ainda para este município. A coleta roda toda
        noite e lê o painel de Pagamento de Resoluções da Secretaria de Estado de Saúde.
      </Vazio>
    );
  }

  const ord = d.ordinario;
  const em = d.emendas!;
  const rp = d.restos!;
  const fed = d.emendas_federais!;
  const fes = d.acordo_fes!;
  const outros = d.outros_credores || [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <TituloTela>{titulo}</TituloTela>
          <p className="text-sm text-muted-foreground">
            {fonte}
            {d.fonte_atualizada_em ? ` · painel atualizado em ${formatDate(d.fonte_atualizada_em)}` : ""}
            {d.coletado_em ? ` · lido em ${formatDate(d.coletado_em)}` : ""}
          </p>
        </div>
        {d.anos.length > 1 && (
          <Abas<string>
            valor={String(d.ano)}
            onChange={(v) => setAno(Number(v))}
            opcoes={d.anos.map((a) => ({ valor: String(a), label: String(a) }))}
          />
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Numero icon={HeartPulse} rotulo={`Fundo a fundo ordinário em ${d.ano}`} tom="acento"
                valor={formatCurrency(ord.total)}
                sub={`${ord.n} pagamento(s) ao Fundo Municipal, em ${ord.programas.length} programa(s)`} />
        <Numero icon={Gift} rotulo="Emendas pagas por Resolução SES"
                valor={formatCurrency(em.total)}
                sub="à parte — já contadas em Emendas parlamentares › Estaduais" />
        <Numero icon={History} rotulo="Restos a pagar pagos no ano"
                valor={formatCurrency(rp.total)}
                sub={rp.total_acordo_fes > 0
                  ? `${formatCurrency(rp.total_acordo_fes)} de empenhos do Acordo FES`
                  : `${rp.n} pagamento(s) de empenhos de anos anteriores`} />
      </div>

      {d.lido_restos === false && (
        <Aviso tom="atencao" titulo="Os restos a pagar deste ano ainda não foram lidos inteiros." className="" />
      )}

      <Bloco className="p-3">
        <BlocoHead icon={HeartPulse} titulo="Ordinário, por programa"
                   sub="O repasse que sustenta a rede — incentivos, farmácia, vigilância. É o total desta tela." />
        {ord.programas.length === 0 ? (
          <p className="px-1 text-[12px]" style={{ color: "var(--bi-muted)" }}>
            Nenhum pagamento ordinário neste ano.
          </p>
        ) : (
          <Lista>
            {ord.programas.map((p) => {
              const k = `p${p.cod_upg}`;
              /* O extrato abre como IRMÃO do item, e não dentro dele: com
                 `onClick` o corpo do ItemLinha é um <button>, e lista dentro de
                 botão é HTML inválido (e o leitor de tela lê tudo como um rótulo). */
              return (
                <React.Fragment key={k}>
                  <ItemLinha
                    titulo={p.upg || `UPG ${p.cod_upg}`}
                    valor={formatCurrency(p.total)}
                    onClick={() => setAberto(aberto === k ? null : k)}
                    expandido={aberto === k}
                    meta={
                      <>
                        UPG {p.cod_upg} · {p.atividade || "—"} · {p.n} pagamento(s)
                        {p.ultimo_pagamento ? ` · último em ${formatDate(p.ultimo_pagamento)}` : ""}
                      </>
                    }
                  />
                  {aberto === k && (
                    <li className="pl-4">
                      <Lista>{p.pagamentos.map((x) => linhaPagamento(x))}</Lista>
                    </li>
                  )}
                </React.Fragment>
              );
            })}
          </Lista>
        )}
      </Bloco>

      {em.n > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={Gift} titulo="Emendas pagas por Resolução SES"
                     sub={`À parte do total: a emenda já soma em Emendas parlamentares › Estaduais (MG). ${em.ligadas || 0} de ${em.n} pagamento(s) ligados à indicação pela Resolução e pela conta.`} />
          <Lista>
            {em.pagamentos.map((p) => (
              <ItemLinha
                key={p.id_fonte}
                titulo={
                  <span className="flex flex-wrap items-center gap-x-2">
                    <span>Res. {p.resolucao || "—"}</span>
                    {p.indicacao
                      ? <Selo tom="ok">indicação {p.indicacao.nr_indicacao}</Selo>
                      : <Selo>sem indicação ligada</Selo>}
                  </span>
                }
                valor={formatCurrency(p.valor)}
                meta={
                  <>
                    {formatDate(p.data)}{p.num_ob ? ` · OB ${p.num_ob}` : ""} · {p.atividade || p.upg}
                  </>
                }
              >
                {p.indicacao && (
                  <Campos cols={3} campos={[
                    { rotulo: "Autor", valor: p.indicacao.autor || "—" },
                    { rotulo: "Valor indicado", valor: formatCurrency(p.indicacao.valor_indicacao) },
                    { rotulo: "Pago segundo a SEGOV", valor: formatCurrency(p.indicacao.valor_pago_segov),
                      tom: (p.indicacao.valor_pago_segov ?? 0) < p.valor ? "atencao" : "normal",
                      title: "O CSV da SEGOV pode estar atrás do pagamento que a SES já fez." },
                  ]} />
                )}
              </ItemLinha>
            ))}
          </Lista>
        </Bloco>
      )}

      {rp.n > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={History} titulo="Restos a pagar pagos no ano"
                     sub="Empenho de ano anterior pago agora. O de empenho que está na dívida do Acordo FES leva o selo." />
          <Lista>
            {rp.pagamentos.map((p) => linhaPagamento(p, p.acordo_fes
              ? <Selo tom="atencao">empenho do Acordo FES</Selo> : null))}
          </Lista>
        </Bloco>
      )}

      {(fed.n > 0 || fes.n > 0) && (
        <Bloco className="p-3">
          <BlocoHead icon={Landmark} titulo="Outros pagamentos pelo fundo estadual"
                     sub="Emenda federal repassada pela SES e recomposição do Acordo FES — fora do ordinário." />
          <Lista>
            {fed.pagamentos.map((p) => linhaPagamento(p, <Selo>emenda federal</Selo>))}
            {fes.pagamentos.map((p) => linhaPagamento(p, <Selo tom="atencao">recomposição do Acordo FES</Selo>))}
          </Lista>
        </Bloco>
      )}

      {outros.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={Users} titulo="Outros credores sediados no município"
                     sub="Consórcios, hospitais e entidades: a SES os lista pelo município, mas o CNPJ não é do município. Fora de toda conta." />
          <Lista>
            {outros.map((o) => (
              <ItemLinha key={o.cnpj} titulo={o.razao_social || cnpjFmt(o.cnpj)}
                         valor={formatCurrency(o.total)}
                         meta={<>{cnpjFmt(o.cnpj)} · {o.n} pagamento(s)</>} />
            ))}
          </Lista>
        </Bloco>
      )}
    </div>
  );
}
