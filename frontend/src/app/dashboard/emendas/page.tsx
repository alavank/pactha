"use client";

import React, { useEffect, useState, useCallback, useMemo } from "react";
import { ChevronLeft, ChevronRight, Search as SearchIcon, ChevronDown, ChevronUp } from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatCurrency } from "@/lib/utils";

/** Os tres tipos que o SIGCON usa na indicacao. Ficam aqui como lista fixa
 *  porque o backend compara com ILIKE por item — acento e caixa nao importam,
 *  e a lista nao muda sem mudanca normativa. */
const TIPOS_INDICACAO = [
  "Transferência Especial",
  "Aplicação Direta",
  "Convênio",
];

interface Emenda {
  id: number;
  municipio_id: number;
  nr_indicacao?: string;
  nome_responsavel?: string;
  tipo_indicacao?: string;
  uo_codigo?: string;
  uo_sigla?: string;
  cnpj_beneficiario?: string;
  beneficiario?: string;
  grupo_despesa?: string;
  tipo_atendimento?: string;
  valor_indicacao?: number;
  status_indicacao?: string;
  ano?: number;
}

const PER_PAGE = 100; // todos por ano

function statusColor(s?: string): string {
  if (!s) return "bg-base-200 text-base-content/70";
  const u = s.toUpperCase();
  if (u.includes("APROVAD")) return "bg-success/15 text-success border-success";
  if (u.includes("REJEIT") || u.includes("CANCEL")) return "bg-error/15 text-error border-error";
  if (u.includes("ANALIS") || u.includes("AGUARD")) return "bg-warning/15 text-warning border-warning";
  return "bg-primary/10 text-primary border-primary";
}

function siglaTipo(t?: string): string {
  if (!t) return "-";
  const u = t.toUpperCase();
  if (u.includes("TRANSFER") && u.includes("ESPECIAL")) return "TE";
  if (u.includes("APLICA")) return "AD";
  if (u.includes("CONV")) return "CV";
  return t.slice(0, 4).toUpperCase();
}

