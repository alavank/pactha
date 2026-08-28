// COMO CADA ESTADO CHAMA A REGULARIDADE PARA RECEBER CONVÊNIO ESTADUAL.
//
// ⚠️ POR QUE ISTO É UM MAPA, E NÃO UMA FÓRMULA.
// Não existe nome nacional. "CAGEC" é marca de Minas (Decreto 44.293/2006), e
// cada estado batizou o seu — e nem sempre é a mesma COISA: Minas tem um
// cadastro, Goiás um sistema, o Espírito Santo um portal, o Tocantins uma
// certidão. Gerar o rótulo por regra daria nome errado, que é o defeito que
// este arquivo existe para fechar: numa carteira multi-estado o sistema
// carimbava "CAGEC — Minas Gerais" sobre cidades de Goiás e do Espírito Santo.
//
// ⚠️ LINHA NOVA SÓ COM FONTE. Cada entrada abaixo foi pesquisada e traz de onde
// veio. UF ausente cai no rótulo genérico de propósito — genérico é chato, nome
// errado na tela do cliente é pior, e foi exatamente o que gerou esta correção.

export interface CadastroEstadual {
  /** Sigla, quando o estado tem uma. É o que vai no título. */
  sigla?: string;
  /** Nome por extenso, para o subtítulo. */
  nome: string;
  /** Título curto, quando o nome oficial não cabe num cartão. "Certidão de
   *  Regularidade de Transferências Voluntárias — Tocantins" tem 58 caracteres:
   *  quebra o cartão e não se lê de longe numa TV. O nome inteiro não some —
   *  desce para o subtítulo. */
  curto?: string;
  /** Quem opera, quando ajuda a localizar. */
  orgao?: string;
  /** O DOCUMENTO de onde sai o detalhamento, quando existe um. Em Minas as
   *  obrigações e validades vêm do CRC (certificado em PDF) e a tela precisa
   *  dizer de que leitura são; no RS as validades saem da consulta pública e
   *  não há certificado nenhum — falar em "CRC" ali é inventar documento. */
  certificado?: string;
  /** O que a irregularidade TRAVA — e é diferente por estado, e a diferença
   *  é material para o gestor: em Minas segura até a parcela de convênio já
   *  assinado; no RS o CHE é exigido para celebrar. Só entra com fonte. */
  trava?: string;
}

export const CADASTRO_ESTADUAL: Record<string, CadastroEstadual> = {
  // portalcagec.mg.gov.br — Cadastro Geral de Convenentes, Decreto 44.293/2006.
  MG: { sigla: "CAGEC", nome: "Cadastro Geral de Convenentes", certificado: "CRC",
        trava: "impede convênio estadual e liberação de parcela" },
  // portal.convenios.go.gov.br — Sistema Estadual de Gestão de Transferências
  // Voluntárias, operado pela Controladoria-Geral do Estado.
  GO: { sigla: "SIGECON", nome: "Sistema Estadual de Gestão de Transferências Voluntárias" },
  // convenios.es.gov.br — Portal de Convênios, da Secretaria de Gestão e
  // Recursos Humanos. Não usa sigla própria.
  ES: { nome: "Portal de Convênios", orgao: "SEGER" },
  // servicos.to.gov.br — a regularidade sai como CERTIDÃO, e não como cadastro
  // (Decreto estadual 5.815/2018), emitida pela Controladoria-Geral.
  TO: { nome: "Certidão de Regularidade de Transferências Voluntárias",
        curto: "Transferências Voluntárias", orgao: "CGE-TO" },
  // cge.sc.gov.br/sctransferencias — "SC Transferências".
  SC: { sigla: "SC Transferências", nome: "Transferências Voluntárias de Santa Catarina", orgao: "CGE-SC" },
  // scge.pe.gov.br/crt — Cadastro de Regularidade de Transferências, da
  // Secretaria da Controladoria-Geral do Estado.
  PE: { sigla: "CRT", nome: "Cadastro de Regularidade de Transferências", orgao: "SCGE-PE" },
  // fazenda.pr.gov.br — a Secretaria da Fazenda emite a certidão exigida pela
  // LRF para o município receber transferência voluntária do Estado.
  PR: { nome: "Certidão de Transferências Voluntárias",
        curto: "Transferências Voluntárias", orgao: "SEFAZ-PR" },
  // fazenda.sp.gov.br/TransferenciaVoluntaria — sistema próprio da SEFAZ.
  SP: { nome: "Sistema de Transferências Voluntárias",
        curto: "Transferências Voluntárias", orgao: "SEFAZ-SP" },
  // che.sefaz.rs.gov.br — Cadastro de Habilitação em Convênios do Estado,
  // Instrução Normativa CAGE nº 01/2006. Consulta pública, sem login.
  RS: { sigla: "CHE", nome: "Cadastro de Habilitação em Convênios do Estado",
        orgao: "CAGE/SEFAZ-RS", trava: "impede celebrar convênio com o Estado" },
};

