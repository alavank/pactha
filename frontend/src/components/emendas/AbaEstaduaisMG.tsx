"use client";

import React, { useEffect, useState, useCallback, useMemo, useRef } from "react";
import { ChevronLeft, ChevronRight, Search as SearchIcon, ChevronDown, ChevronUp, Users } from "lucide-react";
import api from "@/lib/api";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/multi-select";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, situacaoTom } from "@/components/ui/superficies";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { formatDataHora, horasDesde } from "@/lib/bi-format";
import { fonteEmendasEstaduais, NOME_UF } from "@/lib/estadual";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency } from "@/lib/utils";

/** Os tres tipos que o SIGCON usa na indicacao. Ficam aqui como lista fixa
 *  porque o backend compara com ILIKE por item — acento e caixa nao importam,
 *  e a lista nao muda sem mudanca normativa. */
const TIPOS_INDICACAO = [
  "Transferência Especial",
  "Aplicação Direta",
  "Convênio",
  // Só os dados da SEGOV trazem (24/09/2026): o fundo a fundo da saúde por emenda.
  "Resolução SES",
];

interface Emenda {
  id: number;
  municipio_id: number;
  nr_indicacao?: string;
  nome_responsavel?: string;
  tipo_indicacao?: string;
  uo_codigo?: string;
  uo_sigla?: string;
  cnpj_beneficiario?: string;
  beneficiario?: string;
  grupo_despesa?: string;
  tipo_atendimento?: string;
  valor_indicacao?: number;
  status_indicacao?: string;
  ano?: number;
  /** Convênio relacionado, casado pelo nº da indicação (#3). Vazio até o
   *  scraper (#2) popular a indicação no convênio. */
  conv_nr?: string | null;
  conv_objeto?: string | null;
  /** Execução pelos dados abertos da SEGOV (dados.mg.gov.br). `null` = a
   *  fonte não trouxe esta indicação; 0 = a SEGOV afirmou zero. */
  valor_empenhado?: number | null;
  valor_pago?: number | null;
  execucao_em?: string | null;
}

interface Stats {
  total: number; valor_total: number; responsaveis: number; aprovadas: number;
  valor_pago?: number | null; com_execucao?: number; execucao_em?: string | null;
}

/** "2026-05-12" -> "12/05/2026" (sem fuso: é uma data, não um instante). */
function diaBR(iso?: string | null): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

/** A planilha do site da SEGOV ficou de 12/05 a 24/09/2026 sem ser regerada: passou de
 *  90 dias, o "pago" dela está defasado e a tela precisa dizer. */
function planilhaVelha(iso?: string | null): boolean {
  if (!iso) return false;
  const dias = (Date.now() - new Date(`${iso.slice(0, 10)}T00:00:00`).getTime()) / 86400000;
  return dias > 90;
}

const PER_PAGE = 100; // todos por ano

function siglaTipo(t?: string): string {
  if (!t) return "-";
  const u = t.toUpperCase();
  if (u.includes("TRANSFER") && u.includes("ESPECIAL")) return "TE";
  if (u.includes("APLICA")) return "AD";
  if (u.includes("CONV")) return "CV";
  if (u.includes("RESOLU")) return "SES";
  return t.slice(0, 4).toUpperCase();
}

/** `onAbrir` (17/09/2026): na tela de Emendas parlamentares a indicação abre o
 *  detalhe com o parlamentar e o CONVÊNIO que ela gerou — o que a linha não
 *  mostrava inteiro. */
