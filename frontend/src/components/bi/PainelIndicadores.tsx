"use client";
// PAINEL DE INDICADORES — o "Dashboard" quando o modulo BI esta ligado.
//
// Antes eram DOIS menus (Dashboard operacional + Painel de Indicadores) para o
// mesmo publico. Agora e um so: este componente e o conteudo de /dashboard.
// As seis abas sao AS MESMAS do Modo Tela (lib/tela.ts) e usam OS MESMOS
// componentes de aba (components/bi/abas.tsx) — o que o gestor ve aqui e o que
// vai aparecer na TV, sem duas verdades para manter.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { MonitorPlay, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { Municipio, getMunicipios, putTelaFiltros } from "@/lib/bi";
import type { User } from "@/types";
import { allowedTelasOf } from "@/lib/telas";
import { useBiScope, CONSOLIDADO } from "@/contexts/BiScopeContext";
import { ABAS, AbaId, FiltrosTela, abrirJanelaDaTela } from "@/lib/tela";
import { useTelaControle } from "@/lib/useTela";
import { prefetchAba, useDadosAba } from "@/lib/useAbaBi";
import { EscopoSelect, PeriodoMultiSelect, rotuloPeriodo } from "./Filtros";
import { CabecalhoBi } from "./Marca";
import { BotaoAjustes } from "./Ajustes";
import { TemaBi } from "./TemaBi";
import { InsightTicker } from "./InsightTicker";
import { SlideshowControls } from "./SlideshowControls";
import { Painel, Skeleton, Vazio } from "./kit";
import {
  AbaDocumentosView, AbaEstaduaisView, AbaFnsView, AbaGeral,
  AbaParlamentaresView, AbaTransfereGovView,
} from "./abas";

