"use client";
// Alternador claro/escuro no formato da referência: um par de pastilhas
// (sol | lua) em vez do botão com texto usado no sistema operacional.
// Escreve na MESMA chave do resto do app (pactha_theme), então a escolha vale
// para as duas janelas — inclusive a do Modo Tela, que costuma ficar no escuro.
import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Tema = "pactha" | "pactha-dark";

export function TemaBi({ className }: { className?: string }) {
  const [tema, setTema] = useState<Tema>("pactha");

  useEffect(() => {
    let salvo: Tema = "pactha";
    try {
      const s = localStorage.getItem("pactha_theme");
      if (s === "pactha" || s === "pactha-dark") salvo = s;
    } catch { /* storage bloqueado */ }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTema(salvo);
    document.documentElement.setAttribute("data-theme", salvo);
  }, []);

  const aplicar = (t: Tema) => {
    setTema(t);
    document.documentElement.setAttribute("data-theme", t);
    try { localStorage.setItem("pactha_theme", t); } catch { /* storage bloqueado */ }
  };

  const btn = (t: Tema, Icone: typeof Sun, rotulo: string) => {
    const ativo = tema === t;
    return (
      <button
        type="button"
        onClick={() => aplicar(t)}
        aria-label={rotulo}
        aria-pressed={ativo}
        title={rotulo}
        className="grid size-7 place-items-center rounded-full transition-colors"
        style={{
          background: ativo ? "var(--bi-cta)" : "transparent",
          color: ativo ? "var(--bi-cta-ink)" : "var(--bi-muted)",
        }}
      >
        <Icone className="size-3.5" />
      </button>
    );
  };

  return (
    <div
      className={`inline-flex items-center gap-0.5 rounded-full p-0.5 ${className ?? ""}`}
      style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
    >
      {btn("pactha", Sun, "Tema claro")}
      {btn("pactha-dark", Moon, "Tema escuro")}
    </div>
  );
}
