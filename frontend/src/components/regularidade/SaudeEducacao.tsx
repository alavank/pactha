"use client";
// SAÚDE E EDUCAÇÃO — o detalhe dos itens 3.2.3, 3.2.4, 5.1 e 5.2 do CAUC.
//
// O CAUC só diz "!" ou uma validade. Aqui: QUAL bimestre falta, até quando, se o
// município já entregou e o Tesouro ainda não atualizou, e o percentual aplicado.
// Mais o estado do Plano, da PAS, dos RDQAs e do RAG no DigiSUS.
//
// ⚠️ A REGRA NÃO MORA AQUI. Situação, prazo e cor do percentual vêm prontos de
// `GET /api/saude-educacao` (`services/saude_educacao.py`) — a mesma regra que o
// painel e o push usam. Se a tela recalculasse, um dia ela e o alerta do
// prefeito discordariam sobre o mesmo bimestre.
//
// ⚠️ O PERCENTUAL DO BIMESTRE É PARCIAL (acumulado no ano); o mínimo se apura no
// 6º bimestre. Por isso o servidor nunca manda `critico` para um bimestre
// parcial — e esta tela não inventa cor por conta própria.
import React from "react";
import { Clock, HeartPulse } from "lucide-react";
import { Bloco, BlocoHead, Grade, GradeCel, GradeLinha, Selo, Vazio } from "@/components/ui/superficies";
import { formatDataHora, horasDesde } from "@/lib/bi-format";

type Tom = "ok" | "atencao" | "critico" | null;

export interface Bimestre {
  ano: number;
  bimestre: number;
  rotulo: string;
  prazo: string;
  entregue: boolean | null;
  data_entrega: string | null;
  situacao: "entregue" | "entregue_atrasado" | "no_prazo" | "atrasado" | "sem_informacao";
  pct: number | null;
  parcial: boolean;
  tom_pct: Tom;
  recibo?: string | null;
}

export interface SistemaSE {
  sistema: "SIOPS" | "SIOPE";
  nome: string;
  indicador: string;
  minimo: number;
  item_envio: string;
  item_minimo: string;
  bimestres: Bimestre[];
  atrasados: string[];
}

export interface Instrumento {
  instrumento: string;
  rotulo: string;
  ano: number;
  periodo?: string | null;
  situacao: string;
  classe: "concluido" | "conselho" | "pendente" | "reprovado" | "desconhecido";
  prazo: string | null;
  vencido: boolean;
}

export interface SaudeEducacaoResp {
  tem_dados: boolean;
  motivo?: string;
  sistemas?: Record<string, SistemaSE>;
  /** A frase ao lado de cada item do CAUC (3.2.3, 3.2.4, 5.1, 5.2). */
  notas_cauc?: Record<string, { texto: string; tom: Tom }>;
  instrumentos?: Instrumento[];
  instrumentos_vencidos?: number;
  alerta?: boolean;
  atualizado_em?: string | null;
}

/** Data pura do banco (aaaa-mm-dd) → dd/mm/aaaa, sem passar por fuso. */
function data(iso?: string | null): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

function pct(v: number | null): string {
  return v === null || v === undefined ? "—" : `${v.toFixed(2).replace(".", ",")}%`;
}

const SITUACAO: Record<Bimestre["situacao"], { texto: string; tom: "ok" | "atencao" | "critico" | "neutro" }> = {
  entregue: { texto: "Entregue", tom: "ok" },
  entregue_atrasado: { texto: "Entregue com atraso", tom: "ok" },
  no_prazo: { texto: "Aguardando — no prazo", tom: "neutro" },
  atrasado: { texto: "Não entregue — prazo vencido", tom: "critico" },
  sem_informacao: { texto: "Sem dado da fonte", tom: "neutro" },
};

const COLS = "grid-cols-[minmax(7.5rem,1fr)_minmax(9rem,1.2fr)_6.5rem_6.5rem_5.5rem]";

