-- Corrige bug historico SIGCON-MG: convenios "Transferencia Especial" com
-- vigencia indeterminada (30 anos) tinham `ano` = dt_vigencia_inicial.year
-- (ex: 2050) ao inves de dt_publicacao.year (real, ex: 2020).
--
-- Causa: scraper sigcon.py + run_sigcon.py usavam dt_ini.year como prioridade.
-- Fix scraper: trocou para dt_pub.year prioritario.
-- Esta migration: corrige os 138 registros historicos no DB.
--
-- Idempotente: so corrige onde ano > 2030 E diferenca dt_vigencia - dt_pub eh 30 anos.

UPDATE convenios_estadual
SET ano = ano - 30,
    dt_vigencia_inicial = dt_vigencia_inicial - INTERVAL '30 years',
    dt_vigencia_final = dt_vigencia_final - INTERVAL '30 years'
WHERE ano > 2030
  AND dt_publicacao IS NOT NULL
  AND dt_vigencia_inicial IS NOT NULL
  AND EXTRACT(year FROM dt_vigencia_inicial) - EXTRACT(year FROM dt_publicacao) BETWEEN 28 AND 32;
