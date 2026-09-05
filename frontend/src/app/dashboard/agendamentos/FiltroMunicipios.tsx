"use client";

/* O FILTRO DE MUNICÍPIOS DA TOOLBAR — só no tenant de assessoria/consórcio.
 *
 * ⭐ ELE IGNORA O MUNICÍPIO DO MENU LATERAL, e isso é decisão do dono: a agenda
 * é ferramenta da assessoria inteira, não da cidade que está em acesso. Trocar o
 * escopo global REMONTA o dashboard (`key={escopo}` em `dashboard/layout.tsx`) e
 * leva a pessoa para a home — perder a semana que ela estava olhando só para
 * conferir a agenda da cidade vizinha é caro demais. Aqui a escolha é local.
 *
 * ⚠️ TODOS MARCADOS É O PADRÃO, e "todos marcados" manda AUSÊNCIA de filtro para
 * a API — não a lista inteira de ids. Mandar a lista faria o recorte da tela
 * competir com o recorte da carteira, e o dia em que alguém ganhasse um
 * município novo ele não apareceria até a pessoa reabrir o filtro.
 *
 * ⚠️ A LISTA VEM DO `MunicipioContext`, que a barra lateral já carregou e já
 * filtrou por permissão. Rebuscar `GET /api/municipios` aqui duplicaria a
 * requisição E a regra de alcance — e a segunda cópia da regra é a que fica
 * para trás quando o alcance do usuário muda.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Building2, Check, ChevronDown, Search } from "lucide-react";

import { AcaoMini } from "@/components/ui/superficies";
import type { MunicipioEscolha } from "@/components/TransicaoMunicipio";
import { semAcento } from "./tipos";

export default function FiltroMunicipios({
  municipios, selecionados, onMudar,
}: {
  municipios: MunicipioEscolha[];
  /** Vazio = TODOS (e é o padrão). Ver a nota do cabeçalho. */
  selecionados: number[];
  onMudar: (ids: number[]) => void;
}) {
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const caixa = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: MouseEvent) => {
      if (!caixa.current?.contains(e.target as Node)) setAberto(false);
    };
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") setAberto(false); };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", tecla);
    };
  }, [aberto]);

  const visiveis = useMemo(() => {
    const q = semAcento(busca);
    return q ? municipios.filter((m) => semAcento(m.nome).includes(q)) : municipios;
  }, [municipios, busca]);

  const todos = selecionados.length === 0;
  const marcado = (id: number) => todos || selecionados.includes(id);

  const alternar = (id: number) => {
    /* Partindo de "todos", o primeiro clique DESMARCA aquele — que é o que a
       pessoa quer dizer ao clicar num item de uma lista toda marcada. */
    const base = todos ? municipios.map((m) => Number(m.id)) : selecionados;
    const novo = base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
    /* Lista cheia E lista vazia viram `[]`, que é "todos". A cheia porque é
       literalmente isso; a vazia porque desmarcar o último deixaria a tela sem
       nenhum compromisso e sem pista de por quê — voltar para "todos" é o único
       resultado do qual a pessoa consegue sair sozinha. */
    onMudar(novo.length === municipios.length ? [] : novo);
  };

  const rotulo = todos
    ? "Todos os municípios"
    : selecionados.length === 1
      ? municipios.find((m) => Number(m.id) === selecionados[0])?.nome || "1 município"
      : `${selecionados.length} municípios`;

  return (
    <div ref={caixa} className="relative">
      <button type="button" onClick={() => setAberto((v) => !v)}
              aria-haspopup="listbox" aria-expanded={aberto}
              className="bi-field flex h-8 max-w-[14rem] items-center gap-1.5 px-2 text-[12px]">
        <Building2 className="size-3.5 shrink-0" style={{ color: "var(--bi-muted)" }} />
        <span className="min-w-0 flex-1 truncate text-left">{rotulo}</span>
        <ChevronDown className="size-3 shrink-0" style={{ color: "var(--bi-faint)" }} />
      </button>

      {aberto && (
        <div role="listbox" aria-label="Filtrar por município"
             className="absolute left-0 top-9 z-40 w-72 rounded-2xl p-2"
             style={{ background: "var(--bi-surface)",
                      border: "1px solid var(--bi-line-strong)",
                      boxShadow: "var(--bi-shadow)" }}>
          <div className="relative mb-1.5">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2"
                    style={{ color: "var(--bi-faint)" }} />
            <input autoFocus value={busca} onChange={(e) => setBusca(e.target.value)}
                   placeholder="Buscar município"
                   className="bi-field h-8 w-full pl-7 pr-2 text-[12px]" />
          </div>
          {/* ⚠️ SÓ «Marcar todos», e não o par com «Desmarcar todos». Sem
              nenhum município marcado a tela mostraria zero compromissos — um
              estado que ninguém procura e do qual só se sai reabrindo o filtro.
              «Marcar todos» já é o botão de limpar. */}
          <div className="mb-1.5 flex items-center gap-1.5">
            <AcaoMini onClick={() => onMudar([])} disabled={todos}>
              Marcar todos
            </AcaoMini>
            <span className="ml-auto text-[10px]" style={{ color: "var(--bi-faint)" }}>
              {todos ? municipios.length : selecionados.length} de {municipios.length}
            </span>
          </div>
          <div className="bi-scroll max-h-64 space-y-0.5 overflow-y-auto">
            {visiveis.length === 0 && (
              <p className="px-1 py-3 text-center text-[11px]"
                 style={{ color: "var(--bi-faint)" }}>
                Nenhum município com esse nome.
              </p>
            )}
            {visiveis.map((m) => {
              const id = Number(m.id);
              const on = marcado(id);
              return (
                <button key={m.id} type="button" role="option" aria-selected={on}
                        onClick={() => alternar(id)}
                        className="flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left text-[12px] bi-hover">
                  <span className="grid size-4 shrink-0 place-items-center rounded"
                        style={{
                          background: on ? "var(--bi-accent-ink)" : "transparent",
                          border: on ? "none" : "1px solid var(--bi-line-strong)",
                        }}>
                    {on && <Check className="size-3" style={{ color: "var(--bi-cta-ink)" }} />}
                  </span>
                  <span className="min-w-0 flex-1 truncate">
                    {m.nome}{m.uf ? ` - ${m.uf}` : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
