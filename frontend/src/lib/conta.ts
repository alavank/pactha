// OS ATRIBUTOS DA CONTA QUE DECIDEM PODER — e que NAO sao o papel.
//
// O papel (`users.role`: admin / usuario / prefeito — mais `analyst` e `viewer`,
// legados) virou ROTULO: ele organiza a equipe do cliente e nao concede nada.
// Quem concede sao as telas e os municipios marcados em CADA usuario, e as duas
// excecoes a isso viraram coluna propria no banco:
//
//   · `users.super_admin`     — a Alavank, dona da plataforma. Ignora as listas.
//   · `users.somente_leitura` — a conta que le tudo o que lhe cabe e nao escreve
//                               nada (o prefeito no Painel, o quiosque da TV).
//
// Este modulo existe para a tela nao ler `role` para responder essas duas
// perguntas — que e exatamente o habito que este incremento veio desfazer.
//
// ⚠️ AS RESERVAS ABAIXO NAO SAO AUTORIDADE, e sao o ESPELHO das do backend
// (`services/auth.py::is_super_admin` e `::eh_somente_leitura`): a mesma soma
// por OU, que so amplia e nunca corta. Quem manda e o campo devolvido pela API;
// a derivacao so entra quando o campo NAO VEIO.
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

/** O papel que barra escrita por SI SO, mesmo sem a flag.
 *
 *  Espelha `backend/services/auth.py::PAPEIS_SEMPRE_SOMENTE_LEITURA`, e a lista
 *  tem UM item de proposito. `prefeito` estava junto com `viewer` no antigo
 *  `READONLY_ROLES` e SAIU: e justamente o caso que este incremento existe para
 *  destravar — um prefeito pode receber escrita individualmente sem deixar de
 *  aparecer como prefeito, e sem que isso valha para os outros prefeitos.
 *  Deduzir "prefeito logo somente-leitura" aqui reporia a regra velha na tela.
 *
 *  `viewer` fica porque nao e rotulo de pessoa: e a credencial sintetica do
 *  link publico de TV, criada por INSERT direto que nao conhece a flag nova. */
export const PAPEIS_SEMPRE_SOMENTE_LEITURA = new Set<string>(["viewer"]);

export interface ContaLike {
  email?: string | null;
  role?: string | null;
  super_admin?: boolean | null;
  somente_leitura?: boolean | null;
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

/** Conta que nao escreve nada fora do Painel? Flag OU papel-que-barra-sozinho.
 *
 *  Mesma soma por OU, pela mesma razao — e aqui ela protege o quiosque, que
 *  nasce com a coluna em `false` (INSERT direto em `routers/bi.py`). */
export function ehSomenteLeitura(u: ContaLike | null | undefined): boolean {
  if (u?.somente_leitura === true) return true;
  return PAPEIS_SEMPRE_SOMENTE_LEITURA.has((u?.role || "").trim().toLowerCase());
}
