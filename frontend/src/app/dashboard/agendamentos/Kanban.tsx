"use client";

/* O KANBAN — em que pé está cada compromisso.
 *
 * ⚠️ AQUI NÃO SE CRIA COMPROMISSO (decisão do dono). O compromisso nasce no
 * calendário porque ele tem DIA E HORA obrigatórios: um cartão criado numa
 * coluna nasceria sem os dois campos que o posicionam na agenda, e ficaria
 * visível só aqui — que é exatamente a linha que some da tela sem sumir do
 * banco.
 *
 * ⭐ AS COLUNAS DIVIDEM A LARGURA, SEMPRE. `repeat(N, minmax(0, 1fr))` com três,
 * quatro ou cinco — nunca rolagem horizontal. É por isso que o teto de cinco
 * existe: a primeira versão usava colunas de largura fixa e sobrava meia tela
 * vazia à direita com três colunas, e faltava tela com cinco. O `minmax(0, ...)`
 * é obrigatório: sem ele, `1fr` é `minmax(auto, 1fr)` e uma demanda longa
 * ESTICA a coluna, trazendo de volta a rolagem que se queria evitar.
 *
 * ⚠️ O ARRASTAR NÃO É A ÚNICA FORMA DE MOVER. Arrastar não funciona com teclado
 * nem com leitor de tela, e é a interação que um toque desastrado dispara sem
 * querer. Cada cartão traz também um seletor de coluna — com ele, mover nunca
 * depende do mouse, e desfazer é escolher de volta.
 *
 * ⚠️ ARRASTE PRÓPRIO, SEM BIBLIOTECA. O projeto não tem lib de DnD (conferido no
 * `package.json`), e trazer uma para inclinar um cartão custaria uma dependência
 * nova nos cinco tenants. O que a lib daria — overlay que segue o cursor,
 * limiar antes de começar, marcador do destino — são as três coisas abaixo, em
 * ~80 linhas de `pointer events`, que é o mesmo mecanismo que aquelas libs usam.
 * O HTML5 `draggable` foi abandonado de propósito: ele não deixa estilizar o
 * fantasma (só um bitmap do navegador), e era o que impedia a inclinação.
 *
 * ⚠️ TODAS AS COLUNAS SE RENOMEIAM E SE COLORIEM — inclusive as três iniciais
 * (mudou em 05/09/2026). O que as fixas ainda não fazem é sumir.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, MessageSquare, Palette, Pencil, Trash2, X } from "lucide-react";

import { BOTAO_SEC, ESTILO_SEC, Vazio } from "@/components/ui/superficies";
import {
  Coluna, Compromisso, CorPaleta, diaBR, estiloDaCor, horarioDe, minutos,
} from "./tipos";

/** Distância em pixels antes de um clique virar arraste. Abaixo disso, a mão
 *  tremendo sobre o botão do mouse moveria cartão sem querer — e a interação
 *  primária do cartão é o CLIQUE, que abre o detalhe. */
const LIMIAR_ARRASTE = 6;

interface Arraste {
  c: Compromisso;
  /** Onde o cursor está agora. */
  x: number;
  y: number;
  /** Distância do canto do cartão até o cursor, para o fantasma não "pular". */
  dx: number;
  dy: number;
  largura: number;
  /** Coluna sob o cursor. */
  sobre: number | null;
}

