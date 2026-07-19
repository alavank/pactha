"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Activity, RefreshCw, Loader2 } from "lucide-react";
import api from "@/lib/api";
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

const STATUS_STYLE: Record<string, { cls: string; label: string }> = {
  fresco: { cls: "bg-success/15 text-success", label: "Fresco" },
  atrasado: { cls: "bg-warning/15 text-warning", label: "Atrasado" },
  critico: { cls: "bg-error/15 text-error", label: "Crítico" },
  desconhecido: { cls: "bg-base-300 text-base-content/60", label: "?" },
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
            <Activity className="size-6 text-primary" />
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

      {erro && <div className="rounded-lg border border-error bg-error/15 p-3 text-sm text-error">{erro}</div>}

      {!erro && (
        <>
          <div className="flex flex-wrap gap-3 text-sm">
            <span className="text-base-content/60">
              {geradoEm && <>Gerado em {fmtDt(geradoEm)} · </>}
              <strong>{fontes.length}</strong> fontes
            </span>
            {criticos > 0 && <span className="text-error font-medium">{criticos} crítico(s)</span>}
            {atrasados > 0 && <span className="text-warning font-medium">{atrasados} atrasado(s)</span>}
          </div>

          <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-100">
            <table className="min-w-full text-sm">
              <thead className="bg-base-200 text-base-content/70">
                <tr className="[&>th]:px-3 [&>th]:py-2 [&>th]:text-left [&>th]:font-semibold">
                  <th>Fonte</th>
                  <th>Status</th>
                  <th>Idade</th>
                  <th>Último dado</th>
                  <th>Última coleta</th>
                  <th className="text-right">Registros</th>
                </tr>
              </thead>
              <tbody>
                {loading && fontes.length === 0 && (
                  <tr><td colSpan={6} className="p-6 text-center"><Loader2 className="inline size-5 animate-spin text-primary" /></td></tr>
                )}
                {fontes.map((f) => {
                  const st = STATUS_STYLE[f.status] || STATUS_STYLE.desconhecido;
                  return (
                    <tr key={f.fonte} className="border-t border-base-300 even:bg-base-200/40">
                      <td className="px-3 py-2 font-medium text-base-content">{f.fonte}</td>
                      <td className="px-3 py-2">
                        <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${st.cls}`}>
                          {st.label}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-base-content/70">{fmtIdade(f.idade_dias)}</td>
                      <td className="px-3 py-2 text-base-content/60">{fmtDt(f.ultimo_dado)}</td>
                      <td className="px-3 py-2 text-base-content/60">{fmtDt(f.ultima_coleta)}</td>
                      <td className="px-3 py-2 text-right text-base-content/70">
                        {f.registros != null ? f.registros.toLocaleString("pt-BR") : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
