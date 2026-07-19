"use client";

import { ExternalLink, HeartHandshake } from "lucide-react";

// Painel MDS "Acompanhamento de Programações do Estrutura SUAS" (Qlik Sense).
// Os dados vivem no painel (Qlik engine); embutimos o painel oficial via iframe
// — o painel permite framing (sem X-Frame-Options/CSP). Filtros ficam no próprio
// painel. Fonte oficial, sempre atualizada.
const PAINEL_URL =
  "https://paineis.mds.gov.br/public/extensions/Acompanhamento_de_Programacoes_do_Estrutura_SUAS/Acompanhamento_de_Programacoes_do_Estrutura_SUAS.html";

export default function EstruturaSuasPage() {
  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-base-content">
            <HeartHandshake className="size-5 text-primary" />
            Programações do Estrutura SUAS
          </h1>
          <p className="text-sm text-base-content/60 mt-1">
            Painel oficial do MDS — acompanhamento das programações do cofinanciamento
            federal do Estrutura SUAS. Use os filtros do próprio painel (UF/município).
          </p>
        </div>
        <a
          href={PAINEL_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-base-300 bg-base-100 px-3 py-2 text-sm font-medium text-base-content/80 hover:bg-base-200"
        >
          <ExternalLink className="size-4" />
          Abrir em nova aba
        </a>
      </div>

      <div className="flex-1 overflow-hidden rounded-lg border border-base-300 bg-base-100">
        <iframe
          src={PAINEL_URL}
          title="Programações do Estrutura SUAS — MDS"
          className="h-full w-full"
          loading="lazy"
        />
      </div>
    </div>
  );
}
