"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Search, Eye, Loader2, Eraser, RefreshCw,
  ClipboardList, Building2, Landmark, FileText, Banknote, TrendingUp,
} from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Abas, Bloco, BlocoHead, Campo, Campos, ItemLinha, Lista, Modal, ModalCorpo,
  ModalHead, Secao, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";
import { formatCurrency } from "@/lib/utils";

/** Preserva o `-` do helper `Field` que existia aqui: a peça `Campos` renderiza
 *  o que receber, e rótulo com nada embaixo parece falha de carregamento.
 *  `0` não é vazio — "0 meses em execução" é um dado. */
function campoP(rotulo: string, valor: unknown, extra?: Partial<Campo>): Campo {
  const v = valor === null || valor === undefined || valor === "" ? "-" : String(valor);
  return { rotulo, valor: v, title: v === "-" ? undefined : `${rotulo}: ${v}`, ...extra };
}

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

      {/* Modal Detalhe */}
      {(detalhe !== null || loadingDetalhe) && (
        <Modal aberto onFechar={() => setDetalhe(null)} maxW="max-w-5xl">
          <ModalHead
            titulo="Dados do Plano de Ação"
            sub={
              detalhe?.plano
                ? `${detalhe.plano.programaF}-${String(detalhe.plano.codigoSufixo || "").padStart(6, "0")} / ${detalhe.plano.ano}`
                : undefined
            }
            onFechar={() => setDetalhe(null)}
            abaixo={
              detalhe?.plano ? (
                <Abas
                  valor={tab}
                  onChange={(v) => setTab(v)}
                  opcoes={[
                    { valor: "basicos" as const, label: "Dados Básicos" },
                    { valor: "orcamento" as const, label: "Dados Orçamentários" },
                    { valor: "execucao" as const, label: "Execução / Relatório" },
                  ]}
                />
              ) : undefined
            }
          />
          {loadingDetalhe ? (
            <div className="py-16 text-center">
              <Loader2 className="mx-auto size-8 animate-spin" style={{ color: "var(--bi-faint)" }} />
            </div>
          ) : detalhe?.plano ? (
            <ModalCorpo className="flex flex-col gap-3">
              {/* A faixa de identificação: era um bloco cinza de rótulos em
                  negrito grudados no valor. Vira a grade de campos do sistema —
                  mesmos seis dados, alinhados. */}
              <Secao
                icon={ClipboardList}
                titulo="Identificação"
                cols={3}
                campos={[
                  campoP("Plano de Ação", `${detalhe.plano.programaF}-${String(detalhe.plano.codigoSufixo || "").padStart(6, "0")} / ${detalhe.plano.ano}`),
                  campoP("Programa", detalhe.plano.programaF),
                  campoP("Situação", detalhe.plano.situacao),
                  campoP(
                    "Beneficiário",
                    `${detalhe.plano.beneficiario?.cnpj} - ${detalhe.plano.beneficiario?.nome} (${detalhe.plano.beneficiario?.uf})`,
                    { span: 2 },
                  ),
                  campoP("Emenda Parlamentar", detalhe.plano.emendaParlamentar?.codigoEmendaFormatado),
                ]}
              />

              <div key={tab} className="bi-pane-enter flex flex-col gap-3">
              {tab === "basicos" && (
                <>
                  <Secao
                    icon={Building2}
                    titulo="Dados do Beneficiário"
                    campos={[
                      campoP("Beneficiário (Obrigatório)", `${detalhe.plano.beneficiario?.cnpj} - ${detalhe.plano.beneficiario?.nome}`, { span: 2 }),
                      campoP("UF (Obrigatório)", detalhe.plano.beneficiario?.uf),
                      campoP("Código IBGE", detalhe.plano.beneficiario?.ibge),
                      campoP("IDH", detalhe.plano.beneficiario?.idh),
                      campoP("E-mail Câmara", detalhe.plano.emailCamara, { span: 3 }),
                    ]}
                  />
                  <Secao
                    icon={Landmark}
                    titulo="Dados da Emenda Parlamentar"
                    campos={[
                      campoP("Emenda Parlamentar (Obrigatório)", detalhe.plano.emendaParlamentar?.codigoEmendaFormatado),
                      campoP("Parlamentar", detalhe.plano.emendaParlamentar?.nomeParlamentar, { span: 2 }),
                      campoP("Código Parlamentar", detalhe.plano.emendaParlamentar?.codigoParlamentar),
                      campoP("Ano", detalhe.plano.emendaParlamentar?.ano),
                      { rotulo: "Valor de Custeio (Obrigatório)", valor: formatCurrency(detalhe.plano.valorCusteio) },
                      { rotulo: "Valor de Investimento (Obrigatório)", valor: formatCurrency(detalhe.plano.valorInvestimento) },
                    ]}
                  />
                  <Secao icon={FileText} titulo="Dados Complementares do Plano">
                    <Campos
                      cols={2}
                      campos={[
                        campoP("Modalidade", detalhe.plano.modalidade),
                      ]}
                    />
                    {/* Objeto e Motivo de Impedimento saem da grade: são texto
                        livre, às vezes de vários parágrafos, e a célula trunca
                        por desenho. */}
                    <div className="mt-2.5">
                      <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Objeto</div>
                      <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                        {detalhe.plano.objeto || detalhe.plano.objetoDetalhe || "-"}
                      </p>
                    </div>
                    <div className="mt-2.5">
                      <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>Motivo Impedimento</div>
                      <p className="mt-0.5 text-[12px] leading-relaxed break-words" style={{ color: "var(--bi-text)" }}>
                        {detalhe.plano.motivoImpedimento || "-"}
                      </p>
                    </div>
                    <Campos cols={2} campos={[campoP("Anexos", detalhe.plano.listaAPP?.length ?? 0)]} />
                  </Secao>
                </>
              )}

              {tab === "orcamento" && (
                <>
                  <Secao
                    icon={Banknote}
                    titulo="Orçamento do Plano"
                    cols={3}
                    campos={[
                      { rotulo: "Valor de Custeio", valor: formatCurrency(detalhe.plano.valorCusteio) },
                      { rotulo: "Valor de Investimento", valor: formatCurrency(detalhe.plano.valorInvestimento) },
                      { rotulo: "Valor Total", valor: formatCurrency(detalhe.plano.valorTotal) },
                    ]}
                  />
                  {detalhe.plano.emendaParlamentar && (
                    /* Sub-bloco próprio, e não campos soltos: Custeio e
                       Investimento aparecem DUAS vezes no modal, com origens
                       diferentes — o valor do PLANO e o valor da EMENDA. Juntar
                       os quatro numa grade só apagaria a diferença. */
                    <Secao
                      icon={Landmark}
                      titulo="Da Emenda Parlamentar"
                      cols={2}
                      campos={[
                        { rotulo: "Custeio na Emenda", valor: formatCurrency(detalhe.plano.emendaParlamentar.valorCusteio) },
                        { rotulo: "Investimento na Emenda", valor: formatCurrency(detalhe.plano.emendaParlamentar.valorInvestimento) },
                      ]}
                    />
                  )}
                </>
              )}

              {tab === "execucao" && (
                detalhe.resumo ? (
                  <Secao
                    icon={TrendingUp}
                    titulo="Relatório de Gestão"
                    campos={[
                      campoP("Meses em Execução", detalhe.resumo.nrMesesExecucao),
                      { rotulo: "Custeio Previsto", valor: formatCurrency(detalhe.resumo.valorTotalCusteio) },
                      { rotulo: "Investimento Previsto", valor: formatCurrency(detalhe.resumo.valorTotalInvestimento) },
                      { rotulo: "Custeio Executado", valor: formatCurrency(detalhe.resumo.valorTotalCusteioExecutado) },
                      { rotulo: "Investimento Executado", valor: formatCurrency(detalhe.resumo.valorTotalInvestimentoExecutado) },
                      { rotulo: "Total Executado", valor: formatCurrency(detalhe.resumo.valorTotalExecutado), tom: "ok" },
                      { rotulo: "Total Pendente", valor: formatCurrency(detalhe.resumo.valorTotalPendente), tom: "atencao" },
                    ]}
                  />
                ) : (
                  <Vazio>Sem relatório de gestão registrado para este plano.</Vazio>
                )
              )}
              </div>
            </ModalCorpo>
          ) : null}
        </Modal>
      )}
    </div>
  );
}

