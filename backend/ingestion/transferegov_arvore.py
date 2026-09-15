"""VOLUNTARIAS: a ARVORE da proposta pelos dumps de Discricionarias e Legais.

⭐ O QUE ESTE MODULO FAZ. Os 65 zips de CSV de
`api-publica.transferegov.gestao.gov.br/downloads/dadosgov/` (3,5 GB,
republicados todo dia ~11:12 UTC) trazem, por proposta, o que o PACTHA buscava
RASPANDO o portal — parte atras de sessao gov.br, que ficou morta 297 h em 720 h
— e muito que nao buscava de lugar nenhum. O `transferegov_opendata.py` le 5
deles para a camada base (a linha de cada proposta). Este le os outros 50 e
monta, para cada proposta que ja esta no banco:

  transferegov_propostas.arvore   o que e pequeno por proposta (ver o SQL em
                                  `migrations/add_tg_arvore.sql`), mais `_resumo`
  transferegov_propostas.notas_empenho_aberto   NEs reais (`siconv_empenho`)
  transferegov_propostas.ops_obs_aberto         desembolsos/OB, no MESMO
                                                formato do `ops_obs` raspado
  tg_licitacoes / tg_pagamentos / tg_documentos_liquidacao   as listas GRANDES
  tg_propostas_canceladas                       o arquivo que ninguem lia

⚠️ NAO HA API REST PARA DISCRICIONARIAS (a oficial esta prevista a partir de
10/2026). Dump nao tem o risco "filtro ignorado devolve o Brasil" das APIs; o
risco dele e RENOMEAR COLUNA. Por isso cada arquivo declara as colunas que este
modulo le pelo nome (`ARQUIVOS`), e cabecalho sem elas PULA o arquivo inteiro e
marca a secao como incompleta — nada e trocado com metade do dado.

⚠️ AS CHAVES (medidas em 15/09/2026 numa carteira do tamanho da Trust, 7.639
propostas: 1 min de download e 3 min de varredura dos 53 arquivos uteis):
  proposta ─ ID_PROPOSTA ─┬─ convenio ─ NR_CONVENIO ─┬─ empenho, desembolso,
                          │                          │   pagamento, licitacao,
                          │                          │   termo_aditivo, ...
                          ├─ meta ─ ID_META ─ etapa  └─ dados_obrasgov_geral ─
                          ├─ dl ─ ID_DL ─ itens_dl       ID_PROJETO_INVESTIMENTO
                          └─ ...                           ─ *_cipi
  pagamento ─ NR_MOV_FIN ─ obtv_convenente;  licitacao ─ ID_LICITACAO ─
  contrato, itens_licitacao;  desembolso ─ ID_DESEMBOLSO ─ empenho_desembolso.

As propostas vem do BANCO (`id_proposta_siconv` gravado pelo opendata), e nao do
`siconv_proposta.zip`: a arvore e de quem aparece na tela.

Rodar:  python -u ingestion/transferegov_arvore.py
        TG_ARVORE_FORCE=1 ...   (ignora o intervalo minimo de 20 h)
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion import transferegov_opendata as od  # noqa: E402
from ingestion.siconv_empenho_aberto import _e_ne_real, _registro as _ne_registro  # noqa: E402
from services.natureza import municipal_ou_nulo  # noqa: E402

log = logging.getLogger("tg_arvore")

FONTE = "transferegov_arvore"
MIN_INTERVAL_H = float(os.getenv("TG_ARVORE_MIN_INTERVAL_H", "20") or "20")
# Zip acima disto e APAGADO depois de lido. O cache do opendata (20 h) serve aos
# pequenos, que duas tasks leem na mesma noite; os grandes (`itens_dl` 535 MB,
# `justificativas` 750 MB) somariam GBs parados no disco do worker.
APAGA_ACIMA_BYTES = int(float(os.getenv("TG_ARVORE_APAGA_ACIMA_MB", "50") or "50") * 1e6)
csv.field_size_limit(1 << 30)

# Arquivo -> colunas que este modulo le PELO NOME. E a guarda do cabecalho: se a
# fonte renomear uma delas, o arquivo e pulado e a secao fica como estava.
ARQUIVOS: dict[str, tuple[str, ...]] = {
    # -- arvore (por proposta) --------------------------------------------
    "siconv_convenio": ("NR_CONVENIO", "ID_PROPOSTA", "DIA_FIM_VIGENC_CONV",
                        "DIA_FIM_VIGENC_ORIGINAL_CONV", "VL_REPASSE_CONV",
                        "VL_CONTRAPARTIDA_CONV", "VL_SALDO_CONTA", "DIA_LIMITE_PREST_CONTAS",
                        "VL_RENDIMENTO_APLICACAO"),
    "siconv_emenda": ("ID_PROPOSTA", "NR_EMENDA"),
    "apoiadores_emendas_programas": ("NUMERO_EMENDA_APOIADORES_EMENDAS",
                                     "CNPJ_PROPONENTE_APOIADORES_EMENDAS"),
    "siconv_prop_inst_indicadores_municipios": ("ID_PROPOSTA",),
    "siconv_historico_situacao": ("ID_PROPOSTA", "DIA_HISTORICO_SIT", "HISTORICO_SIT",
                                  "DIAS_HISTORICO_SIT"),
    "siconv_historico_projeto_basico": ("ID_PROPOSTA",),
    "siconv_justificativas_proposta": ("ID_PROPOSTA",),
    "siconv_meta_crono_fisico": ("ID_PROPOSTA", "ID_META"),
    "siconv_etapa_crono_fisico": ("ID_META",),
    "siconv_plano_aplicacao_detalhado": ("ID_PROPOSTA",),
    "siconv_cronograma_desembolso": ("ID_PROPOSTA",),
    "siconv_coordenadas_obra": ("ID_PROPOSTA",),
    "siconv_resumo_fisico_financeiro": ("ID_PROPOSTA", "PERCENTUAL_EXECUCAO_RESUMO_FISICO_FINANCEIRO"),
    "siconv_consorcios": ("ID_PROPOSTA",),
    "siconv_solicitacao_ajuste_pt": ("ID_PROPOSTA",),
    "siconv_empenho": ("NR_CONVENIO", "ID_EMPENHO", "NR_EMPENHO", "VALOR_EMPENHO",
                       "DESC_TIPO_NOTA", "DESC_SITUACAO_EMPENHO", "DATA_EMISSAO"),
    "siconv_desembolso": ("NR_CONVENIO", "ID_DESEMBOLSO", "VL_DESEMBOLSADO", "DATA_DESEMBOLSO",
                          "NR_SIAFI", "UG_EMITENTE_DH", "DT_ULT_DESEMBOLSO",
                          "QTD_DIAS_SEM_DESEMBOLSO"),
    "siconv_empenho_desembolso": ("ID_DESEMBOLSO", "ID_EMPENHO"),
    "siconv_pagamento_tributo": ("NR_CONVENIO", "VL_PAG_TRIBUTOS"),
    "siconv_termo_aditivo": ("NR_CONVENIO", "DT_FIM_TA"),
    "siconv_prorroga_oficio": ("NR_CONVENIO", "DT_FIM_PRORROGA", "DIAS_PRORROGA"),
    "siconv_solicitacao_alteracao": ("NR_CONVENIO",),
    "siconv_ingresso_contrapartida": ("NR_CONVENIO", "VL_INGRESSO_CONTRAPARTIDA"),
    "siconv_solicitacao_rendimento_aplicacao": ("NR_CONVENIO",),
    "siconv_desbloqueio_cr": ("NR_CONVENIO",),
    "siconv_desbloqueio_recurso_cr": ("NR_CONVENIO",),
    "siconv_acomp_obras_contratos_medicoes_modulo_empresas": (
        "ID_PROPOSTA", "ID_CONTRATO_MEDICAO_ACOMPANHAMENTO_OBRA",
        "QTD_DIAS_SEM_MEDICAO_ACOMPANHAMENTO_OBRA", "SITUACAO_MEDICAO_ACOMPANHAMENTO_OBRA"),
    "siconv_acomp_obras_valores_itens_medicao_modulo_empresas": (
        "ID_CONTRATO_MEDICAO_ACOMPANHAMENTO_OBRA",),
    "siconv_projeto_basico_proposta_modulo_empresas": ("ID_PROPOSTA",),
    "siconv_projeto_basico_acffo_modulo_empresas": ("ID_PROPOSTA",),
    "siconv_projeto_basico_lae_modulo_empresas": ("ID_PROPOSTA", "ID_QCI_ACFFO"),
    "siconv_projeto_basico_metas_modulo_empresas": ("ID_QCI_ACFFO", "ID_META_PROJETO_BASICO"),
    "siconv_projeto_basico_submetas_modulo_empresas": ("ID_META_PROJETO_BASICO",),
    "siconv_vrpl_proposta_licitacao_modulo_empresas": ("ID_PROPOSTA", "ID_PROPOSTA_VRPL",
                                                       "ID_LICITACAO_VRPL"),
    "siconv_vrpl_metas_submetas_modulo_empresas": ("ID_PROPOSTA_VRPL",),
    "siconv_vrpl_lotes_fornecedores_licitacao_modulo_empresas": ("ID_LICITACAO_VRPL",),
    "siconv_inst_cont_proposta_aio_modulo_empresas": ("ID_PROPOSTA",
                                                      "ID_PROPOSTA_INSTRUMENTO_CONTRATUAL"),
    "siconv_inst_cont_contratos_lotes_empresas_modulo_empresas": (
        "ID_PROPOSTA_INSTRUMENTO_CONTRATUAL",),
    "siconv_inst_cont_metas_submetas_po_modulo_empresas": ("ID_PROPOSTA_INSTRUMENTO_CONTRATUAL",),
    "siconv_dados_obrasgov_geral": ("nr_instrumento", "id_projeto_investimento"),
    "siconv_contrato_cipi": ("ID_PROJETO_INVESTIMENTO",),
    "siconv_empenho_cipi": ("ID_PROJETO_INVESTIMENTO",),
    "siconv_execucao_fisica_cipi": ("id_projeto_investimento",),
    # -- tabelas -----------------------------------------------------------
    "siconv_licitacao": ("ID_LICITACAO", "NR_CONVENIO", "NR_LICITACAO", "MODALIDADE_LICITACAO",
                         "STATUS_LICITACAO", "DATA_PUBLICACAO_LICITACAO", "VALOR_LICITACAO"),
    "siconv_contrato": ("ID_LICITACAO",),
    "siconv_itens_licitacao": ("ID_LICITACAO",),
    "siconv_pagamento": ("NR_MOV_FIN", "NR_CONVENIO", "IDENTIF_FORNECEDOR", "NOME_FORNECEDOR",
                         "TP_MOV_FINANCEIRA", "DATA_PAG", "VL_PAGO", "ID_DL"),
    "siconv_obtv_convenente": ("NR_MOV_FIN",),
    "siconv_dl": ("ID_DL", "ID_PROPOSTA", "ID_LICITACAO", "ID_CONTRATO", "DATA_DE_EMISSAO",
                  "NUMERO", "DESCRICAO", "RAZAO_SOCIAL", "VALOR", "STATUS"),
    "siconv_itens_dl": ("ID_DL",),
    "siconv_proposta_cancelada": ("ID_PROPOSTA", "COD_MUNIC_IBGE", "NR_PROPOSTA", "NM_PROPONENTE",
                                  "NATUREZA_JURIDICA", "OBJETO_PROPOSTA", "DESC_ORGAO",
                                  "VL_GLOBAL_PROP"),
    "data_carga_siconv": ("data_carga",),
}

SECOES = ("arvore", "licitacoes", "pagamentos", "liquidacoes", "canceladas")


class FalhaArquivo(Exception):
    """O arquivo nao foi lido INTEIRO (download, zip ou cabecalho)."""


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _abrir(nome: str) -> tuple[list[str], Iterator[dict]]:
    """(cabecalho, linhas) do CSV dentro de <nome>.zip, em stream.

    Reaproveita o download do `transferegov_opendata` (cache em disco, .part
    atomico) e a mesma leitura: UTF-8 COM BOM. Zip grande e apagado no fim."""
    if nome == "data_carga_siconv":
        return _abrir_data_carga()
    caminho = od._baixa(nome + ".zip")

    def _gerador(z, bruto, leitor):
        try:
            for linha in leitor:
                yield linha
        finally:
            bruto.close()
            z.close()
            try:
                if os.path.getsize(caminho) > APAGA_ACIMA_BYTES:
                    os.remove(caminho)
            except OSError:
                pass

    z = zipfile.ZipFile(caminho)
    bruto = z.open(z.namelist()[0])
    texto = io.TextIOWrapper(bruto, encoding="utf-8-sig", errors="replace", newline="")
    leitor = csv.DictReader(texto, delimiter=";")
    cab = [c.strip().lstrip("﻿") for c in (leitor.fieldnames or [])]
    leitor.fieldnames = cab
    return cab, _gerador(z, bruto, leitor)


def _abrir_data_carga() -> tuple[list[str], Iterator[dict]]:
    """`data_carga_siconv.zip` tem ~150 bytes ("data_carga\\r\\n15/09/2026 06:34:05").

    ⚠️ NAO passa pelo `_baixa`: ele recusa arquivo abaixo de 1.000 bytes como
    download truncado — guarda certa para os zips de centenas de MB, e que
    rejeitava ESTE sempre (medido no e2e de 15/09/2026). Tambem nao usa o cache:
    a data da carga e justamente o que tem de ser o mais novo. A integridade
    fica com o zipfile (zip cortado nao abre)."""
    import httpx
    r = httpx.get(f"{od.BASE}/data_carga_siconv.zip", timeout=60, follow_redirects=True)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        texto = z.read(z.namelist()[0]).decode("utf-8-sig", errors="replace")
    linhas = [li.strip() for li in texto.splitlines() if li.strip()]
    if len(linhas) < 2:
        raise OSError(f"data_carga_siconv sem data: {texto[:60]!r}")
    cab = [linhas[0].split(";")[0].strip()]
    return cab, iter([{cab[0]: linhas[1].split(";")[0].strip()}])


def _ler(nome: str) -> Iterator[dict]:
    """As linhas de um arquivo, COMPACTAS (campo vazio omitido — o JSONB guarda o
    que a fonte disse, e "" nao diz nada), com a guarda do cabecalho."""
    try:
        cab, linhas = _abrir(nome)
    except Exception as e:
        raise FalhaArquivo(f"{nome}: {type(e).__name__}: {str(e)[:120]}") from e
    faltam = [c for c in ARQUIVOS.get(nome, ()) if c not in cab]
    if faltam:
        # Consome o gerador para fechar o zip (e apaga-lo, se grande).
        for _ in linhas:
            break
        raise FalhaArquivo(f"{nome}: cabecalho sem {faltam} — a fonte renomeou coluna?")
    try:
        for linha in linhas:
            yield {k: v for k, v in linha.items() if k and v not in (None, "")}
    except FalhaArquivo:
        raise
    except Exception as e:
        raise FalhaArquivo(f"{nome}: leitura interrompida: {type(e).__name__}: {str(e)[:120]}") from e


def _num(v) -> float | None:
    return od._money(v)


def _dt(v) -> datetime | None:
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if " " in s else s[:10], fmt)
        except ValueError:
            continue
    return None


def _max_data(valores) -> str | None:
    """A maior data de uma lista de textos de data, devolvida como o TEXTO da fonte."""
    melhor = None
    for v in valores:
        d = _dt(v)
        if d and (melhor is None or d > melhor[0]):
            melhor = (d, v)
    return melhor[1] if melhor else None


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Coleta (sem banco: tudo entra por `ler`, o que deixa testar com linhas reais)
# ---------------------------------------------------------------------------
class Coleta:
    def __init__(self):
        self.arvores: dict[str, dict] = {}
        self.notas_empenho: dict[str, list] = {}
        self.ops_obs: dict[str, dict] = {}
        self.licitacoes: list[dict] = []
        self.pagamentos: list[dict] = []
        self.liquidacoes: list[dict] = []
        self.canceladas: list[dict] = []
        self.falhas: dict[str, list[str]] = {s: [] for s in SECOES}
        self.arquivos_falhos: set[str] = set()
        # Chaves da arvore que NAO foram trocadas nesta rodada (arquivo falhou):
        # a gravacao as omite e o `||` do JSONB mantem o valor anterior.
        self.chaves_mantidas: set[str] = set()
        self.linhas: dict[str, int] = {}
        self.data_carga: str | None = None
        self.mids_ibge: list[int] = []


def _agrupa(ler, c: Coleta, secao: str, nome: str, col: str, alvo) -> dict[str, list[dict]] | None:
    """{chave: [linhas]} das linhas cuja `col` esta em `alvo`. None = o arquivo
    nao foi lido inteiro (registrado em `c.falhas[secao]`)."""
    out: dict[str, list[dict]] = defaultdict(list)
    n = lidas = 0
    try:
        for linha in ler(nome):
            lidas += 1
            k = linha.get(col)
            if k is not None and k in alvo:
                out[k].append(linha)
                n += 1
        if not lidas:
            # Todo arquivo destes tem linha no Brasil inteiro. Vazio e carga
            # quebrada da fonte — e trocar por ele APAGARIA a tabela.
            raise FalhaArquivo(f"{nome}: arquivo sem nenhuma linha")
    except FalhaArquivo as e:
        log.warning("  %s", e)
        c.falhas[secao].append(str(e))
        c.arquivos_falhos.add(nome)
        return None
    c.linhas[nome] = n
    return out


# Chave de topo da arvore -> arquivos de que ela depende. Arquivo que falhou
# tira a chave da gravacao (o valor anterior fica). ⚠️ `siconv_convenio` e a
# RAIZ de tudo que vem por NR_CONVENIO: sem ele a arvore nao e trocada.
DEPENDE: dict[str, tuple[str, ...]] = {
    "emendas": ("siconv_emenda", "apoiadores_emendas_programas"),
    "indicadores": ("siconv_prop_inst_indicadores_municipios",),
    "historico_situacao": ("siconv_historico_situacao",),
    "projeto_basico": ("siconv_historico_projeto_basico",
                       "siconv_projeto_basico_proposta_modulo_empresas",
                       "siconv_projeto_basico_acffo_modulo_empresas",
                       "siconv_projeto_basico_lae_modulo_empresas",
                       "siconv_projeto_basico_metas_modulo_empresas",
                       "siconv_projeto_basico_submetas_modulo_empresas"),
    "justificativas": ("siconv_justificativas_proposta",),
    "metas": ("siconv_meta_crono_fisico", "siconv_etapa_crono_fisico"),
    "plano_aplicacao": ("siconv_plano_aplicacao_detalhado",),
    "cronograma": ("siconv_cronograma_desembolso",),
    "coordenadas": ("siconv_coordenadas_obra",),
    "resumo_fisico_financeiro": ("siconv_resumo_fisico_financeiro",),
    "obras": ("siconv_acomp_obras_contratos_medicoes_modulo_empresas",
              "siconv_acomp_obras_valores_itens_medicao_modulo_empresas",
              "siconv_vrpl_proposta_licitacao_modulo_empresas",
              "siconv_vrpl_metas_submetas_modulo_empresas",
              "siconv_vrpl_lotes_fornecedores_licitacao_modulo_empresas",
              "siconv_inst_cont_proposta_aio_modulo_empresas",
              "siconv_inst_cont_contratos_lotes_empresas_modulo_empresas",
              "siconv_inst_cont_metas_submetas_po_modulo_empresas"),
    "cipi": ("siconv_dados_obrasgov_geral", "siconv_contrato_cipi", "siconv_empenho_cipi",
             "siconv_execucao_fisica_cipi"),
    "consorcios": ("siconv_consorcios",),
    "ajustes_pt": ("siconv_solicitacao_ajuste_pt",),
    "empenhos": ("siconv_empenho",),
    "desembolsos": ("siconv_desembolso", "siconv_empenho_desembolso"),
    "tributos": ("siconv_pagamento_tributo",),
    "aditivos": ("siconv_termo_aditivo",),
    "prorrogacoes": ("siconv_prorroga_oficio",),
    "solicitacoes_alteracao": ("siconv_solicitacao_alteracao",),
    "contrapartida": ("siconv_ingresso_contrapartida",),
    "rendimentos": ("siconv_solicitacao_rendimento_aplicacao",),
    "desbloqueios": ("siconv_desbloqueio_cr",),
    "desbloqueio_recurso": ("siconv_desbloqueio_recurso_cr",),
}


def coleta(propostas: dict[str, tuple[int, str | None]], ibges: dict[str, int],
           ler: Callable[[str], Iterator[dict]] = _ler) -> Coleta:
    """`propostas` = {id_proposta_siconv: (municipio_id, cnpj do proponente)};
    `ibges` = {codigo IBGE: municipio_id} (so para as canceladas)."""
    c = Coleta()
    c.mids_ibge = sorted(set(ibges.values()))
    ids = set(propostas)

    def g(nome, col, alvo):
        return _agrupa(ler, c, "arvore", nome, col, alvo) or {}

    # 1) O convenio: NR_CONVENIO de cada proposta.
    conv_por_prop: dict[str, dict] = {}
    for idp, linhas in g("siconv_convenio", "ID_PROPOSTA", ids).items():
        conv_por_prop[idp] = linhas[0]
    prop_por_conv = {v["NR_CONVENIO"]: k for k, v in conv_por_prop.items() if v.get("NR_CONVENIO")}
    convs = set(prop_por_conv)

    # 2) Filhos por ID_PROPOSTA.
    por_prop = {nome: g(nome, "ID_PROPOSTA", ids) for nome in (
        "siconv_emenda", "siconv_prop_inst_indicadores_municipios", "siconv_historico_situacao",
        "siconv_historico_projeto_basico", "siconv_justificativas_proposta",
        "siconv_meta_crono_fisico", "siconv_plano_aplicacao_detalhado",
        "siconv_cronograma_desembolso", "siconv_coordenadas_obra",
        "siconv_resumo_fisico_financeiro", "siconv_consorcios", "siconv_solicitacao_ajuste_pt",
        "siconv_acomp_obras_contratos_medicoes_modulo_empresas",
        "siconv_projeto_basico_proposta_modulo_empresas",
        "siconv_projeto_basico_acffo_modulo_empresas",
        "siconv_projeto_basico_lae_modulo_empresas",
        "siconv_vrpl_proposta_licitacao_modulo_empresas",
        "siconv_inst_cont_proposta_aio_modulo_empresas")}

    # 3) Filhos por NR_CONVENIO.
    por_conv = {nome: g(nome, "NR_CONVENIO", convs) for nome in (
        "siconv_empenho", "siconv_desembolso", "siconv_pagamento_tributo", "siconv_termo_aditivo",
        "siconv_prorroga_oficio", "siconv_solicitacao_alteracao", "siconv_ingresso_contrapartida",
        "siconv_solicitacao_rendimento_aplicacao", "siconv_desbloqueio_cr",
        "siconv_desbloqueio_recurso_cr")}
    obrasgov = g("siconv_dados_obrasgov_geral", "nr_instrumento", convs)

    # 4) Netos (as chaves saem dos filhos acima).
    def _chaves(grupo: dict, col: str) -> set:
        return {l[col] for linhas in grupo.values() for l in linhas if l.get(col)}

    metas = por_prop["siconv_meta_crono_fisico"]
    etapas = g("siconv_etapa_crono_fisico", "ID_META", _chaves(metas, "ID_META"))
    desemb = por_conv["siconv_desembolso"]
    emp_des = g("siconv_empenho_desembolso", "ID_DESEMBOLSO", _chaves(desemb, "ID_DESEMBOLSO"))
    medicoes = por_prop["siconv_acomp_obras_contratos_medicoes_modulo_empresas"]
    med_valores = g("siconv_acomp_obras_valores_itens_medicao_modulo_empresas",
                    "ID_CONTRATO_MEDICAO_ACOMPANHAMENTO_OBRA",
                    _chaves(medicoes, "ID_CONTRATO_MEDICAO_ACOMPANHAMENTO_OBRA"))
    lae = por_prop["siconv_projeto_basico_lae_modulo_empresas"]
    pb_metas = g("siconv_projeto_basico_metas_modulo_empresas", "ID_QCI_ACFFO",
                 _chaves(lae, "ID_QCI_ACFFO"))
    pb_sub = g("siconv_projeto_basico_submetas_modulo_empresas", "ID_META_PROJETO_BASICO",
               _chaves(pb_metas, "ID_META_PROJETO_BASICO"))
    vrpl = por_prop["siconv_vrpl_proposta_licitacao_modulo_empresas"]
    vrpl_metas = g("siconv_vrpl_metas_submetas_modulo_empresas", "ID_PROPOSTA_VRPL",
                   _chaves(vrpl, "ID_PROPOSTA_VRPL"))
    vrpl_lotes = g("siconv_vrpl_lotes_fornecedores_licitacao_modulo_empresas", "ID_LICITACAO_VRPL",
                   _chaves(vrpl, "ID_LICITACAO_VRPL"))
    aio = por_prop["siconv_inst_cont_proposta_aio_modulo_empresas"]
    ids_ic = _chaves(aio, "ID_PROPOSTA_INSTRUMENTO_CONTRATUAL")
    ic_contratos = g("siconv_inst_cont_contratos_lotes_empresas_modulo_empresas",
                     "ID_PROPOSTA_INSTRUMENTO_CONTRATUAL", ids_ic)
    ic_metas = g("siconv_inst_cont_metas_submetas_po_modulo_empresas",
                 "ID_PROPOSTA_INSTRUMENTO_CONTRATUAL", ids_ic)
    ids_pi = _chaves(obrasgov, "id_projeto_investimento")
    cipi_contratos = g("siconv_contrato_cipi", "ID_PROJETO_INVESTIMENTO", ids_pi)
    cipi_empenhos = g("siconv_empenho_cipi", "ID_PROJETO_INVESTIMENTO", ids_pi)
    cipi_exec = g("siconv_execucao_fisica_cipi", "id_projeto_investimento", ids_pi)
    cnpjs = {cnpj for _, cnpj in propostas.values() if cnpj}
    apoiadores = g("apoiadores_emendas_programas", "CNPJ_PROPONENTE_APOIADORES_EMENDAS", cnpjs)
    apoio_por_emenda: dict[tuple, list] = defaultdict(list)
    for cnpj, linhas in apoiadores.items():
        for a in linhas:
            apoio_por_emenda[(a.get("NUMERO_EMENDA_APOIADORES_EMENDAS"), cnpj)].append(a)

    # 5) Montagem da arvore de cada proposta.
    for idp, (mid, cnpj) in propostas.items():
        conv = conv_por_prop.get(idp)
        nc = conv.get("NR_CONVENIO") if conv else None

        def P(nome):
            return list(por_prop[nome].get(idp, []))

        def C(nome):
            return list(por_conv[nome].get(nc, [])) if nc else []

        def um(lista):
            return lista[0] if lista else None

        emendas = P("siconv_emenda")
        for e in emendas:
            e["apoiadores"] = apoio_por_emenda.get((e.get("NR_EMENDA"), cnpj), [])
        ms = P("siconv_meta_crono_fisico")
        for m in ms:
            m["etapas"] = etapas.get(m.get("ID_META"), [])
        ds = C("siconv_desembolso")
        for d in ds:
            d["empenhos"] = emp_des.get(d.get("ID_DESEMBOLSO"), [])
        meds = P("siconv_acomp_obras_contratos_medicoes_modulo_empresas")
        for m in meds:
            m["valores"] = med_valores.get(m.get("ID_CONTRATO_MEDICAO_ACOMPANHAMENTO_OBRA"), [])
        laes = P("siconv_projeto_basico_lae_modulo_empresas")
        for la in laes:
            la["metas"] = [dict(pm, submetas=pb_sub.get(pm.get("ID_META_PROJETO_BASICO"), []))
                           for pm in pb_metas.get(la.get("ID_QCI_ACFFO"), [])]
        vrs = P("siconv_vrpl_proposta_licitacao_modulo_empresas")
        for v in vrs:
            v["metas"] = vrpl_metas.get(v.get("ID_PROPOSTA_VRPL"), [])
            v["lotes"] = vrpl_lotes.get(v.get("ID_LICITACAO_VRPL"), [])
        aios = P("siconv_inst_cont_proposta_aio_modulo_empresas")
        for a in aios:
            k = a.get("ID_PROPOSTA_INSTRUMENTO_CONTRATUAL")
            a["contratos"] = ic_contratos.get(k, [])
            a["metas"] = ic_metas.get(k, [])
        og = um(obrasgov.get(nc, [])) if nc else None
        pi = og.get("id_projeto_investimento") if og else None
        cipi = ({"id_projeto_investimento": pi, "obrasgov": og,
                 "contratos": cipi_contratos.get(pi, []), "empenhos": cipi_empenhos.get(pi, []),
                 "execucao_fisica": cipi_exec.get(pi, [])} if pi else None)
        empenhos = C("siconv_empenho")
        arv = {
            "convenio": conv,
            "emendas": emendas,
            "indicadores": um(P("siconv_prop_inst_indicadores_municipios")),
            "historico_situacao": P("siconv_historico_situacao"),
            "projeto_basico": {
                "historico": P("siconv_historico_projeto_basico"),
                "proposta": um(P("siconv_projeto_basico_proposta_modulo_empresas")),
                "acffo": P("siconv_projeto_basico_acffo_modulo_empresas"),
                "lae": laes,
            },
            "justificativas": um(P("siconv_justificativas_proposta")),
            "metas": ms,
            "plano_aplicacao": P("siconv_plano_aplicacao_detalhado"),
            "cronograma": P("siconv_cronograma_desembolso"),
            "coordenadas": P("siconv_coordenadas_obra"),
            "resumo_fisico_financeiro": um(P("siconv_resumo_fisico_financeiro")),
            "obras": {"medicoes": meds, "vrpl": vrs, "aio": aios},
            "cipi": cipi,
            "consorcios": P("siconv_consorcios"),
            "ajustes_pt": P("siconv_solicitacao_ajuste_pt"),
            "empenhos": empenhos,
            "desembolsos": ds,
            "tributos": C("siconv_pagamento_tributo"),
            "aditivos": C("siconv_termo_aditivo"),
            "prorrogacoes": C("siconv_prorroga_oficio"),
            "solicitacoes_alteracao": C("siconv_solicitacao_alteracao"),
            "contrapartida": C("siconv_ingresso_contrapartida"),
            "rendimentos": C("siconv_solicitacao_rendimento_aplicacao"),
            "desbloqueios": C("siconv_desbloqueio_cr"),
            "desbloqueio_recurso": um(C("siconv_desbloqueio_recurso_cr")),
        }
        c.arvores[idp] = arv
        if conv:
            # ⚠️ So com convenio: sem instrumento nao ha NE nem desembolso a
            # afirmar, e a coluna fica como estava (NULO = "nao ha o que ler").
            # Arquivo que falhou tambem nao afirma nada: a coluna fica.
            if "siconv_empenho" not in c.arquivos_falhos:
                c.notas_empenho[idp] = [_ne_registro(e) for e in empenhos if _e_ne_real(e)]
            if "siconv_desembolso" not in c.arquivos_falhos:
                c.ops_obs[idp] = ops_obs_do_dump(conv, ds)

    c.chaves_mantidas = {k for k, arqs in DEPENDE.items() if c.arquivos_falhos.intersection(arqs)}

    # 6) As listas grandes, uma secao cada.
    # ⚠️ Licitacao e pagamento entram por NR_CONVENIO. Sem o `siconv_convenio`
    # o conjunto de chaves fica VAZIO, a leitura "da certo" com zero linhas e a
    # troca APAGARIA as duas tabelas. A secao falha junto com a raiz.
    if "siconv_convenio" in c.arquivos_falhos:
        for secao in ("licitacoes", "pagamentos"):
            c.falhas[secao].append("siconv_convenio nao foi lido: sem NR_CONVENIO, nada a casar")
    else:
        _licitacoes(c, ler, prop_por_conv, propostas)
        _pagamentos(c, ler, prop_por_conv, propostas)
    _liquidacoes(c, ler, ids, propostas)
    _canceladas(c, ler, ibges)
    _data_carga(c, ler)

    # 7) O resumo, depois das tabelas (ele conta pagamentos e liquidacoes).
    pag_por_prop: dict[str, list] = defaultdict(list)
    for p in c.pagamentos:
        pag_por_prop[p["id_proposta"]].append(p)
    lic_por_prop = defaultdict(int)
    for li in c.licitacoes:
        lic_por_prop[li["id_proposta"]] += 1
    dl_por_prop = defaultdict(int)
    for d in c.liquidacoes:
        dl_por_prop[d["id_proposta"]] += 1
    secoes_ok = {s: not c.falhas[s] for s in SECOES}
    for idp, arv in c.arvores.items():
        arv["_resumo"] = resumo_da_arvore(arv, pag_por_prop.get(idp, []),
                                         lic_por_prop.get(idp, 0), dl_por_prop.get(idp, 0),
                                         secoes_ok=secoes_ok, faltam=c.chaves_mantidas)
        for k in c.chaves_mantidas:
            arv.pop(k, None)
        arv["_mantidas"] = sorted(c.chaves_mantidas)
    return c


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _licitacoes(c: Coleta, ler, prop_por_conv, propostas):
    lics = _agrupa(ler, c, "licitacoes", "siconv_licitacao", "NR_CONVENIO", set(prop_por_conv))
    if lics is None:
        return
    ids_lic = {li["ID_LICITACAO"] for ls in lics.values() for li in ls if li.get("ID_LICITACAO")}
    contratos = _agrupa(ler, c, "licitacoes", "siconv_contrato", "ID_LICITACAO", ids_lic)
    itens = _agrupa(ler, c, "licitacoes", "siconv_itens_licitacao", "ID_LICITACAO", ids_lic)
    if contratos is None or itens is None:
        return
    for nc, ls in lics.items():
        idp = prop_por_conv[nc]
        mid = propostas[idp][0]
        for li in ls:
            k = li.get("ID_LICITACAO")
            if not k:
                continue
            c.licitacoes.append({
                "mid": mid, "id_licitacao": k, "id_proposta": idp, "nr_convenio": nc,
                "numero": li.get("NR_LICITACAO"),
                "modalidade": li.get("MODALIDADE_LICITACAO") or li.get("TP_PROCESSO_COMPRA"),
                "status": li.get("STATUS_LICITACAO"),
                "data_publicacao": li.get("DATA_PUBLICACAO_LICITACAO"),
                "valor": _num(li.get("VALOR_LICITACAO")),
                "dados": _j(li), "contratos": _j(contratos.get(k, [])), "itens": _j(itens.get(k, [])),
            })


def _pagamentos(c: Coleta, ler, prop_por_conv, propostas):
    pags = _agrupa(ler, c, "pagamentos", "siconv_pagamento", "NR_CONVENIO", set(prop_por_conv))
    if pags is None:
        return
    movs = {p["NR_MOV_FIN"] for ls in pags.values() for p in ls if p.get("NR_MOV_FIN")}
    obtv = _agrupa(ler, c, "pagamentos", "siconv_obtv_convenente", "NR_MOV_FIN", movs)
    if obtv is None:
        return
    for nc, ls in pags.items():
        idp = prop_por_conv[nc]
        mid = propostas[idp][0]
        for p in ls:
            k = p.get("NR_MOV_FIN")
            if not k:
                continue
            c.pagamentos.append({
                "mid": mid, "nr_mov_fin": k, "id_proposta": idp, "nr_convenio": nc,
                "data_pagamento": p.get("DATA_PAG"), "fornecedor_doc": p.get("IDENTIF_FORNECEDOR"),
                "fornecedor_nome": p.get("NOME_FORNECEDOR"), "tipo": p.get("TP_MOV_FINANCEIRA"),
                "id_dl": p.get("ID_DL"), "valor": _num(p.get("VL_PAGO")),
                "dados": _j(p), "favorecidos": _j(obtv.get(k, [])),
            })


def _liquidacoes(c: Coleta, ler, ids, propostas):
    dls = _agrupa(ler, c, "liquidacoes", "siconv_dl", "ID_PROPOSTA", ids)
    if dls is None:
        return
    ids_dl = {d["ID_DL"] for ls in dls.values() for d in ls if d.get("ID_DL")}
    itens = _agrupa(ler, c, "liquidacoes", "siconv_itens_dl", "ID_DL", ids_dl)
    if itens is None:
        return
    for idp, ls in dls.items():
        mid = propostas[idp][0]
        for d in ls:
            k = d.get("ID_DL")
            if not k:
                continue
            c.liquidacoes.append({
                "mid": mid, "id_dl": k, "id_proposta": idp, "id_licitacao": d.get("ID_LICITACAO"),
                "id_contrato": d.get("ID_CONTRATO"), "data_emissao": d.get("DATA_DE_EMISSAO"),
                "numero": d.get("NUMERO"), "descricao": d.get("DESCRICAO"),
                "razao_social": d.get("RAZAO_SOCIAL"), "valor": _num(d.get("VALOR")),
                "status": d.get("STATUS"), "dados": _j(d), "itens": _j(itens.get(k, [])),
            })


def _canceladas(c: Coleta, ler, ibges: dict[str, int]):
    rows = _agrupa(ler, c, "canceladas", "siconv_proposta_cancelada", "COD_MUNIC_IBGE", set(ibges))
    if rows is None:
        return
    for ibge, ls in rows.items():
        for p in ls:
            if not p.get("ID_PROPOSTA"):
                continue
            nat = p.get("NATUREZA_JURIDICA")
            c.canceladas.append({
                "mid": ibges[ibge], "id_proposta": p["ID_PROPOSTA"],
                "numero": od._numero_proposta(p.get("NR_PROPOSTA")),
                "proponente": p.get("NM_PROPONENTE"), "natureza": nat,
                "municipal": municipal_ou_nulo(nat), "objeto": p.get("OBJETO_PROPOSTA"),
                "orgao": p.get("DESC_ORGAO") or p.get("DESC_ORGAO_SUP"),
                "valor": _num(p.get("VL_GLOBAL_PROP")), "dados": _j(p),
            })


def _data_carga(c: Coleta, ler):
    """`data_carga_siconv.zip`: "15/09/2026 06:34:05", horario de Brasilia."""
    try:
        for linha in ler("data_carga_siconv"):
            c.data_carga = linha.get("data_carga")
            break
    except FalhaArquivo as e:
        log.warning("  %s", e)


# ---------------------------------------------------------------------------
# Derivados: o formato do ops_obs e o resumo
# ---------------------------------------------------------------------------
def ops_obs_do_dump(conv: dict, desembolsos: list[dict]) -> dict:
    """Os desembolsos do dump no MESMO formato do `ops_obs` raspado (a tela e o
    RM leem `valor_desembolsado`, `valor_a_desembolsar`, `data_ultimo_desembolso`
    e `obs[].{numero_ob, data_emissao_ob, valor}`). Funcao PURA.

    O dump so publica desembolso EFETUADO, entao nao ha situacao de OP a ler: a
    soma e o que saiu.

    ⚠️ `QTD_DIAS_SEM_DESEMBOLSO` NAO E CONTAGEM DE DIAS: o dicionario oficial diz
    "Indicador de dias sem desembolso. Dominio: 90, 180 e 365" (e 0). E FAIXA
    ("mais de N dias"): vai como `faixa_sem_desembolso`, e quem quiser os dias
    conta da `data_ultimo_desembolso` na hora de mostrar — gravar a conta aqui
    faria a arvore mudar todo dia sem a fonte mudar."""
    total = round(sum(_num(d.get("VL_DESEMBOLSADO")) or 0.0 for d in desembolsos), 2)
    repasse = _num(conv.get("VL_REPASSE_CONV"))
    ult = _max_data([d.get("DATA_DESEMBOLSO") for d in desembolsos]) or \
        next((d.get("DT_ULT_DESEMBOLSO") for d in desembolsos if d.get("DT_ULT_DESEMBOLSO")), None)
    faixa = next((_int(d.get("QTD_DIAS_SEM_DESEMBOLSO")) for d in desembolsos
                  if d.get("QTD_DIAS_SEM_DESEMBOLSO")), None)
    return {
        "valor_total_repasse": repasse,
        "valor_desembolsado": total,
        "valor_a_desembolsar": round(repasse - total, 2) if repasse is not None else None,
        "data_ultimo_desembolso": ult,
        "faixa_sem_desembolso": faixa,
        "obs": [{"numero_ob": d.get("NR_SIAFI"), "ug_emitente": d.get("UG_EMITENTE_DH"),
                 "valor": _num(d.get("VL_DESEMBOLSADO")), "data_emissao_ob": d.get("DATA_DESEMBOLSO"),
                 "observacao": d.get("OBSERVACAO_DH")}
                for d in sorted(desembolsos, key=lambda x: _dt(x.get("DATA_DESEMBOLSO")) or datetime.min)],
        "_fonte": "dump siconv_desembolso",
    }


def resumo_da_arvore(arv: dict, pagamentos: list[dict], n_licitacoes: int, n_liquidacoes: int,
                     secoes_ok: dict | None = None, faltam: set | frozenset = frozenset()) -> dict:
    """O que a lista e o modal mostram da proposta, em numeros. Funcao PURA.

    ⚠️ NULO = NAO MEDIDO NESTA RODADA. Numero que depende de uma chave cujo
    arquivo falhou (`faltam`), ou de uma tabela cuja secao falhou (`secoes_ok`),
    sai None — zero seria afirmar "nao ha aditivo" sem ter lido os aditivos."""
    conv = arv.get("convenio") or {}
    ind = arv.get("indicadores") or {}
    ne = [e for e in arv.get("empenhos") or [] if _e_ne_real(e)]
    ds = arv.get("desembolsos") or []
    ops = ops_obs_do_dump(conv, ds) if conv and "desembolsos" not in faltam else None
    hist = sorted(arv.get("historico_situacao") or [],
                  key=lambda h: _dt(h.get("DIA_HISTORICO_SIT")) or datetime.min)
    atual = hist[-1] if hist else None
    meds = (arv.get("obras") or {}).get("medicoes") or []
    rff = arv.get("resumo_fisico_financeiro") or {}
    dias_med = [_int(m.get("QTD_DIAS_SEM_MEDICAO_ACOMPANHAMENTO_OBRA")) for m in meds]
    dias_med = [d for d in dias_med if d is not None]
    fornecedores = {p.get("fornecedor_doc") or p.get("fornecedor_nome") for p in pagamentos}
    fornecedores.discard(None)
    prorr = arv.get("prorrogacoes") or []
    ok = secoes_ok or {}

    def se(chave, valor):
        return None if chave in faltam else valor

    def tab(secao, valor):
        return valor if ok.get(secao, True) else None

    return {
        "tem_convenio": bool(conv),
        "empenhado": se("empenhos", round(sum(_num(e.get("VALOR_EMPENHO")) or 0.0 for e in ne), 2)),
        "n_empenhos": se("empenhos", len(ne)),
        "desembolsado": ops["valor_desembolsado"] if ops else None,
        "a_desembolsar": ops["valor_a_desembolsar"] if ops else None,
        "ultimo_desembolso": ops["data_ultimo_desembolso"] if ops else None,
        "faixa_sem_desembolso": ops["faixa_sem_desembolso"] if ops else None,
        "pago_fornecedores": tab("pagamentos", round(sum(p.get("valor") or 0.0 for p in pagamentos), 2)),
        "n_pagamentos": tab("pagamentos", len(pagamentos)),
        "n_fornecedores": tab("pagamentos", len(fornecedores)),
        "n_licitacoes": tab("licitacoes", n_licitacoes),
        "n_liquidacoes": tab("liquidacoes", n_liquidacoes),
        "tributos": se("tributos", round(sum(_num(t.get("VL_PAG_TRIBUTOS")) or 0.0
                                             for t in arv.get("tributos") or []), 2)),
        "vigencia_original": conv.get("DIA_FIM_VIGENC_ORIGINAL_CONV"),
        "vigencia_atual": conv.get("DIA_FIM_VIGENC_CONV"),
        "n_aditivos": se("aditivos", len(arv.get("aditivos") or [])),
        "n_prorrogacoes": se("prorrogacoes", len(prorr)),
        "dias_prorrogados": se("prorrogacoes", sum(_int(p.get("DIAS_PRORROGA")) or 0 for p in prorr)),
        "prestacao_contas_limite": conv.get("DIA_LIMITE_PREST_CONTAS"),
        "prestacao_contas_concluida": se("indicadores", ind.get("DT_CONCLUSAO_PRESTACAO_CONTAS")),
        "prestacao_contas_aprovada": se("indicadores", ind.get("DT_APROVACAO_PRESTACAO_CONTAS")),
        "cumprimento_objeto": se("indicadores", ind.get("CUMPRIMENTO_OBJETO")),
        "contrapartida_devida": _num(conv.get("VL_CONTRAPARTIDA_CONV")),
        "contrapartida_depositada": se("contrapartida", round(
            sum(_num(i.get("VL_INGRESSO_CONTRAPARTIDA")) or 0.0
                for i in arv.get("contrapartida") or []), 2)),
        "saldo_conta": _num(conv.get("VL_SALDO_CONTA")),
        "rendimento_aplicacao": _num(conv.get("VL_RENDIMENTO_APLICACAO")),
        "execucao_fisica_pct": se("resumo_fisico_financeiro",
                                  _num(rff.get("PERCENTUAL_EXECUCAO_RESUMO_FISICO_FINANCEIRO"))),
        "n_medicoes": se("obras", len(meds)),
        "dias_sem_medicao": se("obras", min(dias_med) if dias_med else None),
        "situacao_atual": se("historico_situacao", atual.get("HISTORICO_SIT") if atual else None),
        "situacao_desde": se("historico_situacao", atual.get("DIA_HISTORICO_SIT") if atual else None),
        "id_projeto_investimento": se("cipi", (arv.get("cipi") or {}).get("id_projeto_investimento")),
        "n_emendas": se("emendas", len(arv.get("emendas") or [])),
        "n_metas": se("metas", len(arv.get("metas") or [])),
        "n_itens_plano": se("plano_aplicacao", len(arv.get("plano_aplicacao") or [])),
    }


# ---------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------
# ⚠️ SO GRAVA O QUE MUDOU. A carga e diaria e quase tudo se repete de um dia
# para o outro; reescrever 7 mil arvores e 460 mil linhas iguais toda noite (a
# carteira da Trust) seria MVCC e WAL a troco de nada. `||` mescla por chave de
# topo: a chave que ficou fora da rodada (arquivo falhou, `_mantidas`) mantem o
# valor anterior.
_SQL_ARVORE = """
UPDATE transferegov_propostas p
   SET arvore = COALESCE(p.arvore, '{}'::jsonb) || v.arv,
       arvore_atualizado_em = NOW(),
       notas_empenho_aberto = COALESCE(v.ne, p.notas_empenho_aberto),
       notas_empenho_aberto_atualizado_em = CASE WHEN v.ne IS NULL
            THEN p.notas_empenho_aberto_atualizado_em ELSE NOW() END,
       ops_obs_aberto = COALESCE(v.ops, p.ops_obs_aberto)
  FROM (VALUES %s) AS v(mid, idp, arv, ne, ops)
 WHERE p.municipio_id = v.mid AND p.id_proposta_siconv = v.idp
   AND (p.arvore IS DISTINCT FROM COALESCE(p.arvore, '{}'::jsonb) || v.arv
        OR (v.ne IS NOT NULL AND p.notas_empenho_aberto IS DISTINCT FROM v.ne)
        OR (v.ops IS NOT NULL AND p.ops_obs_aberto IS DISTINCT FROM v.ops))
