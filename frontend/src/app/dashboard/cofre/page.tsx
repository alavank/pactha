"use client";

import React, { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Eye, EyeOff, KeyRound, Plus, Trash2, ExternalLink } from "lucide-react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import toast from "react-hot-toast";

interface Senha {
  id: number;
  municipio_id: number;
  sistema: string;
  url?: string;
  usuario?: string;
  senha?: string;
  senha_mascarada?: string;
  observacao?: string;
  categoria?: string;
}

const CATEGORIAS = ["Federal", "Estadual", "Saude", "Educacao", "Assistencia Social", "Outro"];

export default function CofrePage() {
  const searchParams = useSearchParams();
  const municipioId = searchParams.get("municipio_id");

  const [senhas, setSenhas] = useState<Senha[]>([]);
  const [loading, setLoading] = useState(true);
  const [revealedIds, setRevealedIds] = useState<Set<number>>(new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [form, setForm] = useState({
    sistema: "",
    url: "",
    usuario: "",
    senha: "",
    categoria: "Federal",
    observacao: "",
    automation_key: "",
  });

  const fetchSenhas = () => {
    if (!municipioId) return;
    setLoading(true);
    api
      .get<Senha[]>("/cofre", { params: { municipio_id: municipioId } })
      .then((res) => setSenhas(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchSenhas, [municipioId]);

  const toggleReveal = async (id: number) => {
    if (revealedIds.has(id)) {
      // hide: remove from revealed e limpa senha do estado
      setSenhas((prev) => prev.map((s) => (s.id === id ? { ...s, senha: undefined } : s)));
      setRevealedIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    } else {
      await revealSenha(id);
    }
  };

  const handleCreate = async () => {
    if (!municipioId || !form.sistema) {
      toast.error("Sistema obrigatorio");
      return;
    }
    try {
      await api.post("/cofre", { ...form, municipio_id: parseInt(municipioId) });
      toast.success("Senha cadastrada");
      setDialogOpen(false);
      setForm({ sistema: "", url: "", usuario: "", senha: "", categoria: "Federal", observacao: "", automation_key: "" });
      fetchSenhas();
    } catch {
      toast.error("Erro ao cadastrar");
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm("Remover esta senha?")) return;
    try {
      await api.delete(`/cofre/${id}`);
      toast.success("Removida");
      fetchSenhas();
    } catch {
      toast.error("Erro ao remover");
    }
  };

  const revealSenha = async (id: number) => {
    try {
      const res = await api.get<{ senha: string }>(`/cofre/${id}/reveal`);
      setSenhas((prev) =>
        prev.map((s) => (s.id === id ? { ...s, senha: res.data.senha } : s))
      );
      setRevealedIds((prev) => new Set(prev).add(id));
    } catch (e: unknown) {
      const err = e as { response?: { status?: number } };
      if (err.response?.status === 403) {
        toast.error("Apenas administradores podem revelar senhas");
      } else {
        toast.error("Erro ao revelar senha");
      }
    }
  };

  const copySenha = async (s: Senha) => {
    if (!s.senha) {
      await revealSenha(s.id);
      const updated = senhas.find((x) => x.id === s.id);
      if (updated?.senha) navigator.clipboard.writeText(updated.senha);
    } else {
      navigator.clipboard.writeText(s.senha);
    }
    toast.success("Senha copiada");
  };

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para visualizar o cofre.
      </div>
    );
  }

  const grouped = senhas.reduce((acc, s) => {
    const cat = s.categoria || "Outro";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {} as Record<string, Senha[]>);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <KeyRound className="size-6 text-indigo-600" />
            Cofre de Senhas
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Senhas centralizadas dos sistemas governamentais para este municipio
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger
            render={
              <Button>
                <Plus className="mr-2 size-4" />
                Nova Senha
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Cadastrar nova senha</DialogTitle>
            </DialogHeader>
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium">Sistema *</label>
                <Input
                  value={form.sistema}
                  onChange={(e) => setForm({ ...form, sistema: e.target.value })}
                  placeholder="Ex: TransfereGov"
                />
              </div>
              <div>
                <label className="text-sm font-medium">URL</label>
                <Input
                  value={form.url}
                  onChange={(e) => setForm({ ...form, url: e.target.value })}
                  placeholder="https://..."
                />
              </div>
              <div>
                <label className="text-sm font-medium">Usuario</label>
                <Input
                  value={form.usuario}
                  onChange={(e) => setForm({ ...form, usuario: e.target.value })}
                />
              </div>
              <div>
                <label className="text-sm font-medium">Senha</label>
                <Input
                  type="password"
                  value={form.senha}
                  onChange={(e) => setForm({ ...form, senha: e.target.value })}
                />
              </div>
              <div>
                <label className="text-sm font-medium">Categoria</label>
                <select
                  className="w-full border rounded-md p-2 text-sm"
                  value={form.categoria}
                  onChange={(e) => setForm({ ...form, categoria: e.target.value })}
                >
                  {CATEGORIAS.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-sm font-medium">Observacao</label>
                <Input
                  value={form.observacao}
                  onChange={(e) => setForm({ ...form, observacao: e.target.value })}
                />
              </div>
              <div className="border-t pt-3 mt-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  Automacao (opcional)
                  <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded">
                    avancado
                  </span>
                </label>
                <select
                  className="w-full border rounded-md p-2 text-sm"
                  value={form.automation_key}
                  onChange={(e) => setForm({ ...form, automation_key: e.target.value })}
                >
                  <option value="">Sem automacao (manual apenas)</option>
                  <option value="fns">FNS - Saude (scraper FNS)</option>
                  <option value="simec">SIMEC/PAR - Educacao</option>
                  <option value="sismob">SISMOB - Obras Saude</option>
                  <option value="suas">Estrutura SUAS - Assistencia</option>
                  <option value="investsus">InvestSUS</option>
                </select>
                <p className="text-xs text-muted-foreground mt-1">
                  Se marcar, esta credencial sera lida pelo scraper desse sistema.
                  Apenas Service Tokens com escopo correspondente acessam.
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button onClick={handleCreate}>Salvar</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded bg-gray-100" />
          ))}
        </div>
      ) : senhas.length === 0 ? (
        <div className="flex h-48 items-center justify-center rounded-lg border text-muted-foreground">
          Nenhuma senha cadastrada. Use o botao acima para adicionar.
        </div>
      ) : (
        Object.entries(grouped).map(([cat, items]) => (
          <Card key={cat}>
            <CardHeader>
              <CardTitle className="text-base">{cat}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {items.map((s) => (
                <div key={s.id} className="border rounded-lg p-4 hover:bg-gray-50">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2">
                        <h3 className="font-semibold text-gray-900">{s.sistema}</h3>
                        {s.url && (
                          <a
                            href={s.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                          >
                            <ExternalLink className="size-4" />
                          </a>
                        )}
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                        <div>
                          <span className="text-muted-foreground">Usuario:</span>{" "}
                          <span className="font-mono">{s.usuario || "-"}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-muted-foreground">Senha:</span>
                          <span
                            className="font-mono cursor-pointer"
                            onClick={() => copySenha(s)}
                          >
                            {revealedIds.has(s.id) ? s.senha || "-" : (s.senha_mascarada || "••••••••")}
                          </span>
                          <button
                            onClick={() => toggleReveal(s.id)}
                            className="text-gray-500 hover:text-gray-700"
                          >
                            {revealedIds.has(s.id) ? (
                              <EyeOff className="size-4" />
                            ) : (
                              <Eye className="size-4" />
                            )}
                          </button>
                        </div>
                      </div>
                      {s.observacao && (
                        <p className="text-xs text-muted-foreground mt-2">{s.observacao}</p>
                      )}
                    </div>
                    <button
                      onClick={() => handleDelete(s.id)}
                      className="text-red-500 hover:text-red-700 p-1"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}
