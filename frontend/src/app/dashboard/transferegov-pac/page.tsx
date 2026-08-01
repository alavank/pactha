"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Landmark, Loader2, Search, Eraser } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";

interface PacItem {
  numero_proposta: string;
  programa: string | null;
  programa_codigo: string | null;
  proponente: string | null;
  cnpj: string | null;
  situacao: string | null;
  valor_repasse: number | null;
  valor_contrapartida: number | null;
  valor_total: number | null;
  emenda_parlamentar: string | null;
  qualificacao: string | null;
  objeto: string | null;
  justificativa: string | null;
}

/** Cor por situacao da proposta PAC. A tela era cinza inteira e o gestor tinha
 *  de LER cada linha para saber se a proposta andou ou morreu — a cor faz esse
 *  trabalho de longe. Comparacao por conteudo (sem acento) porque o portal varia
 *  a grafia ("Nao Habilitada" / "Não habilitada"). */
function corSituacao(s?: string | null): string {
  const u = (s || "")
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .toUpperCase();
  if (!u) return "bg-base-200 text-base-content/60 border-base-300";
  if (u.includes("NAO HABILITADA")) return "bg-error/15 text-error border-error/40";
  if (u.includes("HABILITADA")) return "bg-info/15 text-info border-info/40";
  if (u.includes("SELECIONADA")) return "bg-success/15 text-success border-success/40";
  if (u.includes("ANALISE")) return "bg-warning/15 text-warning border-warning/40";
  if (u.includes("CADASTRADA")) return "bg-base-200 text-base-content/70 border-base-300";
  return "bg-base-200 text-base-content/70 border-base-300";
}

/** Ano vem do sufixo do numero da proposta ("56000006303/2023"). */
function anoDaProposta(numero?: string | null): string {
  const m = /\/(\d{4})\s*$/.exec(numero || "");
  return m ? m[1] : "";
}

