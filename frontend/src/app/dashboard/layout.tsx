"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  LayoutDashboard,
  FileText,
  LogOut,
  Building2,
  ChevronDown,
  Menu,
  KeyRound,
  Newspaper,
  Target,
  Users,
  Landmark,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
} from "@/components/ui/sheet";
import type { Municipio, User } from "@/types";

type NavLeaf = { href: string; label: string; icon?: React.ComponentType<{ className?: string }> };
type NavGroup = { label: string; icon: React.ComponentType<{ className?: string }>; children: NavLeaf[] };
type NavEntry = NavLeaf | NavGroup;

const NAV_ITEMS: NavEntry[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/dashboard/convenios", label: "Convenios (SIGCON)", icon: FileText },
  {
    label: "Transfere Gov",
    icon: Landmark,
    children: [
      { href: "/dashboard/transferegov-geral", label: "Geral" },
      { href: "/dashboard/transferegov", label: "Especiais" },
      { href: "/dashboard/transferegov-voluntarias", label: "Voluntarias" },
    ],
  },
  { href: "/dashboard/emendas", label: "Emendas Estaduais", icon: FileText },
  { href: "/dashboard/fns", label: "Fundo Nacional de Saude", icon: Target },
  { href: "/dashboard/dou", label: "Diario Oficial", icon: Newspaper },
  { href: "/dashboard/cofre", label: "Cofre de Senhas", icon: KeyRound },
  { href: "/dashboard/sessoes", label: "Sessoes (gov.br)", icon: KeyRound },
];

const ADMIN_NAV_ITEMS = [
  { href: "/dashboard/usuarios", label: "Usuarios", icon: Users },
  { href: "/dashboard/service-tokens", label: "Service Tokens", icon: KeyRound },
];

