"use client";

/* EMENDAS PARLAMENTARES FEDERAIS — a carteira do município e a execução dela.
 *
 * ⭐ O QUE ESTA TELA MOSTRA QUE NENHUMA OUTRA MOSTRAVA. A emenda federal
 * aparecia de raspão em dois lugares — como Transferência Especial em
 * «Especiais» e como selo `TE` na lista de Convênios — e sempre pelo mesmo
 * caminho: a emenda que virou PROPOSTA. Medido em 06/09/2026: 45% das emendas
 * de Nova Palma e 43% das de Monte Sião têm `ID_PROPOSTA` vazio. Quase metade
 * da carteira era invisível, e só o filtro por CNPJ do beneficiário a alcança.
 *
 * ⚠️⚠️ OS DOIS VALORES DESTA TELA RESPONDEM PERGUNTAS DIFERENTES:
 *   «Indicado»  = quanto DESTA emenda foi para ESTE beneficiário (dump).
 *   «Empenhado/Pago» = quanto da emenda INTEIRA a União movimentou (CGU), e é
 *   NACIONAL — uma emenda de bancada de R$ 30 mi que passou por aqui com
 *   R$ 250 mil traz R$ 30 mi.
 * Por isso os cartões de execução DIZEM o denominador, e a tela nunca soma um
 * com o outro.
 *
 * ⚠️ E «—» NÃO É R$ 0. Três estados, nunca dois: não consultada (ausência
 * NOSSA), não encontrada (a CGU não conhece o código) e zero (a CGU AFIRMANDO
 * zero). Preencher os dois primeiros com zero é a única forma de esta tela
 * mentir com números certos.
 *
 * ⚠️ «PAGO» INCLUI O RESTO A PAGAR. Emenda empenhada em dezembro é paga, quase
 * sempre, como resto no ano seguinte — olhar só `valor_pago` faria a tela
 * chamar de parada uma emenda já paga, e o gestor cobraria o parlamentar por
 * algo que aconteceu. A classificação é feita no servidor, para tela, PDF e TV
 * concordarem sobre o que é urgente.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Banknote, ExternalLink, Landmark, Loader2, Users,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { formatDataHora, horasDesde } from "@/lib/bi-format";
import {
  Abas, Aviso, Bloco, BlocoHead, Campos, Grade, GradeCel, GradeLinha,
  ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";

interface Emenda {
  codigo_emenda: string | null;
  numero_emenda: string | null;
  ano: number | null;
  autor: string | null;
  tipo: string | null;
  impositiva: boolean | null;
  orgao_siafi: string | null;
  orgao: string | null;
  beneficiario_cnpj: string | null;
  beneficiario_nome: string | null;
  beneficiario_prefeitura: boolean;
  codigo_confirmado: boolean;
  valor_indicado: number;
  propostas: string[];
  execucao_consultada: boolean;
  encontrada: boolean | null;
  documentos_n: number;
  valor_empenhado: number | null;
  valor_liquidado: number | null;
  valor_pago: number | null;
  valor_resto_inscrito: number | null;
  valor_resto_cancelado: number | null;
  valor_resto_pago: number | null;
  funcao: string | null;
  subfuncao: string | null;
  localidade_gasto: string | null;
  grupo: "nao_consultada" | "nao_encontrada" | "sem_empenho" | "parado"
       | "andamento" | "paga";
  alertas: string[];
  motivo: string | null;
  url_fonte: string;
}
interface Autor {
  autor: string; tipo: string | null; colegiado: boolean; emendas: number;
  indicado: number; empenhado: number; pago: number; parado_n: number;
  anos: number[];
}
interface Beneficiario {
  cnpj: string; nome: string | null; prefeitura: boolean; emendas: number;
  indicado: number;
}
interface Resp {
  tem_dados: boolean;
  estado: string; aviso: string; fonte_ligada: boolean;
  municipio_nome: string | null;
  coleta_em: string | null; coleta_falhas: number;
  execucao: { consultadas: number; total: number };
  escopo: { cnpjs: Beneficiario[] };
  totais: Record<string, number>;
  items: Emenda[];
  por_autor: Autor[];
  anos: number[];
  orgaos: Array<{ codigo: string; nome: string }>;
  tipos: string[];
}
interface Documento {
  data: string | null; fase: string | null; codigo_documento: string | null;
  documento_resumido: string | null; especie_tipo: string | null;
}

const brl = (v: number | null | undefined) =>
  v == null ? "—"
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL",
                                  maximumFractionDigits: 0 });
/* ⚠️ «—» e não «R$ 0». Zero é uma AFIRMAÇÃO que a CGU não fez quando ninguém
   perguntou a ela. Vale para os seis valores de execução. */
