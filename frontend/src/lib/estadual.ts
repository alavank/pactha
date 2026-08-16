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
}

export const CADASTRO_ESTADUAL: Record<string, CadastroEstadual> = {
  // portalcagec.mg.gov.br — Cadastro Geral de Convenentes, Decreto 44.293/2006.
  MG: { sigla: "CAGEC", nome: "Cadastro Geral de Convenentes" },
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
        orgao: "CAGE/SEFAZ-RS" },
};

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
};

export function diarioDaUf(uf?: string | null) {
  return DIARIO_POR_UF[(uf || "").trim().toUpperCase()] || null;
}

export function temDiarioEstadual(uf?: string | null): boolean {
  return !!diarioDaUf(uf);
}
