"use client";

/* O DETALHE DE UMA EMENDA — um modal só, venha a emenda de onde vier.
 *
 * ⭐ PARA O QUE JÁ TEM MODAL, O MODAL É O MESMO. Plano de ação (Pix), proposta de
 * Parcerias e convênio voluntário abrem os componentes das telas de origem
 * (`PlanoAcaoModal`, `DetalheProposta`, `DetalheVoluntariaModal`), alimentados
 * por `/emendas-parlamentares/emenda/{origem}/{id}` — que devolve em `dados`
 * exatamente o payload das rotas de lá. Duas versões do mesmo modal seriam duas
 * versões da emenda, e a primeira aba nova que entrasse numa delas faria as
 * telas discordarem.
 *
 * ⚠️ E A ROTA É A DA TELA NOVA, e não a de origem, por causa da permissão: cada
 * aba cobra a chave que já existia (decisão do dono, 17/09/2026), então quem só
 * tem Emendas Federais receberia 403 em `/transferegov/plano-acao`.
 *
 * O que não tinha modal (a emenda da carteira, a indicação de saúde, a indicação
 * do SIGCON e o repasse de GO) ganha este, com as abas que o dado sustenta.
 */

import React, { useEffect, useState } from "react";
import { ExternalLink, Loader2 } from "lucide-react";

import api from "@/lib/api";
import {
  Abas, Campos, Grade, GradeCel, GradeLinha, ItemLinha, Lista, Modal, ModalCorpo,
  ModalHead, Selo, Vazio,
} from "@/components/ui/superficies";
import { PlanoAcaoModal, type DetalhePlano } from "@/components/PlanoAcaoTela";
import { DetalheProposta, type DetalheResp } from "@/components/ParceriasTela";
import { DetalheVoluntariaModal, type Detalhe as DetalheVoluntaria } from "@/components/TransfereGovPropostas";
import { SeloCadastro, type Cadastro } from "@/components/emendas/AbaParlamentares";

export type Origem = "federal" | "te" | "parcerias" | "indicacao" | "voluntaria" | "sigcon" | "go";

export interface Autor { nome: string; pessoa: boolean; cadastro: Cadastro | null }

export interface Instrumento {
  origem: Origem; id: string; rotulo: string; situacao: string | null;
  valor: number | null; objeto: string | null;
}

type Reg = Record<string, unknown>;

interface Resp {
  origem: Origem;
  id: string;
  codigo_emenda: string | null;
  parlamentares: Autor[];
  dados: Reg | null;
}

export const brl = (v: unknown) =>
  typeof v === "number"
    ? v.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 })
    : "—";
const txt = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));
/** "202606" -> "06/2026" (o mês de referência da planilha de favorecidos). */
const mesAno = (s: unknown) => {
  const t = String(s ?? "");
  return /^\d{6}$/.test(t) ? `${t.slice(4)}/${t.slice(0, 4)}` : (t || "—");
};
const dia = (s: unknown) =>
  typeof s === "string" && s ? new Date(s.length === 10 ? `${s}T12:00:00` : s).toLocaleDateString("pt-BR") : "—";

/** Cartão do autor: foto, partido, cargo. Órgão e colegiado aparecem com o nome
 *  e a frase de que não são um parlamentar — nunca num cartão de pessoa. */
function Parlamentares({ autores }: { autores: Autor[] }) {
  if (!autores.length) return <Vazio>A fonte não informa o autor desta emenda.</Vazio>;
  return (
    <Lista>
      {autores.map((a) => (
        <ItemLinha
          key={a.nome}
          titulo={<span className="flex flex-wrap items-center gap-2">
            <span>{a.nome}</span>
            <SeloCadastro c={a.cadastro} />
          </span>}
          meta={
            !a.pessoa ? "Bancada, comissão ou órgão — não é um parlamentar."
            : a.cadastro ? `${a.cadastro.cargo}${a.cadastro.uf ? ` · ${a.cadastro.uf}` : ""}`
            : "Partido não identificado: o nome não casou com o cadastro da Câmara, do Senado ou da ALMG."
          }
        />
      ))}
    </Lista>
  );
}

