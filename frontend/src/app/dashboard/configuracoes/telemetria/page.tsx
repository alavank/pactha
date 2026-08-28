"use client";

// TELEMETRIA — como o sistema é usado.
//
// Aba IRMÃ da Auditoria, e de propósito separada dela: a trilha guarda ato
// consequente e serve de prova; esta guarda navegação e serve para entender o
// uso. Mesma seção de Configurações porque as duas são do AMBIENTE INTEIRO —
// diferente das telas de dado, que mudam com o município selecionado.
//
// O DESENHO (pedido do dono, 28/08/2026):
//   · "Online no Sistema" no topo — a única parte viva da tela.
//   · EVENTOS à esquerda: frases legíveis ("Maria filtrou Convênios: ano 2024",
//     "gerou um Relatório de Monitoramento"), agrupadas por dia; clique abre o
//     detalhe num modal.
//   · SESSÕES à direita: por dia e por pessoa — quando entrou, quanto ficou,
//     quanto foi ocioso e COMO terminou (clicou em Sair, fechou o navegador,
//     expirou). Clique abre o detalhe.
// A frase sai de lib/uso-rotulos.ts; o evento cru sai de lib/uso.ts.

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, Loader2, RefreshCw, MousePointerClick, Clock, LogOut, Monitor,
  User as UserIcon, ListFilter,
} from "lucide-react";
import api from "@/lib/api";
import {
  Abas, Bloco, BlocoHead, ItemLinha, Lista, Modal, ModalCorpo, ModalHead,
  Secao, Selo, Vazio, BOTAO_SEC, ESTILO_SEC,
} from "@/components/ui/superficies";
import { Button } from "@/components/ui/button";
import PresencaAgora from "@/components/PresencaAgora";
import {
  TIPO_EVENTO, chaveDoDia, descreverParams, dispositivo, dur, fimDaSessao, fraseDoEvento,
  horaCompleta, horaCurta, nomeDaTela, nomeDoDia, type EventoUsoLido,
} from "@/lib/uso-rotulos";

interface Sessao {
  sid: string; sessao_token: string | null; user_id: number;
  user_email: string; usuario_nome: string | null;
  inicio: string; ultimo_sinal: string; fim: string | null; motivo_fim: string | null;
  seg_ativos: number; seg_ociosos: number; seg_total: number;
  eventos: number; descartados: number;
  tela_atual: string | null; situacao: string; ip: string | null; user_agent: string | null;
}
interface Evento extends EventoUsoLido {
  id: number; municipio_id: number | null; ip: string | null; user_agent: string | null;
}

type Periodo = "7" | "30" | "90";

const nome = (s: { usuario_nome: string | null; user_email: string }) =>
  s.usuario_nome || s.user_email.split("@")[0];

/** O SELO do tipo de evento é cinza; só a ALTERAÇÃO ganha acento, porque é o
 *  que mudou algo no sistema — o resto é leitura. */
function tomDoTipo(acao: string): "neutro" | "acento" {
  return ["alterar", "gerar", "exportar", "perguntar"].includes(acao) ? "acento" : "neutro";
}

