"use client";

/* RECURSOS RECEBIDOS POR PASTA — todo o dinheiro que a União transferiu ao
 * município e aos fundos dele, mês a mês, pelo arquivo de transferências do
 * Portal da Transparência (CGU): FPM, FUNDEB, o fundo a fundo da saúde, FNDE,
 * FNAS, PNAB, Defesa Civil, royalties.
 *
 * As telas vizinhas de FEDERAIS contam INSTRUMENTO (plano, convênio, emenda);
 * esta conta o DINHEIRO que entrou — inclusive o que não tem instrumento nenhum.
 *
 * ⚠️ A CONTA É DO BACKEND (`routers/cgu_transferencias.py::montar`, com a regra de
 * `services/transferencias_pasta.py`). Esta tela só desenha: nada é somado aqui,
 * para o mesmo dado não dar duas contas.
 *
 * ⚠️ O MÊS CORRENTE É PARCIAL e as constitucionais (FPM, FUNDEB, ITR, royalties)
 * só entram depois que o mês fecha — a tela diz isso em vez de mostrar "FPM zero".
 *
 * ⚠️ O TOTAL É DO MUNICÍPIO (prefeitura, fundos, secretarias). Escolas (caixa
 * escolar, APM — pode ser de escola estadual) e entidades aparecem em «Quem
 * recebeu», fora da conta, a menos que se escolha «Todos os favorecidos».
 */

import React, { useEffect, useMemo, useState } from "react";
import { CalendarRange, Info, Landmark, Loader2, PiggyBank, Users } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Abas, Aviso, Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";
import { formatCurrency } from "@/lib/utils";

type Quem = "municipio" | "todos";
type Periodo = "6" | "12" | "24";

interface MesSerie {
  mes: string;
  coletado: boolean;
  parcial: boolean;
  sem_constitucionais: boolean;
  total: number;
  por_pasta: Record<string, number>;
}
interface Detalhe {
  pasta: string;
  orgao: string | null;
  acao_codigo: string | null;
  acao: string | null;
  linguagem_cidada: string | null;
  favorecido_doc: string | null;
  favorecido: string | null;
  grupo: string;
  total: number;
  meses: number;
}
interface Resp {
  coletado: boolean;
  quem?: Quem;
  periodo?: { de: string; ate: string; meses: number };
  mes_corrente?: string;
  mes_detalhe?: string | null;
  total?: number;
  pastas?: Array<{ chave: string; rotulo: string; total: number }>;
  por_grupo?: Array<{ grupo: string; rotulo: string; total: number; favorecidos: number; na_conta: boolean }>;
  serie?: MesSerie[];
  detalhe?: Detalhe[];
  atualizado_em?: string;
  siafi?: { codigo: string | null; origem: string | null };
  rotulos?: { pastas: Record<string, string>; grupos: Record<string, string> };
}

const moeda = (v: number | null | undefined) => (v == null ? "—" : formatCurrency(v));
const MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
/* "2026-08" -> "ago/26" (curto, para o eixo) e "agosto de 2026" não: o eixo é curto. */
function mesCurto(iso: string): string {
  const [a, m] = iso.split("-");
  return `${MESES_PT[Number(m) - 1]}/${a.slice(2)}`;
}
function dataHora(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
}

