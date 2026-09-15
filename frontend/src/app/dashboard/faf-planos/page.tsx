"use client";

/* PLANOS DE AÇÃO (FUNDO A FUNDO) — o que justifica o repasse, de onde ele vem,
 * e o que aconteceu com o dinheiro.
 *
 * ⭐ O QUE ESTA TELA MOSTRA QUE «FUNDO NACIONAL DE SAÚDE» NÃO MOSTRA. Aquela
 * conta o repasse consolidado por bloco: o dinheiro que ENTRA. Esta conta o
 * plano de ação que o justifica — diagnóstico, objetivos, vigência — e,
 * sobretudo, a DECOMPOSIÇÃO do valor entre emenda parlamentar, repasse
 * específico, voluntário, recursos próprios e rendimentos. Só por aqui o gestor
 * sabe quanto daquele repasse veio de emenda.
 *
 * ⭐ E, DESDE 15/09/2026, O DINHEIRO NA CONTA. A coleta passou a trazer a API
 * oficial inteira: metas e ações, parecer do ministério, histórico, termo de
 * adesão, o relatório de gestão com o % de execução física por ação, e a CONTA
 * de cada plano — saldo informado pelo banco, extrato e QUEM RECEBEU. Tudo isso
 * só aparecia no Transferegov para quem entrasse logado como o ente.
 *
 * ⚠️ A MESMA CONTA SERVE A VÁRIOS PLANOS (Goiânia: cinco planos na 1126-8216).
 * Os cartões somam POR CONTA — somar o saldo de cada plano dobraria o dinheiro.
 * A linha do plano diz quando a conta é dividida.
 *
 * ⚠️ E NÃO É SÓ SAÚDE, apesar do nome. Os quatro planos de Nova Palma são do
 * MINISTÉRIO DA CULTURA, Lei Aldir Blanc. No tenant trust os órgãos mais
 * frequentes são MinC, SENASP (segurança), SPPE (trabalho), MCID (cidades) e
 * FNDE (educação). O SUS não está nesta fonte.
 *
 * ⚠️ O QUE ESTÁ AQUI É DO MUNICÍPIO, E ISSO CUSTOU UM CONSERTO. O filtro da
 * fonte entrega todo ente SEDIADO na cidade, e a sede do governo estadual é a
 * capital: R$ 470 mi do Estado de Goiás estavam creditados a Goiânia, cujo
 * município tem R$ 73 mi. O coletor descarta ente estadual — nos planos e nos
 * beneficiários de programa (`ingestion/faf_planos.py`).
 *
 * ⚠️ E QUANDO NÃO HÁ DADO, A TELA NÃO CONCLUI "o município não tem plano". A
 * coleta é nossa e diária: a ausência pode ser nossa.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  Banknote, Building2, CalendarRange, ExternalLink, Eye, FileCheck2, FileText,
  HandCoins, History, Landmark, Loader2, MessageSquareText, PiggyBank, Receipt,
  Target, Undo2, Users, Wallet,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Abas, Bloco, BlocoHead, Campos, Grade, GradeCel, GradeLinha, ItemLinha, Lista,
  Modal, ModalCorpo, ModalHead, Numero, Secao, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";
import { textoDe } from "@/lib/texto";
import { TituloTela } from "@/components/TituloTela";

interface Relatorio {
  id: number | string | null;
  data: string | null;
  tipo: string | null;
  situacao: string | null;
  valor_executado: number | null;
  valor_pendente: number | null;
  resultados: string | null;
}

/* ⭐ O RESUMO DA ÁRVORE (15/09/2026) — o que o coletor calculou do plano
   (`ingestion/faf_planos.resumo_do_plano`). O saldo é o das contas QUE O PLANO
   USA; conta dividida aparece inteira em cada plano que a usa. */
interface Resumo {
  n_metas?: number;
  n_acoes?: number;
  meta_principal?: string | null;
  situacao_atual?: string | null;
  data_situacao?: string | null;
  enviado_em?: string | null;
  ultima_analise?: { tipo: string | null; resultado: string | null; data: string | null } | null;
  termo?: { situacao: string | null; assinado_em: string | null } | null;
  relatorio?: {
    tipo: string | null; situacao: string | null; data: string | null;
    valor_executado: number | null; valor_pendente: number | null;
    pct_fisico_medio: number | null;
  } | null;
  n_relatorios?: number;
  empenhado?: number;
  n_contas?: number;
  n_contas_abertas?: number;
  saldo_em_conta?: number | null;
  recebido_ob?: number;
  pago_a_beneficiarios?: number;
  devolvido_uniao?: number;
}

interface Plano {
  id_plano_acao: string;
  codigo: string | null;
  id_programa: string | null;
  situacao: string | null;
  inicio_vigencia: string | null;
  fim_vigencia: string | null;
  diagnostico: string | null;
  objetivos: string | null;
  valor_total: number | null;
  valor_emenda: number | null;
  valor_especifico: number | null;
  valor_voluntario: number | null;
  valor_proprios: number | null;
  valor_rendimentos: number | null;
  valor_custeio: number | null;
  valor_investimento: number | null;
  valor_saldo: number | null;
  orgao: string | null;
  sigla_orgao: string | null;
  fundo: string | null;
  ente_recebedor: string | null;
  cnpj_recebedor: string | null;
  tipo_unidade: string | null;
  relatorios: Relatorio[];
  url_fonte: string;
  /* `resumo` nulo + `detalhe_coletado` falso = a árvore ainda não foi colhida.
     Nunca "zero". */
  resumo?: Resumo | null;
  detalhe_coletado?: boolean;
  contas?: Array<{ id_agencia_conta: string; n_planos: number }>;
}

interface Origem { chave: string; rotulo: string; valor: number }
interface PorOrgao { sigla: string; orgao: string | null; planos: number; valor: number }

interface Beneficiario {
  id_programa: number | null;
  programa: string | null;
  ano: number | null;
  sigla_orgao: string | null;
  orgao: string | null;
  situacao_programa: string | null;
  beneficiario: string | null;
  cnpj_beneficiario: string | null;
  tipo: string | null;
  valor: number | null;
  numero_emenda: string | null;
  parlamentar: string | null;
  janela_ini: string | null;
  janela_fim: string | null;
  /** Ainda dá tempo de enviar o plano (a janela do programa para este tipo). */
  janela_aberta: boolean;
  /** O município já tem plano de ação coletado neste programa. */
  tem_plano: boolean;
}

interface Resp {
  tem_dados: boolean;
  motivo?: string;
  itens?: Plano[];
  total?: number;
  valor_total?: number;
  valor_saldo?: number;
  valor_custeio?: number;
  valor_investimento?: number;
  por_origem?: Origem[];
  por_orgao?: PorOrgao[];
  com_relatorio?: number;
  municipio?: { id: number; nome: string; uf: string };
  execucao?: {
    medidos: number;
    n_contas: number;
    contas_com_saldo: number;
    contas_divididas: number;
    saldo_em_conta: number;
    recebido_ob: number;
    pago_a_beneficiarios: number;
    pagamentos_a_beneficiarios: number;
    devolvido_uniao: number;
  };
  beneficiarios?: Beneficiario[];
}

