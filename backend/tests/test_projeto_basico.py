"""Projeto Basico / Termo de Referencia — parser e exibicao no RM.

O HTML da fixture NAO foi inventado: e a estrutura lida ao vivo em 18/08/2026 na
aba "Projeto Básico/Termo de Referência" do convenio 981397 (Araujos, proposta
2124094), com as duas pegadinhas do portal preservadas de proposito:

  1. o cabecalho "Tipo" vem com class="dataUpload" (o portal reusa a classe
     errada) — por isso o parser mapeia por TEXTO do cabecalho, nunca por classe;
  2. a linha traz colunas de acao a mais no fim (DETALHAR/BAIXAR) — por isso o
     mapeamento e por indice-de-cabecalho, nunca por posicao fixa.
"""
import httpx

from ingestion.transferegov_http import TgHttpEnrich
from services.rm_builder import _projeto_basico_resumo
from services.rm_pdf import _clausula_destaque


_HTML_REAL = """
<html><body>
  <table>
    <tr><td class="FormLinhaBotoes"></td><td></td></tr>
    <tr><td class="label">Situação</td><td class="field">Em Análise</td></tr>
  </table>
  <table>
    <tr>
      <th class="nomeArquivo">Nome Arquivo</th>
      <th class="descricao">Descricao</th>
      <th class="dataUpload">Tipo</th>
      <th class="dataUpload">Data Upload</th>
      <th></th><th></th><th></th>
    </tr>
    <tr>
      <td>TERMO DE REFER&Ecirc;NCIA - ARA&Uacute;JOS - ESPORTE.pdf</td>
      <td>Termo de Refer&ecirc;ncia</td>
      <td>Termo Refer&ecirc;ncia</td>
      <td>17/06/2026</td>
      <td></td><td>DETALHAR</td><td>BAIXAR</td>
    </tr>
  </table>
</body></html>
"""

# A parede do SP SAML `execucao`: 200, corpo com "Post Binding". Medida em
# 3469 bytes, identica a do _LIC_URL.
_HTML_SAML = """
<html><body><p>HTTP Post Binding</p>
<form><input name="SAMLResponse" value="x"/></form></body></html>
"""


def _resp(html: str) -> httpx.Response:
    return httpx.Response(200, text=html)


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------
def test_le_situacao_e_documento():
    out = TgHttpEnrich._le_projeto_basico(_resp(_HTML_REAL))
    assert out is not None
    assert out["situacao"] == "Em Análise"
    assert len(out["documentos"]) == 1
    doc = out["documentos"][0]
    assert doc["descricao"] == "Termo de Referência"
    assert doc["tipo"] == "Termo Referência"
    assert doc["data_upload"] == "17/06/2026"
    assert doc["nome_arquivo"].endswith(".pdf")


def test_colunas_de_acao_nao_viram_documento():
    """DETALHAR/BAIXAR estao na mesma linha; nao podem virar campo nem linha nova."""
    out = TgHttpEnrich._le_projeto_basico(_resp(_HTML_REAL))
    assert len(out["documentos"]) == 1
    assert "DETALHAR" not in str(out["documentos"][0].values())


def test_pagina_saml_nao_vira_dado():
    """A parede do SP frio devolve 200. Se virasse {} o upsert gravaria
    'consultado e vazio' por cima de uma captura boa."""
    assert TgHttpEnrich._le_projeto_basico(_resp(_HTML_SAML)) is None


def test_pagina_sem_situacao_nem_anexo_e_indeterminada():
    assert TgHttpEnrich._le_projeto_basico(_resp("<html><body>nada</body></html>")) is None


def test_situacao_sem_anexo_ainda_vale():
    html = ('<html><table><tr><td class="label">Situação</td>'
            '<td class="field">Em Análise</td></tr></table></html>')
    out = TgHttpEnrich._le_projeto_basico(_resp(html))
    assert out == {"situacao": "Em Análise", "documentos": []}


# --------------------------------------------------------------------------
# Resumo para o RM
# --------------------------------------------------------------------------
def test_resumo_junta_documento_e_situacao():
    pb = {"situacao": "Em Análise",
          "documentos": [{"descricao": "Termo de Referência", "tipo": "Termo Referência"}]}
    assert _projeto_basico_resumo(pb) == "Termo de Referência — Em Análise"


def test_resumo_aceita_jsonb_como_texto():
    """Dependendo do driver o JSONB chega como str — nao pode virar linha vazia."""
    assert _projeto_basico_resumo(
        '{"situacao": "Em Análise", "documentos": []}') == "Em Análise"


def test_resumo_vazio_quando_nao_ha_captura():
    assert _projeto_basico_resumo(None) == ""
    assert _projeto_basico_resumo({}) == ""


# --------------------------------------------------------------------------
# Exibicao no PDF
# --------------------------------------------------------------------------
def test_pdf_mostra_o_status_do_documento_na_caixa_da_clausula():
    """O pedido do dono: com clausula suspensiva, o RM diz QUAL documento trava
    (motivo) E em que pe ele esta (situacao)."""
    txt = _clausula_destaque({
        "situacao_contratacao": "Cláusula Suspensiva",
        "clausula_motivo": "Termo de Referência",
        "projeto_basico": "Termo de Referência — Em Análise",
    })
    assert "Motivo:" in txt
    assert "Em Análise" in txt


def test_pdf_omite_a_linha_quando_nao_houve_captura():
    """Sessao fria devolve None -> string vazia -> o RM nao inventa linha."""
    txt = _clausula_destaque({
        "situacao_contratacao": "Cláusula Suspensiva",
        "clausula_motivo": "Termo de Referência",
        "projeto_basico": "",
    })
    assert "Projeto Básico" not in txt
