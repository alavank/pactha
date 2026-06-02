"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { Send, Loader2, Sparkles, Wrench, User, Bot, Eraser, FileText } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";

interface ToolCallLog {
  tool: string;
  input: Record<string, unknown>;
  output_preview: string;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  tool_calls?: ToolCallLog[];
  usage?: Record<string, unknown>;
}

const SUGESTOES_PROMPT = [
  "Quais convênios vencem nos próximos 60 dias?",
  "Quanto recebi em PNATE em 2026?",
  "Liste os convênios estaduais em prestação de contas vencidos.",
  "Gere um relatório de monitoramento federal do município.",
  "Quais propostas voluntárias estão aguardando análise?",
  "Resumo de tudo do município hoje.",
];

export default function AiChatPage() {
  const sp = useSearchParams();
  const municipioId = sp.get("municipio_id");

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const enviar = useCallback(
    async (msg: string) => {
      if (!msg.trim() || loading) return;
      setError(null);
      const userMsg: Message = { role: "user", content: msg.trim() };
      const next = [...messages, userMsg];
      setMessages(next);
      setInput("");
      setLoading(true);
      try {
        const r = await api.post<{
          reply: string;
          tool_calls: ToolCallLog[];
          usage: Record<string, unknown>;
        }>("/ai/chat", {
          message: msg.trim(),
          municipio_id: municipioId ? Number(municipioId) : null,
          history: messages.map((m) => ({ role: m.role, content: m.content })),
        });
        setMessages([
          ...next,
          {
            role: "assistant",
            content: r.data.reply,
            tool_calls: r.data.tool_calls,
            usage: r.data.usage,
          },
        ]);
      } catch (e: unknown) {
        const err = e as { response?: { data?: { detail?: string } } };
        const detail = err.response?.data?.detail || "Erro ao chamar a IA.";
        setError(detail);
      } finally {
        setLoading(false);
      }
    },
    [messages, loading, municipioId]
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    enviar(input);
  };

  const limpar = () => {
    setMessages([]);
    setError(null);
  };

  // Markdown bem simples (negrito, listas, code blocks, headings)
  const renderContent = (text: string) => {
    return text.split("\n").map((line, i) => {
      if (line.startsWith("### ")) return <h3 key={i} className="text-base font-bold mt-3 mb-1">{line.slice(4)}</h3>;
      if (line.startsWith("## ")) return <h2 key={i} className="text-lg font-bold mt-4 mb-1">{line.slice(3)}</h2>;
      if (line.startsWith("# ")) return <h1 key={i} className="text-xl font-bold mt-4 mb-2">{line.slice(2)}</h1>;
      if (line.startsWith("- ") || line.startsWith("* ")) {
        return <li key={i} className="ml-5 list-disc">{renderInline(line.slice(2))}</li>;
      }
      if (line.match(/^\d+\.\s/)) {
        return <li key={i} className="ml-5 list-decimal">{renderInline(line.replace(/^\d+\.\s/, ""))}</li>;
      }
      if (line.trim() === "") return <div key={i} className="h-2" />;
      return <p key={i} className="leading-snug">{renderInline(line)}</p>;
    });
  };
  const renderInline = (text: string) => {
    // **bold** e `code` simples
    const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
    return parts.map((p, i) => {
      if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
      if (p.startsWith("`") && p.endsWith("`")) return <code key={i} className="bg-slate-100 px-1 rounded text-[12px] font-mono">{p.slice(1, -1)}</code>;
      return <span key={i}>{p}</span>;
    });
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)] max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 pb-3 border-b">
        <div>
          <h1 className="text-2xl font-bold text-blue-800 flex items-center gap-2">
            <Sparkles className="size-6 text-violet-600" /> IA PACTA
          </h1>
          <p className="text-sm text-slate-500">
            Assistente que consulta o banco em tempo real e gera relatórios. Pergunte em português.
          </p>
        </div>
        {messages.length > 0 && (
          <Button variant="outline" size="sm" onClick={limpar}>
            <Eraser className="size-4 mr-1" /> Limpar conversa
          </Button>
        )}
      </div>

      {/* Mensagens */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <Sparkles className="size-12 mx-auto text-violet-300 mb-3" />
            <p className="text-slate-600 mb-4">Sugestões para começar:</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
              {SUGESTOES_PROMPT.map((s, i) => (
                <button
                  key={i}
                  onClick={() => enviar(s)}
                  className="text-left text-sm bg-white border rounded-lg px-3 py-2 hover:border-blue-400 hover:bg-blue-50 transition"
                >
                  <FileText className="inline size-3.5 mr-1 text-blue-600" />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && (
              <div className="shrink-0 size-8 rounded-full bg-violet-100 flex items-center justify-center">
                <Bot className="size-5 text-violet-700" />
              </div>
            )}
            <div className={`max-w-[80%] ${m.role === "user" ? "order-1" : ""}`}>
              {m.role === "assistant" && m.tool_calls && m.tool_calls.length > 0 && (
                <details className="mb-2 text-xs text-slate-500 bg-slate-50 border rounded px-2 py-1">
                  <summary className="cursor-pointer flex items-center gap-1">
                    <Wrench className="size-3" />
                    {m.tool_calls.length} consulta(s) no banco
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {m.tool_calls.map((tc, j) => (
                      <li key={j}>
                        <code className="font-mono text-[11px]">{tc.tool}</code>
                        {Object.keys(tc.input).length > 0 && (
                          <span className="text-slate-400"> ({JSON.stringify(tc.input)})</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <div
                className={`rounded-lg px-3.5 py-2.5 text-sm ${
                  m.role === "user"
                    ? "bg-blue-600 text-white"
                    : "bg-white border border-slate-200 text-slate-800"
                }`}
              >
                {m.role === "user" ? (
                  <div className="whitespace-pre-wrap">{m.content}</div>
                ) : (
                  <div className="prose prose-sm max-w-none">{renderContent(m.content)}</div>
                )}
              </div>
              {m.usage && m.role === "assistant" && (
                <div className="text-[10px] text-slate-400 mt-1">
                  {String(m.usage.input_tokens)} in / {String(m.usage.output_tokens)} out tokens
                  {Number(m.usage.cache_read) > 0 && ` · cache hit ${m.usage.cache_read}`}
                </div>
              )}
            </div>
            {m.role === "user" && (
              <div className="shrink-0 size-8 rounded-full bg-blue-100 flex items-center justify-center">
                <User className="size-5 text-blue-700" />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 size-8 rounded-full bg-violet-100 flex items-center justify-center">
              <Bot className="size-5 text-violet-700" />
            </div>
            <div className="bg-white border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm flex items-center gap-2 text-slate-500">
              <Loader2 className="size-4 animate-spin" /> Consultando o banco e pensando...
            </div>
          </div>
        )}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-800 rounded-lg px-3 py-2 text-sm">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="border-t pt-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Pergunte algo sobre os convênios do município..."
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:outline-none focus:border-blue-500"
          disabled={loading}
        />
        <Button type="submit" disabled={loading || !input.trim()} className="bg-violet-600 hover:bg-violet-700">
          {loading ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
        </Button>
      </form>
    </div>
  );
}
