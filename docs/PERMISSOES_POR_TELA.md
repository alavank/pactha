# Permissões por tela — a regra do PACTHA a partir de 05/09/2026

> Spec do incremento que reescreveu Configurações › Usuários. Escrita a pedido do
> dono, junto da implementação.

## O que mudou, em uma frase

A permissão deixou de ser **duas listas que não casavam** (telas de um lado,
ações de outro) e passou a ser **três níveis encaixados: Módulo/menu › Tela ›
Ação** — com a árvore da tela de Usuários saindo do *mesmo objeto* que desenha o
menu lateral.

## 1. A granularidade

```
FEDERAIS                    ← Módulo (grupo do menu lateral)
  ├─ Em execução            ← Tela  (interruptor «Acesso»)
  │    ☑ Ver  ☑ Exportar    ← Ações (caixinhas)
  ├─ PAC (Novo PAC)
  │    ☐ Ver
  └─ …
```

Regras:

- **Liberar «Configurações» inteiro não existe.** Libera-se a aba — Usuários,
  Auditoria, Telemetria, Cofre, Sessões, Status dos Dados, Parâmetros — e dentro
  dela as ações.
- **Vale para todo módulo.** Em FEDERAIS dá para liberar «Em execução» e não
  «PAC»; dentro de «Em execução», liberar Ver e Exportar e não mais nada.
- **«Ver» é pré-requisito.** Marcar qualquer ação marca Ver junto; desmarcar Ver
  desmarca as demais daquela tela. Sem isso sairiam contas com «Excluir» e sem
  «Ver» — no servidor, alguém que apaga o que não consegue abrir.
- **As ações dependem da tela.** Usuários tem ver/criar/editar/excluir/redefinir
  senha/conceder; Auditoria tem ver/exportar; as telas de dado coletado
  (Convênios, TransfereGov, FNS, SISMOB…) têm ver/exportar/atualizar e **não
  têm** inserir/editar/excluir — o dado vem dos portais do governo, e a escrita
  “sobre” um convênio é a anotação da Gestão Interna, que é módulo próprio.
- **Alcance por linha** (todos os registros × só os que ele criou) continua
  existindo, só nos quatro módulos que gravam o autor: Gestão Interna,
  Agendamentos, Relatório de Monitoramento e Geração de Documentos. Aparece
  dentro da tela, e só quando Editar ou Excluir está marcado.

## 2. A árvore segue o menu do cliente

O PACTHA é adaptado por cliente: cada município e cada estado tem o seu menu.
A árvore de permissões **nasce desse menu**, e não de um catálogo global fixo.

| fonte | o que ela dá |
|---|---|
| `frontend/src/lib/menu.ts` | a **estrutura**: grupos, ordem, rótulos, rotas. O mesmo objeto que desenha a barra lateral. |
| `GET /api/permissoes/catalogo` | as **ações** de cada tela, com rótulo, descrição e UF. Fonte única no backend (`services/permissoes.py`). |
| `frontend/src/lib/telas.ts` | as **chaves** de `user_telas`. |

A dobradiça é `hrefToTela(href)` de um lado e `Permissao.tela` do outro; a junção
é `lib/arvorePermissoes.ts`. **Módulo novo aparece nos dois no mesmo deploy, sem
código novo** — que era o pedido.

O recorte por estado usa a **carteira inteira** do ambiente
(`ufsDaCarteira(municipios)`), e não o município selecionado na barra: quem
concede acesso concede para todos os municípios da pessoa. Módulo que só existe
em Minas não aparece para cliente do Rio Grande do Sul, e vice-versa.

⚠️ `backend/tests/test_arvore_segue_o_menu.py` lê os `.ts` do disco e quebra se
os dois lados divergirem. Uma tela no menu sem entrada no catálogo é um módulo
que ninguém consegue liberar; uma no catálogo sem folha no menu é uma caixinha
que concede o que não existe — foi assim que `suas` e `telegram` sobreviveram
meses depois de removidos.

