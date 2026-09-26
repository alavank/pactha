"use client";

/* ASSISTÊNCIA SOCIAL — ESTADO (FEAS). O cofinanciamento ESTADUAL do SUAS: o que o
 * Fundo Estadual de Assistência Social pagou ao município — ao fundo municipal
 * (Piso Mineiro em MG, Piso Gaúcho no RS) ou à prefeitura (emendas e programas do
 * FEAS) —, OB a OB, da despesa aberta do Estado.
 *
 *   - MG: o Piso Mineiro é MENSAL; ação de piso sem pagamento há mais de 60 dias é
 *     o repasse regular que parou de vir (aviso);
 *   - RS: o Estado paga pouco e irregular — a tela mostra até que mês a fonte chega,
 *     para "nenhum pagamento" nunca parecer "não conferimos".
 *
 * ⚠️ A CONTA É DO BACKEND (`services/feas.py::montar`). Esta tela só desenha.
 * O federal (FNAS: saldo das contas, repasses, emendas) é a tela irmã.
 */

import React, { useEffect, useState } from "react";
import { AlertTriangle, Info, Landmark, Loader2, Wallet } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Aviso, Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import { formatCurrency } from "@/lib/utils";

interface Acao {
  acao: string;
  ano: number;
  ano_anterior: number;
  ultimo: string | null;
  dias_desde_ultimo: number | null;
  pagamentos: number;
  destinos: string[];
  atrasado: boolean;
}
interface Pagamento {
  data: string | null;
  ano: number;
  documento: string | null;
  acao: string | null;
  valor: number;
  destino: "fundo" | "prefeitura";
  favorecido: string | null;
  modalidade: string | null;
}
interface Resp {
  cobertura: boolean;
  coletado?: boolean;
  uf: string;
  ano?: number;
  lido_em?: string;
  publicado_ate?: string | null;
  totais?: {
    ano: number; ano_anterior: number; fundo_ano: number; prefeitura_ano: number;
    pagamentos: number; ultimo: string | null;
  };
  acoes?: Acao[];
  atrasadas?: string[];
  pagamentos?: Pagamento[];
}

const moeda = (v: number | null | undefined) => (v == null ? "—" : formatCurrency(v));
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
const FONTE: Record<string, string> = {
  MG: "despesa aberta de MG (dados.mg.gov.br, CGE) — unidade SEDESE/FEAS/SUBAS",
  RS: "despesa aberta do RS (dados.rs.gov.br, CAGE) — UO 2178, Fundo Estadual de Assistência Social",
};

export default function FeasPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<{ chave: string; r: Resp | null; erro: boolean } | null>(null);
  const chave = String(municipioId);

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api.get<Resp>("/feas", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setD({ chave, r: r.data, erro: false }); })
      .catch(() => { if (vivo) setD({ chave, r: null, erro: true }); });
    return () => { vivo = false; };
  }, [municipioId, chave]);

  const cabecalho = (
    <div>
      <TituloTela>Assistência social — Estado (FEAS)</TituloTela>
      <p className="text-sm text-muted-foreground">
        O que o fundo estadual de assistência social pagou ao município: pisos, programas e emendas, OB a OB
      </p>
    </div>
  );

  if (!municipioId) return <Vazio>Escolha um município no seletor para ver o cofinanciamento estadual.</Vazio>;
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
    return <div className="space-y-4">{cabecalho}<Vazio>Não foi possível carregar o FEAS.</Vazio></div>;
  }
  const r = d.r;
  if (!r.cobertura) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <Vazio>
          O cofinanciamento estadual da assistência social está coberto para MG e RS. Para {r.uf || "este Estado"},
          a fonte ainda não foi ligada no PACTHA.
        </Vazio>
      </div>
    );
  }
  if (!r.coletado || !r.totais) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <Vazio>
          A despesa do Estado ainda não foi lida. Isto não significa que o município não recebeu — significa
          que ainda não conferimos.
        </Vazio>
      </div>
    );
  }
  return (
    <div className="space-y-4">
      {cabecalho}
      <Conteudo r={r} />
    </div>
  );
}

