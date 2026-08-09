"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Send, Loader2, Copy, ExternalLink, RefreshCw, Trash2,
  Link2, Terminal,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio,
} from "@/components/ui/superficies";
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

/** Os comandos do bot em dado, não em markup: a lista repetia cinco vezes a
 *  mesma estrutura de `<div><code>…</code> — texto</div>`, e a cada comando novo
 *  no backend alguém tinha que copiar a linha inteira certinha. */
const COMANDOS: { cmd: string; desc: string }[] = [
  { cmd: "/start CODIGO", desc: "Vincular esta conta ao seu usuário do PACTHA" },
  { cmd: "/help", desc: "Lista de comandos disponíveis" },
  { cmd: "/municipio NOME", desc: "Definir o município padrão das respostas" },
  { cmd: "/limpar", desc: "Apagar o histórico de contexto da conversa" },
  { cmd: "/desvincular", desc: "Desconectar a conta deste chat" },
];

/** `code` inline com o cinza da identidade. Usa `--bi-line` (o mesmo fundo do
 *  selo neutro) e não `--bi-surface-2`, porque metade destes trechos vive dentro
 *  de um `bi-card-flat` — que JÁ é surface-2, e ali o chip sumiria. */
function Cod({ children }: { children: React.ReactNode }) {
  return (
    <code
      className="rounded px-1 py-px font-mono text-[11px]"
      style={{ background: "var(--bi-line)", color: "var(--bi-text)" }}
    >
      {children}
    </code>
  );
}

function Externo({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener"
      className="underline underline-offset-2"
      style={{ color: "var(--bi-accent-ink)" }}
    >
      {children}
    </a>
  );
}

function fmtDataHora(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  // Data que o backend mandou fora do ISO não vira "Invalid Date" na tela: o
  // texto cru diz mais ao suporte do que o erro do parser.
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
}

export default function TelegramPage() {
  // Desativado até segunda ordem (ver lib/telas.ts). O gate fica AQUI, antes
  // do componente com hooks, para acesso por URL direta também morrer.
  if (process.env.NEXT_PUBLIC_TELEGRAM_MODULE !== "1") {
    return (
      <div className="p-6 text-sm" style={{ color: "var(--bi-muted)" }}>
        Recurso indisponível.
      </div>
    );
  }
  return <TelegramPageInner />;
}

