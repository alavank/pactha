-- valor_total do SIGCON-MG defasado: a tela somava 7.000.000 + 728.020,41 e
-- exibia 7.000.000.
--
-- CAUSA: o backfill do CKAN grava o convenio com o total que o arquivo traz
-- (so a parte do concedente) e, mais tarde, o scraper do detalhe preenche a
-- CONTRAPARTIDA sem recomputar o total. As duas escritas estao certas
-- isoladamente; a soma e que nunca foi refeita.
--
-- ALCANCE MEDIDO (12/08/2026): freitas 233 linhas / +R$ 13.828.272,69 ·
-- montesiao 25 / +R$ 1.239.613,02 · trust 0 (nao tem SIGCON).
--
-- IDEMPOTENTE POR CONSTRUCAO: depois de rodar, `valor_total <> valor_concedente`
-- nessas linhas e o WHERE deixa de casar. Isso e OBRIGATORIO aqui — o runner do
-- PACTHA executa TODAS as migrations a cada boot, nao ha registro de aplicada.
--
-- ⚠️ SO fonte='SIGCON-MG'. No GCONV-ES o `valor_total` ja INCLUI os aditivos, e
-- recalcular como concedente+contrapartida apagaria R$ 11.651.752,18 de uma
-- linha do trust (Anchieta).
--
-- ⚠️ SEM `updated_at = NOW()`, DE PROPOSITO: routers/freshness.py usa
-- max(updated_at) DESTAS MESMAS LINHAS como idade da coleta do SIGCON, e chama
-- de "fresco" o que tem ate 2 dias. Carimbar aqui pintaria a fonte de verde no
-- boot do deploy, escondendo coleta parada — trocaria um erro de soma por um
-- erro de monitoramento, que e pior porque ninguem procura.
UPDATE convenios_estadual
   SET valor_total = valor_concedente + valor_contrapartida
 WHERE fonte = 'SIGCON-MG'
   AND valor_contrapartida > 0
   AND valor_total = valor_concedente;