export default function Kanban({
  itens, colunas, comMunicipio, paleta, onAbrir, onMover,
  onRenomearColuna, onRemoverColuna,
}: {
  itens: Compromisso[];
  colunas: Coluna[];
  comMunicipio: boolean;
  paleta: CorPaleta[];
  onAbrir: (c: Compromisso) => void;
  onMover: (c: Compromisso, colunaId: number) => void;
  onRenomearColuna: (id: number, nome: string, cor: string) => Promise<void>;
  onRemoverColuna: (id: number, quantos: number) => void;
}) {
  const [arraste, setArraste] = useState<Arraste | null>(null);

  const porColuna = useMemo(() => {
    const m = new Map<number, Compromisso[]>();
    colunas.forEach((k) => m.set(k.id, []));
    itens.forEach((c) => m.get(c.coluna_id)?.push(c));
    /* Dentro da coluna, do mais próximo para o mais distante — a mesma ordem da
       agenda. Ordenação manual não entra (documento). */
    m.forEach((l) => l.sort((a, b) =>
      String(a.data).localeCompare(String(b.data))
      || minutos(a.hora_inicio) - minutos(b.hora_inicio) || a.id - b.id));
    return m;
  }, [itens, colunas]);

  /** Onde o cartão arrastado CAI na coluna de destino.
   *
   *  ⚠️ NÃO É ONDE O CURSOR ESTÁ. A ordem dentro da coluna é por data e hora,
   *  não manual: desenhar o vão embaixo do cursor prometeria uma posição que o
   *  cartão não vai ocupar, e ele "pularia" para outro lugar ao soltar. O vão
   *  vai onde a ordenação de fato o coloca. */
  const posicaoDeQueda = useCallback((colunaId: number, c: Compromisso) => {
    const lista = (porColuna.get(colunaId) || []).filter((x) => x.id !== c.id);
    const chave = (x: Compromisso) =>
      `${x.data}T${x.hora_inicio}#${String(x.id).padStart(9, "0")}`;
    const i = lista.findIndex((x) => chave(x) > chave(c));
    return i === -1 ? lista.length : i;
  }, [porColuna]);

  /* ---------------------------------------------------------- o arraste -- */

  const inicio = useRef<{ x: number; y: number; c: Compromisso; r: DOMRect } | null>(null);

  const aoDescer = (e: React.PointerEvent, c: Compromisso) => {
    /* Só o botão principal, e nunca sobre um controle (o seletor de coluna). */
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("select,button")) return;
    inicio.current = {
      x: e.clientX, y: e.clientY, c,
      r: (e.currentTarget as HTMLElement).getBoundingClientRect(),
    };
  };

  const aoMover = (e: React.PointerEvent) => {
    const i = inicio.current;
    if (!i) return;
    const dist = Math.hypot(e.clientX - i.x, e.clientY - i.y);
    if (!arraste && dist < LIMIAR_ARRASTE) return;
    if (!arraste) {
      /* A captura garante que o `pointerup` chegue aqui mesmo se o cursor sair
         do cartão — sem ela, soltar em cima de outra coluna perderia o evento e
         o fantasma ficaria preso na tela. */
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    }
    const sob = document.elementFromPoint(e.clientX, e.clientY);
    const col = sob?.closest<HTMLElement>("[data-coluna]");
    setArraste({
      c: i.c, x: e.clientX, y: e.clientY,
      dx: i.x - i.r.left, dy: i.y - i.r.top, largura: i.r.width,
      sobre: col ? Number(col.dataset.coluna) : null,
    });
  };

  const aoSoltar = (e: React.PointerEvent) => {
    const i = inicio.current;
    inicio.current = null;
    if (!arraste) {
      /* Não passou do limiar: foi um CLIQUE, e clique abre o detalhe. */
      if (i && !(e.target as HTMLElement).closest("select,button")) onAbrir(i.c);
      return;
    }
    if (arraste.sobre && arraste.sobre !== arraste.c.coluna_id) {
      onMover(arraste.c, arraste.sobre);
    }
    setArraste(null);
  };

  /* Esc solta o cartão onde ele estava — a saída de emergência de todo arraste. */
  useEffect(() => {
    if (!arraste) return;
    const tecla = (ev: KeyboardEvent) => {
      if (ev.key === "Escape") { inicio.current = null; setArraste(null); }
    };
    document.addEventListener("keydown", tecla);
    return () => document.removeEventListener("keydown", tecla);
  }, [arraste]);

  if (!colunas.length) return <Vazio>O quadro ainda não tem colunas.</Vazio>;

  return (
    <div className="grid h-full min-h-0 gap-3"
         style={{ gridTemplateColumns: `repeat(${colunas.length}, minmax(0, 1fr))` }}>
      {colunas.map((col) => {
        const daColuna = porColuna.get(col.id) || [];
        const alvo = arraste?.sobre === col.id;
        const queda = alvo && arraste && arraste.c.coluna_id !== col.id
          ? posicaoDeQueda(col.id, arraste.c) : -1;
        return (
          <div key={col.id} className="flex min-w-0 flex-col gap-2">
            <CabecalhoColuna col={col} total={daColuna.length} paleta={paleta}
                             onSalvar={onRenomearColuna}
                             onRemover={() => onRemoverColuna(col.id, daColuna.length)} />
            {/* ⚠️ SEM `onPointerMove` AQUI. Quem escuta é o cartão, que captura o
                ponteiro assim que o arraste começa — a partir daí todo evento vai
                para ele, esteja o cursor onde estiver. Um segundo ouvinte na
                coluna só faria o mesmo `setState` rodar duas vezes por pixel
                enquanto o cursor ainda está sobre o cartão de origem. */}
            <div
              data-coluna={col.id}
              className="bi-scroll min-h-0 flex-1 space-y-2.5 overflow-y-auto rounded-2xl p-2 transition-colors"
              style={{
                background: alvo
                  ? "color-mix(in oklab, var(--bi-accent) 10%, var(--bi-surface-2))"
                  : "var(--bi-surface-2)",
                border: "1px solid var(--bi-line)",
              }}
            >
              {daColuna.length === 0 && queda < 0 && (
                <p className="px-1 py-6 text-center text-[11px]"
                   style={{ color: "var(--bi-faint)" }}>
                  nada nesta coluna
                </p>
              )}
              {daColuna.map((c, i) => (
                <React.Fragment key={c.id}>
                  {queda === i && <Fantasma cor={arraste!.c.cor} />}
                  <Pasta c={c} colunas={colunas} comMunicipio={comMunicipio}
                         noAr={arraste?.c.id === c.id}
                         onPointerDown={(e) => aoDescer(e, c)}
                         onPointerMove={aoMover}
                         onPointerUp={aoSoltar}
                         onAbrir={onAbrir}
                         onMover={onMover} />
                </React.Fragment>
              ))}
              {queda === daColuna.length && <Fantasma cor={arraste!.c.cor} />}
            </div>
          </div>
        );
      })}

      {/* O cartão no ar. `fixed` e sem eventos: ele segue o cursor por cima de
          tudo, e a coluna embaixo continua recebendo o `pointermove`. */}
      {arraste && (
        <div className="ag-arrastando"
             style={{ left: arraste.x - arraste.dx, top: arraste.y - arraste.dy,
                      width: arraste.largura }}>
          <Pasta c={arraste.c} colunas={colunas} comMunicipio={comMunicipio}
                 estatico />
        </div>
      )}
    </div>
  );
}

