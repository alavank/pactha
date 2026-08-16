-- `cagec_situacao` deixa de ser "a tabela do CAGEC" e passa a ser A TABELA DO
-- CADASTRO ESTADUAL DE CONVENENTES, qualquer que seja o estado.
--
-- ⚠️ POR QUE REUSAR A TABELA EM VEZ DE CRIAR `che_situacao`. O CHE gaúcho
-- (che.sefaz.rs.gov.br, IN CAGE 01/2006) responde exatamente a mesma pergunta
-- que o CAGEC mineiro — "este ente pode assinar convênio com o Estado?" — e
-- entrega o mesmo formato: N exigências, cada uma com validade própria. Uma
-- tabela nova obrigaria a duplicar SEIS peças que já existem e que, duplicadas,
-- divergiriam com o tempo:
--
--   routers/cagec.py                     o payload no formato do CAUC
--   dashboard/cauc/page.tsx              as duas colunas da tela de regularidade
--   services/bi_abas.py::_cagec_bloco    a aba Documentos do Painel
--   run_painel_alertas_cron.py           o alerta de vencimento em 30/15/7 dias
--   bi_abas.prazos_dos_itens             a regra de prazo (tela e alerta juntos)
--   routers/freshness.py                 a linha no monitor de frescor
--
-- O nome da tabela fica como está de propósito: renomear custa três bancos
-- vivos e dezenas de referências, e não compra nada que um comentário não
-- compre. Quem lê `cagec_situacao` deve entender "cadastro estadual".

-- QUEM ESCREVEU A LINHA. É a coluna que sustenta tudo o mais: sem ela, a purga
-- de `uf_sem_default_mg.sql` (que apaga por UF) apagaria o CHE a cada boot, e o
-- `_limpar_sumidos` de um coletor apagaria a entidade do outro.
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS fonte VARCHAR(40);

-- O JSON cru da consulta. O CHE devolve muito mais do que cabe em `itens`
-- (listaAvaliacao com as adesões a programas estaduais, ids internos da
-- entidade, quem atualizou cada documento e quando). Jogar isso fora significa
-- ter de raspar de novo para responder qualquer pergunta nova.
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS raw_data JSONB;

-- ⚠️ CADASTROS NEGATIVOS EM COLUNA PRÓPRIA, e isto não é organização: é uma
-- trava contra corrida entre coletores. CADIN/RS e CFIL/RS vêm de OUTRO portal
-- (o e-CAGE), em OUTRA rodada, com OUTRO horário. Se fossem mesclados em
-- `itens`, a rodada do CHE — cujo upsert faz `itens = EXCLUDED.itens` — apagaria
-- as pendências do CADIN em silêncio, e a tela mostraria "nada consta" para um
-- município travado.
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS itens_negativos JSONB;
-- De quando é a consulta negativa. Mesma função de `crc_em`: sem ela a tela não
-- consegue distinguir "consultei e não há pendência" de "não consultei" — e as
-- duas coisas pintam de verde exatamente do mesmo jeito.
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS negativos_em DATE;
-- A frase do próprio portal quando a consulta falha.
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS negativos_erro TEXT;

-- Carimba a procedência do que já existe. Hoje só o coletor mineiro escreve
-- nesta tabela, então toda linha sem fonte é dele. Guardado por `IS NULL`:
-- roda uma vez nos três bancos vivos e vira no-op; no banco novo não acha nada.
UPDATE cagec_situacao SET fonte = 'CAGEC-MG' WHERE fonte IS NULL;

CREATE INDEX IF NOT EXISTS ix_cagec_situacao_fonte ON cagec_situacao(fonte);
