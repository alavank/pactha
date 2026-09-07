"use client";

/* MONITORAMENTO MENSAL DE CONVÊNIOS — Decreto Estadual (RS) nº 56.939/2023.
 *
 * ⭐ POR QUE ESTA TELA EXISTE, e por que ela é a mais comercial do estado. O
 * decreto obriga o município a atualizar o Sistema de Monitoramento até o dia
 * 15 de cada mês, para cada convênio em execução. Três meses sem atualizar
 * implicam suspensão das parcelas, indeferimento de prorrogação e impedimento
 * de celebrar convênio novo. É a única obrigação gaúcha que trava dinheiro já
 * assinado por esquecimento de cadastro — e o alarme tem de tocar no SEGUNDO
 * mês, antes do bloqueio, que é exatamente o que `services/monitoramento_rs.py`
 * calcula.
 *
 * ⚠️ ELA FALTAVA. O serviço estava pronto e testado (16 casos em
 * `test_monitoramento_rs.py`) e a rota `/api/monitoramento` no ar desde 08/2026,
 * mas NENHUMA página do frontend a consumia — `docs/MAPA_RS.md` §13.3 afirmava
 * que a tela existia. O trabalho estava feito e invisível.
 *
 * ⚠️ TRÊS ESTADOS, NÃO DOIS. "Não conectado" não é "em dia" nem "em atraso": é
 * ausência de fonte. Enquanto a credencial PCPRS não for cadastrada, a tela diz
 * isso com todas as letras em vez de pintar de verde (mentira tranquilizadora)
 * ou de vermelho (acusação falsa) um município sobre o qual não sabemos nada.
 *
 * ⚠️ E NUNCA AFIRMAR QUE O BLOQUEIO JÁ ACONTECEU. Nós vemos a AUSÊNCIA de
 * registro, não a decisão do Estado — o convenente pode ter sido notificado, ter
 * prazo em curso ou ter regularizado por outra via. As frases vêm do servidor
 * justamente para que a tela não invente consequência.
 */

import React, { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Clock, Info, Loader2 } from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Bloco, BlocoHead, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

interface Pendencia {
  chave: string;
  convenio_id?: number | null;
  rotulo?: string | null;
  meses_em_atraso: number;
  competencias: string[];
  nivel: string;
  regime?: string | null;
  prazo?: string | null;
}

interface Resp {
  estado: "avaliado" | "nao_conectado";
  nivel: string;
  resumo: string;
  decreto?: string;
  pendencias: Pendencia[];
  em_dia?: number;
  avaliados?: number;
  regime?: string;
}

/** O tom segue a disciplina do resto do produto: cor SÓ onde há ação a tomar.
 *  Município em dia não vira tela verde. */
function tomDoNivel(nivel: string): "ok" | "atencao" | "critico" | "neutro" {
  if (nivel === "critico" || nivel === "bloqueio") return "critico";
  if (nivel === "atencao" || nivel === "alerta") return "atencao";
  if (nivel === "ok" || nivel === "em_dia") return "ok";
  return "neutro";
}

