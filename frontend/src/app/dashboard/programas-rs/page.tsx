"use client";

/* PROGRAMAS DO ESTADO (RS) — o catálogo de captação.
 *
 * ⭐ ESTA TELA EXISTE PARA MOSTRAR O QUE O GESTOR NÃO SABIA QUE EXISTIA. Nenhum
 * desses programas publica dado estruturado por município — são páginas
 * institucionais e editais em PDF. A tentação seria deixá-los de fora até haver
 * coletor, e essa é a decisão errada: um painel de captação vale justamente por
 * abrir portas que o município não conhecia. Ver `docs/MAPA_RS.md` §13.
 *
 * ⚠️ E POR ISSO O AVISO VEM PRIMEIRO, antes de qualquer programa. Catálogo
 * estático apresentado sem ressalva se passa por monitoramento, e o gestor
 * confiaria que seria avisado de uma abertura de edital que ninguém está
 * vigiando. Meia verdade apresentada como verdade inteira é pior que ausência.
 */

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ExternalLink, Landmark, Loader2 } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Bloco, BlocoHead, Lista, ItemLinha, Selo, Vazio } from "@/components/ui/superficies";

interface Programa {
  chave: string;
  nome: string;
  orgao: string;
  resumo: string;
  exigencias: string[];
  como: string;
  url: string;
  numeros: string;
  observacao: string;
}
interface Area { chave: string; titulo: string; programas: Programa[] }
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  aviso?: string;
  areas?: Area[];
  normas?: { norma: string; sobre: string }[];
}

export default function ProgramasRsPage() {
  const { municipioId } = useMunicipio();
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api
      .get("/programas-rs", { params: { municipio_id: municipioId } })
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
    return <Vazio>{data?.motivo || "Catálogo indisponível."}</Vazio>;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">Programas do Estado</h1>
        <p className="text-sm text-muted-foreground">
          As linhas de fomento do Governo do RS pelas quais o município pode captar
        </p>
      </div>

      {/* O aviso vem ANTES do conteúdo — ver o cabeçalho deste arquivo. */}
      <div
        className="border p-2.5"
        style={{
          borderRadius: "var(--bi-radius-sm)",
          borderColor: "color-mix(in oklab, var(--bi-warn) 35%, transparent)",
          background: "color-mix(in oklab, var(--bi-warn) 8%, transparent)",
        }}
      >
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-[2px] size-3.5 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
          <div className="min-w-0 text-[10px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            <div className="text-[11px] font-semibold" style={{ color: "var(--bi-text)" }}>
              Catálogo curado — a abertura de editais não é monitorada automaticamente
            </div>
            <div className="mt-0.5">{data.aviso}</div>
          </div>
        </div>
      </div>

      {(data.areas || []).map((a) => (
        <Bloco key={a.chave} className="p-3">
          <BlocoHead icon={Landmark} titulo={a.titulo}
                     sub={`${a.programas.length} programa(s)`} />
          <Lista>
            {a.programas.map((p) => (
              <ItemLinha
                key={p.chave}
                titulo={
                  <span className="flex flex-wrap items-center gap-x-2">
                    <span>{p.nome}</span>
                    <Selo>{p.orgao}</Selo>
                  </span>
                }
                meta={p.resumo}
              >
                <div className="mt-1 space-y-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                  {p.exigencias.length > 0 && (
                    <div>
                      <span className="font-semibold" style={{ color: "var(--bi-text)" }}>
                        O que exige:{" "}
                      </span>
                      {p.exigencias.join(" · ")}
                    </div>
                  )}
                  {p.como && (
                    <div>
                      <span className="font-semibold" style={{ color: "var(--bi-text)" }}>
                        Como se candidatar:{" "}
                      </span>
                      {p.como}
                    </div>
                  )}
                  {/* Os números carregam a data em que foram lidos, de propósito:
                      valor sem data envelhece em silêncio e vira erro na tela. */}
                  {p.numeros && <div style={{ color: "var(--bi-faint)" }}>{p.numeros}</div>}
                  {p.observacao && <div style={{ color: "var(--bi-faint)" }}>{p.observacao}</div>}
                  {p.url && (
                    <a
                      href={p.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 underline"
                      style={{ color: "var(--bi-accent-ink)" }}
                    >
                      página oficial <ExternalLink className="size-3" />
                    </a>
                  )}
                </div>
              </ItemLinha>
            ))}
          </Lista>
        </Bloco>
      ))}

      {(data.normas || []).length > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={Landmark} titulo="Base normativa"
                     sub="o que o jurídico costuma pedir junto da proposta" />
          <Lista>
            {(data.normas || []).map((n) => (
              <ItemLinha key={n.norma} titulo={n.norma} meta={n.sobre} />
            ))}
          </Lista>
        </Bloco>
      )}
    </div>
  );
}
