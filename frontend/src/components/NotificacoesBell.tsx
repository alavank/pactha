"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { Bell, CheckCheck, X } from "lucide-react";
import api from "@/lib/api";

interface Notif {
  id: number;
  tipo: string;
  municipio_id: number | null;
  convenio_estadual_id: number | null;
  titulo: string;
  mensagem: string;
  severidade: string;
  lida: boolean;
  created_at: string;
}

const POLL_INTERVAL = 60_000; // 1 min

function sevColor(s: string): string {
  switch (s) {
    case "success": return "border-l-green-500 bg-green-50";
    case "warning": return "border-l-amber-500 bg-amber-50";
    case "critical": return "border-l-red-500 bg-red-50";
    default: return "border-l-blue-500 bg-blue-50";
  }
}

function timeAgo(iso: string): string {
  const d = new Date(iso);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `${s}s atrás`;
  if (s < 3600) return `${Math.floor(s / 60)}min atrás`;
  if (s < 86400) return `${Math.floor(s / 3600)}h atrás`;
  return d.toLocaleDateString("pt-BR");
}

export default function NotificacoesBell({ municipioId }: { municipioId?: number | null }) {
  const [items, setItems] = useState<Notif[]>([]);
  const [naoLidas, setNaoLidas] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const fetchData = useCallback(async () => {
    try {
      const params: Record<string, string | number> = { limit: 20 };
      if (municipioId) params.municipio_id = municipioId;
      const res = await api.get<{ items: Notif[]; nao_lidas: number }>("/notificacoes", { params });
      setItems(res.data.items || []);
      setNaoLidas(res.data.nao_lidas || 0);
    } catch {}
  }, [municipioId]);

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [fetchData]);

  // Click fora pra fechar
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    if (open) document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const marcarTodas = async () => {
    try {
      const params: Record<string, number> = {};
      if (municipioId) params.municipio_id = municipioId;
      await api.post("/notificacoes/marcar-todas-lidas", null, { params });
      fetchData();
    } catch {}
  };

  const marcarUma = async (id: number) => {
    try {
      await api.post(`/notificacoes/${id}/marcar-lida`);
      fetchData();
    } catch {}
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative p-2 rounded-md hover:bg-gray-100"
        aria-label="Notificações"
      >
        <Bell className="size-5 text-gray-700" />
        {naoLidas > 0 && (
          <span className="absolute -top-0.5 -right-0.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold text-white bg-red-600 rounded-full">
            {naoLidas > 99 ? "99+" : naoLidas}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-[380px] max-h-[70vh] overflow-y-auto bg-white rounded-lg shadow-lg border z-50">
          <div className="sticky top-0 bg-white border-b px-3 py-2 flex items-center justify-between">
            <div className="font-semibold text-sm">
              Notificações {naoLidas > 0 && <span className="text-red-600">({naoLidas} novas)</span>}
            </div>
            <div className="flex gap-1">
              {naoLidas > 0 && (
                <button
                  onClick={marcarTodas}
                  className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                  title="Marcar todas como lidas"
                >
                  <CheckCheck className="size-3" /> Marcar todas
                </button>
              )}
              <button onClick={() => setOpen(false)} className="p-1 hover:bg-gray-100 rounded">
                <X className="size-4 text-gray-500" />
              </button>
            </div>
          </div>

          {items.length === 0 ? (
            <div className="text-center text-sm text-muted-foreground py-8">
              Nenhuma notificação ainda.
            </div>
          ) : (
            <div>
              {items.map((n) => (
                <div
                  key={n.id}
                  onClick={() => !n.lida && marcarUma(n.id)}
                  className={`border-b border-l-4 px-3 py-2 cursor-pointer hover:bg-gray-100 ${sevColor(n.severidade)} ${
                    !n.lida ? "font-semibold" : "opacity-70"
                  }`}
                >
                  <div className="text-xs text-gray-500">{timeAgo(n.created_at)}</div>
                  <div className="text-sm">{n.titulo}</div>
                  {n.mensagem && <div className="text-xs text-gray-600 mt-0.5">{n.mensagem}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
