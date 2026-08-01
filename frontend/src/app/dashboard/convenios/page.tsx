"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Search as SearchIcon, ChevronLeft, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { MultiSelect } from "@/components/ui/multi-select";
import { PeriodoVigencia } from "@/components/ui/periodo-vigencia";
import { atalhosAnos, intervaloVazio, resumoAnos, rotuloIntervalo, type Intervalo } from "@/lib/periodo";
import { Campos, ItemLinha, Lista, Selo } from "@/components/ui/superficies";
import AnotacaoButton from "@/components/AnotacaoButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { Convenio, ConvenioList } from "@/types";
import ConvenioDetailModal from "./ConvenioDetailModal";

const PER_PAGE = 20;

// Mapeia secretarias estaduais MG e ministerios federais para sigla curta
const SIGLAS: Record<string, string> = {
  "SECRETARIA DE ESTADO DE SAUDE": "SES",
  "SECRETARIA DE ESTADO DE GOVERNO": "SEGOV",
  "SECRETARIA DE ESTADO DE EDUCACAO": "SEE",
  "SECRETARIA DE ESTADO DE DESENVOLVIMENTO ECONOMICO": "SEDE",
  "SECRETARIA DE ESTADO DE DESENVOLVIMENTO SOCIAL": "SEDESE",
  "SECRETARIA DE ESTADO DE INFRAESTRUTURA": "SEINFRA",
  "SECRETARIA DE ESTADO DE AGRICULTURA": "SEAPA",
  "SECRETARIA DE ESTADO DE CULTURA": "SECULT",
  "SECRETARIA DE ESTADO DE ESPORTES": "SEESP",
  "SECRETARIA DE ESTADO DE TURISMO": "SETUR",
  "SECRETARIA DE ESTADO DE MEIO AMBIENTE": "SEMAD",
  "SECRETARIA DE ESTADO DE PLANEJAMENTO": "SEPLAG",
  "MINISTERIO DA SAUDE": "Min. Saude",
  "MINISTERIO DA FAZENDA": "Min. Fazenda",
  "MINISTERIO DA EDUCACAO": "Min. Educacao",
  "MINISTERIO DO ESPORTE": "Min. Esporte",
  "MINISTERIO DA INTEGRACAO": "MI",
  "MINISTERIO DA INTEGRA": "MI",
  "MINISTERIO DO DESENVOLVIMENTO": "MDS",
  "MINISTERIO DA AGRICULTURA": "Min. Agricultura",
  "MINISTERIO DAS CIDADES": "Min. Cidades",
};

// Codigos numericos SIAFI dos orgaos federais (TransfereGov usa esses)
// Ref: https://www.planejamento.gov.br/transferegov - cod orgao superior
const ORGAO_FED_CODIGOS: Record<string, { sigla: string; nome: string }> = {
  "20000": { sigla: "PR",          nome: "Presidência da República" },
  "22000": { sigla: "MAPA",        nome: "Min. Agricultura, Pecuária e Abastecimento" },
  "24000": { sigla: "MCTI",        nome: "Min. Ciência, Tecnologia e Inovação" },
  "25000": { sigla: "MF",          nome: "Min. Fazenda" },
  "26000": { sigla: "MEC",         nome: "Min. Educação" },
  "30000": { sigla: "MJ",          nome: "Min. Justiça e Segurança Pública" },
  "33000": { sigla: "MPS",         nome: "Min. Previdência Social" },
  "35000": { sigla: "MRE",         nome: "Min. Relações Exteriores" },
  "36000": { sigla: "Min. Saúde",  nome: "Min. Saúde" },
  "38000": { sigla: "MTb",         nome: "Min. Trabalho e Emprego" },
  "39000": { sigla: "MT",          nome: "Min. Transportes" },
  "41000": { sigla: "MinC",        nome: "Min. Cultura" },
  "42000": { sigla: "MinC",        nome: "Min. Cultura" },
  "44000": { sigla: "MMA",         nome: "Min. Meio Ambiente" },
  "49000": { sigla: "MDA",         nome: "Min. Desenvolvimento Agrário" },
  "51000": { sigla: "Min. Esporte", nome: "Min. Esporte" },
  "52000": { sigla: "MD",          nome: "Min. Defesa" },
  "53000": { sigla: "MIDR",        nome: "Min. Integração e Desenvolvimento Regional" },
  "54000": { sigla: "MTur",        nome: "Min. Turismo" },
  "55000": { sigla: "MDS",         nome: "Min. Desenvolvimento Social" },
  "56000": { sigla: "MCID",        nome: "Min. Cidades" },
  "58000": { sigla: "MPO",         nome: "Min. Planejamento e Orçamento" },
};

