"use client";

/**
 * VOLUNTÁRIAS — a ÁRVORE da proposta pelos dumps de Discricionárias (15/09/2026).
 *
 * O coletor (`backend/ingestion/transferegov_arvore.py`) lê 50 arquivos do dado
 * aberto do TransfereGov e pendura em cada proposta o que antes vinha da
 * raspagem atrás da sessão gov.br — e muito que nunca veio de lugar nenhum:
 * aditivos, prorrogações, pagamentos com o fornecedor, plano de trabalho,
 * prestação de contas. Este arquivo é a TELA disso, em abas do modal de
 * `TransfereGovPropostas`.
 *
 * ⚠️ AS LINHAS CHEGAM CRUAS, pelos nomes das colunas do CSV da fonte
 * (`DT_FIM_TA`, `VL_PAGO`...). Os rótulos em português moram AQUI, num lugar
 * só. Valor chega como texto brasileiro ("252712,63") e passa por `num()`.
 *
 * ⚠️ NULO NÃO É ZERO. Campo que a fonte não mandou sai "—", e lista vazia de
 * uma chave que o coletor não conseguiu ler nesta rodada (`_mantidas`) é dita
 * como tal — nunca como "não há aditivo".
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  Banknote, CalendarClock, ClipboardList, ExternalLink, FileSpreadsheet, Gavel,
  HardHat, History, Loader2, MapPin, Search, Users,
} from "lucide-react";
import api from "@/lib/api";
import { formatCurrency as moeda } from "@/lib/utils";
import {
  AcaoMini, Aviso, Bloco, BlocoHead, Campos, Grade, GradeCel, GradeLinha, ItemLinha,
  Lista, Numero, Secao, Selo, Vazio, situacaoTom, type Campo,
} from "@/components/ui/superficies";

// ---------------------------------------------------------------------------
// Tipos
// ---------------------------------------------------------------------------
/** Uma linha crua do CSV da fonte, com os campos vazios já omitidos. */
export type Linha = Record<string, string | undefined>;

export interface ResumoArvore {
  tem_convenio?: boolean;
  situacao_convenio?: string | null;
  subsituacao_convenio?: string | null;
  empenhado?: number | null;
  desembolsado?: number | null;
  a_desembolsar?: number | null;
  ultimo_desembolso?: string | null;
  faixa_sem_desembolso?: number | null;
  pago_fornecedores?: number | null;
  n_pagamentos?: number | null;
  n_fornecedores?: number | null;
  n_licitacoes?: number | null;
  n_liquidacoes?: number | null;
  tributos?: number | null;
  vigencia_original?: string | null;
  vigencia_atual?: string | null;
  n_aditivos?: number | null;
  n_prorrogacoes?: number | null;
  dias_prorrogados?: number | null;
  prestacao_contas_limite?: string | null;
  prestacao_contas_concluida?: string | null;
  prestacao_contas_aprovada?: string | null;
  cumprimento_objeto?: string | null;
  contrapartida_devida?: number | null;
  contrapartida_depositada?: number | null;
  saldo_conta?: number | null;
  rendimento_aplicacao?: number | null;
  execucao_fisica_pct?: number | null;
  n_medicoes?: number | null;
  situacao_atual?: string | null;
  situacao_desde?: string | null;
  id_projeto_investimento?: string | null;
  so_resumo?: boolean;
}

type ComFilhos<K extends string, T = Linha> = Linha & { [k in K]?: T[] };

export interface Arvore {
  convenio?: Linha | null;
  emendas?: ComFilhos<"apoiadores">[];
  indicadores?: Linha | null;
  historico_situacao?: Linha[];
  projeto_basico?: {
    historico?: Linha[]; proposta?: Linha | null; acffo?: Linha[];
    lae?: Array<Linha & { metas?: ComFilhos<"submetas">[] }>;
  };
  justificativas?: Linha | null;
  metas?: ComFilhos<"etapas">[];
  plano_aplicacao?: Linha[];
  cronograma?: Linha[];
  coordenadas?: Linha[];
  resumo_fisico_financeiro?: Linha | null;
  obras?: {
    medicoes?: ComFilhos<"valores">[];
    vrpl?: Array<Linha & { metas?: Linha[]; lotes?: Linha[] }>;
    aio?: Array<Linha & { contratos?: Linha[]; metas?: Linha[] }>;
  };
  cipi?: {
    id_projeto_investimento?: string; obrasgov?: Linha | null;
    contratos?: Linha[]; empenhos?: Linha[]; execucao_fisica?: Linha[];
  } | null;
  consorcios?: Linha[];
  ajustes_pt?: Linha[];
  empenhos?: Linha[];
  desembolsos?: Linha[];
  tributos?: Linha[];
  aditivos?: Linha[];
  prorrogacoes?: Linha[];
  solicitacoes_alteracao?: Linha[];
  contrapartida?: Linha[];
  rendimentos?: Linha[];
  desbloqueios?: Linha[];
  desbloqueio_recurso?: Linha | null;
  _resumo?: ResumoArvore;
  /** Chaves que o coletor NÃO conseguiu atualizar na última rodada. */
  _mantidas?: string[];
}

/** Os selos da lista (`services/voluntarias_dump.sinais_do_resumo`). */
export interface SinaisDump {
  situacao_convenio?: string | null;
  subsituacao?: string | null;
  execucao_fisica_pct?: number | null;
  prorrogada?: boolean;
  vigencia_original?: string | null;
  dias_sem_desembolso?: number | null;
  nunca_desembolsou?: boolean;
  pc_limite?: string | null;
  pc_dias?: number | null;
}

// ---------------------------------------------------------------------------
// Utilitários
// ---------------------------------------------------------------------------
/** "252712,63" / "100000" / "1.234,56" -> número. A fonte escreve em
 *  português; `parseFloat` sozinho leria "252712,63" como 252712. */
export function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  const s = String(v).trim();
  const n = s.includes(",") ? Number(s.replace(/\./g, "").replace(",", ".")) : Number(s);
  return Number.isFinite(n) ? n : null;
}

const r$ = (v: unknown) => { const n = num(v); return n === null ? "—" : moeda(n); };
const txt = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
/** "PRESTACAO_CONTAS_CONCLUIDA" -> "Prestacao contas concluida" (a fonte
 *  escreve o histórico em constante, sem acento). */
const deConstante = (s?: string | null) =>
  s ? (s.charAt(0) + s.slice(1).toLowerCase()).replace(/_/g, " ") : "—";
const pct = (v: unknown) => { const n = num(v); return n === null ? "—" : `${n.toFixed(2).replace(".", ",")}%`; };

/** dd/mm/aaaa -> timestamp, para ORDENAR. Texto brasileiro comparado como
 *  string poria 31/01 depois de 01/12. */
function ts(v?: string | null): number {
  const m = /(\d{2})\/(\d{2})\/(\d{4})/.exec(v || "");
  return m ? Date.UTC(+m[3], +m[2] - 1, +m[1]) : 0;
}

/** Quantas linhas uma grade mostra antes do "mostrar todas". O plano de
 *  aplicação de UM convênio de Goiânia tem milhares de itens (1 MB de árvore). */
const TETO = 200;

/** Trilhas das grades. LITERAIS e no topo do módulo: o Tailwind só gera a
 *  classe que aparece no código-fonte — montada em tempo de execução vira grade
 *  sem colunas. */
