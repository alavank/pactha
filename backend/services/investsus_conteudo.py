"""InvestSUS — conteúdo curado enquanto a coleta não existe.

⭐ POR QUE ESTA TELA NASCE SEM COLETOR, e mesmo assim nasce.

O InvestSUS é onde o município enxerga o dinheiro federal de saúde que já caiu
(ou vai cair) na conta do Fundo Municipal — repasse fundo a fundo por bloco e
competência, e a situação das propostas de investimento. É a fonte que fecha a
pasta da Saúde ao lado do FNS (propostas), do SISMOB (obras) e do Acordo FES.

E ele é FECHADO. Medido em 17/08/2026 contra o servidor de produção:

    GET https://investsus-backend-prd.saude.gov.br/api/geral/repasses/valores
        ?ano=2026&cnpj=<14 digitos>          -> HTTP 200 com o HTML do login

⚠️ O 200 É A ARMADILHA, e é a mesma do CHE: a API não devolve 401. Ela devolve
`text/html` com a página "DATASUS - Login para as aplicações do MS" e status 200.
Um coletor que só olhasse o status daria a rodada por bem-sucedida e gravaria
zero linha em silêncio. Quem for escrever o coletor: cheque o Content-Type e a
presença do título de login, nunca o status.

O QUE JÁ ESTÁ DESCOBERTO (para a próxima etapa, e para não repetir a garimpagem):

    base       https://investsus-backend-prd.saude.gov.br/api
               (vem de https://investsus.saude.gov.br/config/env.json, campo
               `backendUrl` — o bundle Angular a lê em runtime, então não há URL
               absoluta dentro do main.js; procurar por `config.get("backendUrl")`)
    repasses   GET /geral/repasses/valores?ano=<AAAA>&cnpj=<14 digitos>
               GET /geral/repasses            (filtros como query params)
               GET /geral/repasses/detalhe
               GET /geral/repasses/blocos/<codigoBloco>
               GET /geral/repasses/planilha   (devolve XLSX)
    propostas  GET /propostas/paginado
    login      https://acesso.saude.gov.br/v2/login — SSO próprio do DATASUS
               (`clientId: INVESTSUS` no env.json), NÃO é OIDC padrão: o
               `.well-known/openid-configuration` responde 404. A página traz um
               `authorization-server` no `<base href>`, o que sugere fluxo
               próprio. Molde para o coletor: `sigcon_scraper.py` (Playwright +
               credencial por município no Cofre + upsert incremental).

A credencial JÁ PODE SER CADASTRADA — `automation_key='investsus'` existe no
formulário do Cofre desde antes desta tela. Por isso o endpoint mostra se ela
está lá: é a única informação DESTE município que a tela tem hoje, e é acionável
(sem credencial, o coletor futuro não vai coletar nada para ele).
"""
from __future__ import annotations

AVISO = (
    "O InvestSUS é fechado: consultar exige login no autorizador do DATASUS. "
    "Esta tela ainda NÃO coleta os repasses automaticamente — ela reúne o que dá "
    "sem login (o que cada bloco significa, onde consultar, e se a credencial "
    "deste município já está no Cofre). Quando a coleta entrar, os valores "
    "aparecem aqui e passam a alimentar o alerta e o Relatório de Monitoramento."
)

TITULO = "InvestSUS"
SUBTITULO = "Repasses federais de saúde — fundo a fundo do FNS ao Fundo Municipal"

RESUMO = (
    "O InvestSUS mostra o que o Ministério da Saúde repassou ao Fundo Municipal "
    "de Saúde, separado por bloco de financiamento e por competência (mês/ano), "
    "além da situação das propostas de investimento. É a contrapartida do FNS: "
    "lá se acompanha a PROPOSTA, aqui o DINHEIRO que efetivamente caiu."
)

# Os blocos de financiamento da Portaria GM/MS 6.907/2022, que reorganizou o
# financiamento federal do SUS. São a chave de leitura de qualquer extrato do
# InvestSUS — sem eles, o gestor vê um número só e não sabe o que pode gastar
# em quê. Custeio e investimento não se misturam, e é isso que a coluna diz.
BLOCOS = [
    {"nome": "Atenção Primária à Saúde",
     "tipo": "Custeio",
     "o_que": "Piso da Atenção Primária: capitação ponderada, pagamento por "
              "desempenho, incentivos a eSF/eAP, saúde bucal, ACS e ACE."},
    {"nome": "Atenção Especializada à Saúde",
     "tipo": "Custeio",
     "o_que": "Média e alta complexidade ambulatorial e hospitalar, SAMU, "
              "CEO, CAPS e incentivos das redes temáticas."},
    {"nome": "Assistência Farmacêutica",
     "tipo": "Custeio",
     "o_que": "Componente básico da assistência farmacêutica — a parte federal "
              "do custeio dos medicamentos da farmácia básica."},
    {"nome": "Vigilância em Saúde",
     "tipo": "Custeio",
     "o_que": "Piso fixo e variável de vigilância: epidemiológica, sanitária, "
              "ambiental e saúde do trabalhador."},
    {"nome": "Gestão do SUS",
     "tipo": "Custeio",
     "o_que": "Qualificação da gestão, apoio à estruturação de serviços e "
              "ações de planejamento e regulação."},
    {"nome": "Investimento na Rede de Serviços Públicos",
     "tipo": "Investimento",
     "o_que": "Obra, ampliação, reforma e equipamento. É o bloco que conversa "
              "com o SISMOB: a obra que aparece lá foi paga por aqui."},
]

# O que o gestor precisa CONFERIR, e que o portal não avisa sozinho.
CONFERIR = [
    {"item": "Conta específica por bloco",
     "detalhe": "Cada bloco cai numa conta própria do Fundo Municipal. Misturar "
                "custeio de um bloco com outro é achado recorrente de auditoria, "
                "e o extrato do InvestSUS é a prova de qual verba era qual."},
    {"item": "Saldo parado rende glosa",
     "detalhe": "Recurso federal de saúde parado em conta sem execução aparece "
                "no relatório de gestão e pode ser objeto de devolução. O "
                "InvestSUS tem o módulo de devolução de recurso justamente por isso."},
    {"item": "Competência x data de crédito",
     "detalhe": "A competência (mês de referência) não é o mês em que o dinheiro "
                "entrou. Prestação de contas se faz pela competência; o extrato "
                "bancário, pela data de crédito. Confundir os dois desalinha o RM."},
    {"item": "Investimento tem prazo de execução",
     "detalhe": "Parcela de investimento não executada no prazo vira pendência e "
                "pode bloquear proposta nova no FNS — que é onde o próximo "
                "recurso seria pedido."},
]

LINKS: list[tuple[str, str]] = [
    ("InvestSUS (consulta do gestor, exige login)", "https://investsus.saude.gov.br"),
    ("Painéis InvestSUS", "https://investsuspaineis.saude.gov.br"),
    ("Portal do Fundo Nacional de Saúde", "https://portalfns.saude.gov.br"),
    ("Consulta pública do FNS", "https://consultafns.saude.gov.br"),
]
