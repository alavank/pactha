-- CADIN-MG histórico: do CRC que já está no banco para `cadastro_negativo`.
--
-- O item CADIN-MG é lido do CRC do CAGEC desde julho e vive em
-- `cagec_situacao.itens` como uma linha entre as ~27. Do PR anterior em diante o
-- `cagec_scraper` também o espelha em `cadastro_negativo` — mas só quando lê um
-- CRC NOVO. Sem este backfill, a aba de CADIN de um município mineiro nasceria
-- vazia e só se preencheria quando o rodízio passasse por ele, o que na Freitas
-- leva um dia inteiro (42 municípios, 11 por rodada, 4 rodadas).
--
-- ⚠️ RODA UMA VEZ POR BANCO (guarda em `migration_backfills`), como os backfills
-- de permissão. Repetir não corromperia nada — o UPSERT reescreveria o mesmo —,
-- mas carimbaria `consultado_em` com uma data de leitura que não aconteceu de
-- novo, e a tela existe justamente para dizer de quando é o dado.
--
-- ⚠️ SÓ ONDE HÁ `crc_em`: sem certificado lido não há linha de CADIN para
-- copiar, e inventar "nada consta" a partir da ausência é exatamente o erro que
-- o módulo inteiro evita. `consultado_em` recebe `crc_em`, que é a data REAL da
-- leitura — nunca `now()`.
WITH marca AS (
    INSERT INTO migration_backfills (nome)
    VALUES ('backfill_cadin_mg_do_crc:v1')
    ON CONFLICT (nome) DO NOTHING
    RETURNING nome
), origem AS (
    SELECT c.municipio_id,
           regexp_replace(c.cnpj, '\D', '', 'g') AS cnpj,
           c.nome AS entidade,
           COALESCE(c.uf, 'MG') AS uf,
           i->>'tipo' AS tipo,
           i->>'status' AS status_crc,
           c.crc_em
      FROM cagec_situacao c
      CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.itens, '[]'::jsonb)) i
     WHERE EXISTS (SELECT 1 FROM marca)
       AND i->>'codigo' = 'CADIN-MG'
       AND c.crc_em IS NOT NULL
       AND COALESCE(c.fonte, 'CAGEC-MG') = 'CAGEC-MG'
)
INSERT INTO cadastro_negativo (municipio_id, cnpj, entidade, uf, fonte, tipo,
                               situacao, consultado_em, atualizado_em)
SELECT municipio_id, cnpj, entidade, uf, 'CADIN-MG', tipo,
       -- A frase é a MESMA dos cadastros gaúchos: o gestor não deve ter de
       -- traduzir dois vocabulários dentro da mesma aba.
       CASE tipo
           WHEN 'regular' THEN 'Nada consta'
           WHEN 'pendente' THEN 'Consta inscrição'
           ELSE COALESCE(NULLIF(status_crc, ''), 'Não informado')
       END,
       crc_em, NOW()
  FROM origem
ON CONFLICT (municipio_id, cnpj, fonte) DO NOTHING;
