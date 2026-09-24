"""Emendas federais: recebido POR MUNICÍPIO e convênio gerado (planilhas da CGU, 24/09/2026)."""
import io
import zipfile
from datetime import date
from decimal import Decimal

import pytest

from ingestion import portal_transparencia as pt
from services.emendas_unificadas import totais

CAB_FAV = ["Código da Emenda", "Código do Autor da Emenda", "Nome do Autor da Emenda",
           "Número da emenda", "Tipo de Emenda", "Ano/Mês", "Código do Favorecido",
           "Favorecido", "Natureza Jurídica", "Tipo Favorecido", "UF Favorecido",
           "Município Favorecido", "Valor Recebido"]
CAB_CONV = ["Código da Emenda", "Código Função", "Nome Função", "Código Subfunção",
            "Nome Subfunção", "Localidade do gasto", "Tipo de Emenda",
            "Data Publicação Convênio", "Convenente", "Objeto Convênio", "Número Convênio",
            "Valor Convênio"]


def _fav(cod, mun="NOVA PALMA", uf="RS", mes="202606", doc="88488358000156",
         nome="MUNICIPIO DE NOVA PALMA", valor="382000,00"):
    return [cod, "3298", "HEITOR", "0002", "Individual", mes, doc, nome, "Município",
            "Pessoa Jurídica", uf, mun, valor]


def _conv(cod, loc="NOVA PALMA - RS", numero="823363", valor="438750,00"):
    return [cod, "15", "Urbanismo", "451", "Infra", loc, "Individual", "17/12/2015",
            "MUNICIPIO DE NOVA PALMA", "Pavimentação", numero, valor]


def _zip(favs, convs, cab_fav=CAB_FAV) -> bytes:
    def csv(cab, linhas):
        return ("\r\n".join(";".join(f'"{v}"' for v in ln) for ln in [cab] + linhas)
                + "\r\n").encode("latin-1")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(pt.PLANILHA_FAVORECIDOS, csv(cab_fav, favs))
        z.writestr(pt.PLANILHA_CONVENIOS, csv(CAB_CONV, convs))
    return buf.getvalue()


MUNS = {pt._chave_mun("Nova Palma", "RS"): 1, pt._chave_mun("Monte Sião", "MG"): 2}


def test_so_o_municipio_do_cliente_e_so_os_codigos_da_fila():
    favs, convs, nf, nc = pt.ler_vinculos(_zip(
        [_fav("201511170002"),
         _fav("201511170002", mun="TAPERA", doc="1", nome="MUNICIPIO DE TAPERA"),   # outro município
         _fav("999999999999"),                                                      # fora da fila
         _fav("201511170002", mun="MONTE SIÃO", uf="MG", doc="22646525000131")],   # acento e UF
        [_conv("201511170002"),
         _conv("201511170002", loc="TAPERA - RS", numero="822681"),
         _conv("201511170002", loc="MÚLTIPLO", numero="1"),
         _conv("201511170002", loc="SÃO PAULO (UF)", numero="2")]),
        {"201511170002"}, MUNS)
    assert (nf, nc) == (4, 4)
    assert sorted((k[0], k[3]) for k in favs) == [(1, "88488358000156"), (2, "22646525000131")]
    assert list(convs) == [(1, "201511170002", "823363")]
    c = convs[(1, "201511170002", "823363")]
    assert c["valor"] == Decimal("438750.00") and c["data"] == date(2015, 12, 17)


def test_nome_parecido_nao_casa():
    """Casa por IGUALDADE: "SANTA MARIA DO HERVAL" não é Santa Maria."""
    muns = {pt._chave_mun("Santa Maria", "RS"): 9}
    favs, _, _, _ = pt.ler_vinculos(_zip(
        [_fav("201511170002", mun="SANTA MARIA DO HERVAL")], []), {"201511170002"}, muns)
    assert favs == {}


def test_mesmo_mes_e_favorecido_em_duas_linhas_soma():
    favs, _, _, _ = pt.ler_vinculos(_zip(
        [_fav("201511170002", valor="100,00"), _fav("201511170002", valor="50,50")], []),
        {"201511170002"}, MUNS)
    (f,) = favs.values()
    assert f["valor"] == Decimal("150.50")


def test_coluna_renomeada_e_erro():
    cab = [c if c != "Valor Recebido" else "Valor" for c in CAB_FAV]
    with pytest.raises(ValueError, match="Valor Recebido"):
        pt.ler_vinculos(_zip([], [], cab_fav=cab), set(), MUNS)


class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchall(self):
        return [(1, "Nova Palma", "RS")]


class _Conn:
    def commit(self):
        pass


def test_arquivo_cortado_nao_apaga_nada(monkeypatch):
    monkeypatch.setattr(pt, "MIN_FAVORECIDOS", 10)
    cur = _Cur()
    with pytest.raises(ValueError, match="cortados"):
        pt.gravar_vinculos(cur, _Conn(), _zip([_fav("201511170002")], [_conv("201511170002")]),
                           {"201511170002"})
    assert not any(s.startswith("DELETE") for s, _ in cur.sql)


def _linha(cod, recebido, municipal=True):
    return {"codigo_emenda": cod, "recebido_municipio": recebido, "valor": 100.0,
            "municipal": municipal, "grupo": None, "origem": "federal",
            "execucao_consultada": True, "execucao": None, "impositiva": False,
            "origens": ["federal"]}


def test_recebido_soma_uma_vez_por_codigo():
    """A mesma emenda em duas linhas (prefeitura e hospital) tem UM recebido."""
    t = totais([_linha("A", 300.0), _linha("A", 300.0, municipal=False), _linha("B", 50.0),
                _linha("C", None)])
    assert t["recebido_municipio"] == 350.0


def test_o_recebido_esta_no_fim_do_select_sem_deslocar_os_indices():
    import inspect
    from routers import emendas_federais as rf
    fonte = inspect.getsource(rf)
    assert '"recebido_municipio": _f(x[25])' in fonte
    assert '"convenios_n": int(x[26] or 0)' in fonte
    assert "AS recebido_municipio" in rf._SQL_ITENS and "AS convenios_n" in rf._SQL_ITENS
