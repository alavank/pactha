"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import {
  Search, Eye, Loader2, Eraser, RefreshCw, ChevronDown, ChevronRight,
  ClipboardList, Building2, Landmark, FileText, Banknote, TrendingUp,
  Target, History, Wallet, Receipt, Undo2, CalendarRange, MessageSquareText, Users,
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
  // Dados bancários da emenda Pix (do plano de ação, via TransfereGov)
  banco?: string;
  agencia?: string;
  conta?: string;
  situacao_dado_bancario?: string;
  /* Marcadores da ÁRVORE DO PLANO (API oficial, 14/09/2026). Todos `null`
     quando `detalhe_coletado` é false — "não medido", nunca "zero". */
  detalhe_coletado?: boolean;
  saldo_conta?: number | null;
  saldo_conta_em?: string | null;
  valor_devolvido?: number | null;
  fim_execucao?: string | null;
  analise_pendente?: string | null;
}

interface BuscarResp {
  items: Plano[];
  total: number;
  municipio: { id: number; nome: string; uf: string };
  cache_age_seconds: number;
}

/* ⭐ O DETALHE VEM INTEIRO DO BANCO desde 14/09/2026, e com as CHAVES DA API
   OFICIAL (snake_case), exatamente como a fonte manda — nenhuma tradução no
   meio. Até aqui ele vinha AO VIVO da API interna da SPA (camelCase), três
   requisições por clique contra a fonte cuja quota por IP já bloqueou a VPS.

   ⚠️ OS NOMES SÃO OS DA RESPOSTA, NÃO OS DO OPENAPI. Em pelo menos dois
   recursos eles divergem (`tx_identificacao_recebedor_MASCARADO_...`,
   `tx_cpf_responsavel_MASCARADO_devolucao`), e ler o nome do openapi dá
   `undefined` sem erro nenhum — a coluna sai vazia calada. Conferido contra a
   captura real em backend/tests/fixtures/te_especiais_arvore.json.

   Tudo opcional e quase tudo `unknown`-tolerante via `textoDe`: é dado de
   portal federal, e campo que some ou muda de tipo não pode derrubar o modal. */
type Num = number | null;
type Txt = string | null;

/** `planos-acao-especiais` — o registro do plano, gravado em `raw_data`. */
interface PlanoOficial {
  id_plano_acao?: number;
  codigo_plano_acao?: Txt;
  ano_plano_acao?: Num;
  modalidade_plano_acao?: Txt;
  situacao_plano_acao?: Txt;
  email_camara?: Txt;
  data_aceite_plano_acao?: Txt;
  codigo_banco_plano_acao?: Txt;
  nome_banco_plano_acao?: Txt;
  numero_agencia_plano_acao?: Txt;
  dv_agencia_plano_acao?: Txt;
  numero_conta_plano_acao?: Txt;
  dv_conta_plano_acao?: Txt;
  descricao_situacao_dado_bancario_plano_acao?: Txt;
  nome_parlamentar_emenda_plano_acao?: Txt;
  ano_emenda_parlamentar_plano_acao?: Num;
  codigo_parlamentar_emenda_plano_acao?: Num;
  numero_emenda_parlamentar_plano_acao?: Num;
  codigo_emenda_parlamentar_formatado_plano_acao?: Txt;
  motivo_impedimento_plano_acao?: Txt;
  valor_custeio_plano_acao?: Num;
  valor_investimento_plano_acao?: Num;
  nome_objeto?: Txt;
  detalhamento_objeto?: Txt;
  categoria_despesa_plano_acao?: Txt;
  codigo_descricao_areas_politicas_publicas_plano_acao?: Txt;
  descricao_programacao_orcamentaria_plano_acao?: Txt;
  _beneficiario?: { nome_beneficiario?: Txt; cnpj_beneficiario?: Txt; uf_beneficiario?: Txt };
  _situacao_plano_trabalho?: Txt;
}

interface AnalisePT {
  id_plano_trabalho_analise_pt?: number;
  nome_orgao_analise_pt?: Txt;
  situacao_parecer_analise_pt?: Txt;
  texto_parecer_analise_pt?: Txt;
  situacao_analise_pt?: Txt;
  data_analise_pt?: Txt;
  valor_reprovado_pt?: Num;
  historico?: { nome_orgao_analise_pt_hist?: Txt; situacao_parecer_analise_pt_hist?: Txt;
                situacao_analise_pt_hist?: Txt; data_analise_pt_hist?: Txt }[];
}

interface PlanoTrabalho {
  id_plano_trabalho?: number;
  situacao_plano_trabalho?: Txt;
  dt_hora_situacao_plano_trabalho?: Txt;
  ind_orcamento_proprio_plano_trabalho?: Txt;
  data_inicio_execucao_plano_trabalho?: Txt;
  data_fim_execucao_plano_trabalho?: Txt;
  prazo_execucao_meses_plano_trabalho?: Num;
  classificacao_orcamentaria_pt?: Txt;
  ind_justificativa_prorrogacao_atraso_pt?: Txt;
  ind_justificativa_prorrogacao_paralizacao_pt?: Txt;
  justificativa_prorrogacao_paralizacao_pt?: Txt;
  dt_hora_pt_aprovado?: Txt;
  ind_orgao_analises_pendentes?: Txt;
  analises?: AnalisePT[];
  historico?: { data_plano_trabalho_hist?: Txt; cpf_responsavel_plano_trabalho_hist?: Txt;
                situacao_plano_trabalho_hist?: Txt }[];
  orgaos_pendentes?: { nome_orgao_analise_pendente_pt?: Txt }[];
}

interface Meta {
  id_meta?: number;
  nome_meta?: Txt;
  desc_meta?: Txt;
  un_medida_meta?: Txt;
  qt_unidade_meta?: Num;
  vl_custeio_emenda_especial_meta?: Num;
  vl_investimento_emenda_especial_meta?: Num;
  vl_custeio_recursos_proprios_meta?: Num;
  vl_investimento_recursos_proprios_meta?: Num;
  vl_custeio_rendimento_meta?: Num;
  vl_investimento_rendimento_meta?: Num;
  vl_custeio_doacao_meta?: Num;
  vl_investimento_doacao_meta?: Num;
  qt_meses_meta?: Num;
}

interface Executor {
  id_executor?: number;
  cnpj_executor?: Txt;
  nome_executor?: Txt;
  objeto_executor?: Txt;
  vl_custeio_executor?: Num;
  vl_investimento_executor?: Num;
  ind_recursos_gerenciados_conta_especifica_executor?: Txt;
  nome_banco_executor?: Txt;
  numero_agencia_executor?: Txt;
  numero_dv_agencia_executor?: Txt;
  numero_conta_executor?: Txt;
  numero_dv_conta_executor?: Txt;
  descricao_situacao_dado_bancario_executor?: Txt;
  metas?: Meta[];
  finalidades?: { area_politica_publica_tipo_pt?: Txt; area_politica_publica_pt?: Txt }[];
}

