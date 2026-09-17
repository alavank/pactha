"use client";

/* A ABA ESTADUAIS — o que o estado do município publica, e nada além disso.
 *
 *   MG  a tela de Emendas Estaduais (SIGCON-MG), inteira, como era;
 *   RS  o conteúdo curado (o Estado publica em Power BI fechado);
 *   GO  os repasses cuja descrição cita o autor (a fonte é o pagamento);
 *   ES e os demais: a frase do servidor dizendo por que não há lista.
 *
 * ⚠️ NUNCA UMA LISTA VAZIA MUDA. Vazio é lido como "o município não recebeu
 * emenda estadual", e isso a fonte não disse.
 *
 * ⚠️ A PERMISSÃO É A DA TELA QUE JÁ DAVA ESTE DADO (decisão do dono, 17/09/2026):
 * MG `emendas`, RS `emendas_rs`, GO `repasses`. Quem decide se a aba aparece é a
 * página; o servidor cobra de novo.
 */

import React, { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import api from "@/lib/api";
import { Aviso, Bloco, BlocoHead, ItemLinha, Lista, Numero, Vazio } from "@/components/ui/superficies";
import AbaEstaduaisMG from "@/components/emendas/AbaEstaduaisMG";
import AbaEstaduaisRS from "@/components/emendas/AbaEstaduaisRS";
import { SeloCadastro } from "@/components/emendas/AbaParlamentares";
import { brl, type Autor, type Origem } from "@/components/emendas/DetalheEmenda";

interface Repasse {
  id: number; chave: string; data_repasse: string | null; valor: number | null;
  credor: string | null; orgao: string | null; descricao: string | null;
  emenda_numero: string | null; emenda_autor: string | null; parlamentares: Autor[];
}
interface Resp {
  uf: string; fonte: string | null; motivo: string | null;
  items: Repasse[]; totais: { emendas: number; valor: number };
}

/** A tela que cobra a permissão de cada UF — a mesma de `TELA_ESTADUAL_POR_UF`
 *  no servidor. */
export const TELA_ESTADUAL_POR_UF: Record<string, string> = { MG: "emendas", RS: "emendas_rs", GO: "repasses" };

function Goias({ municipioId, onAbrir }: { municipioId: string; onAbrir: (o: Origem, id: string) => void }) {
  const [res, setRes] = useState<{ mun: string; d: Resp | null; erro: string | null } | null>(null);
  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/emendas-parlamentares/estaduais", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setRes({ mun: municipioId, d: r.data, erro: null }); })
      .catch((e) => {
        if (vivo) setRes({ mun: municipioId, d: null, erro: e?.response?.data?.detail || "Não foi possível carregar." });
      });
    return () => { vivo = false; };
  }, [municipioId]);

  if (res?.mun !== municipioId) {
    return <div className="flex items-center gap-2 py-6 text-[13px]" style={{ color: "var(--bi-muted)" }}>
      <Loader2 className="size-4 animate-spin" /> Carregando emendas estaduais…</div>;
  }
  const d = res.d;
  if (!d) return <Vazio>{res.erro}</Vazio>;
  return (
    <div className="flex flex-col gap-4">
      {d.motivo && <Aviso tom="atencao" titulo="O que esta lista cobre">{d.motivo}</Aviso>}
      {d.fonte && (
        <div className="grid grid-cols-2 gap-3">
          <Numero rotulo="Repasses com autor" valor={d.totais.emendas} sub={d.fonte} />
          <Numero rotulo="Valor pago" valor={brl(d.totais.valor)} />
        </div>
      )}
      {!!d.items.length && (
        <Bloco className="p-3">
          <BlocoHead titulo="Repasses que citam o parlamentar" sub="do mais recente para o mais antigo" />
          <Lista>
            {d.items.map((x) => (
              <ItemLinha key={x.chave} onClick={() => onAbrir("go", String(x.id))}
                titulo={<span className="flex flex-wrap items-center gap-1.5">
                  {x.emenda_autor}
                  {x.parlamentares.map((p) => <SeloCadastro key={p.nome} c={p.cadastro} />)}
                </span>}
                valor={<span className="bi-num">{brl(x.valor)}</span>}
                meta={[x.data_repasse ? new Date(`${x.data_repasse}T12:00:00`).toLocaleDateString("pt-BR") : null,
                       x.orgao, x.emenda_numero ? `emenda ${x.emenda_numero}` : null].filter(Boolean).join(" · ")} />
            ))}
          </Lista>
        </Bloco>
      )}
    </div>
  );
}

function SemFonte({ municipioId }: { municipioId: string }) {
  const [motivo, setMotivo] = useState<string | null>(null);
  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/emendas-parlamentares/estaduais", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setMotivo(r.data.motivo); })
      .catch(() => { if (vivo) setMotivo("Não foi possível carregar."); });
    return () => { vivo = false; };
  }, [municipioId]);
  return <Vazio>{motivo ?? "carregando…"}</Vazio>;
}

export default function AbaEstaduais({ uf, municipioId, onAbrir }: {
  uf: string; municipioId: string; onAbrir: (o: Origem, id: string) => void;
}) {
  if (!municipioId) return <Vazio>Selecione um município para ver as emendas estaduais.</Vazio>;
  if (uf === "MG") return <AbaEstaduaisMG onAbrir={(id) => onAbrir("sigcon", String(id))} />;
  if (uf === "RS") return <AbaEstaduaisRS />;
  if (uf === "GO") return <Goias municipioId={municipioId} onAbrir={onAbrir} />;
  return <SemFonte municipioId={municipioId} />;
}
