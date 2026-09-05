# Agendamentos — a agenda de compromissos da equipe

> Especificação viva do módulo. Última atualização: **05/09/2026** (rodada 1 de ajustes).
> Código: `backend/routers/agendamentos.py`, `backend/services/agendamentos_export.py`,
> `frontend/src/app/dashboard/agendamentos/`.
> Referência visual: `design-tela/schedule-inspiration/`.

Todo o resto da plataforma mostra dado que vem de fora. **Este é o único módulo em que a
equipe escreve**: o compromisso marcado, a que horas, quem pediu, em que pé está e o que
foi sendo anotado a respeito.

---

## 1. As decisões que sustentam o resto

### 1.1. Fonte única de dados

As três abas (Calendário, Kanban, Lista) e o card lateral leem o **mesmo**
`GET /api/agendamentos`, carregado uma vez em `page.tsx`. Trocar de aba não busca nada e não
pode divergir; qualquer alteração — salvar, arrastar no quadro, anotar — chama `recarregar()`
e as quatro superfícies acompanham sem F5.

⚠️ **A consulta não tem recorte de data, de propósito.** Cada aba precisa de uma janela
diferente (o mês navegado, o quadro inteiro, «Este mês») e o card precisa de hoje; recortar
no servidor obrigaria a uma busca por aba, e aí acabou a fonte única. O que a API recorta é
o que **todas** respeitam: a carteira do usuário, o filtro de município e a busca.

### 1.2. Município implícito na prefeitura, obrigatório na assessoria

Quem decide é o **backend** (`GET /agendamentos/contexto`), pela contagem de `municipios`
ativos do **tenant** — nunca pelo tamanho da carteira de quem está logado. Numa assessoria de
42 cidades, um usuário com uma cidade só cairia no modo prefeitura e criaria compromisso sem
escolher.

⚠️ **`municipio_id` é `NOT NULL` no banco**, contra a letra do documento de redesenho (que
pedia nulo em prefeitura). Nulo quebraria três coisas que já existem: o JOIN de `municipios`
(INNER — a linha sumiria), o recorte de carteira (`= ANY(:mids)` **nunca casa com NULL**, e o
compromisso ficaria invisível para todo usuário de carteira restrita) e o carimbo da trilha.
O que o documento quer — *o município é implícito* — está entregue **na tela**: num tenant de
um município só não há campo, filtro nem coluna de município em lugar nenhum, e
`_municipio_implicito` preenche a coluna.

### 1.3. O módulo ignora o município do menu lateral

Numa assessoria a agenda é da casa, não da cidade em acesso. O filtro de município é próprio
da toolbar (multi-seleção, **todos** por padrão). Trocar o escopo global remonta o dashboard
inteiro (`key={escopo}` em `dashboard/layout.tsx`) e leva a pessoa para a home — perder a
semana que ela estava olhando só para conferir a agenda da cidade vizinha é caro demais.

### 1.4. Anotação é append-only

Não existe rota de editar nem de apagar anotação, e **a trava é essa ausência** — o banco não
tem trigger para isso (diferente do `audit_log`). Anotar também **não** passa por
`exigir_dono_da_linha`: o alcance por linha restringe quem *altera* o registro alheio, e
anotar cria linha nova assinada por quem escreveu.

### 1.5. Uma lista só, sempre no backend

A **paleta de cores** (9 tons, `GET /paleta`) e as **colunas do kanban** (`GET /colunas`) vêm
da API. Este repo já pagou caro por listas gêmeas que divergem — os três status do kanban
viveram em três lugares ao mesmo tempo. Na tela a cor é **receita, não tabela**:
`.ag-chip` / `.ag-solto-cor` / `.ag-pasta-*` montam fundo e texto com `color-mix` sobre os
tokens do tema, então o mesmo hex lê bem no claro e no escuro sem uma segunda paleta.

---

## 2. Modelo de dados

### `agendamentos` (o compromisso)

