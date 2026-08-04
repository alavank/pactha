// MODELOS DE PERMISSAO — O MOLDE. E molde nao e heranca.
//
// ⚠️ A REGRA DO DONO, e ela decide TUDO o que este arquivo faz: as permissoes
// sao do USUARIO, individualmente. Um modelo nao "vale para" ninguem: ele e uma
// RECEITA que o administrador COPIA para as caixinhas de uma pessoa naquele
// instante. Depois da copia o vinculo acabou — mudar o modelo nao mexe em conta
// nenhuma, e "o que esta pessoa pode?" continua sendo respondivel olhando SO a
// pessoa. Se um dia alguem quiser transformar isto em heranca ("o usuario segue
// o modelo"), estara desfazendo a decisao inteira do RBAC deste produto.
//
// Por isso NAO existe aqui nenhum campo `modelo_id` no usuario, nenhuma funcao
// de "sincronizar" e nenhuma chamada que aplique modelo no servidor: aplicar
// acontece no CLIENTE, preenchendo as caixinhas do modal, e quem grava continua
// sendo o mesmo PUT de permissoes que ja existia.
//
// ⚠️ E aqui tambem nao ha lista de permissao nenhuma — vale a mesma regra de
// `lib/permissoes.ts`. O catalogo manda; o modelo so cita chaves dele. Chave que
// o modelo tenha e o catalogo nao conheca e IGNORADA na aplicacao: o catalogo do
// servidor e a fonte unica, e uma chave orfa (permissao removida do produto)
// nao pode virar caixinha fantasma na tela.
import api from "@/lib/api";
import { type Escopo, lerMapaEscopos, type MapaEscopos } from "@/lib/escopo";
import {
  escopoDe, recursosComEscopo,
  type Catalogo, type MinhasPermissoes, type Permissao,
} from "@/lib/permissoes";

/** Um molde, como a API o devolve. */
export interface Modelo {
  id: number;
  nome: string;
  descricao?: string | null;
  permissoes: string[];
  escopos: MapaEscopos;
}

/** O que vai no POST/PUT. Sem `id`: quem o define e a rota. */
export interface ModeloEntrada {
  nome: string;
  descricao: string;
  permissoes: string[];
  escopos: MapaEscopos;
}

/** A CHAVE que libera criar/editar/apagar molde — o unico ponto de contato do
 *  frontend com o nome que o backend escolheu.
 *
 *  Fica separada de `usuarios.conceder` de proposito: sao poderes diferentes.
 *  Conceder e decidir o que UMA pessoa faz; criar molde e escrever a receita que
 *  os OUTROS administradores vao aplicar — inclusive um molde de nome inocente
 *  ("Somente consulta") carregando uma caixinha sensivel. Nenhum molde escala
 *  privilegio sozinho (a aplicacao e filtrada pelo que quem aplica tem, aqui e
 *  no servidor), mas ele pauta o gesto dos outros, e isso merece caixinha
 *  propria em vez de vir de brinde com a de conceder. */
export const PERM_MODELOS = "usuarios.modelos";

/** Quem administra usuario deve poder criar molde? SIM — desde que tenha esta
 *  caixinha. Deixar molde como ato exclusivo de super-admin (conta da Alavank)
 *  devolveria a prefeitura a dependencia de abrir chamado para arrumar o proprio
 *  cadastro, e o motivo deste incremento e justamente operacional: cadastrar
 *  servidor virou marcar 66 caixas. Quem conhece os cargos de Monte Siao e Monte
 *  Siao. */
export function podeGerirModelos(minhas: MinhasPermissoes | null): boolean {
  return !!minhas && (minhas.super_admin || minhas.chaves.includes(PERM_MODELOS));
}

function lerModelo(bruto: unknown): Modelo {
  const b = (bruto ?? {}) as Record<string, unknown>;
  return {
    id: Number(b.id),
    nome: String(b.nome ?? ""),
    descricao: typeof b.descricao === "string" ? b.descricao : "",
    permissoes: Array.isArray(b.permissoes) ? b.permissoes.map(String) : [],
    escopos: lerMapaEscopos(b.escopos),
  };
}

export interface RespostaModelos {
  modelos: Modelo[];
  /** Quem pode CRIAR/EDITAR/APAGAR, respondido pelo servidor. `null` = a API
   *  nao respondeu isso, e ai quem decide e `podeGerirModelos` — mesma chave,
   *  mesma resposta, so que calculada aqui. */
  podeGerenciar: boolean | null;
}

