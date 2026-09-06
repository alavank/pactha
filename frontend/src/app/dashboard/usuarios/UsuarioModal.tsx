"use client";
// ⭐⭐ O MODAL ÚNICO — cadastro e permissão numa passada só.
//
// ERAM TRÊS GESTOS até 05/09/2026: o card «Novo usuário» (nome/e-mail/perfil),
// o modal «Acesso» (municípios + telas) e o modal «Permissões» (as caixinhas de
// ação). Cadastrar alguém era preencher um, salvar, procurar a pessoa na lista,
// abrir o segundo, salvar, abrir o terceiro. O dono pediu um só.
//
// AS QUATRO DECISÕES QUE SOBREVIVERAM DO MODAL ANTIGO, e cada uma existe para
// evitar o mesmo desfecho — o administrador desistir e conceder tudo:
//
//   1. GRUPOS FECHADOS ao abrir. A árvore tem ~43 telas e ~96 caixinhas; aberta
//      inteira, ninguém lê. Fechado, cada grupo já responde o que interessa.
//   2. MARCAR/LIMPAR POR GRUPO. O gesto que o administrador quer fazer ("essa
//      pessoa cuida de convênios") é por assunto, e não caixinha a caixinha.
//   3. ANTI-ESCALONAMENTO DESENHADO. O que quem edita não possui aparece
//      travado, com a explicação escrita — o servidor barra a mesma coisa
//      (`routers/permissoes.py::_barrar_escalonamento`), e descobrir o limite
//      num 403 depois de dez minutos marcando caixinha é o pior jeito.
//   4. «Liberar todas as telas» EXISTE, e é a diferença deste modal para o
//      antigo — que recusava um "marcar tudo" global de propósito. Aqui ele é
//      o atalho que sobrou depois que os MODELOS de permissão foram removidos a
//      pedido do dono; e ele libera as TELAS, não as ações, que continuam
//      exigindo decisão. O atalho que economiza trabalho sem economizar a
//      decisão.
//
// ⚠️ O QUE SUBSTITUIU OS MOLDES: «Copiar de outro usuário». O dono foi
// explícito — "prefiro mais ainda a forma de criar na mao um a um, e uma forma
// que eu quero pra facilitar é (...) copiar as permissao iguais a de um outro
// usuario". A diferença para um molde é que aqui a origem é uma PESSOA
// concreta, que se pode conferir, e não uma receita anônima reaplicável.
//
// ⚠️ NENHUMA LISTA DE PERMISSÃO MORA AQUI. A estrutura vem de `lib/menu.ts` e as
// ações de `GET /api/permissoes/catalogo` — ver `lib/arvorePermissoes.ts`.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Check, ChevronDown, ChevronRight, CopyPlus,
  Loader2, Lock, Search, ShieldCheck,
} from "lucide-react";
import api from "@/lib/api";
import {
  AcaoMini, Aviso, Bloco, BOTAO_CTA, BOTAO_SEC, ESTILO_CTA, ESTILO_SEC,
  Modal, ModalCorpo, ModalHead, Selo,
} from "@/components/ui/superficies";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { ehSuperAdmin } from "@/lib/conta";
import type { Escopo, MapaEscopos } from "@/lib/escopo";
import {
  acoesDaArvore, arvoreDoMenu, corDoGrupo, telasDaArvore,
  type GrupoNaArvore, type TelaNaArvore,
} from "@/lib/arvorePermissoes";
import {
  alcanceTravadoPara, escopoDe, podeChave, recursosComEscopo,
  type Catalogo, type MinhasPermissoes,
} from "@/lib/permissoes";

export interface UsuarioAlvo {
  id: number;
  email: string;
  name: string;
  role: string;
  funcao?: string | null;
  whatsapp?: string | null;
  active: boolean;
  municipio_ids?: number[];
  telas?: string[];
  super_admin?: boolean | null;
}

interface Municipio { id: number; nome: string; uf: string; }
interface Perfil { value: string; label: string; }

/** Máscara BR de telefone, aplicada enquanto se digita.
 *
 *  ⚠️ SÓ NA TELA. O que vai para a API é o texto como ficou — o backend guarda
 *  o que a pessoa digitou, sem normalizar, porque normalizar número de telefone
 *  é decisão de quem for DISPARAR, e fazê-lo aqui esconderia de quem confere o
 *  que foi realmente cadastrado. */
