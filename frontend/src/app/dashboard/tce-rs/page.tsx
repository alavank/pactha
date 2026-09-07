"use client";

/* TCE-RS — as remessas obrigatórias que refletem na habilitação.
 *
 * ⭐ POR QUE ISTO NÃO É "TELA DE TRIBUNAL", e sim de captação: o atraso na
 * remessa vira pendência no TCE, pendência vira irregularidade fiscal, e
 * irregularidade trava a habilitação para convênio — o CHE inclui certidões do
 * TCE entre suas exigências. A cadeia é invisível para quem olha só o
 * financeiro, e é onde o convênio morre antes de nascer.
 *
 * ⭐ ESTA TELA DEIXOU DE SER SÓ CURADORIA. O calendário de remessas continua
 * sendo conteúdo — é norma, não muda toda semana. Mas as LICITAÇÕES e os
 * CONTRATOS vêm do LicitaCon, pelos dados abertos do próprio Tribunal: em Nova
 * Palma são 866 licitações e 1.202 contratos.
 *
 * São DOIS coletores para as mesmas tabelas, por dois hosts diferentes:
 * `ingestion/tce_rs.py` (dados.tce.rs.gov.br, CKAN — o que devolve 403 ao IP do
 * servidor) e `ingestion/tce_rs_portal.py` (portal.tce.rs.gov.br, API aberta).
 * O segundo entrega o mesmo acervo e mais: obra, medição, saldo e a ORIGEM DO
 * RECURSO — o convênio que pagou a obra, declarado pelo próprio município.
 *
 * As três coisas convivem, e a tela diz qual é qual: o AvisoCurado fala do
 * calendário, e os blocos do LicitaCon trazem dado coletado com data.
 *
 * ⚠️ E quando não há dado coletado, a tela NÃO conclui "o município não licita".
 * A ausência pode ser bloqueio nosso, não silêncio da prefeitura — e afirmar o
 * contrário seria acusar o cliente de uma omissão que ele não cometeu.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { CalendarClock, ExternalLink, Gavel, HardHat, Landmark, Loader2 } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { AvisoCurado } from "@/components/rs/AvisoCurado";
import { Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

interface Sistema {
  nome: string; o_que: string; periodicidade: string; prazo: string;
}
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  aviso?: string;
  titulo?: string;
  subtitulo?: string;
  sistemas?: Sistema[];
  por_que_importa?: string;
  codigo_orgao?: string;
  links?: [string, string][];
  municipio?: { tce_orgao_codigo: string | null };
  licitacon?: {
    coletado: boolean;
    atualizado_em?: string | null;
    entidades?: Array<{ codigo: string; nome?: string | null;
      licitacoes: number; contratos: number }>;
    licitacoes_por_ano?: Array<{ ano: number; orgao?: string | null;
      orgao_nome?: string | null; total: number;
      valor_estimado?: number | null; valor_homologado?: number | null }>;
    contratos_por_ano?: Array<{ ano: number; orgao?: string | null;
      orgao_nome?: string | null; total: number; valor?: number | null }>;
    contratos_vigentes?: Array<{ numero: string; objeto?: string | null;
      valor?: number | null; vigencia_ate?: string | null;
      contratado_documento?: string | null; link?: string | null;
      contratado?: string | null; valor_atual?: number | null;
      orgao?: string | null }>;
  };
  obras?: {
    coletado: boolean;
    atualizado_em?: string | null;
    total?: number;
    paralisadas?: number;
    com_origem_declarada?: number;
    obras?: Array<{
      id: number; objeto?: string | null; situacao?: string | null;
      orgao?: string | null;
      contratado?: string | null; valor?: number | null; medido?: number | null;
      pc_financeiro?: number | null; pc_fisico?: number | null;
      vigencia_ate?: string | null; paralisada_em?: string | null;
      motivo_paralisacao?: string | null; medicoes?: number | null;
      ultima_medicao?: string | null; contrato?: string | null;
      recursos?: Array<{ tipo?: string | null; fonte?: string | null;
        convenio?: string | null; valor?: number | null;
        contrapartida?: number | null; codigo?: string | null }>;
    }>;
  };
}

const money = (v?: number | null) =>
  v == null ? "—" : v.toLocaleString("pt-BR", { style: "currency", currency: "BRL",
                                                maximumFractionDigits: 0 });
const dia = (iso?: string | null) =>
  iso ? new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("pt-BR") : "—";

/* ⚠️ O MUNICÍPIO É MAIS DE UMA ENTIDADE NO LICITACON. Além da prefeitura, as
   autarquias e fundações municipais têm código próprio no Tribunal e licitam
   por conta — em Santa Maria, o IPASSP-SM e o IPLAN. O coletor traz as três, e
   somar tudo é correto: é dinheiro público municipal.

   Mas quem abre a tela procurando "os contratos da prefeitura" precisa chegar
   nesse número sem subtrair de cabeça. Daí o filtro — e ele só aparece quando
   há mais de uma entidade, porque em Nova Palma (só a prefeitura) seria um
   controle que não controla nada. */
