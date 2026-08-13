import {
  Users, ScrollText, KeyRound, Activity, SlidersHorizontal,
} from "lucide-react";
import type { User } from "@/types";
import { ehSuperAdmin } from "@/lib/conta";

/** ⭐ AS ABAS DE CONFIGURAÇÕES — fonte única.
 *
 *  Seis telas que já existiam soltas no menu (Usuários, Auditoria, Cofre,
 *  Sessões, Service Tokens, Status dos Dados) viraram abas de uma página só, na
 *  ordem que o dono pediu (11/08/2026), mais a aba nova de Parâmetros.
 *
 *  ⚠️ AS PERMISSÕES NÃO MUDAM, e isso foi condição do pedido ("as permissões
 *  pra isso continuam do mesmo jeito lá em permissões de usuário"). Cada aba
 *  carrega exatamente o gate que a rota antiga tinha:
 *    · `tela`     — governada por `user_telas` (a mesma chave de antes);
 *    · `soAdmin`  — presa ao papel, como as rotas sem chave de tela sempre foram;
 *    · `soSuper`  — só os donos da plataforma.
 *  O backend não muda uma linha: quem barra de verdade continua sendo
 *  `ensure_tela` / `_require_admin` / `is_super_admin` em cada endpoint.
 */
export type AbaConfig = {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Chave de `user_telas` que libera a aba (quando existe). */
  tela?: string;
  /** Sem chave de tela: quem manda é o papel `admin`. */
  soAdmin?: boolean;
  /** Além do resto, só os donos da plataforma (Alavank). */
  soSuper?: boolean;
};

export const ABAS_CONFIGURACOES: AbaConfig[] = [
  { href: "/dashboard/configuracoes/usuarios", label: "Usuários", icon: Users, soAdmin: true },
  { href: "/dashboard/configuracoes/auditoria", label: "Auditoria", icon: ScrollText, tela: "auditoria" },
  { href: "/dashboard/configuracoes/telemetria", label: "Telemetria", icon: Activity, tela: "auditoria" },
  { href: "/dashboard/configuracoes/cofre", label: "Cofre de Senhas", icon: KeyRound, tela: "cofre" },
  { href: "/dashboard/configuracoes/sessoes", label: "Sessões (gov.br)", icon: KeyRound, tela: "sessoes", soSuper: true },
  { href: "/dashboard/configuracoes/service-tokens", label: "Service Tokens", icon: KeyRound, soAdmin: true, soSuper: true },
  { href: "/dashboard/configuracoes/frescor", label: "Status dos Dados", icon: Activity, soAdmin: true },
  { href: "/dashboard/configuracoes/parametros", label: "Parâmetros", icon: SlidersHorizontal, soAdmin: true },
];

/** As rotas ANTIGAS continuam montando as mesmas telas (bookmark não quebra) —
 *  este mapa existe para o guard de rota tratar as duas famílias igual. */
export const ROTAS_LEGADAS_CONFIG = [
  "/dashboard/usuarios", "/dashboard/auditoria", "/dashboard/cofre",
  "/dashboard/sessoes", "/dashboard/service-tokens", "/dashboard/frescor",
];

/** Quais abas ESTA pessoa vê. Replica exatamente a conta que o menu fazia
 *  antes — nem mais permissiva, nem menos:
 *   · com `tela`: administrador vê sempre; os demais, se tiverem a chave
 *     (era a regra da seção Administração para a Auditoria, e a do menu comum
 *     para Cofre e Sessões — `allowed == null` é super-admin/carregando);
 *   · sem `tela`: só papel `admin`;
 *   · `soSuper`: por cima de tudo, só os donos.
 */
export function abasVisiveis(
  user: User | null,
  allowed: Set<string> | null,
): AbaConfig[] {
  if (!user) return [];
  const ehAdmin = user.role === "admin";
  const ehSuper = ehSuperAdmin(user);
  return ABAS_CONFIGURACOES.filter((aba) => {
    if (aba.soSuper && !ehSuper) return false;
    if (aba.tela) return ehAdmin || allowed === null || allowed.has(aba.tela);
    return ehAdmin;
  });
}
