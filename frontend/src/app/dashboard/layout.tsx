"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
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
  Sparkles,
  Edit2,
  UserCircle2,
  Send,
  FileSignature,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
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
import { hrefToTela, allowedTelasOf } from "@/lib/telas";
import { MunicipioProvider, useMunicipio } from "@/contexts/MunicipioContext";

type NavLeaf = { href: string; label: string; icon?: React.ComponentType<{ className?: string }> };
type NavSection = { sectionLabel: string; children: NavLeaf[] };
type NavGroup = { label: string; icon: React.ComponentType<{ className?: string }>; children: Array<NavLeaf | NavSection> };
type NavEntry = NavLeaf | NavGroup;

// Filtra a navegacao pelas telas permitidas (null = ve tudo: admin ou carregando).
// Grupos so aparecem se sobrar ao menos um filho; secoes idem.
function filterNav(items: NavEntry[], allowed: Set<string> | null): NavEntry[] {
  if (!allowed) return items;
  const out: NavEntry[] = [];
  for (const item of items) {
    if ("children" in item) {
      const children = item.children
        .map((c): NavLeaf | NavSection | null => {
          if ("sectionLabel" in c) {
            const kids = c.children.filter((l) => allowed.has(hrefToTela(l.href)));
            return kids.length ? { ...c, children: kids } : null;
          }
          return allowed.has(hrefToTela(c.href)) ? c : null;
        })
        .filter((c): c is NavLeaf | NavSection => c !== null);
      if (children.length) out.push({ ...item, children });
    } else if (allowed.has(hrefToTela(item.href))) {
      out.push(item);
    }
  }
  return out;
}

// Lista plana de hrefs (ordem da sidebar) — usada pelo guard de rota.
function allLeafHrefs(items: NavEntry[]): string[] {
  const out: string[] = [];
  for (const item of items) {
    if ("children" in item) {
      for (const c of item.children) {
        if ("sectionLabel" in c) out.push(...c.children.map((l) => l.href));
        else out.push(c.href);
      }
    } else {
      out.push(item.href);
    }
  }
  return out;
}

const NAV_ITEMS: NavEntry[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/dashboard/ai", label: "IA PACTHA", icon: Sparkles },
  { href: "/dashboard/telegram", label: "Telegram", icon: Send },
  { href: "/dashboard/parlamentares", label: "Parlamentares", icon: UserCircle2 },
  { href: "/dashboard/gestao", label: "Gestão Interna", icon: Edit2 },
  { href: "/dashboard/rm", label: "Relatório de Monitoramento", icon: FileText },
  { href: "/dashboard/documentos", label: "Geração de Documentos", icon: FileSignature },
  {
    label: "Estaduais",
    icon: FileText,
    children: [
      { href: "/dashboard/convenios", label: "SIGCON" },
      { href: "/dashboard/emendas", label: "Emendas Estaduais" },
    ],
  },
  {
    label: "Transfere Gov",
    icon: Landmark,
    children: [
      { href: "/dashboard/transferegov-geral", label: "Geral" },
      { href: "/dashboard/transferegov", label: "Especiais" },
      { href: "/dashboard/transferegov-voluntarias", label: "Voluntarias" },
      { href: "/dashboard/transferegov-rejeitadas", label: "Rejeitadas" },
      { href: "/dashboard/transferegov-encerradas", label: "Encerradas" },
      { href: "/dashboard/transferegov-cnpj", label: "CNPJ" },
    ],
  },
  { href: "/dashboard/fns", label: "Fundo Nacional de Saude", icon: Target },
  { href: "/dashboard/simec", label: "SIMEC - PAR (MEC)", icon: Target },
  { href: "/dashboard/dou", label: "Diario Oficial", icon: Newspaper },
  { href: "/dashboard/cofre", label: "Cofre de Senhas", icon: KeyRound },
  { href: "/dashboard/sessoes", label: "Sessoes (gov.br)", icon: KeyRound },
];

const ADMIN_NAV_ITEMS = [
  { href: "/dashboard/usuarios", label: "Usuarios", icon: Users },
  { href: "/dashboard/service-tokens", label: "Service Tokens", icon: KeyRound },
];

