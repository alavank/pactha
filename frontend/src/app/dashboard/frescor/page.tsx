"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Activity, Database, RefreshCw, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { Button } from "@/components/ui/button";

interface Fonte {
  fonte: string;
  ultimo_dado: string | null;
  ultima_coleta: string | null;
  referencia: string | null;
  idade_dias: number | null;
  registros: number | null;
  status: "fresco" | "atrasado" | "critico" | "desconhecido";
  /** Última TENTATIVA e o status cru dela — diferentes de `ultima_coleta`, que
   *  agora só conta rodada bem-sucedida. Uma fonte que roda de hora em hora e
   *  falha há três dias tem tentativa recente e coleta velha; antes as duas
   *  eram o mesmo número e a linha ficava verde. */
  ultima_tentativa?: string | null;
  ultimo_status?: string | null;
  falhando?: boolean;
}

const STATUS_TOM: Record<string, { tom: "neutro" | "ok" | "atencao" | "critico"; label: string }> = {
  // "Fresco" e o estado NORMAL de quase toda fonte — vira cinza. Numa tela em
  // que 15 de 17 linhas estavam verdes, o verde nao dizia nada e as duas que
  // importavam disputavam atencao com ele.
  fresco: { tom: "neutro", label: "Fresco" },
  atrasado: { tom: "atencao", label: "Atrasado" },
  critico: { tom: "critico", label: "Crítico" },
  desconhecido: { tom: "neutro", label: "Sem informação" },
};

function fmtDt(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return iso;
  }
}

function fmtIdade(d: number | null): string {
  if (d == null) return "—";
  if (d < 1) return "hoje";
  if (d < 2) return "1 dia";
  return `${Math.round(d)} dias`;
}

/** Um aviso que o vigia (watchdog) emitiu. */
interface Aviso {
  tipo: string;
  chave: string;
  mensagem: string;
  em: string | null;
}

/** O ícone diz de quem é a bola: chave = alguém precisa trocar uma senha;
 *  os demais = o sistema/portal. */
const AVISO_ICONE: Record<string, string> = {
  credencial_recusada: "🔑",
  processo_travado: "🔴",
  fonte_parada: "🟠",
  municipio_defasado: "🟡",
};

