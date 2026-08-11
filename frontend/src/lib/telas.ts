// Telas/modulos da plataforma para o RBAC por tela.
// A chave (`key`) e o que fica salvo em user_telas; o backend valida por ela.
// O `hrefToTela` mapeia rotas da sidebar -> chave (todas as rotas transferegov* -> "transferegov").

export interface TelaDef {
  key: string;
  label: string;
}

export const TELAS: TelaDef[] = [
  // "dashboard" SAIU do catálogo (10/08/2026, pedido do dono): desde a fusão
  // de 29/07 o Painel de Indicadores É o /dashboard — duas entradas no modal
  // de permissões ("Dashboard" e "Painel de Indicadores") concediam a MESMA
  // home e só confundiam quem dá permissão. A implicação bi -> dashboard (em
  // allowedTelasOf, abaixo) continua cobrindo o guard de rota, e concessões
  // antigas gravadas com a chave "dashboard" seguem valendo — ela só não é
  // mais oferecida como opção nova.
  // ⭐ A ORDEM AQUI É A DO MENU LATERAL (pedido do dono, 11/08/2026): estes
  // chips são o que o administrador marca ao cadastrar alguém, e procurar
  // "Diário Oficial" numa ordem diferente da que ele acabou de ver no menu é
  // atrito puro. Menu e chips passam a contar a mesma história, na mesma
  // sequência. As três chaves do BI ficam juntas logo após o Painel, e as de
  // Configurações (Cofre, Sessões, Auditoria) fecham a lista — é a ordem das
  // abas de lá.
  { key: "bi", label: "Painel de Indicadores (BI)" },
  // Separadas de proposito: ver o painel, jogar na TV e PUBLICAR para fora sao
  // decisoes diferentes. Um secretario pode precisar da TV da sala dele sem ter
  // permissao de gerar um link que roda o municipio inteiro pelo WhatsApp.
  { key: "bi_tela", label: "Modo Tela (TV) do BI" },
  { key: "bi_link", label: "Gerar link público da TV" },
  { key: "transferegov", label: "Transfere Gov" },
  // ⚠️ `convenios` governa TAMBÉM a tela de Repasses (/dashboard/repasses):
  // é a mesma família de informação (recurso estadual), e o backend gateia as
  // duas por `convenios.ver`. Chave nova aqui exigiria conceder duas permissões
  // para a mesma coisa.
  { key: "convenios", label: "Convênios Estaduais" },
  { key: "emendas", label: "Emendas Estaduais" },
  { key: "parlamentares", label: "Parlamentares" },
  { key: "fns", label: "Fundo Nacional de Saúde" },
  { key: "sismob", label: "Obras da Saúde (SISMOB)" },
  { key: "simec", label: "SIMEC - PAR (MEC)" },
  { key: "acordofes", label: "Acordo FES (dívida saúde MG)" },
  { key: "cauc", label: "Regularidade (federal e estadual)" },
  { key: "rm", label: "Relatório de Monitoramento" },
  { key: "ai", label: "IA PACTHA" },
  // ⚠️ NAO EXISTE MAIS UMA TELA "suas". O painel oficial do MDS (Estrutura
  // SUAS) nao sumiu — ele mora DENTRO de "Painéis Municipais", ao lado do
  // Painel Municipalista, desde que os dois foram reunidos numa tela só. A
  // caixinha avulsa continuava aqui prometendo um controle que não controlava:
  // quem abria "Painéis Municipais" via o SUAS de qualquer forma, porque a
  // página não filtra painel por painel. Marcar ou desmarcar não mudava nada.
  { key: "paineis", label: "Painéis Municipais" },
  { key: "dou", label: "Diário Oficial" },
  { key: "documentos", label: "Geração de Documentos" },
  { key: "gestao", label: "Gestão Interna" },
  // TELEGRAM DESATIVADO ATÉ SEGUNDA ORDEM (decisão do dono, 09/08/2026): o
  // canal de avisos será WhatsApp com API oficial; Telegram só voltará sob
  // demanda rara de cliente. Fora do catálogo = fora do menu, fora do modal
  // de permissões e fora da criação de usuário. O código fica; religar =
  // NEXT_PUBLIC_TELEGRAM_MODULE=1 (build-time) + TELEGRAM_MODULE=1 na API.
  ...(process.env.NEXT_PUBLIC_TELEGRAM_MODULE === "1"
    ? [{ key: "telegram", label: "Telegram" }]
    : []),
  // As três de CONFIGURAÇÕES (a ordem das abas de lá). As outras abas —
  // Usuários, Service Tokens, Status dos Dados, Parâmetros — não têm chave de
  // tela de propósito: quem as governa é o papel de administrador no backend.
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
  // ⭐ AS ABAS DE CONFIGURAÇÕES SÃO AS MESMAS TELAS, e por isso o prefixo cai
  // ANTES de qualquer outra conta: `/dashboard/configuracoes/cofre` tem de dar
  // "cofre", exatamente como `/dashboard/cofre` dava. Sem este colapso, a chave
  // viraria "configuracoes" — que não existe em catálogo nenhum — e o guard de
  // rota expulsaria da aba justamente quem tem a permissão certa.
  const semPrefixo = href.replace(/^\/dashboard\/configuracoes(?=\/|$)/, "/dashboard");
  // "/dashboard" -> "dashboard"
  const seg = semPrefixo.replace(/^\/dashboard\/?/, "").split("/")[0] || "dashboard";
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
