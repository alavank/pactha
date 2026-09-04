"use client";
// OBRAS DA SAÚDE — SISMOB (Ministério da Saúde, financiamento fundo a fundo).
//
// O público é o gestor de convênios, e o objetivo é ele sair da tela sabendo o
// que fazer hoje. Por isso a hierarquia é: faixa de situação → números →
// "Precisa de ação" ocupando o maior espaço → o resto colapsado.
//
// A classificação (o que é ação, o que está em dia) vem PRONTA do servidor, de
// services/sismob_regras.py — a mesma que o push usa. Se a tela reclassificasse
// por conta, um dia a notificação e a tela discordariam sobre a mesma obra.
//
// SEM FOTOS e SEM MAPA, de propósito: a rota de foto em tamanho cheio da fonte
// devolve 500, e a fonte tem coordenada errada (uma obra de Monte Sião vem com
// lat/long em Mato Grosso). Mostramos a CONTAGEM e a DATA da última foto — que
// é justamente a prova da estagnação.
//
// SOBRE O DESENHO: a tela já era feita de cartões, mas de cartões PRÓPRIOS —
// moldura vermelha/âmbar em volta da obra inteira, selo colorido, barra na cor
// da marca. Agora usa as peças de `ui/superficies`, as mesmas do resto do
// sistema. Duas consequências que valem registrar:
//
//  1. As três seções passaram a usar O MESMO cartão. Antes "Precisa de ação"
//     mostrava dez campos e "Em dia"/"Encerradas" mostravam quatro, o que
//     obrigava o gestor a abrir o SISMOB para conferir uma obra saudável.
//     Com `<Campos>` em posição fixa, as mesmas colunas aparecem em todos os
//     cartões e o olho desce a coluna como descia na planilha.
//  2. A moldura colorida saiu. O alerta continua — nos selos, no ícone da
//     regra e nos KPIs — mas deixou de pintar o cartão inteiro: com metade das
//     obras emolduradas de vermelho, o vermelho para de significar urgência.
import React, { useEffect, useMemo, useState } from "react";
import {
  HardHat, AlertTriangle, CheckCircle2, Clock, Loader2, Wallet,
  Building2, ExternalLink, ChevronDown, ChevronRight, Camera, Layers, ListChecks,
} from "lucide-react";
import api from "@/lib/api";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
// Uma funcao de dinheiro no sistema inteiro. Havia CINCO copias, e a
// desta tela ja tinha derivado: arredondava, e o mesmo valor aparecia
// com e sem centavos no mesmo print.
import { formatCurrency as moeda } from "@/lib/utils";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import {
  Abas, Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";

interface Regra {
  regra: string; titulo: string; detalhe: string; norma: string;
  acao: string; dias: number | null; severidade: string;
}
interface Empresa {
  cnpj: string; numero_contrato: string | null;
  razao_social: string | null; valor_final_licitado: number | null;
}
interface Obra {
  proposta_id: number; numero_proposta: string | null;
  estabelecimento: string | null; bairro: string | null;
  programa: string | null; tipo_obra: string | null; tipo_recurso: string | null;
  ano_referencia: number | null; situacao: string | null; etapa: string | null;
  percentual: number | null; severidade: string; regras: Regra[];
  dinheiro: { proposta: number; repassado: number; parcelas_pagas: number | null;
              regime: string | null; contrato: number | null; saldo: number | null };
  empresas: Empresa[];
  fotos: { grupos: number | null; total: number | null; ultima_em: string | null };
  ultima_atividade_em: string | null;
  url_portal: string;
}
interface Resp {
  tem_dados: boolean; motivo?: string;
  municipio?: string; uf?: string;
  entidade?: { nome: string | null; cnpj: string | null } | null;
  totais?: {
    obras: number; vivas: number; concluidas: number; canceladas: number;
    valor_proposta: number; repasse_total: number; repasse_parado: number;
    contratado: number; saldo_licitacao: number; contrapartida_municipal: number;
  };
  acao?: Obra[]; em_dia?: Obra[]; encerradas?: Obra[];
  por_situacao?: Array<{ label: string; qtd: number; valor: number }>;
  por_programa?: Array<{ label: string; qtd: number; valor: number }>;
  empresas_concentracao?: Array<{ cnpj: string; razao_social: string | null; obras: number; valor: number }>;
  coletado_em?: string | null;
}

type Tom = "neutro" | "ok" | "atencao" | "critico";

function data(iso?: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("pt-BR", { timeZone: "UTC" }); }
  catch { return iso.slice(0, 10); }
}
function cnpjFmt(c?: string | null): string {
  if (!c || c.length !== 14) return c || "—";
  return `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}`;
}

