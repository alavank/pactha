"use client";

// TRILHA DE AUDITORIA — a tela que responde "quem fez o quê, quando, de onde".
//
// O dono pediu duas leituras do MESMO evento, e a distinção é o coração desta
// tela: a linha da lista fala PORTUGUÊS ("Maria revelou a senha do SIGCON-MG") e
// o modal mostra os dois lados — a frase e o registro técnico (`cofre.reveal`, o
// JSON de `details`, o user-agent cru). Uma auditoria só técnica não serve ao
// controle interno da prefeitura; uma só didática não serve à perícia.
//
// ⚠️ A INTERPRETAÇÃO VIVE NO SERVIDOR, NÃO AQUI. A frase didática, o rótulo da
// ação, o módulo, a criticidade e a leitura do user-agent chegam prontos de
// `GET /api/auditoria` (ver `backend/routers/auditoria.py`). Esta tela NÃO tem
// dicionário próprio, e isso é decisão de auditoria, não de arquitetura: o mesmo
// endpoint monta o CSV exportado. Se a tela traduzisse por conta própria, a
// frase da tela e a frase do arquivo entregue ao controle interno divergiriam na
// primeira ação nova que alguém esquecesse de traduzir num dos dois lados — e
// ninguém perceberia, porque as duas continuariam parecendo certas.
//
// ⚠️ A TELA NÃO EDITA NADA. Não há botão de excluir, corrigir ou reclassificar,
// e isso é de propósito: a imutabilidade de verdade (append-only no banco, hash
// encadeado) é um incremento posterior, mas a superfície já nasce sem nenhuma
// porta de escrita — assim nada aqui precisa ser desfeito depois.

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ScrollText, Filter, Download, AlertTriangle, RotateCw, Globe, ListTree, FileClock,
  Eye, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight,
} from "lucide-react";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { TELA_LABELS } from "@/lib/telas";
import {
  Abas, Aviso, Bloco, BlocoHead, BOTAO_CTA, BOTAO_SEC, Campos, ESTILO_CTA,
  ESTILO_SEC, Grade, GradeCel, GradeLinha, ItemLinha, Lista, Modal, ModalCorpo,
  ModalHead, Secao, Selo, Vazio, type Campo,
} from "@/components/ui/superficies";

// ===========================================================================
// O CONTRATO COM O BACKEND — `backend/routers/auditoria.py`
//
// Os nomes aqui são os nomes DE LÁ, sem tradução no meio do caminho. Chave de
// filtro renomeada no front (`q` em vez de `busca`, `limit` em vez de
// `per_page`) não dá erro nenhum: o FastAPI simplesmente IGNORA o parâmetro que
// não conhece, a consulta volta sem o recorte e a tela mostra uma lista que
// parece filtrada e não está. Numa trilha de auditoria, filtro que mente é pior
// que filtro que falha.
// ===========================================================================

interface Origem {
  ip: string;
  navegador: string;
  sistema: string;
  dispositivo: string;
  resumo: string;
  user_agent: string;
}

interface Alteracao {
  campo: string;
  de: string;
  para: string;
}

interface EventoAuditoria {
  id: number;
  /** Já formatado pelo servidor, em horário de Brasília: "03/08/2026 14:22:07". */
  quando: string;
  quando_iso: string | null;
  usuario: { id: number | null; nome: string | null; email: string | null; rotulo: string };
  acao: string;
  acao_rotulo: string;
  modulo: string;
  modulo_rotulo: string;
  resultado: "sucesso" | "falha";
  severidade: "critico" | "alerta" | "info";
  o_que_aconteceu: string;
  alvo: { tipo: string | null; id: string | null; rotulo: string | null };
  municipio: { id: number | null; nome: string | null } | null;
  origem: Origem;
  alteracoes: Alteracao[];
  detalhes: Record<string, unknown> | null;
}

interface RespostaLista {
  items?: unknown;
  total?: number;
  page?: number;
  per_page?: number;
  pages?: number;
  periodo?: { de: string; ate: string };
}

interface ItemCatalogo {
  key: string;
  label: string;
}

interface AcaoCatalogo {
  key: string;
  rotulo: string;
  modulo: string;
  modulo_rotulo: string;
  severidade: string;
  resultado: string;
}

interface Catalogo {
  modulos: ItemCatalogo[];
  acoes: AcaoCatalogo[];
  resultados: ItemCatalogo[];
  severidades: Array<{ key: string; label: string; descricao: string }>;
  periodo_padrao_dias: number;
  export_max_linhas: number;
  per_page_max: number;
  fuso: string;
  retencao: { texto: string };
  aviso_imutabilidade: string;
}

/** Página da lista. O teto do servidor é 200 (`PER_PAGE_MAX`); 100 é o meio do
 *  caminho entre "rola pouco" e "não puxa meio megabyte de JSON por clique". */
const POR_PAGINA = 100;

// ===========================================================================
// Normalização defensiva
//
// A tela desenha SEMPRE, mesmo que um registro venha torto. Uma trilha que
// desaparece por causa de um campo nulo num registro de cinco anos atrás é uma
// trilha que some justamente no dia da conferência.
// ===========================================================================

function texto(v: unknown, padrao = ""): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return padrao;
}

