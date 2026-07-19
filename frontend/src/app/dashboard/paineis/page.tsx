"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  HeartHandshake, Landmark, ExternalLink, ArrowLeft, MapPin, Copy, Check,
  LayoutGrid, Loader2,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";

interface Municipio { id: number; nome: string; uf: string; }

// Painéis oficiais (Qlik Sense) embutidos via iframe. São de domínios do Governo
// (cross-origin) e NÃO expõem filtro por URL — a seleção de UF/município é feita
// nos filtros internos do painel. Por isso destacamos o município + instrução.
const PANELS = [
  {
    key: "suas",
    nome: "Estrutura SUAS",
    orgao: "MDS — Ministério do Desenvolvimento e Assistência Social",
    desc: "Acompanhamento das programações do cofinanciamento federal do Estrutura SUAS.",
    url: "https://paineis.mds.gov.br/public/extensions/Acompanhamento_de_Programacoes_do_Estrutura_SUAS/Acompanhamento_de_Programacoes_do_Estrutura_SUAS.html",
    icon: HeartHandshake,
    accent: "text-primary",
  },
  {
    key: "municipalista",
    nome: "Painel Municipalista",
    orgao: "Transferegov.br / SERPRO",
    desc: "Transferências da União ao município: convênios, especiais, emendas, saldo em conta e prestação de contas.",
    url: "https://dd-publico.serpro.gov.br/extensions/municipalista/municipalista.html",
    icon: Landmark,
    accent: "text-success",
  },
];

// Origens p/ preconnect (acelera o handshake TLS/DNS com os servidores do Governo).
const ORIGINS = Array.from(new Set(PANELS.map((p) => new URL(p.url).origin)));

