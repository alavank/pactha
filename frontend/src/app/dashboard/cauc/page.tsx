"use client";
// REGULARIDADE DE DOCUMENTAÇÃO — CAUC (federal) e CAGEC (estadual/MG) lado a lado.
//
// Estavam separados de mentira: para o gestor o assunto é UM só ("minha
// documentação está em dia para assinar convênio?"). O que muda é a esfera —
// União (CAUC/Tesouro) e Minas (CAGEC/SIGCON) —, então cada uma é uma coluna.
//
// O CAGEC vem do CRC (Certificado de Registro Cadastral) do portal do CAGEC,
// que sai por CNPJ, sem credencial, e traz cada obrigação com SITUAÇÃO e DATA DE
// VALIDADE. Por isso as linhas do CAGEC mostram a data e as do CAUC não: são
// fontes diferentes no mesmo formato, e a data só existe onde a fonte dá.
//
// PELE (identidade do Painel): a GRADE das exigências ficou — código · item ·
// situação · validade em colunas de largura fixa —, porque conferir o extrato
// linha a linha é o gesto da tela e o alinhamento é o que o torna possível. O
// que mudou foi só a pele: fim do verde em toda linha comprovada (trinta ✔
// verdes não informam nada — quando tudo é sinal, nada é sinal), selo cinza por
// padrão e COR só onde há alerta: pendência impeditiva e prazo vencido.
import React, { useEffect, useState } from "react";
import {
  ShieldCheck, ShieldAlert, Check, AlertTriangle, AlertCircle, Ban, Loader2,
  Clock, Info, Gavel, ExternalLink,
} from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { acompanhamosEstadual, subtituloEstadual, tituloEstadual } from "@/lib/estadual";
import { Bloco, BlocoHead, Lista, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";
import { formatDataHora, horasDesde } from "@/lib/bi-format";

interface Item {
  codigo: string;
  grupo: string;
  label: string;
  valor: string;
  tipo: "regular" | "pendente" | "na";
  status: string;
  /** Coluna própria, como no documento (dd/mm/aaaa). Null quando a fonte não dá
   *  data — todo "A Comprovar" e todo "Desativado" do CAUC. */
  validade?: string | null;
  /** Tradução do título oficial do grupo, para quem não vive o extrato. Só CAUC. */
  grupo_glossa?: string;
  /** Significado oficial de um status traiçoeiro. "Desativado" NÃO é dispensa. */
  nota?: string;
}

interface CaucResp {
  tem_dados: boolean;
  nome?: string;
  uf?: string;
  ibge?: string;
  populacao?: number;
  data_pesquisa?: string | null;
  regular?: boolean;
  pendencias?: number;
  pendencias_codigos?: string[];
  itens?: Item[];
  atualizado_em?: string | null;
}

/** Um cadastro do CAGEC. O município NÃO é uma linha só: prefeitura, Fundo
 *  Municipal de Saúde, FMAS e consórcios têm CRC próprio, e cada um trava
 *  APENAS o seu convênio — prefeitura regular não destrava o convênio da saúde
 *  se o fundo estiver irregular. */
interface Entidade {
  nome: string;
  cnpj?: string | null;
  tipo?: string | null;
  situacao?: string | null;
  regular?: boolean | null;
  validade?: string | null;
  itens?: Item[];
  pendencias?: number;
  numero_cadastro?: string | null;
  principal: boolean;
  data_pesquisa?: string | null;
  crc_em?: string | null;
  crc_erro?: string | null;
  detalhe_do_crc?: boolean;
}

interface CagecResp {
  tem_dados: boolean;
  motivo?: string;
  nome?: string;
  uf?: string;
  cnpj?: string;
  situacao?: string;
  regular?: boolean;
  validade?: string | null;
  itens?: Item[];
  pendencias?: number;
  pendencias_codigos?: string[];
  data_pesquisa?: string | null;
  atualizado_em?: string | null;
  /** Todas as entidades, a principal inclusive. Os campos de cima continuam
   *  sendo os da principal — contrato antigo intacto. */
  entidades?: Entidade[];
  pendencias_outras_entidades?: number;
  /** Procedência do detalhamento. A lista de obrigações não vem da consulta
   *  pública — vem do CRC em PDF. `crc_em` é a data da última emissão que
   *  conseguimos ler; `crc_erro`, a frase do próprio portal quando ele recusa. */
  crc_em?: string | null;
  crc_erro?: string | null;
  detalhe_do_crc?: boolean;
}

function fmtDate(iso?: string | null): string {
  if (!iso) return "-";
  try { return new Date(iso).toLocaleDateString("pt-BR", { timeZone: "UTC" }); }
  catch { return iso.slice(0, 10); }
}

/** "Atualizado em <data> <hora>", ao lado do nome da fonte.
 *
 *  ⚠️ O CAMPO É `atualizado_em` (TIMESTAMPTZ, hora da NOSSA coleta) e o fuso é
 *  Brasília, cravado em `formatDataHora`. Não use o `fmtDate` daqui: ele
 *  formata em `timeZone: "UTC"` — correto para data pura vinda do banco, errado
 *  para um instante, porque mostraria a hora do servidor (3h à frente).
 *
 *  O rodapé de cada esfera dizia isto em texto miúdo no fim da lista. Subiu
 *  para o cabeçalho porque a pergunta "isto está atualizado?" é a primeira que
 *  se faz ao abrir a tela, não a última. */
function SeloColeta({ em }: { em?: string | null }) {
  if (!em) return null;
  const h = horasDesde(em);
  const atrasado = h !== null && h > 26;
  return (
    <span
      className="text-[10px]"
      style={{ color: atrasado ? "var(--bi-warn)" : "var(--bi-muted)" }}
      title={atrasado ? "Sem coleta nova há mais de um dia" : undefined}
    >
      Atualizado em {formatDataHora(em)}
    </span>
  );
}

function agrupar(itens: Item[]): Array<[string, Item[]]> {
  const m = new Map<string, Item[]>();
  for (const it of itens) {
    const g = it.grupo || "Exigências";
    if (!m.has(g)) m.set(g, []);
    m.get(g)!.push(it);
  }
  return [...m.entries()];
}

/** Banner de situação da esfera — mesmo formato nas duas colunas.
 *
 *  Regular é CINZA de propósito: estar em dia é o estado normal e não pede
 *  ação. O vermelho fica reservado ao impedimento, que é a única informação
 *  desta tela capaz de fazer o gestor levantar da cadeira. */
function Situacao({
  regular, titulo, detalhe,
}: { regular: boolean; titulo: string; detalhe: string }) {
  return (
    /* `pt-3` sem `pb`: a margem que o BlocoHead já traz embaixo fecha o cartão.
       Anular com `mb-0` seria disputar a mesma propriedade com a peça, e quem
       ganha aí depende da ordem em que o Tailwind emite as classes. */
    /* CARTÃO INTEIRO EM VERMELHO quando há impedimento, não só o texto.
       Este é o primeiro bloco da tela: quem abre o módulo tem que ver que há
       algo errado ANTES de ler qualquer palavra. Com o cartão branco e só a
       frase em vermelho, o alerta competia em peso com o cabeçalho ao lado.
       O valor é o MESMO da faixa de irregularidade do Painel
       (components/bi/abas.tsx) — um vermelho lavado, que chama sem gritar.
       Não vale o inverso: cartão verde quando está regular pintaria a tela de
       cor no estado normal, que é o que esta identidade evita. */
    <Bloco
      className="px-3 pt-3"
      style={regular ? undefined : {
        background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
        borderColor: "color-mix(in oklab, var(--bi-crit) 28%, transparent)",
      }}
    >
      <BlocoHead
        icon={regular ? ShieldCheck : ShieldAlert}
        titulo={
          <span style={regular ? undefined : { color: "var(--bi-crit-ink)" }}>{titulo}</span>
        }
        sub={detalhe}
        right={
          /* Verde no "Regular" pelo mesmo motivo do ✔ da lista: nesta tela o
             cinza ja tem dono (o "Desativado"), e a mesma palavra nao pode
             ter duas cores em dois cantos da mesma tela. */
          <Selo tom={regular ? "ok" : "critico"}>
            {regular ? "Regular" : "Impedimento"}
          </Selo>
        }
      />
    </Bloco>
  );
}

/** Aviso de que a lista de obrigações do CAGEC NÃO está completa.
 *
 *  Por que existe: a lista detalhada não vem da consulta pública, vem do CRC em
 *  PDF. Em 01/08/2026 o portal do Estado passou a recusar a emissão para todo
 *  mundo ("Não foi possível recuperar dados do Convenente/Parceiro para geração
 *  do relatório" — reproduzido 9 vezes em 9, inclusive para Belo Horizonte), e
 *  a tela passou a exibir as duas linhas de fallback COMO SE FOSSEM o cadastro
 *  inteiro. Quem olhou viu um CAGEC com duas exigências e nenhuma pista de que
 *  faltavam 28 — inclusive o FGTS vencido, que é justamente o que trava o
 *  convênio. Uma tela que não sabe precisa dizer que não sabe. */
function AvisoCrc({ crcErro, crcEm, doCrc }: {
  crcErro?: string | null; crcEm?: string | null; doCrc?: boolean;
}) {
  // O gate é `doCrc`, NÃO `crcErro`. Condicionar tudo ao erro deixaria a tela
  // MUDA justamente nas linhas que já estavam no banco quando a coluna nasceu
  // (crc_erro NULL) — que é o estado de Monte Sião neste momento: sem
  // detalhamento, sem aviso, contando 2 documentos como se fosse o cadastro.
  // `doCrc === false` é a afirmação honesta: isto aqui não é o certificado.
  const semCrc = doCrc === false;
  if (!semCrc && !crcErro) return null;
  return (
    /* Um dos poucos lugares com cor: "a tela não sabe o que está mostrando" é
       alerta, e o aviso perde a função se ficar cinza no meio do cinza.
       O raio vem do token dos cartões rasos — este bloco convive com eles, e
       raio próprio era exatamente o que espalhava seis cantos diferentes. */
    <div
      className="border p-2.5"
      style={{
        borderRadius: "var(--bi-radius-sm)",
        borderColor: "color-mix(in oklab, var(--bi-warn) 35%, transparent)",
        background: "color-mix(in oklab, var(--bi-warn) 8%, transparent)",
      }}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-[2px] size-3.5 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
        <div className="min-w-0 text-[10px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          <div className="text-[11px] font-semibold" style={{ color: "var(--bi-text)" }}>
            {semCrc
              ? "Documentos não conferidos — certificado indisponível"
              : `Documentos conferidos em ${fmtDate(crcEm)} — leitura nova indisponível`}
          </div>
          <div className="mt-0.5">
            A lista de documentos e suas validades vem do certificado (CRC), emitido
            pelo portal do CAGEC.{" "}
            {crcErro
              ? <>Nesta consulta ele não saiu. O portal respondeu: <em>“{crcErro}”</em></>
              : <>Nesta consulta ele não pôde ser lido.</>}
          </div>
          <div className="mt-1">
            {semCrc
              ? <>Abaixo aparece <strong>apenas</strong> o que a consulta pública mostra —
                  a situação do cadastro, sem os documentos. Não é a lista de exigências.</>
              : <>A lista abaixo é da leitura de <strong>{fmtDate(crcEm)}</strong> e pode
                  estar desatualizada: um documento pode ter vencido depois disso.</>}
            {" "}A situação e o impedimento acima continuam atualizados.
          </div>
        </div>
      </div>
    </div>
  );
}

/** Obrigação marcada "Vigente" cujo prazo já passou.
 *
 *  Acontece com lista PRESERVADA: o CRC de 01/08 diz que a certidão vale até
 *  10/08, e em 20/08 continuamos exibindo a mesma linha em verde. Pintar de
 *  verde certidão vencida é a pior saída possível — o gestor confia e perde a
 *  parcela. Só um CRC novo poderia reclassificar; até lá, a linha vira alerta. */
function venceu(validade?: string | null): boolean {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec((validade || "").trim());
  if (!m) return false;
  const h = new Date();
  return new Date(+m[3], +m[2] - 1, +m[1]) < new Date(h.getFullYear(), h.getMonth(), h.getDate());
}

/** Uma linha é alerta quando trava convênio: pendência impeditiva, ou "Vigente"
 *  com prazo já vencido (só CAGEC — ver `venceu`). Sai daqui, e não de cada
 *  ponto da tela, para o contador do grupo e o realce da linha não divergirem. */
function alerta(it: Item, esfera: "cauc" | "cagec"): "critico" | "atencao" | null {
  if (it.tipo === "pendente") return "critico";
  if (esfera === "cagec" && it.tipo === "regular" && venceu(it.validade)) return "atencao";
  return null;
}

/** Os DEMAIS cadastros do município no CAGEC (fundos, autarquias, consórcios).
 *
 *  Eles já eram coletados e já vinham na resposta da API — a tela é que lia só
 *  os campos do topo, que são os da prefeitura. Resultado: o Fundo Municipal de
 *  Saúde de Monte Sião (CNPJ 11.875.540/0001-35, cadastro 11896, REGULAR) era
 *  invisível, e o secretário de saúde não tinha como saber o estado do cadastro
 *  que trava justamente o convênio dele.
 *
 *  A situação de cada um fica VISÍVEL sem abrir — é a informação que decide
 *  ação. O detalhe item a item fica dentro do `details` para não empurrar a
 *  coluna da prefeitura para fora da tela. */
function OutrasEntidades({ entidades }: { entidades: Entidade[] }) {
  const outras = entidades.filter((e) => !e.principal);
  if (!outras.length) return null;
  return (
    <div className="space-y-2">
      <div>
        <h3 className="bi-title text-[13px] leading-tight">
          Outros cadastros deste município ({outras.length})
        </h3>
        <p className="mt-0.5 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
          Cada entidade tem CRC próprio e trava <strong>apenas o seu</strong> convênio:
          a prefeitura estar regular não libera o convênio da saúde se o fundo estiver irregular.
        </p>
      </div>
      <Lista>
        {outras.map((e) => {
          const ok = e.regular === true;
          const pend = e.pendencias || 0;
          // A situação vem escrita pela fonte ("REGULAR", "NÃO HABILITADA"), então
          // quem classifica é a regra única do sistema. O booleano `regular` só
          // entra quando ela é falsa: aí é impedimento, escreva a fonte o que
          // escrever.
          // `regular === true` -> verde, como o "Regular" do banner e o ✔ da
          // lista. `situacaoTom` devolveria NEUTRO para a palavra "Regular"
          // (ela nao esta na lista de termos de alerta), e a entidade ficaria
          // cinza ao lado de um banner verde dizendo a mesma coisa.
          const tomSit = e.regular === false ? "critico"
            : e.regular === true ? "ok"
            : situacaoTom(e.situacao);
          return (
            <li key={e.cnpj || e.nome} className="bi-card-flat overflow-hidden">
              <details>
                {/* `flex` no summary é o que esconde o triângulo nativo no
                    Chrome — trocar por bloco faria o marcador reaparecer em cima
                    do nome da entidade. */}
                <summary className="flex cursor-pointer items-start gap-2 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium leading-snug">{e.nome}</div>
                    <div
                      className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] leading-snug"
                      style={{ color: "var(--bi-faint)" }}
                    >
                      <Selo tom={tomSit} title={`Situação no CAGEC: ${e.situacao || (ok ? "Regular" : "Irregular")}`}>
                        {e.situacao || (ok ? "Regular" : "Irregular")}
                      </Selo>
                      <span>{e.tipo || "entidade"}</span>
                      {e.cnpj && <span className="font-mono">CNPJ {e.cnpj}</span>}
                      {e.numero_cadastro && <span className="font-mono">cadastro nº {e.numero_cadastro}</span>}
                      {/* Este resumo é a ÚNICA coisa visível com o bloco fechado, e
                          é onde o Fundo Municipal de Saúde apareceu como "Regular ·
                          sem pendência" sem que nada tivesse sido conferido.
                          "sem pendência" exige documentos lidos; contador de leitura
                          antiga exige a data junto, senão passa por atual. */}
                      <span
                        style={pend && e.detalhe_do_crc !== false
                          ? { color: "var(--bi-crit-ink)" } : undefined}
                      >
                        {e.detalhe_do_crc === false
                          ? "documentos não conferidos"
                          : e.crc_erro
                            ? `documentos de ${fmtDate(e.crc_em)}`
                            : pend ? `${pend} pendência(s)` : "sem pendência"}
                      </span>
                    </div>
                  </div>
                </summary>
                <div
                  className="space-y-2 border-t px-3 py-3"
                  style={{ borderColor: "var(--bi-line)" }}
                >
                  <AvisoCrc crcErro={e.crc_erro} crcEm={e.crc_em} doCrc={e.detalhe_do_crc} />
                  {/* Mesma ressalva do banner da prefeitura: `validade` é a próxima
                      obrigação a vencer, não a validade do certificado — o CRC não
                      tem uma. */}
                  {e.validade && (
                    <p className="text-[10px]" style={{ color: "var(--bi-muted)" }}>
                      Próxima obrigação a vencer: <strong>{fmtDate(e.validade)}</strong>.
                    </p>
                  )}
                  <Exigencias itens={e.itens || []} esfera="cagec" />
                </div>
              </details>
            </li>
          );
        })}
      </Lista>
    </div>
  );
}

