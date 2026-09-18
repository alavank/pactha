"use client";

/* FICHA DO PROGRAMA — o que abre ao clicar num programa do radar (18/09/2026).
 *
 * A lista diz QUE o programa existe e ATÉ QUANDO. A ficha responde o que o
 * gestor pergunta em seguida, tudo de dado aberto do TransfereGov:
 *   prazos e portas · a situação do município · concorrência nesta edição ·
 *   outras edições · o que outras prefeituras aprovaram · quem indica na UF.
 *
 * ⚠️ AINDA NÃO HÁ "VALOR DO PROGRAMA", e nenhum número aqui pode fingir que há.
 * A fonte não publica teto nem dotação. O que aparece é o REPASSE MEDIANO DAS
 * PROPOSTAS APROVADAS — o que cada prefeitura pediu e levou —, com esse nome.
 *
 * ⚠️ FICHA PENDENTE NÃO É ZERO. `ficha_em` nulo quer dizer que a montagem ainda
 * não rodou para este programa (publicado depois da última leitura). Mostrar
 * "0 propostas" nesse caso diria ao gestor que ninguém concorre — o contrário
 * do que talvez seja verdade.
 */

import React, { useEffect, useState } from "react";
import {
  BadgeCheck, CalendarClock, Copy, ExternalLink, History, Landmark, Lightbulb, Loader2,
  Users,
} from "lucide-react";

import api from "@/lib/api";
import { formatCurrency, formatCurrencyShort, formatInt } from "@/lib/bi-format";
import {
  AcaoMini, Aviso, Campo, ItemLinha, Lista, Modal, ModalCorpo, ModalHead, Numero, Secao,
  Selo, Vazio,
} from "@/components/ui/superficies";

type Fase = "aprovada" | "rejeitada" | "andamento";
interface Janela { inicio: string | null; fim: string | null; aberta: boolean; dias: number | null }
interface Fases {
  propostas: number; aprovadas: number; rejeitadas: number; andamento: number;
  uf: { propostas: number; aprovadas: number; rejeitadas: number };
  repasse_mediano: number | null;
  /** Fração (0,01 = 1 %) — contrapartida ÷ valor global, mediana das aprovadas. */
  contrapartida_mediana: number | null;
}
interface Ficha {
  municipio: { nome: string; uf: string; cnpj_cadastrado: boolean; ibge_cadastrado: boolean };
  programa: {
    id_programa: string; nome: string; orgao: string | null; modalidade: string | null;
    cod_programa: string | null; acao_orcamentaria: string | null; subtipo: string | null;
    ufs: string[]; consorcio_tambem: boolean;
    dt_disponibilizacao: string | null; dias_publicado: number | null;
    janelas: { recebimento: Janela; emenda: Janela; beneficiario: Janela };
    nomeado: boolean;
  };
  ficha_em: string | null;
  situacao?: {
    indicacoes: { parlamentar: string | null; solicitante: string | null; indicacao: string | null;
                  nr_emenda: string | null; valor: number | null }[];
    propostas: { edicao_atual: boolean; ano: number | null; data: string | null;
                 nr_proposta: string | null; situacao: string | null; fase: Fase;
                 vl_repasse: number | null; vl_global: number | null; objeto: string | null;
                 proponente: string | null }[];
  };
  concorrencia?: Fases;
  historico?: { edicoes: { id: string; ano: number | null; nome: string }[]; fases: Fases | null };
  exemplos?: { edicao_atual: boolean; ano: number | null; uf: string | null;
               proponente: string | null; objeto: string; vl_repasse: number | null }[];
  apoiadores?: {
    indicacoes: number; municipios: number; municipios_uf: number;
    na_uf: { parlamentar: string | null; solicitante: string | null; municipios: number;
             valor: number | null }[];
  };
}

const PORTAS: { chave: keyof Ficha["programa"]["janelas"]; rotulo: string }[] = [
  { chave: "recebimento", rotulo: "Proposta voluntária" },
  { chave: "emenda", rotulo: "Emenda parlamentar" },
  { chave: "beneficiario", rotulo: "Beneficiário nomeado" },
];

const faseTom = (f: Fase) => (f === "aprovada" ? "ok" : f === "rejeitada" ? "critico" : "neutro");

/** "aprovadas ÷ decididas", e não ÷ propostas: proposta em análise ainda não
 *  perdeu, e contá-la no denominador faria toda edição recente parecer um
 *  massacre. Sem decisão nenhuma, não há taxa — e "—" diz isso. */
function taxa(f: { aprovadas: number; rejeitadas: number }): string {
  const d = f.aprovadas + f.rejeitadas;
  return d ? `${Math.round((100 * f.aprovadas) / d)} %` : "—";
}

