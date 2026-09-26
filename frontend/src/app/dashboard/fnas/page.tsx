"use client";

/* ASSISTÊNCIA SOCIAL — FNAS. O Fundo Nacional de Assistência Social (MDS) deposita
 * nas contas do Fundo Municipal de Assistência Social (FMAS): uma por bloco (PSB,
 * PSE, IGD) e uma por programa ou emenda. Esta tela responde o que o PACTHA não
 * respondia:
 *
 *   1. quanto está em cada conta do fundo, no mês mais novo que o MDS publicou
 *      (em 26/09/2026, agosto) — e quanto disso está PARADO: conta que não recebe
 *      nada há 12 meses e cujo saldo não caiu (só rendeu juros);
 *   2. de qual emenda veio o dinheiro que está parado (parlamentar, ano, OB);
 *   3. o que o FNAS mandou nos últimos 12 meses, por bloco, OB a OB.
 *
 * ⚠️ A CONTA É DO BACKEND (`services/fnas.py::montar`). Esta tela só desenha: nada
 * é somado aqui, para o mesmo dado não dar duas contas.
 *
 * O total por mês que a CGU publica (FNAS por ação) está em «Recursos recebidos
 * por pasta»; aqui é a visão do fundo: conta, saldo e OB.
 */

import React, { useEffect, useState } from "react";
import { BadgeDollarSign, HandHeart, Info, Landmark, Loader2, PiggyBank, Wallet } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Aviso, Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import { formatCurrency } from "@/lib/utils";

interface EmendaConta {
  parlamentar: string;
  partido: string | null;
  ano: number | null;
  valor: number;
  dt_ob: string | null;
  tipo_emenda: string | null;
}
interface Conta {
  agencia: string;
  conta: string;
  cnpj: string;
  tipo_entidade: string | null;
  bloco: string | null;
  nome: string | null;
  saldo: number;
  por_tipo: { conta_corrente: number; poupanca: number; fundos: number; cdb_rdb: number };
  saldo_12m_antes: number | null;
  repassado_12m: number;
  ultimo_repasse: string | null;
  meses_de_repasse: number | null;
  parado: boolean | null;
  emendas: EmendaConta[];
}
interface Ob {
  competencia: string;
  dt_ob: string | null;
  ob: string | null;
  piso: string | null;
  programa: string | null;
  conta: string | null;
  valor: number;
}
interface Emenda {
  parlamentar: string;
  partido: string | null;
  tipo_emenda: string | null;
  programa: string | null;
  ano: number | null;
  valor: number;
  dt_ob: string | null;
  ob: string | null;
  conta: string | null;
  saldo_conta_hoje: number | null;
}
interface Carga { lido_em: string | null; painel_em: string | null; historico: boolean }
interface Resp {
  coletado: boolean;
  mes_referencia?: string | null;
  cargas?: Record<"saldo" | "repasse" | "emenda", Carga | null>;
  totais?: {
    saldo: number; saldo_12m_antes: number | null; contas: number; repassado_12m: number;
    repassado_12m_desde: string; contas_paradas: number; saldo_parado: number;
    emendas: number; emendas_valor: number; parlamentares: number;
  } | null;
  contas?: Conta[];
  repasses_12m?: Array<{ bloco: string; total: number; obs: Ob[] }>;
  emendas?: Emenda[];
}

const moeda = (v: number | null | undefined) => (v == null ? "—" : formatCurrency(v));
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
  "setembro", "outubro", "novembro", "dezembro"];
const mesExtenso = (iso?: string | null) => {
  if (!iso) return "—";
  const [a, m] = iso.split("-");
  return `${MESES[Number(m) - 1]} de ${a}`;
};
const mesCurto = (iso?: string | null) => {
  if (!iso) return "—";
  const [a, m] = iso.split("-");
  return `${m}/${a}`;
};
const dataCurta = (iso?: string | null) => {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
};
function dataHora(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export default function FnasPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<{ chave: string; r: Resp | null; erro: boolean } | null>(null);
  const chave = String(municipioId);

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api.get<Resp>("/fnas", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setD({ chave, r: r.data, erro: false }); })
      .catch(() => { if (vivo) setD({ chave, r: null, erro: true }); });
    return () => { vivo = false; };
  }, [municipioId, chave]);

  const cabecalho = (
    <div>
      <TituloTela>Assistência social — FNAS</TituloTela>
      <p className="text-sm text-muted-foreground">
        O dinheiro em cada conta do fundo municipal de assistência social, o que está parado e de
        qual emenda ele veio
      </p>
    </div>
  );

  if (!municipioId) return <Vazio>Escolha um município no seletor para ver o fundo de assistência social.</Vazio>;
  if (!d || d.chave !== chave) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> carregando…
        </div>
      </div>
    );
  }
  if (d.erro || !d.r) {
    return <div className="space-y-4">{cabecalho}<Vazio>Não foi possível carregar o FNAS.</Vazio></div>;
  }
  if (!d.r.coletado || !d.r.totais) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <Vazio>
          O painel de repasses do MDS ainda não foi lido para este município. Isto não significa
          que o fundo não tem saldo — significa que ainda não conferimos.
        </Vazio>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {cabecalho}
      <Conteudo r={d.r} />
    </div>
  );
}

