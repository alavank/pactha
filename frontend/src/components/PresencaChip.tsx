"use client";

// QUEM ESTÁ ONLINE AGORA — o chip do canto superior direito.
//
// ⚠️ CHIP e não barra, de propósito: a barra de cima NÃO EXISTE neste layout.
// O dashboard é um flex horizontal de dois filhos (a lateral e o `<main>`), e
// criar um `<header>` obrigaria a virar o layout em coluna, mexer no par
// `h-screen`/`overflow-hidden` e reconferir as telas largas e o modo tela cheia
// do BI. O chip entra como irmão do botão de menu do celular, sem tocar em nada
// estrutural — a barra de verdade fica para depois, se fizer falta.

import { useEffect, useState } from "react";
import { Circle } from "lucide-react";
import api from "@/lib/api";

interface Presente {
  nome: string; email: string; desde: string | null; tela: string | null;
}

/** Recalcula do instante ABSOLUTO a cada tique, nunca `segundos++`: o navegador
 *  estrangula `setInterval` em aba de fundo, e um contador incremental
 *  atrasaria minutos sem ninguém perceber. */
function haQuantoTempo(desdeIso: string | null, desvioMs: number): string {
  if (!desdeIso) return "";
  const t = Date.parse(desdeIso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.floor((Date.now() + desvioMs - t) / 1000));
  if (s < 60) return "agora mesmo";
  const min = Math.floor(s / 60);
  if (min < 60) return `${min}min ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(min / 60)}h ${String(min % 60).padStart(2, "0")}min`;
}

export default function PresencaChip({ className = "" }: { className?: string }) {
  const [lista, setLista] = useState<Presente[] | null>(null);
  const [desvio, setDesvio] = useState(0);
  const [aberto, setAberto] = useState(false);
  const [, forcar] = useState(0);

  useEffect(() => {
    let vivo = true;
    const buscar = () => {
      // Pausa com a aba escondida: consultar em segundo plano é gastar bateria
      // e CPU do servidor para atualizar algo que ninguém está vendo.
      if (document.visibilityState !== "visible") return;
      api.get<{ agora: string; online: Presente[] }>("/uso/presenca")
        .then((r) => {
          if (!vivo) return;
          setLista(r.data.online || []);
          // Corrige o relógio pelo do servidor. Sem isto, um desktop de
          // prefeitura com a hora adiantada exibiria "online há -3h" e o widget
          // perderia a credibilidade na primeira conferência.
          const t = Date.parse(r.data.agora);
          if (!Number.isNaN(t)) setDesvio(t - Date.now());
        })
        // 403 = sem a permissão `uso.ver`. O chip simplesmente não aparece, e
        // não há erro na tela: é informação de administração, não do trabalho.
        .catch(() => { if (vivo) setLista(null); });
    };
    buscar();
    const t1 = setInterval(buscar, 45_000);
    const t2 = setInterval(() => forcar((n) => n + 1), 1000);  // o segundo correndo
    return () => { vivo = false; clearInterval(t1); clearInterval(t2); };
  }, []);

  if (!lista) return null;

  // "Só você" e nunca "1 online": contar a si mesmo e anunciar como informação
  // é o painel cru que não serve para nada. Nos clientes de cidade única este
  // vai ser o estado mais frequente.
  const sozinho = lista.length <= 1;

  return (
    <div className={className}>
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium shadow-sm"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)",
                 color: sozinho ? "var(--bi-muted)" : "var(--bi-text)" }}
        title={sozinho ? "Ninguém mais no sistema agora" : "Quem está no sistema agora"}
      >
        <Circle className="size-2 shrink-0" fill={sozinho ? "var(--bi-faint)" : "var(--bi-ok)"}
                stroke="none" />
        {sozinho ? "Só você" : `${lista.length} online`}
      </button>

      {aberto && !sozinho && (
        <div className="absolute right-0 mt-1 w-64 rounded-xl p-2 shadow-lg"
             style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}>
          {lista.map((p) => (
            <div key={p.email} className="flex items-baseline justify-between gap-2 px-1.5 py-1">
              <span className="min-w-0 truncate text-[12px]" style={{ color: "var(--bi-text)" }}>
                {p.nome}
              </span>
              <span className="bi-num shrink-0 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                {haQuantoTempo(p.desde, desvio)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
