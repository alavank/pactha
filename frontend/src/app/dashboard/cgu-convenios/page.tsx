"use client";

/* DEFESA CIVIL E OUTROS REPASSES (CGU) — o dinheiro federal fora do Transferegov.
 *
 * As outras telas de FEDERAIS contam o que passou pelo Transferegov. Esta conta o
 * que NÃO passou: as transferências legais da Defesa Civil (ações de resposta e
 * recuperação, Lei 12.340) e o histórico anterior a 2009, pela planilha de
 * convênios do Portal da Transparência (CGU). Medido em 22/09/2026: Nova Palma
 * com 8 repasses vigentes só aqui, R$ 22,9 mi — um de R$ 14,4 mi ainda sem nada
 * liberado.
 *
 * ⚠️ ABRE PELO QUE PEDE AÇÃO: vigente e fora do Transferegov, com quanto ainda
 * falta liberar. O resto (também no Transferegov, encerrados, e o que não é da
 * prefeitura) vem recolhido — é conferência, não pauta.
 *
 * ⚠️ OS NÚMEROS DO TOPO SÃO SÓ DA PREFEITURA. Hospital, APAE e a UFSM ficam no
 * grupo próprio e fora das contas (regra do dono: nada é descartado, nada entra
 * na conta como se fosse da prefeitura).
 */

import React, { useEffect, useState } from "react";
import { ChevronDown, Landmark, Loader2, ShieldAlert, Wallet } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Numero, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import { formatCurrency } from "@/lib/utils";

interface Item {
  numero: string;
  numero_original: string | null;
  numero_processo: string | null;
  situacao: string | null;
  objeto: string | null;
  orgao_superior: string | null;
  orgao_concedente: string | null;
  convenente_nome: string | null;
  tipo_convenente: string | null;
  municipal: boolean;
  tipo_instrumento: string | null;
  valor: number | null;
  valor_liberado: number | null;
  a_liberar: number | null;
  data_inicio_vigencia: string | null;
  data_final_vigencia: string | null;
  data_ultima_liberacao: string | null;
  valor_ultima_liberacao: number | null;
  no_transferegov: boolean | null;
  vigente: boolean;
  n_ob: number;
  grupo: "vigentes_so_cgu" | "vigentes_no_transferegov" | "encerrados" | "outros_convenentes";
}
interface Resp {
  coletado: boolean;
  arquivo?: string | null;
  carregado_em?: string | null;
  sem_conferencia?: number;
  resumo?: { vigentes_so_cgu: number; valor: number; liberado: number; a_liberar: number };
  itens?: Item[];
}
interface Ob { ordem_bancaria: string; data_emissao: string | null; valor: number | null }

/* Data pura (DATE do banco), lida como DIA — sem o fuso deslocar para a véspera. */
function dia(iso?: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleDateString("pt-BR");
}
const moeda = (v: number | null | undefined) => (v == null ? "—" : formatCurrency(v));

/* "TRANSFERENCIA LEGAL" do MIDR é o repasse da Defesa Civil; o nome técnico não
   diz nada ao gestor. Os outros tipos vão como a CGU escreve, em minúsculas. */
function tipoLegivel(i: Item): string {
  const t = (i.tipo_instrumento || "").toUpperCase();
  if (t === "TRANSFERENCIA LEGAL" && /INTEGRA/i.test(i.orgao_concedente || i.orgao_superior || ""))
    return "Defesa Civil";
  if (t === "TRANSFERENCIA LEGAL") return "transferência legal";
  return (i.tipo_instrumento || "instrumento").toLowerCase();
}

