"use client";

/* OUTROS CONVENENTES NO MUNICÍPIO — os convênios estaduais de quem está na cidade
 * e NÃO é a prefeitura (APAE, associação, câmara).
 *
 * Regra do dono (reafirmada em 23/09/2026 para o PR): nada é descartado, mas nada
 * entra na conta como se fosse da prefeitura. Por isso o bloco é SEPARADO e
 * recolhido, lê uma rota própria (`/convenios/outros-convenentes`) e nenhum total
 * da tela — nem de outra tela — soma estas linhas. Em Juranda, 6 dos 26
 * convênios estaduais de 2026 são da APAE local.
 *
 * Some quando não há nada: município de estado cujo coletor ainda não grava aqui
 * (hoje só o PR grava) não ganha um bloco vazio.
 */

import React, { useEffect, useState } from "react";
import { ChevronDown, Users } from "lucide-react";

import api from "@/lib/api";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, situacaoTom } from "@/components/ui/superficies";
import { formatCurrency } from "@/lib/utils";

interface Outro {
  chave: string;
  convenente: string | null;
  orgao: string | null;
  objeto: string | null;
  situacao: string | null;
  valor_concedente: number | null;
  valor_repassado: number | null;
  valor_total?: number | null;
  dt_assinatura: string | null;
  dt_vigencia_final: string | null;
  numero: string | null;
}

function dia(iso?: string | null): string {
  if (!iso) return "—";
  const dt = new Date(`${iso.slice(0, 10)}T00:00:00`);
  return Number.isNaN(dt.getTime()) ? "—" : dt.toLocaleDateString("pt-BR");
}
const moeda = (v: number | null) => (v == null ? "—" : formatCurrency(v));

export function OutrosConvenentes({ municipioId }: { municipioId: string }) {
  const [itens, setItens] = useState<Outro[] | null>(null);
  const [aberto, setAberto] = useState(false);

  useEffect(() => {
    let vivo = true;
    api.get<Outro[]>("/convenios/outros-convenentes", { params: { municipio_id: municipioId } })
      .then((r) => { if (vivo) setItens(r.data); })
      .catch(() => { if (vivo) setItens([]); });
    return () => { vivo = false; };
  }, [municipioId]);

  if (!itens || itens.length === 0) return null;

  return (
    <Bloco className="p-3">
      <button type="button" className="w-full text-left" onClick={() => setAberto(!aberto)}
              aria-expanded={aberto}>
        <BlocoHead
          icon={Users}
          titulo={`Outros convenentes no município · ${itens.length}`}
          sub="APAE, associações e outras entidades com convênio estadual — não é a prefeitura e fica fora das contas desta tela"
          right={<ChevronDown className={`size-4 transition-transform ${aberto ? "rotate-180" : ""}`} />}
        />
      </button>
      {aberto && (
        <Lista>
          {itens.map((o) => (
            <ItemLinha
              key={o.chave}
              titulo={
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span>{o.objeto || "Sem objeto informado"}</span>
                  {o.situacao && <Selo tom={situacaoTom(o.situacao)}>{o.situacao.toLowerCase()}</Selo>}
                  <Selo>não é a prefeitura</Selo>
                </span>
              }
              // O TO não separa a parte do Estado: sem ela, o total da fonte.
              valor={moeda(o.valor_concedente ?? o.valor_total ?? null)}
              meta={
                <>
                  {o.convenente && <span>{o.convenente}</span>}
                  {o.orgao && <span>· {o.orgao}</span>}
                  {o.numero && <span className="font-mono">· nº {o.numero}</span>}
                </>
              }
            >
              <Campos campos={[
                { rotulo: "Repassado", valor: moeda(o.valor_repassado) },
                { rotulo: "Assinatura", valor: dia(o.dt_assinatura) },
                { rotulo: "Vigência até", valor: dia(o.dt_vigencia_final) },
              ]} />
            </ItemLinha>
          ))}
        </Lista>
      )}
    </Bloco>
  );
}
