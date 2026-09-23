"use client";

/* SAIU NO DOU — o gatilho de captação dentro do Radar.
 *
 * O Radar mostra a porta aberta no TransfereGov; este bloco mostra o que o
 * Diário Oficial da União publicou sobre o município nos últimos 30 dias e que
 * pede ação: repasse autorizado, habilitação, resultado de seleção,
 * reconhecimento de emergência. A portaria sai no DOU antes de aparecer em
 * qualquer sistema — é por isso que ela mora na tela que olha para frente.
 *
 * ⚠️ Fica de fora o ato que cita a cidade só como endereço (UFSM, vara federal):
 * o backend (`/dou-federal/alertas`) já não manda.
 *
 * ⚠️ O BLOCO SOME SEM FAZER BARULHO quando a pessoa não pode vê-lo (403) ou a
 * rota falha: é um complemento do Radar, e um erro nele não pode derrubar os
 * programas abertos logo abaixo.
 */

import React, { useEffect, useState } from "react";
import { ExternalLink, Newspaper } from "lucide-react";
import Link from "next/link";

import api from "@/lib/api";
import { Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { type AtoDou, CATEGORIA_DOU, EVIDENCIA_DOU, dataDou } from "@/lib/dou";

interface Resp {
  coletado: boolean;
  conferido_ate: string | null;
  dias: number;
  itens: AtoDou[];
}

export function AlertasDou({ municipioId }: { municipioId: string }) {
  const [d, setD] = useState<Resp | null>(null);

  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/dou-federal/alertas", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setD(r.data); })
      .catch(() => { if (vivo) setD(null); });
    return () => { vivo = false; };
  }, [municipioId]);

  if (!d) return null;

  return (
    <Bloco className="p-3">
      <BlocoHead
        icon={Newspaper}
        titulo="Saiu no Diário Oficial da União"
        sub={`repasse, habilitação, seleção e emergência dos últimos ${d.dias} dias`
          + (d.conferido_ate ? ` · conferido até ${dataDou(d.conferido_ate)}` : "")}
        right={
          <Link href="/dashboard/dou" className="text-[11px] underline"
                style={{ color: "var(--bi-accent-ink)" }}>
            todos os atos
          </Link>
        }
      />
      {d.itens.length === 0 ? (
        <Vazio>
          {d.coletado
            ? `Nenhum ato de captação citou o município no DOU nos últimos ${d.dias} dias.`
            : "O DOU deste município ainda não foi coletado — assim que a primeira rodada noturna terminar, os atos aparecem aqui."}
        </Vazio>
      ) : (
        <Lista>
          {d.itens.map((a) => (
            <ItemLinha
              key={a.id}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>{a.ementa || a.titulo || a.tipo_ato}</span>
                  <Selo tom="acento">{CATEGORIA_DOU[a.categoria]?.label || a.categoria}</Selo>
                </span>
              }
              valor={dataDou(a.data_publicacao)}
              meta={
                <>
                  {a.titulo && a.ementa && <span>{a.titulo}</span>}
                  {a.orgao && <span>· {a.orgao}</span>}
                  <span>· {EVIDENCIA_DOU[a.evidencia] || a.evidencia}</span>
                </>
              }
              acao={
                <a href={a.url} target="_blank" rel="noopener noreferrer"
                   title="Abrir o ato no site da Imprensa Nacional"
                   aria-label="Abrir o ato no site da Imprensa Nacional"
                   className="inline-flex size-8 items-center justify-center rounded-md"
                   style={{ color: "var(--bi-muted)" }}>
                  <ExternalLink className="size-4" />
                </a>
              }
            />
          ))}
        </Lista>
      )}
    </Bloco>
  );
}