function objeto(v: unknown): Record<string, unknown> | null {
  return v !== null && typeof v === "object" && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function normalizar(bruto: unknown): EventoAuditoria | null {
  const o = objeto(bruto);
  if (!o) return null;
  const id = typeof o.id === "number" ? o.id : Number(o.id);
  if (!Number.isFinite(id)) return null;

  const u = objeto(o.usuario) || {};
  const alvo = objeto(o.alvo) || {};
  const org = objeto(o.origem) || {};
  const mun = objeto(o.municipio);
  const acao = texto(o.acao, "(ação não registrada)");
  const sev = texto(o.severidade);

  return {
    id,
    quando: texto(o.quando, "—"),
    quando_iso: texto(o.quando_iso) || null,
    usuario: {
      id: typeof u.id === "number" ? u.id : null,
      nome: texto(u.nome) || null,
      email: texto(u.email) || null,
      // O servidor já garante rótulo para os três tipos de autor (pessoa, token
      // da Central, ninguém). O fallback aqui é só para não existir linha muda.
      rotulo: texto(u.rotulo) || "Não identificado",
    },
    acao,
    acao_rotulo: texto(o.acao_rotulo) || acao,
    modulo: texto(o.modulo, "outros"),
    modulo_rotulo: texto(o.modulo_rotulo, "Outros"),
    resultado: o.resultado === "falha" ? "falha" : "sucesso",
    severidade: sev === "critico" || sev === "alerta" ? sev : "info",
    o_que_aconteceu: texto(o.o_que_aconteceu) || `Ação registrada no sistema: ${acao}.`,
    alvo: {
      tipo: texto(alvo.tipo) || null,
      id: texto(alvo.id) || null,
      rotulo: texto(alvo.rotulo) || null,
    },
    municipio: mun ? { id: typeof mun.id === "number" ? mun.id : null, nome: texto(mun.nome) || null } : null,
    origem: {
      ip: texto(org.ip) || "Não registrado",
      navegador: texto(org.navegador) || "Não informado",
      sistema: texto(org.sistema) || "Não informado",
      dispositivo: texto(org.dispositivo) || "Não informado",
      resumo: texto(org.resumo) || "Origem não informada",
      user_agent: texto(org.user_agent),
    },
    alteracoes: Array.isArray(o.alteracoes)
      ? o.alteracoes
          .map((a) => objeto(a))
          .filter((a): a is Record<string, unknown> => a !== null)
          .map((a) => ({ campo: texto(a.campo, "campo"), de: texto(a.de, "—"), para: texto(a.para, "—") }))
      : [],
    detalhes: objeto(o.detalhes),
  };
}

// ===========================================================================
// Data e hora
//
// A tela NÃO reinterpreta fuso. O servidor entrega "03/08/2026 14:22:07" já
// convertido para horário de Brasília (o fuso do negócio, declarado em
// `/catalogo`), e a mesma string vai para o CSV. Se aqui a data fosse
// reconstruída de `quando_iso` e formatada com o fuso DO NAVEGADOR, o mesmo
// evento apareceria numa hora na tela e noutra no arquivo exportado — e a
// máquina de quem estivesse com o relógio em outro fuso mostraria uma trilha
// silenciosamente deslocada. Hora errada sem erro na tela é o pior defeito
// possível numa auditoria.
// ===========================================================================

const RE_QUANDO = /^(\d{2})\/(\d{2})\/(\d{4})[ T](\d{2}:\d{2}:\d{2})/;

function horaDe(quando: string): string {
  const m = RE_QUANDO.exec(quando);
  return m ? m[4] : "--:--:--";
}

function diaDe(quando: string): { chave: string; rotulo: string } {
  const m = RE_QUANDO.exec(quando);
  if (!m) return { chave: "sem-data", rotulo: "Eventos sem data registrada" };
  const [, dd, mm, aaaa] = m;
  /* Data montada por COMPONENTES locais e lida por componentes locais: é
     aritmética de calendário, não de instante, então nenhum fuso entra na
     conta. `new Date("2026-08-03")` faria o oposto — seria lido como UTC e a
     oeste de Greenwich cairia no dia anterior. */
  const d = new Date(Number(aaaa), Number(mm) - 1, Number(dd));
  const s = d.toLocaleDateString("pt-BR", {
    weekday: "long", day: "2-digit", month: "long", year: "numeric",
  });
  /* A maiúscula é feita AQUI e não com a classe `capitalize`: `text-transform:
     capitalize` sobe a inicial de TODA palavra, e "segunda-feira, 03 de agosto
     de 2026" viraria "Segunda-feira, 03 De Agosto De 2026". */
  return { chave: `${aaaa}-${mm}-${dd}`, rotulo: s.charAt(0).toUpperCase() + s.slice(1) };
}

/** `AAAA-MM-DD` local — o formato que o `<input type="date">` e o servidor falam. */
function iso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ===========================================================================
// Criticidade
//
// O servidor classifica em `critico` / `alerta` / `info`, e é a MESMA coluna
// que vai no CSV ("Criticidade"). A tela não reclassifica: só escolhe como
// mostrar. Ponto vermelho SÓ no `critico` (mexeu em segredo, permissão ou
// conta) — pelo mesmo motivo que a cor é escassa nesta identidade: se todo
// evento tiver ponto, o ponto não informa mais nada.
// ===========================================================================

const SEV_TOM: Record<string, "critico" | "atencao" | "neutro"> = {
  critico: "critico",
  alerta: "atencao",
  info: "neutro",
};

const SEV_PADRAO: Record<string, { label: string; descricao: string }> = {
  critico: { label: "Sensível", descricao: "Mexeu em segredo, permissão ou conta de usuário." },
  alerta: { label: "Atenção", descricao: "Falhou, foi recusada, ou tirou dado de dentro do sistema." },
  info: { label: "Rotina", descricao: "Uso normal do sistema." },
};

// ===========================================================================
// Rótulos dos campos do `details` bruto
//
// Só para a leitura amigável do JSON no modal. O antes/depois já vem traduzido
// do servidor (em `alteracoes`), então NÃO há dicionário duplicado aqui — este
// mapa cobre apenas as chaves de topo que o servidor não precisa nomear.
// ===========================================================================

const ROTULO_CAMPO: Record<string, string> = {
  name: "Nome",
  nome: "Nome",
  email: "E-mail",
  new_email: "E-mail do usuário",
  alvo_email: "E-mail do usuário alterado",
  alvo_nome: "Nome do usuário alterado",
  role: "Perfil de acesso",
  active: "Usuário ativo",
  telas: "Telas com acesso",
  municipios: "Municípios com acesso",
  municipios_nomes: "Municípios (nomes)",
  must_change_password: "Precisa trocar a senha no próximo acesso",
  sistema: "Sistema",
  senha_changed: "A senha foi trocada",
  automation_key: "Chave de automação",
  municipio_id: "Município (id)",
  token: "Token da Central",
  principal: "Integração",
  tech: "Técnico",
  scopes: "Permissões do token",
  via: "Origem do acesso",
  tela: "Tela",
  formato: "Formato",
  linhas: "Linhas exportadas",
  truncado: "Exportação cortada no teto",
  teto: "Teto de linhas da exportação",
  filtros: "Filtros aplicados",
  ibge: "Código IBGE",
};

function rotuloCampo(k: string): string {
  return ROTULO_CAMPO[k] || k.replace(/_/g, " ");
}

function valorLegivel(chave: string, v: unknown): string {
  if (v == null || v === "") return "—";
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (Array.isArray(v)) {
    if (!v.length) return "(nenhum)";
    // Chave de tela é chave do BACKEND; aqui vira o rótulo que o gestor
    // reconhece do formulário de permissões.
    if (chave === "telas") return v.map((x) => TELA_LABELS[String(x)] || String(x)).join(", ");
    return v.map((x) => (x !== null && typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ");
  }
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ===========================================================================
// Filtros
// ===========================================================================

type PeriodoKey = "hoje" | "7d" | "30d" | "90d" | "12m" | "tudo" | "custom";

const PERIODOS: Array<{ valor: PeriodoKey; label: string }> = [
  { valor: "hoje", label: "Hoje" },
  { valor: "7d", label: "7 dias" },
  { valor: "30d", label: "30 dias" },
  { valor: "90d", label: "90 dias" },
  { valor: "12m", label: "12 meses" },
  { valor: "tudo", label: "Desde o início" },
  { valor: "custom", label: "Personalizado" },
];

interface Filtros {
  periodo: PeriodoKey;
  de: string;
  ate: string;
  usuario: string;
  modulo: string;
  acao: string;
  resultado: string;
  busca: string;
}

/* "Desde o início" precisa de uma data de VERDADE, e não de campo vazio.
   O servidor tem janela padrão de 30 dias: omitir `de` não significa "tudo",
   significa "os últimos 30 dias". Um botão escrito "Desde o início" que
   devolvesse um mês seria a tela mentindo sobre o próprio recorte — e é
   exatamente o tipo de engano que faz alguém concluir que "não houve nada".

   O piso é um ano que PRECEDE qualquer registro possível, e não a data em que a
   trilha começou: cravar o começo aqui significaria que o dia em que alguém
   restaurasse um histórico mais antigo, ou migrasse o banco, esses registros
   sumiriam do "Desde o início" sem nenhum aviso. */
const INICIO_DA_TRILHA = "2000-01-01";

function datasDoPeriodo(p: PeriodoKey, atual: { de: string; ate: string }): { de: string; ate: string } {
  const hoje = new Date();
  const menos = (dias: number) => {
    const d = new Date();
    d.setDate(d.getDate() - dias);
    return iso(d);
  };
  switch (p) {
    case "hoje": return { de: iso(hoje), ate: iso(hoje) };
    case "7d": return { de: menos(6), ate: iso(hoje) };
    case "30d": return { de: menos(29), ate: iso(hoje) };
    case "90d": return { de: menos(89), ate: iso(hoje) };
    case "12m": return { de: menos(364), ate: iso(hoje) };
    case "tudo": return { de: INICIO_DA_TRILHA, ate: iso(hoje) };
    default: return atual;
  }
}

const FILTROS_INICIAIS: Filtros = {
  periodo: "30d",
  ...datasDoPeriodo("30d", { de: "", ate: "" }),
  usuario: "",
  modulo: "",
  acao: "",
  resultado: "",
  busca: "",
};

/** Os parâmetros da chamada. UMA função para a lista e para a exportação: se a
 *  exportação recortasse por critério diferente do que está na tela, o arquivo
 *  entregue ao controle interno não seria o que o gestor viu — e ninguém
 *  perceberia.
 *
 *  Sem `municipio_id` de propósito: evento de login, troca de senha e gestão de
 *  usuário é da INSTÂNCIA e não tem município, então filtrar por ele apagaria
 *  justamente as tentativas de invasão. O recorte por município de quem lê é
 *  feito no servidor (`_cond_escopo`), que é onde ele vale como segurança. */
function parametros(f: Filtros): Record<string, string> {
  const p: Record<string, string> = {};
  if (f.de) p.de = f.de;
  if (f.ate) p.ate = f.ate;
  if (f.usuario.trim()) p.usuario = f.usuario.trim();
  if (f.busca.trim()) p.busca = f.busca.trim();
  if (f.resultado) p.resultado = f.resultado;
  if (f.modulo) p.modulo = f.modulo;
  // `acao` é chave OU prefixo ("cofre." traz a família inteira). Vai junto com
  // o módulo, e não no lugar dele: o servidor faz E, que é o recorte que a
  // barra de filtros mostra.
  if (f.acao) p.acao = f.acao;
  return p;
}

const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR: React.CSSProperties = { color: "var(--bi-muted)" };
const SELECT_CLS = "h-9 w-full rounded-md border px-2 text-[13px]";
const SELECT_ESTILO: React.CSSProperties = {
  borderColor: "var(--bi-line)",
  background: "var(--bi-surface)",
  color: "var(--bi-text)",
};

/** O nome do arquivo baixado, a partir do `Content-Disposition`.
 *
 *  Isolado numa função com try PRÓPRIO porque um nome malformado faria o
 *  `decodeURIComponent` estourar DEPOIS de o servidor já ter entregue o CSV: o
 *  erro cairia no catch do download e a tela diria "não foi possível exportar,
 *  nada foi baixado" — mentindo sobre uma exportação que aconteceu e foi
 *  registrada na própria trilha. */
function nomeDoArquivo(contentDisposition: string): string {
  const reserva = `auditoria-pactha-${iso(new Date())}.csv`;
  try {
    const m = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(contentDisposition);
    if (!m) return reserva;
    const cru = m[1].trim();
    // Só decodifica quando há de fato percent-encoding; `decodeURIComponent`
    // estoura em "%" solto, que é caractere legítimo num nome de arquivo.
    const nome = /%[0-9A-Fa-f]{2}/.test(cru) ? decodeURIComponent(cru) : cru;
    // Nunca aceitar caminho vindo do cabeçalho: `../` num download é gravar
    // fora da pasta escolhida em navegadores antigos.
    return nome.replace(/[\\/]/g, "_") || reserva;
  } catch {
    return reserva;
  }
}

function mensagemErro(e: unknown): string {
  const err = e as { response?: { status?: number; data?: unknown }; message?: string };
  const st = err?.response?.status;
  if (st === 403) {
    return 'Você não tem permissão para ler a trilha de auditoria. Peça o acesso à tela "Auditoria" a um administrador.';
  }
  if (st === 401) {
    return "Sua sessão expirou. Entre novamente para ler a trilha.";
  }
  const dados = err?.response?.data;
  /* O corpo pode NÃO ser JSON: o proxy do Next responde texto puro quando
     estoura o tempo, e imprimir uma página HTML inteira dentro do aviso
     esconderia a mensagem. Corta em 200. */
  const detalhe =
    typeof dados === "string" ? dados : texto((dados as { detail?: unknown } | undefined)?.detail);
  return `Não foi possível carregar a trilha de auditoria${st ? ` (HTTP ${st})` : ""}. ${
    detalhe.slice(0, 200) || err?.message || ""
  }`.trim();
}

// ===========================================================================

export default function AuditoriaPage() {
  const [filtros, setFiltros] = useState<Filtros>(FILTROS_INICIAIS);
  const [pagina, setPagina] = useState(1);
  const [recarga, setRecarga] = useState(0);
  const [eventos, setEventos] = useState<EventoAuditoria[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [paginas, setPaginas] = useState(1);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<EventoAuditoria | null>(null);
  const [exportando, setExportando] = useState(false);
  const [avisoExport, setAvisoExport] = useState<{ tom: "critico" | "atencao"; texto: string } | null>(null);
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);

  /* O CATÁLOGO VEM DO SERVIDOR, não de uma cópia em JavaScript. É o mesmo
     dicionário que monta a frase, o módulo e a criticidade de cada linha e do
     CSV: se a lista de módulos fosse escrita aqui, um módulo novo no servidor
     ficaria invisível no filtro — e o gestor concluiria que aquele tipo de
     evento não existe. Falhar aqui NÃO derruba a tela: a lista continua, só os
     dois seletores de vocabulário ficam sem opções. */
  useEffect(() => {
    let vivo = true;
    api
      .get<Catalogo>("/auditoria/catalogo")
      .then((res) => { if (vivo) setCatalogo(res.data); })
      .catch(() => { if (vivo) setCatalogo(null); });
    return () => { vivo = false; };
  }, []);

  /* A carga vive dentro de um `setTimeout` por dois motivos que se somam: ele
     dá o repique (debounce) dos campos de texto, e mantém o `setState` fora do
     corpo do efeito. O `vivo` descarta resposta de uma consulta que já não é a
     da tela — sem ele, uma busca lenta chegando depois de uma rápida repõe a
     lista errada, e numa auditoria isso é mostrar evento que não casa com o
     filtro exibido. */
  useEffect(() => {
    let vivo = true;
    const t = setTimeout(() => {
      setCarregando(true);
      api
        .get<RespostaLista>("/auditoria", {
          params: { ...parametros(filtros), page: pagina, per_page: POR_PAGINA },
        })
        .then((res) => {
          if (!vivo) return;
          const crus = Array.isArray(res.data?.items) ? res.data.items : [];
          const novos = crus
            .map(normalizar)
            .filter((x): x is EventoAuditoria => x !== null);
          /* PAGINAÇÃO, e não acúmulo: cada página SUBSTITUI a anterior. Antes a
             lista crescia sem fim, e numa trilha com dezenas de milhares de
             eventos isso vira uma rolagem que nunca acaba — sem como voltar a
             um ponto, sem como dizer "estava na página 4".
             Efeito colateral que sumiu junto: acumulando, um evento gravado
             ENTRE duas buscas empurrava a janela e repetia linhas na virada. */
          setEventos(novos);
          setTotal(typeof res.data?.total === "number" ? res.data.total : null);
          setPaginas(typeof res.data?.pages === "number" ? res.data.pages : 1);
          setErro(null);
        })
        .catch((e) => {
          if (!vivo) return;
          /* NÃO limpa a lista e NÃO finge lista vazia: o estado de erro é o que
             a tela mostra, com a mensagem inteira. Auditoria que falha
             parecendo auditoria sem eventos é o defeito que este incremento
             existe para corrigir. */
          setErro(mensagemErro(e));
          setPaginas(1);
        })
        .finally(() => {
          if (vivo) setCarregando(false);
        });
    }, 350);
    return () => {
      vivo = false;
      clearTimeout(t);
    };
  }, [filtros, pagina, recarga]);

  /** Toda mudança de filtro volta para a primeira página. */
  const mudar = useCallback((patch: Partial<Filtros>) => {
    setFiltros((f) => ({ ...f, ...patch }));
    setPagina(1);
  }, []);

  const mudarPeriodo = (p: PeriodoKey) => {
    mudar({ periodo: p, ...datasDoPeriodo(p, { de: filtros.de, ate: filtros.ate }) });
  };

  /** Ações oferecidas no filtro — só as do módulo escolhido, quando há um. */
  const acoesDoFiltro = useMemo(() => {
    const itens = (catalogo?.acoes || []).filter((a) => !filtros.modulo || a.modulo === filtros.modulo);
    return [...itens].sort((a, b) => a.rotulo.localeCompare(b.rotulo, "pt-BR"));
  }, [catalogo, filtros.modulo]);

  /* Agrupamento por dia SEM reordenar: a API entrega do mais recente para o
     mais antigo, e "carregar mais" acrescenta ao fim. Reordenar aqui faria a
     tela e o arquivo exportado divergirem na ordem. */
  const dias = useMemo(() => {
    const mapa = new Map<string, { chave: string; rotulo: string; itens: EventoAuditoria[] }>();
    for (const e of eventos) {
      const { chave, rotulo } = diaDe(e.quando);
      const g = mapa.get(chave) || { chave, rotulo, itens: [] };
      g.itens.push(e);
      mapa.set(chave, g);
    }
    return [...mapa.values()];
  }, [eventos]);

  const exportar = async () => {
    setExportando(true);
    setAvisoExport(null);
    try {
      /* Vai pelo MESMO cliente da lista (`api`), e não por `fetch` cru: é ele
         que carrega o Bearer, o cookie, a baseURL e a renovação automática de
         sessão em 401. Um `fetch` paralelo duplicaria essa lógica e sairia de
         sincronia no dia em que a autenticação mudasse — e a exportação
         falharia só para quem entrou por SSO, que é justamente o caso raro.
         `responseType: "blob"` evita a conversão para texto no caminho. */
      const res = await api.get("/auditoria/exportar", {
        params: parametros(filtros),
        responseType: "blob",
      });

      /* O nome do arquivo é do SERVIDOR (traz o período do recorte). O
         cabeçalho só é legível em mesma origem — que é como a plataforma roda
         em produção (API e front no mesmo container). Em desenvolvimento
         cross-origin o navegador esconde o cabeçalho, daí o nome de reserva. */
      const nome = nomeDoArquivo(texto(res.headers?.["content-disposition"]));

      const url = URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = nome;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);

      /* O servidor corta a exportação num teto e escreve o aviso DENTRO do
         arquivo. Repetimos aqui quando o cabeçalho é legível, porque quem
         clica não abre o CSV na hora — e um arquivo cortado em silêncio vira
         prova de que "não houve mais nada". */
      if (texto(res.headers?.["x-auditoria-truncado"]) === "1") {
        setAvisoExport({
          tom: "atencao",
          texto:
            `O arquivo saiu INCOMPLETO: o filtro selecionado tem mais eventos que o teto de ` +
            `${(catalogo?.export_max_linhas ?? 25000).toLocaleString("pt-BR")} linhas por exportação. ` +
            `Foram gravados os mais recentes do período, e o próprio arquivo traz esse aviso na ` +
            `última linha. Reduza o período ou aplique filtros para obter o restante.`,
        });
      }
    } catch (e) {
      const st = (e as { response?: { status?: number } })?.response?.status;
      setAvisoExport({
        tom: "critico",
        texto:
          st === 403
            ? "Você não tem permissão para exportar a trilha. Nada foi baixado."
            : `Não foi possível exportar${st ? ` (HTTP ${st})` : ""}. Nada foi baixado — o arquivo NÃO saiu parcial.`,
      });
    } finally {
      setExportando(false);
    }
  };

  const limpar = () => {
    setFiltros(FILTROS_INICIAIS);
    setPagina(1);
  };

  const filtrando =
    !!filtros.usuario || !!filtros.acao || !!filtros.modulo || !!filtros.resultado || !!filtros.busca;

  return (
    <div className="space-y-4">
      {/* Cabeçalho */}
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
              <ScrollText className="size-6" style={{ color: "var(--bi-muted)" }} />
              Auditoria
            </h1>
            <p className="mt-1 max-w-3xl text-sm" style={{ color: "var(--bi-muted)" }}>
              Tudo o que foi feito na plataforma, em ordem de acontecimento: data, hora, usuário,
              endereço de rede (IP), dispositivo e navegador. Clique em qualquer linha para ver o
              detalhe completo, com a leitura em português e o registro técnico lado a lado.
              Horários em Brasília.
            </p>
          </div>
          <button
            type="button"
            onClick={exportar}
            disabled={exportando}
            className={BOTAO_CTA}
            style={ESTILO_CTA}
            title="Baixa em CSV exatamente os eventos que os filtros abaixo selecionam"
          >
            <Download className="size-4" />
            {exportando ? "Gerando..." : "Exportar (CSV)"}
          </button>
        </div>
      </div>

      {avisoExport && (
        <Bloco className="p-3">
          <Aviso
            tom={avisoExport.tom}
            titulo={avisoExport.tom === "critico" ? "A exportação falhou" : "A exportação saiu incompleta"}
            icon={AlertTriangle}
            className=""
          >
            <p className="text-[11px] leading-snug" style={{ color: "var(--bi-text)" }}>
              {avisoExport.texto}
            </p>
          </Aviso>
        </Bloco>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Filtros                                                             */}
      {/* ------------------------------------------------------------------ */}
      <Bloco className="p-3">
        <BlocoHead
          icon={Filter}
          titulo="Filtros"
          sub="Período, pessoa, módulo, ação e resultado. A exportação usa exatamente estes filtros."
        />

        <div>
          <span className={ROTULO} style={ROTULO_COR}>Período</span>
          <Abas valor={filtros.periodo} onChange={mudarPeriodo} opcoes={PERIODOS} />
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-de">De</label>
            <Input
              id="aud-de"
              type="date"
              value={filtros.de}
              onChange={(ev) => mudar({ periodo: "custom", de: ev.target.value })}
            />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-ate">Até (inclusive)</label>
            <Input
              id="aud-ate"
              type="date"
              value={filtros.ate}
              onChange={(ev) => mudar({ periodo: "custom", ate: ev.target.value })}
            />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-user">Usuário</label>
            <Input
              id="aud-user"
              value={filtros.usuario}
              onChange={(ev) => mudar({ usuario: ev.target.value })}
              placeholder="nome ou e-mail (parte serve)"
            />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-res">Resultado</label>
            <select
              id="aud-res"
              className={SELECT_CLS}
              style={SELECT_ESTILO}
              value={filtros.resultado}
              onChange={(ev) => mudar({ resultado: ev.target.value })}
            >
              <option value="">Tudo</option>
              {(catalogo?.resultados || [
                { key: "sucesso", label: "Concluída" },
                { key: "falha", label: "Falha ou recusa" },
              ]).map((r) => (
                <option key={r.key} value={r.key}>{r.label}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-mod">Módulo</label>
            <select
              id="aud-mod"
              className={SELECT_CLS}
              style={SELECT_ESTILO}
              value={filtros.modulo}
              /* Trocar de módulo LIMPA a ação: manter uma ação de outro módulo
                 selecionada devolveria zero eventos e pareceria "não tem nada
                 aqui" em vez de "o filtro está incoerente". */
              onChange={(ev) => mudar({ modulo: ev.target.value, acao: "" })}
              disabled={!catalogo}
            >
              <option value="">Todos os módulos</option>
              {(catalogo?.modulos || []).map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </div>
          <div className="lg:col-span-2">
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-acao">Ação</label>
            <select
              id="aud-acao"
              className={SELECT_CLS}
              style={SELECT_ESTILO}
              value={filtros.acao}
              onChange={(ev) => mudar({ acao: ev.target.value })}
              disabled={!catalogo}
            >
              <option value="">Todas as ações{filtros.modulo ? " do módulo" : ""}</option>
              {acoesDoFiltro.map((a) => (
                <option key={a.key} value={a.key}>{a.rotulo}</option>
              ))}
            </select>
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR} htmlFor="aud-q">Busca livre</label>
            <Input
              id="aud-q"
              value={filtros.busca}
              onChange={(ev) => mudar({ busca: ev.target.value })}
              placeholder="IP, sistema, nº do registro..."
            />
          </div>
        </div>

        {!catalogo && (
          /* Seletor desabilitado sem explicação parece tela quebrada. E, pior:
             o gestor concluiria que "não dá para filtrar por módulo" quando o
             que houve foi uma consulta que não voltou. */
          <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
            A lista de módulos e ações não pôde ser carregada do servidor. Os demais filtros e a
            exportação continuam funcionando normalmente.
          </p>
        )}

        <div
          className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t pt-3"
          style={{ borderColor: "var(--bi-line)" }}
        >
          <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {carregando
              ? "Carregando..."
              : erro
                ? "A consulta falhou — veja o aviso abaixo."
                : total != null
                  ? `${total.toLocaleString("pt-BR")} evento(s) no filtro · ${eventos.length.toLocaleString("pt-BR")} carregado(s)`
                  : `${eventos.length.toLocaleString("pt-BR")} evento(s) carregado(s)`}
          </span>
          <button
            type="button"
            onClick={limpar}
            className={BOTAO_SEC}
            style={ESTILO_SEC}
            disabled={!filtrando && filtros.periodo === FILTROS_INICIAIS.periodo}
          >
            Limpar filtros
          </button>
        </div>
      </Bloco>

      {/* ------------------------------------------------------------------ */}
      {/* Erro — VISÍVEL, e nunca confundido com "não há eventos"             */}
      {/* ------------------------------------------------------------------ */}
      {erro && (
        <Bloco className="p-3">
          <Aviso tom="critico" titulo="A trilha de auditoria não pôde ser lida" icon={AlertTriangle} className="">
            <p className="text-[12px] leading-snug" style={{ color: "var(--bi-text)" }}>{erro}</p>
            <p className="mt-1.5 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
              <strong>Isto NÃO quer dizer que não houve movimento no período.</strong> Quer dizer
              que a consulta falhou. Tente de novo e, se persistir, avise o suporte antes de
              concluir qualquer coisa sobre o período.
            </p>
            <button
              type="button"
              onClick={() => setRecarga((n) => n + 1)}
              className={`${BOTAO_SEC} mt-2`}
              style={ESTILO_SEC}
            >
              <RotateCw className="size-4" />
              Tentar de novo
            </button>
          </Aviso>
        </Bloco>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* A lista, um cartão branco POR DIA                                   */}
      {/* ------------------------------------------------------------------ */}
      {carregando && eventos.length === 0 && !erro ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-2xl" style={{ background: "var(--bi-surface-2)" }} />
          ))}
        </div>
      ) : !erro && eventos.length === 0 ? (
        <Bloco className="p-3">
          <BlocoHead icon={FileClock} titulo="Nenhum evento encontrado" />
          <Vazio>
            Não há evento registrado com estes filtros.
            {filtrando || filtros.periodo !== "tudo"
              ? " Amplie o período ou limpe os filtros antes de concluir que nada aconteceu."
              : ""}
            <br />
            <span className="mt-1 inline-block">
              Lembre: navegação é registrada com deduplicação (só na troca de tela ou a cada 5
              minutos) e consultas individuais não são registradas — de propósito.
            </span>
          </Vazio>
        </Bloco>
      ) : (
        <div className="space-y-3">
          {dias.map((dia) => (
            <Bloco key={dia.chave} className="p-3">
              <BlocoHead
                icon={ListTree}
                titulo={dia.rotulo}
                right={
                  <span className="bi-num text-[13px]" title="Eventos carregados neste dia">
                    {dia.itens.length}
                  </span>
                }
              />
              <Lista>
                {dia.itens.map((e) => (
                  <ItemLinha
                    key={e.id}
                    onClick={() => setAberto(e)}
                    titulo={
                      <span className="flex items-baseline gap-2">
                        <span className="bi-id shrink-0 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                          {horaDe(e.quando)}
                        </span>
                        {e.severidade === "critico" && (
                          <>
                            {/* O ponto é o sinal DISCRETO de ação sensível. Cor
                                sozinha não basta (quem não distingue vermelho
                                não veria nada), então vem com `title` e com
                                texto para leitor de tela. */}
                            {/* `mb-[2px]` e não `mt-`: numa linha alinhada por
                                baseline, um elemento vazio tem a base na borda
                                INFERIOR da margem — a margem de baixo é o que
                                ergue o ponto do chão da letra até a altura do
                                corpo do texto. */}
                            <span
                              aria-hidden="true"
                              title="Ação sensível: mexeu em segredo, permissão ou conta de usuário"
                              className="mb-[2px] size-1.5 shrink-0 rounded-full"
                              style={{ background: "var(--bi-crit)" }}
                            />
                            <span className="sr-only">Ação sensível. </span>
                          </>
                        )}
                        <span className="min-w-0 flex-1">{e.o_que_aconteceu}</span>
                      </span>
                    }
                    valor={
                      /* O olho convida ao clique — a linha inteira abre o
                         detalhe, e sem esta pista ninguém descobre.
                         Aqui havia um selo "OK" em toda linha: dizia o óbvio
                         (quase tudo dá certo), ocupava a coluna que o olho
                         procura para agir, e não sugeria que houvesse mais o
                         que ver. A FALHA continua aparecendo, agora em selo
                         vermelho ao lado do olho — porque falha é exceção, e é
                         disso que a cor tem de dar conta. */
                      <span className="flex items-center gap-1.5">
                        {e.resultado === "falha" && <Selo tom="critico">Falhou</Selo>}
                        <Eye
                          className="size-4 shrink-0"
                          style={{ color: "var(--bi-faint)" }}
                          aria-hidden="true"
                        />
                      </span>
                    }
                    meta={
                      <>
                        <span style={{ color: "var(--bi-muted)" }}>{e.usuario.rotulo}</span>
                        <Selo>{e.modulo_rotulo}</Selo>
                        <span className="bi-id">{e.origem.ip}</span>
                        <span>{e.origem.dispositivo}</span>
                      </>
                    }
                  />
                ))}
              </Lista>
            </Bloco>
          ))}

          {paginas > 1 && (
            <Bloco className="p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                  Página <span className="bi-num">{pagina}</span> de{" "}
                  <span className="bi-num">{paginas}</span>
                  {total != null && (
                    <> · <span className="bi-num">{total.toLocaleString("pt-BR")}</span> evento(s)</>
                  )}
                </span>
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setPagina(1)}
                    disabled={pagina <= 1 || carregando}
                    className={BOTAO_SEC}
                    style={ESTILO_SEC}
                    title="Primeira página"
                  >
                    <ChevronsLeft className="size-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setPagina((p) => Math.max(1, p - 1))}
                    disabled={pagina <= 1 || carregando}
                    className={BOTAO_SEC}
                    style={ESTILO_SEC}
                  >
                    <ChevronLeft className="size-4" /> Anterior
                  </button>
                  <button
                    type="button"
                    onClick={() => setPagina((p) => Math.min(paginas, p + 1))}
                    disabled={pagina >= paginas || carregando}
                    className={BOTAO_SEC}
                    style={ESTILO_SEC}
                  >
                    Próxima <ChevronRight className="size-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => setPagina(paginas)}
                    disabled={pagina >= paginas || carregando}
                    className={BOTAO_SEC}
                    style={ESTILO_SEC}
                    title="Última página"
                  >
                    <ChevronsRight className="size-4" />
                  </button>
                </div>
              </div>
            </Bloco>
          )}
        </div>
      )}

      {/* Nota de conformidade. O texto de retenção vem do SERVIDOR (`/catalogo`)
          para a política não viver escrita em dois lugares e divergir. O de
          reserva diz o que É verdade hoje — a trilha não tem nenhuma porta de
          escrita nesta tela — sem prometer a imutabilidade de banco, que é de
          outro incremento. Auditoria que promete mais do que entrega é o pior
          tipo de auditoria. */}
      <p className="px-1 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
        {/* `texto()` e não interpolação direta: um campo ausente na resposta
            imprimiria a palavra "undefined" no meio de uma nota de
            conformidade. */}
        {[
          texto(catalogo?.aviso_imutabilidade) ||
            "A trilha é somente leitura: não há, nesta tela, forma de alterar, editar ou excluir um registro.",
          texto(catalogo?.retencao?.texto) ||
            "Guarda: 5 anos para eventos de segurança, acesso e permissão; 12 meses para navegação. A remoção de registros vencidos só acontece por ato deliberado e é ela própria registrada aqui.",
          "Os dados ficam no servidor da plataforma e não são enviados a terceiros.",
        ].join(" ")}
      </p>

      <ModalEvento evento={aberto} onFechar={() => setAberto(null)} catalogo={catalogo} />
    </div>
  );
}

// ===========================================================================
// O MODAL — os dois lados do mesmo evento.
// ===========================================================================

/* A classe LITERAL das colunas do antes/depois, numa constante para o cabeçalho
   e as linhas nunca divergirem. Montar `grid-cols-[${x}]` produziria uma grade
   sem coluna nenhuma: o Tailwind só gera a classe que aparece escrita. */
const COLS_DIFF = "grid-cols-[10rem_minmax(0,1fr)_minmax(0,1fr)]";

function ModalEvento({
  evento,
  onFechar,
  catalogo,
}: {
  evento: EventoAuditoria | null;
  onFechar: () => void;
  catalogo: Catalogo | null;
}) {
  if (!evento) return null;
  const e = evento;
  const sev =
    catalogo?.severidades?.find((s) => s.key === e.severidade) || SEV_PADRAO[e.severidade];
  const detalhes = e.detalhes && Object.keys(e.detalhes).length ? e.detalhes : null;

  /* Só as chaves SIMPLES viram campo legível. `antes`, `depois` e `mudou` são
     objetos e já aparecem traduzidos na grade "O que mudou" logo acima — aqui
     virariam um JSON.stringify de duas linhas dentro de uma célula, ilegível e
     redundante. Eles continuam inteiros no bloco de JSON abaixo, que é a prova. */
  const detalhesSimples = detalhes
    ? Object.entries(detalhes).filter(([, v]) => objeto(v) === null)
    : [];

  const quem: Campo[] = [
    { rotulo: "Data e hora (Brasília)", valor: e.quando, span: 2, quebra: true },
    {
      rotulo: "Usuário",
      valor: e.usuario.rotulo,
      span: 2,
      quebra: true,
      /* Registro sem autor identificado é achado de auditoria, não detalhe de
         layout: fica marcado como atenção para quem lê saber que a pergunta
         "quem foi?" não tem resposta NESTE registro. */
      tom: e.usuario.nome || e.usuario.email ? "normal" : "atencao",
    },
    { rotulo: "E-mail", valor: e.usuario.email || "—", span: 2, quebra: true },
    { rotulo: "Módulo", valor: e.modulo_rotulo, span: 2 },
    {
      rotulo: "Resultado",
      valor: e.resultado === "falha" ? "Não concluiu (falha)" : "Concluiu",
      tom: e.resultado === "falha" ? "critico" : "normal",
    },
    {
      rotulo: "Criticidade",
      valor: sev?.label || e.severidade,
      title: sev?.descricao,
      tom: SEV_TOM[e.severidade] === "neutro" ? "normal" : SEV_TOM[e.severidade],
    },
    { rotulo: "Município", valor: e.municipio?.nome || (e.municipio?.id ? `id ${e.municipio.id}` : "—") },
    { rotulo: "Sobre o quê", valor: e.alvo.rotulo || "—", span: 2, quebra: true },
  ];

  const origem: Campo[] = [
    {
      rotulo: "Endereço de rede (IP)",
      valor: e.origem.ip,
      mono: true,
      tom: e.origem.ip === "Não registrado" ? "atencao" : "normal",
    },
    { rotulo: "Navegador", valor: e.origem.navegador },
    { rotulo: "Sistema", valor: e.origem.sistema },
    { rotulo: "Dispositivo", valor: e.origem.dispositivo },
  ];

  const tecnico: Campo[] = [
    { rotulo: "Ação (banco)", valor: e.acao, mono: true, span: 2 },
    { rotulo: "Nº do registro", valor: String(e.id), mono: true },
    { rotulo: "Tipo do alvo", valor: e.alvo.tipo || "—", mono: true },
    { rotulo: "Identificador do alvo", valor: e.alvo.id || "—", mono: true, span: 2 },
    { rotulo: "Usuário (id)", valor: e.usuario.id != null ? String(e.usuario.id) : "—", mono: true },
    { rotulo: "Carimbo com fuso", valor: e.quando_iso || "—", mono: true, span: 2, quebra: true },
  ];

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-4xl">
      <ModalHead
        titulo={e.acao_rotulo}
        sub={e.quando}
        onFechar={onFechar}
        right={
          <Selo tom={e.resultado === "falha" ? "critico" : "neutro"}>
            {e.resultado === "falha" ? "Falhou" : "OK"}
          </Selo>
        }
      />
      <ModalCorpo className="space-y-3">
        {e.severidade === "critico" && (
          <Aviso tom="critico" titulo="Ação sensível" icon={AlertTriangle} className="">
            <p className="text-[11px] leading-snug" style={{ color: "var(--bi-text)" }}>
              {sev?.descricao || SEV_PADRAO.critico.descricao} Merece conferência.
            </p>
          </Aviso>
        )}

        {/* 1. A LEITURA EM PORTUGUÊS — vem primeiro de propósito.
            A `Secao` desenha os `campos` ANTES do `children`, então usar a prop
            jogaria a frase para debaixo da grade de rótulos. Aqui os dois vêm
            como filhos, na ordem que interessa: o gestor lê a frase e só depois
            confere os campos. */}
        <Secao icon={ScrollText} titulo="O que aconteceu">
          <p className="text-[13px] leading-snug" style={{ color: "var(--bi-text)" }}>
            {e.o_que_aconteceu}
          </p>
          <Campos campos={quem} cols={4} />
        </Secao>

        {/* 2. DE ONDE */}
        <Secao icon={Globe} titulo="De onde e por qual aparelho" cols={4} campos={origem}>
          <div className="mt-2">
            <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
              Identificação do navegador, como o aparelho a enviou (user-agent)
            </div>
            <p
              className="bi-id mt-1 rounded-lg p-2 text-[10px] leading-relaxed break-words"
              style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
            >
              {e.origem.user_agent || "não registrado"}
            </p>
          </div>
        </Secao>

        {/* 3. O QUE MUDOU — só quando o servidor apurou antes/depois. */}
        {e.alteracoes.length > 0 && (
          <Secao icon={ListTree} titulo="O que mudou" sub="Valor antes e depois da alteração">
            <div className="mt-2">
              <Grade
                cols={COLS_DIFF}
                cabecalho={[{ label: "Campo" }, { label: "Antes" }, { label: "Depois" }]}
                rolagem
                minLargura="34rem"
              >
                {/* O servidor já devolve SÓ o que mudou de fato (compara os
                    valores já normalizados, então reordenar uma lista de telas
                    não vira "alteração"). Por isso não há aqui marca de linha
                    alterada: TODA linha desta grade é uma alteração. */}
                {e.alteracoes.map((a, i) => (
                  <GradeLinha key={`${a.campo}-${i}`} cols={COLS_DIFF}>
                    <GradeCel title={a.campo}>{a.campo}</GradeCel>
                    <GradeCel title={a.de}>{a.de}</GradeCel>
                    <GradeCel title={a.para}>{a.para}</GradeCel>
                  </GradeLinha>
                ))}
              </Grade>
            </div>
          </Secao>
        )}

        {/* 4. O REGISTRO TÉCNICO — o outro lado que o dono pediu. */}
        <Secao
          icon={ListTree}
          titulo="Registro técnico"
          sub="É o que está gravado no banco, palavra por palavra"
          cols={4}
          campos={tecnico}
        >
          <div className="mt-2">
            <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
              Dados adicionais do evento (campo details, em JSON)
            </div>
            {detalhes ? (
              <>
                {/* Leitura em português dos mesmos dados, acima do JSON: o JSON
                    é a prova, a lista é o que se lê. */}
                {detalhesSimples.length > 0 && (
                  <div className="mt-1.5">
                    <Campos
                      cols={3}
                      campos={detalhesSimples.map(([k, v]) => ({
                        rotulo: rotuloCampo(k),
                        valor: valorLegivel(k, v),
                        quebra: true,
                      }))}
                    />
                  </div>
                )}
                <pre
                  className="bi-id bi-scroll mt-2 max-h-64 overflow-auto rounded-lg p-2.5 text-[10px] leading-relaxed break-words whitespace-pre-wrap"
                  style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
                >
                  {JSON.stringify(detalhes, null, 2)}
                </pre>
              </>
            ) : (
              <p className="mt-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Este evento não gravou dados adicionais.
              </p>
            )}
          </div>
        </Secao>
      </ModalCorpo>
    </Modal>
  );
}
