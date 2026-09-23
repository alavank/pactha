"use client";

/* DOU FEDERAL — os atos do Diário Oficial da União que citam o município.
 *
 * Diferente da aba do diário do estado (busca em tempo real, texto livre), aqui
 * é COLETA: toda noite o coletor busca o município e guarda só o ato que o cita
 * com evidência forte (IBGE, CNPJ, "Município de X/UF", ou publicado pela
 * própria prefeitura). É o gatilho da captação: a portaria sai no DOU antes de
 * aparecer em qualquer sistema.
 *
 * ⚠️ "CITADO COMO ENDEREÇO" FICA ESCONDIDO POR PADRÃO. Em Santa Maria/RS, 20 de
 * 28 atos em 14 dias eram UFSM, Exército, vara federal — a cidade, e não a
 * prefeitura. A caixa de marcar mostra quantos são, para ninguém achar que
 * foram perdidos.
 *
 * ⚠️ "Ainda não coletado" e "nenhum ato" são estados DIFERENTES, como no Radar:
 * o primeiro é pendência nossa, e a frase diz isso.
 */

import React, { useEffect, useMemo, useState } from "react";
import { ExternalLink, Loader2, Newspaper, Search } from "lucide-react";

import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Abas, Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio,
} from "@/components/ui/superficies";
import {
  type AtoDou, type CategoriaDou, CATEGORIA_DOU, EVIDENCIA_DOU, dataDou, secaoDou,
} from "@/lib/dou";

interface Resp {
  coletado: boolean;
  conferido_ate: string | null;
  total: number;
  pagina: number;
  total_paginas: number;
  por_categoria: Partial<Record<CategoriaDou, number>>;
  mencoes_cidade: number;
  itens: AtoDou[];
}

type Filtro = "todas" | CategoriaDou;
const PERIODOS = [
  { valor: "30", label: "30 dias" },
  { valor: "90", label: "90 dias" },
  { valor: "365", label: "12 meses" },
] as const;
type Periodo = (typeof PERIODOS)[number]["valor"];

const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR = { color: "var(--bi-muted)" } as const;

