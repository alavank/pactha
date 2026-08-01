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
import React, { useEffect, useState } from "react";
import {
  ShieldCheck, ShieldAlert, CheckCircle2, AlertTriangle, AlertCircle, Ban, Loader2,
  Clock,
} from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";

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

function agrupar(itens: Item[]): Array<[string, Item[]]> {
  const m = new Map<string, Item[]>();
  for (const it of itens) {
    const g = it.grupo || "Exigências";
    if (!m.has(g)) m.set(g, []);
    m.get(g)!.push(it);
  }
  return [...m.entries()];
}

/** Banner de situação da esfera — mesmo formato nas duas colunas. */
function Situacao({
  regular, titulo, detalhe,
}: { regular: boolean; titulo: string; detalhe: string }) {
  return (
    <div className={`rounded-2xl border p-4 ${regular
      ? "border-success/30 bg-success/10"
      : "border-error/30 bg-error/10"}`}>
      <div className="flex items-center gap-3">
        {regular
          ? <CheckCircle2 className="size-8 text-success shrink-0" />
          : <ShieldAlert className="size-8 text-error shrink-0" />}
        <div className="min-w-0">
          <div className={`font-bold ${regular ? "text-success" : "text-error"}`}>{titulo}</div>
          <div className="text-sm text-base-content/70">{detalhe}</div>
        </div>
      </div>
    </div>
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
function AvisoCrc({ crcErro, crcEm }: { crcErro?: string | null; crcEm?: string | null }) {
  if (!crcErro) return null;
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 p-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-[2px] size-4 shrink-0 text-warning" />
        <div className="min-w-0 text-xs leading-relaxed">
          <div className="font-semibold text-base-content/80">
            Detalhamento indisponível — falha no portal do CAGEC
          </div>
          <div className="text-base-content/60">
            O certificado (CRC), que é de onde sai a lista de documentos com suas
            validades, não pôde ser emitido. O portal respondeu:{" "}
            <em>“{crcErro}”</em>
          </div>
          <div className="mt-1 text-base-content/60">
            {crcEm
              ? <>A lista abaixo é da última emissão que conseguimos ler,
                  de <strong>{fmtDate(crcEm)}</strong> — pode estar desatualizada.</>
              : <>Sem uma leitura anterior, abaixo aparece apenas o que a consulta
                  pública mostra: a situação do cadastro, sem os documentos.</>}
            {" "}A situação e o impedimento acima continuam atualizados.
          </div>
        </div>
      </div>
    </div>
  );
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
        <h3 className="text-sm font-bold text-base-content/80">
          Outros cadastros deste município ({outras.length})
        </h3>
        <p className="text-xs text-base-content/50">
          Cada entidade tem CRC próprio e trava <strong>apenas o seu</strong> convênio:
          a prefeitura estar regular não libera o convênio da saúde se o fundo estiver irregular.
        </p>
      </div>
      {outras.map((e) => {
        const ok = e.regular === true;
        const pend = e.pendencias || 0;
        return (
          <details
            key={e.cnpj || e.nome}
            className={`rounded-2xl border overflow-hidden ${ok
              ? "border-success/30 bg-success/5"
              : "border-error/30 bg-error/5"}`}
          >
            <summary className="flex cursor-pointer items-center gap-3 px-4 py-3">
              {ok
                ? <CheckCircle2 className="size-5 shrink-0 text-success" />
                : <ShieldAlert className="size-5 shrink-0 text-error" />}
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">{e.nome}</div>
                <div className="text-xs text-base-content/60">
                  {e.tipo || "entidade"}
                  {e.cnpj ? ` · CNPJ ${e.cnpj}` : ""}
                  {e.numero_cadastro ? ` · cadastro nº ${e.numero_cadastro}` : ""}
                </div>
              </div>
              <span className={`shrink-0 text-right text-xs font-medium ${ok ? "text-success" : "text-error"}`}>
                {e.situacao || (ok ? "Regular" : "Irregular")}
                <span className="block font-normal text-base-content/50">
                  {/* "sem pendência" só pode ser dito quando os documentos foram
                      lidos. Sem o CRC nós não sabemos se há pendência — e foi
                      exatamente assim que o Fundo Municipal de Saúde apareceu
                      como "Regular · sem pendência" com o detalhamento perdido. */}
                  {!e.detalhe_do_crc && e.crc_erro
                    ? "documentos não conferidos"
                    : pend ? `${pend} pendência(s)` : "sem pendência"}
                </span>
              </span>
            </summary>
            <div className="space-y-2 border-t border-base-300/60 bg-base-100 p-3">
              <AvisoCrc crcErro={e.crc_erro} crcEm={e.crc_em} />
              {/* Mesma ressalva do banner da prefeitura: `validade` é a próxima
                  obrigação a vencer, não a validade do certificado — o CRC não
                  tem uma. */}
              {e.validade && (
                <p className="text-xs text-base-content/60">
                  Próxima obrigação a vencer: <strong>{fmtDate(e.validade)}</strong>.
                </p>
              )}
              <Exigencias itens={e.itens || []} esfera="cagec" />
            </div>
          </details>
        );
      })}
    </div>
  );
}

