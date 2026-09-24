"""Emendas estaduais de MG pela planilha oficial da SEGOV — armadilhas de 24/09/2026.

As planilhas sintéticas repetem os dois layouts medidos em emendas.mg.gov.br
(26 colunas em 2019-2022, sem IBGE; 49 em 2023-2026, com IBGE), com a aba
nomeada "12-05" como a fonte faz.
"""
import inspect
import io
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import openpyxl
import pytest

from ingestion import emendas_mg as em

MODIFICADO = datetime(2026, 5, 13, 18, 15, tzinfo=timezone.utc)


def _xlsx(layout: dict, linhas: list[dict], aba="12-05", extra_cab=()) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = aba
    cab = list(layout.values()) + list(extra_cab)
    ws.append(cab)
    for ln in linhas:
        ws.append([ln.get(k) for k in layout] + [None] * len(extra_cab))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _novo(nr, ibge="3143401", municipio="MONTE SIAO", tipo="TRANSFERÊNCIA ESPECIAL",
          tipo_benef="MUNICÍPIO", benef="PREFEITURA MUNICIPAL DE MONTE SIAO",
          cnpj="18675983000121", pago=140000):
    return {"ano": 2025, "nr": nr, "tipo": tipo, "status": "APROVADO", "autor": "FULANO",
            "tipo_atendimento": "-", "uo_codigo": 1491, "uo_sigla": "SEGOV",
            "grupo": "INVESTIMENTOS", "ibge": ibge, "municipio": municipio,
            "tipo_beneficiario": tipo_benef, "beneficiario": benef, "cnpj": cnpj,
            "valor_indicacao": 140000, "valor_empenhado": 140000,
            "valor_liquidado": 140000, "valor_pago": pago, "valor_resto_saldo": 0,
            "instrumento": "-"}


def _antigo(nr, municipio="MONTE SIAO", benef="FUNDO MUNICIPAL DE SAÚDE DE MONTE SIÃO",
            cnpj="11222333000144"):
    return {"ano": 2021, "nr": nr, "tipo": "RESOLUÇÃO SES", "status": "APROVADO",
            "autor": "BELTRANO", "tipo_atendimento": "Custeio (SES)", "uo_sigla": "FES",
            "grupo": "Custeio", "municipio": municipio, "beneficiario": benef,
            "cnpj": cnpj, "valor_indicacao": 100000, "valor_empenhado": 100000,
            "valor_liquidado": 100000, "valor_pago": 90000, "instrumento": "-"}


def test_layout_novo_le_ibge_valores_e_zero_como_zero():
    linhas, data = em.ler_xlsx(_xlsx(em.LAYOUT_NOVO, [_novo(112572, pago=0)]), MODIFICADO)
    assert data == date(2026, 5, 12)
    x = linhas[0]
    assert x["nr"] == "112572" and x["ibge"] == "3143401" and x["ano"] == 2025
    assert x["valor_pago"] == Decimal("0")                 # zero AFIRMADO, não vazio
    assert x["valor_indicacao"] == Decimal("140000")
    assert x["tipo_atendimento"] is None and x["instrumento"] is None   # "-" = vazio


def test_layout_antigo_sem_ibge_e_cnpj_que_perdeu_o_zero():
    linhas, _ = em.ler_xlsx(_xlsx(em.LAYOUT_ANTIGO, [_antigo(23899, cnpj=1834744000174)]),
                            MODIFICADO)
    x = linhas[0]
    assert x["ibge"] is None and x["municipio"] == "MONTE SIAO"
    assert x["cnpj"] == "01834744000174"                  # número do Excel perde o zero
    assert x["valor_resto_saldo"] is None                 # coluna que o layout não tem


@pytest.mark.parametrize("bruto,esperado", [
    ("TRANSFERÊNCIA ESPECIAL", "Transferência Especial"),
    ("CELEBRAÇÃO DE CONVÊNIO", "Convênio"),
    ("APLICAÇÃO DIRETA - DOAÇÃO DE BENS", "Aplicação Direta"),
    ("RESOLUÇÃO SES", "Resolução SES"),
    ("EXECUÇÃO DIRETA - CAIXA ESCOLAR", "Execução Direta - Caixa Escolar"),
    ("TIPO NOVO QUE A SEGOV CRIOU", "TIPO NOVO QUE A SEGOV CRIOU"),   # não some
    ("-", None),
])
def test_tipo_na_grafia_do_sigcon(bruto, esperado):
    assert em.tipo_como_sigcon(bruto) == esperado