| coluna | tipo | nota |
|---|---|---|
| `municipio_id` | INT NOT NULL, FK | ver §1.2 |
| `demanda` | VARCHAR(200) NOT NULL | era `titulo` até 05/09/2026 |
| `data` | DATE NOT NULL | DATE e não TIMESTAMPTZ: não tem fuso |
| `hora_inicio` | TIME NOT NULL | DEFAULT `08:00` para a linha anterior ao campo |
| `tem_periodo` | BOOL NOT NULL | intenção do formulário; **não** é o que o desenho consulta (§4.3) |
| `hora_fim` | TIME | NULL sempre que `tem_periodo` é falso |
| `data_solicitacao` | DATE | quando a demanda chegou |
| `solicitante` | VARCHAR(120) NOT NULL | DEFAULT `''`: na linha antiga essa informação **não existe**, e inventá-la seria pior |
| `contato_whatsapp` | VARCHAR(11) | **só dígitos**; a máscara é da tela |
| `cor` | VARCHAR(7) NOT NULL | hex da paleta; DEFAULT = primeira cor |
| `coluna_id` | INT NOT NULL, FK | substituiu `status` |
| `criado_por`, `created_at`, `updated_at` | | |

**Colunas legadas que continuam de pé, sem serem lidas:** `status`, `relato`,
`responsavel_id`, `anexos`. Nenhum `DROP` — DROP em cinco bancos é irreversível num boot que
o runner engole em silêncio se falhar. O `relato` antigo foi migrado para a **primeira
anotação** de cada compromisso; o anexo já gravado continua sendo servido pela rota com
permissão própria (`agendamentos.anexo_baixar`) e aparece no modal de detalhe — o formulário
novo não anexa mais.

### `agendamentos_colunas` (o quadro)

`id`, `nome`, `ordem`, `fixa`, `chave` (UNIQUE, só nas fixas), `cor`.

- Três iniciais, semeadas por **chave**: `solicitada`, `em_andamento`, `concluida`. A chave
  existe porque SERIAL não promete o mesmo id nos cinco bancos, e o código precisa achar a
  coluna de entrada.
- ⭐ **Todas** as colunas — inclusive as três — podem ser **renomeadas e coloridas**
  (mudou em 05/09/2026). Renomear **não** toca na `chave`.
- As três iniciais **não podem ser removidas**: apagar a coluna de entrada deixaria sem
  destino os cartões devolvidos por uma customizada removida.
- Até **2 customizadas**, teto absoluto de **5** — os dois validados na API, não só no botão
  (duas abas abertas contam separado).
- Remover customizada devolve os cartões dela para «Solicitada», com o número no aviso.

### `agendamentos_anotacoes`

`compromisso_id` (CASCADE), `autor_id` (SET NULL), `texto`, `created_at`. Append-only (§1.4).

### Migrations

1. `add_agendamentos.sql` — cria a tabela (02/09/2026).
2. `add_agendamentos_compromisso.sql` — o redesenho: rename, colunas novas, as duas tabelas.
3. `add_agendamentos_coluna_cor.sql` — `cor` no cabeçalho da coluna.

Registradas nessa ordem em `MIGRATION_FILES`; `test_agendamentos.py` cobra a ordem.

---

## 3. API

Todas sob `/api/agendamentos`, todas com `exige(...)` declarado.

