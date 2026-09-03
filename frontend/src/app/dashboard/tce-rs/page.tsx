"use client";

/* TCE-RS — as remessas obrigatórias que refletem na habilitação.
 *
 * ⭐ POR QUE ISTO NÃO É "TELA DE TRIBUNAL", e sim de captação: o atraso na
 * remessa vira pendência no TCE, pendência vira irregularidade fiscal, e
 * irregularidade trava a habilitação para convênio — o CHE inclui certidões do
 * TCE entre suas exigências. A cadeia é invisível para quem olha só o
 * financeiro, e é onde o convênio morre antes de nascer.
 *
 * ⭐ ESTA TELA DEIXOU DE SER SÓ CURADORIA. O calendário de remessas continua
 * sendo conteúdo — é norma, não muda toda semana. Mas as LICITAÇÕES e os
 * CONTRATOS agora vêm do LicitaCon, pelos dados abertos do próprio Tribunal
 * (`ingestion/tce_rs.py`): em Nova Palma são 864 licitações e 1.201 contratos.
 *
 * As duas coisas convivem, e a tela diz qual é qual: o AvisoCurado fala do
 * calendário, e o bloco do LicitaCon traz dado coletado com data.
 *
 * ⚠️ E quando não há dado coletado, a tela NÃO conclui "o município não licita".
 * O TCE-RS recusa conexões de faixa de datacenter (403), então a ausência pode
 * ser bloqueio nosso, não silêncio da prefeitura — e afirmar o contrário seria
 * acusar o cliente de uma omissão que ele não cometeu.
 */

import React, { useCallback, useEffect, useState } from "react";
import { CalendarClock, ExternalLink, Gavel, Landmark, Loader2 } from "lucide-react";

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
  licitacon?: {
    coletado: boolean;
    atualizado_em?: string | null;
    licitacoes_por_ano?: Array<{ ano: number; total: number;
      valor_estimado?: number | null; valor_homologado?: number | null }>;
    contratos_por_ano?: Array<{ ano: number; total: number; valor?: number | null }>;
    contratos_vigentes?: Array<{ numero: string; objeto?: string | null;
      valor?: number | null; vigencia_ate?: string | null;
      contratado_documento?: string | null; link?: string | null }>;
  };
}

const money = (v?: number | null) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL",
                                                maximumFractionDigits: 0 });
const dia = (iso?: string | null) =>
  iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("pt-BR") : "—";

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

      {/* ---------------- LicitaCon: dado coletado, não curadoria ----------------
          Vem ANTES do calendário de propósito: é o que fala do município deste
          cliente, enquanto o calendário fala da norma. */}
      {d.licitacon?.coletado ? (
        <Bloco className="p-3">
          <BlocoHead
            icon={Gavel}
            titulo="Licitações e contratos do município"
            sub="dados abertos do LicitaCon / TCE-RS — coletado, não curado"
            right={d.licitacon.atualizado_em
              ? <Selo>{`atualizado em ${dia(d.licitacon.atualizado_em)}`}</Selo>
              : undefined}
          />

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="bi-title mb-1 text-[12px]">Licitações por ano</div>
              <Lista>
                {(d.licitacon.licitacoes_por_ano || []).map((a) => (
                  <li key={a.ano}
                      className="flex flex-wrap items-baseline justify-between gap-x-3 py-1">
                    <span className="text-[12px] tabular-nums"
                          style={{ color: "var(--bi-text)" }}>
                      {a.ano} · {a.total} certame(s)
                    </span>
                    {/* ⚠️ Estimado e homologado NÃO fecham, e isso é a verdade:
                        certame em andamento entra na contagem e não na soma do
                        homologado. Mostrar só um dos dois esconderia a economia
                        do certame — ou inventaria contratação que não houve. */}
                    <span className="text-[11px] tabular-nums"
                          style={{ color: "var(--bi-muted)" }}>
                      {money(a.valor_homologado)} homologado
                      <span style={{ color: "var(--bi-faint)" }}>
                        {" "}de {money(a.valor_estimado)} estimado
                      </span>
                    </span>
                  </li>
                ))}
              </Lista>
            </div>
            <div>
              <div className="bi-title mb-1 text-[12px]">Contratos por ano</div>
              <Lista>
                {(d.licitacon.contratos_por_ano || []).map((a) => (
                  <li key={a.ano}
                      className="flex flex-wrap items-baseline justify-between gap-x-3 py-1">
                    <span className="text-[12px] tabular-nums"
                          style={{ color: "var(--bi-text)" }}>
                      {a.ano} · {a.total} contrato(s)
                    </span>
                    <span className="text-[11px] tabular-nums"
                          style={{ color: "var(--bi-muted)" }}>
                      {money(a.valor)}
                    </span>
                  </li>
                ))}
              </Lista>
            </div>
          </div>

          {!!d.licitacon.contratos_vigentes?.length && (
            <div className="mt-3">
              <div className="bi-title mb-1 text-[12px]">
                Contratos vigentes — os próximos a vencer
              </div>
              <Lista>
                {d.licitacon.contratos_vigentes.map((c) => (
                  <li key={c.numero} className="py-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                        Contrato {c.numero}
                      </span>
                      <span className="text-[11px] tabular-nums"
                            style={{ color: "var(--bi-muted)" }}>
                        {money(c.valor)} · até {dia(c.vigencia_ate)}
                      </span>
                    </div>
                    {c.objeto && (
                      <div className="text-[11px] leading-snug"
                           style={{ color: "var(--bi-faint)" }}>
                        {c.objeto.slice(0, 140)}
                      </div>
                    )}
                  </li>
                ))}
              </Lista>
            </div>
          )}
        </Bloco>
      ) : (
        /* ⚠️ AUSÊNCIA DE COLETA NÃO É AUSÊNCIA DE LICITAÇÃO. O TCE-RS recusa
           conexões de faixa de datacenter; dizer "nenhuma licitação" aqui seria
           acusar a prefeitura de uma omissão que pode ser bloqueio nosso. */
        <Bloco className="p-3">
          <BlocoHead icon={Gavel} titulo="Licitações e contratos"
                     sub="ainda não coletados deste município" />
          <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            O LicitaCon publica as licitações e os contratos do município em dados
            abertos, e o PACTHA já sabe lê-los. Enquanto esta seção estiver vazia,
            <b> não conclua que não há licitações</b>: o Tribunal recusa conexões
            vindas de servidores de datacenter, e a liberação é o que falta — não
            o código. A consulta pública continua disponível no LicitaCon Cidadão,
            pelo link abaixo.
          </p>
        </Bloco>
      )}

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
