# CONTINUAR.md — Handoff PACTHA (leia isto primeiro)

> Documento de contexto para a **próxima sessão de IA** (Claude Code) que for continuar este projeto.
> É **auto-contido**: assuma que você (IA) não tem memória das sessões anteriores. Tudo que precisa está aqui.
> Última atualização: 2026-09-07.
>
> 📍 Para servidor, URLs, uuids, bancos e operações no Coolify, a fonte de verdade é o
> **[`INFRA.md`](INFRA.md)** na raiz. Este arquivo cobre o *projeto*; o `INFRA.md` cobre a *infra*.

---

## 1. O QUE É ISTO (em 30 segundos)

**PACTHA** = sistema de **monitoramento de convênios e transferências governamentais** para municípios e assessorias (MG/ES/GO/RS). Módulos: SIGCON-MG (convênios estaduais), TransfereGov, Emendas, Parlamentares, CAUC, Acordo FES, FNS, SIMEC/PAR, **Obras** (SISMOB + Obras.gov.br/CIPI), IA (Claude), DOU-MG, Relatório de Monitoramento (RM), Documentos, Cofre de Senhas (AES-256), Telegram, extensão Chrome de captura gov.br, Painel de Indicadores (BI, nos 5 tenants) com Modo Tela/links públicos, selos de frescor por tela e watchdog de coleta. São **22 fontes oficiais** (o `CLAUDE.md` mantém a contagem em dia).

- **Frontend:** Next.js 16 (App Router) + Tailwind v4 + daisyUI + shadcn. Pasta `frontend/`.
- **Painel (pasta `painel/`):** DEPRECADO — o BI virou módulo do frontend principal (`/dashboard` + `/tela`). Ver `painel/DEPRECADO.md`.
- **Backend:** Python 3.12 FastAPI (uvicorn). Pasta `backend/`. Tudo prefixado `/api`.
- **Banco:** PostgreSQL 16 puro (SQLAlchemy async+asyncpg na API; psycopg2 nos scrapers/migrations).
- **Scraping:** httpx + Playwright (Chromium) + curl_cffi. Pasta `backend/ingestion/`.

**Este repo (`alavank/pactha`) é um FORK PRÓPRIO** do repo original `MattMatiins/PACTA` (do Matheus). O usuário (alavank) **migrou** a stack para **Coolify + Postgres puro** e renomeou tudo de "PACTA" → "PACTHA". Railway, Neon e Vercel (do repo original) **não são mais usados**; a hospedagem posterior na Hetzner também já foi desativada — hoje é **AWS Lightsail**.

⚠️ **DOIS clones no PC — não confundir:**
- `C:\dev\pactha` → **ESTE** repo (`alavank/pactha`). É onde você trabalha.
- `C:\projetos\PACTA` → clone do repo do Matheus (`MattMatiins/PACTA`), usado só para colaboração com ele. **NUNCA** pushe cruzado entre os dois.

⚠️ **Este repo tem RULESET no GitHub exigindo PR aprovado.** Não tente pushar direto na `main` — crie branch e abra PR.

---

## 1.4. ⚠️ PERMISSÃO POR TELA — resolvido, e o que sobrou de aviso (06/09/2026)

> **A migration foi corrigida e rodou nos cinco tenants** (`110/110`, conferido no log de
> cada API em 06/09). A causa foi uma coluna com o nome errado — `pc.permissao` onde
> `permissoes_catalogo` chama de `chave` —, e as redes de compatibilidade **já saíram**.
> O relato abaixo fica porque as lições são o que importa.
>
> ✅ **`AUTHZ_MODO=bloqueio` NOS CINCO** desde 06/09/2026 01:38, conferido no log de cada
> API. Decisão do dono: *"tem q ser bloqueio em tudo... se tá marcado q ela não vai ter
> acesso, isso muda já"*. A regra de permissão é a mesma para todo cliente; o que varia
> entre eles é só QUAIS TELAS existem, e disso quem cuida é a carteira de municípios.
>
> ⚠️ **ONDE A CONFIGURAÇÃO MORA, e a armadilha de lê-la errado:** `AUTHZ_MODO` é setada
> explicitamente por tenant no Coolify, e **cada aplicação tem DUAS entradas** — uma de
> produção (`is_preview: false`) e uma de preview. Ler a lista sem filtrar por `is_preview`
> devolve a de preview e faz concluir o oposto: foi assim que uma sessão reportou Santa
> Maria como "sem trava" quando a produção dela sempre esteve em `bloqueio`. Só o
> **novapalma** estava de fato em `aviso`, e foi ligado.
>
> ⚠️ Se um cliente for barrado indevidamente, o recuo é `AUTHZ_MODO=aviso` no Coolify +
> restart — sem deploy. E o número a olhar antes é o aviso «N contas ativas sem nenhuma ação
> marcada» em Configurações › Usuários: é exatamente quem para de funcionar.

### O relato (05/09/2026)

