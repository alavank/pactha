"use client";

// QUEM ESTÁ NO SISTEMA AGORA — os cartões do topo da Telemetria.
//
// ⚠️ Vive SÓ nesta tela. A primeira versão era um chip fixo no canto superior
// direito de todas as telas, e o dono cortou na hora: informação de
// administração não pode acompanhar quem está trabalhando, tela após tela.
// Aqui ela fica onde alguém foi PROCURAR por ela.

import { useEffect, useState } from "react";
import api from "@/lib/api";

interface Presente {
  nome: string; email: string; desde: string | null;
  tela: string | null; estado: "presente" | "saindo"; ha_seg: number;
}

/** A PALETA. Tons do próprio tema, não cor de festa: o cartão é fundo suave com
 *  texto escuro da mesma família, então seis pessoas na tela continuam legíveis
 *  e nenhuma grita mais que a outra. */
const PALETA = [
  { fundo: "color-mix(in oklab, var(--bi-accent) 14%, transparent)", tinta: "var(--bi-accent-ink)" },
  { fundo: "color-mix(in oklab, var(--bi-ok) 14%, transparent)",     tinta: "var(--bi-ok-ink)" },
  { fundo: "color-mix(in oklab, var(--bi-warn) 14%, transparent)",   tinta: "var(--bi-warn-ink)" },
  { fundo: "color-mix(in oklab, #6366f1 14%, transparent)",          tinta: "#4f46e5" },
  { fundo: "color-mix(in oklab, #d946ef 12%, transparent)",          tinta: "#a21caf" },
  { fundo: "color-mix(in oklab, #0891b2 14%, transparent)",          tinta: "#0e7490" },
];

/** O deslocamento é sorteado UMA vez por montagem da tela, e as cores são
 *  distribuídas por POSIÇÃO na lista — nunca por pessoa.
 *
 *  É o que o dono pediu e faz sentido: cor amarrada ao usuário viraria um código
 *  que a equipe decora ("o roxo é o fulano"), e isso é identificação por outro
 *  meio. Assim, a mesma pessoa é âmbar hoje e azul amanhã, e duas pessoas
 *  simultâneas nunca compartilham a cor porque as posições são distintas. */
function usarDeslocamento(): number {
  const [d] = useState(() => Math.floor(Math.random() * PALETA.length));
  return d;
}

/** Recalcula do instante ABSOLUTO a cada tique, nunca `segundos++`: o navegador
 *  estrangula `setInterval` em aba de fundo e um contador incremental atrasaria
 *  minutos sem ninguém perceber. */
function relogio(desdeIso: string | null, desvioMs: number): string {
  if (!desdeIso) return "--:--:--";
  const t = Date.parse(desdeIso);
  if (Number.isNaN(t)) return "--:--:--";
  const s = Math.max(0, Math.floor((Date.now() + desvioMs - t) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

/** VERDE presente · ÂMBAR ocioso há mais de 30s · VERMELHO saindo.
 *  O ocioso é decidido AQUI, com `ha_seg` que veio do servidor — o relógio da
 *  máquina de quem está olhando não entra na conta. */
function sinal(p: Presente): { cor: string; pulsa: boolean; texto: string } {
  if (p.estado === "saindo") return { cor: "var(--bi-crit)", pulsa: false, texto: "saiu agora" };
  if (p.ha_seg > 30) return { cor: "var(--bi-warn)", pulsa: false, texto: "parado" };
  return { cor: "var(--bi-ok)", pulsa: true, texto: "ativo" };
}

export default function PresencaAgora() {
  const [lista, setLista] = useState<Presente[] | null>(null);
  const [desvio, setDesvio] = useState(0);
  const [, tique] = useState(0);
  const desloc = usarDeslocamento();

  useEffect(() => {
    let vivo = true;
    const buscar = () => {
      if (document.visibilityState !== "visible") return;
      api.get<{ agora: string; online: Presente[] }>("/uso/presenca")
        .then((r) => {
          if (!vivo) return;
          setLista(r.data.online || []);
          const t = Date.parse(r.data.agora);
          if (!Number.isNaN(t)) setDesvio(t - Date.now());
        })
        .catch(() => { if (vivo) setLista([]); });
    };
    buscar();
    // 15s: aqui a pessoa ESTÁ olhando o painel, então vale a pena ser mais
    // vivo que os 45s do envio de eventos — e ainda assim são 4 requisições
    // por minuto de uma tela que quase ninguém abre.
    const t1 = setInterval(buscar, 15_000);
    const t2 = setInterval(() => tique((n) => n + 1), 1000);
    return () => { vivo = false; clearInterval(t1); clearInterval(t2); };
  }, []);

  if (!lista) return null;

  return (
    <div className="rounded-2xl p-3" style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}>
      <div className="mb-2 flex items-baseline gap-2">
        <span className="bi-title text-[14px]">No sistema agora</span>
        <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
          {lista.length === 0
            ? "ninguém, nem você — a sessão começa a contar no próximo login"
            : `${lista.length} sessão(ões) · o contador é o tempo desde que entrou`}
        </span>
      </div>

      {lista.length === 0 ? null : (
        <div className="flex flex-wrap gap-2">
          {lista.map((p, i) => {
            const c = PALETA[(i + desloc) % PALETA.length];
            const s = sinal(p);
            return (
              <div key={p.email + p.desde}
                   className="flex items-center gap-2.5 rounded-xl px-3 py-2"
                   style={{ background: c.fundo }}
                   title={`${p.nome} · ${s.texto}${p.tela ? ` · em ${p.tela}` : ""}`}>
                <span className="relative flex size-2.5 shrink-0">
                  {/* O pulso só existe quando a pessoa está de fato ativa: um
                      ponto piscando ao lado de quem parou seria mentira em
                      movimento, que é a pior espécie. */}
                  {s.pulsa && (
                    <span className="absolute inline-flex size-full animate-ping rounded-full opacity-60"
                          style={{ background: s.cor }} />
                  )}
                  <span className="relative inline-flex size-2.5 rounded-full" style={{ background: s.cor }} />
                </span>
                <span className="text-[13px] font-medium" style={{ color: c.tinta }}>{p.nome}</span>
                <span className="bi-num text-[12px] tabular-nums" style={{ color: c.tinta, opacity: 0.75 }}>
                  {relogio(p.desde, desvio)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
