"use client";
// AS 66 CAIXINHAS — a arvore de permissoes, em UM lugar so.
//
// Nasceu dentro de `PermissoesModal` e saiu para ca quando os MODELOS chegaram:
// o editor de modelo pede exatamente a mesma arvore (secoes fechadas, marcar por
// secao, alcance por modulo, caixinha travada com a explicacao). Copiar 150
// linhas para o editor criaria duas telas de permissao ligeiramente diferentes —
// e a divergencia entre elas nao apareceria como defeito: apareceria como um
// modelo que concede algo que a tela de usuario nem desenha.
//
// As tres decisoes de desenho continuam sendo as do modal original, e continuam
// valendo aqui: secoes FECHADAS ao abrir, marcar/limpar POR SECAO, e nenhum
// "marcar tudo" global.
//
// ⚠️ ANTI-ESCALONAMENTO. Quem usa esta peca passa `posso` e `alcanceTravado`; a
// peca so DESENHA o limite. Quem barra de verdade e o servidor.
import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Lock } from "lucide-react";
import { AcaoMini, Bloco, Selo } from "@/components/ui/superficies";
import type { Escopo, MapaEscopos } from "@/lib/escopo";
import {
  chavesDaSecao, escopoDe, permissoesDeEscopo, recursosComEscopo,
  resumoPorRecurso,
  type Catalogo, type EscopoOpcao, type Permissao, type SecaoCatalogo,
} from "@/lib/permissoes";

/** Onde a arvore esta desenhada. Muda SO a redacao das frases de trava — o que
 *  se "concede" a uma pessoa, num modelo se "coloca". Uma frase escrita para
 *  usuario aparecendo no editor de modelo ("nao pode concedê-la") mandaria o
 *  administrador procurar um problema de permissao que nao existe ali. */
export type ContextoSelecao = "usuario" | "modelo";

/** A ESCOLHA DE ALCANCE de um modulo — a regra de linha, em duas opcoes.
 *
 *  ⚠️ SO APARECE COM «Editar» OU «Excluir» MARCADO, e isso e a peca do desenho,
 *  nao um detalhe: numa conta que so consulta, "somente os que ele criou" nao
 *  restringe nada — restringiria uma escrita que ela nao tem. Mostrar assim
 *  mesmo somaria mais um controle a cada um dos 15 recursos de um modal que ja
 *  tem 66 caixinhas, e cada um deles seria uma pergunta sem consequencia.
 *
 *  Radio, e nao interruptor: sao dois estados NOMEADOS, e o padrao — "Todos os
 *  registros" — precisa estar escrito. */
function Alcance({
  recurso, rotulo, verbos, opcoes, valor, travado, contexto, onChange,
}: {
  recurso: string;
  rotulo: string;
  /** Os verbos de escrita MARCADOS ("Editar e Excluir"): e sobre eles, e so
   *  sobre eles, que esta escolha manda. */
  verbos: string;
  /** As duas opcoes, com rotulo e explicacao — vindas do catalogo da API.
   *  Nenhum texto de permissao e escrito nesta tela. */
  opcoes: EscopoOpcao[];
  valor: Escopo;
  /** Quem edita alcanca so o proprio trabalho neste modulo. O servidor recusa
   *  (403) que essa pessoa defina o alcance de outra ali — ninguem devolve um
   *  alcance que ele mesmo nao tem. */
  travado: boolean;
  contexto: ContextoSelecao;
  onChange: (v: Escopo) => void;
}) {
  return (
    <div className="mt-2 border-t pt-2" style={{ borderColor: "var(--bi-line)" }}>
      <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
        Alcance de {verbos}
      </div>
      <div
        role="radiogroup"
        aria-label={`Alcance de ${verbos} em ${rotulo}`}
        className="mt-1 flex flex-col gap-1.5"
      >
        {opcoes.map((op) => (
          <label
            key={op.valor}
            className={`flex items-start gap-2 ${travado ? "cursor-not-allowed" : "cursor-pointer"}`}
          >
            <input
              type="radio"
              /* O `name` e por RECURSO: sem ele os radios de Gestao Interna e os
                 de RM seriam um grupo so, e escolher num modulo mudaria o
                 outro. */
              name={`escopo-${contexto}-${recurso}`}
              checked={valor === op.valor}
              disabled={travado}
              onChange={() => onChange(op.valor)}
              className="mt-0.5 size-3.5 shrink-0"
              style={{ accentColor: "var(--bi-cta)" }}
            />
            <span className="min-w-0 flex-1">
              <span
                className="text-[12px] font-medium leading-tight"
                style={{ color: travado ? "var(--bi-faint)" : "var(--bi-text)" }}
              >
                {op.rotulo}
              </span>
              <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                {op.descricao}
              </span>
            </span>
          </label>
        ))}
      </div>
      {travado && (
        <span className="mt-1 flex items-start gap-1 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
          <Lock className="mt-px size-3 shrink-0" />
          Neste módulo você alcança só os registros que você mesmo criou, então
          não define {contexto === "modelo" ? "este alcance num modelo" : "o alcance de outra pessoa aqui"}.
        </span>
      )}
    </div>
  );
}

