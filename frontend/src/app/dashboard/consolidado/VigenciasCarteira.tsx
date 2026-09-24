"use client";

/* CONSOLIDADO › VIGÊNCIAS — os instrumentos da carteira vencendo em até 120 dias.
 *
 *  ⭐ ERA O MODAL "Vigências" DO PAINEL DE INDICADORES (`components/bi/
 *  VigenciasModal.tsx`), e veio para cá em 19/09/2026 a pedido do dono: era a
 *  única coisa do sistema que ignorava o município selecionado — "não faz
 *  sentido algo não respeitar o município selecionado a não ser o Consolidado".
 *  O botão saiu do Painel; o conteúdo é o mesmo, agora como aba.
 *
 *  DUAS VISÕES do mesmo recorte, porque as perguntas são diferentes:
 *   - BOLHAS por município: "onde está concentrado?" — o tamanho é a quantidade,
 *     então um município com 9 vencendo salta antes de qualquer leitura de lista.
 *   - LISTA por dias: "o que vence primeiro?" — ordenável nos dois sentidos.
 *  O KPI no topo acompanha o filtro de municípios (multisseleção), então o número
 *  nunca discorda do que está logo abaixo — o erro clássico de dashboard.
 *
 *  ⭐ CADA INSTRUMENTO É CLICÁVEL (19/09/2026): o estadual abre o modal do
 *  convênio e a voluntária abre o da proposta — os MESMOS das telas de origem,
 *  para o gestor não sair procurando.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  CalendarClock, Circle, List, ArrowUpDown, Lock, Download, FileText, Sheet, Loader2,
} from "lucide-react";
import api from "@/lib/api";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { MultiSelect } from "@/components/ui/multi-select";
import { Bloco, BlocoHead, Modal, ModalCorpo, ModalHead } from "@/components/ui/superficies";
import { baixarVigencias, type FormatoVigencias } from "@/lib/vigenciasExport";
import ConvenioDetailModal from "@/app/dashboard/convenios/ConvenioDetailModal";
import { DetalheVoluntariaModal, type Detalhe as DetalheVoluntaria } from "@/components/TransfereGovPropostas";

interface Alerta {
  id: number;
  esfera?: string | null;
  municipio_id?: number | null;
  nr_convenio?: string | null;
  nr_sigcon?: string | null;
  nr_siafi?: string | null;
  objeto?: string | null;
  situacao?: string | null;
  alteracao_tipo?: string | null;
  alteracao_situacao?: string | null;
  alteracao_data?: string | null;
  dt_fim_vigencia?: string | null;
  dias_restantes?: number | null;
  municipio_nome?: string | null;
  orgao_concedente?: string | null;
  valor_total?: number | null;
}

const DIAS = 120;

function tomDias(d?: number | null): { bg: string; fg: string } {
  const n = d ?? 999;
  if (n <= 30) return { bg: "var(--bi-critico-bg, #FEE2E2)", fg: "var(--bi-critico-ink, #991B1B)" };
  if (n <= 60) return { bg: "var(--bi-atencao-bg, #FEF3C7)", fg: "var(--bi-atencao-ink, #92400E)" };
  return { bg: "var(--bi-surface-2)", fg: "var(--bi-muted)" };
}

/** Um instrumento a vencer. É o MESMO cartão nas duas visões — na lista solta e
 *  dentro do município na visão de bolhas — para o dado não mudar de cara. */
/** O número que a pessoa reconhece — o mesmo rótulo do relatório (vigencias_export._numero):
 *  sem nº de convênio, o que sobra sai ROTULADO ("SIAFI …" / "Proposta …"), nunca solto. */
function numeroDoAlerta(i: Alerta): string {
  const conv = (i.nr_convenio || "").trim();
  const sig = (i.nr_sigcon || "").trim();
  const siafi = (i.nr_siafi || "").trim();
  if (i.esfera === "estadual") {
    if (conv) return siafi && siafi !== conv ? `${conv} (SIAFI ${siafi})` : conv;
    // SIAFI só quando É SIAFI (mesma regra de `vigencias_export._numero`): a chave
    // interna de RS/PR/TO/ES e o nº do plano do SIGCON saem como estão.
    if (siafi) return `SIAFI ${siafi}`;
    return /^\d+$/.test(sig) ? `SIAFI ${sig}` : sig;
  }
  if (conv && conv !== sig) return conv;
  return sig ? `Proposta ${sig}` : conv;
}

