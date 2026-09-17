// O ÍCONE DE CADA TELA — um mapa, para o título não depender de quem escreveu.
//
// Pedido do dono em 07/09/2026, olhando o sistema inteiro: *"deixe todos em
// tamanho 24px e sempre tenha um ícone para cada título; fica bem bonitinho os
// que têm — Regularidade tem um escudinho, Obras tem um capacetinho,
// Parlamentares já não tem. Sempre ter um fica bem legal, mesmo que repetir
// alguns não tem problema."*
//
// ⚠️ POR QUE UM MAPA, E NÃO O ÍCONE DO MENU. Seria mais elegante ler de
// `NAV_ITEMS`, e a primeira tentativa foi essa — mas **só 15 das 47 rotas têm
// ícone lá**: as folhas dentro de um grupo (FEDERAIS, ESTADUAIS, Saúde, Obras)
// não têm nenhum, quem tem é o grupo. Ler do menu daria o mesmo Landmark para
// as onze telas federais, que é justamente o que o pedido não quer.
//
// ⚠️ REPETIR É PERMITIDO, E ÀS VEZES É O CERTO. `BadgeDollarSign` marca as três
// telas de emenda (federal, estadual e RS) porque são a mesma natureza de
// recurso em esferas diferentes; `HeartPulse` marca as quatro de saúde. A
// repetição aí não é preguiça: é o que agrupa visualmente telas que o menu já
// agrupa.
//
// ⚠️ O QUE ESTE MAPA NÃO É: uma segunda fonte de verdade sobre as ROTAS. Ele não
// decide o que existe nem quem vê o quê — isso é `lib/menu.ts` e o registro de
// permissões. Rota que não estiver aqui não quebra: cai no `PADRAO` abaixo.
import {
  Activity, Archive, ArrowLeftRight, BadgeDollarSign, BarChart3, Bookmark,
  Building2, CalendarClock, Coins, Edit2, FileSignature, FileText, HandCoins,
  Handshake, HardHat, HeartPulse, KeyRound, Landmark, LayoutGrid, Layers,
  LifeBuoy, Newspaper, Radar, Scale, ScrollText, Settings, ShieldCheck,
  SlidersHorizontal, Sparkles, Stethoscope, Target, UserCircle2, Users, Vote,
  Wallet, XCircle,
} from "lucide-react";

type Icone = React.ComponentType<{ className?: string; style?: React.CSSProperties }>;

/** O fallback. Existe para que uma rota nova apareça com ícone genérico em vez
 *  de voltar a ser o único título pelado do sistema. */
const PADRAO: Icone = FileText;

/* ⚠️ A ORDEM NÃO IMPORTA AQUI, mas o CASAMENTO É POR PREFIXO MAIS LONGO (ver
   `iconeDaTela`): `/dashboard/rm/123` acha `/dashboard/rm`, e
   `/dashboard/configuracoes/cofre` acha a entrada dele e não a de
   `/dashboard/configuracoes`. */
const ICONES: Record<string, Icone> = {
  "/dashboard": BarChart3,
  "/dashboard/transferegov-radar": Radar,

  // FEDERAIS — o grupo inteiro é Landmark no menu, então aqui cada tela ganha o
  // ícone do que ela mostra: o que está correndo, o que é emenda, o que parou.
  "/dashboard/transferegov-geral": Activity,      // em execução
  "/dashboard/transferegov": Coins,               // Transferência Especial (RP9)
  "/dashboard/transferegov-pac": Landmark,        // já era o da tela
  "/dashboard/transferegov-voluntarias": Handshake,
  "/dashboard/parcerias": HandCoins,              // o mesmo dos KPIs da tela
  "/dashboard/faf-planos": Wallet,                // idem
  "/dashboard/transferegov-rejeitadas": XCircle,
  "/dashboard/transferegov-encerradas": Archive,
  "/dashboard/transferegov-cnpj": Building2,      // já era o da tela
  "/dashboard/emendas-federais": BadgeDollarSign,

  // ESTADUAIS
  "/dashboard/convenios": FileText,
  "/dashboard/emendas": BadgeDollarSign,
  "/dashboard/repasses": ArrowLeftRight,
  "/dashboard/cofinanciamento": HeartPulse,
  "/dashboard/monitoramento": CalendarClock,      // já era o da tela
  "/dashboard/consulta-popular": Vote,
  "/dashboard/programas-rs": Layers,
  "/dashboard/funrigs": LifeBuoy,                 // Plano Rio Grande, a reconstrução
  "/dashboard/emendas-rs": BadgeDollarSign,
  "/dashboard/tce-rs": Scale,                     // tribunal de contas

  // A tela com abas (17/09/2026). As quatro rotas acima e abaixo que viraram
  // aba ficam no mapa: redirecionam, mas o histórico de uso ainda as cita.
  "/dashboard/emendas-parlamentares": UserCircle2,
  "/dashboard/agendamentos": CalendarClock,
  "/dashboard/parlamentares": UserCircle2,        // o que faltava, no print do dono

  // SAÚDE
  "/dashboard/fns": HeartPulse,
  "/dashboard/sismob": HardHat,                   // já era o da tela
  "/dashboard/investsus": Stethoscope,
  "/dashboard/acordofes": HeartPulse,             // já era o da tela

  // OBRAS
  "/dashboard/obrasgov": HardHat,

  "/dashboard/simec": Target,
  "/dashboard/cauc": ShieldCheck,                 // o "escudinho" que o dono citou
  "/dashboard/rm": FileText,
  "/dashboard/ai": Sparkles,
  "/dashboard/paineis": LayoutGrid,
  "/dashboard/dou": Newspaper,
  "/dashboard/documentos": FileSignature,
  "/dashboard/gestao": Edit2,

  // CONFIGURAÇÕES — as abas novas e as rotas antigas, que continuam no ar para
  // não quebrar bookmark (ver `ROTAS_LEGADAS_CONFIG`). As duas famílias apontam
  // para o mesmo ícone de propósito: é a mesma tela.
  "/dashboard/configuracoes": Settings,
  "/dashboard/configuracoes/usuarios": Users,
  "/dashboard/usuarios": Users,
  "/dashboard/configuracoes/auditoria": ScrollText,
  "/dashboard/auditoria": ScrollText,
  "/dashboard/configuracoes/telemetria": Activity,
  "/dashboard/configuracoes/cofre": KeyRound,
  "/dashboard/cofre": KeyRound,
  "/dashboard/configuracoes/sessoes": Bookmark,
  "/dashboard/sessoes": Bookmark,
  "/dashboard/configuracoes/frescor": Activity,
  "/dashboard/frescor": Activity,
  "/dashboard/configuracoes/service-tokens": KeyRound,
  "/dashboard/service-tokens": KeyRound,
  "/dashboard/configuracoes/parametros": SlidersHorizontal,
};

/** O ícone da tela em que se está. Casa pelo PREFIXO MAIS LONGO, então rota de
 *  detalhe (`/dashboard/rm/123`) herda o da lista, e uma aba de Configurações
 *  ganha o dela e não o da raiz. */
export function iconeDaTela(pathname: string | null | undefined): Icone {
  if (!pathname) return PADRAO;
  let achado: Icone | null = null;
  let maior = -1;
  for (const [rota, icone] of Object.entries(ICONES)) {
    if ((pathname === rota || pathname.startsWith(rota + "/")) && rota.length > maior) {
      achado = icone;
      maior = rota.length;
    }
  }
  return achado ?? PADRAO;
}