function siglaOrgao(o?: string | null): string {
  if (!o) return "-";
  const trimmed = o.trim();
  // Codigo federal, sozinho ("22000") OU prefixando o nome, que e a forma que
  // o TransfereGov entrega de verdade: "54000 - MINISTERIO DO TURISMO".
  // O teste antigo exigia a string INTEIRA numerica, entao nunca casava com a
  // segunda forma — e TODO orgao federal caia no corte cego do final.
  const comCodigo = /^(\d{4,6})\b/.exec(trimmed);
  if (comCodigo && ORGAO_FED_CODIGOS[comCodigo[1]]) {
    return ORGAO_FED_CODIGOS[comCodigo[1]].sigla;
  }
  const up = trimmed.toUpperCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  for (const [k, sig] of Object.entries(SIGLAS)) {
    if (up.startsWith(k)) return sig;
  }
  // Sem sigla conhecida, devolve o nome INTEIRO. Cortar em 18 caracteres com
  // `slice` transformava "MINISTERIO DO DESENVOLVIMENTO REGIONAL" e
  // "MINISTERIO DO DESENVOLVIMENTO SOCIAL" no mesmo "MINISTERIO DO DESE...".
  // Quem controla o espaco agora e a celula (que quebra a linha), nao a string.
  return trimmed;
}

function nomeOrgaoFull(o?: string | null): string {
  if (!o) return "";
  const trimmed = o.trim();
  if (/^\d{4,6}$/.test(trimmed) && ORGAO_FED_CODIGOS[trimmed]) {
    const m = ORGAO_FED_CODIGOS[trimmed];
    return `${trimmed} - ${m.nome}`;
  }
  return trimmed;
}

/** Cor no selo de situacao SO quando ela e um alerta.
 *
 *  No sistema antigo toda situacao vinha pintada — dez selos coloridos numa
 *  tela, e nenhum deles significando nada. A identidade do Painel e o inverso:
 *  cinza por padrao, cor quando exige acao. */
function situacaoTom(s?: string | null): "neutro" | "ok" | "atencao" | "critico" {
  const t = (s || "").toLowerCase();
  if (/(cancelad|rescindid|impedid|rejeitad|inadimpl)/.test(t)) return "critico";
  if (/(pendente|an[áa]lise|suspens|aguardando)/.test(t)) return "atencao";
  if (/(conclu[íi]d|prestac|encerrad)/.test(t)) return "ok";
  return "neutro";
}

function isTE(objeto?: string | null): boolean {
  return !!objeto && /TRANSFER[ÊE]NCIA\s+ESPECIAL/i.test(objeto);
}

/** Faixas de vencimento. Multi-escolha: marcar duas traz a UNIAO das duas.
 *  "Vence em 30" e subconjunto de "vence em 60" — marcar os dois e o mesmo que
 *  marcar so o maior, e isso e o comportamento esperado. */
const VIGENCIA_OPCOES = ["vence30", "vence60", "vence90", "vence120", "prestacao"];
const VIGENCIA_LABELS: Record<string, string> = {
  vence30: "Vence em 30 dias",
  vence60: "Vence em 60 dias",
  vence90: "Vence em 90 dias",
  vence120: "Vence em 120 dias",
  prestacao: "Prestação de Contas (vencida há +90 dias)",
};

const PAGAMENTO_OPCOES = ["pago", "parcial", "nao_pago"];
const PAGAMENTO_LABELS: Record<string, string> = {
  pago: "Pago (integral)",
  parcial: "Pago parcialmente",
  nao_pago: "Pendente (não pago)",
};

/** As fontes que convivem em `convenios_estadual`.
 *
 *  Elas nao sao esferas diferentes — sao ORIGENS diferentes de dado dentro da
 *  mesma tabela. Em Monte Siao: 81 registros do SIGCON-MG (convenio estadual de
 *  verdade) e 48 do Fundo Nacional de Saude (propostas federais que caem aqui
 *  por herança do modelo). Separar as duas e a pergunta real do gestor; o
 *  antigo "Federal / Estadual" nao separava nada.
 *
 *  O valor "SIGCON" e traduzido no backend para casar tambem com fonte NULL e
 *  "SIGCON-MG" (backend/routers/convenios.py:180-191) — nao trocar por
 *  "SIGCON-MG" aqui sem olhar la. */
