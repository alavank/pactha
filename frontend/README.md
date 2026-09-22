# PACTHA — Frontend

App web do PACTHA: **Next.js 16 (App Router)** + Tailwind v4 + daisyUI + shadcn.

> ⚠️ Este app **não é deployado na Vercel**. Ele é buildado como imagem Docker
> (`frontend/Dockerfile`, `output: "standalone"`) e roda no **Coolify, na AWS Lightsail
> `54.232.208.118`** — um deploy por tenant (seis hoje; a lista vive em `INFRA.md`).
> Ver [`../INFRA.md`](../INFRA.md).

## Desenvolvimento local

```bash
npm install --legacy-peer-deps
npm run dev
```

Abra [http://localhost:3000](http://localhost:3000).

Suba o backend em paralelo (`cd ../backend && python -m uvicorn main:app --reload --port 8000`):
o Next faz **proxy same-origin** de `/api` para `API_PROXY_TARGET` (default
`http://localhost:8000`), via `rewrites()` em `next.config.ts`.

## Variáveis de ambiente (BUILD-TIME)

`API_PROXY_TARGET` e todas as `NEXT_PUBLIC_*` são **inlined no build**. Mudar o valor no
Coolify sem rebuildar o app **não tem efeito nenhum** — marque `is_build_time: true` e
faça redeploy.

| Var | Para que serve |
|-----|----------------|
| `API_PROXY_TARGET` | host interno da API do tenant (destino do rewrite `/api/:path*`) |
| `NEXT_PUBLIC_API_URL` | base da API usada pelo cliente (deve terminar em `/api`) |
| `NEXT_PUBLIC_CLIENT_LOGO` | logo do cliente daquele tenant |
| `NEXT_PUBLIC_CLIENT_SUBTITLE` | subtítulo/identificação do cliente |
| `NEXT_PUBLIC_CLIENT_NAME` | nome do cliente na prévia do link (título e imagem de WhatsApp/Telegram) — `src/lib/previa-link.ts` |
| `NEXT_PUBLIC_SITE_URL` | endereço canônico do tenant (`https://juranda.pr.pactha.com.br`); sem ele o `og:image` sai relativo e a prévia perde a imagem |

## Notas para agentes de IA

Leia também `AGENTS.md` nesta pasta: **esta versão do Next.js tem breaking changes** em
relação ao que a maioria dos modelos conhece — confira `node_modules/next/dist/docs/`
antes de escrever código.

## Referências

- [Next.js Documentation](https://nextjs.org/docs)
- [Learn Next.js](https://nextjs.org/learn)
