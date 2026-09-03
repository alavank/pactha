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
import { PainelFiltros, type FiltroAtivo } from "@/components/ui/filtros";

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
// ⚠️ De 5 para 7 trilhas: entraram Realizado e %. Escrita LITERAL, como avisa o
// comentário do topo — classe de grid montada dinamicamente vira grade SEM
// colunas, porque o Tailwind só gera o que aparece no código-fonte.
const COLS_SUBMETA = "grid-cols-[5rem_minmax(10rem,1fr)_7.5rem_7.5rem_4.5rem_9rem_7rem]";
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
/** Percentual de execução da obra — DERIVADO, não buscado.
 *
 *  O portal mostra esse número no "Resumo Físico-Financeiro", mas os dois valores
 *  que o compõem já vêm no JSONB de obras. Derivar aqui evita um GET por
 *  instrumento num host de 2 vCPU. Confere com o caso real:
 *  344.827,46 / 368.000,00 = 93,70%.
 *
 *  Traço quando não dá para dividir — nunca "0%", que seria afirmar execução
 *  zerada quando na verdade não se sabe o total. */
function pctExec(total?: number | null, realizado?: number | null): string {
  if (!total || total <= 0 || realizado == null) return "—";
  return `${(realizado * 100 / total).toFixed(2).replace(".", ",")}%`;
}

/** Número da proposta do Novo PAC que originou este instrumento, ou "".
 *
 *  O portal registra isso na aba Dados ("Número da Proposta Novo PAC - Seleção").
 *  É o elo que permite ao relatório parar de mostrar o mesmo recurso duas vezes
 *  — uma como voluntária, outra como item do PAC. Aqui a informação é promovida
 *  a campo próprio: ela já aparecia no despejo genérico do detalhe, solta no meio
 *  de dezenas de pares, e ninguém a via.
 *
 *  Busca TOLERANTE (contém "novo pac", sem acento): o rótulo tem acento, hífen e
 *  espaços, e casar a string inteira seria apostar na grafia. */
function pacOrigem(det?: Record<string, string | string[]>): string {
  if (!det) return "";
  const norm = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  for (const [k, v] of Object.entries(det)) {
    if (k.startsWith("_")) continue;
    if (norm(k).includes("novo pac")) {
      const val = String(Array.isArray(v) ? v[0] : v ?? "").trim();
      if (val) return val;
    }
  }
  return "";
}

/** "Sim" ou "" para o campo Empenhado do modal — NUNCA "Não".
 *
 *  ⚠️ NÃO é o `detalhe->>'Empenhado'` cru. Aquele flag do portal erra nos dois
 *  sentidos (marcava "Aprovada" como empenhada, e o 994997 aparecia "Não" aqui
 *  com "Sim" no TransfereGov) e ficava solto no despejo genérico do detalhe,
 *  contradizendo — na MESMA tela — a caixa de Notas de Empenho logo acima.
 *
 *  Ordem de prova: NE REAL coletada > calado. A MINUTA não conta: vem sem
 *  número, com R$ 1,00 e situação "Minuta de Empenho".
 *
 *  Por que nunca "Não": ausência de NE não prova ausência de empenho — tenant
 *  com TG_NES desligado nunca consulta, e "consultei e não tem" fica igual a
 *  "nunca consultei". Mesma doutrina do RM (rm_builder._empenhado_rotulo). */
