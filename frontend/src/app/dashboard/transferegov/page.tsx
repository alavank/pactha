"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Search, Eye, X, Loader2, Eraser, RefreshCw } from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";
import { formatCurrency } from "@/lib/utils";

interface Plano {
  id: number;
  codigo: string;
  programa_codigo: string;
  programa_id: number;
  situacao_plano_acao: string;
  situacao_plano_trabalho: string;
  beneficiario_nome: string;
  beneficiario_cnpj: string;
  uf: string;
  politicas_publicas: string;
  emenda_codigo: string;
  valor_custeio: number;
  valor_investimento: number;
  valor_total: number;
  objeto_descricao?: string;
  motivo_impedimento?: string;
}

interface BuscarResp {
  items: Plano[];
  total: number;
  municipio: { id: number; nome: string; uf: string };
  cache_age_seconds: number;
}

interface DetalhePlano {
  plano?: {
    id: number;
    codigo?: string;
    codigoSufixo?: number;
    ano?: number;
    modalidade?: string;
    situacao?: string;
    motivoImpedimento?: string;
    programaF?: string;
    valorCusteio?: number;
    valorInvestimento?: number;
    valorTotal?: number;
    objeto?: string;
    objetoDetalhe?: string;
    emailCamara?: string;
    beneficiario?: {
      cnpj?: string; nome?: string; uf?: string; ibge?: number;
      idh?: number; enteId?: number; email?: string;
    };
    emendaParlamentar?: {
      codigoEmendaFormatado?: string;
      nomeParlamentar?: string;
      codigoParlamentar?: string;
      ano?: number;
      valorCusteio?: number;
      valorInvestimento?: number;
    };
    listaPO?: unknown[];
    listaAPP?: unknown[];
  };
  resumo?: {
    nrMesesExecucao?: number;
    valorTotalCusteio?: number;
    valorTotalInvestimento?: number;
    valorTotalExecutado?: number;
    valorTotalPendente?: number;
    valorTotalCusteioExecutado?: number;
    valorTotalInvestimentoExecutado?: number;
  };
}

// Vazio = TODAS (convencao do <MultiSelect>), entao "TODAS" saiu da lista de
// opcoes — antes era um valor especial que precisava ser filtrado no envio.
const SITUACOES_PA = ["CIENTE", "EM_ANALISE", "IMPEDIDO", "EM_ELABORACAO", "CONCLUIDA"];
const SITUACOES_PA_LABEL: Record<string, string> = Object.fromEntries(
  SITUACOES_PA.map((s) => [s, s.replace(/_/g, " ")])
);