/** Grupo das obras cuja fonte não informou ano. Fica no FIM da lista: obra sem
 *  `ano_referencia` continua na tela — esconder registro porque um campo veio
 *  vazio na origem é pior que mostrá-lo separado. */
const SEM_ANO = "Sem ano";

/** O ANO de uma obra — `ano_referencia`, e só ele.
 *
 *  É o `nuAnoReferencia` do SISMOB: o exercício em que a proposta foi
 *  habilitada, que é o que o gestor chama de "o ano dessa obra". O candidato
 *  óbvio seria extrair do `numero_proposta`, como se faz nas propostas do
 *  TransfereGov — mas aqui NÃO dá: nesta base o número aparece em três
 *  formatos incompatíveis entre si, e a regexp acertaria uns e erraria outros.
 *
 *  O mesmo campo serve ao FILTRO e ao AGRUPAMENTO de propósito. Se o filtro
 *  olhasse uma data e o agrupamento outra, o gestor filtraria 2025 e veria um
 *  grupo 2024 na tela. */
function anoDa(o: Obra): string {
  return o.ano_referencia != null ? String(o.ano_referencia) : SEM_ANO;
}

/** Tom da SEVERIDADE que o servidor já calculou em `sismob_regras.py`.
 *
 *  Não é uma segunda `situacaoTom` — aquela existe para classificar o TEXTO
 *  LIVRE de situação das fontes ("CANCELADA", "Em análise") e continua sendo
 *  importada, logo abaixo, para o selo de situação da obra. Aqui não há nada a
 *  classificar: `severidade` é um enum fechado do nosso backend
 *  ("critico" | "atencao" | "ok" | "encerrada") e o nome do tom já vem pronto.
 *
 *  "ok" e "encerrada" viram CINZA de propósito: obra saudável é o estado normal
 *  e estado normal não ganha cor — se ganhasse, o vermelho da obra parada teria
 *  que competir com o verde de outras trinta. */
function tomDaSeveridade(sev: string): Tom {
  return sev === "critico" ? "critico" : sev === "atencao" ? "atencao" : "neutro";
}

/** Barra de execução física.
 *
 *  Mantida porque é a leitura mais rápida de "quanto essa obra andou", mas sem
 *  cor de marca: trilho no cinza das divisórias e preenchimento no cinza do
 *  texto secundário. Só ganha cor quando a obra está de fato em alerta. */
function Barra({ pct, tom }: { pct: number; tom: Tom }) {
  const cor = tom === "critico" ? "var(--bi-crit-ink)"
    : tom === "atencao" ? "var(--bi-warn-ink)"
    : "var(--bi-muted)";
  return (
    <div className="mt-2 h-1 w-full overflow-hidden rounded-full"
         style={{ background: "var(--bi-line)" }}>
      <div className="h-full rounded-full"
           style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: cor }} />
    </div>
  );
}

/** O cartão da obra — UM só, usado nas três seções.
 *
 *  Todo campo que a fonte devolve aparece aqui: o que não cabe no título vai
 *  para a meta (programa, tipo, bairro, ano, tipo de recurso, nº da proposta) e
 *  o que é número vai para `<Campos>`, em posições fixas. */
