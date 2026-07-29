"use client";
// Link público da TV: /t/<slug>.
//
// Rota curta de propósito. Antes o link levava o JWT de quiosque inteiro na
// query (~300 caracteres), o que era impossível de ditar por telefone, vazava
// credencial em histórico/print e só dava para revogar derrubando o quiosque
// inteiro — que ainda por cima era compartilhado entre todos os gestores.
// Agora a URL leva 12 caracteres, o token fica no banco e cada link é
// revogável sozinho (Ajustes -> Links publicados).
import { Suspense, use } from "react";
import { ModoTela } from "@/components/bi/ModoTela";

export default function TelaPublicaPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  return (
    <Suspense
      fallback={
        <div className="bi-skin grid h-screen place-items-center text-sm">
          Carregando painel…
        </div>
      }
    >
      <ModoTela slugPublico={slug} />
    </Suspense>
  );
}
