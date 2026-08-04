"use client";
// A TRAVESSIA ENTRE MUNICÍPIOS.
//
// Numa assessoria os municípios são CLIENTES DIFERENTES. Trocar de município
// não é filtrar uma lista: é entrar noutro ambiente. Esta peça existe para dizer
// isso em voz alta, e para dar ao sistema a janela em que ele desmonta a tela
// anterior antes de pintar a próxima.
//
// São dois momentos, e a diferença entre eles importa:
//   1. O AVISO, que pode ser cancelado. Enquanto ele está aberto nada mudou —
//      quem clicou por engano no seletor sai sem consequência.
//   2. A TRAVESSIA, que não pode. Depois do OK o município já é outro, e voltar
//      atrás no meio deixaria a tela remontando para um destino que o usuário
//      acabou de desistir.
import { useEffect, useState } from "react";
import { ArrowRight, Building2 } from "lucide-react";

/** ~800ms: cabe a sensação de mudança e cobre a primeira busca da tela inicial,
 *  sem virar espera. Acima disso, quem troca de município várias vezes seguidas
 *  passa a esperar o sistema em vez de usá-lo. */
const DURACAO_MS = 800;

export function TransicaoMunicipio({
  rotulo, onConfirmar, onCancelar, onConcluir,
}: {
  /** O nome do destino, como aparece no seletor ("Monte Sião - MG"). */
  rotulo: string;
  onConfirmar: () => void;
  onCancelar: () => void;
  onConcluir: () => void;
}) {
  const [atravessando, setAtravessando] = useState(false);

  useEffect(() => {
    if (!atravessando) return;
    const t = setTimeout(onConcluir, DURACAO_MS);
    return () => clearTimeout(t);
  }, [atravessando, onConcluir]);

  /* Esc cancela — mas só no AVISO. Durante a travessia a troca já aconteceu, e
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

  return (
    <div
      className="fixed inset-0 z-[70] grid place-items-center bg-base-300/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-live="polite"
      aria-label={atravessando ? `Entrando em ${rotulo}` : `Mudar para ${rotulo}`}
    >
      {atravessando ? (
        <div className="flex flex-col items-center gap-5 pactha-travessia">
          <span className="text-lg font-bold tracking-tight text-base-content">PACTHA</span>
          <Pontinhos />
          <span className="text-sm text-base-content/70">
            Entrando em <b className="text-base-content">{rotulo}</b>
          </span>
        </div>
      ) : (
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