const brlOuTraco = (v: number | null | undefined) => (v == null ? "—" : brl(v));
const dia = (s: string | null) =>
  s ? new Date(s + "T12:00:00").toLocaleDateString("pt-BR") : "—";

const ROTULO_TIPO: Record<string, string> = {
  INDIVIDUAL: "Individual", BANCADA: "Bancada", COMISSAO: "Comissão",
  "RELATOR GERAL": "Relator-geral",
};
const ROTULO_GRUPO: Record<Emenda["grupo"], string> = {
  nao_consultada: "Execução não consultada",
  nao_encontrada: "Sem registro na CGU",
  sem_empenho: "Sem empenho",
  parado: "Sem pagamento",
  andamento: "Pago em parte",
  paga: "Paga",
};
const TOM_GRUPO: Record<Emenda["grupo"], "neutro" | "ok" | "atencao" | "critico"> = {
  nao_consultada: "neutro", nao_encontrada: "neutro", sem_empenho: "atencao",
  parado: "critico", andamento: "atencao", paga: "ok",
};
const ROTULO_ALERTA: Record<string, string> = {
  resto_a_pagar: "Resto a pagar",
  resto_cancelado: "Resto cancelado",
  impositiva_parada: "Impositiva sem pagamento",
};
/* ⚠️ MAPA LOCAL, e não `situacaoTom` de superficies.tsx: a regex de lá cobre
   «empenhad» e «liquidad», mas NÃO «pagament» — «Pagamento» cairia em neutro.
   Acrescentar lá é PR à parte: ~15 telas dependem daquela função, e mudar a cor
   de status do produto inteiro não cabe no PR de uma tela nova. */
const TOM_FASE: Record<string, "neutro" | "ok" | "atencao"> = {
  Empenho: "atencao", Liquidação: "atencao", Pagamento: "ok",
};

function Documentos({ codigo, municipioId }: { codigo: string; municipioId: string }) {
  const [d, setD] = useState<{ consultado_em: string | null;
    documentos: Documento[]; motivo: string } | null>(null);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let vivo = true;
    api
      .get(`/emendas-federais/${codigo}/documentos`,
           { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setD(r.data); })
      .catch(() => { if (vivo) setErro(true); });
    return () => { vivo = false; };
  }, [codigo, municipioId]);

  if (erro) return <Vazio>Não foi possível carregar a execução desta emenda.</Vazio>;
  if (!d) {
    return (
      <div className="flex items-center gap-2 py-2 text-[11px]"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-3 animate-spin" /> carregando a execução…
      </div>
    );
  }
  /* ⚠️ GAVETA VAZIA TEM DUAS CAUSAS E DUAS FRASES, e o servidor manda qual: «a
     CGU não publica documento» (consultado) ≠ «ainda não foi consultada»
     (ausência nossa). Uma frase só para as duas apagaria a diferença. */
  if (!d.documentos.length) return <Vazio>{d.motivo}</Vazio>;

  const cols = "grid-cols-[6.5rem_8rem_1fr_9rem]";
  return (
    <div className="flex flex-col gap-1">
      <Grade
        rolagem
        minLargura="32rem"
        cols={cols}
        cabecalho={[{ label: "Data" }, { label: "Fase" },
                    { label: "Documento" }, { label: "Espécie" }]}
      >
        {d.documentos.map((x, i) => (
          <GradeLinha key={`${x.codigo_documento}-${i}`} cols={cols}>
            <GradeCel tom="data">{dia(x.data)}</GradeCel>
            <GradeCel>
              {x.fase ? <Selo tom={TOM_FASE[x.fase] || "neutro"}>{x.fase}</Selo> : "—"}
            </GradeCel>
            <GradeCel tom="id" title={x.codigo_documento || undefined}>
              {x.documento_resumido || x.codigo_documento || "—"}
            </GradeCel>
            <GradeCel>{x.especie_tipo || "—"}</GradeCel>
          </GradeLinha>
        ))}
      </Grade>
      {/* ⚠️ A ressalva que impede a leitura errada da gaveta: estes documentos
          são da EMENDA, e uma emenda pode atender vários municípios. */}
      <p className="px-1 text-[10px] leading-snug" style={{ color: "var(--bi-muted)" }}>
        Documentos da emenda inteira — uma mesma emenda pode atender vários
        municípios, e a CGU não separa a fatia de cada um.
      </p>
    </div>
  );
}