export default function MonitoramentoPage() {
  const { municipioId } = useMunicipio();
  const [d, setD] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const carregar = useCallback(() => {
    if (!municipioId) return;
    setLoading(true);
    api.get<Resp>("/monitoramento", { params: { municipio_id: municipioId } })
      .then((r) => setD(r.data)).catch(() => setD(null)).finally(() => setLoading(false));
  }, [municipioId]);
  // Busca de dados: o `setLoading` do callback acima é o "carregando" da
  // primeira pintura e a limpeza ao trocar de município — sincronização com
  // fonte externa, não render em cascata (mesma convenção do resto do app).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(carregar, [carregar]);

  if (!municipioId) return <Vazio>Selecione um município.</Vazio>;
  if (loading && !d) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" /> carregando…
      </div>
    );
  }
  if (!d) return <Vazio>Não foi possível carregar o monitoramento.</Vazio>;

  const naoConectado = d.estado === "nao_conectado";
  const tom = naoConectado ? "neutro" : tomDoNivel(d.nivel);
  const critico = tom === "critico";
  const atencao = tom === "atencao";

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <TituloTela>Monitoramento de Convênios</TituloTela>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          {d.decreto || "Decreto Estadual (RS) nº 56.939/2023"} — atualização mensal
          obrigatória até o dia 15, por convênio em execução.
        </p>
      </div>

      {/* O veredito. Cartão inteiro colorido só quando há o que fazer — mesma
          regra do `Situacao` da tela de Regularidade. */}
      <Bloco
        className="p-4"
        style={critico ? {
          background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
          borderColor: "color-mix(in oklab, var(--bi-crit) 28%, transparent)",
        } : atencao ? {
          background: "color-mix(in oklab, var(--bi-warn) 12%, transparent)",
          borderColor: "color-mix(in oklab, var(--bi-warn) 28%, transparent)",
        } : undefined}
      >
        <BlocoHead
          icon={naoConectado ? Info : critico ? AlertTriangle : atencao ? Clock : Check}
          titulo={
            <span style={critico ? { color: "var(--bi-crit-ink)" }
              : atencao ? { color: "var(--bi-warn-ink)" } : undefined}>
              {naoConectado ? "Ainda não conectado"
                : critico ? "Atraso que pode suspender parcelas"
                  : atencao ? "Atraso a regularizar"
                    : "Registros em dia"}
            </span>
          }
          /* A FRASE VEM DO SERVIDOR. É lá que mora a disciplina de não afirmar
             que o bloqueio já aconteceu — a tela não reescreve consequência. */
          sub={d.resumo}
          right={!naoConectado && d.avaliados
            ? <Selo tom={tom === "neutro" ? undefined : tom}>
                {`${d.em_dia ?? 0} de ${d.avaliados} em dia`}
              </Selo>
            : undefined}
        />
        {d.regime === "calamidade" && (
          /* A exceção que evita o alarme falso: município em calamidade
             reconhecida tem 120 dias, não o dia 15 (Nota Técnica SPGG). O
             sistema já respeita isso via `municipios.calamidade_ate`; a tela
             precisa DIZER, senão o gestor acha que o cálculo está errado. */
          <p className="px-1 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
            Este município está em <b>calamidade reconhecida</b>: o prazo aplicado é
            o excepcional de 120 dias, não o dia 15 de cada mês.
          </p>
        )}
      </Bloco>

      {naoConectado ? (
        <Bloco className="p-4">
          <BlocoHead icon={Info} titulo="O que falta para ligar" />
          <p className="px-1 text-[12px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            O registro mensal acontece dentro do <b>Portal de Convênios e Parcerias</b>{" "}
            do Estado, que exige conta gov.br com o perfil <b>PCPRS</b> — não há
            consulta pública desses lançamentos. Assim que essa credencial for
            cadastrada no Cofre, os prazos deste decreto passam a ser acompanhados
            aqui, convênio a convênio.
          </p>
          <p className="mt-2 px-1 text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
            Enquanto isso, a carteira de convênios estaduais que aparece em
            “Convênios” continua vindo do dado aberto da CAGE — o que falta é
            apenas o registro <i>mensal</i> de execução, que só existe na área logada.
          </p>
        </Bloco>
      ) : d.pendencias.length ? (
        <Bloco className="p-3">
          <BlocoHead
            icon={AlertTriangle}
            titulo="Convênios com competência em aberto"
            sub="cada mês sem registro conta para o limite de três do decreto"
          />
          <Lista>
            {d.pendencias.map((p) => (
              <li key={p.chave} className="py-1.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="min-w-0 text-[12px]" style={{ color: "var(--bi-text)" }}>
                    {p.rotulo || p.chave}
                  </span>
                  <Selo tom={tomDoNivel(p.nivel) === "neutro" ? undefined : tomDoNivel(p.nivel)}>
                    {p.meses_em_atraso === 1
                      ? "1 mês em aberto"
                      : `${p.meses_em_atraso} meses em aberto`}
                  </Selo>
                </div>
                {/* AS COMPETÊNCIAS, uma a uma. "3 meses em atraso" manda o gestor
                    procurar quais; a lista resolve o problema em vez de anunciá-lo. */}
                {!!p.competencias?.length && (
                  <div className="mt-0.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                    Competências: {p.competencias.join(" · ")}
                  </div>
                )}
                {p.prazo && (
                  <div className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    Prazo do mês corrente: {p.prazo}
                  </div>
                )}
              </li>
            ))}
          </Lista>
        </Bloco>
      ) : (
        <Bloco className="p-4">
          <BlocoHead
            icon={Check}
            titulo="Nenhuma competência em aberto"
            sub={`${d.avaliados ?? 0} convênio(s) em execução avaliado(s)`}
          />
        </Bloco>
      )}

      <Bloco className="p-3">
        <BlocoHead icon={Info} titulo="O que o decreto prevê" />
        <p className="px-1 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          O registro é mensal, até o dia 15, para cada convênio em execução, e inclui
          o status (licitando, contratando, executando), o percentual de execução
          física e fotos. A ausência de atualização por <b>três meses consecutivos</b>{" "}
          implica, segundo a norma, suspensão das parcelas, indeferimento de pedido de
          prorrogação e impedimento de celebrar novos convênios com o Estado.
        </p>
      </Bloco>
    </div>
  );
}