export function DouFederal({ municipioId }: { municipioId: string }) {
  const [filtro, setFiltro] = useState<Filtro>("todas");
  const [periodo, setPeriodo] = useState<Periodo>("90");
  const [cidade, setCidade] = useState(false);
  const [texto, setTexto] = useState("");
  const [textoAplicado, setTextoAplicado] = useState("");
  const [pagina, setPagina] = useState(1);
  const params = useMemo(() => ({
    municipio_id: municipioId,
    categoria: filtro === "todas" ? undefined : filtro,
    incluir_cidade: cidade,
    texto: textoAplicado || undefined,
    dias: Number(periodo),
    pagina,
  }), [municipioId, filtro, cidade, textoAplicado, periodo, pagina]);
  /* O último pedido que RESPONDEU, com a chave dele. "Carregando" é derivado —
     a chave pedida ainda não é a respondida — em vez de um setState síncrono
     no efeito. E a lista anterior fica na tela enquanto a nova não chega. */
  const [resposta, setResposta] = useState<{ chave: string; d: Resp | null; erro: string | null } | null>(null);
  const chave = JSON.stringify(params);
  useEffect(() => {
    let vivo = true;
    api.get<Resp>("/dou-federal/atos", { params })
      .then((r) => { if (vivo) setResposta({ chave: JSON.stringify(params), d: r.data, erro: null }); })
      .catch((e) => {
        if (!vivo) return;
        setResposta({
          chave: JSON.stringify(params), d: null,
          erro: e?.response?.status === 403
            ? "Você não tem permissão para ver o Diário Oficial (peça «Diário Oficial → Ver» ao administrador)."
            : "Não foi possível carregar os atos do DOU.",
        });
      });
    return () => { vivo = false; };
  }, [params]);
  const loading = resposta?.chave !== chave;
  const d = resposta?.d ?? null;
  const erro = resposta?.erro ?? null;

  // Trocar filtro volta para a página 1: a página 4 de "Repasse" não existe em
  // "Habilitação", e a tela abriria vazia.
  const mudar = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPagina(1); };

  const total = Object.values(d?.por_categoria || {}).reduce((a, b) => a + (b || 0), 0);
  const opcoes: Array<{ valor: Filtro; label: string }> = [
    { valor: "todas", label: `Todos · ${total}` },
    ...(Object.keys(CATEGORIA_DOU) as CategoriaDou[])
      .filter((c) => (d?.por_categoria?.[c] || 0) > 0 || c === filtro)
      .map((c) => ({ valor: c, label: `${CATEGORIA_DOU[c].label} · ${d?.por_categoria?.[c] || 0}` })),
  ];

  return (
    <div className="space-y-4">
      <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
        Imprensa Nacional (in.gov.br) · coletado toda noite
        {d?.conferido_ate ? ` · conferido até ${dataDou(d.conferido_ate)}` : ""}
        {" "}· entra o ato que cita o município pelo código IBGE, pelo CNPJ, como
        “Município de …/UF”, ou que foi publicado pela própria prefeitura
      </p>

      <Bloco className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[14rem] flex-1">
            <label className={ROTULO} style={ROTULO_COR}>Filtrar por palavra</label>
            <Input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder="Ex: Defesa Civil, PSE, Ministério da Saúde"
              onKeyDown={(e) => {
                if (e.key === "Enter") { setTextoAplicado(texto.trim()); setPagina(1); }
              }}
            />
          </div>
          <Button size="sm" onClick={() => { setTextoAplicado(texto.trim()); setPagina(1); }}>
            <Search className="mr-2 size-4" /> Filtrar
          </Button>
          <Abas valor={periodo} onChange={mudar(setPeriodo)}
                opcoes={PERIODOS.map((p) => ({ valor: p.valor, label: p.label }))} />
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <Abas valor={filtro} onChange={mudar(setFiltro)} opcoes={opcoes} />
          <label className="flex cursor-pointer select-none items-center gap-2 text-[11px]"
                 style={ROTULO_COR}>
            <input type="checkbox" checked={cidade}
                   onChange={(e) => { setCidade(e.target.checked); setPagina(1); }} />
            incluir citações só como endereço
            {d && d.mencoes_cidade > 0 ? ` (${d.mencoes_cidade})` : ""}
          </label>
        </div>
      </Bloco>

      {erro && (
        <div role="alert" className="bi-card-flat px-3 py-2.5 text-[12px]"
             style={{ color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {loading && !d && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> carregando…
        </div>
      )}

      {d && (
        <Bloco className="p-3">
          <BlocoHead
            icon={Newspaper}
            titulo={`${d.total.toLocaleString("pt-BR")} ato(s) no DOU`}
            sub={`do mais recente para o mais antigo · últimos ${
              PERIODOS.find((p) => p.valor === periodo)?.label}`}
            right={loading ? <Loader2 className="size-4 animate-spin" /> : undefined}
          />
          {d.itens.length === 0 ? (
            <Vazio>
              {!d.coletado
                ? "O DOU deste município ainda não foi coletado — assim que a primeira rodada noturna terminar, os atos aparecem aqui. Isto não significa que não saiu nada."
                : textoAplicado || filtro !== "todas"
                  ? "Nenhum ato com esse filtro no período."
                  : "Nenhum ato do DOU citou o município no período."}
            </Vazio>
          ) : (
            <Lista>
              {d.itens.map((a) => {
                const cat = CATEGORIA_DOU[a.categoria] || CATEGORIA_DOU.outros;
                return (
                  <ItemLinha
                    key={a.id}
                    titulo={
                      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span>{a.titulo || a.tipo_ato || "Ato sem título"}</span>
                        <Selo tom={cat.captacao ? "acento" : "neutro"}>{cat.label}</Selo>
                      </span>
                    }
                    valor={dataDou(a.data_publicacao)}
                    meta={
                      <>
                        {a.orgao && <span>{a.orgao}</span>}
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
                  >
                    {a.ementa && (
                      <p className="mt-1.5 text-[12px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                        {a.ementa}
                      </p>
                    )}
                    {/* O trecho é onde o município aparece — numa portaria com a
                        tabela dos 5.570 municípios, é a linha dele (e o valor). */}
                    {a.trecho && (
                      <p className="mt-1.5 rounded px-2 py-1.5 text-[11px] leading-relaxed"
                         style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}>
                        {a.trecho}
                      </p>
                    )}
                    <Campos campos={[
                      { rotulo: "Tipo", valor: a.tipo_ato || "—" },
                      { rotulo: "Edição", valor: `${secaoDou(a.secao)}${a.edicao ? ` · nº ${a.edicao}` : ""}` },
                      { rotulo: "Página", valor: a.pagina || "—" },
                    ]} />
                  </ItemLinha>
                );
              })}
            </Lista>
          )}
          {d.total_paginas > 1 && (
            <div className="mt-3 flex items-center justify-between border-t pt-3"
                 style={{ borderColor: "var(--bi-line)" }}>
              <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Página {d.pagina} de {d.total_paginas}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" disabled={pagina <= 1 || loading}
                        onClick={() => setPagina(pagina - 1)}>Anterior</Button>
                <Button variant="outline" size="sm"
                        disabled={pagina >= d.total_paginas || loading}
                        onClick={() => setPagina(pagina + 1)}>Próximo</Button>
              </div>
            </div>
          )}
        </Bloco>
      )}
    </div>
  );
}
