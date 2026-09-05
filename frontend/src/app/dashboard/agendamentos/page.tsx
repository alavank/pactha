"use client";

/* AGENDAMENTOS — a agenda de compromissos da equipe, em três abas.
 *
 * ⭐ FONTE ÚNICA DE DADOS. Calendário, kanban, lista e o card lateral leem o
 * MESMO `itens` deste componente, vindo de UM `GET /api/agendamentos`. Trocar de
 * aba não busca nada e não pode divergir: qualquer alteração — salvar, arrastar
 * no quadro, anotar — chama `recarregar()`, e as quatro superfícies acompanham
 * sem F5. Três consultas separadas divergiriam, e a primeira a divergir
 * mostraria um compromisso que as outras escondem.
 *
 * ⚠️ A CONSULTA NÃO TEM RECORTE DE DATA, e é essa a razão. Cada aba precisa de
 * uma janela diferente (o mês navegado, o quadro inteiro, «Este mês») e o card
 * lateral precisa de hoje; recortar no servidor obrigaria a uma busca por aba, e
 * aí acabou a fonte única. O que a API recorta é o que TODAS respeitam: a
 * carteira, o filtro de município e a busca. É uma agenda de equipe — algumas
 * centenas de linhas por ano —, não um extrato de convênios.
 *
 * ⚠️ ESTE MÓDULO IGNORA O MUNICÍPIO DO MENU LATERAL (decisão do dono). Numa
 * assessoria a agenda é da casa, não da cidade em acesso; numa prefeitura não há
 * escolha nenhuma a fazer. Quem decide qual dos dois casos é este é o BACKEND
 * (`GET /agendamentos/contexto`), pela contagem de municípios ativos do tenant —
 * e não pelo tamanho da carteira de quem está logado, que é diferente.
 *
 * ⚠️ E VAI PELO `api`, NUNCA POR `fetch` COM `pactha_token`. O token é apagado
 * do localStorage no primeiro refresh (`lib/api.ts`, auto-cura) e `Bearer null`
 * ATROPELA o cookie bom no backend, que lê o Bearer antes. Já mordeu três telas
 * — convênios, DOU e emendas — e cada uma tem o comentário do conserto.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CalendarDays, Columns3, FileDown, LayoutList, Search, X,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { BOTAO_SEC, ESTILO_SEC } from "@/components/ui/superficies";
import type { User } from "@/types";

import Calendario from "./Calendario";
import CardDia from "./CardDia";
import CompromissoModal, { type ModoModal } from "./CompromissoModal";
import FiltroMunicipios from "./FiltroMunicipios";
import Kanban, { BotaoNovaColuna } from "./Kanban";
import ListaCompromissos from "./ListaCompromissos";
import RelatorioModal from "./RelatorioModal";
import {
  Coluna, Compromisso, CorPaleta, ModoCalendario, Vista, hojeISO,
} from "./tipos";

/** A busca só vai ao servidor depois que a pessoa para de digitar. 350ms é o
 *  intervalo em que uma palavra inteira cabe entre duas teclas. */
const DEBOUNCE_MS = 350;

const ABAS: [Vista, string, typeof CalendarDays][] = [
  ["calendario", "Calendário", CalendarDays],
  ["kanban", "Kanban", Columns3],
  ["lista", "Lista", LayoutList],
];

