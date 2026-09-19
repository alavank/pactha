"use client";

/* CONSOLIDADO › RELATÓRIOS — PR 3 da série (19/09/2026).
 *
 * RECURSOS POR MUNICÍPIO: estaduais, voluntárias federais e emendas federais,
 * lado a lado, ordenáveis por qualquer coluna. E a MATRIZ parlamentar ×
 * município, que só existe em planilha (40+ colunas não cabem numa tela).
 *
 * ⚠️ NÃO HÁ COLUNA DE TOTAL, e a tela diz por quê: as fontes se sobrepõem — a
 * voluntária que nasceu de emenda aparece nas voluntárias E nas emendas. Somar
 * as colunas contaria o mesmo dinheiro duas vezes, e o total do cliente sairia
 * errado justamente no relatório que vai para fora.
 */

import React, { useEffect, useMemo, useState } from "react";
import { FileSpreadsheet, Grid3x3, Loader2, TableProperties } from "lucide-react";

import api from "@/lib/api";
import { formatCurrencyShort, formatInt } from "@/lib/bi-format";
import { anosOpcoes, atalhosAnos, resumoAnos } from "@/lib/periodo";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Aviso, BOTAO_SEC, Bloco, BlocoHead, Campos, ESTILO_SEC, ItemLinha, Lista, Selo, Vazio,
} from "@/components/ui/superficies";
import { baixarArquivo, mensagemDeErro } from "./baixar";

interface Linha {
  municipio_id: number; nome: string; uf: string;
  estaduais: { n: number; valor: number };
  voluntarias: { n: number; valor: number };
  emendas: { n: number; valor: number; sem_pagamento: number; estado: string | null };
}
type Ordem = "nome" | "estaduais" | "voluntarias" | "emendas" | "sem_pagamento";

const ANOS = anosOpcoes();
const ATALHOS = atalhosAnos();
const ORDENS: { valor: Ordem; label: string }[] = [
  { valor: "emendas", label: "Emendas federais" },
  { valor: "voluntarias", label: "Voluntárias" },
  { valor: "estaduais", label: "Estaduais" },
  { valor: "sem_pagamento", label: "Sem pagamento" },
  { valor: "nome", label: "Nome" },
];

