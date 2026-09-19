"use client";

/* ONDE O PARLAMENTAR MANDOU DINHEIRO NA CARTEIRA — o modal do CONSOLIDADO.
 *
 * A resposta à pergunta da assessoria, município por município: quanto, por
 * qual fonte e em quais lançamentos. Os lançamentos são os mesmos da tela
 * Parlamentares de cada município (`detalhe_core` no backend), então a soma de
 * um município aqui é a soma que ele vê lá.
 *
 * ⚠️ O TOTAL SÓ APARECE AO LADO DA QUEBRA. A regra do CONSOLIDADO é que nenhum
 * número da carteira saia sozinho; o bloco "Por município" vem logo abaixo.
 */

import React, { useEffect, useMemo, useState } from "react";
import { Download, FileSpreadsheet, FileText, Loader2, MapPin } from "lucide-react";

import api from "@/lib/api";
import { formatCurrency, formatCurrencyShort, formatInt } from "@/lib/bi-format";
import {
  BOTAO_SEC, ESTILO_SEC, ItemLinha, Lista, Modal, ModalCorpo, ModalHead, Numero, Secao, Selo, Vazio,
} from "@/components/ui/superficies";
import { SeloCadastro, type Cadastro } from "@/components/emendas/AbaParlamentares";

interface PorMunicipio {
  municipio_id: number;
  municipio_nome: string;
  valor: number;
  lancamentos: number;
  por_fonte: Record<string, { valor: number; lancamentos: number }>;
}
interface Lancamento {
  fonte: string; municipio_id: number; municipio: string; numero: string;
  ano: number | null; objeto: string; situacao: string; valor: number;
}
interface Resp {
  nome: string;
  municipios_na_carteira: number;
  por_municipio: PorMunicipio[];
  lancamentos: Lancamento[];
  valor_total: number;
  total_lancamentos: number;
  fontes: { chave: string; rotulo: string }[];
}

