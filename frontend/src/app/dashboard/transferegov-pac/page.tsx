"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Landmark, Loader2, Search, Eraser, ChevronDown, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";
import { MultiSelect } from "@/components/ui/multi-select";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";

interface PacItem {
  numero_proposta: string;
  programa: string | null;
  programa_codigo: string | null;
  proponente: string | null;
  cnpj: string | null;
  situacao: string | null;
  valor_repasse: number | null;
  valor_contrapartida: number | null;
  valor_total: number | null;
  emenda_parlamentar: string | null;
  qualificacao: string | null;
  objeto: string | null;
  justificativa: string | null;
}


/* Rotulo de controle (filtro/formulario). 11px em --bi-muted, com a dica em
   --bi-faint. Fica em 11px de proposito: 9px e 10px sao as escalas que <Campos>
   e a meta do <ItemLinha> usam para DADO, e emprestar essas escalas ao filtro
   faz o controle competir com o resultado. Mesmas constantes em `dou`. */
const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR = { color: "var(--bi-muted)" } as const;
const DICA_COR = { color: "var(--bi-faint)" } as const;

/** Ano vem do sufixo do numero da proposta ("56000006303/2023"). */
function anoDaProposta(numero?: string | null): string {
  const m = /\/(\d{4})\s*$/.exec(numero || "");
  return m ? m[1] : "";
}

