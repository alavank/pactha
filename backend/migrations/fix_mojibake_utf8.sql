-- Fix mojibake (UTF-8 lido como Latin-1, depois re-encoded UTF-8).
-- Sintoma: "PrestaÃ§Ã£o" deveria ser "Prestação", "ConvÃªnio" -> "Convênio".
-- Padroes mojibake mais comuns em pt-BR: Ã§ Ã£ Ã¡ Ã© Ã¢ Ãª Ã­ Ã³ Ãº Ã  Ã  Ã³
-- Filtro CRITICO: usar regex para nao tocar texto correto que tem letras
-- maiusculas com cedilha real (EXECUÇÃO).
--
-- Idempotente: roda so onde detecta padrao mojibake especifico.

DO $$
DECLARE
    cnt int;
    pattern text := '(Ã[§£¡¢¤¥¦¨©ª«¬­®¯°±²³´µ¶·¸¹º»¼½¾¿]|Â[¡¢£¤¥¦§¨©ª«¬­®¯°±²³´µ¶·¸¹º»¼½¾¿])';
BEGIN
    -- convenios_federal — tabela do refactor lean: desde 15/09/2026 o setup_db nao a
    -- recria mais (ver `drop_lean_tables.sql`), entao aqui ela normalmente NAO existe.
    BEGIN
        UPDATE convenios_federal SET situacao = convert_from(convert_to(situacao, 'LATIN1'), 'UTF8')
        WHERE situacao ~ pattern AND situacao IS NOT NULL;
        GET DIAGNOSTICS cnt = ROW_COUNT;
        RAISE NOTICE 'convenios_federal.situacao fixed: % rows', cnt;

        UPDATE convenios_federal SET objeto = convert_from(convert_to(objeto, 'LATIN1'), 'UTF8')
        WHERE objeto ~ pattern AND objeto IS NOT NULL;
        GET DIAGNOSTICS cnt = ROW_COUNT;
        RAISE NOTICE 'convenios_federal.objeto fixed: % rows', cnt;

        UPDATE convenios_federal SET orgao_concedente = convert_from(convert_to(orgao_concedente, 'LATIN1'), 'UTF8')
        WHERE orgao_concedente ~ pattern AND orgao_concedente IS NOT NULL;

        UPDATE convenios_federal SET programa = convert_from(convert_to(programa, 'LATIN1'), 'UTF8')
        WHERE programa ~ pattern AND programa IS NOT NULL;

        UPDATE convenios_federal SET proponente_nome = convert_from(convert_to(proponente_nome, 'LATIN1'), 'UTF8')
        WHERE proponente_nome ~ pattern AND proponente_nome IS NOT NULL;
    EXCEPTION WHEN undefined_table THEN NULL; END;

    -- convenios_estadual
    UPDATE convenios_estadual SET situacao = convert_from(convert_to(situacao, 'LATIN1'), 'UTF8')
    WHERE situacao ~ pattern AND situacao IS NOT NULL;

    UPDATE convenios_estadual SET objeto = convert_from(convert_to(objeto, 'LATIN1'), 'UTF8')
    WHERE objeto ~ pattern AND objeto IS NOT NULL;

    UPDATE convenios_estadual SET objetivo = convert_from(convert_to(objetivo, 'LATIN1'), 'UTF8')
    WHERE objetivo ~ pattern AND objetivo IS NOT NULL;

    UPDATE convenios_estadual SET orgao_concedente = convert_from(convert_to(orgao_concedente, 'LATIN1'), 'UTF8')
    WHERE orgao_concedente ~ pattern AND orgao_concedente IS NOT NULL;

    UPDATE convenios_estadual SET convenente_nome = convert_from(convert_to(convenente_nome, 'LATIN1'), 'UTF8')
    WHERE convenente_nome ~ pattern AND convenente_nome IS NOT NULL;

    -- programas_federais (oportunidades)
    BEGIN
        UPDATE programas_federais SET nome_programa = convert_from(convert_to(nome_programa, 'LATIN1'), 'UTF8')
        WHERE nome_programa ~ pattern AND nome_programa IS NOT NULL;
        UPDATE programas_federais SET orgao = convert_from(convert_to(orgao, 'LATIN1'), 'UTF8')
        WHERE orgao ~ pattern AND orgao IS NOT NULL;
        UPDATE programas_federais SET objetivo = convert_from(convert_to(objetivo, 'LATIN1'), 'UTF8')
        WHERE objetivo ~ pattern AND objetivo IS NOT NULL;
    EXCEPTION WHEN undefined_table THEN NULL; END;

    -- editais
    BEGIN
        UPDATE editais SET titulo = convert_from(convert_to(titulo, 'LATIN1'), 'UTF8')
        WHERE titulo ~ pattern AND titulo IS NOT NULL;
        UPDATE editais SET orgao = convert_from(convert_to(orgao, 'LATIN1'), 'UTF8')
        WHERE orgao ~ pattern AND orgao IS NOT NULL;
        UPDATE editais SET resumo = convert_from(convert_to(resumo, 'LATIN1'), 'UTF8')
        WHERE resumo ~ pattern AND resumo IS NOT NULL;
    EXCEPTION WHEN undefined_table OR undefined_column THEN NULL;
    END;

    -- parlamentares
    UPDATE parlamentares SET nome = convert_from(convert_to(nome, 'LATIN1'), 'UTF8')
    WHERE nome ~ pattern AND nome IS NOT NULL;
END $$;
