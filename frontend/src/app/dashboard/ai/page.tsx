"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Send, Loader2, Sparkles, Wrench, User, Bot, Eraser, FileText } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useMunicipio } from "@/contexts/MunicipioContext";

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
  "Liste TUDO do deputado Eduardo Azevedo (estadual e federal)",
  "Resumo de tudo do município hoje.",
  "Convênios estaduais em prestação de contas vencidos.",
  "Quais propostas voluntárias estão aguardando análise?",
  "Quanto recebi em PNATE em 2026?",
];

export default function AiChatPage() {
  const { municipioId } = useMunicipio();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pdfIdx, setPdfIdx] = useState<number | null>(null);
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
        }, {
          // a IA pode consultar varias fontes; da folga (a resposta tipica < 40s)
          timeout: 180000,
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
        const err = e as {
          response?: { status?: number; statusText?: string; data?: { detail?: string | object } };
          message?: string;
          code?: string;
        };
        console.error("AI chat error", err);
        let msg = "Erro ao chamar a IA.";
        if (err.response) {
          const status = err.response.status;
          const detail = err.response.data?.detail;
          const detailStr = typeof detail === "string" ? detail : detail ? JSON.stringify(detail).slice(0, 300) : "";
          msg = `HTTP ${status} ${err.response.statusText || ""}${detailStr ? ` - ${detailStr}` : ""}`;
        } else if (err.code === "ECONNABORTED") {
          msg = "A IA demorou demais para responder. Tente uma pergunta mais específica (ex.: filtre por município) e tente de novo.";
        } else if (err.code === "ERR_NETWORK") {
          msg = "Falha de conexão com a IA — a resposta pode ter demorado ou o servidor estava reiniciando. Aguarde alguns segundos e tente novamente.";
        } else if (err.message) {
          msg = `${err.code || "Network"}: ${err.message}`;
        }
        setError(msg);
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

  // Exporta uma resposta da IA (markdown) em PDF. Usa a pergunta anterior como contexto.
  const baixarPdf = async (msg: Message, idx: number) => {
    setPdfIdx(idx);
    try {
      const pergunta = idx > 0 && messages[idx - 1]?.role === "user" ? messages[idx - 1].content : "";
      const titulo = pergunta ? pergunta.slice(0, 90) : "Relatório - IA PACTHA";
      const token = localStorage.getItem("pactha_token");
      const res = await fetch(`${api.defaults.baseURL}/export-pdf/ai`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify({ titulo, pergunta, conteudo: msg.content }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setError("Não foi possível gerar o PDF. Tente novamente.");
    } finally {
      setPdfIdx(null);
    }
  };

  // Markdown completo via react-markdown + remark-gfm (tabelas, listas, code, etc.)
  const renderContent = (text: string) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: (props) => <h1 className="text-xl font-bold mt-4 mb-2 text-base-content" {...props} />,
        h2: (props) => <h2 className="text-lg font-bold mt-4 mb-2 text-primary border-b border-base-300 pb-1" {...props} />,
        h3: (props) => <h3 className="text-base font-bold mt-3 mb-1 text-base-content" {...props} />,
        h4: (props) => <h4 className="text-sm font-bold mt-2 mb-1 text-base-content/70" {...props} />,
        p: (props) => <p className="leading-relaxed my-2" {...props} />,
        ul: (props) => <ul className="list-disc ml-5 my-2 space-y-1" {...props} />,
        ol: (props) => <ol className="list-decimal ml-5 my-2 space-y-1" {...props} />,
        li: (props) => <li className="leading-snug" {...props} />,
        strong: (props) => <strong className="font-semibold text-base-content" {...props} />,
        em: (props) => <em className="italic text-base-content/70" {...props} />,
        code: (props) => (
          <code className="bg-base-200 px-1.5 py-0.5 rounded text-[12px] font-mono text-error" {...props} />
        ),
        pre: (props) => (
          <pre className="bg-base-300 text-base-content rounded p-3 my-2 text-xs overflow-x-auto" {...props} />
        ),
        blockquote: (props) => (
          <blockquote className="border-l-4 border-base-300 pl-3 my-2 italic text-base-content/70" {...props} />
        ),
        table: (props) => (
          <div className="my-3 overflow-x-auto rounded border border-base-300">
            <table className="min-w-full text-xs" {...props} />
          </div>
        ),
        thead: (props) => <thead className="bg-primary/10 text-primary" {...props} />,
        th: (props) => (
          <th className="text-left font-semibold px-3 py-1.5 border-b border-base-300" {...props} />
        ),
        td: (props) => <td className="px-3 py-1.5 border-b border-base-300 align-top" {...props} />,
        tr: (props) => <tr className="even:bg-base-200/50" {...props} />,
        a: (props) => (
          <a className="text-primary underline hover:text-primary/90" target="_blank" rel="noopener" {...props} />
        ),
        hr: () => <hr className="my-3 border-base-300" />,
      }}
    >
      {text}
    </ReactMarkdown>
  );

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-7rem)] max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 pb-3 border-b">
        <div>
          <h1 className="text-2xl font-bold text-primary flex items-center gap-2">
            <Sparkles className="size-6 text-info" /> IA PACTHA
          </h1>
          <p className="text-sm text-base-content/60">
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
            <Sparkles className="size-12 mx-auto text-info/40 mb-3" />
            <p className="text-base-content/70 mb-4">Sugestões para começar:</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
              {SUGESTOES_PROMPT.map((s, i) => (
                <button
                  key={i}
                  onClick={() => enviar(s)}
                  className="text-left text-sm bg-base-100 border rounded-lg px-3 py-2 hover:border-primary hover:bg-primary/10 transition"
                >
                  <FileText className="inline size-3.5 mr-1 text-primary" />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && (
              <div className="shrink-0 size-8 rounded-full bg-info/15 flex items-center justify-center">
                <Bot className="size-5 text-info" />
              </div>
            )}
            <div className={`${m.role === "user" ? "max-w-[80%] order-1" : "max-w-[92%] flex-1"}`}>
              {m.role === "assistant" && m.tool_calls && m.tool_calls.length > 0 && (
                <details className="mb-2 text-xs text-base-content/60 bg-base-200 border rounded px-2 py-1">
                  <summary className="cursor-pointer flex items-center gap-1">
                    <Wrench className="size-3" />
                    {m.tool_calls.length} consulta(s) no banco
                  </summary>
                  <ul className="mt-1 space-y-1">
                    {m.tool_calls.map((tc, j) => (
                      <li key={j}>
                        <code className="font-mono text-[11px]">{tc.tool}</code>
                        {Object.keys(tc.input).length > 0 && (
                          <span className="text-base-content/40"> ({JSON.stringify(tc.input)})</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              <div
                className={`rounded-lg px-3.5 py-2.5 text-sm ${
                  m.role === "user"
                    ? "bg-primary text-white"
                    : "bg-base-100 border border-base-300 text-base-content"
                }`}
              >
                {m.role === "user" ? (
                  <div className="whitespace-pre-wrap">{m.content}</div>
                ) : (
                  <div className="text-[13px] leading-relaxed">{renderContent(m.content)}</div>
                )}
              </div>
              {m.usage && m.role === "assistant" && (
                <div className="text-[10px] text-base-content/40 mt-1">
                  {String(m.usage.input_tokens)} in / {String(m.usage.output_tokens)} out tokens
                  {Number(m.usage.cache_read) > 0 && ` · cache hit ${m.usage.cache_read}`}
                </div>
              )}
              {m.role === "assistant" && m.content && (
                <button
                  onClick={() => baixarPdf(m, i)}
                  disabled={pdfIdx === i}
                  title="Exportar esta resposta em PDF"
                  className="mt-1.5 inline-flex items-center gap-1 text-xs text-primary hover:underline disabled:opacity-60"
                >
                  {pdfIdx === i ? <Loader2 className="size-3 animate-spin" /> : <FileText className="size-3" />}
                  Baixar PDF
                </button>
              )}
            </div>
            {m.role === "user" && (
              <div className="shrink-0 size-8 rounded-full bg-primary/10 flex items-center justify-center">
                <User className="size-5 text-primary" />
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div className="flex gap-3">
            <div className="shrink-0 size-8 rounded-full bg-info/15 flex items-center justify-center">
              <Bot className="size-5 text-info" />
            </div>
            <div className="bg-base-100 border border-base-300 rounded-lg px-3.5 py-2.5 text-sm flex items-center gap-2 text-base-content/60">
              <Loader2 className="size-4 animate-spin" /> Consultando o banco e pensando...
            </div>
          </div>
        )}
        {error && (
          <div className="bg-error/15 border border-error text-error rounded-lg px-3 py-2 text-sm">
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
          className="flex-1 rounded-lg border border-base-300 px-3 py-2.5 text-sm focus:outline-none focus:border-primary"
          disabled={loading}
        />
        <Button type="submit" disabled={loading || !input.trim()} className="bg-info hover:bg-info/90">
          {loading ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
        </Button>
      </form>
    </div>
  );
}
