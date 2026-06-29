"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Plus, RotateCw, Trash2, Copy, ShieldAlert, Activity } from "lucide-react";
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

interface ServiceToken {
  id: number;
  name: string;
  token_prefix: string | null;
  scopes: string[];
  description: string | null;
  active: boolean;
  last_used_at: string | null;
  last_used_ip: string | null;
  expires_at: string | null;
  created_at: string | null;
}

const SCOPE_PRESETS = [
  { label: "FNS - leitura senhas", value: "secret:read:fns" },
  { label: "FNS - upsert dados", value: "write:fns" },
  { label: "SIMEC - leitura senhas", value: "secret:read:simec" },
  { label: "SIMEC - upsert dados", value: "write:simec" },
  { label: "SISMOB - leitura senhas", value: "secret:read:sismob" },
  { label: "SISMOB - upsert dados", value: "write:sismob" },
  { label: "SUAS - leitura senhas", value: "secret:read:suas" },
  { label: "SUAS - upsert dados", value: "write:suas" },
];

export default function ServiceTokensPage() {
  const router = useRouter();
  const [tokens, setTokens] = useState<ServiceToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [showSecret, setShowSecret] = useState<{ name: string; token: string } | null>(null);
  const [form, setForm] = useState({ name: "", description: "", scopes: [] as string[] });

  // Verifica se usuario eh admin
  useEffect(() => {
    api
      .get<{ role: string }>("/auth/me")
      .then((res) => {
        if (res.data.role !== "admin") {
          toast.error("Apenas administradores acessam esta pagina");
          router.push("/dashboard");
        }
      })
      .catch(() => router.push("/login"));
  }, [router]);

  const fetchTokens = () => {
    setLoading(true);
    api
      .get<ServiceToken[]>("/admin/service-tokens")
      .then((res) => setTokens(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(fetchTokens, []);

  const handleCreate = async () => {
    if (!form.name || form.scopes.length === 0) {
      toast.error("Nome e ao menos um scope sao obrigatorios");
      return;
    }
    try {
      const res = await api.post<{ name: string; token: string }>("/admin/service-tokens", form);
      setShowSecret({ name: res.data.name, token: res.data.token });
      setDialogOpen(false);
      setForm({ name: "", description: "", scopes: [] });
      fetchTokens();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Erro ao criar token");
    }
  };

  const handleRotate = async (id: number, name: string) => {
    if (!confirm(`Rotacionar token "${name}"? O token antigo deixara de funcionar.`)) return;
    try {
      const res = await api.post<{ name: string; token: string }>(`/admin/service-tokens/${id}/rotate`);
      setShowSecret({ name: res.data.name, token: res.data.token });
      fetchTokens();
    } catch {
      toast.error("Erro ao rotacionar");
    }
  };

  const handleRevoke = async (id: number, name: string) => {
    if (!confirm(`REVOGAR token "${name}"? Esta acao desativa o token imediatamente.`)) return;
    try {
      await api.post(`/admin/service-tokens/${id}/revoke`);
      toast.success("Token revogado");
      fetchTokens();
    } catch {
      toast.error("Erro ao revogar");
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast.success("Copiado");
  };

  const toggleScope = (s: string) => {
    setForm((prev) => ({
      ...prev,
      scopes: prev.scopes.includes(s)
        ? prev.scopes.filter((x) => x !== s)
        : [...prev.scopes, s],
    }));
  };

  const formatDate = (s: string | null) =>
    s ? new Date(s).toLocaleString("pt-BR") : "-";

  return (
    <div className="space-y-6">
      <div className="border-b border-base-300 pb-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-base-content flex items-center gap-2">
              <KeyRound className="size-6 text-primary" />
              Service Tokens
            </h1>
            <p className="text-sm text-base-content/60 mt-1">
              Tokens de automacao para scrapers (FNS, SIMEC, etc).
              Cada chamada e auditada.
            </p>
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger render={<Button><Plus className="mr-2 size-4" />Novo Token</Button>} />
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Criar Service Token</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div>
                  <label className="text-sm font-medium">Nome (ex: fns_scraper)</label>
                  <Input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="fns_scraper"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">Descricao</label>
                  <Input
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Worker Railway de scraping FNS"
                  />
                </div>
                <div>
                  <label className="text-sm font-medium block mb-2">Scopes (escolha o minimo necessario)</label>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {SCOPE_PRESETS.map((s) => (
                      <label key={s.value} className="flex items-center gap-2 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={form.scopes.includes(s.value)}
                          onChange={() => toggleScope(s.value)}
                        />
                        <span>{s.label}</span>
                      </label>
                    ))}
                  </div>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDialogOpen(false)}>Cancelar</Button>
                <Button onClick={handleCreate}>Criar Token</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Modal de exibicao do token recem-criado */}
      {showSecret && (
        <Card className="border-l-4 border-l-warning bg-warning/15">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-warning">
              <ShieldAlert className="size-5" />
              Token criado: {showSecret.name}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-warning font-medium">
              ANOTE AGORA. Este token NAO sera mostrado novamente.
            </p>
            <div className="flex items-center gap-2 bg-base-100 border rounded p-2 font-mono text-sm break-all">
              <span className="flex-1">{showSecret.token}</span>
              <button
                onClick={() => copyToClipboard(showSecret.token)}
                className="p-2 hover:bg-base-200 rounded"
              >
                <Copy className="size-4" />
              </button>
            </div>
            <p className="text-xs text-warning">
              Configure no Railway worker: <code>PACTA_SERVICE_TOKEN={showSecret.token.slice(0, 20)}...</code>
            </p>
            <Button variant="outline" size="sm" onClick={() => setShowSecret(null)}>
              Fechar (ja anotei)
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Lista de tokens */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded bg-base-200" />
          ))}
        </div>
      ) : tokens.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">
          Nenhum Service Token cadastrado. Clique em "Novo Token".
        </CardContent></Card>
      ) : (
        <div className="space-y-2">
          {tokens.map((t) => (
            <Card key={t.id} className={!t.active ? "opacity-60" : ""}>
              <CardContent className="p-4">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold text-base-content">{t.name}</h3>
                      {t.active ? (
                        <Badge className="bg-success/15 text-success hover:bg-success/15">
                          Ativo
                        </Badge>
                      ) : (
                        <Badge variant="secondary">Revogado</Badge>
                      )}
                      <span className="text-xs text-muted-foreground font-mono">
                        {t.token_prefix}***
                      </span>
                    </div>
                    {t.description && (
                      <p className="text-sm text-muted-foreground">{t.description}</p>
                    )}
                    <div className="flex flex-wrap gap-1 mt-2">
                      {t.scopes.map((s) => (
                        <Badge key={s} variant="outline" className="text-xs">
                          {s}
                        </Badge>
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-3 mt-2 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Activity className="size-3" />
                        Ultimo uso: {formatDate(t.last_used_at)}
                      </span>
                      {t.last_used_ip && <span>IP: {t.last_used_ip}</span>}
                      <span>Criado: {formatDate(t.created_at)}</span>
                      {t.expires_at && <span>Expira: {formatDate(t.expires_at)}</span>}
                    </div>
                  </div>
                  <div className="flex gap-1">
                    {t.active && (
                      <button
                        onClick={() => handleRotate(t.id, t.name)}
                        className="p-2 hover:bg-primary/10 rounded text-primary"
                        title="Rotacionar token"
                      >
                        <RotateCw className="size-4" />
                      </button>
                    )}
                    {t.active && (
                      <button
                        onClick={() => handleRevoke(t.id, t.name)}
                        className="p-2 hover:bg-error/10 rounded text-error"
                        title="Revogar token"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
