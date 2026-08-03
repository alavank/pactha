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
