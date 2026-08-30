# Anexos da auditoria da coleta (29/08/2026)

Material de apoio de `docs/AUDITORIA_COLETA.md`. Tudo read-only e sem segredos.

- `sql/` — queries executadas no banco do tenant Freitas (só `SELECT`; toda sessão abriu com
  `SET default_transaction_read_only=on`). Nomes Qnn/Bnn/c07/c10 referenciados no relatório.
- `out/q00_q02.txt`, `q03_q05.txt`, `q06.txt`, `q08_q12.txt` — saídas das queries.
- `out/c07_c10_extrato.txt` — tasks, durações e estado da sessão gov.br lidos do `coolify-db`
  (extrato; as mensagens completas das execuções não foram versionadas).
- `out/reconciliacao.md` — reconciliação CSV oficial × banco (5 municípios), gerada por
  `reconcilia_tg.py` (downloads locais dos dumps de dados abertos; cache não versionado).
- `out/verificacao_resumo.txt` — vereditos dos 16 céticos sobre as afirmações de código.
- `out/bloco3_digest.txt` — digest da pesquisa web do Bloco 3 (7 grupos + céticos + crítico).
- `md2pdf.py` — gera o PDF do relatório (markdown → HTML → Chrome headless).

As saídas com dados pessoais (e-mails de usuários no `audit_log`) ficaram fora do repositório.
