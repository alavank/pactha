"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  LayoutDashboard,
  FileText,
  Search,
  ClipboardCheck,
  BarChart3,
  LogOut,
  Building2,
  ChevronDown,
  Menu,
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

const NAV_ITEMS = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/dashboard/convenios", label: "Convenios", icon: FileText },
  { href: "/dashboard/editais", label: "Editais", icon: Search },
  { href: "/dashboard/prestacao", label: "Prestacao", icon: ClipboardCheck },
  { href: "/dashboard/politica", label: "Politica", icon: BarChart3 },
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
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-white font-bold text-sm">
          P
        </div>
        <span className="text-lg font-bold text-indigo-700">PACTA</span>
      </div>

      <div className="px-3 py-3">
        <label className="mb-1.5 block text-xs font-medium text-muted-foreground">
          Municipio
        </label>
        <Select
          value={selectedMunicipioId}
          onValueChange={(v) => v && onMunicipioChange(v)}
        >
          <SelectTrigger className="w-full">
            <Building2 className="mr-1.5 size-4 text-muted-foreground" />
            <SelectValue placeholder="Selecionar municipio" />
            <ChevronDown className="ml-auto size-4 text-muted-foreground" />
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

      <nav className="flex-1 space-y-1 px-3 py-2">
        {NAV_ITEMS.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/dashboard" && pathname.startsWith(item.href));
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={`${item.href}${selectedMunicipioId ? `?municipio_id=${selectedMunicipioId}` : ""}`}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              }`}
            >
              <Icon className="size-5" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t px-3 py-3">
        {user && (
          <div className="mb-2 px-3 text-sm text-muted-foreground truncate">
            {user.name}
          </div>
        )}
        <Button
          variant="ghost"
          className="w-full justify-start gap-3 text-red-600 hover:bg-red-50 hover:text-red-700"
          onClick={onLogout}
        >
          <LogOut className="size-5" />
          Sair
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
    const storedUser = localStorage.getItem("pacta_user");
    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser));
      } catch {
        /* ignore */
      }
    }
    const token = localStorage.getItem("pacta_token");
    if (!token) {
      router.push("/login");
    }
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
      router.push(`${pathname}?${params.toString()}`);
    },
    [pathname, router, searchParams]
  );

  const handleLogout = useCallback(() => {
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
