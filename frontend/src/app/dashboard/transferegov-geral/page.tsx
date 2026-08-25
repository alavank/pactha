"use client";

import TransfereGovPropostas from "@/components/TransfereGovPropostas";

export default function TransfereGovGeralPage() {
  return (
    <TransfereGovPropostas
      categoria="geral"
      titulo="Transfere Gov - Em execução"
      /* O subtítulo antigo dizia "em execução, APROVADOS, etc." — e aprovado é
         justamente o que esta tela NÃO mostra: o filtro manda quem ainda está
         no fluxo de análise (inclusive já aprovado) para Voluntárias. O efeito
         era um município cujo ano mais novo AQUI é 2024 enquanto ele tem 14
         propostas de 2025/2026 nas outras abas — o gestor lê "consolidados",
         vê 2024 no topo e conclui que a coleta parou. Dizer para onde o resto
         foi custa uma linha e evita a desconfiança no dado. */
      subtitulo="Instrumentos em execução e demais situações em curso (SICONV). O que ainda está no fluxo de análise — inclusive o já aprovado — fica em Voluntárias; rejeitadas e encerradas têm abas próprias."
    />
  );
}
