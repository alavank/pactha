"use client";

import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/multi-select";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Modal, ModalCorpo, ModalHead, Numero, Secao, Selo, Vazio, situacaoTom, type Campo,
} from "@/components/ui/superficies";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { formatCurrency } from "@/lib/utils";
import {
  Search, Loader2, Eraser, Printer, Eye, X,
  HeartPulse, Users, Receipt, FileText, Route, Wallet, Hourglass, Building2,
} from "lucide-react";

interface Item {
  tipo_proposta?: string;
  tipo_recurso?: string;
  nu_processo?: string;
  valor_proposta?: number;
  valor_pago?: number;
  valor_pagar?: number;
  constituido_processo?: boolean;
  parlamentares?: Array<{ nome?: string; partido?: string }>;
  pagamentos_count?: number;
  /** De qual ano veio a linha (a consulta agora pode cobrir varios). */
  ano?: string;
}

interface Resp {
  items: Item[];
  total: number;
  totais?: { valor_proposta: number; valor_pago: number; valor_pagar: number };
  params?: Record<string, string | number>;
}

interface Mun { id?: number; nome: string; cod_ibge: string; uf?: string }

interface Individual {
  nu_proposta: string;
  entidade: string;
  tipo_proposta?: string;
  tipo_recurso?: string;
  valor_proposta: number;
  valor_pago: number;
}

interface EtapaWorkflow {
  numero: number;
  descricao: string;
  completada: boolean;
  atual: boolean;
}

interface ParlamentarFNS {
  nome?: string;
  partido?: string;
  nu_emenda?: string;
  ano?: string;
  valor?: number;
}

interface PagamentoFNS {
  parcela?: string;
  data?: number;  // ms epoch
  valor?: number;
  valor_acumulado?: number;
  ordem_bancaria?: string;
  nu_processo?: string;
  localizacao?: string;
}

interface PropostaDetalhe {
  nu_proposta: string;
  uf: string;
  municipio: string;
  cnpj: string;
  entidade: string;
  tipo_proposta: string;
  valor_proposta: number;
  ano: string;
  tipo_recurso: string;
  esfera: string;
  nu_portaria?: string;
  nu_processo: string;
  situacao_descricao: string;
  situacao_data?: number;
  data_portaria?: number;
  vl_empenhado: number;
  vl_pago: number;
  vl_pagar: number;
  parlamentares: ParlamentarFNS[];
  pagamentos: PagamentoFNS[];
  constituido_processo: boolean;
  etapas: EtapaWorkflow[];
  etapa_atual?: number;
}

// Valores exatos aceitos pelo FNS no parametro tpEmenda (valorEmenda do portal)
// Vazio = TODOS (mesma convencao do <MultiSelect> e do backend, que so recebe
// o parametro quando ha filtro).
const TIPOS_EMENDA = [
  "INDIVIDUAL",
  "BANCADA",
  "BANCADA OBRIGATÓRIA",
  "COMISSAO",
  "RELATOR",
];

/** Quanto do proposto ja foi pago. `null` quando nao ha base para dividir —
 *  proposta de valor zero nao e "0% paga", e sem percentual nenhum. */
function pctPago(proposta?: number, pago?: number): number | null {
  if (!proposta) return null;
  return Math.round(((pago || 0) / proposta) * 100);
}

/** Data em ms epoch, como o FNS entrega. */
function dataBR(ms?: number): string {
  return ms ? new Date(ms).toLocaleDateString("pt-BR") : "—";
}

