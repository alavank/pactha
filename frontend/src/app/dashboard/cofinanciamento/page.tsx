"use client";

/* COFINANCIAMENTO ESTADUAL DA SAÚDE.
 *
 * ⚠️ O QUE ESTA TELA EXISTE PARA MOSTRAR NÃO É O TOTAL — é a DIFERENÇA.
 * Na Atenção Primária o Estado define um TETO por quadrimestre e paga uma
 * fração dele conforme o ISF (indicador sintético). A diferença é dinheiro que
 * o município deixa de receber por desempenho — e que ele PODE reverter. Um
 * painel que mostrasse só "recebido" esconderia exatamente a informação útil.
 * Na Vigilância, o mesmo raciocínio na parcela com pagamento não liberado.
 */

import React, { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { cofinanciamentoDaUf } from "@/lib/estadual";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { HeartPulse, TrendingDown, Lock, Loader2 } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";
import { TituloTela } from "@/components/TituloTela";

interface ItemAP {
  competencia: string | null;
  valor_teto: number | null;
  valor: number | null;
  perdido: number | null;
  perc_receber: number | null;
  indicador: number | null;
  fechado: boolean | null;
  ano: number | null;
}
interface ItemVG {
  competencia: string | null;
  programa: string | null;
  valor: number | null;
  liberado: boolean | null;
  data_ref: string | null;
  ano: number | null;
}
interface Resp {
  tem_dados: boolean;
  fonte: string | null;
  primaria: { itens: ItemAP[]; perdido_total: number; teto_total: number };
  vigilancia: {
    itens: ItemVG[]; travadas: number; travado_total: number; liberado_total: number;
  };
}

export default function CofinanciamentoPage() {
  const { municipioId } = useMunicipio();
  const uf = useUfDoMunicipio();
  const info = cofinanciamentoDaUf(uf);

  const [data, setData] = useState<Resp | null>(null);
  const [carimbo, setCarimbo] = useState("");
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    const meu = String(municipioId);
    setLoading(true);
    api.get<Resp>("/cofinanciamento", { params: { municipio_id: municipioId } })
      .then((r) => { setData(r.data); setCarimbo(meu); })
      .catch(() => { setData(null); setCarimbo(meu); })
      .finally(() => setLoading(false));
  }, [municipioId]);

  /* Microtask: `carregar` começa com setState, e síncrono dentro de effect
     dispara render em cascata (o lint barra, com razão). */
  useEffect(() => {
    let vivo = true;
    Promise.resolve().then(() => { if (vivo) carregar(); });
    return () => { vivo = false; };
  }, [carregar]);

  if (!municipioId) return <Vazio>Selecione um município.</Vazio>;

  if (uf && !info) {
    return (
      <div className="rounded-lg border p-6 text-sm"
           style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}>
        Esta tela mostra o <b>cofinanciamento estadual da saúde</b> dos estados que
        publicam o repasse ao fundo municipal. O estado deste município ainda não
        é acompanhado por este sistema.
      </div>
    );
  }

  const doMun = carimbo === String(municipioId);
  const d = doMun ? data : null;

  if (loading && !doMun) {
    return <div className="flex justify-center py-14"><Loader2 className="size-6 animate-spin" /></div>;
  }
  if (!d?.tem_dados) {
    return <Vazio>Nenhum dado de cofinanciamento estadual coletado para este município.</Vazio>;
  }

  const ap = d.primaria;
  const vg = d.vigilancia;

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>{info?.titulo || "Cofinanciamento da Saúde"}</TituloTela>
        <p className="text-sm text-muted-foreground">{info?.fonte || d.fonte}</p>
      </div>

      {/* ⭐ OS DOIS NÚMEROS QUE IMPORTAM vêm primeiro, e são os DOIS que o
          gestor pode agir sobre. O "recebido" é consequência, não meta. */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Numero icon={TrendingDown} rotulo="Deixou de receber" tom="atencao"
                valor={formatCurrency(ap.perdido_total)}
                sub="diferença entre o teto e o pago, por desempenho (ISF)" />
        <Numero icon={Lock} rotulo="Parcela não liberada" tom="critico"
                valor={formatCurrency(vg.travado_total)}
                sub={`${vg.travadas} parcela(s) da Vigilância`} />
        <Numero icon={HeartPulse} rotulo="Teto da Atenção Primária"
                valor={formatCurrency(ap.teto_total)}
                sub={`${ap.itens.length} quadrimestre(s)`} />
      </div>

      {ap.itens.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={HeartPulse} titulo="Atenção Primária"
                     sub="Teto pactuado, percentual liberado pelo ISF e o que sobrou no caminho" />
          <Lista>
            {ap.itens.map((i, n) => (
              <ItemLinha
                key={n}
                titulo={
                  <span className="flex flex-wrap items-center gap-x-2">
                    <span>{i.competencia || "—"}</span>
                    {i.fechado === false && <Selo>quadrimestre aberto</Selo>}
                  </span>
                }
                valor={formatCurrency(i.valor ?? 0)}
                meta={
                  <>
                    teto {formatCurrency(i.valor_teto ?? 0)}
                    {i.perc_receber != null ? ` · ${i.perc_receber}% liberado` : ""}
                    {i.indicador != null ? ` · ISF ${i.indicador}` : ""}
                  </>
                }
              >
                {(i.perdido ?? 0) > 0 && (
                  <Campos
                    cols={2}
                    campos={[
                      { rotulo: "Deixou de receber", tom: "atencao",
                        valor: formatCurrency(i.perdido ?? 0) },
                      { rotulo: "Motivo",
                        valor: `ISF ${i.indicador ?? "—"} liberou ${i.perc_receber ?? "—"}% do teto` },
                    ]}
                  />
                )}
              </ItemLinha>
            ))}
          </Lista>
        </Bloco>
      )}

      {vg.itens.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={Lock} titulo="Vigilância em Saúde"
                     sub="Parcelas por programa — as não liberadas vêm primeiro" />
          <Lista>
            {vg.itens.slice(0, 60).map((i, n) => (
              <ItemLinha
                key={n}
                titulo={
                  <span className="flex flex-wrap items-center gap-x-2">
                    <span>{i.programa || "—"}</span>
                    {i.liberado === false && <Selo tom="critico">não liberado</Selo>}
                  </span>
                }
                valor={formatCurrency(i.valor ?? 0)}
                meta={
                  <>
                    {i.competencia || ""}
                    {i.data_ref ? ` · ${formatDate(i.data_ref)}` : ""}
                  </>
                }
              />
            ))}
          </Lista>
          {vg.itens.length > 60 && (
            <p className="pt-2 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Mostrando 60 de {vg.itens.length} parcelas — as não liberadas estão todas aqui.
            </p>
          )}
        </Bloco>
      )}
    </div>
  );
}