const C_EMPENHO = "grid-cols-[8.5rem_7rem_6rem_minmax(7rem,1fr)_7.5rem]";
const C_PAGTO = "grid-cols-[6rem_minmax(10rem,1.4fr)_9.5rem_minmax(8rem,1fr)_7.5rem]";
const C_DL = "grid-cols-[6rem_6rem_minmax(10rem,1.3fr)_minmax(8rem,1fr)_7rem_7.5rem]";
const C_DATA_VALOR = "grid-cols-[7rem_minmax(8rem,1fr)_8rem]";
const C_ADITIVO = "grid-cols-[4.5rem_minmax(7rem,1fr)_6.5rem_6.5rem_8rem]";
const C_PRORROGA = "grid-cols-[5rem_6.5rem_6.5rem_5rem_minmax(7rem,1fr)]";
const C_SOLIC = "grid-cols-[5rem_6.5rem_minmax(8rem,1fr)_minmax(9rem,2fr)]";
const C_META = "grid-cols-[3.5rem_minmax(10rem,2fr)_6.5rem_6.5rem_5rem_7.5rem]";
const C_PLANO = "grid-cols-[minmax(10rem,2fr)_minmax(7rem,1fr)_4.5rem_7rem_7.5rem]";
const C_CRONO = "grid-cols-[4rem_5.5rem_minmax(7rem,1fr)_8rem]";
const C_ITEM = "grid-cols-[minmax(10rem,2fr)_5rem_6rem_minmax(8rem,1fr)_7.5rem]";
const C_MEDICAO = "grid-cols-[4.5rem_minmax(8rem,1fr)_6.5rem_6.5rem_6rem]";
const C_HIST = "grid-cols-[9.5rem_minmax(12rem,1fr)_5rem]";

function Mais({ total, mostrando, onMais }: { total: number; mostrando: number; onMais: () => void }) {
  if (total <= mostrando) return null;
  return (
    <div className="mt-2 flex items-center gap-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
      Mostrando {mostrando} de {total}.
      <AcaoMini onClick={onMais}>mostrar todas</AcaoMini>
    </div>
  );
}

/** Grade com teto: não trava o navegador num plano de aplicação de milhares de
 *  itens, e não esconde nada — o botão mostra o resto. */
function GradeComTeto<T>({ linhas, cols, cabecalho, render }: {
  linhas: T[]; cols: string; cabecalho: Array<{ label: string; direita?: boolean }>;
  render: (l: T, i: number) => React.ReactNode;
}) {
  const [todas, setTodas] = useState(false);
  const vis = todas ? linhas : linhas.slice(0, TETO);
  return (
    <>
      <Grade rolagem cols={cols} cabecalho={cabecalho}>
        {vis.map((l, i) => <GradeLinha key={i} cols={cols}>{render(l, i)}</GradeLinha>)}
      </Grade>
      {!todas && <Mais total={linhas.length} mostrando={vis.length} onMais={() => setTodas(true)} />}
    </>
  );
}

const Sub = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-1.5 mt-3 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>{children}</div>
);

const Nota = ({ children }: { children: React.ReactNode }) => (
  <p className="mt-1.5 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>{children}</p>
);

