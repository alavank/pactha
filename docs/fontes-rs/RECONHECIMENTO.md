# Reconhecimento de fontes — RS e federais ausentes

> Medições feitas em **02/09/2026**, contra os servidores reais.
>
> ⚠️ **Tudo abaixo foi medido do IP RESIDENCIAL do desenvolvedor**, salvo onde
> dito o contrário. Isso **não** prova que a VPS (`54.232.208.118`) recebe a
> mesma resposta — o TCE-RS é exatamente esse caso: 200 aqui, 403 de lá. O
> veredito de onde o coletor vai viver sai de
> `scripts/reconhecimento_fontes_vps.sh`, que ainda precisa rodar no servidor.

---

## 1. Veredito por fonte

| Fonte | Situação | O que decide |
|---|---|---|
| **SICONFI / Tesouro** | ✅ **integrado** | API ORDS pública, sem token. Ver §2 |
| **CAPAG (Tesouro Transparente)** | ✅ **integrado** | XLSX no CKAN. Ver §2 |
| **TCE-RS (CKAN)** | ⏸️ **pronto para medir da VPS** | Tem o dado por município e URLs previsíveis. Ver §3 |
| **Obras.gov.br / CIPI** | ⚠️ **medição inconclusiva** | Rate limit interrompeu a varredura. Ver §4 |
| **Diário dos Municípios (FAMURS)** | ❌ **não se aplica** | Nem Nova Palma nem Santa Maria publicam lá. Ver §5 |
| **Funrigs / reconstrução (CKAN do RS)** | ❌ **não está no CKAN** | Ver §6 |
| **S2iD (desastres)** | ⏸️ **viável, esforço médio** | Ver §7 |
| **Portal da Transparência (CGU)** e **dados.gov.br** | ⏸️ **dependem da conta gov.br** | Reabertos por decisão do dono |

---

## 2. SICONFI e CAPAG — integrados

**API:** `apidatalake.tesouro.gov.br/ords/siconfi`, pública, sem token.
Endpoints existentes: `entes`, `extrato_entregas`, `extrato_relatorios`, `rreo`,
`rgf`, `dca`, `msc_*`, `anexos-relatorios`, `tce_orcamentaria`.

**O que rendeu, medido:**

| Município | CAPAG | Indicadores |
|---|---|---|
| **Nova Palma** | **A+** | endividamento 0,016 (A) · poupança 0,779 (A) · liquidez 0,140 (A) |
| **Santa Maria** | **C** | endividamento 0,145 (A) · poupança 0,964 (C) · **liquidez −0,051 (C)** |
| Monte Sião (controle) | B | — |

A CAPAG define se o ente pode contratar operação de crédito **com garantia da
União**: Nova Palma pode, Santa Maria não. Nenhuma das duas informações existia
no produto.

`tt/entes` devolve os **5.598 entes numa requisição** com CNPJ e população —
é o que passou a preencher `municipios.cnpj` (CNPJ de Nova Palma:
`88488358000156`).

**As armadilhas medidas** (todas na docstring de `backend/ingestion/siconfi.py`):

1. **O porte muda o nome do demonstrativo.** Nova Palma publica `RREO
   Simplificado`; Santa Maria publica `RREO`. Consultar
   `co_tipo_demonstrativo=RREO` para Nova Palma devolve **HTTP 200 com
   `count: 0`** em 2023, 2024, 2025 e 2026 — leitura ingênua concluiria que a
   prefeitura nunca prestou contas ao Tesouro.
2. **Prefeitura e Câmara compartilham o `cod_ibge`** e vêm na mesma resposta,
   com a Câmara primeiro (15 linhas dela, 22 da prefeitura em 2025).
3. **`status_relatorio` não é uniforme:** RREO/RGF/DCA vêm `'HO'`; as MSC vêm
   `null` — as duas entregues. Filtrar por status descarta 12 das 22 entregas.
4. **O nome do recurso da CAPAG não é estável** (16 recursos, revisões do mesmo
   ano, grafia oscilando, um começando com espaço) → escolher por
   `last_modified`.
5. **O cabeçalho da planilha não está na 1ª linha** e os números vêm como texto
   com ponto decimal.

---

## 3. TCE-RS — a melhor fonte estadual, esperando um teste de IP

O CKAN tem **73.439 datasets**, organizados **por órgão e por ano**, e tem o que
o prompt pede em §2.1:

```
licitacoes-pm-de-nova-palma              contratos-pm-de-nova-palma
despesa-orcamentaria-por-empenhos-pm-de-nova-palma   (23 anos)
balancete-de-despesa / receita / verificacao         (por ano)
```

**URLs previsíveis a partir do código do órgão** — Nova Palma = **53100**,
Santa Maria = **56900** (a Câmara é 53101 / 56901 e não é o cliente):

```
dados/licitacon/licitacao/orgao/{orgao}.csv.zip     1,6 MB (NP) · 10,8 MB (SM)
dados/licitacon/contrato/orgao/{orgao}.csv.zip
dados/municipal/empenhos/{ano}/{orgao}.csv.zip      290 KB (NP, 2026)
```

**Com `ETag` e `Last-Modified`** — download condicional resolve o requisito de
não rebaixar o dataset todo dia. Licitações atualizadas em **31/08/2026**.

> ⚠️ **Duas conclusões antigas se contradiziam, e as duas estavam certas sobre
> coisas diferentes.** `docs/MAPA_RS.md` §12.5 diz "403 só para o IP da VPS";
> `docs/AUDITORIA_COLETA.md` diz "o CKAN não tem dataset de convênio/emenda/
> FUNRIGS — fechar o pedido de liberação". O CKAN de fato **não tem convênio nem
> emenda**; tem **licitação, contrato e empenho por município**, que é outra
> coisa e é o que interessa aqui. O bloqueio de IP continua sendo o único
> impedimento real, e é o primeiro item do script da VPS.