function Conteudo({ r }: { r: Resp }) {
  const t = r.totais!;
  const [aberta, setAberta] = useState<string | null>(null);
  const acoes = r.acoes || [];
  const pagamentos = r.pagamentos || [];

  return (
    <>
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        {FONTE[r.uf] || r.uf}
        {r.publicado_ate ? ` · o Estado publicou até ${r.publicado_ate}` : ""} · lido em {dataHora(r.lido_em)}
      </p>

      {(r.atrasadas || []).length > 0 && (
        <Aviso tom="atencao" icon={AlertTriangle} className="" titulo="Repasse regular sem pagamento há mais de 60 dias">
          <ul className="space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {acoes.filter((a) => a.atrasado).map((a) => (
              <li key={a.acao}>{a.acao} · último pagamento em {dataCurta(a.ultimo)} ({a.dias_desde_ultimo} dias)</li>
            ))}
          </ul>
        </Aviso>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Numero icon={Wallet} tom="acento" rotulo={`Pago pelo FEAS em ${r.ano}`} valor={moeda(t.ano)}
                sub={`${moeda(t.fundo_ano)} ao fundo municipal · ${moeda(t.prefeitura_ano)} à prefeitura`} />
        <Numero icon={Landmark} rotulo={`Pago em ${(r.ano ?? 0) - 1}`} valor={moeda(t.ano_anterior)}
                sub="o ano inteiro, para comparar" />
        <Numero icon={Landmark} rotulo="Último pagamento" valor={dataCurta(t.ultimo)}
                sub={`${t.pagamentos} pagamento(s) em ${(r.ano ?? 0) - 1}–${r.ano}`} />
        <Numero icon={Info} rotulo="Ações do FEAS" valor={String(acoes.length)}
                sub={acoes.length ? "pisos, programas e emendas" : "nenhuma no período"} />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={Landmark} titulo="Por ação do FEAS"
                   sub="o que foi pago no ano e no anterior · clique para ver os pagamentos" />
        {acoes.length === 0 ? (
          <Vazio>
            Nenhum pagamento do FEAS a este município em {(r.ano ?? 0) - 1}–{r.ano}
            {r.publicado_ate ? ` (a fonte chega até ${r.publicado_ate})` : ""}.
          </Vazio>
        ) : (
          <Lista className="mt-2">
            {acoes.map((a) => {
              const ab = aberta === a.acao;
              const deles = pagamentos.filter((p) => (p.acao || "(sem ação)") === a.acao);
              return (
                <ItemLinha key={a.acao} onClick={() => setAberta(ab ? null : a.acao)} expandido={ab}
                           titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                             <span>{a.acao}</span>
                             {a.atrasado && <Selo tom="atencao">sem pagamento há {a.dias_desde_ultimo} dias</Selo>}
                             {a.destinos.map((x) => <Selo key={x}>{x === "fundo" ? "ao fundo municipal" : "à prefeitura"}</Selo>)}
                           </span>}
                           valor={moeda(a.ano)}
                           meta={<>
                             <span>{(r.ano ?? 0) - 1}: {moeda(a.ano_anterior)}</span>
                             <span>· último: {dataCurta(a.ultimo)}</span>
                             <span>· {a.pagamentos} pagamento(s)</span>
                           </>}>
                  {ab && (
                    <ul className="mt-2 space-y-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                      {deles.map((p, i) => (
                        <li key={`${p.documento}|${i}`}>
                          {dataCurta(p.data)} · {p.documento ? `nº ${p.documento}` : "sem nº"} · {moeda(p.valor)} ·{" "}
                          {p.destino === "fundo" ? "fundo municipal" : "prefeitura"}
                          {p.favorecido ? ` (${p.favorecido})` : ""}
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
    </>
  );
}
