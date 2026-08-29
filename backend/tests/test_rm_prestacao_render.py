"""A prestação de contas do SIGCON SAI NO DOCUMENTO — PDF e Word, ponta a ponta.

Pedido do dono (29/08/2026): "as informações do sigcon deve sair no relatório tb
e valide e teste veja se está atualizando corretamente".

⚠️ OS VALORES AQUI SÃO OS DE PRODUÇÃO, lidos do banco do Freitas em 29/08/2026 —
não são inventados. Os cinco status são os cinco distintos que o portal gravou; o
SEI e as datas são de convênios reais (Japaraíba / São Brás do Suaçuí / Perdigão).
Testar com valor bonito inventado é o que já deixou passar o `"*"` e o
"Cancelar Histórico Status": o parser ia bem contra o texto que EU escrevia.

E este teste não olha o dicionário do item: ele RENDERIZA o PDF e lê o texto de
volta. Entre o item e o papel há `roteiro_rm`, o escape de HTML e o ReportLab —
afirmar "o campo está no dict" não prova que o gestor vai ler o número na página.
"""
import io

import pytest

from services.rm_builder import _prestacao_contas_campos
from services.rm_pdf import gerar_pdf
from services.rm_docx import gerar_docx_rm

META = {"data_referencia": None, "cidade_emissao": "Brasília",
        "titulo": "RELATÓRIO DE MONITORAMENTO – ARAÚJOS/MG",
        "rodape": "Setor SHS Quadra 6 — Brasília/DF.", "escopo": "completo",
        "fontes": [], "email": "alfredo@freitaseassociados.com.br", "estagio": ""}

# raw_data como o `_scrape_prestacao_contas` grava (medido em produção).
RAW_PROD = {
    "prestacao_contas_status": "Prestação de contas aprovada com ressalvas",
    "prestacao_contas_status_data": "03/04/2025",
    "prestacao_contas_data": "18/02/2025",
    "prestacao_contas_sei": "1500.01.0069235/2025-73",
}


def _conteudo(raw: dict) -> dict:
    """Monta o `conteudo` como `montar_conteudo` monta para um convênio estadual —
    passando pelo MESMO `_prestacao_contas_campos` que o builder usa."""
    item = {
        "tipo": "Convênio", "numero": "1231000691/2026",
        "objeto": "Aquisição de retroescavadeira",
        "situacao_atual": "Em vigor", "situacao_base": "Em vigor",
        "valor_global": 450000.0, "fonte": "sigcon",
        **_prestacao_contas_campos(raw),
    }
    return {"partes": [{"ordem": 2, "titulo": "PARTE 2 - DEMANDAS DO MUNICÍPIO",
                        "secoes": [{"ordem": 1, "titulo": "INSTRUMENTOS ESTADUAIS",
                                    "grupos": [{"ordem": 1, "orgao": "SEAPA",
                                                "itens": [item]}]}]}]}


def _texto_pdf(b: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(b)).pages)


def _texto_docx(b: bytes) -> str:
    import zipfile
    import re as _re
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return _re.sub(r"<[^>]+>", "", xml)


# --------------------------------------------------------------- o PDF -----
def test_o_PDF_imprime_status_SEI_e_as_duas_datas():
    """A prova que interessa: os quatro campos legíveis na página."""
    t = _texto_pdf(gerar_pdf(META, _conteudo(RAW_PROD), "Araújos/MG"))
    assert "Prestação de contas" in t
    assert "1500.01.0069235/2025-73" in t, "o nº SEI tem de sair no papel"
    assert "18/02/2025" in t and "03/04/2025" in t, "as DUAS datas"


def test_o_PDF_ROTULA_qual_data_e_qual():
    """⚠️ Sem rótulo, "03/04 · 18/02" não diz qual é a entrega do município e qual
    é o carimbo do Estado — e a leitura natural (a primeira é a principal) é
    justamente a errada."""
    t = _texto_pdf(gerar_pdf(META, _conteudo(RAW_PROD), "Araújos/MG"))
    assert "apresentada em 18/02/2025" in t
    assert "status preenchido em 03/04/2025" in t


