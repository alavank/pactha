# TCE-RS: as APIs do `portal.tce.rs.gov.br`

> **Achado de 03/09/2026 — e o desfecho, no mesmo dia.** O Tribunal publica APIs
> abertas em `portal.tce.rs.gov.br`, com **todo o acervo** do CKAN bloqueado e
> mais obras, medições e a origem do recurso. Elas respondem sem autenticação
> nenhuma **de conexão residencial**.
>
> ⛔ **E respondem 403 do IP da VPS, exatamente como o CKAN.** Medido em
> 03/09/2026 11:53 UTC: os dois hosts devolvem o **mesmo corpo** (199 bytes,
> página padrão "403 Forbidden") no **mesmo tempo** (0,08–0,09 s), enquanto o
> CHE/SEFAZ-RS responde 200 do mesmo IP no mesmo minuto. Não era "um host
> bloqueado": é **uma regra de borda para o domínio `tce.rs.gov.br` inteiro**.
>
> Consequência: o coletor entra **pronto e desligado**, como o `tce_rs` e o
> `obrasgov`, e o **ofício volta a ser o caminho crítico** — agora valendo muito
> mais, porque destrava o acervo inteiro e as obras, não só os CSV.
>
> ⚠️ **Este documento foi corrigido duas vezes em 03/09.** A versão da manhã
> afirmava três coisas que a medição derrubou: a remessa como prova de
> pontualidade (§4), a perda do acervo histórico (§1) e o bloqueio como sendo de
> um host só (esta nota). Ficam registradas, com o que as desmentiu, porque o
> erro em si é a lição.

---

## 1. O que isso muda

**O ofício continua sendo o caminho, e passou a valer mais.** A esperança de
contornar o bloqueio por outro host morreu na medição da VPS (ver a nota do
topo): o filtro é do domínio inteiro. O que mudou é o **tamanho do prêmio** — o
que a liberação destrava não é mais "os CSV do LicitaCon", e sim o acervo
inteiro por API, mais o LicitaCon Obras com medição, saldo e a origem do
recurso. O ofício da `OFICIO-TCE-RS.md` foi reescrito para pedir os dois
serviços e para declarar essa finalidade.

**E não se perde o acervo histórico** — nem por um caminho, nem pelo outro.
Medido do IP residencial:

| | CKAN (bloqueado) | API do portal |
|---|---|---|
| Licitações de Nova Palma | 864 | **866** (2012–2026) |
| Contratos de Nova Palma | 1.201 | **1.202** (2007–2026) |
| Licitações de Santa Maria | — | 5.290 |
| Contratos de Santa Maria | — | 6.213 |

A diferença de dois registros são contratos incluídos em 31/08, depois da última
medição do CKAN. **É o mesmo acervo, e mais recente.**

O que o CKAN tem e a API **não**: `VL_LICITACAO` e `VL_HOMOLOGADO` — o valor
estimado e o homologado do certame. Não existem em endpoint nenhum do portal
(conferido no Swagger, nos 15 campos da lista e nos 27 do detalhe). Em
compensação, o portal traz o **valor do contrato em duas versões** (inicial e
depois dos aditivos), que o CSV não separava, mais o **nome** do contratado, os
fiscais e os eventos.

As duas fontes continuam complementares — mas agora a que funciona é a maior.

---

## 2. As duas APIs

### 2.1 Queryon — `/api/qonws/q` (sem autenticação)

Contrato em `https://portal.tce.rs.gov.br/api/qonws/swagger` (Swagger 2.0,
53 KB). `securityDefinitions` **vazio**. O `{syntax}` do caminho é o formato:
use `json`.

| Endpoint | Parâmetros obrigatórios | O que traz |
|---|---|---|
| `licitacon_dominios.orgaos` | — | ⭐ **de-para oficial** dos 1.344 órgãos: `CD_ORGAO` · `CNPJ` · `CD_MUNICIPIO_IBGE` · `TIPO` · `SITUACAO_ORGAO` |
| `licitacon.licitacoes` | `cd_orgao`, `tp_situacao`, `origem` | ⭐ o acervo de licitações do órgão |
| `licitacon.contratos` | `cd_orgao`, `tp_situacao`, `origem` | ⭐ o acervo de contratos |
| `licitacon.licitacao` | + `cd_tipo_modalidade`, `nr_licitacao`, `ano_licitacao` | detalhe: processo, fundamentação legal, data de abertura, resultado |
| `licitacon.contrato` | + `tp_instrumento`, `nr_contrato`, `ano_contrato` | ⭐ detalhe: **valores**, contratado, vigência, fiscais, eventos |
| `licitacon.remessas` | `cd_orgao`, `ano_exercicio`, `periodo` | por qual via o órgão opera (ver §4) |
| `licitacon_obras.obras_por_orgao` | `cd_orgao` | obras do órgão (25 campos) |
| `licitacon_obras.obra` | `id_obra` | ⭐ **50 campos**: medições, aditivos, licenças, coordenadas e **origem do recurso** |
| `licitacon.comissoes`, `licitacon.orgaos_modo_acesso`, `licitacon_dominios.fundamentacoes_legais` | vários | apoio |

