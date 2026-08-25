"use client";

import TransfereGovPropostas from "@/components/TransfereGovPropostas";

export default function TransfereGovVoluntariasPage() {
  return (
    <TransfereGovPropostas
      categoria="voluntarias"
      titulo="Transfere Gov - Voluntárias"
      /* ⭐ A tela passou a mostrar o CICLO DE VIDA INTEIRO (pedido do dono,
         08/2026). Antes ela parava onde a proposta virava instrumento: no dia da
         celebração o convênio sumia daqui e reaparecia em «Em execução», e quem
         acompanhava uma proposta do início ao fim trocava de aba no meio do
         caminho.

         O efeito colateral que fechava o cerco: as opções do filtro de situação
         saem das LINHAS CARREGADAS (ver TransfereGovPropostas.tsx), então
         «Em execução» não podia sequer ser escolhida aqui — as linhas nunca
         chegavam. Agora chegam, e o filtro as oferece.

         Rejeitadas e encerradas continuam fora: são desfecho, não trabalho em
         curso, e cada uma tem aba própria. */
      subtitulo="O ciclo de vida completo no SICONV: propostas em análise, em complementação, aprovadas e instrumentos já em execução. Use o filtro de situação para recortar. Rejeitadas e encerradas têm abas próprias."
    />
  );
}
