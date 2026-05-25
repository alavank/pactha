"use client";

import React, { useEffect, useState, useCallback } from "react";
import { UserPlus, KeyRound, Power, Loader2, Copy, Check, X } from "lucide-react";
import api from "@/lib/api";
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
}

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

export default function UsuariosPage() {
  const [users, setUsers] = useState<Usuario[]>([]);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  // Criar
  const [novoEmail, setNovoEmail] = useState("");
  const [novoNome, setNovoNome] = useState("");
  const [novoRole, setNovoRole] = useState("admin");
  const [criando, setCriando] = useState(false);

  // Senha gerada (modal)
  const [senhaGerada, setSenhaGerada] = useState<SenhaResp | null>(null);
  const [copiado, setCopiado] = useState(false);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get<Usuario[]>("/users");
      setUsers(r.data);
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

  const criar = async () => {
    if (!novoEmail.trim() || !novoNome.trim()) return;
    setCriando(true);
    try {
      const r = await api.post<SenhaResp>("/users", {
        email: novoEmail.trim(), name: novoNome.trim(), role: novoRole,
      });
      setSenhaGerada(r.data);
      setNovoEmail(""); setNovoNome(""); setNovoRole("admin");
      await carregar();
    } catch (e: unknown) {
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro ao criar usuario");
    } finally {
      setCriando(false);
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
        <h1 className="text-2xl font-bold text-gray-900">Usuarios</h1>
        <p className="text-sm text-slate-500">Gerenciamento de acessos a plataforma PACTA</p>
      </div>

      {erro && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{erro}</div>
      )}

      {/* Criar novo */}
      <div className="bg-white border rounded-lg p-4">
        <h2 className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
          <UserPlus className="size-4" /> Novo usuario
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Nome</label>
            <Input value={novoNome} onChange={(e) => setNovoNome(e.target.value)} placeholder="Nome completo" />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">E-mail</label>
            <Input value={novoEmail} onChange={(e) => setNovoEmail(e.target.value)} placeholder="email@exemplo.com" type="email" />
          </div>
          <div>
            <label className="text-xs text-slate-600 mb-1 block">Perfil</label>
            <Select value={novoRole} onValueChange={(v) => setNovoRole(v ?? "admin")}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-end">
            <Button onClick={criar} disabled={criando || !novoEmail.trim() || !novoNome.trim()}
                    className="w-full bg-blue-600 hover:bg-blue-700">
              {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <UserPlus className="size-4 mr-1" />}
              Criar
            </Button>
          </div>
        </div>
        <p className="text-[11px] text-slate-500 mt-2">
          Uma senha temporaria sera gerada automaticamente. O usuario sera obrigado a troca-la no primeiro login.
        </p>
      </div>

      {/* Lista */}
      <div className="bg-white border rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-4 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-10 animate-pulse bg-gray-100 rounded" />)}
          </div>
        ) : (
          <Table className="text-sm">
            <TableHeader>
              <TableRow className="[&>th]:py-2 [&>th]:px-3 [&>th]:text-xs [&>th]:font-semibold bg-slate-50">
                <TableHead className="w-[50px]">ID</TableHead>
                <TableHead>Nome</TableHead>
                <TableHead>E-mail</TableHead>
                <TableHead className="w-[150px]">Perfil</TableHead>
                <TableHead className="w-[90px] text-center">Status</TableHead>
                <TableHead className="w-[180px] text-center">Acoes</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id} className="[&>td]:py-2 [&>td]:px-3 hover:bg-slate-50">
                  <TableCell className="text-slate-500">{u.id}</TableCell>
                  <TableCell className="font-medium">
                    {u.name}
                    {u.must_change_password && (
                      <span className="ml-2 text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                        troca pendente
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-slate-600">{u.email}</TableCell>
                  <TableCell>
                    <Select value={u.role} onValueChange={(v) => v && mudarRole(u, v)}>
                      <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {ROLES.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-center">
                    <span className={`inline-block px-2 py-0.5 rounded-full text-[11px] ${
                      u.active ? "bg-green-100 text-green-800" : "bg-gray-200 text-gray-600"
                    }`}>
                      {u.active ? "Ativo" : "Inativo"}
                    </span>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-center gap-1">
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => resetarSenha(u)} title="Resetar senha">
                        <KeyRound className="size-3 mr-1" /> Senha
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

      {/* Modal senha gerada */}
      {senhaGerada && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
             onClick={() => setSenhaGerada(null)}>
          <div className="bg-white rounded-lg shadow-2xl w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="bg-green-50 px-4 py-3 rounded-t-lg flex items-center justify-between border-b">
              <h3 className="font-bold text-green-900">Senha temporaria gerada</h3>
              <button onClick={() => setSenhaGerada(null)}><X className="size-5 text-gray-500" /></button>
            </div>
            <div className="p-4 space-y-3">
              <div className="text-sm">
                <div className="text-slate-600">Usuario:</div>
                <div className="font-medium">{senhaGerada.name} - {senhaGerada.email}</div>
              </div>
              <div>
                <div className="text-xs text-slate-600 mb-1">Senha temporaria (copie e envie por canal seguro):</div>
                <div className="flex gap-2">
                  <code className="flex-1 bg-slate-100 border rounded px-3 py-2 font-mono text-sm select-all">
                    {senhaGerada.senha_temporaria}
                  </code>
                  <Button size="sm" variant="outline" onClick={() => copiar(senhaGerada.senha_temporaria)}>
                    {copiado ? <Check className="size-4 text-green-600" /> : <Copy className="size-4" />}
                  </Button>
                </div>
              </div>
              <p className="text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
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