Todos aceitam `fields`, `order`, `limit`, `offset`. Não há teto de `limit`
(5.000 devolveu o acervo inteiro sem reclamar); `[]` com HTTP 200 é a resposta
para órgão inexistente, e parâmetro obrigatório faltando dá **400** com a
mensagem dizendo qual é.

**⚠️ `tp_situacao` e `origem` derrubaram a primeira leitura.** Os valores estão
no Swagger e são `A` (em andamento), `E` (encerradas) e `ALL`; e `WEB`
(LicitaCon Web), `VAL` (eValidador) e `ALL`. A tentativa da manhã usou oito
combinações inventadas, recebeu listas vazias e concluiu que o endpoint não
servia para consulta. **Com `ALL/ALL` ele devolve tudo** — foi o que destravou
todo o resto.

### 2.2 LicitaCon Obras — `/api/obras` (leitura sem token)

Contrato em `/api/obras/v3/api-docs` (OpenAPI 3, 189 KB, 75 caminhos). Declara
`securitySchemes: bearer-key` e tem `POST /autenticacao` — mas os GET responderam
**200 sem token**.

**Não é o caminho que usamos.** Os 75 endpoints REST cobram uma requisição por
aspecto de cada obra (medições, licenças, aditivos, fotos, documentos). O
Queryon entrega tudo isso **aninhado numa única chamada** de
`licitacon_obras.obra` — e é de lá que sai a origem do recurso. A API REST fica
documentada para o caso de o Queryon mudar, e para os documentos e fotos, cujos
downloads são links dela.

Instituído pela **Resolução 1.176/2023** e regulamentado pela **IN 6/2023**;
obrigatório para órgãos municipais desde **08/01/2024**.

**Medido:** Santa Maria, **120 obras**; Nova Palma, **0** — resultado legítimo,
o sistema é de 2024 e o município tem 5,6 mil habitantes. **Não confundir com
falha de coleta**; a mesma disciplina do SISMOB.

---

## 3. ⭐ A origem do recurso — por que a obra importa num produto de convênios

Exemplo real, obra 436 de Santa Maria (drenagem e pavimentação no bairro Diácono
João Luiz Pozzobon):

```
Convênio/Repasse Federal · Ministério da Integração e do Desenvolvimento Regional
Processo 59053.018691/2024-19 · R$ 2.431.396,74 · contrapartida R$ 0,00
contrato 122/2024 · R$ 1.878.613,49 inicial, R$ 2.430.766,29 atual
14 medições · R$ 2.297.053,89 medido · saldo R$ 237.499,12
financeiro 90,6% · físico 0,0%
```

Em nenhuma outra fonte do PACTHA esse vínculo existe **declarado pelo próprio
município ao órgão de controle**. O TransfereGov mostra o repasse; o LicitaCon
mostra o contrato; esta é a única que diz *esta obra foi paga por aquele
convênio* — e quanto dela já foi medido.

⚠️ **Os dois percentuais divergem** (90,6% financeiro contra 0,0% físico na mesma
obra): o órgão mede o pagamento e não alimenta o avanço físico. Mostrar um pelo
outro inventaria execução que ninguém declarou.

---

## 4. ⚠️ A remessa NÃO mede pontualidade — o erro da primeira versão

**A versão da manhã deste documento dizia:**

> ⭐ `licitacon.remessas` é o achado mais valioso, e não estava em nenhum plano.
> Ele responde a pergunta que a tela `/dashboard/tce-rs` hoje diz **não** saber
> responder: *o município entregou a remessa?*

**Está errado.** A remessa do tipo **"LicitaCon WEB" é a carga noturna do próprio
Tribunal**, não a entrega do município. A medição que derrubou a tese: nove
órgãos de **oito tipos diferentes** (prefeitura, autarquia, fundação, consórcio,
empresa pública, S/A, associação, Ltda) têm, no mesmo período, a **mesma data e o
mesmo horário**.