export default function AgendamentosPage() {
  const { municipios } = useMunicipio();

  /* ⚠️ ABRE SEMPRE NO CALENDÁRIO, MODO MENSAL (documento). É a visão que
     responde a pergunta que traz a pessoa aqui — "o que tem esta semana" —, e a
     única em que a AUSÊNCIA de compromisso num dia também é informação. */
  const [vista, setVista] = useState<Vista>("calendario");
  const [modoCal, setModoCal] = useState<ModoCalendario>("mensal");
  const [foco, setFoco] = useState(hojeISO());

  const [itens, setItens] = useState<Compromisso[]>([]);
  const [colunas, setColunas] = useState<Coluna[]>([]);
  const [maxColunas, setMaxColunas] = useState(5);
  const [maxCustomizadas, setMaxCustomizadas] = useState(2);
  const [paleta, setPaleta] = useState<CorPaleta[]>([]);
  const [multiMunicipio, setMultiMunicipio] = useState<boolean | null>(null);
  const [usuario, setUsuario] = useState<User | null>(null);

  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [busca, setBusca] = useState("");
  const [buscaAtiva, setBuscaAtiva] = useState("");
  const [munSel, setMunSel] = useState<number[]>([]);

  /* ⚠️ O CARD SEMPRE ABRE VISÍVEL e o ocultar dura só a sessão (documento):
     estado de componente, nunca `localStorage`. Guardado, alguém que o fechou
     em agosto abriria a agenda sem ele em setembro sem lembrar por quê. */
  const [cardVisivel, setCardVisivel] = useState(true);

  const [modal, setModal] = useState<
    { modo: ModoModal; item: Compromisso | null; inicial?: { data?: string; hora?: string } } | null
  >(null);
  const [relatorio, setRelatorio] = useState(false);

  /* ------------------------------------------------------------- carga --- */

  useEffect(() => {
    const t = setTimeout(() => setBuscaAtiva(busca.trim()), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [busca]);

  const filtros = useMemo(() => ({
    ...(munSel.length ? { municipio_ids: munSel } : {}),
    ...(buscaAtiva ? { q: buscaAtiva } : {}),
  }), [munSel, buscaAtiva]);

  /* ⚠️ CONTADOR DE PEDIDO. Sem ele, uma busca lenta que volta DEPOIS de uma
     rápida repinta a tela com o resultado antigo — e a lista passa a não
     corresponder ao que está escrito no campo. */
  const pedido = useRef(0);
  const recarregar = useCallback(() => {
    const meu = ++pedido.current;
    setCarregando(true); setErro(null);
    api.get("/agendamentos", { params: filtros })
      .then((r) => { if (meu === pedido.current) setItens(r.data?.items || []); })
      .catch((e) => {
        if (meu !== pedido.current) return;
        setItens([]);
        setErro(e?.response?.data?.detail || "Não foi possível carregar a agenda.");
      })
      .finally(() => { if (meu === pedido.current) setCarregando(false); });
  }, [filtros]);
  useEffect(recarregar, [recarregar]);

  const recarregarColunas = useCallback(() => {
    api.get("/agendamentos/colunas").then((r) => {
      setColunas(r.data?.colunas || []);
      if (r.data?.max) setMaxColunas(r.data.max);
      if (r.data?.max_customizadas) setMaxCustomizadas(r.data.max_customizadas);
    }).catch(() => { /* sem colunas o kanban se explica sozinho */ });
  }, []);

  useEffect(() => {
    recarregarColunas();
    /* A paleta e o contexto do tenant vêm do backend pela mesma razão: duas
       listas divergem, e a divergência aparece como um compromisso salvo numa
       cor que os swatches não marcam. */
    api.get("/agendamentos/paleta")
      .then((r) => setPaleta(r.data?.cores || []))
      .catch(() => setPaleta([]));
    api.get("/agendamentos/contexto")
      .then((r) => setMultiMunicipio(!!r.data?.multi_municipio))
      /* Sem resposta, assume PREFEITURA (município implícito): é o caso em que
         esconder o campo não perde nada — o backend preenche sozinho. Assumir
         assessoria mostraria um seletor obrigatório num tenant que tem uma
         cidade só, e o formulário ficaria impossível de enviar. */
      .catch(() => setMultiMunicipio(false));
    api.get<User>("/auth/me")
      .then((r) => setUsuario(r.data))
      .catch(() => { /* sem nome a saudação sai sem ele */ });
  }, [recarregarColunas]);

  /* ------------------------------------------------------------- ações --- */

  const mover = async (c: Compromisso, colunaId: number) => {
    const antes = itens;
    const destino = colunas.find((k) => k.id === colunaId);
    // Otimista: o cartão anda na hora. Recusado, volta e explica.
    setItens((l) => l.map((x) => x.id === c.id
      ? { ...x, coluna_id: colunaId, coluna: destino?.nome || x.coluna } : x));
    try {
      await api.patch(`/agendamentos/${c.id}/coluna`, { coluna_id: colunaId });
    } catch (e: unknown) {
      setItens(antes);
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail
        || "Não foi possível mudar este compromisso de coluna.");
    }
  };

  const criarColuna = async (nome: string) => {
    setErro(null);
    try {
      await api.post("/agendamentos/colunas", { nome });
      recarregarColunas();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail || "Não foi possível criar a coluna.");
    }
  };

  const renomearColuna = async (id: number, nome: string, cor: string) => {
    setErro(null);
    try {
      await api.put(`/agendamentos/colunas/${id}`, { nome, cor });
      recarregarColunas();
      recarregar();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail || "Não foi possível renomear a coluna.");
    }
  };

  const removerColuna = async (id: number, quantos: number) => {
    const col = colunas.find((k) => k.id === id);
    /* ⚠️ A CONFIRMAÇÃO DIZ QUANTOS CARTÕES VOLTAM. "Remover esta coluna?" não
       deixa a pessoa medir o estrago; com o número, a decisão é informada. */
    const aviso = quantos > 0
      ? `Remover «${col?.nome}»? Os ${quantos} compromisso(s) desta coluna voltam para «Solicitada».`
      : `Remover a coluna «${col?.nome}»?`;
    if (!window.confirm(aviso)) return;
    setErro(null);
    try {
      await api.delete(`/agendamentos/colunas/${id}`);
      recarregarColunas();
      recarregar();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail || "Não foi possível remover a coluna.");
    }
  };

  /* ⚠️ SÓ EXISTE `abrir`. O duplo clique que abria a edição direto saiu em
     05/09/2026 (decisão do dono): um clique abre o detalhe, e o botão «Editar»
     de dentro dele é o único caminho para o modo de edição. O gesto duplo
     sobreviveu num lugar só — a célula VAZIA, para criar. */
  const abrir = (c: Compromisso) => setModal({ modo: "detalhe", item: c });
  const criar = (data: string, hora?: string) =>
    setModal({ modo: "criar", item: null, inicial: { data, hora } });

  /* ------------------------------------------------------------- tela ---- */

  const comMunicipio = multiMunicipio === true;

  return (
    /* ⭐ `ag-modulo` É A PELE DO MÓDULO, e ela é a razão de existir um contêiner
       nomeado: os tokens `--bi-bg`/`--bi-surface` são redeclarados ali (ver
       globals.css) e valem da borda dele para dentro. O fundo palha não vaza
       para o resto do sistema, e o acento/CTA/foco continuam sendo os do PACTHA.

       ⭐ E A ALTURA É A DA VIEWPORT MENOS O PADDING DO LAYOUT (`py-6` = 3rem),
       agora em TODO tamanho de tela e não só em `lg`. É o que faz o calendário
       chegar até o pé da página mesmo vazio. O `min-h` embaixo é a válvula: numa
       janela baixa ele vence o `h`, o módulo para de encolher e quem rola é o
       `<main>` — sem ele, com 500px de altura sobrariam ~180px para a grade de
       24 horas.

       ⚠️ O `-mx-4 px-4 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8` desfaz e refaz o
       padding do contêiner da página: é o que faz o fundo palha sangrar até a
       borda da área útil em vez de deixar duas faixas cinza nas laterais. */
    <div className="ag-modulo -mx-4 flex h-[calc(100vh-3rem)] min-h-[34rem] flex-col gap-3 px-4 py-3 sm:-mx-6 sm:px-6 lg:-mx-8 lg:px-8">
      {/* ------------------------------------------------------ cabeçalho */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-base-content">Agendamentos</h1>
          <p className="text-sm text-muted-foreground">
            A agenda de compromissos da equipe
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Abas do módulo"
               className="flex overflow-hidden rounded-xl"
               style={{ border: "1px solid var(--bi-line)" }}>
            {ABAS.map(([v, rotulo, Icone]) => (
              <button key={v} type="button" onClick={() => setVista(v)}
                      aria-pressed={vista === v} title={rotulo}
                      className="flex h-9 items-center gap-1.5 px-3 text-[12px] transition-colors"
                      style={vista === v
                        ? { background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)", fontWeight: 600 }
                        : { color: "var(--bi-muted)" }}>
                <Icone className="size-3.5" />
                <span className="hidden sm:inline">{rotulo}</span>
              </button>
            ))}
          </div>
          <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                  onClick={() => setRelatorio(true)}>
            <FileDown className="size-3.5" /> Relatório PDF
          </button>
        </div>
      </div>

      {/* -------------------------------------------------------- toolbar */}
      {/* ⚠️ A TOOLBAR É COMPARTILHADA PELAS TRÊS ABAS, e por isso fica ACIMA
          delas: trocar de desenho não pode zerar o recorte que a pessoa acabou
          de montar. */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2"
                  style={{ color: "var(--bi-faint)" }} />
          <input value={busca} onChange={(e) => setBusca(e.target.value)}
                 placeholder="Buscar demanda, solicitante ou município"
                 aria-label="Buscar compromissos"
                 className="bi-field h-8 w-64 max-w-full pl-8 pr-7 text-[12px]" />
          {busca && (
            <button type="button" onClick={() => setBusca("")}
                    aria-label="Limpar busca"
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-0.5"
                    style={{ color: "var(--bi-faint)" }}>
              <X className="size-3.5" />
            </button>
          )}
        </div>

        {comMunicipio && (
          <FiltroMunicipios municipios={municipios} selecionados={munSel}
                            onMudar={setMunSel} />
        )}

        {/* ⚠️ CRIAR COLUNA É AÇÃO DA ABA, não uma coluna do quadro. Era um
            retângulo tracejado ao lado das três — e com ele o kanban nunca
            dividia a largura por igual, porque havia sempre um bloco a mais
            disputando espaço. Some sozinho no teto de cinco. */}
        {vista === "kanban" && (
          <BotaoNovaColuna colunas={colunas} max={maxColunas}
                           maxCustomizadas={maxCustomizadas} onCriar={criarColuna} />
        )}

        {/* ⚠️ O CONTADOR NÃO APARECE NA LISTA, e é o conserto de um número
            duplicado: a aba Lista tem o seu, logo abaixo do filtro de período, e
            ele conta o PERÍODO FILTRADO — enquanto este conta o recorte inteiro.
            Dois números com o mesmo rótulo na mesma tela é pior que nenhum. */}
        {vista !== "lista" && (
          <span className="ml-auto text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {carregando ? "carregando…" : `${itens.length} compromisso(s)`}
          </span>
        )}
      </div>

      {erro && (
        <div role="alert" className="rounded-xl px-3 py-2 text-[12px]"
             style={{ background: "color-mix(in oklab, var(--bi-crit) 14%, transparent)",
                      color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {/* -------------------------------------------------------- conteúdo */}
      <div className="min-h-0 flex-1">
        {carregando && itens.length === 0 ? (
          <Esqueleto vista={vista} />
        ) : vista === "calendario" ? (
          <div className="flex h-full min-h-0 flex-col gap-3 lg:flex-row">
            <div className="flex min-h-0 flex-1 flex-col lg:order-1">
              <Calendario
                itens={itens} modo={modoCal} onModo={setModoCal}
                foco={foco} onFoco={setFoco} comMunicipio={comMunicipio}
                onCriar={criar} onAbrir={abrir}
                onMostrarCard={cardVisivel ? undefined : () => setCardVisivel(true)}
              />
            </div>
            {/* ⚠️ Abaixo de `lg` o card DEIXA de ser lateral e vira bloco ACIMA
                do calendário (`order`), com altura própria — é o que impede a
                grade de 24 horas e o cartão de disputarem a mesma tela num
                celular. */}
            {cardVisivel && (
              <div className="min-h-0 shrink-0 lg:order-2 lg:w-[320px]">
                <div className="h-56 lg:h-full">
                  <CardDia itens={itens} nome={usuario?.name}
                           comMunicipio={comMunicipio} onAbrir={abrir}
                           onOcultar={() => setCardVisivel(false)} />
                </div>
              </div>
            )}
          </div>
        ) : vista === "kanban" ? (
          /* ⚠️ O QUADRO VAZIO CONTINUA SENDO DESENHADO. A primeira versão trocava
             o kanban por um "nenhum compromisso ainda" quando a lista vinha
             vazia — e com isso escondia as colunas E o botão «+ Coluna»
             justamente no tenant recém-criado, que é o único que precisa
             configurá-las antes de ter qualquer compromisso. Cada coluna já diz
             sozinha que está vazia. */
          <Kanban
            itens={itens} colunas={colunas} comMunicipio={comMunicipio}
            paleta={paleta} onAbrir={abrir} onMover={mover}
            onRenomearColuna={renomearColuna} onRemoverColuna={removerColuna}
          />
        ) : (
          <ListaCompromissos itens={itens} comMunicipio={comMunicipio}
                             onAbrir={abrir} />
        )}
      </div>

      {/* ---------------------------------------------------------- modais */}
      {modal && (
        <CompromissoModal
          modo={modal.modo} item={modal.item} inicial={modal.inicial}
          comMunicipio={comMunicipio} municipios={municipios}
          paleta={paleta} colunas={colunas}
          onModo={(m) => setModal((x) => (x ? { ...x, modo: m } : x))}
          onFechar={() => setModal(null)}
          onMudou={recarregar}
        />
      )}
      {relatorio && (
        <RelatorioModal filtros={filtros} onFechar={() => setRelatorio(false)} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------ esqueleto --- */

/** O estado de carregando com a FORMA da aba que vem — não um spinner no meio
 *  da tela. O calendário ocupa a viewport inteira: um spinner centralizado faria
 *  a página saltar de vazia para cheia a cada busca. */
function Esqueleto({ vista }: { vista: Vista }) {
  if (vista === "kanban") {
    /* Três colunas dividindo a largura, como o quadro de verdade — um esqueleto
       com outra geometria faz a tela "pular" quando o dado chega. */
    return (
      <div className="grid h-full grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-full animate-pulse rounded-2xl"
               style={{ background: "var(--bi-surface-2)" }} />
        ))}
      </div>
    );
  }
  if (vista === "lista") {
    return (
      <div className="space-y-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-14 animate-pulse rounded-xl"
               style={{ background: "var(--bi-surface-2)" }} />
        ))}
      </div>
    );
  }
  return (
    <div className="flex h-full gap-3">
      <div className="flex-1 animate-pulse rounded-2xl"
           style={{ background: "var(--bi-surface-2)" }} />
      <div className="hidden w-[320px] animate-pulse rounded-2xl lg:block"
           style={{ background: "var(--bi-surface-2)" }} />
    </div>
  );
}
