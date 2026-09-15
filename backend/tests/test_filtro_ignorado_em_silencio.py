"""A guarda contra o filtro que a fonte ignora em silêncio.

⚠️ O DEFEITO QUE ISTO PREVINE, medido em 07/09/2026 contra
`api-publica.transferegov.gestao.gov.br`: um parâmetro que a fonte **não
reconhece** não dá erro nenhum — ela devolve HTTP 200 com a base nacional
inteira, byte a byte igual a não ter filtrado.

    /parcerias/proposta?cd_ibge_recebedor=4313102 ......      11
    /parcerias/proposta?cd_ibge_recebedorX=4313102 .....  89.400   ← 200 OK
    /fundoafundo/programas-beneficiarios?parametro_que_nao_existe=xyz
                                                    ......  31.026   ← 200 OK

Os filtros que os quatro coletores usam **funcionam hoje** — cada um foi
conferido com um valor impossível, que devolve 0 e não tudo. O risco não é o
presente: é que o Obras.gov já renomeou TODOS os campos numa troca de host
(ver o cabeçalho de `ingestion/obrasgov.py`). Se isso acontecer aqui, sem a
guarda a rodada gravaria os 57.827 planos do Brasil como sendo do município da
vez — e gravaria em silêncio, com log de sucesso.

Por isso `buscar`/`_pub_todos` aceitam `teto_itens`: acima dele devolvem
`None`, que os coletores já tratam como "não consegui perguntar" e não como
ausência. Este teste trava as duas metades — a guarda existir, e ela estar
ligada em cada consulta que estabelece o vínculo município ↔ dado.
"""
import ast
import inspect
import os

from ingestion import faf_planos, parcerias, transferegov_te

# Envelope real das quatro APIs novas. `total_items` é o campo que denuncia:
# a primeira página parece normal, é o total que revela a carga nacional.
def _envelope(total: int) -> dict:
    return {"data": [{"x": 1}], "total_pages": 1, "total_items": total,
            "page_number": 1, "page_size": 200}


class _ClienteFalso:
    """Devolve sempre o mesmo envelope. Nenhuma rede é tocada."""

    def __init__(self, total: int):
        self.total = total
        self.chamadas = 0

    def get(self, *a, **kw):
        self.chamadas += 1
        return self

    status_code = 200

    def json(self):
        return _envelope(self.total)


def test_o_teto_barra_a_carga_nacional_do_faf(monkeypatch):
    """31.026 beneficiários para um teto de 500 não é resposta: é filtro caído."""
    cli = _ClienteFalso(31_026)
    assert faf_planos.buscar(cli, "programas-beneficiarios",
                             {"codigo_ibge_municipio_ente_beneficiario_programa": 4313102},
                             teto_itens=500) is None


def test_o_teto_barra_a_carga_nacional_das_parcerias():
    """89.400 propostas para um teto de 5.000: a fonte ignorou o `cd_ibge`."""
    cli = _ClienteFalso(89_400)
    assert parcerias.buscar(cli, "proposta", {"cd_ibge_recebedor": 4313102},
                            teto_itens=5000) is None


def test_dentro_do_teto_a_coleta_segue_normal():
    """⚠️ E a guarda não pode virar um freio: 11 propostas passam."""
    assert parcerias.buscar(_ClienteFalso(11), "proposta",
                            {"cd_ibge_recebedor": 4313102},
                            teto_itens=5000) == [{"x": 1}]
    assert faf_planos.buscar(_ClienteFalso(5), "programas-beneficiarios",
                             {"x": 1}, teto_itens=500) == [{"x": 1}]


def test_sem_teto_nada_muda():
    """Consulta que não estabelece vínculo territorial (por id do pai) segue
    sem guarda — passar um teto ali só criaria falso positivo."""
    assert parcerias.buscar(_ClienteFalso(89_400), "parceria",
                            {"id_proposta": 75376}) == [{"x": 1}]


# ---------------------------------------------------------------------------
# A segunda metade: a guarda existir não basta — ela tem de estar LIGADA na
# consulta que casa o município com o dado. Isto lê o código-fonte porque o
# defeito que se quer pegar é justamente alguém acrescentar uma consulta nova
# por IBGE/CNPJ e esquecer o teto.
# ---------------------------------------------------------------------------

# (módulo, função que busca, chave do filtro, nome legível)
VINCULOS = [
    (parcerias, "buscar", "cd_ibge_recebedor", "propostas por IBGE"),
    (parcerias, "buscar", "sg_uf_beneficiario_emenda", "emendas indicadas por UF"),
    (faf_planos, "buscar", "codigo_ibge_municipio_ente_beneficiario_programa",
     "beneficiários por IBGE"),
    (faf_planos, "buscar", "cnpj_ente_recebedor_plano_acao", "planos por CNPJ"),
    (transferegov_te, "_pub_todos", "cnpj_beneficiario", "beneficiário por CNPJ"),
    (transferegov_te, "_pub_todos", "id_beneficiario", "planos por beneficiário"),
]


def _chamadas_com_a_chave(fonte: str, funcao: str, chave: str) -> list[ast.Call]:
    achadas = []
    for no in ast.walk(ast.parse(fonte)):
        if not isinstance(no, ast.Call):
            continue
        alvo = no.func
        nome = getattr(alvo, "id", None) or getattr(alvo, "attr", None)
        if nome != funcao:
            continue
        # A chave aparece como literal dentro de um dict de parâmetros.
        if chave in ast.dump(no):
            achadas.append(no)
    return achadas


def test_toda_consulta_que_casa_municipio_passa_o_teto():
    """⚠️ ESTE É O TESTE QUE IMPORTA. Consulta nova por IBGE ou CNPJ sem
    `teto_itens` é exatamente o caminho pelo qual a carga nacional entraria."""
    faltando = []
    for mod, funcao, chave, rotulo in VINCULOS:
        fonte = inspect.getsource(mod)
        chamadas = _chamadas_com_a_chave(fonte, funcao, chave)
        assert chamadas, f"{rotulo}: a consulta sumiu de {mod.__name__}"
        for c in chamadas:
            if not any(k.arg == "teto_itens" for k in c.keywords):
                faltando.append(f"{mod.__name__}: {rotulo} ({chave})")
    assert not faltando, (
        "consulta que casa município com dado, sem guarda de teto:\n  "
        + "\n  ".join(faltando))


def test_as_tres_funcoes_de_busca_aceitam_o_teto():
    """Se alguém remover o parâmetro, o teste acima passaria vazio."""
    for mod, funcao in [(parcerias, "buscar"), (faf_planos, "buscar"),
                        (transferegov_te, "_pub_todos")]:
        sig = inspect.signature(getattr(mod, funcao))
        assert "teto_itens" in sig.parameters, f"{mod.__name__}.{funcao}"
        assert sig.parameters["teto_itens"].default is None, (
            f"{mod.__name__}.{funcao}: o teto tem de ser OPCIONAL — consulta "
            "por id do pai não deve ganhar guarda sem alguém pedir")


def test_a_guarda_registra_o_motivo_no_log():
    """Rodada que abortou por teto tem de dizer POR QUÊ. Uma coleta que some
    sem explicação é o defeito que a auditoria de 29/08 já pagou uma vez."""
    for mod in (parcerias, faf_planos, transferegov_te):
        fonte = inspect.getsource(mod)
        assert "seria carga nacional" in fonte, mod.__name__
