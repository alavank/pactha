"use client";
// OS MODELOS DE PERMISSAO — a receita, e a tela que a mantem.
//
// ⚠️ UM MODELO NAO E UM GRUPO. Ninguem "pertence" a um modelo, e nenhuma conta
// muda porque um modelo mudou: aplicar COPIA as caixinhas para a pessoa naquele
// instante. Esta tela repete isso em tres momentos — no cabecalho, ao editar e
// ao apagar —, e a repeticao e proposital: quem administra prefeitura conhece
// "grupo de usuarios" de outros sistemas e vai supor heranca se nada disser o
// contrario. Supondo heranca, ele deixa de conferir o cadastro individual, que e
// o unico lugar onde a resposta mora.
//
// QUEM PODE MEXER: quem tem a caixinha `usuarios.modelos` (ver `lib/modelos.ts`,
// onde a escolha esta justificada). Criar molde nao concede nada a ninguem — a
// aplicacao continua limitada ao que quem aplica possui, aqui e no servidor —,
// mas PAUTA o que os outros administradores vao conceder, e por isso nao vem de
// brinde com a caixinha de conceder.
import { useCallback, useMemo, useState } from "react";
import {
  Copy, Loader2, Pencil, Plus, ShieldCheck, Trash2,
} from "lucide-react";
import {
  Bloco, BlocoHead, BOTAO_ACAO, BOTAO_CTA, BOTAO_SEC, ESTILO_CTA, ESTILO_SEC,
  ItemLinha, Lista, Modal, ModalCorpo, ModalHead, Selo, Vazio,
} from "@/components/ui/superficies";
import { Input } from "@/components/ui/input";
import type { MapaEscopos } from "@/lib/escopo";
import {
  alcanceTravadoPara, escopoDe, podeChave, recursosComEscopo, resumoPorRecurso,
  type Catalogo, type MinhasPermissoes,
} from "@/lib/permissoes";
import {
  apagarModelo, criarModelo, salvarModelo,
  type Modelo, type ModeloEntrada,
} from "@/lib/modelos";
import SeletorPermissoes from "./SeletorPermissoes";

/** As tres regras do molde, escritas. Ficam em cinza e sem fundo de alerta: e a
 *  regra normal do sistema, e nao um problema. */
function ComoFunciona() {
  return (
    <Bloco className="p-3">
      <BlocoHead
        icon={Copy}
        titulo="Modelo é molde, não é grupo"
        sub="Ele existe para ninguém precisar marcar 66 caixinhas a cada cadastro."
      />
      <ul className="flex flex-col gap-1.5 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
        {[
          <>
            Aplicar um modelo <b style={{ color: "var(--bi-text)" }}>copia</b> as
            caixinhas para a pessoa naquele instante. As caixinhas continuam
            editáveis e nada é salvo antes de o administrador conferir.
          </>,
          <>
            Depois de aplicado, <b style={{ color: "var(--bi-text)" }}>o vínculo acaba</b>:
            mudar ou apagar o modelo não altera ninguém que já o recebeu.
          </>,
          <>
            A resposta para “o que esta pessoa pode?” continua estando{" "}
            <b style={{ color: "var(--bi-text)" }}>no cadastro dela</b> — o modelo
            é só o caminho mais curto até lá.
          </>,
        ].map((linha, i) => (
          /* Marcador escrito à mão: o reset de CSS do projeto tira o
             `list-style`, e sem ele as três regras viram um parágrafo só. */
          <li key={i} className="flex gap-1.5">
            <span aria-hidden style={{ color: "var(--bi-faint)" }}>·</span>
            <span className="min-w-0">{linha}</span>
          </li>
        ))}
      </ul>
    </Bloco>
  );
}

/** O EDITOR de um molde. Exportado porque o modal de permissões também o abre —
 *  é o caminho "configurei esta pessoa inteira, guarda isso como modelo". */