| rota | permissão | nota |
|---|---|---|
| `GET /paleta` | `agendamentos.ver` | as 9 cores + o padrão |
| `GET /colunas` | `agendamentos.ver` | colunas + os dois tetos |
| `GET /contexto` | `agendamentos.ver` | `multi_municipio`, `municipio_implicito` |
| `GET /feriados?ano=` | `agendamentos.ver` | nacionais + estaduais das UFs do tenant (§4.7) |
| `GET ""` | `agendamentos.ver` | `municipio_id`, `municipio_ids`, `de`, `ate`, `coluna_id`, `q` |
| `GET /{id}` | `agendamentos.ver` | com o histórico de anotações |
| `POST ""` | `agendamentos.criar` | |
| `PUT /{id}` | `agendamentos.editar` | decide por `model_fields_set`, não por `is not None` |
| `PATCH /{id}/coluna` | `agendamentos.editar` | rota própria: arrastar muda **um** campo |
| `DELETE /{id}` | `agendamentos.excluir` | anotações vão junto (CASCADE) |
| `POST /{id}/anotacoes` | `agendamentos.editar` | sem alcance por linha (§1.4) |
| `POST/PUT/DELETE /colunas[/{id}]` | `agendamentos.editar` | tetos e `fixa` validados aqui |
| `GET /{id}/anexo/{idx}` | `agendamentos.anexo_baixar` | legado |
| `GET /relatorio/pdf` | `agendamentos.exportar` | `periodo`, `referencia` + o filtro ativo |

**Nomes de parâmetro em português** (`de`/`ate`), como o resto da API.

⚠️ **A busca (`q`) olha três campos e só eles**: nome do município, demanda e solicitante.
Ignora acento e caixa **sem `unaccent`** (a extensão não está instalada em nenhum dos cinco
bancos): o mesmo mapa de tradução é aplicado no SQL (`translate()`) e no Python
(`str.translate`), então o casamento é exato por construção.

⚠️ **`criar` e `atualizar` usam só `authz.exigir_municipio`** (a família nova de travas,
sujeita a `AUTHZ_MODO`). Acrescentar `ensure_municipio_access` faria a rota bloquear hoje,
fora da janela de observação que o resto do módulo respeita.

---

## 4. Tela

### 4.0. Ocupação e pele

- A rota está em **`telaCheia`** (`dashboard/layout.tsx`), junto com o Painel de Indicadores:
  o contêiner da página **não põe `px` nem `py`**, e o módulo cuida do próprio espaçamento.
  ⚠️ **Não a devolva para `TELAS_LARGAS`.** Ela esteve lá e o padding do contêiner recortava
  o fundo próprio do módulo numa **moldura do cinza do sistema** — 24px em cima e embaixo, e
  o que passasse de 1600px nas laterais. Margem negativa resolve só a horizontal. Sem padding
  externo, o fundo do módulo **é** o fundo da área útil.
- O módulo tem **altura de viewport** (`h-screen`) com `min-h-[34rem]` de válvula: em janela
  baixa quem rola é o `<main>`.
  ⚠️ **`h-screen` e não `h-full`**: o `<div key={escopo}>` que envolve a página é um bloco sem
  altura própria, e `height: 100%` sobre pai de altura automática resolve para `auto`.
  `h-screen` é exato porque a casca é `flex h-screen` e o `<main>` estica a altura toda, sem
  cabeçalho acima dele.
- ⚠️ **`min-h-0` em toda a cadeia flex.** Um filho flex tem `min-height: auto`, que trava a
  divisão da altura; sem ele o mês nasce do tamanho do texto, espremido no topo.
- **Pele própria, escopada**: `.ag-modulo` redeclara `--bi-bg`/`--bi-surface`/`--bi-line`
  (com equivalente escuro). Acento, CTA, links, aba ativa e foco continuam sendo os do
  PACTHA — é o que impede a agenda de virar outro produto. Nenhum outro módulo muda.
  A rampa final: chão `#fffefa`, cartão `#ffffff`, superfície recuada `#f7f5ef`, linhas
  `#e4e1d9` / `#cfcbc0`.
- ⭐ **NUM CALENDÁRIO, QUEM PINTA A TELA É A LINHA DA GRADE, NÃO O FUNDO** — foram três
  tentativas de cor até ver isso. A malha 7×5 do mês atravessa a tela inteira; o chão aparece
  só nos vãos entre os cartões. Medindo o "quanto de amarelo" em `r − b`, a 2ª tentativa
  ficou **mais** amarela que a 1ª com o chão mais **claro**, porque a linha subira de 20 para
  33. **Contraste se ganha na luminosidade; o calor se mantém constante ao longo da rampa.**
