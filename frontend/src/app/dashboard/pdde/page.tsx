"use client";

/* PDDE — DINHEIRO NAS ESCOLAS. O Programa Dinheiro Direto na Escola (FNDE)
 * deposita na conta de cada ESCOLA — da caixa escolar/APM (a UEx) ou, se a
 * escola não tem uma, da prefeitura (a EEx). Esta tela responde duas perguntas
 * que o PACTHA não respondia:
 *
 *   1. quanto está PARADO nessas contas (dinheiro que a escola não gastou), no
 *      mês de referência que o FNDE publica — em 24/09/2026, agosto;
 *   2. qual escola está SUSPENSA — é a próxima parcela que não vem.
 *
 * ⚠️ A CONTA É DO BACKEND (`services/pdde.py::montar`). Esta tela só desenha:
 * nada é somado aqui, para o mesmo dado não dar duas contas.
 *
 * ⚠️ A REDE DECIDE DE QUEM É O DINHEIRO. Muita caixa escolar do município é de
 * escola ESTADUAL (em Monte Sião, os R$ 238 mil da «Renato Franco Bueno»). A
 * conta padrão é a rede MUNICIPAL; as outras aparecem à parte e em «Todas as
 * redes», nunca somadas como se fossem da prefeitura.
 *
 * ⚠️ O DINHEIRO QUE ENTROU são as liberações do FNDE por entidade (a consulta
 * `pls/simad` — o mesmo dado do bloco das escolas na tela do SIMEC), pelo CNPJ da
 * caixa escolar — não de uma segunda coleta.
 */

import React, { useEffect, useState } from "react";
import { AlertTriangle, Ban, Info, Loader2, PiggyBank, School, Wallet } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Abas, Aviso, Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import { formatCurrency } from "@/lib/utils";

type Rede = "municipal" | "todas";

interface Suspensao {
  escola_inep: string | null;
  escola_nome: string | null;
  programa: string | null;
  destinacao: string | null;
  tipo: string;
  rede: string;
}
interface Escola {
  inep: string | null;
  nome: string | null;
  programas: string[];
  previsto: number | null;
  situacao_uex: string | null;
  situacao_eex: string | null;
  suspensa_pc: boolean;
  eex: string | null;
}
interface Entidade {
  cnpj: string;
  nome: string | null;
  prefeitura: boolean;
  redes: string[];
  municipal: boolean;
  saldo: number | null;
  saldo_por_tipo: { conta: number; fundos: number; poupanca: number; rdb_cdb: number };
  saldo_6_meses_antes: number | null;
  previsto_ano: number | null;
  parado: boolean | null;
  recebido_ano: number | null;
  contas: Array<{ banco: string; agencia: string; conta: string; programa: string; saldo: number }>;
  escolas: Escola[];
  suspensoes: Suspensao[];
  suspensa: boolean;
  situacoes_pc: string[];
}
interface Resp {
  coletado: boolean;
  rede?: Rede;
  mes_referencia?: string | null;
  ano?: number;
  saldo_carregado_em?: string | null;
  prestacao_carregada_em?: string | null;
  suspensao_carregada_em?: string | null;
  meses_carregados?: number;
  liberacoes_fnde?: { fechamento: string | null; lido_em: string | null } | null;
  totais?: {
    saldo: number; entidades: number; contas: number; escolas: number;
    escolas_suspensas: number; entidades_paradas: number; saldo_parado: number;
    previsto_ano: number; recebido_ano: number | null; entidades_com_liberacao: number;
  };
  prefeitura_eex?: { situacoes: string[]; suspensa: boolean; escolas: number } | null;
  suspensoes_por_tipo?: Array<{ tipo: string; escolas: number }>;
  sem_executora?: Suspensao[];
  entidades?: Entidade[];
  outras_redes?: { saldo: number; entidades: number; suspensas: number } | null;
}

const moeda = (v: number | null | undefined) => (v == null ? "—" : formatCurrency(v));
const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
  "setembro", "outubro", "novembro", "dezembro"];
const mesExtenso = (iso?: string | null) => {
  if (!iso) return "—";
  const [a, m] = iso.split("-");
  return `${MESES[Number(m) - 1]} de ${a}`;
};
const dataCurta = (iso: string) => {
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
};
function dataHora(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}
const cnpjFmt = (c: string) =>
  c.length === 14 ? `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}` : c;
const ROTULO_REDE: Record<string, string> = {
  municipal: "municipal", estadual: "estadual", particular: "particular", federal: "federal", outra: "outra",
};

