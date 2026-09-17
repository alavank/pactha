"use client";

/* O MODAL DO COMPROMISSO — criar, ler, editar e anotar, numa caixa só.
 *
 * ⭐ TRÊS MODOS E UM LAYOUT. Detalhe e edição mostram os MESMOS campos na MESMA
 * ordem; o que muda é se eles são campo ou texto. Duas caixas diferentes para o
 * mesmo registro fariam a pessoa reaprender onde fica cada coisa ao clicar em
 * «Editar» — e é justamente aí que ela está procurando um campo específico.
 *
 * ⚠️ ANOTAR NÃO EXIGE ENTRAR EM EDIÇÃO (documento). O histórico é append-only e
 * a anotação é de quem escreve, não do dono do compromisso: pedir «Editar» para
 * responder uma pergunta transformaria um comentário num ato de alteração — e o
 * alcance por linha barraria quem só quer responder.
 *
 * ⚠️ A SITUAÇÃO APARECE, MAS NÃO É CAMPO. Ela é a coluna do kanban, e é lá que
 * ela muda (arrastando ou pelo seletor do cartão). Repetir aqui um seletor de
 * coluna criaria dois lugares para o mesmo gesto, e o segundo é sempre o que
 * esquece de invalidar alguma coisa.
 *
 * ⚠️ AS VALIDAÇÕES SÃO AS MESMAS DO BACKEND, de propósito. Validação que só
 * existe aqui é sugestão — um `curl` a ignora. O que estas evitam é a viagem:
 * a pessoa descobre na hora que o término precisa ser depois do início, em vez
 * de descobrir num 422 depois de salvar.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  CalendarOff, Check, Loader2, MessageSquarePlus, Paperclip, Pencil, Trash2,
} from "lucide-react";

import api from "@/lib/api";
import {
  BOTAO_CTA, BOTAO_SEC, ESTILO_CTA, ESTILO_SEC, Modal, ModalCorpo, ModalHead,
  Selo,
} from "@/components/ui/superficies";
import type { MunicipioEscolha } from "@/components/TransicaoMunicipio";
import { VisualizadorDocumento } from "@/components/ui/VisualizadorDocumento";
import {
  Anotacao, Coluna, Compromisso, CorPaleta, MapaFeriados, diaBR,
  ehFeriadoDeVerdade, estiloDaCor, hojeISO, horarioDe, mascaraTelefone, minutos,
  rotuloFeriado, telefoneBR,
} from "./tipos";

export type ModoModal = "criar" | "detalhe" | "editar";

interface Props {
  modo: ModoModal;
  item: Compromisso | null;
  /** Pré-preenchimento vindo do clique no calendário. */
  inicial?: { data?: string; hora?: string };
  comMunicipio: boolean;
  municipios: MunicipioEscolha[];
  paleta: CorPaleta[];
  colunas: Coluna[];
  /** Para avisar quando a data escolhida cai em feriado. */
  feriados: MapaFeriados;
  onModo: (m: ModoModal) => void;
  onFechar: () => void;
  /** Salvou, excluiu ou anotou — a página recarrega a fonte única. */
  onMudou: () => void;
}

interface Form {
  municipio_id: string;
  demanda: string;
  data: string;
  hora_inicio: string;
  tem_periodo: boolean;
  hora_fim: string;
  data_solicitacao: string;
  solicitante: string;
  contato_whatsapp: string;
  cor: string;
  anotacao: string;
}

