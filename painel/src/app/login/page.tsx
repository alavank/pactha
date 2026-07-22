"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "@/lib/painel";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErro("");
    try {
      await login(email, senha);
      router.replace("/app");
    } catch {
      setErro("E-mail ou senha inválidos.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh bg-page grid place-items-center px-4">
      <div className="w-full max-w-[380px]">
        <div className="flex flex-col items-center mb-6">
          <div className="w-14 h-14 rounded-2xl bg-cta grid place-items-center mb-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/icons/icon.svg" alt="Painel" className="w-9 h-9" />
          </div>
          <h1 className="font-display font-extrabold text-2xl tracking-tight">Painel Executivo</h1>
          <p className="text-ink-3 text-sm mt-1">Entre com suas credenciais</p>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            placeholder="E-mail"
            autoComplete="username"
            className="bg-surface border border-line rounded-xl px-4 py-3 text-[15px] outline-none focus:border-accent-strong"
            required
          />
          <input
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            type="password"
            placeholder="Senha"
            autoComplete="current-password"
            className="bg-surface border border-line rounded-xl px-4 py-3 text-[15px] outline-none focus:border-accent-strong"
            required
          />
          {erro && <div className="text-crit text-[13px]">{erro}</div>}
          <button
            type="submit"
            disabled={busy}
            className="bg-cta text-cta-ink font-semibold rounded-xl py-3 mt-1 active:scale-[.99] transition-transform disabled:opacity-60"
          >
            {busy ? "Entrando…" : "Entrar"}
          </button>
        </form>
      </div>
    </div>
  );
}
