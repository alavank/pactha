# PACTHA Captura Automática — Extensão Chrome

Extensão Chrome v2 que **captura sozinha** os cookies dos portais gov.br /
TransfereGov / FNS / SIMEC (incluindo `httpOnly`) e envia ao PACTHA toda vez
que você navega ou as cookies mudam. Mantém a sessão viva no servidor via
keep-alive a cada 12min enquanto o Chrome estiver aberto.

## Por que essa extensão existe

O bookmarklet antigo dependia de clique manual e só capturava cookies
acessíveis pelo `document.cookie` — ou seja, **deixava de fora todos os
`httpOnly`** (geralmente o JSESSIONID JEE do SICONV legado e tokens SSO mais
sensíveis). A extensão usa a permissão `chrome.cookies` que tem acesso
completo, incluindo httpOnly.

Além disso, mantém a sessão viva pingando o servidor a cada 12min — a sessão
JEE típica expira em 20-30min de inatividade, então sem keep-alive ela
morria entre logins.

## Instalação (1x, em <2 min)

1. **Clone ou baixe** este repositório:
   ```
   git clone https://github.com/alavank/pactha.git
   ```
   A pasta da extensão fica em `pactha/extension/`.

2. Abra o Chrome em `chrome://extensions/`

3. Ative **"Modo do desenvolvedor"** (canto superior direito)

4. Clique em **"Carregar sem compactação"** e selecione a pasta
   `pactha/extension/`

5. O ícone PACTHA aparece na barra. Fixe-o (📌) pra ficar sempre visível.

## Configuração inicial (1x, em 30s)

**IMPORTANTE — use o TOKEN LONGEVO (service token), não o JWT da web.**
O JWT da web app expira em 60 minutos; se você usar ele, a auto-captura
para de funcionar silenciosamente após 1h (era a causa da "sessão que
morria sozinha"). O **service token** (prefixo `pactha_`) nunca expira.

1. Peça/gere o **service token de captura** (scope `session:write`,
   prefixo `pactha_st_...`) — fornecido pelo admin do PACTHA.
2. Clica no ícone da extensão → **"Configurar token PACTHA"**.
3. Cola o service token → **Salvar configuração**.

A extensão detecta automaticamente: token que começa com `pactha_` é
enviado como `X-Service-Token` (longevo); qualquer outro vai como
`Authorization: Bearer` (JWT, compat legado de 60min).

Pronto. A partir de agora, **não precisa mais clicar em nada**.

## Como funciona o modo automático

A extensão tem 3 mecanismos rodando em paralelo:

### 1. Auto-captura em cada navegação
Quando você abre qualquer URL em `*.transferegov.sistema.gov.br`,
`*.acesso.gov.br`, `gov.br/transferegov` ou portais de saúde monitorados:
- Espera 1.5s pra cookies da resposta settlearem
- Lê TODOS os cookies dos domínios relevantes (incluindo subdomínios irmãos
  do transferegov que compartilham SSO)
- POSTa pro `/api/session-capture` automaticamente

### 2. Cookie listener
Sempre que um cookie crítico (`JSESSIONID`, `user-id`, `Session_Gov_Br_Prod`,
`Govbrid`, `XSRF-TOKEN`) é criado ou renovado em domínio alvo:
- Aguarda 2.5s pro conjunto inteiro chegar
- Captura e envia

Isso significa: assim que você termina de logar no gov.br, a extensão envia
a sessão sozinha — sem você precisar abrir o popup ou clicar em nada.

### 3. Keep-alive (Chrome alarms)
A cada 12 minutos:
- Faz um `GET` em `https://discricionarias.transferegov.sistema.gov.br/voluntarias/`
  e outras URLs alvo
- Mantém a sessão JEE viva no servidor (que expiraria em 20-30min de
  inatividade)
- Após cada ping bem-sucedido, re-captura cookies (servidor pode rotacionar
  o JSESSIONID)

**Resultado**: você loga no gov.br/TransfereGov uma vez por dia (ou quando
o SSO expirar de verdade — pode durar horas), deixa o Chrome aberto, e o
PACTHA sempre tem cookies frescos pra rodar scrapers enriquecidos.

## Debounce e privacidade

- **Debounce**: captura do mesmo domínio só repete depois de 30s, pra evitar
  spam quando você navega rápido entre páginas.
- **Domínios**: só captura nos hosts listados no `manifest.json` host_permissions
  (transferegov, gov.br/acesso, saúde, MEC). Não toca outros sites.
- **Modo automático pode ser desligado** no popup (toggle "Modo automático")
  — quando off, só responde ao botão "Capturar agora (manual)".

## O popup mostra status

Abrindo o ícone PACTHA você vê:
- ✅ **Modo automático ativo** (verde) ou ⚠️ desligado (âmbar)
- Domínio atual da aba
- **Última captura**: `✓ discricionarias.transferegov.sistema.gov.br · 13
  cookies (6 httpOnly) · 1min atrás · scraper disparado`
- Botão de captura manual (override)

## Segurança

- Token PACTHA fica em `chrome.storage.local` (criptografado pelo Chrome em
  disco do seu PC, isolado da WebApp)
- Cookies trafegam HTTPS direto entre seu Chrome e o backend PACTHA
- Backend cifra com AES-256-GCM antes de gravar no Cofre (chave separada)
- Nenhum servidor intermediário vê seus cookies
- Para parar: desinstale a extensão OU desligue o toggle automático no popup