interface Empenho {
  id_empenho?: number;
  numero_empenho?: Txt;
  descricao_situacao_empenho?: Txt;
  descricao_tipo_documento_empenho?: Txt;
  categoria_despesa_empenho?: Txt;
  natureza_despesa_empenho?: Num;
  fonte_recurso_empenho?: Txt;
  data_emissao_empenho?: Txt;
  valor_empenho?: Num;
}

interface Subtransacao {
  data_pagamento_subtransacao_gestao_financeira?: Txt;
  valor_subtransacao_gestao_financeira?: Num;
  numero_documento_beneficiario_subtransacao_gestao_financeira?: Txt;
  nome_beneficiario_subtransacao_gestao_financeira?: Txt;
  descricao_subtransacao_gestao_financeira?: Txt;
}

interface Lancamento {
  id_lancamento_gestao_financeira?: Txt;
  data_lancamento_gestao_financeira?: Txt;
  tipo_operacao_gestao_financeira?: Txt;   // "C" | "D"
  descricao_gestao_financeira?: Txt;
  valor_gestao_financeira?: Num;
  doc_favorecido_gestao_financeira?: Txt;
  nome_favorecido_gestao_financeira?: Txt;
  doc_depositante_gestao_financeira?: Txt;
  nome_depositante_gestao_financeira?: Txt;
  subtransacoes?: Subtransacao[];
}

interface Devolucao {
  id_devolucao?: number;
  dt_solicitacao_devolucao?: Txt;
  dt_pagamento_devolucao?: Txt;
  situacao_devolucao?: Txt;
  tx_metodo_devolucao?: Txt;
  tipo_devolucao?: Txt;
  ds_motivo_devolucao?: Txt;
  tx_justificativa_devolucao?: Txt;
  vl_devolucao?: Num;
  vl_multa_devolucao?: Num;
  vl_juros_devolucao?: Num;
  vl_total_devolucao?: Num;
}

interface DocLiquidacao {
  id_relatorio_gestao_dl?: number;
  tx_descricao_relatorio_gestao_dl?: Txt;
  tp_doc_recebedor_relatorio_gestao_dl?: Txt;
  tx_identificacao_recebedor_mascarado_relatorio_gestao_dl?: Txt;
  tx_nome_recebedor_relatorio_gestao_dl?: Txt;
  vl_pagamento_relatorio_gestao_dl?: Num;
  dt_pagamento_relatorio_gestao_dl?: Txt;
  tx_natureza_relatorio_gestao_dl?: Txt;
}

interface RelatorioNovo {
  id_relatorio_gestao_novo?: number;
  data_relatorio_gestao_novo?: Txt;
  tipo_relatorio_gestao_novo?: Txt;
  situacao_relatorio_gestao_novo?: Txt;
  valor_executado_relatorio_gestao_novo?: Num;
  valor_pendente_relatorio_gestao_novo?: Num;
  documentos_liquidacao?: DocLiquidacao[];
  analises?: { tx_orgao_nome_relatorio_gestao_analise?: Txt; st_parecer_relatorio_gestao_analise?: Txt;
               st_analise_relatorio_gestao_analise?: Txt; tx_parecer_relatorio_gestao_analise?: Txt;
               dt_analise_relatorio_gestao_analise?: Txt }[];
}

interface RelatorioAntigo {
  id_relatorio_gestao?: number;
  data_relatorio_gestao?: Txt;
  tipo_relatorio_gestao?: Txt;
  situacao_relatorio_gestao?: Txt;
  valor_executado_relatorio_gestao?: Num;
  valor_pendente_relatorio_gestao?: Num;
  descritivo_relatorio_gestao?: Txt;
}

interface Programa {
  codigo_programa?: Txt;
  ano_programa?: Num;
  nome_orgao_superior_programa?: Txt;
  sigla_orgao_superior_programa?: Txt;
  nome_orgao_programa?: Txt;
  data_inicio_ciencia_programa?: Txt;
  data_fim_ciencia_programa?: Txt;
  valor_total_disponibilizado_programa?: Num;
  valor_impedido_programa?: Num;
  valor_a_disponibilizar_programa?: Num;
  valor_documentos_habeis_gerados_programa?: Num;
  valor_obs_geradas_programa?: Num;
  valor_disponibilidade_atual_programa?: Num;
}

/** A árvore do plano (`transferegov_te.detalhe`), montada pelo coletor
 *  (`ingestion/transferegov_te.arvore_do_plano`). */
interface ArvorePlano {
  programa?: Programa | null;
  planos_trabalho?: PlanoTrabalho[];
  executores?: Executor[];
  empenhos?: Empenho[];
  conta?: {
    id_agencia_conta?: Txt;
    saldo?: { saldo_final_gestao_financeira?: Num; data_saldo_conta?: Txt } | null;
    lancamentos?: Lancamento[];
  };
  relatorios_gestao?: RelatorioAntigo[];
  relatorios_gestao_novos?: RelatorioNovo[];
  devolucoes?: Devolucao[];
  historico?: { data_hora_historico_plano_acao?: Txt; situacao_historico_plano_acao?: Txt;
                operacao_historico_plano_acao?: Txt; descricao_historico_plano_acao?: Txt }[];
}

interface DetalhePlano {
  plano?: PlanoOficial | null;
  /* `null` = o coletor ainda não passou por este plano (ele passa toda noite)
     — NÃO é o mesmo que "o plano não tem nada", e a tela diz a diferença. */
  detalhe?: ArvorePlano | null;
  /* PAGAMENTOS: coluna `transferegov_te.pagamentos` — o MESMO JSON que o RM
     congela. `null` = ainda não coletado, que não é "não há pagamento". */
  pagamentos?: PagamentosTE | null;
  detalhe_atualizado_em?: string | null;
  /** Quando a PRÓPRIA fonte se atualizou (`/data-atualizacao`), que é outra
   *  coisa que a hora da nossa coleta. */
  fonte_atualizada_em?: string | null;
}

/** '2026-06-23' ou '2026-06-23T08:19:19' -> '23/06/2026'. Texto que não é
 *  data ISO volta como veio (a fonte é federal; o formato pode mudar). */
function dataBr(s: unknown): string {
  const t = textoDe(s);
  if (!t) return "-";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(t);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : t;
}

