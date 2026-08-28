import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { observarResposta } from "@/lib/uso";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
  withCredentials: true, // envia cookies httpOnly em cross-origin
  // arrays viram chaves repetidas (situacoes=a&situacoes=b) p/ casar com FastAPI list[str]
  paramsSerializer: { indexes: null },
});

// Helper: le CSRF token do cookie pactha_csrf (nao httpOnly)
function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)pactha_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

/** Telas que rodam com credencial de QUIOSQUE (sem login de usuario):
 *  /tela  = janela do Modo Tela aberta pelo painel
 *  /t/*   = link publico da TV
 *  /m/*   = app de celular (PWA)
 *
 *  MANTER SINCRONIZADO com as rotas de quiosque. Esquecer uma nao da erro de
 *  compilacao: a tela simplesmente nao manda o Bearer, toma 401 e o interceptor
 *  abaixo a joga no /login — foi o que aconteceu com /m/ quando o app mobile
 *  nasceu. */
function ehSuperficieDeQuiosque(): boolean {
  if (typeof window === "undefined") return false;
  const p = window.location.pathname;
  return (
    p === "/tela" ||
    p.startsWith("/tela/") ||
    p.startsWith("/t/") ||
    p.startsWith("/m/")
  );
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // Fallback Bearer (compat com clientes que ainda guardam token em localStorage)
  if (typeof window !== "undefined") {
    // A CREDENCIAL DO QUIOSQUE TEM CHAVE PROPRIA e so vale nas telas de
    // quiosque. Antes ia em `pactha_token`, a MESMA chave do login: quem
    // abrisse o link publico da TV no proprio computador passava a mandar o
    // token do quiosque em TODAS as telas, e o cookie de sessao valido era
    // ignorado. Revogado o link, o token morria e o sistema inteiro respondia
    // 401 naquela maquina — e so naquela, o que faz parecer defeito de rede.
    const token = ehSuperficieDeQuiosque()
      ? localStorage.getItem("pactha_kiosk_token") || localStorage.getItem("pactha_token")
      : localStorage.getItem("pactha_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // CSRF: enviar em metodos mutating
    if (
      config.method &&
      ["post", "put", "patch", "delete"].includes(config.method.toLowerCase())
    ) {
      const csrf = getCsrfToken();
      if (csrf) {
        config.headers["X-CSRF-Token"] = csrf;
      }
    }
  }
  return config;
});

// Auto-refresh: tenta /auth/refresh em 401 antes de redirecionar
let isRefreshing = false;
let refreshQueue: Array<(ok: boolean) => void> = [];

async function tryRefresh(): Promise<boolean> {
  if (isRefreshing) {
    return new Promise((resolve) => refreshQueue.push(resolve));
  }
  isRefreshing = true;
  try {
    await axios.post(
      `${api.defaults.baseURL}/auth/refresh`,
      {},
      { withCredentials: true }
    );
    refreshQueue.forEach((cb) => cb(true));
    refreshQueue = [];
    return true;
  } catch {
    refreshQueue.forEach((cb) => cb(false));
    refreshQueue = [];
    return false;
  } finally {
    isRefreshing = false;
  }
}

api.interceptors.response.use(
  (r) => {
    // TELEMETRIA: toda resposta que deu certo passa pelo coletor — GET com
    // parametros e o filtro que a pessoa aplicou; POST/PUT/DELETE e o que ela
    // gravou. Fora do caminho do erro, e sem tocar na resposta.
    observarResposta(r.config?.method, r.config?.url, r.config?.params, r.status);
    return r;
  },
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;
    const status = error.response?.status;

    if (status === 401 && original && !original._retry && typeof window !== "undefined") {
      original._retry = true;
      const ok = await tryRefresh();
      if (ok) {
        // AUTO-CURA de token velho em localStorage.
        // Se o refresh deu certo, a SESSAO (cookie) esta boa — entao um 401
        // vinha do Bearer. Repetir com o mesmo Bearer daria 401 de novo, e como
        // `_retry` ja esta marcado, ninguem limparia nada: a maquina ficava
        // presa em 401 para sempre, so ela. Descartamos o token e repetimos so
        // com o cookie. Sem isto, uma maquina ja contaminada nao se recupera
        // nem depois de corrigido o que gravou o token errado.
        try {
          localStorage.removeItem("pactha_token");
        } catch { /* storage bloqueado */ }
        if (original.headers) delete original.headers.Authorization;
        return api(original);
      }
      // refresh falhou - limpa estado e redireciona
      localStorage.removeItem("pactha_token");
      localStorage.removeItem("pactha_user");
      localStorage.removeItem("pactha_last_municipio_id");
      localStorage.removeItem("pactha_bi_scope"); // nao vazar escopo/periodo do BI entre usuarios
      localStorage.removeItem("pactha_bi_ano");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;
