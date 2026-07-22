"use client";
import { useEffect, useState } from "react";
import { Bell, Moon, Smartphone } from "lucide-react";
import { Card } from "@/components/ui";
import { PageTitle, Switch, Loading } from "@/components/controls";
import { ThemeToggle } from "@/components/ThemeToggle";
import { getMunicipios, getPrefs, putPrefs, type Prefs } from "@/lib/painel";
import { ativarPush, precisaInstalarNoIOS, pushSuportado } from "@/lib/push";

const PREF_LABELS: { key: keyof Prefs; label: string; desc: string }[] = [
  { key: "cauc_vencendo", label: "Documentação (CAUC) mudou", desc: "Nova pendência que pode travar repasses" },
  { key: "nova_emenda", label: "Nova emenda / recurso", desc: "Quando um parlamentar destina verba" },
  { key: "prazo_prestacao", label: "Prazo de prestação de contas", desc: "Convênios vencidos ou perto de vencer" },
  { key: "vigencia_60d", label: "Convênio vencendo (60 dias)", desc: "Aviso antecipado de vigência" },
  { key: "mudanca_status", label: "Mudança de status", desc: "Quando um convênio avança de etapa" },
];

const PREFS_DEFAULT: Prefs = {
  cauc_vencendo: true, nova_emenda: true, prazo_prestacao: true, mudanca_status: true, vigencia_60d: true,
};

export default function ConfigPage() {
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [mid, setMid] = useState<number>(1);
  const [perm, setPerm] = useState<NotificationPermission>("default");
  const [iosHint, setIosHint] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const muns = await getMunicipios();
        setMid(muns[0]?.id ?? 1);
      } catch {}
      try {
        setPrefs(await getPrefs());
      } catch {
        setPrefs(PREFS_DEFAULT);
      }
      if (typeof Notification !== "undefined") setPerm(Notification.permission);
      setIosHint(precisaInstalarNoIOS());
    })();
  }, []);

  async function toggle(key: keyof Prefs) {
    if (!prefs) return;
    const next = { ...prefs, [key]: !prefs[key] };
    setPrefs(next);
    try {
      await putPrefs(next);
    } catch {}
  }

  async function habilitar() {
    setBusy(true);
    try {
      const p = await ativarPush(mid);
      setPerm(p);
    } finally {
      setBusy(false);
    }
  }

  if (!prefs) return <Loading />;

  return (
    <>
      <PageTitle title="Configurações" subtitle="Notificações e preferências" />
      <div className="flex flex-col gap-3.5">
        <Card>
          <div className="flex items-center gap-2.5 mb-1">
            <span className="w-9 h-9 rounded-xl bg-accent-soft grid place-items-center" style={{ color: "var(--accent-ink)" }}>
              <Bell size={18} />
            </span>
            <div>
              <div className="font-bold text-[15px]">Notificações no celular</div>
              <div className="text-[12px] text-ink-3">{perm === "granted" ? "Ativadas neste aparelho" : "Receba avisos importantes"}</div>
            </div>
          </div>

          {iosHint && (
            <div className="mt-2 flex items-start gap-2 text-[12px] text-ink-2 bg-surface-2 border border-line rounded-xl p-3">
              <Smartphone size={16} className="shrink-0 mt-0.5 text-accent-strong" />
              <span>No iPhone, toque em <b>Compartilhar → Adicionar à Tela de Início</b> e abra o app instalado para ativar as notificações.</span>
            </div>
          )}

          {perm !== "granted" && !iosHint && (
            <button
              onClick={habilitar}
              disabled={busy || !pushSuportado()}
              className="mt-2 w-full bg-cta text-cta-ink font-semibold text-[14px] rounded-xl py-3 active:scale-[.99] transition-transform disabled:opacity-60"
            >
              {busy ? "Ativando…" : "Ativar notificações"}
            </button>
          )}
          <p className="text-[11.5px] text-ink-3 mt-2">
            Os avisos automáticos começam quando o painel estiver publicado com as chaves de push configuradas.
          </p>
        </Card>

        <Card>
          <div className="font-bold text-[15px] mb-1">O que você quer receber</div>
          <div className="flex flex-col">
            {PREF_LABELS.map((p) => (
              <div key={p.key} className="flex items-center justify-between gap-3 py-3 border-t border-line first:border-t-0">
                <div>
                  <div className="text-[13.5px] font-semibold">{p.label}</div>
                  <div className="text-[12px] text-ink-3">{p.desc}</div>
                </div>
                <Switch checked={prefs[p.key]} onChange={() => toggle(p.key)} />
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="w-9 h-9 rounded-xl bg-surface-2 grid place-items-center text-ink-2">
                <Moon size={18} />
              </span>
              <div className="font-semibold text-[14px]">Tema escuro</div>
            </div>
            <ThemeToggle />
          </div>
        </Card>

        <div className="text-center text-[11.5px] text-ink-3 mt-1">Painel Executivo · PACTHA</div>
      </div>
    </>
  );
}
