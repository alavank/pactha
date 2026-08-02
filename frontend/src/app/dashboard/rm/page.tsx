"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Trash2, Eye, Download, Loader2, ChevronDown, FileText } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos } from "@/lib/periodo";
import { Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio } from "@/components/ui/superficies";
import { useMunicipio } from "@/contexts/MunicipioContext";

interface RmListItem {
  id: number;
  municipio_id: number;
  municipio_nome?: string;
  data_referencia: string;
  cidade_emissao: string;
  titulo?: string;
  status: string;
  updated_at?: string;
}

/** Cor no selo de status SO quando ela e um alerta. Mesma regra de Convenios e
 *  Emendas.
 *
 *  O que havia aqui era o inverso: "finalizado" saia verde e TODO o resto saia
 *  amarelo — ou seja, um RM em rascunho (o estado normal de trabalho, a maioria
 *  da lista) aparecia pintado de aviso o tempo todo. Rascunho nao exige acao
 *  nenhuma, entao e cinza. */
function rmTom(s?: string | null): "neutro" | "ok" | "atencao" | "critico" {
  const t = (s || "").toLowerCase();
  if (/(cancelad|rejeitad)/.test(t)) return "critico";
  if (/(pendente|an[áa]lise|revis|aguardando)/.test(t)) return "atencao";
  if (/(finalizad|conclu[íi]d|aprovad)/.test(t)) return "ok";
  return "neutro";
}

/** O ANO do RM — o EXERCÍCIO.
 *
 *  Sai de `data_referencia` e de mais nada: a listagem não devolve campo
 *  `exercicio`, o que o cartão sempre mostrou nesse rótulo já era esta data
 *  recortada, e a criação grava `01/01` do ano escolhido no formulário acima.
 *  Um campo só é o que garante que o filtro e o rótulo nunca discordem.
 *
 *  Casa 4 dígitos seguidos em vez de cortar os 4 primeiros caracteres: a data
 *  chega ISO da API, mas se um dia vier "01/01/2025" o corte devolveria "01/0"
 *  e o RM viraria um exercício que não existe. */
function anoDo(rm: RmListItem): string {
  const m = /(\d{4})/.exec(rm.data_referencia || "");
  return m ? m[1] : "";
}

/* As pecas da identidade nao trazem botao — entao o botao de acao e montado
   aqui com os tokens, cinza no repouso. Antes eram tres cores de enfeite numa
   linha so (violeta em "Abrir", verde em "Relatorio", vermelho em remover), e
   com tudo pintado nada mais chamava atencao. */
const CLS_ACAO =
  "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors bi-hover";
const ESTILO_ACAO: React.CSSProperties = {
  background: "var(--bi-surface)",
  border: "1px solid var(--bi-line)",
  color: "var(--bi-muted)",
};

