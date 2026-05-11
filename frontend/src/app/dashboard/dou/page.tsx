"use client";

import React, { useEffect, useState } from "react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

type Item = {
  id: number; dt: string; secao: string; orgao: string;
  titulo: string; preview: string; url_pdf?: string; municipio_match?: string;
};

export default function DouPage() {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");

  const fetchData = (kw = "") => {
    setLoading(true);
    api.get<{ total: number; items: Item[] }>("/dou", { params: { keyword: kw, limit: 50 } })
      .then(r => setItems(r.data.items || []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchData(); }, []);

  return (
    <div className="space-y-4 p-4">
      <h1 className="text-2xl font-bold">Diário Oficial da União</h1>
      <div className="flex gap-2">
        <Input placeholder="Buscar (município, palavra-chave...)" value={keyword}
               onChange={e => setKeyword(e.target.value)}
               onKeyDown={e => e.key === "Enter" && fetchData(keyword)} />
        <Button onClick={() => fetchData(keyword)}>Buscar</Button>
      </div>
      {loading ? <p>Carregando…</p> : items.length === 0 ? (
        <p className="text-muted-foreground">Nenhuma publicação. Rode <code>backend/ingestion/dou_inlabs.py</code> (precisa credencial INLABS).</p>
      ) : (
        <div className="grid gap-3">
          {items.map(i => (
            <Card key={i.id}>
              <CardHeader>
                <CardTitle className="text-sm">{i.titulo}</CardTitle>
                <div className="text-xs text-muted-foreground">
                  {i.dt} · Seção {i.secao} · {i.orgao}
                  {i.municipio_match && <span className="ml-2 rounded bg-blue-100 px-2 text-blue-700">{i.municipio_match}</span>}
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm">{i.preview}...</p>
                {i.url_pdf && <a className="text-xs text-blue-600 underline" href={i.url_pdf} target="_blank">PDF original</a>}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
