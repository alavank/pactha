"use client";
// Dois hooks, um de cada lado do BroadcastChannel do Modo Tela:
//
//   useTelaMotor()    -> roda DENTRO da janela da tela. E o dono do relogio:
//                        avanca as abas, publica `state` e obedece `cmd`.
//   useTelaControle() -> roda no painel de indicadores. So escuta `state`,
//                        interpola o cronometro entre uma publicacao e outra e
//                        manda `cmd`. Se parar de receber `state`, some.
//
// Interpolar no lado do controle e o que faz a rosca girar liso mesmo com o
// `state` chegando a cada 500 ms (mandar 60 mensagens por segundo seria besteira).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ABAS,
  AbaId,
  DURACAO_PADRAO_MS,
  FiltrosTela,
  TELA_TIMEOUT_MS,
  TelaMsg,
  TelaState,
  abaIndex,
  abrirCanal,
} from "./tela";

const TICK_MS = 100;
const PUBLICA_MS = 500;

// --------------------------------------------------------------------------
// Dentro da janela da tela
// --------------------------------------------------------------------------

export function useTelaMotor(opts: {
  abaInicial?: AbaId;
  filtrosIniciais: FiltrosTela;
  duracao?: number;
}) {
  const duracao = opts.duracao ?? DURACAO_PADRAO_MS;
  const [aba, setAba] = useState<AbaId>(opts.abaInicial ?? ABAS[0].id);
  const [tocando, setTocando] = useState(true);
  const [restante, setRestante] = useState(duracao);
  const [filtros, setFiltros] = useState<FiltrosTela>(opts.filtrosIniciais);
  const canalRef = useRef<BroadcastChannel | null>(null);

  const irPara = useCallback((id: AbaId) => {
    setAba(id);
    setRestante(duracao);
  }, [duracao]);

  const avancar = useCallback((passo: number) => {
    setAba((atual) => ABAS[(abaIndex(atual) + passo + ABAS.length) % ABAS.length].id);
    setRestante(duracao);
  }, [duracao]);

  // Cronometro: so decrementa quando esta tocando; ao zerar, vira a aba.
  useEffect(() => {
    if (!tocando) return;
    const id = setInterval(() => {
      setRestante((r) => {
        if (r - TICK_MS > 0) return r - TICK_MS;
        setAba((atual) => ABAS[(abaIndex(atual) + 1) % ABAS.length].id);
        return duracao;
      });
    }, TICK_MS);
    return () => clearInterval(id);
  }, [tocando, duracao]);

  // Canal: recebe comandos do painel e os filtros; anuncia entrada e saida.
  useEffect(() => {
    const canal = abrirCanal();
    canalRef.current = canal;
    if (!canal) return;
    canal.onmessage = (ev: MessageEvent<TelaMsg>) => {
      const m = ev.data;
      if (!m || typeof m !== "object") return;
      if (m.type === "cmd") {
        if (m.acao === "play") setTocando(true);
        else if (m.acao === "pause") setTocando(false);
        else if (m.acao === "toggle") setTocando((t) => !t);
        else if (m.acao === "next") avancar(1);
        else if (m.acao === "prev") avancar(-1);
        else if (m.acao === "goto") irPara(m.aba);
      } else if (m.type === "filtros") {
        setFiltros(m.filtros);
      }
    };
    canal.postMessage({ type: "ola" } satisfies TelaMsg);
    const sair = () => {
      try {
        canal.postMessage({ type: "tchau" } satisfies TelaMsg);
      } catch { /* janela ja indo embora */ }
    };
    window.addEventListener("pagehide", sair);
    return () => {
      sair();
      window.removeEventListener("pagehide", sair);
      canal.close();
      canalRef.current = null;
    };
  }, [avancar, irPara]);

  // Publica o estado para o painel desenhar a rosca dele.
  useEffect(() => {
    const publicar = () => {
      canalRef.current?.postMessage({
        type: "state",
        aba,
        indice: abaIndex(aba),
        total: ABAS.length,
        restante,
        duracao,
        tocando,
        em: Date.now(),
      } satisfies TelaState);
    };
    publicar();
    const id = setInterval(publicar, PUBLICA_MS);
    return () => clearInterval(id);
  }, [aba, restante, duracao, tocando]);

  return {
    aba,
    setAba: irPara,
    tocando,
    setTocando,
    restante,
    duracao,
    filtros,
    playPause: () => setTocando((t) => !t),
    next: () => avancar(1),
    prev: () => avancar(-1),
  };
}