export default function CguConveniosPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<{ chave: string; r: Resp | null; erro: boolean } | null>(null);

  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api.get<Resp>("/cgu-convenios", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setD({ chave: municipioId, r: r.data, erro: false }); })
      .catch(() => { if (vivo) setD({ chave: municipioId, r: null, erro: true }); });
    return () => { vivo = false; };
  }, [municipioId]);

  if (!municipioId) {
    return <Vazio>Escolha um município no seletor para ver os repasses federais publicados pela CGU.</Vazio>;
  }
  if (!d || d.chave !== municipioId) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (d.erro || !d.r) return <Vazio>Não foi possível carregar os repasses da CGU.</Vazio>;
  const r = d.r;

  const cabecalho = (
    <div>
      <TituloTela>Defesa Civil e outros repasses (CGU)</TituloTela>
      <p className="text-sm text-muted-foreground">
        O dinheiro federal que não passa pelo Transferegov: os repasses da Defesa Civil e os
        convênios anteriores a 2009
      </p>
    </div>
  );
  if (!r.coletado) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <Vazio>
          A planilha da CGU ainda não foi carregada para este município. Isto não significa
          que não haja repasse fora do Transferegov — significa que ainda não conferimos.
        </Vazio>
      </div>
    );
  }

  const itens = r.itens || [];
  const grupo = (g: Item["grupo"]) => itens.filter((i) => i.grupo === g);
  const so = grupo("vigentes_so_cgu");
  const res = r.resumo!;

  return (
    <div className="space-y-4">
      {cabecalho}
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        Portal da Transparência (CGU) · planilha de {dia(r.arquivo)} — a CGU não publica todo
        dia · “fora do Transferegov” = o número não está no dado aberto do Transferegov
        {r.sem_conferencia ? ` · ${r.sem_conferencia} instrumento(s) sem essa conferência nesta carga` : ""}
      </p>

      <div className="grid gap-3 sm:grid-cols-3">
        <Numero icon={ShieldAlert} rotulo="Vigentes fora do Transferegov" tom="acento"
                valor={String(res.vigentes_so_cgu)}
                sub="da prefeitura, com vigência em curso" />
        <Numero icon={Landmark} rotulo="Valor desses repasses" valor={moeda(res.valor)}
                sub={`${moeda(res.liberado)} já liberado`} />
        <Numero icon={Wallet} rotulo="Ainda a liberar"
                tom={res.a_liberar > 0 ? "atencao" : "neutro"}
                valor={moeda(res.a_liberar)}
                sub="o que a União ainda não pagou" />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={ShieldAlert} titulo="Vigentes fora do Transferegov"
                   sub="da prefeitura · do maior valor para o menor · clique para ver as ordens bancárias" />
        {so.length === 0 ? (
          <Vazio>Nenhum repasse vigente da prefeitura fora do Transferegov nesta planilha.</Vazio>
        ) : (
          <ListaItens itens={[...so].sort((a, b) => (b.valor || 0) - (a.valor || 0))}
                      municipioId={municipioId} />
        )}
      </Bloco>

      <GrupoRecolhido titulo="Vigentes que também estão no Transferegov"
                      sub="para conferir as duas fontes lado a lado"
                      itens={grupo("vigentes_no_transferegov")} municipioId={municipioId} />
      <GrupoRecolhido titulo="Encerrados e histórico"
                      sub="vigência vencida — inclui os convênios anteriores ao SICONV"
                      itens={grupo("encerrados")} municipioId={municipioId} />
      <GrupoRecolhido titulo="Outros convenentes no município"
                      sub="hospital, APAE, universidade… — não é a prefeitura e fica fora das contas acima"
                      itens={grupo("outros_convenentes")} municipioId={municipioId} />
    </div>
  );
}

function GrupoRecolhido({ titulo, sub, itens, municipioId }: {
  titulo: string; sub: string; itens: Item[]; municipioId: string;
}) {
  const [aberto, setAberto] = useState(false);
  if (itens.length === 0) return null;
  return (
    <Bloco className="p-3">
      <button type="button" className="w-full text-left" onClick={() => setAberto(!aberto)}
              aria-expanded={aberto}>
        <BlocoHead titulo={`${titulo} · ${itens.length}`} sub={sub}
                   right={<ChevronDown className={`size-4 transition-transform ${aberto ? "rotate-180" : ""}`} />} />
      </button>
      {aberto && <ListaItens itens={itens} municipioId={municipioId} />}
    </Bloco>
  );
}

