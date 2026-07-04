"use client";

import React, { useEffect, useState } from "react";
import { HeartPulse, Search as SearchIcon, Loader2, Building2 } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface Credor {
  cnpj: string;
  razao_social: string;
  divida_inicial: number;
  total_pago: number;
  divida_atual: number;
  n_empenhos: number;
}
interface MunResp {
  credores: Credor[];
  total_divida_atual: number;
  total_pago: number;
  total_divida_inicial: number;
}

function maskCnpj(v: string): string {
  const d = (v || "").replace(/\D/g, "");
  if (d.length !== 14) return v || "-";
  return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
}

function Metric({ label, value, cls }: { label: string; value: string; cls?: string }) {
  return (
    <div className="rounded-2xl border border-base-300/60 bg-base-100 p-5 shadow-theme-sm">
      <p className="text-xs font-medium text-base-content/50">{label}</p>
      <p className={`mt-1.5 text-2xl font-bold ${cls || "text-base-content"}`}>{value}</p>
    </div>
  );
}

export default function AcordoFesPage() {
  const { municipioId } = useMunicipio();
  const [mun, setMun] = useState<MunResp | null>(null);
  const [loading, setLoading] = useState(true);

  const [q, setQ] = useState("");
  const [busca, setBusca] = useState<Credor[] | null>(null);
  const [buscando, setBuscando] = useState(false);

  useEffect(() => {
    if (!municipioId) { setMun(null); setLoading(false); return; }
    setLoading(true);
    api.get<MunResp>("/acordofes", { params: { municipio_id: municipioId } })
      .then((r) => setMun(r.data))
      .catch(() => setMun(null))
      .finally(() => setLoading(false));
  }, [municipioId]);

  const buscar = async () => {
    if (q.trim().length < 2) return;
    setBuscando(true);
    try {
      const r = await api.get<{ items: Credor[] }>("/acordofes/buscar", { params: { q: q.trim() } });
      setBusca(r.data.items);
    } catch { setBusca([]); }
    finally { setBuscando(false); }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <HeartPulse className="size-6 text-error" /> Acordo FES — Dívida da Saúde (SES-MG)
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Dívida do Fundo Estadual de Saúde de MG com os credores da saúde (fundos
          municipais, hospitais, consórcios). Fonte: Painel do Acordo FES (SES-MG).
        </p>
      </div>

      {/* Município selecionado */}
      {municipioId && loading && (
        <div className="flex justify-center py-12"><Loader2 className="size-7 animate-spin text-primary" /></div>
      )}
      {municipioId && !loading && (
        <div className="space-y-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-base-content/50">
            Fundo Municipal de Saúde deste município
          </div>
          {mun && mun.credores.length > 0 ? (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Metric label="Dívida inicial (2009-2020)" value={formatCurrency(mun.total_divida_inicial)} />
                <Metric label="Total pago no acordo" value={formatCurrency(mun.total_pago)} cls="text-success" />
                <Metric label="Dívida atual" value={formatCurrency(mun.total_divida_atual)} cls="text-error" />
              </div>
              {mun.credores.map((c) => (
                <div key={c.cnpj} className="rounded-2xl border border-base-300/60 bg-base-100 p-4 shadow-theme-sm flex flex-wrap items-center gap-x-6 gap-y-1">
                  <div className="flex-1 min-w-[200px]">
                    <div className="font-medium text-base-content">{c.razao_social}</div>
                    <div className="text-xs text-base-content/50 font-mono">{maskCnpj(c.cnpj)} · {c.n_empenhos} empenhos</div>
                  </div>
                  <div className="text-sm"><span className="text-base-content/50">Atual:</span> <span className="font-semibold text-error">{formatCurrency(c.divida_atual)}</span></div>
                </div>
              ))}
            </>
          ) : (
            <div className="rounded-2xl border border-base-300 bg-base-100 p-6 text-center text-base-content/60">
              Nenhum débito do Acordo FES vinculado ao fundo municipal de saúde deste município.
            </div>
          )}
        </div>
      )}

      {/* Busca livre por credor */}
      <div className="rounded-2xl border border-base-300/60 bg-base-100 p-4 shadow-theme-sm space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-base-content/50 flex items-center gap-2">
          <Building2 className="size-4" /> Buscar qualquer credor (hospital, consórcio, Santa Casa…)
        </div>
        <div className="flex gap-2">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && buscar()}
            placeholder="Nome ou CNPJ do credor"
            className="max-w-md"
          />
          <Button onClick={buscar} disabled={buscando || q.trim().length < 2} className="bg-primary hover:bg-primary/90">
            {buscando ? <Loader2 className="size-4 animate-spin" /> : <SearchIcon className="size-4" />}
          </Button>
        </div>
        {busca !== null && (
          busca.length === 0 ? (
            <p className="text-sm text-base-content/60 py-2">Nenhum credor encontrado.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-[13px]">
                <thead className="text-xs text-base-content/50">
                  <tr className="[&>th]:text-left [&>th]:font-semibold [&>th]:px-3 [&>th]:py-2">
                    <th>Credor</th><th>CNPJ</th>
                    <th className="text-right">Dívida inicial</th>
                    <th className="text-right">Pago</th>
                    <th className="text-right">Dívida atual</th>
                  </tr>
                </thead>
                <tbody>
                  {busca.map((c, i) => (
                    <tr key={c.cnpj + i} className="border-t border-base-300/60 [&>td]:px-3 [&>td]:py-2">
                      <td className="max-w-[320px]">{c.razao_social}</td>
                      <td className="font-mono text-xs whitespace-nowrap">{maskCnpj(c.cnpj)}</td>
                      <td className="text-right whitespace-nowrap">{formatCurrency(c.divida_inicial)}</td>
                      <td className="text-right whitespace-nowrap text-success">{formatCurrency(c.total_pago)}</td>
                      <td className="text-right whitespace-nowrap font-semibold text-error">{formatCurrency(c.divida_atual)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </div>
    </div>
  );
}
