"""
Catálogo canônico de telas/módulos do tenant, exposto ao Console pelo canal control
(o Console monta a lista de módulos ao criar/editar um usuário do cliente).

Espelha frontend/src/lib/telas.ts, EXCLUINDO cofre/sessoes — que são operacionais da
Alavank (gestão de credenciais gov, §12) e não devem ser concedidos a usuário de cliente.
"""
TELAS_CATALOG = [
    {"key": "dashboard", "label": "Dashboard"},
    {"key": "ai", "label": "IA PACTHA"},
    {"key": "parlamentares", "label": "Parlamentares"},
    {"key": "gestao", "label": "Gestão Interna"},
    {"key": "agendamentos", "label": "Agendamentos"},
    {"key": "rm", "label": "Relatório de Monitoramento"},
    {"key": "documentos", "label": "Geração de Documentos"},
    {"key": "convenios", "label": "Convênios Estaduais"},
    {"key": "emendas", "label": "Emendas Estaduais"},
    # ⭐ «Transfere Gov» virou OITO telas em 05/09/2026 (uma por folha do menu),
    # e o Console passa a oferecer as oito: era uma caixinha que concedia sete
    # telas de uma vez, e o administrador nao tinha como saber disso.
    {"key": "transferegov_radar", "label": "Radar de captação"},
    {"key": "transferegov_geral", "label": "Federais — Em execução"},
    {"key": "transferegov_especiais", "label": "Federais — Especiais"},
    {"key": "transferegov_pac", "label": "Federais — PAC (Novo PAC)"},
    {"key": "transferegov_voluntarias", "label": "Federais — Voluntárias"},
    {"key": "transferegov_rejeitadas", "label": "Federais — Rejeitadas"},
    {"key": "transferegov_encerradas", "label": "Federais — Encerradas"},
    {"key": "transferegov_cnpj", "label": "Federais — CNPJ"},
    # ⭐ EMENDAS FEDERAIS (06/09/2026) — a nona folha do grupo FEDERAIS.
    # ⚠️ MESMO TEXTO de `frontend/src/lib/telas.ts`, como as vizinhas.
    {"key": "emendas_federais", "label": "Federais — Emendas parlamentares"},
    # As oito do grupo ESTADUAIS que estavam dentro de `convenios`. ⚠️ MESMO
    # TEXTO de `frontend/src/lib/telas.ts` — dois nomes para a mesma chave fazem
    # o administrador achar que sao duas permissoes diferentes.
    {"key": "repasses", "label": "Repasses Estaduais"},
    {"key": "cofinanciamento", "label": "Cofinanciamento da Saúde"},
    {"key": "monitoramento", "label": "Monitoramento de Convênios"},
    {"key": "consulta_popular", "label": "Consulta Popular"},
    {"key": "programas_rs", "label": "Programas do Estado"},
    {"key": "funrigs", "label": "Plano Rio Grande"},
    {"key": "emendas_rs", "label": "Emendas Estaduais RS"},
    {"key": "tce_rs", "label": "TCE-RS"},
    # TCE-PR (22/09/2026). MESMO TEXTO de `frontend/src/lib/telas.ts`.
    {"key": "tce_pr", "label": "TCE-PR"},
    # A Telemetria ganhou tela propria: ate 05/09/2026 a aba usava a chave
    # `auditoria`, entao conceder a trilha concedia junto o horario de trabalho
    # de todo mundo. Entra no catalogo do cliente pela mesma razao da Auditoria.
    {"key": "telemetria", "label": "Telemetria (uso do sistema)"},
    # ⚠️ MESMO TEXTO de `frontend/src/lib/telas.ts`: a Central monta o
    # formulario de permissoes pelo catalogo daqui e o cliente pelo de la —
    # dois nomes para a mesma chave fazem o administrador achar que sao duas
    # permissoes diferentes. (Ja estavam divergentes: este dizia so "CAUC".)
    # E o rotulo e NEUTRO porque "CAGEC" e o nome do cadastro de MINAS, e a
    # mesma tela serve clientes de qualquer estado.
    {"key": "cauc", "label": "Regularidade (federal e estadual)"},
    {"key": "sismob", "label": "Obras da Saúde (SISMOB)"},
    # A 2a tela da pasta OBRAS do menu (04/09/2026). MESMO TEXTO de
    # `frontend/src/lib/telas.ts`: dois nomes para a mesma chave fazem o
    # administrador achar que sao duas permissoes diferentes.
    {"key": "obrasgov", "label": "Obras Federais (Obras.gov.br)"},
    # MESMO TEXTO de `frontend/src/lib/telas.ts` — dois nomes para a mesma
    # chave fazem o administrador achar que sao duas permissoes diferentes.
    {"key": "parcerias", "label": "Parcerias (emendas de saúde)"},
    {"key": "faf_planos", "label": "Planos de Ação (Fundo a Fundo)"},
    {"key": "acordofes", "label": "Acordo FES (dívida saúde MG)"},
    {"key": "fns", "label": "Fundo Nacional de Saúde"},
    # A 4ª tela da pasta SAÚDE do menu (#243). Ficou fora deste catálogo no
    # próprio #243 — resultado: só o super-admin via o item, e o Console nem
    # conseguia conceder. Ver add_tela_investsus.sql para o backfill.
    {"key": "investsus", "label": "InvestSUS"},
    {"key": "simec", "label": "SIMEC - PAR (MEC)"},
    {"key": "dou", "label": "Diário Oficial"},
    {"key": "bi", "label": "Painel de Indicadores (BI)"},
    # Trilha de auditoria. ENTRA no catálogo do cliente (ao contrário de
    # cofre/sessoes): quem responde por LGPD/ISO na prefeitura é o controle
    # interno dela, e a trilha existe justamente para ele conferir o que a
    # equipe — e a própria Alavank — fez no sistema. Somente leitura.
    {"key": "auditoria", "label": "Auditoria (trilha de atividades)"},
]
CATALOG_KEYS = {t["key"] for t in TELAS_CATALOG}

