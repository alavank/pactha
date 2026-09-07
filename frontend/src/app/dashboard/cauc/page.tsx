"use client";
// REGULARIDADE DE DOCUMENTAÇÃO — a federal (CAUC) e a estadual, lado a lado.
//
// ⚠️ A COLUNA ESTADUAL NÃO É MAIS SÓ O CAGEC. Desde 08/2026 ela serve dois
// cadastros — CAGEC (MG) e CHE (RS) — e o nome que aparece na tela sai de
// `tituloEstadual(uf)`, nunca de literal. O payload traz `fonte` em cada linha.
// Os nomes de variável e o endpoint continuam "cagec" por custo de renomear;
// a COPY, não: ela fala com o prefeito, e para ele o cadastro tem o nome do
// estado DELE.
//
// Estavam separados de mentira: para o gestor o assunto é UM só ("minha
// documentação está em dia para assinar convênio?"). O que muda é a esfera —
// União (CAUC/Tesouro) e Minas (CAGEC/SIGCON) —, então cada uma é uma coluna.
//
// O CAGEC vem do CRC (Certificado de Registro Cadastral) do portal do CAGEC,
// que sai por CNPJ, sem credencial, e traz cada obrigação com SITUAÇÃO e DATA DE
// VALIDADE. Por isso as linhas do CAGEC mostram a data e as do CAUC não: são
// fontes diferentes no mesmo formato, e a data só existe onde a fonte dá.
//
// PELE (identidade do Painel): a GRADE das exigências ficou — código · item ·
// situação · validade em colunas de largura fixa —, porque conferir o extrato
// linha a linha é o gesto da tela e o alinhamento é o que o torna possível. O
// que mudou foi só a pele: fim do verde em toda linha comprovada (trinta ✔
// verdes não informam nada — quando tudo é sinal, nada é sinal), selo cinza por
// padrão e COR só onde há alerta: pendência impeditiva e prazo vencido.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  ShieldCheck, ShieldAlert, Check, AlertTriangle, AlertCircle, Ban, Loader2,
  Clock, Info, Gavel, ExternalLink, Landmark, RefreshCw, FileSearch,
} from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  CADASTRO_ESTADUAL, NOME_UF, acompanhamosEstadual, certificadoEstadual, siglaEstadual,
  subtituloEstadual, tituloEstadual,
} from "@/lib/estadual";
import { Bloco, BlocoHead, Lista, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";
import { formatDataHora, horasDesde } from "@/lib/bi-format";
import { TituloTela } from "@/components/TituloTela";

interface Item {
  codigo: string;
  grupo: string;
  label: string;
  valor: string;
  tipo: "regular" | "pendente" | "na";
  status: string;
  /** Coluna própria, como no documento (dd/mm/aaaa). Null quando a fonte não dá
   *  data — todo "A Comprovar" e todo "Desativado" do CAUC. */
  validade?: string | null;
  /** Tradução do título oficial do grupo, para quem não vive o extrato. Só CAUC. */
  grupo_glossa?: string;
  /** Significado oficial de um status traiçoeiro. "Desativado" NÃO é dispensa. */
  nota?: string;
}

interface CaucResp {
  tem_dados: boolean;
  nome?: string;
  uf?: string;
  ibge?: string;
  populacao?: number;
  data_pesquisa?: string | null;
  regular?: boolean;
  pendencias?: number;
  pendencias_codigos?: string[];
  itens?: Item[];
  atualizado_em?: string | null;
}

/** Um cadastro do CAGEC. O município NÃO é uma linha só: prefeitura, Fundo
 *  Municipal de Saúde, FMAS e consórcios têm CRC próprio, e cada um trava
 *  APENAS o seu convênio — prefeitura regular não destrava o convênio da saúde
 *  se o fundo estiver irregular. */
interface Entidade {
  nome: string;
  cnpj?: string | null;
  tipo?: string | null;
  situacao?: string | null;
  regular?: boolean | null;
  validade?: string | null;
  itens?: Item[];
  pendencias?: number;
  numero_cadastro?: string | null;
  principal: boolean;
  data_pesquisa?: string | null;
  crc_em?: string | null;
  crc_erro?: string | null;
  detalhe_do_crc?: boolean;
}

interface CagecResp {
  tem_dados: boolean;
  motivo?: string;
  nome?: string;
  uf?: string;
  cnpj?: string;
  situacao?: string;
  regular?: boolean;
  validade?: string | null;
  itens?: Item[];
  pendencias?: number;
  pendencias_codigos?: string[];
  data_pesquisa?: string | null;
  atualizado_em?: string | null;
  /** Todas as entidades, a principal inclusive. Os campos de cima continuam
   *  sendo os da principal — contrato antigo intacto. */
  entidades?: Entidade[];
  pendencias_outras_entidades?: number;
  /** Procedência do detalhamento. A lista de obrigações não vem da consulta
   *  pública — vem do CRC em PDF. `crc_em` é a data da última emissão que
   *  conseguimos ler; `crc_erro`, a frase do próprio portal quando ele recusa. */
  crc_em?: string | null;
  crc_erro?: string | null;
  detalhe_do_crc?: boolean;
}

/** SICONFI / Tesouro Nacional — `GET /api/siconfi`. A terceira leitura da mesma
 *  pergunta: além de estar em dia (CAUC) e habilitado no estado (CAGEC/CHE), o
 *  município tem capacidade de pagamento para tomar crédito? */
interface SiconfiResp {
  tem_dados: boolean;
  motivo?: string;
  ultima_entrega?: string | null;
  exercicios?: Array<{
    exercicio: number;
    total: number;
    entregaveis: string[];
    entregas: Array<{
      entregavel: string; periodo: number; periodicidade?: string | null;
      status?: string | null; entregue_em?: string | null; forma_envio?: string | null;
    }>;
  }>;
  capag?: {
    exercicio: number;
    posicao?: string | null;
    nota?: string | null;
    /** A consequência financeira da nota, do servidor — nunca montada aqui. */
    significado?: string | null;
    indicadores: Array<{
      chave: string; titulo: string; descricao: string;
      valor?: number | null; nota?: string | null;
    }>;
    icf?: string | null;
    observacao?: string | null;
    atualizado_em?: string | null;
    /** ⭐ O QUE A PLANILHA DO TESOURO TRAZ E A TELA IGNORAVA. Estava tudo em
     *  `raw_data` desde a primeira coleta; o servidor passou a expor. É o que
     *  responde as perguntas que a nota sozinha não responde: de que ano-base
     *  ela é, por que é A+ e não A, se houve rebaixamento, e se o município
     *  tem as entregas que o próprio cálculo exige. */
    origem_nota?: string | null;
    /** "Aicf" é a nota máxima do Indicador da Qualidade da Informação Contábil
     *  e Fiscal (ICF) no Siconfi — e é dele que vem o "+" do A+. */
    icf_maximo?: boolean;
    publicou_rgf?: string | null;
    publicou_rreo?: string | null;
    dca?: Record<string, string> | null;
    ressalvas?: string[];
  } | null;
}

/** CADASTROS NEGATIVOS — `GET /api/cadastros-negativos`. A quarta pergunta:
 *  não "está em dia?", e sim "existe pendência INSCRITA contra o ente?".
 *
 *  ⚠️ Uma linha por ENTIDADE e por cadastro, e a que importa pode não ser a da
 *  prefeitura: a única inscrição real da carteira em 07/09/2026 é do Fundo
 *  Municipal de Saúde de Nova Palma — que nem cadastro estadual tem. */
interface NegativoItem {
  cnpj: string;
  entidade?: string | null;
  uf?: string | null;
  /** 'CADIN-MG' · 'CADIN-RS' · 'CFIL-RS' */
  fonte: string;
  /** 'regular' | 'pendente' | 'indeterminado'. ⚠️ `indeterminado` NÃO é "nada
   *  consta": é a certidão que saiu e cujo texto não foi reconhecido. */
  tipo?: string | null;
  situacao?: string | null;
  quantidade?: number | null;
  /** Quem inscreveu, quando e o contato para sanar. Só vem quando HÁ pendência,
   *  e é o que transforma "você está travado" em "ligue para tal órgão". */
  detalhes?: {
    orgao?: string; inscrito_em?: string; quantidade?: number; contato?: string;
  } | null;
  consultado_em?: string | null;
  erro?: string | null;
}

interface NegativosResp {
  tem_dados: boolean;
  uf?: string;
  motivo?: string;
  /** O que EXISTE para este estado, mesmo sem coleta — é o que separa
   *  "consultamos e nada consta" de "não acompanhamos este estado". */
  cadastros_previstos?: string[];
  catalogo?: Record<string, {
    sigla: string; nome: string; uf: string; orgao?: string; lei?: string;
    trava?: string; origem?: string;
  }>;
  itens?: NegativoItem[];
  limpo?: boolean;
  pendencias?: number;
  indeterminados?: number;
  consultado_em?: string | null;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleDateString("pt-BR", { timeZone: "UTC" }); }
  catch { return iso.slice(0, 10); }
}

/** "Atualizado em <data> <hora>", ao lado do nome da fonte.
 *
 *  ⚠️ O CAMPO É `atualizado_em` (TIMESTAMPTZ, hora da NOSSA coleta) e o fuso é
 *  Brasília, cravado em `formatDataHora`. Não use o `fmtDate` daqui: ele
 *  formata em `timeZone: "UTC"` — correto para data pura vinda do banco, errado
 *  para um instante, porque mostraria a hora do servidor (3h à frente).
 *
 *  O rodapé de cada esfera dizia isto em texto miúdo no fim da lista. Subiu
 *  para o cabeçalho porque a pergunta "isto está atualizado?" é a primeira que
 *  se faz ao abrir a tela, não a última. */
