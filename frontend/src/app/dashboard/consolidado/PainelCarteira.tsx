"use client";

/* CONSOLIDADO › PAINEL DA CARTEIRA — a home da área (PR 2, 18/09/2026).
 *
 * Uma linha por município com o que muda a semana da assessoria: regularidade
 * federal e estadual, convênio vencendo, documento vencendo, emenda federal sem
 * pagamento e Radar. Cada bloco é a conta de uma tela que já existe
 * (`backend/services/consolidado_painel.py`).
 *
 * ⚠️ OS CARTÕES CONTAM MUNICÍPIOS, NÃO SOMAM DINHEIRO. "3 municípios com
 * convênio vencendo" é informação da carteira; "R$ X da carteira" seria o número
 * que se lê como de um cliente — o risco de 05/08/2026.
 *
 * ⚠️ "SEM COLETA" E "SEM FONTE" NÃO SÃO VERDE. Falta de dado aparece escrita.
 */

import React, { useEffect, useState } from "react";
import {
  AlertTriangle, BadgeCheck, CalendarClock, FileSpreadsheet, FileWarning, Landmark, Loader2, Radar,
  ShieldCheck,
} from "lucide-react";

import api from "@/lib/api";
import { formatCurrencyShort } from "@/lib/bi-format";
import {
  Aviso, BOTAO_SEC, Bloco, BlocoHead, Campo, Campos, ESTILO_SEC, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { baixarArquivo, mensagemDeErro } from "./baixar";

type Tom = "normal" | "ok" | "atencao" | "critico";
interface Janela { n: number; proximo_dias: number | null }
interface Linha {
  municipio_id: number; nome: string; uf: string;
  cauc: { regular: boolean | null; pendencias: number } | null;
  estadual: { cobertura: "coberto" | "sem_fonte" | "sem_coleta"; regular: boolean | null;
              pendencias: number; entidades_irregulares: number } | null;
  vencimentos: Janela;
  documentos: Janela;
  /** `estado` é o da carteira CGU (services/coleta.classificar_emendas_federais). */
  emendas: { n: number; sem_pagamento: number; nao_consultadas: number; estado: string | null } | null;
  radar: { abertos: number; nomeado: number; indicado: number; proximo_dias: number | null } | null;
}
interface Resp {
  municipios_na_carteira: number;
  indisponivel: string[];
  municipios: Linha[];
  resumo: Record<string, number>;
  vencimentos: { municipio: string; esfera: string; numero: string | null; objeto: string | null;
                 orgao: string | null; fim: string | null; dias: number; situacao: string | null }[];
  vencimentos_total: number;
  documentos: { municipio: string; entidade: string | null; esfera: string; label: string;
                validade: string; dias_restantes: number }[];
  documentos_total: number;
  radar: { municipio: string; programa: string; beneficiario: boolean; dias: number | null;
           indicacoes: { parlamentar: string | null; solicitante: string | null; valor: number | null }[] }[];
  radar_total: number;
}

const BLOCO_NOME: Record<string, string> = {
  cauc: "regularidade federal", estadual: "regularidade estadual",
  vencimentos: "vencimentos", documentos: "documentos", emendas: "emendas federais",
  radar: "Radar",
};

function prazo(j: Janela, vazio: string): { valor: string; tom: Tom } {
  if (!j.n) return { valor: vazio, tom: "normal" };
  const d = j.proximo_dias;
  return {
    valor: `${j.n}${d != null ? ` · ${d === 0 ? "hoje" : `em ${d}d`}` : ""}`,
    tom: d != null && d <= 7 ? "critico" : d != null && d <= 30 ? "atencao" : "normal",
  };
}

function campos(l: Linha): Campo[] {
  const c = l.cauc;
  const e = l.estadual;
  const v = prazo(l.vencimentos, "nenhum em 90 dias");
  const d = prazo(l.documentos, "nenhum em 30 dias");
  return [
    { rotulo: "Federal (CAUC)",
      valor: !c || c.regular == null ? "sem coleta" : c.regular ? "em dia" : `${c.pendencias} pendência(s)`,
      tom: c?.regular === false ? "critico" : c?.regular ? "ok" : "normal" },
    { rotulo: "Estadual",
      valor: !e || e.cobertura === "sem_fonte" ? "sem fonte no estado"
        : e.cobertura === "sem_coleta" || e.regular == null ? "sem coleta"
        : e.regular ? "em dia" : `irregular${e.pendencias ? ` (${e.pendencias})` : ""}`,
      tom: e?.regular === false ? "critico" : e?.regular ? "ok" : "normal" },
    { rotulo: "Convênio vencendo", valor: v.valor, tom: v.tom },
    { rotulo: "Documento vencendo", valor: d.valor, tom: d.tom },
    { rotulo: "Emenda sem pagamento",
      /* Zero emenda só é "sem emenda" quando a carteira foi coletada: sem coleta
         ou sem CNPJ, o zero é falta de dado, e a célula diz isso. */
      valor: !l.emendas ? "—" : l.emendas.sem_pagamento
        ? `${l.emendas.sem_pagamento} de ${l.emendas.n}` : l.emendas.n ? "nenhuma"
        : l.emendas.estado === "sem_coleta" ? "sem coleta"
        : l.emendas.estado === "sem_cnpj" ? "sem CNPJ cadastrado" : "sem emenda",
      tom: l.emendas?.sem_pagamento ? "atencao" : "normal" },
    { rotulo: "Radar",
      valor: !l.radar ? "sem UF cadastrada"
        : `${l.radar.abertos} aberto(s)${l.radar.nomeado ? ` · ${l.radar.nomeado} nomeado` : ""}`
          + (l.radar.indicado ? ` · ${l.radar.indicado} indicado` : ""),
      tom: l.radar && (l.radar.nomeado || l.radar.indicado) ? "ok" : "normal" },
  ];
}

function data(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleDateString("pt-BR");
}

export function PainelCarteira() {
  const [d, setD] = useState<Resp | null>(null);
  const [erro, setErro] = useState(false);
  const [baixando, setBaixando] = useState(false);
  const [erroArquivo, setErroArquivo] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/consolidado/painel")
      .then((r) => { if (vivo) setD(r.data); })
      .catch(() => { if (vivo) setErro(true); });
    return () => { vivo = false; };
  }, []);

  if (erro) return <Vazio>Não foi possível montar o painel da carteira.</Vazio>;
  if (!d) {
    return (
      <div className="flex items-center gap-2 py-10 text-[12px]" style={{ color: "var(--bi-faint)" }}>
        <Loader2 className="size-4 animate-spin" /> montando o painel da carteira… (varre todos os municípios)
      </div>
    );
  }

  const n = d.municipios_na_carteira;
  const r = d.resumo;
  const baixar = async () => {
    setBaixando(true);
    setErroArquivo(null);
    try {
      await baixarArquivo("/consolidado/painel/exportar", "painel_da_carteira.xlsx");
    } catch (e) {
      setErroArquivo(mensagemDeErro(e));
    } finally {
      setBaixando(false);
    }
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-end gap-2">
        {erroArquivo && <span className="text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>{erroArquivo}</span>}
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={baixar} disabled={baixando}
                title="Uma aba por bloco, com as listas inteiras">
          {baixando ? <Loader2 className="size-3.5 animate-spin" /> : <FileSpreadsheet className="size-3.5" />}
          Planilha do painel
        </button>
      </div>
      {d.indisponivel.length > 0 && (
        <Aviso tom="atencao" icon={AlertTriangle} className=""
               titulo={`Ficou de fora desta leitura: ${d.indisponivel.map((b) => BLOCO_NOME[b] ?? b).join(", ")}`}>
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            O resto do painel vale. A coluna desses blocos mostra &quot;—&quot; em vez de zero.
          </p>
        </Aviso>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Numero icon={ShieldCheck} rotulo="Irregulares no CAUC"
                tom={r.cauc_irregulares ? "critico" : "neutro"}
                valor={`${r.cauc_irregulares} de ${n}`}
                sub={r.cauc_sem_dado ? `${r.cauc_sem_dado} sem coleta` : "municípios"} />
        <Numero icon={ShieldCheck} rotulo="Irregulares no estadual"
                tom={r.estadual_irregulares ? "critico" : "neutro"}
                valor={`${r.estadual_irregulares} de ${n}`} sub="alguma entidade irregular" />
        <Numero icon={CalendarClock} rotulo="Convênio vencendo em 30 dias"
                tom={r.com_vencimento_30 ? "atencao" : "neutro"}
                valor={`${r.com_vencimento_30} de ${n}`} sub="municípios" />
        <Numero icon={Landmark} rotulo="Com emenda sem pagamento"
                tom={r.com_sem_pagamento ? "atencao" : "neutro"}
                valor={`${r.com_sem_pagamento} de ${n}`} sub="empenhada e nada pago" />
        <Numero icon={Radar} rotulo="Nomeados ou indicados no Radar"
                tom={r.com_radar_nomeado ? "acento" : "neutro"}
                valor={`${r.com_radar_nomeado} de ${n}`} sub="com programa aberto" />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={BadgeCheck} titulo="Município a município"
                   sub="quem pede atenção primeiro: irregularidade, prazo curto, dinheiro parado" />
        <Lista>
          {d.municipios.map((l) => (
            <ItemLinha key={l.municipio_id}
              titulo={<span className="flex items-center gap-2">{l.nome} {l.uf && <Selo>{l.uf}</Selo>}</span>}>
              <Campos campos={campos(l)} cols={6} />
            </ItemLinha>
          ))}
        </Lista>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={CalendarClock} titulo="Convênios que vencem nos próximos 90 dias"
                   sub={`${d.vencimentos_total} na carteira · do mais próximo para o mais distante`} />
        {d.vencimentos.length === 0 ? <Vazio>Nenhum convênio vence nos próximos 90 dias.</Vazio> : (
          <Lista>
            {d.vencimentos.map((v, i) => (
              <ItemLinha key={i}
                titulo={v.objeto || "Sem objeto publicado"}
                valor={<Selo tom={v.dias <= 7 ? "critico" : v.dias <= 30 ? "atencao" : "neutro"}>
                  {v.dias === 0 ? "vence hoje" : `${v.dias} dias`}</Selo>}
                meta={<>
                  <span className="font-medium" style={{ color: "var(--bi-text)" }}>{v.municipio}</span>
                  <span>· {v.esfera === "voluntaria" ? "federal (voluntária)" : v.esfera}</span>
                  {v.numero && <span>· {v.numero}</span>}
                  {v.orgao && <span>· {v.orgao}</span>}
                  <span>· até {data(v.fim)}</span>
                </>} />
            ))}
          </Lista>
        )}
        {d.vencimentos_total > d.vencimentos.length && (
          <p className="mt-2 px-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            Mostrando os {d.vencimentos.length} mais próximos de {d.vencimentos_total}.
          </p>
        )}
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={FileWarning} titulo="Documentos de regularidade vencendo em 30 dias"
                   sub={`${d.documentos_total} na carteira · CAUC e cadastro estadual`} />
        {d.documentos.length === 0 ? <Vazio>Nenhum documento vence nos próximos 30 dias.</Vazio> : (
          <Lista>
            {d.documentos.map((x, i) => (
              <ItemLinha key={i}
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
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Radar} titulo="Onde a carteira está nomeada ou indicada no Radar"
                   sub={`${d.radar_total} programa(s) aberto(s) · pelo prazo mais curto`} />
        {d.radar.length === 0 ? (
          <Vazio>Nenhum município da carteira está nomeado ou com emenda indicada em programa aberto.</Vazio>
        ) : (
          <Lista>
            {d.radar.map((x, i) => (
              <ItemLinha key={i}
                titulo={x.programa}
                valor={x.dias != null ? <Selo tom={x.dias <= 7 ? "critico" : x.dias <= 30 ? "atencao" : "neutro"}>
                  {x.dias === 0 ? "fecha hoje" : `${x.dias} dias`}</Selo> : "—"}
                meta={<>
                  <span className="font-medium" style={{ color: "var(--bi-text)" }}>{x.municipio}</span>
                  {x.beneficiario && <Selo tom="acento">município nomeado</Selo>}
                  {x.indicacoes.map((ind, k) => (
                    <span key={k}>
                      · emenda de {ind.parlamentar || "—"}
                      {ind.solicitante && ind.solicitante !== ind.parlamentar ? ` (a pedido de ${ind.solicitante})` : ""}
                      {ind.valor != null ? ` · ${formatCurrencyShort(ind.valor)}` : ""}
                    </span>
                  ))}
                </>} />
            ))}
          </Lista>
        )}
      </Bloco>
    </div>
  );
}
