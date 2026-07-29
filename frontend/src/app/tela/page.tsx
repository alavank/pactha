"use client";
// Modo Tela do usuário LOGADO — a janela que o botão "Modo Tela" abre.
//
// O corpo mora em components/bi/ModoTela.tsx porque o link público (/t/<slug>)
// exibe exatamente a mesma tela; o que muda é só de onde vem o token e o filtro.
import { Suspense } from "react";
import { ModoTela } from "@/components/bi/ModoTela";

export default function ModoTelaPage() {
  return (
    <Suspense
      fallback={
        <div className="bi-skin grid h-screen place-items-center text-sm">
          Carregando painel…
        </div>
      }
    >
      <ModoTela />
    </Suspense>
  );
}
