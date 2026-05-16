"use client";

import React, { useState } from "react";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { ExternalLink, Search, Loader2 } from "lucide-react";

interface JmgItem {
  id_jornal: number;
  data_publicacao: string;
  tipo_caderno: string;
  texto_resultado: string;
  pagina: number;
  url_visualizar: string;
  url_baixar: string;
}

interface JmgResponse {
  items: JmgItem[];
  pagina_atual: number;
  total_paginas: number;
  total_registros: number;
}

function fmtDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("pt-BR");
  } catch {
    return iso?.slice(0, 10) || "-";
  }
}

function ddmmaaaa(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export default function DouMGPage() {
  const today = new Date();
  const ago30 = new Date(Date.now() - 30 * 86400_000);

  const [texto, setTexto] = useState("");
  const [dataIni, setDataIni] = useState(ddmmaaaa(ago30));
  const [dataFim, setDataFim] = useState(ddmmaaaa(today));
  const [diarioExec, setDiarioExec] = useState(true);
  const [diarioMun, setDiarioMun] = useState(false);
  const [diarioTer, setDiarioTer] = useState(false);
  const [edicaoExtra, setEdicaoExtra] = useState(false);
  const [pagina, setPagina] = useState(1);
  const [data, setData] = useState<JmgResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const buscar = async (p = 1) => {
    if (!texto.trim()) {
      setError("Informe uma palavra ou frase para pesquisar.");
      return;
    }
    setError(null);
    setLoading(true);
    setPagina(p);
    try {
      const res = await api.get<JmgResponse>("/dou-mg/buscar", {
        params: {
          texto: texto.trim(),
          data_inicial: dataIni,
          data_final: dataFim,
          diario_executivo: diarioExec,
          diario_municipios: diarioMun,
          diario_terceiros: diarioTer,
          edicao_extra: edicaoExtra,
          pagina: p,
          tamanho: 20,
        },
      });
      setData(res.data);
    } catch (e) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (e as Error).message;
      setError(`Falha na busca: ${msg}`);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const limpar = () => {
    setTexto("");
    setDiarioExec(true);
    setDiarioMun(false);
    setDiarioTer(false);
    setEdicaoExtra(false);
    setData(null);
    setError(null);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Diário Oficial MG</h1>
        <p className="text-sm text-muted-foreground">
          Busca em tempo real no Jornal Minas Gerais (jornalminasgerais.mg.gov.br)
        </p>
      </div>

      {/* Formulario */}
      <div className="bg-gray-900 text-white rounded-lg p-4 space-y-3">
        <div className="flex items-center gap-2 font-bold text-lg">
          <Search className="size-5" />
          Busca de conteúdo
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="md:col-span-2">
            <label className="text-xs font-medium">Palavra ou frase:*</label>
            <Input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder="Ex: 1261002768/2025 ou MUNICIPIO DE ARAUJOS"
              className="bg-white text-black"
              onKeyDown={(e) => { if (e.key === "Enter") buscar(1); }}
            />
          </div>

          <div>
            <label className="text-xs font-medium">Data Inicial:*</label>
            <Input
              type="date"
              value={dataIni}
              onChange={(e) => setDataIni(e.target.value)}
              className="bg-white text-black"
            />
          </div>
          <div>
            <label className="text-xs font-medium">Data Final:*</label>
            <Input
              type="date"
              value={dataFim}
              onChange={(e) => setDataFim(e.target.value)}
              className="bg-white text-black"
            />
          </div>
        </div>

        <div>
          <label className="text-xs font-medium block mb-1">Caderno:*</label>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
            <Toggle label="Diário do Executivo" checked={diarioExec} onChange={setDiarioExec} />
            <Toggle label="Diário dos Municípios Mineiros" checked={diarioMun} onChange={setDiarioMun} />
            <Toggle label="Diário de Terceiros" checked={diarioTer} onChange={setDiarioTer} />
            <Toggle label="Edição Extra" checked={edicaoExtra} onChange={setEdicaoExtra} />
          </div>
        </div>

        <div className="flex items-center gap-3 justify-end pt-2 border-t border-gray-700">
          <Button variant="ghost" onClick={limpar} className="text-white hover:bg-gray-800">
            Limpar filtros
          </Button>
          <Button onClick={() => buscar(1)} disabled={loading} className="bg-white text-black hover:bg-gray-100">
            {loading ? <Loader2 className="size-4 animate-spin mr-2" /> : <Search className="size-4 mr-2" />}
            Pesquisar
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          {error}
        </div>
      )}

      {/* Resultados */}
      {data && (
        <div className="rounded-lg border bg-white p-4 space-y-3">
          <div className="text-sm text-muted-foreground border-b pb-2">
            <span className="font-semibold text-foreground">{data.total_registros} resultados</span> encontrados
            {texto ? ` para "${texto}"` : ""}, no período de {fmtDate(dataIni)} até {fmtDate(dataFim)}
          </div>

          {data.items.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">Nenhum resultado encontrado.</div>
          ) : (
            <div className="space-y-3">
              {data.items.map((it) => (
                <div key={it.id_jornal} className="border-b pb-3">
                  <div className="text-xs text-muted-foreground mb-1">
                    <span className="font-medium">Data:</span> {fmtDate(it.data_publicacao)} |
                    <span className="font-medium"> Caderno:</span> {it.tipo_caderno} |
                    <span className="font-medium"> Página:</span> {it.pagina}
                  </div>
                  <div className="text-sm text-gray-800 whitespace-pre-wrap mb-2">{it.texto_resultado}</div>
                  <div className="flex items-center gap-3 text-xs">
                    <a
                      href={it.url_visualizar}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 text-blue-700 hover:underline"
                    >
                      <ExternalLink className="size-3" /> Visualizar publicação
                    </a>
                    <a
                      href={it.url_baixar}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="inline-flex items-center gap-1 text-blue-700 hover:underline"
                    >
                      <ExternalLink className="size-3" /> Baixar publicação
                    </a>
                  </div>
                </div>
              ))}
            </div>
          )}

          {data.total_paginas > 1 && (
            <div className="flex items-center justify-between pt-3">
              <div className="text-xs text-muted-foreground">
                Página {data.pagina_atual} de {data.total_paginas}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina <= 1 || loading}
                  onClick={() => buscar(pagina - 1)}
                >
                  Anterior
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pagina >= data.total_paginas || loading}
                  onClick={() => buscar(pagina + 1)}
                >
                  Próximo
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <button
        type="button"
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
          checked ? "bg-green-500" : "bg-red-500"
        }`}
        aria-pressed={checked}
      >
        <span
          className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
            checked ? "translate-x-4" : "translate-x-0.5"
          }`}
        />
      </button>
      <span>{label}</span>
    </label>
  );
}
