"use client";
import { useEffect, useState, Suspense, type ReactNode } from "react";
import { ExternalLink, RefreshCw, Info, ShieldCheck, Play } from "lucide-react";
import { useMunicipio } from "@/contexts/MunicipioContext";
import api from "@/lib/api";
import {
  Bloco,
  BlocoHead,
  Campos,
  ItemLinha,
  Lista,
  Selo,
  Vazio,
} from "@/components/ui/superficies";
import toast from "react-hot-toast";
import { TituloTela } from "@/components/TituloTela";

interface SessionStatus {
  has_session: boolean;
  has_cookies?: boolean;
  tipo?: "cookies" | "senha_apenas" | null;
  id?: number;
  atualizado_em?: string;
  observacao?: string;
}

interface TgSessionStatus {
  has_session: boolean;
  age_hours?: number;
  expired?: boolean;
  observacao?: string;
  updated_at?: string;
  message?: string;
  user_id_exp_minutes?: number;
  expira_em?: string;
  vinculo?: number;
  nivel?: number;
}

// Sistemas que suportam captura de sessao via bookmarklet
const PORTAIS = [
  { key: "govbr", nome: "gov.br (parcerias.transferegov)", url: "https://parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home" },
  { key: "siconv_legado", nome: "SICONV Legado (discricionárias) — Cláusula Suspensiva", url: "https://discricionarias.transferegov.sistema.gov.br/voluntarias/" },
  { key: "fns", nome: "FNS - Saúde", url: "https://consultafns.saude.gov.br" },
  { key: "simec", nome: "SIMEC/PAR - Educação", url: "https://simec.mec.gov.br" },
  { key: "sismob", nome: "SISMOB - Obras Saúde", url: "https://sismobcidadao.saude.gov.br" },
  { key: "suas", nome: "Estrutura SUAS", url: "https://estruturasuas.mds.gov.br" },
];

/** Caixa de alerta — o ÚNICO lugar colorido desta tela.
 *
 *  Antes a tela pintava tudo: cada portal tinha selo verde/amarelo, o aviso de
 *  segurança era um cartão inteiro laranja e a sessão válida ganhava caixa
 *  verde. Com nove coisas coloridas, a sessão expirada (a única que faz o
 *  scraper falhar) não se destacava de nada.
 *
 *  Agora só existem duas caixas, e as duas exigem ação AGORA: a sessão do
 *  parcerias.transferegov morre ~20 min após a captura. */
function Aviso({ tom, children }: { tom: "atencao" | "critico"; children: ReactNode }) {
  const base = tom === "critico" ? "crit" : "warn";
  return (
    <div
      className="rounded-md px-3 py-2.5 text-[11px] leading-relaxed"
      style={{
        background: `color-mix(in oklab, var(--bi-${base}) 9%, transparent)`,
        color: `var(--bi-${base}-ink)`,
      }}
    >
      {children}
    </div>
  );
}

/** Trecho de URL/endereço dentro de um texto. Cinza, nunca colorido. */
function Codigo({ children }: { children: ReactNode }) {
  return (
    <code
      className="rounded px-1 py-px text-[10px]"
      style={{ background: "var(--bi-surface-2)", color: "var(--bi-text)" }}
    >
      {children}
    </code>
  );
}

/** O passo numerado do "como funciona". O círculo é cinza sobre cinza: ele
 *  ordena a leitura, não classifica nada — não é lugar de cor. */
function Passo({ n, children }: { n: number; children: ReactNode }) {
  return (
    <div className="flex gap-2.5">
      <span
        className="mt-px grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold"
        style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
      >
        {n}
      </span>
      <div className="min-w-0 flex-1 text-[12px] leading-relaxed" style={{ color: "var(--bi-text)" }}>
        {children}
      </div>
    </div>
  );
}

