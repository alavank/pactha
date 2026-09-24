"""PDF «Relatório de Parlamentares»: a CIDADE no título, grande (24/09/2026).

Pedido da Laiza (Nova Serrana/MG): "no título eu gostaria que colocasse o nome da
cidade grande, porque se eu precisar imprimir consigo identificar de qual cidade
é". O subtítulo dizia "município: 2" — o ID interno. No mesmo dia o PDF passou ao
MODELO DA PLANILHA do cliente (ver `test_parlamentares_pdf_modelo.py`): a cidade
agora está no título de cada bloco ("RECURSOS PARA NOVA SERRANA – EMENDAS
INDICADAS POR ..."), a maior letra da folha.

Aqui o endpoint roda INTEIRO (sem Postgres): o banco falso só responde a leitura
do município, `listar`/`detalhe` são dublês, e o PDF gerado é lido de volta com
pypdf. O que se prova é o que sai no papel: o nome grande, o nome na linha de
filtros (sem o ID), o nome em toda folha, o nome no arquivo — e que os filtros
da tela (`anos`, `tipo`) chegam ao PDF.

Rodar:
    python -m pytest backend/tests/test_parlamentares_pdf_cidade.py -v
"""
import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pypdf import PdfReader

import routers.parlamentares as P
from routers import export_pdf

ADMIN = SimpleNamespace(id=1, name="Admin", allowed_telas=None, allowed_municipio_ids=None,
                        allowed_permissoes=None, role="super_admin")


class _Res:
    def __init__(self, v):
        self._v = v

    def scalar_one_or_none(self):
        return self._v


class _Db:
    """Só a leitura do município passa por aqui: `listar`/`detalhe` são dublês."""

    def __init__(self, mun):
        self.mun = mun
        self.consultas = 0

    async def execute(self, *a, **kw):
        self.consultas += 1
        return _Res(self.mun)


def _mun(nome="Nova Serrana", uf="MG", id=2):
    return SimpleNamespace(id=id, nome=nome, uf=uf)


PLANO = {
    "id": 91573, "municipio_id": 2, "municipio_nome": "Nova Serrana",
    "codigo": "09032026-091573", "emenda": "202641760002", "parlamentar": "Nikolas Ferreira",
    "objeto": "Custeio da saúde", "situacao": "CIENTE",
    "valor_total": 398000.0, "valor_custeio": 398000.0, "valor_investimento": 0.0,
    "execucao": "Pago em parte", "execucao_estado": "pago_parte",
    "execucao_consultada": True, "valor_empenhado": 398000.0, "valor_pago": 205066.16,
    "valor_a_pagar": 192933.84, "dt_ultimo_pagamento": "22/06/2026",
    "execucao_consultada_em": None, "fonte": "plano_acao",
}


@pytest.fixture
def chamadas(monkeypatch):
    """Dublês de `listar`/`detalhe` (o export os importa na hora da chamada) e
    trilha neutralizada. Guarda o que o export pediu, para provar os filtros."""
    reg: dict = {"listar": [], "detalhe": []}

    async def _listar(**kw):
        reg["listar"].append(kw)
        return {"items": [{
            "nome_display": "NIKOLAS FERREIRA", "total_lancamentos": 1,
            "valor_total": 398000.0, "por_fonte": {"plano_acao": 1},
            "municipios": ["Nova Serrana"]}]}

    async def _detalhe(**kw):
        reg["detalhe"].append(kw)
        return {"sigcon": [], "voluntarias": [], "emendas": [], "plano_acao": [dict(PLANO)],
                "pac": [], "fns": [], "emendas_federais": []}

    async def _nada(*a, **kw):
        reg.setdefault("trilha", []).append(kw)

    monkeypatch.setattr(P, "listar", _listar)
    monkeypatch.setattr(P, "detalhe", _detalhe)
    monkeypatch.setattr(export_pdf, "_registrar_export", _nada)
    return reg


