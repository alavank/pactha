-- VOLUNTARIAS: o recebedor e a PREFEITURA? (15/09/2026)
--
-- `transferegov_opendata.py` entra por `COD_MUNIC_IBGE`, e isso traz tudo o que
-- esta SEDIADO na cidade. Medido nos dumps de Discricionarias em 15/09/2026:
-- em Goiania 75% do valor e do ESTADO DE GOIAS (1.897 propostas, R$ 8,2 bi),
-- em Palmas 82% e do Tocantins, em Santa Maria 33% e de entidades da sociedade
-- civil. Nenhum coletor, tela ou relatorio separava isso.
--
-- Decisao do dono: mostrar marcado ("nao e da prefeitura") e FORA das somas,
-- como em Parcerias. A regra e `services/natureza.py::e_municipal`.
--
-- `natureza_juridica` e o texto da fonte (`NATUREZA_JURIDICA` de
-- `siconv_proposta`). `municipal` e a regra aplicada NA COLETA:
--   TRUE  = Administracao Publica Municipal
--   FALSE = estado, OSC, consorcio, empresa publica
--   NULL  = a fonte nao disse (conta como municipal: `municipal IS NOT FALSE`)
--
-- ⚠️ SEM backfill aqui: o `raw_data` desta tabela guarda o registro ja
-- processado, sem a natureza. As colunas se preenchem na proxima rodada da task
-- `transferegov` (madrugada); ate la NULO conta como municipal — exatamente o
-- comportamento de antes.
ALTER TABLE transferegov_propostas
    ADD COLUMN IF NOT EXISTS natureza_juridica TEXT,
    ADD COLUMN IF NOT EXISTS municipal         BOOLEAN;
