"use client";

/* PARCERIAS — a emenda de saúde do município, com o parlamentar nomeado.
 *
 * ⭐ O QUE ESTA TELA MOSTRA QUE NENHUMA OUTRA MOSTRAVA. O módulo de Gestão de
 * Parcerias do Transferegov processa as transferências de 2024 em diante — 144
 * dos 176 programas publicados são Fundo a Fundo da Saúde —, e até 07/09/2026
 * era o único instrumento federal invisível à plataforma. Em Nova Palma são 11
 * propostas, R$ 2,18 mi, TODAS com emenda e parlamentar identificados.
 *
 * ⭐ E A PERGUNTA QUE ELA RESPONDE É "QUEM TROUXE". O ranking por parlamentar
 * abre a tela porque é a leitura que o gestor faz primeiro; a lista de
 * propostas vem depois, para quem quer o detalhe. No tenant trust isso são 84
 * propostas e R$ 67,7 mi só da Comissão da Saúde.
 *
 * ⚠️ NÃO CONFUNDIR COM «VOLUNTÁRIAS», a tela vizinha. Aquela mostra o convênio
 * discricionário do SICONV, que continua vindo dos dumps CSV. Esta é outro
 * módulo, com outro ciclo (proposta → parceria) e outro tipo de instrumento. As
 * duas coexistem de propósito, e por isso ficam lado a lado no menu.
 *
 * ⚠️ PROPOSTA SEM PARCERIA CELEBRADA NÃO É ERRO. O ciclo tem dois passos, e a
 * maioria das propostas de um ano corrente ainda não virou instrumento. A tela
 * diz «não celebrada» em vez de esconder a linha — quem lê precisa saber que a
 * proposta existe e em que pé está.
 *
 * ⚠️ E QUANDO NÃO HÁ DADO, A TELA NÃO CONCLUI "o município não tem emenda". A
 * coleta é nossa e diária: a ausência pode ser nossa.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  Banknote, Building2, CalendarRange, ExternalLink, Eye, FileText, HandCoins,
  Landmark, Loader2, MessageSquareText, Receipt, Target, Users, Wallet,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Abas, Bloco, BlocoHead, Campos, Grade, GradeCel, GradeLinha, ItemLinha, Lista,
  Modal, ModalCorpo, ModalHead, Numero, Secao, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";
import { textoDe } from "@/lib/texto";
import { TituloTela } from "@/components/TituloTela";

/* ⭐ A ÁRVORE DA PROPOSTA (15/09/2026) — o que a coleta passou a trazer da API
   oficial inteira: plano de trabalho, parecer, conta, extrato, pagamentos.
   `resumo` é o que o coletor calculou dela (`ingestion/parcerias.
   execucao_da_arvore`): PAGO pela ordem bancária — nunca pela situação da
   parceria, que diz "Aprovada" em parceria já paga. */
interface Resumo {
  empenhado?: number | null;
  pago?: number | null;
  n_ordens_bancarias?: number | null;
  data_ultima_ob?: string | null;
  saldo_corrente?: number | null;
  saldo_investimento?: number | null;
  saldo_total?: number | null;
  data_saldo?: string | null;
  nao_classificado?: number | null;
  pago_a_terceiros?: number | null;
  n_contas?: number | null;
}

interface EmendaIndicada {
  numero_emenda: string | null;
  ano: number | null;
  parlamentar: string | null;
  tipo: string | null;
  valor_gnd3: number | null;
  valor_gnd4: number | null;
  valor_total: number | null;
  beneficiario: string | null;
  cnpj_beneficiario: string | null;
  natureza_juridica: string | null;
  municipal: boolean;
  indicacoes: Array<Record<string, unknown>>;
  /** A emenda já tem proposta coletada (casada pelo número da emenda). */
  tem_proposta: boolean;
}

/* O detalhe vem com as CHAVES DA FONTE (snake_case), exatamente como a API as
   manda — tudo opcional, e texto passa por `textoDe`: é dado de portal federal,
   e campo que muda de tipo não pode derrubar o modal. */
type Reg = Record<string, unknown>;
interface DetalheResp {
  proposta: Reg | null;
  detalhe: {
    programa?: Reg | null;
    metas?: Array<Reg & { etapas_proposta?: Array<Reg & { itens?: Reg[] }> }>;
    cronograma?: Reg[];
    analises?: Reg[];
    indicadores?: Reg[];
    execucao?: {
      contas?: Array<Reg & { extrato?: Reg[]; opp?: Reg[]; classificacoes_ingresso?: Reg[] }>;
      empenhos?: Reg[];
      documentos_habeis?: Array<Reg & { ordens?: Reg[] }>;
    } | null;
    _resumo?: Resumo | null;
  } | null;
  detalhe_atualizado_em: string | null;
  fonte_atualizada_em: string | null;
  url_fonte: string;
}

const t = (v: unknown): string => textoDe(v) || "-";
const n = (v: unknown): number | null => (typeof v === "number" ? v : null);
/** '2026-05-26T00:00:00' -> '26/05/2026'. */
const dia = (v: unknown): string => {
  const s = textoDe(v);
  const m = s ? /^(\d{4})-(\d{2})-(\d{2})/.exec(s) : null;
  return m ? `${m[3]}/${m[2]}/${m[1]}` : s || "-";
};

// Grades do detalhe. ⚠️ Classe LITERAL: montada por template o Tailwind não vê.
const COLS_ITEM = "grid-cols-[minmax(10rem,1.4fr)_6rem_4rem_7rem_7.5rem_minmax(7rem,0.8fr)]";
const COLS_CRONO = "grid-cols-[6rem_minmax(8rem,1fr)_8rem]";
const COLS_EMP = "grid-cols-[7.5rem_6rem_minmax(7rem,1fr)_minmax(8rem,1fr)_7.5rem]";
const COLS_DH = "grid-cols-[7.5rem_6rem_7.5rem_6rem_7.5rem_7.5rem_6rem]";
const COLS_EXT = "grid-cols-[6rem_4.5rem_minmax(8rem,1fr)_minmax(9rem,1.2fr)_8rem_7.5rem]";
const COLS_ING = "grid-cols-[6rem_minmax(9rem,1.3fr)_8rem_minmax(8rem,1fr)_7.5rem_7.5rem]";
const COLS_OPP = "grid-cols-[6rem_minmax(9rem,1.3fr)_8rem_minmax(7rem,1fr)_7.5rem_7.5rem]";

