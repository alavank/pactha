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
 * ⭐ ABAS POR ASSUNTO (revisão do dono, 19/09/2026). A primeira versão abria num
 * "painel da carteira" que empilhava regularidade, vencimentos, emendas e Radar
 * numa rolagem só — "convênio que vence em 90 dias não tem a ver com
 * regularidade". Agora cada assunto é uma aba, e a barra fica em destaque logo
 * abaixo do título (antes era um seletor miúdo no canto direito). A aba vive na
 * URL (`?aba=`): o link mandado para a equipe abre no lugar certo.
 */

import React, { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { CalendarClock, FileSpreadsheet, Radar, ShieldCheck, Users } from "lucide-react";

import { TituloTela } from "@/components/TituloTela";
import { ParlamentaresCarteira } from "./ParlamentaresCarteira";
import { RadarCarteira } from "./RadarCarteira";
import { RegularidadeCarteira } from "./RegularidadeCarteira";
import { RelatoriosCarteira } from "./RelatoriosCarteira";
import { VigenciasCarteira } from "./VigenciasCarteira";

const ABAS = [
  { id: "regularidade", rotulo: "Regularidade", sub: "CAUC e estadual", icon: ShieldCheck },
  { id: "vigencias", rotulo: "Vigências", sub: "vencendo em 120 dias", icon: CalendarClock },
  { id: "parlamentares", rotulo: "Parlamentares", sub: "quem mandou recurso", icon: Users },
  { id: "radar", rotulo: "Radar", sub: "programas com dono", icon: Radar },
  { id: "relatorios", rotulo: "Relatórios", sub: "planilhas da carteira", icon: FileSpreadsheet },
] as const;
type Aba = (typeof ABAS)[number]["id"];

export default function ConsolidadoPage() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const daUrl = params.get("aba");
  const aba: Aba = ABAS.some((a) => a.id === daUrl) ? (daUrl as Aba) : "regularidade";
  const trocar = useCallback((id: Aba) => {
    const p = new URLSearchParams(params.toString());
    p.set("aba", id);
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  }, [params, pathname, router]);

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>Consolidado da carteira</TituloTela>
        <p className="text-sm text-muted-foreground">
          Os municípios da sua carteira, lado a lado — todo número aparece por município.
        </p>
      </div>

      {/* A BARRA DE ABAS em destaque, com a mesma gramática (`bi-folder-tab`)
          da tela de Regularidade e do Painel de Indicadores — maior, com ícone
          e o que cada uma responde, para ninguém procurar onde trocar. */}
      <div className="bi-folder-tabs flex flex-wrap items-end gap-1 border-b"
           style={{ borderColor: "var(--bi-line)" }} role="tablist">
        {ABAS.map((a) => {
          const Icon = a.icon;
          const ativa = a.id === aba;
          return (
            <button key={a.id} type="button" role="tab" aria-selected={ativa} data-active={ativa}
                    className="bi-folder-tab px-4 py-2.5" onClick={() => trocar(a.id)}>
              <span className="flex items-center gap-2">
                <Icon className="size-4" />
                <span className="flex flex-col items-start leading-tight">
                  <span className="text-[14px] font-semibold">{a.rotulo}</span>
                  <span className="hidden text-[10px] font-normal sm:inline" style={{ color: "var(--bi-faint)" }}>
                    {a.sub}
                  </span>
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {aba === "regularidade" && <RegularidadeCarteira />}
      {aba === "vigencias" && <VigenciasCarteira />}
      {aba === "parlamentares" && <ParlamentaresCarteira />}
      {aba === "radar" && <RadarCarteira />}
      {aba === "relatorios" && <RelatoriosCarteira />}
    </div>
  );
}
