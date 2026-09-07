-- CADASTROS NEGATIVOS — CADIN e CFIL, a pergunta que faltava.
--
-- O cadastro estadual (`cagec_situacao`) responde "o ente está habilitado a
-- convêniar?". Estes respondem outra: "existe pendência INSCRITA contra ele?".
-- São coisas diferentes e a segunda trava sozinha: um fundo municipal sem
-- cadastro no CHE — portanto invisível na tabela do cadastro — pode estar
-- inscrito no CADIN e ter o repasse retido.
--
-- ⚠️ POR QUE NÃO REUSEI `cagec_situacao.itens_negativos`. As três colunas
-- (`itens_negativos`, `negativos_em`, `negativos_erro`) foram criadas em
-- `add_cadastro_estadual_rs.sql` prevendo esta fonte, e a premissa delas era que
-- toda entidade consultada teria linha no cadastro estadual. Medido em
-- 07/09/2026, a premissa é falsa **exatamente no caso que importa**: o Fundo
-- Municipal de Saúde de Nova Palma NÃO tem cadastro no CHE e é justamente quem
-- está inscrito no CADIN/RS (1 pendência, incluída em 28/08/2026 pela Secretaria
-- Estadual da Saúde). Guardar a certidão dele numa coluna de `cagec_situacao`
-- exigiria criar ali uma linha de cadastro que não existe — uma entidade
-- fantasma, que a tela desenharia como "cadastro sem exigência nenhuma".
-- As colunas antigas seguem existindo e sendo lidas pelo payload do cadastro
-- estadual; esta tabela é a fonte de verdade da aba de cadastros negativos.
--
-- ⚠️ NÃO É SÓ DO RS. `fonte` é coluna, não sufixo de tabela: hoje entram
-- 'CADIN-RS' e 'CFIL-RS' (coletor `ingestion/cadin_rs.py`, certidão pública da
-- CAGE/SEFAZ-RS) e 'CADIN-MG' (que já vinha lido do CRC do CAGEC, por
-- `ingestion/cagec_scraper.py`, e agora é gravado aqui também para a tela ter
-- UMA aba de CADIN que fala a mesma língua nos dois estados).
CREATE TABLE IF NOT EXISTS cadastro_negativo (
    id             SERIAL PRIMARY KEY,
    municipio_id   INTEGER NOT NULL REFERENCES municipios(id),
    -- 14 dígitos, sem máscara — a chave que a fonte aceita. A entidade pode
    -- não existir em `cagec_situacao` (é o caso do fundo acima), então NÃO há
    -- FK para lá: esta tabela vale por si.
    cnpj           VARCHAR(14) NOT NULL,
    -- Razão social como a própria certidão imprime ("FUNDO MUN DE SAUDE DE
    -- NOVA PALMA"). Guardado porque pode ser a única identificação que temos
    -- de uma entidade que não está no cadastro estadual.
    entidade       TEXT,
    uf             VARCHAR(2),
    -- 'CADIN-RS' · 'CFIL-RS' · 'CADIN-MG'.
    fonte          VARCHAR(20) NOT NULL,
    -- 'regular' (nada consta) · 'pendente' (consta) · 'indeterminado' (a
    -- certidão saiu e o texto não foi reconhecido). ⚠️ `indeterminado` NUNCA
    -- pode ser exibido como "nada consta": é o estado em que não sabemos.
    tipo           VARCHAR(16),
    -- A frase da fonte ("Nada consta", "Consta 1 pendência").
    situacao       TEXT,
    quantidade     INTEGER,
    -- Quem inscreveu, quando e o contato para sanar — só existe na certidão COM
    -- pendência, e é o que permite ao gestor AGIR em vez de só saber que está
    -- travado. {"orgao","inscrito_em","quantidade","contato"}
    detalhes       JSONB,
    -- ⚠️ A CERTIDÃO NÃO TEM VALIDADE: ela vale para a data em que foi emitida
    -- ("Certificamos que, na data de 07/09/2026..."). Sem este carimbo na tela,
    -- uma consulta de duas semanas atrás passa por situação de hoje.
    consultado_em  TIMESTAMPTZ,
    -- A frase do próprio portal quando a emissão falha. `tipo` nulo + erro
    -- preenchido é "não consultado", que é diferente de "nada consta".
    erro           TEXT,
    atualizado_em  TIMESTAMPTZ DEFAULT NOW()
);

-- Uma linha por entidade e por cadastro consultado.
CREATE UNIQUE INDEX IF NOT EXISTS ux_cadastro_negativo
    ON cadastro_negativo (municipio_id, cnpj, fonte);
CREATE INDEX IF NOT EXISTS ix_cadastro_negativo_mun
    ON cadastro_negativo (municipio_id);