### Três exceções, todas legítimas

- **Tela sem ação nenhuma**: o interruptor É a permissão. Hoje são «Painéis
  Municipais» (mural de painéis oficiais em iframe, sem endpoint próprio) e
  «Modo Tela (TV)».
- **Ação sem tela**: `transferegov.atualizar` — a coleta. O botão dela mora em
  Configurações › Sessões e alimenta as oito telas de FEDERAIS de uma vez.
- **Tela com abas, cada aba com a sua chave** (`abas` em `lib/menu.ts`). Hoje
  só «Emendas parlamentares» (17/09/2026): juntou quatro telas, e o dono decidiu
  que cada aba continua cobrando a chave que já existia (`emendas_federais`,
  `emendas`, `emendas_rs`, `parlamentares`). A folha não tem chave própria;
  aparece para quem tem qualquer uma das abas (`podeAbrirRota`), e na árvore
  vira um grupo com uma linha por aba. Ninguém ganhou nem perdeu acesso, e não
  houve migration de acesso.

### Caixinhas inertes ficam escondidas

Nove chaves existem no catálogo e não abrem rota nenhuma
(`services/permissoes.py::PERMISSOES_INERTES`). A árvore **não as desenha**:
caixinha que promete e não entrega é pior que caixinha faltando — o
administrador marca, salva, e nada muda. Elas voltam a aparecer no dia em que o
endpoint existir.

## 3. O cadastro

Um modal só (`UsuarioModal.tsx`) cria e edita, em três seções:

1. **Dados** — Nome*, E-mail*, **Perfil*** (abre **vazio**; só Administrador e
   Usuário), **Função na organização** (texto livre), **WhatsApp** (máscara BR),
   Ativo (na edição).
2. **Municípios** — só em ambiente multi-município. Em ambiente de um município
   só a seção **não é renderizada** e o vínculo é automático. A detecção é a
   contagem (`municipios.length === 1`), não um tipo de cliente configurado.
3. **Telas e permissões** — a árvore, com busca, expandir/recolher, liberar
   grupo, e **«Copiar o acesso de outro usuário»** com confirmação.

**Salvar é tudo-ou-nada**: `POST`/`PATCH /api/users` grava dados, municípios,
telas, ações e alcance num commit só. Antes eram duas chamadas, e um erro entre
elas deixava a pessoa cadastrada e cega — com a senha temporária já exibida na
tela e sem caminho de repetição, porque o e-mail já estava tomado.

### O perfil é só rótulo

Escolher «Administrador» não abre nenhuma tela. O perfil organiza a equipe do
cliente; quem concede são as telas, os municípios e as ações marcados em cada
usuário. Os perfis são cadastráveis por cliente (Configurações › Parâmetros).

**«Prefeito» saiu do cardápio** (decisão do dono). Sair da lista do código não
bastava — o rótulo está semeado na tabela `parametros` dos cinco bancos, e
`migrations/desativa_perfil_prefeito.sql` o desativa. Contas que já têm
`role = 'prefeito'` continuam válidas e o rótulo continua sendo traduzido.

## 4. O que foi removido, e por quê

### Modelos de permissão (os "moldes")

Removidos inteiramente a pedido do dono: *"nao quero modelos ou molde de
permissoes, pode tirar isso tudo, eu sei q é pra facilitar mas eu prefiro mais
ainda a forma de criar na mao um a um"*.

No lugar ficou **copiar o acesso de outro usuário**, agora também no momento da
criação. A diferença: a origem é uma **pessoa concreta**, que se pode conferir,
e não uma receita anônima reaplicável.

A tabela `modelos_permissao` fica no banco, sem uso. A chave `usuarios.modelos`
saiu do Python e da semente SQL; as linhas já gravadas em `permissoes_catalogo`
ficam dormentes (a FK de `user_permissoes` é `ON DELETE RESTRICT`).

### «Somente leitura»