/** Idem, com hora quando houver: '23/06/2026 08:19'. */
function dataHoraBr(s: unknown): string {
  const t = textoDe(s);
  if (!t) return "-";
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(t);
  if (!m) return t;
  return `${m[3]}/${m[2]}/${m[1]}${m[4] ? ` ${m[4]}:${m[5]}` : ""}`;
}

/** Número + dígito verificador de agência/conta: '2127' + '0' -> '2127-0'. */
function comDv(num: unknown, dv: unknown): string {
  const n = textoDe(num);
  const d = textoDe(dv);
  if (!n) return "-";
  return d ? `${n}-${d}` : n;
}

const soma = (...v: (number | null | undefined)[]) => v.reduce<number>((s, x) => s + (x || 0), 0);

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
// As grades da árvore do plano (API oficial, 14/09/2026). Mesma regra: literal.
const COLS_META = "grid-cols-[4.5rem_minmax(12rem,1fr)_6rem_7rem_7rem_7rem_7rem_3.5rem]";
const COLS_HPT = "grid-cols-[8.5rem_minmax(10rem,1fr)_8rem]";
const COLS_EMP = "grid-cols-[8rem_6rem_minmax(7rem,1fr)_6.5rem_5.5rem_7rem_7.5rem]";
const COLS_EXT = "grid-cols-[6rem_2.5rem_minmax(7rem,0.8fr)_minmax(10rem,1.4fr)_8.5rem_7.5rem]";
const COLS_DEV = "grid-cols-[6rem_6rem_7rem_minmax(8rem,1fr)_6.5rem_4rem_7.5rem]";
const COLS_DL = "grid-cols-[6rem_minmax(10rem,1.4fr)_8.5rem_5.5rem_minmax(8rem,1fr)_7.5rem]";
const COLS_RGA = "grid-cols-[minmax(7rem,0.6fr)_5rem_6rem_7.5rem_7.5rem_minmax(8rem,1fr)]";
const COLS_HPA = "grid-cols-[8.5rem_minmax(8rem,1fr)_6.5rem_minmax(8rem,1fr)]";

