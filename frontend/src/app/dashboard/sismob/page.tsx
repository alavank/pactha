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
import React, { useEffect, useState } from "react";
import {
  HardHat, AlertTriangle, CheckCircle2, Clock, Loader2, Wallet,
  Building2, ExternalLink, ChevronDown, ChevronRight, Camera,
} from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";

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

function moeda(v?: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL",
                                     maximumFractionDigits: 0 });
}
function moedaExata(v?: number | null): string {
  if (v == null) return "—";
  return v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
function data(iso?: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString("pt-BR", { timeZone: "UTC" }); }
  catch { return iso.slice(0, 10); }
}
function cnpjFmt(c?: string | null): string {
  if (!c || c.length !== 14) return c || "—";
  return `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}`;
}

function Numero({ label, valor, sub, tom }: {
  label: string; valor: string; sub?: string; tom?: "crit" | "warn" | "ok";
}) {
  const cor = tom === "crit" ? "text-error" : tom === "warn" ? "text-warning"
    : tom === "ok" ? "text-success" : "text-base-content";
  return (
    <div className="rounded-2xl border border-base-300 bg-base-100 p-4 shadow-theme-sm">
      <div className="text-xs text-base-content/60">{label}</div>
      <div className={`mt-1 text-2xl font-bold ${cor}`}>{valor}</div>
      {sub && <div className="text-xs text-base-content/50">{sub}</div>}
    </div>
  );
}