// --------------------------------------------------------------------------
// No painel de indicadores
// --------------------------------------------------------------------------

export interface TelaControle {
  /** true enquanto chega `state` da janela (i.e. a tela esta aberta). */
  ativa: boolean;
  aba: AbaId | null;
  indice: number;
  total: number;
  restante: number;
  duracao: number;
  tocando: boolean;
  playPause: () => void;
  next: () => void;
  prev: () => void;
  irPara: (aba: AbaId) => void;
  /** Empurra o filtro atual para a tela (chamado quando o filtro muda). */
  enviarFiltros: (f: FiltrosTela) => void;
}

export function useTelaControle(filtros: FiltrosTela): TelaControle {
  const [state, setState] = useState<TelaState | null>(null);
  const [agora, setAgora] = useState(() => Date.now());
  const canalRef = useRef<BroadcastChannel | null>(null);
  // O handler do canal e registrado UMA vez, mas precisa enxergar o filtro mais
  // recente quando a tela pedir (`ola`). Guardamos num ref sincronizado por
  // efeito — escrever no ref durante o render quebraria o modelo do React.
  const filtrosRef = useRef(filtros);
  useEffect(() => {
    filtrosRef.current = filtros;
  }, [filtros]);

  useEffect(() => {
    const canal = abrirCanal();
    canalRef.current = canal;
    if (!canal) return;
    canal.onmessage = (ev: MessageEvent<TelaMsg>) => {
      const m = ev.data;
      if (!m || typeof m !== "object") return;
      if (m.type === "state") setState(m);
      else if (m.type === "tchau") setState(null);
      // A tela acabou de abrir -> manda o filtro vigente (ela pode ter sido
      // aberta por um link antigo, ou o filtro mudou depois do window.open).
      else if (m.type === "ola") {
        canal.postMessage({ type: "filtros", filtros: filtrosRef.current } satisfies TelaMsg);
      }
    };
    return () => {
      canal.close();
      canalRef.current = null;
    };
  }, []);

  // Relogio local: gira a rosca entre um `state` e o proximo, e detecta a
  // janela que sumiu sem avisar (fechada no X, crash, outra aba).
  useEffect(() => {
    const id = setInterval(() => setAgora(Date.now()), TICK_MS);
    return () => clearInterval(id);
  }, []);

  const enviar = useCallback((msg: TelaMsg) => {
    canalRef.current?.postMessage(msg);
  }, []);

  const viva = !!state && agora - state.em < TELA_TIMEOUT_MS;
  const restante = useMemo(() => {
    if (!state) return 0;
    if (!state.tocando) return state.restante;
    return Math.max(0, state.restante - (agora - state.em));
  }, [state, agora]);

  return {
    ativa: viva,
    aba: viva ? state!.aba : null,
    indice: viva ? state!.indice : 0,
    total: viva ? state!.total : ABAS.length,
    restante,
    duracao: state?.duracao ?? DURACAO_PADRAO_MS,
    tocando: viva ? state!.tocando : false,
    playPause: () => enviar({ type: "cmd", acao: "toggle" }),
    next: () => enviar({ type: "cmd", acao: "next" }),
    prev: () => enviar({ type: "cmd", acao: "prev" }),
    irPara: (aba: AbaId) => enviar({ type: "cmd", acao: "goto", aba }),
    enviarFiltros: (f: FiltrosTela) => enviar({ type: "filtros", filtros: f }),
  };
}
