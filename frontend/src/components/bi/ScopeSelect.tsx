"use client";
// Seletor de escopo do BI. Entidade unica (municipio/consorcio) = chip estatico
// (sem dropdown). Multi-entidade (assessoria/parceiro/admin) = dropdown com a
// opcao "Consolidado (todos)" no topo. Espelha a regra do sidebar operacional.
import { Municipio } from "@/lib/bi";
import { useBiScope, CONSOLIDADO } from "@/contexts/BiScopeContext";

export function ScopeSelect({
  municipios,
  canConsolidado,
}: {
  municipios: Municipio[];
  canConsolidado: boolean;
}) {
  const { scope, setScope } = useBiScope();

  if (municipios.length <= 1 && !canConsolidado) {
    const m = municipios[0];
    return (
      <div className="rounded-[var(--radius-field)] border border-base-300 bg-base-100 px-3 py-1.5 text-center text-sm font-semibold">
        {m ? `${m.nome} - ${m.uf}` : "—"}
      </div>
    );
  }

  return (
    <select
      className="select select-bordered select-sm min-w-[12rem] max-w-full"
      value={scope}
      onChange={(e) => setScope(e.target.value)}
      aria-label="Escopo do painel"
    >
      {canConsolidado && <option value={CONSOLIDADO}>★ Consolidado (todos)</option>}
      {municipios.map((m) => (
        <option key={m.id} value={String(m.id)}>
          {m.nome} - {m.uf}
        </option>
      ))}
    </select>
  );
}

// Seletor de periodo (ano). Compacto, opcional.
export function PeriodSelect({ anos }: { anos: number[] }) {
  const { ano, setAno } = useBiScope();
  return (
    <select
      className="select select-bordered select-sm w-[7.5rem]"
      value={ano ?? ""}
      onChange={(e) => setAno(e.target.value ? Number(e.target.value) : undefined)}
      aria-label="Período"
    >
      <option value="">Todos os anos</option>
      {anos.map((a) => (
        <option key={a} value={a}>
          {a}
        </option>
      ))}
    </select>
  );
}
