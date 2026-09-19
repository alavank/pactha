"use client";

/* CONSOLIDADO › RADAR — dinheiro que a carteira pode pegar agora (19/09/2026).
 *
 * Programas federais com janela aberta em que o município foi NOMEADO como
 * beneficiário ou teve EMENDA INDICADA por um parlamentar — o recurso já tem
 * dono, falta a prefeitura cadastrar a proposta dentro do prazo. É o Radar de
 * captação de cada município (o mesmo filtro, o mesmo contador do menu), lado a
 * lado.
 *
 * O dono não entendeu o bloco quando ele estava enterrado no fim do painel
 * (19/09/2026); por isso o subtítulo diz o que é, e o clique abre a ficha do
 * programa — a mesma do Radar de captação.
 */

import React, { useEffect, useMemo, useState } from "react";
import { AlertTriangle, FileSpreadsheet, Loader2, MapPin, Radar } from "lucide-react";

import api from "@/lib/api";
import { formatCurrencyShort } from "@/lib/bi-format";
import {
  Aviso, BOTAO_SEC, Bloco, BlocoHead, ESTILO_SEC, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { FichaPrograma } from "@/app/dashboard/transferegov-radar/FichaPrograma";
import { baixarArquivo, mensagemDeErro } from "./baixar";

interface Linha {
  municipio_id: number; nome: string; uf: string;
  radar: { abertos: number; nomeado: number; indicado: number; proximo_dias: number | null } | null;
}
interface Programa {
  municipio_id: number; municipio: string; id_programa: string; programa: string;
  beneficiario: boolean; dias: number | null;
  indicacoes: { parlamentar: string | null; solicitante: string | null; valor: number | null }[];
}
interface Resp {
  municipios_na_carteira: number;
  indisponivel: string[];
  municipios: Linha[];
  resumo: { com_nomeado_ou_indicado: number; sem_uf: number };
  programas: Programa[];
  programas_total: number;
}

export function RadarCarteira() {
  const [d, setD] = useState<Resp | null>(null);
  const [erro, setErro] = useState(false);
  const [filtro, setFiltro] = useState<number | null>(null);
  const [ficha, setFicha] = useState<{ id: string; municipioId: number } | null>(null);
  const [baixando, setBaixando] = useState(false);
  const [erroArquivo, setErroArquivo] = useState<string | null>(null);

  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/consolidado/radar")
      .then((r) => { if (vivo) setD(r.data); })
      .catch(() => { if (vivo) setErro(true); });
    return () => { vivo = false; };
  }, []);

  const programas = useMemo(
    () => (d?.programas ?? []).filter((p) => filtro == null || p.municipio_id === filtro), [d, filtro]);

  if (erro) return <Vazio>Não foi possível montar o Radar da carteira.</Vazio>;
  if (!d) {
    return (
      <div className="flex items-center gap-2 py-10 text-[12px]" style={{ color: "var(--bi-faint)" }}>
        <Loader2 className="size-4 animate-spin" /> lendo o Radar de todos os municípios…
      </div>
    );
  }
  const n = d.municipios_na_carteira;
  const nomeFiltro = d.municipios.find((m) => m.municipio_id === filtro)?.nome;
  const baixar = async () => {
    setBaixando(true);
    setErroArquivo(null);
    try {
      await baixarArquivo("/consolidado/radar/exportar", "radar_da_carteira.xlsx");
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
               titulo="Parte dos municípios não pôde ser lida nesta vez — os números abaixo podem estar incompletos." />
      )}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid flex-1 gap-3 sm:grid-cols-2">
          <Numero icon={Radar} rotulo="Nomeados ou com emenda indicada"
                  tom={d.resumo.com_nomeado_ou_indicado ? "acento" : "neutro"}
                  valor={`${d.resumo.com_nomeado_ou_indicado} de ${n}`}
                  sub="municípios com programa aberto esperando proposta" />
          <Numero icon={MapPin} rotulo="Programas com dono na carteira" valor={String(d.programas_total)}
                  sub="nomeação ou indicação em janela aberta" />
        </div>
        <span className="flex items-center gap-2">
          {erroArquivo && <span className="text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>{erroArquivo}</span>}
          <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={baixar} disabled={baixando}>
            {baixando ? <Loader2 className="size-3.5 animate-spin" /> : <FileSpreadsheet className="size-3.5" />}
            Planilha
          </button>
        </span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Bloco className="p-3">
          <BlocoHead icon={MapPin} titulo="Por município" sub="clique para filtrar os programas" />
          <Lista>
            {d.municipios.map((l) => {
              const r = l.radar;
              const ativo = filtro === l.municipio_id;
              return (
                <ItemLinha key={l.municipio_id}
                  onClick={() => setFiltro(ativo ? null : l.municipio_id)} expandido={ativo}
                  className={ativo ? "ring-1 ring-[var(--bi-accent-ink)]" : ""}
                  titulo={<span className="flex items-center gap-2">{l.nome} {l.uf && <Selo>{l.uf}</Selo>}</span>}
                  valor={r ? String(r.abertos) : "—"}
                  meta={!r ? <span>sem UF cadastrada</span> : <>
                    <span>programas abertos</span>
                    {r.nomeado > 0 && <Selo tom="acento">{r.nomeado} nomeado</Selo>}
                    {r.indicado > 0 && <Selo tom="ok">{r.indicado} com emenda</Selo>}
                  </>} />
              );
            })}
          </Lista>
        </Bloco>

        <Bloco className="p-3">
          <BlocoHead icon={Radar}
                     titulo={nomeFiltro ? `Programas com dono — ${nomeFiltro}` : "Programas com dono na carteira"}
                     sub="o município foi nomeado ou tem emenda indicada; falta cadastrar a proposta no prazo · clique para a ficha" />
          {programas.length === 0 ? (
            <Vazio>{nomeFiltro
              ? `${nomeFiltro} não está nomeado nem com emenda indicada em programa aberto.`
              : "Nenhum município da carteira está nomeado ou com emenda indicada em programa aberto."}</Vazio>
          ) : (
            <Lista>
              {programas.map((x, i) => (
                <ItemLinha key={`${x.municipio_id}:${x.id_programa}:${i}`}
                  onClick={() => setFicha({ id: x.id_programa, municipioId: x.municipio_id })}
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

      {ficha && (
        <FichaPrograma key={`${ficha.municipioId}:${ficha.id}`} idPrograma={ficha.id}
                       municipioId={String(ficha.municipioId)} onFechar={() => setFicha(null)} />
      )}
    </div>
  );
}