/** Lista de exigências por bloco, no MESMO desenho do extrato oficial:
 *  código · Item Legal · **Situação** · **Validade**.
 *
 *  GRADE de largura fixa, não flex — pelo mesmo motivo do Painel: rótulo que
 *  quebra em duas linhas não pode empurrar as colunas da direita, e no CAGEC o
 *  código (de "CNPJ" a "AUTORIZ-ELETRONICA") deslocava o início de cada rótulo.
 *  É a mesma promessa do `<Campos>` das outras telas — coluna na mesma posição
 *  em todo lugar —, só que aqui o conteúdo é literalmente um extrato, e por isso
 *  continua grade e não vira cartão por exigência.
 *
 *  O CAGEC não tem coluna de código: aqueles identificadores são NOSSOS (o CRC
 *  não os imprime) e os informativos — os oito "Item 3.1.2 -…" — já vêm no
 *  próprio rótulo. */
function Exigencias({ itens, esfera = "cauc" }: { itens: Item[]; esfera?: "cauc" | "cagec" }) {
  if (!itens.length) {
    return <Vazio>Nenhuma exigência detalhada nesta esfera.</Vazio>;
  }
  const cols = esfera === "cauc"
    ? "grid-cols-[1.25rem_3rem_minmax(0,1fr)_7.5rem_6rem]"
    : "grid-cols-[1.25rem_minmax(0,1fr)_7.5rem_6rem]";
  return (
    <div className="space-y-2">
      {agrupar(itens).map(([grupo, lista]) => {
        const emAlerta = lista.filter((it) => alerta(it, esfera)).length;
        return (
          <Bloco key={grupo} className="p-3">
            {/* Título = o LITERAL do extrato ("III - Obrigações de
                Transparência"), para casar na conferência. A glosa embaixo,
                para quem não vive o documento. */}
            <BlocoHead
              titulo={grupo}
              sub={lista[0]?.grupo_glossa}
              right={
                emAlerta
                  ? <Selo tom="critico">{emAlerta} em alerta</Selo>
                  : <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                      {lista.length} {lista.length === 1 ? "item" : "itens"}
                    </span>
              }
            />
            <div
              className={`grid ${cols} items-end gap-x-3 border-b px-2 pb-1 text-[9px] uppercase tracking-wide`}
              style={{ borderColor: "var(--bi-line)", color: "var(--bi-faint)" }}
            >
              <span />
              {esfera === "cauc" && <span>Item</span>}
              <span>Item legal</span>
              <span>Situação</span>
              <span className="text-right">Validade</span>
            </div>
            {/* Sem divisória entre as linhas: o que separa é o espaço, e o que
                salta é o fundo das que estão em alerta. Régua em toda linha faz
                a grade inteira gritar no mesmo tom do problema. */}
            <div className="mt-1 flex flex-col gap-0.5">
              {lista.map((it) => {
                const nivel = alerta(it, esfera);
                const vencido = nivel === "atencao";
                // A situação vem escrita pela fonte; a classificação é a regra
                // única do sistema. `tipo === "pendente"` tem precedência porque
                // "A Comprovar" não parece alerta em texto nenhum — e é o que
                // trava a transferência.
                // VERDE de propósito em "Comprovado"/"Vigente", contra a regra
                // geral de "cor só em alerta". Decisão do dono, e o argumento
                // dele é melhor que o meu: nesta tela o CINZA já tem dono — é o
                // "Desativado", e inativo em cinza é convenção que o usuário
                // traz de todo sistema. Pintar o comprovado de cinza junto
                // apagava essa distinção, que é a mais útil da tela.
                // Aqui a cor não é enfeite: é o estado do documento.
                const tomStatus = nivel === "critico" ? "critico"
                  : vencido ? "atencao"
                  : it.tipo === "regular" ? "ok"
                  : it.tipo === "na" ? "neutro"
                  : situacaoTom(it.status);
                return (
                  <div
                    key={it.codigo}
                    className={`grid ${cols} items-start gap-x-3 rounded-lg px-2 py-1.5`}
                    style={nivel
                      ? { background: `color-mix(in oklab, var(--bi-${nivel === "critico" ? "crit" : "warn"}) 9%, transparent)` }
                      : undefined}
                  >
                    {/* Símbolo por esfera, como nos dois documentos: o CAUC marca
                        Comprovado / A Comprovar / Desativado; o CAGEC, Vigente /
                        Vencido. Só os dois primeiros têm cor — o ✔ é cinza porque
                        trinta ✔ verdes escondem o único ⚠ que importa. */}
                    <span className="mt-[3px]">
                      {nivel === "critico"
                        ? (esfera === "cagec"
                            ? <AlertTriangle className="size-3.5" style={{ color: "var(--bi-crit-ink)" }} />
                            : <AlertCircle className="size-3.5" style={{ color: "var(--bi-crit-ink)" }} />)
                        : vencido ? <Clock className="size-3.5" style={{ color: "var(--bi-warn-ink)" }} />
                        : it.tipo === "regular" ? <Check className="size-3.5" style={{ color: "var(--bi-ok-ink)" }} />
                        : <Ban className="size-3.5" style={{ color: "var(--bi-faint)" }} />}
                    </span>
                    {esfera === "cauc" && (
                      /* `font-mono` e não `bi-num`: "1.3" aqui é identificador do
                         extrato, não número — negrito tabular o promoveria acima
                         do próprio item legal. */
                      <span className="font-mono text-[11px] leading-5" style={{ color: "var(--bi-faint)" }}>
                        {it.codigo}
                      </span>
                    )}
                    <div className="min-w-0">
                      <div
                        className={`text-[13px] leading-snug ${nivel === "critico" ? "font-medium" : ""}`}
                        style={{ color: nivel === "critico" ? "var(--bi-crit-ink)" : "var(--bi-text)" }}
                      >
                        {it.label}
                      </div>
                      {/* A nota existe porque duas palavras do extrato enganam:
                          "Desativado" não é dispensa (é falha da ferramenta, para
                          TODOS os entes) e "A Comprovar" não acusa o município. */}
                      {it.nota && (
                        <div className="mt-0.5 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                          {it.nota}
                        </div>
                      )}
                    </div>
                    <span className="min-w-0">
                      {/* O documento dizia "Vigente" quando foi lido; hoje o prazo
                          passou. Repetir "Vigente" seria transcrever fielmente uma
                          informação que deixou de ser verdade. */}
                      <Selo tom={tomStatus} title={vencido ? `A fonte registrou “${it.status}”, mas a validade já passou.` : it.status}>
                        {vencido ? "Prazo vencido" : it.status}
                      </Selo>
                    </span>
                    {/* Validade SEMPRE presente, como no extrato. "—" quando a fonte
                        não dá data: ausência de data é informação, não buraco. */}
                    <span
                      className="bi-num whitespace-nowrap text-right text-[11px] leading-5"
                      style={{
                        color: nivel === "critico" ? "var(--bi-crit-ink)"
                          : vencido ? "var(--bi-warn-ink)"
                          : "var(--bi-muted)",
                      }}
                    >
                      {it.validade || "—"}
                    </span>
                  </div>
                );
              })}
            </div>
          </Bloco>
        );
      })}
    </div>
  );
}

