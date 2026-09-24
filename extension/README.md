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

### 0. Captura completa e o selo do ícone (2.4.0)

O TransfereGov tem **quatro portas com sessão própria** (login, mandatárias
`/private/`, execução, prestação). Logar só na primeira deixa as outras três fora
do que o servidor recebe. O botão **"Captura completa (abre as 4 portas)"** do
popup abre as quatro na mesma aba, uma depois da outra; se cair na tela do
gov.br, ele **para e espera você logar** (não automatiza login) e segue sozinho
depois. No fim faz uma captura com tudo.

O ícone ganha um **"!" vermelho** quando algum servidor PACTHA **mediu** que o
login caiu (`GET /api/session-capture/saude`, a cada 12 min e ao abrir o popup).
"Capturei" não é "está vivo no servidor" — o popup mostra uma linha por ambiente.

⚠️ **Não clique em "Sair"** no TransfereGov nem no gov.br fora da hora de renovar:
é a mesma sessão que os servidores usam.

**⏰ Vencimento (2.4.1):** a sessão do gov.br dura ~24h a partir do login (padrão
medido em 22–23/09/2026; o gov.br não publica o prazo). Quando faltam ~3h, o
servidor avisa no Telegram e o ícone ganha um **⏰** laranja; o popup mostra
"login há Nh · vence ~HH:MM" (a hora vem do servidor). Aí, **nesta ordem**:
1. **Sair** no TransfereGov — só um login novo renova o prazo (na hora do aviso o
   portal ainda abre logado, então sem o Sair a "Captura completa" só recaptura a
   sessão velha e nada muda).
2. **"Captura completa (abre as 4 portas)"** — ela para na tela de login, espera
   você logar e passa pelas 4 portas sozinha, mandando o jar novo. O prazo de 20
   min do roteiro recomeça a cada carregamento da tela de login.
3. Se o gov.br entrar **sem pedir senha**, a sessão dele continuou (o Sair do
   TransfereGov nem sempre encerra a do gov.br — não medido): saia também em
   `sso.acesso.gov.br` e repita. O servidor só reinicia o relógio quando o cookie de
   sessão do gov.br (`Session_Gov_Br_Prod`) muda.

O Sair derruba a sessão dos servidores na hora; ela volta quando o keepalive
promover a captura nova (candidata → promovida, até ~10 min). O ⏰ só apaga
depois disso e da próxima consulta da extensão (até 12 min) — recapturar a
mesma sessão sem o Sair **não** apaga o aviso, de propósito.

**O porteiro (2.4.0):** toda captura `govbr` — navegação, cookie trocado, alarme
e o botão manual — passa por `chromeEstadoLogin()` (`ambientes.js`), que sonda a
porta 1 e olha o **corpo** da resposta. Deslogado, o TransfereGov pode responder
HTTP 200 *na mesma URL* com o formulário SAML de auto-envio; olhar só a URL dizia
"logado". Chrome deslogado ⇒ nada é enviado. Se a sonda não souber dizer (rede,
layout novo), a captura **segue**: o servidor tem a guarda dele, e travar por
dúvida impediria a recaptura.

**Acesso Livre — visitante (2.4.5):** no modo visitante do TransfereGov a porta 1
**não pede login** (responde 200 com a página "… - Acesso Livre"; fatos medidos no
`CONTINUAR.md`, seção "A sessão gov.br parava de ser derrubada por NÓS", parágrafo
"Medido em 24/09/2026"). Visitante não conecta os servidores, e o porteiro
(`chromeEstadoLogin`) o distingue de *deslogado* por UM marcador preciso: o
`<span class="exit">` "Sair do Acesso Livre". O título "… - Acesso Livre" só dispara
a pergunta — não decide, porque a página LOGADA não foi medida e o servidor já viu
"Acesso Livre" no cabeçalho de sessão logada. A frase solta no HTML (script,
comentário, texto oculto) também não conta: página logada tomada por visitante
barraria a captura boa para sempre.
- **Captura completa:** porta assentada com o título da aba no Acesso Livre E a sonda
  da porta 1 achando o span de visitante → a extensão **apaga só o `JSESSIONID` do
  discricionarias** (a sessão de visitante) e reabre a porta 1, que cai na tela de
  login COM contexto (medido em 24/09/2026 num navegador isolado). Título de visitante
  com a sonda dizendo deslogado ou sem resposta: espera o próximo sinal (é a página
  deixada, ainda na aba). **Na tela de login, clique em «Entrar com gov.br» — nunca
  em «Acesso livre»**: esse link leva a `www.gov.br/transferegov/…/acesso-livre`, e o
  roteiro volta à porta 1 contando uma saída. Mais de 3 saídas encerram o roteiro com
  esse motivo no popup.
