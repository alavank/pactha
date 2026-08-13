"use client";

// TELEMETRIA — como o sistema é usado.
//
// Aba IRMÃ da Auditoria, e de propósito separada dela: a trilha guarda ato
// consequente e serve de prova; esta guarda navegação e serve para entender o
// uso. Mesma seção de Configurações porque as duas são do AMBIENTE INTEIRO —
// diferente das telas de dado, que mudam com o município selecionado.

import React, { useCallback, useEffect, useState } from "react";
import { Activity, Loader2, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { Button } from "@/components/ui/button";
import PresencaAgora from "@/components/PresencaAgora";

interface Sessao {
  sid: string; user_email: string; usuario_nome: string | null;
  inicio: string; ultimo_sinal: string; fim: string | null;
  seg_ativos: number; seg_ociosos: number; seg_total: number;
  eventos: number; descartados: number;
  tela_atual: string | null; situacao: string; ip: string | null;
}
interface Evento {
  ocorrido_em: string; tela: string; rota: string | null; acao: string;
  alvo: string | null; ms: number | null; municipio: string | null;
  user_email: string; usuario_nome: string | null; sid: string;
}

const VERBO: Record<string, string> = {
  ver: "abriu", detalhe: "abriu o detalhe de", filtrar: "filtrou",
  buscar: "buscou em", exportar: "exportou", gerar: "gerou",
  perguntar: "perguntou à IA em", acionar: "acionou", sair: "saiu de",
  outro: "usou",
};

function dur(seg: number | null): string {
  if (!seg || seg < 1) return "—";
  if (seg < 60) return `${seg}s`;
  const m = Math.floor(seg / 60);
  if (m < 60) return `${m}min`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}min`;
}
/** COM SEGUNDOS, de propósito. Sem eles, seis atos do mesmo minuto apareciam
 *  todos como "22:29" e a lista parecia desordenada — a ordem estava certa, o
 *  carimbo é que escondia a diferença. */
function hora(iso: string): string {
  try { return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" }); }
  catch { return iso; }
}
const TOM: Record<string, "ok" | "atencao" | "neutro"> = {
  ativa: "ok", logout: "neutro", aba_fechada: "neutro", expirou: "atencao",
};

export default function TelemetriaPage() {
  const [sessoes, setSessoes] = useState<Sessao[]>([]);
  const [eventos, setEventos] = useState<Evento[]>([]);
  const [aberta, setAberta] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async (silencioso = false) => {
    if (!silencioso) setLoading(true);
    try {
      const [s, e] = await Promise.all([
        api.get<{ sessoes: Sessao[] }>("/uso/sessoes", { params: { dias: 7 } }),
        api.get<{ eventos: Evento[] }>("/uso/eventos", { params: { dias: 7 } }),
      ]);
      setSessoes(s.data.sessoes || []);
      setEventos(e.data.eventos || []);
      setErro(null);
    } catch (x: unknown) {
      setErro((x as { response?: { status?: number } })?.response?.status === 403
        ? "Você não tem a permissão «Telemetria — Ver»."
        : "Não foi possível carregar a telemetria.");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  // ⚠️ A LISTA SE ATUALIZA SOZINHA. Sem isto era preciso apertar "Atualizar"
  // para ver o que estava acontecendo — numa tela cujo propósito é justamente
  // acompanhar. 20s casa com o envio de 45s do outro lado: um ato demora no
  // máximo ~1min para aparecer, e o gargalo é o envio, não esta consulta.
  // Pausa com a aba escondida: recarregar em segundo plano é gastar CPU do
  // servidor para atualizar o que ninguém está vendo.
  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === "visible") carregar(true);
    }, 20_000);
    return () => clearInterval(t);
  }, [carregar]);

  const doDia = aberta ? eventos.filter((e) => e.sid === aberta) : eventos;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <Activity className="size-6" style={{ color: "var(--bi-accent-ink)" }} />
            Telemetria
          </h1>
          {/* A frase que separa esta aba da vizinha. Sem ela, as duas parecem a
              mesma coisa com nomes diferentes — e a diferença importa: uma serve
              de prova, a outra de termômetro. */}
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Como o sistema é usado: quem entrou, que telas abriu, quanto tempo ficou em cada
            uma. É diferente da <strong style={{ color: "var(--bi-text)" }}>Auditoria</strong>,
            que guarda os atos com consequência (criar usuário, exportar, revelar senha) e serve
            de prova. Esta aqui serve para entender o produto — e vale para o ambiente inteiro,
            não muda com o município selecionado.
          </p>
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
            Últimos 7 dias. O tempo <strong>ativo</strong> conta só com a aba em primeiro plano e
            com clique, tecla ou rolagem nos últimos 5 minutos — notebook aberto numa reunião não
            é uso.
          </p>
        </div>
        <Button variant="outline" onClick={() => carregar()} disabled={loading}>
          {loading ? <Loader2 className="mr-1 size-4 animate-spin" /> : <RefreshCw className="mr-1 size-4" />}
          Atualizar
        </Button>
      </div>

      {erro && (
        <div className="rounded-2xl p-3 text-sm"
             style={{ background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
                      color: "var(--bi-crit-ink)" }}>{erro}</div>
      )}

      {!erro && (
        <>
          {/* Quem está agora, ACIMA de tudo: é a única parte viva da tela — o
              resto é histórico. Fica aqui e em nenhum outro lugar do sistema. */}
          <PresencaAgora />

          <Bloco className="p-3">
            <BlocoHead icon={Activity} titulo="Sessões"
              sub={`${sessoes.length} nos últimos 7 dias · clique para ver só os atos daquela sessão`} />
            {sessoes.length === 0 ? (
              <Vazio>
                Ainda não há sessão registrada. A telemetria começa a gravar no próximo login —
                sessões anteriores a esta versão não existem aqui.
              </Vazio>
            ) : (
              <Lista>
                {sessoes.map((s) => (
                  <ItemLinha
                    key={s.sid}
                    onClick={() => setAberta(aberta === s.sid ? null : s.sid)}
                    expandido={aberta === s.sid}
                    titulo={s.usuario_nome || s.user_email}
                    valor={dur(s.seg_total)}
                    meta={
                      <>
                        <Selo tom={TOM[s.situacao] || "neutro"}>{s.situacao}</Selo>
                        <span>{hora(s.inicio)}</span>
                        {s.tela_atual && <span>· {s.tela_atual}</span>}
                      </>
                    }
                  >
                    <Campos
                      campos={[
                        { rotulo: "Tempo ativo", valor: dur(s.seg_ativos) },
                        { rotulo: "Tempo ocioso", valor: dur(s.seg_ociosos) },
                        { rotulo: "Atos", valor: s.eventos },
                        /* `descartados` aparece de propósito: telemetria que
                           corta em silêncio ensina a confiar num total
                           incompleto. Só mostra quando houve corte. */
                        ...(s.descartados
                          ? [{ rotulo: "Descartados", valor: s.descartados, tom: "atencao" as const }]
                          : []),
                        { rotulo: "IP", valor: s.ip || "—", mono: true },
                      ]}
                    />
                  </ItemLinha>
                ))}
              </Lista>
            )}
          </Bloco>

          <Bloco className="p-3">
            <BlocoHead icon={Activity} titulo="Atos"
              sub={aberta ? "só desta sessão · clique na sessão de novo para ver todos"
                          : `${doDia.length} nos últimos 7 dias`} />
            {doDia.length === 0 ? (
              <Vazio>Nenhum ato registrado no período.</Vazio>
            ) : (
              <Lista>
                {doDia.slice(0, 300).map((e, i) => (
                  <ItemLinha
                    key={`${e.sid}-${i}`}
                    titulo={
                      <>
                        <strong>{e.usuario_nome || e.user_email}</strong>{" "}
                        {VERBO[e.acao] || e.acao} <strong>{e.rota || e.tela}</strong>
                        {e.alvo ? ` — ${e.alvo}` : ""}
                      </>
                    }
                    valor={e.ms ? dur(Math.round(e.ms / 1000)) : undefined}
                    meta={<><span>{hora(e.ocorrido_em)}</span>
                           {e.municipio && <span>· {e.municipio}</span>}</>}
                  />
                ))}
              </Lista>
            )}
          </Bloco>
        </>
      )}
    </div>
  );
}
