"use client";

/* A ABA LISTA — o extrato da agenda, um cartão comprido por compromisso.
 *
 * ⚠️ CARTÃO COMPRIDO, E NÃO TABELA DENSA (`estilo-lista.jpg`, pedido do dono).
 * A diferença que importa não é estética: numa tabela com régua em toda linha, a
 * linha 14 e a 15 se confundem no meio de uma rolagem, e é assim que alguém abre
 * o compromisso errado. Com respiro entre os cartões, cada registro é um objeto
 * — o cabeçalho de colunas continua existindo em cima, para o olho descer por
 * uma coluna quando o que ele quer é comparar.
 *
 * ⚠️ SEIS COLUNAS, E SÓ ESSAS (rodada 1 de ajustes): Data | Horário |
 * Solicitante | Município | Demanda | Situação. Saíram o contato e o contador de
 * anotações — os dois são detalhe DO compromisso, não critério de varredura, e
 * cada um roubava largura da demanda, que é o que a pessoa está de fato lendo.
 * Os dois continuam no modal, a um clique.
 *
 * ⚠️ O FILTRO DE PERÍODO É DAQUI, e não do módulo. A aba abre em «Este mês»
 * (documento) porque uma lista de tudo, aberta de cara, é uma rolagem sem
 * pergunta. O calendário e o kanban continuam vendo o recorte inteiro: são os
 * dois lugares em que "o que existe depois deste mês" tem uso.
 */

import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import { Selo, Vazio } from "@/components/ui/superficies";
import {
  Compromisso, diaBR, estiloDaCor, hojeISO, horarioDe, limitesDoMes, minutos,
  segundaDaSemana, somaDias,
} from "./tipos";

type Periodo = "hoje" | "semana" | "mes" | "todos";
type Ordem = "data" | "status";

const PERIODOS: [Periodo, string][] = [
  ["hoje", "Hoje"], ["semana", "Esta semana"], ["mes", "Este mês"],
  ["todos", "Todos"],
];

/** O recorte de cada opção, em `YYYY-MM-DD` (inclusive nas duas pontas). */
function janela(p: Periodo): [string, string] | null {
  const hoje = hojeISO();
  if (p === "hoje") return [hoje, hoje];
  if (p === "semana") {
    const seg = segundaDaSemana(hoje);
    return [seg, somaDias(seg, 6)];
  }
  if (p === "mes") return limitesDoMes(hoje);
  return null;
}

