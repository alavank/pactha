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
import { BadgeCheck, CalendarClock, ExternalLink, Loader2, Radar, UserCircle2 } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  Bloco, BlocoHead, ItemLinha, Lista, Numero, Selo, Vazio,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

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
  qt_ufs: number;
  abrangencia: "nacional" | "regional" | "exclusivo";
  /* ⚠️ POR QUAIS PORTAS SE ENTRA. "recebimento" é proposta espontânea — a
     prefeitura protocola. "emenda" depende de um deputado ou senador destinar o
     recurso, e o gestor NÃO cumpre esse prazo sozinho. "beneficiario" (desde
     17/09/2026) é o programa que já NOMEIA quem propõe, e o backend só a manda
     quando o CNPJ do município está na lista. */
  portas: Porta[];
  dt_fim_benef: string | null;
  dias_benef: number | null;
  /** O município está na lista de proponentes do programa, seja qual for a porta. */
  nomeado: boolean;
}
type Porta = "recebimento" | "emenda" | "beneficiario";
interface Resp {
  municipio: { nome: string; uf: string };
  /** Sem CNPJ cadastrado, a porta de beneficiário específico nunca abre. */
  cnpj_cadastrado?: boolean;
  total: number;
  programas: Programa[];
  atualizado_em: string | null;
  /** Só vem quando o radar não pôde responder — hoje, UF não cadastrada. */
  motivo?: string;
}

/** O prazo QUE ESTÁ VALENDO para este programa, e não sempre o de recebimento.
 *
 * ⚠️ Num programa aberto só por emenda, `dt_fim_receb` é uma data PASSADA (ou
 * nula): usá-la no cartão mostraria um prazo vencido como se fosse o alvo, ou um
 * "—" no lugar do prazo real. Quem manda é a porta aberta; com mais de uma
 * aberta, vale a que fecha primeiro, porque é a que muda a agenda da semana.
 */
function prazo(p: Programa): { data: string | null; dias: number | null } {
  const janelas = {
    recebimento: { data: p.dt_fim_receb, dias: p.dias },
    emenda: { data: p.dt_fim_emenda, dias: p.dias_emenda },
    beneficiario: { data: p.dt_fim_benef, dias: p.dias_benef },
  };
  const abertas = p.portas.map((q) => janelas[q]).filter((j) => j.dias != null);
  if (abertas.length === 0) return { data: null, dias: null };
  return abertas.reduce((a, b) => (b.dias! < a.dias! ? b : a));
}

