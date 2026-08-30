# Auditoria independente — confiabilidade da coleta de dados do PACTHA

> **Data:** 29/08/2026 (medições entre 22:28 e 23:50 BRT; banco e Coolify do tenant **Freitas**).
> **Auditor:** independente (não defende o produto nem o cliente). Toda afirmação carrega a prova:
> `arquivo:linha`, query executada + resultado, ou URL consultada + data.
> **Regras seguidas:** nenhuma escrita em banco (toda sessão `psql` abriu com
> `SET default_transaction_read_only=on`), nenhum coletor disparado contra produção, nenhum
> segredo transcrito (a coluna cifrada `cofre_senhas.senha_hash` nunca foi selecionada; envs do
> worker lidas por *whitelist* de chaves não-sensíveis). Nada foi alterado em `main`.
> **Escopo:** Bloco 1 (3 casos relatados pela Freitas), Bloco 2 (hipóteses A–H + medições +
> reconciliação amostral), Bloco 3 (método certo por fonte), auto-confronto.
> Os arquivos de queries e saídas ficam em `docs/auditoria-coleta/` (sem dados sensíveis).

---

# PARTE A — LEITURA EXECUTIVA

## A.1 Veredito geral

**O sistema está coletando.** Nas últimas 30 dias nenhuma das 13 fontes vigiadas passou do prazo
de frescor; a contagem de propostas federais e de instrumentos do TransfereGov bate **100 %**
com o arquivo oficial de dados abertos nos 5 municípios amostrados (499 propostas, 181
instrumentos). A explicação "a coleta não roda" não se sustenta.

**Onde o sistema está falhando (de verdade):**

1. **Valores trocados no TransfereGov.** Em **1.905 das 3.199 propostas** da carteira (60 %, 36
   municípios) o campo "Valor de Repasse" mostra o valor da **contrapartida** e o "Valor Global"
   mostra o valor do **repasse** — porque o leitor de detalhe do portal pega o número errado. O
   arquivo oficial corrige tudo uma vez por dia (03:51), e o lote de 2 em 2 horas volta a
   estragar. Exemplo: a creche de Araújos tem repasse oficial de **R$ 3.819.853,65** e o
   sistema mostra **R$ 3.823,68**. Esse erro entra no Relatório de Monitoramento. *(H1 —
   defeito de coleta, crítico.)*
2. **A "chave" do gov.br fica vencida quase metade do tempo, em silêncio.** Nos últimos 30 dias
   a sessão gov.br esteve **morta 298 de 720 horas** (episódios de 93 h, 38 h, 95 h e o atual,
   desde 26/08 23:05 — 3 dias). Enquanto ela está morta, notas de empenho, projeto básico,
   licitações e cláusula suspensiva detalhada **param de atualizar sem nenhum aviso** (a tela
   mostra o valor antigo sem carimbo e a rodada é registrada como "sucesso"). A renovação
   exige alguém logar de novo pela extensão. *(H1 — a informação "às vezes não vem" tem aqui a
   causa mais forte.)*
3. **Metade da carteira não tem convênio estadual nenhum.** 20 dos 42 municípios ativos têm
   zero convênios SIGCON-MG: **17 sem credencial cadastrada** (nunca foi possível coletar) e **3
   com credencial recusada pelo portal** (Piracema desde 08/08, Papagaios e Santo Antônio do
   Monte desde 15/08). *(H5/uso para os 17; H1 para os 3 — precisam de reset de senha.)*
4. **O Relatório de Monitoramento omite itens em silêncio.** Convênio estadual "em cadastramento
   /análise/checklist" de ano anterior sem data de vigência não entra no RM completo — em
   Araújos ficaram de fora o "Moradas Gerais" (R$ 1.000.000, 2025) e um de 2020 (R$ 100.000).
   Seção vazia simplesmente desaparece do documento, sem "nenhum registro". *(H2.)*
5. **Rodadas morrem sem deixar rastro.** Em 30 dias o Coolify registrou 42 falhas do SIGCON, 32
   do lote TransfereGov e 28 do CAGEC — nenhuma delas deixa linha no `ingestion_log`. Duas são
   sistemáticas: a rodada do CAGEC das 01:50 BRT morre **todo dia** no `timeout` de 17 min, e o
   Coolify reinicia às 21:00 BRT (00:00 UTC) e mata a rodada do lote que começa nesse minuto (10
   dias em 30). O vigia não vê nada disso. *(H1 + observabilidade.)*

**Onde a reclamação é de uso, expectativa ou escopo:** a creche de Araújos **está** no RM desde
a correção #317 (10:49 de 29/08) — os PDFs que a Freitas baixou em 27/08 e 28/08 17:48 foram
gerados **antes** e por isso não a traziam; os estaduais **aparecem** nos RMs "Completo" de
Araújos (19 convênios + 21 emendas); e o cliente não tem, em tela nenhuma, um mapa "município ×
fonte × última coleta boa" — por isso cada reunião produz uma dúvida nova que só a equipe técnica
consegue responder. *(H4 + lacuna de produto.)*

**Hipóteses externas que caíram:** o "enrich por HTTP desligado" (`TG_HTTP_ENRICH=0`) é só o
*default* do código — na Freitas está **ligado** (`TG_HTTP_ENRICH=1`, `TG_NES=1`,
`TG_OPS_OBS=1`); e "municípios do fim do alfabeto sofrem mais" não se confirma hoje (correlação
posição × atraso = 0,15; o rodízio funciona).

## A.2 Triagem dos casos da Freitas

