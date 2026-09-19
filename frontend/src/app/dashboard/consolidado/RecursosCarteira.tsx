"use client";

/* CONSOLIDADO › RECURSOS — PR 3 da série (19/09/2026), revisto no mesmo dia.
 *
 * RECURSOS POR MUNICÍPIO: estaduais, voluntárias federais e emendas federais,
 * lado a lado, ordenáveis por qualquer coluna. E a MATRIZ parlamentar ×
 * município, que só existe em planilha (40+ colunas não cabem numa tela).
 *
 * A aba chamava "Relatórios". O dono estranhou: relatório sai em PDF/Excel de
 * qualquer tela. O que ela mostra é DINHEIRO POR FONTE — daí "Recursos" (e não
 * "Emendas": duas das três colunas de valor não são emenda).
 *
 * ⭐ A SOMA DA CARTEIRA NO TOPO (pedido do dono, 19/09/2026), coluna por coluna.
 * Cada cartão do topo é também o botão de ORDENAR: a primeira versão tinha chips
 * miúdos "Ordenar por" e o dono leu "Emendas federais" marcado como FILTRO,
 * porque os cartões abaixo continuavam mostrando estaduais. Agora a coluna que
 * ordena fica destacada no topo e em cada município.
 *
 * ⚠️ NÃO HÁ TOTAL GERAL, e a tela diz por quê: as fontes se sobrepõem — a
 * voluntária que nasceu de emenda aparece nas voluntárias E nas emendas. Somar
 * ENTRE as colunas contaria o mesmo dinheiro duas vezes. Somar DENTRO de uma
 * coluna é exato (município é disjunto) — é o que o topo faz.
 */

import React, { useEffect, useMemo, useState } from "react";
import { ArrowDownAZ, FileSpreadsheet, Grid3x3, Loader2, TableProperties } from "lucide-react";

import api from "@/lib/api";
import { formatCurrencyShort, formatInt, subVoluntarias } from "@/lib/bi-format";
import { anosOpcoes, atalhosAnos, resumoAnos } from "@/lib/periodo";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Aviso, BOTAO_SEC, Bloco, BlocoHead, Campos, ESTILO_SEC, ItemLinha, Lista, Selo, Vazio,
} from "@/components/ui/superficies";
import { baixarArquivo, mensagemDeErro } from "./baixar";

interface Linha {
  municipio_id: number; nome: string; uf: string;
  estaduais: { n: number; valor: number };
  // `n`/`valor` = CELEBRADAS (a conta do Painel desde 19/09/2026); o pipeline e as
  // rejeitadas vêm ao lado e nunca entram no número nem na soma.
  voluntarias: { n: number; valor: number; analise?: { n: number; valor: number }; rejeitadas_n?: number };
  emendas: {
    n: number; valor: number; fora_n: number; fora_valor: number;
    sem_pagamento: number; com_execucao: number; voluntarias_n: number;
    estado: string | null;
  };
}
type Ordem = "nome" | "estaduais" | "voluntarias" | "emendas" | "sem_pagamento";

const ANOS = anosOpcoes();
const ATALHOS = atalhosAnos();

const ROTULO: Record<Exclude<Ordem, "nome">, string> = {
  estaduais: "Convênios estaduais",
  voluntarias: "Voluntárias celebradas",
  emendas: "Emendas federais (à Prefeitura)",
  sem_pagamento: "Empenhadas sem pagamento",
};

const fmtN = (n: number, um: string, varios: string) => `${formatInt(n)} ${n === 1 ? um : varios}`;

/** Um cartão da soma da carteira, que é também o botão de ordenar. */
function CartaoSoma({ ativo, onClick, rotulo, valor, sub, tom }: {
  ativo: boolean; onClick: () => void; rotulo: string; valor: React.ReactNode;
  sub: React.ReactNode; tom?: "atencao";
}) {
  return (
    <button type="button" onClick={onClick} aria-pressed={ativo}
            title={ativo ? "Os municípios estão ordenados por esta coluna" : "Ordenar os municípios por esta coluna"}
            className="bi-card bi-hover px-3.5 py-3 text-left transition-colors"
            style={ativo ? {
              background: "var(--bi-accent-soft)",
              boxShadow: "inset 0 0 0 1.5px var(--bi-accent-ink)",
            } : undefined}>
      <div className="flex items-center justify-between gap-2 text-[11px] leading-tight"
           style={{ color: ativo ? "var(--bi-accent-ink)" : "var(--bi-muted)" }}>
        <span>{rotulo}</span>
        {ativo && <span className="shrink-0 text-[10px] font-semibold">↓ ordenando</span>}
      </div>
      <div className="bi-num mt-1.5 text-[20px] leading-none"
           style={{ color: tom === "atencao" ? "var(--bi-warn-ink)" : "var(--bi-text)" }}>
        {valor}
      </div>
      <div className="mt-1 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>{sub}</div>
    </button>
  );
}

