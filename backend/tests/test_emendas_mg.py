"""Emendas estaduais de MG pelos dados abertos do Estado — armadilhas de 24/09/2026.

Os CSVs sintéticos repetem o formato medido em dados.mg.gov.br
(`vw_sg_v2_ep_indic_recursos_tw.csv`): `;`, UTF-8 com BOM, decimal com vírgula
e IBGE/CNPJ exportados como float ("3143401,0").
"""
import inspect
from datetime import date
from decimal import Decimal

import httpx
import pytest

from ingestion import emendas_mg as em

MONTE_SIAO_CNPJ = "22646525000131"          # conferido no BrasilAPI em 24/09/2026
# Todas as colunas medidas, na ordem do arquivo; o teste só preenche as nossas.
CABECALHO = (
    "numero_indicacao;tipo_inciso;numero_inciso;ano_exercicio;indicador_impositividade;uo;"
    "uo_sigla;uo_descricao;responsavel;id_tipo_indicacao;tipo_indicacao;numero_prioridade;"
    "id_status_indicacao;status_indicacao;municipio;municipio_ibge;codigo_escola;"
    "beneficiario_nome;beneficiario_cnpj;beneficiario_tipo;acao_numero;acao_nome;"
    "grupo_despesa_codigo;grupo_despesa_nome;funcao_codigo;funcao_descricao;minimo;"
    "genero_descricao;categoria_descricao;especificacao_descricao;tipo_aplicacao_grupo;"
    "tipo_aplicacao_descricao;descricao_indicacao;funcional_programatica;"
    "status_transparencia_id;valor_indicacao;valor_utilizado;valor_empenhado;"
    "valor_liquidado;valor_executado;valor_pago;proposta_numero;proposta_ano;"
    "proposta_titulo;plano_numero;plano_ano;plano_titulo;instrumento_numero;"
    "instrumento_titulo;instrumento_situacao;status_instrumento;numero_siafi;"
    "data_publicacao;data_validade;status_transparencia_descricao").split(";")


def _linha(nr, ibge="3143401,0", municipio="MONTE SIÃO", tipo="TRANSFERÊNCIA ESPECIAL",
           tipo_benef="MUNICÍPIO", benef="MUNICIPIO DE MONTE SIAO",
           cnpj=MONTE_SIAO_CNPJ + ",0", pago="140000,0", **extra):
    v = {"numero_indicacao": str(nr), "ano_exercicio": "2025", "uo": "1491",
         "uo_sigla": "SEGOV", "responsavel": "FULANO", "tipo_indicacao": tipo,
         "status_indicacao": "APROVADO", "municipio": municipio, "municipio_ibge": ibge,
         "beneficiario_nome": benef, "beneficiario_cnpj": cnpj,
         "beneficiario_tipo": tipo_benef, "grupo_despesa_nome": "INVESTIMENTOS",
         "tipo_aplicacao_descricao": "", "valor_indicacao": "140000,0",
         "valor_empenhado": "140000,0", "valor_liquidado": "140000,0", "valor_pago": pago,
         "instrumento_numero": "", "numero_siafi": "1512345,0",
         "status_instrumento": "REGISTRADO NO SIAFI", **extra}
    return ";".join(v.get(c, "") for c in CABECALHO)


def _csv(linhas: list[str], cabecalho=CABECALHO) -> bytes:
    return ("﻿" + ";".join(cabecalho) + "\n" + "\n".join(linhas) + "\n").encode("utf-8")


def test_le_ibge_e_cnpj_exportados_como_float_e_zero_como_zero():
    x, = em.ler_csv(_csv([_linha(112572, pago="0,0")]))
    assert x["nr"] == "112572" and x["ibge"] == "3143401" and x["ano"] == 2025
    assert x["cnpj"] == MONTE_SIAO_CNPJ
    assert x["valor_pago"] == Decimal("0")                 # zero AFIRMADO, não vazio
    assert x["valor_indicacao"] == Decimal("140000")
    assert x["tipo_atendimento"] is None and x["instrumento"] is None   # "" = vazio
    assert x["valor_resto_saldo"] is None                  # coluna que o CSV não tem
    assert x["extras"] == {"numero_siafi": "1512345",
                           "status_instrumento": "REGISTRADO NO SIAFI"}


@pytest.mark.parametrize("extra,objeto", [
    # TE: o plano de trabalho diz para que é o dinheiro (a TE não vira convênio).
    ({"plano_titulo": "COBERTURA DA QUADRA", "proposta_titulo": "COBERTURA E FECHAMENTO",
      "descricao_indicacao": ""}, "COBERTURA DA QUADRA"),
    ({"proposta_titulo": "COBERTURA E FECHAMENTO"}, "COBERTURA E FECHAMENTO"),
    # Resolução SES / doação de bens: só a descrição.
    ({"descricao_indicacao": "DOAÇÃO DE KIT FEIRA LIVRE"}, "DOAÇÃO DE KIT FEIRA LIVRE"),
    ({}, None),
])
def test_objeto_pelo_plano_pela_proposta_ou_pela_descricao(extra, objeto):
    x, = em.ler_csv(_csv([_linha(1, **extra)]))
    assert x["objeto"] == objeto


