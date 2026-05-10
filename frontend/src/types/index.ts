export interface User {
  id: number;
  email: string;
  name: string;
  role: string;
  active: boolean;
  must_change_password?: boolean;
}

export interface Municipio {
  id: number;
  nome: string;
  ibge_code: string;
  uf: string;
  active: boolean;
}

export interface MunicipioSummary {
  municipio: Municipio;
  total_convenios_federal: number;
  total_convenios_estadual: number;
  valor_total_federal: number;
  valor_total_estadual: number;
  alertas_vigencia: number;
  editais_acompanhados: number;
}

export interface Convenio {
  id: number;
  esfera: string;
  nr_convenio?: string;
  nr_sigcon?: string;
  municipio_id: number;
  orgao_concedente?: string;
  objeto?: string;
  situacao?: string;
  valor_total?: number;
  valor_repasse?: number;
  valor_empenhado?: number;
  valor_desembolsado?: number;
  valor_contrapartida?: number;
  dt_inicio?: string;
  dt_fim_vigencia?: string;
  dias_restantes?: number;
  ano?: number;
  programa?: string;
  etapa_sigcon?: string;
  etapa_sigcon_nr?: number;
}

export interface ConvenioList {
  items: Convenio[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface ConvenioStats {
  total_convenios: number;
  total_ativos: number;
  valor_total: number;
  valor_empenhado: number;
  valor_desembolsado: number;
  por_situacao: Record<string, number>;
  por_esfera: Record<string, number>;
}

export interface AlertaVigencia {
  id: number;
  esfera: string;
  nr_convenio?: string;
  nr_sigcon?: string;
  objeto?: string;
  orgao_concedente?: string;
  dt_fim_vigencia?: string;
  dias_restantes: number;
  valor_total?: number;
  situacao?: string;
}

export interface Edital {
  id: number;
  titulo: string;
  orgao?: string;
  area?: string;
  esfera?: string;
  url?: string;
  dt_publicacao?: string;
  dt_encerramento?: string;
  valor_total?: number;
  resumo?: string;
  status: string;
  acompanhando?: boolean;
}

export interface EmendaPorDeputado {
  parlamentar_id: number;
  parlamentar_nome: string;
  partido?: string;
  total_valor: number;
  total_emendas: number;
  esfera?: string;
}

export interface BenchmarkMunicipio {
  municipio_id: number;
  municipio_nome: string;
  total_emendas: number;
  total_convenios: number;
  total_valor_convenios: number;
}

export interface PrestacaoContas {
  id: number;
  convenio_estadual_id?: number;
  convenio_federal_id?: number;
  municipio_id: number;
  etapa_atual: number;
  etapa_nome?: string;
  responsavel_id?: number;
  status: string;
  observacoes?: string;
  documentos: PrestacaoDocumento[];
  nr_convenio?: string;
  objeto?: string;
  esfera?: string;
  orgao_concedente?: string;
  valor_total?: number;
  dt_inicio?: string;
  dt_fim_vigencia?: string;
  dias_restantes?: number;
  ano?: number;
  situacao?: string;
}

export interface PrestacaoDocumento {
  id: number;
  documento_nome: string;
  enviado: boolean;
  dt_envio?: string;
  responsavel_id?: number;
  observacao?: string;
}
