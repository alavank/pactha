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
  ShieldCheck, ShieldAlert, CheckCircle2, AlertTriangle, Loader2, MinusCircle,
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
  /** Só o CAGEC tem: cada obrigação do CRC vence numa data própria (dd/mm/aaaa). */
  validade?: string | null;
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
                  {pend ? `${pend} pendência(s)` : "sem pendência"}
                </span>
              </span>
            </summary>
            <div className="space-y-2 border-t border-base-300/60 bg-base-100 p-3">
              {/* Mesma ressalva do banner da prefeitura: `validade` é a próxima
                  obrigação a vencer, não a validade do certificado — o CRC não
                  tem uma. */}
              {e.validade && (
                <p className="text-xs text-base-content/60">
                  Próxima obrigação a vencer: <strong>{fmtDate(e.validade)}</strong>.
                </p>
              )}
              <Exigencias itens={e.itens || []} />
            </div>
          </details>
        );
      })}
    </div>
  );
}

/** Lista de exigências por bloco. Serve CAUC e CAGEC: o payload é o mesmo. */
function Exigencias({ itens }: { itens: Item[] }) {
  if (!itens.length) {
    return (
      <div className="rounded-2xl border border-base-300 bg-base-100 p-6 text-center text-sm text-base-content/60">
        Nenhuma exigência detalhada nesta esfera.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {agrupar(itens).map(([grupo, lista]) => (
        <div key={grupo} className="rounded-2xl border border-base-300/60 bg-base-100 overflow-hidden shadow-theme-sm">
          <div className="px-4 py-2.5 bg-base-200/50 border-b border-base-300 text-sm font-semibold text-base-content/70">
            {grupo}
          </div>
          <div className="divide-y divide-base-300/60">
            {lista.map((it) => (
              <div key={it.codigo} className="flex items-start gap-3 px-4 py-2.5">
                <span className="mt-0.5">
                  {it.tipo === "pendente" ? <AlertTriangle className="size-4 text-error" />
                    : it.tipo === "regular" ? <CheckCircle2 className="size-4 text-success" />
                    : <MinusCircle className="size-4 text-base-content/30" />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-base-content">
                    <span className="font-mono text-xs text-base-content/50 mr-2">{it.codigo}</span>
                    {it.label}
                  </div>
                </div>
                <span className={`shrink-0 text-xs font-medium whitespace-nowrap text-right ${
                  it.tipo === "pendente" ? "text-error"
                  : it.tipo === "regular" ? "text-success"
                  : "text-base-content/40"}`}>
                  {it.status}
                  {/* A data é o que torna a linha acionável: "Vencido" sozinho não
                      diz se foi ontem ou ano passado, e "Vigente" não diz quanto
                      tempo resta para renovar. */}
                  {it.validade && (
                    <span className="block font-normal text-base-content/50">
                      {it.tipo === "pendente" ? "venceu em " : "até "}{it.validade}
                    </span>
                  )}
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
                <Exigencias itens={cauc.itens || []} />
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
                <Exigencias itens={cagec.itens || []} />
                <OutrasEntidades entidades={cagec.entidades || []} />
                <p className="text-xs text-base-content/40">
                  Atualizado em {fmtDate(cagec.atualizado_em)}.
                </p>
              </>
            )}
          </section>
        </div>
      )}

      {municipioId && !loading && (
        <p className="text-xs text-base-content/40">
          Legenda: <span className="text-success">✔ regular até a data</span> ·
          <span className="text-error"> ⚠ pendência (impeditivo)</span> ·
          {/* NUNCA escrever "nao exigido" aqui. O simbolo marca os itens que o
              CAUC lista como "Desativado", e o texto oficial diz que a
              desativacao e da FERRAMENTA, "para todos os entes federativos" —
              nao e dispensa do municipio. O caso que prova: o FGTS e o item 1.3,
              desativado no CAUC, enquanto na coluna ao lado DESTA MESMA TELA o
              CRF do FGTS esta VENCIDO no CAGEC desde 29/07/2026 e e uma das 3
              causas da irregularidade estadual. "Nao exigido" mandava o gestor
              riscar da lista justamente o que trava o convenio. */}
          <span className="text-base-content/40"> ⊘ não avaliado nesta fonte — leia o status da linha; não é dispensa</span>.
        </p>
      )}
    </div>
  );
}
