"use client";

import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

type Programa = {
  id: number; nome: string; orgao: string; objetivo?: string;
  situacao: string; inicio?: string; fim?: string;
  valor_min?: number; valor_max?: number;
};

const fmtBR = (v?: number) => v ? v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "-";

export default function OportunidadesPage() {
  const [items, setItems] = useState<Programa[]>([]);
  const [loading, setLoading] = useState(true);
  const [filtro, setFiltro] = useState("");

  const fetchData = (orgao = "") => {
    setLoading(true);
    api.get<{ total: number; items: Programa[] }>("/oportunidades", {
      params: { orgao: orgao || undefined, aberto_apenas: true, limit: 100 }
    })
      .then(r => setItems(r.data.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="space-y-4 p-4">
      <h1 className="text-2xl font-bold">Oportunidades — Programas Federais Abertos</h1>
      <p className="text-sm text-muted-foreground">
        Programas em vigor para captação de recursos (TransfereGov).
      </p>

      <div className="flex gap-2">
        <Input placeholder="Filtrar por órgão (ex: saúde, educação)" value={filtro}
               onChange={e => setFiltro(e.target.value)}
               onKeyDown={e => e.key === "Enter" && fetchData(filtro)} />
        <Button onClick={() => fetchData(filtro)}>Filtrar</Button>
      </div>

      {loading ? <p>Carregando…</p> : items.length === 0 ? (
        <p className="text-muted-foreground">Nenhum programa aberto. Rode <code>backend/ingestion/oportunidades.py</code>.</p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {items.map(p => (
            <Card key={p.id}>
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2">
                  {p.nome}
                  <Badge variant="secondary" className="text-xs">{p.situacao}</Badge>
                </CardTitle>
                <div className="text-xs text-muted-foreground">{p.orgao}</div>
              </CardHeader>
              <CardContent className="text-sm space-y-1">
                {p.objetivo && <p className="text-xs text-muted-foreground line-clamp-3">{p.objetivo}</p>}
                <div><strong>Inscrições:</strong> {p.inicio || "-"} a <span className={p.fim ? "text-red-600 font-medium" : ""}>{p.fim || "indeterminado"}</span></div>
                {(p.valor_min || p.valor_max) && (
                  <div><strong>Valor:</strong> {fmtBR(p.valor_min)} — {fmtBR(p.valor_max)}</div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