export default function RecursosPorPastaPage() {
  const { municipioId } = useMunicipio();
  const [periodo, setPeriodo] = useState<Periodo>("12");
  const [quem, setQuem] = useState<Quem>("municipio");
  // O mês escolhido vale para ESTE município e ESTE período: trocar qualquer um
  // dos dois desfaz a escolha (o mês poderia cair fora da janela). Derivado, e
  // não um efeito que zera o estado — que redesenharia a tela duas vezes.
  const base = `${municipioId}|${periodo}`;
  const [mesSel, setMesSel] = useState<{ base: string; mes: string } | null>(null);
  const mes = mesSel && mesSel.base === base ? mesSel.mes : null;
  const setMes = (m: string | null) => setMesSel(m ? { base, mes: m } : null);
  const [pastaSel, setPastaSel] = useState<string | null>(null);
  const [d, setD] = useState<{ chave: string; r: Resp | null; erro: boolean } | null>(null);

  const chave = `${base}|${quem}|${mes ?? ""}`;
  useEffect(() => {
    if (!municipioId) return;
    let vivo = true;
    api.get<Resp>("/cgu-transferencias", {
      params: { municipio_id: municipioId, meses: Number(periodo), quem, ...(mes ? { mes } : {}) },
    })
      .then((r) => { if (vivo) setD({ chave, r: r.data, erro: false }); })
      .catch(() => { if (vivo) setD({ chave, r: null, erro: true }); });
    return () => { vivo = false; };
  }, [municipioId, periodo, quem, mes, chave]);

  const cabecalho = (
    <div>
      <TituloTela>Recursos recebidos por pasta</TituloTela>
      <p className="text-sm text-muted-foreground">
        Todo o dinheiro que a União transferiu ao município e aos fundos dele, mês a mês —
        FPM, FUNDEB, saúde, educação, assistência social, cultura, defesa civil e royalties
      </p>
    </div>
  );

  if (!municipioId) {
    return <Vazio>Escolha um município no seletor para ver os recursos recebidos.</Vazio>;
  }
  if (!d || d.chave !== chave) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> carregando…
        </div>
      </div>
    );
  }
  if (d.erro || !d.r) {
    return <div className="space-y-4">{cabecalho}<Vazio>Não foi possível carregar os recursos recebidos.</Vazio></div>;
  }
  const r = d.r;
  if (!r.coletado) {
    return (
      <div className="space-y-4">
        {cabecalho}
        <Vazio>
          O arquivo de transferências da CGU ainda não foi carregado para este município. Isto
          não significa que ele não recebeu nada — significa que ainda não conferimos.
        </Vazio>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {cabecalho}
      <Conteudo r={r} periodo={periodo} setPeriodo={setPeriodo} quem={quem} setQuem={setQuem}
                mes={mes} setMes={setMes} pastaSel={pastaSel} setPastaSel={setPastaSel} />
    </div>
  );
}

