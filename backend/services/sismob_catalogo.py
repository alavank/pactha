"""Catalogo do SISMOB: o que cada codigo da fonte significa.

Vive FORA do router de proposito, e NAO e arrumacao — nao mova para routers/:

  **A imagem do worker nao tem `/app/routers`.** O `Dockerfile.scraper` copia
  ingestion, models, services e schemas, e so isso. O coletor e o cron de push
  precisam destes rotulos; se importassem de `routers.sismob`, quebrariam em
  producao — e, como a excecao no cron e capturada junto com erro de SQL,
  quebrariam EM SILENCIO. Mesmo motivo de `services/cauc_catalogo.py`.

Os codigos abaixo foram lidos do bundle do proprio SISMOB Cidadao
(`main.<hash>.js`, projeto sismob-cidadao do Laboratorio Bridge/UFSC) e
conferidos contra as obras reais de Monte Siao em 2026-07-31.
"""
from __future__ import annotations

# Situacao da obra (co_situacao_obra). O rotulo por extenso vem da LISTAGEM da
# API; o DETALHE devolve so o codigo. Este mapa existe para o detalhe nao ficar
# sem situacao — ver o comentario sobre divergencia de campos em
# ingestion/sismob_obras.py.
SITUACAO = {
    0: "Em ação preparatória",
    1: "Em início de execução",
    2: "Em execução e conclusão",
    3: "Concluída",
    4: "Em funcionamento",
    5: "Paralisada em ação preparatória",
    6: "Paralisada em execução",
    7: "Obra cancelada",
    8: "Em cancelamento",
}

# Situacoes em que a obra nao consome mais prazo nem gera acao do gestor.
# ATENCAO: "Concluída" (3) NAO entra aqui. A 4a etapa — entrada em
# funcionamento, 90 dias, com registro no CNES — vem DEPOIS da conclusao, e
# ignora-la esconderia pendencia real (ha obra concluida em 2015 sem CNES).
TERMINAIS = (4, 7)

# Situacoes em que a obra esta parada por decisao formal (nao por abandono).
PARALISADAS = (5, 6)

FASE_PROJETO = {
    0: "Não iniciado",
    1: "Em elaboração",
    2: "Concluído",
}

# Programas (co_programa). Lista do bundle; qualquer codigo novo cai no
# fallback e aparece como "Programa <n>" em vez de sumir.
PROGRAMA = {
    1: "Requalifica UBS",
    2: "UPA",
    3: "CAPS",
    4: "Unidade de Acolhimento",
    6: "Academia da Saúde",
    8: "Centro de Parto Normal",
    9: "Casa da Gestante",
    10: "Ambiência",
    11: "UTIN",
    12: "CER",
    13: "UCINco",
    14: "UCINca",
    15: "Oficina Ortopédica",
    17: "Central de Rede de Frio",
    18: "Unidade de Vigilância de Zoonoses",
    19: "Banco de Leite Humano",
    20: "UBS Fluvial",
}

# --------------------------------------------------------------------------
# Prazos de norma
# --------------------------------------------------------------------------
# Portaria de Consolidacao 6/GM/MS de 2017, Titulo IX, arts. 1.104-1.120 (que
# absorveu a Portaria 381/2017), alterada pela GM/MS 6.618/2025.
#
# Etapas oficiais:
#   1. Acao preparatoria ....... 270 dias, prorrogaveis por mais 270
#   2. Inicio de execucao ...... comeca com o repasse, encerra ao informar 30%
#                                de execucao. Prazo maximo: 90 dias
#   3. Execucao e conclusao .... dos 30% ate 100%
#   4. Entrada em funcionamento  90 dias, com registro no CNES
#
# Atualizacao obrigatoria no SISMOB a cada 60 dias.
#
# ⚠️ NAO existe marco de 90%. Circula por ai que o acompanhamento seria "ate
# 30%, ate 90%" — os 30% sao reais e verificados nos dados (obra que cruza 30%
# transiciona de etapa); os 90% nao aparecem em norma nenhuma.
PRAZO_ACAO_PREPARATORIA_DIAS = 270
PRAZO_INICIO_EXECUCAO_DIAS = 90
PRAZO_FUNCIONAMENTO_DIAS = 90
PRAZO_ATUALIZACAO_DIAS = 60

# Marco que encerra a etapa de inicio de execucao.
MARCO_EXECUCAO_PCT = 30

NORMA = "Portaria de Consolidação 6/GM/MS de 2017, Título IX (arts. 1.104–1.120)"


def rotulo_situacao(codigo, fallback: str | None = None) -> str | None:
    """Rotulo por extenso. `fallback` e o que a LISTAGEM trouxe — quando existe,
    tem prioridade, porque e o texto do proprio MS."""
    if fallback:
        return fallback
    try:
        return SITUACAO.get(int(codigo))
    except (TypeError, ValueError):
        return None


def situacao_terminal(codigo) -> bool:
    try:
        return int(codigo) in TERMINAIS
    except (TypeError, ValueError):
        return False


def url_portal(proposta_id) -> str:
    """Link para a obra no SISMOB Cidadao.

    Formato CONFERIDO em 31/07/2026 (antes apontava para a home porque a SPA
    nao expoe rotas no HTML). O bundle do portal declara a rota "/obra/:propostaId"
    e o componente dela chama `loadObra(match.params.propostaId)` contra
    `/api/public/obras/{id}` — a mesma API que este modulo coleta. E o nosso
    `proposta_id` E o `coSeqProposta` do MS: conferido nas tres obras em acao de
    Monte Siao (112462, 193527, 4378), todas devolvendo 200 com o municipio e o
    estabelecimento certos.

    Id nao-numerico cai de volta na home DE PROPOSITO: `/obra/NaN` faz a SPA
    pedir `/api/public/obras/NaN`, que responde 500, e o portal mostra uma tela
    de erro sem busca e sem volta — pior que a home.
    """
    try:
        return f"https://sismobcidadao.saude.gov.br/obra/{int(proposta_id)}"
    except (TypeError, ValueError):
        return "https://sismobcidadao.saude.gov.br/"
