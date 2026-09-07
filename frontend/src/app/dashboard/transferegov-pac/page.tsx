"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { Loader2, Search, Eraser, ChevronDown, ChevronRight } from "lucide-react";
import api from "@/lib/api";
import { useAnoCorrentePadrao } from "@/lib/anoPadrao";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatCurrency } from "@/lib/utils";
import { MultiSelect } from "@/components/ui/multi-select";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio, situacaoTom } from "@/components/ui/superficies";
import { PainelFiltros, type FiltroAtivo } from "@/components/ui/filtros";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import Link from "next/link";
import { TituloTela } from "@/components/TituloTela";

/** O instrumento que NASCEU de uma seleção do PAC.
 *
 *  É o caminho inverso do elo que o RM já usa: lá, a voluntária declara de qual
 *  seleção veio (`_pac_da_voluntaria`, em services/rm_builder.py); aqui, a
 *  seleção mostra o que virou. Sem isto a tela do PAC responde "que propostas
 *  foram selecionadas" e não responde "quais viraram convênio", que é a pergunta
 *  operacional. */
interface VinculoConvenio {
  numero_proposta: string;
  codigo_instrumento: string | null;
  situacao: string | null;
  dt_inicio_vigencia: string | null;
  dt_fim_vigencia: string | null;
  valor_repasse: number | null;
  dias_restantes: number | null;
  /** Em qual das quatro telas de propostas ele está — vem calculado do backend
   *  com as MESMAS regras do /voluntarias, para o link não cair em tela vazia. */
  categoria: "geral" | "voluntarias" | "rejeitadas" | "encerradas";
}

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
  /** LISTA: nada impede duas propostas apontarem para a mesma seleção. Vazia =
   *  nenhum instrumento CONHECIDO (não é o mesmo que "não há instrumento"). */
  vinculos?: VinculoConvenio[];
}


/* Rotulo de controle (filtro/formulario). 11px em --bi-muted, com a dica em
   --bi-faint. Fica em 11px de proposito: 9px e 10px sao as escalas que <Campos>
   e a meta do <ItemLinha> usam para DADO, e emprestar essas escalas ao filtro
   faz o controle competir com o resultado. Mesmas constantes em `dou`. */
const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR = { color: "var(--bi-muted)" } as const;
const DICA_COR = { color: "var(--bi-faint)" } as const;

const VINCULO_LABEL: Record<string, string> = { com: "Com convênio", sem: "Sem convênio" };

