"use client";

/* O KANBAN — em que pé está cada compromisso.
 *
 * ⚠️ AQUI NÃO SE CRIA COMPROMISSO (decisão do dono). O compromisso nasce no
 * calendário porque ele tem DIA E HORA obrigatórios: um cartão criado numa
 * coluna nasceria sem os dois campos que o posicionam na agenda, e ficaria
 * visível só aqui — que é exatamente a linha que some da tela sem sumir do
 * banco.
 *
 * ⚠️ O ARRASTAR NÃO É A ÚNICA FORMA DE MOVER. Arrastar não funciona com teclado
 * nem com leitor de tela, e é a interação que um toque desastrado dispara sem
 * querer. Cada cartão traz também um seletor de coluna — com ele, mover nunca
 * depende do mouse, e desfazer é escolher de volta.
 *
 * ⚠️ AS TRÊS COLUNAS FIXAS NÃO SE RENOMEIAM NEM SE APAGAM, e o botão «+ Coluna»
 * some no teto. Os dois limites também valem na API (`routers/agendamentos`):
 * duas abas abertas contam separado, e quem conta de verdade é o banco.
 */

import React, { useState } from "react";
import { Check, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";

import { BOTAO_SEC, ESTILO_SEC, Vazio } from "@/components/ui/superficies";
import { Coluna, Compromisso, diaBR, estiloDaCor, horarioDe } from "./tipos";

export default function Kanban({
  itens, colunas, comMunicipio, maxColunas, maxCustomizadas,
  onAbrir, onEditar, onMover, onCriarColuna, onRenomearColuna, onRemoverColuna,
}: {
  itens: Compromisso[];
  colunas: Coluna[];
  comMunicipio: boolean;
  maxColunas: number;
  maxCustomizadas: number;
  onAbrir: (c: Compromisso) => void;
  onEditar: (c: Compromisso) => void;
  onMover: (c: Compromisso, colunaId: number) => void;
  onCriarColuna: (nome: string) => Promise<void>;
  onRenomearColuna: (id: number, nome: string) => Promise<void>;
  onRemoverColuna: (id: number, quantos: number) => void;
}) {
  const [sobre, setSobre] = useState<number | null>(null);
  const [criando, setCriando] = useState(false);
  const [nomeNovo, setNomeNovo] = useState("");
  const customizadas = colunas.filter((c) => !c.fixa).length;
  const podeCriar = colunas.length < maxColunas && customizadas < maxCustomizadas;

  const criar = async () => {
    const nome = nomeNovo.trim();
    if (!nome) return;
    await onCriarColuna(nome);
    setNomeNovo(""); setCriando(false);
  };

  return (
    <div className="bi-scroll flex h-full min-h-0 gap-3 overflow-x-auto pb-1">
      {colunas.map((col) => {
        const daColuna = itens.filter((i) => i.coluna_id === col.id);
        return (
          <div
            key={col.id}
            onDragOver={(e) => { e.preventDefault(); setSobre(col.id); }}
            onDragLeave={() => setSobre((s) => (s === col.id ? null : s))}
            onDrop={(e) => {
              e.preventDefault(); setSobre(null);
              const id = Number(e.dataTransfer.getData("text/plain"));
              const item = itens.find((x) => x.id === id);
              if (item && item.coluna_id !== col.id) onMover(item, col.id);
            }}
            className="flex w-[18rem] shrink-0 flex-col rounded-2xl transition-colors"
            style={{
              background: sobre === col.id ? "var(--bi-accent-soft)" : "var(--bi-surface-2)",
              border: "1px solid var(--bi-line)",
            }}
          >
            <CabecalhoColuna col={col} total={daColuna.length}
                             onRenomear={onRenomearColuna}
                             onRemover={() => onRemoverColuna(col.id, daColuna.length)} />
            <div className="bi-scroll min-h-0 flex-1 space-y-2.5 overflow-y-auto px-2 pb-2">
              {daColuna.length === 0 ? (
                <p className="px-1 py-6 text-center text-[11px]"
                   style={{ color: "var(--bi-faint)" }}>
                  {sobre === col.id ? "solte aqui" : "nada nesta coluna"}
                </p>
              ) : daColuna.map((c) => (
                <Pasta key={c.id} c={c} colunas={colunas} comMunicipio={comMunicipio}
                       onAbrir={onAbrir} onEditar={onEditar} onMover={onMover} />
              ))}
            </div>
          </div>
        );
      })}

      {/* ⚠️ O BOTÃO SOME NO TETO em vez de ficar desabilitado: botão apagado
          convida ao clique e devolve nada. Com o limite atingido, o que existe é
          a instrução de remover uma para criar outra — e ela está no 422 da
          API, para quem chegar lá por outro caminho. */}
      {podeCriar && (
        <div className="w-[18rem] shrink-0">
          {criando ? (
            <div className="rounded-2xl p-2"
                 style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}>
              <input autoFocus value={nomeNovo} maxLength={40}
                     onChange={(e) => setNomeNovo(e.target.value)}
                     onKeyDown={(e) => {
                       if (e.key === "Enter") criar();
                       if (e.key === "Escape") { setCriando(false); setNomeNovo(""); }
                     }}
                     placeholder="Nome da coluna"
                     className="bi-field h-8 w-full px-2 text-[12px]" />
              <div className="mt-1.5 flex items-center gap-1.5">
                <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                        onClick={criar} disabled={!nomeNovo.trim()}>
                  <Check className="size-3.5" /> Criar
                </button>
                <button type="button" className="text-[11px] underline"
                        style={{ color: "var(--bi-muted)" }}
                        onClick={() => { setCriando(false); setNomeNovo(""); }}>
                  cancelar
                </button>
              </div>
            </div>
          ) : (
            <button type="button" onClick={() => setCriando(true)}
                    className="flex h-11 w-full items-center justify-center gap-1.5 rounded-2xl border border-dashed text-[12px] bi-hover"
                    style={{ borderColor: "var(--bi-line-strong)", color: "var(--bi-muted)" }}>
              <Plus className="size-3.5" /> Coluna
            </button>
          )}
        </div>
      )}

      {colunas.length === 0 && (
        <Vazio>O quadro ainda não tem colunas.</Vazio>
      )}
    </div>
  );
}

