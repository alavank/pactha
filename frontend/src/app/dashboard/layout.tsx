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
  HardHat,
  ScrollText,
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
import { ehSuperAdmin } from "@/lib/conta";
import { CONSOLIDADO, MunicipioProvider, useMunicipio } from "@/contexts/MunicipioContext";
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
  { href: "/dashboard/cauc", label: "CAUC / CAGEC", icon: ShieldCheck },
  { href: "/dashboard/sismob", label: "Obras da Saúde (SISMOB)", icon: HardHat },
  { href: "/dashboard/acordofes", label: "Acordo FES (Divida Saude)", icon: HeartPulse },
  { href: "/dashboard/fns", label: "Fundo Nacional de Saude", icon: Target },
  { href: "/dashboard/simec", label: "SIMEC - PAR (MEC)", icon: Target },
  { href: "/dashboard/paineis", label: "Painéis Municipais", icon: LayoutGrid },
  { href: "/dashboard/dou", label: "Diario Oficial", icon: Newspaper },
  { href: "/dashboard/cofre", label: "Cofre de Senhas", icon: KeyRound },
  { href: "/dashboard/sessoes", label: "Sessoes (gov.br)", icon: KeyRound },
];

// A secao Administracao. O padrao aqui e "so admin ve", e por isso o bloco
// inteiro nasceu dentro de um `user?.role === "admin"`.
//
// `tela` e a excecao: o item que a declara passa a ser governado pela permissao
// POR TELA (`user_telas`), e nao pelo papel. Existe por causa da Auditoria —
// quem confere o que foi feito (controle interno, controladoria, juridico) nao
// deve precisar virar administrador do sistema para ler a trilha. Os demais
// itens continuam sem `tela` e presos ao papel, de proposito.
type AdminNavItem = NavLeaf & { icon: React.ComponentType<{ className?: string }>; tela?: string };

const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { href: "/dashboard/usuarios", label: "Usuarios", icon: Users },
  { href: "/dashboard/auditoria", label: "Auditoria", icon: ScrollText, tela: "auditoria" },
  { href: "/dashboard/frescor", label: "Status dos Dados", icon: Activity },
  { href: "/dashboard/service-tokens", label: "Service Tokens", icon: KeyRound },
];

// Itens visiveis SO para o super-admin (nao para os demais admins).
//
// Sao os DONOS do sistema, nao "mais um admin do cliente": quem administra a
// plataforma pela Alavank. Quem responde "esta conta e dona?" e `lib/conta.ts`
// — que le a coluna `users.super_admin` e so cai na lista de e-mails quando o
// campo nao veio. A lista morava AQUI, e era a quarta copia dela no produto.
const SUPER_ADMIN_ONLY = new Set<string>(["/dashboard/sessoes", "/dashboard/service-tokens"]);

// As rotas de Administracao que NAO tem chave de tela.
//
// `user_telas` nao governa estas tres: quem barra Usuarios, Status dos Dados e
// Service Tokens e o papel/super-admin, no backend. Enquanto `role === "admin"`
// zerava os limites, o guard de rota nunca chegava a olhar para elas — o
// conjunto de telas do admin era `null` e o guard saia na primeira linha. Agora
// que o admin tem uma lista finita como todo mundo, `hrefToTela("/dashboard/
// usuarios")` daria "usuarios", que nao existe em catalogo nenhum: o
// administrador seria EXPULSO da propria tela de Usuarios ao abri-la.
//
// Derivado de `ADMIN_NAV_ITEMS` de proposito: item novo sem `tela` ja nasce
// isento, e nao ha uma segunda lista para alguem esquecer de atualizar.
const ROTAS_SEM_TELA = new Set(
  ADMIN_NAV_ITEMS.filter((i) => !i.tela).map((i) => i.href),
);

