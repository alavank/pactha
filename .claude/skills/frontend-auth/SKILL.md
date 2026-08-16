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

## Kiosk / public surfaces

Kiosk and public-link surfaces (`/tela`, `/t/*`, `/m/*`) use a separate `pactha_kiosk_token`
key, so opening a public TV link on a normal user's machine can't clobber their session token.

Keep that separation when adding any new public/unauthenticated surface — never reuse
`pactha_token` for it.
