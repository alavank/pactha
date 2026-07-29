"use client";
// MODO TELA — janela separada para exibição (TV da sala do gabinete, monitor na
// recepção, projetor em reunião). Fora do layout do sistema: sem sidebar, sem
// cabeçalho do app, tela cheia de indicador.
//
// As abas são um FICHÁRIO: cada assunto é uma pasta com o nome na orelha, e o
// slideshow vira a pasta sozinho a cada 60s (o PACTHA tem informação demais
// para caber numa tela só).
//
// DE ONDE VEM O FILTRO (três caminhos, nesta ordem de precedência):
//   1. servidor  — o filtro publicado pelo DONO. É o único que atravessa
//                  aparelhos, então é o que faz o link público da TV mostrar o
//                  mesmo período que o gestor filtrou no sistema.
//   2. BroadcastChannel — instantâneo, mas só mesma origem E mesmo navegador.
//                  Serve a janela aberta pelo botão "Modo Tela" na mesma máquina.
//   3. URL/localStorage — o estado inicial, e o fallback dos links antigos
//                  (?kiosk=<jwt>&scope=...) que já estão colados em alguma TV.
//
// O mesmo componente serve /tela (logado) e /t/<slug> (link público) — a única
// diferença é de onde vem o token e se há slug para resolver.
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Maximize2, Minimize2 } from "lucide-react";
import api from "@/lib/api";
import type { User } from "@/types";
import { allowedTelasOf } from "@/lib/telas";
import { ABAS, AbaId, CONSOLIDADO_URL, FiltrosTela } from "@/lib/tela";
import { useTelaMotor } from "@/lib/useTela";
import { useFiltroTelaServidor } from "@/lib/useFiltroTela";
import { prefetchAba, useDadosAba } from "@/lib/useAbaBi";
import { Municipio, getMunicipios } from "@/lib/bi";
import { ConteudoAba, EsqueletoAba } from "@/components/bi/PainelIndicadores";
import { EnteAtendido, MarcaPactha } from "@/components/bi/Marca";
import { InsightTicker } from "@/components/bi/InsightTicker";
import { SlideshowControls } from "@/components/bi/SlideshowControls";
import { TemaBi } from "@/components/bi/TemaBi";
import { Painel, Vazio } from "@/components/bi/kit";
import { rotuloPeriodo } from "@/components/bi/Filtros";

const RECARGA_MS = 5 * 60_000; // dados frescos sem martelar a API

