"use client";

import React, { useEffect, useMemo, useState, useCallback } from "react";
import { Plus, Trash2, Download, Loader2, ChevronDown, FileText, Save } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/multi-select";
import { atalhosAnos, resumoAnos, anosOpcoes as anosOpcoesPeriodo } from "@/lib/periodo";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Modal, ModalCorpo, ModalHead,
  Selo, Vazio,
} from "@/components/ui/superficies";
import AvisoEscopo from "@/components/AvisoEscopo";
import { contarSemEscrita, podeExcluirLinha } from "@/lib/escopo";
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
  /** 'completo' (todos os anos) | 'parcial' (recorte de anos) | 'anual' (legado). */
  escopo?: string;
  /** SELEÇÃO de anos do relatório. `[]`/ausente = TODOS (o completo). */
  anos?: number[];
  /** O veredito do servidor sobre ESTE RM — ver `lib/escopo.ts`. Ausente
   *  significa "a API nao respondeu isso", e ai a tela fica como era. */
  pode_editar?: boolean | null;
  pode_excluir?: boolean | null;
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

/** O ESCOPO do RM sai de `rm.anos` (a seleção de anos), não mais da data.
 *  `[]`/ausente = TODOS os anos (o completo). */
function ehCompleto(rm: RmListItem): boolean {
  return !rm.anos || rm.anos.length === 0;
}