// Itens visiveis SO para o super-admin (nao para os demais admins).
const SUPER_ADMIN_EMAIL = "admin@pacta.com.br";
const SUPER_ADMIN_ONLY = new Set<string>(["/dashboard/sessoes", "/dashboard/service-tokens"]);

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
  // Estado de collapse dos grupos (persiste em localStorage)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    try {
      const raw = localStorage.getItem("pacta_nav_collapsed");
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch { return new Set(); }
  });
  const toggleGroup = (label: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label); else next.add(label);
      try { localStorage.setItem("pacta_nav_collapsed", JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  };
  // Sidebar so mostra as telas permitidas ao usuario (admin/carregando = todas)
  const isSuper = user?.email === SUPER_ADMIN_EMAIL;
  let visibleNav = filterNav(NAV_ITEMS, allowedTelasOf(user));
  if (!isSuper) {
    // Sessoes (captura gov.br) so p/ super-admin
    visibleNav = visibleNav.filter((it) => !("href" in it && SUPER_ADMIN_ONLY.has(it.href)));
  }
  return (
    <div className="flex h-full flex-col bg-base-100">
      {/* Faixa institucional - cores do governo */}
      <div className="gov-stripe" />

      {/* Header com logo PACTHA — chip branco arredondado (legível no claro e no escuro).
          No ambiente CIESP (PACTA2) exibe o co-branding CIESP ao lado. */}
      <div className="border-b border-base-300 px-4 py-4 flex justify-center items-center gap-2">
        <div className="rounded-2xl bg-white p-2.5 shadow-sm ring-1 ring-black/5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/pacta-logo.png" alt="PACTHA — Plataforma de Acompanhamento" className="h-16 w-auto" />
        </div>
        {process.env.NEXT_PUBLIC_TENANT === "ciesp" && (
          <div className="rounded-2xl bg-white p-2.5 shadow-sm ring-1 ring-black/5">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/ciesp-logo.png" alt="CIESP — Consórcio Intermunicipal de Especialidades" className="h-12 w-auto" />
          </div>
        )}
      </div>

      {/* Seletor de municipio */}
      <div className="px-3 py-3 border-b border-base-300 bg-base-200/50">
        <label className="mb-1.5 block text-[10px] font-semibold uppercase tracking-wider text-base-content/50">
          Municipio Atendido
        </label>
        <Select
          value={selectedMunicipioId}
          onValueChange={(v) => v && onMunicipioChange(v)}
        >
          <SelectTrigger className="w-full">
            <Building2 className="mr-1.5 size-4 text-primary" />
            <SelectValue placeholder="Selecionar municipio">
              {() => {
                const m = municipios.find((x) => String(x.id) === selectedMunicipioId);
                return m ? `${m.nome} - ${m.uf}` : "Selecionar municipio";
              }}
            </SelectValue>
            <ChevronDown className="ml-auto size-4 text-base-content/40" />
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
        <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
          Modulos
        </div>
        {visibleNav.map((item) => {
          const qs = selectedMunicipioId ? `?municipio_id=${selectedMunicipioId}` : "";
          const renderLeaf = (leaf: NavLeaf) => {
            const isActive = pathname === leaf.href || pathname.startsWith(leaf.href + "/");
            return (
              <Link
                key={leaf.href}
                href={`${leaf.href}${qs}`}
                className={`flex items-center gap-3 rounded-md px-3 py-1.5 text-sm font-medium transition-all ${
                  isActive
                    ? "bg-primary/10 text-primary font-semibold"
                    : "text-base-content/70 hover:bg-base-200 hover:text-base-content"
                }`}
              >
                <span className="text-[13px]">{leaf.label}</span>
              </Link>
            );
          };
          // Grupo com submenus (ex: Transfere Gov -> Geral / Especiais / Voluntarias / Rejeitadas)
          // Suporta children diretos (NavLeaf) ou sub-secoes (NavSection com children proprios).
          if ("children" in item) {
            const Icon = item.icon;
            const flat: NavLeaf[] = item.children.flatMap((c) =>
              "sectionLabel" in c ? c.children : [c]
            );
            const groupActive = flat.some(
              (c) => pathname === c.href || pathname.startsWith(c.href + "/")
            );
            const isCollapsed = collapsed.has(item.label) && !groupActive;
            // Auto-expande quando o grupo tem submenu ativo, mesmo se usuario colapsou
            return (
              <div key={item.label} className="pt-1">
                <button
                  type="button"
                  onClick={() => toggleGroup(item.label)}
                  className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-semibold w-full text-left hover:bg-base-200 transition-colors ${
                    groupActive ? "text-primary" : "text-base-content/70"
                  }`}
                  aria-expanded={!isCollapsed}
                  aria-label={`${isCollapsed ? "Expandir" : "Recolher"} ${item.label}`}
                >
                  <Icon className={`size-4 ${groupActive ? "text-primary" : "text-base-content/50"}`} />
                  <span className="text-[13px] flex-1">{item.label}</span>
                  <ChevronDown
                    className={`size-4 text-base-content/40 transition-transform duration-150 ${
                      isCollapsed ? "-rotate-90" : "rotate-0"
                    }`}
                  />
                </button>
                {!isCollapsed && (
                  <div className="ml-3 border-l border-base-300 pl-2 space-y-0.5">
                    {item.children.map((c) => {
                      if ("sectionLabel" in c) {
                        return (
                          <div key={c.sectionLabel} className="pt-1">
                            <div className="px-3 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
                              {c.sectionLabel}
                            </div>
                            <div className="ml-2 border-l border-base-300 pl-2 space-y-0.5">
                              {c.children.map((leaf) => renderLeaf(leaf))}
                            </div>
                          </div>
                        );
                      }
                      return renderLeaf(c);
                    })}
                  </div>
                )}
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
                  ? "bg-primary/10 text-primary font-semibold"
                  : "text-base-content/70 hover:bg-base-200 hover:text-base-content"
              }`}
            >
              {Icon && <Icon className={`size-4 ${isActive ? "text-primary" : "text-base-content/50"}`} />}
              <span className="text-[13px]">{item.label}</span>
            </Link>
          );
        })}

        {user?.role === "admin" && (
          <>
            <div className="px-3 mt-4 mb-2 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
              Administracao
            </div>
            {ADMIN_NAV_ITEMS.filter((item) => isSuper || !SUPER_ADMIN_ONLY.has(item.href)).map((item) => {
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-all ${
                    isActive
                      ? "bg-warning/15 text-warning font-semibold"
                      : "text-base-content/70 hover:bg-base-200 hover:text-base-content"
                  }`}
                >
                  <Icon className={`size-4 ${isActive ? "text-warning" : "text-base-content/50"}`} />
                  <span className="text-[13px]">{item.label}</span>
                </Link>
              );
            })}
          </>
        )}
      </nav>

      {/* Footer institucional */}
      <div className="border-t border-base-300 px-3 py-3 bg-base-200/50">
        {user && (
          <div className="mb-2 px-2 py-2 rounded-md bg-base-100 border border-base-300">
            <div className="text-[10px] uppercase tracking-wider text-base-content/40">
              Usuario
            </div>
            <div className="text-sm font-medium text-base-content truncate">
              {user.name}
            </div>
            <div className="text-[10px] text-base-content/50 truncate">
              {user.email}
            </div>
          </div>
        )}
        <ThemeToggle className="w-full mb-1" />
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-2 text-error hover:bg-error/10 text-xs"
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
  const { municipioId: selectedMunicipioId, setMunicipioId } = useMunicipio();
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  const [user, setUser] = useState<User | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

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
          // Prefere ultimo municipio usado (localStorage); senao primeiro da lista
          const lastId = typeof window !== "undefined"
            ? localStorage.getItem("pacta_last_municipio_id")
            : null;
          const chosen = (lastId && data.some(m => String(m.id) === lastId))
            ? lastId
            : String(data[0].id);
          // Estado no context -> telas re-renderizam e carregam os KPIs na hora
          // (sem router.refresh / sem recarregar a pagina).
          setMunicipioId(chosen);
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Persiste municipio selecionado pra proxima visita lembrar
  useEffect(() => {
    if (selectedMunicipioId && typeof window !== "undefined") {
      localStorage.setItem("pacta_last_municipio_id", selectedMunicipioId);
    }
  }, [selectedMunicipioId]);

  // Guard de rota: nao-admin sem acesso a tela atual -> 1a tela permitida.
  // Seguranca real e no backend (ensure_tela / 403); isto e UX.
  useEffect(() => {
    const allowed = allowedTelasOf(user);
    if (!allowed) return; // admin ou ainda carregando
    if (allowed.has(hrefToTela(pathname))) return;
    const firstAllowed = allLeafHrefs(NAV_ITEMS).find((h) => allowed.has(hrefToTela(h)));
    if (firstAllowed && firstAllowed !== pathname) router.replace(firstAllowed);
  }, [user, pathname, router]);

  // Guard super-admin: Sessoes / Service Tokens so p/ admin@pacta.com.br
  useEffect(() => {
    if (!user) return;
    if (user.email !== SUPER_ADMIN_EMAIL && SUPER_ADMIN_ONLY.has(pathname)) {
      router.replace("/dashboard");
    }
  }, [user, pathname, router]);

  // Troca de municipio = so estado no context (instantaneo, client-side).
  // O context ja sincroniza a URL (history.replaceState) e reseta a paginacao.
  const handleMunicipioChange = setMunicipioId;

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
    <div className="flex h-screen overflow-hidden bg-base-200">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 flex-shrink-0 border-r border-base-300 bg-base-100 lg:block">
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
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
        </div>
      }
    >
      <MunicipioProvider>
        <DashboardShell>{children}</DashboardShell>
      </MunicipioProvider>
    </Suspense>
  );
}
