// AS PERMISSOES POR ACAO, COMO A TELA AS ENXERGA.
//
// ⚠️ A REGRA DESTE ARQUIVO, E ELA E A UNICA QUE IMPORTA: **aqui nao ha lista de
// permissao nenhuma.** So tipos e chamadas. O catalogo (as 66 caixinhas, os
// rotulos, as descricoes, as secoes) vem SEMPRE de
// `GET /api/permissoes/catalogo`, e o backend e a fonte unica
// (`services/permissoes.py`).
//
// Este repo ja tem a cicatriz do contrario: `services/telas_catalog.py` e
// `lib/telas.ts` sao a MESMA lista escrita duas vezes, divergiram em seis
// chaves, e o comentario de la avisa que tela nova precisa entrar em tres
// lugares. Com telas, divergir some com um item de menu — alguem reclama.
// Divergir num catalogo de PERMISSAO nao aparece na tela: some com o acesso de
// alguem, em silencio, e o administrador jura que marcou a caixinha.
//
// ⚠️ `chave` (`rm.excluir`) e CONTRATO: vai para o banco, para a API e para o
// `exige()` do router. `rotulo`, `verbo_rotulo` e `descricao` sao texto de tela
// e podem mudar de redacao sem mudar quem pode o que. Nunca comparar por rotulo.
import api from "@/lib/api";

/** Uma caixinha. Espelha `services/permissoes.py::Permissao.as_dict`. */
export interface Permissao {
  chave: string;
  secao: string;
  secao_rotulo: string;
  recurso: string;
  recurso_rotulo: string;
  verbo: string;
  verbo_rotulo: string;
  /** Rotulo COMPLETO ("Relatório de Monitoramento — Excluir"), para quando a
   *  caixinha aparece fora do agrupamento. */
  rotulo: string;
  descricao: string;
  /** O guard de somente-leitura barra esta acao. NAO e "o verbo parece de
   *  escrita" — `ai.exportar` e escrita (o endpoint e POST) e `bi.link` nao e. */
  escrita: boolean;
}

export interface RecursoCatalogo {
  recurso: string;
  recurso_rotulo: string;
  permissoes: Permissao[];
}

export interface SecaoCatalogo {
  chave: string;
  rotulo: string;
  descricao: string;
  recursos: RecursoCatalogo[];
}

export interface Catalogo {
  secoes: SecaoCatalogo[];
  permissoes: Permissao[];
  total: number;
}

/** O que o PROPRIO usuario pode — ja resolvido pela funcao pura do backend.
 *
 *  Nao e a lista de caixinhas marcadas dele: super-admin recebe tudo sem ter
 *  caixinha nenhuma, e conta em somente-leitura perde os verbos de escrita. E o
 *  conjunto EFETIVO, que e o que decide o anti-escalonamento da tela. */
export interface MinhasPermissoes {
  chaves: string[];
  resumo: string[];
  super_admin: boolean;
  somente_leitura: boolean;
  /** `aviso` = a trava so registra "eu teria negado"; `bloqueio` = nega mesmo.
   *  A tela diz isso em portugues para ninguem concluir que a permissao nao
   *  funcionou ao ver um botao que ainda responde. */
  modo: string;
}

export async function buscarCatalogo(): Promise<Catalogo> {
  const r = await api.get<Catalogo>("/permissoes/catalogo");
  return r.data;
}

export async function buscarMinhas(): Promise<MinhasPermissoes> {
  const r = await api.get<MinhasPermissoes>("/permissoes/minhas");
  return r.data;
}

/** As caixinhas MARCADAS de cada usuario, para a lista inteira de uma vez.
 *
 *  Chave do mapa e o id do usuario em texto (JSON nao tem chave numerica). */
export async function buscarConcedidas(): Promise<Record<string, string[]>> {
  const r = await api.get<{ concedidas: Record<string, string[]> }>(
    "/permissoes/usuarios",
  );
  return r.data?.concedidas ?? {};
}

/** Grava o conjunto COMPLETO. O servidor calcula o que entrou e o que saiu,
 *  barra o que quem edita nao possui e registra a mudanca na trilha. */
export async function salvarPermissoes(
  userId: number,
  chaves: string[],
): Promise<string[]> {
  const r = await api.put<{ permissoes: string[] }>(
    `/permissoes/usuario/${userId}`,
    { permissoes: chaves },
  );
  return r.data?.permissoes ?? chaves;
}

/** "Relatório de Monitoramento: Ver, Editar, Exportar" — uma linha por recurso.
 *
 *  Espelha `services/permissoes.py::resumo`, e a duplicacao e deliberada: o
 *  backend responde sobre um conjunto JA GRAVADO, e a tela precisa da mesma
 *  frase enquanto o administrador clica, antes de salvar. O que NAO se duplica
 *  e a lista — a ordem, os rotulos e o agrupamento saem do `catalogo` recebido
 *  da API, entao acrescentar uma permissao no Python muda esta frase sozinho.
 *
 *  `secao` filtra o resumo de uma secao so (o cabecalho de cada grupo). */
export function resumoPorRecurso(
  catalogo: Catalogo | null,
  marcadas: Set<string>,
  secao?: string,
): string[] {
  if (!catalogo) return [];
  const linhas: string[] = [];
  for (const s of catalogo.secoes) {
    if (secao && s.chave !== secao) continue;
    for (const r of s.recursos) {
      const verbos = r.permissoes
        .filter((p) => marcadas.has(p.chave))
        .map((p) => p.verbo_rotulo);
      if (verbos.length) linhas.push(`${r.recurso_rotulo}: ${verbos.join(", ")}`);
    }
  }
  return linhas;
}

/** Todas as chaves de uma secao — para o "marcar seção inteira".
 *
 *  Existe aqui, e nao na tela, porque a tela nao pode reconstruir a lista de
 *  chaves de cabeca: ela so conhece o que a API mandou. */
export function chavesDaSecao(secao: SecaoCatalogo): string[] {
  return secao.recursos.flatMap((r) => r.permissoes.map((p) => p.chave));
}
