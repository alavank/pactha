"use client";

import React, { useEffect, useState, useMemo, useCallback } from "react";
import { Loader2, ExternalLink, BarChart3, Wallet } from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import api from "@/lib/api";
import MultiSelect from "@/components/MultiSelect";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { formatCurrency, formatDate } from "@/lib/utils";

interface Dimensao {
  dimensao: string;
  score_4: number; score_3: number; score_2: number; score_1: number; score_na: number;
  total: number;
  atualizado_em?: string;
}
interface Liberacao {
  programa: string;
  programa_full: string;
  dt_pgto?: string;
  ob?: string;
  valor?: number | null;
  parcela?: string;
  descricao?: string;
  banco?: string;
  agencia?: string;
  conta?: string;
  ano?: number;
  atualizado_em?: string;
}
interface Resumo {
  por_programa: Array<{ programa: string; qtde: number; total: number }>;
  por_ano: Array<{ ano: number; qtde: number; total: number }>;
  total_geral: number;
}

const PORTAL = "https://simec.mec.gov.br/cte/relatoriopublico/principal.php";

function programColor(p: string): string {
  const s = p.toUpperCase();
  if (s.includes("PNATE")) return "bg-primary/10 text-primary";
  if (s.includes("QUOTA")) return "bg-success/15 text-success";
  if (s.includes("PNAE") || s.includes("ALIMENT")) return "bg-warning/15 text-warning";
  if (s.includes("PDDE")) return "bg-info/15 text-info";
  return "bg-base-200 text-base-content/70";
}

