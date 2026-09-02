"use client";

/* O formulário de AGENDAMENTO — criar, editar, anexar e excluir.
 *
 * Molde: `components/AnotacaoModal.tsx`, o único lugar do repo com upload de
 * arquivo. O que MUDA em relação a ele está marcado com ⚠️ abaixo — cada
 * diferença é um defeito que o molde tem e que não vale a pena copiar.
 */

import React, { useEffect, useState } from "react";
import { Loader2, Paperclip, Trash2, X } from "lucide-react";

import api from "@/lib/api";
import {
  BOTAO_CTA, BOTAO_SEC, ESTILO_CTA, ESTILO_SEC, Modal, ModalCorpo, ModalHead,
} from "@/components/ui/superficies";

interface Anexo {
  nome: string; mime: string; tamanho?: number; dados_b64?: string;
}
interface Item {
  id: number; titulo: string; relato: string | null; data: string | null;
  status: string; responsavel_id: number | null; anexos: Anexo[];
}
interface Usuario { id: number; name?: string; email?: string }

/* Espelha o teto do backend (`MAX_ANEXO_BYTES` = 2MB de base64 ≈ 1,5MB de
 * arquivo). ⚠️ O corte tem de acontecer AQUI, antes do upload: sem ele o
 * arquivo sobe inteiro e volta 413 depois — a pessoa espera o envio de um PDF
 * de 8MB para só então descobrir que ele não cabe. */
const MAX_ARQUIVO = 1_500_000;

