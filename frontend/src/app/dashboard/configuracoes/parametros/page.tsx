"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  SlidersHorizontal, Plus, Loader2, Trash2, Check, X, Lock, Pencil,
} from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Bloco, BlocoHead, ItemLinha, Lista, Selo, Vazio,
} from "@/components/ui/superficies";
import { listarParametros, type Parametro } from "@/lib/parametros";

/** ⭐ PARÂMETROS — as listas que ESTE cliente cadastra e o sistema usa.
 *
 *  Pedido do dono (11/08/2026). O primeiro tipo é o Perfil (Rótulo) de usuário:
 *  o que era uma lista fixa em código (Administrador, Usuário, Prefeito) passa
 *  a ser cadastrável aqui, e o cadastro de usuários puxa direto desta lista.
 *
 *  ⚠️ Cada cliente tem os SEUS: o PACTHA é single-tenant (um banco por cliente),
 *  então o isolamento é automático — não há nada a configurar nem a vazar.
 *
 *  ⚠️ O RÓTULO NÃO CONCEDE NADA, e a tela diz isso em voz alta. Quem dá acesso
 *  são as telas, os municípios e as permissões por ação, pessoa a pessoa.
 */
export default function ParametrosPage() {
  const [itens, setItens] = useState<Parametro[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [novo, setNovo] = useState("");
  const [criando, setCriando] = useState(false);
  const [editando, setEditando] = useState<number | null>(null);
  const [textoEdit, setTextoEdit] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    try {
      // Inclui os inativos: esta é a tela que os RESSUSCITA, então escondê-los
      // aqui deixaria o administrador sem caminho de volta.
      setItens(await listarParametros("perfil_usuario", true));
      setErro(null);
    } catch (e: unknown) {
      setErro((e as { response?: { status?: number } })?.response?.status === 403
        ? "Apenas administradores acessam os parâmetros."
        : "Não foi possível carregar os parâmetros.");
    } finally {
      setCarregando(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar();
  }, [carregar]);

  const falhou = (e: unknown, padrao: string) =>
    alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || padrao);

  const criar = async () => {
    const rotulo = novo.trim();
    if (!rotulo) return;
    setCriando(true);
    try {
      await api.post("/parametros", { tipo: "perfil_usuario", rotulo });
      setNovo("");
      await carregar();
    } catch (e: unknown) {
      falhou(e, "Erro ao cadastrar");
    } finally {
      setCriando(false);
    }
  };

  const salvarRotulo = async (p: Parametro) => {
    const rotulo = textoEdit.trim();
    if (!rotulo || rotulo === p.rotulo) { setEditando(null); return; }
    try {
      await api.patch(`/parametros/${p.id}`, { rotulo });
      setEditando(null);
      await carregar();
    } catch (e: unknown) {
      falhou(e, "Erro ao renomear");
    }
  };

  const alternarAtivo = async (p: Parametro) => {
    try {
      await api.patch(`/parametros/${p.id}`, { ativo: !p.ativo });
      await carregar();
    } catch (e: unknown) {
      falhou(e, "Erro ao alterar");
    }
  };

  const excluir = async (p: Parametro) => {
    if (!confirm(`Excluir o perfil «${p.rotulo}»?\nSe alguém estiver usando, desative em vez de excluir.`)) return;
    try {
      await api.delete(`/parametros/${p.id}`);
      await carregar();
    } catch (e: unknown) {
      falhou(e, "Erro ao excluir");
    }
  };

  return (
    <div className="space-y-4">
      <Bloco className="p-4">
        <BlocoHead
          icon={SlidersHorizontal}
          titulo="Perfil (rótulo) de usuário"
          sub="O que aparece no cadastro de usuários deste ambiente"
        />

        <p className="mb-3 text-[12px]" style={{ color: "var(--bi-muted)" }}>
          O perfil é um <b>rótulo de organização interna</b>: cadastrar um perfil novo
          não concede acesso nenhum. Quem dá acesso são as telas, os municípios e as
          permissões, marcados pessoa a pessoa em <b>Usuários</b>.
        </p>

        {/* Cadastro: um campo só. Pedir "chave" ao administrador seria pedir
            que ele pense como o banco — a chave é derivada do nome. */}
        <div className="mb-4 flex flex-wrap gap-2">
          <Input
            value={novo}
            onChange={(e) => setNovo(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") criar(); }}
            placeholder="Novo perfil (ex.: Secretário de Saúde)"
            className="max-w-xs"
            aria-label="Nome do novo perfil"
          />
          <Button
            onClick={criar}
            disabled={criando || !novo.trim()}
            className="hover:opacity-90"
            style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
          >
            {criando ? <Loader2 className="size-4 animate-spin mr-1" /> : <Plus className="size-4 mr-1" />}
            Cadastrar
          </Button>
        </div>

        {erro && (
          <div className="bi-card-flat px-3 py-2.5 text-[12px]" style={{ color: "var(--bi-crit-ink)" }}>
            {erro}
          </div>
        )}

        {carregando ? (
          <div className="flex items-center gap-2 p-4 text-sm" style={{ color: "var(--bi-muted)" }}>
            <Loader2 className="size-4 animate-spin" /> Carregando…
          </div>
        ) : itens.length === 0 && !erro ? (
          <Vazio>Nenhum perfil cadastrado.</Vazio>
        ) : (
          <Lista>
            {itens.map((p) => (
              <ItemLinha
                key={p.id}
                titulo={
                  editando === p.id ? (
                    <span className="flex items-center gap-1.5">
                      <Input
                        value={textoEdit}
                        onChange={(e) => setTextoEdit(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") salvarRotulo(p);
                          if (e.key === "Escape") setEditando(null);
                        }}
                        className="h-7 max-w-[240px] text-[13px]"
                        autoFocus
                        aria-label={`Novo nome para ${p.rotulo}`}
                      />
                      <button type="button" onClick={() => salvarRotulo(p)} aria-label="Salvar">
                        <Check className="size-4" style={{ color: "var(--bi-ok-ink)" }} />
                      </button>
                      <button type="button" onClick={() => setEditando(null)} aria-label="Cancelar">
                        <X className="size-4" style={{ color: "var(--bi-faint)" }} />
                      </button>
                    </span>
                  ) : (
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span>{p.rotulo}</span>
                      {p.reservado && (
                        <Selo tom="neutro" title="Perfil do sistema: pode ser renomeado, mas não desativado nem excluído.">
                          <Lock className="mr-0.5 inline size-2.5" /> do sistema
                        </Selo>
                      )}
                      {!p.ativo && (
                        <Selo tom="neutro" title="Não aparece no cadastro de usuários. Continua identificando quem já o tem.">
                          desativado
                        </Selo>
                      )}
                    </span>
                  )
                }
                meta={<code className="font-mono text-[11px]">{p.valor}</code>}
                acao={
                  <div className="flex items-center gap-1">
                    <Button
                      size="sm" variant="outline" className="h-7 px-2 text-[11px]"
                      onClick={() => { setEditando(p.id); setTextoEdit(p.rotulo); }}
                      title="Renomear" aria-label={`Renomear ${p.rotulo}`}
                    >
                      <Pencil className="size-3" />
                    </Button>
                    <Button
                      size="sm" variant="outline" className="h-7 px-2 text-[11px]"
                      onClick={() => alternarAtivo(p)}
                      disabled={p.reservado && p.ativo}
                      title={p.reservado && p.ativo
                        ? "Perfil do sistema não pode ser desativado"
                        : p.ativo ? "Desativar (some do cadastro)" : "Reativar"}
                    >
                      {p.ativo ? "Desativar" : "Reativar"}
                    </Button>
                    {!p.reservado && (
                      <Button
                        size="sm" variant="outline"
                        className="h-7 px-2 text-[11px] border-[var(--bi-crit)]/40 hover:bg-[var(--bi-crit)]/10"
                        style={{ color: "var(--bi-crit)" }}
                        onClick={() => excluir(p)}
                        title="Excluir" aria-label={`Excluir ${p.rotulo}`}
                      >
                        <Trash2 className="size-3" />
                      </Button>
                    )}
                  </div>
                }
              />
            ))}
          </Lista>
        )}
      </Bloco>
    </div>
  );
}