export default function ListaCompromissos({
  itens, comMunicipio, onAbrir,
}: {
  itens: Compromisso[];
  comMunicipio: boolean;
  onAbrir: (c: Compromisso) => void;
}) {
  const [periodo, setPeriodo] = useState<Periodo>("mes");
  const [ordem, setOrdem] = useState<Ordem>("data");
  const [desc, setDesc] = useState(false);

  const visiveis = useMemo(() => {
    const faixa = janela(periodo);
    const dentro = faixa
      ? itens.filter((c) => {
          const d = String(c.data || "").slice(0, 10);
          return d >= faixa[0] && d <= faixa[1];
        })
      : itens;
    const sinal = desc ? -1 : 1;
    return [...dentro].sort((a, b) => {
      if (ordem === "status") {
        const s = a.coluna.localeCompare(b.coluna, "pt-BR");
        if (s) return s * sinal;
      }
      const d = String(a.data || "").localeCompare(String(b.data || ""));
      if (d) return d * sinal;
      return (minutos(a.hora_inicio) - minutos(b.hora_inicio)) * sinal || a.id - b.id;
    });
  }, [itens, periodo, ordem, desc]);

  const ordenarPor = (campo: Ordem) => {
    if (ordem === campo) setDesc((v) => !v);
    else { setOrdem(campo); setDesc(false); }
  };

  /* `grid-cols-[...]` LITERAL: o Tailwind só gera a classe se ela aparecer
     escrita no código. Duas escadas — com e sem a coluna de município. A tarja
     de cor é a primeira faixa e não conta como coluna de texto. */
  const cols = comMunicipio
    ? "grid-cols-[4px_5.5rem_6.5rem_minmax(0,1fr)_minmax(0,1fr)_minmax(0,2fr)_7rem]"
    : "grid-cols-[4px_5.5rem_6.5rem_minmax(0,1fr)_minmax(0,2.5fr)_7rem]";

  return (
    <div className="flex h-full min-h-0 flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        {PERIODOS.map(([v, rotulo]) => (
          <button key={v} type="button" onClick={() => setPeriodo(v)}
                  aria-pressed={periodo === v}
                  className="rounded-full border px-2.5 py-1 text-[11px] transition-colors"
                  style={periodo === v
                    ? { background: "var(--bi-accent-soft)", borderColor: "transparent",
                        color: "var(--bi-accent-ink)", fontWeight: 600 }
                    : { borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}>
            {rotulo}
          </button>
        ))}
        {/* ⭐ O CONTADOR MORA AQUI, E EM MAIS LUGAR NENHUM (rodada 1). Ele
            aparecia duas vezes — na toolbar do módulo e aqui — e os dois números
            eram DIFERENTES: o de cima contava o recorte inteiro, o de baixo o
            período filtrado. Dois números com o mesmo rótulo na mesma tela é
            pior que nenhum, porque o leitor não sabe qual acreditar. Ficou o de
            baixo, que é o que corresponde ao que está desenhado sob ele. */}
        <span className="ml-auto text-[11px]" style={{ color: "var(--bi-faint)" }}>
          {visiveis.length} compromisso(s)
        </span>
      </div>

      {/* Cabeçalho de colunas em chips DESGARRADOS, na mesma gramática dos dias
          da semana e dos cabeçalhos do kanban. Fica fora da rolagem e alinhado
          aos cartões: é o que permite comparar uma coluna sem transformar a
          lista numa tabela. */}
      <div className={`grid ${cols} shrink-0 items-stretch gap-2 pr-3 text-[10px]`}>
        <span />
        <Cabecalho ativo={ordem === "data"} desc={desc} onClick={() => ordenarPor("data")}>
          Data
        </Cabecalho>
        <Cabecalho>Horário</Cabecalho>
        <Cabecalho>Solicitante</Cabecalho>
        {comMunicipio && <Cabecalho>Município</Cabecalho>}
        <Cabecalho>Demanda</Cabecalho>
        <Cabecalho ativo={ordem === "status"} desc={desc} onClick={() => ordenarPor("status")}>
          Situação
        </Cabecalho>
      </div>

      <div className="bi-scroll min-h-0 flex-1 space-y-2 overflow-y-auto pb-1 pr-0.5">
        {visiveis.length === 0 ? (
          /* Dois vazios diferentes: "não há nada" pede uma instrução (onde se
             cria), "não há nada AQUI" pede só o fato — a pessoa já sabe o que
             fazer, é trocar o período. */
          <Vazio>
            {itens.length === 0
              ? "Nenhum compromisso ainda. Crie o primeiro pelo calendário."
              : "Nenhum compromisso neste período."}
          </Vazio>
        ) : visiveis.map((c) => (
          <div key={c.id} role="button" tabIndex={0}
               onClick={() => onAbrir(c)}
               onKeyDown={(e) => {
                 if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onAbrir(c); }
               }}
               style={{ ...estiloDaCor(c.cor), background: "var(--bi-surface)",
                        border: "1px solid var(--bi-line)" }}
               className={`grid ${cols} items-center gap-2 overflow-hidden rounded-xl py-2.5 pr-3 text-[12px] bi-hover`}>
            {/* A tarja de cor é a PRIMEIRA faixa da grade, colada na borda —
                o mesmo identificador que o chip do calendário usa. */}
            <span className="ag-tarja h-full min-h-[2.5rem] rounded-r-full" />
            <span className="tabular-nums" style={{ color: "var(--bi-muted)" }}>
              {diaBR(c.data, true)}
            </span>
            <span className="tabular-nums font-semibold">{horarioDe(c)}</span>
            <span className="truncate" style={{ color: "var(--bi-muted)" }}>
              {c.solicitante || "—"}
            </span>
            {comMunicipio && (
              <span className="truncate" style={{ color: "var(--bi-muted)" }}>
                {c.municipio}{c.uf ? ` - ${c.uf}` : ""}
              </span>
            )}
            <span className="truncate font-medium">{c.demanda}</span>
            <span className="min-w-0 truncate"><Selo>{c.coluna}</Selo></span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** O chip desgarrado do cabeçalho. Clicável quando a coluna ordena; inerte
 *  quando não — e aí ele é um `<div>`, para o teclado não parar num alvo que
 *  não faz nada. */
function Cabecalho({ ativo, desc, onClick, children }: {
  ativo?: boolean;
  desc?: boolean;
  onClick?: () => void;
  children: ReactNode;
}) {
  const classe = "ag-solto flex items-center justify-center gap-0.5 px-2 py-1.5 uppercase tracking-wider";
  const estilo = { color: ativo ? "var(--bi-accent-ink)" : "var(--bi-muted)",
                   fontWeight: ativo ? 700 : 500 };
  if (!onClick) return <div className={classe} style={estilo}>{children}</div>;
  const Seta = desc ? ArrowDown : ArrowUp;
  return (
    <button type="button" onClick={onClick} className={`${classe} bi-hover`} style={estilo}>
      {children}
      {ativo && <Seta className="size-2.5" />}
    </button>
  );
}
