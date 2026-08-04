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
//   4. APLICAR MODELO, que chegou depois e parece contradizer a decisão 3 — um
//      clique que preenche quarenta caixinhas. A diferença é o que está sendo
//      oferecido: "marcar tudo" é o conjunto MÁXIMO, anônimo e sem autor;
//      um modelo é um conjunto NOMEADO, escrito por alguém, e esta tela mostra
//      por inteiro o que ele marca e o que ele desmarca ANTES do clique. O
//      atalho que faltava é o que economiza o trabalho sem economizar a
//      decisão; o que não existe é o que economiza a decisão.
//
// ⚠️ ANTI-ESCALONAMENTO. O que quem edita não possui aparece TRAVADO, com a
// explicação escrita. Não é enfeite de tela: `routers/permissoes.py::conceder`
// barra a mesma coisa no servidor, e barra nos dois modos de `AUTHZ_MODO`. A
// tela existe para o limite ser entendido antes do clique — e não descoberto
// num 403 depois de dez minutos marcando caixinha.
//
// ⚠️ Nenhuma lista de permissão mora aqui. Tudo vem do catálogo da API — ver o
// cabeçalho de `lib/permissoes.ts`.
//
// ⚠️ E nem a ÁRVORE de caixinhas mora aqui: ela é `SeletorPermissoes`, dividida
// com o editor de modelos. Duas árvores parecidas divergiriam, e a divergência
// apareceria como um modelo capaz de conceder algo que esta tela nem desenha.
import { useCallback, useMemo, useState } from "react";
import { AlertTriangle, Check, Loader2, Lock, ShieldCheck } from "lucide-react";
import {
  Aviso, Bloco, BlocoHead, BOTAO_CTA, BOTAO_SEC, ESTILO_CTA,
  ESTILO_SEC, Modal, ModalCorpo, ModalHead, Selo,
} from "@/components/ui/superficies";
import { ehSomenteLeitura, ehSuperAdmin } from "@/lib/conta";
import type { MapaEscopos } from "@/lib/escopo";
import {
  alcanceTravadoPara, escopoDe, podeChave, recursosComEscopo,
  resumoPorRecurso, salvarPermissoes,
  type Catalogo, type MinhasPermissoes,
} from "@/lib/permissoes";
import { podeGerirModelos, type Modelo } from "@/lib/modelos";
import SeletorPermissoes from "./SeletorPermissoes";
import AplicarModelo from "./AplicarModelo";
import { ModeloEditor } from "./ModelosModal";

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
  alvo, catalogo, minhas, concedidas, escopos, souEu, modelos, podeGerirModelo,
  onModeloCriado, onFechar, onSalvo,
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
  /** Os moldes disponíveis. Lista vazia = nenhum cadastrado (ou a chamada
   *  falhou): o bloco de aplicar aparece do mesmo jeito, dizendo isso. */
  modelos: Modelo[];
  /** Quem pode criar molde — respondido pelo servidor (`pode_gerenciar`), e não
   *  deduzido aqui. Decide só o botão «Salvar como modelo»: APLICAR continua
   *  valendo para quem concede permissão. */
  podeGerirModelo?: boolean;
  /** A página é dona da lista — daqui só se CRIA um modelo a partir das
   *  caixinhas já marcadas, e quem relê a lista é ela. */
  onModeloCriado?: () => void | Promise<void>;
  onFechar: () => void;
  onSalvo: () => void | Promise<void>;
}) {
  const original = useMemo(() => new Set(concedidas), [concedidas]);
  const [sel, setSel] = useState<Set<string>>(() => new Set(concedidas));
  const escOriginal = useMemo(() => ({ ...escopos }), [escopos]);
  const [esc, setEsc] = useState<MapaEscopos>(() => ({ ...escopos }));
  const [salvando, setSalvando] = useState(false);
  // "Salvar como modelo": o editor abre em cima deste modal (nível 2) com as
  // caixinhas de agora. Não fecha nada nem perde o que está marcado.
  const [virarModelo, setVirarModelo] = useState(false);
  /* DE ONDE ESTE SALVAR PARTIU — só para a trilha, e não é vínculo: não há
     coluna ligando pessoa a modelo. Continua valendo depois de o administrador
     ajustar as caixinhas na mão (o normal é elas diferirem do molde); some se
     ele desfizer a aplicação, porque aí não partiu de molde nenhum. */
  const [origem, setOrigem] = useState<{ modeloId: number; modo: string } | null>(null);

  /** Os módulos onde o alcance por autor existe de verdade — quem responde é a
   *  API, e não uma lista escrita aqui (ver `recursosComEscopo`). */
  const comEscopo = useMemo(() => recursosComEscopo(catalogo), [catalogo]);

  const alcanceTravado = useCallback(
    (recurso: string) => alcanceTravadoPara(minhas, recurso),
    [minhas],
  );

  const alvoSuper = ehSuperAdmin(alvo);
  const alvoLeitura = ehSomenteLeitura(alvo);

  const posso = useCallback((chave: string) => podeChave(minhas, chave), [minhas]);

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
      await salvarPermissoes(alvo.id, [...sel], escopoFinal, origem ?? undefined);
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
    <>
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

        {/* O MOLDE, no topo — o atalho que evita as 66 caixinhas à mão.
            Só com `minhas` carregado: sem saber o que quem edita tem, tudo está
            travado e aplicar um modelo não moveria caixinha nenhuma. */}
        {minhas && (
          <AplicarModelo
            catalogo={catalogo}
            modelos={modelos}
            sel={sel}
            esc={esc}
            posso={posso}
            alcanceTravado={alcanceTravado}
            onAplicar={(novaSel, novoEsc, de) => {
              setSel(novaSel); setEsc(novoEsc); setOrigem(de);
            }}
            onDesfazer={(velhaSel, velhoEsc) => {
              setSel(velhaSel); setEsc(velhoEsc); setOrigem(null);
            }}
            onSalvarComoModelo={
              (podeGerirModelo ?? podeGerirModelos(minhas))
                ? () => setVirarModelo(true)
                : undefined
            }
          />
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

        {/* A ÁRVORE — a mesma peça que o editor de modelo usa. */}
        <SeletorPermissoes
          catalogo={catalogo}
          sel={sel}
          setSel={setSel}
          esc={esc}
          setEsc={setEsc}
          posso={posso}
          alcanceTravado={alcanceTravado}
          contexto="usuario"
          seloDe={(p) =>
            /* Só onde a distinção MUDA o resultado: numa conta em somente
               leitura, a caixinha de escrita fica guardada e não vale. Marcar
               todas as 30 de escrita em toda conta seria ruído. */
            alvoLeitura && p.escrita ? (
              <Selo title="A trava de somente leitura da conta barra esta ação.">
                não vale nesta conta
              </Selo>
            ) : null
          }
        />
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

    {/* «Salvar como modelo»: o caminho de criação a partir de um cadastro que
        já ficou bom. Nível 2 — este modal continua aberto por baixo, e o que
        está marcado aqui não se perde.
        ⚠️ Guardar o molde NÃO salva as permissões desta pessoa: são duas
        gravações diferentes, e o botão «Salvar permissões» continua sendo o
        único que mexe na conta. */}
    {virarModelo && (
      <ModeloEditor
        catalogo={catalogo}
        minhas={minhas}
        modelo={null}
        inicial={{ permissoes: [...sel], escopos: esc }}
        onFechar={() => setVirarModelo(false)}
        onSalvo={async () => { await onModeloCriado?.(); }}
      />
    )}
    </>
  );
}
