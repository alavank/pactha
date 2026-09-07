"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  HeartHandshake, Landmark, ExternalLink, ArrowLeft, MousePointerClick, Copy, Check,
  Loader2,
} from "lucide-react";
import api from "@/lib/api";
import {
  BOTAO_CTA, BOTAO_SEC, Aviso, Bloco, ESTILO_CTA, ESTILO_SEC,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

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
  },
  {
    key: "municipalista",
    nome: "Painel Municipalista",
    orgao: "Transferegov.br / SERPRO",
    desc: "Transferências da União ao município: convênios, especiais, emendas, saldo em conta e prestação de contas.",
    url: "https://dd-publico.serpro.gov.br/extensions/municipalista/municipalista.html",
    icon: Landmark,
  },
];

// Origens p/ preconnect (acelera o handshake TLS/DNS com os servidores do Governo).
const ORIGINS = Array.from(new Set(PANELS.map((p) => new URL(p.url).origin)));

export default function PaineisMunicipaisPage() {
  const municipioId = useMunicipio().municipioId || "";
  const [muns, setMuns] = useState<Municipio[]>([]);
  const [active, setActive] = useState<string | null>(null);
  // `opened` = iframe MONTADO (inclui o pre-aquecimento automatico).
  // `visitados` = o usuario realmente ABRIU o painel aqui dentro.
  // Sao coisas diferentes: o pre-aquecimento enche `opened` 400ms depois de a
  // tela carregar, entao usa-lo para revelar "Nova aba" faria o botao aparecer
  // sozinho — que e exatamente o que nao se quer no primeiro contato.
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [visitados, setVisitados] = useState<Set<string>>(new Set());
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
    setVisitados((s) => new Set(s).add(key));
    setActive(key);
  }, []);

  const copiar = useCallback(() => {
    if (!mun) return;
    navigator.clipboard.writeText(mun.nome);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  }, [mun]);

  // A AÇÃO vem primeiro e em destaque; o "são painéis do Governo" é contexto.
  // Antes era o inverso: a instrução na linha de cima e a explicação miúda
  // embaixo, o que fazia o aviso parecer só um rodapé.
  //
  // Ícone de clique e não de localização: o que se pede é uma AÇÃO dentro do
  // painel, não um lugar no mapa.
  const munBanner = (
    <Aviso tom="atencao" className="" titulo={
      <span className="flex items-center gap-1.5">
        <MousePointerClick className="size-3.5 shrink-0" />
        Painéis oficiais do governo.
      </span>
    }>
      {munLabel ? (
        <div className="flex flex-wrap items-center gap-2 text-[11px]" style={{ color: "var(--bi-text)" }}>
          <span>No filtro do painel (UF / Município), selecione:</span>
          <span className="inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 font-semibold"
                style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}>
            {munLabel}
            <button type="button" onClick={copiar} title="Copiar nome do município"
                    className="hover:brightness-90" style={{ color: "var(--bi-muted)" }}>
              {copiado ? <Check className="size-3.5" style={{ color: "var(--bi-ok-ink)" }} /> : <Copy className="size-3.5" />}
            </button>
          </span>
        </div>
      ) : (
        <div className="text-[11px]" style={{ color: "var(--bi-text)" }}>
          Selecione um município no seletor da barra lateral.
        </div>
      )}
    </Aviso>
  );

  const activePanel = PANELS.find((p) => p.key === active);

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col gap-4">
      {/* preconnect (React hoista p/ o <head>) — acelera a 1a carga dos painéis */}
      {ORIGINS.map((o) => <link key={o} rel="preconnect" href={o} crossOrigin="anonymous" />)}

      {/* Cabeçalho: hub ou painel aberto */}
      {activePanel ? (
        <div className="flex items-start justify-between gap-3">
          <div>
            {/* Voltar para a selecao — precisa ser achavel para trocar de
                painel, entao e um botao com borda e nao um link miudo. */}
            <button
              onClick={() => setActive(null)}
              className="mb-1.5 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-medium transition-colors bi-hover"
              style={ESTILO_SEC}
            >
              <ArrowLeft className="size-3.5" /> Escolher outro painel
            </button>
            <h1 className="flex items-center gap-2 text-xl font-bold text-base-content">
              <activePanel.icon className="size-5" style={{ color: "var(--bi-muted)" }} /> {activePanel.nome}
            </h1>
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>{activePanel.orgao}</p>
          </div>
          <a href={activePanel.url} target="_blank" rel="noopener noreferrer"
             className={`shrink-0 ${BOTAO_SEC}`} style={ESTILO_SEC}>
            <ExternalLink className="size-4" /> Abrir em nova aba
          </a>
        </div>
      ) : (
        <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
          <TituloTela>Painéis Municipais</TituloTela>
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Acesso centralizado aos painéis oficiais do Governo. Clique para abrir (já pré-carregados).
          </p>
        </div>
      )}

      {munBanner}

      {/* Área de conteúdo: cards (hub) + iframes SEMPRE montados (só o ativo visível) */}
      <div className="relative flex-1 overflow-hidden"
           style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", borderRadius: "var(--bi-radius)" }}>
        {/* Hub cards — visíveis quando nenhum painel está ativo */}
        {!active && (
          <div className="h-full overflow-auto p-4">
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {PANELS.map((p) => (
                <Bloco key={p.key} plano className="p-4">
                  <div className="flex items-center gap-3">
                    <span className="grid size-10 shrink-0 place-items-center rounded-full"
                          style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}>
                      <p.icon className="size-5" />
                    </span>
                    <div>
                      <h2 className="bi-title text-[14px] leading-tight">{p.nome}</h2>
                      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>{p.orgao}</p>
                    </div>
                    {opened.has(p.key) && (
                      <span className="ml-auto inline-flex items-center gap-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                        {loaded[p.key] ? <><Check className="size-3" style={{ color: "var(--bi-ok-ink)" }} /> pronto</> : <><Loader2 className="size-3 animate-spin" /> carregando</>}
                      </span>
                    )}
                  </div>
                  <p className="mt-3 flex-1 text-[12px] leading-snug" style={{ color: "var(--bi-muted)" }}>{p.desc}</p>
                  <div className="mt-4 flex items-center gap-2">
                    <button type="button" onClick={() => abrir(p.key)} className={BOTAO_CTA} style={ESTILO_CTA}>Abrir painel</button>
                    {/* "Nova aba" aparece so DEPOIS de o painel ter sido aberto
                        aqui. No primeiro contato ela competia com a acao
                        principal e tirava o usuario do sistema sem contexto. */}
                    {visitados.has(p.key) && (
                      <a href={p.url} target="_blank" rel="noopener noreferrer"
                         className={BOTAO_SEC} style={ESTILO_SEC}>
                        <ExternalLink className="size-4" /> Nova aba
                      </a>
                    )}
                  </div>
                </Bloco>
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
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-2" style={{ background: "var(--bi-surface)" }}>
                <Loader2 className="size-7 animate-spin" style={{ color: "var(--bi-faint)" }} />
                <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>Carregando painel oficial…</span>
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
