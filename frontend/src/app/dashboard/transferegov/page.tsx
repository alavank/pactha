"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import {
  Search, Eye, Loader2, Eraser, RefreshCw, ChevronDown, ChevronRight,
  ClipboardList, Building2, Landmark, FileText, Banknote, TrendingUp,
} from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Abas, Bloco, BlocoHead, Campo, Campos, Grade, GradeCel, GradeLinha, ItemLinha,
  Lista, Modal, ModalCorpo, ModalHead, Secao, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";
import { PainelFiltros, type FiltroAtivo } from "@/components/ui/filtros";
import { formatCurrency } from "@/lib/utils";
import { textoDe } from "@/lib/texto";
import { TituloTela } from "@/components/TituloTela";

/** Preserva o `-` do helper `Field` que existia aqui: a peça `Campos` renderiza
 *  o que receber, e rótulo com nada embaixo parece falha de carregamento.
 *  `0` não é vazio — "0 meses em execução" é um dado. */
function campoP(rotulo: string, valor: unknown, extra?: Partial<Campo>): Campo {
  /* `textoDe` e não `String()`: metade destes campos vem crua da API federal,
     que devolve objeto onde promete texto. `String({...})` não quebra a tela,
     mas escreve "[object Object]" nela — e um campo assim no meio de um modal
     de convênio destrói a confiança no número do lado. */
  const v = textoDe(valor) ?? "-";
  return { rotulo, valor: v, title: v === "-" ? undefined : `${rotulo}: ${v}`, ...extra };
}

/** Só vale ano até o corrente + 2: o que passar disso veio do miolo de um
 *  número, não de uma data. */
const ANO_LIMITE = new Date().getFullYear() + 2;

/** O primeiro ano PLAUSÍVEL dentro de um identificador.
 *
 *  PEGADINHA já paga no backend (`_ano_de`, em services/rm_builder.py): a regex
 *  ingênua `20\d{2}` lê `2097` em `042097/2015` — o miolo do número, antes do
 *  ano de verdade — e o registro vai parar num grupo de ano futuro absurdo. Por
 *  isso o ano DEPOIS DA BARRA tem prioridade e, no resto do texto, só entra ano
 *  possível. */
function anoEm(s: string): string {
  const aposBarra = /\/\s*((?:19|20)\d{2})\b/.exec(s);
  if (aposBarra) return aposBarra[1];
  const re = /(?:19|20)\d{2}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s)) !== null) {
    const ano = Number(m[0]);
    if (ano >= 2000 && ano <= ANO_LIMITE) return m[0];
  }
  return "";
}

/** O ANO de um plano de ação.
 *
 *  Vem do CÓDIGO DA EMENDA (`202241760007-Lincoln Portela`), cujos quatro
 *  primeiros dígitos são o exercício da emenda — e é o ano pelo qual o gestor
 *  fala do recurso ("a emenda de 2024"). O código do plano fica de segunda
 *  opção porque seu formato varia entre fontes, e por isso passa pela mesma
 *  peneira de ano plausível.
 *
 *  Esta é a MESMA fonte, na MESMA ordem, que o backend já usa para datar uma
 *  Transferência Especial no Relatório de Monitoramento
 *  (`_ano_de(codigoEmendaFormatado, planoAcaoCodigo)`). Duas partes do produto
 *  datando o mesmo plano em anos diferentes é pior que não agrupar.
 *
 *  O campo `ano` que o TransfereGov tem para o plano existe só no DETALHE — uma
 *  chamada HTTP por plano. Agrupar por ele exigiria abrir os N planos da tela. */
function anoDa(p: Plano): string {
  return anoEm(p.emenda_codigo || "") || anoEm(p.codigo || "");
}

interface Plano {
  id: number;
  codigo: string;
  programa_codigo: string;
  programa_id: number;
  situacao_plano_acao: string;
  situacao_plano_trabalho: string;
  beneficiario_nome: string;
  beneficiario_cnpj: string;
  uf: string;
  politicas_publicas: string;
  emenda_codigo: string;
  valor_custeio: number;
  valor_investimento: number;
  valor_total: number;
  objeto_descricao?: string;
  motivo_impedimento?: string;
}

interface BuscarResp {
  items: Plano[];
  total: number;
  municipio: { id: number; nome: string; uf: string };
  cache_age_seconds: number;
}

