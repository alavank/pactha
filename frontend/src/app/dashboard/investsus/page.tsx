"use client";

/* INVESTSUS — o dinheiro federal de saúde que cai no Fundo Municipal.
 *
 * ⭐ O InvestSUS fecha a pasta da Saúde: o FNS mostra a PROPOSTA, o SISMOB mostra
 * a OBRA, e este mostra o DINHEIRO — quanto o Fundo Municipal recebeu, por bloco
 * e por grupo de financiamento. Sem ele, o gestor tinha três quartos da história.
 *
 * ⭐ DE 17/08 A 02/09/2026 ESTA TELA NÃO TINHA VALOR NENHUM. Nasceu curada (o que
 * cada bloco financia, o que conferir) porque o InvestSUS exige login e o acesso
 * estava barrado no MFA. Em 02/09 o consolidado por bloco entrou, vindo do
 * ConsultaFNS — público, sem login. Medido em Monte Sião/2026: R$ 8,55 milhões.
 *
 * ⚠️ A ORDEM DA TELA MUDOU JUNTO, e a ordem é o argumento. O dinheiro vem
 * primeiro; o pedido de cadastro do MFA, que antes abria a página, desceu para
 * depois dele — continuar abrindo com "o que falta para os valores aparecerem"
 * embaixo de valores que já aparecem faria a tela parecer quebrada.
 *
 * ⚠️ `faf: null` NÃO é "o município não recebeu": é "ainda não coletamos aqui".
 * A tela precisa dizer qual dos dois, senão acusa o município de não receber
 * dinheiro de saúde por causa de uma coleta nossa que não rodou.
 */

import React, { useCallback, useEffect, useState } from "react";
import {
  Banknote, ChevronDown, ChevronRight, ExternalLink, KeyRound, ListChecks,
  Loader2, ShieldAlert, Wallet,
} from "lucide-react";

