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

// Sistemas com integracao automatica (scraper) - URL/categoria/automation_key pre-vinculados
const INTEGRACOES = [
  {
    automation_key: "fns",
    label: "FNS - Fundo Nacional de Saude",
    sistema: "FNS - Fundo Nacional de Saude",
    url: "https://consultafns.saude.gov.br",
    categoria: "Saude",
    usuario_hint: "CPF (gov.br)",
    senha_hint: "Senha gov.br",
  },
  {
    automation_key: "sismob",
    label: "SISMOB - Obras de Saude",
    sistema: "SISMOB - Obras de Saude",
    url: "https://sismobcidadao.saude.gov.br",
    categoria: "Saude",
    usuario_hint: "CPF (gov.br)",
    senha_hint: "Senha gov.br",
  },
  {
    automation_key: "simec",
    label: "SIMEC / PAR - Educacao (FNDE)",
    sistema: "SIMEC/PAR - FNDE",
    url: "https://simec.mec.gov.br/par/",
    categoria: "Educacao",
    usuario_hint: "CPF",
    senha_hint: "Senha SIMEC",
  },
  {
    automation_key: "suas",
    label: "Estrutura SUAS - Assistencia (MDS)",
    sistema: "Estrutura SUAS",
    url: "https://estruturasuas.mds.gov.br",
    categoria: "Assistencia Social",
    usuario_hint: "CPF",
    senha_hint: "Senha gov.br",
  },
  {
    automation_key: "investsus",
    label: "InvestSUS - Painel Saude",
    sistema: "InvestSUS",
    url: "https://investsuspaineis.saude.gov.br",
    categoria: "Saude",
    usuario_hint: "CPF (gov.br)",
    senha_hint: "Senha gov.br",
  },
];

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
  // Flag "Integracao": se true, usuario escolhe sistema da lista (URL/automation_key vinculados)
  // Se false, cadastro livre sem automacao
  const [isIntegracao, setIsIntegracao] = useState(true);
  const [integracaoSelecionada, setIntegracaoSelecionada] = useState<string>("");

  const handleSelecionarIntegracao = (key: string) => {
    setIntegracaoSelecionada(key);
    const integ = INTEGRACOES.find((i) => i.automation_key === key);
    if (integ) {
      setForm((prev) => ({
        ...prev,
        sistema: integ.sistema,
        url: integ.url,
        categoria: integ.categoria,
        automation_key: integ.automation_key,
      }));
    } else {
      // Limpa quando deseleciona
      setForm((prev) => ({ ...prev, sistema: "", url: "", automation_key: "" }));
    }
  };

  const handleToggleIntegracao = (checked: boolean) => {
    setIsIntegracao(checked);
    if (!checked) {
      // Modo manual: limpa sistema/url/automation
      setIntegracaoSelecionada("");
      setForm((prev) => ({ ...prev, sistema: "", url: "", automation_key: "" }));
    }
  };

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
      setIsIntegracao(true);
      setIntegracaoSelecionada("");
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
              {/* FLAG INTEGRACAO - controla todo o resto */}
              <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={isIntegracao}
                    onChange={(e) => handleToggleIntegracao(e.target.checked)}
                    className="mt-1 size-4"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-medium text-blue-900">
                      Integracao com sistema PACTA
                    </div>
                    <div className="text-xs text-blue-700 mt-0.5">
                      {isIntegracao
                        ? "Selecione o sistema abaixo. So precisa preencher usuario e senha - o resto ja vem configurado."
                        : "Cadastro livre - voce preenche tudo manualmente, sem automacao."}
                    </div>
                  </div>
                </label>
              </div>

              {isIntegracao ? (
                <>
                  {/* MODO INTEGRACAO: dropdown de sistemas pre-configurados */}
                  <div>
                    <label className="text-sm font-medium">Sistema integrado *</label>
                    <select
                      className="w-full border rounded-md p-2 text-sm"
                      value={integracaoSelecionada}
                      onChange={(e) => handleSelecionarIntegracao(e.target.value)}
                    >
                      <option value="">-- Selecione o sistema --</option>
                      {INTEGRACOES.map((i) => (
                        <option key={i.automation_key} value={i.automation_key}>
                          {i.label}
                        </option>
                      ))}
                    </select>
                    {integracaoSelecionada && (
                      <div className="mt-2 text-xs text-slate-600 bg-slate-50 rounded p-2 space-y-0.5">
                        <div>
                          <strong>URL:</strong>{" "}
                          <a
                            href={form.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                          >
                            {form.url}
                          </a>
                        </div>
                        <div>
                          <strong>Categoria:</strong> {form.categoria}
                        </div>
                        <div>
                          <strong>Automacao:</strong> ativa via scraper{" "}
                          <code className="bg-amber-100 px-1 rounded">
                            {form.automation_key}
                          </code>
                        </div>
                      </div>
                    )}
                  </div>

                  {integracaoSelecionada && (
                    <>
                      <div>
                        <label className="text-sm font-medium">
                          Usuario *
                          <span className="text-xs text-slate-500 ml-2">
                            ({INTEGRACOES.find((i) => i.automation_key === integracaoSelecionada)?.usuario_hint})
                          </span>
                        </label>
                        <Input
                          value={form.usuario}
                          onChange={(e) => setForm({ ...form, usuario: e.target.value })}
                          placeholder="000.000.000-00"
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium">
                          Senha *
                          <span className="text-xs text-slate-500 ml-2">
                            ({INTEGRACOES.find((i) => i.automation_key === integracaoSelecionada)?.senha_hint})
                          </span>
                        </label>
                        <Input
                          type="password"
                          value={form.senha}
                          onChange={(e) => setForm({ ...form, senha: e.target.value })}
                        />
                      </div>
                      <div>
                        <label className="text-sm font-medium">Observacao</label>
                        <Input
                          value={form.observacao}
                          onChange={(e) => setForm({ ...form, observacao: e.target.value })}
                          placeholder="Opcional"
                        />
                      </div>
                    </>
                  )}
                </>
              ) : (
                <>
                  {/* MODO LIVRE: tudo manual, sem automacao */}
                  <div>
                    <label className="text-sm font-medium">Sistema *</label>
                    <Input
                      value={form.sistema}
                      onChange={(e) => setForm({ ...form, sistema: e.target.value })}
                      placeholder="Ex: TransfereGov, Portal interno, etc"
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
                        <option key={c} value={c}>{c}</option>
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
                  <p className="text-xs text-slate-500 italic">
                    Sem flag de integracao = senha apenas armazenada (sem automacao).
                  </p>
                </>
              )}
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
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
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
                        {s.automation_key ? (
                          <Badge className="bg-amber-100 text-amber-800 hover:bg-amber-100 text-xs">
                            ⚡ Integracao: {s.automation_key}
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-xs text-slate-500">
                            Avulsa
                          </Badge>
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
