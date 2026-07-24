"use client";
import { useEffect, useState } from "react";
import { Bell, Tv, Copy, Check, KeyRound } from "lucide-react";
import api from "@/lib/api";
import { User } from "@/types";
import { useBiScope, CONSOLIDADO } from "@/contexts/BiScopeContext";
import { getPrefs, putPrefs, Prefs, criarKioskToken } from "@/lib/bi";
import { Card, SectionHead, EmptyState } from "@/components/bi/ui";

const PREF_LABELS: { key: keyof Prefs; label: string }[] = [
  { key: "vigencia_60d", label: "Vigências vencendo em 60 dias" },
  { key: "prazo_prestacao", label: "Prestação de contas vencida" },
  { key: "cauc_vencendo", label: "Pendências de regularidade (CAUC)" },
  { key: "nova_emenda", label: "Nova emenda destinada" },
  { key: "mudanca_status", label: "Mudança de status de convênio" },
];

export default function BiConfigPage() {
  const { scope, municipioId } = useBiScope();
  const [user, setUser] = useState<User | null>(null);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [saving, setSaving] = useState(false);
  const [kioskUrl, setKioskUrl] = useState<string | null>(null);
  const [emitindo, setEmitindo] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.get<User>("/auth/me").then((r) => setUser(r.data)).catch(() => {});
    getPrefs().then(setPrefs).catch(() => setPrefs(null));
  }, []);

  const toggle = async (key: keyof Prefs) => {
    if (!prefs) return;
    const next = { ...prefs, [key]: !prefs[key] };
    setPrefs(next);
    setSaving(true);
    try {
      await putPrefs(next);
    } finally {
      setSaving(false);
    }
  };

  const gerarKiosk = async () => {
    setEmitindo(true);
    try {
      // scope consolidado -> token da carteira toda; municipio -> daquele municipio.
      // Codifica o escopo na URL p/ a TV num dispositivo novo (localStorage vazio)
      // abrir a visao certa — single mostra 1 municipio, nao "Consolidado · 1".
      const res = await criarKioskToken(scope === CONSOLIDADO ? null : municipioId);
      const base = typeof window !== "undefined" ? window.location.origin : "";
      const sc = res.municipio_id != null ? String(res.municipio_id) : "all";
      setKioskUrl(`${base}/bi/tv?kiosk=${res.token}&scope=${sc}`);
    } catch {
      setKioskUrl(null);
    } finally {
      setEmitindo(false);
    }
  };

  const isAdmin = user?.role === "admin";

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <Card>
        <SectionHead icon={Bell} title="Alertas e notificações" />
        {prefs ? (
          <div className="flex flex-col divide-y divide-base-200">
            {PREF_LABELS.map(({ key, label }) => (
              <label key={key} className="flex cursor-pointer items-center justify-between py-2.5">
                <span className="text-sm text-base-content/80">{label}</span>
                <input
                  type="checkbox"
                  className="toggle toggle-primary toggle-sm"
                  checked={!!prefs[key]}
                  onChange={() => toggle(key)}
                  disabled={saving}
                />
              </label>
            ))}
          </div>
        ) : (
          <EmptyState>Não foi possível carregar as preferências.</EmptyState>
        )}
      </Card>

      <Card>
        <SectionHead icon={Tv} title="Modo Gestão à Vista (TV)" />
        <p className="mb-3 text-sm text-base-content/70">
          Tela limpa de menus, 100% indicadores em tempo real, para projetar em monitores/sala de reunião.
        </p>
        <a
          href="/bi/tv"
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-primary-content hover:opacity-90"
        >
          <Tv className="size-4" /> Abrir modo TV
        </a>

        {isAdmin && (
          <div className="mt-4 border-t border-base-200 pt-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-base-content/60">
              <KeyRound className="size-3.5" /> Link permanente para TV sem login (quiosque)
            </div>
            <button
              onClick={gerarKiosk}
              disabled={emitindo}
              className="rounded-lg border border-base-300 px-3 py-1.5 text-xs font-medium hover:bg-base-200 disabled:opacity-50"
            >
              {emitindo ? "Gerando…" : "Gerar link do quiosque"}
            </button>
            {kioskUrl && (
              <div className="mt-2 flex items-center gap-2 rounded-lg bg-base-200 p-2">
                <code className="min-w-0 flex-1 truncate text-[11px] text-base-content/70">{kioskUrl}</code>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(kioskUrl);
                    setCopied(true);
                    setTimeout(() => setCopied(false), 1500);
                  }}
                  className="grid size-7 shrink-0 place-items-center rounded-md hover:bg-base-300"
                  title="Copiar"
                >
                  {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
                </button>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
