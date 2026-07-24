"use client";
// Escopo do Painel de Indicadores (BI). INDEPENDENTE do MunicipioContext
// operacional (que os tecnicos usam): adiciona a opcao "Consolidado (todos)" e
// persiste a escolha do BI numa chave PROPRIA (pactha_bi_scope) — nunca sobrescreve
// a selecao do sistema. Le a ultima selecao operacional so como valor inicial.
import { createContext, useContext, useState, useCallback, ReactNode } from "react";

export const CONSOLIDADO = "__all__";

interface BiScope {
  scope: string; // "__all__" (consolidado) | "<municipioId>" | ""
  setScope: (s: string) => void;
  municipioId: number | null; // null quando consolidado ou vazio
  isConsolidado: boolean;
  ano: number | undefined; // filtro de periodo (undefined = todos os anos)
  setAno: (a: number | undefined) => void;
}

const Ctx = createContext<BiScope | null>(null);

export function BiScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScopeState] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return (
      localStorage.getItem("pactha_bi_scope") ||
      localStorage.getItem("pactha_last_municipio_id") ||
      ""
    );
  });
  const [ano, setAnoState] = useState<number | undefined>(() => {
    if (typeof window === "undefined") return undefined;
    const raw = localStorage.getItem("pactha_bi_ano");
    return raw ? Number(raw) || undefined : undefined;
  });

  const setScope = useCallback((s: string) => {
    setScopeState(s);
    if (typeof window !== "undefined") localStorage.setItem("pactha_bi_scope", s);
  }, []);
  const setAno = useCallback((a: number | undefined) => {
    setAnoState(a);
    if (typeof window !== "undefined") {
      if (a) localStorage.setItem("pactha_bi_ano", String(a));
      else localStorage.removeItem("pactha_bi_ano");
    }
  }, []);

  const isConsolidado = scope === CONSOLIDADO;
  const municipioId = scope && scope !== CONSOLIDADO ? Number(scope) : null;

  return (
    <Ctx.Provider value={{ scope, setScope, municipioId, isConsolidado, ano, setAno }}>
      {children}
    </Ctx.Provider>
  );
}

export function useBiScope(): BiScope {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBiScope precisa estar dentro de <BiScopeProvider>");
  return v;
}
