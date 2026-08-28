"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";
import { CLIENT_LOGO_CLASSE } from "@/components/bi/Marca";

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
      {/* Um brilho so, e discreto. Eram dois — violeta em cima e roxo embaixo —
          herdados do design "Base". A identidade do Painel nao tem gradiente
          nem cor de fundo: ela e cinza calmo com um acento que aparece pouco.
          Duas manchas coloridas na primeira tela do produto contradiziam tudo
          que vem depois do login. */}
      <div
        className="pointer-events-none absolute -top-56 left-1/2 h-[32rem] w-[44rem] -translate-x-1/2 rounded-full blur-3xl"
        style={{ background: "color-mix(in oklab, var(--bi-accent) 10%, transparent)" }}
      />
      <div className="bi-card relative w-full max-w-md p-6">
        <div className="flex flex-col items-center gap-2 pb-4 text-center">
          {/* Duas artes, uma por tema — a padrão tem a palavra em tinta preta e
              some sobre o cartão escuro (1,04 de contraste). Ver o comentário
              longo em dashboard/layout.tsx. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/pactha-logo.png" alt="PACTHA" className="marca-clara h-11 w-auto max-w-[210px] object-contain" />
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/pactha-logo-dark.png" alt="" aria-hidden="true" className="marca-escura h-11 w-auto max-w-[210px] object-contain" />
          <div className="leading-tight">
            <p className="text-[13px] font-semibold" style={{ color: "var(--bi-muted)" }}>Monitoramento</p>
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>Convênios · Emendas · Transferências</p>
          </div>
          {CLIENT_LOGO && (
            <div className="mt-1 flex flex-col items-center gap-1">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={CLIENT_LOGO} alt="Cliente" className={`h-14 w-auto max-w-[160px] object-contain ${CLIENT_LOGO_CLASSE}`} />
              {CLIENT_SUBTITLE && (
                <p className="text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>{CLIENT_SUBTITLE}</p>
              )}
            </div>
          )}
        </div>
        <div>
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label className="mb-1 block text-[12px] font-medium" style={{ color: "var(--bi-muted)" }}>Email</label>
              <Input
                type="email"
                placeholder="seu@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-[12px] font-medium" style={{ color: "var(--bi-muted)" }}>Senha</label>
              <Input
                type="password"
                placeholder="Sua senha"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {/* O botao preenchido da identidade e QUASE PRETO, nao colorido —
                e assim que o Painel faz (18.53 de contraste). */}
            <button
              type="submit"
              disabled={loading}
              className="h-10 w-full rounded-xl text-[13px] font-semibold transition-opacity disabled:opacity-60"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
            >
              {loading ? "Entrando..." : "Entrar"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