export function ModeloEditor({
  catalogo, minhas, modelo, inicial, nivel = 2, onFechar, onSalvo,
  ufsCarteira = [],
}: {
  catalogo: Catalogo;
  minhas: MinhasPermissoes | null;
  /** `null` = criar. */
  modelo: Modelo | null;
  /** Semente para o modelo NOVO — as caixinhas de onde ele foi chamado. */
  inicial?: { nome?: string; permissoes: string[]; escopos: MapaEscopos };
  nivel?: 1 | 2;
  onFechar: () => void;
  onSalvo: (m: Modelo) => void | Promise<void>;
  /** Os estados da carteira, só para AGRUPAR a árvore por estado — o recorte
   *  já veio feito no `catalogo`. Vazio = não agrupa. */
  ufsCarteira?: string[];
}) {
  const base = modelo ?? inicial ?? { permissoes: [], escopos: {} as MapaEscopos };
  const [nome, setNome] = useState(modelo?.nome ?? inicial?.nome ?? "");
  const [descricao, setDescricao] = useState(modelo?.descricao ?? "");
  const [sel, setSel] = useState<Set<string>>(() => new Set(base.permissoes));
  const [esc, setEsc] = useState<MapaEscopos>(() => ({ ...base.escopos }));
  const [salvando, setSalvando] = useState(false);

  const comEscopo = useMemo(() => recursosComEscopo(catalogo), [catalogo]);
  const posso = useCallback((chave: string) => podeChave(minhas, chave), [minhas]);
  const travado = useCallback(
    (recurso: string) => alcanceTravadoPara(minhas, recurso),
    [minhas],
  );

  const original = useMemo(() => new Set(base.permissoes), [base.permissoes]);
  const mudou =
    nome.trim() !== (modelo?.nome ?? inicial?.nome ?? "").trim()
    || descricao.trim() !== (modelo?.descricao ?? "").trim()
    || sel.size !== original.size
    || [...sel].some((c) => !original.has(c))
    || [...comEscopo].some((r) => escopoDe(esc, r) !== escopoDe(base.escopos, r));

  const salvar = async () => {
    if (!nome.trim()) return;
    setSalvando(true);
    try {
      /* Vai o mapa INTEIRO dos módulos que aceitam alcance, inclusive os que
         ficaram no padrão: mandar só o que está restrito faria "voltou para
         todos" ser indistinguível de "não foi tocado". Mesma regra do PUT de
         permissões do usuário. */
      const escopos: MapaEscopos = {};
      for (const r of comEscopo) escopos[r] = escopoDe(esc, r);
      const dados: ModeloEntrada = {
        nome: nome.trim(), descricao: descricao.trim(),
        permissoes: [...sel], escopos,
      };
      const salvo = modelo ? await salvarModelo(modelo.id, dados) : await criarModelo(dados);
      await onSalvo(salvo);
      onFechar();
    } catch (e: unknown) {
      alert(
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Erro ao salvar o modelo",
      );
    } finally {
      setSalvando(false);
    }
  };

  return (
    <Modal
      aberto
      nivel={nivel}
      maxW="max-w-2xl"
      onFechar={onFechar}
      podeFechar={() => !mudou || confirm("Descartar as alterações deste modelo?")}
    >
      <ModalHead
        titulo={modelo ? `Editar modelo: ${modelo.nome}` : "Novo modelo de permissão"}
        sub={
          modelo
            ? "Mexer aqui não altera ninguém: quem já recebeu este modelo ficou com uma cópia das caixinhas."
            : "Uma receita de permissões para os próximos cadastros. Ela não concede nada sozinha."
        }
        onFechar={onFechar}
        right={
          <span className="bi-num text-[13px]" title="Caixinhas marcadas neste modelo">
            {sel.size}/{catalogo.total}
          </span>
        }
      />
      <ModalCorpo className="space-y-2.5">
        <Bloco className="p-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Nome do modelo
              </label>
              <Input
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex.: Operação da Gestão Interna"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px]" style={{ color: "var(--bi-muted)" }}>
                Para quem serve
              </label>
              <Input
                value={descricao ?? ""}
                onChange={(e) => setDescricao(e.target.value)}
                placeholder="Uma frase que o gestor reconheça"
              />
            </div>
          </div>
          <p className="mt-2 text-[10px] leading-snug" style={{ color: "var(--bi-faint)" }}>
            O nome aparece na hora de cadastrar alguém, e é por ele que o
            administrador escolhe. Nome que descreve o trabalho da pessoa
            (“quem só consulta”) funciona melhor do que nome de cargo.
          </p>
        </Bloco>

        {/* A mesma árvore de caixinhas do cadastro de pessoa — a peça é
            compartilhada de propósito: um modelo que oferecesse permissões que
            a tela de usuário não desenha seria uma segunda regra de permissão
            escrita em outro lugar. */}
        <SeletorPermissoes
          catalogo={catalogo}
          ufsCarteira={ufsCarteira}
          sel={sel}
          setSel={setSel}
          esc={esc}
          setEsc={setEsc}
          posso={posso}
          alcanceTravado={travado}
          contexto="modelo"
        />
      </ModalCorpo>

      <div
        className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-4 py-3"
        style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface)" }}
      >
        <span className="mr-auto text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {sel.size === 0
            ? "Nenhuma caixinha: aplicar este modelo zera as permissões da pessoa."
            : `${sel.size} caixinha(s) neste modelo.`}
        </span>
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC} onClick={onFechar}>
          Cancelar
        </button>
        <button
          type="button"
          className={BOTAO_CTA}
          style={ESTILO_CTA}
          onClick={salvar}
          disabled={salvando || !nome.trim() || !mudou || !minhas}
          title={!nome.trim() ? "Dê um nome ao modelo." : undefined}
        >
          {salvando ? <Loader2 className="size-4 animate-spin" /> : <Copy className="size-4" />}
          Salvar modelo
        </button>
      </div>
    </Modal>
  );
}