type AbaDet = "proposta" | "plano" | "execucao" | "conta" | "analise" | "emenda";

interface Proposta {
  /* ⚠️ Falso quando o recebedor não é a administração municipal — Fundo
     ESTADUAL de Saúde, associação privada, cooperativa. A linha aparece, mas
     não entra nos cartões nem no ranking. Ver o cabeçalho do router. */
  municipal: boolean;
  id_proposta: number;
  objeto: string | null;
  situacao: string | null;
  valor: number | null;
  ano: number | null;
  data_proposta: string | null;
  ente_recebedor: string | null;
  cnpj_recebedor: string | null;
  natureza_juridica: string | null;
  id_parceria: number | null;
  codigo_parceria: string | null;
  situacao_parceria: string | null;
  data_assinatura: string | null;
  numero_emenda: string | null;
  parlamentar: string | null;
  tipo_emenda: string | null;
  valor_emenda: number | null;
  resultado_esperado: string | null;
  url_fonte: string;
  nu_externo?: string | null;
  /* `resumo` nulo + `detalhe_coletado` falso = o coletor ainda não passou;
     nulo + verdadeiro = proposta sem parceria celebrada. Nunca "zero". */
  detalhe_coletado?: boolean;
  resumo?: Resumo | null;
}

interface PorParlamentar {
  parlamentar: string;
  propostas: number;
  valor: number;
  tipo: string | null;
}

interface Resp {
  tem_dados: boolean;
  motivo?: string;
  itens?: Proposta[];
  total?: number;
  valor_total?: number;
  valor_emenda?: number;
  com_emenda?: number;
  por_parlamentar?: PorParlamentar[];
  por_situacao?: Array<{ situacao: string; qtd: number }>;
  total_listado?: number;
  fora_do_municipio?: { qtd: number; valor: number };
  municipio?: { id: number; nome: string; uf: string };
  execucao?: {
    medidas: number;
    pago: number;
    saldo: number;
    com_saldo: number;
    nao_classificado: number;
    com_nao_classificado: number;
  };
  emendas_indicadas?: EmendaIndicada[];
}

const brl = (v: number | null | undefined) =>
  v == null
    ? "—" /* ⚠️ Não "R$ 0,00": proposta sem valor declarado não é de graça. */
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const dataBR = (s: string | null) =>
  s ? s.split("-").reverse().join("/") : null;