- ⚠️ **O degrau chão→cartão praticamente não existe** (0,37 de ΔL\*, contra 6,1 no tema do
  sistema). Quem separa o cartão da página é a **linha**, e por isso ela é um pouco mais
  escura que a do tema. **Não a enfraqueça "para combinar com o fundo mais claro"**: é o
  movimento intuitivo e é o contrário do que a conta pede. A tabela completa está no
  comentário do bloco `.ag-modulo` em `globals.css`.
  Pelo mesmo motivo, o **dia de fora do mês** sai de `--bi-surface-2` e não de uma mistura
  com o chão — que, tão perto do branco, o tornaria indistinguível do mês corrente.
- **Cabeçalho desgarrado** (`.ag-solto`): uma peça só, em três lugares — nomes dos dias da
  semana, cabeçalho de coluna do kanban, cabeçalho de coluna da lista.
  ⚠️ O vão entre os chips é **padding**, nunca `gap`: com `gap` a fileira ganha trilhas
  menores que as da grade embaixo e os dois desalinham progressivamente.

### 4.1. Interação — uma regra em toda parte (rodada 1)

| gesto | onde | o que faz |
|---|---|---|
| **hover** (200 ms) | calendário | balão: demanda, horário, solicitante, município |
| **um clique** | as três abas | modal de **detalhes** |
| **botão «Editar»** | dentro do modal | libera a edição |
| **duplo clique** | célula/slot **vazio** | cria, com data (e hora) pré-preenchidas |

⚠️ **Não existe mais duplo clique para editar em lugar nenhum.** Ter os dois gestos no mesmo
alvo obrigava o clique simples a esperar 250 ms antes de fazer qualquer coisa — a tela
parecia lenta em todo clique para servir a um atalho que quase ninguém achava.

### 4.2. Calendário

Mensal (padrão) | Semanal | Diária — só essas três. Header com ‹ Hoje ›, título, o
segmentado e «Adicionar compromisso». Card lateral «compromissos de hoje» à direita
(320px), sempre visível ao entrar; o ocultar dura **só a sessão** (estado de componente,
nunca `localStorage`).

- **Mensal**: chip por compromisso (hora + demanda). Quantos cabem por célula é **medido**
  com `ResizeObserver`, não chutado — a célula de um mês de 5 semanas é bem mais alta que a
  de 6. Excedente vira `+N` com popover.
- **Semanal/Diária**: régua 00–23 (48px/hora), linha do horário atual, header fixo e rolagem
  interna. Abre em 07:00 para não mostrar sete horas de madrugada vazia.

### 4.3. O período no calendário — o bug da rodada 1

Compromisso com período estava saindo como chip compacto na hora de início.

**Conserto**: quem decide o bloco esticado é a **hora de término**, não a bandeira
`tem_periodo` (`temPeriodo()` em `tipos.ts`). As duas informações são redundantes por
construção — o backend grava `hora_fim = NULL` sempre que `tem_periodo` é falso — e, quando
duas fontes dizem a mesma coisa, quem manda tem de ser **uma**. A escolhida é a que o desenho
precisa: sem hora de término não existe até onde esticar.

Com período o bloco vai de `hora_inicio` a `hora_fim`, altura proporcional, com demanda e
horário dentro; sem período é chip compacto de 30 min (piso — 10 minutos virariam uma faixa
de 8px). Sobreposição é repartida em colunas lado a lado (`repartirEmColunas`), com largura
igual dentro do aglomerado.

### 4.4. Kanban

- Colunas em `repeat(N, minmax(0, 1fr))` — 3, 4 ou 5 **sempre** dividem a largura, nunca há
  rolagem horizontal. O `minmax(0, ...)` é obrigatório: sem ele uma demanda longa estica a
  coluna.
