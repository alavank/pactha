"use client";
import { useEffect, useState } from "react";
import { Sun, Moon } from "lucide-react";

// Alterna o tema (light padrão / dark opcional), persistindo em localStorage.
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    setDark(document.documentElement.getAttribute("data-theme") === "dark");
  }, []);

  function toggle() {
    const next = !dark;
    setDark(next);
    if (next) document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
    try {
      localStorage.setItem("painel_theme", next ? "dark" : "light");
    } catch {}
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={dark ? "Mudar para tema claro" : "Mudar para tema escuro"}
      className="w-[38px] h-[38px] rounded-xl bg-surface border border-line grid place-items-center text-ink-2 active:scale-95 transition-transform"
    >
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}