export function FichaParlamentarCarteira({ nome, cadastro, anos, onFechar }: {
  nome: string; cadastro?: Cadastro | null; anos: string[]; onFechar: () => void;
}) {
  const [d, setD] = useState<Resp | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<number | null>(null);
  const [baixando, setBaixando] = useState<string | null>(null);

  const qsAnos = useMemo(() => {
    const qs = new URLSearchParams();
    anos.forEach((a) => qs.append("anos", a));
    return qs;
  }, [anos]);

  useEffect(() => {
    let vivo = true;
    api.get<Resp>(`/consolidado/parlamentares/${encodeURIComponent(nome)}?${qsAnos.toString()}`)
      .then((r) => { if (vivo) setD(r.data); })
      .catch((e) => {
        if (!vivo) return;
        setErro(e?.response?.status === 404
          ? "Nenhum lançamento deste parlamentar nos municípios da carteira."
          : "Não foi possível carregar o parlamentar.");
      });
    return () => { vivo = false; };
  }, [nome, qsAnos]);

  const rotulo = useMemo(() => Object.fromEntries((d?.fontes ?? []).map((f) => [f.chave, f.rotulo])), [d]);

  /* Baixa pelo mesmo caminho do PDF da tela Parlamentares: `fetch` com o token
     e os cookies, porque o axios não entrega o arquivo como blob navegável. */
  const baixar = async (formato: "xlsx" | "pdf") => {
    setBaixando(formato);
    try {
      const qs = new URLSearchParams(qsAnos);
      qs.set("formato", formato);
      const token = localStorage.getItem("pactha_token");
      const res = await fetch(
        `${api.defaults.baseURL}/consolidado/parlamentares/${encodeURIComponent(nome)}/exportar?${qs.toString()}`,
        { headers: token ? { Authorization: `Bearer ${token}` } : {}, credentials: "include" });
      if (!res.ok) throw new Error(String(res.status));
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `consolidado_${nome.replace(/[^\p{L}\p{N}]+/gu, "_")}.${formato}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch {
      setErro("Não foi possível gerar o arquivo. Se continuar, confira se você tem a permissão de exportar o Consolidado.");
    } finally {
      setBaixando(null);
    }
  };

  const n = d?.municipios_na_carteira ?? 0;
  const muns = d?.por_municipio ?? [];

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-4xl">
      <ModalHead
        titulo={<span className="flex flex-wrap items-center gap-2">{nome} <SeloCadastro c={cadastro} /></span>}
        sub={`Onde destinou recurso na carteira${anos.length ? ` · ${anos.join(", ")}` : " · todos os anos"}`}
        onFechar={onFechar}
        right={d && (
          <span className="flex items-center gap-1.5">
            <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                    onClick={() => baixar("xlsx")} disabled={!!baixando}>
              {baixando === "xlsx" ? <Loader2 className="size-3.5 animate-spin" /> : <FileSpreadsheet className="size-3.5" />}
              Planilha
            </button>
            <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                    onClick={() => baixar("pdf")} disabled={!!baixando}>
              {baixando === "pdf" ? <Loader2 className="size-3.5 animate-spin" /> : <FileText className="size-3.5" />}
              PDF
            </button>
          </span>
        )}
      />
      {!d && !erro && (
        <div className="flex items-center justify-center gap-2 py-16 text-[12px]" style={{ color: "var(--bi-faint)" }}>
          <Loader2 className="size-4 animate-spin" /> Carregando…
        </div>
      )}
      {erro && <ModalCorpo><Vazio>{erro}</Vazio></ModalCorpo>}
      {d && (
        <ModalCorpo className="flex flex-col gap-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <Numero icon={MapPin} rotulo="Municípios atendidos" tom="acento"
                    valor={`${muns.length} de ${n}`} sub="da sua carteira" />
            <Numero rotulo="Destinado a esses municípios" valor={formatCurrencyShort(d.valor_total)}
                    sub="a soma da lista abaixo" />
            <Numero rotulo="Lançamentos" valor={formatInt(d.total_lancamentos)}
                    sub="emendas, propostas e planos" />
          </div>

          <Secao icon={MapPin} titulo="Por município"
                 sub="do maior valor para o menor · clique para ver os lançamentos">
            {muns.length === 0 ? (
              <Vazio>Nenhum lançamento nos municípios da carteira.</Vazio>
            ) : (
              <Lista className="mt-1">
                {muns.map((m) => {
                  const lancs = (d.lancamentos ?? []).filter((l) => l.municipio_id === m.municipio_id);
                  const expandido = aberto === m.municipio_id;
                  return (
                    <ItemLinha
                      key={m.municipio_id}
                      onClick={() => setAberto(expandido ? null : m.municipio_id)}
                      expandido={expandido}
                      titulo={m.municipio_nome}
                      valor={formatCurrency(m.valor)}
                      meta={
                        <>
                          <span>{formatInt(m.lancamentos)} lançamento(s)</span>
                          {Object.entries(m.por_fonte).map(([f, v]) => (
                            <Selo key={f}>{rotulo[f] ?? f}: {formatCurrencyShort(v.valor)}</Selo>
                          ))}
                        </>
                      }
                    >
                      {expandido && (
                        <ul className="mt-2 flex flex-col gap-1 border-t pt-2" style={{ borderColor: "var(--bi-line)" }}>
                          {lancs.map((l, i) => (
                            <li key={i} className="flex items-baseline gap-3 text-[11px]">
                              <span className="min-w-0 flex-1">
                                <span className="font-medium">{l.objeto || "Sem objeto publicado"}</span>
                                <span className="block text-[10px]" style={{ color: "var(--bi-faint)" }}>
                                  {[l.fonte, l.numero, l.ano, l.situacao].filter(Boolean).join(" · ")}
                                </span>
                              </span>
                              <span className="bi-num shrink-0">{formatCurrency(l.valor)}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </ItemLinha>
                  );
                })}
              </Lista>
            )}
          </Secao>
          <p className="px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            <Download className="mr-1 inline size-3" />
            A planilha traz a tabela por município e todos os lançamentos. Os valores são os
            mesmos da tela Parlamentares de cada município.
          </p>
        </ModalCorpo>
      )}
    </Modal>
  );
}