export default function TransfereGovPacPage() {
  const { municipioId } = useMunicipio();
  const [items, setItems] = useState<PacItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState("");
  const [q, setQ] = useState("");
  const [situacoesSel, setSituacoesSel] = useState<string[]>([]);
  const [programasSel, setProgramasSel] = useState<string[]>([]);
  const [anosSel, setAnosSel] = useState<string[]>([]);
  /* Recolhido por ANO. Guarda o que esta FECHADO e nao o que esta aberto:
     assim um ano novo que chegue na proxima coleta nasce aberto. */
  const [anosFechados, setAnosFechados] = useState<Set<string>>(new Set());
  const [atualizado, setAtualizado] = useState<string | null>(null);

  const carregar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true); setErro("");
    try {
      const r = await api.get("/transferegov/pac", { params: { municipio_id: municipioId } });
      setItems(r.data.items || []);
      setAtualizado(r.data.atualizado || null);
    } catch {
      setErro("Erro ao carregar propostas PAC.");
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [municipioId]);

  useEffect(() => { carregar(); }, [carregar]);

  // Opcoes dos filtros saem dos DADOS carregados: o portal muda a grafia e
  // inventa programa novo, entao uma lista fixa envelheceria em silencio.
  const situacaoOpcoes = useMemo(
    () => Array.from(new Set(items.map((i) => i.situacao).filter(Boolean) as string[])).sort(),
    [items]
  );
  const programaOpcoes = useMemo(
    () => Array.from(new Set(items.map((i) => i.programa).filter(Boolean) as string[])).sort(),
    [items]
  );
  const anoOpcoes = useMemo(
    () => Array.from(new Set(items.map((i) => anoDaProposta(i.numero_proposta)).filter(Boolean)))
      .sort((a, b) => Number(b) - Number(a)),
    [items]
  );

  const termo = q.trim().toLowerCase();
  const filtrados = useMemo(() => items.filter((i) => {
    if (termo && ![i.numero_proposta, i.programa, i.situacao, i.emenda_parlamentar, i.objeto]
      .filter(Boolean).some((v) => (v as string).toLowerCase().includes(termo))) return false;
    if (situacoesSel.length && !situacoesSel.includes(i.situacao || "")) return false;
    if (programasSel.length && !programasSel.includes(i.programa || "")) return false;
    if (anosSel.length && !anosSel.includes(anoDaProposta(i.numero_proposta))) return false;
    return true;
  }), [items, termo, situacoesSel, programasSel, anosSel]);

  const total = filtrados.reduce((s, i) => s + (i.valor_total || 0), 0);

  /** Contagem por situacao do conjunto FILTRADO — some junto com o filtro. */
  const porSituacao = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of filtrados) {
      const k = i.situacao || "Sem situação";
      m.set(k, (m.get(k) || 0) + 1);
    }
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [filtrados]);

  /** Agrupado por ano, do mais recente para o mais antigo.
   *
   *  Mesmo desenho das Emendas Estaduais, que o dono escolheu como padrao do
   *  produto: cada ano e um cartao BRANCO com cabecalho (ano, contagem, total
   *  a direita) e a lista de itens cinza dentro, sobre o fundo cinza da pagina.
   *
   *  O ano vem de `anoDaProposta` — o MESMO campo que alimenta o filtro de
   *  anos, senao o gestor filtraria 2025 e veria um grupo 2024.
   *
   *  Proposta sem ano legivel nao some: cai num grupo "Sem ano" no fim. O
   *  numero do PAC as vezes chega sem o sufixo "/AAAA", e esconder a proposta
   *  por causa disso e pior que mostra-la separada. */
  const porAno = useMemo(() => {
    const m = new Map<string, PacItem[]>();
    for (const i of filtrados) {
      const a = anoDaProposta(i.numero_proposta) || "Sem ano";
      (m.get(a) ?? m.set(a, []).get(a)!).push(i);
    }
    return Array.from(m.entries()).sort((x, y) =>
      x[0] === "Sem ano" ? 1 : y[0] === "Sem ano" ? -1 : y[0].localeCompare(x[0]));
  }, [filtrados]);

  const alternarAno = (a: string) =>
    setAnosFechados((prev) => {
      const n = new Set(prev);
      if (n.has(a)) n.delete(a); else n.add(a);
      return n;
    });

  const temFiltro = !!termo || situacoesSel.length > 0 || programasSel.length > 0 || anosSel.length > 0;
  const limpar = () => { setQ(""); setSituacoesSel([]); setProgramasSel([]); setAnosSel([]); };

  return (
    /* Sem o `p-4` de antes: era a unica pagina do dashboard com padding proprio,
       entao o conteudo comecava 16px adentro em relacao a todas as vizinhas. */
    <div className="space-y-4">
      <div>
        {/* text-2xl como em Convenios, Emendas e as demais telas migradas — o
            titulo desta era o unico em text-xl. */}
        <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
          <Landmark className="size-6" style={{ color: "var(--bi-muted)" }} />
          Transfere Gov — Seleção PAC (Novo PAC)
        </h1>
        <p className="text-sm text-base-content/60 mt-1">
          Propostas do Novo PAC do município (TransfereGov / Acesso Livre).
          {atualizado ? ` · Atualizado: ${new Date(atualizado).toLocaleDateString("pt-BR")}` : ""}
        </p>
      </div>

      {/* Filtros: a tela so tinha uma busca por texto, e achar "as nao
          habilitadas de 2025" exigia ler tudo. Multi-selecao nos tres eixos que
          o gestor usa (situacao, programa, ano) — no cliente, porque o endpoint
          devolve as propostas do municipio de uma vez. */}
      <Bloco className="p-3">
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div>
            {/* Rotulo de controle na escala e nos tokens que as outras telas
                migradas usam (11px em --bi-muted, a dica em --bi-faint), em vez
                das opacidades do tema. Esta era a unica tela do lote que ainda
                escrevia `text-base-content/70` aqui. */}
            <label className={ROTULO} style={ROTULO_COR}>Buscar</label>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2" style={{ color: "var(--bi-faint)" }} />
              <Input className="pl-8" placeholder="Nº, programa, emenda, objeto..."
                value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>
              Situação <span style={DICA_COR}>(uma, algumas ou todas)</span>
            </label>
            <MultiSelect
              opcoes={situacaoOpcoes}
              valor={situacoesSel}
              onChange={setSituacoesSel}
              placeholder="Todas as situações"
              rotuloTodos="Todas"
              ariaLabel="Situação da proposta"
            />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>
              Anos <span style={DICA_COR}>(um, alguns ou o mandato)</span>
            </label>
            <MultiSelect
              opcoes={anoOpcoes}
              valor={anosSel}
              onChange={setAnosSel}
              atalhos={atalhosAnos()}
              formatarResumo={resumoAnos}
              placeholder="Todos os anos"
              rotuloTodos="Todos"
              ariaLabel="Ano da proposta"
            />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>
              Programa <span style={DICA_COR}>(um ou vários)</span>
            </label>
            <MultiSelect
              opcoes={programaOpcoes}
              valor={programasSel}
              onChange={setProgramasSel}
              placeholder="Todos os programas"
              rotuloTodos="Todos"
              ariaLabel="Programa"
            />
          </div>
        </div>

        <div
          className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3"
          style={{ borderColor: "var(--bi-line)" }}
        >
          <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            {filtrados.length} proposta(s) ·{" "}
            <span className="bi-num" style={{ color: "var(--bi-text)" }}>{formatCurrency(total)}</span>
          </span>
          {/* Resumo por situacao, clicavel para virar filtro — o numero que
              chamou a atencao ja leva ao recorte. Agora usa o MESMO selo da
              lista (cinza, cor so em alerta): o resumo e a lista tem de contar
              a mesma historia, senao o chip verde de cima nao acha nada verde
              embaixo. */}
          {porSituacao.map(([sit, n]) => {
            const ativo = situacoesSel.length === 1 && situacoesSel[0] === sit;
            return (
              <button
                key={sit}
                type="button"
                aria-pressed={ativo}
                onClick={() => setSituacoesSel(ativo ? [] : [sit])}
                title={`Filtrar por "${sit}"`}
                className="transition-opacity hover:opacity-70"
              >
                <Selo tom={situacaoTom(sit)}>
                  {sit} <span className="ml-1 font-semibold">{n}</span>
                </Selo>
              </button>
            );
          })}
          {temFiltro && (
            <Button variant="outline" size="sm" className="ml-auto" onClick={limpar}>
              <Eraser className="size-4" /> Limpar
            </Button>
          )}
        </div>
      </Bloco>

      {loading ? (
        <div className="flex justify-center py-10">
          <Loader2 className="size-6 animate-spin" style={{ color: "var(--bi-muted)" }} />
        </div>
      ) : erro ? (
        /* Falha de carga e alerta de verdade, entao aqui a cor e legitima — mas
           vem do token de critico, nao das classes decorativas do tema. */
        <div className="bi-card-flat px-4 py-3 text-[12px]" style={{ color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      ) : filtrados.length === 0 ? (
        <Vazio>
          Nenhuma proposta PAC para este município. (A coleta roda no cron; se acabou de subir, aguarde.)
        </Vazio>
      ) : (
        /* A LISTA DEIXOU DE SER TABELA.
           As cinco colunas continuam todas visiveis: programa virou o titulo,
           valor total o numero da direita, situacao um selo, e proposta/emenda
           foram para a meta — onde QUEBRAM A LINHA em vez de serem cortadas,
           que e a regra desta tela desde sempre (zero truncate).

           Os numeros ficam em <Campos>, em posicoes fixas iguais em todos os
           cartoes: e o que preserva a varredura vertical que a tabela dava.

           AS TRES CAMADAS: fundo cinza da pagina -> cartao BRANCO do ano ->
           itens cinza dentro. Os <ItemLinha> nao mudaram: continuam com todos
           os campos que a tabela tinha. */
        <div className="space-y-3">
        {porAno.map(([ano, doAno]) => {
          const fechado = anosFechados.has(ano);
          const totalAno = doAno.reduce((s, i) => s + (i.valor_total || 0), 0);
          return (
          <Bloco key={ano} className="p-3">
            <button type="button" onClick={() => alternarAno(ano)}
                    className="text-left" aria-expanded={!fechado}>
              <BlocoHead
                icon={fechado ? ChevronRight : ChevronDown}
                titulo={ano}
                sub={`${doAno.length} proposta(s)`}
                right={<span className="bi-num text-[13px]">{formatCurrency(totalAno)}</span>}
                className={fechado ? "mb-0" : undefined}
              />
            </button>
            {!fechado && (
            <Lista>
          {doAno.map((i) => (
            <ItemLinha
              key={i.numero_proposta}
              titulo={i.programa || i.objeto || `Proposta ${i.numero_proposta}`}
              valor={i.valor_total != null ? formatCurrency(i.valor_total) : "—"}
              meta={
                <>
                  {i.situacao && (
                    <Selo tom={situacaoTom(i.situacao)} title={i.situacao}>{i.situacao}</Selo>
                  )}
                  {i.qualificacao && <Selo title={i.qualificacao}>{i.qualificacao}</Selo>}
                  {i.proponente && <span>{i.proponente}</span>}
                  {i.emenda_parlamentar && (
                    <span style={{ color: "var(--bi-muted)" }}>
                      Emenda: {i.emenda_parlamentar}
                    </span>
                  )}
                  {/* Identificadores juntos e em mono: servem para ACHAR a
                      proposta no portal, nao para comparar entre linhas. */}
                  {/* Sem "·" na frente: o numero da proposta e o unico campo
                      SEMPRE presente, entao pode abrir a linha sozinho. */}
                  <span className="font-mono">
                    proposta {i.numero_proposta}
                    {i.programa_codigo ? ` · programa ${i.programa_codigo}` : ""}
                    {i.cnpj ? ` · CNPJ ${i.cnpj}` : ""}
                  </span>
                </>
              }
            >
              <Campos
                campos={[
                  {
                    rotulo: "Valor de repasse",
                    valor: i.valor_repasse != null ? formatCurrency(i.valor_repasse) : "—",
                  },
                  {
                    rotulo: "Contrapartida",
                    valor: i.valor_contrapartida != null ? formatCurrency(i.valor_contrapartida) : "—",
                  },
                  { rotulo: "Ano da proposta", valor: anoDaProposta(i.numero_proposta) || "—" },
                ]}
              />
            </ItemLinha>
          ))}
            </Lista>
            )}
          </Bloco>
          );
        })}
        </div>
      )}
    </div>
  );
}
