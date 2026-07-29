"use client";
// Controle do slideshow do Modo Tela: rosca de contagem regressiva + transporte
// (retroceder / play-pause / avancar). O MESMO componente aparece nos dois
// lugares — ao lado do botao "Modo Tela" no painel de indicadores e no topo da
// janela da tela — porque o prefeito pode comandar de qualquer um dos dois.
//
// Ele nao tem cronometro proprio: recebe `restante`/`duracao` de quem manda no
// relogio (a janela da tela) e so desenha. Quem interpola entre um `state` e o
// proximo e o hook `useTelaControle`.
import React from "react";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { cn } from "@/lib/utils";

export function RoscaContagem({
  restante,
  duracao,
  tocando,
  size = 34,
}: {
  restante: number;
  duracao: number;
  tocando: boolean;
  size?: number;
}) {
  const seg = Math.max(0, Math.ceil(restante / 1000));
  // Preenche conforme o tempo PASSA (vazia no inicio, cheia na hora de virar) —
  // e o "esta chegando o momento" que o painel precisa comunicar.
  const pct = duracao > 0 ? Math.max(0, Math.min(1, 1 - restante / duracao)) : 0;
  const r = 15;
  const circ = 2 * Math.PI * r;
  return (
    <span
      className="relative inline-grid shrink-0 place-items-center"
      style={{ width: size, height: size }}
      title={tocando ? `Vira em ${seg}s` : "Slideshow pausado"}
      aria-label={tocando ? `Próxima aba em ${seg} segundos` : "Slideshow pausado"}
      role="timer"
    >
      <svg viewBox="0 0 36 36" width={size} height={size} className="-rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" stroke="var(--bi-line)" strokeWidth="3" />
        <circle
          cx="18"
          cy="18"
          r={r}
          fill="none"
          stroke={tocando ? "var(--bi-accent)" : "var(--bi-faint)"}
          strokeWidth="3"
          strokeLinecap="round"
          strokeDasharray={`${circ * pct} ${circ}`}
          style={{ transition: "stroke-dasharray .25s linear" }}
        />
      </svg>
      <span
        className="bi-num absolute inset-0 grid place-items-center"
        style={{ fontSize: size * 0.32, color: "var(--bi-text)" }}
      >
        {seg}
      </span>
    </span>
  );
}

export interface ControleProps {
  restante: number;
  duracao: number;
  tocando: boolean;
  onPlayPause: () => void;
  onNext: () => void;
  onPrev: () => void;
  /** Rotulo curto ao lado (ex.: "Geral · 2 de 6"). */
  legenda?: string;
  className?: string;
  compacto?: boolean;
}

export function SlideshowControls({
  restante,
  duracao,
  tocando,
  onPlayPause,
  onNext,
  onPrev,
  legenda,
  className,
  compacto,
}: ControleProps) {
  const btn =
    "grid place-items-center rounded-lg transition-colors hover:opacity-80 disabled:opacity-40";
  const btnStyle: React.CSSProperties = {
    background: "var(--bi-surface-2)",
    border: "1px solid var(--bi-line)",
    color: "var(--bi-muted)",
  };
  const tam = compacto ? "size-7" : "size-8";
  const icone = compacto ? "size-3.5" : "size-4";
  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 rounded-2xl px-2 py-1.5",
        className
      )}
      style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
    >
      <RoscaContagem
        restante={restante}
        duracao={duracao}
        tocando={tocando}
        size={compacto ? 30 : 34}
      />
      {legenda && (
        <span
          className="mr-0.5 hidden max-w-[13rem] truncate text-[11px] font-medium sm:inline"
          style={{ color: "var(--bi-muted)" }}
        >
          {legenda}
        </span>
      )}
      <button type="button" onClick={onPrev} className={cn(btn, tam)} style={btnStyle} title="Aba anterior" aria-label="Aba anterior">
        <SkipBack className={icone} />
      </button>
      <button
        type="button"
        onClick={onPlayPause}
        className={cn(btn, tam)}
        style={{
          ...btnStyle,
          background: tocando ? "var(--bi-surface-2)" : "var(--bi-accent-soft)",
          color: tocando ? "var(--bi-muted)" : "var(--bi-accent)",
        }}
        title={tocando ? "Pausar slideshow" : "Reproduzir slideshow"}
        aria-label={tocando ? "Pausar slideshow" : "Reproduzir slideshow"}
      >
        {tocando ? <Pause className={icone} /> : <Play className={icone} />}
      </button>
      <button type="button" onClick={onNext} className={cn(btn, tam)} style={btnStyle} title="Próxima aba" aria-label="Próxima aba">
        <SkipForward className={icone} />
      </button>
    </div>
  );
}
