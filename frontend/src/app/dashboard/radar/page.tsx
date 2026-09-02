"use client";

/* RADAR DE CAPTAÇÃO — os programas federais com prazo ABERTO para propor.
 *
 * ⭐ É A ÚNICA TELA DO PACTHA QUE OLHA PARA FRENTE. Todas as outras mostram o
 * que o município JÁ tem — convênio assinado, emenda indicada, obra em medição.
 * Esta mostra a porta que ainda está aberta e até quando.
 *
 * ⚠️ A LISTA É CURTA DE PROPÓSITO, e a raridade é o produto. O arquivo aberto do
 * TransfereGov tem 1.257.102 linhas e 1.006.720 com situação "DISPONIBILIZADO";
 * dessas, só 1.314 ainda têm prazo em pé, e apenas 17 programas estão abertos a
 * município. Medido em 02/09/2026: MG vê 9, RS vê 10. Uma tela com 44 mil linhas
 * seria um catálogo; nove é uma pauta de reunião.
 *
 * ⚠️ E NÃO HÁ VALOR NENHUM AQUI, porque a fonte não traz. O radar diz QUE existe
 * e ATÉ QUANDO. Um "R$ 0,00" na ficha se leria como programa sem dinheiro.
 *
 * ⚠️ Lista vazia e coleta que nunca rodou são estados DIFERENTES na tela: o
 * primeiro é "não há programa aberto para a sua UF hoje" (informação), o segundo
 * é pendência nossa. Confundi-los faria o município concluir que não há nada.
 */

import React, { useCallback, useEffect, useState } from "react";
import { CalendarClock, ExternalLink, Loader2, Radar, UserCircle2 } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";

interface Programa {
  id_programa: string;
  nome: string;
  orgao: string | null;
  modalidade: string | null;
  dt_ini_receb: string | null;
  dt_fim_receb: string | null;
  dt_fim_emenda: string | null;
  acao_orcamentaria: string | null;
  subtipo: string | null;
  cod_programa: string | null;
  dias: number | null;
  dias_emenda: number | null;
  abrangencia: "nacional" | "regional";
}
interface Resp {
  municipio: { nome: string; uf: string };
  total: number;
  programas: Programa[];
  atualizado_em: string | null;
  /** Só vem quando o radar não pôde responder — hoje, UF não cadastrada. */
  motivo?: string;
}

