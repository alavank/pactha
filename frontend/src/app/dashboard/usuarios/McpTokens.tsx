"use client";
/**
 * Tokens MCP de uma pessoa — a credencial de LEITURA que ela dá a um assistente
 * de IA (Claude, ChatGPT) para consultar os dados dela pela API MCP.
 *
 * Vive DENTRO do modal de Usuários (onde a permissão já é decidida): um
 * administrador gera/revoga para qualquer pessoa; a pessoa, para si. O backend
 * (`routers/mcp_tokens.py`) é quem decide de fato — aqui só se pede.
 *
 * ⚠️ O valor em claro aparece UMA vez, na criação. Não há como pedir de novo.
 * Revogar não apaga a linha (é o registro de que o acesso existiu) e corta o
 * acesso do assistente na hora.
 */
import { useCallback, useEffect, useState } from "react";
import { KeyRound, Plus, Trash2, Copy, ShieldAlert } from "lucide-react";
import api from "@/lib/api";
import {
  Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio, Campos,
  BOTAO_CTA, ESTILO_CTA, BOTAO_SEC, ESTILO_SEC,
} from "@/components/ui/superficies";
import { Input } from "@/components/ui/input";
import toast from "react-hot-toast";

interface McpTokenInfo {
  id: number;
  name: string;
  token_prefix: string | null;
  active: boolean;
  last_used_at: string | null;
  created_at: string | null;
  revoked_at: string | null;
  user_id: number;
}

export default function McpTokens({ userId }: { userId: number }) {
  const [tokens, setTokens] = useState<McpTokenInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [nome, setNome] = useState("");
  const [criando, setCriando] = useState(false);
  const [novo, setNovo] = useState<{ name: string; token: string } | null>(null);

  const carregar = useCallback(() => {
    setLoading(true);
    api
      .get<McpTokenInfo[]>("/mcp-tokens", { params: { user_id: userId } })
      .then((r) => setTokens(r.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [userId]);
  useEffect(carregar, [carregar]);

  const criar = async () => {
    if (nome.trim().length < 3) {
      toast.error("Dê um nome de ao menos 3 letras (para saber qual revogar depois).");
      return;
    }
    setCriando(true);
    try {
      const r = await api.post<{ name: string; token: string }>("/mcp-tokens", {
        name: nome.trim(),
        user_id: userId,
      });
      setNovo({ name: r.data.name, token: r.data.token });
      setNome("");
      carregar();
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || "Erro ao gerar o token.");
    } finally {
      setCriando(false);
    }
  };

  const revogar = async (id: number, nm: string) => {
    if (!confirm(`Revogar o token "${nm}"? O assistente que o usa perde o acesso na hora.`)) return;
    try {
      await api.post(`/mcp-tokens/${id}/revoke`);
      toast.success("Token revogado.");
      carregar();
    } catch {
      toast.error("Erro ao revogar.");
    }
  };

  const copiar = (t: string) => {
    navigator.clipboard.writeText(t);
    toast.success("Copiado.");
  };
  const data = (s: string | null) => (s ? new Date(s).toLocaleString("pt-BR") : "nunca usado");

  return (
    <Bloco className="p-4">
      <BlocoHead
        icon={KeyRound}
        titulo="Tokens MCP (assistente de IA)"
        sub="Credencial de LEITURA para um assistente (Claude, ChatGPT) consultar os dados desta pessoa, com o mesmo alcance de município que ela tem. Só leitura."
      />

      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div className="min-w-[180px] flex-1">
          <label className="mb-1 block text-[12px] font-medium" style={{ color: "var(--bi-muted)" }}>
            Nome do token
          </label>
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="Claude do gabinete" />
        </div>
        <button type="button" onClick={criar} disabled={criando} className={BOTAO_CTA} style={ESTILO_CTA}>
          <Plus className="size-4" />
          Gerar
        </button>
      </div>

      {novo && (
        <div
          className="mt-3 rounded-lg p-3"
          style={{
            background: "color-mix(in oklab, var(--bi-warn) 12%, transparent)",
            border: "1px solid color-mix(in oklab, var(--bi-warn) 28%, transparent)",
          }}
        >
          <p className="flex items-center gap-2 text-[12px] font-semibold" style={{ color: "var(--bi-warn-ink)" }}>
            <ShieldAlert className="size-4" />
            Token &quot;{novo.name}&quot; — anote AGORA. Ele NÃO será mostrado de novo.
          </p>
          <div
            className="mt-2 flex items-center gap-2 rounded-lg p-2 font-mono text-[12px] break-all"
            style={{ background: "var(--bi-surface)", border: "1px solid var(--bi-line)", color: "var(--bi-text)" }}
          >
            <span className="flex-1">{novo.token}</span>
            <button onClick={() => copiar(novo.token)} className="rounded-lg p-2 hover:bg-[var(--bi-line)]" title="Copiar token">
              <Copy className="size-4" />
            </button>
          </div>
          <button type="button" onClick={() => setNovo(null)} className={`mt-2 ${BOTAO_SEC}`} style={ESTILO_SEC}>
            Fechar (já anotei)
          </button>
        </div>
      )}

      <div className="mt-3">
        {loading ? (
          <div className="h-16 animate-pulse rounded-xl" style={{ background: "var(--bi-surface-2)" }} />
        ) : tokens.length === 0 ? (
          <Vazio>Nenhum token. Gere um acima para conectar um assistente de IA.</Vazio>
        ) : (
          <Lista>
            {tokens.map((t) => (
              <ItemLinha
                key={t.id}
                className={!t.active ? "opacity-60" : ""}
                titulo={
                  <span className="flex flex-wrap items-baseline gap-2">
                    <span className="min-w-0 truncate">{t.name}</span>
                    <Selo tom={t.active ? "neutro" : "critico"}>{t.active ? "Ativo" : "Revogado"}</Selo>
                    <span className="text-[10px]" style={{ color: "var(--bi-faint)" }}>{t.token_prefix}***</span>
                  </span>
                }
                acao={
                  t.active ? (
                    <button
                      type="button"
                      onClick={() => revogar(t.id, t.name)}
                      className="grid size-7 place-items-center rounded-lg"
                      style={{ background: "var(--bi-line)", color: "var(--bi-crit-ink)" }}
                      title="Revogar token"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  ) : undefined
                }
              >
                <Campos
                  cols={2}
                  campos={[
                    { rotulo: "Último uso", valor: data(t.last_used_at) },
                    { rotulo: "Criado em", valor: data(t.created_at) },
                  ]}
                />
              </ItemLinha>
            ))}
          </Lista>
        )}
      </div>

      <p className="mt-2 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
        Como conectar: no cliente MCP do assistente, adicione o servidor{" "}
        <code>&lt;URL da API&gt;/api/mcp</code> com o cabeçalho{" "}
        <code>Authorization: Bearer &lt;token&gt;</code>. O assistente só consegue LER, e apenas os
        municípios desta conta.
      </p>
    </Bloco>
  );
}
