# Abrir um cliente novo

> **Leia isto ANTES de replicar qualquer instância.** Se você é um agente e o
> dono pediu "cria um cliente novo" / "replica a instância para X", **pare e faça
> as perguntas da seção 1 antes de tocar em qualquer coisa.** Não deduza o tipo
> de cliente nem o código IBGE.

**Monte Sião é a base de DESENHO, não de DADOS.** Dela vêm estrutura, regras,
identidade visual e comportamento. **Nenhum dado de Monte Sião — nem de qualquer
outro cliente — vai para o tenant novo. Zero.** Cada cliente tem banco próprio, e
o que popula esse banco é a coleta pública daquele município, feita do zero.

---

## 1. As perguntas (faça TODAS antes de começar)

**a) Quem é o cliente e de que tipo?**

| Tipo | O que muda |
|---|---|
| **Cidade** | Um município. O escopo do BI é único. |
| **Assessoria** | Vários municípios, e o BI consolida. É o modo "rollup" das abas. |
| **Consórcio** | Vários municípios, mesma mecânica da assessoria. |

**b) Se for cidade:** nome, UF e **código IBGE de 7 dígitos**.

> ⚠️ O IBGE é a chave de tudo — CAUC, FNS, SISMOB, TransfereGov. Errado, o sistema
> não dá erro: devolve "nenhum resultado" e parece que o município não tem nada.
> Uma fonte conhecida cobra 6 dígitos em vez de 7 (o SISMOB) — quem trata disso é
> o coletor, não esta configuração.
>
> **NUNCA escreva um código IBGE de cabeça. Busque na API oficial:**
> `https://servicodados.ibge.gov.br/api/v1/localidades/municipios/<codigo>`
> — e confira que o `nome` e a UF que voltam são os do cliente.
>
> Isto já custou caro duas vezes. Um seed antigo gravou Araújos com `3104502`,
> que é **Arinos** — outro município. E Monte Sião foi cadastrado uma vez como
> `3143302` quando o correto é `3143401`. Nos dois casos o sistema subiu, coletou
> e não reclamou de nada: só devolvia vazio.

**c) Se for assessoria ou consórcio:** a lista completa de municípios, cada um com
nome, UF e IBGE. E qual é o município "sede", se houver.

> ⚠️ **Município do RS precisa do COREDE no cadastro** (`municipios.corede`, gravado por
> `POST /api/control/municipios`), senão a Consulta Popular pula o município e a rodada
> sai `partial` com "sem COREDE". Não se adivinha pela geografia: confira na planilha
> "municipios x demandas eleitas" do COREDE em `consultapopular.rs.gov.br` — o nome do
> município tem de aparecer nela. Em 13/09/2026 o BGK nasceu com os 10 sem COREDE
> (Giruá é **Missões**, Portão é **Vale do Rio dos Sinos**, os outros oito são **Serra**).

**d) Que credenciais já existem?** Pergunte uma a uma; o que não houver entra
depois, sem travar a abertura:

- gov.br / TransfereGov (não é credencial: a captura é pela extensão do Chrome,
  ver seção 5 e o passo 10)
- SIGCON-MG (usuário e senha) — só faz sentido em cliente de MG
- CAGEC — portal próprio, **não fica dentro do SIGCON**
- Chave da Anthropic, se a IA vai ficar ligada nesse cliente

**e) Qual o domínio?** Subdomínio próprio ou o `sslip.io` da máquina, no começo.

---

## 2. O que o tenant novo ganha sozinho

Só isto — e é de propósito:

- **As contas de dono da plataforma**, exatamente a lista de
  `services/auth.py::SUPER_ADMIN_EMAILS` (não repetida aqui de propósito: e-mail é dado
  pessoal, e uma segunda cópia diverge). Senhas **aleatórias, impressas no log do primeiro
  boot**, com troca obrigatória no primeiro acesso.
- **O município informado nas variáveis de ambiente** — um registro, o dele.

Quem trabalha no cliente é cadastrado depois, na tela de Usuários, por quem
entrar. Nenhuma conta de outro cliente, nenhum município de outro cliente.

> O seed só roda quando a tabela `users` está **vazia**. Num tenant que já existe
> ele não faz nada, então subir versão nova nunca ressuscita conta apagada.

---

## 3. Variáveis de ambiente

Obrigatórias para o cliente existir:

