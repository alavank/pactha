# Modelo de Segurança de Credenciais — PACTHA

> Infra: **Coolify na AWS Lightsail `54.232.208.118`**. A `COFRE_KEY` mora **nas env vars do
> resource no Coolify**, uma por tenant (os seis estão em [`../INFRA.md`](../INFRA.md)).

## Princípio: Zero-Trust Credentials

Nenhum operador humano (você, Claude, devs, GitHub admins, quem tem acesso ao painel do Coolify) consegue ler em texto puro as senhas dos portais governamentais (FNS, SIMEC, SISMOB, SUAS) **após o cadastro inicial**.

## Como funciona

```
┌─────────────────────────────────────────────────────────────┐
│  1. CLIENTE/OPERADOR cadastra senha via UI Cofre            │
│     ↓                                                        │
│     Backend criptografa AES-256-GCM com COFRE_KEY           │
│     COFRE_KEY mora APENAS nas env vars do Coolify           │
│     (por tenant, cifradas no banco do Coolify)              │
│     Banco guarda blob cifrado (v1:base64...)                 │
│                                                              │
│  2. ADMIN cria Service Token via /api/admin/service-tokens  │
│     name: "fns_scraper"                                      │
│     scopes: ["secret:read:fns"]                              │
│     → Token raw mostrado UMA VEZ (pactha_st_xxxxx)          │
│     → Banco guarda apenas SHA-256 hash                       │
│                                                              │
│  3. WORKER (resource <tenant>-worker no Coolify) recebe:    │
│     - PACTHA_API_URL                                         │
│     - PACTHA_SERVICE_TOKEN (env var do Coolify)             │
│     ZERO credenciais governamentais no env do worker        │
│                                                              │
│  4. Worker executa scraper:                                 │
│     a) GET /api/internal/secrets/fns + X-Service-Token     │
│     b) Backend valida token, descriptografa e retorna       │
│     c) Credencial vive APENAS em RAM do worker              │
│     d) Login no portal → coleta dados → upsert via API      │
│     e) Worker termina → memória zerada                      │
│                                                              │
│  5. AUDITORIA: cada acesso registra audit_log:              │
│     - service_token usado, IP, timestamp                    │
│     - quantos secrets foram lidos                           │
│     - municipio, sistema                                     │
└─────────────────────────────────────────────────────────────┘
```

## O que cada ator vê

| Ator | Vê senha em claro? |
|------|-------------------|
| Cliente/operador (na UI) | Apenas no momento do cadastro |
| Admin que vê o Cofre na UI | **Não** — vê apenas máscara `s****a` (precisa botão "revelar" + role admin/gestor + auditoria) |
| Você (via dashboard) | Idem acima |
| Claude/dev olhando código | **Não** — código não tem credencial |
| GitHub (commits, secrets) | **Não** — credencial nunca vai pro git |
| Quem administra o servidor / SRE | **Não** — vive cifrada no DB e em RAM efêmera |
| Quem tem `psql` no Postgres | **Não** — vê o blob cifrado (v1:...) sem a chave |
| Atacante com acesso ao DB | **Não** — sem `COFRE_KEY` o blob é inútil |
| Atacante com `COFRE_KEY` mas sem DB | **Não** — sem dados |
| Atacante com Service Token | **Sim** — apenas para o scope desse token (`secret:read:fns`); revogável imediatamente |
| Worker do scraper em runtime | **Sim** — em RAM, durante segundos, depois GC |

## Operação

⚠️ **Tudo abaixo é POR TENANT.** Cada um dos seis clientes (lista em `INFRA.md`) tem sua própria
API, seu próprio banco, sua própria `COFRE_KEY` e seus próprios Service Tokens. Um token de um
tenant não vale no outro. Substitua `$API` pela API do tenant certo:

```bash
API=https://pactha-api-54-232-208-118.sslip.io                 # freitas
# API=https://pactha-trust-api-54-232-208-118.sslip.io         # trust
# API=https://pactha-montesiao-mg-api-54-232-208-118.sslip.io  # montesiao-mg
```

### 1) Cadastrar credencial FNS pela primeira vez