function ModalProprio({ titulo, sub, onFechar, abas, children }: {
  titulo: string; sub?: string; onFechar: () => void;
  abas: Array<{ valor: string; label: string; on?: boolean; corpo: React.ReactNode }>;
  children?: React.ReactNode;
}) {
  const [aba, setAba] = useState(abas[0]?.valor ?? "");
  const ativa = abas.find((a) => a.valor === aba && a.on !== false) ?? abas[0];
  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-4xl">
      <ModalHead titulo={titulo} sub={sub} onFechar={onFechar}
                 abaixo={<Abas valor={ativa?.valor ?? ""} onChange={setAba}
                               opcoes={abas.map(({ valor, label, on }) => ({ valor, label, on }))} />} />
      <ModalCorpo className="flex flex-col gap-3">
        {children}
        <div key={ativa?.valor} className="bi-pane-enter flex flex-col gap-3">{ativa?.corpo}</div>
      </ModalCorpo>
    </Modal>
  );
}

const TOM_FASE: Record<string, "neutro" | "ok" | "atencao"> = {
  Empenho: "atencao", Liquidação: "atencao", Pagamento: "ok",
};

function DetalheFederal({ r, onFechar, onAbrir }: {
  r: Resp; onFechar: () => void; onAbrir: (o: Origem, id: string) => void;
}) {
  const d = r.dados || {};
  const res = (d.resumo || {}) as Reg;
  const ex = (d.execucao || {}) as Reg;
  const benef = (d.beneficiarios || []) as Reg[];
  const lt = (d.linha_do_tempo || {}) as {
    documentos?: Reg[]; motivo?: string; recebido?: Reg[]; convenios?: Reg[];
  };
  const recebido = lt.recebido || [];
  const convGerados = lt.convenios || [];
  const totalRecebido = recebido.reduce((a, x) => a + ((x.valor as number) || 0), 0);
  const inst = (d.instrumentos || []) as Instrumento[];
  const consultada = !!res.execucao_consultada;
  const cols = "grid-cols-[6.5rem_8rem_1fr_9rem]";
  return (
    <ModalProprio
      titulo={`Emenda ${txt(res.codigo_emenda)}`}
      sub={[txt(res.autor), res.ano ? String(res.ano) : null].filter(Boolean).join(" · ")}
      onFechar={onFechar}
      abas={[
        { valor: "resumo", label: "Resumo", corpo: (
          <>
            {!!res.motivo && <p className="text-[12px]" style={{ color: "var(--bi-muted)" }}>{String(res.motivo)}</p>}
            <Campos cols={3} campos={[
              { rotulo: "Código", valor: txt(res.codigo_emenda) },
              { rotulo: "Ano", valor: txt(res.ano) },
              { rotulo: "Tipo", valor: txt(res.tipo) },
              { rotulo: "Impositiva", valor: res.impositiva ? "Sim" : "Não" },
              { rotulo: "Órgão", valor: txt(res.orgao) },
              { rotulo: "Função / subfunção", valor: [res.funcao, res.subfuncao].filter(Boolean).join(" · ") || "—" },
            ]} />
            {/* ⚠️ UMA LINHA POR BENEFICIÁRIO: a mesma emenda pode ir à prefeitura e
                ao hospital da cidade, e o valor indicado de cada um é dele. */}
            <Lista>
              {benef.map((b, i) => (
                <ItemLinha key={i}
                  titulo={<span className="flex flex-wrap items-center gap-1.5">
                    {txt(b.beneficiario_nome || b.beneficiario_cnpj)}
                    {!b.beneficiario_prefeitura && <Selo tom="acento">não é a Prefeitura</Selo>}
                  </span>}
                  valor={<span className="bi-num">{brl(b.valor_indicado)}</span>}
                  meta="indicado a este beneficiário" />
              ))}
            </Lista>
            {!!res.url_fonte && (
              <a href={String(res.url_fonte)} target="_blank" rel="noreferrer"
                 className="inline-flex w-fit items-center gap-1 text-[11px] underline"
                 style={{ color: "var(--bi-accent-ink)" }}>
                <ExternalLink className="size-3" /> conferir no Portal da Transparência
              </a>
            )}
          </>
        ) },
        { valor: "parlamentar", label: "Parlamentar", corpo: <Parlamentares autores={r.parlamentares} /> },
        { valor: "pagamentos", label: "Pagamentos", corpo: (
          <>
            {/* ⭐ PRIMEIRO O QUE CHEGOU AQUI: o pago a quem está NESTE município,
                mês a mês (planilha de favorecidos da CGU, 24/09/2026). É a fatia
                que o agregado nacional abaixo não separa. */}
            {recebido.length > 0 && (
              <>
                <p className="text-[12px] font-semibold" style={{ color: "var(--bi-text)" }}>
                  Recebido neste município: {brl(totalRecebido)}
                </p>
                <Lista>
                  {recebido.map((x, i) => (
                    <ItemLinha key={i}
                      titulo={txt(x.favorecido)}
                      valor={<span className="bi-num">{brl(x.valor)}</span>}
                      meta={[mesAno(x.ano_mes), x.natureza ? String(x.natureza) : null]
                        .filter(Boolean).join(" · ")} />
                  ))}
                </Lista>
              </>
            )}
            {consultada ? (
          <>
            {/* ⚠️⚠️ DA EMENDA INTEIRA, NACIONAL — e o rótulo diz. Somado ao
                indicado, deu R$ 4 bilhões em Nova Palma. */}
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Valores da emenda inteira, segundo a CGU. Uma emenda pode atender vários
              municípios, e a CGU não separa a fatia de cada um.
            </p>
            <Campos cols={3} campos={[
              { rotulo: "Empenhado", valor: brl(ex.valor_empenhado) },
              { rotulo: "Liquidado", valor: brl(ex.valor_liquidado) },
              { rotulo: "Pago", valor: brl(ex.valor_pago) },
              { rotulo: "Resto a pagar inscrito", valor: brl(ex.valor_resto_inscrito), tom: "atencao" },
              { rotulo: "Resto a pagar pago", valor: brl(ex.valor_resto_pago) },
              { rotulo: "Resto cancelado", valor: brl(ex.valor_resto_cancelado),
                tom: ((ex.valor_resto_cancelado as number) || 0) > 0 ? "critico" : "normal" },
            ]} />
          </>
            ) : <Vazio>A execução desta emenda ainda não foi consultada no Portal da Transparência.</Vazio>}
          </>
        ) },
        { valor: "historico", label: `Histórico${lt.documentos?.length ? ` (${lt.documentos.length})` : ""}`, corpo:
          lt.documentos?.length ? (
            <Grade rolagem minLargura="32rem" cols={cols}
                   cabecalho={[{ label: "Data" }, { label: "Fase" }, { label: "Documento" }, { label: "Espécie" }]}>
              {lt.documentos.map((x, i) => (
                <GradeLinha key={i} cols={cols}>
                  <GradeCel tom="data">{dia(x.data)}</GradeCel>
                  <GradeCel>{x.fase ? <Selo tom={TOM_FASE[String(x.fase)] || "neutro"}>{String(x.fase)}</Selo> : "—"}</GradeCel>
                  <GradeCel tom="id">{txt(x.documento_resumido || x.codigo_documento)}</GradeCel>
                  <GradeCel>{txt(x.especie_tipo)}</GradeCel>
                </GradeLinha>
              ))}
            </Grade>
          ) : <Vazio>{lt.motivo || "Sem documentos de execução."}</Vazio> },
        { valor: "instrumentos", label: `Projeto e instrumentos${inst.length + convGerados.length ? ` (${inst.length + convGerados.length})` : ""}`, corpo:
          inst.length || convGerados.length ? (
            <>
            {/* Os convênios que a emenda gerou NESTE município, pela planilha da
                CGU — o vínculo emenda → convênio que a API dela não tem. */}
            {convGerados.length > 0 && (
              <Lista>
                {convGerados.map((c, i) => (
                  <ItemLinha key={`cgu-${i}`}
                    titulo={<span className="flex flex-wrap items-center gap-1.5">
                      Convênio {txt(c.numero)} <Selo tom="acento">gerado por esta emenda</Selo>
                    </span>}
                    valor={<span className="bi-num">{brl(c.valor)}</span>}
                    meta={[c.convenente ? String(c.convenente) : null,
                           c.data_publicacao ? `publicado em ${dia(c.data_publicacao)}` : null,
                           c.objeto ? String(c.objeto) : null].filter(Boolean).join(" · ")} />
                ))}
              </Lista>
            )}
            {inst.length > 0 && (
            <Lista>
              {inst.map((i) => (
                <ItemLinha key={`${i.origem}-${i.id}`}
                  titulo={<span className="flex flex-wrap items-center gap-1.5">
                    <Selo>{i.rotulo}</Selo> {i.objeto || i.id}
                  </span>}
                  valor={<span className="bi-num">{brl(i.valor)}</span>}
                  meta={[i.id, i.situacao].filter(Boolean).join(" · ")}
                  onClick={i.origem === "indicacao" ? undefined : () => onAbrir(i.origem, i.id)} />
              ))}
            </Lista>
            )}
            </>
          ) : <Vazio>Esta emenda ainda não virou proposta, plano de ação ou convênio.</Vazio> },
      ]}
    />
  );
}

