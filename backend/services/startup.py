"""
Startup tasks executadas no boot do FastAPI.

Roda migrations idempotentes ao subir o backend, garantindo que:
- Tabelas existem (mesmo apos reset do DB)
- Seeds institucionais (Comissao da Saude, Bancada MG, etc.) estao populados
- Indices estao criados

Cada migration e rodada via psycopg2 raw - usa SYNC para nao bloquear o
event loop async no caso de demora. Falha em uma migration nao impede o
boot (logs warning).
"""
import os
import logging
import time
from pathlib import Path

logger = logging.getLogger("startup")

MIGRATION_FILES = [
    # Tabelas core
    "add_audit_and_user_cols.sql",
    "add_service_tokens.sql",
    # RBAC por tela/municipio (estavam fora da lista -> ausentes em clones novos)
    "add_user_telas.sql",
    "add_user_municipios.sql",
    # Fix +30 anos SIGCON-MG (idempotente)
    "fix_sigcon_year_offset.sql",
    # Fix mojibake UTF-8 (PrestaÃ§Ã£o -> Prestação)
    "fix_mojibake_utf8.sql",
    # UNIQUE INDEX nr_sigcon total (preciso pra ON CONFLICT no UPSERT)
    "fix_unique_nrsigcon_full.sql",
    # nr_proposta + nr_plano_trabalho + qt_alteracoes + dt_assinatura (SIGCON view)
    "add_nr_proposta_estadual.sql",
    # Tabela emendas_estaduais (SIGCON Pesquisar Emendas Por Convenente)
    "add_emendas_estaduais.sql",
    # Refactor lean (2026-05): drop tabelas das features removidas
    "drop_lean_tables.sql",
    # UNIQUE INDEX em nr_siafi (previne duplicacao scraper+CKAN)
    "add_unique_nr_siafi.sql",
    # Valores monetarios das Voluntarias (valor_global/repasse/contrapartida)
    "add_voluntarias_valores.sql",
    # SIMEC PAR (consulta publica MEC) - dimensoes + liberacoes
    "add_simec_par.sql",
    # Relatorio de Monitoramento (RM) - padrao Freitas
    "add_rm.sql",
    # RM: escopo ('anual'|'completo') + unique tripla -> RM completo coexiste
    "add_rm_escopo.sql",
    # RM: escopo por SELECAO de anos (coluna anos INT[], unique (municipio, anos))
    "add_rm_anos.sql",
    # RM: escopo por SELECAO DE CONSULTAS (coluna fontes TEXT[]). DOIS arquivos
    # de proposito — o runner roda cada um numa transacao unica, e juntos uma
    # falha do indice reverteria a coluna. Ver o cabecalho de cada um.
    # ⚠️ ESTE E O DEPLOY 1 DE DOIS: o indice ANTIGO (ux_rm_mun_anos) continua de
    # pe aqui, para o container velho nao tomar 42P10 durante a troca. O
    # `drop_rm_unique_anos.sql` entra num PR POSTERIOR.
    "add_rm_fontes_coluna.sql",
    "add_rm_fontes_indice.sql",
    # RM: DEPLOY 2 DE DOIS — derruba a identidade ANTIGA (ux_rm_mun_anos), que so
    # a partir daqui deixa o RM completo e o filtrado coexistirem no mesmo periodo.
    # ⚠️ DEPOIS de `add_rm_fontes_indice.sql` na lista E num deploy POSTERIOR ao
    # dele: registrar os dois juntos derrubaria o indice antigo enquanto o
    # container antigo ainda estivesse no ar. O proprio arquivo tem guard e vira
    # no-op se o indice novo nao existir naquele tenant.
    "drop_rm_unique_anos.sql",
    # RM: e-mail do cabecalho, carimbado na linha (a 1a das tres camadas do
    # rodape). Coluna ANULAVEL e sem DEFAULT — NULL = "relatorio anterior ao
    # campo"; '' gravado pela tela e uma decisao. Nao entra na identidade do
    # relatorio (nao e chave de UPSERT), entao nao precisa do par coluna+indice.
    "add_rm_email.sql",
    # RM por ESTAGIO (pagas/pendentes/todas) — DEPLOY 1 DE DOIS. A coluna e o
    # indice NOVO; o DROP do anterior (`ux_rm_mun_anos_fontes`) so entra num PR
    # posterior, depois deste estar nos quatro tenants. Mesma danca que o filtro
    # de consultas ja fez — ver o cabecalho de `add_rm_estagio_indice.sql`.
    "add_rm_estagio_coluna.sql",
    "add_rm_estagio_indice.sql",
    # Portal da Transparencia MG: empenhos/pagamentos do Estado ao municipio,
    # vinculados ao convenio pelo HISTORICO do empenho (o unico lugar onde esse
    # vinculo existe — os dados abertos do Estado nao trazem o campo).
    # Tabela propria, e nao coluna em convenios_estadual: a busca e por CNPJ e
    # devolve empenho SEM convenio. Ver o cabecalho do arquivo.
    "add_transparencia_mg_empenhos.sql",
    # Limpa o `prestacao_contas_sei` que nao e numero de processo (99 de 99 no
    # freitas traziam o rotulo dos botoes). Depende do parser ja corrigido; roda
    # a cada boot de proposito — idempotente e autocurativa.
    "limpa_prestacao_contas_sei_lixo.sql",
    # TE/Emenda Pix federal persistida (coletor especiais -> tabela; RM/tela leem)
    "add_transferegov_te.sql",
    # SIMEC: TERMOS DE COMPROMISSO (o instrumento; as liberacoes ja existiam)
    "add_simec_termos.sql",
    # As quatro colunas de dinheiro que a pagina do SIMEC sempre teve e o parser
    # descartava (empenhado, pago, saldo, prestacao de contas). Aditiva.
    "add_simec_termos_dinheiro.sql",
    # FUNDO A FUNDO da saude: o repasse do FNS ao Fundo Municipal por BLOCO.
    # A maior transferencia federal recorrente da saude, invisivel para a
    # plataforma ate 02/09/2026. Depende da tabela `municipios` (FK), que o
    # create_all dos modelos cria ANTES desta lista.
    "add_fns_repasse_faf.sql",
    # RADAR DE CAPTACAO: programas federais com prazo de proposta ABERTO.
    # ⚠️ Nome novo de proposito. `oportunidades` e `programas_federais` existiram
    # e o `drop_lean_tables.sql` — que continua nesta lista, ACIMA — as derruba a
    # cada boot: reusar qualquer um dos dois nomes apagaria a tabela em todo
    # deploy e o sintoma seria "o radar esvaziou sozinho de novo".
    "add_programas_captacao.sql",
    # AGENDAMENTOS: a agenda de trabalho da equipe (lista, calendario e kanban).
    # ⚠️ Tem FK para `municipios` E para `users` — as duas vem do create_all dos
    # modelos, que roda ANTES desta lista. Se um dia esta migration subir para
    # cima do create_all, o CREATE TABLE falha com "relation users does not
    # exist" e o runner ENGOLE o erro (compara por substring): a tabela nao
    # existiria e a tela responderia 500 sem nada no log de boot.
    "add_agendamentos.sql",
    # Voluntarias: situacao contratacao + clausula suspensiva detalhe + parlamentar
    "add_voluntarias_clausula_parlamentar.sql",
    # Voluntarias: detalhe generico da Situacao de Contratacao (qualquer tipo)
    "add_voluntarias_situacao_detalhe.sql",
    # Voluntarias: processo_execucao_qtd (licitacoes do instrumento - Execucao Convenente)
    "add_voluntarias_processo_execucao.sql",
    # Voluntarias: processo_execucao JSONB (lista COM situacao por licitacao)
    "add_voluntarias_processo_execucao_lista.sql",
    # Voluntarias: projeto_basico JSONB (situacao do Projeto Basico/Termo de Referencia)
    "add_voluntarias_projeto_basico.sql",
    # Voluntarias: notas_empenho JSONB (NEs da aba Execucao Concedente)
    "add_voluntarias_notas_empenho.sql",
    # Voluntarias: valor_emenda (soma dos repasses de emenda; voluntario/proponente derivam)
    "add_voluntarias_valor_emenda.sql",
    # Voluntarias: Historico de Comunicacoes + Termos de Notificacao (mandatarias)
    "add_voluntarias_historico_comunicacoes.sql",
    # Voluntarias: OPs/OBs (repasses/desembolsos) + OBRAS (acompanhamento medicao)
    "add_voluntarias_ops_obs_obras.sql",
    # Voluntarias: ops_obs_atualizado_em -> skip incremental da re-navegacao
    "add_voluntarias_ops_obs_atualizado_em.sql",
    # Voluntarias: detalhe_atualizado_em -> skip incremental do loop de detalhe
    "add_voluntarias_detalhe_atualizado_em.sql",
    # Modulo Gestao Interna (anotacoes + anexos por item)
    "add_gestao_anotacoes.sql",
    # Integracao Telegram (telegram_users + telegram_link_codes)
    "add_telegram.sql",
    # Voluntarias: id_proposta_siconv (casa com open data p/ backfill parlamentar)
    "add_voluntarias_id_proposta_siconv.sql",
    # Log de mudancas de status (trigger) -> aviso no dashboard
    "add_status_changes.sql",
    # Modulo Geracao de Documentos (plano de sustentabilidade etc.)
    "add_documentos.sql",
    # CAUC - regularidade fiscal federal do municipio (dados abertos STN)
    "add_cauc.sql",
    # Acordo FES - divida da saude estadual (SES-MG) com os municipios
    "add_acordofes.sql",
    # Selecao PAC / Novo PAC (TransfereGov guest, por municipio)
    "add_transferegov_pac.sql",
    # Fila de jobs on-demand (ex.: refresh SIGCON disparado pela UI) - Coolify
    "add_scraper_jobs.sql",
    # Acentuacao correta dos rotulos de cidade (convencao "Nome - UF")
    "fix_municipio_acentos.sql",
    # Codigo FNS por municipio (des-hardcoda run_fns_local) - gerido pela Central
    "add_fns_code.sql",
    # Control-plane (Console Alavank): coluna kind em service_tokens
    "add_control_token_kind.sql",
    # SSO tecnico: uso unico REAL do token (compartilhado entre workers)
    "add_sso_used_jti.sql",
    # Painel Executivo do prefeito: push subscriptions + preferencias + dedupe + cache IA
    "add_painel_push.sql",
    # Rodizio de coleta por municipio ("mais desatualizado primeiro"). Mata a
    # starvation alfabetica: antes, a rodada era cortada por volta do 10o de 41
    # municipios e os do fim da lista NUNCA eram atualizados, em silencio.
    "add_scraper_municipio_coleta.sql",
    # Rodizio de PAGINA no laco de detalhe do SIGCON: sem ele o laco relia
    # so a pagina 1 da grade, e 24 dos 28 convenios de Araujos nunca ganhavam
    # prestacao de contas / ultima alteracao / indicacao.
    #
    # ⚠️ ESTAVA LA EM CIMA, ANTES da migration que CRIA a tabela que ela altera.
    # Em tenant antigo nunca doeu — `scraper_municipio_coleta` ja existia de um
    # deploy anterior. Em banco NOVO ela falha: medido no primeiro boot do
    # novapalma-rs (01/09/2026), "relation scraper_municipio_coleta does not
    # exist". Como o runner ENGOLE a falha e segue, o tenant nascia sem a coluna
    # de rodizio e o laco de detalhe do SIGCON relia so a pagina 1 — em silencio,
    # que e exatamente o defeito que esta migration existe para consertar.
    #
    # Mesmo tipo de armadilha que o Santa Maria expos em 08/2026, quando foi o
    # primeiro banco criado do zero. Depende de tabela: vai DEPOIS dela.
    "add_detalhe_pagina_rodizio.sql",
    # Modo Tela do BI: filtro POR USUARIO + links publicos curtos e revogaveis
    "add_bi_tela.sql",
    # CAGEC (regularidade estadual MG). A coleta e publica, por CNPJ, sem
    # credencial — ver routers/cagec.py e ingestion/cagec_scraper.py.
    "add_cagec.sql",
    # separa Prefeitura, Fundo Municipal de Saude e FMAS — cadastros proprios
    "add_cagec_entidades.sql",
    # de quando e o detalhamento do CRC, e o erro do portal quando ele nao sai
    "add_cagec_crc_estado.sql",
    # ⭐ cagec_situacao deixa de ser "a tabela do CAGEC" e passa a ser a tabela
    # do CADASTRO ESTADUAL de convenentes, com coluna `fonte` — e e a coluna
    # `fonte` que permite `uf_sem_default_mg.sql` purgar POR FONTE em vez de por
    # UF. ⚠️ Tem de vir ACIMA daquela migration: se viesse depois, no primeiro
    # boot pos-deploy a purga referenciaria uma coluna inexistente, abortaria a
    # transacao do arquivo inteiro e derrubaria junto o DROP DEFAULT da uf.
    "add_cadastro_estadual_rs.sql",
    # Tipo do link publicado: TV de parede ('tela') ou app de celular ('mobile')
    "add_bi_tela_link_kind.sql",
    # Historico da IA por usuario, retencao de 30 dias (expurgo automatico)
    "add_ai_historico.sql",
    # SISMOB: obras de saude do MS (API publica, sem login). Tabela propria —
    # obra tem etapa/percentual/empreiteira, que nao cabem em 'convenio'.
    "add_sismob.sql",
    # Base publica nacional do SICONV (dados abertos), usada na consulta por CNPJ.
    # Nasceu ORFA em a53afcc: o commit criou a migration e nao a registrou aqui,
    # entao o runner nunca a executava. Nas instancias antigas a tabela existe
    # porque foi criada a mao; num tenant novo ela simplesmente nao nascia e
    # `routers/transferegov.py` (que consulta sem guarda) devolvia 500. E
    # CREATE TABLE/INDEX IF NOT EXISTS, sem INSERT: inerte onde ja existe.
    "add_siconv_federal.sql",
    # Marca de quiosque no USUARIO (nao no claim do JWT, que o refresh nao
    # repassa). Fecha o link publico de TV no Painel de Indicadores.
    # DEPENDE de add_bi_tela.sql — o backfill le bi_tela_links — por isso vem
    # depois dela nesta lista.
    "add_users_kiosk.sql",
    # Auditoria detalhada: municipio, sessao, resultado, rota, snapshots legiveis
    # e valor-antes/valor-depois. Puramente ADITIVA sobre audit_log — nenhuma
    # coluna existente muda, nenhuma linha antiga e reescrita (o unico UPDATE e
    # o backfill do nome do autor, com guarda `usuario_nome IS NULL`).
    "add_auditoria_detalhada.sql",
    # Incremento 4 — o papel vira ROTULO: `super_admin` e `somente_leitura` no
    # usuario, e o BACKFILL que evita o apagao (todo admin de cliente ganha,
    # explicitamente, as telas e municipios que hoje ele so tem pelo bypass de
    # `role == 'admin'`). DEPENDE de add_user_telas / add_user_municipios (as
    # tabelas que ela preenche) e de add_users_kiosk (le `users.kiosk`), todas
    # acima nesta lista. O backfill so pode rodar UMA VEZ — a propria migration
    # cria `migration_backfills` para isso; ver o cabecalho dela.
    "add_role_vira_rotulo.sql",
    # Incremento 5 — permissao por ACAO (`recurso.acao`) por usuario: a
    # tabela-catalogo (chave estrangeira que mata o typo silencioso), a tabela
    # de concessao e o BACKFILL de compatibilidade (quem tem a tela X ganha
    # X.ver/X.exportar; os verbos de escrita so para quem e admin hoje).
    # DEPENDE de add_role_vira_rotulo.sql — le `users.super_admin` e conta com
    # `migration_backfills`, os dois criados la — por isso vem depois dela.
    # O backfill so pode rodar UMA VEZ; ver o cabecalho da migration.
    "add_permissoes_por_acao.sql",
    # Incremento 6 — ALCANCE por linha (Row-Level), por usuario e por MODULO:
    # a tabela-catalogo dos modulos escopaveis (FK que mata o typo silencioso) e
    # o alcance escolhido por usuario. DEPENDE de add_permissoes_por_acao.sql
    # so por ordem conceitual (a tabela `users` ja existe muito antes).
    # ⚠️ NAO tem backfill, de proposito: ausencia de linha e `todos`, que e o
    # comportamento de hoje — ninguem perde a edicao no deploy. Ver o cabecalho
    # da migration antes de acrescentar qualquer INSERT ali.
    "add_escopo_por_modulo.sql",
    # Incremento 7 — MODELOS de permissao (o "molde"): as tres tabelas
    # (modelo, conteudo, alcance) e a semente dos QUATRO moldes de prefeitura.
    # DEPENDE de add_permissoes_por_acao.sql (le `permissoes_catalogo`, alvo da
    # FK) e de add_escopo_por_modulo.sql (le `escopo_recursos`) — as duas acima
    # nesta lista.
    # ⚠️ A semente CRUZA `migration_backfills`, ao contrario da semente do
    # catalogo de permissoes: molde e dado que o ADMINISTRADOR edita e apaga, e
    # sem a marca o boot seguinte ressuscitaria o molde apagado ontem. Ver o
    # cabecalho da migration antes de mexer no INSERT.
    "add_modelos_de_permissao.sql",
    # ⚠️ SEMPRE A ULTIMA DA LISTA. Instala o append-only da trilha: gatilho que
    # RECUSA UPDATE/DELETE/TRUNCATE em audit_log e cadeia de hash calculada
    # dentro do banco. Toda migration que ainda faz BACKFILL (hoje so
    # add_auditoria_detalhada.sql, que reescreve `usuario_nome`) tem de rodar
    # ANTES — com o gatilho no ar, um UPDATE de backfill quebraria o BOOT.
    # UF deixa de ter default 'MG' (a Fase 0 tornou a UF decisao explicita de
    # quem provisiona) e a purga do lixo do CAGEC coletado para municipio de
    # fora de MG — linhas que o coletor (agora filtrado por UF) nunca mais
    # visitaria para limpar. Idempotente: DROP DEFAULT e DELETE re-executam
    # como no-op. ⚠️ Registrada AQUI porque o runner so executa o que esta
    # NESTA lista — migration fora dela e orfa e nunca roda (ver o caso
    # add_siconv_federal.sql, acima).
    "uf_sem_default_mg.sql",
    # Repasses estaduais (execução, não instrumento) — Goiás publica pagamento.
    # ⚠️ REGISTRADA AQUI porque o runner só executa o que está NESTA lista;
    # migration fora dela é órfã e nunca roda (foi o que quase aconteceu com a
    # uf_sem_default_mg.sql, pega pela revisão antes do merge).
    "add_repasses_estaduais.sql",
    # Contas julgadas irregulares pelo tribunal de contas (TCM-GO e futuros).
    # ⚠️ INDÍCIO, nunca documento — ver o cabeçalho da migration.
    "add_contas_irregulares.sql",
    # Cofinanciamento estadual da saude (SES-GO e futuros): teto x a receber.
    "add_cofinanciamento_saude.sql",
    # Parametros do ambiente: as listas que o cliente cadastra (hoje o Perfil
    # /Rotulo de usuario) e o sistema puxa nos formularios. Semeia os rotulos
    # que a tela ja oferecia em codigo, para o seletor nao nascer vazio.
    "add_parametros.sql",
    # Identificadores do municipio que o sistema hoje INFERE de dado coletado —
    # e que fora de MG nao ha de onde inferir. O CNPJ e o caso que motiva: o
    # coletor do cadastro estadual precisa so dele, mas ele era deduzido de
    # `emendas_estaduais` (que so existe com SIGCON-MG) ou de `transferegov_pac`
    # (vazia no dia 1). Mais COREDE, codigo no TCE, flag do FUNRIGS e a data de
    # calamidade (o antidoto do falso alarme do Decreto 56.939/2023).
    "add_municipio_identificadores.sql",
    # Registros do Sistema de Monitoramento de Convenios (Decreto RS
    # 56.939/2023). Tabela e nao coluna: a obrigacao e por convenio POR MES, e o
    # alarme e "2 meses consecutivos sem registro" — um timestamp responde
    # "quando", nunca "QUAIS meses faltam". A regra mora em
    # services/monitoramento_rs.py, com teste proprio.
    "add_monitoramento_convenios.sql",
    # Consulta Popular / COREDEs (RS) — o mecanismo de participacao que nao
    # existe em MG. Uma linha por DEMANDA do COREDE, com o desempenho do
    # municipio ao lado (votos e se classificou).
    "add_consulta_popular_rs.sql",
    # ⭐ BOOTSTRAP LIMPO: as 12 colunas de convenios_estadual que só existiam
    # por herança do Neon (`fonte` + os campos do RM). O setup_db não as cria e
    # o create_all não acrescenta coluna a tabela existente — então em banco
    # NOVO elas simplesmente não existiam, e as duas migrations logo abaixo
    # falhavam com `column "fonte" does not exist` (medido no 1º boot do
    # santamaria-rs, o primeiro banco criado do zero no projeto).
    # ⚠️ Tem de ficar ACIMA das duas: elas são as primeiras a usar `fonte`.
    "add_convenios_estadual_colunas_faltantes.sql",
    # ⭐ DUPLICATAS: a chave de identidade estava errada em emendas_estaduais
    # (o ANO DO FILTRO entrou na chave) e em convenios_estadual (a chave mudava
    # quando o nº SIAFI nascia). Deduplica o que existe e instala a chave certa,
    # nos 3 tenants. Idempotente: onde já está limpo, não faz nada.
    "fix_duplicatas_chave_natural.sql",
    # Historico dos alertas do watchdog: o aviso precisa de um lugar para ir.
    # Com o Telegram desligado e o WhatsApp ainda por fazer, a tela de Status
    # dos Dados vira o canal — e ele nao depende de credencial nenhuma.
    "add_watchdog_historico.sql",
    # valor_total do SIGCON-MG defasado em 258 linhas: o backfill do CKAN grava
    # o total com a parte do concedente e o scraper preenche a contrapartida
    # depois sem recomputar — a tela somava 7.000.000 + 728.020,41 = 7.000.000.
    # Idempotente por construcao (ver o cabecalho do .sql). ⚠️ REGISTRADA AQUI
    # porque o runner so executa o que esta NESTA lista.
    "fix_sigcon_total_com_contrapartida.sql",
    # TELEMETRIA DE USO — tabelas proprias, separadas da trilha. Nao pode ficar
    # abaixo de add_auditoria_imutavel.sql (que precisa ser a ultima), e o runner
    # so executa o que esta NESTA lista: migration fora dela e orfa.
    "add_uso.sql",
    # ⭐ DATAS DO TRANSFEREGOV: o setup_db as declarava DATE, mas em produção
    # (os 3 bancos vindos do Neon) sempre foram TEXTO — e o coletor manda
    # "dd/mm/aaaa" cru. No 1º banco criado do zero isso corrompeu dado EM
    # SILÊNCIO (o DateStyle do servidor é MDY: 12/08/2026 virou 8 de dezembro)
    # e abortou a coleta do município quando o dia passava de 12. Alinha o
    # banco novo aos antigos e reconstrói as datas a partir do raw_data.
    # No-op nos 3 tenants antigos. Ver o cabeçalho do .sql.
    "fix_transferegov_datas_texto.sql",
    # ⭐ TE FORA DA CARTEIRA: o coletor de Transferencias Especiais tinha default
    # `TE_UF=MG` e nenhum tenant define a variavel, entao todos baixavam Minas.
    # No Trust (ES/GO/MG/TO) e no Santa Maria (RS) isso virou milhares de linhas
    # com municipio_id nulo — invisiveis ao produto, mas ocupando disco — enquanto
    # os municipios de verdade ficavam sem TE. Limpa a sobra; o coletor corrigido
    # passa a seguir a carteira. No-op no Freitas e no Monte Siao (sao de MG).
    "limpa_transferegov_te_fora_da_carteira.sql",
    # A tela InvestSUS (#243) para quem ja tem a tela fns — sem este backfill,
    # so o super-admin via o item do menu SAUDE (tela nova nao nasce concedida
    # a ninguem, e o proprio catalogo backend a omitia). Mesmo desenho do
    # add_bi_tela.sql; NOT EXISTS respeita revogacao futura.
    "add_tela_investsus.sql",
    # Mesma logica do investsus: tela nova nao nasce concedida, e o item do
    # menu e filtrado por `user_telas`. Quem tem `sismob` ganha `obrasgov`.
    "add_tela_obrasgov.sql",
    # Configuracoes do tenant (chave -> valor) editaveis pela tela. Primeira e
    # unica chave: `rm.rodape`, o rodape padrao do Relatorio de Monitoramento,
    # que ate aqui so existia em RM_RODAPE e exigia deploy para mudar.
    # ⚠️ SEM SEMENTE: linha ausente = usa a env (ver services/rm_config.py).
    "add_configuracoes.sql",
    # Pagamentos da Transferencia Especial: documentos habeis -> OP/OB e o
    # historico de eventos de pagamento, no mesmo formato do `ops_obs` das
    # voluntarias. Puramente ADITIVA (duas colunas + um indice parcial) sobre
    # transferegov_te; o runner so executa o que esta NESTA lista.
    "add_te_pagamentos.sql",
    # TELEMETRIA: sessao de uso vira TRECHO contiguo (sessao_token + motivo_fim
    # mais largo). Precisa de add_uso.sql acima, e nao toca audit_log.
    "add_uso_trechos.sql",
    # FNS: o valor PAGO ocupava a coluna do valor PROPOSTO nas linhas de
    # pagamento parcial (`vl_pago or vl_prop` — o `or` do Python devolve o pago
    # sempre que ele nao e zero). Repara o ja gravado lendo do proprio raw_data;
    # idempotente e autocurativa, roda a cada boot.
    "fix_fns_valor_pago_na_coluna_certa.sql",
    # SIGCON: apaga a data de publicacao SUBSTITUTA (1o de janeiro do ano) que o
    # coletor gravava na mesma coluna da data real e o modal imprimia como
    # "Data Publicação". Depende do coletor ja corrigido; a data de verdade volta
    # pelo backfill do CKAN. Idempotente.
    "limpa_dt_publicacao_substituta.sql",
    # Voluntarias: tira do JSONB `detalhe` o trio de valores que nao fecha a
    # conta. A trava do #322 protegia so as COLUNAS; o blob seguia gravado com o
    # dinheiro deslocado (83 de 83 em Araujos, 61 regravadas no mesmo dia).
    # APAGA, nao corrige — o detalhe e o que a pagina disse. Idempotente.
    "limpa_detalhe_valores_deslocados.sql",
    # SIGCON: apaga o AVISO do portal ("STATUS DE PRESTAÇÃO DE CONTAS NÃO
    # INFORMADO") gravado como se fosse o status. Irmao do
    # `limpa_prestacao_contas_sei_lixo.sql`: o portal dizendo "nao ha" e
    # ausencia, nao dado. Idempotente.
    "limpa_prestacao_contas_nao_informado.sql",
    # Voluntarias: catorze colunas que o dado aberto JA TRAZ e que o coletor
    # nunca leu (banco/agencia/conta, saldo, empenhado, prazo de prestacao de
    # contas, qtd de aditivos, vigencia original...). Primeira etapa da migracao
    # para o ambiente `api-publica`, e a de menor risco: nenhum endereco novo,
    # so colunas de arquivos que ja sao baixados todo dia.
    "add_voluntarias_colunas_do_csv.sql",
    # SICONFI/Tesouro: o extrato de entregas de contas (o que faltou, e nao so
    # "irregular") e a CAPAG (a nota de A+ a D que abre ou fecha credito com
    # garantia da Uniao). Fonte NACIONAL — nao tem recorte de UF. Depende so de
    # `municipios`, entao pode entrar no fim da lista.
    "add_siconfi.sql",
    # TCE-RS/LicitaCon: licitacoes e contratos do municipio, mais a tabela
    # `fonte_http_cache` — que e infraestrutura, nao do TCE: e a primeira peca
    # de HTTP CONDICIONAL do repo (a auditoria de 29/08 mediu zero ETag em 44
    # coletores). Depende so de `municipios`.
    "add_tce_rs.sql",
    # TCE-RS pelo PORTAL: o mesmo Tribunal por um host que responde
    # (portal.tce.rs.gov.br, API aberta) — remessa, obra, medicao e a ORIGEM DO
    # RECURSO, que liga a obra ao convenio que a pagou. ⚠️ DEPOIS de
    # `add_tce_rs.sql`: acrescenta colunas a `tce_rs_licitacoes` e
    # `tce_rs_contratos`, que nascem la. Inverter a ordem quebra banco NOVO —
    # a mesma armadilha que `tests/test_migrations_ordem_tabela.py` guarda.
    "add_tce_rs_portal.sql",
    # Obras.gov.br/CIPI: as obras federais que nao sao de saude (SISMOB) nem
    # de educacao (SIMEC). Depende so de `municipios`.
    "add_obrasgov.sql",
    # ⚠️ DEPOIS de `add_obrasgov.sql`: acrescenta `sistema_origem` a uma
    # tabela que nasce la. Inverter a ordem quebra banco NOVO.
    "add_obrasgov_sistema_origem.sql",
    # ⚠️ DEPOIS das duas acima: alarga taxonomias que nascem la. Santa Maria
    # abortou inteira por UM caractere ("Projeto de Investimento em
    # Infraestrutura" = 41, coluna = 40).
    "add_obrasgov_taxonomias_text.sql",
    # Migration nova que precise reescrever audit_log entra ACIMA desta linha,
    # nunca abaixo.
    "add_auditoria_imutavel.sql",
]