function TelegramPageInner() {
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
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
      </div>
    );
  }

  const pendentes = status?.webhook?.pending_update_count ?? 0;
  const erroWebhook = status?.webhook?.last_error_message;

  return (
    <div className="max-w-4xl space-y-4">
      {/* Header */}
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="text-2xl font-bold text-base-content">Integração Telegram</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Converse com a IA PACTHA direto no Telegram. Pergunte sobre convênios, propostas,
          parlamentares, vigências — em português, com as mesmas ferramentas da IA PACTHA web.
        </p>
      </div>

      {/* ---------------- Status do bot ---------------- */}
      <Bloco className="p-3">
        <BlocoHead
          icon={Send}
          titulo="Status do bot"
          sub={
            status?.configured && status.bot ? (
              <span className="flex flex-wrap items-center gap-1.5">
                <strong style={{ color: "var(--bi-text)" }}>{status.bot.first_name}</strong>
                {status.bot.username && (
                  <Externo href={`https://t.me/${status.bot.username}`}>
                    <span className="inline-flex items-center gap-1">
                      @{status.bot.username} <ExternalLink className="size-3" />
                    </span>
                  </Externo>
                )}
              </span>
            ) : (
              "O bot precisa ser ligado pelo administrador antes de qualquer vinculação."
            )
          }
          right={
            /* Configurado é o estado NORMAL do sistema, então fica cinza — cor
               aqui só quando há algo a resolver. Não passa por `situacaoTom`
               porque isto não é rótulo de situação vindo dos dados: é um
               booleano do backend, e forçá-lo pela regra de texto daria neutro
               nos dois casos, apagando justamente o aviso. */
            /* Sem ícone dentro do selo: o ✔/✘ só repetia a palavra ao lado e é
               a mesma decoração que Sessões e CAUC tiraram dos seus selos. Selo
               com ícone em uma tela e sem ícone na vizinha é o tipo de diferença
               que reaparece multiplicada em seis meses. */
            status?.configured ? (
              <Selo title="Token cadastrado e bot respondendo">Configurado</Selo>
            ) : (
              <Selo tom="atencao" title="Falta cadastrar o TELEGRAM_BOT_TOKEN no backend">
                Não configurado
              </Selo>
            )
          }
        />

        {/* A resposta do /status trazia `message` e `error` que a tela antiga
            nunca mostrava: quando o bot não sobe, é exatamente aqui que está o
            motivo. */}
        {status?.error && (
          <p className="flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            <Selo tom="critico">Erro</Selo>
            {status.error}
          </p>
        )}
        {status?.message && !status.configured && (
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{status.message}</p>
        )}

        {status?.configured && (
          /* Os dados do bot em posição FIXA: webhook, pendências e último erro
             eram linhas que só apareciam quando havia problema, então quem
             abria a tela no dia bom não aprendia onde olhar no dia ruim. */
          <Campos
            cols={3}
            campos={[
              { rotulo: "Bot", valor: status.bot?.first_name || "—", title: status.bot?.first_name },
              { rotulo: "Usuário", valor: status.bot?.username ? `@${status.bot.username}` : "—" },
              { rotulo: "ID do bot", valor: status.bot?.id ?? "—" },
              {
                rotulo: "Webhook",
                valor: status.webhook?.url || "não registrado",
                tom: status.webhook?.url ? "normal" : "atencao",
                title: status.webhook?.url || "Sem webhook: o bot não recebe mensagens.",
              },
              {
                rotulo: "Updates pendentes",
                valor: pendentes,
                tom: pendentes > 0 ? "atencao" : "normal",
                title: pendentes > 0
                  ? "Mensagens que o Telegram tentou entregar e ainda não foram processadas."
                  : undefined,
              },
              {
                rotulo: "Último erro do webhook",
                valor: erroWebhook || "—",
                tom: erroWebhook ? "critico" : "normal",
                title: erroWebhook,
              },
            ]}
          />
        )}

        {!status?.configured && (
          <div className="mt-2 border-t pt-2 text-[12px] leading-relaxed" style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}>
            <div className="font-medium" style={{ color: "var(--bi-text)" }}>Para ativar (administrador):</div>
            <ol className="mt-1.5 list-decimal space-y-1 pl-5">
              <li>
                Crie um bot no Telegram com <Externo href="https://t.me/BotFather">@BotFather</Externo>
                {" "}— comando <Cod>/newbot</Cod>
              </li>
              <li>Copie o token retornado</li>
              <li>No Coolify (resource API), adicione a env var <Cod>TELEGRAM_BOT_TOKEN</Cod> com o token</li>
              <li>Reinicie o backend (redeploy no Coolify)</li>
              <li>
                Como admin, abra o <Externo href="/api/docs">Swagger</Externo> e chame{" "}
                <Cod>POST /api/telegram/setup-webhook</Cod> com a URL do backend
              </li>
            </ol>
          </div>
        )}
      </Bloco>

      {/* ---------------- Vincular ---------------- */}
      {status?.configured && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Link2}
            titulo="Vincular seu Telegram à sua conta"
            sub={
              <>
                Gere um código de uso único (válido por 10 min), abra o bot no Telegram e envie{" "}
                <Cod>/start CODIGO</Cod>
              </>
            }
          />

          {!linkCode && (
            <div>
              <Button
                onClick={gerarCodigo}
                disabled={generating}
                size="sm"
                style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                className="hover:opacity-90"
              >
                {generating ? <Loader2 className="mr-1 size-4 animate-spin" /> : <RefreshCw className="mr-1 size-4" />}
                Gerar código de vinculação
              </Button>
            </div>
          )}

          {linkCode && (
            <div className="flex flex-col gap-3">
              {/* O código é o único número desta tela, então ele — e não uma
                  moldura pontilhada colorida — é o que salta. Quem avisa que
                  está acabando é o selo, que só ganha cor no último minuto. */}
              <div className="bi-card-flat flex flex-col items-center gap-2 px-4 py-5">
                <div className="flex items-center gap-2">
                  <span className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                    Seu código
                  </span>
                  <Selo
                    tom={secsLeft <= 60 ? "atencao" : "neutro"}
                    title="Depois disso o código deixa de valer e é preciso gerar outro"
                  >
                    expira em {Math.floor(secsLeft / 60)}m {secsLeft % 60}s
                  </Selo>
                </div>
                {/* 22px é o tamanho do <Numero>, o maior número do sistema.
                    Um 32px só aqui abriria um sétimo degrau de escala numa
                    identidade que tem seis.
                    O que estava escrito aqui — "com tracking-widest e font-mono"
                    — não acontecia: `.bi-num` declara `letter-spacing:-.02em` e
                    vence o `.tracking-widest` por ordem na mesma camada, então o
                    código saía CONDENSADO (medido: -0,44px em vez de +2,2px). E
                    `font-mono` aponta para Nunito neste projeto. Agora é `.bi-id`
                    (monoespaçada de verdade) e o espaçamento vai inline, que
                    ganha da camada. */}
                <div
                  className="bi-id text-[22px] font-bold leading-none"
                  style={{ color: "var(--bi-text)", letterSpacing: "0.12em" }}
                >
                  {linkCode.codigo}
                </div>
                <button
                  type="button"
                  onClick={() => copiar(linkCode.codigo)}
                  className="inline-flex items-center gap-1 text-[11px] hover:underline"
                  style={{ color: "var(--bi-muted)" }}
                >
                  <Copy className="size-3" /> Copiar
                </button>
              </div>

              {/* O `instrucoes` do backend diz a MESMA coisa que o rodapé do
                  botão abaixo, então só entra quando não há `bot_link` — que é
                  justamente quando o backend não descobriu o @ do bot e o
                  rodapé não aparece, deixando o usuário sem instrução nenhuma. */}
              {!linkCode.bot_link && linkCode.instrucoes && (
                <p className="whitespace-pre-line text-center text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                  {linkCode.instrucoes}
                </p>
              )}

              {linkCode.bot_link && (
                <div className="flex flex-col items-center gap-2">
                  <a
                    href={linkCode.bot_link}
                    target="_blank"
                    rel="noopener"
                    className="inline-flex items-center gap-2 rounded-md px-5 py-2.5 text-[13px] font-semibold transition-opacity hover:opacity-90"
                    style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                  >
                    <Send className="size-4" /> Abrir bot e vincular automaticamente
                  </a>
                  <div className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                    Ou abra manualmente: <strong>@{linkCode.bot_username}</strong> e envie{" "}
                    <Cod>/start {linkCode.codigo}</Cod>
                  </div>
                </div>
              )}

              <Button variant="outline" size="sm" onClick={() => setLinkCode(null)} className="w-full">
                Cancelar / Gerar outro
              </Button>
            </div>
          )}
        </Bloco>
      )}

      {/* ---------------- Vinculações ativas ---------------- */}
      {(status?.configured || links.length > 0) && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Link2}
            titulo="Suas vinculações ativas"
            sub="Cada chat do Telegram que já pode conversar com a IA usando o seu acesso"
            right={<span className="bi-num text-[13px]">{links.length}</span>}
          />
          {links.length === 0 ? (
            <Vazio>Nenhum chat vinculado. Gere um código acima e envie /start no bot.</Vazio>
          ) : (
            <Lista>
              {links.map((l) => (
                <ItemLinha
                  key={l.chat_id}
                  titulo={l.telegram_user || "(sem nome)"}
                  meta={<span className="font-mono">chat_id {l.chat_id}</span>}
                  acao={
                    <button
                      type="button"
                      onClick={() => desvincular(l.chat_id)}
                      title="Desvincular este chat"
                      aria-label={`Desvincular ${l.telegram_user || l.chat_id}`}
                      /* Cinza parado, vermelho só sob o cursor: um lixo pintado
                         de vermelho em cada linha faz a tela parecer cheia de
                         alertas quando não há nenhum. */
                      className="rounded p-1.5 text-[var(--bi-faint)] transition-colors hover:bg-[var(--bi-line)] hover:text-[var(--bi-crit-ink)]"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  }
                >
                  <Campos
                    cols={3}
                    campos={[
                      {
                        rotulo: "Município padrão",
                        valor: l.municipio_nome || "—",
                        title: l.municipio_nome,
                      },
                      { rotulo: "Vinculado em", valor: fmtDataHora(l.vinculado_em) },
                      { rotulo: "Última atividade", valor: fmtDataHora(l.ultima_atividade) },
                    ]}
                  />
                </ItemLinha>
              ))}
            </Lista>
          )}
        </Bloco>
      )}

      {/* ---------------- Comandos ---------------- */}
      {status?.configured && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Terminal}
            titulo="Comandos disponíveis no bot"
            sub="Fora destes comandos, qualquer mensagem vai direto para a IA PACTHA"
          />
          <Lista>
            {COMANDOS.map((c) => (
              <ItemLinha key={c.cmd} titulo={<span className="font-mono">{c.cmd}</span>} meta={c.desc} />
            ))}
          </Lista>
          <div className="mt-2 border-t pt-2 text-[11px] leading-snug" style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}>
            Exemplos de pergunta:
            <ul className="mt-1 list-disc space-y-0.5 pl-5" style={{ color: "var(--bi-faint)" }}>
              <li>&ldquo;Convênios vencendo em 60 dias&rdquo;</li>
              <li>&ldquo;Liste tudo do deputado Eduardo Azevedo&rdquo;</li>
              <li>&ldquo;Resumo do município hoje&rdquo;</li>
            </ul>
          </div>
        </Bloco>
      )}
    </div>
  );
}
