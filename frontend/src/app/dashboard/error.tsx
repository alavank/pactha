"use client";

// A REDE DE BAIXO. Antes deste arquivo o sistema não tinha nenhum limite de
// erro: um único campo com formato inesperado, numa aba de um modal, derrubava
// a árvore inteira do React e o cliente via a tela branca do Next com
// "This page couldn't load" e um botão de recarregar — sem menu, sem saber onde
// estava, e sem nada que dissesse à Alavank o que tinha acontecido.
//
// Aqui o dano fica CONTIDO no conteúdo do painel: a barra lateral continua de
// pé, o município continua escolhido, e o gestor troca de módulo sem perder a
// sessão. E o `digest` dá o que faltava — um identificador que casa a tela do
// cliente com a linha do log do servidor, para o suporte não depender de print.
//
// Não substitui corrigir a causa; existe porque a causa seguinte ainda não é
// conhecida, e dado de portal público muda de forma sem avisar ninguém.

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ErroDoPainel({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // O console é o que o dono consegue printar quando reporta. Manter a
    // mensagem crua e o digest juntos poupa uma ida ao servidor.
    console.error("[PACTHA] falha ao montar a tela:", error);
  }, [error]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center p-4">
      <div
        className="w-full max-w-lg rounded-2xl p-5"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
      >
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 size-5 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold" style={{ color: "var(--bi-text)" }}>
              Não foi possível montar esta tela
            </h2>
            {/* O que o gestor precisa saber, em ordem: o dado dele está a
                salvo, e o problema é nosso. Nada de "erro inesperado". */}
            <p className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
              Os dados do município não foram alterados — a falha é só na exibição.
              Tente novamente; se repetir, use o menu ao lado para seguir em outro
              módulo e avise a Alavank informando o código abaixo.
            </p>
            {error.digest && (
              <p className="bi-id mt-2 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Código: {error.digest}
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" onClick={() => reset()}>
                <RefreshCw className="mr-1 size-4" />
                Tentar de novo
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