/** Montado com `key` de programa + município pela página: trocar de programa
 *  REMONTA o componente, e o estado nasce vazio sem precisar ser limpo num
 *  efeito (o que mostraria a ficha anterior por um instante). */
export function FichaPrograma({ idPrograma, municipioId, onFechar }: {
  idPrograma: string; municipioId: string; onFechar: () => void;
}) {
  const [d, setD] = useState<Ficha | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [copiado, setCopiado] = useState(false);

  useEffect(() => {
    let vivo = true;
    api.get(`/programas-captacao/${encodeURIComponent(idPrograma)}`,
            { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setD(r.data); })
      .catch((e) => {
        if (!vivo) return;
        // 404 aqui é o programa que FECHOU entre a lista e o clique (a lista é
        // de antes da virada do dia, por exemplo) — e isso é informação.
        setErro(e?.response?.status === 404
          ? "Este programa não está mais aberto para o município. Recarregue o radar."
          : "Não foi possível carregar a ficha do programa.");
      });
    return () => { vivo = false; };
  }, [idPrograma, municipioId]);

  const p = d?.programa;
  const copiar = () => {
    if (!p?.cod_programa) return;
    navigator.clipboard?.writeText(p.cod_programa).then(() => {
      setCopiado(true);
      setTimeout(() => setCopiado(false), 1500);
    }).catch(() => {});
  };

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-4xl">
      <ModalHead
        titulo={p?.nome ?? "…"}
        sub={p ? [p.orgao, p.modalidade?.toLowerCase()].filter(Boolean).join(" · ") : "Radar de captação"}
        onFechar={onFechar}
      />
      {!d && !erro && (
        <div className="flex items-center justify-center gap-2 py-16 text-[12px]"
             style={{ color: "var(--bi-faint)" }}>
          <Loader2 className="size-4 animate-spin" /> Carregando…
        </div>
      )}
      {erro && <ModalCorpo><Vazio>{erro}</Vazio></ModalCorpo>}
      {d && p && (
        <ModalCorpo className="flex flex-col gap-3">
          <Prazos d={d} copiado={copiado} onCopiar={copiar} />
          {d.ficha_em == null ? (
            <Aviso tom="atencao" icon={CalendarClock} className=""
                   titulo="A ficha deste programa ainda não foi montada">
              <p className="text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
                O programa entrou depois da última leitura das propostas. Situação do
                município, concorrência e edições anteriores aparecem na próxima coleta.
                Isto <strong>não</strong> quer dizer que ninguém propôs.
              </p>
            </Aviso>
          ) : (
            <>
              <Situacao d={d} />
              <Concorrencia d={d} />
              <Historico d={d} />
              <Exemplos d={d} />
              <QuemIndica d={d} />
              <p className="px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                Dados abertos do TransfereGov · ficha montada em {quando(d.ficha_em)} · só
                propostas de prefeitura (Administração Pública Municipal)
              </p>
            </>
          )}
        </ModalCorpo>
      )}
    </Modal>
  );
}

