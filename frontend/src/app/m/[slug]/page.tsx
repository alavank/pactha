"use client";
// APP DE CELULAR (PWA) dos indicadores — /m/<slug>
//
// Público: prefeito e secretários FORA do gabinete, em reunião, sem computador.
// Daí três decisões que o diferenciam da TV (/t/<slug>):
//
//  1. FILTRO PRÓPRIO. A TV segue o filtro do dono em tempo real; aqui o aparelho
//     manda em si (ver lib/useFiltroMobile.ts). Mexer no período numa reunião não
//     pode mudar a TV do gabinete nem o painel de outro secretário.
//  2. UMA COLUNA e alvos grandes. Nada de grade de parede num aparelho de 390px.
//  3. Abas na BASE, não no topo: é onde o polegar alcança com o celular na mão.
//
// Instalável: manifest por slug (layout.tsx + route ao lado) e service worker.
// O atalho na tela inicial abre já credenciado — sem pedir login em pé na rua.
import { useEffect, useMemo, useState } from "react";
import { use } from "react";
import { Filter, RefreshCw, X, Check, WifiOff } from "lucide-react";
import { ABAS, AbaId, CONSOLIDADO_URL } from "@/lib/tela";
import { useFiltroMobile } from "@/lib/useFiltroMobile";
import { useDadosAba } from "@/lib/useAbaBi";
import { Municipio, getMunicipios } from "@/lib/bi";
import { ConteudoAba, EsqueletoAba } from "@/components/bi/PainelIndicadores";
import { EnteAtendido } from "@/components/bi/Marca";
import { InsightTicker } from "@/components/bi/InsightTicker";
import { Painel, Vazio } from "@/components/bi/kit";
import { rotuloPeriodo } from "@/components/bi/Filtros";

const RECARGA_MS = 5 * 60_000;

/** Anos oferecidos + atalhos. Mesma regra de mandato do painel e de Parlamentares. */
function periodoOpcoes() {
  const y = new Date().getFullYear();
  const anos = Array.from({ length: 8 }, (_, i) => y - i);
  const inicio = y - ((((y - 2025) % 4) + 4) % 4);
  const mandato = [inicio, inicio + 1, inicio + 2, inicio + 3].filter((a) => a <= y);
  return {
    anos,
    atalhos: [
      { label: "Mandato atual", valores: mandato },
      { label: "Este ano", valores: [y] },
      { label: "Todos", valores: [] as number[] },
    ],
  };
}

