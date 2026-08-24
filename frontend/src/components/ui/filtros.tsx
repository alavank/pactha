"use client";
// Bloco de FILTROS RECOLHÍVEL — nasce MINIMIZADO.
//
// As telas do TransfereGov empilhavam de nove a onze controles em três linhas:
// antes de ver a primeira proposta o gestor rolava a página. Filtro é
// ferramenta, resultado é o produto — quem ocupa a dobra tem de ser o resultado.
//
// ⚠️ A REGRA QUE NÃO PODE CAIR: filtro ATIVO nunca fica escondido em silêncio.
// Um painel fechado escondendo um recorte aplicado é PIOR que um painel alto — o
// gestor vê 3 de 180 propostas e conclui que a coleta falhou. Por isso:
//   • os filtros ativos viram chips NO CABEÇALHO, visíveis com o painel fechado;
//   • cada chip remove SÓ o seu filtro (chip que não remove é enfeite);
//   • se já houver filtro ativo na montagem (link de KPI com `?vigencia=`), o
//     painel nasce ABERTO — o recorte veio de fora e precisa estar à vista.
//
// O estado dos campos mora em quem usa o painel, não aqui: recolher NÃO pode
// limpar nada.
import * as React from "react";
import { ChevronDown, ChevronRight, SlidersHorizontal } from "lucide-react";
import { Bloco } from "@/components/ui/superficies";

/** Um filtro aplicado, do jeito que o gestor o lê. */
export interface FiltroAtivo {
  /** Chave estável — serve de React key. */
  chave: string;
  /** Texto legível: "CNPJ: 18.243.220/0001-01", "Vence em 30 dias". */
  rotulo: string;
  /** Tira SÓ este filtro. */
  remover?: () => void;
}

export function PainelFiltros({
  ativos,
  children,
  direita,
  aoLimparTudo,
  titulo = "Filtros",
}: {
  ativos: FiltroAtivo[];
  children: React.ReactNode;
  /** Ação que pertence ao RESULTADO e não ao filtro (ex.: Gerar PDF). Fica no
   *  cabeçalho, visível mesmo com o painel fechado. */
  direita?: React.ReactNode;
  aoLimparTudo?: () => void;
  titulo?: string;
}) {
  /* Estado inicial PREGUIÇOSO, e não um efeito que abre depois: recorte que
     chegou pela URL (link de KPI com `?vigencia=`, selo de convênio do PAC com
     `?proposta=`) precisa nascer à vista, já no primeiro render. Depois disso
     quem manda no painel é o gestor — abrir sozinho a cada filtro digitado seria
     o painel brigando com quem o usa, e é por isso que `ativos` NÃO reabre nada
     depois da montagem. */
  const [aberto, setAberto] = React.useState(() => ativos.length > 0);

  return (
    <Bloco className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setAberto((v) => !v)}
          aria-expanded={aberto}
          className="inline-flex items-center gap-1.5 text-[13px] font-medium"
          style={{ color: "var(--bi-text)" }}
        >
          {aberto ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          <SlidersHorizontal className="size-3.5" style={{ color: "var(--bi-muted)" }} />
          {titulo}
          {ativos.length > 0 && (
            <span
              className="rounded px-1.5 py-px text-[10px] font-semibold"
              style={{ background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)" }}
            >
              {ativos.length}
            </span>
          )}
        </button>
        {direita && <div className="ml-auto flex flex-wrap items-center gap-2">{direita}</div>}
      </div>

      {/* Chips FORA do corpo recolhível de propósito: é o que garante que um
          recorte aplicado nunca some da tela junto com o painel. */}
      {ativos.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {ativos.map((f) => (
            <span
              key={f.chave}
              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{ background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)" }}
            >
              {f.rotulo}
              {f.remover && (
                <button
                  type="button"
                  onClick={f.remover}
                  className="opacity-60 hover:opacity-100"
                  aria-label={`Remover filtro ${f.rotulo}`}
                >
                  ×
                </button>
              )}
            </span>
          ))}
          {aoLimparTudo && (
            <button
              type="button"
              onClick={aoLimparTudo}
              className="text-[10px] underline"
              style={{ color: "var(--bi-muted)" }}
            >
              limpar tudo
            </button>
          )}
        </div>
      )}

      {aberto && (
        <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
          {children}
        </div>
      )}
    </Bloco>
  );
}