export async function listarModelos(): Promise<RespostaModelos> {
  const r = await api.get<unknown>("/permissoes/modelos");
  /* Aceita a lista crua e o envelope `{modelos: [...], pode_gerenciar}`: o
     envelope e o que o servidor manda, e a lista crua e o que uma versao
     anterior mandaria. Errar aqui abriria a tela dizendo "nenhum modelo
     cadastrado" — um vazio que mente. */
  const env = (Array.isArray(r.data) ? null : r.data) as
    { modelos?: unknown[]; pode_gerenciar?: boolean } | null;
  const lista = (Array.isArray(r.data) ? r.data : (env?.modelos ?? [])) as unknown[];
  return {
    modelos: lista.map(lerModelo),
    podeGerenciar: typeof env?.pode_gerenciar === "boolean" ? env.pode_gerenciar : null,
  };
}

export async function criarModelo(dados: ModeloEntrada): Promise<Modelo> {
  const r = await api.post<unknown>("/permissoes/modelos", dados);
  return lerModelo(r.data);
}

export async function salvarModelo(id: number, dados: ModeloEntrada): Promise<Modelo> {
  const r = await api.put<unknown>(`/permissoes/modelos/${id}`, dados);
  return lerModelo(r.data);
}

export async function apagarModelo(id: number): Promise<void> {
  await api.delete(`/permissoes/modelos/${id}`);
}

// ---------------------------------------------------------------------------
// A APLICACAO — calculada uma vez, usada para PREVER e para APLICAR.
// ---------------------------------------------------------------------------

/** Os dois modos vivem no servidor (`services/permissoes.py`), que manda rótulo
 *  e descrição no catálogo. Aqui só as CHAVES, que são contrato — e o padrão
 *  `substituir`, que é o mesmo fail-safe do backend: modo desconhecido cai no
 *  que não concede nada por acidente. */
export const MODO_SUBSTITUIR = "substituir";
export const MODO_SOMAR = "somar";

/** O aviso da CÓPIA é obrigatório na tela, e o texto certo vem do catálogo
 *  (`catalogo.modelos.aviso`). Esta reserva existe só para o caso de a API não
 *  trazê-lo: um bloco que aplica modelo SEM dizer que aplicar é copiar é
 *  exatamente o que faz o administrador supor herança — e ficar calado é pior
 *  do que ter a frase escrita em dois lugares. */
export const AVISO_COPIA_RESERVA =
  "Aplicar um modelo COPIA as permissões para o cadastro desta pessoa, agora. "
  + "As caixinhas continuam editáveis e nada é gravado até você salvar. Depois "
  + "de salvo, mexer no modelo NÃO mexe mais nesta pessoa.";

/** O resultado de "e se eu aplicasse este modelo agora?".
 *
 *  ⚠️ `sel` e `esc` sao o estado FINAL ja pronto. A previa e a aplicacao saem da
 *  MESMA conta, e nao de duas — se fossem duas, a tela poderia prometer "22 a
 *  desmarcar" e o botao fazer outra coisa, e ninguem descobriria antes de salvar. */
export interface PreviaModelo {
  sel: Set<string>;
  esc: MapaEscopos;
  /** Caixinhas que o modelo LIGA nesta pessoa. */
  marcar: Permissao[];
  /** Caixinhas que o modelo DESLIGA — aplicar substitui, nao soma (ver abaixo). */
  desmarcar: Permissao[];
  /** O modelo pede e quem esta aplicando NAO tem: nao vao. */
  bloqueadas: Permissao[];
  /** O modelo nao tem, a pessoa tem, e quem aplica nao pode retirar: ficam. */
  mantidas: Permissao[];
  alcance: Array<{ recurso: string; rotulo: string; para: Escopo }>;
  /** Modulos em que o alcance do modelo NAO pode ser aplicado por quem aplica. */
  alcanceBloqueado: string[];
  mudou: boolean;
}

function rotuloDoRecurso(catalogo: Catalogo, recurso: string): string {
  for (const s of catalogo.secoes) {
    for (const r of s.recursos) if (r.recurso === recurso) return r.recurso_rotulo;
  }
  return catalogo.escopos?.recursos?.[recurso]?.recurso_rotulo ?? recurso;
}

