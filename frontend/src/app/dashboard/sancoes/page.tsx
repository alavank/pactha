"use client";

import React, { useState } from "react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

type Sancao = {
  id?: number; cpf_cnpj?: string; razao_social?: string; razao?: string;
  tipo_sancao?: string; tipo?: string; dt_inicio?: string; dt_fim?: string; orgao?: string;
};

export default function SancoesPage() {
  const [items, setItems] = useState<Sancao[]>([]);
  const [loading, setLoading] = useState(false);
  const [cnpj, setCnpj] = useState("");
  const [razao, setRazao] = useState("");
  const [verdict, setVerdict] = useState<null | { temSancao: boolean; cnpj: string }>(null);

  const buscar = () => {
    setLoading(true); setVerdict(null);
    const params: Record<string, string> = {};
    if (cnpj) params.cpf_cnpj = cnpj;
    if (razao) params.razao_social = razao;
    api.get("/sancoes/ceis", { params })
      .then(r => setItems(r.data.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  const checar = async () => {
    const c = cnpj.replace(/\D/g, "");
    if (!c) return;
    const r = await api.get(`/sancoes/checar/${c}`);
    setVerdict({ temSancao: r.data.tem_sancao_ativa, cnpj: c });
    setItems(r.data.sancoes || []);
  };

  return (
    <div className="space-y-4 p-4">
      <h1 className="text-2xl font-bold">Sanções (CEIS)</h1>
      <p className="text-sm text-muted-foreground">
        Cadastro de Empresas Inidôneas e Suspensas. Use antes de contratar fornecedor.
      </p>

      <div className="flex flex-wrap gap-2">
        <Input placeholder="CNPJ (com ou sem máscara)" className="w-72" value={cnpj}
               onChange={e => setCnpj(e.target.value)} />
        <Input placeholder="Ou razão social" className="w-72" value={razao}
               onChange={e => setRazao(e.target.value)} />
        <Button onClick={buscar}>Buscar</Button>
        <Button variant="outline" onClick={checar}>Checar CNPJ específico</Button>
      </div>

      {verdict && (
        <Card className={verdict.temSancao ? "border-red-300 bg-red-50" : "border-green-300 bg-green-50"}>
          <CardContent className="py-3">
            <p className="font-medium">
              {verdict.temSancao
                ? `⚠️ CNPJ ${verdict.cnpj} TEM SANÇÃO ATIVA - NÃO contratar`
                : `✅ CNPJ ${verdict.cnpj} sem sanção ativa no CEIS`}
            </p>
          </CardContent>
        </Card>
      )}

      {loading ? <p>Carregando…</p> : items.length === 0 ? (
        <p className="text-muted-foreground">Faça uma busca acima.</p>
      ) : (
        <div className="grid gap-3">
          {items.map((s, i) => (
            <Card key={s.id || i}>
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2">
                  {s.razao_social || s.razao}
                  <Badge variant="secondary">{s.cpf_cnpj}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm space-y-1">
                <div><strong>Sanção:</strong> {s.tipo_sancao || s.tipo}</div>
                <div><strong>Período:</strong> {s.dt_inicio} → {s.dt_fim || "indeterminado"}</div>
                <div><strong>Órgão:</strong> {s.orgao}</div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
