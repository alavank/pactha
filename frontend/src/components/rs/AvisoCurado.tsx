"use client";

/* O AVISO DE CONTEÚDO CURADO — obrigatório em toda tela que não coleta.
 *
 * ⭐ POR QUE É UM COMPONENTE, e não um parágrafo copiado em cada tela: porque
 * ele não pode ser esquecido. Conteúdo estático apresentado sem ressalva SE
 * PASSA POR MONITORAMENTO — o gestor confiaria que seria avisado de um prazo ou
 * de um edital que ninguém está vigiando. Meia verdade apresentada como verdade
 * inteira é pior que ausência.
 *
 * ⚠️ E ele vai ANTES do conteúdo, nunca no rodapé. Quem lê o rodapé já leu a
 * tela inteira acreditando nela.
 */

import React from "react";
import { AlertTriangle } from "lucide-react";

export function AvisoCurado({ titulo, children }: {
  titulo?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="border p-2.5"
      style={{
        borderRadius: "var(--bi-radius-sm)",
        borderColor: "color-mix(in oklab, var(--bi-warn) 35%, transparent)",
        background: "color-mix(in oklab, var(--bi-warn) 8%, transparent)",
      }}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-[2px] size-3.5 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
        <div className="min-w-0 text-[10px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          <div className="text-[11px] font-semibold" style={{ color: "var(--bi-text)" }}>
            {titulo || "Conteúdo curado — esta tela não é atualizada automaticamente"}
          </div>
          <div className="mt-0.5">{children}</div>
        </div>
      </div>
    </div>
  );
}
