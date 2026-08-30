# Dicionário oficial dos dados abertos do TransfereGov (SICONV)

Cópia versionada de propósito. O repositório antigo `repositorio.dados.gov.br/seges/detru/`
está congelado desde 17/07/2026 e é **desligado em 31/08/2026**; o host novo
(`api-publica.transferegov.gestao.gov.br/downloads/dadosgov/`) publica os 65 dumps CSV mas
**não** migrou o dicionário nem o histórico de versões (404 em ambos, conferido em 29/08/2026 —
ver `docs/AUDITORIA_COLETA.md`, seção B.6.1). Sem esta cópia, o mapeamento de colunas em
`backend/ingestion/transferegov_opendata.py` fica sem referência oficial.

| Arquivo | Origem | Baixado em | Tamanho | SHA-256 |
|---|---|---|---|---|
| `modelo_dados_siconv.zip` | `https://repositorio.dados.gov.br/seges/detru/modelo_dados_siconv.zip` (Last-Modified 17/07/2026 12:16 UTC) | 29/08/2026 23:46 BRT | 13.156.087 bytes | `42d8669748075f6e5387a21267727e64c1a6dcbfea5181b6063574a74dd81e37` |
| `historico_de_versoes.pdf` | `https://repositorio.dados.gov.br/seges/detru/historico_de_versoes.pdf` (Last-Modified 17/07/2026 12:16 UTC) | 29/08/2026 23:46 BRT | 270.014 bytes | `d8c732ea68dd72d605256334ef57caff767c1349a6f42b158c4ba40deaa42f6e` |

## Como usar

- **Navegar o modelo:** extraia o zip e abra `modelo_dados_sincov/index.html` (SchemaSpy —
  o nome da pasta interna vem assim, com o typo "sincov", do próprio MGI). Há também
  `columns.html`, `relationships.html` e `constraints.html`.
- **Ler por programa:** `modelo_dados_sincov/bd_portal.public.xml` traz as 53 tabelas com todas
  as colunas e tipos. É a base recomendada pela auditoria para uma **guarda de layout** no
  coletor (abortar a ingestão quando o cabeçalho do CSV divergir do esperado — hoje BOM/cabeçalho
  errado produz "zero em silêncio", ver comentário em `transferegov_opendata.py`).
- **Histórico de versões:** o PDF registra o que entrou em cada versão do modelo (v14 → v25;
  a v25, de 25/08/2025, é a última e incluiu `RESULTADO_PRIMARIO`, `OBSERVACAO_EMPENHO` e
  `DESCRICAO_EMENDA_SIAFI` em `empenho`).

## As 53 tabelas do modelo (nome → nº de colunas)

Cada tabela corresponde ao dump `siconv_<nome>.zip` no host novo (exceto as três já prefixadas
com `siconv_`). Os dumps que o PACTHA lê hoje estão marcados com ★.

| Tabela | Colunas | | Tabela | Colunas |
|---|---|---|---|---|
| ★ proposta | 36 | | itens_dl | 6 |
| ★ convenio | 40 | | itens_licitacao | 10 |
| ★ emenda | 10 | | justificativas_proposta | 8 |
| ★ programa | 20 | | licitacao | 18 |
| ★ programa_proposta | 2 | | meta_crono_fisico | 17 |
| ★ proposta_selecao_pac | 11 | | obtv_convenente | 5 |
| ★ pergunta_selecao_pac | 3 | | pagamento | 11 |
| ★ resposta_selecao_pac | 3 | | pagamento_tributo | 3 |
| ★ siconv_proposta_formalizacao_pac | 3 | | plano_aplicacao_detalhado | 15 |
| ★ proponentes | 11 | | programa_proponentes | 2 |
| acomp_obras_contratos_medicoes_modulo_empresas | 10 | | projeto_basico_acffo_modulo_empresas | 7 |
| acomp_obras_valores_itens_medicao_modulo_empresas | 6 | | projeto_basico_lae_modulo_empresas | 6 |
| ajuste_plano_trabalho | 5 | | projeto_basico_metas_modulo_empresas | 8 |
| apoiadores_emendas_programas | 13 | | projeto_basico_proposta_modulo_empresas | 3 |
| consorcios | 9 | | projeto_basico_submetas_modulo_empresas | 15 |
| contrato | 12 | | proposta_cancelada | 34 |
| cronograma_desembolso | 7 | | prorroga_oficio | 7 |
| desbloqueio_cr | 8 | | siconv_coordenadas_obra | 4 |
| desembolso | 11 | | siconv_resumo_fisico_financeiro | 4 |
| empenho | 18 | | solicitacao_alteracao | 6 |
| empenho_desembolso | 3 | | solicitacao_rendimento_aplicacao | 7 |
| etapa_crono_fisico | 13 | | termo_aditivo | 11 |
| historico_projeto_basico | 5 | | vrpl_lotes_fornecedores_licitacao_modulo_empresas | 6 |
| historico_situacao | 6 | | vrpl_metas_submetas_modulo_empresas | 18 |
| ingresso_contrapartida | 3 | | vrpl_proposta_licitacao_modulo_empresas | 9 |
| inst_cont_contratos_lotes_empresas_modulo_empresas | 12 | | | |
| inst_cont_metas_submetas_po_modulo_empresas | 15 | | | |
| inst_cont_proposta_aio_modulo_empresas | 5 | | | |

Candidatos apontados pela auditoria para substituir coleta por browser/sessão gov.br:
`empenho` (notas de empenho), `desembolso` + `empenho_desembolso` (OPs/OBs), `licitacao` +
`contrato` (processo de execução), `historico_projeto_basico` (situação do PB/TR),
`historico_situacao` (linha do tempo), `termo_aditivo` / `prorroga_oficio` /
`solicitacao_alteracao` (vigência e aditivos — escopo novo).

Regra: o `.gitignore` do repo bloqueia `*.zip` e `*.pdf`; estes dois arquivos têm exceção
explícita lá. Se o MGI publicar uma versão nova do modelo, substituir os arquivos **e** as
linhas de hash desta tabela no mesmo commit.