export default function EmendasEstaduaisPage({ onAbrir }: { onAbrir?: (id: number) => void } = {}) {
  const { municipioId } = useMunicipio();
  // A UF do município aberto decide o nome da fonte. `""` = ainda não sei —
  // o hook devolve isso de propósito, e não "MG", para a tela não afirmar nada
  // enquanto carrega.
  const ufAmbiente = useUfDoMunicipio();
  const fonteEmendas = fonteEmendasEstaduais(ufAmbiente);

  const [items, setItems] = useState<Emenda[]>([]);
  const [loading, setLoading] = useState(true);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [responsavel, setResponsavel] = useState("");
  const [tiposSel, setTiposSel] = useState<string[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [anos, setAnos] = useState<number[]>([]);
  const [collapsedYears, setCollapsedYears] = useState<Set<number>>(new Set());
  // Frescor da coleta SIGCON (as emendas vem do mesmo scrape dos convenios).
  const [coleta, setColeta] = useState<{ em: string | null; falhas: number }>({ em: null, falhas: 0 });

  useEffect(() => {
    if (!municipioId) return;
    api.get<number[]>("/emendas-estaduais/anos", { params: { municipio_id: municipioId } })
      .then((r) => setAnos(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, [municipioId]);

  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anos, setAnosSel);

  // Mesma guarda de corrida da tela de Convênios: só a resposta mais recente
  // assenta, e a troca de município zera o estado (senão o selo de frescor do
  // município anterior fica na tela durante o loading).
  const reqSeq = useRef(0);
  useEffect(() => {
    setItems([]);
    setColeta({ em: null, falhas: 0 });
  }, [municipioId]);

  const fetchData = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    // `string[]` no tipo porque anos e tipos agora vao como lista repetida na
    // querystring (?anos=2025&anos=2024), que e o formato que o FastAPI espera.
    const params: Record<string, string | number | string[]> = {
      municipio_id: municipioId,
      page: 1,
      per_page: 500, // todos pra agrupar por ano
    };
    if (anosSel.length) params.anos = anosSel;
    if (responsavel) params.responsavel = responsavel;
    if (tiposSel.length) params.tipos = tiposSel;
    const seq = ++reqSeq.current;
    api.get<{ items: Emenda[]; total: number; coleta_em?: string | null; coleta_falhas?: number }>("/emendas-estaduais", { params })
      .then((r) => {
        if (seq !== reqSeq.current) return;
        setItems(r.data.items || []);
        setColeta({ em: r.data.coleta_em ?? null, falhas: r.data.coleta_falhas ?? 0 });
      })
      .catch(() => {})
      .finally(() => setLoading(false));

    // MESMO recorte da tabela. Mandar so quando ha um ano ("=== 1") fazia os
    // cards do topo somarem a base inteira enquanto a lista abaixo mostrava o
    // mandato — a tela se contradizendo sozinha.
    api.get("/emendas-estaduais/stats", { params: { municipio_id: municipioId, ...(anosSel.length ? { anos: anosSel } : {}) } })
      .then((r) => setStats(r.data as never))
      .catch(() => {});
  }, [municipioId, anosSel, responsavel, tiposSel]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Agrupa por ano (DESC)
  const grouped = useMemo(() => {
    const map = new Map<number, Emenda[]>();
    items.forEach((e) => {
      const y = e.ano ?? 0;
      if (!map.has(y)) map.set(y, []);
      map.get(y)!.push(e);
    });
    return Array.from(map.entries()).sort((a, b) => b[0] - a[0]);
  }, [items]);

  const toggleYear = (y: number) => {
    setCollapsedYears((prev) => {
      const next = new Set(prev);
      if (next.has(y)) next.delete(y);
      else next.add(y);
      return next;
    });
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um município.</div>;
  }

  // ⚠️ Mesmo conserto do `dashboard/convenios`: `pactha_token` é apagado do
  // localStorage no primeiro refresh, e `Bearer null` ATROPELA o cookie bom no
  // backend (o Bearer é lido antes). Pelo `api` vai o cookie e há retry.
  const exportPdf = async () => {
    try {
      const r = await api.get("/export-pdf/emendas", {
        params: { municipio_id: municipioId },
        responseType: "blob",
      });
      const u = URL.createObjectURL(r.data as Blob);
      window.open(u, "_blank");
      setTimeout(() => URL.revokeObjectURL(u), 60000);
    } catch {
      alert("Não foi possível gerar o PDF. Tente novamente.");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          {/* h2 e não TituloTela: desde 17/09/2026 isto é uma ABA de «Emendas
              parlamentares», e o título da tela é o de lá. */}
          <h2 className="text-[15px] font-semibold">Emendas estaduais</h2>
          {/* ⚠️ O NOME DA FONTE VEM DO MAPA POR UF, nunca de literal. O texto
              dizia "SIGCON-MG" fixo — e essa tela abre para qualquer cliente,
              inclusive um do Rio Grande do Sul, onde o SIGCON não existe e as
              emendas estaduais nem sequer são impositivas. Sem fonte na UF, a
              tela diz o que é verdade: que aquele estado ainda não é coletado.

              Por que a primeira frase existe: as telas do TransfereGov abrem um
              modal no olhinho, e o gestor procurou o olhinho aqui. Não há —
              porque não há o que abrir: a fonte publica treze campos por
              indicação e os treze já estão na linha. Sem esta frase, a ausência
              do ícone se lê como "o detalhe ainda não carregou". */}
          {fonteEmendas && onAbrir ? (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Clique numa indicação para ver o parlamentar e o convênio que ela gerou.
            </p>
          ) : fonteEmendas ? (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Cada indicação já mostra todos os campos publicados pelo {fonteEmendas} — não há
              detalhamento adicional a abrir.
            </p>
          ) : (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              {ufAmbiente
                ? `As emendas parlamentares estaduais ${NOME_UF[ufAmbiente] ? `de ${NOME_UF[ufAmbiente]}` : `de ${ufAmbiente}`} ainda não são coletadas por este sistema.`
                : "A fonte de emendas estaduais deste estado ainda não é coletada por este sistema."}
            </p>
          )}
          {/* Frescor da coleta — mesma regra da tela de Convênios: com a coleta
              falhando, avisa SEM afirmar causa e sem datar (o carimbo seria a
              hora do último erro). */}
          {municipioId && (coleta.falhas > 0 ? (
            <p className="text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>
              não foi possível concluir a última coleta no portal do Estado
              {items.length > 0 ? " — exibindo os últimos dados obtidos" : ""}
            </p>
          ) : coleta.em ? (
            <p
              className="text-[11px]"
              style={{ color: (horasDesde(coleta.em) ?? 0) > 26 ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}
              title={(horasDesde(coleta.em) ?? 0) > 26 ? "Sem coleta nova há mais de um dia" : undefined}
            >
              Atualizado em {formatDataHora(coleta.em)}
            </p>
          ) : null)}
          {/* ⚠️ A DATA DOS DADOS, e não a da coleta: a SEGOV pode ficar meses
              sem atualizar o arquivo, e "pago R$ 0" de um arquivo de maio não é
              "não foi pago". */}
          {stats?.execucao_em && (
            <p className="text-[11px]"
               style={{ color: planilhaVelha(stats.execucao_em) ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}>
              Empenhado e pago: dados abertos da SEGOV (dados.mg.gov.br) atualizados
              de {diaBR(stats.execucao_em)}
              {planilhaVelha(stats.execucao_em) ? " — o Estado não os atualiza desde então" : ""}
            </p>
          )}
        </div>
        <Button onClick={exportPdf} size="sm" variant="outline" title="Exportar para PDF">
          📄 PDF
        </Button>
      </div>

      {stats && (
        <div className={`grid gap-3 ${stats.execucao_em ? "grid-cols-2 lg:grid-cols-5" : "grid-cols-4"}`}>
          <StatCard label="Total Indicações" value={stats.total.toLocaleString("pt-BR")} />
          <StatCard label="Valor Total Indicado" value={formatCurrency(stats.valor_total)} />
          <StatCard label="Parlamentares" value={stats.responsaveis.toString()} />
          <StatCard label="Aprovadas" value={stats.aprovadas.toLocaleString("pt-BR")} />
          {stats.execucao_em && (
            <StatCard label={`Pago até ${diaBR(stats.execucao_em)}`}
                      value={stats.valor_pago == null ? "—" : formatCurrency(stats.valor_pago)} />
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <MultiSelect
          opcoes={anos.map(String)}
          valor={anosSel}
          onChange={setAnosSel}
          atalhos={atalhosAnos()}
          formatarResumo={resumoAnos}
          placeholder="Todos os anos"
          rotuloTodos="Todos os anos"
          ariaLabel="Anos"
          className="w-44"
        />

        <MultiSelect
          opcoes={TIPOS_INDICACAO}
          valor={tiposSel}
          onChange={setTiposSel}
          placeholder="Todos os tipos"
          rotuloTodos="Todos os tipos"
          ariaLabel="Tipo de indicação"
          className="w-60"
        />

        <div className="relative flex-1 min-w-[200px]">
          <SearchIcon className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por responsável (parlamentar)..."
            value={responsavel}
            onChange={(e) => setResponsavel(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded bg-base-200" />)}
        </div>
      ) : grouped.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhuma emenda encontrada.
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map(([y, list]) => {
            const isCollapsed = collapsedYears.has(y);
            const totalAno = list.reduce((s, e) => s + (e.valor_indicacao ?? 0), 0);
            return (
              /* Grupo por ano, na gramatica do Painel: um bloco com cabecalho
                 (titulo, contagem, total a direita) e a lista de itens dentro.
                 E a mesma estrutura que o Painel usa para agrupar lancamentos
                 por parlamentar. */
              <Bloco key={y} className="p-3">
                <button onClick={() => toggleYear(y)} className="text-left">
                  <BlocoHead
                    icon={isCollapsed ? ChevronRight : ChevronDown}
                    titulo={y || "Sem ano"}
                    sub={`${list.length} indicação(ões)`}
                    right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                    className={isCollapsed ? "mb-0" : undefined}
                  />
                </button>
                {!isCollapsed && (
                  <Lista>
                    {list.map((em) => (
                      <ItemLinha
                        key={em.id}
                        onClick={onAbrir ? () => onAbrir(em.id) : undefined}
                        titulo={em.tipo_atendimento || em.beneficiario || "Indicação"}
                        valor={formatCurrency(em.valor_indicacao)}
                        meta={
                          <>
                            {/* ⭐ O Nº DA INDICAÇÃO ABRE A META, e não fecha.
                                Duas emendas do mesmo objeto e do mesmo valor —
                                caso comum quando vários parlamentares bancam o
                                mesmo ônibus escolar — só se distinguem por ele,
                                e ele estava no FIM da linha, depois de tipo,
                                status, responsável e beneficiário: na prática,
                                invisível. O dono leu a lista como repetida (e
                                em parte estava mesmo: ver a correção de chave
                                em fix_duplicatas_chave_natural.sql). */}
                            {em.nr_indicacao && (
                              <span className="shrink-0 font-mono" style={{ color: "var(--bi-muted)" }}>
                                nº {em.nr_indicacao}
                              </span>
                            )}
                            {em.tipo_indicacao && (
                              <Selo title={em.tipo_indicacao}>{siglaTipo(em.tipo_indicacao)}</Selo>
                            )}
                            {em.status_indicacao && (
                              <Selo tom={situacaoTom(em.status_indicacao)} title={em.status_indicacao}>
                                {em.status_indicacao}
                              </Selo>
                            )}
                            {em.nome_responsavel && (
                              <span className="font-medium" style={{ color: "var(--bi-muted)" }}>
                                {em.nome_responsavel}
                              </span>
                            )}
                            {em.beneficiario && <span className="truncate">→ {em.beneficiario}</span>}
                            <span className="font-mono">
                              {em.cnpj_beneficiario ? `· CNPJ ${em.cnpj_beneficiario}` : ""}
                            </span>
                            {/* Convênio relacionado (casado pelo nº da indicação, #3). */}
                            {em.conv_nr && (
                              <Selo tom="ok" title={em.conv_objeto || `Convênio ${em.conv_nr}`}>
                                Convênio {em.conv_nr}
                              </Selo>
                            )}
                          </>
                        }
                      >
                        <Campos
                          campos={[
                            { rotulo: "Unidade orçamentária", valor: em.uo_sigla || em.uo_codigo || "—",
                              title: [em.uo_codigo, em.uo_sigla].filter(Boolean).join(" · ") },
                            { rotulo: "Grupo de despesa", valor: em.grupo_despesa || "—" },
                            { rotulo: "Ano", valor: em.ano ?? "—" },
                            // «—» = os dados da SEGOV não trouxeram esta indicação
                            // (não é R$ 0).
                            { rotulo: em.execucao_em ? `Pago até ${diaBR(em.execucao_em)}` : "Pago",
                              valor: em.valor_pago == null ? "—" : formatCurrency(em.valor_pago),
                              title: em.valor_empenhado == null ? undefined
                                : `Empenhado ${formatCurrency(em.valor_empenhado)}` },
                          ]}
                        />
                      </ItemLinha>
                    ))}
                  </Lista>
                )}
              </Bloco>
            );
          })}
        </div>
      )}
      {municipioId && <OutrosBeneficiariosMG municipioId={String(municipioId)} />}
    </div>
  );
}

interface OutroMG {
  nr_indicacao: string; ano: number | null; autor: string | null; tipo_indicacao: string | null;
  tipo_beneficiario: string | null; beneficiario: string | null; cnpj: string | null;
  valor_indicacao: number | null; valor_pago: number | null; status: string | null;
  execucao_em: string | null;
}

/** Indicações a quem está no município e NÃO é o município (OSC, caixa escolar,
 *  órgão estadual) — fora das contas desta tela, num bloco recolhido. Mesma regra
 *  do bloco "Outros convenentes" da tela de Convênios. */
function OutrosBeneficiariosMG({ municipioId }: { municipioId: string }) {
  const [itens, setItens] = useState<OutroMG[] | null>(null);
  const [aberto, setAberto] = useState(false);
  useEffect(() => {
    let vivo = true;
    api.get<OutroMG[]>("/emendas-estaduais/outros", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setItens(r.data); })
      .catch(() => { if (vivo) setItens([]); });
    return () => { vivo = false; };
  }, [municipioId]);
  if (!itens || itens.length === 0) return null;
  return (
    <Bloco className="p-3">
      <button type="button" className="w-full text-left" onClick={() => setAberto(!aberto)}
              aria-expanded={aberto}>
        <BlocoHead
          icon={Users}
          titulo={`Outros beneficiários no município · ${itens.length}`}
          sub="OSC, caixas escolares e órgãos estaduais indicados por emenda — não é a prefeitura e fica fora das contas desta tela"
          right={<ChevronDown className={`size-4 transition-transform ${aberto ? "rotate-180" : ""}`} />}
        />
      </button>
      {aberto && (
        <Lista>
          {itens.map((o) => (
            <ItemLinha
              key={o.nr_indicacao}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>{o.beneficiario || "Beneficiário não informado"}</span>
                  {o.tipo_indicacao && <Selo title={o.tipo_indicacao}>{siglaTipo(o.tipo_indicacao)}</Selo>}
                  {o.status && <Selo tom={situacaoTom(o.status)}>{o.status.toLowerCase()}</Selo>}
                  <Selo>não é a prefeitura</Selo>
                </span>
              }
              valor={o.valor_indicacao == null ? "—" : formatCurrency(o.valor_indicacao)}
              meta={
                <>
                  <span className="font-mono">nº {o.nr_indicacao}</span>
                  {o.autor && <span>· {o.autor}</span>}
                  {o.tipo_beneficiario && <span>· {o.tipo_beneficiario.toLowerCase()}</span>}
                </>
              }
            >
              <Campos campos={[
                { rotulo: "Ano", valor: o.ano ?? "—" },
                { rotulo: o.execucao_em ? `Pago até ${diaBR(o.execucao_em)}` : "Pago",
                  valor: o.valor_pago == null ? "—" : formatCurrency(o.valor_pago) },
                { rotulo: "CNPJ", valor: o.cnpj || "—" },
              ]} />
            </ItemLinha>
          ))}
        </Lista>
      )}
    </Bloco>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-base-100 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-bold mt-1">{value}</div>
    </div>
  );
}