function LinhaEmenda({ e, municipioId }: { e: Emenda; municipioId: string }) {
  const [aberto, setAberto] = useState(false);
  return (
    <ItemLinha
      titulo={
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="min-w-0">{e.autor || "Autor não informado"}</span>
          {/* ⚠️ SELO SÓ NA EXCEÇÃO. Emenda da prefeitura é a norma e não ganha
              chip; pintar 90% das linhas com «Prefeitura» apagaria o sinal.
              `tom="acento"` e não «atenção»: outro destinatário não é problema,
              é informação — e o nome vai POR EXTENSO, porque nós não adivinhamos
              «fundo» de «hospital» a partir da string. */}
          {!e.beneficiario_prefeitura && (
            <Selo tom="acento"
                  title="Emenda destinada a uma entidade do município, e não à Prefeitura">
              {e.beneficiario_nome || e.beneficiario_cnpj}
            </Selo>
          )}
          {e.impositiva && (
            <Selo title="Execução obrigatória por norma constitucional">
              Impositiva
            </Selo>
          )}
          <Selo tom={TOM_GRUPO[e.grupo]} title={e.motivo || undefined}>
            {ROTULO_GRUPO[e.grupo]}
          </Selo>
          {e.alertas.filter((a) => a !== "impositiva_parada").map((a) => (
            <Selo key={a} tom={a === "resto_cancelado" ? "critico" : "atencao"}>
              {ROTULO_ALERTA[a] || a}
            </Selo>
          ))}
        </span>
      }
      valor={<span className="bi-num">{brl(e.valor_indicado)}</span>}
      meta={
        <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {e.ano && <span>{e.ano}</span>}
          {e.tipo && <span>{ROTULO_TIPO[e.tipo] || e.tipo}</span>}
          {e.orgao && <span>{e.orgao}</span>}
          {e.funcao && <span>{e.funcao}</span>}
          {e.numero_emenda && <span>nº {e.numero_emenda}</span>}
        </span>
      }
      onClick={() => setAberto((v) => !v)}
      expandido={aberto}
    >
      {aberto && (
        <div className="mt-2 flex flex-col gap-2">
          {e.motivo && (
            <div className="text-[11px] leading-snug"
                 style={{ color: e.grupo === "parado" ? "var(--bi-crit-ink)"
                                                      : "var(--bi-muted)" }}>
              {e.motivo}
            </div>
          )}
          <Campos
            cols={3}
            campos={[
              { rotulo: "Indicado ao município", valor: brl(e.valor_indicado) },
              { rotulo: "Empenhado (emenda inteira)",
                valor: brlOuTraco(e.valor_empenhado) },
              { rotulo: "Liquidado", valor: brlOuTraco(e.valor_liquidado) },
              { rotulo: "Pago", valor: brlOuTraco(e.valor_pago),
                tom: e.grupo === "parado" ? "critico" : "normal" },
              { rotulo: "Resto a pagar inscrito",
                valor: brlOuTraco(e.valor_resto_inscrito), tom: "atencao" },
              { rotulo: "Resto a pagar pago", valor: brlOuTraco(e.valor_resto_pago) },
              { rotulo: "Resto cancelado",
                valor: brlOuTraco(e.valor_resto_cancelado),
                tom: (e.valor_resto_cancelado || 0) > 0 ? "critico" : "normal" },
              { rotulo: "Beneficiário",
                valor: e.beneficiario_nome || e.beneficiario_cnpj || "—" },
              { rotulo: "Órgão", valor: e.orgao || "—" },
              { rotulo: "Subfunção", valor: e.subfuncao || "—" },
              { rotulo: "Localidade do gasto (CGU)",
                valor: e.localidade_gasto || "—" },
              { rotulo: "Propostas no SICONV",
                valor: e.propostas.length ? e.propostas.join(", ")
                                          : "nenhuma — emenda sem proposta" },
            ]}
          />
          {e.codigo_emenda && (
            <div className="flex flex-col gap-1">
              <div className="text-[11px] font-semibold">Execução, documento a documento</div>
              <Documentos codigo={e.codigo_emenda} municipioId={municipioId} />
            </div>
          )}
          <a href={e.url_fonte} target="_blank" rel="noreferrer"
             className="inline-flex w-fit items-center gap-1 text-[11px] underline"
             style={{ color: "var(--bi-accent-ink)" }}>
            <ExternalLink className="size-3" />
            conferir esta emenda no Portal da Transparência
          </a>
        </div>
      )}
    </ItemLinha>
  );
}

