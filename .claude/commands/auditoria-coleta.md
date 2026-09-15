# AUDITORIA INDEPENDENTE — CONFIABILIDADE DA COLETA DE DADOS DO PACTHA

## Seu papel

Você é um auditor técnico INDEPENDENTE. Você não trabalha para o PACTHA nem
para o cliente. Você não defende o produto e não defende quem reclama dele.
Seu único compromisso é com a evidência: se o sistema estiver falhando, diga
onde, por quê e com prova; se o sistema estiver certo e a reclamação for de
uso, escopo ou expectativa, diga com a mesma firmeza. Conclusão sem evidência
citável não entra no relatório.

## Contexto

O PACTHA monitora convênios, repasses e emendas parlamentares para prefeituras,
coletando de 17+ fontes oficiais (federais + estaduais MG/ES/GO/RS/TO). O
cliente Freitas (assessoria que opera ~44 municípios, maioria MG) relata de
forma recorrente que "está faltando informação" ou que "a informação não veio".

Isso tem CINCO explicações concorrentes, todas plausíveis. Não assuma nenhuma:

- H1 DEFEITO DE COLETA — a fonte tem o dado e nossa ingestão não trouxe
  (falha, timeout, paginação, sessão expirada, parser quebrado)
- H2 DEFEITO DE EXIBIÇÃO — o dado ESTÁ no banco e não chega na tela
  (filtro, permissão, seletor de município, query da API, bug de frontend)
- H3 DADO NÃO EXISTE NA ORIGEM — a fonte oficial também não tem;
  o sistema está fiel à realidade
- H4 USO/DESCOBERTA — o dado está no sistema e a equipe não sabe onde
- H5 ESCOPO NOVO — nunca foi coletado porque nunca foi pedido/decidido

Cada caso investigado recebe UM desses vereditos, com evidência.

## Antes de começar

1. Leia CLAUDE.md, INFRA.md, CONTINUAR.md e docs/ — são handoffs de sessão
   mantidos atualizados e contêm decisões que explicam o estado atual.
2. Inspecione o schema real de `ingestion_log` e das tabelas de dados antes
   de escrever qualquer query — não presuma nomes de colunas.
3. Se a seção CASOS RELATADOS no final estiver vazia, PARE e me pergunte os
   casos antes do Bloco 1. Blocos 2 e 3 podem rodar sem eles.

## Regras invioláveis

- READ-ONLY: nenhum write/UPDATE/DELETE em banco algum — SELECT apenas.
  Nenhum commit em `main` (merge em main = deploy automático nos 4 tenants).
  Crie a branch `auditoria/coleta-$(date +%Y%m%d)` APENAS para os arquivos
  do relatório.
- Não execute coletor contra produção. Se um coletor tiver modo dry-run,
  pode usar; se não tiver, leia o código, não rode.
- Nunca transcreva credencial, cookie, token ou senha no relatório — nem
  parcialmente. Se encontrar segredo logado ou hardcoded, reporte o LOCAL
  (arquivo:linha), jamais o valor.
- Toda afirmação carrega sua prova: arquivo:linha, ou query executada +
  resultado resumido, ou URL oficial consultada + data de acesso.
- Se faltar acesso (banco de tenant, sessão gov.br viva), registre como
  LIMITAÇÃO DA AUDITORIA e siga — não estime no lugar do fato.

## BLOCO 1 — Triagem dos casos relatados pela Freitas

Para CADA caso da lista, rastreie o dado pelos três saltos e determine em
qual ele se perde:

  SALTO 1  Fonte oficial → banco do tenant freitas
           Verifique NA FONTE (web) se o dado existe lá hoje. Depois
           SELECT no banco. Existe na fonte e não existe no banco = H1.
  SALTO 2  Banco → API
           O registro está na tabela mas o endpoint não o retorna?
           Inspecione a query do router correspondente (filtros de
           município, período, status, permissão). Está no banco e não
           sai na API = H2.
  SALTO 3  API → tela
           A API retorna e a tela não mostra (aba errada, coluna oculta,
           seletor de município, label confusa)? = H2 ou H4.

