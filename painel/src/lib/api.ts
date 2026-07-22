import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

// Mesmo padrao do frontend operacional: same-origin via rewrites (/api -> API do
// cliente). Aceita cookie httpOnly (prefeito logado) OU Bearer em localStorage
// (kiosk token da TV). Mantem os MESMOS nomes de cookie/token do PACTHA pra a
// sessao ser compartilhada com a API.
const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
  withCredentials: true,
  paramsSerializer: { indexes: null }, // arrays viram chaves repetidas (FastAPI list[str])
});

function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)pactha_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("pactha_token");
    if (token) config.headers.Authorization = `Bearer ${token}`;
    if (
      config.method &&
      ["post", "put", "patch", "delete"].includes(config.method.toLowerCase())
    ) {
      const csrf = getCsrfToken();
      if (csrf) config.headers["X-CSRF-Token"] = csrf;
    }
  }
  return config;
});

// Auto-refresh silencioso em 401 (so p/ sessao de cookie; kiosk Bearer nao expira cedo).
let isRefreshing = false;
let refreshQueue: Array<(ok: boolean) => void> = [];

async function tryRefresh(): Promise<boolean> {
  if (isRefreshing) return new Promise((resolve) => refreshQueue.push(resolve));
  isRefreshing = true;
  try {
    await axios.post(`${api.defaults.baseURL}/auth/refresh`, {}, { withCredentials: true });
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
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retry?: boolean }) | undefined;
    const status = error.response?.status;
    if (status === 401 && original && !original._retry && typeof window !== "undefined") {
      original._retry = true;
      // Kiosk (Bearer) nao tenta refresh: so redireciona o login do prefeito.
      const hasBearer = !!localStorage.getItem("pactha_token");
      if (!hasBearer) {
        const ok = await tryRefresh();
        if (ok) return api(original);
      }
      // Sem sessao: NAO forca /login aqui — a pagina decide (cai pro preview de
      // exemplo ou mostra login). Evita loop antes do fluxo de auth existir.
    }
    return Promise.reject(error);
  }
);

export default api;
