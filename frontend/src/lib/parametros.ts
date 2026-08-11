import api from "@/lib/api";

/** Um parâmetro do ambiente — uma linha da lista que o cliente cadastra. */
export type Parametro = {
  id: number;
  tipo: string;
  /** A CHAVE gravada no cadastro (`users.role`). Imutável depois de criada. */
  valor: string;
  /** O que a tela mostra. É o que o cliente edita. */
  rotulo: string;
  ordem: number;
  ativo: boolean;
  /** Do sistema: reordena e renomeia, mas não desativa nem exclui. */
  reservado: boolean;
};

/** Os parâmetros de um tipo.
 *
 *  `incluirInativos` existe para a TRADUÇÃO: o seletor de cadastro oferece só
 *  os ativos, mas a lista de usuários precisa saber o rótulo de quem já tem um
 *  perfil desativado — senão a tela mostra a chave crua ("analyst"), que é
 *  exatamente o defeito que a lista fixa em código já teve uma vez. */
export async function listarParametros(
  tipo: string,
  incluirInativos = false,
): Promise<Parametro[]> {
  const r = await api.get<Parametro[]>("/parametros", {
    params: { tipo, incluir_inativos: incluirInativos },
  });
  return Array.isArray(r.data) ? r.data : [];
}

/** chave -> rótulo, para traduzir o que já está gravado. */
export function mapaDeRotulos(lista: Parametro[]): Record<string, string> {
  return Object.fromEntries(lista.map((p) => [p.valor, p.rotulo]));
}
