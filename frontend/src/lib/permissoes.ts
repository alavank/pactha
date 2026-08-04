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
import {
  ESCOPO_PADRAO, lerMapaEscopos, type Escopo, type MapaEscopos,
} from "@/lib/escopo";

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
  /** Este modulo guarda o AUTOR de cada linha (`criado_por`) e o servidor sabe
   *  comparar? So onde isso e verdade a escolha de alcance significa alguma
   *  coisa. Espelha `escopavel()` do backend. */
  escopavel?: boolean;
  /** As CHAVES de escrita que o alcance modifica neste recurso
   *  (`["rm.editar", "rm.excluir"]`). Vem pronta para a tela nao deduzir de
   *  verbo nenhum — e a regra do dono: a escolha so aparece se alguma delas
   *  estiver marcada. */
  escopo_permissoes?: string[];
}

/** O VOCABULARIO do alcance, inteiro vindo da API (`catalogo.escopos`).
 *
 *  ⚠️ Os rotulos e as descricoes das duas opcoes moram no backend
 *  (`services/permissoes.py::ESCOPO_OPCOES`) pela MESMA razao que o resto do
 *  catalogo: escrever "Somente os que ele criou" a mao aqui criaria a segunda
 *  copia de um texto de permissao, e a divergencia nao apareceria como defeito
 *  — apareceria como duas telas explicando a mesma regra de dois jeitos. */
export interface EscopoOpcao {
  valor: Escopo;
  rotulo: string;
  descricao: string;
}

export interface CatalogoEscopos {
  default: Escopo;
  opcoes: EscopoOpcao[];
  /** Os verbos que o alcance modifica (`["editar", "excluir"]`). */
  verbos: string[];
  recursos: Record<string, { recurso: string; recurso_rotulo: string; permissoes: string[] }>;
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
  /** Opcional: contra uma API anterior ao alcance o campo nao vem, e a tela
   *  simplesmente nao desenha a escolha. Nao ha lista de reserva escrita aqui —
   *  oferecer "somente os que ele criou" num servidor que nao confere autor
   *  nenhum seria uma trava de mentira, que e pior do que trava nenhuma. */
  escopos?: CatalogoEscopos;
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
  /** O ALCANCE do PROPRIO usuario, um valor por modulo escopavel.
   *
   *  E o que trava os radios do modal: quem so alcanca o proprio trabalho num
   *  modulo nao define o alcance de ninguem ali. A mesma regra que
   *  `routers/permissoes.py::_barrar_escalonamento_escopo` impoe com 403. */
  escopos?: MapaEscopos;
}

/** Os modulos em que o alcance por autor vale — SO o que a API declarou.
 *
 *  Vazio quando o catalogo nao traz `escopos`: sem a declaracao do servidor nao
 *  ha como saber onde a regra e aplicada, e desenhar a escolha "no chute" seria
 *  configurar uma restricao que nunca acontece. */
export function recursosComEscopo(catalogo: Catalogo | null): Set<string> {
  return new Set(Object.keys(catalogo?.escopos?.recursos ?? {}));
}

/** As caixinhas daquele recurso que o alcance governa (Editar, Excluir).
 *
 *  Sai da lista pronta do catalogo (`escopo_permissoes`); a leitura por verbo e
 *  so a reserva para o grupo que nao a trouxer, e ainda assim usando os verbos
 *  que a API declarou — nenhuma das duas inventa lista. */
export function permissoesDeEscopo(
  catalogo: Catalogo | null,
  recurso: RecursoCatalogo,
): Permissao[] {
  const chaves = recurso.escopo_permissoes
    ?? catalogo?.escopos?.recursos?.[recurso.recurso]?.permissoes;
  if (chaves) return recurso.permissoes.filter((p) => chaves.includes(p.chave));
  const verbos = catalogo?.escopos?.verbos ?? [];
  return recurso.permissoes.filter((p) => verbos.includes(p.verbo));
}

export async function buscarCatalogo(): Promise<Catalogo> {
  const r = await api.get<Catalogo>("/permissoes/catalogo");
  return r.data;
}

export async function buscarMinhas(): Promise<MinhasPermissoes> {
  const r = await api.get<MinhasPermissoes>("/permissoes/minhas");
  return { ...r.data, escopos: lerMapaEscopos(r.data?.escopos) };
}

