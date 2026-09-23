"use client";

import React, { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { NOME_UF, fonteConveniosEstaduais } from "@/lib/estadual";
import { Search as SearchIcon, ChevronLeft, ChevronRight, ChevronDown } from "lucide-react";
import api from "@/lib/api";
import { MultiSelect } from "@/components/ui/multi-select";
import { PeriodoVigencia } from "@/components/ui/periodo-vigencia";
import { atalhosAnos, intervaloVazio, resumoAnos, rotuloIntervalo, type Intervalo } from "@/lib/periodo";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, situacaoTom } from "@/components/ui/superficies";
import AnotacaoButton, { precarregarContagens } from "@/components/AnotacaoButton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency, formatDate } from "@/lib/utils";
import { formatDataHora, horasDesde } from "@/lib/bi-format";
import type { Convenio, ConvenioList } from "@/types";
import ConvenioDetailModal from "./ConvenioDetailModal";
import { OutrosConvenentes } from "./OutrosConvenentes";
import { TituloTela } from "@/components/TituloTela";

/* CARREGA TUDO, e nao 20 por vez.
 *
 *  Esta tela e o SIGCON, vizinha de Emendas Estaduais no mesmo submenu — e
 *  as duas passaram a ter o mesmo desenho de cartao por ano. Com paginacao de
 *  servidor o cartao contava so o que cabia na pagina ("12 convenio(s) nesta
 *  pagina") enquanto a vizinha mostrava o exercicio inteiro. Dois menus
 *  colados com o mesmo desenho e contagens de significados diferentes.
 *
 *  O que impedia carregar tudo nao era a consulta — era o botao de anotacao de
 *  cada linha, que buscava a contagem UMA A UMA num endpoint que devolve as
 *  anotacoes COM OS ANEXOS em base64. Isso morreu:
 *  `precarregarContagens` traz a lista inteira num GROUP BY so.
 *
 *  2000 e o mesmo teto das Emendas Estaduais. Nenhum municipio chega perto —
 *  e se chegar, a paginacao continua no backend e volta com uma linha. */
const PER_PAGE = 2000;

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
  "MINISTERIO DA SAUDE": "Min. Saúde",
  "MINISTERIO DA FAZENDA": "Min. Fazenda",
  "MINISTERIO DA EDUCACAO": "Min. Educação",
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


function isTE(objeto?: string | null): boolean {
  return !!objeto && /TRANSFER[ÊE]NCIA\s+ESPECIAL/i.test(objeto);
}

/** Rótulo do grupo dos registros sem ano legível. Sempre o ÚLTIMO da lista.
 *  Convênio sem `ano` preenchido não some: some-lo por causa de um campo vazio
 *  na origem é pior do que mostrá-lo separado. */
const SEM_ANO = "Sem ano";

/** O ANO de um convênio = o campo `ano`, que no SIGCON é o EXERCÍCIO.
 *
 *  Não é derivado de `dt_inicio` (assinatura) nem de `dt_fim_vigencia`: é o
 *  MESMO campo que o filtro de anos desta tela já usa — o dropdown vem de
 *  `/convenios/anos` (distinct de `ConvenioEstadual.ano`) e o backend filtra com
 *  `ConvenioEstadual.ano.in_(...)`. Agrupar por uma data faria o gestor
 *  selecionar 2025 no filtro e ver um cartão "2024" na tela.
 *
 *  `ano` é o único campo de exercício que existe aqui: não há `exercicio` nem
 *  no `Convenio` do front nem no modelo do backend. */
