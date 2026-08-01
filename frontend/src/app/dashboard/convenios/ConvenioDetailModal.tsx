"use client";

import React, { useEffect, useState } from "react";
import { Building2, CalendarClock, FileText, Fingerprint } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import {
  Campo, Etapas, Modal, ModalCorpo, ModalHead, Numero, Secao, Selo, situacaoTom,
} from "@/components/ui/superficies";

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

/** O `-` de campo vazio vinha do helper `Field` local; a peça `Campos` da
 *  identidade renderiza o que receber. Sem este intermediário, campo sem dado
 *  sai em branco — e rótulo com nada embaixo parece falha de carregamento.
 *  `0` NÃO é vazio: `valor || "-"` transformaria "0 alterações" em "sem dado". */
function campo(rotulo: string, valor: unknown, extra?: Partial<Campo>): Campo {
  const v = valor === null || valor === undefined || valor === "" ? "-" : String(valor);
  return { rotulo, valor: v, title: v === "-" ? undefined : `${rotulo}: ${v}`, ...extra };
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

  // O tom dos dias restantes: prestação de contas é informação, vencido é
  // crítico, menos de 60 dias pede atenção. Mesma escala do resto do sistema.
  const tomDias: Campo["tom"] = !d
    ? "normal"
    // PRIMEIRO, e nao por acaso: o rótulo do SIGCON para a fase de prestação de
    // contas é "VENCIDO +90 DIAS - PRESTACAO DE CONTAS". Testar VENCIDO antes
    // pinta de vermelho um convênio que só encerrou a vigência e está em
    // prestação — que é o curso normal, não inadimplência.
    : d.dias_restantes_label?.includes("PRESTACAO")
    ? "normal"
    : d.dias_restantes_label?.startsWith("VENCIDO")
    ? "critico"
    : d.dias_restantes != null && d.dias_restantes < 60
    ? "atencao"
    : "normal";

  return (
    <Modal aberto onFechar={onClose} maxW="max-w-4xl">
      <ModalHead
        titulo={
          <span className="flex flex-wrap items-center gap-2">
            <span className="bi-num text-[15px]">{d?.nr_convenio_publicado || d?.nr_proposta || "-"}</span>
            {d?.status && <Selo tom={situacaoTom(d.status)}>{d.status}</Selo>}
          </span>
        }
        sub={
          <>
            {d?.tp_instrumento === "Transferência Especial"
              ? "Plano de Trabalho — Transf. Especial"
              : "Convênio"}
            {d?.fonte ? ` · ${d.fonte}` : ""}
          </>
        }
        onFechar={onClose}
      />

      {loading && (
        <div className="py-16 text-center text-[12px]" style={{ color: "var(--bi-faint)" }}>
          Carregando…
        </div>
      )}

      {d && (
        <ModalCorpo className="flex flex-col gap-3">
          {d.workflow?.steps?.length ? (
            <Secao
              icon={CalendarClock}
              titulo="Andamento no SIGCON"
              sub={`${d.workflow.steps.filter((s) => s.completed).length} de ${d.workflow.steps.length} etapa(s) concluída(s)`}
            >
              <Etapas
                largura={78}
                etapas={d.workflow.steps.map((s) => ({
                  rotulo: s.label,
                  concluida: s.completed,
                  atual: s.current,
                }))}
              />
            </Secao>
          ) : null}

          {/* Os quatro valores em destaque. O total leva o acento; os outros
              três ficam neutros — se os quatro forem coloridos, nenhum é. */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Numero
              rotulo="Valor Concedente"
              valor={formatCurrency(d.valor_concedente ?? d.valor_repasse ?? d.valor_total)}
            />
            <Numero rotulo="Contrapartida" valor={formatCurrency(d.valor_contrapartida) || "R$ 0,00"} />
            <Numero
              rotulo="Dotação Compl."
              /* Bivalente de propósito: o SIGCON manda ora número, ora string
                 já formatada dentro do raw_data. `formatCurrency` numa string
                 devolve "R$ NaN". */
              valor={
                typeof d.valor_dotacao_complementar === "number"
                  ? formatCurrency(d.valor_dotacao_complementar)
                  : d.valor_dotacao_complementar || "R$ 0,00"
              }
            />
            <Numero rotulo="Valor Total" valor={formatCurrency(d.valor_total)} tom="acento" />
          </div>

          <Secao
            icon={Fingerprint}
            titulo="Identificação"
            campos={[
              campo("Nº Convênio Publ.", d.nr_convenio_publicado, { mono: true }),
              campo("Nº SIAFI", d.nr_siafi, { mono: true }),
              campo("Nº Proposta", d.nr_proposta, { mono: true }),
              campo("Nº Plano Trabalho", d.nr_plano_trabalho, { mono: true }),
              campo("Nº Instrumento", d.nr_instrumento, { mono: true }),
              campo("Tipo Instrumento", d.tp_instrumento),
              campo("Fonte", d.fonte),
              campo("Ano", d.ano),
            ]}
          />

          <Secao
            icon={CalendarClock}
            titulo="Vigência & Prazos"
            campos={[
              campo("Data Criação", formatDate(d.data_criacao) || formatDate(d.dt_publicacao)),
              campo("Data Assinatura", formatDate(d.dt_assinatura)),
              campo("Data Publicação", formatDate(d.dt_publicacao)),
              campo("Dias Vigência Atual", d.dias_vigencia_atual),
              campo(
                "Vigência Atual",
                d.vigencia_inicial && d.vigencia_atual
                  ? `${formatDate(d.vigencia_inicial)} → ${formatDate(d.vigencia_atual)}`
                  : null,
                { span: 2 },
              ),
              campo(
                "Dias Restantes",
                d.dias_restantes_label || (d.dias_restantes != null ? `${d.dias_restantes}d` : null),
                { tom: tomDias, span: 2 },
              ),
              campo("Qt. Alterações", d.qt_alteracoes ?? 0),
              campo("Prestação de Contas", d.prestacao_contas, { span: 2 }),
              campo("Proposta Vigência", d.proposta_vigencia, { span: 2 }),
            ]}
          />

          <Secao
            icon={Building2}
            titulo="Partes Envolvidas"
            campos={[
              campo("Concedente / Órgão", d.concedente_orgao, { span: 2 }),
              campo("Convenente / OSC", d.convenente_nome, { span: 2 }),
              campo("Município", d.municipio_nome),
              campo("Tipo Convenente", d.tipo_convenente),
              campo("Responsável(is)", d.responsaveis, { span: 2 }),
              campo("Setor", d.setor, { span: 2 }),
            ]}
          />

          {/* Objeto fora da grade: é texto livre e a célula trunca por desenho.
              Num modal de DETALHE isso é o avesso do propósito — quem abriu ali
              quer justamente o texto inteiro. */}
          <Secao icon={FileText} titulo="Objeto">
            <div>
              <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Título</div>
              <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                {d.titulo || "-"}
              </p>
            </div>
            {d.fase_etapa_status && d.fase_etapa_status !== d.status && (
              <div className="mt-2.5">
                <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Fase-Etapa-Status</div>
                <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                  {d.fase_etapa_status}
                </p>
              </div>
            )}
          </Secao>
        </ModalCorpo>
      )}
    </Modal>
  );
}
