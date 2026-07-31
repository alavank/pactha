# Painel de Indicadores e Modo Tela

Superfície executiva do PACTHA — a que o **prefeito e os secretários** usam.
Ligada por instância pela flag build-time `NEXT_PUBLIC_BI_MODULE=1` (hoje só
Monte Sião/MG). Sem a flag, `/dashboard` continua sendo o dashboard operacional
de sempre e nada abaixo se aplica.

## Onde fica

| Rota | O que é |
|---|---|
| `/dashboard` | **Painel de Indicadores** — dentro do sistema, com a barra lateral |
| `/tela` | **Modo Tela** — janela separada, sem menus, para TV/projetor |
| `/bi`, `/bi/*` | redirects para `/dashboard` (endereços antigos) |
| `/bi/tv` | redirect para `/tela`, **preservando `?kiosk=`** |

Antes existiam dois menus (Dashboard + Painel de Indicadores) para o mesmo
público. Agora é um só: o item "Painel de Indicadores" da barra lateral aponta
para `/dashboard`.

## As sete abas

Definidas em **um lugar só** (`frontend/src/lib/tela.ts`, `ABAS`) e renderizadas
pelos **mesmos componentes** (`frontend/src/components/bi/abas.tsx`) no módulo e
na TV — muda só a densidade (`tv`: fonte maior, menos linhas, sem rolagem).
Mexeu numa aba, mexeu nos dois lugares.

| Aba | Endpoint | Conteúdo |
|---|---|---|
| Visão Geral | `/api/bi/overview` + `/api/bi/alertas` | captação, CAUC, em execução, vencendo, prestação de contas |
| Parlamentares | `/api/bi/parlamentares/detalhe` | cada parlamentar com suas emendas: **destinação** e **finalidade** |
| TransfereGov | `/api/bi/transferegov` | voluntárias + Novo PAC, por situação e por órgão |
| Verbas Estaduais | `/api/bi/estaduais` | convênios SIGCON-MG + emendas estaduais |
| CAUC e CAGEC | `/api/bi/documentos` | exigências regulares e pendências impeditivas |
| Fundo Nacional de Saúde | `/api/bi/fns` | propostas do FNS, já consultadas |
| Obras da Saúde | `/api/bi/sismob` | obras do SISMOB: prazo de norma vencido, repasse parado, execução por programa |

Cada aba é **um request só**: a TV troca de aba a cada 60 s e não pode disparar
uma cascata a cada virada. Todas passam pelo mesmo cache TTL (45 s) com
single-flight do overview; o FNS tem cache próprio de 15 min porque consulta um
portal externo lento.

### CAGEC é coletado desde 30/07/2026

> Este trecho dizia "nenhum scraper coleta CAGEC hoje". **Deixou de ser
> verdade** e ficou perigoso: quem lesse concluiria que CAGEC vazio é o
> esperado, quando na prática significa que a coleta falhou.

Existe scraper dedicado (`backend/ingestion/cagec_scraper.py`), cron próprio
(`40 5 * * *`, hoje só em Monte Sião — ver `INFRA.md` §5) e uma linha por
**entidade**, não por município: prefeitura, Fundo Municipal de Saúde, Fundo
de Assistência Social. `bi_documentos` devolve `cagec.disponivel: true` com os
itens; para os tenants sem o cron, continua `false` com o motivo — o princípio
original vale: verde sobre dado não verificado é pior que ausência.

Isto sustenta o cruzamento **R7** do módulo de obras: `sismob_obras.nu_cnpj`
× `cagec_situacao.cnpj` responde se o fundo que executa a obra federal está
cadastrado no CAGEC-MG. Foi por CNPJ, e não por nome, que se descobriu que o
Fundo Municipal de Saúde de Monte Sião **está** cadastrado e regular — a busca
por nome não o achava porque o registro não traz o nome da cidade.

## Período multi-ano

Um prefeito filtra **o mandato**, não um ano. `anos` é uma lista em toda a
cadeia; `ano` (int) segue aceito por compatibilidade e é somado à lista
(`services/bi.py:anos_list`). A fonte do ano difere por tabela:

- `convenios_estadual`, `emendas_estaduais` → coluna `ano`
- `transferegov_propostas`, `transferegov_pac` → sufixo de `numero_proposta` (`xxx/AAAA`)
- Plano de Ação (RP9, ao vivo) → dígitos 5-8 de `programaCodigo`

⚠️ **Duas abas ignoram o período de propósito:** `CAUC e CAGEC` (que nem recebe
`anos`) e `Obras da Saúde`. Nas duas, o dado é **estado atual**, não fato
datado. Em obras isso já custou caro: a aba filtrava por `ano_referencia` (o
ano da *proposta*), e com "Mandato atual" selecionado ela dizia
"0 com prazo vencido / R$ 0 parado" enquanto a tela do módulo, no mesmo
minuto, mostrava 3 obras e R$ 249.648 parados — porque as obras problemáticas
são propostas de 2012 e 2020 ainda em aberto. **Antes de filtrar uma aba por
ano, pergunte se o ano da coluna é o ano do problema.** A aba avisa na tela
que não filtra, senão "troquei o período e nada mudou" vira "a aba travou".

⚠️ O cache de narrativa/insights (`painel_narrativa_cache`) tem `ano` **inteiro**
na chave primária. Um período com vários anos vai com `ano = 0` e o período
entra no campo `kind` — senão 2021-2024 e 2022-2025 brigariam pela mesma linha.

## Modo Tela

Abre por `window.open` com um nome fixo (`pactha_modo_tela`), então clicar duas
vezes não espalha janelas.

**Quem manda no relógio é a janela da tela.** Ela roda o cronômetro, publica o
estado a cada 500 ms num `BroadcastChannel` e obedece comandos. O painel só
escuta e interpola entre uma publicação e outra (por isso a rosca gira liso sem
60 mensagens por segundo). Se parar de chegar estado por 4 s, o painel some com
o controle — foi janela fechada.

Os **filtros** vão no sentido contrário: quem manda é o painel. Filtrou no
módulo, a TV já mostra filtrado. Na abertura eles também vão pela URL
(`?scope=&anos=`), que é o caminho de fallback num navegador sem
`BroadcastChannel`.

Controles (rosca de contagem + play/pause/avançar/retroceder) aparecem **nos
dois lugares**: ao lado do botão "Modo Tela" no painel e no topo da janela.
Padrão de 60 s por aba (`DURACAO_PADRAO_MS`). Na janela também valem
`espaço` (play/pause), `←`/`→` (abas) e `f` (tela cheia).

## Insights da IA

`/api/bi/insights?aba=…` devolve uma **lista** de 2 a 4 frases curtas sobre a
aba aberta, que passam em slideshow no cabeçalho. Uma aba costuma ter mais de
uma coisa importante a dizer. Cache por `input_hash`, igual à narrativa.

Sem `ANTHROPIC_API_KEY` (ou se a chamada falhar), cai num texto por template
montado dos próprios números — a faixa nunca fica vazia e nunca quebra a tela.

## Design

Referências em `design-tela/`. O BI **destoa de propósito** do resto do sistema:
preto quase puro no escuro, cinza-claro no claro, cartões de raio grande, acento
menta, paleta de gráfico pastel, números tabulares grandes. Tudo isso vive
escopado em `.bi-skin` (`globals.css`) para não vazar nas telas operacionais,
que seguem com o tema "Base" violeta. Claro e escuro são ambos suportados.