1. UI → Cofre → Adicionar
2. Preencha sistema, usuário, senha
3. **Marque "Automação: FNS - Saúde"** ← campo crítico
4. Salvar

### 2) Criar Service Token para o scraper FNS (admin only)

```bash
# Via API (uma única vez)
curl -X POST "$API/api/admin/service-tokens" \
  -H "Authorization: Bearer <seu_jwt_admin>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "fns_scraper",
    "scopes": ["secret:read:fns"],
    "description": "Scraper FNS - worker do tenant",
    "expires_at": "2027-01-01T00:00:00Z"
  }'

# Response (UMA VEZ APENAS):
# {"id": 1, "name": "fns_scraper", "token": "pactha_st_xxxxxxxxxxxxx", "warning": "Anote agora..."}
```

### 3) Configurar o worker do tenant (Coolify)

Painel do Coolify (`http://54.232.208.118:8000`) → projeto `pactha` → resource
`<tenant>-worker` → **Environment Variables**:

```
PACTHA_API_URL=http://<uuid_da_api_do_tenant>:8000/api    # host interno da rede Docker
PACTHA_SERVICE_TOKEN=pactha_st_xxxxxxxxxxxxx
```

Ou via API do Coolify:

```bash
curl -X PATCH "http://54.232.208.118:8000/api/v1/applications/<worker_uuid>/envs/bulk" \
  -H "Authorization: Bearer <token_coolify>" -H "Content-Type: application/json" \
  -d '{"data":[{"key":"PACTHA_SERVICE_TOKEN","value":"pactha_st_xxx","is_build_time":false,"is_preview":false}]}'
```

Depois, redeploy do worker. **Nada mais.** Sem CPF, sem senha, sem nada.

### 4) Rotacionar token (recomendado a cada 90 dias)

```bash
curl -X POST "$API/api/admin/service-tokens/1/rotate" \
  -H "Authorization: Bearer <jwt_admin>"
# → retorna novo token
# → atualizar PACTHA_SERVICE_TOKEN no resource worker do Coolify + redeploy
# → token antigo revogado automaticamente
```

### 5) Revogar imediatamente (se suspeitar de comprometimento)

```bash
curl -X POST "$API/api/admin/service-tokens/1/revoke"
# Worker para de funcionar em segundos. Sem dano colateral.
```

## Comparação com alternativas

| Método | Senha guardada onde | Quem vê | Rotação | Auditoria |
|--------|--------------------|--------|---------|-----------|
| **PACTHA Cofre + Service Token** ✅ | DB cifrado AES-GCM | Ninguém após cadastro | API rotate, instantâneo | Por chamada, por token |
| GitHub Secrets | env GitHub Actions | Admins do repo | Manual | Apenas eventos do repo |
| Env vars do Coolify (cru) | Painel Coolify | Quem tem acesso ao painel | Manual | Limitada |
| HashiCorp Vault | Vault server | Operadores Vault | Política | Completa |
| AWS Secrets Manager | AWS | IAM roles | Auto via lambda | CloudTrail |
| .env local | Disco | Quem acessa máquina | Manual | Nenhuma |

PACTHA Cofre + Service Token = **equivalente a HashiCorp Vault** para nosso escopo, sem custo adicional.

## Hardening adicional aplicado

- `senha_encrypted` é AES-256-GCM (autenticada, não falsificável)
- `COFRE_KEY` apenas nas env vars do Coolify, **uma por tenant** (não em arquivo, não em git,
  não em DB). Se ela mudar, `decrypt()` devolve `""` **silenciosamente** e o Cofre daquele
  cliente vira lixo — nunca cruze chaves entre tenants.
- Service Token guardado como SHA-256 (irreversível)
- Token só mostrado uma vez na criação
- Tabela `audit_log` registra: cada `cofre.reveal`, `secret.read`, `service_token.create/rotate/revoke`
- Endpoint `/api/internal/*` recusa JWT de usuário (apenas Service Token)
- CSRF aplicado em mutating methods de usuário
- Rate limit no `/login` (5/min por IP+email)
- HSTS, CSP, X-Frame-Options ativos em produção
