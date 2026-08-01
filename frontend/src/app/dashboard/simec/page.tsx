"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import { Loader2, ExternalLink, BarChart3, Wallet, CalendarDays } from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import api from "@/lib/api";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Campos, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { formatCurrency, formatDate } from "@/lib/utils";

interface Dimensao {
  dimensao: string;
  score_4: number; score_3: number; score_2: number; score_1: number; score_na: number;
  total: number;
  atualizado_em?: string;
}
interface Liberacao {
  programa: string;
  programa_full: string;
  dt_pgto?: string;
  ob?: string;
  valor?: number | null;
  parcela?: string;
  descricao?: string;
  banco?: string;
  agencia?: string;
  conta?: string;
  ano?: number;
  atualizado_em?: string;
}
interface Resumo {
  por_programa: Array<{ programa: string; qtde: number; total: number }>;
  por_ano: Array<{ ano: number; qtde: number; total: number }>;
  total_geral: number;
}

const PORTAL = "https://simec.mec.gov.br/cte/relatoriopublico/principal.php";

/** Cor no score SO quando ele e um alerta.
 *
 *  A tabela antiga pintava a coluna inteira: score 4 e 3 em verde, 2 em amarelo,
 *  1 em vermelho. Com quatro colunas coloridas em todas as linhas, nenhuma cor
 *  informava nada — o verde do "esta bom" gritava tanto quanto o vermelho do
 *  "esta critico". Aqui so recebe cor o que exige acao: indicador com nota 1
 *  (situacao critica) e nota 2 (a melhorar). Nota boa e ausencia de alerta, e
 *  ausencia de alerta se mostra em preto, nao em verde.
 *
 *  Zero tambem nao pinta: "nenhum indicador critico" nao e um alerta. */
function scoreTom(nota: 1 | 2 | 3 | 4, qtde: number): "normal" | "atencao" | "critico" {
  if (!qtde) return "normal";
  if (nota === 1) return "critico";
  if (nota === 2) return "atencao";
  return "normal";
}

/** `atualizado_em` chega como TIMESTAMPTZ ISO ("2026-07-30T03:12:00+00:00").
 *  `formatDate` concatena "T00:00:00" na string que recebe, entao devolveria
 *  Invalid Date nesse formato — dai o corte nos 10 primeiros caracteres. */
function dataDoCarimbo(iso?: string | null): string {
  return iso ? formatDate(iso.slice(0, 10)) : "";
}

/** Aba ativa em tinta forte, inativa em cinza claro. Antes era violeta em cima
 *  de violeta; agora a hierarquia vem do contraste do texto, nao da cor. */
function estiloAba(ativa: boolean): React.CSSProperties {
  return {
    color: ativa ? "var(--bi-text)" : "var(--bi-faint)",
    borderColor: ativa ? "var(--bi-text)" : "transparent",
  };
}

