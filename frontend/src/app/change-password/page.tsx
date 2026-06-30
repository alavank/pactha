"use client";
import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#27272a] via-[#18181b] to-[#000000] p-4">
      <Card className="w-full max-w-md shadow-2xl border-0">
        <CardHeader className="text-center pb-2">
          <div className="mx-auto mb-3 w-14 h-14 bg-warning rounded-[var(--radius-box)] flex items-center justify-center">
            <KeyRound className="size-7 text-warning-content" />
          </div>
          <CardTitle className="text-xl font-bold">
            {isFirstLogin ? "Trocar senha (primeiro acesso)" : "Trocar senha"}
          </CardTitle>
          {isFirstLogin && (
            <div role="alert" className="alert alert-warning alert-soft mt-2 text-xs">
              <span>Voce esta usando uma senha temporaria. Defina uma nova senha para continuar.</span>
            </div>
          )}
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1 block">Senha atual</label>
              <Input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Nova senha</label>
              <Input
                type="password"
                value={next1}
                onChange={(e) => setNext1(e.target.value)}
                minLength={10}
                required
              />
              {next1 && (
                <div className="mt-1 flex items-center gap-2 text-xs">
                  <div className="flex gap-1 flex-1">
                    {[1, 2, 3, 4].map((i) => (
                      <div
                        key={i}
                        className={`h-1 flex-1 rounded ${
                          i <= strength.score
                            ? strength.score >= 3
                              ? "bg-success"
                              : "bg-warning"
                            : "bg-base-300"
                        }`}
                      />
                    ))}
                  </div>
                  <span className="text-base-content/60 w-16">{strength.label}</span>
                </div>
              )}
              <p className="text-xs text-base-content/50 mt-1">
                Min 10 caracteres. Use letras, numeros e simbolos.
              </p>
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Confirmar nova senha</label>
              <Input
                type="password"
                value={next2}
                onChange={(e) => setNext2(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              <ShieldCheck className="mr-2 size-4" />
              {loading ? "Alterando..." : "Alterar senha"}
            </Button>
          </form>
        </CardContent>
      </Card>
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
