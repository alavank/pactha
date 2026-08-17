"use client";

/* INVESTSUS — o dinheiro federal de saúde que cai no Fundo Municipal.
 *
 * ⭐ POR QUE A TELA EXISTE ANTES DO COLETOR. O InvestSUS fecha a pasta da Saúde:
 * o FNS mostra a PROPOSTA, o SISMOB mostra a OBRA, e o InvestSUS mostra o
 * DINHEIRO — repasse por bloco e por competência. Sem ele, o gestor tinha três
 * quartos da história e nenhum lugar no PACTHA que dissesse isso.
 *
 * A fonte é fechada (login no autorizador do DATASUS) e a coleta ainda não
 * existe. Então a tela entrega o que não depende de login: o que cada bloco
 * financia, o que precisa ser conferido, e — o único dado vivo — se a credencial
 * deste município já está no Cofre. O AvisoCurado diz, com todas as letras, que
 * os valores ainda não são coletados.
 *
 * ⚠️ O bloco do município vem ANTES do conteúdo geral, como no FUNRIGS: é o que
 * fala DELE, e é o que tem ação associada (cadastrar a credencial).
 */

import React, { useCallback, useEffect, useState } from "react";
import { Banknote, ExternalLink, KeyRound, ListChecks, Loader2, ShieldAlert } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { AvisoCurado } from "@/components/rs/AvisoCurado";
import { Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";

interface BlocoFin { nome: string; tipo: string; o_que: string }
interface Conferir { item: string; detalhe: string }
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

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get("/investsus", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId]);
  useEffect(carregar, [carregar]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (!d?.tem_dados) return <Vazio>{d?.motivo || "Conteúdo indisponível."}</Vazio>;

  const m = d.municipio;
  const temCred = !!m?.credencial_cadastrada;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">{d.titulo}</h1>
        <p className="text-sm text-muted-foreground">{d.subtitulo}</p>
      </div>

      <AvisoCurado>{d.aviso}</AvisoCurado>

      {/* ⭐ O BLOQUEIO VEM PRIMEIRO, e não no rodapé: é a única coisa nesta tela
          que, feita, destrava todo o resto. Enterrá-lo embaixo do conteúdo
          explicativo seria descrever o problema para quem já desistiu de rolar. */}
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

/* Só dígitos no banco (é como o CHE e o CAGE esperam); a máscara é de leitura. */
function formatarCnpj(v: string): string {
  const d = (v || "").replace(/\D/g, "");
  if (d.length !== 14) return v;
  return `${d.slice(0, 2)}.${d.slice(2, 5)}.${d.slice(5, 8)}/${d.slice(8, 12)}-${d.slice(12)}`;
}
