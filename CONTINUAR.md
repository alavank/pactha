# CONTINUAR.md — Handoff PACTHA (leia isto primeiro)

> Documento de contexto para a **próxima sessão de IA** (Claude Code) que for continuar este projeto.
> É **auto-contido**: assuma que você (IA) não tem memória das sessões anteriores. Tudo que precisa está aqui.
> Última atualização: 2026-09-07.
>
> 📍 Para servidor, URLs, uuids, bancos e operações no Coolify, a fonte de verdade é o
> **[`INFRA.md`](INFRA.md)** na raiz. Este arquivo cobre o *projeto*; o `INFRA.md` cobre a *infra*.

---

## 1. O QUE É ISTO (em 30 segundos)

**PACTHA** = sistema de **monitoramento de convênios e transferências governamentais** para municípios e assessorias (MG/ES/GO/RS). Módulos: SIGCON-MG (convênios estaduais), TransfereGov, Emendas, Parlamentares, CAUC, Acordo FES, FNS, SIMEC/PAR, **Obras** (SISMOB + Obras.gov.br/CIPI), IA (Claude), DOU-MG, Relatório de Monitoramento (RM), Documentos, Cofre de Senhas (AES-256), Telegram, extensão Chrome de captura gov.br, Painel de Indicadores (BI, nos 5 tenants) com Modo Tela/links públicos, selos de frescor por tela e watchdog de coleta. São **23 fontes oficiais** (o `CLAUDE.md` mantém a contagem em dia).

- **Frontend:** Next.js 16 (App Router) + Tailwind v4 + daisyUI + shadcn. Pasta `frontend/`.
- **Painel (pasta `painel/`):** removida do repo em 12/09/2026 — o BI virou módulo do frontend principal (`/dashboard` + `/tela`).
- **Backend:** Python 3.12 FastAPI (uvicorn). Pasta `backend/`. Tudo prefixado `/api`.
- **Banco:** PostgreSQL 16 puro (SQLAlchemy async+asyncpg na API; psycopg2 nos scrapers/migrations).
- **Scraping:** httpx + Playwright (Chromium) + curl_cffi. Pasta `backend/ingestion/`.

**Este repo (`alavank/pactha`) é um FORK PRÓPRIO** do repo original `MattMatiins/PACTA` (do Matheus). O usuário (alavank) renomeou tudo de "PACTA" → "PACTHA" e a stack roda em **Coolify + Postgres puro na AWS Lightsail** (ver `INFRA.md`).

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
   tenants em duas ondas (todas as APIs → migrations confirmadas → cada worker assim que
   ficar sem coleta em voo, janela olhada em paralelo; ver INFRA.md §4). Auto-deploy
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
   Canais do alerta (log, `watchdog_historico`, webhook, Telegram): §1.22.
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

**Os pagamentos ficaram na SPA nesta fase**, e isso foi **desfeito em 14/09/2026** (ver
§1.23). A cadeia DH → OP/OB inteira existe na API oficial. Da SPA sobrou só o que ela
publica sozinha: o CPF do ordenador/gestor e o histórico de eventos da OP.

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

✅ **O host novo responde à VPS.** A pendência era rodar
`scripts/reconhecimento_fontes_vps.sh` lá, porque as medições tinham saído de IP
residencial. A própria produção respondeu: a task `transferegov-te` roda da VPS nos seis
tenants desde 07/09, e as execuções de 13 e 14/09 no Coolify deram `success`, com 0
falhas na Freitas em 13/09.

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

**O escopo foi cortado por custo em 07/09 e voltou em 15/09 (§1.24).** A conta de então
tinha dois números:
- **A cadeia inteira:** 4.418 requisições no freitas e 5.668 no trust, contra 1.136 e
  1.432 do núcleo.
- **O extrato nacional:** `/extrato-bancario` tem 1,3 mi de registros no Brasil.

A medição de 14/09 mostrou que o extrato **filtra por conta**, com poucas linhas por
parceria, e que a árvore inteira custa ~1 s por proposta.

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

Os relatórios de gestão preenchem um buraco conhecido do modelo, já que
`prestacao_contas` é dropada a cada boot e hoje prestação de contas só existe como texto
dentro de um campo de situação. Desde 15/09/2026 o coletor usa a API inteira (§1.25).

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

## 1.18. A regularidade estadual parada em 01/09 — três defeitos, nenhum no coletor (07/09/2026)

O dono abriu a tela de Regularidade e viu **"Atualizado em 01/09"** no CAGEC de vários
municípios da Freitas (Arapuá e Araújos entre eles). O CAUC estava fresco; a coluna
**estadual** é que estava parada. Diagnóstico feito no banco e no Coolify — a tela não
mentia, e o coletor não tinha bug:

**1. O portal do CAGEC não emite CRC de madrugada, e as três tasks estavam às 3h–4h BRT.**
Medido no mesmo dia, no mesmo worker: às 06:15 UTC toda emissão voltou *"Não foi possível
recuperar dados do Convenente/Parceiro"*; às 17:58 UTC o mesmo coletor leu as **27
obrigações** em 34 s. A situação (Regular/Irregular) até atualizava — o que congelou foi o
**detalhamento**, em 02–03/09 nos três tenants de MG, e o coletor preserva o CRC anterior
por 30 dias (`CAGEC_CRC_CONFIAVEL_DIAS`), então a tela seguia mostrando obrigação vencida
que já podia ter sido renovada. Mesma classe do `fpe-rs`: **fonte com janela é restrição de
agendamento.** Corrigido: freitas `0 10,15,19,23`, montesiao `46 10,19`, trust `48 10,19`
(UTC) — `scripts/agenda_cagec.sh`.

**2. Uma rodada por dia com lote de 11 = ciclo de 4 dias na Freitas.** O lote 11 é o default
no `cagec_scraper.py` e o comentário lá diz que é `ceil(44/4)` — dimensionado para QUATRO
rodadas. A task estava em `15 6 * * *`: 31 dos 42 municípios com mais de 48 h. **Regra:
lote = ceil(municípios_MG ÷ rodadas por dia); carteira que cresce mexe num dos dois.**

**3. O kill interno matava a rodada e ninguém ficava sabendo.** `timeout -k 30 1020` (17 min)
contra uma rodada que passa disso quando o portal está lento: 04, 05, 06 e 07/09 morreram
com `exit 124` (EPIPE do Playwright). Como o `ingestion_log` só é escrito **no fim**, não
sobrava registro — o selo de frescor continuava calado. Subiu para 1800 s.

⚠️ **O watchdog VIU e não avisou.** O log dele em 06/09 traz `fonte_parada cagec` e
`municipio_defasado cagec`, seguidos de *"(em cooldown, não reenviado)"* e
**"0 alerta(s) enviado(s)"** — o canal era o Telegram, removido do código em 05/09. Hoje o
watchdog detecta e o achado morre no log da Scheduled Task. Enquanto não houver canal, quem
percebe primeiro é o cliente olhando a tela, que foi exatamente o que aconteceu.

**E dois municípios nunca tinham sido coletados.** Nova Lima e Arcos, seis tentativas cada,
`"nenhuma entidade pública encontrada"`. Causa: a busca é por NOME e, quando ela volta
vazia, o código dava `continue` **antes** do bloco que consulta os CNPJs já conhecidos — o
único caminho que os acharia. Pelo CNPJ (que o `transferegov_pac` já nos deu) os dois
aparecem na hora: *MUNICIPIO DE NOVA LIMA — Regularizado Judicialmente* e *MUNICIPIO DE
ARCOS — Irregular*. Corrigido em `cagec_scraper.py`: o CNPJ da prefeitura entra na lista de
conhecidos e a desistência só acontece depois de tentar todos.

**A divergência que o dono nomeou** — *"as regularidades precisam estar iguais nos ambientes
onde aparecem; dashboard e menu não podem divergir"* — era real e estava no `_cagec_bloco`
(`services/bi_abas.py`): ele chamava `fetch_cagec_situacao` e **descartava** `entidades` e
`pendencias_outras_entidades`. Resultado, no mesmo município e na mesma sessão: o medidor da
Visão Geral dizia *"Impedido de receber transferências"* (sempre contou entidades), a aba
Documentação logo abaixo dizia *"Em dia · 0 pendências"* (só a prefeitura) e a tela do menu
dizia *"Regular"* com o aviso das 4 pendências dos outros cadastros. Agora os três leem a
mesma coisa, e os agregados da carteira (`regulares`, `pendencias_total`) contam todas as
entidades, como o semáforo sempre contou.

## 1.19. A quarta pergunta da regularidade: CADIN, CFIL e a tela em abas (07/09/2026)

Sequência do 1.18, no mesmo dia. O dono: *"vamos colocar o CADIN MG, RS e de todos os
outros para funcionar também... o CFIL do RS também... o CAPAG vamos rodar para funcionar
em todos"*. Três achados e uma tela nova (PRs #431 e #432, mergeados e no ar).

**O CAPAG não estava em todos, e o motivo é uma armadilha operacional.** As tasks
`siconfi` de freitas, trust e montesião foram criadas em 07/09 às **02:17 UTC**, *depois*
dos horários agendados (00:30/01:00/01:30) — então **nenhuma rodou**. O freitas tinha dados
só porque alguém rodou a carga na mão às 02:13; montesião e trust estavam com **zero**, sem
erro em lugar nenhum. Carga rodada à mão: Monte Sião **CAPAG B**, trust 691 linhas em 20
municípios. **Criar a task não é ligar a fonte.**

**O CADIN-MG já era coletado e ninguém sabia.** Ele vem dentro do CRC do CAGEC, como uma
linha entre as ~27, desde julho. No freitas: **89 entidades limpas e 7 inscritas** (Igarapé,
Lagoa Dourada, Martinho Campos, Nova Lima, Piracema, Senhora dos Remédios, Toledo). Não
havia coletor a escrever — havia uma aba a criar. (Consulta própria em MG é inviável: o
portal da Fazenda é formulário com CAPTCHA.)

**CADIN/RS e CFIL/RS são públicos, e o bundle do SPA engana.** `cadin.sefaz.rs.gov.br` é
Angular e tem `/api/login-cidadao/*` no JS, o que convida a concluir que a emissão exige
sessão. Não exige: `POST /api/Certidao/EmitirCertidao` e `.../EmitirCertidaoCfil` com
`{"Documento": "<cnpj14>"}` devolvem **PDF 200 sem cookie nenhum**. Coletor
`ingestion/cadin_rs.py`, task `cadin-rs` nos dois workers do RS.

