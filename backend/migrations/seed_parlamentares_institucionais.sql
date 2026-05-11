-- Seed de parlamentares "institucionais" - rotulos que aparecem nos PDFs Freitas
-- mas nao sao deputados individuais (programas, comissoes, blocos, etc.)
-- Cobrir esses rotulos eleva match PDF Freitas para 94%+ (Bom Despacho) e 100% (Piracema).
-- Idempotente: nao duplica se ja existir (case-insensitive).

INSERT INTO parlamentares (nome, esfera, uf, legislatura)
SELECT *, '2023-2027' FROM (VALUES
    -- Comissoes da Camara
    ('COMISSAO DA SAUDE', 'federal', 'BR'),
    ('COMISSAO SAUDE', 'federal', 'BR'),
    ('COMISSAO DE ASSUNTOS SOCIAIS - CAS', 'federal', 'BR'),
    ('COMISSAO MISTA DE PLANOS, ORCAMENTOS PUBLICOS E FISCALIZACAO', 'federal', 'BR'),
    ('COMISSAO DE EDUCACAO', 'federal', 'BR'),
    -- Bancadas
    ('BANCADA MG', 'federal', 'MG'),
    ('BANCADA EBPM', 'federal', 'MG'),
    -- Blocos (estaduais MG)
    ('BLOCO L. H. CARNEIRO', 'estadual', 'MG'),
    ('BLOCO DO DEPUTADO LUIZ HUMBERTO CARNEIRO', 'estadual', 'MG'),
    -- Programas federais sem indicacao parlamentar
    ('PROGRAMA', 'federal', 'BR'),
    ('PAC', 'federal', 'BR'),
    ('CFFO', 'federal', 'BR'),
    ('PROPOSTA VOLUNTARIA CADASTRADA - PROGRAMA', 'federal', 'BR'),
    ('DOACAO SELECAO NOVO PAC', 'federal', 'BR'),
    -- Programas estaduais MG
    ('PROMAQ', 'estadual', 'MG'),
    ('TRAVESSIA', 'estadual', 'MG'),
    -- Indicacoes compartilhadas (X / Y)
    ('VILSON / FETAEMG', 'estadual', 'MG'),
    ('FRED COSTA / REGINALDO LOPES', 'federal', 'MG'),
    -- Pessoas fisicas que faltam por motivos especificos
    ('AUREA CAROLINA', 'federal', 'MG'),  -- deputada PSOL-MG, sub-cadastrada
    ('ALEXANDRE SILVEIRA', 'federal', 'MG')  -- senador, atualmente Ministro (afastado da API "em exercicio")
) AS v(nome, esfera, uf)
WHERE NOT EXISTS (
    SELECT 1 FROM parlamentares p WHERE upper(p.nome) = upper(v.nome)
);