function Conteudo({ r }: { r: Resp }) {
  const t = r.totais!;
  const [aberta, setAberta] = useState<string | null>(null);
  const [bloco, setBloco] = useState<string | null>(null);
  const contas = r.contas || [];
  const paradas = contas.filter((c) => c.parado);
  const variacao = t.saldo_12m_antes == null ? null : t.saldo - t.saldo_12m_antes;

  return (
    <>
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        Painel de Repasses Fundo a Fundo do MDS · saldo de <strong>{mesExtenso(r.mes_referencia)}</strong> (o
        mês mais novo publicado), painel de {dataHora(r.cargas?.saldo?.painel_em)} · lido pelo PACTHA
        em {dataHora(r.cargas?.saldo?.lido_em)}
      </p>

      {paradas.length > 0 && (
        <Aviso tom="atencao" icon={PiggyBank} className="" titulo={
          `${moeda(t.saldo_parado)} parados em ${paradas.length} conta(s): sem repasse e sem gasto há 12 meses`}>
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {paradas.slice(0, 6).map((c) => (
              <li key={`${c.agencia}|${c.conta}`}>
                {moeda(c.saldo)} · {c.nome || c.bloco}
                {c.emendas.length > 0 && ` · emenda de ${c.emendas.map((e) => `${e.parlamentar} (${e.ano ?? "—"})`).join(", ")}`}
              </li>
            ))}
          </ul>
        </Aviso>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Numero icon={Wallet} tom="acento" rotulo={`Saldo no fundo em ${mesExtenso(r.mes_referencia)}`}
                valor={moeda(t.saldo)}
                sub={variacao == null
                  ? `${t.contas} conta(s) · conta, poupança, fundos e CDB`
                  : `${t.contas} conta(s) · ${variacao >= 0 ? "+" : "−"}${moeda(Math.abs(variacao))} em 12 meses`} />
        <Numero icon={PiggyBank} tom={t.contas_paradas ? "atencao" : "neutro"}
                rotulo="Parado: sem repasse e sem gasto em 12 meses" valor={moeda(t.saldo_parado)}
                sub={`${t.contas_paradas} conta(s) em que o saldo só rendeu juros`} />
        <Numero icon={Landmark} rotulo={`Repassado pelo FNAS (${mesCurto(t.repassado_12m_desde)} a ${mesCurto(r.mes_referencia)})`}
                valor={moeda(t.repassado_12m)}
                sub="12 meses de competência, todos os blocos e programas" />
        <Numero icon={BadgeDollarSign} rotulo="Emendas de assistência social" valor={moeda(t.emendas_valor)}
                sub={t.emendas ? `${t.emendas} emenda(s) de ${t.parlamentares} parlamentar(es), todo o histórico do painel` : "nenhuma emenda no painel"} />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={HandHeart} titulo="Contas do fundo"
                   sub="paradas primeiro, depois o maior saldo · clique para ver onde o dinheiro está aplicado e as emendas da conta" />
        {contas.length === 0 ? (
          <Vazio>Nenhuma conta com saldo publicado neste mês.</Vazio>
        ) : (
          <Lista className="mt-2">
            {contas.map((c) => {
              const k = `${c.agencia}|${c.conta}`;
              const ab = aberta === k;
              return (
                <ItemLinha key={k} onClick={() => setAberta(ab ? null : k)} expandido={ab}
                           titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                             <span>{c.nome || c.bloco || `conta ${c.conta}`}</span>
                             {c.parado && <Selo tom="atencao">parado há 12 meses</Selo>}
                             {c.meses_de_repasse != null && c.meses_de_repasse >= 12 && (
                               <Selo tom="atencao">{c.meses_de_repasse.toLocaleString("pt-BR")} meses de repasse em conta</Selo>
                             )}
                             {c.emendas.length > 0 && <Selo>emenda</Selo>}
                             {c.tipo_entidade === "PREFEITURA" && <Selo>conta da prefeitura</Selo>}
                           </span>}
                           valor={moeda(c.saldo)}
                           meta={<>
                             <span className="bi-id">ag. {c.agencia} · c/c {c.conta}</span>
                             {c.saldo_12m_antes != null && <span>· 12 meses antes: {moeda(c.saldo_12m_antes)}</span>}
                             <span>· repassado em 12 meses: {moeda(c.repassado_12m)}</span>
                             <span>· última OB: {dataCurta(c.ultimo_repasse)}</span>
                           </>}>
                  {ab && <DetalheConta c={c} />}
                </ItemLinha>
              );
            })}
          </Lista>
        )}
      </Bloco>

      {(r.emendas || []).length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={BadgeDollarSign} titulo="Emendas de assistência social"
                     sub="cada emenda com a conta onde a OB caiu e o saldo que essa conta tem hoje" />
          <Lista className="mt-2">
            {r.emendas!.map((e, i) => (
              <ItemLinha key={`${e.ob}|${e.parlamentar}|${i}`}
                         titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                           <span>{e.parlamentar}</span>
                           {e.partido && <Selo>{e.partido}</Selo>}
                           {e.tipo_emenda && <Selo>{e.tipo_emenda}</Selo>}
                         </span>}
                         valor={moeda(e.valor)}
                         meta={<>
                           <span>{e.ano ?? "—"}</span>
                           <span>· {e.programa}</span>
                           <span>· OB {e.ob || "—"} em {dataCurta(e.dt_ob)}</span>
                           {e.conta && <span className="bi-id">· c/c {e.conta}</span>}
                           <span>· saldo da conta hoje: {moeda(e.saldo_conta_hoje)}</span>
                         </>} />
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={Landmark} titulo="Repasses dos últimos 12 meses, por bloco"
                   sub="competência de cada OB · clique para ver as ordens bancárias" />
        {(r.repasses_12m || []).length === 0 ? (
          <Vazio>Nenhum repasse do FNAS com competência nos últimos 12 meses.</Vazio>
        ) : (
          <Lista className="mt-2">
            {r.repasses_12m!.map((b) => {
              const ab = bloco === b.bloco;
              return (
                <ItemLinha key={b.bloco} onClick={() => setBloco(ab ? null : b.bloco)} expandido={ab}
                           titulo={b.bloco} valor={moeda(b.total)}
                           meta={<span>{b.obs.length} OB(s)</span>}>
                  {ab && (
                    <ul className="mt-2 space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                      {b.obs.map((o, i) => (
                        <li key={`${o.ob}|${i}`}>
                          {dataCurta(o.dt_ob)} · OB {o.ob || "—"} · competência {o.competencia} ·{" "}
                          {o.programa || o.piso} · {moeda(o.valor)}
                          {o.conta && <span className="bi-id"> · c/c {o.conta}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </ItemLinha>
              );
            })}
          </Lista>
        )}
      </Bloco>

      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        <Info className="mr-1 inline size-3.5 align-[-2px]" />
        «Parado» é a conta que não recebeu repasse em 12 meses e cujo saldo não caiu mais de 10% no
        período — o dinheiro só rendeu. «Meses de repasse em conta» divide o saldo pela média mensal
        repassada; é uma régua para comparar contas, não uma regra do MDS.
      </p>
    </>
  );
}

function DetalheConta({ c }: { c: Conta }) {
  return (
    <div className="mt-3 space-y-3">
      <Campos cols={4} campos={[
        { rotulo: "Em conta corrente", valor: moeda(c.por_tipo.conta_corrente) },
        { rotulo: "Em poupança", valor: moeda(c.por_tipo.poupanca) },
        { rotulo: "Em fundos", valor: moeda(c.por_tipo.fundos) },
        { rotulo: "Em CDB/RDB", valor: moeda(c.por_tipo.cdb_rdb) },
      ]} />
      {c.emendas.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
            Emendas que caíram nesta conta ({c.emendas.length})
          </div>
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {c.emendas.map((e, i) => (
              <li key={i}>
                <strong>{e.parlamentar}</strong>{e.partido ? ` (${e.partido})` : ""} · {e.ano ?? "—"} ·{" "}
                {moeda(e.valor)} · OB em {dataCurta(e.dt_ob)}{e.tipo_emenda ? ` · ${e.tipo_emenda}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        {c.bloco ? `${c.bloco} · ` : ""}titular {c.tipo_entidade?.toLowerCase() || "—"}
        {c.meses_de_repasse != null ? ` · saldo equivale a ${c.meses_de_repasse.toLocaleString("pt-BR")} meses do repasse médio` : ""}
      </p>
    </div>
  );
}