function CartaoObra({ o }: { o: Obra }) {
  const tom = tomDaSeveridade(o.severidade);
  // `Campos` chama de "normal" o que o `Selo` chama de "neutro", e trata
  // ausência como normal — então o cinza aqui é `undefined`, não uma string.
  const tomCampo = tom === "neutro" ? undefined : tom;
  const temFoto = (o.fotos.grupos || 0) > 0;
  return (
    <ItemLinha
      titulo={o.estabelecimento || `Proposta ${o.numero_proposta || o.proposta_id}`}
      valor={moeda(o.dinheiro.proposta)}
      meta={
        <>
          {o.situacao && (
            <Selo tom={situacaoTom(o.situacao)} title={o.situacao}>{o.situacao}</Selo>
          )}
          {/* O selo de severidade é informação DIFERENTE da situação: a fonte
              pode dizer "Em execução" numa obra parada há oito meses, e é essa
              contradição que o gestor precisa enxergar sem abrir o cartão. */}
          {tom !== "neutro" && (
            <Selo tom={tom} title="Classificação de risco calculada pelo PACTHA a partir dos prazos do SISMOB">
              {tom === "critico" ? "crítico" : "atenção"}
            </Selo>
          )}
          {o.programa && <span className="truncate" title={o.programa}>{o.programa}</span>}
          {o.tipo_obra && <span>· {o.tipo_obra}</span>}
          {o.bairro && <span>· {o.bairro}</span>}
          {o.ano_referencia != null && <span>· {o.ano_referencia}</span>}
          {o.tipo_recurso && <span>· {o.tipo_recurso}</span>}
          <span className="font-mono">· prop {o.numero_proposta || o.proposta_id}</span>
        </>
      }
      acao={
        <a
          href={o.url_portal}
          target="_blank"
          rel="noreferrer"
          title="Abre esta obra no portal SISMOB Cidadão"
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-opacity hover:opacity-80"
          style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
        >
          SISMOB <ExternalLink className="size-3" />
        </a>
      }
    >
      {o.percentual != null && <Barra pct={o.percentual} tom={tom} />}

      {/* AS COLUNAS DA OBRA, iguais em todos os cartões e nas três seções.
          É o que permite descer o olho por "Repassado" ou por "Últ. atividade"
          sem existir tabela — e o que fez a obra "em dia" parar de ser um
          resumo de quatro campos. */}
      <Campos
        cols={5}
        campos={[
          { rotulo: "Execução", tom: tomCampo,
            valor: o.percentual != null ? `${o.percentual}%` : "—" },
          { rotulo: "Etapa", valor: o.etapa || "—", title: o.etapa || undefined },
          { rotulo: "Aprovado", valor: moeda(o.dinheiro.proposta) },
          { rotulo: "Repassado", valor: moeda(o.dinheiro.repassado) },
          { rotulo: "Parcelas pagas", valor: o.dinheiro.parcelas_pagas ?? "—" },
          { rotulo: "Contratado", valor: moeda(o.dinheiro.contrato) },
          // Glosa da coluna, não afirmação sobre esta obra: o título tem que
          // continuar verdadeiro quando o valor é "—".
          { rotulo: "Saldo licitação", valor: moeda(o.dinheiro.saldo),
            title: "Sobra da licitação: repasse recebido acima do valor contratado" },
          { rotulo: "Regime", valor: o.dinheiro.regime || "—",
            title: o.dinheiro.regime || undefined },
          // A data da última atividade É o argumento da estagnação, e por isso
          // acompanha o tom: é a célula que prova o que o selo afirma.
          { rotulo: "Últ. atividade", tom: tomCampo, valor: data(o.ultima_atividade_em) },
          { rotulo: "Fotos",
            title: temFoto ? `${o.fotos.grupos} grupo(s) de foto no SISMOB` : undefined,
            valor: temFoto ? (
              <span className="inline-flex items-center gap-1">
                <Camera className="size-3 shrink-0" />
                {o.fotos.total} · {data(o.fotos.ultima_em)}
              </span>
            ) : "—" },
        ]}
      />

      {/* Uma linha por regra violada. `norma` e `acao` vêm do servidor: um
          alerta que diz "vencido" sem dizer o dispositivo nem o que fazer não
          sobrevive à primeira conversa com a Secretaria de Saúde. */}
      {o.regras.length > 0 && (
        <div className="mt-2 flex flex-col gap-1.5">
          {o.regras.map((r, i) => (
            <div key={`${r.regra}-${i}`} className="rounded-lg p-2"
                 style={{ background: "var(--bi-surface-2)" }}>
              <div className="flex items-start gap-2">
                <AlertTriangle
                  className="mt-0.5 size-3.5 shrink-0"
                  style={{ color: r.severidade === "critico"
                    ? "var(--bi-crit-ink)" : "var(--bi-warn-ink)" }}
                />
                <div className="min-w-0">
                  <div className="text-[12px] font-medium leading-snug"
                       style={{ color: "var(--bi-text)" }}>
                    {r.titulo}
                  </div>
                  <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                    {r.detalhe}
                  </p>
                  <p className="mt-0.5 text-[11px] font-medium leading-snug"
                     style={{ color: "var(--bi-text)" }}>
                    {r.acao}
                  </p>
                  <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                    {r.norma}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* TODAS as contratadas, não só a primeira: obra com duas empresas era
          exatamente o caso em que o cartão antigo escondia a segunda. */}
      {o.empresas.length > 0 && (
        <div className="mt-2 flex flex-col gap-0.5">
          {o.empresas.map((e, i) => (
            <div key={`${e.cnpj}-${i}`}
                 className="flex flex-wrap items-baseline gap-x-2 text-[10px] leading-snug"
                 style={{ color: "var(--bi-faint)" }}>
              <Building2 className="size-3 shrink-0 self-center" />
              <span style={{ color: "var(--bi-muted)" }}>
                {e.razao_social || "Contratada sem razão social informada"}
              </span>
              <span className="font-mono">{cnpjFmt(e.cnpj)}</span>
              {e.numero_contrato && <span>· contrato {e.numero_contrato}</span>}
              {e.valor_final_licitado != null && (
                <span className="bi-num">· {moeda(e.valor_final_licitado)}</span>
              )}
            </div>
          ))}
        </div>
      )}
    </ItemLinha>
  );
}

/** Seção colapsável de obras, agrupadas por ANO dentro dela.
 *
 *  O agrupamento por ano é o mesmo das Emendas Estaduais e das Propostas do
 *  TransfereGov — cabeçalho com chevron, ano, contagem e total à direita, e os
 *  cartões cinza embaixo. O que muda aqui é ONDE fica o cartão branco: naquelas
 *  telas a lista é plana e o branco é o ano; nesta o branco já é a SEÇÃO, e é
 *  ela que o gestor lê primeiro ("precisa de ação"), não o ano — o ano é a
 *  organização secundária. Cartão branco dentro de cartão branco quebraria a
 *  hierarquia fundo → bloco → item, então o ano entra como faixa separada por
 *  linha, com o mesmo cabeçalho e o mesmo gesto de abrir e fechar. */
function Secao({ obras, vazio }: {
  obras: Obra[];
  /** Mensagem quando não há obras. Sem ela a aba fica em branco — que é o certo
   *  para "Em dia" e "Encerradas", mas não para "Precisa de ação": ali o vazio
   *  é a boa notícia e precisa ser dito. */
  vazio?: string;
}) {
  /* Guarda o que está FECHADO, e não o que está aberto: assim um ano novo que
     chegue na próxima coleta nasce ABERTO em vez de invisível. */
  const [anosFechados, setAnosFechados] = useState<Set<string>>(new Set());

  /** Do ano mais recente para o mais antigo, com "Sem ano" sempre por último. */
  const porAno = useMemo(() => {
    const m = new Map<string, Obra[]>();
    for (const o of obras) {
      const a = anoDa(o);
      (m.get(a) ?? m.set(a, []).get(a)!).push(o);
    }
    return Array.from(m.entries()).sort((x, y) =>
      x[0] === SEM_ANO ? 1 : y[0] === SEM_ANO ? -1 : y[0].localeCompare(x[0]));
  }, [obras]);

  const alternarAno = (a: string) =>
    setAnosFechados((prev) => {
      const n = new Set(prev);
      if (n.has(a)) n.delete(a); else n.add(a);
      return n;
    });

  if (!obras.length) return <Vazio>{vazio || "Nenhuma obra."}</Vazio>;
  return (
    <>
      {(
        <div className="flex flex-col gap-2">
          {porAno.map(([ano, doAno]) => {
            const fechado = anosFechados.has(ano);
            const totalAno = doAno.reduce((s, o) => s + (o.dinheiro.proposta || 0), 0);
            return (
              <div key={ano} className="border-t pt-2.5 first:border-t-0 first:pt-0"
                   style={{ borderColor: "var(--bi-line)" }}>
                <button type="button" onClick={() => alternarAno(ano)}
                        aria-expanded={!fechado} className="w-full text-left">
                  <BlocoHead
                    icon={fechado ? ChevronRight : ChevronDown}
                    titulo={ano}
                    sub={`${doAno.length} obra(s)`}
                    right={<span className="bi-num text-[13px]">{moeda(totalAno)}</span>}
                    className={fechado ? "mb-0" : undefined}
                  />
                </button>
                {!fechado && (
                  <Lista>{doAno.map((o) => <CartaoObra key={o.proposta_id} o={o} />)}</Lista>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export default function SismobPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(true);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [triagem, setTriagem] = useState<"acao" | "em_dia" | "encerradas">("acao");
  /* Âncora da faixa "precisam de ação": ela virou botão e precisa levar o olho
     até a lista, que no desktop está abaixo da dobra. */
  const refTriagens = React.useRef<HTMLDivElement>(null);

  /** Levar o gestor até as obras que pedem providência.
   *
   *  Limpa o filtro de anos de propósito: a faixa conta as obras de TODOS os
   *  anos (o número vem do servidor), então mandar para a lista com um recorte
   *  de ano ligado entregaria "nenhuma obra" logo depois de anunciar que há
   *  cinco. Prometer cinco e mostrar zero é pior que não ser clicável. */
  const irParaAcoes = () => {
    setTriagem("acao");
    setAnosSel([]);
    requestAnimationFrame(() =>
      refTriagens.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!municipioId) { setD(null); setLoading(false); return; }
    setLoading(true);
    api.get<Resp>("/sismob", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data))
      .catch(() => setD(null))
      .finally(() => setLoading(false));
  }, [municipioId]);

  const t = d?.totais;
  const acao = d?.acao ?? [];

  /** Os anos que EXISTEM nas obras, para o dropdown não oferecer ano vazio.
   *  Sai das três listas juntas porque o filtro vale para as três. */
  const anosDisponiveis = useMemo(() => {
    const todas = [...(d?.acao ?? []), ...(d?.em_dia ?? []), ...(d?.encerradas ?? [])];
    return Array.from(new Set(
      todas.map((o) => o.ano_referencia).filter((a): a is number => a != null),
    )).sort((a, b) => b - a).map(String);
  }, [d]);
  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anosDisponiveis, setAnosSel);

  /* Nada selecionado = todos, que é a convenção do MultiSelect e do backend. */
  const filtrarAnos = (l: Obra[]) =>
    anosSel.length ? l.filter((o) => anosSel.includes(anoDa(o))) : l;

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
          <HardHat className="size-6" style={{ color: "var(--bi-muted)" }} />
          Obras da Saúde (SISMOB)
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Obras financiadas fundo a fundo pelo Ministério da Saúde
          {d?.entidade?.nome ? <> — convenente <strong>{d.entidade.nome}</strong>
            <span className="font-mono text-xs"> ({cnpjFmt(d.entidade.cnpj)})</span></> : null}
        </p>
        {/* COMO SE LÊ A TELA. Escrito porque o dono, que conhece o produto,
            abriu o módulo e não soube onde clicar nem o que cada quadro dizia —
            se ele não soube, o secretário de saúde do município não vai saber.
            Uma linha por gesto, na ordem em que a tela é usada: o alerta em
            cima, os números no meio, as três abas embaixo. */}
        <p className="mt-1.5 text-[11px] leading-relaxed" style={{ color: "var(--bi-faint)" }}>
          A faixa e o cartão vermelhos apontam as obras com prazo vencido ou paradas — clique
          neles para ir à lista, onde cada obra traz o motivo, a providência exigida e a norma.
          Os cinco números resumem o município inteiro e não seguem o filtro de anos. Embaixo,
          as três abas separam as obras em <strong>precisa de ação</strong>, <strong>em dia</strong> e{" "}
          <strong>concluídas/encerradas</strong> — uma obra está em uma e só uma. O botão SISMOB de
          cada obra abre a mesma obra no portal do Ministério.
        </p>
      </div>

      {!municipioId && <Vazio>Selecione um município para ver as obras.</Vazio>}

      {municipioId && loading && (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      )}

      {municipioId && !loading && !d?.tem_dados && (
        /* Aguardando coleta — e dizendo POR QUÊ. Nunca "ok": um selo verde aqui
           seria lido como "não há obra com problema", que é diferente de "não
           sei". Âmbar porque falta de dado é, ela mesma, uma pendência.

           O `pb` menor (aqui e na faixa de situação) é porque o BlocoHead já
           traz margem inferior própria: num bloco que só tem cabeçalho, `p-3`
           dos dois lados deixa o dobro de folga embaixo. */
        <Bloco className="px-3 pt-3 pb-0.5">
          <BlocoHead
            icon={Clock}
            titulo="Aguardando coleta"
            sub={d?.motivo}
            right={<Selo tom="atencao">sem dados</Selo>}
          />
        </Bloco>
      )}

      {municipioId && !loading && d?.tem_dados && t && (
        <>
          {/* Faixa de situação: uma frase, no lugar do retângulo vermelho que
              ocupava a largura da tela. Quem carrega o alerta é o selo — a
              moldura colorida gritava igual quando havia uma obra e quando
              havia vinte. */}
          {/* A faixa VIROU BOTÃO. Ela anunciava "5 obras precisam de ação" e
              parava aí: quem lia isso não tinha onde clicar, e a lista com o
              motivo e a providência de cada obra ficava numa aba abaixo, sem
              nada ligando as duas. O anúncio de pendência tem que levar à
              pendência — senão vira um número que assusta e não resolve. */}
          <Bloco className="px-3 pt-3 pb-0.5">
            {acao.length ? (
              <button type="button" onClick={irParaAcoes} className="w-full text-left"
                      title="Ver as obras, o motivo de cada pendência e a providência exigida">
                <BlocoHead
                  icon={AlertTriangle}
                  titulo={`${acao.length} obra(s) precisam de ação`}
                  sub={
                    <>
                      {t.repasse_parado > 0
                        ? `${moeda(t.repasse_parado)} repassados em obras que não se movem há mais de 60 dias. `
                        : ""}
                      Clique para ver cada obra com o motivo, a providência exigida e a norma que a obriga.
                    </>
                  }
                  right={<Selo tom="critico">exige ação</Selo>}
                />
              </button>
            ) : (
              <BlocoHead
                icon={CheckCircle2}
                titulo="Nenhuma obra com pendência de prazo"
                sub={`${t.vivas} obra(s) em andamento, todas dentro do prazo de atualização.`}
                right={<Selo>em dia</Selo>}
              />
            )}
          </Bloco>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Numero icon={HardHat} rotulo="Obras em andamento" valor={String(t.vivas)}
              sub={`${t.obras} no total`} />
            <Numero icon={Wallet} rotulo="Já repassado" valor={moeda(t.repasse_total)}
              sub={`de ${moeda(t.valor_proposta)} aprovados`} />
            {/* Zero parado não vira verde: "nada parado" é o estado normal, e o
                vermelho ao lado só funciona porque o resto da linha é cinza. */}
            <Numero icon={AlertTriangle} rotulo="Parado sem atualização"
              valor={moeda(t.repasse_parado)}
              tom={t.repasse_parado > 0 ? "critico" : "neutro"}
              sub={t.repasse_parado > 0 ? "dinheiro em obra que não anda" : "nada parado"} />
            {/* O único KPI que leva a algum lugar — porque é o único que pede
                providência. Os outros quatro são leitura. */}
            {acao.length ? (
              <button type="button" onClick={irParaAcoes} className="text-left"
                      title="Ver as obras e o que cada uma exige">
                <Numero icon={AlertTriangle} rotulo="Precisam de ação" valor={String(acao.length)}
                  tom="critico" sub="prazo ou pendência · clique para ver" />
              </button>
            ) : (
              <Numero icon={AlertTriangle} rotulo="Precisam de ação" valor="0"
                tom="neutro" sub="prazo ou pendência" />
            )}
            <Numero icon={CheckCircle2} rotulo="Concluídas" valor={String(t.concluidas)}
              sub={t.canceladas ? `${t.canceladas} cancelada(s)` : undefined} />
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <section className="flex flex-col gap-3 xl:col-span-2">
              {anosDisponiveis.length > 0 && (
                <div className="flex flex-wrap items-center gap-3">
                  <MultiSelect
                    opcoes={anosDisponiveis}
                    valor={anosSel}
                    onChange={setAnosSel}
                    atalhos={atalhosAnos()}
                    formatarResumo={resumoAnos}
                    placeholder="Todos os anos"
                    rotuloTodos="Todos os anos"
                    ariaLabel="Anos"
                    className="w-44"
                  />
                  {/* O recorte vale para as LISTAS, não para os números do topo
                      nem para os resumos da direita: aqueles são agregados pelo
                      servidor sobre todas as obras, e recalculá-los na tela
                      duplicaria a classificação que vive em `sismob_regras.py`
                      — o mesmo motivo pelo qual esta tela não reclassifica
                      obra. Dizer isso é melhor que deixar o gestor supor que o
                      KPI seguiu o filtro. */}
                  {anosSel.length > 0 && (
                    <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                      Filtrando as listas de obras. Os números do topo e os resumos ao
                      lado continuam somando todos os anos.
                    </span>
                  )}
                </div>
              )}
              {/* AS TRÊS TRIAGENS VIRARAM ABAS DE UM CARTÃO SÓ.
                  Eram três cartões brancos empilhados, cada um com o seu
                  chevron. Com os três recolhidos sobrava metade da tela vazia,
                  e com os três abertos a página ficava quilométrica — o gestor
                  rolava para achar a próxima triagem em vez de trocar de vista.
                  Aba é o gesto certo aqui porque as três são MUTUAMENTE
                  EXCLUSIVAS: uma obra está numa e só numa.

                  O que se PERDE: não dá mais para ver "Precisa de ação" e "Em
                  dia" abertas ao mesmo tempo. A contagem e o valor de cada
                  triagem continuam visíveis no rótulo da aba e no cabeçalho,
                  então a comparação não exige trocar de aba.

                  A aba com zero obras fica DESLIGADA em vez de sumir: "Em dia:
                  0" é informação, e uma aba que aparece e desaparece conforme o
                  filtro de anos move as outras de lugar. */}
              {(() => {
                const grupos = [
                  { valor: "acao" as const, rotulo: "Precisa de ação", obras: filtrarAnos(acao),
                    vazio: anosSel.length
                      ? "Nenhuma obra com prazo vencido ou parada nos anos selecionados."
                      : "Nenhuma obra com prazo vencido ou parada." },
                  { valor: "em_dia" as const, rotulo: "Em dia", obras: filtrarAnos(d.em_dia ?? []),
                    vazio: "Nenhuma obra em dia nos anos selecionados." },
                  { valor: "encerradas" as const, rotulo: "Concluídas e encerradas",
                    obras: filtrarAnos(d.encerradas ?? []),
                    vazio: "Nenhuma obra concluída ou encerrada nos anos selecionados." },
                ];
                /* Cai na primeira aba com obra quando a ativa esvazia por causa
                   do filtro de anos — sem isso o cartão ficaria vazio com abas
                   cheias ao lado. "Precisa de ação" tem prioridade: é a razão
                   da tela existir. */
                const atual = grupos.find((g) => g.valor === triagem && g.obras.length)
                  ? triagem
                  : (grupos.find((g) => g.obras.length)?.valor ?? "acao");
                const g = grupos.find((x) => x.valor === atual)!;
                const total = g.obras.reduce((s, o) => s + (o.dinheiro.proposta || 0), 0);
                return (
                  <div ref={refTriagens} className="scroll-mt-4">
                  <Bloco className="p-3">
                    <BlocoHead
                      titulo={g.rotulo}
                      sub={`${g.obras.length} obra(s)`}
                      right={g.obras.length
                        ? <span className="bi-num text-[13px]">{moeda(total)}</span>
                        : undefined}
                    />
                    <div className="mb-3">
                      <Abas
                        valor={atual}
                        onChange={setTriagem}
                        opcoes={grupos.map((x) => ({
                          valor: x.valor,
                          label: `${x.rotulo} (${x.obras.length})`,
                          on: x.obras.length > 0,
                        }))}
                      />
                    </div>
                    <div key={atual} className="bi-pane-enter">
                      <Secao obras={g.obras} vazio={g.vazio} />
                    </div>
                  </Bloco>
                  </div>
                );
              })()}
            </section>

            <aside className="flex flex-col gap-3">
              <Bloco className="p-3">
                <BlocoHead icon={Wallet} titulo="Dinheiro"
                  sub="totais do município nas obras do SISMOB" />
                <dl className="flex flex-col gap-1.5">
                  {([
                    ["Aprovado", t.valor_proposta, null],
                    ["Repassado pelo FNS", t.repasse_total, null],
                    ["Contratado (licitação)", t.contratado, null],
                    ["Saldo de licitação", t.saldo_licitacao,
                     "repasse acima do contrato — reprogramar ou devolver"],
                    ["Contrapartida do município", t.contrapartida_municipal,
                     "contrato acima do repasse federal"],
                  ] as Array<[string, number, string | null]>)
                    .filter(([, v]) => v > 0)
                    .map(([k, v, nota]) => (
                      <div key={k}>
                        <div className="flex items-baseline justify-between gap-2">
                          <dt className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{k}</dt>
                          <dd className="bi-num text-[12px]" style={{ color: "var(--bi-text)" }}>
                            {moeda(v)}
                          </dd>
                        </div>
                        {nota && (
                          <div className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                            {nota}
                          </div>
                        )}
                      </div>
                    ))}
                </dl>
              </Bloco>

              {!!d.empresas_concentracao?.length && (
                <Bloco className="p-3">
                  <BlocoHead
                    icon={Building2}
                    titulo="Empresas contratadas"
                    sub={`${d.empresas_concentracao.length} empresa(s)`}
                    right={<span className="bi-num text-[13px]">{moeda(t.contratado)}</span>}
                  />
                  <Lista>
                    {d.empresas_concentracao.map((e) => {
                      const pct = t.contratado ? (e.valor / t.contratado) * 100 : 0;
                      return (
                        <ItemLinha
                          key={e.cnpj}
                          titulo={e.razao_social || "Sem razão social informada"}
                          valor={moeda(e.valor)}
                          meta={
                            <>
                              <span className="font-mono">{cnpjFmt(e.cnpj)}</span>
                              <span>· {e.obras} obra(s)</span>
                              {/* Concentração é o único dado desta lista que
                                  pede ação (uma empresa com metade do
                                  contratado do município), então é o único que
                                  ganha cor. */}
                              {pct >= 50 && (
                                <Selo tom="atencao"
                                  title="Uma única empresa concentra metade ou mais do valor contratado">
                                  {Math.round(pct)}% do contratado
                                </Selo>
                              )}
                            </>
                          }
                        />
                      );
                    })}
                  </Lista>
                </Bloco>
              )}

              {!!d.por_situacao?.length && (
                <Bloco className="p-3">
                  <BlocoHead icon={ListChecks} titulo="Por situação"
                    sub={`${d.por_situacao.length} situação(ões)`} />
                  <Lista>
                    {d.por_situacao.map((s) => (
                      <ItemLinha
                        key={s.label}
                        titulo={
                          <Selo tom={situacaoTom(s.label)} title={s.label}>{s.label}</Selo>
                        }
                        valor={moeda(s.valor)}
                        meta={<span>{s.qtd} obra(s)</span>}
                      />
                    ))}
                  </Lista>
                </Bloco>
              )}

              {!!d.por_programa?.length && (
                <Bloco className="p-3">
                  <BlocoHead icon={Layers} titulo="Por programa"
                    sub={`${d.por_programa.length} programa(s)`} />
                  <Lista>
                    {d.por_programa.map((p) => (
                      <ItemLinha
                        key={p.label}
                        titulo={p.label}
                        valor={moeda(p.valor)}
                        meta={<span>{p.qtd} obra(s)</span>}
                      />
                    ))}
                  </Lista>
                </Bloco>
              )}

              <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Fonte: SISMOB Cidadão (Ministério da Saúde). Coleta de {data(d.coletado_em)}.
              </p>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
