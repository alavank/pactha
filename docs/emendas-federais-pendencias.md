# Emendas federais — o que sobrou da varredura de 06/09/2026

> **Para decidir, não para executar.** Esta lista sai de uma varredura adversarial
> de seis frentes sobre o módulo (198 agentes, cada achado atacado por três
> céticos). Os que valiam correção imediata já foram feitos; o que está aqui é o
> que **exige uma decisão sua** ou cujo custo não se justifica hoje.
>
> Nada aqui é bug que produz número errado — esses foram todos corrigidos. O que
> resta é resiliência, custo e casos-limite.

## Como esta fonte quebra

Antes da lista, o padrão, porque ele vale para o próximo coletor:

**Sete dos treze defeitos desta fonte só apareceram com dado real e volume
real.** Nenhum foi pego por revisão de código, plano ou teste de unidade — e a
revisão aqui teve três agentes e um plano de 400 linhas. Os quatro primeiros
custaram cota e tempo; três custariam **dado errado na tela do gestor**:

| defeito | como apareceu |
|---|---|
| `varchar(20)` em `autor` | a rodada abortou na primeira carga completa |
| tela dava 500 (`x[25]`) | só ao chamar `buscar()` com carteira preenchida |
| R$ 4,05 bi de "empenhado" | só ao somar o payload de um município real |
| `fonte_ligada: False` com 64/67 consultadas | só ao chamar a tela pelo container da API |

**A lição operacional**: nesta casa, `python -m pytest` verde e CI verde não
dizem que a coisa funciona. O que diz é rodar contra o banco de produção e
**chamar a função que a tela chama**. Foi isso que achou os três últimos.

---

## Precisa de decisão sua

### 1. `validar_hipotese` gasta 20–40 requisições e joga fora

A amostra roda antes de cada rodada e descarta o resultado; o laço principal
reconsulta os mesmos códigos em seguida. Com a hipótese **já confirmada**
(20/20, autor batendo 100%), ela virou custo puro: ~15% da cota de uma rodada
pequena.

- **Manter** protege contra a CGU mudar o contrato sem avisar.
- **Remover** economiza, e o veto por autor no laço principal já pegaria o caso.
- **Meio-termo**: rodar a amostra só quando `codigo_confirmado` for falso em mais
  da metade da carteira.

*Recomendo o meio-termo.* Não decidi sozinho porque é trocar segurança por cota.

### 2. Nada apaga linha da carteira quando o CNPJ deixa de ser alvo

Se uma entidade sair de `municipio_entidades`, as emendas dela continuam na
carteira e no total. O número **só sabe subir**.

O conserto natural é `ausente_desde`, como `programas_captacao` e `sismob_obras`
já fazem — mas isso muda o que a tela mostra, e a decisão de esconder ou marcar
é sua.

### 3. O `flock` não atravessa tenants, e a chave é a mesma em dois

Cada worker tem seu lock. O invariante que impede dois tenants de baterem no
mesmo token ao mesmo tempo é **só o espaçamento do cron** (30 min), e nada no
código o conhece. Se alguém disparar duas tasks à mão, ou mudar um horário, a
proteção some sem aviso.

Custaria uma tabela de lock compartilhada ou um teste que leia as agendas do
Coolify. Hoje o risco é baixo — a rodada leva ~2 min contra 30 de espaçamento.

---

## Vale fazer, mas não é urgente

| # | o quê | por quê importa |
|---|---|---|
| 4 | `alvos()` e `semear_fila` engolem exceção **sem SAVEPOINT** | a transação fica abortada e a rodada morre depois com `InFailedSqlTransaction` — mensagem que não aponta para a causa |
| 5 | `agregado_da_emenda` descarta o `completo` do `paginar` | o mesmo defeito nº 3 (truncamento silencioso), vivo no endpoint do agregado. Hoje inofensivo: nenhuma emenda passa de 10 páginas de agregado |
| 6 | `_TAM_PAGINA` é global entre `/emendas` e `/emendas/documentos` | aprender o tamanho num encurta o outro. Mitigado (zerado por rodada), não resolvido |
| 7 | O índice único da CGU é btree sobre três colunas **TEXT** | teto de 2.704 bytes. É o novo `varchar(20)`: um texto longo da fonte derruba o UPSERT |
| 8 | `linha_documento` zera a linha do tempo se o formato de data mudar | dois formatos são tentados; um terceiro vira `None` em silêncio |
| 9 | Documentos são rebaixados a cada volta do rodízio | `documentos_em` e `n_documentos` são regravados mesmo quando a busca foi pulada |
| 10 | O gatilho dos ~2.000 itens é só prosa | nada mede, nada avisa. Um tenant de assessoria chega lá |
| 11 | **A tela de Parlamentares conta a emenda federal no resumo, mas não a lista no detalhe** | `por_fonte.emenda_federal` e `total_lancamentos` a incluem; `GET /parlamentares/detalhe` devolve **seis** listas (sigcon, voluntarias, emendas, plano_acao, pac, fns) e nenhuma delas. Quem abre a setinha não acha o que o cartão prometeu, e `total_geral` do detalhe não bate com o `total_lancamentos` da lista. Achado em 07/09/2026 ao trocar a grade de fontes por selos — a grade tinha o mesmo furo, só menos visível. Conserto: uma sétima consulta em `routers/parlamentares.py::detalhe` (a tabela `emendas_federais_carteira` já é lida no agregado, linha ~470) e um `GrupoFonte` na tela |

---

## Anotado e descartado

- **`max()` coluna a coluna sobre a CGU** — resolvido de fato pelo `LATERAL ... LIMIT 1`:
  com uma linha só, `max()` é ela mesma.
- **Índice redundante** e **`documentos_n` não usado no payload** — custo real
  perto de zero.
- **Emenda sem ano invisível no filtro padrão** — são 3 em Nova Palma, todas de
  2009 e vazias em tudo (sem autor, sem valor). Mostrar dá mais confusão que
  esconder.

---

## Estado em 06/09/2026, medido em produção

| | Nova Palma/RS | Monte Sião/MG |
|---|---|---|
| carteira | 77 linhas · 44 códigos | 55 · 33 |
| indicado | **R$ 13.682.127,98** | **R$ 12.237.769,16** |
| … prefeitura / entidades | R$ 12,28 mi / R$ 1,40 mi | R$ 11,96 mi / R$ 281 mil |
| execução consultada | 64 de 67 | 50 de 52 |
| parlamentares (pessoas) | 16 | 12 |
| impositivas | 27 | 22 |

Os valores batem **ao centavo** com a medição feita antes de existir código.

Freitas, Trust e Santa Maria têm as tabelas, a tela e a task — **sem a chave**.
A carteira deles popula sozinha na primeira madrugada; a execução fica com «—» e
a tela diz por quê.
