-- Convencao de rotulo de cidade: "Nome Proprio (com acento) - UF".
-- Corrige os municipios seed que entraram em ASCII. Idempotente
-- (so troca se ainda estiver sem acento). Casa por ibge_code.
UPDATE municipios SET nome = 'Araújos'  WHERE ibge_code = '3104502' AND nome = 'Araujos';
UPDATE municipios SET nome = 'São Tiago' WHERE ibge_code = '3164704' AND nome = 'Sao Tiago';
UPDATE municipios SET nome = 'Monte Sião' WHERE ibge_code = '3143401' AND nome = 'Monte Siao';
