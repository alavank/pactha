-- Dedupe parlamentares duplicados (case-insensitive sem acentos) e cria
-- UNIQUE INDEX para impedir reincidencia. Idempotente.
--
-- Causa raiz: pipelines de ingestao (camara_despesas, emendas) inseriam
-- novo parlamentar a cada run quando o match por nome falhava (race condition
-- ou normalizacao inconsistente). Antes do helper services/institucional.py,
-- isso gerava 18+ copias do mesmo BLOCO/BANCADA/COMISSAO ao longo de meses.
--
-- Este script:
-- 1) Re-aponta FKs (emendas, dados_eleitorais, camara_despesas, etc) pro MIN(id)
-- 2) Para dados_eleitorais, deleta primeiro linhas que conflitariam com UQ
-- 3) Apaga dupes orfas
-- 4) Cria UNIQUE INDEX case-insensitive sem acentos

-- 1) Re-apontar FKs
DO $$
BEGIN
    -- dados_eleitorais: deletar linhas que conflitariam com UQ (parlamentar_id, municipio_id, ano_eleicao, cargo)
    DELETE FROM dados_eleitorais de
    USING (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d
    WHERE de.parlamentar_id = d.id AND d.id != d.keep_id
      AND EXISTS (
        SELECT 1 FROM dados_eleitorais de2
        WHERE de2.parlamentar_id = d.keep_id
          AND COALESCE(de2.municipio_id,-1) = COALESCE(de.municipio_id,-1)
          AND COALESCE(de2.ano_eleicao,-1) = COALESCE(de.ano_eleicao,-1)
          AND COALESCE(de2.cargo,'') = COALESCE(de.cargo,'')
      );

    -- emendas
    UPDATE emendas SET parlamentar_id = d.keep_id
    FROM (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d
    WHERE emendas.parlamentar_id = d.id AND d.id != d.keep_id;

    -- dados_eleitorais (depois de limpar conflitos)
    UPDATE dados_eleitorais SET parlamentar_id = d.keep_id
    FROM (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d
    WHERE dados_eleitorais.parlamentar_id = d.id AND d.id != d.keep_id;

    -- camara_despesas
    UPDATE camara_despesas SET parlamentar_id = d.keep_id
    FROM (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d
    WHERE camara_despesas.parlamentar_id = d.id AND d.id != d.keep_id;

    -- camara_votacoes
    UPDATE camara_votacoes SET parlamentar_id = d.keep_id
    FROM (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d
    WHERE camara_votacoes.parlamentar_id = d.id AND d.id != d.keep_id;

    -- emendas_camara
    UPDATE emendas_camara SET parlamentar_id = d.keep_id
    FROM (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d
    WHERE emendas_camara.parlamentar_id = d.id AND d.id != d.keep_id;
EXCEPTION WHEN undefined_table THEN
    -- Alguma tabela ainda nao existe (deploy fresco) - skip silencioso
    NULL;
END $$;

-- 2) Apagar dupes orfas
DELETE FROM parlamentares WHERE id IN (
    SELECT id FROM (
        SELECT id, MIN(id) OVER (PARTITION BY upper(translate(nome,
            'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
            'AEIOUAAEOAOCAEIOUAAEOAOC'))) AS keep_id
        FROM parlamentares
    ) d WHERE id != keep_id
);

-- 3) UNIQUE INDEX para impedir novas duplicatas
CREATE UNIQUE INDEX IF NOT EXISTS ix_parlamentares_nome_unaccent
ON parlamentares (upper(translate(nome,
    'ÁÉÍÓÚÀÂÊÔÃÕÇáéíóúàâêôãõç',
    'AEIOUAAEOAOCAEIOUAAEOAOC')));
