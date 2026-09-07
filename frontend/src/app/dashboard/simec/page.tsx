"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import {
  Loader2, ExternalLink, BarChart3, Wallet, CalendarDays, ChevronDown, ChevronRight,
  FileText,
} from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import api from "@/lib/api";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { formatCurrency, formatDate } from "@/lib/utils";
import { TituloTela } from "@/components/TituloTela";

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
/** O INSTRUMENTO, não o pagamento — o que a aba de Liberações não mostra.
 *  `vencido` e `dias_vigencia` vêm calculados do backend de propósito: aqui
 *  "vencido" é alerta, e alerta não pode depender do relógio do navegador. */
interface Termo {
  processo?: string;
  nr_documento?: string;
  tipo_documento?: string;
  tipo_objeto?: string;
  dt_validacao?: string;
  periodo_pagamento?: string;
  vigencia_txt?: string;
  dt_vigencia?: string;
  dias_vigencia?: number | null;
  vencido: boolean;
  valor_termo?: number | null;
  quantidade_obra?: string;
  atualizado_em?: string;
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

/** O ANO de uma liberacao.
 *
 *  E o campo `ano` do proprio SIMEC — o exercicio do programa, que e o que o
 *  gestor chama de "o ano deste repasse". NAO e `dt_pgto`: parcela de exercicio
 *  anterior costuma ser paga no ano seguinte, e agrupar pela data do pagamento
 *  jogaria a liberacao de 2024 dentro de um grupo 2025.
 *
 *  E o MESMO campo que o filtro de anos ja usava. Filtro e agrupamento olhando
 *  campos diferentes e o defeito classico: o usuario filtra 2025 e ve um grupo
 *  2024 na tela. */
function anoDa(l: Liberacao): string {
  return l.ano != null ? String(l.ano) : "";
}

/** Em que grupo o termo cai na aba.
 *
 *  Agrupa por SITUAÇÃO e não por ano — ao contrário das liberações — porque o
 *  que o gestor precisa ver primeiro é o que já venceu. Foi esse o caso que
 *  motivou a coleta: um TC com cláusula suspensiva de R$ 3,15 mi vencido há 596
 *  dias, que só existia dentro do portal do MEC e não aparecia em lugar nenhum
 *  do PACTHA.
 *
 *  Termo sem data legível de vigência NÃO some: cai num grupo próprio no fim. O
 *  portal escreve a vigência como texto livre ("30/12/2024 - (-595 dias)") e nem
 *  sempre dá para extrair a data; esconder o termo por causa disso seria pior
 *  que mostrá-lo sem ela. */
const GRUPOS_TERMO = ["Vencidos", "Vigentes", "Sem vigência informada"] as const;
type GrupoTermo = (typeof GRUPOS_TERMO)[number];

function grupoDoTermo(t: Termo): GrupoTermo {
  if (t.vencido) return "Vencidos";
  return t.dt_vigencia ? "Vigentes" : "Sem vigência informada";
}

/** "vencido há 596 dias" / "vence em 43 dias".
 *  O número vem do backend (`dias_vigencia`) de propósito: é alerta, e alerta
 *  não pode depender do relógio do navegador. */
function prazoDoTermo(t: Termo): string {
  const d = t.dias_vigencia;
  if (d == null) return "";
  if (d < 0) return `vencido há ${Math.abs(d)} dia(s)`;
  if (d === 0) return "vence hoje";
  return `vence em ${d} dia(s)`;
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

  const [tab, setTab] = useState<"dim" | "lib" | "termos">("dim");
  const [dimensoes, setDimensoes] = useState<Dimensao[]>([]);
  const [liberacoes, setLiberacoes] = useState<Liberacao[]>([]);
  const [termos, setTermos] = useState<Termo[]>([]);
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [loading, setLoading] = useState(false);

  // Filtros das liberacoes
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [progsSel, setProgsSel] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  /* Recolhido por ANO. Guarda o que esta FECHADO e nao o que esta aberto: assim
     um ano novo que chegue na proxima coleta do SIMEC nasce ABERTO, em vez de
     nascer invisivel. */
  const [anosFechados, setAnosFechados] = useState<Set<string>>(new Set());

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const [d, l, r, t] = await Promise.all([
        api.get<{ items: Dimensao[] }>("/simec/dimensoes", { params: { municipio_id: municipioId } }),
        api.get<{ items: Liberacao[] }>("/simec/liberacoes", { params: { municipio_id: municipioId } }),
        api.get<Resumo>("/simec/resumo", { params: { municipio_id: municipioId } }),
        api.get<{ items: Termo[] }>("/simec/termos", { params: { municipio_id: municipioId } }),
      ]);
      setDimensoes(d.data.items);
      setLiberacoes(l.data.items);
      setResumo(r.data);
      setTermos(t.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId, buscar]);

