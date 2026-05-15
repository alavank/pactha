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
  responsaveis?: string;
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

  const isOpen = !!conv;
  const d = detail;

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-6xl max-h-[90vh] overflow-y-auto">
        <DialogTitle className="sr-only">Detalhes do Convênio</DialogTitle>
        <div className="relative">
          <button
            onClick={onClose}
            className="absolute right-0 top-0 text-gray-400 hover:text-gray-600"
            aria-label="Fechar"
          >
            <X className="size-5" />
          </button>

          {loading && <div className="py-12 text-center text-gray-500">Carregando...</div>}

          {d && (
            <>
              {/* Workflow steps */}
              {d.workflow && d.workflow.steps && (
                <div className="mb-6 mt-2 overflow-x-auto">
                  <div className="flex items-start gap-1 min-w-max pb-2">
                    {d.workflow.steps.map((s, i) => (
                      <React.Fragment key={i}>
                        <div className="flex flex-col items-center text-center" style={{ width: 105 }}>
                          <div className="text-[9px] font-semibold uppercase mb-1.5 text-gray-700 leading-tight" style={{ minHeight: 38 }}>
                            {s.label}
                          </div>
                          <div
                            className={`rounded-full ${s.current ? "size-5" : "size-4"} ${
                              s.completed ? "bg-blue-500" : "bg-gray-300"
                            } ${s.current ? "ring-2 ring-blue-300" : ""}`}
                          />
                        </div>
                        {i < d.workflow!.steps.length - 1 && (
                          <div className={`h-0.5 mt-[42px] flex-1 min-w-2 ${
                            s.completed && d.workflow!.steps[i + 1].completed ? "bg-blue-500" : "bg-gray-300"
                          }`} />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )}

              <h2 className="text-center text-xl font-bold mb-4">
                {d.tp_instrumento === "Transferência Especial" ? "Plano de Trabalho - Transferência Especial" : "Convênio"}
              </h2>

              {/* Bloco principal (laranja claro) */}
              <div className="bg-orange-50 border border-orange-200 rounded p-5 space-y-3">
                <Row3>
                  <Field label="Número do Convênio Publicado:" value={d.nr_convenio_publicado || "-"} highlight />
                  <Field label="Status:" value={d.status || "-"} />
                  <Field label="Nº do SIAFI:" value={d.nr_siafi || "-"} />
                </Row3>
                <Row3>
                  <Field label="Data da Assinatura:" value={formatDate(d.dt_assinatura)} />
                  <Field label="Data de Publicação:" value={formatDate(d.dt_publicacao)} />
                  <div />
                </Row3>
                <Row3>
                  <Field label="Dias de Vigência Atual:" value={d.dias_vigencia_atual?.toString() || "-"} />
                  <Field
                    label="Vigência Atual:"
                    value={d.vigencia_inicial && d.vigencia_atual
                      ? `${formatDate(d.vigencia_inicial)} à ${formatDate(d.vigencia_atual)}`
                      : "-"}
                  />
                  <Field
                    label="Dias Restantes de Vigência:"
                    value={d.dias_restantes_label || (d.dias_restantes != null ? `${d.dias_restantes} dias` : "-")}
                    valueClass={d.dias_restantes_label === "VENCIDO" ? "text-red-600 font-bold" : ""}
                  />
                </Row3>

                <hr className="border-orange-200" />

                <div className="grid grid-cols-12 gap-4">
                  <div className="col-span-3 text-xs font-semibold text-gray-700">Título:</div>
                  <div className="col-span-6 text-xs">{d.titulo || "-"}</div>
                  <div className="col-span-3">
                    <div className="text-xs font-semibold text-gray-700">Prestação de Contas:</div>
                    <div className="text-xs">{d.prestacao_contas || "-"}</div>
                  </div>
                </div>

                <hr className="border-orange-200" />

                <Row3>
                  <Field label="Concedente/Órgão:" value={d.concedente_orgao || "-"} colSpan={2} />
                  <Field label="" value="" />
                </Row3>
                <Row3>
                  <Field label="Convenente / OSC Parceira:" value={d.convenente_nome || "-"} colSpan={2} />
                  <Field label="Município:" value={d.municipio_nome || "-"} />
                </Row3>
                <Row3>
                  <Field label="Tipo de Convenente:" value={d.tipo_convenente || "-"} colSpan={2} />
                  <div />
                </Row3>
                <Row3>
                  <Field label="Valor Concedente Atual:" value={formatCurrency(d.valor_concedente ?? d.valor_repasse ?? d.valor_total)} />
                  <Field label="Valor Contrapartida Atual:" value={formatCurrency(d.valor_contrapartida) || "R$ 0,00"} />
                  <Field label="Valor Total:" value={formatCurrency(d.valor_total)} />
                </Row3>

                {d.responsaveis && (
                  <>
                    <hr className="border-orange-200" />
                    <Row3>
                      <Field label="Responsável(is):" value={d.responsaveis} colSpan={3} />
                    </Row3>
                  </>
                )}

                <hr className="border-orange-200" />

                <Row3>
                  <Field label="Número da Proposta:" value={d.nr_proposta || "-"} highlight />
                  <Field label="Número do Plano de Trabalho:" value={d.nr_plano_trabalho || "-"} highlight />
                  <Field label="Quantidade de Alterações Concluídas:" value={d.qt_alteracoes?.toString() || "0"} />
                </Row3>
                <Row3>
                  <Field label="Tipo de Instrumento:" value={d.tp_instrumento || "-"} />
                  <Field label="Nº do Instrumento:" value={d.nr_instrumento || "-"} highlight />
                  <Field label="Fonte:" value={d.fonte || "-"} />
                </Row3>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Row3({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-3 gap-4">{children}</div>;
}

function Field({
  label,
  value,
  highlight,
  valueClass = "",
  colSpan,
}: {
  label: string;
  value: string;
  highlight?: boolean;
  valueClass?: string;
  colSpan?: number;
}) {
  return (
    <div className={colSpan === 2 ? "col-span-2" : colSpan === 3 ? "col-span-3" : ""}>
      <div className="text-xs font-semibold text-gray-700">{label}</div>
      <div className={`text-xs ${highlight ? "inline-block bg-orange-200 px-2 py-0.5 rounded font-mono" : ""} ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}