export default function SeletorPermissoes({
  catalogo, sel, setSel, esc, setEsc, posso, alcanceTravado,
  contexto = "usuario", seloDe,
}: {
  catalogo: Catalogo;
  sel: Set<string>;
  setSel: React.Dispatch<React.SetStateAction<Set<string>>>;
  esc: MapaEscopos;
  setEsc: React.Dispatch<React.SetStateAction<MapaEscopos>>;
  /** Quem edita pode mexer NESTA caixinha? */
  posso: (chave: string) => boolean;
  /** Quem edita pode definir o alcance NESTE modulo? */
  alcanceTravado: (recurso: string) => boolean;
  contexto?: ContextoSelecao;
  /** Selo extra ao lado do verbo — hoje so o "não vale nesta conta" das contas
   *  em somente leitura, que e conceito de CONTA e nao existe num modelo. */
  seloDe?: (p: Permissao) => React.ReactNode;
}) {
  // Todas fechadas ao abrir: abre com nove linhas, nao com sessenta e seis.
  const [abertas, setAbertas] = useState<Set<string>>(new Set());

  /** Os modulos onde o alcance por autor existe de verdade — quem responde e a
   *  API, e nao uma lista escrita aqui. */
  const comEscopo = useMemo(() => recursosComEscopo(catalogo), [catalogo]);
  const opcoesEscopo: EscopoOpcao[] = catalogo.escopos?.opcoes ?? [];

  const alternar = (chave: string) =>
    setSel((prev) => {
      const n = new Set(prev);
      if (n.has(chave)) n.delete(chave); else n.add(chave);
      return n;
    });

  /** Marcar/limpar secao alcanca SO o que quem edita pode conceder — o resto
   *  fica exatamente como estava. Um atalho que arrastasse caixinha travada
   *  junto seria o proprio escalonamento, so que num botao. */
  const marcarSecao = (s: SecaoCatalogo, ligar: boolean) =>
    setSel((prev) => {
      const n = new Set(prev);
      for (const chave of chavesDaSecao(s)) {
        if (!posso(chave)) continue;
        if (ligar) n.add(chave); else n.delete(chave);
      }
      return n;
    });

  const alternarSecao = (chave: string) =>
    setAbertas((prev) => {
      const n = new Set(prev);
      if (n.has(chave)) n.delete(chave); else n.add(chave);
      return n;
    });

  const travadas = catalogo.permissoes.filter((p) => !posso(p.chave)).length;

  return (
    <>
      {travadas > 0 && (
        <p className="flex items-start gap-1.5 px-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          <Lock className="mt-px size-3.5 shrink-0" style={{ color: "var(--bi-faint)" }} />
          <span>
            {travadas} caixinha(s) aparecem travadas porque <b>você não as tem</b>.
            Ninguém concede — nem retira — o que não possui.
          </span>
        </p>
      )}

      {catalogo.secoes.map((s) => {
        const chaves = chavesDaSecao(s);
        const marcadas = chaves.filter((c) => sel.has(c)).length;
        const alcancaveis = chaves.filter((c) => posso(c));
        const aberta = abertas.has(s.chave);
        const resumoSecao = resumoPorRecurso(catalogo, sel, s.chave, esc);
        const Seta = aberta ? ChevronDown : ChevronRight;
        return (
          <Bloco className="p-3" key={s.chave}>
            <div className="flex items-start gap-2">
              <button
                type="button"
                onClick={() => alternarSecao(s.chave)}
                aria-expanded={aberta}
                className="min-w-0 flex-1 text-left"
              >
                <span className="flex items-center gap-1.5">
                  <Seta className="size-3.5 shrink-0" style={{ color: "var(--bi-faint)" }} />
                  <span className="bi-title text-[13px] leading-tight">{s.rotulo}</span>
                  {marcadas > 0 && <Selo>{marcadas} de {chaves.length}</Selo>}
                </span>
                <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                  {s.descricao}
                </span>
                {/* Fechada, a secao ja responde o que a pessoa pode ali. E o
                    que permite conferir sem expandir nada. */}
                {!aberta && (
                  <span className="mt-1 block text-[11px] leading-snug" style={{ color: marcadas ? "var(--bi-text)" : "var(--bi-faint)" }}>
                    {marcadas ? resumoSecao.join(" · ") : "Nada marcado nesta seção."}
                  </span>
                )}
              </button>
              <span className="flex shrink-0 items-center gap-1">
                <AcaoMini
                  onClick={() => marcarSecao(s, true)}
                  disabled={alcancaveis.length === 0
                    || alcancaveis.every((c) => sel.has(c))}
                >
                  Marcar seção
                </AcaoMini>
                <AcaoMini
                  onClick={() => marcarSecao(s, false)}
                  disabled={!alcancaveis.some((c) => sel.has(c))}
                >
                  Limpar
                </AcaoMini>
              </span>
            </div>

            {aberta && (
              <div className="mt-2.5 flex flex-col gap-1.5">
                {s.recursos.map((r) => {
                  // As caixinhas de escrita por linha (Editar, Excluir) que
                  // estao MARCADAS agora: sao elas que dao sentido a escolha
                  // de alcance, e sao elas que decidem se ela aparece.
                  const escritasLinha = comEscopo.has(r.recurso)
                    ? permissoesDeEscopo(catalogo, r).filter((p) => sel.has(p.chave))
                    : [];
                  return (
                  /* Item cinza dentro do bloco branco: a terceira camada da
                     identidade (fundo cinza -> bloco branco -> item cinza). */
                  <div key={r.recurso} className="bi-card-flat px-3 py-2.5">
                    <div className="text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                      {r.recurso_rotulo}
                    </div>
                    <div className="mt-1.5 flex flex-col gap-2">
                      {r.permissoes.map((p) => {
                        const travada = !posso(p.chave);
                        const marcada = sel.has(p.chave);
                        return (
                          <label
                            key={p.chave}
                            /* O rotulo COMPLETO ("Relatório de Monitoramento
                               — Excluir"). Na tela aparece so o verbo, porque
                               o recurso ja esta escrito acima do grupo e
                               repeti-lo cinco vezes seguidas e o que faz a
                               lista virar parede. */
                            title={p.rotulo}
                            className={`flex items-start gap-2 ${travada ? "cursor-not-allowed" : "cursor-pointer"}`}
                          >
                            <input
                              type="checkbox"
                              checked={marcada}
                              disabled={travada}
                              onChange={() => alternar(p.chave)}
                              className="mt-0.5 size-3.5 shrink-0"
                              /* accentColor pelo token: acompanha claro e
                                 escuro em vez de o navegador pintar de azul
                                 do sistema. */
                              style={{ accentColor: "var(--bi-cta)" }}
                            />
                            <span className="min-w-0 flex-1">
                              <span className="flex flex-wrap items-center gap-1.5">
                                <span
                                  className="text-[12px] font-medium leading-tight"
                                  style={{ color: travada ? "var(--bi-faint)" : "var(--bi-text)" }}
                                >
                                  {p.verbo_rotulo}
                                </span>
                                {seloDe?.(p)}
                              </span>
                              <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                                {p.descricao}
                              </span>
                              {travada && (
                                <span className="mt-0.5 flex items-start gap-1 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                                  <Lock className="mt-px size-3 shrink-0" />
                                  Você não tem esta permissão, então não pode
                                  {contexto === "modelo"
                                    ? (marcada ? " tirá-la deste modelo" : " colocá-la neste modelo")
                                    : (marcada ? " retirá-la" : " concedê-la")}.
                                </span>
                              )}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                    {escritasLinha.length > 0 && opcoesEscopo.length > 0 && (
                      <Alcance
                        recurso={r.recurso}
                        rotulo={r.recurso_rotulo}
                        verbos={escritasLinha.map((p) => p.verbo_rotulo).join(" e ")}
                        opcoes={opcoesEscopo}
                        valor={escopoDe(esc, r.recurso)}
                        travado={alcanceTravado(r.recurso)}
                        contexto={contexto}
                        onChange={(v) => setEsc((prev) => ({ ...prev, [r.recurso]: v }))}
                      />
                    )}
                  </div>
                  );
                })}
              </div>
            )}
          </Bloco>
        );
      })}
    </>
  );
}