/** APLICAR SUBSTITUI POR PADRAO. Somar existe, mas e escolha NOMEADA.
 *
 *  Um molde e o RETRATO INTEIRO de um cargo ("quem so consulta"), e nao um saco
 *  de acrescimos. Se somar fosse o padrao, aplicar "Somente consulta" numa conta
 *  ja aberta nao tiraria nada: o administrador leria o nome, veria a conta
 *  continuar podendo tudo e concluiria que o modelo nao funciona — ou pior, nao
 *  conferiria. Esse erro falha ABERTO (a pessoa fica com mais poder do que o
 *  nome promete), que e exatamente a doenca que este RBAC existe para curar.
 *
 *  `somar` continua servindo a um caso real e diferente — a pessoa que acumula
 *  duas funcoes —, e por isso e uma opcao com rotulo e explicacao (vindos do
 *  catalogo da API), e nao o comportamento silencioso do botao.
 *
 *  O risco oposto — clicar no molde errado numa conta ja configurada — e tratado
 *  na TELA, e nao invertendo a regra: a previa mostra quantas caixinhas caem
 *  ANTES do clique, nada e gravado (o PUT continua sendo o botao Salvar) e ha
 *  «Desfazer» enquanto a aplicacao estiver intacta.
 *
 *  ⚠️ ANTI-ESCALONAMENTO, e ele vale nos DOIS sentidos: caixinha que quem aplica
 *  nao possui nao e concedida (`bloqueadas`) NEM retirada (`mantidas`) — fica
 *  exatamente como estava. Um molde nao pode ser o caminho por fora do limite
 *  que a tela impoe caixinha a caixinha. O servidor recusa o mesmo no PUT; isto
 *  aqui e para o limite ser entendido antes do clique, e nao num 403 depois. */
export function preverModelo(
  catalogo: Catalogo,
  modelo: Modelo,
  sel: Set<string>,
  esc: MapaEscopos,
  posso: (chave: string) => boolean,
  alcanceTravado: (recurso: string) => boolean,
  modo: string = MODO_SUBSTITUIR,
): PreviaModelo {
  const somando = modo === MODO_SOMAR;
  const doModelo = new Set(modelo.permissoes);
  const novaSel = new Set<string>();
  const marcar: Permissao[] = [];
  const desmarcar: Permissao[] = [];
  const bloqueadas: Permissao[] = [];
  const mantidas: Permissao[] = [];

  for (const p of catalogo.permissoes) {
    const tem = sel.has(p.chave);
    const quer = doModelo.has(p.chave);
    if (!posso(p.chave)) {
      if (tem) novaSel.add(p.chave);
      if (quer && !tem) bloqueadas.push(p);
      /* `mantidas` so faz sentido SUBSTITUINDO: e a caixinha que o molde tiraria
         e a trava impediu de tirar. Somando, nada seria tirado de qualquer
         forma, e anunciar "esta continua marcada" seria alarmar sobre uma
         retirada que ninguem pediu. */
      else if (!quer && tem && !somando) mantidas.push(p);
      continue;
    }
    if (quer) {
      novaSel.add(p.chave);
      if (!tem) marcar.push(p);
    } else if (tem) {
      if (somando) novaSel.add(p.chave); else desmarcar.push(p);
    }
  }

  const novoEsc: MapaEscopos = { ...esc };
  const alcance: PreviaModelo["alcance"] = [];
  const alcanceBloqueado: string[] = [];
  /* ⚠️ SOMANDO, O ALCANCE NAO E TOCADO — e a mesma decisao do servidor
     (`aplicar_modelo_escopos`): alcance e um RADIO, e nao existe soma de dois
     radios. "O mais restritivo vence" ou "o do molde vence" seriam regras que
     ninguem consegue prever olhando a tela. */
  for (const recurso of somando ? [] : recursosComEscopo(catalogo)) {
    const atual = escopoDe(esc, recurso);
    const alvo = escopoDe(modelo.escopos, recurso);
    if (atual === alvo) continue;
    if (alcanceTravado(recurso)) {
      alcanceBloqueado.push(rotuloDoRecurso(catalogo, recurso));
      continue;
    }
    novoEsc[recurso] = alvo;
    alcance.push({ recurso, rotulo: rotuloDoRecurso(catalogo, recurso), para: alvo });
  }

  return {
    sel: novaSel,
    esc: novoEsc,
    marcar,
    desmarcar,
    bloqueadas,
    mantidas,
    alcance,
    alcanceBloqueado,
    mudou: marcar.length > 0 || desmarcar.length > 0 || alcance.length > 0,
  };
}

/** Os dois comparadores existem para o «Desfazer» saber se a aplicacao ainda
 *  esta INTACTA. Depois que o administrador mexe numa caixinha, desfazer
 *  deixaria de ser "cancelar aquele clique" e passaria a jogar fora o ajuste
 *  dele junto — entao o botao some. */
export function mesmoConjunto(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false;
  for (const x of a) if (!b.has(x)) return false;
  return true;
}

export function mesmoAlcance(a: MapaEscopos, b: MapaEscopos, recursos: Iterable<string>): boolean {
  for (const r of recursos) if (escopoDe(a, r) !== escopoDe(b, r)) return false;
  return true;
}
