"use client";

import React, { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ArrowLeft, Save, Plus, Trash2, FileText, FileType, Loader2, Lock } from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Input } from "@/components/ui/input";
import {
  Aviso, BOTAO_ACAO, BOTAO_CTA, BOTAO_SEC, Bloco, BlocoHead, ESTILO_CTA, ESTILO_SEC,
} from "@/components/ui/superficies";
import { podeEditarLinha } from "@/lib/escopo";
import { TituloTela } from "@/components/TituloTela";

type Campo = {
  key: string; label: string; tipo: string;
  ajuda?: string; exemplo?: string; opcoes?: string[];
};
type Secao = { titulo: string; tipo?: string; key?: string; item_label?: string; ajuda?: string; campos: Campo[] };
type Schema = { tipo: string; titulo: string; descricao?: string; secoes: Secao[] };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Dados = Record<string, any>;

// A mesma aparencia de campo do resto do sistema (`.bi-field` em globals.css):
// tres desenhos de campo conviviam no produto, um deles sumindo dentro do modal.
const inputCls = "bi-field w-full p-2 text-sm";

/* `travado` = documento de outra pessoa, com alcance por autor ligado. Os
   campos ficam desabilitados em vez de só o botão Salvar: um formulário que
   aceita vinte minutos de digitação e não tem como gravar é a pior versão desta
   regra. `.bi-field:disabled` já tem o desenho apagado (globals.css). */
