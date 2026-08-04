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
import type { Escopo, MapaEscopos } from "@/lib/escopo";
import {
  chavesDaSecao, escopoDe, permissoesDeEscopo, recursosComEscopo,
  resumoPorRecurso, salvarPermissoes,
  type Catalogo, type EscopoOpcao, type MinhasPermissoes, type SecaoCatalogo,
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

/** A ESCOLHA DE ALCANCE de um módulo — a regra de linha, em duas opções.
 *
 *  ⚠️ SÓ APARECE COM «Editar» OU «Excluir» MARCADO, e isso é a peça do desenho,
 *  não um detalhe: numa conta que só consulta, "somente os que ele criou" não
 *  restringe nada — restringiria uma escrita que ela não tem. Mostrar assim
 *  mesmo somaria mais um controle a cada um dos 15 recursos de um modal que já
 *  tem 66 caixinhas, e cada um deles seria uma pergunta sem consequência. É a
 *  mesma economia que faz este modal abrir com as seções fechadas.
 *
 *  Rádio, e não interruptor: são dois estados NOMEADOS, e o padrão — "Todos os
 *  registros" — precisa estar escrito. Um interruptor "só os próprios" deixaria
 *  o administrador adivinhando o que significa desligá-lo. */
function Alcance({
  recurso, rotulo, verbos, opcoes, valor, travado, onChange,
}: {
  recurso: string;
  rotulo: string;
  /** Os verbos de escrita MARCADOS ("Editar e Excluir"): é sobre eles, e só
   *  sobre eles, que esta escolha manda. */
  verbos: string;
  /** As duas opções, com rótulo e explicação — vindas do catálogo da API.
   *  Nenhum texto de permissão é escrito nesta tela. */
  opcoes: EscopoOpcao[];
  valor: Escopo;
  /** Quem edita alcança só o próprio trabalho neste módulo. O servidor recusa
   *  (403) que essa pessoa defina o alcance de outra ali — ninguém devolve um
   *  alcance que ele mesmo não tem. */
  travado: boolean;
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
              /* O `name` é por RECURSO: sem ele os rádios de Gestão Interna e os
                 de RM seriam um grupo só, e escolher num módulo mudaria o
                 outro. */
              name={`escopo-${recurso}`}
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
          não define o alcance de outra pessoa aqui.
        </span>
      )}
    </div>
  );
}

