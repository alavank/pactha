"use client";

// O TÍTULO DE UMA TELA — tamanho e ícone decididos num lugar só.
//
// Pedido do dono em 07/09/2026: *"deixe todos em tamanho 24px e sempre tenha um
// ícone para cada título"*. Antes disso o sistema tinha 47 `<h1>` escritos à
// mão, e eles divergiam em duas coisas ao mesmo tempo:
//
//   · TAMANHO — 42 em `text-2xl` (24px) e 5 em `text-[18px]`, as cinco telas
//     mais novas. Trocar de menu mudava o tamanho do título;
//   · ÍCONE — 15 tinham, 32 não. E não havia regra: telas irmãs, feitas na mesma
//     semana, umas com e outras sem.
//
// Cada `<h1>` à mão é uma decisão a mais para alguém tomar (e errar) na próxima
// tela. Aqui não há decisão: o tamanho é o do sistema e o ícone sai de
// `lib/icones-tela.ts`, pela rota. Tela nova nasce certa sem ninguém lembrar de
// nada.
//
// ⚠️ ESTA PEÇA É SÓ O `<h1>`, de propósito. A tentação era embrulhar o cabeçalho
// inteiro (título + subtítulo + botões + selo de frescor), mas esses cabeçalhos
// são MUITO diferentes entre si — uns têm PDF/Word/Excel à direita, outros um
// parágrafo de três linhas, outros um aviso de coleta. Uma peça que tentasse
// abraçar os 47 casos viraria uma pilha de props opcionais, e a primeira tela
// que não coubesse voltaria a escrever `<h1>` à mão. Trocando só o `<h1>`, cada
// tela mantém o cabeçalho que já tem.
import { createElement } from "react";
import { usePathname } from "next/navigation";
import { iconeDaTela } from "@/lib/icones-tela";

export function TituloTela({
  children,
  /** Sobrepõe o ícone da rota. Use só quando a tela mostrar algo que a rota não
   *  sabe — um documento de um tipo específico, por exemplo. O normal é não
   *  passar: o mapa por rota é o que mantém título e menu contando a mesma
   *  história. */
  icon: IconeForcado,
  className = "",
}: {
  children: React.ReactNode;
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  className?: string;
}) {
  const pathname = usePathname();
  const icone = IconeForcado ?? iconeDaTela(pathname);
  return (
    <h1 className={`flex items-center gap-2 text-2xl font-bold text-base-content ${className}`}>
      {/* ⚠️ `createElement` e não `<Icone />`: escrito como JSX, o lint do React
          Compiler lê uma variável PascalCase atribuída dentro do render como
          COMPONENTE CRIADO NO RENDER (`Cannot create components during render`)
          e acusa erro. Aqui não há criação — o ícone é um componente de módulo
          escolhido por rota —, mas a regra não tem como saber. Onde a peça
          recebe o ícone por PROP (`BlocoHead`, `GrupoFonte`), o JSX normal
          funciona; a diferença é a atribuição local.

          `aria-hidden` porque o ícone REPETE o título para quem lê a tela por
          áudio — ele é orientação visual, não conteúdo.

          ⚠️ E SEMPRE `--bi-muted`, NUNCA colorido. Duas telas pintavam o ícone
          do título (o Acordo FES em vermelho "porque é saúde/dívida", Telemetria
          e Status dos Dados no acento) — decoração pintada com a cor que nesta
          identidade significa ALERTA. Cor aqui gasta o acento em desenho e faz o
          título competir com o que de fato pede ação na tela. O título é que tem
          de puxar o olho, não o ícone. Centralizar isto é o que garante que a
          próxima tela não repita. */}
      {createElement(icone, {
        "aria-hidden": true,
        className: "size-6 shrink-0",
        style: { color: "var(--bi-muted)" },
      } as React.ComponentProps<typeof icone>)}
      <span className="min-w-0">{children}</span>
    </h1>
  );
}

export default TituloTela;
