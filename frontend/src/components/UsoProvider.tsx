"use client";

// O PROVEDOR DA TELEMETRIA — captura navegação e tempo por tela.
//
// ⚠️ Precisa ser montado UMA vez, ACIMA do `<div key={escopo}>` do layout. O
// dashboard remonta a árvore inteira a cada troca de município; montado abaixo
// daquela chave, este componente remontaria junto e picaria a sessão em pedaços
// — perdendo justamente o gesto mais interessante de medir.

import { useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { iniciarSessao, registrar, telaDaRota } from "@/lib/uso";

export default function UsoProvider() {
  const anterior = useRef<{ rota: string; desde: number } | null>(null);

  useEffect(() => { iniciarSessao(); }, []);

  const rota = usePathname();

  useEffect(() => {
    if (!rota) return;
    const agora = Date.now();
    // Ao SAIR da tela anterior, registra quanto tempo ficou nela. É assim que
    // "quanto tempo em cada tela" sai sem uma linha a mais no banco: o `ms` do
    // evento de saída é a permanência.
    const ant = anterior.current;
    if (ant && ant.rota !== rota) {
      registrar({
        tela: telaDaRota(ant.rota), rota: ant.rota,
        acao: "sair", ms: agora - ant.desde,
      });
    }
    if (!ant || ant.rota !== rota) {
      registrar({ tela: telaDaRota(rota), rota, acao: "ver" });
      anterior.current = { rota, desde: agora };
    }
  }, [rota]);

  return null;
}
