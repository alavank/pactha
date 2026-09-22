"""TCE-PR pelo PIT — as armadilhas medidas contra a fonte em 22/09/2026.

Sem rede e sem banco: os XML abaixo reproduzem o formato real (atributos, texto
de largura fixa, UTF-16 em 2019-2021, `&#x1;` no meio de um objeto).
"""
import io
import zipfile
from decimal import Decimal

from ingestion import tce_pr as t
from routers.tce_pr import categoria_da_fonte


def _zip(**arquivos: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dado in arquivos.items():
            z.writestr(nome, dado)
    return buf.getvalue()


CONVENIO = ('<?xml version="1.0"?><root><Convenio cdIBGE="411295" '
            'nmEntidade="MUNICÍPIO DE JURANDA            " idPessoa="12356" '
            'idConvenio="86627" nrConvenio="2026284900" nrAnoConvenio="2026" '
            'dtCelebracao="2026-03-04T00:00:00" dsConvenioEsfera="Federal" '
            'vlConvenio="100000.00" vlRecursoProprio="0.00" '
            'dtEnvio="2026-05-08T11:12:04.133" '
            'ultimoEnvioSIMAMNesteExercicio="2026/06" DataReferencia="2026/09 " '
            'dsObjeto="ESTRUTURAÇÃO DA REDE&#x1; SUAS"/></root>')


def test_ibge_de_sete_digitos_vira_o_codigo_de_seis_do_pit():
    assert t.ibge6("4112959") == "411295"
    # Sem os 7 dígitos não há como saber o código: vazio, e o município é pulado.
    assert t.ibge6("411295") == ""
    assert t.ibge6(None) == ""


def test_utf16_com_bom_e_lido_e_nao_destruido():
    """2019-2021 vêm em UTF-16 LE. O primeiro ensaio limpava BYTES de controle e
    apagava metade do arquivo (todo `\\x00` do UTF-16) — o parser morria na
    coluna 1."""
    dado = _zip(**{"x.xml": b"\xff\xfe" + CONVENIO.encode("utf-16-le")})
    regs = t.registros(dado, "x.xml", "Convenio")
    assert len(regs) == 1
    assert regs[0]["nmEntidade"].strip() == "MUNICÍPIO DE JURANDA"


def test_referencia_de_caractere_invalida_nao_derruba_o_arquivo():
    dado = _zip(**{"x.xml": b"\xef\xbb\xbf" + CONVENIO.encode("utf-8")})
    regs = t.registros(dado, "x.xml", "Convenio")
    assert regs[0]["dsObjeto"] == "ESTRUTURAÇÃO DA REDE  SUAS"


def test_referencia_valida_e_mantida():
    assert t.xml_limpo(b'<a b="x&#233;y&#x41;"/>') == '<a b="x&#233;y&#x41;"/>'.encode()


def test_xml_ausente_e_none_e_nao_lista_vazia():
    """Ausência de arquivo não autoriza apagar nada do banco."""
    assert t.registros(_zip(**{"outro.xml": b"<root/>"}), "x.xml", "Convenio") is None
    assert t.registros(_zip(**{"x.xml": b"<root>SEM REGISTROS</root>"}),
                       "x.xml", "Convenio") == []


def test_linha_de_convenio_tira_espaco_e_le_ponto_decimal():
    a = t.registros(_zip(**{"x.xml": CONVENIO.encode()}), "x.xml", "Convenio")[0]
    linha = t.linha_convenio(7, 2026, a)
    assert linha["entidade"] == "MUNICÍPIO DE JURANDA"
    assert linha["valor"] == Decimal("100000.00")
    assert linha["id"] == 86627 and linha["ano"] == 2026
    assert linha["envio"].year == 2026
    assert t.referencias([a]) == ("2026/09", "2026/06")


def test_aditivo_le_o_id_com_as_duas_caixas():
    """`idcontrato` em dois XML, `idContrato` no de rescisão."""
    assert t.linha_aditivo(1, 2026, "valor", {"idcontrato": "10"})["contrato"] == 10
    assert t.linha_aditivo(1, 2026, "rescisao", {"idContrato": "11"})["contrato"] == 11
    # Só o aditivo de PRAZO carrega a nova data de fim.
    assert t.linha_aditivo(1, 2026, "valor", {"idcontrato": "1",
                                               "dtFim": "2027-01-01T00:00:00"})["fim"] is None
    assert str(t.linha_aditivo(1, 2026, "prazo", {"idcontrato": "1",
                                                   "dtFim": "2027-01-01T00:00:00"})["fim"]) == "2027-01-01"


def test_despesa_soma_por_entidade_e_fonte():
    emp = [
        {"idPessoa": "12356", "cdFonteReceita": "824  ",
         "dsFonteReceita": "SECID Convênio 1748/2025 Pavimentação",
         "dsFontePlanoPadraoFonte": "Transferências Voluntárias Públicas Estaduais",
         "vlEmpenho": "100.10", "vlLiquidacao": "50.05", "vlPagamento": "50.05"},
        {"idPessoa": "12356", "cdFonteReceita": "824",
         "dsFonteReceita": "SECID Convênio 1748/2025 Pavimentação",
         "dsFontePlanoPadraoFonte": "Transferências Voluntárias Públicas Estaduais",
         "vlEmpenho": "0.90", "vlLiquidacao": "", "vlPagamento": None},
        # A Câmara é outra entidade: não soma com a prefeitura.
        {"idPessoa": "9872", "cdFonteReceita": "000",
         "dsFonteReceita": "Recursos Ordinários (Livres)", "vlEmpenho": "5"},
    ]
    grupos = {(g["pessoa"], g["cd"]): g for g in t.agrega_despesa(1, 2026, emp)}
    g = grupos[(12356, "824")]
    assert (g["qt"], g["emp"], g["liq"], g["pag"]) == (2, Decimal("101.00"),
                                                      Decimal("50.05"), Decimal("50.05"))
    assert grupos[(9872, "000")]["emp"] == Decimal("5")


def test_categoria_da_fonte():
    assert categoria_da_fonte("Transferências Voluntárias Públicas Estaduais",
                              "SECID Convênio 1748/2025") == "convenio"
    # Emenda de saúde fundo a fundo é EMENDA, e o gestor pergunta por ela junto.
    assert categoria_da_fonte(
        "Bloco de Custeio das Ações e Serviços Públicos de Saúde – Emendas "
        "Individuais (§ 13, art. 166 da CF)", "") == "convenio"
    assert categoria_da_fonte("Bloco de Custeio das Ações e Serviços Públicos de "
                              "Saúde", "") == "legal"
    assert categoria_da_fonte("Salário Educação", "") == "legal"
    assert categoria_da_fonte("Recursos Ordinários (Livres)", "") == "propria"
    assert categoria_da_fonte("Saúde - Receitas Vinculadas (EC 29/00 - 15%)",
                              "") == "propria"


class _CursorFalso:
    """Guarda o SQL e responde o count(*) pedido."""

    def __init__(self, contagem=0):
        self.contagem, self.sqls = contagem, []

    def execute(self, sql, params=None):
        self.sqls.append(sql)

    def fetchone(self):
        return (self.contagem,)


def test_arquivo_vazio_com_banco_cheio_nao_apaga():
    """Armadilha 5: zip regerado vazio não pode zerar o município."""
    cur = _CursorFalso(contagem=12)
    gravadas, recusou = t._substitui_ano(cur, "obras", 1, 2026, [])
    assert (gravadas, recusou) == (0, True)
    assert not any("DELETE" in s for s in cur.sqls)


def test_arquivo_vazio_com_banco_vazio_e_zero_legitimo():
    cur = _CursorFalso(contagem=0)
    assert t._substitui_ano(cur, "convenios", 1, 2021, []) == (0, False)


def test_ano_com_linhas_grava_e_apaga_o_que_saiu():
    cur = _CursorFalso()
    linhas = [t.linha_licitacao(1, 2026, {"idLicitacao": "5", "nrAnoLicitacao": "2026"})]
    assert t._substitui_ano(cur, "licitacoes", 1, 2026, linhas) == (1, False)
    assert "DELETE" in cur.sqls[-1] and "id_licitacao" in cur.sqls[-1]


def test_despesa_vazia_com_banco_cheio_nao_apaga():
    cur = _CursorFalso(contagem=40)
    contagens, recusas = t._grava_lote(cur, 1, 2026, {"despesa": []})
    assert recusas == ["despesa"]
    assert not any("DELETE" in s for s in cur.sqls)


def test_zip_remoto_aborta_quando_o_etag_muda():
    """Armadilha 2: pedaço de zip velho com pedaço de zip novo é lixo."""
    import httpx

    def responde(req):
        return httpx.Response(206, content=b"abc", headers={"etag": '"novo"'})

    with httpx.Client(transport=httpx.MockTransport(responde)) as c:
        r = t.ZipRemoto(c, "https://x/a.zip", '"velho"', 100)
        try:
            r.read(3)
        except t.ArquivoTrocado:
            pass
        else:
            raise AssertionError("ETag trocado deveria abortar a leitura")


def test_zip_remoto_le_por_range():
    import httpx
    corpo = _zip(**{"2026_411295_Convenio.zip": _zip(**{
        "2026_411295_Convenio.xml": CONVENIO.encode()})})

    def responde(req):
        ini, fim = req.headers["Range"].removeprefix("bytes=").split("-")
        return httpx.Response(206, content=corpo[int(ini):int(fim) + 1],
                              headers={"etag": '"e"'})

    with httpx.Client(transport=httpx.MockTransport(responde)) as c:
        r = t.ZipRemoto(c, "https://x/a.zip", '"e"', len(corpo))
        z = zipfile.ZipFile(io.BufferedReader(r, buffer_size=1 << 16))
        lido = t.ler_ano(z, 2026, "411295", 1, com_despesa=False)
    assert len(lido["convenios"]) == 1
    # Os temas que não vieram no zip ficam registrados — e não viram lista vazia.
    assert "Obra" in lido["faltando"] and "obras" not in lido