interface DetalhePlano {
  plano?: {
    id: number;
    codigo?: string;
    codigoSufixo?: number;
    ano?: number;
    /* `unknown` nos campos que a API federal devolve como OBJETO quando lhe
       convém. `objeto` vem como
       `{ano, codigo, descricao, descricaoFormatada, funcoes, versao}` — e era
       ele que derrubava esta tela inteira: objeto no JSX faz o React abortar a
       ÁRVORE (erro #31), e o que o dono via era só "This page couldn't load",
       sem nada apontando para um campo.
       `situacao` e `modalidade` são texto hoje, mas vêm do mesmo backend Java
       que ora serializa o enum como string, ora como objeto — passam por
       `textoDe` pelo mesmo motivo, antes de virarem o próximo susto. */
    modalidade?: unknown;
    situacao?: unknown;
    motivoImpedimento?: string;
    programaF?: string;
    valorCusteio?: number;
    valorInvestimento?: number;
    valorTotal?: number;
    objeto?: unknown;
    objetoDetalhe?: string;
    emailCamara?: string;
    beneficiario?: {
      cnpj?: string; nome?: string; uf?: string; ibge?: number;
      idh?: number; enteId?: number; email?: string;
    };
    emendaParlamentar?: {
      codigoEmendaFormatado?: string;
      nomeParlamentar?: string;
      codigoParlamentar?: string;
      ano?: number;
      valorCusteio?: number;
      valorInvestimento?: number;
    };
    listaPO?: unknown[];
    listaAPP?: unknown[];
  };
  resumo?: {
    nrMesesExecucao?: number;
    valorTotalCusteio?: number;
    valorTotalInvestimento?: number;
    valorTotalExecutado?: number;
    valorTotalPendente?: number;
    valorTotalCusteioExecutado?: number;
    valorTotalInvestimentoExecutado?: number;
  };
  /* PAGAMENTOS: vem da coluna `transferegov_te.pagamentos`, gravada pelo
     coletor. `null` = o coletor ainda nao passou por este plano — que NAO e o
     mesmo que "nao ha pagamento", e a tela precisa dizer a diferenca. */
  pagamentos?: PagamentosTE | null;
}

/** Uma linha da "Lista de Documentos Habeis" da tela federal, ja resolvida com
 *  a Ordem de Pagamento/Bancaria e o historico de eventos dela. */
interface DocumentoHabilTE {
  dh_id?: number | null;
  numero_dh?: string | null;
  minuta?: string | null;
  numero_empenho?: string | null;
  valor?: number | null;
  situacao_dh?: string | null;
  opob_id?: number | null;
  numero_op?: string | null;
  numero_ob?: string | null;
  data_emissao_ob?: string | null;
  data_emissao_op?: string | null;
  situacao?: string | null;
  ordenador_despesa?: string | null;
  gestor_financeiro?: string | null;
  dt_assinatura_ordenador?: string | null;
  dt_assinatura_gestor?: string | null;
  historico?: { data?: string | null; responsavel?: string | null; situacao?: string | null }[] | null;
}

interface PagamentosTE {
  valor_total?: number | null;
  valor_desembolsado?: number | null;
  valor_a_desembolsar?: number | null;
  data_ultimo_desembolso?: string | null;
  pago_integral?: boolean | null;
  /** DHs com Ordem Bancaria emitida (dinheiro que saiu). */
  obs?: DocumentoHabilTE[] | null;
  /** Minutas de DH e OPs sem OB (dinheiro que ainda nao saiu). */
  pendentes?: DocumentoHabilTE[] | null;
}

// Vazio = TODAS (convencao do <MultiSelect>), entao "TODAS" saiu da lista de
// opcoes — antes era um valor especial que precisava ser filtrado no envio.
/* ⚠️ CLASSE DE GRID LITERAL NO CODIGO-FONTE. Montada por concatenacao ou por
   template string o Tailwind nao ve na varredura e a grade sai SEM COLUNAS —
   tudo empilhado numa coluna so, sem erro nenhum no console. Mesmo padrao dos
   COLS_* de components/TransfereGovPropostas.tsx. */
const COLS_DH = "grid-cols-[8rem_9rem_9rem_8.5rem_minmax(8rem,1fr)_8rem]";
const COLS_EV = "grid-cols-[9.5rem_8rem_minmax(10rem,1fr)]";

const SITUACOES_PA = ["CIENTE", "EM_ANALISE", "IMPEDIDO", "EM_ELABORACAO", "CONCLUIDA"];
const SITUACOES_PA_LABEL: Record<string, string> = Object.fromEntries(
  SITUACOES_PA.map((s) => [s, s.replace(/_/g, " ")])
);



