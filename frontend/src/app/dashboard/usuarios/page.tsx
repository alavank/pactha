"use client";

import React, { useEffect, useState, useCallback } from "react";
import { UserPlus, KeyRound, Power, Loader2, Copy, Check, X, Building2, ListChecks } from "lucide-react";
import api from "@/lib/api";
import { TELAS, TELA_LABELS } from "@/lib/telas";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Bloco, BlocoHead, Campos, ItemLinha, Lista, Selo, Vazio, situacaoTom,
} from "@/components/ui/superficies";

interface Usuario {
  id: number;
  email: string;
  name: string;
  role: string;
  active: boolean;
  must_change_password?: boolean;
  municipio_ids?: number[];
  telas?: string[];
}

interface Municipio { id: number; nome: string; uf: string; }

interface SenhaResp {
  id: number;
  email: string;
  name: string;
  senha_temporaria: string;
}

// ⚠️ `value` e CHAVE do backend (users.role). So o `label` e texto de tela.
const ROLES = [
  { value: "admin", label: "Administrador" },
  { value: "analyst", label: "Analista" },
  { value: "user", label: "Usuario" },
];

/** Rotulo de controle: 11px em `--bi-muted`, a mesma escala dos filtros das
 *  demais telas do lote. Existe para os quatro rotulos desta tela nao voltarem
 *  a divergir em tamanho/cor um do outro. */
function Rotulo({
  icon: Icon, children,
}: {
  icon?: React.ComponentType<{ className?: string; style?: React.CSSProperties }>;
  children: React.ReactNode;
}) {
  return (
    <label className="mb-1 flex items-center gap-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
      {Icon && <Icon className="size-3.5" />}
      {children}
    </label>
  );
}

