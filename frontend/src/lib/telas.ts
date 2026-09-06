// Telas/modulos da plataforma para o RBAC por tela.
// A chave (`key`) e o que fica salvo em user_telas; o backend valida por ela.
// O `hrefToTela` mapeia rotas da sidebar -> chave.
//
// ⭐⭐ UMA FOLHA DO MENU = UMA TELA = UM RECURSO DE PERMISSAO (05/09/2026).
//
// Ate aqui esta lista e o catalogo de permissoes (`backend/services/permissoes.py`)
// eram DUAS listas que nao casavam: 4 recursos sem tela nenhuma, 1 tela sem
// recurso nenhum, e — o pior — o grupo FEDERAIS inteiro (7 telas) e o grupo
// ESTADUAIS inteiro (10 telas) presos a UMA chave cada. O administrador marcava
// «Transfere Gov» e concedia sete telas sem saber que estava concedendo sete.
//
// O pedido do dono foi granularidade Modulo › Tela › Acao: «em Federais posso
// liberar Em execução e não PAC». Entao cada folha virou chave propria, e o
// backend passou a declarar `tela` em cada recurso do catalogo. Os dois lados
// sao conferidos por `backend/tests/test_arvore_segue_o_menu.py`.

export interface TelaDef {
  key: string;
  label: string;
  /** ⭐ EM QUE ESTADOS ESTA TELA EXISTE (pedido do dono, 08/2026). Ausente ou
   *  vazio = federal/nacional: aparece em qualquer tenant.
   *
   *  Serve à aba Usuários: no sistema de Santa Maria/RS não se oferece «Acordo
   *  FES (dívida saúde MG)», e no de Monte Sião/MG não se oferece módulo
   *  gaúcho. Assessoria multi-estado vê um cartão por estado da carteira (ver
   *  `agruparPorEstado` em `lib/estadual.ts`).
   *
   *  ⚠️ NÃO É TRAVA DE SEGURANÇA, é catálogo: quem separa o convênio do ES do
   *  convênio de GO continua sendo a lista de MUNICÍPIOS da pessoa.
   *
   *  ⚠️ TEM DE BATER com `ufs` de `backend/services/permissoes.py` — o teste
   *  `backend/tests/test_catalogo_por_uf.py` quebra se divergirem. E são
   *  LITERAIS de propósito, e não derivados dos mapas de `lib/estadual.ts`:
   *  derivado o teste não conseguiria ler a lista, e a divergência com o
   *  backend voltaria a ser silenciosa. O comentário de cada linha diz de qual
   *  mapa de lá a UF veio. */
  ufs?: string[];
}