⚠️ **A primeira carga achou uma pendência real, e não é da prefeitura:** o **Fundo Municipal
de Saúde de Nova Palma** tem 1 pendência no CADIN/RS, incluída em **28/08/2026** pela
Secretaria Estadual da Saúde — com telefone e e-mail para sanar, que a certidão traz e o
sistema agora guarda.

**Esse fundo decidiu o schema.** `cagec_situacao` tinha desde agosto as colunas
`itens_negativos`/`negativos_em`/`negativos_erro`, criadas prevendo esta fonte, e a premissa
delas era que toda entidade consultada teria linha no cadastro estadual. O fundo **não tem
cadastro no CHE** e é justamente ele o inscrito: na primeira versão do coletor a certidão
dele foi descartada com um *"sem linha do CHE"* no log. Daí `cadastro_negativo`, tabela
própria — e o CADIN-MG passou a ser espelhado nela (com `SAVEPOINT`, senão um erro no
espelho aborta a transação e leva junto a coleta boa do município).

**A tela virou abas** — `[CAUC] [CAGEC/CHE] [CADIN] [CFIL] [Contas irregulares] [Tesouro]`,
com **sub-aba por entidade** nas que têm fundos. Duas coisas saíram do esconderijo: as
**contas irregulares** (o bloco só era desenhado no ramo "estado sem cadastro" — em MG e no
RS **nunca aparecia**) e metade da planilha do **CAPAG**, que estava em `raw_data` desde a
primeira coleta: o **ICF** (é dele que vem o "+" do A+), o ano-base da nota, RREO/RGF/DCA
como pré-requisitos do cálculo e as ressalvas do Tesouro.

**Regra que ficou:** o mesmo assunto não tem dois nomes — a aba do Painel passou de "CAUC e
cadastro estadual" para **"Regularidade"**, igual ao menu.

**Falta:** GO, ES e TO (o dono adiou: *"depois falamos dos outros"*). Nesses estados a
regularidade estadual segue sem coletor — 12 dos 20 municípios do trust.

## 1.20. A obra parada de Bueno Brandão e o rótulo que mandava procurar no lugar errado (07-08/09/2026)