export default function ModelosModal({
  catalogo, minhas, modelos, carregando, onFechar, onMudou, ufsCarteira = [],
}: {
  catalogo: Catalogo;
  minhas: MinhasPermissoes | null;
  modelos: Modelo[];
  carregando?: boolean;
  onFechar: () => void;
  /** Quem relê a lista é a PÁGINA: ela é a dona, e o modal de permissões
   *  recebe dela a mesma lista. Duas releituras — uma aqui e outra lá — dariam
   *  duas listas ligeiramente diferentes na mesma tela. */
  onMudou: () => void | Promise<void>;
  /** Repassado ao editor: os estados da carteira agrupam a árvore. */
  ufsCarteira?: string[];
}) {
  const [editando, setEditando] = useState<Modelo | null>(null);
  const [criando, setCriando] = useState(false);
  const [apagando, setApagando] = useState<number | null>(null);

  const apagar = async (m: Modelo) => {
    const ok = confirm(
      `Apagar o modelo «${m.nome}»?\n\n`
      + "Ninguém perde permissão: quem já recebeu estas caixinhas ficou com uma "
      + "cópia delas no próprio cadastro. O que some é a receita.",
    );
    if (!ok) return;
    setApagando(m.id);
    try {
      await apagarModelo(m.id);
      await onMudou();
    } catch (e: unknown) {
      alert(
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Erro ao apagar o modelo",
      );
    } finally {
      setApagando(null);
    }
  };

  return (
    <>
      <Modal aberto maxW="max-w-3xl" onFechar={onFechar}>
        <ModalHead
          titulo="Modelos de permissão"
          sub="Moldes prontos para o cadastro de gente nova sair em um clique — e continuar conferível pessoa a pessoa."
          onFechar={onFechar}
          right={
            <button
              type="button"
              className={BOTAO_CTA}
              style={ESTILO_CTA}
              onClick={() => setCriando(true)}
            >
              <Plus className="size-4" />
              Novo modelo
            </button>
          }
        />
        <ModalCorpo className="space-y-2.5">
          <ComoFunciona />

          <Bloco className="p-3">
            <BlocoHead
              icon={ShieldCheck}
              titulo="Modelos cadastrados"
              sub={carregando ? "Carregando..." : `${modelos.length} modelo(s).`}
              right={carregando ? undefined : (
                <span className="bi-num text-[13px]">{modelos.length}</span>
              )}
            />
            {carregando ? (
              <Lista>
                {Array.from({ length: 3 }).map((_, i) => (
                  <li key={i} className="bi-card-flat h-[72px] animate-pulse" />
                ))}
              </Lista>
            ) : modelos.length === 0 ? (
              <Vazio>
                Nenhum modelo cadastrado. Sem eles, cada cadastro novo continua
                sendo 66 caixinhas marcadas à mão.
              </Vazio>
            ) : (
              <Lista>
                {modelos.map((m) => {
                  const linhas = resumoPorRecurso(
                    catalogo, new Set(m.permissoes), undefined, m.escopos,
                  );
                  return (
                    <ItemLinha
                      key={m.id}
                      titulo={
                        <span className="flex flex-wrap items-center gap-1.5">
                          <span className="truncate">{m.nome}</span>
                          <Selo title="Caixinhas que este modelo marca.">
                            {m.permissoes.length} caixinha(s)
                          </Selo>
                        </span>
                      }
                      meta={m.descricao || "Sem descrição."}
                      acao={
                        <>
                          <button
                            type="button"
                            className={BOTAO_ACAO}
                            style={ESTILO_SEC}
                            onClick={() => setEditando(m)}
                            title="Editar este modelo"
                          >
                            <Pencil className="size-3" /> Editar
                          </button>
                          <button
                            type="button"
                            className={BOTAO_ACAO}
                            style={ESTILO_SEC}
                            onClick={() => apagar(m)}
                            disabled={apagando === m.id}
                            title="Apagar este modelo"
                            aria-label={`Apagar o modelo ${m.nome}`}
                          >
                            {apagando === m.id
                              ? <Loader2 className="size-3 animate-spin" />
                              : <Trash2 className="size-3" />}
                          </button>
                        </>
                      }
                    >
                      <p
                        className="mt-1.5 border-t pt-1.5 text-[11px] leading-snug"
                        style={{ borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}
                      >
                        {linhas.length ? linhas.join(" · ") : "Nenhuma caixinha marcada."}
                      </p>
                    </ItemLinha>
                  );
                })}
              </Lista>
            )}
          </Bloco>
        </ModalCorpo>
      </Modal>

      {(criando || editando) && (
        <ModeloEditor
          catalogo={catalogo}
          ufsCarteira={ufsCarteira}
          minhas={minhas}
          modelo={editando}
          onFechar={() => { setCriando(false); setEditando(null); }}
          onSalvo={onMudou}
        />
      )}
    </>
  );
}
