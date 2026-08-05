"use client";

/** A UF DO AMBIENTE ABERTO — o primitivo da adaptação por estado.
 *
 *  ⚠️ POR QUE EXISTE. O sistema nasceu mineiro e vestia rótulo de MG em tudo
 *  ("Convênios (SIGCON-MG)" numa cidade do ES). A regra virou: rótulo e
 *  comportamento seguem o ESTADO do município aberto — e para isso toda tela
 *  precisa saber a UF, coisa que o MunicipioContext (que só carrega o id) não
 *  dava. Este hook fecha esse buraco sem obrigar cada tela a refazer a chamada
 *  de /municipios que o layout já faz: uma busca por sessão, compartilhada.
 *
 *  Devolve "" enquanto carrega, no consolidado e sem seleção — quem consome
 *  trata "" como "ainda não sei", nunca como um estado. */

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import type { Municipio } from "@/types";

let cache: Municipio[] | null = null;
let emVoo: Promise<Municipio[]> | null = null;

function carregar(): Promise<Municipio[]> {
  if (cache) return Promise.resolve(cache);
  // Falha vira lista vazia E derruba a promessa em voo: a próxima tela tenta
  // de novo, em vez de todo mundo herdar um erro de rede eterno.
  emVoo ||= api
    .get<Municipio[]>("/municipios")
    .then((r) => {
      cache = Array.isArray(r.data) ? r.data : [];
      return cache;
    })
    .catch(() => {
      emVoo = null;
      return [] as Municipio[];
    });
  return emVoo;
}

export function useUfDoMunicipio(): string {
  const { municipioId } = useMunicipio();
  const [lista, setLista] = useState<Municipio[] | null>(cache);

  useEffect(() => {
    let vivo = true;
    carregar().then((l) => {
      if (vivo) setLista(l);
    });
    return () => {
      vivo = false;
    };
  }, []);

  if (!municipioId || !lista) return "";
  const m = lista.find((x) => String(x.id) === String(municipioId));
  return (m?.uf || "").toUpperCase();
}