const soma = <T extends { ano: number }>(
  linhas: T[] | undefined,
  orgaoDe: (l: T) => string | null | undefined,
  filtro: string | null,
  juntar: (acc: T, l: T) => T,
): T[] => {
  const fora = (linhas || []).filter((l) => !filtro || orgaoDe(l) === filtro);
  const porAno = new Map<number, T>();
  for (const l of fora) {
    const atual = porAno.get(l.ano);
    porAno.set(l.ano, atual ? juntar(atual, l) : { ...l });
  }
  return [...porAno.values()].sort((a, b) => b.ano - a.ano);
};

/* Nome curto para o chip: o TCE manda "IPASSP-SM - INST. PREV. ASSIST. À SAÚDE
   SERV. PÚBL. MUN. DE SANTA MARIA". A sigla antes do travessão é como o próprio
   órgão se chama. */
const curto = (nome?: string | null, codigo?: string) =>
  (nome || codigo || "").split(" - ")[0].trim().slice(0, 28) || (codigo ?? "");

export default function TceRsPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [orgao, setOrgao] = useState<string | null>(null);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get("/rs/tce", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId]);
  useEffect(carregar, [carregar]);

  const entidades = d?.licitacon?.entidades || [];
  // ⚠️ O filtro só existe com MAIS DE UMA entidade. Em Nova Palma há só a
  // prefeitura, e um seletor de um item é ruído que sugere escolha inexistente.
  const temFiltro = entidades.length > 1;
  // ⚠️ O filtro é DERIVADO, e só vale se a entidade existir nos dados que estão
  // na tela. Sem isso, trocar de município no seletor manteria o código de órgão
  // do município anterior — que não casa com nada — e a tela apareceria vazia,
  // como se a prefeitura nova não licitasse. Derivar em vez de resetar num
  // efeito evita o render extra (e o aviso do lint).
  const filtro = temFiltro && entidades.some((e) => e.codigo === orgao)
    ? orgao : null;

  const licPorAno = useMemo(
    () => soma(d?.licitacon?.licitacoes_por_ano, (l) => l.orgao, filtro,
               (a, l) => ({
                 ...a,
                 total: a.total + l.total,
                 // ⚠️ null + número não pode virar número: "sem valor" somado a
                 // "com valor" continua parcial, e mostrar o parcial como total
                 // seria afirmar que o resto é zero.
                 valor_estimado: a.valor_estimado == null && l.valor_estimado == null
                   ? null : (a.valor_estimado ?? 0) + (l.valor_estimado ?? 0),
                 valor_homologado: a.valor_homologado == null && l.valor_homologado == null
                   ? null : (a.valor_homologado ?? 0) + (l.valor_homologado ?? 0),
               })),
    [d?.licitacon?.licitacoes_por_ano, filtro],
  );
  const conPorAno = useMemo(
    () => soma(d?.licitacon?.contratos_por_ano, (l) => l.orgao, filtro,
               (a, l) => ({
                 ...a,
                 total: a.total + l.total,
                 valor: a.valor == null && l.valor == null
                   ? null : (a.valor ?? 0) + (l.valor ?? 0),
               })),
    [d?.licitacon?.contratos_por_ano, filtro],
  );
  const vigentes = useMemo(
    () => (d?.licitacon?.contratos_vigentes || [])
      .filter((c) => !filtro || c.orgao === filtro).slice(0, 10),
    [d?.licitacon?.contratos_vigentes, filtro],
  );
  const obrasFiltradas = useMemo(
    () => (d?.obras?.obras || []).filter((o) => !filtro || o.orgao === filtro),
    [d?.obras?.obras, filtro],
  );

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;

  const codigo = d.municipio?.tce_orgao_codigo;

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>{d.titulo}</TituloTela>
        <p className="text-sm text-muted-foreground">{d.subtitulo}</p>
      </div>

      <AvisoCurado>{d.aviso}</AvisoCurado>

      {/* ---------------- LicitaCon: dado coletado, não curadoria ----------------
          Vem ANTES do calendário de propósito: é o que fala do município deste
          cliente, enquanto o calendário fala da norma. */}
      {d.licitacon?.coletado ? (
        <Bloco className="p-3">
          <BlocoHead
            icon={Gavel}
            titulo="Licitações e contratos do município"
            sub="dados abertos do LicitaCon / TCE-RS — coletado, não curado"
            right={d.licitacon.atualizado_em
              ? <Selo>{`atualizado em ${dia(d.licitacon.atualizado_em)}`}</Selo>
              : undefined}
          />

          {/* ⭐ O FILTRO POR ENTIDADE. O município é a prefeitura MAIS as autarquias
              e fundações municipais, cada uma com código próprio no Tribunal.
              O total somado é o correto — é dinheiro público municipal —, e
              este seletor é o que permite chegar em "só a prefeitura" sem
              subtrair de cabeça. */}
          {temFiltro && (
            <div className="mb-3 flex flex-wrap items-center gap-1.5">
              {[{ codigo: "", nome: "Todas as entidades", licitacoes: 0, contratos: 0 },
                ...entidades].map((e) => {
                const ativo = (e.codigo || null) === filtro;
                return (
                  <button
                    key={e.codigo || "todas"}
                    type="button"
                    onClick={() => setOrgao(e.codigo || null)}
                    className="rounded-full border px-2.5 py-1 text-[11px] transition-colors"
                    style={{
                      borderColor: ativo ? "var(--bi-accent-ink)" : "var(--bi-line)",
                      color: ativo ? "var(--bi-accent-ink)" : "var(--bi-muted)",
                      fontWeight: ativo ? 600 : 400,
                    }}
                    title={e.codigo ? `${e.nome} — código ${e.codigo} no TCE-RS` : undefined}
                  >
                    {e.codigo ? curto(e.nome, e.codigo) : e.nome}
                    {e.codigo ? (
                      <span style={{ color: "var(--bi-faint)" }}>
                        {" "}{e.licitacoes + e.contratos}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <div className="bi-title mb-1 text-[12px]">Licitações por ano</div>
              <Lista>
                {licPorAno.map((a) => (
                  <li key={a.ano}
                      className="flex flex-wrap items-baseline justify-between gap-x-3 py-1">
                    <span className="text-[12px] tabular-nums"
                          style={{ color: "var(--bi-text)" }}>
                      {a.ano} · {a.total} certame(s)
                    </span>
                    {/* ⚠️ Estimado e homologado NÃO fecham, e isso é a verdade:
                        certame em andamento entra na contagem e não na soma do
                        homologado. Mostrar só um dos dois esconderia a economia
                        do certame — ou inventaria contratação que não houve. */}
                    <span className="text-[11px] tabular-nums"
                          style={{ color: "var(--bi-muted)" }}>
                      {money(a.valor_homologado)} homologado
                      <span style={{ color: "var(--bi-faint)" }}>
                        {" "}de {money(a.valor_estimado)} estimado
                      </span>
                    </span>
                  </li>
                ))}
              </Lista>
            </div>
            <div>
              <div className="bi-title mb-1 text-[12px]">Contratos por ano</div>
              <Lista>
                {conPorAno.map((a) => (
                  <li key={a.ano}
                      className="flex flex-wrap items-baseline justify-between gap-x-3 py-1">
                    <span className="text-[12px] tabular-nums"
                          style={{ color: "var(--bi-text)" }}>
                      {a.ano} · {a.total} contrato(s)
                    </span>
                    <span className="text-[11px] tabular-nums"
                          style={{ color: "var(--bi-muted)" }}>
                      {money(a.valor)}
                    </span>
                  </li>
                ))}
              </Lista>
            </div>
          </div>

          {!!vigentes.length && (
            <div className="mt-3">
              <div className="bi-title mb-1 text-[12px]">
                Contratos vigentes — os próximos a vencer
              </div>
              <Lista>
                {vigentes.map((c) => (
                  <li key={c.numero} className="py-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                      <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                        Contrato {c.numero}
                      </span>
                      <span className="text-[11px] tabular-nums"
                            style={{ color: "var(--bi-muted)" }}>
                        {money(c.valor)} · até {dia(c.vigencia_ate)}
                      </span>
                    </div>
                    {/* ⚠️ O valor DEPOIS dos aditivos só aparece quando difere
                        do inicial. Mostrar "R$ X (atual R$ X)" em todo contrato
                        seria ruído; mostrar a diferença quando ela existe é
                        exatamente o que o Tribunal fiscaliza. */}
                    {c.valor_atual != null && c.valor != null
                      && c.valor_atual !== c.valor && (
                      <div className="text-[11px] tabular-nums"
                           style={{ color: "var(--bi-muted)" }}>
                        com aditivos: {money(c.valor_atual)}
                      </div>
                    )}
                    {c.contratado && (
                      <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                        {c.contratado}
                      </div>
                    )}
                    {c.objeto && (
                      <div className="text-[11px] leading-snug"
                           style={{ color: "var(--bi-faint)" }}>
                        {c.objeto.slice(0, 140)}
                      </div>
                    )}
                  </li>
                ))}
              </Lista>
            </div>
          )}
        </Bloco>
      ) : (
        /* ⚠️ AUSÊNCIA DE COLETA NÃO É AUSÊNCIA DE LICITAÇÃO. O TCE-RS recusa
           conexões de faixa de datacenter; dizer "nenhuma licitação" aqui seria
           acusar a prefeitura de uma omissão que pode ser bloqueio nosso. */
        <Bloco className="p-3">
          <BlocoHead icon={Gavel} titulo="Licitações e contratos"
                     sub="ainda não coletados deste município" />
          <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            O LicitaCon publica as licitações e os contratos do município em dados
            abertos, e o PACTHA já sabe lê-los. Enquanto esta seção estiver vazia,
            <b> não conclua que não há licitações</b>: o Tribunal recusa conexões
            vindas de servidores de datacenter, e a liberação é o que falta — não
            o código. A consulta pública continua disponível no LicitaCon Cidadão,
            pelo link abaixo.
          </p>
        </Bloco>
      )}

      {/* ---------------- LicitaCon Obras: a execução, e quem pagou ------------
          ⭐ É o bloco que fecha o círculo do produto. O TransfereGov mostra o
          repasse e o LicitaCon mostra o contrato; aqui está se a obra ANDOU — e,
          na origem do recurso, o convênio que a financiou, declarado pelo
          próprio município ao Tribunal.

          ⚠️ Só aparece quando há obra. Ausência aqui é estado legítimo: o
          sistema é de 2024 e município pequeno pode não ter obra sujeita a
          registro — inventar um "nenhuma obra encontrada" ao lado de uma tela de
          convênios sugeriria omissão onde não há. */}
      {d.obras?.coletado && !!obrasFiltradas.length && (
        <Bloco className="p-3">
          <BlocoHead
            icon={HardHat}
            titulo="Obras registradas no LicitaCon Obras"
            /* ⚠️ O subtítulo conta o que ESTÁ NA LISTA, não o total do
               município: com o filtro ativo, "120 obras" ao lado de três
               listadas seria contradição na mesma linha. */
            sub={`${obrasFiltradas.length} obra(s)`
              + (obrasFiltradas.some((o) => o.paralisada_em)
                  ? ` · ${obrasFiltradas.filter((o) => o.paralisada_em).length} paralisada(s)`
                  : "")
              + (obrasFiltradas.some((o) => o.recursos?.length)
                  ? ` · ${obrasFiltradas.filter((o) => o.recursos?.length).length} com origem de recurso declarada`
                  : "")}
            right={d.obras.atualizado_em
              ? <Selo>{`atualizado em ${dia(d.obras.atualizado_em)}`}</Selo>
              : undefined}
          />
          <Lista>
            {obrasFiltradas.map((o) => (
              <li key={o.id} className="py-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="text-[12px]" style={{ color: "var(--bi-text)" }}>
                    {o.contrato ? `Contrato ${o.contrato}` : `Obra ${o.id}`}
                    {o.situacao && (
                      <span className="ml-2 text-[11px]"
                            style={{ color: "var(--bi-muted)" }}>{o.situacao}</span>
                    )}
                  </span>
                  <span className="text-[11px] tabular-nums"
                        style={{ color: "var(--bi-muted)" }}>
                    {money(o.medido)} medido de {money(o.valor)}
                  </span>
                </div>

                {o.objeto && (
                  <div className="text-[11px] leading-snug"
                       style={{ color: "var(--bi-faint)" }}>
                    {o.objeto.slice(0, 160)}
                  </div>
                )}

                {/* ⚠️ OS DOIS PERCENTUAIS, LADO A LADO E NOMEADOS. Numa obra real
                    de Santa Maria o financeiro está em 90,6% e o físico em 0,0,
                    porque o órgão mede o pagamento e não alimenta o avanço da
                    obra. Um número só, sem dizer qual é, faria o gestor ler
                    "quase pronta" onde o Tribunal lê "nada informado". */}
                <div className="mt-0.5 flex flex-wrap gap-x-4 text-[11px] tabular-nums"
                     style={{ color: "var(--bi-muted)" }}>
                  {o.pc_financeiro != null && (
                    <span>financeiro {o.pc_financeiro.toFixed(1)}%</span>
                  )}
                  {o.pc_fisico != null && (
                    <span>físico {o.pc_fisico.toFixed(1)}%</span>
                  )}
                  {!!o.medicoes && (
                    <span>{o.medicoes} medição(ões)
                      {o.ultima_medicao ? `, última em ${dia(o.ultima_medicao)}` : ""}
                    </span>
                  )}
                  {o.vigencia_ate && <span>vigência até {dia(o.vigencia_ate)}</span>}
                </div>

                {o.paralisada_em && (
                  <div className="mt-0.5 text-[11px]" style={{ color: "var(--bi-accent-ink)" }}>
                    paralisada em {dia(o.paralisada_em)}
                    {o.motivo_paralisacao ? ` — ${o.motivo_paralisacao}` : ""}
                  </div>
                )}

                {/* ⭐ A ORIGEM DO RECURSO — o elo com o convênio. */}
                {o.recursos?.map((r, i) => (
                  <div key={i} className="mt-0.5 text-[11px] leading-snug"
                       style={{ color: "var(--bi-text)" }}>
                    <span className="font-semibold">{r.tipo}</span>
                    {r.fonte ? ` · ${r.fonte}` : ""}
                    {r.convenio ? ` · ${r.convenio}` : ""}
                    {r.valor != null ? ` · ${money(r.valor)}` : ""}
                    {r.contrapartida ? ` (contrapartida ${money(r.contrapartida)})` : ""}
                  </div>
                ))}
              </li>
            ))}
          </Lista>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={CalendarClock} titulo="Sistemas e periodicidade" />
        <Lista>
          {(d.sistemas || []).map((s) => (
            <ItemLinha
              key={s.nome}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2">
                  <span>{s.nome}</span>
                  <Selo>{s.periodicidade}</Selo>
                </span>
              }
              meta={s.o_que}
            >
              <div className="mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                <span className="font-semibold" style={{ color: "var(--bi-text)" }}>Prazo: </span>
                {s.prazo}
              </div>
            </ItemLinha>
          ))}
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Landmark} titulo="Por que isso aparece num sistema de convênios" />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.por_que_importa}
        </p>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead
          icon={Landmark}
          titulo="Código do órgão no TCE-RS"
          sub={codigo ? `Cadastrado neste município: ${codigo}` : "Ainda não cadastrado neste município"}
        />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          {d.codigo_orgao}
        </p>
        <div className="mt-2 flex flex-wrap gap-3 px-1">
          {(d.links || []).map(([rotulo, url]) => (
            <a key={url} href={url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-[11px] underline"
               style={{ color: "var(--bi-accent-ink)" }}>
              {rotulo} <ExternalLink className="size-3" />
            </a>
          ))}
        </div>
      </Bloco>
    </div>
  );
}