RETURNING 1
"""

# secao -> (tabela, coluna da chave do dump, [(campo da linha, coluna, cast)])
_TABELAS: dict[str, tuple[str, str, list[tuple[str, str, str]]]] = {
    "licitacoes": ("tg_licitacoes", "id_licitacao", [
        ("id_proposta", "id_proposta", ""), ("nr_convenio", "nr_convenio", ""),
        ("numero", "numero", ""), ("modalidade", "modalidade", ""), ("status", "status", ""),
        ("data_publicacao", "data_publicacao", ""), ("valor", "valor", ""),
        ("dados", "dados", "::jsonb"), ("contratos", "contratos", "::jsonb"),
        ("itens", "itens", "::jsonb")]),
    "pagamentos": ("tg_pagamentos", "nr_mov_fin", [
        ("id_proposta", "id_proposta", ""), ("nr_convenio", "nr_convenio", ""),
        ("data_pagamento", "data_pagamento", ""), ("fornecedor_doc", "fornecedor_doc", ""),
        ("fornecedor_nome", "fornecedor_nome", ""), ("tipo", "tipo", ""), ("id_dl", "id_dl", ""),
        ("valor", "valor", ""), ("dados", "dados", "::jsonb"),
        ("favorecidos", "favorecidos", "::jsonb")]),
    "liquidacoes": ("tg_documentos_liquidacao", "id_dl", [
        ("id_proposta", "id_proposta", ""), ("id_licitacao", "id_licitacao", ""),
        ("id_contrato", "id_contrato", ""), ("data_emissao", "data_emissao", ""),
        ("numero", "numero", ""), ("descricao", "descricao", ""),
        ("razao_social", "razao_social", ""), ("valor", "valor", ""), ("status", "status", ""),
        ("dados", "dados", "::jsonb"), ("itens", "itens", "::jsonb")]),
    "canceladas": ("tg_propostas_canceladas", "id_proposta", [
        ("numero", "numero_proposta", ""), ("proponente", "proponente", ""),
        ("natureza", "natureza_juridica", ""), ("municipal", "municipal", ""),
        ("objeto", "objeto", ""), ("orgao", "orgao", ""), ("valor", "valor_global", ""),
        ("dados", "dados", "::jsonb")]),
}
# O nome do campo da CHAVE na linha montada pelo coletor, por secao.
_CHAVE_NA_LINHA = {"licitacoes": "id_licitacao", "pagamentos": "nr_mov_fin",
                   "liquidacoes": "id_dl", "canceladas": "id_proposta"}


def _troca_tabela(conn, secao: str, linhas: list[dict], mids: list[int]) -> dict:
    """Deixa a tabela IGUAL ao dump para os municipios da carteira, numa
    transacao: insere o novo, atualiza SO o que mudou e apaga o que saiu da
    fonte. Chamada so com a secao lida INTEIRA — secao que falhou nunca apaga."""
    from psycopg2.extras import execute_values
    tabela, chave, campos = _TABELAS[secao]
    k_linha = _CHAVE_NA_LINHA[secao]
    unicas = {(li["mid"], li[k_linha]): li for li in linhas}     # defensivo: 1 por chave
    cols = ", ".join(["municipio_id", chave] + [col for _, col, _ in campos])
    tpl = "(" + ", ".join(["%s", "%s"] + [f"%s{cast}" for _, _, cast in campos]) + ")"
    sets = ", ".join(f"{col} = EXCLUDED.{col}" for _, col, _ in campos)
    velhos = ", ".join(f"t.{col}" for _, col, _ in campos)
    novos = ", ".join(f"EXCLUDED.{col}" for _, col, _ in campos)
    sql = (f"INSERT INTO {tabela} AS t ({cols}) VALUES %s "
           f"ON CONFLICT (municipio_id, {chave}) DO UPDATE SET {sets}, atualizado_em = NOW() "
           f"WHERE ({velhos}) IS DISTINCT FROM ({novos}) "
           f"RETURNING (xmax = 0) AS inserida")
    cur = conn.cursor()
    try:
        if not unicas:
            # Carteira inteira sem uma linha, e a tabela com linhas: e a chave
            # que deixou de casar (id_proposta_siconv mudou de formato, p.ex.),
            # nao o municipio que parou de pagar. Nada e apagado.
            cur.execute(f"SELECT count(*) FROM {tabela} WHERE municipio_id = ANY(%s)", (mids,))
            if (cur.fetchone() or [0])[0]:
                raise FalhaArquivo(f"{secao}: nenhuma linha casou com a carteira e a tabela tem "
                                   f"linhas — nada apagado")
        tocadas = []
        if unicas:
            tocadas = execute_values(
                cur, sql, [(li["mid"], li[k_linha], *(li[f] for f, _, _ in campos))
                           for li in unicas.values()],
                template=tpl, page_size=1000, fetch=True)
        cur.execute("CREATE TEMP TABLE _tg_chaves (mid INTEGER, k TEXT) ON COMMIT DROP")
        if unicas:
            execute_values(cur, "INSERT INTO _tg_chaves (mid, k) VALUES %s", list(unicas),
                           page_size=5000)
        cur.execute(f"DELETE FROM {tabela} t WHERE t.municipio_id = ANY(%s) AND NOT EXISTS "
                    f"(SELECT 1 FROM _tg_chaves c WHERE c.mid = t.municipio_id AND c.k = t.{chave})",
                    (mids,))
        apagadas = cur.rowcount
        conn.commit()
        novas = sum(1 for (ins,) in tocadas if ins)
        return {"total": len(unicas), "novas": novas, "mudaram": len(tocadas) - novas,
                "apagadas": apagadas}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def grava(conn, c: Coleta, propostas: dict[str, tuple[int, str | None]]) -> dict:
    from psycopg2.extras import execute_values
    gravado: dict = {}
    mids = sorted({mid for mid, _ in propostas.values()})
    if "siconv_convenio" not in c.arquivos_falhos:
        linhas = []
        for idp, arv in c.arvores.items():
            ne = c.notas_empenho.get(idp)
            ops = c.ops_obs.get(idp)
            linhas.append((propostas[idp][0], idp, _j(arv),
                           _j(ne) if ne is not None else None,
                           _j(ops) if ops is not None else None))
        cur = conn.cursor()
        try:
            mudou = execute_values(cur, _SQL_ARVORE, linhas,
                                   template="(%s::int, %s::text, %s::jsonb, %s::jsonb, %s::jsonb)",
                                   page_size=200, fetch=True)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
        gravado["arvore"] = {"total": len(linhas), "mudaram": len(mudou)}
    for secao, linhas in (("licitacoes", c.licitacoes), ("pagamentos", c.pagamentos),
                          ("liquidacoes", c.liquidacoes)):
        if not c.falhas[secao]:
            gravado[secao] = _troca_tabela(conn, secao, linhas, mids)
    # As canceladas entram por IBGE, nao pela carteira: municipio sem nenhuma
    # proposta viva ainda pode ter cancelada.
    if not c.falhas["canceladas"]:
        gravado["canceladas"] = _troca_tabela(conn, "canceladas", c.canceladas, c.mids_ibge)
    return gravado


def _grava_data_carga(conn, data_carga: str | None) -> None:
    """`fonte_atualizacao` com a chave `transferegov_discricionarias`. A data vem
    em horario de Brasilia, sem fuso."""
    d = _dt(data_carga)
    if not d:
        return
    d = d.replace(tzinfo=timezone(timedelta(hours=-3)))
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO fonte_atualizacao (fonte, data_fonte, consultado_em) "
            "VALUES ('transferegov_discricionarias', %s, NOW()) "
            "ON CONFLICT (fonte) DO UPDATE SET data_fonte = EXCLUDED.data_fonte, "
            "consultado_em = NOW()", (d,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("fonte_atualizacao falhou: %s", str(e)[:120])
    finally:
        cur.close()


def _carteira(cur) -> tuple[dict[str, tuple[int, str | None]], dict[str, int]]:
    """As propostas no banco dos municipios ATIVOS, e os IBGEs deles."""
    cur.execute("""
        SELECT p.id_proposta_siconv, p.municipio_id,
               regexp_replace(coalesce(p.identificacao, ''), '\\D', '', 'g')
          FROM transferegov_propostas p
          JOIN municipios m ON m.id = p.municipio_id AND m.active
         WHERE p.id_proposta_siconv IS NOT NULL AND p.id_proposta_siconv <> ''
    """)
    props = {}
    for idp, mid, cnpj in cur.fetchall():
        props.setdefault(str(idp), (mid, cnpj or None))
    cur.execute("SELECT ibge_code, id FROM municipios WHERE active AND length(coalesce(ibge_code,'')) = 7")
    return props, {str(i): mid for i, mid in cur.fetchall()}


def _log_ingest(conn, status: str, n: int, erro: str | None = None,
                inicio: datetime | None = None) -> None:
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO ingestion_log (source, status, records_inserted, error_message, "
                    "started_at, finished_at) VALUES (%s, %s, %s, %s, COALESCE(%s, NOW()), NOW())",
                    (FONTE, status, n, (erro or "")[:500] or None, inicio))
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.warning("ingestion_log falhou: %s", str(e)[:120])
    finally:
        cur.close()


def status_da_coleta(c: Coleta, gravado: dict) -> tuple[str, int, str | None]:
    """UMA linha no `ingestion_log` para a rodada: (status, gravados, erro).

    success  tudo lido inteiro;
    partial  algum arquivo falhou — diz qual, e o que ficou como estava;
    error    nada foi trocado (a raiz `siconv_convenio` falhou e nenhuma tabela
             foi lida inteira)."""
    falhas = {s: f for s, f in c.falhas.items() if f}
    n = int((gravado.get("arvore") or {}).get("total") or 0)
    if not falhas:
        return "success", n, None
    trocou = bool(gravado)
    detalhe = "; ".join(f"{s}: {f[0]}" + (f" (+{len(f) - 1})" if len(f) > 1 else "")
                        for s, f in falhas.items())
    if c.chaves_mantidas and "siconv_convenio" not in c.arquivos_falhos:
        detalhe += f" | arvore trocada sem: {', '.join(sorted(c.chaves_mantidas))}"
    if not trocou:
        return "error", 0, "nada trocado: " + detalhe
    return "partial", n, detalhe


def ingest() -> int:
    from datetime import datetime as _dtm
    from ingestion._resilience import get_sync_db_url, neon_connect

    t0 = time.time()
    inicio = datetime.now(timezone.utc)
    # 5 min por statement: a troca de uma tabela de 200 mil linhas e um DELETE
    # com NOT EXISTS so; o padrao de 60 s do `neon_connect` e para consulta.
    with neon_connect(get_sync_db_url(), statement_timeout_ms=300000) as conn:
        cur = conn.cursor()
        if os.getenv("TG_ARVORE_FORCE") != "1":
            cur.execute("SELECT max(finished_at) FROM ingestion_log "
                        "WHERE source = %s AND status IN ('success','ok')", (FONTE,))
            ultimo = (cur.fetchone() or [None])[0]
            if ultimo and (_dtm.now(ultimo.tzinfo) - ultimo).total_seconds() / 3600 < MIN_INTERVAL_H:
                log.info("ultima rodada ha menos de %.0fh — pulando. TG_ARVORE_FORCE=1 forca.",
                         MIN_INTERVAL_H)
                return 0
        propostas, ibges = _carteira(cur)
        cur.close()
        # ⚠️ Fecha a transacao da leitura ANTES dos 5 min de coleta. Aberta, a
        # conexao fica "idle in transaction" segurando o vacuum, e o NOW() da
        # gravacao sairia com a hora do SELECT (medido no e2e: 7 min antes).
        conn.rollback()
        if not propostas:
            log.warning("nenhuma proposta com id_proposta_siconv na carteira — rode antes o "
                        "transferegov_opendata")
            _log_ingest(conn, "success", 0, "carteira vazia")
            return 0
        log.info("arvore: %d proposta(s) de %d municipio(s)", len(propostas), len(ibges))
        try:
            c = coleta(propostas, ibges)
            log.info("coleta em %.0fs — %d licitacao(oes), %d pagamento(s), %d liquidacao(oes), "
                     "%d cancelada(s)", time.time() - t0, len(c.licitacoes), len(c.pagamentos),
                     len(c.liquidacoes), len(c.canceladas))
            gravado = grava(conn, c, propostas)
            _grava_data_carga(conn, c.data_carga)
            status, n, erro = status_da_coleta(c, gravado)
            log.info("=== arvore: %s em %.0fs — %s%s", status, time.time() - t0, gravado,
                     f" | {erro}" if erro else "")
            _log_ingest(conn, status, n, erro, inicio)
            return n
        except Exception as e:
            conn.rollback()
            log.error("arvore falhou: %s: %s", type(e).__name__, str(e)[:200])
            _log_ingest(conn, "error", 0, f"{type(e).__name__}: {str(e)[:300]}", inicio)
            raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ingest()