O incremento **«Permissão por tela»** (PRs #384–#386) foi deployado nos cinco tenants. O
código está certo e verificado; **uma migration não rodou**, e isso ainda está aberto.

**O que mudou.** A permissão passou a ter três níveis — **Módulo › Tela › Ação** —, os grupos
FEDERAIS e ESTADUAIS viraram 18 telas com chave própria, as abas de Configurações viraram
telas, e o cadastro de usuário virou **um modal só** que grava tudo num commit. Saíram os
modelos de permissão, o rótulo «Prefeito» e a trava de conta «Somente leitura». O
`AUTHZ_MODO` passou a ser **`bloqueio`** por default. Regra inteira em
[`docs/PERMISSOES_POR_TELA.md`](docs/PERMISSOES_POR_TELA.md).

**O que está quebrado.** `migrations/add_permissoes_por_tela.sql` **executou e falhou** no
deploy — e `services/startup.py` engole o erro numa linha de log sem abortar o boot, então a
API subiu saudável e ninguém foi avisado. Medido no freitas pela API em 05/09:

- ninguém tem as 18 chaves novas (só quem foi cadastrado DEPOIS, pelo modal novo);
- ninguém tem as telas `usuarios`, `frescor`, `parametros`.

**Consequência que já mordeu:** como aquelas três viraram telas, todo `role='admin'`
não-super ficou com a aba Usuários **visível** e a tela devolvendo **403** — a única tela que
conserta permissão era a que ninguém abria. O PR #386 remendou isso no **código**
(`services/auth.py::TELAS_DE_ADMINISTRACAO` e `TELAS_RENOMEADAS`,
`services/permissoes.py::_CHAVES_RENOMEADAS`): quem tem a chave antiga alcança as novas,
tenha a migration rodado ou não.

**O que falta fazer, em ordem:**
1. Pegar a linha do log — Coolify → `<tenant>-api` → Logs → `add_permissoes_por_tela` — e
   descobrir **por que** falhou. Sem isso só há remendo.
2. Corrigir a migration e confirmar nos **cinco** bancos.
3. **Remover as redes de compatibilidade** — elas são ponte, não desenho, e enquanto
   existirem a tela mostra desmarcado o que a pessoa na prática tem.
   `tests/test_compat_telas_renomeadas.py` guarda as propriedades delas.

⚠️ **A lição, que vale para toda migration:** nunca faça a correção de acesso depender de o
backfill ter rodado. Ponha a compatibilidade no código, para uma falha degradar a
*exibição* e não o *acesso*.

---

## 1.5. A SEMANA DE 08–09/08 EM 60 SEGUNDOS (o que mudou de grande)

Partiu de "as atualizações diárias estão falhando e não sabemos por quê" e terminou com o
sistema operando sozinho. Se você só ler um bloco deste arquivo, leia este:

1. **Deploy é AUTOMÁTICO** (PRs #161-#163): merge na `main` → CI builda → deploya os
   tenants (API→migrations confirmadas→worker esperando janela sem coleta). Auto-deploy
   por webhook do Coolify DESLIGADO. Secrets `COOLIFY_URL`/`COOLIFY_TOKEN` no
   GitHub. Rollback = repontar tag na mão (continua funcionando).
   ⚠️ Eram **3 tenants / 9 apps** quando isto foi escrito; hoje são **5 / 15 + 5 bancos**.
   ⚠️ "migrations confirmadas" quer dizer que o *deployment* terminou — **não** que a
   migration deu certo. Ver §1.4.
2. **Coleta fatiada com rodízio anti-starvation** (PRs #158/#159 + tuning de 09/08):
   rodadas curtas e frequentes, lock compartilhado `/tmp/scraper.lock` por worker
   (sigcon/lote/cagec nunca simultâneos), agendas entrelaçadas. REGRA: margem do
   `timeout` interno = orçamento + 1 município pesado (22 min); coluna `timeout` da task
   = interno + 120s. Fonte de verdade das agendas = o Coolify, não docs.
3. **Observabilidade honesta** (PR #160): `ingestion_log` com `success`/`parcial`/`erro`
   reais; watchdog com staleness POR MUNICÍPIO (agregado, anti-spam; credencial falhando
   = nota, nunca alarme — regra do dono); paginação validada contra o total oficial.
   O canal Telegram do watchdog foi **removido em 05/09/2026** (nunca teve token em
   tenant nenhum): o alerta sai no log, na tabela `watchdog_historico` (aba Status dos
   Dados) e, se `WATCHDOG_WEBHOOK_URL` estiver setada, num POST JSON genérico.
4. **Selo "Atualizado em" nas telas** (PR #164): CAUC/CAGEC já tinham; Convênios
   Estaduais e Emendas ganharam — só data com coleta saudável (`tentativas=0`), senão
   avisa sem afirmar causa. Emendas têm carimbo próprio (`fonte='sigcon_emendas'`).
5. **Carteira da Freitas corrigida (09/08, lista oficial do cliente): 44 municípios** —
   18 ex-clientes DESATIVADOS (`active=false`, histórico preservado; credenciais deles
   `INATIVO-SIGCON-MG`) e 21 novos inseridos (IBGE da API oficial). Os "municípios com
   credencial revogada" do diagnóstico eram, em maioria, ex-clientes.
6. **Diagnóstico completo de 08/08** (6 causas verificadas + cadência oficial das 17
   fontes + capacidade): relatório no artifact da sessão e em
   `Downloads\PACTHA-diagnostico-ingestao-2026-08-08.html` na máquina do dono.

---

## 1.6. A SESSÃO DE 28/08/2026 EM 60 SEGUNDOS (PRs #309–#313, todos mergeados e no ar)

Diretriz do dono, repetida e agora em código: **Minas NUNCA é padrão** — cada estado tem
suas particularidades, e nome de fonte/cadastro sai de catálogo por UF, não de literal.

1. **Nome do cadastro estadual pelo estado do município** (PR #309). Santa Maria/RS via
   "CAGEC — Minas Gerais" e "Regular no CAGEC" em cima do CHE gaúcho. Entrou
   `backend/services/cadastro_estadual.py`, ESPELHO de `frontend/src/lib/estadual.ts`
   (sigla, nome, fonte, portal, certificado, o que a irregularidade trava). Os payloads do BI
   trazem `ufs_na_fonte` (par de `ufs_sem_fonte`); IA, narrativa, push e `/api/cagec` usam o
   catálogo. Sem UF conhecida o rótulo é o genérico "Cadastro estadual" — nunca "CAGEC".
   ⚠️ Estado novo entra nos DOIS arquivos, só com coletor no ar.
2. **Telemetria (Configurações → Telemetria)** (PRs #310 e #311). A sessão de uso era o `sid`
   do TOKEN (30 dias): quem fechava o navegador e voltava no dia seguinte "estava logado há
   15h". Agora cada linha de `uso_sessao` é um **trecho contíguo** (`add_uso_trechos.sql`:
   `sessao_token` + `motivo_fim` largo): silêncio > 5 min ou logout abre linha nova; a
   anterior fecha como `logout` / `navegador_fechado` / `expirou`. **Sair encerra na hora**
   (o próprio `POST /auth/logout` fecha a sessão; `/uso/presenca` não segura logout).
   Captura de eventos **genérica** em `lib/uso.ts`: clique (rótulo visível), parâmetros de
   GET (= filtro aplicado) e POST/PUT/DELETE 2xx (= o que gravou); nada de texto digitado;
   `data-uso` / `data-uso-alvo` / `data-uso-ignorar` para dizer melhor ou calar. Frases em
   `lib/uso-rotulos.ts` (tela por rota, escrita por caminho — acrescentar linha lá quando
   sair "gravou dados em X"). Retenção 6 meses (expurgo oportunista em `/uso/lote`).
   Card "Online no Sistema"; Eventos à esquerda (por dia, filtro por pessoa/tipo, modal);
   Sessões à direita (por dia → pessoa → sessão, com como terminou, modal).
3. **Menu por esfera** (PR #312): grupos **FEDERAIS** (ex-"Transfere Gov") e **ESTADUAIS**,
   em maiúsculo — municipais virão. A fonte foi para o card: campo "Fonte: TransfereGov"
   no canto inferior direito de cada proposta (Em execução, Especiais, PAC, Voluntárias,
   Rejeitadas, Encerradas). Rótulos do catálogo de permissões não mudaram.
4. **Logo do Freitas** (PRs #312 e #313): arte nova `frontend/public/logo-freitas.png`
   (PNG transparente, corte do dono, 998×354); `build-frontend.yml` do `frontend-freitas`
   aponta para `/logo-freitas.png`. O RM em PDF lê `backend/assets/freitas-logo.jpeg`
   (regerado da arte nova sobre branco — a env `RM_LOGO` NÃO mudou). Em `Marca.tsx`,
   `AJUSTE_LOGO`: fundo claro só no tema escuro e deslocamento óptico de 14% (centro de
   massa da arte a 36% da altura) para o "FREITAS" ficar na linha do nome da cidade —
   se a arte for recortada de novo, remedir.
5. **Fluxo de trabalho desta sessão**: branch → PR → dono merge → CI deploya os 4 tenants.
   Testes do backend: 1931 passando; **11 falhas pré-existentes** em
   `test_permissoes_*`/`test_registro_rotas.py` (não são regressão — conferir com
   `git stash` antes de culpar uma mudança). ESLint tem erros `set-state-in-effect`
   pré-existentes nas telas do TransfereGov e no `dashboard/page.tsx`.

---

## 1.7. A SESSÃO DE 03–04/09/2026 EM 60 SEGUNDOS (PRs #367–#370, todos mergeados e no ar)

Entrou o **Obras.gov.br / CIPI** nos cinco tenants — **1.011 obras federais**, o menu
**OBRAS** e a tela `/dashboard/obrasgov`. É a fonte que mostra o que nenhuma outra
mostrava: SISMOB cobre saúde e SIMEC cobre educação, mas mobilidade, saneamento,
habitação, segurança e a **reconstrução da Defesa Civil** não apareciam em lugar nenhum
(em Nova Palma são 21 das 30 obras — a reconstrução pós-enchente inteira).

1. **O bloqueio era do HOST, não do Governo** (PR #367). O coletor ficou pronto e
   desligado desde 02/09 porque `api.obrasgov.gestao.gov.br` devolve **429 na primeira
   requisição** vinda da VPS. O mesmo acervo está em
   **`api-publica.obrasgov.gestao.gov.br`**, que responde **200 em 0,13 s**. A troca de
   host matou três das quatro armadilhas antigas e derrubou a varredura de uma UF de ~8 min
   para ~75 s. ⭐ **O município sai do CNPJ, NUNCA do nome** (diretriz do dono): casar por
   nome trouxe 379 obras da UFSM como se fossem da prefeitura de Santa Maria.
2. **Uma categoria de 41 caracteres derrubou a carga inteira de um tenant** (PR #368).
   `natureza = 'Projeto de Investimento em Infraestrutura'` contra `VARCHAR(40)`, e o
   novapalma tinha passado limpo minutos antes — a pior forma de bug, some no primeiro
   tenant e derruba o segundo. Taxonomia de fonte externa agora é **`TEXT`**; só continua
   `VARCHAR` o que tem *formato* (`id_unico`, `cep`, `uf`).
3. **A tela que faltava** (PR #369). A tabela era lida só pelo painel de frescor — provava
   que a fonte estava viva sem mostrar obra nenhuma. O grupo OBRAS nasce com dois itens e
   cresce; ⚠️ o **SISMOB aparece em OBRAS e em SAÚDE**, o mesmo link nos dois lugares, de
   propósito. E as duas telas **se sobrepõem nos dados** (o CIPI reúne obras que o SISMOB
   publica: 45 das 360 do freitas): decisão do dono é mostrar a visão geral e **dizer**
   quais são — selo "também no SISMOB" e bloco «Por sistema de origem».
4. **A data efetiva não é sinal de nada, e por isso 27 de 30 obras "exigiam atenção"**
   (PR #370). `data_inicial_efetiva`/`data_final_efetiva` vêm **vazias em 100% das 1.011
   obras**, e 65 obras "Concluída" não têm data de conclusão — o Governo encerra mudando a
   **situação**, não preenchendo data. Quem classifica passou a ser a `situacao`, e são
   **quatro** grupos, não três: ⚠️ **«não saiu do papel»** (Cadastrada + previsto vencido) é
   grupo PRÓPRIO, não um pedaço de «ação» — obra parada se cobra do executor, projeto
   encalhado se cobra do município e do órgão repassador. Somar as duas escondia as duas.
   ⭐ E **a fonte manda acento codificado duas vezes** (latin-1 lido como UTF-8 e gravado
   assim); o conserto vai na ingestão e **desiste** se a reinterpretação não melhorar.

**Auditoria de infra do mesmo dia** (04/09, contra a API do Coolify — as 15 apps na tag
`sha-4d5a37f`, as 5 APIs `running:healthy`). Três achados corrigidos na hora, todos de
agendamento e nenhum de código:

- 🔴 **`tmp-g9umo` rodando a cada minuto há 34h** no `montesiao-mg-worker` — sonda de
  diagnóstico de 03/09 cujo `finally` nunca restaurou o cron. ~1.440 execuções/dia contra o
  banco da prefeitura com uso real. Apagada. Detalhe e a regra nova em [`INFRA.md`](INFRA.md) §8.
- 🟠 **`fpe-rs` agendado fora da janela do portal** nos dois tenants do RS (ver §2).
- 🟡 **`obrasgov` do freitas no mesmo minuto do `transferegov-lote`** (03:25). Os locks são
  diferentes de propósito, então **não** se serializavam. Movido para 03:30. A escada de 5 min
  foi desenhada entre tenants sem conferir a coluna vertical de cada worker.

⚠️ E ficou **uma pendência de código** achada nessa auditoria, não corrigida porque mexer em
`backend/**` deploya os cinco: o **SISMOB tem DOIS caminhos vivos** (Scheduled Task própria
nos 5 workers **e** a entrada em `run_dadosabertos_cron.run_all()`). Hoje não duplica coleta
— os dois passam pelo gate de 20h —, mas o docstring de `_deve_pular()` ainda afirma que não
existe task própria, que é a premissa exata que causou o incidente do PR #259. Ver
[`INFRA.md`](INFRA.md) §5.

---

## 1.8. A SESSÃO DE 05/09/2026 EM 60 SEGUNDOS (redesenho do módulo AGENDAMENTOS)

O agendamento — que nasceu em 02/09 como "título + data + status" — virou **COMPROMISSO**,
e o módulo virou a agenda de verdade da equipe: **três abas** (Calendário | Kanban | Lista),
card lateral "compromissos de hoje" e **relatório PDF** de Dia/Semana/Mês. Todo o resto da
plataforma mostra dado que vem de fora; este continua sendo o único que a equipe escreve.

1. **Modelo novo, migration ADITIVA e sem DROP** (`add_agendamentos_compromisso.sql`).
   `titulo` → `demanda` (RENAME guardado dos dois lados), e entram `hora_inicio`,
   `tem_periodo`, `hora_fim`, `data_solicitacao`, `solicitante`, `contato_whatsapp`, `cor` e
   `coluna_id`. O `status` (as três colunas cravadas) virou a tabela
   **`agendamentos_colunas`** — 3 fixas + até 2 próprias por tenant, teto de 5 conferido
   **na API** e não só no botão. Nasce também `agendamentos_anotacoes`, **append-only**:
   a trava é a AUSÊNCIA de rota de editar/apagar, não um trigger.
   ⚠️ **Nada é apagado**: `status`, `relato`, `responsavel_id` e `anexos` ficam de pé. O
   `relato` antigo é migrado para a PRIMEIRA anotação do compromisso (idempotente pelo
   `NOT EXISTS`, seguro só porque anotação não se apaga), e o anexo já gravado continua
   sendo servido pela rota com permissão própria — o formulário novo não anexa mais.
2. **⭐ `municipio_id` CONTINUA `NOT NULL`, e é a única divergência consciente do documento
   de redesenho**, que pedia "nulo em prefeitura". Nulo quebraria três coisas que já
   existem: o JOIN de `municipios` (INNER — a linha sumiria), o recorte de carteira
   (`= ANY(:mids)` **nunca casa com NULL**, então o compromisso ficaria invisível para toda
   carteira restrita) e o carimbo da trilha. O que o documento quer — "o município é
   implícito na prefeitura" — é sobre a TELA, e é assim que está: num tenant de um município
   só **não há campo nem filtro de município em lugar nenhum**, e `_municipio_implicito`
   preenche a coluna. ⚠️ E a contagem é a de **`municipios` ativos do TENANT**, nunca a
   carteira de quem está logado: numa assessoria de 42 cidades, um usuário com uma cidade só
   cairia no modo prefeitura e criaria compromisso sem escolher.
3. **Uma lista só, sempre no backend.** A paleta de acento (9 cores, `GET /paleta`) e as
   colunas do kanban (`GET /colunas`) vêm da API — este repo já pagou caro por listas gêmeas
   (os três status viviam em três lugares). Na tela a cor é **receita, não tabela**: `.ag-chip`
   monta fundo e texto com `color-mix` sobre os tokens do tema, então o mesmo hex lê bem no
   claro e no escuro sem uma segunda paleta para manter em sincronia.
4. **Fonte única de dados, de verdade.** As três abas e o card lateral leem o MESMO
   `GET /api/agendamentos`; a consulta **não tem recorte de data** de propósito (cada aba
   precisa de uma janela diferente, e recortar no servidor obrigaria a uma busca por aba).
   O relatório PDF usa a **mesma `_filtros`** da lista — o arquivo tem as linhas da tela.
   ⚠️ A busca é sem acento **sem `unaccent`** (a extensão não existe nos cinco bancos): o
   mesmo mapa de `translate()` é aplicado no SQL e no Python, então o casamento é exato por
   construção.
5. **Três defeitos silenciosos herdados, corrigidos de passagem:** a tela usava
   `bi-input` (a classe é **`bi-field`**), `var(--bi-card)` e `var(--bi-crit-bg)` — os três
   nunca existiram. Campos sem estilo e caixa de erro transparente, sem erro nenhum no
   console.

Suíte: **verde inteira** (`test_agendamentos.py` reescrito, 61 casos — inclui um que cruza
o nº de colunas do `_SELECT` com os índices que `_row_to_dict` lê, porque esse defeito não
levanta erro: só troca os valores de lugar na tela). Front: `tsc --noEmit` limpo,
`next build` OK, e o lint saiu de **39 para 37** achados no repo.

**RODADA 1 DE AJUSTES no mesmo dia (PR #378)**, depois de o dono ver o módulo no ar. A spec
detalhada mora agora em **[`docs/agendamentos.md`](docs/agendamentos.md)** — arquivo novo, e
é ele que a próxima sessão deve ler antes de mexer na agenda. O que vale registrar aqui:

- ⭐ **A tela achatada era um `min-h-0` faltando um nível acima.** O `Calendario` não pedia
  `flex-1` dentro da coluna flex do contêiner, e um filho flex tem `min-height: auto`
  ("não encolha abaixo do conteúdo") — o que trava a divisão da altura e faz a grade nascer
  do tamanho do texto. A regra que fica: **numa cadeia flex que divide altura, `min-h-0` em
  todos os elos, e o último pede `flex-1`.**
- ⭐ **O bug do período: a bandeira saiu do caminho.** Compromisso com período saía como chip
  de 30 min. O backend estava CORRETO (simulado o corpo do modal pelo pydantic e pelo
  `_row_to_dict`: `tem_periodo`/`hora_fim` vão e voltam intactos), então quem decide o bloco
  esticado passou a ser a **hora de término**, não a bandeira — as duas são redundantes por
  construção, e quando duas fontes dizem a mesma coisa quem manda tem de ser uma.
  ⚠️ **O defeito original não foi reproduzido**; se reaparecer, o que falta é o JSON de
  `GET /api/agendamentos` do compromisso.
- **A regra das colunas fixas mudou**: as três iniciais passam a ser **renomeáveis e
  coloríveis** (migration `add_agendamentos_coluna_cor.sql`); só a remoção continua vedada.
  ⚠️ Renomear **não toca na `chave`** — o código acha a coluna de entrada por
  `chave = 'solicitada'`, e levar a chave junto quebraria o default de todo compromisso novo,
  em silêncio, só no primeiro cadastro seguinte.
- **Ocupação de tela**: o módulo ganhou **pele própria escopada** — `.ag-modulo` redeclara
  `--bi-bg`/`--bi-surface`/`--bi-line` (com equivalente escuro), e os tokens valem da borda
  do contêiner para dentro. Acento, CTA, link, aba ativa e foco continuam os do PACTHA;
  nenhum outro módulo muda.
- **Sem duplo clique para editar em aba nenhuma** (hover → balão, um clique → detalhe, botão
  «Editar» dentro). O duplo clique sobrou só na célula VAZIA, para criar.
- **Arraste do kanban é próprio, sem biblioteca** — o projeto não tem lib de DnD, e trazer
  uma para inclinar um cartão custaria uma dependência nos cinco tenants. `pointer events`
  com limiar de 6px, overlay `fixed` inclinado −3°, vão tracejado no destino e Esc para
  cancelar.

**AS DUAS CORREÇÕES DE COR QUE VIERAM DEPOIS (PRs #380 e #381)**, cada uma com uma lição que
vale além deste módulo:

- ⭐ **Fundo escopado precisa de contêiner SEM padding, senão vira um retângulo pintado.** O
  módulo estava no contêiner comum, que põe padding — então o `.ag-modulo` pintava só a caixa
  dele e sobrava uma **moldura do cinza do sistema** em volta, em cima, embaixo e nas
  laterais. Margem negativa resolvia só a horizontal. A rota passou para **`telaCheia`** (o
  mesmo mecanismo do Painel de Indicadores) e o módulo cuida do próprio espaçamento — hoje
  copiando o `PADDING_PADRAO` do layout, para não ficar com margem diferente das demais.
  ⚠️ E lá dentro é **`h-screen`, não `h-full`**: o `<div key={escopo}>` que envolve a página
  é um bloco sem altura própria, e `height: 100%` sobre pai de altura automática resolve
  para `auto` — o módulo voltaria a nascer do tamanho do conteúdo.
- ⭐ **NUM CALENDÁRIO, QUEM PINTA A TELA É A LINHA DA GRADE, NÃO O FUNDO.** Foram precisas
  três tentativas até ver isso. Medindo em `r − b` (o "quanto de amarelo" de um cinza; num
  neutro puro vale 0):

  | tentativa | chão | linha da grade |
  |---|---|---|
  | 1ª (`#f4f1e8`) | 12 | 20 |
  | 2ª (`#fffdf0`) | 15 | **33** ← ficou MAIS amarela que a 1ª, com o chão mais CLARO |
  | final (`#fffefa`) | 5 | 11 |
  | tema do sistema | −1 | −2 |

  A malha 7×5 do mês atravessa a tela inteira; o chão aparece só nos vãos entre os cartões.
  Ao escurecer a linha para compensar o degrau chão→cartão perdido, ela foi escurecida pelo
  **eixo do bege** — e o módulo ficou mais amarelo justamente na tentativa em que o fundo
  clareou.
  ⚠️ **A regra que fica: contraste se ganha na LUMINOSIDADE; o calor se mantém constante ao
  longo da rampa.** A razão calor(linha)/calor(chão) é 2,2× — a mesma proporção que o tema
  usa no lado frio (−1 → −2); o que mudou foi o valor absoluto.
- ⚠️ **Com o chão a 0,37 de ΔL\* do branco, o degrau chão→cartão deixou de existir** (no tema
  ele vale 6,1). Quem separa o cartão da página passou a ser a linha — e por isso ela é um
  pouco mais escura que a do tema. **Não a enfraqueça "para combinar com o fundo mais
  claro"**: é o movimento intuitivo e é o contrário do que a conta pede. A tabela inteira
  está no comentário do bloco `.ag-modulo` em `globals.css`.
- Efeito colateral do chão quase branco: o **dia de fora do mês** saía de uma mistura com
  `--bi-bg` e virou branco puro (agosto ficava idêntico a setembro na grade). Passou a sair
  de `--bi-surface-2`.

**Estado em 05/09/2026, fim do dia:** cinco PRs (#377 a #381) mergeados e no ar; backend e
frontend dos cinco tenants na tag `c252c0a`, batendo com o `main` — a checagem que o
[`INFRA.md`](INFRA.md) manda usar para provar que um deploy chegou. O dono conferiu na tela
o bloco de período da vista semanal, as cores dos cabeçalhos do kanban e o fundo: tudo certo.

⚠️ **O que continua sem validação automática**: as cores e o layout, porque não há Postgres
na máquina de desenvolvimento (a suíte roda sem banco, ver `conftest.py`) nem suíte de
frontend no repo. As três rodadas de ajuste visual desta sessão saíram todas de conferência
na tela pelo dono — se um dia o módulo ganhar teste de regressão visual, é aqui que ele paga.

---

## 1.9. A SESSÃO DE 06/09/2026 EM 60 SEGUNDOS (emendas parlamentares FEDERAIS)

O dono trouxe um levantamento da API do Portal da Transparência (CGU) e o token dele. A
fonte já tinha scaffold **deliberadamente inerte** desde 03/09 esperando duas coisas: a
chave e a decisão do que gravar. As duas chegaram.

**O que o levantamento errava, e foi medido contra o Swagger (`/v3/api-docs`, 106 endpoints):**
o `ConvenioDTO` **não tem campo de emenda** — o vínculo que a CGU anunciou em nov/2024 está
na *tela* do portal, não na API. E existe uma classe de **APIs restritas a 180 req/min**,
com suspensão do token por 8h, que o levantamento não mencionava.

**⭐ O achado que mudou a conta, e ele não é da API.** O dump aberto `siconv_emenda.zip`
(8,3 MB) tem `BENEFICIARIO_EMENDA` = **CNPJ de 14 dígitos** em 298.107 das 298.114 linhas.
Casando com o CNPJ que o `siconfi.py` já grava em `municipios.cnpj` — conferido ao vivo
contra a API de entes do Tesouro, **bate exatamente nos três municípios testados** — sai a
carteira inteira, sem chave nenhuma:

| | Emendas | Valor | Parlamentares |
|---|---|---|---|
| Nova Palma/RS | 44 | R$ 13,68 mi | 17 (Heitor Schuch lidera, 14 emendas) |
| Monte Sião/MG | 33 | R$ 12,24 mi | 18 (Júlio Delgado lidera, 11) |

E o número que justificou o trabalho: **45% dessas emendas têm `ID_PROPOSTA` vazio**. Todo
caminho que o produto usava para chegar em emenda federal passava por proposta — quase
metade da carteira era invisível.

**O desenho, em duas fases:** a **carteira** (dump aberto, por CNPJ) roda nos cinco tenants
e é *commitada antes* da **execução** (CGU, com chave), que só roda em `novapalma-rs` e
`montesiao-mg`. É isso que faz a tela nascer útil onde a chave não está.

**Três armadilhas que a medição encontrou e que viraram teste:**

1. **`VALOR_REPASSE_EMENDA` vem vazio em 38% das linhas.** Sem o fallback para
   `VALOR_REPASSE_PROPOSTA_EMENDA`, Nova Palma sai como R$ 9,23 mi em vez de R$ 13,68 mi —
   um terço do dinheiro some, e some *plausivelmente*.
2. **O agregado da CGU é NACIONAL**, da emenda inteira e não da fatia do município. Por
   isso `emendas_federais_cgu` **não tem `municipio_id`**: sem a coluna, o
   `SUM(valor_pago) GROUP BY municipio_id` que inflaria o número é impossível de escrever
   por acidente. A guarda é o schema, não a disciplina de quem escreve a query.
3. **`NR_EMENDA` vem vazio (7.059 linhas), com 4 dígitos (444) e com 9 (1).** Um `zfill`
   produziria um código **válido e de outra emenda** — número plausível e errado não tem
   como ser percebido depois. A função devolve `None` e a linha continua na carteira.

**⚠️ A hipótese que ainda não foi confirmada contra a CGU:** o `codigoEmenda` de 12 dígitos
é derivado (ano do programa + `NR_EMENDA`). O `--verificar` usa como **grupo de controle** os
códigos que o próprio Governo já formatou em `transferegov_te.emenda` — se eles responderem
e os derivados não, o problema é a derivação; se nem eles, é a chave ou o endpoint, e não se
mexe na fórmula. O **plano B já está implementado** (`PT_ESTRATEGIA=ano_numero`): `/emendas`
aceita `ano` + `numeroEmenda`, não depende da hipótese, custa a mesma requisição e devolve o
código verdadeiro — que é gravado em `codigo_confirmado` e nunca mais derivado.

**Cron:** Scheduled Task **própria**, e não `run_dadosabertos_cron.run_all()` — porque
[`INFRA.md`](INFRA.md) §5 diz que **nos dois tenants do RS não há `sigcon`**, e é ele que
chama aquele laço. Nova Palma, justamente um dos dois de teste, nunca coletaria.

**Estado:** dois PRs. **#391 (coleta)** — migration com 4 tabelas, coletor, watchdog,
monitor de frescor e 46 testes. **PR 2 (tela)** — `/dashboard/emendas-federais` no grupo
FEDERAIS, com os cinco estados honestos, o bloco «quem destinou recurso ao município»
e a sétima fonte da tela de Parlamentares (com anti-join para não inflar o Painel do
prefeito). Suíte em 2.530; `tsc`, `eslint` e `next build` limpos.

**06/09, depois da primeira carga real:** ela trouxe **69 das 77 linhas** de Nova Palma.
As 8 que faltaram são da **Associação Hospital Nossa Senhora da Piedade** — R$ 1,2 mi em
emendas que existem e não apareciam, porque `municipios.cnpj` guarda UM CNPJ e os coletores
garimpavam os demais em `sismob_obras` e `transferegov_pac` (onde um hospital filantrópico
nunca aparece). Daí nasceu **`municipio_entidades`** — cadastro explícito de CNPJ por
município, com `origem`. ⚠️ A saída fácil era casar o NOME no dump de proponentes, que é
a regra proibida: o CNPJ tem de ter origem, não dedução.

**✅ NO AR EM 06/09/2026, conferido no servidor.** Migrations OK nas cinco APIs; as cinco
Scheduled Tasks `portal-transparencia` criadas (freitas 03:45 · trust 04:20 · montesiao
04:50 · santamaria 05:20 · **novapalma 05:50** UTC — horários escolhidos DEPOIS de ler a
coluna de cada worker, porque os do plano colidiam com `obrasgov` e `tcm-go`). Carga real:
**Nova Palma 77 linhas / 44 códigos / R$ 13.682.127,98** (69 prefeitura + 8 hospital) e
**Monte Sião 53 / 31 / R$ 11,96 mi**. Zero duplicatas; a segunda rodada não mudou contagem
nem valor, e o `visto_em` avançou — idempotência medida em produção, não presumida.

⚠️ **A FASE 2 (execução) NÃO RODOU:** falta a `PORTAL_TRANSPARENCIA_API_KEY` nos workers.
A rodada sai `success` com a nota «execucao CGU nao coletada», e a tela diz isso em vez de
mostrar R$ 0,00. **A hipótese do código de 12 dígitos segue sem confirmação** — é o
`--verificar` que a testa, e ele depende da chave.

⚠️ **E uma armadilha de identificação que me custou tempo:** `ps aux | grep uvicorn` dentro
do container NÃO distingue API de worker de forma confiável — rodei a primeira carga dentro
das APIs. O dado foi para o banco certo (mesma `DATABASE_URL`), mas a fonte de verdade para
saber quem é quem é `GET /api/v1/applications` do Coolify, que devolve o nome (`*-api`,
`*-worker`, `*-frontend`) junto do UUID — e o nome do container é `<uuid>-<timestamp>`.

**✅ A TELA NO AR E CONFERIDA (06/09, 22h).** Chamada com dado real pelo container da
API: Nova Palma `parcial`, 64/67 consultadas, **R$ 13.682.127,98** indicados (R$ 12,28 mi
à prefeitura + R$ 1,40 mi ao Hospital N. S. da Piedade), 16 parlamentares, 27 impositivas.
Monte Sião: 50/52, R$ 12.237.769,16, 12 parlamentares. **Bate ao centavo** com a medição
feita antes de existir código.

⚠️⚠️ **TREZE DEFEITOS MEUS NESTA FONTE, e o padrão vale para o próximo coletor:** sete só
apareceram com **dado real e volume real** — nenhum foi pego por revisão de código (três
agentes), plano (400 linhas) ou teste de unidade. Os piores: a tela dava **500** em todo
município com carteira (`x[25]` num SELECT de 25 colunas, e dois vizinhos deslocados lendo
campo errado em silêncio); o KPI somava **R$ 4,05 bilhões** para um município de 5.676
habitantes (o agregado da CGU é NACIONAL, e eu contornei em Python a guarda que tinha
posto no schema); e `fonte_ligada` lia uma env que mora no WORKER, escondendo 64 execuções
já coletadas.

**A lição operacional:** `pytest` verde e CI verde não dizem que funciona. O que diz é
rodar contra o banco de produção e **chamar a função que a tela chama**. A lista do que
sobrou (com o que exige decisão do dono) está em `docs/emendas-federais-pendencias.md`.

⚠️ **Achado colateral registrado, e vale conferir:** `add_tela_obrasgov.sql` e
`add_tela_investsus.sql` concedem só `user_telas`, e o comentário deles afirma que a
ação «já herda de convênios». Não herda nos cinco no ar — `permissoes_efetivas()`
resolve só de `user_permissoes`, e os dois blocos que derivariam a permissão têm guard
em `migration_backfills` e já dispararam. Quem foi configurado à mão pode estar vendo
**Obras Federais** e **InvestSUS** no menu e tomando **403**. O backfill das emendas
federais já nasce corrigido (concede a tela E a ação); os dois antigos são PR próprio.

---

## 1.10. A SESSÃO DE 06/09/2026, PARTE 2 (novas APIs do TransfereGov — fases 1 e 2)

O MGI desligou em 31/08/2026 os endereços antigos de dados abertos (Comunicado nº 23/2026)
e publicou dois hosts novos com **68 endpoints REST**. O PACTHA já tinha migrado a parte
obrigatória (os 65 dumps e o host do Obras.gov, em 02–04/09), então nada estava fora do ar:
o que faltava era o que é genuinamente novo.

**Fase 1 (PR #403, mergeado) — higiene.** `docker-compose.yml` e os dois scripts de
reconhecimento da VPS ainda apontavam para hosts que hoje devolvem 404/429. No caminho
apareceu que a env do worker tinha o **nome errado desde sempre**: os coletores leem
`TRANSFEREGOV_DADOS_URL`, não `TRANSFEREGOV_BASE_URL` (esta última, em `config.py`, nunca
foi referenciada em lugar nenhum — removida). Também entraram os três dicionários de dados
novos (Especiais, Parcerias, Fundo a Fundo) e o registro de `siconv_federal` e
`transferegov_te` no monitor de frescor, onde nunca estiveram.

**Fase 2 — a Transferência Especial trocou de fonte.** A listagem saía da API interna da
SPA de `especiais.transferegov.sistema.gov.br`, com endereços descobertos no bundle JS.
Custo registrado: **25 de 42 rodadas parciais em 30 dias** e o IP da VPS punido por >6h. E
o município era casado por **substring de nome** — 628 de 890 linhas com CNPJ divergente no
tenant trust. Agora entra pelo CNPJ (`municipios.cnpj` → `id_beneficiario` → planos): 2
requisições por município, sem 403, vínculo exato.

**O que a medição de 06/09 provou antes de uma linha ser escrita:**

- **Os ids são idênticos nas duas APIs**, na cadeia inteira — plano 3200 = 3200, empenho
  62311 = 62311, DH 76255 = 76255, OP/OB 53038 = 53038. Sem isso, o upsert por
  `plano_acao_id` teria duplicado a tabela na primeira rodada.
- **O vocabulário da situação do plano de trabalho NÃO é o mesmo**, e essa era a armadilha
  muda da fase: a oficial manda `Legado ADPF 854 STF / NT - TCU` onde a SPA mandava
  `CONCLUIDO_NT_TCU`. O `rm_builder` decide estágio procurando **substring** ("conclu",
  "empenh", "pag"...): gravar o rótulo cru faria o plano cair para "CIENTE", e
  `_fed_retem` **descarta ativa de ano anterior** — o plano sumiria do relatório sem erro
  nenhum em log. Mapa conferido par a par, 19/19 (`_SITUACAO_PT_PARA_CODIGO`).
- **`codigo_programa` da API oficial perde o zero à esquerda** ('903' onde a SPA mandava
  '0903', porque trata como número). O código do plano carrega o do programa intacto antes
  do último hífen: 800 de 800 conferindo, e sem gastar uma requisição por programa.
- **`valor_total` não existe na fonte nova** — é custeio + investimento, que bate com o
  `valorTotal` antigo em 800 de 800.
- **A API oficial entrega acentuação correta** onde a SPA entrega mojibake
  ("Ampliação" vs "Amplia??o").

**Os pagamentos ficaram na SPA, de propósito** (decisão do dono): só ela tem o CPF do
ordenador/gestor e o histórico de eventos da OP. E o rate-limit nunca foi dela — os
lookups por id fazem 590 requisições sequenciais com zero 403; quem punia era a listagem,
que é justamente o que saiu.

**Dois consumidores tiveram de acompanhar, e um deles quebraria calado:**
`routers/transferegov.buscar` lia o `raw_data` cru com as chaves camelCase da SPA — com a
fonte nova, todo `it.get(...)` devolveria `None` sem levantar exceção e a tela ficaria
vazia. Passou a ler as **colunas** da tabela (que o RM sempre leu), mantendo os nomes de
saída idênticos, então o frontend não mudou. E `/por-cnpj`, que baixava a listagem
**nacional** (~58 mil planos, budget de 15s, quase sempre estourando) para filtrar um CNPJ
em memória, agora filtra na fonte: 2 requisições, resposta completa.

**A limpeza que o coletor sozinho não faz:** ele corrige, no primeiro upsert, toda linha
cujo beneficiário esteja na carteira. O que sobra são os planos de municípios **de fora**
creditados a alguém de dentro — esses nenhuma rodada visita, e ficariam para sempre na tela
de quem não é dono. `limpa_transferegov_te_vinculo_por_nome.sql` os apaga, exigindo prova
dos dois lados (CNPJ na linha **e** no município) e respeitando `municipio_entidades`.

⚠️ **PENDENTE, e é pré-requisito de operação:** rodar
`scripts/reconhecimento_fontes_vps.sh` **na VPS**. Todas as medições acima saíram de IP
residencial, e o host novo está atrás de Cloudflare — o TCE-RS já ensinou que isso muda
tudo.

## 1.11. A SESSÃO DE 07/09/2026 (Obras.gov.br — fase 3 da migração de APIs)

O coletor usava **1 dos 8 endpoints** da API. A fase 3 acrescentou os outros sete e,
no caminho, corrigiu uma afirmação que estava no cabeçalho do próprio arquivo desde
04/09.

**O filtro territorial existe — só não está onde se procurou.** A armadilha nº 1 do
`ingestion/obrasgov.py` dizia *"NÃO EXISTE FILTRO TERRITORIAL"*, e isso é verdade para
`/projeto-investimento` (que ignora `codigo_ibge` e devolve o estado inteiro com HTTP
200). Mas o `/geometria` filtra de verdade:

    /geometria sem filtro ........... 216.278
    /geometria?cod_ibge=4313102 .....      26
    /geometria?cod_ibge=9999999 .....       0   (não devolve tudo)

**E ele não substitui o CNPJ, soma-se a ele.** Medido nos três tenants:

| município | por CNPJ | por geometria | só CNPJ | só geometria |
|---|---|---|---|---|
| Nova Palma | 30 | 26 | 5 | 1 |
| Santa Maria | 78 | 436 | 7 | **365** |
| Monte Sião | 5 | 8 | 0 | 3 |

Os 365 extras de Santa Maria são obras federais **no território** de outros entes —
UFSM, DNIT, IF Farroupilha, Receita Federal, Comando da Aeronáutica. Decisão do dono:
entram, **marcadas** por `vinculo` ('prefeitura' | 'territorio' | 'abrangencia'). Sem a
marca, seria repetir por outro caminho o erro que o arquivo já documenta — obra da
UFSM posando de obra da prefeitura.

**O terceiro valor do `vinculo` nasceu de medição.** Amostra de 124 projetos da
carteira do freitas: 102 com geometria em UM município, 15 em 2 a 5, e **3 em mais de
cem** — `324.31-80` ("Manutenção rodoviária na malha federal do DNIT em MG", 790
municípios), FUNASA (202) e uma consultoria de PE (312). O primeiro sozinho cai em 41
dos 42 municípios do freitas: gravá-lo como obra em Araújos seria o mesmo ruído 41
vezes. Corte em 20 (`OBRASGOV_ABRANGENCIA_MAX`).

**A chave virou `(municipio_id, id_unico)`** — a troca que `add_obrasgov.sql` previu no
próprio cabeçalho ("*registrado aqui para que a troca seja uma decisão, e não uma
descoberta*"). Chegou a hora porque o freitas tem 42 municípios ativos e o território
multiplica a obra intermunicipal: com a chave global, 40 dos 41 donos do `324.31-80`
perderiam a obra em silêncio.

**A fase de detalhe varre a fonte inteira e casa em memória**, em vez de perguntar
projeto a projeto — contra 2.180 requisições só em Santa Maria (~13 min, crescendo com
a carteira). Sequencial por decisão do dono, mesmo com a VPS nova de 8 núcleos: o
gargalo é latência de rede, não CPU, e paralelizar contra fonte federal é o que a skill
`ingestion` proíbe.

⚠️ **A ESTIMATIVA ERROU POR MAIS DO DOBRO, e a medição contra a fonte mudou o
desenho.** Eu disse ~450s para os cinco endpoints; o real é **1.020s**:

    execucao-fisica ...... 384s    71.743 linhas    3 da carteira (Nova Palma)
    empenho .............. 301s    89.477 linhas  650
    estudo-viabilidade ... 276s    78.227 linhas    3
    contrato .............. 30s     7.624 linhas   73
    historico-paralisada .. 29s     8.000 linhas    0

Daí saíram duas correções. **Rodízio:** os dois baratos (60s juntos) vão toda rodada e
os três caros se revezam, um por noite — varrer os cinco todo dia seria 17 min por
tenant, com os cinco baixando as mesmas 1.278 páginas da mesma fonte federal. Cada
endpoint caro se atualiza a cada três dias, frequência de sobra para percentual de obra.
**Teto próprio de páginas:** o `/empenho` tem 448 páginas e o `TETO_PAGINAS` de 400
cortava a varredura em 80.000 linhas — o coletor gravaria empenho faltando e diria
apenas "PARCIAL" numa linha de log.

**Dois defeitos meus, pegos antes de ir ao ar:** o log do `httpx` despejaria 1.278
linhas por rodada, enterrando o resultado (silenciado, como `sismob_obras` já fazia); e
o loop só olhava os projetos da varredura da UF — mas a `uf_principal` nem sempre é a
do território (o `123265.26-04` é de PE e tem geometria em MG), então os territoriais
de outra UF sumiriam. Agora são buscados um a um.

**Infra mudada junto:** `timeout` das tasks de 900/1200 para **1800s**, e a escada
entre tenants de 5 para **30 min** (santamaria 03:05, novapalma 03:35, montesião 04:05,
trust 04:35, freitas 05:05 UTC). Com rodadas de 12-15 min, os 5 min de antes fariam os
cinco tenants varrerem a fonte federal ao mesmo tempo, do mesmo IP.

### ⚠️ `percentual_execucao` ficou NULO em 538 de 538 obras por um sufixo (07/09/2026)

O #408 prometeu o percentual de avanço físico. O rodízio passou por `execucao-fisica`
em 06/09 e a coluna continuou vazia em **538 de 538** obras do freitas. Causa: o
coletor lia `percentual_execucao` e o campo da fonte é `percentual_execucao_**fisica**`.

⚠️ **E não houve erro em log nenhum.** `.get()` de chave inexistente devolve `None`, que
nesta base significa "a fonte não informou" — o defeito era indistinguível de um dado
que a fonte não publica. Só apareceu porque alguém foi conferir o número.

⚠️⚠️ **E o teste passava.** Ele montava o payload com `percentual_execucao` — o nome que
o *código* usava, deduzido do código em vez de capturado da fonte. Um teste escrito
assim confirma o bug em vez de pegá-lo.

A lição, que vale para todo coletor: **payload de teste se captura da resposta real da
fonte, nunca se deduz do código que se quer testar.** Os quatro testes novos
(`test_os_nomes_dos_campos_lidos_existem_na_fonte`,
`test_payload_com_o_nome_ANTIGO_nao_preenche`) foram verificados por mutação — voltando
o nome errado, quatro deles quebram.

Os campos de `/empenho` (`valor_empenho`, `liquidado`, `pago`, `rpinscrito`) foram
conferidos um a um contra a resposta real e estão certos — daí `valor_empenhado` estar
preenchido em 237 obras enquanto o percentual estava em zero.

### ⚠️⚠️ E o rodízio estava APAGANDO o que não media (07/09/2026)

Descoberto ao conferir a coleta forçada que o dono pediu: o freitas tinha **237 obras
com `valor_empenhado`** e, depois de uma rodada de `execucao-fisica`, ficou com **82**.

`_detalhe_da_rodada` traz UM dos três endpoints caros por dia — desenho correto, para
caber no teto de tempo. Mas o UPDATE sobrescrevia **todas** as colunas de detalhe:

| rodada de… | preenche | **apaga** |
|---|---|---|
| `execucao-fisica` | percentual | empenhos e valores |
| `empenho` | empenhos e valores | percentual |
| `estudo-viabilidade` | estudo | percentual **e** empenhos |

**Nunca havia um dia com os três preenchidos.** O rodízio, criado para economizar
tempo, destruía justamente o dado que o tempo economizado servia para coletar.

⚠️ **E `coalesce` não resolveria direito.** Ele preservaria o valor antigo também
quando a fonte legitimamente parasse de informar — «nunca esquece» é tão errado quanto
«esquece toda vez». A coluna só pode mudar quando ESTA rodada olhou para aquele
endpoint; se não olhou, fica como está. Daí `sql_detalhe(chaves)`, que monta o `SET`
com as colunas dos endpoints efetivamente coletados — função pura, testada nos três
dias do rodízio e validada contra a gramática do Postgres com `pglast`.

⚠️ **Depois do merge, os empenhos não voltam sozinhos**: eles só são recoletados quando
o rodízio passar por `empenho` (09/09), ou numa rodada forçada.

## 1.12. FASE 4 — Gestão de Parcerias (a emenda de saúde que faltava)

O módulo de Parcerias é a fonte onde as transferências passaram a ser processadas
de 2024 em diante: dos 176 programas publicados, **144 são Transferências Fundo a
Fundo da Saúde**. Era o único instrumento federal que a plataforma não enxergava —
e é exatamente onde mora a emenda de saúde do município.

**O que a cadeia entrega**, com dado real de Nova Palma (11 propostas,
R$ 2.184.085, **11 de 11 com emenda identificada**):

    proposta 75376  "AQUISIÇÃO DE EQUIPAMENTO PARA UNIDADE BÁSICA DE SAÚDE"
      └─ emenda 2026.2023.0002 · PAULO PAIM · Individual · GND4 · R$ 299.999
      └─ parceria 75161 celebrada

Os parlamentares que apareceram: Paulo Paim, Covatti Filho, Luis Carlos Heinze,
Afonso Hamm, Márcio Biolchi, Any Ortiz, Pedro Westphalen, Comissão da Saúde.

**⚠️ ESTA FONTE NÃO PODE ENTRAR POR CNPJ.** As 11 propostas de Nova Palma são todas
do FUNDO MUNICIPAL DA SAUDE (`12240183000100`), diferente do CNPJ da prefeitura
(`88488358000156`). Um coletor que casasse por `municipios.cnpj` — como o da
Transferência Especial faz, e com razão lá — não acharia nenhuma. Aqui o
`cd_ibge_recebedor` filtra no servidor (11 de 89.400), então o vínculo vem pronto
da fonte.

**O escopo foi cortado por custo medido, não por esquecimento.** Buscar os 8 filhos
de cada proposta custaria 4.418 requisições no freitas (27 min) e 5.668 no trust
(35 min) — os tenants têm 547 e 706 propostas. O núcleo (proposta + instrumento +
emenda, 2 filhos) custa 1.136 e 1.432, ~420s e ~530s. A execução financeira
(empenho → documento hábil → ordem de pagamento → extrato) entra depois,
incremental. O `/extrato-bancario` sozinho tem **1.275.217 registros** (6.377
páginas) e nunca poderá ser varrido inteiro.

**A TELA CHEGOU EM 07/09/2026** (`/dashboard/parcerias`, `routers/parcerias.py`), e o
ranking por parlamentar abre a página porque é a leitura que o gestor faz primeiro:
quem trouxe recurso para a cidade. No trust isso são 84 propostas e R$ 67,7 mi só da
Comissão da Saúde. A lista de propostas vem abaixo, filtrável por um clique no
ranking, e cada linha diz «não celebrada» quando a proposta ainda não virou
instrumento — estado legítimo e frequente do ano corrente, que esconder faria a
contagem da tela não bater com a da fonte.

⚠️ **Ela fica ao lado de «Voluntárias» no menu de propósito, e não a substitui.**
Aquela mostra o convênio discricionário do SICONV, que continua vindo dos dumps CSV;
esta, o instrumento novo. São dois módulos, dois ciclos e dois tipos de instrumento —
e o dono que abrir as duas lado a lado tem de ver por que os números diferem.

### ⚠️ Nem todo recebedor do município é o município (07/09/2026)

`cd_ibge_recebedor` filtra pelo município do RECEBEDOR — e recebedor não é só a
prefeitura. Goiânia tem 172 propostas, das quais **15 são do FUNDO ESTADUAL DE SAÚDE**,
que atende Goiás inteiro; outras tantas são de associação privada, cooperativa e
sociedade empresária. No tenant trust, dentro de 706 propostas:

| natureza | propostas | valor |
|---|---:|---:|
| Fundo Público da Adm. Direta **Municipal** | 627 | R$ 549,5 mi |
| Associação Privada | 26 | R$ 39,5 mi |
| Fundo Público da Adm. Direta **Estadual** | 20 | R$ 31,1 mi |
| Sociedade Empresária, Cooperativa, Fundação Privada | 28 | R$ 16,1 mi |

**13,6% do valor não era da prefeitura.** E o estrago maior era no ranking: a tela
responde «quem trouxe recurso para a cidade», e somar o Fundo Estadual ao nome de um
parlamentar afirma o que a fonte não afirma.

⭐ **Aqui nada é descartado**, ao contrário do que `faf_planos` faz com o ente estadual.
Lá o plano do estado não tem vínculo municipal nenhum (o IBGE é a SEDE do ente); aqui
tem — a Santa Casa que recebeu emenda federal *está* na cidade, e o gestor quer saber.
Então a linha fica, marcada com «não é da prefeitura», e fora dos totais e do ranking.
`fora_do_municipio` na resposta e uma nota no rodapé dizem quantas são, para quem
conferir contra o portal não achar que faltam propostas.
### ⚠️ E o guarda-chuva do DNIT era 96% do valor da tela de Obras (07/09/2026)

Terceira fonte com a mesma doença, encontrada ao varrer as outras depois do Fundo a
Fundo. O coletor **já marcava** `abrangencia` desde o #408 — o que faltava era a
leitura respeitar a marca. Medido no freitas:

| vínculo | obras | valor |
|---|---:|---:|
| **abrangencia** | 56 | **R$ 15.894.300.865** ← 96% do valor |
| prefeitura | 421 | R$ 606.809.018 |
| territorio | 61 | R$ 91.560.948 |

É o MESMO projeto repetido: «Manutenção rodoviária na malha federal do DNIT em MG»
(R$ 383,3 mi, **790 municípios**) cai em 41 das 42 cidades da carteira, e cada uma
somava os R$ 383 mi inteiros. A tela abria com R$ 16,6 bilhões onde o real é ~R$ 698 mi.

⚠️ **E o conserto tinha de ser nos DOIS lados.** A tela recalcula os cartões a partir
das listas filtradas — de propósito, porque cartão dizendo 360 com 12 obras na lista
faz o gestor desconfiar do resto. Corrigir só o servidor deixaria os R$ 15,89 bi
voltarem pelos cartões; `test_a_tela_usa_a_mesma_regra_do_router` lê o `.tsx` e cobra.

⭐ **`territorio` CONTA**, e essa é a diferença que importa: ali a obra é uma obra só,
naquele lugar, e quem diz é o Governo (`/geometria?cod_ibge=`). O dono ser a UFSM ou o
DNIT não a torna menos real para quem mora na cidade — a tela diz de quem é pelo selo.
Já `abrangencia` não é uma obra na cidade: é um programa estadual cuja geometria passa
por ela.

### As três fontes, o mesmo erro, três respostas diferentes

| fonte | o que entrava | resposta |
|---|---|---|
| `faf_planos` | plano do ESTADO (sede = capital) | **apagado** — o IBGE ali é a sede, não onde se aplica |
| `parcerias` | fundo estadual e entidade privada | **fica, marcado, fora dos totais** — a entidade está na cidade |
| `obrasgov` | programa guarda-chuva (790 municípios) | **fica, em bloco próprio** — o programa passa por ali |

A pergunta que separa os três: *a linha afirma algo sobre ESTE município?* Se não
afirma nada (o plano do Estado de Goiás é executado em Goiás inteiro), sai. Se afirma
mas não é da prefeitura, fica marcada e fora da conta.

## 1.13. FASE 5 — Fundo a Fundo (o plano de ação por trás do repasse)

A última fonte nova do Comunicado nº 23/2026. O `fns_repasse_faf` já conta o repasse
consolidado por bloco no ConsultaFNS — **o dinheiro que entra**. Esta traz o que o FNS
não publica: o **plano de ação** que justifica o repasse, com diagnóstico, objetivos,
vigência e a decomposição do valor entre emenda, repasse específico, voluntário,
recursos próprios e rendimentos. Uma não substitui a outra.

**Não é só saúde.** O nome sugere SUS, mas o módulo cobre todo repasse fundo a fundo:
os quatro planos de Nova Palma (R$ 413.420,20) são do **Ministério da Cultura**, Lei
Aldir Blanc, com o Fundo Nacional da Cultura como repassador. Um coletor que filtrasse
por saúde perderia os quatro.

⚠️ **O FILTRO ÓBVIO DA FONTE ESTÁ QUEBRADO.**
`/planos-acao?codigo_ibge_municipio_ente_recebedor_plano_acao=` está no Swagger e
devolve **HTTP 500** — medido em 06 **e** 07/09, dias diferentes. O caminho que
funciona tem dois passos: `/programas-beneficiarios` por IBGE (que filtra bem) devolve
os CNPJs, e só então `/planos-acao` por CNPJ.

⚠️ **E O CNPJ NÃO PODE SER ADIVINHADO — é o oposto do módulo de Parcerias.** Aqui o
ente recebedor é a PREFEITURA (`88488358000156` em Nova Palma); lá as propostas do
mesmo município são todas do FUNDO MUNICIPAL DA SAUDE (`12240183000100`). Assumir
qualquer um dos dois erraria em um dos módulos — e erraria calado, devolvendo lista
vazia como se o município não tivesse nada. Por isso a fonte é que diz quem recebe.

Custo: **2 requisições por município** mais 1 por plano para os relatórios de gestão —
que preenchem um buraco conhecido do modelo, já que `prestacao_contas` é dropada a cada
boot e hoje prestação de contas só existe como texto dentro de um campo de situação.

### Erro meu corrigido nesta sessão

Usei o IBGE **3143203** para Monte Sião nas medições de exploração — é **Monte Santo de
Minas**. O correto é **3143401**. Nada no código foi afetado (o coletor lê
`municipios.ibge_code`, que está certo no banco), e as medições feitas via banco — como
a comparação CNPJ × geometria do #408 — estavam corretas. O que precisou de correção
foi a tabela de cobertura do #404 e o relatório em PDF: Monte Sião tem **14 propostas
de Parcerias e 8 projetos com geometria**, não 7 e 15.

**A TELA CHEGOU EM 07/09/2026** (`/dashboard/faf-planos`, `routers/faf_planos.py`),
e o que ela abre é a **decomposição do dinheiro**: quanto daquele repasse veio de
emenda parlamentar, de repasse específico, de voluntário, de recursos próprios e de
rendimento de aplicação. É o número que o ConsultaFNS não publica. Abaixo dela vem
«Por órgão repassador», que existe para desfazer o mal-entendido do nome — no trust
os órgãos mais frequentes são MinC, SENASP (segurança), SPPE (trabalho), MCID e
FNDE; o Ministério da Saúde não aparece no topo.

### ⚠️ E a tela quase nasceu mentindo por um fator de 8

Medindo a fonte para desenhar a tela, o total da carteira do trust deu **R$ 1,42
bilhão** para 20 municípios. O filtro `codigo_ibge_municipio_ente_beneficiario_programa`
devolve todo ente **sediado** na cidade — e a sede do governo estadual é a capital:

| creditado a | ente | valor |
|---|---|---:|
| Goiânia | ESTADO DE GOIAS | R$ 470.381.305 |
| Goiânia | SEC. DE ESTADO DA SEGURANÇA PÚBLICA | R$ 265.232.961 |
| Goiânia | **MUNICIPIO DE GOIANIA** | **R$ 73.789.174** |
| Palmas | SECRETARIA DA SEGURANÇA PÚBLICA (SSP/TO) | R$ 243.681.257 |
| Palmas | ESTADO DO TOCANTINS | R$ 164.825.590 |
| Palmas | **MUNICIPIO DE PALMAS** | **R$ 20.297.831** |

Cerca de **85% do valor era dinheiro estadual**. E não havia o que aproveitar: o IBGE
ali é a SEDE do ente, não onde o dinheiro é aplicado — um plano do Estado de Goiás é
executado no estado inteiro.

O que separa os dois é `descricao_tipo_unidade_ente_plano_acao`, com exatamente dois
valores em toda a base ("Ente Municipal" e "Ente Estadual/Distrital"). O coletor passou
a filtrar por ele (`e_do_municipio`, que devolve `True` no campo ausente — esvaziar a
tela em silêncio seria pior) e `add_faf_esfera_ente.sql` apaga o que já tinha entrado.

É o mesmo erro de chave que este repo já pagou duas vezes: **filtrar município por algo
que descreve onde a entidade fica, em vez de de quem é o dinheiro** — as 379 obras da
UFSM em Santa Maria, os 40.707 planos órfãos de `transferegov_te`.

## 1.14. O filtro que a fonte ignora em silêncio (07/09/2026)

Achado ao construir a tela de Fundo a Fundo, medindo a API para saber o que mostrar.
Os quatro módulos de `api-publica.transferegov.gestao.gov.br` **ignoram calados todo
parâmetro que não reconhecem** — devolvem HTTP 200 com a base nacional inteira,
idêntico a não filtrar:

| consulta | resposta |
|---|---|
| `/parcerias/proposta?cd_ibge_recebedor=4313102` | 11 |
| `/parcerias/proposta?cd_ibge_recebedor**X**=4313102` | **89.400** — HTTP 200 |
| `/fundoafundo/programas-beneficiarios?parametro_que_nao_existe=xyz` | **31.026** — HTTP 200 |

Os filtros que os coletores usam **estão certos hoje** — os cinco foram conferidos com
um valor impossível (`9999999`), que devolve 0 e não tudo. O que assusta é a facilidade
do acidente: eu mesmo, medindo, escrevi `codigo_ibge_municipio_beneficiario_programa`
em vez de `codigo_ibge_municipio_**ente**_beneficiario_programa` e recebi 31.026
beneficiários do Brasil, com o primeiro plano sendo da SECULT do Amapá. Se isso
acontecesse dentro do coletor, o Amapá entraria no banco como Nova Palma, com log de
sucesso.

E o risco não é hipotético: **o Obras.gov já renomeou TODOS os campos numa troca de
host**. Se acontecer aqui, sem guarda a rodada grava o Brasil inteiro.

A defesa: `buscar()`/`_pub_todos()` aceitam `teto_itens`, e toda consulta que estabelece
o vínculo município ↔ dado passa o teto do que é plausível. Acima dele devolvem `None`,
que os coletores já tratam como "não consegui perguntar" e nunca como ausência.
`tests/test_filtro_ignorado_em_silencio.py` lê o código dos três coletores e falha
**nomeando** a consulta por IBGE/CNPJ que esquecer o teto — testado por mutação.
Consulta por id do pai (`id_proposta`, `id_plano_acao`) fica sem teto de propósito.

## 1.15. A ÁREA ÚTIL VIROU UMA SÓ (07/09/2026)

Pedido do dono, com print e setas desenhadas por cima: *"cada um segue um tamanho, e isso
não pode; tem que aproveitar a tela, tem que padronizar o layout e dimensão e margens e
tamanho"*. A referência que ele mandou é o **Painel de Indicadores**.

**O que havia.** `dashboard/layout.tsx` tinha **três regimes de largura** convivendo:
`telaCheia` (largura toda), `telaLarga` (`max-w-[1600px]`, uma lista de rotas) e o padrão
(`max-w-7xl`, 1216px úteis). Numa janela de 1920 isso dava **três margens esquerdas
diferentes** conforme o item de menu clicado — ~32px no Painel, ~57px no TransfereGov e
~185px em todo o resto. Trocar de tela empurrava o conteúdo lateralmente.

**O que ficou.** Um `PADDING_PADRAO = "px-4 py-5 sm:px-6 lg:px-8"`, sem `max-w`, para toda
tela que não seja `telaCheia`. `TELAS_LARGAS` **não existe mais** — não reintroduza uma
lista de exceções de largura; ou o padrão muda para todas, ou volta o defeito.

⚠️ A justificativa do `max-w-7xl` era **leitura de parágrafo** (~75 caracteres por linha), e
ela não se sustentava: o PACTHA não tem tela de texto corrido, e onde há parágrafo ele já
traz `max-w-3xl` PRÓPRIO (Obras, Emendas Federais, Gestão, Auditoria) — que é onde o limite
pertence. Travar a página inteira custava ~700px de dado em todas as outras.

⚠️ **`telaCheia` copia o `PADDING_PADRAO` por conta própria** (Painel e Agendamentos). Quem
entrar lá assume o padding com as MESMAS classes.

**As duas telas novas do TransfereGov saíram junto** (Parcerias e Planos de Ação, nascidas
nas fases 4 e 5 acima). Elas tinham três defeitos que o container não explicava:

- `p-4 sm:p-6` no wrapper da página **por cima** do padding do container — margem dobrada.
  As de Obras e Emendas Federais tinham o mesmo, e também saiu.
- **`<Bloco>` sem `className="p-3"`**: `.bi-card` é só fundo, borda, raio e sombra, e o
  respiro sempre veio da classe que cada tela escrevia à mão. Sem ela, cartão interno colado
  na borda do cartão de fora. **Agora o `Bloco` injeta `p-3` quando o `className` não traz
  padding nenhum** — quem quer zero escreve `p-0` (ver `rm/[id]`).
- **`<Campos>` sem `cols`**: o default era *uma coluna por campo*, e essas telas tinham 10 e
  11 — onze colunas de ~150px, tudo em reticências. **O default passou a ter teto de 5**, e
  as duas telas pedem `cols={4}`.

E o **item de lista voltou a nascer fechado**: as duas despejavam todos os campos mais o
`diagnostico`/`objetivos` inteiros (dois parágrafos de texto legal, na Aldir Blanc) em cada
linha. Abrir no clique é o gesto que Obras e Emendas Federais já usavam.

## 1.16. O cartão do parlamentar: sete campos fixos viraram selos (07/09/2026)

Segundo pedido do dono no mesmo dia, com print: *"tem campos que ficam vazios e são
mostrados mesmo assim e por isso toma um espaço maior... não seria melhor manter o mesmo
padrão das do TransfereGov e Convênios, que têm tags mostrando do que se trata?"*

O cartão fechado de cada parlamentar trazia uma `<Campos cols={3}>` com **as sete fontes
sempre**: convênios estaduais, TransfereGov, emendas estaduais, Transferência Especial,
Seleção PAC, FNS e emendas federais. Como quase todo parlamentar tem uma ou duas, cinco
saíam como «—» — **três linhas de cartão para exibir, em média, dois números**.

Agora são **selos, só das fontes que têm lançamento**, em `FONTES` (ordem fixa, no topo de
`parlamentares/page.tsx`). O cartão fechado passou de três linhas para uma.

⚠️ **É uma reversão consciente.** Estes selos já foram chips coloridos, e a grade nasceu
para consertar dois defeitos deles. O primeiro — cor gasta à toa — continua consertado: o
selo é neutro, como manda a peça. O segundo é o que se paga: a varredura vertical vira
**ordem** fixa em vez de **posição** fixa. Foi decisão do dono, vendo o resultado.

⚠️ **Rótulo é nome inteiro** ("Transferência Especial", não "Transf. especial"): a
abreviação existia porque a coluna da grade tinha ~150px, e o selo se ajusta ao texto. É
também o que faz o resumo casar com o título da seção que aparece ao abrir a setinha.

⚠️ **O valor total ganhou rótulo** ("Valor total dos lançamentos", curto no celular): era um
número solto no canto de um cartão que, aberto, mostra o valor de *cada* lançamento.

⭐ **E o furo que isso revelou, fechado no mesmo dia.** «Emendas Federais» contava no
resumo e no `total_lancamentos`, mas `GET /parlamentares/detalhe` devolvia **seis** listas,
não sete: quem abria a setinha não achava a seção, o `total_geral` do detalhe não batia com
o da lista, e o parlamentar que **só** tem emenda federal — 45% da carteira nos municípios
medidos — recebia **404** e o cartão abria com erro. Não era regressão da troca por selo; a
grade tinha o mesmo furo, só menos visível. Fechado com o bloco `ef_list` em
`routers/parlamentares.py::detalhe` mais um `GrupoFonte` na tela.

⚠️ **O SQL da sétima fonte repete os dois `NOT EXISTS` do agregado** (`id_proposta_siconv` e
`split_part(te.emenda,'-',1)`), e eles não são opcionais: esta tabela lê a mesma base que já
alimenta TransfereGov e Transferência Especial. Sem o desconto, a mesma emenda apareceria em
duas seções e o total do detalhe passaria o do cabeçalho — que é onde o gestor confere.

## 1.17. Os 47 títulos viraram uma peça só (07/09/2026)

Fecha o print da manhã. Pedido do dono: *"deixe todos em tamanho 24px e sempre tenha um
ícone para cada título; fica bem bonitinho os que têm — Regularidade tem um escudinho,
Obras tem um capacetinho, Parlamentares já não tem. Sempre ter um fica bem legal, mesmo que
repetir alguns não tem problema."*

Havia **47 `<h1>` escritos à mão**, divergindo em duas coisas ao mesmo tempo: **tamanho**
(42 em `text-2xl`, 5 em `text-[18px]` — as telas mais novas) e **ícone** (15 tinham, 32
não, sem regra: telas irmãs, feitas na mesma semana, umas com e outras sem).

Agora são **45 `<TituloTela>`** (`components/TituloTela.tsx`), que decide o tamanho e busca
o ícone em `lib/icones-tela.ts` **pela rota**. Tela nova nasce certa sem ninguém lembrar de
nada.

⚠️ **Por que um mapa e não o ícone do menu.** Seria mais elegante ler de `NAV_ITEMS`, e foi
a primeira tentativa — mas **só 15 das 47 rotas têm ícone lá**: folha dentro de grupo
(FEDERAIS, ESTADUAIS, Saúde, Obras) não tem, quem tem é o grupo. Ler do menu daria o mesmo
`Landmark` às onze telas federais, que é o oposto do pedido.

⚠️ **Repetir é permitido, e às vezes é o certo:** `BadgeDollarSign` marca as três telas de
emenda (federal, estadual, RS) e `HeartPulse` as quatro de saúde — a repetição agrupa
visualmente o que o menu já agrupa.

⚠️ **A peça é SÓ o `<h1>`, de propósito.** Embrulhar o cabeçalho inteiro (título + subtítulo
+ botões + selo de frescor) viraria uma pilha de props opcionais, e a primeira tela que não
coubesse voltaria a escrever `<h1>` à mão.

⚠️ **Ícone de título nunca é colorido.** Três telas pintavam o seu (Acordo FES em vermelho
"porque é saúde/dívida"; Telemetria e Status dos Dados no acento) — decoração com a cor que
nesta identidade significa alerta. Agora é `--bi-muted` para todas, garantido pela peça.

⚠️ **`createElement` e não `<Icone />`** dentro da peça: em JSX, o lint do React Compiler lê
a variável PascalCase atribuída no render como *componente criado no render* e acusa erro.
Onde o ícone chega por **prop** (`BlocoHead`, `GrupoFonte`) o JSX normal funciona.

**Dois `<h1>` ficaram de fora, e devem ficar:** o do renderizador de markdown das respostas
da IA (`ai/page.tsx`) e o do painel ATIVO em Painéis Municipais, que usa o ícone do próprio
painel.

## 2. ESTADO ATUAL (2026-09-04)

**São CINCO tenants em produção**, todos do mesmo código, cada um com containers e banco próprios:

| Tenant | App | API |
|---|---|---|
| **Freitas** | https://pactha-54-232-208-118.sslip.io | https://pactha-api-54-232-208-118.sslip.io |
| **Trust** | https://pactha-trust-54-232-208-118.sslip.io | https://pactha-trust-api-54-232-208-118.sslip.io |
| **Monte Sião/MG** | https://montesiao.mg.pactha.com.br | https://pactha-montesiao-mg-api-54-232-208-118.sslip.io |
| **Santa Maria/RS** | https://santamaria.rs.pactha.com.br | https://pactha-santamaria-rs-api-54-232-208-118.sslip.io |
| **Nova Palma/RS** | https://pactha-novapalma-rs-54-232-208-118.sslip.io | https://pactha-novapalma-rs-api-54-232-208-118.sslip.io |

⚠️ **Santa Maria (16/08/2026) é o 4º tenant e o primeiro banco criado DO ZERO** — os três
primeiros vieram migrados do Neon. Ele nasceu só com Santa Maria/RS (IBGE 4316907) e as
coletas federais. **Nova Palma (01/09/2026) é o 5º e o segundo banco do zero** — nasceu só
com Nova Palma/RS (IBGE 4313102) e expôs um bug de **ORDEM** nas migrations
(`add_detalhe_pagina_rodizio.sql` alterando tabela criada depois dela em `MIGRATION_FILES`),
hoje guardado por `tests/test_migrations_ordem_tabela.py`. Ele ainda está **sem brasão** de
propósito: `NEXT_PUBLIC_CLIENT_LOGO` e `RM_LOGO` vazios — subir com logo errado é pior que
subir sem.

> ⚠️ **Este parágrafo dizia "nenhuma fonte do RS existe em código ainda". Isso venceu.**
> Era verdade em 16/08; hoje coletam CHE (`che_rs.py`), convênios da CAGE
> (`convenios_rs.py`), Consulta Popular (`consulta_popular_rs.py`) e o DOE-RS
> (`services/diario_rs.py`), com Scheduled Task ativa. Em 02/09/2026 entraram
> ainda **SICONFI/CAPAG** (federal, nacional) e **TCE-RS/LicitaCon** — este
> último pronto mas dependente de liberação de IP (ver `docs/fontes-rs/`).
> O que segue inerte é o **FPE-RS**, esperando credencial PCPRS, por decisão.
>
> ⚠️ **Mas "inerte" escondeu um cron errado por 18 dias.** O portal do FPE só atende
> **seg–sáb, 7h–22h30 BRT** (fora disso: HTTP 500), e as duas tasks estavam agendadas às
> **02:04 e 02:34 BRT**, com `* * *` incluindo domingo. Ninguém viu porque o coletor sai
> antes de tocar no portal e grava `success` por falta de credencial. No dia em que a
> credencial PCPRS entrasse, os dois tenants passariam a falhar todo dia e o sintoma
> pareceria coletor quebrado. Corrigido em 04/09 para `14 14 * * 1-6` (santamaria) e
> `44 14 * * 1-6` (novapalma). **Fonte com janela de funcionamento é restrição de
> agendamento — anote no cron, não só no docstring.**

Os cinco bancos já estão **populados com dados reais** (a migração vinda do Neon foi concluída — não é mais schema+seed). Login seed só vale em banco novo: `super-admin@alavank.com.br`, com senha ALEATÓRIA por tenant impressa no console do primeiro boot (ou via `ADMIN_PASSWORD`) — pede troca no 1º acesso.

**⚠️ INVERTIDO EM 09/08: um merge na `main` DEPLOYA os cinco clientes, sozinho.** As 15
aplicações seguem `build_pack = dockerimage`, mas o job `deploy` do CI avança a tag e
dispara o deploy ao fim de cada build (API primeiro com migrations confirmadas; worker do
mesmo tenant só em janela sem coleta em voo; falha = rollback de tag + run vermelho).
`is_auto_deploy_enabled` agora está **false** nas 9 (o webhook recriava containers com a
tag antiga e matou coleta em voo). Mecânica e provas em [`INFRA.md`](INFRA.md) §2 e nos
próprios workflows. **Tratar todo merge na `main` como um deploy em produção.**

**Carteira Freitas = 44 municípios ativos** (lista oficial de 09/08; 18 ex-clientes com
`active=false` e histórico preservado — NUNCA deletar município, desativar).

---

## 3. INFRA NO COOLIFY (como mexer)

Resumo; o detalhe completo (uuids de todas as aplicações, bancos, crons por tenant) está no **[`INFRA.md`](INFRA.md)**.

- **Servidor:** **AWS Lightsail `54.232.208.118`** (sa-east-1a, São Paulo). t3.large: 2 vCPU / 7,6 GB RAM / 160 GB SSD. **Burstable, baseline 30% (~0,6 vCPU sustentado)** — hospeda mais 10 projetos além do PACTHA. **Não paralelize trabalho pesado.**
- **Instância Coolify:** `http://54.232.208.118:8000` — API REST em `http://54.232.208.118:8000/api/v1`. Versão v4.1.2.
- **SSH:** `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118`.
- **Token da API do Coolify:** NÃO está neste arquivo (é segredo). O usuário fornece (formato `36|xxxx`). Use `Authorization: Bearer <TOKEN>`. **Rotacione periodicamente.**
- **GitHub App (source):** `alavank-coolify` — já dá acesso ao repo privado `alavank/pactha`. Use o `github_app_uuid` dele ao criar apps.

**Projeto Coolify `pactha`** — **um environment por tenant** (`production` está vazio),
**15 aplicações + 5 bancos** (o `montesiao-mg-painel` foi removido).

> ⚠️ **A tabela de UUIDs saiu daqui em 05/09/2026.** Ela estava duplicada — a mesma lista
> vivia neste arquivo e no `INFRA.md`, que é a fonte de verdade de infra. Duas cópias de
> identificador de deploy divergem no dia em que um app é recriado, e aí ninguém sabe qual
> está certa. **Está em [`INFRA.md`](INFRA.md) §3 e §9**, e o workflow de deploy carrega a
> sua própria cópia na variável `TENANTS` do GitHub Actions.

Builds: API = `backend/Dockerfile.api` (base `/`) · Frontend = `frontend/Dockerfile` (base `/frontend`, standalone) · Worker = `backend/Dockerfile.scraper` (PID 1 = `tini` + `reaper.sh`, que mata ingestão >1h e Chromium órfão; crons via Scheduled Tasks). Bancos: `postgres:16-alpine`, db/user `pactha`, porta 5432, host = uuid do resource.

**Segredos** (`JWT_SECRET`, `COFRE_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `CONTROL_TOKEN_BOOTSTRAP`, chaves VAPID do Painel): estão **nas env vars do Coolify, por tenant** (recupere com a API — ver §7). A senha do Postgres também está no `internal_db_url` do resource DB (`GET /databases/<uuid>`). **Nunca copie a `COFRE_KEY` de um tenant para outro.**

**Scheduled Tasks:** cada worker tem as suas, no desenho de 09/08: **lock compartilhado
`/tmp/scraper.lock`** (sigcon/lote/cagec nunca simultâneos no tenant) + agendas
entrelaçadas + rodadas fatiadas com rodízio. **A fonte de verdade dos horários é o
Coolify** (a tabela do `INFRA.md` §5 virou descrição de desenho; `docs/CRON_SETUP.md`
está histórico). Regra das margens e proibição de editar comando via PowerShell
interpolado: [`INFRA.md`](INFRA.md) §5.

---

## 4. DECISÕES DE ARQUITETURA (e POR QUÊ) — não desfazer sem motivo

1. **Mantido Python/FastAPI (não migrou p/ Node).** A parte difícil é o scraping: Playwright p/ portais JSF/SAML (SIGCON, TransfereGov), curl_cffi anti-Cloudflare (SIMEC), e a máquina de sessão gov.br (SSO/SAML/reCAPTCHA). Reescrever isso = refazer o pedaço mais frágil, sem ganho.
2. **Scraping continua httpx+Playwright+curl_cffi (NÃO usar Scrapy).** O sistema é integração de dados abertos (CSV/JSON) + 2 portais JS-pesados, não crawling de HTML em escala. Scrapy não resolveria e pioraria o caso anti-bot do SIMEC.
3. **Isolamento por deploy, não por código.** O código é single-tenant; cada cliente é um conjunto separado de containers + banco, diferenciado por env vars (`INSTANCE_SLUG`, `DATABASE_URL`, `NEXT_PUBLIC_CLIENT_LOGO`, `NEXT_PUBLIC_CLIENT_SUBTITLE`). Foi removido o co-branding via `NEXT_PUBLIC_TENANT`. **"Freitas" NÃO é um recurso do produto — é uma consultoria cliente** (prompt de IA, "padrão Freitas" nos RMs, usuários `@freitas.com.br`).
4. **Rename PACTA→PACTHA completo:** cookies (`pactha_access/refresh/csrf`), localStorage (`pactha_token/user/theme/...`), tema daisyUI (`pactha`/`pactha-dark`), issuer JWT (`pactha-api`), prefixo service-token (`pactha_st_`), email admin, extensão Chrome, `package.json` name. **Tabelas do banco NÃO eram "pacta"** (`convenios_estadual` etc.) → schema intacto.
5. **Gatilho on-demand virou FILA no Postgres.** O `POST /api/convenios/refresh-sigcon` (que no repo original chamava a GraphQL `serviceInstanceRedeploy` do Railway) grava na tabela `scraper_jobs`; `backend/ingestion/run_queue_sigcon.py` consome, via Scheduled Task `queue-sigcon`, com dedup pending/running. CORS é env-driven (`main.py`).
6. **`setup_db.py` roda no BOOT da API** (`backend/services/startup.py`, dentro de `run_migrations`, antes das migrations incrementais). Idempotente (CREATE IF NOT EXISTS + seed só se `users` vazio). No Coolify não há passo manual "rodar setup_db uma vez" — isto se auto-cura em deploy novo.
7. **Frontend faz proxy same-origin de `/api`.** `rewrites()` em `frontend/next.config.ts` repassa `/api/:path*` para o host interno da API (`API_PROXY_TARGET`, **build-time**), e a API não precisa ser same-site com o front. Com isso cookies httpOnly + CSRF + refresh silencioso funcionam. Ver §5.

---

## 5. ARMADILHAS / GOTCHAS (leia antes de debugar)

- **A máquina é burstable (baseline 30%).** Não rode scraping paralelo (`SIGCON_CONCURRENCY=1`), não alinhe os crons dos 5 tenants, não rebuilde os apps de uma vez. Sintoma de estouro: tudo no host fica lento ao mesmo tempo, não só o PACTHA.
- **Coolify STRIPPA o path do domínio.** Se você setar o domínio de um app como `host/api`, o Coolify tira o `/api` antes de chegar no container (testado: `host/api/health`→404, `host/api/api/health`→200). Por isso a API tem **subdomínio próprio SEM path**, e o caminho normal do usuário é o proxy do Next (`API_PROXY_TARGET`).
- **`*.sslip.io` é public suffix** → `pactha-...sslip.io` e `pactha-api-...sslip.io` são **cross-site** entre si; cookies `SameSite=Lax` httpOnly não trafegam entre eles. É exatamente por isso que existe o proxy same-origin no Next (decisão 7). **Se alguém apontar o front direto no subdomínio da API (`NEXT_PUBLIC_API_URL` absoluto), o refresh silencioso quebra e volta o re-login a cada ~60min.**
- **`API_PROXY_TARGET` e `NEXT_PUBLIC_*` são BUILD-TIME.** Mudar o valor no Coolify sem rebuildar o frontend não tem efeito nenhum. Marque `is_build_time:true` e redeploy.
- ~~**`transferegov_propostas` é criada tarde** nas migrations~~ — **RESOLVIDO.** A tabela foi movida para o `setup_db.py` (`CREATE TABLE IF NOT EXISTS`, hoje na linha 105), que é exatamente o conserto que este parágrafo propunha. **A lição fica, porque a classe do bug voltou:** migration que ALTERA tabela criada mais tarde em `MIGRATION_FILES` só quebra em **banco novo do zero** — invisível nos bancos herdados. Foi assim com `transferegov_propostas` e de novo com `add_detalhe_pagina_rodizio.sql` quando o Nova Palma nasceu (01/09). Hoje há guarda automática: `backend/tests/test_migrations_ordem_tabela.py`. São **105** migrations registradas, não 22.
- **COFRE_KEY:** o Cofre e as sessões gov.br são cifrados com AES-256 usando a env `COFRE_KEY` (`backend/services/crypto.py`). Se a chave mudar, `decrypt()` volta `""` **silenciosamente** — sem erro, sem log. **Cada tenant tem a sua**; trocar ou cruzar chaves destrói o Cofre daquele cliente.
- **must_change_password=True** no admin seed → o 1º login redireciona pra `/change-password`. Normal.
- Worker aparece como `running:unknown` no Coolify (roda o reaper, sem healthcheck). Normal. Frontends sem healthcheck também.
- **Chromium órfão.** O worker já roda com `tini` + reaper (`backend/reaper.sh`) e os crons com `flock`+`timeout`, justamente porque Chromium pendurado comia a RAM do host. Não remova esses wrappers.
- **O SISMOB é API pública, não scraping.** `sismobcidadao.saude.gov.br/api/public/obras`
  responde JSON sem token e sem login. Três armadilhas, todas silenciosas: (1) a
  **listagem e o detalhe usam nomes diferentes para o mesmo campo**
  (`propostaId`/`coSeqProposta`, `situacaoObra`/`dsSituacaoObra`…), então um
  `{**listagem, **detalhe}` grava `NULL` calado; (2) **IBGE de 7 dígitos devolve 200 com
  zero resultado**, indistinguível de município sem obra; (3) o campo da 1ª parcela tem
  **typo do próprio MS** (`vlPrimeraParcela`, sem o "i"). E o sinal de obra parada **não é
  `dtAtualizacao`** — é o timestamp das fotos. Tudo anotado em
  `backend/ingestion/sismob_obras.py`.
- **O Obras.gov.br tem DOIS hosts, e só um funciona daqui.** `api.obrasgov.gestao.gov.br`
  devolve **429 na primeira requisição** vinda da VPS; use
  **`api-publica.obrasgov.gestao.gov.br`**, que responde 200 em 0,13 s. Três armadilhas
  silenciosas: (1) o **filtro territorial não existe** — `codigo_ibge` devolve o estado
  inteiro com HTTP 200, e o recorte é feito em memória; (2) **o município sai do CNPJ,
  nunca do nome** (por nome, 379 obras da UFSM viram obras da prefeitura de Santa Maria);
  (3) **a fonte manda acento codificado duas vezes** (latin-1 lido como UTF-8), e o
  conserto na ingestão precisa desistir quando a reinterpretação não melhora — senão
  corrompe 32.000 obras para arrumar 2. E **a data efetiva não classifica nada**: vem
  vazia em 100% das obras. Detalhe em [`INFRA.md`](INFRA.md) §5 e em
  `backend/ingestion/obrasgov.py`.
- **Não existem "1ª, 2ª e 3ª parcelas" no fundo a fundo.** A norma vigente (Portaria de
  Consolidação 6/2017, Título IX) é **parcela única**; obras antigas vieram 20%+80%. O
  marco de 90% **não existe** (o de 30% sim). E a prestação de contas é o **Relatório
  Anual de Gestão** (LC 141/2012), não um "relatório final".
- **O CAGEC NÃO fica dentro do SIGCON-MG.** Perder tempo procurando no portal logado é fácil: a palavra "CAGEC" não aparece uma vez sequer no HTML do sigconv2 nem no menu de 29 itens. Ele tem portal próprio (`cagec.mg.gov.br/convenente-web`) e a consulta é **pública** — basta o CNPJ, não precisa de credencial. Duas armadilhas do portal (ambas fazem a busca *parecer* vazia): a página contém a frase "clique no botão [PESQUISAR]", então seletor por texto casa com a **instrução** e o clique não faz nada; e o cabeçalho do grid usa `th`/`.z-listheader` — fora do seletor de células ele some, e sem cabeçalho não dá para casar coluna por rótulo. Está tudo anotado em `backend/ingestion/cagec_scraper.py`.
- **O detalhe da irregularidade vem do CRC, e o CRC SAI para município irregular.** Errei isso na primeira versão (assumi que só município regular emitiria) e a diferença é grande: a linha da busca só diz "Irregular", enquanto o botão **"Emitir CRC"** da mesma linha baixa um PDF com as ~24 obrigações uma a uma, **cada uma com situação e data de validade**, mais CADIN-MG, SIAFI e o vencimento do mandato. É o que permite dizer "seu FGTS venceu em 29/07" em vez de "você está irregular". Duas armadilhas do PDF: o cabeçalho tem `SITUAÇÃO: Irregular`, que casa como se fosse item (só ler depois de `DOCUMENTAÇÃO`), e a quebra de página parte um item ao meio (há remendo dedicado).
- **Espera fixa no portal do CAGEC falha 1 em 4.** O `wait_for_timeout` fixo depois do PESQUISAR lia o grid ainda vazio e reportava **"CNPJ não encontrado no CAGEC"** — sintoma enganoso, parece que o município não existe no cadastro. Use espera adaptativa (poll até a linha aparecer). Vale para qualquer postback do ZK.

---

## 6. PENDÊNCIAS

> 📍 **O backlog por estado vive em [`docs/BACKLOG_POR_ESTADO.md`](docs/BACKLOG_POR_ESTADO.md).**
> Ele confere o plano da auditoria de 17/08/2026 contra o repositório (conferência de
> 25/08: **o plano não foi executado**) e lista, na ordem de prioridade do dono
> — **MG → RS → GO → ES → TO** —, o que falta em cada estado, com arquivo/linha já
> verificados. As decisões da Onda 0 e o achado do CAGEC (falha em massa em 17-18/08)
> estão lá. Ler antes de abrir frente nova de cobertura estadual.


### 6.1 Domínios definitivos (`*.pactha.com.br`)
Faltam **três**: `freitas`, `trust` e `novapalma-rs` ainda respondem só por `*.sslip.io`. Monte Sião e Santa Maria já têm domínio próprio (`montesiao.mg.pactha.com.br`, `santamaria.rs.pactha.com.br`), assim como a landing (`pactha.com.br`) e a Central de Comando (`control-center.pactha.com.br`). Falta decidir/criar os DNS `A` → `54.232.208.118` para os apps dos clientes e trocar os domínios no Coolify (`PATCH /applications/<uuid>` + redeploy). Lembre de ajustar `FRONTEND_URL`/`CORS_ORIGIN_REGEX` na API e rebuildar o frontend (env build-time).

### 6.2 Secrets opcionais por tenant (features ficam OFF até setar)
`ANTHROPIC_API_KEY` (módulo IA — hoje só `montesiao-mg-api` tem). Setar via `PATCH /applications/<api_uuid>/envs/bulk` + redeploy. (`TELEGRAM_BOT_TOKEN` e `TELEGRAM_WEBHOOK_SECRET` saíram desta lista em 05/09/2026 com o módulo — nunca foram setados em tenant nenhum.)

**`PORTAL_TRANSPARENCIA_API_KEY`** (emendas federais — a EXECUÇÃO). Vai no **worker**,
não na API: quem consulta a CGU é o coletor. Decisão de 06/09/2026: **só em
`novapalma-rs` e `montesiao-mg`**, porque a chave fica vinculada ao **CPF de quem a
cadastrou** e com cinco tenants a chave de uma pessoa responderia pelas consultas de
todas as prefeituras (ver `docs/fontes-rs/CREDENCIAIS.md` §1).
⚠️ **A CARTEIRA de emendas NÃO depende dela** — sai do dump aberto `siconv_emenda.zip`
casado por CNPJ, e roda nos cinco. Sem a chave a rodada sai `success` com a nota
"execucao CGU nao coletada", e a tela diz isso em vez de mostrar R$ 0,00.
⚠️ Env nova só vale **depois de reiniciar o container**, e cada aplicação no Coolify
carrega **duas** entradas por env (produção e preview) — é a mesma armadilha do
`AUTHZ_MODO`. Confira no **log da rodada**, não no painel.
Desligar = apagar a env + restart. Volta ao estado honesto, sem deploy.

Credencial do **SIGCON-MG** (uma por município, no Cofre com `sistema='SIGCON-MG'` /
`automation_key='sigcon'`): sem ela o `sigcon` roda e não traz nada — e agora grava
`success` com a nota "sem credenciais" (não alarma; regra do dono: credencial não trava
o jogo). **O CAGEC não precisa de credencial** — consulta pública.

Estado em 09/08: Monte Sião ok · **Freitas: 24 credenciais ativas** p/ 23 municípios
antigos; **2 PAUSADAS aguardando reset do dono** (Piracema e Ribeirão das Neves —
portal respondeu "USUÁRIO REVOGADO"; fluxo "Esqueci minha senha" resolve) e **21
municípios novos SEM credencial** (pedir à Freitas) · **Trust: ZERO credenciais
SIGCON** apesar de 7 municípios MG (pedir ao cliente). Pausar credencial = trocar
`sistema` p/ valor fora de `SIGCON%` + `automation_key=NULL` (reversível).

### 6.3 Deploy (automático desde 09/08)
Merge na `main` = deploy nos 5 tenants via CI (ver §1.5 e [`INFRA.md`](INFRA.md) §2).
`is_auto_deploy_enabled = false` (webhook desligado de propósito). Deploy manual
para rollback: repontar `docker_registry_image_tag` + `GET /deploy?uuid=`. Pendências do
plano de médio prazo: **M1** (executor de fila por fonte×município — substitui os crons
com teto de 1h) e **M5** (host de scraping dedicado quando a carteira crescer).

### 6.4 Separação de papel no banco para a trilha de auditoria — **decisão do dono**
A `audit_log` já é append-only no banco (gatilho) com selo encadeado e conferência na tela
(botão **Verificar integridade** em `/dashboard/auditoria`). Falta o passo que só o dono decide:
a aplicação hoje roda como `pactha`, **dona de tudo** — ou seja, com poder de derrubar o próprio
gatilho que a impede de mexer na trilha. O ideal é um papel `pactha_app` com
`REVOKE UPDATE, DELETE, TRUNCATE ON audit_log`.

O **SQL pronto** está comentado no fim de `backend/migrations/add_auditoria_imutavel.sql` (seção
"CAMADA 3"); o **passo a passo por tenant, o teste, o rollback e o modelo de ameaça** (o que a
corrente de selos garante e o que ela **não** garante) estão em
[`docs/AUDITORIA_IMUTABILIDADE.md`](docs/AUDITORIA_IMUTABILIDADE.md). Duas coisas de lá que valem
repetir aqui:

- **Não precisa de mudança de código.** Todo o DDL do boot roda em `DATABASE_URL_SYNC`
  (`services/startup.py`) e o runtime da API em `DATABASE_URL` — basta apontar cada uma para um
  papel. ⚠️ Mas `DATABASE_URL_SYNC` **precisa estar preenchida antes**: onde ela está vazia o
  fallback usa a própria `DATABASE_URL`, e trocar só essa faz as migrations rodarem sem
  privilégio de DDL e a aplicação sobe quebrada.
- **Comece por `freitas` ou `trust`, nunca por `montesiao-mg`** (prefeitura com uso real).

---

## 6.5. ABRIR CLIENTE NOVO

**Se o pedido for "cria um cliente novo" / "replica a instância para X": leia
`PROVISIONAR_CLIENTE.md` e FAÇA AS PERGUNTAS DE LÁ ANTES de tocar em qualquer
coisa.** Tipo de cliente (cidade / assessoria / consórcio), nome, UF, IBGE de 7
dígitos e quais credenciais já existem.

Monte Sião é base de **desenho**, não de dados: nenhum dado dele vai para o tenant
novo. O cliente novo nasce com as três contas de super admin e o município que
vier em `MUNICIPIO_NOME` / `MUNICIPIO_IBGE` / `MUNICIPIO_UF` — mais nada.

## 7. OPERAÇÕES COMUNS (Coolify API v1)

`B=http://54.232.208.118:8000/api/v1` · header `Authorization: Bearer <TOKEN>`

- **Redeploy:** `POST $B/deploy?uuid=<app_uuid>&force=false` → devolve `deployment_uuid`. Status: `GET $B/deployments/<deployment_uuid>` (`status`: queued/in_progress/finished/failed). **Um app por vez.**
- **Logs do app:** `GET $B/applications/<uuid>/logs?lines=120`.
- **Setar env (bulk):** `PATCH $B/applications/<uuid>/envs/bulk` body `{"data":[{"key":..,"value":..,"is_build_time":bool,"is_preview":false}]}`. ⚠️ o POST simples `/envs` **não aceita** `is_build_time` (use o bulk). `NEXT_PUBLIC_*` e `API_PROXY_TARGET` precisam `is_build_time:true`.
- **Mudar domínio:** `PATCH $B/applications/<uuid>` body `{"domains":"https://..."}` + redeploy.
- **Scheduled Tasks:** `GET/POST $B/applications/<worker_uuid>/scheduled-tasks` (POST body `{name,frequency,command}`); `PATCH .../scheduled-tasks/<task_uuid>` p/ `{timeout}`.
- **DB status/URL:** `GET $B/databases/<uuid>` (campos `status`, `internal_db_url`).
- **Abrir o banco na mão:** `ssh -i ~/.ssh/coolify_localhost root@54.232.208.118` e `docker exec -it <db_uuid> psql -U pactha -d pactha`.
- **Rodar um scraper na mão:** dispare a Scheduled Task correspondente no worker do tenant (ou `POST /api/convenios/refresh-sigcon` autenticado → enfileira, e a task `queue-sigcon` consome em ≤30min). Lembre: scrapers com login (SIGCON, FNS) só produzem dados se o **Cofre daquele tenant** tiver credenciais.

---

## 8. AO MEXER NO CÓDIGO, LEMBRE

Uma alteração aqui vai para **os cinco clientes**. Antes de commitar:

- Migration nova precisa ser **idempotente** e rodar limpa nos cinco bancos (ela executa no boot da API) — **e num banco criado do zero**, que é onde erro de ordem aparece (ver §5).
- Feature que depende de env var nova: ou tem default seguro, ou você seta a env nos **cinco** resources.
- Nada de aumentar concorrência de scraping "porque tá lento" — ver §5, a CPU é compartilhada com 10 outros projetos.
