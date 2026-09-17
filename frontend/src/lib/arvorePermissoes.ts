// ⭐⭐ A ÁRVORE DE PERMISSÕES — Módulo › Tela › Ação, montada A PARTIR DO MENU.
//
// A regra do dono, palavra por palavra:
//
//     "Granularidade em três níveis: Módulo/menu › Tela ou aba › Ação. Liberar
//      «Configurações» inteiro não existe: libera-se a aba (Usuários, Auditoria
//      etc.) e, dentro dela, as ações. (...) O modal de usuário mostra a árvore
//      do jeito que está no menu lateral do ambiente."
//
// Este arquivo é a JUNÇÃO de duas fontes, e nenhuma das duas mora aqui:
//
//   `lib/menu.ts`                 a ESTRUTURA — grupos, ordem, rótulos, rotas.
//                                 É o mesmo objeto que desenha a barra lateral.
//   `GET /api/permissoes/catalogo` as AÇÕES de cada tela, com rótulo, descrição
//                                 e UF. Fonte única no backend; ver o cabeçalho
//                                 de `lib/permissoes.ts`.
//
// A dobradiça é `hrefToTela(href)` de um lado e `Permissao.tela` do outro. Se
// as duas listas divergirem, `backend/tests/test_arvore_segue_o_menu.py` quebra
// — de propósito: uma tela no menu sem entrada no catálogo é um módulo que
// ninguém consegue liberar, e uma no catálogo sem entrada no menu é uma
// caixinha que concede o que não existe.

import { hrefToTela, TELA_LABELS } from "@/lib/telas";
import { MENU_COMPLETO, type NavEntry, type NavLeaf } from "@/lib/menu";
import type { Catalogo, Permissao } from "@/lib/permissoes";

/** ⚠️ A HOME É A ÚNICA FOLHA CUJA CHAVE NÃO SAI DA ROTA.
 *
 *  `hrefToTela("/dashboard")` devolve `"dashboard"` — e tem de continuar
 *  devolvendo, porque o guard de rota usa aquela função e concessões antigas
 *  gravadas com a chave `dashboard` seguem valendo (`allowedTelasOf` faz `bi`
 *  valer `dashboard` também, desde a fusão de 29/07/2026).
 *
 *  Mas a CHAVE que a árvore tem de gravar é `bi`: é ela que existe no catálogo
 *  de permissões, é ela que carrega as ações do Painel, e é a que o backfill e
 *  o backend conhecem. Sem esta exceção o interruptor do Painel gravaria
 *  `user_telas = "dashboard"` e a linha ficaria sem ação nenhuma embaixo —
 *  silenciosamente, porque `dashboard` não está no catálogo. */
function telaDaFolha(href: string): string {
  const chave = hrefToTela(href);
  return chave === "dashboard" ? "bi" : chave;
}

/** Uma folha da árvore: a TELA, com as ações que ela oferece.
 *
 *  ⚠️ `acoes` PODE SER VAZIA, e isso não é defeito. Duas telas do produto são
 *  assim hoje: «Painéis Municipais» (um mural de painéis oficiais em iframe, sem
 *  endpoint próprio) e «Modo Tela (TV)» (governada pela tela, porque `bi.tela` é
 *  inerte). Nelas o interruptor de acesso É a permissão inteira. */
export interface TelaNaArvore {
  /** Chave de `user_telas` — o que o toggle grava. */
  tela: string;
  /** O rótulo DO MENU, e não o do catálogo: a árvore promete mostrar o menu, e
   *  «Em execução» tem de ler «Em execução» aqui como lê lá. */
  rotulo: string;
  href: string;
  /** As caixinhas daquela tela, na ordem do catálogo. Já sem as inertes. */
  acoes: Permissao[];
  /** Os recursos que essas ações cobrem — o alcance por linha é por RECURSO, e
   *  uma tela pode ter mais de um (o Painel tem `bi` e `vigencias`). */
  recursos: string[];
}

export interface GrupoNaArvore {
  /** Rótulo do grupo do menu ("FEDERAIS", "Saúde", "Configurações"), ou vazio
   *  para os itens soltos de primeiro nível. */
  rotulo: string;
  icone?: React.ComponentType<{ className?: string }>;
  telas: TelaNaArvore[];
}

