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
  /** A aba se despediu (fato do servidor). Diferente de "parou de dar sinal". */
  encerrada?: boolean;
  /** Índice da cor, vindo do SERVIDOR e derivado do id da sessão: estável
   *  enquanto a pessoa estiver logada, novo quando ela sai e volta. */
  cor: number;
  sou_eu: boolean;
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

/* A COR VEM DO SERVIDOR, derivada do id da sessão.
 *
 *  A primeira versão sorteava no cliente a cada montagem da tela — e aí a cor de
 *  uma pessoa mudava toda vez que quem estava olhando atualizava a página, o que
 *  torna a cor inútil como referência ("quem era o azul mesmo?").
 *
 *  Agora ela é da SESSÃO: fixa enquanto a pessoa estiver logada, e diferente
 *  quando ela sair e voltar. Continua não sendo por usuário — cor amarrada à
 *  pessoa viraria um código que a equipe decora, e isso é identificar por outro
 *  meio. */

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
  // ⚠️ VOCÊ NÃO FICA VERMELHO POR SILÊNCIO. Se você está lendo esta tela, você
  // está no sistema — um ponto vermelho no próprio nome é o widget contradizendo
  // o que a pessoa vê com os próprios olhos. A EXCEÇÃO é a sessão que se
  // DESPEDIU (`encerrada`): aí é outra aba/sessão sua que fechou, e ela tem que
  // aparecer vermelha e sumir — o dono viu a própria sessão encerrada ao lado
  // da nova, as duas verdes, e leu que o sistema "segurava" a anterior.
  if (p.estado === "saindo" && (p.encerrada || !p.sou_eu))
    return { cor: "var(--bi-crit)", pulsa: false, texto: "saiu agora" };
  // Âmbar TAMBÉM pulsa, mais devagar: parado não é ausente, e o pulso é o que
  // diz "a sessão está viva". Quem parou de dar sinal é que fica estático.
  if (p.ha_seg > 30) return { cor: "var(--bi-warn)", pulsa: true, texto: "parado" };
  return { cor: "var(--bi-ok)", pulsa: true, texto: "ativo" };
}

export default function PresencaAgora() {
  const [lista, setLista] = useState<Presente[] | null>(null);
  const [desvio, setDesvio] = useState(0);
  const [, tique] = useState(0);

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
    // 8s: aqui a pessoa ESTÁ olhando o painel esperando ver movimento, então
    // vale ser bem mais vivo que os 45s do envio de eventos. São ~7 requisições
    // por minuto de uma tela que quase ninguém abre — barato.
    // ⚠️ O limite de "tempo real" NÃO é este intervalo: uma sessão nova só
    // existe depois do primeiro envio do outro navegador, que sai em até 45s.
    // Encurtar mais aqui não faz o colega aparecer antes.
    const t1 = setInterval(buscar, 8_000);
    const t2 = setInterval(() => tique((n) => n + 1), 1000);
    return () => { vivo = false; clearInterval(t1); clearInterval(t2); };
  }, []);

  if (!lista) return null;

  return (
    <div className="rounded-2xl p-3" style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}>
      <div className="mb-2 flex items-baseline gap-2">
        <span className="bi-title text-[14px]">Online no Sistema</span>
        <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
          {lista.length === 0
            ? "ninguém, nem você — a sessão começa a contar no próximo login"
            : `${lista.length} pessoa(s) · o contador é o tempo desde que entrou nesta sessão`}
        </span>
      </div>

      {lista.length === 0 ? null : (
        <div className="flex flex-wrap gap-2">
          {lista.map((p, i) => {
            const c = PALETA[(p.cor ?? i) % PALETA.length];
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
