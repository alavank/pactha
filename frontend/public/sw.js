// Service worker MÍNIMO — existe por dois motivos, nesta ordem:
//
// 1. Sem um SW com handler de `fetch`, o Chrome no Android não oferece
//    "Instalar aplicativo". É requisito, não enfeite.
// 2. Dar uma tela de "sem conexão" decente. O prefeito usa isso na rua, em
//    4G ruim; um erro cru do navegador no meio de uma reunião é péssimo.
//
// O QUE ELE NÃO FAZ, DE PROPÓSITO: não cacheia resposta de API. Indicador
// financeiro velho servido como atual é pior do que não abrir — o gestor tomaria
// decisão com número de ontem sem saber. Dado é sempre da rede.

const CACHE = "pactha-mobile-v1";
const CASCA = ["/pwa-192.png", "/pwa-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(CASCA)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches
      .keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // API: SEMPRE da rede, nunca do cache (ver comentário no topo).
  if (url.pathname.startsWith("/api/")) return;

  // Navegação: rede primeiro; offline, avisa em português.
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req).catch(
        () =>
          new Response(
            `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
             <meta name="viewport" content="width=device-width,initial-scale=1">
             <title>Sem conexão</title>
             <style>
               body{margin:0;min-height:100vh;display:grid;place-items:center;
                    background:#0a0c0b;color:#f1f4f2;
                    font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
                    padding:24px;text-align:center}
               b{display:block;font-size:19px;margin-bottom:8px}
               span{color:rgba(241,244,242,.6);font-size:14px}
             </style></head><body><div>
               <b>Sem conexão</b>
               <span>Os indicadores vêm do servidor em tempo real.<br>
               Reconecte e abra novamente.</span>
             </div></body></html>`,
            { headers: { "Content-Type": "text/html; charset=utf-8" }, status: 503 }
          )
      )
    );
    return;
  }

  // Estáticos (ícones, chunks): cache primeiro, com atualização em segundo plano.
  e.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          if (res.ok && (url.pathname.startsWith("/_next/") || CASCA.includes(url.pathname))) {
            const copia = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copia));
          }
          return res;
        })
    )
  );
});
