"""Execução das emendas federais pela PLANILHA aberta da CGU (sem chave), 24/09/2026.

O zip sintético repete o formato medido em `EmendasParlamentares.zip`: CSV em
Latin-1, `;`, tudo entre aspas, valores com vírgula decimal.
"""
import io
import json
import zipfile
from decimal import Decimal

import httpx
import pytest

from ingestion import portal_transparencia as pt

CAB = [
    "Código da Emenda", "Ano da Emenda", "Tipo de Emenda", "Código do Autor da Emenda",
    "Nome do Autor da Emenda", "Número da emenda", "Localidade de aplicação do recurso",
    "Código Município IBGE", "Município", "Código UF IBGE", "UF", "Região",
    "Código Função", "Nome Função", "Código Subfunção", "Nome Subfunção",
    "Código Programa", "Nome Programa", "Código Ação", "Nome Ação",
    "Código Plano Orçamentário", "Nome Plano Orçamentário", "Valor Empenhado",
    "Valor Liquidado", "Valor Pago", "Valor Restos A Pagar Inscritos",
    "Valor Restos A Pagar Cancelados", "Valor Restos A Pagar Pagos",
]


def _linha(codigo, localidade="NOVA PALMA - RS", funcao="Saúde", acao="8581",
           emp="100000,00", pago="40000,00", resto_pago="0,00"):
    v = [codigo, codigo[:4], "Emenda Individual - Transferências Especiais", codigo[4:8],
         "HEITOR SCHUCH", codigo[8:], localidade, "4313102", "NOVA PALMA", "43", "RS",
         "Sul", "10", funcao, "301", "Atenção básica", "5119", "SAUDE", acao, "ACAO",
         "0000", "PO", emp, "0,00", pago, "0,00", "0,00", resto_pago]
    return ";".join(f'"{x}"' for x in v)


def _zip(linhas, cab=CAB, arquivo=pt.PLANILHA_ARQUIVO) -> bytes:
    texto = ";".join(f'"{c}"' for c in cab) + "\r\n" + "\r\n".join(linhas) + "\r\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(arquivo, texto.encode("latin-1"))
    return buf.getvalue()


def test_le_latin1_e_so_os_codigos_pedidos():
    linhas, n = pt.ler_planilha(_zip([_linha("202332980002"), _linha("202499990001")]),
                                {"202332980002"})
    assert n == 2
    assert list(linhas) == [("202332980002", "NOVA PALMA - RS", "Saúde", "Atenção básica")]
    x = linhas[("202332980002", "NOVA PALMA - RS", "Saúde", "Atenção básica")]
    assert x["valor_empenhado"] == Decimal("100000.00") and x["valor_pago"] == Decimal("40000.00")
    assert x["valor_liquidado"] == Decimal("0.00")        # zero AFIRMADO, não vazio
    assert x["ano"] == 2023 and x["autor"] == "3298" and x["numero_emenda"] == "0002"
    assert x["tipo_emenda"] == "Emenda Individual - Transferências Especiais"
    assert json.loads(x["raw_data"]) == {"fonte": "planilha_cgu", "linhas_somadas": 1}


def test_acoes_da_mesma_chave_sao_somadas_nao_sobrescritas():
    """A planilha desce a ação/PO; a tabela para em localidade x função x subfunção."""
    z = _zip([_linha("202332980002", acao="8581", emp="100000,00", pago="1.000,50"),
              _linha("202332980002", acao="2E89", emp="50000,00", pago="2.000,25"),
              _linha("202332980002", localidade="MÚLTIPLO", emp="7,00")])
    linhas, _ = pt.ler_planilha(z, {"202332980002"})
    assert len(linhas) == 2
    x = linhas[("202332980002", "NOVA PALMA - RS", "Saúde", "Atenção básica")]
    assert x["valor_empenhado"] == Decimal("150000.00")
    assert x["valor_pago"] == Decimal("3000.75")
    assert json.loads(x["raw_data"])["linhas_somadas"] == 2


def test_coluna_renomeada_recusa_a_planilha_inteira():
    cab = [c if c != "Valor Pago" else "Valor Pago Total" for c in CAB]
    with pytest.raises(ValueError, match="Valor Pago"):
        pt.ler_planilha(_zip([_linha("202332980002")], cab=cab), {"202332980002"})


def test_arquivo_ausente_no_zip_e_erro():
    with pytest.raises(ValueError, match="ausente"):
        pt.ler_planilha(_zip([], arquivo="Outro.csv"), {"x"})


