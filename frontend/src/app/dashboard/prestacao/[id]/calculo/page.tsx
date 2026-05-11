"use client";

import React, { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Download, Upload, Link2, Loader2 } from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type ComparativoItem = {
  item_id: number;
  item: string;
  categoria: string | null;
  valor_planejado: number;
  valor_executado: number;
  saldo: number;
  pct_execucao: number;
  qtd_nfs: number;
  alertas: string[];
};

type Comparativo = {
  prestacao_id: number;
  convenio: { esfera?: string; nr?: string; objeto?: string; valor_global?: number };
  totais: {
    planejado: number;
    executado: number;
    saldo: number;
    pct_execucao: number;
  };
  itens: ComparativoItem[];
  nfs_orfas: { id: number; nf_numero?: string; valor: number; fornecedor?: string; descricao?: string }[];
  soma_nfs_orfas: number;
};

const fmtBR = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

export default function PrestacaoCalculoPage() {
  const params = useParams();
  const prestacaoId = params.id as string;

  const [data, setData] = useState<Comparativo | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState<"plano" | "nfs" | null>(null);
  const [linking, setLinking] = useState(false);

  const fetchData = () => {
    setLoading(true);
    api
      .get<Comparativo>(`/prestacao-calculo/${prestacaoId}/comparativo`)
      .then((r) => setData(r.data))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchData();
  }, [prestacaoId]);

  const handleUpload = async (
    tipo: "plano" | "notas",
    file: File
  ): Promise<void> => {
    setUploading(tipo === "plano" ? "plano" : "nfs");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api.post(`/prestacao-calculo/${prestacaoId}/${tipo}`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast.success(
        tipo === "plano"
          ? `${r.data.itens_inseridos} itens do plano importados`
          : `${r.data.notas_inseridas} NFs importadas`
      );
      fetchData();
    } catch {
      toast.error("Falha no upload. Verifique o XLSX.");
    } finally {
      setUploading(null);
    }
  };

  const handleAutoLink = async () => {
    setLinking(true);
    try {
      const r = await api.post(`/prestacao-calculo/${prestacaoId}/auto-link`);
      toast.success(
        `${r.data.nfs_linkadas} NFs vinculadas | ${r.data.nfs_orfas} ainda sem item`
      );
      fetchData();
    } catch {
      toast.error("Falha ao vincular NFs");
    } finally {
      setLinking(false);
    }
  };

  const downloadAuth = async (path: string, filename: string) => {
    const token = localStorage.getItem("pacta_token");
    const r = await fetch(`${api.defaults.baseURL}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const blob = await r.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
  };

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">
          Prestação #{prestacaoId} — Cálculo NF × Plano
        </h1>
        <Button
          onClick={() =>
            downloadAuth(
              `/prestacao-calculo/${prestacaoId}/comparativo-xlsx`,
              `comparativo_${prestacaoId}.xlsx`
            )
          }
        >
          <Download className="mr-2 size-4" />
          Baixar Comparativo (XLSX)
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">1. Upload do Plano de Trabalho</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadAuth(`/prestacao-calculo/template-plano-xlsx`, "template_plano.xlsx")
              }
            >
              <Download className="mr-2 size-4" />
              Baixar Template
            </Button>
            <label className="block">
              <span className="sr-only">Upload plano</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                disabled={uploading === "plano"}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleUpload("plano", f);
                  e.target.value = "";
                }}
                className="block w-full text-sm file:mr-2 file:rounded file:border-0 file:bg-blue-50 file:px-3 file:py-1 file:text-blue-700"
              />
            </label>
            {uploading === "plano" && (
              <Loader2 className="animate-spin size-4 text-blue-600" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">2. Upload das Notas Fiscais</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadAuth(`/prestacao-calculo/template-nf-xlsx`, "template_nf.xlsx")
              }
            >
              <Download className="mr-2 size-4" />
              Baixar Template
            </Button>
            <label className="block">
              <span className="sr-only">Upload NFs</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                disabled={uploading === "nfs"}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleUpload("notas", f);
                  e.target.value = "";
                }}
                className="block w-full text-sm file:mr-2 file:rounded file:border-0 file:bg-blue-50 file:px-3 file:py-1 file:text-blue-700"
              />
            </label>
            {uploading === "nfs" && (
              <Loader2 className="animate-spin size-4 text-blue-600" />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">3. Vincular NF → Item do Plano</CardTitle>
          </CardHeader>
          <CardContent>
            <Button
              size="sm"
              onClick={handleAutoLink}
              disabled={linking}
              className="bg-purple-700 hover:bg-purple-800"
            >
              {linking ? (
                <Loader2 className="mr-2 animate-spin size-4" />
              ) : (
                <Link2 className="mr-2 size-4" />
              )}
              Vincular Automaticamente
            </Button>
            <p className="mt-2 text-xs text-muted-foreground">
              Compara descrição e valor entre NF e plano. Score ≥ 0.4 vincula.
            </p>
          </CardContent>
        </Card>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="animate-spin size-6" />
        </div>
      ) : data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Totais</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 gap-4 text-sm">
                <Stat label="Planejado" value={fmtBR(data.totais.planejado)} />
                <Stat label="Executado" value={fmtBR(data.totais.executado)} />
                <Stat label="Saldo" value={fmtBR(data.totais.saldo)} />
                <Stat label="% Execução" value={`${data.totais.pct_execucao}%`} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Itens do Plano ({data.itens.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="p-2">Item</th>
                    <th className="p-2 text-right">Planejado</th>
                    <th className="p-2 text-right">Executado</th>
                    <th className="p-2 text-right">% Exec</th>
                    <th className="p-2 text-center">Qtd NFs</th>
                    <th className="p-2">Alertas</th>
                  </tr>
                </thead>
                <tbody>
                  {data.itens.map((it) => (
                    <tr
                      key={it.item_id}
                      className={
                        it.alertas.some((a) => a.includes("EXCESSO"))
                          ? "bg-red-50"
                          : it.alertas.includes("Sem NFs")
                          ? "bg-yellow-50"
                          : ""
                      }
                    >
                      <td className="p-2">
                        {it.item}
                        {it.categoria && (
                          <span className="ml-2 text-xs text-muted-foreground">
                            ({it.categoria})
                          </span>
                        )}
                      </td>
                      <td className="p-2 text-right">{fmtBR(it.valor_planejado)}</td>
                      <td className="p-2 text-right">{fmtBR(it.valor_executado)}</td>
                      <td className="p-2 text-right">{it.pct_execucao}%</td>
                      <td className="p-2 text-center">{it.qtd_nfs}</td>
                      <td className="p-2 text-xs">{it.alertas.join("; ") || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          {data.nfs_orfas.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>
                  NFs sem vínculo ({data.nfs_orfas.length}) — Soma{" "}
                  {fmtBR(data.soma_nfs_orfas)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <table className="w-full text-sm">
                  <thead className="bg-gray-50 text-left">
                    <tr>
                      <th className="p-2">NF</th>
                      <th className="p-2">Fornecedor</th>
                      <th className="p-2">Descrição</th>
                      <th className="p-2 text-right">Valor</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.nfs_orfas.map((nf) => (
                      <tr key={nf.id}>
                        <td className="p-2">{nf.nf_numero || "-"}</td>
                        <td className="p-2">{nf.fornecedor || "-"}</td>
                        <td className="p-2 text-xs">{nf.descricao?.slice(0, 80) || "-"}</td>
                        <td className="p-2 text-right">{fmtBR(nf.valor)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </>
      ) : (
        <div className="text-center text-muted-foreground p-8">
          Faça upload do plano e das NFs para gerar o comparativo.
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-bold">{value}</div>
    </div>
  );
}