export default function TransfereGovPacPage() {
  const { municipioId } = useMunicipio();
  const [items, setItems] = useState<PacItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState("");
  const [q, setQ] = useState("");
  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [programasSel, setProgramasSel] = useState<string[]>([]);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [atualizado, setAtualizado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true); setErro("");
    try {
      const r = await api.get("/transferegov/pac", { params: { municipio_id: municipioId } });
      setItems(r.data.items || []);
      setAtualizado(r.data.atualizado || null);
    } catch {
      setErro("Erro ao carregar propostas PAC.");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [municipioId]);

  useEffect(() => { carregar(); }, [carregar]);

  // Opcoes dos filtros saem dos DADOS carregados: o portal muda a grafia e
  // inventa programa novo, entao uma lista fixa envelheceria em silencio.
  const situacaoOpcoes = useMemo(
    () => Array.from(new Set(items.map((i) => i.situacao).filter(Boolean) as string[])).sort(),
    [items]
  );
  const programaOpcoes = useMemo(
    () => Array.from(new Set(items.map((i) => i.programa).filter(Boolean) as string[])).sort(),
    [items]
  );
  const anoOpcoes = useMemo(
    () => Array.from(new Set(items.map((i) => anoDaProposta(i.numero_proposta)).filter(Boolean)))
      .sort((a, b) => Number(b) - Number(a)),
    [items]
  );

  const termo = q.trim().toLowerCase();
  const filtrados = useMemo(() => items.filter((i) => {
    if (termo && ![i.numero_proposta, i.programa, i.situacao, i.emenda_parlamentar, i.objeto]
      .filter(Boolean).some((v) => (v as string).toLowerCase().includes(termo))) return false;
    if (situacoesSel.length && !situacoesSel.includes(i.situacao || "")) return false;
    if (programasSel.length && !programasSel.includes(i.programa || "")) return false;
    if (anosSel.length && !anosSel.includes(anoDaProposta(i.numero_proposta))) return false;
    return true;
  }), [items, termo, situacoesSel, programasSel, anosSel]);

  const total = filtrados.reduce((s, i) => s + (i.valor_total || 0), 0);

  /** Contagem por situacao do conjunto FILTRADO — some junto com o filtro. */
  const porSituacao = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of filtrados) {
      const k = i.situacao || "Sem situação";
      m.set(k, (m.get(k) || 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [filtrados]);

  const temFiltro = !!termo || situacoesSel.length > 0 || programasSel.length > 0 || anosSel.length > 0;
  const limpar = () => { setQ(""); setSituacoesSel([]); setProgramasSel([]); setAnosSel([]); };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-bold text-base-content">
          <Landmark className="size-5 text-primary" />
          Transfere Gov — Seleção PAC (Novo PAC)
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Propostas do Novo PAC do município (TransfereGov / Acesso Livre).
          {atualizado ? ` · Atualizado: ${new Date(atualizado).toLocaleDateString("pt-BR")}` : ""}
        </p>
      </div>

      {/* Filtros: a tela so tinha uma busca por texto, e achar "as nao
          habilitadas de 2025" exigia ler tudo. Multi-selecao nos tres eixos que
          o gestor usa (situacao, programa, ano) — no cliente, porque o endpoint
          devolve as propostas do municipio de uma vez. */}
      <div className="rounded-lg border border-base-300 bg-base-100 p-3">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="mb-1 block text-xs text-base-content/70">Buscar</label>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-base-content/40" />
              <Input className="pl-8" placeholder="Nº, programa, emenda, objeto..."
                value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs text-base-content/70">
              Situação <span className="text-base-content/40">(uma, algumas ou todas)</span>
            </label>
            <MultiSelect
              opcoes={situacaoOpcoes}
              valor={situacoesSel}
              onChange={setSituacoesSel}
              placeholder="Todas as situações"
              rotuloTodos="Todas"
              ariaLabel="Situação da proposta"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-base-content/70">
              Anos <span className="text-base-content/40">(um, alguns ou o mandato)</span>
            </label>
            <MultiSelect
              opcoes={anoOpcoes}
              valor={anosSel}
              onChange={setAnosSel}
              atalhos={atalhosAnos()}
              formatarResumo={resumoAnos}
              placeholder="Todos os anos"
              rotuloTodos="Todos"
              ariaLabel="Ano da proposta"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-base-content/70">
              Programa <span className="text-base-content/40">(um ou vários)</span>
            </label>
            <MultiSelect
              opcoes={programaOpcoes}
              valor={programasSel}
              onChange={setProgramasSel}
              placeholder="Todos os programas"
              rotuloTodos="Todos"
              ariaLabel="Programa"
            />
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-base-300 pt-3">
          <span className="text-sm text-base-content/60">
            {filtrados.length} proposta(s) · <span className="font-medium text-success">{formatCurrency(total)}</span>
          </span>
          {/* Resumo por situacao: mesma cor da etiqueta da tabela, e clicavel
              para virar filtro — o numero que chamou a atencao ja leva ao recorte. */}
          {porSituacao.map(([sit, n]) => (
            <button
              key={sit}
              type="button"
              onClick={() => setSituacoesSel(situacoesSel.length === 1 && situacoesSel[0] === sit ? [] : [sit])}
              title={`Filtrar por "${sit}"`}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-opacity hover:opacity-80 ${corSituacao(sit)}`}
            >
              {sit} <span className="font-bold">{n}</span>
            </button>
          ))}
          {temFiltro && (
            <Button variant="outline" size="sm" className="ml-auto" onClick={limpar}>
              <Eraser className="size-4" /> Limpar
            </Button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-10"><Loader2 className="size-6 animate-spin text-info" /></div>
      ) : erro ? (
        <div className="text-sm text-error bg-error/15 border border-error rounded p-3">{erro}</div>
      ) : filtrados.length === 0 ? (
        <div className="text-sm text-base-content/60 italic py-8 text-center">
          Nenhuma proposta PAC para este município. (A coleta roda no cron; se acabou de subir, aguarde.)
        </div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-base-300 bg-base-100">
          <table className="w-full text-sm">
            <thead className="bg-base-200 text-left text-xs uppercase text-base-content/60">
              <tr>
                <th className="px-3 py-2">Nº Proposta</th>
                <th className="px-3 py-2">Programa</th>
                <th className="px-3 py-2">Situação</th>
                <th className="px-3 py-2 text-right">Valor Total</th>
                <th className="px-3 py-2">Emenda Parlamentar</th>
              </tr>
            </thead>
            <tbody>
              {filtrados.map((i) => (
                <tr key={i.numero_proposta} className="border-t border-base-200 even:bg-base-200/40 align-top">
                  <td className="px-3 py-2 font-mono whitespace-nowrap">{i.numero_proposta}</td>
                  <td className="px-3 py-2 max-w-[360px] whitespace-normal break-words leading-snug" title={i.programa || ""}>
                    {i.programa || "-"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {i.situacao ? (
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs font-medium ${corSituacao(i.situacao)}`}>
                        {i.situacao}
                      </span>
                    ) : "-"}
                  </td>
                  <td className="px-3 py-2 text-right whitespace-nowrap">{i.valor_total != null ? formatCurrency(i.valor_total) : "-"}</td>
                  <td className="px-3 py-2 text-xs">{i.emenda_parlamentar || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