function SidebarContent({
  pathname,
  municipios,
  selectedMunicipioId,
  escopo,
  onMunicipioChange,
  user,
  onLogout,
  recolhida = false,
  onToggleRecolhida,
}: {
  pathname: string;
  municipios: Municipio[];
  selectedMunicipioId: string;
  /** A escolha CRUA do seletor: `""`, `"<id>"` ou `CONSOLIDADO`. O
   *  `selectedMunicipioId` continua sendo o município concreto (vazio no
   *  consolidado), porque é dele que saem os links do menu. */
  escopo: string;
  onMunicipioChange: (value: string, rotulo: string) => void;
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
  // Sidebar so mostra as telas permitidas (acesso total/carregando = todas)
  const isSuper = ehSuperAdmin(user);
  const allowed = allowedTelasOf(user);
  let visibleNav = filterNav(NAV_ITEMS, allowed);
  if (!isSuper) {
    // Sessoes (captura gov.br) so p/ super-admin
    visibleNav = visibleNav.filter((it) => !("href" in it && SUPER_ADMIN_ONLY.has(it.href)));
  }
  // A secao Administracao. Nao e mais "admin ve tudo, os outros nao veem nada":
  // o item que declara `tela` obedece a permissao por tela, entao um usuario de
  // controle interno pode ter a Auditoria sem ter poder de administrador.
  //
  // ⚠️ Este `role === "admin"` SOBREVIVEU de proposito ao incremento que tirou do
  // papel o poder de conceder ESCOPO. Ele nao concede tela nenhuma: espelha o
  // `_require_admin` que os tres endpoints de administracao (usuarios, frescor,
  // service tokens) ainda aplicam no backend. Esconder o item de quem levaria
  // 403 e o certo — o dia em que aqueles endpoints deixarem de olhar o papel,
  // esta linha sai junto, e nao antes.
  const ehAdmin = user?.role === "admin";
  const adminNavVisivel = ADMIN_NAV_ITEMS.filter((item) => {
    if (!isSuper && SUPER_ADMIN_ONLY.has(item.href)) return false;
    if (item.tela) return ehAdmin || !!allowed?.has(item.tela);
    return ehAdmin;
  });
  return (
    <div className="flex h-full flex-col bg-base-100">
      {/* Faixa de identidade (ver .gov-stripe em globals.css) */}
      <div className="gov-stripe" />

      {/* Header: a marca do PRODUTO, sozinha. O brasão saiu daqui — ele agora
          acompanha o nome da cidade logo abaixo, como título do ente atendido.
          Os dois grudados num chip só embaralhavam quem é fornecedor e quem é
          cliente. No modo ícone fica só a logo: a assinatura não caberia. */}
      <div className={`border-b border-base-300 py-4 flex justify-center ${recolhida ? "px-1.5" : "px-3"}`}>
        <div
          /* `bg-white` e `ring-black/5` eram cor CRAVADA: no modo escuro
             viravam um retangulo branco no meio do menu preto, e nenhum dos
             dois seguia a troca de tema. Passam a token. */
          className={`flex max-w-full flex-col items-center gap-1 rounded-2xl ${
            recolhida ? "px-2 py-2" : "px-3 py-2"
          }`}
          style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}
        >
          {/* DUAS artes, uma por tema. A arte padrão tem a palavra em tinta
              PRETA e fundo transparente: ela só era legível porque a caixa aqui
              atrás tinha `bg-white` cravado. Ao trocar esse fundo por token
              (logo acima), a palavra "PACTHA" passou a dar 1,14 de contraste no
              tema escuro — ou seja, sumiu do topo do menu em TODA tela, e sobrou
              o símbolo flutuando. Consertei o fundo e a assinatura embaixo, e
              não olhei para a imagem no meio.
              O par já existia no repositório (`/pactha-logo-dark.png` + as
              regras `.marca-clara`/`.marca-escura` em globals.css); só o Painel
              o usava. Troca por CSS e não por estado do React, senão a arte
              errada pisca antes da hidratação. */}
          {(() => {
            const cls = recolhida
              ? "h-7 w-auto max-w-[36px] object-contain"
              : "h-6 w-auto max-w-[130px] object-contain";
            return (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/pactha-logo.png" alt="PACTHA" className={`marca-clara ${cls}`} />
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src="/pactha-logo-dark.png" alt="" aria-hidden="true" className={`marca-escura ${cls}`} />
              </>
            );
          })()}
          {!recolhida && (
            /* `text-black/55` era preto CRAVADO: funcionava porque a caixa da
               marca tinha fundo branco cravado tambem. Trocado o fundo por
               token, a assinatura ficaria preta sobre superficie escura — ou
               seja, invisivel no tema escuro. Vai junto para token. */
            <span className="text-center text-[9px] leading-tight" style={{ color: "var(--bi-muted)" }}>
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
            /* Multi-entidade (assessoria/parceiro): dropdown.
               ⭐ ESTE SELETOR MANDA NO SISTEMA INTEIRO, inclusive no Painel de
               Indicadores — que antes tinha escopo PRÓPRIO, guardado noutra
               chave. Dava para estar com um município aqui e outro no Painel ao
               mesmo tempo, com os dois seletores visíveis discordando. Numa
               carteira de clientes diferentes, isso é confundir dado. */
            <select
              className="select select-bordered select-sm w-full"
              value={escopo}
              onChange={(e) => {
                const v = e.target.value;
                const m = municipios.find((x) => String(x.id) === v);
                onMunicipioChange(v, m ? `${m.nome} - ${m.uf}` : "Consolidado (todos)");
              }}
            >
              <option value="">Município selecionado</option>
              {/* A carteira inteira. Só o Painel consolida — as telas
                  operacionais consultam um município por vez e, com este escopo,
                  recebem município vazio e pedem para escolher um. */}
              <option value={CONSOLIDADO}>Consolidado (todos)</option>
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
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-semibold w-full text-left hover:bg-base-200 transition-colors ${
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

        {adminNavVisivel.length > 0 && (
          <>
            {recolhida ? (
              <div className="my-2 border-t border-base-300" />
            ) : (
              <div className="px-3 mt-4 mb-2 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
                Administracao
              </div>
            )}
            {adminNavVisivel.map((item) => {
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
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
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
          <div className="mb-2 px-2 py-2 rounded-lg bg-base-100 border border-base-300">
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
  const { municipioId: selectedMunicipioId, escopo, setMunicipioId, trocarEscopo }
    = useMunicipio();
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
          /* O consolidado é válido — mas SÓ numa carteira. ⚠️ Com um município
             a barra lateral mostra o nome fixo, sem `<select>`: quem chegasse
             aqui em "Consolidado" (id herdado de outro tenant no localStorage,
             ou de quando tinha mais de um) ficaria preso, sem controle nenhum
             na tela para sair. Cair na validação devolve ele ao município. */
          const isValid = (escopo === CONSOLIDADO && data.length > 1)
            || (selectedMunicipioId && data.some(m => String(m.id) === selectedMunicipioId));
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

  // Guard de rota: sem acesso a tela atual -> 1a tela permitida.
  // Seguranca real e no backend (ensure_tela / 403); isto e UX.
  useEffect(() => {
    const allowed = allowedTelasOf(user);
    if (!allowed) return; // acesso total (super-admin) ou ainda carregando
    // Administracao nao e governada por `user_telas` (ver ROTAS_SEM_TELA).
    if (ROTAS_SEM_TELA.has(pathname)) return;
    if (allowed.has(hrefToTela(pathname))) return;
    // Os destinos incluem os itens de Administracao governados por TELA (hoje,
    // a Auditoria). Sem isso, um usuario cujo unico acesso e a trilha nao teria
    // para onde ser mandado: `find` devolveria undefined, nenhum redirect
    // aconteceria e ele ficaria parado numa tela que nao pode ver.
    const destinos = [
      ...allLeafHrefs(NAV_ITEMS),
      ...ADMIN_NAV_ITEMS.filter((i) => i.tela).map((i) => i.href),
    ];
    const firstAllowed = destinos.find((h) => allowed.has(hrefToTela(h)));
    if (firstAllowed && firstAllowed !== pathname) router.replace(firstAllowed);
  }, [user, pathname, router]);

  // Guard super-admin: Sessoes / Service Tokens so para os donos do sistema.
  // Esconder o item de menu nao basta — a rota e digitavel.
  useEffect(() => {
    if (!user) return;
    if (!ehSuperAdmin(user) && SUPER_ADMIN_ONLY.has(pathname)) {
      router.replace("/dashboard");
    }
  }, [user, pathname, router]);

  /* ⭐ A troca deixou de ser instantânea, e a demora é o ponto: ela abre o
     aviso, remonta a árvore e cai na tela inicial do destino. Quem faz isso é o
     `MunicipioContext` — aqui só se pede. Ver o cabeçalho de lá para o motivo
     (documento e senha eram gravados no município errado). */
  const handleMunicipioChange = trocarEscopo;

  const handleLogout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } catch {
      /* ignore */
    }
    localStorage.removeItem("pactha_token");
    // Sair do sistema leva TODA credencial da maquina, inclusive a de quiosque
    // que um link publico aberto aqui possa ter deixado.
    localStorage.removeItem("pactha_kiosk_token");
    localStorage.removeItem("pactha_user");
    localStorage.removeItem("pactha_last_municipio_id"); // nao vazar municipio entre usuarios
    localStorage.removeItem("pactha_bi_scope"); // idem p/ escopo/periodo do BI
    localStorage.removeItem("pactha_bi_ano");
    /* ⚠️ `pactha_bi_anos` é o multi-ano que substituiu o `pactha_bi_ano`, e
       ficou de fora quando nasceu: o PERÍODO do prefeito anterior sobrevivia à
       troca de usuário na mesma máquina. E as `pactha_m_*` guardam o filtro de
       cada link público aberto aqui. */
    localStorage.removeItem("pactha_bi_anos");
    for (const k of Object.keys(localStorage)) {
      if (k.startsWith("pactha_m_")) localStorage.removeItem(k);
    }
    router.push("/login");
  }, [router]);

  // O Painel de Indicadores ocupa a largura toda (e um BI, nao uma tela de
  // formulario): sem max-w-7xl e sem padding do container.
  const telaCheia = BI_ON && pathname === "/dashboard";

  // TELAS LARGAS. `max-w-7xl` da 1216px uteis, e a lista de propostas do
  // TransfereGov tem 12 colunas que pedem ~1440px. Faltando largura, nao existe
  // CSS de celula que resolva: ou o texto e cortado, ou a coluna vizinha e
  // esmagada. Estas telas sao GRADES DE DADOS, nao formularios — o limite de
  // leitura confortavel (~75 caracteres por linha) vale para paragrafo, nao
  // para tabela. As demais continuam em max-w-7xl de proposito.
  const TELAS_LARGAS = [
    "/dashboard/transferegov",   // cobre geral, cnpj, encerradas, rejeitadas,
                                 // voluntarias, pac e o modulo de especiais
    "/dashboard/convenios",      // 14 colunas
    "/dashboard/emendas",        // 11 colunas
  ];
  const telaLarga = TELAS_LARGAS.some((p) => pathname.startsWith(p));

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
          escopo={escopo}
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
            escopo={escopo}
            onMunicipioChange={(v, rotulo) => {
              handleMunicipioChange(v, rotulo);
              setMobileOpen(false);
            }}
            user={user}
            onLogout={handleLogout}
          />
        </SheetContent>
      </Sheet>

      {/* Main content */}
      {/* pactha-scroll reserva a canaleta da barra: sem isso, trocar de uma aba
          que rola para outra que nao rola desloca o conteudo lateralmente.

          `relative` NAO e decorativo — e o que faz esta area rolavel ser o BLOCO
          DE CONTENCAO do que estiver posicionado dentro dela. Sem ele, `main`, a
          casca e o `<body>` sao todos `static`, e qualquer descendente
          `position:absolute` se ancora no DOCUMENTO: deixa de ser cortado por
          este scroller e passa a esticar a pagina inteira.
          Foi o que aconteceu com a tela de Auditoria: cada linha de acao
          sensivel traz um `<span class="sr-only">` para o leitor de tela, e
          `sr-only` do Tailwind e `position:absolute`. Com 100 linhas, o ultimo
          span ficava a ~7000px e o documento ganhava uma SEGUNDA barra de
          rolagem — que rolava para uma area em branco, porque o conteudo de
          verdade mora aqui dentro, preso em `h-screen`. Medido no navegador:
          `window.scrollTo(0, 3000)` andava 3000px e o topo da viewport virava
          `<html>` puro. */}
      <main className="pactha-scroll relative flex-1 overflow-y-auto">
        {/* ⭐⭐ `key={escopo}` — A LINHA QUE FAZ "MUDA TUDO" SER VERDADE.
            Trocar de município era um `setState` que não desmontava nada: cada
            tela só refazia o que tivesse `municipioId` na dependência de um
            efeito. Sobreviviam formulário meio preenchido, modal aberto, filtro
            marcado e cache de detalhe — e em dois casos isso virava ESCRITA no
            cliente errado (um documento preenchido no município A salvo em B,
            uma credencial digitada para A gravada no cofre de B).
            Com a chave, a árvore inteira desmonta e nasce de novo. Não é
            otimização: é o que torna o isolamento verdadeiro POR CONSTRUÇÃO, em
            vez de depender de cada tela lembrar de se limpar. */}
        <div
          key={escopo}
          className={
            telaCheia ? ""
            : telaLarga ? "mx-auto max-w-[1600px] px-4 py-6 sm:px-6 lg:px-8"
            : "mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8"
          }
        >
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
