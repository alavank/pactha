"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  LayoutGrid,
  FileText,
  LogOut,
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
  ShieldCheck,
  HeartPulse,
  Activity,
  BarChart3,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  Sheet,
  SheetContent,
  SheetTrigger,
  SheetTitle,
} from "@/components/ui/sheet";
import type { Municipio, User } from "@/types";
import { hrefToTela, allowedTelasOf } from "@/lib/telas";
import { MunicipioProvider, useMunicipio } from "@/contexts/MunicipioContext";
import { EnteAtendido, SUBTITULO_PACTHA } from "@/components/bi/Marca";

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

// Com o BI ligado, o item "Dashboard" JA E o Painel de Indicadores (mesma rota).
// Antes havia um link separado logo acima da navegacao — dois menus para a
// mesma coisa. Ficou um so.
const BI_ON = process.env.NEXT_PUBLIC_BI_MODULE === "1";

const NAV_ITEMS: NavEntry[] = [
  {
    href: "/dashboard",
    label: BI_ON ? "Painel de Indicadores" : "Dashboard",
    icon: BI_ON ? BarChart3 : LayoutDashboard,
  },
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
      { href: "/dashboard/transferegov-pac", label: "PAC (Novo PAC)" },
      { href: "/dashboard/transferegov-voluntarias", label: "Voluntarias" },
      { href: "/dashboard/transferegov-rejeitadas", label: "Rejeitadas" },
      { href: "/dashboard/transferegov-encerradas", label: "Encerradas" },
      { href: "/dashboard/transferegov-cnpj", label: "CNPJ" },
    ],
  },
  { href: "/dashboard/cauc", label: "CAUC (Regularidade)", icon: ShieldCheck },
  { href: "/dashboard/acordofes", label: "Acordo FES (Divida Saude)", icon: HeartPulse },
  { href: "/dashboard/fns", label: "Fundo Nacional de Saude", icon: Target },
  { href: "/dashboard/simec", label: "SIMEC - PAR (MEC)", icon: Target },
  { href: "/dashboard/paineis", label: "Painéis Municipais", icon: LayoutGrid },
  { href: "/dashboard/dou", label: "Diario Oficial", icon: Newspaper },
  { href: "/dashboard/cofre", label: "Cofre de Senhas", icon: KeyRound },
  { href: "/dashboard/sessoes", label: "Sessoes (gov.br)", icon: KeyRound },
];

const ADMIN_NAV_ITEMS = [
  { href: "/dashboard/usuarios", label: "Usuarios", icon: Users },
  { href: "/dashboard/frescor", label: "Frescor dos Dados", icon: Activity },
  { href: "/dashboard/service-tokens", label: "Service Tokens", icon: KeyRound },
];

// Itens visiveis SO para o super-admin (nao para os demais admins).
//
// Sao os DONOS do sistema, nao "mais um admin do cliente": quem administra a
// plataforma pela Alavank. Fica como lista porque uma conta so era um ponto
// unico de falha — perdido o acesso a ela, ninguem alcanca Sessoes e Tokens de
// Servico. Um e-mail por conta, minusculo (a comparacao normaliza).
const SUPER_ADMIN_EMAILS = new Set<string>([
  "admin@pactha.com.br",
  "alavank.tecnologia@gmail.com",
]);
const SUPER_ADMIN_ONLY = new Set<string>(["/dashboard/sessoes", "/dashboard/service-tokens"]);