export default function PermissoesModal({
  alvo, catalogo, minhas, concedidas, escopos, souEu, onFechar, onSalvo,
}: {
  alvo: AlvoPermissoes;
  catalogo: Catalogo;
  /** O que QUEM EDITA pode. `null` = não deu para carregar, e aí tudo trava:
   *  sem saber o que o editor tem, não há como dizer o que ele pode conceder. */
  minhas: MinhasPermissoes | null;
  /** As caixinhas marcadas HOJE no alvo — o estado contra o qual o diff é feito. */
  concedidas: string[];
  /** O alcance gravado HOJE, por módulo. Módulo ausente = padrão (`todos`). */
  escopos: MapaEscopos;
  souEu: boolean;
  onFechar: () => void;
  onSalvo: () => void | Promise<void>;
}) {
  const original = useMemo(() => new Set(concedidas), [concedidas]);
  const [sel, setSel] = useState<Set<string>>(() => new Set(concedidas));
  const escOriginal = useMemo(() => ({ ...escopos }), [escopos]);
  const [esc, setEsc] = useState<MapaEscopos>(() => ({ ...escopos }));
  // Todas fechadas ao abrir — ver a decisão 1 no cabeçalho.
  const [abertas, setAbertas] = useState<Set<string>>(new Set());
  const [salvando, setSalvando] = useState(false);

  /** Os módulos onde o alcance por autor existe de verdade — quem responde é a
   *  API, e não uma lista escrita aqui (ver `recursosComEscopo`). */
  const comEscopo = useMemo(() => recursosComEscopo(catalogo), [catalogo]);
  const opcoesEscopo: EscopoOpcao[] = catalogo.escopos?.opcoes ?? [];

  /** ⚠️ ANTI-ESCALONAMENTO DO ALCANCE, e ele NÃO é o mesmo das caixinhas.
   *
   *  Nas caixinhas a pergunta é "você tem esta permissão?". Aqui é outra:
   *  quem já está restrito a `proprios` num módulo não define o alcance de
   *  ninguém ali — senão a saída da própria restrição seria conceder a si mesmo
   *  por interposta pessoa. É palavra por palavra o que o servidor recusa com
   *  403 em `_barrar_escalonamento_escopo`, e a tela existe para o limite ser
   *  entendido antes do clique. Super-admin não cai aqui: o backend devolve
   *  `todos` para ele em todos os módulos. */
  const alcanceTravado = (recurso: string) =>
    !minhas || escopoDe(minhas.escopos, recurso) !== "todos";

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
  const alcanceMudou = [...comEscopo].filter(
    (r) => escopoDe(esc, r) !== escopoDe(escOriginal, r),
  );
  const mudou = aConceder.length > 0 || aRetirar.length > 0 || alcanceMudou.length > 0;
  /* Uma frase só para os dois lugares que contam o mesmo diff (o cabeçalho do
     resumo e o rodapé). O alcance entra nela porque é a única alteração que não
     mexe em caixinha nenhuma: sem essa parcela, mudar só o alcance escreveria
     "0 a conceder · 0 a retirar" ao lado de um botão de salvar aceso. */
  const diffEmPalavras =
    `${aConceder.length} a conceder · ${aRetirar.length} a retirar`
    + (alcanceMudou.length ? ` · ${alcanceMudou.length} alcance(s) alterado(s)` : "");

  const linhas = resumoPorRecurso(catalogo, sel, undefined, esc);
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
      /* Vai o mapa INTEIRO dos módulos que aceitam alcance, inclusive os que
         ficaram em `todos` e inclusive aqueles cujas caixinhas de escrita estão
         desmarcadas agora. Mandar só o que está restrito faria o servidor não
         distinguir "voltou para todos" de "não foi tocado" — e o padrão, que é
         o que não restringe, nunca conseguiria ser reposto. */
      const escopoFinal: MapaEscopos = {};
      for (const r of comEscopo) escopoFinal[r] = escopoDe(esc, r);
      await salvarPermissoes(alvo.id, [...sel], escopoFinal);
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
            sub={mudou ? `${diffEmPalavras} — ainda não salvo` : "Igual ao que está gravado hoje."}
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
              {/* ⚠️ O alcance precisa de frase PRÓPRIA, e é a única coisa neste
                  modal que precisa: as caixinhas em modo aviso não mudam nada
                  na tela, então ninguém se engana. O alcance muda — os botões
                  de editar e excluir somem da lista no instante em que isto é
                  salvo. Sem esta linha, o administrador confere visualmente que
                  "funcionou" e conclui que a restrição está valendo, quando o
                  servidor ainda deixa passar quem chamar a API por fora. */}
              {" "}Isso vale também para o <b>alcance</b>: os botões de editar e
              excluir já somem da lista de quem for restringido, mas a recusa de
              verdade só acontece com a trava ligada.
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
                  {s.recursos.map((r) => {
                    // As caixinhas de escrita por linha (Editar, Excluir) que
                    // estao MARCADAS agora: são elas que dão sentido à escolha
                    // de alcance, e são elas que decidem se ela aparece.
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
                      {escritasLinha.length > 0 && opcoesEscopo.length > 0 && (
                        <Alcance
                          recurso={r.recurso}
                          rotulo={r.recurso_rotulo}
                          verbos={escritasLinha.map((p) => p.verbo_rotulo).join(" e ")}
                          opcoes={opcoesEscopo}
                          valor={escopoDe(esc, r.recurso)}
                          travado={alcanceTravado(r.recurso)}
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
      </ModalCorpo>

      {/* Rodapé fixo: com nove seções abertas a lista é longa, e um botão de
          salvar no fim dela é um botão que ninguém acha. */}
      <div
        className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-4 py-3"
        style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface)" }}
      >
        <span className="mr-auto text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {mudou ? diffEmPalavras : "Nada alterado."}
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
