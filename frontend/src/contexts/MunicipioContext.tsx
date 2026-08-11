"use client";

import React, {
  createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  TransicaoMunicipio, type MunicipioEscolha,
} from "@/components/TransicaoMunicipio";

/** O escopo "carteira inteira", só existe para assessoria/consórcio (N municípios).
 *  Mesmo valor que o backend entende (`backend/routers/bi.py`). */
export const CONSOLIDADO = "__all__";

/** A chave do quiosque. A TV (`components/bi/ModoTela.tsx`) e o app de celular
 *  rodam FORA deste provider e continuam lendo daqui — por isso este arquivo
 *  segue ESCREVENDO nela. O que acabou foi a leitura concorrente: dentro do
 *  sistema, quem manda é o escopo abaixo, e mais ninguém. */
const K_ESPELHO_BI = "pactha_bi_scope";
const K_ESCOPO = "pactha_last_municipio_id";

type MunicipioCtx = {
  /** ⭐ O MUNICÍPIO OPERACIONAL: id concreto, ou `""` no consolidado.
   *
   *  Continua sendo o que as telas operacionais leem, e é de propósito que ele
   *  fique VAZIO na carteira inteira: consultar convênio, cofre ou anotação é
   *  sempre de um município por vez, e as seis telas já sabem dizer "Selecione
   *  um município". Fosse `__all__`, elas mandariam isso para a API. */
  municipioId: string;
  /** A escolha CRUA do seletor: `""`, `"<id>"` ou `CONSOLIDADO`. É o que o
   *  Painel de Indicadores consome. */
  escopo: string;
  isConsolidado: boolean;
  /** Troca DIRETA, sem transição. Só para correção automática (id obsoleto,
   *  município que saiu da lista) — não para o gesto do usuário. */
  setMunicipioId: (id: string) => void;
  /** ⭐ O GESTO DO USUÁRIO. Abre o aviso, roda a transição e cai na tela
   *  inicial do destino. `rotulo` é o nome que aparece no aviso. */
  trocarEscopo: (destino: string, rotulo: string) => void;
  /** Abre a MESMA caixa na fase de escolha (busca + lista). É o que a barra
   *  lateral chama hoje, no lugar do antigo <select>. */
  abrirTroca: () => void;
  /** A barra lateral entrega a lista que veio de `GET /api/municipios` (já
   *  filtrada por ativos e pelo escopo do usuário) — o provider não busca nada
   *  por conta própria para não duplicar requisição nem regra de permissão. */
  registrarMunicipios: (lista: MunicipioEscolha[]) => void;
  emTransicao: boolean;
};

const Ctx = createContext<MunicipioCtx | null>(null);

/**
 * ⭐ FONTE ÚNICA do município — do sistema inteiro, e não só do lado operacional.
 *
 * ⚠️ POR QUE A TROCA VIROU UMA TRANSIÇÃO, E NÃO É ENFEITE.
 * Numa assessoria os municípios são CLIENTES DIFERENTES, e a troca era um
 * `setState` que não desmontava nada: formulário meio preenchido, modal aberto,
 * filtro marcado, cache de detalhe — tudo sobrevivia. Media-se o estrago em dois
 * lugares onde ele virava ESCRITA: um documento preenchido no município A era
 * salvo em B, e uma credencial digitada para A ia para o cofre de B.
 *
 * A correção de verdade é a REMONTAGEM (`key={escopo}` em `dashboard/layout.tsx`)
 * e a ida para a tela inicial. A transição é a janela em que isso acontece — e é
 * por isso que ela existe: dá ao sistema o tempo de desmontar e ao usuário a
 * noção de que entrou noutro ambiente. Sem ela, a remontagem seria um piscar
 * inexplicável no meio do trabalho.
 */