function SessoesInner() {
  const { municipioId } = useMunicipio();
  const [status, setStatus] = useState<Record<string, SessionStatus>>({});
  const [tgStatus, setTgStatus] = useState<TgSessionStatus | null>(null);
  const [scraperRunning, setScraperRunning] = useState(false);

  const apiBase = api.defaults.baseURL || "";

  // Bookmarklet JS - substitui {{API}} {{KEY}} {{MUN}} em runtime
  const buildBookmarklet = (key: string) => {
    const code = `(function(){
      var token=prompt('Cole seu JWT do PACTHA (use o botão "Copiar token" na página de Sessões):');
      if(!token)return;
      fetch('${apiBase}/session-capture',{
        method:'POST',
        headers:{'Content-Type':'application/json','Authorization':'Bearer '+token},
        credentials:'omit',
        body:JSON.stringify({
          automation_key:'${key}',
          municipio_id:${municipioId || 0},
          cookie:document.cookie,
          url_atual:location.href,
          user_agent:navigator.userAgent
        })
      }).then(r=>r.json()).then(d=>{
        var msg = d.status==='ok'
          ? 'PACTHA: SESSÃO CAPTURADA!' + (d.auto_scrape_started ? '\\n\\n>>> Scraper TransfereGov iniciado automaticamente em background (janela 20min).\\n\\nVocê pode FECHAR esta aba — o scrape continua no servidor.' : '')
          : 'PACTHA erro: ' + JSON.stringify(d);
        alert(msg);
      }).catch(e=>alert('PACTHA erro: '+e.message));
    })();`;
    return "javascript:" + encodeURIComponent(code.replace(/\s+/g, " "));
  };

  const fetchAll = async () => {
    if (!municipioId) return;
    const results: Record<string, SessionStatus> = {};
    for (const p of PORTAIS) {
      try {
        const r = await api.get(`/session-capture/status/${p.key}`, {
          params: { municipio_id: municipioId },
        });
        results[p.key] = r.data;
      } catch {
        results[p.key] = { has_session: false };
      }
    }
    setStatus(results);
    // status especifico da sessao TransfereGov (mais detalhado: age + expired)
    try {
      const r = await api.get<TgSessionStatus>("/transferegov/admin/sessao-status");
      setTgStatus(r.data);
    } catch {
      setTgStatus(null);
    }
  };

  const rodarScraperTransferegov = async () => {
    if (!confirm(
      "Rodar o scraper TransfereGov agora?\n\n" +
      "Vai capturar propostas + parlamentar + situação de contratação dos\n" +
      "municípios cadastrados (usa a sessão gov.br atual do Cofre).\n\n" +
      "Pode levar 5-10 minutos."
    )) return;
    setScraperRunning(true);
    try {
      await api.post(`/transferegov/admin/run-scraper${municipioId ? `?municipio_id=${municipioId}` : ""}`);
      toast.success("Scraper iniciado em background. Acompanhe via /Logs.");
    } catch (e) {
      toast.error("Falha ao iniciar scraper");
      console.error(e);
    } finally {
      setScraperRunning(false);
    }
  };

  useEffect(() => { fetchAll(); }, [municipioId]);

  const copyToken = () => {
    const t = localStorage.getItem("pactha_token");
    if (!t) {
      toast.error("Faça login primeiro");
      return;
    }
    navigator.clipboard.writeText(t);
    toast.success("JWT copiado para o clipboard");
  };

  const formatDate = (s?: string) =>
    s ? new Date(s).toLocaleString("pt-BR") : "-";

  if (!municipioId) {
    return <Vazio>Selecione um município para gerenciar sessões.</Vazio>;
  }

  // Estado da sessao TransfereGov, resolvido UMA vez para o selo, a grade e as
  // caixas de alerta nao poderem divergir entre si.
  //
  // Nao uso `situacaoTom` aqui de proposito: ela classifica TEXTO de situacao
  // vindo das fontes (SIGCON, PNCP...), e este endpoint nao devolve texto —
  // devolve booleano e minutos. Passar "expirada" por ela cairia em `neutro`
  // (o vocabulario dela e "vencid", nao "expirad") e apagaria justamente o
  // unico alerta real da tela.
  const expMin = tgStatus?.user_id_exp_minutes ?? null;
  const tgExpirada = !!tgStatus?.expired;
  const tgExpirandoJa = !tgExpirada && expMin != null && expMin < 10;
  const tgTom: "neutro" | "atencao" | "critico" = !tgStatus?.has_session
    ? "neutro"
    : tgExpirada
      ? "critico"
      : tgExpirandoJa
        ? "atencao"
        : "neutro";
  const tgRotulo = !tgStatus?.has_session
    ? "Sem sessão"
    : tgExpirada
      ? `Expirou${expMin != null ? ` há ${Math.abs(expMin).toFixed(0)} min` : ""}`
      : expMin != null && expMin < 5
        ? `Expira em ${expMin.toFixed(1)} min — rode agora`
        : `Válida — expira em ${expMin?.toFixed(0) ?? "?"} min`;

  return (
    <div className="space-y-4">
      <div className="border-b pb-4" style={{ borderColor: "var(--bi-line)" }}>
        <TituloTela>Captura de Sessão</TituloTela>
        <p className="mt-1 text-sm" style={{ color: "var(--bi-muted)" }}>
          Solução gratuita para portais com anti-bot (gov.br, FNS, etc).
          Você loga manualmente e captura a sessão com 1 clique.
        </p>
      </div>

      {/* Como funciona */}
      <Bloco className="p-3">
        <BlocoHead icon={Info} titulo="Como funciona (3 passos)" sub="Configuração única por portal" />
        <div className="space-y-2.5">
          <Passo n={1}>
            <strong className="font-semibold">Copie seu token PACTHA.</strong>
            <button
              onClick={copyToken}
              className="ml-2 inline-flex items-center rounded-md px-2.5 py-1 text-[11px] font-medium"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
            >
              Copiar token
            </button>
          </Passo>
          <Passo n={2}>
            <strong className="font-semibold">
              Arraste o link &quot;Capturar sessão&quot; (abaixo) para a barra de favoritos do Chrome.
            </strong>
            <div style={{ color: "var(--bi-faint)" }}>
              Cada portal tem o seu. Faça isso uma única vez.
            </div>
          </Passo>
          <Passo n={3}>
            <strong className="font-semibold">
              Quando logar no portal (FNS, SIMEC...), clique no favorito &quot;PACTHA Capturar [portal]&quot;.
            </strong>
            <div style={{ color: "var(--bi-faint)" }}>
              Vai pedir para colar o token. Cole e pronto - sessão capturada.
              Repita 1x/mês ou quando expirar.
            </div>
          </Passo>
        </div>
      </Bloco>

      {/* Status especifico TransfereGov + rodar scraper */}
      {tgStatus && (
        <Bloco className="p-3">
          <BlocoHead
            icon={ShieldCheck}
            titulo="Sessão TransfereGov (gov.br SSO)"
            sub={tgStatus.has_session ? `Última captura: ${formatDate(tgStatus.updated_at)}` : undefined}
            right={<Selo tom={tgTom}>{tgRotulo}</Selo>}
          />

          {/* Vinculo, nivel e minutos restantes vinham escritos dentro da caixa
              verde de "sessao valida". Aqui viram colunas: continuam visiveis
              SEM precisar de uma caixa colorida para o estado normal. */}
          <Campos
            campos={[
              {
                rotulo: "Situação",
                valor: !tgStatus.has_session ? "Sem sessão" : tgExpirada ? "Expirada" : "Válida",
                tom: tgExpirada ? "critico" : "normal",
              },
              {
                rotulo: tgExpirada ? "Expirou há" : "Expira em",
                valor: expMin != null ? `${Math.abs(expMin).toFixed(0)} min` : "—",
                tom: tgExpirada ? "critico" : tgExpirandoJa ? "atencao" : "normal",
              },
              { rotulo: "Vínculo", valor: tgStatus.vinculo ?? "—" },
              { rotulo: "Nível", valor: tgStatus.nivel ?? "—" },
              {
                rotulo: "Última captura",
                valor: tgStatus.updated_at ? formatDate(tgStatus.updated_at) : "—",
                title: tgStatus.updated_at,
              },
            ]}
          />

          <div className="mt-2.5 space-y-2">
            {tgExpirada && (
              <Aviso tom="critico">
                <strong>Sessão expirou.</strong> A sessão do parcerias.transferegov dura
                apenas <strong>~20 minutos</strong> após inatividade. Para capturar parlamentar,
                situação de contratação detalhada e cláusula suspensiva, refaça os 4 passos:
                <ol className="ml-4 mt-1 list-decimal space-y-0.5">
                  <li>Abra <Codigo>parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home</Codigo></li>
                  <li>Clique <strong>Entrar com gov.br</strong> e complete o login</li>
                  <li>Clique no bookmarklet <strong>📎 PACTHA Capturar gov.br (parcerias.transferegov)</strong></li>
                  <li><strong>IMEDIATAMENTE</strong> volte aqui e clique <strong>Rodar scraper TransfereGov agora</strong> abaixo (você tem 20 min)</li>
                </ol>
                <div
                  className="mt-2 border-t pt-2"
                  style={{ borderColor: "color-mix(in oklab, var(--bi-crit) 30%, transparent)" }}
                >
                  <strong>Para CLÁUSULA SUSPENSIVA / SICONV legado:</strong>
                  <ol className="ml-4 mt-1 list-decimal space-y-0.5">
                    <li>Já logado no gov.br, abra <Codigo>discricionarias.transferegov.sistema.gov.br/voluntarias/</Codigo></li>
                    <li>Acesse qualquer convênio (precisa entrar na área autenticada)</li>
                    <li>Clique o bookmarklet <strong>📎 PACTHA Capturar SICONV Legado</strong> ENQUANTO ESTIVER nessa página</li>
                  </ol>
                </div>
              </Aviso>
            )}
            {tgExpirandoJa && (
              <Aviso tom="atencao">
                <strong>Atenção:</strong> a sessão expira em{" "}
                <strong>{expMin?.toFixed(1) ?? "?"} minutos</strong>. Rode o scraper AGORA antes que expire.
              </Aviso>
            )}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              onClick={rodarScraperTransferegov}
              disabled={scraperRunning}
              className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium disabled:opacity-50"
              style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
            >
              <Play className="size-3" />
              {scraperRunning ? "Iniciando..." : "Rodar scraper TransfereGov agora"}
            </button>
            <button
              onClick={fetchAll}
              className="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px]"
              style={{ border: "1px solid var(--bi-line)", color: "var(--bi-muted)" }}
            >
              <RefreshCw className="size-3" /> Atualizar status
            </button>
          </div>
        </Bloco>
      )}

      {/* PORTAIS — era uma pilha de cartoes com borda verde/azul e selo pintado
          por estado. Agora e a lista da identidade: selo cinza, e o estado de
          cada portal vira COLUNA (cookies / credencial / atualizado em), que e
          o que permite descer o olho pelos seis portais e ver de uma vez quais
          faltam capturar — sem que nada precise ser colorido para isso. */}
      <Lista>
        {PORTAIS.map((p) => {
          const st = status[p.key] || { has_session: false };
          const isSiconvLegado = p.key === "siconv_legado";
          return (
            <ItemLinha
              key={p.key}
              titulo={p.nome}
              meta={
                <>
                  <Selo>
                    {st.has_cookies
                      ? "Cookies capturados"
                      : st.has_session
                        ? "Apenas senha (sem cookies)"
                        : "Sem sessão"}
                  </Selo>
                  <span>
                    {st.has_cookies
                      ? "Pronto para scraping"
                      : st.has_session
                        ? "Faltam cookies — use o bookmarklet"
                        : "Faça login no portal e clique no bookmarklet"}
                  </span>
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noopener"
                    className="inline-flex items-center gap-1 hover:underline"
                  >
                    {p.url} <ExternalLink className="size-3" />
                  </a>
                </>
              }
            >
              <Campos
                campos={[
                  { rotulo: "Cookies", valor: st.has_cookies ? "Capturados" : "Faltando" },
                  { rotulo: "Credencial", valor: st.has_session ? "Cadastrada" : "Não cadastrada" },
                  {
                    rotulo: "Atualizado em",
                    valor: formatDate(st.atualizado_em),
                    title: st.has_cookies
                      ? "Data da captura dos cookies"
                      : "Data de cadastro da credencial",
                  },
                ]}
              />

              {isSiconvLegado && !st.has_cookies && (
                <div
                  className="mt-2 rounded-md px-2.5 py-2 text-[11px] leading-relaxed"
                  style={{ background: "var(--bi-surface-2)", color: "var(--bi-muted)" }}
                >
                  <strong>Necessário para Cláusula Suspensiva:</strong> faça login em{" "}
                  <Codigo>discricionarias.transferegov</Codigo> (via SSO gov.br) e clique este
                  bookmarklet enquanto estiver em uma página dessa URL.
                </div>
              )}

              {/* O bookmarklet fica ABAIXO, e nao no canto direito do cartao,
                  porque o texto do link vira o NOME do favorito quando o
                  usuario arrasta — encurta-lo quebraria os passos que mandam
                  clicar em "PACTHA Capturar [portal]". Como e um <a> dentro do
                  item, este ItemLinha nao pode receber `onClick` (o corpo
                  viraria <button> e teria ancora aninhada). */}
              <div className="mt-2">
                <a
                  href={buildBookmarklet(p.key)}
                  onClick={(e) => {
                    // Impede que o navegador execute o JS quando clicar (so quando arrastado)
                    if (!confirm(`Arraste este link para a barra de favoritos como "PACTHA Capturar ${p.nome}".\n\nClique OK só se quiser executar AGORA (precisa estar logado em ${p.url}).`)) {
                      e.preventDefault();
                    }
                  }}
                  className="inline-flex items-center rounded-md px-3 py-1.5 text-[12px] font-medium"
                  style={{ background: "var(--bi-cta)", color: "var(--bi-cta-ink)" }}
                  draggable
                >
                  📎 PACTHA Capturar {p.nome}
                </a>
              </div>
            </ItemLinha>
          );
        })}
      </Lista>

      {/* Seguranca: era um cartao inteiro laranja. E informacao permanente, nao
          alerta — quem sempre grita nunca e ouvido quando a sessao expira. */}
      <Bloco className="p-3">
        <BlocoHead icon={ShieldCheck} titulo="Sobre segurança" />
        <p className="text-[12px] leading-relaxed" style={{ color: "var(--bi-muted)" }}>
          O cookie capturado é cifrado com AES-256-GCM antes de salvar. Apenas
          os scrapers PACTHA conseguem decifrar. O token JWT que você cola é do
          seu próprio login no PACTHA - nunca compartilhe. Para invalidar uma sessão,
          faça logout no portal de origem.
        </p>
      </Bloco>

      <div className="flex justify-center">
        <button
          onClick={fetchAll}
          className="inline-flex items-center gap-1.5 text-[12px]"
          style={{ color: "var(--bi-muted)" }}
        >
          <RefreshCw className="size-3" /> Atualizar status
        </button>
      </div>
    </div>
  );
}

export default function SessoesPage() {
  return (
    <Suspense fallback={<div />}>
      <SessoesInner />
    </Suspense>
  );
}
