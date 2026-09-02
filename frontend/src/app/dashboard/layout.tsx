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
  ScrollText,
  Building2,
  ChevronsUpDown,
  Settings,
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
import {
  ABAS_CONFIGURACOES, ROTAS_LEGADAS_CONFIG, abasVisiveis,
} from "@/lib/configuracoes";
import { cofinanciamentoDaUf, consultaPopularDaUf, fonteEmendasEstaduais, programasDaUf, repassesDaUf, temConteudoEstadual, temDiarioEstadual } from "@/lib/estadual";
import { ehSuperAdmin } from "@/lib/conta";
import { CONSOLIDADO, MunicipioProvider, useMunicipio } from "@/contexts/MunicipioContext";
import { EnteAtendido, SUBTITULO_PACTHA } from "@/components/bi/Marca";
import UsoProvider from "@/components/UsoProvider";
import { encerrarSessao } from "@/lib/uso";

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

// ⭐ A ORDEM É A QUE O DONO DITOU (11/08/2026), e ela conta uma história: o
// PAINEL abre, as FONTES DE RECURSO vêm em bloco (federal, estadual,
// parlamentares, saúde, educação), a REGULARIDADE fecha o diagnóstico, e só
// então vêm as ferramentas de ENTREGA (relatório, IA, painéis, diário,
// documentos, gestão). Configurações não está aqui: virou item próprio no fim
// da barra, com as telas de administração em abas (lib/configuracoes.ts).
//
// ⚠️ Os GRUPOS foram preservados — "Estaduais" e "Transfere Gov" continuam
// menus com seus submenus, como o dono confirmou. Reordenar folhas soltas
// dentro deles não estava no pedido, e os condicionais por UF (Repasses e
// Cofinanciamento só em GO; ver o filtro mais abaixo) dependem dessa estrutura.
const NAV_ITEMS: NavEntry[] = [
  {
    href: "/dashboard",
    label: BI_ON ? "Painel de Indicadores" : "Dashboard",
    icon: BI_ON ? BarChart3 : LayoutDashboard,
  },
  /* ⭐ FEDERAIS / ESTADUAIS, EM MAIÚSCULO (pedido do dono, 28/08/2026): o que o
     sistema mostra são emendas e convênios por ESFERA — federais, estaduais e,
     mais à frente, municipais. "Transfere Gov" era o nome da fonte, não da
     divisão; a fonte passa a aparecer no card de cada proposta. */
  {
    label: "FEDERAIS",
    icon: Landmark,
    children: [
      /* «Em execução» e não «Geral» (pedido do dono): a tela sempre mostrou os
         instrumentos JÁ CELEBRADOS, e «Geral» prometia um apanhado de tudo —
         quem clicava esperando a visão completa achava que faltava dado. A rota
         continua `transferegov-geral` de propósito: renomeá-la quebraria URLs
         salvas e os links que o PAC monta por `categoria`. */
      /* ⭐ O RADAR ABRE O GRUPO porque é a única tela federal que olha para
         FRENTE. Todas as outras mostram instrumento já celebrado; esta mostra o
         prazo que ainda está aberto — e prazo que vence não espera a ordem
         alfabética. Enterrá-la no fim da lista seria pedir ao gestor que
         descobrisse a oportunidade depois de conferir o que já assinou. */
      { href: "/dashboard/transferegov-radar", label: "Radar de captação" },
      { href: "/dashboard/transferegov-geral", label: "Em execução" },
      { href: "/dashboard/transferegov", label: "Especiais" },
      { href: "/dashboard/transferegov-pac", label: "PAC (Novo PAC)" },
      { href: "/dashboard/transferegov-voluntarias", label: "Voluntárias" },
      { href: "/dashboard/transferegov-rejeitadas", label: "Rejeitadas" },
      { href: "/dashboard/transferegov-encerradas", label: "Encerradas" },
      { href: "/dashboard/transferegov-cnpj", label: "CNPJ" },
    ],
  },
  {
    label: "ESTADUAIS",
    icon: FileText,
    children: [
      { href: "/dashboard/convenios", label: "Convênios" },
      { href: "/dashboard/emendas", label: "Emendas Estaduais" },
      { href: "/dashboard/repasses", label: "Repasses" },
      { href: "/dashboard/cofinanciamento", label: "Cofinanciamento Saúde" },
      { href: "/dashboard/consulta-popular", label: "Consulta Popular" },
      { href: "/dashboard/programas-rs", label: "Programas do Estado" },
      { href: "/dashboard/funrigs", label: "Plano Rio Grande" },
      { href: "/dashboard/emendas-rs", label: "Emendas Estaduais RS" },
      { href: "/dashboard/tce-rs", label: "TCE-RS" },
    ],
  },
  { href: "/dashboard/parlamentares", label: "Parlamentares", icon: UserCircle2 },
  // ⭐ SAÚDE é um grupo porque a saúde é uma PASTA do município, não quatro
  // sistemas avulsos. Quem cuida do fundo municipal de saúde abre as quatro
  // telas no mesmo dia; espalhadas na barra, cada uma parecia um assunto
  // diferente. O SIMEC fica FORA de propósito — é educação (FNDE).
  {
    label: "Saúde",
    icon: HeartPulse,
    children: [
      { href: "/dashboard/fns", label: "Fundo Nacional de Saúde" },
      { href: "/dashboard/sismob", label: "Obras da Saúde (SISMOB)" },
      { href: "/dashboard/investsus", label: "InvestSUS" },
      { href: "/dashboard/acordofes", label: "Acordo FES (Dívida Saúde)" },
    ],
  },
  { href: "/dashboard/simec", label: "SIMEC - PAR (MEC)", icon: Target },
  { href: "/dashboard/cauc", label: "Regularidade", icon: ShieldCheck },
  { href: "/dashboard/rm", label: "Relatório de Monitoramento", icon: FileText },
  { href: "/dashboard/ai", label: "IA PACTHA", icon: Sparkles },
  { href: "/dashboard/paineis", label: "Painéis Municipais", icon: LayoutGrid },
  { href: "/dashboard/dou", label: "Diário Oficial", icon: Newspaper },
  { href: "/dashboard/documentos", label: "Geração de Documentos", icon: FileSignature },
  { href: "/dashboard/gestao", label: "Gestão Interna", icon: Edit2 },
  // Telegram desativado até segunda ordem (ver lib/telas.ts) — o item fica
  // atrás da mesma flag para sumir também de quem já tinha a permissão antiga.
  ...(process.env.NEXT_PUBLIC_TELEGRAM_MODULE === "1"
    ? [{ href: "/dashboard/telegram", label: "Telegram", icon: Send }]
    : []),
  // Cofre de Senhas e Sessões (gov.br) SAÍRAM daqui: viraram abas de
  // Configurações. As rotas antigas continuam existindo (bookmark não quebra).
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

// ⚠️ A SEÇÃO "Administração" VIROU UM ITEM SÓ — "Configurações", com as telas em
// abas (ver `lib/configuracoes.ts`). Esta lista continua existindo por UM
// motivo: as rotas ANTIGAS (/dashboard/usuarios, /frescor, /service-tokens)
// seguem no ar para não quebrar bookmark, e o guard de rota precisa saber que
// elas não têm chave de tela — senão o administrador é EXPULSO da própria tela
// de Usuários ao abrir um link salvo. Ela não desenha mais nada no menu.
const ADMIN_NAV_ITEMS: AdminNavItem[] = [
  { href: "/dashboard/usuarios", label: "Usuários", icon: Users },
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
// O match é EXATO, então cada variante de rota precisa constar: as antigas (que
// continuam no ar) e as novas de Configurações.
const SUPER_ADMIN_ONLY = new Set<string>([
  "/dashboard/sessoes", "/dashboard/service-tokens",
  "/dashboard/configuracoes/sessoes", "/dashboard/configuracoes/service-tokens",
]);

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
// Soma as duas famílias: as rotas antigas sem chave de tela e as abas de
// Configurações sem chave de tela — mais a RAIZ `/dashboard/configuracoes`, que
// não tem tela própria (ela só redireciona para a primeira aba visível).
const ROTAS_SEM_TELA = new Set<string>([
  ...ADMIN_NAV_ITEMS.filter((i) => !i.tela).map((i) => i.href),
  ...ABAS_CONFIGURACOES.filter((a) => !a.tela).map((a) => a.href),
  "/dashboard/configuracoes",
]);

function SidebarContent({
  pathname,
  municipios,
  selectedMunicipioId,
  escopo,
  onAbrirTroca,
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
  /** Abre o modal de troca (escolha + aviso na mesma caixa). */
  onAbrirTroca: () => void;
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
  /* TELAS QUE DEPENDEM DA FONTE DO ESTADO. O Diário Oficial tem provedor por UF
     (MG = Jornal Minas Gerais, ES = DOM/ES, RS = DOE-RS), então segue
     `temDiarioEstadual`: some em GO/TO até existir o provedor daquele estado —
     abrir a busca sem provedor iria ao diário errado. No consolidado (uf vazia)
     fica: a carteira pode conter município mineiro. */
  const ufAmbiente = (municipios.find((m) => String(m.id) === selectedMunicipioId)?.uf || "")
    .toUpperCase();
  if (ufAmbiente && ufAmbiente !== "MG") {
    visibleNav = visibleNav.filter((it) => {
      if (!("href" in it)) return true;
      if (it.href === "/dashboard/dou") return temDiarioEstadual(ufAmbiente);
      return true;
    });
  }
  /* "Repasses" é a tela dos estados que publicam EXECUÇÃO em vez de
     instrumento (hoje só GO). Some em MG/ES — lá o que existe é convênio, e um
     menu que abre sempre vazio ensina o usuário a ignorar o menu. No
     consolidado (uf vazia) fica, porque a carteira pode ter município goiano. */
  /* Telas que só existem onde há a fonte daquela UF. Uma lista, e não um `if`
     por tela: entrar com a próxima é acrescentar uma linha aqui. */
  const semFonteNaUf = new Set<string>();
  /* ⚠️ O Acordo FES MUDOU DE MECANISMO ao entrar no grupo Saúde, e não é
     detalhe: o filtro logo acima só enxerga item de PRIMEIRO NÍVEL (`"href" in
     it`), então dentro de um grupo ele deixaria de esconder — e a dívida do FES
     de Minas apareceria para o cliente gaúcho e para o capixaba. Aqui embaixo o
     filtro desce em grupos e seções, que é o que o caso passou a exigir. */
  if (ufAmbiente && ufAmbiente !== "MG") semFonteNaUf.add("/dashboard/acordofes");
  if (ufAmbiente && !repassesDaUf(ufAmbiente)) semFonteNaUf.add("/dashboard/repasses");
  if (ufAmbiente && !cofinanciamentoDaUf(ufAmbiente)) semFonteNaUf.add("/dashboard/cofinanciamento");
  // Emendas estaduais: hoje só MG tem coletor. Num cliente gaúcho a tela abria
  // vazia anunciando o "SIGCON-MG" — e no RS a emenda estadual nem é impositiva,
  // então além de vazia ela sugeria um direito que não existe lá.
  if (ufAmbiente && !fonteEmendasEstaduais(ufAmbiente)) semFonteNaUf.add("/dashboard/emendas");
  // Consulta Popular: mecanismo do RS. Em qualquer outra UF a tela abriria vazia
  // anunciando algo que não existe naquele estado.
  if (ufAmbiente && !consultaPopularDaUf(ufAmbiente)) semFonteNaUf.add("/dashboard/consulta-popular");
  // Catálogo de programas: existe onde há conteúdo curado daquele estado.
  if (ufAmbiente && !programasDaUf(ufAmbiente)) semFonteNaUf.add("/dashboard/programas-rs");
  // As três telas de conteúdo estadual (fundo de reconstrução, emendas do estado
  // e obrigações do tribunal de contas) só existem onde há conteúdo curado.
  if (ufAmbiente && !temConteudoEstadual(ufAmbiente)) {
    semFonteNaUf.add("/dashboard/funrigs");
    semFonteNaUf.add("/dashboard/emendas-rs");
    semFonteNaUf.add("/dashboard/tce-rs");
  }
  if (semFonteNaUf.size) {
    const semRepasses = (c: NavLeaf | NavSection): NavLeaf | NavSection | null => {
      // ⚠️ O filho de um grupo pode ser uma SEÇÃO (que não tem `href`, e sim
      // uma lista própria). Filtrar só por `c.href` deixaria de fora o item
      // aninhado — e o TypeScript pega isso, que foi o que aconteceu aqui.
      if ("sectionLabel" in c) {
        const kids = c.children.filter((l) => !semFonteNaUf.has(l.href));
        return kids.length ? { ...c, children: kids } : null;
      }
      return semFonteNaUf.has(c.href) ? null : c;
    };
    visibleNav = visibleNav
      .map((it) => {
        if (!("children" in it)) return it;
        const filhos = it.children
          .map(semRepasses)
          .filter((c): c is NavLeaf | NavSection => c !== null);
        return { ...it, children: filhos };
      })
      .filter((it) => !("children" in it) || it.children.length > 0);
  }
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
  // As abas que ESTA pessoa vê em Configurações. A conta (e a lista) moram em
  // `lib/configuracoes.ts` — a barra de abas de lá usa a MESMA função, então o
  // menu e a página nunca discordam sobre quem vê o quê.
  const abasConfig = abasVisiveis(user, allowed);
  // O item do menu leva direto para a PRIMEIRA aba visível: quem só tem Cofre
  // cai no Cofre, e não numa raiz que redireciona (um salto a menos, e nada
  // pisca).
  const hrefConfig = abasConfig[0]?.href ?? "/dashboard/configuracoes";
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
            /* NÃO É MAIS UM DROPDOWN — é o gatilho do MODAL de troca
               (`TransicaoMunicipio`, fase de escolha). Duas tentativas de
               dropdown falharam pelo mesmo motivo estrutural: 44 municípios não
               cabem numa lista de canto — ela abria colada no menu, encostava
               no rodapé e "parecia erro na página" (dono, 09 e 10/08). No modal
               a lista tem corpo, ganha BUSCA e o aviso de troca acontece na
               mesma caixa, sem dois pop-ups em sequência.
               ⚠️ NÃO EXISTE "Consolidado (todos)", e é decisão do dono. Numa
               assessoria os municípios são CLIENTES DIFERENTES: somar as
               carteiras numa tela só não tem uso legítimo e cria a chance de
               ler o número de um cliente achando que é de outro — o risco que a
               transição (aviso + remontagem) existe para fechar. */
            <button
              type="button"
              onClick={onAbrirTroca}
              title="Trocar de município"
              aria-haspopup="dialog"
              className="flex w-full items-center gap-2 rounded-lg border border-base-300 bg-base-100 px-2.5 py-2 text-left text-sm transition-colors hover:border-base-content/25 focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/20 focus-visible:outline-none"
            >
              <Building2 className="size-4 shrink-0 text-primary" />
              <span className="min-w-0 flex-1 truncate font-medium text-base-content">
                {municipios.find((m) => String(m.id) === escopo)
                  ? `${municipios.find((m) => String(m.id) === escopo)!.nome} - ${
                      municipios.find((m) => String(m.id) === escopo)!.uf}`
                  : "Escolher município"}
              </span>
              <ChevronsUpDown className="size-3.5 shrink-0 text-base-content/40" />
            </button>
          )}
        </div>
      )}

      {/* Navegacao */}
      <nav className={`flex-1 space-y-0.5 py-3 overflow-y-auto ${recolhida ? "px-1.5" : "px-2"}`}>
        {!recolhida && (
          <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-wider text-base-content/40">
            Módulos
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

        {/* ⚙️ CONFIGURAÇÕES — último item, e um só. A seção "Administração" com
            quatro links soltos virou esta porta única; as telas viraram abas lá
            dentro (Usuários · Auditoria · Cofre · Sessões · Service Tokens ·
            Status dos Dados · Parâmetros). Quem não vê nenhuma aba não vê o
            item — a mesma conta de antes, agora num lugar só. */}
        {abasConfig.length > 0 && (() => {
          const isActive = pathname.startsWith("/dashboard/configuracoes")
            // As rotas ANTIGAS continuam no ar (bookmarks) e são as mesmas
            // telas: com uma delas aberta, o item precisa aparecer aceso.
            || ROTAS_LEGADAS_CONFIG.some((r) => pathname === r || pathname.startsWith(`${r}/`));
          if (recolhida) {
            return (
              <>
                <div className="my-2 border-t border-base-300" />
                <Link
                  href={hrefConfig}
                  title="Configurações"
                  aria-label="Configurações"
                  className={`flex items-center justify-center rounded-lg py-2 transition-all ${
                    isActive ? "bg-warning/15 text-warning" : "text-base-content/60 hover:bg-base-200"
                  }`}
                >
                  <Settings className="size-[18px]" />
                </Link>
              </>
            );
          }
          return (
            <Link
              href={hrefConfig}
              className={`mt-4 flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all ${
                isActive
                  ? "bg-warning/15 text-warning font-semibold"
                  : "text-base-content/70 hover:bg-base-200 hover:text-base-content"
              }`}
            >
              <Settings className={`size-4 ${isActive ? "text-warning" : "text-base-content/50"}`} />
              <span className="text-[13px]">Configurações</span>
            </Link>
          );
        })()}
      </nav>

      {/* Footer institucional */}
      <div className={`border-t border-base-300 py-3 bg-base-200/50 ${recolhida ? "px-1.5" : "px-3"}`}>
        {user && !recolhida && (
          <div className="mb-2 px-2 py-2 rounded-lg bg-base-100 border border-base-300">
            <div className="text-[10px] uppercase tracking-wider text-base-content/40">
              Usuário
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
  const { municipioId: selectedMunicipioId, escopo, setMunicipioId,
          abrirTroca, registrarMunicipios } = useMunicipio();
  const [municipios, setMunicipios] = useState<Municipio[]>([]);

  /* A lista de municípios vive AQUI (veio de `GET /api/municipios`, já filtrada
     por ativos e pelo escopo do usuário) e o modal de troca vive no provider —
     este efeito é a ponte. Entregar a lista em vez de o provider buscá-la
     sozinho evita duplicar requisição e, pior, duplicar a regra de permissão. */
  useEffect(() => {
    registrarMunicipios(
      municipios.map((m) => ({ id: m.id, nome: m.nome, uf: m.uf })),
    );
  }, [municipios, registrarMunicipios]);
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
          /* ⚠️ O CONSOLIDADO NÃO É MAIS ESTADO VÁLIDO — o seletor deixou de
             oferecê-lo (ver o comentário no <select>). Esta linha é o RESGATE de
             quem já está nele: o valor sobrevive no localStorage e voltaria a
             cada carregamento, deixando a pessoa numa tela sem opção de sair. Ao
             falhar aqui, cai no município anterior (ou no primeiro da lista). */
          const isValid = escopo !== CONSOLIDADO
            && !!selectedMunicipioId && data.some(m => String(m.id) === selectedMunicipioId);
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
    // ⚠️ AS ABAS COM TELA ENTRAM NA LISTA — e agora isso importa mais do que
    // antes: Cofre e Sessões saíram do menu comum e viraram abas, então quem
    // tem SÓ o Cofre não tem mais nenhum destino em `NAV_ITEMS`. Sem esta
    // linha, `find` devolveria undefined e a pessoa ficaria parada numa tela
    // que não pode ver.
    const destinos = [
      ...allLeafHrefs(NAV_ITEMS),
      ...ABAS_CONFIGURACOES.filter((a) => a.tela).map((a) => a.href),
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

  /* ⭐ A troca deixou de ser instantânea, e a demora é o ponto: escolher, avisar,
     remontar a árvore e cair na tela inicial do destino. Quem faz tudo isso é o
     `MunicipioContext` (a caixa é dele) — daqui só se PEDE, com `abrirTroca`.
     Ver o cabeçalho de lá para o motivo (documento e senha eram gravados no
     município errado). */

  const handleLogout = useCallback(async () => {
    // ⚠️ A TELEMETRIA FECHA A SESSAO **ANTES** do logout, e a ordem e o ponto:
    // `/auth/logout` limpa o cookie de autenticacao, e depois disso o envio
    // tomaria 401 — a sessao ficaria eternamente "aberta" no painel, morrendo
    // so por expiracao 2 minutos depois, e o evento `sessao.encerrada` (com
    // duracao, tempo ativo e ocioso) nunca seria gravado na trilha.
    //
    // `await` de proposito: e o unico momento em que vale segurar o clique por
    // uma fracao de segundo, porque e a ULTIMA chance de contar o que aconteceu
    // nesta sessao. Se falhar, `encerrarSessao` engole sozinha e o logout segue
    // — metrica nunca impede alguem de sair.
    await encerrarSessao();
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
          onAbrirTroca={abrirTroca}
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
          <SheetTitle className="sr-only">Menu de navegação</SheetTitle>
          <SidebarContent
            pathname={pathname}
            municipios={municipios}
            selectedMunicipioId={selectedMunicipioId}
            escopo={escopo}
            /* A gaveta fecha ANTES de o modal abrir: os dois são camadas
               flutuantes, e deixar a gaveta atrás do modal empilharia dois véus
               escuros e prenderia o foco no lugar errado. */
            onAbrirTroca={() => { setMobileOpen(false); abrirTroca(); }}
            user={user}
            onLogout={handleLogout}
          />
        </SheetContent>
      </Sheet>

      {/* TELEMETRIA. Montado AQUI, e nao dentro do `<div key={escopo}>` logo
          abaixo: aquela chave remonta a arvore inteira a cada troca de
          municipio, e o coletor remontaria junto — picando a sessao em pedacos
          justamente no gesto mais interessante de medir. */}
      <UsoProvider />


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