export default function PaineisMunicipaisPage() {
  const municipioId = useMunicipio().municipioId || "";
  const [muns, setMuns] = useState<Municipio[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});
  const [copiado, setCopiado] = useState(false);

  useEffect(() => {
    api.get<Municipio[]>("/municipios")
      .then((r) => setMuns(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, []);

  // Pré-aquece os painéis: começa a carregar os iframes em background logo que a
  // tela abre (enquanto o usuário lê os cards) -> clicar já vem quente/rápido.
  useEffect(() => {
    const t = setTimeout(() => setOpened(new Set(PANELS.map((p) => p.key))), 400);
    return () => clearTimeout(t);
  }, []);

  const mun = muns.find((m) => String(m.id) === String(municipioId));
  const munLabel = mun ? `${mun.nome} - ${mun.uf}` : null;

  const abrir = useCallback((key: string) => {
    setOpened((s) => new Set(s).add(key));
    setActive(key);
  }, []);

  const copiar = useCallback(() => {
    if (!mun) return;
    navigator.clipboard.writeText(mun.nome);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  }, [mun]);

  const MunBanner = () => (
    <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <MapPin className="size-4 text-warning shrink-0" />
        {munLabel ? (
          <>
            <span className="text-base-content/80">No filtro do painel (UF / Município), selecione:</span>
            <span className="inline-flex items-center gap-1.5 rounded-md border border-base-300 bg-base-100 px-2 py-0.5 font-semibold text-base-content">
              {munLabel}
              <button onClick={copiar} title="Copiar nome do município" className="text-base-content/50 hover:text-primary">
                {copiado ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
              </button>
            </span>
          </>
        ) : (
          <span className="text-base-content/80">Selecione um município no seletor da barra lateral.</span>
        )}
      </div>
      <p className="mt-1 text-[11px] text-base-content/50">
        Painéis oficiais do Governo (Qlik) — a seleção do município é feita no filtro do próprio painel.
      </p>
    </div>
  );

  const activePanel = PANELS.find((p) => p.key === active);

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-3 p-4">
      {/* preconnect (React hoista p/ o <head>) — acelera a 1a carga dos painéis */}
      {ORIGINS.map((o) => <link key={o} rel="preconnect" href={o} crossOrigin="anonymous" />)}

      {/* Cabeçalho: hub ou painel aberto */}
      {activePanel ? (
        <div className="flex items-start justify-between gap-3">
          <div>
            <button onClick={() => setActive(null)} className="mb-1 inline-flex items-center gap-1 text-xs text-base-content/60 hover:text-primary">
              <ArrowLeft className="size-3.5" /> Painéis Municipais
            </button>
            <h1 className="flex items-center gap-2 text-xl font-bold text-base-content">
              <activePanel.icon className={`size-5 ${activePanel.accent}`} /> {activePanel.nome}
            </h1>
            <p className="text-xs text-base-content/50">{activePanel.orgao}</p>
          </div>
          <a href={activePanel.url} target="_blank" rel="noopener noreferrer"
             className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-base-300 bg-base-100 px-3 py-2 text-sm font-medium text-base-content/80 hover:bg-base-200">
            <ExternalLink className="size-4" /> Abrir em nova aba
          </a>
        </div>
      ) : (
        <div className="border-b border-base-300 pb-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <LayoutGrid className="size-6 text-primary" /> Painéis Municipais
          </h1>
          <p className="mt-1 text-sm text-base-content/60">
            Acesso centralizado aos painéis oficiais do Governo. Clique para abrir (já pré-carregados).
          </p>
        </div>
      )}

      <MunBanner />

      {/* Área de conteúdo: cards (hub) + iframes SEMPRE montados (só o ativo visível) */}
      <div className="relative flex-1 overflow-hidden rounded-lg border border-base-300 bg-base-100">
        {/* Hub cards — visíveis quando nenhum painel está ativo */}
        {!active && (
          <div className="h-full overflow-auto p-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {PANELS.map((p) => (
                <div key={p.key} className="flex flex-col rounded-lg border border-base-300 bg-base-200/40 p-5">
                  <div className="flex items-center gap-3">
                    <div className="rounded-lg bg-base-100 p-2.5"><p.icon className={`size-6 ${p.accent}`} /></div>
                    <div>
                      <h2 className="font-semibold text-base-content">{p.nome}</h2>
                      <p className="text-[11px] text-base-content/50">{p.orgao}</p>
                    </div>
                    {opened.has(p.key) && (
                      <span className="ml-auto inline-flex items-center gap-1 text-[10px] text-base-content/40">
                        {loaded[p.key] ? <><Check className="size-3 text-success" /> pronto</> : <><Loader2 className="size-3 animate-spin" /> carregando</>}
                      </span>
                    )}
                  </div>
                  <p className="mt-3 flex-1 text-sm text-base-content/70">{p.desc}</p>
                  <div className="mt-4 flex items-center gap-2">
                    <Button onClick={() => abrir(p.key)} className="bg-primary hover:bg-primary/90">Abrir painel</Button>
                    <a href={p.url} target="_blank" rel="noopener noreferrer"
                       className="inline-flex items-center gap-1.5 rounded-md border border-base-300 px-3 py-2 text-sm text-base-content/70 hover:bg-base-200">
                      <ExternalLink className="size-4" /> Nova aba
                    </a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* iframes: montados uma vez (pré-aquecidos) e mantidos — reabrir é instantâneo */}
        {PANELS.filter((p) => opened.has(p.key)).map((p) => (
          <div
            key={p.key}
            className={`absolute inset-0 ${active === p.key ? "visible" : "invisible pointer-events-none"}`}
            aria-hidden={active !== p.key}
          >
            {!loaded[p.key] && (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 bg-base-100">
                <Loader2 className="size-7 animate-spin text-primary" />
                <span className="text-xs text-base-content/50">Carregando painel oficial…</span>
              </div>
            )}
            <iframe
              src={p.url}
              title={`${p.nome} — ${p.orgao}`}
              className="h-full w-full"
              onLoad={() => setLoaded((l) => ({ ...l, [p.key]: true }))}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