function Prazos({ d, copiado, onCopiar }: { d: Ficha; copiado: boolean; onCopiar: () => void }) {
  const p = d.programa;
  const campos: Campo[] = [];
  for (const { chave, rotulo } of PORTAS) {
    const j = p.janelas[chave];
    if (!j.aberta) continue;
    campos.push({
      rotulo,
      valor: `${j.inicio ? `${data(j.inicio)} a ` : "até "}${data(j.fim)}${
        j.dias != null ? ` (${j.dias === 0 ? "fecha hoje" : `${j.dias} dias`})` : ""}`,
      tom: j.dias != null && j.dias <= 7 ? "critico" : j.dias != null && j.dias <= 30 ? "atencao" : "normal",
      span: 2,
    });
  }
  if (p.dt_disponibilizacao) {
    campos.push({ rotulo: "Publicado em",
                  valor: `${data(p.dt_disponibilizacao)}${p.dias_publicado != null ? ` (há ${p.dias_publicado} dias)` : ""}` });
  }
  if (p.acao_orcamentaria) campos.push({ rotulo: "Ação orçamentária", valor: p.acao_orcamentaria, mono: true });
  if (p.subtipo) campos.push({ rotulo: "Subtipo", valor: p.subtipo, quebra: true });
  campos.push({
    rotulo: "Quem pode propor",
    /* A lista inteira de UFs, e não "20 estados": o gestor quer saber se o
       vizinho de fronteira concorre com ele. */
    valor: p.ufs.length >= 27 ? "prefeituras dos 27 estados"
      : `prefeituras de ${p.ufs.join(", ")}`,
    span: 4, quebra: true,
  });
  return (
    <Secao icon={CalendarClock} titulo="Prazos e portas"
           sub="por onde se entra e até quando — cada porta tem prazo próprio" campos={campos}>
      {p.janelas.emenda.aberta && !p.janelas.recebimento.aberta && (
        <p className="mt-2 px-1 text-[10px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          Só entra por emenda parlamentar: depende de um deputado, senador ou comissão
          destinar o recurso ao município.
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2 px-1">
        {p.cod_programa && (
          <>
            <span className="bi-id text-[11px]">código {p.cod_programa}</span>
            <AcaoMini onClick={onCopiar}>
              <span className="inline-flex items-center gap-1">
                <Copy className="size-3" /> {copiado ? "copiado" : "copiar código"}
              </span>
            </AcaoMini>
          </>
        )}
        <a href="https://www.gov.br/transferegov/" target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-[11px] underline"
           style={{ color: "var(--bi-accent-ink)" }}>
          Apresentar proposta no TransfereGov <ExternalLink className="size-3" />
        </a>
      </div>
    </Secao>
  );
}

function Situacao({ d }: { d: Ficha }) {
  const s = d.situacao!;
  const p = d.programa;
  const mun = d.municipio.nome;
  const atuais = s.propostas.filter((x) => x.edicao_atual);
  const anteriores = s.propostas.filter((x) => !x.edicao_atual);
  return (
    <Secao icon={BadgeCheck} titulo={`Situação de ${mun}`}
           sub="indicação de emenda e propostas do município neste programa">
      {p.janelas.beneficiario.aberta && (
        <Aviso tom="ok" icon={BadgeCheck} className="mb-2"
               titulo={`O programa nomeia ${mun} como beneficiário`} />
      )}
      {s.indicacoes.length > 0 ? (
        <Lista className="mb-2">
          {s.indicacoes.map((i, k) => (
            <ItemLinha key={k}
              titulo={<span>Emenda indicada por <strong>{i.parlamentar || "—"}</strong>
                {i.solicitante && i.solicitante !== i.parlamentar ? ` a pedido de ${i.solicitante}` : ""}</span>}
              valor={i.valor != null ? formatCurrency(i.valor) : "—"}
              meta={<>{i.indicacao && <span>{i.indicacao.toLowerCase()}</span>}
                {i.nr_emenda && <span>· emenda {i.nr_emenda}</span>}</>} />
          ))}
        </Lista>
      ) : p.janelas.emenda.aberta && (
        <p className="mb-2 px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.municipio.cnpj_cadastrado
            ? `Nenhuma emenda indicada para ${mun} neste programa até a última leitura. A lista cresce durante a janela, conforme os gabinetes indicam.`
            : `${mun} está sem CNPJ cadastrado, e a indicação de emenda só se cruza pelo CNPJ. Cadastre em Configurações → Municípios.`}
        </p>
      )}
      {!d.municipio.ibge_cadastrado ? (
        <p className="px-1 text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>
          {mun} está sem código IBGE cadastrado, então as propostas do município não
          puderam ser cruzadas.
        </p>
      ) : atuais.length === 0 ? (
        <p className="px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          Nenhuma proposta de {mun} nesta edição do programa.
        </p>
      ) : null}
      {s.propostas.length > 0 && (
        <Lista>
          {[...atuais, ...anteriores].map((x, k) => (
            <ItemLinha key={k}
              titulo={x.objeto || "Proposta sem objeto publicado"}
              valor={x.vl_repasse != null ? formatCurrency(x.vl_repasse) : "—"}
              meta={<>
                <Selo tom={faseTom(x.fase)}>{x.situacao || x.fase}</Selo>
                {x.nr_proposta && <span>proposta {x.nr_proposta}</span>}
                {x.data && <span>· {data(x.data)}</span>}
                {!x.edicao_atual && <span>· edição {x.ano ?? "anterior"}</span>}
              </>} />
          ))}
        </Lista>
      )}
    </Secao>
  );
}

function Concorrencia({ d }: { d: Ficha }) {
  const c = d.concorrencia!;
  const uf = d.municipio.uf;
  return (
    <Secao icon={Users} titulo="Concorrência nesta edição"
           sub="propostas de prefeitura já cadastradas neste programa">
      <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Numero rotulo="No país" valor={formatInt(c.propostas)}
                sub={`${formatInt(c.andamento)} em andamento`} />
        <Numero rotulo={`No ${uf}`} valor={formatInt(c.uf.propostas)} tom="acento"
                sub={`${formatInt(c.uf.aprovadas)} aprovada(s)`} />
        <Numero rotulo="Aprovadas no país" valor={formatInt(c.aprovadas)}
                sub={`${formatInt(c.rejeitadas)} rejeitada(s)`} />
        <Numero rotulo="Aprovação" valor={taxa(c)} sub="das propostas já decididas" />
      </div>
    </Secao>
  );
}

function Historico({ d }: { d: Ficha }) {
  const h = d.historico!;
  const f = h.fases;
  return (
    <Secao icon={History} titulo="Outras edições do programa"
           sub="mesmo órgão e mesmo nome, publicadas em outro ano ou já fechadas">
      {h.edicoes.length === 0 || !f ? (
        <p className="mt-1 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          Nenhuma outra edição com o mesmo nome e o mesmo órgão no TransfereGov.
        </p>
      ) : (
        <>
          <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Numero rotulo="Propostas" valor={formatInt(f.propostas)}
                    sub={`${formatInt(f.uf.propostas)} no ${d.municipio.uf}`} />
            <Numero rotulo="Aprovação" valor={taxa(f)}
                    sub={`no ${d.municipio.uf}: ${taxa(f.uf)}`} />
            {/* ⚠️ O RÓTULO É O DADO. "Repasse mediano das aprovadas", nunca
                "valor do programa" — a fonte não publica teto nem dotação. */}
            <Numero rotulo="Repasse mediano das aprovadas"
                    valor={f.repasse_mediano != null ? formatCurrencyShort(f.repasse_mediano) : "—"}
                    sub="metade pediu menos, metade mais" />
            <Numero rotulo="Contrapartida mediana"
                    valor={f.contrapartida_mediana != null
                      ? `${(f.contrapartida_mediana * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} %`
                      : "—"}
                    sub="do valor global, nas aprovadas" />
          </div>
          <p className="mt-2 px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            {h.edicoes.map((e) => `${e.ano ?? "s/ ano"} (programa ${e.id})`).join(" · ")}
          </p>
        </>
      )}
    </Secao>
  );
}

function Exemplos({ d }: { d: Ficha }) {
  const xs = d.exemplos ?? [];
  return (
    <Secao icon={Lightbulb} titulo="O que outras prefeituras aprovaram"
           sub={`propostas aprovadas neste programa e nas edições anteriores — ${d.municipio.uf} primeiro`}>
      {xs.length === 0 ? (
        <p className="mt-1 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          Nenhuma proposta de prefeitura aprovada ainda neste programa ou nas edições anteriores.
        </p>
      ) : (
        <Lista className="mt-1">
          {xs.map((x, k) => (
            <ItemLinha key={k} titulo={x.objeto}
              valor={x.vl_repasse != null ? formatCurrencyShort(x.vl_repasse) : "—"}
              meta={<>
                {x.proponente && <span>{x.proponente}</span>}
                {x.uf && <span>· {x.uf}</span>}
                <span>· {x.edicao_atual ? "esta edição" : `edição ${x.ano ?? "anterior"}`}</span>
              </>} />
          ))}
        </Lista>
      )}
    </Secao>
  );
}

function QuemIndica({ d }: { d: Ficha }) {
  const a = d.apoiadores!;
  const uf = d.municipio.uf;
  // Programa sem porta de emenda e sem indicação: o bloco não tem o que dizer.
  if (!d.programa.janelas.emenda.aberta && a.indicacoes === 0) return null;
  return (
    <Secao icon={Landmark} titulo={`Quem indica emenda no ${uf}`}
           sub="parlamentares e comissões com emenda neste programa para prefeituras da UF">
      {a.indicacoes === 0 ? (
        <p className="mt-1 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          O dado aberto não publica indicações de emenda para este programa.
        </p>
      ) : a.na_uf.length === 0 ? (
        <p className="mt-1 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          Nenhuma indicação para prefeituras do {uf}. No país, {formatInt(a.municipios)}{" "}
          município(s) receberam indicação neste programa.
        </p>
      ) : (
        <>
          <Lista className="mt-1">
            {a.na_uf.map((r, k) => (
              <ItemLinha key={k}
                titulo={<span>{r.parlamentar || "—"}
                  {r.solicitante && r.solicitante !== r.parlamentar
                    ? <span style={{ color: "var(--bi-muted)" }}> · a pedido de {r.solicitante}</span> : null}</span>}
                valor={r.valor != null ? formatCurrencyShort(r.valor) : "—"}
                meta={<span>{formatInt(r.municipios)} município(s) do {uf}</span>} />
            ))}
          </Lista>
          <p className="mt-2 px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            {formatInt(a.municipios_uf)} município(s) do {uf} e {formatInt(a.municipios)} no país
            com indicação neste programa.
          </p>
        </>
      )}
    </Secao>
  );
}

/* Data pura (dd/mm/aaaa). O `T00:00:00` sem fuso lê como dia local — ver a
 * mesma nota em `page.tsx`. */
function data(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleDateString("pt-BR");
}

function quando(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}