export default function TransfereGovPage() {
  const { municipioId } = useMunicipio();

  const [items, setItems] = useState<Plano[]>([]);
  const [loading, setLoading] = useState(false);
  const [cacheAge, setCacheAge] = useState(0);
  const [total, setTotal] = useState(0);

  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [programa, setPrograma] = useState("");
  const [parlamentar, setParlamentar] = useState("");
  const [emenda, setEmenda] = useState("");
  const [objeto, setObjeto] = useState("");

  const [detalhe, setDetalhe] = useState<DetalhePlano | null>(null);
  const [loadingDetalhe, setLoadingDetalhe] = useState(false);
  const [tab, setTab] = useState<"basicos" | "orcamento" | "execucao">("basicos");
  const [baixandoPdf, setBaixandoPdf] = useState(false);

  const filtrosParams = useCallback((): Record<string, string | string[]> => {
    // string[] no filtro multi: o axios manda chave repetida e o FastAPI le list[str].
    const params: Record<string, string | string[]> = { municipio_id: municipioId || "" };
    if (situacoesSel.length) params.situacao = situacoesSel;
    if (programa.trim()) params.programa = programa.trim();
    if (parlamentar.trim()) params.parlamentar = parlamentar.trim();
    if (emenda.trim()) params.emenda = emenda.trim();
    if (objeto.trim()) params.objeto = objeto.trim();
    return params;
  }, [municipioId, situacoesSel, programa, parlamentar, emenda, objeto]);

  const buscar = useCallback(async (refresh = false) => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const params: Record<string, string | string[] | boolean> = { ...filtrosParams() };
      if (refresh) params.refresh = true;
      const r = await api.get<BuscarResp>("/transferegov/buscar", { params });
      setItems(r.data.items);
      setTotal(r.data.total);
      setCacheAge(r.data.cache_age_seconds);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [municipioId, filtrosParams]);

  const gerarPdf = useCallback(async () => {
    if (!municipioId) return;
    setBaixandoPdf(true);
    try {
      const r = await api.get("/export-pdf/plano-acao", { params: filtrosParams(), responseType: "blob" });
      const url = window.URL.createObjectURL(new Blob([r.data], { type: "application/pdf" }));
      const a = document.createElement("a");
      a.href = url; a.download = "relatorio-plano-acao.pdf";
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); } finally { setBaixandoPdf(false); }
  }, [municipioId, filtrosParams]);

  useEffect(() => {
    if (municipioId) buscar(false);
  }, [municipioId]); // eslint-disable-line react-hooks/exhaustive-deps

  const limpar = () => {
    setSituacoesSel([]); setPrograma(""); setParlamentar(""); setEmenda(""); setObjeto("");
    setItems([]); setTotal(0);
  };

  const abrirDetalhe = async (id: number) => {
    setDetalhe(null);
    setTab("basicos");
    setLoadingDetalhe(true);
    try {
      const r = await api.get<DetalhePlano>(`/transferegov/plano-acao/${id}`);
      setDetalhe(r.data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingDetalhe(false);
    }
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">
      Selecione um municipio.
    </div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-base-content">Plano de Ação - TransfereGov</h1>
          <p className="text-sm text-base-content/60">Transferência Especial Federal (Pix Parlamentar)</p>
        </div>
        <div className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
          {cacheAge > 0 && `Cache: ${Math.floor(cacheAge / 60)}min`}
        </div>
      </div>

      {/* Filtros — mesmo comportamento de antes, so trocando a caixa de borda
          dura pelo <Bloco> da identidade. */}
      <Bloco className="p-3">
        <BlocoHead icon={Search} titulo="Pesquisa" sub="Escolha um ou mais critérios" />
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>
              Situação do Plano de Ação{" "}
              <span style={{ color: "var(--bi-faint)" }}>(uma, algumas ou todas)</span>
            </label>
            <MultiSelect
              opcoes={SITUACOES_PA}
              valor={situacoesSel}
              onChange={setSituacoesSel}
              rotulos={SITUACOES_PA_LABEL}
              placeholder="TODAS"
              rotuloTodos="TODAS"
              ariaLabel="Situação do plano de ação"
            />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Programa (código)</label>
            <Input value={programa} onChange={(e) => setPrograma(e.target.value)} placeholder="Ex: 09032022" />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Parlamentar (nome)</label>
            <Input value={parlamentar} onChange={(e) => setParlamentar(e.target.value)} placeholder="Ex: LUIS TIBE" />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Emenda Parlamentar (código)</label>
            <Input value={emenda} onChange={(e) => setEmenda(e.target.value)} placeholder="Ex: 202241760007" />
          </div>
          <div>
            <label className="text-[11px] mb-1 block" style={{ color: "var(--bi-muted)" }}>Objeto/Política Pública</label>
            <Input value={objeto} onChange={(e) => setObjeto(e.target.value)} placeholder="Ex: Urbanismo, Saúde" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-3">
          <Button variant="outline" onClick={limpar}><Eraser className="size-4 mr-1" /> Limpar</Button>
          <Button variant="outline" onClick={() => buscar(true)} disabled={loading} title="Refresh cache do TransfereGov">
            <RefreshCw className="size-4 mr-1" /> Atualizar
          </Button>
          {/* Sem `bg-primary` na mão: a variante padrão do Button já é
              `btn-primary`, e a classe só repintava por cima. */}
          <Button onClick={() => buscar(false)} disabled={loading}>
            {loading ? <Loader2 className="size-4 mr-1 animate-spin" /> : <Search className="size-4 mr-1" />}
            Filtrar
          </Button>
          <Button variant="outline" onClick={gerarPdf} disabled={baixandoPdf || items.length === 0}
                  title="Gera um PDF só com os planos filtrados">
            {baixandoPdf ? <Loader2 className="size-4 animate-spin mr-1" /> : null} 📄 Gerar PDF (filtrado)
          </Button>
        </div>
      </Bloco>

      {/* A LISTA DEIXOU DE SER TABELA.
          Eram 8 colunas fixas com selo pintado e cabecalho violeta. Agora cada
          plano e um cartao na linguagem do Painel — sem borda entre itens, um
          cinza so para a meta, cor apenas no que e alerta — e com a informacao
          COMPLETA das 8 colunas: objeto no titulo, valor a direita, situacao do
          plano de acao como selo, emenda/beneficiario/UF/codigo na meta,
          situacao do plano de trabalho e os valores na grade de <Campos>.

          O <Campos> e o que permite trocar tabela por cartao sem perder a
          varredura vertical: as posicoes sao as MESMAS em todos os cartoes,
          entao o olho continua descendo por uma coluna. */}
      <div className="space-y-2">
        <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
          <span className="bi-num">{total}</span> plano(s) de ação
        </div>
        {loading ? (
          <div className="space-y-1.5">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-16 animate-pulse rounded-lg" style={{ background: "var(--bi-surface-2)" }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <Vazio>
            Nenhum plano encontrado. Use os filtros acima e clique em <strong>Filtrar</strong>.
          </Vazio>
        ) : (
          <Lista>
            {items.map((p) => (
              <ItemLinha
                key={p.id}
                /* O corpo inteiro abre o mesmo detalhe do botao ao lado: clicar
                   no cartao e o gesto da identidade, e o botao continua ali
                   porque a coluna "Acoes" precisa seguir visivel e obvia. */
                onClick={() => abrirDetalhe(p.id)}
                titulo={
                  p.objeto_descricao?.trim() ||
                  p.politicas_publicas?.trim() ||
                  p.beneficiario_nome ||
                  "Plano de ação"
                }
                valor={formatCurrency(p.valor_total)}
                acao={
                  <button
                    type="button"
                    onClick={() => abrirDetalhe(p.id)}
                    title="Detalhar"
                    className="grid size-7 place-items-center rounded"
                    style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
                  >
                    <Eye className="size-3.5" />
                  </button>
                }
                meta={
                  <>
                    {p.situacao_plano_acao && (
                      <Selo
                        tom={situacaoTom(p.situacao_plano_acao)}
                        title={`Situação do plano de ação: ${p.situacao_plano_acao}`}
                      >
                        {p.situacao_plano_acao.replace(/_/g, " ")}
                      </Selo>
                    )}
                    {/* O codigo da emenda carrega o NOME do parlamentar
                        ("202135950005-Lincoln Portela"). Cortar tira justamente
                        a parte que diz de QUEM veio o recurso — vai inteiro, e
                        com o cinza mais forte da meta por ser o que o gestor
                        procura primeiro. */}
                    {p.emenda_codigo && (
                      <span
                        className="font-medium"
                        style={{ color: "var(--bi-muted)" }}
                        title="Emenda parlamentar"
                      >
                        {p.emenda_codigo}
                      </span>
                    )}
                    {/* UF colada no beneficiario: sozinha, numa coluna de 42px,
                        ela nao respondia a pergunta de ninguem. */}
                    <span>
                      {p.beneficiario_cnpj} - {p.beneficiario_nome} ({p.uf})
                    </span>
                    {/* Identificadores servem para ACHAR, nao para comparar —
                        por isso ficam na meta e nao ocupam coluna na grade. */}
                    <span className="font-mono">
                      · cód {p.codigo}
                      {p.programa_codigo ? ` · prog ${p.programa_codigo}` : ""}
                    </span>
                  </>
                }
              >
                <Campos
                  campos={[
                    {
                      rotulo: "Situação do plano de trabalho",
                      valor: p.situacao_plano_trabalho || "—",
                      tom: situacaoTom(p.situacao_plano_trabalho),
                      title: p.situacao_plano_trabalho,
                    },
                    { rotulo: "Custeio", valor: formatCurrency(p.valor_custeio) },
                    { rotulo: "Investimento", valor: formatCurrency(p.valor_investimento) },
                    {
                      rotulo: "Motivo de impedimento",
                      valor: p.motivo_impedimento || "—",
                      // Critico so quando ha motivo: sem impedimento o campo e
                      // um traco cinza e nao disputa atencao com nada.
                      tom: p.motivo_impedimento ? "critico" : "normal",
                      title: p.motivo_impedimento,
                    },
                  ]}
                />
              </ItemLinha>
            ))}
          </Lista>
        )}
      </div>

      {/* Modal Detalhe - replica layout TransfereGov oficial */}
      {(detalhe !== null || loadingDetalhe) && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-start justify-center p-4 overflow-y-auto"
             onClick={() => setDetalhe(null)}>
          <div className="bg-base-100 rounded-lg shadow-2xl w-full max-w-6xl mt-4 mb-8" onClick={(e) => e.stopPropagation()}>
            <div className="bg-base-100 px-5 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="text-xl font-light text-base-content">Dados do Plano de Ação</h3>
              <button onClick={() => setDetalhe(null)}><X className="size-5 text-base-content/60 hover:text-base-content/70" /></button>
            </div>
            {loadingDetalhe ? (
              <div className="text-center py-16"><Loader2 className="size-8 animate-spin mx-auto text-primary" /></div>
            ) : detalhe?.plano && (
              <>
                {/* Header cinza */}
                <div className="bg-base-200 px-5 py-3 grid grid-cols-3 gap-4 text-sm border-b">
                  <div>
                    <span className="font-semibold">Plano de Ação:</span>{" "}
                    {detalhe.plano.programaF}-{String(detalhe.plano.codigoSufixo || "").padStart(6,"0")} / {detalhe.plano.ano}
                  </div>
                  <div><span className="font-semibold">Programa:</span> {detalhe.plano.programaF}</div>
                  <div><span className="font-semibold">Situação:</span> {detalhe.plano.situacao}</div>
                  <div className="col-span-2">
                    <span className="font-semibold">Beneficiário:</span> {detalhe.plano.beneficiario?.cnpj} - {detalhe.plano.beneficiario?.nome} ({detalhe.plano.beneficiario?.uf})
                  </div>
                  <div><span className="font-semibold">Emenda Parlamentar:</span> {detalhe.plano.emendaParlamentar?.codigoEmendaFormatado}</div>
                </div>

                {/* Tabs */}
                <div className="border-b flex gap-1 px-5">
                  {[
                    {k:"basicos", l:"Dados Básicos"},
                    {k:"orcamento", l:"Dados Orçamentários"},
                    {k:"execucao", l:"Execução / Relatório"},
                  ].map((t) => (
                    <button
                      key={t.k}
                      onClick={() => setTab(t.k as "basicos"|"orcamento"|"execucao")}
                      className={`px-4 py-2.5 text-sm border-b-2 ${tab === t.k ? "border-primary text-primary font-semibold" : "border-transparent text-base-content/70 hover:text-base-content"}`}
                    >
                      {t.l}
                    </button>
                  ))}
                </div>

                <div className="p-5 space-y-6 max-h-[70vh] overflow-y-auto">
                  {tab === "basicos" && (
                    <>
                      <Section title="Dados do Beneficiário">
                        <Grid>
                          <Field label="Beneficiário (Obrigatório)" value={`${detalhe.plano.beneficiario?.cnpj} - ${detalhe.plano.beneficiario?.nome}`} />
                          <Field label="UF (Obrigatório)" value={detalhe.plano.beneficiario?.uf} />
                          <Field label="Código IBGE" value={detalhe.plano.beneficiario?.ibge} />
                          <Field label="IDH" value={detalhe.plano.beneficiario?.idh} />
                          <Field label="E-mail Câmara" value={detalhe.plano.emailCamara || "-"} />
                        </Grid>
                      </Section>
                      <Section title="Dados da Emenda Parlamentar">
                        <Grid>
                          <Field label="Emenda Parlamentar (Obrigatório)" value={detalhe.plano.emendaParlamentar?.codigoEmendaFormatado} />
                          <Field label="Parlamentar" value={detalhe.plano.emendaParlamentar?.nomeParlamentar} />
                          <Field label="Código Parlamentar" value={detalhe.plano.emendaParlamentar?.codigoParlamentar} />
                          <Field label="Ano" value={detalhe.plano.emendaParlamentar?.ano} />
                          <Field label="Valor de Custeio (Obrigatório)" value={formatCurrency(detalhe.plano.valorCusteio)} />
                          <Field label="Valor de Investimento (Obrigatório)" value={formatCurrency(detalhe.plano.valorInvestimento)} />
                        </Grid>
                      </Section>
                      <Section title="Dados Complementares do Plano">
                        <Grid cols={2}>
                          <Field label="Modalidade" value={detalhe.plano.modalidade} />
                          <Field label="Objeto" value={detalhe.plano.objeto || detalhe.plano.objetoDetalhe || "-"} />
                          <Field label="Motivo Impedimento" value={detalhe.plano.motivoImpedimento || "-"} />
                          <Field label="Anexos" value={(detalhe.plano.listaAPP?.length || 0).toString()} />
                        </Grid>
                      </Section>
                    </>
                  )}
                  {tab === "orcamento" && (
                    <Section title="Orçamento do Plano">
                      <Grid>
                        <Field label="Valor de Custeio" value={formatCurrency(detalhe.plano.valorCusteio)} />
                        <Field label="Valor de Investimento" value={formatCurrency(detalhe.plano.valorInvestimento)} />
                        <Field label="Valor Total" value={formatCurrency(detalhe.plano.valorTotal)} />
                      </Grid>
                      {detalhe.plano.emendaParlamentar && (
                        <div className="mt-4">
                          <h5 className="text-xs font-semibold text-base-content/70 mb-2">Da Emenda Parlamentar</h5>
                          <Grid>
                            <Field label="Custeio na Emenda" value={formatCurrency(detalhe.plano.emendaParlamentar.valorCusteio)} />
                            <Field label="Investimento na Emenda" value={formatCurrency(detalhe.plano.emendaParlamentar.valorInvestimento)} />
                          </Grid>
                        </div>
                      )}
                    </Section>
                  )}
                  {tab === "execucao" && (
                    detalhe.resumo ? (
                      <Section title="Relatório de Gestão">
                        <Grid>
                          <Field label="Meses em Execução" value={detalhe.resumo.nrMesesExecucao} />
                          <Field label="Custeio Previsto" value={formatCurrency(detalhe.resumo.valorTotalCusteio)} />
                          <Field label="Investimento Previsto" value={formatCurrency(detalhe.resumo.valorTotalInvestimento)} />
                          <Field label="Custeio Executado" value={formatCurrency(detalhe.resumo.valorTotalCusteioExecutado)} />
                          <Field label="Investimento Executado" value={formatCurrency(detalhe.resumo.valorTotalInvestimentoExecutado)} />
                          <Field label="Total Executado" value={formatCurrency(detalhe.resumo.valorTotalExecutado)} highlight="green" />
                          <Field label="Total Pendente" value={formatCurrency(detalhe.resumo.valorTotalPendente)} highlight="amber" />
                        </Grid>
                      </Section>
                    ) : (
                      <p className="text-sm text-base-content/60 italic">Sem relatório de gestão registrado para este plano.</p>
                    )
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-sm font-semibold text-base-content border-b border-primary pb-1 mb-3">
        {title}
      </h4>
      <div>{children}</div>
    </div>
  );
}

function Grid({ children, cols = 4 }: { children: React.ReactNode; cols?: 2 | 3 | 4 }) {
  const cls = cols === 2 ? "md:grid-cols-2" : cols === 3 ? "md:grid-cols-3" : "md:grid-cols-4";
  return <div className={`grid grid-cols-1 ${cls} gap-3`}>{children}</div>;
}

function Field({
  label, value, highlight,
}: {
  label: string;
  value?: string | number | null;
  highlight?: "green" | "amber" | "red";
}) {
  const valStr = value === null || value === undefined || value === "" ? "-" : String(value);
  const color =
    highlight === "green" ? "text-success" :
    highlight === "amber" ? "text-warning" :
    highlight === "red" ? "text-error" : "text-base-content";
  return (
    <div>
      <div className="text-[11px] text-base-content/70 mb-0.5">{label}</div>
      <div className={`border border-base-300 rounded px-2 py-1.5 bg-base-200 text-sm ${color}`}>
        {valStr}
      </div>
    </div>
  );
}
