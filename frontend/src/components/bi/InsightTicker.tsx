"use client";
// Faixa de insights da IA no cabecalho. Uma aba costuma ter mais de uma coisa
// importante a dizer, entao o backend devolve uma LISTA e aqui elas passam em
// slideshow — sempre as da aba que esta aberta.
//
// Se a IA nao estiver disponivel (sem ANTHROPIC_API_KEY, erro de rede), o
// backend manda um texto por template: a faixa nunca fica vazia nem quebra.
import { useEffect, useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { getInsights } from "@/lib/bi";
import { AbaId } from "@/lib/tela";
import { cn } from "@/lib/utils";

const TROCA_MS = 9_000;

export function InsightTicker({
  aba,
  municipioId,
  anos,
  tv,
  className,
}: {
  aba: AbaId;
  municipioId: number | null;
  anos: number[];
  tv?: boolean;
  className?: string;
}) {
  const [msgs, setMsgs] = useState<string[]>([]);
  const [i, setI] = useState(0);
  const [fonteIa, setFonteIa] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const reqRef = useRef(0);

  useEffect(() => {
    const req = ++reqRef.current;
    // Limpa antes de buscar para nao mostrar o insight da aba ANTERIOR enquanto
    // o da nova carrega — seria um texto errado sobre a tela que esta no ar.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMsgs([]);
    setI(0);
    setCarregando(true);
    getInsights(aba, municipioId, anos)
      .then((r) => {
        if (req !== reqRef.current) return;
        setMsgs(r.mensagens || []);
        setFonteIa(r.fonte === "ia");
      })
      .catch(() => {
        if (req === reqRef.current) setMsgs([]);
      })
      .finally(() => {
        if (req === reqRef.current) setCarregando(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aba, municipioId, anos.join(",")]);

  // Rotaciona entre as mensagens da aba atual.
  useEffect(() => {
    if (msgs.length < 2) return;
    const id = setInterval(() => setI((x) => (x + 1) % msgs.length), TROCA_MS);
    return () => clearInterval(id);
  }, [msgs.length]);

  // A FAIXA NUNCA SOME. Antes ela devolvia null enquanto carregava, e a cada
  // troca de aba todo o painel subia e descia de volta quando o texto chegava —
  // parecia defeito. O espaço é reservado sempre; o que muda é o conteúdo.
  const texto = msgs.length ? msgs[Math.min(i, msgs.length - 1)] : null;

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-2xl px-3.5 py-2.5",
        tv ? "min-h-[52px]" : "min-h-[44px]",
        className
      )}
      style={{ background: "var(--bi-accent-soft)", border: "1px solid var(--bi-line)" }}
      role="status"
      aria-live="polite"
    >
      <Sparkles className="size-4 shrink-0" style={{ color: "var(--bi-accent)" }} />
      {texto === null ? (
        // Carregando (ou sem insight): barra discreta no lugar do texto, para a
        // altura ser a mesma dos dois estados.
        <div className="min-w-0 flex-1">
          {carregando && (
            <div
              className="h-3 w-2/3 max-w-[420px] animate-pulse rounded-full"
              style={{ background: "var(--bi-line)" }}
            />
          )}
        </div>
      ) : (
        <p
          key={`${aba}-${i}`}
          className={cn(
            "bi-insight-enter line-clamp-2 min-w-0 flex-1 leading-snug",
            tv ? "text-[15px]" : "text-[13px]"
          )}
          style={{ color: "var(--bi-text)" }}
        >
          {texto}
        </p>
      )}
      {msgs.length > 1 && (
        <span className="flex shrink-0 items-center gap-1" aria-hidden>
          {msgs.map((_, k) => (
            <span
              key={k}
              className="size-1.5 rounded-full transition-opacity"
              style={{
                background: "var(--bi-accent)",
                opacity: k === i ? 1 : 0.3,
              }}
            />
          ))}
        </span>
      )}
      {texto !== null && (
        <span
          className="hidden shrink-0 text-[10px] uppercase tracking-wide sm:inline"
          style={{ color: "var(--bi-faint)" }}
          title={fonteIa ? "Texto gerado por IA a partir dos números desta aba" : "Resumo automático"}
        >
          {fonteIa ? "IA" : "auto"}
        </span>
      )}
    </div>
  );
}