def run_migrations_full():
    """Inclui migrations longas - usar so manual via SSH ou cron."""
    import os, logging
    from pathlib import Path
    extras = ["dedupe_convenios_unique.sql"]
    sync_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not sync_url: return
    import psycopg2
    base = Path(__file__).parent.parent / "migrations"
    for f in extras:
        path = base / f
        if not path.exists(): continue
        try:
            with psycopg2.connect(sync_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            print(f"[STARTUP_FULL] {f}: OK", flush=True)
        except Exception as e:
            print(f"[STARTUP_FULL] {f}: {e}", flush=True)


def _log(msg: str):
    """Log + print (garante visibilidade nos logs Railway)."""
    print(f"[STARTUP] {msg}", flush=True)
    logger.warning(msg)


# Teto de espera pelo outro worker. Generoso porque a espera real e o tempo das
# migrations do OUTRO worker (segundos), e curto o bastante para nunca pendurar o
# boot: estourou, este worker roda sem o lock — que e exatamente o que ja
# acontecia antes, entao o pior caso e o comportamento antigo.
LOCK_ESPERA_S = 120.0
LOCK_INTERVALO_S = 0.5


def _tomar_lock_migrations(sync_url: str):
    """Pega o advisory lock do boot e DEVOLVE A CONEXAO que o segura.

    Devolve a conexao (quem chamou fecha no fim) ou None — e `None` significa
    "siga sem lock", nunca "pule as migrations". Ver o porque no fim.

    ⚠️ 1. POR QUE DEVOLVER A CONEXAO, E NAO SO UM BOOLEANO. Advisory lock pego com
    `pg_try_advisory_lock` e de SESSAO: vive enquanto a CONEXAO viver e morre com
    ela. A versao anterior tomava o lock dentro de um
    `with psycopg2.connect(...) as conn:` e seguia em frente — mas em psycopg2 o
    `with` de conexao fecha a TRANSACAO, nao a conexao; quem fechava era o coletor
    de lixo, no instante em que a variavel `conn` era reatribuida pelo proximo
    `with psycopg2.connect(...)`, poucas linhas abaixo e ANTES da primeira
    migration. A garantia de "so 1 worker" era ficcao: os dois processos do
    `--workers 2` (Dockerfile.api/Procfile) rodavam a lista inteira em paralelo.
    Ninguem notou porque quase tudo e `IF NOT EXISTS` e o runner engole erro.

    Deixou de ser inofensivo quando entrou comando sem forma idempotente barata
    (`ALTER TABLE ... DROP CONSTRAINT`, em add_auditoria_imutavel.sql): dois
    workers no mesmo arquivo fazem o perdedor da corrida abortar a TRANSACAO
    INTEIRA da migration e registrar "Migration ... falhou" num boot que deu
    certo. O banco fica correto (o vencedor commitou), mas o log passa a acusar
    falha em boot saudavel — e log de migration que grita erro no dia a dia e log
    que ninguem le mais.

    ⚠️ 2. POR QUE ESPERAR EM VEZ DE PULAR. O codigo antigo dizia "outro worker
    rodando - pulando", e pular parece mais rapido. Mas quem pula VOLTA A SERVIR
    ANTES DE O SCHEMA ESTAR PRONTO: no primeiro boot de um tenant novo, o worker 2
    comecaria a responder requisicao contra um banco em que a coluna que ele vai
    consultar ainda nao existe. Esperar o outro terminar e depois rodar a lista de
    novo custa alguns segundos (tudo idempotente, o segundo passe nao faz
    trabalho) e paga por: nenhum worker serve com schema pela metade, e as
    migrations nunca correm em paralelo — some a classe inteira de corrida.

    Espera por SONDAGEM (`pg_try_advisory_lock` em intervalos) e nao com
    `pg_advisory_lock` bloqueante de proposito: sondando, o teto de espera e
    codigo nosso, visivel e testavel, em vez de depender de `lock_timeout` valer
    para lock de advisory nesta versao do servidor.

    `autocommit` porque so precisamos da sessao viva: sem isto a conexao ficaria
    `idle in transaction` durante toda a migration, segurando snapshot a toa."""
    import psycopg2
    conn = None
    try:
        conn = psycopg2.connect(sync_url)
        conn.autocommit = True
        limite = time.monotonic() + LOCK_ESPERA_S
        avisou = False
        while True:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(987654321)")
                if cur.fetchone()[0]:
                    return conn
            if time.monotonic() >= limite:
                _log(f"Outro worker segura o lock ha mais de {LOCK_ESPERA_S:.0f}s "
                     "- rodando as migrations sem ele")
                conn.close()
                return None
            if not avisou:
                _log("Outro worker esta rodando as migrations - esperando ele terminar")
                avisou = True
            time.sleep(LOCK_INTERVALO_S)
    except Exception as e:
        # Falhar em PEGAR o lock nao pode virar "nao rodar as migrations": o boot
        # sem schema e pior que o boot com dois workers concorrendo.
        _log(f"Falha ao adquirir lock - tentando sem: {e}")
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return None


def run_migrations():
    """Roda todas as migrations SQL na ordem. Idempotente.

    Serializa os workers por advisory lock (uvicorn --workers 2 inicializaria 2
    boots paralelos, criando corrida em DDL). O lock e SEGURADO ate a ultima
    migration — ver `_tomar_lock_migrations` para o porque de isso ser explicito."""
    sync_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    if not sync_url:
        _log("DATABASE_URL_SYNC nao configurada - pulando migrations")
        return

    try:
        import psycopg2
    except ImportError:
        _log("psycopg2 nao instalado - pulando migrations")
        return

    lock_conn = _tomar_lock_migrations(sync_url)
    try:
        _rodar_migrations(sync_url)
    finally:
        # Solta o lock so DEPOIS da ultima migration (e do bootstrap do token).
        if lock_conn is not None:
            try:
                lock_conn.close()
            except Exception:
                pass


def _rodar_migrations(sync_url: str):
    """O trabalho em si, ja com o lock do boot na mao."""
    import psycopg2

    # Schema base (tabelas + seed) antes das migrations incrementais. No Coolify
    # nao existe o passo manual "rodar setup_db.py uma vez"; e idempotente
    # (CREATE TABLE IF NOT EXISTS + INSERT ON CONFLICT DO NOTHING). O seed so roda
    # quando a tabela users esta vazia (evita re-hash/print de senha a cada boot).
    try:
        import setup_db
        setup_db.create_tables()
        # Tabelas modeladas ausentes do setup_db e sem migration CREATE (ex.:
        # cofre_senhas, audit_log): cria a partir dos models SQLAlchemy.
        # checkfirst=True nao toca tabelas ja existentes.
        try:
            import models  # noqa: F401 - registra todos os models em Base.metadata
            from database import Base
            from sqlalchemy import create_engine as _ce
            _eng = _ce(sync_url)
            Base.metadata.create_all(_eng, checkfirst=True)
            _eng.dispose()
            _log("create_all (tabelas modeladas) OK")
        except Exception as e:
            _log(f"create_all falhou: {str(e)[:150]}")
        with psycopg2.connect(sync_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                n_users = cur.fetchone()[0]
            conn.commit()
        if n_users == 0:
            setup_db.seed_data()
            _log("Seed inicial aplicado (users estava vazio)")
        _log("Schema base (setup_db) OK")
    except Exception as e:
        _log(f"setup_db falhou (seguindo assim mesmo): {str(e)[:200]}")

    base = Path(__file__).parent.parent / "migrations"
    if not base.exists():
        _log(f"Pasta migrations nao encontrada: {base}")
        return

    rodadas = 0
    for fname in MIGRATION_FILES:
        path = base / fname
        if not path.exists():
            _log(f"  Migration ausente: {fname}")
            continue
        try:
            with psycopg2.connect(sync_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            rodadas += 1
            _log(f"  Migration OK: {fname}")
        except Exception as e:
            # Erros tipicos: tabela ja existe, coluna ja adicionada - sao seguros
            msg = str(e)[:200]
            if any(k in msg.lower() for k in ["already exists", "duplicate", "ja existe"]):
                _log(f"  Migration {fname}: ja aplicada (skip)")
            else:
                _log(f"  Migration {fname} falhou: {msg}")

    _log(f"Startup migrations: {rodadas}/{len(MIGRATION_FILES)} executadas")
    _log_estado_da_trava()

    # Bootstrap do control token (Console Alavank), apos as migrations (kind ja existe).
    _bootstrap_control_token(sync_url)


def _log_estado_da_trava() -> None:
    """⭐ O BOOT DIZ EM QUE MODO A TRAVA ESTA. Uma linha, e ela paga a si mesma.

    `AUTHZ_MODO` e `AUTHZ_REGISTRO` mudam o que o sistema RECUSA, e nao deixavam
    rastro nenhum: para saber se a trava estava ligada era preciso abrir o painel
    do Coolify e ler a variavel — ou seja, a resposta vinha de onde alguem
    DECLAROU o estado, e nao de onde ele vale. As duas coisas divergem no dia em
    que a env e criada e o container nao reinicia.

    E as duas sao FAIL-OPEN por escolha (`AUTHZ_MODO=bloqueiop`, com o dedo
    escorregando no teclado, segue em `aviso`): o valor invalido nao liga a trava
    e tambem nao quebra o boot. Sem esta linha, esse erro de digitacao e
    invisivel — o sistema parece protegido e nao esta, que e a pior das duas
    formas de estar errado.

    Nao levanta: log de diagnostico nao pode ser o que derruba a API."""
    try:
        from services import authz, registro_rotas
        _log(f"Trava de permissao: AUTHZ_MODO={authz.modo()} "
             f"| AUTHZ_REGISTRO={registro_rotas.modo()}")
    except Exception as e:  # pragma: no cover - diagnostico nunca derruba o boot
        _log(f"Trava de permissao: nao foi possivel ler o modo ({str(e)[:80]})")


def _bootstrap_control_token(sync_url: str):
    """Se CONTROL_TOKEN_BOOTSTRAP estiver no env e ainda nao houver control token,
    cria um ServiceToken(kind='control', scopes=['control:*']) com o hash do raw.
    Idempotente: nao recria se ja existe um control token. O raw fica so no Console."""
    raw = os.getenv("CONTROL_TOKEN_BOOTSTRAP", "").strip()
    if not raw or len(raw) < 32:
        return
    import json
    import hashlib
    try:
        import psycopg2
    except ImportError:
        return
    th = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    prefix = raw[:12]
    try:
        with psycopg2.connect(sync_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM service_tokens WHERE kind = 'control'")
                if cur.fetchone()[0] == 0:
                    cur.execute(
                        "INSERT INTO service_tokens "
                        "(name, kind, token_hash, token_prefix, scopes, description, active) "
                        "VALUES ('console-alavank', 'control', %s, %s, %s::jsonb, "
                        "'Control-plane token (Console Alavank)', true) "
                        "ON CONFLICT (name) DO NOTHING",
                        (th, prefix, json.dumps(["control:*"])),
                    )
            conn.commit()
        _log("Control token bootstrap: OK (criado ou ja existia)")
    except Exception as e:
        _log(f"Control token bootstrap falhou: {str(e)[:150]}")