function fmtBytes(n?: number): string {
  if (!n) return "";
  return n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)}MB` : `${Math.round(n / 1024)}KB`;
}

export default function AgendamentoModal({
  aberto, municipioId, item, colunas, onFechar, onSalvo,
}: {
  aberto: boolean;
  municipioId: number;
  item: Item | null;
  colunas: { valor: string; rotulo: string }[];
  onFechar: () => void;
  onSalvo: () => void;
}) {
  const [titulo, setTitulo] = useState(item?.titulo || "");
  const [relato, setRelato] = useState(item?.relato || "");
  /* ⚠️ `<input type="date">` só aceita `YYYY-MM-DD`. Passar por formatador
     pt-BR aqui deixa o campo VAZIO sem erro nenhum — o navegador simplesmente
     ignora o valor que não reconhece. */
  const [data, setData] = useState((item?.data || "").slice(0, 10));
  const [status, setStatus] = useState(item?.status || colunas[0]?.valor || "a_fazer");
  const [responsavel, setResponsavel] = useState<string>(
    item?.responsavel_id ? String(item.responsavel_id) : "");
  const [anexos, setAnexos] = useState<Anexo[]>(item?.anexos || []);
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [salvando, setSalvando] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [confirmaExcluir, setConfirmaExcluir] = useState(false);

  useEffect(() => {
    /* A lista de responsáveis. Falha aqui não impede agendar — o campo fica
       vazio e o resto do formulário continua servindo. */
    api.get("/users").then((r) => {
      const lista = Array.isArray(r.data) ? r.data : (r.data?.items || []);
      setUsuarios(lista);
    }).catch(() => setUsuarios([]));
  }, []);

  const anexar = (e: React.ChangeEvent<HTMLInputElement>) => {
    const arquivos = Array.from(e.target.files || []);
    arquivos.forEach((f) => {
      if (f.size > MAX_ARQUIVO) {
        setErr(`"${f.name}" tem ${fmtBytes(f.size)} e o limite por anexo é 1,5MB.`);
        return;
      }
      const leitor = new FileReader();
      leitor.onload = () => {
        const b64 = String(leitor.result || "").split(",")[1] || "";
        setAnexos((prev) => [...prev, {
          nome: f.name, mime: f.type || "application/octet-stream",
          dados_b64: b64, tamanho: f.size,
        }]);
      };
      leitor.readAsDataURL(f);
    });
    e.target.value = "";
  };

  /* ⚠️ CONFERE O STATUS ANTES DE SALVAR O ARQUIVO — e é aqui que este modal se
     afasta do molde. O `baixarAnexo` do `AnotacaoModal` faz `.then(r => r.blob())`
     SEM olhar `r.ok`: quando o backend recusa (403 de quem não tem
     `anexo_baixar`, 404 de índice fora da lista), o corpo de ERRO vira blob e
     desce no disco com o nome do documento. A pessoa recebe um "oficio.pdf" de
     90 bytes com `{"detail":"..."}` dentro, sem nenhum aviso, e conclui que o
     arquivo está corrompido no sistema. */
  const baixar = async (idx: number, nome: string) => {
    if (!item) return;
    setErr(null);
    try {
      const r = await api.get(`/agendamentos/${item.id}/anexo/${idx}`,
                              { responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = nome; a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      const err = e as { response?: { data?: Blob; status?: number } };
      let msg = "Não foi possível baixar o anexo.";
      if (err?.response?.status === 403) {
        msg = "Você não tem permissão para baixar anexos (peça "
            + "«Agendamentos → Baixar anexos» ao administrador).";
      } else {
        try {
          const txt = await err.response?.data?.text();
          msg = JSON.parse(txt || "{}").detail || msg;
        } catch { /* corpo não era JSON */ }
      }
      setErr(msg);
    }
  };

  const salvar = async () => {
    setErr(null);
    if (!titulo.trim()) { setErr("O título é obrigatório — é ele que aparece no calendário e no quadro."); return; }
    if (!data) { setErr("Escolha a data do agendamento."); return; }
    setSalvando(true);
    try {
      const corpo = {
        titulo: titulo.trim(),
        relato: relato.trim() || null,
        data,
        status,
        responsavel_id: responsavel ? Number(responsavel) : null,
        anexos,
      };
      if (item) await api.put(`/agendamentos/${item.id}`, corpo);
      else await api.post("/agendamentos", { ...corpo, municipio_id: municipioId });
      onSalvo();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErr(err?.response?.data?.detail || "Não foi possível salvar.");
    } finally { setSalvando(false); }
  };

  const excluir = async () => {
    if (!item) return;
    setSalvando(true); setErr(null);
    try {
      await api.delete(`/agendamentos/${item.id}`);
      onSalvo();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErr(err?.response?.data?.detail || "Não foi possível excluir.");
      setSalvando(false);
    }
  };

  /* ⚠️ `podeFechar` GUARDA O TRABALHO. Sem ele, Esc, clique fora e o X
     descartam em silêncio um formulário com anexo já carregado — e o descarte
     é irrecuperável, porque o base64 só existe na memória da página. */
  const sujo = !!(titulo.trim() || relato.trim() || anexos.length);

  return (
    <Modal aberto={aberto} onFechar={onFechar} maxW="max-w-lg" superficie
           rotulo={item ? "Editar agendamento" : "Novo agendamento"}
           podeFechar={() => !sujo || salvando
             ? true
             : window.confirm("Descartar este agendamento? O que foi digitado e anexado se perde.")}>
      <ModalHead titulo={item ? "Editar agendamento" : "Novo agendamento"}
                 sub={item ? undefined : "O que a equipe vai fazer, e quando"}
                 onFechar={onFechar} />
      <ModalCorpo className="space-y-3">
        <label className="block">
          <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>Título</span>
          <input value={titulo} onChange={(e) => setTitulo(e.target.value)}
                 maxLength={200} placeholder="Visita técnica — obra da creche"
                 className="bi-input mt-1 h-9 w-full rounded-lg px-2 text-[13px]" />
        </label>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>Data</span>
            <input type="date" value={data} onChange={(e) => setData(e.target.value)}
                   className="bi-input mt-1 h-9 w-full rounded-lg px-2 text-[13px]" />
          </label>
          <label className="block">
            <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>Situação</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
                    className="bi-input mt-1 h-9 w-full rounded-lg px-2 text-[13px]">
              {colunas.map((c) => (
                <option key={c.valor} value={c.valor}>{c.rotulo}</option>
              ))}
            </select>
          </label>
        </div>

        <label className="block">
          <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>Responsável</span>
          <select value={responsavel} onChange={(e) => setResponsavel(e.target.value)}
                  className="bi-input mt-1 h-9 w-full rounded-lg px-2 text-[13px]">
            <option value="">Sem responsável definido</option>
            {usuarios.map((u) => (
              <option key={u.id} value={u.id}>{u.name || u.email}</option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Relato da atividade
          </span>
          <textarea value={relato} onChange={(e) => setRelato(e.target.value)}
                    rows={5} placeholder="O que foi combinado, o que foi feito, o que ficou pendente."
                    className="bi-input mt-1 w-full rounded-lg p-2 text-[13px]" />
        </label>

        <div>
          <div className="flex items-center justify-between">
            <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Anexos <span style={{ color: "var(--bi-faint)" }}>· até 1,5MB cada</span>
            </span>
            <label className={`${BOTAO_SEC} cursor-pointer`} style={ESTILO_SEC}>
              <Paperclip className="size-3.5" /> Anexar
              <input type="file" multiple className="hidden" onChange={anexar}
                     accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx,.xls,.xlsx" />
            </label>
          </div>
          {anexos.length === 0 ? (
            <p className="mt-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Nenhum documento anexado.
            </p>
          ) : (
            <ul className="mt-1.5 space-y-1">
              {anexos.map((ax, i) => (
                <li key={`${ax.nome}-${i}`}
                    className="flex items-center gap-2 rounded-lg px-2 py-1"
                    style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}>
                  {/* Anexo JÁ SALVO (sem `dados_b64` na listagem) baixa pela
                      rota própria; o recém-escolhido ainda só existe aqui. */}
                  {item && !ax.dados_b64 ? (
                    <button type="button" onClick={() => baixar(i, ax.nome)}
                            className="min-w-0 flex-1 truncate text-left text-[11px] underline"
                            style={{ color: "var(--bi-accent-ink)" }}>
                      {ax.nome}
                    </button>
                  ) : (
                    <span className="min-w-0 flex-1 truncate text-[11px]">{ax.nome}</span>
                  )}
                  <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {fmtBytes(ax.tamanho)}
                  </span>
                  <button type="button" aria-label={`Remover ${ax.nome}`}
                          onClick={() => setAnexos((p) => p.filter((_, j) => j !== i))}>
                    <X className="size-3.5" style={{ color: "var(--bi-muted)" }} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        {err && (
          <p className="rounded-lg px-2 py-1.5 text-[11px]"
             style={{ background: "var(--bi-crit-bg)", color: "var(--bi-crit-ink)" }}>
            {err}
          </p>
        )}

        <div className="flex items-center gap-2 pt-1">
          {item && !confirmaExcluir && (
            <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                    onClick={() => setConfirmaExcluir(true)}>
              <Trash2 className="size-3.5" /> Excluir
            </button>
          )}
          {item && confirmaExcluir && (
            <span className="flex items-center gap-2 text-[11px]">
              Excluir mesmo?
              <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                      onClick={excluir} disabled={salvando}>sim</button>
              <button type="button" className="underline"
                      style={{ color: "var(--bi-muted)" }}
                      onClick={() => setConfirmaExcluir(false)}>não</button>
            </span>
          )}
          <button type="button" className={`${BOTAO_CTA} ml-auto`} style={ESTILO_CTA}
                  onClick={salvar} disabled={salvando}>
            {salvando && <Loader2 className="size-3.5 animate-spin" />}
            {item ? "Salvar" : "Criar agendamento"}
          </button>
        </div>
      </ModalCorpo>
    </Modal>
  );
}
