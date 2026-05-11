"use client";

import React, { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Send, Loader2, Sparkles } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type Msg = { role: "user" | "assistant"; content: string };
type Trace = { tool: string; input: Record<string, unknown>; result_keys: string[] | null };

export default function PactaIAPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [lastTraces, setLastTraces] = useState<Trace[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const send = async () => {
    if (!input.trim() || sending) return;
    const userMsg: Msg = { role: "user", content: input.trim() };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setSending(true);
    try {
      const r = await api.post("/ia/chat", {
        messages: next,
        municipio_id: municipioId ? Number(municipioId) : null,
      });
      setMessages([...next, { role: "assistant", content: r.data.answer || "(sem resposta)" }]);
      setLastTraces(r.data.traces || []);
    } catch (e: any) {
      setMessages([...next, {
        role: "assistant",
        content: `Erro: ${e?.response?.data?.detail || e?.message || "falha"}`,
      }]);
    } finally {
      setSending(false);
    }
  };

  const examples = [
    "Quanto Bom Despacho recebeu em emendas do Luis Tibé em 2024-2026?",
    "Quais convênios estão vencendo nos próximos 30 dias?",
    "Liste os 10 deputados mais votados em Piracema com valor de emendas",
    "Que oportunidades federais estão abertas para saúde?",
    "Tem alguma sanção CEIS ativa para o CNPJ 12345678000190?",
  ];

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col gap-4 p-4">
      <div className="flex items-center gap-2">
        <Sparkles className="size-6 text-purple-600" />
        <h1 className="text-2xl font-bold">PACTA IA</h1>
        <span className="rounded bg-purple-100 px-2 py-0.5 text-xs text-purple-700">Beta</span>
        {municipioId && (
          <span className="ml-auto text-xs text-muted-foreground">
            Município ID: {municipioId}
          </span>
        )}
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 rounded-lg border bg-gray-50 p-4">
        {messages.length === 0 ? (
          <div className="space-y-3 text-center py-12">
            <Sparkles className="mx-auto size-12 text-purple-300" />
            <p className="text-sm text-muted-foreground">
              Pergunte qualquer coisa sobre convênios, emendas, parlamentares, oportunidades…
            </p>
            <div className="flex flex-wrap justify-center gap-2 mt-6">
              {examples.map((ex, i) => (
                <button
                  key={i}
                  onClick={() => setInput(ex)}
                  className="rounded-full border bg-white px-3 py-1 text-xs hover:bg-purple-50"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((m, i) => (
            <Card key={i} className={`p-3 ${m.role === "user" ? "bg-blue-50 border-blue-200 ml-12" : "bg-white mr-12"}`}>
              <div className="mb-1 text-xs font-semibold text-muted-foreground">
                {m.role === "user" ? "Você" : "PACTA IA"}
              </div>
              <div className="whitespace-pre-wrap text-sm">{m.content}</div>
            </Card>
          ))
        )}
        {sending && (
          <Card className="p-3 mr-12 flex items-center gap-2">
            <Loader2 className="animate-spin size-4 text-purple-600" />
            <span className="text-sm text-muted-foreground">Consultando dados…</span>
          </Card>
        )}
      </div>

      {lastTraces.length > 0 && (
        <details className="rounded border bg-gray-50 px-3 py-2 text-xs text-muted-foreground">
          <summary className="cursor-pointer">Consultas realizadas ({lastTraces.length})</summary>
          <ul className="mt-2 space-y-1">
            {lastTraces.map((t, i) => (
              <li key={i}>
                <code>{t.tool}</code> ({Object.keys(t.input || {}).join(", ")})
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="flex gap-2">
        <input
          className="flex-1 rounded border px-3 py-2 text-sm"
          placeholder="Faça uma pergunta…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={sending}
        />
        <Button onClick={send} disabled={sending || !input.trim()}>
          <Send className="size-4" />
        </Button>
      </div>
    </div>
  );
}
