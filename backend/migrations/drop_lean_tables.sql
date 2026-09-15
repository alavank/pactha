-- Refactor lean PACTHA (2026-05-16): mantemos apenas
--   SIGCON (convenios_estadual), FNS (real-time, sem tabela),
--   DOU/DOU-MG (real-time), Emendas estaduais, Cofre, Sessoes, Service Tokens.
-- Tudo o que e federal/transferego/portal-transparencia/prestacao/politica vai embora.

-- ATENCAO: irreversivel. Backup deve ter sido feito antes do deploy.
--
-- ⚠️ RODA EM BANCO NOVO E SEMPRE QUE FOR EDITADO (registro `migrations_aplicadas`;
-- ate 15/09/2026, a cada boot), e so e barata porque as tabelas NAO EXISTEM mais:
-- DROP ... IF EXISTS de tabela ausente nao pede lock. Ate 15/09/2026 o `setup_db.py`
-- recriava oito delas antes daqui, e o DROP ... CASCADE esperava lock em
-- `convenios_estadual`/`municipios` enquanto um coletor escrevia — o boot da API
-- estourava o healthcheck. Nenhuma tabela desta lista pode voltar a ser criada
-- (setup_db, modelo ou migration): `tests/test_boot_nao_recria_tabela_morta.py`.

DROP TABLE IF EXISTS emendas CASCADE;                  -- federal antiga (parlamentar_id+convenio_federal_id)
DROP TABLE IF EXISTS desembolsos CASCADE;              -- federal
DROP TABLE IF EXISTS convenios_federal CASCADE;        -- TransfereGov/PortalTransparencia/etc
DROP TABLE IF EXISTS editais CASCADE;
DROP TABLE IF EXISTS editais_acompanhamento CASCADE;
-- O nome que o `setup_db.py` de fato criava (sem o "s"): a linha de cima nunca a
-- achou, e ela sobrevivia a cada boot perdendo a FK para `editais` (15/09/2026).
DROP TABLE IF EXISTS edital_acompanhamento CASCADE;
DROP TABLE IF EXISTS notificacoes CASCADE;             -- push deltas SIGCON (sino)
DROP TABLE IF EXISTS oportunidades CASCADE;
DROP TABLE IF EXISTS prestacao_documentos CASCADE;     -- FK para prestacao_contas
DROP TABLE IF EXISTS plano_trabalho CASCADE;
DROP TABLE IF EXISTS notas_fiscais CASCADE;
DROP TABLE IF EXISTS prestacao_contas CASCADE;
DROP TABLE IF EXISTS dados_eleitorais CASCADE;
DROP TABLE IF EXISTS camara_despesas CASCADE;
DROP TABLE IF EXISTS camara_proposicoes CASCADE;
DROP TABLE IF EXISTS camara_votacoes CASCADE;
DROP TABLE IF EXISTS emendas_camara CASCADE;
DROP TABLE IF EXISTS dou_publicacoes CASCADE;          -- DOU eh real-time agora
DROP TABLE IF EXISTS sancoes_ceis CASCADE;
DROP TABLE IF EXISTS programas_federais CASCADE;
DROP TABLE IF EXISTS estabelecimentos_cnes CASCADE;
-- parlamentares NAO eh dropada: emendas_estaduais.parlamentar_id ainda referencia.
