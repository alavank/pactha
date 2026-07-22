import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Build standalone p/ imagem Docker enxuta no Coolify (gera .next/standalone).
  output: "standalone",
  // Proxy same-origin: o Painel serve /api e repassa pro backend (host interno da
  // API do cliente no Coolify). Cookies httpOnly + CSRF + refresh ficam no MESMO
  // host. API_PROXY_TARGET e build-time (rewrites materializadas no build).
  async rewrites() {
    const target = process.env.API_PROXY_TARGET || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${target}/api/:path*` },
    ];
  },
};

export default nextConfig;
