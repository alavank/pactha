"use client";
// AS PEÇAS DA IDENTIDADE — a gramática visual do sistema inteiro.
//
// Por que existem: o Painel de Indicadores é bonito e calmo, e o dono decidiu
// que ele vira a referência do produto todo. Mas o que faz o Painel funcionar
// NÃO é o formato do cartão — é ele ter só duas ou três peças, reusadas em
// toda parte. As telas operacionais tinham o oposto: 41 cartões montados à mão,
// cinco classes de sombra e seis raios de canto diferentes convivendo.
//
// Se as telas virassem cartão sem peça compartilhada, em seis meses haveria 32
// cartões ligeiramente diferentes e estaríamos de volta ao ponto de partida.
//
// ⚠️ ESTAS PEÇAS SÃO NOVAS, NÃO SÃO AS DO PAINEL. `components/bi/` fica
// intocado de propósito: ele é a inspiração, e mexer nele para "reaproveitar"
// arriscaria justamente a tela que motivou a mudança. A duplicação é pequena e
// consciente; quando o sistema estiver migrado e estável, o Painel pode adotar
// estas — nunca o contrário.
//
// Os tokens `--bi-*` agora vivem em `:root` (ver globals.css), então valem aqui
// sem precisar do `.bi-skin`.
import * as React from "react";

// ---------------------------------------------------------------------------
// Bloco — o cartão. Equivale ao `Painel` do BI.
// ---------------------------------------------------------------------------

export function Bloco({
  children,
  className = "",
  plano = false,
}: {
  children: React.ReactNode;
  className?: string;
  /** `plano` = a variante interna, sem sombra e com raio menor (itens de lista
   *  dentro de um bloco). É o `bi-card-flat` do Painel. */
  plano?: boolean;
}) {
  return (
    <div className={`${plano ? "bi-card-flat" : "bi-card"} flex flex-col ${className}`}>
      {children}
    </div>
  );
}

/** Cabeçalho do bloco: ícone, título, subtítulo cinza e um valor à direita.
 *  É exatamente a estrutura que o Painel usa em todo painel e em todo grupo. */
