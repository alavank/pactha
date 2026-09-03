"""
TCE-RS / LicitaCon — os testes travam as armadilhas que corrompem dado em
silêncio, não a mecânica do parser.

Todas foram medidas contra a fonte em 02/09/2026, no órgão 53100 (Nova Palma):

  (a) O ZIP TEM TREZE CSVs. Abrir "o primeiro" pega `comissao.csv`, que existe,
      tem cabeçalho e parseia sem erro nenhum — e não é o que se procura.

  (b) O ENCODING É UTF-8, E O CONSOLE DO WINDOWS DIZ O CONTRÁRIO. Os bytes de
      "Aquisição" são `c3 a7`; lidos como latin-1 viram `Ã§`, que o cp1252
      RENDERIZA como se estivesse certo. Quem confere pelo terminal conclui o
      oposto da verdade e grava mojibake na tela do cliente.

  (c) VALOR HOMOLOGADO VAZIO NÃO É ZERO. Certame em andamento ou fracassado não
      homologou nada; gravar 0 afirma que a prefeitura contratou de graça.

  (d) O NÚMERO REINICIA POR ANO E POR MODALIDADE — a chave são quatro campos.

  (e) 403 NÃO É "MUNICÍPIO SEM LICITAÇÃO". O TCE-RS bloqueia faixa de datacenter
      e a rodada tem de sair `partial` com a nota, nunca `success` com zero.

Rodar:
    python -m pytest backend/tests/test_tce_rs.py -v
"""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from ingestion.tce_rs import (
    ARQUIVO_CONTRATO, ARQUIVO_LICITACAO, _dec, _data, _slug,
    descobrir_orgao, linha_contrato, linha_licitacao, linhas_do_zip,
    url_contratos, url_licitacoes,
)

FIXTURES = Path(__file__).parent / "fixtures"
# Linhas REAIS do órgão 53100, salvas como JSON — o `.zip` é ignorado pelo
# `.gitignore` e um binário não se lê em diff. O teste remonta o pacote.
LINHAS = json.loads((FIXTURES / "tce_rs_licitacon.json").read_text(encoding="utf-8"))


