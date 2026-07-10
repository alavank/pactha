"use client";

import React, { createContext, useContext, useState, useCallback, ReactNode } from "react";
import { useSearchParams } from "next/navigation";

type MunicipioCtx = {
  municipioId: string;
  setMunicipioId: (id: string) => void;
};

const Ctx = createContext<MunicipioCtx | null>(null);

/**
 * Fonte da verdade do municipio selecionado — estado React (re-render instantaneo
 * e confiavel, sem a flakiness de useSearchParams + Suspense do Next 16).
 *
 * Ao trocar: atualiza o estado (todas as telas re-renderizam e refazem os fetches
 * client-side na hora) e sincroniza a barra de URL via history.replaceState — SEM
 * navegacao/router.refresh, ou seja, sem recarregar a pagina/Server Components.
 * Persiste em localStorage p/ lembrar na proxima visita e no deep-link/refresh.
 */
export function MunicipioProvider({ children }: { children: ReactNode }) {
  const searchParams = useSearchParams();

  const [municipioId, setId] = useState<string>(() => {
    const fromUrl = searchParams.get("municipio_id");
    if (fromUrl) return fromUrl;
    if (typeof window !== "undefined") {
      return localStorage.getItem("pactha_last_municipio_id") || "";
    }
    return "";
  });

  const setMunicipioId = useCallback((id: string) => {
    setId(id);
    if (typeof window === "undefined") return;
    if (id) localStorage.setItem("pactha_last_municipio_id", id);
    // Sincroniza a URL (shareable / sobrevive a refresh) SEM navegar.
    const params = new URLSearchParams(window.location.search);
    if (id) params.set("municipio_id", id);
    else params.delete("municipio_id");
    params.delete("page"); // reset de paginacao ao trocar de municipio
    const qs = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, []);

  return <Ctx.Provider value={{ municipioId, setMunicipioId }}>{children}</Ctx.Provider>;
}

export function useMunicipio(): MunicipioCtx {
  const ctx = useContext(Ctx);
  if (!ctx) return { municipioId: "", setMunicipioId: () => {} };
  return ctx;
}