/** ⭐ Monta a árvore do ambiente.
 *
 *  @param catalogo  já RECORTADO pela carteira (`filtrarCatalogoPorUfs`) — o
 *                   recorte por UF acontece uma vez só, na página, para o
 *                   contador do cabeçalho e a árvore contarem a mesma coisa.
 *  @param telasDoAmbiente  as telas que ESTE cliente oferece. Vem do mesmo
 *                   filtro por UF que esconde do cliente gaúcho o módulo de
 *                   Minas. `null` = ainda carregando, e aí mostra tudo (a mesma
 *                   escolha de `agruparPorEstado`: na dúvida, não esconde).
 *
 *  ⚠️ DEDUPLICA POR TELA, mantendo a PRIMEIRA ocorrência. O SISMOB aparece no
 *  menu em «Saúde» E em «Obras» — o mesmo link, de propósito, porque quem chega
 *  por um não é quem chega pelo outro. Na árvore isso daria DUAS caixinhas para
 *  a mesma concessão, e marcar uma deixaria a outra desmarcada na cara do
 *  administrador. */
export function arvoreDoMenu(
  catalogo: Catalogo | null,
  telasDoAmbiente: Set<string> | null,
): GrupoNaArvore[] {
  if (!catalogo) return [];

  const inertes = new Set(catalogo.inertes ?? []);
  // tela -> ações, na ordem em que o catálogo as devolve.
  const porTela = new Map<string, Permissao[]>();
  for (const p of catalogo.permissoes) {
    if (!p.tela || inertes.has(p.chave)) continue;
    const lista = porTela.get(p.tela);
    if (lista) lista.push(p);
    else porTela.set(p.tela, [p]);
  }

  const vistas = new Set<string>();
  const grupos: GrupoNaArvore[] = [];

  const linhaDe = (tela: string, rotulo: string, href: string): TelaNaArvore | null => {
    if (vistas.has(tela)) return null;
    if (telasDoAmbiente && !telasDoAmbiente.has(tela)) return null;
    vistas.add(tela);
    const acoes = porTela.get(tela) ?? [];
    return {
      tela, rotulo, href, acoes,
      recursos: [...new Set(acoes.map((a) => a.recurso))],
    };
  };

  /** A folha, mais as telas que ela declara em `telasExtras`.
   *
   *  ⚠️ AS EXTRAS VÊM LOGO DEPOIS DELA, e não num grupo próprio: são
   *  capacidades daquela tela («Modo Tela» e «Gerar link» são botões DENTRO do
   *  Painel), e separá-las faria o administrador procurá-las como se fossem
   *  outro módulo. O rótulo sai de `TELA_LABELS` porque elas não têm folha de
   *  menu de onde tirar um. */
  const montarFolha = (folha: NavLeaf): TelaNaArvore[] => {
    const saida: TelaNaArvore[] = [];
    // ⭐ Tela com abas (17/09/2026): cada aba é uma linha, com o rótulo da aba.
    // A folha não tem chave própria — ver `abas` em `lib/menu.ts`.
    if (folha.abas) {
      for (const a of folha.abas) {
        const linha = linhaDe(a.tela, a.rotulo, folha.href);
        if (linha) saida.push(linha);
      }
      return saida;
    }
    const principal = linhaDe(telaDaFolha(folha.href), folha.label, folha.href);
    if (principal) saida.push(principal);
    for (const extra of folha.telasExtras ?? []) {
      const linha = linhaDe(extra, TELA_LABELS[extra] ?? extra, folha.href);
      if (linha) saida.push(linha);
    }
    return saida;
  };

  // ⚠️ OS ITENS SOLTOS VÃO TODOS PARA **UM** GRUPO, e a primeira versão disto
  // errava feio: ela fechava o grupo a cada vez que um grupo de verdade
  // interrompia a sequência, e a árvore saía com TRÊS cabeçalhos «Módulos
  // gerais» (medido em produção, no freitas: `1 de 4`, `1 de 2`, `8 de 8`).
  //
  // Não era só feio — era quebrado: o estado de aberto/fechado é chaveado pelo
  // RÓTULO do grupo, então clicar num abria os três, e «Liberar grupo» de um
  // deles não correspondia ao que o contador do vizinho mostrava.
  //
  // Um grupo por item avulso também não serve — seriam quinze cabeçalhos de uma
  // linha cada. Então: uma lista só, na ordem do menu, entregue no fim.
  const soltos: TelaNaArvore[] = [];

  for (const item of MENU_COMPLETO as NavEntry[]) {
    if ("children" in item) {
      const telas: TelaNaArvore[] = [];
      for (const filho of item.children) {
        if ("sectionLabel" in filho) {
          for (const neta of filho.children) telas.push(...montarFolha(neta));
        } else {
          telas.push(...montarFolha(filho));
        }
      }
      // Grupo que ficou sem tela nenhuma sai: um cabeçalho vazio só ocuparia
      // espaço e faria o administrador procurar dentro dele. É o que acontece
      // com ESTADUAIS num tenant federal.
      if (telas.length) grupos.push({ rotulo: item.label, icone: item.icon, telas });
    } else if (item.abas) {
      // ⭐ A tela com abas vira GRUPO na árvore, no lugar dela no menu: «Emendas
      // parlamentares» com Federais, Estaduais e Parlamentares embaixo — o que o
      // dono aprovou ver na tela de Usuários (17/09/2026).
      const telas = montarFolha(item);
      if (telas.length) grupos.push({ rotulo: item.label, icone: item.icon, telas });
    } else {
      soltos.push(...montarFolha(item));
    }
  }
  // Os avulsos entram no FIM, num cabeçalho só. Ficam depois dos grupos porque
  // é lá que o olho os procura: um item sem assunto não abre a lista.
  if (soltos.length) grupos.push({ rotulo: "Módulos gerais", telas: soltos });
  return grupos;
}

