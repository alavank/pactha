"use client";

import React, { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { X, Check } from "lucide-react";
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

function statusBadge(status?: string): string {
  const t = (status || "").toLowerCase();
  if (/aprovad|execu|vigor|conclu|\bpago\b/.test(t)) return "bg-success/15 text-success border-success/30";
  if (/rejeitad|anulad|cancelad|rescind|impedi/.test(t)) return "bg-error/15 text-error border-error/30";
  if (/an[aá]lise|complementa|pendente|cadastr|checklist|processo|empenhad|autorizad/.test(t)) return "bg-warning/15 text-warning border-warning/30";
  return "bg-base-200 text-base-content/70 border-base-300";
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

  const diasCls = !d
    ? ""
    : d.dias_restantes_label?.includes("PRESTACAO")
    ? "text-info font-bold"
    : d.dias_restantes_label?.startsWith("VENCIDO")
    ? "text-error font-bold"
    : d.dias_restantes != null && d.dias_restantes < 60
    ? "text-warning font-semibold"
    : "";

  return (
    <Dialog open={!!conv} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="!max-w-[900px] !w-[95vw] sm:!max-w-[900px] !block max-h-[92vh] overflow-y-auto overflow-x-hidden p-0 gap-0">
        <DialogTitle className="sr-only">Detalhes do Convênio</DialogTitle>

        {loading && <div className="py-16 text-center text-sm text-base-content/60">Carregando…</div>}

        {d && (
          <>
            {/* Header fixo */}
            <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-base-300 bg-base-100 px-5 py-4">
              <div className="min-w-0">
                <p className="text-[11px] font-medium uppercase tracking-wide text-base-content/50">
                  {d.tp_instrumento === "Transferência Especial" ? "Plano de Trabalho — Transf. Especial" : "Convênio"}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <span className="font-mono text-lg font-bold text-base-content">
                    {d.nr_convenio_publicado || d.nr_proposta || "-"}
                  </span>
                  {d.status && (
                    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${statusBadge(d.status)}`}>
                      {d.status}
                    </span>
                  )}
                  {d.fonte && <span className="text-xs text-base-content/50">{d.fonte}</span>}
                </div>
              </div>
              <button
                onClick={onClose}
                className="shrink-0 rounded-lg p-1 text-base-content/40 hover:bg-base-200 hover:text-base-content/70"
                aria-label="Fechar"
              >
                <X className="size-5" />
              </button>
            </div>

            <div className="space-y-6 p-5">
              {/* Workflow / stepper */}
              {d.workflow?.steps?.length ? (
                <div className="overflow-x-auto pb-1">
                  <div className="flex min-w-max items-start">
                    {d.workflow.steps.map((s, i) => (
                      <React.Fragment key={i}>
                        <div className="flex flex-col items-center" style={{ width: 92 }} title={s.label}>
                          <div
                            className={`flex size-6 items-center justify-center rounded-full text-[10px] font-bold ${
                              s.completed
                                ? "bg-primary text-primary-content"
                                : s.current
                                ? "bg-primary/15 text-primary ring-2 ring-primary"
                                : "bg-base-200 text-base-content/40"
                            }`}
                          >
                            {s.completed ? <Check className="size-3.5" /> : i + 1}
                          </div>
                          <div
                            className={`mt-1.5 px-1 text-center text-[9px] font-medium uppercase leading-tight ${
                              s.current ? "text-primary" : "text-base-content/55"
                            }`}
                            style={{ minHeight: 28 }}
                          >
                            {s.label}
                          </div>
                        </div>
                        {i < d.workflow!.steps.length - 1 && (
                          <div
                            className={`mt-3 h-0.5 min-w-4 flex-1 ${
                              s.completed && d.workflow!.steps[i + 1].completed ? "bg-primary" : "bg-base-300"
                            }`}
                          />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              ) : null}

              {/* Valores em destaque */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <ValueBox label="Valor Concedente" value={formatCurrency(d.valor_concedente ?? d.valor_repasse ?? d.valor_total)} />
                <ValueBox label="Contrapartida" value={formatCurrency(d.valor_contrapartida) || "R$ 0,00"} />
                <ValueBox
                  label="Dotação Compl."
                  value={typeof d.valor_dotacao_complementar === "number"
                    ? formatCurrency(d.valor_dotacao_complementar)
                    : d.valor_dotacao_complementar || "R$ 0,00"}
                />
                <ValueBox label="Valor Total" value={formatCurrency(d.valor_total)} accent />
              </div>

              {/* Identificação */}
              <Section title="Identificação">
                <Field label="Nº Convênio Publ." value={d.nr_convenio_publicado || "-"} mono />
                <Field label="Nº SIAFI" value={d.nr_siafi || "-"} mono />
                <Field label="Nº Proposta" value={d.nr_proposta || "-"} mono />
                <Field label="Nº Plano Trabalho" value={d.nr_plano_trabalho || "-"} mono />
                <Field label="Nº Instrumento" value={d.nr_instrumento || "-"} mono />
                <Field label="Tipo Instrumento" value={d.tp_instrumento || "-"} />
                <Field label="Fonte" value={d.fonte || "-"} />
                <Field label="Ano" value={d.ano?.toString() || "-"} />
              </Section>

              {/* Vigência */}
              <Section title="Vigência & Prazos">
                <Field label="Data Criação" value={formatDate(d.data_criacao) || formatDate(d.dt_publicacao) || "-"} />
                <Field label="Data Assinatura" value={formatDate(d.dt_assinatura) || "-"} />
                <Field label="Data Publicação" value={formatDate(d.dt_publicacao) || "-"} />
                <Field label="Dias Vigência Atual" value={d.dias_vigencia_atual?.toString() || "-"} />
                <Field
                  label="Vigência Atual"
                  value={d.vigencia_inicial && d.vigencia_atual ? `${formatDate(d.vigencia_inicial)} → ${formatDate(d.vigencia_atual)}` : "-"}
                  span={2}
                />
                <Field
                  label="Dias Restantes"
                  value={d.dias_restantes_label || (d.dias_restantes != null ? `${d.dias_restantes}d` : "-")}
                  valueClass={diasCls}
                />
                <Field label="Qt. Alterações" value={d.qt_alteracoes?.toString() || "0"} />
                <Field label="Prestação de Contas" value={d.prestacao_contas || "-"} span={2} />
                <Field label="Proposta Vigência" value={d.proposta_vigencia || "-"} span={2} />
              </Section>

              {/* Partes */}
              <Section title="Partes Envolvidas">
                <Field label="Concedente / Órgão" value={d.concedente_orgao || "-"} span={2} />
                <Field label="Convenente / OSC" value={d.convenente_nome || "-"} span={2} />
                <Field label="Município" value={d.municipio_nome || "-"} />
                <Field label="Tipo Convenente" value={d.tipo_convenente || "-"} />
                <Field label="Responsável(is)" value={d.responsaveis || "-"} span={2} />
                <Field label="Setor" value={d.setor || "-"} span={2} />
              </Section>

              {/* Objeto */}
              <Section title="Objeto">
                <Field label="Título" value={d.titulo || "-"} span={4} full />
                {d.fase_etapa_status && d.fase_etapa_status !== d.status && (
                  <Field label="Fase-Etapa-Status" value={d.fase_etapa_status} span={4} full />
                )}
              </Section>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-base-content/50">{title}</h3>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3.5 rounded-xl border border-base-300 bg-base-100 p-4 sm:grid-cols-4">
        {children}
      </div>
    </div>
  );
}

function ValueBox({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border p-3 ${accent ? "border-primary/30 bg-primary/5" : "border-base-300 bg-base-100"}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-base-content/50">{label}</div>
      <div className={`mt-1 break-words text-sm font-bold leading-tight ${accent ? "text-primary" : "text-base-content"}`}>
        {value}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
  valueClass = "",
  span,
  full,
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueClass?: string;
  span?: number;
  full?: boolean;
}) {
  const spanClass =
    span === 2 ? "col-span-2" : span === 3 ? "col-span-2 sm:col-span-3" : span === 4 ? "col-span-2 sm:col-span-4" : "";
  return (
    <div className={`min-w-0 ${spanClass}`} title={`${label}: ${value}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-base-content/45">{label}</div>
      {/* O default era `truncate`, entao TODO campo saia cortado a menos que
          alguem lembrasse de passar `full`. Num MODAL DE DETALHE isso e o
          avesso do proposito: quem abriu ali quer justamente o texto inteiro —
          o nome do responsavel, o orgao concedente, o objeto. O default agora
          e quebrar a linha; quem precisa de uma linha so passa `full={false}`. */}
      <div className={`mt-0.5 text-sm text-base-content ${mono ? "font-mono" : ""} ${full === false ? "truncate" : "break-words"} ${valueClass}`}>
        {value}
      </div>
    </div>
  );
}