function SidebarContent({
  pathname,
  municipios,
  selectedMunicipioId,
  onMunicipioChange,
  user,
  onLogout,
}: {
  pathname: string;
  municipios: Municipio[];
  selectedMunicipioId: string;
  onMunicipioChange: (value: string) => void;
  user: User | null;
  onLogout: () => void;
}) {
  return (
    <div className="flex h-full flex-col bg-white">
      {/* Faixa institucional - cores do governo */}
      <div className="gov-stripe" />

      {/* Header com brasao */}
      <div className="border-b border-slate-200 px-4 py-5 bg-gradient-to-br from-blue-700 to-blue-900 text-white">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-md bg-white/15 backdrop-blur-sm border border-white/20">
            <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m-1 4h1m-1 4h1m4-8h1m-1 4h1m-1 4h1" />
            </svg>
          </div>
          <div>
            <div className="text-base font-bold tracking-tight">PACTA</div>
            <div className="text-[10px] uppercase tracking-wider text-blue-100/90">
              Plataforma de Acompanhamento
            </div>
          </div>
        </div>
      </div>

      {/* Seletor de municipio */}
      <div className="px-3 py-3 border-b border-slate-100 bg-slate-50/60">
        <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Municipio Atendido
        </label>
        <Select
          value={selectedMunicipioId}
          onValueChange={(v) => v && onMunicipioChange(v)}
        >
          <SelectTrigger className="w-full bg-white border-slate-300">
            <Building2 className="mr-1.5 size-4 text-blue-700" />
            <SelectValue placeholder="Selecionar municipio">
              {() => {
                const m = municipios.find((x) => String(x.id) === selectedMunicipioId);
                return m ? `${m.nome} - ${m.uf}` : "Selecionar municipio";
              }}
            </SelectValue>
            <ChevronDown className="ml-auto size-4 text-slate-400" />
          </SelectTrigger>
          <SelectContent>
            {municipios.map((m) => (
              <SelectItem key={m.id} value={String(m.id)}>
                {m.nome} - {m.uf}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Navegacao */}
      <nav className="flex-1 space-y-0.5 px-2 py-3 overflow-y-auto">
        <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Modulos
        </div>
        {NAV_ITEMS.map((item) => {
          const qs = selectedMunicipioId ? `?municipio_id=${selectedMunicipioId}` : "";
          // Grupo com submenus (ex: Transfere Gov -> Geral / Especiais / Voluntarias)
          if ("children" in item) {
            const Icon = item.icon;
            const groupActive = item.children.some(
              (c) => pathname === c.href || pathname.startsWith(c.href + "/")
            );
            return (
              <div key={item.label} className="pt-1">
                <div
                  className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-semibold ${
                    groupActive ? "text-blue-800" : "text-slate-600"
                  }`}
                >
                  <Icon className={`size-4 ${groupActive ? "text-blue-700" : "text-slate-500"}`} />
                  <span className="text-[13px]">{item.label}</span>
                </div>
                <div className="ml-3 border-l border-slate-200 pl-2 space-y-0.5">
                  {item.children.map((c) => {
                    const isActive = pathname === c.href || pathname.startsWith(c.href + "/");
                    return (
                      <Link
                        key={c.href}
                        href={`${c.href}${qs}`}
                        className={`flex items-center gap-3 rounded-md px-3 py-1.5 text-sm font-medium transition-all ${
                          isActive
                            ? "bg-blue-50 text-blue-800 border-l-3 border-blue-700 shadow-sm"
                            : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 border-l-3 border-transparent"
                        }`}
                      >
                        <span className="text-[13px]">{c.label}</span>
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          }
          const isActive =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href + "/"));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={`${item.href}${qs}`}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                isActive
                  ? "bg-blue-50 text-blue-800 border-l-3 border-blue-700 shadow-sm"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 border-l-3 border-transparent"
              }`}
            >
              {Icon && <Icon className={`size-4 ${isActive ? "text-blue-700" : "text-slate-500"}`} />}
              <span className="text-[13px]">{item.label}</span>
            </Link>
          );
        })}

        {user?.role === "admin" && (
          <>
            <div className="px-3 mt-4 mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Administracao
            </div>
            {ADMIN_NAV_ITEMS.map((item) => {
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                    isActive
                      ? "bg-amber-50 text-amber-800 border-l-3 border-amber-700"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 border-l-3 border-transparent"
                  }`}
                >
                  <Icon className={`size-4 ${isActive ? "text-amber-700" : "text-slate-500"}`} />
                  <span className="text-[13px]">{item.label}</span>
                </Link>
              );
            })}
          </>
        )}
      </nav>

      {/* Footer institucional */}
      <div className="border-t border-slate-200 px-3 py-3 bg-slate-50/60">
        {user && (
          <div className="mb-2 px-2 py-2 rounded-md bg-white border border-slate-200">
            <div className="text-[10px] uppercase tracking-wider text-slate-400">
              Usuario
            </div>
            <div className="text-sm font-medium text-slate-700 truncate">
              {user.name}
            </div>
            <div className="text-[10px] text-slate-500 truncate">
              {user.email}
            </div>
          </div>
        )}
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-2 text-red-700 hover:bg-red-50 hover:text-red-800 text-xs"
          onClick={onLogout}
        >
          <LogOut className="size-4" />
          Sair do sistema
        </Button>
      </div>
    </div>
  );
}

function DashboardShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  const selectedMunicipioId = searchParams.get("municipio_id") || "";

  useEffect(() => {
    // Verifica sessao via /auth/me (cookie httpOnly ou Bearer)
    api
      .get<User & { must_change_password?: boolean }>("/auth/me")
      .then((res) => {
        setUser(res.data);
        localStorage.setItem("pacta_user", JSON.stringify(res.data));
        if (res.data.must_change_password) {
          router.replace("/change-password?first=1");
        }
      })
      .catch(() => {
        // 401 e tratado pelo interceptor (tenta refresh + redireciona)
      });
  }, [router]);

  useEffect(() => {
    api
      .get<Municipio[]>("/municipios")
      .then((res) => {
        const data = Array.isArray(res.data) ? res.data : [];
        setMunicipios(data);
        if (!selectedMunicipioId && data.length > 0) {
          const params = new URLSearchParams(searchParams.toString());
          params.set("municipio_id", String(data[0].id));
          router.replace(`${pathname}?${params.toString()}`);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleMunicipioChange = useCallback(
    (value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("municipio_id", value);
      // page=1 reset evita "Pagina 3 vazia" ao trocar de municipio
      params.delete("page");
      // replace + refresh garante re-render do Client Component se cache local
      // do useSearchParams nao acompanhou (bug recorrente em Next 16 com Suspense)
      router.replace(`${pathname}?${params.toString()}`);
      router.refresh();
    },
    [pathname, router, searchParams]
  );

  const handleLogout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    localStorage.removeItem("pacta_token");
    localStorage.removeItem("pacta_user");
    router.push("/login");
  }, [router]);

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 flex-shrink-0 border-r bg-white lg:block">
        <SidebarContent
          pathname={pathname}
          municipios={municipios}
          selectedMunicipioId={selectedMunicipioId}
          onMunicipioChange={handleMunicipioChange}
          user={user}
          onLogout={handleLogout}
        />
      </aside>

      {/* Mobile sidebar */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <div className="lg:hidden">
          <SheetTrigger
            render={
              <Button variant="ghost" size="icon" className="fixed top-3 left-3 z-40" />
            }
          >
            <Menu className="size-5" />
          </SheetTrigger>
        </div>
        <SheetContent side="left" className="w-64 p-0">
          <SheetTitle className="sr-only">Menu de navegacao</SheetTitle>
          <SidebarContent
            pathname={pathname}
            municipios={municipios}
            selectedMunicipioId={selectedMunicipioId}
            onMunicipioChange={(v) => {
              handleMunicipioChange(v);
              setMobileOpen(false);
            }}
            user={user}
            onLogout={handleLogout}
          />
        </SheetContent>
      </Sheet>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </div>
      </main>
    </div>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-indigo-600 border-t-transparent" />
        </div>
      }
    >
      <DashboardShell>{children}</DashboardShell>
    </Suspense>
  );
}
