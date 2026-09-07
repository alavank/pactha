"use client";

/* REPASSES ESTADUAIS — a tela que o dado de Goiás pede.
 *
 * ⚠️ POR QUE NÃO É A TELA DE CONVÊNIOS. Minas e o Espírito Santo publicam o
 * INSTRUMENTO (número, vigência, situação, valor pactuado); Goiás publica o
 * PAGAMENTO (quem recebeu, quando, quanto, por qual órgão). Enfiar o dado de GO
 * na tela de convênio deixaria vigência, situação e número vazios — e o gestor
 * que conhece Minas concluiria que o sistema perdeu dado, não que o Estado
 * publica outra coisa.
 *
 * Então aqui não há coluna de vigência nem selo de situação: o eixo é a DATA DO
 * REPASSE e o VALOR, que é o que existe. O que o dado tem de especial — o
 * deputado autor, extraído da descrição — ganha destaque, porque é a pergunta
 * que a assessoria faz ("o que veio do fulano?").
 */

import React, { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { repassesDaUf } from "@/lib/estadual";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio } from "@/components/ui/superficies";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/multi-select";
import { Banknote, Search, Loader2, HandCoins } from "lucide-react";
import { formatCurrency, formatDate } from "@/lib/utils";
import { TituloTela } from "@/components/TituloTela";

interface Repasse {
  id: number;
  data_repasse: string | null;
  valor: number | null;
  credor: string | null;
  orgao: string | null;
  formalidade: string | null;
  elemento: string | null;
  sub_elemento: string | null;
  processo: string | null;
  processo_alt: string | null;
  fonte_recursos: string | null;
  descricao: string | null;
  emenda_numero: string | null;
  emenda_autor: string | null;
  ano: number | null;
  fonte: string | null;
}

interface Resp {
  items: Repasse[];
  total: number;
  page: number;
  pages: number;
  total_valor: number;
}

const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR = { color: "var(--bi-muted)" } as const;

