"use client";

import React, { useEffect, useState } from "react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import { useUfDoMunicipio } from "@/lib/useUfDoMunicipio";
import { Eye, EyeOff, KeyRound, Lock, Plus, Trash2, ExternalLink, Pencil, Zap } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Bloco,
  BlocoHead,
  Campos,
  ItemLinha,
  Lista,
  Numero,
  Selo,
  Vazio,
} from "@/components/ui/superficies";
import toast from "react-hot-toast";
import { TituloTela } from "@/components/TituloTela";

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
  automation_key?: string;
}

const CATEGORIAS = ["Federal", "Estadual", "Saude", "Educacao", "Assistencia Social", "Outro"];

// Detecta se a senha é na verdade um payload de sessão capturada
// (cookies JSON em vez de senha texto) — vem do bookmarklet/extensão PACTHA.
function parseSessionPayload(senha?: string): { isSession: boolean; cookieCount?: number; httpOnlyCount?: number; url?: string; domain?: string } {
  if (!senha || senha.length < 30) return { isSession: false };
  const s = senha.trim();
  if (!s.startsWith("{") || !s.includes('"cookies"')) return { isSession: false };
  try {
    const obj = JSON.parse(s);
    if (obj.format === "cookies_full" && Array.isArray(obj.cookies)) {
      const cookies = obj.cookies;
      return {
        isSession: true,
        cookieCount: cookies.length,
        httpOnlyCount: cookies.filter((c: { httpOnly?: boolean }) => c.httpOnly).length,
        url: obj.url,
        domain: obj.domain,
      };
    }
  } catch { /* ignore */ }
  return { isSession: false };
}

// Sistemas com integracao automatica (scraper) - URL/categoria/automation_key pre-vinculados.
// `ufs` marca integracao que so existe em certos estados: o SIGCON e o sistema
// de convenios de MINAS, e a lista o oferecia num municipio gaucho — onde nao
// ha SIGCON para logar. Sem `ufs` = vale em qualquer estado.
const INTEGRACOES: Array<{
  automation_key: string; label: string; sistema: string; url: string;
  categoria: string; usuario_hint: string; senha_hint: string; ufs?: string[];
}> = [
  {
    automation_key: "govbr",
    label: "gov.br SSO (acesso único federal)",
    sistema: "gov.br - Conta Unica",
    url: "https://www.gov.br",
    categoria: "Federal",
    usuario_hint: "Login (usuário, email ou CPF)",
    senha_hint: "Senha",
  },
  {
    automation_key: "sigcon",
    label: "SIGCON-MG - Convênios Estaduais (login do convenente do município)",
    sistema: "SIGCON-MG",
    url: "https://www.convenios.mg.gov.br/sigconv2/public/pages/login.jsf",
    categoria: "Estadual",
    usuario_hint: "CPF do gestor do Convenente (cadastrado no SIGCON-MG deste município)",
    senha_hint: "Senha do SIGCON-MG",
    ufs: ["MG"],
  },
  {
    automation_key: "fns",
    label: "FNS - Fundo Nacional de Saúde (login próprio)",
    sistema: "FNS - Fundo Nacional de Saude",
    url: "https://consultafns.saude.gov.br",
    categoria: "Saude",
    usuario_hint: "Login (CPF, email ou usuário)",
    senha_hint: "Senha do portal",
  },
  {
    automation_key: "sismob",
    label: "SISMOB - Obras de Saúde",
    sistema: "SISMOB - Obras de Saude",
    url: "https://sismobcidadao.saude.gov.br",
    categoria: "Saude",
    usuario_hint: "Login (CPF, email ou usuário)",
    senha_hint: "Senha do portal",
  },
  {
    automation_key: "simec",
    label: "SIMEC / PAR - Educação (FNDE)",
    sistema: "SIMEC/PAR - FNDE",
    url: "https://simec.mec.gov.br/par/",
    categoria: "Educacao",
    usuario_hint: "Login (CPF, email ou usuário)",
    senha_hint: "Senha do portal",
  },
  {
    automation_key: "suas",
    label: "Estrutura SUAS - Assistência (MDS)",
    sistema: "Estrutura SUAS",
    url: "https://estruturasuas.mds.gov.br",
    categoria: "Assistencia Social",
    usuario_hint: "Login (CPF, email ou usuário)",
    senha_hint: "Senha do portal",
  },
  {
    automation_key: "investsus",
    label: "InvestSUS - Painel Saúde",
    sistema: "InvestSUS",
    url: "https://investsuspaineis.saude.gov.br",
    categoria: "Saude",
    usuario_hint: "Login (CPF, email ou usuário)",
    senha_hint: "Senha do portal",
  },
];