def test_layout_desconhecido_e_recusado():
    ruim = dict(em.LAYOUT_NOVO)
    ruim["valor_pago"] = "Valor Pago Total"
    with pytest.raises(ValueError, match="layouts medidos"):
        em.ler_xlsx(_xlsx(ruim, [_novo(1)]), MODIFICADO)


@pytest.mark.parametrize("aba,esperado", [
    ("12-05", date(2026, 5, 12)),
    ("28-12", date(2025, 12, 28)),     # aba de dezembro num arquivo de maio = ano anterior
    ("Planilha1", date(2026, 5, 13)),  # sem data na aba: o Last-Modified
])
def test_data_da_aba(aba, esperado):
    assert em.data_da_aba(aba, MODIFICADO) == esperado


@pytest.mark.parametrize("linha,cnpj_pref,esperado", [
    ({"tipo_beneficiario": "MUNICÍPIO"}, None, True),
    ({"tipo_beneficiario": "FUNDO MUNICIPAL DE SAÚDE"}, None, True),
    ({"tipo_beneficiario": "FUNDO MUNICIPAL DE ASSISTÊNCIA SOCIAL"}, None, True),
    ({"tipo_beneficiario": "ORGANIZAÇÃO DA SOCIEDADE CIVIL"}, None, False),
    ({"tipo_beneficiario": "Caixa Escolar"}, None, False),
    ({"tipo_beneficiario": "ÓRGÃOS OU ENTIDADES PÚBLICAS"}, None, False),
    # Layout antigo, sem o tipo: pelo nome...
    ({"beneficiario": "FUNDO MUNICIPAL DE SAÚDE DE UBÁ"}, None, True),
    ({"beneficiario": "APAE DE UBA"}, None, False),
    # ...ou pelo CNPJ da prefeitura, que vale sempre.
    ({"beneficiario": "PMMS", "cnpj": "18675983000121"}, "18675983000121", True),
])
def test_e_municipal(linha, cnpj_pref, esperado):
    assert em.e_municipal(linha, cnpj_pref) is esperado


def test_municipio_por_ibge_e_por_nome_igual_nunca_contem():
    alvos = [{"id": 1, "nome": "Monte Sião", "ibge": "3143401", "cnpj": None},
             {"id": 2, "nome": "Santa Maria", "ibge": "4316907", "cnpj": None}]
    pi = {a["ibge"]: a for a in alvos}
    pn = {em._norm(a["nome"]): a for a in alvos}
    assert em.casa_municipio({"ibge": "3143401"}, pi, pn)["id"] == 1
    assert em.casa_municipio({"ibge": None, "municipio": "MONTE SIAO"}, pi, pn)["id"] == 1
    # IBGE de OUTRO município não cai no nome.
    assert em.casa_municipio({"ibge": "3100000", "municipio": "MONTE SIAO"}, pi, pn) is None
    assert em.casa_municipio({"ibge": None, "municipio": "SANTA MARIA DO HERVAL"}, pi, pn) is None


def test_upsert_nao_sobrescreve_o_que_o_sigcon_raspou():
    """Armadilha 4: numa linha do SIGCON a planilha só preenche o vazio e grava a
    execução; numa linha que ela mesma criou, ela atualiza tudo."""
    sql = " ".join(em._SQL.split())
    assert "ON CONFLICT (municipio_id, nr_indicacao) DO UPDATE" in sql
    assert (f"status_indicacao = CASE WHEN emendas_estaduais.raw_data->>'_source' = "
            f"'{em.FONTE_RAW}' THEN EXCLUDED.status_indicacao ELSE "
            "COALESCE(NULLIF(emendas_estaduais.status_indicacao::text, ''), "
            "EXCLUDED.status_indicacao::text)::varchar END") in sql
    assert (f"raw_data = CASE WHEN emendas_estaduais.raw_data->>'_source' = "
            f"'{em.FONTE_RAW}' THEN EXCLUDED.raw_data ELSE emendas_estaduais.raw_data END") in sql
    assert "valor_pago = EXCLUDED.valor_pago" in sql
    assert "execucao_em = EXCLUDED.execucao_em" in sql


