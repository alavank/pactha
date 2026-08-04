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
import { createPortal } from "react-dom";

// ---------------------------------------------------------------------------
// Bloco — o cartão. Equivale ao `Painel` do BI.
// ---------------------------------------------------------------------------

export function Bloco({
  children,
  className = "",
  style,
  plano = false,
}: {
  children: React.ReactNode;
  className?: string;
  /** Fundo/borda próprios — para o cartão INTEIRO virar alerta, e não só o
   *  texto dentro dele. Usa token, nunca cor crua. */
  style?: React.CSSProperties;
  /** `plano` = a variante interna, sem sombra e com raio menor (itens de lista
   *  dentro de um bloco). É o `bi-card-flat` do Painel. */
  plano?: boolean;
}) {
  return (
    <div className={`${plano ? "bi-card-flat" : "bi-card"} flex flex-col ${className}`} style={style}>
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

/** O tom de um rótulo de situação/status — UMA regra para o sistema inteiro.
 *
 *  Nasceu copiada em cinco telas, e no dia em que foi medida já divergia:
 *  "aprovado" era `ok` em quatro e neutro na quinta, "tramitando" era atenção
 *  em uma e neutro nas outras. Duas telas classificando a mesma palavra de
 *  formas diferentes é pior do que nenhuma classificação — o gestor aprende a
 *  não confiar na cor.
 *
 *  A regra é deliberadamente ESTREITA. Cor aqui não é enfeite: é o que sobra
 *  depois que o resto virou cinza, e por isso só ganha cor o que pede ação.
 *  Estado normal de um convênio vivo ("em execução", "vigente", "ciente") é
 *  cinza de propósito — se o normal for colorido, a cor não informa nada.
 *
 *  Os termos são fragmentos sem acento e sem terminação, porque as fontes
 *  escrevem diferente: "Cancelado", "CANCELADA", "cancelamento". */
export function situacaoTom(
  s?: string | null,
): "neutro" | "ok" | "atencao" | "critico" {
  const t = (s || "")
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
  // Exige ação corretiva, ou o dinheiro parou.
  /* `nao habilitada` fica AQUI, e não cai na regra genérica de negação abaixo:
     ela rebaixaria para atenção, e não estar habilitada a receber recurso é
     impedimento, não pendência. Foi escalado de propósito. */
  if (/(cancelad|cancelament|rescindid|rejeitad|indeferid|impedid|inadimpl|anulad|nao habilitada|vencid)/.test(t))
    return "critico";
  // Depende de alguém: está esperando análise, documento ou decisão.
  if (/(pendente|analise|aguardando|suspens|complementa|diligencia|tramit|elaborac)/.test(t))
    return "atencao";
  // Chegou ao fim bem — SE não estiver negado.
  //
  // A regra era cega a negação: "NÃO CONCLUÍDO" casa com `conclu` e saía
  // VERDE. A prova de que a forma negada existe nesta base estava dentro da
  // própria regra — `nao habilitada` tinha sido acrescentado à mão na lista
  // crítica, um remendo para UM caso. Os status vêm de portais externos
  // (SIGCON, TransfereGov, FNS), então não dá para enumerá-los aqui.
  //
  // Negado vira ATENÇÃO e não crítico de propósito: "não concluído" é obra em
  // andamento, não inadimplência. O que é recusa de verdade já tem palavra
  // própria na lista de cima (`rejeitad`, `indeferid`).
  const bom = /(conclu|aprovad|homologad|selecionad|empenhad|liquidad|adimplent|encerrad|prestac)/.exec(t);
  if (bom) {
    const antes = t.slice(Math.max(0, bom.index - 14), bom.index);
    return /\b(nao|sem|nunca|falta|deixou de)\s+\S{0,8}\s*$/.test(antes) ? "atencao" : "ok";
  }
  return "neutro";
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
  expandido,
  acao,
  className = "",
}: {
  titulo: React.ReactNode;
  valor?: React.ReactNode;
  meta?: React.ReactNode;
  /** Conteúdo extra abaixo da meta — tipicamente `<Campos>`. */
  children?: React.ReactNode;
  onClick?: () => void;
  /** Quando o item ABRE algo: o leitor de tela anuncia "recolhido/expandido"
   *  e a seta deixa de ser só um desenho. */
  expandido?: boolean;
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
          <button type="button" onClick={onClick} className="min-w-0 flex-1 text-left"
                  {...(expandido !== undefined ? { "aria-expanded": expandido } : {})}>
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
  /** Destaque quando o campo é o que exige ação (prazo estourado, não pago).
   *
   *  Aceita "neutro" e "normal" como sinônimos de propósito: `Selo` fala
   *  "neutro" e este componente nasceu falando "normal", e uma tela já teve de
   *  escrever um adaptador só para traduzir entre os dois. Vocabulário diferente
   *  para o mesmo conceito é defeito da peça, não da tela que a usa. */
  tom?: "normal" | "neutro" | "ok" | "atencao" | "critico";
  title?: string;
  /** Quantas colunas o campo ocupa. Nasceu para os modais de detalhe: lá, nove
   *  campos são texto longo (objeto, concedente, responsáveis) e numa coluna de
   *  1/4 saem truncados ou em três linhas. Largura é CARGA ÚTIL nesses casos,
   *  não estilo. Fora do detalhe, o normal é não usar: colunas de largura igual
   *  em todos os cartões é o que mantém a varredura vertical viva. */
  span?: number;
  /** Quebra a linha em vez de truncar, sem precisar ocupar mais colunas.
   *  Para texto que é frase e não rótulo. */
  quebra?: boolean;
  /** Monoespaçada. Para IDENTIFICADOR (nº SIAFI, nº processo, CNPJ), onde o
   *  alinhamento caractere a caractere é o que permite comparar dois números
   *  parecidos. `bi-num` é tabular, o que serve a valor; não serve a código.
   *  Usa `.bi-id` e NÃO `font-mono`: neste projeto `--font-mono` aponta para
   *  Nunito, então `font-mono` não entrega monoespaçada nenhuma. */
  mono?: boolean;
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
      /* `bi-campos` e nao `gridTemplateColumns` inline: estilo inline nao aceita
         media query, e sem breakpoint quatro colunas valiam em QUALQUER largura.
         No celular isso dava colunas de ~65px em que ate o RÓTULO era truncado —
         "VALOR DE CUSTEIO" e "VALOR DE INVESTIMENTO" saíam cortados no mesmo
         prefixo e ficavam indistinguíveis. A grade que estas peças
         substituíram colapsava para uma coluna abaixo de 768px; esta agora
         colapsa para duas, que é o mesmo gesto. */
      className="bi-campos mt-2 gap-x-3 gap-y-1.5 border-t pt-2"
      style={{
        ["--campos-sm" as string]: Math.min(n, 2),
        ["--campos-md" as string]: Math.min(n, 3),
        ["--campos-lg" as string]: n,
        borderColor: "var(--bi-line)",
      } as React.CSSProperties}
    >
      {campos.map((c, i) => {
        const largo = !!(c.span && c.span > 1);
        /* O `title` deixa de ser opcional na prática: a célula trunca por
           desenho, e valor cortado sem tooltip é dado APAGADO. Quem não passa
           `title` ganha um derivado do próprio valor. */
        /* So onde a celula PODE truncar. Derivar em toda celula fazia o
           navegador abrir tooltip repetindo o que ja esta na tela — barulho
           que nao existia antes desta peca. Onde o valor quebra linha
           (`quebra` ou `span`), nada e cortado e nao ha o que recuperar. */
        const dica =
          c.title ??
          (!largo && !c.quebra && (typeof c.valor === "string" || typeof c.valor === "number")
            ? `${c.rotulo}: ${c.valor}`
            : undefined);
        return (
        <div
          key={i}
          className="min-w-0"
          title={dica}
          /* O clamp precisa ser RESPONSIVO. Escrito em style inline contra
             `n` (a contagem de desktop), um `span: 3` numa grade que a 390px
             tem 2 colunas fazia o CSS Grid criar uma coluna IMPLICITA: medido,
             a grade computava tres colunas DESIGUAIS. Passa a variavel e deixa
             o `min()` do CSS resolver por faixa (ver `.bi-campos > [data-span]`
             em globals.css). */
          {...(largo ? { "data-span": "" } : {})}
          style={largo ? ({ ["--span" as string]: c.span } as React.CSSProperties) : undefined}
        >
          <div
            className="truncate text-[9px] uppercase tracking-wide"
            style={{ color: "var(--bi-faint)" }}
          >
            {c.rotulo}
          </div>
          <div
            className={`text-[11px] leading-tight ${c.mono ? "bi-id" : "bi-num"} ${
              largo || c.quebra ? "break-words" : "truncate"
            }`}
            style={{
              color:
                c.tom === "critico" ? "var(--bi-crit-ink)"
                : c.tom === "atencao" ? "var(--bi-warn-ink)"
                : c.tom === "ok" ? "var(--bi-ok-ink)"
                : "var(--bi-text)",   // "normal" e "neutro" caem aqui
            }}
          >
            {c.valor}
          </div>
        </div>
        );
      })}
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
      className={`bi-card px-4 py-3.5 text-left ${onClick ? "transition-colors bi-hover" : ""}`}
    >
      <div className="flex items-center gap-2">
        {Icon && <Icon className="size-4 shrink-0" style={{ color: cor }} />}
        <span className="text-[11px] leading-tight" style={{ color: "var(--bi-muted)" }}>
          {rotulo}
        </span>
      </div>
      <div className="bi-num mt-1.5 text-[22px] leading-none break-words" style={{ color: cor }}>
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

// ---------------------------------------------------------------------------
// Botões
// ---------------------------------------------------------------------------

/** Os dois botões da identidade, como CLASSE e não componente, porque metade
 *  dos usos é `<a>` e não `<button>`.
 *
 *  O sólido é QUASE PRETO, não colorido — é assim que o Painel faz (18,53 de
 *  contraste). Um botão menta de exibição sobre branco daria 2,55 e o rótulo
 *  ficaria ilegível; e mais: se o botão principal for da cor do acento, o
 *  acento deixa de significar "olhe aqui". */
export const BOTAO_CTA =
  "inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[12px] font-semibold transition-opacity hover:opacity-90 disabled:opacity-60";
export const ESTILO_CTA: React.CSSProperties = {
  background: "var(--bi-cta)",
  color: "var(--bi-cta-ink)",
};

/** Botão MIÚDO de ação em lote ("Marcar todas", "Limpar", "Marcar seção").
 *
 *  Mesma gramática do chip desmarcado: contorno na linha de divisória e tinta
 *  cinza. Não é um CTA — é um atalho, e atalho que compete com o botão de
 *  salvar faz o olho parar no lugar errado.
 *
 *  Nasceu na tela de Usuários e subiu para cá quando a tela de permissões
 *  passou a precisar do mesmo botão: dois botõezinhos "quase iguais" em duas
 *  telas que abrem uma da outra é exatamente a divergência que este arquivo
 *  existe para evitar. */
export function AcaoMini({
  onClick, disabled, children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-full border px-2 py-0.5 text-[10px] transition-colors hover:bg-[var(--bi-surface-2)] disabled:opacity-40"
      style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}
    >
      {children}
    </button>
  );
}

/** Secundário: superfície com a linha de divisória por borda. */
export const BOTAO_SEC =
  "inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[12px] font-semibold transition-colors bi-hover disabled:opacity-60";
/** Miúdo, para a coluna de ações de um item de lista. */
export const BOTAO_ACAO =
  "inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[11px] font-medium transition-colors bi-hover disabled:opacity-60";
export const ESTILO_SEC: React.CSSProperties = {
  background: "var(--bi-surface)",
  border: "1px solid var(--bi-line)",
  color: "var(--bi-text)",
};

// ===========================================================================
// SOBREPOSIÇÃO — modal, abas, grade densa e etapas.
//
// Estas quatro chegaram depois das de cima, e por um motivo específico: quando
// as telas foram migradas, os MODAIS ficaram para trás, e havia CINCO desenhos
// de modal convivendo no produto — a primitiva `ui/dialog`, o `PainelModal` do
// FNS, `bi-card` cru em Usuários, um `Modal` local em TransfereGov-CNPJ e divs
// soltas em mais dois lugares. É exatamente o problema que o cabeçalho deste
// arquivo descreve, repetido uma camada acima.
//
// ONDE ISSO ESTÁ HOJE — e este parágrafo existe porque a versão anterior dele
// falava dos cinco no passado, como se todos tivessem sido eliminados, quando
// três ainda estavam vivos. Comentário que descreve a intenção em vez do
// estado é pior que nenhum: ele impede a próxima pessoa de procurar.
//   ✔ eliminados: `PainelModal`/`CabecalhoModal` do FNS, `bi-card` cru em
//     Usuários, o `Modal` local de TransfereGov-CNPJ, e as divs soltas.
//   ✖ SOBRA UM: `ui/dialog` (Base UI), usado só pelo Cofre. Não foi convertido
//     de propósito — é a tela de senhas, e trocar a primitiva mexe em foco e
//     em fechamento numa superfície onde o dono pediu mudança só visual. O véu
//     dele já foi corrigido (`bg-neutral` invertia no escuro).
//   · `ui/sheet` continua, e é outra coisa: gaveta lateral do menu no celular.
//
// Nada aqui é invenção: `Modal`/`ModalHead`/`Secao` são o `PainelModal`/
// `CabecalhoModal`/`Secao` que já estavam em produção no modal do FNS,
// promovidos para cá; `Abas` é o `SegTabs` do Painel; `Grade` é a grade de
// exigências do CAUC; `Etapas` é o stepper de 12 etapas do FNS.
// ===========================================================================

/** As caixas ABERTAS, na ordem em que abriram. Existe para o teclado saber qual
 *  modal está por cima quando um abre de dentro do outro (`nivel={2}`) — ver a
 *  nota no ouvinte de tecla. Módulo e não estado: é uma só para o app inteiro,
 *  como o próprio empilhamento na tela. */
const pilhaDeModais: HTMLElement[] = [];

/** A sobreposição inteira: véu, caixa, tecla Esc e clique fora.
 *
 *  O véu é `bg-black/50` LITERAL, e isso importa: o que estava lá era
 *  `bg-neutral/50`, e `neutral` inverte com o tema — vale quase preto no claro
 *  e #f1f4f2 no escuro. Ou seja, no tema escuro o "escurecedor" era um véu
 *  BRANCO 255× mais claro que a página. Estava assim em quatro lugares.
 *
 *  A rolagem fica DENTRO da caixa, nunca no véu: é o que permite cabeçalho e
 *  barra de abas ficarem parados enquanto o conteúdo corre. */
export function Modal({
  aberto,
  onFechar,
  maxW,
  nivel = 1,
  superficie = false,
  rotulo,
  esc = true,
  podeFechar,
  children,
}: {
  aberto: boolean;
  onFechar: () => void;
  /** `max-w-*` LITERAL. O Tailwind só gera a classe se ela aparecer escrita no
   *  código, então ela vem do chamador — montar `max-w-${x}` produz um modal
   *  sem largura máxima, esparramado. Escada: `max-w-md` (confirmação),
   *  `max-w-lg` (formulário), `max-w-4xl` (detalhe), `max-w-5xl` (detalhe com
   *  abas e grades). */
  maxW: string;
  /** 2 = modal aberto de dentro de outro modal. Sem isso o segundo nível
   *  renderiza SOB o véu do primeiro: fica clicável e invisível. */
  nivel?: 1 | 2;
  /** Caixa branca em vez do fundo da página. Só para FORMULÁRIO ou mensagem
   *  curta. Num modal de detalhe — cujo corpo é uma pilha de `Bloco` brancos —
   *  o fundo tem que ser `--bi-bg`, o mesmo da página, senão a hierarquia
   *  fundo → bloco → item vira branco sobre branco e tudo achata. */
  superficie?: boolean;
  /** Nome do diálogo para leitor de tela. A primitiva que estas peças
   *  substituíram exigia um `DialogTitle`, e ao trocá-la o nome sumiu: o leitor
   *  passou a anunciar só "diálogo". Como o título visível quase sempre serve,
   *  o padrão é herdá-lo do `ModalHead`; `rotulo` é para quando não serve. */
  rotulo?: string;
  /** Esc fecha. */
  esc?: boolean;
  /** Consultado nas TRÊS saídas — Esc, clique no véu e o X do `ModalHead`.
   *
   *  A primeira tentativa disto foi `esc={false}` quando havia formulário
   *  aberto, e resolvia um terço do problema: o clique fora e o X continuavam
   *  descartando o que a pessoa digitou, sem perguntar. E o gatilho era o
   *  errado — bastava ABRIR o formulário para o Esc parar de funcionar, mesmo
   *  vazio. Aqui quem decide é o chamador, que sabe se há algo a perder. */
  podeFechar?: () => boolean;
  children: React.ReactNode;
}) {
  const idTitulo = React.useId();
  const caixa = React.useRef<HTMLDivElement>(null);

  /* O callback vive num REF, e as dependências dos efeitos abaixo NÃO o
     incluem. Isso não é preciosismo — a versão anterior tinha `onFechar` nas
     deps, e como todo chamador passa uma arrow inline (`() => setAberto(false)`),
     a identidade mudava a cada render. Efeito colateral: o efeito rodava o
     cleanup e reexecutava a cada TECLA digitada dentro do modal, e como ele
     chamava `caixa.current.focus()` no corpo, o foco saía do campo. O
     formulário de criar Service Token aceitava UM CARACTERE POR CLIQUE. */
  const fecharRef = React.useRef(onFechar);
  const podeRef = React.useRef(podeFechar);
  /* Atualizados em EFEITO e não no corpo: escrever em ref durante o render
     quebra com renderização concorrente (o React pode descartar um render pela
     metade) — e o lint acusa. Sem deps: roda depois de todo render, que é
     exatamente o que a ideia de "sempre o mais recente" pede. */
  React.useEffect(() => {
    fecharRef.current = onFechar;
    podeRef.current = podeFechar;
  });
  const fechar = React.useCallback(() => {
    if (podeRef.current && !podeRef.current()) return;
    fecharRef.current();
  }, []);

  /* Foco e trava de rolagem: dependem SÓ de estar aberto. */
  React.useEffect(() => {
    if (!aberto) return;
    const veioDe = document.activeElement as HTMLElement | null;
    const minhaCaixa = caixa.current;
    if (minhaCaixa) pilhaDeModais.push(minhaCaixa);
    caixa.current?.focus({ preventScroll: true });

    /* A primitiva substituída travava a rolagem do corpo; a peça não travava, e
       a roda do mouse sobre o véu rolava a lista por baixo. Compensa a largura
       da barra para o layout não saltar ao abrir. */
    const corpo = document.body;
    const overflowAntes = corpo.style.overflow;
    const padAntes = corpo.style.paddingRight;
    const barra = window.innerWidth - document.documentElement.clientWidth;
    corpo.style.overflow = "hidden";
    if (barra > 0) corpo.style.paddingRight = `${barra}px`;

    return () => {
      const i = minhaCaixa ? pilhaDeModais.indexOf(minhaCaixa) : -1;
      if (i >= 0) pilhaDeModais.splice(i, 1);
      corpo.style.overflow = overflowAntes;
      corpo.style.paddingRight = padAntes;
      /* `preventScroll` porque o elemento de origem pode estar fora da vista:
         sem ele o navegador rola a página de fundo para trazê-lo de volta. */
      veioDe?.focus?.({ preventScroll: true });
    };
  }, [aberto]);

  /* Teclado. Separado do de cima para que ligar/desligar o Esc não mexa no
     foco nem na trava de rolagem. */
  React.useEffect(() => {
    if (!aberto) return;
    const tecla = (e: KeyboardEvent) => {
      /* ⚠️ SÓ O MODAL DE CIMA RESPONDE.
         Os dois ouvintes são de `window`, então com dois modais abertos os DOIS
         rodavam: Esc fechava os dois de uma vez, e o Tab ficava preso — o de
         baixo vê o foco fora da SUA caixa, puxa para o primeiro campo dele, e o
         de cima puxa de volta para o primeiro campo dele. Num modal de leitura
         (o detalhe de proposta do FNS, o único nível 2 que existia) isso passa
         despercebido; num FORMULÁRIO aberto por cima de outro — o editor de
         modelo de permissão — o Tab não sai do primeiro campo. */
      if (pilhaDeModais.length && pilhaDeModais[pilhaDeModais.length - 1] !== caixa.current) return;
      if (e.key === "Escape" && esc) { fechar(); return; }
      if (e.key !== "Tab" || !caixa.current) return;
      /* Prender o foco. `aria-modal="true"` faz o leitor de tela ignorar o
         resto da página; sem prender, o Tab leva para trás do véu e a pessoa
         digita numa tela que não vê nem ouve. */
      const f = Array.from(
        caixa.current.querySelectorAll<HTMLElement>(
          'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
        ),
      ).filter((el) => el.offsetParent !== null);
      if (!f.length) { e.preventDefault(); return; }
      const primeiro = f[0], ultimo = f[f.length - 1];
      const atual = document.activeElement;
      /* Por CONTENÇÃO, não por identidade. Comparar com o primeiro/último falha
         aberta: se o foco estiver em qualquer outro lugar — e vai estar no
         `<body>` sempre que o elemento focado sair da árvore — nada é impedido
         e o Tab cai na página atrás do véu, que vem antes na ordem do documento
         porque o portal é anexado ao fim do body. */
      if (!caixa.current.contains(atual)) {
        e.preventDefault();
        (e.shiftKey ? ultimo : primeiro).focus();
      } else if (e.shiftKey && atual === primeiro) {
        e.preventDefault(); ultimo.focus();
      } else if (!e.shiftKey && atual === ultimo) {
        e.preventDefault(); primeiro.focus();
      }
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [aberto, esc, fechar]);

  if (!aberto) return null;
  const ctx = { id: idTitulo, fechar };
  const conteudo = (
    <div
      className={`fixed inset-0 grid place-items-center bg-black/50 p-4 ${nivel === 2 ? "z-[60]" : "z-50"}`}
      /* Compara alvo com currentTarget em vez de `onClick={onFechar}` + um
         `stopPropagation` na caixa: assim nenhum clique legítimo que borbulha
         de dentro (um <select> nativo, por exemplo) fecha o modal por engano. */
      onClick={(e) => e.target === e.currentTarget && fechar()}
    >
      <div
        ref={caixa}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        {...(rotulo ? { "aria-label": rotulo } : { "aria-labelledby": idTitulo })}
        className={`flex max-h-[85vh] w-full flex-col overflow-hidden border outline-none ${maxW}`}
        style={{
          background: superficie ? "var(--bi-surface)" : "var(--bi-bg)",
          borderColor: "var(--bi-line)",
          borderRadius: "var(--bi-radius)",
        }}
      >
        <CtxModal.Provider value={ctx}>{children}</CtxModal.Provider>
      </div>
    </div>
  );
  /* Portal: a primitiva antiga renderizava fora da árvore da página. Sem isso,
     o modal herda `overflow`/`transform` de qualquer ancestral e a roda do
     mouse sobre o véu rola a lista por baixo. */
  return typeof document === "undefined"
    ? conteudo
    : createPortal(conteudo, document.body);
}

/** O id do título, para o `ModalHead` etiquetar o diálogo sem o chamador
 *  precisar passar nada. */
const CtxModal = React.createContext<{ id: string; fechar: () => void } | undefined>(undefined);

/** Cabeçalho fixo da caixa. Fica em `--bi-surface` mesmo quando o corpo é
 *  `--bi-bg`: é o que separa "o que este modal é" do que se rola. */
export function ModalHead({
  titulo,
  sub,
  onFechar,
  right,
  abaixo,
}: {
  titulo: React.ReactNode;
  sub?: React.ReactNode;
  onFechar: () => void;
  /** Conteúdo à direita do título, antes do X. */
  right?: React.ReactNode;
  /** Faixa extra sob o título, ainda dentro da parte que não rola —
   *  é onde a barra de abas mora. */
  abaixo?: React.ReactNode;
}) {
  /* O X usa o fechador GUARDADO do `Modal` quando existe: senão ele seria a
     única das três saídas a escapar da confirmação de descarte. */
  const ctx = React.useContext(CtxModal);
  const fechar = ctx?.fechar ?? onFechar;
  return (
    <div className="shrink-0 border-b" style={{ background: "var(--bi-surface)", borderColor: "var(--bi-line)" }}>
      <div className="flex items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <h3 id={ctx?.id} className="bi-title text-[14px] leading-tight">{titulo}</h3>
          {sub && (
            <p className="mt-0.5 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
              {sub}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {right}
          <button
            type="button"
            onClick={fechar}
            className="hover:opacity-70"
            style={{ color: "var(--bi-muted)" }}
            aria-label="Fechar"
          >
            <XIcon />
          </button>
        </div>
      </div>
      {abaixo && <div className="px-4 pb-3">{abaixo}</div>}
    </div>
  );
}

/** O X, desenhado aqui para a peça não depender de lucide em quem a importa. */
function XIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
         strokeLinecap="round" className="size-5" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

/** O corpo que rola. */
export function ModalCorpo({ children, className = "" }: {
  children: React.ReactNode; className?: string;
}) {
  return <div className={`bi-scroll min-h-0 flex-1 overflow-y-auto p-3 ${className}`}>{children}</div>;
}

/** Um grupo de campos do detalhe: o cartão e o título em volta da grade.
 *  Quatro colunas fixas em todos, para os blocos empilhados lerem como uma
 *  coisa só. Veio do modal do FNS. */
export function Secao({
  icon,
  titulo,
  sub,
  campos,
  cols = 4,
  children,
}: {
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  titulo: React.ReactNode;
  sub?: React.ReactNode;
  campos?: Campo[];
  cols?: number;
  children?: React.ReactNode;
}) {
  return (
    <Bloco className="p-3">
      <BlocoHead icon={icon} titulo={titulo} sub={sub} />
      {campos && campos.length > 0 && <Campos campos={campos} cols={cols} />}
      {children}
    </Bloco>
  );
}

/** Faixa de aviso DENTRO de uma seção — o que era
 *  `border-l-4 border-warning bg-warning/15`.
 *
 *  A régua colorida de 4px na lateral é gramática do sistema antigo: ela pinta
 *  a borda para dizer o que o fundo lavado já diz, e some no escuro, onde a
 *  borda esquerda encosta num fundo quase preto. Aqui o sinal é o fundo, e o
 *  título leva a variante `-ink` da mesma família — que é a que passa em AA. */
export function Aviso({ tom, titulo, children, icon: Icon, className = "mt-3" }: {
  tom: "ok" | "atencao" | "critico";
  titulo: React.ReactNode;
  children?: React.ReactNode;
  /** Marcador não-textual. Um aviso crítico sem nenhum sinal além da cor
   *  desaparece para quem não distingue vermelho. */
  icon?: React.ComponentType<{ className?: string }>;
  /** O padrão `mt-3` serve ao caso comum (aviso no fim de uma `Secao`). Quem
   *  põe o aviso dentro de um contêiner que já espaça passa `className=""`. */
  className?: string;
}) {
  const c = tom === "critico" ? "crit" : tom === "ok" ? "ok" : "warn";
  return (
    <div
      className={`rounded-lg p-2.5 ${className}`}
      style={{ background: `color-mix(in oklab, var(--bi-${c}) 12%, transparent)` }}
    >
      <div className="flex items-start gap-1.5 text-[11px] font-semibold leading-snug"
           style={{ color: `var(--bi-${c}-ink)` }}>
        {Icon && <Icon className="mt-px size-3.5 shrink-0" />}
        <span className="min-w-0">{titulo}</span>
      </div>
      {children && <div className="mt-1.5">{children}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Abas
// ---------------------------------------------------------------------------

/** Pílulas segmentadas — o `SegTabs` do Painel, com o que faltava para servir
 *  a um modal: aba desligada e semântica de tablist.
 *
 *  Não é o "fichário" das sete abas do Painel, e a razão é estrutural: o
 *  fichário depende de a pasta ativa ter a MESMA cor do painel logo abaixo
 *  (`--bi-surface`). No modal de detalhe o corpo é `--bi-bg`, então a pasta
 *  ativa branca ficaria pendurada sobre cinza e a metáfora quebraria.
 *
 *  O que isto substitui é `border-b-2 border-primary text-primary`. Cuidado ao
 *  procurar por essas abas: como `primary` já foi repontado para o acento, elas
 *  HOJE já aparecem verdes — não parecem quebradas, parecem quase certas. O que
 *  está errado é a gramática (sublinhado de 2px + rótulo colorido), não o tom. */
export function Abas<T extends string>({
  valor,
  onChange,
  opcoes,
  tamanho = "sm",
}: {
  valor: T;
  onChange: (v: T) => void;
  opcoes: Array<{ valor: T; label: string; on?: boolean }>;
  tamanho?: "sm" | "md";
}) {
  /* Setas ←/→ e um só Tab para o grupo (roving tabindex).
   *
   *  Declarar `role="tablist"` cria obrigação: o leitor de tela anuncia "guia 1
   *  de 5" e INSTRUI a pessoa a usar as setas. A versão anterior tinha os
   *  papéis e não tinha as setas — o que é pior que não ter papel nenhum,
   *  porque promete uma navegação que não existe. */
  const grupo = React.useRef<HTMLDivElement>(null);
  const seta = (e: React.KeyboardEvent) => {
    const passo = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!passo) return;
    e.preventDefault();
    const vivas = opcoes.filter((o) => o.on !== false);
    if (vivas.length < 2) return;
    const i = vivas.findIndex((o) => o.valor === valor);
    const alvo = vivas[(i + passo + vivas.length) % vivas.length];
    onChange(alvo.valor);
    // O foco acompanha a seleção, como manda o padrão para aba automática.
    requestAnimationFrame(() =>
      grupo.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus(),
    );
  };

  return (
    <div
      ref={grupo}
      role="tablist"
      onKeyDown={seta}
      className="inline-flex flex-wrap items-center gap-1 rounded-full p-1"
      style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}
    >
      {opcoes.map((o) => {
        const ativo = o.valor === valor;
        const on = o.on !== false;
        return (
          <button
            key={o.valor}
            type="button"
            role="tab"
            aria-selected={ativo}
            tabIndex={ativo ? 0 : -1}
            disabled={!on}
            onClick={() => on && onChange(o.valor)}
            className={`rounded-full font-medium transition-colors ${
              tamanho === "sm" ? "px-2.5 py-1 text-[11px]" : "px-3 py-1.5 text-xs"
            } ${on ? "" : "cursor-not-allowed"}`}
            style={{
              background: ativo ? "var(--bi-surface)" : "transparent",
              color: ativo ? "var(--bi-text)" : "var(--bi-muted)",
              border: `1px solid ${ativo ? "var(--bi-line)" : "transparent"}`,
              fontWeight: ativo ? 700 : 500,
              /* Mesma opacidade que o kit do Painel usa para botão desligado. */
              opacity: on ? 1 : 0.4,
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Grade — o dado tabular que continua tabular.
// ---------------------------------------------------------------------------

/** A identidade nunca proibiu GRADE; ela proibiu `<table>` com borda colapsada,
 *  zebra, régua em toda linha e cor de marca no cabeçalho. A prova está dentro
 *  da própria referência: a lista de exigências do CAUC (`components/bi/
 *  abas.tsx`) é uma grade de quatro colunas de largura fixa, e o comentário de
 *  lá explica que usaram GRADE e não flex porque com flex "o rótulo que
 *  quebrava em duas linhas empurrava as colunas da direita".
 *
 *  Quando usar cartão e quando usar grade:
 *   · registro com UM protagonista (nome, objeto) e números de apoio → cartão,
 *     com `ItemLinha` + `Campos`;
 *   · registro que é PURO extrato, sem protagonista, e cujo gesto é descer o
 *     olho por uma coluna → grade. Seis identificadores irmãos (Nº NS, Nº OP,
 *     Nº OB, valor, situação, emissão) não têm um "nome" para virar título:
 *     virar cartão seria pior para quem confere.
 *
 *  `cols` é uma classe `grid-cols-[...]` LITERAL, pela mesma razão do `maxW`. */
export function Grade({ cols, cabecalho, children, rolagem = false, minLargura = "38rem" }: {
  cols: string;
  cabecalho: Array<{ label: string; direita?: boolean }>;
  children: React.ReactNode;
  /** Rolagem horizontal LOCAL, dentro do bloco — nunca no modal. */
  rolagem?: boolean;
  /** Largura mínima antes de a rolagem entrar.
   *
   *  Era `min-w-max`, e isso anulava a coluna elástica: com `max-content` a
   *  trilha `minmax(10rem,1fr)` resolve para o texto INTEIRO numa linha só, a
   *  grade estoura a largura do modal e a descrição da submeta — que antes
   *  quebrava linha numa célula de tabela — vira uma faixa horizontal longa.
   *  Um piso em `rem` deixa a coluna elástica voltar a quebrar acima dele. */
  minLargura?: string;
}) {
  const corpo = (
    <>
      <div
        className={`grid ${cols} items-end gap-x-2 border-b pb-1 text-[9px] uppercase tracking-wide`}
        style={{ borderColor: "var(--bi-line-strong)", color: "var(--bi-faint)" }}
      >
        {cabecalho.map((c, i) => (
          <div key={i} className={`min-w-0 truncate ${c.direita ? "text-right" : ""}`}>{c.label}</div>
        ))}
      </div>
      <div className="divide-y" style={{ borderColor: "var(--bi-line)" }}>{children}</div>
    </>
  );
  if (!rolagem) return corpo;
  return (
    <div className="bi-scroll overflow-x-auto">
      <div style={{ minWidth: minLargura }}>{corpo}</div>
    </div>
  );
}

/** Uma linha da grade. `alerta` pinta o FUNDO lavado — não o texto de vermelho:
 *  texto colorido numa grade de seis colunas some no meio dos outros cinco. */
export function GradeLinha({ cols, children, alerta = false }: {
  cols: string; children: React.ReactNode; alerta?: boolean;
}) {
  return (
    <div
      className={`grid ${cols} items-start gap-x-2 py-[5px]`}
      style={alerta ? { background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)" } : undefined}
    >
      {children}
    </div>
  );
}

/** Célula. `tom="id"` = identificador (mono, apagado); `"num"` = número
 *  (tabular, à direita); `"data"` = data (tabular, à direita, cinza). */
export function GradeCel({ children, tom = "texto", title, className = "" }: {
  children: React.ReactNode;
  tom?: "texto" | "id" | "num" | "data";
  title?: string;
  className?: string;
}) {
  const base = "min-w-0 text-[11px] leading-snug";
  if (tom === "id")
    return <div className={`${base} bi-id truncate ${className}`} style={{ color: "var(--bi-faint)" }} title={title}>{children}</div>;
  if (tom === "num")
    return <div className={`${base} bi-num truncate text-right whitespace-nowrap ${className}`} style={{ color: "var(--bi-text)" }} title={title}>{children}</div>;
  if (tom === "data")
    return <div className={`${base} bi-num truncate text-right whitespace-nowrap ${className}`} style={{ color: "var(--bi-muted)" }} title={title}>{children}</div>;
  return <div className={`${base} break-words ${className}`} style={{ color: "var(--bi-text)" }} title={title}>{children}</div>;
}

// ---------------------------------------------------------------------------
// Etapas — a sequência.
// ---------------------------------------------------------------------------

/** O stepper. Cor NÃO marca progresso: CONTRASTE marca progresso.
 *
 *  A etapa cumprida usa a CTA (quase preta no claro, menta no escuro) e a
 *  pendente usa a mesma linha cinza das divisórias — o progresso se lê pelo
 *  contraste. A etapa ATUAL não ganha um terceiro fundo: ganha um contorno de
 *  acento sobre o fundo que já teria. Um anel colorido num item que já se
 *  distingue pela posição é o segundo sinal redundante.
 *
 *  Veio do stepper de 12 etapas do modal do FNS, que já está em produção. Dois
 *  steppers com desenhos diferentes no mesmo produto é o defeito que esta
 *  unificação existe para eliminar. */
export function Etapas({ etapas, largura = 60 }: {
  /** Largura da coluna de cada etapa. 60px serve a rótulo curto; um stepper de
   *  rótulos longos (as 15 etapas do SIGCON) precisa de mais, senão a palavra
   *  transborda a caixa. */
  largura?: number;
  etapas: Array<{
    rotulo: string;
    /** O número OFICIAL da etapa, quando a fonte tem um (o FNS tem; o SIGCON
     *  não). Quando existe, aparece SEMPRE — inclusive na etapa cumprida, cujo
     *  estado já se lê pelo preenchimento. Sem ele, a etapa cumprida mostra ✓ e
     *  a pendente mostra a posição. */
    numero?: React.ReactNode;
    concluida: boolean;
    atual?: boolean;
    title?: string;
  }>;
}) {
  return (
    <div className="bi-scroll flex items-start justify-between overflow-x-auto pt-1">
      {etapas.map((e, i) => (
        <React.Fragment key={i}>
          <div className="flex flex-col items-center text-center" style={{ minWidth: largura }} title={e.title || e.rotulo}>
            <div
              className="grid size-7 shrink-0 place-items-center rounded-full text-[11px] font-bold"
              style={{
                background: e.concluida ? "var(--bi-cta)" : "var(--bi-surface-2)",
                /* `--bi-faint` sobre `--bi-line` dava 2,26 no claro e 2,87 no
                   escuro. Sao 11px em NEGRITO: nao contam como texto grande,
                   entao o piso e 4,5 e nao 3. Com `--bi-muted` sobre
                   `--bi-surface-2` passa nos dois. */
                color: e.concluida ? "var(--bi-cta-ink)" : "var(--bi-muted)",
                ...(e.atual
                  ? { outline: "2px solid var(--bi-accent-ink)", outlineOffset: "2px" }
                  : {}),
              }}
            >
              {e.numero ?? (e.concluida ? <CheckIcon /> : i + 1)}
            </div>
            <div className="mt-1 text-[9px] leading-tight break-words hyphens-auto"
                 style={{ maxWidth: largura, color: "var(--bi-faint)" }} lang="pt-BR">
              {e.rotulo}
            </div>
          </div>
          {i < etapas.length - 1 && (
            <div
              className="mx-0.5 mt-3 h-1 flex-1"
              style={{
                background: e.concluida && etapas[i + 1].concluida ? "var(--bi-cta)" : "var(--bi-line)",
              }}
            />
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}
         strokeLinecap="round" strokeLinejoin="round" className="size-3.5" aria-hidden="true">
      <path d="m20 6-11 11-5-5" />
    </svg>
  );
}
