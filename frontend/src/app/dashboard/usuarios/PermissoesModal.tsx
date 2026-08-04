"use client";
// A TELA QUE DECIDE O QUE CADA PESSOA FAZ — 66 caixinhas sem virar paredão.
//
// O RISCO DESTE ARQUIVO NÃO É TÉCNICO, É DE DESISTÊNCIA. Sessenta e seis caixas
// numa lista corrida têm um resultado previsível: o administrador não lê,
// procura o atalho e marca tudo. E permissão granular que todo mundo recebe
// inteira é o mesmo "admin vê tudo" de antes, agora com 66 linhas no banco para
// disfarçar. Três decisões existem só para evitar isso:
//
//   1. SEÇÕES FECHADAS. Abre com nove linhas, não com sessenta e seis. Cada
//      seção fechada já responde o que interessa — "Relatório de Monitoramento:
//      Ver, Editar" —, então dá para conferir a pessoa inteira sem expandir
//      nada.
//   2. MARCAR/LIMPAR POR SEÇÃO. O gesto que o administrador quer fazer ("essa
//      pessoa cuida de convênios") é por assunto, e não caixinha a caixinha.
//   3. NENHUM "MARCAR TUDO" GLOBAL, e a ausência é a decisão. Um botão que
//      concede as 66 de uma vez seria o caminho mais curto da tela, e o caminho
//      mais curto é o que as pessoas usam. Também não há atalho "só leitura":
//      pareceria inofensivo e concederia `cofre.revelar` e `auditoria.exportar`,
//      que não são escrita e são as duas caixinhas mais sensíveis do sistema.
//
// ⚠️ ANTI-ESCALONAMENTO. O que quem edita não possui aparece TRAVADO, com a
// explicação escrita. Não é enfeite de tela: `routers/permissoes.py::conceder`
// barra a mesma coisa no servidor, e barra nos dois modos de `AUTHZ_MODO`. A
// tela existe para o limite ser entendido antes do clique — e não descoberto
// num 403 depois de dez minutos marcando caixinha.
//
// ⚠️ Nenhuma lista de permissão mora aqui. Tudo vem do catálogo da API — ver o
// cabeçalho de `lib/permissoes.ts`.
import { useMemo, useState } from "react";
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, Loader2, Lock, ShieldCheck,
} from "lucide-react";
import {
  AcaoMini, Aviso, Bloco, BlocoHead, BOTAO_CTA, BOTAO_SEC, ESTILO_CTA,
  ESTILO_SEC, Modal, ModalCorpo, ModalHead, Selo,
} from "@/components/ui/superficies";
import { ehSomenteLeitura, ehSuperAdmin } from "@/lib/conta";
import {
  chavesDaSecao, resumoPorRecurso, salvarPermissoes,
  type Catalogo, type MinhasPermissoes, type SecaoCatalogo,
} from "@/lib/permissoes";

export interface AlvoPermissoes {
  id: number;
  name: string;
  email: string;
  role: string;
  super_admin?: boolean | null;
  somente_leitura?: boolean | null;
}