function LinhaAlerta({ i, nome, onAbrir }: { i: Alerta; nome: string; onAbrir: (i: Alerta) => void }) {
  const tom = tomDias(i.dias_restantes);
  const numero = numeroDoAlerta(i);
  const alteracao = [i.alteracao_tipo, i.alteracao_situacao].filter(Boolean).join(" — ");
  return (
    <button type="button" onClick={() => onAbrir(i)}
            className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left bi-hover"
            style={{ background: "var(--bi-surface-2)" }}
            title="Abrir o instrumento">
      <span className="shrink-0 rounded-md px-2 py-1 text-[11px] font-bold" style={{ background: tom.bg, color: tom.fg }}>
        {i.dias_restantes ?? "—"}d
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium" style={{ color: "var(--bi-text)" }}>
          {i.objeto || i.nr_convenio || i.nr_sigcon || "—"}
        </div>
        <div className="truncate text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {nome}
          {i.esfera === "voluntaria" ? " · federal (voluntária)" : i.esfera ? ` · ${i.esfera}` : ""}
          {numero ? ` · nº ${numero}` : ""}
          {i.dt_fim_vigencia ? ` · vence em ${new Date(`${String(i.dt_fim_vigencia).slice(0, 10)}T00:00:00`).toLocaleDateString("pt-BR")}` : ""}
          {i.situacao ? ` · ${i.situacao}` : ""}
        </div>
        {alteracao && (
          <div className="truncate text-[11px] font-medium" style={{ color: "var(--bi-atencao-ink, #92400E)" }}
               title="Alteração registrada no SIGCON (termo aditivo / prorrogação). O prazo só muda depois de publicada.">
            SIGCON: {alteracao}{i.alteracao_data ? ` (${i.alteracao_data})` : ""}
          </div>
        )}
      </div>
    </button>
  );
}