- **Criar coluna é ação da toolbar da aba**, não uma coluna cinza no quadro (que impedia a
  divisão por igual). Some no teto.
- Cabeçalho desgarrado com a cor escolhida, nome e contador; lápis edita nome **e** cor.
- Cartões em **pasta** (`estilo-pastas.jpg`): aba recortada no alto, na cor da demanda.
- **Arraste próprio, sem biblioteca** — o projeto não tem lib de DnD, e trazer uma para
  inclinar um cartão custaria uma dependência nos cinco tenants. `pointer events` com:
  limiar de 6px antes de virar arraste (abaixo disso é clique, que abre o detalhe), overlay
  `fixed` que segue o cursor com **rotação de −3°, escala 1.02 e sombra forte**
  (`kanban-card-tombado.png`), origem apagada, vão tracejado no destino e `Esc` para
  cancelar. O `draggable` do HTML5 foi abandonado: ele não deixa estilizar o fantasma.
  ⚠️ O vão de destino vai **onde a ordenação por data/hora coloca o cartão**, não sob o
  cursor — a ordem da coluna não é manual, e prometer uma posição que o cartão não vai
  ocupar o faria "pular" ao soltar.
- Seletor de coluna em cada cartão, além do arraste: arrastar não funciona com teclado.

### 4.5. Lista

- **Seis colunas, nessa ordem**: Data | Horário | Solicitante | Município | Demanda |
  Situação. Município some em tenant prefeitura. Saíram contato e nº de anotações — são
  detalhe *do* compromisso, não critério de varredura, e roubavam largura da demanda. A
  tarja de cor na borda esquerda fica.
- Cada item é um **cartão comprido** com respiro entre eles, não uma tabela densa.
- Filtro de período: Hoje | Esta semana | Este mês (padrão) | Todos.
- ⚠️ **Um contador só**, abaixo da linha de filtros. Ele aparecia duas vezes e os dois
  números eram *diferentes* (recorte inteiro × período filtrado) — dois números com o mesmo
  rótulo na mesma tela é pior que nenhum.

### 4.6. Modal

Ordem dos campos (rodada 1) — conta a história na sequência em que o compromisso acontece:

1. **Data\*** 2. **Horário\*** (+ toggle «Definir período» → Início\*/Término\*; abre em
horário fixo) 3. **Solicitante\*** 4. **Município\*** (só assessoria) 5. **Contato
WhatsApp** 6. **Demanda\*** 7. **Data da solicitação** 8. **Cor** (swatches) 9. **Anotações**

A validação segue a **mesma ordem** — só uma mensagem aparece por vez, e apontar para um
campo abaixo do primeiro vazio faria a pessoa subir a tela a cada tentativa. A situação
aparece como selo, mas **não é campo**: ela muda no kanban.

### 4.7. Feriados

⭐ **Calculados, não coletados** (`backend/services/feriados.py`). É o único "dado
externo" do repo sem coletor, e de propósito: a regra está em lei e lei nova é mudança de
produto. Um scraper de feriado traria site de terceiro no caminho, selo de frescor e
watchdog para produzir uma tabela de cem linhas — e qualquer erro do fornecedor viraria
compromisso marcado no dia em que a prefeitura está fechada.

**Três tipos, com pesos diferentes na tela:**

| tipo | o que é | como aparece |
|---|---|---|
| `nacional` | os **dez** feriados nacionais | célula/chip com fundo `--bi-info-soft` e o nome |
| `estadual` | só das UFs dos municípios ativos do tenant | idem, com a UF no rótulo |
| `facultativo` | ponto facultativo federal | só o nome, em itálico e apagado |

