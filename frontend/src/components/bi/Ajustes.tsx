"use client";
// Ajustes do Painel de Indicadores. Fica FORA do fichário de abas de propósito:
// as abas são assunto de dado e rodam no slideshow da TV — configuração não
// deve aparecer numa TV de gabinete. Aqui vive o que existia em /bi/config:
// preferências de aviso e o link de quiosque (liga a TV sem login).
import { useEffect, useMemo, useState } from "react";
import { Bell, Check, Copy, KeyRound, Settings2, Share2, Smartphone, Trash2, Tv, X } from "lucide-react";
import api from "@/lib/api";
import type { User } from "@/types";
import {
  Prefs, TelaLink, TipoLink, criarTelaLink, getPrefs, listarTelaLinks, putPrefs,
  putTelaFiltros, revogarTelaLink,
} from "@/lib/bi";
import { allowedTelasOf } from "@/lib/telas";
import { CONSOLIDADO, useBiScope } from "@/contexts/BiScopeContext";

const PREF_LABELS: { key: keyof Prefs; label: string }[] = [
  { key: "vigencia_60d", label: "Vigências vencendo em 60 dias" },
  { key: "prazo_prestacao", label: "Prestação de contas vencida" },
  { key: "cauc_vencendo", label: "Pendências de regularidade (CAUC)" },
  { key: "obra_prazo", label: "Prazos e paralisações de obras da saúde" },
  { key: "nova_emenda", label: "Nova emenda destinada" },
  { key: "mudanca_status", label: "Mudança de status de convênio" },
];

/** Os tres caminhos do gerador. "ambos" NAO e um tipo de link: e um atalho que
 *  gera UM DE CADA. Os dois se comportam de forma diferente — a TV segue o
 *  filtro do dono, o app tem filtro proprio —, entao um link unico servindo aos
 *  dois nao existe, e quem entrega precisa saber qual esta entregando a quem. */
const TIPOS_DE_LINK = [
  { valor: "tela" as const, Icone: Tv, titulo: "Modo Tela (TV)",
    texto: "Acompanha o SEU filtro: mudou o período aqui, muda lá em até 10 segundos." },
  { valor: "mobile" as const, Icone: Smartphone, titulo: "App Mobile (PWA)",
    texto: "Instala como atalho no celular e tem filtro próprio, sem afetar a TV." },
  { valor: "ambos" as const, Icone: Share2, titulo: "Os dois",
    texto: "Gera um link de cada, separados — um serve a TV e o outro serve o celular." },
];

export function BotaoAjustes() {
  const [aberto, setAberto] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setAberto(true)}
        title="Ajustes do painel"
        aria-label="Ajustes do painel"
        className="grid size-9 place-items-center rounded-full"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
      >
        <Settings2 className="size-4" />
      </button>
      {aberto && <ModalAjustes onFechar={() => setAberto(false)} />}
    </>
  );
}

