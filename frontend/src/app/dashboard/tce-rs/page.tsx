"use client";

/* TCE-RS — as remessas obrigatórias que refletem na habilitação.
 *
 * ⭐ POR QUE ISTO NÃO É "TELA DE TRIBUNAL", e sim de captação: o atraso na
 * remessa vira pendência no TCE, pendência vira irregularidade fiscal, e
 * irregularidade trava a habilitação para convênio — o CHE inclui certidões do
 * TCE entre suas exigências. A cadeia é invisível para quem olha só o
 * financeiro, e é onde o convênio morre antes de nascer.
 *
 * O dado é aberto, mas o TCE recusa conexões do nosso servidor (bloqueio por
 * faixa de datacenter). Então a tela entrega o que não depende disso: quais são
 * os sistemas, com que periodicidade, e por que importam. O AvisoCurado diz, com
 * todas as letras, que a conferência do SEU envio ainda não é automática.
 */

import React, { useCallback, useEffect, useState } from "react";
import { CalendarClock, ExternalLink, Landmark, Loader2 } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { AvisoCurado } from "@/components/rs/AvisoCurado";
import { Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";

interface Sistema {
  nome: string; o_que: string; periodicidade: string; prazo: string;
}
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  aviso?: string;
  titulo?: string;
  subtitulo?: string;
  sistemas?: Sistema[];
  por_que_importa?: string;
  codigo_orgao?: string;
  links?: [string, string][];
  municipio?: { tce_orgao_codigo: string | null };
}

export default function TceRsPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get("/rs/tce", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId]);
  useEffect(carregar, [carregar]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;

  const codigo = d.municipio?.tce_orgao_codigo;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">{d.titulo}</h1>
        <p className="text-sm text-muted-foreground">{d.subtitulo}</p>
      </div>

      <AvisoCurado>{d.aviso}</AvisoCurado>

      <Bloco className="p-3">
        <BlocoHead icon={CalendarClock} titulo="Sistemas e periodicidade" />
        <Lista>
          {(d.sistemas || []).map((s) => (
            <ItemLinha
              key={s.nome}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2">
                  <span>{s.nome}</span>
                  <Selo>{s.periodicidade}</Selo>
                </span>
              }
              meta={s.o_que}
            >
              <div className="mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                <span className="font-semibold" style={{ color: "var(--bi-text)" }}>Prazo: </span>
                {s.prazo}
              </div>
            </ItemLinha>
          ))}
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Landmark} titulo="Por que isso aparece num sistema de convênios" />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.por_que_importa}
        </p>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead
          icon={Landmark}
          titulo="Código do órgão no TCE-RS"
          sub={codigo ? `Cadastrado neste município: ${codigo}` : "Ainda não cadastrado neste município"}
        />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.codigo_orgao}
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
