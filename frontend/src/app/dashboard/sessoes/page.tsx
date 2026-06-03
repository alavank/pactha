"use client";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, XCircle, Bookmark, ExternalLink, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import toast from "react-hot-toast";

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
  { key: "govbr", nome: "gov.br", url: "https://acesso.gov.br" },
  { key: "fns", nome: "FNS - Saude", url: "https://consultafns.saude.gov.br" },
  { key: "simec", nome: "SIMEC/PAR - Educacao", url: "https://simec.mec.gov.br" },
  { key: "sismob", nome: "SISMOB - Obras Saude", url: "https://sismobcidadao.saude.gov.br" },
  { key: "suas", nome: "Estrutura SUAS", url: "https://estruturasuas.mds.gov.br" },
];

function SessoesInner() {
  const search = useSearchParams();
  const municipioId = search.get("municipio_id");
  const [status, setStatus] = useState<Record<string, SessionStatus>>({});
  const [tgStatus, setTgStatus] = useState<TgSessionStatus | null>(null);
  const [scraperRunning, setScraperRunning] = useState(false);

  const apiBase = api.defaults.baseURL || "";

  // Bookmarklet JS - substitui {{API}} {{KEY}} {{MUN}} em runtime
  const buildBookmarklet = (key: string) => {
    const code = `(function(){
      var token=prompt('Cole seu JWT do PACTA (use o botão "Copiar token" na página de Sessões):');
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
          ? 'PACTA: SESSAO CAPTURADA!' + (d.auto_scrape_started ? '\\n\\n>>> Scraper TransfereGov iniciado automaticamente em background (janela 20min).\\n\\nVoce pode FECHAR esta aba — o scrape continua no servidor.' : '')
          : 'PACTA erro: ' + JSON.stringify(d);
        alert(msg);
      }).catch(e=>alert('PACTA erro: '+e.message));
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
    const t = localStorage.getItem("pacta_token");
    if (!t) {
      toast.error("Faca login primeiro");
      return;
    }
    navigator.clipboard.writeText(t);
    toast.success("JWT copiado para o clipboard");
  };

  const formatDate = (s?: string) =>
    s ? new Date(s).toLocaleString("pt-BR") : "-";

  if (!municipioId) {
    return (
      <div className="flex h-64 items-center justify-center text-muted-foreground">
        Selecione um municipio para gerenciar sessoes.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="border-b border-slate-200 pb-4">
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Bookmark className="size-6 text-purple-700" />
          Captura de Sessao
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Solucao gratuita para portais com anti-bot (gov.br, FNS, etc).
          Voce loga manualmente e captura a sessao com 1 clique.
        </p>
      </div>

      {/* Como funciona */}
      <Card className="border-l-4 border-l-blue-500 bg-blue-50/40">
        <CardHeader>
          <CardTitle className="text-base">Como funciona (3 passos)</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex gap-3">
            <span className="bg-blue-600 text-white rounded-full size-6 flex items-center justify-center font-bold text-xs flex-shrink-0">1</span>
            <div>
              <strong>Copie seu token PACTA:</strong>
              <button
                onClick={copyToken}
                className="ml-2 inline-block bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-xs"
              >
                Copiar token
              </button>
            </div>
          </div>
          <div className="flex gap-3">
            <span className="bg-blue-600 text-white rounded-full size-6 flex items-center justify-center font-bold text-xs flex-shrink-0">2</span>
            <div>
              <strong>Arraste o link &quot;Capturar sessao&quot; (abaixo) para a barra de favoritos do Chrome.</strong>
              <br />
              <span className="text-xs text-slate-600">
                Cada portal tem o seu. Faca isso uma unica vez.
              </span>
            </div>
          </div>
          <div className="flex gap-3">
            <span className="bg-blue-600 text-white rounded-full size-6 flex items-center justify-center font-bold text-xs flex-shrink-0">3</span>
            <div>
              <strong>Quando logar no portal (FNS, SIMEC...), clique no favorito &quot;PACTA Capturar [portal]&quot;.</strong>
              <br />
              <span className="text-xs text-slate-600">
                Vai pedir para colar o token. Cole e pronto - sessao capturada.
                Repita 1x/mes ou quando expirar.
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Card destacado: status especifico TransfereGov + rodar scraper */}
      {tgStatus && (
        <Card className={`border-l-4 ${tgStatus.expired ? "border-l-amber-500 bg-amber-50/40" : "border-l-green-500 bg-green-50/40"}`}>
          <CardHeader>
            <CardTitle className="text-base flex items-center justify-between">
              <span>Sessão TransfereGov (gov.br SSO)</span>
              {tgStatus.has_session ? (
                tgStatus.expired ? (
                  <Badge className="bg-red-100 text-red-800 hover:bg-red-100">
                    EXPIROU{tgStatus.user_id_exp_minutes != null ? ` (${Math.abs(tgStatus.user_id_exp_minutes).toFixed(0)} min atrás)` : ""}
                  </Badge>
                ) : tgStatus.user_id_exp_minutes != null && tgStatus.user_id_exp_minutes < 5 ? (
                  <Badge className="bg-amber-100 text-amber-800 hover:bg-amber-100">
                    Expira em {tgStatus.user_id_exp_minutes.toFixed(1)} min — RODE AGORA
                  </Badge>
                ) : (
                  <Badge className="bg-green-100 text-green-800 hover:bg-green-100">
                    Válida — expira em {tgStatus.user_id_exp_minutes?.toFixed(0) ?? "?"} min
                  </Badge>
                )
              ) : (
                <Badge variant="outline" className="text-slate-500">Sem sessão</Badge>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            {tgStatus.has_session && (
              <div className="text-xs text-slate-600">
                Última captura: {new Date(tgStatus.updated_at || "").toLocaleString("pt-BR")}
              </div>
            )}
            {tgStatus.expired && (
              <div className="rounded bg-red-100 border border-red-300 p-3 text-red-900 text-xs space-y-1">
                <strong>⚠️ Sessão expirou.</strong> A sessão do parcerias.transferegov dura
                apenas <strong>~20 minutos</strong> após inatividade. Para capturar parlamentar,
                situação de contratação detalhada e cláusula suspensiva, refaça os 4 passos:
                <ol className="list-decimal ml-5 space-y-0.5 mt-1">
                  <li>Abra <code className="bg-white px-1 rounded">parcerias.transferegov.sistema.gov.br/ep-atos-prep-web/home</code></li>
                  <li>Clique <strong>Entrar com gov.br</strong> e complete o login</li>
                  <li>Clique no bookmarklet <strong>📎 PACTA Capturar gov.br</strong></li>
                  <li><strong>IMEDIATAMENTE</strong> volte aqui e clique <strong>▶ Rodar scraper</strong> abaixo (você tem 20 min)</li>
                </ol>
              </div>
            )}
            {!tgStatus.expired && tgStatus.user_id_exp_minutes != null && tgStatus.user_id_exp_minutes < 10 && (
              <div className="rounded bg-amber-100 border border-amber-300 p-3 text-amber-900 text-xs">
                <strong>⏰ Atenção:</strong> a sessão expira em <strong>{tgStatus.user_id_exp_minutes.toFixed(1)} minutos</strong>.
                Rode o scraper AGORA antes que expire.
              </div>
            )}
            {!tgStatus.expired && tgStatus.vinculo && (
              <div className="rounded bg-green-100 border border-green-300 p-3 text-green-900 text-xs">
                Sessão válida (vínculo {tgStatus.vinculo}, nível {tgStatus.nivel}). Expira em{" "}
                {tgStatus.user_id_exp_minutes?.toFixed(0) ?? "?"} minutos.
              </div>
            )}
            <div className="flex gap-2 pt-2">
              <button
                onClick={rodarScraperTransferegov}
                disabled={scraperRunning}
                className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded text-sm font-medium disabled:opacity-50"
              >
                {scraperRunning ? "Iniciando..." : "▶ Rodar scraper TransfereGov agora"}
              </button>
              <button
                onClick={fetchAll}
                className="border border-slate-300 hover:bg-slate-50 px-4 py-2 rounded text-sm"
              >
                <RefreshCw className="inline size-3 mr-1" /> Atualizar status
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Lista de portais */}
      <div className="grid gap-3">
        {PORTAIS.map((p) => {
          const st = status[p.key] || { has_session: false };
          return (
            <Card key={p.key} className={st.has_session ? "border-green-200" : ""}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between flex-wrap gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="font-semibold text-slate-900">{p.nome}</h3>
                      {st.has_cookies ? (
                        <Badge className="bg-green-100 text-green-800 hover:bg-green-100">
                          <CheckCircle2 className="size-3 mr-1" />
                          Cookies capturados
                        </Badge>
                      ) : st.has_session ? (
                        <Badge className="bg-amber-100 text-amber-800 hover:bg-amber-100">
                          Apenas senha (sem cookies)
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="text-slate-500">
                          <XCircle className="size-3 mr-1" />
                          Sem sessao
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-slate-500">
                      {st.has_cookies ? (
                        <>Cookies capturados em: {formatDate(st.atualizado_em)}</>
                      ) : st.has_session ? (
                        <>Credencial cadastrada em: {formatDate(st.atualizado_em)} (faltam cookies — use o bookmarklet)</>
                      ) : (
                        <>Faca login no portal e clique no bookmarklet</>
                      )}
                    </div>
                    <div className="text-xs text-slate-400 mt-1">
                      <a href={p.url} target="_blank" rel="noopener" className="hover:underline">
                        {p.url} <ExternalLink className="inline size-3" />
                      </a>
                    </div>
                  </div>
                  <a
                    href={buildBookmarklet(p.key)}
                    onClick={(e) => {
                      // Impede que o navegador execute o JS quando clicar (so quando arrastado)
                      if (!confirm(`Arraste este link para a barra de favoritos como "PACTA Capturar ${p.nome}".\n\nClique OK so se quiser executar AGORA (precisa estar logado em ${p.url}).`)) {
                        e.preventDefault();
                      }
                    }}
                    className="bg-purple-700 hover:bg-purple-800 text-white px-4 py-2 rounded text-sm font-medium"
                    draggable
                  >
                    📎 PACTA Capturar {p.nome}
                  </a>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <Card className="bg-amber-50 border-amber-200">
        <CardContent className="p-4 text-sm">
          <strong className="text-amber-900">Sobre seguranca:</strong>
          <p className="text-amber-800 mt-1">
            O cookie capturado e cifrado com AES-256-GCM antes de salvar. Apenas
            os scrapers PACTA conseguem decifrar. O token JWT que voce cola e do
            seu proprio login no PACTA - nunca compartilhe. Para invalidar uma sessao,
            faca logout no portal de origem.
          </p>
        </CardContent>
      </Card>

      <div className="flex justify-center">
        <button
          onClick={fetchAll}
          className="text-sm text-slate-600 hover:text-slate-900 flex items-center gap-1"
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