  /** Os anos que EXISTEM no resultado, para o dropdown nao oferecer ano vazio.
   *  Sai de `anoDa`, o mesmo do agrupamento. */
  const anosDisponiveis = useMemo(
    () => Array.from(new Set(liberacoes.map(anoDa).filter(Boolean))).sort((a, b) => b.localeCompare(a)),
    [liberacoes]
  );
  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anosDisponiveis, setAnosSel);
  const progOptions = useMemo(
    () => Array.from(new Set(liberacoes.map((l) => l.programa).filter(Boolean))).sort(),
    [liberacoes]
  );

  const displayLib = useMemo(() => {
    let arr = liberacoes;
    if (anosSel.length) arr = arr.filter((l) => anosSel.includes(anoDa(l)));
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

  /** Agrupado por ano, do mais recente para o mais antigo.
   *
   *  As tres camadas do Painel: fundo cinza da pagina -> cartao BRANCO do ano
   *  -> itens cinza dentro. E o desenho que o dono aprovou nas Emendas
   *  Estaduais e nas Propostas do TransfereGov.
   *
   *  Liberacao sem ano legivel nao e escondida: cai num grupo "Sem ano" no fim.
   *  Sumir com um pagamento porque o SIMEC nao trouxe o exercicio seria pior
   *  que mostra-lo separado. */
  const porAno = useMemo(() => {
    const m = new Map<string, Liberacao[]>();
    for (const l of displayLib) {
      const a = anoDa(l) || "Sem ano";
      (m.get(a) ?? m.set(a, []).get(a)!).push(l);
    }
    return Array.from(m.entries()).sort((x, y) =>
      x[0] === "Sem ano" ? 1 : y[0] === "Sem ano" ? -1 : y[0].localeCompare(x[0]));
  }, [displayLib]);

  /** Termos por situação, na ordem fixa de GRUPOS_TERMO (vencidos primeiro).
   *  Grupo sem nenhum termo não vira cartão vazio. */
  const porGrupoTermo = useMemo(() => {
    const m = new Map<GrupoTermo, Termo[]>();
    for (const t of termos) {
      const g = grupoDoTermo(t);
      (m.get(g) ?? m.set(g, []).get(g)!).push(t);
    }
    return GRUPOS_TERMO.filter((g) => m.has(g)).map((g) => [g, m.get(g)!] as const);
  }, [termos]);

  const totalTermos = useMemo(
    () => termos.reduce((s, t) => s + (t.valor_termo || 0), 0),
    [termos]
  );
  const vencidosTermos = useMemo(() => termos.filter((t) => t.vencido).length, [termos]);

  const alternarAno = (a: string) =>
    setAnosFechados((prev) => {
      const n = new Set(prev);
      if (n.has(a)) n.delete(a); else n.add(a);
      return n;
    });

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um município.</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <TituloTela>SIMEC - PAR (MEC)</TituloTela>
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
        <button
          onClick={() => setTab("termos")}
          className="-mb-px border-b-2 px-3 py-2 text-[13px] font-medium"
          style={estiloAba(tab === "termos")}
        >
          <FileText className="mr-1 inline size-4" />
          Termos de Compromisso ({termos.length})
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
           baixo) sem existir tabela. Nenhuma contagem se perdeu.

           SEM AGRUPAMENTO POR ANO, de proposito: a sintese do PAR nao tem ano.
           Cada dimensao aparece UMA vez, com o diagnostico vigente; o unico
           campo de data e `atualizado_em`, que e quando o robo coletou — todas
           as linhas trariam o mesmo ano e o "grupo" seria a lista inteira.
           Aqui entra so o cartao BRANCO em volta, que e o que faltava para as
           tres camadas (fundo cinza -> cartao branco -> itens cinza). */
        <div className="space-y-2">
          {dimensoes.length === 0 ? (
            <Vazio>Nenhuma dimensão encontrada.</Vazio>
          ) : (
            <Bloco className="p-3">
              <BlocoHead
                icon={BarChart3}
                titulo="Diagnóstico por dimensão"
                sub={`${dimensoes.length} dimensão(ões) avaliadas`}
                right={
                  <span className="bi-num text-[13px]">
                    {dimensoes.reduce((s, d) => s + d.total, 0)} indicadores
                  </span>
                }
              />
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
            </Bloco>
          )}
          <p className="px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            Escala: 4 = situação boa / 3 = adequada / 2 = a melhorar / 1 = crítica.
            Fonte: SIMEC público (PAR diagnóstico).
          </p>
        </div>
      ) : tab === "lib" ? (
        <div className="space-y-3">
          {/* Filtros das liberacoes: mesmo comportamento, sem a moldura de
              cartao — na identidade nova o cartao e do dado, nao do controle. */}
          <div className="flex flex-wrap items-center gap-3">
            <MultiSelect opcoes={anosDisponiveis} valor={anosSel} onChange={setAnosSel} atalhos={atalhosAnos()} placeholder="Todos os anos" rotuloTodos="Todos" formatarResumo={resumoAnos} ariaLabel="Anos" className="w-44" />
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
               tabela nem mostrava.

               AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO por ano
               -> itens cinza dentro. Os itens abaixo nao mudaram nada com o
               agrupamento; so ganharam o cartao do exercicio em volta. */
            <div className="space-y-3">
              {porAno.map(([ano, doAno]) => {
                const fechado = anosFechados.has(ano);
                const totalAno = doAno.reduce((s, l) => s + (l.valor || 0), 0);
                return (
                <Bloco key={ano} className="p-3">
                  <button type="button" onClick={() => alternarAno(ano)}
                          className="text-left" aria-expanded={!fechado}>
                    <BlocoHead
                      icon={fechado ? ChevronRight : ChevronDown}
                      titulo={ano}
                      sub={`${doAno.length} liberação(ões)`}
                      right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                      className={fechado ? "mb-0" : undefined}
                    />
                  </button>
                  {!fechado && (
                  <Lista>
              {doAno.map((l, i) => (
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
                </Bloco>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        /* TERMOS DE COMPROMISSO — o INSTRUMENTO. As duas abas ao lado mostram o
           diagnóstico (PAR) e o dinheiro que saiu (liberações); faltava o termo
           que origina o repasse. Um município pode ter TC vigente com ZERO
           liberação, e é justamente esse o caso que olhar só as OBs esconde.

           Agrupado por SITUAÇÃO (vencidos primeiro), não por ano: aqui a
           pergunta não é "quanto veio em 2026" e sim "o que está vencido". */
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            <span>
              <strong style={{ color: "var(--bi-text)" }}>{termos.length}</strong> termo(s)
              {vencidosTermos > 0 && (
                <> · <strong style={{ color: "var(--bi-text)" }}>{vencidosTermos}</strong> vencido(s)</>
              )}
            </span>
            <span className="bi-num" style={{ color: "var(--bi-text)" }}>{formatCurrency(totalTermos)}</span>
          </div>

          {termos.length === 0 ? (
            <Vazio>Nenhum termo de compromisso encontrado.</Vazio>
          ) : (
            <div className="space-y-3">
              {porGrupoTermo.map(([grupo, doGrupo]) => (
                <Bloco key={grupo} className="p-3">
                  <BlocoHead
                    icon={FileText}
                    titulo={grupo}
                    sub={`${doGrupo.length} termo(s)`}
                    right={
                      <span className="bi-num text-[13px]">
                        {formatCurrency(doGrupo.reduce((s, t) => s + (t.valor_termo || 0), 0))}
                      </span>
                    }
                  />
                  <Lista>
                    {doGrupo.map((t, i) => (
                      <ItemLinha
                        key={i}
                        titulo={t.tipo_documento || t.tipo_objeto || "Termo de Compromisso"}
                        /* Nem todo termo tem valor: os de obra trazem
                           "Quantidade de Obra" na mesma coluna. Cair para ela
                           evita um "R$ 0,00" que seria mentira. */
                        valor={t.valor_termo != null
                          ? formatCurrency(t.valor_termo)
                          : (t.quantidade_obra || "—")}
                        meta={
                          <>
                            {t.tipo_objeto && <Selo title="Tipo do objeto">{t.tipo_objeto}</Selo>}
                            {t.nr_documento && (
                              <Selo title="Nº do documento no SIMEC">nº {t.nr_documento}</Selo>
                            )}
                            {prazoDoTermo(t) && <span>{prazoDoTermo(t)}</span>}
                          </>
                        }
                      >
                        <Campos
                          campos={[
                            { rotulo: "Processo", valor: t.processo || "—", title: t.processo || undefined },
                            {
                              rotulo: "Vigência",
                              /* A data extraída quando existe; senão o texto cru
                                 do portal, que é o que sobra. */
                              valor: t.dt_vigencia ? formatDate(t.dt_vigencia) : (t.vigencia_txt || "—"),
                              tom: t.vencido ? "critico" : undefined,
                              title: t.vigencia_txt || undefined,
                            },
                            {
                              rotulo: "Data da validação",
                              valor: t.dt_validacao ? formatDate(t.dt_validacao) : "—",
                              title: t.atualizado_em
                                ? `Coletado do SIMEC em ${dataDoCarimbo(t.atualizado_em)}`
                                : undefined,
                            },
                            { rotulo: "Período do pagamento", valor: t.periodo_pagamento || "—" },
                          ]}
                        />
                      </ItemLinha>
                    ))}
                  </Lista>
                </Bloco>
              ))}
            </div>
          )}
          <p className="px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            O instrumento (processo, objeto, vigência e valor) — os pagamentos estão em
            “Liberações de recursos”. Fonte: SIMEC público (Termos de Compromisso do PAR).
          </p>
        </div>
      )}
    </div>
  );
}
