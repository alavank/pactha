/* O ANO CORRENTE JÁ VEM MARCADO — em toda tela que filtra por ano.
 *
 * ⭐ POR QUE (pedido do dono, 04/09/2026): abrir com "todos os anos" joga na
 * cara do gestor a soma de uma década. O número fica absurdo, o gráfico fica
 * ilegível, e a primeira impressão de qualquer tela é a de um sistema que
 * mostra dado demais. O ano em que se está é o recorte que quase sempre se
 * quer — e quem precisa de mais tem o filtro ali do lado, com um clique.
 *
 * ⚠️ NÃO É `new Date().getFullYear()` FIXADO NO CÓDIGO. Hoje é 2026; em janeiro
 * vira 2027 sozinho, sem ninguém lembrar de mexer. Um literal aqui seria uma
 * bomba-relógio silenciosa: a tela continuaria abrindo em 2026 e ninguém
 * associaria "o dashboard está vazio" a uma constante esquecida.
 *
 * ⚠️ E SE NÃO HOUVER DADO DO ANO CORRENTE, cai no ANO MAIS RECENTE que existir.
 * Selecionar 2026 numa tela cujo último dado é de 2024 abriria a tela VAZIA — e
 * tela vazia lê-se como defeito, não como filtro. O objetivo é não assustar;
 * trocar "número grande demais" por "nada aqui" seria trocar um susto por outro.
 *
 * ⚠️ E SÓ AGE UMA VEZ. Se a pessoa limpar o filtro de propósito para ver tudo,
 * o padrão não pode voltar e desfazer a escolha dela na próxima renderização.
 */
import { useEffect, useRef } from "react";

/** O ano corrente, como string — que é como os filtros guardam. */
export const anoCorrente = () => String(new Date().getFullYear());

/**
 * Marca o ano corrente assim que a lista de anos aparecer.
 *
 * Os anos disponíveis quase sempre chegam DEPOIS (vêm de fetch ou de um `useMemo`
 * sobre os dados), por isso um efeito e não um valor inicial de `useState`.
 *
 * @param disponiveis anos que o filtro oferece, em qualquer ordem
 * @param aplicar     recebe a seleção inicial (normalmente `setAnosSel`)
 * @param ativo       `false` suspende o padrão (ex.: a tela restaurou um filtro salvo)
 */
export function useAnoCorrentePadrao(
  disponiveis: Array<string | number> | undefined,
  aplicar: (anos: string[]) => void,
  ativo = true,
): void {
  const jaAplicou = useRef(false);
  /* ⚠️ A DEPENDÊNCIA É O CONTEÚDO, NÃO O ARRAY. Metade das telas passa uma
     expressão que constrói a lista na hora (`anosOpcoes(2010)`, um `useMemo`
     recalculado) — referência nova a cada render, e o efeito rodaria em todas
     elas. A `ref` impediria o estrago, mas não o trabalho repetido. */
  const chave = (disponiveis || []).map(String).filter(Boolean).sort().join(",");
  useEffect(() => {
    if (!ativo || jaAplicou.current) return;
    if (!chave) return;                // ainda não carregou: tenta na próxima
    const anos = chave.split(",");
    jaAplicou.current = true;
    const atual = anoCorrente();
    // Ordenação de string serve porque todo ano tem quatro dígitos: o mais
    // recente é o maior lexicograficamente.
    const escolhido = anos.includes(atual) ? atual : anos.at(-1);
    if (escolhido) aplicar([escolhido]);
  }, [chave, aplicar, ativo]);
}
