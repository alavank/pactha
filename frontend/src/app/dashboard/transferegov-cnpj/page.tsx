"use client";

import React, { useState } from "react";
import { Search as SearchIcon, Loader2, Landmark, Building2 } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

interface Especial {
  id?: number; codigo?: string; programa_codigo?: string; situacao?: string;
  beneficiario_nome?: string; beneficiario_cnpj?: string; uf?: string;
  politicas_publicas?: string; emenda_codigo?: string; valor_total?: number;
  objeto_descricao?: string;
}
interface Voluntaria {
  numero_proposta?: string; situacao?: string; orgao?: string; proponente?: string;
  identificacao?: string; codigo_instrumento?: string;
  valor_repasse?: number | null; valor_contrapartida?: number | null;
}
interface Resp {
  cnpj: string;
  especiais: Especial[]; voluntarias: Voluntaria[];
  total_especiais: number; total_voluntarias: number;
}

function maskCnpj(v: string): string {
  const d = v.replace(/\D/g, "").slice(0, 14);
  return d
    .replace(/^(\d{2})(\d)/, "$1.$2")
    .replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3")
    .replace(/\.(\d{3})(\d)/, ".$1/$2")
    .replace(/(\d{4})(\d)/, "$1-$2");
}

export default function TransfereGovCnpjPage() {
  const [cnpj, setCnpj] = useState("");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [data, setData] = useState<Resp | null>(null);

  const consultar = async () => {
    const digits = cnpj.replace(/\D/g, "");
    if (digits.length !== 14) { setErro("Informe um CNPJ com 14 dígitos."); return; }
    setLoading(true); setErro(null);
    try {
      const r = await api.get<Resp>("/transferegov/por-cnpj", { params: { cnpj: digits } });
      setData(r.data);
    } catch (e: unknown) {
      setErro((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro na consulta.");
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
          <Building2 className="size-6 text-primary" /> Consulta TransfereGov por CNPJ
        </h1>
        <p className="text-sm text-base-content/60">
          Busca por CNPJ do proponente — Transferência Especial (Plano de Ação, ao vivo) + Voluntárias (dados já coletados). Não entra em relatório.
        </p>
      </div>

      {/* Barra de consulta */}
      <div className="flex flex-wrap items-end gap-3 bg-base-100 border rounded-lg p-4">
        <div>
          <label className="text-xs text-base-content/70 mb-1 block">CNPJ do proponente</label>
          <Input
            value={cnpj}
            onChange={(e) => setCnpj(maskCnpj(e.target.value))}
            onKeyDown={(e) => e.key === "Enter" && consultar()}
            placeholder="00.000.000/0000-00"
            className="w-56 font-mono"
          />
        </div>
        <Button onClick={consultar} disabled={loading} className="bg-primary hover:bg-primary/90">
          {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <SearchIcon className="size-4 mr-1" />}
          Consultar
        </Button>
      </div>

      {erro && <div className="rounded-lg border border-error bg-error/15 p-3 text-sm text-error">{erro}</div>}

      {data && (
        <div className="space-y-6">
          {/* Especiais / Plano de Acao */}
          <div className="bg-base-100 border rounded-lg overflow-hidden">
            <div className="px-4 py-2.5 bg-base-200 border-b flex items-center gap-2">
              <Landmark className="size-4 text-primary" />
              <span className="font-semibold text-sm">Transferência Especial (Plano de Ação)</span>
              <span className="ml-auto text-xs text-base-content/60">{data.total_especiais} resultado(s)</span>
            </div>
            {data.especiais.length === 0 ? (
              <div className="p-4 text-sm text-base-content/60">Nenhum plano de ação para este CNPJ.</div>
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] bg-base-200/50">
                    <TableHead>Código</TableHead>
                    <TableHead>UF</TableHead>
                    <TableHead>Beneficiário</TableHead>
                    <TableHead>Situação</TableHead>
                    <TableHead>Emenda</TableHead>
                    <TableHead>Políticas</TableHead>
                    <TableHead className="text-right">Valor</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.especiais.map((e, i) => (
                    <TableRow key={e.id ?? i} className="[&>td]:py-1.5 [&>td]:px-2 hover:bg-base-200">
                      <TableCell className="font-mono">{e.codigo || "-"}</TableCell>
                      <TableCell>{e.uf || "-"}</TableCell>
                      <TableCell title={e.beneficiario_nome}>{e.beneficiario_nome || "-"}</TableCell>
                      <TableCell>{e.situacao || "-"}</TableCell>
                      <TableCell className="font-mono">{e.emenda_codigo || "-"}</TableCell>
                      <TableCell title={e.politicas_publicas} className="max-w-[220px] truncate">{e.politicas_publicas || "-"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{formatCurrency(e.valor_total)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>

          {/* Voluntarias */}
          <div className="bg-base-100 border rounded-lg overflow-hidden">
            <div className="px-4 py-2.5 bg-base-200 border-b flex items-center gap-2">
              <Landmark className="size-4 text-primary" />
              <span className="font-semibold text-sm">Voluntárias (convênios) — dados já coletados</span>
              <span className="ml-auto text-xs text-base-content/60">{data.total_voluntarias} resultado(s)</span>
            </div>
            {data.voluntarias.length === 0 ? (
              <div className="p-4 text-sm text-base-content/60">
                Nenhuma proposta voluntária deste CNPJ nos dados já coletados.
              </div>
            ) : (
              <Table className="text-xs">
                <TableHeader>
                  <TableRow className="[&>th]:py-1.5 [&>th]:px-2 [&>th]:text-[11px] bg-base-200/50">
                    <TableHead>Proposta</TableHead>
                    <TableHead>Instrumento</TableHead>
                    <TableHead>Proponente</TableHead>
                    <TableHead>Órgão</TableHead>
                    <TableHead>Situação</TableHead>
                    <TableHead className="text-right">Repasse</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.voluntarias.map((v, i) => (
                    <TableRow key={(v.numero_proposta ?? "") + i} className="[&>td]:py-1.5 [&>td]:px-2 hover:bg-base-200">
                      <TableCell className="font-mono">{v.numero_proposta || "-"}</TableCell>
                      <TableCell className="font-mono">{v.codigo_instrumento || "-"}</TableCell>
                      <TableCell title={v.proponente} className="max-w-[220px] truncate">{v.proponente || "-"}</TableCell>
                      <TableCell>{v.orgao || "-"}</TableCell>
                      <TableCell title={v.situacao} className="max-w-[200px] truncate">{v.situacao || "-"}</TableCell>
                      <TableCell className="text-right whitespace-nowrap">{formatCurrency(v.valor_repasse)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