/* NAO existe helper de tom nesta tela, e nao e esquecimento: credencial guardada
   nao tem situacao. Nada aqui esta "cancelado", "pendente" ou "aprovado" — os
   dois selos (integracao e avulsa) sao classificacao, e classificacao e cinza.
   A regra de cor do sistema e a `situacaoTom` de superficies.tsx e so vale onde
   ha situacao de verdade; escrever uma variante local aqui foi exatamente o
   defeito que o lote anterior teve que consertar. */

/* Rotulo de campo de FORMULARIO: 11px em --bi-muted. O 9px MAIUSCULO e o
   desenho reservado ao rotulo de DADO (<Campos>) — usar os dois iguais faz o
   formulario se passar por resultado. */
const ROTULO = "mb-1 block text-[11px]";
const ROTULO_COR: React.CSSProperties = { color: "var(--bi-muted)" };

/* A dica entre parenteses ao lado do rotulo (o "usuario_hint" da integracao):
   um degrau abaixo do rotulo, porque e apoio e nao o nome do campo. */
const HINT = "ml-1 text-[10px]";
const HINT_COR: React.CSSProperties = { color: "var(--bi-faint)" };

/* Escolha nativa com os tokens da identidade (mesmo desenho do <select> da tela
   de RM). O `border` pelado herdava a cor de borda do tema antigo. */
const SELECT_CLS = "h-9 w-full rounded-md border px-2 text-[13px]";
const SELECT_ESTILO: React.CSSProperties = {
  borderColor: "var(--bi-line)",
  background: "var(--bi-surface)",
  color: "var(--bi-text)",
};

/* Botao de acao do cartao: cinza no repouso. Editar era violeta e remover era
   vermelho — duas cores de enfeite em toda linha. Numa tela de credenciais isso
   pesa dobrado: o vermelho precisa continuar disponivel para alerta de verdade,
   e nao gasto num botao que esta sempre ali. A confirmacao do remover continua
   sendo o `confirm()`, nao a cor. */
const CLS_ACAO =
  "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition-colors bi-hover";
const ESTILO_ACAO: React.CSSProperties = {
  background: "var(--bi-surface)",
  border: "1px solid var(--bi-line)",
  color: "var(--bi-muted)",
};

/* Botao solido da identidade: quase preto no claro, menta no escuro. */
const ESTILO_CTA: React.CSSProperties = { background: "var(--bi-cta)", color: "var(--bi-cta-ink)" };

/* Link discreto: sublinhado na cor do texto. A tela nao gasta cor em navegacao —
   o sublinhado ja diz que e clicavel. */
const CLS_LINK = "underline underline-offset-2 hover:opacity-70";
const ESTILO_LINK: React.CSSProperties = { color: "var(--bi-text)" };

