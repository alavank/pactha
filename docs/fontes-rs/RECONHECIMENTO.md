# Reconhecimento de fontes — RS e federais ausentes

> Medições feitas em **02/09/2026**, contra os servidores reais.
>
> ⚠️ **Tudo abaixo foi medido do IP RESIDENCIAL do desenvolvedor**, salvo onde
> dito o contrário. Isso **não** prova que a VPS (`54.232.208.118`) recebe a
> mesma resposta — o TCE-RS é exatamente esse caso: 200 aqui, 403 de lá. O
> veredito de onde o coletor vai viver sai de
> `scripts/reconhecimento_fontes_vps.sh`, que ainda precisa rodar no servidor.

---

## 0. ⭐ MEDIDO DA VPS — 03/09/2026, 03:11 UTC

Rodado por `scripts/reconhecimento_fontes_vps.sh` do IP **54.232.208.118**, que
é onde os coletores vivem. **Os dois controles positivos passaram** (CHE em
`200`/362 ms e CKAN da CAGE em `200`/113 ms), então nada abaixo é problema de
rede — cada resultado é da fonte.

Carga do host no momento: **0,44 / 0,49 / 0,45**. Há folga.

| Fonte | Da VPS | Veredito |
|---|---|---|
| **TCE-RS** — CKAN, ZIP de licitações e ZIP de empenhos | **403 nos três** | ⛔ **Bloqueio confirmado**, terceira medição (17/08, 29/08, 03/09). Não é intermitência |
| **SICONFI** | `200`, 174 KB em 227 ms | ✅ livre |
| **IBGE** | `200` | ✅ livre |
| **S2iD** | `200`, 17 KB | ✅ livre (o que falta é o filtro, §7) |
| **Transparência RS** — dados abertos e calamidade | `200` | ✅ acessível, mas sem dado estruturado (§6) |
| **FAMURS** | `200` | ✅ acessível — e sem serventia para nossos municípios (§5) |
| **Portal da Transparência (CGU)** | `401` | ✅ a API responde; falta só a chave |
| **dados.gov.br** | `401` | idem |
| **Obras.gov.br** | **`429` na primeira requisição** | ⚠️ ver abaixo |
| **`reconstrucao.fazenda.rs`** | **`000` — sem resposta** | ⛔ não resolve da VPS. Reforça o veredito do §6 |

### O que isto decide

1. **TCE-RS entra pronto e DESLIGADO.** O coletor, os 22 testes e a tela estão
   feitos; a Scheduled Task **não é criada** enquanto o 403 valer. A tela diz,
   com todas as letras, que ausência de dado não é ausência de licitação. O
   caminho agora é institucional, não técnico: pedir liberação ao Tribunal.

2. **SICONFI pode ser ligado imediatamente.** 227 ms e 174 KB numa consulta
   real, do IP certo.

3. **⚠️ Obras.gov.br precisa de segunda medição.** O `429` veio na **primeira**
   requisição da bateria — e isso não distingue duas causas muito diferentes:
   penalidade acumulada no IP (o `INFRA.md` §5 documenta que a API de
   Transferências Especiais já deixou esta VPS 6 horas de castigo) ou recusa
   imediata a faixa de datacenter. A diferença importa: no primeiro caso o
   coletor funciona com espaçamento; no segundo, não funciona. **Não condenar a
   fonte com uma medição.**

---

## 1. Veredito por fonte (medições de 02/09, do IP residencial)

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

## 6. Funrigs e reconstrução — sem caminho de coleta hoje

> **Fechado em 03/09/2026, depois de percorrer os três caminhos possíveis.**

| Caminho tentado | Resultado |
|---|---|
| CKAN `dados.rs.gov.br` (`funrigs`, `calamidade`, `reconstru`) | **zero pacotes** nas três buscas |
| Painel do Funrigs no Portal da Transparência | redireciona para `/recursos-recebidos/` e é **Power BI** embutido — sem CSV, com token de embed dinâmico |
| Seção de dados abertos da CAGE | responde 200, mas **nenhum link de arquivo no HTML**: os downloads são montados por JavaScript |

**Veredito: não construir agora.** Raspar a API interna do Power BI é frágil por
natureza — o próprio `MAPA_RS.md` já registra isso para as emendas estaduais, e
seria a mesma dívida aqui. As saídas reais, em ordem de custo:

1. **Pedir o dado à CAGE** (LAI ou contato institucional): é despesa pública e
   já publicada; um CSV por credor resolveria de uma vez.
2. **Renderizar a página com o navegador** para capturar os links que o JS monta
   — só vale se a estrutura se provar estável.
3. Continuar como conteúdo curado, que é o estado atual.

A tela `/dashboard/funrigs` segue com `AvisoCurado`, dizendo que não é
automática. Isso continua correto — e agora está medido, não suposto.

---

## 6-b. Registro original da medição



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

## 7. S2iD — a estrutura está mapeada; o filtro, não

> **Atualizado em 03/09/2026, depois de tentar de verdade.** A conclusão de
> "esforço médio" abaixo era otimista: o POST JSF funciona, mas o filtro não.

**O que se conseguiu:**

- A sessão JSF abre, o `javax.faces.ViewState` é extraído e o POST parcial
  (`Faces-Request: partial/ajax`) responde **HTTP 200** com XML de update — ou
  seja, o servidor aceita o diálogo, não há captcha nem bloqueio.
- A tabela `resultados` tem **exatamente as colunas que interessam**:
  `Localidade · Municípios · Reconhecimentos · Estado de Calamidade Pública (ECP)
  · Situação de Emergência (SE) · Ano · Documento`.
- O select de recorte é por **UF** (`Brasil` + 27 estados), não por município.

**Onde parou:** selecionar `RS` e acionar o botão devolve a tabela **zerada**
(`Todos os registros acima | 0 | 0 | 0 | 0`). Falta um parâmetro — provavelmente
período/ano, que os componentes `j_idt23`/`j_idt25` sugerem. Duas sequências
foram tentadas (valueChange isolado, e valueChange seguido do botão com
`execute=@all`), com o ViewState renovado entre elas.

**⚠️ E há uma armadilha estrutural, independente disso:** os componentes têm id
gerado (`j_idt30`, `j_idt34`). Esses números **mudam quando o Estado edita a
página** — um coletor amarrado a eles quebra em silêncio na próxima manutenção,
e o sintoma seria exatamente este: tabela zerada, HTTP 200, nenhum erro. Se esta
fonte for retomada, o seletor tem de sair do **rótulo** ou da posição do
componente, nunca do `j_idt`.

**Recomendação:** retomar com o DevTools do navegador aberto na página, copiando
o POST real que o filtro dispara — meia hora de observação vale mais que
tentativa às cegas, e a Chrome extension do repo já serve para isso. O dado
(reconhecimento de SE/ECP por município, com data e portaria) continua valendo o
esforço: é o eixo de desastre que o produto não tem.

---

## 7-b. Nota original (16/08), mantida para contraste — "viável, esforço médio"

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