const tem = (p: Programa, q: Porta) => p.portas.includes(q);

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
          <TituloTela>Radar de captação</TituloTela>
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
  // ⚠️ Pelo prazo QUE VALE, senão um programa de emenda fechando em 3 dias não
  // entra na conta de urgentes (o `dias` dele é de uma janela já vencida).
  const urgentes = ps.filter((p) => {
    const q = prazo(p).dias;
    return q != null && q <= 30;
  });
  const comEmenda = ps.filter((p) => tem(p, "emenda"));
  const nomeados = ps.filter((p) => p.nomeado);
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
        <TituloTela>Radar de captação</TituloTela>
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
          Dados abertos do TransfereGov · lido em {formatarQuando(d.atualizado_em)} ·
          {" "}recorte: programas abertos à Administração Pública Municipal com
          prazo de proposta em pé{d.municipio.uf ? `, válidos para ${d.municipio.uf}` : ""}
          {" "}· os de beneficiário específico, só onde o CNPJ do município está nomeado
        </p>
      )}

      {/* ⚠️ Sem CNPJ, a porta de beneficiário específico nunca abre, e a tela
          precisa dizer: senão "nenhum programa nomeia o município" se lê como fato. */}
      {d.cnpj_cadastrado === false && (
        <p className="text-[11px]" style={{ color: "var(--bi-warn-ink, var(--bi-muted))" }}>
          {d.municipio.nome} está sem CNPJ cadastrado, então os programas que nomeiam
          o município não aparecem aqui. Cadastre o CNPJ em Configurações → Municípios.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
        <Numero icon={BadgeCheck} rotulo="Nomeiam o município"
                tom={nomeados.length > 0 ? "acento" : "neutro"}
                valor={String(nomeados.length)}
                sub="o CNPJ da prefeitura está na lista de proponentes" />
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
                    {/* ⚠️ "só {UF}" SÓ QUANDO É SÓ A UF. O selo era aplicado a
                        qualquer programa com menos de 27 estados, e mentia no
                        de Saneamento — aberto a 20 UFs, exibido como exclusivo
                        de Minas. Exclusivo é o achado de verdade (disputa
                        curta); "20 estados" é concorrência nacional disfarçada,
                        e o gestor precisa distinguir os dois. */}
                    {p.abrangencia === "exclusivo" && (
                      <Selo tom="acento">só {d.municipio.uf}</Selo>
                    )}
                    {p.abrangencia === "regional" && (
                      <Selo>{p.qt_ufs} estados</Selo>
                    )}
                    {/* ⚠️ O SELO DA PORTA, e ele não é decoração. Um programa
                        aberto só por emenda parlamentar exige um deputado ou
                        senador destinar o recurso — sem esse aviso o gestor lê a
                        lista inteira como "é só protocolar" e monta proposta
                        para uma porta que não depende dele. É a razão pela qual
                        os 67 programas de emenda podem entrar na tela. */}
                    {tem(p, "emenda") && !tem(p, "recebimento") && (
                      <Selo tom="atencao">via emenda parlamentar</Selo>
                    )}
                    {tem(p, "emenda") && tem(p, "recebimento") && <Selo>proposta ou emenda</Selo>}
                    {/* ⚠️ "NOMEADO" NÃO É A MESMA COISA NAS DUAS PORTAS. Na de
                        beneficiário, é o convite: só quem está na lista propõe.
                        Na de emenda, a lista é de quem já teve emenda indicada
                        (medido: 888 de 943 já propuseram), então o selo diz
                        "está na lista", e não "pode propor". */}
                    {tem(p, "beneficiario") && (
                      <Selo tom="acento">município nomeado</Selo>
                    )}
                    {p.nomeado && !tem(p, "beneficiario") && (
                      <Selo>na lista do programa</Selo>
                    )}
                    {prazo(p).dias != null && prazo(p).dias! <= 30 && (
                      <Selo tom={prazo(p).dias! <= 7 ? "critico" : "atencao"}>
                        {prazo(p).dias === 0 ? "fecha hoje"
                          : prazo(p).dias === 1 ? "fecha amanhã"
                          : `${prazo(p).dias} dias`}
                      </Selo>
                    )}
                  </span>
                }
                valor={prazo(p).data ? formatarData(prazo(p).data!) : "—"}
                meta={
                  <>
                    {p.orgao && <span>{p.orgao}</span>}
                    {/* ⚠️ SÓ QUANDO A PORTA DE RECEBIMENTO ESTÁ ABERTA. Antes
                        esta linha saía sempre que `dias > 30`; agora chegam
                        programas cujo recebimento já FECHOU, e escrever
                        "propostas até <data passada>" convidaria o gestor a
                        montar proposta por uma porta que não aceita mais. */}
                    {tem(p, "recebimento")
                      && p.dias != null && p.dias > 30 && (
                      <span>· propostas até {formatarData(p.dt_fim_receb)} ({p.dias} dias)</span>
                    )}
                    {/* A janela de emenda é outro prazo e por isso vem escrita
                        por extenso: o gestor não a cumpre sozinho. */}
                    {tem(p, "emenda")
                      && p.dias_emenda != null && p.dias_emenda >= 0 && (
                      <span>· emenda parlamentar até {formatarData(p.dt_fim_emenda)}</span>
                    )}
                    {tem(p, "beneficiario")
                      && p.dias_benef != null && p.dias_benef >= 0 && (
                      <span>· proposta do beneficiário nomeado até {formatarData(p.dt_fim_benef)}</span>
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

/* DATA PURA (dd/mm/aaaa) — prazos, que vêm do banco como DATE.
 *
 * O `T00:00:00` sem sufixo de fuso faz o JS ler como hora LOCAL, que é o certo
 * aqui: `2026-12-31` é o dia 31, não um instante. Sem ele, o `Date` trataria a
 * string como UTC e no Brasil o prazo apareceria como dia 30.
 *
 * Data ilegível some: numa tela de prazo, data errada é pior que data nenhuma —
 * o gestor programaria a agenda por ela. */
function formatarData(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleDateString("pt-BR");
}

/* INSTANTE (dd/mm/aaaa hh:mm) — o carimbo da coleta, que vem TIMESTAMPTZ.
 *
 * ⚠️ FUNÇÃO SEPARADA DE PROPÓSITO. O carimbo passava pela `formatarData` acima,
 * que corta a string nos 10 primeiros caracteres: uma coleta das 22h de
 * Brasília chega como `...T01:00:00+00:00` do dia seguinte e era exibida com a
 * data errada — e a hora, que é o que diz se o radar é de hoje ou de ontem,
 * sumia. Data e instante não são o mesmo tipo e não podem dividir o formatador.
 */
function formatarQuando(iso: string | null): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleString("pt-BR", {
    day: "2-digit", month: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
