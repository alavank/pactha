"use client";

import React, { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { X } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/utils";

interface WorkflowStep {
  label: string;
  completed: boolean;
  current: boolean;
}

interface ConvenioDetail {
  id: number;
  esfera: string;
  nr_convenio_publicado?: string;
  nr_siafi?: string;
  nr_proposta?: string;
  nr_plano_trabalho?: string;
  nr_instrumento?: string;
  status?: string;
  dt_assinatura?: string;
  dt_publicacao?: string;
  data_criacao?: string;
  dias_vigencia_atual?: number;
  vigencia_inicial?: string;
  vigencia_atual?: string;
  dias_restantes?: number;
  dias_restantes_label?: string;
  titulo?: string;
  objetivo?: string;
  prestacao_contas?: string;
  concedente_orgao?: string;
  convenente_nome?: string;
  municipio_nome?: string;
  tipo_convenente?: string;
  valor_concedente?: number;
  valor_contrapartida?: number;
  valor_total?: number;
  valor_repasse?: number;
  valor_dotacao_complementar?: number | string;
  responsaveis?: string;
  proposta_vigencia?: string;
  fase_etapa_status?: string;
  setor?: string;
  qt_alteracoes?: number;
  ano?: number;
  tp_instrumento?: string;
  fonte?: string;
  workflow?: { current_index: number; steps: WorkflowStep[] };
}

interface Props {
  conv: { id: number; esfera: string } | null;
  onClose: () => void;
}

export default function ConvenioDetailModal({ conv, onClose }: Props) {
  const [detail, setDetail] = useState<ConvenioDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!conv) return;
    setLoading(true);
    setDetail(null);
    api
      .get<ConvenioDetail>(`/convenios/${conv.esfera}/${conv.id}`)
      .then((res) => setDetail(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [conv]);

  if (!conv) return null;
  const d = detail;

  return (
    <Dialog open={!!conv} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="!max-w-[960px] !w-[96vw] sm:!max-w-[960px] max-h-[92vh] overflow-y-auto p-3">
        <DialogTitle className="sr-only">Detalhes do Convênio</DialogTitle>
        <div className="relative">
          <button onClick={onClose} className="absolute right-0 top-0 text-gray-400 hover:text-gray-600 z-10" aria-label="Fechar">
            <X className="size-5" />
          </button>

          {loading && <div className="py-12 text-center text-gray-500">Carregando...</div>}

          {d && (
            <>
              {/* Workflow */}
              {d.workflow && d.workflow.steps && (
                <div className="mb-3 mt-1 overflow-x-auto">
                  <div className="flex items-start gap-0.5 min-w-max pb-1">
                    {d.workflow.steps.map((s, i) => (
                      <React.Fragment key={i}>
                        <div className="flex flex-col items-center text-center" style={{ width: 80 }} title={s.label}>
                          <div className="text-[8px] font-semibold uppercase mb-1 text-gray-700 leading-tight" style={{ minHeight: 32 }}>
                            {s.label}
                          </div>
                          <div className={`rounded-full ${s.current ? "size-4" : "size-3"} ${
                            s.completed ? "bg-blue-500" : "bg-gray-300"
                          } ${s.current ? "ring-2 ring-blue-300" : ""}`} />
                        </div>
                        {i < d.workflow!.steps.length - 1 && (
                          <div className={`h-0.5 mt-[32px] flex-1 min-w-1 ${
                            s.completed && d.workflow!.steps[i + 1].completed ? "bg-blue-500" : "bg-gray-300"
                          }`} />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )}

              <h2 className="text-center text-base font-bold mb-2">
                {d.tp_instrumento === "Transferência Especial" ? "Plano de Trabalho - Transferência Especial" : "Convênio"}
              </h2>

              {/* Bloco compacto: 6 colunas para max densidade */}
              <div className="bg-orange-50 border border-orange-200 rounded p-2.5 text-[11px]">
                {/* Identificadores principais */}
                <Grid cols={6}>
                  <Field label="Nº Convênio Publ." value={d.nr_convenio_publicado || "-"} highlight mono span={2} />
                  <Field label="Status" value={d.status || "-"} span={2} />
                  <Field label="Nº SIAFI" value={d.nr_siafi || "-"} mono />
                  <Field label="Data Criação" value={formatDate(d.data_criacao) || formatDate(d.dt_publicacao) || "-"} />
                </Grid>

                <hr className="my-2 border-orange-200" />

                {/* Datas + vigência */}
                <Grid cols={6}>
                  <Field label="Data Assinatura" value={formatDate(d.dt_assinatura) || "-"} />
                  <Field label="Data Publicação" value={formatDate(d.dt_publicacao) || "-"} />
                  <Field label="Dias Vigência Atual" value={d.dias_vigencia_atual?.toString() || "-"} />
                  <Field
                    label="Vigência Atual"
                    value={d.vigencia_inicial && d.vigencia_atual
                      ? `${formatDate(d.vigencia_inicial)} → ${formatDate(d.vigencia_atual)}`
                      : "-"}
                    span={2}
                  />
                  <Field
                    label="Dias Restantes"
                    value={d.dias_restantes_label || (d.dias_restantes != null ? `${d.dias_restantes}d` : "-")}
                    valueClass={d.dias_restantes_label === "VENCIDO" ? "text-red-600 font-bold" : ""}
                  />
                </Grid>

                <hr className="my-2 border-orange-200" />

                {/* Título + Prestação */}
                <Grid cols={6}>
                  <Field label="Título" value={d.titulo || "-"} span={4} fullValue />
                  <Field label="Prestação de Contas" value={d.prestacao_contas || "-"} span={2} />
                </Grid>

                <hr className="my-2 border-orange-200" />

                {/* Concedente + convenente + municipio */}
                <Grid cols={6}>
                  <Field label="Concedente/Órgão" value={d.concedente_orgao || "-"} span={3} />
                  <Field label="Convenente / OSC" value={d.convenente_nome || "-"} span={2} />
                  <Field label="Município" value={d.municipio_nome || "-"} />
                </Grid>
                <Grid cols={6}>
                  <Field label="Tipo Convenente" value={d.tipo_convenente || "-"} span={2} />
                  <Field label="Responsável(is)" value={d.responsaveis || "-"} span={2} />
                  <Field label="Setor" value={d.setor || "-"} span={2} />
                </Grid>

                <hr className="my-2 border-orange-200" />

                {/* Valores */}
                <Grid cols={6}>
                  <Field label="Valor Concedente" value={formatCurrency(d.valor_concedente ?? d.valor_repasse ?? d.valor_total)} mono />
                  <Field label="Valor Contrapartida" value={formatCurrency(d.valor_contrapartida) || "R$ 0,00"} mono />
                  <Field
                    label="Valor Dotação Compl."
                    value={typeof d.valor_dotacao_complementar === "number"
                      ? formatCurrency(d.valor_dotacao_complementar)
                      : (d.valor_dotacao_complementar || "R$ 0,00")}
                    mono
                  />
                  <Field label="Valor Total" value={formatCurrency(d.valor_total)} mono />
                  <Field label="Proposta Vigência" value={d.proposta_vigencia || "-"} />
                  <Field label="Qt. Alterações" value={d.qt_alteracoes?.toString() || "0"} />
                </Grid>

                <hr className="my-2 border-orange-200" />

                {/* Tracking SIGCON + fase */}
                <Grid cols={6}>
                  <Field label="Nº Proposta" value={d.nr_proposta || "-"} highlight mono />
                  <Field label="Nº Plano Trabalho" value={d.nr_plano_trabalho || "-"} highlight mono />
                  <Field label="Nº Instrumento" value={d.nr_instrumento || "-"} highlight mono />
                  <Field label="Tipo Instrumento" value={d.tp_instrumento || "-"} />
                  <Field label="Fonte" value={d.fonte || "-"} />
                  <Field label="Ano" value={d.ano?.toString() || "-"} />
                </Grid>

                {d.fase_etapa_status && d.fase_etapa_status !== d.status && (
                  <>
                    <hr className="my-2 border-orange-200" />
                    <Grid cols={6}>
                      <Field label="Fase-Etapa-Status" value={d.fase_etapa_status} span={6} fullValue />
                    </Grid>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Grid({ cols, children }: { cols: number; children: React.ReactNode }) {
  const gridClass = cols === 6 ? "grid-cols-6" : cols === 4 ? "grid-cols-4" : "grid-cols-3";
  return <div className={`grid ${gridClass} gap-x-3 gap-y-2`}>{children}</div>;
}

function Field({
  label,
  value,
  highlight,
  mono,
  valueClass = "",
  span,
  fullValue,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  mono?: boolean;
  valueClass?: string;
  span?: number;
  fullValue?: boolean;
}) {
  const spanClass = span === 2 ? "col-span-2" : span === 3 ? "col-span-3" : span === 4 ? "col-span-4" : span === 5 ? "col-span-5" : span === 6 ? "col-span-6" : "";
  return (
    <div className={`min-w-0 ${spanClass}`} title={`${label}: ${value}`}>
      <div className="text-[9.5px] font-semibold text-gray-600 leading-tight uppercase tracking-tight">{label}</div>
      <div className={`text-[11px] mt-0.5 ${mono ? "font-mono" : ""} ${highlight ? "inline-block bg-orange-200 px-1.5 py-0.5 rounded text-[10px]" : ""} ${!fullValue ? "truncate" : ""} ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}
