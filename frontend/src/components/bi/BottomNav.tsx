"use client";
// Barra de navegacao inferior (mobile-first). O app operacional nao tem uma;
// o BI executivo ganha esta. Escopo/periodo vivem no contexto (localStorage),
// entao a navegacao entre abas preserva a selecao sem precisar de query string.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutGrid, Users, Bell, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/bi", label: "Visão", icon: LayoutGrid, exact: true },
  { href: "/bi/parlamentares", label: "Parlamentares", icon: Users },
  { href: "/bi/alertas", label: "Alertas", icon: Bell },
  { href: "/bi/config", label: "Ajustes", icon: Settings2 },
];

export function BottomNav() {
  const pathname = usePathname();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex border-t border-base-300 bg-base-100/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
      {TABS.map((t) => {
        const active = t.exact ? pathname === t.href : pathname.startsWith(t.href);
        const Icon = t.icon;
        return (
          <Link
            key={t.href}
            href={t.href}
            className={cn(
              "flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors",
              active ? "text-primary" : "text-base-content/50"
            )}
          >
            <Icon className="size-5" />
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
