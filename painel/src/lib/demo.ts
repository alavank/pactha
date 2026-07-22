import type { Visao, Alertas } from "./painel";

// Panorama REAL do Monte Sião (puxado da API em 2026-07) usado como fallback quando
// o app roda sem sessão (preview) ou a API está fora. Rótulo "exemplo" na UI.
export const DEMO_VISAO: Visao = {
  kpis: {
    municipio: { id: 1, nome: "Monte Sião", ibge_code: "3143401", uf: "MG", active: true },
    total_convenios_estadual: 0,
    total_voluntarias: 135,
    valor_total_estadual: 0,
    valor_total_federal: 156004530.54,
    alertas_vigencia: 1,
    alertas_vigencia_60d: 0,
    alertas_prestacao_contas: 105,
    alertas_prestacao_contas_estadual: 0,
    alertas_prestacao_contas_federal: 105,
  },
  semaforo: { tem_dados: true, regular: true, pendencias: 0, pendencias_codigos: [] },
  saude: { divida_atual: 2157594.76, pago: 2363550.65, inicial: 4521145.41 },
  top_parlamentares: [
    { nome_normalizado: "JULIO DELGADO", nome_display: "Júlio Delgado", total_lancamentos: 9, valor_total: 3852757, municipios: ["Monte Sião"], por_fonte: { sigcon: 0, voluntaria: 6, emenda: 0, plano_acao: 3, pac: 0 } },
    { nome_normalizado: "LINCOLN PORTELA", nome_display: "Lincoln Portela", total_lancamentos: 5, valor_total: 2696454, municipios: ["Monte Sião"], por_fonte: { sigcon: 0, voluntaria: 2, emenda: 0, plano_acao: 3, pac: 0 } },
    { nome_normalizado: "DIMAS FABIANO", nome_display: "Dimas Fabiano", total_lancamentos: 7, valor_total: 2279560, municipios: ["Monte Sião"], por_fonte: { sigcon: 0, voluntaria: 5, emenda: 0, plano_acao: 2, pac: 0 } },
    { nome_normalizado: "RAFAEL SIMOES", nome_display: "Rafael Simões", total_lancamentos: 3, valor_total: 1691000, municipios: ["Monte Sião"], por_fonte: { sigcon: 0, voluntaria: 0, emenda: 0, plano_acao: 3, pac: 0 } },
    { nome_normalizado: "ODAIR CUNHA", nome_display: "Odair Cunha", total_lancamentos: 3, valor_total: 687500, municipios: ["Monte Sião"], por_fonte: { sigcon: 0, voluntaria: 2, emenda: 0, plano_acao: 1, pac: 0 } },
  ],
  ultimas_mudancas: [],
};

// Amostra REAL de alertas do Monte Sião (prestações vencidas + vigência).
function pc(objeto: string, orgao: string, dias: number): Alertas["prestacao"][number] {
  return { id: 0, esfera: "voluntaria", nr_sigcon: null, nr_convenio: null, objeto, orgao_concedente: orgao, dt_fim_vigencia: null, dias_restantes: dias, valor_total: null, situacao: null };
}
export const DEMO_ALERTAS: Alertas = {
  vigencia: [
    { id: 0, esfera: "voluntaria", nr_sigcon: "046137/2021", nr_convenio: "923250", objeto: "RECAPEAMENTO DE VIAS PÚBLICAS", orgao_concedente: "56000 - Ministério das Cidades", dt_fim_vigencia: "2026-11-15", dias_restantes: 116, valor_total: null, situacao: null },
  ],
  prestacao: [
    pc("CONSTRUÇÃO DE CRECHE ESCOLA TIPO II", "26298 - Fundo Nacional de Educação", -258),
    pc("IMPLEMENTAÇÃO DO PROJETO RENOVAR PARA MELHORAR", "55000 - Ministério do Desenvolvimento", -210),
    pc("PATRULHA MECANIZADA", "53000 - Ministério da Integração", -324),
    pc("PAVIMENTAÇÃO ASFÁLTICA – TRECHO MONTE SIÃO / JACUTINGA", "53000 - Ministério da Integração", -324),
    pc("AQUISIÇÃO DE MÁQUINAS E EQUIPAMENTOS AGRÍCOLAS", "22000 - Ministério da Agricultura", -448),
    pc("PAVIMENTAÇÃO RURAL", "53000 - Ministério da Integração", -463),
  ],
};

// Documentações estaduais/federais monitoradas — CAUC ativo hoje; as demais entram
// conforme os logins/fontes são ligados (SIGCON, FNS, Investe SUS, SISMOB, CAGEC).
export const DOCUMENTACOES = [
  { key: "cauc", nome: "CAUC", desc: "Regularidade fiscal federal", ativo: true },
  { key: "cagec", nome: "CAGEC", desc: "Cadastro de convenentes MG", ativo: false },
  { key: "sismob", nome: "SISMOB", desc: "Obras de saúde (MS)", ativo: false },
  { key: "investe_sus", nome: "Investe SUS", desc: "Repasses de saúde MG", ativo: false },
  { key: "fns", nome: "FNS", desc: "Fundo Nacional de Saúde", ativo: false },
];

// Nomes que NÃO são parlamentares (auto-atribuição do próprio município via PAC etc.).
export function ehParlamentarValido(nomeNorm: string, municipioNome: string): boolean {
  const n = (nomeNorm || "").toUpperCase();
  const m = (municipioNome || "").toUpperCase();
  if (!n) return false;
  if (n.includes("MUNICIPIO") || n.includes("PREFEITURA")) return false;
  if (m && n.includes(m.replace(/[^A-Z ]/g, "").trim())) return false;
  return true;
}