/** O rótulo que vale em qualquer estado — e o que sai quando NÃO se sabe de
 *  qual estado é o dado. Genérico é chato; nome errado na tela do cliente é
 *  pior, e "CAGEC" em cima de município gaúcho foi exatamente o defeito. */
export const ROTULO_ESTADUAL_GENERICO = "Cadastro estadual";

function ufsLimpas(ufs?: ReadonlyArray<string | null | undefined> | null): string[] {
  const set = new Set<string>();
  for (const u of ufs || []) {
    const s = (u || "").trim().toUpperCase();
    if (s) set.add(s);
  }
  return [...set].sort();
}

/** A sigla curta do cadastro de um estado ("CAGEC", "CHE"), para caber num
 *  medidor ou num selo. Sem entrada no mapa, o genérico. */
export function siglaEstadual(uf?: string | null): string {
  const c = CADASTRO_ESTADUAL[(uf || "").trim().toUpperCase()];
  return c?.sigla || c?.curto || ROTULO_ESTADUAL_GENERICO;
}

/** ⭐ O NOME DO CADASTRO PARA UM CONJUNTO DE UFs — que é o que o Painel de
 *  Indicadores recebe (`ufs_na_fonte`), porque o escopo pode ser uma carteira.
 *  Um estado só → a sigla dele; vários ou nenhum → o genérico, que é
 *  verdadeiro em qualquer lugar. Nunca "CAGEC" por padrão. */
export function rotuloCadastroEstadual(ufs?: ReadonlyArray<string | null | undefined> | null): string {
  const lista = ufsLimpas(ufs);
  return lista.length === 1 ? siglaEstadual(lista[0]) : ROTULO_ESTADUAL_GENERICO;
}

/** `tituloEstadual` para um conjunto: "CHE — Rio Grande do Sul" com uma UF,
 *  "Cadastro estadual — MG, RS" com várias, o genérico sem nenhuma. */
export function tituloEstadualPorUfs(ufs?: ReadonlyArray<string | null | undefined> | null): string {
  const lista = ufsLimpas(ufs);
  if (lista.length === 1) return tituloEstadual(lista[0]);
  if (lista.length > 1) return `${ROTULO_ESTADUAL_GENERICO} — ${lista.join(", ")}`;
  return ROTULO_ESTADUAL_GENERICO;
}

/** `subtituloEstadual` para um conjunto — com várias UFs não há UM nome por
 *  extenso, então fica a descrição. */
export function subtituloEstadualPorUfs(ufs?: ReadonlyArray<string | null | undefined> | null): string {
  const lista = ufsLimpas(ufs);
  return lista.length === 1 ? subtituloEstadual(lista[0]) : "regularidade estadual para convênios";
}

/** O nome do estado para abrir uma frase ("Minas Gerais: 3 pendências"). Com
 *  várias UFs ou nenhuma, "Estado" — que é verdadeiro e não aponta para o
 *  lugar errado. */
export function nomeEstadoOuGenerico(ufs?: ReadonlyArray<string | null | undefined> | null): string {
  const lista = ufsLimpas(ufs);
  return lista.length === 1 ? (NOME_UF[lista[0]] || lista[0]) : "Estado";
}

/** O documento de onde sai o detalhamento ("CRC" em Minas), ou null onde o
 *  estado não emite certificado — aí a tela fala em "exigências", nunca em
 *  "documentos do CRC". */
export function certificadoEstadual(uf?: string | null): string | null {
  return CADASTRO_ESTADUAL[(uf || "").trim().toUpperCase()]?.certificado || null;
}

/** O que a irregularidade trava naquele estado. Sem entrada, a consequência
 *  mínima que vale em qualquer UF: sem cadastro não se celebra convênio. */
export function travaEstadual(uf?: string | null): string {
  return CADASTRO_ESTADUAL[(uf || "").trim().toUpperCase()]?.trava
    || "impede celebrar convênio com o Estado";
}

