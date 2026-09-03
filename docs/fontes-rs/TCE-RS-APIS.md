# TCE-RS: as APIs do `portal.tce.rs.gov.br`

> **Achado de 03/09/2026.** O que está bloqueado é o **`dados.tce.rs.gov.br`**
> (portal CKAN de dados abertos, 403 medido três vezes). O Tribunal publica
> APIs em **outro host** — `portal.tce.rs.gov.br` — e elas respondem **sem
> autenticação**. Medido do IP residencial; falta confirmar da VPS
> (`scripts/medir_tce_portal_vps.sh`).

---

## 1. O que isso muda

O ofício pedindo liberação de IP mirava o CKAN. Se o `portal.tce.rs.gov.br`
responder da VPS, **o caminho crítico deixa de ser o ofício**: dá para coletar
licitação, contrato, obra e — o que não existia em plano nenhum — a **remessa**,
sem depender de liberação.

O que se perde sem o CKAN é o **dump histórico completo em CSV** (864 licitações
e 1.201 contratos de Nova Palma, 2016–2026, com objeto e valores). O que se
ganha é mais recente e mais operacional.

**As duas fontes são complementares, não substitutas.** O ofício continua
valendo — muda de urgente para desejável.

---

## 2. As duas APIs

### 2.1 Queryon — `/api/qonws/q` (sem autenticação)

Contrato em `https://portal.tce.rs.gov.br/api/qonws/swagger` (Swagger 2.0, 53 KB).
`securityDefinitions` **vazio**. O `{syntax}` do caminho é o formato: use `json`.

| Endpoint | Parâmetros obrigatórios | O que traz |
|---|---|---|
| `licitacon_dominios.orgaos` | — | ⭐ **de-para oficial**: `CD_ORGAO` · `CNPJ` · `CD_MUNICIPIO_IBGE` · `TIPO` · `SITUACAO_ORGAO` |
| `licitacon.remessas` | `cd_orgao`, `ano_exercicio`, `periodo` | ⭐ **a remessa**: data de recebimento, situação, RVE, responsável e cargo |
| `licitacon.licitacoes` | `cd_orgao`, `tp_situacao`, `origem` | licitações do órgão com situação |
| `licitacon.contratos` | `cd_orgao`, `tp_situacao`, `origem` | contratos do órgão com situação |
| `licitacon.licitacao` | `cd_orgao`, `cd_tipo_modalidade`, `nr_licitacao`, `ano_licitacao` | uma licitação |
| `licitacon.contrato` | `cd_orgao`, `tp_instrumento`, `nr_contrato`, `ano_contrato` | um contrato |
| `licitacon.licitacoes_por_processo` | `cd_orgao`, `nr_processo` | licitações de um processo |
| `licitacon_obras.obras_por_orgao` | `cd_orgao` | obras do órgão |
| `licitacon.comissoes` | `cd_orgao` | comissões de licitação |
| `siapes.*`, `fnde.*` | vários | pessoal e despesa/receita FNDE |

Todos aceitam `fields`, `order`, `limit`, `offset`.

**⭐ `licitacon.remessas` é o achado mais valioso**, e não estava em nenhum plano.
Ele responde a pergunta que a tela `/dashboard/tce-rs` hoje diz **não** saber
responder: *o município entregou a remessa?* Medido para Nova Palma, exercício
2026, período 1:

```
CD_ORGAO 53100 · PM DE NOVA PALMA · TIPO_REMESSA "LicitaCon WEB"
DT_RECEBIMENTO 2026-02-09 05:14:58 · COD_BARRAS_RVE 012611038484707176
NOME_REPONSAVEL_ORGAO "JUCEMARA ROSSATO" · DS_CARGO_RESPONSAVEL "PREFEITA"
```

Atraso de remessa vira pendência no TCE, pendência vira irregularidade fiscal, e
irregularidade trava habilitação para convênio — a cadeia que a tela já explica,
e que passa a ser **verificável**.

### 2.2 LicitaCon Obras — `/api/obras` (leitura sem token; escrita autenticada)

Contrato em `/api/obras/v3/api-docs` (OpenAPI 3, 189 KB). Declara
`securitySchemes: bearer-key` e tem `POST /autenticacao` — mas **os GET
responderam 200 sem token**, incluindo dados de órgão específico.

Instituído pela **Resolução 1.176/2023** e regulamentado pela **IN 6/2023**;
obrigatório para órgãos municipais desde **08/01/2024**.

O que a API expõe por obra, além do cadastro: **medições** (com fotos e
documentos), **cronogramas**, **ordens de início, paralisação e reinício**,
**termos aditivos** (com prorrogação de prazo, reajuste, reequilíbrio e
renovação), **termos de recebimento**, **licenças**, **responsáveis técnicos**,
**registros de imóvel**, **rescisão contratual**, **coordenadas** e ⭐ **origem
do recurso** — que é o elo direto com o convênio que financiou a obra.

E expõe **`/alertas` por obra**: o próprio Tribunal aponta as pendências. Entre
elas, do histórico de versões: *"94 — Informar a origem do recurso"*, *"95 —
Informar as licenças"*, *"96 — Cadastrar as planilhas de medição"*.

**Medido:**

| Órgão | CNPJ | Obras |
|---|---|---|
| PM de Santa Maria | 88488366000100 | **120** (40 páginas) |
| PM de Nova Palma | 88488358000156 | 0 |
| IPLAN — Inst. de Planejamento de Santa Maria | 08537127000156 | 0 |

Zero em Nova Palma é resultado legítimo — o sistema é de 2024 e o município é
pequeno. **Não confundir com falha de coleta**; a mesma disciplina do SISMOB.

**Sobre a autorização** (manual §3.2): o ambiente de **produção** é autorizado
**pelo próprio órgão fiscalizado**, no SISCAD → aba *Autorização de API*, onde o
Responsável Operacional gera as credenciais. Ou seja, se um dia for preciso
token, **quem o emite é a prefeitura** — não depende do Tribunal, e é o mesmo
padrão do PCPRS. Homologação (`hml.tce.rs.gov.br`) pede credencial pela Central
de Serviços.

---

## 3. O que ainda falta apurar

1. **Responde da VPS?** É o que decide tudo. `scripts/medir_tce_portal_vps.sh`.
2. **Os valores de `tp_situacao` e `origem`** de `licitacon.licitacoes` e
   `licitacon.contratos` — ambos obrigatórios, e o Swagger não lista o domínio.
3. **Se a leitura sem token é intencional ou permissividade.** O manual trata de
   autorização no contexto de integração (envio). Se um dia fechar, o caminho já
   está mapeado: credencial emitida pela própria prefeitura via SISCAD.
4. **Cadência.** A página do LicitaCon diz que a relação/situação só é atualizada
   após a carga definitiva da remessa, **diariamente a partir das 21h**.

---

## 4. Relação com o que já existe no repo

`backend/ingestion/tce_rs.py` coleta do **CKAN bloqueado** e continua válido: o
dump histórico é mais completo. O que estas APIs permitem é um **segundo
coletor**, por outro caminho, que funciona hoje — e que traz remessa, obra e
medição, que o CSV não tem.

O `tce_orgao_codigo` de `municipios` ganha fonte oficial: `licitacon_dominios.orgaos`
casa `CD_MUNICIPIO_IBGE` com `CD_ORGAO` e `CNPJ`, o que é mais robusto que a
descoberta por slug do CKAN que `tce_rs.py` faz hoje — e funciona mesmo com o
CKAN bloqueado.