Se o dado não existe nem na fonte oficial = H3 (prove com a URL e print/
trecho da consulta). Se existe na fonte mas nunca houve coletor/campo para
ele = H5 (aponte a ausência no código e verifique em CONTINUAR.md/git log
se houve decisão explícita de não coletar).

Saída do bloco: tabela caso → veredito (H1–H5) → evidência dos 3 saltos →
correção proposta (se H1/H2) ou resposta sugerida ao cliente (se H3/H4/H5).

## BLOCO 2 — Auditoria sistêmica da coleta

Uma análise externa do snapshot do repo levantou as hipóteses abaixo.
Trate-as como HIPÓTESES, não como fatos: o código pode ter mudado.
CONFIRME ou REFUTE cada uma com evidência atual, e diga o impacto real:

  A. `TG_HTTP_ENRICH` tem default "0" (transferegov_voluntarias.py ~727) —
     o caminho de enrich por HTTP (~10x mais rápido que o browser, ver
     transferegov_http.py) estaria desligado. Verifique nos envs reais dos
     tenants (INFRA.md / Coolify) se algum liga. Se está off em todos:
     por quê? Há registro de decisão?
  B. `lxml` é importado em transferegov_http.py e NÃO está no
     requirements.txt — chegaria só como dependência transitiva de
     python-docx. Confirme com `pip check`/`pipdeptree` no container ou venv.
  C. transferegov_voluntarias.py itera municípios EM SÉRIE com uma única
     page_guest (~linha 2326), enquanto run_fns_local.py:375,
     sigcon_scraper.py:1880 e sismob_obras.py:508 já usam
     Semaphore+gather. Cruze com o incidente documentado em
     transferegov_opendata.py (rodada abortada a 3600s cobrindo ~10 de 41
     municípios, sempre em ordem alfabética). Municípios do fim do
     alfabeto da Freitas são os que mais geram reclamação? Verifique no
     ingestion_log e cruze com os CASOS do Bloco 1.
  D. Nenhum arquivo de ingestion/ valida com Pydantic; base.py
     (parse_date_br, parse_decimal_br, clean_string) retorna None em
     silêncio quando o formato muda. Liste os campos exibidos no painel
     que podem virar NULL sem nenhum alerta.
  E. watchdog_coleta.py vigia processo travado e frescor, mas NÃO queda de
     volume: rodada 'success' com metade dos registros passa limpa.
     Precedentes no próprio repo: FNS 49%→99% ao sair do Playwright;
     CAGEC 9 dias falhando na Freitas sem alerta (comentário no próprio
     watchdog). Verifique se o ingestion_log guarda contagem por rodada
     suficiente para implementar detecção de queda.
  F. Zero HTTP condicional (ETag/If-Modified-Since) em ingestion/ — tudo é
     full refresh, o que limita a cadência de atualização.
  G. Vocabulário de status inconsistente no ingestion_log entre fontes
     (success vs ok/parcial/erro — caso CAGEC). Ainda há fonte fora do
     padrão que o watchdog não enxerga?
  H. CADEIA DE SESSÃO gov.br: os campos "gated" (detalhe de cláusula
     suspensiva, parlamentar, histórico /private/) dependem de sessão
     viva mantida por govbr_keepalive/govbr_renew/renovar_sessao_govbr +
     extensão de captura. Quando a sessão expira: o campo fica NULL? fica
     com valor velho sem carimbo? a tela indica algo? Esta é uma causa
     candidata FORTE de "às vezes a informação não vem" — trate com
     prioridade e meça no log quanto tempo as sessões ficam mortas.

Além das hipóteses, verifique:
- `except` genérico que engole erro e segue sem marcar a fonte como degradada
- httpx.AsyncClient sem timeout explícito
- coletores SEM orçamento/deadline de rodada (padrão _SIG_DEADLINE do sigcon)
- controle de ritmo por domínio gov.br além de Semaphore (risco de bloqueio)
- versões `>=` sem teto no requirements que podem quebrar build
  (playwright, curl_cffi, httpx)

Medições obrigatórias no ingestion_log do tenant freitas (adapte ao schema
real; janela: 30 dias):
- por fonte: última execução com sucesso vs cadência esperada
  (compare com FRESCOR_HORAS_* do watchdog)