export function VigenciasCarteira() {
  const { municipios } = useMunicipio();
  const [itens, setItens] = useState<Alerta[]>([]);
  const [carregando, setCarregando] = useState(true);
  /* ⭐ SEM PERMISSAO ≠ SEM NADA VENCENDO, e confundir os dois foi o defeito que
     motivou este bloco (pedido do dono, 08/2026): quem não tinha acesso levava
     403, o `catch` zerava a lista em silêncio e a tela anunciava «Nenhum
     instrumento vencendo em 120 dias». Hoje quem libera é a caixinha
     «Vigências a vencer» do modal de Permissões. */
  const [semAcesso, setSemAcesso] = useState(false);
  const [visao, setVisao] = useState<"bolhas" | "lista">("bolhas");
  const [asc, setAsc] = useState(true);
  const [munSel, setMunSel] = useState<string[]>([]);
  // Bolha CLICADA: a visão de bolhas mostra os mesmos itens da lista,
  // só que agrupados — clicar abre os convênios daquele município.
  const [munAberto, setMunAberto] = useState<string | null>(null);
  // O instrumento aberto no modal de detalhe.
  const [convAberto, setConvAberto] = useState<{ id: number; esfera: string } | null>(null);
  const [vol, setVol] = useState<{ municipioId: number | null; detalhe: DetalheVoluntaria | null;
                                   carregando: boolean } | null>(null);

  const nomePorId = useMemo(() => {
    const m: Record<string, string> = {};
    municipios.forEach((x) => { m[String(x.id)] = x.nome; });
    return m;
  }, [municipios]);

  /** Nome do município do alerta. A API manda `municipio_nome` junto — o
   *  cruzamento por id fica como queda. */
  const nomeDo = useCallback(
    (a: Alerta) => a.municipio_nome || nomePorId[String(a.municipio_id)] || "—",
    [nomePorId],
  );

  useEffect(() => {
    let vivo = true;
    // Sem municipio_id => a carteira inteira (o endpoint já respeita o alcance
    // do usuário). Um pedido só; o recorte por município é local, para o filtro
    // responder na hora.
    api.get<Alerta[]>("/convenios/alertas", { params: { dias: DIAS } })
      .then((r) => { if (vivo) setItens(r.data || []); })
      .catch((e: unknown) => {
        if (!vivo) return;
        setItens([]);
        /* SÓ o 403 vira "sem permissão". Uma queda de rede ou um 500 continuam
           caindo no vazio de sempre — dizer "você não tem acesso" para quem tem
           mandaria o gestor pedir uma permissão que ele já possui. */
        const status = (e as { response?: { status?: number } })?.response?.status;
        setSemAcesso(status === 403);
      })
      .finally(() => { if (vivo) setCarregando(false); });
    return () => { vivo = false; };
  }, []);

  const abrir = useCallback(async (i: Alerta) => {
    if (i.esfera === "voluntaria") {
      const numero = i.nr_sigcon || i.nr_convenio;
      if (!numero) return;
      setVol({ municipioId: i.municipio_id ?? null, detalhe: null, carregando: true });
      try {
        const r = await api.get<DetalheVoluntaria>(`/transferegov/voluntarias/${encodeURIComponent(numero)}`,
          { params: { municipio_id: i.municipio_id } });
        setVol({ municipioId: i.municipio_id ?? null, detalhe: r.data, carregando: false });
      } catch {
        setVol({ municipioId: i.municipio_id ?? null, detalhe: null, carregando: false });
      }
      return;
    }
    if (i.id) setConvAberto({ id: i.id, esfera: i.esfera || "estadual" });
  }, []);

  const visiveis = useMemo(() => {
    const base = munSel.length
      ? itens.filter((i) => munSel.includes(nomeDo(i)))
      : itens;
    return [...base].sort((a, b) => {
      const x = a.dias_restantes ?? 9999, y = b.dias_restantes ?? 9999;
      return asc ? x - y : y - x;
    });
  }, [itens, munSel, asc, nomeDo]);

  const porMunicipio = useMemo(() => {
    const m = new Map<string, { nome: string; qtd: number; menor: number }>();
    visiveis.forEach((i) => {
      const nome = nomeDo(i);
      const at = m.get(nome) || { nome, qtd: 0, menor: 9999 };
      at.qtd += 1;
      at.menor = Math.min(at.menor, i.dias_restantes ?? 9999);
      m.set(nome, at);
    });
    return [...m.values()].sort((a, b) => b.qtd - a.qtd);
  }, [visiveis, nomeDo]);

  const opcoesMun = useMemo(
    () => Array.from(new Set(itens.map(nomeDo).filter((n) => n && n !== "—"))).sort(),
    [itens, nomeDo],
  );
  const maxQtd = Math.max(1, ...porMunicipio.map((p) => p.qtd));

  /* EXPORTAÇÃO — botão que abre um modal: ele diz, ANTES de baixar, qual é o
     recorte que vai para o arquivo. */
  const [exportAberto, setExportAberto] = useState(false);
  const [baixando, setBaixando] = useState<FormatoVigencias | null>(null);

  async function exportar(formato: FormatoVigencias) {
    setBaixando(formato);
    try {
      /* ⚠️ MANDA `munSel`, NÃO os municípios visíveis. O backend entende lista
         vazia como "todos os do meu alcance" e refaz o mesmo recorte da tela. */
      await baixarVigencias({ dias: DIAS, municipios: munSel, ordem: asc ? "asc" : "desc", formato });
      setExportAberto(false);
    } finally {
      setBaixando(null);
    }
  }

  return (
    <>
      <Bloco className="p-3">
        <BlocoHead icon={CalendarClock} titulo="Vigências a vencer"
                   sub={`instrumentos da carteira com vigência encerrando em até ${DIAS} dias · clique para abrir`} />

        <div className="flex flex-wrap items-end gap-3 px-1 pb-3">
          <div className="rounded-lg px-4 py-2"
               style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}>
            <div className="text-[10px] uppercase tracking-wide" style={{ color: "var(--bi-muted)" }}>
              {munSel.length ? `${munSel.length} município(s)` : "Todos os municípios"}
            </div>
            <div className="text-2xl font-bold" style={{ color: "var(--bi-text)" }}>
              {/* "—" também no bloqueio: um "0" ao lado do aviso de permissão
                  seria a mesma mentira, só que em número. */}
              {carregando || semAcesso ? "—" : visiveis.length}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>Municípios</label>
            <MultiSelect
              opcoes={opcoesMun} valor={munSel} onChange={setMunSel}
              placeholder="Todos" rotuloTodos="Todos" ariaLabel="Municípios" className="w-56"
            />
          </div>
          <div className="ml-auto flex items-center gap-1">
            <button onClick={() => setVisao("bolhas")}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium bi-hover"
                    style={{ background: visao === "bolhas" ? "var(--bi-surface-2)" : "transparent",
                             border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}>
              <Circle className="size-3" /> Bolhas
            </button>
            <button onClick={() => setVisao("lista")}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium bi-hover"
                    style={{ background: visao === "lista" ? "var(--bi-surface-2)" : "transparent",
                             border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}>
              <List className="size-3" /> Lista
            </button>
            {visao === "lista" && (
              <button onClick={() => setAsc((v) => !v)}
                      title={asc ? "Menor prazo primeiro" : "Maior prazo primeiro"}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] bi-hover"
                      style={{ border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}>
                <ArrowUpDown className="size-3" /> {asc ? "menor→maior" : "maior→menor"}
              </button>
            )}
            {/* Desabilitado (e não escondido) quando não há o que exportar. */}
            <button
              onClick={() => setExportAberto(true)}
              disabled={carregando || semAcesso || visiveis.length === 0}
              title={
                semAcesso ? "Você não tem acesso às vigências"
                  : carregando ? "Carregando…"
                  : visiveis.length === 0 ? "Nada a exportar neste recorte"
                  : "Exportar em PDF ou Excel"
              }
              className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium bi-hover disabled:cursor-not-allowed disabled:opacity-40"
              style={{ border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}>
              <Download className="size-3" /> Exportar
            </button>
          </div>
        </div>

        <div className="px-1">
          {carregando ? (
            <div className="space-y-1.5">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg" style={{ background: "var(--bi-surface-2)" }} />
              ))}
            </div>
          ) : semAcesso ? (
            <div className="mx-auto max-w-md py-8 text-center">
              <Lock className="mx-auto size-5" style={{ color: "var(--bi-faint)" }} />
              <p className="mt-2 text-sm font-semibold" style={{ color: "var(--bi-text)" }}>
                Você não tem acesso às vigências.
              </p>
              <p className="mt-1 text-xs leading-relaxed" style={{ color: "var(--bi-muted)" }}>
                Isto <b>não</b> quer dizer que não há nada vencendo — quer dizer que
                este conteúdo não está liberado para a sua conta. Peça a quem
                administra o sistema a permissão <b>«Vigências a vencer»</b>, em
                Configurações › Usuários › Permissões.
              </p>
            </div>
          ) : visiveis.length === 0 ? (
            <p className="py-8 text-center text-sm" style={{ color: "var(--bi-muted)" }}>
              Nenhum instrumento vencendo em {DIAS} dias.
            </p>
          ) : visao === "bolhas" ? (
            <>
              <div className="flex flex-wrap items-center gap-3">
                {porMunicipio.map((p) => {
                  // área ∝ quantidade: o olho compara tamanho, não número
                  const lado = 46 + Math.round(54 * Math.sqrt(p.qtd / maxQtd));
                  const tom = tomDias(p.menor);
                  const ativo = munAberto === p.nome;
                  return (
                    <button key={p.nome} onClick={() => setMunAberto(ativo ? null : p.nome)}
                            className="flex flex-col items-center gap-1 bi-hover rounded-lg p-1"
                            title={`${p.nome}: ${p.qtd} vencendo — o mais próximo em ${p.menor} dia(s). Clique para ver.`}>
                      <div className="flex items-center justify-center rounded-full font-bold"
                           style={{ width: lado, height: lado, background: tom.bg, color: tom.fg,
                                    border: ativo ? "2px solid var(--bi-text)" : "1px solid var(--bi-line)" }}>
                        {p.qtd}
                      </div>
                      <span className="max-w-[7rem] truncate text-[11px]" style={{ color: "var(--bi-muted)" }}>
                        {p.nome}
                      </span>
                    </button>
                  );
                })}
              </div>
              {/* Os MESMOS itens da lista, do município escolhido. Sem clicar,
                  mostra o município com mais instrumentos — a bolha sozinha
                  dizia "quantos" e nunca "quais". */}
              {(() => {
                const alvo = munAberto || (porMunicipio[0]?.nome ?? null);
                if (!alvo) return null;
                const doMun = visiveis.filter((i) => nomeDo(i) === alvo);
                return (
                  <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                    <div className="mb-2 text-xs font-semibold" style={{ color: "var(--bi-text)" }}>
                      {alvo} — {doMun.length} vencendo
                    </div>
                    <div className="space-y-1.5">
                      {doMun.map((i) => (
                        <LinhaAlerta key={`${i.esfera || ""}-${i.id}-${i.nr_convenio || i.nr_sigcon}`}
                                     i={i} nome={alvo} onAbrir={abrir} />
                      ))}
                    </div>
                  </div>
                );
              })()}
            </>
          ) : (
            <div className="space-y-1.5">
              {visiveis.map((i) => (
                <LinhaAlerta key={`${i.esfera || ""}-${i.id}-${i.nr_convenio || i.nr_sigcon}`}
                             i={i} nome={nomeDo(i)} onAbrir={abrir} />
              ))}
            </div>
          )}
        </div>
      </Bloco>

      {convAberto && <ConvenioDetailModal conv={convAberto} onClose={() => setConvAberto(null)} />}
      {vol && (
        <DetalheVoluntariaModal detalhe={vol.detalhe} carregando={vol.carregando}
                                municipioId={vol.municipioId} onFechar={() => setVol(null)} />
      )}

      <Modal aberto={exportAberto} onFechar={() => setExportAberto(false)}
             maxW="max-w-md" podeFechar={() => baixando === null} rotulo="Exportar vigências">
        <ModalHead
          titulo="Exportar vigências"
          sub="O arquivo sai com o mesmo recorte que está na tela."
          onFechar={() => setExportAberto(false)}
        />
        <ModalCorpo>
          {/* O QUE VAI NO ARQUIVO, escrito antes de baixar: exportação que não
              diz o próprio recorte vira PDF errado circulando por e-mail. */}
          <div className="rounded-lg p-3 text-xs leading-relaxed"
               style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}>
            <div>
              <b style={{ color: "var(--bi-text)" }}>{visiveis.length}</b>{" "}
              instrumento(s) em{" "}
              <b style={{ color: "var(--bi-text)" }}>{porMunicipio.length}</b>{" "}
              município(s), vencendo em até {DIAS} dias.
            </div>
            <div className="mt-1">
              Recorte: {munSel.length
                ? `${munSel.length} município(s) selecionado(s)`
                : "todos os municípios da carteira"}
              {" · "}ordem: {asc ? "menor prazo primeiro" : "maior prazo primeiro"}
            </div>
            <div className="mt-1">
              Os dois formatos trazem a lista completa e o totalizador por município.
            </div>
          </div>

          <div className="mt-3 grid grid-cols-2 gap-2">
            <button onClick={() => exportar("pdf")} disabled={baixando !== null}
                    className="flex flex-col items-center gap-1 rounded-lg p-3 text-xs font-medium bi-hover disabled:cursor-not-allowed disabled:opacity-50"
                    style={{ border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}>
              {baixando === "pdf" ? <Loader2 className="size-5 animate-spin" /> : <FileText className="size-5" />}
              PDF
              <span className="text-[10px] font-normal" style={{ color: "var(--bi-muted)" }}>
                para ler e circular
              </span>
            </button>
            <button onClick={() => exportar("xlsx")} disabled={baixando !== null}
                    className="flex flex-col items-center gap-1 rounded-lg p-3 text-xs font-medium bi-hover disabled:cursor-not-allowed disabled:opacity-50"
                    style={{ border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}>
              {baixando === "xlsx" ? <Loader2 className="size-5 animate-spin" /> : <Sheet className="size-5" />}
              Excel
              <span className="text-[10px] font-normal" style={{ color: "var(--bi-muted)" }}>
                valores somáveis
              </span>
            </button>
          </div>
          <p className="mt-3 text-[11px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
            O PDF abre em outra aba; o Excel baixa. Instrumento sem valor coletado
            na fonte fica <b>fora da soma</b> e é contado à parte — o total é do
            que tem valor conhecido.
          </p>
        </ModalCorpo>
      </Modal>
    </>
  );
}
