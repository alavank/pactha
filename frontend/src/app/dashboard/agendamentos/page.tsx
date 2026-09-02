"use client";

/* AGENDAMENTOS — a agenda de trabalho da equipe, em três desenhos.
 *
 * ⭐ TRÊS VISUALIZAÇÕES, UMA CONSULTA. Lista, calendário e kanban leem o MESMO
 * `GET /api/agendamentos` com os MESMOS filtros; o que muda é o desenho. Por
 * isso o filtro fica ACIMA das abas e não dentro de cada uma: trocar de desenho
 * não pode zerar o recorte que a pessoa acabou de montar, e três consultas
 * separadas divergiriam — a primeira a divergir mostraria um agendamento que as
 * outras duas escondem.
 *
 * ⚠️ O EXPORTAR MANDA OS MESMOS PARÂMETROS DA LISTA, do mesmo estado. É o que
 * garante que o arquivo tenha exatamente as linhas da tela. Montar o filtro do
 * export à parte é como as duas cópias de `exportar` do RM divergiram.
 *
 * ⚠️ E VAI PELO `api`, NUNCA POR `fetch` COM `pactha_token`. O token é apagado
 * do localStorage no primeiro refresh (`lib/api.ts`, auto-cura) e `Bearer null`
 * ATROPELA o cookie bom no backend, que lê o Bearer antes. Já mordeu três telas
 * — convênios, DOU e emendas — e cada uma tem o comentário do conserto.
 *
 * ⚠️ DATA PURA NÃO É INSTANTE. `new Date("2026-09-15")` é meia-noite UTC e, no
 * Brasil, volta dia 14. Toda data aqui passa por `diaBR`/`isoDoDia`, que
 * trabalham com os componentes Y-M-D e nunca com fuso.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarDays, Download, FileSpreadsheet, LayoutList, Loader2, Paperclip,
  Plus, User as UserIcon, Columns3,
} from "lucide-react";

import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import {
  BOTAO_CTA, BOTAO_SEC, Bloco, BlocoHead, ESTILO_CTA, ESTILO_SEC, ItemLinha,
  Lista, Selo, Vazio,
} from "@/components/ui/superficies";
import AgendamentoModal from "@/components/AgendamentoModal";

export interface Agendamento {
  id: number;
  municipio_id: number;
  municipio: string;
  responsavel_id: number | null;
  responsavel: string | null;
  titulo: string;
  relato: string | null;
  data: string | null;
  status: string;
  status_rotulo: string;
  anexos: { nome: string; mime: string; tamanho?: number }[];
  criado_por: number | null;
  criado_por_nome: string | null;
}

/* As três colunas do quadro. A ORDEM é a do kanban, da esquerda para a direita.
 * ⚠️ O backend também tem esta lista (`routers/agendamentos.STATUS`) e manda o
 * rótulo em `status_rotulo`. Aqui ficam só a ordem e a COR — duas listas de
 * rótulo divergiriam, e a divergência esconde cartão. */
const COLUNAS = [
  { valor: "a_fazer", rotulo: "A fazer", cor: "var(--bi-accent)", tom: undefined },
  { valor: "em_andamento", rotulo: "Em andamento", cor: "var(--bi-warn)", tom: "atencao" as const },
  { valor: "realizado", rotulo: "Realizado", cor: "var(--bi-ok)", tom: "ok" as const },
];
const TOM: Record<string, "ok" | "atencao" | undefined> = {
  realizado: "ok", em_andamento: "atencao", a_fazer: undefined,
};

/* `YYYY-MM-DD` -> dd/mm. Sem `Date`, para não haver fuso no caminho. */
function diaBR(iso: string | null, comAno = false): string {
  if (!iso) return "—";
  const [a, m, d] = String(iso).slice(0, 10).split("-");
  if (!a || !m || !d) return "—";
  return comAno ? `${d}/${m}/${a}` : `${d}/${m}`;
}

