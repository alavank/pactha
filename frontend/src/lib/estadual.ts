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
};

/** ⚠️ OS 19 QUE FALTAM, e por que não estão aqui.
 *
 *  AC AL AM AP BA CE DF MA MS MT PA PB PI RJ RN RO RR RS SE.
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
 *  ⚠️ NÃO é "o estado tem cadastro" — todos têm. É se NÓS coletamos. Hoje o
 *  único coletor é o do portal de Minas (`ingestion/cagec_scraper.py`), que só
 *  responde por ente mineiro. Quando entrar outro, esta lista cresce junto. */
export const UFS_ACOMPANHADAS = new Set<string>(["MG"]);

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

export function fonteConveniosEstaduais(uf?: string | null): string | null {
  return FONTE_CONVENIOS_ESTADUAIS[(uf || "").trim().toUpperCase()] || null;
}
