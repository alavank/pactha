"use client";

import React, { useEffect, useState } from "react";
import { Building2, CalendarClock, ClipboardCheck, FileText, Fingerprint } from "lucide-react";
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
  dias_vigencia_atual?: number | null;
  vigencia_inicial?: string;
  vigencia_atual?: string;
  dias_restantes?: number;
  dias_restantes_label?: string;
  titulo?: string;
  objetivo?: string;
  concedente_orgao?: string;
  convenente_nome?: string;
  municipio_nome?: string;
  valor_concedente?: number;
  valor_contrapartida?: number;
  valor_total?: number;
  valor_dotacao_complementar?: number | string;
  responsaveis?: string;
  proposta_vigencia?: string;
  fase_etapa_status?: string;
  setor?: string;
  /* PRESTAÇÃO DE CONTAS, lida da seção própria do detalhe SIGCON. Duas datas
     porque respondem perguntas diferentes: `_data` é quando o município
     APRESENTOU a prestação final, `_status_data` é quando o Estado mexeu no
     status. */
  prestacao_contas_status?: string | null;
  prestacao_contas_data?: string | null;
  prestacao_contas_status_data?: string | null;
  prestacao_contas_sei?: string | null;
  qt_alteracoes?: number | null;
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

/** "o portal nunca informou", que NÃO é zero.
 *
 *  `formatCurrency(null)` devolve "R$ 0,00" (lib/utils.ts), então estes cartões
 *  afirmavam zero onde não houve coleta: contrapartida NULA em 368 das 899
 *  linhas visíveis, em 23 dos 24 municípios, e Dotação Compl. ausente em 864 de
 *  899. Zero de verdade continua imprimindo "R$ 0,00" (180 linhas) — e só passou
 *  a ser distinguível porque o backend parou de colapsar 0 em None.
 *
 *  Texto e não "-": este arquivo já recusou o travessão solitário em bloco
 *  grande (ver o "Objeto"), aqui o número sai grande, e um travessão colidiria
 *  com o "-" que `campo()` usa nas grades.
 *
 *  ⚠️ NÃO alterar `formatCurrency`: são ~40 usos em 11 arquivos que dependem do
 *  "R$ 0,00" de hoje. */
