"use client";

import React, { useState, useEffect, useCallback } from "react";
import { Plus, Trash2, Loader2, Paperclip, Download, FileText, Edit2, CalendarDays, X } from "lucide-react";
import api from "@/lib/api";
import { formatDataCurta as fmtData } from "@/lib/bi-format";
import {
  Aviso, Bloco, BlocoHead, Modal, ModalCorpo, ModalHead, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";
import AvisoEscopo from "@/components/AvisoEscopo";
import {
  contarSemEscrita, linhaSemEscrita, podeEditarLinha, podeExcluirLinha,
} from "@/lib/escopo";
import { Input } from "@/components/ui/input";

interface Anexo {
  nome: string;
  mime: string;
  dados_b64?: string; // omitido na lista, presente no item
  tamanho?: number;
}

interface Anotacao {
  id: number;
  municipio_id: number;
  fonte: string;
  fonte_ref: string;
  numero_referencia?: string;
  status_interno?: string | null;
  status_custom?: string | null;
  protocolo?: string | null;
  data_protocolo?: string | null;
  observacoes?: string | null;
  anexos: Anexo[];
  created_at?: string;
  updated_at?: string;
  /** O veredito do servidor sobre ESTA anotação: `false` quando o alcance da
   *  pessoa é "somente os que ele criou" e a anotação é de outra. Ver
   *  `lib/escopo.ts` — ausente é "a API não respondeu isso", e aí nada muda. */
  pode_editar?: boolean | null;
  pode_excluir?: boolean | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  fonte: string; // sigcon | voluntaria | plano_acao | fns | simec | emenda | rm
  fonteRef: string;
  municipioId: number;
  numeroReferencia?: string;
  onChanged?: () => void;
}

function fmtBytes(n?: number) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

const rotulo = "mb-1 block text-[11px]";
const controle = "bi-field w-full px-2 py-1.5 text-[12px]";

export default function AnotacaoModal({
  open, onClose, fonte, fonteRef, municipioId, numeroReferencia, onChanged,
}: Props) {
  const [items, setItems] = useState<Anotacao[]>([]);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<Anotacao | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [statusOpcoes, setStatusOpcoes] = useState<string[]>([]);

  // Form state
  const [statusInt, setStatusInt] = useState("");
  const [statusCustom, setStatusCustom] = useState("");
  const [protocolo, setProtocolo] = useState("");
  const [dataProt, setDataProt] = useState("");
  const [obs, setObs] = useState("");
  const [anexos, setAnexos] = useState<Anexo[]>([]);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    if (!open) return;
    setLoading(true);
    try {
      const r = await api.get<{ items: Anotacao[] }>("/gestao/anotacoes/item", {
        params: { fonte, fonte_ref: fonteRef },
      });
      setItems(r.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [open, fonte, fonteRef]);

  useEffect(() => { if (open) carregar(); }, [open, carregar]);

  useEffect(() => {
    if (statusOpcoes.length || !open) return;
    api.get<{ opcoes: string[] }>("/gestao/status-opcoes")
      .then((r) => setStatusOpcoes(r.data.opcoes)).catch(() => {});
  }, [open, statusOpcoes.length]);

  /* Há algo digitado que se perderia ao fechar. Anexo conta: subir um arquivo
     e fechar sem salvar é o descarte mais caro deste formulário. */
  const sujo =
    formOpen &&
    !!(statusInt || statusCustom.trim() || protocolo.trim() || dataProt || obs.trim() || anexos.length);

  const resetForm = () => {
    setStatusInt(""); setStatusCustom(""); setProtocolo("");
    setDataProt(""); setObs(""); setAnexos([]); setEditing(null); setErr(null);
  };

  const startEdit = (a: Anotacao) => {
    setEditing(a);
    setStatusInt(a.status_interno || "");
    setStatusCustom(a.status_custom || "");
    setProtocolo(a.protocolo || "");
    // Alimenta um input[type=date], que só aceita YYYY-MM-DD — nunca passar
    // por formatador pt-BR aqui.
    setDataProt(a.data_protocolo || "");
    setObs(a.observacoes || "");
    // Os anexos vêm COM `dados_b64` porque `/gestao/anotacoes/item` usa
    // `with_anexos=True`. Não "enxugar" este payload: o PUT reescreve a coluna
    // inteira, então salvar uma edição com os anexos sem dados apagaria os
    // arquivos.
    setAnexos(a.anexos || []);
    setFormOpen(true);
  };

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    files.forEach((f) => {
      if (f.size > 1_500_000) {
        setErr(`Arquivo "${f.name}" excede 1.5MB (limite por anexo).`);
        return;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        // data:mime/type;base64,XXXX
        const b64 = result.split(",")[1] || "";
        setAnexos((prev) => [...prev, {
          nome: f.name, mime: f.type || "application/octet-stream",
          dados_b64: b64, tamanho: f.size,
        }]);
      };
      reader.readAsDataURL(f);
    });
    e.target.value = "";
  };

  const salvar = async () => {
    setErr(null);
    if (statusInt === "Outro" && !statusCustom.trim()) {
      setErr("Status 'Outro' exige preenchimento do campo livre."); return;
    }
    setSaving(true);
    try {
      const payload = {
        municipio_id: municipioId,
        fonte, fonte_ref: fonteRef, numero_referencia: numeroReferencia,
        status_interno: statusInt || null,
        status_custom: statusInt === "Outro" ? statusCustom : null,
        protocolo: protocolo || null,
        data_protocolo: dataProt || null,
        observacoes: obs || null,
        anexos,
      };
      if (editing) {
        await api.put(`/gestao/anotacoes/${editing.id}`, payload);
      } else {
        await api.post("/gestao/anotacoes", payload);
      }
      resetForm();
      setFormOpen(false);
      await carregar();
      onChanged?.();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErr(err.response?.data?.detail || "Falha ao salvar.");
    } finally { setSaving(false); }
  };

  const remover = async (id: number) => {
    if (!confirm("Remover esta anotação?")) return;
    try {
      await api.delete(`/gestao/anotacoes/${id}`);
      await carregar();
      onChanged?.();
    } catch (e) { console.error(e); }
  };

  /* ⚠️ ESTA FUNÇÃO BAIXAVA O ERRO COMO SE FOSSE O DOCUMENTO. Ela fazia
   * `fetch(...).then(r => r.blob())` sem olhar `r.ok`: quando o backend recusa
   * — 403 de quem não tem `gestao.anexo_baixar`, 404 de índice fora da lista —
   * o corpo de ERRO virava blob e descia no disco com o nome do arquivo real. A
   * pessoa recebia um "oficio.pdf" de 90 bytes com `{"detail":"..."}` dentro,
   * sem aviso nenhum, e concluía que o documento estava corrompido no sistema.
   *
   * ⚠️ E o `fetch` manual lia `pactha_token` do localStorage — o token que
   * `lib/api.ts` APAGA no primeiro refresh (auto-cura). Aqui o header era
   * guardado (`token ? ... : {}`), então não chegava a mandar `Bearer null`,
   * mas o caminho continuava sem a renovação automática e sem o retry que o
   * `api` faz. Passa pelo cliente, como as outras telas já passam. */
  const baixarAnexo = async (anotId: number, idx: number, nome: string) => {
    setErr(null);
    try {
      const r = await api.get(`/gestao/anotacoes/${anotId}/anexo/${idx}`,
                              { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = nome;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      const erro = e as { response?: { data?: Blob; status?: number } };
      let msg = "Não foi possível baixar o anexo.";
      if (erro?.response?.status === 403) {
        msg = "Você não tem permissão para baixar anexos (peça "
            + "«Gestão Interna → Baixar anexos» ao administrador).";
      } else {
        // O corpo de erro chega como Blob porque pedimos blob: sem o `.text()`
        // a mensagem do backend some e sobra a genérica.
        try {
          const txt = await erro.response?.data?.text();
          msg = JSON.parse(txt || "{}").detail || msg;
        } catch { /* corpo não era JSON */ }
      }
      setErr(msg);
    }
  };

  return (
    <Modal
      aberto={open}
      onFechar={onClose}
      maxW="max-w-3xl"
      /* Vale nas TRÊS saídas (Esc, clique fora e o X). O gatilho é ter algo a
         PERDER, não ter o formulário aberto: abrir o formulário por engano e
         não conseguir mais sair com Esc era o efeito da primeira tentativa. */
      podeFechar={() =>
        !sujo || confirm("Descartar esta anotação? O que você digitou será perdido.")
      }
    >
      <ModalHead
        titulo="Gestão Interna"
        sub={numeroReferencia ? `Sobre ${numeroReferencia}` : "Anotações da equipe, à parte do dado oficial"}
        onFechar={onClose}
      />
      <ModalCorpo className="flex flex-col gap-3">
        {loading ? (
          <div className="py-8 text-center">
            <Loader2 className="mx-auto size-6 animate-spin" style={{ color: "var(--bi-faint)" }} />
          </div>
        ) : items.length === 0 ? (
          <Vazio>Nenhuma anotação ainda.</Vazio>
        ) : (
          <div className="flex flex-col gap-1.5">
            <AvisoEscopo
              bloqueadas={contarSemEscrita(items)}
              total={items.length}
              plural="as anotações"
            />
            {items.map((a) => {
              // Antes o selo só aparecia com `status_interno` preenchido, então
              // registro antigo que só tem texto livre ficava sem status nenhum.
              const status = a.status_interno === "Outro"
                ? (a.status_custom || "Outro")
                : (a.status_interno || a.status_custom);
              return (
                <Bloco key={a.id} plano className="p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        {status && <Selo tom={situacaoTom(status)}>{status}</Selo>}
                        {a.protocolo && (
                          <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                            Protocolo{" "}
                            <span className="bi-num" style={{ color: "var(--bi-muted)" }}>{a.protocolo}</span>
                          </span>
                        )}
                        {a.data_protocolo && (
                          <span className="inline-flex items-center gap-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                            <CalendarDays className="size-3" />
                            <span className="bi-num">{fmtData(a.data_protocolo)}</span>
                          </span>
                        )}
                      </div>
                      {a.observacoes && (
                        <p className="mt-1 text-[12px] leading-snug whitespace-pre-wrap break-words" style={{ color: "var(--bi-text)" }}>
                          {a.observacoes}
                        </p>
                      )}
                      {a.anexos && a.anexos.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {a.anexos.map((ax, i) => (
                            <button
                              key={i}
                              type="button"
                              onClick={() => baixarAnexo(a.id, i, ax.nome)}
                              className="inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-[10px] transition-colors bi-hover"
                              style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
                              title={`${ax.nome} · ${fmtBytes(ax.tamanho)}`}
                            >
                              <Paperclip className="size-3" /> {ax.nome}
                              <Download className="size-3" style={{ color: "var(--bi-accent-ink)" }} />
                            </button>
                          ))}
                        </div>
                      )}
                      <div className="mt-1.5 text-[9px]" style={{ color: "var(--bi-faint)" }}>
                        Atualizado {fmtData(a.updated_at)}
                      </div>
                    </div>
                    {/* A COLUNA INTEIRA some quando não sobra ação nenhuma — e
                        não só os botões dentro dela: uma coluna vazia com `gap`
                        continua ocupando lugar e desalinharia este cartão em
                        relação aos de cima e de baixo. Os anexos continuam
                        baixáveis: baixar é leitura. */}
                    {!linhaSemEscrita(a) && (
                      <div className="flex shrink-0 flex-col gap-1">
                        {podeEditarLinha(a) && (
                          <button type="button" onClick={() => startEdit(a)} title="Editar"
                                  className="rounded-lg p-1 transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-muted)" }}>
                            <Edit2 className="size-4" />
                          </button>
                        )}
                        {podeExcluirLinha(a) && (
                          <button type="button" onClick={() => remover(a.id)} title="Remover"
                                  className="rounded-lg p-1 transition-colors hover:bg-[var(--bi-line)]" style={{ color: "var(--bi-muted)" }}>
                            <Trash2 className="size-4" />
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                </Bloco>
              );
            })}
          </div>
        )}

        {!formOpen ? (
          <button
            type="button"
            onClick={() => { resetForm(); setFormOpen(true); }}
            className="flex h-9 w-full items-center justify-center gap-1.5 rounded-xl text-[12px] font-semibold transition-colors bi-hover"
            style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
          >
            <Plus className="size-4" /> Nova anotação
          </button>
        ) : (
          /* O formulário era uma caixa tracejada azul: borda de 2px pontilhada
             mais fundo `bg-info/15`. Isso é a gramática de "alerta", e um
             formulário não é um alerta — é só o próximo bloco da pilha. */
          <Bloco className="p-3">
            <BlocoHead icon={Edit2} titulo={editing ? "Editar anotação" : "Nova anotação"} />
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="md:col-span-2">
                <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Status</label>
                <select
                  value={statusInt}
                  onChange={(e) => setStatusInt(e.target.value)}
                  className={controle}
                >
                  <option value="">(selecione)</option>
                  {statusOpcoes.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              {statusInt === "Outro" && (
                <div className="md:col-span-2">
                  <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Descreva o status</label>
                  <Input value={statusCustom} onChange={(e) => setStatusCustom(e.target.value)} placeholder="Texto livre do status" />
                </div>
              )}
              <div>
                <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Protocolo</label>
                <Input value={protocolo} onChange={(e) => setProtocolo(e.target.value)} placeholder="Nº protocolo / SEI" />
              </div>
              <div>
                <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Data</label>
                <Input type="date" value={dataProt} onChange={(e) => setDataProt(e.target.value)} />
              </div>
              <div className="md:col-span-2">
                <label className={rotulo} style={{ color: "var(--bi-muted)" }}>Observações</label>
                <textarea
                  value={obs} onChange={(e) => setObs(e.target.value)}
                  className={`${controle} min-h-[80px]`}
                  placeholder="Detalhes, contexto, próximos passos..."
                />
              </div>
              <div className="md:col-span-2">
                <label className={rotulo} style={{ color: "var(--bi-muted)" }}>
                  Anexos (PDF/imagem, máx 1.5MB cada)
                </label>
                <input type="file" accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
                       multiple onChange={handleFile}
                       className="text-[11px]" style={{ color: "var(--bi-muted)" }} />
                {anexos.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {anexos.map((a, i) => (
                      <div key={i} className="inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-[10px]"
                           style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}>
                        <FileText className="size-3" /> {a.nome} {a.tamanho ? `(${fmtBytes(a.tamanho)})` : ""}
                        <button type="button" onClick={() => setAnexos(anexos.filter((_, j) => j !== i))}
                                className="ml-1 hover:brightness-90" style={{ color: "var(--bi-crit-ink)" }} aria-label="Remover anexo">
                          <X className="size-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {err && <Aviso tom="critico" titulo={err} />}

            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => { resetForm(); setFormOpen(false); }}
                disabled={saving}
                className="h-9 rounded-xl px-3 text-[12px] font-semibold transition-colors bi-hover disabled:opacity-60"
                style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={salvar}
                disabled={saving}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl px-3 text-[12px] font-semibold transition-opacity disabled:opacity-60"
                style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
              >
                {saving && <Loader2 className="size-4 animate-spin" />}
                {editing ? "Salvar alterações" : "Criar anotação"}
              </button>
            </div>
          </Bloco>
        )}
      </ModalCorpo>
    </Modal>
  );
}
