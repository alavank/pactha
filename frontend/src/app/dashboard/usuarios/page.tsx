"use client";
// A TELA DE USUÁRIOS — só a lista, e um botão.
//
// ⚠️ ELA TINHA TRÊS CARDS DE FORMULÁRIO ANTES DA LISTA até 05/09/2026: «Novo
// usuário», «Municípios com acesso» e «Telas com acesso». Quem entrava aqui para
// conferir quem tem o quê descia por três formulários primeiro, e quem entrava
// para cadastrar alguém preenchia o de cima, salvava, procurava a pessoa lá
// embaixo e abria mais dois modais. Os três viraram um modal só
// (`UsuarioModal.tsx`), e a página passou a fazer uma coisa: mostrar as pessoas.
//
// ⚠️ SAIU TAMBÉM o botão «Modelos de permissão», com o subsistema inteiro
// (decisão do dono). O atalho que ficou no lugar — copiar o acesso de outro
// usuário — mora DENTRO do modal, que é onde ele é usado.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check, Copy, KeyRound, Loader2, Pencil, Power, Search, ShieldCheck, Trash2,
  UserPlus, Users, X,
} from "lucide-react";
import api from "@/lib/api";
import { TELA_LABELS } from "@/lib/telas";
import { agruparPorEstado, ufsDaCarteira } from "@/lib/estadual";
import { TELAS } from "@/lib/telas";
import { ehSuperAdmin } from "@/lib/conta";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Aviso, Bloco, BlocoHead, Campos, ItemLinha, Lista, Modal, Selo, Vazio,
  situacaoTom,
} from "@/components/ui/superficies";
import UsuarioModal, { type UsuarioAlvo } from "./UsuarioModal";
import {
  buscarCatalogo, buscarConcedidas, buscarMinhas, filtrarCatalogoPorUfs,
  resumoPorRecurso, type Catalogo, type MinhasPermissoes,
} from "@/lib/permissoes";
import { listarParametros, type Parametro } from "@/lib/parametros";
import type { MapaEscopos } from "@/lib/escopo";
import { TituloTela } from "@/components/TituloTela";

interface Usuario extends UsuarioAlvo {
  must_change_password?: boolean;
}

interface Municipio { id: number; nome: string; uf: string; }

interface SenhaResp {
  id: number; email: string; name: string; senha_temporaria: string;
}

// ⚠️ SEMENTE, e não a fonte: desde 11/08/2026 os perfis são CADASTRÁVEIS por
// cliente (Configurações › Parâmetros, tipo `perfil_usuario`). Esta lista vale
// enquanto a chamada não voltou, ou se ela falhar — um seletor vazio impediria
// de cadastrar gente.
//
// ⭐ «Prefeito» SAIU em 05/09/2026, a pedido do dono ("nao quero mais a opçao
// prefeito ativada"). Tirar daqui não bastava: o rótulo está semeado na tabela
// `parametros` dos cinco bancos, e quem o desativa lá é
// `migrations/desativa_perfil_prefeito.sql`. As duas coisas no mesmo commit.
const ROLES = [
  { value: "admin", label: "Administrador" },
  { value: "usuario", label: "Usuário" },
];

/** Rótulos de EXIBIÇÃO — incluem papéis que a tela NÃO oferece mais.
 *
 *  Cada um está aqui por um motivo: `prefeito` e `analyst` são legados que
 *  contas antigas ainda carregam, e `viewer` é a credencial sintética do link
 *  de TV. Sem a tradução, o seletor mostraria a chave crua — que é exatamente o
 *  defeito que a lista fixa já teve uma vez com "analyst". */
const ROLE_LABELS: Record<string, string> = {
  ...Object.fromEntries(ROLES.map((r) => [r.value, r.label])),
  user: "Usuário",
  prefeito: "Prefeito",
  analyst: "Analista",
  viewer: "Visualizador",
};