/** Todas as telas da árvore, achatadas — o denominador do «X telas liberadas». */
export function telasDaArvore(arvore: GrupoNaArvore[]): string[] {
  return arvore.flatMap((g) => g.telas.map((t) => t.tela));
}

/** Todas as ações da árvore, achatadas — o denominador do «Y ações». */
export function acoesDaArvore(arvore: GrupoNaArvore[]): string[] {
  return arvore.flatMap((g) => g.telas.flatMap((t) => t.acoes.map((a) => a.chave)));
}

/** ⭐ A COR DE CADA GRUPO — a faixa que o dono pediu para dar para varrer.
 *
 *  Pedido: "usar cor leve por módulo/grupo na árvore (faixa ou borda na cor do
 *  grupo, cabeçalho tingido) para ajudar a varrer e localizar, sem pesar".
 *
 *  ⚠️ SÃO OS TOKENS DO PACTHA, e não uma paleta nova. O sistema já tem cinco
 *  famílias semânticas (`--bi-ok`, `--bi-atencao`, `--bi-crit`, `--bi-info`,
 *  `--bi-accent`), e elas SIGNIFICAM coisas — verde é "em dia", vermelho é
 *  "problema". Usá-las como cor de grupo aqui é seguro porque nesta árvore não
 *  há estado bom nem ruim: nenhum grupo é "melhor" que outro, então a cor volta
 *  a ser só um marcador de posição, que é para o que o dono a pediu.
 *
 *  A cor entra como BORDA de 2px e um fundo a 6% — o suficiente para o olho
 *  pular de grupo em grupo sem transformar a lista num painel colorido, que é a
 *  ressalva que ele mesmo fez ("sem pesar"). */
export function corDoGrupo(rotulo: string): string {
  switch (rotulo) {
    case "FEDERAIS": return "var(--bi-info)";
    case "ESTADUAIS": return "var(--bi-accent)";
    case "Saúde": return "var(--bi-ok)";
    case "Obras": return "var(--bi-atencao)";
    case "Configurações": return "var(--bi-crit)";
    // Os itens soltos ficam no cinza da identidade: eles não são um assunto,
    // são o que sobra entre os assuntos.
    default: return "var(--bi-line)";
  }
}
