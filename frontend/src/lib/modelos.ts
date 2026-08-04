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
import { lerMapaEscopos, type MapaEscopos } from "@/lib/escopo";
// `recursosComEscopo`, `Catalogo`, `Permissao` e `Escopo` saíram junto com
// `preverModelo`: eram as peças da conta que agora é do servidor.
import { escopoDe, type MinhasPermissoes } from "@/lib/permissoes";

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

/** ⭐ O PLANO DA APLICACAO — calculado pelo SERVIDOR, nao aqui.
 *
 *  Isto era `preverModelo`, uma segunda implementacao da regra em TypeScript.
 *  A do servidor (`services/permissoes.py::aplicar_modelo`) tem 65 testes; esta
 *  tinha zero, porque o frontend nao tem runner de teste — ou seja, a copia que
 *  DE FATO rodava era a que ninguem verificava. Enquanto as duas concordassem,
 *  nada apareceria; no dia em que divergissem, a tela proporia uma caixinha que
 *  o `PUT` recusa e o administrador levaria um 403 sem entender o que fez.
 *
 *  `POST /permissoes/modelos/{id}/aplicar` NAO GRAVA NADA: devolve o estado que
 *  as caixinhas devem mostrar. Quem grava continua sendo o `PUT` de sempre,
 *  depois de o administrador conferir. */
export interface PlanoModelo {
  /** O estado FINAL das caixinhas e dos radios — e o que a tela marca. */
  sel: Set<string>;
  esc: MapaEscopos;
  /** Chaves que ENTRAM e que SAEM. */
  vaiConceder: string[];
  vaiRetirar: string[];
  /** Frases prontas do alcance que muda ("Gestão Interna: Somente os que ele criou"). */
  alcanceAlterado: string[];
  /** ⚠️ Do MOLDE, e nao entram: quem aplica nao tem essas chaves. */
  naoAplicadas: string[];
  /** ⚠️ Da PESSOA, e ficam intocadas: quem aplica nao pode retira-las. */
  preservadas: string[];
  /** Modulos cujo alcance do molde nao pode ser aplicado por quem aplica. */
  alcanceNaoAplicado: string[];
  /** Nada muda? O botao fica desligado. */
  mudou: boolean;
}

/** Pede ao servidor o plano de aplicar `modeloId` em `userId`.
 *
 *  ⚠️ MANDA O ESTADO DA TELA (`sel`/`esc`), e nao so o id: o modal e editavel
 *  antes de aplicar, e sem isto a conta sairia contra o cadastro GRAVADO — a
 *  tela diria "a marcar 7" quando sao 5, na cara de quem esta decidindo. */
export async function planoDoModelo(
  modeloId: number,
  userId: number,
  modo: string,
  sel: Set<string>,
  esc: MapaEscopos,
): Promise<PlanoModelo> {
  const r = await api.post<Record<string, unknown>>(
    `/permissoes/modelos/${modeloId}/aplicar`,
    { user_id: userId, modo, estado_atual: [...sel], escopos_atual: esc },
  );
  const d = r.data ?? {};
  const lista = (k: string): string[] =>
    Array.isArray(d[k]) ? (d[k] as unknown[]).map(String) : [];
  const vaiConceder = lista("vai_conceder");
  const vaiRetirar = lista("vai_retirar");
  const alcanceAlterado = lista("alcance_alterado");
  return {
    sel: new Set(lista("permissoes")),
    esc: (d.escopos ?? {}) as MapaEscopos,
    vaiConceder,
    vaiRetirar,
    alcanceAlterado,
    naoAplicadas: lista("nao_aplicadas"),
    preservadas: lista("preservadas"),
    alcanceNaoAplicado: lista("alcance_nao_aplicado"),
    mudou: vaiConceder.length > 0 || vaiRetirar.length > 0
           || alcanceAlterado.length > 0,
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