Removida a pedido do dono: *"essa opçao somente leitura tb pode tirar isso, pq
era para o prefeito, nao precisa, prefiro dar permissao de visualizaçao separada
pra cada menu ou modulo dai eu permito so visualizar sem editar nada"*.

Era um atributo da conta que barrava **todo** POST/PUT/PATCH/DELETE fora do
Painel. O que ela fazia agora se faz desmarcando as caixinhas de escrita de cada
tela — **mais fino**: dá para ser leitor no Cofre e escritor na Gestão Interna na
mesma conta, o que a trava de conta nunca permitiu.

A coluna `users.somente_leitura` fica no banco, sem leitor.

⚠️ **O link público de TV não dependia disso** e continua barrado: `ehQuiosque` +
`KIOSK_GET_PERMITIDOS` em `services/auth.py`, mais o reforço pelo papel `viewer`.

### `AUTHZ_MODO` passou a ser `bloqueio` por padrão

⚠️ **É a linha de maior alcance do incremento**, e ela é a razão de as duas
remoções acima viajarem no mesmo deploy.

Até a véspera o modo era `aviso`: o `exige()` de cada rota **só registrava** na
trilha quem teria sido barrado. Quem impedia a escrita era exatamente a trava
«Somente leitura». Tirar uma sem ligar a outra deixaria o sistema **sem trava de
escrita nenhuma** — a consequência foi posta na mesa e o dono decidiu pelas duas
no mesmo deploy, com o argumento de que o sistema ainda é majoritariamente teste.

O fail-safe continua existindo, invertido: `AUTHZ_MODO=avisoo` (digitado errado)
**não desliga** a trava. Desligar virou o ato deliberado, e o caminho de recuo é
trocar a env para `aviso` exato no Coolify — sem deploy.

## 5. A migration, e o risco que ela cobre

`add_permissoes_por_tela.sql` roda em cinco partes, cada uma com o seu guard em
`migration_backfills`:

| parte | o que faz | por quê |
|---|---|---|
| 1 | `transferegov` → 8 telas, `convenios` → 10, `auditoria` → `telemetria` | é **rename**, não concessão: sem isto todo mundo perde os dois maiores grupos do menu |
| 2 | telas `usuarios`/`frescor`/`parametros` a todo admin ativo | as abas viraram telas de verdade |
| 3 | traduz as **ações** antigas para as telas novas | quem tinha `transferegov.ver` já via as sete telas ontem |
| 4 | deriva `user_permissoes` de `user_telas` **só para quem tem zero linha** | com `bloqueio`, conta sem caixinha perderia tudo |
| 5 | `usuarios.*` a todo admin ativo — **anti-lockout** | `_require_admin` virou `_exige_tela_usuarios`; sem isto um admin se tranca fora da tela que conserta o problema |

⚠️ **A assimetria da parte 4 é deliberada.** Quem *já tem* linha foi configurado
de propósito por alguém, e acrescentar caixinha desfaria uma restrição escolhida.
Quem não tem nenhuma nunca foi configurado, e até ontem isso não fazia falta.
Preservar o acesso de hoje é o contrato de uma migration; apertar é trabalho do
administrador na tela nova, com a árvore na frente dele.

`backend/tests/test_backfill_permissoes_por_tela.py` guarda cada uma dessas
invariantes.

## 6. Depois do deploy

1. Abrir Configurações › Usuários e olhar o aviso **«N conta(s) ativa(s) sem
   nenhuma ação marcada»**. Com `bloqueio` ligado, essas contas entram e não
   abrem nada — é a primeira lista a revisar.
2. Conferir que cada administrador tem a tela **Usuários** marcada (a migration
   garante, mas conferir custa um olhar).
3. Revisar quem ficou com o grupo FEDERAIS/ESTADUAIS inteiro por herança: a
   tradução preservou o acesso de ontem, que era mais amplo do que a
   granularidade nova permite escolher. Apertar agora é um clique por tela.
