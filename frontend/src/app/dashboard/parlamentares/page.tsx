"use client";

import React, { useEffect, useState, useCallback, Suspense } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import { anosOpcoes, atalhosAnos, inicioDoMandato, resumoAnos } from "@/lib/periodo";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import {
  Loader2, Search, ChevronDown, ChevronRight,
  Landmark, Building2, FileText, Eraser, Coins, HeartPulse, ArrowLeftRight, Users,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";

interface ParlamentarItem {
  nome_normalizado: string;
  nome_display: string;
  total_lancamentos: number;
  valor_total: number;
  municipios: string[];
  por_fonte: { sigcon: number; voluntaria: number; emenda: number; plano_acao: number; pac: number; fns: number; emenda_federal: number };
  /** "parlamentar" = pessoa; "outro" = fundo/municipio/secretaria que entrou
   *  como proponente porque a fonte nao publica o autor da emenda. */
  tipo?: "parlamentar" | "outro";
}

/** O que a lista esta exibindo. Abre em "parlamentar" porque a tela e de
 *  parlamentares: o proponente institucional (Fundo Municipal de Saude,
 *  Municipio de X) liderava o ranking em valor sem ser gente. "outro" nao
 *  esconde nada — e um clique, e a contagem dele aparece no proprio seletor. */
type TipoLista = "parlamentar" | "outro" | "todos";

/** Parlamentar que a COMPARACAO trouxe mas que nao esta no recorte de anos da
 *  lista: nao ha contagem por fonte nem municipios para ele, e o cartao precisa
 *  dizer isso em vez de mostrar seis tracinhos sem explicacao. */
type ItemExibido = ParlamentarItem & { foraDoRecorte?: boolean };

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

type Tom = "neutro" | "ok" | "atencao" | "critico";

/* Uma função de dinheiro no sistema inteiro. Havia CINCO cópias — e a do
   SISMOB já tinha derivado: arredondava, e o mesmo valor aparecia com e sem
   centavos no mesmo print. É assim que cinco cópias viram cinco regras. */
import { formatCurrency as fmtMoney } from "@/lib/utils";

function soma<T>(xs: T[], f: (x: T) => number): number {
  return xs.reduce((s, x) => s + (f(x) || 0), 0);
}


/** Leitura da variação entre os dois períodos.
 *
 *  Devolve a PALAVRA quando não há percentual honesto a mostrar: de zero para
 *  R$ 300 mil não é "+∞%", é uma entrada nova; e de R$ 200 mil para zero é o
 *  parlamentar ter parado de destinar, que é a informação que importa.
 *
 *  Sobre o tom: aqui a cor não é enfeite, é o próprio dado — a tela existe para
 *  responder "subiu ou caiu?". Ainda assim, o critério segue o do resto do
 *  sistema: verde para o bom resultado, âmbar para a queda e vermelho só para o
 *  caso que exige ação de verdade (o parlamentar zerou o município). */
function variacao(delta: number, pct: number | null): {
  tom: Tom; seta: string; texto: string; dinheiro: string | null;
} {
  const zero = Math.abs(delta) < 0.005;
  const sobe = delta > 0;
  return {
    tom: zero ? "neutro" : sobe ? "ok" : pct == null ? "critico" : "atencao",
    seta: zero ? "—" : sobe ? "▲" : "▼",
    texto: zero
      ? "sem variação"
      : pct == null
        ? (sobe ? "novo no período" : "sem verba no período")
        : `${sobe ? "+" : "−"}${Math.abs(pct).toFixed(0)}%`,
    dinheiro: zero ? null : `${sobe ? "+" : "−"}${fmtMoney(Math.abs(delta))}`,
  };
}

/** AS FONTES DE UM PARLAMENTAR, em ORDEM FIXA — e é dela que sai o resumo do
 *  cartão fechado.
 *
 *  ⚠️ ISTO SUBSTITUIU UMA GRADE DE SETE CAMPOS (07/09/2026, pedido do dono com
 *  print). A grade mostrava as sete fontes SEMPRE, e como quase todo
 *  parlamentar tem uma ou duas, cinco delas saíam como «—»: três linhas de
 *  cartão para exibir, em média, dois números. "Tem campos que ficam vazios e
 *  são mostrados mesmo assim e por isso toma um espaço maior."
 *
 *  ⚠️ E ISSO É UMA REVERSÃO CONSCIENTE. Estes selos já foram chips coloridos, e
 *  a grade nasceu para consertar dois defeitos deles: a cor gasta à toa e a
 *  posição variável, que impedia descer o olho por uma coluna. O primeiro
 *  continua consertado — selo neutro, cinza sobre cinza, como manda a peça. O
 *  segundo é o que se paga: em troca de um cartão três vezes menor, a varredura
 *  vertical vira ORDEM fixa em vez de POSIÇÃO fixa. Quem tem FNS mostra FNS
 *  sempre depois de Seleção PAC e sempre antes de Emendas Federais.
 *
 *  ⚠️ O RÓTULO É O NOME INTEIRO, não a abreviação ("Transferência Especial", e
 *  não "Transf. especial"). A abreviação existia porque a coluna da grade tinha
 *  ~150px; o selo se ajusta ao texto, então o motivo dela sumiu junto com a
 *  grade. É também o que faz o resumo casar com o título da seção que a pessoa
 *  encontra ao abrir a setinha — é para isso que o resumo existe.
 *
 *  ⚠️ «Emendas Federais» É A EXCEÇÃO QUE FALTA FECHAR: ela conta aqui e no
 *  `total_lancamentos`, mas o endpoint de detalhe (`GET /parlamentares/detalhe`)
 *  devolve seis listas, não sete — ao abrir, não há seção dela. O `title` avisa.
 *  Não é regressão desta mudança: a grade tinha o mesmo furo, só menos visível. */
const FONTES: Array<{
  chave: keyof ParlamentarItem["por_fonte"];
  label: string;
  title: string;
}> = [
  { chave: "sigcon", label: "Convênios Estaduais",
    title: "Convênios do Estado com o município (SIGCON)" },
  { chave: "voluntaria", label: "TransfereGov",
    title: "Propostas TransfereGov / SICONV (federal)" },
  { chave: "emenda", label: "Emendas Estaduais",
    title: "Indicações de emenda estadual" },
  { chave: "plano_acao", label: "Transferência Especial",
    title: "Transferência Especial / Plano de Ação (RP9)" },
  { chave: "pac", label: "Seleção PAC",
    title: "Propostas do Novo PAC" },
  { chave: "fns", label: "FNS (Saúde)",
    title: "Propostas do Fundo Nacional de Saúde" },
  { chave: "emenda_federal", label: "Emendas Federais",
    title: "Emendas parlamentares federais (carteira CGU/SICONV) que ainda não "
         + "viraram instrumento. A listagem delas ainda não abre aqui — está na "
         + "tela «Emendas parlamentares»." },
];

/** Grupo de lançamentos de UMA fonte dentro do parlamentar expandido.
 *  Substitui a tabela interna: cabeçalho com contagem e total à direita, itens
 *  soltos dentro — a mesma estrutura que Emendas usa para agrupar por ano. */
function GrupoFonte({ icon, titulo, sub, total, children }: {
  icon: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  titulo: string;
  sub: string;
  total: number;
  children: React.ReactNode;
}) {
  return (
    <Bloco className="p-3">
      <BlocoHead
        icon={icon}
        titulo={titulo}
        sub={sub}
        right={<span className="bi-num text-[13px]">{fmtMoney(total)}</span>}
      />
      <Lista>{children}</Lista>
    </Bloco>
  );
}

function ParlamentaresInner() {
  const municipioId = useMunicipio().municipioId || null;

  const [items, setItems] = useState<ParlamentarItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [tipoLista, setTipoLista] = useState<TipoLista>("parlamentar");
  const [contagem, setContagem] = useState<{ parlamentar: number; outro: number }>({ parlamentar: 0, outro: 0 });
  // PERIODO MULTI-ANO (o backend de /parlamentares ja aceitava `anos`; era so o
  // frontend que mandava um ano so). Vazio = todos.
  const [anosSel, setAnosSel] = useState<string[]>([]);
  /* Abre no ano corrente — ver `lib/anoPadrao.ts`.
     ⚠️ Só o filtro PRINCIPAL. Os `anosA`/`anosB` da comparação ficam
     vazios de propósito: ali o vazio não significa "todos", significa
     "escolha os dois lados", e preencher um deles sozinho mostraria uma
     comparação que o usuário não pediu. */
  useAnoCorrentePadrao(ANOS_OPCOES, setAnosSel);
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
      params.tipo = tipoLista;
      const r = await api.get<{ items: ParlamentarItem[]; contagem?: { parlamentar: number; outro: number } }>(
        "/parlamentares", { params });
      setItems(r.data.items);
      // A contagem vem SEMPRE dos dois lados, mesmo filtrando um — e o que
      // permite o seletor dizer "Outros (2)" sem uma segunda chamada.
      if (r.data.contagem) setContagem(r.data.contagem);
    } catch (e) {
      console.error("erro parlamentares", e);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [municipioId, search, anosSel, tipoLista]);

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

  const listaExibida: ItemExibido[] = comp
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
          por_fonte: { sigcon: 0, voluntaria: 0, emenda: 0, plano_acao: 0, pac: 0, fns: 0, emenda_federal: 0 },
          foraDoRecorte: true,
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
    // Cache com uma excecao: "error" NAO conta como carregado. Antes qualquer
    // valor no cache barrava a nova busca, entao o "tente novamente" da mensagem
    // era mentira — reabrir o cartao devolvia o mesmo erro sem chamar a API.
    if (detailCache[k] && detailCache[k] !== "error") return;
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

  const varGeral = comp ? variacao(comp.delta, comp.delta_pct) : null;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="text-2xl font-bold text-base-content">Parlamentares</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Lista agregada dos parlamentares (deputados estaduais/federais e senadores)
          com lançamentos vinculados — convênios estaduais, propostas TransfereGov/SICONV,
          emendas estaduais, Transferência Especial / Plano de Ação (RP9), Seleção PAC,
          FNS (Fundo Municipal de Saúde, agrupado pelo proponente) e emendas federais
          indicadas. Cada parlamentar traz os selos das fontes em que tem lançamento;
          clique na setinha para ver um a um.
        </p>
      </div>

      {/* Filtro */}
      <div className="bi-card flex flex-wrap items-end gap-3 p-4">
        <div className="min-w-[200px] flex-1">
          {/* 11px em --bi-muted: a escala de rotulo de controle usada nas demais
              telas do lote (esta era a unica em 12px). */}
          <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Buscar parlamentar
          </label>
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Ex: Eduardo Azevedo"
            onKeyDown={(e) => { if (e.key === "Enter") carregar(); }}
          />
        </div>
        <div>
          <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Exibir
          </label>
          <Select
            value={tipoLista}
            onValueChange={(v) => {
              setTipoLista(v as TipoLista);
              setDetailCache({});
              setExpandedKeys(new Set());
            }}
          >
            <SelectTrigger className="min-w-[190px]">
              <SelectValue>
                {tipoLista === "parlamentar"
                  ? `Parlamentares (${contagem.parlamentar})`
                  : tipoLista === "outro"
                    ? `Outros (${contagem.outro})`
                    : `Todos (${contagem.parlamentar + contagem.outro})`}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="parlamentar">Parlamentares ({contagem.parlamentar})</SelectItem>
              <SelectItem value="outro">Outros ({contagem.outro})</SelectItem>
              <SelectItem value="todos">Todos ({contagem.parlamentar + contagem.outro})</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Anos <span style={{ color: "var(--bi-faint)" }}>(um, alguns ou o mandato)</span>
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
        <Button onClick={carregar}>
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
        /* Bloco em vez do retangulo violeta: o painel deixa de gritar e passa a
           ser mais um cartao da tela — quem destaca a comparacao sao os numeros
           dentro dele, nao a moldura. */
        <Bloco className="gap-3 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>Atalhos:</span>
            {atalhosComparar.map((at) => {
              const ativo = JSON.stringify(anosA) === JSON.stringify(at.a)
                && JSON.stringify(anosB) === JSON.stringify(at.b);
              return (
                <button
                  key={at.label}
                  type="button"
                  aria-pressed={ativo}
                  onClick={() => { setAnosA(at.a); setAnosB(at.b); }}
                  className="rounded-full border px-2.5 py-0.5 text-[11px] font-medium transition-colors"
                  // O chip marcado precisa se distinguir sem virar bloco de cor:
                  // fundo do proprio cinza da identidade e tinta do acento.
                  style={ativo
                    ? { borderColor: "var(--bi-accent-ink)", background: "var(--bi-surface-2)", color: "var(--bi-accent-ink)" }
                    : { borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}
                >
                  {at.label}
                </button>
              );
            })}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="w-52">
              <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Período A (referência)
              </label>
              <MultiSelect
                opcoes={ANOS_OPCOES} valor={anosA} onChange={setAnosA}
                atalhos={ATALHOS_ANOS} formatarResumo={resumoAnos}
                placeholder="Escolha os anos" rotuloTodos="Limpar"
                ariaLabel="Anos do período A"
              />
            </div>
            <ArrowLeftRight className="mb-2 size-4 shrink-0" style={{ color: "var(--bi-faint)" }} />
            <div className="w-52">
              <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Período B (comparado)
              </label>
              <MultiSelect
                opcoes={ANOS_OPCOES} valor={anosB} onChange={setAnosB}
                atalhos={ATALHOS_ANOS} formatarResumo={resumoAnos}
                placeholder="Escolha os anos" rotuloTodos="Limpar"
                ariaLabel="Anos do período B"
              />
            </div>
          </div>

          {compErro && (
            <p className="flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
              <Selo tom="critico">Comparação</Selo>
              {compErro}
            </p>
          )}

          {comp && varGeral && (
            <>
              {/* Os tres numeros do periodo viram KPI: e a leitura de cima da
                  tela, e o <Numero> ja e o formato dessa leitura no sistema.
                  O `sub` aproveita para mostrar quantos parlamentares e quantos
                  anos cada lado tem — que a linha corrida antiga escondia. */}
              <div className="grid gap-2 sm:grid-cols-3">
                <Numero
                  rotulo={comp.periodo_a.rotulo}
                  valor={fmtMoney(comp.periodo_a.total)}
                  sub={`${comp.periodo_a.parlamentares} parlamentares · ${comp.periodo_a.anos.length} ano(s)`}
                />
                <Numero
                  rotulo={comp.periodo_b.rotulo}
                  valor={fmtMoney(comp.periodo_b.total)}
                  sub={`${comp.periodo_b.parlamentares} parlamentares · ${comp.periodo_b.anos.length} ano(s)`}
                />
                <Numero
                  rotulo="Variação no período"
                  tom={varGeral.tom}
                  valor={`${varGeral.seta} ${varGeral.texto}`}
                  sub={varGeral.dinheiro}
                />
              </div>
              {/* Sem este aviso, "mandato atual x anterior" parece uma queda de
                  50% quando na verdade um lado tem 2 anos e o outro tem 4. */}
              {!comp.mesma_duracao && (
                <p className="flex flex-wrap items-center gap-1.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  <Selo tom="atencao">Períodos de tamanhos diferentes</Selo>
                  {comp.periodo_a.anos.length} anos contra {comp.periodo_b.anos.length} — a variação reflete isso.
                </p>
              )}
            </>
          )}
        </Bloco>
      )}

      {/* Lista */}
      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      ) : listaExibida.length === 0 ? (
        /* Conta a lista EXIBIDA, nao `items`: com a comparacao ligada a lista sai
           da comparacao, e o teste antigo mostrava "nenhum parlamentar" junto com
           os cartoes na tela. */
        <Vazio>
          Nenhum parlamentar encontrado. Os parlamentares são extraídos automaticamente
          dos campos: SIGCON (responsáveis), TransfereGov (parlamentar), emendas estaduais
          (nome_responsavel) e Transferência Especial / Plano de Ação (RP9, autor da emenda).
          Se a lista estiver vazia, é porque essas fontes ainda não foram populadas.
        </Vazio>
      ) : (
        /* AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO do grupo ->
           itens cinza dentro. Faltava a do meio: o ranking ficava solto sobre o
           fundo. O `p-3` nao e enfeite — sem ele os itens encostam na margem do
           branco, que foi o motivo de o cartao ter sido retirado da primeira vez.

           O contador de parlamentares e o recorte de municipio vivem AQUI, no
           `sub`, e nao mais numa linha solta acima da lista: era a mesma
           informacao, e repeti-la nos dois lugares so acrescentaria ruido. */
        <Bloco className="p-3">
          <BlocoHead
            icon={Users}
            titulo="Parlamentares"
            sub={`${listaExibida.length} parlamentar(es)${
              municipioId ? " no município selecionado" : " (todos os municípios)"
            }`}
            /* Sem total com a comparacao ligada: ali a lista mistura os dois
               periodos (quem esta fora do recorte entra com o valor do periodo
               que tiver), entao somar `valor_total` daria um numero que nao e de
               periodo nenhum. Os totais honestos dos dois lados ja estao nos
               <Numero> do painel de comparacao. */
            right={!comp ? (
              <span className="bi-num text-[13px]">
                {fmtMoney(soma(listaExibida, (p) => p.valor_total))}
              </span>
            ) : undefined}
          />
          <Lista>
          {listaExibida.map((p) => {
            const expanded = expandedKeys.has(p.nome_normalizado);
            const detail = detailCache[p.nome_normalizado];
            const cmp = mapaComparacao?.get(p.nome_normalizado);
            const varItem = cmp ? variacao(cmp.delta, cmp.delta_pct) : null;
            return (
              <React.Fragment key={p.nome_normalizado}>
                <ItemLinha
                  onClick={() => toggle(p)}
                  expandido={expanded}
                  titulo={
                    /* A seta tinha 14px na cor MAIS FRACA da paleta, colada no
                       texto, sem alvo próprio e sem `aria-expanded`. Nada ali
                       dizia "isto abre" — quem olhava não entendia que havia
                       detalhe para ver. Agora é um alvo de 24px com fundo, na
                       cor de texto secundário, e o leitor de tela anuncia
                       recolhido/expandido. */
                    <span className="flex items-center gap-1.5">
                      <span
                        aria-hidden="true"
                        className="bi-hover grid size-6 shrink-0 place-items-center rounded-lg"
                        style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
                      >
                        {expanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                      </span>
                      <span className="truncate">{p.nome_display}</span>
                    </span>
                  }
                  /* ⭐ O VALOR GANHOU RÓTULO (07/09/2026, pedido do dono): "pra
                     pessoa que bate o olho entender que aquele valor é
                     referente a todos os lançamentos". Era um número solto no
                     canto, e num cartão que também mostra o valor de CADA
                     lançamento quando aberto, ele podia ser lido como o valor de
                     um deles. Mesma tipografia dos rótulos da comparação, ao
                     lado — 9px, caixa alta, cor mais fraca —, para as duas
                     colunas de número lerem como uma coisa só. */
                  valor={
                    <span className="flex flex-col items-end gap-0.5">
                      {/* Duas versões do MESMO rótulo, e não uma que quebra em
                          duas linhas: quebrar devolveria ao cartão a altura que
                          esta mudança acabou de tirar dele. No celular, onde a
                          linha inteira tem ~390px, o rótulo curto deixa o nome
                          do parlamentar caber sem truncar. */}
                      <span
                        className="whitespace-nowrap text-[9px] font-normal uppercase tracking-wide sm:hidden"
                        style={{ color: "var(--bi-faint)" }}
                      >
                        Valor total
                      </span>
                      <span
                        className="hidden whitespace-nowrap text-[9px] font-normal uppercase tracking-wide sm:inline"
                        style={{ color: "var(--bi-faint)" }}
                      >
                        Valor total dos lançamentos
                      </span>
                      <span className="bi-num">{fmtMoney(p.valor_total)}</span>
                    </span>
                  }
                  meta={
                    <>
                      <span>{p.total_lancamentos} lançamento(s)</span>
                      {p.foraDoRecorte && (
                        <Selo title="Aparece por causa da comparação: este parlamentar não está no recorte de anos da lista, então não há detalhe por fonte.">
                          fora do recorte da lista
                        </Selo>
                      )}
                      {p.municipios.length > 0 && (
                        <span className="truncate" title={p.municipios.join(", ")}>
                          · {p.municipios.join(", ")}
                        </span>
                      )}
                      {/* ⭐ O RESUMO DO QUE ESTÁ ATRÁS DA SETINHA: um selo por
                          fonte QUE TEM lançamento, na ordem fixa de `FONTES`.
                          Ver o comentário de lá para o que isto substituiu e o
                          que se paga pela troca. */}
                      {FONTES.map(({ chave, label, title }) => {
                        const n = p.por_fonte[chave];
                        return n ? (
                          <Selo key={chave} title={title}>{`${label} · ${n}`}</Selo>
                        ) : null;
                      })}
                    </>
                  }
                  acao={cmp && varItem ? (
                    /* AS COLUNAS DA COMPARACAO.
                       Continuam a direita e alinhadas entre si para o olho descer
                       a coluna: e assim que se compara uma lista, nao lendo cartao
                       por cartao. A tipografia (rotulo de 9px em caixa alta, cor
                       mais fraca) e a MESMA do rotulo do valor total, ao lado —
                       os dois blocos de numero do cartao leem como uma coisa so.
                       Era tambem a da grade de fontes que ficava embaixo; ela
                       virou os selos da meta em 07/09/2026. */
                    <div className="hidden shrink-0 items-start gap-3 sm:flex">
                      <div className="w-28 text-right">
                        <div className="truncate text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                          {comp?.periodo_a.rotulo}
                        </div>
                        <div className="bi-num truncate text-[11px] leading-tight" style={{ color: "var(--bi-muted)" }}>
                          {cmp.valor_a > 0 ? fmtMoney(cmp.valor_a) : "—"}
                        </div>
                      </div>
                      <div className="w-28 text-right">
                        <div className="truncate text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                          {comp?.periodo_b.rotulo}
                        </div>
                        <div className="bi-num truncate text-[11px] leading-tight" style={{ color: "var(--bi-text)" }}>
                          {cmp.valor_b > 0 ? fmtMoney(cmp.valor_b) : "—"}
                        </div>
                      </div>
                      <div className="flex w-28 flex-col items-end gap-0.5">
                        <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                          Variação
                        </div>
                        <Selo tom={varItem.tom} title={`Situação: ${cmp.situacao}`}>
                          <span aria-hidden className="mr-1">{varItem.seta}</span>
                          {varItem.texto}
                        </Selo>
                        {varItem.dinheiro && (
                          <span className="bi-num text-[10px]" style={{ color: "var(--bi-faint)" }}>
                            {varItem.dinheiro}
                          </span>
                        )}
                      </div>
                    </div>
                  ) : undefined}
                />
                {/* ⚠️ SEM FILHOS. Aqui morava a grade de sete fontes, que agora
                    são os selos da meta — ver `FONTES`. O cartão fechado passou
                    de três linhas para uma. */}

                {expanded && (
                  /* O detalhe e um <li> IRMAO, nao filho do cartao: o corpo do
                     ItemLinha e um <button> quando clicavel, e lista dentro de
                     botao nao e HTML valido. */
                  /* O fundo CINZA aqui e consequencia do cartao branco que
                     passou a envolver a lista: o detalhe e feito de `GrupoFonte`,
                     que sao brancos, e branco sobre branco achata a hierarquia
                     (o mesmo motivo pelo qual o corpo do modal de detalhe usa
                     `--bi-bg`). Com o recuo cinza, a leitura volta a ser
                     branco -> item cinza -> detalhe cinza -> grupo branco. */
                  <li
                    className="p-2"
                    style={{ background: "var(--bi-bg)", borderRadius: "var(--bi-radius)" }}
                  >
                    {detail === "loading" && (
                      <div className="flex justify-center py-6">
                        <Loader2 className="size-5 animate-spin" style={{ color: "var(--bi-muted)" }} />
                      </div>
                    )}
                    {detail === "error" && (
                      <div className="flex flex-wrap items-center justify-center gap-1.5 py-4 text-[12px]" style={{ color: "var(--bi-muted)" }}>
                        <Selo tom="critico">Erro</Selo>
                        Não foi possível carregar os lançamentos. Feche e abra o cartão para tentar de novo.
                      </div>
                    )}
                    {detail && typeof detail === "object" && (
                      <div className="flex flex-col gap-2">
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                          <span><span className="bi-num">{detail.total_geral}</span> lançamentos totais</span>
                          <span className="bi-num" style={{ color: "var(--bi-text)" }}>{fmtMoney(detail.valor_total)}</span>
                        </div>

                        {/* SIGCON */}
                        {detail.sigcon.length > 0 && (
                          <GrupoFonte
                            icon={Building2}
                            titulo="Convênios estaduais"
                            sub={`${detail.sigcon.length} convênio(s)`}
                            total={soma(detail.sigcon, (s) => s.valor_total)}
                          >
                            {detail.sigcon.map((s) => (
                              <ItemLinha
                                key={s.id}
                                titulo={s.objeto || "Sem objeto informado"}
                                valor={fmtMoney(s.valor_total)}
                                meta={
                                  <>
                                    {s.situacao && (
                                      <Selo tom={situacaoTom(s.situacao)} title={s.situacao}>{s.situacao}</Selo>
                                    )}
                                    <span>{s.municipio_nome}</span>
                                    {s.orgao && <span className="truncate" title={s.orgao}>· {s.orgao}</span>}
                                    {s.responsaveis && (
                                      <span className="truncate" title={s.responsaveis}>· {s.responsaveis}</span>
                                    )}
                                    {s.numero && <span className="font-mono">· nº {s.numero}</span>}
                                  </>
                                }
                              >
                                <Campos
                                  campos={[
                                    { rotulo: "Repasse", valor: s.valor_repasse ? fmtMoney(s.valor_repasse) : "—" },
                                    { rotulo: "Vigência atual", valor: s.dt_vigencia_atual || "—" },
                                    { rotulo: "Ano", valor: s.ano ?? "—" },
                                  ]}
                                />
                              </ItemLinha>
                            ))}
                          </GrupoFonte>
                        )}

                        {/* Voluntarias */}
                        {detail.voluntarias.length > 0 && (
                          <GrupoFonte
                            icon={Landmark}
                            titulo="TransfereGov / SICONV (federal)"
                            sub={`${detail.voluntarias.length} proposta(s)`}
                            total={soma(detail.voluntarias, (v) => v.valor_global)}
                          >
                            {detail.voluntarias.map((v) => (
                              <ItemLinha
                                key={v.id}
                                titulo={v.objeto || "Sem objeto informado"}
                                valor={fmtMoney(v.valor_global)}
                                meta={
                                  <>
                                    {v.situacao && (
                                      <Selo tom={situacaoTom(v.situacao)} title={v.situacao}>{v.situacao}</Selo>
                                    )}
                                    {v.situacao_contratacao && (
                                      <Selo
                                        tom={situacaoTom(v.situacao_contratacao)}
                                        title={`Situação de contratação: ${v.situacao_contratacao}`}
                                      >
                                        {v.situacao_contratacao}
                                      </Selo>
                                    )}
                                    <span>{v.municipio_nome}</span>
                                    {v.orgao && <span className="truncate" title={v.orgao}>· {v.orgao}</span>}
                                    {v.parlamentar && (
                                      <span className="truncate" title={v.parlamentar}>· {v.parlamentar}</span>
                                    )}
                                    <span className="font-mono">
                                      · prop {v.numero_proposta}
                                      {v.codigo_instrumento ? ` · instr ${v.codigo_instrumento}` : ""}
                                    </span>
                                  </>
                                }
                              >
                                <Campos
                                  campos={[
                                    { rotulo: "Repasse", valor: v.valor_repasse ? fmtMoney(v.valor_repasse) : "—" },
                                    { rotulo: "Fim da vigência", valor: v.dt_fim_vigencia || "—" },
                                  ]}
                                />
                              </ItemLinha>
                            ))}
                          </GrupoFonte>
                        )}

                        {/* Emendas */}
                        {detail.emendas.length > 0 && (
                          <GrupoFonte
                            icon={FileText}
                            titulo="Emendas estaduais"
                            sub={`${detail.emendas.length} indicação(ões)`}
                            total={soma(detail.emendas, (e) => e.valor_indicacao)}
                          >
                            {detail.emendas.map((e) => (
                              <ItemLinha
                                key={e.id}
                                titulo={e.tipo_atendimento || e.beneficiario || "Indicação"}
                                valor={fmtMoney(e.valor_indicacao)}
                                meta={
                                  <>
                                    {e.status_indicacao && (
                                      <Selo tom={situacaoTom(e.status_indicacao)} title={e.status_indicacao}>
                                        {e.status_indicacao}
                                      </Selo>
                                    )}
                                    <span>{e.municipio_nome}</span>
                                    {e.beneficiario && (
                                      <span className="truncate" title={e.beneficiario}>→ {e.beneficiario}</span>
                                    )}
                                    <span className="font-mono">· ind {e.nr_indicacao}</span>
                                  </>
                                }
                              >
                                <Campos
                                  campos={[
                                    { rotulo: "Unidade orçamentária", valor: e.uo_sigla || "—" },
                                    { rotulo: "Ano", valor: e.ano ?? "—" },
                                  ]}
                                />
                              </ItemLinha>
                            ))}
                          </GrupoFonte>
                        )}

                        {/* Transferencia Especial / Plano de Acao (RP9) */}
                        {detail.plano_acao && detail.plano_acao.length > 0 && (
                          <GrupoFonte
                            icon={Coins}
                            titulo="Transferência Especial / Plano de Ação (RP9)"
                            sub={`${detail.plano_acao.length} plano(s)`}
                            total={soma(detail.plano_acao, (pa) => pa.valor_total)}
                          >
                            {detail.plano_acao.map((pa) => (
                              <ItemLinha
                                key={pa.id}
                                titulo={pa.objeto || "Plano de ação"}
                                valor={fmtMoney(pa.valor_total)}
                                meta={
                                  <>
                                    {pa.situacao && (
                                      <Selo tom={situacaoTom(pa.situacao)} title={pa.situacao}>{pa.situacao}</Selo>
                                    )}
                                    <span>{pa.municipio_nome}</span>
                                    {pa.parlamentar && (
                                      <span className="truncate" title={pa.parlamentar}>· {pa.parlamentar}</span>
                                    )}
                                    <span className="font-mono">
                                      {pa.codigo ? `· plano ${pa.codigo}` : ""}
                                      {pa.emenda ? ` · emenda ${pa.emenda}` : ""}
                                    </span>
                                  </>
                                }
                              >
                                <Campos
                                  campos={[
                                    { rotulo: "Custeio", valor: fmtMoney(pa.valor_custeio) },
                                    { rotulo: "Investimento", valor: fmtMoney(pa.valor_investimento) },
                                  ]}
                                />
                              </ItemLinha>
                            ))}
                          </GrupoFonte>
                        )}

                        {/* Selecao PAC / Novo PAC */}
                        {detail.pac && detail.pac.length > 0 && (
                          <GrupoFonte
                            icon={Landmark}
                            titulo="Seleção PAC / Novo PAC"
                            sub={`${detail.pac.length} proposta(s)`}
                            total={soma(detail.pac, (pc) => pc.valor_total)}
                          >
                            {detail.pac.map((pc) => {
                              // O programa e o titulo quando existe; o objeto so
                              // entra na meta se disser outra coisa, para o cartao
                              // nao repetir a mesma frase duas vezes.
                              const tituloPac = pc.programa || pc.objeto || "Proposta PAC";
                              return (
                                <ItemLinha
                                  key={pc.id}
                                  titulo={tituloPac}
                                  valor={fmtMoney(pc.valor_total)}
                                  meta={
                                    <>
                                      {pc.situacao && (
                                        <Selo tom={situacaoTom(pc.situacao)} title={pc.situacao}>{pc.situacao}</Selo>
                                      )}
                                      <span>{pc.municipio_nome}</span>
                                      {pc.objeto && pc.objeto !== tituloPac && (
                                        <span className="truncate" title={pc.objeto}>· {pc.objeto}</span>
                                      )}
                                      <span className="font-mono">· prop {pc.numero_proposta}</span>
                                    </>
                                  }
                                >
                                  <Campos
                                    campos={[
                                      { rotulo: "Emenda parlamentar", valor: pc.emenda_parlamentar || "—",
                                        title: pc.emenda_parlamentar || undefined },
                                      { rotulo: "Proponente", valor: pc.proponente || "—",
                                        title: pc.proponente || undefined },
                                    ]}
                                  />
                                </ItemLinha>
                              );
                            })}
                          </GrupoFonte>
                        )}

                        {/* FNS — Fundo Nacional de Saude */}
                        {detail.fns && detail.fns.length > 0 && (
                          <GrupoFonte
                            icon={HeartPulse}
                            titulo="FNS — Fundo Nacional de Saúde (federal)"
                            sub={`${detail.fns.length} proposta(s)`}
                            total={soma(detail.fns, (f) => f.valor_total)}
                          >
                            {detail.fns.map((f) => (
                              <ItemLinha
                                key={f.id}
                                titulo={f.objeto || "Sem objeto informado"}
                                valor={fmtMoney(f.valor_total)}
                                meta={
                                  <>
                                    {f.situacao && (
                                      <Selo tom={situacaoTom(f.situacao)} title={f.situacao}>{f.situacao}</Selo>
                                    )}
                                    <span>{f.municipio_nome}</span>
                                    {f.orgao && <span className="truncate" title={f.orgao}>· {f.orgao}</span>}
                                    {f.proponente && (
                                      <span className="truncate" title={f.proponente}>· {f.proponente}</span>
                                    )}
                                    {f.numero && <span className="font-mono">· nº {f.numero}</span>}
                                  </>
                                }
                              >
                                <Campos
                                  campos={[
                                    { rotulo: "Ano", valor: f.ano ?? "—" },
                                    { rotulo: "Fim da vigência", valor: f.dt_vigencia_final || "—" },
                                  ]}
                                />
                              </ItemLinha>
                            ))}
                          </GrupoFonte>
                        )}

                        {detail.total_geral === 0 && (
                          <Vazio>Nenhum lançamento encontrado para este parlamentar.</Vazio>
                        )}
                      </div>
                    )}
                  </li>
                )}
              </React.Fragment>
            );
          })}
          </Lista>
        </Bloco>
      )}
    </div>
  );
}

/** Anos oferecidos no filtro: do corrente para tras, cobrindo dois mandatos. */
// A lista de anos e os atalhos de mandato saem de `@/lib/periodo`: a formula
// do mandato estava copiada literalmente aqui, no Painel e no app de celular.
const ANOS_OPCOES = anosOpcoes();
const ATALHOS_ANOS = atalhosAnos();

export default function ParlamentaresPage() {
  return (
    <Suspense fallback={
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
      </div>
    }>
      <ParlamentaresInner />
    </Suspense>
  );
}
