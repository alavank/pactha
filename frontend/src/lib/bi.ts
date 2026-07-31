import api from "./api";

// Tipos + fetchers do Painel de Indicadores (BI) — backend routers/bi.py (/api/bi/*).
// Escopo: municipioId = null => CONSOLIDADO (omite o param, backend usa o escopo do
// usuario); municipioId = number => 1 municipio.

export interface Municipio {
  id: number;
  nome: string;
  ibge_code: string;
  uf: string;
  active: boolean;
}

export interface BiKpis {
  total_convenios_estadual: number;
  total_voluntarias: number;
  valor_total_estadual: number;
  valor_total_federal: number;
  alertas_vigencia: number;
  alertas_vigencia_60d: number;
  alertas_prestacao_contas: number;
  alertas_prestacao_contas_estadual: number;
  alertas_prestacao_contas_federal: number;
  municipios_count: number;
}

export interface CaucPorMunicipio {
  municipio_id: number;
  nome: string;
  regular: boolean | null;
  pendencias: number;
  pendencias_codigos: string[];
}

// Consolidado (>1 municipio) — rollup do CAUC.
export interface SemaforoRollup {
  total_municipios: number;
  com_dados: number;
  regulares: number;
  com_pendencia: number;
  pendencias_total: number;
  por_municipio: CaucPorMunicipio[];
}

export interface CaucItem {
  codigo: string;
  grupo: string;
  label: string;
  valor: string;
  tipo: "regular" | "pendente" | "na";
  status: string;
}

// Municipio unico — resposta de fetch_cauc_situacao.
export interface SemaforoSingle {
  tem_dados: boolean;
  regular?: boolean | null;
  pendencias?: number;
  pendencias_codigos?: string[];
  itens?: CaucItem[];
  nome?: string;
  atualizado_em?: string | null;
}

export type Semaforo = SemaforoRollup | SemaforoSingle;

export function isRollup(s: Semaforo): s is SemaforoRollup {
  return (s as SemaforoRollup).por_municipio !== undefined;
}

export interface RankingItem {
  nome_normalizado: string;
  nome_display: string;
  total_lancamentos: number;
  valor_total: number;
  municipios: string[];
  por_fonte: Record<string, number>;
}

export interface TimelineItem {
  id: number;
  fonte: string;
  ref: string | null;
  orgao: string | null;
  objeto: string | null;
  status_anterior: string | null;
  status_novo: string | null;
  changed_at: string | null;
}

export interface Saude {
  divida_atual: number;
  pago: number;
  inicial: number;
}

export interface ExecucaoItem {
  id: number;
  municipio: string | null;
  numero: string | null;
  objeto: string | null;
  situacao: string | null;
  valor: number;
  repassado: number;
  pct_repassado: number;
  vigencia_ate: string | null;
  orgao: string | null;
  dias_restantes: number | null;
}

export interface Execucao {
  itens: ExecucaoItem[];
  total: number;
  valor_total: number;
  valor_repassado?: number;
}

export interface SemaforoCagec {
  tem_dados: boolean;
  entidades?: number;
  regulares?: number;
  irregulares?: number;
  municipios_com_irregularidade?: number;
  /** Rótulo cru do portal quando há uma única entidade (ex.: "Irregular"). */
  situacao?: string | null;
  quem?: Array<{ nome: string | null; tipo: string | null; principal: boolean; situacao: string | null }>;
}

export interface Overview {
  /** Regularidade ESTADUAL (MG). Independente do CAUC: regular na União não
   *  é regular em Minas, e a estadual trava até parcela de convênio assinado. */
  semaforo_cagec?: SemaforoCagec;
  consolidado: boolean;
  municipios_count: number;
  municipio_ids: number[];
  ano: number | null;
  anos: number[];
  kpis: BiKpis;
  execucao: Execucao;
  semaforo: Semaforo;
  saude: Saude | null;
  top_parlamentares: RankingItem[];
  ultimas_mudancas: TimelineItem[];
  ttl: number;
}

export interface AlertaVigencia {
  id: number;
  esfera: string;
  nr_sigcon: string | null;
  nr_convenio?: string | null;
  objeto: string | null;
  orgao_concedente: string | null;
  dt_fim_vigencia: string | null;
  dias_restantes: number;
  valor_total: number | null;
  situacao: string | null;
}

export interface DocumentoVencendo {
  municipio_id: number;
  municipio: string | null;
  /** "CAUC" (federal) ou "CAGEC" (estadual/MG). */
  esfera: string;
  /** Só no CAGEC e só quando NÃO é a prefeitura: o CAGEC tem um cadastro por
   *  entidade (Fundo Municipal de Saúde, FMAS…) e cada um trava apenas o SEU
   *  convênio. Sem isto, o prazo do fundo era lido como se fosse do município. */
  entidade?: string | null;
  codigo: string;
  label: string;
  validade: string;
  dias_restantes: number;
}

