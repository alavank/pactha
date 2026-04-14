"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ExternalLink, Star, StarOff, Calendar, Building } from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatCurrency, formatDate } from "@/lib/utils";
import type { Edital } from "@/types";

const AREA_COLORS: Record<string, string> = {
  saude: "bg-red-100 text-red-700",
  educacao: "bg-blue-100 text-blue-700",
  infraestrutura: "bg-yellow-100 text-yellow-700",
  assistencia_social: "bg-purple-100 text-purple-700",
  cultura: "bg-pink-100 text-pink-700",
  esporte: "bg-green-100 text-green-700",
  meio_ambiente: "bg-emerald-100 text-emerald-700",
  tecnologia: "bg-cyan-100 text-cyan-700",
};

function getAreaColor(area?: string | null): string {
  if (!area) return "bg-gray-100 text-gray-600";
  const key = area.toLowerCase().replace(/\s+/g, "_");
  return AREA_COLORS[key] || "bg-gray-100 text-gray-600";
}

function EditalCard({
  edital,
  onToggleAcompanhar,
  loadingId,
}: {
  edital: Edital;
  onToggleAcompanhar: (id: number, acompanhando: boolean) => void;
  loadingId: number | null;
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="line-clamp-2 text-sm font-semibold leading-snug">
            {edital.titulo}
          </CardTitle>
          {edital.status && (
            <Badge variant="secondary" className="shrink-0 text-xs">
              {edital.status}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <div className="space-y-1.5 text-sm">
          {edital.orgao && (
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Building className="size-3.5 shrink-0" />
              <span className="truncate">{edital.orgao}</span>
            </div>
          )}
          {edital.area && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${getAreaColor(
                edital.area
              )}`}
            >
              {edital.area}
            </span>
          )}
          {edital.dt_encerramento && (
            <div className="flex items-center gap-1.5 text-muted-foreground">
              <Calendar className="size-3.5 shrink-0" />
              <span>Encerramento: {formatDate(edital.dt_encerramento)}</span>
            </div>
          )}
          {edital.valor_total != null && (
            <p className="font-semibold text-indigo-700">
              {formatCurrency(edital.valor_total)}
            </p>
          )}
        </div>

        <div className="mt-auto flex items-center gap-2 pt-2">
          <Button
            variant={edital.acompanhando ? "secondary" : "default"}
            size="sm"
            className="flex-1"
            disabled={loadingId === edital.id}
            onClick={() =>
              onToggleAcompanhar(edital.id, !!edital.acompanhando)
            }
          >
            {edital.acompanhando ? (
              <>
                <StarOff className="mr-1 size-3.5" />
                Deixar de acompanhar
              </>
            ) : (
              <>
                <Star className="mr-1 size-3.5" />
                Acompanhar
              </>
            )}
          </Button>
          {edital.url && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => window.open(edital.url!, "_blank")}
            >
              <ExternalLink className="size-3.5" />
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function EditaisPage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [editais, setEditais] = useState<Edital[]>([]);
  const [acompanhados, setAcompanhados] = useState<Edital[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingAcomp, setLoadingAcomp] = useState(true);
  const [toggleLoadingId, setToggleLoadingId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState("abertos");

  const fetchEditais = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api
      .get<Edital[]>("/editais", { params: { municipio_id: municipioId } })
      .then((res) => setEditais(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [municipioId]);

  const fetchAcompanhados = useCallback(() => {
    if (!municipioId) return;
    setLoadingAcomp(true);
    api
      .get<Edital[]>("/editais/acompanhados", {
        params: { municipio_id: municipioId },
      })
      .then((res) => setAcompanhados(Array.isArray(res.data) ? res.data : []))
      .catch(() => {})
      .finally(() => setLoadingAcomp(false));
  }, [municipioId]);

  useEffect(() => {
    fetchEditais();
    fetchAcompanhados();
  }, [fetchEditais, fetchAcompanhados]);

  const handleToggleAcompanhar = useCallback(
    async (id: number, currentlyAcompanhando: boolean) => {
      setToggleLoadingId(id);
      try {
        if (currentlyAcompanhando) {
          await api.delete(`/editais/${id}/acompanhar`);
          toast.success("Edital removido do acompanhamento.");
        } else {
          await api.post(`/editais/${id}/acompanhar`);
          toast.success("Edital adicionado ao acompanhamento!");
        }
        fetchEditais();
        fetchAcompanhados();
      } catch {
        toast.error("Erro ao atualizar acompanhamento.");
      } finally {
        setToggleLoadingId(null);
      }
    },
    [fetchEditais, fetchAcompanhados]
  );

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar editais.
      </div>
    );
  }

  const SkeletonGrid = () => (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-48 animate-pulse rounded-xl bg-gray-100" />
      ))}
    </div>
  );

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Radar de Editais</h1>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="abertos">Editais Abertos</TabsTrigger>
          <TabsTrigger value="acompanhados">
            Acompanhados ({acompanhados.length})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="abertos" className="mt-4">
          {loading ? (
            <SkeletonGrid />
          ) : editais.length === 0 ? (
            <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
              Nenhum edital aberto encontrado.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {editais.map((edital) => (
                <EditalCard
                  key={edital.id}
                  edital={edital}
                  onToggleAcompanhar={handleToggleAcompanhar}
                  loadingId={toggleLoadingId}
                />
              ))}
            </div>
          )}
        </TabsContent>

        <TabsContent value="acompanhados" className="mt-4">
          {loadingAcomp ? (
            <SkeletonGrid />
          ) : acompanhados.length === 0 ? (
            <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
              Nenhum edital acompanhado.
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {acompanhados.map((edital) => (
                <EditalCard
                  key={edital.id}
                  edital={{ ...edital, acompanhando: true }}
                  onToggleAcompanhar={handleToggleAcompanhar}
                  loadingId={toggleLoadingId}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
