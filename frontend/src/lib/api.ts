import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
  withCredentials: true, // envia cookies httpOnly em cross-origin
});

// Helper: le CSRF token do cookie pacta_csrf (nao httpOnly)
function getCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const m = document.cookie.match(/(?:^|;\s*)pacta_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  // Fallback Bearer (compat com clientes que ainda guardam token em localStorage)
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("pacta_token");
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
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;
    const status = error.response?.status;

    if (status === 401 && original && !original._retry && typeof window !== "undefined") {
      original._retry = true;
      const ok = await tryRefresh();
      if (ok) {
        return api(original);
      }
      // refresh falhou - limpa estado e redireciona
      localStorage.removeItem("pacta_token");
      localStorage.removeItem("pacta_user");
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;
