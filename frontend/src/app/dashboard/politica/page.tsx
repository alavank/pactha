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
import { formatCurrency } from "@/lib/utils";
import type { EmendaPorDeputado, BenchmarkMunicipio } from "@/types";

interface TopDeputado {
  parlamentar_id: number;
  parlamentar_nome: string;
  partido?: string;
  votos?: number;
  total_emendas: number;
  total_valor: number;
}

export default function PoliticaPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [activeTab, setActiveTab] = useState("emendas");
  const [emendas, setEmendas] = useState<EmendaPorDeputado[]>([]);
  const [benchmark, setBenchmark] = useState<BenchmarkMunicipio[]>([]);
  const [topDeputados, setTopDeputados] = useState<TopDeputado[]>([]);
  const [loadingEmendas, setLoadingEmendas] = useState(true);
  const [loadingBenchmark, setLoadingBenchmark] = useState(true);
  const [loadingTop, setLoadingTop] = useState(true);

  useEffect(() => {
    if (!municipioId) return;
    setLoadingEmendas(true);
    api
      .get<EmendaPorDeputado[]>("/politica/emendas-por-deputado", {
        params: { municipio_id: municipioId },
      })
      .then((res) => setEmendas(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingEmendas(false));
  }, [municipioId]);

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
    api
      .get<TopDeputado[]>("/politica/top-deputados", {
        params: { municipio_id: municipioId },
      })
      .then((res) => setTopDeputados(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingTop(false));
  }, [municipioId]);

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
      <h1 className="text-2xl font-bold text-gray-900">Analise Politica</h1>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="emendas">Emendas por Deputado</TabsTrigger>
          <TabsTrigger value="benchmark">Benchmark</TabsTrigger>
          <TabsTrigger value="top">Top Deputados</TabsTrigger>
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

        {/* Tab 2: Benchmark */}
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

        {/* Tab 3: Top Deputados */}
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
                      <TableHead className="text-right">Votos</TableHead>
                      <TableHead className="text-right">Emendas</TableHead>
                      <TableHead className="text-right">Valor Total</TableHead>
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
                        <TableCell className="text-right font-mono">
                          {dep.votos?.toLocaleString("pt-BR") ?? "-"}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {dep.total_emendas}
                        </TableCell>
                        <TableCell className="text-right">
                          {formatCurrency(dep.total_valor)}
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