def _zip_como_o_do_tce(principal: str, linhas: list[dict]) -> bytes:
    """Monta um ZIP com a MESMA estrutura do TCE: vários CSVs, o útil no meio.

    ⚠️ `comissao.csv` vem PRIMEIRO de propósito (é o que o zip real traz
    primeiro, em ordem alfabética). Um parser que pegasse `namelist()[0]` passa
    por ele e não pelo arquivo certo — e não daria erro nenhum."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("comissao.csv",
                   "﻿CD_ORGAO,NR_COMISSAO,ANO_COMISSAO\n53100,6156,2016\n"
                   .encode("utf-8"))
        saida = io.StringIO()
        w = csv.DictWriter(saida, fieldnames=list(linhas[0].keys()), delimiter=",")
        w.writeheader()
        w.writerows(linhas)
        # BOM + UTF-8, exatamente como a fonte publica.
        z.writestr(principal, ("﻿" + saida.getvalue()).encode("utf-8"))
        z.writestr("pessoas.csv", "﻿CD_ORGAO,NR_DOCUMENTO\n53100,123\n".encode("utf-8"))
    return buf.getvalue()


@pytest.fixture
def zip_licitacoes():
    return _zip_como_o_do_tce(ARQUIVO_LICITACAO, LINHAS[ARQUIVO_LICITACAO])


@pytest.fixture
def zip_contratos():
    return _zip_como_o_do_tce(ARQUIVO_CONTRATO, LINHAS[ARQUIVO_CONTRATO])


# ---------------------------------------------------------------------------
# (a) O arquivo certo dentro do ZIP
# ---------------------------------------------------------------------------
def test_le_o_csv_certo_e_nao_o_primeiro_do_zip(zip_licitacoes):
    linhas = linhas_do_zip(zip_licitacoes, ARQUIVO_LICITACAO)
    assert linhas, "nenhuma linha lida"
    # `comissao.csv` não tem estas colunas — se o parser tivesse pego o primeiro
    # arquivo, ele teria lido sem erro e devolvido lixo.
    assert "DS_OBJETO" in linhas[0]
    assert "NR_LICITACAO" in linhas[0]


def test_arquivo_ausente_falha_alto_em_vez_de_devolver_vazio(zip_contratos):
    """Se o TCE renomear o CSV, o coletor tem de gritar. Devolver [] faria a
    rodada sair `success` com zero registros — a fonte 'secaria' sem erro."""
    with pytest.raises(ValueError) as e:
        linhas_do_zip(zip_contratos, "licitacao.csv")
    # A mensagem lista o que HÁ no zip, para o diagnóstico não exigir download.
    assert "contrato.csv" in str(e.value)


# ---------------------------------------------------------------------------
# (b) Encoding
# ---------------------------------------------------------------------------
def test_acento_sobrevive_a_leitura(zip_licitacoes):
    """⚠️ Este é o teste que o console do Windows não sabe fazer.

    Os bytes são `c3 a7` (UTF-8 de 'ç'). Lidos como latin-1 virariam 'Ã§' — e o
    terminal cp1252 mostraria isso como 'ção', ou seja, o ERRADO parece certo.
    A comparação aqui é com o code point, que não mente."""
    linhas = linhas_do_zip(zip_licitacoes, ARQUIVO_LICITACAO)
    objetos = " ".join((l.get("DS_OBJETO") or "") for l in linhas)
    assert "ç" in objetos or "ã" in objetos, "nenhum acento na fixture"
    # O mojibake do latin-1 é exatamente esta sequência. Se ela aparecer, o
    # encoding voltou a estar errado.
    assert "Ã§" not in objetos
    assert "�" not in objetos, "caractere de substituição = decodificação errada"


def test_bom_nao_vaza_para_o_nome_da_primeira_coluna(zip_licitacoes):
    """Sem `utf-8-sig`, a primeira coluna vira '\\ufeffCD_ORGAO' e o DictReader
    simplesmente não a encontra — `CD_ORGAO` sai None em toda linha."""
    linhas = linhas_do_zip(zip_licitacoes, ARQUIVO_LICITACAO)
    assert linhas[0].get("CD_ORGAO") == "53100"
    assert not any(k.startswith("﻿") for k in linhas[0])


# ---------------------------------------------------------------------------
# (c) Valor vazio não é zero
# ---------------------------------------------------------------------------
def test_valor_homologado_vazio_continua_vazio(zip_licitacoes):
    linhas = linhas_do_zip(zip_licitacoes, ARQUIVO_LICITACAO)
    montadas = [linha_licitacao(1, r) for r in linhas]
    sem_hom = [m for m in montadas if m["vl_hom"] is None]
    com_hom = [m for m in montadas if m["vl_hom"] is not None]
    # Os dois grupos existem na fixture real — é o que torna isto uma armadilha
    # e não uma questão de estilo.
    assert sem_hom and com_hom, {"sem": len(sem_hom), "com": len(com_hom)}
    assert all(m["vl_hom"] != 0 for m in sem_hom)


@pytest.mark.parametrize("texto,esperado", [
    ("3489.30", 3489.30),      # ponto é DECIMAL neste dump, não milhar
    ("251.70", 251.70),
    ("9981500.00", 9981500.00),
    ("", None), (None, None), ("n/d", None),
])
def test_decimal_com_ponto(texto, esperado):
    """⚠️ `parse_decimal_br` do `ingestion/base.py` trataria o ponto como
    separador de MILHAR e faria 3489.30 virar 348930."""
    assert _dec(texto) == esperado


def test_data_iso():
    assert _data("2016-02-19").isoformat() == "2016-02-19"
    assert _data("") is None
    assert _data("19/02/2016") is None   # a fonte não usa este formato


# ---------------------------------------------------------------------------
# (d) A chave são quatro campos
# ---------------------------------------------------------------------------
def test_chave_da_licitacao_separa_modalidades_do_mesmo_numero():
    """Número reinicia por ano E por modalidade: o pregão 5/2026 e a
    concorrência 5/2026 são certames diferentes. Chave de três campos os
    colapsaria num registro só, em silêncio, no ON CONFLICT."""
    base = {"CD_ORGAO": "53100", "NR_LICITACAO": "5", "ANO_LICITACAO": "2026"}
    a = linha_licitacao(1, {**base, "CD_TIPO_MODALIDADE": "PRP"})
    b = linha_licitacao(1, {**base, "CD_TIPO_MODALIDADE": "CNC"})
    chave = lambda m: (m["orgao"], m["nr"], m["ano"], m["mod"])
    assert chave(a) != chave(b)


def test_chave_do_contrato_separa_contrato_de_ata():
    """Existe contrato 15 e ata 15 no mesmo ano — `TP_INSTRUMENTO` é o que os
    separa, e por isso está na chave."""
    base = {"CD_ORGAO": "53100", "NR_CONTRATO": "15", "ANO_CONTRATO": "2026"}
    c = linha_contrato(1, {**base, "TP_INSTRUMENTO": "C"})
    a = linha_contrato(1, {**base, "TP_INSTRUMENTO": "A"})
    assert (c["orgao"], c["nr"], c["ano"], c["tp"]) != (a["orgao"], a["nr"], a["ano"], a["tp"])


def test_contrato_sem_tipo_de_instrumento_nao_quebra_a_chave():
    """`TP_INSTRUMENTO` é NOT NULL na tabela e faz parte da chave. Linha sem ele
    cairia com erro de banco no meio da rodada, derrubando o lote inteiro."""
    m = linha_contrato(1, {"CD_ORGAO": "53100", "NR_CONTRATO": "9",
                           "ANO_CONTRATO": "2026", "TP_INSTRUMENTO": ""})
    assert m["tp"] == "C"


# ---------------------------------------------------------------------------
# Endereços e descoberta do órgão
# ---------------------------------------------------------------------------
def test_urls_saem_do_codigo_do_orgao():
    assert url_licitacoes("53100").endswith("/licitacon/licitacao/orgao/53100.csv.zip")
    assert url_contratos("56900").endswith("/licitacon/contrato/orgao/56900.csv.zip")


@pytest.mark.parametrize("nome,slug", [
    ("Nova Palma", "nova-palma"),
    ("Santa Maria", "santa-maria"),
    ("São Francisco de Assis", "sao-francisco-de-assis"),
    ("Restinga Sêca", "restinga-seca"),
])
def test_slug_do_municipio(nome, slug):
    assert _slug(nome) == slug


class _RespostaFalsa:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class ClienteFalso:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.chamadas: list = []

    def get(self, url, params=None, **kw):
        self.chamadas.append((url, params))
        return _RespostaFalsa(self.payload, self.status)


def test_descobre_o_orgao_pela_url_do_recurso():
    """O código não está num campo do CKAN — está no caminho do arquivo. E o
    dataset procurado é o `pm-` (prefeitura), nunca o `cm-` (câmara)."""
    cli = ClienteFalso({"success": True, "result": {"resources": [
        {"url": "https://dados.tce.rs.gov.br/dados/licitacon/licitacao/orgao/53100.csv.zip"},
    ]}})
    assert descobrir_orgao(cli, "Nova Palma") == "53100"
    _, params = cli.chamadas[0]
    assert params["id"] == "licitacoes-pm-de-nova-palma"


def test_descoberta_sem_pacote_devolve_none_sem_explodir():
    """Nem todo ente gaúcho tem dataset no CKAN do TCE — é fato da fonte, e o
    coletor tem de seguir para o próximo município."""
    assert descobrir_orgao(ClienteFalso({"success": False}), "Inexistente") is None
    assert descobrir_orgao(ClienteFalso({}, status=404), "Inexistente") is None
