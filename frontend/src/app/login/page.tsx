"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import toast from "react-hot-toast";

// Config de marca por instância (build-time).
const CLIENT_LOGO = process.env.NEXT_PUBLIC_CLIENT_LOGO || "";
const CLIENT_SUBTITLE = process.env.NEXT_PUBLIC_CLIENT_SUBTITLE || "";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    // Auto-retry transparente em cold-start (502/503/504/network err).
    // NAO retry em 401 (senha errada real) nem 429 (rate limit).
    // Resolve o sintoma de "email ou senha incorretos" na primeira tentativa
    // quando o container Railway estava hibernando.
    const COLD_START_STATUS = new Set([0, 502, 503, 504]);
    let lastErr: unknown = null;
    for (let attempt = 1; attempt <= 3; attempt++) {
      try {
        const res = await api.post("/auth/login", { email, password }, {
          timeout: attempt === 1 ? 8000 : 30000,
        });
        localStorage.setItem("pactha_user", JSON.stringify(res.data.user));
        if (res.data.access_token) {
          localStorage.setItem("pactha_token", res.data.access_token);
        }
        toast.success(`Bem-vindo, ${res.data.user.name}!`);
        if (res.data.must_change_password) {
          router.push("/change-password?first=1");
        } else {
          router.push("/dashboard");
        }
        setLoading(false);
        return;
      } catch (e: unknown) {
        const err = e as { response?: { status?: number; data?: { detail?: string } }; code?: string };
        const status = err.response?.status ?? 0;
        const isColdStart = COLD_START_STATUS.has(status) || err.code === "ECONNABORTED" || err.code === "ERR_NETWORK";
        // 401 e 429 sao erros REAIS - nao retry
        if (status === 401 || status === 429) {
          if (status === 429) toast.error("Muitas tentativas. Aguarde 1 minuto.");
          else toast.error(err.response?.data?.detail || "Email ou senha incorretos");
          setLoading(false);
          return;
        }
        if (isColdStart && attempt < 3) {
          // Backoff: 500ms, 1500ms
          await new Promise(r => setTimeout(r, attempt * 500));
          continue;
        }
        lastErr = err;
      }
    }
    const err = lastErr as { response?: { data?: { detail?: string } } };
    toast.error(err?.response?.data?.detail || "Servidor indisponível. Tente novamente em 1 minuto.");
    setLoading(false);
  }

  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden bg-base-200 p-4">
      {/* brilho de marca (design "Base") */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[28rem] w-[40rem] -translate-x-1/2 rounded-full bg-primary/15 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-24 right-[-6rem] h-80 w-80 rounded-full bg-accent-purple/15 blur-3xl" />
      <Card className="relative w-full max-w-md border border-base-300/60 shadow-theme-lg">
        <CardHeader className="flex flex-col items-center gap-2 pb-2 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/pactha-logo.png" alt="PACTHA" className="h-11 w-auto max-w-[210px] object-contain" />
          <div className="leading-tight">
            <p className="text-sm font-semibold text-base-content/75">Monitoramento</p>
            <p className="text-xs text-base-content/50">Convênios | Emendas | Transferências</p>
          </div>
          {CLIENT_LOGO && (
            <div className="mt-1 flex flex-col items-center gap-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={CLIENT_LOGO} alt="Cliente" className="h-14 w-auto max-w-[160px] object-contain" />
              {CLIENT_SUBTITLE && (
                <p className="text-xs font-semibold text-base-content/60">{CLIENT_SUBTITLE}</p>
              )}
            </div>
          )}
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="text-sm font-medium mb-1 block">Email</label>
              <Input
                type="email"
                placeholder="seu@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="text-sm font-medium mb-1 block">Senha</label>
              <Input
                type="password"
                placeholder="Sua senha"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Entrando..." : "Entrar"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