def _gera(db, **kw):
    """Chamada DIRETA, como a dos testes de porta: o que não for passado chega
    como o objeto `Query(...)` — e o export tem de aguentar."""
    args = {"request": None, "municipio_id": 2, "q": None, "ano": None,
            "db": db, "current": ADMIN}
    args.update(kw)
    resp = asyncio.run(export_pdf.export_parlamentares_pdf(**args))
    corpo = b"".join(asyncio.run(_ler(resp)))
    pdf = PdfReader(BytesIO(corpo))
    texto = [p.extract_text() for p in pdf.pages]
    return resp, pdf, texto


async def _ler(resp):
    return [bytes(c) if not isinstance(c, bytes) else c async for c in resp.body_iterator]


def _plano(t: str) -> str:
    """Texto sem as quebras de linha das células (Paragraph quebra onde cabe)."""
    return " ".join(t.split())


def test_a_cidade_sai_no_titulo_e_o_id_sumiu(chamadas):
    _resp, _pdf, texto = _gera(_Db(_mun()), q="Nikolas")
    pag1 = _plano(texto[0])
    # O plano do dublê está pago EM PARTE: o título não pode dizer "PAGOS".
    assert "RECURSOS PARA NOVA SERRANA – EMENDAS INDICADAS POR NIKOLAS FERREIRA" in pag1
    assert "município: Nova Serrana/MG" in pag1
    assert "município: 2" not in pag1


def test_a_cidade_e_a_maior_letra_da_primeira_pagina(chamadas):
    """"Grande" é medido, não suposto: o título com a cidade é a maior letra da
    folha (16pt, o tamanho do título do modelo)."""
    _resp, pdf, _texto = _gera(_Db(_mun()))
    tamanhos: dict = {}

    def _visita(txt, cm, tm, fonte, tamanho):
        t = (txt or "").strip()
        if t:
            tamanhos[t] = max(tamanhos.get(t, 0), tamanho * (tm[0] or 1))

    pdf.pages[0].extract_text(visitor_text=_visita)
    maior = max(tamanhos, key=tamanhos.get)
    assert "NOVA SERRANA" in maior
    assert tamanhos[maior] >= 16
    assert tamanhos[maior] > max(v for k, v in tamanhos.items() if "NOVA SERRANA" not in k)


def test_toda_folha_diz_a_cidade_no_rodape(chamadas, monkeypatch):
    """Impressa, a 2ª folha em diante também precisa dizer de qual cidade é."""
    muitos = [dict(PLANO, id=i, codigo=f"P-{i}") for i in range(60)]

    async def _detalhe(**kw):
        return {"plano_acao": muitos}

    monkeypatch.setattr(P, "detalhe", _detalhe)
    _resp, pdf, texto = _gera(_Db(_mun()))
    assert len(pdf.pages) >= 2
    for i, t in enumerate(texto, 1):
        assert "NOVA SERRANA/MG" in t, f"folha {i} sem a cidade"
        assert f"pág. {i}" in t


def test_o_nome_da_cidade_vai_no_arquivo_e_no_titulo_do_documento(chamadas):
    resp, pdf, _texto = _gera(_Db(_mun()), q="Nikolas", anos=[2026])
    disp = resp.headers["content-disposition"]
    assert disp.endswith("filename=parlamentares_Nova_Serrana_Nikolas_2026.pdf")
    # A tela abre o PDF como blob: o que o usuário vê na aba é o /Title.
    assert pdf.metadata.title == "Relatório de Parlamentares — Nova Serrana/MG"
    assert chamadas["trilha"][0]["filtros"]["municipio"] == "Nova Serrana/MG"