# TODAS as telas que existem no produto — a UNIAO do catálogo acima com as cinco
# que ele omite de propósito: `cofre`/`sessoes` (operacionais da Alavank, §12) e
# `paineis`/`bi_tela`/`bi_link` (nasceram depois deste arquivo).
#
# Existe porque `role` DEIXOU DE CONCEDER (ver services/auth.py::load_user_scopes
# e migrations/add_role_vira_rotulo.sql): "acesso total" parou de ser um desvio
# no código e passou a ser DADO em `user_telas`. Quem precisa de tudo — hoje só
# o usuário de suporte da Alavank criado pelo canal de control — recebe esta
# lista escrita, uma linha por tela.
#
# NÃO é oferecida ao cliente: o Console monta o formulário dele com
# TELAS_CATALOG, e é isso que deve continuar acontecendo.
#
# ⚠️ Tela nova entra em TRÊS lugares, e divergir esconde acesso em silêncio:
# aqui, em `frontend/src/lib/telas.ts` (que desenha os chips) e no bloco
# `catalogo(tela)` de `migrations/add_role_vira_rotulo.sql` (que fez o backfill
# dos administradores). Os três tinham de bater no dia deste incremento.
TELAS_TODAS = [
    # `telegram` SAIU em 05/09/2026, pelo mesmo caminho de `suas`: modulo
    # removido do codigo, tela removida dos tres catalogos.
    "dashboard", "ai", "parlamentares", "consolidado", "gestao", "agendamentos", "rm",
    "documentos", "convenios", "emendas", "cauc", "sismob",
    "obrasgov", "parcerias", "faf_planos",
    # `suas` SAIU: o painel do MDS vive dentro de `paineis` (ver telas.ts).
    "acordofes", "fns", "investsus", "simec", "paineis", "bi", "bi_tela",
    "bi_link", "dou", "cofre", "sessoes", "auditoria",
    # ⭐⭐ AS DEZOITO DO INCREMENTO «PERMISSAO POR TELA» (05/09/2026).
    #
    # ⚠️ `transferegov` SAIU desta lista: ela deixou de ser TELA. A chave
    # continua existindo no catalogo de permissoes, mas so para a acao
    # «Atualizar dados» — a coleta, que nao e de tela nenhuma (o botao mora em
    # Configuracoes › Sessões). As oito telas do grupo FEDERAIS a substituem.
    "transferegov_radar", "transferegov_geral", "transferegov_especiais",
    "transferegov_pac", "transferegov_voluntarias", "transferegov_rejeitadas",
    "transferegov_encerradas", "transferegov_cnpj", "emendas_federais",
    # As oito que estavam escondidas dentro de `convenios` (que continua sendo
    # tela, a de Convenios Estaduais propriamente dita).
    "repasses", "cofinanciamento", "monitoramento", "consulta_popular",
    "programas_rs", "funrigs", "emendas_rs", "tce_rs",
    # TCE-PR (22/09/2026), a primeira tela do Paraná.
    "tce_pr",
    # As quatro abas de Configuracoes que eram governadas pelo PAPEL `admin` e
    # viraram telas de verdade. `telemetria` estava usando a chave `auditoria`,
    # que e de outra coisa — liberar a trilha liberava o horario de trabalho de
    # todo mundo junto.
    "telemetria", "frescor", "usuarios", "parametros",
]
