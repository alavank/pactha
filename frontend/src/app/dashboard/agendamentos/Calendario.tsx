"use client";

/* O CALENDÁRIO — mensal, semanal e diária.
 *
 * ⭐ ELE OCUPA A TELA. Não é estética: um calendário de células pequenas obriga
 * a abrir o dia para saber o que há nele, e aí ele deixou de responder a
 * pergunta que traz a pessoa aqui ("o que tem esta semana?"). A altura vem do
 * pai (`h-full`) e as semanas dividem o que sobra em partes iguais.
 *
 * ⚠️ CLIQUE SIMPLES E DUPLO NO MESMO ALVO. Um clique abre o detalhe, dois abrem
 * a edição — e o navegador dispara DOIS `click` antes do `dblclick`. Por isso o
 * clique simples espera `ESPERA_DUPLO` antes de agir: sem essa espera, todo
 * duplo clique abriria o detalhe e a edição, um por cima do outro. O mesmo vale
 * para a célula do dia, cujo duplo clique cria — o `stopPropagation` do
 * compromisso impede que abrir um vire criar outro.
 *
 * ⚠️ A RÉGUA VAI DE 00 A 23. Recortar o "horário comercial" esconderia o
 * compromisso das 19h — e uma agenda que esconde compromisso não serve.
 */

import React, {
  useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState,
} from "react";
import { CalendarPlus, ChevronLeft, ChevronRight, PanelRightOpen } from "lucide-react";

import { BOTAO_CTA, BOTAO_SEC, ESTILO_CTA, ESTILO_SEC } from "@/components/ui/superficies";
import {
  Compromisso, MESES, ModoCalendario, SEMANA, diaBR, diaDaSemana, duracaoDe,
  diasEntre, estiloDaCor, hojeISO, horarioDe, iso, limitesDoMes, minutos, partes,
  porExtenso, repartirEmColunas, semanaDe, somaDias,
} from "./tipos";

/** Janela em que um segundo clique ainda conta como duplo. 250ms é o padrão de
 *  fato dos sistemas operacionais; abaixo disso a edição vira sorte. */
const ESPERA_DUPLO = 250;
/** Altura de uma hora na régua, em pixels. 48px comporta o chip compacto de 30
 *  minutos (24px) com o texto legível. */
const ALT_HORA = 48;
/** Atraso do balão de passagem, pedido no documento. Sem atraso, arrastar o
 *  mouse pela grade acende e apaga uma dúzia de balões. */
const ATRASO_BALAO = 200;

interface Props {
  itens: Compromisso[];
  modo: ModoCalendario;
  onModo: (m: ModoCalendario) => void;
  /** O dia de referência (`YYYY-MM-DD`). No mensal, manda o mês. */
  foco: string;
  onFoco: (dia: string) => void;
  comMunicipio: boolean;
  onCriar: (dia: string, hora?: string) => void;
  onAbrir: (c: Compromisso) => void;
  onEditar: (c: Compromisso) => void;
  /** Só aparece quando o card lateral está oculto. */
  onMostrarCard?: () => void;
}

