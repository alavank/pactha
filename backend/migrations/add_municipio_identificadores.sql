-- Identificadores do município que hoje o sistema INFERE — e que fora de Minas
-- não há de onde inferir.
--
-- ⚠️ O CNPJ É O CASO QUE MOTIVA ESTA MIGRATION. Ele nunca esteve em
-- `municipios`: o `cagec_scraper` o deduz de `emendas_estaduais.cnpj_beneficiario`
-- ou de `transferegov_pac.cnpj`. Isso funciona em MG por acidente feliz — as
-- emendas estaduais só existem porque o SIGCON-MG as coleta.
--
-- Num tenant do Rio Grande do Sul as duas fontes falham juntas: `emendas_estaduais`
-- nunca terá linha (não há coletor de emenda estadual gaúcha) e `transferegov_pac`
-- está vazia no dia 1 de um tenant novo. Ou seja, o coletor do CHE — que precisa
-- só do CNPJ e de mais nada — sairia com "não se aplica" exatamente na semana em
-- que o cliente está olhando a tela. O CNPJ passa a ter origem própria,
-- preenchida por quem provisiona (`POST/PATCH /api/control/municipios`), que é o
-- mesmo canal que já exige a UF desde `uf_sem_default_mg.sql`.
--
-- Os demais campos vêm do mapa do RS (`docs/MAPA_RS.md` §13.1), mas nenhum deles
-- é gaúcho por natureza: código no tribunal de contas, conselho regional e
-- situação de calamidade existem em qualquer estado. Por isso nomes genéricos.

-- Só dígitos, sem máscara: é o formato que as APIs de governo aceitam
-- (che.sefaz.rs.gov.br devolve o index.html do Angular se receber a barra do
-- CNPJ mascarado). A máscara, quando precisa, é assunto de apresentação.
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS cnpj VARCHAR(14);

-- Conselho Regional de Desenvolvimento — os 28 do RS. É a dimensão de recorte
-- da Consulta Popular e de boa parte dos programas regionais gaúchos; nenhum
-- outro estado que atendemos usa esse recorte hoje, mas o nome não impede.
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS corede VARCHAR(60);

-- Código do órgão no tribunal de contas estadual. No TCE-RS ele é a chave de
-- TODAS as URLs de dado aberto (licitações, contratos, balancetes):
-- .../licitacon/licitacao/orgao/56900.csv.zip. ⚠️ A Câmara Municipal tem código
-- PRÓPRIO (56901 em Santa Maria) e NÃO é o cliente — descobrir por busca, nunca
-- por dedução a partir do código da prefeitura.
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS tce_orgao_codigo VARCHAR(10);

-- Fundo Municipal de Reconstrução: exigência do Fundo a Fundo do Plano Rio
-- Grande (FUNRIGS) para município atingido pelas enchentes de maio/2024.
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS fundo_reconstrucao BOOLEAN;
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS fundo_reconstrucao_obs TEXT;

-- ⭐ ATE QUANDO VALE A EXCECAO DE CALAMIDADE. É o antídoto do falso alarme do
-- Decreto Estadual 56.939/2023 (monitoramento mensal de convênios até o dia 15):
-- município em calamidade tem 120 dias em vez do prazo normal. Sem esta data, o
-- alerta acusaria atraso de quem está legalmente em dia — e alarme falso ensina
-- o cliente a ignorar o alarme verdadeiro.
ALTER TABLE municipios ADD COLUMN IF NOT EXISTS calamidade_ate DATE;

-- Índice PARCIAL, e é o detalhe que faz ele prestar: um UNIQUE cru trataria
-- todos os NULL como distintos (ok) mas barraria o segundo município com string
-- vazia. Assim ele pega o que interessa — o mesmo CNPJ colado em duas cidades,
-- que faria dois municípios coletarem a habilitação um do outro.
CREATE UNIQUE INDEX IF NOT EXISTS ux_municipios_cnpj
    ON municipios (cnpj) WHERE cnpj IS NOT NULL AND length(cnpj) = 14;

-- BACKFILL best-effort a partir do que já foi coletado, para os tenants antigos
-- não precisarem digitar o que o sistema já sabe.
--
-- ⚠️ EM BLOCO PRÓPRIO COM EXCEPTION, e não é zelo excessivo: o runner executa o
-- arquivo inteiro numa transação e engole a falha com uma linha de log. Um
-- `undefined_table` (tenant novo, onde `transferegov_pac` pode não ter nascido)
-- derrubaria junto os ALTERs acima — e ninguém veria, porque o boot continua.
--
-- ⚠️ E o `HAVING count(DISTINCT municipio_id) = 1` não é enfeite: CNPJ que
-- aparece em dois municípios é consórcio ou erro de origem, e adivinhar qual é o
-- dono é exatamente o tipo de palpite que o `gconv_es` e o `transfvol_go` se
-- recusam a dar. Ambíguo não entra; quem provisiona resolve.
DO $$
BEGIN
    UPDATE municipios m
       SET cnpj = s.cnpj
      FROM (
            SELECT municipio_id, min(cnpj) AS cnpj
              FROM (
                    SELECT municipio_id, regexp_replace(cnpj, '\D', '', 'g') AS cnpj
                      FROM transferegov_pac
                     WHERE cnpj IS NOT NULL
                       AND length(regexp_replace(cnpj, '\D', '', 'g')) = 14
                   ) t
             GROUP BY municipio_id
            HAVING count(DISTINCT cnpj) = 1
           ) s
     WHERE m.id = s.municipio_id
       AND m.cnpj IS NULL
       -- não colar um CNPJ que já pertence a outro município (o índice único
       -- abortaria a transação inteira, levando junto os ALTERs)
       AND NOT EXISTS (SELECT 1 FROM municipios o WHERE o.cnpj = s.cnpj);
EXCEPTION WHEN others THEN
    RAISE NOTICE 'backfill de municipios.cnpj pulado: %', SQLERRM;
END $$;