function CampoInput({ campo, value, onChange, travado }: {
  campo: Campo; value: unknown; onChange: (v: string) => void; travado?: boolean;
}) {
  const v = (value as string) ?? "";
  if (campo.tipo === "textarea") {
    return <textarea rows={4} className={inputCls} value={v} disabled={travado}
                     placeholder={campo.exemplo ? `Ex.: ${campo.exemplo}` : ""}
                     onChange={(e) => onChange(e.target.value)} />;
  }
  if (campo.tipo === "select") {
    return (
      <select className={inputCls + " h-9"} value={v} disabled={travado} onChange={(e) => onChange(e.target.value)}>
        <option value="">Selecione...</option>
        {(campo.opcoes || []).map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    );
  }
  if (campo.tipo === "date") {
    return <Input type="date" value={v} disabled={travado} onChange={(e) => onChange(e.target.value)} />;
  }
  return <Input value={v} disabled={travado}
                placeholder={campo.exemplo ? `Ex.: ${campo.exemplo}` : (campo.tipo === "currency" ? "R$ 0,00" : "")}
                onChange={(e) => onChange(e.target.value)} />;
}

function CampoBlock({ campo, value, onChange, travado }: {
  campo: Campo; value: unknown; onChange: (v: string) => void; travado?: boolean;
}) {
  return (
    <div className="mb-4">
      <label className="block text-[12px] font-semibold" style={{ color: "var(--bi-text)" }}>{campo.label}</label>
      {campo.ajuda && <p className="mt-0.5 mb-1.5 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>{campo.ajuda}</p>}
      <CampoInput campo={campo} value={value} onChange={onChange} travado={travado} />
    </div>
  );
}

function EditorInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const { municipioId } = useMunicipio();
  const tipoParam = sp.get("tipo");
  const idParam = sp.get("id");

  const [schema, setSchema] = useState<Schema | null>(null);
  const [dados, setDados] = useState<Dados>({});
  const [docId, setDocId] = useState<number | null>(idParam ? Number(idParam) : null);
  const [loading, setLoading] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [baixando, setBaixando] = useState("");
  const [dirty, setDirty] = useState(false);
  /* Documento NOVO nasce editável: quem cria é o dono, e o alcance por autor
     não tem o que restringir numa linha que ainda não existe. O `false` só pode
     vir do servidor, ao abrir um documento que já é de outra pessoa. */
  const [podeEditar, setPodeEditar] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        let tipo = tipoParam;
        if (idParam) {
          const r = await api.get<{ tipo: string; dados: Dados; pode_editar?: boolean | null }>(
            `/documentos/${idParam}`,
          );
          tipo = r.data.tipo;
          setDados(r.data.dados || {});
          setPodeEditar(podeEditarLinha(r.data));
        } else {
          /* Voltar a `true` no caminho "documento novo" é obrigatório, e não
             redundante: a navegação daqui para /editor?tipo=X é do lado do
             cliente, o componente NÃO remonta, e sem esta linha um documento de
             outra pessoa aberto antes deixaria o formulário em branco travado. */
          setPodeEditar(true);
        }
        if (tipo) {
          const s = await api.get<Schema>(`/documentos/schema/${tipo}`);
          setSchema(s.data);
        }
      } catch (e) { console.error(e); } finally { setLoading(false); }
    })();
  }, [tipoParam, idParam]);

  const setCampo = useCallback((key: string, val: string) => {
    setDados((d) => ({ ...d, [key]: val })); setDirty(true);
  }, []);
  const setItemCampo = (secKey: string, idx: number, key: string, val: string) => {
    setDados((d) => {
      const arr = Array.isArray(d[secKey]) ? [...d[secKey]] : [];
      arr[idx] = { ...(arr[idx] || {}), [key]: val };
      return { ...d, [secKey]: arr };
    });
    setDirty(true);
  };
  const addItem = (secKey: string) => {
    setDados((d) => ({ ...d, [secKey]: [...(Array.isArray(d[secKey]) ? d[secKey] : []), {}] }));
    setDirty(true);
  };
  const removeItem = (secKey: string, idx: number) => {
    setDados((d) => ({ ...d, [secKey]: (d[secKey] as Dados[]).filter((_, i) => i !== idx) }));
    setDirty(true);
  };

  const salvar = useCallback(async (): Promise<number | null> => {
    if (!schema) return null;
    setSalvando(true);
    try {
      const titulo = (dados.convenio_proposta as string) || schema.titulo;
      if (docId) {
        await api.put(`/documentos/${docId}`, { titulo, dados });
        setDirty(false);
        return docId;
      }
      const r = await api.post<{ id: number }>("/documentos", {
        municipio_id: municipioId ? Number(municipioId) : null,
        tipo: schema.tipo, titulo, dados,
      });
      setDocId(r.data.id); setDirty(false);
      // reflete o id na URL (próximos saves viram PUT)
      const qs = new URLSearchParams({ id: String(r.data.id) });
      if (municipioId) qs.set("municipio_id", municipioId);
      router.replace(`/dashboard/documentos/editor?${qs.toString()}`);
      return r.data.id;
    } catch (e) { console.error(e); alert("Falha ao salvar."); return null; }
    finally { setSalvando(false); }
  }, [schema, dados, docId, municipioId, router]);

  const exportar = async (formato: "pdf" | "docx") => {
    let id = docId;
    /* Exportar continua liberado — é leitura — mas o "salva antes de gerar" NÃO
       vale aqui: num documento de outra pessoa esse salvamento automático seria
       uma escrita que a pessoa não pediu, e que só chegaria como "Falha ao
       salvar" no lugar do arquivo. */
    if (podeEditar && (!id || dirty)) { id = await salvar(); }
    if (!id) return;
    setBaixando(formato);
    try {
      const r = await api.get(`/documentos/${id}/export`, { params: { formato }, responseType: "blob" });
      const mime = formato === "docx"
        ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        : "application/pdf";
      const nome = ((dados.convenio_proposta as string) || schema?.titulo || "documento").replace(/[^\w\-]+/g, "_");
      const url = window.URL.createObjectURL(new Blob([r.data], { type: mime }));
      const a = document.createElement("a");
      a.href = url; a.download = `${nome}.${formato}`;
      document.body.appendChild(a); a.click(); a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) { console.error(e); alert("Falha ao exportar."); } finally { setBaixando(""); }
  };

  const voltar = () => {
    const qs = municipioId ? `?municipio_id=${municipioId}` : "";
    router.push(`/dashboard/documentos${qs}`);
  };

  if (loading) return <div className="flex h-64 items-center justify-center"><Loader2 className="size-7 animate-spin" style={{ color: "var(--bi-faint)" }} /></div>;
  if (!schema) return <div className="p-8 text-center text-[12px]" style={{ color: "var(--bi-faint)" }}>Tipo de documento não encontrado.</div>;

  return (
    <div className="mx-auto max-w-4xl space-y-4 pb-24">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div>
          <button type="button" onClick={voltar}
                  className="mb-1.5 inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors bi-hover"
                  style={ESTILO_SEC}>
            <ArrowLeft className="size-3" /> Voltar
          </button>
          <TituloTela>{schema.titulo}</TituloTela>
          {schema.descricao && <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>{schema.descricao}</p>}
        </div>
        <div className="flex items-center gap-2">
          {podeEditar && (
            <button type="button" onClick={() => salvar()} disabled={salvando} className={BOTAO_CTA} style={ESTILO_CTA}>
              {salvando ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} Salvar
            </button>
          )}
          <button type="button" onClick={() => exportar("pdf")} disabled={!!baixando} className={BOTAO_SEC} style={ESTILO_SEC}>
            {baixando === "pdf" ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />} PDF
          </button>
          <button type="button" onClick={() => exportar("docx")} disabled={!!baixando} className={BOTAO_SEC} style={ESTILO_SEC}>
            {baixando === "docx" ? <Loader2 className="size-4 animate-spin" /> : <FileType className="size-4" />} DOCX
          </button>
        </div>
      </div>

      {!podeEditar && (
        /* Antes do formulário: quem chega aqui por link precisa ler isto antes
           de tentar digitar em campo apagado e concluir que a tela quebrou. */
        <Aviso
          tom="atencao"
          icon={Lock}
          titulo="Este documento foi criado por outra pessoa — aqui você só consulta."
          className=""
        >
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O seu acesso à Geração de Documentos alcança <b>só os que você criou</b>.
            Os campos ficam bloqueados e não há como salvar; exportar em PDF e DOCX
            continua valendo. Para alterar este documento, peça a quem o criou ou a
            um administrador.
          </p>
        </Aviso>
      )}

      {schema.secoes.map((secao) => (
        <Bloco key={secao.titulo} className="p-4">
          <BlocoHead titulo={secao.titulo} sub={secao.tipo === "lista" ? undefined : `${secao.campos.length} campo(s)`} />
          {secao.tipo === "lista" ? (
            <ListaSecao secao={secao} itens={(dados[secao.key!] as Dados[]) || []}
                        onItemChange={(idx, k, v) => setItemCampo(secao.key!, idx, k, v)}
                        onAdd={() => addItem(secao.key!)} onRemove={(idx) => removeItem(secao.key!, idx)}
                        travado={!podeEditar} />
          ) : (
            secao.campos.map((c) => (
              <CampoBlock key={c.key} campo={c} value={dados[c.key]} onChange={(v) => setCampo(c.key, v)}
                          travado={!podeEditar} />
            ))
          )}
        </Bloco>
      ))}

      {podeEditar && (
        <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>As alterações são salvas ao clicar em <strong>Salvar</strong>. Exportar salva automaticamente antes de gerar o arquivo.</p>
      )}
    </div>
  );
}

