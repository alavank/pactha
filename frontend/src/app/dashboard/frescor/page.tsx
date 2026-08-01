"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Activity, RefreshCw, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { Campos, ItemLinha, Lista, Selo } from "@/components/ui/superficies";
import { Button } from "@/components/ui/button";

interface Fonte {
  fonte: string;
  ultimo_dado: string | null;
  ultima_coleta: string | null;
  referencia: string | null;
  idade_dias: number | null;
  registros: number | null;
  status: "fresco" | "atrasado" | "critico" | "desconhecido";
}

const STATUS_TOM: Record<string, { tom: "neutro" | "ok" | "atencao" | "critico"; label: string }> = {
  // "Fresco" e o estado NORMAL de quase toda fonte — vira cinza. Numa tela em
  // que 15 de 17 linhas estavam verdes, o verde nao dizia nada e as duas que
  // importavam disputavam atencao com ele.
  fresco: { tom: "neutro", label: "Fresco" },
  atrasado: { tom: "atencao", label: "Atrasado" },
  critico: { tom: "critico", label: "Crítico" },
  desconhecido: { tom: "neutro", label: "Sem informação" },
};

function fmtDt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtIdade(d: number | null): string {
  if (d == null) return "—";
  if (d < 1) return "hoje";
  if (d < 2) return "1 dia";
  return `${Math.round(d)} dias`;
}

export default function FrescorPage() {
  const [fontes, setFontes] = useState<Fonte[]>([]);
  const [loading, setLoading] = useState(true);
  const [geradoEm, setGeradoEm] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<{ gerado_em: string; fontes: Fonte[] }>("/admin/freshness");
      setFontes(r.data.fontes || []);
      setGeradoEm(r.data.gerado_em);
      setErro(null);
    } catch (e: unknown) {
      setErro((e as { response?: { status?: number } })?.response?.status === 403
        ? "Apenas administradores acessam esta tela."
        : "Erro ao carregar o frescor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  const criticos = fontes.filter((f) => f.status === "critico").length;
  const atrasados = fontes.filter((f) => f.status === "atrasado").length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <Activity className="size-6" style={{ color: "var(--bi-accent-ink)" }} />
            Frescor dos Dados
          </h1>
          <p className="mt-1 text-sm text-base-content/60">
            Última atualização de cada fonte (dado gravado + execução do coletor).
            Fresco ≤ 2 dias · Atrasado ≤ 7 dias · Crítico &gt; 7 dias.
          </p>
        </div>
        <Button variant="outline" onClick={carregar} disabled={loading}>
          {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <RefreshCw className="size-4 mr-1" />}
          Atualizar
        </Button>
      </div>

      {erro && (
        <div className="rounded-2xl p-3 text-sm"
          style={{ background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)", color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {!erro && (
        <>
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="text-base-content/60">
              {geradoEm && <>Gerado em {fmtDt(geradoEm)} · </>}
              <strong>{fontes.length}</strong> fontes
            </span>
            {criticos > 0 && <span className="font-medium" style={{ color: "var(--bi-crit-ink)" }}>{criticos} crítico(s)</span>}
            {atrasados > 0 && <span className="font-medium" style={{ color: "var(--bi-warn-ink)" }}>{atrasados} atrasado(s)</span>}
          </div>

          {loading && fontes.length === 0 ? (
            <div className="space-y-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-2xl" style={{ background: "var(--bi-surface-2)" }} />
              ))}
            </div>
          ) : (
            <Lista>
              {fontes.map((f) => {
                const st = STATUS_TOM[f.status] || STATUS_TOM.desconhecido;
                return (
                  <ItemLinha
                    key={f.fonte}
                    titulo={f.fonte}
                    valor={f.registros != null ? f.registros.toLocaleString("pt-BR") : "—"}
                    meta={<><Selo tom={st.tom}>{st.label}</Selo><span>{fmtIdade(f.idade_dias)}</span></>}
                  >
                    <Campos
                      campos={[
                        { rotulo: "Último dado", valor: fmtDt(f.ultimo_dado) },
                        { rotulo: "Última coleta", valor: fmtDt(f.ultima_coleta) },
                      ]}
                    />
                  </ItemLinha>
                );
              })}
            </Lista>
          )}
        </>
      )}
    </div>
  );
}