function CartaoObra({ o }: { o: Obra }) {
  const crit = o.severidade === "critico";
  const pct = o.percentual ?? 0;
  return (
    <div className={`rounded-2xl border p-4 ${crit
      ? "border-error/40 bg-error/5" : "border-warning/40 bg-warning/5"}`}>
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="font-semibold text-base-content">
            {o.estabelecimento || `Proposta ${o.numero_proposta || o.proposta_id}`}
          </div>
          <div className="text-xs text-base-content/60">
            {[o.programa, o.tipo_obra, o.bairro, o.ano_referencia].filter(Boolean).join(" · ")}
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-semibold ${
          crit ? "bg-error text-error-content" : "bg-warning text-warning-content"}`}>
          {o.situacao}
        </span>
      </div>

      {o.percentual != null && (
        <div className="mt-3">
          <div className="flex items-baseline justify-between text-xs">
            <span className="text-base-content/60">Execução física</span>
            <span className="font-mono font-semibold">{pct}%</span>
          </div>
          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-base-300">
            <div className={`h-full ${crit ? "bg-error" : "bg-warning"}`}
                 style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
          </div>
        </div>
      )}

      {/* Uma linha por regra violada. `norma` e `acao` vêm do servidor: um
          alerta que diz "vencido" sem dizer o dispositivo nem o que fazer não
          sobrevive à primeira conversa com a Secretaria de Saúde. */}
      <div className="mt-3 space-y-2">
        {o.regras.map((r) => (
          <div key={r.regra} className="rounded-lg bg-base-100/70 p-2.5">
            <div className="flex items-start gap-2">
              <AlertTriangle className={`mt-0.5 size-4 shrink-0 ${
                r.severidade === "critico" ? "text-error" : "text-warning"}`} />
              <div className="min-w-0">
                <div className="text-sm font-semibold">{r.titulo}</div>
                <p className="text-xs leading-snug text-base-content/70">{r.detalhe}</p>
                <p className="mt-1 text-xs font-medium text-base-content">{r.acao}</p>
                <p className="text-[10px] text-base-content/40">{r.norma}</p>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-base-content/60">
        <span><Wallet className="mr-1 inline size-3.5" />
          {moedaExata(o.dinheiro.repassado)} repassado de {moedaExata(o.dinheiro.proposta)}
        </span>
        {o.empresas[0] && (
          <span><Building2 className="mr-1 inline size-3.5" />
            {o.empresas[0].razao_social}
            {o.empresas[0].numero_contrato ? ` · contrato ${o.empresas[0].numero_contrato}` : ""}
          </span>
        )}
        {/* A data da última foto É o argumento da estagnação — mostrá-la ao lado
            da contagem transforma um número inerte em prova. */}
        {(o.fotos.grupos || 0) > 0 && (
          <span><Camera className="mr-1 inline size-3.5" />
            {o.fotos.total} foto(s), última em {data(o.fotos.ultima_em)}
          </span>
        )}
        <a href={o.url_portal} target="_blank" rel="noreferrer"
           className="ml-auto inline-flex items-center gap-1 font-medium text-primary hover:underline">
          Consultar no SISMOB <ExternalLink className="size-3.5" />
        </a>
      </div>
    </div>
  );
}

function LinhaSimples({ o }: { o: Obra }) {
  return (
    <div className="flex items-start gap-2 border-b border-base-300/60 px-3 py-2 last:border-0">
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{o.estabelecimento || o.numero_proposta}</div>
        <div className="text-xs text-base-content/50">
          {[o.programa, o.tipo_obra].filter(Boolean).join(" · ")}
        </div>
      </div>
      <div className="shrink-0 text-right">
        <div className="text-xs font-medium">{o.situacao}</div>
        <div className="font-mono text-xs text-base-content/50">
          {o.percentual != null ? `${o.percentual}%` : "—"} · {moeda(o.dinheiro.proposta)}
        </div>
      </div>
    </div>
  );
}

function Secao({ titulo, obras, aberta }: { titulo: string; obras: Obra[]; aberta?: boolean }) {
  const [open, setOpen] = useState(!!aberta);
  if (!obras.length) return null;
  return (
    <div className="rounded-2xl border border-base-300 bg-base-100 shadow-theme-sm">
      <button onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left">
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        <span className="text-sm font-semibold">{titulo}</span>
        <span className="ml-auto text-xs text-base-content/50">{obras.length}</span>
      </button>
      {open && <div>{obras.map((o) => <LinhaSimples key={o.proposta_id} o={o} />)}</div>}
    </div>
  );
}

export default function SismobPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(true);

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

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
          <HardHat className="size-6 text-primary" /> Obras da Saúde (SISMOB)
        </h1>
        <p className="mt-1 text-sm text-base-content/60">
          Obras financiadas fundo a fundo pelo Ministério da Saúde
          {d?.entidade?.nome ? <> — convenente <strong>{d.entidade.nome}</strong>
            <span className="font-mono text-xs"> ({cnpjFmt(d.entidade.cnpj)})</span></> : null}
        </p>
      </div>

      {!municipioId && (
        <div className="rounded-2xl border border-base-300 bg-base-100 p-8 text-center text-base-content/60">
          Selecione um município para ver as obras.
        </div>
      )}

      {municipioId && loading && (
        <div className="flex justify-center py-16"><Loader2 className="size-8 animate-spin text-primary" /></div>
      )}

      {municipioId && !loading && !d?.tem_dados && (
        /* Aguardando coleta — e dizendo POR QUÊ. Nunca verde: verde aqui seria
           lido como "não há obra com problema", que é diferente de "não sei". */
        <div className="rounded-2xl border border-warning/30 bg-warning/5 p-6">
          <div className="flex items-start gap-3">
            <Clock className="size-6 shrink-0 text-warning" />
            <div>
              <div className="font-semibold">Aguardando coleta</div>
              <p className="text-sm text-base-content/70">{d?.motivo}</p>
            </div>
          </div>
        </div>
      )}

      {municipioId && !loading && d?.tem_dados && t && (
        <>
          {/* Faixa de situação: uma frase. Verde só quando não há nada a fazer. */}
          <div className={`rounded-2xl border p-4 ${acao.length
            ? "border-error/30 bg-error/10" : "border-success/30 bg-success/10"}`}>
            <div className="flex items-center gap-3">
              {acao.length
                ? <AlertTriangle className="size-8 shrink-0 text-error" />
                : <CheckCircle2 className="size-8 shrink-0 text-success" />}
              <div>
                <div className={`font-bold ${acao.length ? "text-error" : "text-success"}`}>
                  {acao.length
                    ? `${acao.length} obra(s) precisam de ação`
                    : "Nenhuma obra com pendência de prazo"}
                </div>
                <div className="text-sm text-base-content/70">
                  {t.repasse_parado > 0
                    ? `${moedaExata(t.repasse_parado)} repassados em obras que não se movem há mais de 60 dias.`
                    : `${t.vivas} obra(s) em andamento, todas dentro do prazo de atualização.`}
                </div>
              </div>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Numero label="Obras em andamento" valor={String(t.vivas)}
              sub={`${t.obras} no total`} />
            <Numero label="Já repassado" valor={moeda(t.repasse_total)}
              sub={`de ${moeda(t.valor_proposta)} aprovados`} />
            <Numero label="Parado sem atualização" valor={moeda(t.repasse_parado)}
              tom={t.repasse_parado > 0 ? "crit" : "ok"}
              sub={t.repasse_parado > 0 ? "dinheiro em obra que não anda" : "nada parado"} />
            <Numero label="Precisam de ação" valor={String(acao.length)}
              tom={acao.length ? "crit" : "ok"} sub="prazo ou pendência" />
            <Numero label="Concluídas" valor={String(t.concluidas)}
              sub={t.canceladas ? `${t.canceladas} cancelada(s)` : undefined} />
          </div>

          <div className="grid gap-5 xl:grid-cols-3">
            <section className="space-y-3 xl:col-span-2">
              <h2 className="text-lg font-bold">Precisa de ação</h2>
              {acao.length
                ? acao.map((o) => <CartaoObra key={o.proposta_id} o={o} />)
                : (
                  <div className="rounded-2xl border border-base-300 bg-base-100 p-6 text-center text-sm text-base-content/60">
                    Nenhuma obra com prazo vencido ou parada.
                  </div>
                )}
              <Secao titulo="Em dia" obras={d.em_dia ?? []} />
              <Secao titulo="Concluídas e encerradas" obras={d.encerradas ?? []} />
            </section>

            <aside className="space-y-3">
              <div className="rounded-2xl border border-base-300 bg-base-100 p-4 shadow-theme-sm">
                <div className="mb-2 text-sm font-semibold">Dinheiro</div>
                <dl className="space-y-1.5 text-sm">
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
                          <dt className="text-base-content/70">{k}</dt>
                          <dd className="font-mono font-medium">{moedaExata(v)}</dd>
                        </div>
                        {nota && <div className="text-[10px] text-base-content/40">{nota}</div>}
                      </div>
                    ))}
                </dl>
              </div>

              {!!d.empresas_concentracao?.length && (
                <div className="rounded-2xl border border-base-300 bg-base-100 p-4 shadow-theme-sm">
                  <div className="mb-2 text-sm font-semibold">Empresas contratadas</div>
                  <div className="space-y-2">
                    {d.empresas_concentracao.map((e) => {
                      const pct = t.contratado ? (e.valor / t.contratado) * 100 : 0;
                      return (
                        <div key={e.cnpj} className="text-sm">
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="min-w-0 flex-1 truncate">{e.razao_social}</span>
                            <span className="font-mono text-xs">{moeda(e.valor)}</span>
                          </div>
                          <div className="flex items-center gap-2 text-[10px] text-base-content/50">
                            <span className="font-mono">{cnpjFmt(e.cnpj)}</span>
                            <span>{e.obras} obra(s)</span>
                            {pct >= 50 && (
                              <span className="rounded bg-warning/20 px-1.5 font-semibold text-warning">
                                {Math.round(pct)}% do contratado
                              </span>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {!!d.por_programa?.length && (
                <div className="rounded-2xl border border-base-300 bg-base-100 p-4 shadow-theme-sm">
                  <div className="mb-2 text-sm font-semibold">Por programa</div>
                  {d.por_programa.map((p) => (
                    <div key={p.label} className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="min-w-0 flex-1 truncate text-base-content/70">{p.label}</span>
                      <span className="text-xs text-base-content/50">{p.qtd}</span>
                      <span className="font-mono text-xs">{moeda(p.valor)}</span>
                    </div>
                  ))}
                </div>
              )}

              <p className="text-xs text-base-content/40">
                Fonte: SISMOB Cidadão (Ministério da Saúde). Coleta de {data(d.coletado_em)}.
              </p>
            </aside>
          </div>
        </>
      )}
    </div>
  );
}
