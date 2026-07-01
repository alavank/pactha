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
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";

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

const ROLES = [
  { value: "admin", label: "Administrador" },
  { value: "analyst", label: "Analista" },
  { value: "user", label: "Usuario" },
];

// Seletor de municipios (chips com checkbox)
function MunicipioPicker({
  municipios, selected, onToggle,
}: {
  municipios: Municipio[];
  selected: Set<number>;
  onToggle: (id: number) => void;
}) {
  if (municipios.length === 0) {
    return <p className="text-xs text-base-content/50">Nenhum municipio disponivel.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {municipios.map((m) => {
        const on = selected.has(m.id);
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onToggle(m.id)}
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors ${
              on
                ? "border-primary bg-primary/10 text-primary font-medium"
                : "border-base-300 text-base-content/70 hover:bg-base-200"
            }`}
          >
            {on && <Check className="size-3" />}
            {m.nome} - {m.uf}
          </button>
        );
      })}
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
      {TELAS.map((t) => {
        const on = selected.has(t.key);
        return (
          <button
            key={t.key}
            type="button"
            onClick={() => onToggle(t.key)}
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors ${
              on
                ? "border-primary bg-primary/10 text-primary font-medium"
                : "border-base-300 text-base-content/70 hover:bg-base-200"
            }`}
          >
            {on && <Check className="size-3" />}
            {t.label}
          </button>
        );
      })}
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

  useEffect(() => { carregar(); }, [carregar]);

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

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-base-content">Usuarios</h1>
        <p className="text-sm text-base-content/60">Gerenciamento de acessos a plataforma PACTA</p>
      </div>

      {erro && (
        <div className="rounded-lg border border-error bg-error/15 p-3 text-sm text-error">{erro}</div>
      )}

      {/* Criar novo */}
      <div className="bg-base-100 border rounded-lg p-4">
        <h2 className="text-sm font-semibold text-base-content/70 mb-3 flex items-center gap-2">
          <UserPlus className="size-4" /> Novo usuario
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Nome</label>
            <Input value={novoNome} onChange={(e) => setNovoNome(e.target.value)} placeholder="Nome completo" />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">E-mail</label>
            <Input value={novoEmail} onChange={(e) => setNovoEmail(e.target.value)} placeholder="email@exemplo.com" type="email" />
          </div>
          <div>
            <label className="text-xs text-base-content/70 mb-1 block">Perfil</label>
            <Select value={novoRole} onValueChange={(v) => setNovoRole(v ?? "admin")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end">
            <Button onClick={criar} disabled={criando || !novoEmail.trim() || !novoNome.trim()}
                    className="w-full bg-primary hover:bg-primary/90">
              {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <UserPlus className="size-4 mr-1" />}
              Criar
            </Button>
          </div>
        </div>

        {/* Municipios com acesso (so p/ nao-admin) */}
        <div className="mt-3">
          <label className="text-xs text-base-content/70 mb-1.5 flex items-center gap-1">
            <Building2 className="size-3.5" /> Municipios com acesso
          </label>
          {novoRole === "admin" ? (
            <p className="text-xs text-base-content/50 italic">Administrador enxerga todos os municipios.</p>
          ) : (
            <MunicipioPicker municipios={municipios} selected={novoMunis} onToggle={toggleNovo} />
          )}
        </div>

        {/* Telas com acesso (so p/ nao-admin) */}
        <div className="mt-3">
          <label className="text-xs text-base-content/70 mb-1.5 flex items-center gap-1">
            <ListChecks className="size-3.5" /> Telas com acesso
          </label>
          {novoRole === "admin" ? (
            <p className="text-xs text-base-content/50 italic">Administrador enxerga todas as telas.</p>
          ) : (
            <TelaPicker selected={novoTelas} onToggle={toggleNovoTela} />
          )}
        </div>

        <p className="text-[11px] text-base-content/60 mt-2">
          Uma senha temporaria sera gerada automaticamente. O usuario sera obrigado a troca-la no primeiro login.
          O usuario so vera os municipios e as telas selecionados.
        </p>
      </div>

      {/* Lista */}
      <div className="bg-base-100 border rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-base-200 rounded" />)}
          </div>
        ) : (
          <Table className="text-sm">
            <TableHeader>
              <TableRow className="[&>th]:py-2 [&>th]:px-3 [&>th]:text-xs [&>th]:font-semibold bg-base-200">
                <TableHead className="w-[50px]">ID</TableHead>
                <TableHead>Nome</TableHead>
                <TableHead>E-mail</TableHead>
                <TableHead className="w-[150px]">Perfil</TableHead>
                <TableHead>Municipios</TableHead>
                <TableHead>Telas</TableHead>
                <TableHead className="w-[90px] text-center">Status</TableHead>
                <TableHead className="w-[210px] text-center">Acoes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} className="[&>td]:py-2 [&>td]:px-3 hover:bg-base-200">
                  <TableCell className="text-base-content/60">{u.id}</TableCell>
                  <TableCell className="font-medium">
                    {u.name}
                    {u.must_change_password && (
                      <span className="ml-2 text-[10px] bg-warning/15 text-warning px-1.5 py-0.5 rounded">
                        troca pendente
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-base-content/70">{u.email}</TableCell>
                  <TableCell>
                    <Select value={u.role} onValueChange={(v) => v && mudarRole(u, v)}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-xs">
                    {u.role === "admin" ? (
                      <span className="text-base-content/50 italic">Todos</span>
                    ) : (u.municipio_ids && u.municipio_ids.length > 0) ? (
                      <span className="text-base-content/70" title={u.municipio_ids.map(munNome).join(", ")}>
                        {u.municipio_ids.length === 1
                          ? munNome(u.municipio_ids[0])
                          : `${u.municipio_ids.length} municipios`}
                      </span>
                    ) : (
                      <span className="text-error/80">Nenhum</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {u.role === "admin" ? (
                      <span className="text-base-content/50 italic">Todas</span>
                    ) : (u.telas && u.telas.length > 0) ? (
                      <span className="text-base-content/70" title={u.telas.map((t) => TELA_LABELS[t] || t).join(", ")}>
                        {u.telas.length >= TELAS.length ? "Todas" : `${u.telas.length} telas`}
                      </span>
                    ) : (
                      <span className="text-error/80">Nenhuma</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] ${
                      u.active ? "bg-success/15 text-success" : "bg-base-300 text-base-content/70"
                    }`}>
                      {u.active ? "Ativo" : "Inativo"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-1">
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => abrirAcesso(u)}
                              title="Editar municipios com acesso" disabled={u.role === "admin"}>
                        <Building2 className="size-3 mr-1" /> Acesso
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => resetarSenha(u)} title="Resetar senha">
                        <KeyRound className="size-3" />
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => toggleAtivo(u)}
                              title={u.active ? "Desativar" : "Ativar"}>
                        <Power className="size-3" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Modal editar acesso de municipios */}
      {editUser && (
        <div className="fixed inset-0 z-50 bg-neutral/50 flex items-center justify-center p-4"
             onClick={() => setEditUser(null)}>
          <div className="bg-base-100 rounded-lg shadow-2xl w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
            <div className="px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-base-content flex items-center gap-2">
                <Building2 className="size-4 text-primary" /> Acesso de {editUser.name}
              </h3>
              <button onClick={() => setEditUser(null)}><X className="size-5 text-base-content/60" /></button>
            </div>
            <div className="p-4 space-y-4">
              <div className="space-y-2">
                <p className="text-xs font-semibold text-base-content/70 flex items-center gap-1">
                  <Building2 className="size-3.5" /> Municipios
                </p>
                <p className="text-[11px] text-base-content/60">
                  O usuario so vera dados dos municipios marcados.
                </p>
                <MunicipioPicker municipios={municipios} selected={editSel} onToggle={toggleEdit} />
              </div>
              <div className="space-y-2 border-t pt-3">
                <p className="text-xs font-semibold text-base-content/70 flex items-center gap-1">
                  <ListChecks className="size-3.5" /> Telas
                </p>
                <p className="text-[11px] text-base-content/60">
                  Somente as telas marcadas aparecem no menu do usuario.
                </p>
                <TelaPicker selected={editTelas} onToggle={toggleEditTela} />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" size="sm" onClick={() => setEditUser(null)}>Cancelar</Button>
                <Button size="sm" className="bg-primary hover:bg-primary/90" onClick={salvarAcesso} disabled={salvandoAcesso}>
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
        <div className="fixed inset-0 z-50 bg-neutral/50 flex items-center justify-center p-4"
             onClick={() => setSenhaGerada(null)}>
          <div className="bg-base-100 rounded-lg shadow-2xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="bg-success/15 px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-success">Senha temporaria gerada</h3>
              <button onClick={() => setSenhaGerada(null)}><X className="size-5 text-base-content/60" /></button>
            </div>
            <div className="p-4 space-y-3">
              <div className="text-sm">
                <div className="text-base-content/70">Usuario:</div>
                <div className="font-medium">{senhaGerada.name} - {senhaGerada.email}</div>
              </div>
              <div>
                <div className="text-xs text-base-content/70 mb-1">Senha temporaria (copie e envie por canal seguro):</div>
                <div className="flex gap-2">
                  <code className="flex-1 bg-base-200 border rounded px-3 py-2 font-mono text-sm select-all">
                    {senhaGerada.senha_temporaria}
                  </code>
                  <Button size="sm" variant="outline" onClick={() => copiar(senhaGerada.senha_temporaria)}>
                    {copiado ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-warning bg-warning/15 border border-warning rounded p-2">
                Esta senha NAO sera exibida novamente. O usuario sera obrigado a troca-la no primeiro login.
                Nao envie por e-mail em texto puro.
              </p>
              <Button className="w-full" onClick={() => setSenhaGerada(null)}>Fechar</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
