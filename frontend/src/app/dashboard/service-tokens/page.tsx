"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { KeyRound, Plus, RotateCw, Trash2, Copy, ShieldAlert } from "lucide-react";
import api from "@/lib/api";
import {
  BOTAO_CTA, BOTAO_SEC, Bloco, BlocoHead, Campos, ESTILO_CTA, ESTILO_SEC,
  ItemLinha, Lista, Modal, ModalCorpo, ModalHead, Selo, Vazio,
} from "@/components/ui/superficies";
import { Input } from "@/components/ui/input";
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
  // Escopo da extensao de captura de sessao (gov.br/TransfereGov/FNS). Sem ele na
  // lista era impossivel criar por aqui um token que a extensao aceitasse: o
  // formulario exige ao menos um escopo, e o POST /api/session-capture responde
  // 403 sem session:write. A alternativa era o endpoint de control-plane
  // (/api/control/session/token), que exige um token de control ja provisionado.
  { label: "Extensao - captura de sessao", value: "session:write" },
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
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-2xl font-bold text-base-content">
              <KeyRound className="size-6" style={{ color: "var(--bi-muted)" }} />
              Service Tokens
            </h1>
            <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
              Tokens de automacao para scrapers (FNS, SIMEC, etc).
              Cada chamada e auditada.
            </p>
          </div>
          <button type="button" onClick={() => setDialogOpen(true)} className={BOTAO_CTA} style={ESTILO_CTA}>
            <Plus className="size-4" />Novo Token
          </button>
        </div>
      </div>

      {/* Formulario de criacao. `superficie` porque o corpo e formulario, nao
          uma pilha de blocos: caixa branca, e nao o fundo da pagina. */}
      <Modal aberto={dialogOpen} onFechar={() => setDialogOpen(false)} maxW="max-w-lg" superficie esc={false}>
        <ModalHead titulo="Criar Service Token" sub="O token so aparece uma vez, na criacao." onFechar={() => setDialogOpen(false)} />
        <ModalCorpo className="p-4">
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-[12px] font-medium" style={{ color: "var(--bi-muted)" }}>Nome (ex: fns_scraper)</label>
                  <Input
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    placeholder="fns_scraper"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[12px] font-medium" style={{ color: "var(--bi-muted)" }}>Descrição</label>
                  <Input
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    placeholder="Worker de scraping FNS"
                  />
                </div>
                <div>
                  <label className="mb-2 block text-[12px] font-medium" style={{ color: "var(--bi-muted)" }}>Scopes (escolha o minimo necessario)</label>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
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
              <div className="mt-4 flex justify-end gap-2">
                <button type="button" onClick={() => setDialogOpen(false)} className={BOTAO_SEC} style={ESTILO_SEC}>Cancelar</button>
                <button type="button" onClick={handleCreate} className={BOTAO_CTA} style={ESTILO_CTA}>Criar Token</button>
              </div>
        </ModalCorpo>
      </Modal>

      {/* Modal de exibicao do token recem-criado */}
      {showSecret && (
        <Bloco
          className="p-4"
          style={{
            background: "color-mix(in oklab, var(--bi-warn) 12%, transparent)",
            borderColor: "color-mix(in oklab, var(--bi-warn) 28%, transparent)",
          }}
        >
          <BlocoHead
            icon={ShieldAlert}
            titulo={`Token criado: ${showSecret.name}`}
            sub="ANOTE AGORA. Este token NAO sera mostrado novamente."
          />
          <div className="flex items-center gap-2 rounded-lg p-2 font-mono text-[12px] break-all"
               style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}>
            <span className="flex-1">{showSecret.token}</span>
            <button
              onClick={() => copyToClipboard(showSecret.token)}
              className="rounded-lg p-2 transition-colors hover:bg-[var(--bi-line)]"
              title="Copiar token"
            >
              <Copy className="size-4" />
            </button>
          </div>
          <p className="mt-2 text-[11px]" style={{ color: "var(--bi-warn-ink)" }}>
            Configure no Worker: <code>PACTHA_SERVICE_TOKEN={showSecret.token.slice(0, 20)}...</code>
          </p>
          <div className="mt-3">
            <button type="button" onClick={() => setShowSecret(null)} className={BOTAO_SEC} style={ESTILO_SEC}>
              Fechar (ja anotei)
            </button>
          </div>
        </Bloco>
      )}

      {/* Lista de tokens */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="h-20 animate-pulse rounded-2xl" style={{ background: "var(--bi-surface-2)" }} />
          ))}
        </div>
      ) : (
        /* A camada do meio: UM cartao branco em volta da lista inteira. Antes
           cada token era um `Bloco` branco solto no fundo cinza — a hierarquia
           estava invertida, com o item na cor do cartao. O estado vazio fica
           DENTRO do cartao: a tela nao pode alternar entre ter e nao ter a
           camada conforme o numero de tokens. */
        <Bloco className="p-3">
          <BlocoHead
            icon={KeyRound}
            titulo="Tokens cadastrados"
            sub={`${tokens.length} token(s)`}
            right={
              <span className="bi-num text-[13px]" title="Tokens ativos">
                {tokens.filter((t) => t.active).length} ativo(s)
              </span>
            }
          />
          {tokens.length === 0 ? (
            <Vazio>Nenhum Service Token cadastrado. Clique em &quot;Novo Token&quot;.</Vazio>
          ) : (
          <Lista>
            {tokens.map((t) => (
              <ItemLinha
                key={t.id}
                className={!t.active ? "opacity-60" : ""}
                titulo={
                  <span className="flex flex-wrap items-baseline gap-2">
                    <span className="min-w-0 truncate">{t.name}</span>
                    {/* Ativo fica CINZA de proposito: e o estado normal, e o
                        que precisa saltar e o revogado. */}
                    <Selo tom={t.active ? "neutro" : "critico"}>{t.active ? "Ativo" : "Revogado"}</Selo>
                    <span className="bi-id text-[10px]" style={{ color: "var(--bi-faint)" }}>
                      {t.token_prefix}***
                    </span>
                  </span>
                }
                meta={t.scopes.map((s) => (
                  <Selo key={s}>{s}</Selo>
                ))}
                /* Os botoes CONTINUAM ocupando o lugar quando o token esta
                   revogado — `invisible`, e nao removidos.

                   Medido: sem eles a area de conteudo ficava 68px mais larga
                   (2x28 + gap 4 + gap 8), e as quatro colunas da linha revogada
                   saiam 17/34/51px a direita das linhas ativas. Em 390px de
                   largura o desvio chega a 34px numa celula de 98px. A grade de
                   posicoes fixas existe justamente para o olho descer a coluna;
                   uma linha fora do prumo anula isso.

                   `visibility: hidden` guarda o espaco e ja tira o clique;
                   `aria-hidden` + `tabIndex -1` tiram do leitor de tela e do
                   Tab, para nao restar botao fantasma. Reservar por largura fixa
                   escrita a mao seria um numero magico que envelhece no primeiro
                   ajuste de icone. */
                acao={
                  <div
                    className={`flex items-center gap-1 ${t.active ? "" : "invisible"}`}
                    {...(t.active ? {} : { "aria-hidden": true })}
                  >
                    <button
                      type="button"
                      onClick={() => handleRotate(t.id, t.name)}
                      className="grid size-7 place-items-center rounded-lg"
                      style={{ background: "var(--bi-line)", color: "var(--bi-muted)" }}
                      title="Rotacionar token"
                      tabIndex={t.active ? undefined : -1}
                    >
                      <RotateCw className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRevoke(t.id, t.name)}
                      className="grid size-7 place-items-center rounded-lg"
                      style={{ background: "var(--bi-line)", color: "var(--bi-crit-ink)" }}
                      title="Revogar token"
                      tabIndex={t.active ? undefined : -1}
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                }
              >
                {t.description && (
                  <p className="mt-1 text-[12px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                    {t.description}
                  </p>
                )}
                {/* Eram quatro datas em frase corrida, e duas so apareciam
                    quando preenchidas — o que movia as outras de lugar a cada
                    linha. Em colunas fixas o olho desce a coluna, e o campo
                    ausente vira "-" em vez de sumir. */}
                <Campos
                  campos={[
                    { rotulo: "Último uso", valor: formatDate(t.last_used_at) },
                    { rotulo: "IP do último uso", valor: t.last_used_ip || "-", mono: true },
                    { rotulo: "Criado em", valor: formatDate(t.created_at) },
                    { rotulo: "Expira em", valor: formatDate(t.expires_at) },
                  ]}
                  cols={4}
                />
              </ItemLinha>
            ))}
          </Lista>
          )}
        </Bloco>
      )}
    </div>
  );
}