export function MunicipioProvider({ children }: { children: ReactNode }) {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [escopo, setEscopo] = useState<string>(() => {
    const daUrl = searchParams.get("municipio_id");
    if (daUrl) return daUrl;
    if (typeof window !== "undefined") return localStorage.getItem(K_ESCOPO) || "";
    return "";
  });

  /** O destino pedido, enquanto o aviso e a animação acontecem. */
  const [pendente, setPendente] = useState<{ destino: string; rotulo: string } | null>(null);
  /** A caixa está aberta na fase de ESCOLHA (nenhum destino escolhido ainda). */
  const [escolhendo, setEscolhendo] = useState(false);
  const [lista, setLista] = useState<MunicipioEscolha[]>([]);

  const gravar = useCallback((valor: string) => {
    setEscopo(valor);
    if (typeof window === "undefined") return;
    if (valor) {
      localStorage.setItem(K_ESCOPO, valor);
      // Espelho para a TV e o app de celular, que rodam fora deste provider.
      localStorage.setItem(K_ESPELHO_BI, valor);
    }
    // Sincroniza a URL sem navegar (continua compartilhável e sobrevive ao F5).
    const params = new URLSearchParams(window.location.search);
    if (valor) params.set("municipio_id", valor);
    else params.delete("municipio_id");
    params.delete("page"); // a paginação não atravessa a troca
    const qs = params.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
  }, []);

  const trocarEscopo = useCallback((destino: string, rotulo: string) => {
    /* Escolher o município que já está ativo não é troca — fecha a caixa e
       pronto. Sem este `setEscolhendo(false)` o clique não produziria efeito
       nenhum e a caixa ficaria aberta, parecendo travada. */
    if (!destino || destino === escopo) { setEscolhendo(false); return; }
    setPendente({ destino, rotulo });
    setEscolhendo(false);   // a MESMA caixa passa da escolha para o aviso
  }, [escopo]);

  const abrirTroca = useCallback(() => setEscolhendo(true), []);
  const registrarMunicipios = useCallback((ms: MunicipioEscolha[]) => setLista(ms), []);

  /** Confirmado: grava o destino e cai na TELA INICIAL.
   *
   *  ⚠️ Sempre a home, mesmo vindo de uma tela interna. Não é preferência: uma
   *  tela de DETALHE (um convênio, um relatório, um documento) é de um município
   *  específico, e mantê-la aberta depois da troca deixaria na frente do usuário
   *  o registro do cliente anterior sob o nome do novo. */
  const confirmar = useCallback((destino: string) => {
    gravar(destino);
    router.push("/dashboard");
  }, [gravar, router]);

  const cancelar = useCallback(() => { setPendente(null); setEscolhendo(false); }, []);
  const concluir = useCallback(() => { setPendente(null); setEscolhendo(false); }, []);

  const setMunicipioId = useCallback((id: string) => gravar(id), [gravar]);

  const isConsolidado = escopo === CONSOLIDADO;

  return (
    <Ctx.Provider
      value={{
        municipioId: isConsolidado ? "" : escopo,
        escopo,
        isConsolidado,
        setMunicipioId,
        trocarEscopo,
        abrirTroca,
        registrarMunicipios,
        emTransicao: pendente !== null,
      }}
    >
      {children}
      {(escolhendo || pendente) && (
        <TransicaoMunicipio
          /* `rotulo` null = a caixa abre na ESCOLHA. Quando o destino é
             escolhido, `pendente` chega e a MESMA caixa vira o aviso — sem
             desmontar, senão seriam dois modais piscando para um gesto só. */
          rotulo={pendente?.rotulo ?? null}
          municipios={lista}
          escopoAtual={escopo}
          onEscolher={trocarEscopo}
          onConfirmar={() => pendente && confirmar(pendente.destino)}
          onCancelar={cancelar}
          onConcluir={concluir}
        />
      )}
    </Ctx.Provider>
  );
}

export function useMunicipio(): MunicipioCtx {
  const ctx = useContext(Ctx);
  if (!ctx) {
    return {
      municipioId: "", escopo: "", isConsolidado: false,
      setMunicipioId: () => {}, trocarEscopo: () => {},
      abrirTroca: () => {}, registrarMunicipios: () => {},
      emTransicao: false,
    };
  }
  return ctx;
}

/** Espelha o escopo na chave do quiosque quando ele muda por fora (correção
 *  automática, deep link). Fica aqui e não no `gravar` para o caso de o valor
 *  inicial vir da URL — aí nada é gravado e a TV ficaria com o escopo velho. */
export function useEspelharEscopoNoQuiosque(escopo: string) {
  const jaEspelhado = useRef<string>("");
  useEffect(() => {
    if (!escopo || escopo === jaEspelhado.current) return;
    jaEspelhado.current = escopo;
    if (typeof window !== "undefined") localStorage.setItem(K_ESPELHO_BI, escopo);
  }, [escopo]);
}