```
MUNICIPIO_NOME=Nova Serrana
MUNICIPIO_IBGE=3145208
MUNICIPIO_UF=MG
```

Sem as três, o sistema **sobe mas não coleta nada** — e o log do boot diz
exatamente isso. É o comportamento desejado: preferimos base vazia e visível a
base com o município errado, que passa semanas sem ninguém notar.

Do resto da configuração, o que é por tenant:

```
DATABASE_URL=            # banco PRÓPRIO do cliente
JWT_SECRET=              # gere um novo; não reaproveite de outro cliente
COFRE_KEY=               # AES-256 do cofre de senhas; novo por cliente
INSTANCE_SLUG=nova-serrana-mg
FRONTEND_URL=
BI_MODULE=1              # o Painel de Indicadores
ADMIN_PASSWORD=          # opcional: fixa a senha do super-admin em vez de
                         # depender de alguém ler o log do primeiro boot
```

> **`ADMIN_PASSWORD` resolve um problema real.** Sem ela, a senha do
> `super-admin@alavank.com.br` só aparece no console do primeiro boot; se ninguém
> copiar naquele momento, a conta fica inacessível e a saída é resetar pelo banco.

---

## 4. Ordem de execução

### ⛔ Passo 0 — a imagem do frontend, ANTES de tudo

**Não existe imagem de frontend genérica, e clonar o app de outro cliente entrega
os dados daquele cliente.**

O `API_PROXY_TARGET` é **assado na imagem durante o build** (é um build ARG, não
uma variável de runtime). Um app apontado para `pactha-frontend-freitas` faz proxy
de `/api` para a **API da Freitas**: o deploy sobe, o login funciona, e o cliente
novo enxerga os usuários, municípios e dados da Freitas — com o banco dele vazio
ao lado, sem um único erro na tela.

Então, antes de criar qualquer aplicação:

1. Abra `.github/workflows/build-frontend.yml` e **acrescente uma entrada na
   matriz** para o tenant, com o `API_PROXY_TARGET` apontando para a **API dele**,
   mais logo e subtítulo próprios.
2. Rode o workflow (`workflow_dispatch`) e confirme que a imagem
   `ghcr.io/alavank/pactha-frontend-<tenant>` foi publicada.
3. Só então crie o app apontando para **essa** imagem.

> **Nunca aponte o frontend de um cliente para a imagem de outro**, nem "só para
> testar". Não dá erro — dá vazamento.

> **O passo 0 NÃO exige merge na `main`.** O job `deploy` dos dois workflows tem
> `if: github.ref == 'refs/heads/main'`, e o `on:` tem `workflow_dispatch`. Então
> `gh workflow run build-frontend.yml --ref <sua-branch>` **publica a imagem e pula
> o deploy inteiro** — a imagem passa a existir sem tocar em produção. Anote o
> **sha COMPLETO** da branch: é a tag que o app novo vai usar.

### Depois disso

1. **Criar o environment do tenant** no projeto `pactha`
   (`POST /projects/ksmwr13y4iyprom8i1znede8/environments` com `{"name":"<slug>"}` → 201).
   ⚠️ A instância usa **um environment por cliente**; o `production` está vazio e
   não é onde os tenants moram.
2. Criar o banco do cliente (`<slug>-db`, `postgres:16-alpine`, db/user `pactha`).
   ⚠️ Gere a senha do Postgres **só com letras e dígitos**: ela vai crua dentro da
   `DATABASE_URL`, e `@ : / ? #` quebram a URL.
3. Criar as três aplicações no Coolify — api, worker e frontend —, todas com
   `instant_deploy:false`. **O frontend tem de apontar para a imagem do passo 0**,
   nunca para a herdada de outro cliente.
4. Definir as variáveis da seção 3. ⚠️ **`MUNICIPIO_NOME`/`MUNICIPIO_IBGE`/`MUNICIPIO_UF`
   vão no resource da API**, e são o que o seed lê no primeiro boot. Elas **não
   existem** nos três tenants antigos (o banco deles veio populado do Neon) —
   então clonar as env de um deles produz um tenant que sobe e não coleta nada.
5. Subir a **api** primeiro (ela roda as migrations e o seed no boot) e **ler o
   log** para copiar as senhas. Aceite: `Startup migrations: N/N executadas` — se
   vier `N-1/N`, leia qual falhou antes de seguir.
   > Suba o primeiro boot com **`AUTHZ_MODO=aviso`** e só depois troque para
   > `bloqueio` + redeploy. Custa um deploy e evita descobrir um backfill de
   > permissão quebrado com o tenant já trancado.
