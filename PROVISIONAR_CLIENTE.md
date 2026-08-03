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
> **Confirme o código com o dono, dígito a dígito, antes de gravar.** Uma fonte
> conhecida cobra 6 dígitos em vez de 7 (o SISMOB) — quem trata disso é o
> coletor, não esta configuração.

**c) Se for assessoria ou consórcio:** a lista completa de municípios, cada um com
nome, UF e IBGE. E qual é o município "sede", se houver.

**d) Que credenciais já existem?** Pergunte uma a uma; o que não houver entra
depois, sem travar a abertura:

- gov.br / TransfereGov (a captura é por bookmarklet, ver seção 5)
- SIGCON-MG (usuário e senha) — só faz sentido em cliente de MG
- CAGEC — portal próprio, **não fica dentro do SIGCON**
- Chave da Anthropic, se a IA vai ficar ligada nesse cliente

**e) Qual o domínio?** Subdomínio próprio ou o `sslip.io` da máquina, no começo.

---

## 2. O que o tenant novo ganha sozinho

Só isto — e é de propósito:

- **Três contas**, as de `services/auth.py::SUPER_ADMIN_EMAILS`:
  `super-admin@pactha.com.br`, `alavank.tecnologia@gmail.com`,
  `matheus@alavank.com.br`. Senhas **aleatórias, impressas no log do primeiro
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
> `super-admin@pactha.com.br` só aparece no console do primeiro boot; se ninguém
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

### Depois disso

1. Criar o banco do cliente.
2. Criar as três aplicações no Coolify — api, worker e frontend. O engine em
   `C:\projetos\coolify-migrate` ajuda a criar a estrutura, mas **o frontend tem
   de apontar para a imagem do passo 0**, nunca para a herdada do app clonado.
3. Definir as variáveis da seção 3.
4. Subir a **api** primeiro (ela roda as migrations e o seed no boot) e **ler o
   log** para copiar as senhas.
5. Subir **worker** e **frontend**. **Um app por vez, esperando cada um
   terminar** — a VPS é burstable (~0,6 vCPU sustentado).
6. Entrar como `super-admin@pactha.com.br`, trocar a senha, conferir que o
   município que aparece é o certo.

> ⚠️ **Mergear não publica.** As aplicações usam `build_pack = dockerimage`: rodam
> a tag gravada em `docker_registry_image_tag`. O CI só publica no GHCR. Ver
> `INFRA.md`. E a tag da **api é o sha CURTO**, a do **frontend é o sha COMPLETO**.

---

## 5. Depois de abrir

- **Coleta pública** começa sozinha assim que existe município: CAUC, TransfereGov,
  FNS, SISMOB. Confira em **Status dos Dados** no dia seguinte.
- **gov.br** é captura de sessão pelo bookmarklet — a API dispara o scraper na
  hora, sozinha. Não é credencial guardada.
- **SIGCON-MG e CAGEC** entram no Cofre quando o dono passar as credenciais.
- **Cadastrar os setores** se o cliente for usar tramitação: a tabela nasce vazia.

---

## 6. O que NÃO copiar de outro cliente

Nunca, em nenhuma hipótese: registros de `municipios`, `users`, qualquer tabela de
dado coletado, `JWT_SECRET`, `COFRE_KEY`, tokens de serviço, links de TV.

O que se copia é **código e configuração de estrutura** — a imagem, as migrations,
o `BI_MODULE`, o desenho das telas.
