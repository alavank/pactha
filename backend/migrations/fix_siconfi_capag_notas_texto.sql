-- As notas parciais da CAPAG viram TEXT: `VARCHAR(2)` nao cabe "n.d.".
--
-- ⚠️ NAO E TEORIA — a fase inteira da CAPAG morria por causa disto. Medido no
-- freitas em 07/09/2026, na primeira rodada do `siconfi` naquele tenant:
--
--     Córrego Danta/MG: CAPAG n.d. (endividamento A, poupanca B, liquidez n.d.)
--     [WARNING] CAPAG falhou: StringDataRightTruncation:
--               value too long for type character varying(2)
--     === SICONFI: 1385 linha(s) gravada(s), 1 falha(s) ===
--
-- O Tesouro publica "n.d." (nao disponivel) quando o indicador nao pode ser
-- apurado, e sao QUATRO caracteres. A coluna `nota` ja era `VARCHAR(4)` e
-- aguentava; as tres parciais nasceram `VARCHAR(2)` porque a leitura da fonte
-- foi feita sobre as notas que se esperava ver ('A', 'B', 'C', 'D') e o "n.d."
-- nao estava na amostra.
--
-- O efeito nao e perder UMA linha: a exception derruba o bloco inteiro da CAPAG,
-- entao UM municipio com indicador nao apurado zera a coleta da nota de TODOS
-- os municipios do tenant. A tela de Regularidade fica sem CAPAG nenhuma e o log
-- diz apenas "1 falha(s)".
--
-- ⭐ TEXT, e nao VARCHAR(4). E a regra que o proprio repo ja escreveu duas vezes
-- (`add_obrasgov_taxonomias_text.sql`, `add_emendas_federais_texto.sql`): texto
-- que vem de fonte externa nasce TEXT, porque a fonte muda o vocabulario sem
-- avisar e a largura so existe para nos trair. Largura fica para formato que NOS
-- controlamos (CNPJ 14, UF 2, codigo_emenda 12).
--
-- Idempotente: `ALTER ... TYPE` para o tipo que a coluna ja tem e no-op logico,
-- e o bloco so age quando encontra a largura antiga.

DO $$
DECLARE
    coluna text;
BEGIN
    FOREACH coluna IN ARRAY ARRAY['nota_endividamento', 'nota_poupanca',
                                  'nota_liquidez', 'nota', 'icf']
    LOOP
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_name = 'siconfi_capag'
               AND column_name = coluna
               AND data_type = 'character varying')
        THEN
            EXECUTE format('ALTER TABLE siconfi_capag ALTER COLUMN %I TYPE TEXT', coluna);
            RAISE NOTICE 'siconfi_capag.%: VARCHAR -> TEXT', coluna;
        END IF;
    END LOOP;
END $$;
