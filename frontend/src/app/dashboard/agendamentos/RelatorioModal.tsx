"use client";

/* O RELATÓRIO PDF — Dia, Semana ou Mês, a partir de uma data de referência.
 *
 * ⚠️ QUEM MONTA O RECORTE É O BACKEND. A tela manda `periodo` e `referencia`; a
 * janela (primeiro e último dia) é calculada em `routers/agendamentos._janela`,
 * pela MESMA regra de semana da grade — segunda a domingo. Calcular aqui e
 * mandar `de`/`ate` prontos criaria uma segunda definição de "semana", e a que
 * ficasse para trás produziria um arquivo com um dia a mais ou a menos que a
 * tela de onde ele saiu.
 *
 * ⚠️ O FILTRO ATIVO VAI JUNTO (documento): município e busca. O relatório é o
 * que a pessoa está vendo, em papel — se ele trouxesse a carteira inteira
 * enquanto a tela mostra uma cidade, ninguém descobriria pela tela qual dos dois
 * está certo.
 */

import { useState } from "react";
import { Download, FileText, Loader2 } from "lucide-react";

import api from "@/lib/api";
import {
  BOTAO_CTA, BOTAO_SEC, ESTILO_CTA, ESTILO_SEC, Modal, ModalCorpo, ModalHead,
} from "@/components/ui/superficies";
import { hojeISO } from "./tipos";

type Periodo = "dia" | "semana" | "mes";

const OPCOES: [Periodo, string, string][] = [
  ["dia", "Dia", "só a data escolhida"],
  ["semana", "Semana", "de segunda a domingo"],
  ["mes", "Mês", "do dia 1º ao último"],
];

export default function RelatorioModal({
  filtros, onFechar,
}: {
  /** Exatamente os mesmos parâmetros que a listagem da tela usa. */
  filtros: Record<string, unknown>;
  onFechar: () => void;
}) {
  const [periodo, setPeriodo] = useState<Periodo>("mes");
  const [referencia, setReferencia] = useState(hojeISO());
  const [gerando, setGerando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const gerar = async () => {
    setGerando(true); setErro(null);
    try {
      const r = await api.get("/agendamentos/relatorio/pdf", {
        params: { ...filtros, periodo, referencia }, responseType: "blob",
      });
      /* O nome sai do `Content-Disposition` que o backend manda — assim o nome
         no disco é o MESMO que a trilha de auditoria registrou. */
      const cd = String(r.headers["content-disposition"] || "");
      const nome = /filename=([^;]+)/.exec(cd)?.[1]?.trim()
        || `agendamentos-${periodo}-${referencia}.pdf`;
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = nome; a.click();
      URL.revokeObjectURL(url);
      onFechar();
    } catch (e: unknown) {
      /* ⚠️ O CORPO DE ERRO CHEGA COMO BLOB porque pedimos blob — ler
         `data.detail` direto devolve `undefined` e a mensagem do backend (o 413
         do teto de linhas, com a instrução de estreitar o período) some. */
      const err = e as { response?: { data?: Blob } };
      let msg = "Não foi possível gerar o relatório.";
      try {
        const txt = await err.response?.data?.text();
        msg = JSON.parse(txt || "{}").detail || msg;
      } catch { /* corpo não era JSON; fica a mensagem genérica */ }
      setErro(msg);
    } finally { setGerando(false); }
  };

  return (
    <Modal aberto onFechar={onFechar} maxW="max-w-md" superficie
           rotulo="Relatório PDF">
      <ModalHead titulo="Relatório PDF"
                 sub="A agenda do período, com o filtro que está na tela"
                 onFechar={onFechar} />
      <ModalCorpo className="space-y-3">
        <fieldset>
          <legend className="mb-1.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Período
          </legend>
          <div className="grid gap-1.5 sm:grid-cols-3">
            {OPCOES.map(([v, rotulo, ajuda]) => (
              <button key={v} type="button" onClick={() => setPeriodo(v)}
                      aria-pressed={periodo === v}
                      className="rounded-xl border px-2 py-2 text-left transition-colors"
                      style={periodo === v
                        ? { background: "var(--bi-accent-soft)", borderColor: "transparent" }
                        : { borderColor: "var(--bi-line)" }}>
                <span className="block text-[13px] font-semibold"
                      style={{ color: periodo === v ? "var(--bi-accent-ink)" : "var(--bi-text)" }}>
                  {rotulo}
                </span>
                <span className="block text-[10px] leading-tight"
                      style={{ color: "var(--bi-faint)" }}>{ajuda}</span>
              </button>
            ))}
          </div>
        </fieldset>

        <label className="block">
          <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            Data de referência
          </span>
          <input type="date" value={referencia}
                 onChange={(e) => setReferencia(e.target.value)}
                 className="bi-field mt-1 h-9 w-full px-2 text-[13px]" />
        </label>

        <p className="flex items-start gap-1.5 text-[11px]"
           style={{ color: "var(--bi-faint)" }}>
          <FileText className="mt-0.5 size-3.5 shrink-0" />
          A4 retrato, agrupado por dia, com o cabeçalho do cliente e a paginação.
          As anotações não entram — elas são a conversa interna da equipe.
        </p>

        {erro && (
          <p role="alert" className="rounded-xl px-3 py-2 text-[12px]"
             style={{ background: "color-mix(in oklab, var(--bi-crit) 14%, transparent)",
                      color: "var(--bi-crit-ink)" }}>
            {erro}
          </p>
        )}

        <div className="flex items-center justify-end gap-2 pt-1">
          <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                  onClick={onFechar} disabled={gerando}>
            Cancelar
          </button>
          <button type="button" className={BOTAO_CTA} style={ESTILO_CTA}
                  onClick={gerar} disabled={gerando || !referencia}>
            {gerando ? <Loader2 className="size-3.5 animate-spin" />
                     : <Download className="size-3.5" />}
            Gerar relatório
          </button>
        </div>
      </ModalCorpo>
    </Modal>
  );
}