export function PainelIndicadores() {
  const router = useRouter();
  const params = useSearchParams();
  const { scope, setScope, municipioId, anos } = useBiScope();
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  const [user, setUser] = useState<User | null>(null);

  const abaUrl = params.get("aba") as AbaId | null;
  const [aba, setAbaState] = useState<AbaId>(
    abaUrl && ABAS.some((a) => a.id === abaUrl) ? abaUrl : "geral"
  );

  const filtros: FiltrosTela = useMemo(
    () => ({ scope: scope || CONSOLIDADO, anos }),
    [scope, anos]
  );
  const tela = useTelaControle(filtros);

  // Mudou o filtro -> a TV muda junto (o prefeito filtra aqui e olha pra la).
  // Caminho INSTANTANEO, mas so alcanca a janela do MESMO navegador.
  useEffect(() => {
    if (tela.ativa) tela.enviarFiltros(filtros);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtros, tela.ativa]);

  useEffect(() => {
    api.get<User>("/auth/me").then((r) => setUser(r.data)).catch(() => {});
    getMunicipios().then(setMunicipios).catch(() => {});
  }, []);

  // Consolidado só faz sentido para quem tem CARTEIRA (assessoria/parceiro com
  // vários municípios). Antes bastava ser admin, e por isso o ambiente de um
  // município único — que nunca terá outra cidade para comparar — exibia o
  // seletor com uma opção "Consolidado (todos)" que consolidava um só.
  const podeConsolidado = useMemo(() => municipios.length > 1, [municipios.length]);

  const nomeMunicipio = useMemo(() => {
    const m = municipioId
      ? municipios.find((x) => x.id === municipioId)
      : municipios.length === 1
        ? municipios[0]
        : null;
    return m ? `${m.nome} — ${m.uf}` : null; // null = consolidado da assessoria
  }, [municipios, municipioId]);

  // Valida o escopo assim que a lista chega (id obsoleto no localStorage etc.)
  useEffect(() => {
    if (!municipios.length) return;
    if (scope === CONSOLIDADO) {
      if (!podeConsolidado) setScope(String(municipios[0].id));
      return;
    }
    const valido = scope && municipios.some((m) => String(m.id) === scope);
    if (!valido) setScope(podeConsolidado ? CONSOLIDADO : String(municipios[0].id));
  }, [municipios, scope, podeConsolidado, setScope]);

  const setAba = useCallback(
    (id: AbaId) => {
      setAbaState(id);
      const p = new URLSearchParams(Array.from(params.entries()));
      p.set("aba", id);
      router.replace(`?${p.toString()}`, { scroll: false });
    },
    [params, router]
  );

  // A TV virou de aba -> o modulo acompanha, para os dois estarem no mesmo
  // assunto. A origem e externa (BroadcastChannel da outra janela), entao o
  // setState aqui e sincronizacao com sistema externo, nao render em cascata.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (tela.ativa && tela.aba && tela.aba !== aba) setAbaState(tela.aba);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tela.aba, tela.ativa]);

  const pronto = !!scope;
  const { dados, carregando, erro, recarregar } = useDadosAba(aba, municipioId, anos, { pronto });

  // Aquece a proxima aba: trocar deve ser instantaneo.
  useEffect(() => {
    if (!pronto) return;
    const prox = ABAS[(ABAS.findIndex((a) => a.id === aba) + 1) % ABAS.length].id;
    prefetchAba(prox, municipioId, anos);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aba, municipioId, anos.join(","), pronto]);

  // ...e o caminho que atravessa APARELHOS: publica o filtro no servidor, de
  // onde a TV e o link publico leem. Sem isto, "mudei o periodo no sistema" nao
  // chega na TV do gabinete, que e outra maquina. Debounce porque o
  // multi-select de anos dispara varias mudancas seguidas enquanto se clica.
  useEffect(() => {
    if (!pronto) return;
    const id = setTimeout(() => {
      void putTelaFiltros({ scope: filtros.scope, anos: filtros.anos, aba }).catch(() => {});
    }, 600);
    return () => clearTimeout(id);
  }, [filtros, aba, pronto]);

  const telasPermitidas = useMemo(() => allowedTelasOf(user), [user]);
  // null = admin (ou ainda carregando): nao esconde nada.
  const podeModoTela = !telasPermitidas || telasPermitidas.has("bi_tela");

  const abrirTela = () => abrirJanelaDaTela(filtros);

  return (
    <div className="bi-skin min-h-full px-4 py-5 sm:px-6 lg:px-8">
      <CabecalhoBi
        nomeMunicipio={nomeMunicipio}
        legenda={`Gestão à vista · ${rotuloPeriodo(anos)}`}
        right={
          <>
            {/* O seletor só existe para quem TEM carteira: assessoria com vários
                municípios. Num ambiente de município único não há o que
                escolher, e o dropdown só sugeria que existe dado de outra
                cidade ali dentro. */}
            {podeConsolidado && (
              <EscopoSelect municipios={municipios} podeConsolidado={podeConsolidado} />
            )}
            <PeriodoMultiSelect />
            <TemaBi />
            <button
              type="button"
              onClick={recarregar}
              title="Atualizar dados"
              aria-label="Atualizar dados"
              className="grid size-9 place-items-center rounded-full"
              style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
            >
              <RefreshCw className={carregando ? "size-4 animate-spin" : "size-4"} />
            </button>
            <BotaoAjustes />
            {podeModoTela && (
              <button
                type="button"
                onClick={abrirTela}
                className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold"
                style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
              >
                <MonitorPlay className="size-4" />
                Modo Tela
              </button>
            )}
            {tela.ativa && (
              <SlideshowControls
                compacto
                restante={tela.restante}
                duracao={tela.duracao}
                tocando={tela.tocando}
                onPlayPause={tela.playPause}
                onNext={tela.next}
                onPrev={tela.prev}
                legenda={`${ABAS[tela.indice]?.curto ?? ""} · ${tela.indice + 1}/${tela.total}`}
              />
            )}
          </>
        }
      />

      <div className="mb-4">
        <InsightTicker aba={aba} municipioId={municipioId} anos={anos} />
      </div>

      {/* Abas por assunto — as mesmas do Modo Tela */}
      <div
        className="bi-folder-tabs mb-4 flex flex-wrap items-end gap-1 border-b"
        style={{ borderColor: "var(--bi-line)" }}
        role="tablist"
      >
        {ABAS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="tab"
            aria-selected={a.id === aba}
            data-active={a.id === aba}
            className="bi-folder-tab text-[13px]"
            onClick={() => {
              setAba(a.id);
              if (tela.ativa) tela.irPara(a.id);
            }}
            title={a.descricao}
          >
            {a.label}
          </button>
        ))}
      </div>

      {erro ? (
        <Painel>
          <Vazio>{erro}</Vazio>
        </Painel>
      ) : !dados || (carregando && !dados) ? (
        <EsqueletoAba />
      ) : (
        <div key={aba} className="bi-pane-enter flex flex-col">
          <ConteudoAba dados={dados} />
        </div>
      )}
    </div>
  );
}

export function ConteudoAba({
  dados,
  tv,
}: {
  dados: NonNullable<ReturnType<typeof useDadosAba>["dados"]>;
  tv?: boolean;
}) {
  switch (dados.aba) {
    case "geral":
      return <AbaGeral ov={dados.d.ov} alertas={dados.d.alertas} tv={tv} />;
    case "parlamentares":
      return <AbaParlamentaresView d={dados.d} tv={tv} />;
    case "transferegov":
      return <AbaTransfereGovView d={dados.d} tv={tv} />;
    case "estaduais":
      return <AbaEstaduaisView d={dados.d} tv={tv} />;
    case "documentos":
      return <AbaDocumentosView d={dados.d} tv={tv} />;
    case "fns":
      return <AbaFnsView d={dados.d} tv={tv} />;
  }
}

export function EsqueletoAba() {
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-56" />
        ))}
      </div>
    </div>
  );
}
