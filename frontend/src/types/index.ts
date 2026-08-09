export interface User {
  id: number;
  email: string;
  name: string;
  role: string;
  active: boolean;
  must_change_password?: boolean;
  // null = acesso TOTAL (super-admin). Lista = o escopo daquela pessoa.
  //
  // Ate este incremento, `null` tambem chegava para todo `role === "admin"`, e
  // era assim que um administrador do cliente via tudo. O papel deixou de
  // conceder: agora o admin recebe a lista dele como qualquer outro, e so a
  // Alavank (dona da plataforma) continua sem limite.
  telas?: string[] | null;
  municipio_ids?: number[] | null;
  // As duas colunas que substituiram o papel onde ele de fato decidia poder.
  // Opcionais porque a tela precisa continuar de pe contra uma API anterior a
  // elas — ver `lib/conta.ts`, que faz a leitura com reserva.
  super_admin?: boolean | null;
  somente_leitura?: boolean | null;
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
  total_convenios_estadual: number;
  total_voluntarias: number;       // propostas TransfereGov Voluntarias
  valor_total_estadual: number;
  valor_total_federal: number;     // soma valor_global/repasse das Voluntarias
  alertas_vigencia: number;        // 120 dias (estadual + voluntarias)
  alertas_vigencia_60d: number;    // 60 dias (critico)
  alertas_prestacao_contas: number; // vencidos ha +90 dias (total estadual + federal)
  alertas_prestacao_contas_estadual: number; // SIGCON vencidos ha +90 dias
  alertas_prestacao_contas_federal: number;  // Voluntarias vencidas ha +90 dias
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
  fonte?: string;
  tipo_programa?: string;
  banco?: string;
  agencia?: string;
  conta_corrente?: string;
  saldo_bancario?: number;
  dt_saldo?: string;
  nr_sei?: string;
  dt_empenho?: string;
  dt_desembolso?: string;
  // SIGCON tracking
  nr_proposta?: string;
  nr_plano_trabalho?: string;
  nr_instrumento?: string;
  nr_siafi?: string;
}

export interface ConvenioList {
  items: Convenio[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
  /** Frescor da coleta SIGCON do município filtrado (null = sem registro ou
   *  coleta falhando; ver coleta_falhas). */
  coleta_em?: string | null;
  /** Falhas consecutivas de login/scrape — >0 = avisar em vez de datar. */
  coleta_falhas?: number;
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
