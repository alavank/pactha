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
};

export default nextConfig;
