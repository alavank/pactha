"use client";
// A TRAVESSIA ENTRE MUNICÍPIOS.
//
// Numa assessoria os municípios são CLIENTES DIFERENTES. Trocar de município
// não é filtrar uma lista: é entrar noutro ambiente. Esta peça existe para dizer
// isso em voz alta, e para dar ao sistema a janela em que ele desmonta a tela
// anterior antes de pintar a próxima.
//
// São TRÊS momentos numa caixa só (pedido do dono, 10/08/2026: "coloca a troca
// de cidade no modal de aviso e faz a junção, já fica tudo lá"):
//   1. A ESCOLHA, com busca. Antes era um <select> na barra lateral, e com 44
//      municípios a lista abria colada no menu, sumia no rodapé e "parecia erro
//      na página" — a lista longa não cabe num dropdown de canto.
//   2. O AVISO, que pode ser cancelado. Enquanto ele está aberto nada mudou —
//      quem clicou por engano sai sem consequência.
//   3. A TRAVESSIA, que não pode. Depois do OK o município já é outro, e voltar
//      atrás no meio deixaria a tela remontando para um destino que o usuário
//      acabou de desistir.
//
// A caixa NÃO fecha entre 1 e 2: é o mesmo cartão trocando de conteúdo, senão
// seriam dois modais piscando em sequência para um gesto só.
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Building2, Check, Search } from "lucide-react";

/** ~800ms: cabe a sensação de mudança e cobre a primeira busca da tela inicial,
 *  sem virar espera. Acima disso, quem troca de município várias vezes seguidas
 *  passa a esperar o sistema em vez de usá-lo. */
const DURACAO_MS = 800;

export type MunicipioEscolha = { id: number | string; nome: string; uf: string };

/** Busca sem acento e sem caixa: "sao tiago" acha "São Tiago", "carmopolis"
 *  acha "Carmópolis de Minas". Sem isto, metade da carteira de MG só é
 *  encontrada por quem digita o acento certo. */
