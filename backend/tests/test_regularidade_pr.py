"""Regularidade do PR — as certidões da SEFA e do TCE-PR (medidas em 22/09/2026)."""
from datetime import date

import pytest

from ingestion import regularidade_pr as r
from services import cadastro_estadual as ce

# Recortes das páginas reais de Juranda (texto já sem as tags).
SEFA_OK = ("Certidões exigidas pela Lei de Responsabilidade Fiscal Estado do Paraná "
           "Secretaria de Estado da Fazenda Diretoria do Tesouro do Estado - DTE "
           "Certidão Negativa para Transferências Voluntárias Nº 00069059 Dados do "
           "Município: Prefeitura Municipal de Juranda Endereço: Zenóvio Szeremeta , "
           "1713 ... Esta Certidão tem validade até 20 de outubro de 2026 Estado do "
           "Paraná ... Certidão Nº 00069059 Emitida Eletronicamente via Internet "
           "21/08/2026 Dados transmitidos de forma segura Tecnologia CELEPAR")
TCE_OK = ("Verificação de pendências para Certidão Liberatória Entidade "
          "78.196.755/0001-09 Data 22/09/2026 07:46:57 Resultado A entidade não "
          "possui pendências para emissão da Certidão Liberatória.")


def test_certidao_da_sefa_vigente():
    item = r.le_certidao_sefa(SEFA_OK, date(2026, 9, 22))
    assert item["tipo"] == "regular" and item["status"] == "Vigente"
    assert item["valor"] == "Nº 00069059"
    # dd/mm/aaaa, a regra do CHE: a tela e o alerta de vencimento só leem isso.
    assert item["validade"] == "20/10/2026"
    assert item["detalhe"]["emitida_em"] == "21/08/2026"


def test_certidao_da_sefa_vencida_vira_pendente():
    item = r.le_certidao_sefa(SEFA_OK, date(2026, 10, 21))
    assert item["tipo"] == "pendente" and item["status"] == "Vencida"


def test_sefa_com_negativa_explicita_e_pendente():
    item = r.le_certidao_sefa("Não foi possível emitir a certidão: o município "
                              "possui pendências junto ao Estado.", date(2026, 9, 22))
    assert item["tipo"] == "pendente" and item["valor"] == "Não emitida"


def test_sefa_em_formato_desconhecido_nao_vira_irregular():
    """Armadilha 4: página que não se entende é falha de LEITURA."""
    with pytest.raises(r.FormatoDesconhecido):
        r.le_certidao_sefa("Serviço temporariamente indisponível", date(2026, 9, 22))


def test_liberatoria_sem_pendencias():
    item = r.le_liberatoria(TCE_OK)
    assert item["tipo"] == "regular" and item["valor"] == "Sem pendências"
    assert item["validade"] is None


def test_liberatoria_com_pendencias():
    txt = TCE_OK.replace("não possui", "possui")
    assert r.le_liberatoria(txt)["tipo"] == "pendente"


def test_o_titulo_da_pagina_nao_acusa_pendencia():
    """O título diz "Verificação de pendências" — sem o bloco Resultado, falha
    de leitura, e não "Com pendências"."""
    with pytest.raises(r.FormatoDesconhecido):
        r.le_liberatoria("Verificação de pendências para Certidão Liberatória "
                         "Entidade 78.196.755/0001-09")


def test_codigo_da_sefa_sai_pelo_cnpj_do_select():
    html = ('<select name="codMunicipio" id="codMunicipio">'
            '<option value = "522">Jundiaí do Sul   - CNPJ nº: 76.408.061/0001-54</option>'
            '<option value = "844">Juranda          - CNPJ nº: 78.196.755/0001-09</option>'
            '</select>')
    cods = r.codigos_sefa(html)
    assert cods["78196755000109"] == ["844"]
    assert cods["76408061000154"] == ["522"]


def test_linha_resume_as_duas_certidoes():
    hoje = date(2026, 9, 22)
    itens = [r.le_certidao_sefa(SEFA_OK, hoje), r.le_liberatoria(TCE_OK)]
    alvo = {"id": 1, "nome": "Juranda", "cnpj14": "78196755000109",
            "nome_entidade": "Prefeitura Municipal de Juranda"}
    ln = r.linha(alvo, itens, hoje, {})
    assert ln["regular"] is True and ln["situacao"] == "Em dia"
    assert ln["cnpj"] == "78.196.755/0001-09"
    assert str(ln["validade"]) == "2026-10-20"      # a da SEFA; a Liberatória não tem
    itens[1] = r.le_liberatoria(TCE_OK.replace("não possui", "possui"))
    ln = r.linha(alvo, itens, hoje, {})
    assert ln["regular"] is False and ln["pend_cods"] == ["PR-TCE-LIB"]


def test_o_pr_entra_no_catalogo_de_cadastro_estadual():
    assert "PR" in ce.UFS_COM_CADASTRO_COLETADO
    assert ce.uf_da_fonte(r.FONTE) == "PR"
    assert ce.sigla_da_uf("PR") == "Certidões do Estado"
