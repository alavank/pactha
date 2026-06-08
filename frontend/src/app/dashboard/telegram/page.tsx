"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Send, Loader2, Copy, ExternalLink, CheckCircle2, XCircle, RefreshCw, Trash2,
} from "lucide-react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import toast from "react-hot-toast";

interface TelegramStatus {
  configured: boolean;
  bot?: { username?: string; first_name?: string; id?: number };
  webhook?: { url?: string; pending_update_count?: number; last_error_message?: string };
  message?: string;
  error?: string;
}

interface MyLink {
  chat_id: string;
  telegram_user?: string;
  municipio_nome?: string;
  vinculado_em?: string;
  ultima_atividade?: string;
}

interface LinkCode {
  codigo: string;
  expira_em: string;
  instrucoes: string;
  bot_username?: string;
  bot_link?: string;
}

export default function TelegramPage() {
  const [status, setStatus] = useState<TelegramStatus | null>(null);
  const [links, setLinks] = useState<MyLink[]>([]);
  const [linkCode, setLinkCode] = useState<LinkCode | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [secsLeft, setSecsLeft] = useState(0);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([
        api.get<TelegramStatus>("/telegram/status"),
        api.get<{ items: MyLink[] }>("/telegram/my-link"),
      ]);
      setStatus(s.data);
      setLinks(l.data.items || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar();
  }, [carregar]);

  // Contador regressivo do código
  useEffect(() => {
    if (!linkCode) return;
    const tick = () => {
      const diff = Math.max(0, Math.floor((new Date(linkCode.expira_em).getTime() - Date.now()) / 1000));
      setSecsLeft(diff);
      if (diff <= 0) setLinkCode(null);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [linkCode]);

  const gerarCodigo = async () => {
    setGenerating(true);
    try {
      const r = await api.post<LinkCode>("/telegram/link-code");
      setLinkCode(r.data);
      toast.success("Código gerado — válido por 10 minutos");
    } catch (e) {
      console.error(e);
      toast.error("Falha ao gerar código");
    } finally {
      setGenerating(false);
    }
  };

  const copiar = (txt: string) => {
    navigator.clipboard.writeText(txt);
    toast.success("Copiado!");
  };

  const desvincular = async (chatId: string) => {
    if (!confirm(`Desvincular este chat?\n\nVocê precisará gerar novo código e enviar /start no bot para vincular novamente.`)) return;
    try {
      await api.delete(`/telegram/my-link/${chatId}`);
      toast.success("Desvinculado");
      carregar();
    } catch (e) {
      console.error(e);
      toast.error("Falha ao desvincular");
    }
  };

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><Loader2 className="size-6 animate-spin text-blue-600" /></div>;
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* Header */}
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Send className="size-6 text-sky-500" />
          Integração Telegram
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Converse com a IA PACTA direto no Telegram. Pergunte sobre convênios, propostas,
          parlamentares, vigências — em português, com as mesmas ferramentas da IA PACTA web.
        </p>
      </div>

      {/* Status do bot */}
      <Card className={status?.configured ? "border-l-4 border-l-green-500" : "border-l-4 border-l-amber-500 bg-amber-50/40"}>
        <CardHeader>
          <CardTitle className="text-base flex items-center justify-between">
            <span>Status do bot</span>
            {status?.configured ? (
              <Badge className="bg-green-100 text-green-800 hover:bg-green-100">
                <CheckCircle2 className="size-3 mr-1" /> Configurado
              </Badge>
            ) : (
              <Badge className="bg-amber-100 text-amber-800 hover:bg-amber-100">
                <XCircle className="size-3 mr-1" /> Não configurado
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="text-sm space-y-2">
          {!status?.configured && (
            <div className="bg-amber-100 border border-amber-300 rounded p-3 text-xs space-y-2 text-amber-900">
              <strong>⚙️ O bot ainda não foi configurado pelo administrador.</strong>
              <p>Para ativar:</p>
              <ol className="list-decimal ml-5 space-y-1">
                <li>Crie um bot no Telegram com <a href="https://t.me/BotFather" target="_blank" rel="noopener" className="underline">@BotFather</a> — comando <code className="bg-white px-1">/newbot</code></li>
                <li>Copie o token retornado</li>
                <li>No Railway, adicione a env var <code className="bg-white px-1">TELEGRAM_BOT_TOKEN</code> com o token</li>
                <li>Reinicie o backend (redeploy do Railway)</li>
                <li>Como admin, abra o <a href="/api/docs" target="_blank" rel="noopener" className="underline">Swagger</a> e chame <code className="bg-white px-1">POST /api/telegram/setup-webhook</code> com a URL do backend</li>
              </ol>
            </div>
          )}
          {status?.configured && status.bot && (
            <div className="space-y-1">
              <div>
                Bot: <strong>{status.bot.first_name}</strong> ·{" "}
                <a
                  href={`https://t.me/${status.bot.username}`}
                  target="_blank"
                  rel="noopener"
                  className="text-sky-600 hover:underline inline-flex items-center gap-1"
                >
                  @{status.bot.username} <ExternalLink className="size-3" />
                </a>
              </div>
              {status.webhook?.url && (
                <div className="text-xs text-slate-500">
                  Webhook: <code className="bg-slate-100 px-1 rounded">{status.webhook.url}</code>
                  {status.webhook.last_error_message && (
                    <span className="ml-2 text-red-600">⚠️ {status.webhook.last_error_message}</span>
                  )}
                </div>
              )}
              {(status.webhook?.pending_update_count ?? 0) > 0 && (
                <div className="text-xs text-amber-600">
                  ⚠️ {status.webhook?.pending_update_count} updates pendentes
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Gerar código de vinculação */}
      {status?.configured && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Vincular seu Telegram à sua conta</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-slate-600">
              Gere um código de uso único (válido por 10 min), abra o bot no Telegram e envie:{" "}
              <code className="bg-slate-100 px-1.5 py-0.5 rounded">/start CODIGO</code>
            </p>

            {!linkCode && (
              <Button onClick={gerarCodigo} disabled={generating} className="bg-sky-600 hover:bg-sky-700">
                {generating ? <Loader2 className="size-4 animate-spin mr-1" /> : <RefreshCw className="size-4 mr-1" />}
                Gerar código de vinculação
              </Button>
            )}

            {linkCode && (
              <div className="space-y-3">
                <div className="bg-sky-50 border-2 border-dashed border-sky-300 rounded p-4 text-center">
                  <div className="text-xs text-sky-700 mb-1">Seu código (válido por {Math.floor(secsLeft / 60)}m {secsLeft % 60}s):</div>
                  <div className="text-4xl font-mono font-bold text-sky-900 tracking-widest">{linkCode.codigo}</div>
                  <button
                    onClick={() => copiar(linkCode.codigo)}
                    className="mt-2 text-xs text-sky-700 hover:underline inline-flex items-center gap-1"
                  >
                    <Copy className="size-3" /> Copiar
                  </button>
                </div>

                {linkCode.bot_link && (
                  <div className="flex flex-col items-center gap-2 pt-2">
                    <a
                      href={linkCode.bot_link}
                      target="_blank"
                      rel="noopener"
                      className="bg-sky-600 hover:bg-sky-700 text-white px-5 py-2.5 rounded-lg text-sm font-semibold inline-flex items-center gap-2"
                    >
                      <Send className="size-4" /> Abrir bot e vincular automaticamente
                    </a>
                    <div className="text-[11px] text-slate-500">
                      Ou abra manualmente: <strong>@{linkCode.bot_username}</strong> e envie <code className="bg-slate-100 px-1">/start {linkCode.codigo}</code>
                    </div>
                  </div>
                )}

                <Button variant="outline" size="sm" onClick={() => setLinkCode(null)} className="w-full">
                  Cancelar / Gerar outro
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Vinculações ativas */}
      {links.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Suas vinculações ativas ({links.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {links.map((l) => (
              <div key={l.chat_id} className="flex items-center justify-between gap-3 bg-slate-50 border rounded p-3 text-sm">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-slate-900">
                    {l.telegram_user || "(sem nome)"}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">
                    chat_id: <code className="bg-white px-1 rounded">{l.chat_id}</code>
                    {l.municipio_nome && <> · Município padrão: <strong>{l.municipio_nome}</strong></>}
                    {l.ultima_atividade && <> · Última atividade: {new Date(l.ultima_atividade).toLocaleString("pt-BR")}</>}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => desvincular(l.chat_id)}
                  className="text-red-600 hover:text-red-800 hover:bg-red-50"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Como usar */}
      {status?.configured && (
        <Card className="bg-slate-50/50">
          <CardHeader>
            <CardTitle className="text-base">Comandos disponíveis no bot</CardTitle>
          </CardHeader>
          <CardContent className="text-sm space-y-1 text-slate-700">
            <div><code className="bg-white px-1 rounded">/start CODIGO</code> — vincular conta</div>
            <div><code className="bg-white px-1 rounded">/help</code> — lista de comandos</div>
            <div><code className="bg-white px-1 rounded">/municipio NOME</code> — definir município padrão</div>
            <div><code className="bg-white px-1 rounded">/limpar</code> — apagar histórico de contexto</div>
            <div><code className="bg-white px-1 rounded">/desvincular</code> — desconectar conta</div>
            <div className="pt-2 text-xs text-slate-500">
              Fora dos comandos, qualquer mensagem é enviada à IA PACTA. Exemplos:
              <ul className="list-disc ml-5 mt-1 space-y-0.5">
                <li>&ldquo;Convênios vencendo em 60 dias&rdquo;</li>
                <li>&ldquo;Liste tudo do deputado Eduardo Azevedo&rdquo;</li>
                <li>&ldquo;Resumo do município hoje&rdquo;</li>
              </ul>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