def test_nome_com_acento_vira_arquivo_ascii(chamadas):
    resp, _pdf, texto = _gera(_Db(_mun(nome="São João del-Rei")), q="Zé & <Cia>")
    disp = resp.headers["content-disposition"]
    assert "parlamentares_Sao_Joao_del_Rei_Ze_Cia.pdf" in disp
    disp.encode("ascii")
    # E o "<"/"&" da busca não derruba o Paragraph: sai escrito.
    assert 'busca: "Zé & <Cia>"' in texto[0]
    assert "RECURSOS PARA SÃO JOÃO DEL-REI – EMENDAS INDICADAS POR" in _plano(texto[0])


def test_sem_uf_nao_imprime_barra_none(chamadas):
    _resp, pdf, texto = _gera(_Db(_mun(uf=None)))
    assert "RECURSOS PARA NOVA SERRANA – EMENDAS" in _plano(texto[0])
    assert "município: Nova Serrana" in texto[0]
    assert "None" not in texto[0] and "Nova Serrana/" not in texto[0]
    assert pdf.metadata.title == "Relatório de Parlamentares — Nova Serrana"


def test_sem_municipio_diz_todos_os_municipios(chamadas):
    """Só o super-admin chega aqui sem município (os demais levam 403 antes)."""
    db = _Db(None)
    resp, _pdf, texto = _gera(db, municipio_id=None)
    t = _plano(texto[0])
    assert "RECURSOS PARA TODOS OS MUNICÍPIOS – EMENDAS INDICADAS POR NIKOLAS FERREIRA" in t
    assert "TOTAL GERAL – TODOS OS MUNICÍPIOS" in t
    assert "município: Todos os municípios" in texto[0]
    assert "parlamentares_todos_os_municipios" in resp.headers["content-disposition"]
    assert db.consultas == 0          # nada a ler do município


def test_municipio_inexistente_e_404(chamadas):
    with pytest.raises(HTTPException) as e:
        _gera(_Db(None), municipio_id=999)
    assert e.value.status_code == 404
    assert chamadas["listar"] == []


def test_os_filtros_da_tela_chegam_ao_pdf(chamadas):
    """A aba sempre mandou `anos` (e o PDF ignorava) e não mandava `tipo`."""
    _resp, _pdf, texto = _gera(_Db(_mun()), anos=[2026], tipo="parlamentar")
    assert chamadas["listar"][0]["anos"] == [2026]
    assert chamadas["listar"][0]["tipo"] == "parlamentar"
    assert chamadas["detalhe"][0]["anos"] == [2026]
    assert "ano: 2026" in texto[0]
    assert "todos os anos" not in texto[0]


def test_chamada_direta_sem_anos_nem_tipo_nao_quebra(chamadas):
    """Sem `anos`/`tipo`, a chamada direta passa os objetos `Query` — o export
    normaliza para "todos os anos" e "parlamentar" (o padrão da tela)."""
    _resp, _pdf, texto = _gera(_Db(_mun()))
    assert chamadas["listar"][0]["anos"] is None
    assert chamadas["listar"][0]["tipo"] == "parlamentar"
    assert "todos os anos" in texto[0]


def test_a_transferencia_especial_sai_com_a_execucao_por_extenso(chamadas):
    """Pedido 2 da Laiza: "só tá na situação como CIENTE". No modelo novo a
    SITUAÇÃO ATUAL é a execução por extenso — e CIENTE (cadastro) não aparece
    como se fosse o estágio do dinheiro."""
    _resp, _pdf, texto = _gera(_Db(_mun()))
    t = _plano(" ".join(texto))
    assert ("Pago em parte: R$ 205.066,16 de R$ 398.000,00; "
            "último pagamento em 22/06/2026.") in t
    assert "CIENTE" not in t
    # Achado (a) da revisão do 97e4903: a legenda dizia «-» = "não consultado"
    # também do «Últ. pagamento» de plano CONSULTADO. Plano consultado não pode
    # ter "não consultad..." em lugar nenhum da folha.
    assert "não consultad" not in t.lower()
    assert "«-»" not in t