export function RecursosCarteira() {
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

  /* A SOMA DE CADA COLUNA — nunca entre colunas (ver o cabeçalho). */
  const soma = useMemo(() => {
    const s = { est_n: 0, est_v: 0, vol_n: 0, vol_v: 0, an_n: 0, an_v: 0, rej_n: 0,
                em_n: 0, em_v: 0, fora_n: 0, fora_v: 0, sp: 0, com_exec: 0, vol_em: 0,
                mun_vol_em: 0 };
    for (const l of linhas ?? []) {
      s.est_n += l.estaduais.n; s.est_v += l.estaduais.valor;
      s.vol_n += l.voluntarias.n; s.vol_v += l.voluntarias.valor;
      s.an_n += l.voluntarias.analise?.n ?? 0; s.an_v += l.voluntarias.analise?.valor ?? 0;
      s.rej_n += l.voluntarias.rejeitadas_n ?? 0;
      s.em_n += l.emendas.n; s.em_v += l.emendas.valor;
      s.fora_n += l.emendas.fora_n ?? 0; s.fora_v += l.emendas.fora_valor ?? 0;
      s.sp += l.emendas.sem_pagamento; s.com_exec += l.emendas.com_execucao ?? 0;
      s.vol_em += l.emendas.voluntarias_n ?? 0;
      if (l.emendas.voluntarias_n) s.mun_vol_em += 1;
    }
    return s;
  }, [linhas]);

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

  /* A coluna que ordena ganha destaque no cartão do município também: rótulo com
     a seta e valor na cor de acento — o olho desce por ela como numa tabela. */
  const destaque = (col: Exclude<Ordem, "nome">, valor: string): React.ReactNode =>
    ordem === col ? <span style={{ color: "var(--bi-accent-ink)", fontWeight: 600 }}>{valor}</span> : valor;
  const rotulo = (col: Exclude<Ordem, "nome">) => (ordem === col ? `↓ ${ROTULO[col]}` : ROTULO[col]);

  const semPagamento = (e: Linha["emendas"]) =>
    e.com_execucao ? `${e.sem_pagamento} de ${e.com_execucao} com execução no Portal`
      : e.n ? "sem execução no Portal" : "—";

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

      {linhas && linhas.length > 0 && (
        <section className="rounded-xl p-3"
                 style={{ background: "color-mix(in oklab, var(--bi-accent-soft) 55%, transparent)" }}>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2 px-1">
            <span className="text-[12px] font-semibold" style={{ color: "var(--bi-text)" }}>
              Soma da carteira · {fmtN(linhas.length, "município", "municípios")}
              <span className="font-normal" style={{ color: "var(--bi-muted)" }}>
                {" "}· {anos.length ? resumoAnos(anos) : "todos os anos"}
              </span>
            </span>
            <button type="button" onClick={() => setOrdem("nome")} aria-pressed={ordem === "nome"}
                    className="inline-flex items-center gap-1 text-[11px]"
                    style={{ color: ordem === "nome" ? "var(--bi-accent-ink)" : "var(--bi-muted)" }}>
              <ArrowDownAZ className="size-3.5" />
              {ordem === "nome" ? "em ordem alfabética" : "ordem alfabética"}
            </button>
          </div>
          <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
            <CartaoSoma ativo={ordem === "estaduais"} onClick={() => setOrdem("estaduais")}
                        rotulo={ROTULO.estaduais} valor={formatCurrencyShort(soma.est_v)}
                        sub={fmtN(soma.est_n, "convênio", "convênios")} />
            <CartaoSoma ativo={ordem === "voluntarias"} onClick={() => setOrdem("voluntarias")}
                        rotulo={ROTULO.voluntarias} valor={formatCurrencyShort(soma.vol_v)}
                        sub={[fmtN(soma.vol_n, "convênio", "convênios"),
                              subVoluntarias({ celebrada: { n: soma.vol_n, valor: soma.vol_v },
                                               analise: { n: soma.an_n, valor: soma.an_v },
                                               rejeitada: { n: soma.rej_n, valor: 0 } }, "valor"),
                             ].filter(Boolean).join(" · ")} />
            <CartaoSoma ativo={ordem === "emendas"} onClick={() => setOrdem("emendas")}
                        rotulo={ROTULO.emendas} valor={formatCurrencyShort(soma.em_v)}
                        sub={fmtN(soma.em_n, "emenda", "emendas") + (soma.fora_n
                          ? ` · + ${formatCurrencyShort(soma.fora_v)} a ${soma.fora_n} entidade(s), fora do valor`
                          : "")} />
            <CartaoSoma ativo={ordem === "sem_pagamento"} onClick={() => setOrdem("sem_pagamento")}
                        rotulo={ROTULO.sem_pagamento}
                        valor={soma.com_exec ? `${soma.sp} de ${soma.com_exec}` : "—"}
                        tom={soma.sp ? "atencao" : undefined}
                        sub={soma.com_exec
                          ? `só as ${formatInt(soma.com_exec)} emendas com execução no Portal da Transparência — Pix e Saúde não medem pagamento`
                          : "nenhuma emenda com execução no Portal no período"} />
          </div>
          {soma.vol_em > 0 && (
            <p className="mt-2 px-1 text-[10.5px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
              ⚠️ {fmtN(soma.vol_em, "voluntária celebrada aparece", "voluntárias celebradas aparecem")} também nas emendas
              ({fmtN(soma.mun_vol_em, "município", "municípios")}): é o convênio que nasceu de emenda.
              Por isso não há total geral — somar os cartões contaria esse dinheiro duas vezes.
            </p>
          )}
        </section>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={TableProperties} titulo="Recursos por município"
                   sub={`${anos.length ? resumoAnos(anos) : "todos os anos"} · cada cartão é um município; clique numa soma acima para ordenar`} />
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
                  { rotulo: rotulo("estaduais"),
                    valor: destaque("estaduais", l.estaduais.n
                      ? `${formatInt(l.estaduais.n)} · ${formatCurrencyShort(l.estaduais.valor)}` : "nenhum") },
                  { rotulo: rotulo("voluntarias"),
                    valor: destaque("voluntarias",
                      (l.voluntarias.n
                        ? `${formatInt(l.voluntarias.n)} · ${formatCurrencyShort(l.voluntarias.valor)}` : "nenhuma")
                      + (l.voluntarias.analise?.n ? ` (+${formatInt(l.voluntarias.analise.n)} em análise)` : "")),
                    title: [
                      l.voluntarias.analise?.n
                        ? `${l.voluntarias.analise.n} em análise somam ${formatCurrencyShort(l.voluntarias.analise.valor)}, fora do valor`
                        : "",
                      l.voluntarias.rejeitadas_n ? `${l.voluntarias.rejeitadas_n} rejeitada(s)` : "",
                      l.emendas.voluntarias_n
                        ? `${l.emendas.voluntarias_n} celebrada(s) também na coluna de emendas` : "",
                    ].filter(Boolean).join(" · ") || undefined },
                  { rotulo: rotulo("emendas"),
                    valor: destaque("emendas", l.emendas.n
                      ? `${formatInt(l.emendas.n)} · ${formatCurrencyShort(l.emendas.valor)}`
                        + (l.emendas.fora_n ? ` (+${l.emendas.fora_n} a entidade)` : "")
                      : l.emendas.estado === "sem_coleta" ? "sem coleta" : "nenhuma"),
                    title: l.emendas.fora_n
                      ? `${l.emendas.n} emendas; ${l.emendas.fora_n} a entidade(s) da cidade somam `
                        + `${formatCurrencyShort(l.emendas.fora_valor)} e ficam fora do valor da Prefeitura`
                      : undefined },
                  { rotulo: rotulo("sem_pagamento"),
                    valor: destaque("sem_pagamento", semPagamento(l.emendas)),
                    title: "Empenhada e sem nenhum pagamento (inclui resto a pagar). Só a emenda com "
                      + "execução no Portal da Transparência entra: Pix e Saúde não medem pagamento.",
                    tom: l.emendas.sem_pagamento ? "atencao" : "normal" },
                ]} />
              </ItemLinha>
            ))}
          </Lista>
        )}
        <p className="mt-2 px-1 text-[10px] leading-relaxed" style={{ color: "var(--bi-faint)" }}>
          Cada coluna é a conta da tela do município: estaduais e voluntárias como no Painel, emendas
          como na aba Federais. Voluntárias somam só o convênio celebrado (em execução, prestação de
          contas ou encerrado); a proposta em análise aparece entre parênteses e a rejeitada não conta.
        </p>
      </Bloco>
    </div>
  );
}