export interface Alertas {
  /** Certidões vencendo em até 30 dias — só prazos reais (o backend descarta
   *  as datas que são apenas cadência de atualização do extrato do CAUC). */
  documentos?: DocumentoVencendo[];
  vigencia: AlertaVigencia[];
  prestacao: AlertaVigencia[];
  execucao: Execucao;
}

// ---- abas (1 request = 1 aba inteira) ----

export interface Rollup {
  label: string;
  qtd: number;
  valor: number;
}

export interface ConvenioEstadualItem {
  id: number;
  municipio: string | null;
  numero: string | null;
  objeto: string | null;
  situacao: string | null;
  valor: number;
  repassado: number;
  orgao: string | null;
  ano: number | null;
  vigencia_ate: string | null;
  etapa: string | null;
}

export interface EmendaEstadualItem {
  id: number;
  municipio: string | null;
  numero: string | null;
  parlamentar: string | null;
  destinacao: string | null;
  finalidade: string | null;
  valor: number;
  situacao: string | null;
  orgao: string | null;
  ano: number | null;
  grupo_despesa: string | null;
}

export interface AbaEstaduais {
  convenios: {
    total: number;
    valor_total: number;
    valor_repassado: number;
    em_execucao: number;
    por_situacao: Rollup[];
    por_orgao: Rollup[];
    itens: ConvenioEstadualItem[];
  };
  emendas: {
    total: number;
    valor_total: number;
    por_situacao: Rollup[];
    por_orgao: Rollup[];
    itens: EmendaEstadualItem[];
  };
  por_ano: Array<{ ano: number; qtd: number; valor: number }>;
}

export interface VoluntariaItem {
  id: number;
  municipio: string | null;
  numero: string;
  instrumento: string | null;
  objeto: string | null;
  situacao: string | null;
  valor: number;
  repasse: number;
  orgao: string | null;
  parlamentar: string | null;
  vigencia_de: string | null;
  vigencia_ate: string | null;
  programa: string | null;
  ano: number | null;
}

export interface AbaTransfereGov {
  voluntarias: {
    total: number;
    valor_total: number;
    valor_repasse: number;
    em_execucao: number;
    por_situacao: Rollup[];
    por_orgao: Rollup[];
    itens: VoluntariaItem[];
  };
  pac: {
    total: number;
    valor_total: number;
    por_situacao: Rollup[];
    por_orgao: Rollup[];
    itens: Array<{
      id: number;
      municipio: string | null;
      numero: string;
      programa: string | null;
      situacao: string | null;
      valor: number;
      parlamentar: string | null;
      objeto: string | null;
      ano: number | null;
    }>;
  };
  em_execucao: VoluntariaItem[];
  por_ano: Array<{ ano: number; qtd: number; valor: number }>;
}

export interface Lancamento {
  fonte: "emenda_estadual" | "sigcon" | "voluntaria";
  numero: string | null;
  destinacao: string | null;
  finalidade: string | null;
  valor: number;
  situacao: string | null;
  orgao: string | null;
  ano: number | null;
  municipio: string | null;
  vigencia_ate?: string | null;
}

export interface ParlamentarDetalhe {
  nome: string;
  nome_normalizado: string;
  valor_total: number;
  total_lancamentos: number;
  municipios: string[];
  por_fonte: Record<string, number>;
  lancamentos: Lancamento[];
  lancamentos_ocultos: number;
}

export interface AbaParlamentares {
  itens: ParlamentarDetalhe[];
  total: number;
  valor_total: number;
  anos: number[];
}

export interface CaucItemDetalhe {
  codigo: string;
  grupo: string;
  label: string;
  valor: string;
  tipo: "regular" | "pendente" | "na";
  status: string;
}

export interface AbaDocumentos {
  cauc: {
    por_municipio: Array<{
      municipio_id: number;
      nome: string | null;
      regular: boolean | null;
      pendencias: number;
      pendencias_codigos: string[];
      itens_pendentes: CaucItemDetalhe[];
      itens_regulares: CaucItemDetalhe[];
      /** TODAS as exigências, com grupo e tipo — inclusive as "não exigidas".
       *  Opcional porque uma API mais antiga não manda (ver AbaDocumentosView,
       *  que cai de volta em pendentes+regulares). */
      itens?: CaucItemDetalhe[];
      total_itens: number;
      data_pesquisa: string | null;
      atualizado_em: string | null;
    }>;
    total_municipios: number;
    com_dados: number;
    regulares: number;
    pendencias_total: number;
  };
  /** CAGEC = regularidade ESTADUAL (MG), coletada do CRC público do portal do
   *  CAGEC (por CNPJ, sem credencial). Mesmo formato do CAUC; `disponivel:
   *  false` só quando o município ainda não foi coletado. */
  cagec: {
    disponivel: boolean;
    motivo: string;
    por_municipio: Array<{
      municipio_id: number;
      nome: string | null;
      regular: boolean | null;
      situacao: string | null;
      validade: string | null;
      itens: CaucItemDetalhe[];
      pendencias: number;
      data_pesquisa: string | null;
    }>;
  };
}

