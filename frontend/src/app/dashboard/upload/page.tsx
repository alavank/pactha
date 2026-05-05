"use client";

import React, { useState, useRef } from "react";
import { Upload, Download, FileText, CheckCircle2, AlertCircle } from "lucide-react";
import toast from "react-hot-toast";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const FONTES = [
  { value: "FNS", label: "FNS - Fundo Nacional de Saude", url: "https://consultafns.saude.gov.br/" },
  { value: "InvestSUS", label: "InvestSUS", url: "https://investsuspaineis.saude.gov.br/" },
  { value: "SIMEC", label: "SIMEC / PAR (Educacao)", url: "https://simec.mec.gov.br/par/" },
  { value: "SISMOB", label: "SISMOB (Obras de Saude)", url: "https://sismobcidadao.saude.gov.br/" },
  { value: "Estrutura SUAS", label: "Estrutura SUAS", url: "https://estruturasuas.mds.gov.br/" },
  { value: "CIMEC", label: "CIMEC", url: "" },
  { value: "Outros", label: "Outros", url: "" },
];

export default function UploadPage() {
  const [fonte, setFonte] = useState("FNS");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    inseridos: number;
    erros: string[];
    total_erros: number;
  } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDownloadTemplate = async (format: "xlsx" | "csv") => {
    try {
      const token = localStorage.getItem("pacta_token");
      const res = await fetch(
        `${api.defaults.baseURL}/upload/template?format=${format}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `template_upload_pacta.${format}`;
      a.click();
      toast.success("Template baixado");
    } catch {
      toast.error("Erro ao baixar template");
    }
  };

  const handleUpload = async () => {
    if (!file) {
      toast.error("Selecione um arquivo");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("fonte", fonte);
      const res = await api.post("/upload/convenios", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setResult(res.data);
      toast.success(`${res.data.inseridos} convenios importados`);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setFile(null);
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Erro ao importar");
    } finally {
      setLoading(false);
    }
  };

  const selectedFonte = FONTES.find((f) => f.value === fonte);

  return (
    <div className="space-y-6">
      <div className="border-b border-slate-200 pb-4">
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
          <span>Inicio</span>
          <span>›</span>
          <span className="text-slate-700">Upload de Dados</span>
        </div>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2 tracking-tight">
          <Upload className="size-6 text-blue-700" />
          Upload de Convenios (Fontes sem API)
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Importe dados de FNS, SIMEC, SISMOB, Estrutura SUAS e outras fontes que nao possuem API publica
        </p>
      </div>

      <Card className="border-l-4 border-l-amber-500 bg-amber-50/40">
        <CardContent className="pt-6">
          <h3 className="font-semibold text-amber-900 mb-2">Quando usar Upload Manual?</h3>
          <p className="text-sm text-slate-700 mb-2">
            Use este modulo para incluir convenios e propostas que NAO vem das APIs automaticas (TransfereGov e SIGCON-MG).
            Sao especialmente importantes para o <strong>Relatorio de Monitoramento (RM)</strong>:
          </p>
          <ul className="text-sm text-slate-700 list-disc list-inside space-y-1">
            <li><strong>FNS (consultafns.saude.gov.br)</strong>: Propostas e parcelas pagas do Fundo Nacional de Saude</li>
            <li><strong>SISMOB (sismobcidadao.saude.gov.br)</strong>: Obras de saude</li>
            <li><strong>SIMEC/PAR (simec.mec.gov.br)</strong>: Obras de educacao FNDE</li>
            <li><strong>Estrutura SUAS (estruturasuas.mds.gov.br)</strong>: Construcao de CRAS/CREAS</li>
          </ul>
          <p className="text-xs text-slate-500 mt-3">
            <strong>Dica:</strong> Apos upload, os dados aparecem automaticamente no Dashboard, Convenios e no Relatorio Mensal (RM) gerado para o cliente.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">1. Baixar Template</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Baixe o modelo de planilha com as colunas esperadas e exemplos.
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => handleDownloadTemplate("xlsx")}>
              <Download className="mr-2 size-4" />
              Template Excel (.xlsx)
            </Button>
            <Button variant="outline" onClick={() => handleDownloadTemplate("csv")}>
              <Download className="mr-2 size-4" />
              Template CSV
            </Button>
          </div>
          <div className="mt-3 p-3 bg-gray-50 rounded text-xs font-mono">
            <strong>Colunas esperadas:</strong>
            <br />
            nr_convenio, orgao_concedente, objeto, situacao, valor_total, dt_inicio, dt_fim_vigencia, municipio_ibge, ano
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">2. Selecionar Fonte</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Select value={fonte} onValueChange={(v) => v && setFonte(v)}>
            <SelectTrigger className="w-full max-w-md">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {FONTES.map((f) => (
                <SelectItem key={f.value} value={f.value}>
                  {f.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedFonte?.url && (
            <p className="text-xs text-muted-foreground">
              Portal original:{" "}
              <a
                href={selectedFonte.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-600 hover:underline"
              >
                {selectedFonte.url}
              </a>
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">3. Enviar Arquivo</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.xlsx,.xls"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="block w-full text-sm text-gray-600 file:mr-4 file:py-2 file:px-4 file:rounded-md file:border-0 file:text-sm file:font-medium file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
          />
          {file && (
            <p className="text-sm text-muted-foreground flex items-center gap-2">
              <FileText className="size-4" />
              {file.name} ({(file.size / 1024).toFixed(1)} KB)
            </p>
          )}
          <Button onClick={handleUpload} disabled={!file || loading}>
            {loading ? "Importando..." : "Importar Convenios"}
          </Button>
        </CardContent>
      </Card>

      {result && (
        <Card className="border-green-200 bg-green-50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CheckCircle2 className="size-5 text-green-600" />
              Resultado da Importacao
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p>
              <strong>{result.inseridos}</strong> convenios inseridos/atualizados
            </p>
            {result.total_erros > 0 && (
              <div>
                <p className="flex items-center gap-2 text-orange-700">
                  <AlertCircle className="size-4" />
                  {result.total_erros} linhas com erro
                </p>
                <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {result.erros.map((e, i) => (
                    <li key={i}>• {e}</li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
