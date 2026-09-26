# Backlog por estado — o que falta executar da auditoria de 17/08/2026

> **O que é isto.** A auditoria dos 4 tenants (`C:\dev\Auditoria-PACTHA-2026-08-17.pdf`,
> 25 págs) terminou com um plano em ondas no Capítulo 5 e **nada foi executado por
> instrução explícita do dono**. Este arquivo é a conferência desse plano contra o
> repositório em **25/08/2026** — o que saiu, o que não saiu, e o backlog por estado na
> ordem de prioridade definida pelo dono: **MG → RS → GO → ES → TO** (PR e SC ficam para
> depois, fora do horizonte atual).
>
> O PDF da auditoria continua sendo a fonte longa (pesquisa por estado com fontes
> oficiais citadas). Este arquivo é o que sobrou de trabalho, com as referências de
> arquivo/linha já conferidas.

---

## 1. Status: o plano da auditoria NÃO foi executado

Dos 30+ commits entre 17/08 e 25/08, **todos** foram aprofundamento federal / RM para a
Freitas: Notas de Empenho, Projeto Básico/TR, SIMEC Termos, Obras (resumo físico-financeiro,
responsável técnico), Vigências, RM em Word e por seleção de consultas, pagamentos da
Transferência Especial. **Zero itens da Onda 3** (cobertura estadual).

