"use client";

import { useEffect, useState, useCallback } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Landmark, Loader2, Search, Eraser } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";

interface PacItem {
  numero_proposta: string;
  programa: string | null;
  programa_codigo: string | null;
  proponente: string | null;
  cnpj: string | null;
  situacao: string | null;
  valor_repasse: number | null;
  valor_contrapartida: number | null;
  valor_total: number | null;
  emenda_parlamentar: string | null;
  qualificacao: string | null;
  objeto: string | null;
  justificativa: string | null;
}

export default function TransfereGovPacPage() {
  const { municipioId } = useMunicipio();
  const [items, setItems] = useState<PacItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState("");
  const [q, setQ] = useState("");
  const [atualizado, setAtualizado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true); setErro("");
    try {
      const r = await api.get("/transferegov/pac", { params: { municipio_id: municipioId } });
      setItems(r.data.items || []);
      setAtualizado(r.data.atualizado || null);
    } catch {
      setErro("Erro ao carregar propostas PAC.");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [municipioId]);

  useEffect(() => { carregar(); }, [carregar]);

  const termo = q.trim().toLowerCase();
  const filtrados = termo
    ? items.filter((i) =>
        [i.numero_proposta, i.programa, i.situacao, i.emenda_parlamentar, i.objeto]
          .filter(Boolean).some((v) => (v as string).toLowerCase().includes(termo)))
    : items;
  const total = filtrados.reduce((s, i) => s + (i.valor_total || 0), 0);

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold text-base-content">
          <Landmark className="size-5 text-primary" />
          Transfere Gov — Seleção PAC (Novo PAC)
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Propostas do Novo PAC do município (TransfereGov / Acesso Livre).
          {atualizado ? ` · Atualizado: ${new Date(atualizado).toLocaleDateString("pt-BR")}` : ""}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[220px]">
          <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-base-content/40" />
          <Input className="pl-8" placeholder="Buscar nº, programa, situação, emenda, objeto..."
            value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        {q && (
          <Button variant="outline" size="sm" onClick={() => setQ("")}>
            <Eraser className="size-4" /> Limpar
          </Button>
        )}
        <span className="text-sm text-base-content/60">
          {filtrados.length} proposta(s) · <span className="font-medium text-success">{formatCurrency(total)}</span>
        </span>
      </div>

      {loading ? (
        <div className="flex justify-center py-10"><Loader2 className="size-6 animate-spin text-info" /></div>
      ) : erro ? (
        <div className="text-sm text-error bg-error/15 border border-error rounded p-3">{erro}</div>
      ) : filtrados.length === 0 ? (
        <div className="text-sm text-base-content/60 italic py-8 text-center">
          Nenhuma proposta PAC para este município. (A coleta roda no cron; se acabou de subir, aguarde.)
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-100">
          <table className="w-full text-sm">
            <thead className="bg-base-200 text-left text-xs uppercase text-base-content/60">
              <tr>
                <th className="px-3 py-2">Nº Proposta</th>
                <th className="px-3 py-2">Programa</th>
                <th className="px-3 py-2">Situação</th>
                <th className="px-3 py-2 text-right">Valor Total</th>
                <th className="px-3 py-2">Emenda Parlamentar</th>
              </tr>
            </thead>
            <tbody>
              {filtrados.map((i) => (
                <tr key={i.numero_proposta} className="border-t border-base-200 even:bg-base-200/40 align-top">
                  <td className="px-3 py-2 font-mono whitespace-nowrap">{i.numero_proposta}</td>
                  <td className="px-3 py-2 max-w-[360px] whitespace-normal break-words leading-snug" title={i.programa || ""}>
                    {i.programa || "-"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-xs">{i.situacao || "-"}</td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">{i.valor_total != null ? formatCurrency(i.valor_total) : "-"}</td>
                  <td className="px-3 py-2 text-xs">{i.emenda_parlamentar || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