⚠️ **Carnaval, Quarta-feira de Cinzas e Corpus Christi NÃO são feriados nacionais** — são
pontos facultativos (Portaria MGI 11.460/2025 para 2026: dez feriados e nove pontos
facultativos). A **Sexta-feira Santa**, sim, é feriado. Promover um facultativo a feriado
deixaria a tela afirmando o que a lei não diz, e é o erro fácil de cometer aqui porque na
prática quase ninguém trabalha na terça de carnaval.

⚠️ **UF só entra no catálogo com a lei conferida**, e cada linha cita o número dela. Os
agregadores de feriado da internet erram: o primeiro consultado dava ao Espírito Santo
"28/10 — Dia do Servidor Público" como feriado estadual, quando o próprio TJES publica essa
data como **ponto facultativo** e o feriado estadual capixaba é outro — **Nossa Senhora da
Penha**, móvel, a segunda-feira oito dias depois da Páscoa (Lei estadual 11.010/2019).
Estado sem linha mostra só os nacionais: **ausência é honesta; feriado inventado manda
alguém marcar visita num dia em que não há ninguém para receber.** Mesma disciplina de
`services/cadastro_estadual.py`.

Cobertos hoje: **MG** (Data Magna, que coincide com Tiradentes e não acrescenta dia),
**ES**, **GO**, **RS** e **DF**. Municipal fica **fora** — não há fonte, e é o que mais
varia (padroeiro, aniversário da cidade).

⚠️ **A mesma data pode ter dois registros** — 21 de abril é Tiradentes *e* Data Magna de
Minas. Quem calcula não escolhe um e esconde o outro; quem desenha junta os rótulos.

**Na tela**: célula do mês e chip do dia na semanal/diária marcados, com o nome; e um aviso
no modal quando a data escolhida cai em feriado — **informação, nunca bloqueio**. Marcar
compromisso em feriado é legítimo (plantão, mutirão); o que não pode é descobrir depois.

O ano é buscado **uma vez** e fica em cache no `page.tsx`; `anosNecessarios()` cobre a virada
do ano na borda da grade (a grade de dezembro mostra dias de janeiro).

---

## 5. Relatório PDF

Dia | Semana | Mês + data de referência. A **janela é calculada no backend** (`_janela`), pela
mesma regra de semana da grade (segunda a domingo) — calcular na tela criaria uma segunda
definição de "semana". Respeita o filtro ativo usando a **mesma `_filtros`** da lista.

A4 retrato, agrupado por dia, com o logo do tenant resolvido pela **mesma função do RM**
(`rm_pdf._logo_path`, importada e não copiada), rodapé `RM_RODAPE` e «Página N de M».
Anotações não entram: o relatório circula fora da plataforma.
Nome: `agendamentos-{dia|semana|mes}-{AAAA-MM-DD}.pdf`.

---

## 6. Fora de escopo (não fazer)

Outras views de calendário (agenda, ano). Mais de 2 colunas customizadas. Criação de
compromisso fora do calendário. Drag & drop no calendário, recorrência, compromisso
multi-dia, lembretes/notificações. Ordenação manual dentro da coluna do kanban.

---

## 7. Testes

`backend/tests/test_agendamentos.py` (67 casos) cobre, entre outros: a paleta contra o
DEFAULT do banco, as três chaves fixas contra o seed, o horário (término > início), a máscara
do contato, o `dados_b64` que nunca sai na listagem, a busca em três campos por bind, o
recorte de carteira, a janela do relatório, a ausência de rota de editar/apagar anotação, e
um que cruza o **número de colunas do `_SELECT`** com os índices que `_row_to_dict` lê — esse
defeito não levanta erro nenhum, só troca os valores de lugar na tela.

⚠️ O arquivo mascara comentários e docstrings antes das varreduras (`_so_o_codigo`): as notas
deste repo citam o código que elas proíbem, e sem isso o teste reprova o **conserto** em vez
do defeito.

Não há suíte de frontend no repo. A lógica pura de `tipos.ts` (datas sem fuso, horários,
sobreposição) foi conferida com asserções em Node durante o desenvolvimento.
