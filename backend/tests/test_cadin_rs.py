"""O leitor da certidão do CADIN/CFIL do RS — onde um erro pinta de verde quem está travado.

O coletor decide três coisas a partir de um PDF: se consta pendência, quantas, e
quem inscreveu. As três frases vêm dos PDFs REAIS emitidos em 07/09/2026 para
Nova Palma (certidão limpa) e para o Fundo Municipal de Saúde de Nova Palma (uma
pendência, incluída em 28/08/2026 pela Secretaria Estadual da Saúde).

⚠️ O TESTE QUE MOTIVOU O ARQUIVO é `test_pendencia_com_numero_no_meio`. A primeira
versão do padrão exigia "consta(m) pend..." colado e a certidão real diz
"consta **1 pendência** para a pessoa em epígrafe" — o único caso com pendência da
carteira foi classificado como `indeterminado` e a pendência quase se perdeu.
Padrão testado só contra certidão limpa não foi testado.

Rodar:
    python -m pytest backend/tests/test_cadin_rs.py -v
"""
import pytest

from ingestion.cadin_rs import (
    _classifica,
    _data_da_certidao,
    _detalhes_da_inscricao,
    _razao_social,
)

# Texto extraído do PDF real (certidão sem pendência).
LIMPA = (
    "Certidão CADIN/RS CNPJ(Raiz): 88.488.358 Razão Social: MUNICIPIO DE NOVA PALMA "
    "Certificamos que, na data de 07/09/2026 , não constam pendências para a pessoa "
    "em epígrafe no sistema Cadastro Informativo das Pendências perante Órgãos e "
    "Entidades da Administração Pública Estadual (CADIN/RS) de que trata a Lei 10.697 "
    "de 12 de janeiro de 1996 . Porto Alegre, 07 de setembro de 2026 às 16:53:53"
)

# Texto extraído do PDF real (certidão COM pendência) — repare no quadro que vem
# antes da frase, e no número no meio dela.
COM_PENDENCIA = (
    "Entidade Administração Direta / Indireta CNPJ Data Inclusão CADIN Quantidade "
    "Pendências Contato para demais Informações SECRETARIA DA SAUDE / FUNDO ESTADUAL "
    "DE SAUDE 12240183000100 28/08/2026 1 (51) 3288 5861 - fiscalizacao- "
    "ses@saude.rs.gov.br Certidão CADIN/RS Certificamos que, na data de 07/09/2026 , "
    "consta 1 pendência para a pessoa em epígrafe no sistema Cadastro Informativo das "
    "Pendências perante Órgãos e Entidades da Administração Pública Estadual (CADIN/RS) "
    "de que trata a Lei 10.697 de 12 de janeiro de 1996 . Para mais informações ou "
    "sanar a pendência é necessário entrar em contato com o órgão/entidade responsável "
    "pela sua inscrição. CNPJ(Raiz): 12.240.183 Razão Social: FUNDO MUN DE SAUDE DE "
    "NOVA PALMA Porto Alegre, 07 de setembro de 2026 às 17:01:31"
)


def test_certidao_limpa():
    assert _classifica(LIMPA) == ("regular", "Nada consta")


def test_pendencia_com_numero_no_meio():
    """"consta 1 pendência" — a forma que a fonte usa de verdade."""
    tipo, situacao = _classifica(COM_PENDENCIA)
    assert tipo == "pendente"
    assert situacao == "Consta 1 pendência"


def test_plural_quando_ha_mais_de_uma():
    tipo, situacao = _classifica("Certificamos que constam 3 pendências para a pessoa")
    assert (tipo, situacao) == ("pendente", "Constam 3 pendências")


def test_nao_constam_nao_pode_virar_pendencia():
    """"não constam" CONTÉM "constam": a ordem das checagens é o teste."""
    assert _classifica("na data de hoje não constam pendências")[0] == "regular"
    assert _classifica("nao constam 0 pendencias")[0] == "regular"


def test_texto_desconhecido_nunca_vira_nada_consta():
    """O estado honesto é "não sei" — verde aqui trava um repasse em silêncio."""
    tipo, situacao = _classifica("o servidor esta temporariamente indisponivel")
    assert tipo == "indeterminado"
    assert "não foi possível" in situacao.lower()


def test_detalhes_dizem_com_quem_falar():
    """Sem isto a tela diz que o ente está travado e não diz por quem."""
    d = _detalhes_da_inscricao(COM_PENDENCIA)
    assert d["orgao"] == "SECRETARIA DA SAUDE / FUNDO ESTADUAL DE SAUDE"
    assert d["inscrito_em"] == "28/08/2026"
    assert d["quantidade"] == 1
    assert "fiscalizacao" in d["contato"]