export default function PropostasFNSPage() {
  const currentYear = new Date().getFullYear();

  const { municipioId } = useMunicipio();
  const [municipios, setMunicipios] = useState<Mun[]>([]);
  const [anos, setAnos] = useState<string[]>([]);
  const [nrProposta, setNrProposta] = useState("");
  // PERIODO MULTI-ANO. Abre com o ano corrente marcado — e ja consulta sozinho
  // (ver o efeito de auto-consulta abaixo): ninguem deveria precisar clicar em
  // "Consultar" para ver o ano em que esta.
  const [anosSel, setAnosSel] = useState<string[]>([String(currentYear)]);
  const [tiposSel, setTiposSel] = useState<string[]>([]);
  // FNS SEGUE o filtro geral (Município Atendido): travado no município selecionado
  // na sidebar. Assim o usuário não filtra o FNS de município fora da sua permissão.
  const selMun = municipios.find((m) => String(m.id) === municipioId) || null;
  const municipio = selMun?.nome || "";
  const estado = selMun?.uf || "MG";
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Modal de detalhamento (clique no botao olho)
  const [detalheItem, setDetalheItem] = useState<Item | null>(null);
  const [individuais, setIndividuais] = useState<Array<Individual> | null>(null);
  const [loadingIndiv, setLoadingIndiv] = useState(false);
  const [propostaDetalhe, setPropostaDetalhe] = useState<PropostaDetalhe | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);

  // Quando abre modal nivel 1, busca lista de propostas individuais
  useEffect(() => {
    if (!detalheItem || !data) {
      setIndividuais(null);
      return;
    }
    setLoadingIndiv(true);
    api.get<{items: Individual[]}>("/fns/listar-individuais", {
      params: {
        municipio: data.params?.municipio,
        // com varios anos no filtro, o detalhe segue o ano DA LINHA clicada
        ano: detalheItem.ano ?? data.params?.ano,
        uf: data.params?.uf,
        tipo_proposta: detalheItem.tipo_proposta,
        tipo_recurso: detalheItem.tipo_recurso,
      }
    }).then((r) => setIndividuais(r.data.items || []))
      .catch(() => setIndividuais([]))
      .finally(() => setLoadingIndiv(false));
  }, [detalheItem, data]);

  const abrirDetalheProposta = async (nuProposta: string) => {
    setLoadingDetalhe(true);
    setPropostaDetalhe(null);
    try {
      const r = await api.get<PropostaDetalhe>(`/fns/proposta/${nuProposta}`);
      setPropostaDetalhe(r.data);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error).message;
      alert(`Falha: ${msg}`);
    } finally {
      setLoadingDetalhe(false);
    }
  };

  useEffect(() => {
    api.get<Mun[]>("/fns/municipios").then((r) => setMunicipios(r.data || [])).catch(() => {});
    api.get<string[]>("/fns/anos").then((r) => setAnos(r.data || [])).catch(() => {
      // Fallback se /anos falha
      const list = [];
      for (let y = currentYear; y >= 2019; y--) list.push(String(y));
      setAnos(list);
    });
  }, [currentYear]);

  const consultar = React.useCallback(async () => {
    if (!municipio) {
      setError("Selecione um município no menu lateral (Município Atendido).");
      return;
    }
    if (!anosSel.length) {
      setError("Selecione pelo menos um ano.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      // Um request por ano (o FNS so aceita um `ano` por consulta) e junta tudo.
      // Um ano que falhar nao derruba os outros — o portal cai com frequencia.
      const resultados = await Promise.all(
        [...anosSel].sort().map(async (a) => {
          const params: Record<string, string | number> = { municipio, ano: a, uf: estado };
          if (nrProposta) params.nr_proposta = nrProposta;
          // Um tipo -> o proprio FNS filtra (comportamento de antes, intacto).
          // Varios -> pede tudo e filtra aqui: o portal aceita UM tipo por
          // consulta, e multiplicar anos x tipos viraria dezenas de requests.
          if (tiposSel.length === 1) params.tipo_emenda = tiposSel[0];
          try {
            const res = await api.get<Resp>("/fns/buscar", { params });
            return { ano: a, resp: res.data, erro: null as string | null };
          } catch (e) {
            const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
              || (e as Error).message;
            return { ano: a, resp: null, erro: msg };
          }
        })
      );

      const ok = resultados.filter((r) => r.resp);
      const falhas = resultados.filter((r) => r.erro);
      if (!ok.length) {
        setError(`Falha na consulta: ${falhas[0]?.erro ?? "sem resposta do FNS"}`);
        setData(null);
        return;
      }
      const brutos = ok.flatMap((r) => (r.resp!.items || []).map((it) => ({ ...it, ano: r.ano })));
      // Com 2+ tipos marcados o corte e local. `tipo_recurso` vem descritivo
      // ("EMENDA INDIVIDUAL") e o filtro do portal usa o termo curto
      // ("INDIVIDUAL"), entao a comparacao e por conteudo.
      const items = tiposSel.length > 1
        ? brutos.filter((it) => {
            const t = (it.tipo_recurso || "").toUpperCase();
            return tiposSel.some((sel) => t.includes(sel.toUpperCase()));
          })
        : brutos;
      setData({
        items,
        total: items.length,
        totais: {
          valor_proposta: items.reduce((s, i) => s + (i.valor_proposta || 0), 0),
          valor_pago: items.reduce((s, i) => s + (i.valor_pago || 0), 0),
          valor_pagar: items.reduce((s, i) => s + (i.valor_pagar || 0), 0),
        },
        params: {
          ...(ok[0].resp!.params || {}),
          ano: ok.map((r) => r.ano).join(", "),
        },
      });
      setError(falhas.length ? `Sem resposta do FNS para ${falhas.map((f) => f.ano).join(", ")}.` : null);
    } finally {
      setLoading(false);
    }
  }, [municipio, anosSel, estado, nrProposta, tiposSel]);

  // AUTO-CONSULTA: assim que o município estiver resolvido, a tela ja abre com
  // o resultado do ano corrente. Refaz quando o município ou os anos mudarem;
  // os demais filtros (nº da proposta, tipo de emenda) seguem no botao, porque
  // sao refinamentos que o usuario digita.
  const assinaturaAuto = `${municipio}|${estado}|${[...anosSel].sort().join(",")}`;
  const ultimaAutoRef = React.useRef<string>("");
  useEffect(() => {
    if (!municipio || !anosSel.length) return;
    if (ultimaAutoRef.current === assinaturaAuto) return;
    ultimaAutoRef.current = assinaturaAuto;
    void consultar();
  }, [assinaturaAuto, municipio, anosSel.length, consultar]);

  const limpar = () => {
    setNrProposta("");
    setTiposSel([]);
    setAnosSel([String(currentYear)]);
    setError(null);
  };

  const pctGeral = data?.totais
    ? pctPago(data.totais.valor_proposta, data.totais.valor_pago)
    : null;

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="text-2xl font-bold text-base-content">Fundo Nacional de Saúde</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Consulta em tempo real de propostas/emendas no FNS (consultafns.saude.gov.br)
        </p>
      </div>

      {/* Formulario */}
      <div className="bi-card space-y-3 p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Nº da Proposta
            </label>
            <Input
              value={nrProposta}
              onChange={(e) => setNrProposta(e.target.value)}
              placeholder="(opcional)"
              onKeyDown={(e) => { if (e.key === "Enter") consultar(); }}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Anos <span style={{ color: "var(--bi-faint)" }}>(um, alguns ou o mandato)</span>
            </label>
            <MultiSelect
              opcoes={anos}
              valor={anosSel}
              onChange={setAnosSel}
              atalhos={atalhosAnos()}
              formatarResumo={resumoAnos}
              placeholder="Selecione o ano"
              /* Aqui "Limpar" NAO e "todos": o portal do FNS exige um ano por
                 requisicao, entao lista vazia bloqueia a consulta (ver linha do
                 `if (!anosSel.length)`). Nao trocar por "Todos". */
              rotuloTodos="Limpar"
              ariaLabel="Anos da consulta"
            />
          </div>
          {/* O campo "Município (filtro geral)" saiu daqui.
              Era uma caixa cinza travada, sem escolha nenhuma, repetindo o
              municipio que ja esta no menu lateral e no cabecalho do resultado.
              Ocupava um terco da barra de filtros para nao filtrar nada — o
              ambiente inteiro e de um municipio so.
              O aviso de "selecione o municipio" continua existindo onde
              importa: no erro da consulta e no cabecalho do resultado. */}
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Tipo de Emenda <span style={{ color: "var(--bi-faint)" }}>(um, alguns ou todos)</span>
            </label>
            <MultiSelect
              opcoes={TIPOS_EMENDA}
              valor={tiposSel}
              onChange={setTiposSel}
              rotuloTodos="TODOS"
              ariaLabel="Tipo de emenda"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
          <Button variant="outline" onClick={limpar}>
            <Eraser className="size-4 mr-1" /> Limpar
          </Button>
          <Button
            onClick={consultar}
            disabled={loading || !selMun}
            className="hover:opacity-90"
            style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
          >
            {loading ? <Loader2 className="size-4 animate-spin mr-2" /> : <Search className="size-4 mr-2" />}
            Consultar
          </Button>
        </div>
      </div>

      {/* O MESMO `error` carrega dois casos bem diferentes: a consulta que nao
          voltou nada (nao ha o que ler na tela) e a que voltou parcial (alguns
          anos falharam, o resto esta ai embaixo). O selo separa os dois — cor
          critica so quando nao ha resultado. */}
      {error && (
        <div className="bi-card flex flex-wrap items-center gap-2 p-3 text-[12px]" style={{ color: "var(--bi-muted)" }}>
          <Selo tom={data ? "atencao" : "critico"}>{data ? "Consulta parcial" : "Consulta"}</Selo>
          {error}
        </div>
      )}

      {/* Resultado */}
      {data && (
        <div className="space-y-3">
          <Bloco className="p-3">
            <BlocoHead
              icon={HeartPulse}
              titulo="Resultado da consulta"
              sub="Propostas agrupadas por tipo de proposta e tipo de recurso"
              right={
                <Button variant="outline" size="sm" onClick={() => window.print()}>
                  <Printer className="size-3 mr-1" /> Imprimir
                </Button>
              }
            />
            <Campos
              cols={4}
              campos={[
                { rotulo: "Estado", valor: data.params?.uf ?? "—" },
                { rotulo: "Município", valor: data.params?.municipio ?? "—", title: String(data.params?.municipio ?? "") },
                { rotulo: "Ano(s)", valor: data.params?.ano ?? "—", title: String(data.params?.ano ?? "") },
                { rotulo: "Registros", valor: data.total },
              ]}
            />
          </Bloco>

          {data.totais && (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <Numero
                icon={Wallet}
                rotulo="Valor Proposta"
                valor={formatCurrency(data.totais.valor_proposta)}
                sub={`${data.total} proposta(s) no recorte`}
              />
              {/* Pago e "A pagar" sao o mesmo dinheiro visto de dois lados: o
                  verde so aparece quando esta tudo quitado, e o ambar so quando
                  sobrou saldo — nunca os dois acesos ao mesmo tempo. */}
              <Numero
                icon={Receipt}
                rotulo="Valor Pago"
                valor={formatCurrency(data.totais.valor_pago)}
                tom={pctGeral != null && pctGeral >= 100 ? "ok" : "neutro"}
                sub={pctGeral != null ? `${pctGeral}% do proposto` : undefined}
              />
              <Numero
                icon={Hourglass}
                rotulo="A Pagar"
                valor={formatCurrency(data.totais.valor_pagar)}
                tom={data.totais.valor_pagar > 0 ? "atencao" : "neutro"}
                sub={data.totais.valor_pagar > 0 ? "saldo ainda nao repassado" : "sem saldo em aberto"}
              />
            </div>
          )}

          {data.items.length === 0 ? (
            <Vazio>Nenhuma proposta encontrada para os filtros aplicados.</Vazio>
          ) : (
            /* A TABELA DE 9 COLUNAS VIROU LISTA DE CARTOES.
               O que substituiu a grade e o <Campos>: ano, processo e os tres
               numeros ficam em POSICOES FIXAS, iguais em todos os cartoes, entao
               o olho continua descendo por uma coluna. Nada saiu — o tipo de
               recurso virou selo cinza (era pintado de violeta/azul/ambar por
               uma tabela de cores propria, que nao classificava alerta nenhum) e
               os parlamentares seguem na meta com a lista completa no title. */
            <Lista>
              {data.items.map((it, idx) => {
                const parls = it.parlamentares || [];
                const nomes = parls.map((p) => p.nome).filter(Boolean).join(", ");
                const pct = pctPago(it.valor_proposta, it.valor_pago);
                return (
                  <ItemLinha
                    key={idx}
                    onClick={() => setDetalheItem(it)}
                    titulo={it.tipo_proposta || "Sem tipo de proposta"}
                    valor={formatCurrency(it.valor_proposta)}
                    meta={
                      <>
                        {it.tipo_recurso && <Selo title={it.tipo_recurso}>{it.tipo_recurso}</Selo>}
                        {parls.length > 0 ? (
                          <span className="truncate" title={nomes}>
                            {parls.slice(0, 2).map((p) => p.nome).join(", ")}
                            {parls.length > 2 ? ` +${parls.length - 2}` : ""}
                          </span>
                        ) : (
                          <span>sem parlamentar vinculado</span>
                        )}
                      </>
                    }
                    acao={
                      <button
                        type="button"
                        onClick={() => setDetalheItem(it)}
                        className="inline-flex size-7 items-center justify-center rounded hover:opacity-90"
                        style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                        title="Ver detalhamento"
                        aria-label="Ver detalhamento"
                      >
                        <Eye className="size-3.5" />
                      </button>
                    }
                  >
                    <Campos
                      campos={[
                        { rotulo: "Ano", valor: it.ano || "—" },
                        {
                          rotulo: "Nº processo",
                          valor: it.nu_processo || "—",
                          title: it.nu_processo || "Sem processo informado",
                        },
                        { rotulo: "Valor pago", valor: formatCurrency(it.valor_pago) },
                        {
                          rotulo: "A pagar",
                          valor: formatCurrency(it.valor_pagar),
                          tom: (it.valor_pagar || 0) > 0 ? "atencao" : "normal",
                        },
                        {
                          rotulo: "% pago",
                          valor: pct != null ? `${pct}%` : "—",
                          tom: pct != null && pct >= 100 ? "ok" : "normal",
                          title: `${formatCurrency(it.valor_pago)} de ${formatCurrency(it.valor_proposta)}`,
                        },
                      ]}
                    />
                  </ItemLinha>
                );
              })}
            </Lista>
          )}
        </div>
      )}

      {/* Modal Detalhamento — NIVEL 1 */}
      {detalheItem && (
        <Modal aberto maxW="max-w-4xl" onFechar={() => setDetalheItem(null)}>
          <ModalHead
            titulo="Detalhamento por tipo de proposta e tipo de recurso"
            sub={`${data?.params?.municipio ?? "—"}/${data?.params?.uf ?? "—"} · ${data?.params?.ano ?? "—"}`}
            onFechar={() => setDetalheItem(null)}
          />
          <ModalCorpo className="space-y-2.5">
              <Secao
                icon={FileText}
                titulo="Dados da proposta agrupada"
                sub={detalheItem.tipo_recurso}
                campos={[
                  { rotulo: "Estado", valor: data?.params?.uf ?? "—" },
                  { rotulo: "Município", valor: data?.params?.municipio ?? "—", title: String(data?.params?.municipio ?? "") },
                  { rotulo: "Ano", valor: detalheItem.ano ?? data?.params?.ano ?? "—" },
                  { rotulo: "Tipo de recurso", valor: detalheItem.tipo_recurso || "—", title: detalheItem.tipo_recurso },
                  { rotulo: "Tipo de proposta", valor: detalheItem.tipo_proposta || "—", title: detalheItem.tipo_proposta },
                  { rotulo: "Nº processo", valor: detalheItem.nu_processo || "—", title: detalheItem.nu_processo },
                  {
                    rotulo: "Processo constituído",
                    valor: detalheItem.constituido_processo ? "Sim" : "Não",
                    // Sem processo constituido o dinheiro nao anda — e o unico
                    // campo deste bloco que pede providencia.
                    tom: detalheItem.constituido_processo ? "normal" : "atencao",
                  },
                  { rotulo: "Qtd. pagamentos", valor: String(detalheItem.pagamentos_count ?? 0) },
                  { rotulo: "Valor proposta", valor: formatCurrency(detalheItem.valor_proposta) },
                  { rotulo: "Valor pago", valor: formatCurrency(detalheItem.valor_pago) },
                  {
                    rotulo: "A pagar",
                    valor: formatCurrency(detalheItem.valor_pagar),
                    tom: (detalheItem.valor_pagar || 0) > 0 ? "atencao" : "normal",
                  },
                  {
                    rotulo: "% pago",
                    valor: (() => {
                      const p = pctPago(detalheItem.valor_proposta, detalheItem.valor_pago);
                      return p != null ? `${p}%` : "—";
                    })(),
                  },
                ]}
              />

              {/* Parlamentares */}
              {(detalheItem.parlamentares || []).length > 0 && (
                <Bloco className="p-3">
                  <BlocoHead
                    icon={Users}
                    titulo="Parlamentares"
                    sub={`${detalheItem.parlamentares?.length} vinculado(s) à proposta`}
                  />
                  <div className="flex flex-wrap gap-1.5">
                    {(detalheItem.parlamentares || []).map((p, i) => (
                      <Selo key={i} title={p.partido ? `${p.nome} · ${p.partido}` : p.nome}>
                        {p.nome}{p.partido ? ` (${p.partido})` : ""}
                      </Selo>
                    ))}
                  </div>
                </Bloco>
              )}

              {/* Propostas individuais (nivel 1 listagem) */}
              <Bloco className="p-3">
                <BlocoHead
                  icon={Building2}
                  titulo="Propostas individuais (Nº SIPA)"
                  sub={individuais ? `${individuais.length} proposta(s)` : "buscando no portal..."}
                />
                {loadingIndiv ? (
                  <div className="flex justify-center py-5">
                    <Loader2 className="size-5 animate-spin" style={{ color: "var(--bi-muted)" }} />
                  </div>
                ) : (individuais && individuais.length > 0) ? (
                  <Lista>
                    {individuais.map((i, idx) => {
                      const pct = pctPago(i.valor_proposta, i.valor_pago);
                      return (
                        <ItemLinha
                          key={idx}
                          titulo={i.entidade || "Entidade não informada"}
                          valor={formatCurrency(i.valor_proposta)}
                          meta={
                            <>
                              {i.tipo_recurso && <Selo title={i.tipo_recurso}>{i.tipo_recurso}</Selo>}
                              {i.tipo_proposta && <span className="truncate">{i.tipo_proposta}</span>}
                              <span className="font-mono">· nº {i.nu_proposta}</span>
                            </>
                          }
                          acao={
                            <button
                              type="button"
                              onClick={() => abrirDetalheProposta(i.nu_proposta)}
                              className="inline-flex size-6 items-center justify-center rounded hover:opacity-90"
                              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                              title="Ver detalhes"
                              aria-label={`Ver detalhes da proposta ${i.nu_proposta}`}
                            >
                              <Eye className="size-3" />
                            </button>
                          }
                        >
                          <Campos
                            campos={[
                              { rotulo: "Valor pago", valor: formatCurrency(i.valor_pago) },
                              {
                                rotulo: "% pago",
                                valor: pct != null ? `${pct}%` : "—",
                                tom: pct != null && pct >= 100 ? "ok" : "normal",
                              },
                            ]}
                          />
                        </ItemLinha>
                      );
                    })}
                  </Lista>
                ) : (
                  <Vazio>Nenhuma proposta individual encontrada para esse grupo no FNS.</Vazio>
                )}
              </Bloco>
          </ModalCorpo>
        </Modal>
      )}

      {/* Modal NÍVEL 2: Detalhe Completo da Proposta Individual */}
      {(propostaDetalhe || loadingDetalhe) && (
        <Modal aberto nivel={2} maxW="max-w-5xl" onFechar={() => setPropostaDetalhe(null)}>
          <ModalHead
            titulo={`Detalhe da proposta ${propostaDetalhe?.nu_proposta || ""}`}
            sub={propostaDetalhe ? `${propostaDetalhe.municipio}/${propostaDetalhe.uf} · ${propostaDetalhe.ano}` : undefined}
            onFechar={() => setPropostaDetalhe(null)}
          />
          <ModalCorpo className="space-y-2.5">
              {loadingDetalhe && (
                <div className="flex justify-center py-12">
                  <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
                </div>
              )}

              {propostaDetalhe && (
                <>
                  <Secao
                    icon={Building2}
                    titulo="Dados da entidade"
                    campos={[
                      { rotulo: "Estado", valor: propostaDetalhe.uf },
                      { rotulo: "Município", valor: propostaDetalhe.municipio, title: propostaDetalhe.municipio },
                      { rotulo: "Entidade", valor: propostaDetalhe.entidade, title: propostaDetalhe.entidade },
                      { rotulo: "CNPJ", valor: propostaDetalhe.cnpj },
                    ]}
                  />

                  <Secao
                    icon={FileText}
                    titulo="Dados da proposta"
                    sub={propostaDetalhe.tipo_recurso}
                    campos={[
                      { rotulo: "Nº da proposta", valor: propostaDetalhe.nu_proposta },
                      { rotulo: "Tipo de proposta", valor: propostaDetalhe.tipo_proposta, title: propostaDetalhe.tipo_proposta },
                      { rotulo: "Tipo de recurso", valor: propostaDetalhe.tipo_recurso, title: propostaDetalhe.tipo_recurso },
                      { rotulo: "Esfera", valor: propostaDetalhe.esfera || "—" },
                      { rotulo: "Ano", valor: propostaDetalhe.ano },
                      { rotulo: "Nº processo", valor: propostaDetalhe.nu_processo || "—", title: propostaDetalhe.nu_processo },
                      { rotulo: "Nº portaria", valor: propostaDetalhe.nu_portaria || "—" },
                      { rotulo: "Data portaria", valor: dataBR(propostaDetalhe.data_portaria) },
                      { rotulo: "Valor da proposta", valor: formatCurrency(propostaDetalhe.valor_proposta) },
                      { rotulo: "Total empenhado", valor: formatCurrency(propostaDetalhe.vl_empenhado) },
                      { rotulo: "Valor pago", valor: formatCurrency(propostaDetalhe.vl_pago) },
                      {
                        rotulo: "Valor a pagar",
                        valor: formatCurrency(propostaDetalhe.vl_pagar),
                        tom: (propostaDetalhe.vl_pagar || 0) > 0 ? "atencao" : "normal",
                      },
                    ]}
                  />

                  {/* A situacao passa pelo `situacaoTom` importado — a MESMA regra
                      do resto do sistema. Antes era verde fixo, o que pintava de
                      "tudo certo" ate proposta cancelada. */}
                  <Secao
                    icon={Route}
                    titulo="Dados da situação da proposta"
                    campos={[
                      {
                        rotulo: "Situação atual",
                        valor: (
                          <Selo tom={situacaoTom(propostaDetalhe.situacao_descricao)} title={propostaDetalhe.situacao_descricao}>
                            {propostaDetalhe.situacao_descricao || "—"}
                          </Selo>
                        ),
                      },
                      { rotulo: "Última atualização", valor: dataBR(propostaDetalhe.situacao_data) },
                      { rotulo: "Processo constituído", valor: propostaDetalhe.constituido_processo ? "Sim" : "Não",
                        tom: propostaDetalhe.constituido_processo ? "normal" : "atencao" },
                      { rotulo: "Etapa atual", valor: propostaDetalhe.etapa_atual ?? "—" },
                    ]}
                  />

                  {/* Principais etapas - workflow 12 dots */}
                  {propostaDetalhe.etapas && propostaDetalhe.etapas.length > 0 && (
                    <Bloco className="p-3">
                      <BlocoHead
                        icon={Route}
                        titulo="Principais etapas da proposta"
                        sub={`${propostaDetalhe.etapas.filter((e) => e.completada).length} de ${propostaDetalhe.etapas.length} concluída(s)`}
                      />
                      <div className="bi-scroll flex items-start justify-between overflow-x-auto pt-1">
                        {propostaDetalhe.etapas.map((et, i) => (
                          <React.Fragment key={i}>
                            <div className="flex min-w-[60px] flex-col items-center text-center" title={et.descricao}>
                              {/* A etapa cumprida usa a CTA (quase preta) e a
                                  pendente usa a mesma linha cinza das divisorias:
                                  o progresso se le pelo contraste, sem precisar
                                  de violeta. A etapa atual ganha um contorno de
                                  acento em vez de um preenchimento diferente. */}
                              <div
                                className="grid size-7 shrink-0 place-items-center rounded-full text-[11px] font-bold"
                                style={{
                                  background: et.completada ? "var(--bi-cta)" : "var(--bi-line)",
                                  color: et.completada ? "var(--bi-cta-ink)" : "var(--bi-faint)",
                                  ...(et.atual
                                    ? { outline: "2px solid var(--bi-accent-ink)", outlineOffset: "2px" }
                                    : {}),
                                }}
                              >
                                {et.numero}
                              </div>
                              <div className="mt-1 max-w-[60px] text-[9px] leading-tight" style={{ color: "var(--bi-faint)" }}>
                                {et.descricao}
                              </div>
                            </div>
                            {i < propostaDetalhe.etapas.length - 1 && (
                              <div
                                className="mx-0.5 mt-3 h-1 flex-1"
                                style={{
                                  background: et.completada && propostaDetalhe.etapas[i + 1].completada
                                    ? "var(--bi-cta)"
                                    : "var(--bi-line)",
                                }}
                              />
                            )}
                          </React.Fragment>
                        ))}
                      </div>
                      {!propostaDetalhe.constituido_processo && (
                        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                          <Selo tom="atencao">Sem processo</Selo>
                          Não foi constituído processo para essa proposta.
                        </p>
                      )}
                    </Bloco>
                  )}

                  {/* Dados do Parlamentar */}
                  {propostaDetalhe.parlamentares && propostaDetalhe.parlamentares.length > 0 && (
                    <Bloco className="p-3">
                      <BlocoHead
                        icon={Users}
                        titulo="Dados do parlamentar"
                        sub={`${propostaDetalhe.parlamentares.length} emenda(s)`}
                        right={
                          <span className="bi-num text-[13px]">
                            {formatCurrency(propostaDetalhe.parlamentares.reduce((s, p) => s + (p.valor || 0), 0))}
                          </span>
                        }
                      />
                      <Lista>
                        {propostaDetalhe.parlamentares.map((p, i) => (
                          <ItemLinha
                            key={i}
                            titulo={p.nome || "Parlamentar não informado"}
                            valor={formatCurrency(p.valor)}
                          >
                            <Campos
                              campos={[
                                { rotulo: "Partido", valor: p.partido || "—" },
                                { rotulo: "Nº da emenda", valor: p.nu_emenda || "—", title: p.nu_emenda },
                                { rotulo: "Ano", valor: p.ano || "—" },
                              ]}
                            />
                          </ItemLinha>
                        ))}
                      </Lista>
                    </Bloco>
                  )}

                  {/* Dados do Pagamento */}
                  {propostaDetalhe.pagamentos && propostaDetalhe.pagamentos.length > 0 && (
                    <Bloco className="p-3">
                      <BlocoHead
                        icon={Receipt}
                        titulo="Dados do pagamento"
                        sub={`${propostaDetalhe.pagamentos.length} parcela(s)`}
                        right={
                          <span className="bi-num text-[13px]">{formatCurrency(propostaDetalhe.vl_pago)}</span>
                        }
                      />
                      <Lista>
                        {propostaDetalhe.pagamentos.map((pg, i) => (
                          <ItemLinha
                            key={i}
                            titulo={`Parcela ${pg.parcela || "—"}`}
                            valor={formatCurrency(pg.valor)}
                            meta={
                              pg.localizacao
                                ? <span className="truncate" title={pg.localizacao}>{pg.localizacao}</span>
                                : undefined
                            }
                          >
                            <Campos
                              campos={[
                                { rotulo: "Data pagamento", valor: dataBR(pg.data) },
                                { rotulo: "Acumulado", valor: formatCurrency(pg.valor_acumulado) },
                                { rotulo: "Ordem bancária", valor: pg.ordem_bancaria || "—", title: pg.ordem_bancaria },
                                { rotulo: "Nº processo pgto", valor: pg.nu_processo || "—", title: pg.nu_processo },
                              ]}
                            />
                          </ItemLinha>
                        ))}
                      </Lista>
                    </Bloco>
                  )}

                  <div className="flex items-center justify-end gap-2 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                    <Button variant="outline" onClick={() => setPropostaDetalhe(null)}>Voltar</Button>
                    <Button
                      onClick={() => window.print()}
                      className="hover:opacity-90"
                      style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                    >
                      <Printer className="size-4 mr-1" /> Imprimir
                    </Button>
                  </div>
                </>
              )}
          </ModalCorpo>
        </Modal>
      )}
    </div>
  );
}