/* Componentes Y-M-D -> `YYYY-MM-DD`, sem passar por instante. */
function isoDoDia(ano: number, mes0: number, dia: number): string {
  return `${ano}-${String(mes0 + 1).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
}

const MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
  "agosto", "setembro", "outubro", "novembro", "dezembro"];
const SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"];

export default function AgendamentosPage() {
  const { municipioId } = useMunicipio();
  /* ⚠️ O CALENDÁRIO ABRE A TELA (decisão do dono). É a visão que responde a
     pergunta que traz a pessoa aqui — "o que tem esta semana" —, e é a única
     das três em que a AUSÊNCIA de compromisso num dia também é informação. A
     lista responde "o que existe" e o kanban "em que pé está"; as duas fazem
     sentido depois, não antes. */
  const [vista, setVista] = useState<"calendario" | "lista" | "kanban">("calendario");
  const [itens, setItens] = useState<Agendamento[]>([]);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [de, setDe] = useState("");
  const [ate, setAte] = useState("");
  const [status, setStatus] = useState("");
  const [editando, setEditando] = useState<Agendamento | null>(null);
  const [novo, setNovo] = useState(false);
  const [baixando, setBaixando] = useState("");
  /* O mês que o calendário mostra. Guardado como [ano, mês0] e nunca como
     `Date`, pelo mesmo motivo das datas: `new Date()` no dia 1º às 22h de
     Brasília já é o dia 2 em UTC. */
  const hoje = new Date();
  const [mes, setMes] = useState<[number, number]>([hoje.getFullYear(), hoje.getMonth()]);

  const filtros = useMemo(() => ({
    ...(municipioId ? { municipio_id: municipioId } : {}),
    ...(de ? { de } : {}), ...(ate ? { ate } : {}),
    ...(status ? { status } : {}),
  }), [municipioId, de, ate, status]);

  const pedido = React.useRef(0);
  const carregar = useCallback(() => {
    const meu = ++pedido.current;
    setCarregando(true); setErro(null);
    api.get("/agendamentos", { params: filtros })
      .then((r) => { if (meu === pedido.current) setItens(r.data.items || []); })
      .catch((e) => {
        if (meu !== pedido.current) return;
        setItens([]);
        setErro(e?.response?.data?.detail || "Não foi possível carregar a agenda.");
      })
      .finally(() => { if (meu === pedido.current) setCarregando(false); });
  }, [filtros]);
  useEffect(carregar, [carregar]);

  /* ⚠️ `responseType: "blob"` PELO `api`, e o nome do arquivo sai do
     Content-Disposition que o backend manda — assim o nome no disco é o mesmo
     que a trilha de auditoria registrou. */
  const exportar = async (formato: "xlsx" | "pdf") => {
    setBaixando(formato); setErro(null);
    try {
      const r = await api.get("/agendamentos/exportar/relacao", {
        params: { ...filtros, formato }, responseType: "blob",
      });
      const cd = String(r.headers["content-disposition"] || "");
      const nome = /filename=([^;]+)/.exec(cd)?.[1]?.trim()
        || `agendamentos.${formato}`;
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url; a.download = nome; a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      // ⚠️ O CORPO DE ERRO CHEGA COMO BLOB porque pedimos blob — ler
      // `data.detail` direto devolve `undefined` e a mensagem do backend (o
      // 413 do teto de linhas, com a instrução de estreitar o filtro) some.
      const err = e as { response?: { data?: Blob } };
      let msg = "Não foi possível gerar o arquivo.";
      try {
        const txt = await err.response?.data?.text();
        msg = JSON.parse(txt || "{}").detail || msg;
      } catch { /* corpo não era JSON; fica a mensagem genérica */ }
      setErro(msg);
    } finally { setBaixando(""); }
  };

  const mover = async (item: Agendamento, novoStatus: string) => {
    if (item.status === novoStatus) return;
    const antes = itens;
    // Otimista: o cartão anda na hora. Se o servidor recusar, volta e explica.
    setItens((l) => l.map((x) => x.id === item.id
      ? { ...x, status: novoStatus,
          status_rotulo: COLUNAS.find((c) => c.valor === novoStatus)?.rotulo || novoStatus }
      : x));
    try {
      await api.patch(`/agendamentos/${item.id}/status`, { status: novoStatus });
    } catch (e: unknown) {
      setItens(antes);
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail
        || "Não foi possível mudar a situação deste agendamento.");
    }
  };

  const porDia = useMemo(() => {
    const m: Record<string, Agendamento[]> = {};
    itens.forEach((i) => {
      const k = String(i.data || "").slice(0, 10);
      if (k) (m[k] ||= []).push(i);
    });
    return m;
  }, [itens]);

  /* ⚠️ A CARTEIRA INTEIRA É UM CASO VÁLIDO, e não um estado a bloquear. Com
     «Consolidado» o seletor devolve `municipioId = ""`, e a versão anterior
     desta tela mostrava "selecione um município" — negando justamente ao
     cliente de 42 municípios a visão que ele mais precisa: a agenda da semana
     de todo mundo. Sem filtro de município a consulta traz o que a pessoa
     alcança, e cada cartão passa a dizer de qual cidade é.
     CRIAR continua exigindo um município escolhido: agendamento sem cidade não
     existe, e adivinhar qual seria pior que pedir. */
  const consolidado = !municipioId;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-base-content">Agendamentos</h1>
          <p className="text-sm text-muted-foreground">
            A agenda de trabalho da equipe
          </p>
        </div>
        {/* ⚠️ TRÊS BOTÕES, e não abas (decisão do dono). São três DESENHOS do
            mesmo recorte, e aba sugere três conteúdos diferentes — o filtro
            acima continua valendo nos três, o que a aba faria parecer que não.
            Ficam no alto à direita, onde a pessoa já olha para exportar.
            `role="group"` + `aria-pressed`: para o leitor de tela isto é um
            seletor de modo, não navegação. */}
        <div className="flex flex-wrap items-center gap-2">
          <div role="group" aria-label="Modo de visualização"
               className="flex overflow-hidden rounded-xl"
               style={{ border: "1px solid var(--bi-line)" }}>
            {([
              ["calendario", "Calendário", CalendarDays],
              ["lista", "Lista", LayoutList],
              ["kanban", "Kanban", Columns3],
            ] as const).map(([v, rotulo, Icone]) => (
              <button key={v} type="button" onClick={() => setVista(v)}
                      aria-pressed={vista === v} title={rotulo}
                      className="flex h-9 items-center gap-1.5 px-3 text-[12px] transition-colors"
                      style={vista === v
                        ? { background: "var(--bi-accent-bg)", color: "var(--bi-accent-ink)", fontWeight: 600 }
                        : { color: "var(--bi-muted)" }}>
                <Icone className="size-3.5" />
                {/* O rótulo some no celular; o ícone e o `title` seguram. */}
                <span className="hidden sm:inline">{rotulo}</span>
              </button>
            ))}
          </div>
          <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                  disabled={!!baixando} onClick={() => exportar("xlsx")}>
            {baixando === "xlsx"
              ? <Loader2 className="size-3.5 animate-spin" />
              : <FileSpreadsheet className="size-3.5" />} Excel
          </button>
          <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                  disabled={!!baixando} onClick={() => exportar("pdf")}>
            {baixando === "pdf"
              ? <Loader2 className="size-3.5 animate-spin" />
              : <Download className="size-3.5" />} PDF
          </button>
          <button type="button" className={BOTAO_CTA} style={ESTILO_CTA}
                  onClick={() => setNovo(true)} disabled={consolidado}
                  title={consolidado
                    ? "Escolha um município para criar um agendamento"
                    : undefined}>
            <Plus className="size-3.5" /> Novo agendamento
          </button>
        </div>
      </div>

      {/* ⚠️ O FILTRO FICA FORA DAS ABAS. Ver o cabeçalho do arquivo. */}
      <Bloco className="p-3">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>De</span>
            <input type="date" value={de} onChange={(e) => setDe(e.target.value)}
                   className="bi-input h-8 rounded-lg px-2 text-[12px]" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>Até</span>
            <input type="date" value={ate} onChange={(e) => setAte(e.target.value)}
                   className="bi-input h-8 rounded-lg px-2 text-[12px]" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>Situação</span>
            <select value={status} onChange={(e) => setStatus(e.target.value)}
                    className="bi-input h-8 rounded-lg px-2 text-[12px]">
              <option value="">Todas</option>
              {COLUNAS.map((c) => (
                <option key={c.valor} value={c.valor}>{c.rotulo}</option>
              ))}
            </select>
          </label>
          {(de || ate || status) && (
            <button type="button" className="text-[11px] underline"
                    style={{ color: "var(--bi-accent-ink)" }}
                    onClick={() => { setDe(""); setAte(""); setStatus(""); }}>
              limpar filtros
            </button>
          )}
          <span className="ml-auto text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {carregando ? "carregando…" : `${itens.length} agendamento(s)`}
          </span>
        </div>
      </Bloco>

      {erro && (
        <div className="rounded-xl px-3 py-2 text-[12px]"
             style={{ background: "var(--bi-crit-bg)", color: "var(--bi-crit-ink)" }}>
          {erro}
        </div>
      )}

      {carregando && !itens.length ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> carregando…
        </div>
      ) : vista === "lista" ? (
        <VistaLista itens={itens} onAbrir={setEditando} comMunicipio={consolidado} />
      ) : vista === "calendario" ? (
        <VistaCalendario porDia={porDia} mes={mes} setMes={setMes}
                         onAbrir={setEditando} />
      ) : (
        <VistaKanban itens={itens} onAbrir={setEditando} onMover={mover} />
      )}

      {(novo || editando) && (
        <AgendamentoModal
          aberto
          municipioId={Number(editando?.municipio_id ?? municipioId)}
          item={editando}
          colunas={COLUNAS.map((c) => ({ valor: c.valor, rotulo: c.rotulo }))}
          onFechar={() => { setNovo(false); setEditando(null); }}
          onSalvo={() => { setNovo(false); setEditando(null); carregar(); }}
        />
      )}
    </div>
  );
}

/* --------------------------------------------------------------- LISTA --- */

function VistaLista({ itens, onAbrir, comMunicipio }: {
  itens: Agendamento[];
  onAbrir: (a: Agendamento) => void;
  /* Só na carteira inteira: com um município escolhido o nome se repetiria em
     toda linha sem distinguir nada. */
  comMunicipio: boolean;
}) {
  if (!itens.length) {
    return <Vazio>Nenhum agendamento no recorte selecionado.</Vazio>;
  }
  return (
    <Bloco className="p-3">
      <BlocoHead icon={LayoutList} titulo="Agendamentos"
                 sub="do mais próximo para o mais distante" />
      <Lista>
        {itens.map((a) => (
          <ItemLinha
            key={a.id}
            onClick={() => onAbrir(a)}
            titulo={
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span>{a.titulo}</span>
                <Selo tom={TOM[a.status]}>{a.status_rotulo}</Selo>
              </span>
            }
            valor={diaBR(a.data, true)}
            meta={
              <>
                {comMunicipio && <span>{a.municipio}</span>}
                {a.responsavel && (
                  <span className="inline-flex items-center gap-1">
                    <UserIcon className="size-3" /> {a.responsavel}
                  </span>
                )}
                {a.anexos?.length > 0 && (
                  <span className="inline-flex items-center gap-1">
                    <Paperclip className="size-3" /> {a.anexos.length} anexo(s)
                  </span>
                )}
                {a.relato && <span>· {a.relato.slice(0, 120)}
                  {a.relato.length > 120 ? "…" : ""}</span>}
              </>
            }
          />
        ))}
      </Lista>
    </Bloco>
  );
}

/* ---------------------------------------------------------- CALENDÁRIO --- */

/* ⚠️ TETO DE TRÊS POR DIA, com "+N mais". A carteira do freitas tem 42
   municípios ativos: sem município escolhido, um mês pode ter duzentos
   compromissos e a grade vira sopa — o calendário deixaria de ser legível
   justamente no cliente que mais precisa dele. O "+N" abre o dia na lista. */
const TETO_DIA = 3;

function VistaCalendario({ porDia, mes, setMes, onAbrir }: {
  porDia: Record<string, Agendamento[]>;
  mes: [number, number];
  setMes: (m: [number, number]) => void;
  onAbrir: (a: Agendamento) => void;
}) {
  const [ano, m0] = mes;
  const [expandido, setExpandido] = useState<string | null>(null);
  /* Dia 0 do mês seguinte = último dia deste. E `getDay()` domingo=0, mas a
     semana da grade começa na segunda — daí o `(d + 6) % 7`. */
  const dias = new Date(ano, m0 + 1, 0).getDate();
  const vazioAntes = (new Date(ano, m0, 1).getDay() + 6) % 7;
  const anda = (n: number) => {
    const d = new Date(ano, m0 + n, 1);
    setMes([d.getFullYear(), d.getMonth()]);
  };

  return (
    <Bloco className="p-3">
      <div className="mb-2 flex items-center justify-between">
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                onClick={() => anda(-1)} aria-label="Mês anterior">←</button>
        <span className="text-[13px] font-semibold">
          {MESES[m0]} de {ano}
        </span>
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                onClick={() => anda(1)} aria-label="Próximo mês">→</button>
      </div>
      <div className="grid grid-cols-7 gap-1">
        {SEMANA.map((s) => (
          <div key={s} className="py-1 text-center text-[10px]"
               style={{ color: "var(--bi-faint)" }}>{s}</div>
        ))}
        {Array.from({ length: vazioAntes }).map((_, i) => (
          <div key={`v${i}`} />
        ))}
        {Array.from({ length: dias }, (_, i) => i + 1).map((d) => {
          const iso = isoDoDia(ano, m0, d);
          const doDia = porDia[iso] || [];
          const aberto = expandido === iso;
          const visiveis = aberto ? doDia : doDia.slice(0, TETO_DIA);
          return (
            <div key={iso} className="min-h-[68px] rounded-lg p-1"
                 style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}>
              <div className="mb-0.5 text-[10px]" style={{ color: "var(--bi-faint)" }}>{d}</div>
              {visiveis.map((a) => (
                <button key={a.id} type="button" onClick={() => onAbrir(a)}
                        title={a.titulo}
                        className="mb-0.5 block w-full truncate rounded px-1 py-0.5 text-left text-[10px] leading-tight"
                        style={{
                          background: a.status === "realizado" ? "var(--bi-ok-bg)"
                            : a.status === "em_andamento" ? "var(--bi-warn-bg)"
                              : "var(--bi-accent-bg)",
                          color: a.status === "realizado" ? "var(--bi-ok-ink)"
                            : a.status === "em_andamento" ? "var(--bi-warn-ink)"
                              : "var(--bi-accent-ink)",
                        }}>
                  {a.titulo}
                </button>
              ))}
              {doDia.length > TETO_DIA && (
                <button type="button" className="text-[10px] underline"
                        style={{ color: "var(--bi-accent-ink)" }}
                        onClick={() => setExpandido(aberto ? null : iso)}>
                  {aberto ? "menos" : `+${doDia.length - TETO_DIA} mais`}
                </button>
              )}
            </div>
          );
        })}
      </div>
    </Bloco>
  );
}

/* -------------------------------------------------------------- KANBAN --- */

function VistaKanban({ itens, onAbrir, onMover }: {
  itens: Agendamento[];
  onAbrir: (a: Agendamento) => void;
  onMover: (a: Agendamento, s: string) => void;
}) {
  const [sobre, setSobre] = useState<string | null>(null);

  return (
    <div className="grid gap-3 md:grid-cols-3">
      {COLUNAS.map((col) => {
        const daColuna = itens.filter((i) => i.status === col.valor);
        return (
          <div key={col.valor}
               onDragOver={(e) => { e.preventDefault(); setSobre(col.valor); }}
               onDragLeave={() => setSobre((s) => (s === col.valor ? null : s))}
               onDrop={(e) => {
                 e.preventDefault(); setSobre(null);
                 const id = Number(e.dataTransfer.getData("text/plain"));
                 const item = itens.find((x) => x.id === id);
                 if (item) onMover(item, col.valor);
               }}
               className="rounded-xl p-2 transition-colors"
               style={{
                 background: sobre === col.valor ? "var(--bi-accent-bg)" : "var(--bi-surface)",
                 border: "1px solid var(--bi-line)",
               }}>
            <div className="mb-2 flex items-center justify-between px-1">
              <span className="text-[12px] font-semibold">{col.rotulo}</span>
              <span className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
                {daColuna.length}
              </span>
            </div>
            {daColuna.length === 0 && (
              <p className="px-1 py-3 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                nada aqui
              </p>
            )}
            {daColuna.map((a) => (
              <div key={a.id} draggable
                   onDragStart={(e) => e.dataTransfer.setData("text/plain", String(a.id))}
                   className="mb-1.5 cursor-grab rounded-lg p-2"
                   style={{ background: "var(--bi-card)", border: "1px solid var(--bi-line)",
                            borderLeft: `3px solid ${col.cor}` }}>
                <button type="button" onClick={() => onAbrir(a)}
                        className="block w-full text-left">
                  <p className="text-[12px] font-medium leading-snug">{a.titulo}</p>
                  <p className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                    {diaBR(a.data)}
                    {a.responsavel ? ` · ${a.responsavel}` : ""}
                    {a.anexos?.length ? ` · ${a.anexos.length} anexo(s)` : ""}
                  </p>
                </button>
                {/* ⚠️ O SELETOR EXISTE ALÉM DO ARRASTAR, e não em vez dele.
                    Arrastar não funciona com teclado nem com leitor de tela, e
                    é justamente a interação que um toque desastrado dispara sem
                    querer. Com o seletor, mover um cartão nunca depende do
                    mouse — e desfazer é escolher de volta. */}
                <select value={a.status} aria-label={`Situação de ${a.titulo}`}
                        onChange={(e) => onMover(a, e.target.value)}
                        className="bi-input mt-1.5 h-6 w-full rounded px-1 text-[10px]">
                  {COLUNAS.map((c) => (
                    <option key={c.valor} value={c.valor}>{c.rotulo}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}
