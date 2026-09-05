// OS ATRIBUTOS DA CONTA QUE DECIDEM PODER — e que NAO sao o papel.
//
// O papel (`users.role`: admin / usuario — mais `prefeito`, `analyst` e
// `viewer`, legados) virou ROTULO: ele organiza a equipe do cliente e nao
// concede nada. Quem concede sao as telas, os municipios e as caixinhas de acao
// marcados em CADA usuario. A unica excecao a isso e uma coluna propria:
//
//   · `users.super_admin` — a Alavank, dona da plataforma. Ignora as listas.
//
// ⚠️ ERAM DUAS ate 05/09/2026. `users.somente_leitura` — a conta que le tudo o
// que lhe cabe e nao escreve nada — foi REMOVIDA por decisao do dono, que
// preferiu o controle mais fino: "prefiro dar permissao de visualizaçao
// separada pra cada menu ou modulo dai eu permito so visualizar sem editar
// nada". Quem nao escreve agora e quem esta sem a caixinha de escrita daquela
// tela. Ver o topo de `backend/services/auth.py`.
//
// Este modulo existe para a tela nao ler `role` para responder essa pergunta —
// que e exatamente o habito que este incremento veio desfazer.
//
// ⚠️ A RESERVA ABAIXO NAO E AUTORIDADE, e e o ESPELHO da do backend
// (`services/auth.py::is_super_admin`): a mesma soma por OU, que so amplia e
// nunca corta. Quem manda e o campo devolvido pela API; a derivacao so entra
// quando o campo NAO VEIO.
//
// ONDE ELE NAO VEM, hoje: `GET /users` manda os dois campos, ja calculados.
// `GET /auth/me` NAO — `schemas/auth.py::UserResponse` nao os declara. Efeito
// pratico: promover alguem a dono por UPDATE no banco (a capacidade que este
// incremento abriu) passa a valer no backend na hora, mas a SIDEBAR so vai
// mostrar Sessoes/Service Tokens a quem tambem estiver na lista abaixo. Os
// quatro donos padrao estao, entao nada regride — mas o dia em que a lista e a
// coluna divergirem, quem resolve e acrescentar os dois campos aquele schema.

/** Contas DONAS do sistema (Alavank). Semente da coluna `users.super_admin`.
 *
 *  ⚠️ Tem de bater com `backend/services/auth.py::SUPER_ADMIN_EMAILS` e com
 *  `backend/setup_db.py` — sao as sementes da mesma coluna. Divergir aqui so
 *  afeta o que a tela DESENHA (esconder item de menu, marcar o selo); quem
 *  barra de verdade e o backend. */
export const SUPER_ADMIN_EMAILS = new Set<string>([
  "super-admin@alavank.com.br",
  "alavank.tecnologia@gmail.com",
  "matheus@alavank.com.br",
  "tiagomiller@alavank.com.br",
]);

export interface ContaLike {
  email?: string | null;
  role?: string | null;
  super_admin?: boolean | null;
}

/** Dona da plataforma? Campo OU allowlist — soma, nunca corte.
 *
 *  ⚠️ Era `if (typeof super_admin === "boolean") return super_admin`, e isso NAO
 *  era um OU: um `false` vindo do campo DESLIGAVA a allowlist. Enquanto a API
 *  manda o valor ja somado, dava no mesmo; no dia em que qualquer rota
 *  serializasse a COLUNA crua, um dos quatro donos apareceria como conta comum
 *  na tela — a unica falha que o comentario do topo promete que nao existe. */
export function ehSuperAdmin(u: ContaLike | null | undefined): boolean {
  if (u?.super_admin === true) return true;
  return SUPER_ADMIN_EMAILS.has((u?.email || "").trim().toLowerCase());
}

// ⚠️ `ehSomenteLeitura` e `PAPEIS_SEMPRE_SOMENTE_LEITURA` SAIRAM em 05/09/2026
// com a trava de conta que elas espelhavam (ver o topo deste arquivo). A tela
// nao tem mais o que perguntar: "esta pessoa escreve aqui?" e a caixinha de
// escrita daquela tela, e quem responde e o catalogo de permissoes.
//
// O quiosque continua barrado — mas no BACKEND, que e onde a trava dele sempre
// esteve de verdade (`ehQuiosque` + `KIOSK_GET_PERMITIDOS`). Espelhar aquilo
// aqui nunca protegeu nada: o link publico nao passa por esta tela.
