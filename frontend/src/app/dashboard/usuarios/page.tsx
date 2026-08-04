"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  UserPlus, Users, KeyRound, Power, Loader2, Copy, Check, X, Building2,
  ListChecks, ShieldCheck, AlertTriangle, Lock,
} from "lucide-react";
import api from "@/lib/api";
import { TELAS, TELA_LABELS } from "@/lib/telas";
import {
  ehSuperAdmin, ehSomenteLeitura, PAPEIS_SEMPRE_SOMENTE_LEITURA,
} from "@/lib/conta";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  AcaoMini, Aviso, Bloco, BlocoHead, Campos, ItemLinha, Lista, Modal, Selo,
  Vazio, situacaoTom,
} from "@/components/ui/superficies";
import PermissoesModal from "./PermissoesModal";
import {
  buscarCatalogo, buscarConcedidas, buscarMinhas, resumoPorRecurso,
  type Catalogo, type MinhasPermissoes,
} from "@/lib/permissoes";
import type { MapaEscopos } from "@/lib/escopo";

interface Usuario {
  id: number;
  email: string;
  name: string;
  role: string;
  active: boolean;
  must_change_password?: boolean;
  municipio_ids?: number[];
  telas?: string[];
  // As duas colunas que substituiram o papel onde ele decidia poder de verdade.
  // Opcionais: `lib/conta.ts` deriva com reserva quando a API ainda nao manda.
  super_admin?: boolean | null;
  somente_leitura?: boolean | null;
}

interface Municipio { id: number; nome: string; uf: string; }

interface SenhaResp {
  id: number;
  email: string;
  name: string;
  senha_temporaria: string;
}

// O PERFIL E ROTULO, E SO ISSO.
//
// Ate este incremento, escolher "Administrador" aqui entregava a pessoa o
// sistema inteiro: o backend zerava os limites de tela e de municipio de quem
// tivesse `role == "admin"`. Nao zera mais. O papel serve para o cliente
// organizar a propria equipe — quem concede acesso sao as telas e os municipios
// marcados em CADA usuario, individualmente.
//
// ⚠️ `value` e CHAVE do backend (users.role). So o `label` e texto de tela.
const ROLES = [
  { value: "admin", label: "Administrador" },
  // "Analista" SAIU da lista de escolha. `analyst` e `user` sao byte-identicos
  // no sistema — nenhuma linha de codigo testa nenhum dos dois — e a migration
  // deste incremento funde os dois em `usuario` no banco. Dois nomes para a
  // mesma coisa fazem o administrador acreditar que escolher entre eles muda
  // alguma coisa; sobra UM rotulo de usuario comum.
  //
  // A chave e `usuario`, que e a que a migration grava. Os validadores do
  // backend passaram a aceita-la no MESMO deploy — sem isso, o usuario
  // normalizado apareceria neste seletor como chave crua, porque o valor
  // gravado nao existiria entre as opcoes. `analyst` e `user` continuam
  // ACEITAS la (integracao antiga pode manda-las) mas nao sao mais OFERECIDAS
  // aqui: dois nomes para a mesma coisa fazem o administrador acreditar que a
  // escolha muda alguma coisa.
  { value: "usuario", label: "Usuário" },
  // Entrou junto com a regra: o cliente marca o prefeito COMO prefeito e da a
  // ele so o Painel de Indicadores, sem que a palavra "prefeito" mude nada
  // sozinha. O backend ja aceitava esta chave; a tela e que nao a oferecia, e
  // por isso um usuario vindo do Console aparecia aqui com a chave crua.
  { value: "prefeito", label: "Prefeito" },
];

/** Rotulos de EXIBICAO — inclui papeis que a tela NAO oferece.
 *
 *  Nenhum destes tres e escolhivel, e cada um esta aqui por um motivo:
 *   · `usuario` — a chave NORMALIZADA pela migration deste incremento. E o que
 *     a maioria das contas passa a ter no banco, e sem esta linha o seletor
 *     mostraria a chave crua exatamente como ja mostrou "analyst" um dia.
 *   · `analyst` — legado: o canal do Console (`routers/control.py`) ainda cria
 *     usuario com este papel.
 *   · `viewer`  — as contas de quiosque (links de TV). O backend recusa cria-lo
 *     ou atribui-lo por aqui ("Role invalida"). */
const ROLE_LABELS: Record<string, string> = {
  ...Object.fromEntries(ROLES.map((r) => [r.value, r.label])),
  usuario: "Usuário",
  analyst: "Analista",
  viewer: "Visualizador",
};

/** O rotulo humano de um perfil, para o GATILHO FECHADO do seletor.
 *
 *  `<Select.Value>` do Base UI renderiza o valor CRU quando nao recebe funcao
 *  de formatacao — entao o gatilho fechado mostrava `analyst`, a chave do
 *  backend, enquanto a lista aberta mostrava "Analista" certinho. Medido no
 *  DOM: os cinco gatilhos liam "admin/admin/analyst/user/user".
 *
 *  A traducao e SO DE EXIBICAO. A chave continua sendo o que vai e volta da
 *  API — renomear `value` quebraria permissao em silencio. */
const rotuloRole = (v: unknown) =>
  ROLE_LABELS[String(v ?? "")] ?? String(v ?? "");

/** Rotulo de controle: 11px em `--bi-muted`, a mesma escala dos filtros das
 *  demais telas do lote. Existe para os quatro rotulos desta tela nao voltarem
 *  a divergir em tamanho/cor um do outro. */
function Rotulo({
  icon: Icon, children, right,
}: {
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  children: React.ReactNode;
  /** Controles na ponta direita da mesma linha (as acoes em lote dos
   *  seletores). Ficam AQUI e nao soltos acima do seletor para o rotulo e a
   *  contagem lerem como uma coisa so. */
  right?: React.ReactNode;
}) {
  return (
    <div className="mb-1 flex items-center justify-between gap-2">
      <label className="flex items-center gap-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
        {Icon && <Icon className="size-3.5" />}
        {children}
      </label>
      {right}
    </div>
  );
}

