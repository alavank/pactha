-- Refactor lean PACTA (2026-05-16): mantemos apenas
--   SIGCON (convenios_estadual), FNS (real-time, sem tabela),
--   DOU/DOU-MG (real-time), Emendas estaduais, Cofre, Sessoes, Service Tokens.
-- Tudo o que e federal/transferego/portal-transparencia/prestacao/politica vai embora.

-- ATENCAO: irreversivel. Backup deve ter sido feito antes do deploy.

DROP TABLE IF EXISTS emendas CASCADE;                  -- federal antiga (parlamentar_id+convenio_federal_id)
DROP TABLE IF EXISTS desembolsos CASCADE;              -- federal
DROP TABLE IF EXISTS convenios_federal CASCADE;        -- TransfereGov/PortalTransparencia/etc
DROP TABLE IF EXISTS editais CASCADE;
DROP TABLE IF EXISTS editais_acompanhamento CASCADE;
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
