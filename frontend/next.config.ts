import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Build standalone p/ imagem Docker enxuta no Coolify (gera .next/standalone)
  output: "standalone",
  // Proxy same-origin: o front serve /api e repassa pro backend (host interno da
  // API no Coolify). Assim cookies httpOnly + CSRF + refresh silencioso ficam no
  // MESMO host -> acaba o re-login de ~60min. API_PROXY_TARGET e build-time
  // (as rewrites sao materializadas no build do Next).
  async rewrites() {
    const target = process.env.API_PROXY_TARGET || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
    ];
  },
  experimental: {
    // O proxy de rewrite do Next corta em 30s por DEFAULT e responde
    // `500 Internal Server Error` em TEXTO PURO (sem JSON, sem `detail`) --
    // era isso que aparecia na tela como "HTTP 500" seco quando a IA passava
    // de 30s. A API respondia 200; quem desistia era o proxy. Perguntas da IA
    // que varrem varias fontes levam 25-50s legitimamente, entao o teto aqui
    // tem que acompanhar o timeout do axios (180s em src/lib/api.ts).
    proxyTimeout: 240_000,
  },
};

export default nextConfig;