def _cliente(arquivos: dict[str, bytes | int]):
    def responde(req):
        nome = str(req.url).rsplit("/", 1)[1]
        v = arquivos.get(nome, 404)
        if isinstance(v, int):
            return httpx.Response(v)
        return httpx.Response(200, content=v,
                              headers={"last-modified": "Wed, 13 May 2026 18:15:32 GMT"})
    return httpx.Client(transport=httpx.MockTransport(responde))


ALVOS = [{"id": 7, "nome": "Monte Sião", "ibge": "3143401", "cnpj": "18675983000121"}]


def test_coletar_separa_municipal_de_entidade(monkeypatch):
    monkeypatch.setattr(em, "MIN_LINHAS", 1)
    novo = _xlsx(em.LAYOUT_NOVO, [
        _novo(1), _novo(2, tipo="RESOLUÇÃO SES", tipo_benef="ORGANIZAÇÃO DA SOCIEDADE CIVIL",
                        benef="APAE DE MONTE SIAO", cnpj="99999999000199"),
        _novo(3, ibge="3106200", municipio="BELO HORIZONTE")])
    antigo = _xlsx(em.LAYOUT_ANTIGO, [_antigo(23899)])
    with _cliente({em.ARQUIVOS[0]: antigo, em.ARQUIVOS[1]: novo}) as cl:
        municipais, outros, falhas, data = em.coletar(cl, ALVOS)
    assert falhas == [] and data == date(2026, 5, 12)
    assert sorted(municipais) == [(7, "1"), (7, "23899")]
    assert list(outros) == [(7, "2")]
    assert municipais[(7, "1")]["execucao_em"] == date(2026, 5, 12)


def test_arquivo_cortado_ou_fora_do_ar_vira_falha(monkeypatch):
    monkeypatch.setattr(em, "MIN_LINHAS", 5)
    with _cliente({em.ARQUIVOS[0]: 500,
                   em.ARQUIVOS[1]: _xlsx(em.LAYOUT_NOVO, [_novo(1)])}) as cl:
        municipais, _, falhas, _ = em.coletar(cl, ALVOS)
    assert municipais == {} and len(falhas) == 2
    assert "cortada" in falhas[1]


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))


def test_so_apaga_entidade_com_os_dois_arquivos_lidos(monkeypatch):
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        lambda cur, sql, seq, page_size=100: [cur.execute(sql, p) for p in seq])
    reg = {"mid": 7, "nr": "2"}
    cur = _Cur()
    em.grava(cur, {}, {(7, "2"): reg}, ALVOS, completa=False)
    assert not any(s.startswith("DELETE") for s, _ in cur.sql)
    cur = _Cur()
    em.grava(cur, {}, {(7, "2"): reg}, ALVOS, completa=True)
    assert [p for s, p in cur.sql if s.startswith("DELETE")] == [(7, ["2"])]


def test_so_a_rota_propria_le_a_tabela_das_entidades():
    """Fora das contas POR CONSTRUÇÃO: BI, RM ou parlamentares que lessem
    `emendas_estaduais_outros` somariam a APAE como se fosse da prefeitura."""
    import pathlib
    import re
    raiz = pathlib.Path(__file__).resolve().parents[1]
    le = re.compile(r"(?i)\b(FROM|JOIN)\s+emendas_estaduais_outros\b")
    leitores = sorted(
        str(p.relative_to(raiz)).replace("\\", "/")
        for pasta in ("routers", "services")
        for p in (raiz / pasta).rglob("*.py")
        if le.search(p.read_text(encoding="utf-8")))
    assert leitores == ["routers/emendas_estaduais.py"]


def test_cagec_nao_pega_o_cnpj_do_fundo_municipal():
    """Com a Resolução SES, `emendas_estaduais` passou a ter FUNDO MUNICIPAL — e o
    `ILIKE '%MUNIC%'` antigo casava com ele. O CNPJ da prefeitura vem primeiro de
    `municipios.cnpj`, e das emendas só nome que COMEÇA por PREFEITURA/MUNIC."""
    from ingestion import cagec_scraper
    fonte = inspect.getsource(cagec_scraper._municipios_alvo)
    fonte = fonte[fonte.index("_sql = "):]          # o SQL, não o comentário que o explica
    assert "'%MUNIC%'" not in fonte
    assert "NULLIF(regexp_replace(coalesce(m.cnpj, '')" in fonte
    assert fonte.index("m.cnpj") < fonte.index("FROM emendas_estaduais")