function TabelaSistema({ s }: { s: SistemaSE }) {
  const anos = [...new Set(s.bimestres.map((b) => b.ano))].sort((a, b) => b - a);
  const verbo = s.sistema === "SIOPS" ? "Homologado em" : "Declarado em";
  return (
    <Bloco className="p-4">
      <BlocoHead
        titulo={s.nome}
        sub={`CAUC ${s.item_envio} (envio) e ${s.item_minimo} (mínimo de ${s.minimo}%) · ${s.indicador}`}
        right={s.atrasados.length
          ? <Selo tom="critico">{s.atrasados.length} em atraso</Selo>
          : undefined}
      />
      {anos.map((ano) => (
        <div key={ano} className="mt-2">
          <div className="mb-1 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>{ano}</div>
          <Grade
            cols={COLS}
            rolagem
            minLargura="34rem"
            cabecalho={[
              { label: "Bimestre" }, { label: "Situação" }, { label: verbo, direita: true },
              { label: "Prazo", direita: true }, { label: "% aplicado", direita: true },
            ]}
          >
            {s.bimestres.filter((b) => b.ano === ano).map((b) => {
              const sit = SITUACAO[b.situacao];
              return (
                <GradeLinha key={`${b.ano}-${b.bimestre}`} cols={COLS} alerta={b.situacao === "atrasado"}>
                  <GradeCel>{b.bimestre}º bimestre</GradeCel>
                  <GradeCel>
                    <Selo tom={sit.tom} title={b.situacao === "sem_informacao"
                      ? "A fonte ainda não publicou este bimestre para a UF — não é o mesmo que falta de entrega."
                      : undefined}>{sit.texto}</Selo>
                  </GradeCel>
                  <GradeCel tom="data">{data(b.data_entrega)}</GradeCel>
                  <GradeCel tom="data">{data(b.prazo)}</GradeCel>
                  <GradeCel tom="num">
                    <span
                      title={b.parcial
                        ? `Acumulado até o ${b.rotulo}. Parcial: o mínimo de ${s.minimo}% se apura no ano (6º bimestre).`
                        : `Ano fechado. Mínimo: ${s.minimo}%.`}
                      style={{
                        color: b.tom_pct === "critico" ? "var(--bi-crit-ink)"
                          : b.tom_pct === "atencao" ? "var(--bi-warn-ink)" : undefined,
                      }}
                    >
                      {pct(b.pct)}{b.pct !== null && b.parcial ? "*" : ""}
                    </span>
                  </GradeCel>
                </GradeLinha>
              );
            })}
          </Grade>
        </div>
      ))}
      <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
        * Percentual acumulado até o bimestre — <b>parcial</b>. O mínimo de {s.minimo}% é
        apurado no ano inteiro (6º bimestre); abaixo dele no meio do ano é sinal de atenção,
        não descumprimento. Prazo de envio: 30 dias após o fim do bimestre.
      </p>
    </Bloco>
  );
}

const ORDEM = ["PLANO", "PAS", "RDQA1", "RDQA2", "RDQA3", "RAG"];
const CURTO: Record<string, string> = {
  PLANO: "Plano de Saúde", PAS: "PAS", RDQA1: "1º RDQA", RDQA2: "2º RDQA", RDQA3: "3º RDQA", RAG: "RAG",
};
const COLS_INSTR = "grid-cols-[3.5rem_repeat(6,minmax(6.5rem,1fr))]";

function tomInstrumento(i: Instrumento): "ok" | "atencao" | "critico" | "neutro" {
  if (i.classe === "reprovado") return "critico";
  if (i.vencido) return "atencao";
  if (i.classe === "concluido") return "ok";
  return "neutro";
}

