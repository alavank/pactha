-- RM por selecao de CONSULTAS (fontes) — PARTE 2 de 2: a IDENTIDADE NOVA.
--
-- ⚠️⚠️ ESTE ARQUIVO E O DEPLOY 1 DE DOIS. Ele CRIA o indice novo e NAO derruba o
-- antigo. Durante a troca de container, o codigo VELHO
-- (`ON CONFLICT (municipio_id, anos)`) e o NOVO
-- (`ON CONFLICT (municipio_id, anos, fontes)`) rodam ao MESMO TEMPO contra este
-- banco, e cada um precisa do SEU indice. Sem essa coexistencia, o container
-- velho passa a responder 42P10 ("there is no unique or exclusion constraint
-- matching the ON CONFLICT specification") em TODO POST /api/rm ate terminar de
-- sair do ar. O DROP do antigo e `drop_rm_unique_anos.sql`, que so entra em
-- MIGRATION_FILES num PR POSTERIOR, depois deste estar em producao nos QUATRO
-- tenants (Freitas, Trust, Monte Siao/MG, Santa Maria/RS).
--
-- Enquanto o indice antigo viver, o completo e o filtrado do MESMO periodo ainda
-- nao conseguem coexistir (23505 no indice velho). E temporario, e o router
-- explica isso em 409 — ver o `except DBAPIError` de rm.py::criar.
--
-- E UNIQUE INDEX (e nao constraint) pelo mesmo motivo de ux_rm_mun_anos:
-- `ON CONFLICT (colunas)` infere por lista de colunas e funciona;
-- `ON CONFLICT ON CONSTRAINT` nao.
--
-- ⚠️ Este CREATE NAO PODE falhar por dado duplicado, e e por isso que ele vem
-- ANTES do DROP e nao depois: enquanto `ux_rm_mun_anos` existe, (municipio_id,
-- anos) ja e unico, entao um indice sobre (municipio_id, anos, fontes) e
-- forcosamente unico tambem. Na ordem invertida, um CREATE que falhasse por
-- duplicata seria classificado como "ja aplicada (skip)" pelo runner
-- (services/startup.py filtra a mensagem por substring "duplicate") e o indice
-- simplesmente NAO EXISTIRIA — com o ON CONFLICT novo estourando 42P10 em
-- producao e o log dizendo que estava tudo certo.
-- ⚠️ GUARDA ACRESCENTADA EM 26/08/2026, quando `estagio` entrou na identidade.
-- Este arquivo roda a CADA BOOT. Depois que `drop_rm_unique_anos_fontes.sql`
-- derrubar este indice (o deploy 2 da vez seguinte), o boot seguinte o RECRIARIA
-- e a troca se desfaria sozinha — em silencio, com o log dizendo "Migration OK".
-- E exatamente a guarda que `add_rm_anos.sql` ja carrega pelo mesmo motivo.
DO $$
BEGIN
    IF to_regclass('public.ux_rm_mun_anos_fontes_estagio') IS NULL THEN
        CREATE UNIQUE INDEX IF NOT EXISTS ux_rm_mun_anos_fontes
            ON rm_relatorios (municipio_id, anos, fontes);
    END IF;
END $$;