export default function ParceriasPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ A RESPOSTA GUARDA DE QUAL MUNICÍPIO ELA É, e `carregando` é DERIVADO
     disso — mesmo desenho de `obrasgov/page.tsx` e pela mesma razão: ao trocar
     de município, um `d` que sobrou do anterior apareceria por um quadro sob o
     cabeçalho do novo, mostrando a emenda de uma cidade no nome de outra. */
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null }>(
    { mun: "", d: null, erro: null });
  const [parlamentar, setParlamentar] = useState<string>("");
  // A proposta com o detalhe completo aberto (modal). Guarda o id, não o índice.
  const [detId, setDetId] = useState<number | null>(null);

  const daVez = res.mun === municipioId;
  const carregando = !!municipioId && !daVez;
  const d = daVez ? res.d : null;
  const erro = daVez ? res.erro : null;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<Resp>("/parcerias", { params: { municipio_id: municipioId } })
      .then((r) => {
        if (vivo) setRes({ mun: municipioId, d: r.data, erro: null });
      })
      .catch((e) => {
        if (vivo)
          setRes({
            mun: municipioId, d: null,
            erro: e?.response?.data?.detail || "Não foi possível carregar.",
          });
      });
    return () => { vivo = false; };
  }, [municipioId]);

  const itens = useMemo(() => {
    const todos = d?.itens || [];
    return parlamentar
      ? todos.filter((p) => p.parlamentar === parlamentar)
      : todos;
  }, [d, parlamentar]);

  if (!municipioId) {
    return <Vazio>Selecione um município.</Vazio>;
  }
  if (carregando) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando parcerias…
      </div>
    );
  }
  if (erro) return <Vazio>{erro}</Vazio>;
  if (!d?.tem_dados) {
    return (
      <Vazio>{d?.motivo || "Sem parcerias coletadas para este município."}</Vazio>
    );
  }

  const ranking = d.por_parlamentar || [];
  const fora = d.fora_do_municipio?.qtd ?? 0;

  return (
    <div className="flex flex-col gap-4">
      {/* ⭐ CABEÇALHO SOLTO, e não um `Bloco` com `BlocoHead`. A primeira versão
          embrulhava título + KPIs num cartão só, e os quatro `Numero` — que já
          são `bi-card` — viravam CARTÃO DENTRO DE CARTÃO, encostados na borda
          do de fora (o `Bloco` não traz padding próprio). Este é o mesmo
          cabeçalho das Obras Federais e das Emendas Federais: h1, o parágrafo
          do que a tela é, e a régua de números logo abaixo, no fundo da
          página. */}
      <header>
        <TituloTela>Parcerias</TituloTela>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug"
           style={{ color: "var(--bi-muted)" }}>
          O módulo do Transferegov que processa as transferências de 2024 em
          diante — onde a <b>emenda de saúde</b> vira proposta e, depois,
          instrumento. Nas propostas listadas aqui o parlamentar que indicou o
          recurso vem nomeado na própria fonte.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Numero
          icon={Landmark}
          rotulo="Propostas"
          valor={String(d.total ?? 0)}
          /* ⚠️ O cartão conta a ADMINISTRAÇÃO MUNICIPAL. O resto continua na
             lista abaixo, marcado — esconder faria a contagem não bater com o
             portal, e somar diria que a prefeitura recebeu o que não recebeu. */
          sub={fora > 0
            ? `+ ${fora} de outro recebedor no município`
            : undefined}
        />
        <Numero icon={Wallet} rotulo="Valor total" valor={brl(d.valor_total)} />
        {/* ⚠️ A CONTAGEM, e não o valor — que seria o mesmo do cartão ao lado.
            Nesta fonte o valor da proposta É o da emenda em quase toda linha
            (538 de 547 no freitas, 691 de 706 no trust, 14 de 14 em Monte Sião),
            então dois cartões com o mesmo número não informavam nada e faziam
            quem lê desconfiar de erro — o dono desconfiou, olhando Nova Palma,
            onde os dois davam R$ 2.184.085,00. «11 de 11» diz o que o valor
            repetido não dizia: toda proposta tem parlamentar nomeado. */}
        <Numero
          icon={HandCoins}
          rotulo="Com emenda identificada"
          valor={`${d.com_emenda ?? 0} de ${d.total ?? 0}`}
          sub={(d.total ?? 0) > 0 && d.com_emenda === d.total
            ? "todas com parlamentar nomeado"
            : `${(d.total ?? 0) - (d.com_emenda ?? 0)} sem emenda na fonte`}
          tom={(d.total ?? 0) > 0 && d.com_emenda === d.total ? "ok" : "neutro"}
        />
        <Numero icon={Users} rotulo="Parlamentares"
                valor={String(ranking.length)} />
      </div>

      {/* ⭐ O QUE ACONTECEU COM O DINHEIRO (15/09/2026). A tela mostrava que a
          parceria existe e quanto vale; agora mostra se o dinheiro saiu, onde
          está e o que o município ainda deve fazer. Pago é pela ORDEM BANCÁRIA
          (a situação da parceria diz "Aprovada" em parceria já paga), e o
          `medidas` diz quanto da carteira o coletor já percorreu — R$ 0 pago
          numa carteira ainda não medida não é "nada foi pago". */}
      {d.execucao && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Numero
            icon={Banknote}
            rotulo="Pago (ordem bancária)"
            valor={d.execucao.medidas ? brl(d.execucao.pago) : "—"}
            sub={`${d.execucao.medidas} de ${d.total ?? 0} proposta(s) medida(s)`}
            tom={d.execucao.pago > 0 ? "ok" : "neutro"}
          />
          <Numero
            icon={Wallet}
            rotulo="Saldo em conta"
            valor={d.execucao.com_saldo ? brl(d.execucao.saldo) : "—"}
            sub="corrente + aplicação, na data informada pelo banco"
          />
          <Numero
            icon={Receipt}
            rotulo="Ingresso não classificado"
            valor={d.execucao.medidas ? brl(d.execucao.nao_classificado) : "—"}
            sub={d.execucao.com_nao_classificado
              ? `${d.execucao.com_nao_classificado} proposta(s) — pendência do município`
              : "nenhuma pendência de classificação"}
            tom={d.execucao.com_nao_classificado ? "atencao" : "neutro"}
          />
        </div>
      )}

      {/* ⭐ O RANKING ABRE A TELA porque é a pergunta que o gestor faz primeiro:
          quem trouxe recurso para a cidade. Clicar filtra a lista abaixo. */}
      {ranking.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Users}
            titulo="Por parlamentar"
            sub={parlamentar
              ? `filtrando por ${parlamentar} — clique de novo para ver todos`
              : fora > 0
                ? "só o que veio para a administração municipal · clique num nome para filtrar"
                : "clique num nome para filtrar as propostas"}
          />
          <Lista>
            {ranking.map((p) => (
              <ItemLinha
                key={p.parlamentar}
                titulo={
                  parlamentar === p.parlamentar
                    ? `${p.parlamentar} · filtrando`
                    : p.parlamentar
                }
                meta={`${p.propostas} proposta${p.propostas > 1 ? "s" : ""}` +
                      (p.tipo ? ` · ${p.tipo}` : "")}
                valor={<span className="bi-num">{brl(p.valor)}</span>}
                onClick={() =>
                  setParlamentar(parlamentar === p.parlamentar ? "" : p.parlamentar)}
              />
            ))}
          </Lista>
        </Bloco>
      )}

      {/* ⭐ EMENDAS INDICADAS AO MUNICÍPIO — a pergunta nova: "tem dinheiro
          indicado para nós que ainda não virou proposta?". A fonte lista a
          indicação antes da proposta existir; a que ainda não tem proposta é a
          que pede ação da prefeitura. */}
      {(d.emendas_indicadas?.length ?? 0) > 0 && (() => {
        const ind = d.emendas_indicadas!;
        const semProposta = ind.filter((e) => !e.tem_proposta);
        return (
          <Bloco className="p-3">
            <BlocoHead
              icon={HandCoins}
              titulo="Emendas indicadas ao município"
              sub={`${ind.length} indicação(ões) · ${semProposta.length} ainda sem proposta coletada`}
            />
            <Lista>
              {[...semProposta, ...ind.filter((e) => e.tem_proposta)].map((e, i) => (
                <ItemLinha
                  key={`${e.numero_emenda}-${i}`}
                  titulo={`${e.parlamentar || "Parlamentar não informado"} · emenda ${e.numero_emenda || "-"}`}
                  valor={<span className="bi-num">{brl(e.valor_total)}</span>}
                  meta={
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Selo tom={e.tem_proposta ? "ok" : "atencao"}>
                        {e.tem_proposta ? "virou proposta" : "ainda sem proposta"}
                      </Selo>
                      {!e.municipal && (
                        <Selo tom="atencao" title={e.natureza_juridica || undefined}>
                          não é da prefeitura
                        </Selo>
                      )}
                      {e.ano && <span>{e.ano}</span>}
                      {e.tipo && <span>{e.tipo}</span>}
                      <span>{e.beneficiario}</span>
                      {(e.valor_gnd3 || e.valor_gnd4) && (
                        <span className="bi-num">
                          {e.valor_gnd3 ? `custeio ${brl(e.valor_gnd3)}` : ""}
                          {e.valor_gnd3 && e.valor_gnd4 ? " · " : ""}
                          {e.valor_gnd4 ? `investimento ${brl(e.valor_gnd4)}` : ""}
                        </span>
                      )}
                      {e.indicacoes.length > 0 && (
                        <span title={e.indicacoes.map((x) => textoDe(x.nm_solicitante)).filter(Boolean).join("; ")}>
                          {e.indicacoes.length} apoiador(es)
                        </span>
                      )}
                    </span>
                  }
                />
              ))}
            </Lista>
          </Bloco>
        );
      })()}

      <Bloco className="p-3">
        <BlocoHead
          icon={Landmark}
          titulo={parlamentar ? `Propostas · ${parlamentar}` : "Propostas"}
          sub={`${itens.length} de ${d.total} · a fonte publica de 2024 em diante`}
        />
        <Lista>
          {itens.map((p) => (
            <LinhaProposta key={p.id_proposta} p={p} onDetalhe={() => setDetId(p.id_proposta)} />
          ))}
        </Lista>
        {itens.length === 0 && (
          <Vazio>Nenhuma proposta deste parlamentar.</Vazio>
        )}
        {fora > 0 && !parlamentar && (
          <p className="mt-3 text-[11px] leading-relaxed"
             style={{ color: "var(--bi-muted)" }}>
            {fora} proposta{fora > 1 ? "s" : ""} acima {fora > 1 ? "têm" : "tem"}{" "}
            como recebedor uma entidade do município que não é a administração
            municipal — fundo estadual, associação, cooperativa. {fora > 1
              ? "Elas aparecem" : "Ela aparece"} na lista porque o dinheiro chega
            à cidade, mas {fora > 1 ? "ficam" : "fica"} fora dos totais e do
            ranking: não é recurso da prefeitura.
          </p>
        )}
      </Bloco>

      {(d.por_situacao?.length ?? 0) > 0 && (
        <Bloco className="p-3">
          <BlocoHead icon={Building2} titulo="Por situação" />
          <div className="flex flex-wrap gap-2">
            {d.por_situacao!.map((s) => (
              <Selo key={s.situacao} tom={situacaoTom(s.situacao)}>
                {s.situacao} · {s.qtd}
              </Selo>
            ))}
          </div>
        </Bloco>
      )}

      {detId !== null && <DetalheProposta id={detId} onFechar={() => setDetId(null)} />}
    </div>
  );
}