function anoDo(c: Convenio): string {
  return c.ano ? String(c.ano) : SEM_ANO;
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
/** RÓTULO das fontes. A LISTA vem do banco (`/convenios/fontes`), não daqui.
 *
 *  Era `["SIGCON","FNS"]` chumbado: num município do ES isso oferecia SIGCON-MG,
 *  que devolve zero, e escondia o GConv-ES, que é o convênio estadual de
 *  verdade (25 linhas do Trust, em 3 municípios). Em 39 dos 65 municípios dos
 *  três clientes a única opção estadual oferecida devolvia ZERO.
 *
 *  Fonte nova na ingestão passa a aparecer sozinha; sem rótulo aqui o
 *  MultiSelect mostra o valor cru, em vez de sumir com a opção. */
const FONTES_ROTULOS: Record<string, string> = {
  SIGCON: "SIGCON-MG (convênio estadual)",
  "SIGCON-MG": "SIGCON-MG (convênio estadual)",
  "GCONV-ES": "GConv-ES (convênio estadual)",
  "SIT-PR": "SIT-PR (convênio estadual)",
  FNS: "Fundo Nacional de Saúde (não é convênio estadual)",
};

/** ⚠️ FALLBACK, e não é paranoia: o CI tem filtro de `paths` — um commit que só
 *  toque o frontend NÃO gera imagem de API — e as tags divergem (api = sha
 *  curto, front = sha completo). Dá para o front novo subir contra uma API que
 *  ainda não tem `/convenios/fontes`: o 404 cai no `.catch`, a lista ficaria
 *  vazia e o filtro Fonte abriria sem nenhuma opção, calado.
 *  Os dois valores continuam válidos no backend porque `_cond_fonte` mantém de
 *  propósito a grafia legada 'SIGCON' (= 'SIGCON-MG' + fonte NULA). */
const FONTES_FALLBACK = ["SIGCON", "FNS"];

export default function ConveniosPage() {
  const searchParams = useSearchParams();
  const municipioId = useMunicipio().municipioId || null;
  /* "" = ainda carregando ou consolidado — nesses casos a tela não
     afirma estado nenhum. */
  const ufAmbiente = useUfDoMunicipio();
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
  /* Recolhido por ANO. Guarda o que está FECHADO e não o que está aberto:
     assim um ano novo que chegue na próxima coleta do SIGCON nasce ABERTO em
     vez de invisível. */
  const [anosFechados, setAnosFechados] = useState<Set<string>>(new Set());
  // O KPI do dashboard entra aqui por querystring com UM valor — continua
  // funcionando, so que agora como lista de um item.
  const [vigenciasSel, setVigenciasSel] = useState<string[]>(
    vigenciaParam ? [vigenciaParam] : [],
  );
  const [intervalo, setIntervalo] = useState<Intervalo>({});
  const [searchTerm, setSearchTerm] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [fontes, setFontes] = useState<string[]>([]);
  const [situacoes, setSituacoes] = useState<string[]>([]);
  const [anos, setAnos] = useState<number[]>([]);

  // Load distinct situacoes and anos for this municipio
  // AS FONTES QUE ESTE MUNICÍPIO TEM DE VERDADE. Efeito PRÓPRIO, sem
  // `fontesSel` nas deps: se dependesse da seleção, a lista de opções
  // encolheria para a própria seleção e não haveria volta.
  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api
      .get<string[]>("/convenios/fontes", { params: { municipio_id: municipioId } })
      .then((res) => {
        if (!vivo) return;
        const opts = Array.isArray(res.data) ? res.data : [];
        // ⚠️ ERRO e LISTA VAZIA são coisas diferentes: [] é resposta legítima
        // (município sem nenhuma linha) e deve continuar vazia. Só o `catch`
        // cai no fallback.
        setFontes(opts);
        // ⚠️ REFERÊNCIA PRESERVADA quando nada foi removido: `sel.filter()`
        // devolve SEMPRE array novo — até `[].filter()` — e `fontesSel` está
        // nas deps do fetch. Sem esta guarda, toda abertura da tela e toda
        // troca de município disparariam uma busca a mais com per_page=2000.
        setFontesSel((sel) => {
          const mantidos = sel.filter((f) => opts.includes(f));
          return mantidos.length === sel.length ? sel : mantidos;
        });
      })
      .catch(() => { if (vivo) setFontes(FONTES_FALLBACK); });
    return () => { vivo = false; };
  }, [municipioId]);

  // Situações e anos seguem a FONTE escolhida — senão o dropdown oferece o que
  // a lista não tem e esconde o que ela tem. Com Fonte=FNS marcada, as duas
  // caixas abriam VAZIAS enquanto a tela mostrava as linhas do FNS atrás.
  useEffect(() => {
    if (!municipioId) return;
    const params: Record<string, string | number | string[]> = { municipio_id: municipioId };
    if (fontesSel.length) params.fontes = fontesSel;
    api
      .get<string[]>("/convenios/situacoes", { params })
      .then((res) => setSituacoes(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});
    api
      .get<number[]>("/convenios/anos", { params })
      .then((res) => setAnos(Array.isArray(res.data) ? res.data : []))
      .catch(() => {});
  }, [municipioId, fontesSel]);

  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anos, setAnosSel);

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

  // Guarda de corrida: na troca A→B duas respostas podem chegar fora de ordem
  // e a de A assentar por cima da de B — com o selo de frescor no payload, isso
  // viraria "Atualizado em" do município errado. Só a resposta mais recente
  // assenta; o reset abaixo cobre o intervalo de loading.
  const reqSeq = useRef(0);
  useEffect(() => {
    setData(null);
  }, [municipioId]);

  /* ⚠️ UMA SÓ MONTAGEM DE FILTROS, usada pela listagem E pelos exports.
   *
   * O `exportPdf` mandava só `{ municipio_id }` — por isso o documento saía com
   * a base inteira mesmo com "Em vigor" marcado. Não era filtro perdido no
   * caminho: ele nunca era enviado. Montar os params em dois lugares é como a
   * divergência volta, então a tela passa a ter uma função só.
   *
   * ⚠️ `debouncedSearch`, e NÃO `searchTerm`: o documento tem de carregar o
   * termo que a tela realmente consultou, não o que está sendo digitado. */
  const filtrosParams = useCallback((): Record<string, string | number | string[]> => {
    // `municipioId` é `string | null` enquanto o contexto carrega. Os dois
    // chamadores já saem cedo quando ele é nulo (`if (!municipioId) return`);
    // o `?? ""` existe só para o tipo, e um `""` nunca chega ao servidor.
    const p: Record<string, string | number | string[]> = { municipio_id: municipioId ?? "" };
    if (fontesSel.length) p.fontes = fontesSel;
    if (situacoesSel.length) p.situacoes = situacoesSel;
    if (pagamentosSel.length) p.pagamentos = pagamentosSel;
    if (anosSel.length) p.anos = anosSel;
    if (vigenciasSel.length) p.vigencias = vigenciasSel;
    if (intervalo.de) p.vig_fim_de = intervalo.de;
    if (intervalo.ate) p.vig_fim_ate = intervalo.ate;
    if (debouncedSearch) p.search = debouncedSearch;
    return p;
  }, [municipioId, fontesSel, situacoesSel, pagamentosSel, anosSel, vigenciasSel,
      intervalo, debouncedSearch]);

  const fetchData = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);

    const params: Record<string, string | number | string[]> = {
      ...filtrosParams(),
      page,
      per_page: PER_PAGE,
    };

    const seq = ++reqSeq.current;
    api
      .get<ConvenioList>("/convenios", { params })
      .then((res) => {
        if (seq === reqSeq.current) setData(res.data);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
    // `filtrosParams` já depende dos oito filtros; repeti-los aqui só criaria
    // duas listas para manter em sincronia.
  }, [municipioId, page, filtrosParams]);

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

  const items = useMemo(() => data?.items ?? [], [data]);

  /* UMA requisição para a contagem de anotações da lista inteira. Sem isto,
     cada linha dispara a sua — e no endpoint que carrega os anexos junto. */
  useEffect(() => {
    if (items.length) precarregarContagens("sigcon", items.map((c) => String(c.id)));
  }, [items]);

  /** Agrupado por ano, do mais recente para o mais antigo.
   *
   *  Mesmo desenho das Emendas Estaduais e das Propostas do TransfereGov: cada
   *  ano é um cartão BRANCO com cabeçalho (ano, contagem, total à direita) e a
   *  lista de itens cinza dentro, sobre o fundo cinza da página.
   *
   *  A tela carrega TUDO (ver `PER_PAGE`), então cada cartão é o exercício
   *  inteiro — a contagem do cabeçalho é o total do ano, não o da página. */
  const porAno = useMemo(() => {
    const m = new Map<string, Convenio[]>();
    for (const c of items) {
      const a = anoDo(c);
      (m.get(a) ?? m.set(a, []).get(a)!).push(c);
    }
    return Array.from(m.entries()).sort((x, y) =>
      x[0] === SEM_ANO ? 1 : y[0] === SEM_ANO ? -1 : y[0].localeCompare(x[0]));
  }, [items]);

  const alternarAno = (a: string) =>
    setAnosFechados((prev) => {
      const n = new Set(prev);
      if (n.has(a)) n.delete(a); else n.add(a);
      return n;
    });

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um município para visualizar convênios.
      </div>
    );
  }

  const totalPages = data?.pages ?? 1;

  // ⚠️ NAO LER `pactha_token` DO localStorage AQUI.
  //
  // O interceptor de `lib/api.ts` APAGA essa chave assim que o primeiro refresh
  // dá certo (a "auto-cura" comentada lá): daí em diante `getItem` devolve null
  // e este fetch mandava `Authorization: Bearer null`. E o backend lê o Bearer
  // ANTES do cookie (`services/auth.py`: `if credentials: token = ...`), então
  // o header inválido ATROPELAVA uma sessão boa e voltava 401 "Token inválido"
  // — não "Token expirado", que é o que confundia o diagnóstico.
  //
  // Pelo `api` o pedido vai com o cookie e, se ainda assim tomar 401, o
  // interceptor renova a sessão e repete sozinho. Um `fetch` cru não tem isso.
  const [exportando, setExportando] = useState<string | null>(null);

  /* ⚠️ MANDA OS FILTROS DA TELA. Era aqui o defeito: ia só `municipio_id`, e o
   * documento saía com a base inteira mesmo com "Em vigor" marcado.
   *
   * ⚠️ PDF ABRE EM ABA; Word e Excel BAIXAM. `window.open` num .xlsx entrega
   * uma aba em branco e o arquivo perdido no perfil do navegador — o formato
   * decide o gesto, não o gosto. */
  const exportar = async (formato: "pdf" | "docx" | "xlsx") => {
    if (!municipioId || exportando) return;
    setExportando(formato);
    try {
      const r = await api.get("/export-pdf/convenios", {
        params: { ...filtrosParams(), formato },
        responseType: "blob",
      });
      const blob = r.data as Blob;
      /* ⚠️ CORPO DE ERRO CHEGA COMO BLOB. Com `responseType: "blob"` um 403 ou
       * 500 vira um Blob de JSON, e sem esta checagem o navegador "baixa" a
       * mensagem de erro com extensão .xlsx — o usuário abre um arquivo
       * corrompido e culpa o Excel. Mesmo defeito já corrigido no
       * AnotacaoModal. */
      if (blob.type.includes("json") || blob.type.startsWith("text/")) {
        const txt = await blob.text();
        throw new Error(txt.slice(0, 200));
      }
      const u = URL.createObjectURL(blob);
      if (formato === "pdf") {
        window.open(u, "_blank");
      } else {
        const a = document.createElement("a");
        a.href = u;
        a.download = `convenios.${formato}`;
        a.click();
      }
      setTimeout(() => URL.revokeObjectURL(u), 60000);
    } catch {
      alert("Não foi possível gerar o arquivo. Tente novamente.");
    } finally {
      setExportando(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <TituloTela>Convênios Estaduais</TituloTela>
          {/* A fonte é do ESTADO do ambiente e segue a cobertura REAL: onde já
              coletamos (MG=SIGCON, ES=GConv), nomeia a fonte; onde ainda não,
              diz com todas as letras — o vazio sem explicação era lido como
              "não temos convênio", que é outra frase. */}
          {ufAmbiente && (
            <p className="text-xs" style={{ color: "var(--bi-muted)" }}>
              {fonteConveniosEstaduais(ufAmbiente)
                ? `${fonteConveniosEstaduais(ufAmbiente)} · convênios do Estado com o município`
                : `${NOME_UF[ufAmbiente] || ufAmbiente} — a fonte estadual deste estado ainda não está integrada`}
            </p>
          )}
          {/* Frescor da COLETA (não confundir com a legenda da fonte acima):
              responde "isto está atualizado?" na abertura da tela, como o CAUC
              já faz. Com a coleta falhando, AVISA sem afirmar causa (o backend
              só sabe que falhou — pode ser credencial, portal fora ou layout) e
              sem datar: o carimbo, nesse caso, seria a hora do último ERRO.
              Some quando o filtro mostra só FNS (outra origem, outra cadência —
              o frescor do SIGCON não cobre aquelas linhas). */}
          {municipioId && data &&
            !(fontesSel.length > 0 && fontesSel.every((f) => f === "FNS")) &&
            ((data.coleta_falhas ?? 0) > 0 ? (
            <p className="text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>
              não foi possível concluir a última coleta no portal do Estado
              {data.items.length > 0 ? " — exibindo os últimos dados obtidos" : ""}
            </p>
          ) : data.coleta_em ? (
            <p
              className="text-[11px]"
              style={{ color: (horasDesde(data.coleta_em) ?? 0) > 26 ? "var(--bi-warn-ink)" : "var(--bi-muted)" }}
              title={(horasDesde(data.coleta_em) ?? 0) > 26 ? "Sem coleta nova há mais de um dia" : undefined}
            >
              Atualizado em {formatDataHora(data.coleta_em)}
            </p>
          ) : null)}
        </div>
        <div className="flex items-center gap-2">
          {refreshMsg && (
            <span className="text-xs text-base-content/70 italic">{refreshMsg}</span>
          )}
          {/* ⚠️ O TÍTULO DIZ QUE O ARQUIVO SEGUE OS FILTROS. Sem isso, quem foi
              mordido pelo defeito antigo continua desconfiando do documento —
              e desconfiança de relatório não se conserta só no backend. */}
          <div className="flex items-center gap-1" role="group" aria-label="Exportar">
            <Button onClick={() => exportar("pdf")} size="sm" variant="outline"
                    disabled={!!exportando}
                    title="Exportar em PDF, com os filtros aplicados">
              {exportando === "pdf" ? "…" : "📄 PDF"}
            </Button>
            <Button onClick={() => exportar("docx")} size="sm" variant="outline"
                    disabled={!!exportando}
                    title="Exportar em Word, com os filtros aplicados">
              {exportando === "docx" ? "…" : "📝 Word"}
            </Button>
            <Button onClick={() => exportar("xlsx")} size="sm" variant="outline"
                    disabled={!!exportando}
                    title="Exportar em Excel, com os filtros aplicados">
              {exportando === "xlsx" ? "…" : "📊 Excel"}
            </Button>
          </div>
          {/* O botão dispara o scraper do PORTAL MINEIRO — fora de MG ele
              não tem o que pesquisar, então nem aparece. ("" = UF ainda
              carregando: mantém visível para não piscar em MG.) */}
          {(ufAmbiente === "" || ufAmbiente === "MG") && (
            <Button
              onClick={handleRefreshSigcon}
              disabled={refreshing}
              size="sm"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }} className="hover:opacity-90"
              title="Força atualização via portal SIGCON-MG (Pesquisa Unificada)"
            >
              <SearchIcon className="size-4 mr-1" />
              {refreshing ? "Sincronizando..." : "Pesquisar SIGCON"}
            </Button>
          )}
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Fonte, nao "esfera": a coluna Fonte da tabela ja mostra esses
            mesmos valores, e agora da para filtrar por eles — um ou varios. */}
        <MultiSelect
          opcoes={fontes}
          rotulos={FONTES_ROTULOS}
          valor={fontesSel}
          onChange={setFontesSel}
          /* "Estaduais (sem FNS)" e não "Todas as fontes": o estado sem
             nenhuma caixa marcada EXCLUI o FNS, então "Marcar tudo" devolve
             MAIS linhas que o padrão — em 65 de 65 municípios os dois
             discordam, e no Trust eles se invertem (11 convênios estaduais
             contra 54 propostas do FNS, com os 11 sumindo). O rótulo antigo
             era uma afirmação falsa na tela. */
          placeholder="Estaduais (sem FNS)"
          rotuloTodos="Estaduais (sem FNS)"
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
            <span key={v} className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium" style={{ background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)" }}>
              {VIGENCIA_LABELS[v] ?? v}
              <button
                onClick={() => setVigenciasSel(vigenciasSel.filter((x) => x !== v))}
                className="opacity-60 hover:opacity-100"
                aria-label={`Remover filtro ${VIGENCIA_LABELS[v] ?? v}`}
              >
                ×
              </button>
            </span>
          ))}
          {!intervaloVazio(intervalo) && (
            <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium" style={{ background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)" }}>
              Fim da vigência {rotuloIntervalo(intervalo)}
              <button
                onClick={() => setIntervalo({})}
                className="opacity-60 hover:opacity-100"
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
        /* ⚠️ O VAZIO TINHA TRÊS CAUSAS E DIZIA UMA SÓ.
           "Nenhum dado encontrado." aparecia igual quando (a) não há credencial
           do SIGCON no Cofre para o município, (b) a credencial foi recusada, e
           (c) a coleta rodou e realmente não há convênio. O cliente lia todas
           como (c) — e as duas primeiras são pendências acionáveis, com um lugar
           exato para resolver. O backend agora classifica (services/coleta.py) e
           manda a frase pronta. */
        <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border px-6 text-center">
          <span className="text-muted-foreground">Nenhum dado encontrado.</span>
          {data?.credencial_aviso ? (
            <span className="max-w-md text-sm text-warning">{data.credencial_aviso}</span>
          ) : null}
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
              o olho continua descendo por uma coluna como descia na tabela.

              AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO do ano ->
              itens cinza dentro. E o mesmo desenho que o dono aprovou nas
              Emendas Estaduais e nas Propostas do TransfereGov; o respiro do
              branco vem do `p-3` do `Bloco`, para os itens nao encostarem na
              margem. Os `ItemLinha` de dentro nao mudaram em NADA — a lista
              so ganhou o cartao do ano em volta. */}
          <div className="space-y-3">
          {porAno.map(([ano, doAno]) => {
            const fechado = anosFechados.has(ano);
            // Soma a MESMA base que cada item exibe como valor, senao o total
            // do cabecalho discorda das linhas logo abaixo dele.
            const totalAno = doAno.reduce((s, c) => s + (c.valor_repasse ?? c.valor_total ?? 0), 0);
            return (
            <Bloco key={ano} className="p-3">
              <button type="button" onClick={() => alternarAno(ano)}
                      className="text-left" aria-expanded={!fechado}>
                <BlocoHead
                  icon={fechado ? ChevronRight : ChevronDown}
                  titulo={ano}
                  /* "nesta pagina" so quando ha mais de uma: a paginacao e do
                     servidor, entao a contagem e o total sao do recorte que
                     chegou, nao do ano inteiro. Numero sem escopo mente. */
                  sub={`${doAno.length} convênio(s)`}
                  right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                  className={fechado ? "mb-0" : undefined}
                />
              </button>
              {!fechado && (
              <Lista>
            {doAno.map((conv: Convenio) => {
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
                      {/* ÚLTIMA ALTERAÇÃO: a situação REAL do convênio estadual.
                          `situacao` sozinha é genérica ("Em vigor") e não diz em que
                          pé ele está — este selo mostra o estágio de fato. */}
                      {conv.alteracao_situacao && (
                        <Selo
                          tom="atencao"
                          title={[conv.alteracao_tipo, conv.alteracao_data, conv.alteracao_titulo]
                            .filter(Boolean).join(" · ") || "Última alteração"}
                        >
                          {conv.alteracao_situacao}
                        </Selo>
                      )}
                      {/* PRESTAÇÃO DE CONTAS: o estágio da ENTREGA, que é outra
                          pergunta que a alteração acima (o estágio do CONVÊNIO).
                          Vai prefixado porque com os dois selos lado a lado a
                          linha passa a ter duas situações, e sem o prefixo não dá
                          para saber qual é qual. O SEI e as datas ficam no título
                          — o detalhe inteiro está no modal. */}
                      {conv.prestacao_contas_status && (
                        <Selo
                          tom="neutro"
                          title={["Prestação de contas", conv.prestacao_contas_status,
                                  conv.prestacao_contas_data && `apresentada em ${conv.prestacao_contas_data}`,
                                  conv.prestacao_contas_sei && `SEI ${conv.prestacao_contas_sei}`]
                            .filter(Boolean).join(" · ")}
                        >
                          PC · {conv.prestacao_contas_status}
                        </Selo>
                      )}
                      {/* Emenda vinculada (espelho do selo "Convênio" da tela de Emendas). */}
                      {conv.emenda_nr && (
                        <Selo tom="ok" title={conv.emenda_objeto || `Emenda ${conv.emenda_nr}`}>
                          Emenda {conv.emenda_nr}
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
                        // `conv.valor_contrapartida ? ... : "—"` era veracidade
                        // de JS: `0` é falso, então NULO e ZERO REAL saíam
                        // iguais. Par obrigatório do `is not None` no
                        // serializador da lista — sem os dois, lista e modal
                        // discordam nas 180 linhas com contrapartida zero de
                        // verdade.
                        valor: conv.valor_contrapartida != null
                          ? formatCurrency(conv.valor_contrapartida) : "—",
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
              )}
            </Bloco>
            );
          })}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              Página {page} de {totalPages} ({data?.total ?? 0} registros)
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
                Próximo
                <ChevronRight className="size-4" />
              </Button>
            </div>
          </div>
        </>
      )}

      {/* Quem está no município e NÃO é a prefeitura (APAE, associação): fora das
          contas acima por construção — tabela e rota próprias. Some quando vazio. */}
      {municipioId && <OutrosConvenentes key={municipioId} municipioId={municipioId} />}

      <ConvenioDetailModal conv={selectedConv} onClose={() => setSelectedConv(null)} />
    </div>
  );
}
