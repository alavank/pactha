"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Search, Eraser, Loader2, ExternalLink, Eye, AlertTriangle, ChevronDown, ChevronRight,
  FileText, Handshake, CalendarDays, Building2, Info, Paperclip,
  Banknote, HardHat, MessagesSquare,
} from "lucide-react";
import api from "@/lib/api";
// Uma funcao de dinheiro no sistema inteiro. Havia CINCO copias, e a
// desta tela ja tinha derivado: arredondava, e o mesmo valor aparecia
// com e sem centavos no mesmo print.
import { formatCurrency as moeda } from "@/lib/utils";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { textoDe } from "@/lib/texto";
import {
  Abas, Aviso, Bloco, BlocoHead, Campo, Campos, Grade, GradeCel,
  GradeLinha, ItemLinha, Lista, Modal, ModalCorpo, ModalHead, Secao, Selo,
  Vazio, situacaoTom,
} from "@/components/ui/superficies";

/** O ANO de uma proposta.
 *
 *  Vem do próprio número (`057216/2025`), que é a fonte mais confiável: a
 *  data da proposta chega como texto já formatado pelo portal e nem sempre
 *  existe. O início de vigência serve de segunda opção porque uma proposta
 *  pode ter sido protocolada num ano e assinada no seguinte — e para agrupar
 *  o que importa é o exercício da proposta. */
function anoDa(p: { numero_proposta?: string; dt_proposta?: string; dt_inicio_vigencia?: string }): string {
  const doNumero = /\/(\d{4})\s*$/.exec(p.numero_proposta || "");
  if (doNumero) return doNumero[1];
  const daData = /(\d{4})/.exec(p.dt_proposta || p.dt_inicio_vigencia || "");
  return daData ? daData[1] : "";
}

/** Trilhas das grades densas. Escritas LITERAIS e no topo do módulo porque o
 *  Tailwind só gera a classe se ela aparecer no código-fonte — montar
 *  `grid-cols-[${x}]` produz uma grade sem colunas. */
const COLS_OB = "grid-cols-[6.5rem_6.5rem_6.5rem_7.5rem_minmax(7rem,1fr)_6.5rem]";
const COLS_SUBMETA = "grid-cols-[5rem_minmax(10rem,1fr)_7.5rem_9rem_7rem]";
const COLS_NE = "grid-cols-[8rem_8rem_8rem_8rem_minmax(7rem,1fr)_7rem]";
const COLS_ART = "grid-cols-[5rem_8rem_6.5rem_minmax(9rem,1fr)]";

/** O `-` de campo vazio precisa continuar exatamente onde estava.
 *
 *  O helper `Field` que existia aqui trocava null/undefined/"" por "-", e a
 *  peça `Campos` da identidade NÃO faz isso: ela renderiza o que receber. Sem
 *  este intermediário, os campos sem dado sairiam em branco em vez de "-", e
 *  um rótulo com nada embaixo parece defeito de carregamento.
 *
 *  Repare no que NÃO é vazio: `0`. Escrever `valor || "-"` transformaria zero
 *  em traço, e "0 dias sem medição" viraria "sem informação". */
function campo(rotulo: string, valor: unknown, extra?: Partial<Campo>): Campo {
  const v = valor === null || valor === undefined || valor === "" ? "-" : String(valor);
  return { rotulo, valor: v, title: v === "-" ? undefined : `${rotulo}: ${v}`, ...extra };
}
import AnotacaoButton, { precarregarContagens } from "@/components/AnotacaoButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Proposta {
  numero_proposta: string;
  situacao: string;
  orgao: string;
  proponente: string;
  possui_parecer: string;
  identificacao: string;
  codigo_instrumento?: string;
  modalidade?: string;
  situacao_siafi?: string;
  numero_processo?: string;
  objeto?: string;
  programa?: string;
  dt_inicio_vigencia?: string;
  dt_fim_vigencia?: string;
  dt_proposta?: string;
  dt_assinatura?: string;
  dias_restantes?: number | null;
  atualizado_em?: string;
  situacao_contratacao?: string | null;
  clausula_suspensiva_dt_prevista?: string | null;
  clausula_suspensiva_motivo?: string | null;
  parlamentar?: string | null;
  valor_global?: number | null;
  valor_repasse?: number | null;
  valor_contrapartida?: number | null;
  situacao_contratacao_detalhe?: Record<string, string | null> | null;
  processo_execucao_qtd?: number | null;
  /** Lista das licitações/processos COM situação (Concluído / Em execução ...). */
  processo_execucao?: Array<{
    numero?: string | null; modalidade?: string | null;
    data_publicacao?: string | null; situacao?: string | null;
    sistema_origem?: string | null; aceite?: string | null;
  }> | null;
  historico_comunicacoes?: Record<string, string>[];
  documentos_quadro_resumo?: Record<string, string>[];
  historico_atualizado_em?: string | null;
  /** Projeto Básico/Termo de Referência: o documento que sustenta a cláusula
   *  suspensiva e em que pé ele está no portal. Só é coletado para convênio em
   *  cláusula suspensiva, então vem nulo na maioria das propostas. */
  projeto_basico?: {
    situacao?: string | null;
    documentos?: Array<{
      nome_arquivo?: string | null; descricao?: string | null;
      tipo?: string | null; data_upload?: string | null;
    }>;
  } | null;
  /** NEs (Notas de Empenho) da aba Execução Concedente.
   *  ⚠️ `minuta_apenas` marca a linha que NÃO é dinheiro: a listagem do portal
   *  mistura o empenho com a minuta, que vem sem número e com valor de R$ 1,00. */
  notas_empenho?: Array<{
    numero?: string | null; minuta?: string | null;
    valor?: number | null; valor_siafi?: number | null;
    situacao?: string | null; dt_emissao?: string | null;
    minuta_apenas?: boolean;
  }> | null;
}

interface Resp { items: Proposta[]; total: number; atualizado_em?: string; }