/** ⚠️ OS 19 QUE FALTAM, e por que não estão aqui.
 *
 *  AC AL AM AP BA CE DF MA MS MT PA PB PI RJ RN RO RR SE.
 *
 *  Não foi possível fechar o nome oficial de cada um em fonte do próprio
 *  Estado, e nome inventado na tela do cliente é pior que rótulo genérico — é
 *  justamente o defeito que este arquivo veio corrigir (o sistema carimbava
 *  "CAGEC — Minas Gerais" sobre cidade de Goiás). Sem entrada, `tituloEstadual`
 *  devolve "Cadastro estadual de convenentes — <Estado>", que é verdadeiro em
 *  qualquer UF.
 *
 *  Para acrescentar um: achar a página do próprio Estado (controladoria ou
 *  fazenda), copiar o nome como ele se escreve lá, e deixar a URL no comentário
 *  — como nas linhas acima. Uma linha, com fonte. */

/** Nome do estado por extenso. Fato estável e sem ambiguidade — o que NÃO é
 *  estável é o nome do sistema de cada um, que fica no mapa acima. */
export const NOME_UF: Record<string, string> = {
  AC: "Acre", AL: "Alagoas", AP: "Amapá", AM: "Amazonas", BA: "Bahia",
  CE: "Ceará", DF: "Distrito Federal", ES: "Espírito Santo", GO: "Goiás",
  MA: "Maranhão", MT: "Mato Grosso", MS: "Mato Grosso do Sul",
  MG: "Minas Gerais", PA: "Pará", PB: "Paraíba", PR: "Paraná",
  PE: "Pernambuco", PI: "Piauí", RJ: "Rio de Janeiro",
  RN: "Rio Grande do Norte", RS: "Rio Grande do Sul", RO: "Rondônia",
  RR: "Roraima", SC: "Santa Catarina", SP: "São Paulo", SE: "Sergipe",
  TO: "Tocantins",
};

/** O título da seção para um estado: "CAGEC — Minas Gerais", "SIGECON — Goiás",
 *  "Portal de Convênios — Espírito Santo". Sem entrada no mapa, o genérico. */
export function tituloEstadual(uf?: string | null): string {
  const sigla = (uf || "").trim().toUpperCase();
  const estado = NOME_UF[sigla] || sigla;
  const c = CADASTRO_ESTADUAL[sigla];
  if (!c) {
    return estado
      ? `Cadastro estadual de convenentes — ${estado}`
      : "Cadastro estadual de convenentes";
  }
  return `${c.sigla || c.curto || c.nome} — ${estado}`;
}

/** A linha fina embaixo do título: o nome por extenso e quem opera. */
export function subtituloEstadual(uf?: string | null): string {
  const sigla = (uf || "").trim().toUpperCase();
  const c = CADASTRO_ESTADUAL[sigla];
  if (!c) return "regularidade estadual para convênios";
  // O nome inteiro entra sempre que o título não o mostrou por completo — é onde
  // ele cabe, e é o termo que o gestor vai procurar no portal do Estado.
  const partes: string[] = [];
  if (c.sigla || c.curto) partes.push(c.nome);
  if (c.orgao) partes.push(c.orgao);
  return partes.length ? partes.join(" · ") : "regularidade estadual para convênios";
}

/** Este sistema acompanha a regularidade estadual deste estado hoje?
 *
 *  ⚠️ NÃO é "o estado tem cadastro" — todos têm. É se NÓS coletamos. Hoje são
 *  dois coletores: `ingestion/cagec_scraper.py` (portal de Minas, Playwright +
 *  PDF) e `ingestion/che_rs.py` (CHE gaúcho, API JSON pública). Cada um só
 *  responde por ente do seu estado. Quando entrar outro, esta lista cresce junto.
 *
 *  ⚠️ E ela cresce SÓ COM COLETOR NO AR, nunca "porque o estado tem cadastro":
 *  esta lista é o que faz o medidor da Visão Geral afirmar que a regularidade
 *  está acompanhada. Entrar aqui com a tabela vazia é prometer cobertura que
 *  não existe. */
export const UFS_ACOMPANHADAS = new Set<string>(["MG", "RS"]);

export function acompanhamosEstadual(uf?: string | null): boolean {
  return UFS_ACOMPANHADAS.has((uf || "").trim().toUpperCase());
}

