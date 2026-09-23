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
            achados, falhas, outros = c.coletar(cl, [{"id": 1, "nome": "Juranda", "cod": 12959}])
    finally:
        c.ANO_INICIAL = c_ano
    assert list(achados) == ["PR-10444"]
    assert achados["PR-10444"]["v_repassado"] == Decimal("463748.99")
    # ⭐ A APAE (mesmo IBGE, não é a prefeitura) NÃO some desde 23/09/2026: vem em
    # `outros`, que vai para `convenios_estadual_outros` — e NUNCA em `achados`,
    # que é o que entra em `convenios_estadual` e nas contas.
    assert list(outros) == ["PR-21904"]
    assert outros["PR-21904"]["convenente"].startswith("ASSOCIAÇÃO DE PAIS")
    assert outros["PR-21904"]["mid"] == 1
    assert falhas == []


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))


def test_grava_outros_so_apaga_com_todos_os_anos_lidos():
    """Um ano que falhou esconderia linhas que continuam na fonte: sem ele, só
    grava; com todos os anos, grava e apaga o que a fonte deixou de publicar."""
    reg = {"mid": 1, "nr": "PR-21904", "fonte": c.FONTE}
    alvos = [{"id": 1, "nome": "Juranda", "cod": 12959}]
    cur = _Cur()
    c.grava_outros(cur, {"PR-21904": reg}, alvos, falhou_ano=True)
    assert not any(s.startswith("DELETE") for s, _ in cur.sql)
    cur = _Cur()
    c.grava_outros(cur, {"PR-21904": reg}, alvos, falhou_ano=False)
    apaga = [p for s, p in cur.sql if s.startswith("DELETE")]
    assert apaga == [(c.FONTE, 1, ["PR-21904"])]
    assert all("convenios_estadual_outros" in s for s, _ in cur.sql)


def test_so_a_rota_propria_le_a_tabela_das_entidades():
    """Fora das contas POR CONSTRUÇÃO: um painel, BI ou RM que passasse a ler
    `convenios_estadual_outros` somaria a APAE como se fosse da prefeitura."""
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parents[1]
    # LEITURA de verdade (`FROM`/`JOIN`), e não o nome do .sql na lista de
    # migrations de `services/startup.py`.
    le = re.compile(r"(?i)\b(FROM|JOIN)\s+convenios_estadual_outros\b")
    leitores = sorted(
        str(p.relative_to(raiz)).replace("\\", "/")
        for pasta in ("routers", "services")
        for p in (raiz / pasta).rglob("*.py")
        if le.search(p.read_text(encoding="utf-8")))
    assert leitores == ["routers/convenios.py"]


def test_entidade_nunca_vai_para_convenios_estadual():
    """A tabela que os quinze leitores somam não pode receber a APAE."""
    import inspect
    fonte = inspect.getsource(c.grava_outros)
    assert "INSERT INTO convenios_estadual (" not in fonte
    assert "convenios_estadual_outros" in c._SQL_OUTROS