export function BlocoHead({
  icon: Icon,
  titulo,
  sub,
  right,
  className = "",
}: {
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  titulo: React.ReactNode;
  sub?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`mb-2.5 flex items-start gap-2.5 ${className}`}>
      {Icon && (
        <span
          className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full"
          style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
        >
          <Icon className="size-3.5" />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <div className="bi-title text-[14px] leading-tight">{titulo}</div>
        {sub && (
          <div className="mt-0.5 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
            {sub}
          </div>
        )}
      </div>
      {right && <div className="shrink-0 text-right">{right}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Selo — o badge. Cinza sobre cinza por padrão.
// ---------------------------------------------------------------------------

/** O selo do Painel usa `--bi-line` de fundo: a MESMA cor das divisórias.
 *  Ele classifica sem gritar. É o oposto do sistema hoje, onde qualquer selo
 *  de situação vinha pintado de violeta ou verde — e com dez selos coloridos
 *  numa linha, nenhum deles significa mais nada.
 *
 *  Cor só entra em `tom` quando a informação é de fato um alerta. */
export function Selo({
  children,
  tom = "neutro",
  title,
}: {
  children: React.ReactNode;
  tom?: "neutro" | "ok" | "atencao" | "critico" | "acento";
  title?: string;
}) {
  const estilo: React.CSSProperties =
    tom === "neutro"
      ? { background: "var(--bi-line)", color: "var(--bi-muted)" }
      : tom === "acento"
        ? { background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)" }
        : {
            background: `color-mix(in oklab, var(--bi-${
              tom === "ok" ? "ok" : tom === "atencao" ? "warn" : "crit"
            }) 14%, transparent)`,
            color: `var(--bi-${tom === "ok" ? "ok-ink" : tom === "atencao" ? "warn-ink" : "crit-ink"})`,
          };
  return (
    <span
      title={title}
      className="inline-flex shrink-0 items-center rounded px-1.5 py-px text-[10px] font-medium leading-[1.5]"
      style={estilo}
    >
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ItemLinha — o tijolo da lista.
// ---------------------------------------------------------------------------

/** Duas linhas: título à esquerda com valor à direita, e a meta em cinza claro
 *  embaixo. É o mesmo item que o Painel usa nas Propostas do FNS e nos
 *  lançamentos do parlamentar. */
export function ItemLinha({
  titulo,
  valor,
  meta,
  children,
  onClick,
  acao,
  className = "",
}: {
  titulo: React.ReactNode;
  valor?: React.ReactNode;
  meta?: React.ReactNode;
  /** Conteúdo extra abaixo da meta — tipicamente `<Campos>`. */
  children?: React.ReactNode;
  onClick?: () => void;
  /** Botão(ões) à direita, fora da área clicável. */
  acao?: React.ReactNode;
  className?: string;
}) {
  const corpo = (
    <>
      <div className="flex items-baseline gap-3">
        <span className="min-w-0 flex-1 text-[13px] font-medium leading-snug">{titulo}</span>
        {valor != null && (
          <span className="bi-num shrink-0 text-[13px] leading-snug">{valor}</span>
        )}
      </div>
      {meta && (
        <div
          className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] leading-snug"
          style={{ color: "var(--bi-faint)" }}
        >
          {meta}
        </div>
      )}
      {children}
    </>
  );
  return (
    <li className={`bi-card-flat px-3 py-2.5 ${className}`}>
      <div className="flex items-start gap-2">
        {onClick ? (
          <button type="button" onClick={onClick} className="min-w-0 flex-1 text-left">
            {corpo}
          </button>
        ) : (
          <div className="min-w-0 flex-1">{corpo}</div>
        )}
        {acao && <div className="flex shrink-0 items-center gap-1">{acao}</div>}
      </div>
    </li>
  );
}

/** A lista de itens: vão entre eles, sem borda e sem divisória.
 *  O que separa é o espaço e o fundo levemente diferente — tabela é grade de
 *  linhas, esta identidade é pilha de blocos macios. */
export function Lista({ children, className = "" }: {
  children: React.ReactNode; className?: string;
}) {
  return <ul className={`flex flex-col gap-1.5 ${className}`}>{children}</ul>;
}

// ---------------------------------------------------------------------------
// Campos — a grade alinhada. A peça que faz cartão substituir tabela.
// ---------------------------------------------------------------------------

export interface Campo {
  rotulo: string;
  valor: React.ReactNode;
  /** Destaque quando o campo é o que exige ação (prazo estourado, não pago). */
  tom?: "normal" | "ok" | "atencao" | "critico";
  title?: string;
}

/** A linha de números do cartão, em POSIÇÕES FIXAS.
 *
 *  Esta peça é a razão de um cartão poder substituir uma tabela de 14 colunas.
 *  A meta do Painel é escrita como frase corrida ("2026 · PROGRAMA · pago R$ 0"),
 *  o que é lindo com cinco campos e o valor à direita. Mas frase corrida MATA a
 *  varredura vertical: o "% pago" do primeiro item cai numa posição e o do
 *  segundo em outra, porque o título acima tem comprimento diferente — e a
 *  equipe perde justamente o gesto que a planilha permitia, descer o olho por
 *  uma coluna.
 *
 *  Aqui as colunas têm largura igual em TODOS os cartões, então o olho desce
 *  como desceria numa tabela. Sem linha de grade, sem borda e sem cor. */
export function Campos({ campos, cols }: { campos: Campo[]; cols?: number }) {
  if (!campos.length) return null;
  const n = cols ?? campos.length;
  return (
    <div
      className="mt-2 grid gap-x-3 gap-y-1.5 border-t pt-2"
      style={{
        gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))`,
        borderColor: "var(--bi-line)",
      }}
    >
      {campos.map((c, i) => (
        <div key={i} className="min-w-0" title={c.title}>
          <div
            className="truncate text-[9px] uppercase tracking-wide"
            style={{ color: "var(--bi-faint)" }}
          >
            {c.rotulo}
          </div>
          <div
            className="bi-num truncate text-[11px] leading-tight"
            style={{
              color:
                c.tom === "critico" ? "var(--bi-crit-ink)"
                : c.tom === "atencao" ? "var(--bi-warn-ink)"
                : c.tom === "ok" ? "var(--bi-ok-ink)"
                : "var(--bi-text)",
            }}
          >
            {c.valor}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Numero — o KPI do topo.
// ---------------------------------------------------------------------------

export function Numero({
  icon: Icon,
  rotulo,
  valor,
  sub,
  tom = "neutro",
  onClick,
}: {
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  rotulo: string;
  valor: React.ReactNode;
  sub?: React.ReactNode;
  tom?: "neutro" | "acento" | "ok" | "atencao" | "critico";
  onClick?: () => void;
}) {
  const cor =
    tom === "acento" ? "var(--bi-accent-ink)"
    : tom === "ok" ? "var(--bi-ok-ink)"
    : tom === "atencao" ? "var(--bi-warn-ink)"
    : tom === "critico" ? "var(--bi-crit-ink)"
    : "var(--bi-text)";
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      {...(onClick ? { type: "button" as const, onClick } : {})}
      className={`bi-card px-4 py-3.5 text-left ${onClick ? "transition-colors hover:brightness-[0.98]" : ""}`}
    >
      <div className="flex items-center gap-2">
        {Icon && <Icon className="size-4 shrink-0" style={{ color: cor }} />}
        <span className="text-[11px] leading-tight" style={{ color: "var(--bi-muted)" }}>
          {rotulo}
        </span>
      </div>
      <div className="bi-num mt-1.5 text-[22px] leading-none" style={{ color: cor }}>
        {valor}
      </div>
      {sub && (
        <div className="mt-1 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
          {sub}
        </div>
      )}
    </Tag>
  );
}

// ---------------------------------------------------------------------------

export function Vazio({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="bi-card-flat px-4 py-10 text-center text-[12px]"
      style={{ color: "var(--bi-faint)" }}
    >
      {children}
    </div>
  );
}
