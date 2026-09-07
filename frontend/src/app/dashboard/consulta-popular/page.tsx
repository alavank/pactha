"use client";

/* CONSULTA POPULAR / COREDEs — o mecanismo de participação que só existe no RS.
 *
 * ⭐ O QUE ESTA TELA EXISTE PARA MOSTRAR NÃO É O QUE A REGIÃO GANHOU — é o que
 * o MUNICÍPIO deixou de alcançar. Em 2026/2027 o COREDE Central elegeu duas
 * demandas (R$ 2,23 milhões) e Santa Maria ficou DESCLASSIFICADA nas duas, com
 * 153 e 141 votos: ficou de fora de um recurso da própria região por falta de
 * mobilização. Um painel que listasse só as demandas eleitas esconderia
 * exatamente a informação que muda comportamento no ano seguinte — e que não
 * aparece em nenhum sistema financeiro da prefeitura.
 *
 * Mesma doutrina da tela de Cofinanciamento: o número que vem primeiro é o que
 * o gestor PODE reverter, não o total.
 */

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Loader2, Users, Vote } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { consultaPopularDaUf } from "@/lib/estadual";
import { Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { formatCurrency, formatDate } from "@/lib/utils";
import { TituloTela } from "@/components/TituloTela";

interface Item {
  edicao: string;
  ordem: string;
  demanda: string | null;
  orgao: string | null;
  votos_corede: number | null;
  valor: number | null;
  votos_municipio: number | null;
  status_municipio: string | null;
  perdeu: boolean;
}
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  corede?: string;
  edicao?: string;
  atualizado_em?: string | null;
  itens?: Item[];
  resumo?: {
    demandas_eleitas: number;
    valor_regiao: number;
    desclassificadas: number;
    valor_fora_do_alcance: number;
    votos_do_municipio: number;
  };
}

export default function ConsultaPopularPage() {
  const { municipioId } = useMunicipio();
  const uf = useUfDoMunicipio();
  const info = consultaPopularDaUf(uf);

  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api
      .get("/consulta-popular", { params: { municipio_id: municipioId } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [municipioId]);

  useEffect(carregar, [carregar]);

  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> carregando…
      </div>
    );
  }
  if (!data?.tem_dados) {
    return <Vazio>{data?.motivo || "Nenhum resultado da Consulta Popular coletado para este município."}</Vazio>;
  }

  const r = data.resumo!;
  const itens = (data.itens || []).filter((i) => i.edicao === data.edicao);

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>{info?.titulo || "Consulta Popular"}</TituloTela>
        <p className="text-sm text-muted-foreground">
          COREDE {data.corede} · edição {data.edicao}
          {data.atualizado_em ? ` · atualizado em ${formatDate(data.atualizado_em)}` : ""}
        </p>
      </div>

      {/* ⭐ O PRIMEIRO NÚMERO É A PERDA, e é deliberado: o valor que a região
          conquistou é consequência da votação de todo mundo; o que este
          município deixou escapar é o que ele pode mudar no ano que vem. */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Numero
          icon={AlertTriangle}
          rotulo="Fora do alcance"
          tom={r.desclassificadas ? "atencao" : undefined}
          valor={formatCurrency(r.valor_fora_do_alcance)}
          sub={
            r.desclassificadas
              ? `${r.desclassificadas} demanda(s) em que o município não se classificou`
              : "o município se classificou em todas"
          }
        />
        <Numero
          icon={Vote}
          rotulo="Eleito na região"
          valor={formatCurrency(r.valor_regiao)}
          sub={`${r.demandas_eleitas} demanda(s) eleita(s) no COREDE`}
        />
        <Numero
          icon={Users}
          rotulo="Votos do município"
          valor={String(r.votos_do_municipio)}
          sub="somados nas demandas eleitas"
        />
      </div>

      <Bloco className="p-3">
        <BlocoHead
          icon={Vote}
          titulo="Demandas eleitas no COREDE"
          sub="O que a região aprovou, e como este município votou em cada uma"
        />
        <Lista>
          {itens.map((i) => (
            <ItemLinha
              key={`${i.edicao}-${i.ordem}`}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2">
                  <span>{i.demanda || `Demanda ${i.ordem}`}</span>
                  {/* O selo é o ponto da tela: diz, item a item, se este
                      município entrou ou ficou de fora. */}
                  {i.status_municipio && (
                    <Selo tom={i.perdeu ? "atencao" : undefined}>
                      {i.status_municipio}
                    </Selo>
                  )}
                </span>
              }
              valor={formatCurrency(i.valor ?? 0)}
              meta={
                <>
                  {i.orgao || "—"}
                  {i.votos_corede != null ? ` · ${i.votos_corede} votos na região` : ""}
                  {i.votos_municipio != null ? ` · ${i.votos_municipio} deste município` : ""}
                </>
              }
            />
          ))}
        </Lista>
      </Bloco>

      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        A Consulta Popular é anual e por COREDE: a população vota quais projetos entram no
        orçamento do Estado, e os mais votados viram convênio com os municípios. Município
        desclassificado não participa do recurso daquela demanda.
      </p>
    </div>
  );
}
