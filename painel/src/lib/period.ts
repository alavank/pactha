"use client";
import { useEffect, useState } from "react";

// Período selecionado (ano) compartilhado entre todas as telas do painel.
// Persistido em localStorage e sincronizado via evento — muda numa tela, reflete
// em todas. null = todos os anos.
const KEY = "painel_ano";
const EVT = "painel-period";

function read(): number | null {
  if (typeof window === "undefined") return null;
  const v = localStorage.getItem(KEY);
  return v && v !== "todos" ? Number(v) : null;
}

export function usePeriod() {
  const [ano, setAnoState] = useState<number | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setAnoState(read());
    setReady(true);
    const h = () => setAnoState(read());
    window.addEventListener(EVT, h);
    return () => window.removeEventListener(EVT, h);
  }, []);

  const setAno = (a: number | null) => {
    try {
      localStorage.setItem(KEY, a == null ? "todos" : String(a));
    } catch {}
    setAnoState(a);
    window.dispatchEvent(new Event(EVT));
  };

  return { ano, setAno, ready };
}

// Janela de dias (para alertas/prazos): 60 / 90 / 120 dias etc.
const KEY_DIAS = "painel_dias";
const EVT_DIAS = "painel-dias";

export function useJanelaDias(def = 120) {
  const [dias, setDiasState] = useState<number>(def);
  useEffect(() => {
    try {
      const v = Number(localStorage.getItem(KEY_DIAS));
      if (v) setDiasState(v);
    } catch {}
    const h = () => {
      try {
        const v = Number(localStorage.getItem(KEY_DIAS));
        if (v) setDiasState(v);
      } catch {}
    };
    window.addEventListener(EVT_DIAS, h);
    return () => window.removeEventListener(EVT_DIAS, h);
  }, []);
  const setDias = (d: number) => {
    try {
      localStorage.setItem(KEY_DIAS, String(d));
    } catch {}
    setDiasState(d);
    window.dispatchEvent(new Event(EVT_DIAS));
  };
  return { dias, setDias };
}

export const ANOS: (number | null)[] = [null, 2026, 2025, 2024, 2023];
export const JANELAS = [
  { d: 60, label: "60 dias" },
  { d: 90, label: "90 dias" },
  { d: 120, label: "120 dias" },
  { d: 365, label: "1 ano" },
];

export function labelAno(ano: number | null): string {
  return ano == null ? "todos os anos" : String(ano);
}