/** Rótulo do escopo para a lista: "Todos os anos" | "2026" | "2024, 2025, 2026". */
function escopoLabel(rm: RmListItem): string {
  if (ehCompleto(rm)) return "Todos os anos";
  return [...(rm.anos || [])].sort((a, b) => a - b).join(", ");
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
  const { municipioId } = useMunicipio();

  const [items, setItems] = useState<RmListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [criando, setCriando] = useState(false);
  const [menuId, setMenuId] = useState<number | null>(null);
  // SELEÇÃO de anos para GERAR. VAZIO = Todos os anos (o completo). Seleção de
  // anos específicos = um único relatório com esses anos juntos. Começa vazio:
  // a ação primária é gerar o completo.
  const opcoesGerar = anosOpcoesPeriodo();     // 2016..ano atual (string[])
  const [anosGerar, setAnosGerar] = useState<string[]>([]);
  const [anosSel, setAnosSel] = useState<string[]>([]);

  // RODAPÉ PADRÃO do tenant. `origem` diz se o texto exibido veio do banco
  // ("salvo") ou ainda da variável de ambiente ("env") — sem isso a pessoa
  // apaga o campo, salva, e não entende por que o rodapé antigo "voltou".
  //
  // Mora num MODAL e não num bloco da página: é configuração que se mexe uma
  // vez por ano, e como bloco fixo ocupava mais altura que o próprio "Novo RM",
  // empurrando a lista de relatórios — que é o conteúdo — para baixo da dobra.
  const [rodape, setRodape] = useState("");
  /** O último valor PERSISTIDO. É contra ele que se mede "há edição não salva?"
   *  e é para ele que o campo volta quando o modal fecha sem salvar. */
  const [rodapeOriginal, setRodapeOriginal] = useState("");
  const [rodapeAberto, setRodapeAberto] = useState(false);
  const [rodapeOrigem, setRodapeOrigem] = useState<"salvo" | "env">("env");
  const [rodapePodeEditar, setRodapePodeEditar] = useState(false);
  const [rodapeSalvando, setRodapeSalvando] = useState(false);
  const [rodapeOk, setRodapeOk] = useState(false);
  const rodapeSujo = rodape !== rodapeOriginal;

  /** Os anos que aparecem no ESCOPO de algum RM da lista (para o filtro). */
  const anosDisponiveis = useMemo(
    () => Array.from(new Set(items.flatMap((r) => (r.anos || []).map(String))))
      .sort((a, b) => b.localeCompare(a)),
    [items],
  );

  /* Filtro client-side por ano do ESCOPO: mostra o RM cujo escopo inclui algum
     ano selecionado; o COMPLETO (todos os anos) aparece sempre (cobre qualquer
     ano). A listagem vem inteira (poucos registros por município). */
  const visiveis = useMemo(
    () => (anosSel.length
      ? items.filter((r) => ehCompleto(r) || (r.anos || []).some((a) => anosSel.includes(String(a))))
      : items),
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

  // O rodapé é do TENANT, não do município: carrega uma vez, e não a cada troca
  // de município no seletor — pendurá-lo ali sugeriria que ele muda por
  // prefeitura, o que não é verdade.
  useEffect(() => {
    api.get<{ rodape: string; origem: "salvo" | "env"; pode_editar: boolean }>("/rm/config")
      .then((r) => {
        setRodape(r.data.rodape || "");
        setRodapeOriginal(r.data.rodape || "");
        setRodapeOrigem(r.data.origem);
        setRodapePodeEditar(!!r.data.pode_editar);
      })
      .catch((e) => console.error(e));
  }, []);

  /** Fecha o modal DESCARTANDO a edição — o campo volta ao último valor salvo.
   *
   *  Sem o retorno, reabrir o modal mostraria o texto abandonado como se fosse
   *  o rodapé em vigor, e a pessoa acreditaria ter salvo o que não salvou. */
  const fecharRodape = useCallback(() => {
    setRodape(rodapeOriginal);
    setRodapeOk(false);
    setRodapeAberto(false);
  }, [rodapeOriginal]);

  const salvarRodape = async () => {
    setRodapeSalvando(true);
    setRodapeOk(false);
    try {
      const r = await api.put<{ rodape: string; origem: "salvo" | "env" }>(
        "/rm/config", { rodape });
      setRodape(r.data.rodape);
      setRodapeOriginal(r.data.rodape);
      setRodapeOrigem(r.data.origem);
      setRodapeOk(true);
    } catch (e) {
      console.error(e);
      alert("Não foi possível salvar o rodapé padrão.");
    } finally { setRodapeSalvando(false); }
  };

  // GERAR: UM único relatório com o escopo escolhido (upsert por município+anos).
  //   nenhum ano marcado -> TODOS (o completo);
  //   um ano            -> só ele;
  //   vários anos       -> esses anos JUNTOS, num só relatório.
  // É sempre o padrão Freitas (4 partes por estágio), recortado pelos anos. Fica
  // na tela, só recarrega a lista — o RM é gerado, não editado à mão.
  const gerar = async () => {
    if (!municipioId) return;
    setCriando(true);
    try {
      const anos = [...anosGerar].map(Number).filter(Boolean).sort((a, b) => a - b);
      await api.post<{ id: number }>("/rm", {
        municipio_id: Number(municipioId),
        data_referencia: new Date().toISOString().slice(0, 10),  // data de emissão
        anos,                                                    // [] = todos = completo
        // Nao manda cidade: o servidor usa a do proprio municipio do RM.
        auto_popular: true,
      });
      await buscar();
    } catch (e) {
      console.error(e); alert("Erro ao gerar RM.");
    } finally { setCriando(false); }
  };

  // Rótulo do botão conforme a seleção (nenhum = completo; 1 = ano; vários = junto).
  const rotuloGerar = criando
    ? "Gerando…"
    : anosGerar.length === 0
      ? "Gerar RM Completo (todos os anos)"
      : anosGerar.length === 1
        ? `Gerar RM ${anosGerar[0]}`
        : `Gerar RM (${anosGerar.length} anos juntos)`;

  const remover = async (id: number) => {
    if (!confirm("Remover este RM?")) return;
    try {
      await api.delete(`/rm/${id}`);
      buscar();
    } catch (e) { console.error(e); }
  };

  const exportar = (id: number, tipo: "completo" | "resumido", formato: "pdf" = "pdf") => {
    setMenuId(null);
    const url = `${api.defaults.baseURL}/rm/${id}/pdf?tipo=${tipo}&formato=${formato}`;
    const token = localStorage.getItem("pactha_token");
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.blob())
      .then((blob) => {
        // Só PDF: o totalizado (o único que saía em .xlsx) foi descontinuado.
        window.open(URL.createObjectURL(blob), "_blank");
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
          Gestão dos RMs do município — padrão Freitas (gerar e exportar PDF).
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
              É <strong>por seleção de anos</strong>: escolha os anos e clique em Gerar. <strong>Nenhum ano</strong> marcado
              gera o <strong>completo</strong> (todos os anos); <strong>um ano</strong> gera só ele; <strong>vários anos</strong> geram
              um único relatório com eles juntos. O conteúdo é gerado automaticamente com os dados atuais do banco
              (padrão Freitas). Gerar de novo <strong>atualiza</strong> o relatório daquele escopo.
            </>
          }
          right={
            /* O rodapé vive AQUI, no cabeçalho de "Novo RM", porque é o Gerar
               que o carimba — e como botão, não como bloco: é ajuste raro, e
               ocupando altura fixa ele empurrava a lista de relatórios (o
               conteúdo da tela) para baixo da dobra. */
            <Button
              variant="outline"
              size="sm"
              onClick={() => { setRodapeOk(false); setRodapeAberto(true); }}
              title={rodape
                ? `Rodapé em vigor: ${rodape}`
                : "Nenhum rodapé definido — as páginas do RM saem sem o endereço de quem assina"}
            >
              <FileText className="size-4 mr-1" /> Rodapé padrão
              {!rodape && (
                <span className="ml-1.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  não definido
                </span>
              )}
            </Button>
          }
        />
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label
              className="mb-1 block text-[11px]"
              style={{ color: "var(--bi-muted)" }}
            >
              Anos do relatório
            </label>
            {/* VAZIO = Todos os anos (o completo). Selecionar anos recorta o escopo
                de UM único relatório — não gera um por ano. */}
            <MultiSelect
              opcoes={opcoesGerar}
              valor={anosGerar}
              onChange={setAnosGerar}
              atalhos={atalhosAnos()}
              formatarResumo={resumoAnos}
              placeholder="Todos os anos (completo)"
              rotuloTodos="Todos os anos (completo)"
              ariaLabel="Anos do relatório"
              className="w-60"
            />
          </div>
          <Button onClick={gerar} disabled={criando}>
            {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <Plus className="size-4 mr-1" />}
            {rotuloGerar}
          </Button>
        </div>
      </Bloco>

      {/* RODAPÉ PADRÃO — abre pelo botão do cabeçalho de "Novo RM".
          `superficie` porque é FORMULÁRIO (caixa branca), e `max-w-lg` é a
          escada que a primitiva reserva para formulário. */}
      <Modal
        aberto={rodapeAberto}
        onFechar={fecharRodape}
        maxW="max-w-lg"
        superficie
        rotulo="Rodapé padrão dos relatórios"
        /* ⚠️ As TRÊS saídas (Esc, clique no véu e o X) passam por aqui. Sem esta
           guarda, o endereço que a pessoa acabou de digitar sumia sem aviso — é
           exatamente para isso que a primitiva expõe `podeFechar`. */
        podeFechar={() => !rodapeSujo
          || confirm("Há alteração não salva no rodapé. Descartar?")}
      >
        <ModalHead
          titulo="Rodapé padrão dos relatórios"
          sub={
            <>
              Sai impresso no <strong>pé de toda página</strong> do RM — é o endereço de quem
              assina. O que você salvar aqui vira o <strong>padrão</strong> e entra nos relatórios{" "}
              <strong>gerados a partir de agora</strong>; os já emitidos continuam com o rodapé
              que receberam.{" "}
              {rodapeOrigem === "env"
                ? "Hoje o texto abaixo ainda vem da configuração do servidor — salvando, ele passa a vir daqui."
                : "Este texto está salvo no sistema."}
            </>
          }
          onFechar={fecharRodape}
        />
        <ModalCorpo>
          <textarea
            className="bi-field min-h-[96px] w-full px-2 py-1 text-[12px]"
            value={rodape}
            disabled={!rodapePodeEditar}
            onChange={(e) => { setRodape(e.target.value); setRodapeOk(false); }}
            placeholder="Ex.: SHS Quadra 6, Bloco A, Sala 000 — Brasília/DF — (61) 0000-0000"
            aria-label="Rodapé padrão dos relatórios"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <Button onClick={salvarRodape} disabled={!rodapePodeEditar || rodapeSalvando}>
              {rodapeSalvando ? <Loader2 className="size-4 animate-spin mr-1" /> : <Save className="size-4 mr-1" />}
              Salvar como padrão
            </Button>
            <Button variant="outline" onClick={fecharRodape}>Fechar</Button>
            {rodapeOk && (
              <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Salvo. Vale para os próximos RMs gerados.
              </span>
            )}
            {!rodapePodeEditar && (
              /* Campo desligado NÃO é permissão — quem barra é o servidor. Isto só
                 evita oferecer um botão que devolveria 403. */
              <span className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Somente administradores alteram o rodapé padrão.
              </span>
            )}
          </div>
        </ModalCorpo>
      </Modal>

      {/* Filtro por ano do ESCOPO: mostra os RMs cujo escopo inclui o ano
          escolhido; o COMPLETO aparece sempre (cobre qualquer ano). */}
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
                ? `${visiveis.length} de ${items.length} RM(s) — filtrado por ano`
                : `${items.length} RM(s)`
            }
          />
          {visiveis.length === 0 ? (
            <Vazio>Nenhum RM no(s) ano(s) selecionado(s).</Vazio>
          ) : (
          <>
          {/* Conta o que está NA TELA (`visiveis`) e não a lista inteira: com o
              filtro de exercício ligado, "em 4 de 9" apontaria para itens que a
              pessoa não está vendo. */}
          <AvisoEscopo
            bloqueadas={contarSemEscrita(visiveis)}
            total={visiveis.length}
            plural="os RMs"
          />
          <Lista>
          {visiveis.map((rm) => {
            const completo = ehCompleto(rm);
            const escopoTxt = escopoLabel(rm);
            return (
              <ItemLinha
                key={rm.id}
                /* Sem edicao: o RM e gerado e EMITIDO direto pelo dropdown
                   "Relatório" (Completo/Resumido/Totalizado). Nao ha mais "Abrir"
                   nem clique no corpo — nao existe tela de edicao a abrir. */
                titulo={
                  rm.titulo ||
                  (completo
                    ? "RM Completo — todos os anos"
                    : (rm.anos && rm.anos.length === 1)
                      ? `RM ${escopoTxt}`
                      : `RM — ${escopoTxt}`)
                }
                meta={
                  <>
                    <Selo tom={rmTom(rm.status)} title={`Status: ${rm.status}`}>{rm.status}</Selo>
                    {/* Escopo do RM: "Completo" (todos os anos) ou os anos escolhidos. */}
                    {completo ? (
                      <Selo tom="ok" title="RM de todos os anos (padrão Freitas)">Completo</Selo>
                    ) : (
                      <Selo tom="neutro" title={`Anos do relatório: ${escopoTxt}`}>{escopoTxt}</Selo>
                    )}
                    {rm.municipio_nome && <span>{rm.municipio_nome}</span>}
                    <span className="font-mono">· #{rm.id}</span>
                  </>
                }
                acao={
                  <>
                    {/* Emissão direta pelo dropdown — sem "Abrir"/edição. */}
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
                          </div>
                        </>
                      )}
                    </div>
                    {podeExcluirLinha(rm) && (
                      <button onClick={() => remover(rm.id)} className={CLS_ACAO} style={ESTILO_ACAO} title="Remover este RM">
                        <Trash2 className="size-3.5" />
                      </button>
                    )}
                  </>
                }
              >
                <Campos
                  campos={[
                    { rotulo: "Abrangência", valor: completo ? "Todos os anos" : escopoTxt },
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
          </>
          )}
        </Bloco>
      )}
    </div>
  );
}
