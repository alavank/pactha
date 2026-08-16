-- BOOTSTRAP LIMPO: as 12 colunas de `convenios_estadual` que nunca tiveram
-- migration porque nasceram no Neon.
--
-- ⚠️ POR QUE ISTO EXISTE, e por que ninguem tinha visto antes. Os tres bancos
-- de producao (freitas, trust, montesiao-mg) vieram MIGRADOS do Neon, ja com o
-- schema completo. Nenhum deles jamais foi criado do zero. Estas 12 colunas
-- (`fonte` e os campos do Relatorio de Monitoramento) existem la desde sempre,
-- mas NAO estao no `setup_db.create_tables()` e NAO estavam em migration
-- nenhuma — ou seja, so existiam por heranca.
--
-- E `Base.metadata.create_all(checkfirst=True)` NAO conserta isso: ele cria
-- TABELA que falta, nunca COLUNA que falta em tabela existente. Como o
-- `setup_db` cria `convenios_estadual` primeiro (sem estas colunas), o
-- create_all a ve existente e passa direto.
--
-- Medido no 1o boot do 4o tenant (santamaria-rs, 16/08/2026), o primeiro banco
-- criado do zero na historia do projeto: `62/64 migrations executadas`, com
-- `fix_duplicatas_chave_natural.sql` e `fix_sigcon_total_com_contrapartida.sql`
-- falhando com `column "fonte" does not exist`. E o estrago passava MUITO alem
-- das duas migrations: `routers/convenios.py` filtra por `fonte`, o RM le
-- `nr_sei`/`banco`/`agencia`/`saldo_bancario`, e o monitor de frescor separa
-- SIGCON de FNS por `fonte` — num tenant novo, tudo isso quebraria em runtime.
--
-- REGISTRADA ACIMA de `fix_duplicatas_chave_natural.sql` na MIGRATION_FILES, que
-- e a primeira que precisa da coluna. Nos tres bancos vivos e no-op completo
-- (todos os ADD tem IF NOT EXISTS).

-- `fonte` distingue SIGCON-MG / GConv-ES / FNS / (agora) as fontes gauchas na
-- mesma tabela. ⚠️ O DEFAULT 'SIGCON-MG' e mantido de proposito: e o que existe
-- nos tres bancos de producao e no ORM (`models/convenio.py`), e o objetivo
-- desta migration e igualar o banco novo aos antigos, nao mudar o
-- comportamento dos clientes em producao. Os tres INSERTs que alimentam a
-- tabela (sigcon_scraper, gconv_es, run_fns_local) informam `fonte`
-- explicitamente, entao o default nunca e exercido na pratica. Se um dia ele
-- for removido — e ha bom argumento para isso, pela mesma razao que
-- `uf_sem_default_mg.sql` derrubou o default 'MG' de `municipios.uf` —, que
-- seja em migration propria, valendo para os quatro tenants de uma vez.
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS fonte VARCHAR(50) DEFAULT 'SIGCON-MG';

-- Campos do Relatorio de Monitoramento (RM). Preenchidos a mao pelo cliente na
-- tela, nao por coletor — por isso nunca apareceram como "faltando" em teste de
-- coleta.
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS banco VARCHAR(100);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS agencia VARCHAR(20);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS conta_corrente VARCHAR(50);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS saldo_bancario NUMERIC(18,2);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS dt_saldo DATE;
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS nr_sei VARCHAR(100);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS dt_empenho DATE;
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS dt_desembolso DATE;
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS tipo_programa VARCHAR(100);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS nr_indicacao VARCHAR(50);
ALTER TABLE convenios_estadual ADD COLUMN IF NOT EXISTS resolucao VARCHAR(100);