class _Cur:
    """Cursor que responde as duas consultas da função e guarda o resto."""
    def __init__(self, codigos):
        self.codigos = codigos
        self.sql = []
        self._ult = None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sql.append((s, params))
        self._ult = s

    def executemany(self, sql, seq):
        for p in seq:
            self.execute(sql, p)

    def fetchall(self):
        if "FROM emendas_federais_consulta" in self._ult:
            return [(c,) for c in self.codigos]
        return []

    @property
    def connection(self):
        return None


class _Conn:
    def commit(self):
        pass


@pytest.fixture
def sem_fila(monkeypatch):
    monkeypatch.setattr(pt, "alvos", lambda cur: {"88488358000156": {}})
    monkeypatch.setattr(pt, "limpar_fila_orfa", lambda cur, c: 0)
    monkeypatch.setattr(pt, "semear_fila", lambda cur, c: 0)
    import psycopg2.extras
    monkeypatch.setattr(psycopg2.extras, "execute_batch",
                        lambda cur, sql, seq, page_size=100: cur.executemany(sql, seq))


def _cliente(conteudo, last_modified="Wed, 23 Sep 2026 20:18:10 GMT"):
    def responde(req):
        return httpx.Response(200, content=conteudo, headers={"last-modified": last_modified})
    return httpx.Client(transport=httpx.MockTransport(responde))


def test_planilha_cortada_nao_grava_nem_marca(sem_fila, monkeypatch):
    """Menos linhas que o mínimo = arquivo cortado: marcar "a CGU não conhece" em
    quem faltou seria afirmação falsa."""
    monkeypatch.setattr(pt, "PLANILHA_MIN_LINHAS", 5)
    cur = _Cur(["202332980002"])
    rel = pt.execucao_planilha(cur, _Conn(), _cliente(_zip([_linha("202332980002")])))
    assert "recusada" in rel["nota"]
    assert not any(s.startswith(("INSERT", "UPDATE", "DELETE")) for s, _ in cur.sql)


def test_grava_marca_e_nao_toca_no_rodizio_da_api(sem_fila, monkeypatch):
    monkeypatch.setattr(pt, "PLANILHA_MIN_LINHAS", 1)
    cur = _Cur(["202332980002", "201328590001"])      # o 2º é de 2013: a CGU não publica
    rel = pt.execucao_planilha(cur, _Conn(), _cliente(_zip([_linha("202332980002")])))
    assert rel["achou"] == 1 and rel["codigos"] == 2 and rel["gravadas"] == 1
    ins = [p for s, p in cur.sql if s.startswith("INSERT INTO emendas_federais_cgu")]
    assert [p["codigo_emenda"] for p in ins] == ["202332980002"]
    # A fatia antiga só sai se foi a PLANILHA que a gravou.
    dele = [s for s, _ in cur.sql if s.startswith("DELETE")]
    assert dele and all("raw_data->>'fonte' = 'planilha_cgu'" in s for s in dele)
    upd = [(s, p) for s, p in cur.sql if s.startswith("UPDATE emendas_federais_consulta")]
    assert len(upd) == 1
    s, p = upd[0]
    # ⚠️ `consultado_em` é o rodízio da API: carimbá-lo faria a API (onde há chave)
    # pular os códigos novos e nunca trazer a linha do tempo de documentos.
    assert "consultado_em" not in s
    assert "agregados_em = NOW()" in s
    # O que a API já achou nunca volta a "não achou" por aqui.
    assert "OR coalesce(achou_agregado, false)" in s
    assert p[0] == ["202332980002"]
    assert sorted(p[1]) == ["201328590001", "202332980002"]


def test_planilha_velha_vira_aviso(sem_fila, monkeypatch):
    monkeypatch.setattr(pt, "PLANILHA_MIN_LINHAS", 1)
    cur = _Cur(["202332980002"])
    rel = pt.execucao_planilha(cur, _Conn(), _cliente(
        _zip([_linha("202332980002")]), last_modified="Mon, 01 Jan 2024 00:00:00 GMT"))
    assert "defasada" in rel["nota"]


def test_sem_fila_nao_baixa_nada(sem_fila):
    def nao_pode(req):
        raise AssertionError("baixou a planilha sem código nenhum na fila")
    cur = _Cur([])
    with httpx.Client(transport=httpx.MockTransport(nao_pode)) as cl:
        rel = pt.execucao_planilha(cur, _Conn(), cl)
    assert rel["codigos"] == 0
