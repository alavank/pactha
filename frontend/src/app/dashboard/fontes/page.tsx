"use client";

import React, { useEffect, useState } from "react";
import { Database, ExternalLink, CheckCircle2, AlertCircle, Settings, FileWarning, Clock, KeyRound } from "lucide-react";
import api from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";

interface Fonte {
  id: string;
  nome: string;
  categoria: string;
  url: string;
  tipo: string;
  status: string;
  descricao: string;
  frequencia?: string;
  ultima_ingestao?: string;
  ultimo_status?: string;
  horas_atras?: number | null;
  registros: number;
  credenciais_cadastradas?: number;
}

const STATUS_CFG: Record<string, { color: string; bg: string; border: string; icon: typeof CheckCircle2; label: string }> = {
  ativo:        { color: "text-green-700",  bg: "bg-green-50",  border: "border-green-300",  icon: CheckCircle2, label: "Ativo" },
  instavel:     { color: "text-orange-700", bg: "bg-orange-50", border: "border-orange-300", icon: AlertCircle,  label: "Instavel" },
  configuravel: { color: "text-blue-700",   bg: "bg-blue-50",   border: "border-blue-300",   icon: KeyRound,     label: "Sem credencial" },
  manual:       { color: "text-gray-700",   bg: "bg-gray-50",   border: "border-gray-300",   icon: FileWarning,  label: "Manual" },
};

function fmtAge(h?: number | null) {
  if (h == null) return "nunca";
  if (h < 1) return "< 1h atras";
  if (h < 24) return `${Math.floor(h)}h atras`;
  if (h < 24 * 7) return `${Math.floor(h / 24)}d atras`;
  return `${Math.floor(h / 24)}d atras`;
}

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

  const stats = {
    total: fontes.length,
    ativas: fontes.filter((f) => f.status === "ativo").length,
    instaveis: fontes.filter((f) => f.status === "instavel").length,
    sem_cred: fontes.filter((f) => f.status === "configuravel").length,
    registros: fontes.reduce((s, f) => s + (f.registros || 0), 0),
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
          <Database className="size-6 text-indigo-600" />
          Fontes de Dados
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Status real das integracoes com portais governamentais (atualizado em tempo real via ingestion_log)
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
          {/* Stats */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Total Fontes</p>
                <p className="text-2xl font-bold">{stats.total}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Ativas (&lt; 48h)</p>
                <p className="text-2xl font-bold text-green-600">{stats.ativas}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Instaveis</p>
                <p className="text-2xl font-bold text-orange-600">{stats.instaveis}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Sem Credencial</p>
                <p className="text-2xl font-bold text-blue-600">{stats.sem_cred}</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-6">
                <p className="text-xs text-muted-foreground">Registros Carregados</p>
                <p className="text-2xl font-bold">{stats.registros.toLocaleString("pt-BR")}</p>
              </CardContent>
            </Card>
          </div>

          {Object.entries(grouped).map(([categoria, items]) => (
            <div key={categoria} className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                {categoria}
              </h2>
              <div className="grid gap-3">
                {items.map((f) => {
                  const cfg = STATUS_CFG[f.status] || STATUS_CFG.manual;
                  const Icon = cfg.icon;
                  return (
                    <Card key={f.id} className={`${cfg.border} border-l-4 ${cfg.bg}`}>
                      <CardContent className="py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <Icon className={`size-4 ${cfg.color}`} />
                              <h3 className="font-semibold text-gray-900">{f.nome}</h3>
                              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cfg.bg} ${cfg.color} border ${cfg.border}`}>
                                {cfg.label}
                              </span>
                              {(f.credenciais_cadastradas ?? 0) > 0 && (
                                <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-0.5 text-xs font-medium text-purple-700 border border-purple-200">
                                  <KeyRound className="size-3" /> {f.credenciais_cadastradas} cred
                                </span>
                              )}
                            </div>
                            <p className="text-sm text-muted-foreground mb-2">{f.descricao}</p>
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
                              <span><strong>Tipo:</strong> {f.tipo}</span>
                              {f.frequencia && (
                                <span className="inline-flex items-center gap-1">
                                  <Clock className="size-3" /> {f.frequencia}
                                </span>
                              )}
                              {f.registros > 0 && (
                                <span className="font-mono">
                                  <strong>{f.registros.toLocaleString("pt-BR")}</strong> registros
                                </span>
                              )}
                              {f.ultima_ingestao ? (
                                <span>
                                  Ult. sync: {fmtAge(f.horas_atras)} (
                                  {new Date(f.ultima_ingestao).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}
                                  )
                                </span>
                              ) : (
                                <span className="text-orange-600">Ainda nao executou</span>
                              )}
                            </div>
                          </div>
                          <a
                            href={f.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:text-blue-800 flex-shrink-0"
                            title="Abrir portal externo"
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
