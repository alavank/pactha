"use client";

import React, { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatCurrency } from "@/lib/utils";
import type { EmendaPorDeputado, BenchmarkMunicipio } from "@/types";

interface TopDeputado {
  parlamentar_id: number;
  parlamentar_nome: string;
  partido?: string;
  votos?: number;
  cargo?: string;
  eleito?: boolean;
  total_emendas_valor: number;
}

interface CruzamentoItem {
  parlamentar_id: number;
  parlamentar_nome: string;
  partido?: string;
  esfera?: string;
  cargo?: string;
  votos: number;
  eleito: boolean;
  total_emendas_valor: number;
  total_emendas_count: number;
  valor_por_voto: number;
}

interface FuncaoItem {
  funcao: string;
  total_valor: number;
  count: number;
}

const PIE_COLORS = ["#4f46e5", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#84cc16"];

export default function PoliticaPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [activeTab, setActiveTab] = useState("emendas");
  const [emendas, setEmendas] = useState<EmendaPorDeputado[]>([]);
  const [benchmark, setBenchmark] = useState<BenchmarkMunicipio[]>([]);
  const [topDeputados, setTopDeputados] = useState<TopDeputado[]>([]);
  const [cruzamento, setCruzamento] = useState<CruzamentoItem[]>([]);
  const [funcoes, setFuncoes] = useState<FuncaoItem[]>([]);
  const [loadingEmendas, setLoadingEmendas] = useState(true);
  const [loadingBenchmark, setLoadingBenchmark] = useState(true);
  const [loadingTop, setLoadingTop] = useState(true);
  const [loadingCruz, setLoadingCruz] = useState(true);
  const [loadingFuncoes, setLoadingFuncoes] = useState(true);
  const [anoFilter, setAnoFilter] = useState("todos");

  const anosDisponiveis = Array.from({ length: 20 }, (_, i) => 2026 - i);

  useEffect(() => {
    if (!municipioId) return;
    setLoadingEmendas(true);
    const params: Record<string, string | number> = { municipio_id: municipioId };
    if (anoFilter !== "todos") params.ano = anoFilter;
    api
      .get<EmendaPorDeputado[]>("/politica/emendas-por-deputado", { params })
      .then((res) => setEmendas(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingEmendas(false));
  }, [municipioId, anoFilter]);

  useEffect(() => {
    setLoadingBenchmark(true);
    api
      .get<BenchmarkMunicipio[]>("/politica/benchmark-municipios")
      .then((res) => setBenchmark(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingBenchmark(false));
  }, []);

  useEffect(() => {
    if (!municipioId) return;
    setLoadingTop(true);
    const params: Record<string, string | number> = { municipio_id: municipioId };
    if (anoFilter !== "todos") params.ano = anoFilter;
    api
      .get<TopDeputado[]>("/politica/top-deputados", { params })
      .then((res) => setTopDeputados(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingTop(false));
  }, [municipioId, anoFilter]);

  useEffect(() => {
    if (!municipioId) return;
    setLoadingCruz(true);
    const params: Record<string, string | number> = { municipio_id: municipioId };
    if (anoFilter !== "todos") params.ano = anoFilter;
    api
      .get<CruzamentoItem[]>("/politica/cruzamento-eleitoral", { params })
      .then((res) => setCruzamento(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingCruz(false));
  }, [municipioId, anoFilter]);

  useEffect(() => {
    if (!municipioId) return;
    setLoadingFuncoes(true);
    const params: Record<string, string | number> = { municipio_id: municipioId };
    if (anoFilter !== "todos") params.ano = anoFilter;
    api
      .get<FuncaoItem[]>("/politica/emendas-por-funcao", { params })
      .then((res) => setFuncoes(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingFuncoes(false));
  }, [municipioId, anoFilter]);

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar analise politica.
      </div>
    );
  }

  const benchmarkChartData = benchmark.map((b) => ({
    name:
      b.municipio_nome.length > 15
        ? b.municipio_nome.slice(0, 15) + "..."
        : b.municipio_nome,
    convenios: b.total_convenios,
    valor: b.total_valor_convenios,
    emendas: b.total_emendas,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Analise Politica</h1>
        <Select value={anoFilter} onValueChange={(v) => setAnoFilter(v ?? "todos")}>
          <SelectTrigger className="w-32">
            <SelectValue placeholder="Ano" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="todos">Todos Anos</SelectItem>
            {anosDisponiveis.map((a) => (
              <SelectItem key={a} value={String(a)}>
                {a}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="emendas">Emendas por Deputado</TabsTrigger>
          <TabsTrigger value="funcoes">Por Area</TabsTrigger>
          <TabsTrigger value="benchmark">Benchmark</TabsTrigger>
          <TabsTrigger value="top">Top Deputados</TabsTrigger>
          <TabsTrigger value="cruzamento">Cruzamento Eleitoral</TabsTrigger>
        </TabsList>

        {/* Tab 1: Emendas por Deputado */}
        <TabsContent value="emendas" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Emendas Parlamentares por Deputado</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingEmendas ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-10 animate-pulse rounded bg-gray-100"
                    />
                  ))}
                </div>
              ) : emendas.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Nenhum dado encontrado.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Parlamentar</TableHead>
                      <TableHead>Partido</TableHead>
                      <TableHead className="text-right">Valor Total</TableHead>
                      <TableHead className="text-right">
                        Total Emendas
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {emendas.map((e) => (
                      <TableRow key={e.parlamentar_id}>
                        <TableCell className="font-medium">
                          {e.parlamentar_nome}
                        </TableCell>
                        <TableCell>
                          {e.partido ? (
                            <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                              {e.partido}
                            </span>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatCurrency(e.total_valor)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {e.total_emendas}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 2: Por Area/Funcao */}
        <TabsContent value="funcoes" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Emendas por Area / Funcao Governamental</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingFuncoes ? (
                <div className="h-64 animate-pulse rounded bg-gray-100" />
              ) : funcoes.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Nenhum dado encontrado.
                </p>
              ) : (
                <div className="grid gap-6 md:grid-cols-2">
                  <ResponsiveContainer width="100%" height={350}>
                    <PieChart>
                      <Pie
                        data={funcoes}
                        dataKey="total_valor"
                        nameKey="funcao"
                        cx="50%"
                        cy="50%"
                        outerRadius={120}
                        label={(props: object) => (props as { funcao?: string }).funcao || ""}
                      >
                        {funcoes.map((_, idx) => (
                          <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(v) => formatCurrency(Number(v))} />
                    </PieChart>
                  </ResponsiveContainer>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Area</TableHead>
                        <TableHead className="text-right">Qtd</TableHead>
                        <TableHead className="text-right">Valor Total</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {funcoes.map((f, idx) => (
                        <TableRow key={idx}>
                          <TableCell className="font-medium">{f.funcao}</TableCell>
                          <TableCell className="text-right">{f.count}</TableCell>
                          <TableCell className="text-right">
                            {formatCurrency(f.total_valor)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 3: Benchmark */}
        <TabsContent value="benchmark" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Benchmark entre Municipios</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingBenchmark ? (
                <div className="h-64 animate-pulse rounded bg-gray-100" />
              ) : benchmarkChartData.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Nenhum dado encontrado.
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={400}>
                  <BarChart data={benchmarkChartData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 11 }}
                      interval={0}
                      angle={-30}
                      textAnchor="end"
                      height={80}
                    />
                    <YAxis allowDecimals={false} />
                    <Tooltip
                      formatter={(value, name) => {
                        if (name === "valor") return formatCurrency(Number(value));
                        return value;
                      }}
                    />
                    <Bar
                      dataKey="convenios"
                      fill="#4f46e5"
                      name="Convenios"
                      radius={[4, 4, 0, 0]}
                    />
                    <Bar
                      dataKey="emendas"
                      fill="#06b6d4"
                      name="Emendas"
                      radius={[4, 4, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 4: Top Deputados */}
        <TabsContent value="top" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Top Deputados</CardTitle>
            </CardHeader>
            <CardContent>
              {loadingTop ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-10 animate-pulse rounded bg-gray-100"
                    />
                  ))}
                </div>
              ) : topDeputados.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Nenhum dado encontrado.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Parlamentar</TableHead>
                      <TableHead>Partido</TableHead>
                      <TableHead>Cargo</TableHead>
                      <TableHead className="text-right">Votos</TableHead>
                      <TableHead className="text-center">Eleito</TableHead>
                      <TableHead className="text-right">Valor em Emendas</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {topDeputados.map((dep) => (
                      <TableRow key={dep.parlamentar_id}>
                        <TableCell className="font-medium">
                          {dep.parlamentar_nome}
                        </TableCell>
                        <TableCell>
                          {dep.partido ? (
                            <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                              {dep.partido}
                            </span>
                          ) : (
                            "-"
                          )}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {dep.cargo || "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {dep.votos?.toLocaleString("pt-BR") ?? "-"}
                        </TableCell>
                        <TableCell className="text-center">
                          {dep.eleito ? (
                            <span className="text-green-600 font-bold text-xs">SIM</span>
                          ) : (
                            <span className="text-gray-400 text-xs">nao</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatCurrency(dep.total_emendas_valor)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 5: Cruzamento Eleitoral */}
        <TabsContent value="cruzamento" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle>Cruzamento: Votos Recebidos x Emendas Enviadas (2022)</CardTitle>
              <p className="text-xs text-muted-foreground mt-1">
                Quanto cada deputado eleito devolveu em emendas para cada voto recebido neste municipio
              </p>
            </CardHeader>
            <CardContent>
              {loadingCruz ? (
                <div className="space-y-2">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="h-10 animate-pulse rounded bg-gray-100" />
                  ))}
                </div>
              ) : cruzamento.length === 0 ? (
                <p className="py-8 text-center text-muted-foreground">
                  Nenhum dado eleitoral disponivel.
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Parlamentar</TableHead>
                      <TableHead>Partido</TableHead>
                      <TableHead>Cargo</TableHead>
                      <TableHead className="text-right">Votos</TableHead>
                      <TableHead className="text-center">Eleito</TableHead>
                      <TableHead className="text-right">Emendas (R$)</TableHead>
                      <TableHead className="text-right">R$ / Voto</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {cruzamento.map((c) => (
                      <TableRow key={c.parlamentar_id}>
                        <TableCell className="font-medium">{c.parlamentar_nome}</TableCell>
                        <TableCell>
                          {c.partido && (
                            <span className="inline-flex items-center rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">
                              {c.partido}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-xs">{c.cargo}</TableCell>
                        <TableCell className="text-right font-mono">
                          {c.votos.toLocaleString("pt-BR")}
                        </TableCell>
                        <TableCell className="text-center">
                          {c.eleito ? (
                            <span className="text-green-600 font-bold">SIM</span>
                          ) : (
                            <span className="text-gray-400">nao</span>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatCurrency(c.total_emendas_valor)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {c.valor_por_voto > 0 ? formatCurrency(c.valor_por_voto) : "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