/** Contagem + "marcar tudo" / "limpar" de um seletor.
 *
 *  Existe porque conceder acesso deixou de ser um efeito colateral do papel:
 *  quem antes marcava "Administrador" e pronto agora precisa marcar as telas
 *  que aquela pessoa usa. Sem um atalho, montar um administrador do cliente
 *  seriam 24 cliques — e o caminho do meio (marcar tudo e desmarcar o que
 *  sobra) e justamente o que evita esquecer uma tela no caminho. */
function LoteAcoes({
  marcadas, total, onTodas, onNenhuma, marcarLabel = "Marcar todas",
}: {
  marcadas: number;
  total: number;
  onTodas: () => void;
  onNenhuma: () => void;
  marcarLabel?: string;
}) {
  return (
    <span className="flex shrink-0 items-center gap-1">
      <span className="bi-num text-[10px]" style={{ color: "var(--bi-faint)" }}>
        {marcadas}/{total}
      </span>
      <AcaoMini onClick={onTodas} disabled={total === 0 || marcadas === total}>{marcarLabel}</AcaoMini>
      <AcaoMini onClick={onNenhuma} disabled={marcadas === 0}>Limpar</AcaoMini>
    </span>
  );
}

/** O chip de marcacao dos dois seletores (municipio e tela).
 *
 *  Estava escrito duas vezes, identico, com o violeta do tema no estado
 *  marcado. Agora e uma peca so e o marcado se distingue como em Parlamentares:
 *  fundo do proprio cinza da identidade e tinta de acento — o suficiente para
 *  ler "ligado" sem transformar a lista inteira de telas num painel colorido. */
function Chip({
  on, onClick, children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors hover:bg-[var(--bi-surface-2)]"
      style={on
        ? {
            borderColor: "var(--bi-accent-ink)",
            background: "var(--bi-surface-2)",
            color: "var(--bi-accent-ink)",
            fontWeight: 500,
          }
        : { borderColor: "var(--bi-line)", color: "var(--bi-muted)" }}
    >
      {on && <Check className="size-3" />}
      {children}
    </button>
  );
}

/** A TRAVA DE ESCRITA da conta — o que era o perfil "Prefeito".
 *
 *  Até este incremento, quem não escrevia era decidido pelo PAPEL: o backend
 *  barrava todo POST/PUT/PATCH/DELETE de quem estivesse marcado como prefeito ou
 *  visualizador, fora do Painel de Indicadores. Marcar o rótulo era conceder (ou
 *  negar) uma capacidade, e era impossível ter dois prefeitos com direitos
 *  diferentes — exatamente a "besteira" que o dono descreveu.
 *
 *  Agora é atributo da CONTA, e por isso precisa de um interruptor próprio: sem
 *  ele a trava existiria no banco e em lugar nenhum da tela, e o administrador
 *  que criasse um prefeito depois do deploy receberia, calado, uma conta que
 *  escreve — o oposto do que a mesma escolha fazia na véspera.
 *
 *  Desenho deliberadamente sóbrio (chip, não interruptor colorido): é uma
 *  restrição normal de cadastro, não um alerta. */
function TravaEscrita({
  on, onToggle, sufixo,
}: {
  on: boolean;
  onToggle: () => void;
  /** Frase de contexto do lugar onde ele aparece (criação x edição). */
  sufixo?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Chip on={on} onClick={onToggle}>
        <Lock className="size-3" /> Somente leitura
      </Chip>
      <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>
        {on
          ? "A pessoa consulta o que lhe cabe e não altera nada fora do Painel de Indicadores."
          : "A pessoa pode alterar dados nas telas a que tem acesso."}
        {sufixo ? <> {sufixo}</> : null}
      </span>
    </div>
  );
}

// Seletor de municipios (chips com checkbox)
function MunicipioPicker({
  municipios, selected, onToggle,
}: {
  municipios: Municipio[];
  selected: Set<number>;
  onToggle: (id: number) => void;
}) {
  if (municipios.length === 0) {
    return <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>Nenhum município disponível.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {municipios.map((m) => (
        <Chip key={m.id} on={selected.has(m.id)} onClick={() => onToggle(m.id)}>
          {m.nome} - {m.uf}
        </Chip>
      ))}
    </div>
  );
}