export default function EmendasFederaisPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ A RESPOSTA GUARDA DE QUAL MUNICÍPIO ELA É, e `carregando` é DERIVADO —
     o mesmo desenho da tela de Obras Federais, pela mesma razão: ao TROCAR de
     município, um `d` que sobrou do anterior apareceria por um quadro sob o
     cabeçalho do novo. */
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null }>(
    { mun: "", d: null, erro: null });
  const [anos, setAnos] = useState<string[]>([]);
  const [autorSel, setAutorSel] = useState("");
  const [benefSel, setBenefSel] = useState("");
  const [aba, setAba] = useState<"acao" | "autor" | "todas">("acao");

  const daVez = res.mun === municipioId;
  const carregando = !!municipioId && !daVez;
  const d = daVez ? res.d : null;
  const erro = daVez ? res.erro : null;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<Resp>("/emendas-federais", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setRes({ mun: municipioId, d: r.data, erro: null }); })
      .catch((e) => {
        if (vivo) setRes({ mun: municipioId, d: null,
          erro: e?.response?.data?.detail || "Não foi possível carregar." });
      });
    return () => { vivo = false; };
  }, [municipioId]);

  const aplicarAnos = useCallback((a: string[]) => setAnos(a), []);
  useAnoCorrentePadrao(d?.anos, aplicarAnos);

  const filtradas = useMemo(
    () => (d?.items || []).filter(
      (e) =>
        (!anos.length || (e.ano != null && anos.includes(String(e.ano)))) &&
        (!autorSel || e.autor === autorSel) &&
        (!benefSel ||
         (benefSel === "prefeitura" ? e.beneficiario_prefeitura
                                    : !e.beneficiario_prefeitura)),
    ),
    [d, anos, autorSel, benefSel],
  );
  /* ⚠️ «Precisa de cobrança» é ESTREITO de propósito: emenda «não consultada»
     NÃO entra. Se entrasse, um município recém-ligado abriria com metade da
     carteira "urgente" — que é o mesmo que nenhuma. */
  const acao = useMemo(
    () => filtradas.filter((e) => e.grupo === "parado"
                                || e.alertas.includes("resto_a_pagar")),
    [filtradas]);
  /* ⚠️ Os totais acompanham o FILTRO, e não o servidor: cartão dizendo 44 com 6
     emendas na lista abaixo faz o gestor desconfiar de tudo o mais. */
  const soma = useCallback(
    (f: (e: Emenda) => number | null) =>
      filtradas.reduce((s, e) => s + (f(e) || 0), 0),
    [filtradas]);
  const consultadasNoFiltro = filtradas.filter((e) => e.execucao_consultada).length;

  const autoresFiltrados = useMemo(() => {
    const vivos = new Set(filtradas.map((e) => e.autor || ""));
    return (d?.por_autor || []).filter((a) => vivos.has(a.autor));
  }, [d, filtradas]);

  if (!municipioId) {
    return <div className="p-6"><Vazio>Selecione um município para ver as emendas federais.</Vazio></div>;
  }
  if (carregando) {
    return (
      <div className="flex items-center gap-2 p-6 text-[13px]"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando emendas federais…
      </div>
    );
  }
  if (erro) return <div className="p-6"><Vazio>{erro}</Vazio></div>;

  const t = d?.totais || {};
  /* ⚠️ O AVISO VAI ANTES DO CONTEÚDO, nunca no rodapé — a regra do
     `AvisoCurado`: quem lê o rodapé já leu a tela inteira acreditando nela. */
  const aviso = d?.aviso ? (
    <Aviso
      tom={d.estado === "sem_cnpj" ? "critico" : "atencao"}
      icon={AlertTriangle}
      titulo={
        d.estado === "sem_chave" ? "Carteira completa, execução ainda não consultada"
        : d.estado === "sem_cnpj" ? "Falta o CNPJ do município"
        : d.estado === "sem_emendas" ? "Nenhuma emenda federal encontrada"
        : d.estado === "sem_coleta" ? "A coleta ainda não rodou"
        : "Execução consultada em parte da carteira"
      }
    >
      {d.aviso}
      {/* ⭐ O que torna a frase VERIFICÁVEL em vez de defensiva: quais CNPJ
          foram, de fato, procurados. */}
      {d.estado === "sem_emendas" && !!d.escopo.cnpjs.length && (
        <div className="mt-1">
          CNPJ consultados: {d.escopo.cnpjs.map((b) => b.nome || b.cnpj).join(" · ")}
        </div>
      )}
    </Aviso>
  ) : null;

  if (!d?.tem_dados) {
    return (
      <div className="flex flex-col gap-3 p-4 md:p-6">
        <header>
          <h1 className="bi-title text-[18px]">Emendas Parlamentares Federais</h1>
        </header>
        {aviso}
        {!d?.aviso && <Vazio>Sem emendas federais coletadas para este município.</Vazio>}
      </div>
    );
  }

  const secoes: Array<[string, string, Emenda[]]> = [
    ["Precisa de cobrança",
     "empenhada e sem pagamento, ou com resto a pagar em aberto", acao],
  ];

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <header>
        <h1 className="bi-title text-[18px]">Emendas Parlamentares Federais</h1>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug"
           style={{ color: "var(--bi-muted)" }}>
          A carteira de emendas federais destinadas ao município, reconhecida
          pelo <b>CNPJ do beneficiário</b> nos dados abertos do TransfereGov — o
          que alcança também as emendas que nunca viraram proposta. A execução
          (empenhado, liquidado, pago) vem do Portal da Transparência da CGU.
        </p>
        {/* Selo de frescor, no dialeto das demais telas. ⚠️ Com falha, avisa SEM
            datar: o carimbo acontece também no erro (anti-starvation do
            rodízio), então a data seria a do último ERRO. */}
        {(d.coleta_falhas ?? 0) > 0 ? (
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>
            não foi possível concluir a última coleta
            {d.items.length > 0 ? " — exibindo os últimos dados obtidos" : ""}
          </p>
        ) : d.coleta_em ? (
          <p className="mt-1 text-[11px]"
             style={{ color: (horasDesde(d.coleta_em) ?? 0) > 26
               ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}>
            Atualizado em {formatDataHora(d.coleta_em)}
            {" · execução consultada em "}
            {d.execucao.consultadas} de {d.execucao.total} emendas
          </p>
        ) : null}
      </header>

      {aviso}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Numero icon={Landmark} rotulo="Emendas no filtro" valor={filtradas.length}
                sub={`de ${t.emendas} na carteira`} />
        {/* ⭐ O `sub` DESTE CARTÃO É O CORAÇÃO DA HONESTIDADE DA TELA. «R$ 13,68
            mi para Nova Palma» não é mentira, mas o gestor não pode gastar o que
            foi para o Hospital N. S. da Piedade. Um filtro com padrão «só
            prefeitura» esconderia dinheiro; um total sem ressalva prometeria
            caixa que não existe. A segunda linha resolve os dois de graça. */}
        <Numero icon={Banknote} rotulo="Indicado" valor={brl(soma((e) => e.valor_indicado))}
                sub={
                  <>
                    {brl(soma((e) => e.beneficiario_prefeitura ? e.valor_indicado : 0))} à
                    Prefeitura · {brl(soma((e) => e.beneficiario_prefeitura ? 0 : e.valor_indicado))} a
                    outros beneficiários
                  </>
                } />
        {/* ⚠️ O `sub` DIZ O DENOMINADOR. Sem ele o percentual é irreproduzível:
            emendas não consultadas entram no «indicado» e ficam fora do
            «empenhado», e o número vira ficção. */}
        <Numero icon={Banknote} rotulo="Empenhado"
                valor={d.fonte_ligada ? brl(soma((e) => e.valor_empenhado)) : "—"}
                sub={d.fonte_ligada
                  ? `sobre as ${consultadasNoFiltro} emendas já consultadas`
                  : "execução não consultada neste ambiente"} />
        <Numero icon={Banknote} rotulo="Pago"
                valor={d.fonte_ligada
                  ? brl(soma((e) => (e.valor_pago || 0) + (e.valor_resto_pago || 0)))
                  : "—"}
                sub={d.fonte_ligada
                  ? "inclui o resto a pagar quitado"
                  : "execução não consultada neste ambiente"} />
        <Numero icon={AlertTriangle} rotulo="Precisa de cobrança" valor={acao.length}
                tom={acao.length ? "critico" : "neutro"}
                onClick={acao.length ? () => setAba("acao") : undefined}
                sub={acao.length
                  ? brl(acao.reduce((s, e) => s + (e.valor_empenhado || 0), 0))
                  : "nada empenhado e parado"} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {!!d.anos.length && (
          <select
            className="bi-input h-7 rounded px-2 text-[12px]"
            value={anos[0] || ""}
            onChange={(ev) => setAnos(ev.target.value ? [ev.target.value] : [])}
            aria-label="Ano"
          >
            <option value="">Todos os anos</option>
            {d.anos.map((a) => <option key={a} value={String(a)}>{a}</option>)}
          </select>
        )}
        {!!d.por_autor.length && (
          <select
            className="bi-input h-7 rounded px-2 text-[12px]"
            value={autorSel}
            onChange={(ev) => setAutorSel(ev.target.value)}
            aria-label="Parlamentar"
          >
            <option value="">Todos os autores</option>
            {d.por_autor.map((a) => (
              <option key={a.autor} value={a.autor}>{a.autor}</option>
            ))}
          </select>
        )}
        {d.escopo.cnpjs.some((b) => !b.prefeitura) && (
          <select
            className="bi-input h-7 rounded px-2 text-[12px]"
            value={benefSel}
            onChange={(ev) => setBenefSel(ev.target.value)}
            aria-label="Beneficiário"
          >
            <option value="">Prefeitura e entidades</option>
            <option value="prefeitura">Só a Prefeitura</option>
            <option value="entidades">Só entidades do município</option>
          </select>
        )}
      </div>

      <Abas
        valor={aba}
        onChange={setAba}
        opcoes={[
          { valor: "acao", label: `Precisa de cobrança (${acao.length})` },
          { valor: "autor", label: `Por parlamentar (${autoresFiltrados.length})` },
          { valor: "todas", label: `Todas as emendas (${filtradas.length})` },
        ]}
      />

      {aba === "acao" && (
        secoes.map(([titulo, sub, lista]) => (
          <Bloco key={titulo} className="p-3">
            <BlocoHead icon={AlertTriangle} titulo={titulo} sub={sub}
                       right={<span className="bi-num text-[12px]">
                         {brl(lista.reduce((s, e) => s + (e.valor_empenhado || 0), 0))}
                       </span>} />
            {lista.length ? (
              <Lista>
                {lista.map((e) => (
                  <LinhaEmenda key={`${e.codigo_emenda}-${e.beneficiario_cnpj}`}
                               e={e} municipioId={municipioId} />
                ))}
              </Lista>
            ) : (
              /* ⚠️ Vazio aqui é BOA notícia — e diz por quê, em vez de um
                 "nenhum registro" que soaria como falha de coleta. */
              <Vazio>
                {d.fonte_ligada
                  ? "Nenhuma emenda empenhada e parada no filtro atual."
                  : "A execução não foi consultada neste ambiente, então não há como dizer o que está parado."}
              </Vazio>
            )}
          </Bloco>
        ))
      )}

      {aba === "autor" && (
        <>
          <Bloco className="p-3">
            <BlocoHead icon={Users} titulo="Quem destinou recurso ao município"
                       sub="parlamentares, do maior valor indicado para o menor" />
            <Lista>
              {autoresFiltrados.filter((a) => !a.colegiado).map((a) => (
                <ItemLinha
                  key={a.autor}
                  titulo={a.autor}
                  valor={<span className="bi-num">{brl(a.indicado)}</span>}
                  meta={
                    <span className="flex flex-wrap items-center gap-x-3">
                      <span>{a.emendas} emenda(s)</span>
                      {!!a.anos.length && (
                        <span>{a.anos[a.anos.length - 1]}–{a.anos[0]}</span>
                      )}
                      {!!a.parado_n && (
                        <Selo tom="critico">{a.parado_n} sem pagamento</Selo>
                      )}
                    </span>
                  }
                >
                  <Campos
                    cols={3}
                    campos={[
                      { rotulo: "Indicado", valor: brl(a.indicado) },
                      { rotulo: "Empenhado",
                        valor: d.fonte_ligada ? brl(a.empenhado) : "—" },
                      { rotulo: "Pago", valor: d.fonte_ligada ? brl(a.pago) : "—" },
                    ]}
                  />
                </ItemLinha>
              ))}
            </Lista>
          </Bloco>
          {/* ⚠️ COLEGIADO EM BLOCO PRÓPRIO. Bancada, comissão e relator-geral NÃO
              são pessoas — são 7 dos 35 nomes de autor nos municípios medidos, e
              misturá-los no ranking repetiria o defeito de «Não há» (R$ 14,9 mi)
              no topo da lista da Freitas. Quem separa é
              `services/nome_parlamentar.e_pessoa`, no servidor. */}
          {!!autoresFiltrados.filter((a) => a.colegiado).length && (
            <Bloco className="p-3">
              <BlocoHead icon={Users} titulo="Emendas de colegiado"
                         sub="bancada, comissão e relator-geral — não são de um parlamentar" />
              <Lista>
                {autoresFiltrados.filter((a) => a.colegiado).map((a) => (
                  <ItemLinha key={a.autor} titulo={a.autor}
                             valor={<span className="bi-num">{brl(a.indicado)}</span>}
                             meta={<span>{a.emendas} emenda(s)</span>} />
                ))}
              </Lista>
            </Bloco>
          )}
        </>
      )}

      {aba === "todas" && (
        <Bloco className="p-3">
          <BlocoHead icon={Landmark} titulo="Todas as emendas"
                     sub={`${filtradas.length} no filtro`}
                     right={<span className="bi-num text-[12px]">
                       {brl(soma((e) => e.valor_indicado))}
                     </span>} />
          {filtradas.length ? (
            <Lista>
              {filtradas.map((e) => (
                <LinhaEmenda key={`${e.codigo_emenda}-${e.beneficiario_cnpj}`}
                             e={e} municipioId={municipioId} />
              ))}
            </Lista>
          ) : (
            <Vazio>Nenhuma emenda no filtro atual.</Vazio>
          )}
        </Bloco>
      )}
    </div>
  );
}