export default function SimecPage() {
  const { municipioId } = useMunicipio();

  const [tab, setTab] = useState<"dim" | "lib">("dim");
  const [dimensoes, setDimensoes] = useState<Dimensao[]>([]);
  const [liberacoes, setLiberacoes] = useState<Liberacao[]>([]);
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [loading, setLoading] = useState(false);

  // Filtros das liberacoes
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [progsSel, setProgsSel] = useState<string[]>([]);
  const [search, setSearch] = useState("");

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const [d, l, r] = await Promise.all([
        api.get<{ items: Dimensao[] }>("/simec/dimensoes", { params: { municipio_id: municipioId } }),
        api.get<{ items: Liberacao[] }>("/simec/liberacoes", { params: { municipio_id: municipioId } }),
        api.get<Resumo>("/simec/resumo", { params: { municipio_id: municipioId } }),
      ]);
      setDimensoes(d.data.items);
      setLiberacoes(l.data.items);
      setResumo(r.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId, buscar]);

  const anoOptions = useMemo(
    () => Array.from(new Set(liberacoes.map((l) => l.ano).filter(Boolean))).sort((a, b) => (b! - a!)).map(String),
    [liberacoes]
  );
  const progOptions = useMemo(
    () => Array.from(new Set(liberacoes.map((l) => l.programa).filter(Boolean))).sort(),
    [liberacoes]
  );

  const displayLib = useMemo(() => {
    let arr = liberacoes;
    if (anosSel.length) arr = arr.filter((l) => l.ano && anosSel.includes(String(l.ano)));
    if (progsSel.length) arr = arr.filter((l) => progsSel.includes(l.programa));
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      arr = arr.filter((l) =>
        (l.descricao || "").toLowerCase().includes(q) ||
        (l.ob || "").toLowerCase().includes(q) ||
        (l.programa_full || "").toLowerCase().includes(q)
      );
    }
    return arr;
  }, [liberacoes, anosSel, progsSel, search]);

  const displayTotal = useMemo(
    () => displayLib.reduce((s, l) => s + (l.valor || 0), 0),
    [displayLib]
  );

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um município.</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-base-content">SIMEC - PAR (MEC)</h1>
          <p className="text-sm" style={{ color: "var(--bi-muted)" }}>
            Plano de Ações Articuladas + liberações de recursos federais (PNAE, PNATE, QUOTA, PDDE, etc.)
          </p>
        </div>
        <a href={PORTAL} target="_blank" rel="noreferrer noopener"
           className="inline-flex items-center gap-1 text-xs hover:underline"
           style={{ color: "var(--bi-muted)" }}>
          <ExternalLink className="size-3" /> Portal oficial SIMEC
        </a>
      </div>

      {/* Resumo no topo */}
      {resumo && !loading && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Numero
            icon={Wallet}
            rotulo="Total liberado"
            valor={formatCurrency(resumo.total_geral)}
            sub={`${liberacoes.length} pagamentos`}
          />
          <Numero
            icon={BarChart3}
            rotulo="Programas"
            valor={resumo.por_programa.length}
            sub={resumo.por_programa.slice(0, 4).map((p) => p.programa).join(", ")}
          />
          <Numero
            icon={CalendarDays}
            rotulo="Anos cobertos"
            valor={resumo.por_ano.length}
            sub={resumo.por_ano.length
              ? `${Math.min(...resumo.por_ano.map((a) => a.ano))} - ${Math.max(...resumo.por_ano.map((a) => a.ano))}`
              : "-"}
          />
        </div>
      )}

      {/* Abas */}
      <div className="flex gap-1 border-b" style={{ borderColor: "var(--bi-line)" }}>
        <button
          onClick={() => setTab("dim")}
          className="-mb-px border-b-2 px-3 py-2 text-[13px] font-medium"
          style={estiloAba(tab === "dim")}
        >
          <BarChart3 className="mr-1 inline size-4" />
          Síntese do PAR ({dimensoes.length} dimensões)
        </button>
        <button
          onClick={() => setTab("lib")}
          className="-mb-px border-b-2 px-3 py-2 text-[13px] font-medium"
          style={estiloAba(tab === "lib")}
        >
          <Wallet className="mr-1 inline size-4" />
          Liberações de recursos ({liberacoes.length})
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center">
          <Loader2 className="mx-auto size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      ) : tab === "dim" ? (
        /* SÍNTESE DO PAR — era uma tabela de 7 colunas com quatro delas pintadas
           de fundo. Virou cartao por dimensao: o nome e o titulo, o total de
           indicadores ocupa o canto do valor e as cinco contagens de score vao
           para <Campos>, em posicoes FIXAS — e o que mantem a varredura vertical
           que a tabela dava (descer o olho pela coluna "score 1" de cima a
           baixo) sem existir tabela. Nenhuma contagem se perdeu. */
        <div className="space-y-2">
          {dimensoes.length === 0 ? (
            <Vazio>Nenhuma dimensão encontrada.</Vazio>
          ) : (
            <Lista>
              {dimensoes.map((d, i) => (
                <ItemLinha
                  key={i}
                  titulo={d.dimensao}
                  /* O total nao e dinheiro: sem o rotulo junto, um "18" solto no
                     canto nao diz o que conta. */
                  valor={`${d.total} indicadores`}
                  meta={
                    d.atualizado_em
                      ? <span>coletado em {dataDoCarimbo(d.atualizado_em)}</span>
                      : undefined
                  }
                >
                  <Campos
                    campos={[
                      { rotulo: "Score 4 · boa", valor: d.score_4, tom: scoreTom(4, d.score_4),
                        title: "Indicadores com pontuação 4 (situação boa)" },
                      { rotulo: "Score 3 · adequada", valor: d.score_3, tom: scoreTom(3, d.score_3),
                        title: "Indicadores com pontuação 3 (situação adequada)" },
                      { rotulo: "Score 2 · a melhorar", valor: d.score_2, tom: scoreTom(2, d.score_2),
                        title: "Indicadores com pontuação 2 (situação a melhorar)" },
                      { rotulo: "Score 1 · crítica", valor: d.score_1, tom: scoreTom(1, d.score_1),
                        title: "Indicadores com pontuação 1 (situação crítica)" },
                      { rotulo: "N/A", valor: d.score_na,
                        title: "Indicadores sem pontuação atribuída" },
                    ]}
                  />
                </ItemLinha>
              ))}
            </Lista>
          )}
          <p className="px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            Escala: 4 = situação boa / 3 = adequada / 2 = a melhorar / 1 = crítica.
            Fonte: SIMEC público (PAR diagnóstico).
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Filtros das liberacoes: mesmo comportamento, sem a moldura de
              cartao — na identidade nova o cartao e do dado, nao do controle. */}
          <div className="flex flex-wrap items-center gap-3">
            <MultiSelect opcoes={anoOptions} valor={anosSel} onChange={setAnosSel} atalhos={atalhosAnos()} placeholder="Todos os anos" rotuloTodos="Todos" formatarResumo={resumoAnos} ariaLabel="Anos" className="w-44" />
            <MultiSelect opcoes={progOptions} valor={progsSel} onChange={setProgsSel} placeholder="Todos os programas" rotuloTodos="Todos" ariaLabel="Programas" className="w-56" />
            <div className="min-w-[200px] flex-1">
              <Input placeholder="Buscar descrição/OB" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <Button variant="outline" onClick={() => { setAnosSel([]); setProgsSel([]); setSearch(""); }}>Limpar</Button>
          </div>

          <div className="flex items-center justify-between px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            <span>
              <strong style={{ color: "var(--bi-text)" }}>{displayLib.length}</strong> liberações
            </span>
            <span className="bi-num" style={{ color: "var(--bi-text)" }}>{formatCurrency(displayTotal)}</span>
          </div>

          {displayLib.length === 0 ? (
            <Vazio>Nenhuma liberação encontrada.</Vazio>
          ) : (
            /* LIBERAÇÕES — eram 7 colunas de 11px com a descricao espremida em
               320px e a sigla do programa pintada de uma cor por programa (cor
               como enfeite: PNATE violeta, PNAE amarelo, sem nada disso
               significar alerta). Agora a descricao e o titulo e tem a linha
               inteira; o programa e um selo cinza que guarda o nome completo no
               title; e data, OB, banco/agencia e conta descem para a grade
               alinhada. Continuam todas as colunas, mais ano e parcela, que a
               tabela nem mostrava. */
            <Lista>
              {displayLib.map((l, i) => (
                <ItemLinha
                  key={i}
                  titulo={l.descricao || l.programa_full || l.programa || "Liberação sem descrição"}
                  valor={formatCurrency(l.valor || 0)}
                  meta={
                    <>
                      <Selo title={l.programa_full || l.programa}>{l.programa}</Selo>
                      {/* Parcela so aparece quando existe: no SIMEC ela vem vazia
                          na maioria das liberacoes, e uma coluna de travessoes
                          seria ruido em toda a lista. */}
                      {l.parcela && <Selo title="Parcela da liberação">parcela {l.parcela}</Selo>}
                      {l.ano != null && <span>{l.ano}</span>}
                      {/* O nome completo do programa so entra quando acrescenta
                          algo — quando a descricao ja e ele, repetir polui. */}
                      {l.programa_full && l.programa_full !== l.descricao && l.descricao && (
                        <span className="truncate">· {l.programa_full}</span>
                      )}
                    </>
                  }
                >
                  <Campos
                    campos={[
                      {
                        rotulo: "Data do pagamento",
                        valor: l.dt_pgto ? formatDate(l.dt_pgto) : "—",
                        title: l.atualizado_em ? `Coletado do SIMEC em ${dataDoCarimbo(l.atualizado_em)}` : undefined,
                      },
                      { rotulo: "OB", valor: l.ob || "—", title: l.ob ? `Ordem bancária ${l.ob}` : undefined },
                      {
                        rotulo: "Banco / agência",
                        valor: [l.banco, l.agencia].filter(Boolean).join(" / ") || "—",
                        title: [l.banco, l.agencia].filter(Boolean).join(" / ") || undefined,
                      },
                      { rotulo: "Conta", valor: l.conta || "—" },
                    ]}
                  />
                </ItemLinha>
              ))}
            </Lista>
          )}
        </div>
      )}
    </div>
  );
}