export function ModoTela({ slugPublico }: { slugPublico?: string }) {
  const params = useSearchParams();

  // Filtros iniciais: URL (link antigo) -> localStorage do BI -> consolidado.
  // No link público não lemos localStorage: a TV pode ter sobra de outra sessão,
  // e quem manda ali é o servidor.
  const iniciais: FiltrosTela = useMemo(() => {
    const scopeUrl = params.get("scope");
    const anosUrl = params.get("anos");
    const podeLerLocal = !slugPublico && typeof window !== "undefined";
    const scope =
      scopeUrl ||
      (podeLerLocal ? localStorage.getItem("pactha_bi_scope") : null) ||
      CONSOLIDADO_URL;
    let anos: number[] = [];
    if (anosUrl) {
      anos = anosUrl.split(",").map(Number).filter(Boolean);
    } else if (podeLerLocal) {
      try {
        const raw = localStorage.getItem("pactha_bi_anos");
        if (raw) anos = (JSON.parse(raw) as number[]).map(Number).filter(Boolean);
      } catch { /* ignora json invalido */ }
    }
    return { scope, anos: anos.sort((a, b) => a - b) };
  }, [params, slugPublico]);

  // Link ANTIGO com o token na URL. Continua funcionando de propósito: existem
  // links desse formato já colados em TV, e trocar o formato não pode apagá-los.
  useEffect(() => {
    const kiosk = params.get("kiosk");
    if (kiosk && typeof window !== "undefined") localStorage.setItem("pactha_token", kiosk);
  }, [params]);

  const abaUrl = params.get("aba") as AbaId | null;
  const motor = useTelaMotor({
    abaInicial: abaUrl && ABAS.some((a) => a.id === abaUrl) ? abaUrl : undefined,
    filtrosIniciais: iniciais,
  });

  // Permissão do Modo Tela. Esconder só o botão no painel não bastaria: a rota
  // é digitável, e aí a permissão viraria enfeite. No link público não há
  // usuário para checar — quem autoriza ali é o slug.
  const [semPermissao, setSemPermissao] = useState(false);
  useEffect(() => {
    if (slugPublico) return;
    api
      .get<User>("/auth/me")
      .then((r) => {
        const t = allowedTelasOf(r.data);
        setSemPermissao(!(!t || t.has("bi_tela"))); // t === null => admin
      })
      .catch(() => {
        /* rede caiu: não trava a TV que já estava no ar */
      });
  }, [slugPublico]);

  // O filtro do dono, vindo do servidor. É o que atravessa aparelhos.
  const servidor = useFiltroTelaServidor(slugPublico);
  const { setFiltros } = motor;
  useEffect(() => {
    if (servidor.filtros) setFiltros(servidor.filtros);
  }, [servidor.filtros, setFiltros]);

  const municipioId = useMemo(() => {
    const s = motor.filtros.scope;
    return s && s !== CONSOLIDADO_URL ? Number(s) || null : null;
  }, [motor.filtros.scope]);
  const anos = motor.filtros.anos;

  // No link público os dados só podem sair DEPOIS de resolver o slug — antes
  // disso não há token, e cada request voltaria 401.
  //
  // E se o link estiver morto, NÃO podem sair nunca: o interceptor de 401
  // (lib/api.ts) manda o navegador para /login, então uma TV com link revogado
  // exibiria uma tela de login em vez do aviso daqui a poucos metros do prefeito.
  const pronto = (!slugPublico || (servidor.pronto && !servidor.erro)) && !semPermissao;

  const { dados, carregando, erro } = useDadosAba(motor.aba, municipioId, anos, {
    pronto,
    recarregarMs: RECARGA_MS,
  });

  // Aquece a próxima pasta antes de virar: a troca não pode piscar esqueleto.
  useEffect(() => {
    if (!pronto) return;
    const prox = ABAS[(ABAS.findIndex((a) => a.id === motor.aba) + 1) % ABAS.length].id;
    prefetchAba(prox, municipioId, anos);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [motor.aba, municipioId, anos.join(","), pronto]);

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

  // Nome do ente atendido. Vem da API (é o nome real, e na assessoria muda
  // conforme o escopo); só depois de `pronto`, porque no link público o token
  // ainda não existe antes disso. Sem resposta, o <EnteAtendido> cai no nome
  // embutido no build.
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  useEffect(() => {
    if (!pronto) return;
    getMunicipios().then(setMunicipios).catch(() => {});
  }, [pronto]);
  const nomeMunicipio = useMemo(() => {
    if (!municipios.length) return null;
    const m = municipioId
      ? municipios.find((x) => x.id === municipioId)
      : municipios.length === 1
        ? municipios[0]
        : null;
    return m ? `${m.nome} — ${m.uf}` : null; // null no consolidado da assessoria
  }, [municipios, municipioId]);

  const abaAtual = ABAS.find((a) => a.id === motor.aba)!;

  if (semPermissao) {
    return (
      <div className="bi-skin grid h-screen place-items-center p-8">
        <div className="text-center">
          <div className="bi-title text-[20px]">Sem acesso ao Modo Tela</div>
          <div className="mt-2 text-[13px]" style={{ color: "var(--bi-faint)" }}>
            Peça a um administrador a permissão “Modo Tela (TV) do BI”.
          </div>
        </div>
      </div>
    );
  }

  // Link morto tem que dizer que morreu. Deixar o último painel no ar seria
  // pior que a tela em branco: vira dado velho passando por atual.
  if (servidor.erro) {
    return (
      <div className="bi-skin grid h-screen place-items-center p-8">
        <div className="text-center">
          <div className="bi-title text-[20px]">Painel indisponível</div>
          <div className="mt-2 text-[13px]" style={{ color: "var(--bi-faint)" }}>
            {servidor.erro}
          </div>
          <div className="mt-1 text-[12px]" style={{ color: "var(--bi-faint)" }}>
            Peça um link novo a quem publicou esta tela.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bi-skin flex h-screen flex-col overflow-hidden p-4">
      {/* Cabeçalho em três colunas: quem é o ente (esquerda), de quem é o
          produto (centro) e os controles (direita). A do meio fica centrada na
          TELA, não no espaço que sobra — por isso as laterais são flex-1. */}
      <div className="mb-3 flex items-center gap-3">
        <div className="flex min-w-0 flex-1 flex-col">
          <EnteAtendido nome={nomeMunicipio} />
          <span className="mt-0.5 truncate text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {abaAtual.descricao} · {rotuloPeriodo(anos)}
          </span>
        </div>

        <MarcaPactha className="shrink-0" />

        <div className="flex flex-1 items-center justify-end gap-2">
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
        {/* Também preso ao `pronto`: o ticker busca no mount, e no link público
            o mount acontece ANTES do slug virar token. Sem esta guarda ele
            dispara /bi/insights sem credencial, toma 401, e o interceptor de
            api.ts manda a TV para /login — a tela pública nunca chegaria a
            aparecer. */}
        {pronto && <InsightTicker aba={motor.aba} municipioId={municipioId} anos={anos} tv />}
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
