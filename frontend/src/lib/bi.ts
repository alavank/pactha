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

export interface Overview {
  consolidado: boolean;
  municipios_count: number;
  municipio_ids: number[];
  ano: number | null;
  kpis: BiKpis;
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

export interface Alertas {
  vigencia: AlertaVigencia[];
  prestacao: AlertaVigencia[];
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

// ---- fetchers ----

export async function getMunicipios(): Promise<Municipio[]> {
  const { data } = await api.get<Municipio[]>("/municipios");
  return Array.isArray(data) ? data : [];
}

export async function getOverview(
  municipioId: number | null,
  ano?: number,
  live = false
): Promise<Overview> {
  const { data } = await api.get<Overview>("/bi/overview", {
    params: scopeParams(municipioId, { ano, live }),
  });
  return data;
}

export async function getAlertas(municipioId: number | null, ano?: number): Promise<Alertas> {
  const { data } = await api.get<Alertas>("/bi/alertas", {
    params: scopeParams(municipioId, { ano }),
  });
  return data;
}

export async function getParlamentares(
  municipioId: number | null,
  ano?: number,
  live = false
): Promise<{ items: RankingItem[]; total?: number }> {
  const { data } = await api.get("/bi/parlamentares", {
    params: scopeParams(municipioId, { ano, live }),
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
  ano?: number,
  kind = "resumo"
): Promise<Narrativa> {
  const { data } = await api.get<Narrativa>("/bi/narrativa", {
    params: scopeParams(municipioId, { ano, kind }),
  });
  return data;
}

// ---- kiosk (admin) ----
export async function criarKioskToken(
  municipioId: number | null,
  dias = 365
): Promise<{ token: string; escopo: string; user_email: string; municipio_id: number | null }> {
  const { data } = await api.post("/bi/kiosk-tokens", {
    municipio_id: municipioId,
    dias,
  });
  return data;
}

// ---- push + preferencias ----
export interface Prefs {
  cauc_vencendo: boolean;
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
