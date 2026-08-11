"use client";

import TransfereGovPropostas from "@/components/TransfereGovPropostas";

export default function TransfereGovVoluntariasPage() {
  return (
    <TransfereGovPropostas
      categoria="voluntarias"
      titulo="Transfere Gov - Voluntárias"
      /* Também estava estreito demais: o filtro pega TODO o fluxo de análise —
         enviada, em complementação e já aprovada —, não só "enviado para
         análise". É aqui que aparecem as propostas dos anos mais recentes, que
         é o que o gestor procura quando estranha a Geral parada em 2024. */
      subtitulo="Propostas no fluxo de análise do SICONV: enviadas, em complementação e já aprovadas — antes de virarem instrumento em execução."
    />
  );
}