6. Subir **worker** e **frontend**. **Um app por vez, esperando cada um
   terminar** — não por CPU (a VPS tem 8 vCPU e 32 GB), e sim porque o Coolify
   roda com `concurrent_builds=1`: disparar tudo junto só faz fila, e fila longa
   já matou coleta em voo neste projeto.
7. Entrar como `super-admin@alavank.com.br`, trocar a senha, conferir que o
   município que aparece é o certo.
8. **Fechar o laço do CI** — e este passo já foi esquecido: acrescentar o uuid do
   frontend no `for APP in ...` do `build-frontend.yml` **e** o trio
   `nome:api_uuid:worker_uuid` em `TENANTS` no `build-backend.yml`. Sem isso o
   tenant novo **nunca mais recebe deploy**, e em silêncio: os merges seguintes
   simplesmente não o incluem. Ponha-o por último nas duas listas.
9. Criar as Scheduled Tasks do worker (horários em janelas que os outros tenants
   não usem) e a 4ª entrada no `case` de `scripts/separar_papel_banco.sh`.
10. **Colocar o tenant na extensão de captura** — `AMBIENTES_CONHECIDOS` em
    `extension/ambientes.js` — e emitir o service token dele
    (`POST /api/control/session/token`, scope `session:write`) para colar no
    popup da extensão. **Sem isto o tenant nunca recebe a sessão gov.br**, e o
    silêncio é total: o POST responde 200 para os outros ambientes, e o coletor
    gated registra `parcial` em vez de erro — o `bgk-rs` passou o primeiro dia
    inteiro assim, com 216 leituras atrás do login sem retorno.
    `backend/tests/test_extensao_conhece_os_tenants.py` reprova o PR que
    esquecer, cruzando esta lista com o `TENANTS` do passo 8.

> ⚠️ **Mergear não publica.** As aplicações usam `build_pack = dockerimage`: rodam
> a tag gravada em `docker_registry_image_tag`. O CI só publica no GHCR. Ver
> `INFRA.md`. E a tag da **api é o sha CURTO**, a do **frontend é o sha COMPLETO**.

---

## 5. Depois de abrir

- **Coleta pública** começa sozinha assim que existe município: CAUC, TransfereGov,
  FNS, SISMOB. Confira em **Status dos Dados** no dia seguinte.
- **gov.br** é captura de sessão pela **extensão do Chrome** (`extension/`), não
  é credencial guardada e não é mais o bookmarklet — este foi aposentado porque
  só enxergava `document.cookie` e deixava de fora todo cookie `httpOnly`,
  justamente onde mora o `JSESSIONID` do SICONV legado. A extensão manda a
  sessão para os seis ambientes de uma vez e faz keep-alive a cada 12 min.
  ⚠️ **Ela só funciona com um Chrome aberto**: a sessão JEE morre com 20–30 min
  de inatividade. Chrome fechado no fim do expediente = coleta gated parada no
  dia seguinte, em todos os tenants ao mesmo tempo.
- **SIGCON-MG e CAGEC** entram no Cofre quando o dono passar as credenciais — e
  **só fazem sentido em cliente de MG**. Num tenant de outro estado, não crie as
  Scheduled Tasks `sigcon`, `cagec` e `queue-sigcon`: os coletores se protegem
  sozinhos por UF, mas gastariam processo e encheriam o log de "sem credenciais".
  ⚠️ **Mas repare no efeito colateral**: `run_dadosabertos_cron.run_all()` — que
  roda CAUC, Acordo FES, SISMOB **e SIMEC-PAR** — é chamado de dentro do
  `run_sigcon_cron.py`. Sem a task `sigcon`, o **SIMEC-PAR fica órfão** (CAUC e
  SISMOB têm tasks próprias). Crie uma task `simec` para ele.
- **Cadastrar os setores** se o cliente for usar tramitação: a tabela nasce vazia.

---

## 6. O que NÃO copiar de outro cliente

Nunca, em nenhuma hipótese: registros de `municipios`, `users`, qualquer tabela de
dado coletado, `JWT_SECRET`, `COFRE_KEY`, tokens de serviço, links de TV.

O que se copia é **código e configuração de estrutura** — a imagem, as migrations,
o `BI_MODULE`, o desenho das telas.
