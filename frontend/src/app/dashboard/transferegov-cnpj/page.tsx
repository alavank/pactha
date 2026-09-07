"use client";

import React, { useMemo, useState } from "react";
import {
  Search as SearchIcon, Loader2, Landmark, Building2, Coins, FileText, Wallet,
  ChevronDown, ChevronRight,
} from "lucide-react";
import api from "@/lib/api";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { formatCurrency } from "@/lib/utils";
import { textoDe } from "@/lib/texto";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import {
  Bloco, BlocoHead, Campo, Campos, ItemLinha, Lista, Modal, ModalCorpo, ModalHead,
  Numero, Secao, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";

/** O `-` de campo vazio, e o `title` para o valor truncado ser recuperavel.
 *  Substitui o `Field` local, que era a setima forma do mesmo padrao no
 *  produto: `wide` virou `span`, `mono` virou `mono`. */
function campoC(rotulo: string, valor: unknown, extra?: Partial<Campo>): Campo {
  /* O `valor as React.ReactNode` que estava aqui era um cast que MENTIA: dizia
     ao compilador que qualquer coisa serve como filho de JSX. Quinze campos
     desta tela vêm crus da API federal, e um objeto entre eles derruba a
     árvore inteira do React (erro #31) — o mesmo defeito que apagava a tela de
     Especiais. `textoDe` resolve o valor E o `title` do mesmo jeito, então os
     dois nunca mais divergem. */
  const texto = textoDe(valor);
  return {
    rotulo,
    valor: texto ?? "-",
    title: texto ? `${rotulo}: ${texto}` : undefined,
    ...extra,
  };
}

interface Especial {
  id?: number; codigo?: string; programa_codigo?: string; situacao?: string;
  beneficiario_nome?: string; beneficiario_cnpj?: string; uf?: string;
  politicas_publicas?: string; emenda_codigo?: string; valor_total?: number;
  objeto_descricao?: string;
}
interface Voluntaria {
  numero_proposta?: string; situacao?: string; proponente?: string;
  municipio?: string; uf?: string; ano?: number; objeto?: string;
  valor_global?: number | null; valor_repasse?: number | null;
  nr_convenio?: string | null; situacao_convenio?: string | null;
  valor_desembolsado?: number | null;
  dt_assinatura?: string | null; dt_fim_vigencia?: string | null;
}
interface Resp {
  cnpj: string;
  /** false = o tenant NÃO tem o módulo SICONV (padrão do produto; hoje só a
   *  Freitas liga). A flag vem no payload de propósito — decidir por build-arg
   *  criaria um build de frontend por cliente para esconder UMA seção. Sem o
   *  campo (API antiga), trata como ligado. */
  siconv_module?: boolean;
  especiais: Especial[]; voluntarias: Voluntaria[];
  total_especiais: number; total_voluntarias: number;
}

function maskCnpj(v: string): string {
  const d = v.replace(/\D/g, "").slice(0, 14);
  return d
    .replace(/^(\d{2})(\d)/, "$1.$2")
    .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
    .replace(/\.(\d{3})(\d)/, ".$1/$2")
    .replace(/(\d{4})(\d)/, "$1-$2");
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "-";
  try {
    return new Date(iso).toLocaleDateString("pt-BR", { timeZone: "UTC" });
  } catch {
    return iso.slice(0, 10);
  }
}

/** Fim de vigencia so vira alerta quando ainda da para AGIR: vencendo nos
 *  proximos 60 dias. Data ja vencida nao e pintada de proposito — esta consulta
 *  devolve o historico inteiro do CNPJ (ate 800 propostas, muitas dos anos
 *  2000), e pintar todas de vermelho e o mesmo que nao pintar nenhuma. */
function vigenciaTom(iso?: string | null): "normal" | "atencao" {
  if (!iso) return "normal";
  const fim = new Date(iso).getTime();
  if (Number.isNaN(fim)) return "normal";
  const dias = Math.ceil((fim - Date.now()) / 86_400_000);
  return dias >= 0 && dias <= 60 ? "atencao" : "normal";
}

/** O ANO escondido dentro de um CÓDIGO.
 *
 *  Mesma leitura que o backend faz (`_ano_de`, em `services/rm_builder.py`),
 *  com a mesma pegadinha: a busca ingênua por `20\d{2}` acha "2097" no MIOLO
 *  de "042097/2015" e data a proposta num ano futuro absurdo. Por isso o ano
 *  DEPOIS DA BARRA tem prioridade e, na falta dele, só vale um ano plausível
 *  (não passa de dois anos à frente de hoje). */
function anoDeCodigo(...vals: Array<string | null | undefined>): string {
  const lim = new Date().getFullYear() + 2;
  for (const v of vals) {
    if (!v) continue;
    const barra = /\/\s*((?:19|20)\d{2})\b/.exec(v);
    if (barra) return barra[1];
    for (const cand of v.match(/(?:19|20)\d{2}/g) ?? []) {
      const y = Number(cand);
      if (y >= 2000 && y <= lim) return cand;
    }
  }
  return "";
}

/** O ano de um PLANO DE AÇÃO (Transferência Especial).
 *
 *  Esta lista não tem campo de data nenhum: a API pública do TransfereGov
 *  devolve só códigos e situação. O ano do registro é o da EMENDA que o
 *  originou — `emenda_codigo` chega como "202135950005-Lincoln Portela", e os
 *  quatro primeiros dígitos são o exercício. O código do plano entra como
 *  segunda opção. É a MESMA regra que o backend usa para datar Transferência
 *  Especial no relatório mensal, então as duas telas concordam. */
function anoEsp(e: Especial): string {
  return anoDeCodigo(e.emenda_codigo, e.codigo);
}

/** O ano de uma proposta VOLUNTÁRIA: o `ano` do SICONV — o exercício da
 *  proposta, que é por onde o próprio backend ordena a consulta. Não se usa
 *  aqui a data de assinatura: uma proposta de 2024 assinada em 2025 é de 2024
 *  para quem presta contas. */
function anoVol(v: Voluntaria): string {
  return v.ano ? String(v.ano) : "";
}

/** Agrupa por ano, do mais recente para o mais antigo, com "Sem ano" no FIM.
 *
 *  Registro sem ano legível NÃO some: esconder um plano de ação porque o
 *  código da emenda veio fora do padrão é pior que mostrá-lo separado. */
function agruparPorAno<T>(itens: T[], ano: (x: T) => string): Array<[string, T[]]> {
  const m = new Map<string, T[]>();
  for (const it of itens) {
    const a = ano(it) || "Sem ano";
    (m.get(a) ?? m.set(a, []).get(a)!).push(it);
  }
  return Array.from(m.entries()).sort((x, y) =>
    x[0] === "Sem ano" ? 1 : y[0] === "Sem ano" ? -1 : y[0].localeCompare(x[0]));
}

export default function TransfereGovCnpjPage() {
  const [cnpj, setCnpj] = useState("");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [data, setData] = useState<Resp | null>(null);
  const [selVol, setSelVol] = useState<Voluntaria | null>(null);
  const [selEsp, setSelEsp] = useState<Especial | null>(null);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  /* Recolhido por ANO, um conjunto POR LISTA. Guarda o que está FECHADO e não
     o que está aberto: assim um ano novo que apareça na próxima consulta nasce
     aberto. Conjuntos separados porque fechar 2024 nos planos de ação não tem
     por que fechar 2024 nas voluntárias. */
  const [espFechados, setEspFechados] = useState<Set<string>>(new Set());
  const [volFechados, setVolFechados] = useState<Set<string>>(new Set());

  /** Os anos que EXISTEM no resultado — união das duas listas, para o dropdown
   *  não oferecer ano sem registro nenhum. */
  const anosDisponiveis = useMemo(() => {
    if (!data) return [];
    const s = new Set<string>();
    for (const e of data.especiais) { const a = anoEsp(e); if (a) s.add(a); }
    for (const v of data.voluntarias) { const a = anoVol(v); if (a) s.add(a); }
    return Array.from(s).sort((a, b) => b.localeCompare(a));
  }, [data]);
  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anosDisponiveis, setAnosSel);

  /* O filtro de ano vale para AS DUAS listas, cada uma pelo SEU campo de ano
     (a emenda no plano de ação, o exercício da proposta na voluntária) — que é
     o mesmo campo pelo qual ela se agrupa logo abaixo. Marcar 2025 nunca faz
     aparecer um grupo 2024. */
  const especiais = useMemo(() => {
    const todas = data?.especiais ?? [];
    return anosSel.length ? todas.filter((e) => anosSel.includes(anoEsp(e))) : todas;
  }, [data, anosSel]);
  const voluntarias = useMemo(() => {
    const todas = data?.voluntarias ?? [];
    return anosSel.length ? todas.filter((v) => anosSel.includes(anoVol(v))) : todas;
  }, [data, anosSel]);

  const porAnoEsp = useMemo(() => agruparPorAno(especiais, anoEsp), [especiais]);
  const porAnoVol = useMemo(() => agruparPorAno(voluntarias, anoVol), [voluntarias]);

  /** Recolher/expandir um ano. */
  const alternarAno = (
    set: React.Dispatch<React.SetStateAction<Set<string>>>,
    ano: string,
  ) =>
    set((prev) => {
      const n = new Set(prev);
      if (n.has(ano)) n.delete(ano); else n.add(ano);
      return n;
    });

  // Os totais em dinheiro que os KPIs mostram, no MESMO recorte das listas: se
  // o filtro de ano estivesse ligado e os cards continuassem somando a base
  // inteira, a tela se contradiria sozinha. Sem filtro a conta e a de antes —
  // o endpoint devolve as duas listas inteiras, entao somar aqui nao mente.
  const resumo = useMemo(() => {
    if (!data) return null;
    return {
      valEsp: especiais.reduce((s, e) => s + (e.valor_total ?? 0), 0),
      valVol: voluntarias.reduce((s, v) => s + (v.valor_repasse ?? v.valor_global ?? 0), 0),
      pagoVol: voluntarias.reduce((s, v) => s + (v.valor_desembolsado ?? 0), 0),
    };
  }, [data, especiais, voluntarias]);

  /* Módulo ausente NÃO é resultado vazio: onde o SICONV não existe, a seção de
     voluntárias, os 2 KPIs dela e a menção no subtítulo SOMEM — mostrar
     "0 convênios" num tenant sem a base leria como defeito ou como "procurei e
     não achei", e nenhum dos dois é verdade. Antes da primeira consulta a flag
     é desconhecida e assume ligado (só afeta o subtítulo, e se corrige na
     primeira resposta). */
  const siconvOn = data?.siconv_module !== false;

  const consultar = async () => {
    const digits = cnpj.replace(/\D/g, "");
    if (digits.length !== 14) { setErro("Informe um CNPJ com 14 dígitos."); return; }
    setLoading(true); setErro(null);
    // Anos do CNPJ ANTERIOR nao valem para o proximo: um 2019 marcado que o
    // novo CNPJ nao tem esvaziaria as duas listas e pareceria "sem resultado".
    setAnosSel([]);
    try {
      const r = await api.get<Resp>("/transferegov/por-cnpj", { params: { cnpj: digits } });
      setData(r.data);
    } catch (e: unknown) {
      setErro((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro na consulta.");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <Building2 className="size-6" style={{ color: "var(--bi-muted)" }} /> Consulta TransfereGov por CNPJ
        </h1>
        <p className="text-sm" style={{ color: "var(--bi-muted)" }}>
          {siconvOn
            ? "Busca por CNPJ do proponente — Transferência Especial (Plano de Ação, ao vivo) + Voluntárias (dados já coletados). Não entra em relatório."
            : "Busca por CNPJ do proponente — Transferência Especial (Plano de Ação, ao vivo). Não entra em relatório."}
        </p>
      </div>

      {/* Barra de consulta */}
      <Bloco className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
              CNPJ do proponente
            </label>
            <Input
              value={cnpj}
              onChange={(e) => setCnpj(maskCnpj(e.target.value))}
              onKeyDown={(e) => e.key === "Enter" && consultar()}
              placeholder="00.000.000/0000-00"
              className="w-56 font-mono"
            />
          </div>
          {/* Sem `bg-primary` na mão: a variante padrão do Button já é
              `btn-primary`, e a classe só repintava por cima. */}
          <Button onClick={consultar} disabled={loading}>
            {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <SearchIcon className="size-4 mr-1" />}
            Consultar
          </Button>
          {/* O filtro de ano só existe DEPOIS da consulta: os anos são os que o
              CNPJ tem, não uma lista fixa. Um dropdown vazio antes de buscar
              seria um controle que não faz nada. */}
          {anosDisponiveis.length > 0 && (
            <div>
              <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Anos
              </label>
              <MultiSelect
                opcoes={anosDisponiveis}
                valor={anosSel}
                onChange={setAnosSel}
                atalhos={atalhosAnos()}
                formatarResumo={resumoAnos}
                placeholder="Todos os anos"
                rotuloTodos="Todos os anos"
                ariaLabel="Anos"
                className="w-52"
              />
            </div>
          )}
        </div>
      </Bloco>

      {/* Erro e alerta de verdade: aqui a cor tem significado, e vem do token
          critico — nao das classes decorativas de antes. */}
      {erro && (
        <div className="bi-card-flat px-3 py-2.5 text-[12px]" style={{ color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {data && resumo && (
        <div className="space-y-4">
          {/* Os cabecalhos das duas tabelas so contavam resultado. Viram KPI:
              quantidade E dinheiro, que e a pergunta que o gestor faz primeiro. */}
          {/* Classes completas nos DOIS ramos — classe montada em runtime o
              Tailwind não enxerga e falha calada. */}
          <div className={siconvOn ? "grid grid-cols-2 gap-3 lg:grid-cols-4" : "grid grid-cols-2 gap-3"}>
            <Numero
              icon={Landmark}
              rotulo="Planos de ação"
              valor={especiais.length}
              sub="Transferência Especial (ao vivo)"
            />
            <Numero
              icon={Coins}
              rotulo="Valor em planos de ação"
              valor={formatCurrency(resumo.valEsp)}
              sub={formatCurrency(resumo.valEsp)}
            />
            {siconvOn && (
              <>
                <Numero
                  icon={FileText}
                  rotulo="Propostas voluntárias"
                  valor={voluntarias.length}
                  sub="SICONV — base federal"
                />
                <Numero
                  icon={Wallet}
                  rotulo="Repasse (voluntárias)"
                  valor={formatCurrency(resumo.valVol)}
                  sub={`pago ${formatCurrency(resumo.pagoVol)}`}
                />
              </>
            )}
          </div>

          {/* AS DUAS TABELAS VIRARAM LISTA.
              Cada bloco e um grupo na gramatica do Painel (cabecalho com
              contagem e total a direita) e cada registro e um cartao sem borda.
              As colunas nao sumiram: as que se comparam entre linhas foram para
              <Campos>, em posicao FIXA, para o olho continuar descendo em
              coluna como descia na tabela; as que servem para identificar
              foram para a meta.

              E AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO por ANO
              -> itens cinza dentro. O branco DEIXOU de ser da secao e passou a
              ser do ano — manter os dois seria branco sobre branco e achataria
              a hierarquia. O cabecalho da secao nao perdeu nada (titulo,
              contagem e total continuam), so passou a ficar direto sobre o
              fundo da pagina. */}
          <section className="space-y-3">
            <BlocoHead
              icon={Landmark}
              titulo="Transferência Especial (Plano de Ação)"
              sub={`${especiais.length}${anosSel.length ? ` de ${data.total_especiais}` : ""} resultado(s) · consulta ao vivo no TransfereGov`}
              right={<span className="bi-num text-[13px]">{formatCurrency(resumo.valEsp)}</span>}
              className="mb-0"
            />
            {especiais.length === 0 ? (
              <Vazio>
                {data.especiais.length === 0
                  ? "Nenhum plano de ação para este CNPJ."
                  : "Nenhum plano de ação nos anos selecionados."}
              </Vazio>
            ) : (
              porAnoEsp.map(([ano, doAno]) => {
                const fechado = espFechados.has(ano);
                const totalAno = doAno.reduce((s, e) => s + (e.valor_total ?? 0), 0);
                return (
                  <Bloco key={ano} className="p-3">
                    <button type="button" onClick={() => alternarAno(setEspFechados, ano)}
                            className="text-left" aria-expanded={!fechado}>
                      <BlocoHead
                        icon={fechado ? ChevronRight : ChevronDown}
                        titulo={ano}
                        sub={`${doAno.length} plano(s) de ação`}
                        right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                        className={fechado ? "mb-0" : undefined}
                      />
                    </button>
                    {!fechado && (
                      <Lista>
                        {doAno.map((e, i) => {
                          // O objeto e quem descreve o plano. Quando o TransfereGov nao
                          // manda objeto, a politica publica assume o titulo — e nesse
                          // caso nao se repete na meta logo abaixo.
                          const titulo = e.objeto_descricao
                            || e.politicas_publicas
                            || `Plano de ação ${e.codigo || ""}`.trim();
                          return (
                            <ItemLinha
                              key={e.id ?? i}
                              onClick={() => setSelEsp(e)}
                              titulo={titulo}
                              valor={formatCurrency(e.valor_total)}
                              meta={
                                <>
                                  {e.situacao && (
                                    <Selo tom={situacaoTom(e.situacao)} title={e.situacao}>{e.situacao}</Selo>
                                  )}
                                  {e.beneficiario_nome && (
                                    <span className="truncate" title={e.beneficiario_nome}>{e.beneficiario_nome}</span>
                                  )}
                                  {e.politicas_publicas && e.politicas_publicas !== titulo && (
                                    <span className="truncate" title={e.politicas_publicas}>
                                      · {e.politicas_publicas}
                                    </span>
                                  )}
                                </>
                              }
                            >
                              {/* Estes quatro sao TEXTO numa celula que trunca, entao
                                  cada um leva `title`: o codigo da emenda vem com o nome
                                  do parlamentar colado ("202135950005-Lincoln Portela") e
                                  era justamente essa parte que o corte comia, sem nenhum
                                  jeito de recuperar. Todas as outras telas do lote ja
                                  dao `title` em campo de texto. */}
                              <Campos
                                campos={[
                                  { rotulo: "Código", valor: e.codigo || "—", title: e.codigo || undefined },
                                  { rotulo: "Programa", valor: e.programa_codigo || "—",
                                    title: e.programa_codigo || undefined },
                                  { rotulo: "Emenda", valor: e.emenda_codigo || "—",
                                    title: e.emenda_codigo || undefined },
                                  { rotulo: "UF", valor: e.uf || "—" },
                                ]}
                              />
                            </ItemLinha>
                          );
                        })}
                      </Lista>
                    )}
                  </Bloco>
                );
              })
            )}
          </section>

          {/* Mesmo desenho da secao de cima, com o ANO DESTA lista: aqui ele vem
              do exercicio da proposta no SICONV, nao do codigo da emenda.
              A secao INTEIRA so existe onde o modulo SICONV existe. */}
          {siconvOn && (
          <section className="space-y-3">
            <BlocoHead
              icon={Landmark}
              titulo="Voluntárias / Convênios (SICONV — base federal)"
              sub={`${voluntarias.length}${anosSel.length ? ` de ${data.total_voluntarias}` : ""} resultado(s) · dados já coletados`}
              right={<span className="bi-num text-[13px]">{formatCurrency(resumo.valVol)}</span>}
              className="mb-0"
            />
            {voluntarias.length === 0 ? (
              <Vazio>
                {data.voluntarias.length === 0
                  ? "Nenhuma proposta voluntária deste CNPJ nos dados já coletados."
                  : "Nenhuma proposta voluntária nos anos selecionados."}
              </Vazio>
            ) : (
              porAnoVol.map(([ano, doAno]) => {
                const fechado = volFechados.has(ano);
                // Mesma base do valor mostrado em cada item e do KPI de repasse.
                const totalAno = doAno.reduce((s, v) => s + (v.valor_repasse ?? v.valor_global ?? 0), 0);
                return (
                  <Bloco key={ano} className="p-3">
                    <button type="button" onClick={() => alternarAno(setVolFechados, ano)}
                            className="text-left" aria-expanded={!fechado}>
                      <BlocoHead
                        icon={fechado ? ChevronRight : ChevronDown}
                        titulo={ano}
                        sub={`${doAno.length} proposta(s)`}
                        right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                        className={fechado ? "mb-0" : undefined}
                      />
                    </button>
                    {!fechado && (
                      <Lista>
                        {doAno.map((v, i) => {
                          // Mesma conta da coluna "Repasse": quando nao ha repasse
                          // informado, o global e a base — inclusive para o % pago.
                          const base = v.valor_repasse ?? v.valor_global ?? 0;
                          const pago = v.valor_desembolsado;
                          const pct = pago != null && base ? Math.round((pago / base) * 100) : null;
                          return (
                            <ItemLinha
                              key={(v.numero_proposta ?? "") + i}
                              onClick={() => setSelVol(v)}
                              titulo={v.objeto || "Sem objeto informado"}
                              valor={formatCurrency(v.valor_repasse ?? v.valor_global)}
                              meta={
                                <>
                                  {v.situacao && (
                                    <Selo tom={situacaoTom(v.situacao)} title={`Proposta: ${v.situacao}`}>
                                      {v.situacao}
                                    </Selo>
                                  )}
                                  {v.situacao_convenio && (
                                    <Selo tom={situacaoTom(v.situacao_convenio)} title={`Convênio: ${v.situacao_convenio}`}>
                                      {v.situacao_convenio}
                                    </Selo>
                                  )}
                                  {v.municipio && <span>{`${v.municipio}/${v.uf || ""}`}</span>}
                                  {/* Proposta e convenio servem para ACHAR o registro,
                                      nao para comparar — por isso ficam na meta e nao
                                      ocupam coluna na grade. */}
                                  <span className="font-mono">
                                    {v.numero_proposta ? `· prop ${v.numero_proposta}` : ""}
                                    {v.nr_convenio ? ` · conv ${v.nr_convenio}` : ""}
                                  </span>
                                </>
                              }
                            >
                              <Campos
                                campos={[
                                  { rotulo: "Ano", valor: v.ano ?? "—" },
                                  {
                                    rotulo: "Valor global",
                                    valor: v.valor_global != null ? formatCurrency(v.valor_global) : "—",
                                  },
                                  {
                                    rotulo: "Pago",
                                    valor: pago != null ? formatCurrency(pago) : "—",
                                    tom: pct == null ? "normal" : pct >= 100 ? "ok" : pct > 0 ? "atencao" : "normal",
                                    title: pct != null ? `${pct}% de ${formatCurrency(base)}` : "Sem informação de desembolso",
                                  },
                                  { rotulo: "Assinatura", valor: fmtDate(v.dt_assinatura) },
                                  {
                                    rotulo: "Fim da vigência",
                                    valor: fmtDate(v.dt_fim_vigencia),
                                    tom: vigenciaTom(v.dt_fim_vigencia),
                                  },
                                ]}
                              />
                            </ItemLinha>
                          );
                        })}
                      </Lista>
                    )}
                  </Bloco>
                );
              })
            )}
          </section>
          )}
        </div>
      )}

      {/* Modal Voluntaria / Convenio */}
      {selVol && (
        <Modal aberto onFechar={() => setSelVol(null)} maxW="max-w-2xl">
          <ModalHead
            titulo={`Proposta ${selVol.numero_proposta || ""}`}
            sub={selVol.situacao}
            onFechar={() => setSelVol(null)}
          />
          <ModalCorpo>
            <Secao
              icon={FileText}
              titulo="Proposta e convênio"
              campos={[
                campoC("Nº Proposta", selVol.numero_proposta, { mono: true }),
                campoC("Ano", selVol.ano),
                campoC("Situação da proposta", selVol.situacao, { span: 2 }),
                campoC("Proponente", selVol.proponente, { span: 2 }),
                campoC("Município / UF", selVol.municipio ? `${selVol.municipio}/${selVol.uf || ""}` : null),
                campoC("Nº Convênio", selVol.nr_convenio, { mono: true }),
                campoC("Situação do convênio", selVol.situacao_convenio, { span: 2 }),
                { rotulo: "Valor global", valor: formatCurrency(selVol.valor_global) },
                { rotulo: "Valor repasse", valor: formatCurrency(selVol.valor_repasse) },
                campoC("Valor desembolsado (pago)", selVol.valor_desembolsado != null ? formatCurrency(selVol.valor_desembolsado) : null),
                campoC("Assinatura", fmtDate(selVol.dt_assinatura)),
                campoC("Fim da vigência", fmtDate(selVol.dt_fim_vigencia)),
              ]}
            >
              {/* Objeto fora da grade: e texto livre e a celula trunca por desenho. */}
              <div className="mt-2.5">
                <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Objeto</div>
                <p className="mt-0.5 text-[12px] leading-relaxed break-words whitespace-pre-wrap" style={{ color: "var(--bi-text)" }}>
                  {selVol.objeto || "-"}
                </p>
              </div>
            </Secao>
          </ModalCorpo>
        </Modal>
      )}

      {/* Modal Especial / Plano de Acao */}
      {selEsp && (
        <Modal aberto onFechar={() => setSelEsp(null)} maxW="max-w-2xl">
          <ModalHead
            titulo={`Plano de Ação ${selEsp.codigo || ""}`}
            sub={selEsp.situacao}
            onFechar={() => setSelEsp(null)}
          />
          <ModalCorpo>
            <Secao
              icon={Landmark}
              titulo="Plano de ação"
              campos={[
                campoC("Código", selEsp.codigo, { mono: true }),
                campoC("Programa", selEsp.programa_codigo, { mono: true }),
                campoC("Situação", selEsp.situacao, { span: 2 }),
                campoC("Beneficiário", selEsp.beneficiario_nome),
                campoC("CNPJ", selEsp.beneficiario_cnpj ? maskCnpj(selEsp.beneficiario_cnpj) : null, { mono: true }),
                campoC("UF", selEsp.uf),
                campoC("Emenda", selEsp.emenda_codigo, { mono: true }),
                { rotulo: "Valor total", valor: formatCurrency(selEsp.valor_total) },
                campoC("Políticas públicas", selEsp.politicas_publicas, { span: 2, quebra: true }),
              ]}
            >
              <div className="mt-2.5">
                <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Objeto</div>
                <p className="mt-0.5 text-[12px] leading-relaxed break-words whitespace-pre-wrap" style={{ color: "var(--bi-text)" }}>
                  {selEsp.objeto_descricao || "-"}
                </p>
              </div>
            </Secao>
          </ModalCorpo>
        </Modal>
      )}
    </div>
  );
}