/** A fonte de CONVÊNIOS estaduais que este sistema JÁ coleta, por UF.
 *
 *  ⚠️ Isto é sobre CONVÊNIOS, não REGULARIDADE — as duas coberturas andam
 *  separadas. No ES coletamos os convênios (GConv/SEGER, dado aberto), mas a
 *  regularidade estadual ainda não (a certidão da SEFAZ tem captcha). Por isso
 *  este mapa existe ao lado de `UFS_ACOMPANHADAS` (regularidade), e não dentro
 *  dele: a aba Convênios do ES mostra dado real enquanto o medidor de
 *  regularidade continua, com razão, dizendo "ainda não acompanhada". */
export const FONTE_CONVENIOS_ESTADUAIS: Record<string, string> = {
  MG: "SIGCON-MG",
  ES: "GConv · SEGER",
};

/** A fonte de EMENDAS ESTADUAIS que este sistema coleta, por UF.
 *
 *  ⚠️ MAPA SEPARADO, e não um campo dentro do de convênios, porque emenda
 *  estadual não é a mesma coisa em todo estado — e a diferença é material para
 *  o cliente, não estética. Em Minas ela é IMPOSITIVA (a Constituição estadual
 *  obriga a execução, e o valor do PACTHA lá é justamente controlar o prazo
 *  constitucional). No Rio Grande do Sul ela é AUTORIZATIVA: definida ano a ano
 *  na LDO, sem prazo legal de pagamento. Carimbar na tela gaúcha o discurso
 *  mineiro seria induzir o gestor a erro sobre um direito que ele não tem.
 *
 *  Por isso o RS **não entra aqui** enquanto não houver coletor próprio — e,
 *  quando entrar, com o rótulo dizendo que são autorizativas. */
export const FONTE_EMENDAS_ESTADUAIS: Record<string, string> = {
  MG: "SIGCON-MG",
};

export function fonteEmendasEstaduais(uf?: string | null): string | null {
  return FONTE_EMENDAS_ESTADUAIS[(uf || "").trim().toUpperCase()] || null;
}

/** UFs com mecanismo de ORÇAMENTO PARTICIPATIVO cujo resultado nós coletamos.
 *
 *  ⚠️ Hoje só o RS, e não por limitação nossa: a Consulta Popular/COREDEs
 *  existe desde 1998 e não tem equivalente em Minas — é justamente o que
 *  nenhum concorrente que atende só MG consegue mostrar. Estado que criar (ou
 *  que já tenha) um mecanismo assim entra aqui, junto com o coletor. */
export const CONSULTA_POPULAR_POR_UF: Record<string, { titulo: string; fonte: string }> = {
  RS: { titulo: "Consulta Popular",
        fonte: "Consulta Popular / COREDEs · SPGG (consultapopular.rs.gov.br)" },
};

export function consultaPopularDaUf(uf?: string | null) {
  return CONSULTA_POPULAR_POR_UF[(uf || "").trim().toUpperCase()] || null;
}

/** UFs com CATÁLOGO DE PROGRAMAS estaduais de fomento mantido por nós.
 *
 *  ⚠️ Diferente dos mapas acima, este NÃO significa "coletamos": significa que
 *  há conteúdo curado sobre as linhas de fomento daquele estado. A regra do
 *  roadmap do RS (docs/MAPA_RS.md §13) é que nenhuma fonte fica de fora por não
 *  ser coletável — entrega-se o que dá, com o aviso de que a abertura de edital
 *  não é monitorada. Estado novo entra aqui junto com o catálogo em
 *  `services/programas_<uf>.py`. */
export const PROGRAMAS_POR_UF: Record<string, { titulo: string; fonte: string }> = {
  RS: { titulo: "Programas do Estado",
        fonte: "Avançar, Pavimenta, Assistir, RBC/RS, FEAPER e outros" },
};

export function programasDaUf(uf?: string | null) {
  return PROGRAMAS_POR_UF[(uf || "").trim().toUpperCase()] || null;
}

/** UFs para as quais mantemos as telas de CONTEÚDO ESTADUAL — fundo de
 *  reconstrução, emendas estaduais e obrigações do tribunal de contas.
 *
 *  ⚠️ Como `PROGRAMAS_POR_UF`, isto NÃO significa "coletamos": significa que há
 *  conteúdo curado. As três telas mostram o aviso de que não são atualizadas
 *  automaticamente — ver `components/rs/AvisoCurado.tsx`. */
export const CONTEUDO_ESTADUAL_POR_UF = new Set<string>(["RS"]);

export function temConteudoEstadual(uf?: string | null): boolean {
  return CONTEUDO_ESTADUAL_POR_UF.has((uf || "").trim().toUpperCase());
}

