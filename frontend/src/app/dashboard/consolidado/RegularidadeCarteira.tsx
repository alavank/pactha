"use client";

/* CONSOLIDADO › REGULARIDADE — a regularidade da carteira (19/09/2026).
 *
 * Duas sub-abas, a pedido do dono ("faça aba pra colocar os que vencem em 30
 * dias"): SITUAÇÃO (CAUC e cadastro estadual, município a município) e VENCENDO
 * EM 30 DIAS (os documentos de regularidade que vão vencer).
 *
 * ⭐ CLIQUE ABRE A TELA DE REGULARIDADE DAQUELE MUNICÍPIO num modal grande — a
 * MESMA do menu (`components/regularidade/RegularidadeTela`), não uma cópia.
 * O documento vencendo abre direto na aba do cadastro dele.
 *
 * ⚠️ OS CARTÕES CONTAM MUNICÍPIOS ("12 de 42"). "Sem coleta" e "sem fonte no
 * estado" são escritos, nunca verdes.
 */

import React, { useEffect, useState } from "react";
import { AlertTriangle, FileSpreadsheet, FileWarning, Loader2, ShieldCheck } from "lucide-react";

import api from "@/lib/api";
import {
  Aviso, BOTAO_SEC, Bloco, BlocoHead, Campo, Campos, ESTILO_SEC, ItemLinha, Lista, Modal,
  ModalCorpo, ModalHead, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { RegularidadeTela } from "@/components/regularidade/RegularidadeTela";
import { baixarArquivo, mensagemDeErro } from "./baixar";

interface Linha {
  municipio_id: number; nome: string; uf: string;
  cauc: { regular: boolean | null; pendencias: number } | null;
  estadual: { cobertura: "coberto" | "sem_fonte" | "sem_coleta"; regular: boolean | null;
              pendencias: number; entidades_irregulares: number } | null;
  documentos: { n: number; proximo_dias: number | null };
}
interface Documento {
  municipio_id: number; municipio: string; entidade: string | null; esfera: string;
  codigo: string | null; label: string; validade: string; dias_restantes: number;
}
interface Resp {
  municipios_na_carteira: number;
  indisponivel: string[];
  municipios: Linha[];
  resumo: { cauc_irregulares: number; cauc_sem_dado: number; estadual_irregulares: number;
            com_documento_30: number };
  documentos: Documento[];
  documentos_total: number;
}
type Sub = "situacao" | "vencendo";

function campos(l: Linha): Campo[] {
  const c = l.cauc;
  const e = l.estadual;
  const d = l.documentos;
  return [
    { rotulo: "Federal (CAUC)",
      valor: !c || c.regular == null ? "sem coleta" : c.regular ? "em dia" : `${c.pendencias} pendência(s)`,
      tom: c?.regular === false ? "critico" : c?.regular ? "ok" : "normal" },
    { rotulo: "Estadual",
      valor: !e || e.cobertura === "sem_fonte" ? "sem fonte no estado"
        : e.cobertura === "sem_coleta" || e.regular == null ? "sem coleta"
        : e.regular ? "em dia"
        : `irregular${e.entidades_irregulares > 1 ? ` (${e.entidades_irregulares} entidades)` : ""}`,
      tom: e?.regular === false ? "critico" : e?.regular ? "ok" : "normal" },
    { rotulo: "Documento vencendo (30 dias)",
      valor: !d.n ? "nenhum" : `${d.n}${d.proximo_dias != null ? ` · ${d.proximo_dias === 0 ? "hoje" : `em ${d.proximo_dias}d`}` : ""}`,
      tom: d.proximo_dias != null && d.proximo_dias <= 7 ? "critico" : d.n ? "atencao" : "normal" },
  ];
}

function data(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleDateString("pt-BR");
}

export function RegularidadeCarteira() {
  const [d, setD] = useState<Resp | null>(null);
  const [erro, setErro] = useState(false);
  const [sub, setSub] = useState<Sub>("situacao");
  const [aberto, setAberto] = useState<{ id: number; nome: string; aba?: string } | null>(null);
  const [baixando, setBaixando] = useState(false);
  const [erroArquivo, setErroArquivo] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/consolidado/regularidade")
      .then((r) => { if (vivo) setD(r.data); })
      .catch(() => { if (vivo) setErro(true); });
    return () => { vivo = false; };
  }, []);

  if (erro) return <Vazio>Não foi possível montar a regularidade da carteira.</Vazio>;
  if (!d) {
    return (
      <div className="flex items-center gap-2 py-10 text-[12px]" style={{ color: "var(--bi-faint)" }}>
        <Loader2 className="size-4 animate-spin" /> lendo a regularidade de todos os municípios…
      </div>
    );
  }

  const n = d.municipios_na_carteira;
  const r = d.resumo;
  const baixar = async () => {
    setBaixando(true);
    setErroArquivo(null);
    try {
      await baixarArquivo("/consolidado/regularidade/exportar", "regularidade_da_carteira.xlsx");
    } catch (e) {
      setErroArquivo(mensagemDeErro(e));
    } finally {
      setBaixando(false);
    }
  };

  return (
    <div className="space-y-4">
      {d.indisponivel.length > 0 && (
        <Aviso tom="atencao" icon={AlertTriangle} className=""
               titulo={`Ficou de fora desta leitura: ${d.indisponivel.join(", ")}`}>
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O resto vale. A coluna desses blocos mostra &quot;sem coleta&quot; em vez de afirmar &quot;em dia&quot;.
          </p>
        </Aviso>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Numero icon={ShieldCheck} rotulo="Irregulares no CAUC (federal)"
                tom={r.cauc_irregulares ? "critico" : "neutro"} valor={`${r.cauc_irregulares} de ${n}`}
                sub={r.cauc_sem_dado ? `${r.cauc_sem_dado} sem coleta` : "municípios"} />
        <Numero icon={ShieldCheck} rotulo="Irregulares no cadastro estadual"
                tom={r.estadual_irregulares ? "critico" : "neutro"} valor={`${r.estadual_irregulares} de ${n}`}
                sub="prefeitura ou algum fundo irregular" />
        <Numero icon={FileWarning} rotulo="Com documento vencendo em 30 dias"
                tom={r.com_documento_30 ? "atencao" : "neutro"} valor={`${r.com_documento_30} de ${n}`}
                sub={`${d.documentos_total} documento(s) na carteira`}
                onClick={() => setSub("vencendo")} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="inline-flex rounded-full p-1" role="tablist"
             style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}>
          {([["situacao", "Situação por município"], ["vencendo", `Vencendo em 30 dias (${d.documentos_total})`]] as const)
            .map(([v, rotulo]) => (
              <button key={v} type="button" role="tab" aria-selected={sub === v} onClick={() => setSub(v)}
                      className="rounded-full px-4 py-1.5 text-[13px] font-semibold transition-colors"
                      style={sub === v ? { background: "var(--bi-surface)", color: "var(--bi-text)",
                                           boxShadow: "0 1px 2px rgba(0,0,0,.08)" }
                                       : { color: "var(--bi-muted)" }}>
                {rotulo}
              </button>
            ))}
        </div>
        <span className="flex items-center gap-2">
          {erroArquivo && <span className="text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>{erroArquivo}</span>}
          <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={baixar} disabled={baixando}>
            {baixando ? <Loader2 className="size-3.5 animate-spin" /> : <FileSpreadsheet className="size-3.5" />}
            Planilha
          </button>
        </span>
      </div>

      {sub === "situacao" ? (
        <Bloco className="p-3">
          <BlocoHead icon={ShieldCheck} titulo="Município a município"
                     sub="irregulares primeiro · clique para abrir a tela de Regularidade do município" />
          <Lista>
            {d.municipios.map((l) => (
              <ItemLinha key={l.municipio_id}
                onClick={() => setAberto({ id: l.municipio_id, nome: l.nome })}
                titulo={<span className="flex items-center gap-2">{l.nome} {l.uf && <Selo>{l.uf}</Selo>}</span>}>
                <Campos campos={campos(l)} cols={3} />
              </ItemLinha>
            ))}
          </Lista>
        </Bloco>
      ) : (
        <Bloco className="p-3">
          <BlocoHead icon={FileWarning} titulo="Documentos de regularidade vencendo em 30 dias"
                     sub="CAUC e cadastro estadual · do mais próximo · clique para abrir o cadastro do município" />
          {d.documentos.length === 0 ? <Vazio>Nenhum documento vence nos próximos 30 dias.</Vazio> : (
            <Lista>
              {d.documentos.map((x, i) => (
                <ItemLinha key={i}
                  onClick={() => setAberto({ id: x.municipio_id, nome: x.municipio,
                                             aba: x.esfera === "CAUC" ? "cauc" : "estadual" })}
                  titulo={x.label}
                  valor={<Selo tom={x.dias_restantes <= 7 ? "critico" : "atencao"}>
                    {x.dias_restantes === 0 ? "vence hoje" : `${x.dias_restantes} dias`}</Selo>}
                  meta={<>
                    <span className="font-medium" style={{ color: "var(--bi-text)" }}>{x.municipio}</span>
                    {x.entidade && <span>· {x.entidade}</span>}
                    <span>· {x.esfera}</span>
                    <span>· até {data(x.validade)}</span>
                  </>} />
              ))}
            </Lista>
          )}
          {d.documentos_total > d.documentos.length && (
            <p className="mt-2 px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
              Mostrando os {d.documentos.length} mais próximos de {d.documentos_total}. A planilha traz todos.
            </p>
          )}
        </Bloco>
      )}

      {aberto && (
        <Modal aberto onFechar={() => setAberto(null)} maxW="max-w-6xl">
          <ModalHead titulo={`Regularidade — ${aberto.nome}`}
                     sub="a mesma tela do menu Regularidade, para este município"
                     onFechar={() => setAberto(null)} />
          <ModalCorpo>
            <RegularidadeTela key={`${aberto.id}:${aberto.aba ?? ""}`} municipioId={String(aberto.id)}
                              embutido abaInicial={aberto.aba} />
          </ModalCorpo>
        </Modal>
      )}
    </div>
  );
}