function Fantasma({ cor }: { cor: string }) {
  return <div className="ag-fantasma h-24" style={estiloDaCor(cor)} aria-hidden="true" />;
}

/* ------------------------------------------------------ cabeçalho da coluna */

/** O chip desgarrado acima da coluna: nome, contador e, ao editar, a cor.
 *
 * ⚠️ AS TRÊS INICIAIS TAMBÉM SE EDITAM (mudou em 05/09/2026). «Solicitada | Em
 * andamento | Concluída» são o ponto de partida, não o vocabulário obrigatório
 * de cinco clientes diferentes. Só o REMOVER continua vedado nelas: apagar a
 * coluna de entrada deixaria sem destino os cartões devolvidos por uma
 * customizada removida. */
function CabecalhoColuna({ col, total, paleta, onSalvar, onRemover }: {
  col: Coluna;
  total: number;
  paleta: CorPaleta[];
  onSalvar: (id: number, nome: string, cor: string) => Promise<void>;
  onRemover: () => void;
}) {
  const [editando, setEditando] = useState(false);
  const [nome, setNome] = useState(col.nome);
  const [cor, setCor] = useState(col.cor);

  const salvar = async () => {
    const n = nome.trim();
    if (!n) { setNome(col.nome); setEditando(false); return; }
    if (n !== col.nome || cor !== col.cor) await onSalvar(col.id, n, cor);
    setEditando(false);
  };
  const cancelar = () => { setNome(col.nome); setCor(col.cor); setEditando(false); };

  if (editando) {
    return (
      <div className="ag-solto ag-solto-cor shrink-0 p-2" style={estiloDaCor(cor)}>
        <div className="flex items-center gap-1">
          <input autoFocus value={nome} maxLength={40}
                 onChange={(e) => setNome(e.target.value)}
                 onKeyDown={(e) => {
                   if (e.key === "Enter") salvar();
                   if (e.key === "Escape") cancelar();
                 }}
                 aria-label={`Nome da coluna ${col.nome}`}
                 className="bi-field h-7 min-w-0 flex-1 px-1.5 text-[12px]" />
          <button type="button" onClick={salvar} aria-label="Salvar"
                  className="rounded p-1 bi-hover" style={{ color: "var(--bi-accent-ink)" }}>
            <Check className="size-3.5" />
          </button>
          <button type="button" onClick={cancelar} aria-label="Cancelar"
                  className="rounded p-1 bi-hover" style={{ color: "var(--bi-muted)" }}>
            <X className="size-3.5" />
          </button>
        </div>
        <div className="mt-1.5 flex items-center gap-1">
          <Palette className="size-3 shrink-0" style={{ color: "var(--bi-muted)" }} />
          <div className="flex flex-wrap gap-1">
            {paleta.map((p) => (
              <button key={p.hex} type="button" title={p.nome} aria-label={p.nome}
                      aria-pressed={cor === p.hex} onClick={() => setCor(p.hex)}
                      className="size-4 rounded-full transition-transform hover:scale-110"
                      style={{ background: p.hex,
                               outline: cor === p.hex ? "2px solid var(--bi-text)" : "none",
                               outlineOffset: 1.5 }} />
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="ag-solto ag-solto-cor group flex shrink-0 items-center gap-1.5 px-3 py-2"
         style={estiloDaCor(col.cor)}>
      <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold">
        {col.nome}
      </span>
      <span className="rounded-full px-1.5 text-[11px] tabular-nums"
            style={{ background: "color-mix(in oklab, var(--bi-text) 8%, transparent)" }}>
        {total}
      </span>
      <button type="button" onClick={() => setEditando(true)}
              aria-label={`Renomear e colorir a coluna ${col.nome}`}
              className="rounded p-1 opacity-0 transition-opacity bi-hover focus-visible:opacity-100 group-hover:opacity-100">
        <Pencil className="size-3" />
      </button>
      {!col.fixa && (
        <button type="button" onClick={onRemover}
                aria-label={`Remover a coluna ${col.nome}`}
                className="rounded p-1 opacity-0 transition-opacity bi-hover focus-visible:opacity-100 group-hover:opacity-100"
                style={{ color: "var(--bi-crit-ink)" }}>
          <Trash2 className="size-3" />
        </button>
      )}
    </div>
  );
}

/* --------------------------------------------------------- cartão em pasta */

/** O cartão no formato de PASTA (`estilo-pastas.jpg`): a aba recortada no alto,
 *  na cor da demanda, e o corpo colado nela — os dois lêem como uma peça só. */
function Pasta({
  c, colunas, comMunicipio, noAr, estatico, onMover, onAbrir,
  onPointerDown, onPointerMove, onPointerUp,
}: {
  c: Compromisso;
  colunas: Coluna[];
  comMunicipio: boolean;
  /** Este é o cartão que está sendo arrastado: fica apagado no lugar de origem. */
  noAr?: boolean;
  /** A cópia que segue o cursor — sem eventos e sem controles. */
  estatico?: boolean;
  onMover?: (c: Compromisso, colunaId: number) => void;
  /** Só para o teclado — o ponteiro entra por `onPointerUp`, que distingue
   *  clique de arraste. */
  onAbrir?: (c: Compromisso) => void;
  onPointerDown?: (e: React.PointerEvent) => void;
  onPointerMove?: (e: React.PointerEvent) => void;
  onPointerUp?: (e: React.PointerEvent) => void;
}) {
  return (
    /* ⚠️ O CARTÃO É UM ALVO DE TECLADO, e não só de ponteiro. A versão anterior
       tinha um `<button>` por dentro; com o arraste próprio, quem escuta o
       clique é a caixa toda — e sem `role`/`tabIndex`/`onKeyDown` ela sairia da
       ordem de tabulação, deixando o kanban inteiro inalcançável por teclado.
       A cópia que segue o cursor (`estatico`) fica fora: dois cartões com o
       mesmo rótulo na ordem de tabulação é pior que nenhum. */
    <div style={estiloDaCor(c.cor)}
         role={estatico ? undefined : "button"}
         tabIndex={estatico ? undefined : 0}
         aria-label={estatico ? undefined : `Abrir ${c.demanda}`}
         onKeyDown={estatico ? undefined : (e) => {
           if (e.key === "Enter" || e.key === " ") {
             e.preventDefault();
             onAbrir?.(c);
           }
         }}
         onPointerDown={onPointerDown}
         onPointerMove={onPointerMove}
         onPointerUp={onPointerUp}
         className={`select-none transition-opacity duration-150 ease-out ${
           estatico ? "" : "cursor-grab active:cursor-grabbing"} ${
           noAr ? "ag-origem" : ""}`}>
      {/* A ABA. Leva o dia e a hora — é o que distingue dois cartões da mesma
          coluna à distância, e o que a pasta de arquivo teria escrito na guia. */}
      <div className="ag-pasta-aba flex w-[62%] items-center gap-1 px-2 py-0.5 text-[10px] font-semibold tabular-nums">
        <span className="truncate">{diaBR(c.data)} · {horarioDe(c)}</span>
      </div>
      <div className="ag-pasta-corpo p-2">
        <p className="text-[12.5px] font-semibold leading-snug">{c.demanda}</p>
        <p className="mt-1 truncate text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {c.solicitante || "sem solicitante"}
        </p>
        {comMunicipio && (
          <p className="truncate text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {c.municipio}{c.uf ? ` - ${c.uf}` : ""}
          </p>
        )}
        <div className="mt-2 flex items-center gap-2 border-t pt-1.5"
             style={{ borderColor: "var(--bi-line)" }}>
          <span className="inline-flex items-center gap-1 text-[10px]"
                style={{ color: "var(--bi-faint)" }}>
            <MessageSquare className="size-3" /> {c.anotacoes_qtd}
          </span>
          {!estatico && onMover && (
            <select value={c.coluna_id} aria-label={`Coluna de ${c.demanda}`}
                    onChange={(e) => onMover(c, Number(e.target.value))}
                    className="bi-field ml-auto h-6 max-w-[9rem] px-1 text-[10px]">
              {colunas.map((k) => (
                <option key={k.id} value={k.id}>{k.nome}</option>
              ))}
            </select>
          )}
        </div>
      </div>
    </div>
  );
}

/** O botão de criar coluna, que mora na toolbar da aba e some no teto.
 *
 * ⚠️ SAIU DE DENTRO DO QUADRO (pedido do dono). Era uma quarta "coluna" cinza
 * tracejada ao lado das três — e com ela o quadro nunca dividia a largura por
 * igual, porque havia sempre um bloco a mais disputando espaço. Uma ação de
 * configuração não é uma coluna do quadro. */
export function BotaoNovaColuna({ colunas, max, maxCustomizadas, onCriar }: {
  colunas: Coluna[];
  max: number;
  maxCustomizadas: number;
  onCriar: (nome: string) => Promise<void>;
}) {
  const [abrindo, setAbrindo] = useState(false);
  const [nome, setNome] = useState("");
  const customizadas = colunas.filter((c) => !c.fixa).length;
  if (colunas.length >= max || customizadas >= maxCustomizadas) return null;

  const criar = async () => {
    const n = nome.trim();
    if (!n) return;
    await onCriar(n);
    setNome(""); setAbrindo(false);
  };

  if (!abrindo) {
    return (
      <button type="button" onClick={() => setAbrindo(true)}
              className={BOTAO_SEC} style={ESTILO_SEC}>
        + Coluna
      </button>
    );
  }
  return (
    <span className="inline-flex items-center gap-1">
      <input autoFocus value={nome} maxLength={40}
             onChange={(e) => setNome(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "Enter") criar();
               if (e.key === "Escape") { setAbrindo(false); setNome(""); }
             }}
             placeholder="Nome da coluna" aria-label="Nome da coluna nova"
             className="bi-field h-8 w-40 px-2 text-[12px]" />
      <button type="button" onClick={criar} disabled={!nome.trim()}
              className={BOTAO_SEC} style={ESTILO_SEC}>
        <Check className="size-3.5" /> Criar
      </button>
      <button type="button" className="text-[11px] underline"
              style={{ color: "var(--bi-muted)" }}
              onClick={() => { setAbrindo(false); setNome(""); }}>
        cancelar
      </button>
    </span>
  );
}
