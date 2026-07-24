"use client";
// Shell executivo do Painel de Indicadores (BI). SEPARADO do sidebar operacional
// (/dashboard) para atender a alta gestao com navegacao simplificada. Mesmo app,
// mesmo login, mesmo deploy. Densidade/escala NORMAIS do Pactha.
import { useEffect, useMemo, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LayoutGrid, Users, Bell, Settings2, LogOut, ArrowLeft, BarChart3 } from "lucide-react";
import api from "@/lib/api";
import { getMunicipios, Municipio } from "@/lib/bi";
import { User } from "@/types";
import { BiScopeProvider, useBiScope, CONSOLIDADO } from "@/contexts/BiScopeContext";
import { ScopeSelect, PeriodSelect } from "@/components/bi/ScopeSelect";
import { BottomNav } from "@/components/bi/BottomNav";
import { ThemeToggle } from "@/components/ThemeToggle";
import { cn } from "@/lib/utils";

const BI_ON = process.env.NEXT_PUBLIC_BI_MODULE === "1";

const DESKTOP_TABS = [
  { href: "/bi", label: "Visão Geral", icon: LayoutGrid, exact: true },
  { href: "/bi/parlamentares", label: "Parlamentares", icon: Users },
  { href: "/bi/alertas", label: "Prazos & Alertas", icon: Bell },
  { href: "/bi/config", label: "Ajustes", icon: Settings2 },
];

function anosDisponiveis(): number[] {
  const y = new Date().getFullYear();
  return Array.from({ length: 7 }, (_, i) => y - i);
}

function BiShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { scope, setScope } = useBiScope();
  const [user, setUser] = useState<User | null>(null);
  const [municipios, setMunicipios] = useState<Municipio[]>([]);

  // Flag OFF -> fora do ar
  useEffect(() => {
    if (!BI_ON) router.replace("/dashboard");
  }, [router]);

  // Sessao + autorizacao (visibilidade real e no backend; isto e UX)
  useEffect(() => {
    api
      .get<User & { must_change_password?: boolean }>("/auth/me")
      .then((res) => {
        setUser(res.data);
        if (res.data.must_change_password) {
          router.replace("/change-password?first=1");
          return;
        }
        const ok =
          res.data.role === "admin" ||
          res.data.role === "prefeito" ||
          res.data.role === "viewer" ||
          (Array.isArray(res.data.telas) && res.data.telas.includes("bi")) ||
          res.data.telas == null; // null = admin/carregando
        if (!ok) router.replace("/dashboard");
      })
      .catch(() => {
        /* 401 -> interceptor tenta refresh/redirect */
      });
  }, [router]);

  // Municipios do escopo + validacao da selecao
  useEffect(() => {
    getMunicipios()
      .then((data) => setMunicipios(data))
      .catch(() => {});
  }, []);

  const canConsolidado = useMemo(
    () => municipios.length > 1 || user?.role === "admin",
    [municipios.length, user?.role]
  );

  // Valida/ajusta o escopo assim que a lista chega (mirror do DashboardShell)
  useEffect(() => {
    if (!municipios.length) return;
    if (scope === CONSOLIDADO) {
      if (!canConsolidado) setScope(String(municipios[0].id));
      return;
    }
    const valid = scope && municipios.some((m) => String(m.id) === scope);
    if (!valid) setScope(canConsolidado ? CONSOLIDADO : String(municipios[0].id));
  }, [municipios, scope, canConsolidado, setScope]);

  const handleLogout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    localStorage.removeItem("pactha_token");
    localStorage.removeItem("pactha_user");
    localStorage.removeItem("pactha_last_municipio_id");
    localStorage.removeItem("pactha_bi_scope"); // nao vazar escopo/periodo do BI entre usuarios
    localStorage.removeItem("pactha_bi_ano");
    router.push("/login");
  }, [router]);

  const isExecutivo = user?.role === "prefeito" || user?.role === "viewer";

  return (
    <div className="flex min-h-screen flex-col bg-base-200">
      {/* Header (sticky) */}
      <header className="sticky top-0 z-30 border-b border-base-300 bg-base-100/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-3 px-4 py-2.5 sm:px-6">
          <div className="flex items-center gap-2">
            <span className="grid size-8 place-items-center rounded-xl bg-primary/10 text-primary">
              <BarChart3 className="size-[18px]" />
            </span>
            <div className="leading-tight">
              <div className="text-sm font-bold text-base-content">Painel de Indicadores</div>
              <div className="text-[11px] text-base-content/50">BI · gestão à vista</div>
            </div>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <ScopeSelect municipios={municipios} canConsolidado={canConsolidado} />
            <PeriodSelect anos={anosDisponiveis()} />
            <ThemeToggle />
            {!isExecutivo && (
              <Link
                href="/dashboard"
                className="hidden items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-base-content/70 hover:bg-base-200 sm:flex"
                title="Voltar ao sistema operacional"
              >
                <ArrowLeft className="size-4" /> Sistema
              </Link>
            )}
            <button
              onClick={handleLogout}
              className="grid size-8 place-items-center rounded-lg text-error hover:bg-error/10"
              title="Sair"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </div>

        {/* Tabs desktop */}
        <nav className="mx-auto hidden max-w-7xl gap-1 px-4 sm:px-6 lg:flex">
          {DESKTOP_TABS.map((t) => {
            const active = t.exact ? pathname === t.href : pathname.startsWith(t.href);
            const Icon = t.icon;
            return (
              <Link
                key={t.href}
                href={t.href}
                className={cn(
                  "-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "border-primary text-primary"
                    : "border-transparent text-base-content/60 hover:text-base-content"
                )}
              >
                <Icon className="size-4" />
                {t.label}
              </Link>
            );
          })}
        </nav>
      </header>

      {/* Conteudo */}
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-5 pb-24 sm:px-6 lg:pb-8">{children}</main>

      <BottomNav />
    </div>
  );
}

export default function BiShellLayout({ children }: { children: React.ReactNode }) {
  return (
    <BiScopeProvider>
      <Suspense fallback={null}>
        <BiShell>{children}</BiShell>
      </Suspense>
    </BiScopeProvider>
  );
}
