"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Bell, Users, Settings } from "lucide-react";
import { cn } from "./ui";

const TABS = [
  { href: "/app", label: "Panorama", icon: Home },
  { href: "/app/alertas", label: "Alertas", icon: Bell },
  { href: "/app/parlamentares", label: "Parlam.", icon: Users },
  { href: "/app/config", label: "Config", icon: Settings },
];

export function TabBar() {
  const path = usePathname();
  return (
    <nav
      className="fixed bottom-3 left-1/2 -translate-x-1/2 z-40 w-[calc(100%-24px)] max-w-[456px] bg-surface border border-line rounded-[22px] shadow-card flex justify-around px-1.5 py-2.5"
      style={{ paddingBottom: "calc(0.625rem + env(safe-area-inset-bottom, 0px))" }}
    >
      {TABS.map((t) => {
        const on = path === t.href;
        const Icon = t.icon;
        return (
          <Link
            key={t.href}
            href={t.href}
            className={cn("flex flex-col items-center gap-[3px] text-[10.5px] font-semibold px-3", on ? "text-accent-strong" : "text-ink-3")}
          >
            <Icon size={22} strokeWidth={on ? 2.4 : 1.8} />
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}
