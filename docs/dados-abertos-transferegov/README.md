# Dicionários oficiais dos dados abertos do TransfereGov

Cópia versionada de propósito. O repositório antigo `repositorio.dados.gov.br/seges/detru/`
foi **desligado em 31/08/2026** (Comunicado nº 23/2026 do MGI) e hoje devolve 404. Em
29/08/2026 o host novo (`api-publica.transferegov.gestao.gov.br/downloads/dadosgov/`) ainda
não tinha migrado o dicionário do SICONV nem o histórico de versões (404 em ambos — ver
`docs/AUDITORIA_COLETA.md`, seção B.6.1); **isso mudou**: em 06/09/2026 o MGI publicou os
dicionários no portal `gov.br/transferegov`, e o SICONV **não ganhou conteúdo novo** — o
pacote novo (`modelo-dados-csvs-discricionarias-e-legais.zip`) é um repacotamento do mesmo
`modelo_dados_siconv.zip` e do mesmo `historico_de_versoes.pdf` já versionados aqui (SHA-256
idêntico, conferido nesta data). Por isso as duas linhas abaixo continuam com o conteúdo de
sempre — só a origem mudou, de um host morto para um que responde.

Além do SICONV, o comunicado também publicou APIs novas com dicionário próprio —
Transferências Especiais, Gestão de Parcerias e Fundo a Fundo —, cujos modelos entram na
tabela abaixo pela primeira vez. Sem esta cópia, o mapeamento de colunas em
`backend/ingestion/transferegov_opendata.py` (e o de qualquer coletor futuro para os módulos
novos) fica sem referência oficial.

O Obras.gov.br (`api-publica.obrasgov.gestao.gov.br/obras`) não tem dicionário em ZIP —
sua documentação é só o Swagger interativo e o `openapi.json` do próprio host, então não
há arquivo para versionar aqui.

| Arquivo | Origem | Baixado em | Tamanho | SHA-256 |
|---|---|---|---|---|
| `modelo_dados_siconv.zip` | `https://www.gov.br/transferegov/pt-br/ferramentas-gestao/paineis-gerenciais/arquivos/modelo-dados-csvs-discricionarias-e-legais.zip/@@download/file` (conteúdo idêntico ao publicado em `repositorio.dados.gov.br`, Last-Modified original 17/07/2026 12:16 UTC) | 29/08/2026 23:46 BRT | 13.156.087 bytes | `42d8669748075f6e5387a21267727e64c1a6dcbfea5181b6063574a74dd81e37` |
| `historico_de_versoes.pdf` | idem acima | 29/08/2026 23:46 BRT | 270.014 bytes | `d8c732ea68dd72d605256334ef57caff767c1349a6f42b158c4ba40deaa42f6e` |
| `modelo_dados_api-especiais.zip` | `https://www.gov.br/transferegov/pt-br/ferramentas-gestao/paineis-gerenciais/arquivos/modelo_dados_api-especiais.zip/@@download/file` | 06/09/2026 21:22 BRT | 11.489.380 bytes | `f515c484bf3832f730de47fbb18ddcaf46de311fee858192f9a4f0a40e8c59d3` |
| `modelo_dados_api_parcerias.zip` | `https://www.gov.br/transferegov/pt-br/ferramentas-gestao/paineis-gerenciais/arquivos/modelo_dados_api_parcerias.zip/@@download/file` | 06/09/2026 21:22 BRT | 11.580.759 bytes | `0d7804d4b14e46dbb3bfc050e298af21455d48324cf66b4e3b80c6f1d46f8556` |
| `modelo_dados_api_faf.zip` | `https://www.gov.br/transferegov/pt-br/ferramentas-gestao/paineis-gerenciais/arquivos/modelo_dados_api_faf.zip/@@download/file` | 06/09/2026 21:23 BRT | 22.670.862 bytes | `d03342c818fc904432b7b07693a97bfb8082c78eff51d38624b723dceeb50ad1` |

O portal `gov.br` não expõe `Last-Modified` nestes links (ao contrário do antigo blob do
`repositorio.dados.gov.br`); a coluna "Baixado em" é a única data confiável para estes três.

## Como usar — SICONV (dados abertos/CSV, Discricionárias e Legais)

- **Navegar o modelo:** extraia `modelo_dados_siconv.zip` e abra `modelo_dados_sincov/index.html`
  (SchemaSpy — o nome da pasta interna vem assim, com o typo "sincov", do próprio MGI). Há também
  `columns.html`, `relationships.html` e `constraints.html`.
- **Ler por programa:** `modelo_dados_sincov/bd_portal.public.xml` traz as 53 tabelas com todas
  as colunas e tipos. É a base recomendada pela auditoria para uma **guarda de layout** no
  coletor (abortar a ingestão quando o cabeçalho do CSV divergir do esperado — hoje BOM/cabeçalho
  errado produz "zero em silêncio", ver comentário em `transferegov_opendata.py`).
- **Histórico de versões:** o PDF registra o que entrou em cada versão do modelo (v14 → v25;
  a v25, de 25/08/2025, é a última e incluiu `RESULTADO_PRIMARIO`, `OBSERVACAO_EMPENHO` e
  `DESCRICAO_EMENDA_SIAFI` em `empenho`).

## Como usar — APIs REST novas (Especiais, Parcerias, Fundo a Fundo)

Os três zips seguem o mesmo gerador (SchemaSpy), mas **sem** a pasta intermediária do SICONV:
o `index.html` já fica na raiz do zip.

- `modelo_dados_api-especiais.zip` → extrair e abrir `index.html` na raiz. 18 tabelas
  documentadas — módulo `/especiais`, coletado inteiro por `ingestion/transferegov_te.py`
  (`CONTINUAR.md` §1.23).
- `modelo_dados_api_parcerias.zip` → idem, `index.html` na raiz. 27 tabelas — módulo
  `/parcerias`, coletado inteiro por `ingestion/parcerias.py` (`CONTINUAR.md` §1.24).
- `modelo_dados_api_faf.zip` → idem, `index.html` na raiz. 25 tabelas — módulo `/fundoafundo`,
  coletado inteiro por `ingestion/faf_planos.py` (`CONTINUAR.md` §1.25). ⚠️ O zip do MGI duplica a árvore inteira sob
  `home/dandedf/dev/cgimo/apis/schemaspy/schemaspy-output/` (caminho absoluto da máquina que
  gerou o export, vazado no pacote) **além** da cópia na raiz — as duas são idênticas; use a
  da raiz e ignore a duplicata.

Os nomes de tabela do dicionário usam `_` onde a API usa `-` (ex.: tabela
`planos_acao_especiais` ↔ endpoint `GET /especiais/planos-acao-especiais`) — normal do
SchemaSpy, não é divergência de dado.

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

Regra: o `.gitignore` do repo bloqueia `*.zip` e `*.pdf`; os cinco arquivos desta pasta têm
exceção explícita lá. Se o MGI publicar uma versão nova de qualquer um dos modelos, substituir
o arquivo **e** a linha de hash correspondente nesta tabela no mesmo commit.

Não versionamos `modelo-dados-csvs-discricionarias-e-legais.zip` em si — é o wrapper que o MGI
publica hoje em torno do SICONV (ver acima); manter os dois arquivos internos, já extraídos,
evita duplicar os mesmos 13 MB duas vezes no repositório.
