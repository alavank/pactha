// ⭐⭐ O MENU LATERAL — E A FONTE DA ÁRVORE DE PERMISSÕES.
//
// Este arquivo saiu de dentro de `app/dashboard/layout.tsx` em 05/09/2026 por
// um motivo só, e ele é o pedido do dono:
//
//     "O modal de usuário mostra a árvore do jeito que está no menu lateral do
//      ambiente. Isso é dinâmico por cliente: cada município e cada estado tem
//      seu menu, o PACTHA é adaptado por cliente. Se o menu do cliente mudar
//      (módulo novo liberado, aba nova), a tela de permissões acompanha sem
//      código novo."
//
// Enquanto `NAV_ITEMS` morava no layout, a tela de Usuários desenhava a própria
// lista de chips a partir de `TELAS` — outra lista, com outra ordem e outros
// agrupamentos. As duas contavam histórias diferentes sobre o mesmo produto, e
// quem administra procurava "Diário Oficial" numa ordem que não era a que ele
// tinha acabado de ver no menu.
//
// Agora há UMA estrutura: o menu desenha a barra lateral E a árvore do modal.
// Módulo novo aparece nos dois no mesmo deploy, sem código novo.
//
// ⚠️ O QUE NÃO MORA AQUI: as AÇÕES de cada tela. Elas vêm do backend
// (`GET /api/permissoes/catalogo`), que é a fonte única delas — ver o cabeçalho
// de `lib/permissoes.ts`. Aqui está a ESTRUTURA (grupos, ordem, rótulos,
// rotas); lá está o que se pode FAZER em cada uma. `hrefToTela` é a dobradiça,
// e `backend/tests/test_arvore_segue_o_menu.py` quebra se os dois lados
// divergirem.

import {
  LayoutDashboard, LayoutGrid, FileText, Newspaper, Target, Landmark,
  Sparkles, Edit2, UserCircle2, FileSignature, ShieldCheck, HeartPulse,
  BarChart3, CalendarClock, Radar, HardHat, Users, ScrollText, Activity,
  KeyRound, SlidersHorizontal,
} from "lucide-react";
import { hrefToTela } from "@/lib/telas";

/* `destaque` marca o item que sai da fila e ganha cor propria — hoje so o
   Radar de Captacao. Nao e enfeite: e o unico item do menu que olha para
   FRENTE (prazo ainda aberto), enquanto todo o resto mostra instrumento ja
   celebrado. Ver o comentario no NAV_ITEMS. */
export type NavLeaf = {
  href: string;
  label: string;
  icon?: React.ComponentType<{ className?: string }>;
  destaque?: boolean;
  /** ⭐ TELAS QUE NÃO TÊM ITEM PRÓPRIO NO MENU, mas são permissão separada.
   *
   *  Hoje só o Painel: «Modo Tela (TV)» e «Gerar link público» são CAPACIDADES
   *  dele — botões dentro da tela, não linhas na barra lateral —, e o dono
   *  quis as três separadas desde 2026: *"um secretário pode precisar da TV da
   *  sala dele sem ter permissão de gerar um link que roda o município inteiro
   *  pelo WhatsApp"*.
   *
   *  ⚠️ SEM ESTE CAMPO ELAS SUMIAM DA ÁRVORE. A árvore percorre o menu, e o que
   *  não é folha não aparece — então `bi_tela` e `bi_link` existiam em
   *  `telas.ts`, no catálogo e no banco, e **não havia onde marcá-las**. O
   *  administrador não conseguia conceder nem tirar o Modo Tela.
   *  `test_arvore_segue_o_menu.py` as tinha numa lista de exceção, o que
   *  escondeu o buraco em vez de acusá-lo. */
  telasExtras?: string[];
  /** ⭐ TELA COM ABAS, CADA ABA COM A SUA PERMISSÃO (17/09/2026).
   *
   *  Hoje só «Emendas parlamentares»: juntou quatro telas numa, e o dono decidiu
   *  que cada aba continua cobrando a chave que já existia — ninguém ganha nem
   *  perde acesso. A folha não tem chave própria; ela aparece para quem tem
   *  QUALQUER uma das abas (`telasDoHref`), e na árvore de Usuários vira um
   *  grupo com uma linha por aba.
   *
   *  ⚠️ `tela` é chave de `telas.ts`; `rotulo` é o que a árvore escreve. */
  abas?: Array<{ tela: string; rotulo: string }>;
};
export type NavSection = { sectionLabel: string; children: NavLeaf[] };
export type NavGroup = {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  children: Array<NavLeaf | NavSection>;
};
export type NavEntry = NavLeaf | NavGroup;