const FONTES_OPCOES = ["SIGCON", "FNS"];
const FONTES_ROTULOS: Record<string, string> = {
  SIGCON: "SIGCON-MG (convênio estadual)",
  FNS: "Fundo Nacional de Saúde",
};

export default function ConveniosPage() {
  const searchParams = useSearchParams();
  const municipioId = useMunicipio().municipioId || null;
  const vigenciaParam = searchParams.get("vigencia");

  const [data, setData] = useState<ConvenioList | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [selectedConv, setSelectedConv] = useState<{ id: number; esfera: string } | null>(null);
  // ANTES era `esfera` ("todos"/"federal"/"estadual"), e era um filtro MORTO:
  // o endpoint GET /convenios nao tem parametro `esfera`, o FastAPI descartava
  // em silencio e escolher "Federal" devolvia a mesma lista. O proprio backend
  // diz no cabecalho: "Apos refactor lean, mantemos apenas a esfera estadual."
  // No lugar entra FONTE, que e a distincao que existe de verdade nesta tabela
  // (SIGCON-MG e FNS convivem nela) e que o backend ja aceita como lista.
  const [fontesSel, setFontesSel] = useState<string[]>([]);
  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  // Tudo em lista: o dono pediu poder marcar "um, dois, tres ou todos" em
  // qualquer filtro do sistema. Vazio = todos, mesma convencao do MultiSelect
  // e do backend (que simplesmente nao aplica o filtro).
  const [pagamentosSel, setPagamentosSel] = useState<string[]>([]);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  // O KPI do dashboard entra aqui por querystring com UM valor — continua
  // funcionando, so que agora como lista de um item.
  const [vigenciasSel, setVigenciasSel] = useState<string[]>(
    vigenciaParam ? [vigenciaParam] : [],
  );
  const [intervalo, setIntervalo] = useState<Intervalo>({});
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [situacoes, setSituacoes] = useState<string[]>([]);
  const [anos, setAnos] = useState<number[]>([]);

  // Load distinct situacoes and anos for this municipio
  useEffect(() => {
    if (!municipioId) return;
    api
      .get<string[]>("/convenios/situacoes", { params: { municipio_id: municipioId } })
      .then((res) => setSituacoes(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});
    api
      .get<number[]>("/convenios/anos", { params: { municipio_id: municipioId } })
      .then((res) => setAnos(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});
  }, [municipioId]);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 400);
    return () => clearTimeout(timer);
  }, [searchTerm]);

  // Sincroniza filtro de vigencia com o parametro da URL (vindo dos KPIs do
  // dashboard, que continuam mandando UM valor — vira lista de um item).
  useEffect(() => {
    setVigenciasSel(vigenciaParam ? [vigenciaParam] : []);
  }, [vigenciaParam]);

  // Reset page on filter change
  useEffect(() => {
    setPage(1);
  }, [fontesSel, situacoesSel, pagamentosSel, anosSel, vigenciasSel, intervalo, debouncedSearch]);

  const fetchData = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);

    const params: Record<string, string | number | string[]> = {
      municipio_id: municipioId,
      page,
      per_page: PER_PAGE,
    };
    if (fontesSel.length) params.fontes = fontesSel;
    if (situacoesSel.length) params.situacoes = situacoesSel;
    if (pagamentosSel.length) params.pagamentos = pagamentosSel;
    if (anosSel.length) params.anos = anosSel;
    if (vigenciasSel.length) params.vigencias = vigenciasSel;
    if (intervalo.de) params.vig_fim_de = intervalo.de;
    if (intervalo.ate) params.vig_fim_ate = intervalo.ate;
    if (debouncedSearch) params.search = debouncedSearch;

    api
      .get<ConvenioList>("/convenios", { params })
      .then((res) => setData(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [municipioId, page, fontesSel, situacoesSel, pagamentosSel, anosSel, vigenciasSel, intervalo, debouncedSearch]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);

  const handleRefreshSigcon = useCallback(async () => {
    setRefreshing(true);
    setRefreshMsg(null);
    try {
      const r = await api.post<{ status: string; message: string }>("/convenios/refresh-sigcon");
      setRefreshMsg(r.data.message || "Sincronizando...");
      // Polling: refaz fetchData a cada 30s ate 3min
      let tries = 0;
      const interval = setInterval(() => {
        tries++;
        fetchData();
        if (tries >= 6) {
          clearInterval(interval);
          setRefreshing(false);
          setRefreshMsg(null);
        }
      }, 30_000);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setRefreshMsg(err.response?.data?.detail || "Falha ao iniciar refresh");
      setRefreshing(false);
    }
  }, [fetchData]);

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar convenios.
      </div>
    );
  }

  const items = data?.items ?? [];
  const totalPages = data?.pages ?? 1;

  const exportPdf = () => {
    const token = localStorage.getItem("pactha_token");
    const url = `${api.defaults.baseURL}/export-pdf/convenios?municipio_id=${municipioId}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const u = URL.createObjectURL(blob);
        window.open(u, "_blank");
      });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-base-content">Convênios (SIGCON-MG)</h1>
        <div className="flex items-center gap-2">
          {refreshMsg && (
            <span className="text-xs text-base-content/70 italic">{refreshMsg}</span>
          )}
          <Button onClick={exportPdf} size="sm" variant="outline" title="Exportar para PDF">
            📄 PDF
          </Button>
          <Button
            onClick={handleRefreshSigcon}
            disabled={refreshing}
            size="sm"
            className="bg-primary hover:bg-primary/90"
            title="Forca atualizacao via portal SIGCON-MG (Pesquisa Unificada)"
          >
            <SearchIcon className="size-4 mr-1" />
            {refreshing ? "Sincronizando..." : "Pesquisar SIGCON"}
          </Button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Fonte, nao "esfera": a coluna Fonte da tabela ja mostra esses
            mesmos valores, e agora da para filtrar por eles — um ou varios. */}
        <MultiSelect
          opcoes={FONTES_OPCOES}
          rotulos={FONTES_ROTULOS}
          valor={fontesSel}
          onChange={setFontesSel}
          placeholder="Todas as fontes"
          rotuloTodos="Todas as fontes"
          ariaLabel="Fonte do convênio"
          className="w-56"
        />

        <MultiSelect
          opcoes={situacoes}
          valor={situacoesSel}
          onChange={setSituacoesSel}
          placeholder="Todas as situações"
          rotuloTodos="Todas"
          ariaLabel="Situações"
          className="w-56"
        />

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
          opcoes={VIGENCIA_OPCOES}
          rotulos={VIGENCIA_LABELS}
          valor={vigenciasSel}
          onChange={setVigenciasSel}
          placeholder="Toda a vigência"
          rotuloTodos="Toda a vigência"
          ariaLabel="Vigência"
          className="w-56"
        />

        <MultiSelect
          opcoes={PAGAMENTO_OPCOES}
          rotulos={PAGAMENTO_LABELS}
          valor={pagamentosSel}
          onChange={setPagamentosSel}
          placeholder="Todo pagamento"
          rotuloTodos="Todo pagamento"
          ariaLabel="Situação de pagamento"
          className="w-48"
        />

        {/* PERIODO LIVRE, por FIM DE VIGENCIA. Convivem com os anos de
            proposito: ano recorta o exercicio do convenio, o intervalo recorta
            o vencimento. Sao perguntas diferentes e somam bem. */}
        <PeriodoVigencia valor={intervalo} onChange={setIntervalo} />

        <div className="relative flex-1 min-w-[200px]">
          <SearchIcon className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por nº, proposta, plano, instrumento, SIAFI ou objeto..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {/* Chips dos filtros ativos. Com multi-escolha isso deixa de ser enfeite:
          o gatilho do dropdown resume como "3 selecionados", e sem os chips o
          gestor nao sabe QUAIS tres — nem que ha um periodo aplicado. */}
      {(vigenciasSel.length > 0 || !intervaloVazio(intervalo)) && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-base-content/60">Filtros ativos:</span>
          {vigenciasSel.map((v) => (
            <span key={v} className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 border border-primary px-2.5 py-0.5 text-xs font-medium text-primary">
              {VIGENCIA_LABELS[v] ?? v}
              <button
                onClick={() => setVigenciasSel(vigenciasSel.filter((x) => x !== v))}
                className="text-primary hover:text-primary/90"
                aria-label={`Remover filtro ${VIGENCIA_LABELS[v] ?? v}`}
              >
                ×
              </button>
            </span>
          ))}
          {!intervaloVazio(intervalo) && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 border border-primary px-2.5 py-0.5 text-xs font-medium text-primary">
              Fim da vigência {rotuloIntervalo(intervalo)}
              <button
                onClick={() => setIntervalo({})}
                className="text-primary hover:text-primary/90"
                aria-label="Limpar período"
              >
                ×
              </button>
            </span>
          )}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded bg-base-200" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhum dado encontrado.
        </div>
      ) : (
        <>
          {/* A LISTA DEIXOU DE SER TABELA.
              Eram 14 colunas numa grade de linhas finas, com o objeto cortado e
              o violeta em toda parte. Agora cada convenio e um cartao na
              linguagem do Painel: sem borda entre itens, um cinza so para a
              meta, selo cinza em vez de pintado — e a informacao COMPLETA, que
              foi a condicao do dono ("tem q aparecer todas as informaçoes").

              O que torna isso possivel sem virar bagunca e o <Campos>: os
              numeros ficam em POSICOES FIXAS, iguais em todos os cartoes, entao
              o olho continua descendo por uma coluna como descia na tabela. */}
          <Lista>
            {items.map((conv: Convenio) => {
              const objeto = conv.objeto || "";
              const programa = conv.tipo_programa || conv.programa || "";
              const orgao = conv.orgao_concedente || "";
              const dias = conv.dias_restantes;
              const base = conv.valor_repasse ?? conv.valor_total ?? 0;
              const rep = conv.valor_desembolsado;
              const pct = rep != null && base ? Math.round((rep / base) * 100) : null;
              return (
                <ItemLinha
                  key={conv.id}
                  onClick={() => setSelectedConv({ id: conv.id, esfera: conv.esfera })}
                  titulo={
                    <span className="flex items-start gap-1.5">
                      {isTE(conv.objeto) && <Selo tom="acento">TE</Selo>}
                      <span>{objeto || "Sem objeto informado"}</span>
                    </span>
                  }
                  valor={formatCurrency(conv.valor_repasse ?? conv.valor_total)}
                  acao={
                    <span onClick={(e) => e.stopPropagation()}>
                      <AnotacaoButton
                        fonte="sigcon"
                        fonteRef={String(conv.id)}
                        municipioId={Number(municipioId)}
                        numero={conv.nr_instrumento || conv.nr_sigcon || conv.nr_proposta || String(conv.id)}
                      />
                    </span>
                  }
                  meta={
                    <>
                      {conv.fonte && <Selo title={conv.fonte}>{conv.fonte.replace("SIGCON-MG", "SIGCON")}</Selo>}
                      {conv.situacao && (
                        <Selo tom={situacaoTom(conv.situacao)} title={conv.situacao}>
                          {conv.situacao}
                        </Selo>
                      )}
                      {orgao && (
                        <span title={nomeOrgaoFull(conv.orgao_concedente) || orgao}>
                          {siglaOrgao(conv.orgao_concedente)}
                        </span>
                      )}
                      {programa && <span className="truncate">· {programa}</span>}
                      {/* Os tres identificadores juntos: servem para ACHAR, nao
                          para comparar, entao nao ocupam coluna na grade. */}
                      <span className="font-mono">
                        {conv.nr_proposta ? `· prop ${conv.nr_proposta}` : ""}
                        {conv.nr_plano_trabalho ? ` · plano ${conv.nr_plano_trabalho}` : ""}
                        {conv.nr_instrumento ? ` · instr ${conv.nr_instrumento}` : ""}
                        {conv.nr_sigcon ? ` · sigcon ${conv.nr_sigcon}` : ""}
                      </span>
                    </>
                  }
                >
                  <Campos
                    campos={[
                      {
                        rotulo: "Repassado",
                        valor: pct != null ? `${pct}%` : "—",
                        tom: pct == null ? "normal" : pct >= 100 ? "ok" : pct > 0 ? "atencao" : "normal",
                        title: rep != null ? `${formatCurrency(rep)} de ${formatCurrency(base)}` : "Sem informação de repasse",
                      },
                      {
                        rotulo: "Contrapartida",
                        valor: conv.valor_contrapartida ? formatCurrency(conv.valor_contrapartida) : "—",
                      },
                      { rotulo: "Assinatura", valor: formatDate(conv.dt_inicio) || "—" },
                      { rotulo: "Fim da vigência", valor: formatDate(conv.dt_fim_vigencia) || "—" },
                      {
                        rotulo: dias != null && dias < 0 ? "Vencido há" : "Dias restantes",
                        valor: dias != null ? `${Math.abs(dias)}d` : "—",
                        tom: dias == null ? "normal" : dias < 0 ? "critico" : dias <= 60 ? "atencao" : "ok",
                      },
                    ]}
                  />
                </ItemLinha>
              );
            })}
          </Lista>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Pagina {page} de {totalPages} ({data?.total ?? 0} registros)
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft className="size-4" />
                Anterior
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Proximo
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}

      <ConvenioDetailModal conv={selectedConv} onClose={() => setSelectedConv(null)} />
    </div>
  );
}
