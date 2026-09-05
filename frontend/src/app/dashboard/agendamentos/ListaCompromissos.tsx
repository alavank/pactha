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
 * ⚠️ O FILTRO DE PERÍODO É DAQUI, e não do módulo. A aba abre em «Este mês»
 * (documento) porque uma lista de tudo, aberta de cara, é uma rolagem sem
 * pergunta. O calendário e o kanban continuam vendo o recorte inteiro: são os
 * dois lugares em que "o que existe depois deste mês" tem uso.
 */

import { useMemo, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, MessageSquare } from "lucide-react";

import { Selo, Vazio } from "@/components/ui/superficies";
import {
  Compromisso, diaBR, estiloDaCor, hojeISO, horarioDe, limitesDoMes, minutos,
  segundaDaSemana, somaDias, telefoneBR,
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
  itens, comMunicipio, onAbrir, onEditar,
}: {
  itens: Compromisso[];
  comMunicipio: boolean;
  onAbrir: (c: Compromisso) => void;
  onEditar: (c: Compromisso) => void;
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
     escrita no código. Duas escadas — com e sem a coluna de município. */
  const cols = comMunicipio
    ? "grid-cols-[4px_5.5rem_6.5rem_minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_8rem_7rem_3rem]"
    : "grid-cols-[4px_5.5rem_6.5rem_minmax(0,3fr)_minmax(0,1fr)_8rem_7rem_3rem]";

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
        <span className="ml-auto text-[11px]" style={{ color: "var(--bi-faint)" }}>
          {visiveis.length} compromisso(s)
        </span>
      </div>

      {/* O cabeçalho de colunas fica FORA da rolagem e alinhado aos cartões:
          é o que permite comparar uma coluna sem transformar a lista em tabela. */}
      <div className={`grid ${cols} items-center gap-2 px-3 text-[10px] uppercase tracking-wider`}
           style={{ color: "var(--bi-faint)" }}>
        <span />
        <Cabecalho ativo={ordem === "data"} desc={desc} onClick={() => ordenarPor("data")}>
          Data
        </Cabecalho>
        <span>Horário</span>
        <span>Demanda</span>
        {comMunicipio && <span>Município</span>}
        <span>Solicitante</span>
        <span>Contato</span>
        <Cabecalho ativo={ordem === "status"} desc={desc} onClick={() => ordenarPor("status")}>
          Situação
        </Cabecalho>
        <span className="text-right">Anot.</span>
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
               onDoubleClick={() => onEditar(c)}
               onKeyDown={(e) => {
                 if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onAbrir(c); }
               }}
               style={{ ...estiloDaCor(c.cor), background: "var(--bi-surface)",
                        border: "1px solid var(--bi-line)" }}
               className={`grid ${cols} items-center gap-2 overflow-hidden rounded-xl py-2.5 pr-3 text-[12px] bi-hover`}>
            {/* A tarja de cor é a PRIMEIRA coluna da grade, colada na borda —
                o mesmo identificador que o chip do calendário usa. */}
            <span className="ag-tarja h-full min-h-[2.5rem] rounded-r-full" />
            <span className="tabular-nums" style={{ color: "var(--bi-muted)" }}>
              {diaBR(c.data, true)}
            </span>
            <span className="tabular-nums font-semibold">{horarioDe(c)}</span>
            <span className="truncate font-medium">{c.demanda}</span>
            {comMunicipio && (
              <span className="truncate" style={{ color: "var(--bi-muted)" }}>
                {c.municipio}{c.uf ? ` - ${c.uf}` : ""}
              </span>
            )}
            <span className="truncate" style={{ color: "var(--bi-muted)" }}>
              {c.solicitante || "—"}
            </span>
            <span className="truncate tabular-nums" style={{ color: "var(--bi-muted)" }}>
              {telefoneBR(c.contato_whatsapp) || "—"}
            </span>
            <span><Selo>{c.coluna}</Selo></span>
            <span className="inline-flex items-center justify-end gap-1 text-[11px]"
                  style={{ color: "var(--bi-faint)" }}>
              <MessageSquare className="size-3" />{c.anotacoes_qtd}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Cabecalho({ ativo, desc, onClick, children }: {
  ativo: boolean;
  desc: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  const Seta = desc ? ArrowDown : ArrowUp;
  return (
    <button type="button" onClick={onClick}
            className="inline-flex items-center gap-0.5 uppercase tracking-wider"
            style={{ color: ativo ? "var(--bi-accent-ink)" : "inherit",
                     fontWeight: ativo ? 700 : 400 }}>
      {children}
      {ativo && <Seta className="size-2.5" />}
    </button>
  );
}