export default function RadarPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    setErro(false);
    api.get("/programas-captacao", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data))
      .catch(() => { setD(null); setErro(true); })
      .finally(() => setLoading(false));
  }, [municipioId]);
  useEffect(carregar, [carregar]);

  if (loading && !d) {
    return <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <Loader2 className="size-4 animate-spin" /> carregando…</div>;
  }
  if (erro || !d) return <Vazio>Não foi possível carregar o radar.</Vazio>;
  // ⚠️ `motivo` vem quando o radar NÃO PÔDE responder (hoje: UF não cadastrada).
  // Cair na tela normal mostraria zero programas, que se lê como "não há
  // oportunidade" — culpando o TransfereGov por um cadastro nosso incompleto.
  if (d.motivo) {
    return (
      <div className="space-y-4">
        <div>
          <h1 className="text-2xl font-bold text-base-content">Radar de captação</h1>
          <p className="text-sm text-muted-foreground">{d.municipio.nome}</p>
        </div>
        <Bloco className="p-3">
          <BlocoHead icon={Radar} titulo="O radar não consegue responder ainda"
                     sub="falta um dado de cadastro" />
          <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            {d.motivo}
          </p>
        </Bloco>
      </div>
    );
  }

  const ps = d.programas || [];
  // "Fecha em menos de 30 dias" é o que muda a agenda da semana. Acima disso o
  // programa é planejamento, não urgência.
  const urgentes = ps.filter((p) => p.dias != null && p.dias <= 30);
  const comEmenda = ps.filter((p) => p.dias_emenda != null && p.dias_emenda >= 0);
  const nuncaColetado = d.atualizado_em == null;
  // ⚠️ O TRANSFEREGOV PUBLICA PROGRAMAS DISTINTOS COM O MESMO NOME. Medido em
  // 02/09/2026: "Ação 00SX — Apoio a Projetos de Desenvolvimento Sustentável"
  // sai duas vezes, com IDs 55990 e 56567 e códigos diferentes. NÃO são
  // duplicata nossa e não podem ser fundidos — cada um é uma proposta possível,
  // e esconder um tiraria da mesa uma porta que abre. O que a tela deve fazer é
  // avisar, senão a lista parece defeituosa e perde a confiança do gestor.
  const temNomeRepetido =
    new Set(ps.map((p) => p.nome)).size < ps.length;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">Radar de captação</h1>
        <p className="text-sm text-muted-foreground">
          Programas federais com prazo aberto para {d.municipio.nome} apresentar proposta
        </p>
      </div>

      {/* ⚠️ ESTE AVISO NÃO É RODAPÉ. Sem ele, um radar coletado há três semanas
          se apresenta como se fosse de hoje — e prazo é exatamente o dado que
          não sobrevive a três semanas. */}
      {nuncaColetado ? (
        <Bloco className="p-3">
          <BlocoHead icon={Radar} titulo="O radar ainda não foi coletado aqui"
                     sub="pendência nossa, não do município" />
          <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            A leitura dos programas federais ainda não rodou neste ambiente. Isto{" "}
            <strong>não</strong> significa que não haja programa aberto — significa
            que ainda não buscamos.
          </p>
        </Bloco>
      ) : (
        <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
          Dados abertos do TransfereGov · lido em {formatarData(d.atualizado_em)} ·
          {" "}recorte: programas abertos à Administração Pública Municipal com
          prazo de proposta em pé{d.municipio.uf ? `, válidos para ${d.municipio.uf}` : ""}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Numero icon={Radar} rotulo="Programas abertos hoje" tom="acento"
                valor={String(d.total)}
                sub={`para ${d.municipio.nome}${d.municipio.uf ? ` — ${d.municipio.uf}` : ""}`} />
        <Numero icon={CalendarClock} rotulo="Fecham em até 30 dias"
                tom={urgentes.length > 0 ? "atencao" : "neutro"}
                valor={String(urgentes.length)}
                sub={urgentes.length > 0
                  ? "prazo curto — proposta precisa entrar nesta janela"
                  : "nenhum prazo vencendo no mês"} />
        <Numero icon={UserCircle2} rotulo="Aceitam emenda parlamentar"
                valor={String(comEmenda.length)}
                sub="janela própria, que depende de um gabinete indicar" />
      </div>

      <Bloco className="p-3">
        <BlocoHead icon={Radar} titulo="Programas abertos"
                   sub="do prazo mais curto para o mais longo" />
        {ps.length === 0 ? (
          /* ⚠️ Vazio COM coleta é informação, e a frase diz isso. "Nenhum
             resultado" deixaria a dúvida entre não-há e não-buscamos. */
          <Vazio>
            {nuncaColetado
              ? "Assim que a primeira coleta rodar, os programas aparecem aqui."
              : `Nenhum programa federal está com prazo aberto para ${d.municipio.uf || "esta UF"} hoje. A lista muda quando um novo programa é disponibilizado.`}
          </Vazio>
        ) : (
          <Lista>
            {ps.map((p) => (
              <ItemLinha
                key={p.id_programa}
                titulo={
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span>{p.nome}</span>
                    {p.modalidade && <Selo>{p.modalidade.toLowerCase()}</Selo>}
                    {/* Regional é o achado: menos município disputando. */}
                    {p.abrangencia === "regional" && (
                      <Selo tom="acento">só {d.municipio.uf}</Selo>
                    )}
                    {p.dias != null && p.dias <= 30 && (
                      <Selo tom={p.dias <= 7 ? "critico" : "atencao"}>
                        {p.dias === 0 ? "fecha hoje"
                          : p.dias === 1 ? "fecha amanhã"
                          : `${p.dias} dias`}
                      </Selo>
                    )}
                  </span>
                }
                valor={p.dt_fim_receb ? formatarData(p.dt_fim_receb) : "—"}
                meta={
                  <>
                    {p.orgao && <span>{p.orgao}</span>}
                    {p.dias != null && p.dias > 30 && (
                      <span>· propostas até {formatarData(p.dt_fim_receb)} ({p.dias} dias)</span>
                    )}
                    {/* A janela de emenda é outro prazo e por isso vem escrita
                        por extenso: o gestor não a cumpre sozinho. */}
                    {p.dias_emenda != null && p.dias_emenda >= 0 && (
                      <span>· emenda parlamentar até {formatarData(p.dt_fim_emenda)}</span>
                    )}
                    {p.cod_programa && <span>· código {p.cod_programa}</span>}
                    {p.acao_orcamentaria && <span>· ação {p.acao_orcamentaria}</span>}
                  </>
                }
              />
            ))}
          </Lista>
        )}
        {temNomeRepetido && (
          <p className="mt-2 px-1 text-[10px] italic leading-relaxed"
             style={{ color: "var(--bi-faint)" }}>
            Há programas com o mesmo nome na lista. Não é repetição: o
            TransfereGov publica cada um como programa separado, com código
            próprio — e cada um aceita uma proposta. O código na linha é o que
            os diferencia.
          </p>
        )}
        <div className="mt-2 px-1">
          <a href="https://www.gov.br/transferegov/" target="_blank" rel="noopener noreferrer"
             className="inline-flex items-center gap-1 text-[11px] underline"
             style={{ color: "var(--bi-accent-ink)" }}>
            Apresentar proposta no TransfereGov <ExternalLink className="size-3" />
          </a>
        </div>
      </Bloco>
    </div>
  );
}

/* ISO -> dd/mm/aaaa. Data ilegível some: numa tela de prazo, data errada é pior
 * que data nenhuma — o gestor programaria a agenda por ela. */
function formatarData(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleDateString("pt-BR");
}
