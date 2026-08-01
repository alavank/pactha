"use client";
// PERÍODO LIVRE POR DATA — "de 23/03/2025 a 11/10/2025".
//
// Filtra sempre pelo FIM DA VIGÊNCIA. Foi decisão do dono, e é a única
// semântica que já existia pronta ponta a ponta no sistema (o TransfereGov já
// filtrava por `vig_fim_de`/`vig_fim_ate`). É também a pergunta que a equipe de
// convênios faz de verdade: "o que vence entre março e outubro".
//
// Por que não é só dois <input type="date"> soltos na barra: soltos, eles
// ocupam o dobro do espaço dos outros filtros, não mostram estado quando estão
// vazios, e não têm como avisar que o usuário inverteu as datas — que devolve
// lista vazia e parece "não tem nada", não "seu filtro está de cabeça para
// baixo". Aqui o gatilho resume o que está aplicado, igual aos MultiSelects ao
// lado, e o painel avisa quando o intervalo é impossível.
import * as React from "react";
import { CalendarRange, ChevronDown } from "lucide-react";
import { type Intervalo, intervaloInvalido, intervaloVazio, rotuloIntervalo } from "@/lib/periodo";

export function PeriodoVigencia({
  valor,
  onChange,
  className = "w-56",
  rotulo = "Fim da vigência",
}: {
  valor: Intervalo;
  onChange: (v: Intervalo) => void;
  className?: string;
  rotulo?: string;
}) {
  const [aberto, setAberto] = React.useState(false);
  const boxRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!aberto) return;
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setAberto(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setAberto(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [aberto]);

  const vazio = intervaloVazio(valor);
  const invalido = intervaloInvalido(valor);

  return (
    <div ref={boxRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        aria-label={`Período por ${rotulo.toLowerCase()}`}
        className={`mt-1 flex h-9 w-full items-center justify-between gap-2 rounded-lg border bg-base-100 px-3 text-sm transition-colors hover:bg-base-200 ${
          invalido ? "border-error text-error"
          : vazio ? "border-base-300 text-base-content"
          : "border-primary text-primary"
        }`}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          <CalendarRange className="size-4 shrink-0 opacity-70" />
          <span className="truncate">{vazio ? "Período (qualquer)" : rotuloIntervalo(valor)}</span>
        </span>
        <ChevronDown className={`size-4 shrink-0 opacity-60 transition-transform ${aberto ? "rotate-180" : ""}`} />
      </button>

      {aberto && (
        <div className="absolute z-50 mt-1 w-72 rounded-lg border border-base-300 bg-base-100 p-3 shadow-lg">
          <div className="mb-2 text-xs font-medium text-base-content/70">
            {rotulo} entre
          </div>
          <div className="flex items-center gap-2">
            <input
              type="date"
              value={valor.de ?? ""}
              onChange={(e) => onChange({ ...valor, de: e.target.value || undefined })}
              className="h-9 w-full rounded-lg border border-base-300 bg-base-100 px-2 text-sm"
              aria-label="Data inicial"
            />
            <span className="shrink-0 text-xs text-base-content/50">até</span>
            <input
              type="date"
              value={valor.ate ?? ""}
              onChange={(e) => onChange({ ...valor, ate: e.target.value || undefined })}
              className="h-9 w-full rounded-lg border border-base-300 bg-base-100 px-2 text-sm"
              aria-label="Data final"
            />
          </div>

          {invalido && (
            <p className="mt-2 text-xs text-error">
              A data inicial é depois da final — assim a lista vem vazia.
            </p>
          )}
          {/* Um lado só é uso legítimo e comum, não erro: "tudo que vence a
              partir de março" é uma pergunta inteira. */}
          <p className="mt-2 text-[11px] leading-snug text-base-content/50">
            Pode preencher só um dos lados.
          </p>

          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => onChange({})}
              className="flex-1 rounded px-2 py-1 text-xs font-medium text-base-content/70 hover:bg-base-200"
            >
              Limpar
            </button>
            <button
              type="button"
              onClick={() => setAberto(false)}
              className="flex-1 rounded bg-primary px-2 py-1 text-xs font-medium text-primary-content hover:bg-primary/90"
            >
              Aplicar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
