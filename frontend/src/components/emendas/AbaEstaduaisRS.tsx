"use client";

/* EMENDAS PARLAMENTARES ESTADUAIS (RS).
 *
 * ⭐⭐ A PRIMEIRA COISA QUE ESTA TELA DIZ NÃO É UM NÚMERO — é que no RS as
 * emendas estaduais NÃO SÃO IMPOSITIVAS. Não é preciosismo jurídico: em Minas o
 * PACTHA vende "controle do prazo constitucional da emenda impositiva", e
 * repetir esse discurso aqui levaria o cliente a cobrar do Estado um prazo que
 * não existe. Erro material com o cliente é pior que tela vazia.
 *
 * Por isso o alerta vem acima de tudo, e o que a tela oferece no lugar do
 * "prazo a cobrar" é o que de fato funciona sem impositividade: a JANELA da LDO
 * e o relacionamento com o gabinete.
 *
 * A execução das emendas do município ainda não é coletada — o Estado publica em
 * painel fechado. O AvisoCurado diz isso antes de qualquer coisa.
 */

import React, { useCallback, useEffect, useState } from "react";
import { AlertOctagon, ExternalLink, Info, Loader2, Vote } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { AvisoCurado } from "@/components/rs/AvisoCurado";
import { Bloco, BlocoHead, ItemLinha, Lista, Vazio } from "@/components/ui/superficies";

interface Resp {
  tem_dados: boolean;
  motivo?: string;
  aviso?: string;
  titulo?: string;
  alerta_impositividade?: string;
  resumo?: string;
  numeros?: [string, string][];
  numeros_data?: string;
  atencao?: string;
  o_que_fazer?: string[];
  links?: [string, string][];
}

export default function EmendasRsPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get("/rs/emendas", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId]);
  useEffect(carregar, [carregar]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;

  return (
    <div className="space-y-4">
      <div>
        {/* h2: isto é uma ABA de «Emendas parlamentares» desde 17/09/2026. */}
        <h2 className="text-[15px] font-semibold">{d.titulo}</h2>
        <p className="text-sm text-muted-foreground">
          55 deputados estaduais · regras definidas ano a ano na LDO
        </p>
      </div>

      {/* ⭐ ACIMA DE TUDO. Ver o cabeçalho deste arquivo. */}
      <div
        className="border p-3"
        style={{
          borderRadius: "var(--bi-radius-sm)",
          borderColor: "color-mix(in oklab, var(--bi-crit) 40%, transparent)",
          background: "color-mix(in oklab, var(--bi-crit) 8%, transparent)",
        }}
      >
        <div className="flex items-start gap-2">
          <AlertOctagon className="mt-[2px] size-4 shrink-0" style={{ color: "var(--bi-crit-ink)" }} />
          <div className="min-w-0 text-[11px] leading-relaxed" style={{ color: "var(--bi-text)" }}>
            <div className="text-[12px] font-semibold">
              No RS a emenda estadual não é impositiva
            </div>
            <div className="mt-1" style={{ color: "var(--bi-muted)" }}>
              {d.alerta_impositividade}
            </div>
          </div>
        </div>
      </div>

      <AvisoCurado>{d.aviso}</AvisoCurado>

      <Bloco className="p-3">
        <BlocoHead icon={Vote} titulo="Como funciona" sub={d.resumo} />
        <Lista>
          {(d.numeros || []).map(([rotulo, valor]) => (
            <ItemLinha key={rotulo} titulo={rotulo} valor={valor} />
          ))}
        </Lista>
        <p className="mt-2 px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
          {d.numeros_data}
        </p>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Info} titulo="Atenção — não confundir com as emendas Pix" />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.atencao}
        </p>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Vote} titulo="O que fazer, então"
                   sub="sem prazo a cobrar, o que resta é chegar antes" />
        <Lista>
          {(d.o_que_fazer || []).map((t, i) => (
            <ItemLinha key={i} titulo={t} />
          ))}
        </Lista>
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