---

## 4. Obras.gov.br / CIPI — inconclusivo, e por um motivo específico

Público, sem login. O **OpenAPI** (`/obrasgov/api/api-obrasgov-docs`) resolveu a
armadilha central: **não existe filtro por município**. Os parâmetros reais são
`idUnico`, `situacao`, `codigoOrganizacao`, `nomeOrganizacao`, `uf`,
`dataCadastro`, `pagina`, `tamanhoDaPagina`. O `codigoIbge` que se supunha
existir é simplesmente ignorado (com ele, a API devolveu obra do **Amapá** para
o IBGE de Nova Palma).

Três armadilhas medidas:

1. **A paginação mente.** `last: true` em **toda** página, e `totalPages` /
   `totalElements` crescem conforme a página pedida (`totalElements` = tamanho
   da página). Um coletor que confiasse em `last` pararia na página 0 e
   afirmaria ter todas as obras do estado.
2. **As páginas se sobrepõem** — 41 dos 200 itens da página 1 repetiam a
   página 0. Dedup por `idUnico` é obrigatório.
3. **Rate limit agressivo, com corpo vazio.** HTTP **429** com `size=0` —
   indistinguível de "sem obras" para quem não checar o status. Recuperou com
   20–45 s de espera.

**Por isso a medição ficou inconclusiva:** a varredura de `uf=RS` parou na
página 2 por 429 persistente, com 397 projetos distintos coletados. **"Nova
Palma: 0 obras" não é conclusão** — é onde a varredura parou.

O caminho para o município existe: **`tomadores[].codigo` traz CNPJ de 14
dígitos para entes municipais** (ex.: `11413650000185` = Fundo Municipal de
Saúde de Canoas), que é a mesma disciplina de casamento por CNPJ do
`convenios_rs.py` e do `gconv_es.py`. Dos 397 medidos, 240 têm CNPJ em
tomador/executor e só 96 têm CEP ou endereço.

**Antes de codar:** repetir a varredura do IP da VPS (que não tem o histórico de
requisições de hoje) e medir o rate limit real de lá.

---

## 5. Diário Oficial dos Municípios (FAMURS) — não se aplica

`robots.txt` libera tudo (`Disallow:` vazio). É SIGPub, mas **não é a mesma
plataforma** de ES/GO: a rota `/busca/busca/buscar/query/…` que
`services/diario_sigpub.py` usa devolve **404** aqui. A busca real é GET em
`/famurs/pesquisar` com `busca_avancada[...]` e token CSRF.

**Mas a fonte não serve aos nossos tenants:** o select de entidades tem **303
entradas, 205 delas prefeituras** — de 497 municípios gaúchos — e **nem Nova
Palma nem Santa Maria estão na lista**. (Faxinal do Soturno, vizinha de Nova
Palma, está.) Elas publicam em outro veículo.

**Decisão:** não construir. Reavaliar se entrar tenant gaúcho que use o FAMURS.

---

## 6. Funrigs e reconstrução — não estão no dado aberto do Estado

Busca no CKAN `dados.rs.gov.br` por `funrigs`, `calamidade` e `reconstru`:
**zero pacotes** nos três. Confirma o que `docs/MAPA_RS.md` §13 registrou.

A página de dados abertos da CAGE
(`transparencia.rs.gov.br/dados-abertos/dados-transparencia-rs/dados/`) responde
200 mas **não expõe link de arquivo no HTML** — os downloads são montados por
JavaScript. O menu do portal confirma as seções que interessam (Calamidade
Pública 2024, Despesas do Estado, Emendas Parlamentares, Convênios e Parcerias).

**Próximo passo:** inspecionar as chamadas XHR da seção Calamidade Pública 2024
para achar o endpoint por trás — é o caminho para o Funrigs por credor.

⚠️ `dados.rs.gov.br` **falhou o handshake TLS** numa das tentativas e voltou
sozinho na seguinte. É a instabilidade já documentada; retry é condição de
funcionamento, não otimização.

---

## 7. S2iD — viável, esforço médio

`s2id.mi.gov.br` responde 200. Não há `robots.txt` (a rota devolve a página de
erro do JSF). As duas áreas públicas existem:
`/paginas/series/` (série histórica de reconhecimentos) e `/paginas/relatorios/`.

É **JSF/PrimeFaces com postback e ViewState** — o formulário da série histórica
dispara `PrimeFaces.ab(...)`, não uma querystring. Viável em httpx stateful (o
molde mais próximo é o `gconv_es`), mas é a fonte de maior esforço entre as
novas. O dado — reconhecimento federal de SE/ECP por município, com data e
portaria — é o eixo de desastre que hoje não existe no produto.

---

## 8. O que o script da VPS ainda precisa responder

`scripts/reconhecimento_fontes_vps.sh` — somente leitura, uma requisição por
fonte, com pausa. Rodar:

```bash
ssh -i ~/.ssh/coolify_localhost root@54.232.208.118 'bash -s' \
  < scripts/reconhecimento_fontes_vps.sh | tee recon.txt
```

Ele mede, do IP onde os coletores vivem: TCE-RS (o 403), Obras.gov.br (o rate
limit real), SICONFI, IBGE, S2iD, Transparência RS, `reconstrucao.fazenda.rs`,
Portal da Transparência da CGU, dados.gov.br e FAMURS — com dois **controles
positivos** (CHE e CKAN da CAGE, que já coletamos hoje) para separar "a fonte
bloqueia" de "a rede está ruim".
