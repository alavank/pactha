"use client";

/* EMENDAS PARLAMENTARES — uma tela só, com abas Federais | Estaduais | Parlamentares.
 *
 * Pedido do dono em 17/09/2026: o assunto estava em quatro itens soltos do menu
 * (Federais › Emendas parlamentares, Estaduais › Emendas Estaduais e Emendas
 * Estaduais RS, e Parlamentares). As quatro rotas antigas redirecionam para cá,
 * na aba equivalente.
 *
 * ⚠️⚠️ CADA ABA TEM A PERMISSÃO QUE JÁ EXISTIA (decisão do dono): Federais =
 * `emendas_federais`; Estaduais = a tela da UF (MG `emendas`, RS `emendas_rs`,
 * GO `repasses`); Parlamentares = `parlamentares`. A aba some para quem não tem
 * a chave, e o servidor cobra de novo. Não há tela `emendas_parlamentares` no
 * catálogo — o menu declara as abas em `lib/menu.ts` (`abas`), e é de lá que a
 * árvore de permissões e o guard de rota tiram as chaves.
 *
 * A aba vai na URL (`?aba=`): o link colado no WhatsApp abre onde foi copiado.
 */

import React, { Suspense, useState, useSyncExternalStore } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { podeVerTela } from "@/lib/telas";
import { Abas, Vazio } from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import AbaFederais from "@/components/emendas/AbaFederais";
import AbaEstaduais, { TELA_ESTADUAL_POR_UF } from "@/components/emendas/AbaEstaduais";
import AbaParlamentares from "@/components/emendas/AbaParlamentares";
import { DetalheEmenda, type Origem } from "@/components/emendas/DetalheEmenda";

type Aba = "federais" | "estaduais" | "parlamentares";

const TELAS_DAS_ABAS = ["emendas_federais", "emendas", "emendas_rs", "repasses", "parlamentares"];
// A lista de telas da pessoa só muda com novo login (que recarrega a página).
const semAssinatura = () => () => {};

function EmendasParlamentares() {
  const sp = useSearchParams();
  const router = useRouter();
  const { municipioId } = useMunicipio();
  const uf = useUfDoMunicipio();
  const [aberta, setAberta] = useState<{ origem: Origem; id: string } | null>(null);

  /* ⚠️ A PERMISSÃO SÓ EXISTE NO NAVEGADOR: `podeVerTela` lê o localStorage.
     No servidor o snapshot é `null` (e a tela mostra o carregando); lê-la no
     render direto faria o servidor desenhar três abas e o navegador duas, e o
     React acusaria a divergência. O snapshot é TEXTO para ser estável entre
     leituras. */
  const podeTxt = useSyncExternalStore(
    semAssinatura,
    () => TELAS_DAS_ABAS.map((t) => (podeVerTela(t) ? "1" : "0")).join(""),
    () => null,
  );
  const pode: Record<string, boolean> | null = podeTxt === null ? null
    : Object.fromEntries(TELAS_DAS_ABAS.map((t, i) => [t, podeTxt[i] === "1"]));

  if (!pode) {
    return <div className="flex h-64 items-center justify-center">
      <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} /></div>;
  }

  const telaEstadual = TELA_ESTADUAL_POR_UF[uf];
  // UF sem fonte (ES, TO…) mostra a aba com a frase de por que não há lista —
  // para quem já vê alguma das outras duas. Sem município (consolidado), some:
  // o estadual depende do estado de UM município.
  const estaduaisOn = !!municipioId && !!uf &&
    (telaEstadual ? pode[telaEstadual] : pode.emendas_federais || pode.parlamentares);
  const opcoes: Array<{ valor: Aba; label: string; on: boolean }> = [
    { valor: "federais", label: "Federais", on: pode.emendas_federais },
    { valor: "estaduais", label: "Estaduais", on: estaduaisOn },
    { valor: "parlamentares", label: "Parlamentares", on: pode.parlamentares },
  ];
  const pedida = sp.get("aba") as Aba | null;
  const aba = opcoes.find((o) => o.valor === pedida && o.on)?.valor
    ?? opcoes.find((o) => o.on)?.valor ?? null;
  const trocar = (v: Aba) => router.replace(`/dashboard/emendas-parlamentares?aba=${v}`, { scroll: false });
  const abrir = (origem: Origem, id: string) => setAberta({ origem, id });

  return (
    <div className="flex flex-col gap-4">
      <header>
        <TituloTela>Emendas parlamentares</TituloTela>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug" style={{ color: "var(--bi-muted)" }}>
          Tudo o que deputados e senadores destinaram ao município: as emendas federais, as
          estaduais e quem as assinou, com partido e cargo.
        </p>
      </header>

      {!aba ? (
        <Vazio>Você não tem acesso a nenhuma das abas desta tela.</Vazio>
      ) : (
        <>
          <Abas valor={aba} onChange={trocar} tamanho="md" opcoes={opcoes} />
          <div key={aba} className="bi-pane-enter">
            {aba === "federais" && <AbaFederais municipioId={municipioId} onAbrir={abrir} />}
            {aba === "estaduais" && <AbaEstaduais uf={uf} municipioId={municipioId} onAbrir={abrir} />}
            {aba === "parlamentares" && <AbaParlamentares />}
          </div>
        </>
      )}

      {aberta && municipioId && (
        <DetalheEmenda key={`${aberta.origem}:${aberta.id}`} origem={aberta.origem} id={aberta.id}
                       municipioId={municipioId} onFechar={() => setAberta(null)} onAbrir={abrir} />
      )}
    </div>
  );
}

export default function EmendasParlamentaresPage() {
  return (
    <Suspense fallback={
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
      </div>
    }>
      <EmendasParlamentares />
    </Suspense>
  );
}