interface OpsObs {
  valor_total_repasse?: number | null;
  valor_desembolsado?: number | null;
  valor_a_desembolsar?: number | null;
  data_ultimo_desembolso?: string | null;
  obs?: Array<{
    numero_interno?: string; numero_ns?: string; numero_op?: string; numero_ob?: string;
    ug_emitente?: string; gestao_emitente?: string; valor?: number | null;
    valor_acerto?: number | null; situacao?: string; data_emissao_ob?: string;
  }>;
}
interface ObraSubmeta {
  numero?: string; descricao?: string; situacao?: string;
  regime_execucao?: string; valor?: number | null; valor_realizado?: number | null;
}
interface ObraArt {
  /* `unknown`, e não `string`, porque é o que a fonte realmente manda: a API de
     obras devolve `tipo` como `{codigo:"EXE", descricao:"Execução"}` e
     `responsavel_tecnico` como `{id, cpf, nome, ...}`. Declarar `string` aqui
     não fazia virar texto — só escondia o problema do compilador até o
     navegador do cliente. Passam por `textoDe()` na hora de mostrar. */
  tipo?: unknown; numero?: string; dt_emissao?: string; responsavel_tecnico?: unknown;
}
interface ObraLote {
  tipo?: string; numero?: string; id_contrato?: number | null;
  apto_iniciar?: boolean; atrasado?: boolean | null; paralisado?: boolean | null;
  dias_sem_medicao?: number | null;
  submetas?: ObraSubmeta[];
  contrato?: {
    numero?: string; cnpj?: string; empresa?: string; objeto?: string;
    valor?: number | null; dt_assinatura?: string; dt_inicio_vigencia?: string; dt_fim_vigencia?: string;
  } | null;
  arts?: ObraArt[];
}
interface Obras {
  situacao_paralisacao?: string | null;
  valor_total_submetas?: number | null;
  valor_total_realizado?: number | null;
  objeto?: string | null;
  lotes?: ObraLote[];
}


interface Detalhe extends Proposta {
  detalhe?: Record<string, string | string[]>;
  ops_obs?: OpsObs | null;
  obras?: Obras | null;
}

const PORTAL_BASE = "https://discricionarias.transferegov.sistema.gov.br/voluntarias/ForwardAction.do?modulo=Principal&path=/MostraPrincipalConsultarProposta.do&Usr=guest&Pwd=guest";

// Estava incompleto (faltavam vence30 e vence90), e o chip do filtro vindo dos
// KPIs mostrava o codigo cru ("vence30") em vez do rotulo.
const VIGENCIA_LABELS: Record<string, string> = {
  vence30: "Vence em 30 dias",
  vence60: "Vence em 60 dias",
  vence90: "Vence em 90 dias",
  vence120: "Vence em 120 dias",
  prestacao: "Prestação de contas (vencido +90d)",
};

/** Ordem que o gestor espera ver no dropdown (do mais curto ao mais longo). */
const VIGENCIA_OPCOES = ["vence30", "vence60", "vence90", "vence120", "prestacao"];

/** Valores da coluna `situacao_contratacao` no TransfereGov. */
const SIT_CONTRATACAO_OPCOES = ["Normal", "Cláusula Suspensiva", "Liminar Judicial"];

