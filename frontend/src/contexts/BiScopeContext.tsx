"use client";
// Periodo do Painel de Indicadores (BI) — e SÓ o período.
//
// ⚠️ O ESCOPO DEIXOU DE MORAR AQUI. Ele era independente do MunicipioContext e
// persistia numa chave PRÓPRIA (`pactha_bi_scope`), com um seletor próprio no
// cabeçalho do Painel. Numa assessoria isso produzia dois seletores de município
// visíveis ao mesmo tempo, apontando para CIDADES DIFERENTES: a pessoa trocava o
// município no menu, a barra lateral passava a dizer B, e o painel inteiro
// continuava mostrando A — sem piscar, sem aviso. Como os municípios de uma
// carteira são clientes diferentes, isso é confundir dado de cliente.
//
// Agora o escopo vem do `MunicipioContext`, que é o seletor único do sistema, e
// este contexto cuida apenas do período.
//
// PERIODO E MULTI-ANO: um prefeito filtra o MANDATO (ex.: 2021-2024), nao um
// ano. `anos` e a fonte da verdade; `ano` continua exposto so para as telas
// antigas que ainda mandam um valor unico.
import { createContext, useContext, useState, useCallback, ReactNode, useMemo } from "react";
import { CONSOLIDADO, useMunicipio } from "./MunicipioContext";

/** Reexportado para as telas que já importavam daqui — a definição mora no
 *  `MunicipioContext`, junto do seletor que manda nele. */
export { CONSOLIDADO };

const K_ANOS = "pactha_bi_anos";
const K_ANO_LEGADO = "pactha_bi_ano";

interface BiScope {
  /** Espelho do seletor único: `"__all__"` | `"<municipioId>"` | `""`. */
  scope: string;
  municipioId: number | null; // null quando consolidado ou vazio
  isConsolidado: boolean;
  /** Anos selecionados (vazio = todos os anos). */
  anos: number[];
  setAnos: (a: number[]) => void;
  alternarAno: (a: number) => void;
  /** Compat: primeiro ano quando ha exatamente um selecionado. */
  ano: number | undefined;
  setAno: (a: number | undefined) => void;
}

const Ctx = createContext<BiScope | null>(null);

/* ⭐ NA PRIMEIRA VISITA, O ANO CORRENTE (pedido do dono, 04/09/2026). O Painel
   é a tela que abre o sistema; abri-lo somando uma década joga um número
   absurdo na cara de quem chegou, e a leitura vira "isto aqui é grande demais
   para eu entender". O ano em que se está é o recorte que quase sempre se quer.

   ⚠️ E "TODOS OS ANOS" CONTINUA SENDO UMA ESCOLHA POSSÍVEL — por isso a chave
   passa a guardar `[]` em vez de ser APAGADA quando o usuário limpa o período.
   Sem essa distinção, "escolhi ver tudo" e "nunca escolhi nada" ficariam
   indistinguíveis no localStorage, e o padrão desfaria a escolha da pessoa toda
   vez que ela voltasse. Chave ausente = primeira visita; `[]` gravado = ela
   pediu tudo. */
function lerAnosIniciais(): number[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(K_ANOS);
    if (raw) {
      const arr = JSON.parse(raw);
      // `[]` explícito é "quero todos", e tem de sobreviver ao recarregamento.
      if (Array.isArray(arr)) return arr.map(Number).filter(Boolean).sort((a, b) => a - b);
    }
  } catch { /* json invalido -> cai no legado */ }
  const legado = Number(localStorage.getItem(K_ANO_LEGADO) || 0);
  if (legado) return [legado];
  // Nunca escolheu nada: abre no ano corrente. `getFullYear` e não um literal —
  // em janeiro isto vira 2027 sozinho, sem ninguém lembrar de mexer.
  return [new Date().getFullYear()];
}

export function BiScopeProvider({ children }: { children: ReactNode }) {
  /* O escopo é LIDO do seletor único, e não guardado aqui. Não há `setScope`:
     quem muda de município é o seletor da barra lateral, que passa pela
     transição (aviso + remontagem + tela inicial). Um segundo caminho de troca
     sem transição reabriria exatamente o buraco que ela fechou. */
  const { escopo: scope } = useMunicipio();
  const [anos, setAnosState] = useState<number[]>(lerAnosIniciais);

  const setAnos = useCallback((a: number[]) => {
    const limpo = [...new Set(a.map(Number).filter(Boolean))].sort((x, y) => x - y);
    setAnosState(limpo);
    if (typeof window === "undefined") return;
    if (limpo.length) {
      localStorage.setItem(K_ANOS, JSON.stringify(limpo));
      // mantem a chave antiga coerente p/ quem ainda le (1 ano = mesmo valor)
      if (limpo.length === 1) localStorage.setItem(K_ANO_LEGADO, String(limpo[0]));
      else localStorage.removeItem(K_ANO_LEGADO);
    } else {
      // ⚠️ GRAVA `[]`, não apaga: é assim que "quero todos os anos" se distingue
      // de "nunca escolhi" — ver `lerAnosIniciais`.
      localStorage.setItem(K_ANOS, "[]");
      localStorage.removeItem(K_ANO_LEGADO);
    }
  }, []);

  const alternarAno = useCallback((a: number) => {
    setAnosState((atual) => {
      const proximo = atual.includes(a) ? atual.filter((x) => x !== a) : [...atual, a];
      const limpo = [...new Set(proximo)].sort((x, y) => x - y);
      if (typeof window !== "undefined") {
        if (limpo.length) {
          localStorage.setItem(K_ANOS, JSON.stringify(limpo));
          if (limpo.length === 1) localStorage.setItem(K_ANO_LEGADO, String(limpo[0]));
          else localStorage.removeItem(K_ANO_LEGADO);
        } else {
          // Mesma razão do `setAnos`: desligar a última pastilha é "quero
          // todos", e isso é uma escolha — tem de sobreviver ao recarregamento.
          localStorage.setItem(K_ANOS, "[]");
          localStorage.removeItem(K_ANO_LEGADO);
        }
      }
      return limpo;
    });
  }, []);

  const setAno = useCallback((a: number | undefined) => setAnos(a ? [a] : []), [setAnos]);

  const value = useMemo<BiScope>(() => ({
    scope,
    municipioId: scope && scope !== CONSOLIDADO ? Number(scope) : null,
    isConsolidado: scope === CONSOLIDADO,
    anos,
    setAnos,
    alternarAno,
    ano: anos.length === 1 ? anos[0] : undefined,
    setAno,
  }), [scope, anos, setAnos, alternarAno, setAno]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBiScope(): BiScope {
  const v = useContext(Ctx);
  if (!v) throw new Error("useBiScope precisa estar dentro de <BiScopeProvider>");
  return v;
}