export default function TelemetriaPage() {
  const [periodo, setPeriodo] = useState<Periodo>("7");
  const [sessoes, setSessoes] = useState<Sessao[]>([]);
  const [eventos, setEventos] = useState<Evento[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  /** Filtros da coluna de eventos: uma sessão OU uma pessoa. */
  const [filtroSid, setFiltroSid] = useState<string | null>(null);
  const [filtroUser, setFiltroUser] = useState<number | null>(null);
  const [filtroTipo, setFiltroTipo] = useState<string>("");
  const [mostrar, setMostrar] = useState(150);
  const [eventoAberto, setEventoAberto] = useState<Evento | null>(null);
  const [sessaoAberta, setSessaoAberta] = useState<Sessao | null>(null);

  const carregar = useCallback(async (silencioso = false) => {
    if (!silencioso) setLoading(true);
    try {
      const dias = Number(periodo);
      const paramsEv: Record<string, string | number> = { dias, limite: 1000 };
      if (filtroSid) paramsEv.sid = filtroSid;
      else if (filtroUser) paramsEv.user_id = filtroUser;
      const [s, e] = await Promise.all([
        api.get<{ sessoes: Sessao[] }>("/uso/sessoes", { params: { dias, limite: 1000 } }),
        api.get<{ eventos: Evento[] }>("/uso/eventos", { params: paramsEv }),
      ]);
      setSessoes(s.data.sessoes || []);
      setEventos(e.data.eventos || []);
      setErro(null);
    } catch (x: unknown) {
      setErro((x as { response?: { status?: number } })?.response?.status === 403
        ? "Você não tem a permissão «Telemetria — Ver»."
        : "Não foi possível carregar a telemetria.");
    } finally { setLoading(false); }
  }, [periodo, filtroSid, filtroUser]);

  // Busca de dados ao montar e a cada troca de filtro/período. Adiada para
  // fora do corpo do efeito (o `setLoading` síncrono dentro dele dispara
  // render em cascata e o lint barra) — mesmo idioma das outras telas.
  useEffect(() => {
    const t = setTimeout(() => { void carregar(); }, 0);
    return () => clearTimeout(t);
  }, [carregar]);

  // ⚠️ A LISTA SE ATUALIZA SOZINHA. Sem isto era preciso apertar "Atualizar"
  // para ver o que estava acontecendo — numa tela cujo propósito é justamente
  // acompanhar. 20s casa com o envio de 45s do outro lado: um evento demora no
  // máximo ~1min para aparecer, e o gargalo é o envio, não esta consulta.
  // Pausa com a aba escondida e com um modal aberto: recarregar por baixo de
  // um detalhe que a pessoa está lendo é gastar servidor para nada.
  useEffect(() => {
    const t = setInterval(() => {
      if (document.visibilityState === "visible" && !eventoAberto && !sessaoAberta) carregar(true);
    }, 20_000);
    return () => clearInterval(t);
  }, [carregar, eventoAberto, sessaoAberta]);

  /* ---------------- Sessões por dia e por pessoa ---------------- */
  const sessoesPorDia = useMemo(() => {
    const dias = new Map<string, { chave: string; rotulo: string; pessoas: Map<number, { nome: string; itens: Sessao[] }> }>();
    for (const s of sessoes) {
      const k = chaveDoDia(s.inicio);
      if (!dias.has(k)) dias.set(k, { chave: k, rotulo: nomeDoDia(s.inicio), pessoas: new Map() });
      const dia = dias.get(k)!;
      if (!dia.pessoas.has(s.user_id)) dia.pessoas.set(s.user_id, { nome: nome(s), itens: [] });
      dia.pessoas.get(s.user_id)!.itens.push(s);
    }
    // Dia mais recente primeiro; dentro do dia, quem tem mais tempo primeiro.
    return [...dias.values()]
      .sort((a, b) => (a.chave < b.chave ? 1 : -1))
      .map((d) => ({
        ...d,
        pessoas: [...d.pessoas.entries()]
          .map(([id, p]) => ({
            id, nome: p.nome,
            itens: p.itens.sort((a, b) => (a.inicio < b.inicio ? 1 : -1)),
            total: p.itens.reduce((n, s) => n + (s.seg_total || 0), 0),
            ativo: p.itens.reduce((n, s) => n + (s.seg_ativos || 0), 0),
            ocioso: p.itens.reduce((n, s) => n + (s.seg_ociosos || 0), 0),
          }))
          .sort((a, b) => b.total - a.total),
      }));
  }, [sessoes]);

  /* ---------------- Eventos por dia ---------------- */
  const pessoas = useMemo(() => {
    const m = new Map<number, string>();
    for (const s of sessoes) if (!m.has(s.user_id)) m.set(s.user_id, nome(s));
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
  }, [sessoes]);

  const eventosFiltrados = useMemo(
    () => (filtroTipo ? eventos.filter((e) => e.acao === filtroTipo) : eventos),
    [eventos, filtroTipo],
  );

  const eventosPorDia = useMemo(() => {
    const dias: Array<{ chave: string; rotulo: string; itens: Evento[] }> = [];
    for (const e of eventosFiltrados.slice(0, mostrar)) {
      const k = chaveDoDia(e.ocorrido_em);
      const ultimo = dias[dias.length - 1];
      if (ultimo && ultimo.chave === k) ultimo.itens.push(e);
      else dias.push({ chave: k, rotulo: nomeDoDia(e.ocorrido_em), itens: [e] });
    }
    return dias;
  }, [eventosFiltrados, mostrar]);

  const sessaoDoFiltro = filtroSid ? sessoes.find((s) => s.sid === filtroSid) : null;
  const tiposPresentes = useMemo(() => {
    const set = new Set(eventos.map((e) => e.acao));
    return Object.keys(TIPO_EVENTO).filter((k) => set.has(k));
  }, [eventos]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-base-300 pb-4">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
            <Activity className="size-6" style={{ color: "var(--bi-accent-ink)" }} />
            Telemetria
          </h1>
          {/* A frase que separa esta aba da vizinha. Sem ela, as duas parecem a
              mesma coisa com nomes diferentes — e a diferença importa: uma serve
              de prova, a outra de termômetro. */}
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Como o sistema é usado: quem entrou, o que abriu, o que filtrou, o que gerou e quanto
            tempo ficou. É diferente da <strong style={{ color: "var(--bi-text)" }}>Auditoria</strong>,
            que guarda os atos com consequência e serve de prova. Vale para o ambiente inteiro,
            não muda com o município selecionado.
          </p>
          <p className="mt-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
            O tempo <strong>ativo</strong> conta só com a aba em primeiro plano e com clique, tecla ou
            rolagem nos últimos 5 minutos; o resto é <strong>ocioso</strong> (sistema aberto, sem uso).
            Texto digitado nunca é gravado. Os registros ficam por 6 meses.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Abas<Periodo>
            valor={periodo}
            onChange={(v) => { setPeriodo(v); setMostrar(150); }}
            opcoes={[{ valor: "7", label: "7 dias" }, { valor: "30", label: "30 dias" }, { valor: "90", label: "90 dias" }]}
          />
          <Button variant="outline" onClick={() => carregar()} disabled={loading}>
            {loading ? <Loader2 className="mr-1 size-4 animate-spin" /> : <RefreshCw className="mr-1 size-4" />}
            Atualizar
          </Button>
        </div>
      </div>

      {erro && (
        <div className="rounded-2xl p-3 text-sm"
             style={{ background: "color-mix(in oklab, var(--bi-crit) 12%, transparent)",
                      color: "var(--bi-crit-ink)" }}>{erro}</div>
      )}

      {!erro && (
        <>
          {/* Quem está agora, ACIMA de tudo: é a única parte viva da tela — o
              resto é histórico. Fica aqui e em nenhum outro lugar do sistema. */}
          <PresencaAgora />

          {/* EVENTOS À ESQUERDA (mais largo: cada linha é uma frase), SESSÕES À
              DIREITA. No celular empilha, eventos primeiro.
              `data-uso-ignorar`: clicar num evento para ler o detalhe não pode
              virar outro evento ("abriu o detalhe de «Maria abriu...»") — a
              telemetria olhando para si mesma só gera ruído. A abertura da
              tela continua registrada pela navegação. */}
          <div className="grid gap-4 lg:grid-cols-[3fr_2fr]" data-uso-ignorar="">
            {/* ================= EVENTOS ================= */}
            <Bloco className="p-3">
              <BlocoHead icon={MousePointerClick} titulo="Eventos"
                sub={sessaoDoFiltro
                  ? <>só da sessão de <strong>{nome(sessaoDoFiltro)}</strong> às {horaCurta(sessaoDoFiltro.inicio)} · {eventosFiltrados.length} evento(s)</>
                  : `${eventosFiltrados.length} nos últimos ${periodo} dias · clique num evento para ver o detalhe`}
                right={
                  <div className="flex flex-wrap items-center justify-end gap-1.5" data-uso-ignorar="">
                    {filtroSid ? (
                      <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                              onClick={() => setFiltroSid(null)}>
                        <ListFilter className="size-3.5" /> todas as sessões
                      </button>
                    ) : (
                      <select
                        aria-label="Pessoa"
                        className="h-8 rounded-lg border px-2 text-[11px]"
                        style={{ ...ESTILO_SEC }}
                        value={filtroUser ?? ""}
                        onChange={(ev) => { setFiltroUser(ev.target.value ? Number(ev.target.value) : null); setMostrar(150); }}
                      >
                        <option value="">Todas as pessoas</option>
                        {pessoas.map(([id, n]) => <option key={id} value={id}>{n}</option>)}
                      </select>
                    )}
                    <select
                      aria-label="Tipo de evento"
                      className="h-8 rounded-lg border px-2 text-[11px]"
                      style={{ ...ESTILO_SEC }}
                      value={filtroTipo}
                      onChange={(ev) => { setFiltroTipo(ev.target.value); setMostrar(150); }}
                    >
                      <option value="">Todos os tipos</option>
                      {tiposPresentes.map((k) => <option key={k} value={k}>{TIPO_EVENTO[k]}</option>)}
                    </select>
                  </div>
                } />
              {eventosPorDia.length === 0 ? (
                <Vazio>Nenhum evento registrado no período.</Vazio>
              ) : (
                <div className="space-y-3">
                  {eventosPorDia.map((dia) => (
                    <div key={dia.chave}>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide"
                           style={{ color: "var(--bi-faint)" }}>{dia.rotulo}</div>
                      <Lista>
                        {dia.itens.map((e) => {
                          const f = fraseDoEvento(e);
                          return (
                            <ItemLinha
                              key={e.id ?? `${e.sid}-${e.ocorrido_em}`}
                              onClick={() => setEventoAberto(e)}
                              titulo={
                                <>
                                  <strong>{nome(e)}</strong> {f.acao}
                                  {f.onde && <span style={{ color: "var(--bi-muted)" }}> {f.onde}</span>}
                                </>
                              }
                              valor={horaCurta(e.ocorrido_em)}
                              meta={
                                <>
                                  <Selo tom={tomDoTipo(e.acao)}>{TIPO_EVENTO[e.acao] || e.acao}</Selo>
                                  {e.municipio && <span>· {e.municipio}</span>}
                                </>
                              }
                            />
                          );
                        })}
                      </Lista>
                    </div>
                  ))}
                  {eventosFiltrados.length > mostrar && (
                    <button type="button" className={`${BOTAO_SEC} w-full justify-center`} style={ESTILO_SEC}
                            onClick={() => setMostrar((n) => n + 150)}>
                      mostrar mais ({eventosFiltrados.length - mostrar} restantes)
                    </button>
                  )}
                </div>
              )}
            </Bloco>

            {/* ================= SESSÕES ================= */}
            <Bloco className="p-3">
              <BlocoHead icon={Clock} titulo="Sessões"
                sub={`${sessoes.length} nos últimos ${periodo} dias · por dia e por pessoa · clique para ver o detalhe`} />
              {sessoesPorDia.length === 0 ? (
                <Vazio>
                  Ainda não há sessão registrada. A telemetria começa a gravar no próximo login.
                </Vazio>
              ) : (
                <div className="space-y-3">
                  {sessoesPorDia.map((dia) => (
                    <div key={dia.chave}>
                      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide"
                           style={{ color: "var(--bi-faint)" }}>{dia.rotulo}</div>
                      <div className="space-y-2">
                        {dia.pessoas.map((p) => (
                          <div key={p.id} className="bi-card-flat p-2.5">
                            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                              <span className="inline-flex items-center gap-1 text-[13px] font-semibold">
                                <UserIcon className="size-3.5" style={{ color: "var(--bi-muted)" }} />
                                {p.nome}
                              </span>
                              <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                                {p.itens.length} sessão(ões) · {dur(p.total)} no sistema · {dur(p.ativo)} ativo · {dur(p.ocioso)} ocioso
                              </span>
                            </div>
                            <ul className="mt-1.5 flex flex-col gap-1">
                              {p.itens.map((s) => {
                                const fim = fimDaSessao(s.situacao);
                                return (
                                  <li key={s.sid}>
                                    <button
                                      type="button"
                                      data-uso="detalhe"
                                      data-uso-alvo={`sessão de ${p.nome} às ${horaCurta(s.inicio)}`}
                                      onClick={() => setSessaoAberta(s)}
                                      className="flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded-lg px-2 py-1.5 text-left text-[11px] transition-colors bi-hover"
                                      style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
                                    >
                                      <span className="bi-num">
                                        {horaCurta(s.inicio)} → {s.situacao === "ativa" ? "agora" : horaCurta(s.fim || s.ultimo_sinal)}
                                      </span>
                                      <span className="bi-num font-semibold">{dur(s.seg_total)}</span>
                                      <span style={{ color: "var(--bi-muted)" }}>
                                        ativo {dur(s.seg_ativos)} · ocioso {dur(s.seg_ociosos)}
                                      </span>
                                      <span className="ml-auto"><Selo tom={fim.tom}>{fim.texto}</Selo></span>
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Bloco>
          </div>
        </>
      )}

      {/* ================= DETALHE DO EVENTO ================= */}
      <Modal aberto={!!eventoAberto} onFechar={() => setEventoAberto(null)} maxW="max-w-2xl">
        {eventoAberto && (() => {
          const e = eventoAberto;
          const f = fraseDoEvento(e);
          const d = (e.detalhe || {}) as Record<string, unknown>;
          const sessao = sessoes.find((s) => s.sid === e.sid);
          return (
            <>
              <ModalHead
                titulo={<><strong>{nome(e)}</strong> {f.acao}{f.onde ? ` ${f.onde}` : ""}</>}
                sub={horaCompleta(e.ocorrido_em)}
                onFechar={() => setEventoAberto(null)}
              />
              <ModalCorpo className="space-y-3">
                <Secao icon={MousePointerClick} titulo="O evento" cols={3} campos={[
                  { rotulo: "Tipo", valor: TIPO_EVENTO[e.acao] || e.acao },
                  { rotulo: "Tela", valor: nomeDaTela(e.rota, e.tela) },
                  { rotulo: "Rota", valor: e.rota || "—", mono: true },
                  { rotulo: "Alvo", valor: e.alvo || "—", span: 2, quebra: true },
                  { rotulo: "Município", valor: e.municipio || "—" },
                  ...(e.ms ? [{ rotulo: "Duração", valor: dur(e.ms / 1000) }] : []),
                  ...(d.params ? [{ rotulo: "Filtros", valor: descreverParams(d.params), span: 3, quebra: true }] : []),
                  ...(d.valor != null ? [{ rotulo: "Valor escolhido", valor: String(d.valor), span: 2 }] : []),
                  ...(d.grupo ? [{ rotulo: "Filtro", valor: String(d.grupo) }] : []),
                  ...(d.marcado != null ? [{ rotulo: "Marcado", valor: d.marcado ? "sim" : "não" }] : []),
                  ...(d.status ? [{ rotulo: "Resposta da API", valor: String(d.status) }] : []),
                  ...(d.site ? [{ rotulo: "Site", valor: String(d.site) }] : []),
                ]} />
                <Secao icon={Clock} titulo="A sessão em que aconteceu" cols={3} campos={[
                  { rotulo: "Pessoa", valor: nome(e) },
                  { rotulo: "E-mail", valor: e.user_email, mono: true },
                  { rotulo: "Entrou às", valor: sessao ? horaCompleta(sessao.inicio) : "—" },
                  { rotulo: "IP", valor: e.ip || sessao?.ip || "—", mono: true },
                  { rotulo: "Dispositivo", valor: dispositivo(e.user_agent || sessao?.user_agent), span: 2 },
                ]}>
                  {sessao && (
                    <div className="mt-2 flex flex-wrap gap-2">
                      <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                              onClick={() => { setEventoAberto(null); setSessaoAberta(sessao); }}>
                        ver a sessão
                      </button>
                      <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                              onClick={() => { setEventoAberto(null); setFiltroSid(sessao.sid); }}>
                        só os eventos desta sessão
                      </button>
                    </div>
                  )}
                </Secao>
                {e.detalhe && Object.keys(e.detalhe).length > 0 && (
                  <details className="text-[11px]" data-uso-ignorar="">
                    <summary className="cursor-pointer" style={{ color: "var(--bi-faint)" }}>dado bruto</summary>
                    <pre className="bi-scroll mt-1 overflow-x-auto rounded-lg p-2 text-[10px]"
                         style={{ background: "var(--bi-surface-2)" }}>
                      {JSON.stringify(e.detalhe, null, 2)}
                    </pre>
                  </details>
                )}
              </ModalCorpo>
            </>
          );
        })()}
      </Modal>

      {/* ================= DETALHE DA SESSÃO ================= */}
      <Modal aberto={!!sessaoAberta} onFechar={() => setSessaoAberta(null)} maxW="max-w-2xl">
        {sessaoAberta && (() => {
          const s = sessaoAberta;
          const fim = fimDaSessao(s.situacao);
          const pctAtivo = s.seg_total ? Math.round(100 * s.seg_ativos / Math.max(1, s.seg_ativos + s.seg_ociosos)) : 0;
          return (
            <>
              <ModalHead
                titulo={<>Sessão de <strong>{nome(s)}</strong> — {nomeDoDia(s.inicio)}</>}
                sub={`entrou às ${horaCurta(s.inicio)} · ${s.situacao === "ativa" ? "ainda no sistema" : `até ${horaCurta(s.fim || s.ultimo_sinal)}`}`}
                onFechar={() => setSessaoAberta(null)}
                right={<Selo tom={fim.tom}>{fim.texto}</Selo>}
              />
              <ModalCorpo className="space-y-3">
                <Secao icon={Clock} titulo="Tempo" cols={4} campos={[
                  { rotulo: "No sistema", valor: dur(s.seg_total) },
                  { rotulo: "Ativo", valor: dur(s.seg_ativos), tom: "ok" },
                  { rotulo: "Ocioso", valor: dur(s.seg_ociosos), tom: s.seg_ociosos > s.seg_ativos ? "atencao" : "neutro" },
                  { rotulo: "Aproveitamento", valor: `${pctAtivo}% ativo` },
                  { rotulo: "Entrou", valor: horaCompleta(s.inicio) },
                  { rotulo: "Último sinal", valor: horaCompleta(s.ultimo_sinal) },
                  { rotulo: "Saiu", valor: s.fim ? horaCompleta(s.fim) : (s.situacao === "ativa" ? "ainda não" : "sem registro") },
                  { rotulo: "Eventos", valor: `${s.eventos}${s.descartados ? ` (+${s.descartados} descartados)` : ""}` },
                ]}>
                  <p className="mt-2 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                    <LogOut className="mr-1 inline size-3.5 align-text-bottom" />
                    {s.situacao === "logout" && "A pessoa clicou em Sair: a sessão foi encerrada por ela."}
                    {s.situacao === "navegador_fechado" && "A pessoa fechou o navegador (ou a aba) sem clicar em Sair, e ninguém voltou em 5 minutos: o sistema encerrou a sessão."}
                    {s.situacao === "aba_fechada" && "A aba se despediu há pouco. Se ninguém voltar em 5 minutos, a sessão é encerrada."}
                    {s.situacao === "expirou" && "O navegador parou de dar sinal sem se despedir (rede, notebook fechado, computador desligado). A sessão expirou sozinha."}
                    {s.situacao === "ativa" && "A sessão está em uso agora."}
                    {!["logout", "navegador_fechado", "aba_fechada", "expirou", "ativa"].includes(s.situacao) && "Sessão encerrada."}
                  </p>
                </Secao>
                <Secao icon={Monitor} titulo="De onde" cols={3} campos={[
                  { rotulo: "Pessoa", valor: nome(s) },
                  { rotulo: "E-mail", valor: s.user_email, mono: true },
                  { rotulo: "Última tela", valor: nomeDaTela(null, s.tela_atual || undefined) },
                  { rotulo: "IP", valor: s.ip || "—", mono: true },
                  { rotulo: "Dispositivo", valor: dispositivo(s.user_agent), span: 2 },
                ]}>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                            onClick={() => { setSessaoAberta(null); setFiltroSid(s.sid); setFiltroTipo(""); }}>
                      ver os eventos desta sessão
                    </button>
                  </div>
                </Secao>
              </ModalCorpo>
            </>
          );
        })()}
      </Modal>
    </div>
  );
}
