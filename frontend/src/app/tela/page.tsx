"use client";
// MODO TELA — janela separada para exibição (TV da sala do gabinete, monitor
// na recepção, projetor em reunião). Fora do layout do sistema: sem sidebar,
// sem cabeçalho do app, tela cheia de indicador.
//
// As abas são um FICHÁRIO: cada assunto é uma pasta com o nome na orelha, e o
// slideshow vira a pasta sozinho a cada 60s (o PACTHA tem informação demais
// para caber numa tela só). Play/pause/avançar/retroceder ficam aqui em cima
// E no painel de indicadores — o prefeito comanda de onde estiver.
//
// Filtro: chega pela URL na abertura e depois pelo BroadcastChannel, então
// filtrar no módulo reflete aqui na hora.
import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Maximize2, Minimize2 } from "lucide-react";
import { ABAS, AbaId, CONSOLIDADO_URL, FiltrosTela } from "@/lib/tela";
import { useTelaMotor } from "@/lib/useTela";
import { prefetchAba, useDadosAba } from "@/lib/useAbaBi";
import { ConteudoAba, EsqueletoAba } from "@/components/bi/PainelIndicadores";
import { InsightTicker } from "@/components/bi/InsightTicker";
import { SlideshowControls } from "@/components/bi/SlideshowControls";
import { TemaBi } from "@/components/bi/TemaBi";
import { Painel, Vazio } from "@/components/bi/kit";
import { rotuloPeriodo } from "@/components/bi/Filtros";

const RECARGA_MS = 5 * 60_000; // dados frescos sem martelar a API

function TelaInner() {
  const params = useSearchParams();

  // Filtros iniciais: URL (link do quiosque) -> localStorage do BI -> consolidado.
  const iniciais: FiltrosTela = useMemo(() => {
    const scopeUrl = params.get("scope");
    const anosUrl = params.get("anos");
    const scope =
      scopeUrl ||
      (typeof window !== "undefined" ? localStorage.getItem("pactha_bi_scope") : null) ||
      CONSOLIDADO_URL;
    let anos: number[] = [];
    if (anosUrl) {
      anos = anosUrl.split(",").map(Number).filter(Boolean);
    } else if (typeof window !== "undefined") {
      try {
        const raw = localStorage.getItem("pactha_bi_anos");
        if (raw) anos = (JSON.parse(raw) as number[]).map(Number).filter(Boolean);
      } catch { /* ignora json invalido */ }
    }
    return { scope, anos: anos.sort((a, b) => a - b) };
  }, [params]);

  // Token de quiosque na URL -> liga a TV sem login.
  useEffect(() => {
    const kiosk = params.get("kiosk");
    if (kiosk && typeof window !== "undefined") localStorage.setItem("pactha_token", kiosk);
  }, [params]);

  const abaUrl = params.get("aba") as AbaId | null;
  const motor = useTelaMotor({
    abaInicial: abaUrl && ABAS.some((a) => a.id === abaUrl) ? abaUrl : undefined,
    filtrosIniciais: iniciais,
  });

  const municipioId = useMemo(() => {
    const s = motor.filtros.scope;
    return s && s !== CONSOLIDADO_URL ? Number(s) || null : null;
  }, [motor.filtros.scope]);
  const anos = motor.filtros.anos;

  const { dados, carregando, erro } = useDadosAba(motor.aba, municipioId, anos, {
    recarregarMs: RECARGA_MS,
  });

  // Aquece a próxima pasta antes de virar: a troca não pode piscar esqueleto.
  useEffect(() => {
    const prox = ABAS[(ABAS.findIndex((a) => a.id === motor.aba) + 1) % ABAS.length].id;
    prefetchAba(prox, municipioId, anos);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [motor.aba, municipioId, anos.join(",")]);

  const [cheia, setCheia] = useState(false);
  const alternarTelaCheia = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
        setCheia(false);
      } else {
        await document.documentElement.requestFullscreen();
        setCheia(true);
      }
    } catch { /* navegador pode recusar sem gesto do usuario */ }
  };

  // Atalhos de teclado: quem opera a TV costuma ter só um controle na mão.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === " ") { e.preventDefault(); motor.playPause(); }
      else if (e.key === "ArrowRight") motor.next();
      else if (e.key === "ArrowLeft") motor.prev();
      else if (e.key === "f") void alternarTelaCheia();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [motor.playPause, motor.next, motor.prev]);

  const abaAtual = ABAS.find((a) => a.id === motor.aba)!;

  return (
    <div className="bi-skin flex h-screen flex-col overflow-hidden p-4">
      {/* Cabeçalho: identidade, insight da IA e o controle do slideshow */}
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2.5">
          <span
            className="grid size-9 place-items-center rounded-2xl text-[15px] font-black"
            style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
          >
            P
          </span>
          <div className="leading-tight">
            <div className="bi-title text-[17px]">Painel de Indicadores</div>
            <div className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              {abaAtual.descricao} · {rotuloPeriodo(anos)}
            </div>
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <SlideshowControls
            restante={motor.restante}
            duracao={motor.duracao}
            tocando={motor.tocando}
            onPlayPause={motor.playPause}
            onNext={motor.next}
            onPrev={motor.prev}
            legenda={`${abaAtual.curto} · ${ABAS.findIndex((a) => a.id === motor.aba) + 1}/${ABAS.length}`}
          />
          <TemaBi />
          <button
            type="button"
            onClick={alternarTelaCheia}
            title={cheia ? "Sair da tela cheia (f)" : "Tela cheia (f)"}
            aria-label={cheia ? "Sair da tela cheia" : "Tela cheia"}
            className="grid size-9 place-items-center rounded-2xl"
            style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
          >
            {cheia ? <Minimize2 className="size-4" /> : <Maximize2 className="size-4" />}
          </button>
        </div>
      </div>

      <div className="mb-3">
        <InsightTicker aba={motor.aba} municipioId={municipioId} anos={anos} tv />
      </div>

      {/* Fichário: as orelhas das pastas */}
      <div
        className="bi-folder-tabs flex items-end gap-1 border-b"
        style={{ borderColor: "var(--bi-line)" }}
        role="tablist"
      >
        {ABAS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="tab"
            aria-selected={a.id === motor.aba}
            data-active={a.id === motor.aba}
            className="bi-folder-tab text-[13px]"
            onClick={() => motor.setAba(a.id)}
          >
            {a.label}
          </button>
        ))}
      </div>

      {/* Conteúdo da pasta aberta */}
      <div
        className="flex min-h-0 flex-1 flex-col rounded-b-[var(--bi-radius)] rounded-tr-[var(--bi-radius)] p-3"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", borderTop: "none" }}
      >
        {erro ? (
          <Painel className="flex-1">
            <Vazio>{erro}</Vazio>
          </Painel>
        ) : !dados || (carregando && !dados) ? (
          <EsqueletoAba />
        ) : (
          <div key={motor.aba} className="bi-pane-enter flex min-h-0 flex-1 flex-col">
            <ConteudoAba dados={dados} tv />
          </div>
        )}
      </div>
    </div>
  );
}

export default function ModoTelaPage() {
  return (
    <Suspense
      fallback={
        <div className="bi-skin grid h-screen place-items-center text-sm">
          Carregando painel…
        </div>
      }
    >
      <TelaInner />
    </Suspense>
  );
}
