"use client";
import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";
import { KeyRound, ShieldCheck } from "lucide-react";

function ChangePasswordInner() {
  const router = useRouter();
  const search = useSearchParams();
  const isFirstLogin = search.get("first") === "1";

  const [current, setCurrent] = useState("");
  const [next1, setNext1] = useState("");
  const [next2, setNext2] = useState("");
  const [loading, setLoading] = useState(false);

  const strength = (() => {
    if (!next1) return { score: 0, label: "" };
    let s = 0;
    if (next1.length >= 10) s++;
    if (/[a-z]/.test(next1) && /[A-Z]/.test(next1)) s++;
    if (/\d/.test(next1)) s++;
    if (/[^a-zA-Z0-9]/.test(next1)) s++;
    const labels = ["", "Fraca", "Razoavel", "Boa", "Forte"];
    return { score: s, label: labels[s] };
  })();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next1 !== next2) {
      toast.error("As senhas nao conferem");
      return;
    }
    if (next1.length < 10) {
      toast.error("Senha deve ter no minimo 10 caracteres");
      return;
    }
    setLoading(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next1,
      });
      toast.success("Senha alterada com sucesso");
      router.push("/dashboard");
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Erro ao alterar senha");
    } finally {
      setLoading(false);
    }
  }

  const rotulo = "mb-1 block text-[12px] font-medium";

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden bg-base-200 p-4">
      {/* O MESMO brilho único do Login, e pela mesma razão: eram duas manchas
          — uma violeta e outra da marca antiga — e esta tela abre logo depois
          do Login, então a diferença entre as duas era visível na sequência. */}
      <div
        className="pointer-events-none absolute -top-56 left-1/2 h-[32rem] w-[44rem] -translate-x-1/2 rounded-full blur-3xl"
        style={{ background: "color-mix(in oklab, var(--bi-accent) 10%, transparent)" }}
      />
      <div className="bi-card relative w-full max-w-md p-6">
        <div className="flex flex-col items-center gap-2 pb-4 text-center">
          <span
            className="grid size-12 place-items-center rounded-full"
            style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
          >
            <KeyRound className="size-5" />
          </span>
          <div className="bi-title text-[15px] leading-tight">
            {isFirstLogin ? "Trocar senha (primeiro acesso)" : "Trocar senha"}
          </div>
          {isFirstLogin && (
            <div
              role="alert"
              className="mt-1 w-full rounded-lg px-3 py-2 text-left text-[11px] leading-snug"
              style={{
                background: "color-mix(in oklab, var(--bi-warn) 12%, transparent)",
                color: "var(--bi-warn-ink)",
              }}
            >
              Você está usando uma senha temporária. Defina uma nova senha para continuar.
            </div>
          )}
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Senha atual</label>
            <Input
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </div>
          <div>
            <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Nova senha</label>
            <Input
              type="password"
              value={next1}
              onChange={(e) => setNext1(e.target.value)}
              minLength={10}
              required
            />
            {next1 && (
              <div className="mt-1.5 flex items-center gap-2 text-[10px]">
                <div className="flex flex-1 gap-1">
                  {[1, 2, 3, 4].map((i) => (
                    <div
                      key={i}
                      className="h-1 flex-1 rounded"
                      style={{
                        background:
                          i > strength.score ? "var(--bi-line)"
                          : strength.score >= 3 ? "var(--bi-ok)"
                          : "var(--bi-warn)",
                      }}
                    />
                  ))}
                </div>
                <span className="w-14" style={{ color: "var(--bi-muted)" }}>{strength.label}</span>
              </div>
            )}
            <p className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
              Mín. 10 caracteres. Use letras, números e símbolos.
            </p>
          </div>
          <div>
            <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Confirmar nova senha</label>
            <Input
              type="password"
              value={next2}
              onChange={(e) => setNext2(e.target.value)}
              required
            />
          </div>
          {/* Mesma CTA do Login: quase preta, não colorida. */}
          <button
            type="submit"
            disabled={loading}
            className="flex h-10 w-full items-center justify-center gap-2 rounded-xl text-[13px] font-semibold transition-opacity disabled:opacity-60"
            style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
          >
            <ShieldCheck className="size-4" />
            {loading ? "Alterando..." : "Alterar senha"}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function ChangePasswordPage() {
  return (
    <Suspense fallback={<div />}>
      <ChangePasswordInner />
    </Suspense>
  );
}
