"use client";

import TransfereGovPropostas from "@/components/TransfereGovPropostas";

export default function TransfereGovEncerradasPage() {
  return (
    <TransfereGovPropostas
      categoria="encerradas"
      titulo="Transfere Gov - Encerradas"
      subtitulo="Instrumentos finalizados (Anulado, Rescindido, Prestação de Contas Concluída/Aprovada) - SICONV"
    />
  );
}