function ListaSecao({ secao, itens, onItemChange, onAdd, onRemove, travado }: {
  secao: Secao; itens: Dados[];
  onItemChange: (idx: number, key: string, val: string) => void;
  onAdd: () => void; onRemove: (idx: number) => void;
  travado?: boolean;
}) {
  return (
    <div className="space-y-4">
      {secao.ajuda && <p className="-mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>{secao.ajuda}</p>}
      {itens.length === 0 && <p className="text-[12px] italic" style={{ color: "var(--bi-faint)" }}>Nenhum {(secao.item_label || "item").toLowerCase()} cadastrado.</p>}
      {itens.map((item, idx) => (
        <Bloco key={idx} plano className="p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[12px] font-semibold" style={{ color: "var(--bi-muted)" }}>{secao.item_label || "Item"} {idx + 1}</span>
            {!travado && (
              <button type="button" onClick={() => onRemove(idx)} className={BOTAO_ACAO}
                      style={{ ...ESTILO_SEC, color: "var(--bi-crit-ink)" }}>
                <Trash2 className="size-3.5" /> Remover
              </button>
            )}
          </div>
          {secao.campos.map((c) => (
            <CampoBlock key={c.key} campo={c} value={item[c.key]} onChange={(v) => onItemChange(idx, c.key, v)}
                        travado={travado} />
          ))}
        </Bloco>
      ))}
      {!travado && (
        <button type="button" onClick={onAdd} className={BOTAO_SEC} style={ESTILO_SEC}>
          <Plus className="size-4" /> Adicionar {secao.item_label || "item"}
        </button>
      )}
    </div>
  );
}

export default function EditorPage() {
  return (
    <Suspense fallback={<div className="flex h-64 items-center justify-center"><Loader2 className="size-7 animate-spin" style={{ color: "var(--bi-faint)" }} /></div>}>
      <EditorInner />
    </Suspense>
  );
}
