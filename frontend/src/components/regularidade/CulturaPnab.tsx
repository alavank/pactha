"use client";
// CULTURA (PNAB) — o município vai continuar recebendo a Política Nacional Aldir Blanc?
//
// Lei 14.399/2022, art. 6º, § 8º (Lei 15.132/2025): a partir de 2027, só recebe o PNAB
// o ente que dispuser de fundo de cultura. Até 2026 o repasse vai para a estrutura que
// o ente indicar — por isso muito município recebe hoje sem ter o fundo, e perde em 2027.
//
// ⚠️ A REGRA NÃO MORA AQUI. A situação (ok / atenção / risco / sem dado) vem pronta de
// `GET /api/cultura-pnab` (`services/cultura_pnab.py`), que cruza o registro no Sistema
// Nacional de Cultura com para onde o PNAB dos últimos 12 meses foi (planilha da CGU).
import React from "react";
import { Landmark } from "lucide-react";
import { Aviso, Bloco, BlocoHead, Selo, Vazio } from "@/components/ui/superficies";
import { formatCurrency } from "@/lib/utils";

export interface CulturaPnabResp {
  situacao: "ok" | "atencao" | "risco" | "sem_dado";
  fundo_registrado_snc: boolean | null;
  recebe_no_fundo: boolean;
  pnab_12m: number;
  favorecidos: Array<{ cnpj: string; nome: string | null; valor: number; fundo_de_cultura: boolean }>;
  snc: {
    situacao: string;
    data_publicacao: string | null;
    componentes: Array<{ nome: string; registrado: boolean; documento: string | null }>;
    lido_em: string | null;
  } | null;
  regra: string;
}

function data(iso?: string | null): string {
  if (!iso) return "—";
  const [a, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${a}`;
}

const cnpjFmt = (c: string) =>
  c.length === 14 ? `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}` : c;

const TITULO: Record<CulturaPnabResp["situacao"], { tom: "ok" | "atencao" | "critico" | "neutro"; texto: string }> = {
  ok: { tom: "ok", texto: "O PNAB já cai no fundo de cultura — apto para 2027" },
  atencao: { tom: "atencao", texto: "Lei do fundo registrada, mas o PNAB ainda não cai nele" },
  risco: { tom: "critico", texto: "Sem fundo de cultura à vista — o PNAB para em 2027" },
  sem_dado: { tom: "neutro", texto: "O Sistema Nacional de Cultura ainda não foi lido para este município" },
};

/** A situação resumida, para o ponto vermelho da aba. */
export function alertaCulturaPnab(d: CulturaPnabResp | null): boolean {
  return !!d && (d.situacao === "risco" || d.situacao === "atencao");
}

export function CulturaPnabAba({ dados }: { dados: CulturaPnabResp | null }) {
  if (!dados) return <Vazio>Não foi possível carregar a situação da cultura.</Vazio>;
  const t = TITULO[dados.situacao];
  return (
    <section className="space-y-2.5">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h2 className="bi-title text-[14px]">Cultura — PNAB 2027</h2>
        <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
          Sistema Nacional de Cultura{dados.snc?.lido_em ? `, lido em ${data(dados.snc.lido_em)}` : ""} ·
          Portal da Transparência (CGU), PNAB dos últimos 12 meses
        </span>
      </div>

      {t.tom === "neutro" ? (
        <Vazio>{t.texto}. Isto não significa que falta o fundo — significa que ainda não conferimos.</Vazio>
      ) : (
      <Aviso tom={t.tom} icon={Landmark} className="" titulo={t.texto}>
        <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{dados.regra}</p>
        {dados.situacao === "risco" && (
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O município não tem lei do fundo de cultura registrada no SNC e o PNAB não cai num fundo de
            cultura. Se a lei existir e só não estiver registrada, registrar no SNC resolve a evidência; se
            não existir, é preciso criá-la antes de 2027.
          </p>
        )}
        {dados.situacao === "atencao" && (
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O fundo existe no papel, mas o PNAB ainda cai em outra estrutura. Até 2026 isso é permitido
            (§ 7º); para 2027 o fundo precisa estar apto a receber — com CNPJ e conta próprios, conforme
            o regulamento.
          </p>
        )}
      </Aviso>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <Bloco className="p-4">
          <BlocoHead titulo="Sistema Nacional de Cultura"
                     sub={dados.snc
                       ? `Acordo: ${dados.snc.situacao}${dados.snc.data_publicacao ? ` (DOU de ${data(dados.snc.data_publicacao)})` : ""}`
                       : "ainda não lido"} />
          {dados.snc ? (
            <ul className="mt-2 space-y-1 text-[12px]">
              {dados.snc.componentes.map((c) => (
                <li key={c.nome} className="flex flex-wrap items-center gap-2">
                  <Selo tom={c.registrado ? "ok" : "neutro"}>{c.registrado ? "registrada" : "não registrada"}</Selo>
                  {c.documento
                    ? <a href={c.documento} target="_blank" rel="noreferrer" className="underline">{c.nome}</a>
                    : <span>{c.nome}</span>}
                </li>
              ))}
            </ul>
          ) : <Vazio>Sem leitura do SNC ainda.</Vazio>}
        </Bloco>

        <Bloco className="p-4">
          <BlocoHead titulo="Para onde o PNAB foi (12 meses)" sub={`total ${formatCurrency(dados.pnab_12m)}`} />
          {dados.favorecidos.length === 0 ? (
            <Vazio>Nenhum repasse do PNAB (ação 00UV) nos últimos 12 meses publicados pela CGU.</Vazio>
          ) : (
            <ul className="mt-2 space-y-1 text-[12px]">
              {dados.favorecidos.map((f) => (
                <li key={f.cnpj} className="flex flex-wrap items-center gap-2">
                  <Selo tom={f.fundo_de_cultura ? "ok" : "neutro"}>{f.fundo_de_cultura ? "fundo de cultura" : "outra estrutura"}</Selo>
                  <span>{f.nome || "—"}</span>
                  <span className="bi-id">{cnpjFmt(f.cnpj)}</span>
                  <span className="ml-auto">{formatCurrency(f.valor)}</span>
                </li>
              ))}
            </ul>
          )}
        </Bloco>
      </div>
    </section>
  );
}