export default function EmendasEstaduaisPage() {
  const { municipioId } = useMunicipio();

  const [items, setItems] = useState<Emenda[]>([]);
  const [loading, setLoading] = useState(true);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  const [responsavel, setResponsavel] = useState("");
  const [tiposSel, setTiposSel] = useState<string[]>([]);
  const [stats, setStats] = useState<{ total: number; valor_total: number; responsaveis: number; aprovadas: number } | null>(null);
  const [anos, setAnos] = useState<number[]>([]);
  const [collapsedYears, setCollapsedYears] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (!municipioId) return;
    api.get<number[]>("/emendas-estaduais/anos", { params: { municipio_id: municipioId } })
      .then((r) => setAnos(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, [municipioId]);

  const fetchData = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    // `string[]` no tipo porque anos e tipos agora vao como lista repetida na
    // querystring (?anos=2025&anos=2024), que e o formato que o FastAPI espera.
    const params: Record<string, string | number | string[]> = {
      municipio_id: municipioId,
      page: 1,
      per_page: 500, // todos pra agrupar por ano
    };
    if (anosSel.length) params.anos = anosSel;
    if (responsavel) params.responsavel = responsavel;
    if (tiposSel.length) params.tipos = tiposSel;
    api.get<{ items: Emenda[]; total: number }>("/emendas-estaduais", { params })
      .then((r) => setItems(r.data.items || []))
      .catch(() => {})
      .finally(() => setLoading(false));

    // MESMO recorte da tabela. Mandar so quando ha um ano ("=== 1") fazia os
    // cards do topo somarem a base inteira enquanto a lista abaixo mostrava o
    // mandato — a tela se contradizendo sozinha.
    api.get("/emendas-estaduais/stats", { params: { municipio_id: municipioId, ...(anosSel.length ? { anos: anosSel } : {}) } })
      .then((r) => setStats(r.data as never))
      .catch(() => {});
  }, [municipioId, anosSel, responsavel, tiposSel]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Agrupa por ano (DESC)
  const grouped = useMemo(() => {
    const map = new Map<number, Emenda[]>();
    items.forEach((e) => {
      const y = e.ano ?? 0;
      if (!map.has(y)) map.set(y, []);
      map.get(y)!.push(e);
    });
    return Array.from(map.entries()).sort((a, b) => b[0] - a[0]);
  }, [items]);

  const toggleYear = (y: number) => {
    setCollapsedYears((prev) => {
      const next = new Set(prev);
      if (next.has(y)) next.delete(y);
      else next.add(y);
      return next;
    });
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um municipio.</div>;
  }

  const exportPdf = () => {
    const token = localStorage.getItem("pactha_token");
    const url = `${api.defaults.baseURL}/export-pdf/emendas?municipio_id=${municipioId}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => r.blob())
      .then((blob) => {
        const u = URL.createObjectURL(blob);
        window.open(u, "_blank");
      });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-base-content">Emendas Parlamentares Estaduais</h1>
        <Button onClick={exportPdf} size="sm" variant="outline" title="Exportar para PDF">
          📄 PDF
        </Button>
      </div>

      {stats && (
        <div className="grid grid-cols-4 gap-3">
          <StatCard label="Total Indicações" value={stats.total.toLocaleString("pt-BR")} />
          <StatCard label="Valor Total Indicado" value={formatCurrency(stats.valor_total)} />
          <StatCard label="Parlamentares" value={stats.responsaveis.toString()} />
          <StatCard label="Aprovadas" value={stats.aprovadas.toLocaleString("pt-BR")} />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <MultiSelect
          opcoes={anos.map(String)}
          valor={anosSel}
          onChange={setAnosSel}
          atalhos={atalhosAnos()}
          formatarResumo={resumoAnos}
          placeholder="Todos os anos"
          rotuloTodos="Todos os anos"
          ariaLabel="Anos"
          className="w-44"
        />

        <MultiSelect
          opcoes={TIPOS_INDICACAO}
          valor={tiposSel}
          onChange={setTiposSel}
          placeholder="Todos os tipos"
          rotuloTodos="Todos os tipos"
          ariaLabel="Tipo de indicação"
          className="w-60"
        />

        <div className="relative flex-1 min-w-[200px]">
          <SearchIcon className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Buscar por responsável (parlamentar)..."
            value={responsavel}
            onChange={(e) => setResponsavel(e.target.value)}
            className="pl-9"
          />
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, i) => <div key={i} className="h-12 animate-pulse rounded bg-base-200" />)}
        </div>
      ) : grouped.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhuma emenda encontrada. Rode o scraper SIGCON-MG para popular.
        </div>
      ) : (
        <div className="space-y-3">
          {grouped.map(([y, list]) => {
            const isCollapsed = collapsedYears.has(y);
            const totalAno = list.reduce((s, e) => s + (e.valor_indicacao ?? 0), 0);
            return (
              <div key={y} className="rounded-lg border bg-base-100 overflow-hidden">
                <button
                  onClick={() => toggleYear(y)}
                  className="w-full flex items-center justify-between px-3 py-2 bg-base-200 hover:bg-base-300 border-b"
                >
                  <div className="flex items-center gap-2">
                    {isCollapsed ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
                    <span className="font-bold text-sm">{y || "Sem ano"}</span>
                    <span className="text-xs text-muted-foreground">({list.length} indicações)</span>
                  </div>
                  <span className="text-xs font-mono font-semibold">{formatCurrency(totalAno)}</span>
                </button>
                {!isCollapsed && (
                  <Table className="text-xs table-fixed w-full">
                    <TableHeader>
                      <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[10px] [&>th]:font-semibold [&>th]:whitespace-normal [&>th]:align-bottom [&>th]:leading-tight">
                        <TableHead className="w-[74px]">Nº da Indicação</TableHead>
                        <TableHead className="w-[168px]">Responsável</TableHead>
                        <TableHead className="w-[48px]">Tipo</TableHead>
                        <TableHead className="w-[58px]">Unidade Orçamentária</TableHead>
                        <TableHead className="w-[76px]">Sigla</TableHead>
                        <TableHead className="w-[124px]">CNPJ do Beneficiário</TableHead>
                        <TableHead className="min-w-0">Beneficiário</TableHead>
                        <TableHead className="w-[118px]">Grupo de Despesa</TableHead>
                        <TableHead className="min-w-0">Tipo de Atendimento</TableHead>
                        <TableHead className="w-[100px] text-right">Valor</TableHead>
                        <TableHead className="w-[96px]">Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {list.map((em) => (
                        <TableRow key={em.id} className="[&>td]:py-1.5 [&>td]:px-2 [&>td]:text-[11px] [&>td]:align-top [&>td]:leading-snug hover:bg-base-200">
                          <TableCell className="font-mono text-[10px]" title={`Nº Indicação: ${em.nr_indicacao || "-"}`}>{em.nr_indicacao || "-"}</TableCell>
                          {/* O nome do parlamentar e a coisa que identifica a
                              emenda — cortar aqui e cortar justamente o dado. */}
                          <TableCell className="whitespace-normal break-words font-medium">{em.nome_responsavel || "-"}</TableCell>
                          <TableCell title={em.tipo_indicacao || ""}>
                            <span className="inline-flex items-center rounded bg-info/15 border border-info px-1 py-0.5 text-[9px] font-mono text-info">{siglaTipo(em.tipo_indicacao)}</span>
                          </TableCell>
                          <TableCell className="font-mono text-[10px]" title={`UO ${em.uo_codigo || "-"}`}>{em.uo_codigo || "-"}</TableCell>
                          <TableCell className="font-mono text-[10px] whitespace-normal break-all">{em.uo_sigla || "-"}</TableCell>
                          <TableCell className="font-mono text-[10px] whitespace-normal break-all">{em.cnpj_beneficiario || "-"}</TableCell>
                          <TableCell className="whitespace-normal break-words">{em.beneficiario || "-"}</TableCell>
                          <TableCell className="whitespace-normal break-words text-[10px]">{em.grupo_despesa || "-"}</TableCell>
                          <TableCell className="whitespace-normal break-words text-[10px]">{em.tipo_atendimento || "-"}</TableCell>
                          <TableCell className="text-right font-mono whitespace-nowrap" title={`Valor: ${formatCurrency(em.valor_indicacao)}`}>{formatCurrency(em.valor_indicacao)}</TableCell>
                          <TableCell title={em.status_indicacao || ""}>
                            <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-medium border whitespace-normal break-words text-left ${statusColor(em.status_indicacao)}`}>{em.status_indicacao || "-"}</span>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-base-100 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-bold mt-1">{value}</div>
    </div>
  );
}