export function fonteConveniosEstaduais(uf?: string | null): string | null {
  return FONTE_CONVENIOS_ESTADUAIS[(uf || "").trim().toUpperCase()] || null;
}

/** UFs que publicam a EXECUÇÃO (pagamento) em vez do INSTRUMENTO (convênio).
 *
 *  ⚠️ Não é um detalhe técnico, é o que o estado divulga. MG e ES publicam o
 *  convênio (número, vigência, situação); Goiás publica o repasse (quem
 *  recebeu, quando, quanto). Por isso GO ganha uma tela PRÓPRIA em vez de
 *  aparecer na de Convênios com metade das colunas vazia. Estado novo que
 *  publique execução entra aqui. */
export const REPASSES_POR_UF: Record<string, { titulo: string; fonte: string }> = {
  GO: { titulo: "Repasses Estaduais",
        fonte: "Transferências Voluntárias · CGE-GO (dados abertos)" },
};

export function repassesDaUf(uf?: string | null) {
  return REPASSES_POR_UF[(uf || "").trim().toUpperCase()] || null;
}

/** UFs que publicam o COFINANCIAMENTO ESTADUAL DA SAÚDE (repasse do fundo
 *  estadual ao municipal). Em MG o equivalente é o Acordo FES — que é DÍVIDA,
 *  não repasse, e por isso tem tela própria. */
export const COFINANCIAMENTO_POR_UF: Record<string, { titulo: string; fonte: string }> = {
  GO: { titulo: "Cofinanciamento da Saúde",
        fonte: "SES-GO · Atenção Primária e Vigilância (dados abertos)" },
};

export function cofinanciamentoDaUf(uf?: string | null) {
  return COFINANCIAMENTO_POR_UF[(uf || "").trim().toUpperCase()] || null;
}

/** UFs cujo Diário Oficial este sistema JÁ busca. MG = Jornal Minas Gerais
 *  (dou_mg); ES = Diário dos Municípios do ES (dou_es). Um estado sem provedor
 *  não mostra a tela — o menu a esconde, em vez de abrir uma busca que iria ao
 *  diário errado. ⚠️ Cada UF nova aqui exige um provedor no backend.
 *
 *  O valor é o PREFIXO da rota da API, e é o que a tela usa para falar com o
 *  provedor certo — assim entrar com um estado novo é uma linha aqui, e não um
 *  `if` a mais na página. */
export const DIARIO_POR_UF: Record<string, { api: string; titulo: string; fonte: string }> = {
  MG: { api: "/dou-mg", titulo: "Diário Oficial MG",
        fonte: "Jornal Minas Gerais (jornalminasgerais.mg.gov.br)" },
  ES: { api: "/dou-es", titulo: "Diário Oficial ES",
        fonte: "Diário dos Municípios do Espírito Santo (ioes.dio.es.gov.br)" },
  GO: { api: "/dou-go", titulo: "Diário Oficial GO",
        fonte: "Diário Oficial do Estado de Goiás (diariooficial.abc.go.gov.br)" },
  /* ⚠️ O TO é OUTRA PLATAFORMA: a busca devolve EDIÇÕES, não páginas com
     trecho. A tela mostra a ficha da edição (número, páginas, tamanho) em vez
     de um excerto — a fonte não dá excerto, e inventar um seria pior. */
  TO: { api: "/dou-to", titulo: "Diário Oficial TO",
        fonte: "Diário Oficial do Estado do Tocantins (diariooficial.to.gov.br)" },
  /* O DOE-RS NÃO é SIGPub (por isso tem `services/diario_rs.py` próprio), mas é
     o mais simples dos quatro: API REST JSON pública da PROCERGS, com busca por
     texto e período. A matéria não tem página pública com URL estável — o que
     existe é o download em PDF. */
  RS: { api: "/dou-rs", titulo: "Diário Oficial RS",
        fonte: "Diário Oficial do Estado do RS (diariooficial.rs.gov.br · PROCERGS)" },
};

export function diarioDaUf(uf?: string | null) {
  return DIARIO_POR_UF[(uf || "").trim().toUpperCase()] || null;
}

export function temDiarioEstadual(uf?: string | null): boolean {
  return !!diarioDaUf(uf);
}