- ⛔ **Nunca o "Sair do Acesso Livre" da página** (`/voluntarias?LLO=true`): ele roda
  o logout de mandatárias, acompanhamento, habilitação **e do gov.br**
  (`sso.acesso.gov.br/logout`) — derruba a sessão que os servidores usam quando ela é
  a mesma deste Chrome. Nenhum caminho da extensão navega para lá, e a faixa manda
  evitá-lo.
- O prazo de 20 min do roteiro conta do último CARREGAMENTO de página; o alarme de 30s
  só reconfere (antes ele renovava o prazo, e só o teto de 60 min valia).
- O popup só troca a recusa do roteiro por "Captura enviada" com uma captura do
  TransfereGov (`automation_key` `govbr`) cuja sonda disse **logado** — a do FNS/SIMEC
  (keepalive de 12 min) também chega aos servidores e não prova nada da sessão gov.br.
- **Modo automático:** não navega nada; acende o **"!"** e o popup avisa
  (`pactha_visitante`: some em 6h sem visitante novo, ou com a sonda do TransfereGov
  dizendo logado ou deslogado — captura de outro sistema não apaga).
- **Faixa na página** (`aviso_pagina.js`, content script): no Acesso Livre (pelo
  mesmo span "Sair do Acesso Livre"; com o roteiro em curso ela diz "aguarde, a
  Captura completa está saindo dele") e, com o roteiro em curso, na tela de login do
  TransfereGov. Fechável; não clica, não preenche e não envia nada.
- Ambiente com **HTTP 401** no popup: mostra o motivo do servidor ("Token inválido ou
  revogado", "Service token expirado") e a ação — gerar outro token em
  Configurações › Service Tokens no PACTHA daquele cliente e colar em «Configurar
  token PACTHA».

### 1. Auto-captura em cada navegação
Quando você abre qualquer URL em `*.transferegov.sistema.gov.br` ou nos portais
de saúde monitorados (⚠️ `www.gov.br` e a tela de login `sso.acesso.gov.br`
**não disparam mais** captura desde a 2.4.0 — navegar neles deslogado mandava um
jar sem login por cima da sessão viva dos servidores; os cookies deles continuam
entrando no jar):
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
  o JSESSIONID) — **só com o Chrome logado** (o porteiro acima): deslogado, o
  portal devolve HTTP 200 do mesmo jeito, e tratar isso como "sessão viva"
  mandava o jar deslogado aos servidores de 12 em 12 minutos

E o servidor se defende sozinho, com qualquer versão da extensão: se a sessão
dele está **viva**, a captura que chega fica como *candidata* e só é promovida
se autenticar; sessão **morta** aceita a recaptura na hora.

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
  cookies (6 httpOnly) · 6 de 6 ambiente(s) · 1min atrás`
- Botão de captura manual (override)

## Segurança

- Token PACTHA fica em `chrome.storage.local` (criptografado pelo Chrome em
  disco do seu PC, isolado da WebApp)
- Cookies trafegam HTTPS direto entre seu Chrome e o backend PACTHA
- Backend cifra com AES-256-GCM antes de gravar no Cofre (chave separada)
- Nenhum servidor intermediário vê seus cookies
- Para parar: desinstale a extensão OU desligue o toggle automático no popup
