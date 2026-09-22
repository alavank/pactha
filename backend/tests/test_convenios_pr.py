"""Convênios do Estado do PR — as armadilhas medidas contra a fonte em 22/09/2026."""
import io
import json
import zipfile
from decimal import Decimal

import pytest

from ingestion import convenios_pr as c

CAB = ("convenio_empreendimento_cod;convenio_entidade_cod;atividade;concedente;"
       "dt_celebracao;dt_publicacao;dt_vigencia_fim;dt_vigencia_inicio;ibge;"
       "info_adicional;numero;objeto;qtd_unidade;representante_legal_concedente;"
       "representante_legal_tomador;situacao;tomador;total_contra_partida_depositada;"
       "total_contra_partida;total_repassado;total_repassado_1;total_repasses;unidade")


def _linha(cod, tomador, ibge="12959", repassado="463748.99", total="15245720.37"):
    return (f"{cod};17;Abastecimento;FUNDO DE EQUIPAMENTO AGROPECUARIO - MATRIZ;"
            "2025-11-28 00:00:00;2025-12-02 00:00:00;2027-12-02 00:00:00;"
            f"2025-12-02 00:00:00;{ibge};Este Empreendimento corresponde ao SIT nr. "
            "78968  no Sistema Integrado de Transferências;745 241573168;"
            "Estradas da Integração;10550;X;Y;Em Execução;"
            f"{tomador};;0.00;{repassado};0.00;{total};Metro linear")


def _zip(*linhas) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("TB_CONVENIO_EMPREENDIMENTO-2026.csv",
                   ("﻿" + CAB + "\n" + "\n".join(linhas)).encode("utf-8"))
        z.writestr("TB_CONVENIO_ENTIDADE-2026.csv",
                   "﻿convenio_entidade_cod;cnpj;nome\n17;11111111000111;FEAP\n"
                   .encode("utf-8"))
    return buf.getvalue()


def test_o_ibge_do_arquivo_nao_tem_o_prefixo_da_uf():
    assert c.codigo_pr("4112959") == 12959
    assert c.codigo_pr("4106902") == 6902       # Curitiba: sem zero à esquerda
    assert c.codigo_pr("4313102") is None       # RS não é PR
    assert c.codigo_pr("") is None


@pytest.mark.parametrize("tomador,esperado", [
    ("MUNICIPIO DE JURANDA", True),
    ("MUNICÍPIO DE JURANDA", True),
    ("FUNDO MUNICIPAL DE SAÚDE DE JURANDA", True),
    ("ASSOCIAÇÃO DE PAIS E AMIGOS DOS EXCEPCIONAIS DE JURANDA", False),
    ("MUNICIPIO DE JURANDA DO SUL", True),       # a palavra inteira casa; o IBGE separa
    ("MUNICIPIO DE CAMPO MOURAO", False),
])
def test_so_ente_municipal_do_proprio_municipio(tomador, esperado):
    assert c.e_ente_municipal(tomador, "Juranda") is esperado


def test_zip_le_bom_e_separador_e_devolve_concedentes():
    linhas, entidades = c.ler_zip(_zip(_linha(10444, "MUNICIPIO DE JURANDA")), 2026)
    assert linhas[0]["convenio_empreendimento_cod"] == "10444"
    assert entidades["17"]["cnpj"] == "11111111000111"


def test_coluna_renomeada_recusa_o_ano():
    ruim = io.BytesIO()
    with zipfile.ZipFile(ruim, "w") as z:
        z.writestr("TB_CONVENIO_EMPREENDIMENTO-2026.csv",
                   (CAB.replace("total_repassado;", "vl_repassado;") + "\n"
                    + _linha(1, "MUNICIPIO DE JURANDA")).encode())
    with pytest.raises(ValueError, match="total_repassado"):
        c.ler_zip(ruim.getvalue(), 2026)


def test_registro_valores_numero_e_sit():
    linhas, ent = c.ler_zip(_zip(_linha(10444, "MUNICIPIO DE JURANDA")), 2026)
    r = c.registro(linhas[0], 7, ent)
    assert r["nr"] == "PR-10444" and r["mid"] == 7 and r["fonte"] == "SIT-PR"
    assert r["v_conc"] == Decimal("15245720.37")
    assert r["v_repassado"] == Decimal("463748.99")
    assert r["v_total"] == Decimal("15245720.37")
    assert r["ano"] == 2025 and str(r["dt_fim"]) == "2027-12-02"
    raw = json.loads(r["raw"])
    assert raw["nr_instrumento"] == "745 241573168"
    assert raw["nr_sit"] == "78968"
    assert raw["concedente_cnpj"] == "11111111000111"


def test_formalizada_sem_repasse_fica_vazia_e_nao_zero():
    linhas, ent = c.ler_zip(_zip(_linha(1, "MUNICIPIO DE JURANDA", repassado="")), 2026)
    assert c.registro(linhas[0], 1, ent)["v_repassado"] is None


def test_coletar_casa_por_ibge_e_nome_e_o_ano_mais_recente_vence():
    import httpx
    arquivos = {
        "2025": _zip(_linha(10444, "MUNICIPIO DE JURANDA", repassado="100.00"),
                     _linha(21904, "ASSOCIAÇÃO DE PAIS E AMIGOS DOS EXCEPCIONAIS DE JURANDA"),
                     _linha(5, "MUNICIPIO DE CURITIBA", ibge="6902")),
        "2026": _zip(_linha(10444, "MUNICIPIO DE JURANDA", repassado="463748.99")),
    }

    def responde(req):
        ano = str(req.url).rsplit("-", 1)[1][:4]
        return (httpx.Response(200, content=arquivos[ano]) if ano in arquivos
                else httpx.Response(404))

    c_ano = c.ANO_INICIAL
    c.ANO_INICIAL = 2025
    try:
        with httpx.Client(transport=httpx.MockTransport(responde)) as cl:
            achados, falhas, fora = c.coletar(cl, [{"id": 1, "nome": "Juranda", "cod": 12959}])
    finally:
        c.ANO_INICIAL = c_ano
    assert list(achados) == ["PR-10444"]
    assert achados["PR-10444"]["v_repassado"] == Decimal("463748.99")
    assert fora == {"Juranda": 1}           # a APAE: mesmo IBGE, não é a prefeitura
    assert falhas == []
