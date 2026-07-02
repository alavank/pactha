-- Log de MUDANCAS DE STATUS detectadas nas atualizacoes (scrapers diarios).
-- Um trigger AFTER UPDATE compara situacao antiga x nova e registra a diferenca,
-- alimentando o aviso no dashboard. So registra mudanca REAL (IS DISTINCT FROM)
-- e so em UPDATE (linhas novas nao sao "mudanca de status").
CREATE TABLE IF NOT EXISTS status_changes (
    id              SERIAL PRIMARY KEY,
    municipio_id    INT,
    fonte           TEXT,        -- 'voluntaria' | 'fns' | 'sigcon'
    tabela          TEXT,
    ref             TEXT,        -- numero_proposta / nr_sigcon
    orgao           TEXT,
    objeto          TEXT,
    status_anterior TEXT,
    status_novo     TEXT,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_status_changes_mun ON status_changes (municipio_id, changed_at DESC);

CREATE OR REPLACE FUNCTION log_status_change() RETURNS trigger AS $$
DECLARE
    v_ref   text;
    v_fonte text;
    v_orgao text;
BEGIN
    IF NEW.situacao IS DISTINCT FROM OLD.situacao THEN
        IF TG_TABLE_NAME = 'transferegov_propostas' THEN
            v_ref   := NEW.numero_proposta;
            v_fonte := 'voluntaria';
            v_orgao := NEW.orgao;
        ELSE  -- convenios_estadual (SIGCON-MG + FNS)
            v_ref   := COALESCE(NEW.nr_sigcon, NEW.nr_plano_trabalho, NEW.nr_proposta);
            v_orgao := NEW.orgao_concedente;
            v_fonte := CASE WHEN upper(COALESCE(NEW.fonte, '')) LIKE '%FNS%'
                              OR upper(COALESCE(NEW.fonte, '')) LIKE '%MS%' THEN 'fns'
                            ELSE 'sigcon' END;
        END IF;
        -- Nao registra lixo: convenio sem objeto util ou sem referencia valida
        -- (ex.: linhas mal parseadas do SIGCON com objeto 'AA' / ref 'Nao ha')
        IF length(trim(coalesce(NEW.objeto, ''))) > 3
           AND coalesce(v_ref, '') !~* 'n[aã]o h' THEN
            INSERT INTO status_changes
                (municipio_id, fonte, tabela, ref, orgao, objeto, status_anterior, status_novo)
            VALUES
                (NEW.municipio_id, v_fonte, TG_TABLE_NAME, v_ref, v_orgao, NEW.objeto,
                 OLD.situacao, NEW.situacao);
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_status_change_tgprop ON transferegov_propostas;
CREATE TRIGGER trg_status_change_tgprop
    AFTER UPDATE ON transferegov_propostas
    FOR EACH ROW EXECUTE FUNCTION log_status_change();

DROP TRIGGER IF EXISTS trg_status_change_conv ON convenios_estadual;
CREATE TRIGGER trg_status_change_conv
    AFTER UPDATE ON convenios_estadual
    FOR EACH ROW EXECUTE FUNCTION log_status_change();
