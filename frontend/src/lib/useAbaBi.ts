"use client";
// Carregamento dos dados de uma aba do BI, com cache curto em memoria.
//
// Por que cache: o Modo Tela roda em loop pelas sete abas. Sem cache, cada volta
// refaria os seis requests; com ele, o payload da aba fica valido por ~40 s (na
// mesma ordem do TTL do backend) e a volta seguinte reaproveita. `prefetchAba`
// deixa a proxima aba pronta ANTES de virar, para a troca nao mostrar esqueleto.
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AbaDocumentos, AbaEstaduais, AbaFns, AbaParlamentares, AbaSismob, AbaTransfereGov,
  Alertas, Overview, getAbaDocumentos, getAbaEstaduais, getAbaFns,
  getAbaParlamentares, getAbaSismob, getAbaTransfereGov, getAlertas, getOverview,
} from "./bi";
import { AbaId } from "./tela";

export interface DadosGeral {
  ov: Overview;
  alertas: Alertas | null;
}

export type DadosAba =
  | { aba: "geral"; d: DadosGeral }
  | { aba: "parlamentares"; d: AbaParlamentares }
  | { aba: "transferegov"; d: AbaTransfereGov }
  | { aba: "estaduais"; d: AbaEstaduais }
  | { aba: "documentos"; d: AbaDocumentos }
  | { aba: "fns"; d: AbaFns }
  | { aba: "sismob"; d: AbaSismob };

const TTL_MS = 40_000;
const cache = new Map<string, { em: number; dados: DadosAba }>();

function chave(aba: AbaId, municipioId: number | null, anos: number[]) {
  return `${aba}|${municipioId ?? "all"}|${anos.join(",")}`;
}

async function carregar(aba: AbaId, municipioId: number | null, anos: number[]): Promise<DadosAba> {
  switch (aba) {
    case "parlamentares":
      return { aba, d: await getAbaParlamentares(municipioId, anos) };
    case "transferegov":
      return { aba, d: await getAbaTransfereGov(municipioId, anos) };
    case "estaduais":
      return { aba, d: await getAbaEstaduais(municipioId, anos) };
    case "documentos":
      return { aba, d: await getAbaDocumentos(municipioId) };
    case "fns":
      return { aba, d: await getAbaFns(municipioId, anos) };
    case "sismob":
      return { aba, d: await getAbaSismob(municipioId, anos) };
    default: {
      // A visao geral precisa dos alertas junto (vencimento / prestacao de
      // contas), mas um erro nos alertas nao pode derrubar a aba inteira.
      const ov = await getOverview(municipioId, anos);
      const alertas = await getAlertas(municipioId, anos).catch(() => null);
      return { aba: "geral", d: { ov, alertas } };
    }
  }
}

/** Busca (ou reaproveita do cache) os dados de uma aba. */
export async function buscarAba(
  aba: AbaId,
  municipioId: number | null,
  anos: number[],
  forcar = false
): Promise<DadosAba> {
  const k = chave(aba, municipioId, anos);
  const hit = cache.get(k);
  if (!forcar && hit && Date.now() - hit.em < TTL_MS) return hit.dados;
  const dados = await carregar(aba, municipioId, anos);
  cache.set(k, { em: Date.now(), dados });
  return dados;
}

/** Aquece o cache sem renderizar nada (a proxima aba do slideshow). */
export function prefetchAba(aba: AbaId, municipioId: number | null, anos: number[]) {
  const k = chave(aba, municipioId, anos);
  const hit = cache.get(k);
  if (hit && Date.now() - hit.em < TTL_MS) return;
  void buscarAba(aba, municipioId, anos).catch(() => {});
}

export function invalidarAbas() {
  cache.clear();
}

export function useDadosAba(
  aba: AbaId,
  municipioId: number | null,
  anos: number[],
  opts: { pronto?: boolean; recarregarMs?: number } = {}
) {
  const { pronto = true, recarregarMs } = opts;
  const [dados, setDados] = useState<DadosAba | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const reqRef = useRef(0);
  // `anos` chega como array novo a cada render; a chave estavel evita refazer
  // o efeito sem que o periodo tenha mudado de fato.
  const anosKey = anos.join(",");

  const buscar = useCallback(
    async (forcar: boolean) => {
      const req = ++reqRef.current;
      setErro(null);
      // So mostra esqueleto quando ainda nao ha nada em cache para esta aba —
      // trocar de aba com dado quente deve ser instantaneo.
      const k = chave(aba, municipioId, anos);
      const quente = cache.get(k);
      if (!quente) setCarregando(true);
      else setDados(quente.dados);
      try {
        const d = await buscarAba(aba, municipioId, anos, forcar);
        if (req === reqRef.current) {
          setDados(d);
          setCarregando(false);
        }
      } catch {
        if (req === reqRef.current) {
          setErro("Não foi possível carregar esta aba.");
          setCarregando(false);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [aba, municipioId, anosKey]
  );

  useEffect(() => {
    if (!pronto) return;
    // Busca de dados: o setState sincrono aqui e o "carregando" da primeira
    // pintura, nao um loop de render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void buscar(false);
  }, [buscar, pronto]);

  useEffect(() => {
    if (!pronto || !recarregarMs) return;
    const id = setInterval(() => void buscar(true), recarregarMs);
    return () => clearInterval(id);
  }, [buscar, pronto, recarregarMs]);

  return { dados, carregando, erro, recarregar: () => buscar(true) };
}