function SidebarContent({
  pathname,
  municipios,
  selectedMunicipioId,
  onMunicipioChange,
  user,
  onLogout,
  recolhida = false,
  onToggleRecolhida,
}: {
  pathname: string;
  municipios: Municipio[];
  selectedMunicipioId: string;
  onMunicipioChange: (value: string) => void;
  user: User | null;
  onLogout: () => void;
  /** Modo icone: so os simbolos, com o rotulo no title. */
  recolhida?: boolean;
  onToggleRecolhida?: () => void;
}) {
  // Estado de collapse dos grupos (persiste em localStorage)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    if (typeof window === "undefined") return new Set();
    try {
      const raw = localStorage.getItem("pactha_nav_collapsed");
      return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
    } catch { return new Set(); }
  });
  const toggleGroup = (label: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label); else next.add(label);
      try { localStorage.setItem("pactha_nav_collapsed", JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  };
  // Sidebar so mostra as telas permitidas ao usuario (admin/carregando = todas)
  const isSuper = SUPER_ADMIN_EMAILS.has((user?.email || "").trim().toLowerCase());
  let visibleNav = filterNav(NAV_ITEMS, allowedTelasOf(user));
  if (!isSuper) {
    // Sessoes (captura gov.br) so p/ super-admin
    visibleNav = visibleNav.filter((it) => !("href" in it && SUPER_ADMIN_ONLY.has(it.href)));
  }
  return (
    <div className="flex h-full flex-col bg-base-100">
      {/* Faixa institucional - cores do governo */}
      <div className="gov-stripe" />

      {/* Header: a marca do PRODUTO, sozinha. O brasão saiu daqui — ele agora
          acompanha o nome da cidade logo abaixo, como título do ente atendido.
          Os dois grudados num chip só embaralhavam quem é fornecedor e quem é
          cliente. No modo ícone fica só a logo: a assinatura não caberia. */}
      <div className={`border-b border-base-300 py-4 flex justify-center ${recolhida ? "px-1.5" : "px-3"}`}>
        <div
          className={`flex max-w-full flex-col items-center gap-1 rounded-2xl bg-white shadow-sm ring-1 ring-black/5 ${
            recolhida ? "px-2 py-2" : "px-3 py-2"
          }`}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/pactha-logo.png"
            alt="PACTHA"
            className={recolhida ? "h-7 w-auto max-w-[36px] object-contain" : "h-6 w-auto max-w-[130px] object-contain"}
          />
          {!recolhida && (
            <span className="text-center text-[9px] leading-tight text-black/55">
              {SUBTITULO_PACTHA}
            </span>
          )}
        </div>
      </div>

      {/* Botao de recolher/expandir (so no desktop; o mobile ja abre em gaveta) */}
      {onToggleRecolhida && (
        <div className={`hidden lg:flex ${recolhida ? "justify-center px-1.5" : "justify-end px-3"} pt-2`}>
          <button
            type="button"
            onClick={onToggleRecolhida}
            className="grid size-7 place-items-center rounded-lg text-base-content/50 transition-colors hover:bg-base-200 hover:text-base-content"
            title={recolhida ? "Expandir menu" : "Recolher menu"}
            aria-label={recolhida ? "Expandir menu" : "Recolher menu"}
            aria-expanded={!recolhida}
          >
            {recolhida ? <PanelLeftOpen className="size-4" /> : <PanelLeftClose className="size-4" />}
          </button>
        </div>
      )}

      {/* Ente atendido (some no modo icone — nao cabe e nao e clicavel util) */}
      {!recolhida && (
        <div className="px-3 py-3 border-b border-base-300 bg-base-200/50">
          {municipios.length === 1 ? (
            // Entidade unica (municipio/consorcio): brasao + nome como TITULO.
            // Nao ha dropdown porque nao ha o que escolher — e o campo com cara
            // de seletor sugeria que existe dado de outra cidade ali dentro.
            <EnteAtendido
              nome={`${municipios[0].nome} - ${municipios[0].uf}`}
              tamanho="medio"
              className="justify-center"
            />
          ) : (
            // Multi-entidade (assessoria/parceiro): dropdown
            <select
              className="select select-bordered select-sm w-full"
              value={selectedMunicipioId}
              onChange={(e) => onMunicipioChange(e.target.value)}
            >
              <option value="">Município selecionado</option>
              {municipios.map((m) => (
                <option key={m.id} value={String(m.id)}>
                  {m.nome} - {m.uf}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {/* Navegacao */}
      <nav className={`flex-1 space-y-0.5 py-3 overflow-y-auto ${recolhida ? "px-1.5" : "px-2"}`}>
        {!recolhida && (
          <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
            Modulos
          </div>
        )}
        {visibleNav.map((item) => {
          const qs = selectedMunicipioId ? `?municipio_id=${selectedMunicipioId}` : "";
          const renderLeaf = (leaf: NavLeaf) => {
            const isActive = pathname === leaf.href || pathname.startsWith(leaf.href + "/");
            return (
              <Link
                key={leaf.href}
                href={`${leaf.href}${qs}`}
                className={`flex items-center gap-3 rounded-lg px-3 py-1.5 text-sm font-medium transition-all ${
                  isActive
                    ? "bg-accent text-primary font-semibold"
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
            // Menu recolhido: o grupo vira UM icone que leva ao primeiro filho.
            // Empilhar submenu num trilho de 4rem so cria ruido.
            if (recolhida) {
              return (
                <Link
                  key={item.label}
                  href={`${flat[0]?.href ?? "/dashboard"}${qs}`}
                  title={`${item.label}: ${flat.map((c) => c.label).join(", ")}`}
                  aria-label={item.label}
                  className={`flex items-center justify-center rounded-lg py-2 transition-all ${
                    groupActive ? "bg-accent text-primary" : "text-base-content/60 hover:bg-base-200"
                  }`}
                >
                  <Icon className="size-[18px]" />
                </Link>
              );
            }
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
          if (recolhida) {
            return (
              <Link
                key={item.href}
                href={`${item.href}${qs}`}
                title={item.label}
                aria-label={item.label}
                className={`flex items-center justify-center rounded-lg py-2 transition-all ${
                  isActive ? "bg-accent text-primary" : "text-base-content/60 hover:bg-base-200"
                }`}
              >
                {Icon && <Icon className="size-[18px]" />}
              </Link>
            );
          }
          return (
            <Link
              key={item.href}
              href={`${item.href}${qs}`}
              className={`relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                isActive
                  ? "bg-accent text-primary font-semibold before:absolute before:-left-2 before:top-1/2 before:h-6 before:w-1 before:-translate-y-1/2 before:rounded-r-full before:bg-primary"
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
            {recolhida ? (
              <div className="my-2 border-t border-base-300" />
            ) : (
              <div className="px-3 mt-4 mb-2 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
                Administracao
              </div>
            )}
            {ADMIN_NAV_ITEMS.filter((item) => isSuper || !SUPER_ADMIN_ONLY.has(item.href)).map((item) => {
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
              const Icon = item.icon;
              if (recolhida) {
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    title={item.label}
                    aria-label={item.label}
                    className={`flex items-center justify-center rounded-lg py-2 transition-all ${
                      isActive ? "bg-warning/15 text-warning" : "text-base-content/60 hover:bg-base-200"
                    }`}
                  >
                    <Icon className="size-[18px]" />
                  </Link>
                );
              }
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
      <div className={`border-t border-base-300 py-3 bg-base-200/50 ${recolhida ? "px-1.5" : "px-3"}`}>
        {user && !recolhida && (
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
        {recolhida ? (
          <div className="flex flex-col items-center gap-1">
            <ThemeToggle className="w-full justify-center px-0" />
            <button
              type="button"
              onClick={onLogout}
              title="Sair do sistema"
              aria-label="Sair do sistema"
              className="grid w-full place-items-center rounded-lg py-2 text-error transition-colors hover:bg-error/10"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        ) : (
          <>
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
          </>
        )}
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
  // Barra lateral recolhivel (modo icone). Persiste entre sessoes — quem
  // trabalha o dia todo numa tela pequena nao quer reclicar toda vez.
  const [sidebarRecolhida, setSidebarRecolhida] = useState(false);

  // Le a preferencia DEPOIS da hidratacao: ler no initializer do useState faria
  // o servidor renderizar expandido e o cliente recolhido (mismatch).
  useEffect(() => {
    if (typeof window === "undefined") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSidebarRecolhida(localStorage.getItem("pactha_sidebar_recolhida") === "1");
  }, []);

  const toggleSidebar = useCallback(() => {
    setSidebarRecolhida((v) => {
      const proximo = !v;
      try {
        localStorage.setItem("pactha_sidebar_recolhida", proximo ? "1" : "0");
      } catch { /* storage cheio/bloqueado: nao vale quebrar a navegacao */ }
      return proximo;
    });
  }, []);

  useEffect(() => {
    // Verifica sessao via /auth/me (cookie httpOnly ou Bearer)
    api
      .get<User & { must_change_password?: boolean }>("/auth/me")
      .then((res) => {
        setUser(res.data);
        localStorage.setItem("pactha_user", JSON.stringify(res.data));
        if (res.data.must_change_password) {
          router.replace("/change-password?first=1");
          return;
        }
        // Perfil executivo (prefeito/viewer): o Painel de Indicadores JA e a
        // home (/dashboard), entao nao ha mais para onde redirecionar.
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
        if (data.length > 0) {
          // Valida a selecao ATUAL contra a lista de municipios ATIVOS. Se a atual nao
          // esta na lista (ex.: id obsoleto no localStorage apontando p/ municipio
          // inativo ou de outro tenant clonado), RE-SELECIONA. Antes so auto-selecionava
          // quando estava VAZIO -> um id stale passava batido e a tela filtrava por um
          // municipio inexistente, mostrando vazio mesmo com dados no banco.
          const isValid = selectedMunicipioId && data.some(m => String(m.id) === selectedMunicipioId);
          if (!isValid) {
            const lastId = typeof window !== "undefined"
              ? localStorage.getItem("pactha_last_municipio_id")
              : null;
            const chosen = (lastId && data.some(m => String(m.id) === lastId))
              ? lastId
              : String(data[0].id);
            // Estado no context -> telas re-renderizam e carregam os KPIs na hora
            // (sem router.refresh / sem recarregar a pagina).
            setMunicipioId(chosen);
          }
        }
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Persiste municipio selecionado pra proxima visita lembrar
  useEffect(() => {
    if (selectedMunicipioId && typeof window !== "undefined") {
      localStorage.setItem("pactha_last_municipio_id", selectedMunicipioId);
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

  // Guard super-admin: Sessoes / Service Tokens so para os donos do sistema.
  // Esconder o item de menu nao basta — a rota e digitavel.
  useEffect(() => {
    if (!user) return;
    const ehSuper = SUPER_ADMIN_EMAILS.has((user.email || "").trim().toLowerCase());
    if (!ehSuper && SUPER_ADMIN_ONLY.has(pathname)) {
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
    localStorage.removeItem("pactha_token");
    localStorage.removeItem("pactha_user");
    localStorage.removeItem("pactha_last_municipio_id"); // nao vazar municipio entre usuarios
    localStorage.removeItem("pactha_bi_scope"); // idem p/ escopo/periodo do BI
    localStorage.removeItem("pactha_bi_ano");
    router.push("/login");
  }, [router]);

  // O Painel de Indicadores ocupa a largura toda (e um BI, nao uma tela de
  // formulario): sem max-w-7xl e sem padding do container.
  const telaCheia = BI_ON && pathname === "/dashboard";

  return (
    <div className="flex h-screen overflow-hidden bg-base-200">
      {/* Desktop sidebar */}
      <aside
        className={`hidden flex-shrink-0 border-r border-base-300 bg-base-100 transition-[width] duration-200 lg:block ${
          sidebarRecolhida ? "w-16" : "w-64"
        }`}
      >
        <SidebarContent
          pathname={pathname}
          municipios={municipios}
          selectedMunicipioId={selectedMunicipioId}
          onMunicipioChange={handleMunicipioChange}
          user={user}
          onLogout={handleLogout}
          recolhida={sidebarRecolhida}
          onToggleRecolhida={toggleSidebar}
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
      {/* pactha-scroll reserva a canaleta da barra: sem isso, trocar de uma aba
          que rola para outra que nao rola desloca o conteudo lateralmente. */}
      <main className="pactha-scroll flex-1 overflow-y-auto">
        <div className={telaCheia ? "" : "mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8"}>
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