// Com o BI ligado, o item "Dashboard" JA E o Painel de Indicadores (mesma rota).
// Antes havia um link separado logo acima da navegacao — dois menus para a
// mesma coisa. Ficou um so.
export const BI_ON = process.env.NEXT_PUBLIC_BI_MODULE === "1";

// ⭐ A ORDEM É A QUE O DONO DITOU (11/08/2026), e ela conta uma história: o
// PAINEL abre, as FONTES DE RECURSO vêm em bloco (federal, estadual,
// parlamentares, saúde, educação), a REGULARIDADE fecha o diagnóstico, e só
// então vêm as ferramentas de ENTREGA (relatório, IA, painéis, diário,
// documentos, gestão). Configurações não está aqui: é item próprio no fim da
// barra, com as telas de administração em abas (ver `GRUPO_CONFIGURACOES`).
//
// ⚠️ Os GRUPOS foram preservados — "Estaduais" e "Transfere Gov" continuam
// menus com seus submenus, como o dono confirmou.
export const NAV_ITEMS: NavEntry[] = [
  {
    href: "/dashboard",
    label: BI_ON ? "Painel de Indicadores" : "Dashboard",
    icon: BI_ON ? BarChart3 : LayoutDashboard,
    // As duas capacidades do Painel que se concedem separadas — ver
    // `telasExtras`. Jogar na TV e PUBLICAR um link sem login são decisões
    // diferentes de abrir o painel.
    telasExtras: ["bi_tela", "bi_link"],
  },
  /* ⭐ RADAR DE CAPTAÇÃO — FORA DE QUALQUER GRUPO, e logo abaixo do Painel
     (pedido do dono, 04/09/2026).
     Ele estava dentro de FEDERAIS, abrindo o grupo, e ali competia com sete
     telas que mostram o que JÁ FOI ASSINADO. Esta é a única que olha para
     FRENTE: programas com janela de proposta ainda aberta. */
  {
    href: "/dashboard/transferegov-radar",
    label: "Radar de captação",
    icon: Radar,
    destaque: true,
  },
  /* ⭐ FEDERAIS / ESTADUAIS, EM MAIÚSCULO (pedido do dono, 28/08/2026): o que o
     sistema mostra são emendas e convênios por ESFERA. */
  {
    label: "FEDERAIS",
    icon: Landmark,
    children: [
      /* «Em execução» e não «Geral» (pedido do dono): a tela sempre mostrou os
         instrumentos JÁ CELEBRADOS. A rota continua `transferegov-geral` de
         propósito: renomeá-la quebraria URLs salvas e os links que o PAC monta
         por `categoria`. */
      { href: "/dashboard/transferegov-geral", label: "Em execução" },
      { href: "/dashboard/transferegov", label: "Especiais" },
      { href: "/dashboard/transferegov-pac", label: "PAC (Novo PAC)" },
      { href: "/dashboard/transferegov-voluntarias", label: "Voluntárias" },
      /* ⭐ PARCERIAS (07/09/2026). O módulo do Transferegov onde as
         transferências passaram a ser processadas de 2024 em diante — 144 dos
         176 programas publicados são Fundo a Fundo da Saúde. É onde mora a
         emenda de saúde do município, com o parlamentar nomeado.
         ⚠️ Vem logo depois de «Voluntárias» de propósito: são os dois lados da
         mesma pergunta. Aquela mostra o convênio discricionário do SICONV,
         que continua vindo dos dumps CSV; esta, o instrumento novo. */
      { href: "/dashboard/parcerias", label: "Parcerias (emendas de saúde)" },
      /* ⭐ PLANOS DE AÇÃO FUNDO A FUNDO (07/09/2026). O «Fundo Nacional de
         Saúde», na pasta SAÚDE, conta o repasse que ENTRA; esta conta o plano
         que o justifica — e a decomposição que diz quanto daquele dinheiro
         veio de emenda, que é o número que o FNS não publica.
         ⚠️ Fica em FEDERAIS e não em SAÚDE de propósito: o módulo cobre TODO
         repasse fundo a fundo, e os 4 planos de Nova Palma são do Ministério
         da Cultura (Lei Aldir Blanc), não do SUS. */
      { href: "/dashboard/faf-planos", label: "Planos de Ação (Fundo a Fundo)" },
      { href: "/dashboard/transferegov-rejeitadas", label: "Rejeitadas" },
      { href: "/dashboard/transferegov-encerradas", label: "Encerradas" },
      { href: "/dashboard/transferegov-cnpj", label: "CNPJ" },
      /* «Emendas parlamentares» SAIU DAQUI em 17/09/2026: virou a aba Federais
         da tela única, logo abaixo de ESTADUAIS. */
    ],
  },
  {
    label: "ESTADUAIS",
    icon: FileText,
    children: [
      { href: "/dashboard/convenios", label: "Convênios" },
      { href: "/dashboard/repasses", label: "Repasses" },
      { href: "/dashboard/cofinanciamento", label: "Cofinanciamento Saúde" },
      { href: "/dashboard/monitoramento", label: "Monitoramento" },
      { href: "/dashboard/consulta-popular", label: "Consulta Popular" },
      { href: "/dashboard/programas-rs", label: "Programas do Estado" },
      { href: "/dashboard/funrigs", label: "Plano Rio Grande" },
      { href: "/dashboard/tce-rs", label: "TCE-RS" },
    ],
  },
  /* ⭐ EMENDAS PARLAMENTARES — UMA TELA COM ABAS (pedido do dono, 17/09/2026).
     Juntou Federais › Emendas parlamentares, Estaduais › Emendas Estaduais e
     Emendas Estaduais RS, e Parlamentares. Fica logo depois das esferas porque
     é a mesma pergunta — de onde vem o dinheiro —, vista pelo autor.
     ⚠️ `abas` é a permissão: cada uma com a chave que já existia. */
  { href: "/dashboard/emendas-parlamentares", label: "Emendas parlamentares", icon: UserCircle2, abas: [
    { tela: "emendas_federais", rotulo: "Federais" },
    { tela: "emendas", rotulo: "Estaduais (MG)" },
    { tela: "emendas_rs", rotulo: "Estaduais (RS)" },
    { tela: "parlamentares", rotulo: "Parlamentares" },
  ] },
  // ⭐ AGENDAMENTOS fica FORA dos grupos de esfera porque não é fonte de
  // recurso: é o trabalho da equipe SOBRE essas fontes.
  { href: "/dashboard/agendamentos", label: "Agendamentos", icon: CalendarClock },
  // ⭐ SAÚDE é um grupo porque a saúde é uma PASTA do município, não quatro
  // sistemas avulsos. O SIMEC fica FORA de propósito — é educação (FNDE).
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
  // ⭐ OBRAS é um grupo pelo mesmo motivo que SAÚDE é.
  //
  // ⚠️ O SISMOB APARECE AQUI **E** EM SAÚDE, o mesmo link nos dois lugares. Não
  // é engano: ele é as duas coisas (é obra e é saúde), e quem chega por "Saúde"
  // não é a mesma pessoa que chega por "Obras".
  //
  // ⚠️ NA ÁRVORE DE PERMISSÕES ISSO IMPORTA: a mesma tela em dois grupos daria
  // duas caixinhas para a mesma concessão. Quem resolve é `arvoreDoMenu`, que
  // deduplica por chave de tela e mantém a PRIMEIRA ocorrência.
  {
    label: "Obras",
    icon: HardHat,
    children: [
      { href: "/dashboard/obrasgov", label: "Obras Federais (Obras.gov.br)" },
      { href: "/dashboard/sismob", label: "Obras da Saúde (SISMOB)" },
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
];

/** ⭐ CONFIGURAÇÕES COMO GRUPO DA ÁRVORE.
 *
 *  Na barra lateral, Configurações é um item só que abre uma página com abas —
 *  e por isso não está em `NAV_ITEMS`. Na ÁRVORE DE PERMISSÕES ele precisa ser
 *  um grupo com as abas dentro, porque a regra do dono é explícita:
 *
 *      "Liberar «Configurações» inteiro não existe: libera-se a aba (Usuários,
 *       Auditoria etc.) e, dentro dela, as ações."
 *
 *  ⚠️ SERVICE TOKENS NÃO ESTÁ AQUI, e a ausência é a decisão: é credencial de
 *  MÁQUINA da Alavank, só super-admin. Oferecê-la na árvore seria prometer o que
 *  nenhum usuário de cliente pode receber — a mesma regra que mantém as
 *  caixinhas inertes fora da tela. */
export const GRUPO_CONFIGURACOES: NavGroup = {
  label: "Configurações",
  icon: SlidersHorizontal,
  children: [
    { href: "/dashboard/configuracoes/usuarios", label: "Usuários", icon: Users },
    { href: "/dashboard/configuracoes/auditoria", label: "Auditoria", icon: ScrollText },
    { href: "/dashboard/configuracoes/telemetria", label: "Telemetria", icon: Activity },
    { href: "/dashboard/configuracoes/cofre", label: "Cofre de Senhas", icon: KeyRound },
    { href: "/dashboard/configuracoes/sessoes", label: "Sessões (gov.br)", icon: KeyRound },
    { href: "/dashboard/configuracoes/frescor", label: "Status dos Dados", icon: Activity },
    { href: "/dashboard/configuracoes/parametros", label: "Parâmetros", icon: SlidersHorizontal },
  ],
};

/** O menu INTEIRO, como a árvore de permissões o enxerga: a barra lateral mais
 *  o grupo de Configurações. A ordem é a da barra, com Configurações no fim —
 *  que é onde ele está para quem administra. */
export const MENU_COMPLETO: NavEntry[] = [...NAV_ITEMS, GRUPO_CONFIGURACOES];

/** As chaves de tela que abrem uma rota — a dobradiça do guard e do filtro do
 *  menu. Rota comum: `[hrefToTela(href)]`. Folha com `abas`: as chaves das abas,
 *  e basta ter UMA (quem só tem Emendas Federais abre a tela e vê só aquela aba).
 *
 *  ⚠️ Compara pelo primeiro segmento, como `hrefToTela`: `?aba=` e subrotas
 *  não mudam a tela. */
export function telasDoHref(href: string): string[] {
  const seg = (h: string) => h.split("?")[0].replace(/^\/dashboard\/?/, "").split("/")[0];
  for (const item of MENU_COMPLETO) {
    const folhas = "children" in item
      ? item.children.flatMap((c) => ("sectionLabel" in c ? c.children : [c]))
      : [item];
    for (const f of folhas) {
      if (f.abas && seg(f.href) === seg(href)) return f.abas.map((a) => a.tela);
    }
  }
  return [hrefToTela(href)];
}

/** A pessoa pode abrir esta rota? `null` = sem limite (super-admin/carregando). */
export function podeAbrirRota(allowed: Set<string> | null, href: string): boolean {
  return !allowed || telasDoHref(href).some((t) => allowed.has(t));
}

/** Lista plana de hrefs (ordem da sidebar) — usada pelo guard de rota. */
export function allLeafHrefs(items: NavEntry[]): string[] {
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