export default function RmListPage() {
  const router = useRouter();
  const { municipioId } = useMunicipio();

  const [items, setItems] = useState<RmListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [criando, setCriando] = useState(false);
  const anoAtual = new Date().getFullYear();
  const [novoAno, setNovoAno] = useState<number>(anoAtual);
  const [menuId, setMenuId] = useState<number | null>(null);
  const anosOpcoes = [anoAtual + 1, anoAtual, anoAtual - 1, anoAtual - 2];
  const [anosSel, setAnosSel] = useState<string[]>([]);

  /** Os anos que EXISTEM na lista, para o dropdown não oferecer ano vazio. */
  const anosDisponiveis = useMemo(
    () => Array.from(new Set(items.map(anoDo).filter(Boolean))).sort((a, b) => b.localeCompare(a)),
    [items],
  );

  /* Filtro client-side: a listagem do RM vem inteira (é um punhado de
     registros por município), então não há o que pedir de novo ao servidor. */
  const visiveis = useMemo(
    () => (anosSel.length ? items.filter((r) => anosSel.includes(anoDo(r))) : items),
    [items, anosSel],
  );

  const buscar = useCallback(async () => {
    if (!municipioId) return;
    setLoading(true);
    try {
      const r = await api.get<{ items: RmListItem[] }>("/rm", {
        params: { municipio_id: municipioId },
      });
      setItems(r.data.items);
    } catch (e) { console.error(e); } finally { setLoading(false); }
  }, [municipioId]);

  useEffect(() => { if (municipioId) buscar(); }, [municipioId, buscar]);

  const criar = async () => {
    if (!municipioId) return;
    setCriando(true);
    try {
      const r = await api.post<{ id: number }>("/rm", {
        municipio_id: Number(municipioId),
        // RM é ANUAL: a janela usa o ANO. Guardamos 01/01 do ano como referência.
        data_referencia: `${novoAno}-01-01`,
        cidade_emissao: "Brasília/DF",
        auto_popular: true,
      });
      router.push(`/dashboard/rm/${r.data.id}?municipio_id=${municipioId}`);
    } catch (e) {
      console.error(e); alert("Erro ao criar RM.");
    } finally { setCriando(false); }
  };

  const remover = async (id: number) => {
    if (!confirm("Remover este RM?")) return;
    try {
      await api.delete(`/rm/${id}`);
      buscar();
    } catch (e) { console.error(e); }
  };

  const exportar = (id: number, tipo: "completo" | "resumido" | "totalizado", formato: "pdf" | "xlsx" = "pdf") => {
    setMenuId(null);
    const url = `${api.defaults.baseURL}/rm/${id}/pdf?tipo=${tipo}&formato=${formato}`;
    const token = localStorage.getItem("pactha_token");
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        const href = URL.createObjectURL(blob);
        if (formato === "xlsx") {
          const a = document.createElement("a");
          a.href = href; a.download = "RM-Totalizado.xlsx"; a.click();
        } else {
          window.open(href, "_blank");
        }
      });
  };

  if (!municipioId) {
    return <div className="flex h-64 items-center justify-center text-muted-foreground">Selecione um município.</div>;
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-base-content">Relatório de Monitoramento (RM)</h1>
        <p className="mt-0.5 text-sm" style={{ color: "var(--bi-muted)" }}>
          Gestão dos RMs do município — padrão Freitas (criar, editar, exportar PDF).
        </p>
      </div>

      {/* Novo RM: bloco-envelope na gramatica do Painel — cabecalho com icone e
          subtitulo cinza, e o formulario dentro. */}
      <Bloco className="p-3">
        <BlocoHead
          icon={Plus}
          titulo="Novo RM"
          sub={
            <>
              O RM é <strong>anual</strong> (por ano de emissão). O conteúdo é preenchido automaticamente com os
              dados atuais do banco: propostas do ano em análise/aprovação + todas as empenhadas. Você edita
              livremente depois.
            </>
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <div>
            {/* 11px em --bi-muted, como o rotulo de controle das demais telas.
                Estava em 9px MAIUSCULO, que e o desenho exclusivo do rotulo de
                <Campos> — um controle vestido de celula de dado. */}
            <label
              htmlFor="rm-novo-ano"
              className="mb-1 block text-[11px]"
              style={{ color: "var(--bi-muted)" }}
            >
              Ano de referência
            </label>
            <select
              id="rm-novo-ano"
              className="bi-num h-9 rounded-md border px-2 text-[13px]"
              style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface)", color: "var(--bi-text)" }}
              value={novoAno}
              onChange={(e) => setNovoAno(Number(e.target.value))}
            >
              {anosOpcoes.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
          <Button onClick={criar} disabled={criando}>
            {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <Plus className="size-4 mr-1" />}
            Criar RM {novoAno}
          </Button>
        </div>
      </Bloco>

      {/* Filtro de EXERCÍCIO. Mesmo dropdown de anos das demais telas (com os
          atalhos de mandato), e olhando o MESMO campo que rotula o cartão.

          NÃO há agrupamento por ano aqui, e é decisão e não esquecimento: o
          banco tem UNIQUE (municipio_id, data_referencia) e a criação sempre
          grava 01/01 do ano, então existe NO MÁXIMO UM RM por exercício neste
          município. Um cartão por ano seria um cartão por item — moldura sem
          agrupar nada. */}
      <div className="flex flex-wrap items-center gap-3">
        <MultiSelect
          opcoes={anosDisponiveis}
          valor={anosSel}
          onChange={setAnosSel}
          atalhos={atalhosAnos()}
          formatarResumo={resumoAnos}
          placeholder="Todos os anos"
          rotuloTodos="Todos os anos"
          ariaLabel="Anos"
          className="w-44"
        />
      </div>

      {/* A LISTA DEIXOU DE SER TABELA-EM-CAIXA.
          Era um <ul divide-y> dentro de uma moldura com cabecalho cinza; agora
          e a pilha de cartoes macios da identidade, sem borda entre itens. Toda
          coluna que existia continua na tela: titulo e titulo, status virou
          selo, exercicio/cidade/atualizacao foram para <Campos> (posicoes
          fixas, para o olho descer a coluna como descia na tabela). */}
      {loading ? (
        /* Mesmo esqueleto da tela de Plano de Ação, a outra do lote que tem um.
           Estava em `bg-base-200`, que aponta para --bi-bg — a cor do FUNDO da
           pagina: o bloco de carregamento ficava invisivel. --bi-surface-2 e o
           cinza que existe justamente para aparecer sobre o fundo. */
        <div className="space-y-1.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg" style={{ background: "var(--bi-surface-2)" }} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Vazio>Nenhum RM ainda. Crie o primeiro acima.</Vazio>
      ) : (
        /* AS TRÊS CAMADAS: fundo cinza da página -> cartão BRANCO -> itens
           cinza dentro. A lista estava solta sobre o fundo, sem a camada do
           meio, e a contagem era um parágrafo perdido acima dela — agora é o
           subtítulo do próprio cartão. */
        <Bloco className="p-3">
          <BlocoHead
            icon={FileText}
            titulo="RMs cadastrados"
            sub={
              anosSel.length
                ? `${visiveis.length} de ${items.length} RM(s) — filtrado por exercício`
                : `${items.length} RM(s)`
            }
          />
          {visiveis.length === 0 ? (
            <Vazio>Nenhum RM no(s) exercício(s) selecionado(s).</Vazio>
          ) : (
          <Lista>
          {visiveis.map((rm) => {
            const exercicio = anoDo(rm);
            const href = `/dashboard/rm/${rm.id}?municipio_id=${municipioId}`;
            return (
              <ItemLinha
                key={rm.id}
                /* O corpo abre o RM, como nos cartoes do Painel. O botao "Abrir"
                   continua ali de proposito: e o unico affordance visivel. */
                onClick={() => router.push(href)}
                titulo={rm.titulo || (exercicio ? `RM ${exercicio}` : "RM sem exercício informado")}
                meta={
                  <>
                    <Selo tom={rmTom(rm.status)} title={`Status: ${rm.status}`}>{rm.status}</Selo>
                    {rm.municipio_nome && <span>{rm.municipio_nome}</span>}
                    <span className="font-mono">· #{rm.id}</span>
                  </>
                }
                acao={
                  <>
                    <Link href={href} className={CLS_ACAO} style={ESTILO_ACAO} title="Abrir o RM para edição">
                      <Eye className="size-3.5" /> Abrir
                    </Link>
                    <div className="relative">
                      <button
                        onClick={() => setMenuId(menuId === rm.id ? null : rm.id)}
                        className={CLS_ACAO}
                        style={ESTILO_ACAO}
                      >
                        <Download className="size-3.5" /> Relatório <ChevronDown className="size-3" />
                      </button>
                      {menuId === rm.id && (
                        <>
                          <div className="fixed inset-0 z-10" onClick={() => setMenuId(null)} />
                          <div className="bi-card absolute right-0 z-20 mt-1 w-56 py-1 text-left text-xs">
                            <button className="w-full px-3 py-1.5 text-left hover:bg-base-200" onClick={() => exportar(rm.id, "completo")}>
                              <span className="font-medium" style={{ color: "var(--bi-text)" }}>Completo</span>
                              <span className="block text-[10px]" style={{ color: "var(--bi-faint)" }}>Detalhado (PDF)</span>
                            </button>
                            <button className="w-full px-3 py-1.5 text-left hover:bg-base-200" onClick={() => exportar(rm.id, "resumido")}>
                              <span className="font-medium" style={{ color: "var(--bi-text)" }}>Resumido</span>
                              <span className="block text-[10px]" style={{ color: "var(--bi-faint)" }}>Só pendências (PDF)</span>
                            </button>
                            <div className="my-1 border-t" style={{ borderColor: "var(--bi-line)" }} />
                            <button className="w-full px-3 py-1.5 text-left hover:bg-base-200" onClick={() => exportar(rm.id, "totalizado", "xlsx")}>
                              <span className="font-medium" style={{ color: "var(--bi-text)" }}>Totalizado — Excel</span>
                              <span className="block text-[10px]" style={{ color: "var(--bi-faint)" }}>Planilha .xlsx</span>
                            </button>
                            <button className="w-full px-3 py-1.5 text-left hover:bg-base-200" onClick={() => exportar(rm.id, "totalizado", "pdf")}>
                              <span className="font-medium" style={{ color: "var(--bi-text)" }}>Totalizado — PDF</span>
                              <span className="block text-[10px]" style={{ color: "var(--bi-faint)" }}>Grade em PDF</span>
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                    <button onClick={() => remover(rm.id)} className={CLS_ACAO} style={ESTILO_ACAO} title="Remover este RM">
                      <Trash2 className="size-3.5" />
                    </button>
                  </>
                }
              >
                <Campos
                  campos={[
                    { rotulo: "Exercício", valor: exercicio || "—" },
                    { rotulo: "Cidade de emissão", valor: rm.cidade_emissao || "—" },
                    {
                      rotulo: "Atualizado em",
                      valor: rm.updated_at ? new Date(rm.updated_at).toLocaleString("pt-BR") : "—",
                      title: rm.updated_at || undefined,
                    },
                  ]}
                />
              </ItemLinha>
            );
          })}
          </Lista>
          )}
        </Bloco>
      )}
    </div>
  );
}
