---
name: frontend-auth
description: PACTHA frontend session handling — httpOnly cookies, the same-origin /api proxy that makes them work, silent 401 refresh via axios interceptors, and separate kiosk tokens. Use when touching src/lib/api.ts, next.config.ts rewrites, login/logout flows, API base URLs, or the public /tela, /t/*, /m/* surfaces.
---

# Frontend auth — `src/lib/api.ts`

httpOnly cookies (`pactha_access` / `pactha_refresh` / `pactha_csrf`) are the primary session,
with a `pactha_token` in `localStorage` as a Bearer fallback and silent 401 → refresh → retry
via axios interceptors.

## The same-origin constraint — do not break this

This only works because the frontend proxies `/api/*` to the backend **same-origin**
(`rewrites()` in `next.config.ts`, target = `API_PROXY_TARGET`, baked in at **build time**).

⚠️ Pointing the frontend at an absolute cross-site API URL breaks `SameSite=Lax` cookies and
silent refresh. If you're tempted to set an absolute API base URL for any reason, don't —
change the proxy target instead.

Because `API_PROXY_TARGET` is build-time, changing it requires a rebuild, not just an env var
update on the running container.

## Arquivos abrem no `VisualizadorDocumento`, não em aba nova

Regra do dono (16/09/2026): anexo, PDF de diário, foto de obra — todo ARQUIVO — abre em
`src/components/ui/VisualizadorDocumento.tsx` (modal com Baixar / Imprimir / Fonte oficial).
Nada de `window.open(blob)` nem `<a target=_blank>` para arquivo; link para PÁGINA de portal
continua em nova aba. O componente busca pelo `api` como blob e embute o `blob:` no iframe,
porque o backend manda `X-Frame-Options: DENY` em toda resposta — apontar o iframe para a
rota `/api/...` mostra a página de bloqueio. Não afrouxe o header. O porquê completo está no
cabeçalho do componente.

## Kiosk / public surfaces

Kiosk and public-link surfaces (`/tela`, `/t/*`, `/m/*`) use a separate `pactha_kiosk_token`
key, so opening a public TV link on a normal user's machine can't clobber their session token.

Keep that separation when adding any new public/unauthenticated surface — never reuse
`pactha_token` for it.