function normalizar(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

export function TransicaoMunicipio({
  rotulo, municipios = [], escopoAtual = "",
  onEscolher, onConfirmar, onCancelar, onConcluir,
}: {
  /** O nome do destino, como aparece no seletor ("Monte Sião - MG").
   *  `null` = ainda não há destino: a caixa abre na fase de ESCOLHA. */
  rotulo: string | null;
  municipios?: MunicipioEscolha[];
  /** Id do município ativo — marcado com ✓ na lista. */
  escopoAtual?: string;
  onEscolher?: (destino: string, rotulo: string) => void;
  onConfirmar: () => void;
  onCancelar: () => void;
  onConcluir: () => void;
}) {
  const [atravessando, setAtravessando] = useState(false);
  const [busca, setBusca] = useState("");
  const [destaque, setDestaque] = useState(0);
  const listaRef = useRef<HTMLDivElement | null>(null);

  const escolhendo = !atravessando && !rotulo;

  const filtrados = useMemo(() => {
    const q = normalizar(busca);
    if (!q) return municipios;
    return municipios.filter((m) => normalizar(`${m.nome} ${m.uf}`).includes(q));
  }, [municipios, busca]);

  /* Rolar o item destacado para dentro da vista. `block: "nearest"` para a lista
     não pular quando o item já está visível. */
  useEffect(() => {
    if (!escolhendo) return;
    const el = listaRef.current?.querySelector<HTMLElement>(`[data-idx="${destaque}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [destaque, escolhendo]);

  useEffect(() => {
    if (!atravessando) return;
    const t = setTimeout(onConcluir, DURACAO_MS);
    return () => clearTimeout(t);
  }, [atravessando, onConcluir]);

  /* Esc cancela — mas só antes da travessia. Depois dela a troca já aconteceu, e
     um Esc que "fechasse" deixaria a tela pela metade. */
  useEffect(() => {
    if (atravessando) return;
    const aoTeclar = (e: KeyboardEvent) => { if (e.key === "Escape") onCancelar(); };
    window.addEventListener("keydown", aoTeclar);
    return () => window.removeEventListener("keydown", aoTeclar);
  }, [atravessando, onCancelar]);

  const comecar = () => {
    setAtravessando(true);
    onConfirmar();
  };

  const escolher = (m: MunicipioEscolha) =>
    onEscolher?.(String(m.id), `${m.nome} - ${m.uf}`);

  /** Setas andam na lista, Enter escolhe. Fica no input (que tem o foco) em vez
   *  de na janela: assim não disputa tecla com o resto do sistema. */
  const teclaNaBusca = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setDestaque((i) => Math.min(i + 1, filtrados.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setDestaque((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const m = filtrados[destaque];
      if (m) escolher(m);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[70] grid place-items-center bg-base-300/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-live="polite"
      aria-label={
        atravessando ? `Entrando em ${rotulo}`
          : rotulo ? `Mudar para ${rotulo}`
          : "Escolher município"
      }
    >
      {atravessando ? (
        <div className="flex flex-col items-center gap-5 pactha-travessia">
          <span className="text-lg font-bold tracking-tight text-base-content">PACTHA</span>
          <Pontinhos />
          <span className="text-sm text-base-content/70">
            Entrando em <b className="text-base-content">{rotulo}</b>
          </span>
        </div>
      ) : escolhendo ? (
        /* FASE 1 — ESCOLHA. Mesma moldura do aviso, um pouco mais larga: a
           lista precisa de corpo, e o cartão não pode crescer a ponto de virar
           uma segunda página. */
        <div className="mx-4 flex max-h-[80vh] w-full max-w-md flex-col rounded-2xl border border-base-300 bg-base-100 shadow-xl">
          <div className="border-b border-base-300 p-4">
            <div className="mb-3 flex items-center gap-2.5">
              <span className="flex size-9 items-center justify-center rounded-xl bg-primary/10">
                <Building2 className="size-4.5 text-primary" />
              </span>
              <div>
                <h2 className="text-base font-bold text-base-content">Trocar de município</h2>
                <p className="text-[11px] text-base-content/50">
                  {municipios.length} municípios na carteira
                </p>
              </div>
            </div>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-base-content/40" />
              <input
                autoFocus
                value={busca}
                /* O destaque volta ao topo a cada tecla — com a lista filtrada,
                   manter o índice antigo apontaria para outro município e Enter
                   trocaria de cidade errada. Vai no onChange, não num efeito:
                   `setState` dentro de effect é erro de lint no projeto (e aqui
                   custaria um render a mais por letra digitada). */
                onChange={(e) => { setBusca(e.target.value); setDestaque(0); }}
                onKeyDown={teclaNaBusca}
                placeholder="Buscar município…"
                aria-label="Buscar município"
                className="w-full rounded-lg border border-base-300 bg-base-100 py-2 pr-3 pl-8 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
              />
            </div>
          </div>

          <div ref={listaRef} className="min-h-0 flex-1 overflow-y-auto p-2">
            {filtrados.length === 0 ? (
              <p className="px-2 py-6 text-center text-sm text-base-content/50">
                Nenhum município com “{busca}”.
              </p>
            ) : (
              filtrados.map((m, i) => {
                const atual = String(m.id) === escopoAtual;
                return (
                  <button
                    key={m.id}
                    type="button"
                    data-idx={i}
                    onMouseEnter={() => setDestaque(i)}
                    onClick={() => escolher(m)}
                    aria-current={atual ? "true" : undefined}
                    className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-sm transition-colors ${
                      i === destaque ? "bg-base-200" : ""
                    } ${atual ? "font-semibold text-base-content" : "text-base-content/80"}`}
                  >
                    <span className="min-w-0 flex-1 truncate">
                      {m.nome} <span className="text-base-content/45">- {m.uf}</span>
                    </span>
                    {atual && <Check className="size-4 shrink-0 text-primary" />}
                  </button>
                );
              })
            )}
          </div>

          <div className="flex justify-end border-t border-base-300 p-3">
            <button
              type="button"
              onClick={onCancelar}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-base-content/70 hover:bg-base-200"
            >
              Fechar
            </button>
          </div>
        </div>
      ) : (
        /* FASE 2 — AVISO. */
        <div className="mx-4 w-full max-w-sm rounded-2xl border border-base-300 bg-base-100 p-5 shadow-xl">
          <div className="mb-3 flex size-11 items-center justify-center rounded-xl bg-primary/10">
            <Building2 className="size-5 text-primary" />
          </div>
          <h2 className="text-base font-bold text-base-content">
            Você está mudando de município
          </h2>
          <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-sm text-base-content/70">
            O sistema inteiro passa a ser de
            <b className="inline-flex items-center gap-1 text-base-content">
              <ArrowRight className="size-3.5" />
              {rotulo}
            </b>
          </p>
          {/* O que o usuário PERDE ao seguir. Dizer isto aqui é o que evita a
              pergunta "cadê o que eu estava preenchendo?" do outro lado. */}
          <p className="mt-2 text-[11px] leading-snug text-base-content/50">
            As telas abertas são fechadas e você volta para a tela inicial. Nada
            do município atual continua na tela.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button
              type="button"
              onClick={onCancelar}
              className="rounded-lg px-3 py-1.5 text-sm font-medium text-base-content/70 hover:bg-base-200"
            >
              Cancelar
            </button>
            <button
              type="button"
              onClick={comecar}
              autoFocus
              className="rounded-lg bg-primary px-3.5 py-1.5 text-sm font-semibold text-primary-content hover:opacity-90"
            >
              Entrar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Cinco pontinhos saltitando, um atraso por ponto. A animação vive em
 *  `globals.css` (`pactha-pulo`) junto das outras do projeto — classe montada em
 *  runtime o Tailwind não gera, e o atraso vai inline por isso mesmo. */
function Pontinhos() {
  return (
    <span className="flex items-end gap-1.5" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <span
          key={i}
          className="pactha-pontinho size-2 rounded-full bg-primary"
          style={{ animationDelay: `${i * 90}ms` }}
        />
      ))}
    </span>
  );
}