function empenhadoDe(det?: Detalhe | null): string {
  const nes = det?.notas_empenho;
  if (Array.isArray(nes) && nes.some((n) => !n.minuta_apenas && (n.numero || "").trim())) {
    return "Sim";
  }
  return "";
}

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
  /** Situação do Projeto Básico/TR vinda do CSV PÚBLICO ("Em Análise",
   *  "Aprovado", …). É o caminho que funciona com a sessão gov.br fria: o
   *  `projeto_basico` acima exige o SP `execucao` quente e por isso vem nulo na
   *  prática. Chega no `siconv_proposta.zip` desde 31/08 e estava preenchida em
   *  2.799 de 3.200 propostas do Freitas sem que nenhuma tela a lesse. */
  situacao_projeto_basico?: string | null;
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
  /** Abas de Dados Gerais do contrato (tela de medição). */
  responsaveis?: Array<{
    cpf?: string | null; nome?: string | null; atividade?: string | null;
    tipo?: string | null; crea_cau?: string | null; dt_inclusao?: string | null;
  }>;
  documentos?: Array<{
    nome?: string | null; tipo?: string | null; dt_inclusao?: string | null;
  }>;
  medicoes_total?: number | null;
  medicoes_atestadas?: number | null;
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

/** A FONTE, no card (pedido do dono, 28/08/2026). O grupo do menu passou a se
 *  chamar FEDERAIS — é a esfera, não o sistema —, então quem diz de onde veio
 *  cada proposta é o card. Quando entrar outra fonte federal, o valor aqui vira
 *  campo do registro; hoje tudo desta tela sai do TransfereGov. */
