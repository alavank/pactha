"use client";

/* VIGÊNCIAS A VENCER (<120 dias) — o que está prestes a expirar.
 *
 *  Substitui o selo que só REPETIA o município já escolhido na barra lateral
 *  (informação que a tela toda já dava) por algo acionável: o que vence primeiro.
 *
 *  DUAS VISÕES do mesmo recorte, porque as perguntas são diferentes:
 *   - BOLHAS por município: "onde está concentrado?" — o tamanho é a quantidade,
 *     então um município com 9 vencendo salta antes de qualquer leitura de lista.
 *   - LISTA por dias: "o que vence primeiro?" — ordenável nos dois sentidos.
 *  O KPI no topo acompanha o filtro de municípios (multisseleção), então o número
 *  nunca discorda do que está logo abaixo — o erro clássico de dashboard.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { X, CalendarClock, Circle, List, ArrowUpDown, Lock } from "lucide-react";
import api from "@/lib/api";
import { MultiSelect } from "@/components/ui/multi-select";
import type { Municipio } from "@/types";

interface Alerta {
  id: number;
  esfera?: string | null;
  municipio_id?: number | null;
  nr_convenio?: string | null;
  nr_sigcon?: string | null;
  objeto?: string | null;
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
function LinhaAlerta({ i, nome }: { i: Alerta; nome: string }) {
  const tom = tomDias(i.dias_restantes);
  return (
    <div className="flex items-center gap-3 rounded-lg px-3 py-2" style={{ background: "var(--bi-surface-2)" }}>
      <span className="shrink-0 rounded-md px-2 py-1 text-[11px] font-bold" style={{ background: tom.bg, color: tom.fg }}>
        {i.dias_restantes ?? "—"}d
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs font-medium" style={{ color: "var(--bi-text)" }}>
          {i.objeto || i.nr_convenio || i.nr_sigcon || "—"}
        </div>
        <div className="truncate text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {nome}
          {i.nr_convenio || i.nr_sigcon ? ` · ${i.nr_convenio || i.nr_sigcon}` : ""}
          {i.dt_fim_vigencia ? ` · vence em ${new Date(i.dt_fim_vigencia).toLocaleDateString("pt-BR")}` : ""}
        </div>
      </div>
    </div>
  );
}

export default function VigenciasModal({
  municipios, onClose,
}: { municipios: Municipio[]; onClose: () => void }) {
  const [itens, setItens] = useState<Alerta[]>([]);
  const [carregando, setCarregando] = useState(true);
  /* ⭐ SEM PERMISSAO ≠ SEM NADA VENCENDO, e confundir os dois foi o defeito que
     motivou este bloco (pedido do dono, 08/2026): quem não tinha acesso levava
     403, o `catch` zerava a lista em silêncio e o modal anunciava «Nenhum
     instrumento vencendo em 120 dias». A pessoa fechava tranquila achando que
     estava tudo em dia — quando na verdade não estava vendo nada.

     Hoje quem libera é a caixinha «Vigências a vencer» do modal de Permissões
     (ou o módulo de Convênios Estaduais, para quem já o tinha). */
  const [semAcesso, setSemAcesso] = useState(false);
  const [visao, setVisao] = useState<"bolhas" | "lista">("bolhas");
  const [asc, setAsc] = useState(true);
  const [munSel, setMunSel] = useState<string[]>([]);
  // Bolha CLICADA: a visao de bolhas mostra os mesmos itens da lista,
  // so que agrupados — clicar abre os convenios daquele municipio.
  const [munAberto, setMunAberto] = useState<string | null>(null);

  const nomePorId = useMemo(() => {
    const m: Record<string, string> = {};
    municipios.forEach((x) => { m[String(x.id)] = x.nome; });
    return m;
  }, [municipios]);

  /** Nome do município do alerta. A API passou a mandar `municipio_nome` junto —
   *  antes a tela cruzava por id e, quando a API nem devolvia o id, a bolha saía
   *  como "—" e o filtro nascia vazio. O cruzamento fica como queda. */
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: "rgba(15,23,42,.55)" }} onClick={onClose}>
      <div className="bi-card w-full max-w-4xl max-h-[86vh] overflow-hidden flex flex-col"
           onClick={(e) => e.stopPropagation()}>
        {/* cabeçalho + KPI (acompanha o filtro — nunca discorda da lista abaixo) */}
        <div className="flex items-start justify-between gap-3 border-b p-4"
             style={{ borderColor: "var(--bi-line)" }}>
          <div>
            <h2 className="flex items-center gap-2 text-base font-bold" style={{ color: "var(--bi-text)" }}>
              <CalendarClock className="size-4" /> Vigências a vencer
            </h2>
            <p className="mt-0.5 text-xs" style={{ color: "var(--bi-muted)" }}>
              Instrumentos com vigência encerrando em até {DIAS} dias.
            </p>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 bi-hover" aria-label="Fechar">
            <X className="size-4" />
          </button>
        </div>

        <div className="flex flex-wrap items-end gap-3 p-4 pb-2">
          <div className="rounded-lg px-4 py-2"
               style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}>
            <div className="text-[10px] uppercase tracking-wide" style={{ color: "var(--bi-muted)" }}>
              {munSel.length ? `${munSel.length} município(s)` : "Todos os municípios"}
            </div>
            <div className="text-2xl font-bold" style={{ color: "var(--bi-text)" }}>
              {/* "—" tambem no bloqueio: um "0" garboso ao lado do aviso de
                  permissao seria a mesma mentira, so que em numero. */}
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
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4 pt-2">
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
                  mostra o município com o prazo mais curto — a bolha sozinha
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
                        <LinhaAlerta key={`${i.esfera || ""}-${i.id}-${i.nr_convenio || i.nr_sigcon}`} i={i} nome={alvo} />
                      ))}
                    </div>
                  </div>
                );
              })()}
            </>
          ) : (
            <div className="space-y-1.5">
              {visiveis.map((i) => <LinhaAlerta key={`${i.esfera || ""}-${i.id}-${i.nr_convenio || i.nr_sigcon}`} i={i} nome={nomeDo(i)} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
