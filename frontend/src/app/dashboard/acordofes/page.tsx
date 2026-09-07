"use client";

import React, { useEffect, useState } from "react";
import { Search as SearchIcon, Loader2, Building2 } from "lucide-react";
import api from "@/lib/api";
import { formatCurrency } from "@/lib/utils";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { NOME_UF } from "@/lib/estadual";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Bloco,
  BlocoHead,
  Campos,
  ItemLinha,
  Lista,
  Numero,
  Selo,
  Vazio,
} from "@/components/ui/superficies";
import { TituloTela } from "@/components/TituloTela";

interface Credor {
  cnpj: string;
  razao_social: string;
  divida_inicial: number;
  total_pago: number;
  divida_atual: number;
  n_empenhos: number;
}
interface MunResp {
  credores: Credor[];
  total_divida_atual: number;
  total_pago: number;
  total_divida_inicial: number;
}

function maskCnpj(v: string): string {
  const d = (v || "").replace(/\D/g, "");
  if (d.length !== 14) return v || "-";
  return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, "$1.$2.$3/$4-$5");
}

/** Cor no selo SO quando ela e um alerta — mesma regra de Convenios e Emendas.
 *
 *  Esta tela nao tem coluna de situacao: o Acordo FES entrega so valores. O
 *  unico estado que existe e derivado do saldo, e por isso o helper recebe o
 *  numero, nao um texto. Saldo zerado = divida quitada, o caso raro e a unica
 *  coisa aqui que merece cor. Saldo em aberto e o normal desta base (quase
 *  todos os credores), entao pintar seria pintar a tela inteira — que e
 *  exatamente o que a identidade veio desfazer. */
function saldoTom(dividaAtual: number): "neutro" | "ok" {
  return dividaAtual <= 0 ? "ok" : "neutro";
}

/** O credor como cartao. As duas listas da tela (o fundo municipal e a busca
 *  livre) usam ESTE mesmo item de proposito: eram um cartao improvisado e uma
 *  tabela de 5 colunas mostrando o mesmo registro de dois jeitos diferentes.
 *
 *  A antiga tabela da busca tinha Credor / CNPJ / Divida inicial / Pago /
 *  Divida atual; o antigo cartao do municipio tinha razao social, CNPJ e nº de
 *  empenhos. Nada disso se perdeu — trocou de posicao. */
function CredorItem({ c }: { c: Credor }) {
  const quitado = c.divida_atual <= 0;
  // % quitado nao existe no backend: e leitura direta de pago/inicial e e o
  // que o gestor de fato pergunta ("quanto ja veio?"). Sem divida inicial nao
  // ha percentual possivel — melhor um traco do que um numero inventado.
  const pct = c.divida_inicial > 0 ? Math.round((c.total_pago / c.divida_inicial) * 100) : null;
  return (
    <ItemLinha
      titulo={c.razao_social || "Credor sem razão social informada"}
      valor={formatCurrency(c.divida_atual)}
      meta={
        <>
          {/* Só aparece quando é verdade. Um selo "Em aberto" cinza em todas as
              linhas não classificaria nada — o próprio valor já diz. */}
          {quitado && <Selo tom={saldoTom(c.divida_atual)}>Quitado</Selo>}
          <span className="font-mono">{maskCnpj(c.cnpj)}</span>
        </>
      }
    >
      <Campos
        campos={[
          { rotulo: "Dívida inicial", valor: formatCurrency(c.divida_inicial) },
          { rotulo: "Total pago", valor: formatCurrency(c.total_pago) },
          {
            rotulo: "% quitado",
            valor: pct != null ? `${pct}%` : "—",
            tom: pct != null && pct >= 100 ? "ok" : "normal",
            title:
              pct != null
                ? `${formatCurrency(c.total_pago)} de ${formatCurrency(c.divida_inicial)}`
                : "Sem dívida inicial registrada",
          },
          { rotulo: "Empenhos", valor: Number(c.n_empenhos || 0).toLocaleString("pt-BR") },
        ]}
      />
    </ItemLinha>
  );
}