| # | Caso relatado | Veredito | Em linguagem simples | O que será feito |
|---|---|---|---|---|
| 1 | Araújos — "no RM não veio um dado da reforma de uma creche" | **H2 (corrigido em 29/08, #317) + resíduo H1** | A proposta 059522/2021 (FNDE, "Construir escola ou creche", R$ 3,82 mi) existe no portal e no banco, mas o RM a descartava por ser de 2021 "ainda em aprovação". Corrigido às 10:49 de 29/08; os PDFs baixados pela Freitas em 27/08 (17:18–17:20) e 28/08 (17:48) são anteriores. O que continua faltando nela — notas de empenho, projeto básico, andamento da obra — depende da sessão gov.br, morta desde 26/08; e o "Valor de Repasse" pode sair como R$ 3.823,68 (defeito 1). | Regerar o RM (Auto-popular); recapturar a sessão gov.br; corrigir o leitor de valores; passar a avisar no RM quando um campo não pôde ser coletado. |
| 2 | "Os estaduais não estão aparecendo no PDF de monitoramento" | **Misto: H5 (17 municípios), H1 (3), H2 (omissões por ano/vigência e detalhe não lido)** | Para 17 municípios não há credencial SIGCON — nunca houve o que mostrar; para 3 a senha está recusada pelo portal. Onde há credencial (ex.: Araújos), os estaduais aparecem, mas (a) 2 convênios reais ficam de fora pela regra de ano/vigência, (b) 24 dos 28 convênios de Araújos estavam sem os campos do detalhe (parlamentar, contrapartida, prestação de contas) — corrigido às 19:43 de 29/08 (#319), preenche ao longo das próximas rodadas — e (c) a variante "Resumido" nunca traz estaduais por construção (não foi o caso: as 88 exportações recentes foram "Completo"). | Pedir à Freitas as 17 credenciais faltantes e reset das 3; ajustar a regra de retenção; colocar "seção sem registros" e "não coletado" explícitos no RM; avisar no botão Resumido que ele é só Parte 1. |
| 3 | "Cada reunião tem um problema" (padrão recorrente) | **H4 + lacuna de produto** | O cliente não consegue ver o que está coberto e o que não está: não existe tela de cobertura município × fonte para não-admin; campos vencidos não têm carimbo; seções vazias somem. Toda dúvida vira suporte. | Tela/caixa "Cobertura desta emissão" (fontes coletadas, data, o que faltou e por quê) no RM e no dashboard. |

## A.3 Problemas confirmados — cards

**1. Valores trocados no TransfereGov** — *crítico, esforço P*
- **O problema:** "Valor de Repasse" = contrapartida e "Valor Global" = repasse em 60 % das propostas.
- **Por que acontece:** o leitor da página de detalhe procura "o próximo R$ depois do rótulo" e o
  portal exibe os três valores numa disposição em que o rótulo casa com o número vizinho. É como
  ler uma tabela pelo espelho. O arquivo oficial diário conserta; o lote de 2 em 2 h estraga de novo.
- **O que muda para quem usa:** valores errados nas telas do TransfereGov e no RM (e a soma "a
  desembolsar").
- **Depois do ajuste:** valores coerentes (global = repasse + contrapartida) em 100 % das linhas.
- **Esforço:** P (guarda de 6 linhas: se global ≠ repasse + contrapartida, descartar o trio e
  deixar o CSV mandar).

**2. Sessão gov.br morta sem aviso** — *crítico, esforço M*
- **O problema:** 41 % do tempo sem sessão válida; campos gated congelam com valor velho e sem carimbo.
- **Por que acontece:** o login gov.br tem reCAPTCHA (não automatizável); a renovação automática
  só re-deriva a sessão enquanto o SSO está vivo; expirou → precisa de captura humana. Nada grava
  "sessão morta" no banco; a rodada segue em modo visitante e é registrada como sucesso.
- **O que muda para quem usa:** notas de empenho, projeto básico, licitações e histórico param
  de atualizar e ninguém sabe desde quando.
- **Depois do ajuste:** rodada com sessão morta vira "parcial" com o motivo; tela e RM mostram
  "não atualizado desde dd/mm — sessão gov.br pendente"; alerta ao operador (já existe código de
  alerta, nunca chamado).
- **Esforço:** M.

**3. Metade da carteira sem SIGCON** — *alto, esforço P (comercial)*
- **O problema:** 17 municípios sem credencial, 3 com credencial recusada.
- **Por que acontece:** o SIGCON só mostra convênios do convenente logado; sem senha por
  município não há coleta. Nada no sistema diz isso ao cliente.
- **Depois do ajuste:** 42/42 com convênios estaduais; a tela avisa "sem credencial" em vez de vazio.
- **Esforço:** P (pedido ao cliente + cadastro no Cofre).

**4. RM descarta e esconde em silêncio** — *alto, esforço P/M*
- **O problema:** convênio estadual "em análise/checklist" de ano anterior sem vigência não
  entra; seção vazia some; a variante Resumido nunca traz estadual e o comentário do código
  afirma o contrário; o RM é um retrato congelado no momento da geração.
- **Depois do ajuste:** critério de retenção explícito, "nenhum registro" nas seções vazias,
  caixa de cobertura no cabeçalho, aviso no botão Resumido.
- **Esforço:** P (retenção/placeholder) + M (caixa de cobertura).

**5. Rodadas morrem sem rastro; vigia cego a queda de volume** — *alto, esforço M*
- **O problema:** 102 execuções falhas em 30 dias sem linha de log; CAGEC morre todo dia às
  01:50 BRT; Coolify reinicia às 21:00 BRT e mata o lote; SIMEC/PAR gravou "sucesso" com 0
  registros 3 vezes em 24/08 e ninguém viu.
- **Depois do ajuste:** linha de log no início da rodada (não só no fim), detecção de queda
  de volume no vigia, tarefa do CAGEC realinhada, horário do lote fora do minuto de reinício.
- **Esforço:** M.

**6. Instrumentação e higiene** — *médio, esforço P cada*
- 5 clientes HTTP sem `timeout`; 8 fontes que só sabem dizer "sucesso"; `transferegov_te` fora
  do catálogo de frescor; `transparencia_mg` sem tarefa e sem log; endpoint público
  `/api/status/ingestao` sem autenticação; `simec-termos` com `timeout` de tarefa (300 s) menor
  que o orçamento interno (1.500 s); `lxml` fora do `requirements.txt`; 24 dependências sem teto.

---

# PARTE B — TÉCNICA

## B.0 Método e fontes de evidência

| Fonte | Como | Onde estão as saídas |
|---|---|---|
| Código | HEAD `bead44a` (main), leitura direta + 16 agentes céticos independentes tentando refutar 100 afirmações (70 confirmadas, 30 parciais, 0 refutadas; correções incorporadas) | `docs/auditoria-coleta/verificacao_resumo.txt` |
| Banco Freitas | `ssh` → `docker exec tox59… psql` read-only; queries Q00–Q12, B1–B2 | `docs/auditoria-coleta/sql/*.sql`, `out/*.txt` |
| Coolify | `coolify-db` (`scheduled_tasks`, `scheduled_task_executions`, `application_deployment_queues`), `docker inspect` (envs por whitelist), `pip show` no container do worker | `out/c07_c10.txt` |
| Fonte oficial | CSVs de dados abertos do TransfereGov baixados em 30/08 01:29 UTC (`Last-Modified` 29/08 11:12 UTC); consulta pública do TransfereGov via Chrome | `out/reconciliacao.md` |
| Web (Bloco 3) | 7 pesquisadores + 7 céticos + crítico de completude, URLs acessadas em 29–30/08 | seção B.6 |

Carteira medida: **42 municípios ativos** (a documentação diz 44; Q01) e 18 inativos, todos MG.
Volumes: `transferegov_propostas` 3.199; `convenios_estadual` 2.406 (SIGCON-MG 798 em 22
municípios, FNS 1.608 em 42); `emendas_estaduais` 762; `cagec_situacao` 93; `cauc_situacao` 60;
`ingestion_log` 5.769 linhas; `rm_relatorios` 15.

## B.1 Bloco 1 — casos relatados

### Caso 1 — Araújos, "reforma de creche" ausente do RM

**Salto 1 (fonte → banco).** Consulta pública do TransfereGov (Acesso Livre,
`discricionarias.transferegov.sistema.gov.br/voluntarias/…`, 29/08 23:45 BRT): proposta
**059522/2021**, órgão 26298 FNDE, proponente MUNICIPIO DE ARAUJOS, situação "Proposta/Plano
de Trabalho Aprovados", possui parecer = Sim. CSV oficial `siconv_proposta.zip` (29/08):
`ID_PROPOSTA=1791663`, `VL_GLOBAL_PROP=3.823.677,33`, `VL_REPASSE_PROP=3.819.853,65`,
`VL_CONTRAPARTIDA_PROP=3.823,68`; `siconv_convenio.zip`: `NR_CONVENIO=932836`,
`DIA_FIM_VIGENC_CONV=16/12/2024`. Banco (`transferegov_propostas` id 18): presente, objeto
"019-Construir escola ou creche", `codigo_instrumento=932836`, programa "SIMEC/PAR4",
`dt_fim_vigencia=31/12/2026` (diverge do CSV — ver B.5), **`valor_global=3819853.65`,
`valor_repasse=3823.68`** (deslocados, achado B.3-1), `projeto_basico=NULL`,
`notas_empenho=NULL`, `obras=NULL`, `processo_execucao=NULL`, `ops_obs.valor_desembolsado=0`.
Também existe `simec_termos` id 6: processo 23400.002301/2021-01, "TC – Municípios – Com
cláusula suspensiva_Obra", R$ 3.157.096,83, vigência 30/12/2024. Nenhuma linha com "creche"
em `convenios_estadual`, `transferegov_pac` ou `sismob_obras` para Araújos (query B1b).
→ **O dado existe na fonte e no banco** (não é H3 nem H1 na base).

**Salto 2 (banco → RM).** `services/rm_builder.py:315-357` (`_fed_retem`): até o commit
`cbcd3ab` (#317, 29/08 10:49) uma proposta "ativa" de 2021 só entrava se `ano ≥ ano_ref` —
a própria mensagem do #317 cita a 932836 como exemplo do que "caía fora do relatório COMPLETO,
calada". Depois do #317 entra quando a vigência venceu (`_vigencia_vencida`, `:291-312`).
Conteúdo congelado: o PDF sai de `rm_relatorios.conteudo` (`routers/rm.py:845`). RM 51
(Araújos, todas as fontes) repopulado às 10:14/10:39/11:37/13:41 de 29/08 tem a proposta na
Parte 1 (`tem_creche=1`, query B1c); RMs 90/94/95 (27/08) não têm.

**Salto 3 (RM → PDF baixado).** `audit_log` (`action='export.rm'`): três usuários da Freitas
exportaram o RM de Araújos em 27/08 17:18–17:20 (RMs 51 e 90) e em 28/08 17:48 (RM 51) —
**todos antes do #317**; as exportações posteriores (29/08 10:14 em diante) foram da equipe
Alavank. Variante sempre "completo" (88 exportações "completo" × 3 "resumido" no histórico
inteiro; nenhuma "resumido" nos últimos 14 dias).

**Veredito: H2 — defeito de exibição (retenção por ano), corrigido em 29/08 10:49; o PDF que
a Freitas tinha em mãos era anterior.** Resíduo H1: os dados de execução da creche (NEs,
projeto básico, obra, licitações) estão vazios porque os SPs `execucao`/`prestacao` da sessão
gov.br estão frios desde 26/08 (B.4.4) e porque `situacao_contratacao` não casa com a regra de
cláusula (`:922`); e o valor de repasse exibido está deslocado (B.3-1). O TC do SIMEC aparece
na Parte 3 por vigência vencida (30/12/2024) — decisão de desenho (`:2103-2106`), não defeito.
**Resposta ao cliente:** "a creche está no RM gerado a partir de 29/08 10:49 — regere pelo
Auto-popular; notas de empenho e obra dependem da sessão gov.br, que precisa ser recapturada."

### Caso 2 — "os estaduais não aparecem no PDF"

**Salto 1.** SIGCON-MG só lista convênios do convenente logado (`ingestion/sigcon_scraper.py:9`);
credencial por município no Cofre. Medido (B2d/B2e): **17 municípios ativos sem credencial**
(Arcos, Camacho, Capela Nova, Caranaíba, Carmópolis de Minas, Casa Grande, Cláudio, Estrela do
Indaiá, Heliodora, Ibitiúra de Minas, Igarapé, Itaguara, Nova Lima, Passa Tempo, Senhora dos
Remédios, São Tiago, Tocos do Moji) e **3 com login recusado** (Piracema: 58 tentativas desde
08/08 15:04; Papagaios e Santo Antônio do Monte: 3 tentativas, última coleta boa 15/08 08:26;
`ultimo_erro` = "login SIGCON nao completou (form nao submeteu ou credencial invalida)"). Esses
20 têm `convenios_estadual` (SIGCON) = 0. Os outros 22 têm 22–60 convênios cada.
→ Para 17: **H5/uso** (nunca houve o que coletar; `CONTINUAR.md` §6.2 já pedia as credenciais).
Para 3: **H1** (credencial recusada; o watchdog trata como "nota", não alarme — regra do dono).

**Salto 2 (banco → RM).** Araújos: 28 convênios SIGCON no banco; RM 51 traz **19** + 21 emendas
estaduais (Parte 2 "INFORMAÇÕES DE REPASSE ESTADUAIS" e Parte 3 "Convênios Estaduais"). Os 9
ausentes: 4 "Cancelado" (`dead`, por desenho, `rm_builder.py:349-351`); 3 "Cadastramento"
sem objeto (2021, 2023 ×2 — um é "teste"); **2 omissões reais**: `005991/2025` "Preenchimento
Checklist", R$ 1.000.000, Programa Moradas Gerais, e `002842/2020` "Analise Celebracao",
R$ 100.000 — ambos sem `dt_vigencia_*`, logo `_vigencia_vencida(None)=False` e
`ano < 2026` → descartados sem aviso (`:353-357` + `:1508-1511`). → **H2.**
Campos do detalhe: `raw_data ? 'responsaveis'` em 4 de 28 convênios de Araújos (o "Detalhes
capturados: 4" do #319); na carteira, 22 municípios com 8–60 % dos convênios sem assinatura /
contrapartida (B2c). Corrigido por `bead44a` (#319, 19:43) — rodízio de página do detalhe;
preenche ao longo das rodadas (teto `SIGCON_DET_MAX_PAG=4`). → **H1 corrigido, efeito gradual.**

**Salto 3 (RM → PDF).** Variante "Resumido" recorta só a Parte 1 (`services/rm_export.py:286-292`)
e `_destino_completo` nunca manda estadual para a Parte 1 (`rm_builder.py:216-221`) → o
Resumido **nunca** contém estadual; o comentário `rm_export.py:210-211` afirma o contrário.
Não foi o caso destas reclamações (todas "completo"), mas é armadilha aberta na tela
(`dashboard/rm/page.tsx:699-714`, botões lado a lado).

**Veredito: misto** — H5 (17 municípios), H1 (3 credenciais + detalhe não lido, este corrigido
hoje), H2 (retenção por ano/vigência, seções vazias sem placeholder, Resumido).

### Caso 3 — padrão recorrente ("cada reunião um problema")

Não existe superfície para o cliente ver cobertura: `GET /api/control/cobertura`
(`routers/control.py:431-504`) exige `X-Control-Token`; `/dashboard/frescor` exige `role=admin`
(`routers/freshness.py:180-181`) e é por fonte, não por município; o BI (`routers/bi.py:247-327`)
cobre só sigcon/transferegov, 24 h, 5 piores. Campos gated não têm carimbo por campo (B.2-H);
seções vazias do RM somem (`rm_builder.py:2275-2294`); quatro limiares diferentes de "atrasado"
convivem (26 h nas telas, 2 d no monitor, 6–192 h no watchdog, 24 h no BI). → **H4 + lacuna de
produto**: a informação "o que não foi coletado e por quê" não chega ao cliente.

## B.2 Bloco 2 — hipóteses A–H

| Hip. | Veredito | Evidência | Impacto real |
|---|---|---|---|
| **A** `TG_HTTP_ENRICH` default "0" → enrich HTTP desligado | **REFUTADA em produção (Freitas); confirmada como default de código** | Default `"0"` em `ingestion/transferegov_voluntarias.py:727`. Env real do worker Freitas (`docker inspect`, 29/08): `TG_HTTP_ENRICH=1`, `TG_NES=1`, `TG_OPS_OBS=1`, `TG_SKIP_ENRICH=1` (o lote sobrescreve com `TG_SKIP_ENRICH=0 TG_HTTP_DETALHE=1 TG_BUDGET_S=1500 TG_LOTE_MUNICIPIOS=4`, task `transferegov-lote`, `0 0-22/2 * * *`). Banco: `projeto_basico` preenchido em 0–10 propostas/município e `notas_empenho` em 2–43 (Q11a) — só possível com `_hx`. Zero registro de decisão em docs/commits (`git log -S TG_HTTP_ENRICH` = 2 commits). | Nenhum na Freitas. Risco de desenho: `projeto_basico` (`:922`) e `notas_empenho` (`:947`, fallback browser `:966` dentro do gate) **não têm caminho sem `_hx`** — tenant sem a env nunca coleta. Estado dos outros 3 tenants: não verificado (limitação). |
| **B** `lxml` fora do requirements | **CONFIRMADA** | `transferegov_http.py:30-31`; `requirements.txt` sem `lxml`, **24** linhas todas `>=` sem teto; no worker: `lxml 6.1.2` via `python-docx 1.2.0`, `pip check` limpo; `Dockerfile.scraper:19` instala Chromium sem versão pinada. | Latente: remover/trocar `python-docx` (exportação DOCX) derruba o enrich HTTP e a guarda `_ops_obs_vazio` (`:1685-1690`, `except: pass`). |
| **C** série + alfabeto | **PARCIAL: série confirmada; starvation alfabética REFUTADA hoje** | Laços `:2326` (diário) e `:2504` (lote) com uma `page_guest`, zero `Semaphore` (vs `run_fns_local.py:375`, `sigcon_scraper.py:2029`, `sismob_obras.py:508`). Rodízio só por staleness (`:2411`), sem backoff — `INFRA.md:220-221` afirma backoff que só existe no SIGCON (`sigcon_scraper.py:1512-1513`). Medição Q08d/Q09c: correlação posição alfabética × dias sem coleta = **0,15** (transferegov), 0,25 (sigcon, puxada pelas 3 credenciais quebradas do terço final); terço 2 é o pior no TG; `detalhe_atualizado_em` < 7 d em 100 % das propostas (Q11b). O diário (`run()`, alfabético, sem deadline) dura 1.430–1.540 s para 42 municípios (Coolify c07c) porque roda com `TG_SKIP_ENRICH=1`. | O incidente de 23/07 (10 de 41 municípios) foi resolvido pelo rodízio + CSV. Hoje 22 municípios carregam "parcial: orçamento esgotado, N restantes" (Arcos 143, Nova Lima 82) — mas o detalhe é revisitado por idade (`TG_DETALHE_MAX_AGE_H=18`) e ninguém passa de 1,6 d. |
| **D** parsers silenciosos | **CONFIRMADA, alvo corrigido** | `ingestion/base.py` é **código morto** (zero imports). 28 parsers locais devolvem `None` mudo; só `transferegov_opendata._data:259-261` e `._modalidade:178-180` avisam. FNS converte ausente em **0** (`run_fns_local.py:199-201`). Mapa tela→campo→parser em B.3-9. | Campo que vira NULL/0 sem alerta em todas as telas; no CAUC um marcador diferente de "!" pintaria irregular como regular (`cauc_ingest.py:120`). |
| **E** sem detecção de queda de volume | **CONFIRMADA + medida** | Nenhuma query de `watchdog_coleta.py` lê `records_*`; única guarda é local ao SISMOB (`sismob_obras.py:594-607`). Q05: `simec_par` gravou **success com 0 registros** 3× em 24/08 (12:26, 14:26, 16:25; mediana anterior 311–338) — invisível. `ingestion_log` tem `records_processed/inserted/updated` (setup_db.py:226-236), suficiente para a detecção. | Queda de 100 % passa limpa. Semântica das contagens é inconsistente (SIGCON só `updated`; CAGEC conta municípios) — normalizar antes de alertar. |
| **F** zero HTTP condicional | **CONFIRMADA** | grep de ETag/If-Modified-Since/304 em 44 arquivos: 0; cache só por idade (`transferegov_opendata.py:287-291`, 20 h). | Limita cadência; dumps de 205 MB (`siconv_proposta.zip`) baixados 1×/dia mesmo sem mudança (`Last-Modified` diário às 11:12 UTC). |
| **G** vocabulário de status | **CONFIRMADA + agravada** | Na Freitas convivem `success/partial/error`, `ok/parcial/erro` (CAGEC), `success/parcial/erro` (sigcon, TG), `success/failed` (opendata/pac) (Q02). `STATUS_SUCESSO=("success","ok")` (`watchdog_coleta.py:158`). **8 fontes gravam `'success'` hardcoded** (acordofes, cauc, emendas_estaduais, siconv_convenio_backfill, siconv_emenda_backfill, siconv_federal, sigcon_ckan_backfill, simec_par) — 4 delas vigiadas pelo watchdog; em `siconv_emenda_backfill.py:215-224` a exceção vai para `logger.error` e o log recebe success com n=0. `transferegov_te` e `siconv_federal` fora do catálogo de frescor; `transparencia_mg.py` não grava log e **não tem task** no Coolify da Freitas. `POST /api/control/te/lote` aceita status arbitrário (`control.py:555`). | Fonte quebrada pode ficar verde para sempre; fonte sem log é invisível. |
| **H** cadeia de sessão gov.br | **CONFIRMADA + medida (causa forte)** | Detecção: `transferegov_http.py:164-200`, `transferegov_voluntarias.py:1197-1199`; retorno `None` → `COALESCE` preserva valor velho (`:2138-2146`), sem marcador; só `historico_atualizado_em` avança e só com sessão viva (`:1029-1035`); status do log ignora sessão (`:2364-2369`). Alerta de sessão morta (`govbr_keepalive.py:148-206`) **nunca é chamado**; o módulo não é executado por task nenhuma. Medição (c10a/b, task `govbr-renew`): **viva 210 h, morta 297,5 h**, indeterminado 212 h (antes de 08/08 as mensagens não tinham marcador); episódios mortos 12–15/08 (93 h), 16–18/08 (38 h), 21–24/08 (95 h), **26/08 23:05 → agora** ("SSO expirou … precisa RE-CAPTURA (login tem reCAPTCHA)"). `private-keepalive` (a cada 10 min): `/private/` vivo, **`execucao=CAIU, prestacao=CAIU`**; "SP `execucao` frio" 519× nos logs do lote. | Notas de empenho, projeto básico, licitações e cláusula detalhada congelados desde 26/08 sem sinal; histórico de comunicações com mediana de 18–27 dias de idade (Q11a). |

## B.3 Achados adicionais (severidade, evidência, causa, correção, risco)

### B.3-1 · CRÍTICO · Valores global/repasse/contrapartida deslocados (H1)
- **Evidência:** reconciliação CSV × banco (B.5): 246 propostas com `valor_global` e 247 com
  `valor_repasse` divergentes nos 5 municípios; padrão `valor_repasse == valor_contrapartida`
  em **1.905 de 3.199** propostas da carteira (36 municípios) — query "padrão na carteira". O
  `detalhe` jsonb guarda os rótulos originais já trocados: `Valor Global=R$ 1.000.000,00 ; Valor de
  Repasse=R$ 1.500,00 ; Valor de Contrapartida=R$ 1.500,00` para a 000002/2016 (CSV: global
  1.001.500 / repasse 1.000.000 / contrapartida 1.500). Linha do tempo: linhas com detalhe lido
  nas rodadas de 04:00 e 06:00 UTC estão corretas porque o CSV diário (06:51 UTC) as reescreveu
  depois; todas as rodadas seguintes (08:00 → 00:00 UTC) gravam 80–90 % deslocadas.
- **Causa-raiz (provada na fonte, 29/08 23:53 BRT, consulta pública da proposta 059522/2021):**
  na seção "Valores" do detalhe o portal imprime **o número antes do rótulo**, em árvore:
  `R$ 3.823.677,33 Valor Global → R$ 3.819.853,65 Valor de Repasse → R$ 3.823,68 Valor da
  Contrapartida → R$ 3.823,68 Valor Contrapartida Financeira → R$ 0,00 Bens e Serviços → R$ 0,00
  Rendimentos`. `grab_money` (`ingestion/transferegov_http.py:355-368`) e `grabMoney`
  (`transferegov_voluntarias.py:1953-1970`) procuram "o próximo `R$` até 40 caracteres **depois**
  do rótulo" — logo "Valor Global" recebe o repasse (linha seguinte), "Valor de Repasse" recebe a
  contrapartida e "Valor da Contrapartida" recebe a "Contrapartida Financeira" (igual, por
  coincidência). O resultado é gravado por cima do par rótulo|valor já lido das células
  (`set_kv`, `:330-341`), sem condição. `transferegov_opendata.py:524-533` documenta que "o
  scraper trocou global/repasse/contrapartida de lugar" e escolheu o CSV como autoritativo —
  mas o CSV roda 1×/dia (06:51 UTC) e o lote 12×/dia.
- **Correção proposta (ler o `R$` que precede o rótulo + guarda de consistência):**
```diff
--- a/backend/ingestion/transferegov_http.py
+++ b/backend/ingestion/transferegov_http.py
@@ def detalhe(self, id_proposta):
         def grab_money(label):
-            m = re.search(label + r"[\s\S]{0,40}?(R\$\s*[\d.]+,\d{2})", txt, re.I)
-            return m.group(1).strip() if m else None
+            # No bloco "Valores" o portal imprime o NUMERO ANTES do rotulo
+            # ("R$ 3.819.853,65 Valor de Repasse"). Medido na fonte em 29/08/2026:
+            # procurar o R$ DEPOIS do rotulo pegava o valor da linha seguinte
+            # (global<-repasse, repasse<-contrapartida) em 1.905/3.199 propostas.
+            m = re.search(r"(R\$\s*[\d.]+,\d{2})\s*" + label + r"(?![\w ])", txt, re.I)
+            if not m:   # layout antigo (rotulo: valor) continua aceito
+                m = re.search(label + r"\s*[:\n]\s*(R\$\s*[\d.]+,\d{2})", txt, re.I)
+            return m.group(1).strip() if m else None
@@
         for chave, variantes in (
             ("Valor Global", ("Valor Global do Instrumento", "Valor Global")),
             ("Valor de Repasse", ("Valor de Repasse da União", "Valor de Repasse", "Valor do Repasse")),
             ("Valor de Contrapartida", ("Valor da Contrapartida", "Valor de Contrapartida", "Valor Contrapartida")),
         ):
+            if out.get(chave):          # celula rotulo|valor ja leu — nao sobrescrever pelo regex
+                continue
             for lbl in variantes:
                 v = grab_money(lbl)
                 if v:
                     out[chave] = v
                     break
+        # GUARDA: global tem de ser repasse + contrapartida. Se nao fecha, o trio e lixo;
+        # descartar deixa o COALESCE do upsert preservar o valor do CSV de dados abertos.
+        _g, _r, _c = (_money_num(out.get(k)) for k in ("Valor Global", "Valor de Repasse", "Valor de Contrapartida"))
+        if None not in (_g, _r, _c) and abs(_g - (_r + _c)) > 0.05:
+            logger.warning(f"detalhe {id_proposta}: valores inconsistentes (G={_g} R={_r} C={_c}) — descartando o trio")
+            for k in ("Valor Global", "Valor de Repasse", "Valor de Contrapartida"):
+                out.pop(k, None)
```
  Mesma mudança no `grabMoney` JS (`transferegov_voluntarias.py:1956-1959`) e a guarda no
  `_upsert` (`:2065-2067`). Teste de regressão com o texto real da seção "Valores" (acima).
  Nota: a mesma consulta pública mostra `Data Término de Vigência Atual = 31/12/2026` — o banco
  está certo e `siconv_convenio.DIA_FIM_VIGENC_CONV` (16/12/2024) é a vigência original, não a
  atual: o CSV **não** deve sobrescrever `dt_fim_vigencia` quando o detalhe é mais novo
  (hoje sobrescreve: `_SOBRESCREVE` inclui `dt_fim_vigencia`, `transferegov_opendata.py:531`).
- **Risco (4 tenants):** baixo — só reduz o que o scraper grava; o CSV já é a fonte de verdade
  declarada. Verificar depois do deploy: `SELECT count(*) FROM transferegov_propostas WHERE
  abs(valor_repasse-valor_contrapartida)<0.05 AND valor_contrapartida>0` deve cair a ~0 em 24 h.

### B.3-2 · CRÍTICO · Sessão gov.br morta é invisível (H1/observabilidade)
- **Evidência:** B.2-H. Ainda: `renovar_sessao_govbr.py` (login programático) é script de
  bancada sem chamador; `routers/session_capture.py:236-245` dispara `transferegov_voluntarias.run()`
  no processo da **API**, cuja imagem não tem Chromium (`Dockerfile.api:1-2`) — a exceção é
  engolida (`:242-243`) e a resposta diz "scraper iniciado".
- **Correção proposta:**
```diff
--- a/backend/ingestion/transferegov_voluntarias.py
@@ (lote e diario, antes de gravar ingestion_log)
-        if _ok_diario == 0 and _falhas_diario: _st_d = "erro"
-        elif _falhas_diario or _subs_diario: _st_d = "parcial"
+        _sessao_morta = (page_auth is None) and _precisa_auth   # campos gated pedidos sem sessão
+        if _ok_diario == 0 and _falhas_diario: _st_d = "erro"
+        elif _falhas_diario or _subs_diario or _sessao_morta: _st_d = "parcial"
         else: _st_d = "success"
+        if _sessao_morta:
+            _partes_d.append("sessao gov.br ausente/expirada: campos gated (NEs, projeto basico, historico, clausula) nao atualizados")
```
  + carimbo por campo (`notas_empenho_atualizado_em`, `projeto_basico_atualizado_em` — migration
  idempotente `ADD COLUMN IF NOT EXISTS`) exibido na tela como "não atualizado desde dd/mm";
  + chamar o alerta já escrito (`govbr_keepalive._alert_session_dead`) a partir de
  `govbr_renew.renew()` quando cair em `needs_recapture`, gravando `watchdog_historico`;
  + em `session_capture.py`: enfileirar em `scraper_jobs` (tipo `transferegov`) em vez de
  `create_task` no processo da API.
- **Risco:** baixo/médio (status "parcial" novo aparece no monitor de frescor como degradado —
  é o objetivo).

### B.3-3 · ALTO · Rodadas mortas sem linha de log; CAGEC e lote sistematicamente mortos
- **Evidência (Coolify, 30 d):** `sigcon` 42 falhas (exit 124 ×5, 137/OOM ×4, `ScheduledTaskJob
  has timed out` 3.120 s ×4 em 25/08, "No such container" ×3 em 24–25/08 = deploy em voo,
  3.003 s ×8 em 05–08/08); `transferegov-lote` 32 (10× "Marked as failed during Coolify startup —
  job was interrupted" às 21:00 BRT = **00:00 UTC**, 12,13,15,16,17,18,22,25,27,28/08; 137 ×2;
  2 em 28–29/08 com 1.320/1.165 s); `cagec` 28 (**todo dia às 01:50 BRT** exit 124 aos 1.021 s —
  as outras 3 rodadas do dia passam). `ingestion_log` só recebe linha no fim (`started_at≈finished_at`
  em 100 % das linhas, Q02) → nenhuma dessas falhas aparece; o watchdog só reclama quando o
  último sucesso envelhece.
- **Causa:** (a) log escrito uma vez ao final; (b) algo reinicia o Coolify às 00:00 UTC (não
  identificado — fora do escopo read-only) e o lote começa exatamente às 00:00; (c) a rodada do
  CAGEC das 04:50 UTC excede os 1.020 s (11 municípios × 43–47 s ≈ 8–9 min + CRC; ver
  `cagec_scraper.py:371-382`) — as demais rodadas (10/16/22 UTC) cabem.
- **Correção:** INSERT `running` no início da rodada + UPDATE no fim (usa colunas que já
  existem); deslocar o lote para `5 0-22/2 * * *`; investigar o reinício 00:00 UTC (cron do
  host? `coolify` upgrade?); CAGEC: medir a rodada de 04:50 e ajustar `CAGEC_LOTE_MUNICIPIOS`
  ou o `timeout` (coluna ≥ N+120).
- **Risco:** baixo (schema idempotente; só muda horário).

### B.3-4 · ALTO · Watchdog cego a queda de volume + vocabulário/hardcoded (E/G)
- **Correção (detecção de queda, no watchdog, por fonte "comparável" — não rodízio):**
```sql
WITH r AS (SELECT source, id, COALESCE(records_inserted,0)+COALESCE(records_updated,0) n
           FROM ingestion_log WHERE status IN ('success','ok') AND finished_at > now()-interval '10 days'),
u AS (SELECT DISTINCT ON (source) source, n FROM r ORDER BY source, id DESC),
m AS (SELECT source, percentile_cont(0.5) WITHIN GROUP (ORDER BY n) med FROM r GROUP BY 1)
SELECT u.source, u.n, m.med FROM u JOIN m USING (source)
WHERE m.med > 20 AND u.n < 0.5*m.med AND u.source NOT IN ('sigcon_scraper','transferegov_lote','cagec');
```
  + normalizar os 8 escritores hardcoded (`try/except` → `'error'` com mensagem);
  + `FRESCOR_HORAS_NACIONAL`: `transferegov_te: 30`, `siconv_federal: 48`;
  + `transparencia_mg`: criar task (hoje inexistente) e gravar `ingestion_log`;
  + `control.py:555`: validar status ∈ {success,partial,error}.

### B.3-5 · ALTO · RM: retenção silenciosa e seções que somem (H2)
- `_fed_retem` (`rm_builder.py:353-357`): estadual "ativa" de ano anterior sem vigência sai
  (Araújos: R$ 1,1 mi em 2 convênios). `_fns_retem` (`:421-425`) não recebeu `dt_fim` (irmão
  do #317). Seções vazias somem (`:2275-2294`). Blocos TE/SIMEC-termos/PAC em `try/except`
  mudo (`:2008`, `:2136`, `:2222`). `"MS" in fonte_db` por substring (`:1359`). Resumido sem
  estadual (`rm_export.py:286-292`) com comentário errado (`:210-211`).
- **Correção:** em `_fed_retem`, para `esfera=="estadual"` e status `ativa`: reter quando
  `situacao` ∈ {Cadastramento, Análise Celebração, Preenchimento Checklist} **e** `ano ≥ ano_ref-2`
  (ou sempre, marcando "sem vigência"); `_fns_retem(dt_fim=…)`; placeholder "Nenhum registro
  nesta seção" + caixa "Cobertura desta emissão" (fontes, data da última coleta boa por fonte via
  `services/coleta.frescor_coleta`, sessão gov.br viva/morta, municípios sem credencial); no
  `try/except` dos blocos, anotar a fonte em `conteudo.meta.fontes_falhas` e imprimir.
- **Risco:** médio (muda o que entra no RM — validar com o dono contra o "padrão Freitas").

### B.3-6 · ALTO · 20/42 municípios sem SIGCON (H5/H1)
- 17 sem credencial (lista em B.1 caso 2) e 3 recusadas. Ação comercial + reset ("Esqueci
  minha senha", `CONTINUAR.md` §6.2). Tela de Convênios deveria dizer "sem credencial cadastrada
  para este município" em vez de lista vazia (hoje `coleta_falhas>0` só cobre falha).

### B.3-7 · MÉDIO · Timeouts, guardas e configuração
- 5 clientes httpx sem `timeout` (default 5 s): `che_rs.py:380`, `convenios_rs.py:370`,
  `gconv_es.py:324,360`, `run_fns_local.py:377` → `timeout=httpx.Timeout(60, connect=15)`.
- `run_fns_local.py:318/337`: `break` mudo em HTTP≠200/exceção grava success com anos faltando
  → contar em `falhas`.
- `transferegov_pac.py`: sem guarda de completude (copiar `TG_GUARD_MIN_RATIO` do opendata);
  `_registra_ingestao` em `logger.debug` quando falha (`:482-483`) → `warning`.
- `sigcon_scraper.py:185-187`: `return []` vira success → marcar `_marca_coleta(ok=False,
  erro="tabela nao carregou")` e contar em `falhas`.
- Task `simec-termos`: coluna `timeout=300` no Coolify vs `timeout -k 30 1700` no comando
  (regra de ouro: coluna ≥ N+120 = 1.820); hoje as rodadas duram ≤162 s, mas um portal lento
  mata sem log. `INFRA.md:314-315` confunde os dois números.
- `GET /api/status/ingestao` (`main.py:230-268`) público: contagens, últimas 25 linhas do log e
  `error` de jobs → exigir token ou remover.
- `requirements.txt`: 24 deps sem teto, sem lock; `lxml` explícito; Chromium não pinado →
  `pip freeze` em `requirements.lock` + `lxml>=5,<7`.

### B.3-8 · BAIXO · Higiene
- `ingestion/base.py` morto; `migrations/fix_municipio_acentos.sql:4` casa Araújos com o IBGE
  de Arinos (3104502; no-op onde está certo — na Freitas está 3103900); placeholders "Araújos"
  em 3 telas; `dashboard/fns/page.tsx:141` fallback "MG"; ramo `completo=False` do RM morto e
  quebrado (`UnboundLocalError`); `docs/CRON_SETUP.md` não lista watchdog, transferegov-lote,
  simec-termos, transferegov-te, private-keepalive, sismob; `INFRA.md:220-221` afirma backoff
  no rodízio do TG que não existe; `rm_export.py:210-211` comentário falso.

### B.3-9 · Mapa "campo exibido → parser silencioso" (hipótese D)
| Tela | Campo | Coluna | Parser | Coletor:linha |
|---|---|---|---|---|
| Convênios (SIGCON) | Assinatura / Fim da vigência / Contrapartida / valor do cartão | `dt_assinatura`, `dt_vigencia_final`, `valor_contrapartida`, `valor_concedente` | `_parse_date`, `_parse_vigencia_range`, `_parse_money` | `sigcon_scraper.py:94-124, :83-91, :1585-1589, :213` |
| TransfereGov (todas as abas) | Vigência, Data da proposta/assinatura, Valor global/repasse/contrapartida, cláusula (data) | idem | `_data` (avisa), `_money` (mudo), `_data_iso` (mudo) | `transferegov_opendata.py:410-457` |
| TE (Emenda Pix) | Custeio/Investimento, pagamentos, datas | `valor_*`, `pagamentos` | `_num`, `_dt_br` | `transferegov_te.py:332-345` |
| CAUC | Validade por exigência / Regular | `itens` (string crua), `pendencias` | nenhum; `v == "!"` | `cauc_ingest.py:117-130` |
| FNS | Valor da proposta / pago / a pagar | `valor_total`, `raw_data.vlPago` | `float(x or 0)` → **0** | `run_fns_local.py:199-201` |
| SIMEC | Data do pagamento, valor do termo, vigência | `dt_pgto`, `valor_termo`, `dt_vigencia` | `_parse_data`, `_valor`, `_data` | `simec_par.py:49-79`, `simec_termos.py:162-183` |
| SISMOB | Execução %, aprovado, repassado, últ. atividade | `vl_*`, `ultima_atividade_em` | `_dec`, `_num` (typo `vlPrimeraParcela`), `_ts` | `sismob_obras.py:126-175` |
| Emendas estaduais | Valor da emenda | `valor_indicacao` | `_parse_money(cells[9])` | `sigcon_scraper.py:1267` |

## B.4 Medições (tenant Freitas, 30 dias, 29/08 22:30 BRT)

### B.4.1 Frescor por fonte vs catálogo do watchdog (Q03)
| Fonte | Frescor esperado (h) | Último sucesso (BRT) | h desde | Atrasada? | 30 d: ok / parcial / erro |
|---|---|---|---|---|---|
| acordofes | 12 | 29/08 22:25 | 0,1 | não | 299 / 0 / 0 |
| cagec | 30 | 29/08 13:57 | 8,6 | não | 49 / 15 / 10 |
| cauc | 12 | 29/08 22:25 | 0,1 | não | 412 / 0 / 0 |
| fns | 30 | 29/08 02:33 | 20,0 | não | 31 / 0 / 0 |
| siconv_convenio_backfill | 30 | 29/08 03:51 | 18,7 | não | 39 / 0 / 0 |
| sigcon_scraper | 18 | 29/08 20:45 | 1,8 | não | 233 / 0 / 0 |
| simec_par | 12 | 29/08 22:25 | 0,1 | não | 287 / 0 / 0 |
| simec_termos | 30 | 29/08 03:12 | 19,3 | não | 12 / 0 / 0 |
| sismob | 30 | 29/08 11:00 | 11,5 | não | 30 / 0 / 0 |
| transferegov_lote | 6 | 29/08 21:23 | 1,1 | não | 256 / 5 / 0 |
| transferegov_opendata | 30 | 29/08 03:51 | 18,7 | não | 55 / 0 / 0 |
| transferegov_pac | 30 | 29/08 04:14 | 18,3 | não | 29 / 0 / 0 |
| transferegov_voluntarias | 30 | 29/08 04:13 | 18,3 | não | 29 / 0 / 0 |
| transferegov_te | **sem catálogo** | 29/08 00:40 | 21,9 | — | 17 / **25** / 0 |
| siconv_federal | sem catálogo | 29/08 10:03 | 12,5 | — | 25 / 0 / 0 |
| sigcon_ckan_backfill | sem catálogo | 29/08 22:25 | 0,1 | — | 257 / 0 / 0 |
| transparencia_mg | sem catálogo | **nunca** | — | — | 0 (sem task) |

`sigcon_scraper` nunca grava `erro` (0 em 30 d) apesar de 42 execuções falhas no Coolify —
as falhas matam o processo antes do INSERT.

### B.4.2 Série e quedas > 25 % (Q04/Q05)
- Quedas reais em regime comparável: **`simec_par` 24/08 12:26, 14:26, 16:25 → 0 registros
  (−100 %) com status `success`**; 24/08 10:28 → 49 (−86 %). Causa provável: portal SIMEC
  indisponível (mesmo dia em que o CAUC devolveu 503 e o SIGCON caiu por deploy em voo).
- `sigcon_ckan_backfill` 10/08: 695 → 416 (−40 %) — coincide com a desativação dos 18
  ex-clientes em 09/08 (legítimo).
- `cagec` 18/08: 4 rodadas `erro` (falha em massa registrada no backlog) — voltou em 19/08.
- Fontes com rodízio (`sigcon_scraper`, `transferegov_lote`, `cagec`) variam por desenho —
  medição por município abaixo.

### B.4.3 Duração real (Coolify, c07b/c07c)
| Task | Cron (UTC) | Sucessos | Falhas | Duração mediana / máx (s) | Teto da task (s) | Obs. |
|---|---|---|---|---|---|---|
| transferegov (diário, base) | 50 6 | 32 | 3 | 1.469 / 1.656 | 3.120 | `TG_SKIP_ENRICH=1`; 42 municípios |
| transferegov-lote | 0 0-22/2 | 331 | 32 | 175 / 1.519 (falhas até 3.603) | 2.820 | 2 no teto; 10 mortas no reinício 00:00 UTC |
| sigcon | 25 1-23/2 | 308 | 42 | 1.223 / 3.017 | 3.120 | 4 no teto (25/08) |
| cagec | 50 4,10,16,22 | 107 | 28 | 480 / 2.032 | 3.420 | rodada 04:50 morre em 1.021 s todo dia |
| govbr-renew | 5 * | 720 | 0 | 23 / 63 | 720 | — |
| private-keepalive | */10 | 3.948 | 4 | 15 / 101 | 420 | — |
| simec-termos | 10 6 | 12 | 0 | 114 / 162 | **300** | comando pede 1.700 |
| transferegov-te | 40 3 | 83 | 2 | 2 / 309 | 1.720 | quota 403 (25 parciais) |
| fns | 30 5 | 31 | 1 | 160 / 467 | 1.920 | — |
| watchdog | 7,37 * | 1.440 | 0 | 1 / 4 | 420 | existe (não está em docs) |

Teto de 3.600 s do `transferegov_voluntarias`: hoje não se aplica ao diário (≈24 min) nem ao lote
(orçamento 1.500 s + margem); as 2 execuções de 3.603 s foram em 08/08, antes do redesenho.

### B.4.4 Sessão gov.br (c10a/c10b/c10d)
| Estado (task `govbr-renew`, 30 d) | Horas |
|---|---|
| viva (RECONECTADO) | 210,0 |
| morta (SSO expirou — precisa RE-CAPTURA) | 297,5 |
| indeterminado (antes de 08/08, sem marcador) | 212,0 |

Episódios: viva 08/08 19:05 → 12/08 02:05; **morta 12/08 → 15/08 (93 h)**; viva 15/08 → 16/08;
**morta 16/08 → 18/08 (38 h)**; viva 18/08 → 21/08; **morta 21/08 → 24/08 (95 h)**; viva 24/08
23:05 → 26/08 23:05; **morta 26/08 23:05 → em curso (71,5 h no fechamento)**. Cofre: 1 sessão
real (id 16, município 1, `len=17.967`, capturada 25/08 01:36 UTC); as outras 14 linhas `govbr`
são senhas (`len` 51–62), não sessões. `private-keepalive`: `/private/` vivo, `execucao=CAIU`,
`prestacao=CAIU` nas execuções recentes; 1.684 de 3.948 execuções (43 %) marcadas
`private_dead`. Nos logs do lote: "SP `execucao` frio" 519×, "enrich via HTTP" 1.078×.

### B.4.5 Município × fonte (Q08/Q09)
| Fonte (`scraper_municipio_coleta`) | Teto | Ativos | Bons (`tentativas=0`) | Em erro | Nunca | Mediana h | Máx h |
|---|---|---|---|---|---|---|---|
| sigcon | 48 | 42 | 22 | 3 | **17** | 10,6 | 350 |
| sigcon_emendas | — | 42 | 22 | 0 | 20 | 9,9 | 16 |
| cagec | 48 | 42 | 40 | 2 (Arcos 6×, Nova Lima 5× — "nenhuma entidade encontrada", casamento por nome) | 0 | 8,7 | 140 |
| transferegov | 36 | 42 | 35 | 7 (orçamento esgotado, tentativas=1) | 0 | 11,4 | 25 |
| simec_termos | — | 42 | 42 | 0 | 0 | 19,4 | 19 |

Piores por carimbo de dados (Q09): Arcos e Nova Lima sem CAGEC e sem SIGCON; Piracema, Papagaios,
Santo Antônio do Monte com SIGCON parado (credencial). `detalhe_atualizado_em` do TransfereGov:
2.843 propostas < 1 d, 356 entre 1–7 d, **0** acima — o detalhe base está fresco em 100 %;
`historico_atualizado_em`: 2.554 entre 7–30 d (só as nunca lidas são revisitadas,
`TG_HISTORICO_MAX_AGE_DAYS=0`); `ops_obs`: 1.123 entre 7–30 d.

Teste da hipótese alfabética (Q08d/Q09c): terços 1/2/3 → média de dias sem carimbo no
transferegov 0,34 / 0,66 / 0,46; correlação posição × dias 0,15; no sigcon 0,36 / 0,36 / 3,61
(terço 3 = Papagaios, Piracema, Santo Antônio do Monte — credencial, não alfabeto).

## B.5 Reconciliação amostral CSV oficial × banco (5 municípios)

Arquivos: `siconv_proposta.zip` (205 MB, `Last-Modified` 29/08 11:12 UTC), `siconv_convenio.zip`,
`siconv_emenda.zip`; snapshot do banco = último `transferegov_opendata` success 29/08 06:51 UTC;
`TG_IGNORA_SITUACOES` default (3 situações de rascunho); chave `(IBGE, numero_proposta zfill(6))`.
Critério de escolha: rank de "pior" (Carandaí, Arcos), Araújos (caso 1), Toledo (fim do
alfabeto), Bom Despacho (pesado).

| Município | CSV | Banco | Ambos | Só CSV | Só banco | Ignoradas | Instr. CSV/banco | Σ global CSV | Σ global banco | Σ repasse CSV | Σ repasse banco | Diverg. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Araújos | 83 | 83 | 83 | 0 | 0 | 9 | 22/22 | 64.667.945 | 63.692.481 | 63.042.353 | **9.250.773** | 60 |
| Arcos | 147 | 147 | 147 | 0 | 0 | 14 | 57/57 | 86.351.810 | 86.211.910 | 83.352.582 | 80.682.482 | 4 |
| Bom Despacho | 144 | 145 | 144 | 0 | 1 | 11 | 62/63 | 98.224.109 | 93.527.657 | 93.222.357 | **10.119.305** | 131 |
| Carandaí | 78 | 78 | 78 | 0 | 0 | 4 | 25/25 | 55.340.387 | 54.686.968 | 53.721.933 | 39.506.682 | 14 |
| Toledo | 47 | 47 | 47 | 0 | 0 | 2 | 15/15 | 42.676.061 | 41.541.638 | 41.541.638 | **4.464.423** | 41 |

- **Cobertura: 100 %** — nenhuma proposta do CSV falta no banco; 1 "só banco" (Bom Despacho,
  `id_proposta_siconv` nulo, resíduo do scraper antigo por CNPJ — R12). Instrumentos batem.
- **Divergências: 246 `valor_global` + 247 `valor_repasse`** = achado B.3-1 (Arcos tem só 4
  porque foi visitado pelo lote às 19:25 UTC de um dia em que o CSV ainda o cobria — a
  proporção varia com a hora da última visita). 6 `situacao(ESTADO)`: 3 são oscilação diária
  legítima entre "complementado em Análise" (CSV) e "Aprovada e Plano … em Análise" (portal)
  — `status_changes` registra a mesma proposta indo e voltando às 06:51/06:52 todo dia
  (010532/2026): o portal e o CSV usam rótulos diferentes para o mesmo estado, e a trigger de
  mudança de status gera 2 eventos falsos por dia; 3 são "Instrumento Anulado" (CSV) vs
  rótulos antigos (banco) — o lote sobrescreve o CSV com o rótulo do portal.
- `dt_fim_vigencia` da 059522/2021: banco 31/12/2026 vs `siconv_convenio` 16/12/2024 — não
  comparado pelo script; provável prorrogação lida no detalhe e não refletida no dump (ou o
  inverso). **A verificar na fonte com sessão** (limitação).

## B.6 Bloco 3 — método por fonte

Pesquisa web feita em 29–30/08/2026 por 7 pesquisadores independentes (um por grupo de
fontes), cada um revisado por um cético que re-acessou as URLs e caçou exageros, mais um
crítico de completude; só entra aqui o que sobreviveu à revisão. Toda URL abaixo foi acessada
nessas datas com o status indicado. Digest completo em `docs/auditoria-coleta/out/bloco3_digest.txt`.

Hierarquia: **1** API/dado aberto oficial · **2** HTTP autenticado/sem browser · **3** Browser.

### B.6.1 Tabela fonte × método

| Fonte | Método atual | Nível | Alternativa oficial melhor? | Recomendação | Esforço |
|---|---|---|---|---|---|
| TransfereGov — base (propostas, convênios, emendas, programas) | 5 dumps CSV de `api-publica.transferegov.gestao.gov.br/downloads/dadosgov/` (`transferegov_opendata.py:97`) | 1 | **Já no ideal.** Host novo vivo (65 blobs, `Last-Modified` 29/08 11:12 UTC, carimbo `data_carga_siconv.zip` = 29/08 06:32 BRT); suporta **ETag/304 e Range/206** (testado). O repositório antigo está congelado desde 17/07 e desliga em 31/08 — o repo já usa o novo. **Não há API REST** para Discricionárias (entregas anunciadas: Atos Preparatórios até 10/2026, Instrumentos 11/2026–02/2027, Execução 03–06/2027, Obras 07–10/2027). | Manter; trocar cache por idade por `If-None-Match`; gravar `data_carga` no log; ler colunas já baixadas e ignoradas (`VL_EMPENHADO_CONV`, `VL_DESEMBOLSADO_CONV`, `QTD_TA`, `DIA_LIMITE_PREST_CONTAS`, `SUBSITUACAO_CONV`); **baixar hoje** `modelo_dados_siconv.zip` e `historico_de_versoes.pdf` (só existem no host antigo, 404 no novo) e versionar em `docs/`. | P |
| TransfereGov — listagem/detalhe guest (Playwright) | Chromium guest em `ConsultarProposta` | 3 | **Sim:** `siconv_proposta` + `siconv_convenio` + `siconv_proposta_cancelada.zip` cobrem tudo, exceto `possui_parecer` (que o frontend **não renderiza** — `TransfereGovPropostas.tsx:131` é só tipo). | Desligar a listagem/detalhe guest por browser como fonte primária (a listagem já é redundante com o CSV). Atenção do cético: hoje o GET guest sem sessão devolve o **muro SAML** — HTTP puro para o detalhe depende de cookies capturados. | P |
| TransfereGov — notas de empenho (sessão gov.br, SP `/prestacao/`) | HTTP autenticado / browser (`transferegov_http.notas_empenho`) | 2/3 | **Sim:** `siconv_empenho.zip` (23 MB; NR_CONVENIO, NR_EMPENHO, TIPO_NOTA, DATA_EMISSAO, DESC_SITUACAO_EMPENHO, VALOR_EMPENHO…) + `siconv_empenho_desembolso.zip`. Cético: 169 linhas com `VALOR_EMPENHO = 1` reais — **não** portar a regra "valor 1 = minuta". | Migrar para o dump (join por `codigo_instrumento`); manter HTTP só como conferência amostral. Elimina a dependência do SP `/prestacao/` (4 PRs de correção em 25/08). | P |
| TransfereGov — OPs/OBs e resumo de repasses (GERCOMP) | Browser/HTTP guest stateful | 2/3 | **Sim:** `siconv_desembolso.zip` (OB, data, valor, dias sem desembolso) + `siconv_convenio` (`VL_REPASSE_CONV`, `VL_DESEMBOLSADO_CONV`, `VL_SALDO_CONTA`); `siconv_pagamento.zip` (367 MB/dia) só se quiser favorecidos. | Substituir `ops_obs` pelo dump; desligar o clique GERCOMP. | P |
| TransfereGov — licitações/processo de execução | Browser/HTTP guest stateful | 2/3 | **Parcial:** `siconv_licitacao.zip` (+ `siconv_contrato`, `siconv_itens_licitacao` 230 MB) cobre contagem/lista/datas/valor; cético: `STATUS_LICITACAO` tem só 3 valores e `SITUACAO_ACEITE` está vazia em 82 % — validar amostralmente contra a tela. | Migrar contagem/lista; manter a tela só para o campo "Situação" se a validação mostrar perda. | P/M |
| TransfereGov — projeto básico / TR | HTTP autenticado (SP `execucao`) | 2 | **Parcial:** situação e histórico em `siconv_proposta.SITUACAO_PROJETO_BASICO` + `siconv_historico_projeto_basico.zip` (+ `*_modulo_empresas` para obras via mandatária); **anexos** só na tela. | Situação/histórico → dumps; anexos → manter HTTP autenticado só quando o painel usar a lista. | P |
| TransfereGov — cláusula suspensiva detalhada | Browser Struts autenticado | 3 | **Sim:** `siconv_convenio` já traz `DATA_SUSPENSIVA`, `DATA_RETIRADA_SUSPENSIVA`, `DIAS_CLAUSULA_SUSPENSIVA`, `MOTIVO_SUSPENSAO`, `SITUACAO_CONTRATACAO`, `SUBSITUACAO_CONV` (o opendata já grava 3 deles). | Desligar a navegação Struts; derivar `situacao_contratacao_detalhe` do dump. | P |
| TransfereGov — histórico de comunicações / quadro-resumo (`/private/`) | Browser/HTTP autenticado (mandatárias) | 2/3 | **Parcial:** `siconv_historico_situacao.zip` (103 MB zip / 583 MB CSV — linha do tempo oficial com hora), `siconv_historico_projeto_basico`, AIO, VRPL. Texto de pareceres e anexos **só com sessão**. | Histórico-base pelo dump (100 % das propostas, sem sessão); `/private/` como enriquecimento opcional com carimbo visível. Custo de CSV grande no host de 0,6 vCPU: usar Range/ETag e streaming. | M |
| TransfereGov — obras (medicao SPA) | Browser guest com listener + HTTP | 2/3 | **Parcial:** dumps do Módulo Empresas (medições, CTEF/empresa, submetas, `siconv_resumo_fisico_financeiro`, coordenadas). Paralisação/ART/responsável técnico só na SPA. | Base em dumps; `transferegov_http.obras` (JWT do idp) só para a fatia residual. Nunca mais listener de SPA. | M |
| TransfereGov — vigência/aditivos/prorrogações/alterações | **Não coletado** | — | **Sim (escopo novo H5):** `siconv_termo_aditivo` (186 MB CSV), `siconv_prorroga_oficio`, `siconv_solicitacao_alteracao`, `siconv_ingresso_contrapartida`, `siconv_solicitacao_ajuste_pt`. É exatamente o "prazo/prorrogação/aditivo" que o cliente cobra. | Incluir como escopo novo. Atenção: formatos de data ISO nesses dumps vs dd/mm/aaaa nos demais. | M |
| TransfereGov — Transferências Especiais (Emenda Pix) | API interna da SPA `especiais.…/api/public` com quota por IP (`transferegov_te.py`; 25 de 42 rodadas **parciais** em 30 d) | 2 | **Sim:** API oficial nova `api-publica.transferegov.gestao.gov.br/especiais` (Swagger em `/especiais/docs`, 21 endpoints, paginação 200, chave por CNPJ → `id_beneficiario` → planos → empenhos → DHs → OP/OB; ids idênticos aos da SPA; 20 páginas em 10 s sem 403 **de IP residencial**). Não expõe CPF do ordenador nem histórico de eventos da OP; `situacao_trabalho` vem com vocabulário diferente (rótulo vs enum). | Migrar listagem e pagamentos (3 requisições por plano da carteira, **não** carga total). Pré-requisito: `municipios.cnpj` preenchido nos 4 tenants. **Testar do IP da VPS antes** (a API nova está atrás do Cloudflare). O `POST /api/control/te/lote` que compartilha `plano_para_linha` precisa acompanhar. | M/G |
| TransfereGov — Novo PAC | Dumps CSV (`transferegov_pac.py`) | 1 | **Já no ideal.** Dump de hoje: 90.731 propostas, 11 situações; o coletor mapeia 6 — `SELECIONADA_PARLAMENTAR` (49) e `HABILITADA_PARLAMENTAR` viram "outra" e o RM (`rm_builder.py:2166-2170`) as exclui. | Adicionar as 5 situações a `_SITUACAO` (`transferegov_pac.py:99-106`) e decidir a regra do RM; expor o funil (cadastrada/enviada/habilitada) na tela. | P |
| SICONV federal (`siconv_federal_ingest.py`) | Dump nacional 205 MB 1×/dia | 1 | Já no ideal, mas **fora do catálogo de frescor** e com custo diário de 200 MB num host de 0,6 vCPU (a doc pede mensal; a task da Freitas é `0 13 * * *`, diária). | Incluir no catálogo; mensal + `If-None-Match`. | P |
| SIGCON-MG — convênios (detalhe logado) | Playwright com login por município (JSF) | 3 | **Parcial:** CKAN `dados.mg.gov.br` CGE "convenios-saida" (diário; `dm_convenio` 90.254 linhas com vigência atual, `ft_convenio` com contrapartida/repassado, `fl_convenio_alteracao`, `dm_convenente` com CNPJ) + SEGOV "portal_convenios_saida" (semanal, criado 09/07/2026; `convenios_saida.csv` com status, `pagamento{ano}.csv` chaveado por SIAFI, junção 100 % provada) — inclusive **2.922 instrumentos de TE-MG**. Cético: o CKAN cobre só **instrumentos celebrados** (26.853 de 26.854 linhas); propostas em cadastramento, assinatura, responsáveis e prestação de contas **seguem só logados**; WAF do dados.mg.gov.br exige UA de navegador. | Ampliar o backfill (`fl_convenio_alteracao`, `convenios_saida.csv`, `dm_convenente`) para todos os municípios — inclusive os 17 sem credencial (P); o Playwright logado vira enriquecimento estreito (assinatura, responsáveis, prestação de contas) (G para reescrever). | P + G |
| Emendas estaduais MG (indicação, deputado, TE-MG) | Regex sobre objeto + página logada | 3 | **Sim:** planilhas oficiais `emendas.mg.gov.br/transparencia` (XLSX 2023-26: 36.876 × 49 colunas; 2019-22: 30.429 × 26 — dois layouts) com nº da indicação, autor, IBGE, CNPJ, valores, SIAFI do instrumento, status. Cadência esporádica (12/05/2026); consulta pública `sigconv2/public/…/emendas.jsf` diária. | Coletor `emendas_mg` (item 3 do backlog): link descoberto por scraping, dois parsers, chave (ano, nº), join por SIAFI. Regex só como fallback. | M |
| Transparência MG (empenho/OB por credor) | HTTP stateful Joomla (`transparencia_mg.py`; **sem task e sem log** hoje) | 2 | **Parcial:** `pagamento{ano}.csv`/`pagamentorp{ano}.csv` SEGOV (semanal, chave SIAFI, 100 % de junção) — mas **sem data/nº de OB/situação da OP**, que é o que o coletor grava. | Complementar (não substituir): carga do CSV para o grosso + Joomla sob demanda para OB específica. Criar a task e o log antes de tudo. | M |
| CAGEC-MG | Playwright ZK + PDF do CRC | 3 | **Não há.** Sem API, sem CKAN (0 resultados), CADIN-MG com captcha, TCE-MG SPA. O flag `situacao_cagec` do CSV SEGOV é retrato por instrumento (320 CNPJs com Regular **e** Irregular no mesmo arquivo) — **não** serve de sentinela. | Manter ZK+PDF (**comprovadamente inevitável**). Não investir em CADIN-MG/TCE-MG. | n/a |
| Acordo FES (SES-MG) | XLSX espelho do Power BI | 1 | Já no ideal (planilha de 12/05/2026, 9,2 MB). Hoje é baixada **10–14×/dia** (pendurada no cron do sigcon 12×/dia + cauc-manha). | Auto-limitar a 1×/dia; validar cabeçalho antes de ler por índice; persistir `Last-Modified` e mostrar "dados de 12/05/2026"; remover `verify=False`. | P |
| SES-MG "Pagamento de Resoluções" (fundo a fundo estadual) | **Não coletado** | — | **Sim:** painel Laravel `pagamentoderesolucoes.saude.mg.gov.br` — GET (token CSRF) + POST por município/ano devolve a tabela completa (nº resolução, empenho, documento, data, valor, situação da OP, conta, CNPJ). | Coletor `ses_resolucoes_mg` (httpx stateful, 1 req/s). Reconciliar com o `fns_repasses` abaixo (mesma tela InvestSUS). | M |
| CHE-RS | API JSON pública | 1 | Nenhuma melhor. | Manter. | n/a |
| CAGE-RS convênios | CKAN `dados.rs.gov.br` (ZIP/CSV mensal, "atualizado até junho/2026") | 1 | Já no ideal; recursos irmãos não lidos (`Parcerias-RS.csv`, `Convênios de Receita`). Cético: TLS do `dados.rs.gov.br` falhou em 3 de 7 requisições — o retry é condição de funcionamento. | Manter; frescor esperado ~60 dias no watchdog (hoje 30 h); opcional Parcerias. | P |
| Consulta Popular RS | XLSX oficial | 1 | Nenhuma melhor (Power BI sem CSV). | Manter. | n/a |
| FPE-RS | Inerte (decisão: só fontes públicas) | — | **Não há porta pública** (gov.br + perfil PCPRS; WebForms). | Manter inerte. | G |
| TCE-RS / FUNRIGS | Conteúdo curado | — | **Não:** CKAN do TCE-RS não tem dataset de convênio/emenda/FUNRIGS (count 0); painéis são Qlik Sense atrás de **challenge Cloudflare para qualquer IP** (não só datacenter). | Fechar o item "pedir liberação de IP ao TCE-RS". | n/a |
| GConv-ES | CKAN `dados.es.gov.br` (55 recursos) | 1 | Já no ideal; `AditivosConvenios-AAAA.csv` não lido. | Manter; opcional aditivos. | P |
| **Emendas estaduais ES** | **Não coletado** | — | **Sim — melhor entrada nova do bloco:** dataset `portal-da-transparencia-emendas-parlamentares-do-estado` (15 CSVs, `metadata_modified` 29/08 08:08, 37 colunas, `CodigoConvenio` = `cod` do CSV que o `gconv_es` já lê — verificado em 3 amostras; `CodigoMunicipio` = IBGE 6 dígitos; S3 pré-assinado). | Coletor `emendas_es.py` no molde do `gconv_es`. | P/M |
| CRCC-ES | Não coletado | — | **Não localizado:** a área pública do GConv-web não tem consulta de CRCC por CNPJ; a premissa do backlog não se confirma. | Rebaixar para conteúdo curado até haver consulta pública ou credencial. | n/a |
| TRANSFVOL-GO | CKAN CGE-GO (mensal, 2–3 meses de defasagem) | 1 | Já no ideal; `datastore_search_sql` **funciona** (o backlog dizia bloqueado). | Manter; frescor esperado ~90 dias; medir frescor por SQL. | P |
| Emendas SERINT-GO | Não coletado (regex no `transfvol_go`) | — | **Sim, como memória:** CSV 2019–jul/2025 (TAB, 25 colunas, deputado/município/CNPJ/empenho), parado há 13 meses; notação científica nos números longos. | Coletor histórico `emendas_go.py`; regex continua para o corrente. | M |
| SES-GO cofinanciamento | CKAN datastore | 1 | Já no ideal; 2–4 recursos irmãos com o mesmo parser (Qualifica APS pactuado × pago; SEDS). Cético: a Vigilância tem conteúdo até 04/2025 apesar de `last_modified` 24/08 — o watchdog deve olhar `max(data_fechamento)`, não `last_modified`. | Adicionar irmãos (P cada). | P |
| TCM-GO | REST CSV único | 1 | Nenhum outro endpoint existe. | Manter. | n/a |
| CGE-TO certidão | Não coletado | — | **Sim:** formulário ScriptCase em `gestao.cge.to.gov.br` (sem `www`), POST sem captcha. | Coletor httpx reproduzindo os POSTs (medir sequência uma vez). | M |
| FES-TO fundo a fundo | Não coletado | — | **Não verificado:** `sistemas.saude.to.gov.br/repasse_fundoafundo/` em timeout em todas as tentativas (29–30/08). | Reverificar antes de decidir. | M |
| TCE-TO API | Não coletado | — | **Não utilizável:** respostas em `print_r` PHP (text/html), `/pessoas` e `/decisoes` 501; escopo é processos, não convênios. | Baixa prioridade. | G |
| Transfere.TO / Transparência TO | Não coletado | — | **Não há:** `dados.to.gov.br` não resolve; portal é Vaadin 8 (browser-only); Transfere.TO logado. | Conteúdo curado. | G |
| FNS propostas | API JSON pública `consultafns` | 1 | Já no ideal; sem OpenAPI (contrato = bundle 1.50.8). | Manter; tratar "resultado vazio"/500 como estados; registrar versão do portal. | P |
| **FNS repasses fundo a fundo / InvestSUS** | InvestSUS: nada (MFA); repasses: não coletados | — | **Sim, parcial:** endpoints públicos do `consultafns` não usados pelo repo — `/recursos/consulta-consolidada/repasse-bloco` (por bloco/componente, **anual** — o parâmetro `mes` é ignorado), `/consulta-consolidada/entidades`, `/recursos/contas-bancarias` (saldos, ~2 meses de atraso). Competência **mensal** só no CSV do Portal da Transparência (3 MB/mês, chave SIAFI). | Coletor `fns_repasses` (httpx) alimentando a tela InvestSUS; não perseguir o MFA do SCPA. | M |
| SISMOB | API JSON pública | 1 | Já no ideal; sem OpenAPI (403). `/endereco/municipios` ignora `uf` (lista nacional 546 KB) — baixar 1× por rodada para validar IBGE. | Manter. | P |
| CAUC | CSV CKAN do Tesouro | 1 | Já no ideal: STN não tem CAUC na `apidatalake`; o CAUC novo (23/03/2026) é hCaptcha. Recurso muda em **dias úteis** (`package_activity_list`). Hoje é baixado 10–14×/dia. | Auto-limite 1×/dia útil; "stale" se `Data da Pesquisa` < D-4; remover `verify=False`. | P |
| SIMEC/PAR liberações | `curl_cffi` (Cloudflare) | 2 | **Sim:** consulta pública PL/SQL do FNDE `internet_fnde.LIBERACOES_RESULT_PC` (POST por CNPJ; httpx puro, sem Cloudflare/captcha; fechamento D-1; mesmas 8 colunas). Pré-requisito: `municipios.cnpj` (ou de-para código FNDE). `impressao.php` continua só para a "Síntese por Dimensão". | Migrar liberações; SIMEC 1×/dia para dimensões. | M |
| SIMEC/PAR termos | httpx puro | 2 | **Não há dado aberto** (PDA-FNDE 2026-28 promete anual). Cético: o Cloudflare desafia httpx puro **do IP residencial**; da Lightsail as 12 rodadas de 30 d passaram (`simec_termos` 12 ok) — endurecimento preventivo, não incidente. | Trocar para `curl_cffi` como no `simec_par.py:165`. | P |
| **Obras escolares FNDE/SIMEC (creches, quadras)** | **Não coletado** | — | **Sim:** (1) API da Plataforma Antonieta de Barros — `constructions/tce/export` (XLSX nacional 10,9 MB, 13 abas, 3.911 obras do Pacto de Retomada, dado mais novo 09/07/2026; gerado on-the-fly, 70 s) e `constructions/tce/{obrid}` JSON; (2) Painel de Obras SIMEC `painelObras/lista.php?estuf=UF&muncod=IBGE` + `print.php?obra=ID` (Cloudflare → `curl_cffi`), todas as obras FNDE do município com situação/tipo/% execução. | Coletor `obras_fnde`: camada 1 semanal (XLSX filtrado por IBGE) — é a fonte certa para "creche paralisada/em retomada"; camada 2 (painel) como pacote maior. | M (+G) |
| FNDE PNAE/PNATE/PDDE | Indireto (liberações) | — | Sim: mesma consulta PL/SQL (por CNPJ, inclusive caixas escolares — 2 passos) + artefatos `.gz` da Antonieta (anuais). | Fonte primária = PL/SQL; Antonieta como enriquecimento anual. | M |
| dados.gov.br / Portal da Transparência (CGU) | Não usados | — | dados.gov.br: catálogo SPA, API CKAN exige token (401) — não é fonte. Portal CGU: derivado do SICONV com menos colunas; API exige chave gov.br prata/ouro (vinculada a pessoa física — passivo para 4 tenants). | Ignorar como fonte; no máximo reconciliação amostral. | n/a |

### B.6.2 Sessão gov.br — existe caminho oficial?

**Não.** Login Único é OIDC restrito a órgãos/empresas públicas (elegibilidade em
`gov.br/governodigital/…/servico-de-integracao`), autentica o cidadão *no sistema integrado* e
não dá sessão de terceiro no TransfereGov; o IdP do TransfereGov usa `client_id` próprio com
PKCE (`sso.acesso.gov.br/.well-known/openid-configuration`; POST em `idp.transferegov…/idp/`
→ 401 com página de login). A "API de integração" pública é a de **sistemas de compras**
(enviar licitações; token por ofício de órgão público) — escopo errado e viola "só fontes
públicas até aprovação". **Conclusão: manter extensão + Cofre e reduzir a dependência** —
(a) migrar campos gated para dados abertos (tabela acima); (b) *spike* de esforço P para
re-derivar a sessão SAML por HTTP em vez de Chromium (`govbr_renew.py:198-201`: o salto
SP→IdP é HTTP-POST Binding em HTML puro com `<NOSCRIPT>`, parseável) — hipótese com evidência
anterior contra (`govbr_renew.py:7-8`) e **não testada** por falta de sessão viva; (c)
reavaliar em 11/2026 e 03/2027 as entregas da API de Discricionárias.

### B.6.3 Ferramentas externas — vale trocar de framework?

**Não vale, e o assunto está encerrado.** Scrapling (0.4.15), ScrapeGraphAI (2.2.2, LLM
obrigatório), crawl4ai (0.9.2), Botasaurus (4.0.97, driver próprio), nodriver (AGPL) /
undetected-chromedriver (sem release desde 02/2024) e Camoufox (Firefox beta, `playwright<1.61`
conflitante): nenhum resolve SAML gov.br sem login humano, ZK Framework (CAGEC) ou JSF com
login por município (SIGCON) — todos são Chromium/CDP com outro nome, e a migração exigiria
reescrever coletores que deployam em 4 tenants sem CI. O único ingrediente com valor é o
**Patchright** (drop-in do Playwright, Apache-2.0, 1.62.2): plano B de esforço P **se** o
`ingestion_log` mostrar página de desafio — hoje não há incidente registrado. Ação imediata e
independente: **teto de versão** (`playwright<1.63`, `curl_cffi<0.17`, `httpx<0.29`) e lock.

### B.6.4 O que o crítico de completude apontou (e fica registrado)

- **`municipios.cnpj` é dependência transversal** de 4 recomendações (TE por CNPJ, CSV SEGOV,
  CGE-TO, FNDE PL/SQL) — na Freitas os 42 ativos têm CNPJ (Q01); nos outros 3 tenants não
  foi medido.
- Contradição resolvida: as APIs `/especiais/docs`, `/parcerias/docs` e `/fundoafundo/docs`
  do host novo **existem** (o grupo 1 errou ao dizer 404).
- `govbr-renew` roda **de hora em hora** e `private-keepalive` a cada 10 min (Coolify, c07a) —
  não "a cada 15 min" como diz `docker-compose.yml:88`.
- SIMEC "quebrado por Cloudflare" **não se confirma na Lightsail** (0 erros em 30 d); vale
  como endurecimento.
- CAUC/Acordo FES/SIMEC-PAR rodam 10–14×/dia (pendurados no cron do sigcon 12×/dia +
  `cauc-manha`), 3× mais do que o grupo 5 estimou — a recomendação de auto-limite fica mais forte.
- `transferegov_te` está **majoritariamente parcial** (25/42) — a migração para a API nova
  vale mais do que o cético do grupo 2 supôs, desde que testada do IP da VPS.
- Sem veredito por falta de acesso: FES-TO (timeout), TCE-MG dados abertos (SPA), API Obrasgov
  no host novo (docs 404), Portal da Transparência com chave, texto oficial do Comunicado
  23/2026 (só reprodução de terceiro), emendas federais por autor fora do SICONV (SIOP).

## B.7 Auto-confronto

**Objeção 1 — "O deslocamento de valores é semântica (valor do instrumento ≠ da proposta),
não defeito."** Resposta: o `detalhe` jsonb guarda os rótulos do próprio portal já trocados
("Valor de Repasse = R$ 1.500,00" para uma proposta cujo repasse oficial é R$ 1.000.000) e o
comentário de `transferegov_opendata.py:524-533` reconhece a troca desde a comparação de
produção que motivou o CSV autoritativo. Global = repasse + contrapartida é identidade do
TransfereGov; 1.905 linhas a violam. **Sobrevive.** Evidência contrária procurada: rows de
"Termo de Compromisso" (que poderiam ter regra própria) — 69 deslocadas vs 192 consistentes,
mesmo padrão.

**Objeção 2 — "A sessão morta não importa: o CSV e o modo visitante cobrem o que o cliente
usa."** Resposta: o que depende de sessão é exatamente o que a Freitas cobra no RM (notas de
empenho, projeto básico, obra, cláusula) — os PRs #285–#296 desta semana existem por isso. E
o histórico de comunicações tem mediana de 18–27 dias. **Sobrevive**, com a ressalva de que a
solução definitiva pode ser dado aberto (B.6) e não sessão.

**Objeção 3 — "A Freitas reclama porque o sistema está errado, não por uso."** Resposta: dos
dois casos concretos, um era defeito de exibição já corrigido antes da reunião (mas depois do
PDF que eles tinham) e o outro é majoritariamente ausência de credencial. A parte "uso" é real:
o cliente não tem como saber o que está coberto. **Muda o enquadramento**: o problema-raiz do
caso 3 não é coleta nem uso — é a ausência de uma superfície de cobertura, que transforma
qualquer lacuna (legítima ou não) em "o sistema falhou".

**Que evidência me faria concluir o contrário, e eu procurei?** (a) Propostas do CSV ausentes
do banco → 0 em 499 (procurei). (b) Fonte vigiada atrasada → nenhuma (Q03). (c) Starvation
alfabética → correlação 0,15 (procurei). (d) `TG_HTTP_ENRICH` desligado em produção →
ligado (li a env real). (e) Exportação "Resumido" pela Freitas → nenhuma em 14 dias (li a
auditoria). (f) Que o deslocamento fosse regressão de hoje → não: nenhum commit tocou o parser
desde 26/08 e a linha do tempo mostra o CSV corrigindo diariamente; é estado permanente.

## B.8 Backlog ordenado por retorno/esforço

| # | Item | Retorno | Esforço | Depende de |
|---|---|---|---|---|
| 1 | Guarda de consistência de valores (B.3-1) + teste com HTML real | valores certos em 60 % das propostas e no RM | P | — |
| 2 | Recapturar sessão gov.br (operacional, hoje) | destrava NEs/PB/obra | P | extensão + login humano |
| 3 | Pedir 17 credenciais SIGCON + reset de 3 | +20 municípios com estaduais | P (comercial) | Freitas |
| 4 | RM: retenção de "ativa" estadual sem vigência; `_fns_retem(dt_fim)`; placeholder de seção vazia | fecha omissões silenciosas | P | decisão do dono sobre o critério |
| 5 | `ingestion_log`: status `parcial` + nota quando sessão morta; alerta de sessão morta ligado | fim do "sucesso" falso | M | — |
| 6 | Caixa "Cobertura desta emissão" no RM + tela de cobertura município×fonte para o cliente | mata o caso 3 | M | 5 |
| 7 | Linha `running` no início da rodada; detecção de queda de volume; catálogo (TE, siconv_federal); 8 escritores com erro real | vigia enxerga rodadas mortas e zeros | M | — |
| 8 | Lote fora do minuto 00:00 UTC; rodada CAGEC 04:50 investigada; `simec-termos` timeout 1.820 | menos rodadas mortas | P | acesso Coolify |
| 9 | 5 timeouts httpx; FNS `break` mudo; PAC com guarda; SIGCON `return []` → falha | robustez | P | — |
| 10 | `transparencia_mg`: task + log | fonte visível | P | — |
| 11 | Carimbo por campo gated (migration) + "não atualizado desde" na tela | transparência | M | 5 |
| 12 | Endpoint `/api/status/ingestao` com token; `control.py:555` validado; `session_capture` via fila | segurança/coerência | P | — |
| 13 | `requirements.lock`, `lxml` explícito, Chromium pinado | builds reprodutíveis | P | — |
| 14 | Notas de empenho, OPs/OBs, licitações e cláusula suspensiva pelos dumps `siconv_*` (B.6.1) | 4 campos gated deixam de depender da sessão gov.br | P cada | dicionário salvo antes de 31/08 |
| 15 | Baixar e versionar `modelo_dados_siconv.zip` + `historico_de_versoes.pdf` (só no host antigo, desliga 31/08/2026) | guarda de layout dos CSVs | P | **urgente (2 dias)** |
| 16 | Emendas estaduais ES (CKAN, 15 CSVs) · emendas MG (planilhas) · `fns_repasses` · obras FNDE (Antonieta) · TE pela API oficial nova | escopo novo com fonte oficial verificada | P/M · M · M · M · M/G | `municipios.cnpj` nos 4 tenants; teste do IP da VPS (TE) |
| 17 | Auto-limite 1×/dia em CAUC/Acordo FES/SIMEC-PAR (hoje 10–14×/dia) e frescor esperado realista (CAGE-RS 60 d, GO 90 d) | menos carga no host burstable; menos falso "atrasado" | P | — |
| 18 | Docs: CRON_SETUP, INFRA (backoff TG; simec-termos; 44→42 municípios), `rm_export` comentário, `base.py`, tetos de versão + lock | honestidade da doc / builds reprodutíveis | P | — |

## B.9 Limitações desta auditoria

- **Outros 3 tenants** (Trust, Monte Sião, Santa Maria): não medidos; a hipótese A pode estar
  "confirmada" neles (env não lida). Para verificar: `docker inspect` dos 3 workers (whitelist).
- **Fonte com login**: SIGCON-MG não foi consultado na fonte (exigiria credencial da Freitas);
  o detalhe autenticado do TransfereGov (`dt_fim_vigencia` 31/12/2026 vs 16/12/2024) idem.
  A extensão Claude in Chrome negou leitura do DOM em `discricionarias.transferegov…`; a
  verificação na fonte foi por captura de tela (listagem da proposta), não por leitura de campos.
- **Causa do reinício do Coolify às 00:00 UTC**: não investigada (fora do escopo read-only do
  host).
- **Rodada do CAGEC das 04:50 UTC**: sabe-se que morre no `timeout`; o motivo (CRC, portal
  lento, quantidade) exige rodar com log — não executado (regra: não rodar coletor).
- **`TG_IGNORA_SITUACOES` real do worker**: não está na env (usa o default); confirmado.
- **Duração das rodadas pelo `ingestion_log`**: impossível (`started_at≈finished_at`); usada
  a do Coolify.
- **Bloco 3**: URLs verificadas por agentes em 29–30/08; cadência e cobertura de datasets são
  as declaradas pelos portais no dia — podem mudar.
