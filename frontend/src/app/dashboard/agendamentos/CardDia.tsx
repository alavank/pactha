"use client";

/* O CARD "COMPROMISSOS DE HOJE" — o cartão desgarrado à direita do calendário.
 *
 * ⭐ ELE RESPONDE A PERGUNTA DE QUEM ACABOU DE CHEGAR. O calendário mostra o mês
 * que a pessoa está navegando, que pode ser outubro; este cartão mostra HOJE,
 * sempre — e por isso ele não acompanha a navegação do calendário. Um cartão que
 * seguisse o mês exibido repetiria a informação que já está na grade ao lado.
 *
 * ⚠️ ELE SEMPRE ABRE VISÍVEL, e o ocultar dura só a sessão (pedido do dono).
 * Guardar a escolha no `localStorage` faria alguém que o fechou uma vez em
 * agosto abrir a agenda sem ele em setembro, sem lembrar por quê — e o botão de
 * reexibir fica na barra do calendário, que é onde ninguém procura o que não
 * sabe que sumiu.
 */

import { CalendarClock, X } from "lucide-react";

import {
  Compromisso, estiloDaCor, horarioDe, hojeISO, porExtenso, primeiroNome,
  saudacao,
} from "./tipos";

export default function CardDia({
  itens, nome, comMunicipio, onAbrir, onOcultar,
}: {
  /** TODOS os compromissos do recorte — o filtro do dia é feito aqui, para o
   *  cartão ler exatamente a mesma lista das três abas. */
  itens: Compromisso[];
  nome?: string | null;
  comMunicipio: boolean;
  onAbrir: (c: Compromisso) => void;
  onOcultar: () => void;
}) {
  const hoje = hojeISO();
  const doDia = itens.filter((c) => String(c.data || "").slice(0, 10) === hoje);
  const quem = primeiroNome(nome);

  return (
    <aside className="bi-card flex h-full min-h-0 flex-col overflow-hidden p-0"
           aria-label="Compromissos de hoje">
      <div className="flex items-start justify-between gap-2 px-3.5 pb-2.5 pt-3.5">
        <div className="min-w-0">
          <h2 className="bi-title text-[15px] leading-tight">
            {saudacao()}{quem ? `, ${quem}` : ""}
          </h2>
          <p className="mt-0.5 text-[11px] leading-snug first-letter:uppercase"
             style={{ color: "var(--bi-faint)" }}>
            {porExtenso(hoje)}
          </p>
        </div>
        <button type="button" onClick={onOcultar} aria-label="Ocultar este cartão"
                title="Ocultar" className="shrink-0 rounded-lg p-1 bi-hover"
                style={{ color: "var(--bi-muted)" }}>
          <X className="size-4" />
        </button>
      </div>

      <div className="flex items-center gap-1.5 border-y px-3.5 py-1.5"
           style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface-2)" }}>
        <CalendarClock className="size-3.5" style={{ color: "var(--bi-muted)" }} />
        <span className="text-[10px] font-semibold uppercase tracking-wider"
              style={{ color: "var(--bi-muted)" }}>
          Hoje · {doDia.length}
        </span>
      </div>

      <div className="bi-scroll min-h-0 flex-1 overflow-y-auto p-2">
        {doDia.length === 0 ? (
          <div className="px-3 py-10 text-center">
            <p className="text-[12px]" style={{ color: "var(--bi-muted)" }}>
              Nenhum compromisso hoje.
            </p>
            <p className="mt-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Dê um duplo clique num dia do calendário para marcar um.
            </p>
          </div>
        ) : (
          <ul className="space-y-1">
            {doDia.map((c) => (
              <li key={c.id}>
                <button type="button" onClick={() => onAbrir(c)}
                        style={estiloDaCor(c.cor)}
                        className="flex w-full items-start gap-2 rounded-xl px-2 py-1.5 text-left bi-hover">
                  <span className="ag-tarja mt-1 h-8 w-1 shrink-0 rounded-full" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[11px] font-semibold tabular-nums"
                          style={{ color: "var(--bi-muted)" }}>
                      {horarioDe(c)}
                    </span>
                    <span className="block truncate text-[12px] font-medium leading-snug">
                      {c.demanda}
                    </span>
                    {comMunicipio && (
                      <span className="block truncate text-[11px]"
                            style={{ color: "var(--bi-faint)" }}>
                        {c.municipio}{c.uf ? ` - ${c.uf}` : ""}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
