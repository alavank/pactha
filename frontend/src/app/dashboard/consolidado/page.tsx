"use client";

/* CONSOLIDADO — a carteira inteira lado a lado (18/09/2026).
 *
 * Pedido da assessoria Freitas: "onde o Reginaldo Lopes mandou $$ para nossos
 * clientes?". Toda tela operacional é de UM município; esta atravessa todos os
 * municípios que o usuário enxerga.
 *
 * ⚠️ NÃO É O "Consolidado (todos)" do seletor, que saiu em 05/08/2026 e continua
 * fora. A regra que torna esta área segura: TODO NÚMERO SAI QUEBRADO POR
 * MUNICÍPIO — dinheiro nunca aparece somado sozinho, onde poderia ser lido como
 * número de um cliente.
 *
 * ⚠️ NÃO USA `useMunicipio().municipioId`: o escopo é o do usuário, resolvido no
 * backend (`services/bi.resolve_scope`).
 *
 * Abas: o PAINEL (PR 2) abre, porque é o que se olha toda semana; PARLAMENTARES
 * (PR 1) responde à pergunta que originou a área.
 */

import React, { useState } from "react";

import { TituloTela } from "@/components/TituloTela";
import { Abas } from "@/components/ui/superficies";
import { PainelCarteira } from "./PainelCarteira";
import { ParlamentaresCarteira } from "./ParlamentaresCarteira";

type Aba = "painel" | "parlamentares";

export default function ConsolidadoPage() {
  const [aba, setAba] = useState<Aba>("painel");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <TituloTela>Consolidado da carteira</TituloTela>
          <p className="text-sm text-muted-foreground">
            Os municípios da sua carteira, lado a lado — todo número aparece por município.
          </p>
        </div>
        <Abas<Aba> valor={aba} onChange={setAba} tamanho="md"
                   opcoes={[{ valor: "painel", label: "Painel da carteira" },
                            { valor: "parlamentares", label: "Parlamentares" }]} />
      </div>
      {aba === "painel" ? <PainelCarteira /> : <ParlamentaresCarteira />}
    </div>
  );
}