export default function FrescorPage() {
  const [fontes, setFontes] = useState<Fonte[]>([]);
  const [avisos, setAvisos] = useState<Aviso[]>([]);
  const [loading, setLoading] = useState(true);
  const [geradoEm, setGeradoEm] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<{ gerado_em: string; fontes: Fonte[]; avisos?: Aviso[] }>("/admin/freshness");
      setFontes(r.data.fontes || []);
      setAvisos(r.data.avisos || []);
      setGeradoEm(r.data.gerado_em);
      setErro(null);
    } catch (e: unknown) {
      setErro((e as { response?: { status?: number } })?.response?.status === 403
        ? "Apenas administradores acessam esta tela."
        : "Erro ao carregar o status dos dados.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { carregar(); }, [carregar]);

  const criticos = fontes.filter((f) => f.status === "critico").length;
  const atrasados = fontes.filter((f) => f.status === "atrasado").length;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 border-b border-base-300 pb-4">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <Activity className="size-6" style={{ color: "var(--bi-accent-ink)" }} />
            Status dos Dados
          </h1>
          {/* A legenda explica as DUAS colunas em vez de listar os limiares de
              dias. Os limiares já estão ditos onde importam — no selo colorido
              de cada fonte. O que ninguém adivinha olhando é a diferença entre
              as duas datas, e ela é justamente o ponto: o coletor pode ter
              rodado hoje com sucesso e trazido dado do mês passado. */}
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            <strong style={{ color: "var(--bi-text)" }}>Último dado</strong>: a data do
            registro mais recente que temos dessa fonte.{" "}
            <strong style={{ color: "var(--bi-text)" }}>Última coleta com sucesso</strong>: a
            última rodada que terminou bem — rodada que falhou ou veio incompleta NÃO conta
            aqui.{" "}
            <strong style={{ color: "var(--bi-text)" }}>Última tentativa</strong>: aparece só
            quando a última rodada não foi um sucesso limpo, com o status cru do coletor ao
            lado. As três podem divergir: uma coleta boa hoje pode trazer dado antigo, e uma
            fonte pode estar rodando de hora em hora e falhando há dias.
          </p>
        </div>
        <Button variant="outline" onClick={carregar} disabled={loading}>
          {loading ? <Loader2 className="size-4 animate-spin mr-1" /> : <RefreshCw className="size-4 mr-1" />}
          Atualizar
        </Button>
      </div>

      {erro && (
        <div className="rounded-2xl p-3 text-sm"
          style={{ background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)", color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {/* ⭐ OS AVISOS DO VIGIA — antes da lista, porque avisam o que já
          aconteceu e pede AÇÃO, enquanto a lista abaixo é estado.
          Até 11/08/2026 estes avisos morriam no log do servidor: o Telegram foi
          desligado e o WhatsApp ainda não existe, então o watchdog detectava
          (bem) e não tinha a quem contar. Aqui eles têm. */}
      {!erro && avisos.length > 0 && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Activity}
            titulo="Avisos do monitor"
            sub={`${avisos.length} nos últimos 7 dias · o sistema detectou e registrou`}
          />
          <Lista>
            {avisos.map((a, i) => (
              <ItemLinha
                key={`${a.em}-${i}`}
                titulo={
                  <span className="flex items-start gap-1.5">
                    <span aria-hidden>{AVISO_ICONE[a.tipo] || "🟠"}</span>
                    {/* A mensagem já vem escrita para gente ler, com o nome dos
                        municípios e o que fazer — não reescrever aqui. */}
                    <span className="whitespace-pre-wrap">{a.mensagem}</span>
                  </span>
                }
                meta={<span>{fmtDt(a.em)} · {a.chave}</span>}
              />
            ))}
          </Lista>
        </Bloco>
      )}

      {!erro && (
        <>
          {loading && fontes.length === 0 ? (
            <div className="space-y-1.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-2xl" style={{ background: "var(--bi-surface-2)" }} />
              ))}
            </div>
          ) : (
            /* AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO -> itens
               cinza dentro. A linha de resumo que ficava solta acima da lista
               ("Gerado em ... · N fontes" e os contadores) virou o cabecalho
               deste cartao: e a mesma informacao, agora ancorada no que ela
               resume. Os contadores continuam sendo os UNICOS coloridos da
               tela — critico e atrasado pedem acao; o resto e cinza. */
            <Bloco className="p-3">
              <BlocoHead
                icon={Database}
                titulo="Fontes de dados"
                sub={
                  <>
                    {geradoEm && <>Gerado em {fmtDt(geradoEm)} · </>}
                    {fontes.length} fonte(s)
                  </>
                }
                right={
                  criticos > 0 || atrasados > 0 ? (
                    <div className="flex flex-wrap justify-end gap-1">
                      {criticos > 0 && <Selo tom="critico">{criticos} crítico(s)</Selo>}
                      {atrasados > 0 && <Selo tom="atencao">{atrasados} atrasado(s)</Selo>}
                    </div>
                  ) : undefined
                }
              />
              {fontes.length === 0 ? (
                <Vazio>Nenhuma fonte de dados encontrada.</Vazio>
              ) : (
                <Lista>
                  {fontes.map((f) => {
                    const st = STATUS_TOM[f.status] || STATUS_TOM.desconhecido;
                    return (
                      <ItemLinha
                        key={f.fonte}
                        titulo={f.fonte}
                        valor={f.registros != null ? f.registros.toLocaleString("pt-BR") : "—"}
                        meta={<><Selo tom={st.tom}>{st.label}</Selo><span>{fmtIdade(f.idade_dias)}</span></>}
                      >
                        <Campos
                          campos={[
                            { rotulo: "Último dado", valor: fmtDt(f.ultimo_dado) },
                            { rotulo: "Última coleta com sucesso", valor: fmtDt(f.ultima_coleta) },
                            /* Só aparece quando a última tentativa NÃO deu certo.
                               Na linha saudável seria ruído: tentativa e sucesso
                               são o mesmo instante. */
                            ...(f.falhando
                              ? [{
                                  rotulo: "Última tentativa",
                                  tom: "critico" as const,
                                  valor: `${fmtDt(f.ultima_tentativa ?? null)} — ${f.ultimo_status ?? "?"}`,
                                }]
                              : []),
                          ]}
                        />
                      </ItemLinha>
                    );
                  })}
                </Lista>
              )}
            </Bloco>
          )}
        </>
      )}
    </div>
  );
}
