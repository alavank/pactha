"use client";
// Filtro do app de celular — INDEPENDENTE, e essa é a razão de ele existir.
//
// A TV (/t/<slug>) segue o filtro do dono em tempo real: ela é uma extensão da
// tela do gabinete. O celular é o contrário: o gestor está na rua, numa reunião,
// e precisa mexer no período ali mesmo — sem depender de alguém no computador e
// sem que isso mude a TV do gabinete ou o painel de outro secretário.
//
// Por isso aqui NÃO existe poll do filtro do dono. O que vem do servidor é usado
// UMA vez, como semente; a partir daí o aparelho é dono do seu filtro e o guarda
// localmente, por slug (dois links diferentes no mesmo celular não se misturam).
import { useCallback, useEffect, useRef, useState } from "react";
import { resolverTelaPub } from "./bi";
import { CONSOLIDADO_URL, FiltrosTela } from "./tela";

const chaveAnos = (slug: string) => `pactha_m_${slug}_anos`;
const chaveScope = (slug: string) => `pactha_m_${slug}_scope`;

export interface FiltroMobile {
  filtros: FiltrosTela | null;
  setAnos: (anos: number[]) => void;
  setScope: (scope: string) => void;
  /** false enquanto não houver token — sem ele, todo request volta 401. */
  pronto: boolean;
  erro: string | null;
}

export function useFiltroMobile(slug: string): FiltroMobile {
  const [filtros, setFiltrosState] = useState<FiltrosTela | null>(null);
  const [pronto, setPronto] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const resolvido = useRef(false);

  useEffect(() => {
    if (resolvido.current) return;
    resolvido.current = true;
    let vivo = true;

    (async () => {
      // O que ESTE aparelho já escolheu antes tem prioridade sobre a semente:
      // reabrir o app não pode desfazer o filtro que o gestor deixou montado.
      let anosLocal: number[] | null = null;
      let scopeLocal: string | null = null;
      try {
        const a = localStorage.getItem(chaveAnos(slug));
        if (a) anosLocal = (JSON.parse(a) as number[]).map(Number).filter(Boolean);
        scopeLocal = localStorage.getItem(chaveScope(slug));
      } catch { /* storage bloqueado: segue com a semente */ }

      try {
        const r = await resolverTelaPub(slug);
        if (r.token) {
          try {
            localStorage.setItem("pactha_kiosk_token", r.token);
          } catch { /* storage bloqueado */ }
        }
        if (!vivo) return;
        setFiltrosState({
          scope: scopeLocal || r.scope || CONSOLIDADO_URL,
          anos: anosLocal ?? r.anos ?? [],
        });
      } catch (e) {
        if (!vivo) return;
        const st = (e as { response?: { status?: number } })?.response?.status;
        setErro(
          st === 404
            ? "Link inválido, expirado ou revogado. Peça um novo a quem publicou."
            : "Não foi possível conectar. Verifique a internet e tente de novo."
        );
      } finally {
        if (vivo) setPronto(true);
      }
    })();

    return () => { vivo = false; };
  }, [slug]);

  const setAnos = useCallback((anos: number[]) => {
    const limpo = [...new Set(anos.map(Number).filter(Boolean))].sort((a, b) => a - b);
    setFiltrosState((f) => (f ? { ...f, anos: limpo } : f));
    try {
      if (limpo.length) localStorage.setItem(chaveAnos(slug), JSON.stringify(limpo));
      else localStorage.removeItem(chaveAnos(slug));
    } catch { /* storage bloqueado */ }
  }, [slug]);

  const setScope = useCallback((scope: string) => {
    setFiltrosState((f) => (f ? { ...f, scope } : f));
    try {
      localStorage.setItem(chaveScope(slug), scope);
    } catch { /* storage bloqueado */ }
  }, [slug]);

  return { filtros, setAnos, setScope, pronto, erro };
}
