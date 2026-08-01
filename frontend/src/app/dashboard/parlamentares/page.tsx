"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import { anosOpcoes, atalhosAnos, inicioDoMandato, resumoAnos } from "@/lib/periodo";
import {
  UserCircle2, Loader2, Search, ChevronDown, ChevronRight,
  Landmark, Building2, FileText, Eraser, Coins, HeartPulse, ArrowLeftRight,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ParlamentarItem {
  nome_normalizado: string;
  nome_display: string;
  total_lancamentos: number;
  valor_total: number;
  municipios: string[];
  por_fonte: { sigcon: number; voluntaria: number; emenda: number; plano_acao: number; pac: number; fns: number };
}

/** Uma linha da comparacao entre dois periodos. */
interface ComparaItem {
  nome_normalizado: string;
  nome_display: string;
  valor_a: number;
  valor_b: number;
  lancamentos_a: number;
  lancamentos_b: number;
  delta: number;
  /** null quando nao havia base no periodo A — de zero para R$ 300 mil nao e
   *  "+infinito%", e ENTRADA, e a tela escreve a palavra em vez de um numero. */
  delta_pct: number | null;
  situacao: "novo" | "saiu" | "igual" | "subiu" | "caiu";
}

interface ComparaResp {
  periodo_a: { anos: number[]; rotulo: string; total: number; parlamentares: number };
  periodo_b: { anos: number[]; rotulo: string; total: number; parlamentares: number };
  mesma_duracao: boolean;
  delta: number;
  delta_pct: number | null;
  items: ComparaItem[];
  total: number;
}

interface DetalheSigcon {
  id: number;
  municipio_nome: string;
  numero: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_total: number;
  valor_repasse: number;
  responsaveis: string | null;
  dt_vigencia_atual: string | null;
  ano: number | null;
  orgao: string | null;
}

interface DetalheVoluntaria {
  id: number;
  municipio_nome: string;
  numero_proposta: string;
  codigo_instrumento: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_global: number;
  valor_repasse: number;
  parlamentar: string | null;
  dt_fim_vigencia: string | null;
  orgao: string | null;
  situacao_contratacao: string | null;
}

interface DetalheEmenda {
  id: number;
  municipio_nome: string;
  nr_indicacao: string;
  ano: number | null;
  beneficiario: string | null;
  tipo_atendimento: string | null;
  valor_indicacao: number;
  status_indicacao: string | null;
  uo_sigla: string | null;
}

interface DetalhePlanoAcao {
  id: number;
  municipio_nome: string;
  codigo: string | null;
  emenda: string | null;
  parlamentar: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_total: number;
  valor_custeio: number;
  valor_investimento: number;
}

interface DetalhePac {
  id: number;
  municipio_nome: string;
  numero_proposta: string;
  programa: string | null;
  situacao: string | null;
  valor_total: number;
  emenda_parlamentar: string | null;
  proponente: string | null;
  objeto: string | null;
}

interface DetalheFns {
  id: number;
  municipio_nome: string;
  numero: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_total: number;
  orgao: string | null;
  ano: number | null;
  dt_vigencia_final: string | null;
  proponente: string | null;
}

interface ParlamentarDetalhe {
  nome_consulta: string;
  sigcon: DetalheSigcon[];
  voluntarias: DetalheVoluntaria[];
  emendas: DetalheEmenda[];
  plano_acao: DetalhePlanoAcao[];
  pac: DetalhePac[];
  fns: DetalheFns[];
  total_sigcon: number;
  total_voluntarias: number;
  total_emendas: number;
  total_plano_acao: number;
  total_pac: number;
  total_fns: number;
  total_geral: number;
  valor_total: number;
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "-";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

/** Variação entre os dois períodos.
 *
 *  Mostra a PALAVRA quando não há percentual honesto a mostrar: de zero para
 *  R$ 300 mil não é "+∞%", é uma entrada nova; e de R$ 200 mil para zero é o
 *  parlamentar ter parado de destinar, que é a informação que importa. */
function VariacaoBadge({ delta, pct, grande = false }: {
  delta: number; pct: number | null; grande?: boolean;
}) {
  const zero = Math.abs(delta) < 0.005;
  const sobe = delta > 0;
  const cor = zero ? "text-base-content/50" : sobe ? "text-success" : "text-error";
  const texto = zero ? "sem variação"
    : pct == null ? (sobe ? "novo no período" : "sem verba no período")
    : `${sobe ? "+" : "−"}${Math.abs(pct).toFixed(0)}%`;
  const seta = zero ? "—" : sobe ? "▲" : "▼";
  return (
    <span className={`inline-flex items-center gap-1 font-semibold ${cor} ${grande ? "text-sm" : "text-xs"}`}>
      <span aria-hidden>{seta}</span>
      <span>{texto}</span>
      {!zero && pct != null && (
        <span className="font-normal text-base-content/50">
          ({sobe ? "+" : "−"}{fmtMoney(Math.abs(delta)).replace("R$", "R$")})
        </span>
      )}
    </span>
  );
}

function ParlamentaresInner() {
  const municipioId = useMunicipio().municipioId || null;

  const [items, setItems] = useState<ParlamentarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  // PERIODO MULTI-ANO (o backend de /parlamentares ja aceitava `anos`; era so o
  // frontend que mandava um ano so). Vazio = todos.
  const [anosSel, setAnosSel] = useState<string[]>([]);
  // COMPARACAO entre dois conjuntos LIVRES de anos. Os chips sao atalho, nao
  // regra: da para comparar 2024 com 2025, ou dois anos com um, ou mandato
  // inteiro com mandato inteiro.
  const [compararOn, setCompararOn] = useState(false);
  const [anosA, setAnosA] = useState<string[]>([]);
  const [anosB, setAnosB] = useState<string[]>([]);
  const [comp, setComp] = useState<ComparaResp | null>(null);
  const [compErro, setCompErro] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [detailCache, setDetailCache] = useState<Record<string, ParlamentarDetalhe | "loading" | "error">>({});

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string | string[]> = {};
      if (municipioId) params.municipio_id = municipioId;
      if (search.trim()) params.q = search.trim();
      if (anosSel.length) params.anos = anosSel;
      const r = await api.get<{ items: ParlamentarItem[] }>("/parlamentares", { params });
      setItems(r.data.items);
    } catch (e) {
      console.error("erro parlamentares", e);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [municipioId, search, anosSel]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar();
  }, [carregar]);

  const compararPeriodos = useCallback(async () => {
    if (!compararOn || !anosA.length || !anosB.length) { setComp(null); setCompErro(null); return; }
    try {
      const params: Record<string, string | string[]> = { a: anosA, b: anosB };
      if (municipioId) params.municipio_id = municipioId;
      if (search.trim()) params.q = search.trim();
      const r = await api.get<ComparaResp>("/parlamentares/comparar", { params });
      setComp(r.data);
      setCompErro(null);
    } catch (e: unknown) {
      // O backend recusa ano repetido nos dois lados e periodo vazio. Mostrar a
      // razao dele, e nao "erro": o usuario tem como corrigir.
      const det = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setComp(null);
      setCompErro(det || "Não foi possível comparar os períodos.");
    }
  }, [compararOn, anosA, anosB, municipioId, search]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    compararPeriodos();
  }, [compararPeriodos]);

  /** Chips de atalho. Preenchem OS DOIS lados de uma vez — o caso comum tem
   *  que ser um clique, e a escolha livre continua ali para o resto. */
  const atalhosComparar = (() => {
    const y = new Date().getFullYear();
    const i = inicioDoMandato(y);
    const cheio = (ini: number) => [ini, ini + 1, ini + 2, ini + 3].map(String);
    const ateHoje = (ini: number) => [ini, ini + 1, ini + 2, ini + 3]
      .filter((a) => a <= y).map(String);
    return [
      { label: "Mandato atual × anterior", a: cheio(i - 4), b: ateHoje(i) },
      // Mesmo numero de anos dos dois lados: e a unica comparacao que responde
      // "este mandato vai melhor?" sem o vies de um lado ter o dobro do tempo.
      { label: "Mesmo trecho dos mandatos",
        a: Array.from({ length: ateHoje(i).length }, (_, k) => String(i - 4 + k)),
        b: ateHoje(i) },
      { label: "Este ano × ano passado", a: [String(y - 1)], b: [String(y)] },
    ];
  })();

  /** Com a comparacao ligada, quem manda na ORDEM e na COMPOSICAO da lista e o
   *  resultado da comparacao — inclusive quem so aparece em um dos periodos, que
   *  a lista normal (filtrada por outro recorte de anos) nao traria. Os cartoes
   *  seguem os mesmos; muda a fonte da lista. */
  const mapaComparacao = comp
    ? new Map(comp.items.map((i) => [i.nome_normalizado, i]))
    : null;

  const listaExibida: ParlamentarItem[] = comp
    ? comp.items.map((c) => {
        const orig = items.find((i) => i.nome_normalizado === c.nome_normalizado);
        return orig ?? {
          // Parlamentar que existe num dos periodos mas nao no recorte atual da
          // lista: mostra o que a comparacao sabe, sem inventar o resto.
          nome_normalizado: c.nome_normalizado,
          nome_display: c.nome_display,
          total_lancamentos: c.lancamentos_a + c.lancamentos_b,
          valor_total: c.valor_b || c.valor_a,
          municipios: [],
          por_fonte: { sigcon: 0, voluntaria: 0, emenda: 0, plano_acao: 0, pac: 0, fns: 0 },
        };
      })
    : items;

  const toggle = async (item: ParlamentarItem) => {
    const k = item.nome_normalizado;
    const ns = new Set(expandedKeys);
    if (ns.has(k)) {
      ns.delete(k);
      setExpandedKeys(ns);
      return;
    }
    ns.add(k);
    setExpandedKeys(ns);
    if (detailCache[k]) return;
    setDetailCache((c) => ({ ...c, [k]: "loading" }));
    try {
      const params: Record<string, string | string[]> = {};
      if (municipioId) params.municipio_id = municipioId;
      if (anosSel.length) params.anos = anosSel;
      // Backend faz ILIKE — usa o nome display original do registro
      const nome = encodeURIComponent(item.nome_display);
      const r = await api.get<ParlamentarDetalhe>(`/parlamentares/${nome}`, { params });
      setDetailCache((c) => ({ ...c, [k]: r.data }));
    } catch (e) {
      console.error("erro detalhe", e);
      setDetailCache((c) => ({ ...c, [k]: "error" }));
    }
  };

  const gerarPdf = async () => {
    setPdfLoading(true);
    try {
      const qs = new URLSearchParams();
      if (municipioId) qs.set("municipio_id", municipioId);
      if (search.trim()) qs.set("q", search.trim());
      // URLSearchParams: `append` por ano (o backend le list[int])
      anosSel.forEach((a) => qs.append("anos", a));
      const token = localStorage.getItem("pactha_token");
      const res = await fetch(`${api.defaults.baseURL}/export-pdf/parlamentares?${qs.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        credentials: "include",
      });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      alert("Não foi possível gerar o PDF. Tente novamente.");
    } finally {
      setPdfLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b border-base-300 pb-4">
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <UserCircle2 className="size-6 text-info" />
          Parlamentares
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Lista agregada dos parlamentares (deputados estaduais/federais e senadores)
          com lançamentos vinculados — convênios SIGCON-MG, propostas TransfereGov/SICONV,
          emendas estaduais, Transferência Especial / Plano de Ação (RP9), Seleção PAC e
          FNS (Fundo Municipal de Saúde, agrupado pelo proponente). Clique para ver os lançamentos.
        </p>
      </div>

      {/* Filtro */}
      <div className="bg-base-100 border rounded p-4 flex flex-wrap gap-3 items-end">
        <div className="flex-1 min-w-[200px]">
          <label className="text-xs text-base-content/70 mb-1 block">Buscar parlamentar</label>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Ex: Eduardo Azevedo"
            onKeyDown={(e) => { if (e.key === "Enter") carregar(); }}
          />
        </div>
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">
            Anos <span className="text-base-content/40">(um, alguns ou o mandato)</span>
          </label>
          <MultiSelect
            className="min-w-[190px]"
            opcoes={ANOS_OPCOES}
            valor={anosSel}
            onChange={(v) => { setAnosSel(v); setDetailCache({}); setExpandedKeys(new Set()); }}
            formatarResumo={resumoAnos}
            placeholder="Todos os anos"
            rotuloTodos="Todos"
            ariaLabel="Anos"
            atalhos={ATALHOS_ANOS}
          />
        </div>
        <Button onClick={carregar} className="bg-info hover:bg-info/90">
          <Search className="size-4 mr-1" /> Buscar
        </Button>
        <Button
          variant="outline"
          onClick={gerarPdf}
          disabled={pdfLoading || loading || items.length === 0}
          title="Gera um PDF com todos os lançamentos por parlamentar, respeitando a busca atual"
        >
          {pdfLoading ? <Loader2 className="size-4 mr-1 animate-spin" /> : <FileText className="size-4 mr-1" />}
          Gerar PDF
        </Button>
        <Button
          variant={compararOn ? "default" : "outline"}
          onClick={() => {
            const ligar = !compararOn;
            setCompararOn(ligar);
            // Liga ja com o atalho mais pedido preenchido: caixa vazia depois de
            // clicar em "Comparar" faz o usuario achar que nao funcionou.
            if (ligar && !anosA.length && !anosB.length) {
              setAnosA(atalhosComparar[0].a);
              setAnosB(atalhosComparar[0].b);
            }
          }}
          title="Compara quanto cada parlamentar destinou em dois períodos"
        >
          <ArrowLeftRight className="size-4 mr-1" /> Comparar períodos
        </Button>
        {(search || anosSel.length > 0 || municipioId || compararOn) && (
          <Button variant="outline" onClick={() => {
            setSearch(""); setAnosSel([]); setDetailCache({}); setExpandedKeys(new Set());
            setCompararOn(false); setAnosA([]); setAnosB([]); setComp(null); setCompErro(null);
          }}>
            <Eraser className="size-4 mr-1" /> Limpar
          </Button>
        )}
      </div>

      {/* ---------------- Painel de comparacao ---------------- */}
      {compararOn && (
        <div className="rounded-xl border border-primary/40 bg-primary/5 p-3 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-base-content/70">Atalhos:</span>
            {atalhosComparar.map((at) => {
              const ativo = JSON.stringify(anosA) === JSON.stringify(at.a)
                && JSON.stringify(anosB) === JSON.stringify(at.b);
              return (
                <button
                  key={at.label}
                  type="button"
                  onClick={() => { setAnosA(at.a); setAnosB(at.b); }}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
                    ativo ? "border-primary bg-primary text-primary-content"
                          : "border-base-300 text-base-content/70 hover:bg-base-200"}`}
                >
                  {at.label}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-52">
              <label className="text-xs font-medium text-base-content/70">Período A (referência)</label>
              <MultiSelect
                opcoes={ANOS_OPCOES} valor={anosA} onChange={setAnosA}
                atalhos={ATALHOS_ANOS} formatarResumo={resumoAnos}
                placeholder="Escolha os anos" rotuloTodos="Limpar"
                ariaLabel="Anos do período A"
              />
            </div>
            <ArrowLeftRight className="mb-2 size-4 shrink-0 text-base-content/40" />
            <div className="w-52">
              <label className="text-xs font-medium text-base-content/70">Período B (comparado)</label>
              <MultiSelect
                opcoes={ANOS_OPCOES} valor={anosB} onChange={setAnosB}
                atalhos={ATALHOS_ANOS} formatarResumo={resumoAnos}
                placeholder="Escolha os anos" rotuloTodos="Limpar"
                ariaLabel="Anos do período B"
              />
            </div>
          </div>

          {compErro && (
            <p className="text-xs font-medium text-error">{compErro}</p>
          )}

          {comp && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 border-t border-primary/20 pt-2 text-sm">
              <span className="text-base-content/60">
                {comp.periodo_a.rotulo}: <strong className="text-base-content">{fmtMoney(comp.periodo_a.total)}</strong>
              </span>
              <span className="text-base-content/40">→</span>
              <span className="text-base-content/60">
                {comp.periodo_b.rotulo}: <strong className="text-base-content">{fmtMoney(comp.periodo_b.total)}</strong>
              </span>
              <VariacaoBadge delta={comp.delta} pct={comp.delta_pct} grande />
              {/* Sem este aviso, "mandato atual x anterior" parece uma queda de
                  50% quando na verdade um lado tem 2 anos e o outro tem 4. */}
              {!comp.mesma_duracao && (
                <span className="text-xs text-warning">
                  Períodos de tamanhos diferentes ({comp.periodo_a.anos.length} anos contra{" "}
                  {comp.periodo_b.anos.length}) — a variação reflete isso.
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Resumo */}
      <div className="text-xs text-base-content/60">
        {loading ? "Carregando..." : (
          <>
            <strong>{listaExibida.length}</strong> parlamentares
            {municipioId && " no município selecionado"}
            {!municipioId && " (todos os municípios)"}
          </>
        )}
      </div>

      {/* Lista */}
      <div className="space-y-2">
        {loading && (
          <div className="flex justify-center py-12">
            <Loader2 className="size-8 animate-spin text-info" />
          </div>
        )}
        {!loading && items.length === 0 && (
          <div className="bg-base-200 border border-base-300 rounded p-12 text-center text-base-content/60">
            Nenhum parlamentar encontrado. Os parlamentares são extraídos automaticamente
            dos campos: SIGCON (responsáveis), TransfereGov (parlamentar), emendas estaduais
            (nome_responsavel) e Transferência Especial / Plano de Ação (RP9, autor da emenda).
            Se a lista estiver vazia, é porque essas fontes ainda não foram populadas.
          </div>
        )}
        {!loading && listaExibida.map((p) => {
          const expanded = expandedKeys.has(p.nome_normalizado);
          const detail = detailCache[p.nome_normalizado];
          const cmp = mapaComparacao?.get(p.nome_normalizado);
          return (
            <div key={p.nome_normalizado} className="bg-base-100 border rounded">
              <button
                onClick={() => toggle(p)}
                className="w-full flex items-center gap-3 p-3 hover:bg-info/10 transition text-left"
              >
                {expanded ? <ChevronDown className="size-4 text-info shrink-0" /> : <ChevronRight className="size-4 text-base-content/40 shrink-0" />}
                <UserCircle2 className="size-8 text-info shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-base-content">{p.nome_display}</div>
                  <div className="text-xs text-base-content/60 flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
                    <span>{p.total_lancamentos} lançamentos</span>
                    <span className="font-medium text-success">{fmtMoney(p.valor_total)}</span>
                    <span className="text-base-content/40">·</span>
                    {p.por_fonte.sigcon > 0 && (
                      <span className="text-primary">SIGCON: {p.por_fonte.sigcon}</span>
                    )}
                    {p.por_fonte.voluntaria > 0 && (
                      <span className="text-success">TransfereGov: {p.por_fonte.voluntaria}</span>
                    )}
                    {p.por_fonte.emenda > 0 && (
                      <span className="text-warning">Emendas: {p.por_fonte.emenda}</span>
                    )}
                    {p.por_fonte.plano_acao > 0 && (
                      <span className="text-info">Transf. Especial: {p.por_fonte.plano_acao}</span>
                    )}
                    {p.por_fonte.pac > 0 && (
                      <span className="text-primary">PAC: {p.por_fonte.pac}</span>
                    )}
                    {p.por_fonte.fns > 0 && (
                      <span className="text-error">FNS (Saúde): {p.por_fonte.fns}</span>
                    )}
                    {p.municipios.length > 0 && (
                      <>
                        <span className="text-base-content/40">·</span>
                        <span>{p.municipios.join(", ")}</span>
                      </>
                    )}
                  </div>
                </div>

                {/* AS COLUNAS DA COMPARACAO.
                    Ficam a direita e alinhadas entre si para o olho descer a
                    coluna: e assim que se compara uma lista, nao lendo cartao
                    por cartao. So aparecem com a comparacao ligada. */}
                {cmp && (
                  <div className="hidden shrink-0 items-center gap-4 sm:flex">
                    <div className="w-28 text-right">
                      <div className="text-[10px] uppercase tracking-wide text-base-content/40">
                        {comp?.periodo_a.rotulo}
                      </div>
                      <div className="text-sm tabular-nums text-base-content/70">
                        {cmp.valor_a > 0 ? fmtMoney(cmp.valor_a) : "—"}
                      </div>
                    </div>
                    <div className="w-28 text-right">
                      <div className="text-[10px] uppercase tracking-wide text-base-content/40">
                        {comp?.periodo_b.rotulo}
                      </div>
                      <div className="text-sm font-semibold tabular-nums text-base-content">
                        {cmp.valor_b > 0 ? fmtMoney(cmp.valor_b) : "—"}
                      </div>
                    </div>
                    <div className="w-36 text-right">
                      <VariacaoBadge delta={cmp.delta} pct={cmp.delta_pct} />
                    </div>
                  </div>
                )}
              </button>

              {expanded && (
                <div className="border-t bg-base-200/50 p-4 space-y-4">
                  {detail === "loading" && (
                    <div className="flex justify-center py-6">
                      <Loader2 className="size-5 animate-spin text-info" />
                    </div>
                  )}
                  {detail === "error" && (
                    <div className="text-sm text-error bg-error/15 border border-error rounded p-3">
                      Erro ao carregar lançamentos. Tente novamente.
                    </div>
                  )}
                  {detail && typeof detail === "object" && (
                    <>
                      {/* Resumo dentro do expand */}
                      <div className="text-xs text-base-content/70 flex flex-wrap gap-4 pb-2 border-b border-base-300">
                        <span><strong>{detail.total_geral}</strong> lançamentos totais</span>
                        <span className="text-success font-semibold">{fmtMoney(detail.valor_total)}</span>
                      </div>

                      {/* SIGCON */}
                      {detail.sigcon.length > 0 && (
                        <Section
                          icon={<Building2 className="size-4 text-primary" />}
                          title={`SIGCON-MG (Estadual) — ${detail.sigcon.length} convênio(s)`}
                        >
                          <Table headers={["Município", "Nº SIGCON", "Órgão", "Situação", "Valor Total", "Vigência", "Objeto"]}>
                            {detail.sigcon.map((s) => (
                              <tr key={s.id} className="even:bg-base-100">
                                <Td>{s.municipio_nome}</Td>
                                <Td mono>{s.numero || "-"}</Td>
                                <Td className="text-xs">{s.orgao || "-"}</Td>
                                <Td className="text-xs">{s.situacao || "-"}</Td>
                                <Td>{fmtMoney(s.valor_total)}</Td>
                                <Td>{s.dt_vigencia_atual || "-"}</Td>
                                <Td className="max-w-[320px] whitespace-normal break-words leading-snug align-top" title={s.objeto || ""}>
                                  {s.objeto || "-"}
                                </Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* Voluntarias */}
                      {detail.voluntarias.length > 0 && (
                        <Section
                          icon={<Landmark className="size-4 text-success" />}
                          title={`TransfereGov / SICONV (Federal) — ${detail.voluntarias.length} proposta(s)`}
                        >
                          <Table headers={["Município", "Nº Proposta", "Instrumento", "Órgão", "Situação", "Sit. Contrat.", "Valor Global", "Fim Vig.", "Objeto"]}>
                            {detail.voluntarias.map((v) => (
                              <tr key={v.id} className="even:bg-base-100">
                                <Td>{v.municipio_nome}</Td>
                                <Td mono>{v.numero_proposta}</Td>
                                <Td mono>{v.codigo_instrumento || "-"}</Td>
                                <Td className="text-xs">{v.orgao || "-"}</Td>
                                <Td className="text-xs">{v.situacao || "-"}</Td>
                                <Td className="text-xs">{v.situacao_contratacao || "-"}</Td>
                                <Td>{fmtMoney(v.valor_global)}</Td>
                                <Td>{v.dt_fim_vigencia || "-"}</Td>
                                <Td className="max-w-[320px] whitespace-normal break-words leading-snug align-top" title={v.objeto || ""}>
                                  {v.objeto || "-"}
                                </Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* Emendas */}
                      {detail.emendas.length > 0 && (
                        <Section
                          icon={<FileText className="size-4 text-warning" />}
                          title={`Emendas Estaduais — ${detail.emendas.length} indicação(ões)`}
                        >
                          <Table headers={["Município", "Indicação", "Ano", "UO", "Beneficiário", "Tipo", "Valor", "Status"]}>
                            {detail.emendas.map((e) => (
                              <tr key={e.id} className="even:bg-base-100">
                                <Td>{e.municipio_nome}</Td>
                                <Td mono>{e.nr_indicacao}</Td>
                                <Td>{e.ano || "-"}</Td>
                                <Td>{e.uo_sigla || "-"}</Td>
                                <Td className="text-xs">{e.beneficiario || "-"}</Td>
                                <Td className="text-xs">{e.tipo_atendimento || "-"}</Td>
                                <Td>{fmtMoney(e.valor_indicacao)}</Td>
                                <Td className="text-xs">{e.status_indicacao || "-"}</Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* Transferencia Especial / Plano de Acao (RP9) */}
                      {detail.plano_acao && detail.plano_acao.length > 0 && (
                        <Section
                          icon={<Coins className="size-4 text-info" />}
                          title={`Transferência Especial / Plano de Ação (RP9) — ${detail.plano_acao.length} plano(s)`}
                        >
                          <Table headers={["Município", "Plano", "Emenda", "Situação", "Custeio", "Investimento", "Valor Total", "Objeto/Política"]}>
                            {detail.plano_acao.map((pa) => (
                              <tr key={pa.id} className="even:bg-base-100">
                                <Td>{pa.municipio_nome}</Td>
                                <Td mono>{pa.codigo || "-"}</Td>
                                <Td mono className="text-xs">{pa.emenda || "-"}</Td>
                                <Td className="text-xs">{pa.situacao || "-"}</Td>
                                <Td>{fmtMoney(pa.valor_custeio)}</Td>
                                <Td>{fmtMoney(pa.valor_investimento)}</Td>
                                <Td>{fmtMoney(pa.valor_total)}</Td>
                                <Td className="max-w-[320px] whitespace-normal break-words leading-snug align-top" title={pa.objeto || ""}>
                                  {pa.objeto || "-"}
                                </Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* Selecao PAC / Novo PAC */}
                      {detail.pac && detail.pac.length > 0 && (
                        <Section
                          icon={<Landmark className="size-4 text-primary" />}
                          title={`Seleção PAC / Novo PAC — ${detail.pac.length} proposta(s)`}
                        >
                          <Table headers={["Município", "Nº Proposta", "Programa", "Situação", "Valor Total", "Emenda"]}>
                            {detail.pac.map((pc) => (
                              <tr key={pc.id} className="even:bg-base-100">
                                <Td>{pc.municipio_nome}</Td>
                                <Td mono>{pc.numero_proposta}</Td>
                                <Td className="max-w-[320px] whitespace-normal break-words leading-snug align-top" title={pc.programa || ""}>
                                  {pc.programa || "-"}
                                </Td>
                                <Td className="text-xs">{pc.situacao || "-"}</Td>
                                <Td>{fmtMoney(pc.valor_total)}</Td>
                                <Td className="text-xs">{pc.emenda_parlamentar || "-"}</Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {/* FNS — Fundo Municipal de Saúde */}
                      {detail.fns && detail.fns.length > 0 && (
                        <Section
                          icon={<HeartPulse className="size-4 text-error" />}
                          title={`FNS — Fundo Nacional de Saúde (Federal) — ${detail.fns.length} proposta(s)`}
                        >
                          <Table headers={["Município", "Nº Proposta", "Órgão", "Situação", "Valor Total", "Ano", "Objeto"]}>
                            {detail.fns.map((f) => (
                              <tr key={f.id} className="even:bg-base-100">
                                <Td>{f.municipio_nome}</Td>
                                <Td mono>{f.numero || "-"}</Td>
                                <Td className="text-xs">{f.orgao || "-"}</Td>
                                <Td className="text-xs">{f.situacao || "-"}</Td>
                                <Td>{fmtMoney(f.valor_total)}</Td>
                                <Td>{f.ano || "-"}</Td>
                                <Td className="max-w-[320px] whitespace-normal break-words leading-snug align-top" title={f.objeto || ""}>
                                  {f.objeto || "-"}
                                </Td>
                              </tr>
                            ))}
                          </Table>
                        </Section>
                      )}

                      {detail.total_geral === 0 && (
                        <div className="text-sm text-base-content/60 italic text-center py-4">
                          Nenhum lançamento encontrado para este parlamentar.
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-base-content flex items-center gap-2 mb-2">
        {icon} {title}
      </h3>
      <div className="overflow-x-auto rounded border border-base-300 bg-base-100">
        {children}
      </div>
    </div>
  );
}

function Table({ headers, children }: { headers: string[]; children: React.ReactNode }) {
  return (
    <table className="min-w-full text-[13px]">
      <thead className="bg-base-200 text-base-content/70">
        <tr>
          {headers.map((h, i) => (
            <th key={i} className="text-left font-semibold px-3 py-1.5 border-b">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>{children}</tbody>
    </table>
  );
}

function Td({ children, mono, className, title }: { children: React.ReactNode; mono?: boolean; className?: string; title?: string }) {
  return (
    <td className={`px-3 py-1.5 border-b border-base-300 ${mono ? "font-mono" : ""} ${className || ""}`} title={title}>
      {children}
    </td>
  );
}

/** Anos oferecidos no filtro: do corrente para tras, cobrindo dois mandatos. */
// A lista de anos e os atalhos de mandato saem de `@/lib/periodo`: a formula
// do mandato estava copiada literalmente aqui, no Painel e no app de celular.
const ANOS_OPCOES = anosOpcoes();
const ATALHOS_ANOS = atalhosAnos();

export default function ParlamentaresPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="size-6 animate-spin text-info" /></div>}>
      <ParlamentaresInner />
    </Suspense>
  );
}
