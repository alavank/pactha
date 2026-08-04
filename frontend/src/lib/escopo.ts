// O ALCANCE DE ESCRITA POR LINHA — "editar e excluir so o que a pessoa criou".
//
// Sao DUAS metades, e elas nao se encontram aqui dentro:
//
//   · A CONFIGURACAO — por usuario e por MODULO (`todos` | `proprios`). Quem
//     escreve e o modal de permissoes; o vocabulario inteiro (rotulos, textos e
//     quais modulos aceitam alcance) vem do catalogo da API, nunca daqui —
//     ver o cabecalho de `lib/permissoes.ts`.
//   · O VEREDITO — linha a linha, e ele vem PRONTO da API, nos campos
//     `pode_editar` e `pode_excluir` de cada item.
//
// ⚠️ A TELA NAO RECALCULA O VEREDITO. Seria facil: comparar `criado_por` com o
// proprio id e pronto. Seria tambem uma segunda regra de permissao escrita em
// JavaScript, que divergiria da do servidor no primeiro caso de borda — e os
// casos de borda ja existem e sao conhecidos: a linha antiga com `criado_por`
// nulo, e o fato de o veredito somar a permissao do verbo ao alcance de formas
// diferentes conforme `AUTHZ_MODO` (ver `authz.pode_editar_item`). Quem responde
// "esta linha e sua?" e quem barra: o servidor.
//
// ⚠️ ESCONDER BOTAO NAO E PERMISSAO. Tudo o que sai daqui e DESENHO. Chamar a
// rota na mao continua levando 403 do backend. O que isto compra e nao oferecer
// um clique que ja se sabe que vai falhar.

/** O que se escolhe no modal, por usuario e por modulo.
 *
 *  `todos` e o padrao, e o padrao NAO restringe ninguem: e o comportamento que o
 *  sistema tem hoje e o que toda conta existente recebe na migracao. Espelha
 *  `services/permissoes.py::ESCOPOS` — e o catalogo devolve o proprio default em
 *  `catalogo.escopos.default`. */
export type Escopo = "todos" | "proprios";

export const ESCOPO_PADRAO: Escopo = "todos";

/** Recurso (`rm`, `documentos`, `gestao`) -> escopo daquele usuario ali. */
export type MapaEscopos = Record<string, Escopo>;

/** Le um valor vindo da API sem confiar nele.
 *
 *  Qualquer coisa que nao seja exatamente `proprios` vira `todos` — o mesmo
 *  fail-open de `services/permissoes.py::normalizar_escopo`, e pela mesma razao:
 *  um valor torto ou um campo ausente nao podem TIRAR de ninguem a edicao que a
 *  pessoa tem hoje. Restringir e ato deliberado do administrador, nunca efeito
 *  colateral de dado sujo. */
export function normalizarEscopo(v: unknown): Escopo {
  return v === "proprios" ? "proprios" : "todos";
}

export function lerMapaEscopos(bruto: unknown): MapaEscopos {
  const saida: MapaEscopos = {};
  if (!bruto || typeof bruto !== "object") return saida;
  for (const [recurso, valor] of Object.entries(bruto as Record<string, unknown>)) {
    saida[recurso] = normalizarEscopo(valor);
  }
  return saida;
}

/** Um item de lista devolvido pela API, ja julgado pelo servidor.
 *
 *  Os dois campos sao SEPARADOS porque as duas acoes sao separadas: quem tem
 *  `rm.editar` e nao tem `rm.excluir` recebe `pode_editar: true` e
 *  `pode_excluir: false` na MESMA linha. Um booleano so escondia o botao certo
 *  pelo motivo errado. */
export interface LinhaComDono {
  /** `false` = o servidor NAO deixa esta pessoa alterar esta linha. */
  pode_editar?: boolean | null;
  /** `false` = o servidor NAO deixa esta pessoa apagar esta linha. */
  pode_excluir?: boolean | null;
}

/* ⚠️ Os dois so escondem diante de um `false` EXPLICITO. Ausente (`undefined`)
   significa "a API nao respondeu isso", e nao "nao pode": um campo que ainda nao
   foi implantado nao pode tirar o botao de editar de todo mundo. Falhar aberto
   aqui e seguro justamente porque o desenho nao e a trava — o servidor e. */

export function podeEditarLinha(item: LinhaComDono | null | undefined): boolean {
  return item?.pode_editar !== false;
}

export function podeExcluirLinha(item: LinhaComDono | null | undefined): boolean {
  return item?.pode_excluir !== false;
}

/** A linha em que NENHUMA acao de escrita sobrou — a que fica sem botao nenhum.
 *
 *  E este o numero que a frase de aviso usa, e nao "linhas com algum botao a
 *  menos": numa conta que tem editar e nao tem excluir, TODA linha perde a
 *  lixeira, inclusive as dela — contar isso como bloqueio anunciaria a lista
 *  inteira como alheia. */
export function linhaSemEscrita(item: LinhaComDono | null | undefined): boolean {
  return !podeEditarLinha(item) && !podeExcluirLinha(item);
}

export function contarSemEscrita(itens: readonly LinhaComDono[]): number {
  return itens.reduce((n, item) => (linhaSemEscrita(item) ? n + 1 : n), 0);
}
