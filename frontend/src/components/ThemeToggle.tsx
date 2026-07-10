"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

type Theme = "pactha" | "pactha-dark";

export function ThemeToggle({ className = "" }: { className?: string }) {
  const [theme, setTheme] = useState<Theme>("pactha");

  useEffect(() => {
    let saved: Theme = "pactha";
    try {
      const s = localStorage.getItem("pactha_theme");
      if (s === "pactha" || s === "pactha-dark") saved = s;
    } catch { /* ignore */ }
    setTheme(saved);
    document.documentElement.setAttribute("data-theme", saved);
  }, []);

  const toggle = () => {
    const next: Theme = theme === "pactha" ? "pactha-dark" : "pactha";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("pactha_theme", next); } catch { /* ignore */ }
  };

  const isDark = theme === "pactha-dark";
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={isDark ? "Mudar para tema claro" : "Mudar para tema escuro"}
      className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-xs font-medium text-base-content/70 hover:bg-base-200 hover:text-base-content transition-colors ${className}`}
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
      {isDark ? "Tema claro" : "Tema escuro"}
    </button>
  );
}
