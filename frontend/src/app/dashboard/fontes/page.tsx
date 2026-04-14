"use client";

import React, { useEffect, useState } from "react";
import { Database, ExternalLink, CheckCircle2, AlertCircle, Settings, FileWarning } from "lucide-react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface Fonte {
  id: string;
  nome: string;
  categoria: string;
  url: string;
  tipo: string;
  status: string;
  descricao: string;
  ultima_ingestao?: string;
  ultimo_status?: string;
  registros: number;
}

const STATUS_CONFIG: Record<string, { color: string; bg: string; icon: typeof CheckCircle2; label: string }> = {
  ativo: { color: "text-green-700", bg: "bg-green-50 border-green-200", icon: CheckCircle2, label: "Ativo" },
  instavel: { color: "text-orange-700", bg: "bg-orange-50 border-orange-200", icon: AlertCircle, label: "Instavel" },
  configuravel: { color: "text-blue-700", bg: "bg-blue-50 border-blue-200", icon: Settings, label: "Requer Token" },
  manual: { color: "text-gray-700", bg: "bg-gray-50 border-gray-200", icon: FileWarning, label: "Manual" },
};

export default function FontesPage() {
  const [fontes, setFontes] = useState<Fonte[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<Fonte[]>("/fontes")
      .then((res) => setFontes(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const grouped = fontes.reduce((acc, f) => {
    if (!acc[f.categoria]) acc[f.categoria] = [];
    acc[f.categoria].push(f);
    return acc;
  }, {} as Record<string, Fonte[]>);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Database className="size-6 text-indigo-600" />
          Fontes de Dados
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Status das integracoes com portais governamentais
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      ) : (
        <>
          {/* Summary stats */}
          <div className="grid gap-4 sm:grid-cols-4">
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Total Fontes</p>
                <p className="text-2xl font-bold">{fontes.length}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Ativas</p>
                <p className="text-2xl font-bold text-green-600">
                  {fontes.filter((f) => f.status === "ativo").length}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Instaveis/Token</p>
                <p className="text-2xl font-bold text-orange-600">
                  {fontes.filter((f) => f.status === "instavel" || f.status === "configuravel").length}
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Total Registros</p>
                <p className="text-2xl font-bold">
                  {fontes.reduce((sum, f) => sum + (f.registros || 0), 0).toLocaleString("pt-BR")}
                </p>
              </CardContent>
            </Card>
          </div>

          {Object.entries(grouped).map(([categoria, items]) => (
            <div key={categoria} className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase">{categoria}</h2>
              <div className="grid gap-3">
                {items.map((f) => {
                  const cfg = STATUS_CONFIG[f.status] || STATUS_CONFIG.manual;
                  const Icon = cfg.icon;
                  return (
                    <Card key={f.id} className={`border-l-4 ${cfg.bg}`}>
                      <CardContent className="py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <Icon className={`size-4 ${cfg.color}`} />
                              <h3 className="font-semibold text-gray-900">{f.nome}</h3>
                              <span
                                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.color}`}
                              >
                                {cfg.label}
                              </span>
                            </div>
                            <p className="text-sm text-muted-foreground mb-2">{f.descricao}</p>
                            <div className="flex items-center gap-4 text-xs text-muted-foreground">
                              <span>Tipo: {f.tipo}</span>
                              {f.registros > 0 && (
                                <span className="font-mono">
                                  {f.registros.toLocaleString("pt-BR")} registros
                                </span>
                              )}
                              {f.ultima_ingestao && (
                                <span>
                                  Ultima sync: {new Date(f.ultima_ingestao).toLocaleString("pt-BR")}
                                </span>
                              )}
                            </div>
                          </div>
                          <a
                            href={f.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:text-blue-800 flex-shrink-0"
                          >
                            <ExternalLink className="size-5" />
                          </a>
                        </div>
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