export function RelatoriosCarteira() {
  const [anos, setAnos] = useState<string[]>([]);
  const [linhas, setLinhas] = useState<Linha[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ordem, setOrdem] = useState<Ordem>("emendas");
  const [baixando, setBaixando] = useState<string | null>(null);

  const qs = useMemo(() => {
    const q = new URLSearchParams();
    anos.forEach((a) => q.append("anos", a));
    return q.toString();
  }, [anos]);

  useEffect(() => {
    let vivo = true;
    api.get<{ linhas: Linha[] }>(`/consolidado/relatorios/recursos?${qs}`)
      .then((r) => { if (vivo) { setLinhas(r.data.linhas); setErro(null); } })
      .catch(() => { if (vivo) setErro("Não foi possível montar o relatório."); });
    return () => { vivo = false; };
  }, [qs]);

  const ordenadas = useMemo(() => {
    const xs = [...(linhas ?? [])];
    const chave: Record<Ordem, (l: Linha) => number | string> = {
      nome: (l) => l.nome,
      estaduais: (l) => -l.estaduais.valor,
      voluntarias: (l) => -l.voluntarias.valor,
      emendas: (l) => -l.emendas.valor,
      sem_pagamento: (l) => -l.emendas.sem_pagamento,
    };
    return xs.sort((a, b) => {
      const x = chave[ordem](a), y = chave[ordem](b);
      return x < y ? -1 : x > y ? 1 : a.nome.localeCompare(b.nome);
    });
  }, [linhas, ordem]);

  const baixar = async (tipo: "recursos" | "matriz") => {
    setBaixando(tipo);
    try {
      await baixarArquivo(`/consolidado/relatorios/${tipo}/exportar?${qs}`,
                          tipo === "recursos" ? "recursos_por_municipio.xlsx" : "parlamentares_x_municipios.xlsx");
    } catch (e) {
      setErro(mensagemDeErro(e));
    } finally {
      setBaixando(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>Período</label>
          <MultiSelect className="min-w-[190px]" opcoes={ANOS} valor={anos} onChange={setAnos}
                       formatarResumo={resumoAnos} placeholder="Todos os anos" rotuloTodos="Todos"
                       ariaLabel="Anos" atalhos={ATALHOS} />
        </div>
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                onClick={() => baixar("recursos")} disabled={!!baixando || !linhas}>
          {baixando === "recursos" ? <Loader2 className="size-3.5 animate-spin" /> : <FileSpreadsheet className="size-3.5" />}
          Planilha de recursos
        </button>
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                onClick={() => baixar("matriz")} disabled={!!baixando}
                title="Uma linha por parlamentar, uma coluna por município da carteira">
          {baixando === "matriz" ? <Loader2 className="size-3.5 animate-spin" /> : <Grid3x3 className="size-3.5" />}
          Matriz parlamentar × município
        </button>
      </div>

      {erro && <Aviso tom="atencao" titulo={erro} className="" />}

      <Bloco className="p-3">
        <BlocoHead icon={TableProperties} titulo="Recursos por município"
                   sub={`${anos.length ? resumoAnos(anos) : "todos os anos"} · estaduais, voluntárias federais e emendas federais, lado a lado`} />
        <div className="mb-2 flex flex-wrap items-center gap-1.5 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          Ordenar por
          {ORDENS.map((o) => (
            <button key={o.valor} type="button" onClick={() => setOrdem(o.valor)}
                    aria-pressed={ordem === o.valor}>
              <Selo tom={ordem === o.valor ? "acento" : "neutro"}>{o.label}</Selo>
            </button>
          ))}
        </div>
        {!linhas && !erro ? (
          <div className="flex items-center gap-2 px-1 py-6 text-[12px]" style={{ color: "var(--bi-faint)" }}>
            <Loader2 className="size-4 animate-spin" /> montando o relatório… (varre todos os municípios)
          </div>
        ) : ordenadas.length === 0 ? (
          <Vazio>Nenhum município na carteira.</Vazio>
        ) : (
          <Lista>
            {ordenadas.map((l) => (
              <ItemLinha key={l.municipio_id}
                titulo={<span className="flex items-center gap-2">{l.nome} {l.uf && <Selo>{l.uf}</Selo>}</span>}>
                <Campos cols={4} campos={[
                  { rotulo: "Convênios estaduais",
                    valor: l.estaduais.n ? `${formatInt(l.estaduais.n)} · ${formatCurrencyShort(l.estaduais.valor)}` : "nenhum" },
                  { rotulo: "Voluntárias federais",
                    valor: l.voluntarias.n ? `${formatInt(l.voluntarias.n)} · ${formatCurrencyShort(l.voluntarias.valor)}` : "nenhuma" },
                  { rotulo: "Emendas federais (prefeitura)",
                    valor: l.emendas.n ? `${formatInt(l.emendas.n)} · ${formatCurrencyShort(l.emendas.valor)}`
                      : l.emendas.estado === "sem_coleta" ? "sem coleta" : "nenhuma" },
                  { rotulo: "Emendas sem pagamento",
                    valor: l.emendas.sem_pagamento ? `${l.emendas.sem_pagamento} de ${l.emendas.n}` : "—",
                    tom: l.emendas.sem_pagamento ? "atencao" : "normal" },
                ]} />
              </ItemLinha>
            ))}
          </Lista>
        )}
        <p className="mt-2 px-1 text-[10px] leading-relaxed" style={{ color: "var(--bi-faint)" }}>
          Sem coluna de total, de propósito: as fontes se sobrepõem — a voluntária que nasceu de
          emenda aparece nas voluntárias e nas emendas federais. Cada coluna é a conta da tela do
          município (Painel e aba Federais).
        </p>
      </Bloco>
    </div>
  );
}