function ListaItens({ itens, municipioId }: { itens: Item[]; municipioId: string }) {
  const [aberto, setAberto] = useState<string | null>(null);
  return (
    <Lista>
      {itens.map((i) => {
        const chave = `${i.numero}|${i.convenente_nome}`;
        return (
          <ItemLinha
            key={chave}
            onClick={i.n_ob > 0 ? () => setAberto(aberto === chave ? null : chave) : undefined}
            expandido={i.n_ob > 0 ? aberto === chave : undefined}
            titulo={
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>{i.objeto || "Sem objeto informado"}</span>
                <Selo tom={tipoLegivel(i) === "Defesa Civil" ? "acento" : "neutro"}>{tipoLegivel(i)}</Selo>
                {i.situacao && <Selo tom={situacaoTom(i.situacao)}>{i.situacao.toLowerCase()}</Selo>}
                {!i.municipal && <Selo>não é a prefeitura</Selo>}
              </span>
            }
            valor={moeda(i.valor)}
            meta={
              <>
                {i.orgao_concedente && <span>{i.orgao_concedente}</span>}
                <span className="font-mono">· nº {i.numero}</span>
                {i.numero_processo && <span>· processo {i.numero_processo}</span>}
                {!i.municipal && i.convenente_nome && <span>· {i.convenente_nome}</span>}
              </>
            }
          >
            <Campos campos={[
              { rotulo: "Liberado", valor: moeda(i.valor_liberado) },
              { rotulo: "A liberar", valor: moeda(i.a_liberar),
                tom: i.vigente && (i.a_liberar || 0) > 0 ? "atencao" : "neutro" },
              { rotulo: "Vigência", valor: `${dia(i.data_inicio_vigencia)} a ${dia(i.data_final_vigencia)}` },
              { rotulo: "Última liberação", valor: i.data_ultima_liberacao
                  ? `${dia(i.data_ultima_liberacao)} · ${moeda(i.valor_ultima_liberacao)}` : "—" },
            ]} />
            {aberto === chave && <OrdensBancarias numero={i.numero} municipioId={municipioId} />}
          </ItemLinha>
        );
      })}
    </Lista>
  );
}

function OrdensBancarias({ numero, municipioId }: { numero: string; municipioId: string }) {
  const [obs, setObs] = useState<Ob[] | null>(null);
  const [erro, setErro] = useState(false);
  useEffect(() => {
    let vivo = true;
    api.get<{ itens: Ob[] }>("/cgu-convenios/ordens-bancarias",
      { params: { municipio_id: municipioId, numero } })
      .then((r) => { if (vivo) setObs(r.data.itens); })
      .catch(() => { if (vivo) setErro(true); });
    return () => { vivo = false; };
  }, [numero, municipioId]);
  if (erro) return <p className="mt-2 text-[11px]" style={{ color: "var(--bi-crit-ink)" }}>Não foi possível carregar as ordens bancárias.</p>;
  if (!obs) return <p className="mt-2 text-[11px]" style={{ color: "var(--bi-faint)" }}>carregando ordens bancárias…</p>;
  return (
    <div className="mt-2 rounded px-2 py-1.5" style={{ background: "var(--bi-surface-2)" }}>
      <p className="mb-1 text-[10px] uppercase" style={{ color: "var(--bi-faint)" }}>
        Ordens bancárias · {obs.length}
      </p>
      <ul className="space-y-0.5">
        {obs.map((o, k) => (
          <li key={`${o.ordem_bancaria}-${k}`} className="flex justify-between gap-3 text-[11px]"
              style={{ color: "var(--bi-muted)" }}>
            <span>{dia(o.data_emissao)} · <span className="font-mono">{o.ordem_bancaria}</span></span>
            <span className="bi-num">{moeda(o.valor)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