def test_certidao_limpa_nao_tem_quadro_de_inscricao():
    assert _detalhes_da_inscricao(LIMPA) is None


def test_razao_social_identifica_entidade_fora_do_cadastro_estadual():
    """Para o fundo, este nome é a ÚNICA identificação que temos: ele não está
    no CHE."""
    assert _razao_social(COM_PENDENCIA) == "FUNDO MUN DE SAUDE DE NOVA PALMA"
    assert _razao_social(LIMPA) == "MUNICIPIO DE NOVA PALMA"


def test_data_e_a_que_a_certidao_afirma():
    """A certidão não tem validade: o que existe é a data da consulta."""
    assert _data_da_certidao(LIMPA) == "07/09/2026"
    assert _data_da_certidao(COM_PENDENCIA) == "07/09/2026"


# --------------------------------------------------------------------------
# A porta que o Estado fechou — e que ficou dois dias sem aparecer na tela.
#
# Em 09/09/2026 as duas rotas públicas responderam 404 (do Windows E da VPS: não
# é bloqueio de IP), porque a SEFAZ/RS reescreveu o portal e pôs reCAPTCHA na
# consulta — exigido no SERVIDOR: `{"message": "Erro ao validar recaptcha"}`.
# O coletor gravava `partial` com zero certidões e mensagem VAZIA, e a tela
# seguia escrevendo "ainda não foram consultados". Ausência tem causa.
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=404, texto=""):
        self.status_code = status
        self.text = texto
        self.content = b""
        self.headers = {}

    def raise_for_status(self):
        raise AssertionError("nao deveria chegar aqui com 404")


class _Client:
    """httpx.Client de mentira: 404 na rota velha, captcha na consulta nova."""
    def __init__(self):
        self.chamadas = []

    def post(self, url, **kwargs):
        self.chamadas.append(url)
        if "cadinConsulta/consulta" in url:
            return _Resp(400, '{"code":400,"message":"Erro ao validar recaptcha"}')
        return _Resp(404)


def test_rota_404_vira_motivo_legivel_e_nao_httpstatuserror():
    """`HTTPStatusError: 404` na tela manda procurar bug nosso. O motivo real é
    público e cabe numa frase — basta perguntar ao portal novo."""
    import ingestion.cadin_rs as c

    c._DIAGNOSTICO["checado"] = False
    c._DIAGNOSTICO["motivo"] = None
    cli = _Client()
    with pytest.raises(c.BloqueioNaOrigem) as e:
        c.emitir(cli, "EmitirCertidao", "88488358000167")
    assert "reCAPTCHA" in str(e.value)
    assert "cadin.sefaz.rs.gov.br" in str(e.value)


def test_o_portal_e_perguntado_uma_vez_por_rodada():
    """Uma carteira de 10 municípios x 2 certidões daria 20 diagnósticos — bater
    20 vezes no portal do Estado para descobrir a mesma coisa é falta de educação
    e de propósito."""
    import ingestion.cadin_rs as c

    c._DIAGNOSTICO["checado"] = False
    c._DIAGNOSTICO["motivo"] = None
    cli = _Client()
    for _ in range(3):
        with pytest.raises(c.BloqueioNaOrigem):
            c.emitir(cli, "EmitirCertidao", "88488358000167")
    assert sum(1 for u in cli.chamadas if "cadinConsulta" in u) == 1


def test_bloqueio_sobe_inteiro_em_vez_de_virar_erro_da_entidade():
    """Engolido como erro comum, o 404 se repetiria em cada entidade e a rodada
    terminaria 'parcial' sem dizer por quê — que foi exatamente o que aconteceu."""
    import ingestion.cadin_rs as c

    c._DIAGNOSTICO["checado"] = False
    c._DIAGNOSTICO["motivo"] = None
    with pytest.raises(c.BloqueioNaOrigem):
        c.consultar_entidade(_Client(), "88488358000167")


def test_catalogo_do_router_cobre_os_tres_cadastros():
    """A tela desenha a partir deste catálogo; cadastro sem entrada vira aba
    sem nome."""
    from routers.negativos import CATALOGO
    assert set(CATALOGO) == {"CADIN-MG", "CADIN-RS", "CFIL-RS"}
    assert [c for c, d in CATALOGO.items() if d["uf"] == "RS"] == ["CADIN-RS", "CFIL-RS"]
    assert all(d.get("trava") and d.get("origem") for d in CATALOGO.values())