export default function AcordoFesPage() {
  const { municipioId } = useMunicipio();
  const ufAmbiente = useUfDoMunicipio();
  const [mun, setMun] = useState<MunResp | null>(null);
  const [loading, setLoading] = useState(true);

  const [q, setQ] = useState("");
  const [busca, setBusca] = useState<Credor[] | null>(null);
  const [buscando, setBuscando] = useState(false);

  useEffect(() => {
    if (!municipioId) { setMun(null); setLoading(false); return; }
    // Programa de MG: para municipio de outro estado nao ha o que buscar —
    // e nada a gravar aqui: a guarda de render resolve a tela sozinha.
    if (ufAmbiente && ufAmbiente !== "MG") return;
    setLoading(true);
    api.get<MunResp>("/acordofes", { params: { municipio_id: municipioId } })
      .then((r) => setMun(r.data))
      .catch(() => setMun(null))
      .finally(() => setLoading(false));
  }, [municipioId, ufAmbiente]);

  const buscar = async () => {
    if (q.trim().length < 2) return;
    setBuscando(true);
    try {
      const r = await api.get<{ items: Credor[] }>("/acordofes/buscar", { params: { q: q.trim() } });
      setBusca(r.data.items);
    } catch { setBusca([]); }
    finally { setBuscando(false); }
  };

  // Lista achatada para o JSX não precisar repetir a checagem de nulo a cada
  // uso. `formatCurrency` já devolve "R$ 0,00" para nulo, então os totais podem
  // ser lidos com `?.` sem ganhar asserção `!`.
  const credores = mun?.credores ?? [];
  const dividaAtualTotal = mun?.total_divida_atual ?? 0;

  /* O menu ja esconde esta tela fora de MG — a guarda cobre navegacao direta
     por URL, que nao passa pelo menu. */
  if (ufAmbiente && ufAmbiente !== "MG") {
    return (
      <div className="rounded-lg border p-6 text-sm"
           style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}>
        O Acordo FES é um programa do Estado de Minas Gerais (dívida do Fundo
        Estadual de Saúde com credores mineiros). Não se aplica a municípios de{" "}
        {NOME_UF[ufAmbiente] || ufAmbiente}.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <TituloTela>Acordo FES — Dívida da Saúde (SES-MG)</TituloTela>
        <p className="text-sm text-base-content/60 mt-1">
          Dívida do Fundo Estadual de Saúde de MG com os credores da saúde (fundos
          municipais, hospitais, consórcios). Fonte: Painel do Acordo FES (SES-MG).
        </p>
      </div>

      {/* Município selecionado */}
      {municipioId && loading && (
        <div className="flex justify-center py-12">
          <Loader2 className="size-7 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      )}
      {municipioId && !loading && (
        <>
          {credores.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-3">
              <Numero
                rotulo="Dívida inicial (2009-2020)"
                valor={formatCurrency(mun?.total_divida_inicial)}
              />
              {/* "Total pago" era verde. Dinheiro que já entrou não é alerta:
                  fica neutro. O saldo é o único KPI que pode ganhar cor — e pela
                  MESMA regra do selo do cartão (`saldoTom`), senão o topo da tela
                  e a lista abaixo julgariam o mesmo saldo de formas diferentes:
                  âmbar permanente aqui, cinza lá. Dívida em aberto é o estado
                  normal desta base, então só o saldo zerado se destaca. */}
              <Numero rotulo="Total pago no acordo" valor={formatCurrency(mun?.total_pago)} />
              <Numero
                rotulo="Dívida atual"
                valor={formatCurrency(dividaAtualTotal)}
                tom={saldoTom(dividaAtualTotal)}
              />
            </div>
          )}

          <Bloco className="p-3">
            <BlocoHead
              icon={Building2}
              titulo="Fundo Municipal de Saúde deste município"
              sub={
                credores.length > 0
                  ? `${credores.length} credor(es) vinculado(s) ao município selecionado`
                  : undefined
              }
            />
            {credores.length > 0 ? (
              <Lista>
                {credores.map((c) => (
                  <CredorItem key={c.cnpj} c={c} />
                ))}
              </Lista>
            ) : (
              <Vazio>
                Nenhum débito do Acordo FES vinculado ao fundo municipal de saúde deste município.
              </Vazio>
            )}
          </Bloco>
        </>
      )}

      {/* Busca livre por credor — não é limitada ao município selecionado */}
      <Bloco className="p-3">
        <BlocoHead
          icon={SearchIcon}
          titulo="Buscar qualquer credor (hospital, consórcio, Santa Casa…)"
          sub="A busca varre todos os credores do Acordo FES, fora do recorte do município."
        />
        <div className="flex gap-2">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && buscar()}
            placeholder="Nome ou CNPJ do credor"
            className="max-w-md"
          />
          {/* Sem `bg-primary` na mão: a variante padrão do Button já é primária,
              e a classe só duplicava a decoração. */}
          <Button
            onClick={buscar}
            disabled={buscando || q.trim().length < 2}
            title="Buscar credor"
            aria-label="Buscar credor"
          >
            {buscando ? <Loader2 className="size-4 animate-spin" /> : <SearchIcon className="size-4" />}
          </Button>
        </div>
        {busca !== null && (
          busca.length === 0 ? (
            <div className="mt-3">
              <Vazio>Nenhum credor encontrado.</Vazio>
            </div>
          ) : (
            /* Mesma <Lista> do bloco de cima: a busca deixou de ser tabela e o
               resultado passa a ser lido exatamente como o do município. */
            <Lista className="mt-3">
              {busca.map((c, i) => (
                <CredorItem key={c.cnpj + i} c={c} />
              ))}
            </Lista>
          )
        )}
      </Bloco>
    </div>
  );
}