export default function PddePage() {
  const { municipioId } = useMunicipio();
  const [rede, setRede] = useState<Rede>("municipal");
  const [d, setD] = useState<{ chave: string; r: Resp | null; erro: boolean } | null>(null);
  const chave = `${municipioId}|${rede}`;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api.get<Resp>("/pdde", { params: { municipio_id: municipioId, rede } })
      .then((r) => { if (vivo) setD({ chave, r: r.data, erro: false }); })
      .catch(() => { if (vivo) setD({ chave, r: null, erro: true }); });
    return () => { vivo = false; };
  }, [municipioId, rede, chave]);

  const cabecalho = (
    <div>
      <TituloTela>PDDE — dinheiro nas escolas</TituloTela>
      <p className="text-sm text-muted-foreground">
        O saldo parado na conta de cada escola e as escolas suspensas — a próxima parcela que não vem
      </p>
    </div>
  );

  if (!municipioId) return <Vazio>Escolha um município no seletor para ver o PDDE das escolas.</Vazio>;
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
    return <div className="space-y-4">{cabecalho}<Vazio>Não foi possível carregar o PDDE.</Vazio></div>;
  }
  if (!d.r.coletado) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <Vazio>
          O PDDE Info (FNDE) ainda não foi lido para este município. Isto não significa que as
          escolas não têm saldo nem suspensão — significa que ainda não conferimos.
        </Vazio>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {cabecalho}
      <Conteudo r={d.r} rede={rede} setRede={setRede} />
    </div>
  );
}

