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
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-4">
      <div className="flex items-start justify-between gap-3 border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <HeartHandshake className="size-6" style={{ color: "var(--bi-muted)" }} />
            Programações do Estrutura SUAS
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Painel oficial do MDS — acompanhamento das programações do cofinanciamento
            federal do Estrutura SUAS. Use os filtros do próprio painel (UF/município).
          </p>
        </div>
        <a
          href={PAINEL_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1.5 rounded-xl px-3 py-2 text-[12px] font-semibold transition-colors hover:brightness-95"
          style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
        >
          <ExternalLink className="size-4" />
          Abrir em nova aba
        </a>
      </div>

      {/* O painel é do MDS e tem a estética DELE — não dá para tokenizar o que
          vive dentro do iframe. O que a identidade controla é a moldura: o
          mesmo cartão do resto do sistema, e não uma caixa de canto pequeno. */}
      <div
        className="flex-1 overflow-hidden"
        style={{
          background: "var(--bi-surface)",
          border: "1px solid var(--bi-line)",
          borderRadius: "var(--bi-radius)",
        }}
      >
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