export interface SismobObraResumo {
  proposta_id: number;
  municipio: string | null;
  estabelecimento: string | null;
  programa: string | null;
  situacao?: string | null;
  percentual: number | null;
  severidade?: string;
  /** UMA frase por obra: o painel precisa ser lido de longe. O detalhe
   *  completo fica na tela do módulo. */
  problema?: string;
  problemas?: number;
  valor: number;
}

export interface AbaSismob {
  total: number;
  totais: {
    obras: number; vivas: number; concluidas: number; canceladas: number;
    valor_proposta: number; repasse_total: number; repasse_parado: number;
    com_prazo_vencido: number;
  };
  acao: SismobObraResumo[];
  execucao: SismobObraResumo[];
  por_situacao: Array<{ label: string; qtd: number; valor: number }>;
  por_programa: Array<{ label: string; qtd: number; valor: number }>;
  /** Sempre true: obra em aberto e obrigacao do presente, entao esta aba
   *  ignora o seletor de periodo do Painel. A tela avisa isso ao gestor —
   *  senao "troquei o periodo e nada mudou" e lido como aba travada. */
  sem_filtro_periodo?: boolean;
}

export interface AbaFns {
  anos: number[];
  por_ano: Array<{
    ano: number;
    total: number;
    valor_proposta: number;
    valor_pago: number;
    valor_pagar: number;
  }>;
  itens: Array<{
    tipo_proposta: string | null;
    tipo_recurso: string | null;
    nu_processo: string | null;
    valor_proposta: number;
    valor_pago: number;
    valor_pagar: number;
    parlamentares: unknown[];
    ano: number;
    municipio: string;
  }>;
  total: number;
  totais: { valor_proposta: number; valor_pago: number; valor_pagar: number };
  disponivel: boolean;
  erros: string[];
}

export interface Insights {
  aba: string;
  mensagens: string[];
  disponivel: boolean;
  fonte?: "ia" | "template";
}

export interface Narrativa {
  texto: string | null;
  disponivel: boolean;
  cache?: boolean;
}

// param de escopo -> query. null = consolidado (omite municipio_id).
function scopeParams(municipioId: number | null, extra: Record<string, unknown> = {}) {
  return municipioId != null ? { municipio_id: municipioId, ...extra } : { ...extra };
}

/** Periodo -> query. Vazio = todos os anos (nao manda o param).
 *  O axios serializa array como `anos=2021&anos=2022`, que e o formato que o
 *  FastAPI espera para `Optional[list[int]] = Query(None)`. */
function periodoParams(anos?: number[]) {
  return anos && anos.length ? { anos } : {};
}

// ---- fetchers ----

export async function getMunicipios(): Promise<Municipio[]> {
  const { data } = await api.get<Municipio[]>("/municipios");
  return Array.isArray(data) ? data : [];
}

export async function getOverview(
  municipioId: number | null,
  anos?: number[],
  live = false
): Promise<Overview> {
  const { data } = await api.get<Overview>("/bi/overview", {
    params: scopeParams(municipioId, { ...periodoParams(anos), live }),
  });
  return data;
}

export async function getAlertas(municipioId: number | null, anos?: number[]): Promise<Alertas> {
  const { data } = await api.get<Alertas>("/bi/alertas", {
    params: scopeParams(municipioId, periodoParams(anos)),
  });
  return data;
}

export async function getParlamentares(
  municipioId: number | null,
  anos?: number[],
  live = false
): Promise<{ items: RankingItem[]; total?: number }> {
  const { data } = await api.get("/bi/parlamentares", {
    params: scopeParams(municipioId, { ...periodoParams(anos), live }),
  });
  return data;
}

// ---- abas ----

export async function getAbaParlamentares(
  municipioId: number | null,
  anos?: number[]
): Promise<AbaParlamentares> {
  const { data } = await api.get<AbaParlamentares>("/bi/parlamentares/detalhe", {
    params: scopeParams(municipioId, periodoParams(anos)),
  });
  return data;
}

export async function getAbaEstaduais(
  municipioId: number | null,
  anos?: number[]
): Promise<AbaEstaduais> {
  const { data } = await api.get<AbaEstaduais>("/bi/estaduais", {
    params: scopeParams(municipioId, periodoParams(anos)),
  });
  return data;
}

export async function getAbaTransfereGov(
  municipioId: number | null,
  anos?: number[]
): Promise<AbaTransfereGov> {
  const { data } = await api.get<AbaTransfereGov>("/bi/transferegov", {
    params: scopeParams(municipioId, periodoParams(anos)),
  });
  return data;
}

