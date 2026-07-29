"use client";
// Ajustes do Painel de Indicadores. Fica FORA do fichário de abas de propósito:
// as abas são assunto de dado e rodam no slideshow da TV — configuração não
// deve aparecer numa TV de gabinete. Aqui vive o que existia em /bi/config:
// preferências de aviso e o link de quiosque (liga a TV sem login).
import { useEffect, useMemo, useState } from "react";
import { Bell, Check, Copy, KeyRound, Settings2, Trash2, Tv, X } from "lucide-react";
import api from "@/lib/api";
import type { User } from "@/types";
import {
  Prefs, TelaLink, criarTelaLink, getPrefs, listarTelaLinks, putPrefs,
  putTelaFiltros, revogarTelaLink,
} from "@/lib/bi";
import { allowedTelasOf } from "@/lib/telas";
import { CONSOLIDADO, useBiScope } from "@/contexts/BiScopeContext";

const PREF_LABELS: { key: keyof Prefs; label: string }[] = [
  { key: "vigencia_60d", label: "Vigências vencendo em 60 dias" },
  { key: "prazo_prestacao", label: "Prestação de contas vencida" },
  { key: "cauc_vencendo", label: "Pendências de regularidade (CAUC)" },
  { key: "nova_emenda", label: "Nova emenda destinada" },
  { key: "mudanca_status", label: "Mudança de status de convênio" },
];

export function BotaoAjustes() {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setAberto(true)}
        title="Ajustes do painel"
        aria-label="Ajustes do painel"
        className="grid size-9 place-items-center rounded-full"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
      >
        <Settings2 className="size-4" />
      </button>
      {aberto && <ModalAjustes onFechar={() => setAberto(false)} />}
    </>
  );
}

function ModalAjustes({ onFechar }: { onFechar: () => void }) {
  const { scope, anos } = useBiScope();
  const [user, setUser] = useState<User | null>(null);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [links, setLinks] = useState<TelaLink[]>([]);
  const [emitindo, setEmitindo] = useState(false);
  const [copiado, setCopiado] = useState<string | null>(null);

  const podeGerarLink = useMemo(() => {
    const t = allowedTelasOf(user);
    return !t || t.has("bi_link"); // null = admin
  }, [user]);

  useEffect(() => {
    api.get<User>("/auth/me").then((r) => setUser(r.data)).catch(() => {});
    getPrefs().then(setPrefs).catch(() => setPrefs(null));
    listarTelaLinks().then(setLinks).catch(() => setLinks([]));
  }, []);

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && onFechar();
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onFechar]);

  const alternar = async (key: keyof Prefs) => {
    if (!prefs) return;
    const proximo = { ...prefs, [key]: !prefs[key] };
    setPrefs(proximo);
    setSalvando(true);
    try {
      await putPrefs(proximo);
    } catch {
      setPrefs(prefs); // desfaz se o backend recusou
    } finally {
      setSalvando(false);
    }
  };

  const gerarLink = async () => {
    setEmitindo(true);
    try {
      // Publica o filtro ANTES de emitir. Sem isto o link nasce mostrando
      // "consolidado / todos os anos" e só passaria a refletir o período depois
      // que alguém mexesse no filtro de novo — que é exatamente o defeito que
      // esta tela existe para não ter.
      await putTelaFiltros({ scope: scope || CONSOLIDADO, anos, aba: null }).catch(() => {});
      const novo = await criarTelaLink();
      setLinks((L) => [novo, ...L]);
    } catch {
      /* silencio aqui = o botao volta ao normal; o link simplesmente nao entra */
    } finally {
      setEmitindo(false);
    }
  };

  const revogar = async (slug: string) => {
    try {
      await revogarTelaLink(slug);
      setLinks((L) => L.filter((l) => l.slug !== slug));
    } catch { /* mantem na lista se o backend recusou */ }
  };

  const urlDe = (l: TelaLink) =>
    `${typeof window !== "undefined" ? window.location.origin : ""}${l.caminho}`;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Ajustes do painel"
      onClick={(e) => e.target === e.currentTarget && onFechar()}
    >
      <div
        className="bi-scroll max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-3xl p-5"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
      >
        <div className="mb-4 flex items-center gap-2">
          <Settings2 className="size-4" style={{ color: "var(--bi-muted)" }} />
          <h2 className="bi-title text-[16px]">Ajustes do painel</h2>
          <button
            type="button"
            onClick={onFechar}
            className="ml-auto grid size-7 place-items-center rounded-lg"
            style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        <section className="mb-5">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
            <Bell className="size-4" style={{ color: "var(--bi-muted)" }} />
            Avisos que quero receber
          </div>
          {prefs ? (
            <ul className="flex flex-col gap-1">
              {PREF_LABELS.map((p) => (
                <li key={p.key}>
                  <label className="flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2" style={{ background: "var(--bi-surface-2)" }}>
                    <input
                      type="checkbox"
                      checked={!!prefs[p.key]}
                      onChange={() => alternar(p.key)}
                      disabled={salvando}
                      className="size-4 accent-[var(--bi-accent)]"
                    />
                    <span className="text-[12px]">{p.label}</span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px]" style={{ color: "var(--bi-faint)" }}>
              Não foi possível carregar as preferências.
            </p>
          )}
        </section>

        {podeGerarLink && (
          <section>
            <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
              <Tv className="size-4" style={{ color: "var(--bi-muted)" }} />
              Link público da TV
            </div>
            <p className="mb-2 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Abre o Modo Tela sem login e acompanha <strong>o seu</strong> filtro:
              mudou o período aqui, muda lá em até 10 segundos. Trate como senha —
              quem tiver o link vê os indicadores.
            </p>
            <button
              type="button"
              onClick={gerarLink}
              disabled={emitindo}
              className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[12px] font-semibold disabled:opacity-60"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
            >
              <KeyRound className="size-3.5" />
              {emitindo ? "Gerando…" : "Gerar link"}
            </button>

            {links.length > 0 && (
              <ul className="mt-2 space-y-1.5">
                {links.map((l) => (
                  <li
                    key={l.slug}
                    className="flex items-center gap-2 rounded-xl px-2.5 py-2"
                    style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}
                  >
                    <code className="min-w-0 flex-1 truncate text-[11px]">{urlDe(l)}</code>
                    <button
                      type="button"
                      onClick={() => {
                        void navigator.clipboard.writeText(urlDe(l));
                        setCopiado(l.slug);
                        setTimeout(() => setCopiado(null), 1800);
                      }}
                      className="grid size-7 shrink-0 place-items-center rounded-lg"
                      style={{ background: "var(--bi-surface)", color: "var(--bi-muted)" }}
                      aria-label="Copiar link"
                    >
                      {copiado === l.slug ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => void revogar(l.slug)}
                      className="grid size-7 shrink-0 place-items-center rounded-lg"
                      style={{ background: "var(--bi-surface)", color: "var(--bi-muted)" }}
                      aria-label="Revogar link"
                      title="Revogar link"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
