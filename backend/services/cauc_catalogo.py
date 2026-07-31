"""Catalogo do CAUC: o que cada codigo do extrato significa.

Vive FORA do router de proposito. A regra de vencimento (services/bi_abas.py)
e o cron de push (ingestion/run_painel_alertas_cron.py) precisam destes rotulos,
e importar `routers.cauc` so por causa deles arrastaria FastAPI, os modelos e o
engine do banco para dentro de um script de linha de comando — cadeia pesada que
falharia por motivo nenhum a ver com o alerta.
"""
from __future__ import annotations

# Grupos das exigencias CAUC (pelo digito inicial do codigo).
GRUPOS = {
    "1": "Regularidade fiscal e adimplência com a União",
    "2": "Prestação de contas de recursos federais recebidos",
    "3": "Informações fiscais e contábeis, transparência e Siafic",
    "4": "Competência tributária e regularidade previdenciária",
    "5": "Aplicações mínimas e limites (educação, saúde, Fundeb, PPP, crédito)",
}

# Rotulos das exigencias do extrato do CAUC.
#
# ⚠️ FONTE OBRIGATORIA — nao escreva de cabeca. Estes rotulos sao transcricao do
# PDF oficial "Metadados CAUC Municipios", do MESMO dataset CKAN que a ingestao
# ja baixa (`ingestion/cauc_ingest.py`, dataset `cauc` do Tesouro Transparente):
#   package_show?id=cauc -> resource format=PDF, name="Metadados CAUC Municípios"
# Conferido em 2026-07-30 contra o PDF e, de forma independente, contra o CRC do
# CAGEC-MG, que cita nominalmente os itens 3.1.2, 3.2, 3.3, 3.4, 3.5, 4.1, 5.1 e 5.2.
#
# POR QUE O AVISO: a versao anterior desta tabela tinha a MAIORIA dos rotulos
# trocada — 3.3 aparecia como "Cadastro da Divida Publica" (e CDP e o 3.5), 4.1
# como "Aplicacao minima em Educacao" (e competencia tributaria; educacao e o
# 5.1), 5.2 como "Transparencia LC 131" (e aplicacao minima em saude). A tela
# dizia ao prefeito que faltava uma coisa quando faltava outra. Provavel causa:
# a numeracao do extrato mudou e a tabela ficou para tras. Ao mexer aqui,
# reconfira contra o PDF — nao contra memoria nem contra FAQ de terceiros.
LABELS = {
    "1.1": "Tributos, contribuições previdenciárias federais e Dívida Ativa da União",
    "1.2": "Pagamento de precatórios judiciais",
    "1.3": "Contribuições para o FGTS",
    "1.4": "Adimplência em empréstimos e financiamentos concedidos pela União",
    "1.5": "Regularidade perante o Poder Público Federal",
    "2.1.1": "Prestação de contas de recursos federais — SIAFI/Transferências",
    "2.1.2": "Prestação de contas de recursos federais — Transferegov",
    "3.1.1": "RGF — publicação do Relatório de Gestão Fiscal",
    "3.1.2": "RGF — encaminhamento ao Siconfi",
    "3.2.1": "RREO — publicação do Relatório Resumido de Execução Orçamentária",
    "3.2.2": "RREO — encaminhamento ao Siconfi",
    "3.2.3": "RREO — encaminhamento do Anexo 8 ao Siope",
    "3.2.4": "RREO — encaminhamento do Anexo 12 ao Siops",
    "3.3": "Encaminhamento das contas anuais",
    "3.4.1": "Matriz de Saldos Contábeis — encaminhamento mensal",
    "3.4.2": "Matriz de Saldos Contábeis — encaminhamento de encerramento",
    "3.5": "Cadastro da Dívida Pública (CDP)",
    "3.6": "Transparência da execução orçamentária e financeira em meio eletrônico",
    "3.7": "Adoção de Sistema Integrado de Administração Financeira e Controle (Siafic)",
    "4.1": "Exercício da plena competência tributária",
    "4.2": "Regularidade previdenciária",
    "5.1": "Aplicação mínima de recursos em Educação",
    "5.2": "Aplicação mínima de recursos em Saúde",
    "5.3": "Limite de despesas com Parcerias Público-Privadas (PPP)",
    "5.4": "Limite de operações de crédito, inclusive por antecipação de receita",
    "5.5": "Fundeb — aplicação mínima em profissionais da educação básica",
    "5.6": "Fundeb — complementação da União aplicada em despesas de capital",
    "5.7": "Fundeb — 50% da complementação VAAT na educação infantil",
}


def _classifica(valor: str) -> tuple[str, str]:
    """(tipo, status legivel) a partir do valor bruto do CSV do CAUC.

    Os significados sao os do proprio PDF de metadados, e um deles e traicoeiro:
    **"Desabilitado" NAO quer dizer "nao exigido"**. O texto oficial e "a
    informacao do item nao esta disponivel na data da consulta. Essa situacao e
    valida para TODOS os entes" — ou seja, e indisponibilidade da FONTE, nao
    dispensa do municipio. Dizer "nao exigido" na tela fazia o gestor riscar da
    lista uma exigencia que continua valendo."""
    v = (valor or "").strip()
    if v == "!":
        # Oficial: "nao foi possivel ao CAUC obter a informacao de comprovacao
        # de cumprimento do requisito fiscal". Sem comprovacao, trava — mas o
        # rotulo diz o que de fato aconteceu em vez de acusar o municipio.
        return ("pendente", "Sem comprovação no CAUC")
    if v.lower() == "desabilitado":
        return ("na", "Indisponível na consulta (para todos os entes)")
    if v == "":
        return ("na", "Sem informação")
    return ("regular", f"Regular até {v}")