def test_fase_do_plano_e_a_situacao_do_instrumento():
    x, = em.ler_csv(_csv([_linha(1, status_instrumento="ADEQUAÇÃO")]))
    assert x["fase_plano"] == "ADEQUAÇÃO"
    x, = em.ler_csv(_csv([_linha(1, status_instrumento="")]))
    assert x["fase_plano"] is None


def test_objeto_e_fase_sao_da_segov_mesmo_na_linha_do_sigcon():
    """O SIGCON não tem os dois: a fonte grava sempre (armadilha 8), e um CSV sem
    objeto não apaga o que já estava."""
    sql = " ".join(em._SQL.split())
    assert "objeto = COALESCE(EXCLUDED.objeto, emendas_estaduais.objeto)" in sql
    assert "fase_plano = EXCLUDED.fase_plano" in sql
    assert "fase_plano = EXCLUDED.fase_plano" in " ".join(em._SQL_OUTROS.split())


def test_caixa_escolar_sem_ibge_e_cnpj_que_perdeu_o_zero():
    x, = em.ler_csv(_csv([_linha(23899, ibge="", cnpj="1834744000174,0",
                                 tipo_benef="CAIXA ESCOLAR", benef="CX ESC FULANO")]))
    assert x["ibge"] is None and x["municipio"] == "MONTE SIÃO"
    assert x["cnpj"] == "01834744000174"                   # float perde o zero


def test_conta_da_resolucao_ses_vai_para_o_raw_sem_a_casa_decimal():
    """(instrumento = nº da Resolução, conta) liga o pagamento da SES-MG
    (`ses_mg_resolucoes.py`) à indicação — cada indicação tem conta própria."""
    cab = CABECALHO + ["conta"]
    linha = _linha(204322, tipo="RESOLUÇÃO SES", instrumento_numero="011058/2026") + ";26101,0"
    x, = em.ler_csv(_csv([linha], cabecalho=cab))
    assert x["instrumento"] == "011058/2026" and x["extras"]["conta"] == "26101"


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


def test_coluna_renomeada_e_recusada():
    ruim = [("valor_pago_total" if c == "valor_pago" else c) for c in CABECALHO]
    with pytest.raises(ValueError, match="layout medido"):
        em.ler_csv(_csv([_linha(1)], cabecalho=ruim))


def _pacote(url_final=em.RECURSO, last_modified="2026-09-23T17:40:31.639475"):
    base = "https://dados.mg.gov.br/dataset/x/resource"
    return {"result": {"resources": [
        {"url": f"{base}/a/download/execucao2026.csv", "last_modified": "2026-09-23T17:40:00"},
        {"url": f"{base}/b/download/{url_final}", "last_modified": last_modified}]}}


def test_recurso_pelo_nome_do_arquivo_e_data_do_ckan():
    url, em_ = em.recurso(_pacote())
    assert url.endswith("/b/download/" + em.RECURSO)
    assert em_ == date(2026, 9, 23)
    with pytest.raises(ValueError, match="sumiu"):
        em.recurso(_pacote(url_final="outro.csv"))