const SEM_DADO = (
  <span className="text-[13px]" style={{ color: "var(--bi-faint)" }}>não informado</span>
);
const moeda = (v: number | null | undefined) => (v == null ? SEM_DADO : formatCurrency(v));

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
            {/* "Sem número" e não "-", pela mesma razão já escrita para o
                Objeto: travessão sozinho no ponto mais alto do modal lê-se como
                falha de carregamento. Depois que a chave sintética do FNS saiu
                do número publicado, 3.194 registros abrem sem identificador —
                eles não têm proposta, SIAFI nem plano de trabalho. E enquanto
                `d` é nulo o rótulo ainda não pode ser afirmado: ali o certo é a
                reticência, que casa com o "Carregando…" logo abaixo. */}
            <span className="bi-num text-[15px]">
              {d
                ? d.nr_convenio_publicado || d.nr_proposta || (
                    <span style={{ color: "var(--bi-faint)" }}>Sem número</span>
                  )
                : "…"}
            </span>
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
              /* `?? d.valor_repasse` SAIU: o endpoint de detalhe nunca devolve
                 essa chave — era fallback inalcançável. E não escondia número:
                 `raw_data.valor_repasse` existe em 793 linhas do freitas e é
                 IDÊNTICO a `valor_concedente` em 792 comparáveis. */
              valor={moeda(d.valor_concedente ?? d.valor_total)}
            />
            <Numero rotulo="Contrapartida" valor={moeda(d.valor_contrapartida)} />
            <Numero
              rotulo="Dotação Compl."
              /* O SIGCON manda o valor JÁ FORMATADO ("R$ 241.771,54") dentro do
                 raw_data: `jsonb_typeof` diz 'string' em 100% das 35 linhas que
                 têm o campo, nas três bases — `formatCurrency` numa string
                 devolveria "R$ NaN". O ramo de número fica só como guarda, caso
                 a ingestão passe a converter.
                 Duas correções: ausente vira "não informado" em vez de
                 "R$ 0,00" (eram 864 de 899 linhas afirmando zero onde a fonte
                 nada disse, e há 24 em que ela DE FATO disse "R$ 0,00", hoje
                 indistinguíveis); e string SEM DÍGITO também vira "não
                 informado" — uma linha do freitas imprimia o texto "Não há"
                 dentro de uma caixa de moeda. */
              valor={(() => {
                const v = d.valor_dotacao_complementar;
                if (typeof v === "number") return formatCurrency(v);
                const s = (v ?? "").trim();
                return /\d/.test(s) ? s : SEM_DADO;
              })()}
            />
            <Numero rotulo="Valor Total" valor={moeda(d.valor_total)} tom="acento" />
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
              /* Era "Dias Vigência Atual", encostado em "Dias Restantes" no
                 mesmo cartão: "Atual" lê-se como "agora" e o gestor entendia
                 "quanto ainda falta" — mas o número é a DURAÇÃO do período
                 vigente. E saía "730" pelado ao lado de um vizinho que sai
                 "433d". O sufixo "d" é de propósito igual ao da célula vizinha:
                 a convenção já existe no mesmo cartão. */
              campo(
                "Duração da Vigência",
                d.dias_vigencia_atual != null ? `${d.dias_vigencia_atual}d` : null,
              ),
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
              /* Sem o `?? 0`: "não sei" deixa de virar "zero". O helper
                 `campo()` já preserva o 0 legítimo — ele só troca null/""
                 por "-", e é isso que separa as 81 linhas em que o portal
                 contou zero das 703 em que ninguém contou nada. */
              campo("Qt. Alterações", d.qt_alteracoes),
              campo("Proposta Vigência", d.proposta_vigencia, { span: 2 }),
            ]}
          />

          {/* PRESTAÇÃO DE CONTAS — seção própria, e ela SÓ APARECE quando há dado.
              O campo antigo com este nome foi removido do modal justamente por
              desenhar "-" em 894 de 894 linhas; a seção volta com coletor, mas
              renascer vazia repetiria o defeito em todo convênio de fonte que não
              é SIGCON-MG (GConv-ES, FNS) e em todo tenant sem `SIGCON_INDICACOES`.

              ⚠️ NÃO passar as datas por `formatDate`: o portal já entrega
              "08/08/2024", e o helper espera ISO — ele devolveria "Invalid Date"
              ou, pior, trocaria dia por mês em silêncio. São strings verbatim. */}
          {(d.prestacao_contas_status || d.prestacao_contas_data
            || d.prestacao_contas_sei || d.prestacao_contas_status_data) && (
            <Secao
              icon={ClipboardCheck}
              titulo="Prestação de Contas"
              campos={[
                campo("Status Atual", d.prestacao_contas_status, { span: 4 }),
                campo("Apresentação da Prestação Final", d.prestacao_contas_data, { span: 2 }),
                campo("Preenchimento do Status", d.prestacao_contas_status_data, { span: 2 }),
                campo("Nº SEI", d.prestacao_contas_sei, { span: 4 }),
              ]}
            />
          )}

          <Secao
            icon={Building2}
            titulo="Partes Envolvidas"
            campos={[
              campo("Concedente / Órgão", d.concedente_orgao, { span: 2 }),
              campo("Convenente / OSC", d.convenente_nome, { span: 2 }),
              // "Município" fica em coluna inteira agora que "Tipo Convenente"
              // saiu: o campo removido escrevia "Administração Municipal" por
              // conta própria em 4.018 de 4.093 linhas — inclusive onde o
              // convenente é um Fundo Municipal de Saúde, que administração
              // municipal não é. E nunca distinguia nada: nas 75 vezes em que a
              // fonte de fato informou, informou sempre a mesma coisa. O que
              // ele prometia já está na linha de cima, em "Convenente / OSC".
              campo("Município", d.municipio_nome, { span: 2 }),
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
                {/* "Sem objeto informado" e nao "-": e a mesma frase que a LISTA
                    ja usa, e um travessao solitario ocupando a largura inteira
                    do bloco mais importante do modal le-se como falha de
                    carregamento. Atinge 150 das 788 linhas do freitas. */}
                {d.titulo || <span style={{ color: "var(--bi-faint)" }}>Sem objeto informado</span>}
              </p>
            </div>
            {/* ⭐ A DESCRIÇÃO, que existia no banco e nunca era desenhada.
                No dialeto do Espírito Santo a coluna `objeto` guarda o CÓDIGO do
                processo — o gestor do Trust abria o convênio e lia "2026-M632Z"
                no lugar de "AQUISIÇÃO DE EQUIPAMENTOS PARA A SECRETARIA
                MUNICIPAL DE CULTURA". O texto vinha na resposta da API, estava
                declarado na interface deste componente, e não era referenciado
                em nenhuma das 249 linhas.

                ADITIVO, nunca substituição: em MG `objetivo` é NULO nas 869
                linhas, então lá este bloco simplesmente não renderiza — zero
                regressão. E em 7 dos 25 convênios do ES o `objeto` carrega o
                código que o gestor usa para conferir com o processo, então
                trocar um pelo outro perderia informação útil. */}
            {d.objetivo && d.objetivo !== d.titulo && (
              <div className="mt-2.5">
                <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Descrição</div>
                <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                  {d.objetivo}
                </p>
              </div>
            )}
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