function mascaraWhatsapp(bruto: string): string {
  const d = (bruto || "").replace(/\D/g, "").slice(0, 11);
  if (d.length <= 2) return d;
  if (d.length <= 6) return `(${d.slice(0, 2)}) ${d.slice(2)}`;
  if (d.length <= 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
}

/** Rótulo de controle: 11px em `--bi-muted`, a mesma escala do resto do lote. */
function Rotulo({ children, right }: {
  children: React.ReactNode;
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-1 flex items-center justify-between gap-2">
      <label className="text-[11px]" style={{ color: "var(--bi-muted)" }}>{children}</label>
      {right}
    </div>
  );
}

/** O chip de marcação dos municípios. */
function Chip({ on, onClick, children }: {
  on: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors hover:bg-[var(--bi-surface-2)]"
      style={on
        ? { borderColor: "var(--bi-accent-ink)", background: "var(--bi-surface-2)",
            color: "var(--bi-accent-ink)", fontWeight: 500 }
        : { borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}
    >
      {on && <Check className="size-3" />}
      {children}
    </button>
  );
}

/** ⭐ O INTERRUPTOR DE ACESSO de uma tela.
 *
 *  Interruptor e não caixinha, de propósito: ele não é mais uma ação na lista —
 *  é o que decide se a lista aparece. A distinção visual é o que faz a
 *  hierarquia Tela › Ação ser legível de relance. */
function Interruptor({ on, onToggle, rotulo }: {
  on: boolean; onToggle: () => void; rotulo: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={`Acesso a ${rotulo}`}
      onClick={onToggle}
      className="relative inline-flex h-[18px] w-[32px] shrink-0 items-center rounded-full transition-colors"
      style={{ background: on ? "var(--bi-cta)" : "var(--bi-line)" }}
    >
      <span
        className="inline-block size-[14px] rounded-full bg-white transition-transform"
        style={{ transform: on ? "translateX(16px)" : "translateX(2px)" }}
      />
    </button>
  );
}

export default function UsuarioModal({
  alvo, catalogo, minhas, municipios, perfis, telasDoAmbiente,
  concedidas, escopos, souEu, podeConceder, outros, permsDe, telasDe,
  municipiosDe, onFechar, onSalvo,
}: {
  /** `null` = criação. */
  alvo: UsuarioAlvo | null;
  catalogo: Catalogo;
  minhas: MinhasPermissoes | null;
  municipios: Municipio[];
  perfis: Perfil[];
  /** As telas que ESTE ambiente oferece (já recortadas por UF). */
  telasDoAmbiente: Set<string> | null;
  concedidas: string[];
  escopos: MapaEscopos;
  souEu: boolean;
  /** ⭐ Quem edita tem `usuarios.conceder`? É a MESMA chave que o servidor
   *  cobra em `POST`/`PATCH /api/users` quando o corpo traz telas, municípios
   *  ou permissões. Sem ela a seção 3 inteira fica travada, com a explicação —
   *  em vez de deixar o administrador marcar trinta caixinhas e levar um 403 no
   *  Salvar. Cadastrar a PESSOA (nome, e-mail, perfil) continua liberado: é o
   *  fluxo legítimo de "cadastro agora, acesso depois". */
  podeConceder: boolean;
  /** Candidatos a origem do «Copiar de outro usuário». */
  outros: UsuarioAlvo[];
  permsDe: (u: UsuarioAlvo) => string[];
  telasDe: (u: UsuarioAlvo) => string[];
  municipiosDe: (u: UsuarioAlvo) => number[];
  onFechar: () => void;
  onSalvo: () => void | Promise<void>;
}) {
  const editando = alvo !== null;

  // --- Seção 1: dados -----------------------------------------------------
  const [nome, setNome] = useState(alvo?.name ?? "");
  const [email, setEmail] = useState(alvo?.email ?? "");
  // ⭐ ABRE VAZIO na criação (pedido do dono). Antes nascia "user" preenchido, e
  // um default num campo que é só rótulo faz o administrador nem olhar para ele.
  // Vazio, ele escolhe — e o botão fica desabilitado até escolher.
  const [perfil, setPerfil] = useState(alvo?.role ?? "");
  const [funcao, setFuncao] = useState(alvo?.funcao ?? "");
  const [whatsapp, setWhatsapp] = useState(mascaraWhatsapp(alvo?.whatsapp ?? ""));
  const [ativo, setAtivo] = useState(alvo?.active ?? true);

  // --- Seção 2: municípios ------------------------------------------------
  const [munsSel, setMunsSel] = useState<Set<number>>(
    () => new Set(alvo?.municipio_ids ?? []));
  const [buscaMun, setBuscaMun] = useState("");

  // --- Seção 3: telas e ações ---------------------------------------------
  const [telasSel, setTelasSel] = useState<Set<string>>(
    () => new Set(alvo?.telas ?? []));
  const [acoesSel, setAcoesSel] = useState<Set<string>>(() => new Set(concedidas));
  const [esc, setEsc] = useState<MapaEscopos>(() => ({ ...escopos }));
  const [abertos, setAbertos] = useState<Set<string>>(new Set());
  const [buscaTela, setBuscaTela] = useState("");

  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [copiarDe, setCopiarDe] = useState<number | null>(null);

  /** Tenant de UM município (prefeitura): a seção de municípios não é
   *  renderizada e o vínculo é automático. A detecção é a CONTAGEM, e não um
   *  tipo de cliente configurado — assim ela acerta nos dois casos sem exigir
   *  configuração nova. Vazio NÃO é "um só", por isso o teste é por igualdade. */
  const municipioUnico = municipios.length === 1;

  const arvore = useMemo(
    () => arvoreDoMenu(catalogo, telasDoAmbiente), [catalogo, telasDoAmbiente]);
  const todasTelas = useMemo(() => telasDaArvore(arvore), [arvore]);
  const todasAcoes = useMemo(() => acoesDaArvore(arvore), [arvore]);
  const comEscopo = useMemo(() => recursosComEscopo(catalogo), [catalogo]);
  const opcoesEscopo = catalogo.escopos?.opcoes ?? [];

  // Duas travas, e as duas são as do servidor: `podeConceder` é a permissão de
  // mexer no acesso de alguém; `podeChave` é o anti-escalonamento (ninguém
  // concede o que não tem). Desenhar as duas aqui é o que faz o limite ser
  // entendido ANTES do clique, e não descoberto num 403 depois.
  const posso = useCallback(
    (c: string) => podeConceder && podeChave(minhas, c), [minhas, podeConceder]);
  const alcanceTravado = useCallback(
    (r: string) => alcanceTravadoPara(minhas, r), [minhas]);

  /** ⭐ «VER» É PRÉ-REQUISITO — a regra do dono, e ela vale nos dois sentidos.
   *
   *  Marcar qualquer ação marca «Ver» junto; desmarcar «Ver» desmarca as demais
   *  daquela tela. Sem isto sairiam contas com «Excluir» e sem «Ver» — que no
   *  servidor é uma pessoa que apaga o que não consegue abrir. */
  const ehVer = (v: string) => v === "ver" || v === "usar";

  const alternarAcao = (tela: TelaNaArvore, chave: string) => {
    const acao = tela.acoes.find((a) => a.chave === chave);
    if (!acao) return;
    // ⚠️ O PRÉ-REQUISITO É POR RECURSO, e não por tela. O Painel tem dois (o
    // painel e as «Vigências a vencer»): marcar «Exportar» das Vigências não
    // pode marcar o «Ver» do Painel — são concessões diferentes, e foi para
    // poder separá-las que `vigencias` virou recurso próprio.
    const verDoRecurso = tela.acoes.find(
      (a) => a.recurso === acao.recurso && ehVer(a.verbo))?.chave;
    setAcoesSel((prev) => {
      const n = new Set(prev);
      if (n.has(chave)) {
        n.delete(chave);
        // Desmarcar «Ver» leva junto as demais DO MESMO recurso: sem isso
        // sobraria «Excluir» sem «Ver» — no servidor, alguém que apaga o que
        // não consegue abrir.
        if (chave === verDoRecurso) {
          for (const a of tela.acoes) {
            if (a.recurso === acao.recurso && posso(a.chave)) n.delete(a.chave);
          }
        }
      } else {
        n.add(chave);
        if (verDoRecurso && posso(verDoRecurso)) n.add(verDoRecurso);
      }
      return n;
    });
  };

  /** Ligar/desligar o acesso a uma tela.
   *
   *  ⚠️ DESLIGAR NÃO APAGA AS MARCAÇÕES — elas ficam no estado local até salvar,
   *  e religar traz tudo de volta. É o pedido do documento, e a razão é a
   *  óbvia: desligar por engano uma tela com dez ações marcadas não pode custar
   *  dez cliques para desfazer. O que NÃO estiver com acesso ligado não é
   *  enviado (ver `salvar`). */
  const alternarTela = (tela: TelaNaArvore) => {
    setTelasSel((prev) => {
      const n = new Set(prev);
      if (n.has(tela.tela)) n.delete(tela.tela);
      else {
        n.add(tela.tela);
        // Ligar o acesso marca o «Ver» do recurso PRINCIPAL: é o mínimo que faz
        // o acesso significar alguma coisa, e é o que o servidor vai cobrar na
        // primeira rota. ⚠️ Só o principal — abrir o Painel não concede as
        // «Vigências a vencer», que são a segunda concessão daquela mesma tela.
        const principal = tela.recursos[0];
        const ver = tela.acoes.find(
          (a) => a.recurso === principal && ehVer(a.verbo));
        if (ver && posso(ver.chave)) {
          setAcoesSel((p) => new Set(p).add(ver.chave));
        }
      }
      return n;
    });
  };

  const marcarGrupo = (g: GrupoNaArvore, ligar: boolean) => {
    setTelasSel((prev) => {
      const n = new Set(prev);
      for (const t of g.telas) { if (ligar) n.add(t.tela); else n.delete(t.tela); }
      return n;
    });
    setAcoesSel((prev) => {
      const n = new Set(prev);
      for (const t of g.telas) {
        for (const a of t.acoes) {
          if (!posso(a.chave)) continue;
          // Marcar o grupo liga o ACESSO e o «Ver» — não as ações de escrita.
          // Um atalho que concedesse «Excluir» de dez telas de uma vez seria o
          // caminho mais curto da tela, e o caminho mais curto é o que as
          // pessoas usam.
          const marcaVer = ehVer(a.verbo);
          if (ligar) { if (marcaVer) n.add(a.chave); } else n.delete(a.chave);
        }
      }
      return n;
    });
  };

  const liberarTudo = (ligar: boolean) => {
    setTelasSel(new Set(ligar ? todasTelas : []));
    setAcoesSel((prev) => {
      const n = new Set(prev);
      for (const g of arvore) for (const t of g.telas) for (const a of t.acoes) {
        if (!posso(a.chave)) continue;
        if (ligar) { if (ehVer(a.verbo)) n.add(a.chave); } else n.delete(a.chave);
      }
      return n;
    });
  };

  /** «Marcar todas as ações nas telas liberadas» — o único atalho que concede
   *  escrita, e ele é EXPLÍCITO e alcança só o que já está liberado. */
  const marcarTodasAcoes = () => {
    setAcoesSel((prev) => {
      const n = new Set(prev);
      for (const g of arvore) for (const t of g.telas) {
        if (!telasSel.has(t.tela)) continue;
        for (const a of t.acoes) if (posso(a.chave)) n.add(a.chave);
      }
      return n;
    });
  };

  /** ⭐ COPIAR DE OUTRO USUÁRIO — o que substituiu os modelos de permissão. */
  const copiar = () => {
    const origem = outros.find((o) => o.id === copiarDe);
    if (!origem) return;
    if (!confirm(
      `Copiar o acesso de ${origem.name} para este usuário?\n\n`
      + `· ${telasDe(origem).length} tela(s)\n`
      + `· ${permsDe(origem).length} ação(ões)\n`
      + (municipioUnico ? "" : `· ${municipiosDe(origem).length} município(s)\n`)
      + "\nO que estiver marcado aqui é substituído. Nada é gravado até você "
      + "clicar em Salvar.",
    )) return;
    setTelasSel(new Set(telasDe(origem)));
    // ⚠️ SÓ O QUE QUEM COPIA PODE CONCEDER. O servidor recusa o resto
    // (`_barrar_escalonamento`), e propor na tela o que ele vai negar faria o
    // administrador descobrir o limite num 403 depois de confirmar.
    setAcoesSel(new Set(permsDe(origem).filter(posso)));
    if (!municipioUnico) setMunsSel(new Set(municipiosDe(origem)));
    setCopiarDe(null);
  };

  // --- Resumo e diff ------------------------------------------------------
  const telasLiberadas = todasTelas.filter((t) => telasSel.has(t)).length;
  const acoesMarcadas = todasAcoes.filter((a) => acoesSel.has(a)).length;
  const mudou = useMemo(() => {
    if (!editando) return nome.trim() !== "" || email.trim() !== "";
    const igual = (a: Set<string> | Set<number>, b: (string | number)[]) =>
      a.size === b.length && b.every((x) => (a as Set<unknown>).has(x));
    return nome !== alvo!.name || email !== alvo!.email || perfil !== alvo!.role
      || (funcao || "") !== (alvo!.funcao || "")
      || mascaraWhatsapp(whatsapp) !== mascaraWhatsapp(alvo!.whatsapp || "")
      || ativo !== alvo!.active
      || !igual(munsSel, alvo!.municipio_ids ?? [])
      || !igual(telasSel, alvo!.telas ?? [])
      || !igual(acoesSel, concedidas)
      || [...comEscopo].some((r) => escopoDe(esc, r) !== escopoDe(escopos, r));
  }, [editando, alvo, nome, email, perfil, funcao, whatsapp, ativo, munsSel,
      telasSel, acoesSel, esc, concedidas, escopos, comEscopo]);

  // Esc/clique fora só descartam com confirmação — marcar trinta caixinhas e
  // perdê-las num clique torto é o que faz o administrador não voltar à tela.
  const podeFechar = () =>
    !mudou || confirm("Descartar as alterações não salvas?");

  const emailValido = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());
  // Só cobra município de quem PODE definir município: para quem não pode, a
  // seção nem é enviada, e exigir escolha ali travaria o cadastro por uma
  // decisão que não é dele.
  const faltaMunicipio = podeConceder && !municipioUnico && munsSel.size === 0;
  const podeSalvar = nome.trim() !== "" && emailValido && perfil !== ""
    && !faltaMunicipio && !salvando;

  const salvar = async () => {
    setSalvando(true);
    setErro(null);
    try {
      // ⚠️ SÓ O QUE ESTÁ COM ACESSO LIGADO É PERSISTIDO. As marcações de uma
      // tela desligada ficaram no estado local (para religar sem perder), mas
      // gravá-las produziria uma pessoa com `rm.excluir` e sem a tela `rm` — o
      // tipo de estado que ninguém consegue explicar olhando o cadastro.
      const telasFinais = todasTelas.filter((t) => telasSel.has(t));
      const permitidas = new Set(
        arvore.flatMap((g) => g.telas)
          .filter((t) => telasSel.has(t.tela))
          .flatMap((t) => t.acoes.map((a) => a.chave)),
      );
      const acoesFinais = [...acoesSel].filter((a) => permitidas.has(a));
      // O mapa INTEIRO dos módulos que aceitam alcance, inclusive os que
      // ficaram no padrão: mandar só o restrito faria o servidor não distinguir
      // "voltou para todos" de "não foi tocado", e o padrão nunca seria reposto.
      const escopoFinal: MapaEscopos = {};
      for (const r of comEscopo) escopoFinal[r] = escopoDe(esc, r);

      const corpo = {
        name: nome.trim(),
        email: email.trim(),
        role: perfil,
        funcao: funcao.trim() || null,
        whatsapp: whatsapp.trim() || null,
        // ⚠️ OS CAMPOS DE ACESSO SÓ VÃO COM `usuarios.conceder`. O servidor cobra
        // essa chave assim que o corpo traz qualquer um dos três
        // (`routers/users.py`), e mandá-los vazios seria pior que omiti-los:
        // num PATCH, `telas: []` significa "apague todas as telas dela".
        ...(podeConceder ? {
          municipio_ids: municipioUnico ? [municipios[0].id] : [...munsSel],
          telas: telasFinais,
          permissoes: acoesFinais,
          escopos: escopoFinal,
        } : {}),
      };
      if (editando) {
        await api.patch(`/users/${alvo!.id}`, { ...corpo, active: ativo });
      } else {
        await api.post("/users", corpo);
      }
      await onSalvo();
      onFechar();
    } catch (e: unknown) {
      setErro((e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail || "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  };

  // Busca por nome de tela: filtra as folhas e mantém o grupo que sobrar.
  const arvoreVisivel = useMemo(() => {
    const q = buscaTela.trim().toLowerCase();
    if (!q) return arvore;
    return arvore
      .map((g) => ({ ...g, telas: g.telas.filter(
        (t) => t.rotulo.toLowerCase().includes(q)) }))
      .filter((g) => g.telas.length > 0);
  }, [arvore, buscaTela]);

  // Buscar abre os grupos: filtrar e continuar tendo de clicar em cada
  // cabeçalho seria filtrar pela metade.
  useEffect(() => {
    if (buscaTela.trim()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setAbertos(new Set(arvoreVisivel.map((g) => g.rotulo)));
    }
  }, [buscaTela, arvoreVisivel]);

  const munsVisiveis = municipios.filter((m) => {
    const q = buscaMun.trim().toLowerCase();
    return !q || `${m.nome} ${m.uf}`.toLowerCase().includes(q);
  });

  const alvoSuper = alvo ? ehSuperAdmin(alvo) : false;

  return (
    <Modal
      aberto
      maxW="max-w-5xl"
      onFechar={onFechar}
      podeFechar={podeFechar}
      rotulo={editando ? "Editar usuário" : "Novo usuário"}
    >
      <ModalHead
        titulo={editando ? `Editar ${alvo!.name}` : "Novo usuário"}
        sub={editando
          ? alvo!.email
          : "Uma senha temporária é gerada automaticamente e a troca é obrigatória no primeiro login."}
        onFechar={() => { if (podeFechar()) onFechar(); }}
        right={
          <span className="bi-num text-[13px]" title="Telas liberadas · ações marcadas">
            {telasLiberadas} · {acoesMarcadas}
          </span>
        }
      />
      <ModalCorpo className="space-y-3">
        {!minhas && (
          <Aviso tom="critico" icon={AlertTriangle} className=""
                 titulo="Não deu para conferir as suas próprias permissões.">
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Ninguém concede o que não tem, e sem essa conferência não há como
              saber o que você pode conceder. Tudo fica travado até recarregar.
            </p>
          </Aviso>
        )}

        {alvoSuper && (
          <Aviso tom="atencao" icon={ShieldCheck} className=""
                 titulo="Esta é uma conta super-admin: ela pode tudo, sem depender destas marcações.">
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              O que for marcado fica guardado e só passa a valer se a conta
              deixar de ser super-admin.
            </p>
          </Aviso>
        )}

        {!podeConceder && minhas && (
          <Aviso tom="atencao" icon={Lock} className=""
                 titulo="Você não tem a permissão «Usuários — Conceder permissões».">
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Dá para cadastrar a pessoa (nome, e-mail, perfil e contato), mas
              municípios, telas e ações ficam travados — quem libera o acesso é
              quem tem essa caixinha.
            </p>
          </Aviso>
        )}

        {souEu && (
          <Aviso tom="atencao" icon={AlertTriangle} className=""
                 titulo="Você está editando o seu próprio cadastro.">
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Só dá para RETIRAR: conceder exigiria ter o que você ainda não tem.
              Se você tirar a tela <b>Usuários</b> de si mesmo, perde o acesso a
              esta tela e depende de outro administrador para voltar.
            </p>
          </Aviso>
        )}

        {/* ---------------- 1. DADOS ---------------- */}
        <Bloco className="p-4">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide"
               style={{ color: "var(--bi-faint)" }}>
            1. Dados do usuário
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <Rotulo>Nome *</Rotulo>
              <Input value={nome} onChange={(e) => setNome(e.target.value)}
                     placeholder="Nome completo" />
            </div>
            <div>
              <Rotulo>E-mail *</Rotulo>
              <Input value={email} type="email"
                     onChange={(e) => setEmail(e.target.value)}
                     placeholder="email@exemplo.com" />
              {email.trim() !== "" && !emailValido && (
                <p className="mt-1 text-[10px]" style={{ color: "var(--bi-crit)" }}>
                  E-mail inválido.
                </p>
              )}
            </div>
            <div>
              <Rotulo>Perfil *</Rotulo>
              <Select value={perfil} onValueChange={(v) => setPerfil(v ?? "")}>
                <SelectTrigger>
                  <SelectValue>
                    {(v: unknown) => perfis.find((p) => p.value === String(v ?? ""))?.label
                      ?? "Selecione"}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {perfis.map((p) => (
                    <SelectItem key={p.value} value={p.value}>{p.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                Organização interna. Não concede acesso.
              </p>
            </div>
            <div>
              <Rotulo>Função na organização</Rotulo>
              <Input value={funcao} onChange={(e) => setFuncao(e.target.value)}
                     placeholder="Secretário de Administração, Contadora…" />
            </div>
            <div>
              <Rotulo>WhatsApp</Rotulo>
              <Input value={whatsapp} inputMode="tel"
                     onChange={(e) => setWhatsapp(mascaraWhatsapp(e.target.value))}
                     placeholder="(31) 99999-9999" />
            </div>
            {editando && (
              <div className="flex items-end">
                <Chip on={ativo} onClick={() => setAtivo((v) => !v)}>
                  {ativo ? "Conta ativa" : "Conta inativa"}
                </Chip>
              </div>
            )}
          </div>
        </Bloco>

        {/* ---------------- 2. MUNICÍPIOS ----------------
            ⚠️ NÃO RENDERIZADA em ambiente de um município só: perguntar "quais
            municípios?" a quem está dentro do sistema de Monte Sião é pedir uma
            decisão que não existe. O vínculo é automático (ver `salvar`). */}
        {!municipioUnico && (
          <Bloco className="p-4">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wide"
                    style={{ color: "var(--bi-faint)" }}>
                2. Municípios
              </span>
              <span className="flex items-center gap-1">
                <span className="bi-num text-[10px]" style={{ color: "var(--bi-faint)" }}>
                  {munsSel.size}/{municipios.length}
                </span>
                <AcaoMini onClick={() => setMunsSel(new Set(municipios.map((m) => m.id)))}
                          disabled={munsSel.size === municipios.length}>
                  Marcar todos
                </AcaoMini>
                <AcaoMini onClick={() => setMunsSel(new Set())} disabled={munsSel.size === 0}>
                  Limpar
                </AcaoMini>
              </span>
            </div>
            {munsSel.size > 0 && (
              <div className="mb-2 flex flex-wrap gap-1">
                {[...munsSel].map((id) => {
                  const m = municipios.find((x) => x.id === id);
                  return (
                    <Selo key={id} tom="acento">{m ? `${m.nome}-${m.uf}` : `#${id}`}</Selo>
                  );
                })}
              </div>
            )}
            <div className="relative mb-2">
              <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2"
                      style={{ color: "var(--bi-faint)" }} />
              <Input value={buscaMun} onChange={(e) => setBuscaMun(e.target.value)}
                     placeholder="Buscar município" className="pl-7" />
            </div>
            <div className="bi-scroll flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
              {munsVisiveis.map((m) => (
                <Chip key={m.id} on={munsSel.has(m.id)}
                      onClick={() => setMunsSel((prev) => {
                        const n = new Set(prev);
                        if (n.has(m.id)) n.delete(m.id); else n.add(m.id);
                        return n;
                      })}>
                  {m.nome} - {m.uf}
                </Chip>
              ))}
            </div>
            {faltaMunicipio && (
              <p className="mt-2 text-[11px]" style={{ color: "var(--bi-crit)" }}>
                Ao menos um município é obrigatório — sem nenhum, a pessoa não
                enxerga dado nenhum.
              </p>
            )}
          </Bloco>
        )}

        {/* ---------------- 3. TELAS E PERMISSÕES ---------------- */}
        <Bloco className="p-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide"
                  style={{ color: "var(--bi-faint)" }}>
              {municipioUnico ? "2" : "3"}. Telas e permissões
            </span>
            <span className="text-[11px]" style={{ color: "var(--bi-text)" }}>
              {telasLiberadas} tela(s) liberada(s) · {acoesMarcadas} ação(ões) marcada(s)
            </span>
          </div>

          {/* Copiar de outro usuário — o que substituiu os modelos. */}
          {outros.length > 0 && (
            <div className="bi-card-flat mb-3 flex flex-wrap items-end gap-2 p-3">
              <div className="min-w-[220px] flex-1">
                <Rotulo>Copiar o acesso de outro usuário</Rotulo>
                <Select value={copiarDe ? String(copiarDe) : ""}
                        onValueChange={(v) => setCopiarDe(v ? Number(v) : null)}>
                  <SelectTrigger className="w-full">
                    <SelectValue>
                      {(v: unknown) => {
                        const o = outros.find((c) => String(c.id) === String(v ?? ""));
                        return o ? `${o.name} — ${o.email}` : "Escolher usuário";
                      }}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {outros.map((o) => (
                      <SelectItem key={o.id} value={String(o.id)}>
                        {o.name} — {o.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                      onClick={copiar} disabled={!copiarDe}>
                <CopyPlus className="size-4" /> Copiar
              </button>
            </div>
          )}

          <div className="mb-2 flex flex-wrap items-center gap-2">
            <div className="relative min-w-[180px] flex-1">
              <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2"
                      style={{ color: "var(--bi-faint)" }} />
              <Input value={buscaTela} onChange={(e) => setBuscaTela(e.target.value)}
                     placeholder="Buscar tela" className="pl-7" />
            </div>
            <AcaoMini onClick={() => setAbertos(new Set(arvore.map((g) => g.rotulo)))}>
              Expandir tudo
            </AcaoMini>
            <AcaoMini onClick={() => setAbertos(new Set())}>Recolher tudo</AcaoMini>
            <AcaoMini onClick={() => liberarTudo(true)}>Liberar todas as telas</AcaoMini>
            <AcaoMini onClick={() => liberarTudo(false)} disabled={telasLiberadas === 0}>
              Limpar tudo
            </AcaoMini>
            <AcaoMini onClick={marcarTodasAcoes} disabled={telasLiberadas === 0}>
              Marcar todas as ações nas telas liberadas
            </AcaoMini>
          </div>

          <div className="flex flex-col gap-2">
            {arvoreVisivel.map((g) => {
              const aberto = abertos.has(g.rotulo);
              const Seta = aberto ? ChevronDown : ChevronRight;
              const liberadas = g.telas.filter((t) => telasSel.has(t.tela)).length;
              const cor = corDoGrupo(g.rotulo);
              return (
                <div key={g.rotulo}
                     className="overflow-hidden rounded-md border"
                     style={{ borderColor: "var(--bi-line)", borderLeftWidth: 2,
                              borderLeftColor: cor }}>
                  <div className="flex items-start gap-2 px-3 py-2"
                       style={{ background: `color-mix(in srgb, ${cor} 6%, transparent)` }}>
                    <button type="button" onClick={() => setAbertos((prev) => {
                              const n = new Set(prev);
                              if (n.has(g.rotulo)) n.delete(g.rotulo); else n.add(g.rotulo);
                              return n;
                            })}
                            aria-expanded={aberto}
                            className="min-w-0 flex-1 text-left">
                      <span className="flex items-center gap-1.5">
                        <Seta className="size-3.5 shrink-0" style={{ color: "var(--bi-faint)" }} />
                        {g.icone && <g.icone className="size-3.5 shrink-0" />}
                        <span className="bi-title text-[13px] leading-tight">
                          {g.rotulo}
                        </span>
                        {liberadas > 0 && <Selo>{liberadas} de {g.telas.length}</Selo>}
                      </span>
                    </button>
                    <span className="flex shrink-0 items-center gap-1">
                      <AcaoMini onClick={() => marcarGrupo(g, true)}
                                disabled={liberadas === g.telas.length}>
                        Liberar grupo
                      </AcaoMini>
                      <AcaoMini onClick={() => marcarGrupo(g, false)} disabled={liberadas === 0}>
                        Limpar
                      </AcaoMini>
                    </span>
                  </div>

                  {aberto && (
                    <div className="flex flex-col gap-1.5 p-2">
                      {g.telas.map((t) => {
                        const ligada = telasSel.has(t.tela);
                        const escritasMarcadas = t.recursos
                          .filter((r) => comEscopo.has(r))
                          .filter((r) => t.acoes.some(
                            (a) => a.recurso === r
                              && ["editar", "excluir"].includes(a.verbo)
                              && acoesSel.has(a.chave)));
                        return (
                          <div key={t.tela} className="bi-card-flat px-3 py-2">
                            <div className="flex items-center gap-2">
                              <Interruptor on={ligada} rotulo={t.rotulo}
                                           onToggle={() => alternarTela(t)} />
                              <span className="min-w-0 flex-1 text-[12px] font-medium"
                                    style={{ color: ligada ? "var(--bi-text)" : "var(--bi-muted)" }}>
                                {t.rotulo}
                              </span>
                              {ligada && t.acoes.length > 0 && (
                                <AcaoMini onClick={() => setAcoesSel((prev) => {
                                  const n = new Set(prev);
                                  for (const a of t.acoes) if (posso(a.chave)) n.add(a.chave);
                                  return n;
                                })}>
                                  Marcar todas
                                </AcaoMini>
                              )}
                            </div>

                            {/* As AÇÕES, indentadas — a hierarquia Tela › Ação
                                é o que permite varrer quarenta telas rápido.

                                ⚠️ AGRUPADAS POR RECURSO QUANDO HÁ MAIS DE UM, e
                                isso não é enfeite: o Painel de Indicadores tem
                                DOIS (o painel e as «Vigências a vencer», que são
                                um botão dentro dele). Sem o rótulo do recurso,
                                a linha mostrava «Ver · Ver · Exportar» — duas
                                caixinhas com o mesmo nome, e nenhuma pista de
                                que uma delas era a das Vigências. */}
                            {ligada && t.acoes.length > 0 && (
                              <div className="mt-1.5 flex flex-col gap-1 pl-[40px]">
                                {t.recursos.map((r) => {
                                  const doRecurso = t.acoes.filter((a) => a.recurso === r);
                                  const nomear = t.recursos.length > 1;
                                  return (
                                    <div key={r} className="flex flex-wrap items-center gap-x-4 gap-y-1">
                                      {nomear && (
                                        <span className="w-full text-[9px] uppercase tracking-wide sm:w-auto sm:min-w-[130px]"
                                              style={{ color: "var(--bi-faint)" }}>
                                          {doRecurso[0].recurso_rotulo}
                                        </span>
                                      )}
                                      {doRecurso.map((a) => {
                                        const travada = !posso(a.chave);
                                        return (
                                          <label key={a.chave} title={travada
                                                   ? "Você não tem esta permissão, então não pode concedê-la."
                                                   : a.descricao}
                                                 className={`flex items-center gap-1.5 ${travada ? "cursor-not-allowed" : "cursor-pointer"}`}>
                                            <input type="checkbox" className="size-3.5"
                                                   checked={acoesSel.has(a.chave)}
                                                   disabled={travada}
                                                   onChange={() => alternarAcao(t, a.chave)}
                                                   style={{ accentColor: "var(--bi-cta)" }} />
                                            <span className="text-[11px]"
                                                  style={{ color: travada ? "var(--bi-faint)" : "var(--bi-text)" }}>
                                              {a.verbo_rotulo}
                                            </span>
                                            {travada && <Lock className="size-3" style={{ color: "var(--bi-faint)" }} />}
                                          </label>
                                        );
                                      })}
                                    </div>
                                  );
                                })}
                              </div>
                            )}

                            {ligada && t.acoes.length === 0 && (
                              <p className="mt-1 pl-[40px] text-[10px]"
                                 style={{ color: "var(--bi-faint)" }}>
                                Esta tela não tem ações separadas — o acesso é a
                                permissão inteira.
                              </p>
                            )}

                            {/* O ALCANCE, só onde ele significa alguma coisa:
                                com «Editar» ou «Excluir» marcado. Numa conta que
                                só consulta, "somente os que ele criou" não
                                restringe nada — restringiria uma escrita que ela
                                não tem. */}
                            {ligada && escritasMarcadas.map((r) => (
                              <div key={r} className="mt-2 border-t pl-[40px] pt-2"
                                   style={{ borderColor: "var(--bi-line)" }}>
                                <div className="text-[9px] uppercase tracking-wide"
                                     style={{ color: "var(--bi-faint)" }}>
                                  Alcance de editar e excluir
                                </div>
                                <div role="radiogroup" className="mt-1 flex flex-wrap gap-3">
                                  {opcoesEscopo.map((op) => (
                                    <label key={op.valor}
                                           title={op.descricao}
                                           className={`flex items-center gap-1.5 ${alcanceTravado(r) ? "cursor-not-allowed" : "cursor-pointer"}`}>
                                      <input type="radio" name={`escopo-${t.tela}-${r}`}
                                             className="size-3.5"
                                             checked={escopoDe(esc, r) === op.valor}
                                             disabled={alcanceTravado(r)}
                                             onChange={() => setEsc((p) => ({ ...p, [r]: op.valor as Escopo }))}
                                             style={{ accentColor: "var(--bi-cta)" }} />
                                      <span className="text-[11px]" style={{ color: "var(--bi-text)" }}>
                                        {op.rotulo}
                                      </span>
                                    </label>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Salvar sem tela nenhuma é permitido — pode ser exatamente o que o
              administrador quer (cadastrar agora, liberar depois). Mas não pode
              acontecer sem ele perceber. */}
          {telasLiberadas === 0 && !alvoSuper && (
            <p className="mt-2 flex items-center gap-1.5 text-[11px]"
               style={{ color: "var(--bi-muted)" }}>
              <AlertTriangle className="size-3.5" style={{ color: "var(--bi-atencao-ink)" }} />
              Sem telas liberadas o usuário não verá nada — ele entra e o menu
              fica vazio.
            </p>
          )}
        </Bloco>

        {erro && (
          <div className="bi-card flex flex-wrap items-center gap-2 p-3 text-[12px]"
               style={{ color: "var(--bi-muted)" }}>
            <Selo tom="critico">Erro</Selo>
            {erro}
          </div>
        )}
      </ModalCorpo>

      {/* Rodapé fixo: a árvore é longa, e um botão de salvar no fim dela é um
          botão que ninguém acha. */}
      <div className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-4 py-3"
           style={{ borderColor: "var(--bi-line)", background: "var(--bi-surface)" }}>
        <span className="mr-auto text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {mudou ? "Alterações não salvas" : "Nada alterado."}
        </span>
        <button type="button" className={BOTAO_SEC} style={ESTILO_SEC}
                onClick={() => { if (podeFechar()) onFechar(); }}>
          Cancelar
        </button>
        <button type="button" className={BOTAO_CTA} style={ESTILO_CTA}
                onClick={salvar} disabled={!podeSalvar}>
          {salvando ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          {editando ? "Salvar alterações" : "Criar usuário"}
        </button>
      </div>
    </Modal>
  );
}