function fmtData(iso?: string): string {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }); }
  catch { return "-"; }
}
export default function TransfereGovPropostas({
  categoria,
  titulo,
  subtitulo,
}: {
  categoria: "geral" | "voluntarias" | "rejeitadas" | "encerradas";
  titulo: string;
  subtitulo: string;
}) {
  const sp = useSearchParams();
  const { municipioId } = useMunicipio();
  const vigenciaParam = sp.get("vigencia");

  const [items, setItems] = useState<Proposta[]>([]);
  const [atualizadoEm, setAtualizadoEm] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [vigenciaSel, setVigenciaSel] = useState<string[]>(vigenciaParam ? [vigenciaParam] : []);
  const [parlamentar, setParlamentar] = useState("");
  const [orgao, setOrgao] = useState("");
  const [sitContratacaoSel, setSitContratacaoSel] = useState<string[]>([]);
  const [vigFimDe, setVigFimDe] = useState("");
  const [vigFimAte, setVigFimAte] = useState("");
  const [anosSel, setAnosSel] = useState<string[]>([]);
  /* Recolhido por ANO. Guarda o que está FECHADO e não o que está aberto:
     assim um ano novo que chegue na próxima coleta nasce aberto. */
  const [anosFechados, setAnosFechados] = useState<Set<string>>(new Set());
  const [baixandoPdf, setBaixandoPdf] = useState(false);

  const [detalhe, setDetalhe] = useState<Detalhe | null>(null);
  // Aba ativa do modal de detalhe (evita rolagem gigante com 50+ eventos)
  const [aba, setAba] = useState<"dados" | "opsobs" | "obras" | "historico" | "docs">("dados");
  const [loadingDet, setLoadingDet] = useState(false);

  const buildParams = useCallback((): Record<string, string | string[]> => {
    // string[] p/ os filtros multi: o axios serializa como chave repetida
    // (?vigencia=a&vigencia=b), que e o formato que o FastAPI le em list[str].
    const params: Record<string, string | string[]> = { municipio_id: municipioId || "", categoria };
    if (search.trim()) params.search = search.trim();
    if (vigenciaSel.length) params.vigencia = vigenciaSel;
    if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
    if (orgao.trim()) params.orgao = orgao.trim();
    if (sitContratacaoSel.length) params.situacao_contratacao = sitContratacaoSel;
    if (vigFimDe) params.vig_fim_de = vigFimDe;
    if (vigFimAte) params.vig_fim_ate = vigFimAte;
    return params;
  }, [municipioId, categoria, search, vigenciaSel, parlamentar, orgao, sitContratacaoSel, vigFimDe, vigFimAte]);

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const r = await api.get<Resp>("/transferegov/voluntarias", { params: buildParams() });
      setItems(r.data.items); setAtualizadoEm(r.data.atualizado_em);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId, buildParams]);

  const gerarPdf = useCallback(async () => {
    if (!municipioId) return;
    setBaixandoPdf(true);
    try {
      const r = await api.get("/export-pdf/voluntarias", { params: buildParams(), responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url; a.download = `relatorio-federais-${categoria}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); } finally { setBaixandoPdf(false); }
  }, [municipioId, categoria, buildParams]);

  // Sincroniza filtro de vigencia com o parametro da URL (vindo dos KPIs)
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setVigenciaSel(vigenciaParam ? [vigenciaParam] : []); }, [vigenciaParam]);

  // Busca ao montar e sempre que municipio/categoria/vigencia mudarem
  useEffect(() => { if (municipioId) buscar(); }, [municipioId, vigenciaSel, categoria]); // eslint-disable-line react-hooks/exhaustive-deps

  // Opcoes do multi-select = situacoes distintas presentes nos dados carregados
  const situacaoOptions = useMemo(
    () => Array.from(new Set(items.map((i) => i.situacao).filter(Boolean))).sort(),
    [items]
  );

  /* UMA requisição para a contagem de anotações da lista inteira, em vez de
     uma por linha no endpoint que traz os anexos junto. */
  useEffect(() => {
    if (items.length) precarregarContagens("voluntaria", items.map((p) => p.numero_proposta));
  }, [items]);

  /** Os anos que EXISTEM no resultado, para o dropdown não oferecer ano vazio. */
  const anosDisponiveis = useMemo(
    () => Array.from(new Set(items.map(anoDa).filter(Boolean))).sort((a, b) => b.localeCompare(a)),
    [items]
  );

  // Filtro de situacao e de ANO, client-side (os dois sao multi-select)
  const displayItems = useMemo(() => {
    let r = items;
    if (situacoesSel.length) r = r.filter((i) => situacoesSel.includes(i.situacao));
    if (anosSel.length) r = r.filter((i) => anosSel.includes(anoDa(i)));
    return r;
  }, [items, situacoesSel, anosSel]);

  /** Agrupado por ano, do mais recente para o mais antigo.
   *
   *  É o mesmo desenho das Emendas Estaduais, que o dono escolheu como padrão
   *  do produto: cada ano é um cartão BRANCO com cabeçalho (ano, contagem,
   *  total à direita) e a lista de itens cinza dentro dele, sobre o fundo
   *  cinza da página. As três camadas do Painel.
   *
   *  Proposta sem ano legível não é escondida: cai num grupo "Sem ano" no fim.
   *  Sumir com registro porque o número veio fora do padrão seria pior que
   *  mostrá-lo separado. */
  const porAno = useMemo(() => {
    const m = new Map<string, Proposta[]>();
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

  const abrirDetalhe = async (numero: string) => {
    setDetalhe(null); setLoadingDet(true); setAba("dados");
    try {
      const r = await api.get<Detalhe>(`/transferegov/voluntarias/${encodeURIComponent(numero)}`,
        { params: { municipio_id: municipioId } });
      setDetalhe(r.data);
    } catch (e) { console.error(e); } finally { setLoadingDet(false); }
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um município.</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-base-content">{titulo}</h1>
          <p className="text-sm text-base-content/60">
            {subtitulo}
            {atualizadoEm && <span className="ml-2 text-xs">· Atualizado: {fmtData(atualizadoEm)}</span>}
          </p>
        </div>
        <a href={PORTAL_BASE} target="_blank" rel="noreferrer noopener"
           className="text-xs text-primary hover:underline inline-flex items-center gap-1">
          <ExternalLink className="size-3" /> Portal oficial
        </a>
      </div>

      <div className="bg-base-100 border rounded p-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Buscar (nº / proponente / CNPJ)</label>
            <Input value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Ex: 048291/2025 ou CNPJ" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Parlamentar</label>
            <Input value={parlamentar} onChange={(e) => setParlamentar(e.target.value)}
                   placeholder="Ex: Cleitinho" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Órgão</label>
            <Input value={orgao} onChange={(e) => setOrgao(e.target.value)}
                   placeholder="Ex: Ministério do Esporte" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">
              Situação de Contratação <span className="text-base-content/40">(uma, algumas ou todas)</span>
            </label>
            <MultiSelect
              opcoes={SIT_CONTRATACAO_OPCOES}
              valor={sitContratacaoSel}
              onChange={setSitContratacaoSel}
              placeholder="Todas"
              rotuloTodos="Todas"
              ariaLabel="Situação de contratação"
            />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">
              Vencimento (fim de vigência) <span className="text-base-content/40">(um ou vários)</span>
            </label>
            <MultiSelect
              opcoes={VIGENCIA_OPCOES}
              valor={vigenciaSel}
              onChange={setVigenciaSel}
              rotulos={VIGENCIA_LABELS}
              placeholder="Todos"
              rotuloTodos="Todos"
              ariaLabel="Vencimento"
            />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Anos</label>
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
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Situação (multi)</label>
            <MultiSelect
              opcoes={situacaoOptions}
              valor={situacoesSel}
              onChange={setSituacoesSel}
              placeholder="Todas as situações"
              rotuloTodos="Todas"
              ariaLabel="Situação da proposta"
            />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Fim de vigência (de)</label>
            <Input type="date" value={vigFimDe} onChange={(e) => setVigFimDe(e.target.value)} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Fim de vigência (até)</label>
            <Input type="date" value={vigFimAte} onChange={(e) => setVigFimAte(e.target.value)} />
          </div>
          <div className="flex items-end gap-2 flex-wrap">
            {/* Sem `bg-primary` na mão: a variante padrão do Button já é a CTA
                quase-preta da identidade, e a classe só repintava de verde por
                cima. Foi o último dos oito. */}
            <Button onClick={buscar} disabled={loading}>
              {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />} Filtrar
            </Button>
            <Button variant="outline" onClick={() => {
              setSearch(""); setSituacoesSel([]); setVigenciaSel([]);
              setParlamentar(""); setOrgao(""); setSitContratacaoSel([]); setVigFimDe(""); setVigFimAte("");
              setTimeout(buscar, 100);
            }}>
              <Eraser className="size-4 mr-1" /> Limpar
            </Button>
            <Button variant="outline" onClick={gerarPdf} disabled={baixandoPdf}
                    title="Gera um PDF só com os instrumentos filtrados">
              {baixandoPdf ? <Loader2 className="size-4 animate-spin mr-1" /> : null} 📄 Gerar PDF (filtrado)
            </Button>
          </div>
        </div>
      </div>

      {/* Chips dos filtros de vencimento ativos (podem vir dos KPIs do
          dashboard ou do proprio dropdown, e agora podem ser varios). */}
      {vigenciaSel.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-base-content/60">Filtro ativo:</span>
          {vigenciaSel.map((v) => (
            <span key={v} className="inline-flex items-center gap-1.5 rounded-full bg-info/15 border border-info px-2.5 py-0.5 text-xs font-medium text-info">
              {VIGENCIA_LABELS[v] ?? v}
              <button
                onClick={() => setVigenciaSel((atual) => atual.filter((x) => x !== v))}
                className="text-info hover:text-info/80"
                aria-label={`Remover filtro ${VIGENCIA_LABELS[v] ?? v}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div>
        <div className="mb-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          <strong className="bi-num">{displayItems.length}</strong> propostas
        </div>
        {loading ? (
          <div className="space-y-1.5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-16 animate-pulse rounded-2xl" style={{ background: "var(--bi-surface-2)" }} />
            ))}
          </div>
        ) : displayItems.length === 0 ? (
          <Vazio>Nenhuma proposta encontrada.</Vazio>
        ) : (
          /* A LISTA DEIXOU DE SER TABELA — as mesmas 12 colunas, agora na
             linguagem do Painel. Este componente serve QUATRO telas (geral,
             voluntarias, rejeitadas e encerradas), entao uma edicao aqui muda
             as quatro de uma vez.
             Os numeros ficam em <Campos>, de largura igual em todos os
             cartoes: e o que permite continuar descendo o olho por uma coluna
             sem existir tabela.

             AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO do ano ->
             itens cinza dentro. O cartao branco ja existiu aqui e foi retirado
             a pedido do dono, porque os itens encostavam na margem e ficava
             feio. O problema era o espacamento, nao o branco: agora o branco
             volta com o `p-3` do `Bloco`, que e o mesmo respiro das Emendas
             Estaduais — a tela que o dono apontou como certa. */
          <div className="space-y-3">
          {porAno.map(([ano, doAno]) => {
            const fechado = anosFechados.has(ano);
            return (
            <Bloco key={ano} className="p-3">
              <button type="button" onClick={() => alternarAno(ano)}
                      className="text-left" aria-expanded={!fechado}>
                <BlocoHead
                  icon={fechado ? ChevronRight : ChevronDown}
                  titulo={ano}
                  sub={`${doAno.length} proposta(s)`}
                  className={fechado ? "mb-0" : undefined}
                />
              </button>
              {!fechado && (
              <Lista>
            {doAno.map((p, i) => {
              const dias = p.dias_restantes;
              const semProcesso =
                p.processo_execucao_qtd === 0 &&
                (p.situacao_contratacao || "").toLowerCase().includes("normal");
              const temDetalhe =
                (p.situacao_contratacao_detalhe &&
                  Object.keys(p.situacao_contratacao_detalhe).filter((k) => !k.startsWith("_")).length > 0) ||
                p.clausula_suspensiva_motivo ||
                p.clausula_suspensiva_dt_prevista;
              return (
                <ItemLinha
                  key={i}
                  onClick={() => abrirDetalhe(p.numero_proposta)}
                  titulo={p.objeto || "Sem objeto informado"}
                  acao={
                    <span onClick={(e) => e.stopPropagation()} className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => abrirDetalhe(p.numero_proposta)}
                        className="grid size-7 place-items-center rounded-lg"
                        style={{ background: "var(--bi-line)", color: "var(--bi-muted)" }}
                        title="Ver detalhe"
                      >
                        <Eye className="size-3.5" />
                      </button>
                      <AnotacaoButton
                        fonte="voluntaria"
                        fonteRef={p.numero_proposta}
                        municipioId={Number(municipioId)}
                        numero={p.codigo_instrumento || p.numero_proposta}
                      />
                    </span>
                  }
                  meta={
                    <>
                      {p.situacao && (
                        <Selo tom={situacaoTom(p.situacao)} title={p.situacao}>{p.situacao}</Selo>
                      )}
                      {p.situacao_contratacao && (
                        <Selo title={`Situação da contratação: ${p.situacao_contratacao}`}>
                          {p.situacao_contratacao}
                        </Selo>
                      )}
                      {/* Este aviso e o unico que ganha cor por padrao: contratacao
                          "Normal" sem processo de execucao registrado e o achado
                          que faz a equipe ir atras. */}
                      {semProcesso && (
                        <Selo tom="critico" title="Contratação Normal sem licitação registrada">
                          sem processo
                        </Selo>
                      )}
                      {temDetalhe && <Selo tom="atencao">tem detalhamento</Selo>}
                      {p.orgao && <span className="truncate">{p.orgao}</span>}
                      {p.parlamentar && <span className="truncate">· {p.parlamentar}</span>}
                      <span className="font-mono">
                        {p.codigo_instrumento ? `· instr ${p.codigo_instrumento}` : ""}
                        {p.numero_proposta ? ` · prop ${p.numero_proposta}` : ""}
                      </span>
                    </>
                  }
                >
                  <Campos
                    campos={[
                      { rotulo: "Início da vigência", valor: p.dt_inicio_vigencia || "—" },
                      { rotulo: "Fim da vigência", valor: p.dt_fim_vigencia || "—" },
                      {
                        rotulo: dias != null && dias < 0 ? "Vencido há" : "Dias restantes",
                        valor: dias != null ? `${Math.abs(dias)}d` : "—",
                        tom: dias == null ? "normal" : dias < 0 ? "critico" : dias <= 60 ? "atencao" : "ok",
                      },
                    ]}
                  />
                </ItemLinha>
              );
            })}
              </Lista>
              )}
            </Bloco>
            );
          })}
          </div>
        )}
      </div>

      {/* Modal detalhe */}
      {(detalhe !== null || loadingDet) && (() => {
        const nHist = (detalhe?.historico_comunicacoes || []).length;
        const nDocs = (detalhe?.documentos_quadro_resumo || []).length;
        const nLotes = (detalhe?.obras?.lotes || []).length;
        const temOpsObs = !!(detalhe?.ops_obs && (detalhe.ops_obs.valor_total_repasse != null || (detalhe.ops_obs.obs || []).length));
        const abas: Array<{ valor: typeof aba; label: string; on: boolean }> = [
          { valor: "dados", label: "Dados", on: true },
          { valor: "opsobs", label: "OPs/OBs", on: temOpsObs },
          { valor: "obras", label: `Obras${nLotes ? ` (${nLotes})` : ""}`, on: nLotes > 0 },
          { valor: "historico", label: `Histórico${nHist ? ` (${nHist})` : ""}`, on: nHist > 0 },
          { valor: "docs", label: `Documentos${nDocs ? ` (${nDocs})` : ""}`, on: nDocs > 0 },
        ];
        const ativa = abas.find((a) => a.valor === aba)?.on ? aba : "dados";
        return (
        <Modal aberto onFechar={() => setDetalhe(null)} maxW="max-w-5xl">
          <ModalHead
            titulo={`Consultar Pré-Instrumento/Instrumento ${detalhe?.codigo_instrumento || detalhe?.numero_proposta || ""}`}
            sub={detalhe?.orgao || undefined}
            onFechar={() => setDetalhe(null)}
            abaixo={detalhe ? <Abas valor={ativa} onChange={setAba} opcoes={abas} /> : undefined}
          />
          {loadingDet ? (
            <div className="py-16 text-center">
              <Loader2 className="mx-auto size-8 animate-spin" style={{ color: "var(--bi-faint)" }} />
            </div>
          ) : detalhe ? (
            <ModalCorpo>
              <div key={ativa} className="bi-pane-enter flex flex-col gap-3">

              {ativa === "dados" && (<>
                <Secao
                  icon={FileText}
                  titulo="Dados da Proposta"
                  campos={[
                    campo("Modalidade", detalhe.modalidade),
                    campo("Situação no SIAFI", detalhe.situacao_siafi),
                    campo("Situação", detalhe.situacao),
                    campo("Código do Instrumento", detalhe.codigo_instrumento),
                    campo("Número da Proposta", detalhe.numero_proposta),
                    campo("Número do Processo", detalhe.numero_processo),
                    campo("Órgão", detalhe.orgao),
                    campo("Programa", detalhe.programa),
                  ]}
                />

                {(detalhe.situacao_contratacao || detalhe.parlamentar || detalhe.situacao_contratacao_detalhe || detalhe.clausula_suspensiva_motivo || detalhe.clausula_suspensiva_dt_prevista) && (
                  <Secao
                    icon={Handshake}
                    titulo="Contratação e Indicação"
                    cols={2}
                    campos={[
                      campo("Situação de Contratação Atual", detalhe.situacao_contratacao),
                      campo("Parlamentar Responsável", detalhe.parlamentar),
                    ]}
                  >
                    {detalhe.situacao_contratacao_detalhe && Object.keys(detalhe.situacao_contratacao_detalhe).filter(k => !k.startsWith("_")).length > 0 && (
                      <Aviso
                        tom="atencao"
                        titulo={`Detalhe da Situação de Contratação${detalhe.situacao_contratacao_detalhe._label_botao ? ` (${String(detalhe.situacao_contratacao_detalhe._label_botao)})` : ""}`}
                      >
                        <Campos
                          cols={2}
                          campos={Object.entries(detalhe.situacao_contratacao_detalhe)
                            .filter(([k]) => !k.startsWith("_"))
                            .map(([k, v]) => campo(k, v))}
                        />
                      </Aviso>
                    )}
                    {(!detalhe.situacao_contratacao_detalhe || Object.keys(detalhe.situacao_contratacao_detalhe).filter(k => !k.startsWith("_")).length === 0) && (detalhe.clausula_suspensiva_motivo || detalhe.clausula_suspensiva_dt_prevista) && (
                      <Aviso tom="atencao" titulo="Detalhe da Cláusula Suspensiva">
                        <Campos
                          cols={2}
                          campos={[
                            campo("Motivo", detalhe.clausula_suspensiva_motivo),
                            campo("Data Prevista", detalhe.clausula_suspensiva_dt_prevista),
                          ]}
                        />
                      </Aviso>
                    )}
                    {/* NEs — Notas de Empenho (Execução Concedente). Troca o
                        "Empenhado: Sim/Não", que é inferência, pelo documento:
                        número, valor, situação e data.
                        ⚠️ A MINUTA fica visível mas SEPARADA, com selo próprio e
                        sem entrar no total: ela vem com R$ 1,00 e sem número, e
                        somá-la poria um real no relatório como se fosse recurso. */}
                    {Array.isArray(detalhe.notas_empenho) && detalhe.notas_empenho.length > 0 && (
                      <Aviso
                        tom="ok"
                        titulo={`Notas de Empenho: ${
                          detalhe.notas_empenho.filter((n) => !n.minuta_apenas).length
                        } · ${moeda(
                          detalhe.notas_empenho
                            .filter((n) => !n.minuta_apenas)
                            .reduce((s, n) => s + (n.valor || 0), 0)
                        )} empenhado`}
                      >
                        <Grade
                          rolagem
                          cols={COLS_NE}
                          cabecalho={[
                            { label: "Nº do empenho" }, { label: "Nº da minuta" },
                            { label: "Valor", direita: true }, { label: "No SIAFI", direita: true },
                            { label: "Situação" }, { label: "Emissão" },
                          ]}
                        >
                          {detalhe.notas_empenho.map((n, i) => (
                            <GradeLinha key={i} cols={COLS_NE}>
                              <GradeCel tom="id">{n.numero || "—"}</GradeCel>
                              <GradeCel>{n.minuta || "—"}</GradeCel>
                              <GradeCel tom="num">{n.valor != null ? moeda(n.valor) : "—"}</GradeCel>
                              <GradeCel tom="num">{n.valor_siafi != null ? moeda(n.valor_siafi) : "—"}</GradeCel>
                              <GradeCel>
                                {n.situacao
                                  ? <Selo tom={n.minuta_apenas ? "neutro" : situacaoTom(n.situacao)}>{n.situacao}</Selo>
                                  : "—"}
                              </GradeCel>
                              <GradeCel>{n.dt_emissao || "—"}</GradeCel>
                            </GradeLinha>
                          ))}
                        </Grade>
                      </Aviso>
                    )}
                    {/* PROJETO BÁSICO / TERMO DE REFERÊNCIA — o Motivo da cláusula diz
                        QUAL documento trava; este diz em que PÉ ele está no portal
                        (ex.: "Em Análise"). Só é coletado para convênio em cláusula
                        suspensiva, e vem NULO quando a sessão do SP `execucao` estava
                        fria na coleta. Nesse caso a caixa não aparece — melhor não
                        mostrar nada do que afirmar uma ausência que não foi medida. */}
                    {detalhe.projeto_basico && (detalhe.projeto_basico.situacao
                      || (detalhe.projeto_basico.documentos || []).length > 0) && (
                      <Aviso
                        tom="atencao"
                        titulo={`Projeto Básico/Termo de Referência${
                          detalhe.projeto_basico.situacao ? ` — ${detalhe.projeto_basico.situacao}` : ""}`}
                      >
                        {(detalhe.projeto_basico.documentos || []).map((d, i) => (
                          <Campos
                            key={i}
                            cols={2}
                            campos={[
                              campo("Documento", d.descricao || d.tipo),
                              campo("Data de upload", d.data_upload),
                              campo("Arquivo", d.nome_arquivo),
                            ]}
                          />
                        ))}
                      </Aviso>
                    )}
                    {/* LICITAÇÃO — só p/ contratação Normal. 0 = convênio Normal sem
                        licitação iniciada (flag, igual à cláusula). O nome no portal do
                        TransfereGov é "Processo de Execução"; aqui e no RM chamamos de
                        Licitação, que é o que o dado é. */}
                    {detalhe.processo_execucao_qtd != null && (detalhe.situacao_contratacao || "").toLowerCase().includes("normal") && (
                      detalhe.processo_execucao_qtd === 0 ? (
                        <Aviso tom="critico" icon={AlertTriangle} titulo="Licitação: NENHUM registro">
                          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                            Contratação Normal, mas sem licitação registrada no TransfereGov
                            (Execução Convenente → Processo de Execução).
                          </p>
                        </Aviso>
                      ) : (
                        <Aviso tom="ok" titulo={`Licitação: ${detalhe.processo_execucao_qtd} registro(s)`}>
                          {/* Detalhes por licitação/processo (situação, modalidade,
                              data). Antes só a contagem aparecia; agora, quando o
                              scraper trouxe a lista, mostra cada registro. */}
                          {Array.isArray(detalhe.processo_execucao) && detalhe.processo_execucao.length > 0 && (
                            <div className="mt-1 space-y-1">
                              {detalhe.processo_execucao.map((pe, i) => (
                                <div key={i} className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                                  <b style={{ color: "var(--bi-text)" }}>{pe.situacao || "—"}</b>
                                  {pe.modalidade ? ` · ${pe.modalidade}` : ""}
                                  {pe.numero ? ` · nº ${pe.numero}` : ""}
                                  {pe.data_publicacao ? ` · ${pe.data_publicacao}` : ""}
                                  {pe.sistema_origem ? ` · ${pe.sistema_origem}` : ""}
                                  {pe.aceite ? ` · ${pe.aceite}` : ""}
                                </div>
                              ))}
                            </div>
                          )}
                        </Aviso>
                      )
                    )}
                  </Secao>
                )}

                <Secao
                  icon={CalendarDays}
                  titulo="Vigência e Datas"
                  campos={[
                    campo("Data da Proposta", detalhe.dt_proposta),
                    campo("Data de Assinatura", detalhe.dt_assinatura),
                    campo("Início de Vigência", detalhe.dt_inicio_vigencia),
                    campo("Término de Vigência", detalhe.dt_fim_vigencia),
                  ]}
                />

                <Secao
                  icon={Building2}
                  titulo="Proponente"
                  cols={2}
                  campos={[
                    campo("Proponente", detalhe.proponente),
                    campo("CNPJ", detalhe.identificacao),
                  ]}
                />

                {/* Objeto fica FORA de <Campos>: é texto livre, às vezes de vários
                    parágrafos, e a célula da grade trunca por desenho. */}
                <Secao icon={FileText} titulo="Objeto">
                  <p className="text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                    {detalhe.objeto || "-"}
                  </p>
                </Secao>

                {detalhe.detalhe && Object.keys(detalhe.detalhe).length > 0 && (
                  <Secao icon={Info} titulo="Justificativa e demais informações">
                    <dl className="flex flex-col gap-1.5">
                      {Object.entries(detalhe.detalhe)
                        .filter(([k]) => !k.startsWith("_") && !["Modalidade","Situação no SIAFI","Código do Instrumento","Número da Proposta","Número do Processo","Órgão","Objeto do Instrumento"].includes(k))
                        .map(([k, v]) => (
                          <div key={k} className="border-b pb-1.5 last:border-0 last:pb-0" style={{ borderColor: "var(--bi-line)" }}>
                            <dt className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>{k}</dt>
                            <dd className="mt-0.5 text-[12px] leading-snug break-words" style={{ color: "var(--bi-text)" }}>
                              {Array.isArray(v) ? v.join(" | ") : v}
                            </dd>
                          </div>
                        ))}
                    </dl>
                  </Secao>
                )}

                {Array.isArray(detalhe.detalhe?._documentos) && (detalhe.detalhe!._documentos as string[]).length > 0 && (
                  <Secao icon={Paperclip} titulo="Documentos Digitalizados" sub={`${(detalhe.detalhe!._documentos as string[]).length} documento(s)`}>
                    <ul className="flex flex-col gap-1">
                      {(detalhe.detalhe!._documentos as string[]).map((d, i) => {
                        const nome = d.replace(/\s*Baixar( Contrapartida)?\s*$/i, "").trim();
                        return (
                          <li key={i} className="flex items-start gap-2 text-[12px] leading-snug break-words" style={{ color: "var(--bi-text)" }}>
                            <Paperclip className="mt-0.5 size-3 shrink-0" style={{ color: "var(--bi-faint)" }} />
                            <span>{nome}</span>
                          </li>
                        );
                      })}
                    </ul>
                    <a href={PORTAL_BASE} target="_blank" rel="noreferrer noopener"
                       className="mt-3 inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-semibold"
                       style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}>
                      <ExternalLink className="size-3" /> Baixar no portal (Acesso Livre)
                    </a>
                    <p className="mt-1.5 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                      Os anexos do TransfereGov exigem sessão do portal. Clique acima, pesquise o município/proposta
                      e baixe os PDFs diretamente no Acesso Livre.
                    </p>
                  </Secao>
                )}
              </>)}

              {/* OPs/OBs — Execução Concedente → Listagem de Repasses */}
              {ativa === "opsobs" && detalhe.ops_obs && (
                <Secao
                  icon={Banknote}
                  titulo="OPs/OBs — Repasses e Desembolsos"
                  campos={[
                    { rotulo: "Valor Total de Repasse", valor: moeda(detalhe.ops_obs.valor_total_repasse) },
                    { rotulo: "Valor Desembolsado", valor: moeda(detalhe.ops_obs.valor_desembolsado), tom: "ok" },
                    { rotulo: "Valor a Desembolsar", valor: moeda(detalhe.ops_obs.valor_a_desembolsar), tom: "atencao" },
                    campo("Último Desembolso", detalhe.ops_obs.data_ultimo_desembolso),
                  ]}
                >
                  {(detalhe.ops_obs.obs || []).length > 0 && (
                    <div className="mt-3">
                      <div className="mb-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                        Ordens Bancárias (GERCOMP) · {(detalhe.ops_obs.obs || []).length}
                      </div>
                      <Grade
                        rolagem
                        cols={COLS_OB}
                        cabecalho={[
                          { label: "Nº NS" }, { label: "Nº OP" }, { label: "Nº OB" },
                          { label: "Valor", direita: true }, { label: "Situação" },
                          { label: "Emissão OB", direita: true },
                        ]}
                      >
                        {(detalhe.ops_obs.obs || []).map((o, i) => (
                          <GradeLinha key={i} cols={COLS_OB}>
                            <GradeCel tom="id" title={o.numero_ns || undefined}>{o.numero_ns || "-"}</GradeCel>
                            <GradeCel tom="id" title={o.numero_op || undefined}>{o.numero_op || "-"}</GradeCel>
                            <GradeCel tom="id" title={o.numero_ob || undefined}>{o.numero_ob || "-"}</GradeCel>
                            <GradeCel tom="num">{moeda(o.valor)}</GradeCel>
                            <GradeCel>
                              {o.situacao ? <Selo tom={situacaoTom(o.situacao)}>{o.situacao}</Selo> : "-"}
                            </GradeCel>
                            <GradeCel tom="data">{o.data_emissao_ob || "-"}</GradeCel>
                          </GradeLinha>
                        ))}
                      </Grade>
                    </div>
                  )}
                </Secao>
              )}

              {/* OBRAS — Acompanhamento de Obras (medição) */}
              {ativa === "obras" && detalhe.obras && (detalhe.obras.lotes || []).length > 0 && (
                <Secao
                  icon={HardHat}
                  titulo="Acompanhamento de Obras"
                  sub={`${(detalhe.obras.lotes || []).length} lote(s)`}
                  cols={2}
                  campos={[
                    { rotulo: "Valor total das submetas", valor: moeda(detalhe.obras.valor_total_submetas) },
                    ...(detalhe.obras.situacao_paralisacao
                      ? [campo("Paralisação", detalhe.obras.situacao_paralisacao, { tom: "atencao", quebra: true })]
                      : []),
                  ]}
                >
                  <div className="mt-3 flex flex-col gap-2">
                    {(detalhe.obras.lotes || []).map((lote, li) => (
                      <div key={li} className="bi-card-flat p-3">
                        <div className="mb-2 flex flex-wrap items-center gap-2">
                          <Selo tom="acento">{lote.tipo === "C" ? "CTEF" : "Lote"} {lote.numero}</Selo>
                          {lote.dias_sem_medicao != null && (
                            <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                              {lote.dias_sem_medicao} dias sem medição
                            </span>
                          )}
                          {lote.paralisado && <Selo tom="critico">Paralisado</Selo>}
                        </div>
                        <Grade
                          rolagem
                          cols={COLS_SUBMETA}
                          cabecalho={[
                            { label: "Submeta" }, { label: "Descrição" },
                            { label: "Valor", direita: true }, { label: "Situação" }, { label: "Regime" },
                          ]}
                        >
                          {(lote.submetas || []).map((s, si) => (
                            <GradeLinha key={si} cols={COLS_SUBMETA}>
                              <GradeCel tom="id">{s.numero || "-"}</GradeCel>
                              <GradeCel title={s.descricao || undefined}>{s.descricao || "-"}</GradeCel>
                              <GradeCel tom="num">{moeda(s.valor)}</GradeCel>
                              <GradeCel>
                                {s.situacao ? <Selo tom={situacaoTom(s.situacao)}>{s.situacao}</Selo> : "-"}
                              </GradeCel>
                              <GradeCel>{s.regime_execucao || "-"}</GradeCel>
                            </GradeLinha>
                          ))}
                        </Grade>
                        {lote.contrato && (
                          <div className="mt-3 rounded-lg p-2.5" style={{ background: "var(--bi-surface-2)" }}>
                            <div className="mb-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                              Contrato {lote.contrato.numero} — Detalhar
                            </div>
                            <Campos
                              cols={2}
                              campos={[
                                campo("Empresa", lote.contrato.empresa),
                                campo("CNPJ", lote.contrato.cnpj),
                                { rotulo: "Valor", valor: moeda(lote.contrato.valor) },
                                { rotulo: "Vigência", valor: `${lote.contrato.dt_inicio_vigencia || "?"} a ${lote.contrato.dt_fim_vigencia || "?"}` },
                              ]}
                            />
                            {lote.contrato.objeto && (
                              <div className="mt-2">
                                <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Objeto</div>
                                <p className="mt-0.5 text-[11px] leading-snug break-words" style={{ color: "var(--bi-text)" }}>
                                  {lote.contrato.objeto}
                                </p>
                              </div>
                            )}
                            <div className="mt-2.5 mb-1 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>ART/RRT</div>
                            {(lote.arts || []).length > 0 ? (
                              <Grade
                                rolagem
                                cols={COLS_ART}
                                cabecalho={[
                                  { label: "Tipo" }, { label: "ART/RRT" },
                                  { label: "Emissão", direita: true }, { label: "Responsável Técnico" },
                                ]}
                              >
                                {(lote.arts || []).map((a, ai) => {
                                  /* `tipo` e `responsavel_tecnico` chegam como
                                     OBJETO da API de obras — `{codigo, descricao}`
                                     e `{id, cpf, nome, ...}` — e não como texto.
                                     Era o que derrubava a aba inteira. */
                                  const tipo = textoDe(a.tipo);
                                  const resp = textoDe(a.responsavel_tecnico);
                                  return (
                                  <GradeLinha key={ai} cols={COLS_ART}>
                                    <GradeCel>{tipo || "-"}</GradeCel>
                                    <GradeCel tom="id">{a.numero || "-"}</GradeCel>
                                    <GradeCel tom="data">{a.dt_emissao || "-"}</GradeCel>
                                    <GradeCel title={resp || undefined}>{resp || "-"}</GradeCel>
                                  </GradeLinha>
                                  );
                                })}
                              </Grade>
                            ) : (
                              <div className="text-[11px] italic" style={{ color: "var(--bi-faint)" }}>Nenhum item incluído</div>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </Secao>
              )}

              {/* Histórico de Comunicações (TransfereGov mandatárias) — SITUAÇÃO e
                  CONSIDERAÇÕES em destaque: é o andamento real da análise. */}
              {ativa === "historico" && detalhe.historico_comunicacoes && detalhe.historico_comunicacoes.length > 0 && (
                <Secao
                  icon={MessagesSquare}
                  titulo="Histórico de Comunicações"
                  sub={`${detalhe.historico_comunicacoes.length} registro(s)`}
                >
                  <div className="mt-1 flex flex-col gap-1.5">
                    {detalhe.historico_comunicacoes.map((h, i) => {
                      const pick = (re: RegExp) => {
                        const k = Object.keys(h).find((kk) => re.test(kk));
                        return k ? (h[k] || "") : "";
                      };
                      const data = pick(/data|hora/i);
                      const evento = pick(/evento/i);
                      const resp = pick(/respons/i);
                      const sit = pick(/situa/i);
                      const cons = pick(/considera/i);
                      return (
                        <div key={i} className="bi-card-flat p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="bi-num text-[10px]" style={{ color: "var(--bi-faint)" }}>{data}</span>
                            <span className="text-[12px] font-medium" style={{ color: "var(--bi-text)" }}>{evento}</span>
                            {sit && <span className="ml-auto"><Selo tom={situacaoTom(sit)}>{sit}</Selo></span>}
                          </div>
                          {resp && <div className="mt-0.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>{resp}</div>}
                          {cons && (
                            <div className="mt-2 rounded-lg p-2" style={{ background: "color-mix(in oklab, var(--bi-warn) 10%, transparent)" }}>
                              <div className="text-[9px] font-semibold uppercase tracking-wide" style={{ color: "var(--bi-warn-ink)" }}>
                                Considerações
                              </div>
                              <p className="mt-0.5 text-[11px] leading-snug break-words" style={{ color: "var(--bi-text)" }}>{cons}</p>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </Secao>
              )}

              {/* Documentos do Quadro Resumo (Termos de Notificação etc.) */}
              {ativa === "docs" && detalhe.documentos_quadro_resumo && detalhe.documentos_quadro_resumo.length > 0 && (
                <Secao
                  icon={Paperclip}
                  titulo="Documentos / Termos de Notificação"
                  sub={`${detalhe.documentos_quadro_resumo.length} registro(s)`}
                >
                  <div className="mt-1 flex flex-col gap-1.5">
                    {detalhe.documentos_quadro_resumo.map((d, i) => {
                      const vals = Object.entries(d).filter(([, v]) => v && !/^\s*$/.test(v));
                      return (
                        <div key={i} className="bi-card-flat p-3">
                          <Campos cols={1} campos={vals.map(([k, v]) => campo(k, v, { quebra: true }))} />
                        </div>
                      );
                    })}
                  </div>
                </Secao>
              )}

              </div>
            </ModalCorpo>
          ) : null}
        </Modal>
        );
      })()}
    </div>
  );
}