function Conteudo({ r, periodo, setPeriodo, quem, setQuem, mes, setMes, pastaSel, setPastaSel }: {
  r: Resp;
  periodo: Periodo; setPeriodo: (p: Periodo) => void;
  quem: Quem; setQuem: (q: Quem) => void;
  mes: string | null; setMes: (m: string | null) => void;
  pastaSel: string | null; setPastaSel: (p: string | null) => void;
}) {
  const serie = r.serie || [];
  const pastas = r.pastas || [];
  const rotuloPasta = (k: string) => r.rotulos?.pastas[k] || k;
  const corrente = serie.find((s) => s.mes === r.mes_corrente);
  // Mês FECHADO que veio sem nenhuma constitucional: o FPM daquele mês ainda não saiu.
  const fechadosSemConst = serie.filter((s) => s.coletado && !s.parcial && s.sem_constitucionais);
  const fechados = serie.filter((s) => s.coletado && !s.parcial);
  const media = fechados.length ? fechados.reduce((a, s) => a + s.total, 0) / fechados.length : null;
  const ultimoFechado = fechados.length ? fechados[fechados.length - 1] : null;
  const fora = (r.por_grupo || []).filter((g) => !g.na_conta);
  const valorDaBarra = (s: MesSerie) => (pastaSel ? s.por_pasta[pastaSel] || 0 : s.total);
  const maxBarra = Math.max(1, ...serie.map(valorDaBarra));

  const detalhe = useMemo(
    () => (r.detalhe || []).filter((x) => !pastaSel || x.pasta === pastaSel),
    [r.detalhe, pastaSel],
  );

  return (
    <>
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        Portal da Transparência (CGU) · arquivo de transferências, atualizado todo dia pela CGU ·
        carregado em {dataHora(r.atualizado_em)}
        {r.siafi?.codigo ? ` · município pelo código SIAFI ${r.siafi.codigo}` : ""}
      </p>

      <Aviso tom="atencao" icon={Info} className="" titulo={
        corrente
          ? `${mesCurto(corrente.mes)} é o mês corrente e está PARCIAL: a CGU atualiza o arquivo todo dia.`
          : "O mês corrente é sempre parcial: a CGU atualiza o arquivo todo dia."
      }>
        <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
          FPM, FUNDEB, ITR e royalties (as transferências constitucionais) só entram no arquivo
          depois que o mês fecha — por isso o mês corrente aparece sem eles.
          {fechadosSemConst.length > 0 && (
            <> {fechadosSemConst.map((s) => mesCurto(s.mes)).join(", ")} já fechou e ainda veio
              sem as constitucionais: a CGU ainda não as publicou.</>
          )}
        </p>
      </Aviso>

      <div className="flex flex-wrap items-center gap-2">
        <Abas<Periodo> valor={periodo} onChange={setPeriodo} opcoes={[
          { valor: "6", label: "6 meses" }, { valor: "12", label: "12 meses" },
          { valor: "24", label: "24 meses" },
        ]} />
        <Abas<Quem> valor={quem} onChange={setQuem} opcoes={[
          { valor: "municipio", label: "Prefeitura e fundos" },
          { valor: "todos", label: "Todos os favorecidos" },
        ]} />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Numero icon={PiggyBank} tom="acento" rotulo={`Recebido em ${r.periodo?.meses} meses`}
                valor={moeda(r.total)}
                sub={`${mesCurto(r.periodo!.de)} a ${mesCurto(r.periodo!.ate)} · ${
                  quem === "municipio" ? "prefeitura, fundos e secretarias" : "todos os favorecidos"}`} />
        <Numero icon={CalendarRange} rotulo="Média por mês fechado" valor={moeda(media)}
                sub={`${fechados.length} mês(es) fechado(s) no período — sem o corrente`} />
        <Numero icon={Landmark} rotulo={ultimoFechado ? `Último mês fechado (${mesCurto(ultimoFechado.mes)})` : "Último mês fechado"}
                valor={moeda(ultimoFechado?.total)}
                sub={corrente ? `${mesCurto(corrente.mes)} até agora: ${moeda(corrente.total)} (parcial)` : undefined} />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={PiggyBank} titulo="Por pasta"
                   sub="no período · clique numa pasta para ver só ela no gráfico e no detalhe" />
        {pastas.length === 0 ? (
          <Vazio>Nenhum recurso no período.</Vazio>
        ) : (
          <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {pastas.map((p) => {
              const ativa = pastaSel === p.chave;
              const pct = r.total ? (p.total / r.total) * 100 : 0;
              return (
                <button key={p.chave} type="button" aria-pressed={ativa}
                        onClick={() => setPastaSel(ativa ? null : p.chave)}
                        className="bi-card-flat px-3 py-2.5 text-left transition-colors bi-hover"
                        style={ativa ? { outline: "2px solid var(--bi-accent)", outlineOffset: "-2px" } : undefined}>
                  <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{p.rotulo}</div>
                  <div className="bi-num mt-1 text-[16px] leading-none">{moeda(p.total)}</div>
                  <div className="mt-1.5 h-1 w-full rounded-full" style={{ background: "var(--bi-line)" }}>
                    <div className="h-1 rounded-full" style={{ width: `${pct.toFixed(1)}%`, background: "var(--bi-accent)" }} />
                  </div>
                  <div className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>{pct.toFixed(1)}% do total</div>
                </button>
              );
            })}
          </div>
        )}
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={CalendarRange}
                   titulo={pastaSel ? `Mês a mês — ${rotuloPasta(pastaSel)}` : "Mês a mês"}
                   sub="clique num mês para ver o detalhe só dele · barra clara = mês parcial" />
        <div className="bi-scroll mt-3 overflow-x-auto">
          <div className="flex min-w-[36rem] items-end gap-1.5" style={{ height: "10rem" }}>
            {serie.map((s) => {
              const v = valorDaBarra(s);
              const h = s.coletado ? Math.max(2, (v / maxBarra) * 100) : 0;
              const sel = mes === s.mes;
              return (
                <button key={s.mes} type="button" disabled={!s.coletado}
                        onClick={() => setMes(sel ? null : s.mes)} aria-pressed={sel}
                        title={s.coletado
                          ? `${mesCurto(s.mes)}: ${moeda(v)}${s.parcial ? " (parcial)" : ""}${s.sem_constitucionais ? " — sem FPM/FUNDEB" : ""}`
                          : `${mesCurto(s.mes)}: ainda não carregado`}
                        className="flex h-full min-w-0 flex-1 flex-col justify-end">
                  <div className="w-full rounded-t"
                       style={{
                         height: `${h}%`,
                         background: s.parcial ? "var(--bi-accent-soft)" : "var(--bi-accent)",
                         border: s.parcial ? "1px dashed var(--bi-accent)" : undefined,
                         outline: sel ? "2px solid var(--bi-text)" : undefined,
                       }} />
                </button>
              );
            })}
          </div>
          <div className="mt-1 flex min-w-[36rem] gap-1.5">
            {serie.map((s) => (
              <div key={s.mes} className="min-w-0 flex-1 truncate text-center text-[9px]"
                   style={{ color: mes === s.mes ? "var(--bi-text)" : "var(--bi-faint)" }}>
                {mesCurto(s.mes)}{s.parcial ? "*" : ""}
              </div>
            ))}
          </div>
        </div>
        <p className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
          * parcial — o mês corria quando o arquivo foi lido; FPM e FUNDEB só entram depois do fechamento.
        </p>
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Users} titulo="Quem recebeu" sub="no período, por tipo de favorecido" />
        <Lista className="mt-2">
          {(r.por_grupo || []).map((g) => (
            <ItemLinha key={g.grupo}
                       titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                         <span>{g.rotulo}</span>
                         {!g.na_conta && <Selo>fora da conta</Selo>}
                       </span>}
                       valor={moeda(g.total)}
                       meta={<span>{g.favorecidos} favorecido(s)</span>} />
          ))}
        </Lista>
        {fora.length > 0 && quem === "municipio" && (
          <p className="mt-2 text-[10px]" style={{ color: "var(--bi-faint)" }}>
            Escolas (caixa escolar, APM — podem ser de escola estadual) e entidades recebem no
            município mas não são a prefeitura: ficam fora do total. «Todos os favorecidos» as inclui.
          </p>
        )}
      </Bloco>

      <Bloco className="p-3">
        <BlocoHead icon={Landmark}
                   titulo={`Detalhe por ação e favorecido${pastaSel ? ` — ${rotuloPasta(pastaSel)}` : ""}`}
                   sub={mes ? `só ${mesCurto(mes)}${serie.find((s) => s.mes === mes)?.parcial ? " (parcial)" : ""} · clique no mês de novo para voltar ao período`
                            : "no período inteiro · do maior valor para o menor"}
                   right={mes ? <button type="button" className="text-[11px] underline" onClick={() => setMes(null)}>ver o período</button> : undefined} />
        {detalhe.length === 0 ? (
          <Vazio>Nenhuma transferência {mes ? `em ${mesCurto(mes)}` : "no período"}{pastaSel ? " nesta pasta" : ""}.</Vazio>
        ) : (
          <Lista className="mt-2">
            {detalhe.map((x, i) => (
              <ItemLinha key={`${x.pasta}|${x.acao_codigo}|${x.favorecido_doc}|${x.orgao}|${i}`}
                         titulo={<span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                           <span>{x.linguagem_cidada || x.acao || "Ação sem nome"}</span>
                           {!pastaSel && <Selo>{rotuloPasta(x.pasta)}</Selo>}
                         </span>}
                         valor={moeda(x.total)}
                         meta={<>
                           {x.acao_codigo && <span className="bi-id">{x.acao_codigo}</span>}
                           {x.linguagem_cidada && x.acao && <span>· {x.acao.toLowerCase()}</span>}
                           {x.orgao && <span>· {x.orgao}</span>}
                           <span>· {x.favorecido || x.favorecido_doc || "favorecido não informado"}</span>
                           <span>· {r.rotulos?.grupos[x.grupo] || x.grupo}</span>
                           {!mes && <span>· em {x.meses} mês(es)</span>}
                         </>} />
            ))}
          </Lista>
        )}
      </Bloco>
    </>
  );
}