/** Lista de exigências por bloco, no MESMO desenho do extrato oficial:
 *  código · Item Legal · **Situação** · **Validade**.
 *
 *  GRADE de largura fixa, não flex — pelo mesmo motivo do Painel: rótulo que
 *  quebra em duas linhas não pode empurrar as colunas da direita, e no CAGEC o
 *  código (de "CNPJ" a "AUTORIZ-ELETRONICA") deslocava o início de cada rótulo.
 *
 *  O CAGEC não tem coluna de código: aqueles identificadores são NOSSOS (o CRC
 *  não os imprime) e os informativos — os oito "Item 3.1.2 -…" — já vêm no
 *  próprio rótulo. */
function Exigencias({ itens, esfera = "cauc" }: { itens: Item[]; esfera?: "cauc" | "cagec" }) {
  if (!itens.length) {
    return (
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 text-center text-sm text-base-content/60">
        Nenhuma exigência detalhada nesta esfera.
      </div>
    );
  }
  const cols = esfera === "cauc"
    ? "grid-cols-[1.25rem_3rem_minmax(0,1fr)_7.5rem_6rem]"
    : "grid-cols-[1.25rem_minmax(0,1fr)_7.5rem_6rem]";
  return (
    <div className="space-y-3">
      {agrupar(itens).map(([grupo, lista]) => (
        <div key={grupo} className="rounded-2xl border border-base-300/60 bg-base-100 overflow-hidden shadow-theme-sm">
          <div className="px-4 py-2.5 bg-base-200/50 border-b border-base-300">
            {/* Título = o LITERAL do extrato ("III - Obrigações de
                Transparência"), para casar na conferência. A glosa embaixo,
                para quem não vive o documento. */}
            <div className="text-sm font-semibold text-base-content/70">{grupo}</div>
            {lista[0]?.grupo_glossa && (
              <div className="text-xs text-base-content/45">{lista[0].grupo_glossa}</div>
            )}
          </div>
          <div className={`grid ${cols} items-end gap-x-3 border-b border-base-300/60 bg-base-200/20 px-4 py-1.5 text-[10px] uppercase tracking-wide text-base-content/40`}>
            <span />
            {esfera === "cauc" && <span>Item</span>}
            <span>Item legal</span>
            <span>Situação</span>
            <span className="text-right">Validade</span>
          </div>
          <div className="divide-y divide-base-300/60">
            {lista.map((it) => (
              <div key={it.codigo}
                className={`grid ${cols} items-start gap-x-3 px-4 py-2 ${
                  it.tipo === "pendente" ? "bg-error/10" : ""}`}>
                {/* Símbolo por esfera, como nos dois documentos: o CAUC marca
                    Comprovado / A Comprovar / Desativado; o CAGEC, Vigente /
                    Vencido. O vermelho na linha inteira é o que faz o olho achar
                    o problema sem precisar ler. */}
                <span className="mt-[3px]">
                  {it.tipo === "pendente"
                    ? (esfera === "cagec"
                        ? <AlertTriangle className="size-4 text-error" />
                        : <AlertCircle className="size-4 text-error" />)
                    : it.tipo === "regular" ? <CheckCircle2 className="size-4 text-success" />
                    : <Ban className="size-4 text-base-content/30" />}
                </span>
                {esfera === "cauc" && (
                  <span className="font-mono text-xs leading-6 text-base-content/50">{it.codigo}</span>
                )}
                <div className="min-w-0">
                  <div className={`text-sm leading-6 ${it.tipo === "pendente"
                    ? "font-semibold text-error" : "text-base-content"}`}>
                    {it.label}
                  </div>
                  {/* A nota existe porque duas palavras do extrato enganam:
                      "Desativado" não é dispensa (é falha da ferramenta, para
                      TODOS os entes) e "A Comprovar" não acusa o município. */}
                  {it.nota && (
                    <div className="text-xs leading-snug text-base-content/45">{it.nota}</div>
                  )}
                </div>
                <span className={`text-xs font-medium leading-6 ${
                  it.tipo === "pendente" ? "text-error"
                  : it.tipo === "regular" ? "text-success"
                  : "text-base-content/40"}`}>
                  {it.status}
                </span>
                {/* Validade SEMPRE presente, como no extrato. "—" quando a fonte
                    não dá data: ausência de data é informação, não buraco. */}
                <span className={`whitespace-nowrap text-right font-mono text-xs leading-6 ${
                  it.tipo === "pendente" ? "text-error" : "text-base-content/50"}`}>
                  {it.validade || "—"}
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function RegularidadePage() {
  const { municipioId } = useMunicipio();
  const [cauc, setCauc] = useState<CaucResp | null>(null);
  const [cagec, setCagec] = useState<CagecResp | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Busca de dados: os setState aqui são o "carregando" da primeira pintura e
    // a limpeza ao trocar de município — sincronização com fonte externa, não
    // render em cascata (mesma convenção do resto do app).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (!municipioId) { setCauc(null); setCagec(null); setLoading(false); return; }
    setLoading(true);
    // As duas esferas em paralelo, com allSettled: uma falhar não pode apagar a
    // outra da tela — são fontes independentes (Tesouro e SIGCON).
    Promise.allSettled([
      api.get<CaucResp>("/cauc", { params: { municipio_id: municipioId } }),
      api.get<CagecResp>("/cagec", { params: { municipio_id: municipioId } }),
    ]).then(([a, b]) => {
      setCauc(a.status === "fulfilled" ? a.value.data : null);
      setCagec(b.status === "fulfilled" ? b.value.data : null);
    }).finally(() => setLoading(false));
  }, [municipioId]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <ShieldCheck className="size-6 text-primary" /> Regularidade de Documentação
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Exigências para assinar convênio nas duas esferas: <strong>CAUC</strong> (União,
          Tesouro Nacional) e <strong>CAGEC</strong> (Minas Gerais, SIGCON).
        </p>
      </div>

      {!municipioId && (
        <div className="rounded-2xl border border-base-300 bg-base-100 p-8 text-center text-base-content/60">
          Selecione um município para ver a situação.
        </div>
      )}

      {municipioId && loading && (
        <div className="flex justify-center py-16"><Loader2 className="size-8 animate-spin text-primary" /></div>
      )}

      {municipioId && !loading && (
        <div className="grid gap-5 xl:grid-cols-2">
          {/* ---------------- CAUC (federal) ---------------- */}
          <section className="space-y-3">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <h2 className="text-lg font-bold">CAUC — União</h2>
              <span className="text-xs text-base-content/50">
                Tesouro Nacional{cauc?.data_pesquisa ? ` · pesquisa de ${fmtDate(cauc.data_pesquisa)}` : ""}
              </span>
            </div>

            {!cauc?.tem_dados ? (
              <div className="rounded-2xl border border-base-300 bg-base-100 p-6 text-center text-sm text-base-content/60">
                Sem dados do CAUC para este município ainda. (A base é atualizada automaticamente.)
              </div>
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
                <p className="text-xs text-base-content/40">
                  Atualizado em {fmtDate(cauc.atualizado_em)}.
                </p>
              </>
            )}
          </section>

          {/* ---------------- CAGEC (estadual / MG) ---------------- */}
          <section className="space-y-3">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <h2 className="text-lg font-bold">CAGEC — Minas Gerais</h2>
              <span className="text-xs text-base-content/50">
                SIGCON-MG{cagec?.data_pesquisa ? ` · pesquisa de ${fmtDate(cagec.data_pesquisa)}` : ""}
              </span>
            </div>

            {!cagec?.tem_dados ? (
              /* Aguardando coleta — e dizendo POR QUÊ. Deixar em branco faria
                 parecer que não existe regularidade estadual a acompanhar;
                 pintar de verde seria pior, porque seria lido como "em dia". */
              <div className="rounded-2xl border border-warning/30 bg-warning/5 p-6">
                <div className="flex items-start gap-3">
                  <Clock className="size-6 shrink-0 text-warning" />
                  <div className="space-y-2">
                    <div className="font-semibold text-base-content">Aguardando coleta</div>
                    <p className="text-sm text-base-content/70">
                      {cagec?.motivo
                        || "O CAGEC deste município ainda não foi coletado."}
                    </p>
                    {/* A coleta do CAGEC NÃO usa credencial — a consulta do portal
                        é pública e basta o CNPJ. Mandar o gestor cadastrar senha
                        aqui seria trabalho inútil. O que falta, quando falta, é o
                        CNPJ do município nas bases. */}
                    <p className="text-xs text-base-content/50">
                      A consulta do CAGEC é pública e usa o CNPJ do município — não
                      depende de senha. Se o CNPJ ainda não foi identificado nas bases,
                      a coleta o encontra assim que houver emenda estadual ou registro
                      no PAC.
                    </p>
                  </div>
                </div>
              </div>
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
                <AvisoCrc crcErro={cagec.crc_erro} crcEm={cagec.crc_em} />
                <Exigencias itens={cagec.itens || []} esfera="cagec" />
                <OutrasEntidades entidades={cagec.entidades || []} />
                <p className="text-xs text-base-content/40">
                  Atualizado em {fmtDate(cagec.atualizado_em)}.
                  {cagec.crc_em && (
                    <> Documentos conferidos no CRC de {fmtDate(cagec.crc_em)}.</>
                  )}
                </p>
              </>
            )}
          </section>
        </div>
      )}

      {municipioId && !loading && (
        <p className="text-xs text-base-content/40">
          {/* A legenda espelha as PALAVRAS dos dois documentos, porque cada
              esfera usa o seu vocabulario e a tela existe para ser conferida
              contra o extrato. NUNCA escrever "nao exigido" para o Desativado:
              o texto oficial diz que a desativacao e da FERRAMENTA, "para todos
              os entes federativos". O caso que prova e o FGTS — item 1.3,
              desativado no CAUC, e ao mesmo tempo VENCIDO no CAGEC na coluna ao
              lado, travando convenio estadual. */}
          <span className="font-semibold">CAUC:</span>{" "}
          <span className="text-success">✔ Comprovado</span> ·
          <span className="text-error"> ⚠ A Comprovar (impeditivo)</span> ·
          <span className="text-base-content/40"> ⊘ Desativado (indisponível na fonte — não é dispensa)</span>
          {"  ·  "}
          <span className="font-semibold">CAGEC:</span>{" "}
          <span className="text-success">✔ Vigente</span> ·
          <span className="text-error"> ⚠ Vencido (impeditivo)</span>.
        </p>
      )}
    </div>
  );
}