| Período | Data de "recebimento" | Horário |
|---|---|---|
| 2026/7 | 10/08/2026 | 05:12 a 05:19 |
| 2026/6 | 07/07/2026 | 05:12 a 05:18 |
| 2025/12 | 08/01/2026 | 05:12 a 05:17 |

Nova Palma e Santa Maria coincidem nos **19 meses** conferidos, sempre entre o 7º
e o 12º dia do mês seguinte. Uma prefeitura que atrasasse teria a data de uma que
não atrasou.

A remessa do tipo **e-Validador** é envio de verdade — as quatro de Nova Palma em
agosto/2025 são de 15, 22, 27 e 29/08, e nenhum outro órgão tem essas datas. Mas
quem registra direto no LicitaCon Web não envia nenhuma, e Nova Palma parou de
enviar em 2026.

**O que a remessa serve, então:** dizer **por qual via** o município opera (Web ou
e-Validador), se o período foi consolidado, e quem é o responsável cadastrado.
É pouco, e é honesto.

### O que de fato mede pontualidade

A defasagem entre **assinar** (`DT_ASSINATURA`) e **registrar no Tribunal**
(`DATA_INCLUSAO`) — os dois vêm do detalhe do contrato. Medido em 25 contratos
recentes de cada município:

| Município | mínimo | mediana | máximo | acima de 30 dias |
|---|---|---|---|---|
| Nova Palma | 0 | **1 dia** | 5 | 0 |
| Santa Maria | 0 | **5 dias** | 6 | 0 |

**Os dois estão em dia.** Não há alarme a construir aqui — e dizer isso ao
cliente é uma boa notícia, não um achado vazio.

---

## 5. O que ainda falta apurar

1. ~~**Responde da VPS?**~~ **RESPONDIDO em 03/09/2026, 11:53 UTC: não.** 403
   nos quatro endereços testados, corpo e tempo idênticos aos do CKAN, com o
   CHE respondendo 200 do mesmo IP no mesmo minuto. **A Scheduled Task não é
   criada.** As saídas, em ordem de custo:

   | Saída | Custo | Observação |
   |---|---|---|
   | **Ofício ao TCE** (`OFICIO-TCE-RS.md`) | zero, mas depende de terceiro | O dado é aberto e o pedido é legítimo. Único caminho que resolve em definitivo |
   | **Carga inicial de outro ponto** | uma execução manual | O coletor roda de qualquer máquina contra o banco do tenant. Enche a tela hoje; as atualizações seguintes continuam dependendo da liberação |
   | **Proxy de saída só para esta coleta** | mensalidade | Resolve sem depender de terceiro. Só compensa se o ofício for negado |

2. **Se a leitura sem token é intencional ou permissividade.** O manual trata de
   autorização no contexto de *envio*. Se um dia fechar, o caminho está mapeado:
   a credencial de produção é emitida **pela própria prefeitura**, no SISCAD →
   aba *Autorização de API*, pelo Responsável Operacional — não depende do
   Tribunal, e é o mesmo padrão do PCPRS.
3. **Cadência.** A página do LicitaCon diz que a relação/situação só é atualizada
   após a carga definitiva da remessa, **diariamente a partir das 21h**.
4. **As entidades além da prefeitura.** O de-para traz, por município, a Câmara
   (código próprio, não é o cliente) e as autarquias — Santa Maria tem IPLAN,
   IPASSP e um consórcio. Ficam **fora da coleta** por ora, e registradas no log
   de cada rodada: incluí-las multiplica o custo do job e a decisão é do dono,
   com o número na mão.

---

## 6. Relação com o que já existe no repo

`backend/ingestion/tce_rs.py` (CKAN, bloqueado) e
`backend/ingestion/tce_rs_portal.py` (portal, aberto) escrevem nas **mesmas
tabelas** — `tce_rs_licitacoes` e `tce_rs_contratos` —, porque a chave natural do
LicitaCon é a mesma pelos dois caminhos. Não duplicam: fazem UPSERT na mesma
linha, e cada um preenche o que o outro não tem (o CKAN, os valores da licitação;
o portal, tudo o mais).

`add_tce_rs_portal.sql` acrescenta as colunas do portal e três tabelas novas:
`tce_rs_remessas`, `tce_rs_obras` e `tce_rs_obras_recursos`.

O `municipios.tce_orgao_codigo` ganha fonte oficial: `licitacon_dominios.orgaos`
casa IBGE × código × CNPJ, o que é mais robusto que a descoberta por slug no
CKAN — e funciona com o CKAN fora do ar.
