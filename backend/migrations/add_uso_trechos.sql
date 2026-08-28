-- TELEMETRIA: a sessao de USO deixa de ser a vida do token.
--
-- O `sid` de `uso_sessao` era o hash do `sid` do TOKEN — que atravessa o refresh
-- e dura 30 dias. Quem fechava o navegador as 18h e voltava as 9h do dia
-- seguinte caia na MESMA linha: "No sistema agora" dizia que a pessoa estava
-- logada ha 15 horas, e a sessao somava 3h de "total" com 4 minutos de uso.
-- Pedido do dono (28/08/2026): "tem que ser real — se eu entrei, marca la".
--
-- Agora cada linha e um TRECHO CONTIGUO de uso (routers/uso.py): silencio maior
-- que _GAP_NOVO_TRECHO_S ou logout abre linha nova. `sessao_token` guarda o sid
-- do token, para agrupar os trechos de uma mesma entrada quando for util.
--
-- Idempotente: roda a cada boot, contra 4 bancos vivos.

ALTER TABLE uso_sessao ADD COLUMN IF NOT EXISTS sessao_token CHAR(32);

-- Linhas antigas: o sid ERA o token. Backfill so onde esta vazio.
UPDATE uso_sessao SET sessao_token = sid WHERE sessao_token IS NULL;

CREATE INDEX IF NOT EXISTS ix_uso_sessao_token ON uso_sessao (sessao_token, inicio DESC);

-- 'navegador_fechado' (17 chars) nao cabia em VARCHAR(16). Alargar e
-- idempotente: repetir o ALTER para o mesmo tipo e no-op.
ALTER TABLE uso_sessao ALTER COLUMN motivo_fim TYPE VARCHAR(24);
