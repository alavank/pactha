-- Obras.gov.br: as taxonomias viram TEXT, porque a fonte renomeia categoria.
--
-- 04/09/2026, durante a primeira carga de verdade. Santa Maria abortou inteira
-- com `StringDataRightTruncation` — e o culpado era **um caractere**:
--
--     natureza = 'Projeto de Investimento em Infraestrutura'   (41 chars)
--     coluna   = VARCHAR(40)
--
-- Nova Palma tinha passado minutos antes porque nenhuma das 30 obras dela usa
-- essa categoria. É a pior forma de bug: some no primeiro tenant e derruba o
-- segundo, com uma mensagem que não diz qual campo.
--
-- ⚠️ A LARGURA AQUI NÃO PROTEGE NADA. Estes campos são taxonomia de uma fonte
-- externa: hoje são 5, 6, 6 e 9 valores distintos (medidos sobre 32.300 obras
-- de RS/MG/GO/ES/TO), e o Governo pode renomear qualquer um deles amanhã sem
-- avisar — foi exatamente o que aconteceu na troca de host. Um VARCHAR ajustado
-- ao maior valor de hoje só garante que a próxima renomeação derrube a carga
-- inteira de novo. TEXT não custa nada no Postgres e falha zero vezes.
--
-- Os campos que continuam VARCHAR são os que têm formato, e não vocabulário:
-- `id_unico` (maior medido: 12), `cep` (10) e `uf` (2).
--
-- Em Postgres, VARCHAR(n) -> TEXT não reescreve a tabela: é instantâneo mesmo
-- com a tabela cheia.
ALTER TABLE obrasgov_projetos ALTER COLUMN natureza       TYPE TEXT;
ALTER TABLE obrasgov_projetos ALTER COLUMN especie        TYPE TEXT;
ALTER TABLE obrasgov_projetos ALTER COLUMN situacao       TYPE TEXT;
ALTER TABLE obrasgov_projetos ALTER COLUMN sistema_origem TYPE TEXT;