function ModalAjustes({ onFechar }: { onFechar: () => void }) {
  const { scope, anos } = useBiScope();
  const [user, setUser] = useState<User | null>(null);
  const [prefs, setPrefs] = useState<Prefs | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [links, setLinks] = useState<TelaLink[]>([]);
  const [emitindo, setEmitindo] = useState<TipoLink | null>(null);
  const [copiado, setCopiado] = useState<string | null>(null);
  /* PARA QUEM o link vai, e por quanto tempo. Ficam FORA dos dois botões porque
     valem para os dois: o gestor decide o destinatário e o prazo uma vez, e só
     então escolhe se aquilo é uma TV ou um celular. */
  const [destinatario, setDestinatario] = useState("");
  const [expira, setExpira] = useState<"dias" | "data" | "nunca">("dias");
  const [dias, setDias] = useState("30");
  const [dataExpira, setDataExpira] = useState("");
  const [erroLink, setErroLink] = useState<string | null>(null);
  /* O SEGUNDO modal — o de criacao. O primeiro e a lista. */
  const [formAberto, setFormAberto] = useState(false);
  /* "ambos" NAO e um tipo de link: e um atalho que gera UM DE CADA. Os dois se
     comportam de forma diferente (a TV segue o filtro do dono, o app tem filtro
     proprio), entao um link unico servindo aos dois nao existe — e quem
     entrega precisa saber qual esta entregando a quem. */
  const [tipo, setTipo] = useState<"tela" | "mobile" | "ambos">("tela");

  const podeGerarLink = useMemo(() => {
    const t = allowedTelasOf(user);
    return !t || t.has("bi_link"); // null = admin
  }, [user]);

  useEffect(() => {
    api.get<User>("/auth/me").then((r) => setUser(r.data)).catch(() => {});
    getPrefs().then(setPrefs).catch(() => setPrefs(null));
    listarTelaLinks().then(setLinks).catch(() => setLinks([]));
  }, []);

  /* ⚠️ O ESC FECHA UMA CAIXA POR VEZ — a de cima.
     O formulário mora DENTRO deste modal, então um único ouvinte de tecla via
     `window` fechava os dois de uma vez: quem apertasse Esc para desistir de
     gerar o link perdia também a lista, e voltava para o painel sem entender o
     que aconteceu. Com o formulário aberto, Esc só o fecha e devolve a lista. */
  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (formAberto) setFormAberto(false);
      else onFechar();
    };
    window.addEventListener("keydown", onEsc);
    return () => window.removeEventListener("keydown", onEsc);
  }, [onFechar, formAberto]);

  const alternar = async (key: keyof Prefs) => {
    if (!prefs) return;
    const proximo = { ...prefs, [key]: !prefs[key] };
    setPrefs(proximo);
    setSalvando(true);
    try {
      await putPrefs(proximo);
    } catch {
      setPrefs(prefs); // desfaz se o backend recusou
    } finally {
      setSalvando(false);
    }
  };

  const gerarLink = async (escolha: "tela" | "mobile" | "ambos") => {
    const kinds: TipoLink[] = escolha === "ambos" ? ["tela", "mobile"] : [escolha];
    setEmitindo(escolha === "ambos" ? "tela" : escolha);
    setErroLink(null);
    try {
      // Publica o filtro ANTES de emitir. Sem isto o link nasce mostrando
      // "consolidado / todos os anos" e só passaria a refletir o período depois
      // que alguém mexesse no filtro de novo — que é exatamente o defeito que
      // esta tela existe para não ter.
      await putTelaFiltros({ scope: scope || CONSOLIDADO, anos, aba: null }).catch(() => {});
      const opcoes = {
        nome: destinatario.trim() || null,
        expira,
        dias: Number(dias) || 30,
        data_expiracao: dataExpira || null,
      };
      // EM SÉRIE, e não em paralelo: cada emissão cria um usuário de quiosque e
      // grava na trilha. Disparar as duas juntas é pedir para colidirem no mesmo
      // instante por um ganho de meio segundo.
      const novos: TelaLink[] = [];
      for (const kind of kinds) {
        novos.push(await criarTelaLink(kind, opcoes));
      }
      setLinks((L) => [...novos.reverse(), ...L]);
      setDestinatario("");
      setFormAberto(false);   // volta para a LISTA, com os novos já lá
    } catch (e) {
      /* A falha PRECISA aparecer: data no passado e data vazia voltam 400, e um
         botão que volta ao normal em silêncio faz o gestor achar que gerou. */
      setErroLink(
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Não foi possível gerar o link."
      );
    } finally {
      setEmitindo(null);
    }
  };

  const revogar = async (slug: string) => {
    try {
      await revogarTelaLink(slug);
      setLinks((L) => L.filter((l) => l.slug !== slug));
    } catch { /* mantem na lista se o backend recusou */ }
  };

  const urlDe = (l: TelaLink) =>
    `${typeof window !== "undefined" ? window.location.origin : ""}${l.caminho}`;

  /** "Expira em 12/08/2026 (9 dias)" / "Sem prazo" / "Expirado".
   *
   *  Os dias que FALTAM importam mais que a data: o gestor quer saber se
   *  precisa agir esta semana. E a lista não esconde link expirado — ele
   *  continua ocupando lugar até alguém revogar, e sumir daria a impressão
   *  errada de que já foi resolvido. */
  const prazoDe = (l: TelaLink) => {
    if (!l.expira_em) return "Sem prazo — vale até você revogar";
    const fim = new Date(l.expira_em);
    if (Number.isNaN(fim.getTime())) return "Prazo não informado";
    const dias = Math.ceil((fim.getTime() - Date.now()) / 86_400_000);
    const data = fim.toLocaleDateString("pt-BR");
    if (dias < 0) return `Expirou em ${data}`;
    if (dias === 0) return `Expira hoje (${data})`;
    return `Expira em ${data} · ${dias} dia${dias > 1 ? "s" : ""}`;
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="Ajustes do painel"
      onClick={(e) => e.target === e.currentTarget && onFechar()}
    >
      <div
        className="bi-scroll max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-3xl p-5"
        style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
      >
        <div className="mb-4 flex items-center gap-2">
          <Settings2 className="size-4" style={{ color: "var(--bi-muted)" }} />
          <h2 className="bi-title text-[16px]">Ajustes do painel</h2>
          <button
            type="button"
            onClick={onFechar}
            className="ml-auto grid size-7 place-items-center rounded-lg"
            style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        <section className="mb-5">
          <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
            <Bell className="size-4" style={{ color: "var(--bi-muted)" }} />
            Avisos que quero receber
          </div>
          {prefs ? (
            <ul className="flex flex-col gap-1">
              {PREF_LABELS.map((p) => (
                <li key={p.key}>
                  <label className="flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2" style={{ background: "var(--bi-surface-2)" }}>
                    <input
                      type="checkbox"
                      checked={!!prefs[p.key]}
                      onChange={() => alternar(p.key)}
                      disabled={salvando}
                      className="size-4 accent-[var(--bi-accent)]"
                    />
                    <span className="text-[12px]">{p.label}</span>
                  </label>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px]" style={{ color: "var(--bi-faint)" }}>
              Não foi possível carregar as preferências.
            </p>
          )}
        </section>

        {podeGerarLink && (
          <section>
            <div className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
              <Share2 className="size-4" style={{ color: "var(--bi-muted)" }} />
              Links externos
            </div>
            <p className="mb-3 text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Abrem sem login. Trate como senha — quem tiver o link vê os indicadores.
              Cada link gerado aparece na lista abaixo e pode ser revogado a qualquer momento.
            </p>

            {/* O BOTAO QUE ABRE O FORMULARIO.
                Este modal e a LISTA dos links ja gerados; a criacao mora num
                segundo modal. Antes, formulario e lista dividiam a mesma tela e
                os dois botoes de gerar ficavam no meio — quem entrava aqui so
                para conferir ou revogar um link tinha de passar por um
                formulario vazio antes de chegar na lista. */}
            <button
              type="button"
              onClick={() => { setErroLink(null); setFormAberto(true); }}
              className="mb-3 inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[12px] font-semibold"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
            >
              <KeyRound className="size-3.5" /> Gerar link externo
            </button>

            {links.length === 0 ? (
              <p className="rounded-xl px-2.5 py-3 text-center text-[11px]"
                 style={{ background: "var(--bi-surface-2)", color: "var(--bi-faint)" }}>
                Nenhum link externo gerado.
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {links.map((l) => (
                  <li
                    key={l.slug}
                    className="flex items-center gap-2 rounded-xl px-2.5 py-2"
                    style={{ background: "var(--bi-surface-2)", border: "1px solid var(--bi-line)" }}
                  >
                    <span
                      className="shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase"
                      style={{
                        background: "var(--bi-accent-soft)",
                        color: "var(--bi-accent)",
                      }}
                      title={l.kind === "mobile"
                        ? "App Mobile — filtro próprio no aparelho"
                        : "Modo Tela — segue o seu filtro"}
                    >
                      {l.kind === "mobile" ? "app" : "tv"}
                    </span>
                    {/* O NOME vem primeiro e o endereço embaixo: na hora de
                        revogar, a pergunta é "de quem é este?", não "qual é a
                        URL?". Link antigo (gerado antes deste campo existir)
                        fica sem nome — dizer isso é melhor que inventar um. */}
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[12px] font-semibold">
                        {l.nome || <span style={{ color: "var(--bi-faint)" }}>Sem destinatário</span>}
                      </span>
                      <code className="block truncate text-[10px]" style={{ color: "var(--bi-faint)" }}>
                        {urlDe(l)}
                      </code>
                      <span className="block text-[10px]" style={{ color: "var(--bi-faint)" }}>
                        {prazoDe(l)}
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        void navigator.clipboard.writeText(urlDe(l));
                        setCopiado(l.slug);
                        setTimeout(() => setCopiado(null), 1800);
                      }}
                      className="grid size-7 shrink-0 place-items-center rounded-lg"
                      style={{ background: "var(--bi-surface)", color: "var(--bi-muted)" }}
                      aria-label="Copiar link"
                    >
                      {copiado === l.slug ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => void revogar(l.slug)}
                      className="grid size-7 shrink-0 place-items-center rounded-lg"
                      style={{ background: "var(--bi-surface)", color: "var(--bi-muted)" }}
                      aria-label="Revogar link"
                      title="Revogar link"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>

      {/* SEGUNDO MODAL — a criacao. O primeiro e a LISTA.
          `stopPropagation` no conteudo: sem ele, clicar dentro do formulario
          fecharia o modal de tras, que fecha no clique do fundo. */}
      {formAberto && (
        <div
          className="fixed inset-0 z-[60] grid place-items-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Gerar link externo"
          onClick={(e) => e.target === e.currentTarget && setFormAberto(false)}
        >
          <div
            className="bi-scroll max-h-[85vh] w-full max-w-md overflow-y-auto rounded-3xl p-5"
            style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-3 flex items-center gap-2">
              <KeyRound className="size-4" style={{ color: "var(--bi-muted)" }} />
              <h3 className="bi-title text-[15px]">Gerar link externo</h3>
              <button
                type="button"
                onClick={() => setFormAberto(false)}
                className="ml-auto grid size-7 place-items-center rounded-lg"
                style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
                aria-label="Fechar"
              >
                <X className="size-4" />
              </button>
            </div>

            <div className="rounded-2xl p-2.5" style={{ background: "var(--bi-surface-2)" }}>
              <label className="mb-1 block text-[11px] font-semibold" htmlFor="link-destinatario">
                Para quem é este link
              </label>
              <input
                id="link-destinatario"
                value={destinatario}
                onChange={(e) => setDestinatario(e.target.value)}
                placeholder="Ex.: Secretário de Saúde — TV do gabinete"
                maxLength={120}
                className="mb-2.5 w-full rounded-xl px-2.5 py-1.5 text-[12px] outline-none"
                style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
              />

              <span className="mb-1 block text-[11px] font-semibold">Validade</span>
              <div className="mb-2.5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px]">
                {([["dias", "Por"], ["data", "Até"], ["nunca", "Sem prazo"]] as const).map(
                  ([valor, rotulo]) => (
                    <label key={valor} className="flex cursor-pointer items-center gap-1.5">
                      <input
                        type="radio"
                        name="link-expira"
                        checked={expira === valor}
                        onChange={() => setExpira(valor)}
                        className="size-3.5 accent-[var(--bi-accent)]"
                      />
                      {rotulo}
                      {valor === "dias" && expira === "dias" && (
                        <>
                          <input
                            type="number"
                            min={1}
                            max={3650}
                            value={dias}
                            onChange={(e) => setDias(e.target.value)}
                            className="w-16 rounded-lg px-1.5 py-0.5 text-[12px] outline-none"
                            style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
                            aria-label="Quantidade de dias"
                          />
                          dias
                        </>
                      )}
                      {valor === "data" && expira === "data" && (
                        <input
                          type="date"
                          value={dataExpira}
                          onChange={(e) => setDataExpira(e.target.value)}
                          className="rounded-lg px-1.5 py-0.5 text-[12px] outline-none"
                          style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
                          aria-label="Data de expiração"
                        />
                      )}
                    </label>
                  )
                )}
              </div>

              {/* O TIPO. Os dois se comportam de forma diferente, e a descricao
                  fica JUNTO da opcao — quem escolhe precisa ler ali, e nao numa
                  legenda acima que ja rolou para fora da tela. */}
              <span className="mb-1 block text-[11px] font-semibold">Tipo de link</span>
              <div className="flex flex-col gap-1.5">
                {TIPOS_DE_LINK.map(({ valor, Icone, titulo, texto }) => (
                  <label
                    key={valor}
                    className="flex cursor-pointer items-start gap-2 rounded-xl p-2"
                    style={{
                      background: "var(--bi-surface)",
                      border: tipo === valor
                        ? "1px solid var(--bi-accent-ink)"
                        : "1px solid var(--bi-line)",
                    }}
                  >
                    <input
                      type="radio"
                      name="link-tipo"
                      checked={tipo === valor}
                      onChange={() => setTipo(valor)}
                      className="mt-0.5 size-3.5 accent-[var(--bi-accent)]"
                    />
                    <span className="min-w-0">
                      <span className="flex items-center gap-1.5 text-[12px] font-semibold">
                        <Icone className="size-3.5" style={{ color: "var(--bi-muted)" }} />
                        {titulo}
                      </span>
                      <span className="block text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                        {texto}
                      </span>
                    </span>
                  </label>
                ))}
              </div>

              {expira === "nunca" && (
                <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                  O sistema nao vai encerrar sozinho. Continua valendo ate voce revogar
                  (limite tecnico de 10 anos).
                </p>
              )}
              {erroLink && (
                <p className="mt-2 text-[11px]" style={{ color: "var(--bi-crit-ink)" }}>{erroLink}</p>
              )}
            </div>

            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setFormAberto(false)}
                className="rounded-full px-3.5 py-1.5 text-[12px] font-semibold"
                style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => gerarLink(tipo)}
                disabled={!!emitindo}
                className="inline-flex items-center gap-2 rounded-full px-3.5 py-1.5 text-[12px] font-semibold disabled:opacity-60"
                style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
              >
                <KeyRound className="size-3.5" />
                {emitindo ? "Gerando…" : tipo === "ambos" ? "Gerar os dois" : "Gerar link"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
