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
  // ⚠️ NAO EXISTE MAIS UMA TELA "suas". O painel oficial do MDS (Estrutura
  // SUAS) nao sumiu — ele mora DENTRO de "Painéis Municipais", ao lado do
  // Painel Municipalista, desde que os dois foram reunidos numa tela só. A
  // caixinha avulsa continuava aqui prometendo um controle que não controlava:
  // quem abria "Painéis Municipais" via o SUAS de qualquer forma, porque a
  // página não filtra painel por painel. Marcar ou desmarcar não mudava nada.
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
  // A trilha de auditoria tem chave PROPRIA em vez de viver so no papel de
  // admin: quem confere o que foi feito (controle interno, controladoria,
  // juridico) nao e — e nao deve ser — quem administra o sistema. Segregacao de
  // funcao e requisito das ISOs, nao preferencia de menu.
  // A tela e SOMENTE LEITURA; conceder esta chave nao da poder de mudar nada.
  // ⚠️ O rotulo tem de bater com `backend/services/telas_catalog.py`: a Central
  // monta o formulario de permissoes do cliente pelo catalogo do BACKEND, e o
  // formulario daqui pelo deste arquivo. Dois nomes para a mesma chave fazem o
  // administrador achar que sao duas permissoes diferentes.
  { key: "auditoria", label: "Auditoria (trilha de atividades)" },
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
 * null = acesso total (super-admin ou ainda carregando). Set = escopo da pessoa.
 */
export function allowedTelasOf(
  user: { role?: string; telas?: string[] | null } | null
): Set<string> | null {
  if (!user) return null; // carregando -> nao esconde nada ainda
  // Havia aqui um `if (user.role === "admin") return null`. Saiu porque o papel
  // deixou de conceder: o backend passou a mandar a lista REAL de todo mundo em
  // `telas`, e reserva `null` para quem de fato nao tem limite (o super-admin).
  //
  // Sem tirar, o menu do administrador continuaria mostrando as 24 telas mesmo
  // depois de o administrador ter 6 — e cada clique cairia num 403. E derivar do
  // papel aqui e derivar de novo o que o servidor ja decidiu: se as duas contas
  // divergirem, ganha a errada, porque a tela e a que a pessoa ve.
  //
  // Nao afrouxa nada: para o backend anterior, `role === "admin"` vinha com
  // `telas: null` de qualquer forma, e o `null` logo abaixo faz o mesmo.
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