function Instrumentos({ itens, vencidos }: { itens: Instrumento[]; vencidos: number }) {
  if (!itens.length) return null;
  const anos = [...new Set(itens.map((i) => i.ano))].sort((a, b) => b - a);
  const por = new Map(itens.map((i) => [`${i.instrumento}-${i.ano}`, i]));
  return (
    <Bloco className="p-4">
      <BlocoHead
        titulo="Instrumentos de planejamento do SUS"
        sub="DigiSUS Gestor — Plano de Saúde, Programação Anual (PAS), Relatórios Detalhados do Quadrimestre (RDQA) e Relatório Anual de Gestão (RAG)"
        right={vencidos
          ? <Selo tom="atencao">{vencidos} com prazo vencido</Selo>
          : undefined}
      />
      <Grade
        cols={COLS_INSTR}
        rolagem
        minLargura="46rem"
        cabecalho={[{ label: "Ano" }, ...ORDEM.map((k) => ({ label: CURTO[k] }))]}
      >
        {anos.map((ano) => (
          <GradeLinha key={ano} cols={COLS_INSTR}>
            <GradeCel tom="id">{ano}</GradeCel>
            {ORDEM.map((k) => {
              const i = por.get(`${k}-${ano}`);
              if (!i) return <GradeCel key={k}><span style={{ color: "var(--bi-faint)" }}>—</span></GradeCel>;
              return (
                <GradeCel key={k}>
                  <Selo
                    tom={tomInstrumento(i)}
                    title={[
                      i.periodo ? `Período ${i.periodo}` : "",
                      i.prazo ? `Prazo legal: ${data(i.prazo)}` : "",
                      i.classe === "conselho" ? "A prefeitura já enviou; aguarda o Conselho Municipal de Saúde." : "",
                    ].filter(Boolean).join(" · ") || undefined}
                  >
                    {i.situacao}
                  </Selo>
                </GradeCel>
              );
            })}
          </GradeLinha>
        ))}
      </Grade>
      <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
        Prazos da LC 141/2012 (art. 36): 1º RDQA até o fim de maio, 2º até o fim de setembro,
        3º até o fim de fevereiro do ano seguinte; RAG até 30 de março do ano seguinte.
        “Em Análise no Conselho de Saúde” quer dizer que a prefeitura já enviou — falta o
        conselho. Plano e PAS seguem o calendário do próprio município e não têm prazo aqui.
      </p>
    </Bloco>
  );
}

export function SaudeEducacaoAba({ dados }: { dados: SaudeEducacaoResp | null }) {
  const h = dados?.atualizado_em ? horasDesde(dados.atualizado_em) : null;
  return (
    <section className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 className="bi-title flex items-center gap-1.5 text-[14px]">
          <HeartPulse className="size-3.5" style={{ color: "var(--bi-muted)" }} />
          Saúde e educação
        </h2>
        {dados?.atualizado_em && (
          <span className="text-[10px]"
                style={{ color: h !== null && h > 26 ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}>
            Atualizado em {formatDataHora(dados.atualizado_em)}
          </span>
        )}
        <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
          SIOPS (Ministério da Saúde), SIOPE (FNDE) e DigiSUS
        </span>
      </div>

      {!dados ? (
        <Vazio>Não foi possível carregar os dados de saúde e educação.</Vazio>
      ) : !dados.tem_dados ? (
        /* Ausência de coleta NÃO é ausência de pendência — mesmo cuidado das
           outras abas desta tela. */
        <Bloco className="p-4">
          <div className="flex items-start gap-2.5">
            <Clock className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
            <div className="space-y-1.5">
              <div className="bi-title text-[13px] leading-tight">Aguardando coleta</div>
              <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                {dados.motivo || "Ainda não consultado."}
              </p>
              <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                As consultas são públicas e usam o código IBGE do município — não dependem
                de senha nem de credencial.
              </p>
            </div>
          </div>
        </Bloco>
      ) : (
        <div className="space-y-2.5">
          {["SIOPS", "SIOPE"].map((k) => {
            const s = dados.sistemas?.[k];
            return s && s.bimestres.length ? <TabelaSistema key={k} s={s} /> : null;
          })}
          <Instrumentos itens={dados.instrumentos || []} vencidos={dados.instrumentos_vencidos || 0} />
        </div>
      )}
    </section>
  );
}

/** A frase ao lado do item do CAUC. A cor é a que o servidor mandou. */
export function NotaCauc({ nota }: { nota?: { texto: string; tom: Tom } }) {
  if (!nota) return null;
  return (
    <div
      className="mt-0.5 text-[10px] leading-snug"
      style={{
        color: nota.tom === "critico" ? "var(--bi-crit-ink)"
          : nota.tom === "ok" ? "var(--bi-ok-ink)" : "var(--bi-muted)",
      }}
    >
      {nota.texto}
    </div>
  );
}