export const TELAS: TelaDef[] = [
  // ⭐ A ORDEM AQUI É A DO MENU LATERAL (pedido do dono, 11/08/2026): estes
  // chips são o que o administrador marca ao cadastrar alguém, e procurar
  // "Diário Oficial" numa ordem diferente da que ele acabou de ver no menu é
  // atrito puro. Menu e árvore de permissões contam a mesma história, na mesma
  // sequência — e desde 05/09/2026 saem literalmente da mesma fonte
  // (`lib/menu.ts`).
  { key: "bi", label: "Painel de Indicadores (BI)" },
  // Separadas de proposito: ver o painel, jogar na TV e PUBLICAR para fora sao
  // decisoes diferentes. Um secretario pode precisar da TV da sala dele sem ter
  // permissao de gerar um link que roda o municipio inteiro pelo WhatsApp.
  { key: "bi_tela", label: "Modo Tela (TV) do BI" },
  { key: "bi_link", label: "Gerar link público da TV" },

  // --- FEDERAIS -----------------------------------------------------------
  // ⚠️ AS OITO SAIRAM DE DENTRO DE `transferegov` em 05/09/2026. A chave antiga
  // continua existindo no CATÁLOGO, mas só para a ação «Atualizar dados» (a
  // coleta, cujo botão mora em Configurações › Sessões) — ela não é mais uma
  // tela, e por isso não está nesta lista.
  { key: "transferegov_radar", label: "Radar de captação" },
  { key: "transferegov_geral", label: "Federais — Em execução" },
  { key: "transferegov_especiais", label: "Federais — Especiais" },
  { key: "transferegov_pac", label: "Federais — PAC (Novo PAC)" },
  { key: "transferegov_voluntarias", label: "Federais — Voluntárias" },
  { key: "transferegov_rejeitadas", label: "Federais — Rejeitadas" },
  { key: "transferegov_encerradas", label: "Federais — Encerradas" },
  { key: "transferegov_cnpj", label: "Federais — CNPJ" },
  /* ⭐ EMENDAS FEDERAIS (06/09/2026) — a nona folha do grupo.
     ⚠️ SEM `ufs`, e isso não é esquecimento: a fonte é FEDERAL (dump do
     TransfereGov + API da CGU). A chave da CGU estar ligada só em dois dos cinco
     tenants é OUTRA COISA — `ufs` diz onde a fonte EXISTE, e ela existe em todo
     lugar. Marcar a tela como estadual faria o administrador de um tenant sem
     chave não conseguir liberar uma tela que ele passa a ver no dia em que ela
     for ligada; quem conta a verdade sobre a chave é o payload da rota. */
  { key: "emendas_federais", label: "Federais — Emendas parlamentares" },

  // --- ESTADUAIS ----------------------------------------------------------
  // ⚠️ AS DEZ ERAM UMA CHAVE SÓ (`convenios`) até 05/09/2026, e as UFs de
  // `convenios` eram a UNIÃO do grupo inteiro justamente por isso. Cada uma
  // carrega agora o próprio estado — o de onde a fonte existe de verdade.
  // FONTE_CONVENIOS_ESTADUAIS: MG=SIGCON, ES=GConv/SEGER.
  { key: "convenios", label: "Convênios Estaduais", ufs: ["MG", "ES"] },
  // Só MG tem coletor de emenda estadual (FONTE_EMENDAS_ESTADUAIS). No RS a
  // emenda nem é impositiva — oferecer a caixinha lá prometeria um direito que
  // não existe naquele estado.
  { key: "emendas", label: "Emendas Estaduais", ufs: ["MG"] },
  // REPASSES_POR_UF: Goiás publica a EXECUÇÃO (pagamento) em vez do instrumento.
  { key: "repasses", label: "Repasses Estaduais", ufs: ["GO"] },
  // COFINANCIAMENTO_POR_UF: o repasse do fundo estadual ao municipal de saúde.
  { key: "cofinanciamento", label: "Cofinanciamento da Saúde", ufs: ["GO"] },
  // MONITORAMENTO_POR_UF: onde a norma estadual cria o registro mensal (RS).
  { key: "monitoramento", label: "Monitoramento de Convênios", ufs: ["RS"] },
  // CONSULTA_POPULAR_POR_UF: o orçamento participativo dos COREDEs.
  { key: "consulta_popular", label: "Consulta Popular", ufs: ["RS"] },
  // PROGRAMAS_POR_UF: catálogo curado das linhas de fomento do estado.
  { key: "programas_rs", label: "Programas do Estado", ufs: ["RS"] },
  // As três de CONTEUDO_ESTADUAL_POR_UF (conteúdo curado do RS).
  { key: "funrigs", label: "Plano Rio Grande", ufs: ["RS"] },
  { key: "emendas_rs", label: "Emendas Estaduais RS", ufs: ["RS"] },
  { key: "tce_rs", label: "TCE-RS", ufs: ["RS"] },

  // AGENDAMENTOS — a agenda de trabalho da equipe.
  // ⚠️ SEM `ufs`: é nacional. Pôr um recorte aqui esconderia a caixinha dos
  // clientes dos outros estados, e uma agenda não depende de que estado é.
  { key: "agendamentos", label: "Agendamentos" },
  { key: "parlamentares", label: "Parlamentares" },
  // As quatro da pasta SAÚDE, na ordem em que aparecem no grupo do menu.
  { key: "fns", label: "Fundo Nacional de Saúde" },
  { key: "sismob", label: "Obras da Saúde (SISMOB)" },
  { key: "investsus", label: "InvestSUS" },
  // A dívida da saúde é um acordo da SES-MG: não existe fora de Minas.
  { key: "acordofes", label: "Acordo FES (dívida saúde MG)", ufs: ["MG"] },
  // A pasta OBRAS do menu (04/09/2026).
  { key: "obrasgov", label: "Obras Federais (Obras.gov.br)" },
  { key: "simec", label: "SIMEC - PAR (MEC)" },
  { key: "cauc", label: "Regularidade (federal e estadual)" },
  { key: "rm", label: "Relatório de Monitoramento" },
  { key: "ai", label: "IA PACTHA" },
  // ⚠️ NAO EXISTE MAIS UMA TELA "suas". O painel oficial do MDS (Estrutura
  // SUAS) mora DENTRO de "Painéis Municipais", ao lado do Painel Municipalista.
  // ⭐ Ganhou chave de AÇÃO (`paineis.ver`) em 05/09/2026: era a única tela do
  // menu governada só por `user_telas`, sem nada na língua das permissões.
  { key: "paineis", label: "Painéis Municipais" },
  // Um provedor por estado (DIARIO_POR_UF em `lib/estadual.ts`). Sem provedor
  // a tela já some do menu — oferecer a caixinha seria conceder o que não abre.
  { key: "dou", label: "Diário Oficial", ufs: ["MG", "ES", "GO", "TO", "RS"] },
  { key: "documentos", label: "Geração de Documentos" },
  { key: "gestao", label: "Gestão Interna" },

  // --- CONFIGURAÇÕES (a ordem das abas de lá) -----------------------------
  // ⭐ AS SETE ABAS VIRARAM TELAS DE VERDADE em 05/09/2026. Antes, quatro delas
  // (Usuários, Telemetria, Status dos Dados, Parâmetros) não tinham chave: eram
  // governadas pelo PAPEL `admin`, e por isso não havia como liberar a
  // Auditoria para o controlador interno sem torná-lo administrador do sistema.
  // A regra do dono é que se libera a ABA, não «Configurações» inteiro.
  //
  // ⚠️ SERVICE TOKENS FICOU DE FORA de propósito: é credencial de máquina da
  // Alavank, só super-admin. Oferecê-la na árvore seria prometer o que nenhum
  // usuário de cliente pode receber.
  { key: "usuarios", label: "Usuários e permissões" },
  // A trilha de auditoria tem chave PROPRIA em vez de viver so no papel de
  // admin: quem confere o que foi feito (controle interno, controladoria,
  // juridico) nao e — e nao deve ser — quem administra o sistema. Segregacao de
  // funcao e requisito das ISOs, nao preferencia de menu.
  // ⚠️ O rotulo tem de bater com `backend/services/telas_catalog.py`.
  { key: "auditoria", label: "Auditoria (trilha de atividades)" },
  // ⭐ TELA PRÓPRIA desde 05/09/2026. A aba declarava `tela: "auditoria"` — a
  // chave de outra coisa —, então liberar a trilha liberava junto o horário de
  // trabalho de todo mundo. São perguntas diferentes: a Auditoria guarda ato
  // consequente e serve de prova; a Telemetria guarda navegação.
  { key: "telemetria", label: "Telemetria (uso do sistema)" },
  { key: "cofre", label: "Cofre de Senhas" },
  { key: "sessoes", label: "Sessões (gov.br)" },
  { key: "frescor", label: "Status dos Dados" },
  { key: "parametros", label: "Parâmetros" },
];