/** As linhas do resumo, em cinza. Uma por recurso ("Cofre de senhas: Ver"). */
function Resumo({ linhas }: { linhas: string[] }) {
  return (
    <ul className="flex flex-col gap-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
      {linhas.map((l) => {
        /* Corta no PRIMEIRO ": " e não em todos: rótulo de recurso pode conter
           dois-pontos, e um `split` cru comeria os verbos depois do segundo. */
        const corte = l.indexOf(": ");
        const recurso = corte < 0 ? l : l.slice(0, corte);
        const verbos = corte < 0 ? "" : l.slice(corte + 2);
        return (
          /* O marcador é escrito à mão: o reset de CSS do projeto tira o
             `list-style`, e sem ele as linhas viram um parágrafo só. */
          <li key={l} className="flex gap-1.5">
            <span aria-hidden style={{ color: "var(--bi-faint)" }}>·</span>
            <span className="min-w-0">
              <b style={{ color: "var(--bi-text)", fontWeight: 500 }}>{recurso}</b>
              {verbos ? <>: {verbos}</> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

export default function PermissoesModal({
  alvo, catalogo, minhas, concedidas, souEu, onFechar, onSalvo,
}: {
  alvo: AlvoPermissoes;
  catalogo: Catalogo;
  /** O que QUEM EDITA pode. `null` = não deu para carregar, e aí tudo trava:
   *  sem saber o que o editor tem, não há como dizer o que ele pode conceder. */
  minhas: MinhasPermissoes | null;
  /** As caixinhas marcadas HOJE no alvo — o estado contra o qual o diff é feito. */
  concedidas: string[];
  souEu: boolean;
  onFechar: () => void;
  onSalvo: () => void | Promise<void>;
}) {
  const original = useMemo(() => new Set(concedidas), [concedidas]);
  const [sel, setSel] = useState<Set<string>>(() => new Set(concedidas));
  // Todas fechadas ao abrir — ver a decisão 1 no cabeçalho.
  const [abertas, setAbertas] = useState<Set<string>>(new Set());
  const [salvando, setSalvando] = useState(false);

  const alvoSuper = ehSuperAdmin(alvo);
  const alvoLeitura = ehSomenteLeitura(alvo);

  /** Quem edita pode mexer NESTA caixinha? Super-admin pode em todas; os demais,
   *  só nas que eles próprios têm. Sem `minhas`, ninguém mexe em nada. */
  const posso = (chave: string) =>
    !!minhas && (minhas.super_admin || minhas.chaves.includes(chave));

  const alternar = (chave: string) =>
    setSel((prev) => {
      const n = new Set(prev);
      if (n.has(chave)) n.delete(chave); else n.add(chave);
      return n;
    });

  /** Marcar/limpar seção alcança SÓ o que quem edita pode conceder — o resto
   *  fica exatamente como estava. Um atalho que arrastasse caixinha travada
   *  junto seria o próprio escalonamento, só que num botão. */
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

  const aConceder = [...sel].filter((c) => !original.has(c));
  const aRetirar = [...original].filter((c) => !sel.has(c));
  const mudou = aConceder.length > 0 || aRetirar.length > 0;

  const linhas = resumoPorRecurso(catalogo, sel);
  // Quantas caixinhas de ESCRITA estão marcadas: é o número que explica por que
  // uma conta em somente leitura não vai fazer o que a tela diz que ela faz.
  const escritasMarcadas = catalogo.permissoes.filter(
    (p) => p.escrita && sel.has(p.chave),
  ).length;
  const travadas = minhas?.super_admin
    ? 0
    : catalogo.permissoes.filter((p) => !posso(p.chave)).length;

  const salvar = async () => {
    setSalvando(true);
    try {
      await salvarPermissoes(alvo.id, [...sel]);
      await onSalvo();
      onFechar();
    } catch (e: unknown) {
      alert(
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Erro ao salvar as permissões",
      );
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal
      aberto
      maxW="max-w-2xl"
      onFechar={onFechar}
      /* Consultado nas TRÊS saídas (Esc, clique fora e o X). Marcar trinta
         caixinhas e perdê-las num clique torto é o tipo de coisa que faz o
         administrador não voltar a esta tela. */
      podeFechar={() => !mudou || confirm("Descartar as alterações de permissão?")}
    >
      <ModalHead
        titulo={`Permissões de ${alvo.name}`}
        sub={
          <>
            {alvo.email} — as <b>telas</b> dizem onde a pessoa entra; estas caixinhas
            dizem o que ela <b>faz</b> lá dentro.
          </>
        }
        onFechar={onFechar}
        right={
          <span className="bi-num text-[13px]" title="Caixinhas marcadas">
            {sel.size}/{catalogo.total}
          </span>
        }
      />
      <ModalCorpo className="space-y-2.5">
        {!minhas && (
          <Aviso
            tom="critico"
            icon={AlertTriangle}
            titulo="Não deu para conferir as suas próprias permissões."
            className=""
          >
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Ninguém concede o que não tem, e sem essa conferência não há como
              saber o que você pode conceder. Tudo fica travado até recarregar a
              tela.
            </p>
          </Aviso>
        )}

        {alvoSuper && (
          /* Mesma ressalva que o modal de Acesso já faz para telas e municípios:
             marcar aqui não é proibido, é inócuo enquanto a conta for da
             Alavank — e passa a valer no dia em que ela deixar de ser. */
          <Aviso
            tom="atencao"
            icon={ShieldCheck}
            titulo="Esta é uma conta super-admin: ela pode tudo, sem depender destas caixinhas."
            className=""
          >
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              O que for marcado fica guardado e só passa a valer se a conta deixar
              de ser super-admin.
            </p>
          </Aviso>
        )}

        {alvoLeitura && escritasMarcadas > 0 && (
          <Aviso
            tom="atencao"
            icon={Lock}
            titulo={`Conta em somente leitura: ${escritasMarcadas} caixinha(s) marcada(s) alteram dados e não vão valer.`}
            className=""
          >
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              A trava de escrita da conta vem antes da permissão: ela fica guardada
              e volta a valer se a conta deixar de ser somente leitura. Para liberar
              agora, desmarque <b>Somente leitura</b> em <b>Acesso</b>.
            </p>
          </Aviso>
        )}

        {souEu && (
          <Aviso
            tom="atencao"
            icon={AlertTriangle}
            titulo="Você está editando as suas próprias permissões."
            className=""
          >
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Só dá para RETIRAR: conceder exigiria ter o que você ainda não tem.
              O que for retirado vale na hora, e devolver depende de outra pessoa
              que tenha aquela caixinha.
            </p>
          </Aviso>
        )}

        {/* O RESUMO — a leitura em português, antes das caixinhas.
            É o que responde "o que essa pessoa pode?" sem obrigar ninguém a
            conferir sessenta e seis caixas uma a uma. */}
        <Bloco className="p-3">
          <BlocoHead
            icon={ShieldCheck}
            titulo="O que esta pessoa vai poder"
            sub={
              mudou
                ? `${aConceder.length} a conceder · ${aRetirar.length} a retirar — ainda não salvo`
                : "Igual ao que está gravado hoje."
            }
          />
          {linhas.length === 0 ? (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>
              Nenhuma caixinha marcada. A pessoa entra no sistema e não consegue
              fazer nada — nem consultar as telas a que tem acesso.
            </p>
          ) : (
            <Resumo linhas={linhas} />
          )}
          {minhas?.modo === "aviso" && (
            /* Sem cor: não é alerta, é o estado normal do sistema hoje. Mas
               precisa estar escrito, senão o administrador marca as caixinhas,
               vê a pessoa continuar fazendo o que fazia e conclui que a tela
               está quebrada. */
            <p className="mt-2 border-t pt-2 text-[10px]" style={{ borderColor: "var(--bi-line)", color: "var(--bi-faint)" }}>
              As permissões estão em <b>modo aviso</b>: por enquanto o sistema
              apenas registra o que teria barrado, sem bloquear ninguém. O que for
              marcado aqui já fica valendo para quando a trava for ligada.
            </p>
          )}
        </Bloco>

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
          const resumoSecao = resumoPorRecurso(catalogo, sel, s.chave);
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
                  {/* Fechada, a seção já responde o que a pessoa pode ali. É o
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
                  {s.recursos.map((r) => (
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
                              /* O rótulo COMPLETO ("Relatório de Monitoramento
                                 — Excluir"). Na tela aparece só o verbo, porque
                                 o recurso já está escrito acima do grupo e
                                 repeti-lo cinco vezes seguidas é o que faz a
                                 lista virar parede; aqui ele fica disponível
                                 para quem precisar do nome inteiro. */
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
                                  {/* Só onde a distinção MUDA o resultado: numa
                                      conta em somente leitura, a caixinha de
                                      escrita fica guardada e não vale. Marcar
                                      todas as 30 de escrita em toda conta seria
                                      ruído. */}
                                  {alvoLeitura && p.escrita && (
                                    <Selo title="A trava de somente leitura da conta barra esta ação.">
                                      não vale nesta conta
                                    </Selo>
                                  )}
                                </span>
                                <span className="mt-0.5 block text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                                  {p.descricao}
                                </span>
                                {travada && (
                                  <span className="mt-0.5 flex items-start gap-1 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
                                    <Lock className="mt-px size-3 shrink-0" />
                                    Você não tem esta permissão, então não pode
                                    {marcada ? " retirá-la" : " concedê-la"}.
                                  </span>
                                )}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Bloco>
          );
        })}
      </ModalCorpo>

      {/* Rodapé fixo: com nove seções abertas a lista é longa, e um botão de
          salvar no fim dela é um botão que ninguém acha. */}
      <div
        className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-4 py-3"
        style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface)" }}
      >
        <span className="mr-auto text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {mudou
            ? `${aConceder.length} a conceder · ${aRetirar.length} a retirar`
            : "Nada alterado."}
        </span>
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={onFechar}>
          Cancelar
        </button>
        <button
          type="button"
          className={BOTAO_CTA}
          style={ESTILO_CTA}
          onClick={salvar}
          disabled={salvando || !mudou || !minhas}
        >
          {salvando ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          Salvar permissões
        </button>
      </div>
    </Modal>
  );
}