export default function CofrePage() {
  const { municipioId } = useMunicipio();
  // "" = UF ainda carregando: mostra tudo, para a lista não piscar em MG.
  const ufAmbiente = useUfDoMunicipio();
  const integracoesDaUf = INTEGRACOES.filter(
    (i) => !i.ufs || !ufAmbiente || i.ufs.includes(ufAmbiente),
  );

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

  // Edicao de uma senha existente (troca usuario/senha/observacao sem perder a integracao)
  const [editItem, setEditItem] = useState<Senha | null>(null);
  const [editForm, setEditForm] = useState({ usuario: "", senha: "", observacao: "" });

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
      toast.error("Sistema obrigatório");
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

  const openEdit = (s: Senha) => {
    setEditItem(s);
    setEditForm({ usuario: s.usuario || "", senha: "", observacao: s.observacao || "" });
  };

  const handleUpdate = async () => {
    if (!editItem) return;
    // senha so e enviada se preenchida (em branco = mantem a atual)
    const payload: Record<string, string> = {
      usuario: editForm.usuario,
      observacao: editForm.observacao,
    };
    if (editForm.senha) payload.senha = editForm.senha;
    try {
      await api.put(`/cofre/${editItem.id}`, payload);
      toast.success(editForm.senha ? "Senha atualizada" : "Dados atualizados");
      setEditItem(null);
      fetchSenhas();
    } catch {
      toast.error("Erro ao atualizar");
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
    // Mesmo estado vazio de CAUC, SISMOB, Sessoes e Gestao: a peca `<Vazio>`,
    // nao uma caixa de 16rem escrita a mao.
    return <Vazio>Selecione um município para visualizar o cofre.</Vazio>;
  }

  const grouped = senhas.reduce((acc, s) => {
    const cat = s.categoria || "Outro";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(s);
    return acc;
  }, {} as Record<string, Senha[]>);

  // A pergunta que o gestor faz ao abrir o cofre nao e "quantas senhas tenho",
  // e "quantas delas as automacoes usam" — uma credencial integrada que vence
  // derruba um scraper inteiro.
  const comIntegracao = senhas.filter((s) => !!s.automation_key).length;

  return (
    <div className="space-y-4">
      {/* `border-b pb-4` e `mt-1`: o mesmo cabecalho de pagina de Parlamentares
          e das outras sete telas do lote. A acao a direita continua no lugar. */}
      <div
        className="flex flex-wrap items-start justify-between gap-2 border-b pb-4"
        style={{ borderColor: "var(--bi-line)" }}
      >
        <div>
          <TituloTela>Cofre de Senhas</TituloTela>
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Senhas centralizadas dos sistemas governamentais para este município
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger
            render={
              <Button style={ESTILO_CTA} className="hover:opacity-90">
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
              {/* FLAG INTEGRACAO - controla todo o resto.
                  Era um painel violeta com texto violeta dentro: a cor mais
                  forte da tela gasta num controle de formulario. Virou o mesmo
                  cinza dos demais blocos — o que decide continua sendo a caixa
                  marcada, nao a moldura. */}
              <div className="bi-card-flat p-3">
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    checked={isIntegracao}
                    onChange={(e) => handleToggleIntegracao(e.target.checked)}
                    className="mt-0.5 size-4"
                    /* accentColor acompanha claro/escuro pelo token, em vez de
                       deixar o navegador pintar de azul do sistema. */
                    style={{ accentColor: "var(--bi-cta)" }}
                  />
                  <div className="flex-1">
                    <div className="text-[13px] font-medium" style={{ color: "var(--bi-text)" }}>
                      Integração com sistema PACTHA
                    </div>
                    <div className="mt-0.5 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                      {isIntegracao
                        ? "Selecione o sistema abaixo. Só precisa preencher usuário e senha - o resto já vem configurado."
                        : "Cadastro livre - você preenche tudo manualmente, sem automação."}
                    </div>
                  </div>
                </label>
              </div>

              {isIntegracao ? (
                <>
                  {/* MODO INTEGRACAO: dropdown de sistemas pre-configurados */}
                  <div>
                    <label className={ROTULO} style={ROTULO_COR}>Sistema integrado *</label>
                    <select
                      className={SELECT_CLS}
                      style={SELECT_ESTILO}
                      value={integracaoSelecionada}
                      onChange={(e) => handleSelecionarIntegracao(e.target.value)}
                    >
                      <option value="">-- Selecione o sistema --</option>
                      {integracoesDaUf.map((i) => (
                        <option key={i.automation_key} value={i.automation_key}>
                          {i.label}
                        </option>
                      ))}
                    </select>
                    {integracaoSelecionada && (
                      <div
                        className="bi-card-flat mt-2 space-y-0.5 p-2 text-[11px] leading-snug"
                        style={{ color: "var(--bi-text)" }}
                      >
                        <div>
                          <span style={{ color: "var(--bi-faint)" }}>URL:</span>{" "}
                          <a
                            href={form.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={CLS_LINK}
                            style={ESTILO_LINK}
                          >
                            {form.url}
                          </a>
                        </div>
                        <div>
                          <span style={{ color: "var(--bi-faint)" }}>Categoria:</span> {form.categoria}
                        </div>
                        <div>
                          <span style={{ color: "var(--bi-faint)" }}>Automação:</span> ativa via scraper{" "}
                          <code
                            className="rounded px-1 font-mono"
                            style={{ background: "var(--bi-line)", color: "var(--bi-muted)" }}
                          >
                            {form.automation_key}
                          </code>
                        </div>
                      </div>
                    )}
                  </div>

                  {integracaoSelecionada && (
                    <>
                      <div>
                        <label className={ROTULO} style={ROTULO_COR}>
                          Usuário *
                          <span className={HINT} style={HINT_COR}>
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
                        <label className={ROTULO} style={ROTULO_COR}>
                          Senha *
                          <span className={HINT} style={HINT_COR}>
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
                        <label className={ROTULO} style={ROTULO_COR}>Observação</label>
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
                    <label className={ROTULO} style={ROTULO_COR}>Sistema *</label>
                    <Input
                      value={form.sistema}
                      onChange={(e) => setForm({ ...form, sistema: e.target.value })}
                      placeholder="Ex: TransfereGov, Portal interno, etc"
                    />
                  </div>
                  <div>
                    <label className={ROTULO} style={ROTULO_COR}>URL</label>
                    <Input
                      value={form.url}
                      onChange={(e) => setForm({ ...form, url: e.target.value })}
                      placeholder="https://..."
                    />
                  </div>
                  <div>
                    <label className={ROTULO} style={ROTULO_COR}>Usuário</label>
                    <Input
                      value={form.usuario}
                      onChange={(e) => setForm({ ...form, usuario: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className={ROTULO} style={ROTULO_COR}>Senha</label>
                    <Input
                      type="password"
                      value={form.senha}
                      onChange={(e) => setForm({ ...form, senha: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className={ROTULO} style={ROTULO_COR}>Categoria</label>
                    <select
                      className={SELECT_CLS}
                      style={SELECT_ESTILO}
                      value={form.categoria}
                      onChange={(e) => setForm({ ...form, categoria: e.target.value })}
                    >
                      {CATEGORIAS.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className={ROTULO} style={ROTULO_COR}>Observação</label>
                    <Input
                      value={form.observacao}
                      onChange={(e) => setForm({ ...form, observacao: e.target.value })}
                    />
                  </div>
                  <p className="text-[11px] italic" style={{ color: "var(--bi-faint)" }}>
                    Sem flag de integração = senha apenas armazenada (sem automação).
                  </p>
                </>
              )}
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDialogOpen(false)}>
                Cancelar
              </Button>
              <Button onClick={handleCreate} style={ESTILO_CTA} className="hover:opacity-90">
                Salvar
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Os tres numeros do topo respondem, antes de qualquer rolagem, quanto do
          cofre sustenta automacao. Ficam fora do carregamento e do vazio porque
          "0 de 0" nao e informacao. */}
      {!loading && senhas.length > 0 && (
        <div className="grid grid-cols-3 gap-3">
          <Numero icon={KeyRound} rotulo="Credenciais guardadas" valor={senhas.length} />
          <Numero
            icon={Zap}
            rotulo="Com integração"
            valor={comIntegracao}
            sub="usadas pelos scrapers do PACTHA"
          />
          <Numero
            icon={Lock}
            rotulo="Avulsas"
            valor={senhas.length - comIntegracao}
            sub="apenas armazenadas"
          />
        </div>
      )}

      {loading ? (
        /* Esqueleto sobre --bi-surface-2: em `bg-base-200` ele apontava para a
           cor do FUNDO da pagina e sumia. */
        <div className="space-y-1.5">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg" style={{ background: "var(--bi-surface-2)" }} />
          ))}
        </div>
      ) : senhas.length === 0 ? (
        <Vazio>Nenhuma senha cadastrada. Use o botão acima para adicionar.</Vazio>
      ) : (
        /* A CATEGORIA VIROU BLOCO E A SENHA VIROU CARTAO.
           Era um Card por categoria com molduras dentro (borda em volta de cada
           senha, hover cinza) — grade dentro de grade. Agora e o bloco-envelope
           da identidade com a pilha macia de itens, sem borda entre eles. Toda
           coluna continua na tela: sistema e titulo, integracao/avulsa viraram
           selo, e usuario/senha/endereco foram para <Campos>, em posicoes FIXAS
           iguais em todos os cartoes — e o que deixa o olho descer a coluna
           "Usuario" de uma linha para a outra como descia na tabela. */
        <div className="space-y-3">
          {Object.entries(grouped).map(([cat, items]) => (
            <Bloco key={cat} className="p-3">
              <BlocoHead icon={KeyRound} titulo={cat} sub={`${items.length} credencial(is)`} />
              <Lista>
                {items.map((s) => {
                  const revelada = revealedIds.has(s.id);
                  // O payload de sessao so pode ser lido depois de revelar: antes
                  // disso o que esta no estado e a mascara, que nunca casa.
                  const sess = revelada ? parseSessionPayload(s.senha) : { isSession: false };
                  return (
                    <ItemLinha
                      key={s.id}
                      /* Sem `onClick`: nao ha detalhe para abrir, e o titulo
                         precisa hospedar o link do portal — botao dentro de
                         botao nao e clicavel. */
                      titulo={
                        <span className="flex items-center gap-1.5">
                          <span className="min-w-0 truncate">{s.sistema}</span>
                          {s.url && (
                            <a
                              href={s.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              title={`Abrir ${s.url} em nova aba`}
                              className="shrink-0 transition-opacity hover:opacity-70"
                              style={{ color: "var(--bi-faint)" }}
                            >
                              <ExternalLink className="size-3.5" />
                            </a>
                          )}
                        </span>
                      }
                      meta={
                        s.automation_key ? (
                          <Selo title={`Automação ativa: o scraper "${s.automation_key}" usa esta credencial`}>
                            <span className="inline-flex items-center gap-1">
                              <Zap className="size-3" />
                              Integração · {s.automation_key}
                            </span>
                          </Selo>
                        ) : (
                          <Selo title="Sem automação — a senha fica apenas guardada">Avulsa</Selo>
                        )
                      }
                      acao={
                        <>
                          <button
                            onClick={() => openEdit(s)}
                            className={CLS_ACAO}
                            style={ESTILO_ACAO}
                            title="Editar / trocar senha"
                            aria-label="Editar / trocar senha"
                          >
                            <Pencil className="size-3.5" />
                          </button>
                          <button
                            onClick={() => handleDelete(s.id)}
                            className={CLS_ACAO}
                            style={ESTILO_ACAO}
                            title="Remover"
                            aria-label="Remover"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </>
                      }
                    >
                      <Campos
                        cols={3}
                        campos={[
                          {
                            rotulo: "Usuário",
                            valor: <span className="font-mono font-medium">{s.usuario || "—"}</span>,
                            title: s.usuario || undefined,
                          },
                          {
                            rotulo: "Senha",
                            valor: (
                              <span className="flex items-start gap-1.5">
                                {sess.isSession ? (
                                  /* Sessao capturada pelo bookmarklet: o valor e
                                     um JSON de cookies, nao uma senha — imprimir
                                     o JSON cru nao ajuda ninguem. O selo era
                                     azul com bolinha; azul aqui era enfeite, e
                                     "tem uma sessao guardada" nao e alerta. */
                                  <Selo
                                    /* O `title` repete a contagem porque a
                                       coluna e estreita: se o selo for cortado,
                                       o numero continua alcancavel. O dominio
                                       (que so o payload sabe) entra aqui. */
                                    title={[
                                      "Sessão capturada",
                                      `${sess.cookieCount} cookies`,
                                      sess.httpOnlyCount ? `${sess.httpOnlyCount} httpOnly` : null,
                                      sess.domain || sess.url,
                                    ]
                                      .filter(Boolean)
                                      .join(" · ")}
                                  >
                                    Sessão · {sess.cookieCount} cookies
                                    {sess.httpOnlyCount ? ` (${sess.httpOnlyCount} httpOnly)` : ""}
                                  </Selo>
                                ) : (
                                  /* Revelada quebra em varias linhas em vez de
                                     cortar com reticencias: quem revela quer LER
                                     o valor inteiro. Mascarada cabe sempre. */
                                  <span
                                    className={`min-w-0 flex-1 cursor-pointer font-mono font-medium ${
                                      revelada ? "whitespace-normal break-all" : "truncate"
                                    }`}
                                    onClick={() => copySenha(s)}
                                    title="Clique para copiar a senha"
                                  >
                                    {revelada ? s.senha || "-" : (s.senha_mascarada || "••••••••")}
                                  </span>
                                )}
                                {/* O olho fica fora do texto (shrink-0) para nao
                                    ser empurrado para fora da celula por uma
                                    senha longa — sem ele nao da para ocultar. */}
                                <button
                                  onClick={() => toggleReveal(s.id)}
                                  className="shrink-0 transition-opacity hover:opacity-70"
                                  style={{ color: "var(--bi-faint)" }}
                                  title={revelada ? "Ocultar senha" : "Revelar senha"}
                                  aria-label={revelada ? "Ocultar senha" : "Revelar senha"}
                                >
                                  {revelada ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                                </button>
                              </span>
                            ),
                          },
                          {
                            rotulo: "Endereço",
                            valor: s.url ? (
                              <a href={s.url} target="_blank" rel="noopener noreferrer" className={CLS_LINK} style={ESTILO_LINK}>
                                {s.url}
                              </a>
                            ) : (
                              "—"
                            ),
                            title: s.url || undefined,
                          },
                        ]}
                      />
                      {/* A observacao e frase livre: fica fora da grade, em linha
                          inteira, porque cortada com reticencias ela some. */}
                      {s.observacao && (
                        <p className="mt-1.5 text-[11px] leading-snug" style={{ color: "var(--bi-muted)" }}>
                          {s.observacao}
                        </p>
                      )}
                    </ItemLinha>
                  );
                })}
              </Lista>
            </Bloco>
          ))}
        </div>
      )}

      {/* Dialog de edicao (troca usuario/senha sem perder a integracao) */}
      <Dialog open={!!editItem} onOpenChange={(o) => { if (!o) setEditItem(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Editar — {editItem?.sistema}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <label className={ROTULO} style={ROTULO_COR}>Usuário</label>
              <Input
                value={editForm.usuario}
                onChange={(e) => setEditForm({ ...editForm, usuario: e.target.value })}
                placeholder="Login / CPF"
              />
            </div>
            <div>
              <label className={ROTULO} style={ROTULO_COR}>Nova senha</label>
              <Input
                type="password"
                value={editForm.senha}
                onChange={(e) => setEditForm({ ...editForm, senha: e.target.value })}
                placeholder="Deixe em branco para manter a senha atual"
              />
              <p className="mt-1 text-[10px]" style={{ color: "var(--bi-faint)" }}>
                Preencha para gravar uma nova senha; em branco mantém a atual.
              </p>
            </div>
            <div>
              <label className={ROTULO} style={ROTULO_COR}>Observação</label>
              <Input
                value={editForm.observacao}
                onChange={(e) => setEditForm({ ...editForm, observacao: e.target.value })}
                placeholder="Opcional"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditItem(null)}>
              Cancelar
            </Button>
            <Button onClick={handleUpdate} style={ESTILO_CTA} className="hover:opacity-90">
              Salvar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