- por fonte: série de contagem de itens por rodada — marque quedas >25%
- duração das rodadas do transferegov_voluntarias vs teto de 3600s
- por município da Freitas: dias desde a última atualização, por fonte —
  ordene e destaque os piores

RECONCILIAÇÃO AMOSTRAL (a prova mais forte da auditoria): escolha 5
municípios da Freitas (inclua os piores da medição acima e pelo menos um do
fim do alfabeto). Baixe o CSV de dados abertos do TransfereGov do dia,
filtre por COD_MUNIC_IBGE e compare com o banco: contagem de propostas,
instrumentos e valores. Divergência aqui é defeito de coleta PROVADO, sem
depender de relato de ninguém.

## BLOCO 3 — O método certo para cada fonte

Monte a tabela: fonte → método atual (API / CSV dados abertos / HTTP
autenticado / Playwright) → alternativa oficial melhor existe? →
recomendação → esforço.

Para responder "existe alternativa melhor", PESQUISE NA WEB agora (não
confie em memória): API e dados abertos do TransfereGov, dados.gov.br,
CKAN estaduais (dados.mg.gov.br e equivalentes de RS/ES/GO/TO), portais
FNS/SIMEC/SISMOB. Confirme endpoint vivo e cite a URL.

Hierarquia de preferência (justifique qualquer exceção):
  1. API/dado aberto oficial   2. HTTP autenticado (httpx/curl_cffi)
  3. Browser (Playwright) — só onde comprovadamente inevitável
     (SAML com JS obrigatório, ZK Framework, download gated)
O repo já provou essa direção duas vezes (FNS, transferegov_opendata) —
avalie o que ainda resta no browser sem necessidade.

Avalie também, com ceticismo, se alguma ferramenta externa mudaria o jogo
(Scrapling, ScrapeGraphAI, outra) — considerando que o repo JÁ TEM stealth,
impersonation TLS, deadline de rodada, watchdog e reaper próprios. Migração
de framework precisa pagar o risco de reescrever coletores que deployam em
4 tenants sem CI de teste. Se a resposta for "não vale", diga e encerre o
assunto.

## Auto-confronto (obrigatório)

Antes de fechar, para cada conclusão relevante escreva a melhor objeção
CONTRA ela (advogado do diabo) e responda: a conclusão sobrevive ou muda?
Registre as 3 objeções mais fortes e suas respostas no relatório. Inclua
explicitamente: "que evidência me faria concluir o contrário do que
concluí, e eu procurei por ela?"

## Entregável

1. `docs/AUDITORIA_COLETA.md` — fonte da verdade, na branch de auditoria.
2. PDF gerado a partir dele, salvo em `~/pactha-auditoria-coleta-AAAAMMDD.pdf`
   (fora do repo). Gere via pandoc se disponível; senão
   `pip install weasyprint markdown` e converta; se nada funcionar, me
   avise em vez de entregar só o .md. Confirme no final o caminho absoluto
   do PDF.

Estrutura do documento — DUAS PARTES, nesta ordem:

PARTE A — LEITURA EXECUTIVA (para não técnicos; zero jargão)
- Meia página de veredito geral honesto: "o sistema está falhando em X,
  funcionando em Y, e Z é expectativa/uso" — sem diplomacia vazia.
- Tabela da triagem Freitas: caso → veredito em linguagem simples →
  o que será feito.
- Para cada problema confirmado, um card curto:
  O PROBLEMA (uma frase) / POR QUE ACONTECE (explicação simples, use
  analogia se ajudar) / O QUE MUDA PARA QUEM USA / RESULTADO ESPERADO
  DEPOIS DO AJUSTE / ESFORÇO (P/M/G).

PARTE B — TÉCNICA
- Cada achado com severidade (crítico/alto/médio/baixo), evidência
  (arquivo:linha, queries + resultados, URLs), causa-raiz, correção
  proposta como diff pronto, e risco da mudança (lembrando: 1 repo →
  4 tenants).
- Resultado das medições e da reconciliação amostral, com números.
- Tabela fonte×método do Bloco 3.
- Backlog final ordenado por retorno/esforço, com dependências entre itens.
- Seção "Limitações desta auditoria" — o que não foi possível verificar
  e o que seria necessário para verificar.

Tudo em português. Comentários e commits em português (convenção do repo).