import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { AvisoCurado } from "@/components/rs/AvisoCurado";
import {
  Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";

interface BlocoFin { nome: string; tipo: string; o_que: string }
interface Conferir { item: string; detalhe: string }
interface Grupo { codigo: number; nome: string | null; total: number; desconto: number; liquido: number }
interface BlocoFaf extends Grupo { grupos: Grupo[] }
interface Faf {
  ano: number;
  anos: number[];
  blocos: BlocoFaf[];
  total: number;
  desconto: number;
  liquido: number;
  atualizado_em: string | null;
}
interface Resp {
  tem_dados: boolean;
  motivo?: string;
  aviso?: string;
  titulo?: string;
  subtitulo?: string;
  resumo?: string;
  blocos?: BlocoFin[];
  conferir?: Conferir[];
  links?: [string, string][];
  faf?: Faf | null;
  coleta_automatica?: boolean;
  bloqueio?: {
    titulo: string;
    texto: string;
    passos: string[];
    porque_nao_contornamos: string;
  };
  municipio?: {
    nome: string;
    cnpj: string | null;
    credencial_cadastrada: boolean;
    credencial_escopo: "municipio" | "instancia" | null;
  };
}

export default function InvestSusPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [ano, setAno] = useState<number | null>(null);
  const [aberto, setAberto] = useState<number | null>(null);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get("/investsus", { params: { municipio_id: municipioId, ...(ano ? { ano } : {}) } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId, ano]);
  useEffect(carregar, [carregar]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;

  const m = d.municipio;
  const temCred = !!m?.credencial_cadastrada;
  const faf = d.faf ?? null;
  const quando = faf?.atualizado_em ? formatarQuando(faf.atualizado_em) : "";

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">{d.titulo}</h1>
        <p className="text-sm text-muted-foreground">{d.subtitulo}</p>
      </div>

      <AvisoCurado>{d.aviso}</AvisoCurado>

      {/* ⭐ O DINHEIRO ABRE A TELA. É o que o gestor veio ver, e desde 02/09/2026
          é a única parte desta página que fala do município DELE em reais. */}
      {faf ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-sm font-semibold text-base-content">
                Fundo a fundo recebido em {faf.ano}
              </h2>
              <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                ConsultaFNS · consolidado por bloco e grupo de financiamento
                {quando && ` · coletado em ${quando}`}
              </p>
            </div>
            {/* Um ano só não é escolha — o seletor sumir é o certo. */}
            {faf.anos.length > 1 && (
              <div className="flex flex-wrap gap-1">
                {faf.anos.map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => { setAno(a); setAberto(null); }}
                    className="rounded px-2 py-1 text-[11px] tabular-nums transition-colors"
                    style={a === faf.ano
                      ? { background: "var(--bi-accent)", color: "var(--bi-accent-ink)", fontWeight: 600 }
                      : { color: "var(--bi-muted)" }}
                  >
                    {a}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <Numero icon={Wallet} rotulo="Total repassado no ano" tom="acento"
                    valor={formatCurrency(faf.total)}
                    sub={`${faf.blocos.length} bloco(s) de financiamento`} />
            {/* ⚠️ O DESCONTO É GLOSA E TEM QUE APARECER. Mostrar só o líquido
                esconderia dinheiro que o município perdeu — exatamente o número
                que ele precisa questionar. Fica cinza quando é zero: destacar
                zero em vermelho treinaria o olho a ignorar o cartão. */}
            <Numero icon={Banknote} rotulo="Descontado (glosa)"
                    tom={faf.desconto > 0 ? "atencao" : "neutro"}
                    valor={formatCurrency(faf.desconto)}
                    sub={faf.desconto > 0
                      ? "valor retido pelo Ministério antes do crédito — vale conferir a origem"
                      : "nenhum desconto registrado no ano"} />
            <Numero icon={Wallet} rotulo="Creditado no Fundo Municipal" tom="ok"
                    valor={formatCurrency(faf.liquido)}
                    sub="o que efetivamente entrou na conta" />
          </div>

          <Bloco className="p-3">
            <BlocoHead icon={Banknote} titulo="Por bloco de financiamento"
                       sub="clique para abrir os grupos de cada bloco" />
            <Lista>
              {/* ⚠️ Fragment, e não <div>, em volta do par bloco+grupos: `Lista`
                  é um <ul> e `ItemLinha` é um <li>. Um <div> aqui seria filho
                  direto de <ul> — HTML inválido, e leitor de tela perde a
                  contagem de itens da lista. */}
              {faf.blocos.map((b) => {
                const abre = aberto === b.codigo;
                const temGrupos = b.grupos.length > 0;
                return (
                  <React.Fragment key={b.codigo}>
                    <ItemLinha
                      onClick={temGrupos ? () => setAberto(abre ? null : b.codigo) : undefined}
                      expandido={temGrupos ? abre : undefined}
                      titulo={
                        <span className="flex flex-wrap items-center gap-x-2">
                          {temGrupos && (abre
                            ? <ChevronDown className="size-3.5 shrink-0" />
                            : <ChevronRight className="size-3.5 shrink-0" />)}
                          <span>{b.nome || `Bloco ${b.codigo}`}</span>
                          {b.desconto > 0 && (
                            <Selo tom="atencao">glosa {formatCurrency(b.desconto)}</Selo>
                          )}
                        </span>
                      }
                      valor={formatCurrency(b.total)}
                      meta={temGrupos
                        ? `${b.grupos.length} grupo(s) de financiamento`
                        : "o portal não detalhou os grupos deste bloco"}
                    />
                    {abre && b.grupos.map((g) => (
                      <ItemLinha
                        key={`${b.codigo}-${g.codigo}`}
                        className="ml-5"
                        titulo={g.nome || `Grupo ${g.codigo}`}
                        valor={formatCurrency(g.total)}
                        meta={g.desconto > 0
                          ? `glosa de ${formatCurrency(g.desconto)} · creditado ${formatCurrency(g.liquido)}`
                          : undefined}
                      />
                    ))}
                  </React.Fragment>
                );
              })}
            </Lista>
          </Bloco>
        </div>
      ) : (
        /* ⚠️ ESTA MENSAGEM DIZ DE QUEM É A PENDÊNCIA. "Sem repasses" faria a tela
           afirmar que o município não recebeu dinheiro de saúde — que é falso, e
           grave. O que houve é que a coleta ainda não rodou neste ambiente. */
        <Bloco className="p-3">
          <BlocoHead icon={Wallet} titulo="Fundo a fundo ainda não coletado aqui"
                     sub="pendência nossa, não do município" />
          <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            A coleta do consolidado do ConsultaFNS ainda não rodou para este
            município. Isto <strong>não</strong> significa que ele não recebeu
            repasses — significa que ainda não buscamos. Assim que a primeira
            rodada passar, os valores por bloco aparecem aqui.
          </p>
        </Bloco>
      )}

      {/* O bloqueio do MFA desceu para DEPOIS do dinheiro em 02/09/2026: ele
          abria a tela quando não havia valor nenhum para mostrar. Continua na
          página porque é o que destrava o detalhe parcela a parcela. */}
      {d.bloqueio && (
        <Bloco className="p-3">
          <BlocoHead icon={ShieldAlert} titulo={d.bloqueio.titulo}
                     sub="pendência no cadastro de acesso do município" />
          <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            {d.bloqueio.texto}
          </p>
          <ol className="mt-2 space-y-1.5 px-1">
            {d.bloqueio.passos.map((p, i) => (
              <li key={i} className="flex gap-2 text-[11px] leading-relaxed"
                  style={{ color: "var(--bi-muted)" }}>
                <span className="shrink-0 font-semibold tabular-nums"
                      style={{ color: "var(--bi-accent-ink)" }}>{i + 1}.</span>
                <span>{p}</span>
              </li>
            ))}
          </ol>
          <p className="mt-2 px-1 text-[10px] italic leading-relaxed"
             style={{ color: "var(--bi-faint)" }}>
            {d.bloqueio.porque_nao_contornamos}
          </p>
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={KeyRound} titulo="Situação deste município"
                   sub="o que já está pronto para quando a coleta entrar" />
        <Lista>
          <ItemLinha
            titulo={
              <span className="flex flex-wrap items-center gap-x-2">
                <span>Credencial do InvestSUS no Cofre</span>
                <Selo tom={temCred ? "ok" : "atencao"}>
                  {temCred
                    ? (m!.credencial_escopo === "municipio" ? "cadastrada" : "cadastrada (escopo geral)")
                    : "não cadastrada"}
                </Selo>
              </span>
            }
            meta={
              temCred
                ? "A credencial está guardada e cifrada. Assim que o coletor entrar, este município já é coletado sem nenhuma ação a mais."
                : "Sem credencial, o coletor futuro não vai conseguir consultar este município. Cadastre em Configurações → Cofre de Senhas, sistema InvestSUS."
            }
          />
          <ItemLinha
            titulo={
              <span className="flex flex-wrap items-center gap-x-2">
                <span>CNPJ da prefeitura</span>
                <Selo tom={m?.cnpj ? undefined : "atencao"}>
                  {m?.cnpj ? formatarCnpj(m.cnpj) : "não cadastrado"}
                </Selo>
              </span>
            }
            meta={
              m?.cnpj
                ? "É por ele que a consulta do InvestSUS é feita."
                : "A consulta do InvestSUS é por CNPJ. Sem ele cadastrado no município, não há como consultar."
            }
          />
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Banknote} titulo="Blocos de financiamento" sub={d.resumo} />
        <Lista>
          {(d.blocos || []).map((b) => (
            <ItemLinha
              key={b.nome}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2">
                  <span>{b.nome}</span>
                  <Selo tom={b.tipo === "Investimento" ? "acento" : undefined}>{b.tipo}</Selo>
                </span>
              }
              meta={b.o_que}
            />
          ))}
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={ListChecks} titulo="O que conferir"
                   sub="achados recorrentes que o portal não avisa sozinho" />
        <Lista>
          {(d.conferir || []).map((c) => (
            <ItemLinha key={c.item} titulo={c.item} meta={c.detalhe} />
          ))}
        </Lista>
        <div className="mt-2 flex flex-wrap gap-3 px-1">
          {(d.links || []).map(([rotulo, url]) => (
            <a key={url} href={url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 text-[11px] underline"
               style={{ color: "var(--bi-accent-ink)" }}>
              {rotulo} <ExternalLink className="size-3" />
            </a>
          ))}
        </div>
      </Bloco>
    </div>
  );
}

/* Quando a coleta passou. Vem ISO com fuso do Postgres; a tela mostra data e
 * hora curtas. Se vier ilegível, some — carimbo errado é pior que carimbo
 * nenhum numa tela que se propõe a dizer o quanto o dado está fresco. */
function formatarQuando(iso: string): string {
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  return dt.toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

/* Só dígitos no banco (é como o CHE e o CAGE esperam); a máscara é de leitura. */
function formatarCnpj(v: string): string {
  const d = (v || "").replace(/\D/g, "");
  if (d.length !== 14) return v;
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}