export default function AppMobilePage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = use(params);
  const { filtros, setAnos, setScope, pronto, erro } = useFiltroMobile(slug);
  const [aba, setAba] = useState<AbaId>("geral");
  const [filtroAberto, setFiltroAberto] = useState(false);
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  const { anos: ANOS, atalhos } = useMemo(() => periodoOpcoes(), []);

  // Service worker: é o que habilita "Instalar aplicativo" no Android e dá a
  // tela de sem-conexão. Registrado depois da hidratação para não competir com
  // a primeira pintura.
  useEffect(() => {
    if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
    const t = setTimeout(() => {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* sem SW o app funciona; só não fica instalável */
      });
    }, 1200);
    return () => clearTimeout(t);
  }, []);

  const municipioId = useMemo(() => {
    const s = filtros?.scope;
    return s && s !== CONSOLIDADO_URL ? Number(s) || null : null;
  }, [filtros?.scope]);
  const anosSel = filtros?.anos ?? [];

  useEffect(() => {
    if (!pronto || erro) return;
    getMunicipios().then(setMunicipios).catch(() => {});
  }, [pronto, erro]);

  const nomeMunicipio = useMemo(() => {
    if (!municipios.length) return null;
    const m = municipioId
      ? municipios.find((x) => x.id === municipioId)
      : municipios.length === 1 ? municipios[0] : null;
    return m ? `${m.nome} — ${m.uf}` : null;
  }, [municipios, municipioId]);

  const podeTrocarMunicipio = municipios.length > 1;

  // UM gate para tudo que bate na API. Sem token (slug ainda nao resolvido) todo
  // request volta 401 e o interceptor manda o app para /login.
  const dadosProntos = pronto && !erro && !!filtros;

  const { dados, carregando, recarregar } = useDadosAba(aba, municipioId, anosSel, {
    pronto: dadosProntos,
    recarregarMs: RECARGA_MS,
  });

  if (erro) {
    return (
      <div className="bi-skin flex min-h-screen items-center justify-center p-6" data-bi-theme="dark">
        <div className="text-center">
          <WifiOff className="mx-auto mb-3 size-8" style={{ color: "var(--bi-faint)" }} />
          <div className="bi-title text-[18px]">Painel indisponível</div>
          <p className="mt-2 text-[13px]" style={{ color: "var(--bi-faint)" }}>{erro}</p>
        </div>
      </div>
    );
  }

  const abaAtual = ABAS.find((a) => a.id === aba)!;

  return (
    <div
      className="bi-skin flex min-h-screen flex-col"
      data-bi-theme="dark"
      style={{ background: "var(--bi-bg)" }}
    >
      {/* Cabeçalho fixo: quem é o ente + o período VIGENTE sempre à vista.
          Numa reunião, ninguém deve ter de lembrar de cabeça o que está filtrado. */}
      <header
        className="sticky top-0 z-20 px-4 pb-2"
        style={{
          background: "var(--bi-bg)",
          borderBottom: "1px solid var(--bi-line)",
          paddingTop: "max(0.75rem, env(safe-area-inset-top))",
        }}
      >
        <div className="flex items-center gap-2">
          <EnteAtendido nome={nomeMunicipio} tamanho="medio" className="min-w-0 flex-1" />
          <button
            type="button"
            onClick={recarregar}
            aria-label="Atualizar"
            className="grid size-10 shrink-0 place-items-center rounded-full"
            style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
          >
            <RefreshCw className={carregando ? "size-4 animate-spin" : "size-4"} />
          </button>
        </div>

        <button
          type="button"
          onClick={() => setFiltroAberto(true)}
          className="mt-2 flex w-full items-center gap-2 rounded-2xl px-3 py-2.5 text-left"
          style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
        >
          <Filter className="size-4 shrink-0" style={{ color: "var(--bi-accent)" }} />
          <span className="min-w-0 flex-1 truncate text-[13px]">
            <span style={{ color: "var(--bi-faint)" }}>Período: </span>
            <span className="font-semibold">{rotuloPeriodo(anosSel)}</span>
          </span>
          <span className="shrink-0 text-[11px]" style={{ color: "var(--bi-faint)" }}>alterar</span>
        </button>
      </header>

      <div className="px-4 pt-3">
        {/* Preso ao mesmo `pronto` dos dados: o ticker busca no MOUNT, e aqui o
            mount acontece antes de o slug virar token. Sem esta guarda ele
            dispara /bi/insights sem credencial, toma 401 e o interceptor de
            api.ts joga o app no /login — exatamente o que aconteceu na primeira
            tentativa desta tela. */}
        {dadosProntos && (
          <InsightTicker aba={aba} municipioId={municipioId} anos={anosSel} />
        )}
      </div>

      {/* Conteúdo: uma coluna. Espaço extra embaixo p/ a barra de abas não cobrir. */}
      <main className="flex-1 px-4 pb-32 pt-3">
        <div className="mb-2">
          <h1 className="bi-title text-[17px]">{abaAtual.label}</h1>
          <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>{abaAtual.descricao}</p>
        </div>
        {!dados ? (
          carregando ? <EsqueletoAba /> : <Painel><Vazio>Sem dados para este período.</Vazio></Painel>
        ) : (
          <div key={aba} className="bi-pane-enter">
            <ConteudoAba dados={dados} />
          </div>
        )}
      </main>

      {/* Abas na BASE: alcance do polegar. Rolagem horizontal porque são seis e
          cortar rótulo em telefone pequeno é pior que arrastar. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-20"
        style={{
          background: "var(--bi-surface)",
          borderTop: "1px solid var(--bi-line)",
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
      >
        <div className="bi-scroll flex gap-1 overflow-x-auto px-2 py-2">
          {ABAS.map((a) => {
            const ativo = a.id === aba;
            return (
              <button
                key={a.id}
                type="button"
                onClick={() => setAba(a.id)}
                aria-current={ativo ? "page" : undefined}
                className="shrink-0 rounded-xl px-3.5 py-2 text-[12px] font-semibold transition-colors"
                style={{
                  background: ativo ? "var(--bi-cta)" : "transparent",
                  color: ativo ? "var(--bi-cta-ink)" : "var(--bi-muted)",
                  minHeight: 44, // alvo de toque confortável
                }}
              >
                {a.curto}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Folha de filtro. Sobe de baixo porque é de baixo que o dedo vem. */}
      {filtroAberto && (
        <div className="fixed inset-0 z-30 flex items-end" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="Fechar filtro"
            onClick={() => setFiltroAberto(false)}
            className="absolute inset-0 bg-black/60"
          />
          <div
            className="relative w-full rounded-t-3xl p-4"
            style={{
              background: "var(--bi-surface)",
              borderTop: "1px solid var(--bi-line)",
              paddingBottom: "max(1rem, env(safe-area-inset-bottom))",
            }}
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="bi-title text-[16px]">Período</span>
              <button
                type="button"
                onClick={() => setFiltroAberto(false)}
                aria-label="Fechar"
                className="grid size-9 place-items-center rounded-full"
                style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="mb-3 flex flex-wrap gap-1.5">
              {atalhos.map((at) => (
                <button
                  key={at.label}
                  type="button"
                  onClick={() => setAnos(at.valores)}
                  className="rounded-full px-3 py-1.5 text-[12px] font-medium"
                  style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
                >
                  {at.label}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-4 gap-2">
              {ANOS.map((a) => {
                const on = anosSel.includes(a);
                return (
                  <button
                    key={a}
                    type="button"
                    onClick={() => setAnos(on ? anosSel.filter((x) => x !== a) : [...anosSel, a])}
                    aria-pressed={on}
                    className="rounded-xl py-2.5 text-[13px] font-semibold"
                    style={{
                      background: on ? "var(--bi-accent-soft)" : "var(--bi-surface-2)",
                      border: `1px solid ${on ? "var(--bi-accent)" : "var(--bi-line)"}`,
                      color: on ? "var(--bi-accent)" : "var(--bi-muted)",
                      minHeight: 44,
                    }}
                  >
                    {a}
                  </button>
                );
              })}
            </div>
            <p className="mt-2 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Nenhum ano marcado = todos os anos.
            </p>

            {/* Município só aparece para carteira (assessoria). Município único
                não tem o que escolher, e o seletor sugeriria que há dado de
                outra cidade aqui dentro. */}
            {podeTrocarMunicipio && (
              <div className="mt-4">
                <div className="bi-title mb-2 text-[16px]">Município</div>
                <div className="flex flex-col gap-1.5">
                  {municipios.map((m) => {
                    const on = String(m.id) === filtros?.scope;
                    return (
                      <button
                        key={m.id}
                        type="button"
                        onClick={() => setScope(String(m.id))}
                        className="flex items-center justify-between rounded-xl px-3 py-2.5 text-[13px]"
                        style={{
                          background: on ? "var(--bi-accent-soft)" : "var(--bi-surface-2)",
                          border: `1px solid ${on ? "var(--bi-accent)" : "var(--bi-line)"}`,
                          minHeight: 44,
                        }}
                      >
                        <span className="truncate">{m.nome} — {m.uf}</span>
                        {on && <Check className="size-4 shrink-0" style={{ color: "var(--bi-accent)" }} />}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            <button
              type="button"
              onClick={() => setFiltroAberto(false)}
              className="mt-4 w-full rounded-2xl py-3 text-[14px] font-bold"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)", minHeight: 48 }}
            >
              Ver indicadores
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
