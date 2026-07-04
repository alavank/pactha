"use client";

import React, { useEffect, useState } from "react";
import { ShieldCheck, ShieldAlert, CheckCircle2, AlertTriangle, Loader2, MinusCircle } from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";

interface Item {
  codigo: string;
  grupo: string;
  label: string;
  valor: string;
  tipo: "regular" | "pendente" | "na";
  status: string;
}
interface CaucResp {
  tem_dados: boolean;
  nome?: string;
  uf?: string;
  ibge?: string;
  populacao?: number;
  data_pesquisa?: string | null;
  regular?: boolean;
  pendencias?: number;
  pendencias_codigos?: string[];
  itens?: Item[];
  atualizado_em?: string | null;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleDateString("pt-BR", { timeZone: "UTC" }); }
  catch { return iso.slice(0, 10); }
}

export default function CaucPage() {
  const { municipioId } = useMunicipio();
  const [data, setData] = useState<CaucResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!municipioId) { setData(null); setLoading(false); return; }
    setLoading(true);
    api.get<CaucResp>("/cauc", { params: { municipio_id: municipioId } })
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [municipioId]);

  // agrupa os itens por grupo
  const grupos: Record<string, Item[]> = {};
  (data?.itens || []).forEach((it) => {
    (grupos[it.grupo] ||= []).push(it);
  });

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <ShieldCheck className="size-6 text-primary" /> CAUC — Regularidade Fiscal Federal
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Situação do município no CAUC (Tesouro Nacional) — exigências para receber
          transferências voluntárias da União. Fonte: dados abertos do Tesouro.
          {data?.data_pesquisa ? ` Pesquisa de ${fmtDate(data.data_pesquisa)}.` : ""}
        </p>
      </div>

      {!municipioId && (
        <div className="rounded-2xl border border-base-300 bg-base-100 p-8 text-center text-base-content/60">
          Selecione um município para ver a situação no CAUC.
        </div>
      )}

      {municipioId && loading && (
        <div className="flex justify-center py-16"><Loader2 className="size-8 animate-spin text-primary" /></div>
      )}

      {municipioId && !loading && !data?.tem_dados && (
        <div className="rounded-2xl border border-base-300 bg-base-100 p-8 text-center text-base-content/60">
          Sem dados do CAUC para este município ainda. (A base é atualizada automaticamente.)
        </div>
      )}

      {municipioId && !loading && data?.tem_dados && (
        <>
          {/* Banner de situação */}
          <div className={`rounded-2xl border p-5 ${data.regular
            ? "border-success/30 bg-success/10"
            : "border-error/30 bg-error/10"}`}>
            <div className="flex items-center gap-3">
              {data.regular
                ? <CheckCircle2 className="size-9 text-success shrink-0" />
                : <ShieldAlert className="size-9 text-error shrink-0" />}
              <div>
                <div className={`text-lg font-bold ${data.regular ? "text-success" : "text-error"}`}>
                  {data.regular
                    ? "Regular no CAUC"
                    : `${data.pendencias} pendência(s) impeditiva(s)`}
                </div>
                <div className="text-sm text-base-content/70">
                  {data.nome}/{data.uf}
                  {data.regular
                    ? " — apto a receber transferências voluntárias da União."
                    : ` — pendências nos itens ${(data.pendencias_codigos || []).join(", ")} podem travar transferências.`}
                </div>
              </div>
            </div>
          </div>

          {/* Exigências agrupadas */}
          <div className="space-y-4">
            {Object.entries(grupos).map(([grupo, itens]) => (
              <div key={grupo} className="rounded-2xl border border-base-300/60 bg-base-100 overflow-hidden shadow-theme-sm">
                <div className="px-4 py-2.5 bg-base-200/50 border-b border-base-300 text-sm font-semibold text-base-content/70">
                  {grupo}
                </div>
                <div className="divide-y divide-base-300/60">
                  {itens.map((it) => (
                    <div key={it.codigo} className="flex items-start gap-3 px-4 py-2.5">
                      <span className="mt-0.5">
                        {it.tipo === "pendente" ? <AlertTriangle className="size-4 text-error" />
                          : it.tipo === "regular" ? <CheckCircle2 className="size-4 text-success" />
                          : <MinusCircle className="size-4 text-base-content/30" />}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-base-content">
                          <span className="font-mono text-xs text-base-content/50 mr-2">{it.codigo}</span>
                          {it.label}
                        </div>
                      </div>
                      <span className={`shrink-0 text-xs font-medium whitespace-nowrap ${
                        it.tipo === "pendente" ? "text-error"
                        : it.tipo === "regular" ? "text-success"
                        : "text-base-content/40"}`}>
                        {it.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <p className="text-xs text-base-content/40">
            Legenda: <span className="text-success">✔ regular até a data</span> ·
            <span className="text-error"> ⚠ pendência (impeditivo)</span> ·
            <span className="text-base-content/40"> ⊘ não exigido</span>.
            Atualizado em {fmtDate(data.atualizado_em)}.
          </p>
        </>
      )}
    </div>
  );
}
