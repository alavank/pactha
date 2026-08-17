-- As datas do TransfereGov são TEXTO em produção — e o setup_db as declarava DATE.
--
-- ⚠️⚠️ ISTO CORROMPIA DADO EM SILÊNCIO, e só apareceu no primeiro banco criado
-- do zero. Mesma classe do `add_convenios_estadual_colunas_faltantes.sql`: o
-- schema que o `setup_db` cria divergia do schema real dos bancos de produção,
-- que vieram migrados do Neon.
--
-- O QUE ACONTECIA. O coletor lê a data do detalhe do TransfereGov como texto no
-- formato brasileiro (`ingestion/transferegov_voluntarias.py`, `g("Data Início
-- de Vigência")` → "06/07/2026") e a passa crua ao INSERT. Nos três bancos
-- antigos a coluna é `character varying` e o texto entra como está. No banco
-- novo ela nasceu `date`, e o Postgres converteu usando o `DateStyle` padrão do
-- servidor — que é **MDY**:
--
--     "06/07/2026"  ->  6 de JULHO viraria 7 de JUNHO   (dia <= 12: TROCA CALADA)
--     "30/09/2027"  ->  mês 30: ERRO, e a rodada do município inteiro falha
--
-- Ou seja, dois estragos diferentes pelo mesmo motivo: vigência errada na tela
-- (sem erro nenhum) para metade das datas, e coleta abortada para a outra
-- metade. Medido em Santa Maria: 14 das 15 datas gravadas estavam trocadas — a
-- única correta era `07/07/2026`, e por coincidência de dia igual ao mês.
--
-- A CORREÇÃO É ALINHAR O BANCO NOVO AOS ANTIGOS, e não o contrário. Converter o
-- código para gravar `date` seria tecnicamente melhor, mas mudaria o formato dos
-- dados dos três clientes em produção e o que as telas leem — risco alto para
-- ganho nenhum hoje. Fica registrada a dívida: a data do TransfereGov é texto
-- `dd/mm/aaaa` em todo o sistema.

DO $$
DECLARE
    col text;
BEGIN
    FOREACH col IN ARRAY ARRAY['dt_inicio_vigencia', 'dt_fim_vigencia',
                               'dt_proposta', 'dt_assinatura']
    LOOP
        -- Só age onde a coluna nasceu `date` (o banco novo). Nos três bancos de
        -- produção já é varchar e este bloco é no-op.
        IF EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'transferegov_propostas'
                      AND column_name = col
                      AND data_type = 'date') THEN
            -- USING to_char preserva o que estiver lá, no formato que o resto do
            -- sistema espera. O valor pode estar TROCADO (ver acima) — o UPDATE
            -- logo abaixo conserta a partir da fonte.
            EXECUTE format(
                'ALTER TABLE transferegov_propostas ALTER COLUMN %I TYPE VARCHAR(20) '
                'USING to_char(%I, ''DD/MM/YYYY'')', col, col);
            RAISE NOTICE 'transferegov_propostas.% : date -> varchar', col;
        END IF;
    END LOOP;
END $$;

-- REPARO DO DADO JÁ GRAVADO ERRADO. A verdade está no `raw_data->'detalhe'`, que
-- guarda o texto exatamente como o portal o publicou. Onde o detalhe existe, ele
-- vence; onde não existe, a data vira NULL — "não sei" é melhor que uma vigência
-- errada na tela do gestor, e o coletor repõe na próxima rodada com o detalhe.
--
-- ⚠️ Guardado por `IS DISTINCT FROM`: roda uma vez, e nas próximas vira no-op.
-- Nos bancos antigos não encontra divergência (lá o texto sempre entrou íntegro).
UPDATE transferegov_propostas
   SET dt_inicio_vigencia = raw_data->'detalhe'->>'Data Início de Vigência'
 WHERE raw_data->'detalhe'->>'Data Início de Vigência' IS NOT NULL
   AND dt_inicio_vigencia IS DISTINCT FROM raw_data->'detalhe'->>'Data Início de Vigência';

UPDATE transferegov_propostas
   SET dt_proposta = raw_data->'detalhe'->>'Data da Proposta'
 WHERE raw_data->'detalhe'->>'Data da Proposta' IS NOT NULL
   AND dt_proposta IS DISTINCT FROM raw_data->'detalhe'->>'Data da Proposta';

UPDATE transferegov_propostas
   SET dt_assinatura = raw_data->'detalhe'->>'Data Assinatura'
 WHERE raw_data->'detalhe'->>'Data Assinatura' IS NOT NULL
   AND dt_assinatura IS DISTINCT FROM raw_data->'detalhe'->>'Data Assinatura';

-- O término de vigência tem DOIS rótulos possíveis no portal, e o coletor já
-- trata os dois (`g("Data Término de Vigência Atual", "Data Término de Vigência")`).
UPDATE transferegov_propostas
   SET dt_fim_vigencia = COALESCE(
           raw_data->'detalhe'->>'Data Término de Vigência Atual',
           raw_data->'detalhe'->>'Data Término de Vigência')
 WHERE COALESCE(raw_data->'detalhe'->>'Data Término de Vigência Atual',
                raw_data->'detalhe'->>'Data Término de Vigência') IS NOT NULL
   AND dt_fim_vigencia IS DISTINCT FROM COALESCE(
           raw_data->'detalhe'->>'Data Término de Vigência Atual',
           raw_data->'detalhe'->>'Data Término de Vigência');
