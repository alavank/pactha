"use client";

/* CONSOLIDADO — a carteira inteira lado a lado (18/09/2026).
 *
 * Pedido da assessoria Freitas: "onde o Reginaldo Lopes mandou $$ para nossos
 * clientes?". Toda tela operacional é de UM município; esta atravessa todos os
 * municípios que o usuário enxerga.
 *
 * ⚠️ NÃO É O "Consolidado (todos)" do seletor, que saiu em 05/08/2026 e continua
 * fora. A regra que torna esta área segura: TODO NÚMERO SAI QUEBRADO POR
 * MUNICÍPIO. O total de um parlamentar só aparece ao lado da lista de onde ele
 * veio — nunca sozinho, onde poderia ser lido como número de um cliente.
 *
 * ⚠️ NÃO USA `useMunicipio().municipioId`: o escopo é o do usuário, resolvido no
 * backend (`services/bi.resolve_scope`).
 */

import React, { useCallback, useEffect, useState } from "react";
import { Loader2, Search, Users } from "lucide-react";

import api from "@/lib/api";
import { formatCurrencyShort, formatInt } from "@/lib/bi-format";
import { anosOpcoes, atalhosAnos, resumoAnos } from "@/lib/periodo";
import { TituloTela } from "@/components/TituloTela";
import { MultiSelect } from "@/components/ui/multi-select";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { SeloCadastro, type Cadastro } from "@/components/emendas/AbaParlamentares";
import { FichaParlamentarCarteira } from "./FichaParlamentarCarteira";

interface Item {
  nome_normalizado: string;
  nome_display: string;
  total_lancamentos: number;
  valor_total: number;
  municipios: string[];
  qt_municipios: number;
  por_fonte: Record<string, number>;
  cadastro?: Cadastro | null;
}
interface Resp { municipios_na_carteira: number; items: Item[]; total: number }

const ROTULO_FONTE: Record<string, string> = {
  plano_acao: "Emenda Pix",
  voluntaria: "Voluntárias",
  emenda_federal: "Emendas federais",
  fns: "Saúde (FNS)",
  pac: "Novo PAC",
  emenda: "Emendas estaduais",
  sigcon: "SIGCON",
};

const ANOS = anosOpcoes();
const ATALHOS = atalhosAnos();

export default function ConsolidadoPage() {
  const [busca, setBusca] = useState("");
  const [anos, setAnos] = useState<string[]>([]);
  const [d, setD] = useState<Resp | null>(null);
  // Nasce `true`: a primeira carga dispara no efeito abaixo.
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<Item | null>(null);

  const carregar = useCallback(async (q: string, a: string[]) => {
    setCarregando(true);
    setErro(null);
    try {
      const qs = new URLSearchParams();
      if (q.trim()) qs.set("q", q.trim());
      a.forEach((x) => qs.append("anos", x));
      const r = await api.get<Resp>(`/consolidado/parlamentares?${qs.toString()}`);
      setD(r.data);
    } catch {
      setErro("Não foi possível carregar a carteira.");
    } finally {
      setCarregando(false);
    }
  }, []);

  // Primeira carga: a carteira inteira, todos os anos. O estado só muda nos
  // callbacks da promessa, e não no corpo do efeito.
  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/consolidado/parlamentares")
      .then((r) => { if (vivo) setD(r.data); })
      .catch(() => { if (vivo) setErro("Não foi possível carregar a carteira."); })
      .finally(() => { if (vivo) setCarregando(false); });
    return () => { vivo = false; };
  }, []);

  const itens = d?.items ?? [];
  const n = d?.municipios_na_carteira ?? 0;

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>Consolidado da carteira</TituloTela>
        <p className="text-sm text-muted-foreground">
          {n ? `Os ${n} municípios da sua carteira, lado a lado` : "Os municípios da sua carteira, lado a lado"}
          {" "}— todo valor aparece quebrado por município.
        </p>
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={Users} titulo="Parlamentares na carteira"
                   sub="quem destinou recurso aos seus municípios · clique para ver onde" />
        <form
          className="mb-3 flex flex-wrap items-end gap-3 px-1"
          onSubmit={(e) => { e.preventDefault(); void carregar(busca, anos); }}
        >
          <div className="min-w-[220px] flex-1">
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Parlamentar
            </label>
            <Input value={busca} onChange={(e) => setBusca(e.target.value)}
                   placeholder="Ex.: Reginaldo Lopes" />
          </div>
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>Anos</label>
            <MultiSelect className="min-w-[190px]" opcoes={ANOS} valor={anos}
                         onChange={(v) => { setAnos(v); void carregar(busca, v); }}
                         formatarResumo={resumoAnos} placeholder="Todos os anos"
                         rotuloTodos="Todos" ariaLabel="Anos" atalhos={ATALHOS} />
          </div>
          <Button type="submit" disabled={carregando}>
            {carregando ? <Loader2 className="mr-1 size-4 animate-spin" /> : <Search className="mr-1 size-4" />}
            Buscar
          </Button>
        </form>

        {erro ? (
          <Vazio>{erro}</Vazio>
        ) : !d && carregando ? (
          <div className="flex items-center gap-2 px-1 py-6 text-[12px]" style={{ color: "var(--bi-faint)" }}>
            <Loader2 className="size-4 animate-spin" /> carregando a carteira…
          </div>
        ) : itens.length === 0 ? (
          <Vazio>
            {busca.trim()
              ? `Nenhum parlamentar com "${busca.trim()}" destinou recurso aos municípios da carteira${anos.length ? " no período" : ""}.`
              : "Nenhum parlamentar com lançamento nos municípios da carteira."}
          </Vazio>
        ) : (
          <Lista>
            {itens.map((p) => (
              <ItemLinha
                key={p.nome_normalizado}
                onClick={() => setAberto(p)}
                titulo={
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span>{p.nome_display}</span>
                    <SeloCadastro c={p.cadastro} />
                  </span>
                }
                valor={formatCurrencyShort(p.valor_total)}
                meta={
                  <>
                    <Selo tom="acento">
                      {p.qt_municipios} de {n} município{n === 1 ? "" : "s"}
                    </Selo>
                    <span>{formatInt(p.total_lancamentos)} lançamento(s)</span>
                    {Object.entries(p.por_fonte)
                      .filter(([, q]) => q > 0)
                      .map(([f, q]) => (
                        <span key={f}>· {ROTULO_FONTE[f] ?? f} {q}</span>
                      ))}
                    <span className="truncate" title={p.municipios.join(", ")}>
                      · {p.municipios.slice(0, 4).join(", ")}
                      {p.municipios.length > 4 ? ` e mais ${p.municipios.length - 4}` : ""}
                    </span>
                  </>
                }
              />
            ))}
          </Lista>
        )}
        {itens.length > 0 && (
          <p className="mt-2 px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            {formatInt(itens.length)} parlamentar(es) · os valores somam emenda Pix, voluntárias,
            saúde (FNS), carteira de emendas federais (CGU), Novo PAC e emendas estaduais, pela
            mesma conta da tela Parlamentares de cada município.
          </p>
        )}
      </Bloco>

      {aberto && (
        <FichaParlamentarCarteira
          key={`${aberto.nome_normalizado}:${anos.join(",")}`}
          nome={aberto.nome_display}
          cadastro={aberto.cadastro}
          anos={anos}
          onFechar={() => setAberto(null)}
        />
      )}
    </div>
  );
}
