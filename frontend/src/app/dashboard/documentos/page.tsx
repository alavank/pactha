"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { FileSignature, Plus, Pencil, Trash2, FileText, FileType, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  BOTAO_ACAO, BOTAO_CTA, Bloco, BlocoHead, ESTILO_CTA, ESTILO_SEC,
  ItemLinha, Lista, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";

interface Doc {
  id: number;
  municipio_id: number | null;
  tipo: string;
  titulo: string;
  status: string;
  updated_at: string;
}
interface TipoDoc { tipo: string; titulo: string; descricao: string; }

function fmt(iso?: string): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "-" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export default function DocumentosPage() {
  const router = useRouter();
  const { municipioId } = useMunicipio();

  const [docs, setDocs] = useState<Doc[]>([]);
  const [tipos, setTipos] = useState<TipoDoc[]>([]);
  const [loading, setLoading] = useState(false);
  const [baixando, setBaixando] = useState<string>("");

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const params = municipioId ? { municipio_id: municipioId } : {};
      const [d, t] = await Promise.all([
        api.get<{ items: Doc[] }>("/documentos", { params }),
        api.get<{ items: TipoDoc[] }>("/documentos/schemas"),
      ]);
      setDocs(d.data.items ?? []);
      setTipos(t.data.items ?? []);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { carregar(); }, [carregar]);

  const novo = (tipo: string) => {
    const qs = new URLSearchParams({ tipo });
    if (municipioId) qs.set("municipio_id", municipioId);
    router.push(`/dashboard/documentos/editor?${qs.toString()}`);
  };
  const editar = (id: number) => {
    const qs = new URLSearchParams({ id: String(id) });
    if (municipioId) qs.set("municipio_id", municipioId);
    router.push(`/dashboard/documentos/editor?${qs.toString()}`);
  };
  const excluir = async (id: number) => {
    if (!confirm("Excluir este documento? Esta ação não pode ser desfeita.")) return;
    try { await api.delete(`/documentos/${id}`); setDocs((p) => p.filter((d) => d.id !== id)); }
    catch (e) { console.error(e); alert("Falha ao excluir."); }
  };
  const exportar = async (id: number, formato: "pdf" | "docx", titulo: string) => {
    setBaixando(`${id}-${formato}`);
    try {
      const r = await api.get(`/documentos/${id}/export`, { params: { formato }, responseType: "blob" });
      const ext = formato === "docx" ? "docx" : "pdf";
      const mime = formato === "docx"
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : "application/pdf";
      const url = window.URL.createObjectURL(new Blob([r.data], { type: mime }));
      const a = document.createElement("a");
      a.href = url; a.download = `${(titulo || "documento").replace(/[^\w\-]+/g, "_")}.${ext}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); alert("Falha ao exportar."); } finally { setBaixando(""); }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <FileSignature className="size-6" style={{ color: "var(--bi-muted)" }} />
            Geração de Documentos
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Preencha, salve e exporte documentos (DOCX/PDF) com edição e exclusão.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {tipos.map((t) => (
            <button key={t.tipo} type="button" onClick={() => novo(t.tipo)} className={BOTAO_CTA}
                    style={ESTILO_CTA}>
              <Plus className="size-4" /> Novo {t.titulo}
            </button>
          ))}
        </div>
      </div>

      <Bloco className="p-3">
        <BlocoHead
          icon={FileSignature}
          titulo="Documentos"
          sub={`${docs.length} documento(s)${municipioId ? " neste município" : ""}`}
        />
        {loading ? (
          <div className="flex flex-col gap-1.5">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="h-14 animate-pulse rounded-2xl" style={{ background: "var(--bi-surface-2)" }} />
            ))}
          </div>
        ) : docs.length === 0 ? (
          <Vazio>Nenhum documento criado ainda. Use um dos botões acima para começar.</Vazio>
        ) : (
          <Lista>
            {docs.map((d) => (
              <ItemLinha
                key={d.id}
                titulo={d.titulo || "(sem título)"}
                meta={
                  <>
                    <Selo>{tipos.find((t) => t.tipo === d.tipo)?.titulo || d.tipo}</Selo>
                    {d.status && d.status !== "rascunho" && (
                      <Selo tom={situacaoTom(d.status)}>{d.status}</Selo>
                    )}
                    <span>Atualizado {fmt(d.updated_at)}</span>
                  </>
                }
                acao={
                  <>
                    <button type="button" onClick={() => editar(d.id)} className={BOTAO_ACAO} style={ESTILO_SEC} title="Editar">
                      <Pencil className="size-3.5" /> Editar
                    </button>
                    <button type="button" onClick={() => exportar(d.id, "pdf", d.titulo)}
                            disabled={baixando === `${d.id}-pdf`} className={BOTAO_ACAO} style={ESTILO_SEC} title="Exportar PDF">
                      {baixando === `${d.id}-pdf` ? <Loader2 className="size-3.5 animate-spin" /> : <FileText className="size-3.5" />} PDF
                    </button>
                    <button type="button" onClick={() => exportar(d.id, "docx", d.titulo)}
                            disabled={baixando === `${d.id}-docx`} className={BOTAO_ACAO} style={ESTILO_SEC} title="Exportar DOCX">
                      {baixando === `${d.id}-docx` ? <Loader2 className="size-3.5 animate-spin" /> : <FileType className="size-3.5" />} DOCX
                    </button>
                    <button type="button" onClick={() => excluir(d.id)} title="Excluir"
                            className="rounded-lg p-1.5 hover:brightness-90" style={{ color: "var(--bi-crit-ink)" }}>
                      <Trash2 className="size-3.5" />
                    </button>
                  </>
                }
              />
            ))}
          </Lista>
        )}
      </Bloco>
    </div>
  );
}
