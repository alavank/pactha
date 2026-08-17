"use client";

/* PLANO RIO GRANDE / FUNRIGS — a reconstrução pós-enchentes de 2024.
 *
 * Hoje é a maior fonte de demanda de captação e prestação de contas das
 * prefeituras gaúchas. O portal do Estado publica só normativos e um formulário
 * em branco, e o painel de execução é fechado — então esta tela entrega o que
 * dá: as exigências do fundo a fundo, que é a parte acionável.
 *
 * ⭐ E ela tem UM CAMPO VIVO, que não é conteúdo: a data-limite da calamidade.
 * Ela muda o comportamento do sistema — com ela cadastrada, o alarme do Decreto
 * 56.939 usa o prazo excepcional de 120 dias em vez do dia 15. Mostrar aqui se
 * está cadastrada é a diferença entre o gestor saber que está protegido e ser
 * cobrado por um atraso que a norma lhe perdoou.
 */

import React, { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Circle, Clock, Loader2, ExternalLink, ShieldAlert } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { AvisoCurado } from "@/components/rs/AvisoCurado";
import { Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { formatDate } from "@/lib/utils";

interface Resp {
  tem_dados: boolean;
  motivo?: string;
  aviso?: string;
  titulo?: string;
  subtitulo?: string;
  resumo?: string;
  exigencias?: { item: string; detalhe: string }[];
  excecao_120_dias?: string;
  numeros?: string;
  links?: [string, string][];
  municipio?: {
    calamidade_ate: string | null;
    fundo_reconstrucao: boolean | null;
    fundo_reconstrucao_obs: string | null;
  };
}

export default function FunrigsPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get("/rs/funrigs", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId]);
  useEffect(carregar, [carregar]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;

  const m = d.municipio;
  const temCalamidade = !!m?.calamidade_ate;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">{d.titulo}</h1>
        <p className="text-sm text-muted-foreground">{d.subtitulo}</p>
      </div>

      <AvisoCurado>{d.aviso}</AvisoCurado>

      {/* O bloco do município vem antes do conteúdo geral: é o que fala DELE. */}
      <Bloco className="p-3">
        <BlocoHead icon={ShieldAlert} titulo="Situação deste município"
                   sub="o que está cadastrado no PACTHA e muda o comportamento dos alertas" />
        <Lista>
          <ItemLinha
            titulo={
              <span className="flex flex-wrap items-center gap-x-2">
                <span>Prazo excepcional de calamidade</span>
                <Selo tom={temCalamidade ? "ok" : "atencao"}>
                  {temCalamidade ? `até ${formatDate(m!.calamidade_ate!)}` : "não cadastrado"}
                </Selo>
              </span>
            }
            meta={
              temCalamidade
                ? "O alarme do monitoramento mensal usa 120 dias em vez do dia 15 enquanto este prazo valer."
                : "Sem esta data, o monitoramento mensal é cobrado pelo prazo padrão (dia 15). Se o município está em calamidade reconhecida, cadastre a data para não receber alerta indevido."
            }
          />
          <ItemLinha
            titulo={
              <span className="flex flex-wrap items-center gap-x-2">
                <span>Fundo Municipal de Reconstrução</span>
                <Selo tom={m?.fundo_reconstrucao ? "ok" : undefined}>
                  {m?.fundo_reconstrucao === true ? "cadastrado"
                    : m?.fundo_reconstrucao === false ? "não possui" : "não informado"}
                </Selo>
              </span>
            }
            meta={m?.fundo_reconstrucao_obs || "Exigência do fundo a fundo: conselho gestor constituído e conta bancária específica."}
          />
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={CheckCircle2} titulo="O que o fundo a fundo exige"
                   sub={d.resumo} />
        <Lista>
          {(d.exigencias || []).map((e) => (
            <ItemLinha key={e.item} titulo={e.item} meta={e.detalhe} />
          ))}
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Clock} titulo="Prazo excepcional de 120 dias" />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.excecao_120_dias}
        </p>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Circle} titulo="Números do fundo" />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.numeros}
        </p>
        <div className="mt-2 flex flex-wrap gap-3 px-1">
          {(d.links || []).map(([rotulo, url]) => (
            <a key={url} href={url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-[11px] underline"
               style={{ color: "var(--bi-accent-ink)" }}>
              {rotulo} <ExternalLink className="size-3" />
            </a>
          ))}
        </div>
      </Bloco>
    </div>
  );
}