export default function SimecPage() {
  const { municipioId } = useMunicipio();

  const [tab, setTab] = useState<"dim" | "lib">("dim");
  const [dimensoes, setDimensoes] = useState<Dimensao[]>([]);
  const [liberacoes, setLiberacoes] = useState<Liberacao[]>([]);
  const [resumo, setResumo] = useState<Resumo | null>(null);
  const [loading, setLoading] = useState(false);

  // Filtros das liberacoes
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [progsSel, setProgsSel] = useState<string[]>([]);
  const [search, setSearch] = useState("");

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const [d, l, r] = await Promise.all([
        api.get<{ items: Dimensao[] }>("/simec/dimensoes", { params: { municipio_id: municipioId } }),
        api.get<{ items: Liberacao[] }>("/simec/liberacoes", { params: { municipio_id: municipioId } }),
        api.get<Resumo>("/simec/resumo", { params: { municipio_id: municipioId } }),
      ]);
      setDimensoes(d.data.items);
      setLiberacoes(l.data.items);
      setResumo(r.data);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId, buscar]);

  const anoOptions = useMemo(
    () => Array.from(new Set(liberacoes.map((l) => l.ano).filter(Boolean))).sort((a, b) => (b! - a!)).map(String),
    [liberacoes]
  );
  const progOptions = useMemo(
    () => Array.from(new Set(liberacoes.map((l) => l.programa).filter(Boolean))).sort(),
    [liberacoes]
  );

  const displayLib = useMemo(() => {
    let arr = liberacoes;
    if (anosSel.length) arr = arr.filter((l) => l.ano && anosSel.includes(String(l.ano)));
    if (progsSel.length) arr = arr.filter((l) => progsSel.includes(l.programa));
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      arr = arr.filter((l) =>
        (l.descricao || "").toLowerCase().includes(q) ||
        (l.ob || "").toLowerCase().includes(q) ||
        (l.programa_full || "").toLowerCase().includes(q)
      );
    }
    return arr;
  }, [liberacoes, anosSel, progsSel, search]);

  const displayTotal = useMemo(
    () => displayLib.reduce((s, l) => s + (l.valor || 0), 0),
    [displayLib]
  );

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold text-primary">SIMEC - PAR (MEC)</h1>
          <p className="text-sm text-base-content/60">
            Plano de Acoes Articuladas + Liberacoes de recursos federais (PNAE, PNATE, QUOTA, PDDE, etc.)
          </p>
        </div>
        <a href={PORTAL} target="_blank" rel="noreferrer noopener"
           className="text-xs text-primary hover:underline inline-flex items-center gap-1">
          <ExternalLink className="size-3" /> Portal oficial SIMEC
        </a>
      </div>

      {/* Resumo no topo */}
      {resumo && !loading && (
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border bg-base-100 p-3">
            <div className="text-[11px] uppercase tracking-wider text-base-content/60">Total liberado</div>
            <div className="text-xl font-bold text-success mt-1">{formatCurrency(resumo.total_geral)}</div>
            <div className="text-[11px] text-base-content/60 mt-1">{liberacoes.length} pagamentos</div>
          </div>
          <div className="rounded-lg border bg-base-100 p-3">
            <div className="text-[11px] uppercase tracking-wider text-base-content/60">Programas</div>
            <div className="text-xl font-bold text-primary mt-1">{resumo.por_programa.length}</div>
            <div className="text-[11px] text-base-content/60 mt-1 truncate">
              {resumo.por_programa.slice(0, 4).map((p) => p.programa).join(", ")}
            </div>
          </div>
          <div className="rounded-lg border bg-base-100 p-3">
            <div className="text-[11px] uppercase tracking-wider text-base-content/60">Anos cobertos</div>
            <div className="text-xl font-bold text-info mt-1">{resumo.por_ano.length}</div>
            <div className="text-[11px] text-base-content/60 mt-1">
              {resumo.por_ano.length ? `${Math.min(...resumo.por_ano.map((a) => a.ano))} - ${Math.max(...resumo.por_ano.map((a) => a.ano))}` : "-"}
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b">
        <button
          onClick={() => setTab("dim")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            tab === "dim" ? "border-primary text-primary" : "border-transparent text-base-content/60 hover:text-base-content/70"
          }`}
        >
          <BarChart3 className="inline size-4 mr-1" />
          Sintese do PAR ({dimensoes.length} dimensoes)
        </button>
        <button
          onClick={() => setTab("lib")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            tab === "lib" ? "border-primary text-primary" : "border-transparent text-base-content/60 hover:text-base-content/70"
          }`}
        >
          <Wallet className="inline size-4 mr-1" />
          Liberacoes de Recursos ({liberacoes.length})
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center"><Loader2 className="size-6 animate-spin mx-auto text-primary" /></div>
      ) : tab === "dim" ? (
        <div className="bg-base-100 border rounded overflow-hidden">
          {dimensoes.length === 0 ? (
            <div className="p-12 text-center text-base-content/60">Nenhuma dimensao encontrada.</div>
          ) : (
            <Table className="text-sm">
              <TableHeader>
                <TableRow className="[&>th]:py-2 [&>th]:px-3 [&>th]:font-semibold bg-primary/10 [&>th]:text-xs">
                  <TableHead>Dimensao do PAR</TableHead>
                  <TableHead className="text-center w-[80px]">Total</TableHead>
                  <TableHead className="text-center w-[70px] bg-success/15">Score 4</TableHead>
                  <TableHead className="text-center w-[70px] bg-success/15">Score 3</TableHead>
                  <TableHead className="text-center w-[70px] bg-warning/15">Score 2</TableHead>
                  <TableHead className="text-center w-[70px] bg-error/15">Score 1</TableHead>
                  <TableHead className="text-center w-[60px]">N/A</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {dimensoes.map((d, i) => (
                  <TableRow key={i} className="[&>td]:py-2 [&>td]:px-3 [&>td]:text-sm">
                    <TableCell className="font-medium">{d.dimensao}</TableCell>
                    <TableCell className="text-center font-mono">{d.total}</TableCell>
                    <TableCell className="text-center font-mono bg-success/15 font-semibold">{d.score_4}</TableCell>
                    <TableCell className="text-center font-mono bg-success/15">{d.score_3}</TableCell>
                    <TableCell className="text-center font-mono bg-warning/15">{d.score_2}</TableCell>
                    <TableCell className="text-center font-mono bg-error/15">{d.score_1}</TableCell>
                    <TableCell className="text-center font-mono text-base-content/40">{d.score_na}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          <div className="px-3 py-2 bg-base-200 border-t text-[11px] text-base-content/60">
            Escala: 4 = situacao boa / 3 = adequada / 2 = a melhorar / 1 = critica. Fonte: SIMEC publico (PAR diagnostico).
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Filtros liberacoes */}
          <div className="bg-base-100 border rounded p-3 grid gap-3 md:grid-cols-4">
            <MultiSelect options={anoOptions} selected={anosSel} onChange={setAnosSel} placeholder="Todos os anos" width="w-full" />
            <MultiSelect options={progOptions} selected={progsSel} onChange={setProgsSel} placeholder="Todos os programas" width="w-full" />
            <Input placeholder="Buscar descricao/OB" value={search} onChange={(e) => setSearch(e.target.value)} />
            <Button variant="outline" onClick={() => { setAnosSel([]); setProgsSel([]); setSearch(""); }}>Limpar</Button>
          </div>

          <div className="bg-base-100 border rounded overflow-hidden">
            <div className="px-3 py-2 bg-base-200 border-b text-sm flex items-center justify-between">
              <span><strong>{displayLib.length}</strong> liberacoes</span>
              <span className="font-mono font-semibold text-success">{formatCurrency(displayTotal)}</span>
            </div>
            {displayLib.length === 0 ? (
              <div className="p-12 text-center text-base-content/60">Nenhuma liberacao encontrada.</div>
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:font-semibold [&>th]:text-[11px] bg-primary/10">
                    <TableHead className="w-[90px]">Data Pgto</TableHead>
                    <TableHead className="w-[70px]">Programa</TableHead>
                    <TableHead>Descricao</TableHead>
                    <TableHead className="w-[80px]">OB</TableHead>
                    <TableHead className="w-[110px] text-right">Valor</TableHead>
                    <TableHead className="w-[110px]">Banco / Ag.</TableHead>
                    <TableHead className="w-[100px]">Conta</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {displayLib.map((l, i) => (
                    <TableRow key={i} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px]">
                      <TableCell className="whitespace-nowrap">{formatDate(l.dt_pgto)}</TableCell>
                      <TableCell>
                        <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium ${programColor(l.programa)}`}>
                          {l.programa}
                        </span>
                      </TableCell>
                      <TableCell className="truncate" title={l.descricao || l.programa_full}>
                        {l.descricao || l.programa_full || "-"}
                      </TableCell>
                      <TableCell className="font-mono">{l.ob || "-"}</TableCell>
                      <TableCell className="text-right font-mono font-semibold text-success">{formatCurrency(l.valor || 0)}</TableCell>
                      <TableCell className="text-[10px] truncate" title={l.banco || ""}>
                        {l.banco || "-"} {l.agencia ? `/ ${l.agencia}` : ""}
                      </TableCell>
                      <TableCell className="font-mono text-[10px]">{l.conta || "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
