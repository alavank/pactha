-- Dedupe convenios_estadual por nr_sigcon + cross-source convenios_federal
-- (PortalTransparencia <-> TransfereGov), e cria UNIQUE INDEX preventivo.
-- Idempotente. Aplicado pos-FNS scraper para limpar 1129 dupes SIGCON
-- + 40 dupes cross-source.

-- 1) SIGCON: re-aponta FKs antes de deletar
DO $$
BEGIN
    -- emendas
    UPDATE emendas SET convenio_estadual_id = d.keep_id FROM (
        SELECT id, MIN(id) OVER (PARTITION BY nr_sigcon) keep_id
        FROM convenios_estadual WHERE nr_sigcon IS NOT NULL
    ) d WHERE emendas.convenio_estadual_id = d.id AND d.id != d.keep_id;

    -- prestacao_contas
    UPDATE prestacao_contas SET convenio_estadual_id = d.keep_id FROM (
        SELECT id, MIN(id) OVER (PARTITION BY nr_sigcon) keep_id
        FROM convenios_estadual WHERE nr_sigcon IS NOT NULL
    ) d WHERE prestacao_contas.convenio_estadual_id = d.id AND d.id != d.keep_id;
EXCEPTION WHEN undefined_table THEN
    NULL;
END $$;

DELETE FROM convenios_estadual WHERE id IN (
    SELECT id FROM (
        SELECT id, MIN(id) OVER (PARTITION BY nr_sigcon) keep_id
        FROM convenios_estadual WHERE nr_sigcon IS NOT NULL
    ) d WHERE id != keep_id
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_convenios_estadual_nrsigcon
ON convenios_estadual (nr_sigcon) WHERE nr_sigcon IS NOT NULL;


-- 2) Cross-source federal: PortalTransparencia <-> TransfereGov
-- Mesmo (mun_id, ano, valor_repasse) com valor > 50k = mesmo convenio.
-- Prefere TransfereGov (tem dt_inicio, dt_fim, programa).
DO $$
BEGIN
    UPDATE emendas SET convenio_federal_id = dups.tg_id FROM (
        SELECT a.id pt_id, b.id tg_id FROM convenios_federal a
        JOIN convenios_federal b
          ON a.municipio_id=b.municipio_id AND a.ano=b.ano
          AND a.valor_repasse=b.valor_repasse AND a.valor_repasse > 50000
          AND a.fonte='PortalTransparencia' AND b.fonte='TransfereGov'
    ) dups WHERE emendas.convenio_federal_id = dups.pt_id;

    UPDATE desembolsos SET convenio_federal_id = dups.tg_id FROM (
        SELECT a.id pt_id, b.id tg_id FROM convenios_federal a
        JOIN convenios_federal b
          ON a.municipio_id=b.municipio_id AND a.ano=b.ano
          AND a.valor_repasse=b.valor_repasse AND a.valor_repasse > 50000
          AND a.fonte='PortalTransparencia' AND b.fonte='TransfereGov'
    ) dups WHERE desembolsos.convenio_federal_id = dups.pt_id;

    UPDATE prestacao_contas SET convenio_federal_id = dups.tg_id FROM (
        SELECT a.id pt_id, b.id tg_id FROM convenios_federal a
        JOIN convenios_federal b
          ON a.municipio_id=b.municipio_id AND a.ano=b.ano
          AND a.valor_repasse=b.valor_repasse AND a.valor_repasse > 50000
          AND a.fonte='PortalTransparencia' AND b.fonte='TransfereGov'
    ) dups WHERE prestacao_contas.convenio_federal_id = dups.pt_id;
EXCEPTION WHEN undefined_table THEN
    NULL;
END $$;

DELETE FROM convenios_federal a USING convenios_federal b
WHERE a.municipio_id=b.municipio_id AND a.ano=b.ano AND a.valor_repasse=b.valor_repasse
  AND a.valor_repasse > 50000
  AND a.fonte='PortalTransparencia' AND b.fonte='TransfereGov'
  AND a.id != b.id;
