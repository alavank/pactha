"""
Catálogo canônico de telas/módulos do tenant, exposto ao Console pelo canal control
(o Console monta a lista de módulos ao criar/editar um usuário do cliente).

Espelha frontend/src/lib/telas.ts, EXCLUINDO cofre/sessoes — que são operacionais da
Alavank (gestão de credenciais gov, §12) e não devem ser concedidos a usuário de cliente.
"""
TELAS_CATALOG = [
    {"key": "dashboard", "label": "Dashboard"},
    {"key": "ai", "label": "IA PACTHA"},
    {"key": "telegram", "label": "Telegram"},
    {"key": "parlamentares", "label": "Parlamentares"},
    {"key": "gestao", "label": "Gestão Interna"},
    {"key": "rm", "label": "Relatório de Monitoramento"},
    {"key": "documentos", "label": "Geração de Documentos"},
    {"key": "convenios", "label": "SIGCON (Estaduais)"},
    {"key": "emendas", "label": "Emendas Estaduais"},
    {"key": "transferegov", "label": "Transfere Gov"},
    {"key": "cauc", "label": "CAUC (regularidade federal)"},
    {"key": "sismob", "label": "Obras da Saúde (SISMOB)"},
    {"key": "acordofes", "label": "Acordo FES (dívida saúde MG)"},
    {"key": "fns", "label": "Fundo Nacional de Saúde"},
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

# TODAS as telas que existem no produto — a UNIAO do catálogo acima com as seis
# que ele omite de propósito: `cofre`/`sessoes` (operacionais da Alavank, §12) e
# `suas`/`paineis`/`bi_tela`/`bi_link` (nasceram depois deste arquivo).
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
    "dashboard", "ai", "telegram", "parlamentares", "gestao", "rm",
    "documentos", "convenios", "emendas", "transferegov", "cauc", "sismob",
    "acordofes", "fns", "simec", "suas", "paineis", "bi", "bi_tela",
    "bi_link", "dou", "cofre", "sessoes", "auditoria",
]