export default function UsuariosPage() {
  const [users, setUsers] = useState<Usuario[]>([]);
  const [municipios, setMunicipios] = useState<Municipio[]>([]);
  const [eu, setEu] = useState<Usuario | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  const [catalogo, setCatalogo] = useState<Catalogo | null>(null);
  const [minhas, setMinhas] = useState<MinhasPermissoes | null>(null);
  const [concedidas, setConcedidas] = useState<Record<string, string[]>>({});
  const [escopos, setEscopos] = useState<Record<string, MapaEscopos>>({});
  const [perfis, setPerfis] = useState<Parametro[]>([]);

  const [busca, setBusca] = useState("");
  /** `undefined` = fechado; `null` = criando; objeto = editando. */
  const [modal, setModal] = useState<Usuario | null | undefined>(undefined);
  const [senhaGerada, setSenhaGerada] = useState<SenhaResp | null>(null);
  const [copiado, setCopiado] = useState(false);
  const [excluir, setExcluir] = useState<Usuario | null>(null);
  const [excluirTexto, setExcluirTexto] = useState("");
  const [excluindo, setExcluindo] = useState(false);

  const carregar = useCallback(async () => {
    setLoading(true);
    try {
      const [ru, rm, rme, rcat, rminhas, rconc, rperfis] = await Promise.all([
        api.get<Usuario[]>("/users"),
        api.get<Municipio[]>("/municipios"),
        // Falha isolada de propósito: saber quem sou eu é um EXTRA (serve ao
        // aviso de auto-edição). Dentro do `Promise.all` cru, um /auth/me que
        // tropeçasse derrubaria a listagem inteira junto.
        api.get<Usuario>("/auth/me").catch(() => null),
        buscarCatalogo().catch(() => null),
        buscarMinhas().catch(() => null),
        buscarConcedidas().catch(() => ({ concedidas: {}, escopos: {} })),
        listarParametros("perfil_usuario", true).catch(() => [] as Parametro[]),
      ]);
      setUsers(ru.data);
      setMunicipios(Array.isArray(rm.data) ? rm.data : []);
      setEu(rme?.data ?? null);
      setCatalogo(rcat);
      setMinhas(rminhas);
      setConcedidas(rconc.concedidas);
      setEscopos(rconc.escopos);
      setPerfis(rperfis);
      setErro(null);
    } catch (e: unknown) {
      setErro((e as { response?: { status?: number } })?.response?.status === 403
        ? "Você não tem acesso à tela de Usuários."
        : "Erro ao carregar usuários.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    carregar();
  }, [carregar]);

  /** ⭐ OS ESTADOS QUE ESTA CARTEIRA ATENDE — a base de todo o recorte por UF.
   *
   *  ⚠️ Vem de `/municipios` (a carteira INTEIRA), e NÃO do município escolhido
   *  na barra lateral — que é o que o MENU usa. A diferença é deliberada: quem
   *  concede acesso concede para todos os municípios da pessoa, não para o que
   *  está selecionado em cima. Cadastrar alguém para o Espírito Santo não pode
   *  depender de ter trocado o seletor para uma cidade capixaba antes. */
  const ufsCart = useMemo(() => ufsDaCarteira(municipios), [municipios]);

  /** As telas que ESTE tenant oferece — as federais mais as dos estados dele. */
  const telasDoAmbiente = useMemo(() => {
    const g = agruparPorEstado(TELAS, ufsCart);
    return new Set([...g.federais, ...g.estados.flatMap((e) => e.itens)]
      .map((t) => t.key));
  }, [ufsCart]);

  /** O catálogo recortado para a carteira — UMA VEZ SÓ, aqui, para o contador
   *  do cabeçalho e a árvore do modal contarem a mesma coisa. */
  const catalogoUf = useMemo(
    () => filtrarCatalogoPorUfs(catalogo, ufsCart), [catalogo, ufsCart]);

  const municipioUnico = municipios.length === 1;

  const permsDe = useCallback(
    (u: UsuarioAlvo) => concedidas[String(u.id)] ?? [], [concedidas]);
  const escoposDe = useCallback(
    (u: UsuarioAlvo): MapaEscopos => escopos[String(u.id)] ?? {}, [escopos]);
  const telasDe = useCallback((u: UsuarioAlvo) => u.telas ?? [], []);
  const municipiosDe = useCallback((u: UsuarioAlvo) => u.municipio_ids ?? [], []);

  const munNome = useCallback((id: number) => {
    const m = municipios.find((x) => x.id === id);
    return m ? `${m.nome}-${m.uf}` : `#${id}`;
  }, [municipios]);

  /* Os perfis do CLIENTE vencem a semente. Duas listas de propósito:
     · `perfisOferecidos` — só os ATIVOS: é o que o seletor propõe;
     · `rotuloDoPerfil`   — inclui os desativados, porque uma conta antiga pode
       carregar um perfil que saiu do cardápio (o «Prefeito» é exatamente esse
       caso desde 05/09/2026), e mostrar a chave crua é o defeito conhecido. */
  const perfisOferecidos = perfis.length
    ? perfis.filter((p) => p.ativo).map((p) => ({ value: p.valor, label: p.rotulo }))
    : ROLES;
  const rotuloDoPerfil = (v: unknown) => {
    const chave = String(v ?? "");
    const achado = perfis.find((p) => p.valor === chave);
    return achado ? achado.rotulo : (ROLE_LABELS[chave] ?? chave);
  };

  const podeConceder = !!minhas
    && (minhas.super_admin || minhas.chaves.includes("usuarios.conceder"));

  const resetarSenha = async (u: Usuario) => {
    if (!confirm(`Resetar a senha de ${u.name} (${u.email})?\nEla será obrigada a trocar no próximo login.`)) return;
    try {
      const r = await api.post<SenhaResp>(`/users/${u.id}/reset-password`);
      setSenhaGerada(r.data);
    } catch { alert("Erro ao resetar senha"); }
  };

  const toggleAtivo = async (u: Usuario) => {
    try {
      await api.patch(`/users/${u.id}`, { active: !u.active });
      await carregar();
    } catch (e: unknown) {
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Erro");
    }
  };

  const confirmarExclusao = async () => {
    if (!excluir) return;
    setExcluindo(true);
    try {
      await api.delete(`/users/${excluir.id}`);
      setExcluir(null); setExcluirTexto("");
      await carregar();
    } catch (e: unknown) {
      alert((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || "Erro ao excluir");
    } finally { setExcluindo(false); }
  };

  const copiarTexto = (s: string) => {
    navigator.clipboard.writeText(s);
    setCopiado(true);
    setTimeout(() => setCopiado(false), 2000);
  };

  const visiveis = useMemo(() => {
    const q = busca.trim().toLowerCase();
    if (!q) return users;
    return users.filter((u) =>
      u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q));
  }, [users, busca]);

  const ativos = users.filter((u) => u.active).length;
  const pendentes = users.filter((u) => u.must_change_password).length;
  const semAcesso = users.filter(
    (u) => u.active && !ehSuperAdmin(u) && (u.telas ?? []).length === 0).length;
  // Conta ATIVA que entra e não faz nada. ⚠️ DEIXOU DE SER SÓ INFORMATIVO em
  // 05/09/2026: com `AUTHZ_MODO=bloqueio`, zero caixinha marcada É zero acesso.
  const semPermissao = users.filter(
    (u) => u.active && !ehSuperAdmin(u) && permsDe(u).length === 0).length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4"
           style={{ borderColor: "var(--bi-line)" }}>
        <div className="min-w-0">
          <TituloTela>Usuários</TituloTela>
          <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
            Acesso à plataforma PACTHA, concedido usuário a usuário.
          </p>
        </div>
        <Button
          onClick={() => setModal(null)}
          disabled={!catalogoUf}
          title={catalogoUf
            ? "Cadastrar uma pessoa e definir o acesso dela"
            : "Não foi possível carregar o catálogo de permissões. Recarregue a tela."}
          className="hover:opacity-90"
          style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
        >
          <UserPlus className="size-4 mr-1" /> Criar usuário
        </Button>
      </div>

      {erro && (
        <div className="bi-card flex flex-wrap items-center gap-2 p-3 text-[12px]"
             style={{ color: "var(--bi-muted)" }}>
          <Selo tom="critico">Acesso</Selo>
          {erro}
        </div>
      )}

      {semPermissao > 0 && !loading && (
        /* ⚠️ ESTE AVISO NASCEU COM O `bloqueio`. Enquanto a trava estava em modo
           aviso, conta sem caixinha funcionava do mesmo jeito e o número era só
           curiosidade. Agora ele é a lista de quem para de funcionar. */
        <Aviso tom="atencao" icon={ShieldCheck} className=""
               titulo={`${semPermissao} conta(s) ativa(s) sem nenhuma ação marcada.`}>
          <p className="text-[11px]" style={{ color: "var(--bi-muted)" }}>
            As permissões por ação estão <b>valendo</b>: sem nenhuma marcada, a
            pessoa entra e não consegue abrir nada. Edite cada uma e libere o que
            ela precisa.
          </p>
        </Aviso>
      )}

      <Bloco className="p-3">
        <BlocoHead
          icon={Users}
          titulo="Usuários cadastrados"
          sub={loading ? "Carregando..." : (
            <>
              {ativos} ativo(s)
              {pendentes > 0 && <> · {pendentes} com troca de senha pendente</>}
              {semAcesso > 0 && (
                <> · <span style={{ color: "var(--bi-crit-ink)" }}>{semAcesso} sem tela nenhuma</span></>
              )}
            </>
          )}
          right={loading ? undefined : <span className="bi-num text-[13px]">{users.length}</span>}
        />

        <div className="relative mb-3">
          <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2"
                  style={{ color: "var(--bi-faint)" }} />
          <Input value={busca} onChange={(e) => setBusca(e.target.value)}
                 placeholder="Buscar por nome ou e-mail" className="pl-7" />
        </div>

        {loading ? (
          <Lista>
            {Array.from({ length: 5 }).map((_, i) => (
              <li key={i} className="bi-card-flat h-[86px] animate-pulse" />
            ))}
          </Lista>
        ) : visiveis.length === 0 ? (
          <Vazio>
            {users.length === 0
              ? "Nenhum usuário cadastrado. Use «Criar usuário» para começar."
              : "Nenhum usuário encontrado para esta busca."}
          </Vazio>
        ) : (
          <Lista>
            {visiveis.map((u) => {
              const superAdmin = ehSuperAdmin(u);
              const muns = u.municipio_ids ?? [];
              const telas = u.telas ?? [];
              const perms = permsDe(u);
              const campos = [
                ...(municipioUnico ? [] : [{
                  rotulo: "Municípios",
                  valor: superAdmin ? "Todos"
                    : muns.length === 0 ? "Nenhum"
                    : muns.length === 1 ? munNome(muns[0])
                    : `${muns.length} municípios`,
                  tom: (!superAdmin && muns.length === 0 ? "critico" : "normal") as "critico" | "normal",
                  title: superAdmin ? "Super-admin: enxerga todos os municípios"
                    : muns.length > 0 ? muns.map(munNome).join(", ")
                    : "Sem município: o usuário não enxerga dado nenhum",
                }]),
                {
                  rotulo: "Telas",
                  valor: superAdmin ? "Todas"
                    : telas.length === 0 ? "Nenhuma" : `${telas.length} telas`,
                  tom: (!superAdmin && telas.length === 0 ? "critico" : "normal") as "critico" | "normal",
                  title: superAdmin ? "Super-admin: enxerga todas as telas"
                    : telas.length > 0 ? telas.map((t) => TELA_LABELS[t] || t).join(", ")
                    : "Sem tela: o menu do usuário fica vazio",
                },
                {
                  rotulo: "Permissões",
                  valor: superAdmin ? "Todas"
                    : !catalogoUf ? "—"
                    : perms.length === 0 ? "Nenhuma"
                    : `${perms.length} de ${catalogoUf.total}`,
                  tom: (!superAdmin && catalogoUf && perms.length === 0
                    ? "critico" : "normal") as "critico" | "normal",
                  title: superAdmin ? "Super-admin: pode tudo"
                    : !catalogoUf ? "Catálogo de permissões indisponível"
                    : perms.length > 0
                      // O resumo legível, e não 96 chaves cruas: quem confere lê
                      // "Cofre de senhas: Ver, Revelar a senha", não
                      // `cofre.revelar`.
                      ? resumoPorRecurso(catalogoUf, new Set(perms), undefined, escoposDe(u)).join(" · ")
                      : "Nenhuma ação liberada: a pessoa entra e não faz nada",
                },
                {
                  rotulo: "Função",
                  valor: u.funcao || "—",
                  title: u.funcao || undefined,
                },
                {
                  rotulo: "Situação",
                  valor: u.active ? "Ativo" : "Inativo",
                  title: u.active ? "Pode entrar no sistema" : "Login bloqueado",
                },
              ];
              return (
                <ItemLinha
                  key={u.id}
                  titulo={
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate">{u.name}</span>
                      <Selo>{rotuloDoPerfil(u.role)}</Selo>
                      {superAdmin && (
                        <Selo tom="acento" title="Conta da Alavank: acesso total à plataforma.">
                          super-admin
                        </Selo>
                      )}
                      {u.must_change_password && (
                        <Selo tom={situacaoTom("troca de senha pendente")}
                              title="O usuário ainda não trocou a senha temporária.">
                          troca pendente
                        </Selo>
                      )}
                    </span>
                  }
                  valor={<span style={{ color: "var(--bi-faint)" }}>#{u.id}</span>}
                  meta={<span className="truncate" title={u.email}>{u.email}</span>}
                  acao={
                    <div className="flex flex-wrap items-center justify-end gap-1">
                      <Button size="sm" variant="outline" className="h-7 text-[11px]"
                              onClick={() => setModal(u)}
                              disabled={!catalogoUf || (superAdmin && !ehSuperAdmin(eu))}
                              title={!catalogoUf
                                ? "Catálogo de permissões indisponível. Recarregue a tela."
                                : "Editar cadastro, municípios, telas e permissões"}>
                        <Pencil className="size-3 mr-1" /> Editar
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]"
                              onClick={() => resetarSenha(u)}
                              title="Resetar senha" aria-label={`Resetar senha de ${u.name}`}>
                        <KeyRound className="size-3" />
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 px-2 text-[11px]"
                              onClick={() => toggleAtivo(u)}
                              title={u.active ? "Desativar" : "Ativar"}
                              aria-label={`${u.active ? "Desativar" : "Ativar"} ${u.name}`}>
                        <Power className="size-3" />
                      </Button>
                      {u.id !== eu?.id && !superAdmin && (
                        <Button size="sm" variant="outline"
                                className="h-7 px-2 text-[11px] border-[var(--bi-crit)]/40 hover:bg-[var(--bi-crit)]/10"
                                style={{ color: "var(--bi-crit)" }}
                                onClick={() => { setExcluir(u); setExcluirTexto(""); }}
                                title="Excluir usuário" aria-label={`Excluir ${u.name}`}>
                          <Trash2 className="size-3" />
                        </Button>
                      )}
                    </div>
                  }
                >
                  <Campos cols={municipioUnico ? 4 : 5} campos={campos} />
                </ItemLinha>
              );
            })}
          </Lista>
        )}
      </Bloco>

      {/* O MODAL ÚNICO — cria e edita. `catalogoUf` no guarda porque ele é
          obrigatório: sem catálogo não há árvore para desenhar, e o botão que
          abre já vem desligado nesse caso. */}
      {modal !== undefined && catalogoUf && (
        <UsuarioModal
          alvo={modal}
          catalogo={catalogoUf}
          minhas={minhas}
          municipios={municipios}
          perfis={perfisOferecidos}
          telasDoAmbiente={telasDoAmbiente}
          concedidas={modal ? permsDe(modal) : []}
          escopos={modal ? escoposDe(modal) : {}}
          souEu={!!eu && !!modal && eu.id === modal.id}
          podeConceder={podeConceder}
          outros={users.filter((o) =>
            o.id !== modal?.id && !ehSuperAdmin(o) && !o.email.endsWith("@painel.local"))}
          permsDe={permsDe}
          telasDe={telasDe}
          municipiosDe={municipiosDe}
          onFechar={() => setModal(undefined)}
          onSalvo={carregar}
        />
      )}

      {/* Senha temporária gerada. ⚠️ Aparece no reset E na criação: o POST de
          criação devolve a senha no corpo, e é o único jeito de entregar a conta
          à pessoa. */}
      {senhaGerada && (
        <Modal aberto superficie maxW="max-w-md" rotulo="Senha temporária gerada"
               onFechar={() => setSenhaGerada(null)}>
          <div className="p-4">
            <BlocoHead icon={KeyRound} titulo="Senha temporária gerada"
                       sub={`${senhaGerada.name} — ${senhaGerada.email}`}
                       right={
                         <button type="button" onClick={() => setSenhaGerada(null)} aria-label="Fechar">
                           <X className="size-4" style={{ color: "var(--bi-faint)" }} />
                         </button>
                       } />
            <div className="flex flex-col gap-3">
              <div className="flex gap-2">
                <code className="bi-card-flat flex-1 select-all px-3 py-2 font-mono text-[13px]"
                      style={{ color: "var(--bi-text)" }}>
                  {senhaGerada.senha_temporaria}
                </code>
                <Button size="sm" variant="outline"
                        onClick={() => copiarTexto(senhaGerada.senha_temporaria)}
                        title="Copiar senha" aria-label="Copiar senha">
                  {copiado
                    ? <Check className="size-4" style={{ color: "var(--bi-ok-ink)" }} />
                    : <Copy className="size-4" />}
                </Button>
              </div>
              <p className="flex flex-wrap items-center gap-1.5 text-[11px]"
                 style={{ color: "var(--bi-muted)" }}>
                <Selo tom="atencao">Atenção</Selo>
                Esta senha NÃO será exibida novamente. Não envie por e-mail em
                texto puro.
              </p>
              <Button className="w-full hover:opacity-90"
                      style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                      onClick={() => setSenhaGerada(null)}>
                Fechar
              </Button>
            </div>
          </div>
        </Modal>
      )}

      {/* Excluir: confirmação DIGITADA — é a única ação irreversível da tela, e
          o confirm() nativo não basta. */}
      {excluir && (
        <Modal aberto superficie maxW="max-w-md" rotulo="Excluir usuário"
               onFechar={() => setExcluir(null)}>
          <div className="p-4">
            <BlocoHead icon={Trash2} titulo="Excluir usuário"
                       sub={`${excluir.name} — ${excluir.email}`}
                       right={
                         <button type="button" onClick={() => setExcluir(null)} aria-label="Fechar">
                           <X className="size-4" style={{ color: "var(--bi-faint)" }} />
                         </button>
                       } />
            <div className="flex flex-col gap-3">
              <p className="text-[12px]" style={{ color: "var(--bi-muted)" }}>
                A conta é <b style={{ color: "var(--bi-crit)" }}>removida definitivamente</b>:
                acesso, permissões e cadastro somem. O que a pessoa criou
                (relatórios, documentos, anotações) <b>permanece no sistema</b> com a
                autoria &ldquo;usuário removido&rdquo;, e a trilha de auditoria fica intacta.
                Não há desfazer.
              </p>
              <div>
                <div className="mb-1 text-[11px]" style={{ color: "var(--bi-muted)" }}>
                  Para confirmar, digite o e-mail da conta: <b>{excluir.email}</b>
                </div>
                <Input value={excluirTexto} onChange={(e) => setExcluirTexto(e.target.value)}
                       placeholder={excluir.email} autoFocus />
              </div>
              <Button className="w-full hover:opacity-90"
                      style={{ background: "var(--bi-crit)", color: "#fff" }}
                      onClick={confirmarExclusao}
                      disabled={excluindo
                        || excluirTexto.trim().toLowerCase() !== excluir.email.toLowerCase()}>
                {excluindo ? <Loader2 className="size-4 animate-spin mr-1" /> : <Trash2 className="size-4 mr-1" />}
                Excluir definitivamente
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