function DetalheSimples({ r, onFechar }: { r: Resp; onFechar: () => void }) {
  const d = r.dados || {};
  if (r.origem === "indicacao") {
    const ind = (d.indicacoes || []) as Reg[];
    const x = ind[0] || {};
    return (
      <ModalProprio titulo={`Emenda de saúde ${txt(x.numero_emenda)}`} sub="Indicada, ainda sem proposta"
        onFechar={onFechar}
        abas={[
          { valor: "resumo", label: "Resumo", corpo: (
            <Lista>
              {ind.map((i, k) => (
                <ItemLinha key={k} titulo={txt(i.nome_beneficiario)}
                  valor={<span className="bi-num">{brl(i.valor_total)}</span>}
                  meta={`custeio ${brl(i.valor_gnd3)} · investimento ${brl(i.valor_gnd4)} · ${txt(i.natureza_juridica)}`} />
              ))}
            </Lista>
          ) },
          { valor: "parlamentar", label: "Parlamentar", corpo: <Parlamentares autores={r.parlamentares} /> },
        ]} />
    );
  }
  if (r.origem === "sigcon") {
    const e = (d.emenda || {}) as Reg;
    const c = (d.convenio || null) as Reg | null;
    return (
      <ModalProprio titulo={`Indicação ${txt(e.nr_indicacao)}`} sub={`SIGCON-MG · ${txt(e.ano)}`} onFechar={onFechar}
        abas={[
          { valor: "resumo", label: "Resumo", corpo: (
            <Campos cols={3} campos={[
              { rotulo: "Valor indicado", valor: brl(e.valor_indicacao) },
              { rotulo: "Situação", valor: txt(e.status_indicacao) },
              { rotulo: "Tipo", valor: txt(e.tipo_indicacao) },
              { rotulo: "Beneficiário", valor: txt(e.beneficiario) },
              { rotulo: "Atendimento", valor: txt(e.tipo_atendimento) },
              { rotulo: "Unidade orçamentária", valor: txt(e.uo_sigla) },
            ]} />
          ) },
          { valor: "parlamentar", label: "Parlamentar", corpo: <Parlamentares autores={r.parlamentares} /> },
          { valor: "convenio", label: "Convênio", corpo: c ? (
            <>
              <Campos cols={3} campos={[
                { rotulo: "Nº SIGCON", valor: txt(c.nr_sigcon) },
                { rotulo: "Situação", valor: txt(c.situacao) },
                { rotulo: "Valor total", valor: brl(c.valor_total) },
                { rotulo: "Repasse do Estado", valor: brl(c.valor_concedente) },
                { rotulo: "Vigência", valor: `${dia(c.dt_vigencia_inicial)} a ${dia(c.dt_vigencia_final)}` },
                { rotulo: "Concedente", valor: txt(c.orgao_concedente) },
              ]} />
              <p className="text-[12px]">{txt(c.objeto)}</p>
            </>
          ) : <Vazio>Esta indicação ainda não está ligada a um convênio no SIGCON.</Vazio> },
          { valor: "pagamentos", label: "Pagamentos", corpo: <Vazio>{String(d.sem_pagamento_motivo || "")}</Vazio> },
        ]} />
    );
  }
  // go
  return (
    <ModalProprio titulo={`Repasse ${txt(d.processo)}`} sub={`${txt(d.orgao)} · ${dia(d.data_repasse)}`} onFechar={onFechar}
      abas={[
        { valor: "resumo", label: "Resumo", corpo: (
          <>
            <Campos cols={3} campos={[
              { rotulo: "Valor pago", valor: brl(d.valor) },
              { rotulo: "Data", valor: dia(d.data_repasse) },
              { rotulo: "Credor", valor: txt(d.credor) },
              { rotulo: "Emenda nº", valor: txt(d.emenda_numero) },
              { rotulo: "Elemento", valor: txt(d.elemento) },
              { rotulo: "Fonte de recursos", valor: txt(d.fonte_recursos) },
            ]} />
            <p className="text-[12px]">{txt(d.descricao)}</p>
          </>
        ) },
        { valor: "parlamentar", label: "Parlamentar", corpo: <Parlamentares autores={r.parlamentares} /> },
      ]} />
  );
}