/** Uma proposta na lista — FECHADA por padrão.
 *
 *  ⚠️ NASCEU SEMPRE ABERTA, e foi assim que o dono a viu: cada uma das onze
 *  linhas despejava dez campos mais o parágrafo de «resultado esperado», e a
 *  lista virava uma parede de texto de várias telas de rolagem. Lista é para
 *  varrer; detalhe é para quem pediu. O gesto de abrir é o mesmo das Obras
 *  Federais e das Emendas Federais — nesta identidade, item de lista que
 *  esconde detalhe SEMPRE abre no clique, e nunca vem aberto.
 *
 *  ⚠️ E O `cols={4}` NÃO É ENFEITE. Sem `cols`, a peça `Campos` abre UMA COLUNA
 *  POR CAMPO: com dez campos, dez colunas de ~150px numa janela de 1920, e
 *  «FUNDO PÚBLICO DA ADMINISTRAÇÃO MUNICIPAL» saía como «FUNDO PÚBLICO DA A…».
 *  Era metade do que o dono chamou de "formatação toda bugada". */
function LinhaProposta({ p, onDetalhe }: { p: Proposta; onDetalhe: () => void }) {
  const [aberto, setAberto] = useState(false);
  const r = p.resumo;
  return (
    <ItemLinha
      titulo={p.objeto || `Proposta ${p.id_proposta}`}
      valor={<span className="bi-num">{brl(p.valor)}</span>}
      onClick={() => setAberto((v) => !v)}
      expandido={aberto}
      meta={
        <span className="flex flex-wrap items-center gap-1.5">
          <Selo tom={situacaoTom(p.situacao)}>{p.situacao || "—"}</Selo>
          {/* ⚠️ Proposta sem instrumento não é erro: o ciclo tem dois passos e a
              maioria do ano corrente ainda não celebrou. */}
          <Selo tom={p.id_parceria ? "ok" : "neutro"}>
            {p.id_parceria ? "parceria celebrada" : "não celebrada"}
          </Selo>
          {/* ⚠️ O aviso é a diferença entre «a cidade recebeu» e «alguém na
              cidade recebeu». O Fundo Estadual de Saúde atende o estado
              inteiro; a associação privada não é a prefeitura. */}
          {!p.municipal && (
            <Selo tom="atencao" title={p.natureza_juridica || undefined}>
              não é da prefeitura
            </Selo>
          )}
          {/* ⭐ DA ÁRVORE DA PROPOSTA: se o dinheiro saiu (pela ordem
              bancária), onde está, e se o município ainda deve classificar o
              ingresso. Selo só quando há o que dizer. */}
          {!!r?.pago && (
            <Selo tom="ok" title={`${r.n_ordens_bancarias ?? 0} ordem(ns) bancária(s)`}>
              Pago {brl(r.pago)}{r.data_ultima_ob ? ` em ${dataBR(r.data_ultima_ob)}` : ""}
            </Selo>
          )}
          {r?.saldo_total != null && r.saldo_total > 0 && (
            <Selo tom="neutro" title={`Corrente ${brl(r.saldo_corrente)} · aplicação ${brl(r.saldo_investimento)} em ${dataBR(r.data_saldo ?? null) ?? "-"}`}>
              Saldo {brl(r.saldo_total)}
            </Selo>
          )}
          {!!r?.nao_classificado && (
            <Selo tom="atencao" title="Ingresso na conta ainda não classificado pelo município">
              Ingresso não classificado
            </Selo>
          )}
          {p.parlamentar && <span>{p.parlamentar}</span>}
          {p.ano && <span>{p.ano}</span>}
        </span>
      }
    >
      {aberto && (
        <div className="mt-2 flex flex-col gap-2">
          <Campos
            cols={4}
            campos={[
              { rotulo: "Emenda", valor: p.numero_emenda, mono: true },
              { rotulo: "Parlamentar", valor: p.parlamentar },
              { rotulo: "Tipo de emenda", valor: p.tipo_emenda },
              { rotulo: "Valor da emenda", valor: brl(p.valor_emenda) },
              /* Raramente é a prefeitura: em Nova Palma as 11 propostas são do
                 Fundo Municipal da Saúde, com CNPJ próprio. */
              { rotulo: "Recebedor", valor: p.ente_recebedor },
              { rotulo: "Natureza jurídica", valor: p.natureza_juridica },
              { rotulo: "Proposta em", valor: dataBR(p.data_proposta) },
              { rotulo: "Instrumento", valor: p.codigo_parceria, mono: true },
              { rotulo: "Situação do instrumento", valor: p.situacao_parceria },
              { rotulo: "Assinatura", valor: dataBR(p.data_assinatura) },
            ].filter((c) => c.valor && c.valor !== "—")}
          />
          {p.resultado_esperado && (
            <p className="text-[11px] leading-relaxed"
               style={{ color: "var(--bi-muted)" }}>
              {p.resultado_esperado}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            {/* O detalhe completo: plano de trabalho, parecer, conta, extrato e
                pagamentos — tudo do banco, colhido pela coleta noturna. */}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDetalhe(); }}
              className="inline-flex w-fit items-center gap-1 rounded px-2 py-1 text-[11px] font-medium"
              style={{ background: "var(--bi-surface-2)", color: "var(--bi-text)" }}
            >
              <Eye className="size-3" /> ver detalhe completo
            </button>
            {/* O link deixa qualquer número desta tela conferível na fonte — a
                mesma disciplina do `url_fonte` das Obras. */}
            <a
              href={p.url_fonte}
              target="_blank"
              rel="noreferrer"
              className="inline-flex w-fit items-center gap-1 text-[11px] underline"
              style={{ color: "var(--bi-muted)" }}
            >
              <ExternalLink className="size-3" /> ver na fonte
            </a>
          </div>
        </div>
      )}
    </ItemLinha>
  );
}

