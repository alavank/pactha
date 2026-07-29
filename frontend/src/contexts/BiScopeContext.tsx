"use client";
// Escopo + periodo do Painel de Indicadores (BI). INDEPENDENTE do
// MunicipioContext operacional (que os tecnicos usam): adiciona a opcao
// "Consolidado (todos)" e persiste a escolha do BI numa chave PROPRIA
// (pactha_bi_scope) — nunca sobrescreve a selecao do sistema.
//
// PERIODO E MULTI-ANO: um prefeito filtra o MANDATO (ex.: 2021-2024), nao um
// ano. `anos` e a fonte da verdade; `ano` continua exposto so para as telas
// antigas que ainda mandam um valor unico.
import { createContext, useContext, useState, useCallback, ReactNode, useMemo } from "react";

export const CONSOLIDADO = "__all__";

const K_SCOPE = "pactha_bi_scope";
const K_ANOS = "pactha_bi_anos";
const K_ANO_LEGADO = "pactha_bi_ano";

interface BiScope {
  scope: string; // "__all__" (consolidado) | "<municipioId>" | ""
  setScope: (s: string) => void;
  municipioId: number | null; // null quando consolidado ou vazio
  isConsolidado: boolean;
  /** Anos selecionados (vazio = todos os anos). */
  anos: number[];
  setAnos: (a: number[]) => void;
  alternarAno: (a: number) => void;
  /** Compat: primeiro ano quando ha exatamente um selecionado. */
  ano: number | undefined;
  setAno: (a: number | undefined) => void;
}

const Ctx = createContext<BiScope | null>(null);

function lerAnosIniciais(): number[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(K_ANOS);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) return arr.map(Number).filter(Boolean).sort((a, b) => a - b);
    }
  } catch { /* json invalido -> cai no legado */ }
  const legado = Number(localStorage.getItem(K_ANO_LEGADO) || 0);
  return legado ? [legado] : [];
}

export function BiScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScopeState] = useState<string>(() => {
    if (typeof window === "undefined") return "";
    return (
      localStorage.getItem(K_SCOPE) ||
      localStorage.getItem("pactha_last_municipio_id") ||
      ""
    );
  });
  const [anos, setAnosState] = useState<number[]>(lerAnosIniciais);

  const setScope = useCallback((s: string) => {
    setScopeState(s);
    if (typeof window !== "undefined") localStorage.setItem(K_SCOPE, s);
  }, []);

  const setAnos = useCallback((a: number[]) => {
    const limpo = [...new Set(a.map(Number).filter(Boolean))].sort((x, y) => x - y);
    setAnosState(limpo);
    if (typeof window === "undefined") return;
    if (limpo.length) {
      localStorage.setItem(K_ANOS, JSON.stringify(limpo));
      // mantem a chave antiga coerente p/ quem ainda le (1 ano = mesmo valor)
      if (limpo.length === 1) localStorage.setItem(K_ANO_LEGADO, String(limpo[0]));
      else localStorage.removeItem(K_ANO_LEGADO);
    } else {
      localStorage.removeItem(K_ANOS);
      localStorage.removeItem(K_ANO_LEGADO);
    }
  }, []);

  const alternarAno = useCallback((a: number) => {
    setAnosState((atual) => {
      const proximo = atual.includes(a) ? atual.filter((x) => x !== a) : [...atual, a];
      const limpo = [...new Set(proximo)].sort((x, y) => x - y);
      if (typeof window !== "undefined") {
        if (limpo.length) {
          localStorage.setItem(K_ANOS, JSON.stringify(limpo));
          if (limpo.length === 1) localStorage.setItem(K_ANO_LEGADO, String(limpo[0]));
          else localStorage.removeItem(K_ANO_LEGADO);
        } else {
          localStorage.removeItem(K_ANOS);
          localStorage.removeItem(K_ANO_LEGADO);
        }
      }
      return limpo;
    });
  }, []);

  const setAno = useCallback((a: number | undefined) => setAnos(a ? [a] : []), [setAnos]);

  const value = useMemo<BiScope>(() => ({
    scope,
    setScope,
    municipioId: scope && scope !== CONSOLIDADO ? Number(scope) : null,
    isConsolidado: scope === CONSOLIDADO,
    anos,
    setAnos,
    alternarAno,
    ano: anos.length === 1 ? anos[0] : undefined,
    setAno,
  }), [scope, setScope, anos, setAnos, alternarAno, setAno]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBiScope(): BiScope {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBiScope precisa estar dentro de <BiScopeProvider>");
  return v;
}