Da Onda 1 só entrou o que veio de carona no `69b04f2` (24/08, "Permissões por estado na aba
Usuários"):

| Item da Onda 1 | Status em 25/08 | Onde |
| :--- | :--- | :--- |
| **P3** — chip "Acordo FES … MG" condicionado à UF | ✅ feito | `services/permissoes.py` (`ufs=("MG",)`) |
| **P9** — `AND uf='MG'` no SQL do coletor SIGCON | ✅ feito | `ingestion/sigcon_scraper.py:906` |
| **P1** — cadastro estadual parametrizado por UF no BI | ⚠️ **meio feito** | título já usa `tituloEstadual` (`abas.tsx:1120,1292`), mas a Visão Geral ainda carimba `"CAGEC · obrigações"` fixo em **`abas.tsx:238`** |
| **P2** — tela Regularidade: banner e textos por UF | ❌ pendente | |
| **P4** — Cofre: filtrar integrações pela UF da carteira | ❌ pendente | `dashboard/cofre/page.tsx` lista SIGCON-MG em qualquer tenant |
| **P5** — remover fallbacks "MG" e placeholder "ARAUJOS" | ✅ **feito em 02/09/2026** | Eram TRÊS, não dois: `dashboard/dou/page.tsx`, `dashboard/fns/page.tsx` e — o mais grave, porque grava dado — `ingestion/fns_scraper.py`, que assumia Minas para resolver o código FNS pelo NOME e podia casar com município homônimo de outro estado |
| **P6** — menu esconde módulos estaduais com UF desconhecida | ❌ pendente | `dashboard/layout.tsx:297` guarda com `ufAmbiente &&` → na dúvida mostra tudo |
| **P7 / P8** — rótulos residuais + `/api/cagec` neutro | ❌ pendente | |
| **O2** — TE e InvestSUS no catálogo de frescor/watchdog | 🟡 metade | **TE feita**: no `routers/freshness.py` desde 06/09/2026 e em `watchdog_coleta.FRESCOR_HORAS_NACIONAL` desde 14/09/2026 (CONTINUAR §1.23). **InvestSUS continua fora dos dois** (zero ocorrências de `investsus`, conferido em 14/09/2026) |

⚠️ **A Onda 0 não é verificável pelo repositório** — é tudo env var e Scheduled Task no
Coolify. Precisa ser conferida no painel.

---

## 2. Onda 0 — decisões do dono, ainda em aberto

Nenhuma exige código; somadas dão ~1h de execução. Continuam pendentes desde 17/08:

| # | Decisão | Por que importa |
| :--- | :--- | :--- |
| **S1** | Santa Maria: `AUTHZ_MODO` de `aviso` → `bloqueio` | Usuário autenticado da prefeitura pode acessar além da permissão **durante a avaliação do sistema** |
| ~~**S3**~~ | ~~Freitas: manter ou desligar `TG_OPS_OBS=1`~~ | **Resolvido em 15/09/2026** (PR 4 da §1.26 do CONTINUAR): `TG_OPS_OBS=0` nos seis workers, porque o desembolso vem do dump. As obras seguem com a chave própria `TG_OBRAS=1` — ver INFRA §5 |
| **S4** | SICONV nos 3 tenants: ligar `SICONV_MODULE=1` **ou** remover task + truncar | Hoje está no pior dos dois mundos: ~393 MB/banco e coleta paga, sem tela |
| **S5** | Faxina de contas `teste.com`, `claude.com`, 35× `painel.local` | Contas não rastreáveis em produção de prefeitura |
| **S2** | Freitas: `siconv-federal` de diário → mensal (dia 2) | Dump grande baixado todo dia para dado que muda 1×/mês — rede e I/O à toa (a justificativa dizia "host burstable"; a máquina tem 8 vCPU desde o upgrade, mas o desperdício continua) |
| **O4** | Trust: preencher o CNPJ de Goiânia via control-plane | Repasses e TE de Goiânia não casam com o município |
| **O3** | Ação comercial: reset de 4 credenciais SIGCON quebradas (Freitas) + 21 faltantes (Freitas) + 7 (Trust) | 28 municípios de MG sem convênios/emendas estaduais |

### ⚠️ Achado operacional aberto — CAGEC

Na janela de 17-18/08 o CAGEC **falhou em massa nos 3 tenants de MG** (timeout "listar
entidades"). Não dá para verificar pelo repositório se voltou.

Hipótese registrada na auditoria: a **Resolução Conjunta SEGOV/CGE 02, de 30/12/2025**,
mudou a norma do cadastro e houve exigências novas em 2025 (ex.: credenciamento do
representante do CMAS para o FMAS) — o parser do CRC pode estar lendo uma tabela que mudou.

**Primeira coisa a conferir na volta.** Se persistir, é diagnóstico do portal + ajuste do
scraper ZK (a parte mais frágil do sistema).

Relacionado, e crônico: **Arcos, Nova Lima e Ubá** nunca casam no CAGEC por nome — precisam
casar por CNPJ ou grafia alternativa.

---

## 3. Backlog por estado

Classificação herdada da auditoria: **COLETADO** (automático, no ar) · **CURADO** (conteúdo
editorial com aviso, por decisão) · **BLOQUEADO** (impedimento externo real) · **AUSENTE**
(não existe no produto).

### 3.1 Minas Gerais — completo no núcleo, com dinheiro invisível na borda

Prioridade 1 do dono. 3 dos 4 tenants têm município de MG.

| Lacuna | Status | O que fazer |
| :--- | :--- | :--- |
| **TE-MG — Transferência Especial estadual** (art. 160-A da CE/MG) | **COLETADO** (indicação pelo SIGCON + execução pelos dados da SEGOV no dados.mg.gov.br, `emendas_mg.py`, 2023+) — o que segue abaixo é o registro de 25/08 | **A maior lacuna de MG.** Repasse direto ao município **sem convênio** — não aparece no SIGCON como convênio. Desde 2026 exige plano de trabalho no SIGCON, com prazos próprios (indicação até 20/03, plano até 16/11). Municípios da Freitas recebem TE-MG e o PACTHA não mostra. Fonte: planilhas de `emendas.mg.gov.br` + Resolução SEGOV 18/2026 |
| **Emendas impositivas — fonte oficial** | **COLETADO** (`emendas_mg.py`, CSV `portal_emendas_estaduais` do dados.mg.gov.br, 2023+; ⚠️ as planilhas do emendas.mg.gov.br dão 403 a IP de datacenter e pararam em 12/05/2026) | Hoje o parlamentar é **derivado do texto do objeto** do convênio SIGCON. A fonte oficial estruturada existe: planilhas Excel de execução 2019-2026 em `emendas.mg.gov.br/transparencia` (SIAFI+SIGCON+SIAD, **com dicionário de dados**), cobrindo todas as modalidades. Valida o nosso derivado **e** resolve a TE-MG no mesmo coletor |
| **Fundo a fundo — saúde e assistência** | **SAÚDE COLETADA** (24/09/2026: painel "Pagamento de Resoluções" da SES, `ses_mg_resolucoes.py`, tela ESTADUAIS › Cofinanciamento Saúde); assistência (Piso Mineiro) e SES Resolve seguem AUSENTES — o que segue abaixo é o registro de 25/08 | Emendas e cofinanciamento executados como **resolução, não convênio**. Painel público "Pagamento de Resoluções" da SES (2019-2026); Plano de Serviços do Piso Mineiro preenchido no próprio SIGCON (credencial que já temos). Novidade 2025: **SES Resolve** substituiu o SIGRES (login gov.br — candidato à captura de sessão que já dominamos) |
| **Regularidade além do CAGEC** | PARCIAL | Hoje só via CRC. Existem consultas diretas e públicas: **CADIN-MG** por CNPJ, **CDT da SEF-MG** (SIARE) e a lista de inadimplentes do **SICOM/TCE-MG** (publicada automaticamente, + dados abertos do TCE). Valor: avisar **antes** de o CRC vencer |
| **Radar de captação** | AUSENTE | PTE-MG (transporte escolar, 10 parcelas/ano), ICMS Robin Hood / IEPHA (pontuação do Patrimônio Cultural), Edital BDMG Municípios 2026, FHIDRO (70% não reembolsável). Formato curado + alertas por palavra-chave no Diário que já coletamos |

**Dois riscos a vigiar em MG:**

1. **`sigconsaida.mg.gov.br`** — portal institucional novo. O login ainda está no domínio
   antigo; **se o login migrar, o scraper do SIGCON quebra**. O manual também foi reformulado.
2. **Resolução Conjunta SEGOV/CGE 02/2025** — pode ter mudado o CRC do CAGEC (ver §2).

### 3.2 Rio Grande do Sul — a curadoria envelheceu; nenhum scraper novo é necessário

A pesquisa da auditoria trouxe 6 novidades. Tudo abaixo é conteúdo/checklist, **exceto** o
CADIN, que muda de classificação.

| Item | Mudança |
| :--- | :--- |
| ~~**CHE — checklist de 9 → 11 itens**~~ | ❌ **A premissa não se confirmou (medido 02/09/2026).** A API do CHE devolve **dez** exigências para a Prefeitura de Nova Palma, não onze — e **a tela não usa lista nenhuma**: `ingestion/che_rs.py` grava o que a API mandar, com `GRUPO_PADRAO` para item não mapeado, então exigência nova entra sozinha. Não havia o que consertar no produto; o que estava errado era o `MAPA_RS.md` §2.2, que listava nove e omitia "Adesão Programas Estaduais". Corrigido lá. Segue valendo verificar se a certidão CHE virou espelho do monitoramento mensal |
| **CADIN/RS — sai de BLOQUEADO** | Desde ~05/2025 existe **consulta autenticada via gov.br com certidão em tempo real** (`cadin.sefaz.rs.gov.br`). Pode migrar de conteúdo curado para **coleta assistida**, mesmo padrão gov.br do TransfereGov. O caminho público segue com captcha + janela seg-sáb 7h-22h30 |
| **CFIL/RS — rebaixar na tela** | Correção de rota: o CFIL é cadastro de **fornecedores impedidos de licitar** — não é exigência do município convenente. Hoje está no mesmo plano do CADIN, e não deveria |
| **FUNRIGS — deixou de ser "só normativos"** | O Fundo a Fundo da Reconstrução foi regulamentado (**Decreto 58.119/2025**; 13 municípios contemplados até 04/2026 — **Santa Maria fora da lista**) e o TCE-RS publicou **painel público do FUNRIGS**. Atualizar a tela curada com os requisitos (fundo municipal, conselho, nexo causal) e o painel como link |
| **Emendas estaduais — números de 2026** | Seguem **autorizativas** (reconfirmado). Regra 2026: R$ 4 mi/deputado, ≥50% saúde, reversão para APS se não executada em 2 exercícios. Atualizar com a **Portaria SES 348/2026** (R$ 116 mi / 962 emendas de saúde) |
| **Programas setoriais** | Atualizar ciclo "Avançar Mais" (R$ 3,7 bi) e **PIAPS 2026** (R$ 395 mi, Portarias SES 68-69/2026) |
| **Portal de Convênios / FPE** | Continua INERTE aguardando credencial PCPRS (decisão: **não pedir durante a avaliação**). Novidade: desde 04/2025 há **mais dois sistemas no mesmo login** (Propostas e Prestação de Contas) — quando a credencial vier, cobrir os três |
| **TCE-RS** | 403 para IP de datacenter **reconfirmado em 17/08**. Saídas: pedido de liberação (LAI), proxy residencial de saída, ou coleta assistida. As certidões do TCE são insumo direto do CHE |

**Ausentes novos detectados pela pesquisa (roadmap):** ① **CDTV** — cadastro estadual de
demandas de transferência voluntária, a "porta de pleitos" do RS (login); ② **FUNDEC →
FUMDEC** — fundo a fundo da Defesa Civil (R$ 60 mi; exige COMPDEC, plano de contingência e
FUMDEC); ③ **Pagamentos do FES** — consulta pública AME3/PROCERGS dos repasses mensais da
saúde por município (**candidata a coletor de verdade**); ④ **PEATE** — transporte escolar
(~R$ 228 mi/ano, 10 parcelas); ⑤ **FEAS/Piso Gaúcho**; ⑥ Conexões RS, Drenagem RS, A Casa é
Sua, FAC-Cultura, Pró-Esporte, FRH, Badesul-BRDE Cidades (editais em PDF — radar curado).

### 3.3 Goiás — pagamentos cobertos; instrumento, emenda e regularidade descobertos

| Item | Status | O que fazer |
| :--- | :--- | :--- |
| **Emendas de GO** | AUSENTE | **Ganho rápido nº 1 de GO.** Dataset CKAN "Emendas Parlamentares — SERINT", CSVs 2019-2025: nº da emenda, deputado autor, objeto, município beneficiário, CNPJ, tipo, empenho/liquidação/pagamento. Inclui a **Transferência Especial goiana** (art. 111-A CE-GO, Decreto 10.634/2025). Hoje só extraímos o deputado da **descrição do pagamento**, o que é frágil. ⚠️ Armadilha conhecida: campos numéricos longos vêm em **notação científica** no CSV |
| **Regularidade goiana** | NÃO EXISTE cadastro | Confirmado: **GO não tem CAGEC/CHE**. A regularidade é por certidões avulsas, todas públicas por CNPJ: CND SEFAZ-GO (60 dias), certidão de limites constitucionais e atestado de adimplência do **TCM-GO**, CADIN Estadual (Lei 19.754/2017) e a peculiaridade goiana: **adimplência perante a SANEAGO**. A tela de regularidade de GO deve virar **checklist dessas certidões** |
| **RN 10/2025 do TCM-GO** | AUSENTE | Criou obrigações novas para o município receber emenda: **conta específica por transferência, plano de trabalho prévio, execução 2026 condicionada à conformidade**. Oportunidade de produto — o PACTHA vira a ferramenta que ajuda a cumprir (checklist + alertas) |
| **Instrumentos (não só pagamento)** | PARCIAL | SIGECON é atrás de login, sem consulta pública de situação. O dataset de instrumentos da SEGOV morreu em 2018; hoje estão pulverizados por órgão no CKAN (GOINFRA mensal desde 2023 — inclui Goiás em Movimento —, SECULT, AGEHAB, FAPEG, UEG, Emater). **Vigiar o painel público prometido do SISREG** (novo em 04/2026, registro retroativo a 2019 por determinação do TCE-GO) — quando sair, vira o consolidado que falta |
| **Fundo a fundo** | AUSENTE | Goiás Social / FEAS (Lei 21.811/2023 — R$ 2,50/família CadÚnico/mês aos 246 municípios; nova parcela exige 70% de execução). Planilha XLSX semi-estruturada; gestão no SIGS/GO (login) |

⚠️ **Avisos operacionais de GO:** o portal de convênios responde **só por HTTP** (TLS
inválido); o Portal da Transparência novo tem **WAF que bloqueia acesso programático** —
usar a API CKAN, que é aberta.

### 3.4 Espírito Santo — o mais barato de fechar

| Item | Status | O que fazer |
| :--- | :--- | :--- |
| **Emendas estaduais do ES** | AUSENTE | **Ganho rápido nº 1 do ES.** Dataset CKAN `portal-da-transparencia-emendas-parlamentares-do-estado` com **15 CSVs** — inclusive o vínculo **emenda→convênio** e **emenda→contrato** — atualizado diariamente. Mesmo padrão do coletor GConv que já existe. Esforço baixo, valor alto. (Emendas do ES **não** são impositivas — confirmado) |
| **CRCC** | AUSENTE | O equivalente capixaba do CAGEC/CHE (Portaria SEGER 010-R/2016, validade 12 meses). **Consulta pública na área aberta do GConv-web** (JSF, sem login). O rótulo da tela já existe, falta o coletor — consulta pontual, não raspagem em massa |
| **Fundo Cidades** (LC 712/2013) | AUSENTE | **Maior programa estadual de repasse discricionário a prefeituras capixabas** — R$ 1,12 bi 2022-2025 + vertente climática R$ 324 mi. Sem dado estruturado próprio (portarias/PDF + execução no SIGEFES/CKAN): formato curado + radar no DIO-ES |
| **Regularidade: CADIN-ES, CND SEFAZ-ES, dívida ativa PGE** | AUSENTE | CADIN-ES (Lei 7.727/2004) trava a CND estadual, que o CRCC exige. Consultas públicas por CNPJ em HTML; **a CND tem captcha** (limitação já conhecida) |
| **TCE-ES** | AUSENTE | Dataset de obrigações/consistências de remessa no CKAN estadual permite alertar **remessa pendente** do município. Painel de Controle público |
| **Fundo a fundo (SESA, FEAS/SETADES ~R$ 90 mi/ano, PETE/SEDU)** | AUSENTE | Rastros em portarias no DIO-ES, **que já coletamos** — regras de detecção por palavra-chave dão cobertura imediata de baixo custo |
| **Prestação de contas** | AUSENTE (conteúdo) | Decreto 2.737-R/2011 + Normas SCV 006-010/2025: 60 dias para prestar, 90 para analisar, guarda 10 anos. Matéria para checklist curado, equivalente ao que a tela do RS já faz |

Vigiar: o ciclo segue no SIGA/GConv; o **SIADES novo ainda não absorveu convênios**.

### 3.5 Tocantins — maior lacuna, e a mais fácil de atacar

| Item | Status | O que fazer |
| :--- | :--- | :--- |
| **Certidão de Regularidade de Transf. Voluntárias (CGE-TO)** | AUSENTE (**rótulo já pronto**) | **Ganho rápido nº 1 do TO.** Consulta/emissão **pública por CNPJ, sem login e sem captcha**, em `gestao.cge.to.gov.br/convenioseparcerias/certidao_convcedido/` — **verificado ao vivo**. ⚠️ Host **sem `www`**: o TLS do `www` é quebrado. É o semáforo de adimplência estadual do TO (Decretos 5.815 e 5.816/2018, vigentes) |
| **Repasses fundo a fundo da saúde (FES-TO → FMS)** | AUSENTE | **Ganho rápido nº 2.** Consulta pública em `sistemas.saude.to.gov.br/repasse_fundoafundo/` — formulário HTML clássico com dropdown de **~139 fundos municipais** por CNPJ, por ação/programa e mês, **série 2010-2025**. Dificuldade baixa-média |
| **TCE-TO** | AUSENTE | **A melhor porta estruturada do estado:** WebServices REST públicos em `api.tceto.tc.br/econtas/api` (processos/decisões por município). Lista de gestores com contas irregulares em PDF/HTML. ⚠️ No TO **quem julga conta municipal é o próprio TCE-TO** — não há TCM |
| **Convênios estaduais (Transfere.TO)** | **COLETADO desde 23/09/2026** (`convenios_to.py`, fonte `TRANSFERE-TO`) | ⚠️ O que esta linha dizia em 25/08 ("atrás de login; dificuldade alta") estava errado: o TRANSFERE.TO tem uma **pesquisa externa pública** (`convenio.to.gov.br/PesquisaExterna/VisualizarConvenio.aspx?idConvenio=N`), achada atrás do botão "Consulta de Emendas" do Portal da Transparência — GET simples, com CNPJ do convenente, ordens bancárias e a emenda de origem. Falta: a consulta de EMENDAS do mesmo sistema (`ConsultarEmendas.aspx`, filtro por município), para a tela de emendas estaduais |
| **Emendas impositivas** | AUSENTE | EC 27/2014; **EC 55/2024 elevou a 1,73% da RCL**, ~R$ 10 mi/deputado; o repasse independe de adimplência desde 2019. Plataforma pública da Assembleia é um **app Shiny** (indicações por deputado/município, integrada a SIAFE+Transfere.TO; R$ 241 mi indicados em 2025) — headless, média-alta. No mínimo: tela curada com as regras (25% saúde, 13,5% investimento) |
| **CND SEFAZ-TO** (finalidade "CONVÊNIO") | AUSENTE | Pública por CNPJ com PDF, dificuldade baixa. **CADIN-TO estadual não existe** (confirmado) — o papel é da certidão da CGE |

⚠️ **Avisos operacionais do TO:** não há CKAN estadual (`dados.to.gov.br` não resolve);
sites `to.gov.br` parcialmente suspensos por legislação eleitoral desde 04/07/2026 — os
coletores novos devem **tolerar o interstício**; TLS quebrado nos hosts `www.` de
transparência e da CGE.

### 3.6 Santa Catarina — medido em 23/09/2026, SEM cliente (não construir ainda)

Nenhum tenant tem município de SC. O cartão do relatório de fontes do dono ("SIGEF/SC
Transferências e SCtransferências · dados.sc.gov.br", prioridade 1) foi conferido contra a
fonte e **acerta só em parte**. Quando entrar o primeiro cliente catarinense, o coletor sai
em uma sessão — o rótulo "SC Transferências" já existe em `frontend/src/lib/estadual.ts`.

| Item | Status | O que fazer |
| :--- | :--- | :--- |
| **Convênios Simplificados (art. 17-A da CE/SC)** — a "emenda pix" estadual | AUSENTE — **a fonte certa** | Dataset CKAN `tev` da SEF em `dados.sc.gov.br` (CSV/JSON/XLSX, **regerado todo dia ~10:00 UTC**, sem login). 16.921 linhas em 23/09: município, **CNPJ do beneficiário**, objeto, valor autorizado/contratado/pago e **NE, NL e OB com data** — o caminho do dinheiro inteiro. O cartão nem o cita |
| Dataset `transferencias` (fundo a fundo, transporte escolar, subvenções, voluntárias) | **PARADO desde 03/2022** | O cartão o vende como a fonte principal; não serve para coleta diária. O link de consulta que o dataset aponta (`transparencia.sc.gov.br/transferencias`) dá 404 |
| Portal SCtransferências (CGE-SC) | a medir | Mudou para `www.cge.sc.gov.br/sctransferencias/` (o endereço antigo redireciona). Falta ver o que a consulta pública mostra sem login |

---

## 4. InvestSUS, SISMOB, SiGPC e SUASWeb — o estado real

### InvestSUS: a credencial já foi entregue e ela funciona

Registrado no código (`services/investsus_conteudo.py`) e medido em **17/08/2026 com a
credencial real do Monte Sião, pelo fluxo correto**: a senha está certa, o login passa. A
tela seguinte é o **cadastro do segundo fator** — TOTP obrigatório no SCPA, ainda não
cadastrado nessa conta.

**Não é preciso repassar a credencial.** O que falta é uma pendência do cliente:

1. Instalar um aplicativo autenticador no celular.
2. Entrar em `acesso.saude.gov.br` com o CPF e a senha do InvestSUS e ler o QR Code da
   tela de cadastro do MFA.
3. **Guardar a chave em base32 que aparece ao lado do QR Code** — é ela que o coletor
   precisa, não o código de 6 dígitos.
4. Cadastrar esse segredo no Cofre (`automation_key='investsus'`), cifrado como qualquer
   senha. Com ele o coletor gera o código sozinho (`pyotp`) e o fluxo fecha sem gente na
   frente.

Para conferir se a credencial ainda está no Cofre daquele tenant: abrir
`/dashboard/investsus` no Monte Sião — a tela mostra exatamente isso, é a única informação
viva que ela tem hoje.

⚠️ Quando o coletor nascer, "MFA pendente" deve ser **estado próprio** no `ingestion_log`,
nunca erro de senha: são pendências diferentes, com donos diferentes.

### SISMOB: quase certamente há mais atrás de login — mas ninguém verificou

**O que se sabe:** o coletor usa apenas `sismobcidadao.saude.gov.br/api/public/obras`, que
responde sem token e sem cookie. O Cofre **já oferece a caixinha "SISMOB — Obras de
Saúde"** (`automation_key='sismob'`), mas **nenhum coletor consome essa credencial** — é
slot vazio, mesmo caso de `simec` e `suas`.

**O que não se sabe, e não deve ser afirmado antes de medir:** o prefixo `/api/public/` é
indício forte de um irmão não-público, e o SISMOB de gestor do Ministério da Saúde fica
atrás do **SCPA — o mesmo autenticador do InvestSUS**. Ninguém sondou até hoje.

⭐ **Consequência prática:** se o Monte Sião cadastrar o MFA, provavelmente destrava os
**dois**. Vale fazer o recon do SISMOB logado no mesmo dia e com a mesma conta do
InvestSUS — o padrão de reconhecimento já está documentado no cabeçalho de
`services/investsus_conteudo.py`.

### SiGPC (FNDE): só com o gov.br do gestor — registrado, NÃO construir (26/09/2026)

Cartão "SiGPC — prestação de contas da educação" do relatório de fontes do dono (p.32,
prioridade 3). Situação, pendências e prazos de prestação de contas do PDDE, PNAE e PNATE
por exercício. **Só existe logado**: gov.br do gestor, com perfil que o dirigente municipal
de educação cadastra. Medido em 26/09/2026: não há consulta pública
(`/sigpc/contasonline/` 404, `/pls/simad/` sem rotina de prestação de contas). Pela regra
de só usar fonte pública enquanto a prefeitura avalia o sistema, fica fora.

O que da prestação de contas **já chega sem login**: as escolas com PDDE suspenso
(`pdde_info`, #576), que é a consequência visível da conta não prestada, e as liberações
por entidade (`fnde_liberacoes`, #575), onde repasse que parou de vir aparece como buraco no
histórico. Se um cliente entregar a credencial, o slot é o do `simec` no Cofre.

### SUASWeb: as consultas "públicas" têm hCaptcha conferido no servidor (26/09/2026)

`aplicacoes.mds.gov.br/suaswebcons` abre sem login três relatórios (Parcelas Pagas, Saldo
Detalhado por Conta, Distribuição Financeira por Piso), mas o Pesquisar devolve "Falha na
verificação do Captcha" sem o token do hCaptcha. **Não automatizar.** O mesmo dado, com
mais detalhe, sai do painel Qlik do FNAS, que aceita sessão anônima (ver o cartão FNAS em
`CONTINUAR.md`). A parte logada (plano de ação, demonstrativo) segue fora, como o SiGPC.

---

## 5. Sequência proposta

A ordem do dono é **MG primeiro**. Ela faz sentido: 3 dos 4 tenants têm município de MG e é
lá que está o dinheiro invisível (TE-MG).

⚠️ **Uma ressalva de tempo, não de mérito.** Santa Maria é uma prefeitura **avaliando** o
sistema, e é justamente lá que sobra rótulo de Minas na tela. A Onda 1 é ~1,5 dia e fecha
isso num PR só. Enquanto a avaliação estiver correndo, ela paga mais que qualquer coletor
novo — um coletor a mais não recupera cliente perdido por parecer sistema de outro estado.
**Se a avaliação já terminou, essa ressalva cai e MG entra direto.**

| Ordem | Bloco | Tamanho |
| :--- | :--- | :--- |
| 1 | **Onda 0** — as 7 decisões do §2 + conferir se o CAGEC voltou | ~1h + decisão |
| 2 | **Onda 1** — "RS sem rótulo de MG", num PR único revisado | ~1,5 dia |
| 3 | **MG** — planilhas de `emendas.mg.gov.br` cobrindo emendas oficiais **e** TE-MG num coletor só | 1-1,5 dia |
| 4 | **MG** — fundo a fundo: ~~painel "Pagamento de Resoluções" da SES~~ (feito 24/09/2026, `ses_mg_resolucoes.py`) + avaliar SES Resolve | 1-2 dias |
| 5 | **RS** — atualizações da pesquisa (§3.2): checklist CHE 11 itens, CADIN reclassificado, CFIL rebaixado, FUNRIGS, números 2026 | 0,5-1 dia |
| 6 | **GO** — coletor de emendas (SERINT/CKAN) | 0,5-1 dia |
| 7 | **ES** — coletor de emendas (CKAN, 15 CSVs) | 0,5-1 dia |
| 8 | **TO** — certidão CGE-TO por CNPJ + tela de regularidade | 0,5-1 dia |
| — | **Em paralelo, barato:** O2 — incluir o InvestSUS no monitor de frescor e no vigia (a TE já entrou) | 1h |

O item marcado "em paralelo" evita cegueira: hoje a Transferência Especial pode ficar meses
sem coletar e ninguém ver — **já aconteceu**.

Lembretes que valem para todas as ondas: um merge na `main` **deploya os 4 tenants**;
migrations precisam ser idempotentes nos 4 bancos; nunca editar comando de Scheduled Task
com string interpolada de PowerShell.

---

## 6. Duas perguntas em aberto para o dono

1. **A avaliação de Santa Maria ainda está em curso?** Define se a Onda 1 vem antes ou
   depois do bloco de Minas.
2. **O CAGEC voltou a coletar depois de 18/08?** Se não, é a primeira coisa a diagnosticar —
   43 municípios de MG ficam sem regularidade estadual nos 3 tenants.

---

*Conferido contra o repositório em 25/08/2026. A fonte longa, com a pesquisa por estado e as
fontes oficiais citadas uma a uma, é `Auditoria-PACTHA-2026-08-17.pdf` (Capítulo 4 para a
cobertura por estado, Capítulo 5 para o plano em ondas com esforço por item).*
