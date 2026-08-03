-- Marca de QUIOSQUE no usuario, e nao no token.
--
-- A superficie publica de TV (`/t/<slug>`, `/m/<slug>`) recebe um token de
-- 365 dias por um endpoint PUBLICO — o slug e o unico segredo, e o link e feito
-- para circular. Esse token e um usuario `viewer` de verdade, entao passa por
-- `get_current_user` como qualquer um.
--
-- POR QUE NO USUARIO, E NAO NO CLAIM DO TOKEN: `routers/auth.py::refresh` monta
-- o access token novo com `{"sub", "role"}` e NAO repassa `kiosk`. Como o
-- interceptor do front (`lib/api.ts`) dispara refresh automatico em qualquer
-- 401, uma guarda que lesse o claim se dissolveria sozinha na primeira falha —
-- e numa maquina com cookie de sessao do gestor trocaria a credencial de
-- quiosque por uma sessao plena, sem ninguem pedir. A marca tem de sobreviver
-- ao refresh, entao mora no usuario.
ALTER TABLE users ADD COLUMN IF NOT EXISTS kiosk BOOLEAN NOT NULL DEFAULT FALSE;

-- Backfill pelos DOIS emissores que ja criaram conta de quiosque:
--   kiosk-<municipio_id>@painel.local          -> routers/painel.py (legado)
--   kiosk-u<owner_id>-<slug>@painel.local      -> routers/bi.py (atual)
-- `NOT kiosk` no WHERE porque este arquivo roda a CADA boot (o runner nao tem
-- registro de "ja aplicada"): sem a guarda, todo start reescreveria as linhas.
UPDATE users SET kiosk = TRUE
 WHERE email LIKE 'kiosk-%@painel.local' AND NOT kiosk;

-- Cinto e suspensorio: quem for dono de link de TV como usuario de quiosque
-- tambem entra, mesmo que o e-mail nao siga o padrao.
UPDATE users u SET kiosk = TRUE
  FROM bi_tela_links l
 WHERE l.kiosk_user_id = u.id AND NOT u.kiosk;

CREATE INDEX IF NOT EXISTS ix_users_kiosk ON users (kiosk) WHERE kiosk;