function SeloColeta({ em }: { em?: string | null }) {
  if (!em) return null;
  const h = horasDesde(em);
  const atrasado = h !== null && h > 26;
  return (
    <span
      className="text-[10px]"
      /* `--bi-warn-ink`: em texto de 10px o token de exibição não tem
         contraste, e é a regra que todos os outros seis usos de warn neste
         arquivo já seguem. */
      style={{ color: atrasado ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}
      title={atrasado ? "Sem coleta nova há mais de um dia" : undefined}
    >
      Atualizado em {formatDataHora(em)}
    </span>
  );
}

function agrupar(itens: Item[]): Array<[string, Item[]]> {
  const m = new Map<string, Item[]>();
  for (const it of itens) {
    const g = it.grupo || "Exigências";
    if (!m.has(g)) m.set(g, []);
    m.get(g)!.push(it);
  }
  return [...m.entries()];
}

/** Banner de situação da esfera — mesmo formato nas duas colunas.
 *
 *  Regular é CINZA de propósito: estar em dia é o estado normal e não pede
 *  ação. O vermelho fica reservado ao impedimento, que é a única informação
 *  desta tela capaz de fazer o gestor levantar da cadeira. */
function Situacao({
  regular, titulo, detalhe,
}: { regular: boolean; titulo: string; detalhe: string }) {
  return (
    /* `pt-3` sem `pb`: a margem que o BlocoHead já traz embaixo fecha o cartão.
       Anular com `mb-0` seria disputar a mesma propriedade com a peça, e quem
       ganha aí depende da ordem em que o Tailwind emite as classes. */
    /* CARTÃO INTEIRO EM VERMELHO quando há impedimento, não só o texto.
       Este é o primeiro bloco da tela: quem abre o módulo tem que ver que há
       algo errado ANTES de ler qualquer palavra. Com o cartão branco e só a
       frase em vermelho, o alerta competia em peso com o cabeçalho ao lado.
       O valor é o MESMO da faixa de irregularidade do Painel
       (components/bi/abas.tsx) — um vermelho lavado, que chama sem gritar.
       Não vale o inverso: cartão verde quando está regular pintaria a tela de
       cor no estado normal, que é o que esta identidade evita. */
    <Bloco
      className="px-3 pt-3"
      style={regular ? undefined : {
        background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
        borderColor: "color-mix(in oklab, var(--bi-crit) 28%, transparent)",
      }}
    >
      <BlocoHead
        icon={regular ? ShieldCheck : ShieldAlert}
        titulo={
          <span style={regular ? undefined : { color: "var(--bi-crit-ink)" }}>{titulo}</span>
        }
        sub={detalhe}
        right={
          /* Verde no "Regular" pelo mesmo motivo do ✔ da lista: nesta tela o
             cinza ja tem dono (o "Desativado"), e a mesma palavra nao pode
             ter duas cores em dois cantos da mesma tela. */
          <Selo tom={regular ? "ok" : "critico"}>
            {regular ? "Regular" : "Impedimento"}
          </Selo>
        }
      />
    </Bloco>
  );
}

/** Aviso de que a lista de obrigações do cadastro estadual NÃO está completa.
 *
 *  ⚠️ NASCEU MINEIRO, E A COPY NÃO PODE CONTINUAR SENDO. Em MG o detalhamento
 *  vem do CRC em PDF, e era isso que o texto dizia. Desde 08/2026 esta tela
 *  também serve o CHE gaúcho (`ingestion/che_rs.py`), onde as validades vêm
 *  direto do JSON público — falar de "CRC do portal do CAGEC" para um prefeito
 *  do Rio Grande do Sul é o mesmo defeito que `lib/estadual.ts` existe para
 *  fechar. O texto passa a dizer "certificado do cadastro estadual", que é
 *  verdadeiro nos dois; o nome local sai de `tituloEstadual(uf)`.
 *
 *  Por que existe: em MG a lista detalhada não vem da consulta pública, vem do
 *  CRC em PDF. Em 01/08/2026 o portal do Estado passou a recusar a emissão para todo
 *  mundo ("Não foi possível recuperar dados do Convenente/Parceiro para geração
 *  do relatório" — reproduzido 9 vezes em 9, inclusive para Belo Horizonte), e
 *  a tela passou a exibir as duas linhas de fallback COMO SE FOSSEM o cadastro
 *  inteiro. Quem olhou viu um CAGEC com duas exigências e nenhuma pista de que
 *  faltavam 28 — inclusive o FGTS vencido, que é justamente o que trava o
 *  convênio. Uma tela que não sabe precisa dizer que não sabe. */
function AvisoCrc({ crcErro, crcEm, doCrc }: {
  crcErro?: string | null; crcEm?: string | null; doCrc?: boolean;
}) {
  // O gate é `doCrc`, NÃO `crcErro`. Condicionar tudo ao erro deixaria a tela
  // MUDA justamente nas linhas que já estavam no banco quando a coluna nasceu
  // (crc_erro NULL) — que é o estado de Monte Sião neste momento: sem
  // detalhamento, sem aviso, contando 2 documentos como se fosse o cadastro.
  // `doCrc === false` é a afirmação honesta: isto aqui não é o certificado.
  const semCrc = doCrc === false;
  if (!semCrc && !crcErro) return null;
  return (
    /* Um dos poucos lugares com cor: "a tela não sabe o que está mostrando" é
       alerta, e o aviso perde a função se ficar cinza no meio do cinza.
       O raio vem do token dos cartões rasos — este bloco convive com eles, e
       raio próprio era exatamente o que espalhava seis cantos diferentes. */
    <div
      className="border p-2.5"
      style={{
        borderRadius: "var(--bi-radius-sm)",
        borderColor: "color-mix(in oklab, var(--bi-warn) 35%, transparent)",
        background: "color-mix(in oklab, var(--bi-warn) 8%, transparent)",
      }}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-[2px] size-3.5 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
        <div className="min-w-0 text-[10px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          <div className="text-[11px] font-semibold" style={{ color: "var(--bi-text)" }}>
            {semCrc
              ? "Documentos não conferidos — certificado indisponível"
              : `Documentos conferidos em ${fmtDate(crcEm)} — leitura nova indisponível`}
          </div>
          <div className="mt-0.5">
            A lista de documentos e suas validades vem do certificado emitido pelo
            portal do cadastro estadual.{" "}
            {crcErro
              ? <>Nesta consulta ele não saiu. O portal respondeu: <em>“{crcErro}”</em></>
              : <>Nesta consulta ele não pôde ser lido.</>}
          </div>
          <div className="mt-1">
            {semCrc
              ? <>Abaixo aparece <strong>apenas</strong> o que a consulta pública mostra —
                  a situação do cadastro, sem os documentos. Não é a lista de exigências.</>
              : <>A lista abaixo é da leitura de <strong>{fmtDate(crcEm)}</strong> e pode
                  estar desatualizada: um documento pode ter vencido depois disso.</>}
            {" "}A situação e o impedimento acima continuam atualizados.
          </div>
        </div>
      </div>
    </div>
  );
}

/** Obrigação marcada "Vigente" cujo prazo já passou.
 *
 *  Acontece com lista PRESERVADA: o CRC de 01/08 diz que a certidão vale até
 *  10/08, e em 20/08 continuamos exibindo a mesma linha em verde. Pintar de
 *  verde certidão vencida é a pior saída possível — o gestor confia e perde a
 *  parcela. Só um CRC novo poderia reclassificar; até lá, a linha vira alerta. */
function venceu(validade?: string | null): boolean {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((validade || "").trim());
  if (!m) return false;
  const h = new Date();
  return new Date(+m[3], +m[2] - 1, +m[1]) < new Date(h.getFullYear(), h.getMonth(), h.getDate());
}

/** Uma linha é alerta quando trava convênio: pendência impeditiva, ou "Vigente"
 *  com prazo já vencido (só CAGEC — ver `venceu`). Sai daqui, e não de cada
 *  ponto da tela, para o contador do grupo e o realce da linha não divergirem. */
function alerta(it: Item, esfera: "cauc" | "cagec"): "critico" | "atencao" | null {
  if (it.tipo === "pendente") return "critico";
  if (esfera === "cagec" && it.tipo === "regular" && venceu(it.validade)) return "atencao";
  return null;
}

/** Os DEMAIS cadastros do município no CAGEC (fundos, autarquias, consórcios).
 *
 *  Eles já eram coletados e já vinham na resposta da API — a tela é que lia só
 *  os campos do topo, que são os da prefeitura. Resultado: o Fundo Municipal de
 *  Saúde de Monte Sião (CNPJ 11.875.540/0001-35, cadastro 11896, REGULAR) era
 *  invisível, e o secretário de saúde não tinha como saber o estado do cadastro
 *  que trava justamente o convênio dele.
 *
 *  A situação de cada um fica VISÍVEL sem abrir — é a informação que decide
 *  ação. O detalhe item a item fica dentro do `details` para não empurrar a
 *  coluna da prefeitura para fora da tela. */
/** ⚠️ A NOTA SOZINHA NÃO INFORMA. "C" não diz nada a quem não vive a Portaria
 *  MF 501/2021; o que muda a decisão do gestor é a frase ao lado — apta, ou NÃO
 *  apta, a contratar crédito com garantia da União. Por isso o `significado`
 *  vem do servidor e é exibido junto, sempre. */
function Capag({ capag }: { capag: NonNullable<SiconfiResp["capag"]> }) {
  const nota = (capag.nota || "").toUpperCase();
  // Só duas famílias importam para a decisão: A/B destravam a garantia da
  // União, C/D não. Nada de escala de cinco cores para uma escolha binária.
  const apta = nota.startsWith("A") || nota.startsWith("B");
  /* MESMA DISCIPLINA DE COR DO RESTO DA TELA (ver `Situacao` acima): cartão
     inteiro em vermelho quando há impedimento, e NENHUMA cor quando está tudo
     bem. Pintar de verde a nota A+ encheria de cor o estado normal, que é o
     que esta identidade evita — e faria a nota C, que é a que importa, brigar
     por atenção com uma dúzia de verdes. Os mesmos valores da faixa de
     irregularidade do Painel. */
  const impedido = !!nota && !apta;

  return (
    <Bloco
      className="p-4"
      style={impedido ? {
        background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
        borderColor: "color-mix(in oklab, var(--bi-crit) 28%, transparent)",
      } : undefined}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold leading-none"
                style={{ color: impedido ? "var(--bi-crit-ink)" : "var(--bi-text)" }}>
            {capag.nota || "—"}
          </span>
          <span className="text-[11px] font-semibold uppercase tracking-wide"
                style={{ color: "var(--bi-muted)" }}>
            CAPAG
          </span>
        </div>
        <p className="min-w-0 flex-1 text-[12px] leading-snug" style={{ color: "var(--bi-text)" }}>
          {capag.significado
            ? <>Município <b>{capag.significado}</b>.</>
            : "Capacidade de pagamento publicada pelo Tesouro Nacional."}
          {capag.posicao && (
            <span style={{ color: "var(--bi-muted)" }}>
              {" "}Posição de {fmtDate(capag.posicao)}.
            </span>
          )}
        </p>
        {nota && (
          <Selo tom={apta ? "ok" : "critico"}>
            {apta ? "Pode tomar crédito" : "Sem garantia da União"}
          </Selo>
        )}
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {capag.indicadores.map((i) => (
          <div key={i.chave} className="rounded-md px-2.5 py-2"
               style={{ background: "var(--bi-surface)" }}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="bi-title text-[12px]">{i.titulo}</span>
              <span className="text-[13px] font-bold"
                    style={{ color: "var(--bi-text)" }}>{i.nota || "—"}</span>
            </div>
            <div className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
              {i.descricao}
            </div>
            {i.valor != null && (
              /* Três casas porque o indicador é uma razão, não dinheiro — e
                 porque o SINAL importa: liquidez negativa (obrigações acima da
                 disponibilidade de caixa) é o que costuma derrubar a nota. */
              <div className="mt-0.5 text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                {i.valor.toLocaleString("pt-BR", {
                  minimumFractionDigits: 3, maximumFractionDigits: 3,
                })}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* ⭐ O RESTO DA PLANILHA. Estava em `raw_data` desde a primeira coleta e
          nunca chegou ao gestor. Responde o que a nota sozinha não responde. */}
      <div className="mt-3 space-y-1.5 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
        {/* Por que A+ e não A — a pergunta que o "+" provoca. */}
        {capag.icf && (
          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            <b>ICF {capag.icf}</b> — nota do município no{" "}
            <b>Indicador da Qualidade da Informação Contábil e Fiscal</b> do Siconfi.
            {capag.icf_maximo
              ? <> É a nota máxima, e é dela que vem o <b>“+”</b>: nota A ou B na CAPAG
                  somada a <i>Aicf</i> no ICF resulta em A+ ou B+.</>
              : <> O “+” da CAPAG (A+ / B+) exige a nota máxima <i>Aicf</i> aqui.</>}
          </p>
        )}
        {capag.origem_nota && (
          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            Base do cálculo: <b>{capag.origem_nota}</b>
            {/* A data da posição é quando o Tesouro PUBLICOU; o ano-base é o
                exercício de onde saíram os números. Confundir os dois faz o
                gestor achar que a nota reflete o ano corrente. */}
            {capag.posicao ? <> · publicada na posição de {fmtDate(capag.posicao)}</> : null}.
          </p>
        )}

        {/* As entregas que o PRÓPRIO cálculo exige. "Não" aqui explica nota
            ausente ou rebaixada melhor que qualquer texto nosso — e liga esta
            aba à lista de contas entregues logo abaixo. */}
        {(capag.publicou_rreo || capag.publicou_rgf || capag.dca) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]"
               style={{ color: "var(--bi-muted)" }}>
            <span style={{ color: "var(--bi-faint)" }}>Pré-requisitos do cálculo:</span>
            {capag.publicou_rreo && <span>RREO publicado: <b>{capag.publicou_rreo}</b></span>}
            {capag.publicou_rgf && <span>RGF publicado: <b>{capag.publicou_rgf}</b></span>}
            {Object.entries(capag.dca || {}).map(([ano, sim]) => (
              <span key={ano}>DCA {ano}: <b>{sim}</b></span>
            ))}
          </div>
        )}

        {/* Ressalvas metodológicas: quando preenchidas, explicam nota estranha.
            Vazio é o normal — por isso só aparecem quando existem. */}
        {!!capag.ressalvas?.length && (
          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-warn-ink)" }}>
            <b>Ressalvas do Tesouro:</b> {capag.ressalvas.join(" · ")}.
          </p>
        )}
        {capag.observacao && (
          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            {capag.observacao}
          </p>
        )}
        <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
          Metodologia da Portaria Normativa MF nº 1.583/2023: três indicadores —
          endividamento, poupança corrente e liquidez. A nota abre ou fecha crédito
          com garantia da União.
        </p>
      </div>
    </Bloco>
  );
}

