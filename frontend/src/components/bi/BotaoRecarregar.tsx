"use client";
// O BOTÃO DE RECARREGAR DO PAINEL — e por que ele deixou de ser um ícone mudo.
//
// ⚠️ O ANTERIOR PARECIA NÃO FUNCIONAR, e o dono estava certo: ele chamava
// `recarregar()` da aba, que refaz a busca com `forcar=true`. Isso derruba o
// cache em memória do navegador — mas NÃO o do servidor, que guarda o payload
// de cada aba por ~40s. Resultado: clicar trazia exatamente os mesmos números,
// com um giro de meio segundo no ícone. Sem nada mudando na tela, a conclusão
// óbvia é "está quebrado".
//
// E o ícone era um círculo de setas sem rótulo, ao lado de uma engrenagem
// também sem rótulo. Dois símbolos mudos lado a lado, um deles sendo o gerador
// de link de acesso externo.
//
// ⭐ O QUE ELE FAZ AGORA, e é o que o dono pediu — o equivalente ao
// Ctrl+Shift+R do teclado, que "limpa o cache, aquele que é melhor e mais
// eficaz que somente dar refresh comum":
//
//   1. descarta o cache em memória das abas (`lib/useAbaBi.ts`);
//   2. apaga o Cache Storage — é o que o service worker do app de celular
//      guarda, e é justamente o que um F5 comum NÃO descarta;
//   3. recarrega a página do servidor.
//
// ⚠️ O QUE ELE **NÃO** ALCANÇA, e a honestidade importa aqui: o cache do
// SERVIDOR (~40s por aba). Nenhum botão do navegador alcança aquilo — nem o
// Ctrl+Shift+R de verdade. Passados 40 segundos, o dado vem novo de qualquer
// jeito. Por isso o rótulo é «Atualizar» e não «Buscar dados novos»: prometer a
// segunda coisa seria repetir o defeito que este arquivo conserta.
import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { limparCacheAbas } from "@/lib/useAbaBi";

export default function BotaoRecarregar() {
  const [limpando, setLimpando] = useState(false);

  const recarregarForte = async () => {
    setLimpando(true);
    limparCacheAbas();
    try {
      // `caches` não existe em contexto inseguro nem em todo navegador, e pode
      // recusar por política de site. Falhar aqui não pode impedir o reload —
      // que é a parte que resolve o problema do usuário.
      if (typeof window !== "undefined" && "caches" in window) {
        const chaves = await caches.keys();
        await Promise.all(chaves.map((k) => caches.delete(k)));
      }
    } catch {
      /* segue para o reload de qualquer forma */
    }
    window.location.reload();
  };

  return (
    <button
      type="button"
      onClick={recarregarForte}
      disabled={limpando}
      title="Limpa o cache do navegador e recarrega a página, como o Ctrl+Shift+R"
      className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold bi-hover disabled:opacity-60"
      style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
    >
      <RefreshCw className={limpando ? "size-3.5 animate-spin" : "size-3.5"} />
      Atualizar
    </button>
  );
}