/** O que cada usuario tem HOJE: as caixinhas marcadas e o alcance por modulo.
 *
 *  Chave dos dois mapas e o id do usuario em texto (JSON nao tem chave
 *  numerica). Usuario sem entrada em `escopos` nao e usuario sem alcance — e
 *  usuario no padrao (`todos`), que e o caso da esmagadora maioria. */
export interface ConcedidasResposta {
  concedidas: Record<string, string[]>;
  escopos: Record<string, MapaEscopos>;
}

export async function buscarConcedidas(): Promise<ConcedidasResposta> {
  const r = await api.get<{
    concedidas?: Record<string, string[]>;
    escopos?: Record<string, unknown>;
  }>("/permissoes/usuarios");
  const escopos: Record<string, MapaEscopos> = {};
  for (const [id, mapa] of Object.entries(r.data?.escopos ?? {})) {
    escopos[id] = lerMapaEscopos(mapa);
  }
  return { concedidas: r.data?.concedidas ?? {}, escopos };
}

/** Grava o conjunto COMPLETO. O servidor calcula o que entrou e o que saiu,
 *  barra o que quem edita nao possui e registra a mudanca na trilha.
 *
 *  `escopos` vai junto e no mesmo PUT de proposito: alcance e permissao sao a
 *  mesma decisao ("o que essa pessoa faz aqui"), e separa-los em duas chamadas
 *  criaria o estado meio-salvo — a caixinha de Editar gravada e o alcance nao —
 *  que ninguem consegue ler na trilha depois. */
export async function salvarPermissoes(
  userId: number,
  chaves: string[],
  escopos: MapaEscopos,
): Promise<string[]> {
  const r = await api.put<{ permissoes: string[] }>(
    `/permissoes/usuario/${userId}`,
    { permissoes: chaves, escopos },
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
 *  `secao` filtra o resumo de uma secao so (o cabecalho de cada grupo).
 *
 *  `escopos` acrescenta o alcance a linha — e o resumo e o unico lugar onde o
 *  administrador ve essa restricao SEM abrir a secao. Sem isso, "Gestao Interna:
 *  Ver, Criar, Editar" leria igual para quem edita a prefeitura inteira e para
 *  quem edita so o proprio trabalho. */
export function resumoPorRecurso(
  catalogo: Catalogo | null,
  marcadas: Set<string>,
  secao?: string,
  escopos?: MapaEscopos,
): string[] {
  if (!catalogo) return [];
  const linhas: string[] = [];
  for (const s of catalogo.secoes) {
    if (secao && s.chave !== secao) continue;
    for (const r of s.recursos) {
      const verbos = r.permissoes
        .filter((p) => marcadas.has(p.chave))
        .map((p) => p.verbo_rotulo);
      if (!verbos.length) continue;
      /* O sufixo so aparece quando ha o que restringir: com apenas "Ver"
         marcado, dizer "so os que ele criou" seria falso — a leitura continua
         sendo a lista inteira do municipio. */
      const restringe =
        (escopos?.[r.recurso] ?? ESCOPO_PADRAO) === "proprios"
        && permissoesDeEscopo(catalogo, r).some((p) => marcadas.has(p.chave));
      // O rotulo da opcao vem do catalogo, como todo o resto do vocabulario.
      const rotuloEscopo = catalogo.escopos?.opcoes
        ?.find((o) => o.valor === "proprios")?.rotulo;
      linhas.push(
        `${r.recurso_rotulo}: ${verbos.join(", ")}`
        + (restringe && rotuloEscopo ? ` (${rotuloEscopo.toLowerCase()})` : ""),
      );
    }
  }
  return linhas;
}

/** O alcance de um recurso, ja com o padrao aplicado. */
export function escopoDe(mapa: MapaEscopos | undefined, recurso: string): Escopo {
  return mapa?.[recurso] ?? ESCOPO_PADRAO;
}

/** Todas as chaves de uma secao — para o "marcar seção inteira".
 *
 *  Existe aqui, e nao na tela, porque a tela nao pode reconstruir a lista de
 *  chaves de cabeca: ela so conhece o que a API mandou. */
export function chavesDaSecao(secao: SecaoCatalogo): string[] {
  return secao.recursos.flatMap((r) => r.permissoes.map((p) => p.chave));
}
