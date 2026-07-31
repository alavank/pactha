"""Catalogo do CAUC: o que cada codigo do extrato significa.

Vive FORA do router de proposito, e NAO e arrumacao — nao mova de volta:

  **A imagem do worker nao tem `/app/routers`.** O `Dockerfile.scraper` copia
  ingestion, models, services e schemas, e so isso. O cron de push
  (`ingestion/run_painel_alertas_cron.py`) precisa destes rotulos; se ele
  importasse `routers.cauc`, quebraria em producao — e, como a excecao la e
  capturada junto com erro de SQL, quebraria EM SILENCIO: o alerta nunca
  chegaria e ninguem saberia por que.

De quebra, evita arrastar FastAPI, os modelos e o engine do banco para dentro de
um script de linha de comando. Tambem usa: a regra de vencimento em
`services/bi_abas.py`. `routers/cauc.py` reexporta, por ser o endereco ja
conhecido destes nomes.
"""
from __future__ import annotations

# Grupos das exigencias CAUC (pelo digito inicial do codigo).
#
# ⚠️ SAO OS TITULOS LITERAIS DO EXTRATO, algarismo romano incluido. Nao reescreva
# com palavras "mais claras": a equipe de convenios abre o PDF do CAUC ao lado da
# tela e procura a secao pelo titulo. A versao anterior usava descricoes nossas
# ("Regularidade fiscal e adimplencia com a Uniao") — verdadeiras, mas que nao
# existem em documento nenhum, entao nao casavam com o extrato na hora de
# conferir. Transcrito do extrato de 31/07/2026.
GRUPOS = {
    "1": "I - Obrigações de Adimplência Financeira",
    "2": "II - Adimplemento na Prestação de Contas de Convênios",
    "3": "III - Obrigações de Transparência",
    "4": "IV - Adimplemento de Obrigações Constitucionais ou Legais",
    "5": "V - Cumprimento de Limites Constitucionais e Legais",
}

# A traducao para quem nao vive o extrato. Vai como SUBTITULO do bloco, nunca no
# lugar do titulo oficial: o prefeito entende a glosa, a equipe de convenios
# precisa do titulo que esta no PDF. Os dois cabem.
GRUPOS_GLOSSA = {
    "1": "regularidade fiscal e adimplência com a União",
    "2": "prestação de contas de recursos federais já recebidos",
    "3": "informações fiscais e contábeis, transparência e Siafic",
    "4": "competência tributária e regularidade previdenciária",
    "5": "aplicações mínimas e limites (educação, saúde, Fundeb, PPP, crédito)",
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


def _ano4(d: str) -> str:
    """dd/mm/aa -> dd/mm/aaaa. O CSV do Tesouro manda o ano com 2 digitos
    ("31/07/26") e o extrato oficial imprime 4. Como a tela existe para ser
    conferida CONTRA o extrato, ela usa o formato do extrato."""
    p = d.split("/")
    if len(p) == 3 and len(p[2]) == 2 and p[2].isdigit():
        yy = int(p[2])
        p[2] = f"{2000 + yy if yy < 70 else 1900 + yy}"
    return "/".join(p)


def _classifica(valor: str) -> tuple[str, str, str | None, str]:
    """(tipo, situacao, validade, nota) a partir do valor bruto do CSV do CAUC.

    `situacao` usa as PALAVRAS DO EXTRATO — "Comprovado", "A Comprovar",
    "Desativado" —, e a data sai separada, em `validade`, porque no extrato sao
    duas colunas e a tela existe para ser conferida contra ele. Antes isto
    devolvia frases nossas ("Regular ate 31/07/26"), que misturavam as duas
    colunas numa so e nao casavam com o documento.

    A `nota` carrega o significado oficial, que e traicoeiro em dois pontos:

    **"Desativado" NAO quer dizer "nao exigido".** O texto oficial e "a
    informacao do item nao esta disponivel na data da consulta. Essa situacao e
    valida para TODOS os entes" — indisponibilidade da FONTE, nao dispensa do
    municipio. O caso que prova: o FGTS e o item 1.3, desativado no CAUC, e ao
    mesmo tempo esta VENCIDO no CAGEC, travando convenio estadual.

    **"A Comprovar" nao acusa o municipio**: e "nao foi possivel ao CAUC obter a
    informacao de comprovacao de cumprimento do requisito fiscal".
    """
    v = (valor or "").strip()
    if v == "!":
        return ("pendente", "A Comprovar", None,
                "O CAUC não obteve a comprovação deste requisito. "
                "Comprove documentalmente junto ao órgão concedente.")
    if v.lower() == "desabilitado":
        return ("na", "Desativado", None,
                "Indisponível na consulta, para TODOS os entes — "
                "é falha/adaptação da própria ferramenta, não dispensa a exigência.")
    if v == "":
        return ("na", "Sem informação", None, "")
    return ("regular", "Comprovado", _ano4(v), "")