/* ------------------------------------------------------ cabeçalho da coluna */

function CabecalhoColuna({ col, total, onRenomear, onRemover }: {
  col: Coluna;
  total: number;
  onRenomear: (id: number, nome: string) => Promise<void>;
  onRemover: () => void;
}) {
  const [editando, setEditando] = useState(false);
  const [nome, setNome] = useState(col.nome);

  const salvar = async () => {
    const n = nome.trim();
    if (!n || n === col.nome) { setEditando(false); setNome(col.nome); return; }
    await onRenomear(col.id, n);
    setEditando(false);
  };

  if (editando) {
    return (
      <div className="flex items-center gap-1 px-2.5 py-2">
        <input autoFocus value={nome} maxLength={40}
               onChange={(e) => setNome(e.target.value)}
               onKeyDown={(e) => {
                 if (e.key === "Enter") salvar();
                 if (e.key === "Escape") { setEditando(false); setNome(col.nome); }
               }}
               className="bi-field h-7 min-w-0 flex-1 px-1.5 text-[12px]" />
        <button type="button" onClick={salvar} aria-label="Salvar nome"
                className="rounded p-1 bi-hover" style={{ color: "var(--bi-accent-ink)" }}>
          <Check className="size-3.5" />
        </button>
        <button type="button" aria-label="Cancelar" className="rounded p-1 bi-hover"
                style={{ color: "var(--bi-muted)" }}
                onClick={() => { setEditando(false); setNome(col.nome); }}>
          <X className="size-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="group flex items-center gap-1.5 px-2.5 py-2">
      <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">
        {col.nome}
      </span>
      <span className="rounded-full px-1.5 text-[11px] tabular-nums"
            style={{ background: "var(--bi-line)", color: "var(--bi-muted)" }}>
        {total}
      </span>
      {!col.fixa && (
        <>
          <button type="button" onClick={() => setEditando(true)}
                  aria-label={`Renomear coluna ${col.nome}`}
                  className="rounded p-1 opacity-0 transition-opacity bi-hover focus-visible:opacity-100 group-hover:opacity-100"
                  style={{ color: "var(--bi-muted)" }}>
            <Pencil className="size-3" />
          </button>
          <button type="button" onClick={onRemover}
                  aria-label={`Remover coluna ${col.nome}`}
                  className="rounded p-1 opacity-0 transition-opacity bi-hover focus-visible:opacity-100 group-hover:opacity-100"
                  style={{ color: "var(--bi-crit-ink)" }}>
            <Trash2 className="size-3" />
          </button>
        </>
      )}
    </div>
  );
}

/* --------------------------------------------------------- cartão em pasta */

/** O cartão no formato de PASTA (`estilo-pastas.jpg`): a aba recortada no alto,
 *  na cor da demanda, e o corpo colado nela — os dois lêem como uma peça só. */
function Pasta({ c, colunas, comMunicipio, onAbrir, onEditar, onMover }: {
  c: Compromisso;
  colunas: Coluna[];
  comMunicipio: boolean;
  onAbrir: (c: Compromisso) => void;
  onEditar: (c: Compromisso) => void;
  onMover: (c: Compromisso, colunaId: number) => void;
}) {
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  React.useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  /* Um clique abre, dois editam — a mesma regra do calendário, e pelo mesmo
     motivo: o navegador dispara dois `click` antes do `dblclick`. */
  const abrir = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { timer.current = null; onAbrir(c); }, 250);
  };
  const editar = () => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    onEditar(c);
  };

  return (
    <div draggable style={estiloDaCor(c.cor)}
         onDragStart={(e) => e.dataTransfer.setData("text/plain", String(c.id))}
         className="cursor-grab active:cursor-grabbing">
      {/* A ABA. Leva o dia e a hora — é o que distingue dois cartões da mesma
          coluna à distância, e o que a pasta de arquivo teria escrito na guia. */}
      <div className="ag-pasta-aba flex w-[62%] items-center gap-1 px-2 py-0.5 text-[10px] font-semibold tabular-nums">
        <span className="truncate">{diaBR(c.data)} · {horarioDe(c)}</span>
      </div>
      <div className="ag-pasta-corpo p-2">
        <button type="button" onClick={abrir} onDoubleClick={editar}
                className="block w-full text-left">
          <p className="text-[12.5px] font-semibold leading-snug">{c.demanda}</p>
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {c.solicitante || "sem solicitante"}
          </p>
          {comMunicipio && (
            <p className="truncate text-[11px]" style={{ color: "var(--bi-faint)" }}>
              {c.municipio}{c.uf ? ` - ${c.uf}` : ""}
            </p>
          )}
        </button>
        <div className="mt-2 flex items-center gap-2 border-t pt-1.5"
             style={{ borderColor: "var(--bi-line)" }}>
          <span className="inline-flex items-center gap-1 text-[10px]"
                style={{ color: "var(--bi-faint)" }}>
            <MessageSquare className="size-3" /> {c.anotacoes_qtd}
          </span>
          <select value={c.coluna_id} aria-label={`Coluna de ${c.demanda}`}
                  onChange={(e) => onMover(c, Number(e.target.value))}
                  className="bi-field ml-auto h-6 max-w-[9rem] px-1 text-[10px]">
            {colunas.map((k) => (
              <option key={k.id} value={k.id}>{k.nome}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  );
}
