"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import toast from "react-hot-toast";

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
        localStorage.setItem("pacta_user", JSON.stringify(res.data.user));
        if (res.data.access_token) {
          localStorage.setItem("pacta_token", res.data.access_token);
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
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-900 via-blue-800 to-indigo-900 p-4">
      <Card className="w-full max-w-md shadow-2xl border-0">
        <CardHeader className="text-center pb-2">
          <div className="mx-auto mb-4 w-16 h-16 bg-blue-600 rounded-xl flex items-center justify-center">
            <span className="text-white text-2xl font-bold">P</span>
          </div>
          <CardTitle className="text-2xl font-bold">PACTA</CardTitle>
          <p className="text-sm text-muted-foreground mt-1">
            Monitoramento de Convenios e Transferencias
          </p>
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