export async function getAbaDocumentos(municipioId: number | null): Promise<AbaDocumentos> {
  const { data } = await api.get<AbaDocumentos>("/bi/documentos", {
    params: scopeParams(municipioId),
  });
  return data;
}

export async function getAbaSismob(municipioId: number | null, anos?: number[]): Promise<AbaSismob> {
  const { data } = await api.get<AbaSismob>("/bi/sismob", {
    params: scopeParams(municipioId, periodoParams(anos)),
  });
  return data;
}

export async function getAbaFns(
  municipioId: number | null,
  anos?: number[]
): Promise<AbaFns> {
  const { data } = await api.get<AbaFns>("/bi/fns", {
    params: scopeParams(municipioId, periodoParams(anos)),
  });
  return data;
}

export async function getInsights(
  aba: string,
  municipioId: number | null,
  anos?: number[]
): Promise<Insights> {
  const { data } = await api.get<Insights>("/bi/insights", {
    params: scopeParams(municipioId, { aba, ...periodoParams(anos) }),
  });
  return data;
}

export async function getTimeline(
  municipioId: number | null,
  days = 30,
  limit = 100
): Promise<{ items: TimelineItem[]; total: number }> {
  const { data } = await api.get("/bi/timeline", {
    params: scopeParams(municipioId, { days, limit }),
  });
  return data;
}

export async function getSemaforo(municipioId: number | null): Promise<Semaforo> {
  const { data } = await api.get<Semaforo>("/bi/semaforo", {
    params: scopeParams(municipioId),
  });
  return data;
}

export async function getNarrativa(
  municipioId: number | null,
  anos?: number[],
  kind = "resumo"
): Promise<Narrativa> {
  const { data } = await api.get<Narrativa>("/bi/narrativa", {
    params: scopeParams(municipioId, { ...periodoParams(anos), kind }),
  });
  return data;
}

// ---- Modo Tela: filtro do usuario + links publicos ----
//
// O filtro vive no SERVIDOR (e nao so no BroadcastChannel) porque a TV costuma
// ser OUTRO APARELHO — e entre aparelhos o canal do navegador nao existe.

export interface FiltroTela {
  scope: string;
  anos: number[];
  aba: string | null;
}

export async function getTelaFiltros(): Promise<FiltroTela> {
  const { data } = await api.get<FiltroTela>("/bi/tela-filtros");
  return data;
}

export async function putTelaFiltros(f: FiltroTela): Promise<void> {
  await api.put("/bi/tela-filtros", { scope: f.scope, anos: f.anos, aba: f.aba });
}

export type TipoLink = "tela" | "mobile";

export interface TelaLink {
  slug: string;
  caminho: string;
  /** 'tela' = TV (segue o filtro do dono) · 'mobile' = app (filtro próprio). */
  kind?: TipoLink;
  nome: string | null;
  criado_em?: string | null;
  expira_em?: string | null;
  revogado?: boolean;
  ultimo_acesso?: string | null;
}

export async function criarTelaLink(
  kind: TipoLink = "tela",
  nome?: string,
  dias = 365
): Promise<TelaLink> {
  const { data } = await api.post<TelaLink>("/bi/tela-links", { nome: nome || null, dias, kind });
  return data;
}

export async function listarTelaLinks(): Promise<TelaLink[]> {
  const { data } = await api.get<TelaLink[]>("/bi/tela-links");
  return data;
}

export async function revogarTelaLink(slug: string): Promise<void> {
  await api.delete(`/bi/tela-links/${encodeURIComponent(slug)}`);
}

/** Resolve o link publico: token do quiosque + filtro VIGENTE do dono.
 *  Sem autenticacao de proposito — o segredo e o proprio slug. */
export async function resolverTelaPub(
  slug: string
): Promise<{ token: string; scope: string; anos: number[]; aba: string | null; kind?: TipoLink }> {
  const { data } = await api.get(`/bi/tela-pub/${encodeURIComponent(slug)}`);
  return data;
}

// ---- push + preferencias ----
export interface Prefs {
  cauc_vencendo: boolean;
  /** Prazos e paralisações de obras da saúde (SISMOB). */
  obra_prazo: boolean;
  nova_emenda: boolean;
  prazo_prestacao: boolean;
  mudanca_status: boolean;
  vigencia_60d: boolean;
}
export async function getVapidKey(): Promise<string> {
  const { data } = await api.get<{ key: string }>("/bi/vapid-public-key");
  return data.key || "";
}
export async function getPrefs(): Promise<Prefs> {
  const { data } = await api.get<Prefs>("/bi/preferencias");
  return data;
}
export async function putPrefs(prefs: Prefs) {
  await api.put("/bi/preferencias", prefs);
}