/** Contas julgadas irregulares no tribunal de contas do estado.
 *  ⚠️ INDÍCIO, não documento — ver `migrations/add_contas_irregulares.sql`. */
interface ContasResp {
  tem_dados: boolean;
  total: number;
  prefeitura: number;
  autarquias: number;
  de_prefeito: number;
  fonte: string | null;
  itens: Array<{
    entidade: string | null;
    responsavel: string | null;
    assunto: string | null;
    competencia: string | null;
    processo: string | null;
    dt_julgamento: string | null;
    tipo_lista: string | null;
    url: string | null;
  }>;
}

export default function RegularidadePage() {
  const { municipioId } = useMunicipio();

  const [cauc, setCauc] = useState<CaucResp | null>(null);
  /* A UF vem do próprio extrato do CAUC (que é federal e cobre o país inteiro),
     e não de uma lista escrita aqui: é o dado que já está na tela. Enquanto ele
     não chegou, nada é anunciado — não se fala da cobertura antes de saber de
     onde é o município. */
  const ufDoMunicipio = (cauc?.uf || "").toUpperCase();
  /* Nome e cobertura vêm do mapa por UF (`lib/estadual.ts`), onde cada linha é
     pesquisada — e não de um `!== "MG"` escrito aqui. */
  const semFonteEstadual = !!ufDoMunicipio && !acompanhamosEstadual(ufDoMunicipio);
  const [cagec, setCagec] = useState<CagecResp | null>(null);
  /* ⚠️ FORA DO MEDIDOR, de propósito: a ausência de conta irregular NÃO é
     regularidade — é "sem conta irregular listada". Verde por isto colocaria um
     "apto" falso na frente de um prefeito. */
  const [contas, setContas] = useState<ContasResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Busca de dados: os setState aqui são o "carregando" da primeira pintura e
    // a limpeza ao trocar de município — sincronização com fonte externa, não
    // render em cascata (mesma convenção do resto do app).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!municipioId) { setCauc(null); setCagec(null); setContas(null); setLoading(false); return; }
    setLoading(true);
    // As duas esferas em paralelo, com allSettled: uma falhar não pode apagar a
    // outra da tela — são fontes independentes (Tesouro e SIGCON).
    Promise.allSettled([
      api.get<CaucResp>("/cauc", { params: { municipio_id: municipioId } }),
      api.get<CagecResp>("/cagec", { params: { municipio_id: municipioId } }),
      api.get<ContasResp>("/contas-irregulares", { params: { municipio_id: municipioId } }),
    ]).then(([a, b, c]) => {
      setCauc(a.status === "fulfilled" ? a.value.data : null);
      setCagec(b.status === "fulfilled" ? b.value.data : null);
      setContas(c.status === "fulfilled" ? c.value.data : null);
    }).finally(() => setLoading(false));
  }, [municipioId]);

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
          <ShieldCheck className="size-6" style={{ color: "var(--bi-muted)" }} />
          Regularidade de Documentação
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Exigências para assinar convênio nas duas esferas: a <strong>federal</strong>{" "}
          (CAUC, Tesouro Nacional) e a <strong>estadual</strong> — o cadastro de
          convenentes do estado deste município, nomeado na coluna ao lado.
        </p>
      </div>

      {!municipioId && <Vazio>Selecione um município para ver a situação.</Vazio>}

      {municipioId && loading && (
        <div className="flex justify-center py-16">
          <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      )}

      {municipioId && !loading && (
        <div className="grid gap-4 xl:grid-cols-2">
          {/* ---------------- CAUC (federal) ---------------- */}
          <section className="space-y-2.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              {/* 14px é o tamanho de título do <BlocoHead>: este h2 encabeça a
                  coluna inteira e tem que ler como cabeçalho do sistema, não
                  como um degrau próprio. 15px não existia em nenhuma outra tela. */}
              <h2 className="bi-title text-[14px]">CAUC — União</h2>
              <SeloColeta em={cauc?.atualizado_em} />
              <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                Tesouro Nacional{cauc?.data_pesquisa ? ` · extrato de ${fmtDate(cauc.data_pesquisa)}` : ""}
              </span>
            </div>

            {!cauc?.tem_dados ? (
              <Vazio>
                Sem dados do CAUC para este município ainda. (A base é atualizada automaticamente.)
              </Vazio>
            ) : (
              <>
                <Situacao
                  regular={!!cauc.regular}
                  titulo={cauc.regular ? "Regular no CAUC" : `${cauc.pendencias} pendência(s) impeditiva(s)`}
                  detalhe={`${cauc.nome}/${cauc.uf}` + (cauc.regular
                    ? " — apto a receber transferências voluntárias da União."
                    : ` — itens ${(cauc.pendencias_codigos || []).join(", ")} podem travar transferências.`)}
                />
                <Exigencias itens={cauc.itens || []} esfera="cauc" />

              </>
            )}
          </section>

          {/* ---------------- CAGEC (estadual / MG) ---------------- */}
          <section className="space-y-2.5">
            <div className="flex flex-wrap items-baseline gap-x-2">
              {/* ⚠️ O TÍTULO É DO AMBIENTE ABERTO, e "CAGEC" é nome de Minas
                  (Decreto 44.293/2006) — não do produto. Num ambiente do ES ou
                  de GO nada aqui pode falar de Minas: o cliente trocou de
                  ambiente, e o ambiente é dele. */}
              <h2 className="bi-title text-[14px]">{tituloEstadual(ufDoMunicipio)}</h2>
              {!semFonteEstadual && <SeloColeta em={cagec?.atualizado_em} />}
              <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                {subtituloEstadual(ufDoMunicipio)}
              </span>
            </div>

            {semFonteEstadual ? (
              /* ⚠️ TRÊS ESTADOS DE COISA DIFERENTE, e a tela precisa separar:
                   "em dia / irregular"  — coletamos e sabemos;
                   "aguardando coleta"   — a fonte cobre este ente e ainda não veio;
                   "fora da nossa coleta" — a fonte que temos não responde por ele.
                 O terceiro caso é este. Dizer "aguardando" promete um dado que
                 não vai chegar; dizer "não se aplica" afirmaria que o município
                 NÃO TEM cadastro estadual — e disso não sabemos nada. Cadastro
                 estadual de convenentes existe em outros estados; o que é de
                 Minas é o portal que este sistema sabe consultar. */
              <Bloco className="p-4">
                <div className="flex items-start gap-2.5">
                  <Info className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-faint)" }} />
                  <div className="space-y-1.5">
                    <div className="bi-title text-[13px] leading-tight">
                      Ainda não acompanhado
                    </div>
                    <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      A regularidade estadual de <b>{tituloEstadual(ufDoMunicipio)}</b> ainda
                      não é acompanhada por este sistema — a consulta segue sendo no portal
                      do próprio Estado. A regularidade <b>federal</b> (CAUC, ao lado)
                      continua valendo normalmente.
                    </p>
                  </div>
                </div>

                {/* ⭐ O QUE TEMOS, mesmo sem o cadastro: contas julgadas
                    irregulares no tribunal de contas do estado.

                    ⚠️ A REDAÇÃO AQUI É O PRODUTO. Isto é INDÍCIO, e a tela tem
                    de dizer as duas coisas que ele NÃO significa: (a) não é a
                    situação do município para convênio; (b) nenhuma linha não
                    quer dizer regular. Um bloco mal escrito aqui vira "está
                    tudo certo" na cabeça de quem lê — que é o oposto do dado. */}
                {contas?.tem_dados && (
                  <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                    <div className="flex items-start gap-2.5">
                      <Gavel className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
                      <div className="min-w-0 space-y-1.5">
                        <div className="bi-title text-[13px] leading-tight">
                          {contas.total} conta(s) julgada(s) irregular(es) no {contas.fonte}
                        </div>
                        <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                          {contas.prefeitura > 0
                            ? <>{contas.prefeitura} da <b>prefeitura</b></>
                            : <>nenhuma da prefeitura</>}
                          {contas.autarquias > 0 && <> · {contas.autarquias} de autarquias e fundos</>}
                          {contas.de_prefeito > 0 && <> · <b>{contas.de_prefeito} de prefeito ou ex-prefeito</b></>}
                          .{" "}
                          É <b>indício</b>, não a situação do município para convênio: a lista
                          diz quem tem conta julgada irregular, e <b>não</b> atesta regularidade
                          de quem não aparece nela.
                        </p>
                        <ul className="space-y-1 pt-0.5">
                          {contas.itens.slice(0, 4).map((c, i) => (
                            <li key={i} className="text-[11px] leading-snug"
                                style={{ color: "var(--bi-muted)" }}>
                              <span style={{ color: "var(--bi-text)" }}>
                                {c.entidade || "Prefeitura"}
                              </span>
                              {c.responsavel ? ` · ${c.responsavel}` : ""}
                              {c.assunto ? ` · ${c.assunto}` : ""}
                              {c.processo ? ` · proc. ${c.processo}` : ""}
                              {c.url && (
                                <a href={c.url} target="_blank" rel="noopener noreferrer"
                                   className="ml-1 inline-flex items-center gap-0.5"
                                   style={{ color: "var(--bi-accent-ink)" }}>
                                  ver <ExternalLink className="size-3" />
                                </a>
                              )}
                            </li>
                          ))}
                          {contas.total > 4 && (
                            <li className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                              … e mais {contas.total - 4}.
                            </li>
                          )}
                        </ul>
                      </div>
                    </div>
                  </div>
                )}
              </Bloco>
            ) : !cagec?.tem_dados ? (
              /* Aguardando coleta — e dizendo POR QUÊ. Deixar em branco faria
                 parecer que não existe regularidade estadual a acompanhar;
                 pintar de verde seria pior, porque seria lido como "em dia". */
              <Bloco className="p-4">
                <div className="flex items-start gap-2.5">
                  <Clock className="mt-0.5 size-4 shrink-0" style={{ color: "var(--bi-warn-ink)" }} />
                  <div className="space-y-1.5">
                    <div className="bi-title text-[13px] leading-tight">Aguardando coleta</div>
                    <p className="text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      {cagec?.motivo
                        || "O CAGEC deste município ainda não foi coletado."}
                    </p>
                    {/* A coleta do CAGEC NÃO usa credencial — a consulta do portal
                        é pública e basta o CNPJ. Mandar o gestor cadastrar senha
                        aqui seria trabalho inútil. O que falta, quando falta, é o
                        CNPJ do município nas bases. */}
                    <p className="text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                      A consulta do CAGEC é pública e usa o CNPJ do município — não
                      depende de senha. Se o CNPJ ainda não foi identificado nas bases,
                      a coleta o encontra assim que houver emenda estadual ou registro
                      no PAC.
                    </p>
                  </div>
                </div>
              </Bloco>
            ) : (
              <>
                <Situacao
                  regular={!!cagec.regular}
                  titulo={cagec.regular ? "Regular no CAGEC" : (cagec.situacao || `${cagec.pendencias} pendência(s)`)}
                  /* `validade` NÃO é a validade do certificado — o CRC não tem uma.
                     É a data mais próxima entre as obrigações ainda vigentes, ou
                     seja, o próximo prazo a segurar. Chamar de "certificado válido
                     até" faria o gestor achar que tem até lá para tudo. */
                  /* O banner fala do cadastro da PREFEITURA. Se um fundo estiver
                     irregular, "Regular no CAGEC" seria lido como "o município
                     está liberado" — e não está: o convênio daquele fundo
                     continua travado. Por isso a pendência das outras entidades
                     entra aqui, no lugar mais visível da coluna. */
                  detalhe={`${cagec.nome}/${cagec.uf}` + (cagec.validade
                    ? ` — próxima obrigação a vencer: ${fmtDate(cagec.validade)}.`
                    : " — cadastro de convenentes do Estado de Minas Gerais.")
                    + (cagec.pendencias_outras_entidades
                      ? ` Atenção: outra(s) entidade(s) do município somam ${cagec.pendencias_outras_entidades} pendência(s) — veja abaixo.`
                      : "")}
                />
                <AvisoCrc crcErro={cagec.crc_erro} crcEm={cagec.crc_em}
                  doCrc={cagec.detalhe_do_crc} />
                <Exigencias itens={cagec.itens || []} esfera="cagec" />
                <OutrasEntidades entidades={cagec.entidades || []} />
                {cagec.crc_em && (
                  <p className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    Documentos conferidos no CRC de {fmtDate(cagec.crc_em)}.
                  </p>
                )}
              </>
            )}
          </section>
        </div>
      )}

      {municipioId && !loading && (
        <div
          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]"
          style={{ color: "var(--bi-faint)" }}
        >
          {/* A legenda espelha as PALAVRAS dos dois documentos, porque cada
              esfera usa o seu vocabulario e a tela existe para ser conferida
              contra o extrato. NUNCA escrever "nao exigido" para o Desativado:
              o texto oficial diz que a desativacao e da FERRAMENTA, "para todos
              os entes federativos". O caso que prova e o FGTS — item 1.3,
              desativado no CAUC, e ao mesmo tempo VENCIDO no CAGEC na coluna ao
              lado, travando convenio estadual. */}
          <span className="font-semibold" style={{ color: "var(--bi-muted)" }}>CAUC:</span>
          <span className="inline-flex items-center gap-1">
            <Check className="size-3" style={{ color: "var(--bi-ok-ink)" }} /> Comprovado
          </span>
          <span className="inline-flex items-center gap-1" style={{ color: "var(--bi-crit-ink)" }}>
            <AlertCircle className="size-3" /> A Comprovar (impeditivo)
          </span>
          <span className="inline-flex items-center gap-1">
            <Ban className="size-3" /> Desativado (indisponível na fonte — não é dispensa)
          </span>
          <span className="font-semibold" style={{ color: "var(--bi-muted)" }}>Estadual:</span>
          <span className="inline-flex items-center gap-1">
            <Check className="size-3" style={{ color: "var(--bi-ok-ink)" }} /> Vigente
          </span>
          <span className="inline-flex items-center gap-1" style={{ color: "var(--bi-crit-ink)" }}>
            <AlertTriangle className="size-3" /> Vencido (impeditivo)
          </span>
          {/* Entrada nova, e não decoração: a linha em amarelo aparece na tela
              desde o `venceu()` e não tinha legenda nenhuma. */}
          <span className="inline-flex items-center gap-1" style={{ color: "var(--bi-warn-ink)" }}>
            <Clock className="size-3" /> Prazo vencido (validade passou depois da leitura)
          </span>
        </div>
      )}
    </div>
  );
}