/* ==========================================================================
   O CATALOGO DE PERMISSOES POR ESTADO — pedido do dono, 08/2026.
   ==========================================================================

   O PROBLEMA que isto fecha: a aba Usuarios oferecia as MESMAS 24 telas e as
   MESMAS caixinhas em todo tenant. Quem cadastra alguem no sistema de Santa
   Maria/RS via «Acordo FES (divida saude MG)» e «Emendas Estaduais» (que so
   existem em Minas) na lista, e quem cadastra em Monte Siao/MG via modulos do
   Rio Grande do Sul. Marcar qualquer um deles nao dava erro nenhum — dava uma
   tela que abre vazia, que e a pior forma de errar: parece que o sistema esta
   quebrado, e nao que o modulo nao existe naquele estado.

   ⚠️ ISTO NAO E UMA TRAVA DE SEGURANCA, E CATALOGO. Quem separa o convenio do
   Espirito Santo do convenio de Goias continua sendo a lista de MUNICIPIOS da
   pessoa (o seletor logo acima, e `ensure_municipio_access` no servidor): a
   chave `convenios.ver` e UMA SO e serve os dois estados. O que estas funcoes
   fazem e nao oferecer ao administrador um modulo que naquela carteira nunca
   teria dado nenhum.

   ⚠️ NA DUVIDA, MOSTRA TUDO. Carteira vazia (ainda carregando, ou um
   administrador sem municipio marcado) devolve a lista inteira como federal:
   esconder por engano tiraria do administrador a caixinha que ele precisa
   marcar, e o custo do contrario e so oferecer um modulo a mais. */

/** Item de catalogo que sabe em que estados existe. `ufs` vazio ou ausente =
 *  federal/nacional. Espelha `ufs` de `backend/services/permissoes.py`. */
export interface ComUfs {
  ufs?: string[];
}

/** As UFs que a carteira do tenant realmente atende, sem repetir e sem vazio.
 *  Freitas devolve ["MG"]; a Trust devolve os estados das cidades dela. */
export function ufsDaCarteira(municipios: Array<{ uf?: string | null }>): string[] {
  const set = new Set<string>();
  for (const m of municipios) {
    const uf = (m?.uf || "").trim().toUpperCase();
    if (uf) set.add(uf);
  }
  return [...set];
}

export interface GrupoEstadual<T> {
  uf: string;
  /** "Minas Gerais" — o nome por extenso e o titulo do cartao. */
  nome: string;
  itens: T[];
}

export interface CatalogoPorEstado<T> {
  /** O que vale em qualquer estado. Sempre primeiro. */
  federais: T[];
  /** Um cartao por estado da carteira, na ordem alfabetica do NOME. Estado sem
   *  nenhum modulo proprio nao vira cartao — cartao vazio nao informa nada. */
  estados: Array<GrupoEstadual<T>>;
}

/** Separa um catalogo em «federais» + um grupo por estado da carteira.
 *
 *  ⚠️ UM ITEM PODE CAIR EM MAIS DE UM ESTADO, e isso e verdade e nao defeito:
 *  «Convenios Estaduais» e uma chave so que atende MG, ES, GO e RS. Ele aparece
 *  no cartao de cada estado da carteira que ele serve, e marcar num marca nos
 *  outros — quem chama deve dizer isso na tela quando `ufs.length > 1`. A
 *  alternativa (uma chave por estado) exigiria uma permissao nova por UF no
 *  backend, e o que separa os estados na pratica ja e a lista de municipios. */
export function agruparPorEstado<T extends ComUfs>(
  itens: T[],
  ufsCarteira: string[],
): CatalogoPorEstado<T> {
  const carteira = ufsCarteira
    .map((u) => (u || "").trim().toUpperCase())
    .filter(Boolean);
  // Sem carteira nao ha o que filtrar (ver "NA DUVIDA, MOSTRA TUDO").
  if (!carteira.length) return { federais: itens, estados: [] };

  const federais = itens.filter((i) => !i.ufs || i.ufs.length === 0);
  const estados = carteira
    .map((uf) => ({
      uf,
      nome: NOME_UF[uf] || uf,
      itens: itens.filter((i) => (i.ufs || []).includes(uf)),
    }))
    .filter((g) => g.itens.length > 0)
    .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  return { federais, estados };
}

/** As UFs de um item que a carteira REALMENTE atende — e o que a tela escreve
 *  ao lado de um modulo compartilhado ("vale tambem no Rio Grande do Sul").
 *  Listar as quatro UFs possiveis para um cliente que so tem duas seria
 *  prometer estado que aquele tenant nao atende. */
export function ufsAtendidas(item: ComUfs, ufsCarteira: string[]): string[] {
  const carteira = new Set(ufsCarteira.map((u) => (u || "").trim().toUpperCase()));
  return (item.ufs || []).filter((u) => carteira.has(u));
}