@pytest.mark.parametrize("linha,cnpj_pref,esperado", [
    ({"tipo_beneficiario": "MUNICÍPIO"}, None, True),
    ({"tipo_beneficiario": "FUNDO MUNICIPAL DE SAÚDE"}, None, True),
    ({"tipo_beneficiario": "FUNDO MUNICIPAL DE ASSISTÊNCIA SOCIAL"}, None, True),
    ({"tipo_beneficiario": "ORGANIZAÇÃO DA SOCIEDADE CIVIL"}, None, False),
    ({"tipo_beneficiario": "Caixa Escolar"}, None, False),
    ({"tipo_beneficiario": "ÓRGÃOS OU ENTIDADES PÚBLICAS"}, None, False),
    # Sem o tipo: pelo nome...
    ({"beneficiario": "FUNDO MUNICIPAL DE SAÚDE DE UBÁ"}, None, True),
    ({"beneficiario": "APAE DE UBA"}, None, False),
    # ...ou pelo CNPJ da prefeitura, que vale sempre.
    ({"beneficiario": "PMMS", "cnpj": MONTE_SIAO_CNPJ}, MONTE_SIAO_CNPJ, True),
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


def _cliente(csv_: bytes | int, pacote: dict | int | list | None = None, urls=None):
    """`pacote` pode ser uma LISTA de respostas, uma por tentativa (502, 502, 200...)."""
    fila = list(pacote) if isinstance(pacote, list) else None

    def responde(req):
        if urls is not None:
            urls.append(str(req.url))
        if "package_show" in str(req.url):
            v = (fila.pop(0) if fila else _pacote()) if fila is not None else (
                _pacote() if pacote is None else pacote)
            return httpx.Response(v) if isinstance(v, int) else httpx.Response(200, json=v)
        assert req.headers["user-agent"].startswith("Mozilla/5.0 (Windows")
        if isinstance(csv_, int):
            return httpx.Response(csv_)
        return httpx.Response(200, content=csv_,
                              headers={"last-modified": "Wed, 23 Sep 2026 17:40:13 GMT"})
    return httpx.Client(transport=httpx.MockTransport(responde))


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    monkeypatch.setattr(em, "ESPERA_S", (0, 0))


ALVOS = [{"id": 7, "nome": "Monte Sião", "ibge": "3143401", "cnpj": MONTE_SIAO_CNPJ}]


def test_coletar_separa_municipal_de_entidade(monkeypatch):
    monkeypatch.setattr(em, "MIN_LINHAS", 1)
    arq = _csv([
        _linha(1),
        _linha(2, tipo="RESOLUÇÃO SES", tipo_benef="ORGANIZAÇÃO DA SOCIEDADE CIVIL",
               benef="APAE DE MONTE SIAO", cnpj="99999999000199,0"),
        _linha(3, ibge="3106200,0", municipio="BELO HORIZONTE"),
        _linha(4, tipo="RESOLUÇÃO SES", tipo_benef="FUNDO MUNICIPAL DE SAÚDE",
               benef="FUNDO MUNICIPAL DE SAUDE DE MONTE SIAO", cnpj="11222333000144,0"),
        _linha(5, ibge="", tipo_benef="CAIXA ESCOLAR", benef="CX ESC FULANO", cnpj="")])
    with _cliente(arq) as cl:
        municipais, outros, falhas, data = em.coletar(cl, ALVOS)
    assert falhas == [] and data == date(2026, 9, 23)
    assert sorted(municipais) == [(7, "1"), (7, "4")]
    assert sorted(outros) == [(7, "2"), (7, "5")]       # caixa escolar casa pelo nome
    assert municipais[(7, "1")]["execucao_em"] == date(2026, 9, 23)
    assert '"numero_siafi": "1512345"' in municipais[(7, "1")]["raw"]


@pytest.mark.parametrize("csv_,pacote,motivo", [
    (b"", 403, "layout"),                    # CKAN barrou -> plano B -> arquivo vazio
    (500, None, "HTTPStatusError"),          # o arquivo não veio (nem nas tentativas)
    (None, None, "cortado"),                 # veio curto
])
def test_fonte_fora_do_ar_ou_cortada_vira_falha(monkeypatch, csv_, pacote, motivo):
    monkeypatch.setattr(em, "MIN_LINHAS", 5)
    with _cliente(_csv([_linha(1)]) if csv_ is None else csv_, pacote) as cl:
        municipais, outros, falhas, data = em.coletar(cl, ALVOS)
    assert municipais == {} and outros == {} and data is None
    assert len(falhas) == 1 and motivo in falhas[0]


def test_catalogo_fora_do_ar_baixa_pelo_endereco_conhecido(monkeypatch):
    """Armadilha 9: 502 no package_show em TODAS as tentativas — o arquivo vem pelo
    endereço conhecido e a data sai do Last-Modified dele."""
    monkeypatch.setattr(em, "MIN_LINHAS", 1)
    urls: list = []
    with _cliente(_csv([_linha(1)]), [502, 502, 504], urls) as cl:
        municipais, _, falhas, data = em.coletar(cl, ALVOS)
    assert falhas == [] and data == date(2026, 9, 23)
    assert list(municipais) == [(7, "1")]
    assert sum("package_show" in u for u in urls) == em.TENTATIVAS
    assert urls[-1] == em.RECURSO_URL_CONHECIDA


def test_catalogo_soluca_uma_vez_e_responde():
    urls: list = []
    with _cliente(_csv([_linha(1)] * 2), [502], urls) as cl:
        em.MIN_LINHAS, antes = 1, em.MIN_LINHAS
        try:
            _, _, falhas, data = em.coletar(cl, ALVOS)
        finally:
            em.MIN_LINHAS = antes
    assert falhas == [] and data == date(2026, 9, 23)
    assert sum("package_show" in u for u in urls) == 2        # 502 e depois 200
    assert "/b/download/" in urls[-1]                          # o do catálogo, não o conhecido


def test_4xx_nao_se_repete():
    urls: list = []
    with _cliente(404, None, urls) as cl:
        em.coletar(cl, ALVOS)
    assert sum("download" in u for u in urls) == 1


@pytest.mark.parametrize("cab,esperado", [
    ("Wed, 23 Sep 2026 17:40:13 GMT", date(2026, 9, 23)), ("", None), ("lixo", None), (None, None)])
def test_data_do_arquivo(cab, esperado):
    assert em.data_do_arquivo(cab) == esperado


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))


def test_so_apaga_entidade_com_o_arquivo_lido(monkeypatch):
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
