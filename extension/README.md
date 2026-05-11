# PACTA Captura de Sessão — Extensão Chrome

Extensão Chrome que captura cookies de sessão (incluindo `httpOnly`) dos portais governamentais (gov.br, FNS, SIMEC, SISMOB, SUAS) e envia cifrado para a plataforma PACTA. Permite que os scrapers façam requisições HTTP autenticadas sem precisar burlar anti-bot (F5 Bot Defense).

## Instalação (modo desenvolvedor)

1. **Baixe esta pasta** `extension/` do repositório PACTA para seu computador.
   - Pode clonar o repo: `git clone https://github.com/MattMatiins/PACTA.git`
   - A pasta fica em `PACTA/extension/`
2. **Abra o Chrome** e vá em `chrome://extensions/`
3. Ative o **"Modo do desenvolvedor"** (toggle no canto superior direito)
4. Clique em **"Carregar sem compactação"**
5. Selecione a pasta `extension/` (a que tem o `manifest.json`)
6. Pronto! Ícone PACTA aparece na barra de extensões do Chrome

## Configuração inicial (1x apenas)

1. Faça login em https://pacta-production.up.railway.app
2. Abra o Console do navegador (F12 → Console)
3. Cole: `localStorage.getItem('pacta_token')` e copie o token (entre aspas)
4. Clique no ícone PACTA na barra → **"Configurar token PACTA"**
5. Cole o token → **Salvar**

## Uso (toda vez que precisar capturar)

1. Faça login no portal desejado (gov.br, consultafns.saude.gov.br, simec.mec.gov.br, etc)
2. Permaneça na aba do portal já logado
3. Clique no ícone PACTA na barra
4. Confirme **Sistema** e **Município ID** (auto-detectados pelo domínio)
5. Clique em **"Capturar e enviar para PACTA"**
6. Pronto - cookies enviados cifrados para o Cofre

## Como funciona tecnicamente

- A permissão `cookies` da extensão acessa `chrome.cookies.getAll()` que retorna **TODOS** os cookies do domínio, incluindo os marcados como `httpOnly` (que JavaScript regular não consegue ler)
- Cookies são empacotados em JSON estruturado (com `name`, `value`, `domain`, `httpOnly`, `expirationDate`, etc)
- Enviado via HTTPS com seu JWT PACTA para `/api/session-capture`
- Backend cifra com AES-256-GCM e salva no Cofre
- Scrapers usam esses cookies em `Cookie:` header para fazer requests HTTP autenticados

## Segurança

- Token PACTA fica em `chrome.storage.local` (criptografado pelo Chrome em disco)
- Cookies trafegam via HTTPS direto entre seu Chrome e o backend PACTA
- Backend cifra antes de gravar no banco (AES-256-GCM, chave separada)
- Nenhum servidor intermediário vê seus cookies
- Você pode revogar a qualquer momento: faça logout no portal de origem

## Privacidade

A extensão NÃO:
- Envia cookies sem você clicar no botão
- Acessa cookies de outros domínios além do que você está vendo
- Coleta histórico de navegação
- Faz requisições em background

A extensão SÓ pega os cookies do domínio atual, e SÓ quando você clica em "Capturar".