/** Diz de onde veio e quando — e se alguma parte ficou de fora da última rodada. */
export function FonteDaArvore({ arvore, atualizadoEm }: { arvore?: Arvore | null; atualizadoEm?: string | null }) {
  const mantidas = arvore?._mantidas || [];
  return (
    <>
      <Nota>
        Fonte: dado aberto do TransfereGov (arquivos de Discricionárias e Legais, carga diária)
        {atualizadoEm ? ` · última mudança ${new Date(atualizadoEm).toLocaleDateString("pt-BR")}` : ""}.
      </Nota>
      {mantidas.length > 0 && (
        <Aviso tom="atencao" titulo="Parte deste dado não foi atualizada na última coleta">
          <Nota>
            A fonte mudou o formato de um arquivo e estas partes ficaram como estavam na coleta
            anterior: {mantidas.join(", ")}.
          </Nota>
        </Aviso>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Quais abas acendem
// ---------------------------------------------------------------------------
export function abasDaArvore(a?: Arvore | null) {
  const r = a?._resumo || {};
  const temConv = !!a?.convenio;
  const temObraDump = !!(a?.resumo_fisico_financeiro || (a?.obras?.medicoes || []).length
    || (a?.coordenadas || []).length || a?.cipi || (a?.obras?.vrpl || []).length
    || (a?.obras?.aio || []).length);
  return {
    execucao: temConv,
    plano: !!(a?.justificativas || (a?.metas || []).length || (a?.plano_aplicacao || []).length
      || (a?.cronograma || []).length || (a?.emendas || []).length),
    prazos: temConv,
    licitacoes: (r.n_licitacoes ?? 0) > 0,
    obraDump: temObraDump,
    linha: (a?.historico_situacao || []).length > 0,
    nLicitacoes: r.n_licitacoes ?? 0,
    nHistorico: (a?.historico_situacao || []).length,
  };
}

// ---------------------------------------------------------------------------
// Lista paginada (pagamentos, liquidações, licitações)
// ---------------------------------------------------------------------------
interface Pagina<T> {
  items: T[]; total: number; soma: number | null; offset: number; limit: number;
  so_resumo: boolean;
  resumo: { n_pagamentos?: number | null; pago_fornecedores?: number | null;
            n_fornecedores?: number | null; n_licitacoes?: number | null; n_liquidacoes?: number | null };
}

function usePagina<T>(tipo: string, numero: string, municipioId: string | number | null | undefined) {
  const [offset, setOffset] = useState(0);
  const [busca, setBusca] = useState("");
  const [buscaAplicada, setBuscaAplicada] = useState("");
  const [dados, setDados] = useState<Pagina<T> | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState(false);
  useEffect(() => {
    if (!municipioId || !numero) return;
    let vivo = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCarregando(true); setErro(false);
    api.get<Pagina<T>>(`/transferegov/voluntarias-arvore/${tipo}`, {
      params: { numero_proposta: numero, municipio_id: municipioId, offset, limit: 50,
                ...(buscaAplicada ? { busca: buscaAplicada } : {}) },
    }).then((r) => { if (vivo) setDados(r.data); })
      .catch(() => { if (vivo) setErro(true); })
      .finally(() => { if (vivo) setCarregando(false); });
    return () => { vivo = false; };
  }, [tipo, numero, municipioId, offset, buscaAplicada]);
  const aplicar = () => { setOffset(0); setBuscaAplicada(busca.trim()); };
  return { dados, carregando, erro, offset, setOffset, busca, setBusca, aplicar };
}

function Paginador<T>({ p, placeholder }: { p: ReturnType<typeof usePagina<T>>; placeholder: string }) {
  const d = p.dados;
  const ate = d ? Math.min(d.offset + d.items.length, d.total) : 0;
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
      <div className="flex items-center gap-1 rounded-lg border px-2 py-1" style={{ borderColor: "var(--bi-line)" }}>
        <Search className="size-3" />
        <input
          value={p.busca} onChange={(e) => p.setBusca(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") p.aplicar(); }}
          placeholder={placeholder} aria-label={placeholder}
          className="w-44 bg-transparent text-[11px] outline-none"
        />
      </div>
      <AcaoMini onClick={p.aplicar}>buscar</AcaoMini>
      {d && d.total > 0 && (
        <span>
          {d.offset + 1}–{ate} de <b className="bi-num">{d.total}</b>
          {d.soma !== null ? <> · <b className="bi-num">{moeda(d.soma)}</b></> : null}
        </span>
      )}
      {p.carregando && <Loader2 className="size-3 animate-spin" />}
      <span className="ml-auto flex gap-1">
        <AcaoMini onClick={() => p.setOffset(Math.max(0, p.offset - 50))}
                  disabled={!d || p.offset === 0 || p.carregando}>‹ anterior</AcaoMini>
        <AcaoMini onClick={() => p.setOffset(p.offset + 50)}
                  disabled={!d || ate >= d.total || p.carregando}>próxima ›</AcaoMini>
      </span>
    </div>
  );
}

/** Proposta que não é da prefeitura: a opção B do dono guarda só as contas. */
function SoResumo({ d, o }: { d: Pagina<unknown>; o: "pagamentos" | "licitacoes" | "liquidacoes" }) {
  const r = d.resumo;
  const linha = o === "pagamentos"
    ? `${r.n_pagamentos ?? 0} pagamento(s), ${moeda(r.pago_fornecedores ?? 0)}, ${r.n_fornecedores ?? 0} fornecedor(es)`
    : o === "licitacoes" ? `${r.n_licitacoes ?? 0} licitação(ões)`
    : `${r.n_liquidacoes ?? 0} documento(s) de liquidação`;
  return (
    <Aviso tom="atencao" titulo="Só o resumo: esta proposta não é da prefeitura">
      <Nota>
        Recebedor sediado no município (estado, entidade ou consórcio). O PACTHA guarda as
        contas — {linha} — e não a lista linha a linha. O detalhe está no portal do TransfereGov.
      </Nota>
    </Aviso>
  );
}

interface Pagamento {
  nr_mov_fin: string; data?: string | null; fornecedor_doc?: string | null;
  fornecedor_nome?: string | null; tipo?: string | null; valor?: number | null;
  nr_dl?: string | null; desc_dl?: string | null; favorecidos?: Linha[];
}
interface Liquidacao {
  id: string; data?: string | null; numero?: string | null; descricao?: string | null;
  razao_social?: string | null; valor?: number | null; status?: string | null; itens?: Linha[];
}
interface Licitacao {
  id: string; data?: string | null; numero?: string | null; modalidade?: string | null;
  status?: string | null; valor?: number | null; dados?: Linha; contratos?: Linha[]; itens?: Linha[];
}

function Pagamentos({ numero, municipioId }: { numero: string; municipioId: string | number }) {
  const p = usePagina<Pagamento>("pagamentos", numero, municipioId);
  const d = p.dados;
  if (d?.so_resumo) return <SoResumo d={d} o="pagamentos" />;
  return (
    <>
      <Paginador p={p} placeholder="fornecedor ou CNPJ" />
      {p.erro ? <Vazio>Não foi possível carregar os pagamentos.</Vazio>
        : d && d.items.length === 0 ? <Vazio>Nenhum pagamento publicado para este convênio.</Vazio>
        : d && (
        <Grade rolagem cols={C_PAGTO} cabecalho={[
          { label: "Data" }, { label: "Fornecedor" }, { label: "CNPJ/CPF" },
          { label: "Nota (documento de liquidação)" }, { label: "Valor", direita: true },
        ]}>
          {d.items.map((x) => (
            <GradeLinha key={x.nr_mov_fin} cols={C_PAGTO}>
              <GradeCel tom="data">{txt(x.data)}</GradeCel>
              <GradeCel title={x.fornecedor_nome || undefined}>
                {txt(x.fornecedor_nome)}
                {(x.favorecidos || []).length > 0 && (
                  <span className="ml-1"><Selo title="Pagamento por OBTV com favorecido final">OBTV · {(x.favorecidos || []).length}</Selo></span>
                )}
              </GradeCel>
              <GradeCel tom="id">{txt(x.fornecedor_doc)}</GradeCel>
              <GradeCel title={x.desc_dl || undefined}>{x.nr_dl ? `${x.nr_dl}${x.desc_dl ? ` · ${x.desc_dl}` : ""}` : txt(x.desc_dl)}</GradeCel>
              <GradeCel tom="num">{x.valor !== null && x.valor !== undefined ? moeda(x.valor) : "—"}</GradeCel>
            </GradeLinha>
          ))}
        </Grade>
      )}
    </>
  );
}

function Liquidacoes({ numero, municipioId }: { numero: string; municipioId: string | number }) {
  const p = usePagina<Liquidacao>("liquidacoes", numero, municipioId);
  const d = p.dados;
  if (d?.so_resumo) return <SoResumo d={d} o="liquidacoes" />;
  return (
    <>
      <Paginador p={p} placeholder="número, empresa ou descrição" />
      {p.erro ? <Vazio>Não foi possível carregar os documentos.</Vazio>
        : d && d.items.length === 0 ? <Vazio>Nenhum documento de liquidação publicado.</Vazio>
        : d && (
        <Grade rolagem cols={C_DL} cabecalho={[
          { label: "Emissão" }, { label: "Número" }, { label: "Empresa" },
          { label: "Descrição" }, { label: "Situação" }, { label: "Valor", direita: true },
        ]}>
          {d.items.map((x) => (
            <GradeLinha key={x.id} cols={C_DL}>
              <GradeCel tom="data">{txt(x.data)}</GradeCel>
              <GradeCel tom="id">{txt(x.numero)}</GradeCel>
              <GradeCel title={x.razao_social || undefined}>{txt(x.razao_social)}</GradeCel>
              <GradeCel title={(x.itens || []).map((i) => i.NOME_ITEM_DL || i.DESCRICAO_ITEM_DL).filter(Boolean).join(" · ") || x.descricao || undefined}>
                {txt(x.descricao)}{(x.itens || []).length ? ` (${(x.itens || []).length} item)` : ""}
              </GradeCel>
              <GradeCel>{x.status ? <Selo tom={situacaoTom(x.status)}>{x.status}</Selo> : "—"}</GradeCel>
              <GradeCel tom="num">{x.valor !== null && x.valor !== undefined ? moeda(x.valor) : "—"}</GradeCel>
            </GradeLinha>
          ))}
        </Grade>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Aba: Execução financeira
// ---------------------------------------------------------------------------
export function AbaExecucao({ arvore, numero, municipioId }: {
  arvore: Arvore; numero: string; municipioId: string | number;
}) {
  const c = arvore.convenio || {};
  const r = arvore._resumo || {};
  const [ver, setVer] = useState<"pagamentos" | "liquidacoes">("pagamentos");
  const empenhos = useMemo(() => [...(arvore.empenhos || [])]
    .sort((a, b) => ts(b.DATA_EMISSAO) - ts(a.DATA_EMISSAO)), [arvore.empenhos]);
  const devida = num(c.VL_CONTRAPARTIDA_CONV);
  const depositada = r.contrapartida_depositada ?? null;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        <Numero icon={Banknote} rotulo="Repasse do convênio" valor={r$(c.VL_REPASSE_CONV)}
                sub={`global ${r$(c.VL_GLOBAL_CONV)}`} />
        <Numero rotulo="Empenhado (NEs publicadas)" valor={r.empenhado != null ? moeda(r.empenhado) : "—"}
                sub={`${empenhos.length} nota(s)`} />
        <Numero rotulo="Desembolsado" tom="ok" valor={r.desembolsado != null ? moeda(r.desembolsado) : "—"}
                sub={r.a_desembolsar ? `falta ${moeda(r.a_desembolsar)}` : undefined} />
        <Numero rotulo="Pago a fornecedores" valor={r.pago_fornecedores != null ? moeda(r.pago_fornecedores) : "—"}
                sub={r.n_pagamentos != null ? `${r.n_pagamentos} pagamento(s) · ${r.n_fornecedores ?? 0} fornecedor(es)` : undefined} />
        <Numero rotulo="Contrapartida depositada"
                tom={devida && depositada !== null && depositada + 0.01 < devida ? "atencao" : "neutro"}
                valor={depositada !== null ? moeda(depositada) : "—"}
                sub={devida !== null ? `devida ${moeda(devida)}` : undefined} />
        <Numero rotulo="Saldo em conta" valor={r$(c.VL_SALDO_CONTA)}
                sub="estimado pela fonte; varia até o próximo dia útil" />
        <Numero rotulo="Rendimento de aplicação" valor={r$(c.VL_RENDIMENTO_APLICACAO)} />
        <Numero rotulo="Tributos pagos" valor={r.tributos != null ? moeda(r.tributos) : "—"} />
      </div>
      {r.pago_fornecedores != null && r.desembolsado != null && r.pago_fornecedores > r.desembolsado + 0.01 && (
        <Nota>
          Pago maior que desembolsado não é erro: o convenente paga com o repasse E com a
          contrapartida (e o rendimento da aplicação).
        </Nota>
      )}

      <Secao icon={ClipboardList} titulo="Pagamentos e documentos de liquidação"
             sub="quem recebeu, quanto e com qual nota">
        <div className="mb-2 flex gap-1">
          <AcaoMini onClick={() => setVer("pagamentos")} disabled={ver === "pagamentos"}>Pagamentos</AcaoMini>
          <AcaoMini onClick={() => setVer("liquidacoes")} disabled={ver === "liquidacoes"}>Documentos de liquidação</AcaoMini>
        </div>
        {ver === "pagamentos"
          ? <Pagamentos numero={numero} municipioId={municipioId} />
          : <Liquidacoes numero={numero} municipioId={municipioId} />}
      </Secao>

      {empenhos.length > 0 && (
        <Secao icon={FileSpreadsheet} titulo="Notas de empenho (dado aberto)" sub={`${empenhos.length} nota(s)`}>
          <GradeComTeto linhas={empenhos} cols={C_EMPENHO} cabecalho={[
            { label: "Nº do empenho" }, { label: "Tipo" }, { label: "Emissão" },
            { label: "Situação" }, { label: "Valor", direita: true },
          ]} render={(e) => (<>
            <GradeCel tom="id">{txt(e.NR_EMPENHO)}</GradeCel>
            <GradeCel>{txt(e.DESC_TIPO_NOTA)}</GradeCel>
            <GradeCel tom="data">{txt(e.DATA_EMISSAO)}</GradeCel>
            <GradeCel>{e.DESC_SITUACAO_EMPENHO ? <Selo tom={situacaoTom(e.DESC_SITUACAO_EMPENHO)}>{e.DESC_SITUACAO_EMPENHO}</Selo> : "—"}</GradeCel>
            <GradeCel tom="num">{r$(e.VALOR_EMPENHO)}</GradeCel>
          </>)} />
          <Nota>
            A fonte publica algumas notas com valor zero; o empenhado soma o que ela publica. O
            desembolso (ordens bancárias) está na aba OPs/OBs.
          </Nota>
        </Secao>
      )}

      {((arvore.contrapartida || []).length > 0 || (arvore.tributos || []).length > 0) && (
        <Secao icon={Banknote} titulo="Contrapartida e tributos">
          {(arvore.contrapartida || []).length > 0 && (<>
            <Sub>Ingressos de contrapartida · {(arvore.contrapartida || []).length}</Sub>
            <GradeComTeto linhas={[...(arvore.contrapartida || [])].sort((a, b) => ts(b.DT_INGRESSO_CONTRAPARTIDA) - ts(a.DT_INGRESSO_CONTRAPARTIDA))}
              cols={C_DATA_VALOR} cabecalho={[{ label: "Data" }, { label: "" }, { label: "Valor", direita: true }]}
              render={(x) => (<>
                <GradeCel tom="data">{txt(x.DT_INGRESSO_CONTRAPARTIDA)}</GradeCel>
                <GradeCel>Depósito de contrapartida</GradeCel>
                <GradeCel tom="num">{r$(x.VL_INGRESSO_CONTRAPARTIDA)}</GradeCel>
              </>)} />
          </>)}
          {(arvore.tributos || []).length > 0 && (<>
            <Sub>Tributos pagos · {(arvore.tributos || []).length}</Sub>
            <GradeComTeto linhas={[...(arvore.tributos || [])].sort((a, b) => ts(b.DATA_TRIBUTO) - ts(a.DATA_TRIBUTO))}
              cols={C_DATA_VALOR} cabecalho={[{ label: "Data" }, { label: "" }, { label: "Valor", direita: true }]}
              render={(x) => (<>
                <GradeCel tom="data">{txt(x.DATA_TRIBUTO)}</GradeCel>
                <GradeCel>Pagamento de tributo</GradeCel>
                <GradeCel tom="num">{r$(x.VL_PAG_TRIBUTOS)}</GradeCel>
              </>)} />
          </>)}
        </Secao>
      )}

      {((arvore.rendimentos || []).length > 0 || (arvore.desbloqueios || []).length > 0) && (
        <Secao icon={Banknote} titulo="Rendimento de aplicação e desbloqueios">
          {(arvore.rendimentos || []).map((x, i) => (
            <Campos key={`r${i}`} cols={4} campos={[
              { rotulo: "Solicitação de uso do rendimento", valor: txt(x.NR_SOLICITACAO_REND_APLICACAO) },
              { rotulo: "Data", valor: txt(x.DATA_SOLICITACAO_REND_APLICACAO) },
              { rotulo: "Pedido / aprovado", valor: `${r$(x.VALOR_SOLICITACAO_REND_APLICACAO)} / ${r$(x.VALOR_APROVADO_SOLICITACAO_REND_APLICACAO)}` },
              { rotulo: "Situação", valor: txt(x.STATUS_SOLICITACAO_REND_APLICACAO) },
            ]} />
          ))}
          {(arvore.desbloqueios || []).length > 0 && (<>
            <Sub>Desbloqueios · {(arvore.desbloqueios || []).length}</Sub>
            {(arvore.desbloqueios || []).map((x, i) => (
              <Campos key={`d${i}`} cols={4} campos={[
                { rotulo: "OB", valor: txt(x.NR_OB), mono: true },
                { rotulo: "Envio", valor: txt(x.DATA_ENVIO || x.DATA_CADASTRO) },
                { rotulo: "Desbloqueado / bloqueado", valor: `${r$(x.VL_DESBLOQUEADO)} / ${r$(x.VL_BLOQUEADO)}` },
                { rotulo: "Recurso", valor: txt(x.TIPO_RECURSO_DESBLOQUEIO) },
              ]} />
            ))}
          </>)}
        </Secao>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aba: Prazos e aditivos
// ---------------------------------------------------------------------------
export function AbaPrazos({ arvore }: { arvore: Arvore }) {
  const c = arvore.convenio || {};
  const ind = arvore.indicadores || {};
  const r = arvore._resumo || {};
  /* A LINHA DA VIGÊNCIA: da original, passo a passo, até a atual. Aditivo sem
     `DT_FIM_TA` mexeu em outra coisa (valor, meta) e não entra na linha. */
  const passos = useMemo(() => {
    const p: Array<{ data: string; rotulo: string; detalhe?: string }> = [];
    for (const a of arvore.aditivos || []) {
      if (a.DT_FIM_TA) p.push({ data: a.DT_FIM_TA, rotulo: `Termo aditivo ${a.NUMERO_TA || ""}`.trim(),
                                detalhe: [a.TIPO_TA, a.DT_ASSINATURA_TA && `assinado ${a.DT_ASSINATURA_TA}`].filter(Boolean).join(" · ") });
    }
    for (const pr of arvore.prorrogacoes || []) {
      if (pr.DT_FIM_PRORROGA) p.push({ data: pr.DT_FIM_PRORROGA, rotulo: `Prorrogação de ofício ${pr.NR_PRORROGA || ""}`.trim(),
                                       detalhe: [pr.DIAS_PRORROGA && `+${pr.DIAS_PRORROGA} dias`, pr.SIT_PRORROGA].filter(Boolean).join(" · ") });
    }
    return p.sort((a, b) => ts(a.data) - ts(b.data));
  }, [arvore.aditivos, arvore.prorrogacoes]);
  const campos: Campo[] = [
    { rotulo: "Assinatura", valor: txt(c.DIA_ASSIN_CONV) },
    { rotulo: "Início da vigência", valor: txt(c.DIA_INIC_VIGENC_CONV) },
    { rotulo: "Fim original", valor: txt(c.DIA_FIM_VIGENC_ORIGINAL_CONV) },
    { rotulo: "Fim atual", valor: txt(c.DIA_FIM_VIGENC_CONV),
      tom: c.DIA_FIM_VIGENC_ORIGINAL_CONV && c.DIA_FIM_VIGENC_CONV && c.DIA_FIM_VIGENC_ORIGINAL_CONV !== c.DIA_FIM_VIGENC_CONV ? "atencao" : "normal" },
    { rotulo: "Aditivos / prorrogações", valor: `${r.n_aditivos ?? "—"} / ${r.n_prorrogacoes ?? "—"}` },
    { rotulo: "Dias prorrogados de ofício", valor: txt(r.dias_prorrogados) },
    { rotulo: "Situação do convênio", valor: txt(c.SIT_CONVENIO) },
    ...(c.SUBSITUACAO_CONV ? [{ rotulo: "Subsituação", valor: c.SUBSITUACAO_CONV,
        tom: /tce/i.test(c.SUBSITUACAO_CONV) ? "critico" as const : "atencao" as const }] : []),
  ];
  return (
    <div className="flex flex-col gap-3">
      <Secao icon={CalendarClock} titulo="Vigência" campos={campos}>
        {passos.length > 0 && (<>
          <Sub>Da vigência original à atual</Sub>
          <ol className="flex flex-col gap-1">
            <li className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              <b className="bi-num" style={{ color: "var(--bi-text)" }}>{txt(c.DIA_FIM_VIGENC_ORIGINAL_CONV)}</b> · vigência original
            </li>
            {passos.map((p, i) => (
              <li key={i} className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                → <b className="bi-num" style={{ color: "var(--bi-text)" }}>{p.data}</b> · {p.rotulo}
                {p.detalhe ? ` · ${p.detalhe}` : ""}
              </li>
            ))}
          </ol>
        </>)}
        {(c.DATA_SUSPENSIVA || c.DATA_RETIRADA_SUSPENSIVA) && (
          <Campos cols={3} campos={[
            { rotulo: "Cláusula suspensiva até", valor: txt(c.DATA_SUSPENSIVA) },
            { rotulo: "Retirada da suspensiva", valor: txt(c.DATA_RETIRADA_SUSPENSIVA) },
            { rotulo: "Dias em suspensiva", valor: txt(c.DIAS_CLAUSULA_SUSPENSIVA) },
          ]} />
        )}
      </Secao>

      <Secao icon={ClipboardList} titulo="Prestação de contas" campos={[
        { rotulo: "Prazo limite", valor: txt(c.DIA_LIMITE_PREST_CONTAS) },
        { rotulo: "Enviada / concluída", valor: txt(ind.DT_CONCLUSAO_PRESTACAO_CONTAS) },
        { rotulo: "Aprovada", valor: txt(ind.DT_APROVACAO_PRESTACAO_CONTAS || ind.DT_APROVACAO_COM_RESSALVAS_PRESTACAO_CONTAS) },
        { rotulo: "Rejeitada", valor: txt(ind.DT_APROVACAO_REJEICAO_PRESTACAO_CONTAS) },
        { rotulo: "Cumprimento do objeto", valor: txt(ind.CUMPRIMENTO_OBJETO) },
        { rotulo: "Realização dos objetivos", valor: txt(ind.REALIZACAO_OBJETIVOS_CONV) },
      ]}>
        {!arvore.indicadores && (
          <Nota>A fonte publica os indicadores de prestação de contas só para parte dos convênios; aqui não vieram.</Nota>
        )}
      </Secao>

      {(arvore.aditivos || []).length > 0 && (
        <Secao icon={FileSpreadsheet} titulo="Termos aditivos" sub={`${(arvore.aditivos || []).length}`}>
          <GradeComTeto linhas={arvore.aditivos || []} cols={C_ADITIVO} cabecalho={[
            { label: "Nº" }, { label: "Tipo" }, { label: "Assinatura" }, { label: "Novo fim" },
            { label: "Novo valor global", direita: true },
          ]} render={(a) => (<>
            <GradeCel tom="id">{txt(a.NUMERO_TA)}</GradeCel>
            <GradeCel title={a.JUSTIFICATIVA_TA || undefined}>{txt(a.TIPO_TA)}</GradeCel>
            <GradeCel tom="data">{txt(a.DT_ASSINATURA_TA)}</GradeCel>
            <GradeCel tom="data">{txt(a.DT_FIM_TA)}</GradeCel>
            <GradeCel tom="num">{r$(a.VL_GLOBAL_TA)}</GradeCel>
          </>)} />
          <Nota>Passe o mouse sobre o tipo para ver a justificativa do aditivo.</Nota>
        </Secao>
      )}

      {(arvore.prorrogacoes || []).length > 0 && (
        <Secao icon={CalendarClock} titulo="Prorrogações de ofício" sub={`${(arvore.prorrogacoes || []).length}`}>
          <GradeComTeto linhas={arvore.prorrogacoes || []} cols={C_PRORROGA} cabecalho={[
            { label: "Nº" }, { label: "Início" }, { label: "Novo fim" }, { label: "Dias", direita: true },
            { label: "Situação" },
          ]} render={(p) => (<>
            <GradeCel tom="id">{txt(p.NR_PRORROGA)}</GradeCel>
            <GradeCel tom="data">{txt(p.DT_INICIO_PRORROGA)}</GradeCel>
            <GradeCel tom="data">{txt(p.DT_FIM_PRORROGA)}</GradeCel>
            <GradeCel tom="num">{txt(p.DIAS_PRORROGA)}</GradeCel>
            <GradeCel>{txt(p.SIT_PRORROGA)}</GradeCel>
          </>)} />
        </Secao>
      )}

      {((arvore.solicitacoes_alteracao || []).length > 0 || (arvore.ajustes_pt || []).length > 0) && (
        <Secao icon={History} titulo="Solicitações de alteração e ajustes do plano de trabalho">
          {(arvore.solicitacoes_alteracao || []).length > 0 && (
            <GradeComTeto linhas={[...(arvore.solicitacoes_alteracao || [])].sort((a, b) => ts(b.DATA_SOLICITACAO) - ts(a.DATA_SOLICITACAO))}
              cols={C_SOLIC} cabecalho={[{ label: "Nº" }, { label: "Data" }, { label: "Situação" }, { label: "Objeto" }]}
              render={(s) => (<>
                <GradeCel tom="id">{txt(s.NR_SOLICITACAO)}</GradeCel>
                <GradeCel tom="data">{txt(s.DATA_SOLICITACAO)}</GradeCel>
                <GradeCel>{s.SITUACAO_SOLICITACAO ? <Selo tom={situacaoTom(s.SITUACAO_SOLICITACAO)}>{s.SITUACAO_SOLICITACAO}</Selo> : "—"}</GradeCel>
                <GradeCel title={s.OBJETO_SOLICITACAO || undefined}>{txt(s.OBJETO_SOLICITACAO)}</GradeCel>
              </>)} />
          )}
          {(arvore.ajustes_pt || []).length > 0 && (<>
            <Sub>Ajustes do plano de trabalho · {(arvore.ajustes_pt || []).length}</Sub>
            <GradeComTeto linhas={arvore.ajustes_pt || []} cols={C_SOLIC}
              cabecalho={[{ label: "Nº" }, { label: "Data" }, { label: "Situação" }, { label: "" }]}
              render={(s) => (<>
                <GradeCel tom="id">{txt(s.NR_AJUSTE_PT)}</GradeCel>
                <GradeCel tom="data">{txt(s.DATA_SOLICITACAO_AJUSTE_PT)}</GradeCel>
                <GradeCel>{txt(s.SITUACAO_SOLICITACAO_AJUSTE_PT)}</GradeCel>
                <GradeCel>{""}</GradeCel>
              </>)} />
          </>)}
        </Secao>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aba: Plano de trabalho
// ---------------------------------------------------------------------------
const JUSTIFICATIVAS: Array<[string, string]> = [
  ["JUSTIFICATIVA", "Justificativa"],
  ["PROBLEMA_A_SER_RESOLVIDO", "Problema a ser resolvido"],
  ["PUBLICO_ALVO", "Público-alvo"],
  ["RESULTADOS_ESPERADOS", "Resultados esperados"],
  ["CARACTERIZACAO_INTERESSES_RECI", "Interesses recíprocos"],
  ["RELACAO_PROPOSTA_OBJETIVOS_PRO", "Relação com os objetivos do programa"],
  ["CAPACIDADE_TECNICA", "Capacidade técnica e gerencial"],
];

export function AbaPlano({ arvore }: { arvore: Arvore }) {
  const j = arvore.justificativas || {};
  const metas = arvore.metas || [];
  const plano = arvore.plano_aplicacao || [];
  const totalPlano = plano.reduce((s, x) => s + (num(x.VALOR_TOTAL_ITEM) || 0), 0);
  return (
    <div className="flex flex-col gap-3">
      {JUSTIFICATIVAS.some(([k]) => j[k]) && (
        <Secao icon={ClipboardList} titulo="Justificativa da proposta">
          <dl className="flex flex-col gap-2">
            {JUSTIFICATIVAS.filter(([k]) => j[k]).map(([k, rot]) => (
              <div key={k}>
                <dt className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>{rot}</dt>
                <dd className="mt-0.5 whitespace-pre-line text-[12px] leading-snug break-words" style={{ color: "var(--bi-text)" }}>{j[k]}</dd>
              </div>
            ))}
          </dl>
        </Secao>
      )}

      {metas.length > 0 && (
        <Secao icon={ClipboardList} titulo="Metas e etapas" sub={`${metas.length} meta(s)`}>
          <div className="flex flex-col gap-2">
            {[...metas].sort((a, b) => (num(a.NR_META) || 0) - (num(b.NR_META) || 0)).map((m, i) => (
              <div key={i} className="bi-card-flat p-3">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <Selo tom="acento">Meta {txt(m.NR_META)}</Selo>
                  <span className="text-[12px] font-medium" style={{ color: "var(--bi-text)" }}>{txt(m.DESC_META)}</span>
                  <span className="ml-auto bi-num text-[11px]" style={{ color: "var(--bi-muted)" }}>{r$(m.VL_META)}</span>
                </div>
                <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  {txt(m.DATA_INICIO_META)} a {txt(m.DATA_FIM_META)}
                  {m.QTD_META ? ` · ${m.QTD_META} ${m.UND_FORNECIMENTO_META || ""}` : ""}
                  {m.MUNICIPIO_META ? ` · ${m.MUNICIPIO_META}` : ""}
                </div>
                {(m.etapas || []).length > 0 && (
                  <div className="mt-2">
                    <GradeComTeto linhas={[...(m.etapas || [])].sort((a, b) => (num(a.NR_ETAPA) || 0) - (num(b.NR_ETAPA) || 0))}
                      cols={C_META} cabecalho={[
                        { label: "Etapa" }, { label: "Descrição" }, { label: "Início" }, { label: "Fim" },
                        { label: "Qtd.", direita: true }, { label: "Valor", direita: true },
                      ]} render={(e) => (<>
                        <GradeCel tom="id">{txt(e.NR_ETAPA)}</GradeCel>
                        <GradeCel title={e.DESC_ETAPA || undefined}>{txt(e.DESC_ETAPA)}</GradeCel>
                        <GradeCel tom="data">{txt(e.DATA_INICIO_ETAPA)}</GradeCel>
                        <GradeCel tom="data">{txt(e.DATA_FIM_ETAPA)}</GradeCel>
                        <GradeCel tom="num">{txt(e.QTD_ETAPA)}</GradeCel>
                        <GradeCel tom="num">{r$(e.VL_ETAPA)}</GradeCel>
                      </>)} />
                  </div>
                )}
              </div>
            ))}
          </div>
        </Secao>
      )}

      {plano.length > 0 && (
        <Secao icon={FileSpreadsheet} titulo="Plano de aplicação detalhado"
               sub={`${plano.length} item(ns) · ${moeda(totalPlano)}`}>
          <GradeComTeto linhas={plano} cols={C_PLANO} cabecalho={[
            { label: "Item" }, { label: "Natureza da despesa" }, { label: "Qtd.", direita: true },
            { label: "Unitário", direita: true }, { label: "Total", direita: true },
          ]} render={(x) => (<>
            <GradeCel title={x.DESCRICAO_ITEM || undefined}>{txt(x.DESCRICAO_ITEM)}</GradeCel>
            <GradeCel title={x.NATUREZA_DESPESA || undefined}>{txt(x.TIPO_DESPESA_ITEM || x.NATUREZA_DESPESA)}</GradeCel>
            <GradeCel tom="num">{txt(x.QTD_ITEM)}</GradeCel>
            <GradeCel tom="num">{r$(x.VALOR_UNITARIO_ITEM)}</GradeCel>
            <GradeCel tom="num">{r$(x.VALOR_TOTAL_ITEM)}</GradeCel>
          </>)} />
        </Secao>
      )}

      {(arvore.cronograma || []).length > 0 && (
        <Secao icon={CalendarClock} titulo="Cronograma de desembolso" sub={`${(arvore.cronograma || []).length} parcela(s)`}>
          <GradeComTeto linhas={[...(arvore.cronograma || [])].sort((a, b) =>
              (num(a.ANO_CRONO_DESEMBOLSO) || 0) * 100 + (num(a.MES_CRONO_DESEMBOLSO) || 0)
              - ((num(b.ANO_CRONO_DESEMBOLSO) || 0) * 100 + (num(b.MES_CRONO_DESEMBOLSO) || 0)))}
            cols={C_CRONO} cabecalho={[{ label: "Parcela" }, { label: "Mês/ano" }, { label: "Responsável" }, { label: "Valor", direita: true }]}
            render={(x) => (<>
              <GradeCel tom="id">{txt(x.NR_PARCELA_CRONO_DESEMBOLSO)}</GradeCel>
              <GradeCel tom="data">{x.MES_CRONO_DESEMBOLSO ? `${String(x.MES_CRONO_DESEMBOLSO).padStart(2, "0")}/${x.ANO_CRONO_DESEMBOLSO || ""}` : "—"}</GradeCel>
              <GradeCel>{txt(x.TIPO_RESP_CRONO_DESEMBOLSO)}</GradeCel>
              <GradeCel tom="num">{r$(x.VALOR_PARCELA_CRONO_DESEMBOLSO)}</GradeCel>
            </>)} />
        </Secao>
      )}

      {(arvore.emendas || []).length > 0 && (
        <Secao icon={Users} titulo="Emendas parlamentares e apoiadores" sub={`${(arvore.emendas || []).length} emenda(s)`}>
          <div className="flex flex-col gap-2">
            {(arvore.emendas || []).map((e, i) => (
              <div key={i} className="bi-card-flat p-3">
                <Campos cols={4} campos={[
                  { rotulo: "Emenda", valor: txt(e.NR_EMENDA), mono: true },
                  { rotulo: "Parlamentar", valor: txt(e.NOME_PARLAMENTAR) },
                  { rotulo: "Tipo", valor: [e.TIPO_PARLAMENTAR, e.IND_IMPOSITIVO === "SIM" ? "impositiva" : null].filter(Boolean).join(" · ") || "—" },
                  { rotulo: "Valor da emenda na proposta", valor: r$(e.VALOR_REPASSE_EMENDA || e.VALOR_REPASSE_PROPOSTA_EMENDA) },
                ]} />
                {(e.apoiadores || []).length > 0 && (
                  <Nota>
                    Apoiadores: {(e.apoiadores || []).map((a) =>
                      a.NOME_PARLAMENTAR_APOIADORES_EMENDAS || a.NOME_PJ_SOLICITANTE_APOIADORES_EMENDAS
                      || a.NOME_PF_SOLICITANTE_APOIADORES_EMENDAS).filter(Boolean).join(" · ") || "—"}
                  </Nota>
                )}
              </div>
            ))}
          </div>
        </Secao>
      )}

      {(arvore.consorcios || []).length > 0 && (
        <Secao icon={Users} titulo="Consórcio" sub={txt(arvore.consorcios?.[0]?.NOME_CONSORCIO)}>
          <Nota>
            Participantes: {Array.from(new Set((arvore.consorcios || []).map((x) => x.NOME_PARTICIPANTE).filter(Boolean))).join(" · ")}
          </Nota>
        </Secao>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aba: Licitações (paginada)
// ---------------------------------------------------------------------------
export function AbaLicitacoes({ numero, municipioId }: { numero: string; municipioId: string | number }) {
  const p = usePagina<Licitacao>("licitacoes", numero, municipioId);
  const [aberta, setAberta] = useState<string | null>(null);
  const d = p.dados;
  if (d?.so_resumo) return <SoResumo d={d} o="licitacoes" />;
  return (
    <Secao icon={Gavel} titulo="Licitações e contratos" sub="dado aberto do TransfereGov">
      <Paginador p={p} placeholder="número, modalidade ou situação" />
      {p.erro ? <Vazio>Não foi possível carregar as licitações.</Vazio>
        : d && d.items.length === 0 ? <Vazio>Nenhuma licitação publicada para este convênio.</Vazio>
        : d && (
        <div className="flex flex-col gap-1.5">
          {d.items.map((l) => {
            const x = l.dados || {};
            const abrir = aberta === l.id;
            return (
              <div key={l.id} className="bi-card-flat p-3">
                <button type="button" className="flex w-full flex-wrap items-center gap-2 text-left"
                        onClick={() => setAberta(abrir ? null : l.id)} aria-expanded={abrir}>
                  <span className="bi-num text-[11px] font-semibold" style={{ color: "var(--bi-text)" }}>{txt(l.numero)}</span>
                  <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{txt(l.modalidade)}</span>
                  {l.status && <Selo tom={situacaoTom(l.status)}>{l.status}</Selo>}
                  {x.SITUACAO_ACEITE_PROCESSO_EXECU && <Selo title="Aceite do processo de execução pelo concedente">{x.SITUACAO_ACEITE_PROCESSO_EXECU}</Selo>}
                  <span className="ml-auto bi-num text-[11px]" style={{ color: "var(--bi-muted)" }}>
                    {txt(l.data)} · {l.valor != null ? moeda(l.valor) : "—"}
                  </span>
                </button>
                {abrir && (
                  <div className="mt-2">
                    <Campos cols={4} campos={[
                      { rotulo: "Processo", valor: txt(x.NR_PROCESSO_LICITACAO), mono: true },
                      { rotulo: "Abertura", valor: txt(x.DATA_ABERTURA_LICITACAO) },
                      { rotulo: "Homologação", valor: txt(x.DATA_HOMOLOGACAO_LICITACAO) },
                      { rotulo: "Sistema de origem", valor: txt(x.SISTEMA_ORIGEM) },
                    ]} />
                    {(l.contratos || []).length > 0 && (<>
                      <Sub>Contratos · {(l.contratos || []).length}</Sub>
                      {(l.contratos || []).map((ct, i) => (
                        <Campos key={i} cols={4} campos={[
                          { rotulo: "Contrato", valor: txt(ct.NR_CONTRATO), mono: true },
                          { rotulo: "Fornecedor", valor: txt(ct.NOME_FORNECEDOR_CONTRATO), span: 2 },
                          { rotulo: "Valor", valor: r$(ct.VALOR_GLOBAL_CONTRATO) },
                          { rotulo: "Assinatura", valor: txt(ct.DATA_ASSINATURA_CONTRATO) },
                          { rotulo: "Vigência", valor: `${txt(ct.DATA_INICIO_VIGENCIA_CONTRATO)} a ${txt(ct.DATA_FIM_VIGENCIA_CONTRATO)}` },
                          { rotulo: "Objeto", valor: txt(ct.OBJETO_CONTRATO), span: 2, quebra: true },
                        ]} />
                      ))}
                    </>)}
                    {(l.itens || []).length > 0 && (<>
                      <Sub>Itens · {(l.itens || []).length}</Sub>
                      <GradeComTeto linhas={l.itens || []} cols={C_ITEM} cabecalho={[
                        { label: "Item" }, { label: "Qtd.", direita: true }, { label: "Unitário", direita: true },
                        { label: "Fornecedor" }, { label: "Total", direita: true },
                      ]} render={(it) => (<>
                        <GradeCel title={it.DESCRICAO_ITEM_LICITACAO || undefined}>{txt(it.DESCRICAO_ITEM_LICITACAO)}</GradeCel>
                        <GradeCel tom="num">{txt(it.QUANTIDADE_ITEM_LICITACAO)}</GradeCel>
                        <GradeCel tom="num">{r$(it.PRECO_UNITARIO_ITEM_LICITACAO)}</GradeCel>
                        <GradeCel title={it.NOME_FORNECEDOR_ITEM_LICITACAO || undefined}>{txt(it.NOME_FORNECEDOR_ITEM_LICITACAO)}</GradeCel>
                        <GradeCel tom="num">{r$(it.VALOR_TOTAL_ITEM_LICITACAO)}</GradeCel>
                      </>)} />
                    </>)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Secao>
  );
}

// ---------------------------------------------------------------------------
// Obras (a parte do dump, somada à aba de obras da raspagem)
// ---------------------------------------------------------------------------
export function ObrasDoDump({ arvore }: { arvore: Arvore }) {
  const rff = arvore.resumo_fisico_financeiro;
  const cipi = arvore.cipi;
  const execs = [...(cipi?.execucao_fisica || [])].sort((a, b) => ts(b.data_situacao) - ts(a.data_situacao));
  const meds = arvore.obras?.medicoes || [];
  const coords = (arvore.coordenadas || []).filter((x) => x.LATITUDE_CADASTRO_OBRA && x.LONGITUDE_CADASTRO_OBRA);
  const link = cipi?.obrasgov?.link_transparencia;
  return (
    <Secao icon={HardHat} titulo="Obra no dado aberto" sub="resumo físico-financeiro, medições e o elo com o Obras.gov">
      <Campos cols={4} campos={[
        { rotulo: "Valor total", valor: r$(rff?.VALOR_TOTAL_RESUMO_FISICO_FINANCEIRO) },
        { rotulo: "Realizado", valor: r$(rff?.VALOR_REALIZADO_RESUMO_FISICO_FINANCEIRO) },
        { rotulo: "Execução física", valor: pct(rff?.PERCENTUAL_EXECUCAO_RESUMO_FISICO_FINANCEIRO) },
        { rotulo: "Projeto no Obras.gov", valor: cipi?.id_projeto_investimento || "—", mono: true },
      ]} />
      {link && (
        <a href={link} target="_blank" rel="noreferrer noopener"
           className="mt-2 inline-flex items-center gap-1 text-[11px] hover:underline" style={{ color: "var(--bi-accent-ink)" }}>
          <ExternalLink className="size-3" /> Ver a obra no Obras.gov / Transparência
        </a>
      )}
      {execs.length > 0 && (
        <Nota>
          Última situação no Obras.gov: {pct(execs[0].percentual_execucao)} executado
          {execs[0].data_situacao ? ` em ${execs[0].data_situacao}` : ""}
          {execs[0].justificativa ? ` · ${execs[0].justificativa}` : ""}.
        </Nota>
      )}
      {meds.length > 0 && (<>
        <Sub>Medições · {meds.length}</Sub>
        <GradeComTeto linhas={[...meds].sort((a, b) => (num(b.NUMERO_MEDICAO_ACOMPANHAMENTO_OBRA) || 0) - (num(a.NUMERO_MEDICAO_ACOMPANHAMENTO_OBRA) || 0))}
          cols={C_MEDICAO} cabecalho={[
            { label: "Medição" }, { label: "Situação" }, { label: "De" }, { label: "Até" },
            { label: "Dias sem medição", direita: true },
          ]} render={(m) => (<>
            <GradeCel tom="id">{txt(m.NUMERO_MEDICAO_ACOMPANHAMENTO_OBRA)}</GradeCel>
            <GradeCel>{m.SITUACAO_MEDICAO_ACOMPANHAMENTO_OBRA ? <Selo tom={situacaoTom(m.SITUACAO_MEDICAO_ACOMPANHAMENTO_OBRA)}>{m.SITUACAO_MEDICAO_ACOMPANHAMENTO_OBRA}</Selo> : "—"}</GradeCel>
            <GradeCel tom="data">{txt(m.DATA_INICIO_MEDICAO_OBJETO_ACOMPANHAMENTO_OBRA)}</GradeCel>
            <GradeCel tom="data">{txt(m.DATA_FIM_MEDICAO_OBJETO_ACOMPANHAMENTO_OBRA)}</GradeCel>
            <GradeCel tom="num">{txt(m.QTD_DIAS_SEM_MEDICAO_ACOMPANHAMENTO_OBRA)}</GradeCel>
          </>)} />
      </>)}
      {coords.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {coords.map((x, i) => (
            <a key={i} target="_blank" rel="noreferrer noopener"
               href={`https://www.google.com/maps?q=${encodeURIComponent(`${x.LATITUDE_CADASTRO_OBRA},${x.LONGITUDE_CADASTRO_OBRA}`)}`}
               className="inline-flex items-center gap-1 text-[11px] hover:underline" style={{ color: "var(--bi-accent-ink)" }}>
              <MapPin className="size-3" /> {x.NOME_PROJETO_CADASTRO_OBRA || "Localização da obra"}
            </a>
          ))}
        </div>
      )}
    </Secao>
  );
}

// ---------------------------------------------------------------------------
// Aba: Linha do tempo
// ---------------------------------------------------------------------------
export function AbaLinhaTempo({ arvore }: { arvore: Arvore }) {
  const hist = useMemo(() => [...(arvore.historico_situacao || [])]
    .sort((a, b) => ts(b.DIA_HISTORICO_SIT) - ts(a.DIA_HISTORICO_SIT)
      || String(b.DIA_HISTORICO_SIT || "").localeCompare(String(a.DIA_HISTORICO_SIT || ""))),
    [arvore.historico_situacao]);
  const pb = [...(arvore.projeto_basico?.historico || [])].sort((a, b) => ts(b.DATA_HIST_PB_TR) - ts(a.DATA_HIST_PB_TR));
  return (
    <div className="flex flex-col gap-3">
      <Secao icon={History} titulo="Linha do tempo da proposta" sub={`${hist.length} mudança(s) de situação`}>
        <GradeComTeto linhas={hist} cols={C_HIST} cabecalho={[
          { label: "Data" }, { label: "Situação" }, { label: "Dias nela", direita: true },
        ]} render={(h) => (<>
          <GradeCel tom="data">{txt(h.DIA_HISTORICO_SIT)}</GradeCel>
          <GradeCel><Selo tom={situacaoTom(deConstante(h.HISTORICO_SIT))}>{deConstante(h.HISTORICO_SIT)}</Selo></GradeCel>
          <GradeCel tom="num">{txt(h.DIAS_HISTORICO_SIT)}</GradeCel>
        </>)} />
        <Nota>
          As comunicações e os termos de notificação continuam nas abas Histórico e Documentos,
          que dependem da sessão do portal.
        </Nota>
      </Secao>
      {pb.length > 0 && (
        <Secao icon={History} titulo="Projeto básico / termo de referência" sub={`${pb.length} evento(s)`}>
          <GradeComTeto linhas={pb} cols={C_HIST} cabecalho={[
            { label: "Data" }, { label: "Evento · situação" }, { label: "Versão", direita: true },
          ]} render={(h) => (<>
            <GradeCel tom="data">{txt(h.DATA_HIST_PB_TR)}</GradeCel>
            <GradeCel title={h.EVENTO_HIST_PB_TR || undefined}>
              {txt(h.EVENTO_HIST_PB_TR)}{h.SITUACAO_HIST_PB_TR ? ` · ${h.SITUACAO_HIST_PB_TR}` : ""}
            </GradeCel>
            <GradeCel tom="num">{txt(h.VERSAO_DOC_PB_TR)}</GradeCel>
          </>)} />
        </Secao>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Selos da lista
// ---------------------------------------------------------------------------
export function SelosDoDump({ s }: { s?: SinaisDump | null }) {
  if (!s) return null;
  const out: React.ReactNode[] = [];
  if (s.subsituacao) {
    out.push(<Selo key="sub" tom={/tce/i.test(s.subsituacao) ? "critico" : "neutro"}
                   title={`Subsituação do convênio: ${s.subsituacao}`}>{s.subsituacao}</Selo>);
  }
  if (s.pc_dias != null) {
    if (s.pc_dias < 0) {
      out.push(<Selo key="pc" tom="critico" title={`Prazo da prestação de contas: ${s.pc_limite}. O convênio ainda está "${s.situacao_convenio}".`}>
        prestação de contas vencida há {Math.abs(s.pc_dias)}d</Selo>);
    } else if (s.pc_dias <= 90) {
      out.push(<Selo key="pc" tom="atencao" title={`Prazo da prestação de contas: ${s.pc_limite}`}>
        prestação de contas em {s.pc_dias}d</Selo>);
    }
  }
  if (s.dias_sem_desembolso != null && s.dias_sem_desembolso >= 180) {
    out.push(<Selo key="des" tom={s.dias_sem_desembolso >= 365 ? "critico" : "atencao"}
                   title="Convênio em execução com saldo a desembolsar">
      {s.nunca_desembolsou ? `nenhum desembolso em ${s.dias_sem_desembolso}d` : `sem desembolso há ${s.dias_sem_desembolso}d`}
    </Selo>);
  }
  if (s.prorrogada) {
    out.push(<Selo key="prorr" title={`Vigência original: ${s.vigencia_original}`}>vigência prorrogada</Selo>);
  }
  if (s.execucao_fisica_pct != null) {
    out.push(<Selo key="obra" title="Resumo físico-financeiro publicado pelo TransfereGov">
      obra {String(s.execucao_fisica_pct).replace(".", ",")}% executada</Selo>);
  }
  return <>{out}</>;
}

// ---------------------------------------------------------------------------
// Canceladas (tela de Rejeitadas)
// ---------------------------------------------------------------------------
interface Cancelada {
  numero_proposta: string; proponente?: string | null; natureza_juridica?: string | null;
  municipal?: boolean; objeto?: string | null; orgao?: string | null; valor_global?: number | null;
  dt_proposta?: string | null; modalidade?: string | null;
}

export function BlocoCanceladas({ municipioId }: { municipioId: string | number }) {
  const [dados, setDados] = useState<{ items: Cancelada[]; total: number; fora_da_prefeitura: number } | null>(null);
  const [aberto, setAberto] = useState(false);
  useEffect(() => {
    let vivo = true;
    api.get(`/transferegov/canceladas`, { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setDados(r.data); })
      .catch(() => { if (vivo) setDados(null); });
    return () => { vivo = false; };
  }, [municipioId]);
  if (!dados || dados.total === 0) return null;
  return (
    <Bloco className="p-3">
      <button type="button" onClick={() => setAberto(!aberto)} className="text-left" aria-expanded={aberto}>
        <BlocoHead titulo={`Propostas canceladas · ${dados.total}`}
          sub={`dado aberto do TransfereGov (arquivo próprio de canceladas)${dados.fora_da_prefeitura
            ? ` · ${dados.fora_da_prefeitura} não ${dados.fora_da_prefeitura > 1 ? "são" : "é"} da prefeitura` : ""}`}
          className={aberto ? undefined : "mb-0"} />
      </button>
      {aberto && (
        <Lista>
          {dados.items.map((c) => (
            <ItemLinha key={c.numero_proposta} titulo={c.objeto || "Sem objeto informado"}
              meta={<>
                <Selo tom="neutro">Cancelada</Selo>
                {c.municipal === false && <Selo tom="atencao" title={c.natureza_juridica || undefined}>não é da prefeitura</Selo>}
                {c.orgao && <span className="truncate">{c.orgao}</span>}
                <span className="font-mono">· prop {c.numero_proposta}</span>
              </>}>
              <Campos campos={[
                { rotulo: "Proponente", valor: txt(c.proponente) },
                { rotulo: "Data da proposta", valor: txt(c.dt_proposta) },
                { rotulo: "Modalidade", valor: txt(c.modalidade) },
                { rotulo: "Valor global", valor: c.valor_global != null ? moeda(c.valor_global) : "—" },
              ]} />
            </ItemLinha>
          ))}
        </Lista>
      )}
    </Bloco>
  );
}