/** O DETALHE COMPLETO de uma proposta — do banco, sem requisição à fonte.
 *
 *  ⭐ É o que a coleta passou a trazer em 15/09/2026 da API oficial inteira. As
 *  abas seguem o ciclo da proposta: o que foi PEDIDO (proposta, plano de
 *  trabalho), o que foi ANALISADO (parecer), o que foi PAGO (execução) e ONDE O
 *  DINHEIRO ESTÁ (conta, extrato, pagamentos a terceiros). */
function DetalheProposta({ id, onFechar }: { id: number; onFechar: () => void }) {
  const [res, setRes] = useState<{ id: number; d: DetalheResp | null; erro: string | null } | null>(null);
  const [aba, setAba] = useState<AbaDet>("proposta");

  useEffect(() => {
    let vivo = true;
    api.get<DetalheResp>(`/parcerias/proposta/${id}`)
      .then((r) => { if (vivo) setRes({ id, d: r.data, erro: null }); })
      .catch((e) => {
        if (vivo) setRes({ id, d: null, erro: e?.response?.data?.detail || "Não foi possível carregar." });
      });
    return () => { vivo = false; };
  }, [id]);

  const carregando = !res || res.id !== id;
  const d = !carregando ? res!.d : null;
  const pr = d?.proposta || {};
  const arv = d?.detalhe || null;
  const par = (pr._parceria as Reg | undefined) || {};
  const em = (pr._emenda as Reg | undefined) || {};
  const ex = arv?.execucao || null;
  const r = arv?._resumo || null;
  const naoColhida = (
    <Vazio>
      O detalhe desta proposta ainda não foi colhido. A coleta passa por todas as
      propostas toda noite.
    </Vazio>
  );

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-5xl">
      <ModalHead
        titulo={t(pr.ds_objeto) !== "-" ? t(pr.ds_objeto) : `Proposta ${id}`}
        sub={`Proposta ${id}${par.cd_parceria ? ` · instrumento ${t(par.cd_parceria)}` : ""}`}
        onFechar={onFechar}
        abaixo={
          <Abas
            valor={aba}
            onChange={(v) => setAba(v)}
            opcoes={[
              { valor: "proposta" as const, label: "Proposta" },
              { valor: "plano" as const, label: "Plano de Trabalho" },
              { valor: "execucao" as const, label: "Execução" },
              { valor: "conta" as const, label: "Conta e Extrato" },
              { valor: "analise" as const, label: "Análise" },
              { valor: "emenda" as const, label: "Emenda e Instrumento" },
            ]}
          />
        }
      />
      {carregando ? (
        <div className="py-16 text-center">
          <Loader2 className="mx-auto size-8 animate-spin" style={{ color: "var(--bi-faint)" }} />
        </div>
      ) : !d ? (
        <ModalCorpo><Vazio>{res?.erro || "Não foi possível carregar."}</Vazio></ModalCorpo>
      ) : (
        <ModalCorpo className="flex flex-col gap-3">
          <div className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
            Fonte: API oficial do TransfereGov (Gestão de Parcerias)
            {d.fonte_atualizada_em && <> · fonte atualizada em {dia(d.fonte_atualizada_em)}</>}
            {d.detalhe_atualizado_em && <> · detalhe colhido em {dia(d.detalhe_atualizado_em)}</>}
            {" · "}
            <a href={d.url_fonte} target="_blank" rel="noreferrer" className="underline">ver na fonte</a>
          </div>

          <div key={aba} className="bi-pane-enter flex flex-col gap-3">
          {aba === "proposta" && (
            <>
              <Secao
                icon={FileText}
                titulo="Proposta"
                campos={[
                  { rotulo: "Situação", valor: t(pr.situacao_proposta), tom: situacaoTom(pr.situacao_proposta) },
                  { rotulo: "Valor", valor: brl(n(pr.vl_total_planejamento_gastos) ?? n(pr.nr_vlr_total)) },
                  { rotulo: "Proposta em", valor: dia(pr.dt_proposta) },
                  { rotulo: "Enviada para análise", valor: dia(pr.dt_envio_analise) },
                  { rotulo: "Recebedor", valor: t(pr.nm_ente_recebedor), span: 2 },
                  { rotulo: "CNPJ do recebedor", valor: t(pr.cnpj_ente_recebedor), mono: true },
                  { rotulo: "Natureza jurídica", valor: t(pr.nm_natureza_juridica) },
                  { rotulo: "Executor", valor: t(pr.nm_executor), span: 2 },
                  { rotulo: "Unidade gestora", valor: t(pr.nm_unidade_gestora), span: 2 },
                  { rotulo: "Nº no sistema de origem (FNS)", valor: t(par.nu_externo), mono: true },
                ]}
              >
                {([
                  ["Objeto", pr.ds_objeto],
                  ["Problema", pr.ds_problema_proposta],
                  ["Resultado esperado", pr.ds_resultado_esperado_proposta],
                  ["Público-alvo", pr.ds_publico_alvo_proposta],
                ] as const).map(([rot, txt]) => (
                  <div key={rot} className="mt-2.5">
                    <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>{rot}</div>
                    <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>{t(txt)}</p>
                  </div>
                ))}
              </Secao>
              {!arv ? naoColhida : (
                <>
                  <Secao icon={Target} titulo="Indicadores de resultado" sub={`${(arv.indicadores || []).length} indicador(es)`}>
                    {!(arv.indicadores || []).length ? (
                      <Vazio>A proposta não declarou indicadores de resultado.</Vazio>
                    ) : (
                      <div className="mt-2 flex flex-col gap-1.5">
                        {(arv.indicadores || []).map((ind, i) => (
                          <div key={i} className="text-[12px]">
                            <b>{t(ind.nm_indicador_proposta)}</b>{" "}
                            <span className="bi-num">{t(ind.vl_indicador_proposta)} {textoDe(ind.nm_unidade_medida_indicador_proposta) || ""}</span>
                            <div style={{ color: "var(--bi-muted)" }}>{t(ind.ds_resultado_esperado_proposta_resultado_indicador)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </Secao>
                  {arv.programa && (
                    <Secao
                      icon={Landmark}
                      titulo={`Programa — ${t(arv.programa.nm_programa)}`}
                      campos={[
                        { rotulo: "Código", valor: t(arv.programa.cd_programa), mono: true },
                        { rotulo: "Ano", valor: t(arv.programa.ano_programa) },
                        { rotulo: "Órgão", valor: t(arv.programa.sg_nome_ente_superior ?? arv.programa.nm_ente_superior), span: 2 },
                        { rotulo: "Objetivo", valor: t(arv.programa.ds_objetivo), span: 4, quebra: true },
                      ]}
                    />
                  )}
                </>
              )}
            </>
          )}

          {aba === "plano" && (!arv ? naoColhida : (
            <>
              {(arv.metas || []).map((meta, i) => (
                <Secao key={i} icon={Target} titulo={`Meta ${t(meta.cd_meta)} — ${t(meta.nm_meta)}`}>
                  {(meta.etapas_proposta || []).map((et, j) => (
                    <div key={j} className="mt-3">
                      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px] font-semibold" style={{ color: "var(--bi-muted)" }}>
                        <CalendarRange className="size-3.5" />
                        Etapa {t(et.cd_etapa)} · {dia(et.dt_inicio)} a {dia(et.dt_fim)}
                      </div>
                      <p className="mb-1.5 text-[12px]" style={{ color: "var(--bi-text)" }}>{t(et.ds_etapa)}</p>
                      {!(et.itens || []).length ? <Vazio>Sem itens nesta etapa.</Vazio> : (
                        <Grade rolagem minLargura="46rem" cols={COLS_ITEM}
                               cabecalho={[{ label: "Item" }, { label: "Unidade" }, { label: "Qtd.", direita: true },
                                           { label: "Unitário", direita: true }, { label: "Total", direita: true }, { label: "Categoria" }]}>
                          {(et.itens || []).map((it, k) => (
                            <GradeLinha key={k} cols={COLS_ITEM}>
                              <GradeCel title={textoDe(it.ds_item) || undefined}>{t(it.nm_item)}</GradeCel>
                              <GradeCel>{t(it.nm_unidade_medida)}</GradeCel>
                              <GradeCel tom="num">{t(it.qt_quantidade)}</GradeCel>
                              <GradeCel tom="num">{brl(n(it.vl_unitario_item))}</GradeCel>
                              <GradeCel tom="num">{brl(n(it.vl_total_item))}</GradeCel>
                              <GradeCel>{t(it.in_categoria_despesa)}</GradeCel>
                            </GradeLinha>
                          ))}
                        </Grade>
                      )}
                    </div>
                  ))}
                </Secao>
              ))}
              <Secao icon={CalendarRange} titulo="Cronograma de desembolso">
                {!(arv.cronograma || []).length ? <Vazio>Sem cronograma declarado.</Vazio> : (
                  <div className="mt-2">
                    <Grade cols={COLS_CRONO} cabecalho={[{ label: "Mês/Ano" }, { label: "Origem" }, { label: "Valor", direita: true }]}>
                      {(arv.cronograma || []).map((c, i) => (
                        <GradeLinha key={i} cols={COLS_CRONO}>
                          <GradeCel tom="data">{t(c.nr_ref_mes_data_especif)}/{t(c.nr_ref_ano_data_especif)}</GradeCel>
                          <GradeCel>{t(c.origem_recurso)}</GradeCel>
                          <GradeCel tom="num">{brl(n(c.vl_cronograma_desembolso))}</GradeCel>
                        </GradeLinha>
                      ))}
                    </Grade>
                  </div>
                )}
              </Secao>
            </>
          ))}

          {aba === "execucao" && (!arv ? naoColhida : !ex ? (
            <Vazio>A proposta ainda não virou parceria celebrada — não há execução financeira.</Vazio>
          ) : (
            <>
              <Secao
                icon={Banknote}
                titulo="Execução financeira"
                campos={[
                  { rotulo: "Empenhado", valor: brl(r?.empenhado) },
                  { rotulo: "Pago (ordem bancária)", valor: brl(r?.pago), tom: r?.pago ? "ok" : "normal" },
                  { rotulo: "Última OB", valor: dia(r?.data_ultima_ob) },
                  { rotulo: "Pago a terceiros (OPP)", valor: brl(r?.pago_a_terceiros) },
                ]}
              />
              <Secao icon={Receipt} titulo="Empenhos" sub={`${(ex.empenhos || []).length} empenho(s)`}>
                {!(ex.empenhos || []).length ? <Vazio>Nenhum empenho.</Vazio> : (
                  <div className="mt-2">
                    <Grade rolagem minLargura="44rem" cols={COLS_EMP}
                           cabecalho={[{ label: "Empenho" }, { label: "Emissão" }, { label: "Situação no SIAFI" },
                                       { label: "Favorecido" }, { label: "Valor", direita: true }]}>
                      {(ex.empenhos || []).map((e, i) => (
                        <GradeLinha key={i} cols={COLS_EMP}>
                          <GradeCel tom="id">{t(e.numero_nota_empenho_gerada)}</GradeCel>
                          <GradeCel tom="data">{dia(e.data_emissao)}</GradeCel>
                          <GradeCel>{t(e.in_situacao_siafi)}</GradeCel>
                          <GradeCel title={textoDe(e.identificacao_favorecido) || undefined}>{t(e.nome_favorecido)}</GradeCel>
                          <GradeCel tom="num">{brl(n(e.valor_empenho))}</GradeCel>
                        </GradeLinha>
                      ))}
                    </Grade>
                  </div>
                )}
              </Secao>
              <Secao icon={Banknote} titulo="Documentos hábeis e ordens bancárias">
                {!(ex.documentos_habeis || []).length ? <Vazio>Nenhum documento hábil emitido.</Vazio> : (
                  <div className="mt-2">
                    <Grade rolagem minLargura="50rem" cols={COLS_DH}
                           cabecalho={[{ label: "Documento" }, { label: "Emissão" }, { label: "Valor", direita: true },
                                       { label: "Situação" }, { label: "OP" }, { label: "OB" }, { label: "Data OB" }]}>
                      {(ex.documentos_habeis || []).flatMap((dh, i) => {
                        const ords = dh.ordens || [];
                        const linhas = ords.length ? ords : [{} as Reg];
                        return linhas.map((op, j) => (
                          <GradeLinha key={`${i}-${j}`} cols={COLS_DH}>
                            <GradeCel tom="id">{t(dh.nr_documento_habil ?? dh.nr_minuta_dh)}</GradeCel>
                            <GradeCel tom="data">{dia(dh.dt_emissao)}</GradeCel>
                            <GradeCel tom="num">{brl(n(dh.vl_documento_habil))}</GradeCel>
                            <GradeCel>{t(op.in_situacao_op ?? dh.in_situacao_dh)}</GradeCel>
                            <GradeCel tom="id">{t(op.nr_ordem_pagamento)}</GradeCel>
                            <GradeCel tom="id">{t(op.nr_ordem_bancaria)}</GradeCel>
                            <GradeCel tom="data">{dia(op.dt_emissao_ordem_bancaria)}</GradeCel>
                          </GradeLinha>
                        ));
                      })}
                    </Grade>
                  </div>
                )}
              </Secao>
            </>
          ))}

          {aba === "conta" && (!arv ? naoColhida : !ex ? (
            <Vazio>A proposta ainda não virou parceria celebrada — não há conta.</Vazio>
          ) : !(ex.contas || []).length ? (
            <Vazio>A fonte não informa conta para esta parceria.</Vazio>
          ) : (
            (ex.contas || []).map((c, i) => (
              <React.Fragment key={i}>
                <Secao
                  icon={Wallet}
                  titulo={`Conta ${t(c.tx_conta)} — ${t(c.nm_banco)}`}
                  sub={`agência ${t(c.tx_numero)} ${textoDe(c.nm_agencia) || ""}`}
                  campos={[
                    { rotulo: "Saldo em conta corrente", valor: brl(n(c.vl_saldo_conta_corrente)),
                      title: `em ${dia(c.dt_referencia_saldo_conta_corrente)}` },
                    { rotulo: "Saldo aplicado", valor: brl(n(c.vl_saldo_conta_investimento)),
                      title: `em ${dia(c.dt_referencia_saldo_conta_investimento)}` },
                    { rotulo: "Data do saldo aplicado", valor: dia(c.dt_referencia_saldo_conta_investimento) },
                    { rotulo: "Aberta em", valor: dia(c.dt_abertura) },
                    { rotulo: "Situação da conta", valor: t(c.tx_descricao), tom: situacaoTom(c.tx_descricao) },
                    { rotulo: "Detalhe da situação", valor: t(c.tx_detalhamento), span: 3, quebra: true },
                  ]}
                />
                <Secao icon={Receipt} titulo="Classificação de ingresso"
                       sub="quem depositou, quanto, e se o município já classificou">
                  {!(c.classificacoes_ingresso || []).length ? <Vazio>Nenhum ingresso a classificar.</Vazio> : (
                    <div className="mt-2">
                      <Grade rolagem minLargura="48rem" cols={COLS_ING}
                             cabecalho={[{ label: "Data" }, { label: "Depositante" }, { label: "Documento" },
                                         { label: "Classificação" }, { label: "Valor", direita: true },
                                         { label: "Não classificado", direita: true }]}>
                        {(c.classificacoes_ingresso || []).map((ci, j) => (
                          <GradeLinha key={j} cols={COLS_ING}
                                      alerta={(n(ci.vl_nao_classificado) ?? 0) > 0}>
                            <GradeCel tom="data">{dia(ci.dt_movimento_lancamento)}</GradeCel>
                            <GradeCel>{t(ci.tx_nome_depositante)}</GradeCel>
                            <GradeCel tom="id">{t(ci.nu_identificacao_depositante)}</GradeCel>
                            <GradeCel>{t(ci.tx_descricao_classificacao_ingresso)}</GradeCel>
                            <GradeCel tom="num">{brl(n(ci.vl_lancamento))}</GradeCel>
                            <GradeCel tom="num">{brl(n(ci.vl_nao_classificado))}</GradeCel>
                          </GradeLinha>
                        ))}
                      </Grade>
                    </div>
                  )}
                </Secao>
                <Secao icon={Banknote} titulo="Extrato da conta" sub={`${(c.extrato || []).length} lançamento(s)`}>
                  {!(c.extrato || []).length ? <Vazio>Nenhum lançamento publicado.</Vazio> : (
                    <div className="mt-2">
                      <Grade rolagem minLargura="48rem" cols={COLS_EXT}
                             cabecalho={[{ label: "Data" }, { label: "C/D" }, { label: "Operação" },
                                         { label: "Depositante / Beneficiário" }, { label: "Documento" },
                                         { label: "Valor", direita: true }]}>
                        {[...(c.extrato || [])]
                          .sort((a, b) => String(b.dt_movimento_lancamento_extrato_bancario ?? "").localeCompare(String(a.dt_movimento_lancamento_extrato_bancario ?? "")))
                          .map((l, j) => {
                            const credito = textoDe(l.in_transacao) === "Crédito";
                            return (
                              <GradeLinha key={j} cols={COLS_EXT}>
                                <GradeCel tom="data">{dia(l.dt_movimento_lancamento_extrato_bancario)}</GradeCel>
                                <GradeCel>{t(l.in_transacao)}</GradeCel>
                                <GradeCel>{t(l.nm_tipo_operacao)}</GradeCel>
                                <GradeCel>{t(credito ? l.tx_nome_depositante_extrato_bancario : l.tx_nome_beneficiario)}</GradeCel>
                                <GradeCel tom="id">{t(credito ? l.nu_identificacao_depositante_extrato_bancario : l.nu_identificacao_beneficiario)}</GradeCel>
                                <GradeCel tom="num">{brl(n(l.vl_lancamento_extrato_bancario))}</GradeCel>
                              </GradeLinha>
                            );
                          })}
                      </Grade>
                    </div>
                  )}
                </Secao>
                {/* ⭐ QUEM RECEBEU DA CONTA: os pagamentos que o município fez a
                    terceiros pela própria conta da parceria (OPP). */}
                <Secao icon={HandCoins} titulo="Pagamentos a terceiros (OPP)" sub={`${(c.opp || []).length} pagamento(s)`}>
                  {!(c.opp || []).length ? <Vazio>Nenhum pagamento a terceiros registrado nesta conta.</Vazio> : (
                    <div className="mt-2">
                      <Grade rolagem minLargura="48rem" cols={COLS_OPP}
                             cabecalho={[{ label: "Data" }, { label: "Beneficiário" }, { label: "Documento" },
                                         { label: "Tipo / Situação" }, { label: "Valor", direita: true },
                                         { label: "Efetivado", direita: true }]}>
                        {(c.opp || []).map((o, j) => (
                          <GradeLinha key={j} cols={COLS_OPP}>
                            <GradeCel tom="data">{dia(o.dh_efetivacao ?? o.dh_inclusao_opp)}</GradeCel>
                            <GradeCel title={textoDe(o.tx_descricao_operacao) || undefined}>{t(o.nm_beneficiario)}</GradeCel>
                            <GradeCel tom="id">{t(o.nr_cpf_cnpj_beneficiario_mascarado ?? o.nr_cpf_cnpj_beneficiario)}</GradeCel>
                            <GradeCel>{t(o.nm_tipo_opp)} · {t(o.nm_situacao)}</GradeCel>
                            <GradeCel tom="num">{brl(n(o.vl_opp))}</GradeCel>
                            <GradeCel tom="num">{brl(n(o.vl_efetivado))}</GradeCel>
                          </GradeLinha>
                        ))}
                      </Grade>
                    </div>
                  )}
                </Secao>
              </React.Fragment>
            ))
          ))}

          {aba === "analise" && (!arv ? naoColhida : !(arv.analises || []).length ? (
            <Vazio>Nenhuma análise registrada para esta proposta.</Vazio>
          ) : (
            <Secao icon={MessageSquareText} titulo="Análises da proposta" sub={`${(arv.analises || []).length} análise(s)`}>
              <div className="mt-2 flex flex-col gap-2.5">
                {(arv.analises || []).map((a, i) => (
                  <div key={i} className="border-t pt-2" style={{ borderColor: "var(--bi-line)" }}>
                    <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                      <span className="font-medium">{t(a.in_fase_analise)}</span>
                      <Selo tom={situacaoTom(a.in_resultado_analise)}>{t(a.in_resultado_analise)}</Selo>
                      <span className="bi-num text-[11px]" style={{ color: "var(--bi-faint)" }}>{dia(a.dh_analise_proposta)}</span>
                    </div>
                    <p className="mt-1 text-[12px] leading-relaxed break-words whitespace-pre-line" style={{ color: "var(--bi-muted)" }}>
                      {t(a.ds_parecer)}
                    </p>
                  </div>
                ))}
              </div>
            </Secao>
          ))}

          {aba === "emenda" && (
            <>
              <Secao
                icon={HandCoins}
                titulo="Emenda parlamentar"
                campos={[
                  { rotulo: "Emenda", valor: t(em.nr_emenda_proposta), mono: true },
                  { rotulo: "Parlamentar", valor: t(em.nm_parlamentar_proposta) },
                  { rotulo: "Tipo", valor: t(em.in_tipo_emenda_parlamentar_proposta) },
                  { rotulo: "GND", valor: t(em.in_tipo_gnd) },
                  { rotulo: "Valor da emenda", valor: brl(n(em.valor_emenda)) },
                  { rotulo: "Distribuição", valor: t(em.in_tipo_distribuicao) },
                ]}
              />
              <Secao
                icon={Landmark}
                titulo="Instrumento (parceria)"
                campos={[
                  { rotulo: "Código", valor: t(par.cd_parceria), mono: true },
                  { rotulo: "Situação", valor: t(par.in_situacao_parceria), tom: situacaoTom(par.in_situacao_parceria),
                    title: "A situação da parceria não diz se o dinheiro saiu: veja a aba Execução" },
                  { rotulo: "Origem", valor: t(par.tp_origem) },
                  { rotulo: "Nº no sistema de origem", valor: t(par.nu_externo), mono: true },
                  { rotulo: "Assinatura", valor: dia(par.dh_assinatura) },
                  { rotulo: "Autorização de execução", valor: t(par.in_situacao_autorizacao_execucao) },
                  { rotulo: "Processo SEI", valor: t(par.cd_processo_sei), mono: true },
                ]}
              />
            </>
          )}
          </div>
        </ModalCorpo>
      )}
    </Modal>
  );
}
