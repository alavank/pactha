// Telas/modulos da plataforma para o RBAC por tela.
// A chave (`key`) e o que fica salvo em user_telas; o backend valida por ela.
// O `hrefToTela` mapeia rotas da sidebar -> chave (todas as rotas transferegov* -> "transferegov").

export interface TelaDef {
  key: string;
  label: string;
}

export const TELAS: TelaDef[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "ai", label: "IA PACTHA" },
  { key: "telegram", label: "Telegram" },
  { key: "parlamentares", label: "Parlamentares" },
  { key: "gestao", label: "Gestão Interna" },
  { key: "rm", label: "Relatório de Monitoramento" },
  { key: "documentos", label: "Geração de Documentos" },
  { key: "convenios", label: "SIGCON (Estaduais)" },
  { key: "emendas", label: "Emendas Estaduais" },
  { key: "transferegov", label: "Transfere Gov" },
  { key: "cauc", label: "CAUC / CAGEC (regularidade federal e estadual)" },
  { key: "sismob", label: "Obras da Saúde (SISMOB)" },
  { key: "acordofes", label: "Acordo FES (dívida saúde MG)" },
  { key: "fns", label: "Fundo Nacional de Saúde" },
  { key: "simec", label: "SIMEC - PAR (MEC)" },
  { key: "suas", label: "Estrutura SUAS (MDS)" },
  { key: "paineis", label: "Painéis Municipais" },
  { key: "bi", label: "Painel de Indicadores (BI)" },
  // Separadas de proposito: ver o painel, jogar na TV e PUBLICAR para fora sao
  // decisoes diferentes. Um secretario pode precisar da TV da sala dele sem ter
  // permissao de gerar um link que roda o municipio inteiro pelo WhatsApp.
  { key: "bi_tela", label: "Modo Tela (TV) do BI" },
  { key: "bi_link", label: "Gerar link público da TV" },
  { key: "dou", label: "Diário Oficial" },
  { key: "cofre", label: "Cofre de Senhas" },
  { key: "sessoes", label: "Sessões (gov.br)" },
];

export const TELA_LABELS: Record<string, string> = Object.fromEntries(
  TELAS.map((t) => [t.key, t.label])
);

/** Deriva a chave de tela a partir de um href da sidebar. */
export function hrefToTela(href: string): string {
  // "/dashboard" -> "dashboard"
  const seg = href.replace(/^\/dashboard\/?/, "").split("/")[0] || "dashboard";
  if (seg.startsWith("transferegov")) return "transferegov";
  return seg;
}

/**
 * Conjunto de telas permitidas p/ um usuario.
 * null = acesso total (admin ou ainda carregando). Set = escopo do nao-admin.
 */
export function allowedTelasOf(
  user: { role?: string; telas?: string[] | null } | null
): Set<string> | null {
  if (!user) return null; // carregando -> nao esconde nada ainda
  if (user.role === "admin") return null; // admin ve tudo
  if (Array.isArray(user.telas)) {
    const set = new Set(user.telas);
    // O Painel de Indicadores foi FUNDIDO ao /dashboard (antes vivia em /bi).
    // Quem tinha so a tela "bi" continuaria batendo no guard de rota e seria
    // expulso da propria home — entao "bi" passa a valer "dashboard" tambem.
    if (set.has("bi")) set.add("dashboard");
    return set;
  }
  return null; // fallback seguro (sem info -> nao trava)
}