export default function RepassesPage() {
  const { municipioId } = useMunicipio();
  const uf = useUfDoMunicipio();
  const info = repassesDaUf(uf);

  const [anosDisp, setAnosDisp] = useState<string[]>([]);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [busca, setBusca] = useState("");
  const [aplicada, setAplicada] = useState("");
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<number | null>(null);

  /* ⚠️ O CARIMBO existe para não mostrar dado do município ANTERIOR.
     Sem ele, a resposta de uma requisição disparada antes da troca chegaria
     depois e pintaria a tela com o município errado — e o `setState` síncrono
     que "limparia" antes é justamente o que o lint barra (renderização em
     cascata). Guardar de qual município é a resposta resolve os dois. */
  const [carimbo, setCarimbo] = useState<string>("");

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api.get<number[]>("/repasses/anos", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setAnosDisp((r.data || []).map(String)); })
      .catch(() => { if (vivo) setAnosDisp([]); });
    return () => { vivo = false; };
  }, [municipioId]);

  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anosDisp, setAnosSel);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    const meu = String(municipioId);
    setLoading(true);
    setErro(null);
    const params: Record<string, unknown> = { municipio_id: municipioId, per_page: 500 };
    if (anosSel.length) params.anos = anosSel.map(Number);
    if (aplicada.trim()) params.search = aplicada.trim();
    api.get<Resp>("/repasses", { params })
      .then((r) => { setData(r.data); setCarimbo(meu); })
      .catch((e) => {
        setErro((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
          || "Não foi possível carregar os repasses.");
        setData(null);
        setCarimbo(meu);
      })
      .finally(() => setLoading(false));
  }, [municipioId, anosSel, aplicada]);

  /* ⚠️ MICROTASK, e não `carregar()` direto. `carregar` começa com
     `setLoading(true)`, e setState SÍNCRONO dentro de um effect dispara
     renderização em cascata (o `react-hooks/set-state-in-effect` barra, com
     razão). Adiar um microtask tira o setState da fase síncrona sem atraso
     perceptível, e o `vivo` evita disparar depois que a tela saiu. */
  useEffect(() => {
    let vivo = true;
    Promise.resolve().then(() => { if (vivo) carregar(); });
    return () => { vivo = false; };
  }, [carregar]);

  if (!municipioId) return <Vazio>Selecione um município para ver os repasses.</Vazio>;

  /* Estado sem fonte de execução: a tela existe no menu só onde há fonte, mas
     navegação direta por URL chega aqui — e vazio sem explicação se lê como
     "não recebemos nada", que é outra frase. */
  if (uf && !info) {
    return (
      <div className="rounded-lg border p-6 text-sm"
           style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}>
        Esta tela mostra os <b>repasses estaduais</b> de estados que publicam a
        execução do recurso. O estado deste município ainda não é acompanhado
        por este sistema — os convênios estaduais dele, quando houver fonte,
        aparecem em <b>Estaduais → Convênios</b>.
      </div>
    );
  }

  // Só mostra o que for deste município (ver o carimbo acima).
  const doMunicipio = carimbo === String(municipioId);
  const itens = doMunicipio ? (data?.items ?? []) : [];

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>{info?.titulo || "Repasses Estaduais"}</TituloTela>
        <p className="text-sm text-muted-foreground">
          {info ? info.fonte : "Execução de recurso estadual"}
        </p>
      </div>

      {/* O QUE O DADO TEM: total e período. Não há "vigência a vencer" aqui —
          um pagamento já aconteceu; inventar prazo seria inventar dado. */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <Numero icon={HandCoins} rotulo="Total repassado" tom="acento"
                valor={formatCurrency(doMunicipio ? (data?.total_valor ?? 0) : 0)}
                sub={`${doMunicipio ? (data?.total ?? 0) : 0} repasse(s)`} />
        <Numero icon={Banknote} rotulo="Repasses no filtro"
                valor={String(doMunicipio ? (data?.total ?? 0) : 0)}
                sub={anosSel.length ? `anos: ${[...anosSel].sort().join(", ")}` : "todos os anos"} />
        <Numero icon={Search} rotulo="Com emenda identificada"
                valor={String(itens.filter((i) => i.emenda_autor).length)}
                sub="autor extraído da descrição" />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={Search} titulo="Filtrar"
                   sub="Ano, e busca por credor, órgão, processo ou nome do deputado" />
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[190px]">
            <span className={ROTULO} style={ROTULO_COR}>Ano</span>
            <MultiSelect opcoes={anosDisp} valor={anosSel} onChange={setAnosSel}
                         rotuloTodos="Todos os anos" ariaLabel="Filtrar por ano" />
          </div>
          <div className="min-w-[240px] flex-1">
            <label className={ROTULO} style={ROTULO_COR}>Buscar</label>
            <Input value={busca} onChange={(e) => setBusca(e.target.value)}
                   placeholder="Ex: FUNDO ESTADUAL DE SAUDE, ou o nome do deputado"
                   onKeyDown={(e) => { if (e.key === "Enter") setAplicada(busca); }} />
          </div>
          <Button size="sm" onClick={() => setAplicada(busca)} disabled={loading}>
            {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <Search className="size-4 mr-1" />}
            Buscar
          </Button>
          {(aplicada || anosSel.length > 0) && (
            <Button size="sm" variant="ghost"
                    onClick={() => { setBusca(""); setAplicada(""); setAnosSel([]); }}>
              Limpar
            </Button>
          )}
        </div>
      </Bloco>

      {erro && (
        <div className="rounded-lg border p-3 text-[13px]"
             style={{ borderColor: "var(--bi-crit)", color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {loading && !doMunicipio ? (
        <div className="flex justify-center py-14"><Loader2 className="size-6 animate-spin" /></div>
      ) : itens.length === 0 ? (
        <Vazio>
          {aplicada || anosSel.length
            ? "Nenhum repasse com esses filtros."
            : "Nenhum repasse estadual coletado para este município."}
        </Vazio>
      ) : (
        <Lista>
          {itens.map((r) => (
            <ItemLinha
              key={r.id}
              onClick={() => setAberto(aberto === r.id ? null : r.id)}
              expandido={aberto === r.id}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>{r.credor || "—"}</span>
                  {r.emenda_autor && (
                    <Selo title={`Emenda ${r.emenda_numero || ""} — ${r.emenda_autor}`}>
                      {r.emenda_autor}
                    </Selo>
                  )}
                </span>
              }
              valor={formatCurrency(r.valor ?? 0)}
              meta={
                <>
                  {r.data_repasse ? formatDate(r.data_repasse) : "sem data"}
                  {r.orgao ? ` · ${r.orgao}` : ""}
                </>
              }
            >
              {aberto === r.id && (
                <Campos
                  cols={3}
                  campos={[
                    { rotulo: "Formalidade", valor: r.formalidade || "—" },
                    { rotulo: "Elemento", valor: r.elemento || "—" },
                    { rotulo: "Sub elemento", valor: r.sub_elemento || "—" },
                    { rotulo: "Processo", valor: r.processo || "—" },
                    { rotulo: "Processo (nº)", valor: r.processo_alt || "—" },
                    { rotulo: "Fonte de recursos", valor: r.fonte_recursos || "—" },
                    ...(r.emenda_numero
                      ? [{ rotulo: "Emenda", valor: `nº ${r.emenda_numero}` }]
                      : []),
                    { rotulo: "Descrição", valor: r.descricao || "—", span: 3,
                      title: r.descricao || undefined },
                  ]}
                />
              )}
            </ItemLinha>
          ))}
        </Lista>
      )}
    </div>
  );
}