export const TELA_LABELS: Record<string, string> = Object.fromEntries(
  TELAS.map((t) => [t.key, t.label])
);

const TELAS_VALIDAS = new Set(TELAS.map((t) => t.key));

/* ⚠️ `TELAS_RENOMEADAS` VIVEU AQUI ENTRE 05 E 06/09/2026 — a rede que traduzia
 *  a chave de tela antiga para as novas enquanto a migration de tradução não
 *  rodava (ela falhou no deploy por uma coluna com o nome errado, e uma
 *  migration quebrada não derruba o boot).
 *
 *  Saiu quando os cinco bancos confirmaram a migration. A nota completa, com as
 *  duas lições que ficam, está em `backend/services/auth.py`. */

/** Deriva a chave de tela a partir de um href da sidebar.
 *
 *  ⚠️ MUDOU MUITO em 05/09/2026. Antes havia dois colapsos aqui — todo
 *  `transferegov*` virava `"transferegov"` e sete rotas do grupo estadual
 *  viravam `"convenios"` — e eram eles que faziam uma permissão abrir várias
 *  telas. Agora cada rota tem a sua chave: a conversão é mecânica (o primeiro
 *  segmento, com `-` virando `_`), e o que não bate com o catálogo é devolvido
 *  como veio, para o guard de rota tratar como tela desconhecida. */
export function hrefToTela(href: string): string {
  // ⭐ AS ABAS DE CONFIGURAÇÕES SÃO AS MESMAS TELAS, e por isso o prefixo cai
  // ANTES de qualquer outra conta: `/dashboard/configuracoes/cofre` tem de dar
  // "cofre", exatamente como `/dashboard/cofre` dava. Sem este colapso, a chave
  // viraria "configuracoes" — que não existe em catálogo nenhum — e o guard de
  // rota expulsaria da aba justamente quem tem a permissão certa.
  const semPrefixo = href.replace(/^\/dashboard\/configuracoes(?=\/|$)/, "/dashboard");
  // "/dashboard" -> "dashboard"
  const seg = semPrefixo.replace(/^\/dashboard\/?/, "").split("/")[0] || "dashboard";
  const chave = seg.replace(/-/g, "_");
  // «Especiais» mora em `/dashboard/transferegov` (a rota mais antiga do grupo,
  // preservada para não quebrar bookmark). A chave dela é explícita.
  if (chave === "transferegov") return "transferegov_especiais";
  return TELAS_VALIDAS.has(chave) ? chave : seg;
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

/** A pessoa logada enxerga esta tela?
 *
 *  Existe para COMPONENTE que nao esta na arvore de rotas e por isso nao passa
 *  pelo guard do layout — hoje o botao de anotacao, que aparece dentro das
 *  listas de Convenios e do TransfereGov.
 *
 *  ⚠️ NA DUVIDA, LIBERA. Sem info (SSR, localStorage vazio, JSON quebrado) o
 *  retorno e `true`: esconder por engano tiraria funcionalidade de quem tem
 *  direito, enquanto liberar por engano so leva ao 403 que o backend ja aplica
 *  — a decisao de verdade continua sendo do servidor, e este helper e apenas
 *  cortesia de UI. */
export function podeVerTela(chave: string): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem("pactha_user");
    if (!raw) return true;
    const permitidas = allowedTelasOf(JSON.parse(raw));
    return permitidas === null || permitidas.has(chave);
  } catch {
    return true;
  }
}