export default function Calendario(p: Props) {
  const hoje = hojeISO();
  const porDia = useMemo(() => {
    const m: Record<string, Compromisso[]> = {};
    p.itens.forEach((c) => {
      const k = String(c.data || "").slice(0, 10);
      if (k) (m[k] ||= []).push(c);
    });
    Object.values(m).forEach((l) => l.sort(
      (a, b) => minutos(a.hora_inicio) - minutos(b.hora_inicio) || a.id - b.id));
    return m;
  }, [p.itens]);

  const andar = (passo: number) => {
    if (p.modo === "mensal") {
      const [a, m0] = partes(p.foco);
      const d = new Date(a, m0 + passo, 1);
      p.onFoco(iso(d.getFullYear(), d.getMonth(), 1));
    } else {
      p.onFoco(somaDias(p.foco, passo * (p.modo === "semanal" ? 7 : 1)));
    }
  };

  const titulo = (() => {
    const [a, m0] = partes(p.foco);
    if (p.modo === "mensal") return `${MESES[m0]} de ${a}`;
    if (p.modo === "diaria") return porExtenso(p.foco);
    /* A semana escreve só o que MUDA de uma ponta à outra: "7 – 13 de setembro
       de 2026" quando o mês é o mesmo, e as duas datas inteiras quando ela cai
       na virada do ano. Repetir mês e ano dos dois lados enche o cabeçalho com
       a informação que já estava lá. */
    const dias = semanaDe(p.foco);
    const [a1, m1, d1] = partes(dias[0]);
    const [a2, m2, d2] = partes(dias[6]);
    if (a1 !== a2) return `${diaBR(dias[0], true)} – ${diaBR(dias[6], true)}`;
    if (m1 !== m2) return `${d1} de ${MESES[m1]} – ${d2} de ${MESES[m2]} de ${a2}`;
    return `${d1} – ${d2} de ${MESES[m2]} de ${a2}`;
  })();

  return (
    <div className="bi-card flex min-h-0 flex-col overflow-hidden p-0">
      <Cabecalho {...p} titulo={titulo} onAndar={andar} onHoje={() => p.onFoco(hoje)} />
      {p.modo === "mensal" ? (
        <Mensal {...p} porDia={porDia} hoje={hoje} />
      ) : (
        <Grade {...p} porDia={porDia} hoje={hoje}
               dias={p.modo === "semanal" ? semanaDe(p.foco) : [p.foco]} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------- cabeçalho -- */

function Cabecalho({
  titulo, modo, onModo, onAndar, onHoje, onCriar, foco, onMostrarCard,
}: Props & { titulo: string; onAndar: (n: number) => void; onHoje: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2.5"
         style={{ borderColor: "var(--bi-line)" }}>
      <div className="flex items-center gap-1">
        <button type="button" onClick={() => onAndar(-1)} aria-label="Anterior"
                className="grid size-8 place-items-center rounded-lg bi-hover"
                style={{ color: "var(--bi-muted)" }}>
          <ChevronLeft className="size-4" />
        </button>
        <button type="button" onClick={onHoje} className={BOTAO_SEC} style={ESTILO_SEC}>
          Hoje
        </button>
        <button type="button" onClick={() => onAndar(1)} aria-label="Próximo"
                className="grid size-8 place-items-center rounded-lg bi-hover"
                style={{ color: "var(--bi-muted)" }}>
          <ChevronRight className="size-4" />
        </button>
      </div>

      <h2 className="bi-title min-w-0 flex-1 truncate text-[15px] first-letter:uppercase">
        {titulo}
      </h2>

      {/* ⚠️ SÓ TRÊS MODOS (decisão do dono). Agenda e ano não entram: a primeira
          é a aba Lista com outro nome, e a segunda não cabe num chip por dia. */}
      <div role="group" aria-label="Modo do calendário"
           className="flex overflow-hidden rounded-xl"
           style={{ border: "1px solid var(--bi-line)" }}>
        {([["mensal", "Mensal"], ["semanal", "Semanal"], ["diaria", "Diária"]] as const)
          .map(([v, rotulo]) => (
            <button key={v} type="button" onClick={() => onModo(v)}
                    aria-pressed={modo === v}
                    className="h-8 px-3 text-[12px] transition-colors"
                    style={modo === v
                      ? { background: "var(--bi-accent-soft)", color: "var(--bi-accent-ink)", fontWeight: 600 }
                      : { color: "var(--bi-muted)" }}>
              {rotulo}
            </button>
          ))}
      </div>

      {onMostrarCard && (
        <button type="button" onClick={onMostrarCard} className={BOTAO_SEC}
                style={ESTILO_SEC} title="Mostrar os compromissos de hoje">
          <PanelRightOpen className="size-3.5" />
          <span className="hidden sm:inline">Compromissos de hoje</span>
        </button>
      )}

      <button type="button" className={BOTAO_CTA} style={ESTILO_CTA}
              onClick={() => onCriar(foco)}>
        <CalendarPlus className="size-3.5" /> Adicionar compromisso
      </button>
    </div>
  );
}

/* ----------------------------------------------------------------- mensal -- */

function Mensal({
  porDia, hoje, foco, comMunicipio, onCriar, onAbrir, onEditar,
}: Props & { porDia: Record<string, Compromisso[]>; hoje: string }) {
  const [a, m0] = partes(foco);
  const primeiro = iso(a, m0, 1);
  /* A grade começa na segunda-feira da semana do dia 1º e vai até completar
     semanas inteiras — é o que faz o mês encaixar sem buraco na borda. */
  const inicio = somaDias(primeiro, -diaDaSemana(primeiro));
  const ultimo = limitesDoMes(foco)[1];
  const semanas = Math.ceil((diasEntre(inicio, ultimo) + 1) / 7);
  const dias = Array.from({ length: semanas * 7 }, (_, i) => somaDias(inicio, i));

  /* ⭐ QUANTOS CHIPS CABEM É MEDIDO, NÃO CHUTADO. Com a grade ocupando a tela, a
     célula de um mês de 5 semanas é bem mais alta que a de um mês de 6 — um
     teto fixo de três chips deixaria metade da célula vazia num caso e cortaria
     no outro. O observador mede a altura real da linha e responde. */
  const grade = useRef<HTMLDivElement>(null);
  const [cabem, setCabem] = useState(3);
  useLayoutEffect(() => {
    const el = grade.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const medir = () => {
      const alturaLinha = (el.clientHeight - 24) / semanas;   // 24 = cabeçalho
      setCabem(Math.max(1, Math.floor((alturaLinha - 26) / 22)));
    };
    medir();
    const obs = new ResizeObserver(medir);
    obs.observe(el);
    return () => obs.disconnect();
  }, [semanas]);

  const [aberto, setAberto] = useState<string | null>(null);
  const balao = useBalao();

  return (
    <div ref={grade} className="grid min-h-0 flex-1"
         style={{ gridTemplateRows: `24px repeat(${semanas}, minmax(0, 1fr))` }}>
      <div className="grid grid-cols-7">
        {SEMANA.map((s) => (
          <div key={s} className="text-center text-[10px] uppercase tracking-wider"
               style={{ color: "var(--bi-faint)" }}>{s}</div>
        ))}
      </div>
      {Array.from({ length: semanas }, (_, linha) => (
        <div key={linha} className="grid min-h-0 grid-cols-7">
          {dias.slice(linha * 7, linha * 7 + 7).map((dia) => {
            const doDia = porDia[dia] || [];
            const noMes = partes(dia)[1] === m0;
            const ehHoje = dia === hoje;
            const visiveis = doDia.slice(0, cabem);
            return (
              <div key={dia}
                   onDoubleClick={() => onCriar(dia)}
                   className="relative min-w-0 border-b border-r p-1"
                   style={{
                     borderColor: "var(--bi-line)",
                     background: noMes ? "var(--bi-surface)" : "var(--bi-surface-2)",
                   }}>
                <div className="mb-0.5 flex items-center justify-between">
                  <span className={`grid size-5 place-items-center rounded-full text-[10px] ${ehHoje ? "font-bold" : ""}`}
                        style={ehHoje
                          ? { background: "var(--bi-accent-ink)", color: "var(--bi-cta-ink)" }
                          : { color: noMes ? "var(--bi-muted)" : "var(--bi-faint)" }}>
                    {partes(dia)[2]}
                  </span>
                  {doDia.length > cabem && (
                    <button type="button"
                            onClick={(e) => { e.stopPropagation(); setAberto(aberto === dia ? null : dia); }}
                            className="rounded px-1 text-[10px] underline"
                            style={{ color: "var(--bi-accent-ink)" }}>
                      +{doDia.length - cabem}
                    </button>
                  )}
                </div>
                <div className="space-y-0.5 overflow-hidden">
                  {visiveis.map((c) => (
                    <ChipMes key={c.id} c={c} balao={balao}
                             onAbrir={onAbrir} onEditar={onEditar} />
                  ))}
                </div>
                {aberto === dia && (
                  <PopoverDia dia={dia} itens={doDia} comMunicipio={comMunicipio}
                              onFechar={() => setAberto(null)}
                              onAbrir={(c) => { setAberto(null); onAbrir(c); }} />
                )}
              </div>
            );
          })}
        </div>
      ))}
      {balao.no}
    </div>
  );
}

function ChipMes({ c, balao, onAbrir, onEditar }: {
  c: Compromisso;
  balao: ReturnType<typeof useBalao>;
  onAbrir: (c: Compromisso) => void;
  onEditar: (c: Compromisso) => void;
}) {
  const clique = useCliqueSimplesOuDuplo(onAbrir, onEditar);
  return (
    <button type="button" style={estiloDaCor(c.cor)}
            {...clique(c)} {...balao.gatilhos(c)}
            className="ag-chip flex w-full items-center gap-1 px-1 py-[3px] text-left text-[10px] leading-tight">
      <span className="shrink-0 font-semibold tabular-nums">{c.hora_inicio}</span>
      <span className="min-w-0 flex-1 truncate">{c.demanda}</span>
    </button>
  );
}

/** A lista do dia quando não cabe tudo na célula. Fecha com Esc ou clique fora. */
function PopoverDia({ dia, itens, comMunicipio, onFechar, onAbrir }: {
  dia: string;
  itens: Compromisso[];
  comMunicipio: boolean;
  onFechar: () => void;
  onAbrir: (c: Compromisso) => void;
}) {
  const caixa = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const fora = (e: MouseEvent) => {
      if (!caixa.current?.contains(e.target as Node)) onFechar();
    };
    const tecla = (e: KeyboardEvent) => { if (e.key === "Escape") onFechar(); };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", tecla);
    };
  }, [onFechar]);
  return (
    <div ref={caixa} role="dialog" aria-label={`Compromissos de ${diaBR(dia, true)}`}
         className="bi-scroll absolute left-1 right-1 top-6 z-20 max-h-56 overflow-y-auto rounded-xl p-2"
         style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line-strong)",
                  boxShadow: "var(--bi-shadow)" }}>
      <p className="mb-1 text-[10px] font-semibold" style={{ color: "var(--bi-muted)" }}>
        {diaBR(dia, true)} · {itens.length}
      </p>
      <div className="space-y-0.5">
        {itens.map((c) => (
          <button key={c.id} type="button" onClick={() => onAbrir(c)}
                  style={estiloDaCor(c.cor)}
                  className="ag-chip block w-full px-1.5 py-1 text-left text-[10px] leading-tight">
            <span className="font-semibold tabular-nums">{horarioDe(c)}</span>{" "}
            {c.demanda}
            {comMunicipio && (
              <span className="block opacity-70">{c.municipio}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

/* -------------------------------------------------- semanal e diária ------ */

function Grade({
  porDia, hoje, dias, comMunicipio, onCriar, onAbrir, onEditar, modo,
}: Props & { porDia: Record<string, Compromisso[]>; hoje: string; dias: string[] }) {
  const balao = useBalao();
  const rolagem = useRef<HTMLDivElement>(null);
  const [agora, setAgora] = useState(() => new Date());

  /* A linha do horário atual anda sozinha. Um minuto de intervalo: a linha
     move-se 0,8px por minuto, e um relógio mais rápido gastaria render por
     nada. */
  useEffect(() => {
    const t = setInterval(() => setAgora(new Date()), 60_000);
    return () => clearInterval(t);
  }, []);

  /* Abre mostrando o começo do expediente. Sem isto a régua abre em 00:00 e a
     pessoa rola sete horas de madrugada vazia toda vez que entra. */
  useLayoutEffect(() => {
    if (rolagem.current) rolagem.current.scrollTop = 7 * ALT_HORA;
  }, [modo]);

  const minutosAgora = agora.getHours() * 60 + agora.getMinutes();

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Cabeçalho dos dias, parado enquanto a régua rola. */}
      <div className="flex border-b" style={{ borderColor: "var(--bi-line)" }}>
        <div className="w-12 shrink-0" />
        {dias.map((dia) => {
          const ehHoje = dia === hoje;
          return (
            <div key={dia} className="min-w-0 flex-1 py-1.5 text-center">
              <div className="text-[10px] uppercase tracking-wider"
                   style={{ color: "var(--bi-faint)" }}>
                {SEMANA[diaDaSemana(dia)]}
              </div>
              <div className="mx-auto mt-0.5 grid size-6 place-items-center rounded-full text-[12px] font-semibold"
                   style={ehHoje
                     ? { background: "var(--bi-accent-ink)", color: "var(--bi-cta-ink)" }
                     : { color: "var(--bi-text)" }}>
                {partes(dia)[2]}
              </div>
            </div>
          );
        })}
      </div>

      <div ref={rolagem} className="bi-scroll min-h-0 flex-1 overflow-y-auto">
        <div className="relative flex" style={{ height: 24 * ALT_HORA }}>
          {/* A régua de horas, 00–23. */}
          <div className="w-12 shrink-0">
            {Array.from({ length: 24 }, (_, h) => (
              <div key={h} className="relative" style={{ height: ALT_HORA }}>
                <span className="absolute -top-1.5 right-1.5 text-[10px] tabular-nums"
                      style={{ color: "var(--bi-faint)" }}>
                  {h === 0 ? "" : `${String(h).padStart(2, "0")}:00`}
                </span>
              </div>
            ))}
          </div>

          {dias.map((dia) => {
            const doDia = porDia[dia] || [];
            const faixas = repartirEmColunas(doDia);
            return (
              <div key={dia} className="relative min-w-0 flex-1 border-l"
                   style={{ borderColor: "var(--bi-line)" }}>
                {/* Os slots de hora: alvo do duplo clique que já vem com a
                    hora preenchida. */}
                {Array.from({ length: 24 }, (_, h) => (
                  <div key={h}
                       onDoubleClick={() =>
                         onCriar(dia, `${String(h).padStart(2, "0")}:00`)}
                       className="border-b"
                       style={{ height: ALT_HORA, borderColor: "var(--bi-line)" }} />
                ))}

                {dia === hoje && (
                  <div className="pointer-events-none absolute inset-x-0 z-10"
                       style={{ top: (minutosAgora / 60) * ALT_HORA }}
                       aria-hidden="true">
                    <div className="h-px" style={{ background: "var(--bi-crit)" }} />
                    <div className="absolute -left-1 -top-1 size-2 rounded-full"
                         style={{ background: "var(--bi-crit)" }} />
                  </div>
                )}

                {doDia.map((c) => (
                  <BlocoHora key={c.id} c={c} faixa={faixas.get(c.id)}
                             comMunicipio={comMunicipio} balao={balao}
                             onAbrir={onAbrir} onEditar={onEditar} />
                ))}
              </div>
            );
          })}
        </div>
      </div>
      {balao.no}
    </div>
  );
}

function BlocoHora({ c, faixa, comMunicipio, balao, onAbrir, onEditar }: {
  c: Compromisso;
  faixa?: { col: number; cols: number };
  comMunicipio: boolean;
  balao: ReturnType<typeof useBalao>;
  onAbrir: (c: Compromisso) => void;
  onEditar: (c: Compromisso) => void;
}) {
  const clique = useCliqueSimplesOuDuplo(onAbrir, onEditar);
  const col = faixa?.col ?? 0;
  const cols = faixa?.cols ?? 1;
  const altura = (duracaoDe(c) / 60) * ALT_HORA;
  return (
    <button
      type="button" style={{
        ...estiloDaCor(c.cor),
        top: (minutos(c.hora_inicio) / 60) * ALT_HORA,
        height: Math.max(20, altura - 2),
        left: `calc(${(col / cols) * 100}% + 2px)`,
        width: `calc(${100 / cols}% - 4px)`,
      }}
      {...clique(c)} {...balao.gatilhos(c)}
      className="ag-chip absolute z-[5] overflow-hidden px-1.5 py-0.5 text-left text-[10px] leading-tight">
      <span className="block truncate font-semibold">{c.demanda}</span>
      {altura >= 34 && (
        <span className="block truncate tabular-nums opacity-80">{horarioDe(c)}</span>
      )}
      {altura >= 58 && comMunicipio && (
        <span className="block truncate opacity-70">{c.municipio}</span>
      )}
    </button>
  );
}

/* ------------------------------------------------------------ interações -- */

/** Um clique abre; dois editam. Ver a nota no cabeçalho do arquivo. */
function useCliqueSimplesOuDuplo(
  simples: (c: Compromisso) => void,
  duplo: (c: Compromisso) => void,
) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  return (c: Compromisso) => ({
    onClick: (e: React.MouseEvent) => {
      e.stopPropagation();
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => { timer.current = null; simples(c); },
                                 ESPERA_DUPLO);
    },
    onDoubleClick: (e: React.MouseEvent) => {
      /* ⚠️ `stopPropagation` OBRIGATÓRIO: sem ele o duplo clique sobe para a
         célula do dia e abre a criação por cima da edição. */
      e.stopPropagation();
      if (timer.current) { clearTimeout(timer.current); timer.current = null; }
      duplo(c);
    },
  });
}

/** O balão de passagem: demanda, horário, solicitante e município.
 *
 * ⚠️ POSIÇÃO `fixed` A PARTIR DO RETÂNGULO DO ALVO, e não `absolute` dentro da
 * célula: dentro da célula ele seria cortado pelo `overflow-hidden` da grade
 * justamente nas bordas, que é onde ele mais precisa aparecer. */
function useBalao() {
  const [alvo, setAlvo] = useState<{ c: Compromisso; x: number; y: number } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const limpar = useCallback(() => {
    if (timer.current) { clearTimeout(timer.current); timer.current = null; }
    setAlvo(null);
  }, []);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  const gatilhos = (c: Compromisso) => ({
    onMouseEnter: (e: React.MouseEvent<HTMLElement>) => {
      const r = e.currentTarget.getBoundingClientRect();
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(
        () => setAlvo({ c, x: r.left + r.width / 2, y: r.top }), ATRASO_BALAO);
    },
    onMouseLeave: limpar,
    /* O balão é dica, não conteúdo: quem navega por teclado abre o detalhe com
       Enter e vê tudo. Some ao rolar para não ficar pendurado no ar. */
    onBlur: limpar,
  });

  const no = alvo ? <Balao {...alvo} /> : null;
  return { gatilhos, no, limpar };
}

function Balao({ c, x, y }: { c: Compromisso; x: number; y: number }) {
  return (
    <div role="tooltip"
         className="pointer-events-none fixed z-50 w-56 -translate-x-1/2 -translate-y-full rounded-xl p-2"
         style={{ left: x, top: y - 8, background: "var(--bi-surface)",
                  border: "1px solid var(--bi-line-strong)",
                  boxShadow: "var(--bi-shadow)" }}>
      <div className="flex items-start gap-1.5">
        <span className="ag-tarja mt-0.5 h-3 w-1 shrink-0 rounded-full"
              style={estiloDaCor(c.cor)} />
        <div className="min-w-0">
          <p className="text-[12px] font-semibold leading-snug">{c.demanda}</p>
          <p className="mt-0.5 text-[11px] tabular-nums" style={{ color: "var(--bi-muted)" }}>
            {horarioDe(c)}
          </p>
          <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
            {c.solicitante || "sem solicitante"}
          </p>
          {c.municipio && (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              {c.municipio}{c.uf ? ` - ${c.uf}` : ""}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