function Conteudo({ r, rede, setRede }: { r: Resp; rede: Rede; setRede: (x: Rede) => void }) {
  const t = r.totais!;
  const [aberta, setAberta] = useState<string | null>(null);
  const entidades = r.entidades || [];
  const eex = r.prefeitura_eex;
  const eexProblema = !!eex && (eex.suspensa || eex.situacoes.some((s) => !/^adimplente$/i.test(s)));

  return (
    <>
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        PDDE Info (FNDE) · saldo de <strong>{mesExtenso(r.mes_referencia)}</strong> (o mês mais novo
        que o FNDE publicou), lido em {dataHora(r.saldo_carregado_em)} · situação e suspensões de {r.ano},
        lidas em {dataHora(r.suspensao_carregada_em)}
        {r.liberacoes_fnde ? ` · recebido: liberações do FNDE de ${r.ano}${r.liberacoes_fnde.fechamento ? `, fechamento de ${dataCurta(r.liberacoes_fnde.fechamento)}` : ""}` : ""}
      </p>

      {eexProblema && (
        <Aviso tom="critico" icon={Ban} className="" titulo={
          `A prefeitura, como executora do PDDE (EEx), está ${eex!.suspensa ? "SUSPENSA" : eex!.situacoes.join(" / ")}`}>
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Ela responde por {eex!.escolas} escola(s) no PDDE de {r.ano}: enquanto isso não for
            regularizado, o repasse dessas escolas fica travado.
          </p>
        </Aviso>
      )}

      {t.escolas_suspensas > 0 && (
        <Aviso tom="critico" icon={AlertTriangle} className="" titulo={
          `${t.escolas_suspensas} escola(s) com pagamento SUSPENSO em ${r.ano} — a próxima parcela não sai`}>
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {(r.suspensoes_por_tipo || []).map((s) => (
              <li key={s.tipo}>{s.escolas} escola(s): {s.tipo}</li>
            ))}
          </ul>
        </Aviso>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Abas<Rede> valor={rede} onChange={setRede} opcoes={[
          { valor: "municipal", label: "Rede municipal" },
          { valor: "todas", label: "Todas as redes" },
        ]} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Numero icon={Wallet} tom="acento" rotulo={`Saldo nas contas em ${mesExtenso(r.mes_referencia)}`}
                valor={moeda(t.saldo)}
                sub={`${t.contas} conta(s) de ${t.entidades} executora(s) · conta, fundos, poupança e CDB`} />
        <Numero icon={PiggyBank} tom={t.entidades_paradas ? "atencao" : "neutro"}
                rotulo="Parado: saldo acima do previsto do ano" valor={moeda(t.saldo_parado)}
                sub={`${t.entidades_paradas} executora(s) com mais dinheiro em conta do que o PDDE prevê para ${r.ano} inteiro`} />
        <Numero icon={Ban} tom={t.escolas_suspensas ? "critico" : "ok"}
                rotulo={`Escolas suspensas em ${r.ano}`} valor={String(t.escolas_suspensas)}
                sub={`de ${t.escolas} escola(s) no PDDE · previsto no ano ${moeda(t.previsto_ano)}`} />
        <Numero icon={School} rotulo={`PDDE liberado pelo FNDE em ${r.ano}`} valor={moeda(t.recebido_ano)}
                sub={r.liberacoes_fnde == null
                  ? `as liberações do FNDE de ${r.ano} ainda não foram lidas para o município`
                  : t.recebido_ano == null
                    ? `nenhuma liberação de PDDE a estas executoras em ${r.ano}`
                    : `a ${t.entidades_com_liberacao} executora(s) — o mesmo dado da tela do SIMEC`} />
      </div>

      {r.outras_redes && r.outras_redes.entidades > 0 && (
        <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
          <Info className="mr-1 inline size-3.5 align-[-2px]" />
          Fora da conta: {moeda(r.outras_redes.saldo)} em {r.outras_redes.entidades} executora(s) de escola
          estadual ou particular{r.outras_redes.suspensas ? ` (${r.outras_redes.suspensas} com suspensão)` : ""}.
          Elas estão no município, mas não são da prefeitura — veja «Todas as redes».
        </p>
      )}

      {(r.sem_executora || []).length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={AlertTriangle} titulo="Escolas suspensas sem executora"
                     sub="o motivo é justamente não ter caixa escolar/EEx — o dinheiro não tem para onde ir" />
          <Lista className="mt-2">
            {r.sem_executora!.map((s, i) => (
              <ItemLinha key={`${s.escola_inep}|${s.destinacao}|${i}`}
                         titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                           <span>{s.escola_nome || s.escola_inep}</span>
                           <Selo tom="critico">{s.tipo}</Selo>
                         </span>}
                         meta={<>
                           {s.escola_inep && <span className="bi-id">INEP {s.escola_inep}</span>}
                           <span>· {s.destinacao || s.programa}</span>
                           <span>· rede {ROTULO_REDE[s.rede] || s.rede}</span>
                         </>} />
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={School} titulo="Por executora (caixa escolar, APM ou prefeitura)"
                   sub="suspensas primeiro, depois quem tem saldo acima do previsto do ano, depois o maior saldo · clique para ver contas, escolas e suspensões" />
        {entidades.length === 0 ? (
          <Vazio>Nenhuma executora {rede === "municipal" ? "da rede municipal" : ""} neste município.</Vazio>
        ) : (
          <Lista className="mt-2">
            {entidades.map((e) => {
              const ab = aberta === e.cnpj;
              return (
                <ItemLinha key={e.cnpj} onClick={() => setAberta(ab ? null : e.cnpj)} expandido={ab}
                           titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                             <span>{e.nome || cnpjFmt(e.cnpj)}</span>
                             {e.prefeitura && <Selo>prefeitura (EEx)</Selo>}
                             {e.suspensa && <Selo tom="critico">suspensa</Selo>}
                             {e.parado && <Selo tom="atencao">saldo acima do previsto do ano</Selo>}
                             {e.redes.filter((x) => x !== "municipal").map((x) => (
                               <Selo key={x}>rede {ROTULO_REDE[x] || x}</Selo>
                             ))}
                           </span>}
                           valor={moeda(e.saldo)}
                           meta={<>
                             <span className="bi-id">{cnpjFmt(e.cnpj)}</span>
                             <span>· previsto {r.ano}: {moeda(e.previsto_ano)}</span>
                             {e.saldo_6_meses_antes != null && <span>· 6 meses antes: {moeda(e.saldo_6_meses_antes)}</span>}
                             <span>· liberado {r.ano}: {e.recebido_ano == null ? (r.liberacoes_fnde ? "sem liberação de PDDE" : "—") : moeda(e.recebido_ano)}</span>
                             <span>· {e.escolas.length} escola(s)</span>
                           </>}>
                  {ab && <Detalhe e={e} />}
                </ItemLinha>
              );
            })}
          </Lista>
        )}
      </Bloco>
    </>
  );
}

function Detalhe({ e }: { e: Entidade }) {
  return (
    <div className="mt-3 space-y-3">
      <Campos cols={4} campos={[
        { rotulo: "Em conta corrente", valor: moeda(e.saldo_por_tipo.conta) },
        { rotulo: "Em fundos", valor: moeda(e.saldo_por_tipo.fundos) },
        { rotulo: "Em poupança", valor: moeda(e.saldo_por_tipo.poupanca) },
        { rotulo: "Em RDB/CDB", valor: moeda(e.saldo_por_tipo.rdb_cdb) },
      ]} />
      {e.suspensoes.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] font-semibold" style={{ color: "var(--bi-crit-ink)" }}>
            Suspensões ({e.suspensoes.length})
          </div>
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {e.suspensoes.map((s, i) => (
              <li key={i}>
                <strong>{s.tipo}</strong> · {s.escola_nome || s.escola_inep} · {s.destinacao || s.programa}
              </li>
            ))}
          </ul>
        </div>
      )}
      {e.escolas.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
            Escolas ({e.escolas.length}) e prestação de contas
          </div>
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {e.escolas.map((s) => (
              <li key={s.inep || s.nome || ""}>
                {s.nome} {s.inep && <span className="bi-id">· INEP {s.inep}</span>} · {s.programas.join(", ")}
                {" "}· previsto {moeda(s.previsto)} · PC da executora: {s.situacao_uex || "—"}
                {s.situacao_eex && s.eex ? ` · PC de ${s.eex}: ${s.situacao_eex}` : ""}
                {s.suspensa_pc ? " · SUSPENSA na PC" : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {e.contas.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
            Contas ({e.contas.length})
          </div>
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {e.contas.map((c) => (
              <li key={`${c.banco}|${c.agencia}|${c.conta}|${c.programa}`}>
                <span className="bi-id">{c.banco} · ag. {c.agencia} · c/c {c.conta}</span> · {c.programa} · {moeda(c.saldo)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
