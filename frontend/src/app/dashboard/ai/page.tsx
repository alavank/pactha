"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { Send, Loader2, Sparkles, Wrench, User, Bot, Eraser, Square, Printer,
         History, Trash2, ChevronLeft, ChevronRight } from "lucide-react";
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

interface ConversaResumo {
  id: number;
  titulo: string;
  atualizado_em: string | null;
  criado_em: string | null;
}

// Sugestões propositalmente genéricas: não citam nome de parlamentar nem
// programa específico, que variam por município e levariam a resposta vazia.
const SUGESTOES_PROMPT = [
  "Resumo de tudo do município hoje.",
  "Quais convênios vencem nos próximos 60 dias?",
  "Quais parlamentares indicaram recursos para o município?",
  "Quais propostas estão aguardando análise?",
  "Quais propostas federais estão em cláusula suspensiva?",
  "Quais propostas do FNS existem e em que situação estão?",
];

export default function AiChatPage() {
  const { municipioId } = useMunicipio();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pdfIdx, setPdfIdx] = useState<number | null>(null);
  // Rotulo da consulta em andamento ("Consultando propostas do FNS...").
  const [etapa, setEtapa] = useState<string | null>(null);
  // Histórico do usuário logado
  const [conversas, setConversas] = useState<ConversaResumo[]>([]);
  const [conversaId, setConversaId] = useState<number | null>(null);
  const [historicoAberto, setHistoricoAberto] = useState(true);
  const [retencaoDias, setRetencaoDias] = useState(30);
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  // ---- Histórico (somente do usuário logado, retido por 30 dias) ----
  const carregarHistorico = useCallback(async () => {
    try {
      const r = await api.get<{ retencao_dias: number; conversas: ConversaResumo[] }>(
        "/ai/conversas");
      setConversas(r.data.conversas || []);
      setRetencaoDias(r.data.retencao_dias ?? 30);
    } catch {
      /* histórico é acessório: falhar aqui não pode quebrar o chat */
    }
  }, []);

  useEffect(() => { carregarHistorico(); }, [carregarHistorico]);

  const abrirConversa = async (id: number) => {
    try {
      const r = await api.get<{ mensagens: Message[] }>(`/ai/conversas/${id}`);
      setMessages(r.data.mensagens || []);
      setConversaId(id);
      setError(null);
    } catch {
      setError("Não foi possível abrir esta conversa.");
    }
  };

  const apagarConversa = async (id: number) => {
    try {
      await api.delete(`/ai/conversas/${id}`);
      setConversas((c) => c.filter((x) => x.id !== id));
      if (conversaId === id) { setMessages([]); setConversaId(null); }
    } catch {
      setError("Não foi possível apagar esta conversa.");
    }
  };

  const enviar = useCallback(
    async (msg: string) => {
      if (!msg.trim() || loading) return;
      setError(null);
      const userMsg: Message = { role: "user", content: msg.trim() };
      const next = [...messages, userMsg];
      setMessages(next);
      setInput("");
      setLoading(true);
      setEtapa(null);
      // Mensagem vazia do assistente: ela vai sendo preenchida ao vivo.
      setMessages([...next, { role: "assistant", content: "" }]);

      const ctrl = new AbortController();
      abortRef.current = ctrl;
      let acumulado = "";
      try {
        const token = localStorage.getItem("pactha_token");
        const res = await fetch(`${api.defaults.baseURL}/ai/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          credentials: "include",
          signal: ctrl.signal,
          body: JSON.stringify({
            message: msg.trim(),
            municipio_id: municipioId ? Number(municipioId) : null,
            history: messages.map((m) => ({ role: m.role, content: m.content })),
            conversa_id: conversaId,
          }),
        });
        if (!res.ok || !res.body) {
          let detalhe = "";
          try {
            const j = await res.json();
            detalhe = typeof j?.detail === "string" ? j.detail : "";
          } catch { /* corpo nao-JSON (ex.: erro de proxy) */ }
          throw new Error(detalhe || `HTTP ${res.status}`);
        }

        // Le o SSE manualmente: EventSource nao faz POST nem manda Authorization.
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let erroSse: string | null = null;

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // Eventos SSE sao separados por linha em branco.
          const blocos = buffer.split("\n\n");
          buffer = blocos.pop() ?? "";
          for (const bloco of blocos) {
            const linhaEvento = bloco.split("\n").find((l) => l.startsWith("event: "));
            const linhaDado = bloco.split("\n").find((l) => l.startsWith("data: "));
            if (!linhaEvento || !linhaDado) continue;
            const evento = linhaEvento.slice(7).trim();
            let dado: Record<string, unknown>;
            try {
              dado = JSON.parse(linhaDado.slice(6));
            } catch {
              continue;
            }
            if (evento === "etapa") {
              setEtapa(String(dado.rotulo ?? ""));
            } else if (evento === "texto") {
              setEtapa(null);
              acumulado += String(dado.t ?? "");
              setMessages((atual) => {
                const copia = [...atual];
                const ultimo = copia[copia.length - 1];
                if (ultimo?.role === "assistant") {
                  copia[copia.length - 1] = { ...ultimo, content: acumulado };
                }
                return copia;
              });
            } else if (evento === "fim") {
              const tc = dado.tool_calls as ToolCallLog[] | undefined;
              const us = dado.usage as Record<string, unknown> | undefined;
              if (typeof dado.conversa_id === "number") setConversaId(dado.conversa_id);
              // `reply` do servidor e a verdade final; o acumulado pode conter
              // texto de passos intermediarios.
              const textoFinal = String(dado.reply ?? "") || acumulado;
              setMessages((atual) => {
                const copia = [...atual];
                const ultimo = copia[copia.length - 1];
                if (ultimo?.role === "assistant") {
                  copia[copia.length - 1] = {
                    ...ultimo, content: textoFinal, tool_calls: tc, usage: us,
                  };
                }
                return copia;
              });
            } else if (evento === "erro") {
              erroSse = String(dado.detail ?? "Erro na IA.");
            }
          }
        }
        if (erroSse) throw new Error(erroSse);
      } catch (e: unknown) {
        const err = e as { name?: string; message?: string };
        if (err.name === "AbortError") {
          // Cancelado de proposito: mantem o que ja apareceu na tela.
          setMessages((atual) => {
            const copia = [...atual];
            const ultimo = copia[copia.length - 1];
            if (ultimo?.role === "assistant" && !ultimo.content) copia.pop();
            return copia;
          });
        } else {
          console.error("AI chat error", err);
          setError(err.message || "Erro ao chamar a IA.");
          // Remove a bolha vazia para o erro nao ficar orfao.
          setMessages((atual) => {
            const copia = [...atual];
            const ultimo = copia[copia.length - 1];
            if (ultimo?.role === "assistant" && !ultimo.content) copia.pop();
            return copia;
          });
        }
      } finally {
        abortRef.current = null;
        setEtapa(null);
        setLoading(false);
        carregarHistorico();  // titulo/ordem do painel acompanham a conversa
      }
    },
    [messages, loading, municipioId, conversaId, carregarHistorico]
  );

  // Para a geracao (e para de gastar token) quando o usuario desiste.
  const parar = useCallback(() => abortRef.current?.abort(), []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    enviar(input);
  };

  const limpar = () => {
    setMessages([]);
    setError(null);
  };

  // Exporta uma resposta da IA (markdown) em PDF. Usa a pergunta anterior como contexto.
  // Gera um RELATÓRIO daquele resultado (não a transcrição da conversa): o
  // assunto vem da pergunta, e as fontes vêm das consultas que a IA realmente
  // fez, que viram a seção de procedência do documento.
  const gerarRelatorio = async (msg: Message, idx: number) => {
    setPdfIdx(idx);
    try {
      const pergunta = idx > 0 && messages[idx - 1]?.role === "user" ? messages[idx - 1].content : "";
      const token = localStorage.getItem("pactha_token");
      const res = await fetch(`${api.defaults.baseURL}/export-pdf/ai-relatorio`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify({
          assunto: pergunta || "Relatório da plataforma PACTHA",
          conteudo: msg.content,
          municipio_id: municipioId ? Number(municipioId) : null,
          tools: (msg.tool_calls || []).map((t) => t.tool),
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setError("Não foi possível gerar o relatório. Tente novamente.");
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
        h2: (props) => <h2 className="mt-4 mb-2 border-b pb-1 text-[15px] font-bold" style={{ borderColor: "var(--bi-line)", color: "var(--bi-text)" }} {...props} />,
        h3: (props) => <h3 className="text-base font-bold mt-3 mb-1 text-base-content" {...props} />,
        h4: (props) => <h4 className="text-sm font-bold mt-2 mb-1 text-base-content/70" {...props} />,
        p: (props) => <p className="leading-relaxed my-2" {...props} />,
        ul: (props) => <ul className="list-disc ml-5 my-2 space-y-1" {...props} />,
        ol: (props) => <ol className="list-decimal ml-5 my-2 space-y-1" {...props} />,
        li: (props) => <li className="leading-snug" {...props} />,
        strong: (props) => <strong className="font-semibold text-base-content" {...props} />,
        em: (props) => <em className="italic text-base-content/70" {...props} />,
        code: (props) => (
          <code className="rounded px-1.5 py-0.5 font-mono text-[12px]" style={{ background: "var(--bi-surface-2)", color: "var(--bi-text)" }} {...props} />
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
        thead: (props) => <thead className="text-[10px] uppercase tracking-wide" style={{ background: "var(--bi-surface-2)", color: "var(--bi-faint)" }} {...props} />,
        th: (props) => (
          <th className="text-left font-semibold px-3 py-1.5 border-b border-base-300" {...props} />
        ),
        td: (props) => <td className="px-3 py-1.5 border-b border-base-300 align-top" {...props} />,
        tr: (props) => <tr className="even:bg-base-200/50" {...props} />,
        a: (props) => (
          <a className="underline" style={{ color: "var(--bi-accent-ink)" }} target="_blank" rel="noopener" {...props} />
        ),
        hr: () => <hr className="my-3 border-base-300" />,
      }}
    >
      {text}
    </ReactMarkdown>
  );

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um município.</div>;
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-7rem)] max-w-7xl mx-auto">
    <div className="flex flex-col flex-1 min-w-0">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 pb-3 border-b">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <Sparkles className="size-6" style={{ color: "var(--bi-muted)" }} /> IA PACTHA
          </h1>
          <p className="text-sm text-base-content/60">
            Assistente que consulta o banco em tempo real e gera relatórios. Pergunte em português.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {messages.length > 0 && (
            <Button variant="outline" size="sm" onClick={limpar}>
              <Eraser className="size-4 mr-1" /> Nova conversa
            </Button>
          )}
          {/* Botao de mostrar/esconder o historico (fica a DIREITA porque a
              esquerda ja e o menu do sistema). */}
          <Button variant="outline" size="sm" onClick={() => setHistoricoAberto((v) => !v)}
                  title={historicoAberto ? "Esconder histórico" : "Mostrar histórico"}>
            <History className="size-4 mr-1" />
            {historicoAberto ? <ChevronRight className="size-4" /> : <ChevronLeft className="size-4" />}
          </Button>
        </div>
      </div>

      {/* Mensagens */}
      <div className="flex-1 overflow-y-auto py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-8">
            <Sparkles className="mx-auto mb-3 size-12" style={{ color: "var(--bi-faint)" }} />
            <p className="text-base-content/70 mb-4">Sugestões para começar:</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-w-2xl mx-auto">
              {SUGESTOES_PROMPT.map((s, i) => (
                <button
                  key={i}
                  onClick={() => enviar(s)}
                  className="rounded-xl px-3 py-2 text-left text-[12px] transition-colors bi-hover"
                  style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
                >
                  <Sparkles className="mr-1 inline size-3.5" style={{ color: "var(--bi-faint)" }} />
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && (
              <div className="grid size-8 shrink-0 place-items-center rounded-full" style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}>
                <Bot className="size-5" />
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
                    ? "bi-bolha-eu"
                    : "bg-base-100 border border-base-300 text-base-content"
                }`}
              >
                {m.role === "user" ? (
                  <div className="whitespace-pre-wrap">{m.content}</div>
                ) : (
                  <div className="text-[13px] leading-relaxed">
                    {renderContent(m.content)}
                    {/* Cursor piscando enquanto o texto ainda esta chegando. */}
                    {loading && i === messages.length - 1 && (
                      <span className="ml-0.5 inline-block h-[1em] w-[2px] animate-pulse align-[-0.15em]" style={{ background: "var(--bi-accent)" }} />
                    )}
                  </div>
                )}
              </div>
              {m.usage && m.role === "assistant" && (
                <div className="text-[10px] text-base-content/40 mt-1">
                  {String(m.usage.input_tokens)} in / {String(m.usage.output_tokens)} out tokens
                  {Number(m.usage.cache_read) > 0 && ` · cache hit ${m.usage.cache_read}`}
                </div>
              )}
              {/* Oferta de RELATORIO: aparece so quando a resposta terminou
                  (nao durante o streaming) e gera um documento daquele
                  resultado — nao a transcricao da conversa. */}
              {m.role === "assistant" && m.content && !(loading && i === messages.length - 1) && (
                <div className="mt-2 flex items-center gap-2 rounded-lg border border-base-300 bg-base-200/50 px-3 py-2">
                  <span className="text-xs text-base-content/70">
                    Quer um relatório em PDF deste resultado?
                  </span>
                  <button
                    onClick={() => gerarRelatorio(m, i)}
                    disabled={pdfIdx === i}
                    title="Gerar relatório em PDF deste resultado"
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors bi-hover disabled:opacity-60"
                    style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
                  >
                    {pdfIdx === i
                      ? <Loader2 className="size-3.5 animate-spin" />
                      : <Printer className="size-3.5" />}
                    {pdfIdx === i ? "Gerando..." : "Gerar relatório"}
                  </button>
                </div>
              )}
            </div>
            {m.role === "user" && (
              <div className="grid size-8 shrink-0 place-items-center rounded-full" style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}>
                <User className="size-5" />
              </div>
            )}
          </div>
        ))}
        {/* Enquanto nao chegou nenhum texto, mostramos a etapa REAL em curso
            (o nome vem da ferramenta que o servidor esta executando agora). */}
        {loading && !messages[messages.length - 1]?.content && (
          <div className="flex gap-3">
            <div className="grid size-8 shrink-0 place-items-center rounded-full" style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}>
              <Bot className="size-5" />
            </div>
            <div className="bg-base-100 border border-base-300 rounded-lg px-3.5 py-2.5 text-sm flex items-center gap-2 text-base-content/60">
              <Loader2 className="size-4 animate-spin" />
              {etapa || "Analisando a pergunta..."}
            </div>
          </div>
        )}
        {error && (
          <div className="rounded-lg px-3 py-2 text-[12px]" style={{ background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)", color: "var(--bi-crit-ink)" }}>
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
          className="bi-field flex-1 px-3 py-2.5 text-sm"
          disabled={loading}
        />
        {loading ? (
          <Button type="button" onClick={parar} variant="outline"
                  title="Parar a geração (interrompe também o consumo de tokens)">
            <Square className="size-4" /> Parar
          </Button>
        ) : (
          <Button type="submit" disabled={!input.trim()} className="border-0" style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}>
            <Send className="size-4" />
          </Button>
        )}
      </form>
    </div>

    {/* Histórico — à DIREITA de propósito: a esquerda já é o menu do sistema,
        e dois painéis do mesmo lado confundiriam a navegação. */}
    {historicoAberto && (
      <aside className="hidden lg:flex w-72 shrink-0 flex-col border-l border-base-300 pl-4">
        <div className="pb-2 border-b">
          <h2 className="text-sm font-semibold text-base-content flex items-center gap-1.5">
            <History className="size-4" style={{ color: "var(--bi-muted)" }} /> Minhas conversas
          </h2>
          {/* O aviso fica ACIMA da lista, como pedido. */}
          <p className="mt-1.5 rounded-lg px-2 py-1.5 text-[11px] leading-snug"
             style={{ background: "color-mix(in oklab, var(--bi-warn) 12%, transparent)", color: "var(--bi-warn-ink)" }}>
            As conversas ficam guardadas por no máximo <strong>{retencaoDias} dias</strong> e
            depois são <strong>excluídas definitivamente</strong>. Só você vê o seu histórico.
          </p>
        </div>

        <div className="flex-1 overflow-y-auto py-2 space-y-1">
          {conversas.length === 0 && (
            <p className="text-xs text-base-content/40 px-1 py-4 text-center">
              Nenhuma conversa ainda.
            </p>
          )}
          {conversas.map((c) => (
            <div
              key={c.id}
              className={`group flex items-start gap-1 rounded-md px-2 py-1.5 text-xs cursor-pointer hover:bg-base-200 ${
                conversaId === c.id ? "bi-conversa-ativa" : ""
              }`}
              onClick={() => abrirConversa(c.id)}
            >
              <div className="flex-1 min-w-0">
                <div className="truncate text-base-content">{c.titulo}</div>
                <div className="text-[10px] text-base-content/40">
                  {c.atualizado_em
                    ? new Date(c.atualizado_em).toLocaleDateString("pt-BR", {
                        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
                      })
                    : ""}
                </div>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); apagarConversa(c.id); }}
                title="Apagar esta conversa"
                className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100" style={{ color: "var(--bi-crit-ink)" }}
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          ))}
        </div>
      </aside>
    )}
    </div>
  );
}