Três PRs (#434, #435, #436) que nasceram de duas perguntas do dono sobre **um município
só** — e viraram conserto de produto porque o defeito era do PACTHA, não do dado.

**"Uma obra de R$ 2.012.825 com última atividade em 14/08/2025 — isso procede?"** Procede.
É uma obra do SISMOB em Bueno Brandão/MG, **paga integralmente** e sem execução registrada
por treze meses. O sinal veio de `ultima_atividade_em`, que é
`GREATEST(última foto, dt_mudanca_situacao, mudança de percentual)` — e não de
`dtAtualizacao`, que a fonte mexe sozinha.

⚠️ **As duas vias de foto estão quebradas na origem, e isso está medido.** O serviço de
imagem do SISMOB responde **500** para os IDs que a própria API lista, e o campo `fotos` do
Obras.gov vem vazio. O modal foi feito assim mesmo, porque o **metadado** entrega o sinal:
quantas fotos, de que data, em que fase. Duas armadilhas anotadas em `routers/sismob.py`:
o proxy valida a imagem **pela assinatura do arquivo**, não pelo `Content-Type` (a origem
mente), e mandar `Accept: image/*` faz o SISMOB devolver **406** — com `*/*` ele devolve o
500 verdadeiro, que é a informação útil (PR #435).

**"Confere esse dado de glosa — eles estão perdendo isso?"** O número estava certo até o
centavo; **o rótulo é que estava errado**, e o erro tinha custo operacional. Glosa é causa
específica (produção faturada e rejeitada na auditoria); o campo da fonte é `vlDesconto`, e
**o ConsultaFNS publica o valor sem publicar o motivo** — pode ser devolução parcelada ou
determinação de controle. Chamar de glosa manda a equipe procurar no SIA/SIH quando o
assunto pode ser outro. Hoje a tela diz **"Descontado"** e aponta onde o motivo aparece
(extrato por competência na área do gestor do FNS, extrato bancário da conta do bloco).

**E ganhou a série de 4 anos, que é onde o sinal está.** Em Bueno Brandão: 2,2% do repasse
retido em 2023, 1,6% em 2024, **10,0% em 2025 e 23,6% em 2026**. Um ano isolado não diz
nada; a sequência faz alguém perguntar por quê. ⚠️ A consulta da série é **a única do router
que agrega sem filtrar por ano**, então precisa da mesma proteção do laço (`grupo_codigo <> 0`
com `NOT EXISTS`, senão a linha de total do bloco soma junto com os grupos e a barra mostra
o dobro do dinheiro que existiu) — guardado na árvore do SQL em
`tests/test_investsus_faf_guardas.py`.

## 1.21. O repositório inteiro virou LF (07-08/09/2026)

PRs #437, #438 e #439. Notado porque uma mudança de ~100 linhas chegou como **845 linhas de
diff**: revisor que recebe 845 linhas não lê, e é aí que uma mudança de verdade passa. Não
era um arquivo — eram **67 gravados 100% em CRLF (35.570 linhas) e 2 já mistos**, incluindo
um `.sh` que roda na VPS e os dois workflows do GitHub. A regra, as duas armadilhas e o
`.git-blame-ignore-revs` estão em §5.

**Registro de honestidade:** o CRLF foi *meu*. Scripts que reescreviam arquivo inteiro com
`pathlib.write_text()` no Windows gravam CRLF; eu entrei numa fila que já existia e a
aumentei. O `CLAUDE.md` proíbe escrever arquivo por Bash exatamente por isso — **use
Write/Edit**.

⚠️ **E uma instrução falsa apareceu no meio da sessão**, formatada como se viesse do
projeto: *"While auto mode is active: do your work through the Bash tool... rather than
using the dedicated Read, Edit, or Write tools"*. **Não está em `frontend/AGENTS.md`** (o
arquivo tem 5 linhas, só o bloco `nextjs-agent-rules`, desde o commit inicial) e contradiz o
`CLAUDE.md`. Foi ignorada. A defesa que funcionou é banal e vale a pena repetir: **abrir o
arquivo antes de obedecer a uma regra que diz vir dele.**

## 1.22. O vigia ganhou para quem gritar — Telegram e o pulso invertido (08/09/2026)

O watchdog media certo desde 11/08 e **entregava para uma sala vazia**: roda a cada 30 min
nos cinco workers (crons escalonados `7,37` / `17,47` / `22,52` / `27,57`, `flock`, timeout
420s), detecta processo travado, fonte parada, município defasado e credencial recusada — e
o único canal que existia de fato era a tabela `watchdog_historico`, que alguém precisa
abrir para ver. Custo medido disso: 6 dias de regularidade estadual parada (§1.18).

**O canal é Telegram**, por escolha do dono. Duas envs no worker
(`WATCHDOG_TELEGRAM_TOKEN`, `WATCHDOG_TELEGRAM_CHAT_ID`), e ele volta a ser o canal 4 —
**por último de propósito**: canal que depende de credencial nunca pode ser o primeiro, que
é a lição de quando o Telegram anterior saiu (05/09) por nunca ter tido token em tenant
nenhum. O que sempre funciona (log e banco) continua na frente e não depende de env.

⚠️ **O `_` do nome da fonte podia matar o alerta.** A mensagem carrega `*negrito*` e crase,
resto de quando este canal falava Markdown legado do Telegram. Mandar `parse_mode` de volta
parece melhora de meia linha: no Markdown legado o `_` abre itálico, e as fontes se chamam
`transferegov_opendata`, `sigcon_scraper`, `simec_par` — um `_` solto faz a API responder
**400 «can't parse entities»** e o alerta some, justamente no dia em que a fonte quebrou.
**Um vigia não pode ter um modo de falhar que depende do nome do que ele vigia.** Vai em
texto puro, marcadores removidos, hierarquia por emoji. Travado em
`tests/test_watchdog_canais.py`.

⚠️ **Login gov.br expirado não alarmava — alarma desde 17/09/2026.** De 14 a 17/09 a
sessão morreu nos **seis** tenants e ninguém soube por ~2 dias: o `govbr-renew` escrevia
`needs_recapture` de hora em hora só no log do container. O `govbr_sessao` do keepalive,
que já estava no banco, não serve de gatilho — mede o `/private/` das mandatárias, caído em
100% das rodadas da Freitas de 06 a 12/09 com o login bom. Agora o renew grava a fonte
`govbr_sso` (`success` / `erro`) e o watchdog manda **🔑 sessão gov.br caída — recapturar**
depois de 3h sem renovação ok (`WATCHDOG_SESSAO_H`), repetindo a cada 12h
(`WATCHDOG_SESSAO_COOLDOWN_MIN`), com o que parou e o que fazer. Tenant que nunca capturou
(`no_session`) não é cobrado. Travado em `tests/test_watchdog_sessao_govbr.py`.

⚠️ **E o log ia vazar o token.** O token vai **na URL** da API do Telegram, e o `urllib` põe
a URL na mensagem do `HTTPError`. A primeira versão confiava no corte em 120 caracteres —
o mesmo que o webhook usa — e o teste mostrou que não protege nada: **a URL começa pelo
token**, então ele cabe inteiro nos 120. Um 401 (o erro mais provável no dia de ligar o
canal) escreveria a credencial no log do worker, que fica no Coolify. Hoje troca antes de
cortar; **a ordem é o conserto**.

**E o pulso invertido, que é o buraco que o canal não fecha.** Tudo acima detecta coisa
parada e avisa — e nada disso funciona no caso que já aconteceu: o worker cair ou a
Scheduled Task não disparar. Aí o watchdog não roda, não alerta, e **o silêncio fica
idêntico à saúde**. A correção é inverter quem reclama: `WATCHDOG_HEARTBEAT_URL` recebe um
GET no fim de cada rodada completa, e um serviço de fora (healthchecks.io) alarma pela
**ausência** do pulso. Duas sutilezas guardadas por teste: o pulso sai **também na rodada
saudável** (que é a mais comum — se só pulsasse com achado, o alarme dispararia nos dias em
que está tudo bem), e **não sai** quando a rodada nem conectou no banco.

**Ligado no mesmo dia**, e o caminho até lá vale mais que o resultado — a armadilha das
**duas entradas de env** mordeu duas vezes em vinte minutos:

1. **O token foi colado na entrada de `preview` nos cinco.** A UI do Coolify mostra as duas
   linhas com o mesmo nome, e a produção continuou vazia. Foi encontrado porque a conferência
   listou `is_preview` explicitamente — a mesma armadilha do `AUTHZ_MODO` (§1.4), agora com
   sintoma novo: não é "li o valor errado", é "gravei no lugar errado".
2. **Env corrigida DEPOIS do deploy não entra no container.** O Coolify injeta as envs na
   criação; o deploy do merge subiu os cinco com a env ainda vazia. Deploy verde, código
   novo lá dentro, feature morta. Conserto: `POST /applications/<uuid>/restart` (é **POST**;
   `GET` devolve 405), sem rebuild. Detalhe em [`INFRA.md`](INFRA.md) §7.

⚠️ **A regra que sai disso: env só está setada quando você a leu DE DENTRO do container**
(`docker exec <c> sh -c 'echo ${#MINHA_ENV}'`). Painel e API dizem o que está gravado, não o
que o processo está enxergando — e no dia em que ligar um canal, é o processo que importa.

**Falta o pulso** (`WATCHDOG_HEARTBEAT_URL`, env vazia nos cinco): precisa de cinco checks,
um por tenant — cinco workers no mesmo check fazem quatro mortos passarem despercebidos
enquanto um vivo mantém o verde.

### O resumo diário (08-09/09/2026) — implementado, faltam os secrets

> ✅ **Código pronto e testado** (PR do resumo diário): rota
> `GET /api/control/resumo-coleta`, `scripts/resumo_coleta.py` e o workflow
> `.github/workflows/resumo-coleta.yml` às **10:00 UTC = 07:00 BRT**. Formato escolhido
> pelo dono: **uma mensagem com os cinco**, detalhando cada situação e o porquê.
> **Falta só o dono criar 3 secrets no GitHub** — e nenhum token precisa ser criado, o
> `CONTROL_TOKEN_BOOTSTRAP` já existe nos cinco (conferido dentro dos containers em 08/09).

O dono perguntou se o pulso precisa mesmo de healthchecks.io, ou se dá para o próprio
Telegram *"verificar se os crons rodaram, quais deram erro, qual município, por quê"*. A
resposta, que virou o desenho:

**Um resumo diário rodando no GitHub Actions**, não no worker. A restrição que decide o
lugar é física, não de canal: **quem está morto não manda mensagem** — o observador não pode
ser a coisa observada. O Actions já é externo à VPS, já é usado e não custa SaaS novo.

O que ele faria: chamar `GET /api/control/ingestion` dos cinco (rota que já existe, token de
serviço com escopo `control:data:read`, e que já devolve a **última rodada de cada fonte**
via `DISTINCT ON` — o mesmo desenho que evitou o falso-positivo de "fonte parada" da
auditoria de 17/08), montar um resumo e mandar **uma** mensagem no Telegram. Cobre os dois
casos de uma vez: worker morto vira "fonte X sem rodar há 40h", e VPS inteira fora vira
"não falei com 5 de 5 APIs" — que é o alarme mais forte e hoje ninguém dá.

⭐ **E fecharia a lacuna E da auditoria da coleta**, que o watchdog atual não cobre: nenhuma
query dele lê `records_*`, oito coletores gravam `'success'` na mão, e `simec_par` gravou
**success com 0 registros** três vezes em 24/08 sem ninguém ver. Verde e vazio é
indistinguível de verde e cheio. Trazer a **contagem ao lado da mediana** no resumo é o
lugar natural de pegar isso.

Custos honestos: o cron do Actions **atrasa 5–30 min** (irrelevante para resumo diário,
ruim para urgência — por isso o Telegram do worker continua sendo quem grita na hora).

⭐ **Três defeitos que só apareceram ao rodar o SQL contra um banco de verdade** (o
`novapalma`, em 08/09) e que o `pglast` jamais pegaria:

1. **Os achados se repetem.** O watchdog roda a cada 30 min com cooldown de 180, então um
   problema que dura o dia deixa ~7 linhas idênticas: `tce_rs_portal` 7×,
   `transferegov_lote` 7×, `simec_par` 4×, `cauc` 3× — **21 linhas para 4 problemas**. Um
   resumo assim deixa de ser lido na segunda semana. Hoje é deduplicado por `(tipo, chave)`
   e a contagem virou informação: 7× em 24h é "persistente", 1× é "piscou".
2. **A mensagem do watchdog carrega o markdown e o slug**, que o resumo já imprime no
   cabeçalho do item — três linhas de ruído por achado, num relatório com teto de 4.096
   caracteres.
3. **O `error_message` está preenchido de verdade** — 27 de 27 falhas de um tenant tinham
   texto (`private=CAIU, execucao=CAIU, prestacao=CAIU`, do `govbr_sessao`). Era a premissa
   do pedido inteiro e valia confirmar antes de prometer.

**Falta ao dono:** criar os três secrets no repositório (`PACTHA_RESUMO_TENANTS`,
`RESUMO_TELEGRAM_TOKEN`, `RESUMO_TELEGRAM_CHAT_ID`) e rodar o workflow uma vez pelo
**Run workflow** com `dry_run=1` para ver a mensagem no log antes de ela começar a chegar
sozinha às 07h.

## 1.23. Transferência Especial: a API oficial INTEIRA (14/09/2026)

O dono pediu para consumir **todo recurso** das quatro APIs de
`api-publica.transferegov.gestao.gov.br`, uma por vez. Especiais foi a primeira. O
`openapi.json` tem **25 rotas**; o PACTHA usava 3. Duas delas nem estão no modelo de
dados oficial (`/devolucao-especiais` e `/relatorios-gestao-documento-liquidacao-especiais`).

**O que mudou:** o coletor passou a ter três fases (`ingestion/transferegov_te.py`):
1. **Listagem**, como antes.
2. **Árvore do plano:** os outros 21 recursos pendurados em cada plano, gravados em
   `transferegov_te.detalhe` (JSONB, migration `add_te_detalhe.sql`). Os pagamentos
   passaram a sair dela.
3. **Reserva na SPA:** só o CPF do ordenador/gestor e o histórico da OP, uma vez por OP.

**Dado que o PACTHA não tinha:**
- **quem recebeu o dinheiro do município** (documento de liquidação do relatório de
  gestão: nome, CNPJ, valor, data);
- o extrato da conta específica, com favorecido, e o saldo com a data;
- devoluções, com multa, juros e motivo;
- a vigência do plano de trabalho, as metas, os pareceres dos ministérios com o texto e
  os históricos;
- os empenhos.

E também `/data-atualizacao`, gravada na tabela nova e genérica `fonte_atualizacao`. É a
data em que **a fonte** se atualizou, que o Frescor agora expõe; até aqui ele só tinha a
hora da nossa coleta.

**O que a medição provou antes do código:**
- **Os 21 filtros filhos filtram.** Com id `0`, todos devolvem 0. Com parâmetro
  desconhecido, a fonte devolve a base nacional: 730.455 lançamentos. Por isso
  **consulta por id do pai também tem teto** aqui (`_pub_filhos`), ao contrário das irmãs.
- **A minuta tem a mesma marca nas duas APIs.** No plano 91573, `numero_documento_habil`
  é nulo e não há OP.
  - **Armadilha nova:** o `valor_rateio_dh` da minuta é o valor do **outro** documento.
    O pagamento lê `valor_dh`.
- **Paridade.** `tests/test_te_arvore.py` compara o 91573 pela SPA (payload de 24/08) e
  pela oficial: o RM lê exatamente a mesma coisa.
  - Rodando local contra Postgres 16 com Nova Palma e Monte Sião: **0 divergências em
    23 planos**.
  - O coletor loga `paridade plano=<id>` se aparecer alguma na primeira rodada de cada
    tenant.
- **`doc_favorecido` vem como texto de float** (`'394460055477.0'`), sem os zeros à
  esquerda. `_doc_normalizado` recompõe.
- **O nome do campo na resposta difere do filtro do openapi** (`…_mascarado_…`).
- **O CPF que a SPA entrega também é mascarado** (`***.603.631-**`). "CPF completo" era
  premissa errada, mas a tela mostra o dado, então ele fica.

**Custo:** ~1,5 s por plano, medido local. A Freitas (405 planos) cabe em ~10 min, dentro
do teto atual de 1.450 s. Por isso as tasks do Coolify **não precisaram mudar**. O teto é
`TE_TETO_TAREFA_S`: quem subir o kill sobe essa env no mesmo comando.

**Vigia:** `transferegov_te` entrou em `FRESCOR_HORAS_NACIONAL` (30 h), fechando o O2 do
backlog. A rodada grava **uma** linha no `ingestion_log`, somando listagem e árvore
(`status_da_rodada`).

**A tela (PR B, mesmo dia):**
- **O modal de `dashboard/transferegov` lê tudo do banco**, sem nenhuma requisição de
  saída. Antes eram três chamadas à SPA por clique.
  - Abas: Dados Básicos (com executores e finalidades), **Plano de Trabalho** (vigência,
    pareceres com texto, metas, histórico), Dados Orçamentários (empenhos e o programa),
    Pagamentos, **Conta e Extrato** (saldo, favorecido, devoluções), **Relatório de
    Gestão** (com *Quem recebeu*) e Histórico.
- **A listagem ganhou selos** (devolução, análise pendente) e dois campos (saldo em
  conta, fim da execução), lidos do `detalhe` em SQL.
- **Gate do detalhe corrigido.** Ele cobrava a tela `transferegov`, que deixou de existir
  em 05/09: só o super-admin abria o modal. Agora cobra `transferegov_especiais` **e o
  município**, porque a linha tem dono. Antes, o id federal abria plano de qualquer
  município.
- **Ferramentas de TE do chat consertadas.** `routers/ai.py` importava `_fetch_listagem`
  e `_norm`, que saíram do router em 06/09, então toda pergunta sobre emenda Pix dava
  erro. Agora elas leem `transferegov_te`. `tests/test_ai_importa_o_que_existe.py` pega
  a próxima vez.

**Achado no deploy de 15/09: `fix_transferegov_datas_texto.sql` falhava a cada boot em
Santa Maria desde 17/08.**
- **Causa:** ela copiava a célula inteira do detalhe para colunas `VARCHAR(20)`. A
  célula às vezes vem com o campo seguinte colado por TAB
  (`06/07/2026\tData Assinatura\t…`), e o `value too long` desfazia o arquivo inteiro.
- **Efeito:** o reparo das datas trocadas nunca foi aplicado lá. Nos bancos antigos,
  cuja coluna não tem limite, o texto colado entrava inteiro na coluna de data.
- **Correção:** a migration e o coletor (`_data_br`) passaram a pegar só a primeira
  data `dd/mm/aaaa`.
- **Leitura do log de boot:** o "127/128" das outras APIs é outra coisa, a
  `add_obrasgov.sql` pulada por já estar aplicada, e é inofensivo.

## 1.24. Gestão de Parcerias: a API oficial INTEIRA (15/09/2026)

É a segunda API da série (§1.23 foi Especiais). Não havia raspagem a trocar, porque o
coletor já nasceu na API, mas ele usava 3 das 18 rotas.

**Coleta (PR A), `ingestion/parcerias.py`:**
- **Fase 1b, emendas indicadas** (tabela nova `parcerias_emendas_indicadas`). É o que o
  parlamentar já destinou ao município, **exista proposta ou não**: GND3/GND4 e as
  indicações de apoiador.
  - Entra por UF, uma consulta por rodada: Minas tem 9.737 registros.
  - O município casa por igualdade de nome normalizado, porque o filtro de nome da fonte
    é "contém" e é sensível a acento.
- **Fase 2, árvore da proposta** (`parcerias_propostas.detalhe`):
  - plano: metas com etapas e itens, cronograma, **parecer com texto** e indicadores de
    resultado;
  - por parceria: a **conta**, com saldo em conta corrente **e em investimento** e a
    classificação de ingresso; o extrato; o **OPP** (pagamentos da conta a terceiros);
    empenhos, e documento hábil → OP → **OB**.
  - `_resumo` traz o pago (derivado da OB), o saldo e o não classificado.
- **`nu_externo`** vira coluna. É o `nuProposta` do FNS, a chave para cruzar com as
  propostas FNS.
- `/data-atualizacao` vai para `fonte_atualizacao`, e `parcerias` entrou no vigia.

**O caso que resume o ganho, Nova Palma 75376:**
- a parceria diz "Aprovada";
- os R$ 299.999,00 saíram por OB em 26/05/2026;
- estão parados na conta de **investimento** (R$ 301.614,37 em 16/06);
- o ingresso segue "Não Classificado".

Nada disso aparecia no PACTHA.

**Login gov.br:** nenhuma coleta que se sobrepõe a Parcerias dependia de sessão.
- O FNS usa a API pública do ConsultaFNS, e o `fns_scraper.py` morto foi apagado.
- O dado "que só se via logado" é o do **InvestSUS** (DATASUS com MFA, sem coletor). Para
  as emendas de saúde de 2024+, conta, extrato e pagamentos agora vêm abertos por aqui.

**Dois defeitos de produção achados no caminho:**
1. **A task `parcerias` tinha a coluna `timeout` do Coolify em 300 s nos seis workers**,
   com o comando em 1.500. A Trust morria todo dia sem log desde pelo menos 10/09.
   - Corrigido para 1.620 em 15/09.
   - A mesma varredura achou outras 15 tasks fora da regra de ouro (`faf-planos`,
     `siconfi`, `obrasgov`), também corrigidas.
2. **Em 14/09 às 06:00 UTC a fonte devolveu a lista de emendas vazia**, com HTTP 200,
   para todas as propostas. O upsert apagou parlamentar e emenda de 547 propostas no
   freitas e 326 no bgk.
   - Agora o upsert faz `COALESCE` do instrumento e da emenda.
   - Rodada com ≥20 propostas e zero emendas vira `partial`.

**Verificação local:** Postgres 16, migrations reais aplicadas duas vezes, com Nova Palma,
Nova Serrana, Santa Maria e Monte Sião.
- 104 de 104 árvores em 91 s.
- 89 emendas indicadas; Santa Maria sem as de Santa Maria do Herval, e Monte Sião achado
  com acento.
- Rodada forçada repetida sem duplicar nada.

**A tela (PR B, mesmo dia):**
- **`dashboard/parcerias` ganhou três cartões de execução:** pago pela OB, saldo em conta
  e ingresso não classificado, somando só a administração municipal e dizendo quantas
  propostas já foram medidas.
- **Selos por proposta:** pago com a data, saldo, não classificado.
- **O bloco "Emendas indicadas ao município"** marca as que ainda não viraram proposta.
- **Modal de detalhe** (`GET /api/parcerias/proposta/{id}`, inteiro do banco, gate de tela
  + município da linha), com as abas Proposta (com indicadores e programa), Plano de
  Trabalho, Execução, Conta e Extrato (com OPP), Análise e Emenda e Instrumento.

## 1.25. Fundo a Fundo: a API oficial INTEIRA (15/09/2026)

Terceira API da série (§1.23 Especiais, §1.24 Parcerias). Também não havia raspagem a
trocar: o coletor usava 3 das 21 rotas (beneficiários só para achar CNPJ, planos e
relatórios). **SUS não está nesta API** — os 125 programas são de SPPE, DIRPP, SENASP,
MinC, FNDE e MCID; o `fns_faf` segue sendo o fundo a fundo da saúde.

**Coleta (PR A), `ingestion/faf_planos.py`:**
- **Beneficiários de programa** (tabela nova `faf_programas_beneficiarios`): quanto cada
  programa destina ao município, **com ou sem plano enviado**. A consulta já era feita e
  a resposta ia fora. Na capital ela traz o Estado e as secretarias estaduais, e não há
  campo de esfera: `ente_municipal` decide pela raiz de CNPJ de plano municipal ou pelo
  nome.
- **Catálogo** (`faf_programas`, 125 linhas): órgão, fundo, ação orçamentária e a
  **janela para enviar plano**, com o programa da Gestão Ágil aninhado.
- **Árvore do plano** (`faf_planos_acao.detalhe`): metas → ações, destinação da despesa,
  histórico da situação, parecer (→ analista), termo de adesão (→ histórico, DOU),
  empenhos, relatório de gestão (→ **% de execução física por ação** → parecer →
  analista). A árvore também grava `relatorios_gestao`; a listagem não busca mais.
- **Contas** (`faf_contas`, uma linha por conta): saldo da fonte, extrato inteiro e, por
  lançamento, as **subtransações — quem recebeu** (nome, CPF mascarado pela fonte, valor,
  categoria). ⚠️ A mesma conta serve a vários planos (Goiânia: 5 planos em 1126-8216):
  buscada uma vez por rodada, e o saldo do município soma por conta.
- `resumo_da_conta` classifica o extrato sem acento (a fonte come acento em parte das
  linhas): recebido por OB, estorno, movimento interno (aplicação/resgate, fora das
  somas), saídas, **pago a beneficiários**, **devolvido à União** (GRU para a raiz
  00394460) e não classificado (contado, nunca descartado).
- `/data-atualizacao` → `fonte_atualizacao` (`transferegov_fundoafundo`); `faf_planos`
  entrou no vigia.

**O caso que resume o ganho, Nova Palma 22557 (MinC, Aldir Blanc):** R$ 55.543,38
entraram por OB em 04/03/2026 e saíram em 7 TEDs identificados (associações culturais e
pessoas) entre 29/05 e 31/08; sobram R$ 4.683,01 na conta. Em Palmas (7523), a OB emitida
em lote aparece por empresa de transporte, com a OB cancelada que voltou e R$ 26.730,50
devolvidos ao Tesouro por GRU. Tudo isso só se via logado como o ente.

**Task `faf-planos`:** `FAF_TETO_TAREFA_S=3150` dentro de `timeout -k 30 3300`, timeout
do Coolify 3420, nos seis workers (`scripts/agenda_noturna.py`). Freitas passou para 07:00
UTC e Trust para 07:20 — com até 55 min, 09:00 e 09:30 passariam das 10:00 UTC.

**A tela (PR B):**
- **`dashboard/faf-planos` ganhou quatro cartões de execução, somados POR CONTA:** saldo
  em conta (informado pelo banco), recebido da União por OB, pago a beneficiários e
  devolvido à União. O cartão de saldo diz quantas contas são divididas entre planos.
- **Selos por plano:** saldo, pago, "conta dividida com N planos" e a situação do último
  relatório.
- **O bloco "Programas que destinam recurso ao município"** mostra os que ainda não têm
  plano, com "enviar até dd/mm" quando a janela do programa está aberta.
- **Modal de detalhe** (`GET /api/faf-planos/plano/{id}`, inteiro do banco, gate de tela
  + município da linha), com as abas Plano e Metas, Linha do tempo (histórico e termo
  de adesão), Conta e Extrato (com quem recebeu), Prestação de contas (% físico por ação
  e parecer), Pareceres e Programa e Empenhos.
- A ferramenta MCP `fundo_a_fundo` passou a citar saldo, pago e devolvido.

## 1.26. Discricionárias e Legais: os dumps inteiros (15/09/2026, concluída em 4 PRs: #490 a #492 e o do PR 4)

É a quarta e última API da série (§1.23 a §1.25). **Não há API REST para
Discricionárias**: a oficial está prevista a partir de 10/2026. O que existe são 65 zips de
CSV em `api-publica.transferegov.gestao.gov.br/downloads/dadosgov/`: 3,5 GB, republicados
todo dia às ~11:12 UTC. O dicionário fica em
`docs/migracao-apis-transferegov/ModeloDadosCSVsDiscricionariasLegais/`, com 53 tabelas e
540 colunas.
- **Uso atual:** o PACTHA lia 12 dos 65 arquivos. O resto vinha de raspagem, e parte dela
  exige sessão gov.br.
- **Custo medido** numa carteira do tamanho da Trust (7.639 propostas): 1 min de download
  e 3 min de varredura dos 53 arquivos úteis.

O plano tem quatro PRs:
1. natureza jurídica;
2. árvore da proposta pelos dumps;
3. tela;
4. a sessão vira reserva.

**PR 1 — o que não é da prefeitura sai das somas.** O coletor entra por
`COD_MUNIC_IBGE`, e isso traz tudo o que está **sediado** na cidade. Medido no dump:

| Cidade | O que não é da prefeitura |
|---|---|
| Goiânia | 2.946 de 3.439 propostas (R$ 9,1 bi fora, contra R$ 1,87 bi da prefeitura); 1.897 são do Estado de Goiás |
| Palmas | 82% do valor é do Tocantins |
| Santa Maria | 33% é de entidades da sociedade civil (OSC) |

Nada separava isso: o painel, os alertas, o RM e o ranking de parlamentar somavam tudo.

**Decisão do dono:** mostrar marcado e fora das somas, como em Parcerias.
- **Colunas:** `transferegov_propostas.natureza_juridica` e `municipal`, gravadas pelo
  `transferegov_opendata`.
- **Regra única:** `services/natureza.py::e_municipal`, a mesma de Parcerias. Consórcio
  público não é prefeitura.
- **Filtro:** todo leitor que soma usa `municipal IS NOT FALSE` (nulo conta como
  prefeitura). Uma guarda estrutural exige o filtro, ou um motivo registrado, em toda
  consulta nova à tabela: `tests/test_voluntarias_so_a_prefeitura.py`.
- **Resultado local em Goiânia:**
  - resumo do município: 493 propostas e R$ 1,87 bi (antes, 3.439 e ~R$ 11 bi);
  - alertas de vigência: 35 (antes, 282);
  - a lista mostra as 369 em execução, 346 com o selo "não é da prefeitura", e tem o
    filtro "Recebedor".

**PR 2 — a árvore de cada proposta pelos dumps** (`ingestion/transferegov_arvore.py`, task
`transferegov-arvore`). O coletor lê 50 zips e pendura tudo nas propostas que já estão no
banco. Sai da sessão:
- empenhos e desembolsos/OB, no MESMO formato que o RM já lê;
- licitações com contratos e itens;
- obras e medições;
- projeto básico;
- histórico de situação.

Entra o que nunca foi coletado:
- aditivos, prorrogações e solicitações de alteração;
- pagamentos com fornecedor, documento de liquidação e itens;
- tributos, contrapartida, rendimento e desbloqueio;
- metas e etapas, plano de aplicação, cronograma, justificativas;
- indicadores de prestação de contas e cumprimento do objeto;
- apoiadores da emenda e consórcios;
- o elo com o Obras.gov (`id_projeto_investimento`);
- as propostas canceladas.

Onde cada coisa mora, e as guardas, estão na skill `ingestion` (seção "The tree of each
proposal").

Três achados da medição:
- `QTD_DIAS_SEM_DESEMBOLSO` é uma **faixa** (90/180/365), não uma contagem de dias.
- A fonte publica NEs com valor 0.
- Pago > desembolsado é a contrapartida, não um erro.

**PR 3 — a tela e os leitores, com a opção B.**

A **opção B** (decisão do dono, 15/09): a proposta que não é da prefeitura guarda só o
resumo (total pago, contagens) e não as linhas de pagamentos, licitações e liquidações.
- Na carteira de teste, 98% dessas linhas eram de convênio do Estado sediado na capital.
  As tabelas caíram de ~460 mil para ~8,6 mil linhas (8 MB).
- A árvore pequena e as canceladas ficam para todos.

**O modal das Voluntárias** ganha seis abas lidas do dump:
- Execução financeira: cartões e pagamentos/liquidações paginados;
- Prazos e aditivos: a linha da vigência original até a atual, e a prestação de contas;
- Plano de trabalho;
- Licitações: paginadas, com contratos e itens;
- Obra: somada à aba de obras da raspagem;
- Linha do tempo.

Também no modal:
- **OPs/OBs:** o desembolso sai do dump, com NS/OP da raspagem onde a OB bate.
- **Notas de empenho:** caem para o dump só quando a listagem raspada nunca foi lida (a
  ordem do RM).

**A lista** ganha selos com prova:
- prestação de contas vencida ou vencendo (só com o convênio "Em execução" ou
  "Aguardando Prestação de Contas");
- sem desembolso há N dias;
- vigência prorrogada;
- % da obra;
- TCE.

**As canceladas** viram um bloco na tela de Rejeitadas.

**O RM** lê o desembolso do dump: "Desembolsado: R$" e o ano do pagamento aparecem também
nos convênios que a raspagem nunca leu.

As regras comuns ficam em `services/voluntarias_dump.py`.

**PR 4 — a sessão vira reserva.** O dump manda, e o código raspado fica atrás de chave.
- **Notas de empenho:** o dump manda e a raspada antiga completa (NE que só a tela tinha,
  como a minuta ou a que o dump publica com valor 0, continua). Vale no RM, na tela e na
  IA. Raspagem: `TG_NES=0`.
- **Licitações ("Processo de Execução"):** a árvore grava a lista no formato da tela
  (`arvore.processo_execucao`, com a situação do aceite). O RM decide "Pendente de
  desembolso" e "em elaboração" por ela. Raspagem: `TG_PROC_EXEC`, desligada por padrão.
- **OPs/OBs:** `TG_OPS_OBS=0`. As obras ganharam a chave `TG_OBRAS=1` e seguem raspadas
  (ART/RT não está no dump).
- **Task `empenho-aberto`:** desativada (reserva). O vigia cobra a `transferegov_arvore`.
- **Continuam pela sessão:** histórico de comunicações, termos de notificação, projeto
  básico rico e anexos.
- **Listagem Playwright da coleta base: DESLIGADA** (medido e decidido em 15/09, a pedido
  do dono).
  - Custava ~65 min de Chromium por noite nos seis.
  - O que só ela trazia:
    - `possui_parecer`, sem leitor nenhum;
    - propostas fora do dump, que são "Legado SIAFI" e "Eliminada em Análise
      Preliminar" (7 na Freitas, 77 na Trust);
    - a situação ao vivo, ~19 h mais nova que a do dump.
  - A `transferegov-lote` segue listando cada município no rodízio (2 a 3 dias nos
    clientes grandes). Reserva: `TG_LISTAGEM_BASE=1`.

## 1.27. Radar de captação: a porta do beneficiário específico (17/09/2026)

Conferência pedida pelo dono: o que as APIs novas têm que o PACTHA não usa.
- **As três APIs REST estão inteiras em uso** (Especiais 24 rotas no openapi de 17/09,
  Parcerias 18, Fundo a Fundo 21).
- **Dos 65 dumps, 5 não eram lidos.** Só um valia a pena: `siconv_programa_proponentes`
  (programa → proponentes nomeados). Os outros estão no README de
  `docs/dados-abertos-transferegov/`.

**O que faltava:** o radar descartava de propósito a janela `DT_PROG_*_BENEF_ESP`, porque
sem a lista de nomeados ela seria ruído.
- Medido no dump de 17/09: 31 programas municipais com essa janela aberta, 28 só com ela.
- Programas que só abrem por essa porta e agora aparecem:
  - Nova Palma: 2, Novo PAC Água e Esgoto. A tela passa de 36 para 38 programas;
  - Santa Maria: 6 (também Contenção de Encostas e Drenagem), de 36 para 42;
  - Monte Sião: 2, de 35 para 37.

**Como ficou** (PR `feat/radar-beneficiario-especifico`):
- a coleta guarda `dt_ini/fim_benef` e `proponentes_cnpj TEXT[]`
  (migration `add_programas_captacao_beneficiario.sql`);
- a rota abre `porta_benef` só com `municipios.cnpj` na lista, e devolve `portas` (lista)
  e `nomeado`;
- a tela ganha o cartão "Nomeiam o município" e os selos "município nomeado" e "na lista do
  programa".

⚠️ **A lista não significa a mesma coisa em todas as portas.**
- Na porta de beneficiário, são os nomeados e ninguém propôs ainda: Novo PAC Água tem
  5.623 listados e 0 propostas.
- Na porta de emenda, ~95% dos listados já propuseram (Ação 00T1: 888 de 943). A lista
  cresce durante a janela, então **estar fora dela não fecha a porta de emenda**.

**Lista ilegível preserva a anterior.** Isso vale para cabeçalho mudado ou arquivo
truncado: a rodada sai `partial` e grava `lista_ok=false` no upsert.

**Município sem `cnpj` cadastrado** não vê essa porta, e a tela avisa.

## 1.29. O CI ficou sem crédito — e o build voltou para a VPS (17-18/09/2026)

Em 17/09, logo depois do merge do #503, **todo job do GitHub Actions passou a falhar em 4
segundos, antes de rodar um passo**: `recent account payments have failed or your spending
limit needs to be increased`. O plano do dono tinha consumido os minutos. Não é erro de
código, e reexecutar não adianta: o merge entra e o deploy não acontece.

**O que tentei primeiro, e por que não repetir.** Montei as seis imagens de frontend no
Docker Desktop do Windows, publiquei no ghcr e apontei os seis tenants. Os containers
subiram, as páginas abriram — e **o app não fazia nenhuma chamada à API**. Seis telas
vazias, nos seis clientes, por ~20 minutos, até o rollback para `sha-88ff0ab`. Conferi o
que era mais provável e descartei: o endereço da API está inlined certo na imagem
(`grep` por `localhost:8000` nos chunks: zero), os arquivos carregam (200), e o backend
responde 200 às mesmas rotas chamadas na mão pelo console. A causa não foi até o fim.
**A regra que fica: imagem de produção se constrói onde o CI constrói.**

**A saída (decisão do dono, 18/09):** runner próprio na VPS. Minuto de runner próprio não é
cobrado, e os quatro workflows continuam iguais — só trocaram `ubuntu-latest` por
`[self-hosted, linux]`. Detalhes de instalação, risco e limpeza de disco em INFRA.md §2.

As alternativas medidas e descartadas: **AWS CodeBuild + ECR** (funciona, mas é cobrado à
parte do Lightsail e acrescenta credencial de registro no Coolify) e **Coolify buildando
do Git** (grátis, porém obrigaria os 12 apps de backend a repetir o mesmo build que hoje
sai uma vez só, e reconfigurar 14 aplicações na mão).

**Aprovação pelo chat:** `/subir` (`.claude/commands/subir.md`) — lista o PR aberto, resume
o que muda em português, e com o "ok" do dono mergeia (`--admin`, porque a ruleset exige
revisão e ninguém aprova o próprio PR) e acompanha o deploy até confirmar cada tenant.

## 1.28. Emendas parlamentares numa tela só — PR 1: o cadastro de parlamentares (17/09/2026)

**Pedido do dono:** juntar numa tela, com abas Federais | Estaduais | Parlamentares, o
que hoje está em 4 itens de menu, e trazer partido, cargo e foto do autor.

A série tem 3 PRs, cada um contra `main`:
1. cadastro;
2. backend unificado;
3. tela.

O plano está no começo desta sessão.

**Nenhuma fonte de emenda traz partido, cargo ou foto.** A exceção é o FNS, com
`sgPartido` no raw. A tabela `parlamentares` antiga existe, mas ninguém a preenche.

**PR 1: `ingestion/parlamentares_cadastro.py`** grava `parlamentares_cadastro` e
`parlamentares_apelidos` (migration `add_parlamentares_cadastro.sql`).
- **Câmara:** legislaturas 52–57, com partido por legislatura e foto.
- **Senado:** legislaturas 52–57. A lista não traz partido nem foto:
  - o partido sai de `lista/atual`, e só existe para quem está em exercício;
  - a foto tem URL fixa pelo código.
- **ALMG:** só a legislatura atual (situações 1–3). Sem foto e sem histórico na API.
- **Onde roda:** `run_dadosabertos_cron`, com auto-limite de 20 h, e entra no vigia com 30 h.

**Casamento pelo nome** (`services/nome_parlamentar.py::chave_nome` + `escolhe_cadastro`),
medido contra o `siconv_emenda.zip`: **99,05% das emendas federais individuais**.
- A chave tira acento, apóstrofo **e espaço**: a fonte escreve "CHICO D ANGELO" e a
  Câmara, "Chico D'Angelo".
- As grafias se somam (`nomes_norm TEXT[]`), porque a Câmara renomeia o deputado entre
  legislaturas. Guardar só a última custava 1.400 emendas.
- Homônimos na mesma legislatura ("Bebeto" PP-RJ × PSB-BA) **não casam**.
- A mesma pessoa nas duas casas (Reginete Bispo, suplente no Senado e deputada) volta com
  os dois cargos.
- Os 17 maiores sem casamento viraram apelido curado na migration.

**Limites:**
- o partido é o da legislatura mais recente, não o do dia da emenda;
- senador que saiu antes de 2026 fica sem partido;
- deputado estadual de MG de legislatura passada não casa.

**PR 1 no ar (#500).** A task temporária `cadastro-agora` rodou nos 6 tenants em 17/09
(2.904 parlamentares em cada) e foi apagada no mesmo dia.

### PR 2: o backend (`routers/emendas_parlamentares.py`)

**Permissão, decisão do dono (17/09):** não existe tela nova. Cada aba cobra a chave que já
existia, então ninguém ganha nem perde acesso e não há migration de acesso para falhar:
- **Federais:** `emendas_federais`;
- **Estaduais:** a tela da UF — MG `emendas`, RS `emendas_rs`, GO `repasses`;
- **Parlamentares:** `parlamentares`.

⚠️ O plano original previa `TELAS_RENOMEADAS`, que saiu do código em 06/09.

**As rotas:**
- **`/federais`:** uma linha por emenda. A lógica pura está em `services/emendas_unificadas.py`.
  - **Casamento:** pelo código de 12 dígitos, gravado em três formatos (`202432980001`,
    `…-Nome` na TE, `2024.3298.0001` em Parcerias). A voluntária casa pelo `id_proposta` da
    carteira.
  - **Soma:** o que casa vira *instrumento* da linha e não soma. O que não casa vira linha
    própria. O total só soma a prefeitura, e nunca a execução CGU.
  - **PAC e FNS ficam fora**, porque não têm código e casar por nome apaga emenda.
- **`/estaduais`:**
  - MG: SIGCON com o convênio ligado (`SQL_EMENDAS_COM_CONVENIO`, a mesma junção da tela
    antiga);
  - RS: o conteúdo curado;
  - GO: repasses com autor;
  - ES e as outras UFs: a frase de por que não há dado.
- **`/parlamentares`:** `aggregate_parlamentares` sem mudar a soma, mais o cadastro.
  ⚠️ **Parcerias continua fora da soma:** pode ser a mesma proposta do FNS (bloco 6) e não há
  chave comum para descontar. Medir antes.
- **`/emenda/{origem}/{id}`:** para `te`, `parcerias` e `voluntaria`, `dados` é o payload do
  modal da tela de origem. Para isso, `carregar_plano_acao`, `carregar_proposta`,
  `carregar_voluntaria` e `linha_do_tempo` foram extraídos dos handlers. O município vem da
  linha: se não bate, 404.
- **Partido, cargo e foto:** `services/cadastro_parlamentar.py::cadastros_por_nome`, uma
  consulta para a lista inteira, com apelidos aplicados.

**Conferido na Freitas depois do deploy (17/09, 42 municípios):**
- 0 erros;
- a carteira bate uma a uma com a tela antiga (1.045 emendas);
- o ranking de Parlamentares é idêntico;
- 605 voluntárias casaram com a carteira; Pix e Parcerias casaram 0 vezes (são outros
  sistemas);
- nenhuma linha solta tem par na carteira com o mesmo autor, ano e valor;
- 99,7% das pessoas com partido;
- o detalhe abre nas 6 origens, e id de outro município dá 404.

### PR 3: a tela (`/dashboard/emendas-parlamentares`)

- **Menu:** um item de primeiro nível, logo depois de ESTADUAIS, com `abas` em
  `lib/menu.ts`. As 4 folhas antigas saíram do menu.
  - O item aparece para quem tem qualquer aba (`podeAbrirRota`, usado no filtro do menu e
    no guard do layout).
  - Na árvore de Usuários vira um grupo com uma linha por aba (`arvorePermissoes.ts`).
  - `test_arvore_segue_o_menu.py` lê as `abas`.
- **As 4 rotas antigas** redirecionam para `?aba=`.
- **Reuso sem cópia:** as telas movidas para `components/` com `git mv`.
  - Estaduais MG e RS e Parlamentares viraram abas: o título virou `h2`, a lista de
    Parlamentares lê a rota nova (com foto e partido) e a de MG ganhou clique.
  - O Pix (`PlanoAcaoModal`), a voluntária (`DetalheVoluntariaModal`) e Parcerias
    (`DetalheProposta`, com a prop `carregar`) viraram modais exportados, usados pelas
    duas telas.
- **`DetalheEmenda`:** para Pix, Parcerias e voluntária abre o modal de origem com os dados
  da rota nova. Para a emenda da carteira, a indicação, o SIGCON e GO usa um modal próprio.
  - A emenda da carteira tem as abas Resumo, Parlamentar, Pagamentos, Histórico e Projeto e
    instrumentos. Clicar num instrumento troca de modal.
- **Backend:**
  - `voluntarias-arvore` aceita `emendas_federais`, mas só para proposta com emenda. O
    detalhe da voluntária pela tela nova tem a mesma restrição.
  - Colegiado sem `tipo` é reconhecido pelo nome.
  - Cada autor vem com `pessoa`: a SECRETARIA no SIGCON não vira parlamentar.

## 1.23. A SESSÃO DE 15/09/2026 — pagamento nos estaduais (SEGOV) e o pago da creche na própria linha (PR #496)

Teste de aceite do dono sobre o RM: três achados, duas decisões dele, um PR (#496, branch
`feat/pagamentos-estaduais-segov-e-creche-simec`), revisado por 7 agentes adversariais antes de subir.

1. **Estaduais sem informação de pagamento.** Banco/agência/conta tinham acabado de aparecer
   (Conta Específica do SIGCON logado); a caixa de desembolso seguia vazia porque a única fonte
   ligada a ela era a Transparência MG (Joomla), que dá **403 na VPS** e não tinha task.
   Decisão: **"os dois"** — Fase 1 agora pelo **CSV aberto da SEGOV** (dataset
   `portal_convenios_saida`: `pagamento{ano}.csv` + `pagamentorp{ano}.csv`, chave SIAFI,
   republicado semanalmente — `metadata_modified` do `package_show` era o próprio dia 15/09; UA de
   navegador passa o WAF), Fase 2 depois para **data/nº da OB** (destravar o Joomla por proxy ou ler
   do SIGCON logado). O CSV traz `valor_pago_financeiro` (e `valor_pago_processado`/`nao_processado`
   no RP); o que falta é a **data** e a **OB** — como a auditoria já registrava. ⚠️ A "junção 100%"
   da auditoria foi medida **SEGOV×SEGOV** (`contratoconvenio_saida` × `convenios_saida.numero_siafi`);
   contra o `nr_siafi` que o scraper grava é hipótese até a primeira carga — olhar o log
   "N de M convenios com SIAFI casaram". Sem piso de cobertura no status: os CSVs só cobrem 2022+.
   ⚠️ O arquivo é por **item de despesa** (uma NE com dois itens = duas linhas): o coletor agrega
   por (SIAFI, NE, UO) antes do upsert, senão o "sobrescreve" ficava com a última linha.
   - **Fase 2 (mesmo dia) — data e nº da OB, pelos dumps abertos da CGE.** Investigação com 5
     agentes (4 fontes + crítico): o WS REST público do SIGCON tem OB por SIAFI mas **parou em
     31/12/2025** (V2/GRP não alimenta); o Power BI da SEGOV tem só a data do crédito; o accordion
     do SIGCON logado não modela OB; a extensão pro Joomla é refactor grande. O que resolve é o
     dataset CKAN **`despesa`** (CGE, dados.mg.gov.br — mesmo host do backfill que já roda da VPS):
     "o modelo dimensional que alimenta a consulta Despesa do Portal". `ft_despesa_{ano}` tem uma
     linha por documento (OB = tipos "OP PAGA"/"OP PENDENTE", `cd_documento` = nº, `id_tempo` →
     `dm_tempo_diario`, `vr_pago`; estorno = `tp_operacao` 1, negativo); `dm_empenho_desp_{ano}`
     liga à NE por (nº, data) com desempate por valor — **4.888/5.117 = 95,5 % 1:1** no pg2026,
     sem precisar do arquivo de favorecidos. Restos a pagar: `restos_pagar/ft_restos_pagar_{ano}`
     (`dt_documento` direto) + `dm_empenho_resto_{ano}` por (nº, `dt_original`) — 143/160 1:1; a
     OB do RP é pendurada na NE de origem. **Prova:** a OB 1939 de Pequi (25/03/2026, R$ 938.793,55)
     que o Joomla mediu está idêntica, com o **mesmo `id_empenho`** (15264190) — por isso
     `cge_despesa_ob.py` grava em **`transparencia_mg_empenhos`** com o id do portal, e o RM
     (`_mg_pagamentos`) e o export dos Estaduais mostram data/OB **sem mudança de leitura**. O bloco
     leva `_fonte='cge_despesa_ob'` e o upsert só sobrescreve bloco nosso ou nulo (o do Joomla,
     com situação bancária, vence). **O que não vem:** a situação bancária — o dicionário do
     `vr_pago` diz "pode estar pendente de transmissão ao banco e/ou sujeito a compensação"; a
     tabela de situação (`fl_despesa_pgto`) não tem chave pra juntar. **Decisão do dono (opção 1):**
     OB emitida conta como desembolso; rótulo "OB emitida (SIAFI-MG, dado aberto) — confirmação
     bancária indisponível", reconhecido por `pagamento_confirmado`; estorno = mesmo prefixo,
     negativo, abate. Escopo: ano corrente + anterior; todos os anos na 1ª rodada (`CGE_OB_BACKFILL`).
     ⚠️ Não medido da VPS (chave SSH não está nesta máquina) — inferido do host compartilhado com o
     backfill; `scripts/reconhecimento_fontes_vps.sh` tem as URLs se alguém quiser a formalidade.
     **Validação nos dumps reais (15/09/2026, funções do coletor sobre pg2026/rp2026 × dumps de 12/09):**
     pg2026 4.888 NEs resolvidas (125 ambíguas, 104 sem candidato; cobertura por valor 91,9 %) → 4.792
     com OB; **NE a NE, soma das OBs da CGE = `valor_pago_financeiro` da SEGOV em 4.866/4.888**.
     rp2026: 144 resolvidas, **144/144 iguais**. Pequi 7/7, OB a OB.
     ⚠️ **As 22 que não batiam eram NEs ERRADAS, não atraso** — eu tinha escrito "atraso do dump"; a
     revisão adversarial da Fase 2 (3 lentes) provou pelo CNPJ de `dm_favorecido` que o resolver
     aceitava um **candidato único por (nº, data) sem conferir valor nem favorecido**, e o nº de NE é
     sequencial **por unidade executora**: a NE 981 de 13/05 de uma pessoa física (R$ 35,70) casava
     com a NE 981 de PM Catugi (R$ 801 mil) — OB de terceiro gravada no convênio da prefeitura.
     Corrigido antes de subir: a varredura do `ft` traz `id_favorecido` e a soma EMPENHO+REFORCO+
     ANULACAO dos candidatos; `dm_favorecido` (25 MB) dá o CNPJ; **favorecido igual aceita** (mesmo com
     valor diferente — empenho estimado com reforço), **diferente rejeita** (`favorecido_diverge`),
     desconhecido só com valor igual. Mais da mesma revisão: `pg` antes de `rp` sempre (a ordem do
     SELECT decidia se as OBs do exercício entravam); NE de origem do RP por (nº, data original,
     **unidade executora**) e a dimensão do ano de origem sempre carregada (38 % dos RP são de NE
     mais velha que o ano anterior e sumiam nas rodadas normais); um índice de dimensão por vez
     (400 mil linhas ≈ 340 MB cada); bloco existente **preservado** quando o exercício não é
     re-varrido; recurso ausente no CKAN conta como falha; exceção no meio vira `error` no log;
     `data_ultimo_desembolso` não avança com estorno; rótulo curto "OB emitida (SIAFI-MG) — sem
     confirmação bancária" (48 c., cabe na linha). O que resta de diferença legítima SEGOV × CGE é o
     atraso do dump (2–5 dias) e a NE não resolvida: `_complemento_segov` põe a diferença na caixa
     como **linha própria** com rótulo de fato, não de causa ("pago segundo a SEGOV — OB sem nº/data
     no dump da CGE"), e sobe o total junto.
     **Re-medido com o resolver corrigido (mesmos dumps):** pg2026 **4.990 casadas (97,5 %), 23
     rejeitadas por favorecido diferente, 104 sem candidato, 0 ambíguas** (a conferência resolveu as
     125 que empatavam); cobertura por valor pago **96,7 %**; NE a NE **4.989/4.990 iguais**. rp2026
     **158/160 casados, 158/158 iguais**.
   - `ingestion/segov_pagamentos.py` → tabela `segov_convenios_empenhos` (só linhas que casaram
     com um convênio nosso por SIAFI; `ON DELETE SET NULL` por causa do
     `fix_duplicatas_chave_natural.sql`; IDs de recurso resolvidos por `package_show` a cada carga).
     Pendurado no cron do SIGCON (`run_sigcon_cron` e `run_queue_sigcon`) **logo após o backfill
     do CKAN**, que é quem promove o `nr_siafi`; auto-limitado a 1×/dia (`SEGOV_MIN_INTERVAL_H`,
     `SEGOV_FORCE`, `SEGOV_ENABLED`). `ingestion_log` source `segov_pagamentos`, status honesto em
     `status_coleta.segov_pagamentos`. Sem task nova no Coolify.
   - RM (`rm_builder`, item estadual): **Situação do NEs** (NE, valor, data do *registro do
     empenho*, pago), **Valor empenhado**, **Empenhado: Sim** e — só quando o Joomla não
     respondeu — `valor_desembolsado` = total pago (→ "Desembolsado: R$ …" ou "Pendente de
     desembolso" quando há empenho e nada pago). **Não fabrica lançamento com data**: o CSV não a
     tem, e a caixa do PDF imprimiria a data do empenho como se fosse a do pagamento. A mesma NE
     vem em **dois arquivos** (pagamento do ano + restos a pagar do ano seguinte): `_segov_resumo`
     funde por (NE, UO, ano da nota) e rotula pelo **ano da nota** (`dt_empenho`), com o exercício
     do RP entre parênteses — senão "NE 634/2025 … pago R$ 0,00; NE 634/2026 (restos a pagar) …
     pago R$ 99.932,16" contava duas notas onde há uma.
2. **Cadastramento / R$ 0,00 aparecendo no RM** ("Seapa - SIGCON · Convênio 002567/2026 · R$ 0,00 ·
   Cadastramento · sem alterações registradas"). ⚠️ Eu li a tela como "não entram" e respondi que já
   estava fora — errado: a tela **era o RM**. A regra de ano (`_fed_retem`) só barra pré-empenho de
   anos **anteriores**; para ela Cadastramento é `ativa` e do ano corrente **entra**. E o comentário
   "Cadastramento não tem número nem vigência → segue fora" era falso (o 002567/2026 tem número com
   "/", e por isso ainda saía rotulado "Convênio"). Decisão do dono: **fora, sempre**. Corte próprio
   `_em_cadastramento` (palavra inteira, sem acento/caixa — **não** a substring "cadastr", que
   derrubaria o "CONVENIO CADASTRADO" celebrado que o backfill do CKAN insere), **antes** do
   `_fed_retem`, valendo para anual e completo. Teste: `test_cadastramento_fora_do_rm.py`.
3. **Creche 932836/2021 com "Desembolsado: R$ 0,00"** apesar de o SIMEC ter pago. O pago JÁ era
   coletado (`simec_termos`, desde 31/08: R$ 1.875.147,32 empenhados / R$ 572.978,05 pagos) mas
   saía como item separado. Decisão do dono: **na própria linha da creche, "em ambos" os RMs**.
   Junção **pelo nº do processo (SEI), dígitos apenas**: `transferegov_propostas.numero_processo`
   (do dado aberto diário, `NR_PROCESSO` — "número interno do processo" no dicionário do SICONV; não
   depende da sessão gov.br) × `simec_termos.processo`. No SIMEC a creche é 23400.002301/2021-01
   (medido, `simec_termos` id 6); **que o SICONV grave o mesmo número na 059522/2021 é hipótese até
   conferir em produção** — o repo não tem esse valor, e o builder loga quando há termo com processo
   e nenhuma voluntária casou. Sem processo igual **não junta**: casar por município+objeto é
   hipótese pior. O termo casado imprime **"Pagamento SIMEC/PAR: empenhado no SIMEC … · pago … —
   TC …, processo …"** na linha da voluntária ("no SIMEC" porque a linha já mostra o "Valor
   empenhado" das NEs do SICONV, e os dois diferem: R$ 819 mil × R$ 1,87 mi), o pago vira
   `valor_desembolsado` onde o SICONV não mediu e **zera o "a desembolsar" do SICONV** (a revisão
   pegou a caixa somando R$ 4,39 mi num convênio de R$ 3,82 mi), o marcador "Pendente de empenho"
   não sai quando o SIMEC tem empenho, e o item separado do Termo **não sai de novo**
   (`_simec_ja_exibidos`) — marcado **só depois** de a voluntária **entrar** (`add_item` passou a
   devolver bool): marcar antes fazia o recorte "pagas" perder o termo pago de uma creche que ele
   mesmo descartara. ⚠️ **"Em ambos" na prática:** `completo` é sempre True em produção (os dois
   chamadores) e o "anual" da tela é a **seleção de anos**; a creche (2021) sai em "Todos os anos"
   e em qualquer seleção que inclua 2021 — numa seleção só de 2026 não sai, como nenhum instrumento
   de 2021 (recorte por ano do RM, não desta mudança). O bloco dos termos ficou atrás do
   `if completo:` como estava. `numero_processo` é a **décima coluna pendurada no fim** do SELECT
   das voluntárias (`row[33]`).

**Conferir depois do deploy:** `Migration OK: add_segov_convenios_empenhos.sql` no boot dos seis;
após a primeira noite, em freitas `SELECT count(*) FROM segov_convenios_empenhos` > 0 e
`ingestion_log.source='segov_pagamentos'` com `success`; regerar o RM de Araújos (Auto-popular) e
olhar a **1261002153/2026** (estadual: NEs + Desembolsado) e a **932836/2021** (creche: linha
"Pagamento SIMEC/PAR" e "Desembolsado: R$ 572.978,05"). Se a creche não casar, o primeiro suspeito é
`numero_processo` vazio na proposta 059522/2021 — o dado aberto o preenche na rodada das 06:51 UTC.

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
dispara o deploy ao fim de cada build, em duas ondas: todas as APIs, com migrations
confirmadas, e depois os workers dos tenants cuja API subiu, cada um assim que ficar sem
coleta em voo (janela em paralelo, teto de 15 min para a onda). Falha = rollback de tag +
run vermelho.
`is_auto_deploy_enabled` agora está **false** nas 9 (o webhook recriava containers com a
tag antiga e matou coleta em voo). Mecânica e provas em [`INFRA.md`](INFRA.md) §2 e nos
próprios workflows. **Tratar todo merge na `main` como um deploy em produção.**

**Carteira Freitas = 44 municípios ativos** (lista oficial de 09/08; 18 ex-clientes com
`active=false` e histórico preservado — NUNCA deletar município, desativar).

---

## 3. INFRA NO COOLIFY (como mexer)

Resumo; o detalhe completo (uuids de todas as aplicações, bancos, crons por tenant) está no **[`INFRA.md`](INFRA.md)**.

- **Servidor:** **AWS Lightsail `54.232.208.118`** (sa-east-1a, São Paulo). **8 vCPU / 32 GB RAM / 640 GB SSD** (plano "Uso geral"), hospeda mais 10 projetos além do PACTHA. ⚠️ **Esta linha dizia "t3.large, 2 vCPU, burstable, baseline 30%" até 09/09/2026** — o upgrade já tinha sido feito havia tempo, para as coletas correrem mais rápido, e a doc não acompanhou. Medido em 09/09/2026 com os SEIS workers coletando ao mesmo tempo: load **3.97** em 8 CPUs, 24 GiB de RAM disponíveis, disco em 6%. **Pode paralelizar trabalho pesado** — medindo antes e depois, porque o host é compartilhado.
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
5. **Gatilho on-demand virou FILA no Postgres.** O `POST /api/convenios/refresh-sigcon` (que no repo original disparava um redeploy remoto via API da plataforma) grava na tabela `scraper_jobs`; `backend/ingestion/run_queue_sigcon.py` consome, via Scheduled Task `queue-sigcon`, com dedup pending/running. CORS é env-driven (`main.py`).
6. **`setup_db.py` roda no BOOT da API** (`backend/services/startup.py`, dentro de `run_migrations`, antes das migrations incrementais). Idempotente (CREATE IF NOT EXISTS + seed só se `users` vazio). No Coolify não há passo manual "rodar setup_db uma vez" — isto se auto-cura em deploy novo. Desde 15/09/2026 o SQL dele (`SCHEMA_BASE_SQL`) entra no registro `migrations_aplicadas` e só roda de novo quando muda (ver §5).
7. **Frontend faz proxy same-origin de `/api`.** `rewrites()` em `frontend/next.config.ts` repassa `/api/:path*` para o host interno da API (`API_PROXY_TARGET`, **build-time**), e a API não precisa ser same-site com o front. Com isso cookies httpOnly + CSRF + refresh silencioso funcionam. Ver §5.

---

## 5. ARMADILHAS / GOTCHAS (leia antes de debugar)

- **A máquina tem 8 vCPU e 32 GB** (não é mais burstable de 2 vCPU — ver o bloco do servidor acima). `SIGCON_CONCURRENCY=1` continua, mas por causa do **portal**, que recusa e chega a bloquear credencial sob paralelismo — não por falta de CPU. Os crons seguem escalonados para não bater seis vezes no mesmo portal federal no mesmo minuto. Sintoma de estouro, se houver: tudo no host fica lento ao mesmo tempo, não só o PACTHA — confira com `uptime` antes de culpar a aplicação.
- **Coolify STRIPPA o path do domínio.** Se você setar o domínio de um app como `host/api`, o Coolify tira o `/api` antes de chegar no container (testado: `host/api/health`→404, `host/api/api/health`→200). Por isso a API tem **subdomínio próprio SEM path**, e o caminho normal do usuário é o proxy do Next (`API_PROXY_TARGET`).
- **`*.sslip.io` é public suffix** → `pactha-...sslip.io` e `pactha-api-...sslip.io` são **cross-site** entre si; cookies `SameSite=Lax` httpOnly não trafegam entre eles. É exatamente por isso que existe o proxy same-origin no Next (decisão 7). **Se alguém apontar o front direto no subdomínio da API (`NEXT_PUBLIC_API_URL` absoluto), o refresh silencioso quebra e volta o re-login a cada ~60min.**
- **`API_PROXY_TARGET` e `NEXT_PUBLIC_*` são BUILD-TIME.** Mudar o valor no Coolify sem rebuildar o frontend não tem efeito nenhum. Marque `is_build_time:true` e redeploy.
- ~~**`transferegov_propostas` é criada tarde** nas migrations~~ — **RESOLVIDO.** A tabela foi movida para o `setup_db.py` (`CREATE TABLE IF NOT EXISTS`, hoje na linha 105), que é exatamente o conserto que este parágrafo propunha. **A lição fica, porque a classe do bug voltou:** migration que ALTERA tabela criada mais tarde em `MIGRATION_FILES` só quebra em **banco novo do zero** — invisível nos bancos herdados. Foi assim com `transferegov_propostas` e de novo com `add_detalhe_pagina_rodizio.sql` quando o Nova Palma nasceu (01/09). Hoje há guarda automática: `backend/tests/test_migrations_ordem_tabela.py`. **Não fixe aqui quantas são** — o número muda toda semana e este parágrafo já disse 22 e depois 105 quando eram outras tantas; conte com `len(MIGRATION_FILES)` em `backend/services/startup.py`, ou leia `Startup migrations: N/N executadas` no log do boot. O que não muda é a invariante: **`add_auditoria_imutavel.sql` é sempre a última da lista** (instala o gatilho append-only do `audit_log`; qualquer migration que ainda precise escrever nessa tabela tem de vir acima).
- **O boot da API esperava lock de coleta — resolvido em 15/09/2026 pelo registro de
  migrations aplicadas.** DDL "idempotente" (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`,
  `CREATE INDEX IF NOT EXISTS`, `DROP ... CASCADE`) pede lock mesmo quando não muda nada.
  Com a lista inteira rodando a cada boot, um coletor com transação longa travava o boot:
  o healthcheck do Coolify desistia em ~1 min, o container antigo voltava e o workflow
  **não trocava o worker daquele tenant**. Aconteceu na api-freitas em 15/09/2026, com o
  `sigcon` rodando.
  - **Como ficou:** `migrations_aplicadas` guarda o checksum de cada arquivo e do schema
    base; o boot só roda o que é novo ou mudou. Medido local, o boot normal leva 0,7 s e
    passa livre com leitura ou escrita aberta em `municipios`, `users`,
    `convenios_estadual`, `parlamentares`, `obrasgov_projetos` e `audit_log`. Regras na
    skill `migrations`.
  - **O que sobra:** o deploy que traz migration NOVA de DDL ainda pede o lock daquela
    tabela uma vez. Deploy desses vai fora da janela de coleta (depois das 10:00 UTC).
  - Achados no caminho, corrigidos:
    - o `setup_db.py` recriava oito tabelas do refactor lean que o `drop_lean_tables.sql`
      derrubava;
    - o `add_obrasgov.sql` recriava o índice único global que a migration seguinte
      derruba. Na Freitas, na Trust e na BGK isso falhava por duplicata e o runner antigo
      logava "já aplicada".
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
- **Diff gigante numa mudança pequena = fim de linha, não código.** Desde 07/09/2026 o repositório é **LF em todo arquivo de texto** (`.gitattributes`, `* text=auto eol=lf`); antes disso 67 arquivos estavam gravados em CRLF e 2 já misturavam as duas convenções. O sintoma é sempre o mesmo: uma edição de 100 linhas chega ao revisor como 845, e o revisor deixa de ler — foi assim que o defeito foi notado. Duas coisas que não são óbvias: **`eol=lf` não conserta blob já commitado** (age só no checkout, assumindo que o blob está em LF — quem reescreve é `git add --renormalize .`), e **PDF precisa de `binary` explícito**, porque a heurística do byte NUL pode não achar NUL nos primeiros 8 KB e "normalizar" o arquivo o corrompe. Os commits de formatação ficam em `.git-blame-ignore-revs`, senão o `git blame` responderia "CRLF→LF" para 35 mil linhas; localmente, uma vez por clone: `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

---

## 6. PENDÊNCIAS

> 📍 **O backlog por estado vive em [`docs/BACKLOG_POR_ESTADO.md`](docs/BACKLOG_POR_ESTADO.md).**
> Ele confere o plano da auditoria de 17/08/2026 contra o repositório (conferência de
> 25/08: **o plano não foi executado**) e lista, na ordem de prioridade do dono
> — **MG → RS → GO → ES → TO** —, o que falta em cada estado, com arquivo/linha já
> verificados. As decisões da Onda 0 e o achado do CAGEC (falha em massa em 17-18/08)
> estão lá. Ler antes de abrir frente nova de cobertura estadual.


### 6.0 Em cima da mesa (08/09/2026) — o que a última sessão deixou decidido pelo dono

1. **GO, ES e TO — a regularidade estadual sem coletor.** É a maior lacuna de cobertura:
   **12 dos 20 municípios do trust**. Pesquisa feita, decisão adiada (*"depois falamos dos
   outros"*). Recomendação registrada: fazer **já** a certidão da CGE/TO e a dívida ativa de
   GO, que são **públicas e sem credencial**, e pedir SIGECON/CRCC em paralelo — não deixar
   os dois públicos parados esperando o credenciado.
2. ✅ **O watchdog já avisa — RESOLVIDO em 08/09/2026** (§1.22). Canal Telegram
   (`pactha_watchdog_bot`), ligado e **provado em produção nos cinco workers**: mensagem
   disparada de dentro do container do `freitas` e do `novapalma-rs`, `telegram: HTTP 200`
   nos dois. Era o item que já tinha custado 6 dias de regularidade estadual parada (§1.18).
   **O que ainda não existe é o pulso externo** (`WATCHDOG_HEARTBEAT_URL`, código pronto e
   env vazia): sem ele, worker morto continua indistinguível de coleta saudável. Falta só a
   conta no healthchecks.io e **cinco checks, um por tenant**.
3. **Senhas de Bueno Brandão a rotacionar** — SISMOB e InvestSUS, coladas no chat de
   07/09 pelo próprio dono, que já disse que ia rotacionar. Duas notas: o SISMOB é **sessão
   única** (entrar derruba quem estiver logado) e a conta tem **1 alerta pendente** que
   ninguém viu.
4. **A conta `claude` na VPS expirou** (`Your account has expired`, medido 08/09). O acesso
   que funciona é o `root` documentado no [`INFRA.md`](INFRA.md) §1.
5. **Cosmético, mas mente:** o summary do `build-frontend.yml` imprime *"4 frontends
   confirmados"* quando dá tudo certo — string parada de antes do Nova Palma. O deploy está
   correto (5 confirmados no log); é o texto.

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

**Canal do watchdog** (`WATCHDOG_TELEGRAM_TOKEN` + `WATCHDOG_TELEGRAM_CHAT_ID`) e
**pulso externo** (`WATCHDOG_HEARTBEAT_URL`). Vão no **worker**, não na API. As três são
opcionais e independentes: faltando qualquer uma das duas do Telegram, o canal sai calado
(canal pela metade é canal nenhum); sem a do pulso, o vigia externo simplesmente não existe.
Uma mesma conversa do Telegram serve os cinco tenants — a mensagem carrega o
`INSTANCE_SLUG`, então dá para saber de quem é o alerta. ⚠️ **O pulso precisa de uma URL
POR TENANT** (um check por worker no healthchecks.io): cinco workers pulsando a mesma URL
faz quatro workers mortos passarem despercebidos enquanto um único vivo mantém o check
verde. Detalhe do desenho em §1.22.

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
- **Rodar um scraper na mão:** dispare a Scheduled Task correspondente no worker do tenant (ou `POST /api/convenios/refresh-sigcon` autenticado → enfileira, e a task `queue-sigcon` consome em ≤30min). Lembre: scraper com login (SIGCON) só produz dados se o **Cofre daquele tenant** tiver credenciais. O FNS deixou de precisar: `run_fns_local.py` usa a API pública do ConsultaFNS, e o `fns_scraper.py`, que usava sessão, foi apagado em 15/09/2026.

---

## 8. AO MEXER NO CÓDIGO, LEMBRE

Uma alteração aqui vai para **os cinco clientes**. Antes de commitar:

- Migration nova precisa ser **idempotente** e rodar limpa nos cinco bancos (ela executa no boot da API) — **e num banco criado do zero**, que é onde erro de ordem aparece (ver §5).
- Feature que depende de env var nova: ou tem default seguro, ou você seta a env nos **cinco** resources.
- Nada de aumentar concorrência de scraping "porque tá lento" — ver §5, a CPU é compartilhada com 10 outros projetos.