// Seletor de telas/modulos (chips com checkbox)
function TelaPicker({
  selected, onToggle,
}: {
  selected: Set<string>;
  onToggle: (key: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {TELAS.map((t) => (
        <Chip key={t.key} on={selected.has(t.key)} onClick={() => onToggle(t.key)}>
          {t.label}
        </Chip>
      ))}
    </div>
  );
}

export default function UsuariosPage() {
  const [users, setUsers] = useState<Usuario[]>([]);
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  // Quem esta mexendo. Passou a fazer falta neste incremento: enquanto o papel
  // abria tudo, o botao "Acesso" vinha DESLIGADO para quem fosse admin — e com
  // isso ninguem conseguia esvaziar o proprio escopo por engano. Agora o botao
  // esta ligado para todos (e precisa estar), entao editar a si mesmo virou um
  // caminho real, e a tela tem de reconhece-lo.
  const [eu, setEu] = useState<Usuario | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  // PERMISSAO POR ACAO. As tres coisas vem da API e nenhuma e copiada para ca:
  //   catalogo    as 66 caixinhas, com rotulo e descricao (fonte: o backend)
  //   minhas      o que EU posso — e o teto do que eu consigo conceder
  //   concedidas  as caixinhas marcadas de CADA usuario, por id
  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);
  const [minhas, setMinhas] = useState<MinhasPermissoes | null>(null);
  const [concedidas, setConcedidas] = useState<Record<string, string[]>>({});
  // O ALCANCE por usuario e por modulo (`todos` | `proprios`). Vem da mesma
  // chamada das caixinhas: sao a mesma pergunta ("o que essa pessoa faz aqui").
  const [escopos, setEscopos] = useState<Record<string, MapaEscopos>>({});
  const [permUser, setPermUser] = useState<Usuario | null>(null);

  // Criar
  const [novoEmail, setNovoEmail] = useState("");
  const [novoNome, setNovoNome] = useState("");
  // Nasce "Usuário" e nao "Administrador". Enquanto o papel concedia acesso, o
  // default de administrador era o caminho curto para dar tudo a todo mundo — e
  // era o mesmo default do backend, que este incremento tirou de la. Papel
  // amplo tem de ser escolha explicita, ainda que hoje ele nao conceda nada.
  const [novoRole, setNovoRole] = useState("user");
  const [novoMunis, setNovoMunis] = useState<Set<number>>(new Set());
  const [novoTelas, setNovoTelas] = useState<Set<string>>(new Set());
  // A trava de ESCRITA, agora por pessoa. Segue o rótulo enquanto o
  // administrador não a tocar (`novoLeituraTocado`): "Prefeito" nasce somente
  // leitura, que é o que o sistema fazia com esse perfil até este incremento.
  // Depois de um clique manual, ela para de seguir — trocar o rótulo não pode
  // desfazer uma decisão que a pessoa já tomou na tela.
  const [novoLeitura, setNovoLeitura] = useState(false);
  const [novoLeituraTocado, setNovoLeituraTocado] = useState(false);
  const [criando, setCriando] = useState(false);

  // Editar acesso (modal): municipios + telas + a trava de escrita
  const [editUser, setEditUser] = useState<Usuario | null>(null);
  const [editSel, setEditSel] = useState<Set<number>>(new Set());
  const [editTelas, setEditTelas] = useState<Set<string>>(new Set());
  const [editLeitura, setEditLeitura] = useState(false);
  const [salvandoAcesso, setSalvandoAcesso] = useState(false);

  // Senha gerada (modal)
  const [senhaGerada, setSenhaGerada] = useState<SenhaResp | null>(null);
  const [copiado, setCopiado] = useState(false);

  const munNome = useCallback(
    (id: number) => {
      const m = municipios.find((x) => x.id === id);
      return m ? `${m.nome}-${m.uf}` : `#${id}`;
    },
    [municipios]
  );

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const [ru, rm, rme, rcat, rminhas, rconc] = await Promise.all([
        api.get<Usuario[]>("/users"),
        api.get<Municipio[]>("/municipios"),
        // Falha isolada de proposito: saber quem sou eu e um EXTRA (serve ao
        // aviso de auto-edicao). Dentro do `Promise.all` cru, um /auth/me que
        // tropeçasse derrubaria a listagem inteira de usuarios junto.
        api.get<Usuario>("/auth/me").catch(() => null),
        // As tres de permissao seguem a mesma regra: sao o INCREMENTO da tela,
        // e nao a tela. Se qualquer uma falhar, a lista de usuarios continua
        // funcionando e o que fica indisponivel e so o botao Permissoes — que
        // avisa por que. O contrario (derrubar a tela inteira) trancaria o
        // administrador fora ate de desativar uma conta.
        buscarCatalogo().catch(() => null),
        buscarMinhas().catch(() => null),
        buscarConcedidas().catch(() => ({ concedidas: {}, escopos: {} })),
      ]);
      setUsers(ru.data);
      setMunicipios(Array.isArray(rm.data) ? rm.data : []);
      setEu(rme?.data ?? null);
      setCatalogo(rcat);
      setMinhas(rminhas);
      setConcedidas(rconc.concedidas);
      setEscopos(rconc.escopos);
      setErro(null);
    } catch (e: unknown) {
      const msg = (e as { response?: { status?: number } })?.response?.status === 403
        ? "Apenas administradores acessam esta tela."
        : "Erro ao carregar usuarios.";
      setErro(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Mesma dispensa que as demais telas do lote usam: a carga inicial e uma
    // busca na API, nao um setState derivado de render.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar();
  }, [carregar]);

  const toggleNovo = (id: number) =>
    setNovoMunis((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleEdit = (id: number) =>
    setEditSel((prev) => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleNovoTela = (k: string) =>
    setNovoTelas((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const toggleEditTela = (k: string) =>
    setEditTelas((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });

  // Atalhos de lote. `TELAS` e a lista do frontend (a mesma que desenha os
  // chips), entao "marcar todas" concede exatamente o que esta na tela — nao um
  // conjunto invisivel.
  const todasTelas = () => TELAS.map((t) => t.key);
  const todosMunis = () => municipios.map((m) => m.id);

  /** Tenant de UM municipio (prefeitura). Ver a nota no formulario.
   *
   *  `municipios` chega vazio enquanto carrega, e vazio NAO e "um so" — por isso
   *  o teste e por igualdade a 1, e nao `<= 1`. Com a lista vazia o seletor
   *  continua aparecendo (vazio, dizendo que nao ha municipio), que e honesto:
   *  esconder ali faria a conta nascer sem municipio nenhum e sem ninguem ver. */
  const municipioUnico = municipios.length === 1;

  const criar = async () => {
    if (!novoEmail.trim() || !novoNome.trim()) return;
    setCriando(true);
    try {
      // O que vai e o que esta MARCADO, sempre.
      //
      // Aqui morava `role === "admin" ? [] : [...]`: criar um administrador
      // mandava listas VAZIAS de proposito, porque o papel abria tudo no
      // servidor e gravar escopo era redundante. Com o papel sem poder, essa
      // mesma linha criaria a conta mais cega do sistema — sem tela e sem
      // municipio nenhum, um usuario que entra e nao ve nada.
      const r = await api.post<SenhaResp>("/users", {
        email: novoEmail.trim(), name: novoNome.trim(), role: novoRole,
        // Num tenant de um municipio o seletor nao existe, entao a escolha e
        // feita AQUI: a conta nasce vinculada ao unico municipio. Mandar a lista
        // vazia criaria a conta cega — ela passaria por `ensure_municipio_access`
        // sem nenhum municipio permitido e nao enxergaria nada, sem erro nenhum
        // para explicar o porque.
        municipio_ids: municipioUnico ? [municipios[0].id] : [...novoMunis],
        telas: [...novoTelas],
        // Sempre explícito. Omitido, o backend semeia do rótulo — e uma tela que
        // mostra o interruptor tem de mandar o que o interruptor diz, e não
        // deixar o servidor adivinhar por baixo do que está desenhado.
        somente_leitura: novoLeitura,
      });
      setSenhaGerada(r.data);
      setNovoEmail(""); setNovoNome(""); setNovoRole("user");
      setNovoLeitura(false); setNovoLeituraTocado(false);
      setNovoMunis(new Set()); setNovoTelas(new Set());
      await carregar();
    } catch (e: unknown) {
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro ao criar usuario");
    } finally {
      setCriando(false);
    }
  };

  const abrirAcesso = (u: Usuario) => {
    setEditUser(u);
    setEditSel(new Set(u.municipio_ids ?? []));
    setEditTelas(new Set(u.telas ?? []));
    setEditLeitura(ehSomenteLeitura(u));
  };

  const salvarAcesso = async () => {
    if (!editUser) return;
    // Cortar o PROPRIO acesso: confirma antes.
    //
    // Nao e proibido — pode ser exatamente o que a pessoa quer (deixar de ver o
    // que nao lhe cabe mais). E tambem nao e uma cilada sem saida: a tela de
    // Usuarios nao depende de `user_telas` (quem a abre e o papel de
    // administrador), entao da para voltar aqui e se devolver o acesso. Mas o
    // menu vai sumir na hora, e sumir sem aviso parece defeito do sistema.
    const souEu = !!eu && eu.id === editUser.id;
    if (souEu && (editTelas.size === 0 || editSel.size === 0)) {
      const ok = confirm(
        "Você está editando o próprio acesso e vai ficar sem "
        + (editTelas.size === 0 ? "nenhuma tela" : "nenhum município")
        + ".\nO menu some na hora. Esta tela de Usuários continua acessível para você reverter.\n\nConfirma?"
      );
      if (!ok) return;
    }
    setSalvandoAcesso(true);
    try {
      await api.patch(`/users/${editUser.id}`, {
        municipio_ids: [...editSel],
        telas: [...editTelas],
        // Só quando MUDOU. O backend recusa que alguém se ponha em somente
        // leitura (é a porta que fecha por fora), e mandar o valor atual de si
        // mesmo — inalterado — faria essa recusa aparecer como erro numa edição
        // que não mexeu na trava.
        ...(editLeitura !== ehSomenteLeitura(editUser)
          ? { somente_leitura: editLeitura }
          : {}),
      });
      setEditUser(null);
      await carregar();
    } catch (e: unknown) {
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro ao salvar acesso");
    } finally {
      setSalvandoAcesso(false);
    }
  };

  const resetarSenha = async (u: Usuario) => {
    if (!confirm(`Resetar a senha de ${u.name} (${u.email})?\nEla sera obrigada a trocar no proximo login.`)) return;
    try {
      const r = await api.post<SenhaResp>(`/users/${u.id}/reset-password`);
      setSenhaGerada(r.data);
    } catch {
      alert("Erro ao resetar senha");
    }
  };

  const toggleAtivo = async (u: Usuario) => {
    try {
      await api.patch(`/users/${u.id}`, { active: !u.active });
      await carregar();
    } catch (e: unknown) {
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro");
    }
  };

  const mudarRole = async (u: Usuario, role: string) => {
    try {
      await api.patch(`/users/${u.id}`, { role });
      await carregar();
    } catch (e: unknown) {
      // O `detail` do backend e informativo aqui ("nao pode rebaixar o proprio
      // perfil", "somente o administrador principal pode alterar essa conta") e
      // era descartado por um catch cego que dizia so "Erro ao mudar role".
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Erro ao mudar o perfil");
    }
  };

  const copiar = (s: string) => {
    navigator.clipboard.writeText(s);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  };

  const ativos = users.filter((u) => u.active).length;
  const pendentes = users.filter((u) => u.must_change_password).length;
  // Conta ATIVA que nao enxerga nada. Passou a ser o numero que importa nesta
  // tela: com o papel sem poder, uma conta sem tela marcada e uma pessoa que faz
  // login e olha para um menu vazio — e antes isso era invisivel aqui, porque
  // "Administrador" preenchia o buraco calado.
  const semAcesso = users.filter(
    (u) => u.active && !ehSuperAdmin(u) && (u.telas ?? []).length === 0,
  ).length;

  /** As caixinhas MARCADAS de um usuario. Nunca `undefined`: quem nunca recebeu
   *  permissao nenhuma nao tem entrada no mapa, e "sem entrada" e zero. */
  const permsDe = (u: Usuario) => concedidas[String(u.id)] ?? [];
  /** O alcance por modulo. Usuario sem entrada nao e usuario sem alcance: e
   *  usuario no padrao (`todos`), que e o caso de quase todo mundo. */
  const escoposDe = (u: Usuario): MapaEscopos => escopos[String(u.id)] ?? {};
  // Quem CONCEDE precisa ter `usuarios.conceder` — a mesma chave que o servidor
  // exige. Sem `minhas` carregado nao da para afirmar que pode, e o botao fica
  // desligado com a explicacao: e melhor que abrir a tela e levar 403 no fim.
  const podeConceder = !!minhas
    && (minhas.super_admin || minhas.chaves.includes("usuarios.conceder"));
  // Conta ATIVA que pode entrar e nao faz nada. Hoje isso nao trava ninguem (a
  // trava esta em modo aviso), e por isso a contagem sai sem cor — mas e a
  // configuracao que vira ligacao de suporte no dia em que ela for ligada.
  const semPermissao = users.filter(
    (u) => u.active && !ehSuperAdmin(u) && permsDe(u).length === 0,
  ).length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="text-2xl font-bold text-base-content">Usuários</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Acesso à plataforma PACTHA, concedido usuário a usuário.
        </p>
      </div>

      {/* A REGRA DA TELA, escrita.
          Ela precisa estar aqui porque contraria o que o produto ensinou por
          um ano: até este incremento, marcar "Administrador" ERA dar tudo, e
          quem administra o cliente aprendeu esse gesto. Fica em cinza, sem
          fundo de alerta — é a regra normal do sistema, não um problema. */}
      <Bloco className="p-4">
        <BlocoHead
          icon={ShieldCheck}
          titulo="O perfil é só um rótulo"
          sub="Quem dá acesso são as telas e os municípios marcados em cada usuário, individualmente."
        />
        <ul className="flex flex-col gap-1.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
          {[
            <>
              <b style={{ color: "var(--bi-text)" }}>Perfil</b> (Administrador, Usuário,
              Prefeito) organiza a equipe do cliente e <b>não concede nada</b>.
              Escolher “Administrador” não abre nenhuma tela.
            </>,
            <>
              <b style={{ color: "var(--bi-text)" }}>Telas e Municípios</b> são a permissão
              de verdade. Sem tela marcada o menu da pessoa fica vazio; sem município, ela
              não enxerga dado nenhum.
            </>,
            <>
              <b style={{ color: "var(--bi-text)" }}>Super-admin</b> (contas da Alavank) é a
              única condição que ignora as duas listas — é a porta de entrada de quem
              mantém a plataforma.
            </>,
            <>
              <b style={{ color: "var(--bi-text)" }}>Somente leitura</b> é atributo da conta,
              não do perfil: a pessoa lê o que lhe cabe e não altera nada fora do Painel de
              Indicadores.
            </>,
          ].map((linha, i) => (
            /* O marcador é escrito à mão: o reset de CSS do projeto tira o
               `list-style`, e sem ele as quatro regras viram um parágrafo só. */
            <li key={i} className="flex gap-1.5">
              <span aria-hidden style={{ color: "var(--bi-faint)" }}>·</span>
              <span className="min-w-0">{linha}</span>
            </li>
          ))}
        </ul>
      </Bloco>

      {erro && (
        /* O aviso deixa de ser um retangulo vermelho inteiro: cor so no selo, e
           o texto no cinza de leitura. Um bloco pintado no topo compete com a
           lista sem dizer nada a mais do que a palavra "Acesso" ja diz. */
        <div className="bi-card flex flex-wrap items-center gap-2 p-3 text-[12px]" style={{ color: "var(--bi-muted)" }}>
          <Selo tom="critico">Acesso</Selo>
          {erro}
        </div>
      )}

      {/* Criar novo */}
      <Bloco className="p-4">
        <BlocoHead
          icon={UserPlus}
          titulo="Novo usuário"
          sub="Uma senha temporária é gerada automaticamente e a troca é obrigatória no primeiro login."
        />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <div>
            <Rotulo>Nome</Rotulo>
            <Input value={novoNome} onChange={(e) => setNovoNome(e.target.value)} placeholder="Nome completo" />
          </div>
          <div>
            <Rotulo>E-mail</Rotulo>
            <Input value={novoEmail} onChange={(e) => setNovoEmail(e.target.value)} placeholder="email@exemplo.com" type="email" />
          </div>
          <div>
            <Rotulo>Perfil (rótulo)</Rotulo>
            <Select
              value={novoRole}
              onValueChange={(v) => {
                const papel = v ?? "user";
                setNovoRole(papel);
                // O rótulo não CONCEDE nada — mas continua sendo uma boa
                // sugestão inicial para a trava de escrita, e é a mesma que o
                // backend aplica quando o campo vem omitido. Só sugere enquanto
                // o administrador não tiver tocado no interruptor: depois disso
                // trocar o rótulo não pode desfazer o que ele já decidiu.
                if (!novoLeituraTocado) setNovoLeitura(papel === "prefeito");
              }}
            >
              <SelectTrigger><SelectValue>{rotuloRole}</SelectValue></SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
              Organização interna. Não concede acesso.
            </p>
          </div>
          <div className="flex items-end">
            <Button
              onClick={criar}
              disabled={criando || !novoEmail.trim() || !novoNome.trim()}
              className="w-full hover:opacity-90"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
            >
              {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <UserPlus className="size-4 mr-1" />}
              Criar
            </Button>
          </div>
        </div>

        {/* Municipios e telas: SEMPRE, para todo perfil.
            Os dois blocos ficavam escondidos quando o perfil era "admin", e no
            lugar deles havia a frase "Administrador enxerga todos os
            municípios". Deixou de ser verdade — e um formulário que esconde o
            único campo que concede acesso cria a conta cega sem avisar.

            ⚠️ EXCEÇÃO, e ela é sobre não oferecer escolha que não existe: num
            tenant de UM município — que é o caso de toda prefeitura — perguntar
            "quais municípios?" é pedir uma decisão inexistente. Quem está
            dentro do sistema de Monte Sião está criando acesso para Monte Sião,
            e não tem nada a ver com outra cidade. O bloco some e o município é
            vinculado sozinho (ver `municipioUnico`). Com vários — assessoria,
            consórcio — o seletor aparece como sempre, porque aí a escolha é
            real. A regra é a CONTAGEM, não o tipo do cliente: assim ela acerta
            nos dois casos sem exigir configuração nova. */}
        {municipioUnico ? null : (
        <div className="mt-3">
          <Rotulo
            icon={Building2}
            right={
              <LoteAcoes
                marcadas={novoMunis.size}
                total={municipios.length}
                marcarLabel="Marcar todos"
                onTodas={() => setNovoMunis(new Set(todosMunis()))}
                onNenhuma={() => setNovoMunis(new Set())}
              />
            }
          >
            Municípios com acesso
          </Rotulo>
          <MunicipioPicker municipios={municipios} selected={novoMunis} onToggle={toggleNovo} />
        </div>
        )}

        <div className="mt-3">
          <Rotulo
            icon={ListChecks}
            right={
              <LoteAcoes
                marcadas={novoTelas.size}
                total={TELAS.length}
                onTodas={() => setNovoTelas(new Set(todasTelas()))}
                onNenhuma={() => setNovoTelas(new Set())}
              />
            }
          >
            Telas com acesso
          </Rotulo>
          <TelaPicker selected={novoTelas} onToggle={toggleNovoTela} />
        </div>

        {/* A terceira permissão da conta, junto das outras duas: as listas dizem
            o que a pessoa VÊ, esta chave diz se ela ALTERA. */}
        <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
          <Rotulo icon={Lock}>O que pode fazer</Rotulo>
          <TravaEscrita
            on={novoLeitura}
            onToggle={() => { setNovoLeitura((v) => !v); setNovoLeituraTocado(true); }}
          />
        </div>

        <p className="mt-3 text-[11px]" style={{ color: "var(--bi-faint)" }}>
          O usuário só verá os municípios e as telas selecionados — qualquer que seja o perfil.
        </p>

        {/* Só depois de a conta estar pronta para ser criada.
            Antes disso o formulário está vazio por definição, e um alerta
            permanente no rodapé vira parte do desenho: ninguém mais o lê. */}
        {novoEmail.trim() && novoNome.trim() && (novoTelas.size === 0 || novoMunis.size === 0) && (
          <Aviso
            tom="atencao"
            icon={AlertTriangle}
            titulo={
              novoTelas.size === 0 && novoMunis.size === 0
                ? "Esta conta vai nascer sem acesso nenhum."
                : novoTelas.size === 0
                  ? "Sem tela marcada: a pessoa entra e o menu fica vazio."
                  : "Sem município marcado: a pessoa não enxerga dado nenhum."
            }
          >
            <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
              Dá para criar assim e liberar depois em <b>Acesso</b>, na lista abaixo.
              O perfil escolhido não supre isso.
            </p>
          </Aviso>
        )}
      </Bloco>

      {/* LISTA — deixou de ser tabela.
          Eram oito colunas numa grade de linhas, com selo verde para o estado
          normal ("Ativo") e violeta no perfil. Agora cada usuario e um cartao:
          nome e e-mail em cima, e Municipios / Telas / Situacao em POSICOES
          FIXAS no <Campos>, de modo que o olho continua descendo a coluna como
          descia na tabela. Nada saiu — o ID virou o numero a direita e o perfil
          continua sendo o proprio seletor, que e como se troca o perfil aqui.

          O cartao branco em volta e a camada do meio da identidade (fundo cinza
          -> bloco branco -> item cinza). O resumo "13 usuario(s) · 10 ativo(s)"
          era uma linha solta acima da lista e virou o cabecalho deste bloco: e a
          mesma contagem, agora presa ao que ela conta. */}
      <Bloco className="p-3">
        <BlocoHead
          icon={Users}
          titulo="Usuários cadastrados"
          sub={loading ? "Carregando..." : (
            <>
              {ativos} ativo(s)
              {pendentes > 0 && <> · {pendentes} com troca de senha pendente</>}
              {semAcesso > 0 && (
                <> · <span style={{ color: "var(--bi-crit-ink)" }}>{semAcesso} sem tela nenhuma</span></>
              )}
              {semPermissao > 0 && <> · {semPermissao} sem permissão marcada</>}
            </>
          )}
          right={loading ? undefined : (
            <span className="bi-num text-[13px]">{users.length}</span>
          )}
        />
        {loading ? (
          <Lista>
            {Array.from({ length: 5 }).map((_, i) => (
              <li key={i} className="bi-card-flat h-[86px] animate-pulse" />
            ))}
          </Lista>
        ) : users.length === 0 ? (
          <Vazio>Nenhum usuário para exibir.</Vazio>
        ) : (
          <Lista>
            {users.map((u) => {
              // `admin` (o papel) SAIU daqui: ele nao diz mais nada sobre o que
              // a pessoa alcanca. Quem responde por "ve tudo" e o super-admin, e
              // e a UNICA condicao que ignora as duas listas.
              const superAdmin = ehSuperAdmin(u);
              const leitura = ehSomenteLeitura(u);
              const muns = u.municipio_ids ?? [];
              const telas = u.telas ?? [];
              const perms = permsDe(u);
              return (
                <ItemLinha
                  key={u.id}
                  titulo={
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate">{u.name}</span>
                      {superAdmin && (
                        /* Acento e nao cinza: e a linha onde a regra desta tela
                           NAO se aplica, e quem confere precisa achá-la de
                           relance no meio de trinta. */
                        <Selo
                          tom="acento"
                          title="Conta da Alavank: acesso total à plataforma, independente das telas e dos municípios marcados."
                        >
                          super-admin
                        </Selo>
                      )}
                      {leitura && (
                        /* Neutro de propósito: é uma restrição, não um alerta. */
                        <Selo
                          tom="neutro"
                          title="Somente leitura: a conta lê o que lhe cabe e não altera nada fora do Painel de Indicadores."
                        >
                          somente leitura
                        </Selo>
                      )}
                      {u.must_change_password && (
                        /* "pendente" e a palavra: quem decide o tom e a regra
                           unica do sistema, nao um tom escrito a mao aqui. */
                        <Selo
                          tom={situacaoTom("troca de senha pendente")}
                          title="O usuário ainda não trocou a senha temporária."
                        >
                          troca pendente
                        </Selo>
                      )}
                    </span>
                  }
                  valor={<span style={{ color: "var(--bi-faint)" }}>#{u.id}</span>}
                  meta={<span className="truncate" title={u.email}>{u.email}</span>}
                  acao={
                    <div className="flex flex-col items-end gap-1.5">
                      {/* O perfil e controle, nao texto: continua sendo o proprio
                          seletor. Largura fixa e rotulo de 9px para ele alinhar
                          com a grade de campos e com os demais cartoes. */}
                      <div className="w-[148px]">
                        <div
                          className="text-right text-[9px] uppercase tracking-wide"
                          style={{ color: "var(--bi-faint)" }}
                          title="Rótulo de organização interna. Trocar o perfil não concede nem retira acesso — isso se faz em Acesso."
                        >
                          Perfil (rótulo)
                        </div>
                        <Select value={u.role} onValueChange={(v) => v && mudarRole(u, v)}>
                          <SelectTrigger className="h-7 text-[11px]"><SelectValue>{rotuloRole}</SelectValue></SelectTrigger>
                          <SelectContent>
                            {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>
                      <div className="flex flex-wrap items-center justify-end gap-1">
                        {/* Deixou de vir `disabled` para quem tem papel de
                            administrador. Era coerente enquanto o papel abria
                            tudo — não havia o que editar. Agora é o contrário:
                            o administrador é justamente quem PRECISA ter as
                            telas marcadas, e o botão desligado o trancava fora
                            do único lugar onde isso se faz. */}
                        <Button
                          size="sm" variant="outline" className="h-7 text-[11px]"
                          onClick={() => abrirAcesso(u)}
                          title="Editar municípios e telas com acesso"
                        >
                          <Building2 className="size-3 mr-1" /> Acesso
                        </Button>
                        {/* SEPARADO de "Acesso" de propósito. Aquele botão diz
                            ONDE a pessoa entra (telas e municípios); este diz o
                            que ela FAZ lá dentro. Juntar os dois num modal só
                            somaria 66 caixinhas a uma tela que já tem três
                            seletores — e o resultado seria o paredão que faz o
                            administrador desistir e conceder tudo. */}
                        <Button
                          size="sm" variant="outline" className="h-7 text-[11px]"
                          onClick={() => setPermUser(u)}
                          disabled={!catalogo || !podeConceder}
                          title={
                            !catalogo
                              ? "Não foi possível carregar o catálogo de permissões. Recarregue a tela."
                              // As duas causas de `!podeConceder` sao diferentes e
                              // precisam de frases diferentes: dizer "voce nao tem a
                              // permissao" quando o que houve foi uma chamada que
                              // falhou manda o administrador procurar o problema no
                              // cadastro dele, que esta certo.
                              : !minhas
                                ? "Não foi possível conferir as suas permissões. Recarregue a tela."
                                : !podeConceder
                                  ? "Você não tem a permissão «Usuários — Conceder permissões»."
                                  : "Editar o que esta pessoa pode fazer"
                          }
                        >
                          <ShieldCheck className="size-3 mr-1" /> Permissões
                        </Button>
                        <Button
                          size="sm" variant="outline" className="h-7 px-2 text-[11px]"
                          onClick={() => resetarSenha(u)}
                          title="Resetar senha" aria-label={`Resetar senha de ${u.name}`}
                        >
                          <KeyRound className="size-3" />
                        </Button>
                        <Button
                          size="sm" variant="outline" className="h-7 px-2 text-[11px]"
                          onClick={() => toggleAtivo(u)}
                          title={u.active ? "Desativar" : "Ativar"}
                          aria-label={`${u.active ? "Desativar" : "Ativar"} ${u.name}`}
                        >
                          <Power className="size-3" />
                        </Button>
                      </div>
                    </div>
                  }
                >
                  <Campos
                    cols={4}
                    campos={[
                      {
                        rotulo: "Municípios",
                        valor: superAdmin
                          ? "Todos"
                          : muns.length === 0
                            ? "Nenhum"
                            : muns.length === 1
                              ? munNome(muns[0])
                              : `${muns.length} municípios`,
                        // Sem municipio nenhum a pessoa nao ve dado algum: e
                        // configuracao quebrada, e por isso um dos poucos lugares
                        // desta tela onde entra cor. A ressalva vale para todo
                        // mundo menos o super-admin — inclusive para quem tem
                        // papel de administrador, que antes era dispensado desta
                        // checagem e podia estar vazio sem ninguem notar.
                        tom: !superAdmin && muns.length === 0 ? "critico" : "normal",
                        title: superAdmin
                          ? "Super-admin: enxerga todos os municípios, sem depender desta lista"
                          : muns.length > 0
                            ? muns.map(munNome).join(", ")
                            : "Sem município: o usuário não enxerga dado nenhum",
                      },
                      {
                        rotulo: "Telas",
                        valor: superAdmin
                          ? "Todas"
                          : telas.length === 0
                            ? "Nenhuma"
                            : telas.length >= TELAS.length
                              ? "Todas"
                              : `${telas.length} telas`,
                        tom: !superAdmin && telas.length === 0 ? "critico" : "normal",
                        title: superAdmin
                          ? "Super-admin: enxerga todas as telas, sem depender desta lista"
                          : telas.length > 0
                            ? telas.map((t) => TELA_LABELS[t] || t).join(", ")
                            : "Sem tela: o menu do usuário fica vazio",
                      },
                      {
                        rotulo: "Permissões",
                        valor: superAdmin
                          ? "Todas"
                          : !catalogo
                            ? "—"
                            : perms.length === 0
                              ? "Nenhuma"
                              : `${perms.length} de ${catalogo.total}`,
                        // ATENÇÃO e não crítico: enquanto a trava está em modo
                        // aviso, zero caixinha não impede nada — anunciar como
                        // falha seria alarme falso. Vira problema no dia em que
                        // o bloqueio for ligado, e é aí que esta linha ajuda.
                        tom: !superAdmin && catalogo && perms.length === 0
                          ? "atencao" : "normal",
                        title: superAdmin
                          ? "Super-admin: pode tudo, sem depender destas caixinhas"
                          : !catalogo
                            ? "Catálogo de permissões indisponível"
                            : perms.length > 0
                              // O resumo legível, e não 40 chaves cruas: quem
                              // confere lê "Cofre de senhas: Ver, Revelar a
                              // senha", não `cofre.revelar`. Com o alcance
                              // junto: "Gestão Interna: Ver, Editar (só os que
                              // ele criou)" é uma pessoa DIFERENTE de quem
                              // edita a prefeitura inteira, e a lista precisa
                              // distinguir as duas sem abrir o modal.
                              ? resumoPorRecurso(catalogo, new Set(perms), undefined, escoposDe(u)).join(" · ")
                              : "Nenhuma ação liberada: a pessoa entra e não faz nada",
                      },
                      {
                        rotulo: "Situação",
                        // Cinza nos dois estados de proposito: "Ativo" e o normal
                        // e nao pode gritar verde, e "Inativo" e uma decisao do
                        // administrador, nao um alerta.
                        valor: u.active ? "Ativo" : "Inativo",
                        title: u.active ? "Pode entrar no sistema" : "Login bloqueado",
                      },
                    ]}
                  />
                </ItemLinha>
              );
            })}
          </Lista>
        )}
      </Bloco>

      {/* Modal editar acesso de municipios e telas */}
      {editUser && (
        <Modal
          aberto
          superficie
          maxW="max-w-lg"
          rotulo={`Acesso de ${editUser.name}`}
          onFechar={() => setEditUser(null)}
        >
          <div className="bi-scroll min-h-0 flex-1 overflow-y-auto p-4">
            <BlocoHead
              icon={Building2}
              titulo={`Acesso de ${editUser.name}`}
              sub={
                <>
                  {editUser.email} — estas duas listas <b>são</b> a permissão dela.
                  O perfil “{rotuloRole(editUser.role)}” não acrescenta nada.
                  {!!eu && eu.id === editUser.id && <> <b>Esta conta é a sua.</b></>}
                </>
              }
              right={
                <button type="button" onClick={() => setEditUser(null)} aria-label="Fechar">
                  <X className="size-4" style={{ color: "var(--bi-faint)" }} />
                </button>
              }
            />
            {/* Editar o escopo de um super-admin não é proibido — só é inócuo
                enquanto ele for super-admin. Dizer isso aqui evita a conclusão
                errada ("marquei e não adiantou, a tela está quebrada"), e o que
                for marcado passa a valer no dia em que a conta deixar de ser. */}
            {ehSuperAdmin(editUser) && (
              <Aviso
                tom="atencao"
                icon={ShieldCheck}
                titulo="Esta é uma conta super-admin: ela ignora as duas listas."
                className="mb-3"
              >
                <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
                  O que for marcado fica guardado e só passa a valer se a conta deixar
                  de ser super-admin.
                </p>
              </Aviso>
            )}
            <div className="flex flex-col gap-3">
              <div>
                <Rotulo
                  icon={Building2}
                  right={
                    <LoteAcoes
                      marcadas={editSel.size}
                      total={municipios.length}
                      marcarLabel="Marcar todos"
                      onTodas={() => setEditSel(new Set(todosMunis()))}
                      onNenhuma={() => setEditSel(new Set())}
                    />
                  }
                >
                  Municípios
                </Rotulo>
                <p className="mb-1.5 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                  O usuário só verá dados dos municípios marcados.
                </p>
                <MunicipioPicker municipios={municipios} selected={editSel} onToggle={toggleEdit} />
              </div>
              <div className="border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                <Rotulo
                  icon={ListChecks}
                  right={
                    <LoteAcoes
                      marcadas={editTelas.size}
                      total={TELAS.length}
                      onTodas={() => setEditTelas(new Set(todasTelas()))}
                      onNenhuma={() => setEditTelas(new Set())}
                    />
                  }
                >
                  Telas
                </Rotulo>
                <p className="mb-1.5 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                  Somente as telas marcadas aparecem no menu do usuário.
                </p>
                <TelaPicker selected={editTelas} onToggle={toggleEditTela} />
              </div>
              <div className="border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                <Rotulo icon={Lock}>O que pode fazer</Rotulo>
                <TravaEscrita
                  on={editLeitura}
                  onToggle={() => setEditLeitura((v) => !v)}
                  sufixo={
                    !!eu && eu.id === editUser.id ? (
                      /* O backend recusa este caso (400), porque é a porta que
                         fecha por fora: em somente leitura a pessoa não
                         conseguiria nem desfazer o próprio PATCH. Dizer aqui
                         evita o erro que só aparece depois do clique em Salvar. */
                      <b>Você não pode se colocar em somente leitura.</b>
                    ) : PAPEIS_SEMPRE_SOMENTE_LEITURA.has(editUser.role) ? (
                      /* Quiosque: o papel barra escrita por si só, no backend —
                         a lista vem de `lib/conta.ts`, que espelha
                         `services/auth.py`. Escrever "viewer" aqui à mão seria a
                         quinta cópia de uma regra de permissão. */
                      <b>Conta de link público de TV: continua somente leitura de qualquer forma.</b>
                    ) : null
                  }
                />
              </div>
              {/* Salvar com as duas listas vazias é revogar o acesso inteiro.
                  É uma operação legítima (desligar alguém sem desativar a
                  conta), mas não pode acontecer por descuido de clique. */}
              {(editTelas.size === 0 || editSel.size === 0) && !ehSuperAdmin(editUser) && (
                <Aviso
                  tom="atencao"
                  icon={AlertTriangle}
                  titulo={
                    editTelas.size === 0 && editSel.size === 0
                      ? "Salvando assim, esta pessoa fica sem acesso nenhum."
                      : editTelas.size === 0
                        ? "Sem tela marcada: o menu dela fica vazio."
                        : "Sem município marcado: ela não enxerga dado nenhum."
                  }
                  className=""
                />
              )}
              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" size="sm" onClick={() => setEditUser(null)}>Cancelar</Button>
                <Button
                  size="sm"
                  onClick={salvarAcesso}
                  disabled={salvandoAcesso}
                  className="hover:opacity-90"
                  style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                >
                  {salvandoAcesso ? <Loader2 className="size-4 animate-spin mr-1" /> : <Check className="size-4 mr-1" />}
                  Salvar
                </Button>
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* Modal de PERMISSOES — o que a pessoa faz, caixinha a caixinha.
          `catalogo` no guarda porque o modal o recebe obrigatorio: sem o
          catalogo nao ha o que desenhar, e o botao que abre este modal ja vem
          desligado nesse caso. */}
      {permUser && catalogo && (
        <PermissoesModal
          alvo={permUser}
          catalogo={catalogo}
          minhas={minhas}
          concedidas={permsDe(permUser)}
          escopos={escoposDe(permUser)}
          souEu={!!eu && eu.id === permUser.id}
          onFechar={() => setPermUser(null)}
          onSalvo={carregar}
        />
      )}

      {/* Modal senha gerada */}
      {senhaGerada && (
        <Modal
          aberto
          superficie
          maxW="max-w-md"
          rotulo="Senha temporária gerada"
          onFechar={() => setSenhaGerada(null)}
        >
          <div className="p-4">
            <BlocoHead
              icon={KeyRound}
              titulo="Senha temporária gerada"
              sub={`${senhaGerada.name} — ${senhaGerada.email}`}
              right={
                <button type="button" onClick={() => setSenhaGerada(null)} aria-label="Fechar">
                  <X className="size-4" style={{ color: "var(--bi-faint)" }} />
                </button>
              }
            />
            <div className="flex flex-col gap-3">
              <div>
                <div className="mb-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                  Senha temporária (copie e envie por canal seguro)
                </div>
                <div className="flex gap-2">
                  <code
                    className="bi-card-flat flex-1 select-all px-3 py-2 font-mono text-[13px]"
                    style={{ color: "var(--bi-text)" }}
                  >
                    {senhaGerada.senha_temporaria}
                  </code>
                  <Button
                    size="sm" variant="outline"
                    onClick={() => copiar(senhaGerada.senha_temporaria)}
                    title="Copiar senha" aria-label="Copiar senha"
                  >
                    {copiado
                      ? <Check className="size-4" style={{ color: "var(--bi-ok-ink)" }} />
                      : <Copy className="size-4" />}
                  </Button>
                </div>
              </div>
              {/* Aviso real (a senha some ao fechar): cor no selo, texto em
                  cinza — o mesmo tratamento dos avisos de Parlamentares. */}
              <p className="flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                <Selo tom="atencao">Atenção</Selo>
                Esta senha NÃO será exibida novamente. O usuário será obrigado a trocá-la
                no primeiro login. Não envie por e-mail em texto puro.
              </p>
              <Button
                className="w-full hover:opacity-90"
                style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                onClick={() => setSenhaGerada(null)}
              >
                Fechar
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