/* O detalhe vem com as CHAVES DA FONTE (snake_case), exatamente como a API as
   manda — tudo opcional, e texto passa por `textoDe`: é dado de portal federal,
   e campo que muda de tipo não pode derrubar o modal. */
type Reg = Record<string, unknown>;
interface ContaDet {
  id_agencia_conta: string;
  nome_banco: string | null;
  agencia: string | null;
  dv_agencia: string | null;
  conta: string | null;
  dv_conta: string | null;
  situacao: string | null;
  data_abertura: string | null;
  programa_agil: string | null;
  saldo_final: number | null;
  planos: string[];
  cabecalho: Reg | null;
  /** NULO = conta não aberta ("NNNN-0"): não há extrato. */
  lancamentos: Array<Reg & { subtransacoes?: Reg[] }> | null;
  resumo: Reg | null;
  n_lancamentos: number | null;
  ultimo_lancamento: string | null;
}
interface DetalheResp {
  plano: Reg | null;
  detalhe: {
    metas?: Array<Reg & { acoes?: Reg[] }>;
    destinacao?: Reg[];
    historico?: Reg[];
    analises?: Array<Reg & { responsaveis?: Reg[] }>;
    termos_adesao?: Array<Reg & { historico?: Reg[] }>;
    empenhos?: Reg[];
    relatorios?: Array<Reg & { acoes?: Reg[]; analises?: Array<Reg & { responsaveis?: Reg[] }> }>;
    contas?: Reg[];
    _resumo?: Resumo | null;
  } | null;
  contas: ContaDet[];
  programa: (Reg & { gestao_agil?: Reg[] }) | null;
  detalhe_atualizado_em: string | null;
  fonte_atualizada_em: string | null;
  url_fonte: string;
}

type AbaDet = "plano" | "tempo" | "conta" | "prestacao" | "analise" | "programa";

const brl = (v: number | null | undefined) =>
  v == null
    ? "—" /* ⚠️ Não "R$ 0,00": plano sem valor declarado não é de graça. */
    : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const dataBR = (s: string | null | undefined) => (s ? s.slice(0, 10).split("-").reverse().join("/") : null);

const t = (v: unknown): string => textoDe(v) || "-";
const n = (v: unknown): number | null => (typeof v === "number" ? v : null);
/** '2026-05-26T00:00:00' -> '26/05/2026'. */
const dia = (v: unknown): string => {
  const s = textoDe(v);
  const m = s ? /^(\d{4})-(\d{2})-(\d{2})/.exec(s) : null;
  return m ? `${m[3]}/${m[2]}/${m[1]}` : s || "-";
};

/* A fonte manda `ADITIVACAO_ENVIADA_PARA_ANALISE`. Numa tela lida por gestor,
   caixa-alta com underscore é ruído de banco vazando para a interface. */
const humano = (s: unknown) => {
  const v = textoDe(s);
  return v ? v.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()) : null;
};

/* `situacaoTom` é compartilhada por ~15 telas e não conhece o vocabulário desta
   fonte: «AUTORIZADO» é o estado BOM aqui (172 de 204 planos no trust) e cairia
   em cinza. O ajuste fica local de propósito — mexer na função compartilhada
   por causa de uma palavra mudaria a cor das outras catorze. */
const tomDoPlano = (s: string | null | undefined) =>
  /autorizad|aprovad|assinad/i.test(s || "") ? ("ok" as const) : situacaoTom(s || null);

// Grades do detalhe. ⚠️ Classe LITERAL: montada por template o Tailwind não vê.
const COLS_ACAO = "grid-cols-[4.5rem_minmax(10rem,1fr)_8rem]";
const COLS_DEST = "grid-cols-[6rem_minmax(9rem,1fr)_7rem_8rem]";
const COLS_HIST = "grid-cols-[6rem_minmax(10rem,1fr)_4.5rem]";
const COLS_EXT = "grid-cols-[6rem_3rem_minmax(9rem,1fr)_minmax(10rem,1.2fr)_9rem_8rem]";
const COLS_SUB = "grid-cols-[6rem_minmax(10rem,1.3fr)_8rem_minmax(8rem,1fr)_6rem_8rem]";
const COLS_RACAO = "grid-cols-[4.5rem_minmax(10rem,1fr)_5rem_minmax(8rem,1fr)]";
const COLS_EMP = "grid-cols-[7.5rem_6rem_minmax(8rem,1fr)_minmax(7rem,1fr)_8rem]";

/* O título de um plano é o que ele se propõe a fazer. A fonte não tem campo de
   objeto curto — `objetivos_plano_acao` é texto corrido, às vezes um parágrafo —
   e o código (`30882120200002-001617`) não diz nada a quem lê. Então o objetivo
   truncado vira o título, e o texto inteiro continua no corpo, ao lado do
   diagnóstico. Sem objetivo, o código é melhor que "Plano 1617". */
function tituloDoPlano(p: Plano): string {
  const tx = (p.objetivos || "").trim().replace(/\s+/g, " ");
  if (!tx) return p.codigo || `Plano ${p.id_plano_acao}`;
  return tx.length > 110 ? `${tx.slice(0, 110).trimEnd()}…` : tx;
}

