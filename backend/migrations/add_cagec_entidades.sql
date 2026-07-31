-- CAGEC por ENTIDADE, não por município.
--
-- Descoberta que motivou: no CAGEC, Prefeitura, Fundo Municipal de Saúde, Fundo
-- Municipal de Assistência Social e CMAS são CADASTROS SEPARADOS, cada um com
-- CNPJ próprio, lista de exigências própria e situação própria. Prefeitura
-- regular NÃO destrava o convênio da saúde se o fundo estiver irregular — e o
-- PACTHA só olhava a prefeitura, então dizia "regular" com o convênio travado.
--
-- `cagec_situacao` tinha PK = municipio_id, ou seja, cabia UMA entidade. Agora a
-- chave é (municipio_id, cnpj). A linha da prefeitura continua existindo e
-- ganha `principal = true`, então quem já lia a tabela esperando "a" situação
-- do município continua funcionando filtrando por `principal`.

ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS tipo TEXT;
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS principal BOOLEAN DEFAULT FALSE;
ALTER TABLE cagec_situacao ADD COLUMN IF NOT EXISTS numero_cadastro TEXT;

-- Troca da PK. Idempotente: só age se a PK ainda for a antiga (só municipio_id).
DO $$
DECLARE
    cols int;
BEGIN
    SELECT count(*) INTO cols
    FROM information_schema.key_column_usage k
    JOIN information_schema.table_constraints t
      ON t.constraint_name = k.constraint_name AND t.table_name = k.table_name
    WHERE k.table_name = 'cagec_situacao' AND t.constraint_type = 'PRIMARY KEY';

    IF cols = 1 THEN
        -- Sem CNPJ não há como distinguir entidade; as linhas antigas são todas
        -- da prefeitura, então marcá-las como principal é o que descreve a
        -- realidade (e o coletor confirma no próximo ciclo).
        UPDATE cagec_situacao SET principal = TRUE WHERE principal IS DISTINCT FROM TRUE;
        UPDATE cagec_situacao SET tipo = COALESCE(tipo, 'Município');
        UPDATE cagec_situacao SET cnpj = COALESCE(NULLIF(cnpj, ''), 'sem-cnpj-' || municipio_id);

        ALTER TABLE cagec_situacao DROP CONSTRAINT IF EXISTS cagec_situacao_pkey;
        ALTER TABLE cagec_situacao ADD PRIMARY KEY (municipio_id, cnpj);
    END IF;
END $$;

-- Uma única entidade principal por município: se duas linhas virarem principal,
-- a tela passa a mostrar a errada sem erro nenhum.
CREATE UNIQUE INDEX IF NOT EXISTS cagec_situacao_principal_uniq
    ON cagec_situacao (municipio_id) WHERE principal;

CREATE INDEX IF NOT EXISTS cagec_situacao_municipio_idx ON cagec_situacao (municipio_id);