/** As contas entregues ao Tesouro no exercício mais recente.
 *
 *  ⚠️ NÃO se filtra por `status`: RREO, RGF e DCA vêm com 'HO' (homologado) e
 *  as MSC vêm SEM status nenhum — as duas entregues. Quem prova a entrega é a
 *  data, e foi por isso que o coletor guarda as duas coisas. */
const PERIODICIDADE: Record<string, string> = {
  M: "mensal", B: "bimestral", Q: "quadrimestral", S: "semestral", A: "anual",
};

function ContasNoTesouro({ ano }: { ano: NonNullable<SiconfiResp["exercicios"]>[number] }) {
  /* ⚠️ ABRE UM ENTREGÁVEL POR VEZ, e não a lista inteira: são 22 envios num ano
     normal. O resumo fechado responde "ele está prestando contas?" e o detalhe
     responde "o que faltou no 3º bimestre?" — que é a pergunta que sobra depois
     do CAUC dizer "irregular na obrigação 3.2.2" sem dizer o que faltou. */
  const [aberto, setAberto] = useState<string | null>(null);
  const porEntregavel = new Map<string, {
    total: number; ultima?: string | null;
    envios: typeof ano.entregas;
  }>();
  for (const e of ano.entregas) {
    const atual = porEntregavel.get(e.entregavel) || { total: 0, ultima: null, envios: [] };
    atual.total += 1;
    atual.envios.push(e);
    if (e.entregue_em && (!atual.ultima || e.entregue_em > atual.ultima)) {
      atual.ultima = e.entregue_em;
    }
    porEntregavel.set(e.entregavel, atual);
  }
  return (
    <Bloco className="p-4">
      <BlocoHead
        titulo={`Contas entregues ao Tesouro — ${ano.exercicio}`}
        sub={`${ano.total} envio(s) da prefeitura em ${ano.entregaveis.length} obrigação(ões)`}
      />
      <Lista>
        {[...porEntregavel.entries()].map(([nome, d]) => {
          const abertoAqui = aberto === nome;
          const per = d.envios.find((e) => e.periodicidade)?.periodicidade || "";
          return (
            <li key={nome} className="py-1">
              <button
                type="button"
                onClick={() => setAberto(abertoAqui ? null : nome)}
                className="flex w-full flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 text-left"
                aria-expanded={abertoAqui}
              >
                <span className="min-w-0 text-[12px]" style={{ color: "var(--bi-text)" }}>
                  {nome}
                  {PERIODICIDADE[per] && (
                    <span className="ml-1.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                      {PERIODICIDADE[per]}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
                  {d.total} envio(s)
                  {d.ultima ? ` · último em ${fmtDate(d.ultima)}` : ""}
                </span>
              </button>
              {abertoAqui && (
                <ul className="mt-1 space-y-0.5 rounded-lg px-3 py-2"
                    style={{ background: "var(--bi-surface)" }}>
                  {[...d.envios]
                    .sort((a, b) => a.periodo - b.periodo)
                    .map((e, i) => (
                      <li key={i}
                          className="flex flex-wrap items-baseline justify-between gap-x-3 text-[11px]"
                          style={{ color: "var(--bi-muted)" }}>
                        <span style={{ color: "var(--bi-text)" }}>
                          {/* O número do período é o que o gestor procura no
                              recibo: "o 3º bimestre foi entregue?" */}
                          {e.periodo}º período
                        </span>
                        <span className="tabular-nums">
                          {e.entregue_em ? fmtDate(e.entregue_em) : "sem data"}
                          {/* ⚠️ 'HO' (homologado) só aparece em RREO/RGF/DCA. A MSC
                              vem SEM status e está entregue: quem prova a entrega é
                              a data, e por isso o status vem depois dela, como
                              informação adicional. */}
                          {e.status ? ` · ${e.status}` : ""}
                          {e.forma_envio ? ` · ${e.forma_envio}` : ""}
                        </span>
                      </li>
                    ))}
                </ul>
              )}
            </li>
          );
        })}
      </Lista>
      {/* O nome com "Simplificado" não é detalhe: é o que explica por que a
          cadência deste município difere da do vizinho. Ver ingestion/siconfi.py. */}
      {ano.entregaveis.some((n) => n.includes("Simplificado")) && (
        <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
          Este município entrega os demonstrativos na versão <b>Simplificada</b>, permitida
          aos entes de menor porte — por isso a periodicidade difere da de municípios maiores.
        </p>
      )}
    </Bloco>
  );
}

/** Lista de exigências por bloco, no MESMO desenho do extrato oficial:
 *  código · Item Legal · **Situação** · **Validade**.
 *
 *  GRADE de largura fixa, não flex — pelo mesmo motivo do Painel: rótulo que
 *  quebra em duas linhas não pode empurrar as colunas da direita, e no CAGEC o
 *  código (de "CNPJ" a "AUTORIZ-ELETRONICA") deslocava o início de cada rótulo.
 *  É a mesma promessa do `<Campos>` das outras telas — coluna na mesma posição
 *  em todo lugar —, só que aqui o conteúdo é literalmente um extrato, e por isso
 *  continua grade e não vira cartão por exigência.
 *
 *  O CAGEC não tem coluna de código: aqueles identificadores são NOSSOS (o CRC
 *  não os imprime) e os informativos — os oito "Item 3.1.2 -…" — já vêm no
 *  próprio rótulo. */
function Exigencias({ itens, esfera = "cauc" }: { itens: Item[]; esfera?: "cauc" | "cagec" }) {
  if (!itens.length) {
    return <Vazio>Nenhuma exigência detalhada nesta esfera.</Vazio>;
  }
  const cols = esfera === "cauc"
    ? "grid-cols-[1.25rem_3rem_minmax(0,1fr)_7.5rem_6rem]"
    : "grid-cols-[1.25rem_minmax(0,1fr)_7.5rem_6rem]";
  return (
    <div className="space-y-2">
      {agrupar(itens).map(([grupo, lista]) => {
        const emAlerta = lista.filter((it) => alerta(it, esfera)).length;
        return (
          <Bloco key={grupo} className="p-3">
            {/* Título = o LITERAL do extrato ("III - Obrigações de
                Transparência"), para casar na conferência. A glosa embaixo,
                para quem não vive o documento. */}
            <BlocoHead
              titulo={grupo}
              sub={lista[0]?.grupo_glossa}
              right={
                emAlerta
                  ? <Selo tom="critico">{emAlerta} em alerta</Selo>
                  : <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                      {lista.length} {lista.length === 1 ? "item" : "itens"}
                    </span>
              }
            />
            <div
              className={`grid ${cols} items-end gap-x-3 border-b px-2 pb-1 text-[9px] uppercase tracking-wide`}
              style={{ borderColor: "var(--bi-line)", color: "var(--bi-faint)" }}
            >
              <span />
              {esfera === "cauc" && <span>Item</span>}
              <span>Item legal</span>
              <span>Situação</span>
              <span className="text-right">Validade</span>
            </div>
            {/* Sem divisória entre as linhas: o que separa é o espaço, e o que
                salta é o fundo das que estão em alerta. Régua em toda linha faz
                a grade inteira gritar no mesmo tom do problema. */}
            <div className="mt-1 flex flex-col gap-0.5">
              {lista.map((it) => {
                const nivel = alerta(it, esfera);
                const vencido = nivel === "atencao";
                // A situação vem escrita pela fonte; a classificação é a regra
                // única do sistema. `tipo === "pendente"` tem precedência porque
                // "A Comprovar" não parece alerta em texto nenhum — e é o que
                // trava a transferência.
                // VERDE de propósito em "Comprovado"/"Vigente", contra a regra
                // geral de "cor só em alerta". Decisão do dono, e o argumento
                // dele é melhor que o meu: nesta tela o CINZA já tem dono — é o
                // "Desativado", e inativo em cinza é convenção que o usuário
                // traz de todo sistema. Pintar o comprovado de cinza junto
                // apagava essa distinção, que é a mais útil da tela.
                // Aqui a cor não é enfeite: é o estado do documento.
                const tomStatus = nivel === "critico" ? "critico"
                  : vencido ? "atencao"
                  : it.tipo === "regular" ? "ok"
                  : it.tipo === "na" ? "neutro"
                  : situacaoTom(it.status);
                return (
                  <div
                    key={it.codigo}
                    className={`grid ${cols} items-start gap-x-3 rounded-lg px-2 py-1.5`}
                    style={nivel
                      ? { background: `color-mix(in oklab, var(--bi-${nivel === "critico" ? "crit" : "warn"}) 9%, transparent)` }
                      : undefined}
                  >
                    {/* Símbolo por esfera, como nos dois documentos: o CAUC marca
                        Comprovado / A Comprovar / Desativado; o CAGEC, Vigente /
                        Vencido. Só os dois primeiros têm cor — o ✔ é cinza porque
                        trinta ✔ verdes escondem o único ⚠ que importa. */}
                    <span className="mt-[3px]">
                      {nivel === "critico"
                        ? (esfera === "cagec"
                            ? <AlertTriangle className="size-3.5" style={{ color: "var(--bi-crit-ink)" }} />
                            : <AlertCircle className="size-3.5" style={{ color: "var(--bi-crit-ink)" }} />)
                        : vencido ? <Clock className="size-3.5" style={{ color: "var(--bi-warn-ink)" }} />
                        : it.tipo === "regular" ? <Check className="size-3.5" style={{ color: "var(--bi-ok-ink)" }} />
                        : <Ban className="size-3.5" style={{ color: "var(--bi-faint)" }} />}
                    </span>
                    {esfera === "cauc" && (
                      /* `font-mono` e não `bi-num`: "1.3" aqui é identificador do
                         extrato, não número — negrito tabular o promoveria acima
                         do próprio item legal. */
                      <span className="font-mono text-[11px] leading-5" style={{ color: "var(--bi-faint)" }}>
                        {it.codigo}
                      </span>
                    )}
                    <div className="min-w-0">
                      <div
                        className={`text-[13px] leading-snug ${nivel === "critico" ? "font-medium" : ""}`}
                        style={{ color: nivel === "critico" ? "var(--bi-crit-ink)" : "var(--bi-text)" }}
                      >
                        {it.label}
                      </div>
                      {/* A nota existe porque duas palavras do extrato enganam:
                          "Desativado" não é dispensa (é falha da ferramenta, para
                          TODOS os entes) e "A Comprovar" não acusa o município. */}
                      {it.nota && (
                        <div className="mt-0.5 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                          {it.nota}
                        </div>
                      )}
                    </div>
                    <span className="min-w-0">
                      {/* O documento dizia "Vigente" quando foi lido; hoje o prazo
                          passou. Repetir "Vigente" seria transcrever fielmente uma
                          informação que deixou de ser verdade. */}
                      <Selo tom={tomStatus} title={vencido ? `A fonte registrou “${it.status}”, mas a validade já passou.` : it.status}>
                        {vencido ? "Prazo vencido" : it.status}
                      </Selo>
                    </span>
                    {/* Validade SEMPRE presente, como no extrato. "—" quando a fonte
                        não dá data: ausência de data é informação, não buraco. */}
                    <span
                      className="bi-num whitespace-nowrap text-right text-[11px] leading-5"
                      style={{
                        color: nivel === "critico" ? "var(--bi-crit-ink)"
                          : vencido ? "var(--bi-warn-ink)"
                          : "var(--bi-muted)",
                      }}
                    >
                      {it.validade || "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          </Bloco>
        );
      })}
    </div>
  );
}

/** Contas julgadas irregulares no tribunal de contas do estado.
 *  ⚠️ INDÍCIO, não documento — ver `migrations/add_contas_irregulares.sql`. */
interface ContasResp {
  tem_dados: boolean;
  total: number;
  prefeitura: number;
  autarquias: number;
  de_prefeito: number;
  fonte: string | null;
  itens: Array<{
    entidade: string | null;
    responsavel: string | null;
    assunto: string | null;
    competencia: string | null;
    processo: string | null;
    dt_julgamento: string | null;
    tipo_lista: string | null;
    url: string | null;
  }>;
}

/** As SUB-ABAS de entidade: prefeitura, fundo de saúde, FMAS.
 *
 *  ⚠️ Elas existem porque cada entidade tem cadastro PRÓPRIO e trava apenas o
 *  SEU convênio — prefeitura regular não libera o convênio da saúde com o fundo
 *  irregular. Enquanto tudo ficava numa lista só, a situação do fundo era uma
 *  linha discreta embaixo de um banner verde. A marca vermelha no rótulo é o
 *  que permite escolher a aba certa sem abrir as três. */
function SubAbasEntidade({ opcoes, ativa, onChange }: {
  opcoes: Array<{ id: string; label: string; alerta?: boolean }>;
  ativa: string;
  onChange: (id: string) => void;
}) {
  if (opcoes.length < 2) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="tablist">
      {opcoes.map((o) => {
        const sel = o.id === ativa;
        return (
          <button
            key={o.id}
            type="button"
            role="tab"
            aria-selected={sel}
            onClick={() => onChange(o.id)}
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition-colors"
            style={{
              background: sel ? "var(--bi-surface-2)" : "transparent",
              border: `1px solid ${sel ? "var(--bi-line-strong)" : "var(--bi-line)"}`,
              color: sel ? "var(--bi-text)" : "var(--bi-muted)",
            }}
          >
            {o.alerta && (
              <span aria-hidden style={{ color: "var(--bi-crit-ink)" }}>●</span>
            )}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** Um cadastro negativo (CADIN ou CFIL) para UMA entidade.
 *
 *  ⚠️ TRÊS ESTADOS, e a diferença entre eles é o produto:
 *    pendente       — consta inscrição: trava, e a tela diz quem inscreveu;
 *    regular        — nada consta NA DATA da consulta (não há validade);
 *    indeterminado  — a certidão saiu e não conseguimos ler. Verde aqui seria
 *                     afirmar ausência de inscrição a partir do que não se leu. */
function CadastroNegativo({ item, cat }: {
  item: NegativoItem;
  cat?: { sigla: string; nome: string; orgao?: string; lei?: string; trava?: string; origem?: string };
}) {
  const pendente = item.tipo === "pendente";
  const indefinido = item.tipo === "indeterminado" || !item.tipo;
  const tom = pendente ? "crit" : indefinido ? "warn" : "ok";
  const d = item.detalhes || null;
  return (
    <Bloco
      className="p-4"
      style={{
        background: `color-mix(in oklab, var(--bi-${tom}) 8%, transparent)`,
        borderColor: `color-mix(in oklab, var(--bi-${tom}) 26%, transparent)`,
      }}
    >
      <div className="flex items-start gap-2.5">
        {pendente ? <AlertTriangle className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-crit-ink)" }} />
          : indefinido ? <Info className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
          : <Check className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-ok-ink)" }} />}
        <div className="min-w-0 space-y-1.5">
          <div className="bi-title text-[13px] leading-tight"
               style={{ color: `var(--bi-${tom}-ink)` }}>
            {item.situacao || "Sem informação"}
            {cat ? ` — ${cat.sigla}` : ""}
          </div>
          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            {item.entidade || "Entidade"}
            {cat?.trava && (pendente ? <> — a inscrição <b>{cat.trava}</b>.</> : <> · a inscrição {cat.trava}.</>)}
          </p>

          {/* O QUE FAZER. Sem este quadro a tela diz que o ente está travado e
              não diz por quem — o gestor fica sabendo do problema e não tem a
              quem ligar. Só existe na certidão COM pendência. */}
          {d && (
            <div className="mt-1 space-y-0.5 rounded-lg px-3 py-2"
                 style={{ background: "var(--bi-surface)" }}>
              {d.orgao && (
                <div className="text-[11px]" style={{ color: "var(--bi-text)" }}>
                  Inscrito por <b>{d.orgao}</b>
                  {d.inscrito_em ? <> em {d.inscrito_em}</> : null}
                  {d.quantidade ? <> · {d.quantidade} pendência(s)</> : null}
                </div>
              )}
              {d.contato && (
                <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                  Contato para sanar: <span style={{ color: "var(--bi-text)" }}>{d.contato}</span>
                </div>
              )}
            </div>
          )}

          {item.erro && (
            <p className="text-[10px] leading-snug" style={{ color: "var(--bi-warn-ink)" }}>
              {item.erro}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px]"
               style={{ color: "var(--bi-faint)" }}>
            {/* ⚠️ A DATA NÃO É DETALHE AQUI. A certidão não tem validade: ela
                afirma a situação "na data de …". Sem este carimbo, uma consulta
                de duas semanas atrás passa por situação de hoje. */}
            <span>Consultado em {fmtDate(item.consultado_em)}</span>
            {item.cnpj && <span className="font-mono">CNPJ {item.cnpj}</span>}
            {cat?.lei && <span>{cat.lei}</span>}
            {cat?.orgao && <span>{cat.orgao}</span>}
          </div>
          {cat?.origem && (
            <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
              {cat.origem}
            </p>
          )}
        </div>
      </div>
    </Bloco>
  );
}

/** Contas julgadas irregulares no tribunal de contas do estado.
 *
 *  ⚠️ GANHOU ABA PRÓPRIA porque estava escondido: o bloco só era desenhado no
 *  ramo "estado sem fonte de cadastro" — ou seja, em MG e no RS, onde HÁ
 *  cadastro, ele nunca aparecia, mesmo com contas listadas.
 *
 *  ⚠️ E É INDÍCIO, não documento: a lista diz quem TEM conta julgada irregular
 *  e não atesta regularidade de quem não aparece nela. */
function ContasIrregulares({ contas }: { contas: ContasResp }) {
  if (!contas.tem_dados) {
    return (
      <Bloco className="p-4">
        <div className="flex items-start gap-2.5">
          <Info className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-faint)" }} />
          <div className="space-y-1.5">
            <div className="bi-title text-[13px] leading-tight">Nenhuma conta listada</div>
            <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
              Não há conta julgada irregular listada para este município na fonte que
              acompanhamos. <b>Isso não é atestado de regularidade</b>: a lista diz quem
              aparece nela, e não que quem não aparece está em dia.
            </p>
          </div>
        </div>
      </Bloco>
    );
  }
  return (
    <Bloco className="p-4">
      <div className="flex items-start gap-2.5">
        <Gavel className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
        <div className="min-w-0 space-y-1.5">
          <div className="bi-title text-[13px] leading-tight">
            {contas.total} conta(s) julgada(s) irregular(es) no {contas.fonte}
          </div>
          <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            {contas.prefeitura > 0
              ? <>{contas.prefeitura} da <b>prefeitura</b></>
              : <>nenhuma da prefeitura</>}
            {contas.autarquias > 0 && <> · {contas.autarquias} de autarquias e fundos</>}
            {contas.de_prefeito > 0 && <> · <b>{contas.de_prefeito} de prefeito ou ex-prefeito</b></>}
            .{" "}
            É <b>indício</b>, não a situação do município para convênio: a lista diz quem tem
            conta julgada irregular, e <b>não</b> atesta regularidade de quem não aparece nela.
          </p>
          <ul className="space-y-1 pt-0.5">
            {contas.itens.map((c, i) => (
              <li key={i} className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                <span style={{ color: "var(--bi-text)" }}>{c.entidade || "Prefeitura"}</span>
                {c.responsavel ? ` · ${c.responsavel}` : ""}
                {c.assunto ? ` · ${c.assunto}` : ""}
                {c.processo ? ` · proc. ${c.processo}` : ""}
                {c.url && (
                  <a href={c.url} target="_blank" rel="noopener noreferrer"
                     className="ml-1 inline-flex items-center gap-0.5"
                     style={{ color: "var(--bi-accent-ink)" }}>
                    ver <ExternalLink className="size-3" />
                  </a>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Bloco>
  );
}

export default function RegularidadePage() {
  const { municipioId } = useMunicipio();

  const [cauc, setCauc] = useState<CaucResp | null>(null);
  /* A UF vem do próprio extrato do CAUC (que é federal e cobre o país inteiro),
     e não de uma lista escrita aqui: é o dado que já está na tela. Enquanto ele
     não chegou, nada é anunciado — não se fala da cobertura antes de saber de
     onde é o município. */
  const [cagec, setCagec] = useState<CagecResp | null>(null);
  /* O cadastro estadual também traz a UF (inclusive quando ainda não há
     coleta) — serve de reserva se o extrato do CAUC não tiver chegado. */
  const ufDoMunicipio = (cauc?.uf || cagec?.uf || "").toUpperCase();
  /* Nome e cobertura vêm do mapa por UF (`lib/estadual.ts`), onde cada linha é
     pesquisada — e não de um `!== "MG"` escrito aqui. */
  const semFonteEstadual = !!ufDoMunicipio && !acompanhamosEstadual(ufDoMunicipio);
  /* ⚠️ TODA FRASE DESTA COLUNA CHAMA O CADASTRO PELO NOME DO ESTADO. O título
     já saía de `tituloEstadual`, mas o corpo dizia "Regular no CAGEC", "O CAGEC
     deste município..." e "cadastro de convenentes do Estado de Minas Gerais"
     — em cima do CHE de Santa Maria/RS. A sigla, o nome e o documento (CRC só
     existe em Minas) saem do mesmo mapa. */
  const siglaEst = siglaEstadual(ufDoMunicipio);
  const certificadoEst = certificadoEstadual(ufDoMunicipio);
  const nomeCadastroEst = CADASTRO_ESTADUAL[ufDoMunicipio]?.nome || "cadastro estadual de convenentes";
  /* ⚠️ FORA DO MEDIDOR, de propósito: a ausência de conta irregular NÃO é
     regularidade — é "sem conta irregular listada". Verde por isto colocaria um
     "apto" falso na frente de um prefeito. */
  const [contas, setContas] = useState<ContasResp | null>(null);
  const [tesouro, setTesouro] = useState<SiconfiResp | null>(null);
  const [negativos, setNegativos] = useState<NegativosResp | null>(null);
  const [loading, setLoading] = useState(true);
  /* ⚠️ A ABA VIVE NA URL (`?aba=`). Sem isso, um link mandado para o
     jurídico ("olha o CADIN do fundo") abre no CAUC, e a pessoa tem de
     procurar — e o F5 no meio de uma conferência joga de volta para a
     primeira aba. */
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [aba, setAbaState] = useState<string>(params.get("aba") || "cauc");
  const setAba = useCallback((id: string) => {
    setAbaState(id);
    const p = new URLSearchParams(params.toString());
    p.set("aba", id);
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  }, [params, pathname, router]);
  /* A entidade escolhida dentro da aba (prefeitura / fundo / autarquia). Fica
     por aba: quem está olhando o fundo no CADIN não quer voltar à prefeitura
     ao abrir o cadastro estadual. */
  const [entidadeAtiva, setEntidadeAtiva] = useState<Record<string, string>>({});
  const [consultando, setConsultando] = useState(false);

  useEffect(() => {
    // Busca de dados: os setState aqui são o "carregando" da primeira pintura e
    // a limpeza ao trocar de município — sincronização com fonte externa, não
    // render em cascata (mesma convenção do resto do app).
    if (!municipioId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCauc(null); setCagec(null); setContas(null); setTesouro(null);
      setLoading(false); return;
    }
    setLoading(true);
    // As esferas em paralelo, com allSettled: uma falhar não pode apagar as
    // outras da tela — são fontes independentes (Tesouro e SIGCON).
    Promise.allSettled([
      api.get<CaucResp>("/cauc", { params: { municipio_id: municipioId } }),
      api.get<CagecResp>("/cagec", { params: { municipio_id: municipioId } }),
      api.get<ContasResp>("/contas-irregulares", { params: { municipio_id: municipioId } }),
      api.get<SiconfiResp>("/siconfi", { params: { municipio_id: municipioId } }),
      api.get<NegativosResp>("/cadastros-negativos", { params: { municipio_id: municipioId } }),
    ]).then(([a, b, c, d, e]) => {
      setCauc(a.status === "fulfilled" ? a.value.data : null);
      setCagec(b.status === "fulfilled" ? b.value.data : null);
      setContas(c.status === "fulfilled" ? c.value.data : null);
      setTesouro(d.status === "fulfilled" ? d.value.data : null);
      setNegativos(e.status === "fulfilled" ? e.value.data : null);
    }).finally(() => setLoading(false));
  }, [municipioId]);

  /* ⚠️ SÓ NO RS, e o servidor recusa fora dele. Em Minas o CADIN vem dentro do
     CRC, e emitir CRC é a rodada do CAGEC (Playwright) — não cabe num clique.
     O botão existe porque a certidão gaúcha NÃO TEM VALIDADE: ela afirma a
     situação "na data de …", então numa reunião a de ontem não serve. */
  const consultarAgora = useCallback(async () => {
    if (!municipioId || consultando) return;
    setConsultando(true);
    try {
      const { data } = await api.post<NegativosResp>(
        "/cadastros-negativos/refresh", null, { params: { municipio_id: municipioId } });
      if (data?.tem_dados !== undefined) setNegativos(data);
    } catch {
      /* Silêncio proposital: o payload antigo continua na tela com o carimbo
         da data dele, que é honesto. Um erro vermelho aqui apagaria o dado
         bom por causa de um portal fora do ar. */
    } finally {
      setConsultando(false);
    }
  }, [municipioId, consultando]);

  /* ---------------------------------------------------------------------
     AS ABAS. Uma por CADASTRO, e não uma tela só com tudo empilhado.
     Antes eram duas colunas (CAUC | estadual) mais dois blocos soltos; com
     CADIN e CFIL entrando, e cada um deles tendo uma linha POR ENTIDADE, a
     página passaria de sessenta linhas de documento numa rolagem só.
     A regra do dono: "a pessoa entra no menu Regularidade e tem as abas".

     ⚠️ A ABA SÓ EXISTE ONDE O CADASTRO EXISTE. `cadastros_previstos` vem do
     servidor (por UF): CFIL é gaúcho, e uma aba vazia com esse nome num
     município mineiro afirmaria que falta coletar algo que não se aplica. */
  const negPorFonte = useMemo(() => {
    const m: Record<string, NegativoItem[]> = {};
    for (const i of negativos?.itens || []) (m[i.fonte] ||= []).push(i);
    return m;
  }, [negativos]);
  const fontesNegativas = useMemo(() => {
    const s = new Set<string>([...(negativos?.cadastros_previstos || []),
                               ...Object.keys(negPorFonte)]);
    return [...s];
  }, [negativos, negPorFonte]);
  const fontesCadin = fontesNegativas.filter((f) => f.startsWith("CADIN"));
  const fontesCfil = fontesNegativas.filter((f) => f.startsWith("CFIL"));
  /* As chaves de dependência dos `useMemo`: array não é comparável por
     identidade entre renders, e o lint exige expressão simples. */
  const chaveCadin = fontesCadin.join(",");
  const chaveCfil = fontesCfil.join(",");
  const alertaDe = (fontes: string[]) =>
    fontes.some((f) => (negPorFonte[f] || []).some((i) => i.tipo === "pendente"));

  const abas = useMemo(() => {
    const lista: Array<{ id: string; label: string; sub: string; alerta: boolean }> = [
      { id: "cauc", label: "CAUC", sub: "União",
        alerta: !!cauc?.tem_dados && !cauc.regular },
      { id: "estadual", label: siglaEst,
        sub: NOME_UF[ufDoMunicipio] || "estadual",
        /* O alerta considera TODAS as entidades: prefeitura regular com fundo
           irregular não é "em dia" — o convênio daquele fundo está travado. */
        alerta: !!cagec?.tem_dados
          && (cagec.regular === false
              || (cagec.entidades || []).some((e) => e.regular === false)) },
    ];
    if (fontesCadin.length)
      lista.push({ id: "cadin", label: "CADIN", sub: "cadastro informativo",
                   alerta: alertaDe(fontesCadin) });
    if (fontesCfil.length)
      lista.push({ id: "cfil", label: "CFIL", sub: "impedidos de licitar",
                   alerta: alertaDe(fontesCfil) });
    lista.push({ id: "contas", label: "Contas irregulares", sub: "tribunal de contas",
                 alerta: !!contas?.tem_dados && contas.total > 0 });
    lista.push({ id: "tesouro", label: "Tesouro Nacional", sub: "CAPAG e contas entregues",
                 alerta: false });
    return lista;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cauc, cagec, contas, negativos, siglaEst, ufDoMunicipio, chaveCadin, chaveCfil]);

  /* Aba de URL que não existe neste município (um link de Nova Palma aberto
     num ambiente de Minas pede `?aba=cfil`) volta para a primeira, em vez de
     desenhar a tela vazia. */
  useEffect(() => {
    if (!loading && abas.length && !abas.some((a) => a.id === aba)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setAbaState("cauc");
    }
  }, [abas, aba, loading]);

  /** As entidades de uma aba, com a prefeitura primeiro e a marca de quem tem
   *  pendência — é o que permite escolher a certa sem abrir as três. */
  const entidadesDaAba = useCallback((id: string) => {
    if (id === "estadual") {
      const es = cagec?.entidades || [];
      return es.map((e) => ({
        id: e.cnpj || e.nome || "",
        label: e.principal ? "Prefeitura" : (e.tipo || e.nome || "Entidade"),
        alerta: e.regular === false,
      }));
    }
    const fontes = id === "cadin" ? fontesCadin : id === "cfil" ? fontesCfil : [];
    const vistos = new Map<string, { id: string; label: string; alerta: boolean }>();
    for (const f of fontes) {
      for (const i of negPorFonte[f] || []) {
        const atual = vistos.get(i.cnpj);
        const alerta = i.tipo === "pendente" || atual?.alerta || false;
        vistos.set(i.cnpj, {
          id: i.cnpj,
          label: i.entidade || i.cnpj,
          alerta,
        });
      }
    }
    return [...vistos.values()];
  }, [cagec, negPorFonte, fontesCadin, fontesCfil]);

  const entidadeDa = (id: string) => {
    const opcoes = entidadesDaAba(id);
    const escolhida = entidadeAtiva[id];
    return opcoes.some((o) => o.id === escolhida) ? escolhida : (opcoes[0]?.id || "");
  };

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <TituloTela>Regularidade</TituloTela>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Exigências para assinar convênio, uma aba por cadastro: a <strong>federal</strong>{" "}
          (CAUC), a <strong>estadual</strong> — o cadastro de convenentes do estado deste
          município —, os <strong>cadastros negativos</strong> (CADIN, CFIL) e o{" "}
          <strong>Tesouro Nacional</strong> (CAPAG e contas entregues).
        </p>
      </div>

      {!municipioId && <Vazio>Selecione um município para ver a situação.</Vazio>}

      {municipioId && loading && (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      )}

      {/* A BARRA DE ABAS — mesmo desenho do Painel de Indicadores
          (`bi-folder-tab`), para o sistema ter UMA gramática de abas. O ponto
          vermelho no rótulo é o que faz a barra valer: sem ele, saber onde há
          pendência exigiria abrir as cinco. */}
      {municipioId && !loading && (
        <div
          className="bi-folder-tabs flex flex-wrap items-end gap-1 border-b"
          style={{ borderColor: "var(--bi-line)" }}
          role="tablist"
        >
          {abas.map((a) => (
            <button
              key={a.id}
              type="button"
              role="tab"
              aria-selected={a.id === aba}
              data-active={a.id === aba}
              className="bi-folder-tab text-[13px]"
              onClick={() => setAba(a.id)}
              title={a.sub}
            >
              <span className="inline-flex items-center gap-1.5">
                {a.alerta && (
                  <span aria-hidden style={{ color: "var(--bi-crit-ink)" }}>●</span>
                )}
                {a.label}
              </span>
            </button>
          ))}
        </div>
      )}

      {municipioId && !loading && (
        <div className="space-y-4">
          {/* ---------------- CAUC (federal) ---------------- */}
          <section className={aba === "cauc" ? "space-y-2.5" : "hidden"}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              {/* 14px é o tamanho de título do <BlocoHead>: este h2 encabeça a
                  coluna inteira e tem que ler como cabeçalho do sistema, não
                  como um degrau próprio. 15px não existia em nenhuma outra tela. */}
              <h2 className="bi-title text-[14px]">CAUC — União</h2>
              <SeloColeta em={cauc?.atualizado_em} />
              <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                Tesouro Nacional{cauc?.data_pesquisa ? ` · extrato de ${fmtDate(cauc.data_pesquisa)}` : ""}
              </span>
            </div>

            {!cauc?.tem_dados ? (
              <Vazio>
                Sem dados do CAUC para este município ainda. (A base é atualizada automaticamente.)
              </Vazio>
            ) : (
              <>
                <Situacao
                  regular={!!cauc.regular}
                  titulo={cauc.regular ? "Regular no CAUC" : `${cauc.pendencias} pendência(s) impeditiva(s)`}
                  detalhe={`${cauc.nome}/${cauc.uf}` + (cauc.regular
                    ? " — apto a receber transferências voluntárias da União."
                    : ` — itens ${(cauc.pendencias_codigos || []).join(", ")} podem travar transferências.`)}
                />
                <Exigencias itens={cauc.itens || []} esfera="cauc" />

              </>
            )}
          </section>

          {/* ---------------- Cadastro estadual (CAGEC em MG, CHE no RS) ---------------- */}
          <section className={aba === "estadual" ? "space-y-2.5" : "hidden"}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              {/* ⚠️ O TÍTULO É DO AMBIENTE ABERTO, e "CAGEC" é nome de Minas
                  (Decreto 44.293/2006) — não do produto. Num ambiente do ES ou
                  de GO nada aqui pode falar de Minas: o cliente trocou de
                  ambiente, e o ambiente é dele. */}
              <h2 className="bi-title text-[14px]">{tituloEstadual(ufDoMunicipio)}</h2>
              {!semFonteEstadual && <SeloColeta em={cagec?.atualizado_em} />}
              <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                {subtituloEstadual(ufDoMunicipio)}
              </span>
            </div>

            {semFonteEstadual ? (
              /* ⚠️ TRÊS ESTADOS DE COISA DIFERENTE, e a tela precisa separar:
                   "em dia / irregular"  — coletamos e sabemos;
                   "aguardando coleta"   — a fonte cobre este ente e ainda não veio;
                   "fora da nossa coleta" — a fonte que temos não responde por ele.
                 O terceiro caso é este. Dizer "aguardando" promete um dado que
                 não vai chegar; dizer "não se aplica" afirmaria que o município
                 NÃO TEM cadastro estadual — e disso não sabemos nada. Cadastro
                 estadual de convenentes existe em outros estados; o que é de
                 Minas é o portal que este sistema sabe consultar. */
              <Bloco className="p-4">
                <div className="flex items-start gap-2.5">
                  <Info className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-faint)" }} />
                  <div className="space-y-1.5">
                    <div className="bi-title text-[13px] leading-tight">
                      Ainda não acompanhado
                    </div>
                    <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      A regularidade estadual de <b>{tituloEstadual(ufDoMunicipio)}</b> ainda
                      não é acompanhada por este sistema — a consulta segue sendo no portal
                      do próprio Estado. A regularidade <b>federal</b> (CAUC, ao lado)
                      continua valendo normalmente.
                    </p>
                  </div>
                </div>

                {/* ⭐ O QUE TEMOS, mesmo sem o cadastro: contas julgadas
                    irregulares no tribunal de contas do estado.

                    ⚠️ A REDAÇÃO AQUI É O PRODUTO. Isto é INDÍCIO, e a tela tem
                    de dizer as duas coisas que ele NÃO significa: (a) não é a
                    situação do município para convênio; (b) nenhuma linha não
                    quer dizer regular. Um bloco mal escrito aqui vira "está
                    tudo certo" na cabeça de quem lê — que é o oposto do dado. */}
                {contas?.tem_dados && (
                  <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                    <div className="flex items-start gap-2.5">
                      <Gavel className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
                      <div className="min-w-0 space-y-1.5">
                        <div className="bi-title text-[13px] leading-tight">
                          {contas.total} conta(s) julgada(s) irregular(es) no {contas.fonte}
                        </div>
                        <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                          {contas.prefeitura > 0
                            ? <>{contas.prefeitura} da <b>prefeitura</b></>
                            : <>nenhuma da prefeitura</>}
                          {contas.autarquias > 0 && <> · {contas.autarquias} de autarquias e fundos</>}
                          {contas.de_prefeito > 0 && <> · <b>{contas.de_prefeito} de prefeito ou ex-prefeito</b></>}
                          .{" "}
                          É <b>indício</b>, não a situação do município para convênio: a lista
                          diz quem tem conta julgada irregular, e <b>não</b> atesta regularidade
                          de quem não aparece nela.
                        </p>
                        <ul className="space-y-1 pt-0.5">
                          {contas.itens.slice(0, 4).map((c, i) => (
                            <li key={i} className="text-[11px] leading-snug"
                                style={{ color: "var(--bi-muted)" }}>
                              <span style={{ color: "var(--bi-text)" }}>
                                {c.entidade || "Prefeitura"}
                              </span>
                              {c.responsavel ? ` · ${c.responsavel}` : ""}
                              {c.assunto ? ` · ${c.assunto}` : ""}
                              {c.processo ? ` · proc. ${c.processo}` : ""}
                              {c.url && (
                                <a href={c.url} target="_blank" rel="noopener noreferrer"
                                   className="ml-1 inline-flex items-center gap-0.5"
                                   style={{ color: "var(--bi-accent-ink)" }}>
                                  ver <ExternalLink className="size-3" />
                                </a>
                              )}
                            </li>
                          ))}
                          {contas.total > 4 && (
                            <li className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                              … e mais {contas.total - 4}.
                            </li>
                          )}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </Bloco>
            ) : !cagec?.tem_dados ? (
              /* Aguardando coleta — e dizendo POR QUÊ. Deixar em branco faria
                 parecer que não existe regularidade estadual a acompanhar;
                 pintar de verde seria pior, porque seria lido como "em dia". */
              <Bloco className="p-4">
                <div className="flex items-start gap-2.5">
                  <Clock className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
                  <div className="space-y-1.5">
                    <div className="bi-title text-[13px] leading-tight">Aguardando coleta</div>
                    <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      {cagec?.motivo
                        || `O ${siglaEst} deste município ainda não foi coletado.`}
                    </p>
                    {/* A coleta do cadastro estadual NÃO usa credencial — nos dois
                        portais (CAGEC e CHE) a consulta é pública e basta o CNPJ.
                        Mandar o gestor cadastrar senha aqui seria trabalho inútil.
                        O que falta, quando falta, é o CNPJ do município nas bases. */}
                    <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                      A consulta do {siglaEst} é pública e usa o CNPJ do município — não
                      depende de senha. Se o CNPJ ainda não foi identificado nas bases,
                      a coleta o encontra assim que ele aparecer em outra fonte já
                      coletada.
                    </p>
                  </div>
                </div>
              </Bloco>
            ) : (
              <>
                {/* ⚠️ UMA SUB-ABA POR ENTIDADE, decisão do dono: "as
                    regularidades dos fundos também, uma em cada aba, para
                    separar da do município". Cada entidade tem cadastro próprio
                    e trava apenas o SEU convênio — enquanto tudo ficava numa
                    lista só, a situação do fundo era uma linha discreta embaixo
                    de um banner verde da prefeitura. */}
                <SubAbasEntidade
                  opcoes={entidadesDaAba("estadual")}
                  ativa={entidadeDa("estadual")}
                  onChange={(id) => setEntidadeAtiva((s) => ({ ...s, estadual: id }))}
                />
                {(() => {
                  const ents = cagec.entidades || [];
                  const sel = ents.find((e) => (e.cnpj || e.nome || "") === entidadeDa("estadual"))
                    || ents.find((e) => e.principal) || ents[0];
                  if (!sel) return null;
                  const pendSel = (sel.itens || []).filter((i) => i.tipo === "pendente").length;
                  return (
                    <>
                      <Situacao
                        regular={sel.regular === true}
                        titulo={sel.regular
                          ? `${sel.situacao || "Regular"} no ${siglaEst}`
                          : (sel.situacao || `${pendSel} pendência(s)`)}
                        detalhe={`${sel.nome || cagec.nome}` + (sel.tipo ? ` · ${sel.tipo}` : "")
                          + (sel.validade
                            ? ` — próxima obrigação a vencer: ${fmtDate(sel.validade)}.`
                            : ` — ${nomeCadastroEst} (${NOME_UF[ufDoMunicipio] || ufDoMunicipio}).`)
                          + (sel.numero_cadastro ? ` Cadastro nº ${sel.numero_cadastro}.` : "")}
                      />
                      <AvisoCrc crcErro={sel.crc_erro} crcEm={sel.crc_em}
                        doCrc={sel.detalhe_do_crc} />
                      <Exigencias itens={sel.itens || []} esfera="cagec" />
                      {sel.crc_em && (
                        <p className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                          {certificadoEst
                            ? `Documentos conferidos no ${certificadoEst} de ${fmtDate(sel.crc_em)}.`
                            : `Validades consultadas no portal do ${siglaEst} em ${fmtDate(sel.crc_em)}.`}
                        </p>
                      )}
                    </>
                  );
                })()}
              </>
            )}
          </section>

          {/* ---------------- CADIN e CFIL (cadastros negativos) ---------------- */}
          {["cadin", "cfil"].map((qual) => {
            const fontes = qual === "cadin" ? fontesCadin : fontesCfil;
            if (!fontes.length) return null;
            const opcoes = entidadesDaAba(qual);
            const ent = entidadeDa(qual);
            const doEnte = fontes
              .map((f) => (negPorFonte[f] || []).find((i) => i.cnpj === ent))
              .filter(Boolean) as NegativoItem[];
            return (
              <section key={qual} className={aba === qual ? "space-y-2.5" : "hidden"}>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <h2 className="bi-title flex items-center gap-1.5 text-[14px]">
                    <FileSearch className="size-3.5" style={{ color: "var(--bi-muted)" }} />
                    {fontes.map((f) => negativos?.catalogo?.[f]?.sigla || f).join(" · ")}
                  </h2>
                  <SeloColeta em={negativos?.consultado_em} />
                  <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {negativos?.catalogo?.[fontes[0]]?.nome}
                  </span>
                  {/* Só o RS: em Minas o CADIN vem do CRC, e emitir CRC é a
                      rodada do CAGEC — não cabe num clique síncrono. */}
                  {ufDoMunicipio === "RS" && (
                    <button
                      type="button"
                      onClick={consultarAgora}
                      disabled={consultando}
                      className="ml-auto inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold bi-hover"
                      style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)",
                               color: "var(--bi-text)", opacity: consultando ? 0.6 : 1 }}
                      title="Emite a certidão agora — ela vale para a data em que é emitida"
                    >
                      {consultando
                        ? <Loader2 className="size-3.5 animate-spin" />
                        : <RefreshCw className="size-3.5" />}
                      {consultando ? "Consultando…" : "Consultar agora"}
                    </button>
                  )}
                </div>

                {!negativos?.tem_dados ? (
                  <Bloco className="p-4">
                    <div className="flex items-start gap-2.5">
                      <Clock className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
                      <div className="space-y-1.5">
                        <div className="bi-title text-[13px] leading-tight">Aguardando consulta</div>
                        <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                          {negativos?.motivo || "Ainda não consultado."}
                        </p>
                      </div>
                    </div>
                  </Bloco>
                ) : (
                  <>
                    <SubAbasEntidade
                      opcoes={opcoes}
                      ativa={ent}
                      onChange={(id) => setEntidadeAtiva((s) => ({ ...s, [qual]: id }))}
                    />
                    {doEnte.length ? doEnte.map((i) => (
                      <CadastroNegativo key={`${i.fonte}-${i.cnpj}`} item={i}
                        cat={negativos?.catalogo?.[i.fonte]} />
                    )) : (
                      <Vazio>Sem consulta registrada para esta entidade.</Vazio>
                    )}
                    <p className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                      A certidão não tem prazo de validade: ela afirma a situação
                      <b> na data em que foi emitida</b>. Por isso a consulta é diária
                      {ufDoMunicipio === "RS" && " e existe o botão de consultar agora"}.
                    </p>
                  </>
                )}
              </section>
            );
          })}

          {/* ---------------- Contas irregulares (tribunal de contas) ---------------- */}
          <section className={aba === "contas" ? "space-y-2.5" : "hidden"}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <h2 className="bi-title flex items-center gap-1.5 text-[14px]">
                <Gavel className="size-3.5" style={{ color: "var(--bi-muted)" }} />
                Contas julgadas irregulares
              </h2>
              <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                {contas?.fonte || "tribunal de contas do estado"} · indício, não documento
              </span>
            </div>
            {contas ? <ContasIrregulares contas={contas} /> : <Vazio>Sem dados.</Vazio>}
          </section>
        </div>
      )}


      {/* ---------------- Tesouro Nacional (SICONFI) ----------------
          Largura inteira, e abaixo das duas colunas, porque responde a uma
          pergunta DIFERENTE das de cima. CAUC e cadastro estadual dizem se a
          documentação está em dia; a CAPAG diz se o município aguenta tomar
          crédito, e o extrato de entregas diz O QUE foi entregue e quando —
          que é o detalhe que falta ao "irregular na obrigação 3.2.2" do CAUC. */}
      {municipioId && !loading && aba === "tesouro" && (
        <section className="space-y-2.5">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <h2 className="bi-title flex items-center gap-1.5 text-[14px]">
              <Landmark className="size-3.5" style={{ color: "var(--bi-muted)" }} />
              Tesouro Nacional
            </h2>
            <SeloColeta em={tesouro?.capag?.atualizado_em} />
            <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              capacidade de pagamento e contas entregues (SICONFI)
            </span>
          </div>

          {!tesouro?.tem_dados ? (
            /* ⚠️ Ausência de coleta NÃO é ausência de pendência. Pintar de
               verde, ou simplesmente não mostrar a seção, faria a tela calar
               sobre a própria ignorância — mesmo cuidado do bloco estadual. */
            <Bloco className="p-4">
              <div className="flex items-start gap-2.5">
                <Clock className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
                <div className="space-y-1.5">
                  <div className="bi-title text-[13px] leading-tight">Aguardando coleta</div>
                  <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                    {tesouro?.motivo
                      || "As contas deste município no Tesouro Nacional ainda não foram consultadas."}
                  </p>
                  <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                    A consulta é pública e usa o código IBGE do município — não depende de
                    senha nem de credencial.
                  </p>
                </div>
              </div>
            </Bloco>
          ) : (
            <div className="space-y-2.5">
              {tesouro.capag && <Capag capag={tesouro.capag} />}
              {/* ⚠️ TODOS OS EXERCÍCIOS COLETADOS, e não só o mais recente. O
                  ano corrente sempre parece incompleto (o 6º bimestre ainda não
                  venceu), e sem o ano fechado ao lado não há como saber se
                  falta entrega ou falta calendário. */}
              {(tesouro.exercicios || []).map((ano) => (
                <ContasNoTesouro key={ano.exercicio} ano={ano} />
              ))}
              <p className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                Fonte: SICONFI / Secretaria do Tesouro Nacional. A CAPAG é publicada algumas
                vezes por ano; as entregas são atualizadas a cada envio do município.
                Clique num demonstrativo para ver período a período.
              </p>
            </div>
          )}
        </section>
      )}

      {/* A legenda explica os SÍMBOLOS da lista de exigências — só faz sentido
          nas duas abas que desenham essa lista. Nas de CADIN/CFIL (que têm uma
          frase, não uma lista) e na do Tesouro ela seria ruído. */}
      {municipioId && !loading && (aba === "cauc" || aba === "estadual") && (
        <div
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]"
          style={{ color: "var(--bi-faint)" }}
        >
          {/* A legenda espelha as PALAVRAS dos dois documentos, porque cada
              esfera usa o seu vocabulario e a tela existe para ser conferida
              contra o extrato. NUNCA escrever "nao exigido" para o Desativado:
              o texto oficial diz que a desativacao e da FERRAMENTA, "para todos
              os entes federativos". O caso que prova e o FGTS — item 1.3,
              desativado no CAUC, e ao mesmo tempo VENCIDO no CAGEC na coluna ao
              lado, travando convenio estadual. */}
          <span className="font-semibold" style={{ color: "var(--bi-muted)" }}>CAUC:</span>
          <span className="inline-flex items-center gap-1">
            <Check className="size-3" style={{ color: "var(--bi-ok-ink)" }} /> Comprovado
          </span>
          <span className="inline-flex items-center gap-1" style={{ color: "var(--bi-crit-ink)" }}>
            <AlertCircle className="size-3" /> A Comprovar (impeditivo)
          </span>
          <span className="inline-flex items-center gap-1">
            <Ban className="size-3" /> Desativado (indisponível na fonte — não é dispensa)
          </span>
          <span className="font-semibold" style={{ color: "var(--bi-muted)" }}>Estadual:</span>
          <span className="inline-flex items-center gap-1">
            <Check className="size-3" style={{ color: "var(--bi-ok-ink)" }} /> Vigente
          </span>
          <span className="inline-flex items-center gap-1" style={{ color: "var(--bi-crit-ink)" }}>
            <AlertTriangle className="size-3" /> Vencido (impeditivo)
          </span>
          {/* Entrada nova, e não decoração: a linha em amarelo aparece na tela
              desde o `venceu()` e não tinha legenda nenhuma. */}
          <span className="inline-flex items-center gap-1" style={{ color: "var(--bi-warn-ink)" }}>
            <Clock className="size-3" /> Prazo vencido (validade passou depois da leitura)
          </span>
        </div>
      )}
    </div>
  );
}