export default function FafPlanosPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ A RESPOSTA GUARDA DE QUAL MUNICÍPIO ELA É, e `carregando` é DERIVADO
     disso — mesmo desenho de `parcerias/page.tsx` e pela mesma razão: ao trocar
     de município, um `d` que sobrou do anterior apareceria por um quadro sob o
     cabeçalho do novo, mostrando o plano de uma cidade no nome de outra. */
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null }>(
    { mun: "", d: null, erro: null });
  const [orgao, setOrgao] = useState<string>("");
  // O plano com o detalhe completo aberto (modal). Guarda o id, não o índice.
  const [detId, setDetId] = useState<string | null>(null);

  const daVez = res.mun === municipioId;
  const carregando = !!municipioId && !daVez;
  const d = daVez ? res.d : null;
  const erro = daVez ? res.erro : null;

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<Resp>("/faf-planos", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setRes({ mun: municipioId, d: r.data, erro: null }); })
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
    return orgao
      ? todos.filter((p) => (p.sigla_orgao || p.orgao || "—") === orgao)
      : todos;
  }, [d, orgao]);

  if (!municipioId) {
    return <Vazio>Selecione um município.</Vazio>;
  }
  if (carregando) {
    return (
      <div className="flex items-center gap-2 py-6 text-sm"
           style={{ color: "var(--bi-muted)" }}>
        <Loader2 className="size-4 animate-spin" /> Carregando planos de ação…
      </div>
    );
  }
  if (erro) return <Vazio>{erro}</Vazio>;
  if (!d?.tem_dados) {
    return (
      <Vazio>{d?.motivo || "Sem planos de ação coletados para este município."}</Vazio>
    );
  }

  const origens = d.por_origem || [];
  const orgaos = d.por_orgao || [];
  const maiorOrigem = Math.max(...origens.map((o) => o.valor), 1);
  const ex = d.execucao;
  const benefs = d.beneficiarios || [];

  return (
    <div className="flex flex-col gap-4">
      {/* ⭐ CABEÇALHO SOLTO — ver a nota gêmea em `parcerias/page.tsx`. Os
          `Numero` já são `bi-card`; dentro de um `Bloco` viravam cartão dentro
          de cartão, encostados na borda do de fora. */}
      <header>
        <TituloTela>Planos de Ação (Fundo a Fundo)</TituloTela>
        <p className="mt-1 max-w-3xl text-[12px] leading-snug"
           style={{ color: "var(--bi-muted)" }}>
          O plano que justifica cada repasse fundo a fundo — diagnóstico,
          objetivos, metas — a <b>decomposição do valor</b> (quanto veio de
          emenda, de repasse específico, de recursos próprios) e, na conta de cada
          plano, <b>o que aconteceu com o dinheiro</b>: saldo, extrato e quem
          recebeu. Apesar do nome, não é saúde: cultura, segurança, trabalho e
          educação repassam por aqui.
        </p>
      </header>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Numero icon={Landmark} rotulo="Planos" valor={String(d.total ?? 0)} />
        <Numero icon={Wallet} rotulo="Valor total" valor={brl(d.valor_total)} />
        <Numero icon={PiggyBank} rotulo="Saldo disponível no plano"
                valor={brl(d.valor_saldo)} sub="o que o plano declara ainda não usado" />
        {/* ⭐ Prestação de contas é o buraco que esta fonte preenche: a tabela
            `prestacao_contas` é dropada a cada boot, e até aqui ela só existia
            como texto dentro de um campo de situação. */}
        <Numero icon={FileCheck2} rotulo="Com prestação de contas"
                valor={`${d.com_relatorio ?? 0} de ${d.total ?? 0}`} />
      </div>

      {/* ⭐ O QUE ACONTECEU COM O DINHEIRO (15/09/2026), somado POR CONTA. O
          saldo é o que o banco informa (o extrato sozinho dá zero: o dinheiro fica
          na aplicação automática). `medidos` diz quanto da carteira a coleta já
          percorreu — R$ 0 pago numa carteira não medida não é "nada foi pago". */}
      {ex && ex.n_contas > 0 && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Numero
            icon={Wallet}
            rotulo="Saldo em conta"
            valor={ex.contas_com_saldo ? brl(ex.saldo_em_conta) : "—"}
            sub={`${ex.n_contas} conta(s), informado pelo banco${
              ex.contas_divididas ? ` · ${ex.contas_divididas} dividida(s) entre planos` : ""}`}
          />
          <Numero
            icon={Banknote}
            rotulo="Recebido da União (OB)"
            valor={brl(ex.recebido_ob)}
            sub={`${ex.medidos} de ${d.total ?? 0} plano(s) medido(s)`}
          />
          <Numero
            icon={Users}
            rotulo="Pago a beneficiários"
            valor={brl(ex.pago_a_beneficiarios)}
            sub={ex.pagamentos_a_beneficiarios
              ? `${ex.pagamentos_a_beneficiarios} beneficiário(s) identificado(s) no extrato`
              : "nenhum pagamento identificado no extrato"}
            tom={ex.pago_a_beneficiarios > 0 ? "ok" : "neutro"}
          />
          <Numero
            icon={Undo2}
            rotulo="Devolvido à União"
            valor={brl(ex.devolvido_uniao)}
            sub="GRU para o Tesouro, pelo extrato"
            tom={ex.devolvido_uniao > 0 ? "atencao" : "neutro"}
          />
        </div>
      )}

      {/* ⭐ A DECOMPOSIÇÃO É O PRODUTO DESTA TELA. O ConsultaFNS diz quanto
          entrou; só aqui se sabe quanto daquilo veio de emenda parlamentar. */}
      {origens.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={PiggyBank}
            titulo="De onde vem o dinheiro"
            sub="a origem que o repasse consolidado não separa"
          />
          <div className="space-y-2.5">
            {origens.map((o) => (
              <div key={o.chave}>
                <div className="flex items-baseline justify-between gap-3 text-[12px]">
                  <span>{o.rotulo}</span>
                  <span className="bi-num shrink-0">{brl(o.valor)}</span>
                </div>
                {/* A barra é comparação entre origens, não percentual do total:
                    rendimento de aplicação ao lado de repasse específico ficaria
                    invisível numa escala absoluta. */}
                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full"
                     style={{ background: "var(--bi-line)" }}>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.max(2, (o.valor / maiorOrigem) * 100)}%`,
                      background: o.chave === "emenda"
                        ? "var(--bi-accent-ink)" : "var(--bi-muted)",
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2 text-[11px]"
               style={{ color: "var(--bi-muted)" }}>
            <span>Custeio {brl(d.valor_custeio)}</span>
            <span>·</span>
            <span>Investimento {brl(d.valor_investimento)}</span>
          </div>
        </Bloco>
      )}

      {/* ⭐ PROGRAMAS QUE DESTINAM RECURSO AO MUNICÍPIO — a pergunta nova: "tem
          dinheiro reservado para nós que ainda não pedimos?". A fonte lista o
          beneficiário antes do plano existir; o que ainda não tem plano, com a
          janela aberta, é o que pede ação da prefeitura. */}
      {benefs.length > 0 && (() => {
        const semPlano = benefs.filter((b) => !b.tem_plano);
        const abertos = semPlano.filter((b) => b.janela_aberta);
        return (
          <Bloco className="p-3">
            <BlocoHead
              icon={HandCoins}
              titulo="Programas que destinam recurso ao município"
              sub={`${benefs.length} destinação(ões) · ${semPlano.length} sem plano de ação coletado`
                + (abertos.length ? ` · ${abertos.length} com prazo aberto para enviar` : "")}
            />
            <Lista>
              {[...abertos, ...semPlano.filter((b) => !b.janela_aberta),
                ...benefs.filter((b) => b.tem_plano)].map((b, i) => (
                <ItemLinha
                  key={`${b.id_programa}-${i}`}
                  titulo={b.programa || `Programa ${b.id_programa ?? "-"}`}
                  valor={<span className="bi-num">{brl(b.valor)}</span>}
                  meta={
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Selo tom={b.tem_plano ? "ok" : "atencao"}>
                        {b.tem_plano ? "com plano de ação" : "sem plano de ação"}
                      </Selo>
                      {!b.tem_plano && b.janela_aberta && (
                        <Selo tom="acento" title={`Janela do programa: ${dataBR(b.janela_ini)} a ${dataBR(b.janela_fim)}`}>
                          enviar até {dataBR(b.janela_fim)}
                        </Selo>
                      )}
                      {b.sigla_orgao && <Selo tom="neutro" title={b.orgao || undefined}>{b.sigla_orgao}</Selo>}
                      {b.ano && <span>{b.ano}</span>}
                      {b.tipo && <span>{humano(b.tipo)}</span>}
                      {b.parlamentar && <span>{b.parlamentar}{b.numero_emenda ? ` · emenda ${b.numero_emenda}` : ""}</span>}
                    </span>
                  }
                />
              ))}
            </Lista>
          </Bloco>
        );
      })()}

      {/* ⚠️ Este bloco é o que desfaz o mal-entendido do nome: «fundo a fundo»
          soa SUS, mas em Nova Palma são quatro planos do Ministério da Cultura.
          Clicar filtra a lista abaixo. */}
      {orgaos.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Building2}
            titulo="Por órgão repassador"
            sub={orgao
              ? `filtrando por ${orgao} — clique de novo para ver todos`
              : "não é saúde: clique num órgão para filtrar"}
          />
          <Lista>
            {orgaos.map((o) => (
              <ItemLinha
                key={o.sigla}
                titulo={orgao === o.sigla ? `${o.sigla} · filtrando` : o.sigla}
                meta={o.orgao || undefined}
                valor={<span className="bi-num">{brl(o.valor)}</span>}
                onClick={() => setOrgao(orgao === o.sigla ? "" : o.sigla)}
              />
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead
          icon={Landmark}
          titulo={orgao ? `Planos · ${orgao}` : "Planos de ação"}
          sub={`${itens.length} de ${d.total}`}
        />
        <Lista>
          {itens.map((p) => (
            <LinhaPlano key={p.id_plano_acao} p={p} onDetalhe={() => setDetId(p.id_plano_acao)} />
          ))}
        </Lista>
        {itens.length === 0 && <Vazio>Nenhum plano deste órgão.</Vazio>}
      </Bloco>

      {detId !== null && <DetalhePlano id={detId} onFechar={() => setDetId(null)} />}
    </div>
  );
}

/** Um plano na lista — FECHADO por padrão.
 *
 *  ⚠️ ERA ESTA A TELA MAIS MACHUCADA DAS DUAS. Cada plano abria com onze campos
 *  em ONZE COLUNAS (`Campos` sem `cols` abre uma coluna por campo) e, logo
 *  abaixo, o `diagnostico` e os `objetivos` INTEIROS — que na Lei Aldir Blanc
 *  são dois parágrafos de texto legal transcritos por extenso.
 *
 *  Fechado, o item é título + selos + valor. Aberto, ele entrega o essencial e o
 *  botão do detalhe completo (metas, histórico, conta e extrato, prestação). */
function LinhaPlano({ p, onDetalhe }: { p: Plano; onDetalhe: () => void }) {
  const [aberto, setAberto] = useState(false);
  const r = p.resumo;
  const dividida = (p.contas || []).find((c) => c.n_planos > 1);
  return (
    <ItemLinha
      titulo={tituloDoPlano(p)}
      valor={<span className="bi-num">{brl(p.valor_total)}</span>}
      onClick={() => setAberto((v) => !v)}
      expandido={aberto}
      meta={
        <span className="flex flex-wrap items-center gap-1.5">
          <Selo tom={tomDoPlano(p.situacao)}>{humano(p.situacao) || "—"}</Selo>
          {p.sigla_orgao && (
            <Selo tom="neutro" title={p.orgao || undefined}>{p.sigla_orgao}</Selo>
          )}
          {/* ⭐ DA ÁRVORE DO PLANO: quanto está na conta e quanto já foi pago a
              beneficiários identificados. Selo só quando há o que dizer. */}
          {r?.saldo_em_conta != null && r.saldo_em_conta > 0 && (
            <Selo tom="neutro" title="Saldo que o banco informa para a(s) conta(s) do plano">
              Saldo {brl(r.saldo_em_conta)}
            </Selo>
          )}
          {!!r?.pago_a_beneficiarios && (
            <Selo tom="ok" title="Pagamentos a beneficiários identificados no extrato da conta">
              Pago {brl(r.pago_a_beneficiarios)}
            </Selo>
          )}
          {/* ⚠️ A conta dividida é a razão de o saldo do plano não somar com o
              dos outros: a mesma conta aparece inteira em cada plano. */}
          {dividida && (
            <Selo tom="atencao" title={`A conta ${dividida.id_agencia_conta} serve a ${dividida.n_planos} planos: o saldo e o extrato são da conta inteira`}>
              conta dividida com {dividida.n_planos - 1} plano(s)
            </Selo>
          )}
          {r?.relatorio ? (
            <Selo tom={tomDoPlano(r.relatorio.situacao)} title={`Relatório ${humano(r.relatorio.tipo) || ""} de ${dataBR(r.relatorio.data) || "-"}`}>
              <FileCheck2 className="mr-1 inline size-3" />
              relatório {humano(r.relatorio.situacao)?.toLowerCase()}
            </Selo>
          ) : p.relatorios.length > 0 && (
            <Selo tom="ok">
              <FileCheck2 className="mr-1 inline size-3" />
              {p.relatorios.length} relatório{p.relatorios.length > 1 ? "s" : ""}
            </Selo>
          )}
          {(p.inicio_vigencia || p.fim_vigencia) && (
            <span>
              {dataBR(p.inicio_vigencia) || "?"} a {dataBR(p.fim_vigencia) || "?"}
            </span>
          )}
        </span>
      }
    >
      {aberto && (
        <div className="mt-2 flex flex-col gap-2">
          <Campos
            cols={4}
            campos={[
              { rotulo: "Meta principal", valor: r?.meta_principal ?? null, span: 2 },
              { rotulo: "Situação atual", valor: r?.situacao_atual
                  ? `${humano(r.situacao_atual)}${r.data_situacao ? ` em ${dataBR(r.data_situacao)}` : ""}` : null },
              { rotulo: "Enviado em", valor: dataBR(r?.enviado_em) },
              { rotulo: "Emenda parlamentar", valor: brl(p.valor_emenda) },
              { rotulo: "Repasse específico", valor: brl(p.valor_especifico) },
              { rotulo: "Repasse voluntário", valor: brl(p.valor_voluntario) },
              { rotulo: "Recursos próprios", valor: brl(p.valor_proprios) },
              { rotulo: "Rendimentos", valor: brl(p.valor_rendimentos) },
              { rotulo: "Custeio", valor: brl(p.valor_custeio) },
              { rotulo: "Investimento", valor: brl(p.valor_investimento) },
              { rotulo: "Saldo disponível", valor: brl(p.valor_saldo) },
              { rotulo: "Fundo repassador", valor: p.fundo },
              { rotulo: "Recebedor", valor: p.ente_recebedor },
              { rotulo: "Código do plano", valor: p.codigo, mono: true },
            ].filter((c) => c.valor && c.valor !== "—" && c.valor !== "R$ 0,00")}
          />
          {!p.detalhe_coletado && (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              O detalhe deste plano (metas, conta, extrato) ainda não foi colhido. A coleta
              passa por todos os planos toda noite.
            </p>
          )}
          <div className="flex flex-wrap items-center gap-3">
            {/* O detalhe completo: metas, histórico, parecer, conta e extrato,
                prestação de contas — tudo do banco, colhido pela coleta noturna. */}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDetalhe(); }}
              className="inline-flex w-fit items-center gap-1 rounded px-2 py-1 text-[11px] font-medium"
              style={{ background: "var(--bi-surface-2)", color: "var(--bi-text)" }}
            >
              <Eye className="size-3" /> ver detalhe completo
            </button>
            {/* O link deixa qualquer número desta tela conferível na fonte — a
                mesma disciplina do `url_fonte` das Obras e das Parcerias. */}
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

/** Quem analisou — os nomes dos responsáveis, numa linha. */
const nomes = (rs: Reg[] | undefined, campo: string) =>
  (rs || []).map((x) => textoDe(x[campo])).filter(Boolean).join(", ");

/** O DETALHE COMPLETO de um plano — do banco, sem requisição à fonte.
 *
 *  ⭐ É o que a coleta passou a trazer em 15/09/2026 da API oficial inteira. As
 *  abas seguem o ciclo do plano: o que foi PROPOSTO (plano, metas), o CAMINHO
 *  (histórico, termo de adesão), ONDE O DINHEIRO ESTÁ (conta, extrato, quem
 *  recebeu), o que foi PRESTADO (relatório com % físico), o que o ministério
 *  DISSE (pareceres) e o PROGRAMA. */
function DetalhePlano({ id, onFechar }: { id: string; onFechar: () => void }) {
  const [res, setRes] = useState<{ id: string; d: DetalheResp | null; erro: string | null } | null>(null);
  const [aba, setAba] = useState<AbaDet>("plano");

  useEffect(() => {
    let vivo = true;
    api.get<DetalheResp>(`/faf-planos/plano/${id}`)
      .then((r) => { if (vivo) setRes({ id, d: r.data, erro: null }); })
      .catch((e) => {
        if (vivo) setRes({ id, d: null, erro: e?.response?.data?.detail || "Não foi possível carregar." });
      });
    return () => { vivo = false; };
  }, [id]);

  const carregando = !res || res.id !== id;
  const d = !carregando ? res!.d : null;
  const pl = d?.plano || {};
  const arv = d?.detalhe || null;
  const prog = d?.programa || null;
  const naoColhida = (
    <Vazio>
      O detalhe deste plano ainda não foi colhido. A coleta passa por todos os
      planos toda noite.
    </Vazio>
  );
  // id da ação da meta -> "A1.1 — nome", para ler o % físico do relatório.
  const acoesDaMeta = useMemo(() => {
    const m = new Map<string, string>();
    for (const meta of arv?.metas || []) {
      for (const a of meta.acoes || []) {
        m.set(String(a.id_acao_meta_plano_acao), `${t(a.numero_acao_meta_plano_acao)} — ${t(a.nome_acao_meta_plano_acao)}`);
      }
    }
    return m;
  }, [arv]);

  const titulo = textoDe(pl.objetivos_plano_acao)?.replace(/\s+/g, " ") || `Plano ${id}`;

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-5xl">
      <ModalHead
        titulo={titulo.length > 120 ? `${titulo.slice(0, 120).trimEnd()}…` : titulo}
        sub={`Plano ${id}${pl.codigo_plano_acao ? ` · ${t(pl.codigo_plano_acao)}` : ""}${
          pl.sigla_orgao_repassador_plano_acao ? ` · ${t(pl.sigla_orgao_repassador_plano_acao)}` : ""}`}
        onFechar={onFechar}
        abaixo={
          <Abas
            valor={aba}
            onChange={(v) => setAba(v)}
            opcoes={[
              { valor: "plano" as const, label: "Plano e Metas" },
              { valor: "tempo" as const, label: "Linha do tempo" },
              { valor: "conta" as const, label: "Conta e Extrato" },
              { valor: "prestacao" as const, label: "Prestação de contas" },
              { valor: "analise" as const, label: "Pareceres" },
              { valor: "programa" as const, label: "Programa e Empenhos" },
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
            Fonte: API oficial do TransfereGov (Fundo a Fundo)
            {d.fonte_atualizada_em && <> · fonte atualizada em {dia(d.fonte_atualizada_em)}</>}
            {d.detalhe_atualizado_em && <> · detalhe colhido em {dia(d.detalhe_atualizado_em)}</>}
            {" · "}
            <a href={d.url_fonte} target="_blank" rel="noreferrer" className="underline">ver na fonte</a>
          </div>

          <div key={aba} className="bi-pane-enter flex flex-col gap-3">
          {aba === "plano" && (
            <>
              <Secao
                icon={FileText}
                titulo="Plano de ação"
                campos={[
                  { rotulo: "Situação", valor: humano(pl.situacao_plano_acao) || "-", tom: tomDoPlano(textoDe(pl.situacao_plano_acao)) },
                  { rotulo: "Valor total", valor: brl(n(pl.valor_total_plano_acao)) },
                  { rotulo: "Vigência", valor: `${dia(pl.data_inicio_vigencia_plano_acao)} a ${dia(pl.data_fim_vigencia_plano_acao)}` },
                  { rotulo: "Saldo disponível", valor: brl(n(pl.valor_saldo_disponivel_plano_acao)) },
                  { rotulo: "Órgão repassador", valor: t(pl.nome_orgao_repassador_plano_acao), span: 2 },
                  { rotulo: "Fundo repassador", valor: t(pl.nome_fundo_repassador_plano_acao), span: 2 },
                  { rotulo: "Recebedor", valor: t(pl.nome_ente_recebedor_plano_acao), span: 2 },
                  { rotulo: "Fundo vinculado", valor: t(pl.nome_fundo_vinculado_plano_acao), span: 2 },
                  { rotulo: "Custeio", valor: brl(n(pl.valor_total_custeio_plano_acao)) },
                  { rotulo: "Investimento", valor: brl(n(pl.valor_total_investimento_plano_acao)) },
                  { rotulo: "Emenda parlamentar", valor: brl(n(pl.valor_repasse_emenda_plano_acao)) },
                  { rotulo: "Recursos próprios", valor: brl(n(pl.valor_recursos_proprios_plano_acao)) },
                ]}
              >
                {([
                  ["Diagnóstico", pl.diagnostico_plano_acao],
                  ["Objetivos", pl.objetivos_plano_acao],
                ] as const).map(([rot, txt]) => (
                  <div key={rot} className="mt-2.5">
                    <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>{rot}</div>
                    <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>{t(txt)}</p>
                  </div>
                ))}
              </Secao>
              {!arv ? naoColhida : (
                <>
                  {!(arv.metas || []).length && <Vazio>O plano não declarou metas.</Vazio>}
                  {(arv.metas || []).map((meta, i) => (
                    <Secao key={i} icon={Target}
                           titulo={`Meta ${t(meta.numero_meta_plano_acao)} — ${t(meta.nome_meta_plano_acao)}`}
                           sub={brl(n(meta.valor_meta_plano_acao))}>
                      <p className="mb-2 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-muted)" }}>
                        {t(meta.descricao_meta_plano_acao)}
                      </p>
                      {!(meta.acoes || []).length ? <Vazio>Sem ações nesta meta.</Vazio> : (
                        <Grade cols={COLS_ACAO} cabecalho={[{ label: "Ação" }, { label: "Nome" }, { label: "Valor", direita: true }]}>
                          {(meta.acoes || []).map((a, j) => (
                            <GradeLinha key={j} cols={COLS_ACAO}>
                              <GradeCel tom="id">{t(a.numero_acao_meta_plano_acao)}</GradeCel>
                              <GradeCel title={textoDe(a.descricao_acao_meta_plano_acao) || undefined}>{t(a.nome_acao_meta_plano_acao)}</GradeCel>
                              <GradeCel tom="num">{brl(n(a.valor_acao_meta_plano_acao))}</GradeCel>
                            </GradeLinha>
                          ))}
                        </Grade>
                      )}
                    </Secao>
                  ))}
                  <Secao icon={Receipt} titulo="Destinação dos recursos" sub="natureza da despesa">
                    {!(arv.destinacao || []).length ? <Vazio>Sem destinação declarada.</Vazio> : (
                      <div className="mt-2">
                        <Grade cols={COLS_DEST} cabecalho={[{ label: "Natureza" }, { label: "Descrição" }, { label: "Tipo" }, { label: "Valor", direita: true }]}>
                          {(arv.destinacao || []).map((x, i) => (
                            <GradeLinha key={i} cols={COLS_DEST}>
                              <GradeCel tom="id">{t(x.codigo_natureza_despesa_destinacao_recursos_plano_acao)}</GradeCel>
                              <GradeCel>{t(x.descricao_natureza_despesa_destinacao_recursos_plano_acao)}</GradeCel>
                              <GradeCel>{humano(x.tipo_despesa_destinacao_recursos_plano_acao) || "-"}</GradeCel>
                              <GradeCel tom="num">{brl(n(x.valor_destinacao_recursos_plano_acao))}</GradeCel>
                            </GradeLinha>
                          ))}
                        </Grade>
                      </div>
                    )}
                  </Secao>
                </>
              )}
            </>
          )}

          {aba === "tempo" && (!arv ? naoColhida : (
            <>
              <Secao icon={History} titulo="Histórico da situação" sub={`${(arv.historico || []).length} registro(s)`}>
                {!(arv.historico || []).length ? <Vazio>Sem histórico publicado.</Vazio> : (
                  <div className="mt-2">
                    <Grade cols={COLS_HIST} cabecalho={[{ label: "Data" }, { label: "Situação" }, { label: "Versão", direita: true }]}>
                      {[...(arv.historico || [])]
                        .sort((a, b) => `${a.data_historico_plano_acao}${String(a.id_historico_plano_acao).padStart(10, "0")}`
                          .localeCompare(`${b.data_historico_plano_acao}${String(b.id_historico_plano_acao).padStart(10, "0")}`))
                        .map((h, i) => (
                          <GradeLinha key={i} cols={COLS_HIST}>
                            <GradeCel tom="data">{dia(h.data_historico_plano_acao)}</GradeCel>
                            <GradeCel>{humano(h.situacao_historico_plano_acao) || "-"}</GradeCel>
                            <GradeCel tom="num">{t(h.versao_historico_plano_acao)}</GradeCel>
                          </GradeLinha>
                        ))}
                    </Grade>
                  </div>
                )}
              </Secao>
              {!(arv.termos_adesao || []).length ? (
                <Vazio>Nenhum termo de adesão publicado para este plano.</Vazio>
              ) : (arv.termos_adesao || []).map((tm, i) => (
                <Secao
                  key={i}
                  icon={FileCheck2}
                  titulo="Termo de adesão"
                  campos={[
                    { rotulo: "Situação", valor: humano(tm.situacao_termo_adesao) || "-", tom: tomDoPlano(textoDe(tm.situacao_termo_adesao)) },
                    { rotulo: "Assinado em", valor: dia(tm.data_assinatura_termo_adesao) },
                    { rotulo: "Processo", valor: t(tm.numero_processo_termo_adesao), mono: true },
                    { rotulo: "Ano", valor: t(tm.ano_termo_adesao) },
                    { rotulo: "Publicação no DOU", valor: `${dia(tm.data_publicacao_dou_termo_adesao)} · seção ${t(tm.secao_publicacao_dou_termo_adesao)}, pág. ${t(tm.pagina_publicacao_dou_termo_adesao)}`, span: 2 },
                    { rotulo: "Histórico do termo", valor: (tm.historico || []).map((h) => `${dia(h.data_historico_termo_adesao)} ${humano(h.situacao_historico_termo_adesao) || ""}`).join(" · ") || "-", span: 2, quebra: true },
                  ]}
                >
                  <details className="mt-2 text-[12px]">
                    <summary className="cursor-pointer" style={{ color: "var(--bi-muted)" }}>objeto do termo</summary>
                    <p className="mt-1 leading-relaxed break-words whitespace-pre-line" style={{ color: "var(--bi-muted)" }}>
                      {t(tm.objeto_termo_adesao)}
                    </p>
                  </details>
                </Secao>
              ))}
            </>
          ))}

          {aba === "conta" && (!d.contas.length ? (
            arv ? <Vazio>A fonte não informa conta para este plano.</Vazio> : naoColhida
          ) : d.contas.map((c, i) => {
            const r = c.resumo || {};
            const lancs = c.lancamentos;
            const subs = (lancs || []).flatMap((l) => (l.subtransacoes || []).map((s) => s));
            return (
              <React.Fragment key={i}>
                <Secao
                  icon={Wallet}
                  titulo={`Conta ${t(c.conta)}${c.dv_conta ? `-${c.dv_conta}` : ""} — ${t(c.nome_banco)}`}
                  sub={`agência ${t(c.agencia)}${c.dv_agencia ? `-${c.dv_agencia}` : ""}${c.programa_agil ? ` · ${c.programa_agil}` : ""}`}
                  campos={[
                    { rotulo: "Saldo (informado pelo banco)", valor: brl(c.saldo_final) },
                    { rotulo: "Situação da conta", valor: t(c.situacao), tom: situacaoTom(c.situacao) },
                    { rotulo: "Aberta em", valor: dia(c.data_abertura) },
                    { rotulo: "Último lançamento", valor: dia(c.ultimo_lancamento) },
                    { rotulo: "Recebido da União (OB)", valor: brl(n(r.recebido_ob)) },
                    { rotulo: "Pago a beneficiários", valor: brl(n(r.pago_a_beneficiarios)), tom: n(r.pago_a_beneficiarios) ? "ok" : "normal" },
                    { rotulo: "Devolvido à União (GRU)", valor: brl(n(r.devolvido_uniao)), tom: n(r.devolvido_uniao) ? "atencao" : "normal" },
                    { rotulo: "Estornos (OB cancelada, TED devolvida)", valor: brl(n(r.estornos)) },
                    ...(n(r.n_nao_classificado) ? [{
                      rotulo: "Lançamentos não classificados", valor: `${n(r.n_nao_classificado)} · ${brl(n(r.nao_classificado))}`,
                      tom: "atencao" as const, span: 2,
                      title: ((r.descricoes_nao_classificadas as string[] | undefined) || []).join("; "),
                    }] : []),
                  ]}
                >
                  {c.planos.length > 1 && (
                    <p className="mt-2 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                      ⚠️ Esta conta serve a {c.planos.length} planos ({c.planos.join(", ")}): o saldo e o
                      extrato são da conta inteira, não só deste plano.
                    </p>
                  )}
                </Secao>
                {lancs === null ? (
                  <Vazio>A conta deste plano ainda não foi aberta — não há extrato.</Vazio>
                ) : (
                  <>
                    {/* ⭐ QUEM RECEBEU: a ordem bancária emitida em lote detalha
                        cada beneficiário (nome, CPF mascarado pela fonte, valor,
                        categoria). Só aparecia logado como o ente. */}
                    {subs.length > 0 && (
                      <Secao icon={HandCoins} titulo="Quem recebeu (pagamentos em lote)" sub={`${subs.length} pagamento(s)`}>
                        <div className="mt-2">
                          <Grade rolagem minLargura="50rem" cols={COLS_SUB}
                                 cabecalho={[{ label: "Pago em" }, { label: "Beneficiário" }, { label: "Documento" },
                                             { label: "Categoria" }, { label: "Situação" }, { label: "Valor", direita: true }]}>
                            {subs.map((s, j) => (
                              <GradeLinha key={j} cols={COLS_SUB}
                                          alerta={!/^pago$/i.test(textoDe(s.descricao_situacao_pagamento_subtransacao_gestao_financeira) || "")}>
                                <GradeCel tom="data">{dia(s.data_pagamento_subtransacao_gestao_financeira)}</GradeCel>
                                <GradeCel>{t(s.nome_beneficiario_subtransacao_gestao_financeira)}</GradeCel>
                                <GradeCel tom="id">{t(s.doc_beneficiario_subtransacao_gestao_financeira_mask)}</GradeCel>
                                <GradeCel>{t((s.categorias_despesa_subtransacao as Reg | undefined)?.caminho_categoria_subtransacao)}</GradeCel>
                                <GradeCel>{t(s.descricao_situacao_pagamento_subtransacao_gestao_financeira)}</GradeCel>
                                <GradeCel tom="num">{brl(n(s.valor_subtransacao_gestao_financeira))}</GradeCel>
                              </GradeLinha>
                            ))}
                          </Grade>
                        </div>
                      </Secao>
                    )}
                    <Secao icon={Banknote} titulo="Extrato da conta"
                           sub={`${lancs.length} lançamento(s) · aplicação e resgate automáticos são o dinheiro mudando de gaveta`}>
                      {!lancs.length ? <Vazio>Nenhum lançamento publicado.</Vazio> : (
                        <div className="mt-2">
                          <Grade rolagem minLargura="52rem" cols={COLS_EXT}
                                 cabecalho={[{ label: "Data" }, { label: "C/D" }, { label: "Descrição" },
                                             { label: "Favorecido" }, { label: "Documento" }, { label: "Valor", direita: true }]}>
                            {[...lancs]
                              .sort((a, b) => `${b.data_lancamento_gestao_financeira}${String(b.numero_ordem_gestao_financeira ?? "").padStart(4, "0")}`
                                .localeCompare(`${a.data_lancamento_gestao_financeira}${String(a.numero_ordem_gestao_financeira ?? "").padStart(4, "0")}`))
                              .map((l, j) => (
                                <GradeLinha key={j} cols={COLS_EXT}>
                                  <GradeCel tom="data">{dia(l.data_lancamento_gestao_financeira)}</GradeCel>
                                  <GradeCel>{t(l.tipo_operacao_gestao_financeira)}</GradeCel>
                                  <GradeCel title={(l.subtransacoes || []).length ? `${(l.subtransacoes || []).length} beneficiário(s) — ver "Quem recebeu"` : undefined}>
                                    {t(l.descricao_gestao_financeira)}
                                  </GradeCel>
                                  <GradeCel>{t(l.nome_favorecido_gestao_financeira)}</GradeCel>
                                  <GradeCel tom="id">{t(l.doc_favorecido_gestao_financeira_mask)}</GradeCel>
                                  <GradeCel tom="num">{brl(n(l.valor_lancamento_gestao_financeira))}</GradeCel>
                                </GradeLinha>
                              ))}
                          </Grade>
                        </div>
                      )}
                    </Secao>
                  </>
                )}
              </React.Fragment>
            );
          }))}

          {aba === "prestacao" && (!arv ? naoColhida : !(arv.relatorios || []).length ? (
            <Vazio>Nenhum relatório de gestão publicado para este plano.</Vazio>
          ) : (
            [...(arv.relatorios || [])]
              .sort((a, b) => String(b.data_e_hora_relatorio_gestao ?? "").localeCompare(String(a.data_e_hora_relatorio_gestao ?? "")))
              .map((rel, i) => (
                <Secao
                  key={i}
                  icon={FileCheck2}
                  titulo={`Relatório ${humano(rel.tipo_relatorio_gestao)?.toLowerCase() || ""} · ${dia(rel.data_relatorio_gestao)}`}
                  campos={[
                    { rotulo: "Situação", valor: humano(rel.situacao_relatorio_gestao) || "-", tom: tomDoPlano(textoDe(rel.situacao_relatorio_gestao)) },
                    { rotulo: "Valor executado", valor: brl(n(rel.valor_executado_relatorio_gestao)) },
                    { rotulo: "Valor pendente", valor: brl(n(rel.valor_pendente_relatorio_gestao)) },
                    { rotulo: "Declaração de conformidade", valor: rel.declaracao_conformidade_relatorio_gestao === true ? "sim" : rel.declaracao_conformidade_relatorio_gestao === false ? "não" : "-" },
                    { rotulo: "Contrapartida", valor: t(rel.contrapartida_relatorio_gestao), span: 2, quebra: true },
                    { rotulo: "Publicidade das ações", valor: t(rel.endereco_eletronico_publicidade_acoes_relatorio_gestao), span: 2, quebra: true },
                  ]}
                >
                  {([
                    ["Resultados alcançados", rel.resultados_alcancados_metas_relatorio_gestao],
                    ["Descritivo", rel.descritivo_relatorio_gestao],
                  ] as const).filter(([, tx]) => textoDe(tx)).map(([rot, tx]) => (
                    <div key={rot} className="mt-2.5">
                      <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>{rot}</div>
                      <p className="mt-0.5 text-[12px] leading-relaxed break-words whitespace-pre-line" style={{ color: "var(--bi-text)" }}>{t(tx)}</p>
                    </div>
                  ))}
                  {/* ⭐ A ANÁLISE DE RESULTADO: quanto de cada ação da meta o
                      município declarou ter executado. */}
                  {(rel.acoes || []).length > 0 && (
                    <div className="mt-3">
                      <div className="mb-1 text-[11px] font-medium" style={{ color: "var(--bi-muted)" }}>Execução física por ação</div>
                      <Grade rolagem minLargura="36rem" cols={COLS_RACAO}
                             cabecalho={[{ label: "Ação" }, { label: "Nome" }, { label: "% físico", direita: true }, { label: "Observações" }]}>
                        {(rel.acoes || []).map((a, j) => {
                          const nome = acoesDaMeta.get(String(a.id_acao_meta_plano_acao)) || "";
                          const [num, ...resto] = nome.split(" — ");
                          return (
                            <GradeLinha key={j} cols={COLS_RACAO}>
                              <GradeCel tom="id">{num || t(a.id_acao_meta_plano_acao)}</GradeCel>
                              <GradeCel>{resto.join(" — ") || "-"}</GradeCel>
                              <GradeCel tom="num">{n(a.percentual_execucao_fisica_acao_relatorio_gestao_acao) != null ? `${n(a.percentual_execucao_fisica_acao_relatorio_gestao_acao)}%` : "-"}</GradeCel>
                              <GradeCel>{t(a.observacoes_justificativas_relatorio_gestao_acao)}</GradeCel>
                            </GradeLinha>
                          );
                        })}
                      </Grade>
                    </div>
                  )}
                  {(rel.analises || []).length > 0 && (
                    <div className="mt-3 flex flex-col gap-2">
                      <div className="text-[11px] font-medium" style={{ color: "var(--bi-muted)" }}>Análise do relatório</div>
                      {(rel.analises || []).map((a, j) => (
                        <div key={j} className="border-t pt-2" style={{ borderColor: "var(--bi-line)" }}>
                          <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                            <span className="font-medium">{humano(a.tipo_analise_relatorio_gestao_analise)}</span>
                            <Selo tom={tomDoPlano(textoDe(a.resultado_analise_relatorio_gestao_analise))}>{humano(a.resultado_analise_relatorio_gestao_analise) || "-"}</Selo>
                            <span className="bi-num text-[11px]" style={{ color: "var(--bi-faint)" }}>{dia(a.data_analise_relatorio_gestao_analise)}</span>
                            {nomes(a.responsaveis, "nome_responsavel_analise_relatorio_gestao_analise") && (
                              <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                                · {nomes(a.responsaveis, "nome_responsavel_analise_relatorio_gestao_analise")}
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-[12px] leading-relaxed break-words whitespace-pre-line" style={{ color: "var(--bi-muted)" }}>
                            {t(a.parecer_analise_relatorio_gestao_analise)}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </Secao>
              ))
          ))}

          {aba === "analise" && (!arv ? naoColhida : !(arv.analises || []).length ? (
            <Vazio>Nenhuma análise registrada para este plano.</Vazio>
          ) : (
            <Secao icon={MessageSquareText} titulo="Pareceres sobre o plano" sub={`${(arv.analises || []).length} análise(s)`}>
              <div className="mt-2 flex flex-col gap-2.5">
                {[...(arv.analises || [])]
                  .sort((a, b) => String(a.data_analise_plano_acao ?? "").localeCompare(String(b.data_analise_plano_acao ?? "")))
                  .map((a, i) => (
                    <div key={i} className="border-t pt-2" style={{ borderColor: "var(--bi-line)" }}>
                      <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                        <span className="font-medium">{humano(a.tipo_analise_plano_acao)}</span>
                        <Selo tom={tomDoPlano(textoDe(a.tipo_resultado_analise_plano_acao))}>{humano(a.tipo_resultado_analise_plano_acao) || "-"}</Selo>
                        <span className="bi-num text-[11px]" style={{ color: "var(--bi-faint)" }}>{dia(a.data_analise_plano_acao)}</span>
                        {nomes(a.responsaveis, "nome_responsavel_analise_plano_acao") && (
                          <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                            · {nomes(a.responsaveis, "nome_responsavel_analise_plano_acao")}
                          </span>
                        )}
                      </div>
                      <p className="mt-1 text-[12px] leading-relaxed break-words whitespace-pre-line" style={{ color: "var(--bi-muted)" }}>
                        {t(a.parecer_analise_plano_acao)}
                      </p>
                    </div>
                  ))}
              </div>
            </Secao>
          ))}

          {aba === "programa" && (
            <>
              {!prog ? (
                <Vazio>O programa deste plano ainda não está no catálogo coletado.</Vazio>
              ) : (
                <Secao
                  icon={Landmark}
                  titulo={`Programa — ${t(prog.nome_programa)}`}
                  campos={[
                    { rotulo: "Código", valor: t(prog.codigo_programa), mono: true },
                    { rotulo: "Ano", valor: t(prog.ano_programa) },
                    { rotulo: "Situação", valor: humano(prog.situacao_programa) || "-" },
                    { rotulo: "Valor global", valor: brl(n(prog.valor_global_programa)) },
                    { rotulo: "Órgão", valor: t(prog.nome_orgao_superior_programa), span: 2 },
                    { rotulo: "Fundo", valor: t(prog.nome_fundo_programa), span: 2 },
                    { rotulo: "Janela (específicos)", valor: `${dia(prog.data_inicio_recebimento_planos_acao_beneficiarios_especificos)} a ${dia(prog.data_fim_recebimento_planos_acao_beneficiarios_especificos)}` },
                    { rotulo: "Janela (emendas)", valor: `${dia(prog.data_inicio_recebimento_planos_acao_beneficiarios_emendas)} a ${dia(prog.data_fim_recebimento_planos_acao_beneficiarios_emendas)}` },
                    { rotulo: "Janela (voluntários)", valor: `${dia(prog.data_inicio_recebimento_planos_acao_beneficiarios_voluntarios)} a ${dia(prog.data_fim_recebimento_planos_acao_beneficiarios_voluntarios)}` },
                    { rotulo: "Gestão Ágil (conta BB)", valor: (prog.gestao_agil || []).map((g) => `${t(g.nome_programa_agil)} (${t(g.codigo_programa_agil)})`).join(" · ") || "-" },
                    { rotulo: "Ação orçamentária", valor: ((prog.programa_acao_orcamentaria as Reg[] | undefined) || []).map((a) => `${t(a.codigo_acao_orcamentaria_programa)} — ${t(a.descricao_acao_orcamentaria_programa)}`).join(" · ") || "-", span: 4, quebra: true },
                    { rotulo: "Objetivo", valor: t(prog.objetivo_programa), span: 4, quebra: true },
                  ]}
                >
                  <details className="mt-2 text-[12px]">
                    <summary className="cursor-pointer" style={{ color: "var(--bi-muted)" }}>descrição do programa</summary>
                    <p className="mt-1 leading-relaxed break-words whitespace-pre-line" style={{ color: "var(--bi-muted)" }}>
                      {t(prog.descricao_programa)}
                    </p>
                  </details>
                </Secao>
              )}
              {arv && (
                <Secao icon={CalendarRange} titulo="Empenhos federais" sub={`${(arv.empenhos || []).length} empenho(s)`}>
                  {!(arv.empenhos || []).length ? <Vazio>A fonte não publica empenho para este plano.</Vazio> : (
                    <div className="mt-2">
                      <Grade rolagem minLargura="44rem" cols={COLS_EMP}
                             cabecalho={[{ label: "Empenho" }, { label: "Emissão" }, { label: "Tipo" }, { label: "Situação" }, { label: "Valor", direita: true }]}>
                        {(arv.empenhos || []).map((e, i) => (
                          <GradeLinha key={i} cols={COLS_EMP}>
                            <GradeCel tom="id">{t(e.numero_empenho)}</GradeCel>
                            <GradeCel tom="data">{dia(e.data_emissao_empenho)}</GradeCel>
                            <GradeCel>{t(e.descricao_tipo_empenho)}</GradeCel>
                            <GradeCel>{t(e.descricao_situacao_empenho)}</GradeCel>
                            <GradeCel tom="num">{brl(n(e.valor_empenho))}</GradeCel>
                          </GradeLinha>
                        ))}
                      </Grade>
                    </div>
                  )}
                </Secao>
              )}
            </>
          )}
          </div>
        </ModalCorpo>
      )}
    </Modal>
  );
}
