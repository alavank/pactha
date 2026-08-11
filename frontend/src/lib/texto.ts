import * as React from "react";

// COERÇÃO DE VALOR CRU DE FONTE EXTERNA.
//
// Por que existe: metade do que estas telas mostram é JSON repassado tal como
// veio do portal federal, e o portal NÃO promete que um campo seja escalar.
// `plano.objeto` da API de Transferências Especiais vem como
// `{ano, codigo, descricao, descricaoFormatada, funcoes, versao}`; `art.tipo`
// da API de obras vem como `{codigo, descricao}`. O tipo em TypeScript dizia
// `string?` — e TypeScript não valida nada em runtime, então a mentira só
// aparecia no navegador do cliente.
//
// E aparecia da pior forma: React se recusa a renderizar um objeto
// (erro #31 em produção) lançando de dentro do render, o que derruba a ÁRVORE
// INTEIRA. O sintoma que o dono via era "This page couldn't load" com botão de
// recarregar — nada que apontasse para um campo. Um único campo de um único
// registro apagava o sistema todo.
//
// A regra: nada de fonte externa entra no JSX sem passar por aqui.

/** Onde procurar o rótulo humano dentro de um objeto da fonte, em ordem de
 *  preferência. Estes nomes são a convenção do próprio TransfereGov (Java/
 *  Spring): `descricaoFormatada` é a versão pronta para tela ("830 - Sistema
 *  Simplificado..."), `descricao` é a crua, `nome` é como vem pessoa/empresa. */
const CHAVES_ROTULO = [
  "descricaoFormatada",
  "descricao",
  "nome",
  "rotulo",
  "label",
  "titulo",
  "sigla",
  "codigo",
] as const;

/** O texto que representa um valor cru — ou `null` quando não há o que mostrar.
 *
 *  Devolve `null`, e não `"-"`, de propósito: quem chama já tem seu próprio
 *  vazio ("-", "—", "Sem informação") e a peça não deve escolher por ele. */
export function textoDe(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  if (typeof v === "string") return v.trim() || null;
  if (typeof v === "number") return Number.isFinite(v) ? String(v) : null;
  if (typeof v === "boolean") return v ? "Sim" : "Não";
  if (Array.isArray(v)) {
    const partes = v.map(textoDe).filter((p): p is string => !!p);
    return partes.length ? partes.join(" · ") : null;
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    for (const k of CHAVES_ROTULO) {
      const c = o[k];
      if (typeof c === "string" && c.trim()) return c.trim();
      if (typeof c === "number" && Number.isFinite(c)) return String(c);
    }
    // Objeto que não sabemos nomear vira ausência de informação. Serializar o
    // JSON aqui seria pior: o gestor veria `{"versao":0,"funcoes":null}` numa
    // célula e concluiria que o sistema está quebrado — que é exatamente a
    // impressão que este arquivo existe para evitar.
    return null;
  }
  return null;
}

/** A rede de segurança das peças de UI: deixa passar tudo que o React sabe
 *  renderizar e converte o resto em texto.
 *
 *  Fica DENTRO das primitivas (`GradeCel`, `Campos`, `Selo`, `ItemLinha`), e
 *  não em cada tela, porque o risco não é uma tela: são as dezenas de campos
 *  que ainda vamos ligar a JSON de portal. Uma tela nova erra; a peça protege. */
export function noSeguro(v: React.ReactNode | unknown): React.ReactNode {
  if (v === null || v === undefined) return v as React.ReactNode;
  const t = typeof v;
  if (t === "string" || t === "number" || t === "boolean") return v as React.ReactNode;
  if (React.isValidElement(v)) return v;
  // Array de filhos: os elementos válidos já carregam `key` própria e passam
  // intactos; só os objetos crus do meio é que viram texto.
  if (Array.isArray(v)) return v.map((x) => noSeguro(x)) as React.ReactNode;
  if (t === "object") return textoDe(v);
  return null;
}
