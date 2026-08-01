"use client";

import React, { useMemo, useState } from "react";
import {
  Search as SearchIcon, Loader2, Landmark, Building2, X, Coins, FileText, Wallet,
} from "lucide-react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { formatCurrencyShort } from "@/lib/bi-format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";

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

function Field({ label, value, mono, wide }: { label: string; value?: React.ReactNode; mono?: boolean; wide?: boolean }) {
  return (
    <div className={wide ? "sm:col-span-2" : ""}>
      <div className="text-[11px] uppercase tracking-wide text-base-content/50">{label}</div>
      <div className={`text-sm text-base-content ${mono ? "font-mono" : ""}`}>{value ?? "-"}</div>
    </div>
  );
}

export default function TransfereGovCnpjPage() {
  const [cnpj, setCnpj] = useState("");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [data, setData] = useState<Resp | null>(null);
  const [selVol, setSelVol] = useState<Voluntaria | null>(null);
  const [selEsp, setSelEsp] = useState<Especial | null>(null);

  // Os totais em dinheiro que os KPIs mostram. O endpoint devolve as duas
  // listas inteiras (total_* = length), entao somar aqui nao mente.
  const resumo = useMemo(() => {
    if (!data) return null;
    return {
      valEsp: data.especiais.reduce((s, e) => s + (e.valor_total ?? 0), 0),
      valVol: data.voluntarias.reduce((s, v) => s + (v.valor_repasse ?? v.valor_global ?? 0), 0),
      pagoVol: data.voluntarias.reduce((s, v) => s + (v.valor_desembolsado ?? 0), 0),
    };
  }, [data]);

  const consultar = async () => {
    const digits = cnpj.replace(/\D/g, "");
    if (digits.length !== 14) { setErro("Informe um CNPJ com 14 dígitos."); return; }
    setLoading(true); setErro(null);
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
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <Building2 className="size-6" style={{ color: "var(--bi-muted)" }} /> Consulta TransfereGov por CNPJ
        </h1>
        <p className="text-sm" style={{ color: "var(--bi-muted)" }}>
          Busca por CNPJ do proponente — Transferência Especial (Plano de Ação, ao vivo) + Voluntárias (dados já coletados). Não entra em relatório.
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
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Numero
              icon={Landmark}
              rotulo="Planos de ação"
              valor={data.total_especiais}
              sub="Transferência Especial (ao vivo)"
            />
            <Numero
              icon={Coins}
              rotulo="Valor em planos de ação"
              valor={formatCurrencyShort(resumo.valEsp)}
              sub={formatCurrency(resumo.valEsp)}
            />
            <Numero
              icon={FileText}
              rotulo="Propostas voluntárias"
              valor={data.total_voluntarias}
              sub="SICONV — base federal"
            />
            <Numero
              icon={Wallet}
              rotulo="Repasse (voluntárias)"
              valor={formatCurrencyShort(resumo.valVol)}
              sub={`pago ${formatCurrency(resumo.pagoVol)}`}
            />
          </div>

          {/* AS DUAS TABELAS VIRARAM LISTA.
              Cada bloco e um grupo na gramatica do Painel (cabecalho com
              contagem e total a direita) e cada registro e um cartao sem borda.
              As colunas nao sumiram: as que se comparam entre linhas foram para
              <Campos>, em posicao FIXA, para o olho continuar descendo em
              coluna como descia na tabela; as que servem para identificar
              foram para a meta. */}
          <Bloco className="p-3">
            <BlocoHead
              icon={Landmark}
              titulo="Transferência Especial (Plano de Ação)"
              sub={`${data.total_especiais} resultado(s) · consulta ao vivo no TransfereGov`}
              right={<span className="bi-num text-[13px]">{formatCurrency(resumo.valEsp)}</span>}
            />
            {data.especiais.length === 0 ? (
              <Vazio>Nenhum plano de ação para este CNPJ.</Vazio>
            ) : (
              <Lista>
                {data.especiais.map((e, i) => {
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

          <Bloco className="p-3">
            <BlocoHead
              icon={Landmark}
              titulo="Voluntárias / Convênios (SICONV — base federal)"
              sub={`${data.total_voluntarias} resultado(s) · dados já coletados`}
              right={<span className="bi-num text-[13px]">{formatCurrency(resumo.valVol)}</span>}
            />
            {data.voluntarias.length === 0 ? (
              <Vazio>Nenhuma proposta voluntária deste CNPJ nos dados já coletados.</Vazio>
            ) : (
              <Lista>
                {data.voluntarias.map((v, i) => {
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
        </div>
      )}

      {/* Modal Voluntaria / Convenio */}
      {selVol && (
        <Modal onClose={() => setSelVol(null)} title={`Proposta ${selVol.numero_proposta || ""}`} subtitle={selVol.situacao}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            <Field label="Nº Proposta" value={selVol.numero_proposta} mono />
            <Field label="Ano" value={selVol.ano} />
            <Field label="Situação da proposta" value={selVol.situacao} wide />
            <Field label="Proponente" value={selVol.proponente} wide />
            <Field label="Município / UF" value={selVol.municipio ? `${selVol.municipio}/${selVol.uf || ""}` : "-"} />
            <Field label="Nº Convênio" value={selVol.nr_convenio} mono />
            <Field label="Situação do convênio" value={selVol.situacao_convenio} wide />
            <Field label="Valor global" value={formatCurrency(selVol.valor_global)} />
            <Field label="Valor repasse" value={formatCurrency(selVol.valor_repasse)} />
            <Field label="Valor desembolsado (pago)" value={selVol.valor_desembolsado != null ? formatCurrency(selVol.valor_desembolsado) : "-"} />
            <Field label="Assinatura" value={fmtDate(selVol.dt_assinatura)} />
            <Field label="Fim da vigência" value={fmtDate(selVol.dt_fim_vigencia)} />
            <Field label="Objeto" value={<span className="whitespace-pre-wrap">{selVol.objeto || "-"}</span>} wide />
          </div>
        </Modal>
      )}

      {/* Modal Especial / Plano de Acao */}
      {selEsp && (
        <Modal onClose={() => setSelEsp(null)} title={`Plano de Ação ${selEsp.codigo || ""}`} subtitle={selEsp.situacao}>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-3">
            <Field label="Código" value={selEsp.codigo} mono />
            <Field label="Programa" value={selEsp.programa_codigo} mono />
            <Field label="Situação" value={selEsp.situacao} wide />
            <Field label="Beneficiário" value={selEsp.beneficiario_nome} />
            <Field label="CNPJ" value={selEsp.beneficiario_cnpj ? maskCnpj(selEsp.beneficiario_cnpj) : "-"} mono />
            <Field label="UF" value={selEsp.uf} />
            <Field label="Emenda" value={selEsp.emenda_codigo} mono />
            <Field label="Valor total" value={formatCurrency(selEsp.valor_total)} />
            <Field label="Políticas públicas" value={selEsp.politicas_publicas} wide />
            <Field label="Objeto" value={<span className="whitespace-pre-wrap">{selEsp.objeto_descricao || "-"}</span>} wide />
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({ title, subtitle, onClose, children }: { title: string; subtitle?: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="bg-base-100 rounded-2xl shadow-xl w-full max-w-2xl max-h-[85vh] overflow-y-auto" onClick={(ev) => ev.stopPropagation()}>
        <div className="sticky top-0 bg-base-100 border-b px-5 py-3 flex items-start gap-3">
          <div className="min-w-0">
            <div className="font-semibold text-base-content truncate">{title}</div>
            {subtitle && <div className="text-xs text-base-content/60 truncate">{subtitle}</div>}
          </div>
          <button onClick={onClose} className="ml-auto text-base-content/50 hover:text-base-content shrink-0">
            <X className="size-5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