export function DetalheEmenda({ origem, id, municipioId, onFechar, onAbrir }: {
  origem: Origem;
  id: string;
  municipioId: string;
  onFechar: () => void;
  /** Abrir um instrumento a partir da emenda (troca o modal, não empilha). */
  onAbrir: (o: Origem, id: string) => void;
}) {
  const url = `/emendas-parlamentares/emenda/${origem}/${encodeURIComponent(id)}`;
  const [res, setRes] = useState<{ url: string; r: Resp | null; erro: string | null } | null>(null);

  useEffect(() => {
    // Parcerias busca sozinha (o componente de lá já tem o ciclo de carga).
    if (origem === "parcerias") return;
    let vivo = true;
    api.get<Resp>(url, { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setRes({ url, r: r.data, erro: null }); })
      .catch((e) => {
        if (vivo) setRes({ url, r: null, erro: e?.response?.data?.detail || "Não foi possível carregar esta emenda." });
      });
    return () => { vivo = false; };
  }, [url, origem, municipioId]);

  if (origem === "parcerias") {
    return (
      <DetalheProposta id={Number(id)} onFechar={onFechar}
        carregar={(i) => api.get<Resp>(`/emendas-parlamentares/emenda/parcerias/${i}`,
          { params: { municipio_id: municipioId } }).then((r) => r.data.dados as unknown as DetalheResp)} />
    );
  }

  const carregando = !res || res.url !== url;
  const r = carregando ? null : res!.r;
  // ⚠️ O erro vem ANTES dos modais reusados: com `detalhe` nulo e sem carregar,
  // eles simplesmente não abrem — e o clique pareceria não ter feito nada.
  if (!carregando && !r) {
    return (
      <Modal aberto onFechar={onFechar} maxW="max-w-4xl">
        <ModalHead titulo="Emenda" onFechar={onFechar} />
        <ModalCorpo><Vazio>{res?.erro}</Vazio></ModalCorpo>
      </Modal>
    );
  }

  if (origem === "te") {
    return <PlanoAcaoModal detalhe={(r?.dados as DetalhePlano | undefined) ?? null}
                           carregando={carregando} onFechar={onFechar} />;
  }
  if (origem === "voluntaria") {
    return <DetalheVoluntariaModal detalhe={(r?.dados as unknown as DetalheVoluntaria | undefined) ?? null}
                                   carregando={carregando} municipioId={municipioId} onFechar={onFechar} />;
  }
  if (!r) {
    return (
      <Modal aberto onFechar={onFechar} maxW="max-w-4xl">
        <ModalHead titulo="Emenda" onFechar={onFechar} />
        <ModalCorpo>
          <div className="py-16 text-center">
            <Loader2 className="mx-auto size-8 animate-spin" style={{ color: "var(--bi-faint)" }} />
          </div>
        </ModalCorpo>
      </Modal>
    );
  }
  if (origem === "federal") return <DetalheFederal r={r} onFechar={onFechar} onAbrir={onAbrir} />;
  return <DetalheSimples r={r} onFechar={onFechar} />;
}