const FONTE = "TransfereGov";

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
  /* Semente vinda da tela do PAC: "qual convênio nasceu desta seleção" leva para
     cá já com o número da proposta no filtro. É por isso que o campo `proposta`
     do filtro e o link do PAC são a mesma peça. */
  const propostaParam = sp.get("proposta");

  const [items, setItems] = useState<Proposta[]>([]);
  const [atualizadoEm, setAtualizadoEm] = useState<string | undefined>();
  const [loading, setLoading] = useState(false);
  /* QUATRO CAMPOS, e não uma caixa. A caixa única era um OR de três colunas — e
     a coluna do número do CONVÊNIO (`codigo_instrumento`), que é o número que
     esta tela mostra em destaque, nem entrava nele. */
  const [instrumento, setInstrumento] = useState("");
  const [proposta, setProposta] = useState(propostaParam || "");
  const [proponente, setProponente] = useState("");
  const [cnpj, setCnpj] = useState("");
  /* Disparo EXPLÍCITO da busca. Antes o "Limpar" fazia `setTimeout(buscar, 100)`,
     e aquele `buscar` era o do render ANTERIOR — fechado sobre os filtros que
     acabavam de ser apagados. Ele corria com a busca limpa que o efeito já tinha
     disparado e, por sair 100ms depois, normalmente respondia por último: clicar
     em Limpar deixava a lista FILTRADA. */
  const [disparo, setDisparo] = useState(0);
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
    if (instrumento.trim()) params.instrumento = instrumento.trim();
    if (proposta.trim()) params.proposta = proposta.trim();
    if (proponente.trim()) params.proponente = proponente.trim();
    if (cnpj.trim()) params.cnpj = cnpj.trim();
    if (vigenciaSel.length) params.vigencia = vigenciaSel;
    if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
    if (orgao.trim()) params.orgao = orgao.trim();
    if (sitContratacaoSel.length) params.situacao_contratacao = sitContratacaoSel;
    if (vigFimDe) params.vig_fim_de = vigFimDe;
    if (vigFimAte) params.vig_fim_ate = vigFimAte;
    return params;
  }, [municipioId, categoria, instrumento, proposta, proponente, cnpj, vigenciaSel,
      parlamentar, orgao, sitContratacaoSel, vigFimDe, vigFimAte]);

  /** Limpa TUDO e refaz a busca UMA vez.
   *
   *  Substitui o `setTimeout(buscar, 100)` de antes, que reenviava os filtros
   *  velhos. Aqui as limpezas e o `setDisparo` entram no MESMO lote de estado:
   *  um render, um efeito, uma requisição — com os campos já vazios.
   *  Zera também `anosSel`, que o Limpar antigo esquecia (filtro client-side
   *  continuava aplicado depois de "limpar"). */
  const limparTudo = useCallback(() => {
    setInstrumento(""); setProposta(""); setProponente(""); setCnpj("");
    setSituacoesSel([]); setVigenciaSel([]); setAnosSel([]);
    setParlamentar(""); setOrgao(""); setSitContratacaoSel([]);
    setVigFimDe(""); setVigFimAte("");
    setDisparo((d) => d + 1);
  }, []);

  /** O que está filtrando AGORA, para o cabeçalho do painel recolhido.
   *
   *  Filtro escondido é filtro que mente: com o painel fechado, estes chips são
   *  a única coisa que explica por que a lista tem 3 itens e não 180. Os que vão
   *  ao servidor precisam de `setDisparo` ao serem removidos; ano e situação são
   *  client-side e aplicam sozinhos. */
  const filtrosAtivos = useMemo<FiltroAtivo[]>(() => {
    const a: FiltroAtivo[] = [];
    const servidor = (chave: string, rotulo: string, limpar: () => void) =>
      a.push({ chave, rotulo, remover: () => { limpar(); setDisparo((d) => d + 1); } });
    if (instrumento.trim()) servidor("instrumento", `Instrumento: ${instrumento.trim()}`, () => setInstrumento(""));
    if (proposta.trim()) servidor("proposta", `Proposta: ${proposta.trim()}`, () => setProposta(""));
    if (proponente.trim()) servidor("proponente", `Proponente: ${proponente.trim()}`, () => setProponente(""));
    if (cnpj.trim()) servidor("cnpj", `CNPJ: ${cnpj.trim()}`, () => setCnpj(""));
    if (parlamentar.trim()) servidor("parlamentar", `Parlamentar: ${parlamentar.trim()}`, () => setParlamentar(""));
    if (orgao.trim()) servidor("orgao", `Órgão: ${orgao.trim()}`, () => setOrgao(""));
    if (vigFimDe) servidor("vigde", `Fim de vigência de ${vigFimDe}`, () => setVigFimDe(""));
    if (vigFimAte) servidor("vigate", `Fim de vigência até ${vigFimAte}`, () => setVigFimAte(""));
    sitContratacaoSel.forEach((s) =>
      servidor(`sc:${s}`, s, () => setSitContratacaoSel((x) => x.filter((y) => y !== s))));
    vigenciaSel.forEach((v) =>
      servidor(`vig:${v}`, VIGENCIA_LABELS[v] ?? v, () => setVigenciaSel((x) => x.filter((y) => y !== v))));
    situacoesSel.forEach((s) =>
      a.push({ chave: `sit:${s}`, rotulo: s, remover: () => setSituacoesSel((x) => x.filter((y) => y !== s)) }));
    anosSel.forEach((y) =>
      a.push({ chave: `ano:${y}`, rotulo: y, remover: () => setAnosSel((x) => x.filter((z) => z !== y)) }));
    return a;
  }, [instrumento, proposta, proponente, cnpj, parlamentar, orgao, vigFimDe, vigFimAte,
      sitContratacaoSel, vigenciaSel, situacoesSel, anosSel]);

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

  // Sincroniza o filtro de proposta com o parametro da URL (vem do selo de
  // convenio vinculado, na tela do PAC). Sem este efeito o link so funcionaria
  // na MONTAGEM: um segundo clique em outro convenio da MESMA categoria trocaria
  // a URL sem trocar o filtro, e a tela ficaria mostrando o convenio anterior.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProposta(propostaParam || "");
    setDisparo((d) => d + 1);
  }, [propostaParam]);

  // Busca ao montar, quando municipio/categoria/vigencia mudam e a cada disparo
  // EXPLICITO (Filtrar, Limpar, remover chip). `disparo` na lista de dependencias
  // e o que permite Limpar disparar UMA busca — com os campos ja vazios — em vez
  // do `setTimeout` que reenviava os filtros velhos.
  useEffect(() => { if (municipioId) buscar(); }, [municipioId, vigenciaSel, categoria, disparo]); // eslint-disable-line react-hooks/exhaustive-deps

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

      <PainelFiltros
        ativos={filtrosAtivos}
        aoLimparTudo={limparTudo}
        direita={
          /* Fica FORA do corpo recolhível: gerar PDF é ação sobre o RESULTADO,
             não sobre o filtro — sumir junto com o painel seria perder o botão. */
          <Button variant="outline" size="sm" onClick={gerarPdf} disabled={baixandoPdf}
                  title="Gera um PDF só com os instrumentos filtrados">
            {baixandoPdf ? <Loader2 className="size-4 animate-spin mr-1" /> : null} 📄 Gerar PDF (filtrado)
          </Button>
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div>
            {/* O número do CONVÊNIO. Era o único número da tela que a busca NÃO
                consultava, apesar de ser o que aparece na meta de cada item
                ("instr 981397") e no título do modal. */}
            <label className="text-xs text-base-content/70 mb-1 block">Instrumento (nº do convênio)</label>
            <Input value={instrumento} onChange={(e) => setInstrumento(e.target.value)}
                   placeholder="Ex: 981397" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Proposta (nº)</label>
            <Input value={proposta} onChange={(e) => setProposta(e.target.value)}
                   placeholder="Ex: 048291/2025" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Proponente</label>
            <Input value={proponente} onChange={(e) => setProponente(e.target.value)}
                   placeholder="Ex: Município de Araújos" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
          </div>
          <div>
            {/* Com ou sem máscara: o backend compara só os dígitos dos dois lados. */}
            <label className="text-xs text-base-content/70 mb-1 block">CNPJ</label>
            <Input value={cnpj} onChange={(e) => setCnpj(e.target.value)} inputMode="numeric"
                   placeholder="18.243.220/0001-01" onKeyDown={(e) => { if (e.key === "Enter") buscar(); }} />
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
            {/* `limparTudo` e não um onClick inline com setTimeout: ver o
                comentário da função — o inline reenviava os filtros ANTIGOS. */}
            <Button variant="outline" onClick={limparTudo}>
              <Eraser className="size-4 mr-1" /> Limpar
            </Button>
          </div>
        </div>
      </PainelFiltros>

      {/* Os chips de vigência que ficavam aqui SAÍRAM: o PainelFiltros já mostra
          TODOS os filtros ativos no cabeçalho, com o mesmo botão × por chip.
          Manter os dois faria o mesmo filtro aparecer duas vezes, com dois
          visuais e dois botões de remover — e duplicata de controle é pior que
          nenhum, porque o gestor não sabe qual dos dois manda. */}

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
                      /* Última coluna = canto inferior direito do card, abaixo
                         do olhinho e na linha dos dias restantes. */
                      { rotulo: "Fonte", valor: FONTE },
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
        // ⚠️ ZERO NÃO LIGA A ABA. O coletor grava 0.0 (não null) quando a
        // "Listagem de Repasses" existe e está zerada — e `!= null` acendia a aba
        // "OPs/OBs" em voluntária que nunca teve um centavo de desembolso,
        // mostrando três linhas de R$ 0,00. Só há o que ver quando há ordem
        // bancária ou algum valor diferente de zero. Corrige também os registros
        // zerados JÁ gravados, sem depender de limpeza no banco.
        const _oo = detalhe?.ops_obs;
        const temOpsObs = !!(_oo && (((_oo.valor_total_repasse ?? 0) > 0)
          || ((_oo.valor_desembolsado ?? 0) > 0)
          || ((_oo.valor_a_desembolsar ?? 0) > 0)
          || (_oo.obs || []).length));
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
                    // EMPENHADO — derivado da NE, não o flag cru do portal (ver
                    // empenhadoDe). Só sai quando há prova: sem NE a linha some,
                    // porque "não consultado" ≠ "não empenhado". Promovido do
                    // despejo genérico lá embaixo, onde ficava solto e
                    // contradizendo a caixa de Notas de Empenho.
                    ...(empenhadoDe(detalhe) ? [campo("Empenhado", empenhadoDe(detalhe))] : []),
                    // Só aparece quando o instrumento nasceu de uma seleção do
                    // Novo PAC — é a contrapartida de o item do PAC deixar de
                    // sair separado no relatório.
                    ...(pacOrigem(detalhe.detalhe)
                      ? [campo("Origem — Novo PAC", pacOrigem(detalhe.detalhe))]
                      : []),
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
                        {/* ⚠️ Fallback do CSV logo abaixo: quando a versão rica
                            não veio, ainda assim dizemos em que pé o TR está. */}
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
                    {/* TERMO DE REFERÊNCIA pelo CSV PÚBLICO — o caminho que
                        funciona com a sessão gov.br fria.
                        ⚠️ SÓ QUANDO A VERSÃO RICA NÃO VEIO. Se `projeto_basico`
                        chegou, ele já traz situação E documentos, e mostrar as
                        duas caixas faria o gestor ver o mesmo assunto duas vezes,
                        eventualmente com rótulos diferentes.
                        ⚠️ O RÓTULO DIZ DE ONDE VEIO. "Em Análise" sem contexto
                        parece a leitura da tela logada; dizendo "dado aberto", quem
                        precisa do detalhe (quais documentos, de que data) sabe que
                        tem de abrir o portal — e não conclui que o PACTHA está
                        escondendo. */}
                    {!detalhe.projeto_basico?.situacao && detalhe.situacao_projeto_basico && (
                      <Aviso
                        tom="atencao"
                        titulo={`Projeto Básico/Termo de Referência — ${detalhe.situacao_projeto_basico}`}
                      >
                        <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                          Situação publicada no dado aberto do TransfereGov. A lista de
                          documentos e as datas só existem na tela autenticada do portal.
                        </p>
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

                {/* "Empenhado" entra na lista de exclusão abaixo: o par cru do
                    portal é o flag furado, e mostrá-lo aqui contradizia, na mesma
                    tela, a caixa de Notas de Empenho e o campo "Empenhado"
                    derivado em Dados da Proposta (ver empenhadoDe). */}
                {detalhe.detalhe && Object.keys(detalhe.detalhe).length > 0 && (
                  <Secao icon={Info} titulo="Justificativa e demais informações">
                    <dl className="flex flex-col gap-1.5">
                      {Object.entries(detalhe.detalhe)
                        .filter(([k]) => !k.startsWith("_") && !["Modalidade","Situação no SIAFI","Código do Instrumento","Número da Proposta","Número do Processo","Órgão","Objeto do Instrumento","Empenhado"].includes(k))
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
                  /* RESUMO FÍSICO-FINANCEIRO — os três números que o portal
                     mostra no topo da tela de obras. Os dois primeiros já eram
                     coletados e NUNCA exibidos; o percentual é DERIVADO deles,
                     sem requisição nenhuma. */
                  campos={[
                    { rotulo: "Valor total", valor: moeda(detalhe.obras.valor_total_submetas) },
                    { rotulo: "Valor realizado", valor: moeda(detalhe.obras.valor_total_realizado) },
                    { rotulo: "Percentual de execução", valor: pctExec(
                        detalhe.obras.valor_total_submetas, detalhe.obras.valor_total_realizado) },
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
                          {/* MEDIÇÕES — o número que sustenta a frase do RM
                              ("com 02 medições atestadas"). Selo âmbar quando
                              NENHUMA foi atestada: é o sinal de obra que ainda
                              não começou a ser medida. */}
                          {lote.medicoes_total != null && (
                            <Selo tom={lote.medicoes_atestadas ? "ok" : "atencao"}>
                              {lote.medicoes_atestadas || 0} de {lote.medicoes_total} medição(ões) atestada(s)
                            </Selo>
                          )}
                          {/* Sem responsável técnico a obra NÃO PODE ser medida —
                              por isso é alerta, e não ausência silenciosa. */}
                          {(lote.responsaveis || []).length === 0 && (lote.arts || []).length === 0 && (
                            <Selo tom="critico">Sem responsável técnico / ART</Selo>
                          )}
                        </div>
                        <Grade
                          rolagem
                          cols={COLS_SUBMETA}
                          cabecalho={[
                            { label: "Submeta" }, { label: "Descrição" },
                            { label: "Valor", direita: true },
                            { label: "Realizado", direita: true },
                            { label: "%", direita: true },
                            { label: "Situação" }, { label: "Regime" },
                          ]}
                        >
                          {(lote.submetas || []).map((s, si) => (
                            <GradeLinha key={si} cols={COLS_SUBMETA}>
                              <GradeCel tom="id">{s.numero || "-"}</GradeCel>
                              <GradeCel title={s.descricao || undefined}>{s.descricao || "-"}</GradeCel>
                              <GradeCel tom="num">{moeda(s.valor)}</GradeCel>
                              {/* Realizado já vinha no JSONB (valorRealizadoAcumulado)
                                  e a grade simplesmente não o mostrava. */}
                              <GradeCel tom="num">{moeda(s.valor_realizado)}</GradeCel>
                              <GradeCel tom="num">{pctExec(s.valor, s.valor_realizado)}</GradeCel>
                              <GradeCel>
                                {s.situacao ? <Selo tom={situacaoTom(s.situacao)}>{s.situacao}</Selo> : "-"}
                              </GradeCel>
                              <GradeCel>{s.regime_execucao || "-"}</GradeCel>
                            </GradeLinha>
                          ))}
                        </Grade>
                        {/* RESPONSÁVEL TÉCNICO — a aba do portal, com os campos
                            que ela mostra. Vem de /responsavel/listar/{id}, que
                            foge do padrão /contratos/{id}/... dos vizinhos. */}
                        {(lote.responsaveis || []).length > 0 && (
                          <div className="mt-3">
                            <div className="mb-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                              Responsável Técnico
                            </div>
                            {(lote.responsaveis || []).map((rt, ri) => (
                              <Campos
                                key={ri}
                                cols={3}
                                campos={[
                                  campo("Nome", rt.nome), campo("CPF", rt.cpf),
                                  campo("Atividade", rt.atividade), campo("Tipo", rt.tipo),
                                  campo("CREA / CAU", rt.crea_cau),
                                  campo("Data de inclusão", rt.dt_inclusao),
                                ]}
                              />
                            ))}
                          </div>
                        )}
                        {(lote.documentos || []).length > 0 && (
                          <div className="mt-3">
                            <div className="mb-1.5 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                              Documentação Complementar
                            </div>
                            {(lote.documentos || []).map((d, di) => (
                              <Campos
                                key={di}
                                cols={3}
                                campos={[campo("Arquivo", d.nome), campo("Tipo", d.tipo),
                                         campo("Inclusão", d.dt_inclusao)]}
                              />
                            ))}
                          </div>
                        )}
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
                      /* ⚠️ O FILTRO TAMBÉM AQUI, e não só no coletor. A coluna
                         "Ações" da grade do portal é um botão do PrimeFaces, e o
                         `textContent` dela é o `onclick` inteiro — que estava
                         sendo gravado no JSONB e impresso campo a campo neste
                         modal, que é onde o gestor vem LER o parecer.

                         O coletor já não guarda mais isso, mas o JSONB de TODAS
                         as propostas já coletadas continua com o lixo até a
                         próxima passagem do lote (2 em 2h, e só as celebradas).
                         Sem este filtro a tela seguiria feia por dias.

                         A 2ª regra é a que aguenta: o nome da coluna pode mudar,
                         a assinatura do PrimeFaces no valor não engana. */
                      const vals = Object.entries(d).filter(
                        ([k, v]) => v && !/^\s*$/.test(v)
                          && !/^\s*a[çc][ãaõo](o|es)\s*$/i.test(k)
                          && !/PrimeFaces\.|CommandButton|widget_/.test(v),
                      );
                      if (!vals.length) return null;
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