export default function TransfereGovPage() {
  const { municipioId } = useMunicipio();

  const [items, setItems] = useState<Plano[]>([]);
  const [loading, setLoading] = useState(false);
  const [cacheAge, setCacheAge] = useState(0);
  const [total, setTotal] = useState(0);

  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [programa, setPrograma] = useState("");
  const [parlamentar, setParlamentar] = useState("");
  const [emenda, setEmenda] = useState("");
  const [objeto, setObjeto] = useState("");
  const [anosSel, setAnosSel] = useState<string[]>([]);
  /* Recolhido por ANO. Guarda o que está FECHADO e não o que está aberto: assim
     um ano novo que chegue na próxima coleta nasce ABERTO, e não invisível. */
  const [anosFechados, setAnosFechados] = useState<Set<string>>(new Set());

  const [detalhe, setDetalhe] = useState<DetalhePlano | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);
  const [tab, setTab] = useState<"basicos" | "orcamento" | "execucao" | "pagamentos">("basicos");
  /* Qual pagamento esta com o historico ABERTO ("ao selecionar tem os
     historicos"). Guarda o opob_id, nao o indice: a lista se reordena quando o
     coletor roda de novo e o indice apontaria para outra linha. */
  const [opAberta, setOpAberta] = useState<number | null>(null);
  const [baixandoPdf, setBaixandoPdf] = useState(false);

  const filtrosParams = useCallback((): Record<string, string | string[]> => {
    // string[] no filtro multi: o axios manda chave repetida e o FastAPI le list[str].
    const params: Record<string, string | string[]> = { municipio_id: municipioId || "" };
    if (situacoesSel.length) params.situacao = situacoesSel;
    if (programa.trim()) params.programa = programa.trim();
    if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
    if (emenda.trim()) params.emenda = emenda.trim();
    if (objeto.trim()) params.objeto = objeto.trim();
    return params;
  }, [municipioId, situacoesSel, programa, parlamentar, emenda, objeto]);

  const buscar = useCallback(async (refresh = false) => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string | string[] | boolean> = { ...filtrosParams() };
      if (refresh) params.refresh = true;
      const r = await api.get<BuscarResp>("/transferegov/buscar", { params });
      setItems(r.data.items);
      setTotal(r.data.total);
      setCacheAge(r.data.cache_age_seconds);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [municipioId, filtrosParams]);

  const gerarPdf = useCallback(async () => {
    if (!municipioId) return;
    setBaixandoPdf(true);
    try {
      const r = await api.get("/export-pdf/plano-acao", { params: filtrosParams(), responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url; a.download = "relatorio-plano-acao.pdf";
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); } finally { setBaixandoPdf(false); }
  }, [municipioId, filtrosParams]);

  useEffect(() => {
    if (municipioId) buscar(false);
  }, [municipioId]); // eslint-disable-line react-hooks/exhaustive-deps

  const limpar = () => {
    setSituacoesSel([]); setPrograma(""); setParlamentar(""); setEmenda(""); setObjeto("");
    setAnosSel([]);
    setItems([]); setTotal(0);
  };

  /** O que está filtrando AGORA, para o cabeçalho do painel recolhido — mesma
   *  regra das telas vizinhas: recorte aplicado nunca fica invisível. */
  const filtrosAtivos = useMemo<FiltroAtivo[]>(() => {
    const a: FiltroAtivo[] = [];
    const t = (chave: string, rot: string, v: string, limparCampo: () => void) => {
      if (v.trim()) a.push({ chave, rotulo: `${rot}: ${v.trim()}`, remover: limparCampo });
    };
    situacoesSel.forEach((s) => a.push({
      chave: `sit:${s}`, rotulo: SITUACOES_PA_LABEL[s] ?? s,
      remover: () => setSituacoesSel((x) => x.filter((y) => y !== s)),
    }));
    t("programa", "Programa", programa, () => setPrograma(""));
    t("parlamentar", "Parlamentar", parlamentar, () => setParlamentar(""));
    t("emenda", "Emenda", emenda, () => setEmenda(""));
    t("objeto", "Objeto", objeto, () => setObjeto(""));
    anosSel.forEach((y) => a.push({
      chave: `ano:${y}`, rotulo: y,
      remover: () => setAnosSel((x) => x.filter((z) => z !== y)),
    }));
    return a;
  }, [situacoesSel, programa, parlamentar, emenda, objeto, anosSel]);

  /** Os anos que EXISTEM no resultado, para o dropdown não oferecer ano vazio. */
  const anosDisponiveis = useMemo(
    () => Array.from(new Set(items.map(anoDa).filter(Boolean))).sort((a, b) => b.localeCompare(a)),
    [items]
  );
  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anosDisponiveis, setAnosSel);

  /* Filtro de ano é CLIENT-SIDE: o ano não é parâmetro da API pública do
     TransfereGov, e a listagem já vem inteira para o município. Repare que
     filtro e agrupamento chamam a MESMA `anoDa` — se divergissem, o gestor
     filtraria 2024 e veria um grupo 2023. */
  const displayItems = useMemo(
    () => (anosSel.length ? items.filter((p) => anosSel.includes(anoDa(p))) : items),
    [items, anosSel]
  );

  /** Agrupado por ano, do mais recente para o mais antigo.
   *
   *  Plano sem ano legível NÃO é escondido: cai num grupo "Sem ano" no fim.
   *  Sumir com um plano porque o código veio fora do padrão é pior que
   *  mostrá-lo separado. */
  const porAno = useMemo(() => {
    const m = new Map<string, Plano[]>();
    for (const p of displayItems) {
      const a = anoDa(p) || "Sem ano";
      (m.get(a) ?? m.set(a, []).get(a)!).push(p);
    }
    return Array.from(m.entries()).sort((x, y) =>
      x[0] === "Sem ano" ? 1 : y[0] === "Sem ano" ? -1 : y[0].localeCompare(x[0]));
  }, [displayItems]);

  const alternarAno = (a: string) =>
    setAnosFechados((prev) => {
      const n = new Set(prev);
      if (n.has(a)) n.delete(a); else n.add(a);
      return n;
    });

  const abrirDetalhe = async (id: number) => {
    setDetalhe(null);
    setTab("basicos");
    setLoadingDetalhe(true);
    try {
      const r = await api.get<DetalhePlano>(`/transferegov/plano-acao/${id}`);
      setDetalhe(r.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingDetalhe(false);
    }
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">
      Selecione um município.
    </div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <TituloTela>Plano de Ação - TransfereGov</TituloTela>
          <p className="text-sm text-base-content/60">Transferência Especial Federal (Pix Parlamentar)</p>
        </div>
        <div className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
          {cacheAge > 0 && `Cache: ${Math.floor(cacheAge / 60)}min`}
        </div>
      </div>

      {/* Filtros RECOLHÍVEIS. Esta tela não tem o defeito de busca das outras (os
          campos já nascem separados), mas tem cinco colunas de filtro e quatro
          botões sempre abertos empurrando o primeiro plano de ação para baixo da
          dobra. Mesmo painel das telas de propostas e do PAC. */}
      <PainelFiltros
        ativos={filtrosAtivos}
        aoLimparTudo={limpar}
        titulo="Pesquisa"
        direita={
          <Button variant="outline" size="sm" onClick={gerarPdf} disabled={baixandoPdf || items.length === 0}
                  title="Gera um PDF só com os planos filtrados">
            {baixandoPdf ? <Loader2 className="size-4 animate-spin mr-1" /> : null} 📄 Gerar PDF (filtrado)
          </Button>
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>
              Situação do Plano de Ação{" "}
              <span style={{ color: "var(--bi-faint)" }}>(uma, algumas ou todas)</span>
            </label>
            <MultiSelect
              opcoes={SITUACOES_PA}
              valor={situacoesSel}
              onChange={setSituacoesSel}
              rotulos={SITUACOES_PA_LABEL}
              placeholder="TODAS"
              rotuloTodos="TODAS"
              ariaLabel="Situação do plano de ação"
            />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Programa (código)</label>
            <Input value={programa} onChange={(e) => setPrograma(e.target.value)} placeholder="Ex: 09032022" />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Parlamentar (nome)</label>
            <Input value={parlamentar} onChange={(e) => setParlamentar(e.target.value)} placeholder="Ex: LUIS TIBE" />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Emenda Parlamentar (código)</label>
            <Input value={emenda} onChange={(e) => setEmenda(e.target.value)} placeholder="Ex: 202241760007" />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Objeto/Política Pública</label>
            <Input value={objeto} onChange={(e) => setObjeto(e.target.value)} placeholder="Ex: Urbanismo, Saúde" />
          </div>
          {/* Anos: o único filtro desta tela que NÃO vai à API — o ano sai do
              código da emenda, que já veio na listagem. Por isso ele aplica
              sozinho, sem depender do botão Filtrar. */}
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>
              Anos <span style={{ color: "var(--bi-faint)" }}>(um, alguns ou todos)</span>
            </label>
            <MultiSelect
              opcoes={anosDisponiveis}
              valor={anosSel}
              onChange={setAnosSel}
              atalhos={atalhosAnos()}
              formatarResumo={resumoAnos}
              placeholder="Todos os anos"
              rotuloTodos="Todos os anos"
              ariaLabel="Anos"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-3">
          {/* ⚠️ `limpar` aqui também esvazia `items` e deixa a tela em branco até
              alguém apertar Filtrar — diferente das telas vizinhas, onde Limpar
              REFAZ a busca sem filtro. Não alterado de propósito: é mudança de
              comportamento, não de layout. */}
          <Button variant="outline" onClick={limpar}><Eraser className="size-4 mr-1" /> Limpar</Button>
          <Button variant="outline" onClick={() => buscar(true)} disabled={loading} title="Refresh cache do TransfereGov">
            <RefreshCw className="size-4 mr-1" /> Atualizar
          </Button>
          {/* Sem `bg-primary` na mão: a variante padrão do Button já é
              `btn-primary`, e a classe só repintava por cima. */}
          <Button onClick={() => buscar(false)} disabled={loading}>
            {loading ? <Loader2 className="size-4 mr-1 animate-spin" /> : <Search className="size-4 mr-1" />}
            Filtrar
          </Button>
          {/* O "Gerar PDF (filtrado)" subiu para o cabeçalho do painel (prop
              `direita`): é ação sobre o RESULTADO, e sumir junto com o painel
              recolhido seria perder o botão. */}
        </div>
      </PainelFiltros>

      {/* A LISTA DEIXOU DE SER TABELA.
          Eram 8 colunas fixas com selo pintado e cabecalho violeta. Agora cada
          plano e um cartao na linguagem do Painel — sem borda entre itens, um
          cinza so para a meta, cor apenas no que e alerta — e com a informacao
          COMPLETA das 8 colunas: objeto no titulo, valor a direita, situacao do
          plano de acao como selo, emenda/beneficiario/UF/codigo na meta,
          situacao do plano de trabalho e os valores na grade de <Campos>.

          O <Campos> e o que permite trocar tabela por cartao sem perder a
          varredura vertical: as posicoes sao as MESMAS em todos os cartoes,
          entao o olho continua descendo por uma coluna. */}
      <div className="space-y-2">
        <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
          <span className="bi-num">{displayItems.length}</span> plano(s) de ação
          {/* O filtro de anos esconde sem avisar; quando esconde, diz de quantos. */}
          {displayItems.length !== total && <> de <span className="bi-num">{total}</span></>}
        </div>
        {loading ? (
          <div className="space-y-1.5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-16 animate-pulse rounded-lg" style={{ background: "var(--bi-surface-2)" }} />
            ))}
          </div>
        ) : displayItems.length === 0 ? (
          /* DUAS causas de lista vazia, e o conselho certo e diferente em cada
             uma. O filtro de Anos e client-side: quando e ELE que zerou a tela,
             mandar "clique em Filtrar" manda fazer justamente a unica coisa que
             nao resolve — a busca volta do servidor igual e o ano continua
             escondendo tudo. Quem tem de mudar e o ano.

             Mesma ramificacao que a tela irma de CNPJ ja faz. */
          <Vazio>
            {items.length > 0 && anosSel.length > 0 ? (
              <>Nenhum plano de ação nos anos selecionados. Ajuste o filtro <strong>Anos</strong>.</>
            ) : (
              <>Nenhum plano encontrado. Use os filtros acima e clique em <strong>Filtrar</strong>.</>
            )}
          </Vazio>
        ) : (
          /* AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO do ano ->
             itens cinza dentro dele. O `p-3` do <Bloco> nao e detalhe de
             estilo: sem ele os cartoes de item encostam na margem do branco, e
             foi por isso que o branco chegou a ser retirado uma vez. */
          <div className="space-y-3">
          {porAno.map(([ano, doAno]) => {
            const fechado = anosFechados.has(ano);
            const totalAno = doAno.reduce((s, p) => s + (p.valor_total || 0), 0);
            return (
            <Bloco key={ano} className="p-3">
              <button type="button" onClick={() => alternarAno(ano)}
                      className="text-left" aria-expanded={!fechado}>
                <BlocoHead
                  icon={fechado ? ChevronRight : ChevronDown}
                  titulo={ano}
                  sub={`${doAno.length} plano(s) de ação`}
                  right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                  className={fechado ? "mb-0" : undefined}
                />
              </button>
              {!fechado && (
              <Lista>
            {doAno.map((p) => (
              <ItemLinha
                key={p.id}
                /* O corpo inteiro abre o mesmo detalhe do botao ao lado: clicar
                   no cartao e o gesto da identidade, e o botao continua ali
                   porque a coluna "Acoes" precisa seguir visivel e obvia. */
                onClick={() => abrirDetalhe(p.id)}
                titulo={
                  p.objeto_descricao?.trim() ||
                  p.politicas_publicas?.trim() ||
                  p.beneficiario_nome ||
                  "Plano de ação"
                }
                valor={formatCurrency(p.valor_total)}
                acao={
                  <button
                    type="button"
                    onClick={() => abrirDetalhe(p.id)}
                    title="Detalhar"
                    className="grid size-7 place-items-center rounded"
                    style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
                  >
                    <Eye className="size-3.5" />
                  </button>
                }
                meta={
                  <>
                    {p.situacao_plano_acao && (
                      <Selo
                        tom={situacaoTom(p.situacao_plano_acao)}
                        title={`Situação do plano de ação: ${p.situacao_plano_acao}`}
                      >
                        {p.situacao_plano_acao.replace(/_/g, " ")}
                      </Selo>
                    )}
                    {/* O codigo da emenda carrega o NOME do parlamentar
                        ("202135950005-Lincoln Portela"). Cortar tira justamente
                        a parte que diz de QUEM veio o recurso — vai inteiro, e
                        com o cinza mais forte da meta por ser o que o gestor
                        procura primeiro. */}
                    {p.emenda_codigo && (
                      <span
                        className="font-medium"
                        style={{ color: "var(--bi-muted)" }}
                        title="Emenda parlamentar"
                      >
                        {p.emenda_codigo}
                      </span>
                    )}
                    {/* UF colada no beneficiario: sozinha, numa coluna de 42px,
                        ela nao respondia a pergunta de ninguem. */}
                    <span>
                      {p.beneficiario_cnpj} - {p.beneficiario_nome} ({p.uf})
                    </span>
                    {/* Identificadores servem para ACHAR, nao para comparar —
                        por isso ficam na meta e nao ocupam coluna na grade. */}
                    <span className="font-mono">
                      · cód {p.codigo}
                      {p.programa_codigo ? ` · prog ${p.programa_codigo}` : ""}
                    </span>
                  </>
                }
              >
                <Campos
                  campos={[
                    {
                      rotulo: "Situação do plano de trabalho",
                      valor: p.situacao_plano_trabalho || "—",
                      tom: situacaoTom(p.situacao_plano_trabalho),
                      title: p.situacao_plano_trabalho,
                    },
                    { rotulo: "Custeio", valor: formatCurrency(p.valor_custeio) },
                    { rotulo: "Investimento", valor: formatCurrency(p.valor_investimento) },
                    {
                      rotulo: "Motivo de impedimento",
                      valor: p.motivo_impedimento || "—",
                      // Critico so quando ha motivo: sem impedimento o campo e
                      // um traco cinza e nao disputa atencao com nada.
                      tom: p.motivo_impedimento ? "critico" : "normal",
                      title: p.motivo_impedimento,
                    },
                    // A FONTE, no canto inferior direito (pedido do dono): o menu
                    // diz a esfera (FEDERAIS), o card diz o sistema de origem.
                    { rotulo: "Fonte", valor: "TransfereGov" },
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

      {/* Modal Detalhe */}
      {(detalhe !== null || loadingDetalhe) && (
        <Modal aberto onFechar={() => setDetalhe(null)} maxW="max-w-5xl">
          <ModalHead
            titulo="Dados do Plano de Ação"
            sub={
              detalhe?.plano
                ? `${detalhe.plano.programaF}-${String(detalhe.plano.codigoSufixo || "").padStart(6, "0")} / ${detalhe.plano.ano}`
                : undefined
            }
            onFechar={() => setDetalhe(null)}
            abaixo={
              detalhe?.plano ? (
                <Abas
                  valor={tab}
                  onChange={(v) => setTab(v)}
                  opcoes={[
                    { valor: "basicos" as const, label: "Dados Básicos" },
                    { valor: "orcamento" as const, label: "Dados Orçamentários" },
                    { valor: "execucao" as const, label: "Execução / Relatório" },
                    { valor: "pagamentos" as const, label: "Pagamentos" },
                  ]}
                />
              ) : undefined
            }
          />
          {loadingDetalhe ? (
            <div className="py-16 text-center">
              <Loader2 className="mx-auto size-8 animate-spin" style={{ color: "var(--bi-faint)" }} />
            </div>
          ) : detalhe?.plano ? (
            <ModalCorpo className="flex flex-col gap-3">
              {/* A faixa de identificação: era um bloco cinza de rótulos em
                  negrito grudados no valor. Vira a grade de campos do sistema —
                  mesmos seis dados, alinhados. */}
              <Secao
                icon={ClipboardList}
                titulo="Identificação"
                cols={3}
                campos={[
                  campoP("Plano de Ação", `${detalhe.plano.programaF}-${String(detalhe.plano.codigoSufixo || "").padStart(6, "0")} / ${detalhe.plano.ano}`),
                  campoP("Programa", detalhe.plano.programaF),
                  campoP("Situação", detalhe.plano.situacao),
                  campoP(
                    "Beneficiário",
                    `${detalhe.plano.beneficiario?.cnpj} - ${detalhe.plano.beneficiario?.nome} (${detalhe.plano.beneficiario?.uf})`,
                    { span: 2 },
                  ),
                  campoP("Emenda Parlamentar", detalhe.plano.emendaParlamentar?.codigoEmendaFormatado),
                ]}
              />

              <div key={tab} className="bi-pane-enter flex flex-col gap-3">
              {tab === "basicos" && (
                <>
                  <Secao
                    icon={Building2}
                    titulo="Dados do Beneficiário"
                    campos={[
                      campoP("Beneficiário (Obrigatório)", `${detalhe.plano.beneficiario?.cnpj} - ${detalhe.plano.beneficiario?.nome}`, { span: 2 }),
                      campoP("UF (Obrigatório)", detalhe.plano.beneficiario?.uf),
                      campoP("Código IBGE", detalhe.plano.beneficiario?.ibge),
                      campoP("IDH", detalhe.plano.beneficiario?.idh),
                      campoP("E-mail Câmara", detalhe.plano.emailCamara, { span: 3 }),
                    ]}
                  />
                  <Secao
                    icon={Landmark}
                    titulo="Dados da Emenda Parlamentar"
                    campos={[
                      campoP("Emenda Parlamentar (Obrigatório)", detalhe.plano.emendaParlamentar?.codigoEmendaFormatado),
                      campoP("Parlamentar", detalhe.plano.emendaParlamentar?.nomeParlamentar, { span: 2 }),
                      campoP("Código Parlamentar", detalhe.plano.emendaParlamentar?.codigoParlamentar),
                      campoP("Ano", detalhe.plano.emendaParlamentar?.ano),
                      { rotulo: "Valor de Custeio (Obrigatório)", valor: formatCurrency(detalhe.plano.valorCusteio) },
                      { rotulo: "Valor de Investimento (Obrigatório)", valor: formatCurrency(detalhe.plano.valorInvestimento) },
                    ]}
                  />
                  <Secao icon={FileText} titulo="Dados Complementares do Plano">
                    <Campos
                      cols={2}
                      campos={[
                        campoP("Modalidade", detalhe.plano.modalidade),
                      ]}
                    />
                    {/* Objeto e Motivo de Impedimento saem da grade: são texto
                        livre, às vezes de vários parágrafos, e a célula trunca
                        por desenho. */}
                    <div className="mt-2.5">
                      <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Objeto</div>
                      <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                        {textoDe(detalhe.plano.objeto) || detalhe.plano.objetoDetalhe || "-"}
                      </p>
                    </div>
                    <div className="mt-2.5">
                      <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Motivo Impedimento</div>
                      <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                        {detalhe.plano.motivoImpedimento || "-"}
                      </p>
                    </div>
                    <Campos cols={2} campos={[campoP("Anexos", detalhe.plano.listaAPP?.length ?? 0)]} />
                  </Secao>
                </>
              )}

              {tab === "orcamento" && (
                <>
                  <Secao
                    icon={Banknote}
                    titulo="Orçamento do Plano"
                    cols={3}
                    campos={[
                      { rotulo: "Valor de Custeio", valor: formatCurrency(detalhe.plano.valorCusteio) },
                      { rotulo: "Valor de Investimento", valor: formatCurrency(detalhe.plano.valorInvestimento) },
                      { rotulo: "Valor Total", valor: formatCurrency(detalhe.plano.valorTotal) },
                    ]}
                  />
                  {detalhe.plano.emendaParlamentar && (
                    /* Sub-bloco próprio, e não campos soltos: Custeio e
                       Investimento aparecem DUAS vezes no modal, com origens
                       diferentes — o valor do PLANO e o valor da EMENDA. Juntar
                       os quatro numa grade só apagaria a diferença. */
                    <Secao
                      icon={Landmark}
                      titulo="Da Emenda Parlamentar"
                      cols={2}
                      campos={[
                        { rotulo: "Custeio na Emenda", valor: formatCurrency(detalhe.plano.emendaParlamentar.valorCusteio) },
                        { rotulo: "Investimento na Emenda", valor: formatCurrency(detalhe.plano.emendaParlamentar.valorInvestimento) },
                      ]}
                    />
                  )}
                </>
              )}

              {tab === "pagamentos" && (
                !detalhe.pagamentos ? (
                  /* Terceiro estado, e nao "não há pagamentos": a coluna vem
                     NULA enquanto o coletor nao visitou este plano. Escrever
                     "sem pagamentos" aqui seria afirmar o que ninguem mediu. */
                  <Vazio>Pagamentos ainda não coletados para este plano de ação.</Vazio>
                ) : (
                  <Secao
                    icon={Banknote}
                    titulo="Pagamentos — Documentos Hábeis e Ordens Bancárias"
                    cols={4}
                    campos={[
                      { rotulo: "Valor Total", valor: formatCurrency(detalhe.pagamentos.valor_total) },
                      { rotulo: "Desembolsado", valor: formatCurrency(detalhe.pagamentos.valor_desembolsado), tom: "ok" },
                      { rotulo: "A Desembolsar", valor: formatCurrency(detalhe.pagamentos.valor_a_desembolsar),
                        tom: detalhe.pagamentos.pago_integral ? "ok" : "atencao" },
                      campoP("Último Desembolso", detalhe.pagamentos.data_ultimo_desembolso),
                    ]}
                  >
                    {(() => {
                      const linhas = [
                        ...(detalhe.pagamentos?.obs || []),
                        ...(detalhe.pagamentos?.pendentes || []),
                      ];
                      if (!linhas.length) {
                        return <Vazio>Nenhum documento hábil emitido para este plano.</Vazio>;
                      }
                      return (
                        <div className="mt-3">
                          <div className="mb-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                            Lista de Documentos Hábeis · {linhas.length}
                          </div>
                          <Grade
                            rolagem
                            cols={COLS_DH}
                            cabecalho={[
                              { label: "Empenho" }, { label: "Minuta" }, { label: "Documento Hábil" },
                              { label: "Valor", direita: true }, { label: "Situação" },
                              { label: "Ordem de Pagamento" },
                            ]}
                          >
                            {linhas.map((d, i) => (
                              <React.Fragment key={d.dh_id ?? i}>
                                <GradeLinha cols={COLS_DH}>
                                  <GradeCel tom="id">{d.numero_empenho || "-"}</GradeCel>
                                  <GradeCel tom="id">{d.minuta || "-"}</GradeCel>
                                  <GradeCel tom="id">{d.numero_dh || "-"}</GradeCel>
                                  <GradeCel tom="num">{formatCurrency(d.valor)}</GradeCel>
                                  <GradeCel>
                                    {d.situacao_dh
                                      ? <Selo tom={situacaoTom(d.situacao_dh)}>{d.situacao_dh}</Selo>
                                      : "-"}
                                  </GradeCel>
                                  <GradeCel>
                                    {d.numero_op ? (
                                      /* "ao selecionar tem os historicos": a OP é o
                                         gatilho, como na tela federal, onde o número
                                         da OP é o link para detalhar-ordem-pagamento. */
                                      <button
                                        type="button"
                                        className="underline underline-offset-2"
                                        onClick={() => setOpAberta(
                                          opAberta === (d.opob_id ?? -1) ? null : (d.opob_id ?? null))}
                                        title="Ver histórico de eventos de pagamento"
                                      >
                                        {d.numero_op}
                                      </button>
                                    ) : "-"}
                                  </GradeCel>
                                </GradeLinha>
                                {d.opob_id != null && opAberta === d.opob_id && (
                                  <div className="px-2 py-2" style={{ background: "var(--bi-surface-2)" }}>
                                    <Campos
                                      cols={4}
                                      campos={[
                                        campoP("Ordem Bancária", d.numero_ob),
                                        campoP("Emissão da OB", d.data_emissao_ob),
                                        campoP("Ordenador de Despesa", d.ordenador_despesa),
                                        campoP("Gestor Financeiro", d.gestor_financeiro),
                                        campoP("Assinatura do Ordenador", d.dt_assinatura_ordenador),
                                        campoP("Assinatura do Gestor", d.dt_assinatura_gestor),
                                        campoP("Situação da OP", d.situacao, { span: 2 }),
                                      ]}
                                    />
                                    <div className="mt-2 mb-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                                      Histórico de Eventos de Pagamento · {(d.historico || []).length}
                                    </div>
                                    {(d.historico || []).length === 0 ? (
                                      <Vazio>Sem eventos registrados para esta ordem de pagamento.</Vazio>
                                    ) : (
                                      <Grade
                                        rolagem
                                        cols={COLS_EV}
                                        cabecalho={[{ label: "Data" }, { label: "Responsável" }, { label: "Situação" }]}
                                      >
                                        {(d.historico || []).map((h, j) => (
                                          <GradeLinha key={j} cols={COLS_EV}>
                                            <GradeCel tom="data">{h.data || "-"}</GradeCel>
                                            <GradeCel tom="id">{h.responsavel || "-"}</GradeCel>
                                            <GradeCel>{h.situacao || "-"}</GradeCel>
                                          </GradeLinha>
                                        ))}
                                      </Grade>
                                    )}
                                  </div>
                                )}
                              </React.Fragment>
                            ))}
                          </Grade>
                        </div>
                      );
                    })()}
                  </Secao>
                )
              )}

              {tab === "execucao" && (
                detalhe.resumo ? (
                  <Secao
                    icon={TrendingUp}
                    titulo="Relatório de Gestão"
                    campos={[
                      campoP("Meses em Execução", detalhe.resumo.nrMesesExecucao),
                      { rotulo: "Custeio Previsto", valor: formatCurrency(detalhe.resumo.valorTotalCusteio) },
                      { rotulo: "Investimento Previsto", valor: formatCurrency(detalhe.resumo.valorTotalInvestimento) },
                      { rotulo: "Custeio Executado", valor: formatCurrency(detalhe.resumo.valorTotalCusteioExecutado) },
                      { rotulo: "Investimento Executado", valor: formatCurrency(detalhe.resumo.valorTotalInvestimentoExecutado) },
                      { rotulo: "Total Executado", valor: formatCurrency(detalhe.resumo.valorTotalExecutado), tom: "ok" },
                      { rotulo: "Total Pendente", valor: formatCurrency(detalhe.resumo.valorTotalPendente), tom: "atencao" },
                    ]}
                  />
                ) : (
                  <Vazio>Sem relatório de gestão registrado para este plano.</Vazio>
                )
              )}
              </div>
            </ModalCorpo>
          ) : null}
        </Modal>
      )}
    </div>
  );
}

