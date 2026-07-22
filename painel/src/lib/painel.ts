import api from "./api";

// Tipos que espelham as respostas de /api/painel/* (backend routers/painel.py).

export interface Municipio {
  id: number;
  nome: string;
  ibge_code: string;
  uf: string;
  active: boolean;
}

export interface MunicipioSummary {
  municipio: Municipio;
  total_convenios_estadual: number;
  total_voluntarias: number;
  valor_total_estadual: number;
  valor_total_federal: number;
  alertas_vigencia: number;
  alertas_vigencia_60d: number;
  alertas_prestacao_contas: number;
  alertas_prestacao_contas_estadual: number;
  alertas_prestacao_contas_federal: number;
}

export interface RankingItem {
  nome_normalizado: string;
  nome_display: string;
  total_lancamentos: number;
  valor_total: number;
  municipios: string[];
  por_fonte: { sigcon: number; voluntaria: number; emenda: number; plano_acao: number; pac: number };
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

export interface CaucItem {
  codigo: string;
  grupo: string;
  label: string;
  valor: string;
  tipo: "regular" | "pendente" | "na";
  status: string;
}

export interface Semaforo {
  tem_dados: boolean;
  regular?: boolean | null;
  pendencias?: number;
  pendencias_codigos?: string[];
  itens?: CaucItem[];
  nome?: string;
  data_pesquisa?: string | null;
  atualizado_em?: string | null;
}

export interface Saude {
  divida_atual: number;
  pago: number;
  inicial: number;
}

export interface Visao {
  kpis: MunicipioSummary;
  semaforo: Pick<Semaforo, "tem_dados" | "regular" | "pendencias" | "pendencias_codigos">;
  saude?: Saude | null;
  top_parlamentares: RankingItem[];
  ultimas_mudancas: TimelineItem[];
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

// ---- fetchers ----

export async function getMunicipios(): Promise<Municipio[]> {
  const { data } = await api.get<Municipio[]>("/municipios");
  return data;
}

export async function getVisao(mid: number, ano?: number): Promise<Visao> {
  const { data } = await api.get<Visao>(`/painel/${mid}/visao`, { params: { ano } });
  return data;
}

export async function getSemaforo(mid: number): Promise<Semaforo> {
  const { data } = await api.get<Semaforo>(`/painel/${mid}/semaforo`);
  return data;
}

export async function getRanking(mid: number, ano?: number, live = false): Promise<{ items: RankingItem[]; total: number }> {
  const { data } = await api.get(`/painel/${mid}/ranking-parlamentares`, { params: { ano, live } });
  return data;
}

export async function getTimeline(mid: number, days = 30, limit = 100): Promise<{ items: TimelineItem[]; total: number }> {
  const { data } = await api.get(`/painel/${mid}/timeline`, { params: { days, limit } });
  return data;
}

export async function getAlertas(mid: number, ano?: number): Promise<Alertas> {
  const { data } = await api.get<Alertas>(`/painel/${mid}/alertas`, { params: { ano } });
  return data;
}

export interface Narrativa {
  texto: string | null;
  disponivel: boolean;
  cache?: boolean;
}
export async function getNarrativa(mid: number, ano?: number, kind = "resumo"): Promise<Narrativa> {
  const { data } = await api.get<Narrativa>(`/painel/${mid}/narrativa`, { params: { ano, kind } });
  return data;
}

// ---- push + preferências ----
export interface Prefs {
  cauc_vencendo: boolean;
  nova_emenda: boolean;
  prazo_prestacao: boolean;
  mudanca_status: boolean;
  vigencia_60d: boolean;
}
export async function getVapidKey(): Promise<string> {
  const { data } = await api.get<{ key: string }>("/painel/vapid-public-key");
  return data.key || "";
}
export async function pushSubscribe(sub: { municipio_id: number; endpoint: string; p256dh: string; auth: string; ua?: string }) {
  await api.post("/painel/push/subscribe", sub);
}
export async function pushUnsubscribe(endpoint: string) {
  await api.delete("/painel/push/subscribe", { params: { endpoint } });
}
export async function getPrefs(): Promise<Prefs> {
  const { data } = await api.get<Prefs>("/painel/preferencias");
  return data;
}
export async function putPrefs(prefs: Prefs) {
  await api.put("/painel/preferencias", prefs);
}

// ---- auth ----
export async function login(email: string, password: string) {
  const { data } = await api.post("/auth/login", { email, password });
  return data;
}
