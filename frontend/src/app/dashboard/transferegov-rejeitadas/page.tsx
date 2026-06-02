"use client";

import TransfereGovPropostas from "@/components/TransfereGovPropostas";

export default function TransfereGovRejeitadasPage() {
  return (
    <TransfereGovPropostas
      categoria="rejeitadas"
      titulo="Transfere Gov - Rejeitadas"
      subtitulo="Propostas rejeitadas (incluindo por impedimento tecnico) - SICONV"
    />
  );
}
