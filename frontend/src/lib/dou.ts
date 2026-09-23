/* DOU federal — tipos e rótulos que a aba do Diário Oficial e o bloco do Radar
 * dividem. Um lugar só: se as duas telas nomeassem a mesma categoria de jeitos
 * diferentes, o gestor acharia que são atos diferentes.
 *
 * As chaves vêm de `backend/ingestion/dou_federal.py` (`categoria` e
 * `EVIDENCIAS`); `tests/test_dou_federal.py` confere que a tela conhece todas. */

export type CategoriaDou =
  | "emergencia" | "selecao" | "habilitacao" | "repasse"
  | "prazo" | "convenio" | "licitacao" | "outros";

export type EvidenciaDou = "orgao" | "ibge" | "cnpj" | "municipio" | "cidade";

export interface AtoDou {
  id: number;
  data_publicacao: string;
  secao: string | null;
  edicao: string | null;
  pagina: string | null;
  tipo_ato: string | null;
  orgao: string | null;
  titulo: string | null;
  ementa: string | null;
  categoria: CategoriaDou;
  evidencia: EvidenciaDou;
  trecho: string | null;
  url: string;
}

/** As quatro primeiras são de CAPTAÇÃO — as que viram alerta no Radar. */
export const CATEGORIA_DOU: Record<CategoriaDou, { label: string; captacao: boolean }> = {
  repasse: { label: "Repasse", captacao: true },
  habilitacao: { label: "Habilitação", captacao: true },
  selecao: { label: "Seleção", captacao: true },
  emergencia: { label: "Emergência", captacao: true },
  prazo: { label: "Prazo", captacao: false },
  convenio: { label: "Instrumento", captacao: false },
  licitacao: { label: "Licitação", captacao: false },
  outros: { label: "Outros", captacao: false },
};

/** Como o ato se liga ao município, dito para quem lê — e não o nome técnico. */
export const EVIDENCIA_DOU: Record<EvidenciaDou, string> = {
  orgao: "publicado pela prefeitura",
  ibge: "pelo código IBGE",
  cnpj: "pelo CNPJ da prefeitura",
  municipio: "citado como município",
  cidade: "citado como endereço",
};

/** "DO1_EXTRA_A" -> "Seção 1 · extra A". */
export function secaoDou(s?: string | null): string {
  const m = /^DO(\d)(?:_EXTRA_?([A-Z]))?/.exec((s || "").toUpperCase());
  if (!m) return s || "—";
  return `Seção ${m[1]}${m[2] ? ` · extra ${m[2]}` : ""}`;
}

/** Data pura do banco (DATE) em dd/mm/aaaa, lida como dia e não como instante. */
export function dataDou(iso?: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleDateString("pt-BR");
}