function formDe(item: Compromisso | null, inicial: Props["inicial"],
                padraoCor: string): Form {
  return {
    municipio_id: item ? String(item.municipio_id) : "",
    demanda: item?.demanda || "",
    data: item?.data?.slice(0, 10) || inicial?.data || hojeISO(),
    hora_inicio: item?.hora_inicio || inicial?.hora || "09:00",
    tem_periodo: !!item?.tem_periodo,
    hora_fim: item?.hora_fim || "",
    /* Só o formulário de CRIAÇÃO assume hoje. Num compromisso antigo, sem data
       de solicitação gravada, preencher com hoje aqui gravaria uma data falsa
       na primeira edição que a pessoa fizesse por outro motivo. */
    data_solicitacao: item ? (item.data_solicitacao?.slice(0, 10) || "") : hojeISO(),
    solicitante: item?.solicitante || "",
    contato_whatsapp: item ? mascaraTelefone(item.contato_whatsapp || "") : "",
    cor: item?.cor || padraoCor,
    anotacao: "",
  };
}

export default function CompromissoModal({
  modo, item, inicial, comMunicipio, municipios, paleta, colunas, feriados,
  onModo, onFechar, onMudou,
}: Props) {
  const padraoCor = paleta[0]?.hex || "#12b886";
  const [f, setF] = useState<Form>(() => formDe(item, inicial, padraoCor));
  const [erro, setErro] = useState<string | null>(null);
  const [campoRuim, setCampoRuim] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [confirmaExcluir, setConfirmaExcluir] = useState(false);
  const [anotacoes, setAnotacoes] = useState<Anotacao[]>([]);
  const [nova, setNova] = useState("");
  const [anotando, setAnotando] = useState(false);
  /* ⚠️ `useState` E NÃO `useRef`, e a diferença não é estilo: ler `ref.current`
     durante o render é justamente o que o React desaconselha (e o lint acusa) —
     um ref não participa do render, e o valor lido ali pode ser o de antes. O
     inicializador preguiçoso do `useState` roda UMA vez, que é o que este
     retrato do formulário precisa ser. */
  const [retratoInicial] = useState(
    () => JSON.stringify(formDe(item, inicial, padraoCor)));

  const lendo = modo === "detalhe";
  const criando = modo === "criar";
  const coluna = colunas.find((c) => c.id === item?.coluna_id);

  /* O histórico só existe no detalhe (`GET /agendamentos/{id}`) — a listagem
     manda apenas o CONTADOR, para uma agenda de mês não trazer trinta
     históricos só para desenhar a grade. */
  useEffect(() => {
    /* ⚠️ SEM `setAnotacoes([])` NO RAMO DE CRIAÇÃO. O estado já nasce vazio, e
       zerá-lo aqui seria um `setState` síncrono dentro do efeito — cascata de
       render que o lint acusa e que não compra nada: a caixa de criação nem
       desenha o histórico. */
    if (!item) return;
    let vivo = true;
    api.get(`/agendamentos/${item.id}`)
      .then((r) => { if (vivo) setAnotacoes(r.data?.anotacoes || []); })
      .catch(() => { /* sem histórico a caixa continua servindo para o resto */ });
    return () => { vivo = false; };
  }, [item]);

  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF((x) => ({ ...x, [k]: v }));
    setErro(null); setCampoRuim(null);
  };

  const sujo = useMemo(
    () => JSON.stringify(f) !== retratoInicial, [f, retratoInicial]);

  /** As mesmas regras do backend, NA ORDEM EM QUE A PESSOA LÊ O FORMULÁRIO.
   *
   *  ⚠️ A ordem daqui acompanha a dos campos, e não é detalhe: só uma mensagem
   *  aparece por vez, e se ela apontar para um campo abaixo do primeiro que está
   *  vazio, a pessoa conserta um, salva de novo e leva outro erro — subindo a
   *  tela a cada tentativa. */
  const validar = (): string | null => {
    if (!f.data) { setCampoRuim("data"); return "Escolha a data do compromisso."; }
    if (!f.hora_inicio) { setCampoRuim("hora_inicio"); return "Informe o horário."; }
    if (f.tem_periodo) {
      if (!f.hora_fim) {
        setCampoRuim("hora_fim"); return "Com período marcado, o término é obrigatório.";
      }
      if (minutos(f.hora_fim) <= minutos(f.hora_inicio)) {
        setCampoRuim("hora_fim"); return "O término precisa ser depois do início.";
      }
    }
    if (!f.solicitante.trim()) {
      setCampoRuim("solicitante"); return "Diga quem solicitou.";
    }
    if (comMunicipio && !f.municipio_id) {
      setCampoRuim("municipio_id"); return "Escolha o município do compromisso.";
    }
    const zap = f.contato_whatsapp.replace(/\D/g, "");
    if (zap && zap.length !== 10 && zap.length !== 11) {
      setCampoRuim("contato_whatsapp");
      return "O contato precisa ter DDD e 8 ou 9 dígitos.";
    }
    if (!f.demanda.trim()) {
      setCampoRuim("demanda"); return "Descreva a demanda — é o que aparece no calendário.";
    }
    return null;
  };

  const salvar = async () => {
    const problema = validar();
    if (problema) { setErro(problema); return; }
    setSalvando(true); setErro(null);
    const corpo = {
      ...(comMunicipio ? { municipio_id: Number(f.municipio_id) } : {}),
      demanda: f.demanda.trim(),
      data: f.data,
      hora_inicio: f.hora_inicio,
      tem_periodo: f.tem_periodo,
      hora_fim: f.tem_periodo ? f.hora_fim : null,
      data_solicitacao: f.data_solicitacao || null,
      solicitante: f.solicitante.trim(),
      contato_whatsapp: f.contato_whatsapp.replace(/\D/g, "") || null,
      cor: f.cor,
    };
    try {
      if (item) await api.put(`/agendamentos/${item.id}`, corpo);
      else await api.post("/agendamentos", { ...corpo, anotacao: f.anotacao.trim() || null });
      onMudou();
      onFechar();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail || "Não foi possível salvar.");
    } finally { setSalvando(false); }
  };

  const excluir = async () => {
    if (!item) return;
    setSalvando(true); setErro(null);
    try {
      await api.delete(`/agendamentos/${item.id}`);
      onMudou();
      onFechar();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail || "Não foi possível excluir.");
      setSalvando(false);
    }
  };

  const anotar = async () => {
    if (!item || !nova.trim()) return;
    setAnotando(true); setErro(null);
    try {
      await api.post(`/agendamentos/${item.id}/anotacoes`, { texto: nova.trim() });
      const r = await api.get(`/agendamentos/${item.id}`);
      setAnotacoes(r.data?.anotacoes || []);
      setNova("");
      /* A lista de fora precisa saber: o contador de anotações do cartão e da
         linha vem de lá, e sem isto ele só mudaria no próximo F5. */
      onMudou();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      setErro(err?.response?.data?.detail || "Não foi possível anotar.");
    } finally { setAnotando(false); }
  };

  const titulo = criando ? "Novo compromisso"
    : lendo ? "Compromisso" : "Editar compromisso";

  return (
    <Modal
      aberto onFechar={onFechar} maxW="max-w-2xl" superficie rotulo={titulo}
      /* ⚠️ GUARDA O TRABALHO nas TRÊS saídas (Esc, véu e X). No modo leitura
         não há o que perder, e perguntar ali seria atrito puro. */
      podeFechar={() => (lendo || !sujo || salvando)
        ? true
        : window.confirm("Descartar as alterações deste compromisso?")}
    >
      <ModalHead
        titulo={titulo}
        sub={item
          ? `${diaBR(item.data, true)} · ${horarioDe(item)}`
          : "Quando é, quem pediu e do que se trata"}
        onFechar={onFechar}
        right={
          <div className="flex items-center gap-2">
            {coluna && <Selo>{coluna.nome}</Selo>}
            {lendo && (
              <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                      onClick={() => onModo("editar")}>
                <Pencil className="size-3.5" /> Editar
              </button>
            )}
          </div>
        }
      />
      <ModalCorpo className="space-y-3">
        <div className="bi-card p-3">
          <div className="space-y-3">
            {/* ⭐ A ORDEM DOS CAMPOS É A DO DONO (rodada 1 de ajustes), e ela
                conta a história na sequência em que o compromisso acontece:
                QUANDO é (data e hora), QUEM pediu (solicitante, município,
                contato), DO QUE se trata (demanda), e só então os acessórios
                (quando o pedido chegou, a cor). A versão anterior abria pela
                demanda, que é o campo que a pessoa preenche por último — ela
                digitava o texto antes de saber para quando estava marcando. */}
            <div className="grid gap-3 sm:grid-cols-2">
              <Campo rotulo="Data" obrigatorio erro={campoRuim === "data"}>
                {lendo ? <Leitura>{diaBR(item?.data ?? null, true)}</Leitura> : (
                  /* ⚠️ `<input type="date">` só aceita `YYYY-MM-DD`. Passar por
                     formatador pt-BR aqui deixa o campo VAZIO sem erro nenhum —
                     o navegador ignora o valor que não reconhece. */
                  <input type="date" value={f.data}
                         onChange={(e) => set("data", e.target.value)}
                         className="bi-field h-9 w-full px-2 text-[13px]" />
                )}
              </Campo>

              <Campo rotulo={f.tem_periodo ? "Início" : "Horário"} obrigatorio
                     erro={campoRuim === "hora_inicio"}>
                {lendo ? <Leitura>{item ? horarioDe(item) : "—"}</Leitura> : (
                  <input type="time" value={f.hora_inicio} step={300}
                         onChange={(e) => set("hora_inicio", e.target.value)}
                         className="bi-field h-9 w-full px-2 text-[13px]" />
                )}
              </Campo>
            </div>

            {/* ⭐ O AVISO DE FERIADO É INFORMAÇÃO, NUNCA BLOQUEIO. Marcar
                compromisso em feriado é legítimo — plantão, mutirão, uma visita
                combinada com o prefeito num sábado de ponto facultativo. O que
                não pode é a pessoa descobrir DEPOIS. Fica colado no par
                Data/Horário, que é onde a escolha acabou de ser feita, e some
                sozinho quando a data muda.
                ⚠️ E ele distingue feriado de ponto facultativo, pelo mesmo
                motivo do calendário: dizer que a terça de carnaval é feriado
                nacional seria a tela afirmando o que a lei não diz. */}
            {(() => {
              const fer = feriados.get(f.data);
              if (!fer?.length) return null;
              const forte = ehFeriadoDeVerdade(fer);
              return (
                <p className="flex items-start gap-1.5 rounded-lg px-2 py-1.5 text-[11px] leading-snug"
                   style={{ background: "var(--bi-info-soft)",
                            color: "var(--bi-info-ink)" }}>
                  <CalendarOff className="mt-0.5 size-3.5 shrink-0" />
                  <span>
                    {diaBR(f.data, true)} é {forte ? "feriado" : "ponto facultativo"}
                    {" — "}{rotuloFeriado(fer)}.
                  </span>
                </p>
              );
            })()}

            {/* O toggle abre em HORÁRIO FIXO por padrão (documento): a maioria
                dos compromissos é um ponto na agenda, não uma faixa. */}
            {!lendo && (
              <div className={`grid gap-3 ${f.tem_periodo ? "sm:grid-cols-2" : ""}`}>
                <label className="flex cursor-pointer items-center gap-2 text-[12px]">
                  <input type="checkbox" checked={f.tem_periodo}
                         onChange={(e) => setF((x) => ({
                           ...x, tem_periodo: e.target.checked,
                           /* Desmarcar LIMPA o término — é o que impede o bloco
                              de continuar esticado no calendário depois de a
                              pessoa dizer que ele não tem período. */
                           hora_fim: e.target.checked ? x.hora_fim : "",
                         }))}
                         className="size-3.5 accent-[var(--bi-accent-ink)]" />
                  Definir período (início e término)
                </label>
                {f.tem_periodo && (
                  <Campo rotulo="Término" obrigatorio erro={campoRuim === "hora_fim"}>
                    <input type="time" value={f.hora_fim} step={300}
                           onChange={(e) => set("hora_fim", e.target.value)}
                           className="bi-field h-9 w-full px-2 text-[13px]" />
                  </Campo>
                )}
              </div>
            )}

            <div className={`grid gap-3 ${comMunicipio ? "sm:grid-cols-2" : ""}`}>
              <Campo rotulo="Solicitante" obrigatorio erro={campoRuim === "solicitante"}>
                {lendo ? <Leitura>{item?.solicitante || "—"}</Leitura> : (
                  <input value={f.solicitante} maxLength={120}
                         onChange={(e) => set("solicitante", e.target.value)}
                         placeholder="Quem pediu"
                         className="bi-field h-9 w-full px-2 text-[13px]" />
                )}
              </Campo>

              {comMunicipio && (
                <Campo rotulo="Município" obrigatorio erro={campoRuim === "municipio_id"}>
                  {lendo ? (
                    <Leitura>{item ? `${item.municipio}${item.uf ? ` - ${item.uf}` : ""}` : "—"}</Leitura>
                  ) : (
                    /* O MESMO seletor do resto do sistema: a lista vem do
                       `MunicipioContext`, que a barra lateral já carregou e já
                       filtrou por permissão. Rebuscar aqui duplicaria a
                       requisição E a regra de alcance. */
                    <select value={f.municipio_id}
                            onChange={(e) => set("municipio_id", e.target.value)}
                            className="bi-field h-9 w-full px-2 text-[13px]">
                      <option value="">Selecione…</option>
                      {municipios.map((m) => (
                        <option key={m.id} value={String(m.id)}>
                          {m.nome}{m.uf ? ` - ${m.uf}` : ""}
                        </option>
                      ))}
                    </select>
                  )}
                </Campo>
              )}
            </div>

            <Campo rotulo="Contato WhatsApp" erro={campoRuim === "contato_whatsapp"}>
              {lendo ? (
                item?.contato_whatsapp ? (
                  /* No modo leitura o número vira ação: abrir a conversa é o
                     que a pessoa faz com ele em 100% dos casos. */
                  <a href={`https://wa.me/55${item.contato_whatsapp}`}
                     target="_blank" rel="noopener noreferrer"
                     className="text-[13px] underline"
                     style={{ color: "var(--bi-accent-ink)" }}>
                    {telefoneBR(item.contato_whatsapp)}
                  </a>
                ) : <Leitura>—</Leitura>
              ) : (
                <input value={f.contato_whatsapp} inputMode="numeric"
                       onChange={(e) => set("contato_whatsapp", mascaraTelefone(e.target.value))}
                       placeholder="(51) 99999-9999"
                       className="bi-field h-9 w-full px-2 text-[13px]" />
              )}
            </Campo>

            <Campo rotulo="Demanda" obrigatorio erro={campoRuim === "demanda"}>
              {lendo ? <Leitura forte>{item?.demanda}</Leitura> : (
                <input value={f.demanda} maxLength={200}
                       onChange={(e) => set("demanda", e.target.value)}
                       placeholder="Visita técnica na obra da creche"
                       className="bi-field h-9 w-full px-2 text-[13px]" />
              )}
            </Campo>

            <Campo rotulo="Data da solicitação">
              {lendo ? (
                <Leitura>{item?.data_solicitacao ? diaBR(item.data_solicitacao, true) : "—"}</Leitura>
              ) : (
                <input type="date" value={f.data_solicitacao}
                       onChange={(e) => set("data_solicitacao", e.target.value)}
                       className="bi-field h-9 w-full px-2 text-[13px] sm:max-w-[15rem]" />
              )}
            </Campo>

            <Campo rotulo="Cor">
              {lendo ? (
                <span className="inline-flex items-center gap-2 text-[13px]">
                  <span className="ag-tarja size-3.5 rounded-full"
                        style={estiloDaCor(item?.cor || f.cor)} />
                  {paleta.find((c) => c.hex === item?.cor)?.nome || "—"}
                </span>
              ) : (
                /* ⚠️ SWATCHES FIXOS, e não seletor livre de cor (documento): a
                   cor identifica o compromisso nas três abas, e uma paleta
                   aberta em pouco tempo produz dez tons de verde que ninguém
                   distingue no chip de 10px do calendário. */
                <div className="flex flex-wrap gap-1.5">
                  {paleta.map((c) => (
                    <button key={c.hex} type="button" title={c.nome}
                            aria-label={c.nome} aria-pressed={f.cor === c.hex}
                            onClick={() => set("cor", c.hex)}
                            className="grid size-7 place-items-center rounded-full transition-transform hover:scale-110"
                            style={{ background: c.hex,
                                     outline: f.cor === c.hex
                                       ? "2px solid var(--bi-text)" : "none",
                                     outlineOffset: 2 }}>
                      {f.cor === c.hex && <Check className="size-3.5 text-white" />}
                    </button>
                  ))}
                </div>
              )}
            </Campo>
          </div>
        </div>

        {/* ------------------------------------------------------ anotações */}
        <div className="bi-card p-3">
          <h4 className="bi-title mb-2 text-[13px]">Anotações</h4>
          {criando ? (
            <>
              <textarea value={f.anotacao} rows={3}
                        onChange={(e) => set("anotacao", e.target.value)}
                        placeholder="O que ficou combinado, o contexto do pedido…"
                        className="bi-field w-full p-2 text-[13px]" />
              <p className="mt-1 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                Vira a primeira anotação do histórico. Depois de criado, ninguém
                edita nem apaga uma anotação — só se acrescenta.
              </p>
            </>
          ) : (
            <>
              {anotacoes.length === 0 ? (
                <p className="text-[12px]" style={{ color: "var(--bi-faint)" }}>
                  Nenhuma anotação ainda.
                </p>
              ) : (
                <ul className="space-y-2">
                  {anotacoes.map((n) => (
                    <li key={n.id} className="bi-card-flat p-2">
                      <p className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
                        {n.autor || "autor desconhecido"} ·{" "}
                        {n.criado_em
                          ? new Date(n.criado_em).toLocaleString("pt-BR",
                              { dateStyle: "short", timeStyle: "short" })
                          : ""}
                      </p>
                      <p className="mt-0.5 whitespace-pre-wrap text-[12.5px] leading-snug">
                        {n.texto}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-2 flex items-start gap-2">
                <textarea value={nova} rows={2}
                          onChange={(e) => setNova(e.target.value)}
                          placeholder="Adicionar anotação…"
                          className="bi-field min-w-0 flex-1 p-2 text-[13px]" />
                <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                        onClick={anotar} disabled={anotando || !nova.trim()}>
                  {anotando ? <Loader2 className="size-3.5 animate-spin" />
                            : <MessageSquarePlus className="size-3.5" />}
                  Anotar
                </button>
              </div>
            </>
          )}
        </div>

        {/* Anexos: só o que foi anexado ANTES do redesenho. O formulário novo
            não anexa — mas o documento que já está no banco continua
            alcançável, senão a mudança de tela apagaria o acesso a ele. */}
        {!!item?.anexos?.length && (
          <div className="bi-card p-3">
            <h4 className="bi-title mb-2 text-[13px]">
              Anexos <span className="font-normal" style={{ color: "var(--bi-faint)" }}>
                · registrados antes do redesenho
              </span>
            </h4>
            <ul className="space-y-1">
              {item.anexos.map((ax, i) => (
                <li key={`${ax.nome}-${i}`}>
                  <BotaoAnexo id={item.id} idx={i} nome={ax.nome} />
                </li>
              ))}
            </ul>
          </div>
        )}

        {erro && (
          /* ⚠️ `color-mix` E NÃO `--bi-crit-bg`: esse token nunca existiu
             (a primeira versão desta tela o usava e caía em transparente — o
             aviso de erro saía como texto vermelho solto, sem caixa). */
          <p role="alert" className="rounded-xl px-3 py-2 text-[12px]"
             style={{ background: "color-mix(in oklab, var(--bi-crit) 14%, transparent)",
                      color: "var(--bi-crit-ink)" }}>
            {erro}
          </p>
        )}

        {!lendo && (
          <div className="flex flex-wrap items-center gap-2">
            {item && !confirmaExcluir && (
              /* Discreto de propósito: excluir não pode competir com salvar. */
              <button type="button" onClick={() => setConfirmaExcluir(true)}
                      className="inline-flex items-center gap-1 text-[11px] underline"
                      style={{ color: "var(--bi-muted)" }}>
                <Trash2 className="size-3" /> Excluir compromisso
              </button>
            )}
            {item && confirmaExcluir && (
              <span className="flex items-center gap-2 text-[11px]">
                Excluir mesmo? As anotações vão junto.
                <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                        onClick={excluir} disabled={salvando}>sim, excluir</button>
                <button type="button" className="underline"
                        style={{ color: "var(--bi-muted)" }}
                        onClick={() => setConfirmaExcluir(false)}>não</button>
              </span>
            )}
            <button type="button" className={`${BOTAO_SEC} ml-auto`} style={ESTILO_SEC}
                    onClick={onFechar} disabled={salvando}>
              Cancelar
            </button>
            <button type="button" className={BOTAO_CTA} style={ESTILO_CTA}
                    onClick={salvar} disabled={salvando}>
              {salvando && <Loader2 className="size-3.5 animate-spin" />}
              {criando ? "Adicionar compromisso" : "Salvar alterações"}
            </button>
          </div>
        )}
      </ModalCorpo>
    </Modal>
  );
}

/* ------------------------------------------------------------- peças ------ */

function Campo({ rotulo, obrigatorio, erro, children }: {
  rotulo: string;
  obrigatorio?: boolean;
  erro?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px]" style={{ color: erro ? "var(--bi-crit-ink)" : "var(--bi-muted)" }}>
        {rotulo}
        {obrigatorio && <span aria-hidden="true" style={{ color: "var(--bi-crit-ink)" }}> *</span>}
      </span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Leitura({ children, forte }: { children: ReactNode; forte?: boolean }) {
  return (
    <p className={`text-[13px] ${forte ? "font-semibold" : ""}`}>{children}</p>
  );
}

/** O anexo ABRE no VisualizadorDocumento (Baixar e Imprimir lá dentro) — era
 *  download direto. A leitura do erro mora no visualizador: 403 de quem não tem
 *  `anexo_baixar` e 404 de índice fora da lista viram mensagem, nunca um
 *  "oficio.pdf" de 90 bytes com `{"detail":"..."}` dentro. */
function BotaoAnexo({ id, idx, nome }: { id: number; idx: number; nome: string }) {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setAberto(true)}
              className="inline-flex items-center gap-1.5 text-[12px] underline"
              style={{ color: "var(--bi-accent-ink)" }}>
        <Paperclip className="size-3" />
        {nome}
      </button>
      <VisualizadorDocumento
        nivel={2}
        onFechar={() => setAberto(false)}
        doc={aberto ? {
          titulo: nome,
          sub: "Anexo do compromisso",
          src: `/agendamentos/${id}/anexo/${idx}`,
          nomeArquivo: nome,
          mensagem403: "Você não tem permissão para abrir anexos (peça "
                     + "«Agendamentos → Baixar anexos» ao administrador).",
        } : null}
      />
    </>
  );
}