/** O chip de marcacao dos dois seletores (municipio e tela).
 *
 *  Estava escrito duas vezes, identico, com o violeta do tema no estado
 *  marcado. Agora e uma peca so e o marcado se distingue como em Parlamentares:
 *  fundo do proprio cinza da identidade e tinta de acento — o suficiente para
 *  ler "ligado" sem transformar a lista de 23 telas num painel colorido. */
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
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  // Criar
  const [novoEmail, setNovoEmail] = useState("");
  const [novoNome, setNovoNome] = useState("");
  const [novoRole, setNovoRole] = useState("admin");
  const [novoMunis, setNovoMunis] = useState<Set<number>>(new Set());
  const [novoTelas, setNovoTelas] = useState<Set<string>>(new Set());
  const [criando, setCriando] = useState(false);

  // Editar acesso (modal): municipios + telas
  const [editUser, setEditUser] = useState<Usuario | null>(null);
  const [editSel, setEditSel] = useState<Set<number>>(new Set());
  const [editTelas, setEditTelas] = useState<Set<string>>(new Set());
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
      const [ru, rm] = await Promise.all([
        api.get<Usuario[]>("/users"),
        api.get<Municipio[]>("/municipios"),
      ]);
      setUsers(ru.data);
      setMunicipios(Array.isArray(rm.data) ? rm.data : []);
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

  const criar = async () => {
    if (!novoEmail.trim() || !novoNome.trim()) return;
    setCriando(true);
    try {
      const r = await api.post<SenhaResp>("/users", {
        email: novoEmail.trim(), name: novoNome.trim(), role: novoRole,
        municipio_ids: novoRole === "admin" ? [] : [...novoMunis],
        telas: novoRole === "admin" ? [] : [...novoTelas],
      });
      setSenhaGerada(r.data);
      setNovoEmail(""); setNovoNome(""); setNovoRole("admin");
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
  };

  const salvarAcesso = async () => {
    if (!editUser) return;
    setSalvandoAcesso(true);
    try {
      await api.patch(`/users/${editUser.id}`, {
        municipio_ids: [...editSel],
        telas: [...editTelas],
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
    } catch {
      alert("Erro ao mudar role");
    }
  };

  const copiar = (s: string) => {
    navigator.clipboard.writeText(s);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  };

  const ativos = users.filter((u) => u.active).length;
  const pendentes = users.filter((u) => u.must_change_password).length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <h1 className="text-2xl font-bold text-base-content">Usuários</h1>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Gerenciamento de acessos à plataforma PACTHA: perfil, municípios e telas
          que cada pessoa enxerga.
        </p>
      </div>

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
            <Rotulo>Perfil</Rotulo>
            <Select value={novoRole} onValueChange={(v) => setNovoRole(v ?? "admin")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
              </SelectContent>
            </Select>
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

        {/* Municipios com acesso (so p/ nao-admin) */}
        <div className="mt-3">
          <Rotulo icon={Building2}>Municípios com acesso</Rotulo>
          {novoRole === "admin" ? (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>Administrador enxerga todos os municípios.</p>
          ) : (
            <MunicipioPicker municipios={municipios} selected={novoMunis} onToggle={toggleNovo} />
          )}
        </div>

        {/* Telas com acesso (so p/ nao-admin) */}
        <div className="mt-3">
          <Rotulo icon={ListChecks}>Telas com acesso</Rotulo>
          {novoRole === "admin" ? (
            <p className="text-[11px]" style={{ color: "var(--bi-faint)" }}>Administrador enxerga todas as telas.</p>
          ) : (
            <TelaPicker selected={novoTelas} onToggle={toggleNovoTela} />
          )}
        </div>

        <p className="mt-3 text-[11px]" style={{ color: "var(--bi-faint)" }}>
          O usuário só verá os municípios e as telas selecionados.
        </p>
      </Bloco>

      {/* Resumo */}
      <div className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
        {loading ? "Carregando..." : (
          <>
            <strong>{users.length}</strong> usuário(s) · {ativos} ativo(s)
            {pendentes > 0 && <> · {pendentes} com troca de senha pendente</>}
          </>
        )}
      </div>

      {/* LISTA — deixou de ser tabela.
          Eram oito colunas numa grade de linhas, com selo verde para o estado
          normal ("Ativo") e violeta no perfil. Agora cada usuario e um cartao:
          nome e e-mail em cima, e Municipios / Telas / Situacao em POSICOES
          FIXAS no <Campos>, de modo que o olho continua descendo a coluna como
          descia na tabela. Nada saiu — o ID virou o numero a direita e o perfil
          continua sendo o proprio seletor, que e como se troca o perfil aqui. */}
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
            const admin = u.role === "admin";
            const muns = u.municipio_ids ?? [];
            const telas = u.telas ?? [];
            return (
              <ItemLinha
                key={u.id}
                titulo={
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate">{u.name}</span>
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
                      <div className="text-right text-[9px] uppercase tracking-wide" style={{ color: "var(--bi-faint)" }}>
                        Perfil
                      </div>
                      <Select value={u.role} onValueChange={(v) => v && mudarRole(u, v)}>
                        <SelectTrigger className="h-7 text-[11px]"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm" variant="outline" className="h-7 text-[11px]"
                        onClick={() => abrirAcesso(u)}
                        title="Editar municípios e telas com acesso"
                        disabled={admin}
                      >
                        <Building2 className="size-3 mr-1" /> Acesso
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
                  cols={3}
                  campos={[
                    {
                      rotulo: "Municípios",
                      valor: admin
                        ? "Todos"
                        : muns.length === 0
                          ? "Nenhum"
                          : muns.length === 1
                            ? munNome(muns[0])
                            : `${muns.length} municípios`,
                      // Nao-admin sem municipio nenhum nao ve dado algum: e
                      // configuracao quebrada, e por isso um dos poucos lugares
                      // desta tela onde entra cor.
                      tom: !admin && muns.length === 0 ? "critico" : "normal",
                      title: admin
                        ? "Administrador enxerga todos os municípios"
                        : muns.length > 0
                          ? muns.map(munNome).join(", ")
                          : "Sem município: o usuário não enxerga dado nenhum",
                    },
                    {
                      rotulo: "Telas",
                      valor: admin
                        ? "Todas"
                        : telas.length === 0
                          ? "Nenhuma"
                          : telas.length >= TELAS.length
                            ? "Todas"
                            : `${telas.length} telas`,
                      tom: !admin && telas.length === 0 ? "critico" : "normal",
                      title: admin
                        ? "Administrador enxerga todas as telas"
                        : telas.length > 0
                          ? telas.map((t) => TELA_LABELS[t] || t).join(", ")
                          : "Sem tela: o menu do usuário fica vazio",
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

      {/* Modal editar acesso de municipios e telas */}
      {editUser && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(13, 16, 15, 0.45)" }}
          onClick={() => setEditUser(null)}
        >
          <div
            className="bi-card bi-scroll max-h-[85vh] w-full max-w-lg overflow-y-auto p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <BlocoHead
              icon={Building2}
              titulo={`Acesso de ${editUser.name}`}
              sub={editUser.email}
              right={
                <button type="button" onClick={() => setEditUser(null)} aria-label="Fechar">
                  <X className="size-4" style={{ color: "var(--bi-faint)" }} />
                </button>
              }
            />
            <div className="flex flex-col gap-3">
              <div>
                <Rotulo icon={Building2}>Municípios</Rotulo>
                <p className="mb-1.5 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                  O usuário só verá dados dos municípios marcados.
                </p>
                <MunicipioPicker municipios={municipios} selected={editSel} onToggle={toggleEdit} />
              </div>
              <div className="border-t pt-3" style={{ borderColor: "var(--bi-line)" }}>
                <Rotulo icon={ListChecks}>Telas</Rotulo>
                <p className="mb-1.5 text-[11px]" style={{ color: "var(--bi-faint)" }}>
                  Somente as telas marcadas aparecem no menu do usuário.
                </p>
                <TelaPicker selected={editTelas} onToggle={toggleEditTela} />
              </div>
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
        </div>
      )}

      {/* Modal senha gerada */}
      {senhaGerada && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(13, 16, 15, 0.45)" }}
          onClick={() => setSenhaGerada(null)}
        >
          <div className="bi-card w-full max-w-md p-4" onClick={(e) => e.stopPropagation()}>
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
        </div>
      )}
    </div>
  );
}