def test_o_numero_do_SEI_sai_INTEIRO_e_nao_reescrito():
    """O normalizador de caixa do RM não pode tocar num número de processo."""
    t = _texto_pdf(gerar_pdf(META, _conteudo(RAW_PROD), "Araújos/MG"))
    assert "1500.01.0069235/2025-73" in t
    assert "1500.01.0069235/2025-7 3" not in t


# --------------------------------------------------------------- o WORD ----
def test_o_WORD_sai_igual_ao_PDF():
    """⚠️ `roteiro_rm` é a única fonte de verdade da apresentação: PDF e Word são
    dois CONSUMIDORES. Se o Word divergir, alguém decidiu conteúdo fora do
    roteiro — que é exatamente o que o desenho proíbe."""
    t = _texto_docx(gerar_docx_rm(META, _conteudo(RAW_PROD), "Araújos/MG"))
    assert "1500.01.0069235/2025-73" in t
    assert "apresentada em 18/02/2025" in t


# ------------------------------------- o CONVÊNIO SEM prestação de contas --
def test_convenio_SEM_a_secao_nao_ganha_caixa_nenhuma():
    """⚠️ O caso do Araújos, medido em produção: 0 convênios com nº SEI. A caixa
    NÃO pode aparecer vazia — o campo com este nome já foi removido do sistema uma
    vez por desenhar "-" em 894 de 894 linhas."""
    t = _texto_pdf(gerar_pdf(META, _conteudo({}), "Araújos/MG"))
    assert "Prestação de contas" not in t
    assert "sem status informado" not in t


def test_SO_o_status_ja_rende_a_caixa_sem_inventar_o_resto():
    """O caso REAL do Araújos: o portal informa o status e deixa SEI e datas em
    branco. A caixa sai com o status e CALA sobre o resto — não escreve "-"."""
    t = _texto_pdf(gerar_pdf(
        META, _conteudo({"prestacao_contas_status": "Instrumento cancelado sem repasse de recursos"}),
        "Araújos/MG"))
    assert "Instrumento cancelado sem repasse de recursos" in t
    assert "Nº SEI" not in t
    assert "apresentada em" not in t


# ------------------------------------------------- ATUALIZAÇÃO (o pedido) --
@pytest.mark.parametrize("status", [
    "Aguardando análise da prestação de contas final",
    "Instrumento cancelado sem repasse de recursos",
    "Prestação de contas aprovada",
    "Prestação de contas aprovada com ressalvas",
    "Prestação de contas em análise técnica e/ou financeira",
])
def test_os_CINCO_status_reais_do_portal_saem_no_papel(status):
    """Os cinco valores distintos que a coleta gravou em produção. Se o portal
    mudar o status de um convênio, é ESTE texto que troca no documento."""
    t = _texto_pdf(gerar_pdf(META, _conteudo({"prestacao_contas_status": status}),
                             "Araújos/MG"))
    assert status in t


def test_a_ATUALIZACAO_troca_o_texto_do_documento():
    """"Está atualizando corretamente?" — o documento é reconstruído a partir do
    `raw_data` de HOJE. Status novo => papel novo.

    ⚠️ E é por isso que um RM já emitido NÃO muda sozinho: o PDF sai do JSONB
    CONGELADO em `rm_relatorios.conteudo` (routers/rm.py: `conteudo = row[4]`).
    Atualizar a coleta não reescreve relatório antigo — tem de repopular ou gerar
    um novo. Esta é a pegadinha que fez a prestação de contas "não aparecer"."""
    antes = _texto_pdf(gerar_pdf(META, _conteudo(
        {"prestacao_contas_status": "Prestação de contas em análise técnica e/ou financeira"}),
        "Araújos/MG"))
    depois = _texto_pdf(gerar_pdf(META, _conteudo(
        {"prestacao_contas_status": "Prestação de contas aprovada"}), "Araújos/MG"))
    assert "em análise técnica" in antes and "em análise técnica" not in depois
    assert "Prestação de contas aprovada" in depois
