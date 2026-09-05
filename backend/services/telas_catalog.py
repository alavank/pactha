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
    {"key": "transferegov", "label": "Transfere Gov"},
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
    "dashboard", "ai", "parlamentares", "gestao", "agendamentos", "rm",
    "documentos", "convenios", "emendas", "transferegov", "cauc", "sismob",
    "obrasgov",
    # `suas` SAIU: o painel do MDS vive dentro de `paineis` (ver telas.ts).
    "acordofes", "fns", "investsus", "simec", "paineis", "bi", "bi_tela",
    "bi_link", "dou", "cofre", "sessoes", "auditoria",
]