type AbaDetalhe =
  | "basicos" | "trabalho" | "orcamento" | "pagamentos" | "conta" | "gestao" | "historico";

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
  const [tab, setTab] = useState<AbaDetalhe>("basicos");
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
                    {/* Os dois SINAIS de que algo não anda, vindos da árvore do
                        plano (API oficial): dinheiro que VOLTOU e análise
                        parada num órgão. Selo só quando existem — ausência
                        não disputa atenção com nada. */}
                    {!!p.valor_devolvido && (
                      <Selo tom="atencao" title="Soma das devoluções registradas para este plano">
                        Devolução {formatCurrency(p.valor_devolvido)}
                      </Selo>
                    )}
                    {p.analise_pendente && (
                      <Selo tom="atencao" title={`Órgão com análise pendente: ${p.analise_pendente}`}>
                        Análise pendente: {p.analise_pendente}
                      </Selo>
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
                    // Dados bancários da emenda Pix (plano de ação, TransfereGov).
                    // "—" quando o plano ainda não tem domicílio bancário definido.
                    { rotulo: "Banco", valor: p.banco || "—", title: p.banco },
                    { rotulo: "Agência", valor: p.agencia || "—" },
                    {
                      rotulo: "Conta",
                      valor: p.conta || "—",
                      title: p.situacao_dado_bancario
                        ? `Conta ${p.conta || "—"} · ${p.situacao_dado_bancario}`
                        : p.conta,
                    },
                    {
                      rotulo: "Motivo de impedimento",
                      valor: p.motivo_impedimento || "—",
                      // Critico so quando ha motivo: sem impedimento o campo e
                      // um traco cinza e nao disputa atencao com nada.
                      tom: p.motivo_impedimento ? "critico" : "normal",
                      title: p.motivo_impedimento,
                    },
                    /* Da ÁRVORE DO PLANO. "—" quando o coletor ainda não passou
                       pelo plano, e o title diz isso — um "—" mudo seria lido
                       como "conta zerada". */
                    {
                      rotulo: "Saldo em conta",
                      valor: p.saldo_conta != null ? formatCurrency(p.saldo_conta) : "—",
                      title: p.saldo_conta != null
                        ? `Saldo da conta específica em ${dataBr(p.saldo_conta_em)}`
                        : p.detalhe_coletado ? "Saldo não informado pela fonte"
                        : "Ainda não coletado (o coletor passa toda noite)",
                    },
                    {
                      rotulo: "Fim da execução",
                      valor: p.fim_execucao ? dataBr(p.fim_execucao) : "—",
                      title: p.fim_execucao
                        ? `Fim da execução no plano de trabalho: ${dataBr(p.fim_execucao)}`
                        : undefined,
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

      {/* Modal Detalhe — INTEIRO DO BANCO desde 14/09/2026 (API oficial via
          coletor). As abas novas — Plano de Trabalho, Conta, Relatório de
          Gestão e Histórico — mostram o que a API oficial publica e o PACTHA
          não coletava: vigência, pareceres, extrato com favorecido, QUEM
          RECEBEU o dinheiro do município, devoluções. */}
      {(detalhe !== null || loadingDetalhe) && (() => {
        const pl = detalhe?.plano ?? null;
        const arv = detalhe?.detalhe ?? null;
        const pg = detalhe?.pagamentos ?? null;
        const ben = pl?._beneficiario;
        const codigoAno = pl ? `${pl.codigo_plano_acao || "-"} / ${pl.ano_plano_acao ?? "-"}` : undefined;
        const naoColetado = (
          <Vazio>
            A árvore deste plano ainda não foi coletada. O coletor passa por todos os planos
            toda noite — tente de novo amanhã.
          </Vazio>
        );
        return (
        <Modal aberto onFechar={() => setDetalhe(null)} maxW="max-w-5xl">
          <ModalHead
            titulo="Dados do Plano de Ação"
            sub={codigoAno}
            onFechar={() => setDetalhe(null)}
            abaixo={
              pl ? (
                <Abas
                  valor={tab}
                  onChange={(v) => setTab(v)}
                  opcoes={[
                    { valor: "basicos" as const, label: "Dados Básicos" },
                    { valor: "trabalho" as const, label: "Plano de Trabalho" },
                    { valor: "orcamento" as const, label: "Dados Orçamentários" },
                    { valor: "pagamentos" as const, label: "Pagamentos" },
                    { valor: "conta" as const, label: "Conta e Extrato" },
                    { valor: "gestao" as const, label: "Relatório de Gestão" },
                    { valor: "historico" as const, label: "Histórico" },
                  ]}
                />
              ) : undefined
            }
          />
          {loadingDetalhe ? (
            <div className="py-16 text-center">
              <Loader2 className="mx-auto size-8 animate-spin" style={{ color: "var(--bi-faint)" }} />
            </div>
          ) : pl ? (
            <ModalCorpo className="flex flex-col gap-3">
              {/* De onde e de quando é o dado — duas datas diferentes, e as duas
                  importam: quando a FONTE se atualizou e quando nós coletamos. */}
              <div className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Fonte: API oficial do TransfereGov
                {detalhe?.fonte_atualizada_em && <> · fonte atualizada em {dataBr(detalhe.fonte_atualizada_em)}</>}
                {detalhe?.detalhe_atualizado_em && <> · coletado em {dataHoraBr(detalhe.detalhe_atualizado_em)}</>}
              </div>
              <Secao
                icon={ClipboardList}
                titulo="Identificação"
                cols={3}
                campos={[
                  campoP("Plano de Ação", codigoAno),
                  campoP("Programa", arv?.programa?.codigo_programa
                    ? `${arv.programa.codigo_programa} — ${arv.programa.nome_orgao_programa || arv.programa.nome_orgao_superior_programa || ""}`
                    : pl.codigo_plano_acao?.split("-").slice(0, -1).join("-")),
                  campoP("Situação", pl.situacao_plano_acao),
                  campoP(
                    "Beneficiário",
                    `${ben?.cnpj_beneficiario || "-"} - ${ben?.nome_beneficiario || "-"} (${ben?.uf_beneficiario || "-"})`,
                    { span: 2 },
                  ),
                  campoP("Emenda Parlamentar", pl.codigo_emenda_parlamentar_formatado_plano_acao),
                ]}
              />

              <div key={tab} className="bi-pane-enter flex flex-col gap-3">
              {tab === "basicos" && (
                <>
                  <Secao
                    icon={Landmark}
                    titulo="Dados da Emenda Parlamentar"
                    campos={[
                      campoP("Emenda Parlamentar", pl.codigo_emenda_parlamentar_formatado_plano_acao),
                      campoP("Parlamentar", pl.nome_parlamentar_emenda_plano_acao, { span: 2 }),
                      campoP("Código Parlamentar", pl.codigo_parlamentar_emenda_plano_acao),
                      campoP("Ano da Emenda", pl.ano_emenda_parlamentar_plano_acao),
                      campoP("Nº da Emenda", pl.numero_emenda_parlamentar_plano_acao),
                      { rotulo: "Valor de Custeio", valor: formatCurrency(pl.valor_custeio_plano_acao) },
                      { rotulo: "Valor de Investimento", valor: formatCurrency(pl.valor_investimento_plano_acao) },
                    ]}
                  />
                  <Secao icon={FileText} titulo="Dados Complementares do Plano">
                    <Campos
                      cols={4}
                      campos={[
                        campoP("Modalidade", pl.modalidade_plano_acao),
                        campoP("Categoria da Despesa", pl.categoria_despesa_plano_acao),
                        campoP("Aceite do Plano", dataBr(pl.data_aceite_plano_acao)),
                        campoP("E-mail Câmara", pl.email_camara),
                      ]}
                    />
                    {/* Texto livre sai da grade: às vezes são vários parágrafos, e
                        a célula trunca por desenho. */}
                    {([
                      ["Objeto", [pl.nome_objeto, pl.detalhamento_objeto].filter(Boolean).join(" — ")],
                      ["Áreas de Políticas Públicas", pl.codigo_descricao_areas_politicas_publicas_plano_acao],
                      ["Programação Orçamentária", pl.descricao_programacao_orcamentaria_plano_acao],
                      ["Motivo do Impedimento", pl.motivo_impedimento_plano_acao],
                    ] as const).map(([rot, txt]) => (
                      <div key={rot} className="mt-2.5">
                        <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>{rot}</div>
                        <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                          {textoDe(txt) || "-"}
                        </p>
                      </div>
                    ))}
                  </Secao>
                  <Secao
                    icon={Building2}
                    titulo="Dados Bancários do Plano"
                    campos={[
                      campoP("Banco", pl.nome_banco_plano_acao || pl.codigo_banco_plano_acao),
                      campoP("Agência", comDv(pl.numero_agencia_plano_acao, pl.dv_agencia_plano_acao)),
                      campoP("Conta", comDv(pl.numero_conta_plano_acao, pl.dv_conta_plano_acao)),
                      campoP("Situação da Conta", pl.descricao_situacao_dado_bancario_plano_acao),
                    ]}
                  />
                  {/* EXECUTORES: quem executa o recurso — quase sempre o próprio
                      município, às vezes um fundo municipal com CNPJ e conta
                      próprios. As finalidades (área/subárea) moram nele. */}
                  {!arv ? naoColetado : (arv.executores || []).map((ex, i) => (
                    <Secao
                      key={ex.id_executor ?? i}
                      icon={Users}
                      titulo={`Executor — ${ex.nome_executor || "-"}`}
                      campos={[
                        campoP("CNPJ", ex.cnpj_executor, { mono: true }),
                        { rotulo: "Custeio", valor: formatCurrency(ex.vl_custeio_executor) },
                        { rotulo: "Investimento", valor: formatCurrency(ex.vl_investimento_executor) },
                        campoP("Conta Específica", ex.ind_recursos_gerenciados_conta_especifica_executor),
                        campoP("Banco", ex.nome_banco_executor),
                        campoP("Agência", comDv(ex.numero_agencia_executor, ex.numero_dv_agencia_executor)),
                        campoP("Conta", comDv(ex.numero_conta_executor, ex.numero_dv_conta_executor)),
                        campoP("Situação da Conta", ex.descricao_situacao_dado_bancario_executor),
                        campoP("Objeto", ex.objeto_executor, { span: 4, quebra: true }),
                        campoP("Finalidades",
                          (ex.finalidades || [])
                            .map((f) => [f.area_politica_publica_tipo_pt, f.area_politica_publica_pt].filter(Boolean).join(" › "))
                            .join(" · ") || "-",
                          { span: 4, quebra: true }),
                      ]}
                    />
                  ))}
                </>
              )}

              {tab === "trabalho" && (
                !arv ? naoColetado
                : !(arv.planos_trabalho || []).length ? (
                  <Vazio>Este plano de ação ainda não tem plano de trabalho na fonte.</Vazio>
                ) : (
                  <>
                    {(arv.planos_trabalho || []).map((pt, i) => (
                      <React.Fragment key={pt.id_plano_trabalho ?? i}>
                        <Secao
                          icon={CalendarRange}
                          titulo="Plano de Trabalho"
                          sub={pt.id_plano_trabalho ? `nº ${pt.id_plano_trabalho}` : undefined}
                          campos={[
                            { rotulo: "Situação", valor: textoDe(pt.situacao_plano_trabalho) || "-",
                              tom: situacaoTom(pt.situacao_plano_trabalho) },
                            campoP("Situação desde", dataHoraBr(pt.dt_hora_situacao_plano_trabalho)),
                            campoP("Início da Execução", dataBr(pt.data_inicio_execucao_plano_trabalho)),
                            campoP("Fim da Execução", dataBr(pt.data_fim_execucao_plano_trabalho)),
                            campoP("Prazo (meses)", pt.prazo_execucao_meses_plano_trabalho),
                            campoP("Aprovado em", dataHoraBr(pt.dt_hora_pt_aprovado)),
                            campoP("Orçamento Próprio", pt.ind_orcamento_proprio_plano_trabalho),
                            { rotulo: "Análise Pendente", valor: textoDe(pt.ind_orgao_analises_pendentes) || "-",
                              tom: /^sim/i.test(pt.ind_orgao_analises_pendentes || "") ? "atencao" : "normal" },
                            campoP("Prorrogação por Atraso", pt.ind_justificativa_prorrogacao_atraso_pt),
                            campoP("Prorrogação por Paralisação", pt.ind_justificativa_prorrogacao_paralizacao_pt),
                            campoP("Justificativa da Prorrogação", pt.justificativa_prorrogacao_paralizacao_pt,
                              { span: 2, quebra: true }),
                          ]}
                        >
                          {!!(pt.orgaos_pendentes || []).length && (
                            <div className="mt-2 text-[12px]" style={{ color: "var(--bi-warn-ink)" }}>
                              Órgão(s) com análise pendente:{" "}
                              {(pt.orgaos_pendentes || []).map((o) => o.nome_orgao_analise_pendente_pt).filter(Boolean).join("; ")}
                            </div>
                          )}
                          {pt.classificacao_orcamentaria_pt && (
                            <div className="mt-2.5">
                              <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                                Classificação Orçamentária (declarada pelo município)
                              </div>
                              <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                                {pt.classificacao_orcamentaria_pt}
                              </p>
                            </div>
                          )}
                        </Secao>

                        {/* PARECERES: o que cada ministério disse do plano, com o
                            TEXTO — responde "por que isso não anda" sem telefonar. */}
                        <Secao icon={MessageSquareText} titulo="Pareceres dos Ministérios"
                               sub={`${(pt.analises || []).length} análise(s)`}>
                          {!(pt.analises || []).length ? (
                            <Vazio>Nenhuma análise registrada para este plano de trabalho.</Vazio>
                          ) : (
                            <div className="mt-2 flex flex-col gap-2.5">
                              {(pt.analises || []).map((a, j) => (
                                <div key={a.id_plano_trabalho_analise_pt ?? j} className="border-t pt-2"
                                     style={{ borderColor: "var(--bi-line)" }}>
                                  <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                                    <span className="font-medium" style={{ color: "var(--bi-text)" }}>
                                      {a.nome_orgao_analise_pt || "-"}
                                    </span>
                                    {a.situacao_parecer_analise_pt && (
                                      <Selo tom={situacaoTom(a.situacao_parecer_analise_pt)}>{a.situacao_parecer_analise_pt}</Selo>
                                    )}
                                    {a.situacao_analise_pt && (
                                      <Selo tom={situacaoTom(a.situacao_analise_pt)}>{a.situacao_analise_pt}</Selo>
                                    )}
                                    <span className="bi-num text-[11px]" style={{ color: "var(--bi-faint)" }}>
                                      {dataHoraBr(a.data_analise_pt)}
                                    </span>
                                    {!!a.valor_reprovado_pt && (
                                      <Selo tom="critico">Reprovado {formatCurrency(a.valor_reprovado_pt)}</Selo>
                                    )}
                                  </div>
                                  {a.texto_parecer_analise_pt && (
                                    <p className="mt-1 text-[12px] leading-relaxed break-words whitespace-pre-line"
                                       style={{ color: "var(--bi-muted)" }}>
                                      {a.texto_parecer_analise_pt}
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </Secao>

                        <Secao icon={History} titulo="Histórico do Plano de Trabalho"
                               sub={`${(pt.historico || []).length} evento(s)`}>
                          {!(pt.historico || []).length ? (
                            <Vazio>Sem eventos registrados.</Vazio>
                          ) : (
                            <div className="mt-2">
                              <Grade rolagem cols={COLS_HPT}
                                     cabecalho={[{ label: "Data" }, { label: "Situação" }, { label: "Responsável" }]}>
                                {[...(pt.historico || [])]
                                  .sort((x, y) => String(y.data_plano_trabalho_hist || "").localeCompare(String(x.data_plano_trabalho_hist || "")))
                                  .map((h, j) => (
                                    <GradeLinha key={j} cols={COLS_HPT}>
                                      <GradeCel tom="data">{dataHoraBr(h.data_plano_trabalho_hist)}</GradeCel>
                                      <GradeCel>{h.situacao_plano_trabalho_hist || "-"}</GradeCel>
                                      <GradeCel tom="id">{h.cpf_responsavel_plano_trabalho_hist || "-"}</GradeCel>
                                    </GradeLinha>
                                  ))}
                              </Grade>
                            </div>
                          )}
                        </Secao>
                      </React.Fragment>
                    ))}

                    {/* METAS: o que o município se comprometeu a entregar, por
                        executor, com a origem do dinheiro de cada uma (emenda,
                        rendimento da conta, recurso próprio). */}
                    {(arv.executores || []).map((ex, i) => (
                      <Secao key={ex.id_executor ?? i} icon={Target}
                             titulo={`Metas — ${ex.nome_executor || "Executor"}`}
                             sub={`${(ex.metas || []).length} meta(s)`}>
                        {!(ex.metas || []).length ? (
                          <Vazio>Nenhuma meta cadastrada.</Vazio>
                        ) : (
                          <div className="mt-2">
                            <Grade rolagem minLargura="52rem" cols={COLS_META}
                                   cabecalho={[
                                     { label: "Meta" }, { label: "Descrição" }, { label: "Qtd." },
                                     { label: "Emenda custeio", direita: true },
                                     { label: "Emenda invest.", direita: true },
                                     { label: "Rendimentos", direita: true },
                                     { label: "Próprios/doação", direita: true },
                                     { label: "Meses", direita: true },
                                   ]}>
                              {[...(ex.metas || [])]
                                .sort((x, y) => String(x.nome_meta || "").localeCompare(String(y.nome_meta || "")))
                                .map((m, j) => (
                                  <GradeLinha key={m.id_meta ?? j} cols={COLS_META}>
                                    <GradeCel tom="id">{m.nome_meta || "-"}</GradeCel>
                                    <GradeCel>{m.desc_meta || "-"}</GradeCel>
                                    <GradeCel tom="num">{`${m.qt_unidade_meta ?? "-"} ${m.un_medida_meta || ""}`.trim()}</GradeCel>
                                    <GradeCel tom="num">{formatCurrency(m.vl_custeio_emenda_especial_meta)}</GradeCel>
                                    <GradeCel tom="num">{formatCurrency(m.vl_investimento_emenda_especial_meta)}</GradeCel>
                                    <GradeCel tom="num">{formatCurrency(soma(m.vl_custeio_rendimento_meta, m.vl_investimento_rendimento_meta))}</GradeCel>
                                    <GradeCel tom="num">{formatCurrency(soma(m.vl_custeio_recursos_proprios_meta, m.vl_investimento_recursos_proprios_meta,
                                                                           m.vl_custeio_doacao_meta, m.vl_investimento_doacao_meta))}</GradeCel>
                                    <GradeCel tom="num">{m.qt_meses_meta ?? "-"}</GradeCel>
                                  </GradeLinha>
                                ))}
                            </Grade>
                          </div>
                        )}
                      </Secao>
                    ))}
                  </>
                )
              )}

              {tab === "orcamento" && (
                <>
                  <Secao
                    icon={Banknote}
                    titulo="Orçamento do Plano"
                    cols={3}
                    campos={[
                      { rotulo: "Valor de Custeio", valor: formatCurrency(pl.valor_custeio_plano_acao) },
                      { rotulo: "Valor de Investimento", valor: formatCurrency(pl.valor_investimento_plano_acao) },
                      { rotulo: "Valor Total", valor: formatCurrency(soma(pl.valor_custeio_plano_acao, pl.valor_investimento_plano_acao)) },
                    ]}
                  />
                  {!arv ? naoColetado : (
                    <>
                      <Secao icon={Receipt} titulo="Empenhos" sub={`${(arv.empenhos || []).length} empenho(s)`}>
                        {!(arv.empenhos || []).length ? (
                          <Vazio>Nenhum empenho emitido para este plano.</Vazio>
                        ) : (
                          <div className="mt-2">
                            <Grade rolagem minLargura="46rem" cols={COLS_EMP}
                                   cabecalho={[
                                     { label: "Empenho" }, { label: "Emissão" }, { label: "Situação" },
                                     { label: "Categoria" }, { label: "Natureza" }, { label: "Fonte" },
                                     { label: "Valor", direita: true },
                                   ]}>
                              {(arv.empenhos || []).map((e, j) => (
                                <GradeLinha key={e.id_empenho ?? j} cols={COLS_EMP}>
                                  <GradeCel tom="id">{e.numero_empenho || "-"}</GradeCel>
                                  <GradeCel tom="data">{dataBr(e.data_emissao_empenho)}</GradeCel>
                                  <GradeCel>
                                    {e.descricao_situacao_empenho
                                      ? <Selo tom={situacaoTom(e.descricao_situacao_empenho)}>{e.descricao_situacao_empenho}</Selo>
                                      : "-"}
                                  </GradeCel>
                                  <GradeCel>{e.categoria_despesa_empenho || "-"}</GradeCel>
                                  <GradeCel tom="id">{e.natureza_despesa_empenho ?? "-"}</GradeCel>
                                  <GradeCel tom="id">{e.fonte_recurso_empenho || "-"}</GradeCel>
                                  <GradeCel tom="num">{formatCurrency(e.valor_empenho)}</GradeCel>
                                </GradeLinha>
                              ))}
                            </Grade>
                          </div>
                        )}
                      </Secao>
                      {arv.programa && (
                        /* O PROGRAMA orçamentário da emenda, visto de cima: quanto
                           o governo disponibilizou nele no Brasil inteiro e quanto
                           já virou OB. Contexto, não dado do município. */
                        <Secao
                          icon={Landmark}
                          titulo={`Programa ${arv.programa.codigo_programa || ""} — visão nacional`}
                          sub={[arv.programa.sigla_orgao_superior_programa, arv.programa.nome_orgao_programa].filter(Boolean).join(" · ")}
                          campos={[
                            campoP("Ano", arv.programa.ano_programa),
                            campoP("Ciência de", dataBr(arv.programa.data_inicio_ciencia_programa)),
                            campoP("Ciência até", dataBr(arv.programa.data_fim_ciencia_programa)),
                            { rotulo: "Disponibilizado", valor: formatCurrency(arv.programa.valor_total_disponibilizado_programa) },
                            { rotulo: "Impedido", valor: formatCurrency(arv.programa.valor_impedido_programa) },
                            { rotulo: "A Disponibilizar", valor: formatCurrency(arv.programa.valor_a_disponibilizar_programa) },
                            { rotulo: "DHs Gerados", valor: formatCurrency(arv.programa.valor_documentos_habeis_gerados_programa) },
                            { rotulo: "OBs Geradas", valor: formatCurrency(arv.programa.valor_obs_geradas_programa) },
                          ]}
                        />
                      )}
                    </>
                  )}
                </>
              )}

              {tab === "pagamentos" && (
                !pg ? (
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
                      { rotulo: "Valor Total", valor: formatCurrency(pg.valor_total) },
                      { rotulo: "Desembolsado", valor: formatCurrency(pg.valor_desembolsado), tom: "ok" },
                      { rotulo: "A Desembolsar", valor: formatCurrency(pg.valor_a_desembolsar),
                        tom: pg.pago_integral ? "ok" : "atencao" },
                      campoP("Último Desembolso", pg.data_ultimo_desembolso),
                    ]}
                  >
                    {(() => {
                      const linhas = [
                        ...(pg?.obs || []),
                        ...(pg?.pendentes || []),
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

              {tab === "conta" && (
                !arv ? naoColetado : (() => {
                  const conta = arv.conta || {};
                  const lancs = [...(conta.lancamentos || [])].sort((x, y) =>
                    String(y.data_lancamento_gestao_financeira || "").localeCompare(String(x.data_lancamento_gestao_financeira || "")));
                  const devs = arv.devolucoes || [];
                  const creditos = soma(...lancs.filter((l) => l.tipo_operacao_gestao_financeira === "C").map((l) => l.valor_gestao_financeira));
                  const debitos = soma(...lancs.filter((l) => l.tipo_operacao_gestao_financeira === "D").map((l) => l.valor_gestao_financeira));
                  return (
                    <>
                      <Secao
                        icon={Wallet}
                        titulo="Conta Específica da Emenda"
                        sub={conta.id_agencia_conta ? `agência-conta ${conta.id_agencia_conta}` : "sem conta informada"}
                        campos={[
                          { rotulo: "Saldo Final", valor: conta.saldo ? formatCurrency(conta.saldo.saldo_final_gestao_financeira) : "-",
                            title: "Saldo final informado pela fonte na data ao lado" },
                          campoP("Data do Saldo", dataBr(conta.saldo?.data_saldo_conta)),
                          { rotulo: "Créditos no Extrato", valor: formatCurrency(creditos) },
                          { rotulo: "Débitos no Extrato", valor: formatCurrency(debitos) },
                        ]}
                      />
                      {/* O EXTRATO com o FAVORECIDO de cada débito: para onde o
                          dinheiro da emenda foi, pela conta. Crédito mostra quem
                          depositou (o Tesouro); débito, quem recebeu. */}
                      <Secao icon={Banknote} titulo="Extrato da Conta" sub={`${lancs.length} lançamento(s)`}>
                        {!lancs.length ? (
                          <Vazio>Nenhum lançamento publicado para esta conta.</Vazio>
                        ) : (
                          <div className="mt-2">
                            <Grade rolagem minLargura="46rem" cols={COLS_EXT}
                                   cabecalho={[
                                     { label: "Data" }, { label: "C/D" }, { label: "Descrição" },
                                     { label: "Favorecido / Depositante" }, { label: "Documento" },
                                     { label: "Valor", direita: true },
                                   ]}>
                              {lancs.map((l, j) => {
                                const debito = l.tipo_operacao_gestao_financeira === "D";
                                const nome = debito ? l.nome_favorecido_gestao_financeira : l.nome_depositante_gestao_financeira;
                                const doc = debito ? l.doc_favorecido_gestao_financeira : l.doc_depositante_gestao_financeira;
                                return (
                                  <React.Fragment key={l.id_lancamento_gestao_financeira ?? j}>
                                    <GradeLinha cols={COLS_EXT}>
                                      <GradeCel tom="data">{dataBr(l.data_lancamento_gestao_financeira)}</GradeCel>
                                      <GradeCel tom="id">{l.tipo_operacao_gestao_financeira || "-"}</GradeCel>
                                      <GradeCel>{l.descricao_gestao_financeira || "-"}</GradeCel>
                                      <GradeCel>{nome || "-"}</GradeCel>
                                      <GradeCel tom="id">{doc || "-"}</GradeCel>
                                      <GradeCel tom="num">{`${debito ? "− " : ""}${formatCurrency(l.valor_gestao_financeira)}`}</GradeCel>
                                    </GradeLinha>
                                    {(l.subtransacoes || []).map((s, k) => (
                                      <GradeLinha key={`s${k}`} cols={COLS_EXT}>
                                        <GradeCel tom="data">{dataBr(s.data_pagamento_subtransacao_gestao_financeira)}</GradeCel>
                                        <GradeCel tom="id">↳</GradeCel>
                                        <GradeCel>{s.descricao_subtransacao_gestao_financeira || "-"}</GradeCel>
                                        <GradeCel>{s.nome_beneficiario_subtransacao_gestao_financeira || "-"}</GradeCel>
                                        <GradeCel tom="id">{s.numero_documento_beneficiario_subtransacao_gestao_financeira || "-"}</GradeCel>
                                        <GradeCel tom="num">{formatCurrency(s.valor_subtransacao_gestao_financeira)}</GradeCel>
                                      </GradeLinha>
                                    ))}
                                  </React.Fragment>
                                );
                              })}
                            </Grade>
                          </div>
                        )}
                      </Secao>
                      {/* DEVOLUÇÃO: o recurso que voltou para a União. É sinal de
                          que algo deu errado — e até aqui era invisível. */}
                      <Secao icon={Undo2} titulo="Devoluções" sub={`${devs.length} devolução(ões)`}>
                        {!devs.length ? (
                          <Vazio>Nenhuma devolução registrada para este plano.</Vazio>
                        ) : (
                          <div className="mt-2">
                            <Grade rolagem minLargura="46rem" cols={COLS_DEV}
                                   cabecalho={[
                                     { label: "Solicitação" }, { label: "Pagamento" }, { label: "Tipo" },
                                     { label: "Motivo" }, { label: "Situação" }, { label: "Método" },
                                     { label: "Total", direita: true },
                                   ]}>
                              {devs.map((d, j) => (
                                <GradeLinha key={d.id_devolucao ?? j} cols={COLS_DEV}>
                                  <GradeCel tom="data">{dataBr(d.dt_solicitacao_devolucao)}</GradeCel>
                                  <GradeCel tom="data">{dataBr(d.dt_pagamento_devolucao)}</GradeCel>
                                  <GradeCel>{d.tipo_devolucao || "-"}</GradeCel>
                                  <GradeCel title={d.tx_justificativa_devolucao || undefined}>
                                    {[d.ds_motivo_devolucao, d.tx_justificativa_devolucao].filter(Boolean).join(" — ") || "-"}
                                  </GradeCel>
                                  <GradeCel>{d.situacao_devolucao || "-"}</GradeCel>
                                  <GradeCel tom="id">{d.tx_metodo_devolucao || "-"}</GradeCel>
                                  <GradeCel tom="num"
                                            title={`Valor ${formatCurrency(d.vl_devolucao)} · multa ${formatCurrency(d.vl_multa_devolucao)} · juros ${formatCurrency(d.vl_juros_devolucao)}`}>
                                    {formatCurrency(d.vl_total_devolucao)}
                                  </GradeCel>
                                </GradeLinha>
                              ))}
                            </Grade>
                          </div>
                        )}
                      </Secao>
                    </>
                  );
                })()
              )}

              {tab === "gestao" && (
                !arv ? naoColetado
                : !(arv.relatorios_gestao_novos || []).length && !(arv.relatorios_gestao || []).length ? (
                  <Vazio>Sem relatório de gestão registrado para este plano.</Vazio>
                ) : (
                  <>
                    {(arv.relatorios_gestao_novos || []).map((r, i) => {
                      const dls = [...(r.documentos_liquidacao || [])].sort((x, y) =>
                        String(y.dt_pagamento_relatorio_gestao_dl || "").localeCompare(String(x.dt_pagamento_relatorio_gestao_dl || "")));
                      return (
                        <Secao
                          key={r.id_relatorio_gestao_novo ?? i}
                          icon={TrendingUp}
                          titulo={`Relatório de Gestão ${r.tipo_relatorio_gestao_novo || ""}`.trim()}
                          sub={dataBr(r.data_relatorio_gestao_novo)}
                          campos={[
                            { rotulo: "Situação", valor: textoDe(r.situacao_relatorio_gestao_novo) || "-",
                              tom: situacaoTom(r.situacao_relatorio_gestao_novo) },
                            { rotulo: "Executado", valor: formatCurrency(r.valor_executado_relatorio_gestao_novo), tom: "ok" },
                            { rotulo: "Pendente", valor: formatCurrency(r.valor_pendente_relatorio_gestao_novo),
                              tom: r.valor_pendente_relatorio_gestao_novo ? "atencao" : "normal" },
                            { rotulo: "Pago a Terceiros", valor: formatCurrency(soma(...dls.map((d) => d.vl_pagamento_relatorio_gestao_dl))) },
                          ]}
                        >
                          {/* ⭐ QUEM RECEBEU O DINHEIRO DO MUNICÍPIO — a pergunta que
                              o TCU e a imprensa fazem sobre emenda Pix, e que o
                              PACTHA não respondia. */}
                          <div className="mt-3 mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                            <Receipt className="size-3.5" /> Quem recebeu — Documentos de Liquidação · {dls.length}
                          </div>
                          {!dls.length ? (
                            <Vazio>Nenhum documento de liquidação neste relatório.</Vazio>
                          ) : (
                            <Grade rolagem minLargura="46rem" cols={COLS_DL}
                                   cabecalho={[
                                     { label: "Pagamento" }, { label: "Recebedor" }, { label: "Documento" },
                                     { label: "Natureza" }, { label: "Descrição" }, { label: "Valor", direita: true },
                                   ]}>
                              {dls.map((d, j) => (
                                <GradeLinha key={d.id_relatorio_gestao_dl ?? j} cols={COLS_DL}>
                                  <GradeCel tom="data">{dataBr(d.dt_pagamento_relatorio_gestao_dl)}</GradeCel>
                                  <GradeCel>{d.tx_nome_recebedor_relatorio_gestao_dl || "-"}</GradeCel>
                                  <GradeCel tom="id" title={d.tp_doc_recebedor_relatorio_gestao_dl || undefined}>
                                    {d.tx_identificacao_recebedor_mascarado_relatorio_gestao_dl || "-"}
                                  </GradeCel>
                                  <GradeCel>{d.tx_natureza_relatorio_gestao_dl || "-"}</GradeCel>
                                  <GradeCel>{d.tx_descricao_relatorio_gestao_dl || "-"}</GradeCel>
                                  <GradeCel tom="num">{formatCurrency(d.vl_pagamento_relatorio_gestao_dl)}</GradeCel>
                                </GradeLinha>
                              ))}
                            </Grade>
                          )}
                          {!!(r.analises || []).length && (
                            <div className="mt-3 flex flex-col gap-2">
                              <div className="text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                                Análise do relatório · {(r.analises || []).length}
                              </div>
                              {(r.analises || []).map((a, j) => (
                                <div key={j} className="text-[12px]">
                                  <div className="flex flex-wrap items-center gap-1.5">
                                    <span className="font-medium">{a.tx_orgao_nome_relatorio_gestao_analise || "-"}</span>
                                    {a.st_parecer_relatorio_gestao_analise && (
                                      <Selo tom={situacaoTom(a.st_parecer_relatorio_gestao_analise)}>{a.st_parecer_relatorio_gestao_analise}</Selo>
                                    )}
                                    <span className="bi-num text-[11px]" style={{ color: "var(--bi-faint)" }}>
                                      {dataHoraBr(a.dt_analise_relatorio_gestao_analise)}
                                    </span>
                                  </div>
                                  {a.tx_parecer_relatorio_gestao_analise && (
                                    <p className="mt-0.5 leading-relaxed break-words" style={{ color: "var(--bi-muted)" }}>
                                      {a.tx_parecer_relatorio_gestao_analise}
                                    </p>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </Secao>
                      );
                    })}
                    {!!(arv.relatorios_gestao || []).length && (
                      <Secao icon={FileText} titulo="Relatórios de Gestão (modelo anterior)"
                             sub={`${(arv.relatorios_gestao || []).length} relatório(s)`}>
                        <div className="mt-2">
                          <Grade rolagem minLargura="46rem" cols={COLS_RGA}
                                 cabecalho={[
                                   { label: "Situação" }, { label: "Tipo" }, { label: "Data" },
                                   { label: "Executado", direita: true }, { label: "Pendente", direita: true },
                                   { label: "Descritivo" },
                                 ]}>
                            {(arv.relatorios_gestao || []).map((r, j) => (
                              <GradeLinha key={r.id_relatorio_gestao ?? j} cols={COLS_RGA}>
                                <GradeCel>{(r.situacao_relatorio_gestao || "-").replace(/_/g, " ")}</GradeCel>
                                <GradeCel>{r.tipo_relatorio_gestao || "-"}</GradeCel>
                                <GradeCel tom="data">{dataBr(r.data_relatorio_gestao)}</GradeCel>
                                <GradeCel tom="num">{formatCurrency(r.valor_executado_relatorio_gestao)}</GradeCel>
                                <GradeCel tom="num">{formatCurrency(r.valor_pendente_relatorio_gestao)}</GradeCel>
                                <GradeCel>{r.descritivo_relatorio_gestao || "-"}</GradeCel>
                              </GradeLinha>
                            ))}
                          </Grade>
                        </div>
                      </Secao>
                    )}
                  </>
                )
              )}

              {tab === "historico" && (
                !arv ? naoColetado
                : !(arv.historico || []).length ? (
                  <Vazio>Sem eventos registrados para este plano de ação.</Vazio>
                ) : (
                  <Secao icon={History} titulo="Histórico do Plano de Ação" sub={`${(arv.historico || []).length} evento(s)`}>
                    <div className="mt-2">
                      <Grade rolagem cols={COLS_HPA}
                             cabecalho={[{ label: "Data" }, { label: "Situação" }, { label: "Operação" }, { label: "Descrição" }]}>
                        {[...(arv.historico || [])]
                          .sort((x, y) => String(y.data_hora_historico_plano_acao || "").localeCompare(String(x.data_hora_historico_plano_acao || "")))
                          .map((h, j) => (
                            <GradeLinha key={j} cols={COLS_HPA}>
                              <GradeCel tom="data">{dataHoraBr(h.data_hora_historico_plano_acao)}</GradeCel>
                              <GradeCel>{(h.situacao_historico_plano_acao || "-").replace(/_/g, " ")}</GradeCel>
                              <GradeCel tom="id">{h.operacao_historico_plano_acao || "-"}</GradeCel>
                              <GradeCel>{h.descricao_historico_plano_acao || "-"}</GradeCel>
                            </GradeLinha>
                          ))}
                      </Grade>
                    </div>
                  </Secao>
                )
              )}
              </div>
            </ModalCorpo>
          ) : !loadingDetalhe && detalhe ? (
            <ModalCorpo>
              <Vazio>Não foi possível carregar este plano de ação.</Vazio>
            </ModalCorpo>
          ) : null}
        </Modal>
        );
      })()}
    </div>
  );
}