const semAcento = (s?: string | null) =>
  (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Casa `termo` contra `texto` tolerando o acento PERDIDO na coleta.
 *
 *  ⚠️ O portal serve U+FFFD no lugar da letra acentuada e o coletor APAGA esse
 *  caractere — o banco guarda "MUNICPIO DE SO GONALO". Por isso cada caractere
 *  não-ASCII do termo vira coringa OPCIONAL, que casa a letra ("São"), a versão
 *  sem acento ("Sao") e a AUSÊNCIA dela ("So"). É a mesma doutrina do
 *  `_padrao_like` do backend (routers/transferegov.py). */
function casa(texto: string | null | undefined, termo: string): boolean {
  const t = (termo || "").trim();
  if (!t) return true;
  const padrao = Array.from(t)
    .map((ch) => (ch.charCodeAt(0) > 127 ? ".?" : ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))
    .join("");
  try { return new RegExp(padrao, "i").test(semAcento(texto)); }
  catch { return semAcento(texto).includes(semAcento(t)); }
}

/** CNPJ: só os dígitos dos dois lados — o portal grava com máscara e o gestor
 *  cola dos dois jeitos. Termo sem dígito nenhum não filtra. */
const casaCnpj = (cnpj: string | null | undefined, termo: string) => {
  const d = (termo || "").replace(/\D/g, "");
  return !d || (cnpj || "").replace(/\D/g, "").includes(d);
};

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
  /* CINCO CAMPOS no lugar da caixa única. A caixa era um OR de cinco colunas:
     digitar um número procurava o mesmo número em proposta, programa, situação,
     emenda e objeto ao mesmo tempo, e não havia como pedir "só o convênio". */
  const [fInstrumento, setFInstrumento] = useState("");
  const [fProposta, setFProposta] = useState("");
  const [fProponente, setFProponente] = useState("");
  const [fCnpj, setFCnpj] = useState("");
  const [fObjeto, setFObjeto] = useState("");
  /** "com" / "sem" convênio vinculado. */
  const [vinculoSel, setVinculoSel] = useState<string[]>([]);
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
  // Abre no ano corrente em vez de "todos" — ver `lib/anoPadrao.ts`.
  useAnoCorrentePadrao(anoOpcoes, setAnosSel);

  const filtrados = useMemo(() => items.filter((i) => {
    if (!casa(i.numero_proposta, fProposta)) return false;
    if (!casa(i.proponente, fProponente)) return false;
    if (!casaCnpj(i.cnpj, fCnpj)) return false;
    if (fObjeto.trim() && ![i.objeto, i.programa, i.emenda_parlamentar, i.qualificacao]
      .some((v) => casa(v, fObjeto))) return false;
    // Convênio vinculado: casa o nº do instrumento OU o nº da proposta que nasceu
    // desta seleção — o gestor procura pelos dois.
    if (fInstrumento.trim() && !(i.vinculos || []).some(
      (v) => casa(v.codigo_instrumento, fInstrumento) || casa(v.numero_proposta, fInstrumento))) return false;
    if (vinculoSel.length) {
      const tem = (i.vinculos || []).length > 0;
      if (!vinculoSel.includes(tem ? "com" : "sem")) return false;
    }
    if (situacoesSel.length && !situacoesSel.includes(i.situacao || "")) return false;
    if (programasSel.length && !programasSel.includes(i.programa || "")) return false;
    if (anosSel.length && !anosSel.includes(anoDaProposta(i.numero_proposta))) return false;
    return true;
  }), [items, fProposta, fProponente, fCnpj, fObjeto, fInstrumento, vinculoSel,
       situacoesSel, programasSel, anosSel]);

  /** Chips do painel recolhido — mesma regra da tela de propostas: recorte
   *  aplicado nunca fica invisível. */
  const filtrosAtivos = useMemo<FiltroAtivo[]>(() => {
    const a: FiltroAtivo[] = [];
    const t = (chave: string, rot: string, v: string, limparCampo: () => void) => {
      if (v.trim()) a.push({ chave, rotulo: `${rot}: ${v.trim()}`, remover: limparCampo });
    };
    t("instrumento", "Convênio", fInstrumento, () => setFInstrumento(""));
    t("proposta", "Proposta", fProposta, () => setFProposta(""));
    t("proponente", "Proponente", fProponente, () => setFProponente(""));
    t("cnpj", "CNPJ", fCnpj, () => setFCnpj(""));
    t("objeto", "Objeto/Programa", fObjeto, () => setFObjeto(""));
    vinculoSel.forEach((v) => a.push({
      chave: `vinc:${v}`, rotulo: VINCULO_LABEL[v] ?? v,
      remover: () => setVinculoSel((x) => x.filter((y) => y !== v)),
    }));
    situacoesSel.forEach((s) => a.push({
      chave: `sit:${s}`, rotulo: s,
      remover: () => setSituacoesSel((x) => x.filter((y) => y !== s)),
    }));
    programasSel.forEach((p) => a.push({
      chave: `prog:${p}`, rotulo: p,
      remover: () => setProgramasSel((x) => x.filter((y) => y !== p)),
    }));
    anosSel.forEach((y) => a.push({
      chave: `ano:${y}`, rotulo: y,
      remover: () => setAnosSel((x) => x.filter((z) => z !== y)),
    }));
    return a;
  }, [fInstrumento, fProposta, fProponente, fCnpj, fObjeto, vinculoSel,
      situacoesSel, programasSel, anosSel]);

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

  /* Uma fonte só para "há filtro aplicado?": a MESMA lista que vira chip. Antes
     eram duas contas paralelas, e a daqui esquecia campos. */
  const temFiltro = filtrosAtivos.length > 0;
  /* Limpa TODOS os campos, inclusive os cinco novos e o vínculo — um "limpar"
     que deixa filtro aplicado é exatamente o defeito que esta tela veio
     consertar. */
  const limpar = () => {
    setFInstrumento(""); setFProposta(""); setFProponente(""); setFCnpj(""); setFObjeto("");
    setVinculoSel([]); setSituacoesSel([]); setProgramasSel([]); setAnosSel([]);
  };

  return (
    /* Sem o `p-4` de antes: era a unica pagina do dashboard com padding proprio,
       entao o conteudo comecava 16px adentro em relacao a todas as vizinhas. */
    <div className="space-y-4">
      <div>
        {/* text-2xl como em Convenios, Emendas e as demais telas migradas — o
            titulo desta era o unico em text-xl. */}
        <TituloTela>Transfere Gov — Seleção PAC (Novo PAC)</TituloTela>
        <p className="text-sm text-base-content/60 mt-1">
          Propostas do Novo PAC do município (TransfereGov / Acesso Livre).
          {atualizado ? ` · Atualizado: ${new Date(atualizado).toLocaleDateString("pt-BR")}` : ""}
        </p>
      </div>

      {/* Filtros: a tela so tinha uma busca por texto, e achar "as nao
          habilitadas de 2025" exigia ler tudo. Multi-selecao nos tres eixos que
          o gestor usa (situacao, programa, ano) — no cliente, porque o endpoint
          devolve as propostas do municipio de uma vez. */}
      <PainelFiltros ativos={filtrosAtivos} aoLimparTudo={limpar}>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          <div>
            {/* CONVÊNIO VINCULADO — o campo que só existe porque a tela passou a
                saber o que cada seleção virou. Casa o nº do instrumento e o nº da
                proposta que nasceu daqui. */}
            <label className={ROTULO} style={ROTULO_COR}>Convênio vinculado (nº)</label>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2" style={{ color: "var(--bi-faint)" }} />
              <Input className="pl-8" placeholder="Ex: 981397"
                value={fInstrumento} onChange={(e) => setFInstrumento(e.target.value)} />
            </div>
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>Proposta (nº)</label>
            <Input placeholder="Ex: 56000004633/2025"
              value={fProposta} onChange={(e) => setFProposta(e.target.value)} />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>Proponente</label>
            <Input placeholder="Ex: Município de Araújos"
              value={fProponente} onChange={(e) => setFProponente(e.target.value)} />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>CNPJ</label>
            <Input placeholder="18.243.220/0001-01" inputMode="numeric"
              value={fCnpj} onChange={(e) => setFCnpj(e.target.value)} />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>Objeto / Programa / Emenda</label>
            <Input placeholder="Ex: Pavimentação"
              value={fObjeto} onChange={(e) => setFObjeto(e.target.value)} />
          </div>
          <div>
            <label className={ROTULO} style={ROTULO_COR}>
              Convênio <span style={DICA_COR}>(virou instrumento?)</span>
            </label>
            <MultiSelect
              opcoes={["com", "sem"]}
              valor={vinculoSel}
              onChange={setVinculoSel}
              rotulos={VINCULO_LABEL}
              placeholder="Tanto faz"
              rotuloTodos="Tanto faz"
              ariaLabel="Vínculo com convênio"
            />
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
      </PainelFiltros>

      {/* Resumo FORA do painel de propósito: "N proposta(s) · R$ X" e os selos
          por situação descrevem o RESULTADO, não o filtro — recolher o painel
          não pode apagar a contagem que o gestor está lendo. */}
      <Bloco className="p-3">
        <div className="flex flex-wrap items-center gap-2">
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
                  {/* CONVÊNIO VINCULADO — o que esta seleção virou.
                      Verde porque é o desfecho bom da seleção, e é o único selo
                      desta linha que o gestor procura ativamente. O link leva à
                      tela de propostas CERTA (o backend diz qual) já filtrada
                      pelo número da proposta — sem isso o gestor cairia numa
                      lista de 180 itens para achar um. */}
                  {(i.vinculos || []).map((v) => (
                    <Link
                      key={v.numero_proposta}
                      href={`/dashboard/transferegov-${v.categoria}?proposta=${encodeURIComponent(v.numero_proposta)}`}
                      onClick={(e) => e.stopPropagation()}
                      title={`Ver o instrumento ${v.codigo_instrumento || v.numero_proposta}${v.situacao ? ` — ${v.situacao}` : ""}`}
                    >
                      <Selo tom="ok">
                        Convênio {v.codigo_instrumento || v.numero_proposta}
                        {v.situacao ? ` · ${v.situacao}` : ""}
                      </Selo>
                    </Link>
                  ))}
                  {/* SEM vínculo NÃO vira selo de alerta: a maior parte das
                      seleções legitimamente ainda não virou instrumento, e
                      pintar todas de vermelho ensinaria a ignorar a cor. Quem
                      quer esse recorte usa o filtro "Sem convênio". */}
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
                  // A FONTE, no canto inferior direito (pedido do dono): o menu
                  // diz a esfera (FEDERAIS), o card diz o sistema de origem.
                  { rotulo: "Fonte", valor: "TransfereGov" },
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
