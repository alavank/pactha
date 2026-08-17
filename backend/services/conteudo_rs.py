"""Conteúdo curado do Rio Grande do Sul — o que a coleta ainda não alcança.

⭐ POR QUE ESTE MÓDULO EXISTE. Pela regra do roadmap gaúcho (`docs/MAPA_RS.md`
§13), nenhuma fonte de convênio, emenda ou transferência para prefeitura do RS
fica de fora do PACTHA — e onde a coleta não é possível hoje, entrega-se **o que
dá**: o que a coisa é, o que exige, quando abre, onde confirmar.

Os três assuntos aqui têm o mesmo motivo e obstáculos diferentes:

    FUNRIGS / Plano Rio Grande   o portal publica só normativos e um formulário
                                 em branco; o painel de execução é Power BI
    Emendas estaduais            Power BI "publish to web", sem CSV e com token
                                 de embed dinâmico
    TCE-RS                       o CKAN é aberto, mas devolve 403 para o IP do
                                 nosso servidor (bloqueio de datacenter)

⚠️ TODA TELA QUE CONSOME ISTO É OBRIGADA A MOSTRAR `AVISO_*`. Conteúdo curado
apresentado sem ressalva se passa por monitoramento — e o gestor confiaria que
seria avisado de um prazo que ninguém está vigiando.

⚠️ NÚMEROS SÃO DATADOS. Cada valor carrega a data em que foi lido na fonte. Sem
isso ele envelhece em silêncio e um dia vira erro na tela do prefeito. Ao
atualizar um número, atualize a data junto.

⚠️ Mora em `services/` (e não em `routers/`) porque a imagem do worker não copia
`/app/routers` — ver o cabeçalho de `services/cauc_catalogo.py`.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Plano Rio Grande / FUNRIGS
# ---------------------------------------------------------------------------

FUNRIGS = {
    "titulo": "Plano Rio Grande / FUNRIGS",
    "subtitulo": "Reconstrução pós-enchentes de maio de 2024 — hoje a maior fonte "
                 "de demanda de captação e prestação de contas das prefeituras gaúchas",
    "resumo": (
        "Coordenado pela Secretaria da Reconstrução Gaúcha (SERG), criada em maio "
        "de 2024, e financiado pelo FUNRIGS — Fundo do Plano Rio Grande, com "
        "recursos da suspensão da dívida do Estado com a União por 36 meses."
    ),
    # ⭐ A parte acionável: o gestor lê e sabe se está apto HOJE.
    "exigencias": [
        {"item": "Situação de calamidade decretada",
         "detalhe": "o município precisa ter o decreto de calamidade reconhecido; "
                    "é a porta de entrada do fundo a fundo"},
        {"item": "Fundo Municipal de Reconstrução criado",
         "detalhe": "com conselho gestor constituído e conta bancária específica — "
                    "não basta a lei de criação"},
        {"item": "Nexo causal com o evento de maio/2024",
         "detalhe": "cada ação precisa ser demonstrada como decorrente da "
                    "enchente (Resolução nº 09/FUNRIGS)"},
    ],
    # A exceção que o PACTHA JÁ respeita — e é o único ponto deste conteúdo que
    # tem efeito no comportamento do sistema, não só na tela.
    "excecao_120_dias": (
        "Município em calamidade tem prazo excepcional de 120 dias para atualizar "
        "o Sistema de Monitoramento de Convênios, em vez do dia 15 de cada mês "
        "(Nota Técnica SPGG). O PACTHA já aplica essa exceção no alarme do Decreto "
        "56.939/2023 quando a data-limite da calamidade está cadastrada no "
        "município — sem ela, o sistema cobra pelo prazo padrão."
    ),
    "numeros": "R$ 13,7 bilhões aprovados pelo FUNRIGS para 186 ações de "
               "reconstrução, dentro de R$ 14,5 bilhões, com R$ 6,4 bilhões "
               "empenhados e R$ 3,2 bilhões liquidados (dados divulgados pela "
               "SERG em novembro de 2025)",
    "links": [
        ("Plano Rio Grande — Municípios", "https://planoriogrande.rs.gov.br/municipios"),
        ("Fundo a Fundo da Reconstrução", "https://planoriogrande.rs.gov.br/fundo-a-fundo-reconstrucao"),
        ("Secretaria da Reconstrução Gaúcha", "https://www.reconstrucao.rs.gov.br/"),
    ],
}

AVISO_FUNRIGS = (
    "O Plano Rio Grande publica normativos e formulários, mas não uma base por "
    "município — e o painel de execução do Estado é um relatório fechado. Este "
    "conteúdo é mantido pela equipe do PACTHA: confirme editais, prazos e "
    "condições nos canais oficiais antes de decidir."
)

# ---------------------------------------------------------------------------
# Emendas parlamentares estaduais
# ---------------------------------------------------------------------------

EMENDAS = {
    "titulo": "Emendas Parlamentares Estaduais (RS)",
    # ⭐⭐ A PRIMEIRA COISA QUE A TELA DIZ, e não é detalhe jurídico: é o que
    # impede o cliente de tomar uma decisão errada. Em Minas o PACTHA vende
    # "controle do prazo constitucional da emenda impositiva". No RS esse prazo
    # NÃO EXISTE — e repetir o discurso mineiro aqui seria erro material.
    "alerta_impositividade": (
        "No Rio Grande do Sul as emendas parlamentares estaduais NÃO são "
        "impositivas. A Constituição Estadual não institui orçamento impositivo "
        "para deputados estaduais: as emendas são autorizativas, pactuadas e "
        "definidas ano a ano na LDO. Não há prazo constitucional de empenho ou "
        "pagamento a cobrar do Estado — diferente do que vale em Minas Gerais e "
        "das emendas FEDERAIS."
    ),
    "resumo": (
        "As emendas dos 55 deputados estaduais são disciplinadas ano a ano pela "
        "LDO e por decreto. O Decreto Estadual nº 58.394/2025 instituiu o Sistema "
        "Estadual de Gestão de Emendas Parlamentares, para controle e "
        "transparência das emendas federais e estaduais."
    ),
    "numeros": [
        ("PLOA 2026 — total de emendas", "R$ 220 milhões"),
        ("PLOA 2026 — por deputado", "R$ 4 milhões"),
        ("Acumulado 2020–2025", "≈ 3.900 emendas · ≈ R$ 423 milhões · "
                                "R$ 212 milhões em saúde · 474 municípios beneficiados"),
    ],
    "numeros_data": "valores conforme Casa Civil e SPGG, lidos em 16/08/2026",
    # A confusão que aparece na imprensa e chega ao gestor.
    "atencao": (
        "As chamadas \"emendas Pix\" associadas ao RS na imprensa são FEDERAIS "
        "(transferências especiais do art. 166-A da Constituição, de deputados "
        "federais e senadores gaúchos). Não há base legal estadual para "
        "transferência especial no RS — essas aparecem no módulo TransfereGov, "
        "não aqui."
    ),
    "o_que_fazer": [
        "Acompanhar a janela de emendas ao PLOA (calendário anual da SPGG) e "
        "articular com o deputado ANTES do fechamento — sem impositividade, a "
        "relação é o que garante a execução.",
        "Rastrear a execução no Portal da Transparência do Estado.",
        "Manter separadas, na conversa com o gabinete, a emenda estadual "
        "(autorizativa) e a federal (impositiva).",
    ],
    "links": [
        ("Portal da Transparência — emendas estaduais (painel oficial)",
         "https://www.transparencia.rs.gov.br/emendas-parlamentares/emendas-parlamentares-estaduais/dados/"),
        ("SPGG — orientações e cartilhas",
         "https://planejamento.rs.gov.br/emendas-parlamentares-estaduais"),
    ],
}

AVISO_EMENDAS = (
    "O Estado publica as emendas em painel fechado (Power BI), sem base aberta "
    "para download — então a execução das emendas do seu município ainda NÃO é "
    "coletada automaticamente pelo PACTHA. Consulte o painel oficial no link "
    "abaixo; este conteúdo explica as regras e o calendário."
)

# ---------------------------------------------------------------------------
# TCE-RS — as remessas que refletem na habilitação
# ---------------------------------------------------------------------------

TCE = {
    "titulo": "TCE-RS — remessas obrigatórias",
    "subtitulo": "O atraso na remessa vira pendência, e pendência trava habilitação e repasse",
    "sistemas": [
        {"nome": "SIAPC / PAD",
         "o_que": "Sistema de Informações para Auditoria e Prestação de Contas. "
                  "Remessa dos dados contábeis (empenhos, folha), integrando RREO "
                  "e RGF.",
         "periodicidade": "MENSAL",
         "prazo": "cerca de 60 dias após o fim do período — os prazos do exercício "
                  "saem no calendário do TCE (ex.: dados de março até 02/05; "
                  "dados de maio até 30/06)"},
        {"nome": "LicitaCon",
         "o_que": "Licitações e contratos, enviados pelo e-Validador ou pelo "
                  "LicitaCon Web.",
         "periodicidade": "SEMANAL (envio) · MENSAL (RVE)",
         "prazo": "envio mínimo semanal; o recibo de validação de envio (RVE) é "
                  "mensal"},
        {"nome": "Meu TCE",
         "o_que": "Cadastro de acesso do gestor aos sistemas do Tribunal.",
         "periodicidade": "cadastro único",
         "prazo": "obrigatório estar ativo para operar os demais sistemas"},
    ],
    "por_que_importa": (
        "O descumprimento de prazo de remessa gera pendência no Tribunal, que se "
        "reflete em irregularidade fiscal e pode travar a habilitação para "
        "convênio (o CHE inclui certidões do TCE entre suas exigências) e o "
        "próprio repasse."
    ),
    "codigo_orgao": (
        "Cada órgão tem um código no TCE-RS, e ele é a chave de todas as consultas "
        "de dado aberto. ⚠️ A Câmara Municipal tem código PRÓPRIO e distinto do "
        "da Prefeitura — conferir antes de usar."
    ),
    "links": [
        ("Sistemas de controle externo do TCE-RS", "https://tcers.tc.br/sistemas-de-controle-externo/"),
        ("Dados abertos do TCE-RS", "https://dados.tce.rs.gov.br/dataset"),
        ("LicitaCon Cidadão", "https://portal.tce.rs.gov.br/aplicprod/f?p=50500"),
    ],
}

AVISO_TCE = (
    "O TCE-RS publica dados abertos, mas hoje recusa conexões vindas do servidor "
    "do PACTHA (bloqueio por faixa de datacenter) — então a conferência de que a "
    "SUA remessa foi enviada ainda NÃO é automática. Este conteúdo traz os "
    "sistemas, a periodicidade e onde confirmar; a integração entra assim que o "
    "acesso for liberado."
)
